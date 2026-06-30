"""
Photo-Aiid-system · SQLite database layer (async via aiosqlite).

Tables: photos, ai_results, exif_data, settings, scan_sessions
"""

import aiosqlite
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

DB_PATH = os.environ.get("PHOTO_AIID_DB", "photo_aiid.db")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS photos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name     TEXT    NOT NULL,
    original_name TEXT,                                 -- 首次扫描时的原始文件名，物理重命名后不覆盖
    file_path     TEXT    NOT NULL,
    relative_path TEXT,
    file_size     INTEGER NOT NULL DEFAULT 0,
    file_mtime    REAL,
    mime_type     TEXT,
    width         INTEGER,
    height        INTEGER,
    scan_status   TEXT    NOT NULL DEFAULT 'queued',   -- queued | analyzing | done | error
    error_message TEXT,                                 -- last analysis failure reason (NULL when ok)
    scan_session_id INTEGER,
    created_at    REAL    NOT NULL,
    updated_at    REAL    NOT NULL,
    UNIQUE(file_path)
);

CREATE TABLE IF NOT EXISTS ai_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id    INTEGER NOT NULL UNIQUE,
    category    TEXT,
    tags        TEXT,        -- JSON array
    description TEXT,
    slug        TEXT,
    location    TEXT,
    photographer TEXT,
    engine      TEXT,
    raw_response TEXT,
    analyzed_at REAL    NOT NULL,
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exif_data (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id            INTEGER NOT NULL UNIQUE,
    date_time_original  TEXT,
    camera_model        TEXT,
    lens_model          TEXT,
    f_number            REAL,
    iso                 INTEGER,
    focal_length        REAL,
    exposure_time       TEXT,
    gps_lat             REAL,
    gps_lon             REAL,
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS scan_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    root_path   TEXT    NOT NULL,
    photo_count INTEGER NOT NULL DEFAULT 0,
    status      TEXT    NOT NULL DEFAULT 'running',  -- running | completed | error
    created_at  REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_photos_scan_status   ON photos(scan_status);
CREATE INDEX IF NOT EXISTS idx_photos_relative_path ON photos(relative_path);
CREATE INDEX IF NOT EXISTS idx_ai_results_photo     ON ai_results(photo_id);
CREATE INDEX IF NOT EXISTS idx_ai_results_category  ON ai_results(category);
CREATE INDEX IF NOT EXISTS idx_exif_photo           ON exif_data(photo_id);
"""


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

async def get_db() -> aiosqlite.Connection:
    """Return an async connection with WAL mode and FK enforcement."""
    db = await aiosqlite.connect(DB_PATH, timeout=60.0)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    """Create tables if they don't exist and seed default settings."""
    db = await get_db()
    try:
        await db.executescript(SCHEMA_SQL)
        # Lightweight migrations for pre-existing databases (CREATE TABLE IF NOT
        # EXISTS won't add new columns to an already-created table).
        cols = await db.execute_fetchall("PRAGMA table_info(ai_results)")
        col_names = {c["name"] for c in cols}
        if "location" not in col_names:
            await db.execute("ALTER TABLE ai_results ADD COLUMN location TEXT")
        if "photographer" not in col_names:
            await db.execute("ALTER TABLE ai_results ADD COLUMN photographer TEXT")
        pcols = await db.execute_fetchall("PRAGMA table_info(photos)")
        pcol_names = {c["name"] for c in pcols}
        if "error_message" not in pcol_names:
            await db.execute("ALTER TABLE photos ADD COLUMN error_message TEXT")
        if "original_name" not in pcol_names:
            await db.execute("ALTER TABLE photos ADD COLUMN original_name TEXT")
            # 回填：尚未物理重命名时 file_name 即原始名，保住原文件名里的地名等信息，
            # 使其在历史索引中即便重命名后仍可被搜到。
            await db.execute(
                "UPDATE photos SET original_name = file_name "
                "WHERE original_name IS NULL OR original_name = ''"
            )
        # Seed defaults
        defaults = {
            "engine": "ollama",
            "claude_api_key": "",
            "claude_model": "claude-sonnet-4-6",
            "ollama_url": "http://localhost:11434",
            "ollama_model": "gemma4:31b",
            "gemini_api_key": "",
            "gemini_model": "gemini-2.5-flash",
            "zhipu_api_key": "",
            "zhipu_model": "glm-4v-flash",
            "openai_api_key": "",
            "openai_model": "gpt-4o-mini",
            "openai_base_url": "https://api.openai.com/v1",
            "rename_prefix": "",
            "rename_template": "[摄影师]_[地点]_[类别]_[日期]",
            "analysis_concurrency": "2",
            "thumbnail_max_size": "512",
        }
        for k, v in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# CRUD: Settings
# ---------------------------------------------------------------------------

async def get_settings() -> dict[str, str]:
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in rows}
    finally:
        await db.close()


