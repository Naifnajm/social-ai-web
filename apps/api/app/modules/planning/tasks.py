"""Periodic planning work: campaign states follow their dates, evergreen posts are reposted."""
import logging

from app.core.jobs import periodic, session_scope

from . import service

_logger = logging.getLogger(__name__)


@periodic(seconds=3600)
def update_campaign_states():
    with session_scope() as db:
        changed = service.update_campaign_states(db)
    if changed:
        _logger.info("planning: %s campaign state(s) updated", changed)


@periodic(seconds=1800)
def recycle_evergreen():
    with session_scope() as db:
        created = service.recycle_due_posts(db)
    if created:
        _logger.info("planning: %s evergreen repost(s) created", len(created))
