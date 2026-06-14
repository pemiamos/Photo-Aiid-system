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

import base64
import hashlib
import hmac
import json
import os
import re
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Form, UploadFile, File, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse, HTMLResponse

import database as db

router = APIRouter()

# ---------------------------------------------------------------------------
# 管理后台鉴权
#   设置环境变量 INTAKE_ADMIN_TOKEN 后，/api/intake/admin/* 与后台页面需登录；
#   未设置时本地放行（仅便于本机原型调试，对外暴露前务必设置）。
# ---------------------------------------------------------------------------
ADMIN_TOKEN = os.environ.get("INTAKE_ADMIN_TOKEN", "")
_ADMIN_COOKIE = "intake_admin"


def _admin_cookie_value() -> str:
    return hmac.new(ADMIN_TOKEN.encode(), b"intake-admin-v1", hashlib.sha256).hexdigest()


def _admin_ok(request: Request) -> bool:
    if not ADMIN_TOKEN:
        return True
    return request.cookies.get(_ADMIN_COOKIE) == _admin_cookie_value()


async def require_admin(request: Request):
    """API 守卫：未登录返回 401。"""
    if not _admin_ok(request):
        raise HTTPException(401, "需要管理员登录")

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

# ---------------------------------------------------------------------------
# 阿里云 OSS 直传配置（全部来自环境变量；任一缺失则自动回退本地直存模式）
#   OSS_REGION            如 oss-cn-hangzhou（带 oss- 前缀，供浏览器 ali-oss 用）
#   OSS_BUCKET            存储桶名，如 photo-intake
#   OSS_ACCESS_KEY_ID     拥有 sts:AssumeRole 权限的子账号 AK
#   OSS_ACCESS_KEY_SECRET 对应 SK
#   OSS_STS_ROLE_ARN      被扮演的 RAM 角色 ARN（该角色有写桶权限）
# 详见 docs/OSS接入配置.md
# ---------------------------------------------------------------------------
OSS_REGION = os.environ.get("OSS_REGION", "")           # oss-cn-hangzhou
OSS_BUCKET = os.environ.get("OSS_BUCKET", "")
OSS_AK = os.environ.get("OSS_ACCESS_KEY_ID", "")
OSS_SK = os.environ.get("OSS_ACCESS_KEY_SECRET", "")
OSS_ROLE_ARN = os.environ.get("OSS_STS_ROLE_ARN", "")
OSS_STS_DURATION = int(os.environ.get("OSS_STS_DURATION", "3600"))


def _oss_configured() -> bool:
    return all([OSS_REGION, OSS_BUCKET, OSS_AK, OSS_SK, OSS_ROLE_ARN])


def _sts_region() -> str:
    """STS 用的地域 ID（去掉 oss- 前缀），如 cn-hangzhou。"""
    return OSS_REGION[4:] if OSS_REGION.startswith("oss-") else OSS_REGION


def _pe(s) -> str:
    """阿里云 RPC 签名的 percent-encode（RFC3986）。"""
    return urllib.parse.quote(str(s), safe="-_.~")


