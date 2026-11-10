"""Brand-template framing for other features — CONTRACT (the templates builder implements the bodies).

    from app.modules.templates import frame
    media = frame.compose(db, ws_id, template_id, media_id, text="99 SAR")   # new Media (JPEG image or MP4)
    media = frame.compose_for_post(db, ws_id, set_or_template_id, media_id, text=None, story=False)
"""
from sqlalchemy.orm import Session

from app.core.models import Media


def compose(db: Session, workspace_id: int, template_id: int, media_id: int, text: str | None = None) -> Media:
    raise NotImplementedError


def compose_for_post(db: Session, workspace_id: int, template_or_set: str, media_id: int, text: str | None = None,
                     story: bool = False) -> Media:
    """``template_or_set`` is "template:<id>" or "set:<id>" (a set picks its post or story template)."""
    raise NotImplementedError
