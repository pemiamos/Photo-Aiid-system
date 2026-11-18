"""Photo-Aiid-system · 本地视觉层（fastvec · ONNX 版）

替代 analyzer 里「每张图都调一次 LLM」的路径，给照片库一个便宜的第一层：

  classify(path)     人脸检测 + CLIP 零样本分类 → 粗类别 + 置信度
  embed(path)        512 维向量，用于语义搜索 / 相似图去重
  search(query)      文本编码一次 + 全库内积，毫秒级

设计取舍（都是实测出来的，不是拍脑袋）：
  * 不装 torch：onnxruntime 15MB vs torch cu124 2.5GB，本机网络装不上后者
  * 人脸检测用 YuNet（227KB）：CLIP 只回答"画面里有什么"，不回答"拍的是谁"，
    "人站在石碑前"必被判建筑 —— 只能靠专用检测器兜住
  * 人脸置信度 0.8 是实测的真假分离点（真人脸 0.85~0.90，猫脸/纹理误检 0.59~0.65）
  * 文本侧必须乘 logit_scale=100：CLIP 文本嵌入聚在窄锥内（任意两句余弦 0.85~0.94），
    类间真实差异只有 0.19~0.25，不乘温度直接归一化会让所有概率挤在 1/C 附近
  * 阈值以上的低置信（<0.5）才送 LLM：实测占 20~32%
"""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# ── 模型路径（可用环境变量覆盖）────────────────────────────
_MODEL_DIR = Path(os.environ.get(
    "PHOTO_AIID_MODELS",
    str(Path(__file__).resolve().parent.parent / "models"),
))
VISION_MODEL = _MODEL_DIR / "vision_model_quantized.onnx"
TEXT_MODEL = _MODEL_DIR / "text_model_quantized.onnx"
TOKENIZER = _MODEL_DIR / "tokenizer.json"
FACE_MODEL = _MODEL_DIR / "face_detection_yunet.onnx"

# CLIP 图像预处理常量（OpenAI CLIP 官方）
_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
_STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)
_SIZE = 224
_LOGIT_SCALE = 100.0

# 类别词表：这是本方案真正的"参数"。每条锚描述越具体，零样本精度越高
# （实测：把 "a photo of a bird" 换成 "close-up ... with feathers and beak"，
#   宝塔照从「鸟类 0.66」变「建筑 0.72」，跑步照从「鸟类 0.43」变「人像 0.56」）
CLASSES: list[tuple[str, list[str]]] = [
    ("自然风光", ["a landscape photo of mountains, hills or sky",
                  "a scenic view of nature, fields or wilderness"]),
    ("人像",     ["a portrait photo of a person looking at the camera",
                  "a person standing in the frame, full body"]),
    ("鸟类",     ["a close-up photo of a bird with feathers and beak",
                  "a bird perched or flying, its body clearly visible"]),
    ("哺乳动物", ["a close-up photo of a cat, dog or other furry mammal",
                  "a pet or wild mammal resting"]),
    ("昆虫",     ["a macro photo of an insect, bug or butterfly"]),
    ("花卉植物", ["a close-up photo of flowers in bloom",
                  "a photo of plants, leaves or blossoms"]),
    ("美食",     ["a photo of a plated meal or dish of food"]),
    ("建筑",     ["a photo of a building exterior or architecture",
                  "a photo of a tower, temple or house"]),
    ("街景",     ["a street scene with road, pedestrians or traffic"]),
    ("水面",     ["a photo of a river, lake, sea or waterfall",
                  "water surface with reflections or waves"]),
    ("交通工具", ["a photo of a train, car, boat or aircraft",
                  "a cable car or tram on tracks"]),
    ("文档截图", ["a screenshot of a computer screen or phone app",
                  "a scanned document page with text"]),
]
ZH = [c[0] for c in CLASSES]
PORTRAIT = "人像"

# 实测阈值
FACE_SCORE_MIN = 0.80      # 人脸置信度：真人脸 >=0.85，假阳性 <=0.65
FACE_AREA_MIN = 0.002      # 人脸面积占画面比：1/500
LOW_CONF = 0.50            # 低于此值才值得送 LLM 复核
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}