async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    try:
        row = await db.execute_fetchall(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        return row[0]["value"] if row else default
    finally:
        await db.close()


async def update_settings(updates: dict[str, str]):
    db = await get_db()
    try:
        for k, v in updates.items():
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, v),
            )
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# CRUD: Photos
# ---------------------------------------------------------------------------

async def insert_photo(
    file_name: str,
    file_path: str,
    relative_path: str,
    file_size: int,
    file_mtime: float,
    mime_type: str = "",
    width: int = 0,
    height: int = 0,
    scan_session_id: int | None = None,
    conn: aiosqlite.Connection | None = None,
) -> int:
    """Insert a photo row, return its id. Updates metadata if file_path exists but changed."""
    now = time.time()
    should_close = False
    if conn is None:
        conn = await get_db()
        should_close = True
    try:
        cursor = await conn.execute(
            """INSERT INTO photos
               (file_name, original_name, file_path, relative_path, file_size, file_mtime,
                mime_type, width, height, scan_status, scan_session_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
               ON CONFLICT(file_path) DO UPDATE SET
                 file_size = excluded.file_size,
                 file_mtime = excluded.file_mtime,
                 width = excluded.width,
                 height = excluded.height,
                 scan_status = 'queued',
                 updated_at = excluded.updated_at""",
            (file_name, file_name, file_path, relative_path, file_size, file_mtime,
             mime_type, width, height, scan_session_id, now, now),
        )
        await conn.commit()
        rows = await conn.execute_fetchall(
            "SELECT id FROM photos WHERE file_path = ?", (file_path,)
        )
        return rows[0]["id"] if rows else 0
    finally:
        if should_close:
            await conn.close()


async def get_photos_in_directory(root_path: str) -> dict[str, tuple[int, int, float]]:
    """Return a map of file_path -> (photo_id, file_size, file_mtime) for the folder."""
    db = await get_db()
    try:
        norm_folder = root_path.replace("\\", "/").rstrip("/")
        # We query paths under the root directory
        rows = await db.execute_fetchall(
            """SELECT id, file_path, file_size, file_mtime FROM photos 
               WHERE file_path LIKE ? OR replace(file_path, '\\', '/') LIKE ?""",
            (f"{norm_folder}/%", f"{norm_folder}/%")
        )
        return {r["file_path"]: (r["id"], r["file_size"], r["file_mtime"]) for r in rows}
    finally:
        await db.close()


def _natural_key(name: str):
    """Sort key that orders 'x (2)' before 'x (10)' (natural numeric order)."""
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


async def get_sibling_file_names(file_path: str, span: int = 4) -> list[str]:
    """Return up to `span` file names before and after `file_path` within the
    same immediate folder, in natural sort order (excluding the file itself)."""
    norm = file_path.replace("\\", "/")
    parent = norm.rsplit("/", 1)[0] if "/" in norm else ""
    if not parent:
        return []
    db = await get_db()
    try:
        # Immediate children only: under parent/ but not in a deeper subdir.
        rows = await db.execute_fetchall(
            """SELECT file_name, file_path FROM photos
               WHERE replace(file_path, '\\', '/') LIKE ?
                 AND replace(file_path, '\\', '/') NOT LIKE ?""",
            (f"{parent}/%", f"{parent}/%/%"),
        )
    finally:
        await db.close()
    siblings = sorted(rows, key=lambda r: _natural_key(r["file_name"]))
    names = [r["file_name"] for r in siblings]
    try:
        idx = next(i for i, r in enumerate(siblings)
                   if r["file_path"].replace("\\", "/") == norm)
    except StopIteration:
        return []
    before = names[max(0, idx - span):idx]
    after = names[idx + 1: idx + 1 + span]
    return before + after


