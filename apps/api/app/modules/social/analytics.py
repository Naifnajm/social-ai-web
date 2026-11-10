"""Performance dashboard: KPIs with deltas, per-network breakdown, trends, best posting times, content insights,
top posts, tips, AI strategy report, and the metrics sync from the networks."""
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.http import ApiError
from app.core.i18n import _, get_locale
from app.modules.workspaces.models import Workspace

from . import hooks
from .accounts import USABLE_STATES, aware, mark_failed, sync_audience
from .models import PUBLISH_PLATFORMS, AccountStat, Post, PostTarget, SocialAccount
from .platforms import PLATFORM_LABELS, get_publisher

_logger = logging.getLogger(__name__)

# General industry guidance, used until there is enough own data (weekday 0 = Monday, local time).
BENCHMARK_SLOTS = {
    "facebook": [(1, 9), (2, 10), (3, 12), (4, 9), (2, 13)],
    "instagram": [(0, 11), (1, 12), (2, 19), (3, 11), (4, 20)],
    "linkedin": [(1, 8), (2, 9), (3, 10), (2, 12), (1, 17)],
    "x": [(1, 9), (2, 9), (3, 9), (2, 12), (4, 8)],
    "tiktok": [(1, 19), (3, 19), (4, 20), (5, 11), (6, 20)],
    "threads": [(1, 8), (2, 9), (3, 19), (0, 12), (4, 18)],
    "telegram": [(0, 9), (2, 9), (4, 19), (1, 20), (3, 9)],
}
# Healthy posting rhythm per week (min, max).
RHYTHM = {"facebook": (3, 5), "instagram": (4, 7), "linkedin": (2, 5), "x": (7, 21),
          "tiktok": (3, 7), "threads": (5, 14), "telegram": (3, 7)}
MIN_OWN_DATA = 8
METRICS = ("impressions", "reach", "likes", "comments", "shares", "saves", "clicks", "video_views", "engagements")
RAW_METRICS = ("impressions", "reach", "likes", "comments", "shares", "saves", "clicks", "video_views")


