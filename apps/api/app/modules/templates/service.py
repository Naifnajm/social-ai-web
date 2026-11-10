"""Brand templates business logic: frame specs, previews, choices (sets), composition into Media, Quick publish.

Every function takes the workspace id and only touches rows of that workspace.
"""
import base64
import hashlib
import logging
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.core.models import Media
from app.core.storage import delete_media_file, read_media, save_media
from app.modules.brand.models import BrandKit

from . import render
from .models import BrandTemplate, BrandTemplateSet

_logger = logging.getLogger(__name__)

STORY_PLATFORMS = ("instagram", "facebook")
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif")
FRAME_TAG = "template-frame"
PREVIEW_TAG = "template-preview"
SPEC_FIELDS = ("format", "box_x", "box_y", "box_w", "box_h", "photo_fit", "background_color", "text_enabled",
               "text_x", "text_y", "text_w", "text_h", "text_size", "text_color", "text_bg_color", "text_align",
               "text_bold", "text_max_lines", "text_default", "logo_enabled", "logo_position", "logo_size",
               "frame_media_id", "brand_kit_id", "set_id")


# ---------------------------------------------------------------------------- lookups (workspace-scoped)
def get_template(db: Session, workspace_id: int, template_id: int) -> BrandTemplate:
    template = db.get(BrandTemplate, template_id)
    if not template or template.workspace_id != workspace_id:
        raise NotFound(_("Template not found."), code="template_not_found")
    return template


def get_set(db: Session, workspace_id: int, set_id: int) -> BrandTemplateSet:
    tset = db.get(BrandTemplateSet, set_id)
    if not tset or tset.workspace_id != workspace_id:
        raise NotFound(_("Template set not found."), code="template_set_not_found")
    return tset


def get_media(db: Session, workspace_id: int, media_id: int) -> Media:
    media = db.get(Media, media_id)
    if not media or media.workspace_id != workspace_id:
        raise NotFound(_("File not found."), code="media_not_found")
    return media


def get_kit(db: Session, workspace_id: int, kit_id: int | None) -> BrandKit | None:
    if not kit_id:
        return None
    kit = db.get(BrandKit, kit_id)
    if not kit or kit.workspace_id != workspace_id:
        raise NotFound(_("Brand kit not found."), code="brand_kit_not_found")
    return kit


def template_kit(db: Session, template: BrandTemplate) -> BrandKit | None:
    """The template's brand kit, else its set's, else the workspace default kit."""
    tset = db.get(BrandTemplateSet, template.set_id) if template.set_id else None
    kit_id = template.brand_kit_id or (tset.brand_kit_id if tset is not None else None)
    kit = db.get(BrandKit, kit_id) if kit_id else None
    if kit is None or kit.workspace_id != template.workspace_id:
        kit = db.scalar(select(BrandKit).where(BrandKit.workspace_id == template.workspace_id,
                                               BrandKit.active.is_(True))
                        .order_by(BrandKit.is_default.desc(), BrandKit.id).limit(1))
    return kit


def aspect(fmt: str) -> str:
    return render.ASPECT_OF.get(fmt or "post_4x5", "4:5")


# ---------------------------------------------------------------------------- spec & fingerprint
def frame_spec(db: Session, template: BrandTemplate) -> dict:
    """Everything the renderer needs, as plain data (see ``render.py``)."""
    width, height = render.FORMATS.get(template.format or "post_4x5", render.FORMATS["post_4x5"])
    kit = template_kit(db, template)
    frame = None
    if template.frame_media_id:
        media = db.get(Media, template.frame_media_id)
        if media and media.workspace_id == template.workspace_id:
            try:
                frame = read_media(media)
            except OSError:
                _logger.warning("frame file missing for template %s", template.id)
    spec = {
        "width": width, "height": height, "frame": frame,
        "box": (template.box_x, template.box_y, template.box_w, template.box_h),
        "fit": template.photo_fit or "cover",
        "background": template.background_color or (kit.color_primary if kit else None) or "#111111",
        "text": None, "logo": None,
    }
    if template.text_enabled:
        spec["text"] = {"x": template.text_x, "y": template.text_y, "w": template.text_w, "h": template.text_h,
                        "size": template.text_size or 64, "color": template.text_color or "#ffffff",
                        "background": template.text_bg_color or None, "align": template.text_align or "auto",
                        "bold": template.text_bold, "max_lines": template.text_max_lines or 2,
                        "default": template.text_default or ""}
    if template.logo_enabled and kit and kit.logo_media_id:
        logo = db.get(Media, kit.logo_media_id)
        if logo and logo.workspace_id == template.workspace_id:
            try:
                spec["logo"] = {"content": read_media(logo), "position": template.logo_position,
                                "size": template.logo_size or 16}
            except OSError:
                pass
    return spec


