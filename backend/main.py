"""
Photo-Aiid-system · FastAPI Backend
Main application with all API routes.
"""

import asyncio
import csv
import io
import json
import logging
import os
import platform
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import database as db
from engines import get_engine, list_engines
from services import scanner, analyzer, renamer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    logger.info("Photo-Aiid-system backend started ✓")
    yield


app = FastAPI(
    title="Photo-Aiid-system",
    description="AI 智能照片管理与批量处理系统 API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class ScanRequest(BaseModel):
    folder_path: str

class AnalyzeRequest(BaseModel):
    photo_ids: list[int] | None = None
    engine: str | None = None
    concurrency: int | None = None

class AnalyzeSingleRequest(BaseModel):
    engine: str | None = None

class RenameRequest(BaseModel):
    photo_ids: list[int] | None = None
    prefix: str | None = None
    template: str | None = None
    dry_run: bool = False

class SearchRequest(BaseModel):
    query: str

class AIEdit(BaseModel):
    description: str | None = None
    tags: list[str] | None = None
    category: str | None = None
    location: str | None = None
    photographer: str | None = None

class BatchAIEdit(BaseModel):
    photo_ids: list[int]
    description: str | None = None
    add_tags: list[str] | None = None
    remove_tags: list[str] | None = None
    category: str | None = None
    photographer: str | None = None
    location: str | None = None

class SettingsUpdate(BaseModel):
    engine: str | None = None
    claude_api_key: str | None = None
    claude_model: str | None = None
    ollama_url: str | None = None
    ollama_model: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    zhipu_api_key: str | None = None
    zhipu_model: str | None = None
    rename_prefix: str | None = None
    rename_template: str | None = None
    analysis_concurrency: str | None = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health_check():
    settings = await db.get_settings()
    engines = list_engines()
    return {
        "status": "ok",
        "engine": settings.get("engine", "claude"),
        "engines": engines,
        "scan_progress": scanner.get_scan_progress(),
        "analysis_progress": analyzer.get_analysis_progress(),
    }


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

@app.post("/api/scan")
async def scan_folder(req: ScanRequest, bg: BackgroundTasks):
    folder = req.folder_path.strip()
    if not os.path.isdir(folder):
        raise HTTPException(status_code=400, detail=f"路径不存在或不是文件夹: {folder}")

    # Check if this is a new folder path to clear history
    import unicodedata
    def norm(p):
        return unicodedata.normalize("NFC", p.replace("\\", "/").rstrip("/"))

    settings = await db.get_settings()
    old_folder = settings.get("last_folder", "")
    
    if old_folder and norm(old_folder) != norm(folder):
        logger.info(f"New folder path detected: {folder}. Clearing previous scan and analysis records.")
        await db.clear_database()

    # Save folder path to settings
    await db.update_settings({"last_folder": folder})

    thumb_size = int(settings.get("thumbnail_max_size", "512"))

    # Start scanning in background
    bg.add_task(scanner.scan_directory, folder, thumb_size)

    return {
        "message": f"开始扫描: {folder}",
        "status": "scanning",
    }


@app.get("/api/scan/progress")
async def scan_progress():
    return scanner.get_scan_progress()


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------

@app.get("/api/photos")
async def list_photos(
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    status: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    folder_path: str | None = None,
):
    photos, total = await db.get_photos(
        offset=offset, limit=limit,
        status=status, category=category, tag=tag, search=q,
        folder_path=folder_path,
    )
    return {"photos": photos, "total": total, "offset": offset, "limit": limit}


@app.get("/api/photos/{photo_id}")
async def get_photo(photo_id: int):
    photo = await db.get_photo(photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")
    return photo


@app.patch("/api/photos/{photo_id}/ai")
async def edit_photo_ai(photo_id: int, req: AIEdit):
    """Manually edit a single photo's AI fields (description / tags / etc.)."""
    ok = await db.update_ai_fields(
        photo_id,
        description=req.description,
        tags=req.tags,
        category=req.category,
        location=req.location,
        photographer=req.photographer,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="照片尚未分析或不存在，无法编辑")
    return await db.get_photo(photo_id)


@app.post("/api/photos/ai/batch")
async def batch_edit_photo_ai(req: BatchAIEdit):
    """Batch-edit AI fields for selected photos: set description / category /
    photographer, and add or remove tags (merged per photo)."""
    updated = 0
    for pid in req.photo_ids:
        photo = await db.get_photo(pid)
        if not photo or not photo.get("ai"):
            continue
        tags = list(photo["ai"].get("tags") or [])
        if req.add_tags:
            for t in req.add_tags:
                if t and t not in tags:
                    tags.append(t)
        if req.remove_tags:
            tags = [t for t in tags if t not in req.remove_tags]
        new_tags = tags if (req.add_tags or req.remove_tags) else None
        ok = await db.update_ai_fields(
            pid,
            description=req.description if req.description else None,
            tags=new_tags,
            category=req.category if req.category else None,
            photographer=req.photographer if req.photographer else None,
            location=req.location if req.location else None,
        )
        if ok:
            updated += 1
    return {"updated": updated, "total": len(req.photo_ids)}


# ---------------------------------------------------------------------------
# Thumbnails
# ---------------------------------------------------------------------------

@app.get("/api/thumbnails/{photo_id}")
async def get_thumbnail(photo_id: int):
    """Serve thumbnail image for a photo."""
    photo = await db.get_photo(photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")

    # Find root path from scan session
    root_path = str(Path(photo["file_path"]).parent)
    if photo.get("scan_session_id"):
        conn = await db.get_db()
        try:
            rows = await conn.execute_fetchall(
                "SELECT root_path FROM scan_sessions WHERE id = ?",
                (photo["scan_session_id"],),
            )
            if rows:
                root_path = rows[0]["root_path"]
        finally:
            await conn.close()

    rel_path = photo.get("relative_path", photo["file_name"])
    thumb_path = scanner.get_thumbnail_path(root_path, rel_path)

    if thumb_path.exists():
        return FileResponse(str(thumb_path), media_type="image/jpeg")

    # Fall back to original file
    if os.path.exists(photo["file_path"]):
        return FileResponse(photo["file_path"])

    raise HTTPException(status_code=404, detail="缩略图未找到")


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@app.post("/api/analyze")
async def analyze_photos(req: AnalyzeRequest, bg: BackgroundTasks):
    # Update settings if engine specified
    if req.engine:
        await db.update_settings({"engine": req.engine})

    bg.add_task(
        analyzer.analyze_batch,
        photo_ids=req.photo_ids,
        engine_name=req.engine,
        concurrency=req.concurrency,
    )

    return {"message": "AI 分析已启动", "status": "analyzing"}


# Registered before the /{photo_id} route so "pause"/"resume" don't get parsed
# as a photo id.
@app.post("/api/analyze/pause")
async def analyze_pause():
    return analyzer.pause_analysis()


@app.post("/api/analyze/resume")
async def analyze_resume():
    return analyzer.resume_analysis()


@app.post("/api/analyze/{photo_id}")
async def analyze_single(photo_id: int, req: AnalyzeSingleRequest = None):
    try:
        engine_name = req.engine if req else None
        result = await analyzer.analyze_single(photo_id, engine_name=engine_name)
        photo = await db.get_photo(photo_id)
        return {"message": "分析完成", "photo": photo}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analyze/progress")
async def analysis_progress():
    return analyzer.get_analysis_progress()


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------

@app.post("/api/rename")
async def rename_photos(req: RenameRequest):
    try:
        result = await renamer.execute_renames(
            photo_ids=req.photo_ids,
            prefix=req.prefix,
            template=req.template,
            dry_run=req.dry_run,
        )
        return {
            "total": result.total,
            "success": result.success,
            "failed": result.failed,
            "skipped": result.skipped,
            "entries": [
                {
                    "photo_id": e.photo_id,
                    "old_name": e.old_name,
                    "new_name": e.new_name,
                    "status": e.status,
                    "error": e.error,
                }
                for e in result.entries
            ],
            "log_csv": result.log_csv,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rename/preview")
async def rename_preview(req: RenameRequest):
    entries = await renamer.compute_renames(
        photo_ids=req.photo_ids,
        prefix=req.prefix,
        template=req.template,
    )
    return {
        "entries": [
            {
                "photo_id": e.photo_id,
                "old_name": e.old_name,
                "new_name": e.new_name,
            }
            for e in entries
        ]
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@app.get("/api/search")
async def search_keyword(q: str = Query(..., min_length=1)):
    photos, total = await db.get_photos(limit=200, search=q)
    return {"photos": photos, "total": total, "query": q}


@app.post("/api/search/semantic")
async def semantic_search(req: SearchRequest):
    """Semantic search using the AI engine to match tags/descriptions."""
    settings = await db.get_settings()
    engine_name = settings.get("engine", "claude")

    # Scope to the currently active folder so results match the gallery view.
    current_folder = settings.get("last_folder", "")

    # Get analyzed photos within the active folder
    photos, _ = await db.get_photos(
        limit=10000, status="done", folder_path=current_folder or None
    )
    if not photos:
        return {"photos": [], "query": req.query}

    # Build compact index
    compact = [
        {"id": p["id"], "t": "/".join(
            [p["ai"]["category"]] + (p["ai"].get("tags") or [])
        ) if p.get("ai") else "", "d": p["ai"]["description"] if p.get("ai") else ""}
        for p in photos
    ]

    # Build engine kwargs
    engine_kwargs = {}
    if engine_name == "claude":
        engine_kwargs["api_key"] = settings.get("claude_api_key", "")
        engine_kwargs["model"] = settings.get("claude_model", "claude-sonnet-4-6")
    elif engine_name == "ollama":
        engine_kwargs["url"] = settings.get("ollama_url", "http://localhost:11434")
        engine_kwargs["model"] = settings.get("ollama_model", "gemma3:12b")
    elif engine_name == "gemini":
        engine_kwargs["api_key"] = settings.get("gemini_api_key", "")
        engine_kwargs["model"] = settings.get("gemini_model", "gemini-2.5-flash")
    elif engine_name == "zhipu":
        engine_kwargs["api_key"] = settings.get("zhipu_api_key", "")
        engine_kwargs["model"] = settings.get("zhipu_model", "glm-4v-flash")

    engine = get_engine(engine_name, **engine_kwargs)

    prompt = f"""照片索引：{json.dumps(compact, ensure_ascii=False)}
用户的自然语言搜索："{req.query}"
返回语义上匹配的照片 id 数组，按相关度排序。只输出 JSON 数组如 [3,1]，无其他内容。没有匹配则输出 []。"""

    import re
    try:
        if hasattr(engine, 'analyze'):
            # Use text-only call for Claude/Ollama/Gemini/Zhipu
            from engines.claude_engine import ClaudeEngine
            from engines.ollama_engine import OllamaEngine
            from engines.gemini_engine import GeminiEngine
            from engines.zhipu_engine import ZhipuEngine
            if isinstance(engine, ClaudeEngine):
                text = await _claude_text_call(engine, prompt)
            elif isinstance(engine, OllamaEngine):
                text = await _ollama_text_call(engine, prompt)
            elif isinstance(engine, GeminiEngine):
                text = await _gemini_text_call(engine, prompt)
            elif isinstance(engine, ZhipuEngine):
                text = await _zhipu_text_call(engine, prompt)
            else:
                return {"photos": [], "query": req.query, "error": "CLIP 不支持语义搜索"}

            m = re.search(r'\[[\d,\s]*\]', text)
            ids = json.loads(m.group(0) if m else text.replace("```json", "").replace("```", "").strip())

            matched = [p for p in photos if p["id"] in ids]
            # Sort by order in ids
            id_order = {pid: i for i, pid in enumerate(ids)}
            matched.sort(key=lambda p: id_order.get(p["id"], 999))

            return {"photos": matched, "query": req.query, "total": len(matched)}
    except Exception as e:
        return {"photos": [], "query": req.query, "error": str(e)}


async def _claude_text_call(engine, prompt):
    import httpx
    payload = {
        "model": engine.model,
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": engine.api_key,
        "anthropic-version": "2023-06-01",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(engine.API_URL, json=payload, headers=headers)
    data = resp.json()
    return "".join(b["text"] for b in data.get("content", []) if b.get("type") == "text")


async def _ollama_text_call(engine, prompt):
    import httpx
    payload = {
        "model": engine.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{engine.base_url}/api/chat", json=payload)
    data = resp.json()
    return data.get("message", {}).get("content", "")


async def _zhipu_text_call(engine, prompt):
    import httpx
    payload = {
        "model": engine.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(engine.API_URL, json=payload, headers=engine._headers())
    data = resp.json()
    text = ""
    for choice in data.get("choices", []):
        content = choice.get("message", {}).get("content", "")
        if isinstance(content, str):
            text += content
    return text


async def _gemini_text_call(engine, prompt):
    import httpx
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 1000},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            engine.api_url,
            json=payload,
            params={"key": engine.api_key},
            headers={"Content-Type": "application/json"},
        )
    data = resp.json()
    text = ""
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "text" in part:
                text += part["text"]
    return text


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

@app.get("/api/tags")
async def get_tags():
    tags = await db.get_all_tags()
    return {"tags": tags}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# Settings fields holding secrets — never returned in plaintext.
_SECRET_SETTING_KEYS = ("claude_api_key", "gemini_api_key", "zhipu_api_key")
_MASK_CHAR = "…"


def _mask_secret(key: str) -> str:
    """Return a non-reversible masked hint for a secret value."""
    if not key:
        return ""
    return key[:6] + _MASK_CHAR if len(key) > 6 else "***"


@app.get("/api/settings")
async def get_settings():
    settings = await db.get_settings()
    safe = dict(settings)
    # Strip plaintext secrets; expose only a masked hint + a "is set" flag.
    for k in _SECRET_SETTING_KEYS:
        value = safe.pop(k, "")
        safe[f"{k}_masked"] = _mask_secret(value)
        safe[f"{k}_set"] = bool(value)
    return safe


@app.put("/api/settings")
async def update_settings(req: SettingsUpdate):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    # Never overwrite a stored secret with an empty value or with the masked
    # hint that the frontend echoes back during its periodic auto-sync.
    for k in _SECRET_SETTING_KEYS:
        v = updates.get(k)
        if v is not None and (v == "" or _MASK_CHAR in v):
            updates.pop(k)
    if updates:
        await db.update_settings(updates)
    # Return the same sanitized shape as GET so no plaintext secret leaks back.
    return await get_settings()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@app.get("/api/export/csv")
async def export_csv():
    photos, _ = await db.get_photos(limit=100000)

    output = io.StringIO()
    output.write('\ufeff')  # BOM for Excel
    writer = csv.writer(output)
    writer.writerow(["ID", "原文件名", "相对路径", "摄影师", "AI类别", "标签", "描述", "地点",
                     "拍摄日期", "相机", "镜头", "GPS", "建议新名"])

    settings = await db.get_settings()
    entries = await renamer.compute_renames(
        prefix=settings.get("rename_prefix"),
        template=settings.get("rename_template"),
    )
    name_map = {e.photo_id: e.new_name for e in entries}

    for p in photos:
        ai = p.get("ai") or {}
        exif = p.get("exif") or {}
        tags = ", ".join(ai.get("tags", []))
        gps = ""
        if exif.get("gps_lat"):
            gps = f"{exif['gps_lat']:.4f}, {exif.get('gps_lon', 0):.4f}"
        writer.writerow([
            p["id"], p["file_name"], p.get("relative_path", ""),
            ai.get("photographer", ""),
            ai.get("category", ""), tags, ai.get("description", ""),
            ai.get("location", ""),
            exif.get("date_time_original", ""), exif.get("camera_model", ""),
            exif.get("lens_model", ""), gps, name_map.get(p["id"], ""),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=photo-index.csv"},
    )


# ---------------------------------------------------------------------------
# Test Engine Connection
# ---------------------------------------------------------------------------

@app.post("/api/test-engine")
async def test_engine():
    settings = await db.get_settings()
    engine_name = settings.get("engine", "claude")

    engine_kwargs = {}
    if engine_name == "claude":
        engine_kwargs["api_key"] = settings.get("claude_api_key", "")
        engine_kwargs["model"] = settings.get("claude_model", "claude-sonnet-4-6")
    elif engine_name == "ollama":
        engine_kwargs["url"] = settings.get("ollama_url", "http://localhost:11434")
        engine_kwargs["model"] = settings.get("ollama_model", "gemma3:12b")
    elif engine_name == "gemini":
        engine_kwargs["api_key"] = settings.get("gemini_api_key", "")
        engine_kwargs["model"] = settings.get("gemini_model", "gemini-2.5-flash")
    elif engine_name == "zhipu":
        engine_kwargs["api_key"] = settings.get("zhipu_api_key", "")
        engine_kwargs["model"] = settings.get("zhipu_model", "glm-4v-flash")

    try:
        engine = get_engine(engine_name, **engine_kwargs)
        result = await engine.test_connection()
        return result
    except Exception as e:
        return {"ok": False, "message": str(e)}


# ---------------------------------------------------------------------------
# Native Folder Selector Dialog
# ---------------------------------------------------------------------------

@app.post("/api/select-folder")
def select_folder():
    system = platform.system()
    path = None
    logger.info(f"Opening native folder picker on {system}...")

    if system == "Darwin":
        # macOS: Run AppleScript to open folder picker and bring to front
        cmd = [
            "osascript", "-e",
            'tell application "System Events"\n'
            '   activate\n'
            '   set file_path to POSIX path of (choose folder with prompt "请选择照片文件夹")\n'
            'end tell\n'
            'return file_path'
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if res.returncode == 0:
                path = res.stdout.strip()
                logger.info(f"Selected path via AppleScript: {path}")
        except subprocess.TimeoutExpired:
            logger.warning("AppleScript folder select timed out")
        except Exception as e:
            logger.error(f"macOS AppleScript folder select failed: {e}")

    elif system == "Windows":
        # Windows: Run PowerShell to open folder picker
        cmd = [
            "powershell", "-NoProfile", "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dialog.Description = '请选择照片文件夹'; "
            "$res = $dialog.ShowDialog(); "
            "if ($res -eq 'OK') { $dialog.SelectedPath }"
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if res.returncode == 0:
                path = res.stdout.strip()
                logger.info(f"Selected path via PowerShell: {path}")
        except subprocess.TimeoutExpired:
            logger.warning("PowerShell folder select timed out")
        except Exception as e:
            logger.error(f"Windows PowerShell folder select failed: {e}")

    # Fallback to tkinter if no path selected yet (e.g., Linux or script errors)
    if not path:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.wm_attributes("-topmost", 1)  # Bring to front
            path = filedialog.askdirectory(title="请选择照片文件夹")
            root.destroy()
            if path:
                logger.info(f"Selected path via Tkinter: {path}")
        except Exception as e:
            logger.error(f"Tkinter fallback failed: {e}")

    return {"folder_path": path if path else ""}

