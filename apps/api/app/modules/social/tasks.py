"""Background jobs and periodic tasks of publishing."""
import logging

from sqlalchemy import select

from app.core.jobs import enqueue, periodic, session_scope

from . import accounts as account_service
from . import analytics, publishing
from .models import PUBLISH_PLATFORMS, OAuthSession, SocialAccount

_logger = logging.getLogger(__name__)


def publish_post(post_id: int) -> None:
    """Publish a post on every pending account (job enqueued by ``submit`` / ``retry`` / the scheduler)."""
    with session_scope() as db:
        publishing.run_publish(db, post_id)


@periodic(seconds=60)
def publish_due_posts() -> list[int]:
    """Scheduled posts whose time has come."""
    with session_scope() as db:
        publishing.release_stuck_targets(db)
        claimed = publishing.claim_due_posts(db)
    for post_id in claimed:
        try:
            enqueue(publish_post, post_id)
        except Exception:
            _logger.exception("could not enqueue scheduled post %s", post_id)
    return claimed


@periodic(seconds=3 * 3600)
def sync_metrics() -> int:
    with session_scope() as db:
        return analytics.sync_metrics(db)


@periodic(seconds=6 * 3600)
def sync_followers() -> int:
    """Followers + today's AccountStat row for every active account (one row per day, updated in place)."""
    with session_scope() as db:
        accounts = db.scalars(select(SocialAccount).where(SocialAccount.active.is_(True),
                                                          SocialAccount.platform.in_(PUBLISH_PLATFORMS))).all()
        return account_service.sync_audience(db, list(accounts))


@periodic(seconds=6 * 3600)
def refresh_tokens() -> int:
    with session_scope() as db:
        return account_service.refresh_due_tokens(db)


@periodic(seconds=3600)
def purge_oauth_sessions() -> None:
    from datetime import timedelta

    from app.core.db import utcnow
    with session_scope() as db:
        for row in db.scalars(select(OAuthSession).where(OAuthSession.created_at < utcnow() - timedelta(hours=1))):
            db.delete(row)
