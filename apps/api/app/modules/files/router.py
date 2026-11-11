"""Media files of the workspace: upload, list, download (authenticated)."""
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse

from app.core.hardening import UPLOAD_HEADERS
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.core.models import Media
from app.core.storage import media_path, public_url, save_media
from app.modules.workspaces.models import Role

router = APIRouter(prefix="/media", tags=["media"])


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    mimetype: str
    size: int
    source: str
    width: int | None = None
    height: int | None = None
    url: str = ""
    thumb_url: str = ""


def media_out(media: Media) -> MediaOut:
    out = MediaOut.model_validate(media)
    out.url = f"/api/media/{media.id}/file"
    out.thumb_url = f"/api/media/{media.id}/file" if media.kind == "image" else ""
    return out


def get_media(ctx: Ctx, media_id: int) -> Media:
    media = ctx.db.get(Media, media_id)
    if not media or media.workspace_id != ctx.workspace.id:
        raise NotFound(_("File not found."))
    return media


@router.post("", response_model=MediaOut, status_code=201)
async def upload(file: UploadFile = File(...), ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise AppError(_("The file is too large (max {mb} MB).", mb=settings.max_upload_mb), code="too_large")
    if not (file.content_type or "").split("/")[0] in ("image", "video", "audio"):
        raise AppError(_("Only images, videos and audio files can be uploaded."), code="bad_type")
    media = save_media(ctx.db, ctx.workspace.id, content, file.filename or "file", file.content_type,
                       source="upload", user_id=ctx.user.id)
    return media_out(media)


@router.get("", response_model=list[MediaOut])
def list_media(kind: str | None = None, limit: int = 60, ctx: Ctx = Depends(workspace_ctx())):
    query = select(Media).where(Media.workspace_id == ctx.workspace.id).order_by(Media.id.desc()).limit(min(limit, 200))
    if kind:
        query = query.where(Media.mimetype.startswith(f"{kind}/"))
    return [media_out(m) for m in ctx.db.scalars(query)]


@router.get("/{media_id}", response_model=MediaOut)
def one(media_id: int, ctx: Ctx = Depends(workspace_ctx())):
    return media_out(get_media(ctx, media_id))


@router.get("/{media_id}/file")
def download(media_id: int, ctx: Ctx = Depends(workspace_ctx())):
    media = get_media(ctx, media_id)
    return FileResponse(media_path(media), media_type=media.mimetype, filename=media.filename,
                        content_disposition_type="inline", headers=UPLOAD_HEADERS)


@router.get("/{media_id}/public-url")
def share(media_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    return {"url": public_url(get_media(ctx, media_id))}