@dataclass
class Item:
    """单张照片的视觉分析结果。"""
    path: str
    category: str = ""
    conf: float = 0.0
    top: list[dict] = field(default_factory=list)   # [{cls, sim, p}, ...]
    faces: int = 0
    face_ratio: float = 0.0
    face_score: float = 0.0
    overridden: bool = False                        # 是否被人脸覆盖
    low_conf: bool = False                          # 是否建议送 LLM
    ms: float = 0.0

    def as_dict(self) -> dict:
        return {
            "path": self.path, "category": self.category, "conf": round(self.conf, 3),
            "top": self.top, "faces": self.faces,
            "face_ratio": round(self.face_ratio, 5), "face_score": round(self.face_score, 3),
            "overridden": self.overridden, "low_conf": self.low_conf, "ms": round(self.ms, 1),
        }


class FastVec:
    """进程内单例：模型只加载一次，文本侧类别嵌入只算一次。"""

    def __init__(self, db_path: str | Path | None = None, threads: int = 0):
        self.db_path = str(db_path or os.environ.get("PHOTO_AIID_FASTVEC_DB", "fastvec.db"))
        self._vis = None
        self._txt = None
        self._tok = None
        self._face = None
        self._text_emb: np.ndarray | None = None
        self._threads = threads
        self._init_db()

    # ── 加载 ────────────────────────────────────────────
    def _sess(self, path: Path):
        import onnxruntime as ort
        if not Path(path).exists():
            raise FileNotFoundError(f"模型缺失: {path}（首次使用需下载到 backend/models/）")
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if self._threads:
            so.intra_op_num_threads = self._threads
        return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])

    def load(self):
        if self._vis is not None:
            return
        import cv2
        from tokenizers import Tokenizer

        t0 = time.time()
        self._vis = self._sess(VISION_MODEL)
        self._txt = self._sess(TEXT_MODEL)
        self._tok = Tokenizer.from_file(str(TOKENIZER))
        self._tok.enable_truncation(max_length=77)
        self._tok.enable_padding(length=77, pad_id=0, pad_token="<|endoftext|>")
        if FACE_MODEL.exists():
            self._face = cv2.FaceDetectorYN.create(
                str(FACE_MODEL), "", (320, 320), 0.5, 0.3, 5000)
        self._text_emb = self._build_text_emb()
        self._load_ms = (time.time() - t0) * 1000

    def _build_text_emb(self) -> np.ndarray:
        texts, owner = [], []
        for ci, (_, anchors) in enumerate(CLASSES):
            for a in anchors:
                texts.append(a); owner.append(ci)
        owner = np.array(owner)
        enc = self._tok.encode_batch(texts)
        ids = np.array([e.ids for e in enc], np.int64)
        raw = self._txt.run(None, {"input_ids": ids})[0]
        raw = raw / np.maximum(np.linalg.norm(raw, axis=1, keepdims=True), 1e-9)
        T = np.zeros((len(CLASSES), raw.shape[1]), np.float32)
        for ci in range(len(CLASSES)):
            v = raw[owner == ci].mean(0)
            T[ci] = v / max(float(np.linalg.norm(v)), 1e-9)
        return T

    @property
    def load_ms(self) -> float:
        return getattr(self, "_load_ms", 0.0)

    # ── 编码 ────────────────────────────────────────────
    @staticmethod
    def _prep(img, size: int = _SIZE) -> np.ndarray:
        from PIL import Image
        w, h = img.size
        s = size / min(w, h)
        img = img.resize((max(size, int(round(w * s))), max(size, int(round(h * s)))), Image.BICUBIC)
        w, h = img.size
        l, t = (w - size) // 2, (h - size) // 2
        a = np.asarray(img.crop((l, t, l + size, t + size)), np.float32) / 255.0
        return ((a - _MEAN) / _STD).transpose(2, 0, 1)

    def embed_images(self, imgs: list, batch: int = 16) -> np.ndarray:
        self.load()
        out = []
        for i in range(0, len(imgs), batch):
            arr = np.stack([self._prep(im) for im in imgs[i:i + batch]]).astype(np.float32)
            out.append(self._vis.run(None, {"pixel_values": arr})[0])
        if not out:
            return np.zeros((0, 512), np.float32)
        E = np.concatenate(out)
        return E / np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9)

    def encode_text(self, texts: list[str]) -> np.ndarray:
        self.load()
        enc = self._tok.encode_batch(list(texts))
        ids = np.array([e.ids for e in enc], np.int64)
        E = self._txt.run(None, {"input_ids": ids})[0]
        return E / np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9)

    # ── 人脸 ────────────────────────────────────────────
    def detect_face_img(self, pil_img) -> tuple[int, float, float]:
        """在已解码的 PIL 图上检测人脸。避免为检测再读一次盘——解码是最大瓶颈。"""
        if self._face is None:
            return 0, 0.0, 0.0
        import cv2
        import numpy as np
        try:
            arr = np.asarray(pil_img)
            if arr.ndim != 3:
                return 0, 0.0, 0.0
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            h, w = bgr.shape[:2]
            s = 640 / max(h, w)
            if s < 0.98:
                bgr = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
            h, w = bgr.shape[:2]
            self._face.setInputSize((w, h))
            _, det = self._face.detect(bgr)
            if det is None or len(det) == 0:
                return 0, 0.0, 0.0
            areas = det[:, 2] * det[:, 3] / (w * h)
            k = int(np.argmax(areas))
            return len(det), float(areas[k]), float(det[k, 14])
        except Exception:
            return 0, 0.0, 0.0

    def detect_face(self, path: str) -> tuple[int, float, float]:
        """返回 (脸数, 最大脸面积比, 该脸置信度)。1/8 尺寸直读，只在只需人脸时用。"""
        if self._face is None:
            return 0, 0.0, 0.0
        import cv2
        import numpy as np
        try:
            bgr = cv2.imread(path, cv2.IMREAD_REDUCED_COLOR_8)
            if bgr is None:
                return 0, 0.0, 0.0
            h, w = bgr.shape[:2]
            s = 640 / max(h, w)
            if s < 1:
                bgr = cv2.resize(bgr, (int(w * s), int(h * s)))
            h, w = bgr.shape[:2]
            self._face.setInputSize((w, h))
            _, det = self._face.detect(bgr)
            if det is None or len(det) == 0:
                return 0, 0.0, 0.0
            areas = det[:, 2] * det[:, 3] / (w * h)
            k = int(np.argmax(areas))
            return len(det), float(areas[k]), float(det[k, 14])
        except Exception:
            return 0, 0.0, 0.0

    # ── 主流程 ──────────────────────────────────────────
    def analyze(self, path: str) -> Item:
        """单张：人脸检测 + CLIP 分类 + 融合。"""
        import cv2
        from PIL import Image

        t0 = time.time()
        it = Item(path=path)

        n, ratio, score = self.detect_face(path)
        it.faces, it.face_ratio, it.face_score = n, ratio, score

        try:
            with Image.open(path) as im:
                try:
                    im.draft("RGB", (512, 512))
                except Exception:
                    pass
                img = im.convert("RGB")
        except Exception:
            img = Image.new("RGB", (224, 224), (128, 128, 128))

        E = self.embed_images([img])
        S = (E @ self._text_emb.T)[0]
        lg = _LOGIT_SCALE * S
        P = np.exp(lg - lg.max()); P /= P.sum()
        order = np.argsort(-S)
        it.top = [{"cls": ZH[j], "sim": round(float(S[j]), 4), "p": round(float(P[j]), 3)}
                  for j in order[:3]]

        # 融合：人脸优先于场景分类。CLIP 回答的是"画面里有什么"，
        # 人脸检测回答的是"拍的是谁"—— 后者才是人像照的判据。
        clip_top = ZH[order[0]]
        clip_p = float(P[order[0]])
        is_portrait = (n > 0 and ratio >= FACE_AREA_MIN and score >= FACE_SCORE_MIN)
        if is_portrait:
            it.category = PORTRAIT
            it.conf = score
            it.overridden = clip_top != PORTRAIT
        else:
            it.category = clip_top
            it.conf = clip_p
        it.low_conf = it.conf < LOW_CONF
        it.ms = (time.time() - t0) * 1000
        return it

    def analyze_batch(self, paths: list[str], batch: int = 16) -> tuple[list[Item], np.ndarray]:
        """批量：解码一次 → 人脸 + CLIP 共用同一张图。返回 (items, 向量矩阵)。

        关键：只 decode 一次。此前 cv2.imread 给检测 + PIL.open 给 CLIP 各解一次，
        24MP 的 JPEG 解码成本翻倍（实测 96ms/张 → 240ms/张）。
        """
        from PIL import Image
        self.load()
        items, imgs = [], []
        for p in paths:
            it = Item(path=p)
            try:
                with Image.open(p) as im:
                    try:
                        im.draft("RGB", (640, 640))   # 大图先按 DCT 尺度降采样解码
                    except Exception:
                        pass
                    img = im.convert("RGB")
            except Exception:
                img = Image.new("RGB", (224, 224), (128, 128, 128))
            imgs.append(img)
            n, ratio, score = self.detect_face_img(img)
            it.faces, it.face_ratio, it.face_score = n, ratio, score
            items.append(it)

        E = self.embed_images(imgs, batch=batch)
        S = E @ self._text_emb.T
        lg = _LOGIT_SCALE * S
        P = np.exp(lg - lg.max(1, keepdims=True))
        P /= P.sum(1, keepdims=True)
        order = np.argsort(-S, axis=1)

        for i, it in enumerate(items):
            it.top = [{"cls": ZH[j], "sim": round(float(S[i, j]), 4), "p": round(float(P[i, j]), 3)}
                      for j in order[i][:3]]
            clip_top, clip_p = ZH[order[i][0]], float(P[i, order[i][0]])
            is_portrait = (it.faces > 0 and it.face_ratio >= FACE_AREA_MIN
                           and it.face_score >= FACE_SCORE_MIN)
            if is_portrait:
                it.category, it.conf, it.overridden = PORTRAIT, it.face_score, clip_top != PORTRAIT
            else:
                it.category, it.conf = clip_top, clip_p
            it.low_conf = it.conf < LOW_CONF
        return items, E

    # ── 向量库 ──────────────────────────────────────────
    def _init_db(self):
        con = sqlite3.connect(self.db_path)
        con.executescript("""
        CREATE TABLE IF NOT EXISTS vec (
            path   TEXT PRIMARY KEY,
            mtime  REAL,
            dim    INTEGER,
            cat    TEXT,
            conf   REAL,
            low    INTEGER,
            vec    BLOB
        );
        CREATE INDEX IF NOT EXISTS idx_vec_cat ON vec(cat);
        """)
        # 迁移：打标字段（'' 未处理 | ok 已确认 | dup 标记为重复 | llm 已提交复核）
        cols = {r[1] for r in con.execute("PRAGMA table_info(vec)")}
        if "flag" not in cols:
            con.execute("ALTER TABLE vec ADD COLUMN flag TEXT DEFAULT ''")
        if "note" not in cols:
            con.execute("ALTER TABLE vec ADD COLUMN note TEXT DEFAULT ''")
        if "ts" not in cols:
            con.execute("ALTER TABLE vec ADD COLUMN ts REAL DEFAULT 0")
        con.execute("CREATE INDEX IF NOT EXISTS idx_vec_flag ON vec(flag)")
        con.commit()
        con.close()

    def set_flag(self, paths: list[str], flag: str, note: str = "") -> int:
        con = sqlite3.connect(self.db_path)
        try:
            con.executemany(
                "UPDATE vec SET flag=?, note=?, ts=? WHERE path=?",
                [(flag, note, time.time(), p) for p in paths])
            con.commit()
            return con.total_changes
        finally:
            con.close()

    def store(self, items: list[Item], vecs: np.ndarray):
        con = sqlite3.connect(self.db_path)
        rows = []
        for it, v in zip(items, vecs):
            try:
                m = os.path.getmtime(it.path)
            except OSError:
                m = 0.0
            rows.append((it.path, m, int(v.shape[0]), it.category, float(it.conf),
                         1 if it.low_conf else 0, np.asarray(v, np.float32).astype(np.float16).tobytes()))
        con.executemany(
            "INSERT INTO vec (path,mtime,dim,cat,conf,low,vec) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, cat=excluded.cat, "
            "conf=excluded.conf, low=excluded.low, vec=excluded.vec", rows)
        con.commit()
        con.close()
        return len(rows)

    def load_vecs(self) -> tuple[list[str], np.ndarray]:
        con = sqlite3.connect(self.db_path)
        rows = con.execute("SELECT path, dim, vec FROM vec").fetchall()
        con.close()
        if not rows:
            return [], np.zeros((0, 512), np.float16)
        dim = rows[0][1]
        M = np.zeros((len(rows), dim), np.float16)
        for i, (_, _, b) in enumerate(rows):
            M[i] = np.frombuffer(b, dtype=np.float16)
        return [r[0] for r in rows], M

    def search(self, query: str, k: int = 30, center: bool = False) -> list[tuple[str, float]]:
        """文本语义检索。

        注意：**调用方负责把中文查询转成英文**（见 services/zh_lexicon.py）。
        这里拿到什么文本就算什么——纯中文进来结果会很差，原因不是本函数：

          * CLIP ViT-B/32 的文本塔是英文训练的，中文只有 byte-level BPE 的字节模式
          * 实测：纯中文查询与英文基准 top10 重合 1%，中英混合 31%，纯英文 85%
          * 中英向量余弦其实有 0.88，但图文相似度的类间差异只有 0.02，
            而中英向量偏差 0.12 —— 偏差比信号大 6 倍，排序被打乱

        已排除的后处理因素：padding 方式（余弦差 0.0001）、文本/图像均值中心化
        （重叠反而 45%→90%），都不是这里能修的。

        center=True 会减去全库图像均值再算余弦；实测对本数据集更差，默认关闭。
        """
        q = self.encode_text([query])[0]
        paths, M = self.load_vecs()
        if not len(paths):
            return []
        M = M.astype(np.float32)
        if center:
            mu = M.mean(axis=0, keepdims=True)
            M = M - mu
            q = q - mu[0]
        q = q / max(float(np.linalg.norm(q)), 1e-9)
        M = M / np.maximum(np.linalg.norm(M, axis=1, keepdims=True), 1e-9)
        sims = M @ q
        idx = np.argsort(-sims)[:k]
        return [(paths[i], float(sims[i])) for i in idx]

    def search_similar(self, path: str, k: int = 30) -> list[tuple[str, float]]:
        """以图搜图 —— CLIP 真正可靠的部分。

        图像嵌入之间有真实结构（两两余弦 0.54~0.97，std 0.126），
        同一主体的照片会聚在一起。实测同一只猫的三张照片互为 top 命中。
        """
        paths, M = self.load_vecs()
        if not len(paths):
            return []
        try:
            i0 = paths.index(path)
        except ValueError:
            return []
        M = M.astype(np.float32)
        q = M[i0]
        q = q / max(float(np.linalg.norm(q)), 1e-9)
        M = M / np.maximum(np.linalg.norm(M, axis=1, keepdims=True), 1e-9)
        sims = M @ q
        order = np.argsort(-sims)
        out = []
        for i in order:
            if i == i0:
                continue
            out.append((paths[i], float(sims[i])))
            if len(out) >= k:
                break
        return out

    def stats(self) -> dict:
        con = sqlite3.connect(self.db_path)
        try:
            total = con.execute("SELECT COUNT(*) FROM vec").fetchone()[0]
            low = con.execute("SELECT COUNT(*) FROM vec WHERE low=1").fetchone()[0]
            cats = con.execute(
                "SELECT cat, COUNT(*) c FROM vec WHERE cat IS NOT NULL AND cat<>'' "
                "GROUP BY cat ORDER BY c DESC").fetchall()
            flags = con.execute(
                "SELECT COALESCE(NULLIF(flag,''),'none'), COUNT(*) FROM vec GROUP BY 1").fetchall()
        finally:
            con.close()
        return {
            "total": total, "low_conf": low,
            "categories": [{"cat": c, "n": n} for c, n in cats],
            "flag_counts": {(k or "none"): v for k, v in flags},
        }
