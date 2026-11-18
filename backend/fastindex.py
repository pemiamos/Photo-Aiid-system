"""Photo-Aiid-system · 本地视觉索引路由（fastindex）

给「上万张照片」加一层便宜的本地粗分类，不动原有画廊/AI 分析逻辑：

  POST /api/fast/index      对目录建/更新向量索引（后台，可看进度）
  GET  /api/fast/progress   进度
  GET  /api/fast/stats      分类分布 / 低置信数
  GET  /api/fast/items      结果列表（分页 + 类别/低置信筛选）
  POST /api/fast/search     语义搜索（文本编一次 + 全库内积）
  GET  /api/fast/thumb      按路径出缩略图（只允许已索引路径）
  GET  /api/fast/review     可视化验收页

设计原则：本模块只新增端点，不修改 main.py 里任何现有路由的行为。
"""
from __future__ import annotations

import asyncio
import mimetypes
import os
import time
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

import database as db
from services import fastvec as fv
from services import scanner

router = APIRouter(prefix="/api/fast", tags=["fast"])

_engine: fv.FastVec | None = None

# 全局进度（与 scanner/analyzer 同样的模式）
_progress: dict = {
    "running": False, "total": 0, "done": 0, "errors": 0,
    "current": "", "started_at": 0.0, "elapsed": 0.0,
    "ms_per_img": 0.0, "eta": None, "root": "",
}


def engine() -> fv.FastVec:
    global _engine
    if _engine is None:
        db_path = os.environ.get(
            "PHOTO_AIID_FASTVEC_DB",
            str(Path(__file__).resolve().parent / "fastvec.db"),
        )
        _engine = fv.FastVec(db_path=db_path)
    return _engine


def _collect(root: str, limit: int | None = None) -> list[str]:
    out: list[str] = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in files:
            if f.startswith("."):
                continue
            if Path(f).suffix.lower() in fv.IMG_EXT:
                out.append(os.path.join(dirpath, f))
    out.sort()
    return out[:limit] if limit else out


def _run_index(root: str, batch: int, limit: int | None, skip_indexed: bool):
    """同步执行（跑在线程里），边跑边更新 _progress。"""
    eng = engine()
    eng.load()
    paths = _collect(root, limit)
    if skip_indexed:
        done_paths, _ = eng.load_vecs()
        known = set(done_paths)
        paths = [p for p in paths if p not in known]

    _progress.update({
        "running": True, "total": len(paths), "done": 0, "errors": 0,
        "current": "", "started_at": time.time(), "elapsed": 0.0,
        "ms_per_img": 0.0, "eta": None, "root": root, "load_ms": eng.load_ms,
    })
    chunk = max(batch, 8)
    try:
        for i in range(0, len(paths), chunk):
            part = paths[i:i + chunk]
            _progress["current"] = os.path.basename(part[0])
            try:
                # analyze_batch 内部只解码/编码各一次，直接拿回向量入库
                items, vecs = eng.analyze_batch(part, batch=batch)
                eng.store(items, vecs)
                _progress["done"] += len(items)
            except Exception as e:
                _progress["errors"] += len(part)
                print(f"[fastindex] chunk 失败 {part[0]}: {e}", flush=True)

            el = time.time() - _progress["started_at"]
            _progress["elapsed"] = round(el, 1)
            d = max(_progress["done"], 1)
            _progress["ms_per_img"] = round(el / d * 1000, 1)
            left = _progress["total"] - _progress["done"]
            _progress["eta"] = round(el / d * left, 0) if left > 0 else 0
    finally:
        _progress["running"] = False
        _progress["current"] = ""


class IndexReq(BaseModel):
    root: str | None = None
    batch: int = 16
    limit: int | None = None
    skip_indexed: bool = True