async def get_photo(photo_id: int) -> Optional[dict]:
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT p.*,
                      a.category, a.tags AS ai_tags, a.description AS ai_desc,
                      a.slug, a.location, a.photographer, a.engine, a.analyzed_at,
                      e.date_time_original, e.camera_model, e.lens_model,
                      e.f_number, e.iso, e.focal_length, e.exposure_time,
                      e.gps_lat, e.gps_lon
               FROM photos p
               LEFT JOIN ai_results a ON a.photo_id = p.id
               LEFT JOIN exif_data  e ON e.photo_id = p.id
               WHERE p.id = ?""",
            (photo_id,),
        )
        return _row_to_photo(rows[0]) if rows else None
    finally:
        await db.close()


async def get_photos(
    offset: int = 0,
    limit: int = 50,
    status: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    search: str | None = None,
    scan_session_id: int | None = None,
    folder_path: str | None = None,
) -> tuple[list[dict], int]:
    """Return (photos, total_count) with pagination and filters."""
    db = await get_db()
    try:
        where_clauses = []
        params: list[Any] = []

        if status:
            where_clauses.append("p.scan_status = ?")
            params.append(status)
        if category:
            where_clauses.append("a.category = ?")
            params.append(category)
        if tag:
            where_clauses.append("(a.category = ? OR a.tags LIKE ?)")
            params.extend([tag, f'%"{tag}"%'])
        if search:
            # 同时搜「当前文件名 / 原始文件名 / 类别 / 标签 / 描述 / 地点 / 摄影师」，
            # 原始文件名里的地名（如「九龙潭」）即便物理重命名后也仍可被历史索引搜到。
            where_clauses.append(
                "(p.file_name LIKE ? OR p.original_name LIKE ? OR a.category LIKE ? "
                "OR a.tags LIKE ? OR a.description LIKE ? OR a.location LIKE ? "
                "OR a.photographer LIKE ?)"
            )
            s = f"%{search}%"
            params.extend([s, s, s, s, s, s, s])
        if scan_session_id is not None:
            where_clauses.append("p.scan_session_id = ?")
            params.append(scan_session_id)
        if folder_path:
            norm_folder = folder_path.replace("\\", "/").rstrip("/")
            where_clauses.append("(p.file_path LIKE ? OR replace(p.file_path, '\\', '/') LIKE ?)")
            params.extend([f"{norm_folder}/%", f"{norm_folder}/%"])

        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        count_row = await db.execute_fetchall(
            f"""SELECT COUNT(*) AS cnt FROM photos p
                LEFT JOIN ai_results a ON a.photo_id = p.id
                {where}""",
            params,
        )
        total = count_row[0]["cnt"]

        rows = await db.execute_fetchall(
            f"""SELECT p.*,
                       a.category, a.tags AS ai_tags, a.description AS ai_desc,
                       a.slug, a.location, a.photographer, a.engine, a.analyzed_at,
                       e.date_time_original, e.camera_model, e.lens_model,
                       e.f_number, e.iso, e.focal_length, e.exposure_time,
                       e.gps_lat, e.gps_lon
                FROM photos p
                LEFT JOIN ai_results a ON a.photo_id = p.id
                LEFT JOIN exif_data  e ON e.photo_id = p.id
                {where}
                ORDER BY p.id ASC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        )
        return [_row_to_photo(r) for r in rows], total
    finally:
        await db.close()


async def update_photo_status(
    photo_id: int, status: str, error_message: str | None = None
):
    """Update a photo's analysis status. When status != 'error', the stored
    failure reason is cleared so a later success doesn't keep a stale message."""
    db = await get_db()
    try:
        msg = error_message if status == "error" else None
        await db.execute(
            "UPDATE photos SET scan_status = ?, error_message = ?, updated_at = ? WHERE id = ?",
            (status, msg, time.time(), photo_id),
        )
        await db.commit()
    finally:
        await db.close()


async def update_photo_name(photo_id: int, new_name: str, new_path: str):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE photos SET file_name = ?, file_path = ?, updated_at = ? WHERE id = ?",
            (new_name, new_path, time.time(), photo_id),
        )
        await db.commit()
    finally:
        await db.close()


