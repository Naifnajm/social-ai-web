"""Core tables used by every feature: external API log, media files, notifications and devices."""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, TimestampMixin, WorkspaceMixin


class ApiLog(TimestampMixin, Base):
    """Every call to an external API (social networks, AI providers), secrets redacted."""

    __tablename__ = "api_logs"

    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    service: Mapped[str] = mapped_column(String(20))  # social | ai | other
    operation: Mapped[str] = mapped_column(String(120))
    method: Mapped[str] = mapped_column(String(10))
    endpoint: Mapped[str] = mapped_column(String(1000))
    status_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    request_body: Mapped[str | None] = mapped_column(Text)
    response_body: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    ref_model: Mapped[str | None] = mapped_column(String(60))  # e.g. "social_account", "ai_provider"
    ref_id: Mapped[int | None] = mapped_column(Integer)


class ErrorEvent(TimestampMixin, Base):
    """A failure on our side (an unhandled error or a failed external API call) that a person saw, kept under the
    reference shown to them so support can find exactly what happened."""

    __tablename__ = "error_events"

    ref: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    status: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(40))
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(500))
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)  # traceback, shown to platform admins only
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), index=True)


class Media(WorkspaceMixin, Base):
    """A file of a workspace (upload, AI result, framed image, production output…)."""

    __tablename__ = "media"

    filename: Mapped[str] = mapped_column(String(255))
    mimetype: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    source: Mapped[str] = mapped_column(String(20), default="upload")  # upload | ai | production | template | inbox
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[float | None] = mapped_column(Float)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    tags: Mapped[list | None] = mapped_column(JSON)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def kind(self) -> str:
        return (self.mimetype or "").split("/")[0]


class Notification(WorkspaceMixin, Base):
    """In-app notification (bell + mobile push)."""

    __tablename__ = "notifications"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # inbox.handover, post.approval, post.failed, report…
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(500))  # app route, e.g. "/inbox/12"
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Device(TimestampMixin, Base):
    """A mobile device registered for push notifications (Expo push token)."""

    __tablename__ = "devices"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    push_token: Mapped[str] = mapped_column(String(255), unique=True)
    platform: Mapped[str | None] = mapped_column(String(20))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
