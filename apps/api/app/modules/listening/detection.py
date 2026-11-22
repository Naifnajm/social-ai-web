"""Find what is out of the ordinary in a query's mentions and write it as an event card.

Rules (own brand unless said otherwise; windows in UTC hours/days):
* crisis — negative mentions in the last 6 h ≥ 8, at least 3× the usual 6 h amount, and half or more of all
  mentions in those 6 h. Urgent; one event per topic per day (refreshed while it grows).
* spike — all mentions in the last 6 h ≥ 15 and ≥ 3× the usual amount (not already a crisis).
* opportunity — 5 or more unanswered buying questions in 7 days, grouped by topic (≥ 3 on one topic).
* influencer — a mention in the last 24 h by an author with ≥ 50,000 followers.
* competitor — a competitor's mentions doubled week on week (≥ 20), or the workspace's share of voice fell
  by 5 points or more.
* rising — a word used ≥ 10 times in 7 days that at least doubled compared with the 7 days before.

Each card says what happened, why it matters and what to do, from templates; with an AI provider the card and
a reply/post draft are rewritten in the brand's voice (brand kit). Urgent and high events notify editors.
"""
import logging
from collections import Counter
from datetime import UTC, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.i18n import _, set_locale
from app.core.notify import notify_role
from app.modules.workspaces.models import Role, Workspace
from app.modules.workspaces.settings import get_setting

from . import text as tx
from .models import ListeningQuery, Mention, RadarEvent

_logger = logging.getLogger(__name__)
INFLUENCER_FOLLOWERS = 50_000
NOTIFY = ("urgent", "high")


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def _upsert(db: Session, query: ListeningQuery, key: str, **values) -> tuple[RadarEvent, bool]:
    event = db.scalar(select(RadarEvent).where(RadarEvent.query_id == query.id, RadarEvent.key == key))
    if event:
        if event.state == "open":
            event.metrics = values.get("metrics", event.metrics)
            event.evidence_ids = values.get("evidence_ids", event.evidence_ids)
        return event, False
    event = RadarEvent(workspace_id=query.workspace_id, query_id=query.id, key=key, started_at=utcnow(), **values)
    db.add(event)
    db.flush()
    return event, True


def _evidence(mentions: list[Mention], limit: int = 8) -> list[int]:
    ranked = sorted(mentions, key=lambda m: (m.reach or 0) + (m.engagement or 0) * 5 + (m.author_followers or 0),
                    reverse=True)
    return [m.id for m in ranked[:limit]]


