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

import asyncio
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import shutil
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
    # ① Web 端旧后台：签名 Cookie
    cookie = request.cookies.get(_ADMIN_COOKIE) or ""
    if hmac.compare_digest(cookie, _admin_cookie_value()):
        return True
    # ② 桌面 App 远程管理：直接带管理口令请求头（跨域 Cookie 不发送，故用头）
    header = request.headers.get("x-intake-admin-token") or ""
    return bool(header) and hmac.compare_digest(header, ADMIN_TOKEN)


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


def _assume_role(prefix: str, actions: list | None = None) -> dict:
    """调用 STS AssumeRole，返回限定在 {bucket}/{prefix}* 内的临时凭证。

    actions 缺省为上传所需动作；看板下钻预览原图时传只读动作（见 _assume_role_read）。
    注意：被扮演的 RAM 角色（OSS_STS_ROLE_ARN）须同时拥有这些动作的权限，
    否则临时凭证再受 policy 限制也无效——只读预览要求角色具备 oss:GetObject。
    """
    actions = actions or ["oss:PutObject", "oss:AbortMultipartUpload", "oss:ListParts"]
    policy = {
        "Version": "1",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": actions,
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


def _assume_role_read(prefix: str) -> dict:
    """限定在 {bucket}/{prefix}* 内的只读临时凭证（看板下钻预览原图用）。"""
    return _assume_role(prefix, actions=["oss:GetObject"])


def _oss_presign_get(object_key: str, creds: dict, expires: int = 600) -> str:
    """用 STS 临时凭证为私有桶里的一个 object 生成预签名 GET URL（OSS 签名 V1）。

    security-token 既作为查询参数，又作为子资源参与 CanonicalizedResource——这是
    阿里云 V1 的硬性要求（子资源白名单含 security-token），漏掉则签名校验失败。
    """
    ak = creds["AccessKeyId"]
    sk = creds["AccessKeySecret"]
    token = creds["SecurityToken"]
    deadline = int(time.time()) + expires
    # CanonicalizedResource 用「未编码」的 key 与 token；查询串里再各自编码
    canonical_resource = f"/{OSS_BUCKET}/{object_key}?security-token={token}"
    string_to_sign = f"GET\n\n\n{deadline}\n{canonical_resource}"
    signature = base64.b64encode(
        hmac.new(sk.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    host = f"{OSS_BUCKET}.{OSS_REGION}.aliyuncs.com"
    key_path = urllib.parse.quote(object_key, safe="/")
    qs = urllib.parse.urlencode({
        "OSSAccessKeyId": ak,
        "Expires": deadline,
        "Signature": signature,
        "security-token": token,
    })
    return f"https://{host}/{key_path}?{qs}"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    code        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',   -- active | archived
    created_at  REAL NOT NULL
);

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
        now = time.time()
        # 种入默认画册（来自环境变量，向后兼容单本配置）
        await conn.execute(
            "INSERT OR IGNORE INTO books (code, title, status, created_at) "
            "VALUES (?, ?, 'active', ?)",
            (BOOK_CODE, BOOK_TITLE, now),
        )
        # 老库迁移：把 photographers 里出现过、但 books 表还没有的 book_code 补登记
        legacy = await conn.execute_fetchall(
            "SELECT DISTINCT book_code FROM photographers "
            "WHERE book_code NOT IN (SELECT code FROM books)"
        )
        for r in legacy:
            await conn.execute(
                "INSERT OR IGNORE INTO books (code, title, status, created_at) "
                "VALUES (?, ?, 'active', ?)",
                (r["book_code"], r["book_code"], now),
            )
        # demo 种子：A03 王芳 故意不投稿，用于看板展示「未交」
        seed = [
            ("A01", "张伟", "13800000001"),
            ("A02", "李娜", "13800000002"),
            ("A03", "王芳", "13800000003"),
        ]
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
    # 投稿码全局唯一，按码直接定位摄影师；其所属画册由 book_code 字段携带，
    # 因此同一台后端可同时承接多本画册的投稿。
    conn = await db.get_db()
    try:
        row = await conn.execute_fetchall(
            "SELECT * FROM photographers WHERE invite_code = ?", (code,)
        )
        return dict(row[0]) if row else None
    finally:
        await conn.close()


async def _book_title(conn, code: str) -> str:
    rows = await conn.execute_fetchall(
        "SELECT title FROM books WHERE code = ?", (code,)
    )
    return rows[0]["title"] if rows else code


async def _default_book(conn) -> str:
    """未指定画册时的兜底：最近创建的 active 画册，否则环境默认。"""
    rows = await conn.execute_fetchall(
        "SELECT code FROM books WHERE status = 'active' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    return rows[0]["code"] if rows else BOOK_CODE


async def _resolve_book(conn, book: str) -> str:
    book = (book or "").strip()
    if book:
        return book
    return await _default_book(conn)


async def _next_code(conn, book_code: str = "") -> str:
    """生成下一个 A01、A02… 投稿码。

    invite_code 在全库唯一，因此序号按全局最大值递增（而非按画册），
    多本画册共用一条不重复的序列，避免跨画册撞码。book_code 参数保留
    以兼容调用方，当前不参与计算。
    """
    rows = await conn.execute_fetchall("SELECT invite_code FROM photographers")
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
        book_title = await _book_title(conn, p["book_code"])
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
        "book_title": book_title,
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


def _merge_label_into_tags(label, tags_raw):
    """把「特别标注」并入标签数组，便于后期按标签搜索。去重、跳过空与默认占位。"""
    try:
        tags = json.loads(tags_raw) if tags_raw else []
        if not isinstance(tags, list):
            tags = [str(tags)]
    except (ValueError, TypeError):
        tags = [t.strip() for t in str(tags_raw).split(",") if t.strip()]
    label = (label or "").strip()
    if label and label != "未命名" and label not in tags:
        tags.append(label)
    return json.dumps(tags, ensure_ascii=False) if tags else None


async def _insert_file(conn, submission_id, label, object_key, file_name, size, meta):
    """写入一条照片记录，含可选的本地 AI 索引字段。

    按 object_key 去重：object_key = {书}/{投稿码-姓名}/{标注}/{文件名}，对同一张
    照片是确定且唯一的。摄影师若重复提交（如上传中误点多次），同一 object_key 在 OSS
    里是覆盖、在库里也只更新这一行而非新增，避免张数被重复计数。
    """
    merged_tags = _merge_label_into_tags(label, meta.get("tags"))
    cols = (
        meta.get("photographer") or None,
        meta.get("location") or None,
        meta.get("category") or None,
        meta.get("description") or None,
        merged_tags,
    )
    existing = await conn.execute_fetchall(
        "SELECT id FROM submission_files WHERE object_key = ?", (object_key,)
    )
    if existing:
        await conn.execute(
            "UPDATE submission_files SET submission_id=?, content_label=?, file_name=?, "
            "file_size=?, photographer=?, location=?, category=?, description=?, tags=?, "
            "status='done', created_at=? WHERE object_key=?",
            (submission_id, label, file_name, size, *cols, time.time(), object_key),
        )
        return
    await conn.execute(
        "INSERT INTO submission_files "
        "(submission_id, content_label, object_key, file_name, file_size, "
        " photographer, location, category, description, tags, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'done', ?)",
        (submission_id, label, object_key, file_name, size, *cols, time.time()),
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
    # 特别标注为选填，留空则归入 _safe 的默认目录「未命名」
    label = _safe(content_label)

    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT s.id, p.invite_code, p.name, p.book_code FROM submissions s "
            "JOIN photographers p ON s.photographer_id = p.id WHERE s.id = ?",
            (submission_id,),
        )
        if not rows:
            raise HTTPException(404, "投稿会话不存在")
        sub = rows[0]

        prefix = _photographer_prefix(sub["invite_code"], sub["name"], sub["book_code"])
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


def _photographer_prefix(invite_code: str, name: str, book_code: str = "") -> str:
    """该摄影师在桶内的可写前缀：{book}/{投稿码-姓名}/"""
    folder = f"{_safe(invite_code)}-{_safe(name)}"
    return f"{_safe(book_code) if book_code else BOOK_CODE}/{folder}/"


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
    prefix = _photographer_prefix(p["invite_code"], p["name"], p["book_code"])
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
    # 特别标注为选填，留空则归入 _safe 的默认目录「未命名」
    label = _safe(content_label)
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT p.invite_code, p.name, p.book_code FROM submissions s "
            "JOIN photographers p ON s.photographer_id = p.id WHERE s.id = ?",
            (submission_id,),
        )
        if not rows:
            raise HTTPException(404, "投稿会话不存在")
        prefix = _photographer_prefix(
            rows[0]["invite_code"], rows[0]["name"], rows[0]["book_code"])
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
# 编辑端：画册项目管理
#
# 一台后端可承接多本画册（每本一个征稿项目）。投稿码全局唯一并归属某画册，
# 因此摄影师投稿无需选画册，编辑端则按画册分别查看看板与投稿码。
# ---------------------------------------------------------------------------

def _book_slug(s: str) -> str:
    """画册 code 规整：仅保留字母数字与 - _，转小写，作为存储前缀的一段。"""
    s = re.sub(r"[^0-9A-Za-z_-]+", "-", (s or "").strip()).strip("-_").lower()
    return s


@router.get("/api/intake/admin/books")
async def list_books(_: None = Depends(require_admin)):
    """列出全部画册（新建在前），含每本的征稿统计。"""
    conn = await db.get_db()
    try:
        books = await conn.execute_fetchall(
            "SELECT code, title, status, created_at FROM books "
            "ORDER BY (status='archived'), created_at DESC"
        )
        result = []
        for b in books:
            stat = await conn.execute_fetchall(
                "SELECT COUNT(DISTINCT p.id) AS people, "
                "       COUNT(sf.id) AS files, "
                "       COALESCE(SUM(sf.file_size), 0) AS bytes, "
                "       COUNT(DISTINCT CASE WHEN sf.id IS NOT NULL THEN p.id END) AS submitted "
                "FROM photographers p "
                "LEFT JOIN submissions s ON s.photographer_id = p.id "
                "LEFT JOIN submission_files sf ON sf.submission_id = s.id "
                "WHERE p.book_code = ?",
                (b["code"],),
            )
            st = stat[0] if stat else {}
            result.append({
                "code": b["code"],
                "title": b["title"],
                "status": b["status"],
                "created_at": b["created_at"],
                "created": time.strftime("%Y-%m-%d", time.localtime(b["created_at"])),
                "people": st["people"] or 0,
                "submitted": st["submitted"] or 0,
                "files": st["files"] or 0,
                "mb": round((st["bytes"] or 0) / 1024 / 1024, 1),
            })
        return {"rows": result}
    finally:
        await conn.close()


@router.post("/api/intake/admin/books")
async def create_book(
    title: str = Form(...),
    code: str = Form(""),
    _: None = Depends(require_admin),
):
    """新建一本画册（征稿项目）。code 留空则由标题自动生成。"""
    title = title.strip()
    if not title:
        raise HTTPException(400, "画册名称不能为空")
    code = _book_slug(code) or _book_slug(title)
    if not code:
        # 标题全为中文等无法 slug 化时，用时间戳兜底
        code = "book-" + time.strftime("%Y%m%d-%H%M%S")
    conn = await db.get_db()
    try:
        exists = await conn.execute_fetchall(
            "SELECT 1 FROM books WHERE code = ?", (code,)
        )
        if exists:
            raise HTTPException(409, f"画册编号 {code} 已存在")
        await conn.execute(
            "INSERT INTO books (code, title, status, created_at) "
            "VALUES (?, ?, 'active', ?)",
            (code, title, time.time()),
        )
        await conn.commit()
        return {"ok": True, "code": code, "title": title}
    finally:
        await conn.close()


@router.post("/api/intake/admin/books/{code}/status")
async def set_book_status(
    code: str,
    status: str = Form(...),
    _: None = Depends(require_admin),
):
    """归档 / 恢复画册。归档只改状态，不影响已有投稿数据。"""
    if status not in ("active", "archived"):
        raise HTTPException(400, "status 仅支持 active / archived")
    conn = await db.get_db()
    try:
        cur = await conn.execute(
            "UPDATE books SET status = ? WHERE code = ?", (status, code)
        )
        await conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "画册不存在")
        return {"ok": True, "code": code, "status": status}
    finally:
        await conn.close()


@router.patch("/api/intake/admin/books/{code}")
async def rename_book(
    code: str,
    title: str = Form(...),
    _: None = Depends(require_admin),
):
    """重命名画册标题（编号不变，前缀与历史数据不受影响）。"""
    title = title.strip()
    if not title:
        raise HTTPException(400, "画册名称不能为空")
    conn = await db.get_db()
    try:
        cur = await conn.execute(
            "UPDATE books SET title = ? WHERE code = ?", (title, code)
        )
        await conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "画册不存在")
        return {"ok": True, "code": code, "title": title}
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 编辑端：征稿看板
# ---------------------------------------------------------------------------

