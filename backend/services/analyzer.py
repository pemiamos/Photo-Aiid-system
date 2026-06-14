"""
AI analysis orchestrator for Photo-Aiid-system.

Manages concurrent analysis of photos using the selected AI engine.
Dispatches to Claude / Ollama / CLIP and stores results in the database.
"""

import asyncio
import logging
import time
from pathlib import Path

import database as db
from engines import get_engine
from engines.base import AnalysisResult
from services import geocode
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
    "paused": False,
    "started_at": 0.0,
    "elapsed_seconds": 0.0,   # active time, excluding paused spans
    "eta_seconds": None,      # estimated remaining seconds
}

# Guard against overlapping batches. Set synchronously (before any await) so two
# near-simultaneous /api/analyze requests cannot both start a batch and double
# the request rate against rate-limited cloud APIs.
_batch_active = False

# Pause/resume control. Event is "set" while running, "clear" while paused.
_pause_event = asyncio.Event()
_pause_event.set()
# Cancel control. "set" => a cancel has been requested for the current batch.
_cancel_event = asyncio.Event()
# Accumulators for active-time accounting (excludes paused spans).
_active_start = 0.0       # wall-clock time the current active span began
_active_accum = 0.0       # total active seconds accumulated before current span


def pause_analysis() -> dict:
    """Pause the running batch (takes effect before the next photo)."""
    global _active_accum, _active_start
    if _pause_event.is_set() and analysis_progress.get("running"):
        # Close the current active span.
        if _active_start:
            _active_accum += time.time() - _active_start
            _active_start = 0.0
        _pause_event.clear()
        analysis_progress["paused"] = True
    return get_analysis_progress()


def resume_analysis() -> dict:
    """Resume a paused batch."""
    global _active_start
    if not _pause_event.is_set():
        _active_start = time.time()
        _pause_event.set()
        analysis_progress["paused"] = False
    return get_analysis_progress()


def cancel_analysis() -> dict:
    """Request cancellation of the running batch. Takes effect before the next
    photo; the in-flight photo finishes. Also unblocks a paused batch so its
    workers can observe the cancel and exit."""
    if analysis_progress.get("running"):
        _cancel_event.set()
        # Unblock any paused workers so they reach the cancel check and stop.
        _pause_event.set()
        analysis_progress["paused"] = False
    return get_analysis_progress()


import re as _re
from pathlib import PurePath as _PurePath


