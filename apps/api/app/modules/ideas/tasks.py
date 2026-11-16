"""Ideas of the day: a fresh batch every morning (workspace time) and old untouched ideas expire."""
import logging

from sqlalchemy import select

from app.core.db import utcnow
from app.core.i18n import _, set_locale
from app.core.jobs import periodic, session_scope
from app.core.notify import notify_role
from app.modules.billing import limits
from app.modules.planning.service import workspace_tz
from app.modules.social.models import PUBLISH_PLATFORMS, SocialAccount
from app.modules.workspaces.models import Role, Workspace
from app.modules.workspaces.settings import get_setting, set_setting

from . import service

_logger = logging.getLogger(__name__)


@periodic(seconds=1800)
def daily_ideas() -> int:
    made = 0
    with session_scope() as db:
        service.expire(db)
        ids = db.scalars(select(SocialAccount.workspace_id).where(
            SocialAccount.active.is_(True), SocialAccount.platform.in_(PUBLISH_PLATFORMS)).distinct()).all()
        for workspace_id in ids:
            workspace = db.get(Workspace, workspace_id)
            if not workspace or workspace.status != "active":
                continue
            conf = service.settings(db, workspace)
            local = utcnow().astimezone(workspace_tz(workspace))
            day = local.date().isoformat()
            if not conf["daily"] or local.hour < int(conf["hour"]) or get_setting(db, workspace_id, "ideas.day") == day:
                continue
            set_setting(db, workspace_id, "ideas.day", day)
            if not limits.feature(db, workspace_id, "ai_studio"):
                continue
            try:
                with db.begin_nested():
                    ideas = service.generate(db, workspace)
            except Exception:
                _logger.exception("daily ideas failed for workspace %s", workspace_id)
                continue
            if ideas:
                made += len(ideas)
                set_locale(workspace.locale)
                notify_role(db, workspace_id, Role.editor, kind="ideas.daily",
                            title=_("{count} new ideas for today", count=len(ideas)),
                            body=ideas[0].title, link="/ideas")
    return made