def _hourly(mentions: list[Mention], now, hours: int = 24) -> list[int]:
    series = [0] * hours
    for m in mentions:
        age = int((now - _aware(m.published_at)).total_seconds() // 3600)
        if 0 <= age < hours:
            series[hours - 1 - age] += 1
    return series


def detect(db: Session, query: ListeningQuery, now=None) -> list[RadarEvent]:
    """Run every rule for ``query``. Returns the events created by this run."""
    now = now or utcnow()
    workspace = db.get(Workspace, query.workspace_id)
    set_locale(workspace.locale)
    rows = list(db.scalars(select(Mention).where(Mention.query_id == query.id, Mention.status != "spam",
                                                 Mention.published_at >= now - timedelta(days=14))))
    own = [m for m in rows if m.brand is None]
    created: list[RadarEvent] = []

    def add(key, **values):
        event, new = _upsert(db, query, key, **values)
        if new:
            created.append(event)

    last6 = [m for m in own if _aware(m.published_at) >= now - timedelta(hours=6)]
    before = [m for m in own if now - timedelta(days=7, hours=6) <= _aware(m.published_at) < now - timedelta(hours=6)]
    usual = len(before) / 28  # 28 windows of 6 h in 7 days
    neg6 = [m for m in last6 if m.sentiment == "negative"]
    usual_neg = sum(1 for m in before if m.sentiment == "negative") / 28
    day = now.strftime("%Y-%m-%d")
    week = now.strftime("%G-W%V")
    crisis = False

    if len(neg6) >= 8 and len(neg6) >= 3 * usual_neg + 2 and len(neg6) >= 0.5 * len(last6):
        crisis = True
        topic = Counter(m.topic for m in neg6 if m.topic).most_common(1)
        topic = topic[0][0] if topic else None
        reach = sum(m.reach or 0 for m in neg6)
        add(f"crisis:{topic or '-'}:{day}", kind="crisis", severity="urgent", topic=topic,
            title=_("Negative mentions about {topic} are rising fast", topic=topic or _("your brand")),
            what=_("{count} negative mentions in the last 6 hours (usually about {usual}). Possible reach: {reach}.",
                   count=len(neg6), usual=max(1, round(usual_neg)), reach=f"{reach:,}"),
            why=_("They are about the same subject, so this looks like one problem, not separate cases. "
                  "Left alone, a complaint like this spreads further."),
            suggestion=_("Post one public reply that admits the problem and says when it will be fixed, then "
                         "answer the people affected in private."),
            evidence_ids=_evidence(neg6),
            metrics={"count": len(neg6), "usual": round(usual_neg, 1), "reach": reach,
                     "hourly": _hourly([m for m in own if m.sentiment == "negative"], now)})

    if not crisis and len(last6) >= 15 and len(last6) >= 3 * usual + 5:
        share = len(neg6) / len(last6)
        add(f"spike:{day}", kind="spike", severity="high" if share >= 0.35 else "normal",
            title=_("Mentions of your brand jumped"),
            what=_("{count} mentions in the last 6 hours, about {times}× the usual amount.",
                   count=len(last6), times=round(len(last6) / max(usual, 1), 1)),
            why=_("{neg}% of them are negative.", neg=round(share * 100)) if share >= 0.35 else
            _("Most of them are positive or neutral: a good moment to join the conversation."),
            suggestion=_("Read the top mentions and reply to the most visible ones; consider a post that "
                         "builds on the attention."),
            evidence_ids=_evidence(last6), metrics={"count": len(last6), "usual": round(usual, 1),
                                                    "hourly": _hourly(own, now)})

    week_own = [m for m in own if _aware(m.published_at) >= now - timedelta(days=7)]
    buyers = [m for m in week_own if m.intent in ("purchase", "question") and m.status == "new"]
    if len(buyers) >= 5:
        topic, count = (Counter(m.topic for m in buyers if m.topic).most_common(1) or [(None, 0)])[0]
        if topic and count >= 3:
            group = [m for m in buyers if m.topic == topic]
            add(f"opportunity:{topic}:{week}", kind="opportunity", severity="normal", topic=topic,
                title=_("{count} people asked about {topic} this week", count=count, topic=topic),
                what=_("Questions from people who want to buy, most of them still without an answer."),
                why=_("These are ready buyers; a quick answer or a post about it can turn them into orders."),
                suggestion=_("Answer the open questions and publish a post about {topic}.", topic=topic),
                evidence_ids=_evidence(group), metrics={"count": count, "total_questions": len(buyers)})

    for m in own:
        if (m.author_followers or 0) >= INFLUENCER_FOLLOWERS and _aware(m.published_at) >= now - timedelta(hours=24):
            negative = m.sentiment == "negative"
            add(f"influencer:{m.id}", kind="influencer", severity="high" if negative else "normal",
                title=_("{name} mentioned you", name=m.author_handle or m.author_name or _("A large account")),
                what=_("An account with {followers} followers mentioned your brand.",
                       followers=f"{m.author_followers:,}"),
                why=_("A negative mention from a large account spreads quickly.") if negative else
                _("A positive mention from a large account is worth thanking and sharing."),
                suggestion=_("Reply quickly and offer to solve it in private.") if negative else
                _("Thank them and consider working together."),
                evidence_ids=[m.id], metrics={"followers": m.author_followers, "sentiment": m.sentiment})

    if query.competitors:
        prev_week = [m for m in rows if now - timedelta(days=14) <= _aware(m.published_at) < now - timedelta(days=7)]
        this_week = [m for m in rows if _aware(m.published_at) >= now - timedelta(days=7)]
        sov_now = len(week_own) / len(this_week) * 100 if this_week else 0
        prev_own = sum(1 for m in prev_week if m.brand is None)
        sov_prev = prev_own / len(prev_week) * 100 if prev_week else 0
        for competitor in query.competitors:
            name = competitor.get("name")
            now_c = [m for m in this_week if m.brand == name]
            prev_c = sum(1 for m in prev_week if m.brand == name)
            if len(now_c) >= 20 and len(now_c) >= 2 * max(prev_c, 1):
                topic = (Counter(m.topic for m in now_c if m.topic).most_common(1) or [(None, 0)])[0][0]
                add(f"competitor:{name}:{week}", kind="competitor", severity="normal", brand=name, topic=topic,
                    title=_("{name} is getting much more attention", name=name),
                    what=_("{now} mentions this week against {before} last week{about}.", now=len(now_c),
                           before=prev_c, about=_(", mostly about {topic}", topic=topic) if topic else ""),
                    why=_("Your share of the conversation is {share}% (it was {before}%).",
                          share=round(sov_now), before=round(sov_prev)),
                    suggestion=_("Look at what people say about them and answer with your own strength rather "
                                 "than a matching discount."),
                    evidence_ids=_evidence(now_c), metrics={"now": len(now_c), "before": prev_c,
                                                            "sov": round(sov_now), "sov_before": round(sov_prev)})
        if prev_week and sov_prev - sov_now >= 5:
            add(f"sov:{week}", kind="competitor", severity="normal",
                title=_("Your share of the conversation fell"),
                what=_("You have {share}% of the mentions in your market this week (it was {before}%).",
                       share=round(sov_now), before=round(sov_prev)),
                why=_("Competitors are talked about more; people choose what they hear about."),
                suggestion=_("Plan two or three posts this week on what customers like most about you."),
                evidence_ids=[], metrics={"sov": round(sov_now), "sov_before": round(sov_prev)})

    exclude = {tx.normalize(k).lstrip("#@") for k in tx.search_terms(query)}
    recent = Counter(w for m in week_own for w in set(tx.words(m.text, exclude)))
    older = Counter(w for m in own if now - timedelta(days=14) <= _aware(m.published_at) < now - timedelta(days=7)
                    for w in set(tx.words(m.text, exclude)))
    rising = [(w, c) for w, c in recent.most_common(200) if c >= 10 and c >= 2 * max(older.get(w, 0), 1)]
    if rising:
        word, count = rising[0]
        forms = tx.display_forms([m.text for m in week_own], exclude)
        label = forms.get(word, word)
        add(f"rising:{word}:{week}", kind="rising", severity="info", topic=label,
            title=_("“{word}” is suddenly used much more", word=label),
            what=_("Used {count} times this week (last week: {before}).", count=count, before=older.get(word, 0)),
            why=_("A new word in what people say often means a new topic, product or problem."),
            suggestion=_("Read the mentions with this word to see what is behind it."),
            evidence_ids=_evidence([m for m in week_own if word in tx.words(m.text, exclude)]),
            metrics={"count": count, "before": older.get(word, 0)})

    if any(e.kind in ("crisis", "spike") for e in created):
        from .analysis import boost
        boost(db, workspace.id)  # read the next runs more carefully (larger AI budget for 6 hours)
    for event in created:
        if event.severity != "info":
            write_card(db, workspace, event)
        if event.severity in NOTIFY:
            notify_role(db, workspace.id, Role.editor, kind="radar.event", title=event.title,
                        body=(event.what or "")[:180], link=f"/radar/events/{event.id}")
        if event.severity == "urgent" and get_setting(db, workspace.id, "listening.email_alerts", False):
            _email(db, workspace, event)
    db.flush()
    return created


def _email(db: Session, workspace: Workspace, event: RadarEvent) -> None:
    """Urgent events by e-mail to the workspace's admins (opt-in: ``listening.email_alerts``)."""
    from html import escape

    from app.core.config import settings
    from app.core.mail import send_mail
    from app.modules.auth.models import User
    from app.modules.workspaces.models import ROLE_RANK, Membership
    members = db.scalars(select(Membership).where(Membership.workspace_id == workspace.id)).all()
    ids = [m.user_id for m in members if ROLE_RANK[m.role] >= ROLE_RANK[Role.admin]]
    emails = [u.email for u in db.scalars(select(User).where(User.id.in_(ids or [0]))) if u.email]
    if not emails:
        return
    link = f"{settings.web_url.rstrip('/')}/radar/events/{event.id}"
    try:
        send_mail(emails, _("Radar alert: {title}", title=event.title),
                  f"<p><strong>{escape(event.title)}</strong></p><p>{escape(event.what or '')}</p>"
                  f"<p>{escape(event.suggestion or '')}</p><p><a href=\"{escape(link)}\">{escape(link)}</a></p>",
                  text=f"{event.title}\n{event.what}\n{link}")
    except Exception:  # mail problems never stop detection
        _logger.exception("radar alert e-mail failed for workspace %s", workspace.id)


CARD_SYSTEM = """You write short alert cards for a company's social media team, in {language}.
Brand: {brand}. {voice}
Rewrite the card below in plain, specific words, keeping every number. Then write "draft": {draft_kind}
Answer with ONLY one JSON object: {{"title": "…", "what": "…", "why": "…", "suggestion": "…", "draft": "…"}}.
Never invent facts, prices, discounts, dates or compensation that are not in the card or the mentions."""

DRAFT_KINDS = {
    "crisis": "a public reply that apologizes, names the problem and says the team is fixing it (no promise of "
              "a time unless it is given), and invites people to send their order number in private.",
    "spike": "a short public post or reply that joins the conversation.",
    "opportunity": "a short social media post that answers the question people keep asking.",
    "influencer": "a short public reply to this person.",
    "competitor": "a short post that highlights what customers praise about the brand.",
}


def write_card(db: Session, workspace: Workspace, event: RadarEvent) -> bool:
    """Rewrite ``event`` with the AI in the brand's voice and add a draft. False when no AI was used."""
    from app.core.i18n import LANGUAGE_NAMES
    from app.modules.ai import service as ai
    from app.modules.brand import service as brand

    if not get_setting(db, workspace.id, "listening.ai_cards", True) or not ai.has_provider(db, workspace.id):
        return False
    kit = brand.default_kit(db, workspace.id)
    voice = " ".join(filter(None, [f"Tone: {kit.tone}." if kit and kit.tone else "",
                                   f"Rules: {kit.guidelines}." if kit and kit.guidelines else "",
                                   f"Never use: {kit.banned_words}." if kit and kit.banned_words else ""]))
    quotes = db.scalars(select(Mention).where(Mention.id.in_(event.evidence_ids or [0]))).all()
    card = (f"Title: {event.title}\nWhat happened: {event.what}\nWhy it matters: {event.why}\n"
            f"Suggestion: {event.suggestion}\nMentions:\n" +
            "\n".join(f"- {(m.text or '')[:280]}" for m in quotes[:6]))
    try:
        data = ai.generate_json(db, workspace.id, CARD_SYSTEM.format(
            language=LANGUAGE_NAMES.get(workspace.locale, "Arabic"), brand=workspace.name, voice=voice,
            draft_kind=DRAFT_KINDS.get(event.kind, "an empty string.")), card, purpose="Radar: event card",
            max_tokens=900)
    except Exception as exc:
        _logger.info("radar card for event %s kept as template: %s", event.id, exc)
        return False
    for field in ("title", "what", "why", "suggestion"):
        value = str(data.get(field) or "").strip()
        if value:
            setattr(event, field, value[:300] if field == "title" else value)
    event.draft = str(data.get("draft") or "").strip() or None
    event.ai_written = True
    return True
