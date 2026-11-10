"""Planning logic: campaign & pillar statistics, the Planner calendar, best-time hints and evergreen reposts.

Posts are created and published only through the publishing contract (``app.modules.social.service``).
"""
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.db import utcnow
from app.core.errors import ApiError, AppError, NotFound
from app.core.i18n import _
from app.core.models import Media
from app.modules.social import service as social
from app.modules.social.models import Post, PostTarget, SocialAccount
from app.modules.workspaces.models import Workspace

from .models import Campaign, ContentPillar

_logger = logging.getLogger(__name__)
UTC = timezone.utc

PUBLISHED = ("posted", "partial")
PENDING = ("scheduled", "to_approve")
MOVABLE = ("draft", "failed", "to_approve", "scheduled")
OPEN_COPY = ("draft", "to_approve", "scheduled", "publishing")
PALETTE = ["#0a0a0a", "#2563eb", "#db2777", "#059669", "#ea580c", "#7c3aed", "#0891b2", "#ca8a04", "#dc2626",
           "#4f46e5", "#65a30d", "#9333ea"]

# General industry guidance, used until the publishing feature knows better (weekday 0 = Monday, local time).
BENCHMARK_SLOTS = {
    "facebook": [(1, 9), (2, 10), (3, 12), (4, 9), (2, 13)],
    "instagram": [(0, 11), (1, 12), (2, 19), (3, 11), (4, 20)],
    "linkedin": [(1, 8), (2, 9), (3, 10), (2, 12), (1, 17)],
    "x": [(1, 9), (2, 9), (3, 9), (2, 12), (4, 8)],
    "tiktok": [(1, 19), (3, 19), (4, 20), (5, 11), (6, 20)],
    "threads": [(1, 8), (2, 9), (3, 19), (0, 12), (4, 18)],
    "telegram": [(0, 9), (2, 9), (4, 19), (1, 20), (3, 9)],
}


