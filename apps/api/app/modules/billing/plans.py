"""Plan catalog: limits, features and prices. Plans live in code (one place, reviewed like code).

A limit of ``None`` means unlimited. Prices are in USD; SAR is shown for Gulf customers (fixed peg, 3.75).
Per-workspace exceptions (enterprise deals) go in ``Subscription.limit_overrides`` — see ``effective_limits``.
"""
from dataclasses import dataclass, field

SAR_PER_USD = 3.75
TRIAL_DAYS = 14

# Resources counted by ``limits.check``.  ``storage_gb`` is checked in bytes through the "storage" resource.
RESOURCES = ("social_accounts", "members", "posts_month", "ai_credits", "storage_gb")

# Features a plan can include (``limits.feature(db, ws_id, name)``). Names not listed here are always allowed.
FEATURES = (
    "ai_studio",         # AI writing / image / video studio
    "templates",         # brand templates & frames
    "quick_publish",     # one-click publishing to several networks
    "planning",          # calendar, campaigns, content pillars
    "inbox",             # unified inbox (comments, DMs)
    "analytics",         # performance dashboards
    "approvals",         # approval workflow before publishing
    "inbox_assistant",   # AI assistant answering the inbox
    "reports",           # scheduled PDF / e-mail reports
    "link_tracking",     # short links & sales attribution
    "evergreen",         # automatic reposting of evergreen posts
    "production",        # production canvas (AI video / multi-step boards)
    "priority_support",
    "custom_branding",   # white-label reports, custom domain
)

_FREE = ("ai_studio", "templates", "quick_publish", "planning")
_STARTER = ("ai_studio", "templates", "quick_publish", "planning", "inbox", "analytics")
_PRO = _STARTER + ("approvals", "inbox_assistant", "reports", "link_tracking", "evergreen")
_BUSINESS = _PRO + ("production", "priority_support")
_ENTERPRISE = FEATURES


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price_month: float | None  # USD per month (None: on quote)
    price_year: float | None   # USD per year
    limits: dict = field(default_factory=dict)
    features: tuple = ()
    public: bool = True        # shown in the pricing table
    rank: int = 0              # upgrade order
    highlight: bool = False    # "most popular"

    @property
    def price_month_sar(self) -> float | None:
        return round(self.price_month * SAR_PER_USD) if self.price_month is not None else None

    @property
    def price_year_sar(self) -> float | None:
        return round(self.price_year * SAR_PER_USD) if self.price_year is not None else None

    @property
    def is_paid(self) -> bool:
        return bool(self.price_month) and self.code not in ("trial",)

    def monthly_value(self, interval: str = "month") -> float:
        """Monthly recurring revenue of one subscription (USD)."""
        if interval == "year" and self.price_year is not None:
            return round(self.price_year / 12, 2)
        return self.price_month or 0.0


PLANS: dict[str, Plan] = {
    "trial": Plan(
        "trial", "Free trial", 0, 0, public=False, rank=0, features=_BUSINESS,
        limits={"social_accounts": 10, "members": 5, "posts_month": 300, "ai_credits": 2.0, "storage_gb": 2},
    ),
    # What a workspace keeps for good when its trial ends without a subscription. AI only with its own key.
    "free": Plan(
        "free", "Free", 0, 0, rank=0, features=_FREE,
        limits={"social_accounts": 3, "members": 1, "posts_month": 30, "ai_credits": 0.0, "storage_gb": 1},
    ),
    "starter": Plan(
        "starter", "Starter", 19, 190, rank=1, features=_STARTER,
        limits={"social_accounts": 5, "members": 2, "posts_month": 150, "ai_credits": 3.0, "storage_gb": 5},
    ),
    "pro": Plan(
        "pro", "Pro", 49, 490, rank=2, features=_PRO, highlight=True,
        limits={"social_accounts": 15, "members": 6, "posts_month": 1000, "ai_credits": 10.0, "storage_gb": 25},
    ),
    "business": Plan(
        "business", "Business", 129, 1290, rank=3, features=_BUSINESS,
        limits={"social_accounts": 40, "members": 20, "posts_month": None, "ai_credits": 30.0, "storage_gb": 100},
    ),
    "enterprise": Plan(
        "enterprise", "Enterprise", None, None, rank=4, features=_ENTERPRISE,
        limits={"social_accounts": None, "members": None, "posts_month": None, "ai_credits": 100.0,
                "storage_gb": 1000},
    ),
}

PAID_PLANS = ("starter", "pro", "business")  # self-service through checkout (enterprise: contact sales)


def get_plan(code: str | None) -> Plan:
    return PLANS.get(code or "trial") or PLANS["trial"]


def effective_limits(plan: Plan, overrides: dict | None = None) -> dict:
    limits = dict(plan.limits)
    for key, value in (overrides or {}).items():
        if key in RESOURCES:
            limits[key] = value
    return limits


def upgrade_for(plan: Plan, resource: str | None = None, needed: float | None = None,
                feature: str | None = None) -> str | None:
    """The cheapest higher plan that lifts the limit (or includes the feature)."""
    for candidate in sorted(PLANS.values(), key=lambda p: p.rank):
        if candidate.rank <= plan.rank or not candidate.public:
            continue
        if feature and feature not in candidate.features:
            continue
        if resource:
            limit = candidate.limits.get(resource)
            if limit is not None and needed is not None and needed > limit:
                continue
        return candidate.code
    return None
