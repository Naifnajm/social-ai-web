from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Interval = Literal["month", "year"]


class PlanLimitsOut(BaseModel):
    social_accounts: int | None = None
    members: int | None = None
    posts_month: int | None = None
    ai_credits: float | None = None
    storage_gb: float | None = None


class PlanOut(BaseModel):
    code: str
    name: str
    price_month: float | None
    price_year: float | None
    price_month_sar: float | None
    price_year_sar: float | None
    limits: PlanLimitsOut
    features: list[str]
    highlight: bool = False
    self_service: bool  # can be bought online (enterprise: contact sales)


class PlansOut(BaseModel):
    plans: list[PlanOut]
    features: list[str]
    trial_days: int
    currency: str = "USD"
    sar_rate: float


class UsageItem(BaseModel):
    used: float
    limit: float | None = None  # None = unlimited


class BillingSummaryOut(BaseModel):
    plan: str
    plan_name: str
    status: Literal["trialing", "active", "past_due", "canceled"]
    blocked: str | None = None  # trial_ended | payment_overdue | canceled | suspended
    interval: str
    trial_ends_at: datetime | None = None
    trial_days_left: int | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    grace_ends_at: datetime | None = None
    provider: str
    has_payment_method: bool
    payments_enabled: bool  # online checkout configured on this platform
    usage: dict[str, UsageItem]
    features: list[str]
    can_manage: bool  # the current user is an owner
    announcement: str | None = None


class CheckoutIn(BaseModel):
    plan: Literal["starter", "pro", "business"]
    interval: Interval = "month"


class CheckoutOut(BaseModel):
    url: str | None = None
    updated: bool = False


class PortalOut(BaseModel):
    url: str


class InvoiceOut(BaseModel):
    id: str
    number: str | None = None
    status: str
    amount: float
    currency: str
    created: datetime
    period_end: datetime | None = None
    hosted_url: str | None = None
    pdf_url: str | None = None


class OnboardingStep(BaseModel):
    key: Literal["connect_account", "ai_provider", "brand_kit", "invite_teammate", "first_post"]
    done: bool
    href: str


class OnboardingOut(BaseModel):
    steps: list[OnboardingStep]
    done: int
    total: int
    dismissed: bool


# ---------------------------------------------------------------- platform admin
class AdminWorkspaceRow(BaseModel):
    id: int
    name: str
    slug: str
    status: str  # active | suspended (workspace)
    plan: str
    subscription_status: str
    blocked: str | None = None
    interval: str
    trial_ends_at: datetime | None = None
    current_period_end: datetime | None = None
    provider: str
    owner_email: str | None = None
    members: int
    social_accounts: int
    posts_month: int
    created_at: datetime


class AdminWorkspacePage(BaseModel):
    items: list[AdminWorkspaceRow]
    total: int
    page: int
    page_size: int


class AdminMemberOut(BaseModel):
    user_id: int
    name: str
    email: str
    role: str
    last_login_at: datetime | None = None
    is_active: bool


class AdminEventOut(BaseModel):
    id: int
    provider: str
    type: str
    summary: str | None = None
    created_at: datetime


class AdminErrorOut(BaseModel):
    id: int
    service: str
    operation: str
    status_code: int | None = None
    error: str | None = None
    created_at: datetime


class AdminWorkspaceDetail(BaseModel):
    workspace: AdminWorkspaceRow
    locale: str
    timezone: str
    currency: str
    note: str | None = None
    limit_overrides: dict | None = None
    usage: dict[str, UsageItem]
    features: list[str]
    members: list[AdminMemberOut]
    events: list[AdminEventOut]
    recent_errors: list[AdminErrorOut]
    provider_customer_id: str | None = None
    provider_subscription_id: str | None = None


class SuspendIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class ExtendTrialIn(BaseModel):
    days: int = Field(ge=1, le=365)


class AdminPlanIn(BaseModel):
    plan: Literal["trial", "starter", "pro", "business", "enterprise"]
    status: Literal["trialing", "active", "past_due", "canceled"] = "active"
    interval: Interval = "month"
    period_end: datetime | None = None
    limit_overrides: dict[str, float | None] | None = None
    note: str | None = Field(default=None, max_length=1000)


class DayCount(BaseModel):
    day: str
    count: int


class PlatformStatsOut(BaseModel):
    workspaces_total: int
    workspaces_active: int  # trialing or paying, not blocked/suspended
    workspaces_suspended: int
    users_total: int
    signups_7d: int
    signups_30d: int
    signups_by_day: list[DayCount]
    paying: int
    trialing: int
    past_due: int
    mrr_usd: float
    arr_usd: float
    by_plan: dict[str, int]


class PlatformSettingsOut(BaseModel):
    values: dict  # secrets appear as booleans (configured or not)
    schema_: dict[str, str] = Field(alias="schema")
    stripe_configured: bool
    stripe_webhook_configured: bool
    webhook_url: str
    ai_status: dict[str, dict] = {}  # last connection test of each platform AI key

    model_config = {"populate_by_name": True}


class PlatformSettingsIn(BaseModel):
    values: dict  # secrets: a new value sets it, "" clears it, omitted keeps it
