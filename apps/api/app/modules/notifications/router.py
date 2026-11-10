from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update

from app.core.deps import Ctx, workspace_ctx
from app.core.models import Device, Notification

router = APIRouter(tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    title: str
    body: str | None = None
    link: str | None = None
    read_at: datetime | None = None
    created_at: datetime


class DeviceIn(BaseModel):
    push_token: str
    platform: str | None = None


@router.get("/notifications", response_model=list[NotificationOut])
def my_notifications(unread: bool = False, ctx: Ctx = Depends(workspace_ctx())):
    query = select(Notification).where(Notification.workspace_id == ctx.workspace.id,
                                       Notification.user_id == ctx.user.id)
    if unread:
        query = query.where(Notification.read_at.is_(None))
    return ctx.db.scalars(query.order_by(Notification.id.desc()).limit(50)).all()


@router.get("/notifications/count")
def unread_count(ctx: Ctx = Depends(workspace_ctx())):
    count = ctx.db.scalar(select(func.count()).select_from(Notification).where(
        Notification.workspace_id == ctx.workspace.id, Notification.user_id == ctx.user.id,
        Notification.read_at.is_(None)))
    return {"unread": count or 0}


@router.post("/notifications/read", status_code=204)
def mark_read(ids: list[int] | None = None, ctx: Ctx = Depends(workspace_ctx())):
    query = update(Notification).where(Notification.workspace_id == ctx.workspace.id,
                                       Notification.user_id == ctx.user.id, Notification.read_at.is_(None))
    if ids:
        query = query.where(Notification.id.in_(ids))
    ctx.db.execute(query.values(read_at=datetime.now(timezone.utc)))


@router.post("/devices", status_code=204)
def register_device(data: DeviceIn, ctx: Ctx = Depends(workspace_ctx())):
    device = ctx.db.scalar(select(Device).where(Device.push_token == data.push_token))
    if device is None:
        device = Device(push_token=data.push_token, user_id=ctx.user.id)
        ctx.db.add(device)
    device.user_id = ctx.user.id
    device.platform = data.platform
    device.last_seen_at = datetime.now(timezone.utc)


@router.delete("/devices/{push_token}", status_code=204)
def unregister_device(push_token: str, ctx: Ctx = Depends(workspace_ctx())):
    device = ctx.db.scalar(select(Device).where(Device.push_token == push_token, Device.user_id == ctx.user.id))
    if device:
        ctx.db.delete(device)
