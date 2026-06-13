"""
AI analysis orchestrator for Photo-Aiid-system.

Manages concurrent analysis of photos using the selected AI engine.
Dispatches to Claude / Ollama / CLIP and stores results in the database.
"""

import asyncio
import logging
from pathlib import Path

import database as db
from engines import get_engine
from engines.base import AnalysisResult
from services.scanner import get_thumbnail_path

logger = logging.getLogger(__name__)

# Global analysis state
analysis_progress: dict = {
    "running": False,
    "engine": "",
    "total": 0,
    "completed": 0,
    "errors": 0,
    "current_file": "",
}


async def analyze_single(photo_id: int, engine_name: str | None = None) -> AnalysisResult:
    """Analyze a single photo by its ID."""
    photo = await db.get_photo(photo_id)
    if not photo:
        raise ValueError(f"Photo not found: {photo_id}")

    settings = await db.get_settings()

    if engine_name is None:
        engine_name = settings.get("engine", "claude")

    # Build engine kwargs from settings
    engine_kwargs = {}
    if engine_name == "claude":
        engine_kwargs["api_key"] = settings.get("claude_api_key", "")
        engine_kwargs["model"] = settings.get("claude_model", "claude-sonnet-4-6")
    elif engine_name == "ollama":
        engine_kwargs["url"] = settings.get("ollama_url", "http://localhost:11434")
        engine_kwargs["model"] = settings.get("ollama_model", "gemma3:12b")

    engine = get_engine(engine_name, **engine_kwargs)

    # Read thumbnail bytes for the engine
    file_path = photo["file_path"]
    root_path = str(Path(file_path).parent)

    # Try to find root from scan session
    if photo.get("scan_session_id"):
        db_conn = await db.get_db()
        try:
            rows = await db_conn.execute_fetchall(
                "SELECT root_path FROM scan_sessions WHERE id = ?",
                (photo["scan_session_id"],),
            )
            if rows:
                root_path = rows[0]["root_path"]
        finally:
            await db_conn.close()

    relative_path = photo.get("relative_path", photo["file_name"])
    thumb_path = get_thumbnail_path(root_path, relative_path)

    if thumb_path.exists():
        image_bytes = thumb_path.read_bytes()
    else:
        # Fall back to reading the original file (resize in memory)
        image_bytes = _read_and_resize(file_path)

    # Determine context
    folder_path = str(Path(relative_path).parent) if "/" in relative_path else ""

    await db.update_photo_status(photo_id, "analyzing")

    try:
        result = await engine.analyze(
            image_bytes=image_bytes,
            file_name=photo["file_name"],
            folder_path=folder_path,
        )

        # Store results
        await db.upsert_ai_result(
            photo_id=photo_id,
            category=result.category,
            tags=result.tags,
            description=result.description,
            slug=result.slug,
            engine=result.engine,
            raw_response=result.raw_response,
        )

        return result

    except Exception as e:
        await db.update_photo_status(photo_id, "error")
        raise


async def analyze_batch(
    photo_ids: list[int] | None = None,
    engine_name: str | None = None,
    concurrency: int | None = None,
):
    """
    Analyze multiple photos concurrently.
    If photo_ids is None, analyze all photos with status 'queued' or 'error'.
    """
    global analysis_progress

    settings = await db.get_settings()
    if engine_name is None:
        engine_name = settings.get("engine", "claude")
    if concurrency is None:
        concurrency = int(settings.get("analysis_concurrency", "2"))

    # Get photos to analyze
    if photo_ids is None:
        photos, _ = await db.get_photos(limit=10000, status="queued")
        error_photos, _ = await db.get_photos(limit=10000, status="error")
        photos.extend(error_photos)
        photo_ids = [p["id"] for p in photos]

    if not photo_ids:
        return

    analysis_progress = {
        "running": True,
        "engine": engine_name,
        "total": len(photo_ids),
        "completed": 0,
        "errors": 0,
        "current_file": "",
    }

    queue = asyncio.Queue()
    for pid in photo_ids:
        await queue.put(pid)

    async def worker():
        while not queue.empty():
            try:
                photo_id = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            photo = await db.get_photo(photo_id)
            if photo:
                analysis_progress["current_file"] = photo["file_name"]

            try:
                await analyze_single(photo_id, engine_name=engine_name)
                analysis_progress["completed"] += 1
            except Exception as e:
                logger.error(f"Analysis failed for photo {photo_id}: {e}")
                analysis_progress["errors"] += 1
                analysis_progress["completed"] += 1

    workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, len(photo_ids)))]
    await asyncio.gather(*workers)

    analysis_progress["running"] = False
    analysis_progress["current_file"] = ""


def get_analysis_progress() -> dict:
    return dict(analysis_progress)


def _read_and_resize(file_path: str, max_size: int = 512) -> bytes:
    """Read an image file and resize it to max_size, return JPEG bytes."""
    import io
    from PIL import Image

    with Image.open(file_path) as img:
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=72)
        return buf.getvalue()