@router.get("/api/intake/admin/submissions")
async def admin_submissions(book: str = "", _: None = Depends(require_admin)):
    """看板数据：某画册下每位摄影师交了多少、未交名单。"""
    conn = await db.get_db()
    try:
        book_code = await _resolve_book(conn, book)
        book_title = await _book_title(conn, book_code)
        rows = await conn.execute_fetchall(
            "SELECT p.invite_code, p.name, "
            "       COUNT(sf.id) AS files, "
            "       COALESCE(SUM(sf.file_size), 0) AS bytes "
            "FROM photographers p "
            "LEFT JOIN submissions s ON s.photographer_id = p.id "
            "LEFT JOIN submission_files sf ON sf.submission_id = s.id "
            "WHERE p.book_code = ? "
            "GROUP BY p.id ORDER BY p.invite_code",
            (book_code,),
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

    total_files = sum(x["files"] for x in result)
    total_mb = round(sum(x["mb"] for x in result), 1)
    return {
        "book_code": book_code,
        "book_title": book_title,
        "total_photographers": len(result),
        "submitted": sum(1 for x in result if x["submitted"]),
        "total_files": total_files,
        "total_mb": total_mb,
        "rows": result,
    }


@router.get("/api/intake/admin/files")
async def admin_photographer_files(code: str, _: None = Depends(require_admin)):
    """看板下钻：列出某投稿码下所有照片，并给出可直接 <img> 预览的 url。

    OSS 模式：为该摄影师前缀签发只读临时凭证，逐张生成预签名 GET URL（10 分钟有效）。
    本地直存：url 指向受管理鉴权保护的 /api/intake/admin/file/raw 代理。
    """
    p = await _get_photographer(_safe(code).upper())
    if not p:
        raise HTTPException(404, "投稿码无效")

    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT sf.id, sf.content_label, sf.object_key, sf.file_name, "
            "       sf.file_size, sf.location, sf.category, sf.description, "
            "       sf.tags, sf.created_at "
            "FROM submission_files sf "
            "JOIN submissions s ON sf.submission_id = s.id "
            "WHERE s.photographer_id = ? ORDER BY sf.created_at DESC, sf.id DESC",
            (p["id"],),
        )
    finally:
        await conn.close()

    mode = "oss" if _oss_configured() else "local"
    creds = None
    if mode == "oss" and rows:
        prefix = _photographer_prefix(p["invite_code"], p["name"], p["book_code"])
        creds = _assume_role_read(prefix)

    files = []
    for r in rows:
        key = r["object_key"]
        if mode == "oss":
            url = _oss_presign_get(key, creds)
        else:
            url = f"/api/intake/admin/file/raw?key={urllib.parse.quote(key)}"
        try:
            tags = json.loads(r["tags"]) if r["tags"] else []
        except (ValueError, TypeError):
            tags = []
        files.append({
            "id": r["id"],
            "label": r["content_label"],
            "file_name": r["file_name"],
            "size": r["file_size"],
            "mb": round((r["file_size"] or 0) / 1024 / 1024, 2),
            "location": r["location"] or "",
            "category": r["category"] or "",
            "description": r["description"] or "",
            "tags": tags if isinstance(tags, list) else [],
            "url": url,
            "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created_at"])),
        })

    return {
        "code": p["invite_code"],
        "name": p["name"],
        "mode": mode,
        "count": len(files),
        "files": files,
    }


