"""Shared helpers of the publishing tests."""
import io
from datetime import datetime, timedelta

import pytest
from PIL import Image

from app.core.config import settings
from app.core.db import utcnow
from app.core.i18n import set_locale
from app.core.storage import save_media
from app.modules.social.models import Post, PostTarget, SocialAccount
from app.modules.social.platforms import meta


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (124, 58, 237)).save(buffer, "PNG")
    return buffer.getvalue()


PNG = png()


@pytest.fixture(autouse=True)
def jobs_in_test_session(db, monkeypatch):
    """``app.core.jobs`` keeps its own reference to ``SessionLocal``: make background jobs use the test session
    (conftest only patches ``app.core.db.SessionLocal``)."""
    from app.core import db as core_db
    from app.core import jobs

    monkeypatch.setattr(jobs, "SessionLocal", core_db.SessionLocal)
    set_locale("en")  # service-level messages in English (the API tests set the locale per request)


@pytest.fixture()
def public_https(monkeypatch):
    monkeypatch.setattr(settings, "public_api_url", "https://api.example.com")
    monkeypatch.setattr(meta, "sleep", lambda seconds: None)


def account(db, workspace_id, platform, name=None, **values) -> SocialAccount:
    defaults = {"facebook": {"external_id": "111", "access_token": "fbtok"},
                "x": {"username": "brand", "access_token": "xtok"},
                "instagram": {"external_id": "999", "access_token": "igtok", "username": "mybrand"},
                "linkedin": {"external_id": "urn:li:person:abc", "access_token": "litok"},
                "telegram": {"external_id": "@brand", "access_token": "123:ABC"},
                "threads": {"external_id": "th1", "access_token": "thtok"},
                "tiktok": {"external_id": "tt1", "access_token": "tttok"},
                "whatsapp": {"external_id": "+31600000000", "access_token": "wa"}}[platform]
    row = SocialAccount(workspace_id=workspace_id, platform=platform, name=name or platform.title(),
                        state="connected", **{**defaults, **values})
    db.add(row)
    db.flush()
    return row


def image(db, workspace_id, name="a.png"):
    return save_media(db, workspace_id, PNG, name, "image/png")


def video(db, workspace_id, name="v.mp4"):
    return save_media(db, workspace_id, b"\x00\x00\x00\x18ftypmp42" + b"0" * 64, name, "video/mp4")


def published(db, acc, when: datetime, media_type="image", text_length=80, **metrics) -> PostTarget:
    from app.modules.social.analytics import apply_metrics

    post = Post(workspace_id=acc.workspace_id, content=f"post {when}", state="posted", published_at=when)
    post.accounts = [acc]
    db.add(post)
    db.flush()
    target = PostTarget(workspace_id=acc.workspace_id, post_id=post.id, account_id=acc.id, platform=acc.platform,
                        state="posted", published_at=when, external_id=f"e{post.id}", media_type=media_type,
                        text_length=text_length)
    db.add(target)
    db.flush()
    apply_metrics(target, metrics)
    target.metrics_updated_at = when
    db.flush()
    return target


def ago(**kwargs) -> datetime:
    return utcnow() - timedelta(**kwargs)