async def photo_exists_by_path_size_mtime(
    file_path: str, file_size: int, file_mtime: float
) -> bool:
    """Check if a photo with same path, size and mtime is already scanned."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id FROM photos WHERE file_path = ? AND file_size = ? AND file_mtime = ?",
            (file_path, file_size, file_mtime),
        )
        return len(rows) > 0
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# CRUD: AI Results
# ---------------------------------------------------------------------------

async def upsert_ai_result(
    photo_id: int,
    category: str,
    tags: list[str],
    description: str,
    slug: str,
    engine: str,
    raw_response: str = "",
    location: str = "",
    photographer: str = "",
):
    now = time.time()
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO ai_results (photo_id, category, tags, description, slug, location, photographer, engine, raw_response, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(photo_id) DO UPDATE SET
                 category=excluded.category, tags=excluded.tags,
                 description=excluded.description, slug=excluded.slug,
                 location=excluded.location, photographer=excluded.photographer,
                 engine=excluded.engine, raw_response=excluded.raw_response,
                 analyzed_at=excluded.analyzed_at""",
            (photo_id, category, json.dumps(tags, ensure_ascii=False),
             description, slug, location, photographer, engine, raw_response, now),
        )
        await db.execute(
            "UPDATE photos SET scan_status = 'done', error_message = NULL, updated_at = ? WHERE id = ?",
            (now, photo_id),
        )
        await db.commit()
    finally:
        await db.close()


async def update_ai_fields(
    photo_id: int,
    *,
    description: str | None = None,
    tags: list[str] | None = None,
    category: str | None = None,
    location: str | None = None,
    photographer: str | None = None,
) -> bool:
    """Update selected AI fields for one photo (only non-None fields)."""
    sets, params = [], []
    if description is not None:
        sets.append("description = ?"); params.append(description)
    if tags is not None:
        sets.append("tags = ?"); params.append(json.dumps(tags, ensure_ascii=False))
    if category is not None:
        sets.append("category = ?"); params.append(category)
    if location is not None:
        sets.append("location = ?"); params.append(location)
    if photographer is not None:
        sets.append("photographer = ?"); params.append(photographer)
    if not sets:
        return False
    params.append(photo_id)
    db = await get_db()
    try:
        cur = await db.execute(
            f"UPDATE ai_results SET {', '.join(sets)} WHERE photo_id = ?", params
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# CRUD: EXIF
# ---------------------------------------------------------------------------

async def upsert_exif(photo_id: int, exif: dict, conn: aiosqlite.Connection | None = None):
    should_close = False
    if conn is None:
        conn = await get_db()
        should_close = True
    try:
        await conn.execute(
            """INSERT INTO exif_data
               (photo_id, date_time_original, camera_model, lens_model,
                f_number, iso, focal_length, exposure_time, gps_lat, gps_lon)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(photo_id) DO UPDATE SET
                 date_time_original=excluded.date_time_original,
                 camera_model=excluded.camera_model, lens_model=excluded.lens_model,
                 f_number=excluded.f_number, iso=excluded.iso,
                 focal_length=excluded.focal_length, exposure_time=excluded.exposure_time,
                 gps_lat=excluded.gps_lat, gps_lon=excluded.gps_lon""",
            (
                photo_id,
                exif.get("date_time_original"),
                exif.get("camera_model"),
                exif.get("lens_model"),
                exif.get("f_number"),
                exif.get("iso"),
                exif.get("focal_length"),
                exif.get("exposure_time"),
                exif.get("gps_lat"),
                exif.get("gps_lon"),
            ),
        )
        await conn.commit()
    finally:
        if should_close:
            await conn.close()


# ---------------------------------------------------------------------------
# CRUD: Scan Sessions
# ---------------------------------------------------------------------------

async def create_scan_session(root_path: str) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO scan_sessions (root_path, photo_count, status, created_at) VALUES (?, 0, 'running', ?)",
            (root_path, time.time()),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def update_scan_session(session_id: int, photo_count: int, status: str = "completed"):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE scan_sessions SET photo_count = ?, status = ? WHERE id = ?",
            (photo_count, status, session_id),
        )
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Tags aggregation
# ---------------------------------------------------------------------------

