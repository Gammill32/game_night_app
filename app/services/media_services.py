# services/media_services.py
"""Uploaded images: night photos and food receipts (ported from Poker Night).

Every upload is decoded with Pillow (HEIC via pillow-heif), rotated upright
from its EXIF orientation, then re-encoded as a fresh JPEG with no metadata,
so EXIF (including GPS location) never reaches disk. Files live under
MEDIA_DIR (a bind-mounted ZFS dataset in production), never in the database,
and are only served through routes that check the viewer can see the night.
"""

import os
import secrets
from contextlib import contextmanager

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()

ALLOWED_FORMATS = {"JPEG", "PNG", "HEIF"}
MAX_PIXELS = 60_000_000  # guards against decompression bombs
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class MediaError(ValueError):
    pass


def media_root():
    return current_app.config["MEDIA_DIR"]


def _abs(rel_path):
    root = os.path.realpath(media_root())
    path = os.path.realpath(os.path.join(root, rel_path))
    if not path.startswith(root + os.sep):
        raise MediaError("Bad file path.")
    return path


def save_image(file_storage, folder, max_side=2400, thumb_side=None):
    """Validate, clean and store an uploaded image.

    Returns (rel_path, rel_thumb_path or None). Raises MediaError with a
    plain-English message if the file isn't a usable JPEG/PNG/HEIC."""
    if file_storage is None or not file_storage.filename:
        raise MediaError("Choose a photo to upload.")
    limit = current_app.config["MAX_UPLOAD_BYTES"]
    data = file_storage.stream.read(limit + 1)
    if len(data) > limit:
        raise MediaError(f"That file is too big; the limit is {limit // (1024 * 1024)} MB.")
    if not data:
        raise MediaError("That file is empty.")
    from io import BytesIO

    too_large = MediaError("That image is too large (too many pixels) to upload.")
    try:
        img = Image.open(BytesIO(data))  # reads the header only
    except Image.DecompressionBombError:
        raise too_large from None
    except (UnidentifiedImageError, OSError):
        raise MediaError("That doesn't look like a JPEG, PNG or HEIC photo.") from None
    fmt = img.format
    if fmt not in ALLOWED_FORMATS:
        raise MediaError("Only JPEG, PNG and HEIC photos can be uploaded.")
    # Pillow only raises past 2x MAX_IMAGE_PIXELS; between 1x and 2x it just
    # warns (DecompressionBombWarning) and decodes. Check before load().
    width, height = img.size
    if width * height > MAX_PIXELS:
        raise too_large
    try:
        img.load()
    except (OSError, Image.DecompressionBombError):
        raise MediaError("That doesn't look like a JPEG, PNG or HEIC photo.") from None

    img = ImageOps.exif_transpose(img)  # honour the camera's rotation, then drop EXIF
    img = _to_rgb(img)
    name = secrets.token_hex(16)
    rel = os.path.join(folder, f"{name}.jpg")
    rel_thumb = os.path.join(folder, f"{name}_t.jpg") if thumb_side else None
    try:
        _write(img, rel, max_side)
        if rel_thumb:
            _write(img, rel_thumb, thumb_side)
    except BaseException:
        delete(rel, rel_thumb)
        raise
    return rel, rel_thumb


def _to_rgb(img):
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        return background
    return img.convert("RGB")


def _write(img, rel, max_side):
    copy = img.copy()
    copy.thumbnail((max_side, max_side))
    path = _abs(rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # A fresh encode with no exif= argument writes no EXIF at all.
    copy.save(path, "JPEG", quality=85, optimize=True)


def path_for(rel_path):
    """Absolute path for serving, or None if it's missing."""
    if not rel_path:
        return None
    path = _abs(rel_path)
    return path if os.path.isfile(path) else None


def delete(*rel_paths):
    """Remove files. Call it after the commit that drops their rows: a file
    left behind is only clutter, a row pointing at no file is a broken image.
    So a file that can't be removed is logged, not raised."""
    for rel in rel_paths:
        if not rel:
            continue
        try:
            os.remove(_abs(rel))
        except FileNotFoundError:
            pass
        except (OSError, MediaError):
            current_app.logger.exception("Couldn't remove media file %s", rel)


@contextmanager
def removed_if_not_committed(*rel_paths):
    """Wrap the commit that records freshly written files: if it fails, roll
    back and remove the files instead of leaving orphans, then re-raise."""
    from app.extensions import db

    try:
        yield
    except BaseException:
        db.session.rollback()
        delete(*rel_paths)
        raise
