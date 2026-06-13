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
    file_path     TEXT    NOT NULL,
    relative_path TEXT,
    file_size     INTEGER NOT NULL DEFAULT 0,
    file_mtime    REAL,
    mime_type     TEXT,
    width         INTEGER,
    height        INTEGER,
    scan_status   TEXT    NOT NULL DEFAULT 'queued',   -- queued | analyzing | done | error
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
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    """Create tables if they don't exist and seed default settings."""
    db = await get_db()
    try:
        await db.executescript(SCHEMA_SQL)
        # Seed defaults
        defaults = {
            "engine": "claude",
            "claude_api_key": "",
            "claude_model": "claude-sonnet-4-6",
            "ollama_url": "http://localhost:11434",
            "ollama_model": "gemma3:12b",
            "rename_prefix": "SDEXP",
            "rename_template": "[前缀]_[AI标签]_[日期]_[序号]",
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
) -> int:
    """Insert a photo row, return its id. Skips if file_path already exists."""
    now = time.time()
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT OR IGNORE INTO photos
               (file_name, file_path, relative_path, file_size, file_mtime,
                mime_type, width, height, scan_status, scan_session_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
            (file_name, file_path, relative_path, file_size, file_mtime,
             mime_type, width, height, scan_session_id, now, now),
        )
        await db.commit()
        if cursor.rowcount == 0:
            # Already exists – return existing id
            rows = await db.execute_fetchall(
                "SELECT id FROM photos WHERE file_path = ?", (file_path,)
            )
            return rows[0]["id"] if rows else 0
        return cursor.lastrowid
    finally:
        await db.close()


async def get_photo(photo_id: int) -> Optional[dict]:
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT p.*,
                      a.category, a.tags AS ai_tags, a.description AS ai_desc,
                      a.slug, a.engine, a.analyzed_at,
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
            where_clauses.append(
                "(p.file_name LIKE ? OR a.category LIKE ? OR a.tags LIKE ? OR a.description LIKE ?)"
            )
            s = f"%{search}%"
            params.extend([s, s, s, s])
        if scan_session_id is not None:
            where_clauses.append("p.scan_session_id = ?")
            params.append(scan_session_id)

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
                       a.slug, a.engine, a.analyzed_at,
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


async def update_photo_status(photo_id: int, status: str):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE photos SET scan_status = ?, updated_at = ? WHERE id = ?",
            (status, time.time(), photo_id),
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
):
    now = time.time()
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO ai_results (photo_id, category, tags, description, slug, engine, raw_response, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(photo_id) DO UPDATE SET
                 category=excluded.category, tags=excluded.tags,
                 description=excluded.description, slug=excluded.slug,
                 engine=excluded.engine, raw_response=excluded.raw_response,
                 analyzed_at=excluded.analyzed_at""",
            (photo_id, category, json.dumps(tags, ensure_ascii=False),
             description, slug, engine, raw_response, now),
        )
        await db.execute(
            "UPDATE photos SET scan_status = 'done', updated_at = ? WHERE id = ?",
            (now, photo_id),
        )
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# CRUD: EXIF
# ---------------------------------------------------------------------------

async def upsert_exif(photo_id: int, exif: dict):
    db = await get_db()
    try:
        await db.execute(
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
        await db.commit()
    finally:
        await db.close()


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
            "engine": d.get("engine"),
            "analyzed_at": d.get("analyzed_at"),
        }
    # Clean up duplicated keys
    for k in ("category", "slug", "engine", "analyzed_at", "raw_response"):
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
