"""
Photo-Aiid-system · 投稿征稿模块（M2 网页原型）

提供摄影师网页投稿的最小可用流程：
    投稿码校验 → 创建投稿会话 → 先拉入照片后标注 → 强制标注后上传 → 看板

原型存储：文件经后端保存到本地目录 INTAKE_DATA/{书}/{投稿码-姓名}/{标注}/{文件名}，
目录结构与未来阿里云 OSS 的 object key 一致；上线时把保存逻辑替换为 OSS 直传即可，
其余接口与数据模型不变。

注意：本模块只新增 photographers / submissions / submission_files 三张表，
不触碰现有 photos / ai_results 等表。
"""

import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, Form, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

import database as db

router = APIRouter()

INTAKE_DATA = Path(
    os.environ.get(
        "INTAKE_DATA",
        os.path.join(os.path.dirname(__file__), "intake_data"),
    )
).resolve()

_PAGE = os.path.join(os.path.dirname(__file__), "intake_page.html")

# 原型阶段的书目代号（正式版应支持多书目）
BOOK_CODE = os.environ.get("INTAKE_BOOK", "2026-sanxia")
BOOK_TITLE = os.environ.get("INTAKE_BOOK_TITLE", "三峡画册")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS photographers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    book_code   TEXT NOT NULL,
    invite_code TEXT NOT NULL UNIQUE,
    name        TEXT,
    contact     TEXT,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    photographer_id INTEGER NOT NULL,
    note            TEXT,
    license_agreed  INTEGER NOT NULL DEFAULT 0,
    license_at      REAL,
    status          TEXT NOT NULL DEFAULT 'open',
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS submission_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL,
    content_label TEXT NOT NULL,
    object_key    TEXT NOT NULL,
    file_name     TEXT NOT NULL,
    file_size     INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'done',
    created_at    REAL NOT NULL
);
"""


async def init_intake_db():
    """建投稿相关表，并种入 demo 投稿码（原型用）。"""
    conn = await db.get_db()
    try:
        await conn.executescript(_SCHEMA)
        # demo 种子：A03 王芳 故意不投稿，用于看板展示「未交」
        seed = [
            ("A01", "张伟", "13800000001"),
            ("A02", "李娜", "13800000002"),
            ("A03", "王芳", "13800000003"),
        ]
        now = time.time()
        for code, name, contact in seed:
            await conn.execute(
                "INSERT OR IGNORE INTO photographers "
                "(book_code, invite_code, name, contact, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (BOOK_CODE, code, name, contact, now),
            )
        await conn.commit()
    finally:
        await conn.close()


def _safe(part: str) -> str:
    """清洗路径片段，去掉分隔符与危险字符。"""
    part = (part or "").strip()
    part = re.sub(r"[\\/:*?\"<>|]", "_", part)
    part = part.replace("..", "_")
    return part or "未命名"


async def _get_photographer(code: str):
    conn = await db.get_db()
    try:
        row = await conn.execute_fetchall(
            "SELECT * FROM photographers WHERE invite_code = ? AND book_code = ?",
            (code, BOOK_CODE),
        )
        return dict(row[0]) if row else None
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 摄影师端接口
# ---------------------------------------------------------------------------

@router.get("/intake", response_class=HTMLResponse)
async def intake_page():
    """摄影师投稿上传页。"""
    if os.path.isfile(_PAGE):
        return FileResponse(_PAGE)
    raise HTTPException(404, "投稿页面未找到")


@router.post("/api/intake/verify")
async def verify(code: str = Form(...)):
    """校验投稿码，返回摄影师与历史已交批次。"""
    p = await _get_photographer(_safe(code).upper())
    if not p:
        raise HTTPException(404, "投稿码无效")

    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT sf.content_label AS label, COUNT(*) AS cnt, "
            "       MAX(sf.created_at) AS last_at "
            "FROM submission_files sf "
            "JOIN submissions s ON sf.submission_id = s.id "
            "WHERE s.photographer_id = ? "
            "GROUP BY sf.content_label ORDER BY last_at DESC",
            (p["id"],),
        )
    finally:
        await conn.close()

    history = [
        {
            "label": r["label"],
            "count": r["cnt"],
            "date": time.strftime("%m/%d", time.localtime(r["last_at"])),
        }
        for r in rows
    ]
    return {
        "ok": True,
        "book_title": BOOK_TITLE,
        "name": p["name"],
        "total": sum(h["count"] for h in history),
        "history": history,
    }


@router.post("/api/intake/submit")
async def submit(code: str = Form(...), license_agreed: int = Form(0)):
    """创建一次投稿会话（一次回访）。"""
    if not license_agreed:
        raise HTTPException(400, "请先勾选版权授权")
    p = await _get_photographer(_safe(code).upper())
    if not p:
        raise HTTPException(404, "投稿码无效")

    now = time.time()
    conn = await db.get_db()
    try:
        cur = await conn.execute(
            "INSERT INTO submissions "
            "(photographer_id, license_agreed, license_at, status, created_at) "
            "VALUES (?, 1, ?, 'open', ?)",
            (p["id"], now, now),
        )
        await conn.commit()
        return {"ok": True, "submission_id": cur.lastrowid}
    finally:
        await conn.close()


@router.post("/api/intake/upload")
async def upload(
    submission_id: int = Form(...),
    content_label: str = Form(...),
    file: UploadFile = File(...),
):
    """上传单张照片（原型：经后端落本地，结构同 OSS key）。"""
    label = _safe(content_label)
    if not content_label.strip():
        raise HTTPException(400, "缺少内容标注")

    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT s.id, p.invite_code, p.name FROM submissions s "
            "JOIN photographers p ON s.photographer_id = p.id WHERE s.id = ?",
            (submission_id,),
        )
        if not rows:
            raise HTTPException(404, "投稿会话不存在")
        sub = rows[0]

        folder = f"{_safe(sub['invite_code'])}-{_safe(sub['name'])}"
        rel_key = f"{BOOK_CODE}/{folder}/{label}/{_safe(file.filename)}"
        dest = INTAKE_DATA / rel_key
        dest.parent.mkdir(parents=True, exist_ok=True)

        size = 0
        with open(dest, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
                size += len(chunk)

        await conn.execute(
            "INSERT INTO submission_files "
            "(submission_id, content_label, object_key, file_name, file_size, "
            " status, created_at) VALUES (?, ?, ?, ?, ?, 'done', ?)",
            (submission_id, label, rel_key, file.filename, size, time.time()),
        )
        await conn.commit()
        return {"ok": True, "object_key": rel_key, "size": size}
    finally:
        await conn.close()


@router.post("/api/intake/complete")
async def complete(submission_id: int = Form(...)):
    conn = await db.get_db()
    try:
        await conn.execute(
            "UPDATE submissions SET status = 'completed' WHERE id = ?",
            (submission_id,),
        )
        await conn.commit()
        return {"ok": True}
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 编辑端：征稿看板
# ---------------------------------------------------------------------------

@router.get("/api/intake/admin/submissions")
async def admin_submissions():
    """看板数据：每位摄影师交了多少、未交名单。"""
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT p.invite_code, p.name, "
            "       COUNT(sf.id) AS files, "
            "       COALESCE(SUM(sf.file_size), 0) AS bytes "
            "FROM photographers p "
            "LEFT JOIN submissions s ON s.photographer_id = p.id "
            "LEFT JOIN submission_files sf ON sf.submission_id = s.id "
            "WHERE p.book_code = ? "
            "GROUP BY p.id ORDER BY p.invite_code",
            (BOOK_CODE,),
        )
        result = []
        for r in rows:
            labels = await conn.execute_fetchall(
                "SELECT sf.content_label AS label, COUNT(*) AS cnt "
                "FROM submission_files sf "
                "JOIN submissions s ON sf.submission_id = s.id "
                "JOIN photographers p ON s.photographer_id = p.id "
                "WHERE p.invite_code = ? GROUP BY sf.content_label",
                (r["invite_code"],),
            )
            result.append(
                {
                    "code": r["invite_code"],
                    "name": r["name"],
                    "files": r["files"],
                    "mb": round(r["bytes"] / 1024 / 1024, 1),
                    "submitted": r["files"] > 0,
                    "labels": [{"label": x["label"], "count": x["cnt"]} for x in labels],
                }
            )
    finally:
        await conn.close()

    return {
        "book_code": BOOK_CODE,
        "book_title": BOOK_TITLE,
        "total_photographers": len(result),
        "submitted": sum(1 for x in result if x["submitted"]),
        "rows": result,
    }


@router.get("/intake/admin", response_class=HTMLResponse)
async def admin_page():
    """极简征稿看板（原型）。"""
    return HTMLResponse(_ADMIN_HTML)


_ADMIN_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>征稿看板</title><style>
body{font-family:-apple-system,"PingFang SC",sans-serif;background:#f5f5f4;color:#1f1f1d;
max-width:760px;margin:0 auto;padding:28px 16px;line-height:1.6}
h1{font-size:20px}.stat{color:#6b6a64;font-size:14px;margin-bottom:18px}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden}
th,td{text-align:left;padding:10px 12px;font-size:13px;border-bottom:1px solid #eee}
th{background:#fafaf8;color:#6b6a64;font-weight:600}
.no{color:#a32d2d}.yes{color:#0f6e56}.tag{display:inline-block;background:#e6f1fb;color:#185fa5;
border-radius:6px;padding:1px 7px;margin:1px;font-size:12px}
</style></head><body>
<h1 id="title">征稿看板</h1><div class="stat" id="stat">加载中…</div>
<table><thead><tr><th>投稿码</th><th>摄影师</th><th>状态</th><th>张数</th><th>大小</th><th>内容标注</th></tr></thead>
<tbody id="tb"></tbody></table>
<script>
fetch('/api/intake/admin/submissions').then(r=>r.json()).then(d=>{
  document.getElementById('title').textContent='《'+d.book_title+'》征稿看板';
  document.getElementById('stat').textContent='已投稿 '+d.submitted+' / '+d.total_photographers+' 位摄影师';
  document.getElementById('tb').innerHTML=d.rows.map(r=>'<tr><td>'+r.code+'</td><td>'+r.name+
    '</td><td class="'+(r.submitted?'yes':'no')+'">'+(r.submitted?'已交':'未交')+'</td><td>'+
    r.files+'</td><td>'+r.mb+' MB</td><td>'+(r.labels.map(l=>'<span class="tag">'+l.label+
    ' '+l.count+'</span>').join('')||'—')+'</td></tr>').join('');
});
</script></body></html>"""
