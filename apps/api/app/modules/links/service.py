"""Link tracking & attribution.

* :func:`track_text` — the publishing ``TEXT_FILTERS`` hook: replaces the URLs of a post's text, per account, by
  short links ``<base>/r/<code>`` that redirect with ``utm_source=<network>&utm_medium=social&utm_campaign=<…>``.
* :func:`register_click` — counts a click (bots ignored, one per visitor and link per 24 h).
* :func:`record_conversion` — stores an order / lead attributed by click code or by UTM tags.
* :func:`results_by` — clicks, conversions and revenue per ``post`` / ``platform`` / ``campaign`` / ``all``
  (other features — the Performance dashboard, reports — call this).
"""
import hashlib
import re
import secrets
import string
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, literal_column, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import utcnow
from app.core.errors import AppError
from app.core.i18n import _
from app.modules.workspaces.settings import get_setting, set_setting

from .models import Conversion, LinkClick, TrackedLink

UTC = timezone.utc
UTM_PARAMS = ("utm_source", "utm_medium", "utm_campaign")
REF_PARAM = "sref"
MEDIUM = "social"
URL_RE = re.compile(r"""https?://[^\s<>"'`]+""", re.IGNORECASE)
TRAILING = ").,!?;:'\"»”’…"
CODE_ALPHABET = string.ascii_letters + string.digits
MAX_CHARS = {"x": 280, "threads": 500, "instagram": 2200, "tiktok": 2200, "linkedin": 3000, "telegram": 4096,
             "facebook": 63206, "youtube": 5000, "pinterest": 800, "google_business": 1500}
BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|facebot|embedly|quora link|outbrain|pinterest|"
    r"vkshare|w3c_validator|whatsapp|telegram|skypeuripreview|discord|slack|curl|wget|python-|httpx|"
    r"go-http-client|java/|okhttp|headless|lighthouse|monitor|uptime|scanner|axios|node-fetch|libwww",
    re.IGNORECASE)
CONVERSION_KINDS = ("order", "lead", "signup", "other")
MAX_PUBLIC_VALUE = 10_000_000


# ---------------------------------------------------------------------------------------------- settings
def is_enabled(db: Session, workspace_id: int) -> bool:
    return bool(get_setting(db, workspace_id, "links.enabled", True))


def short_base(db: Session, workspace_id: int) -> str:
    return (get_setting(db, workspace_id, "links.base_url") or settings.public_api_url).rstrip("/")


def public_key(db: Session, workspace_id: int) -> str:
    """Public identifier of the workspace for the conversion pixel (safe to put in a web page)."""
    key = get_setting(db, workspace_id, "links.public_key")
    if not key:
        key = "pk_" + secrets.token_urlsafe(12)
        set_setting(db, workspace_id, "links.public_key", key)
    return key


def workspace_for_key(db: Session, key: str | None) -> int | None:
    from app.modules.workspaces.models import WorkspaceSetting
    if not key or not key.startswith("pk_") or len(key) > 40:
        return None
    rows = db.scalars(select(WorkspaceSetting).where(WorkspaceSetting.key == "links.public_key")).all()
    return next((row.workspace_id for row in rows if row.value == key), None)


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(("sai-conv:" + secret).encode()).hexdigest()


def new_secret(db: Session, workspace_id: int) -> str:
    """Server-to-server conversion key (shown once; only its hash is kept)."""
    secret = "sk_" + secrets.token_urlsafe(24)
    set_setting(db, workspace_id, "links.secret_hash", _hash_secret(secret))
    return secret


def workspace_for_secret(db: Session, secret: str | None) -> int | None:
    from app.modules.workspaces.models import WorkspaceSetting
    if not secret or not secret.startswith("sk_"):
        return None
    wanted = _hash_secret(secret)
    rows = db.scalars(select(WorkspaceSetting).where(WorkspaceSetting.key == "links.secret_hash")).all()
    return next((row.workspace_id for row in rows if row.value and secrets.compare_digest(row.value, wanted)), None)