@router.get("/api/intake/admin/file/raw")
async def admin_file_raw(key: str, _: None = Depends(require_admin)):
    """本地直存模式下，受鉴权地回源单张原图。校验解析后仍落在 INTAKE_DATA 内，防越权。"""
    if _oss_configured():
        raise HTTPException(400, "OSS 模式请用预签名 URL 直接访问")
    target = (INTAKE_DATA / key).resolve()
    if not target.is_relative_to(INTAKE_DATA) or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target)


# ---------------------------------------------------------------------------
# 编辑端：投稿码管理
#
# 注意：以下管理接口在原型阶段未加鉴权，仅供本机/内网使用。对外暴露前
# 必须加管理员认证（见 PRD 第 7 章安全约束）。
# ---------------------------------------------------------------------------

@router.get("/api/intake/admin/ping")
async def admin_ping(_: None = Depends(require_admin)):
    """连通性探测：桌面 App 用「服务器地址 + 管理口令头」验证能否远程管理。"""
    return {"ok": True, "oss": _oss_configured()}


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
async def list_codes(book: str = "", _: None = Depends(require_admin)):
    """列出某画册所有投稿码及其投稿状态。"""
    conn = await db.get_db()
    try:
        book_code = await _resolve_book(conn, book)
        book_title = await _book_title(conn, book_code)
        rows = await conn.execute_fetchall(
            "SELECT p.id, p.invite_code, p.name, p.contact, "
            "       COUNT(sf.id) AS files "
            "FROM photographers p "
            "LEFT JOIN submissions s ON s.photographer_id = p.id "
            "LEFT JOIN submission_files sf ON sf.submission_id = s.id "
            "WHERE p.book_code = ? "
            "GROUP BY p.id ORDER BY p.invite_code",
            (book_code,),
        )
        return {
            "book_code": book_code,
            "book_title": book_title,
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
    book: str = Form(""),
    _: None = Depends(require_admin),
):
    """在指定画册下新增一位摄影师并分配投稿码（code 留空则自动生成）。"""
    name = name.strip()
    if not name:
        raise HTTPException(400, "姓名不能为空")
    conn = await db.get_db()
    try:
        book_code = await _resolve_book(conn, book)
        invite = _safe(code).upper() if code.strip() else await _next_code(conn, book_code)
        exists = await conn.execute_fetchall(
            "SELECT 1 FROM photographers WHERE invite_code = ?", (invite,)
        )
        if exists:
            raise HTTPException(409, f"投稿码 {invite} 已存在")
        cur = await conn.execute(
            "INSERT INTO photographers "
            "(book_code, invite_code, name, contact, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (book_code, invite, name, contact.strip(), time.time()),
        )
        await conn.commit()
        return {"ok": True, "id": cur.lastrowid, "code": invite, "name": name}
    finally:
        await conn.close()


