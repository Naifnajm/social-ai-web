"""Subscription lifecycle: trial start, plan changes, payment failures and the effective state of a workspace.

Effective state (``billing_state``):
* ``trialing`` until ``trial_ends_at`` → then blocked (``trial_ended``) until a plan is bought;
* ``active`` → everything within the plan limits;
* ``past_due`` (payment failed) → still working during the grace period, then blocked (``payment_overdue``);
* ``canceled`` → working until the paid period ends, then blocked (``canceled``);
* a workspace suspended by a platform admin is blocked (``suspended``).
Blocked means read-only: every ``limits.check`` raises ``LimitReached`` (reads keep working).
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import _
from app.core.notify import notify_role
from app.modules.workspaces.models import Role, Workspace

from . import platform
from .config import billing_settings
from .models import BillingEvent, Subscription
from .plans import TRIAL_DAYS, Plan, effective_limits, get_plan


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def trial_days(db: Session) -> int:
    return int(platform.get_setting(db, "billing.trial_days", TRIAL_DAYS) or TRIAL_DAYS)


def grace_days(db: Session) -> int:
    value = platform.get_setting(db, "billing.grace_days")
    return int(value) if value is not None else billing_settings().billing_grace_days


# ---------------------------------------------------------------- subscription rows
def get_subscription(db: Session, workspace_id: int) -> Subscription | None:
    return db.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id))


def ensure_subscription(db: Session, workspace: Workspace) -> Subscription:
    """The subscription of a workspace, creating a trial for workspaces made before billing existed."""
    sub = get_subscription(db, workspace.id)
    if sub is None:
        start = _aware(workspace.created_at) or utcnow()
        sub = Subscription(workspace_id=workspace.id, plan_code="trial", status="trialing",
                           trial_ends_at=start + timedelta(days=trial_days(db)))
        db.add(sub)
        db.flush()
        sync_workspace(db, sub, workspace)
    return sub


def start_trial(db: Session, workspace: Workspace) -> Subscription:
    """WORKSPACE_CREATED_HOOKS entry: every new workspace starts a free trial."""
    sub = get_subscription(db, workspace.id)
    if sub is None:
        sub = Subscription(workspace_id=workspace.id, plan_code="trial", status="trialing",
                           trial_ends_at=utcnow() + timedelta(days=trial_days(db)))
        db.add(sub)
        db.flush()
    sync_workspace(db, sub, workspace)
    return sub


def sync_workspace(db: Session, sub: Subscription, workspace: Workspace | None = None) -> None:
    workspace = workspace or db.get(Workspace, sub.workspace_id)
    if workspace is not None and workspace.plan_code != sub.plan_code:
        workspace.plan_code = sub.plan_code


# ---------------------------------------------------------------- effective state
@dataclass
class BillingState:
    workspace_id: int
    plan: Plan
    status: str                      # trialing | active | past_due | canceled
    blocked: str | None = None       # None | trial_ended | payment_overdue | canceled | suspended
    trial_ends_at: datetime | None = None
    current_period_end: datetime | None = None
    grace_ends_at: datetime | None = None
    cancel_at_period_end: bool = False
    limits: dict = field(default_factory=dict)
    subscription: Subscription | None = None

    @property
    def trial_days_left(self) -> int | None:
        if self.status != "trialing" or not self.trial_ends_at:
            return None
        seconds = (self.trial_ends_at - utcnow()).total_seconds()
        return max(0, int((seconds + 86399) // 86400))


def billing_state(db: Session, workspace_id: int) -> BillingState:
    sub = get_subscription(db, workspace_id)
    workspace = db.get(Workspace, workspace_id)
    now = utcnow()
    if sub is None:  # workspace created before billing (or outside the API): implicit trial, no write here
        start = _aware(workspace.created_at) if workspace and workspace.created_at else now
        plan = get_plan(workspace.plan_code if workspace else "trial")
        state = BillingState(workspace_id, plan, "trialing" if plan.code == "trial" else "active",
                             trial_ends_at=start + timedelta(days=trial_days(db)) if plan.code == "trial" else None,
                             limits=effective_limits(plan))
    else:
        plan = get_plan(sub.plan_code)
        state = BillingState(workspace_id, plan, sub.status, trial_ends_at=_aware(sub.trial_ends_at),
                             current_period_end=_aware(sub.current_period_end),
                             cancel_at_period_end=sub.cancel_at_period_end,
                             limits=effective_limits(plan, sub.limit_overrides), subscription=sub)
        if sub.status == "past_due":
            since = _aware(sub.past_due_since) or now
            state.grace_ends_at = since + timedelta(days=grace_days(db))
    if state.status == "trialing" and state.trial_ends_at and state.trial_ends_at <= now:
        state.blocked = "trial_ended"
    elif state.status == "past_due" and state.grace_ends_at and state.grace_ends_at <= now:
        state.blocked = "payment_overdue"
    elif state.status == "canceled" and not (state.current_period_end and state.current_period_end > now):
        state.blocked = "canceled"
    if workspace is not None and workspace.status != "active":
        state.blocked = "suspended"
    return state


# ---------------------------------------------------------------- changes
def log_event(db: Session, provider: str, event_id: str, type_: str, workspace_id: int | None, *,
              summary: str = "", payload: dict | None = None, actor_id: int | None = None) -> BillingEvent:
    event = BillingEvent(provider=provider, event_id=event_id[:120], type=type_[:80], workspace_id=workspace_id,
                         summary=summary[:500] or None, payload=payload, actor_id=actor_id)
    db.add(event)
    db.flush()
    return event


def apply_plan(db: Session, sub: Subscription, plan_code: str, *, status: str = "active", interval: str | None = None,
               period_end: datetime | None = None) -> Subscription:
    """Move a subscription to a plan/status (used by webhooks and by platform admins)."""
    previous = sub.status
    sub.plan_code = get_plan(plan_code).code
    sub.status = status
    if interval in ("month", "year"):
        sub.interval = interval
    if period_end is not None:
        sub.current_period_end = period_end
    if status == "past_due" and previous != "past_due":
        sub.past_due_since = utcnow()
    if status != "past_due":
        sub.past_due_since = None
    if status == "canceled" and previous != "canceled":
        sub.canceled_at = utcnow()
    if status in ("active", "trialing"):
        sub.canceled_at = None
    sync_workspace(db, sub)
    return sub


def mark_past_due(db: Session, sub: Subscription) -> None:
    if sub.status == "past_due":
        return
    apply_plan(db, sub, sub.plan_code, status="past_due")
    notify_role(db, sub.workspace_id, Role.owner, kind="billing.past_due",
                title=_("Payment failed"),
                body=_("We could not charge your card. Update your payment method within {days} days to avoid "
                       "interruption.", days=grace_days(db)),
                link="/settings/billing")


def mark_paid(db: Session, sub: Subscription) -> None:
    if sub.status in ("past_due", "trialing", "canceled") and sub.provider != "none":
        apply_plan(db, sub, sub.plan_code, status="active")


def extend_trial(db: Session, sub: Subscription, days: int) -> Subscription:
    base = _aware(sub.trial_ends_at)
    now = utcnow()
    sub.trial_ends_at = (base if base and base > now else now) + timedelta(days=days)
    if sub.status != "trialing":
        sub.plan_code = "trial"
        sub.status = "trialing"
        sub.past_due_since = None
        sync_workspace(db, sub)
    sub.reminders = {k: v for k, v in (sub.reminders or {}).items() if not k.startswith("trial")}
    return sub
