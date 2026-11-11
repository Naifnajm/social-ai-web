"""Performance reports: numbers of a period (from ``post_targets``, link clicks and conversions), rendered with
Jinja2 (black / grey print design, RTL for Arabic), as PDF when WeasyPrint is installed, e-mailed on a schedule."""
import base64
import calendar
import io
import json
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import utcnow
from app.core.errors import AppError
from app.core.i18n import _, get_locale, set_locale
from app.core.mail import send_mail
from app.core.models import Media
from app.core.storage import read_media
from app.modules.links import service as links
from app.modules.planning import service as planning
from app.modules.social.analytics import RHYTHM
from app.modules.social.models import AccountStat, Post, PostMedia, PostTarget, SocialAccount
from app.modules.social.platforms import PLATFORM_LABELS
from app.modules.workspaces.models import Workspace

from .models import ReportSchedule

_logger = logging.getLogger(__name__)
UTC = timezone.utc
TEMPLATES = Path(__file__).resolve().parent / "templates"
MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر",
             "ديسمبر"]
PERIODS = ("last_7", "last_30", "prev_month")


# ---------------------------------------------------------------------------------------------- dates
def next_occurrence(schedule: ReportSchedule, after: datetime, tz: ZoneInfo) -> datetime:
    """First sending moment strictly after ``after`` (aware), returned in UTC."""
    local = planning.aware(after).astimezone(tz)
    hour = time(min(max(schedule.hour or 0, 0), 23))
    if schedule.frequency == "monthly":
        day = min(max(schedule.month_day or 1, 1), 28)
        candidate = datetime.combine(local.date().replace(day=day), hour, tzinfo=tz)
        if candidate <= local:
            year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
            candidate = datetime.combine(date(year, month, day), hour, tzinfo=tz)
    else:
        weekday = min(max(schedule.weekday or 0, 0), 6)
        candidate = datetime.combine(local.date() + timedelta(days=(weekday - local.weekday()) % 7), hour, tzinfo=tz)
        if candidate <= local:
            candidate += timedelta(days=7)
    return candidate.astimezone(UTC)