def fingerprint(db: Session, template: BrandTemplate, extra: str = "") -> str:
    """Changes whenever the result of this template would change (previews, production caches)."""
    kit = template_kit(db, template)
    values = [getattr(template, f) for f in SPEC_FIELDS]
    values += [kit.id if kit else None, kit.color_primary if kit else None, kit.logo_media_id if kit else None, extra]
    return hashlib.sha1(repr(values).encode()).hexdigest()


# ---------------------------------------------------------------------------- frames
def detect(content: bytes) -> dict:
    """Window (in %), canvas format and whether the frame has a transparent window."""
    found = render.detect_window(content)
    x, y, w, h = found["box"]
    return {"box_x": x, "box_y": y, "box_w": w, "box_h": h, "frame_has_window": found["transparent"],
            "format": render.guess_format(*found["size"]), "width": found["size"][0], "height": found["size"][1]}


def save_frame(db: Session, workspace_id: int, content: bytes, filename: str, mimetype: str | None,
               user_id: int | None) -> tuple[Media, dict]:
    if not (mimetype or "").startswith("image/"):
        raise AppError(_("The frame must be a PNG image (with a transparent window)."), code="bad_frame")
    detection = detect(content)  # raises when it is not an image
    media = save_media(db, workspace_id, content, filename or "frame.png", mimetype, source="template",
                       user_id=user_id)
    media.tags = [FRAME_TAG]
    return media, detection


def detect_for_template(db: Session, template: BrandTemplate) -> dict:
    if not template.frame_media_id:
        raise AppError(_("Upload the frame PNG first."), code="no_frame")
    media = get_media(db, template.workspace_id, template.frame_media_id)
    return detect(read_media(media))


def apply_detection(template: BrandTemplate, detection: dict, with_format: bool) -> None:
    for key in ("box_x", "box_y", "box_w", "box_h", "frame_has_window"):
        setattr(template, key, detection[key])
    if with_format:
        template.format = detection["format"]


# ---------------------------------------------------------------------------- previews
def preview_sample_text(template: BrandTemplate) -> str:
    return template.text_default or _("Your text here")


def ensure_preview(db: Session, template: BrandTemplate, force: bool = False) -> Media | None:
    """(Re)render the stored preview when the template (or its brand kit) changed."""
    sample = preview_sample_text(template) if template.text_enabled else ""
    digest = fingerprint(db, template, sample)
    current = db.get(Media, template.preview_media_id) if template.preview_media_id else None
    if current is not None and template.preview_hash == digest and not force:
        return current
    try:
        content = render.preview(frame_spec(db, template), text=sample or None, max_side=720)
    except AppError as exc:
        _logger.info("no preview for template %s: %s", template.id, exc.detail)
        return current
    media = save_media(db, template.workspace_id, content, f"template-{template.id}-preview.jpg", "image/jpeg",
                       source="template")
    media.tags = [PREVIEW_TAG]
    template.preview_media_id = media.id
    template.preview_hash = digest
    if current is not None:
        delete_media_file(current)
        db.delete(current)
    db.flush()
    return media


def preview_url(template: BrandTemplate) -> str:
    return f"/api/templates/{template.id}/preview?v={(template.preview_hash or '')[:10]}"


def delete_template(db: Session, template: BrandTemplate) -> None:
    """Delete a template, its preview and its frame file (unless another template uses the same frame)."""
    leftovers = []
    if template.preview_media_id:
        leftovers.append(db.get(Media, template.preview_media_id))
    if template.frame_media_id:
        shared = db.scalar(select(BrandTemplate.id).where(BrandTemplate.frame_media_id == template.frame_media_id,
                                                          BrandTemplate.id != template.id).limit(1))
        frame = db.get(Media, template.frame_media_id)
        if not shared and frame is not None and frame.source == "template":
            leftovers.append(frame)
    db.delete(template)
    db.flush()
    for media in leftovers:
        if media is not None:
            delete_media_file(media)
            db.delete(media)
    db.flush()


# ---------------------------------------------------------------------------- choices (sets)
def ordered(templates) -> list[BrandTemplate]:
    """Active templates, post formats first then stories."""
    return sorted((t for t in templates if t.active), key=lambda t: (t.is_story, t.sequence, t.id))


