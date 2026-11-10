"""Plan limits for other features — CONTRACT (implemented by billing).

    from app.modules.billing import limits
    limits.check(db, ws_id, "social_accounts")      # raises LimitReached (HTTP 402) when the plan is full
    limits.check(db, ws_id, "posts_month")
    limits.check(db, ws_id, "ai_credits", amount=0.04)   # $ of AI the platform pays for (not BYO keys)
    limits.check(db, ws_id, "members")
    limits.check(db, ws_id, "storage", amount=len(content))  # bytes of a new file
    limits.feature(db, ws_id, "production")         # bool: is this feature in the plan?
    limits.require(db, ws_id, "production")         # same, but raises LimitReached when it is not

``check`` is for *writes*: a workspace whose trial ended, whose payment is overdue past the grace period,
whose subscription is canceled or which is suspended is read-only, so every ``check`` raises.

The error body is ``{"detail": "<translated message>", "code": "limit_reached", "reason": "limit" | "feature" |
"trial_ended" | "payment_overdue" | "canceled" | "suspended", "resource": ..., "limit": ..., "used": ...,
"plan": "pro", "upgrade": "business" | null}`` — the web app opens an upgrade dialog on this code.

Usage counted per workspace:
* ``social_accounts`` — active rows of ``social_accounts``;
* ``members`` — memberships + pending (not expired) invitations;
* ``posts_month`` — non-draft posts whose publish/schedule (or creation) date is in the current UTC month;
* ``ai_credits`` — $ cost this month of ``ai_usage`` rows with ``provider_id IS NULL`` (platform-provided AI;
  usage on a workspace's own keys is free and has a provider id);
* ``storage_gb`` — total size of ``media``.
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import LimitReached
from app.core.i18n import _, lazy

from .plans import FEATURES, RESOURCES, upgrade_for

GB = 1024 ** 3

RESOURCE_LABELS = {
    "social_accounts": lazy("social accounts"),
    "members": lazy("team members"),
    "posts_month": lazy("posts per month"),
    "ai_credits": lazy("AI credits"),
    "storage_gb": lazy("storage"),
}
FEATURE_LABELS = {
    "ai_studio": lazy("AI studio"),
    "templates": lazy("Templates"),
    "quick_publish": lazy("Quick publish"),
    "planning": lazy("Planning"),
    "inbox": lazy("Inbox"),
    "analytics": lazy("Analytics"),
    "approvals": lazy("Approvals"),
    "inbox_assistant": lazy("Inbox assistant"),
    "reports": lazy("Reports"),
    "link_tracking": lazy("Link tracking"),
    "evergreen": lazy("Evergreen posts"),
    "production": lazy("Production"),
    "priority_support": lazy("Priority support"),
    "custom_branding": lazy("Custom branding"),
}
PLAN_LABELS = {
    "trial": lazy("Free trial"),
    "starter": lazy("Starter"),
    "pro": lazy("Pro"),
    "business": lazy("Business"),
    "enterprise": lazy("Enterprise"),
}
BLOCKED_MESSAGES = {
    "trial_ended": lazy("Your free trial has ended. Choose a plan to keep creating — your data is safe."),
    "payment_overdue": lazy("Your last payment failed and the grace period is over. Update your payment method "
                            "to continue."),
    "canceled": lazy("Your subscription is canceled. Choose a plan to continue."),
    "suspended": lazy("This workspace is suspended. Please contact support."),
}


def plan_label(code: str | None) -> str:
    return _(PLAN_LABELS.get(code or "", code or ""))


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------- usage
def count_social_accounts(db: Session, workspace_id: int) -> int:
    from app.modules.social.models import SocialAccount
    return db.scalar(select(func.count()).select_from(SocialAccount).where(
        SocialAccount.workspace_id == workspace_id, SocialAccount.active.is_(True))) or 0


def count_members(db: Session, workspace_id: int) -> int:
    from app.modules.workspaces.models import Invitation, Membership
    members = db.scalar(select(func.count()).select_from(Membership).where(
        Membership.workspace_id == workspace_id)) or 0
    pending = db.scalar(select(func.count()).select_from(Invitation).where(
        Invitation.workspace_id == workspace_id, Invitation.accepted_at.is_(None),
        Invitation.expires_at > datetime.now(timezone.utc))) or 0
    return members + pending


def count_posts_month(db: Session, workspace_id: int) -> int:
    from app.modules.social.models import Post
    when = func.coalesce(Post.published_at, Post.scheduled_at, Post.created_at)
    return db.scalar(select(func.count()).select_from(Post).where(
        Post.workspace_id == workspace_id, Post.state != "draft", when >= month_start())) or 0


def ai_spend_month(db: Session, workspace_id: int) -> float:
    from app.modules.ai.models import AIUsage
    total = db.scalar(select(func.coalesce(func.sum(AIUsage.cost), 0.0)).where(
        AIUsage.workspace_id == workspace_id, AIUsage.provider_id.is_(None),
        AIUsage.created_at >= month_start()))
    return round(float(total or 0.0), 4)


def storage_bytes(db: Session, workspace_id: int) -> int:
    from app.core.models import Media
    return int(db.scalar(select(func.coalesce(func.sum(Media.size), 0)).where(
        Media.workspace_id == workspace_id)) or 0)


def used(db: Session, workspace_id: int, resource: str) -> float:
    if resource == "social_accounts":
        return count_social_accounts(db, workspace_id)
    if resource == "members":
        return count_members(db, workspace_id)
    if resource == "posts_month":
        return count_posts_month(db, workspace_id)
    if resource == "ai_credits":
        return ai_spend_month(db, workspace_id)
    if resource == "storage_gb":
        return round(storage_bytes(db, workspace_id) / GB, 3)
    return 0


def usage(db: Session, workspace_id: int, state=None) -> dict[str, dict]:
    """``{resource: {"used": x, "limit": y | None}}`` for the billing page and the platform admin."""
    if state is None:
        from .service import billing_state
        state = billing_state(db, workspace_id)
    return {resource: {"used": used(db, workspace_id, resource), "limit": state.limits.get(resource)}
            for resource in RESOURCES}


# ---------------------------------------------------------------- contract
def _fmt(resource: str, value: float) -> str:
    if resource == "ai_credits":
        return f"${value:,.2f}"
    if resource == "storage_gb":
        return f"{value:g} GB"
    return f"{int(value):,}"


def _blocked_error(state, resource: str | None = None) -> LimitReached:
    upgrade = None if state.blocked == "suspended" else (upgrade_for(state.plan) or state.plan.code)
    if state.plan.code == "trial" and upgrade:
        upgrade = "pro"
    return LimitReached(_(BLOCKED_MESSAGES[state.blocked]), code="limit_reached", reason=state.blocked,
                        resource=resource, plan=state.plan.code, upgrade=upgrade)


def check(db: Session, workspace_id: int, resource: str, amount: float = 1) -> None:
    from .service import billing_state
    state = billing_state(db, workspace_id)
    if state.blocked:
        raise _blocked_error(state, resource)
    if resource == "storage":  # amount in bytes
        resource, amount = "storage_gb", (amount or 0) / GB
    if resource not in RESOURCES:
        return
    limit = state.limits.get(resource)
    if limit is None:
        return
    current = used(db, workspace_id, resource)
    if current + amount <= limit + 1e-9:
        return
    upgrade = upgrade_for(state.plan, resource, current + amount)
    values = dict(plan=plan_label(state.plan.code), limit=_fmt(resource, limit),
                  resource=_(RESOURCE_LABELS[resource]), used=_fmt(resource, current))
    if upgrade:
        message = _("Your {plan} plan includes {limit} {resource} (used: {used}). Upgrade to {upgrade} for more.",
                    upgrade=plan_label(upgrade), **values)
    else:
        message = _("Your {plan} plan includes {limit} {resource} (used: {used}). Contact us to raise it.",
                    **values)
    raise LimitReached(message, code="limit_reached", reason="limit", resource=resource, limit=limit,
                       used=current, plan=state.plan.code, upgrade=upgrade)


def feature(db: Session, workspace_id: int, name: str) -> bool:
    if name not in FEATURES:
        return True
    from .service import billing_state
    return name in billing_state(db, workspace_id).plan.features


def require(db: Session, workspace_id: int, name: str) -> None:
    """Raise ``LimitReached`` (reason ``feature``) when the plan does not include the feature."""
    if feature(db, workspace_id, name):
        return
    from .service import billing_state
    state = billing_state(db, workspace_id)
    upgrade = upgrade_for(state.plan, feature=name) or "enterprise"
    raise LimitReached(
        _("{feature} is not included in your {plan} plan. Upgrade to {upgrade} to use it.",
          feature=_(FEATURE_LABELS.get(name, name)), plan=plan_label(state.plan.code), upgrade=plan_label(upgrade)),
        code="limit_reached", reason="feature", feature=name, plan=state.plan.code, upgrade=upgrade)
