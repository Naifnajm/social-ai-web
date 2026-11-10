"""Subscriptions (one per workspace), processed payment-provider events and platform-wide settings."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedString
from app.core.db import Base, TimestampMixin, WorkspaceMixin

SUBSCRIPTION_STATUSES = ("trialing", "active", "past_due", "canceled")


class Subscription(WorkspaceMixin, Base):
    """The plan of a workspace. ``Workspace.plan_code`` mirrors ``plan_code`` (shown in the app shell)."""

    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("workspace_id"),)

    plan_code: Mapped[str] = mapped_column(String(40), default="trial")
    status: Mapped[str] = mapped_column(String(20), default="trialing", index=True)
    interval: Mapped[str] = mapped_column(String(10), default="month")  # month | year
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    past_due_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(20), default="none")  # none | stripe | moyasar | manual
    provider_customer_id: Mapped[str | None] = mapped_column(String(120), index=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(120), index=True)
    provider_price_id: Mapped[str | None] = mapped_column(String(120))
    limit_overrides: Mapped[dict | None] = mapped_column(JSON)  # {"social_accounts": 100, ...} (enterprise deals)
    reminders: Mapped[dict | None] = mapped_column(JSON)  # e-mails/notifications already sent {"trial_3d": true}
    note: Mapped[str | None] = mapped_column(Text)  # platform admin note


class BillingEvent(TimestampMixin, Base):
    """A payment-provider webhook event (idempotency + audit trail). Also manual changes by platform admins."""

    __tablename__ = "billing_events"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)

    provider: Mapped[str] = mapped_column(String(20))  # stripe | moyasar | admin
    event_id: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(80))
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    summary: Mapped[str | None] = mapped_column(String(500))
    payload: Mapped[dict | None] = mapped_column(JSON)


class PlatformSetting(TimestampMixin, Base):
    """Platform-wide key/value settings managed by superadmins. Secrets go in ``secret`` (encrypted at rest)."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    secret: Mapped[str | None] = mapped_column(EncryptedString(4000))
    updated_by_id: Mapped[int | None] = mapped_column(Integer)


# registers the trial / post quota / members guard hooks once the models exist
from . import hooks as _hooks  # noqa: E402

_hooks.register()
