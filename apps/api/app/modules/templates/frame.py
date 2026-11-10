"""Brand-template framing for other features — CONTRACT (implemented by the templates feature).

    from app.modules.templates import frame
    media = frame.compose(db, ws_id, template_id, media_id, text="99 SAR")   # new Media (JPEG image or MP4)
    media = frame.compose_for_post(db, ws_id, set_or_template_id, media_id, text=None, story=False)

Both raise ``NotFound`` when the template/set/media is not in the workspace and ``AppError`` when the file
cannot be framed (not a photo/video, ffmpeg missing…). The new Media has ``source="template"``.
Helpers for caches (e.g. production blocks): ``fingerprint(db, ws_id, template_or_set)``, ``choices(db, ws_id)``.
"""
from sqlalchemy.orm import Session

from app.core.models import Media

from . import service


def compose(db: Session, workspace_id: int, template_id: int, media_id: int, text: str | None = None, *,
            user_id: int | None = None) -> Media:
    template = service.get_template(db, workspace_id, template_id)
    media = service.get_media(db, workspace_id, media_id)
    return service.compose_media(db, template, media, text, user_id)


def compose_for_post(db: Session, workspace_id: int, template_or_set: str, media_id: int, text: str | None = None,
                     story: bool = False, *, user_id: int | None = None) -> Media:
    """``template_or_set`` is "template:<id>" or "set:<id>" (a set picks its post or story template)."""
    post_tpl, story_tpl = service.roles(service.resolve_choice(db, workspace_id, template_or_set))
    media = service.get_media(db, workspace_id, media_id)
    return service.compose_media(db, story_tpl if story else post_tpl, media, text, user_id)


def fingerprint(db: Session, workspace_id: int, template_or_set: str) -> str:
    """Changes whenever framing with this template/set would give a different result."""
    templates = service.resolve_choice(db, workspace_id, template_or_set)
    return "-".join(service.fingerprint(db, t)[:12] for t in templates)


def choices(db: Session, workspace_id: int) -> list[dict]:
    """Template sets and loose templates: ``[{"key": "set:1", "name", "category", "templates": [...]}]``."""
    return service.choices(db, workspace_id)