def period_range(period: str, now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """``(start, end)`` in UTC of the period covered by a report made at ``now``."""
    local_now = planning.aware(now).astimezone(tz)
    midnight = datetime.combine(local_now.date(), time(0), tzinfo=tz)
    if period == "prev_month":
        end = midnight.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
    else:
        end = midnight
        start = end - timedelta(days=7 if period == "last_7" else 30)
    return start.astimezone(UTC), end.astimezone(UTC)


# ---------------------------------------------------------------------------------------------- formatting
def fmt(value, digits: int = 0) -> str:
    value = value or 0
    return f"{value:,.{digits}f}"


def money(value: float, currency: str) -> str:
    return f"{fmt(value)} {currency}"


def fmt_date(day: date, language: str) -> str:
    if language == "ar":
        return f"{day.day} {MONTHS_AR[day.month - 1]} {day.year}"
    return f"{day.day} {calendar.month_abbr[day.month]} {day.year}"


def day_name(weekday: int) -> str:
    return [_("Monday"), _("Tuesday"), _("Wednesday"), _("Thursday"), _("Friday"), _("Saturday"),
            _("Sunday")][weekday]


def delta(current, previous) -> float | None:
    if not previous:
        return None
    return round(100.0 * (current - previous) / previous, 1)


def image_uri(media: Media | None, size: int = 160) -> str | None:
    if not media or not (media.mimetype or "").startswith("image/"):
        return None
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(read_media(media))) as image:
            thumb = ImageOps.fit(image.convert("RGB"), (size, size))
            buffer = io.BytesIO()
            thumb.save(buffer, "JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    except Exception:  # missing file, not an image Pillow can read
        return None


def logo_uri(db: Session, workspace: Workspace) -> str | None:
    if not workspace.logo_media_id:
        return None
    media = db.get(Media, workspace.logo_media_id)
    if not media or media.workspace_id != workspace.id:
        return None
    try:
        return f"data:{media.mimetype};base64," + base64.b64encode(read_media(media)).decode()
    except OSError:
        return None


# ---------------------------------------------------------------------------------------------- numbers
METRICS = ("impressions", "reach", "likes", "comments", "shares", "saves", "clicks", "video_views", "engagements")


def _targets(db: Session, workspace_id: int, start: datetime, end: datetime, account_ids: list[int] | None):
    query = select(PostTarget).where(PostTarget.workspace_id == workspace_id, PostTarget.state == "posted",
                                     PostTarget.published_at >= start, PostTarget.published_at < end)
    if account_ids:
        query = query.where(PostTarget.account_id.in_(account_ids))
    return list(db.scalars(query))


def _sum(targets) -> dict:
    totals = {m: sum(getattr(t, m) or 0 for t in targets) for m in METRICS}
    totals["posts"] = len({t.post_id for t in targets})
    base = totals["impressions"] or totals["reach"]
    totals["engagement_rate"] = round(100.0 * totals["engagements"] / base, 2) if base else 0.0
    return totals


def _followers_at(db: Session, accounts: list[SocialAccount], day: datetime) -> int:
    total = 0
    for account in accounts:
        stat = db.scalar(select(AccountStat).where(AccountStat.account_id == account.id, AccountStat.day <= day)
                         .order_by(AccountStat.day.desc()).limit(1))
        total += stat.followers if stat else 0
    return total


def report_data(db: Session, workspace: Workspace, start: datetime, end: datetime,
                account_ids: list[int] | None = None) -> dict:
    """Raw numbers of a period (``start`` included, ``end`` excluded) compared with the period before."""
    prev_start = start - (end - start)
    accounts = list(db.scalars(select(SocialAccount).where(
        SocialAccount.workspace_id == workspace.id, SocialAccount.platform != "whatsapp")))
    if account_ids:
        accounts = [a for a in accounts if a.id in account_ids]
    platforms = sorted({a.platform for a in accounts}) if account_ids else None
    targets = _targets(db, workspace.id, start, end, account_ids)
    prev_targets = _targets(db, workspace.id, prev_start, start, account_ids)
    kpis, prev = _sum(targets), _sum(prev_targets)
    results = links.results_by(db, workspace.id, "all", start=start, end=end, platforms=platforms).get("all") or {}
    prev_results = links.results_by(db, workspace.id, "all", start=prev_start, end=start,
                                    platforms=platforms).get("all") or {}
    for key in ("clicks", "conversions", "orders", "leads", "revenue"):
        kpis["link_" + key if key == "clicks" else key] = results.get(key, 0)
        prev["link_" + key if key == "clicks" else key] = prev_results.get(key, 0)
    kpis["ctr"] = round(100.0 * kpis["link_clicks"] / kpis["impressions"], 2) if kpis["impressions"] else 0.0
    prev["ctr"] = round(100.0 * prev["link_clicks"] / prev["impressions"], 2) if prev["impressions"] else 0.0
    followers_now = sum(a.followers or 0 for a in accounts)
    followers_then = _followers_at(db, accounts, start) or followers_now
    kpis.update(followers=followers_now, followers_growth=followers_now - followers_then)

    by_platform = defaultdict(list)
    for target in targets:
        by_platform[target.platform].append(target)
    clicks_platform = links.results_by(db, workspace.id, "platform", start=start, end=end, platforms=platforms)
    networks = []
    for platform in sorted(set(by_platform) | {a.platform for a in accounts}):
        totals = _sum(by_platform.get(platform, []))
        extra = clicks_platform.get(platform) or {}
        networks.append(dict(totals, platform=platform, label=PLATFORM_LABELS.get(platform, platform),
                             link_clicks=extra.get("clicks", 0), revenue=extra.get("revenue", 0.0),
                             followers=sum(a.followers or 0 for a in accounts if a.platform == platform)))
    networks.sort(key=lambda r: (-r["engagements"], -r["posts"]))

    top = sorted(targets, key=lambda t: (t.engagements or 0, t.impressions or 0), reverse=True)[:5]
    by_post = links.results_by(db, workspace.id, "post", start=start, end=end, platforms=platforms)
    return {"kpis": kpis, "prev": prev, "networks": networks, "top_targets": top, "by_post": by_post,
            "accounts": accounts, "platforms": platforms, "has_metrics": any(t.metrics_updated_at for t in targets),
            "days": max(1, round((end - start).total_seconds() / 86400))}


def tips(data: dict, best: list[dict]) -> list[dict]:
    out = []
    kpis, prev = data["kpis"], data["prev"]
    if not kpis["posts"]:
        out.append({"level": "info", "title": _("Start publishing"),
                    "text": _("No published posts in this period yet. Plan 3 posts this week in the Planner.")})
        return out
    days = data["days"]
    for row in data["networks"]:
        low, high = RHYTHM.get(row["platform"], (3, 7))
        per_week = row["posts"] * 7.0 / days
        if row["posts"] and per_week < low:
            out.append({"level": "info", "title": _("Post more on {network}", network=row["label"]),
                        "text": _("You post {current}× per week; {low}–{high}× works best on {network}.",
                                  current=round(per_week, 1), low=low, high=high, network=row["label"])})
    change = delta(kpis["engagements"], prev["engagements"])
    if change is not None and change <= -20:
        out.append({"level": "warning", "title": _("Engagement is down {pct}%", pct=abs(change)),
                    "text": _("Look at your top posts and repeat what worked.")})
    elif change is not None and change >= 20:
        out.append({"level": "success", "title": _("Engagement is up {pct}%", pct=change),
                    "text": _("Great momentum — keep the same rhythm.")})
    if kpis["link_clicks"] and not kpis["conversions"]:
        out.append({"level": "info", "title": _("Track your sales"),
                    "text": _("Your links get clicks. Add the conversion snippet to your website to see revenue.")})
    if best:
        out.append({"level": "success", "title": _("Best time: {when}", when=f"{best[0]['day']} {best[0]['hour']}"),
                    "text": _("Plan your most important posts around this time.")})
    return out[:5]


def ai_summary(db: Session, workspace: Workspace, data: dict, best: list[dict], language: str) -> str | None:
    from app.modules.ai import service as ai
    summary = {
        "period_days": data["days"], "kpis": data["kpis"],
        "change_vs_previous_period_pct": {k: delta(data["kpis"][k], data["prev"][k]) for k in
                                          ("posts", "impressions", "engagements", "link_clicks", "revenue")},
        "per_network": [{k: r[k] for k in ("label", "posts", "impressions", "engagements", "engagement_rate",
                                            "link_clicks", "revenue", "followers")} for r in data["networks"]],
        "best_times": best,
    }
    system = ("You are a senior social media strategist. Analyse the statistics and give a short practical plan "
              "for the coming weeks: what works, what to improve, 3 concrete post ideas (network, format, day/time). "
              "Use simple bullet points with '•'. No markdown symbols like ** or #. Maximum 160 words. "
              f"Write in {'Arabic' if language == 'ar' else 'English'}.")
    try:
        text = ai.generate_text(db, workspace.id, system, json.dumps(summary, ensure_ascii=False, default=str),
                                purpose="report summary")
    except Exception as exc:  # no provider, quota… the report still goes out
        _logger.info("AI summary skipped for workspace %s: %s", workspace.id, exc)
        return None
    return (text or "").replace("**", "").replace("#", "").strip() or None


def report_values(db: Session, workspace: Workspace, *, period: str = "last_7", language: str = "ar",
                  account_ids: list[int] | None = None, include_ai: bool = False, title: str | None = None,
                  now: datetime | None = None) -> dict:
    """Everything the report template shows, in ``language``."""
    previous_locale = get_locale()
    set_locale(language)
    try:
        tz = planning.workspace_tz(workspace)
        start, end = period_range(period, now or utcnow(), tz)
        data = report_data(db, workspace, start, end, account_ids)
        kpis, prev = data["kpis"], data["prev"]
        currency = workspace.currency
        tiles = [("posts", _("Posts"), fmt(kpis["posts"])),
                 ("impressions", _("Impressions"), fmt(kpis["impressions"])),
                 ("engagements", _("Engagements"), fmt(kpis["engagements"])),
                 ("engagement_rate", _("Engagement rate"), fmt(kpis["engagement_rate"], 2) + "%"),
                 ("video_views", _("Video views"), fmt(kpis["video_views"])),
                 ("link_clicks", _("Link clicks"), fmt(kpis["link_clicks"])),
                 ("ctr", _("Click-through rate"), fmt(kpis["ctr"], 2) + "%")]
        show_revenue = bool(kpis["conversions"] or prev["conversions"])
        if show_revenue:
            tiles += [("revenue", _("Revenue"), money(kpis["revenue"], currency)),
                      ("conversions", _("Conversions"), fmt(kpis["conversions"]))]
        kpi_tiles = []
        for key, label, value in tiles:
            change = delta(kpis[key], prev[key])
            kpi_tiles.append({"key": key, "label": label, "value": value,
                              "delta": None if change is None else f"{'+' if change >= 0 else ''}{change}%",
                              "up": change is not None and change >= 0})
        growth = kpis["followers_growth"]
        kpi_tiles.append({"key": "followers", "label": _("Followers"), "value": fmt(kpis["followers"]),
                          "delta": f"{'+' if growth >= 0 else ''}{fmt(growth)}" if growth else None, "up": growth >= 0})

        networks = [{"platform": r["platform"], "label": r["label"], "posts": fmt(r["posts"]),
                     "impressions": fmt(r["impressions"]), "engagements": fmt(r["engagements"]),
                     "engagement_rate": fmt(r["engagement_rate"], 2) + "%", "clicks": fmt(r["link_clicks"]),
                     "revenue": money(r["revenue"], currency), "followers": fmt(r["followers"])}
                    for r in data["networks"]]

        post_ids = {t.post_id for t in data["top_targets"]} | set(data["by_post"])
        posts = {p.id: p for p in db.scalars(select(Post).where(Post.id.in_(post_ids),
                                                                Post.workspace_id == workspace.id))} if post_ids else {}
        first_media = {}
        if post_ids:
            for link in db.scalars(select(PostMedia).where(PostMedia.post_id.in_(post_ids))
                                   .order_by(PostMedia.post_id, PostMedia.position)):
                first_media.setdefault(link.post_id, link.media_id)
        medias = {m.id: m for m in db.scalars(select(Media).where(Media.id.in_(set(first_media.values()))))} \
            if first_media else {}
        account_names = {a.id: a.name for a in data["accounts"]}
        top_posts = []
        for target in data["top_targets"]:
            post = posts.get(target.post_id)
            published = planning.aware(target.published_at).astimezone(tz).date()
            top_posts.append({
                "name": (post.name if post else "") or (post.content or "")[:60] if post else "",
                "platform": target.platform, "account": account_names.get(target.account_id, ""),
                "image": image_uri(medias.get(first_media.get(target.post_id))),
                "engagements": fmt(target.engagements), "impressions": fmt(target.impressions),
                "rate": fmt(target.engagement_rate, 2) + "%", "date": fmt_date(published, language),
                "url": target.external_url or "",
            })
        top_results = []
        for post_id, row in sorted(data["by_post"].items(), key=lambda kv: (kv[1]["revenue"], kv[1]["clicks"]),
                                   reverse=True)[:5]:
            post = posts.get(post_id)
            if post and (row["clicks"] or row["revenue"]):
                top_results.append({"name": post.name or (post.content or "")[:60], "clicks": fmt(row["clicks"]),
                                    "conversions": fmt(row["conversions"]), "revenue": money(row["revenue"], currency)})

        best = [{"day": day_name(s["weekday"]), "hour": s["time"]}
                for s in planning.best_slots(db, workspace, data["platforms"], count=3)]
        names = [a.name for a in data["accounts"]] if account_ids else []
        values = {
            "title": title or _("Social media report"),
            "company": workspace.name,
            "logo": logo_uri(db, workspace),
            "period": f"{fmt_date(start.astimezone(tz).date(), language)} – "
                      f"{fmt_date((end - timedelta(seconds=1)).astimezone(tz).date(), language)}",
            "networks_label": ", ".join(names) or _("All networks"),
            "direction": "rtl" if language == "ar" else "ltr",
            "lang": language,
            "kpis": kpi_tiles,
            "networks": networks,
            "show_revenue": show_revenue,
            "top_posts": top_posts,
            "top_results": top_results,
            "best": best,
            "tips": tips(data, best),
            "ai_text": ai_summary(db, workspace, data, best, language) if include_ai else None,
            "generated": fmt_date(datetime.now(tz).date(), language),
            "has_metrics": data["has_metrics"],
            "app_name": settings.app_name,
            "web_url": settings.web_url.rstrip("/"),
        }
        return values
    finally:
        set_locale(previous_locale)


# ---------------------------------------------------------------------------------------------- rendering
@lru_cache
def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.globals["_"] = _
    return env


def render(template: str, values: dict, **extra) -> str:
    previous_locale = get_locale()
    set_locale(values.get("lang", "ar"))
    try:
        return _env().get_template(template).render(r=values, **extra)
    finally:
        set_locale(previous_locale)


@lru_cache
def pdf_available() -> bool:
    try:
        import weasyprint
        return weasyprint.HTML(string="<p>ok</p>").write_pdf()[:4] == b"%PDF"
    except Exception:  # not installed, or system libraries (Pango) missing
        return False


def render_pdf(html: str) -> bytes | None:
    if not pdf_available():
        return None
    try:
        import weasyprint
        return weasyprint.HTML(string=html, base_url=str(TEMPLATES)).write_pdf()
    except Exception:
        _logger.exception("PDF rendering failed, the HTML report is used")
        return None


def schedule_values(db: Session, schedule: ReportSchedule, now: datetime | None = None) -> dict:
    workspace = db.get(Workspace, schedule.workspace_id)
    return report_values(db, workspace, period=schedule.period, language=schedule.language,
                         account_ids=list(schedule.account_ids or []) or None, include_ai=schedule.include_ai,
                         title=schedule.name, now=now)


def build(db: Session, schedule: ReportSchedule, now: datetime | None = None) -> tuple[dict, str, bytes | None]:
    values = schedule_values(db, schedule, now)
    html = render("report.html", values)
    return values, html, render_pdf(html)


def send(db: Session, schedule: ReportSchedule, now: datetime | None = None) -> dict:
    """E-mail the report now. Returns ``{"recipients", "format"}``."""
    recipients = [r for r in (schedule.recipients or []) if r]
    if not recipients:
        raise AppError(_("Add at least one recipient with an e-mail address."), code="no_recipients")
    values, html, pdf = build(db, schedule, now)
    safe = "".join(c if c.isalnum() or c in " -_" else "-" for c in values["title"]).strip() or "report"
    attachments = [(f"{safe}.pdf", pdf, "application/pdf")] if pdf else []
    attachments.append((f"{safe}.html", html.encode(), "text/html"))
    body = render("email.html", values, is_pdf=bool(pdf))
    previous_locale = get_locale()
    set_locale(schedule.language)
    try:
        subject = f"{values['title']} · {values['period']}"
        text = _("Your social media report is attached.")
    finally:
        set_locale(previous_locale)
    send_mail(recipients, subject, body, text=text, attachments=attachments)
    workspace = db.get(Workspace, schedule.workspace_id)
    moment = now or utcnow()
    schedule.last_sent_at = moment
    schedule.last_error = None
    schedule.send_count = (schedule.send_count or 0) + 1
    schedule.next_send_at = next_occurrence(schedule, moment, planning.workspace_tz(workspace)) \
        if schedule.active else None
    db.flush()
    return {"recipients": len(recipients), "format": "pdf" if pdf else "html"}


def send_due(db: Session, now: datetime | None = None, limit: int = 20) -> int:
    now = now or utcnow()
    due = db.scalars(select(ReportSchedule).where(ReportSchedule.active.is_(True),
                                                  ReportSchedule.next_send_at.is_not(None),
                                                  ReportSchedule.next_send_at <= now)
                     .order_by(ReportSchedule.next_send_at).limit(limit)).all()
    sent = 0
    for schedule in due:
        try:
            with db.begin_nested():
                send(db, schedule, now)
            sent += 1
        except Exception as exc:
            _logger.exception("scheduled report %s failed", schedule.id)
            workspace = db.get(Workspace, schedule.workspace_id)
            schedule.last_error = (getattr(exc, "detail", None) or str(exc))[:1000]
            schedule.next_send_at = next_occurrence(schedule, now, planning.workspace_tz(workspace))
            db.flush()
    return sent


def count_schedules(db: Session, workspace_id: int) -> int:
    return db.scalar(select(func.count()).select_from(ReportSchedule).where(
        ReportSchedule.workspace_id == workspace_id)) or 0