@router.post("/index")
async def start_index(req: IndexReq):
    if _progress["running"]:
        raise HTTPException(409, "索引任务正在进行中")
    root = req.root
    if not root:
        s = await db.get_settings()
        root = s.get("last_folder", "")
    root = (root or "").strip()
    if not root or not os.path.isdir(root):
        raise HTTPException(400, f"目录不存在: {root!r}（请先在画廊里选文件夹，或传 root）")
    _progress.update({"running": True, "total": 0, "done": 0, "errors": 0, "root": root})
    asyncio.create_task(asyncio.to_thread(_run_index, root, req.batch, req.limit, req.skip_indexed))
    return {"ok": True, "root": root}


@router.get("/progress")
async def progress():
    return dict(_progress)


@router.get("/stats")
async def stats():
    st = engine().stats()
    st["progress"] = dict(_progress)
    st["models"] = {
        "vision": fv.VISION_MODEL.name, "text": fv.TEXT_MODEL.name,
        "face": fv.FACE_MODEL.name if fv.FACE_MODEL.exists() else None,
        "dir": str(fv._MODEL_DIR),
        "present": fv.VISION_MODEL.exists() and fv.TEXT_MODEL.exists(),
    }
    st["thresholds"] = {
        "face_score_min": fv.FACE_SCORE_MIN, "face_area_min": fv.FACE_AREA_MIN,
        "low_conf": fv.LOW_CONF, "classes": fv.ZH,
    }
    return st


@router.get("/items")
async def items(
    offset: int = Query(0, ge=0),
    limit: int = Query(120, ge=1, le=5000),
    cat: str | None = None,
    low: bool | None = None,
    flag: str | None = None,
):
    import sqlite3
    con = sqlite3.connect(engine().db_path)
    try:
        where, params = [], []
        if cat:
            where.append("cat = ?"); params.append(cat)
        if low is not None:
            where.append("low = ?"); params.append(1 if low else 0)
        if flag is not None:
            where.append("COALESCE(flag,'') = ?"); params.append(flag)
        w = ("WHERE " + " AND ".join(where)) if where else ""
        total = con.execute(f"SELECT COUNT(*) FROM vec {w}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT path, cat, conf, low, COALESCE(flag,''), COALESCE(note,'') "
            f"FROM vec {w} ORDER BY path LIMIT ? OFFSET ?",
            params + [limit, offset]).fetchall()
        # 空字符串不能当 JSON key（PowerShell 的 ConvertFrom-Json 会直接拒绝），用 none 占位
        counts = {(k or "none"): v for k, v in con.execute(
            "SELECT COALESCE(NULLIF(flag,''),'none'), COUNT(*) FROM vec GROUP BY 1").fetchall()}
    finally:
        con.close()
    return {
        "total": total, "offset": offset, "limit": limit, "flag_counts": counts,
        "items": [{"path": p, "name": os.path.basename(p), "cat": c,
                   "conf": round(cf or 0, 3), "low": bool(l), "flag": f, "note": n}
                  for p, c, cf, l, f, n in rows],
    }


class SearchReq(BaseModel):
    query: str
    k: int = 40


@router.post("/search")
async def search(req: SearchReq):
    """语义搜索。中文查询会先经内置词典替换成英文关键词。

    原因（实测）：CLIP ViT-B/32 的文本塔是英文训练的，纯中文查询与英文基准的
    top10 重合只有 1%，中英混合 31%，**完全替换成英文 85%**。中文 token 留在
    查询里会把英文淹掉（"猫 cat" 60%，"猫在草地上 cat grass" 只有 20%）。
    """
    from services import zh_lexicon

    t0 = time.time()
    q = req.query
    expanded, lex_hits, ratio = "", [], 0.0
    if zh_lexicon.has_cjk(req.query):
        expanded, lex_hits, ratio = zh_lexicon.expand(req.query)
        if expanded:
            q = expanded

    hits = await asyncio.to_thread(engine().search, q, req.k)
    import sqlite3
    con = sqlite3.connect(engine().db_path)
    out = []
    try:
        for p, s in hits:
            r = con.execute("SELECT cat, conf FROM vec WHERE path = ?", (p,)).fetchone()
            out.append({"path": p, "name": os.path.basename(p), "score": round(s, 4),
                        "cat": r[0] if r else "", "conf": round((r[1] or 0), 3) if r else 0})
    finally:
        con.close()
    return {
        "query": req.query, "used": q, "expanded": expanded,
        "lexicon": [{"zh": a, "en": b} for a, b in lex_hits],
        "hit_ratio": round(ratio, 2),
        "ms": round((time.time() - t0) * 1000, 1), "items": out,
    }


