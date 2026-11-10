"""Billing plugs itself into other features at import time (imported from ``billing/models.py``):

* every new workspace starts a free trial (``WORKSPACE_CREATED_HOOKS``);
* publishing checks the monthly post quota (``social.hooks.POST_LIMIT_CHECKS``);
* new invitations are checked against the members limit (a ``before_flush`` guard, so the workspaces module
  does not need to know about plans).
"""
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.modules.social import hooks as social_hooks
from app.modules.workspaces import service as workspaces_service
from app.modules.workspaces.models import Invitation


def _start_trial(db, workspace) -> None:
    from .service import start_trial
    start_trial(db, workspace)


def _posts_quota(db, workspace_id: int) -> None:
    from . import limits
    limits.check(db, workspace_id, "posts_month")


def _members_guard(session: Session, _flush_context, _instances) -> None:
    new_invitations = [obj for obj in session.new if isinstance(obj, Invitation)]
    if not new_invitations:
        return
    from . import limits
    per_workspace: dict[int, list] = {}
    for invitation in new_invitations:
        per_workspace.setdefault(invitation.workspace_id, []).append(invitation)
    for workspace_id, items in per_workspace.items():
        try:
            with session.no_autoflush:
                limits.check(session, workspace_id, "members", amount=len(items))
        except Exception:
            for item in items:  # do not leave the refused rows pending in the session
                session.expunge(item)
            raise


def register() -> None:
    if _start_trial not in workspaces_service.WORKSPACE_CREATED_HOOKS:
        workspaces_service.WORKSPACE_CREATED_HOOKS.append(_start_trial)
    if _posts_quota not in social_hooks.POST_LIMIT_CHECKS:
        social_hooks.POST_LIMIT_CHECKS.append(_posts_quota)
    if not event.contains(Session, "before_flush", _members_guard):
        event.listen(Session, "before_flush", _members_guard)
