"""Brand templates API: templates & sets CRUD, frame upload/detection, previews, Quick publish, Telegram settings."""
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.core.storage import media_path, read_media
from app.modules.brand.models import BrandKit
from app.modules.files.router import media_out
from app.modules.social.models import PUBLISH_PLATFORMS, SocialAccount
from app.modules.workspaces.models import Role

from . import render, service, telegram
from .models import BrandTemplate, BrandTemplateSet
from .schemas import (
    BrandKitBrief,
    Detection,
    FrameUploadOut,
    QuickData,
    QuickPreviewIn,
    QuickPreviewOut,
    QuickPublishIn,
    QuickPublishOut,
    RenderPreviewIn,
    TelegramSettings,
    TemplateCreate,
    TemplateFields,
    TemplateOut,
    TemplateSetCreate,
    TemplateSetIn,
    TemplateSetOut,
)

router = APIRouter(prefix="/templates", tags=["templates"])

EDIT = Role.editor
BOX_FIELDS = ("box_x", "box_y", "box_w", "box_h")


# ---------------------------------------------------------------------------- helpers
def template_out(template: BrandTemplate) -> TemplateOut:
    width, height = render.FORMATS.get(template.format, render.FORMATS["post_4x5"])
    return TemplateOut.model_validate({
        **{c.name: getattr(template, c.name) for c in BrandTemplate.__table__.columns},
        "set_name": template.set.name if template.set else None,
        "aspect": service.aspect(template.format), "width": width, "height": height,
        "preview_url": service.preview_url(template),
    })


def set_out(tset: BrandTemplateSet) -> TemplateSetOut:
    templates = service.ordered(tset.templates)
    post, story = service.roles(templates) if templates else (None, None)
    return TemplateSetOut(id=tset.id, name=tset.name, sequence=tset.sequence, active=tset.active,
                          category=tset.category, brand_kit_id=tset.brand_kit_id,
                          post_template_id=post.id if post and not post.is_story else None,
                          story_template_id=story.id if story and story.is_story else None,
                          templates=[template_out(t) for t in sorted(tset.templates, key=lambda t: (t.is_story, t.sequence, t.id))],
                          usage_count=sum(t.usage_count or 0 for t in tset.templates))


def _check_refs(ctx: Ctx, values: dict) -> None:
    """Every id coming from the client must belong to the workspace."""
    ws = ctx.workspace.id
    if values.get("set_id"):
        service.get_set(ctx.db, ws, values["set_id"])
    if values.get("brand_kit_id"):
        service.get_kit(ctx.db, ws, values["brand_kit_id"])
    if values.get("frame_media_id"):
        media = service.get_media(ctx.db, ws, values["frame_media_id"])
        if media.kind != "image":
            raise AppError(_("The frame must be a PNG image (with a transparent window)."), code="bad_frame")


def _apply(ctx: Ctx, template: BrandTemplate, values: dict, creating: bool) -> None:
    _check_refs(ctx, values)
    new_frame = "frame_media_id" in values and values["frame_media_id"] and \
        values["frame_media_id"] != template.frame_media_id
    for key, value in values.items():
        setattr(template, key, value)
    if new_frame and not any(f in values for f in BOX_FIELDS):
        detection = service.detect_for_template(ctx.db, template)
        service.apply_detection(template, detection, with_format=creating and "format" not in values)


def _templates_query(ctx: Ctx):
    return select(BrandTemplate).where(BrandTemplate.workspace_id == ctx.workspace.id)


# ---------------------------------------------------------------------------- frames
@router.post("/frames", response_model=FrameUploadOut, status_code=201)
async def upload_frame(file: UploadFile = File(...), ctx: Ctx = Depends(workspace_ctx(EDIT))):
    """Upload a frame PNG: returns the stored file and the detected photo window and format."""
    content = await file.read()
    if len(content) > 30 * 1024 * 1024:
        raise AppError(_("The file is too large (max {mb} MB).", mb=30), code="too_large")
    media, detection = service.save_frame(ctx.db, ctx.workspace.id, content, file.filename or "frame.png",
                                          file.content_type, ctx.user.id)
    return FrameUploadOut(media=media_out(media), detection=Detection(**detection))


@router.post("/render-preview", response_class=Response,
             responses={200: {"content": {"image/jpeg": {}}, "description": "JPEG preview"}})
