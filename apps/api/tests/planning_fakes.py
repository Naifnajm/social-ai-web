"""Test helpers of the planning features: a fake publishing contract (``social.service``) and data builders."""
import io
from datetime import datetime, timedelta, timezone

from PIL import Image

from app.core.storage import save_media
from app.modules.social import service as social
from app.modules.social.models import Post, PostMedia, PostTarget, SocialAccount

UTC = timezone.utc


def png(color=(20, 20, 20), size=(32, 32)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


class FakeSocial:
    """Implements the publishing contract in memory (records the calls)."""

    def __init__(self, db, slot: datetime | None = None):
        self.db = db
        self.created: list[Post] = []
        self.submits: list[tuple] = []
        self.slot = slot or (datetime.now(UTC) + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
        self.fail_submit: str | None = None

    def create_post(self, db, workspace_id, user_id, *, content="", media_ids=None, account_ids=None,
                    publish_as="feed", story_media_ids=None, platform_media=None, variants=None, name=None,
                    campaign_id=None, pillar_id=None, planned_date=None, source_ref=None):
        post = Post(workspace_id=workspace_id, author_id=user_id, content=content, name=name, publish_as=publish_as,
                    platform_media=platform_media, variants=variants, campaign_id=campaign_id, pillar_id=pillar_id,
                    planned_date=planned_date, source_ref=source_ref, state="draft")
        post.accounts = [db.get(SocialAccount, i) for i in account_ids or []]
        db.add(post)
        db.flush()
        for index, media_id in enumerate(media_ids or []):
            post.media_links.append(PostMedia(post_id=post.id, media_id=media_id, position=index))
        for index, media_id in enumerate(story_media_ids or []):
            post.media_links.append(PostMedia(post_id=post.id, media_id=media_id, position=index, role="story"))
        db.flush()
        self.created.append(post)
        return post

    def submit(self, db, post, user_id, *, action, when=None):
        self.submits.append((post.id, action, when))
        if self.fail_submit:
            from app.core.errors import AppError
            raise AppError(self.fail_submit, code="refused")
        if action == "schedule":
            post.state, post.scheduled_at = "scheduled", when
        elif action == "best_time":
            post.state, post.scheduled_at = "scheduled", self.slot
        elif action == "publish":
            post.state, post.published_at = "posted", datetime.now(UTC)
        db.flush()
        return post

    def next_best_slots(self, db, workspace_id, platforms=None, count=3):
        return [{"at": self.slot + timedelta(days=i), "label": "slot"} for i in range(count)]


def install_fake_social(monkeypatch, db) -> FakeSocial:
    fake = FakeSocial(db)
    monkeypatch.setattr(social, "create_post", fake.create_post)
    monkeypatch.setattr(social, "submit", fake.submit)
    monkeypatch.setattr(social, "next_best_slots", fake.next_best_slots)
    return fake


def make_account(db, workspace_id, platform="facebook", name=None, followers=0) -> SocialAccount:
    account = SocialAccount(workspace_id=workspace_id, name=name or f"{platform} page", platform=platform,
                            external_id=f"{platform}-1", access_token="tok", followers=followers)
    db.add(account)
    db.flush()
    return account


def make_post(db, workspace_id, accounts=(), *, state="draft", content="Hello", name="Post", media=(), **values) -> Post:
    post = Post(workspace_id=workspace_id, content=content, name=name, state=state, **values)
    post.accounts = list(accounts)
    db.add(post)
    db.flush()
    for index, item in enumerate(media):
        post.media_links.append(PostMedia(post_id=post.id, media_id=item.id, position=index))
    db.flush()
    return post


def publish(db, post, accounts=None, when=None, **metrics) -> list[PostTarget]:
    """Mark a post as published with one target per account (and metrics)."""
    when = when or datetime.now(UTC) - timedelta(hours=2)
    post.state, post.published_at = "posted", when
    targets = []
    for account in accounts or post.accounts:
        target = PostTarget(workspace_id=post.workspace_id, post_id=post.id, account_id=account.id,
                            platform=account.platform, state="posted", published_at=when, **metrics)
        db.add(target)
        targets.append(target)
    db.flush()
    return targets


def make_media(db, workspace_id, name="photo.png", user_id=None, content=None, mimetype="image/png", source="upload"):
    return save_media(db, workspace_id, content or png(), name, mimetype, source=source, user_id=user_id)


def share_job_session(monkeypatch) -> None:
    """Background jobs (``session_scope``) use the test transaction too.

    ``app.core.jobs`` keeps its own reference to ``SessionLocal`` (imported at module load), so the conftest's
    patch of ``app.core.db.SessionLocal`` does not reach it."""
    from app.core import db as core_db
    from app.core import jobs
    monkeypatch.setattr(jobs, "SessionLocal", core_db.SessionLocal)