@router.post("/api/intake/admin/codes/batch")
async def create_codes_batch(
    names: str = Form(...),
    book: str = Form(""),
    _: None = Depends(require_admin),
):
    """批量新增：每行一个姓名，在指定画册下自动分配连续投稿码。"""
    created = []
    conn = await db.get_db()
    try:
        book_code = await _resolve_book(conn, book)
        for line in names.splitlines():
            nm = line.strip()
            if not nm:
                continue
            invite = await _next_code(conn, book_code)
            await conn.execute(
                "INSERT INTO photographers "
                "(book_code, invite_code, name, contact, created_at) "
                "VALUES (?, ?, ?, '', ?)",
                (book_code, invite, nm, time.time()),
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


@router.get("/api/intake/admin/export.csv")
async def export_codes_csv(
    book: str = "",
    base: str = "",
    _: None = Depends(require_admin),
):
    """一键导出投稿码花名册为 CSV（含 UTF-8 BOM，Excel 直接打开）。

    book 留空 → 导出全部画册；指定 → 仅该画册。base 为投稿页对外地址，
    用于拼出每位摄影师的专属投稿链接列（留空则不含域名，只给相对路径）。
    """
    base = (base or "").strip().rstrip("/")
    conn = await db.get_db()
    try:
        if book.strip():
            where, params = "WHERE p.book_code = ?", (book.strip(),)
            fname_book = book.strip()
        else:
            where, params = "", ()
            fname_book = "all"
        rows = await conn.execute_fetchall(
            "SELECT b.title AS book_title, p.book_code, p.invite_code, "
            "       p.name, p.contact, "
            "       COUNT(sf.id) AS files, "
            "       COALESCE(SUM(sf.file_size), 0) AS bytes "
            "FROM photographers p "
            "LEFT JOIN books b ON b.code = p.book_code "
            "LEFT JOIN submissions s ON s.photographer_id = p.id "
            "LEFT JOIN submission_files sf ON sf.submission_id = s.id "
            f"{where} "
            "GROUP BY p.id ORDER BY p.book_code, p.invite_code",
            params,
        )
    finally:
        await conn.close()

    buf = io.StringIO()
    buf.write("﻿")  # BOM：让 Excel 以 UTF-8 解析中文
    w = csv.writer(buf)
    w.writerow(["画册", "画册编号", "投稿码", "姓名", "联系方式",
                "状态", "已交张数", "容量(MB)", "专属投稿链接"])
    for r in rows:
        link = f"{base}/intake?code={r['invite_code']}" if base else \
               f"/intake?code={r['invite_code']}"
        w.writerow([
            r["book_title"] or r["book_code"],
            r["book_code"],
            r["invite_code"],
            r["name"] or "",
            r["contact"] or "",
            "已交" if r["files"] > 0 else "未交",
            r["files"],
            round((r["bytes"] or 0) / 1024 / 1024, 1),
            link,
        ])

    stamp = time.strftime("%Y%m%d")
    filename = f"投稿码花名册_{fname_book}_{stamp}.csv"
    quoted = urllib.parse.quote(filename)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
        },
    )