def resolve_choice(db: Session, workspace_id: int, choice: str | int) -> list[BrandTemplate]:
    """``choice``: ``"set:ID"``, ``"template:ID"`` (or ``"tpl:ID"``) or a bare set id → templates."""
    if isinstance(choice, str) and ":" in choice:
        kind, _sep, value = choice.partition(":")
    else:
        kind, value = "set", str(choice or "")
    try:
        record_id = int(value)
    except ValueError:
        raise AppError(_("Choose a template."), code="no_template") from None
    if kind in ("template", "tpl"):
        templates = [get_template(db, workspace_id, record_id)]
    elif kind == "set":
        templates = list(get_set(db, workspace_id, record_id).templates)
    else:
        raise AppError(_("Choose a template."), code="no_template")
    templates = ordered(templates)
    if not templates:
        raise AppError(_("This template set has no active template yet."), code="no_template")
    return templates


def roles(templates: list[BrandTemplate]) -> tuple[BrandTemplate, BrandTemplate]:
    """(post template, story template) of a choice; each falls back on the other."""
    post = next((t for t in templates if not t.is_story), None)
    story = next((t for t in templates if t.is_story), None)
    return post or story, story or post  # type: ignore[return-value]


def template_brief(db: Session, template: BrandTemplate) -> dict:
    ensure_preview(db, template)
    return {"id": template.id, "name": template.name, "format": template.format, "aspect": aspect(template.format),
            "role": "story" if template.is_story else "post", "text_enabled": template.text_enabled,
            "text_default": template.text_default or "", "preview_url": preview_url(template),
            "preview_media_id": template.preview_media_id}


def choices(db: Session, workspace_id: int) -> list[dict]:
    """Template sets (and templates without a set) offered in Quick publish, Telegram and Production."""
    result = []
    sets = db.scalars(select(BrandTemplateSet).where(BrandTemplateSet.workspace_id == workspace_id,
                                                     BrandTemplateSet.active.is_(True))
                      .order_by(BrandTemplateSet.sequence, BrandTemplateSet.name, BrandTemplateSet.id))
    for tset in sets:
        templates = ordered(tset.templates)
        if templates:
            result.append({"key": f"set:{tset.id}", "name": tset.name, "category": tset.category,
                           "templates": [template_brief(db, t) for t in templates],
                           "usage": sum(t.usage_count or 0 for t in templates)})
    loose = db.scalars(select(BrandTemplate).where(BrandTemplate.workspace_id == workspace_id,
                                                   BrandTemplate.set_id.is_(None), BrandTemplate.active.is_(True))
                       .order_by(BrandTemplate.sequence, BrandTemplate.name, BrandTemplate.id))
    for template in loose:
        result.append({"key": f"template:{template.id}", "name": template.name, "category": template.category,
                       "templates": [template_brief(db, template)], "usage": template.usage_count or 0})
    return result


# ---------------------------------------------------------------------------- composition
def _base_name(media: Media) -> str:
    return (Path(media.filename or "photo").stem or "photo")[:40]


def compose_bytes(db: Session, template: BrandTemplate, content: bytes, mimetype: str,
                  text: str | None = None) -> tuple[bytes, str, str]:
    """Frame one file. Returns ``(bytes, mimetype, extension)``: JPEG for images, MP4 for videos."""
    spec = frame_spec(db, template)
    if (mimetype or "").startswith("video/"):
        return render.compose_video(spec, content, mimetype, text=text), "video/mp4", "mp4"
    return render.compose(spec, content, text=text, fmt="JPEG"), "image/jpeg", "jpg"


def compose_media(db: Session, template: BrandTemplate, media: Media, text: str | None = None,
                  user_id: int | None = None, count: bool = True) -> Media:
    """A new Media: ``media`` framed with ``template``."""
    if media.workspace_id != template.workspace_id:
        raise NotFound(_("File not found."), code="media_not_found")
    if media.kind not in ("image", "video"):
        raise AppError(_("Only photos and videos can be framed."), code="bad_media")
    content, mimetype, ext = compose_bytes(db, template, read_media(media), media.mimetype, text)
    name = f"{_base_name(media)}-{aspect(template.format).replace(':', 'x')}.{ext}"
    framed = save_media(db, template.workspace_id, content, name, mimetype, source="template", user_id=user_id)
    if mimetype == "video/mp4":
        framed.width, framed.height = (render._even(render.FORMATS[template.format][0] * 2 / 3),
                                       render._even(render.FORMATS[template.format][1] * 2 / 3))
    if count:
        template.usage_count = (template.usage_count or 0) + 1
    db.flush()
    return framed


