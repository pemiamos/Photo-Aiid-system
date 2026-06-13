"""
File scanner service for Photo-Aiid-system.

Recursively scans a directory for image files, extracts EXIF data using Pillow,
generates thumbnails, and stores everything in the database.
Supports incremental scanning (skips files with same path+size+mtime).
"""

import asyncio
import logging
import mimetypes
import os
import time
from pathlib import Path

from PIL import Image, ExifTags
import database as db

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".heic", ".heif", ".bmp", ".tiff", ".tif",
}

# Global scan state for progress tracking
scan_progress: dict = {
    "running": False,
    "session_id": None,
    "root_path": "",
    "total_files": 0,
    "scanned_files": 0,
    "skipped_files": 0,
    "error_count": 0,
}


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def get_thumbnail_dir(root_path: str) -> Path:
    """Return the .thumbnails directory inside the scanned root."""
    thumb_dir = Path(root_path) / ".thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    return thumb_dir


def get_thumbnail_path(root_path: str, relative_path: str) -> Path:
    """Compute thumbnail path preserving relative structure."""
    thumb_dir = get_thumbnail_dir(root_path)
    # Use relative path with flattened separators for uniqueness
    safe_name = relative_path.replace("/", "__").replace("\\", "__")
    # Always save thumbnails as JPEG
    name = Path(safe_name).stem + ".jpg"
    return thumb_dir / name


def generate_thumbnail(image_path: str, output_path: Path, max_size: int = 512) -> bool:
    """Generate a JPEG thumbnail. Returns True on success."""
    try:
        with Image.open(image_path) as img:
            # Handle EXIF orientation
            try:
                exif = img.getexif()
                orientation_tag = None
                for tag, name in ExifTags.TAGS.items():
                    if name == "Orientation":
                        orientation_tag = tag
                        break
                if orientation_tag and orientation_tag in exif:
                    orientation = exif[orientation_tag]
                    if orientation == 3:
                        img = img.rotate(180, expand=True)
                    elif orientation == 6:
                        img = img.rotate(270, expand=True)
                    elif orientation == 8:
                        img = img.rotate(90, expand=True)
            except Exception:
                pass

            # Convert to RGB for JPEG
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")

            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(output_path), "JPEG", quality=72, optimize=True)
            return True
    except Exception as e:
        logger.warning(f"Thumbnail generation failed for {image_path}: {e}")
        return False


def extract_exif(image_path: str) -> dict:
    """Extract EXIF data using Pillow."""
    result = {
        "date_time_original": None,
        "camera_model": None,
        "lens_model": None,
        "f_number": None,
        "iso": None,
        "focal_length": None,
        "exposure_time": None,
        "gps_lat": None,
        "gps_lon": None,
    }
    try:
        with Image.open(image_path) as img:
            exif_data = img.getexif()
            if not exif_data:
                return result

            # Build tag name map
            tag_map = {}
            for tag_id, tag_name in ExifTags.TAGS.items():
                tag_map[tag_name] = tag_id

            # Basic EXIF fields
            if "DateTime" in tag_map and tag_map["DateTime"] in exif_data:
                result["date_time_original"] = str(exif_data[tag_map["DateTime"]])
            if "DateTimeOriginal" in tag_map and tag_map["DateTimeOriginal"] in exif_data:
                result["date_time_original"] = str(exif_data[tag_map["DateTimeOriginal"]])

            if "Model" in tag_map and tag_map["Model"] in exif_data:
                result["camera_model"] = str(exif_data[tag_map["Model"]])
            if "LensModel" in tag_map and tag_map["LensModel"] in exif_data:
                result["lens_model"] = str(exif_data[tag_map["LensModel"]])

            if "FNumber" in tag_map and tag_map["FNumber"] in exif_data:
                val = exif_data[tag_map["FNumber"]]
                if hasattr(val, "numerator"):
                    result["f_number"] = float(val)
                else:
                    result["f_number"] = float(val) if val else None

            if "ISOSpeedRatings" in tag_map and tag_map["ISOSpeedRatings"] in exif_data:
                result["iso"] = int(exif_data[tag_map["ISOSpeedRatings"]])

            if "FocalLength" in tag_map and tag_map["FocalLength"] in exif_data:
                val = exif_data[tag_map["FocalLength"]]
                if hasattr(val, "numerator"):
                    result["focal_length"] = float(val)
                else:
                    result["focal_length"] = float(val) if val else None

            if "ExposureTime" in tag_map and tag_map["ExposureTime"] in exif_data:
                val = exif_data[tag_map["ExposureTime"]]
                if hasattr(val, "numerator") and val.denominator:
                    result["exposure_time"] = f"{val.numerator}/{val.denominator}"
                else:
                    result["exposure_time"] = str(val)

            # GPS data (from IFD)
            try:
                ifd = exif_data.get_ifd(ExifTags.IFD.GPSInfo)
                if ifd:
                    # GPSLatitude = tag 2, GPSLatitudeRef = tag 1
                    # GPSLongitude = tag 4, GPSLongitudeRef = tag 3
                    def _dms_to_decimal(dms, ref):
                        """Convert DMS tuple to decimal degrees."""
                        d, m, s = [float(x) for x in dms]
                        dec = d + m / 60.0 + s / 3600.0
                        if ref in ("S", "W"):
                            dec = -dec
                        return dec

                    if 2 in ifd and 1 in ifd:
                        result["gps_lat"] = _dms_to_decimal(ifd[2], ifd[1])
                    if 4 in ifd and 3 in ifd:
                        result["gps_lon"] = _dms_to_decimal(ifd[4], ifd[3])
            except Exception:
                pass

            # Try ExifIFD for DateTimeOriginal
            try:
                exif_ifd = exif_data.get_ifd(ExifTags.IFD.Exif)
                if exif_ifd:
                    # DateTimeOriginal = 36867, DateTimeDigitized = 36868
                    if 36867 in exif_ifd:
                        result["date_time_original"] = str(exif_ifd[36867])
                    # ISOSpeedRatings = 34855
                    if 34855 in exif_ifd and result["iso"] is None:
                        result["iso"] = int(exif_ifd[34855])
                    # FNumber = 33437
                    if 33437 in exif_ifd and result["f_number"] is None:
                        val = exif_ifd[33437]
                        result["f_number"] = float(val)
                    # FocalLength = 37386
                    if 37386 in exif_ifd and result["focal_length"] is None:
                        val = exif_ifd[37386]
                        result["focal_length"] = float(val)
                    # ExposureTime = 33434
                    if 33434 in exif_ifd and result["exposure_time"] is None:
                        val = exif_ifd[33434]
                        if hasattr(val, "numerator") and val.denominator:
                            result["exposure_time"] = f"{val.numerator}/{val.denominator}"
                        else:
                            result["exposure_time"] = str(val)
                    # LensModel = 42036
                    if 42036 in exif_ifd and result["lens_model"] is None:
                        result["lens_model"] = str(exif_ifd[42036])
            except Exception:
                pass

    except Exception as e:
        logger.debug(f"EXIF extraction failed for {image_path}: {e}")

    return result


