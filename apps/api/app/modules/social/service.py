"""Posts & publishing API for other features — CONTRACT (implemented by the publishing feature).

Other features (quick publish, inbox, planning, production, product posts…) create and publish posts only
through these functions; tests of other features may monkeypatch them.

    from app.modules.social import service as social
    post = social.create_post(db, ws_id, user_id, content="Hi", media_ids=[3], account_ids=[1, 2],
                              publish_as="feed_story", campaign_id=None, source_ref="quick")
    social.submit(db, post, user_id, action="publish")       # publish now (or send to approval if required)
    social.submit(db, post, user_id, action="schedule", when=dt)
    social.submit(db, post, user_id, action="best_time")     # next best slot for the post's networks
    slots = social.next_best_slots(db, ws_id, ["instagram"], count=3)  # [{"at": datetime(utc), "label": "Mon 19:00"}]

Notes: ids are checked against the workspace (``NotFound``); validation problems raise ``AppError`` with
code ``invalid_post`` and ``problems=[{platform, account_id, message}]``; "publish" commits the current
transaction before handing the post to the background worker.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from . import analytics, publishing
from .models import Post


def create_post(db: Session, workspace_id: int, user_id: int | None, *, content: str = "",
                media_ids: list[int] | None = None, account_ids: list[int] | None = None,
                publish_as: str = "feed", story_media_ids: list[int] | None = None,
                platform_media: dict | None = None, variants: dict | None = None, name: str | None = None,
                campaign_id: int | None = None, pillar_id: int | None = None, planned_date: datetime | None = None,
                source_ref: str | None = None, ai_brief: str | None = None,
                brand_template_id: int | None = None) -> Post:
    post = Post(workspace_id=workspace_id, author_id=user_id, state="draft", publish_as="feed")
    db.add(post)
    db.flush()
    publishing.apply_fields(db, post, {
        "content": content or "", "media_ids": media_ids or [], "story_media_ids": story_media_ids or [],
        "account_ids": account_ids or [], "publish_as": publish_as or "feed", "platform_media": platform_media,
        "variants": variants, "name": name, "campaign_id": campaign_id, "pillar_id": pillar_id,
        "planned_date": planned_date, "source_ref": source_ref, "ai_brief": ai_brief,
        "brand_template_id": brand_template_id,
    })
    return post


def submit(db: Session, post: Post, user_id: int | None, *, action: str, when: datetime | None = None) -> Post:
    """action: "draft" | "publish" | "schedule" | "best_time". Applies the approval rules of the workspace
    (the post may end in state "to_approve"). Returns the post."""
    return publishing.submit(db, post, user_id, action=action, when=when)


def next_best_slots(db: Session, workspace_id: int, platforms: list[str] | None = None, count: int = 3) -> list[dict]:
    """Upcoming best publishing moments: ``[{"at": aware UTC datetime, "local": "YYYY-MM-DDTHH:MM", "label",
    "score"}]`` from the workspace's own engagement data (or general benchmarks until there is enough)."""
    return analytics.next_best_slots(db, workspace_id, platforms, count)