@router.get("/similar")
async def similar(path: str, k: int = 24):
    """以图搜图。CLIP 最可靠的部分（图像嵌入之间有真实结构）。"""
    t0 = time.time()
    hits = await asyncio.to_thread(engine().search_similar, path, k)
    import sqlite3
    con = sqlite3.connect(engine().db_path)
    out = []
    try:
        for p, s in hits:
            r = con.execute("SELECT cat, conf FROM vec WHERE path = ?", (p,)).fetchone()
            out.append({"path": p, "name": os.path.basename(p), "score": round(s, 4),
                        "cat": r[0] if r else ""})
    finally:
        con.close()
    return {"path": path, "ms": round((time.time() - t0) * 1000, 1), "items": out}


@router.get("/duplicates")
async def duplicates(thr: float = 0.97, max_pairs: int = 5000):
    """重复/近重复图检测，按「组」返回（并查集合并传递关系）。

    A≈B、B≈C 时 A/B/C 属同一组——直接列 pair 会让用户面对一堆交叉对，
    分组后每组只需决策一次「留哪张」。
    """
    t0 = time.time()
    paths, M = engine().load_vecs()
    if len(paths) < 2:
        return {"groups": [], "ms": 0, "scanned": len(paths)}
    import numpy as np
    M = M.astype(np.float32)
    M = M / np.maximum(np.linalg.norm(M, axis=1, keepdims=True), 1e-9)
    pairs: list[tuple[float, int, int]] = []
    B = 512
    for s in range(0, len(paths), B):
        blk = M[s:s + B] @ M.T
        ii, jj = np.where(blk >= thr)
        for a, b in zip(ii, jj):
            gi, gj = s + int(a), int(b)
            if gi < gj:
                pairs.append((float(blk[a, b]), gi, gj))
        if len(pairs) >= max_pairs:
            break

    # 并查集
    parent = list(range(len(paths)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _, a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    buckets: dict[int, list[int]] = {}
    for _, a, b in pairs:
        buckets.setdefault(find(a), set()).update((a, b))

    import os as _os
    groups = []
    for root_id, members in buckets.items():
        members = sorted(members)
        sims = [s for s, a, b in pairs if find(a) == root_id]
        groups.append({
            "id": root_id,
            "size": len(members),
            "min_score": round(min(sims), 4) if sims else 0.0,
            "files": [{"path": paths[i], "name": _os.path.basename(paths[i]),
                       "dir": _os.path.basename(_os.path.dirname(paths[i]))} for i in members],
        })
    groups.sort(key=lambda g: (-g["size"], -g["min_score"]))
    total_dup = sum(g["size"] - 1 for g in groups)
    return {
        "scanned": len(paths), "thr": thr, "pairs": len(pairs),
        "groups": groups, "redundant": total_dup,
        "ms": round((time.time() - t0) * 1000, 1),
    }


class FlagReq(BaseModel):
    paths: list[str]
    flag: str = "ok"          # '' 清除 | ok 已确认 | dup 标记为重复 | llm 已提交复核
    note: str = ""


@router.post("/flag")
async def set_flag(req: FlagReq):
    if req.flag not in ("", "ok", "dup", "llm"):
        raise HTTPException(400, "flag 只能是 '' / ok / dup / llm")
    n = engine().set_flag(req.paths, req.flag, req.note)
    return {"ok": True, "updated": n, "flag": req.flag}


class SubmitReq(BaseModel):
    paths: list[str]
    engine_name: str | None = None


@router.post("/submit-llm")
async def submit_llm(req: SubmitReq):
    """把选中的照片提交给 LLM 分析（复核低置信项）。

    fastvec 库独立于 photos 表，所以这里先按路径补齐 photos 记录
    （含一个扫描会话，供 analyzer 解析根目录），再走原有 analyze_batch。
    不修改 analyzer 任何逻辑。
    """
    import aiosqlite
    from pathlib import Path as _P
    from services import analyzer

    if not req.paths:
        raise HTTPException(400, "未选择照片")
    # 同一批必须同根目录（analyzer 用 scan_session 的 root_path 找缩略图）
    roots = {str(_P(p).parent.parent) for p in req.paths}
    root = sorted(roots)[0] if len(roots) == 1 else str(_P(req.paths[0]).parent)

    conn = await db.get_db()
    ids: list[int] = []
    try:
        rows = await conn.execute_fetchall("SELECT id, file_path FROM photos")
        known = {r["file_path"]: r["id"] for r in rows}
        sess = await conn.execute(
            "INSERT INTO scan_sessions (root_path, photo_count, status, created_at) "
            "VALUES (?, 0, 'running', ?)", (root, time.time()))
        session_id = sess.lastrowid
        for p in req.paths:
            if p in known:
                ids.append(known[p])
                continue
            st = _P(p).stat()
            rel = str(_P(p).relative_to(root)) if str(_P(p)).startswith(root) else _P(p).name
            cur = await conn.execute(
                "INSERT INTO photos (file_name, original_name, file_path, relative_path, "
                "file_size, file_mtime, scan_status, scan_session_id, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,'queued',?,?,?) "
                "ON CONFLICT(file_path) DO UPDATE SET scan_status='queued', updated_at=excluded.updated_at",
                (_P(p).name, _P(p).name, p, rel, st.st_size, st.st_mtime,
                 session_id, time.time(), time.time()))
            if cur.lastrowid:
                ids.append(cur.lastrowid)
        await conn.execute("UPDATE scan_sessions SET photo_count=?, status='completed' WHERE id=?",
                           (len(ids), session_id))
        await conn.commit()
    finally:
        await conn.close()

    if not ids:
        raise HTTPException(500, "无法建立照片记录")
    asyncio.create_task(analyzer.analyze_batch(photo_ids=ids, engine_name=req.engine_name))
    engine().set_flag(req.paths, "llm")
    return {"ok": True, "queued": len(ids), "engine": req.engine_name or "settings默认"}


@router.get("/thumb")
async def thumb(path: str, size: int = 320):
    """按路径出缩略图。只允许已索引过的路径（防止任意文件读取）。"""
    import sqlite3
    con = sqlite3.connect(engine().db_path)
    try:
        if not con.execute("SELECT 1 FROM vec WHERE path = ?", (path,)).fetchone():
            raise HTTPException(404, "未索引的路径")
    finally:
        con.close()
    if not os.path.exists(path):
        raise HTTPException(404, "文件已不存在")
    from PIL import Image
    try:
        with Image.open(path) as im:
            try:
                im.draft("RGB", (size, size))
            except Exception:
                pass
            im = im.convert("RGB")
            im.thumbnail((size, size), Image.Resampling.LANCZOS)
            buf = BytesIO()
            im.save(buf, "JPEG", quality=82)
        return Response(buf.getvalue(), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})
    except Exception as e:
        raise HTTPException(500, f"缩略图失败: {e}")


_REVIEW_PATH = Path(__file__).resolve().parent / "fast_review.html"


@router.get("/review", response_class=HTMLResponse)
async def review():
    """验收页（独立 HTML，按本机设计规范：OPPO Sans / MiSans + 统一令牌）。

    拆成文件而不是内嵌字符串：页面有 500+ 行 CSS/JS，内嵌在 Python 里无法维护。
    """
    if not _REVIEW_PATH.exists():
        raise HTTPException(500, f"页面文件缺失: {_REVIEW_PATH}")
    return _REVIEW_PATH.read_text(encoding="utf-8")