# ---------------------------------------------------------------------------------------------- links
def make_code(db: Session) -> str:
    for _attempt in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _i in range(7))
        if not db.scalar(select(TrackedLink.id).where(TrackedLink.code == code)):
            return code
    raise AppError(_("Could not create a short link, please retry."), code="code_collision")


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()


def campaign_name_for(db: Session, post) -> str:
    if post.campaign_id:
        from app.modules.planning.models import Campaign
        campaign = db.get(Campaign, post.campaign_id)
        if campaign and campaign.workspace_id == post.workspace_id:
            return campaign.name
    return (post.name or "").strip() or f"post-{post.id}"


def destination(link: TrackedLink, add_ref: bool = True) -> str:
    """The final URL: the original one with our UTM tags (and the click reference for the pixel)."""
    parts = urlsplit(link.url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k not in UTM_PARAMS and k != REF_PARAM]
    for key in UTM_PARAMS:
        value = getattr(link, key)
        if value:
            query.append((key, value))
    if add_ref:
        query.append((REF_PARAM, link.code))
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), parts.fragment))


def link_for(db: Session, post, account, url: str) -> TrackedLink:
    """The tracked link of ``url`` for this post on this account (created once, reused on retries)."""
    digest = url_hash(url)
    link = db.scalar(select(TrackedLink).where(
        TrackedLink.workspace_id == post.workspace_id, TrackedLink.post_id == post.id,
        TrackedLink.account_id == account.id, TrackedLink.url_hash == digest))
    if link:
        return link
    link = TrackedLink(workspace_id=post.workspace_id, code=make_code(db), url=url, url_hash=digest, kind="post",
                       label=account.name, post_id=post.id, account_id=account.id, platform=account.platform,
                       campaign_id=post.campaign_id, utm_source=account.platform, utm_medium=MEDIUM,
                       utm_campaign=campaign_name_for(db, post)[:200])
    db.add(link)
    db.flush()
    return link


def find_urls(text: str, own_prefixes: tuple[str, ...], retag: bool) -> list[str]:
    urls = []
    for match in URL_RE.findall(text or ""):
        url = match.rstrip(TRAILING)
        if not url or url in urls or url.startswith(own_prefixes):
            continue
        query = dict(parse_qsl(urlsplit(unescape(url)).query))
        if not retag and any(key in query for key in UTM_PARAMS):
            continue  # the author tagged this link on purpose
        urls.append(url)
    return urls


def _replace_url(text: str, url: str, short: str) -> str:
    """Replace ``url`` only where it is a whole link (not a prefix of a longer one)."""
    pattern = re.compile(re.escape(url) + r"(?![^\s<>\"'`" + re.escape(TRAILING) + r"])")
    return pattern.sub(short, text)


def track_text(db: Session, post, account, text: str) -> str:
    """``TEXT_FILTERS`` hook: put tracked short links in the text sent to ``account``."""
    if not text or post is None or account is None or not getattr(post, "id", None):
        return text
    workspace_id = post.workspace_id
    if not is_enabled(db, workspace_id):
        return text
    base = short_base(db, workspace_id)
    own = (base + "/r/", settings.public_api_url.rstrip("/") + "/r/")
    urls = find_urls(text, own, bool(get_setting(db, workspace_id, "links.retag", False)))
    max_chars = MAX_CHARS.get(account.platform)
    for url in urls:
        link = link_for(db, post, account, unescape(url))
        candidate = _replace_url(text, url, f"{base}/r/{link.code}")
        # never push a text over the network's limit just because the short link is longer
        if max_chars and len(candidate) > max_chars and len(candidate) > len(text):
            continue
        text = candidate
    return text