def guess_photographer(file_name: str, folder_path: str) -> str:
    """Heuristic fallback: pull a likely photographer name (real name or
    nickname) from the leading segment of the filename or folder.

    Names are commonly written as "<name>-<subject>" or "<name>_<subject>",
    e.g. "戴频-盐城滩涂", "老王_西湖", "Ansel-yosemite".
    """
    candidates = []
    if file_name:
        candidates.append(_PurePath(file_name).stem)
    if folder_path:
        # innermost folder first, then outer
        candidates.extend(reversed(str(folder_path).replace("\\", "/").split("/")))

    for cand in candidates:
        head = _re.split(r"[-_—–]", cand.strip(), maxsplit=1)[0].strip()
        if not head:
            continue
        # Chinese name/nickname (2-4 漢字) or an ASCII name (letters only, 2-12).
        if _re.fullmatch(r"[一-鿿]{2,4}", head):
            return head
        if _re.fullmatch(r"[A-Za-z][A-Za-z.]{1,11}", head):
            return head
    return ""


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
    elif engine_name == "gemini":
        engine_kwargs["api_key"] = settings.get("gemini_api_key", "")
        engine_kwargs["model"] = settings.get("gemini_model", "gemini-2.5-flash")
    elif engine_name == "zhipu":
        engine_kwargs["api_key"] = settings.get("zhipu_api_key", "")
        engine_kwargs["model"] = settings.get("zhipu_model", "glm-4v-flash")

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

    # Build rich folder context: root folder name + relative subdirectory
    root_name = Path(root_path).name  # e.g. "2024-京都旅行"
    rel_parent = str(Path(relative_path).parent) if "/" in relative_path else ""
    if rel_parent and rel_parent != ".":
        folder_path = f"{root_name}/{rel_parent}"
    else:
        folder_path = root_name

    # GPS-based location takes priority over AI inference (offline geocoding).
    exif = photo.get("exif") or {}
    gps_location = geocode.reverse_geocode(exif.get("gps_lat"), exif.get("gps_lon"))

    # Build extra context for the prompt: adjacent sequence filenames (naming
    # continuity) + the GPS place name (so the model can dedup filename places
    # against it, per the prompt rules).
    neighbors = await db.get_sibling_file_names(file_path)
    ctx_parts = []
    if neighbors:
        ctx_parts.append(f"相邻序列文件名：{', '.join(neighbors)}")
    if gps_location:
        ctx_parts.append(f"GPS定位地名：{gps_location}")
    extra_context = "\n".join(ctx_parts)

    await db.update_photo_status(photo_id, "analyzing")

    # Retry with backoff for rate-limit (429) errors
    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            result = await engine.analyze(
                image_bytes=image_bytes,
                file_name=photo["file_name"],
                folder_path=folder_path,
                extra_context=extra_context,
            )

            # Location: GPS is the authoritative macro-location when present —
            # it is consistent and accurate, whereas the model's per-image text
            # guess is not. A place name written in the filename/folder only
            # *refines* GPS as a finer sub-level within the same region (e.g.
            # 上海市-松江区-石臼湖); it never replaces the region. This stops a
            # project/series name like 「沿长江」 or the photo subject from
            # overriding correct GPS, which previously made sibling photos in one
            # folder land on wildly different locations. Without GPS, fall back to
            # the filename place, then the AI-inferred location.
            gps_norm = geocode.normalize_location(gps_location)
            place_norm = geocode.normalize_location(result.place_in_name)
            if gps_norm:
                if place_norm and place_norm not in gps_norm and gps_norm not in place_norm:
                    final_location = f"{gps_norm}-{place_norm}"
                else:
                    final_location = gps_norm
            else:
                final_location = place_norm or geocode.normalize_location(result.location)

            # Photographer: prefer the model's field, fall back to a filename/
            # folder heuristic so a name is never silently dropped.
            final_photographer = result.photographer or guess_photographer(
                photo["file_name"], folder_path
            )

            # Store results
            await db.upsert_ai_result(
                photo_id=photo_id,
                category=result.category,
                tags=result.tags,
                description=result.description,
                slug=result.slug,
                location=final_location,
                photographer=final_photographer,
                engine=result.engine,
                raw_response=result.raw_response,
            )

            result.location = final_location
            result.photographer = final_photographer
            return result

        except (RuntimeError, ValueError) as e:
            err_str = str(e)
            if ("429" in err_str or "503" in err_str) and attempt < max_retries:
                wait = (attempt + 1) * 10  # 10s, 20s, 30s
                logger.warning(f"API error, retrying in {wait}s... (attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait)
                continue
            await db.update_photo_status(photo_id, "error", error_message=err_str)
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
    global analysis_progress, _batch_active, _active_start, _active_accum

    # Reject overlapping batches. This runs synchronously before any await, so
    # two near-simultaneous requests cannot both pass this guard.
    if _batch_active:
        logger.warning("Analysis batch already active; ignoring duplicate request")
        return
    _batch_active = True
    # Reset pause/cancel/timing state for the new batch.
    _pause_event.set()
    _cancel_event.clear()
    _active_start = time.time()
    _active_accum = 0.0

    try:
        settings = await db.get_settings()
        if engine_name is None:
            engine_name = settings.get("engine", "claude")
        if concurrency is None:
            concurrency = int(settings.get("analysis_concurrency", "2"))

        # For cloud engines, use sequential processing to avoid rate limits
        is_cloud = engine_name in ("gemini", "claude")
        if is_cloud:
            concurrency = 1

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
            "paused": False,
            "started_at": time.time(),
            "elapsed_seconds": 0.0,
            "eta_seconds": None,
        }

        queue = asyncio.Queue()
        for pid in photo_ids:
            await queue.put(pid)

        async def worker():
            while not queue.empty():
                # Stop pulling new work once a cancel has been requested.
                if _cancel_event.is_set():
                    break
                # Block here while paused (takes effect before each photo).
                await _pause_event.wait()
                # Re-check after unblocking: a cancel sets _pause_event to wake us.
                if _cancel_event.is_set():
                    break
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
                    # Throttle cloud API calls (Gemini free: ~15 RPM)
                    if is_cloud:
                        await asyncio.sleep(5)
                except Exception as e:
                    logger.error(f"Analysis failed for photo {photo_id}: {e}")
                    analysis_progress["errors"] += 1
                    analysis_progress["completed"] += 1

        workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, len(photo_ids)))]
        await asyncio.gather(*workers)
    finally:
        analysis_progress["running"] = False
        analysis_progress["current_file"] = ""
        analysis_progress["cancelled"] = _cancel_event.is_set()
        _cancel_event.clear()
        _batch_active = False


def get_analysis_progress() -> dict:
    p = dict(analysis_progress)
    # Active elapsed time (excludes paused spans).
    elapsed = _active_accum
    if _pause_event.is_set() and _active_start:
        elapsed += time.time() - _active_start
    p["elapsed_seconds"] = round(elapsed, 1)
    # ETA from average time per completed photo.
    completed = p.get("completed", 0)
    total = p.get("total", 0)
    if completed > 0 and total > completed and elapsed > 0:
        per = elapsed / completed
        p["eta_seconds"] = round(per * (total - completed), 1)
    else:
        p["eta_seconds"] = None
    return p


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