# ---------------------------------------------------------------------------
# 编辑端：R2 归档（一键触发 scripts/archive-to-r2.sh + 状态轮询）
#
# 后端在仓库根目录跑归档脚本（rclone 把某书原图从 OSS 搬到 R2 并核对）。
# 状态写 JSON 文件，便于重启后仍能展示「上次归档时间/结果」。进行中状态在内存。
# 注意：脚本依赖运行机器已装 rclone 且配好 oss/r2 remote（见脚本头注释）。
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARCHIVE_SCRIPT = _REPO_ROOT / "scripts" / "archive-to-r2.sh"
_ARCHIVE_STATE = Path(__file__).resolve().parent / "archive_state.json"
_archive_running: dict[str, bool] = {}

# R2 持续镜像（systemd timer 跑 scripts/mirror-oss-to-r2.sh）写的状态文件。
# 用于让 App 徽章反映「上一轮是否成功」，而不只是「rclone 是否就绪」。
_MIRROR_STATE = Path("/var/log/photo-r2-mirror.state")


def _load_mirror_state() -> dict | None:
    try:
        return json.loads(_MIRROR_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _load_archive_state() -> dict:
    try:
        return json.loads(_ARCHIVE_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_archive_state(state: dict) -> None:
    try:
        _ARCHIVE_STATE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


async def _run_archive(book: str) -> None:
    """后台跑归档脚本，结束后把结果（成功/失败 + 日志尾）写入状态文件。"""
    _archive_running[book] = True
    started = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash", str(_ARCHIVE_SCRIPT), book,
            cwd=str(_REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        log = (out or b"").decode("utf-8", "replace")
        ok = proc.returncode == 0
        message = "归档完成" if ok else f"归档失败（退出码 {proc.returncode}）"
    except Exception as e:  # noqa: BLE001 — 任何异常都要落到状态里给前端看
        ok = False
        log = str(e)
        message = "归档启动失败"
    finally:
        _archive_running[book] = False

    state = _load_archive_state()
    state[book] = {
        "last_at": time.time(),
        "last_at_str": time.strftime("%Y-%m-%d %H:%M", time.localtime()),
        "ok": ok,
        "message": message,
        "log_tail": "\n".join(log.splitlines()[-12:]),
        "duration_s": round(time.time() - started, 1),
    }
    _save_archive_state(state)


@router.post("/api/intake/admin/archive")
async def archive_book(book: str = Form(...), _: None = Depends(require_admin)):
    """一键把某书原图从 OSS 归档到 R2（后台执行，不阻塞请求）。"""
    book = (book or "").strip()
    if not book:
        raise HTTPException(400, "缺少书目代号")
    if _archive_running.get(book):
        raise HTTPException(409, "该书归档正在进行中")
    if not _ARCHIVE_SCRIPT.is_file():
        raise HTTPException(500, "未找到归档脚本 scripts/archive-to-r2.sh")
    if not shutil.which("rclone"):
        raise HTTPException(
            400, "服务器未安装 rclone，无法归档。请在运行后端的机器上安装并配置 rclone。"
        )
    asyncio.create_task(_run_archive(book))
    return {"ok": True, "started": True, "book": book}


@router.get("/api/intake/admin/archive/status")
async def archive_status(book: str = "", _: None = Depends(require_admin)):
    """归档状态：是否进行中、上次时间/结果/日志尾。"""
    book = (book or "").strip()
    state = _load_archive_state()
    info = state.get(book, {})
    return {
        "book": book,
        "running": bool(_archive_running.get(book)),
        "rclone": bool(shutil.which("rclone")),
        "last_at_str": info.get("last_at_str", ""),
        "ok": info.get("ok"),
        "message": info.get("message", ""),
        "log_tail": info.get("log_tail", ""),
        # 持续镜像状态（整桶级，与具体 book 无关）：{at, ok, msg} 或 null
        "mirror": _load_mirror_state(),
    }


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