def get_image_dimensions(image_path: str) -> tuple[int, int]:
    """Get image width and height quickly."""
    try:
        with Image.open(image_path) as img:
            return img.size  # (width, height)
    except Exception:
        return (0, 0)


async def scan_directory(
    root_path: str,
    thumbnail_max_size: int = 512,
) -> int:
    """
    Scan a directory recursively for image files.
    Returns the scan session id.
    """
    global scan_progress

    root = Path(root_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Directory does not exist: {root_path}")

    session_id = await db.create_scan_session(str(root))

    # Collect all image files first
    all_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden directories
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if is_image_file(fpath):
                all_files.append(fpath)

    scan_progress = {
        "running": True,
        "session_id": session_id,
        "root_path": str(root),
        "total_files": len(all_files),
        "scanned_files": 0,
        "skipped_files": 0,
        "error_count": 0,
    }

    photo_count = 0
    cpu_count = os.cpu_count() or 4
    concurrency = max(4, min(8, cpu_count))
    sem = asyncio.Semaphore(concurrency)

    # Establish a shared DB connection for all insertions in this scan session
    conn = await db.get_db()

    try:
        # Load all existing photo records for memory-based incremental scan
        existing_photos = await db.get_photos_in_directory(str(root))

        async def process_file(fpath: Path):
            nonlocal photo_count
            async with sem:
                try:
                    # CPU/IO bound stat
                    stat = await asyncio.to_thread(fpath.stat)
                    file_size = stat.st_size
                    file_mtime = stat.st_mtime
                    fpath_str = str(fpath)

                    # Incremental check using in-memory dict
                    if fpath_str in existing_photos:
                        db_id, db_size, db_mtime = existing_photos[fpath_str]
                        if db_size == file_size and abs(db_mtime - file_mtime) < 0.1:
                            scan_progress["skipped_files"] += 1
                            scan_progress["scanned_files"] += 1
                            return

                    relative_path = str(fpath.relative_to(root))
                    mime_type = mimetypes.guess_type(str(fpath))[0] or ""
                    
                    # CPU bound dimension check
                    width, height = await asyncio.to_thread(get_image_dimensions, str(fpath))

                    # Insert photo record (using shared conn)
                    photo_id = await db.insert_photo(
                        file_name=fpath.name,
                        file_path=fpath_str,
                        relative_path=relative_path,
                        file_size=file_size,
                        file_mtime=file_mtime,
                        mime_type=mime_type,
                        width=width,
                        height=height,
                        scan_session_id=session_id,
                        conn=conn,
                    )

                    if photo_id:
                        # CPU bound EXIF check
                        exif = await asyncio.to_thread(extract_exif, str(fpath))
                        # Upsert exif (using shared conn)
                        await db.upsert_exif(photo_id, exif, conn=conn)

                        # CPU bound thumbnail generation
                        thumb_path = get_thumbnail_path(str(root), relative_path)
                        await asyncio.to_thread(generate_thumbnail, str(fpath), thumb_path, max_size=thumbnail_max_size)

                        photo_count += 1

                    scan_progress["scanned_files"] += 1

                except Exception as e:
                    logger.error(f"Error scanning {fpath}: {e}")
                    scan_progress["error_count"] += 1
                    scan_progress["scanned_files"] += 1

        if all_files:
            await asyncio.gather(*(process_file(fpath) for fpath in all_files))

    finally:
        # Clean up the shared database connection
        await conn.close()

    await db.update_scan_session(session_id, photo_count, "completed")
    scan_progress["running"] = False

    return session_id


def get_scan_progress() -> dict:
    return dict(scan_progress)