def _assume_role(prefix: str) -> dict:
    """调用 STS AssumeRole，返回限定在 {bucket}/{prefix}* 内可写的临时凭证。"""
    policy = {
        "Version": "1",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "oss:PutObject",
                    "oss:AbortMultipartUpload",
                    "oss:ListParts",
                ],
                "Resource": [f"acs:oss:*:*:{OSS_BUCKET}/{prefix}*"],
            }
        ],
    }
    params = {
        "Action": "AssumeRole",
        "RoleArn": OSS_ROLE_ARN,
        "RoleSessionName": "intake-upload",
        "DurationSeconds": str(OSS_STS_DURATION),
        "Policy": json.dumps(policy, separators=(",", ":")),
        "Format": "JSON",
        "Version": "2015-04-01",
        "AccessKeyId": OSS_AK,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": uuid.uuid4().hex,
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    canonical = "&".join(f"{_pe(k)}={_pe(params[k])}" for k in sorted(params))
    string_to_sign = "GET&%2F&" + _pe(canonical)
    signature = base64.b64encode(
        hmac.new((OSS_SK + "&").encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    params["Signature"] = signature

    url = f"https://sts.{_sts_region()}.aliyuncs.com/"
    resp = httpx.get(url, params=params, timeout=10.0)
    data = resp.json()
    if resp.status_code != 200 or "Credentials" not in data:
        raise HTTPException(
            502, f"STS 获取临时凭证失败：{data.get('Message', resp.text)[:200]}"
        )
    c = data["Credentials"]
    return {
        "AccessKeyId": c["AccessKeyId"],
        "AccessKeySecret": c["AccessKeySecret"],
        "SecurityToken": c["SecurityToken"],
        "Expiration": c["Expiration"],
    }

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
    photographer  TEXT,              -- 摄影师（来自 App 本地 AI 索引）
    location      TEXT,              -- 地点
    category      TEXT,              -- 类别
    description   TEXT,              -- 描述
    tags          TEXT,              -- 标签（JSON 字符串）
    status        TEXT NOT NULL DEFAULT 'done',
    created_at    REAL NOT NULL
);
"""

# 提交时随照片一起上传的本地 AI 索引字段（App 投稿模式用；网页留空）
_META_COLUMNS = ("photographer", "location", "category", "description", "tags")


async def init_intake_db():
    """建投稿相关表，并种入 demo 投稿码（原型用）。"""
    conn = await db.get_db()
    try:
        await conn.executescript(_SCHEMA)
        # 老库迁移：为已存在的 submission_files 补上索引字段
        cols = await conn.execute_fetchall("PRAGMA table_info(submission_files)")
        existing = {c["name"] for c in cols}
        for col in _META_COLUMNS:
            if col not in existing:
                await conn.execute(
                    f"ALTER TABLE submission_files ADD COLUMN {col} TEXT"
                )
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


async def _next_code(conn, book_code: str) -> str:
    """按 A01、A02… 生成下一个可用投稿码（跳过已存在的最大序号）。"""
    rows = await conn.execute_fetchall(
        "SELECT invite_code FROM photographers WHERE book_code = ?", (book_code,)
    )
    mx = 0
    for r in rows:
        m = re.match(r"^A(\d+)$", r["invite_code"] or "")
        if m:
            mx = max(mx, int(m.group(1)))
    return f"A{mx + 1:02d}"


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


async def _insert_file(conn, submission_id, label, object_key, file_name, size, meta):
    """写入一条照片记录，含可选的本地 AI 索引字段。"""
    await conn.execute(
        "INSERT INTO submission_files "
        "(submission_id, content_label, object_key, file_name, file_size, "
        " photographer, location, category, description, tags, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'done', ?)",
        (
            submission_id, label, object_key, file_name, size,
            meta.get("photographer") or None,
            meta.get("location") or None,
            meta.get("category") or None,
            meta.get("description") or None,
            meta.get("tags") or None,
            time.time(),
        ),
    )


@router.post("/api/intake/upload")
async def upload(
    submission_id: int = Form(...),
    content_label: str = Form(...),
    file: UploadFile = File(...),
    photographer: str = Form(""),
    location: str = Form(""),
    category: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
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

        prefix = _photographer_prefix(sub["invite_code"], sub["name"])
        rel_key = f"{prefix}{label}/{_safe(file.filename)}"
        dest = INTAKE_DATA / rel_key
        dest.parent.mkdir(parents=True, exist_ok=True)

        size = 0
        with open(dest, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
                size += len(chunk)

        await _insert_file(
            conn, submission_id, label, rel_key, file.filename, size,
            {"photographer": photographer, "location": location,
             "category": category, "description": description, "tags": tags},
        )
        await conn.commit()
        return {"ok": True, "object_key": rel_key, "size": size}
    finally:
        await conn.close()


def _photographer_prefix(invite_code: str, name: str) -> str:
    """该摄影师在桶内的可写前缀：{book}/{投稿码-姓名}/"""
    folder = f"{_safe(invite_code)}-{_safe(name)}"
    return f"{BOOK_CODE}/{folder}/"


@router.get("/api/intake/oss-config")
async def oss_config():
    """告诉前端当前用 OSS 直传还是本地直存（不返回任何密钥）。"""
    if _oss_configured():
        return {"mode": "oss", "region": OSS_REGION, "bucket": OSS_BUCKET}
    return {"mode": "local"}


@router.post("/api/intake/sts")
async def sts(code: str = Form(...)):
    """为某投稿码签发限定前缀的 OSS 临时上传凭证。"""
    if not _oss_configured():
        raise HTTPException(400, "未配置 OSS，当前为本地模式")
    p = await _get_photographer(_safe(code).upper())
    if not p:
        raise HTTPException(404, "投稿码无效")
    prefix = _photographer_prefix(p["invite_code"], p["name"])
    creds = _assume_role(prefix)
    return {
        "ok": True,
        "region": OSS_REGION,
        "bucket": OSS_BUCKET,
        "prefix": prefix,
        "credentials": creds,
    }


@router.post("/api/intake/record")
async def record(
    submission_id: int = Form(...),
    content_label: str = Form(...),
    object_key: str = Form(...),
    file_name: str = Form(...),
    file_size: int = Form(0),
    photographer: str = Form(""),
    location: str = Form(""),
    category: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
):
    """OSS 直传完成后登记元数据。校验 object_key 落在该摄影师前缀内。"""
    label = _safe(content_label)
    if not content_label.strip():
        raise HTTPException(400, "缺少内容标注")
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT p.invite_code, p.name FROM submissions s "
            "JOIN photographers p ON s.photographer_id = p.id WHERE s.id = ?",
            (submission_id,),
        )
        if not rows:
            raise HTTPException(404, "投稿会话不存在")
        prefix = _photographer_prefix(rows[0]["invite_code"], rows[0]["name"])
        if not object_key.startswith(prefix):
            raise HTTPException(403, "object_key 越权，不在该摄影师前缀内")
        await _insert_file(
            conn, submission_id, label, object_key, file_name, file_size,
            {"photographer": photographer, "location": location,
             "category": category, "description": description, "tags": tags},
        )
        await conn.commit()
        return {"ok": True, "object_key": object_key}
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
async def admin_submissions(_: None = Depends(require_admin)):
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


# ---------------------------------------------------------------------------
# 编辑端：投稿码管理
#
# 注意：以下管理接口在原型阶段未加鉴权，仅供本机/内网使用。对外暴露前
# 必须加管理员认证（见 PRD 第 7 章安全约束）。
# ---------------------------------------------------------------------------

@router.post("/api/intake/admin/login")
async def admin_login(response: Response, password: str = Form(...)):
    """校验管理口令，成功则下发签名 Cookie。"""
    if not ADMIN_TOKEN:
        return {"ok": True, "note": "未设置口令，已放行"}
    if password != ADMIN_TOKEN:
        raise HTTPException(401, "口令错误")
    response.set_cookie(
        _ADMIN_COOKIE, _admin_cookie_value(),
        httponly=True, samesite="lax", max_age=7 * 24 * 3600,
    )
    return {"ok": True}


@router.post("/api/intake/admin/logout")
async def admin_logout(response: Response):
    response.delete_cookie(_ADMIN_COOKIE)
    return {"ok": True}


@router.get("/api/intake/admin/codes")
async def list_codes(_: None = Depends(require_admin)):
    """列出本书所有投稿码及其投稿状态。"""
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT p.id, p.invite_code, p.name, p.contact, "
            "       COUNT(sf.id) AS files "
            "FROM photographers p "
            "LEFT JOIN submissions s ON s.photographer_id = p.id "
            "LEFT JOIN submission_files sf ON sf.submission_id = s.id "
            "WHERE p.book_code = ? "
            "GROUP BY p.id ORDER BY p.invite_code",
            (BOOK_CODE,),
        )
        return {
            "book_code": BOOK_CODE,
            "book_title": BOOK_TITLE,
            "rows": [
                {
                    "id": r["id"],
                    "code": r["invite_code"],
                    "name": r["name"],
                    "contact": r["contact"] or "",
                    "files": r["files"],
                    "submitted": r["files"] > 0,
                }
                for r in rows
            ],
        }
    finally:
        await conn.close()


@router.post("/api/intake/admin/codes")
async def create_code(
    name: str = Form(...),
    contact: str = Form(""),
    code: str = Form(""),
    _: None = Depends(require_admin),
):
    """新增一位摄影师并分配投稿码（code 留空则自动生成）。"""
    name = name.strip()
    if not name:
        raise HTTPException(400, "姓名不能为空")
    conn = await db.get_db()
    try:
        invite = _safe(code).upper() if code.strip() else await _next_code(conn, BOOK_CODE)
        exists = await conn.execute_fetchall(
            "SELECT 1 FROM photographers WHERE invite_code = ?", (invite,)
        )
        if exists:
            raise HTTPException(409, f"投稿码 {invite} 已存在")
        cur = await conn.execute(
            "INSERT INTO photographers "
            "(book_code, invite_code, name, contact, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (BOOK_CODE, invite, name, contact.strip(), time.time()),
        )
        await conn.commit()
        return {"ok": True, "id": cur.lastrowid, "code": invite, "name": name}
    finally:
        await conn.close()


@router.post("/api/intake/admin/codes/batch")
async def create_codes_batch(names: str = Form(...), _: None = Depends(require_admin)):
    """批量新增：每行一个姓名，自动分配连续投稿码。"""
    created = []
    conn = await db.get_db()
    try:
        for line in names.splitlines():
            nm = line.strip()
            if not nm:
                continue
            invite = await _next_code(conn, BOOK_CODE)
            await conn.execute(
                "INSERT INTO photographers "
                "(book_code, invite_code, name, contact, created_at) "
                "VALUES (?, ?, ?, '', ?)",
                (BOOK_CODE, invite, nm, time.time()),
            )
            await conn.commit()  # 逐条提交，确保 _next_code 看到最新序号
            created.append({"code": invite, "name": nm})
        return {"ok": True, "created": created}
    finally:
        await conn.close()


@router.delete("/api/intake/admin/codes/{pid}")
async def delete_code(pid: int, _: None = Depends(require_admin)):
    """删除投稿码。若该摄影师已有投稿，拒绝删除以防孤立已上传文件。"""
    conn = await db.get_db()
    try:
        files = await conn.execute_fetchall(
            "SELECT COUNT(sf.id) AS c FROM submission_files sf "
            "JOIN submissions s ON sf.submission_id = s.id "
            "WHERE s.photographer_id = ?",
            (pid,),
        )
        if files and files[0]["c"] > 0:
            raise HTTPException(409, "该摄影师已有投稿，不能删除")
        await conn.execute("DELETE FROM submissions WHERE photographer_id = ?", (pid,))
        await conn.execute("DELETE FROM photographers WHERE id = ?", (pid,))
        await conn.commit()
        return {"ok": True}
    finally:
        await conn.close()


@router.get("/intake/admin/codes", response_class=HTMLResponse)
async def codes_page(request: Request):
    """投稿码管理后台（原型）。"""
    if not _admin_ok(request):
        return HTMLResponse(_LOGIN_HTML)
    return HTMLResponse(_CODES_HTML)


@router.get("/intake/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """极简征稿看板（原型）。"""
    if not _admin_ok(request):
        return HTMLResponse(_LOGIN_HTML)
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
<h1 id="title">征稿看板</h1>
<div class="stat" id="stat">加载中… · <a href="/intake/admin/codes">→ 投稿码管理</a></div>
<table><thead><tr><th>投稿码</th><th>摄影师</th><th>状态</th><th>张数</th><th>大小</th><th>内容标注</th></tr></thead>
<tbody id="tb"></tbody></table>
<script>
fetch('/api/intake/admin/submissions').then(r=>r.json()).then(d=>{
  document.getElementById('title').textContent='《'+d.book_title+'》征稿看板';
  document.getElementById('stat').innerHTML='已投稿 '+d.submitted+' / '+d.total_photographers+
    ' 位摄影师 · <a href="/intake/admin/codes">→ 投稿码管理</a>';
  document.getElementById('tb').innerHTML=d.rows.map(r=>'<tr><td>'+r.code+'</td><td>'+r.name+
    '</td><td class="'+(r.submitted?'yes':'no')+'">'+(r.submitted?'已交':'未交')+'</td><td>'+
    r.files+'</td><td>'+r.mb+' MB</td><td>'+(r.labels.map(l=>'<span class="tag">'+l.label+
    ' '+l.count+'</span>').join('')||'—')+'</td></tr>').join('');
});
</script></body></html>"""


_CODES_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>投稿码管理</title><style>
body{font-family:-apple-system,"PingFang SC",sans-serif;background:#f5f5f4;color:#1f1f1d;
max-width:820px;margin:0 auto;padding:28px 16px;line-height:1.6}
h1{font-size:20px;margin-bottom:2px}h2{font-size:15px;margin:22px 0 10px;color:#444}
.stat{color:#6b6a64;font-size:14px;margin-bottom:8px}a{color:#185fa5}
.panel{background:#fff;border:1px solid #e5e4e1;border-radius:12px;padding:16px 18px;margin-bottom:14px}
input,textarea,button{font-family:inherit;font-size:14px}
input,textarea{border:1px solid #d6d4cf;border-radius:8px;padding:8px 10px;background:#fff}
input:focus,textarea:focus{outline:none;border-color:#185fa5;box-shadow:0 0 0 3px #e6f1fb}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.btn{background:#185fa5;color:#fff;border:none;border-radius:8px;padding:8px 16px;cursor:pointer}
.btn:hover{background:#134e89}.btn.ghost{background:#fff;color:#185fa5;border:1px solid #d6d4cf}
.btn.sm{padding:3px 10px;font-size:12px}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e5e4e1}
th,td{text-align:left;padding:9px 11px;font-size:13px;border-bottom:1px solid #eee}
th{background:#fafaf8;color:#6b6a64;font-weight:600}
.code{font-weight:600;letter-spacing:1px}
.no{color:#a32d2d}.yes{color:#0f6e56}
.link{color:#185fa5;font-size:12px;word-break:break-all}
.msg{font-size:13px;color:#0f6e56;margin-left:8px}
</style></head><body>
<h1 id="title">投稿码管理</h1>
<div class="stat"><a href="/intake/admin">← 返回征稿看板</a></div>

<div class="panel">
  <h2 style="margin-top:0">新增摄影师</h2>
  <div class="row">
    <input id="name" placeholder="姓名" style="width:130px">
    <input id="contact" placeholder="联系方式（选填）" style="width:180px">
    <input id="custom" placeholder="自定义码（选填）" style="width:130px">
    <button class="btn" id="addBtn">添加（自动生成码）</button>
    <span class="msg" id="addMsg"></span>
  </div>
  <h2>批量新增（每行一个姓名，自动连号）</h2>
  <div class="row" style="align-items:flex-start">
    <textarea id="batch" rows="3" placeholder="张伟&#10;李娜&#10;王芳" style="width:280px"></textarea>
    <button class="btn ghost" id="batchBtn">批量添加</button>
    <span class="msg" id="batchMsg"></span>
  </div>
</div>

<table><thead><tr><th>投稿码</th><th>姓名</th><th>联系方式</th><th>状态</th>
<th>投稿链接</th><th></th></tr></thead><tbody id="tb"></tbody></table>

<script>
var origin = location.origin;
function load(){
  fetch('/api/intake/admin/codes').then(r=>r.json()).then(d=>{
    document.getElementById('title').textContent='《'+d.book_title+'》投稿码管理';
    document.getElementById('tb').innerHTML = d.rows.map(function(r){
      var link = origin+'/intake?code='+r.code;
      return '<tr><td class="code">'+r.code+'</td><td>'+r.name+'</td><td>'+(r.contact||'—')+
        '</td><td class="'+(r.submitted?'yes':'no')+'">'+(r.submitted?'已交 '+r.files:'未交')+
        '</td><td><span class="link">'+link+'</span></td>'+
        '<td style="white-space:nowrap"><button class="btn ghost sm" onclick="copy(\\''+link+
        '\\')">复制</button> '+(r.submitted?'':'<button class="btn ghost sm" onclick="del('+
        r.id+')">删除</button>')+'</td></tr>';
    }).join('') || '<tr><td colspan="6" style="color:#9a988f">还没有投稿码，先在上方添加</td></tr>';
  });
}
function copy(t){ navigator.clipboard.writeText(t).then(function(){ alert('已复制：'+t); }); }
function del(id){
  if(!confirm('删除该投稿码？')) return;
  fetch('/api/intake/admin/codes/'+id,{method:'DELETE'}).then(function(r){
    if(!r.ok) return r.json().then(function(e){ alert(e.detail||'删除失败'); });
    load();
  });
}
document.getElementById('addBtn').onclick=function(){
  var fd=new FormData();
  fd.append('name',document.getElementById('name').value);
  fd.append('contact',document.getElementById('contact').value);
  fd.append('code',document.getElementById('custom').value);
  fetch('/api/intake/admin/codes',{method:'POST',body:fd}).then(function(r){
    return r.json().then(function(d){
      var m=document.getElementById('addMsg');
      if(!r.ok){ m.style.color='#a32d2d'; m.textContent=d.detail||'添加失败'; return; }
      m.style.color='#0f6e56'; m.textContent='已添加 '+d.code+' · '+d.name;
      document.getElementById('name').value='';document.getElementById('contact').value='';
      document.getElementById('custom').value=''; load();
    });
  });
};
document.getElementById('batchBtn').onclick=function(){
  var fd=new FormData(); fd.append('names',document.getElementById('batch').value);
  fetch('/api/intake/admin/codes/batch',{method:'POST',body:fd}).then(r=>r.json()).then(function(d){
    document.getElementById('batchMsg').textContent='已批量添加 '+d.created.length+' 位';
    document.getElementById('batch').value=''; load();
  });
};
load();
</script></body></html>"""


_LOGIN_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>管理员登录</title><style>
body{font-family:-apple-system,"PingFang SC",sans-serif;background:#f5f5f4;color:#1f1f1d;
display:flex;min-height:90vh;align-items:center;justify-content:center}
.box{background:#fff;border:1px solid #e5e4e1;border-radius:14px;padding:28px 30px;width:300px}
h1{font-size:18px;margin:0 0 16px}
input{width:100%;border:1px solid #d6d4cf;border-radius:8px;padding:10px 12px;font-size:14px;margin-bottom:12px}
input:focus{outline:none;border-color:#185fa5;box-shadow:0 0 0 3px #e6f1fb}
button{width:100%;background:#185fa5;color:#fff;border:none;border-radius:8px;padding:11px;font-size:14px;cursor:pointer}
button:hover{background:#134e89}.err{color:#a32d2d;font-size:13px;min-height:18px}
</style></head><body><div class="box">
<h1>征稿后台 · 管理员登录</h1>
<input type="password" id="pw" placeholder="管理口令" autofocus>
<div class="err" id="err"></div>
<button id="btn">登录</button>
<script>
function go(){
  var fd=new FormData(); fd.append('password',document.getElementById('pw').value);
  fetch('/api/intake/admin/login',{method:'POST',body:fd}).then(function(r){
    if(r.ok){ location.reload(); }
    else { document.getElementById('err').textContent='口令错误'; }
  });
}
document.getElementById('btn').onclick=go;
document.getElementById('pw').addEventListener('keydown',function(e){if(e.key==='Enter')go();});
</script></div></body></html>"""
