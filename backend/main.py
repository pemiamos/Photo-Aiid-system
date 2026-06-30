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


# ---------------------------------------------------------------------------
# 加载 .env（KEY=VALUE）到环境变量。必须在 import intake 之前执行，
# 因为 intake.py 在模块顶层读取 OSS_* 等配置。无第三方依赖；
# 用 setdefault，使真实环境变量（export）优先于 .env 文件。
# ---------------------------------------------------------------------------
def _load_dotenv() -> None:
    here = Path(__file__).resolve().parent
    for envfile in (here.parent / ".env", here / ".env"):
        if not envfile.is_file():
            continue
        for raw in envfile.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

import database as db
import intake
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
    await intake.init_intake_db()
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
    # 允许桌面 App 投稿模式从任意来源跨域调用投稿接口（Tauri webview 等）。
    # 生产可收紧为具体来源；admin 用 SameSite=Lax Cookie，跨站 POST 不带 Cookie，无 CSRF 暴露。
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 投稿征稿模块（网页上传页 + 凭证接口 + 看板）。必须在 "/" 静态兜底挂载之前注册。
app.include_router(intake.router)


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class ScanRequest(BaseModel):
    folder_path: str

class FolderRequest(BaseModel):
    path: str

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
    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_base_url: str | None = None
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

    # 多文件夹持久化库：换文件夹**不再清库**。每扫一个文件夹就并入库（按 file_path
    # upsert，重扫同路径只更新不重复），历史文件夹的元数据与 AI 结果长期保留，供索引表
    # 全局搜索跨全库检索。清理交给「已索引文件夹」的移除/清空入口显式完成。
    settings = await db.get_settings()

    # Save folder path to settings（仅记录「当前工作文件夹」，画廊据此过滤显示）
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
# 已索引文件夹注册表（多文件夹持久库的管理）
# ---------------------------------------------------------------------------

@app.get("/api/folders")
async def list_folders():
    """列出所有曾扫描过的文件夹及其张数/已分析数/最近扫描时间，并标注路径是否仍存在。"""
    folders = await db.get_indexed_folders()
    for f in folders:
        f["exists"] = os.path.isdir(f["path"])
    return {"folders": folders}


@app.post("/api/folders/remove")
async def remove_folder(req: FolderRequest):
    """移除单个已索引文件夹（删除其下所有照片元数据/AI 结果与扫描记录）。"""
    path = (req.path or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="缺少路径")
    deleted = await db.remove_folder(path)
    # 若移除的是当前工作文件夹，顺手清掉 last_folder
    settings = await db.get_settings()
    cur = (settings.get("last_folder", "") or "").replace("\\", "/").rstrip("/")
    if cur and cur == path.replace("\\", "/").rstrip("/"):
        await db.update_settings({"last_folder": ""})
    return {"removed": deleted, "path": path}


@app.post("/api/folders/clear")
async def clear_folders():
    """清空整个索引库（所有文件夹）。"""
    await db.clear_database()
    await db.update_settings({"last_folder": ""})
    return {"ok": True}


@app.post("/api/folders/clean-stale")
async def clean_stale_folders():
    """清理失效文件夹：路径在磁盘上已不存在的，整条移除。"""
    folders = await db.get_indexed_folders()
    removed = []
    for f in folders:
        if not os.path.isdir(f["path"]):
            await db.remove_folder(f["path"])
            removed.append(f["path"])
    return {"removed": removed, "count": len(removed)}


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------

@app.get("/api/photos")
async def list_photos(
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=100000),
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

    # 按需生成：扫描阶段不再全量生成缩略图（上万张库才放得下），首次被请求（搜索命中、
    # 滚动到可见）时才从原图实时生成 512px 并缓存，下次直接命中缓存。
    if os.path.exists(photo["file_path"]):
        settings = await db.get_settings()
        thumb_size = int(settings.get("thumbnail_max_size", "512"))
        try:
            ok = await asyncio.to_thread(
                scanner.generate_thumbnail, photo["file_path"], thumb_path, thumb_size
            )
            if ok and thumb_path.exists():
                return FileResponse(str(thumb_path), media_type="image/jpeg")
        except Exception as e:
            logger.warning(f"按需生成缩略图失败 {photo['file_path']}: {e}")
        # 兜底：生成失败则直接回原图
        return FileResponse(photo["file_path"])

    raise HTTPException(status_code=404, detail="缩略图未找到（原文件可能已移动或删除）")