def render_preview(body: RenderPreviewIn, ctx: Ctx = Depends(workspace_ctx(EDIT))):
    """Live preview of unsaved template values (the editor): a JPEG of the sample (or given) photo framed."""
    ws = ctx.workspace.id
    values = body.model_dump(exclude_unset=True, exclude={"template_id", "text", "media_id"})
    _check_refs(ctx, values)
    base = service.get_template(ctx.db, ws, body.template_id) if body.template_id else None
    draft = BrandTemplate(workspace_id=ws)
    for column in BrandTemplate.__table__.columns:
        if column.name in ("id", "workspace_id", "created_at", "updated_at"):
            continue
        default = column.default.arg if column.default is not None and not callable(column.default.arg) else None
        setattr(draft, column.name, getattr(base, column.name) if base else default)
    for key, value in values.items():
        setattr(draft, key, value)
    photo = None
    if body.media_id:
        media = service.get_media(ctx.db, ws, body.media_id)
        content = read_media(media)
        if media.kind == "video":
            content = render.video_poster(content, media.mimetype)
        photo = render.open_image(content)
    text = body.text if body.text is not None else (service.preview_sample_text(draft) if draft.text_enabled else None)
    data = render.preview(service.frame_spec(ctx.db, draft), text=text or None, photo=photo, max_side=900)
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------- sets
@router.get("/sets", response_model=list[TemplateSetOut])
def list_sets(ctx: Ctx = Depends(workspace_ctx())):
    sets = ctx.db.scalars(select(BrandTemplateSet).where(BrandTemplateSet.workspace_id == ctx.workspace.id)
                          .order_by(BrandTemplateSet.sequence, BrandTemplateSet.name, BrandTemplateSet.id))
    out = []
    for tset in sets:
        for template in tset.templates:
            service.ensure_preview(ctx.db, template)
        out.append(set_out(tset))
    return out


@router.post("/sets", response_model=TemplateSetOut, status_code=201)
def create_set(body: TemplateSetCreate, ctx: Ctx = Depends(workspace_ctx(EDIT))):
    values = body.model_dump(exclude_unset=True)
    service.get_kit(ctx.db, ctx.workspace.id, values.get("brand_kit_id"))
    tset = BrandTemplateSet(workspace_id=ctx.workspace.id, **values)
    ctx.db.add(tset)
    ctx.db.flush()
    return set_out(tset)


@router.get("/sets/{set_id}", response_model=TemplateSetOut)
def read_set(set_id: int, ctx: Ctx = Depends(workspace_ctx())):
    return set_out(service.get_set(ctx.db, ctx.workspace.id, set_id))


@router.patch("/sets/{set_id}", response_model=TemplateSetOut)
def update_set(set_id: int, body: TemplateSetIn, ctx: Ctx = Depends(workspace_ctx(EDIT))):
    tset = service.get_set(ctx.db, ctx.workspace.id, set_id)
    values = body.model_dump(exclude_unset=True)
    service.get_kit(ctx.db, ctx.workspace.id, values.get("brand_kit_id"))
    for key, value in values.items():
        setattr(tset, key, value)
    ctx.db.flush()
    for template in tset.templates:
        service.ensure_preview(ctx.db, template)
    return set_out(tset)


@router.delete("/sets/{set_id}", status_code=204)
def delete_set(set_id: int, delete_templates: bool = False, ctx: Ctx = Depends(workspace_ctx(EDIT))):
    """Delete a set. Its templates are kept (without a set) unless ``delete_templates=true``."""
    tset = service.get_set(ctx.db, ctx.workspace.id, set_id)
    for template in list(tset.templates):
        if delete_templates:
            service.delete_template(ctx.db, template)
        else:
            template.set_id = None
    ctx.db.delete(tset)
    ctx.db.flush()


