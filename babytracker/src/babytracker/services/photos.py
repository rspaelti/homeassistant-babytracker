"""Foto-Upload-Service: speichert Original + komprimierte Display-Variante + Thumb.

EXIF-Daten (Aufnahmedatum, Orientierung, GPS, Kamera) werden ausgelesen.
HEIC/HEIF wird absichtlich nicht unterstützt — iOS-Browser konvertieren das
beim File-Upload ohnehin automatisch zu JPEG.
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException, UploadFile
from PIL import ExifTags, Image, ImageOps

from babytracker.config import settings
from babytracker.models import Photo

logger = logging.getLogger(__name__)

ALLOWED_MIME: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
DISPLAY_MAX_EDGE = 2560
THUMB_MAX_EDGE = 400
JPEG_DISPLAY_QUALITY = 85
JPEG_THUMB_QUALITY = 80

TZ = ZoneInfo(settings.timezone)


def _gps_to_decimal(coord, ref: str | None) -> float | None:
    try:
        d, m, s = coord
        value = float(d) + float(m) / 60.0 + float(s) / 3600.0
    except (TypeError, ValueError):
        return None
    if ref in ("S", "W"):
        value = -value
    return value


def _read_exif(img: Image.Image) -> dict:
    out: dict = {}
    raw = img.getexif()
    if not raw:
        return out

    for tag_id, value in raw.items():
        name = ExifTags.TAGS.get(tag_id)
        if name == "Make":
            out["camera_make"] = str(value).strip()[:64]
        elif name == "Model":
            out["camera_model"] = str(value).strip()[:64]
        elif name == "DateTimeOriginal":
            out["datetime_original"] = str(value).strip()

    try:
        exif_ifd = raw.get_ifd(ExifTags.IFD.Exif)
        for tag_id, value in exif_ifd.items():
            name = ExifTags.TAGS.get(tag_id)
            if name == "DateTimeOriginal" and "datetime_original" not in out:
                out["datetime_original"] = str(value).strip()
    except (KeyError, AttributeError):
        pass

    try:
        gps_ifd = raw.get_ifd(ExifTags.IFD.GPSInfo)
        gps = {ExifTags.GPSTAGS.get(t, t): v for t, v in gps_ifd.items()}
        lat = _gps_to_decimal(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
        lng = _gps_to_decimal(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
        if lat is not None and lng is not None:
            out["gps_lat"] = lat
            out["gps_lng"] = lng
    except (KeyError, AttributeError):
        pass

    return out


def _parse_exif_datetime(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S").replace(tzinfo=TZ)
    except (ValueError, TypeError):
        return None


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


async def save_upload(
    upload: UploadFile,
    *,
    linked_table: str | None,
    linked_id: int | None,
    uploader_user_id: int | None,
    visibility: str = "family",
) -> Photo:
    """Liest Upload, speichert Original + Display + Thumb, gibt ein Photo-Objekt zurück.

    Der Aufrufer ist verantwortlich für `session.add(photo)` und commit.
    """
    if upload.content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"Dateityp {upload.content_type or 'unbekannt'} nicht unterstützt "
            "(erlaubt: JPEG, PNG, WebP)",
        )

    raw = await upload.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Leere Datei")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Datei grösser als 20 MB")

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Bild kann nicht gelesen werden: {exc}") from exc

    width, height = img.size
    exif = _read_exif(img)

    taken_at: datetime | None = None
    if "datetime_original" in exif:
        taken_at = _parse_exif_datetime(exif["datetime_original"])
    if taken_at is None:
        taken_at = datetime.now(TZ)

    photo_uuid = uuid.uuid4().hex
    month = taken_at.astimezone(TZ).strftime("%Y-%m")
    ext = ALLOWED_MIME[upload.content_type]

    rel_original = f"originals/{month}/{photo_uuid}{ext}"
    rel_display = f"display/{month}/{photo_uuid}.jpg"
    rel_thumb = f"thumbs/{month}/{photo_uuid}.jpg"

    base = Path(settings.photos_dir)
    abs_original = base / rel_original
    abs_display = base / rel_display
    abs_thumb = base / rel_thumb

    for path in (abs_original, abs_display, abs_thumb):
        _ensure_parent(path)

    abs_original.write_bytes(raw)

    display_img = ImageOps.exif_transpose(img)
    if display_img.mode not in ("RGB", "L"):
        display_img = display_img.convert("RGB")
    display_img.thumbnail((DISPLAY_MAX_EDGE, DISPLAY_MAX_EDGE), Image.Resampling.LANCZOS)
    display_img.save(abs_display, "JPEG", quality=JPEG_DISPLAY_QUALITY, optimize=True)

    thumb_img = display_img.copy()
    thumb_img.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE), Image.Resampling.LANCZOS)
    thumb_img.save(abs_thumb, "JPEG", quality=JPEG_THUMB_QUALITY, optimize=True)

    return Photo(
        taken_at=taken_at,
        rel_path=rel_display,
        thumb_path=rel_thumb,
        original_path=rel_original,
        mime=upload.content_type,
        width=width,
        height=height,
        size_bytes=len(raw),
        gps_lat=exif.get("gps_lat"),
        gps_lng=exif.get("gps_lng"),
        camera_make=exif.get("camera_make"),
        camera_model=exif.get("camera_model"),
        uploader_user_id=uploader_user_id,
        linked_table=linked_table,
        linked_id=linked_id,
        visibility=visibility,
    )


def delete_photo_files(photo: Photo) -> None:
    """Löscht Original, Display und Thumb von der Disk (Datei-Ebene)."""
    base = Path(settings.photos_dir)
    for rel in (photo.rel_path, photo.thumb_path, photo.original_path):
        if not rel:
            continue
        try:
            (base / rel).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Foto-Datei %s konnte nicht gelöscht werden: %s", rel, exc)