@app.get("/api/originals/{photo_id}")
async def get_original(photo_id: int):
    """Serve the full-resolution original file as a download.

    Used by the gallery's drag-to-desktop feature: dragging a thumbnail to a
    folder/Desktop pulls the original here. If the photo has been analyzed, the
    download is named with the AI-suggested new filename; otherwise it keeps the
    original name.
    """
    photo = await db.get_photo(photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")

    src = photo["file_path"]
    if not os.path.exists(src):
        raise HTTPException(status_code=404, detail="原始文件不存在")

    download_name = photo["file_name"]
    if photo.get("ai"):
        entries = await renamer.compute_renames(photo_ids=[photo_id])
        if entries:
            download_name = entries[0].new_name

    return FileResponse(src, filename=download_name)


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


@app.post("/api/analyze/cancel")
async def analyze_cancel():
    return analyzer.cancel_analysis()


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
    photos, total = await db.get_photos(limit=100000, search=q)
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
    elif engine_name == "openai":
        engine_kwargs["api_key"] = settings.get("openai_api_key", "")
        engine_kwargs["model"] = settings.get("openai_model", "gpt-4o-mini")
        engine_kwargs["base_url"] = settings.get("openai_base_url", "")

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
            from engines.openai_engine import OpenAIEngine
            if isinstance(engine, ClaudeEngine):
                text = await _claude_text_call(engine, prompt)
            elif isinstance(engine, OllamaEngine):
                text = await _ollama_text_call(engine, prompt)
            elif isinstance(engine, GeminiEngine):
                text = await _gemini_text_call(engine, prompt)
            elif isinstance(engine, (ZhipuEngine, OpenAIEngine)):
                # 两者都是 OpenAI 兼容的 chat/completions，文本调用形状一致
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
_SECRET_SETTING_KEYS = ("claude_api_key", "gemini_api_key", "zhipu_api_key", "openai_api_key")
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

@app.get("/api/openai/models")
async def openai_models():
    """拉取当前配置的 OpenAI（或兼容网关）实际支持的模型列表。

    硬编码模型名对自建/代理网关并不成立——它们各有各的模型清单。改为调用标准的
    GET {base_url}/models，把真实可用的 id 返回给前端下拉。读取已保存的 key/base。
    """
    import httpx
    settings = await db.get_settings()
    api_key = settings.get("openai_api_key", "")
    base_url = (settings.get("openai_base_url", "") or "https://api.openai.com/v1").rstrip("/")
    if not api_key:
        return {"ok": False, "message": "未配置 API Key", "models": []}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code != 200:
            return {"ok": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}", "models": []}
        data = resp.json()
        # 兼容多种返回结构：{data:[...]} / {models:[...]} / 直接数组；
        # 每项可能是字符串，或带 id / name / model 字段的对象。
        if isinstance(data, dict):
            rows = data.get("data") or data.get("models") or []
        elif isinstance(data, list):
            rows = data
        else:
            rows = []
        ids = set()
        for m in rows:
            if isinstance(m, str):
                mid = m.strip()
            elif isinstance(m, dict):
                mid = str(m.get("id") or m.get("name") or m.get("model") or "").strip()
            else:
                mid = ""
            if mid:
                ids.add(mid)
        ids = sorted(ids)
        # 官方 /models 会把账号下所有模型都列出来（embedding/tts/whisper/dall-e…）。
        # 过滤掉明显非「看图聊天」的，下拉更干净；过滤后为空则退回完整列表。
        _NON_CHAT = (
            "embedding", "tts", "whisper", "audio", "transcribe", "realtime",
            "dall-e", "dalle", "image", "moderation", "rerank", "guard",
            "search", "similarity", "babbage", "davinci", "ada", "curie",
        )
        chat = [i for i in ids if not any(k in i.lower() for k in _NON_CHAT)]
        return {"ok": True, "models": chat or ids, "total": len(ids)}
    except Exception as e:
        return {"ok": False, "message": str(e), "models": []}


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
    elif engine_name == "openai":
        engine_kwargs["api_key"] = settings.get("openai_api_key", "")
        engine_kwargs["model"] = settings.get("openai_model", "gpt-4o-mini")
        engine_kwargs["base_url"] = settings.get("openai_base_url", "")

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


# ---------------------------------------------------------------------------
# 在系统文件管理器中定位某张照片（Finder / 资源管理器选中该文件）
# ---------------------------------------------------------------------------

@app.post("/api/photos/{photo_id}/reveal")
async def reveal_photo(photo_id: int):
    """在 Finder/资源管理器里打开照片所在文件夹并选中它。

    路径以服务器侧数据库记录的 file_path 为准（不信任前端传入），避免越权打开任意目录。
    仅桌面端有意义；纯 API/无桌面环境会返回 ok=False。
    """
    photo = await db.get_photo(photo_id)
    if not photo or not photo.get("file_path"):
        raise HTTPException(404, "照片不存在或无本地路径")
    target = os.path.abspath(photo["file_path"])
    if not os.path.exists(target):
        return {"ok": False, "message": "文件已不在原位置（可能被移动或删除）", "path": target}

    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", "-R", target], timeout=15)
        elif system == "Windows":
            # explorer 用 /select 选中文件；返回码非 0 不代表失败，故不检查
            subprocess.run(["explorer", "/select,", target], timeout=15)
        else:
            # Linux：多数文件管理器不支持选中单文件，退而打开所在目录
            subprocess.run(["xdg-open", os.path.dirname(target)], timeout=15)
        return {"ok": True, "path": target}
    except Exception as e:
        logger.error(f"Reveal photo {photo_id} failed: {e}")
        return {"ok": False, "message": str(e), "path": target}


# ---------------------------------------------------------------------------
# 托管前端构建产物 (生产 / 打包模式)
# 必须放在所有 @app.<method> 路由定义之后：挂在 "/" 的 StaticFiles 会兜底
# 一切未被 /api 等路由命中的请求，并以 index.html 支持单页应用。
# ---------------------------------------------------------------------------
from fastapi.staticfiles import StaticFiles  # noqa: E402

_dist = os.environ.get(
    "PHOTO_AIID_DIST",
    os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"),
)
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
    logger.info(f"Serving frontend from: {_dist}")
else:
    logger.info(f"Frontend dist not found ({_dist}); API-only mode.")

