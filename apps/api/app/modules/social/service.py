"""Posts & publishing API for other features — CONTRACT (the publishing builder implements the bodies).

Other features (quick publish, inbox, planning, production, product posts…) create and publish posts only
through these functions; tests of other features may monkeypatch them.

    from app.modules.social import service as social
    post = social.create_post(db, ws_id, user_id, content="Hi", media_ids=[3], account_ids=[1, 2],
                              publish_as="feed_story", campaign_id=None, source_ref="quick")
    social.submit(db, post, user_id, action="publish")       # publish now (or send to approval if required)
    social.submit(db, post, user_id, action="schedule", when=dt)
    social.submit(db, post, user_id, action="best_time")     # next best slot for the post's networks
    slots = social.next_best_slots(db, ws_id, ["instagram"], count=3)  # [{"at": datetime(utc), "label": "Mon 19:00"}]
"""
from datetime import datetime

from sqlalchemy.orm import Session

from .models import Post


def create_post(db: Session, workspace_id: int, user_id: int | None, *, content: str = "",
                media_ids: list[int] | None = None, account_ids: list[int] | None = None,
                publish_as: str = "feed", story_media_ids: list[int] | None = None,
                platform_media: dict | None = None, variants: dict | None = None, name: str | None = None,
                campaign_id: int | None = None, pillar_id: int | None = None, planned_date: datetime | None = None,
                source_ref: str | None = None) -> Post:
    raise NotImplementedError


def submit(db: Session, post: Post, user_id: int | None, *, action: str, when: datetime | None = None) -> Post:
    """action: "draft" | "publish" | "schedule" | "best_time". Applies the approval rules of the workspace
    (the post may end in state "to_approve"). Returns the post."""
    raise NotImplementedError


def next_best_slots(db: Session, workspace_id: int, platforms: list[str] | None = None, count: int = 3) -> list[dict]:
    raise NotImplementedError
