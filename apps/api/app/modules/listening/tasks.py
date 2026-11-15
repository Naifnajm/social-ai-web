"""Radar background work: collection runs, and the morning brief."""
import logging
from datetime import timedelta

from sqlalchemy import or_, select

from app.core.db import utcnow
from app.core.i18n import _, set_locale
from app.core.jobs import enqueue, periodic, session_scope
from app.core.notify import notify_role
from app.modules.billing import limits
from app.modules.planning.service import workspace_tz
from app.modules.workspaces.models import Role, Workspace
from app.modules.workspaces.settings import get_setting, set_setting

from . import service
from .models import ListeningQuery

_logger = logging.getLogger(__name__)
EVERY = timedelta(minutes=30)
BRIEF_HOUR = 8  # local time of the workspace


def collect_query(query_id: int) -> dict | None:
    with session_scope() as db:
        query = db.get(ListeningQuery, query_id)
        if not query or not query.active or not limits.feature(db, query.workspace_id, "listening"):
            return None
        try:
            return service.collect(db, query)
        except Exception:
            _logger.exception("radar collection failed for query %s", query_id)
            raise


@periodic(seconds=600)
def collect_due() -> int:
    """Queue every active query that was not collected in the last 30 minutes."""
    with session_scope() as db:
        ids = list(db.scalars(select(ListeningQuery.id).where(
            ListeningQuery.active.is_(True),
            or_(ListeningQuery.last_collected_at.is_(None), ListeningQuery.last_collected_at < utcnow() - EVERY))
            .order_by(ListeningQuery.last_collected_at.nullsfirst()).limit(200)))
    for query_id in ids:
        enqueue("app.modules.listening.tasks.collect_query", query_id)
    return len(ids)


def send_brief(db, workspace: Workspace, query: ListeningQuery) -> bool:
    data = service.brief(db, workspace, query)
    if not data["mentions"] and not data["events"]:
        return False
    set_locale(workspace.locale)
    title = _("Radar brief: {count} mentions yesterday", count=data["mentions"])
    parts = [_("Net sentiment {value}.", value=f"{data['net_sentiment']:+d}")]
    if data["negative"]:
        parts.append(_("{count} negative.", count=data["negative"]))
    if data["events"]:
        parts.append(_("Needs attention: {title}", title=data["events"][0].title))
    notify_role(db, workspace.id, Role.editor, kind="radar.brief", title=title, body=" ".join(parts),
                link="/radar")
    return True


@periodic(seconds=1800)
def morning_brief() -> int:
    """Once a day, around 08:00 in each workspace's time zone, a short summary for editors."""
    sent = 0
    with session_scope() as db:
        queries = list(db.scalars(select(ListeningQuery).where(ListeningQuery.active.is_(True))
                                  .order_by(ListeningQuery.workspace_id, ListeningQuery.id)))
        done: set[int] = set()
        for query in queries:
            if query.workspace_id in done:
                continue
            done.add(query.workspace_id)
            workspace = db.get(Workspace, query.workspace_id)
            if not workspace or not get_setting(db, workspace.id, "listening.brief", True):
                continue
            local = utcnow().astimezone(workspace_tz(workspace))
            day = local.date().isoformat()
            if local.hour < BRIEF_HOUR or get_setting(db, workspace.id, "listening.brief_day") == day:
                continue
            set_setting(db, workspace.id, "listening.brief_day", day)
            try:
                sent += int(send_brief(db, workspace, query))
            except Exception:
                _logger.exception("radar brief failed for workspace %s", workspace.id)
    return sent
