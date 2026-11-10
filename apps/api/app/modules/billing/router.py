"""Billing API: public plan catalog, the workspace's subscription (checkout, portal, invoices), the onboarding
checklist, and the platform admin (``/api/admin/...``, superadmins only — see ``admin.py``)."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError
from app.core.i18n import _
from app.modules.workspaces.models import Invitation, Membership, Role
from app.modules.workspaces.settings import get_setting, set_setting

from . import limits, platform
from .admin import router as admin_router
from .plans import FEATURES, PAID_PLANS, PLANS, SAR_PER_USD, Plan
from .providers import get_provider
from .schemas import (
    BillingSummaryOut,
    CheckoutIn,
    CheckoutOut,
    InvoiceOut,
    OnboardingOut,
    OnboardingStep,
    PlanLimitsOut,
    PlanOut,
    PlansOut,
    PortalOut,
    UsageItem,
)
from .service import billing_state, ensure_subscription, trial_days

router = APIRouter(tags=["billing"])
router.include_router(admin_router)


def plan_out(plan: Plan) -> PlanOut:
    return PlanOut(code=plan.code, name=plan.name, price_month=plan.price_month, price_year=plan.price_year,
                   price_month_sar=plan.price_month_sar, price_year_sar=plan.price_year_sar,
                   limits=PlanLimitsOut(**plan.limits), features=list(plan.features), highlight=plan.highlight,
                   self_service=plan.code in PAID_PLANS)


@router.get("/billing/plans", response_model=PlansOut)
def list_plans(db: Session = Depends(get_db)):
    """Public: the pricing table (landing page, billing settings, mobile)."""
    return PlansOut(plans=[plan_out(p) for p in sorted(PLANS.values(), key=lambda p: p.rank) if p.public],
                    features=list(FEATURES), trial_days=trial_days(db), sar_rate=SAR_PER_USD)


@router.get("/billing/summary", response_model=BillingSummaryOut)
def summary(ctx: Ctx = Depends(workspace_ctx())):
    """Plan, status, trial/grace dates and usage meters of the current workspace (any member: trial banner)."""
    sub = ensure_subscription(ctx.db, ctx.workspace)
    state = billing_state(ctx.db, ctx.workspace.id)
    provider = get_provider(sub.provider if sub.provider in ("stripe", "moyasar") else None)
    return BillingSummaryOut(
        plan=state.plan.code, plan_name=limits.plan_label(state.plan.code), status=state.status,
        blocked=state.blocked, interval=sub.interval, trial_ends_at=state.trial_ends_at,
        trial_days_left=state.trial_days_left, current_period_end=state.current_period_end,
        cancel_at_period_end=state.cancel_at_period_end, grace_ends_at=state.grace_ends_at,
        provider=sub.provider, has_payment_method=bool(sub.provider_customer_id and sub.provider == "stripe"),
        payments_enabled=provider.configured(ctx.db),
        usage={k: UsageItem(**v) for k, v in limits.usage(ctx.db, ctx.workspace.id, state).items()},
        features=list(state.plan.features), can_manage=ctx.can(Role.owner),
        announcement=platform.get_setting(ctx.db, "platform.announcement") or None,
    )


def _return_url(ctx: Ctx, query: str = "") -> str:
    locale = ctx.user.locale if ctx.user.locale in ("ar", "en") else "ar"
    return f"{settings.web_url.rstrip('/')}/{locale}/settings/billing{query}"


@router.post("/billing/checkout", response_model=CheckoutOut)
def checkout(data: CheckoutIn, ctx: Ctx = Depends(workspace_ctx(Role.owner))):
    """Subscribe / upgrade / downgrade. Returns a hosted payment page URL, or ``updated`` when an existing
    subscription was moved to the new plan in place."""
    if ctx.workspace.status != "active":
        raise AppError(_("This workspace is suspended. Please contact support."), code="workspace_suspended",
                       status_code=403)
    sub = ensure_subscription(ctx.db, ctx.workspace)
    if sub.provider == "manual" and sub.status == "active":
        raise AppError(_("Your plan is managed by our team. Contact us to change it."), code="managed_plan")
    provider = get_provider()
    result = provider.checkout(ctx.db, ctx.workspace, sub, data.plan, data.interval, ctx.user,
                               success_url=_return_url(ctx, "?checkout=success&session_id={CHECKOUT_SESSION_ID}"),
                               cancel_url=_return_url(ctx, "?checkout=cancel"))
    return CheckoutOut(url=result.url, updated=result.updated)


@router.post("/billing/portal", response_model=PortalOut)
def portal(ctx: Ctx = Depends(workspace_ctx(Role.owner))):
    """Customer portal (payment method, invoices, cancel)."""
    sub = ensure_subscription(ctx.db, ctx.workspace)
    return PortalOut(url=get_provider(sub.provider if sub.provider != "none" else None)
                     .portal(ctx.db, ctx.workspace, sub, _return_url(ctx)))


@router.get("/billing/invoices", response_model=list[InvoiceOut])
def invoices(ctx: Ctx = Depends(workspace_ctx(Role.owner))):
    sub = ensure_subscription(ctx.db, ctx.workspace)
    if sub.provider not in ("stripe", "moyasar"):
        return []
    return [InvoiceOut(**vars(item)) for item in get_provider(sub.provider).invoices(ctx.db, ctx.workspace, sub)]


# ---------------------------------------------------------------- onboarding checklist
ONBOARDING_HREFS = {
    "connect_account": "/settings/accounts",
    "ai_provider": "/settings/ai",
    "brand_kit": "/settings/brand",
    "invite_teammate": "/settings/members",
    "first_post": "/studio",
}


def _count(db: Session, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


@router.get("/onboarding", response_model=OnboardingOut)
def onboarding(ctx: Ctx = Depends(workspace_ctx())):
    """First steps of a new workspace, computed from existing rows (nothing to tick by hand)."""
    from app.modules.ai.models import AIProvider
    from app.modules.brand.models import BrandKit
    from app.modules.social.models import Post, SocialAccount

    ws = ctx.workspace.id
    done = {
        "connect_account": _count(ctx.db, SocialAccount, SocialAccount.workspace_id == ws) > 0,
        "ai_provider": _count(ctx.db, AIProvider, AIProvider.workspace_id == ws) > 0
        or bool(platform.get_setting(ctx.db, "ai.default_provider")),
        "brand_kit": _count(ctx.db, BrandKit, BrandKit.workspace_id == ws) > 0,
        "invite_teammate": _count(ctx.db, Membership, Membership.workspace_id == ws) > 1
        or _count(ctx.db, Invitation, Invitation.workspace_id == ws) > 0,
        "first_post": _count(ctx.db, Post, Post.workspace_id == ws,
                             Post.state.in_(("scheduled", "publishing", "posted", "partial"))) > 0,
    }
    steps = [OnboardingStep(key=key, done=value, href=ONBOARDING_HREFS[key]) for key, value in done.items()]
    return OnboardingOut(steps=steps, done=sum(done.values()), total=len(steps),
                         dismissed=bool(get_setting(ctx.db, ws, "billing.onboarding_dismissed", False)))


@router.post("/onboarding/dismiss", response_model=OnboardingOut)
def dismiss_onboarding(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    set_setting(ctx.db, ctx.workspace.id, "billing.onboarding_dismissed", True)
    return onboarding(ctx)
