"""File storage for media (local disk by default; the interface allows S3-compatible storage later).

    media = save_media(db, workspace_id, content, "photo.jpg", "image/jpeg", source="upload", user_id=...)
    content = read_media(media)
    url = public_url(media)            # signed, time-limited URL a social network can download from
"""
import hashlib
import hmac
import io
import mimetypes
import secrets
import time
from pathlib import Path

from sqlalchemy.orm import Session

from .config import settings
from .models import Media

PUBLIC_LINK_HOURS = 48


def _root() -> Path:
    root = Path(settings.storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _probe(content: bytes, mimetype: str) -> tuple[int | None, int | None]:
    if not mimetype.startswith("image/"):
        return None, None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(content)) as image:
            return image.size
    except Exception:
        return None, None


def guess_mimetype(filename: str, default: str = "application/octet-stream") -> str:
    return mimetypes.guess_type(filename)[0] or default


def save_media(db: Session, workspace_id: int, content: bytes, filename: str, mimetype: str | None = None, *,
               source: str = "upload", user_id: int | None = None) -> Media:
    mimetype = mimetype or guess_mimetype(filename)
    ext = Path(filename).suffix.lower()[:10] or mimetypes.guess_extension(mimetype) or ""
    key = f"{workspace_id}/{time.strftime('%Y/%m')}/{secrets.token_hex(12)}{ext}"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    width, height = _probe(content, mimetype)
    media = Media(workspace_id=workspace_id, filename=filename[:255], mimetype=mimetype, size=len(content),
                  storage_key=key, source=source, width=width, height=height, created_by_id=user_id)
    db.add(media)
    db.flush()
    return media


def read_media(media: Media) -> bytes:
    return (_root() / media.storage_key).read_bytes()


def media_path(media: Media) -> Path:
    return _root() / media.storage_key


def delete_media_file(media: Media) -> None:
    try:
        (_root() / media.storage_key).unlink(missing_ok=True)
    except OSError:
        pass


def _signature(media_id: int, expires: int) -> str:
    message = f"{media_id}:{expires}".encode()
    return hmac.new(settings.secret_key.encode(), message, hashlib.sha256).hexdigest()[:32]


def public_url(media: Media, hours: int = PUBLIC_LINK_HOURS) -> str:
    """URL anyone can fetch until it expires (Instagram/TikTok/Threads download media from a URL)."""
    expires = int(time.time()) + hours * 3600
    return f"{settings.public_api_url.rstrip('/')}/m/{media.id}/{expires}/{_signature(media.id, expires)}"


def check_public_signature(media_id: int, expires: int, signature: str) -> bool:
    return expires >= int(time.time()) and hmac.compare_digest(_signature(media_id, expires), signature)
