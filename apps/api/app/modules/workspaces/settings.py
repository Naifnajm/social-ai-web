"""Workspace settings (replaces Odoo's ir.config_parameter): ``get_setting(db, ws_id, "inbox.handover_message")``."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import WorkspaceSetting


def get_setting(db: Session, workspace_id: int, key: str, default=None):
    row = db.scalar(select(WorkspaceSetting).where(WorkspaceSetting.workspace_id == workspace_id,
                                                   WorkspaceSetting.key == key))
    return default if row is None or row.value is None else row.value


def set_setting(db: Session, workspace_id: int, key: str, value) -> None:
    row = db.scalar(select(WorkspaceSetting).where(WorkspaceSetting.workspace_id == workspace_id,
                                                   WorkspaceSetting.key == key))
    if row is None:
        db.add(WorkspaceSetting(workspace_id=workspace_id, key=key, value=value))
    else:
        row.value = value
    db.flush()


def get_settings_prefix(db: Session, workspace_id: int, prefix: str) -> dict:
    rows = db.scalars(select(WorkspaceSetting).where(WorkspaceSetting.workspace_id == workspace_id,
                                                     WorkspaceSetting.key.startswith(prefix)))
    return {row.key[len(prefix):]: row.value for row in rows}
