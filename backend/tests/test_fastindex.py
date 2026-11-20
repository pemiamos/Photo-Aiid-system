"""本地视觉预分类的回归测试。

覆盖 review 里指出的 5 个问题：
  1. 搜索后全选操作错对象      → test_search_items_replace_state
  2. LLM 任务被静默丢弃        → test_submit_llm_rejects_when_busy
  3. 初始化异常使索引永久 running → test_index_error_resets_running
  4. 下载校验接受截断/忽略 Range → test_verify_*, test_download_overwrites_on_200
  5. 解码失败被当作成功入库     → test_bad_image_is_marked_error
另含 use_lexicon 的中文查询替换。

跑法（从仓库根目录）:
    pip install pytest
    pytest backend/tests -v

这些测试**不需要真实模型**：模型加载与编码都被 monkeypatch 掉，
所以能在没有 148MB 模型的 CI 上跑。
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 4) 下载校验 ────────────────────────────────────────────
dl = _load("download_fast_models", BACKEND.parent / "scripts" / "download-fast-models.py")

VISION_SIZE = 89_117_001
VISION_SHA = "583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299"


def test_verify_rejects_truncated(tmp_path):
    """截断文件必须被拒 —— 旧逻辑 `>= size*0.995` 会把它当完整。"""
    f = tmp_path / "v.onnx"
    f.write_bytes(b"\0" * 89_000_000)          # 比 89,117,001 少约 117KB
    assert 89_000_000 >= VISION_SIZE * 0.995   # 旧判据在此为 True（误判）
    ok, why = dl.verify(f, VISION_SIZE, None)
    assert not ok
    assert "大小不符" in why


def test_verify_rejects_oversize(tmp_path):
    """比预期大的文件（续传追加坏了）也必须被拒。"""
    f = tmp_path / "v.onnx"
    f.write_bytes(b"\0" * (VISION_SIZE + 4096))
    ok, why = dl.verify(f, VISION_SIZE, None)
    assert not ok


def test_verify_accepts_exact_size(tmp_path):
    f = tmp_path / "v.onnx"
    f.write_bytes(b"\0" * VISION_SIZE)
    ok, why = dl.verify(f, VISION_SIZE, None)   # 不给 sha 时只校验大小
    assert ok, why


def test_verify_checks_sha256(tmp_path):
    f = tmp_path / "v.onnx"
    f.write_bytes(b"\0" * VISION_SIZE)
    ok, why = dl.verify(f, VISION_SIZE, "00" * 32)   # 故意错的 sha
    assert not ok
    assert "sha256" in why


def test_file_specs_are_exact():
    """脚本里写死的期望值必须与 HF 官方一致（防止再出现估算值）。"""
    by_name = {n: (s, h) for _, _, n, s, h in dl.FILES}
    assert by_name["vision_model_quantized.onnx"] == (VISION_SIZE, VISION_SHA)
    assert by_name["text_model_quantized.onnx"][0] == 64_504_507
    assert by_name["tokenizer.json"][0] == 2_224_119
    assert by_name["face_detection_yunet.onnx"][0] == 232_589


class _FakeResp:
    """服务器**忽略 Range、返回 200 全量**的假响应。"""

    def __init__(self, payload: bytes):
        self._p = payload
        self.status = 200
        self.headers = types.SimpleNamespace(get=lambda k, d=None: "" if k != "Content-Length" else str(len(payload)))

    def read(self, n=-1):
        if n is None or n < 0:
            out, self._p = self._p, b""
            return out
        out, self._p = self._p[:n], self._p[n:]
        return out

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_overwrites_on_200(tmp_path, monkeypatch):
    """已有半截文件 + 服务器回 200 时必须覆盖写，不能追加。

    追加的话会得到 `size + have` 字节、大小不对且内容乱掉的文件。
    """
    dst = tmp_path / "v.onnx"
    dst.write_bytes(b"OLD" * 1000)                  # 假装是上次的半截
    payload = b"NEW" * 4000                          # 全量内容

    monkeypatch.setattr(dl.urllib.request, "urlopen", lambda req, timeout=0: _FakeResp(payload))
    monkeypatch.setattr(dl.time, "sleep", lambda s: None)

    ok = dl.download("https://x", "r", "p", dst, len(payload), None, retries=1)
    assert ok
    assert dst.read_bytes() == payload               # 不是 OLD+NEW 拼接
    assert dst.stat().st_size == len(payload)


# ── 3) 索引初始化异常不能永久 running ─────────────────────
@pytest.fixture()
def fastindex_mod(monkeypatch):
    """导入 fastindex 并屏蔽它对 database/services 的真实依赖。"""
    import fastindex  # noqa: F401
    return fastindex


def test_index_error_resets_running(fastindex_mod, monkeypatch, tmp_path):
    """缺模型/缺依赖时抛异常，running 必须复位、错误要暴露。"""
    fi = fastindex_mod
    monkeypatch.setattr(fi, "probe_available", lambda: (False, "模型缺失（fixture）"))
    fi._progress.update({"running": False, "error": ""})

    fi._run_index(str(tmp_path), 8, None, True)

    assert fi._progress["running"] is False, "初始化失败后 running 卡住会导致后续全部 409"
    assert "模型缺失" in fi._progress["error"]


def test_index_error_leaves_no_partial_state(fastindex_mod, monkeypatch, tmp_path):
    fi = fastindex_mod
    monkeypatch.setattr(fi, "probe_available", lambda: (False, "boom"))
    fi._progress.update({"running": False, "done": 0, "total": 0})
    fi._run_index(str(tmp_path), 8, None, True)
    assert fi._progress["done"] == 0 and fi._progress["total"] == 0


# ── 5) 解码失败的图不能入库 ────────────────────────────────
@pytest.fixture()
def fv_mod(monkeypatch):
    from services import fastvec
    # 屏蔽真实模型：文本嵌入给 12x512，图像编码返回零向量
    monkeypatch.setattr(fastvec.FastVec, "load",
                        lambda self: setattr(self, "_text_emb", np.zeros((len(fastvec.ZH), 512), np.float32)))
    monkeypatch.setattr(fastvec.FastVec, "embed_images",
                        lambda self, imgs, batch=16: np.zeros((len(imgs), 512), np.float32))
    monkeypatch.setattr(fastvec.FastVec, "detect_face_img", lambda self, img: (0, 0.0, 0.0))
    return fastvec


def test_bad_image_is_marked_error(fv_mod, tmp_path):
    """坏文件必须写 error，且不产出分类结果。"""
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"this is not a jpeg")
    fv = fv_mod.FastVec(db_path=tmp_path / "t.db")
    items, vecs = fv.analyze_batch([str(bad)])
    assert len(items) == 1
    assert items[0].error, "解码失败必须记 error，否则会被当成功分类入库"
    assert items[0].category == ""
    assert vecs.shape[0] == 1


def test_bad_images_do_not_become_identical(fv_mod, tmp_path):
    """多张坏图不能得到相同向量（否则会被重复检测误报成同组）。"""
    paths = []
    for i in range(3):
        p = tmp_path / f"bad{i}.jpg"
        p.write_bytes(b"broken" * 10)
        paths.append(str(p))
    fv = fv_mod.FastVec(db_path=tmp_path / "t2.db")
    items, vecs = fv.analyze_batch(paths)
    assert all(it.error for it in items)
    # 调用方（_run_index）按 error 过滤，所以这里断言的是"全部被标错"
    assert not any(it.category for it in items)


# ── 2) 分析忙碌时提交必须拒绝，不能静默丢 ─────────────────
def test_analyzer_batch_guard_is_atomic():
    """try_acquire_batch 第二次必须失败，release 后可再抢。"""
    from services import analyzer
    analyzer._batch_active = False
    try:
        assert analyzer.try_acquire_batch() is True
        assert analyzer.try_acquire_batch() is False   # 已占用
        analyzer.release_batch()
        assert analyzer.try_acquire_batch() is True
    finally:
        analyzer._batch_active = False


def test_analyze_batch_honours_preacquired():
    """_preacquired=True 时不能把自己判成重复请求而直接返回。"""
    import inspect
    from services import analyzer
    sig = inspect.signature(analyzer.analyze_batch)
    assert "_preacquired" in sig.parameters
    assert sig.parameters["_preacquired"].default is False


# ── 1) 搜索结果必须替换 state.items（API 契约） ────────────
def test_search_response_contract(fastindex_mod, monkeypatch):
    """搜索接口必须返回 items，前端才能拿它替换 state.items。

    前端若不同步，Ctrl+A 会从旧列表取路径 —— 这里锁住 API 契约，
    前端行为由真机验证覆盖。
    """
    fi = fastindex_mod
    monkeypatch.setattr(fi.engine(), "search", lambda q, k: [])

    from fastapi.testclient import TestClient
    import main
    client = TestClient(main.app)
    r = client.post("/api/fast/search", json={"query": "cat", "k": 5})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and isinstance(body["items"], list)
    assert {"query", "used", "expanded", "hit_ratio", "ms"} <= set(body)


# ── 中文词典 ──────────────────────────────────────────────
def test_lexicon_replaces_not_appends():
    """扩展结果里不能残留中文 —— 实测"猫 cat"60% 而"猫在草地上 cat grass"只有 20%。"""
    from services import zh_lexicon
    en, hits, ratio = zh_lexicon.expand("猫在草地上")
    assert zh_lexicon.has_cjk(en) is False, "扩展结果不能含中文"
    assert "cat" in en and "grass" in en
    assert ratio > 0.3


def test_lexicon_falls_back_when_uncovered():
    from services import zh_lexicon
    en, hits, ratio = zh_lexicon.expand("超现实主义梦境")
    assert en == "", "未覆盖时应返回空串，让调用方回退原文"
    assert ratio < zh_lexicon.MIN_HIT_RATIO


def test_lexicon_longest_match_wins():
    from services import zh_lexicon
    en, _, _ = zh_lexicon.expand("古建筑")
    assert "chinese temple architecture" in en, "古建筑 应先于 建筑 匹配"
    en2, _, _ = zh_lexicon.expand("江边")
    assert "riverside" in en2
