"""
Batch rename service for Photo-Aiid-system.

Applies naming template, handles deduplication, executes physical renames,
and generates rename log.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import database as db

logger = logging.getLogger(__name__)


@dataclass
class RenameEntry:
    photo_id: int
    old_name: str
    old_path: str
    new_name: str
    new_path: str
    status: str = "pending"  # pending | ok | error
    error: str = ""


@dataclass
class RenameResult:
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    entries: list[RenameEntry] = field(default_factory=list)
    log_csv: str = ""


def sanitize_filename(s: str) -> str:
    """Remove illegal filename characters."""
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(s)).strip()


def format_date(date_str: str | None) -> str:
    """Convert EXIF date (YYYY:MM:DD HH:MM:SS) to compact format (YYYYMMDD)."""
    if not date_str:
        return "未知"
    # Try common EXIF date format
    try:
        parts = date_str.replace("-", ":").split(" ")[0].split(":")
        if len(parts) >= 3:
            return f"{parts[0]}{parts[1]}{parts[2]}"
    except Exception:
        pass
    return "未知"


async def compute_renames(
    photo_ids: list[int] | None = None,
    prefix: str | None = None,
    template: str | None = None,
) -> list[RenameEntry]:
    """
    Compute new names for a batch of photos without executing renames.
    Returns list of RenameEntry with proposed new names.
    """
    settings = await db.get_settings()
    if prefix is None:
        prefix = settings.get("rename_prefix", "SDEXP")
    if template is None:
        template = settings.get("rename_template", "[前缀]_[AI标签]_[日期]_[序号]")

    # Fetch photos with AI results
    if photo_ids:
        photos = []
        for pid in photo_ids:
            p = await db.get_photo(pid)
            if p:
                photos.append(p)
    else:
        photos, _ = await db.get_photos(limit=10000, status="done")

    entries: list[RenameEntry] = []
    used_names: set[str] = set()

    for seq, photo in enumerate(photos, start=1):
        ai = photo.get("ai")
        if not ai:
            continue

        # Get EXIF date
        exif_date = ""
        exif = photo.get("exif")
        if exif and exif.get("date_time_original"):
            exif_date = format_date(exif["date_time_original"])
        if not exif_date or exif_date == "未知":
            # Fall back to file modification time
            try:
                mtime = os.path.getmtime(photo["file_path"])
                from datetime import datetime
                dt = datetime.fromtimestamp(mtime)
                exif_date = dt.strftime("%Y%m%d")
            except Exception:
                exif_date = "未知"

        # Apply template
        base = sanitize_filename(
            template
            .replace("[前缀]", prefix)
            .replace("[AI标签]", ai.get("category", "未分类"))
            .replace("[日期]", exif_date)
            .replace("[序号]", str(seq).zfill(3))
        )

        old_ext = Path(photo["file_name"]).suffix or ".jpg"
        new_name = base + old_ext

        # Deduplicate
        n = 2
        lower_name = new_name.lower()
        while lower_name in used_names:
            new_name = f"{base}-{n}{old_ext}"
            lower_name = new_name.lower()
            n += 1
        used_names.add(lower_name)

        old_dir = str(Path(photo["file_path"]).parent)
        new_path = os.path.join(old_dir, new_name)

        entries.append(RenameEntry(
            photo_id=photo["id"],
            old_name=photo["file_name"],
            old_path=photo["file_path"],
            new_name=new_name,
            new_path=new_path,
        ))

    return entries


async def execute_renames(
    entries: list[RenameEntry] | None = None,
    photo_ids: list[int] | None = None,
    prefix: str | None = None,
    template: str | None = None,
    dry_run: bool = False,
) -> RenameResult:
    """
    Execute physical renames on disk.
    If entries is None, computes them first.
    """
    if entries is None:
        entries = await compute_renames(photo_ids, prefix, template)

    result = RenameResult(total=len(entries))

    for entry in entries:
        if entry.old_name == entry.new_name:
            entry.status = "skipped"
            result.skipped += 1
            continue

        if dry_run:
            entry.status = "ok"
            result.success += 1
            continue

        try:
            # Check source exists
            if not os.path.exists(entry.old_path):
                entry.status = "error"
                entry.error = "Source file not found"
                result.failed += 1
                continue

            # Check destination doesn't already exist (with different casing)
            if os.path.exists(entry.new_path) and entry.old_path != entry.new_path:
                entry.status = "error"
                entry.error = "Destination already exists"
                result.failed += 1
                continue

            os.rename(entry.old_path, entry.new_path)

            # Update database
            await db.update_photo_name(
                entry.photo_id, entry.new_name, entry.new_path
            )

            entry.status = "ok"
            result.success += 1

        except Exception as e:
            entry.status = "error"
            entry.error = str(e)
            result.failed += 1
            logger.error(f"Rename failed: {entry.old_name} -> {entry.new_name}: {e}")

    result.entries = entries

    # Generate CSV log
    result.log_csv = _generate_csv_log(entries)

    return result


def _generate_csv_log(entries: list[RenameEntry]) -> str:
    """Generate a CSV string with BOM for Excel compatibility."""
    lines = ["\ufeff相对路径,原文件名,新文件名,结果,错误信息"]
    for e in entries:
        rel_dir = str(Path(e.old_path).parent)
        row = [
            _csv_escape(rel_dir),
            _csv_escape(e.old_name),
            _csv_escape(e.new_name),
            _csv_escape(e.status),
            _csv_escape(e.error),
        ]
        lines.append(",".join(row))
    return "\n".join(lines)


def _csv_escape(s: str) -> str:
    """Escape a string for CSV."""
    s = str(s).replace('"', '""')
    return f'"{s}"'