def create_manual_link(db: Session, workspace_id: int, url: str, *, label: str | None = None,
                       campaign_id: int | None = None, utm_source: str | None = None,
                       utm_campaign: str | None = None) -> TrackedLink:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise AppError(_("Enter a full web address starting with https://"), code="bad_url")
    campaign_name = None
    if campaign_id:
        from app.modules.planning.models import Campaign
        campaign = db.get(Campaign, campaign_id)
        campaign_name = campaign.name if campaign else None
    platform = utm_source if utm_source in MAX_CHARS else None
    link = TrackedLink(workspace_id=workspace_id, code=make_code(db), url=url.strip(), url_hash=url_hash(url.strip()),
                       kind="manual", label=(label or "").strip() or None, platform=platform,
                       campaign_id=campaign_id, utm_source=(utm_source or "social")[:120], utm_medium=MEDIUM,
                       utm_campaign=(utm_campaign or campaign_name or label or "link")[:200])
    db.add(link)
    db.flush()
    return link


# ---------------------------------------------------------------------------------------------- clicks
def is_bot(user_agent: str | None) -> bool:
    return not user_agent or bool(BOT_RE.search(user_agent))


def device_of(user_agent: str) -> str:
    ua = user_agent.lower()
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if "mobi" in ua or "android" in ua or "iphone" in ua:
        return "mobile"
    return "desktop"


def visitor_id(ip: str | None, user_agent: str | None, when: datetime | None = None) -> str:
    day = (when or utcnow()).strftime("%Y-%m-%d")
    raw = f"{settings.secret_key}|{day}|{ip or '-'}|{user_agent or '-'}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def register_click(db: Session, link: TrackedLink, ip: str | None, user_agent: str | None,
                   referrer: str | None = None) -> bool:
    """Count a click unless it comes from a bot / link preview or the same visitor clicked in the last 24 h."""
    if is_bot(user_agent):
        return False
    now = utcnow()
    visitor = visitor_id(ip, user_agent, now)
    recent = db.scalar(select(LinkClick.id).where(LinkClick.link_id == link.id, LinkClick.visitor == visitor,
                                                  LinkClick.created_at >= now - timedelta(hours=24)))
    if recent:
        return False
    db.add(LinkClick(workspace_id=link.workspace_id, link_id=link.id, visitor=visitor,
                     referrer=(referrer or "")[:300] or None, device=device_of(user_agent or "")))
    link.clicks = (link.clicks or 0) + 1
    link.last_click_at = now
    db.flush()
    return True


# ---------------------------------------------------------------------------------------------- conversions
def attribute(db: Session, workspace_id: int, *, code: str | None = None, utm_source: str | None = None,
              utm_medium: str | None = None, utm_campaign: str | None = None) -> dict | None:
    """Find what brought a conversion: the clicked short link (best) or the UTM tags. None = not from social."""
    if code:
        link = db.scalar(select(TrackedLink).where(TrackedLink.code == code[:16],
                                                   TrackedLink.workspace_id == workspace_id))
        if link:
            return {"link_id": link.id, "post_id": link.post_id, "platform": link.platform,
                    "campaign_id": link.campaign_id}
    source = (utm_source or "").strip().lower()
    medium = (utm_medium or "").strip().lower()
    if not source or medium not in (MEDIUM, "social-media", "social media", "sm"):
        return None
    out = {"link_id": None, "post_id": None, "platform": source if source in MAX_CHARS else None,
           "campaign_id": None}
    name = (utm_campaign or "").strip()
    if name:
        from app.modules.planning.models import Campaign
        campaign = db.scalar(select(Campaign).where(Campaign.workspace_id == workspace_id,
                                                    func.lower(Campaign.name) == name.lower()))
        if campaign:
            out["campaign_id"] = campaign.id
        query = select(TrackedLink).where(
            TrackedLink.workspace_id == workspace_id, func.lower(TrackedLink.utm_campaign) == name.lower(),
            TrackedLink.post_id.is_not(None))
        if out["platform"]:
            query = query.where(TrackedLink.platform == out["platform"])
        link = db.scalar(query.order_by(TrackedLink.id.desc()))
        if link:
            out.update(post_id=link.post_id, campaign_id=out["campaign_id"] or link.campaign_id)
    return out