# ---------------------------------------------------------------------------- quick publish
@router.get("/quick", response_model=QuickData)
def quick_data(ctx: Ctx = Depends(workspace_ctx())):
    """Everything the Quick publish screen needs: template sets with previews, accounts, recent photos…"""
    from app.core.models import Media
    from app.modules.ai import service as ai

    ws = ctx.workspace.id
    accounts = ctx.db.scalars(select(SocialAccount).where(
        SocialAccount.workspace_id == ws, SocialAccount.active.is_(True),
        SocialAccount.platform.in_(PUBLISH_PLATFORMS)).order_by(SocialAccount.platform, SocialAccount.name)).all()
    recent = ctx.db.scalars(select(Media).where(Media.workspace_id == ws, Media.source != "template",
                                                Media.mimetype.in_(service.IMAGE_TYPES))
                            .order_by(Media.id.desc()).limit(12)).all()
    try:
        has_ai = bool(ai.has_provider(ctx.db, ws, "text"))
    except NotImplementedError:
        has_ai = False
    platforms = sorted({a.platform for a in accounts})
    return QuickData(
        choices=service.choices(ctx.db, ws),
        accounts=[{"id": a.id, "name": a.name, "platform": a.platform, "username": a.username,
                   "avatar_url": a.avatar_url, "state": a.state,
                   "can_story": a.platform in service.STORY_PLATFORMS} for a in accounts],
        recent=[media_out(m) for m in recent],
        story_platforms=list(service.STORY_PLATFORMS),
        best_slots=service.best_slots(ctx.db, ws, platforms, count=3),
        has_ai=has_ai, ffmpeg=render.ffmpeg_available(), can_manage=ctx.can(EDIT),
    )


@router.post("/quick/preview", response_model=list[QuickPreviewOut])
def quick_preview(body: QuickPreviewIn, ctx: Ctx = Depends(workspace_ctx(EDIT))):
    """Framed previews (post and story) of each photo with the chosen set, as small JPEG data URLs."""
    return service.quick_preview(ctx.db, ctx.workspace.id, body.choice, body.media_ids, body.text)


@router.post("/quick/publish", response_model=QuickPublishOut)
def quick_publish(body: QuickPublishIn, ctx: Ctx = Depends(workspace_ctx(EDIT))):
    """Frame the photos and create the posts (draft, publish now, best time or a date)."""
    ws = ctx.workspace.id
    templates = service.resolve_choice(ctx.db, ws, body.choice)
    media = [service.get_media(ctx.db, ws, mid) for mid in dict.fromkeys(body.media_ids)]
    accounts = []
    for account_id in dict.fromkeys(body.account_ids):
        account = ctx.db.get(SocialAccount, account_id)
        if not account or account.workspace_id != ws:
            raise NotFound(_("Account not found."), code="account_not_found")
        accounts.append(account)
    if body.mode != "draft" and not accounts:
        raise AppError(_("Choose at least one account to publish on."), code="no_accounts")
    if body.mode == "schedule" and not body.scheduled_at:
        raise AppError(_("Choose the date and time to publish."), code="no_date")
    for item in media:
        if item.kind == "video" and not render.ffmpeg_available():
            raise AppError(_("Framing a video needs ffmpeg on the server."), code="no_ffmpeg")
    posts = service.create_framed_posts(
        ctx.db, ws, ctx.user.id, templates, media, content=body.content.strip(), text=(body.text or "").strip() or None,
        account_ids=[a.id for a in accounts], publish_as=body.publish_as, carousel=body.grouping == "carousel")
    service.submit_posts(ctx.db, posts, ctx.user.id, body.mode, body.scheduled_at)
    ctx.db.flush()
    for post in posts:
        ctx.db.refresh(post)
    return QuickPublishOut(mode=body.mode, posts=[service.post_result(p) for p in posts])


