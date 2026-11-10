"""Notify users: in-app notification + mobile push (Expo push service).

    notify(db, workspace_id, [user.id], kind="inbox.handover", title=_("..."), body=..., link="/inbox/12")
    notify_role(db, workspace_id, Role.approver, ...)   # everyone with at least this role
"""
import logging

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Device, Notification

_logger = logging.getLogger(__name__)
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def notify(db: Session, workspace_id: int, user_ids: list[int], *, kind: str, title: str, body: str = "",
           link: str | None = None, push: bool = True) -> list[Notification]:
    created = []
    for user_id in dict.fromkeys(user_ids):
        item = Notification(workspace_id=workspace_id, user_id=user_id, kind=kind, title=title[:200], body=body,
                            link=link)
        db.add(item)
        created.append(item)
    db.flush()
    if push and not settings.is_test:
        tokens = db.scalars(select(Device.push_token).where(Device.user_id.in_(user_ids))).all()
        _send_push(tokens, title, body, {"link": link, "workspace_id": workspace_id, "kind": kind})
    return created


def notify_role(db: Session, workspace_id: int, min_role, **kwargs) -> list[Notification]:
    from app.modules.workspaces.models import ROLE_RANK, Membership
    members = db.scalars(select(Membership).where(Membership.workspace_id == workspace_id)).all()
    ids = [m.user_id for m in members if ROLE_RANK[m.role] >= ROLE_RANK[min_role]]
    return notify(db, workspace_id, ids, **kwargs)


def _send_push(tokens: list[str], title: str, body: str, data: dict) -> None:
    messages = [{"to": t, "title": title, "body": body[:180], "data": data, "sound": "default"}
                for t in tokens if t.startswith("ExponentPushToken")]
    if not messages:
        return
    try:
        requests.post(EXPO_PUSH_URL, json=messages, timeout=15)
    except requests.RequestException:  # push is best-effort
        _logger.warning("push notification failed", exc_info=True)