async def get_all_tags() -> list[dict]:
    """Return tag name + count, aggregated from ai_results."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall("SELECT category, tags FROM ai_results")
        tag_count: dict[str, int] = {}
        for r in rows:
            cat = r["category"]
            if cat:
                tag_count[cat] = tag_count.get(cat, 0) + 1
            if r["tags"]:
                try:
                    for t in json.loads(r["tags"]):
                        tag_count[t] = tag_count.get(t, 0) + 1
                except json.JSONDecodeError:
                    pass
        return [{"name": k, "count": v} for k, v in sorted(tag_count.items(), key=lambda x: -x[1])]
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_photo(row) -> dict:
    """Convert a joined row into a clean dict."""
    d = dict(row)
    # Parse JSON tags
    tags_raw = d.pop("ai_tags", None)
    ai_desc = d.pop("ai_desc", None)
    tags = []
    if tags_raw:
        try:
            tags = json.loads(tags_raw)
        except json.JSONDecodeError:
            tags = []

    d["ai"] = None
    if d.get("category"):
        d["ai"] = {
            "category": d.get("category"),
            "tags": tags,
            "description": ai_desc,
            "slug": d.get("slug"),
            "location": d.get("location"),
            "photographer": d.get("photographer"),
            "engine": d.get("engine"),
            "analyzed_at": d.get("analyzed_at"),
        }
    # Clean up duplicated keys
    for k in ("category", "slug", "location", "photographer", "engine", "analyzed_at", "raw_response"):
        d.pop(k, None)

    d["exif"] = None
    if d.get("date_time_original") or d.get("camera_model"):
        d["exif"] = {
            "date_time_original": d.get("date_time_original"),
            "camera_model": d.get("camera_model"),
            "lens_model": d.get("lens_model"),
            "f_number": d.get("f_number"),
            "iso": d.get("iso"),
            "focal_length": d.get("focal_length"),
            "exposure_time": d.get("exposure_time"),
            "gps_lat": d.get("gps_lat"),
            "gps_lon": d.get("gps_lon"),
        }
    for k in ("date_time_original", "camera_model", "lens_model",
              "f_number", "iso", "focal_length", "exposure_time",
              "gps_lat", "gps_lon"):
        d.pop(k, None)

    return d


async def clear_database():
    """Clear all photos, exif, and scan sessions to clean up history."""
    db = await get_db()
    try:
        # Deleting from photos will cascade delete exif_data and ai_results due to FOREIGN KEY cascades
        await db.execute("DELETE FROM photos")
        await db.execute("DELETE FROM scan_sessions")
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Indexed-folder registry (multi-folder persistent library)
# ---------------------------------------------------------------------------

async def get_indexed_folders() -> list[dict]:
    """List every folder ever scanned (distinct scan_sessions.root_path), with
    live photo / analyzed counts and the most recent scan time. Filesystem
    existence is checked by the caller (this layer stays pure DB).
    """
    db = await get_db()
    try:
        sessions = await db.execute_fetchall(
            "SELECT root_path, MAX(created_at) AS last_scan "
            "FROM scan_sessions GROUP BY root_path ORDER BY last_scan DESC"
        )
        out: list[dict] = []
        for s in sessions:
            root = s["root_path"]
            norm = root.replace("\\", "/").rstrip("/")
            cnt = await db.execute_fetchall(
                "SELECT COUNT(*) AS total, "
                "       SUM(CASE WHEN a.photo_id IS NOT NULL THEN 1 ELSE 0 END) AS analyzed "
                "FROM photos p LEFT JOIN ai_results a ON a.photo_id = p.id "
                "WHERE p.file_path LIKE ? OR replace(p.file_path, '\\', '/') LIKE ?",
                (f"{norm}/%", f"{norm}/%"),
            )
            out.append({
                "path": root,
                "photo_count": cnt[0]["total"] or 0,
                "analyzed_count": cnt[0]["analyzed"] or 0,
                "last_scan": s["last_scan"],
            })
        return out
    finally:
        await db.close()


async def delete_hidden_photos() -> int:
    """删除文件名以 '.' 开头的记录：macOS 在非 HFS 磁盘生成的 AppleDouble 伴随
    文件（._xxx）与隐藏文件（.DS_Store 等）无图像内容，不应留在库里。
    返回删除的记录数（级联清理 exif_data / ai_results）。
    """
    db = await get_db()
    try:
        cur = await db.execute("DELETE FROM photos WHERE file_name LIKE '.%'")
        deleted = cur.rowcount
        await db.commit()
        return deleted
    finally:
        await db.close()


async def remove_folder(path: str) -> int:
    """Remove one indexed folder: delete all photos under that path (cascades to
    ai_results / exif_data) plus its scan_sessions. Returns deleted photo count.
    """
    db = await get_db()
    try:
        norm = path.replace("\\", "/").rstrip("/")
        cur = await db.execute(
            "DELETE FROM photos WHERE file_path LIKE ? OR replace(file_path, '\\', '/') LIKE ?",
            (f"{norm}/%", f"{norm}/%"),
        )
        deleted = cur.rowcount
        await db.execute(
            "DELETE FROM scan_sessions WHERE root_path = ? "
            "OR replace(root_path, '\\', '/') = ?",
            (path, norm),
        )
        await db.commit()
        return deleted
    finally:
        await db.close()