# ---------------------------------------------------------------------------- telegram settings
@router.get("/telegram-settings", response_model=TelegramSettings)
def read_telegram_settings(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    return telegram.load_settings(ctx.db, ctx.workspace.id)


@router.put("/telegram-settings", response_model=TelegramSettings)
def write_telegram_settings(body: TelegramSettings, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    ws = ctx.workspace.id
    if body.default_set_id:
        service.get_set(ctx.db, ws, body.default_set_id)
    for account_id in body.account_ids:
        account = ctx.db.get(SocialAccount, account_id)
        if not account or account.workspace_id != ws:
            raise NotFound(_("Account not found."), code="account_not_found")
    return telegram.save_settings(ctx.db, ws, body)


@router.get("/brand-kits", response_model=list[BrandKitBrief])
def brand_kits(ctx: Ctx = Depends(workspace_ctx())):
    """Brand kits of the workspace (logo and colours used by the templates)."""
    kits = ctx.db.scalars(select(BrandKit).where(BrandKit.workspace_id == ctx.workspace.id, BrandKit.active.is_(True))
                          .order_by(BrandKit.is_default.desc(), BrandKit.name))
    return [BrandKitBrief(id=k.id, name=k.name, color_primary=k.color_primary, logo_media_id=k.logo_media_id,
                          is_default=k.is_default) for k in kits]


# ---------------------------------------------------------------------------- templates
@router.get("", response_model=list[TemplateOut])
def list_templates(set_id: int | None = None, ctx: Ctx = Depends(workspace_ctx())):
    query = _templates_query(ctx).order_by(BrandTemplate.sequence, BrandTemplate.name, BrandTemplate.id)
    if set_id is not None:
        query = query.where(BrandTemplate.set_id == set_id)
    templates = ctx.db.scalars(query).all()
    for template in templates:
        service.ensure_preview(ctx.db, template)
    return [template_out(t) for t in templates]


@router.post("", response_model=TemplateOut, status_code=201)
def create_template(body: TemplateCreate, ctx: Ctx = Depends(workspace_ctx(EDIT))):
    template = BrandTemplate(workspace_id=ctx.workspace.id)
    _apply(ctx, template, body.model_dump(exclude_unset=True), creating=True)
    ctx.db.add(template)
    ctx.db.flush()
    ctx.db.refresh(template)
    service.ensure_preview(ctx.db, template, force=True)
    return template_out(template)


@router.get("/{template_id}", response_model=TemplateOut)
def read_template(template_id: int, ctx: Ctx = Depends(workspace_ctx())):
    template = service.get_template(ctx.db, ctx.workspace.id, template_id)
    service.ensure_preview(ctx.db, template)
    return template_out(template)


@router.patch("/{template_id}", response_model=TemplateOut)
def update_template(template_id: int, body: TemplateFields, ctx: Ctx = Depends(workspace_ctx(EDIT))):
    template = service.get_template(ctx.db, ctx.workspace.id, template_id)
    values = body.model_dump(exclude_unset=True)
    if "name" in values and not (values["name"] or "").strip():
        raise AppError(_("Give the template a name."), code="name_required")
    _apply(ctx, template, values, creating=False)
    ctx.db.flush()
    ctx.db.refresh(template)
    service.ensure_preview(ctx.db, template)
    return template_out(template)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: int, ctx: Ctx = Depends(workspace_ctx(EDIT))):
    service.delete_template(ctx.db, service.get_template(ctx.db, ctx.workspace.id, template_id))


@router.post("/{template_id}/duplicate", response_model=TemplateOut, status_code=201)
def duplicate_template(template_id: int, ctx: Ctx = Depends(workspace_ctx(EDIT))):
    source = service.get_template(ctx.db, ctx.workspace.id, template_id)
    skip = {"id", "created_at", "updated_at", "preview_media_id", "preview_hash", "usage_count"}
    copy = BrandTemplate(**{c.name: getattr(source, c.name) for c in BrandTemplate.__table__.columns
                            if c.name not in skip})
    copy.name = _("{name} (copy)", name=source.name)[:120]
    ctx.db.add(copy)
    ctx.db.flush()
    ctx.db.refresh(copy)
    service.ensure_preview(ctx.db, copy, force=True)
    return template_out(copy)


@router.post("/{template_id}/detect", response_model=TemplateOut)
def redetect(template_id: int, ctx: Ctx = Depends(workspace_ctx(EDIT))):
    """Find the photo window of the frame again (after moving the box by hand)."""
    template = service.get_template(ctx.db, ctx.workspace.id, template_id)
    service.apply_detection(template, service.detect_for_template(ctx.db, template), with_format=False)
    ctx.db.flush()
    service.ensure_preview(ctx.db, template)
    return template_out(template)


@router.get("/{template_id}/preview", response_class=FileResponse,
            responses={200: {"content": {"image/jpeg": {}}, "description": "JPEG preview"}})
def template_preview(template_id: int, ctx: Ctx = Depends(workspace_ctx())):
    """The template with a sample photo (JPEG, max 720 px)."""
    template = service.get_template(ctx.db, ctx.workspace.id, template_id)
    media = service.ensure_preview(ctx.db, template)
    if media is None:
        data = render.preview(service.frame_spec(ctx.db, template), max_side=720)
        return Response(content=data, media_type="image/jpeg")
    return FileResponse(media_path(media), media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400" if not settings.is_test else "no-store"})