# ---------------------------------------------------------------------------------------------- dates
def workspace_tz(workspace: Workspace) -> ZoneInfo:
    try:
        return ZoneInfo(workspace.timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def day_to_dt(day: date | None) -> datetime | None:
    """Store a day at 12:00 UTC (same calendar day in every zone from UTC-11 to UTC+11)."""
    return datetime.combine(day, time(12), tzinfo=UTC) if day else None


def as_day(dt: datetime | None, tz: ZoneInfo) -> date | None:
    """The calendar day of a stored "day" value (noon or midnight UTC = that UTC day; else the local day)."""
    dt = aware(dt)
    if dt is None:
        return None
    utc = dt.astimezone(UTC)
    if utc.minute == 0 and utc.second == 0 and utc.hour in (0, 12):
        return utc.date()
    return utc.astimezone(tz).date()


def local_today(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


def local_dt(day: date, hour_minute: str, tz: ZoneInfo) -> datetime:
    """``day`` + "HH:MM" in ``tz`` → aware UTC datetime."""
    try:
        hh, mm = (int(x) for x in hour_minute.split(":")[:2])
        moment = time(hh, mm)
    except (ValueError, TypeError):
        raise AppError(_("Choose a valid time (HH:MM)."), code="bad_time")
    return datetime.combine(day, moment, tzinfo=tz).astimezone(UTC)


def day_start_utc(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


def post_day(post: Post, tz: ZoneInfo) -> tuple[date | None, str | None]:
    """Where a post sits on the calendar: (local day, "HH:MM" or None for a draft planned for a day)."""
    moment = aware(post.published_at or post.scheduled_at)
    if moment:
        local = moment.astimezone(tz)
        return local.date(), local.strftime("%H:%M")
    return as_day(post.planned_date, tz), None


def next_color(db: Session, model, workspace_id: int) -> str:
    count = db.scalar(select(func.count()).select_from(model).where(model.workspace_id == workspace_id)) or 0
    return PALETTE[(count + 1) % len(PALETTE)]


# ---------------------------------------------------------------------------------------------- campaigns
def campaign_stats(db: Session, workspace_id: int, campaign_ids: list[int]) -> dict[int, dict]:
    """Per campaign: post counts by state, metrics of published targets, link clicks and revenue."""
    out = {cid: {"post_count": 0, "published_count": 0, "scheduled_count": 0, "draft_count": 0,
                 "impressions": 0, "reach": 0, "engagements": 0, "engagement_rate": 0.0, "video_views": 0,
                 "progress": 0.0, "clicks": 0, "conversions": 0, "revenue": 0.0} for cid in campaign_ids}
    if not campaign_ids:
        return out
    rows = db.execute(select(Post.campaign_id, Post.state, func.count()).where(
        Post.workspace_id == workspace_id, Post.campaign_id.in_(campaign_ids)).group_by(Post.campaign_id, Post.state))
    for cid, state, count in rows:
        row = out[cid]
        row["post_count"] += count
        if state in PUBLISHED:
            row["published_count"] += count
        elif state in PENDING:
            row["scheduled_count"] += count
        elif state == "draft":
            row["draft_count"] += count
    metrics = db.execute(
        select(Post.campaign_id, func.coalesce(func.sum(PostTarget.impressions), 0),
               func.coalesce(func.sum(PostTarget.reach), 0), func.coalesce(func.sum(PostTarget.engagements), 0),
               func.coalesce(func.sum(PostTarget.video_views), 0))
        .join(Post, Post.id == PostTarget.post_id)
        .where(PostTarget.workspace_id == workspace_id, PostTarget.state == "posted",
               Post.campaign_id.in_(campaign_ids))
        .group_by(Post.campaign_id))
    for cid, impressions, reach, engagements, views in metrics:
        row = out[cid]
        row.update(impressions=int(impressions), reach=int(reach), engagements=int(engagements),
                   video_views=int(views))
    from app.modules.links import service as links  # clicks & revenue of the tracked links
    results = links.results_by(db, workspace_id, "campaign", campaign_ids=campaign_ids)
    for cid, row in out.items():
        base = row["impressions"] or row["reach"]
        row["engagement_rate"] = round(100.0 * row["engagements"] / base, 2) if base else 0.0
        row["progress"] = round(100.0 * row["published_count"] / row["post_count"], 1) if row["post_count"] else 0.0
        extra = results.get(cid) or {}
        row.update(clicks=extra.get("clicks", 0), conversions=extra.get("conversions", 0),
                   revenue=extra.get("revenue", 0.0))
    return out


def update_campaign_states(db: Session, workspace_id: int | None = None, today: date | None = None) -> int:
    """Start and finish campaigns by their dates (only those with ``auto_state``). Returns the number changed."""
    query = select(Campaign).where(Campaign.state != "finished", Campaign.auto_state.is_(True),
                                   Campaign.archived.is_(False))
    if workspace_id:
        query = query.where(Campaign.workspace_id == workspace_id)
    campaigns = db.scalars(query).all()
    zones: dict[int, ZoneInfo] = {}
    changed = 0
    for campaign in campaigns:
        if campaign.workspace_id not in zones:
            zones[campaign.workspace_id] = workspace_tz(db.get(Workspace, campaign.workspace_id))
        tz = zones[campaign.workspace_id]
        now_day = today or local_today(tz)
        start, end = as_day(campaign.date_start, tz), as_day(campaign.date_end, tz)
        new = campaign.state
        if end and end < now_day:
            new = "finished"
        elif campaign.state == "planned" and start and start <= now_day:
            new = "running"
        if new != campaign.state:
            campaign.state = new
            changed += 1
    db.flush()
    return changed


# ---------------------------------------------------------------------------------------------- pillars
def pillar_shares(db: Session, workspace_id: int) -> tuple[dict, int, dict, int]:
    """``(published_by_pillar, published_total, planned_by_pillar, planned_total)`` for the last / next 30 days."""
    now = utcnow()
    base = select(Post.pillar_id, func.count()).where(Post.workspace_id == workspace_id).group_by(Post.pillar_id)
    past = base.where(Post.state.in_(PUBLISHED), Post.published_at >= now - timedelta(days=30))
    future = base.where(or_(
        and_(Post.state.in_(PENDING), Post.scheduled_at >= now, Post.scheduled_at < now + timedelta(days=30)),
        and_(Post.state == "draft", Post.scheduled_at.is_(None), Post.planned_date >= now - timedelta(days=1),
             Post.planned_date < now + timedelta(days=30)),
    ))

    def count(query):
        by_pillar, total = {}, 0
        for pillar_id, n in db.execute(query):
            total += n
            if pillar_id:
                by_pillar[pillar_id] = n
        return by_pillar, total

    return count(past) + count(future)


def pillar_rows(db: Session, workspace_id: int, include_inactive: bool = True) -> list[dict]:
    query = select(ContentPillar).where(ContentPillar.workspace_id == workspace_id)
    if not include_inactive:
        query = query.where(ContentPillar.active.is_(True))
    pillars = db.scalars(query.order_by(ContentPillar.position, ContentPillar.id)).all()
    done, done_total, planned, planned_total = pillar_shares(db, workspace_id)
    rows = []
    for pillar in pillars:
        share = round(100.0 * done.get(pillar.id, 0) / done_total, 1) if done_total else 0.0
        rows.append({
            "id": pillar.id, "name": pillar.name, "color": pillar.color, "description": pillar.description,
            "target_share": pillar.target_share, "position": pillar.position, "active": pillar.active,
            "published_30": done.get(pillar.id, 0), "share_30": share,
            "planned_30": planned.get(pillar.id, 0),
            "planned_share_30": round(100.0 * planned.get(pillar.id, 0) / planned_total, 1) if planned_total else 0.0,
            "gap": round(share - pillar.target_share, 1) if done_total else 0.0,
        })
    return rows


# ---------------------------------------------------------------------------------------------- best times
def benchmark_slots(platforms: list[str] | None) -> list[tuple[int, int, float]]:
    """Ranked (weekday, hour, score) from general benchmarks."""
    keys = [p for p in (platforms or []) if p in BENCHMARK_SLOTS] or list(BENCHMARK_SLOTS)
    weight: dict = defaultdict(float)
    for key in keys:
        for rank, (day, hour) in enumerate(BENCHMARK_SLOTS[key]):
            weight[(day, hour)] += 5 - rank
    top = max(weight.values()) if weight else 1
    return [(d, h, round(100 * v / top, 1)) for (d, h), v in sorted(weight.items(), key=lambda kv: -kv[1])]


def best_slots(db: Session, workspace: Workspace, platforms: list[str] | None = None, count: int = 3) -> list[dict]:
    """Upcoming best moments ``[{"at": aware UTC, "local": "YYYY-MM-DDTHH:MM", "weekday", "time"}]``.

    Asks the publishing feature (``social.next_best_slots``); falls back to benchmarks when it is not available."""
    tz = workspace_tz(workspace)
    slots = []
    try:
        for slot in social.next_best_slots(db, workspace.id, platforms or None, count=count) or []:
            at = slot.get("at") if isinstance(slot, dict) else None
            if isinstance(at, str):
                at = datetime.fromisoformat(at)
            if isinstance(at, datetime):
                slots.append(aware(at))
    except NotImplementedError:
        slots = []
    except (AppError, ApiError):
        _logger.info("best slots unavailable for workspace %s", workspace.id, exc_info=True)
        slots = []
    source = "service"
    if not slots:
        source = "benchmark"
        now_local = datetime.now(tz)
        for weekday, hour, _score in benchmark_slots(platforms)[:max(count * 2, 7)]:
            ahead = (weekday - now_local.weekday()) % 7
            candidate = datetime.combine(now_local.date() + timedelta(days=ahead), time(hour), tzinfo=tz)
            if candidate <= now_local + timedelta(minutes=30):
                candidate += timedelta(days=7)
            slots.append(candidate.astimezone(UTC))
        slots = sorted(set(slots))[:count]
    out = []
    for at in slots:
        local = at.astimezone(tz)
        out.append({"at": at, "local": local.strftime("%Y-%m-%dT%H:%M"), "weekday": local.weekday(),
                    "time": local.strftime("%H:%M"), "source": source})
    return out


def best_by_weekday(db: Session, workspace: Workspace, platforms: list[str] | None = None) -> list[dict]:
    """One hint per weekday (0 = Monday): the best hour to post that day."""
    hints: dict[int, dict] = {}
    for slot in best_slots(db, workspace, platforms, count=14):
        if slot["weekday"] not in hints:
            hints[slot["weekday"]] = {"weekday": slot["weekday"], "time": slot["time"], "top": len(hints) < 3,
                                      "source": slot["source"]}
    for weekday, hour, _score in benchmark_slots(platforms):
        if weekday not in hints:
            hints[weekday] = {"weekday": weekday, "time": "%02d:00" % hour, "top": False, "source": "benchmark"}
    return [hints.get(d) or {"weekday": d, "time": None, "top": False, "source": "benchmark"} for d in range(7)]


# ---------------------------------------------------------------------------------------------- planner
def _thumbs(db: Session, posts: list[Post]) -> dict[int, Media]:
    first: dict[int, int] = {}
    for post in posts:
        links = sorted(post.media_links, key=lambda link: (link.role == "story", link.position))
        if links:
            first[post.id] = links[0].media_id
    medias = {m.id: m for m in db.scalars(select(Media).where(Media.id.in_(set(first.values()))))} if first else {}
    return {pid: medias[mid] for pid, mid in first.items() if mid in medias}


def planner_item(post: Post, tz: ZoneInfo, *, thumb: Media | None, campaigns: dict, pillars: dict,
                 authors: dict | None = None) -> dict:
    day, hour = post_day(post, tz)
    campaign = campaigns.get(post.campaign_id)
    pillar = pillars.get(post.pillar_id)
    return {
        "id": post.id,
        "name": post.name or "",
        "preview": (post.content or "")[:160],
        "state": post.state,
        "day": day.isoformat() if day else None,
        "time": hour,
        "scheduled_at": aware(post.scheduled_at),
        "published_at": aware(post.published_at),
        "platforms": sorted({a.platform for a in post.accounts}),
        "account_ids": sorted(a.id for a in post.accounts),
        "media": {"id": thumb.id, "kind": thumb.kind, "url": f"/api/media/{thumb.id}/file"} if thumb else None,
        "media_count": len(post.media_links),
        "campaign": {"id": campaign.id, "name": campaign.name, "color": campaign.color} if campaign else None,
        "pillar": {"id": pillar.id, "name": pillar.name, "color": pillar.color} if pillar else None,
        "author": (authors or {}).get(post.author_id, ""),
        "evergreen": bool(post.evergreen),
        "recycled": bool(post.recycled_from_id),
        "movable": post.state in MOVABLE,
    }


def _lookups(db: Session, workspace_id: int):
    campaigns = {c.id: c for c in db.scalars(select(Campaign).where(Campaign.workspace_id == workspace_id))}
    pillars = {p.id: p for p in db.scalars(select(ContentPillar).where(ContentPillar.workspace_id == workspace_id))}
    return campaigns, pillars


def _authors(db: Session, posts: list[Post]) -> dict[int, str]:
    from app.modules.auth.models import User
    ids = {p.author_id for p in posts if p.author_id}
    return {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def items_for(db: Session, workspace: Workspace, posts: list[Post]) -> list[dict]:
    tz = workspace_tz(workspace)
    campaigns, pillars = _lookups(db, workspace.id)
    thumbs = _thumbs(db, posts)
    authors = _authors(db, posts)
    return [planner_item(p, tz, thumb=thumbs.get(p.id), campaigns=campaigns, pillars=pillars, authors=authors)
            for p in posts]


def planner_posts(db: Session, workspace: Workspace, start: date, end: date, *, account_id: int | None = None,
                  campaign_id: int | None = None, pillar_id: int | None = None, state: str | None = None,
                  platform: str | None = None) -> list[dict]:
    """Posts placed on local days ``[start, end)``."""
    tz = workspace_tz(workspace)
    s, e = day_start_utc(start, tz), day_start_utc(end, tz)
    query = (select(Post).where(Post.workspace_id == workspace.id).where(or_(
        and_(Post.published_at >= s, Post.published_at < e),
        and_(Post.published_at.is_(None), Post.scheduled_at >= s, Post.scheduled_at < e),
        and_(Post.published_at.is_(None), Post.scheduled_at.is_(None),
             Post.planned_date >= s - timedelta(days=1), Post.planned_date < e + timedelta(days=1)),
    )).options(selectinload(Post.accounts), selectinload(Post.media_links)))
    if account_id:
        query = query.where(Post.accounts.any(SocialAccount.id == account_id))
    if platform:
        query = query.where(Post.accounts.any(SocialAccount.platform == platform))
    if campaign_id:
        query = query.where(Post.campaign_id == campaign_id)
    if pillar_id:
        query = query.where(Post.pillar_id == pillar_id)
    if state:
        query = query.where(Post.state.in_(PUBLISHED if state == "posted" else (state,)))
    posts = db.scalars(query.order_by(Post.scheduled_at, Post.id).limit(2000)).unique().all()
    items = items_for(db, workspace, list(posts))
    lo, hi = start.isoformat(), end.isoformat()
    items = [i for i in items if i["day"] and lo <= i["day"] < hi]
    return sorted(items, key=lambda i: (i["day"], i["time"] or "99:99", i["id"]))


def unplanned_posts(db: Session, workspace: Workspace, limit: int = 50) -> list[dict]:
    """Drafts without any date: the "to plan" tray of the Planner."""
    posts = db.scalars(select(Post).where(
        Post.workspace_id == workspace.id, Post.state.in_(("draft", "failed")), Post.scheduled_at.is_(None),
        Post.planned_date.is_(None), Post.published_at.is_(None),
    ).options(selectinload(Post.accounts), selectinload(Post.media_links))
        .order_by(Post.updated_at.desc()).limit(limit)).unique().all()
    return items_for(db, workspace, list(posts))


def get_post(db: Session, workspace_id: int, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if not post or post.workspace_id != workspace_id:
        raise NotFound(_("This post no longer exists."))
    return post


def _check_day(day: date, tz: ZoneInfo) -> None:
    if day < local_today(tz):
        raise AppError(_("You cannot plan a post in the past."), code="past_day")


def _check_movable(post: Post) -> None:
    if post.state not in MOVABLE:
        raise AppError(_("Published posts cannot be moved."), code="not_movable")


def move_post(db: Session, workspace: Workspace, post: Post, day: date, hour_minute: str | None,
              user_id: int | None) -> dict:
    """Drag & drop: move a post to another day, keeping its time unless one is given."""
    tz = workspace_tz(workspace)
    _check_movable(post)
    _check_day(day, tz)
    if not hour_minute and post.scheduled_at:
        hour_minute = aware(post.scheduled_at).astimezone(tz).strftime("%H:%M")
    when = local_dt(day, hour_minute, tz) if hour_minute else None
    if when and when < utcnow():
        raise AppError(_("This time has already passed. Choose a later time."), code="past_time")
    if when and post.state == "scheduled":
        social.submit(db, post, user_id, action="schedule", when=when)  # publishing re-plans its job
    elif when and (post.scheduled_at or post.state == "to_approve"):
        post.scheduled_at = when
    post.planned_date = day_to_dt(day)
    db.flush()
    return items_for(db, workspace, [post])[0]


def schedule_post(db: Session, workspace: Workspace, post: Post, day: date, hour_minute: str,
                  user_id: int | None) -> dict:
    """Give a planned post its exact time and schedule it (publishing may send it for approval)."""
    tz = workspace_tz(workspace)
    _check_movable(post)
    _check_day(day, tz)
    when = local_dt(day, hour_minute or "09:00", tz)
    if when < utcnow():
        raise AppError(_("This time has already passed. Choose a later time."), code="past_time")
    if post.state == "to_approve":
        post.scheduled_at = when
    else:
        social.submit(db, post, user_id, action="schedule", when=when)
    post.planned_date = day_to_dt(day)
    db.flush()
    return items_for(db, workspace, [post])[0]


def unplan_post(db: Session, workspace: Workspace, post: Post) -> dict:
    """Remove the planned day of a draft (back to the "to plan" tray)."""
    if post.state not in ("draft", "failed"):
        raise AppError(_("Only drafts can be taken off the calendar."), code="not_draft")
    post.planned_date = None
    db.flush()
    return items_for(db, workspace, [post])[0]


# ---------------------------------------------------------------------------------------------- evergreen
def next_recycle_at(post: Post) -> datetime | None:
    base = aware(post.last_recycled_at or post.published_at)
    if not post.evergreen or not base:
        return None
    nxt = base + timedelta(days=max(post.recycle_interval_days or 1, 1))
    until = as_day(post.recycle_until, UTC)
    if until and nxt.astimezone(UTC).date() > until:
        return None
    return nxt


def open_copies(db: Session, post_ids: list[int]) -> set[int]:
    """Evergreen posts that already have a repost waiting (draft, approval or scheduled)."""
    if not post_ids:
        return set()
    return set(db.scalars(select(Post.recycled_from_id).where(Post.recycled_from_id.in_(post_ids),
                                                              Post.state.in_(OPEN_COPY))))


def recycle_due(post: Post, now: datetime, waiting: set[int], tz: ZoneInfo = ZoneInfo("UTC")) -> bool:
    """``tz`` is the workspace time zone: "repost until" ends with that day there, not with the UTC day."""
    if not post.evergreen or post.state not in PUBLISHED:
        return False
    until = as_day(post.recycle_until, tz)
    if until and aware(now).astimezone(tz).date() > until:
        return False
    nxt = next_recycle_at(post)
    return bool(nxt and nxt <= now and post.id not in waiting)


REWRITE_SYSTEM = ("You rewrite social media posts so that a repost does not look like a copy. Keep the meaning, "
                  "the facts, the offer, links, @mentions and the language of the post, keep hashtags and keep "
                  "about the same length. Answer with the new post text only, no quotes and no explanations.")


def rewrite_text(db: Session, workspace_id: int, text: str | None, user_id: int | None = None) -> str | None:
    if not (text or "").strip():
        return text
    from app.modules.ai import service as ai
    answer = ai.generate_text(db, workspace_id, REWRITE_SYSTEM, "Rewrite this post:\n\n%s" % text,
                              purpose="evergreen rewrite", user_id=user_id)
    cleaned = (answer or "").strip().strip("\"'“”«»„ \n")
    return cleaned or text


def recycle(db: Session, post: Post) -> Post:
    """Create the next repost of an evergreen post and schedule it at the next best slot."""
    content, variants, note = post.content, dict(post.variants or {}), None
    if post.recycle_rewrite:
        try:
            content = rewrite_text(db, post.workspace_id, post.content, post.author_id)
            variants = {k: rewrite_text(db, post.workspace_id, v, post.author_id) for k, v in variants.items() if v}
        except (AppError, ApiError, NotImplementedError) as exc:
            note = getattr(exc, "detail", None) or getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
            content, variants = post.content, dict(post.variants or {})
    feed = [link.media_id for link in post.media_links if link.role != "story"]
    story = [link.media_id for link in post.media_links if link.role == "story"]
    copy = social.create_post(
        db, post.workspace_id, post.author_id, content=content or "", media_ids=feed,
        account_ids=[a.id for a in post.accounts], publish_as=post.publish_as or "feed",
        story_media_ids=story or None, platform_media=post.platform_media, variants=variants or None,
        name=post.name, campaign_id=post.campaign_id, pillar_id=post.pillar_id, source_ref=f"evergreen:{post.id}",
    )
    copy.recycled_from_id = post.id
    copy.evergreen = False
    post.last_recycled_at = utcnow()
    post.recycle_count = (post.recycle_count or 0) + 1
    db.flush()
    try:
        social.submit(db, copy, post.author_id, action="best_time")
    except AppError as exc:
        note = (note + " · " if note else "") + exc.detail
    if post.author_id:
        from app.core.notify import notify
        body = _("The rewrite failed, the original text is used: {reason}", reason=note) if note else ""
        notify(db, post.workspace_id, [post.author_id], kind="planning.evergreen",
               title=_("Evergreen repost planned: {name}", name=post.name or _("Untitled")), body=body,
               link=f"/planner?post={copy.id}")
    return copy


def recycle_due_posts(db: Session, workspace_id: int | None = None, now: datetime | None = None) -> list[int]:
    """Repost every evergreen post that is due. Returns the ids of the copies created."""
    now = now or utcnow()
    query = select(Post).where(Post.evergreen.is_(True), Post.state.in_(PUBLISHED)).options(
        selectinload(Post.accounts), selectinload(Post.media_links))
    if workspace_id:
        query = query.where(Post.workspace_id == workspace_id)
    posts = db.scalars(query).unique().all()
    waiting = open_copies(db, [p.id for p in posts])
    created = []
    zones: dict[int, ZoneInfo] = {}
    for post in posts:
        if post.workspace_id not in zones:
            zones[post.workspace_id] = workspace_tz(db.get(Workspace, post.workspace_id))
        if not recycle_due(post, now, waiting, zones[post.workspace_id]):
            continue
        try:
            with db.begin_nested():
                created.append(recycle(db, post).id)
        except Exception:
            _logger.exception("evergreen repost of post %s failed", post.id)
    return created