def record_conversion(db: Session, workspace_id: int, *, kind: str = "order", value: float = 0.0,
                      currency: str | None = None, external_id: str | None = None, code: str | None = None,
                      utm_source: str | None = None, utm_medium: str | None = None, utm_campaign: str | None = None,
                      post_id: int | None = None, occurred_at: datetime | None = None, source: str = "api",
                      note: str | None = None, product_id: int | None = None,
                      require_attribution: bool = False) -> Conversion | None:
    """Store a conversion (idempotent by ``external_id``). Returns None when it is not attributable and
    ``require_attribution`` is set (public pixel: we only keep conversions that came from social)."""
    kind = kind if kind in CONVERSION_KINDS else "other"
    found = attribute(db, workspace_id, code=code, utm_source=utm_source, utm_medium=utm_medium,
                      utm_campaign=utm_campaign)
    if post_id:
        from app.modules.social.models import Post
        post = db.get(Post, post_id)
        if not post or post.workspace_id != workspace_id:
            post = None
        if post:
            found = dict(found or {}, post_id=post.id)
            found.setdefault("campaign_id", post.campaign_id)
            found["campaign_id"] = found.get("campaign_id") or post.campaign_id
    if not found and require_attribution:
        return None
    external_id = (external_id or "").strip()[:120] or None
    if external_id:
        existing = db.scalar(select(Conversion).where(Conversion.workspace_id == workspace_id,
                                                      Conversion.kind == kind, Conversion.external_id == external_id))
        if existing:
            return existing
    found = found or {}
    conversion = Conversion(
        workspace_id=workspace_id, kind=kind, value=max(float(value or 0), 0.0),
        currency=(currency or "").upper()[:3] or None, external_id=external_id,
        occurred_at=occurred_at or utcnow(), source=source, link_id=found.get("link_id"),
        post_id=found.get("post_id"), platform=found.get("platform"), campaign_id=found.get("campaign_id"),
        product_id=product_id, utm_source=(utm_source or None) and utm_source[:120],
        utm_medium=(utm_medium or None) and utm_medium[:120], utm_campaign=(utm_campaign or None) and utm_campaign[:200],
        note=(note or None) and note[:300])
    try:
        with db.begin_nested():
            db.add(conversion)
            db.flush()
    except IntegrityError:  # same order reported twice at the same moment
        return db.scalar(select(Conversion).where(Conversion.workspace_id == workspace_id, Conversion.kind == kind,
                                                  Conversion.external_id == external_id))
    return conversion


# ---------------------------------------------------------------------------------------------- results
def _workspace_currency(db: Session, workspace_id: int) -> str:
    from app.modules.workspaces.models import Workspace
    workspace = db.get(Workspace, workspace_id)
    return (workspace.currency if workspace else None) or "SAR"


