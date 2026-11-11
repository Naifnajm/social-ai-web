from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, WorkspaceMixin


class Role(StrEnum):
    """Ordered from least to most rights (see ROLE_RANK)."""

    viewer = "viewer"      # read only
    editor = "editor"      # create content, reply to messages
    approver = "approver"  # + approve posts
    admin = "admin"        # + accounts, providers, members, settings
    owner = "owner"        # + billing, delete workspace


ROLE_RANK = {Role.viewer: 0, Role.editor: 1, Role.approver: 2, Role.admin: 3, Role.owner: 4}


class Workspace(TimestampMixin, Base):
    """One customer company (tenant)."""

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    locale: Mapped[str] = mapped_column(String(5), default="ar")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Riyadh")
    currency: Mapped[str] = mapped_column(String(3), default="SAR")
    logo_media_id: Mapped[int | None] = mapped_column()
    plan_code: Mapped[str] = mapped_column(String(40), default="trial")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | suspended

    memberships = relationship("Membership", back_populates="workspace", cascade="all, delete-orphan")


class Membership(TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default=Role.editor)
    # $ of platform-paid AI this member may use per month in this workspace (None: only the plan's limit).
    ai_monthly_limit: Mapped[float | None] = mapped_column(Float)

    user = relationship("User", back_populates="memberships")
    workspace = relationship("Workspace", back_populates="memberships")


class Invitation(WorkspaceMixin, Base):
    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(String(254), index=True)
    role: Mapped[str] = mapped_column(String(20), default=Role.editor)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceSetting(WorkspaceMixin, Base):
    """Key/value settings of a workspace (feature switches, defaults…). Values are JSON."""

    __tablename__ = "workspace_settings"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)

    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
