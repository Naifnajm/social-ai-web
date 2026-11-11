"""Hourly billing reminders: trial ending soon / ended, grace period over (in-app + push, once each)."""
from datetime import timedelta

from sqlalchemy import select

from app.core.i18n import _, set_locale
from app.core.jobs import periodic, session_scope
from app.core.notify import notify_role
from app.modules.workspaces.models import Role, Workspace

from .config import billing_settings
from .models import Subscription
from .service import billing_state, utcnow


def _remind(db, sub: Subscription, key: str, **kwargs) -> bool:
    sent = dict(sub.reminders or {})
    if sent.get(key):
        return False
    workspace = db.get(Workspace, sub.workspace_id)
    set_locale(workspace.locale if workspace else None)
    notify_role(db, sub.workspace_id, Role.owner, link="/settings/billing", **kwargs)
    sent[key] = utcnow().isoformat()
    sub.reminders = sent
    return True


def run_reminders(db) -> int:
    """Send due reminders; returns how many were sent (also used by tests)."""
    count = 0
    soon = utcnow() + timedelta(days=billing_settings().billing_trial_reminder_days)
    for sub in db.scalars(select(Subscription).where(Subscription.status.in_(("trialing", "past_due")))).all():
        state = billing_state(db, sub.workspace_id)
        if sub.status == "trialing" and state.plan.code == "free":
            count += _remind(db, sub, "trial_ended", kind="billing.trial_ended", title=_("Your free trial has ended"),
                             body=_("You are now on the free plan. Choose a plan for more accounts, posts and AI."))
        elif sub.status == "trialing" and state.trial_ends_at and state.trial_ends_at <= soon:
            count += _remind(db, sub, "trial_soon", kind="billing.trial_ending",
                             title=_("Your free trial ends in {days} days", days=state.trial_days_left or 0),
                             body=_("Choose a plan now to keep everything running without interruption."))
        elif sub.status == "past_due" and state.blocked == "payment_overdue":
            count += _remind(db, sub, f"overdue_{(sub.past_due_since or utcnow()).date()}",
                             kind="billing.overdue", title=_("Your workspace is now read-only"),
                             body=_("The payment is still missing. Update your payment method to unlock it."))
    return count


@periodic(seconds=3600)
def billing_reminders():
    with session_scope() as db:
        run_reminders(db)
