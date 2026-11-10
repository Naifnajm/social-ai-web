"""Signed public media links (social networks download photos/videos from here)."""
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import NotFound
from app.core.models import Media
from app.core.storage import check_public_signature, media_path

router = APIRouter(tags=["public"])


@router.get("/m/{media_id}/{expires}/{signature}")
def public_media(media_id: int, expires: int, signature: str, db: Session = Depends(get_db)):
    media = db.get(Media, media_id)
    if not media or not check_public_signature(media_id, expires, signature):
        raise NotFound("Not found")
    return FileResponse(media_path(media), media_type=media.mimetype, filename=media.filename,
                        content_disposition_type="inline")