def results_by(db: Session, workspace_id: int, group: str, *, start: datetime | None = None,
               end: datetime | None = None, campaign_ids: list[int] | None = None,
               post_ids: list[int] | None = None, platforms: list[str] | None = None) -> dict:
    """``{key: {"clicks", "conversions", "orders", "leads", "revenue"}}``.

    ``group``: ``post`` (post id), ``platform``, ``campaign`` (campaign id) or ``all`` (key "all").
    Revenue sums conversions in the workspace currency (or without currency)."""
    currency = _workspace_currency(db, workspace_id)
    columns = {"post": (TrackedLink.post_id, Conversion.post_id),
               "platform": (TrackedLink.platform, Conversion.platform),
               "campaign": (TrackedLink.campaign_id, Conversion.campaign_id)}
    out: dict = defaultdict(lambda: {"clicks": 0, "conversions": 0, "orders": 0, "leads": 0, "revenue": 0.0})

    link_key, conv_key = columns.get(group, (None, None))
    click_q = (select(link_key if link_key is not None else literal_column("'all'"), func.count(LinkClick.id))
               .join(TrackedLink, TrackedLink.id == LinkClick.link_id)
               .where(LinkClick.workspace_id == workspace_id))
    conv_q = (select(conv_key if conv_key is not None else literal_column("'all'"), Conversion.kind,
                     func.count(Conversion.id), func.coalesce(func.sum(Conversion.value), 0.0))
              .where(Conversion.workspace_id == workspace_id,
                     func.coalesce(Conversion.currency, currency) == currency))
    conv_other = (select(conv_key if conv_key is not None else literal_column("'all'"), Conversion.kind, func.count(Conversion.id))
                  .where(Conversion.workspace_id == workspace_id, Conversion.currency.is_not(None),
                         Conversion.currency != currency))
    if start:
        click_q = click_q.where(LinkClick.created_at >= start)
        conv_q = conv_q.where(Conversion.occurred_at >= start)
        conv_other = conv_other.where(Conversion.occurred_at >= start)
    if end:
        click_q = click_q.where(LinkClick.created_at < end)
        conv_q = conv_q.where(Conversion.occurred_at < end)
        conv_other = conv_other.where(Conversion.occurred_at < end)
    if campaign_ids is not None:
        click_q = click_q.where(TrackedLink.campaign_id.in_(campaign_ids))
        conv_q = conv_q.where(Conversion.campaign_id.in_(campaign_ids))
        conv_other = conv_other.where(Conversion.campaign_id.in_(campaign_ids))
    if post_ids is not None:
        click_q = click_q.where(TrackedLink.post_id.in_(post_ids))
        conv_q = conv_q.where(Conversion.post_id.in_(post_ids))
        conv_other = conv_other.where(Conversion.post_id.in_(post_ids))
    if platforms:
        click_q = click_q.where(TrackedLink.platform.in_(platforms))
        conv_q = conv_q.where(Conversion.platform.in_(platforms))
        conv_other = conv_other.where(Conversion.platform.in_(platforms))
    if link_key is not None:
        click_q = click_q.group_by(link_key)
        conv_q = conv_q.group_by(conv_key, Conversion.kind)
        conv_other = conv_other.group_by(conv_key, Conversion.kind)
    else:
        conv_q = conv_q.group_by(Conversion.kind)
        conv_other = conv_other.group_by(Conversion.kind)

    for key, clicks in db.execute(click_q):
        if key is not None and clicks:
            out[key]["clicks"] += clicks
    def add(key, kind, count, value=0.0):
        if key is None:
            return
        row = out[key]
        row["conversions"] += count
        if kind == "order":
            row["orders"] += count
        elif kind in ("lead", "signup"):
            row["leads"] += count
        row["revenue"] = round(row["revenue"] + float(value or 0), 2)

    for key, kind, count, value in db.execute(conv_q):
        add(key, kind, count, value)
    for key, kind, count in db.execute(conv_other):  # other currencies: counted, not summed
        add(key, kind, count)
    return {k: dict(v) for k, v in out.items()}


def period_bounds(days: int) -> tuple[datetime, datetime]:
    end = utcnow()
    return end - timedelta(days=max(1, min(days, 365))), end


def daily_series(db: Session, workspace_id: int, start: datetime, end: datetime, tz) -> list[dict]:
    clicks = defaultdict(int)
    for (moment,) in db.execute(select(LinkClick.created_at).where(
            LinkClick.workspace_id == workspace_id, LinkClick.created_at >= start, LinkClick.created_at < end)):
        clicks[moment.astimezone(tz).date().isoformat()] += 1
    revenue = defaultdict(float)
    conversions = defaultdict(int)
    currency = _workspace_currency(db, workspace_id)
    for moment, value, cur in db.execute(select(Conversion.occurred_at, Conversion.value, Conversion.currency).where(
            Conversion.workspace_id == workspace_id, Conversion.occurred_at >= start, Conversion.occurred_at < end)):
        day = moment.astimezone(tz).date().isoformat()
        conversions[day] += 1
        if not cur or cur == currency:
            revenue[day] += float(value or 0)
    first, last = start.astimezone(tz).date(), (end - timedelta(seconds=1)).astimezone(tz).date()
    out, day = [], first
    while day <= last:
        key = day.isoformat()
        out.append({"date": key, "clicks": clicks[key], "conversions": conversions[key],
                    "revenue": round(revenue[key], 2)})
        day += timedelta(days=1)
    return out