# ------------------------------------------------------------------ helpers
def workspace_tz(db: Session, workspace_id: int) -> ZoneInfo:
    workspace = db.get(Workspace, workspace_id)
    try:
        return ZoneInfo((workspace.timezone if workspace else None) or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def day_name(weekday: int) -> str:
    return [_("Monday"), _("Tuesday"), _("Wednesday"), _("Thursday"), _("Friday"), _("Saturday"),
            _("Sunday")][weekday]


def apply_metrics(target: PostTarget, values: dict) -> None:
    for key in RAW_METRICS:
        if key in values:
            setattr(target, key, int(values[key] or 0))
    target.engagements = target.likes + target.comments + target.shares + target.saves + target.clicks
    base = target.impressions or target.reach
    target.engagement_rate = round(100.0 * target.engagements / base, 2) if base else 0.0
    target.metrics_updated_at = utcnow()


def _targets(db, workspace_id, start, end, platform=None, account_ids=None) -> list[PostTarget]:
    query = select(PostTarget).where(PostTarget.workspace_id == workspace_id, PostTarget.state == "posted",
                                     PostTarget.published_at >= start, PostTarget.published_at < end)
    if platform:
        query = query.where(PostTarget.platform == platform)
    if account_ids:
        query = query.where(PostTarget.account_id.in_(account_ids))
    return list(db.scalars(query))


def _sum(targets) -> dict:
    totals = {m: sum(getattr(t, m) or 0 for t in targets) for m in METRICS}
    totals["posts"] = len({t.post_id for t in targets})
    base = totals["impressions"] or totals["reach"]
    totals["engagement_rate"] = round(100.0 * totals["engagements"] / base, 2) if base else 0.0
    return totals


def delta(current, previous):
    if not previous:
        return None
    return round(100.0 * (current - previous) / previous, 1)


def _accounts(db, workspace_id, platform=None, account_ids=None) -> list[SocialAccount]:
    query = select(SocialAccount).where(SocialAccount.workspace_id == workspace_id,
                                        SocialAccount.platform.in_(PUBLISH_PLATFORMS),
                                        SocialAccount.active.is_(True)).order_by(SocialAccount.id)
    if platform:
        query = query.where(SocialAccount.platform == platform)
    if account_ids:
        query = query.where(SocialAccount.id.in_(account_ids))
    return list(db.scalars(query))


def _followers_at(db, accounts, day) -> int:
    total = 0
    for account in accounts:
        followers = db.scalar(select(AccountStat.followers).where(AccountStat.account_id == account.id,
                                                                  AccountStat.day <= day)
                              .order_by(AccountStat.day.desc()).limit(1))
        total += followers or 0
    return total


# ------------------------------------------------------------------ dashboard
def dashboard(db: Session, workspace_id: int, days: int = 30, platform: str | None = None,
              account_id: int | None = None) -> dict:
    days = max(1, min(int(days or 30), 365))
    end = utcnow()
    return dashboard_data(db, workspace_id, end - timedelta(days=days), end, platform,
                          [account_id] if account_id else None)


def dashboard_data(db: Session, workspace_id: int, start: datetime, end: datetime, platform: str | None = None,
                   account_ids: list[int] | None = None) -> dict:
    """Dashboard numbers for any period (``start`` included, ``end`` excluded, aware UTC)."""
    tz = workspace_tz(db, workspace_id)
    days = max(1, round((end - start).total_seconds() / 86400))
    prev_start = start - (end - start)
    targets = _targets(db, workspace_id, start, end, platform, account_ids)
    prev_targets = _targets(db, workspace_id, prev_start, start, platform, account_ids)
    accounts = _accounts(db, workspace_id, platform, account_ids)

    kpis = _sum(targets)
    prev = _sum(prev_targets)
    followers_now = sum(a.followers or 0 for a in accounts)
    followers_then = _followers_at(db, accounts, start) or followers_now
    kpis.update(followers=followers_now, followers_growth=followers_now - followers_then)
    deltas = {key: delta(kpis[key], prev[key]) for key in
              ("posts", "impressions", "engagements", "engagement_rate", "video_views")}
    heatmap, best_slots, best_source = best_times(db, workspace_id, platform, account_ids)
    synced = [aware(t.metrics_updated_at) for t in targets if t.metrics_updated_at]
    data = {
        "period": {"days": days, "start": start, "end": end},
        "platform": platform,
        "timezone": str(tz),
        "has_metrics": bool(synced),
        "kpis": kpis,
        "deltas": deltas,
        "breakdown": _breakdown(db, workspace_id, targets, days) if not platform else [],
        "series": _series(targets, start, days, tz),
        "followers_series": _followers_series(db, accounts, start, days),
        "heatmap": heatmap,
        "best_slots": best_slots,
        "best_source": best_source,
        "content": _content(targets),
        "top_posts": _top_posts(db, targets),
        "accounts": [{"id": a.id, "name": a.name, "platform": a.platform, "followers": a.followers or 0,
                      "state": a.state, "avatar_url": a.avatar_url or ""} for a in accounts],
        "tips": [],
        "last_sync": max(synced) if synced else None,
        "extra": {},
    }
    data["tips"] = _tips(db, workspace_id, targets, prev, kpis, accounts, platform, days, best_slots, best_source)
    for extender in getattr(hooks, "DASHBOARD_EXTENDERS", []):
        try:
            extender(db, workspace_id, data, start, end, prev_start, platform, account_ids)
        except Exception:
            _logger.exception("dashboard extender %r failed", extender)
    return data


def _breakdown(db, workspace_id, targets, days):
    rows = []
    accounts = _accounts(db, workspace_id)
    for key in PUBLISH_PLATFORMS:
        platform_targets = [t for t in targets if t.platform == key]
        platform_accounts = [a for a in accounts if a.platform == key]
        if not platform_targets and not platform_accounts:
            continue
        totals = _sum(platform_targets)
        rows.append(dict(totals, platform=key, label=PLATFORM_LABELS[key],
                         followers=sum(a.followers or 0 for a in platform_accounts),
                         per_week=round(len(platform_targets) * 7.0 / days, 1),
                         rhythm=list(RHYTHM.get(key, (3, 7)))))
    return sorted(rows, key=lambda r: -r["engagements"])


def _series(targets, start, days, tz):
    buckets = defaultdict(lambda: {"posts": 0, "impressions": 0, "engagements": 0})
    for target in targets:
        day = aware(target.published_at).astimezone(tz).date().isoformat()
        buckets[day]["posts"] += 1
        buckets[day]["impressions"] += target.impressions or 0
        buckets[day]["engagements"] += target.engagements or 0
    first = start.astimezone(tz).date()
    return [dict(buckets[(first + timedelta(days=i)).isoformat()], date=(first + timedelta(days=i)).isoformat())
            for i in range(days + 1)]


def _followers_series(db, accounts, start, days):
    if not accounts:
        return []
    stats = db.scalars(select(AccountStat).where(AccountStat.account_id.in_([a.id for a in accounts]),
                                                 AccountStat.day >= start - timedelta(days=1))
                       .order_by(AccountStat.day)).all()
    per_day = defaultdict(dict)
    for stat in stats:
        per_day[aware(stat.day).date().isoformat()][stat.account_id] = stat.followers
    out, last = [], {}
    for i in range(days + 1):
        day = (start.date() + timedelta(days=i)).isoformat()
        last.update(per_day.get(day, {}))
        if last:
            out.append({"date": day, "followers": sum(last.values())})
    return out


def best_times(db: Session, workspace_id: int, platform: str | None = None, account_ids: list[int] | None = None):
    """7×24 grid of average engagement rate of the last 180 days (local time), or general benchmarks."""
    tz = workspace_tz(db, workspace_id)
    end = utcnow()
    targets = [t for t in _targets(db, workspace_id, end - timedelta(days=180), end, platform, account_ids)
               if t.metrics_updated_at]
    grid = [[{"score": 0.0, "count": 0} for _h in range(24)] for _d in range(7)]
    if len(targets) >= MIN_OWN_DATA:
        sums = defaultdict(list)
        for target in targets:
            local = aware(target.published_at).astimezone(tz)
            sums[(local.weekday(), local.hour)].append(target.engagement_rate or float(target.engagements or 0))
        for (day, hour), values in sums.items():
            grid[day][hour] = {"score": round(sum(values) / len(values), 2), "count": len(values)}
        ranked = sorted(((cell["score"], d, h) for d, row in enumerate(grid) for h, cell in enumerate(row)
                         if cell["count"]), reverse=True)
        return grid, [{"weekday": d, "hour": h, "score": s} for s, d, h in ranked[:5]], "own"
    keys = [platform] if platform else list(BENCHMARK_SLOTS)
    weight = defaultdict(float)
    for key in keys:
        for rank, (day, hour) in enumerate(BENCHMARK_SLOTS.get(key, [])):
            weight[(day, hour)] += 5 - rank
            for near in (hour - 1, hour + 1):  # soften around the peak
                if 0 <= near < 24:
                    weight[(day, near)] += (5 - rank) * 0.4
    top = max(weight.values()) if weight else 1
    for (day, hour), value in weight.items():
        grid[day][hour] = {"score": round(100 * value / top, 1), "count": 0}
    ranked = sorted(((v, d, h) for (d, h), v in weight.items()), reverse=True)
    return grid, [{"weekday": d, "hour": h, "score": round(100 * v / top, 1)} for v, d, h in ranked[:5]], "benchmark"


def _content(targets):
    def group(key_fn, labels):
        rows = []
        for key, label in labels:
            subset = [t for t in targets if key_fn(t) == key]
            if subset:
                totals = _sum(subset)
                rows.append({"key": key, "label": label, "count": len(subset),
                             "engagement_rate": totals["engagement_rate"],
                             "avg_engagements": round(totals["engagements"] / len(subset), 1)})
        return rows

    media_labels = [("text", _("Text only")), ("image", _("Single image")), ("carousel", _("Carousel")),
                    ("video", _("Video")), ("audio", _("Audio")), ("story", _("Story"))]
    length_labels = [("short", _("Short (< 100)")), ("medium", _("Medium (100–300)")), ("long", _("Long (> 300)"))]
    tag_labels = [("0", _("No hashtags")), ("1-3", _("1–3 hashtags")), ("4+", _("4+ hashtags"))]
    return {
        "media": group(lambda t: t.media_type or "text", media_labels),
        "length": group(lambda t: "short" if t.text_length < 100 else "medium" if t.text_length <= 300 else "long",
                        length_labels),
        "hashtags": group(lambda t: "0" if not t.hashtag_count else "1-3" if t.hashtag_count <= 3 else "4+",
                          tag_labels),
    }


def _top_posts(db, targets, limit=6):
    top = sorted(targets, key=lambda t: (t.engagements or 0, t.impressions or 0), reverse=True)[:limit]
    posts = {p.id: p for p in db.scalars(select(Post).where(Post.id.in_([t.post_id for t in top])))} if top else {}
    rows = []
    for target in top:
        post = posts.get(target.post_id)
        image = next((link.media_id for link in (post.media_links if post else []) if link.role != "story"), None)
        rows.append({
            "id": target.post_id, "target_id": target.id, "name": (post.name if post else "") or _("Untitled"),
            "platform": target.platform, "account": target.account.name if target.account else "",
            "url": target.external_url or "", "date": target.published_at, "media_id": image,
            "impressions": target.impressions, "engagements": target.engagements,
            "engagement_rate": target.engagement_rate, "likes": target.likes, "comments": target.comments,
            "shares": target.shares, "media_type": target.media_type or "text",
        })
    return rows


# ------------------------------------------------------------------ tips
def _has_brand_profile(db, workspace_id) -> bool:
    try:
        from app.modules.brand.models import BrandKit
    except Exception:  # pragma: no cover
        return True
    kits = db.scalars(select(BrandKit).where(BrandKit.workspace_id == workspace_id, BrandKit.active.is_(True))).all()
    return any((k.tone or "").strip() or (k.guidelines or "").strip() for k in kits)


def _tips(db, workspace_id, targets, prev, kpis, accounts, platform, days, best_slots, best_source):
    tips = []

    def tip(level, icon, title, text, action=None):
        tips.append({"level": level, "icon": icon, "title": title, "text": text, "action": action})

    broken = [a for a in accounts if a.state in ("expired", "error")]
    if broken:
        tip("danger", "link_off", _("Reconnect your accounts"),
            _("{names} cannot publish right now. Reconnect them to avoid failed posts.",
              names=", ".join(a.name for a in broken)), "accounts")
    soon = utcnow() + timedelta(days=7)
    expiring = [a for a in accounts if a.token_expires_at and aware(a.token_expires_at) <= soon and not a.refresh_token
                and a.state == "connected"]
    if expiring:
        tip("warning", "key", _("Access expiring soon"),
            _("The access of {names} ends within 7 days and cannot renew itself.",
              names=", ".join(a.name for a in expiring)), "accounts")
    failed = db.scalar(select(func.count(Post.id)).where(Post.workspace_id == workspace_id,
                                                         Post.state.in_(("failed", "partial"))))
    if failed:
        tip("danger", "error", _("Posts need attention ({count})", count=failed),
            _("Open them and press “Retry failed” — only the networks that failed are sent again."), "failed")
    if not targets:
        tip("info", "rocket_launch", _("Start publishing"),
            _("No published posts in this period yet. Plan 3 posts this week in the Studio."), "studio")
        return tips

    now = utcnow()
    keys = [platform] if platform else sorted({a.platform for a in accounts})
    for key in keys:
        low, high = RHYTHM.get(key, (3, 7))
        platform_targets = [t for t in targets if t.platform == key]
        per_week = len(platform_targets) * 7.0 / days
        label = PLATFORM_LABELS.get(key, key)
        last = max((aware(t.published_at) for t in platform_targets), default=None)
        if last and (now - last).days >= max(3, 14 // max(low, 1)):
            tip("warning", "schedule", _("{network} is quiet", network=label),
                _("Your last {network} post was {days} days ago. Regular posting keeps you visible.",
                  network=label, days=(now - last).days), "studio")
        elif per_week < low:
            tip("info", "event_upcoming", _("Post more on {network}", network=label),
                _("You post {current}× per week; {low}–{high}× works best on {network}.",
                  current=round(per_week, 1), low=low, high=high, network=label), "studio")

    if prev["engagements"]:
        change = delta(kpis["engagements"], prev["engagements"])
        if change is not None and change <= -20:
            tip("warning", "show_chart", _("Engagement is down {pct}%", pct=abs(change)),
                _("Compared with the previous {days} days. Look at your top posts below and repeat what worked.",
                  days=days))
        elif change is not None and change >= 20:
            tip("success", "trophy", _("Engagement is up {pct}%", pct=change),
                _("Great momentum compared with the previous {days} days — keep the same rhythm.", days=days))

    content = _content(targets)
    for block, title in (("media", _("Format")), ("length", _("Length")), ("hashtags", _("Hashtags"))):
        rows = [r for r in content[block] if r["count"] >= 3 and r["engagement_rate"]]
        if len(rows) >= 2:
            best = max(rows, key=lambda r: r["engagement_rate"])
            worst = min(rows, key=lambda r: r["engagement_rate"])
            if worst["engagement_rate"] and best["engagement_rate"] >= worst["engagement_rate"] * 1.3:
                tip("success", "lightbulb", _("{title}: {best} works best", title=title, best=best["label"]),
                    _("{best} posts get {times}× the engagement of {worst} posts. Do more of them.",
                      best=best["label"], worst=worst["label"],
                      times=round(best["engagement_rate"] / worst["engagement_rate"], 1)))
    if "video" not in {r["key"] for r in content["media"]}:
        tip("info", "movie", _("Try short videos"),
            _("Short vertical videos usually reach the most people on Instagram, TikTok and Facebook. "
              "Create one with AI in the Studio."), "studio")

    if best_slots:
        slot = best_slots[0]
        when = f"{day_name(slot['weekday'])} {slot['hour']:02d}:00"
        if best_source == "own":
            tip("success", "schedule", _("Your best time: {when}", when=when),
                _("Your posts published around this time get the highest engagement."), "schedule")
        else:
            tip("info", "schedule", _("Suggested time: {when}", when=when),
                _("Based on general benchmarks until you have {count} posts with statistics.", count=MIN_OWN_DATA),
                "schedule")
    if not _has_brand_profile(db, workspace_id):
        tip("info", "campaign", _("Describe your brand voice"),
            _("The AI writes much better posts when it knows who you are and who you talk to."), "brand")
    if not any(t.metrics_updated_at for t in targets):
        tip("info", "sync_alt", _("Statistics are on their way"),
            _("Numbers are collected every 3 hours. Press “Refresh stats” to get them now."), "refresh")
    order = {"danger": 0, "warning": 1, "success": 2, "info": 3}
    return sorted(tips, key=lambda t: order[t["level"]])


# ------------------------------------------------------------------ best slots (Studio "Best time")
def next_best_slots(db: Session, workspace_id: int, platforms: list[str] | None = None, count: int = 3) -> list[dict]:
    platforms = [p for p in (platforms or []) if p in PUBLISH_PLATFORMS]
    _grid, slots, _source = best_times(db, workspace_id, platforms[0] if len(platforms) == 1 else None)
    tz = workspace_tz(db, workspace_id)
    now_local = datetime.now(tz)
    upcoming = []
    for slot in slots:
        days_ahead = (slot["weekday"] - now_local.weekday()) % 7
        candidate = datetime.combine(now_local.date() + timedelta(days=days_ahead), time(slot["hour"]), tzinfo=tz)
        if candidate <= now_local + timedelta(minutes=30):
            candidate += timedelta(days=7)
        upcoming.append((candidate, slot["score"]))
    upcoming = sorted(set(upcoming))[:max(1, count)]
    return [{
        "at": c.astimezone(timezone.utc),
        "local": c.strftime("%Y-%m-%dT%H:%M"),
        "label": f"{day_name(c.weekday())} {c.hour:02d}:00",
        "score": score,
    } for c, score in upcoming]


# ------------------------------------------------------------------ metrics sync
def sync_metrics(db: Session, workspace_id: int | None = None, days: int = 60, account_ids: list[int] | None = None,
                 platform: str | None = None) -> int:
    """Pull likes, comments, views… of recent posts (one network call batch per account)."""
    query = select(PostTarget).where(PostTarget.state == "posted", PostTarget.external_id.is_not(None),
                                     PostTarget.published_at >= utcnow() - timedelta(days=days))
    if workspace_id:
        query = query.where(PostTarget.workspace_id == workspace_id)
    if account_ids:
        query = query.where(PostTarget.account_id.in_(account_ids))
    if platform:
        query = query.where(PostTarget.platform == platform)
    targets = list(db.scalars(query))
    by_account = defaultdict(list)
    for target in targets:
        if target.media_type != "story":
            by_account[target.account_id].append(target)
    updated = 0
    for account_id, account_targets in by_account.items():
        account = db.get(SocialAccount, account_id)
        if not account or not account.active or account.state not in USABLE_STATES:
            continue
        try:
            metrics = get_publisher(db, account).fetch_metrics(account_targets)
        except ApiError as exc:
            _logger.info("metrics for account %s skipped: %s", account.id, exc.message)
            mark_failed(account, exc)
            continue
        except Exception:
            _logger.exception("metrics for account %s failed", account.id)
            continue
        by_id = {t.id: t for t in account_targets}
        for target_id, values in metrics.items():
            if target_id in by_id:
                apply_metrics(by_id[target_id], values)
                updated += 1
        db.flush()
    return updated


def refresh(db: Session, workspace_id: int, platform: str | None = None) -> dict:
    """Pull fresh numbers now (button on the dashboard)."""
    accounts = _accounts(db, workspace_id, platform)
    updated = sync_metrics(db, workspace_id, account_ids=[a.id for a in accounts] or [-1])
    followers = sync_audience(db, accounts)
    return {"posts": updated, "accounts": followers}


# ------------------------------------------------------------------ AI report
def clean_ai_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```[a-z]*\n?|```$", "", text).strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def ai_report(db: Session, workspace_id: int, days: int = 30, platform: str | None = None,
              user_id: int | None = None) -> dict:
    from app.modules.ai import service as ai

    data = dashboard(db, workspace_id, days, platform)
    summary = {
        "period_days": days, "platform": platform or "all",
        "kpis": data["kpis"], "change_vs_previous_period_pct": data["deltas"],
        "per_platform": [{k: r[k] for k in ("label", "posts", "impressions", "engagements", "engagement_rate",
                                             "followers", "per_week")} for r in data["breakdown"]],
        "content_performance": data["content"],
        "best_slots": [{"day": day_name(s["weekday"]), "hour": s["hour"]} for s in data["best_slots"]],
        "best_slots_source": data["best_source"],
        "top_posts": [{k: p[k] for k in ("name", "platform", "engagements", "engagement_rate", "media_type")}
                      for p in data["top_posts"]],
        "extra_results": data.get("extra") or {},
    }
    language = "Arabic (Modern Standard, Gulf-friendly)" if get_locale() == "ar" else "English"
    system = (
        "You are a senior social media strategist. Analyse the account statistics and give a practical plan. "
        f"Write in {language}. Use short sections with these headings: Summary, What works, What to improve, "
        "Plan for the next 2 weeks (concrete post ideas with network, format and day/time), Quick wins. "
        "Use simple bullet points with '•'. No markdown symbols like ** or #. Be specific, use the numbers. "
        "If data is thin, say so and focus on proven best practices.")
    try:
        from app.modules.brand.models import BrandKit
        kit = db.scalar(select(BrandKit).where(BrandKit.workspace_id == workspace_id, BrandKit.active.is_(True))
                        .order_by(BrandKit.is_default.desc(), BrandKit.id).limit(1))
        if kit:
            system += "\nBrand profile:\n" + kit.llm_profile()
    except Exception:  # pragma: no cover - brand module optional
        pass
    text = ai.generate_text(db, workspace_id, system, json.dumps(summary, ensure_ascii=False, default=str),
                            purpose="performance report", user_id=user_id)
    return {"text": clean_ai_text(text), "generated_at": utcnow()}
