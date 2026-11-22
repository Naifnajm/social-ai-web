"""Radar source registry: one place that describes every place the radar can read from, what it needs, what it
costs and whether it works right now for a workspace.

    from app.modules.listening import registry
    registry.SOURCE_DEFS["web"].unit                       # "query"
    registry.unit_price(db, "x")                           # $ per post read (admin-editable, default 0.005)
    registry.health(db, workspace_id, "threads", query)    # {"status": "needs_connection", "message", "action"}
    registry.workspace_view(db, workspace_id, query)       # the Sources page: every source with status and cost

Access paths:
* ``owned``    — the workspace's own connected account (comments, tags, reviews on its pages). Free.
* ``public``   — an official search over the whole network or the web (X, Threads, YouTube, Brave, news…).
* ``provider`` — a third-party data provider for networks without an official search (TikTok). Paid, beta.

Statuses: ready | needs_connection | needs_key | needs_permission | needs_setup | quota_exhausted |
out_of_credits | not_in_plan | disabled | error. Each comes with a human message and the action that fixes it
(``connect`` a network, ``ask_admin`` for a key, ``request_permission`` from Meta/Google, ``edit_setup``,
``buy_credits``, ``upgrade``, ``test``).

Platform settings (superadmin, ``billing.platform``): secrets ``listening.<key>`` (write-only),
``listening.unit_prices`` ({source: $ per unit}), ``listening.sources_off`` ([source, …]) and
``listening.youtube_units_per_run``. Workspaces may bring their own key for X and Brave
(``listening.own_keys``, encrypted): their reads are then not charged.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.i18n import _, lazy

YOUTUBE_DAILY_UNITS = 10_000          # per Google project (the platform's key), resets at midnight Pacific time
YOUTUBE_UNITS_PER_RUN = 300           # default spend of one workspace in one run (admin-editable)
HEALTH_TTL = timedelta(hours=24)      # how long a failed run keeps the source in that state
STATUSES = ("ready", "needs_connection", "needs_key", "needs_permission", "needs_setup", "quota_exhausted",
            "out_of_credits", "not_in_plan", "disabled", "error")


@dataclass(frozen=True)
class SourceDef:
    key: str
    label: str                       # English name (the web app translates by key)
    access: str                      # owned | public | provider
    feature: str = "listening"       # plan feature that unlocks it
    platform: str | None = None      # social account to connect (owned sources, Threads search…)
    keys: tuple = ()                 # platform secrets it needs (all of them)
    any_keys: tuple = ()             # optional platform secrets (e.g. paid news APIs); one is enough to use them
    permission: str | None = None    # Meta / Google permission the platform app needs
    permission_doc: str | None = None
    unit: str | None = None          # what is paid for: post | query | request | call
    default_price: float = 0.0       # $ per unit (what the platform pays; the workspace pays it + markup)
    quota: str | None = None         # free quota, in words (English; shown on the admin page)
    byo: bool = False                # a workspace may use its own key (then nothing is charged)
    beta: bool = False
    option: str | None = None        # query option it reads (telegram_channels, app_store_ids…)
    available: bool = True           # False: no way to read it at all (Snapchat)
    docs: str | None = None
    terms_note: str | None = None
    covers: str = ""
    extra: dict = field(default_factory=dict)


SOURCE_DEFS: dict[str, SourceDef] = {s.key: s for s in [
    # ---- your accounts
    SourceDef("owned", "Comments on your posts", "owned",
              covers="Public comments the inbox receives on every connected account."),
    SourceDef("instagram", "Instagram", "owned", platform="instagram",
              permission="Instagram Public Content Access",
              permission_doc="https://developers.facebook.com/docs/features-reference/instagram-public-content-access",
              quota="30 different hashtags per account every 7 days; hashtag posts of the last 24 hours",
              covers="Posts that tag your account, and recent posts of your #hashtags."),
    SourceDef("facebook", "Facebook", "owned", platform="facebook", permission="pages_read_user_content",
              permission_doc="https://developers.facebook.com/docs/permissions#pages_read_user_content",
              covers="Posts that tag your Page and your Page reviews. Facebook has no public search."),
    SourceDef("threads", "Threads", "public", platform="threads", permission="threads_keyword_search",
              permission_doc="https://developers.facebook.com/docs/threads/keyword-search",
              covers="Keyword search over public Threads posts, and replies to your own posts."),
    SourceDef("youtube", "YouTube", "public", platform="youtube", keys=(), any_keys=("listening.youtube_api_key",),
              quota="10,000 units a day for the platform; a search costs 100 units",
              docs="https://developers.google.com/youtube/v3/determine_quota_cost",
              covers="New videos that mention your words."),
    SourceDef("youtube_comments", "YouTube comments", "public", platform="youtube",
              any_keys=("listening.youtube_api_key",),
              quota="1 unit per page of comments, from the same daily 10,000 units",
              docs="https://developers.google.com/youtube/v3/docs/commentThreads/list",
              covers="Comments on your channel's videos and on videos found by the search."),
    SourceDef("google_business", "Google reviews", "owned", platform="google_business",
              permission="Google Business Profile API access",
              permission_doc="https://developers.google.com/my-business/content/prereqs",
              covers="Reviews of your connected Google Business Profile locations."),
    SourceDef("linkedin", "LinkedIn", "owned", platform="linkedin", permission="r_organization_social",
              permission_doc="https://learn.microsoft.com/linkedin/marketing/community-management/",
              covers="Comments on your company page posts (LinkedIn has no public search)."),
    # ---- public search
    SourceDef("news", "News", "public", any_keys=("listening.gnews_api_key", "listening.newsapi_key"),
              covers="News sites (Google News; GNews or NewsAPI when the platform has a key)."),
    SourceDef("web", "Web, blogs and forums", "public", keys=("listening.brave_api_key",), unit="query",
              default_price=0.005, byo=True, docs="https://brave.com/search/api/",
              covers="The whole web through Brave Search: blogs, forums, review sites and news."),
    SourceDef("x", "X (Twitter)", "public", feature="listening_x", keys=("listening.x_bearer_token",), unit="post",
              default_price=0.005, byo=True, quota="3 million posts read per month for the platform",
              docs="https://docs.x.com/x-api/getting-started/pricing",
              covers="Full keyword and hashtag search of recent posts."),
    SourceDef("reddit", "Reddit", "public", keys=("listening.reddit_client_id", "listening.reddit_client_secret"),
              unit="call", default_price=0.00024, docs="https://support.reddithelp.com/hc/en-us/articles/16160319875092",
              terms_note="Commercial use of the Reddit API needs an agreement with Reddit.",
              covers="Posts and comments that mention your words, optionally in chosen subreddits."),
    SourceDef("telegram", "Telegram channels", "public", option="telegram_channels",
              covers="Recent posts of the public channels you list (no search across all of Telegram)."),
    SourceDef("app_store", "App Store reviews", "public", option="app_store_ids",
              covers="Customer reviews of the iPhone apps you list (Apple's public reviews feed)."),
    SourceDef("google_play", "Google Play reviews", "owned", option="google_play_ids",
              permission="Google Play Developer API (service account)",
              permission_doc="https://developers.google.com/android-publisher/reply-to-reviews",
              covers="Reviews of your own Android app (needs a Play Console service account)."),
    # ---- data providers
    SourceDef("tiktok", "TikTok", "provider", feature="listening_providers", keys=("listening.tiktok_provider_key",),
              unit="request", default_price=0.0015, beta=True, docs="https://scrapecreators.com/tiktok-api",
              terms_note="Through ScrapeCreators, an unofficial provider that collects public TikTok data. TikTok's "
                         "terms do not allow scraping; TikTok's official Research API is for non-commercial "
                         "research only.",
              covers="Public TikTok videos found by keyword or hashtag (caption, author, followers, views)."),
    SourceDef("snapchat", "Snapchat", "public", available=False,
              covers="Snapchat has no API for comments or public search."),
]}

PAID = tuple(k for k, s in SOURCE_DEFS.items() if s.default_price > 0)
GROUPS = ("owned", "public", "provider")


# ------------------------------------------------------------------------------------------- settings
def _platform(db: Session):
    from app.modules.billing import platform
    return platform


def secret(db: Session, key: str) -> str | None:
    return _platform(db).get_secret(db, key)


def unit_price(db: Session, source: str) -> float:
    """$ the platform pays per unit of ``source`` (admin-editable, default from the research)."""
    spec = SOURCE_DEFS.get(source)
    if not spec or not spec.unit:
        return 0.0
    prices = _platform(db).get_setting(db, "listening.unit_prices") or {}
    try:
        value = float(prices.get(source)) if isinstance(prices, dict) and prices.get(source) is not None else None
    except (TypeError, ValueError):
        value = None
    return max(0.0, value if value is not None else spec.default_price)


def switched_off(db: Session) -> set[str]:
    rows = _platform(db).get_setting(db, "listening.sources_off") or []
    return {str(r) for r in rows} if isinstance(rows, list) else set()


def youtube_units_per_run(db: Session) -> int:
    try:
        return max(1, int(_platform(db).get_setting(db, "listening.youtube_units_per_run", YOUTUBE_UNITS_PER_RUN)))
    except (TypeError, ValueError):
        return YOUTUBE_UNITS_PER_RUN


def _pacific_day() -> str:
    return (utcnow() - timedelta(hours=8)).date().isoformat()  # YouTube quotas reset at midnight Pacific time


def youtube_units_used(db: Session) -> int:
    row = _platform(db).get_setting(db, "listening.youtube_units") or {}
    return int(row.get("used") or 0) if isinstance(row, dict) and row.get("day") == _pacific_day() else 0


def spend_youtube_units(db: Session, units: int, *, exhausted: bool = False) -> None:
    used = YOUTUBE_DAILY_UNITS if exhausted else youtube_units_used(db) + int(units)
    _platform(db).set_setting(db, "listening.youtube_units", {"day": _pacific_day(), "used": used})


# ---------------------------------------------------------------------------------------- own keys (BYO)
def own_key(db: Session, workspace_id: int, source: str) -> str | None:
    from app.core.crypto import decrypt
    from app.modules.workspaces.settings import get_setting
    if not SOURCE_DEFS.get(source, SourceDef("", "", "")).byo:
        return None
    rows = get_setting(db, workspace_id, "listening.own_keys") or {}
    try:
        return decrypt(rows.get(source)) if rows.get(source) else None
    except Exception:  # a key encrypted with another secret: treat as missing
        return None


def set_own_key(db: Session, workspace_id: int, source: str, value: str | None) -> None:
    from app.core.crypto import encrypt
    from app.modules.workspaces.settings import get_setting, set_setting
    rows = dict(get_setting(db, workspace_id, "listening.own_keys") or {})
    if value:
        rows[source] = encrypt(value.strip())
    else:
        rows.pop(source, None)
    set_setting(db, workspace_id, "listening.own_keys", rows)


def key_for(db: Session, workspace_id: int, source: str, name: str | None = None) -> tuple[str | None, bool]:
    """(key, own): the workspace's own key when it set one, else the platform's ``name`` secret."""
    own = own_key(db, workspace_id, source)
    if own:
        return own, True
    spec = SOURCE_DEFS[source]
    return secret(db, name or (spec.keys[0] if spec.keys else "")), False


# ------------------------------------------------------------------------------------------- health
def _state(status: str, message: str, action: dict | None = None, **extra) -> dict:
    return {"status": status, "message": message, "action": action, **extra}


def _accounts(db: Session, workspace_id: int, platform: str) -> list:
    from app.modules.social.models import SocialAccount
    return list(db.scalars(select(SocialAccount).where(
        SocialAccount.workspace_id == workspace_id, SocialAccount.platform == platform,
        SocialAccount.active.is_(True), SocialAccount.state == "connected")))


def in_plan(db: Session, workspace_id: int, source: str) -> bool:
    from app.modules.billing import limits
    spec = SOURCE_DEFS[source]
    return limits.feature(db, workspace_id, "listening") and limits.feature(db, workspace_id, spec.feature)


NETWORK_NAMES = {"google_business": lazy("Google Business Profile")}


def _connect(platform: str, label: str) -> dict:
    network = _(NETWORK_NAMES[platform]) if platform in NETWORK_NAMES else label
    return _state("needs_connection", _("Connect a {network} account to use this source.", network=network),
                  {"kind": "connect", "platform": platform})


def _ask_admin(what: str) -> dict:
    return _state("needs_key", _("The platform admin must add the {what} in Admin › Radar sources.", what=what),
                  {"kind": "ask_admin", "what": what})


def _base_health(db: Session, workspace_id: int, source: str) -> dict:
    """What the source needs, without looking at a setup or at the last run."""
    spec = SOURCE_DEFS[source]
    if not spec.available:
        return _state("disabled", _("Snapchat offers no API for comments or public search, so it cannot be "
                                    "listened to."))
    if source in switched_off(db):
        return _state("disabled", _("The platform admin turned this source off."), {"kind": "ask_admin",
                                                                                    "what": spec.label})
    if not in_plan(db, workspace_id, source):
        return _state("not_in_plan", _("This source is not included in your plan."), {"kind": "upgrade"})
    if source == "linkedin":
        accounts = _accounts(db, workspace_id, "linkedin")
        orgs = [a for a in accounts if (a.external_id or "").startswith("urn:li:organization:")]
        if not orgs:
            return _state("needs_connection", _("Connect your LinkedIn company page (not a personal profile): "
                                                "LinkedIn only shares comments on your own page."),
                          {"kind": "connect", "platform": "linkedin"})
        scopes = str((orgs[0].extra or {}).get("scopes") or "")
        if scopes and "r_organization_social" not in scopes:
            return _state("needs_permission", _("The LinkedIn connection lacks the r_organization_social permission. "
                                                "Reconnect the page after the app gets Community Management "
                                                "access."), {"kind": "request_permission",
                                                             "permission": spec.permission, "doc": spec.permission_doc})
        return _state("ready", _("Ready."))
    if source == "google_play":
        return _state("needs_key", _("Google Play reviews need a Play Console service account, which is not "
                                     "connected yet."), {"kind": "request_permission", "permission": spec.permission,
                                                         "doc": spec.permission_doc})
    if source in ("youtube", "youtube_comments"):
        if not secret(db, "listening.youtube_api_key") and not _accounts(db, workspace_id, "youtube"):
            return _state("needs_connection", _("Connect a YouTube channel, or ask the platform admin to add the "
                                                "YouTube API key."), {"kind": "connect", "platform": "youtube"})
        if youtube_units_used(db) >= YOUTUBE_DAILY_UNITS:
            return _state("quota_exhausted", _("Today's YouTube quota is used up. It comes back after midnight "
                                               "(Pacific time)."))
        return _state("ready", _("Ready."))
    if spec.platform and not _accounts(db, workspace_id, spec.platform):
        return _connect(spec.platform, spec.label)
    if spec.keys:
        own = own_key(db, workspace_id, source) if spec.byo else None
        if not own and not all(secret(db, k) for k in spec.keys):
            return _ask_admin(_key_label(source))
    if spec.default_price > 0 and not own_key(db, workspace_id, source):
        from app.modules.billing import credits
        left = credits.available(db, workspace_id).get("available_usd")
        if left is not None and left <= 0:
            return _state("out_of_credits", _("Your AI credits are used up. Buy credits to keep reading this "
                                              "source."), {"kind": "buy_credits"})
    note = None
    if spec.permission and source in ("threads", "instagram"):
        note = _("Keyword search needs Meta's approval of {permission} for the platform app.",
                 permission=spec.permission)
    return _state("ready", _("Ready."), note=note) if note else _state("ready", _("Ready."))


def _key_label(source: str) -> str:
    return {"web": "Brave Search API key", "x": "X API bearer token", "reddit": "Reddit API client id and secret",
            "tiktok": "TikTok data provider key (ScrapeCreators)"}.get(source, f"{SOURCE_DEFS[source].label} key")


def health(db: Session, workspace_id: int, source: str, query=None) -> dict:
    """Is ``source`` usable for the workspace (and for ``query``, its options, cap and last run)?"""
    state = _base_health(db, workspace_id, source)
    if state["status"] != "ready" or query is None:
        return state
    spec = SOURCE_DEFS[source]
    if spec.option and not ((query.options or {}).get(spec.option)):
        return _state("needs_setup", _("Add what to read in the setup ({field}).", field=spec.option),
                      {"kind": "edit_setup", "field": spec.option})
    last = ((query.cursors or {}).get(source) or {}).get("_health")
    if last and last.get("status") in STATUSES and last.get("status") != "ready":
        from app.modules.listening.collectors import _date
        if _date(last.get("at")) > utcnow() - HEALTH_TTL:
            action = last.get("action")
            if last["status"] == "needs_permission" and spec.permission:
                action = {"kind": "request_permission", "permission": spec.permission, "doc": spec.permission_doc}
            elif last["status"] == "out_of_credits":
                action = {"kind": "buy_credits"}
            elif not action:
                action = {"kind": "test"}
            return _state(last["status"], last.get("message") or "", action, at=last.get("at"))
    return state


# --------------------------------------------------------------------------------------------- views
def month_usage(db: Session, workspace_id: int | None = None) -> dict[str, dict]:
    """Units and $ of paid radar reads this month, per source (one workspace, or the whole platform)."""
    from app.modules.ai.models import AIUsage
    from app.modules.billing.limits import month_start
    stmt = select(AIUsage.model_name, func.coalesce(func.sum(AIUsage.units), 0.0), func.coalesce(func.sum(AIUsage.cost),
                  0.0), func.coalesce(func.sum(func.coalesce(AIUsage.price, AIUsage.cost)), 0.0), func.count()).where(
        AIUsage.capability == "data", AIUsage.created_at >= month_start())
    if workspace_id is not None:
        stmt = stmt.where(AIUsage.workspace_id == workspace_id)
    out = {}
    for name, units, cost, price, calls in db.execute(stmt.group_by(AIUsage.model_name)).all():
        source = source_of_usage(name)
        if source:
            out[source] = {"units": round(float(units)), "cost": round(float(cost), 4), "price": round(float(price), 4),
                           "calls": calls}
    return out


def usage_name(source: str) -> str:
    return f"Radar · {SOURCE_DEFS[source].label}"


def source_of_usage(name: str | None) -> str | None:
    for key in SOURCE_DEFS:
        if name == usage_name(key):
            return key
    return None


def cost_view(db: Session, source: str, workspace_id: int | None = None) -> dict:
    from app.modules.billing import credits
    spec = SOURCE_DEFS[source]
    if not spec.unit or not spec.default_price:
        return {"free": True, "unit": None, "unit_price": 0.0, "per_1000": 0.0, "own_key": False}
    base = unit_price(db, source)
    own = bool(workspace_id and own_key(db, workspace_id, source))
    price = 0.0 if own else credits.price_of(db, base)
    return {"free": own, "unit": spec.unit, "unit_cost": base, "unit_price": price,
            "per_1000": round(price * 1000, 2), "own_key": own}


def workspace_view(db: Session, workspace_id: int, query=None) -> list[dict]:
    usage = month_usage(db, workspace_id)
    used_by_query = set(query.sources or []) if query is not None else set()
    yt_used = youtube_units_used(db)
    out = []
    for key, spec in SOURCE_DEFS.items():
        row = {"key": key, "label": spec.label, "access": spec.access, "beta": spec.beta, "platform": spec.platform,
               "permission": spec.permission, "permission_doc": spec.permission_doc, "option": spec.option,
               "byo": spec.byo, "available": spec.available, "terms_note": spec.terms_note, "docs": spec.docs,
               "health": health(db, workspace_id, key, query if key in used_by_query else None),
               "cost": cost_view(db, key, workspace_id), "usage": usage.get(key),
               "in_query": key in used_by_query, "quota": None}
        if key in ("youtube", "youtube_comments"):
            row["quota"] = {"used": yt_used, "limit": YOUTUBE_DAILY_UNITS, "per": "day"}
        if key == "x" and query is not None:
            from .collectors import x_reads_this_month
            row["quota"] = {"used": x_reads_this_month((query.cursors or {}).get("x") or {}),
                            "limit": query.x_monthly_cap, "per": "month"}
        out.append(row)
    return out


def admin_view(db: Session) -> list[dict]:
    from app.modules.billing import credits
    usage = month_usage(db)
    off = switched_off(db)
    out = []
    for key, spec in SOURCE_DEFS.items():
        names = list(spec.keys) + list(spec.any_keys)
        out.append({"key": key, "label": spec.label, "access": spec.access, "beta": spec.beta,
                    "available": spec.available, "enabled": key not in off, "feature": spec.feature,
                    "unit": spec.unit, "default_price": spec.default_price,
                    "unit_price": unit_price(db, key) if spec.unit else None,
                    "workspace_price": credits.price_of(db, unit_price(db, key)) if spec.unit else None,
                    "keys": {name: bool(secret(db, name)) for name in names}, "required_keys": list(spec.keys),
                    "permission": spec.permission, "permission_doc": spec.permission_doc, "quota": spec.quota,
                    "terms_note": spec.terms_note, "docs": spec.docs, "usage": usage.get(key)})
    return out


SECRET_KEYS = ("listening.x_bearer_token", "listening.youtube_api_key", "listening.brave_api_key",
               "listening.reddit_client_id", "listening.reddit_client_secret", "listening.tiktok_provider_key",
               "listening.gnews_api_key", "listening.newsapi_key")