# ---------------------------------------------------------------------------- Quick publish
def quick_preview(db: Session, workspace_id: int, choice: str, media_ids: list[int], text: str | None) -> list[dict]:
    """Framed previews (small JPEG data URLs) of each file with the chosen post and story templates."""
    post_tpl, story_tpl = roles(resolve_choice(db, workspace_id, choice))
    pairs = [("post", post_tpl)] + ([("story", story_tpl)] if story_tpl is not post_tpl else [])
    specs = {template.id: frame_spec(db, template) for _role, template in pairs}
    result = []
    for media_id in media_ids[:20]:
        media = get_media(db, workspace_id, media_id)
        video = media.kind == "video"
        try:
            content = read_media(media)
            if video:
                content = render.video_poster(content, media.mimetype)
            elif media.kind != "image":
                raise AppError(_("Only photos and videos can be framed."), code="bad_media")
            photo = render.open_image(content)
        except (AppError, OSError) as exc:
            message = exc.detail if isinstance(exc, AppError) else _("File not found.")
            result.append({"media_id": media.id, "video": video, "error": message, "items": []})
            continue
        items = []
        for role, template in pairs:
            data = render.preview(specs[template.id], text=text or None, photo=photo, max_side=540)
            items.append({"role": role, "template_id": template.id, "aspect": aspect(template.format),
                          "src": "data:image/jpeg;base64," + base64.b64encode(data).decode()})
        result.append({"media_id": media.id, "video": video, "error": None, "items": items})
    return result


def create_framed_posts(db: Session, workspace_id: int, user_id: int | None, templates: list[BrandTemplate],
                        media: list[Media], *, content: str = "", text: str | None = None,
                        account_ids: list[int] | None = None, publish_as: str = "feed", carousel: bool = False,
                        name: str | None = None, source_ref: str = "quick") -> list:
    """Frame each file with the post/story templates and create one post per file (or one carousel)."""
    from app.modules.social import service as social

    post_tpl, story_tpl = roles(templates)
    if carousel and len(media) > 1 and not any(m.kind == "video" for m in media):
        groups = [media]
    else:
        groups = [[m] for m in media]
    if not content.strip() and not name:
        first = templates[0]
        name = f"{first.set.name if first.set else first.name} — {date.today().isoformat()}"
    posts = []
    for group in groups:
        feed_ids: list[int] = []
        story_ids: list[int] = []
        for item in group:
            if publish_as in ("feed", "feed_story"):
                feed_ids.append(compose_media(db, post_tpl, item, text, user_id).id)
            if publish_as in ("story", "feed_story"):
                story_ids.append(compose_media(db, story_tpl, item, text, user_id).id)
        post = social.create_post(db, workspace_id, user_id, content=content, media_ids=feed_ids or story_ids,
                                  account_ids=list(account_ids or []), publish_as=publish_as,
                                  story_media_ids=story_ids, name=name, source_ref=source_ref)
        post.brand_template_id = (story_tpl if publish_as == "story" else post_tpl).id
        posts.append(post)
    db.flush()
    return posts


def submit_posts(db: Session, posts: list, user_id: int | None, mode: str, when: datetime | None = None) -> None:
    from app.modules.social import service as social

    action = {"draft": "draft", "now": "publish", "publish": "publish", "best_time": "best_time",
              "best": "best_time", "schedule": "schedule"}[mode]
    for post in posts:
        social.submit(db, post, user_id, action=action, when=when if action == "schedule" else None)


def post_result(post) -> dict:
    return {
        "id": post.id, "name": post.name or "", "state": post.state,
        "scheduled_at": post.scheduled_at,
        "results": [{"account_id": target.account_id,
                     "account": target.account.name if target.account else "",
                     "platform": target.platform, "state": target.state, "url": target.external_url or "",
                     "error": target.error or "", "story_state": target.story_state or "",
                     "story_error": target.story_error or ""} for target in (post.targets or [])],
    }


def best_slots(db: Session, workspace_id: int, platforms: list[str], count: int = 3) -> list[dict]:
    from app.modules.social import service as social

    try:
        slots = social.next_best_slots(db, workspace_id, platforms or None, count=count) or []
    except NotImplementedError:
        return []
    except AppError:
        return []
    out = []
    for slot in slots:
        at = slot.get("at")
        if isinstance(at, datetime) and at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        out.append({"at": at, "label": slot.get("label") or ""})
    return out
