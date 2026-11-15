"""Radar service: collection runs, the numbers behind every chart, and the actions that hand a mention or an
event to the rest of the platform (inbox, studio, planner, approvals).

    from app.modules.listening import service as radar
    radar.collect(db, query)                      # one run of every source of the query
    radar.overview(db, workspace, query, days=30) # KPIs, daily volume, sentiment, sources, words, open events
    radar.mention_to_inbox(db, mention)           # the mention becomes an inbox conversation
    radar.act(db, event, user_id, "studio")       # a draft post with the event's draft text
"""
import logging
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import AppError, NotFound
from app.core.http import ApiError
from app.core.i18n import _
from app.modules.billing import limits
from app.modules.planning.service import workspace_tz
from app.modules.social.models import SocialAccount
from app.modules.workspaces.models import Workspace

from . import analysis, collectors, detection
from . import text as tx
from .models import FREE_SOURCES, ListeningQuery, Mention, RadarEvent

_logger = logging.getLogger(__name__)
INBOX_PLATFORMS = ("instagram", "facebook")
INTENT_TO_INBOX = {"complaint": "complaint", "purchase": "lead", "question": "question", "praise": "praise"}


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------------------------- queries
def allowed_sources(db: Session, workspace_id: int) -> list[str]:
    sources = list(FREE_SOURCES)
    if limits.feature(db, workspace_id, "listening_x"):
        sources.append("x")
    return sources


def get_query(db: Session, workspace_id: int, query_id: int | None) -> ListeningQuery:
    """The query asked for, else the workspace's first active one."""
    stmt = select(ListeningQuery).where(ListeningQuery.workspace_id == workspace_id)
    query = db.scalar(stmt.where(ListeningQuery.id == query_id)) if query_id else \
        db.scalar(stmt.order_by(ListeningQuery.active.desc(), ListeningQuery.id))
    if not query:
        raise NotFound(_("Set up what to listen for first."))
    return query


# --------------------------------------------------------------------------------------------- collection
def _keep(query: ListeningQuery, item: dict) -> tuple[bool, str | None]:
    text = item.get("text") or ""
    if item.get("owned"):
        return bool(text.strip()), None
    every = list(query.keywords or []) + [k for c in query.competitors or []
                                          for k in (c.get("keywords") or [c.get("name") or ""])]
    if not tx.matches(text, every, query.required, query.excluded):
        return False, None
    matched, brand = tx.brand_of(text, query.keywords, query.competitors)
    if not matched:
        return False, None
    lang = item.get("lang") or tx.detect_lang(text)
    if query.languages and lang and lang not in query.languages:
        return False, None
    if query.countries and item.get("country") and item["country"].upper() not in [c.upper() for c in query.countries]:
        return False, None
    return True, brand


def store(db: Session, query: ListeningQuery, items: list[dict]) -> list[Mention]:
    """Store the items that match the query and are not stored yet. Returns the new mentions."""
    created = []
    for item in items:
        keep, brand = _keep(query, item)
        external_id = str(item.get("external_id") or "")[:255]
        if not keep or not external_id:
            continue
        exists = db.scalar(select(Mention.id).where(Mention.query_id == query.id, Mention.source == item["source"],
                                                    Mention.external_id == external_id))
        if exists:
            continue
        text = item.get("text") or ""
        mention = Mention(
            workspace_id=query.workspace_id, query_id=query.id, source=item["source"],
            platform=item.get("platform"), external_id=external_id, url=(item.get("url") or None),
            author_name=(item.get("author_name") or None) and str(item["author_name"])[:200],
            author_handle=(item.get("author_handle") or None) and str(item["author_handle"])[:200],
            author_followers=int(item.get("author_followers") or 0), text=text[:5000],
            lang=item.get("lang") or tx.detect_lang(text), country=(item.get("country") or None),
            published_at=_aware(item.get("published_at")) or utcnow(), brand=brand,
            reach=int(item.get("reach") or 0), engagement=int(item.get("engagement") or 0),
            account_id=item.get("account_id"), conversation_id=item.get("conversation_id"), extra=item.get("extra"),
            status="converted" if item.get("conversation_id") else "new")
        try:
            with db.begin_nested():
                db.add(mention)
                db.flush()
        except IntegrityError:
            continue
        created.append(mention)
    return created


def collect(db: Session, query: ListeningQuery, *, detect: bool = True) -> dict:
    """One collection run: every source of the query, then classification and detection."""
    allowed = allowed_sources(db, query.workspace_id)
    cursors = dict(query.cursors or {})
    found, errors = 0, {}
    for source in query.sources or []:
        if source not in allowed or source not in collectors.COLLECTORS:
            continue
        cursor = dict(cursors.get(source) or {})
        try:
            items = collectors.COLLECTORS[source](db, query, cursor)
        except ApiError as exc:
            errors[source] = str(exc)[:300]
            continue
        except Exception as exc:  # one broken source never stops the others
            _logger.exception("radar source %s failed for query %s", source, query.id)
            errors[source] = str(exc)[:300]
            continue
        cursors[source] = cursor
        found += len(store(db, query, items))
    query.cursors = cursors
    query.last_collected_at = utcnow()
    query.last_error = "; ".join(f"{k}: {v}" for k, v in errors.items()) or None
    db.flush()
    analysis.classify_pending(db, query.workspace_id)
    events = detection.detect(db, query) if detect else []
    return {"new": found, "errors": errors, "events": len(events)}


def x_usage(query: ListeningQuery) -> dict:
    cursor = (query.cursors or {}).get("x") or {}
    reads = collectors.x_reads_this_month(cursor)
    return {"reads": reads, "cap": query.x_monthly_cap, "cost_usd": round(reads * collectors.X_PRICE_PER_POST, 2),
            "cap_cost_usd": round((query.x_monthly_cap or 0) * collectors.X_PRICE_PER_POST, 2),
            "capped": bool(cursor.get("capped"))}


# ---------------------------------------------------------------------------------------------- numbers
def _window(days: int, now: datetime | None = None) -> tuple[datetime, datetime, datetime]:
    end = now or utcnow()
    return end - timedelta(days=days), end, end - timedelta(days=2 * days)


def _rows(db: Session, query: ListeningQuery, start: datetime, end: datetime) -> list[Mention]:
    return list(db.scalars(select(Mention).where(Mention.query_id == query.id, Mention.published_at >= start,
                                                 Mention.published_at < end, Mention.status != "muted")
                           .order_by(Mention.published_at)))


def net_sentiment(mentions: list[Mention]) -> int:
    pos = sum(1 for m in mentions if m.sentiment == "positive")
    neg = sum(1 for m in mentions if m.sentiment == "negative")
    return round((pos - neg) / (pos + neg) * 100) if pos + neg else 0


def _split(mentions: list[Mention]) -> dict:
    total = len(mentions) or 1
    counts = Counter(m.sentiment or "neutral" for m in mentions)
    return {key: round(counts.get(key, 0) / total * 100) for key in ("positive", "neutral", "negative")}


def _delta(now: float, before: float) -> float | None:
    return round((now - before) / before * 100, 1) if before else None


def _brand_exclude(query: ListeningQuery) -> set[str]:
    return {tx.normalize(k).lstrip("#@") for k in tx.search_terms(query)}


def word_cloud(mentions: list[Mention], exclude: set[str], limit: int = 40) -> list[dict]:
    counts: Counter = Counter()
    moods: dict[str, Counter] = defaultdict(Counter)
    for m in mentions:
        for word in set(tx.words(m.text, exclude)):
            counts[word] += 1
            moods[word][m.sentiment or "neutral"] += 1
    forms = tx.display_forms([m.text for m in mentions[-3000:]], exclude)
    out = []
    for word, count in counts.most_common(limit):
        mood = moods[word]
        share_pos = mood["positive"] / count
        share_neg = mood["negative"] / count
        out.append({"word": forms.get(word, word), "count": count,
                    "sentiment": "positive" if share_pos >= 0.5 else "negative" if share_neg >= 0.5 else "neutral",
                    "positive": round(share_pos * 100), "negative": round(share_neg * 100)})
    return out


def _event_out_short(event: RadarEvent) -> dict:
    return {"id": event.id, "kind": event.kind, "severity": event.severity, "state": event.state,
            "title": event.title, "what": event.what, "started_at": event.started_at, "brand": event.brand}


SEVERITY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "info": 3}


def open_events(db: Session, query: ListeningQuery, limit: int = 6) -> list[RadarEvent]:
    events = list(db.scalars(select(RadarEvent).where(RadarEvent.query_id == query.id, RadarEvent.state == "open")
                             .order_by(RadarEvent.started_at.desc()).limit(50)))
    events.sort(key=lambda e: (SEVERITY_ORDER.get(e.severity, 9), -e.started_at.timestamp()))
    return events[:limit]


def overview(db: Session, workspace: Workspace, query: ListeningQuery, days: int = 30) -> dict:
    start, end, prev_start = _window(days)
    rows = _rows(db, query, prev_start, end)
    now_all = [m for m in rows if _aware(m.published_at) >= start]
    prev_all = [m for m in rows if _aware(m.published_at) < start]
    own, prev_own = [m for m in now_all if m.brand is None], [m for m in prev_all if m.brand is None]
    tz = workspace_tz(workspace)
    first_day = start.astimezone(tz).date()
    daily = Counter((_aware(m.published_at).astimezone(tz).date() - first_day).days for m in own)
    spikes = {(_aware(e.started_at).astimezone(tz).date() - first_day).days: e.kind for e in db.scalars(
        select(RadarEvent).where(RadarEvent.query_id == query.id, RadarEvent.kind.in_(("crisis", "spike")),
                                 RadarEvent.started_at >= start))}
    series = [{"date": (first_day + timedelta(days=i)).isoformat(), "count": daily.get(i, 0),
               "event": spikes.get(i)} for i in range(days + 1)]
    sov = (len(own) / len(now_all) * 100) if query.competitors and now_all else None
    prev_sov = (len(prev_own) / len(prev_all) * 100) if query.competitors and prev_all else None
    reach, prev_reach = sum(m.reach for m in own), sum(m.reach for m in prev_own)
    return {
        "query_id": query.id, "days": days, "last_collected_at": query.last_collected_at,
        "kpis": {
            "mentions": {"value": len(own), "delta": _delta(len(own), len(prev_own))},
            "reach": {"value": reach, "delta": _delta(reach, prev_reach)},
            "net_sentiment": {"value": net_sentiment(own), "change": net_sentiment(own) - net_sentiment(prev_own)
                              if prev_own else None},
            "share_of_voice": {"value": round(sov) if sov is not None else None,
                               "change": round(sov - prev_sov) if sov is not None and prev_sov is not None else None},
        },
        "series": series,
        "sentiment": _split(own),
        "sources": [{"source": s, "count": c} for s, c in Counter(m.source if m.source != "owned" else
                                                                  (m.platform or "owned") for m in own).most_common()],
        "words": word_cloud(own, _brand_exclude(query), 30),
        "events": [_event_out_short(e) for e in open_events(db, query)],
    }


def voice(db: Session, workspace: Workspace, query: ListeningQuery, days: int = 30) -> dict:
    start, end, prev_start = _window(days)
    rows = [m for m in _rows(db, query, prev_start, end) if m.brand is None]
    now_rows = [m for m in rows if _aware(m.published_at) >= start]
    prev_rows = [m for m in rows if _aware(m.published_at) < start]
    exclude = _brand_exclude(query)

    phrase_counts: Counter = Counter()
    phrase_mood: dict[str, Counter] = defaultdict(Counter)
    for m in now_rows:
        for p in set(tx.phrases(m.text, exclude)):
            phrase_counts[p] += 1
            phrase_mood[p][m.sentiment or "neutral"] += 1
    shown = tx.display_forms([m.text for m in now_rows[-3000:]], exclude)
    phrase_list = [{"phrase": " ".join(shown.get(w, w) for w in p.split(" ")), "count": c,
                    "sentiment": phrase_mood[p].most_common(1)[0][0]}
                   for p, c in phrase_counts.most_common(10) if c >= 2]

    tags_now = Counter(h for m in now_rows for h in set(tx.hashtags(m.text)))
    tags_prev = Counter(h for m in prev_rows for h in set(tx.hashtags(m.text)))
    hashtag_list = [{"tag": t, "count": c, "change": _delta(c, tags_prev.get(t, 0))}
                    for t, c in tags_now.most_common(10)]

    week_start = end - timedelta(days=7)
    last7 = [m for m in rows if _aware(m.published_at) >= week_start]
    prior7 = [m for m in rows if week_start - timedelta(days=7) <= _aware(m.published_at) < week_start]
    recent = Counter(w for m in last7 for w in set(tx.words(m.text, exclude)))
    older = Counter(w for m in prior7 for w in set(tx.words(m.text, exclude)))
    mood = defaultdict(Counter)
    for m in last7:
        for w in set(tx.words(m.text, exclude)):
            mood[w][m.sentiment or "neutral"] += 1
    forms = tx.display_forms([m.text for m in last7], exclude)
    rising = sorted(((w, c, older.get(w, 0)) for w, c in recent.items() if c >= 3 and c >= 2 * max(older.get(w, 0), 1)),
                    key=lambda r: (r[1] - r[2]), reverse=True)[:6]
    rising_list = [{"word": forms.get(w, w), "count": c, "before": b, "change": _delta(c, b),
                    "sentiment": mood[w].most_common(1)[0][0]} for w, c, b in rising]

    def best(sentiment):
        pool = [m for m in now_rows if m.sentiment == sentiment]
        pool.sort(key=lambda m: (m.reach or 0) + (m.engagement or 0) * 5 + (m.author_followers or 0), reverse=True)
        return mention_out(pool[0]) if pool else None

    return {"words": word_cloud(now_rows, exclude, 60), "phrases": phrase_list, "hashtags": hashtag_list,
            "rising": rising_list, "top_positive": best("positive"), "top_negative": best("negative"),
            "total": len(now_rows)}


def competitors(db: Session, workspace: Workspace, query: ListeningQuery, days: int = 30) -> dict:
    start, end, _prev = _window(days)
    rows = _rows(db, query, start, end)
    names = [None] + [c.get("name") for c in query.competitors or []]
    label = {None: workspace.name, **{n: n for n in names if n}}
    weeks = max(4, min(12, days // 7))
    week_rows = _rows(db, query, end - timedelta(weeks=weeks), end)
    sov_weeks = []
    for w in range(weeks):
        w_start = end - timedelta(weeks=weeks - w)
        w_rows = [m for m in week_rows if w_start <= _aware(m.published_at) < w_start + timedelta(weeks=1)]
        total = len(w_rows) or 1
        counts = Counter(m.brand for m in w_rows)
        sov_weeks.append({"week_start": w_start.date().isoformat(),
                          "shares": [round(counts.get(n, 0) / total * 100) for n in names],
                          "counts": [counts.get(n, 0) for n in names]})
    total = len(rows) or 1
    table = []
    for n in names:
        mine = [m for m in rows if m.brand == n]
        strong = sum(1 for m in mine if m.emotion and m.emotion != "none")
        topics = Counter(m.topic for m in mine if m.topic)
        complaints = Counter(m.topic for m in mine if m.topic and m.sentiment == "negative")
        table.append({"brand": label[n], "own": n is None, "mentions": len(mine),
                      "share_of_voice": round(len(mine) / total * 100), "net_sentiment": net_sentiment(mine),
                      "passion": round(strong / len(mine) * 100) if mine else 0,
                      "top_topic": topics.most_common(1)[0][0] if topics else None,
                      "top_complaint": complaints.most_common(1)[0][0] if complaints else None})
    return {"brands": [label[n] for n in names], "weeks": sov_weeks, "table": table}


def breakdowns(db: Session, workspace: Workspace, query: ListeningQuery, days: int = 30) -> dict:
    start, end, _prev = _window(days)
    own = [m for m in _rows(db, query, start, end) if m.brand is None]
    tz = workspace_tz(workspace)
    heat = [[0] * 12 for _ in range(7)]
    for m in own:
        local = _aware(m.published_at).astimezone(tz)
        heat[(local.weekday() + 1) % 7][local.hour // 2] += 1  # rows: Sunday first
    total = len(own) or 1
    emotions = Counter(m.emotion for m in own if m.emotion and m.emotion != "none")
    emo_total = sum(emotions.values()) or 1
    topic_rows: dict[str, list[Mention]] = defaultdict(list)
    for m in own:
        if m.topic:
            topic_rows[m.topic].append(m)
    topics = sorted(({"topic": t, "count": len(ms), "net_sentiment": net_sentiment(ms)}
                     for t, ms in topic_rows.items()), key=lambda r: r["count"], reverse=True)[:12]
    countries = Counter((m.country or "").upper() for m in own if m.country)
    langs = Counter(m.lang for m in own if m.lang)
    intents = Counter(m.intent for m in own if m.intent)
    return {
        "heatmap": heat,
        "emotions": [{"emotion": e, "share": round(c / emo_total * 100)} for e, c in emotions.most_common()],
        "topics": topics,
        "countries": [{"country": c, "share": round(n / total * 100)} for c, n in countries.most_common(8)],
        "languages": [{"lang": lang, "share": round(n / total * 100)} for lang, n in langs.most_common(5)],
        "intents": [{"intent": i, "count": c} for i, c in intents.most_common()],
    }


def brief(db: Session, workspace: Workspace, query: ListeningQuery, hours: int = 24) -> dict:
    """Numbers for the morning brief: the last ``hours`` against the same span before."""
    end = utcnow()
    rows = [m for m in _rows(db, query, end - timedelta(hours=2 * hours), end) if m.brand is None]
    now_rows = [m for m in rows if _aware(m.published_at) >= end - timedelta(hours=hours)]
    events = [e for e in open_events(db, query, 10) if _aware(e.started_at) >= end - timedelta(hours=hours)]
    return {"mentions": len(now_rows), "before": len(rows) - len(now_rows), "net_sentiment": net_sentiment(now_rows),
            "negative": sum(1 for m in now_rows if m.sentiment == "negative"), "events": events}


# ------------------------------------------------------------------------------------------- mentions
SOURCE_PLATFORM = {"instagram": "instagram", "facebook": "facebook", "youtube": "youtube", "x": "x",
                   "google_business": "google_business", "news": "news"}


def mention_out(m: Mention) -> dict:
    return {"id": m.id, "source": m.source, "platform": m.platform or SOURCE_PLATFORM.get(m.source, m.source),
            "url": m.url, "author_name": m.author_name, "author_handle": m.author_handle,
            "author_followers": m.author_followers, "text": m.text, "lang": m.lang, "country": m.country,
            "published_at": m.published_at, "brand": m.brand, "reach": m.reach, "engagement": m.engagement,
            "sentiment": m.sentiment, "intent": m.intent, "topic": m.topic, "emotion": m.emotion,
            "status": m.status, "corrected": m.corrected, "conversation_id": m.conversation_id,
            "can_inbox": (m.platform or m.source) in INBOX_PLATFORMS and m.source != "google_business"}


def list_mentions(db: Session, query: ListeningQuery, *, days: int = 30, sentiment: str | None = None,
                  intent: str | None = None, source: str | None = None, brand: str | None = "own",
                  status: str | None = None, q: str | None = None, influencers: bool = False,
                  unanswered: bool = False, ids: list[int] | None = None, offset: int = 0,
                  limit: int = 50) -> tuple[list[Mention], int]:
    stmt = select(Mention).where(Mention.query_id == query.id)
    if ids:
        stmt = stmt.where(Mention.id.in_(ids))
    else:
        stmt = stmt.where(Mention.published_at >= utcnow() - timedelta(days=days))
    if sentiment:
        stmt = stmt.where(Mention.sentiment == sentiment)
    if intent:
        stmt = stmt.where(Mention.intent == intent)
    if source:
        stmt = stmt.where((Mention.source == source) | (Mention.platform == source))
    if brand == "own":
        stmt = stmt.where(Mention.brand.is_(None))
    elif brand and brand != "all":
        stmt = stmt.where(Mention.brand == brand)
    if status:
        stmt = stmt.where(Mention.status == status)
    elif not ids:
        stmt = stmt.where(Mention.status != "muted")
    if q and q.strip():
        stmt = stmt.where(Mention.text.ilike(f"%{q.strip()}%"))
    if influencers:
        stmt = stmt.where(Mention.author_followers >= 10_000)
    if unanswered:
        stmt = stmt.where(Mention.status == "new", Mention.intent.in_(("question", "purchase", "complaint")))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(Mention.published_at.desc()).offset(offset).limit(limit)))
    return rows, total


def mention_counts(db: Session, query: ListeningQuery, days: int = 30) -> dict:
    base = select(func.count()).where(Mention.query_id == query.id, Mention.brand.is_(None),
                                      Mention.status != "muted",
                                      Mention.published_at >= utcnow() - timedelta(days=days))
    return {
        "all": db.scalar(base) or 0,
        "negative": db.scalar(base.where(Mention.sentiment == "negative")) or 0,
        "purchase": db.scalar(base.where(Mention.intent == "purchase")) or 0,
        "influencers": db.scalar(base.where(Mention.author_followers >= 10_000)) or 0,
        "unanswered": db.scalar(base.where(Mention.status == "new",
                                           Mention.intent.in_(("question", "purchase", "complaint")))) or 0,
    }


def _account_for(db: Session, mention: Mention) -> SocialAccount | None:
    platform = mention.platform or mention.source
    if mention.account_id:
        account = db.get(SocialAccount, mention.account_id)
        if account and account.platform == platform and account.active:
            return account
    return db.scalar(select(SocialAccount).where(SocialAccount.workspace_id == mention.workspace_id,
                                                 SocialAccount.platform == platform,
                                                 SocialAccount.active.is_(True)).order_by(SocialAccount.id))


def mention_to_inbox(db: Session, mention: Mention):
    """Open the mention as a comment conversation in the inbox (replies then go through the inbox)."""
    from app.modules.inbox import service as inbox
    from app.modules.inbox.models import Conversation

    if mention.conversation_id:
        conv = db.get(Conversation, mention.conversation_id)
        if conv:
            return conv
    platform = mention.platform or mention.source
    if platform not in INBOX_PLATFORMS or mention.source == "google_business":
        raise AppError(_("Mentions from this source cannot be answered from the inbox. Open the original post "
                         "to reply."), code="radar_no_inbox")
    account = _account_for(db, mention)
    if not account:
        raise AppError(_("Connect a {platform} account to answer this mention from the inbox.",
                         platform=platform.capitalize()), code="radar_no_account")
    conv = inbox.find_or_create(db, account, "comment", mention.external_id,
                                customer={"name": mention.author_name, "handle": mention.author_handle},
                                post={"url": mention.url, "text": mention.text})
    inbox.ingest(db, conv, {"direction": "in", "channel": "public", "body": mention.text,
                            "external_id": f"radar-{mention.id}", "sent_at": mention.published_at,
                            "author_name": mention.author_name or mention.author_handle}, bot=False)
    conv.sentiment = mention.sentiment
    conv.intent = INTENT_TO_INBOX.get(mention.intent or "", conv.intent)
    mention.conversation_id, mention.status = conv.id, "converted"
    db.flush()
    return conv


# --------------------------------------------------------------------------------------------- events
def event_post_text(event: RadarEvent) -> str:
    return (event.draft or event.suggestion or event.title or "").strip()


def _publish_accounts(db: Session, event: RadarEvent) -> list[int]:
    from app.modules.social.models import PUBLISH_PLATFORMS
    rows = db.scalars(select(Mention).where(Mention.id.in_(event.evidence_ids or [0]))).all()
    platforms = {m.platform or m.source for m in rows} & set(PUBLISH_PLATFORMS)
    stmt = select(SocialAccount.id).where(SocialAccount.workspace_id == event.workspace_id,
                                          SocialAccount.active.is_(True),
                                          SocialAccount.platform.in_(platforms or PUBLISH_PLATFORMS))
    ids = list(db.scalars(stmt))
    if not ids and platforms:
        ids = list(db.scalars(select(SocialAccount.id).where(
            SocialAccount.workspace_id == event.workspace_id, SocialAccount.active.is_(True),
            SocialAccount.platform.in_(PUBLISH_PLATFORMS))))
    return ids


def act(db: Session, event: RadarEvent, user_id: int, action: str, *, account_ids: list[int] | None = None,
        text: str | None = None) -> dict:
    """Do the suggested step: studio | planner | approval | inbox | dismiss. Returns {"url", ...}."""
    from app.modules.planning.service import day_to_dt
    from app.modules.social import publishing
    from app.modules.social import service as social

    body = (text or "").strip() or event_post_text(event)
    result: dict = {"action": action}
    if action == "dismiss":
        event.state = "dismissed"
        db.flush()
        return {**result, "url": "/radar"}
    if action == "inbox":
        converted = 0
        last = None
        for mention in db.scalars(select(Mention).where(Mention.id.in_(event.evidence_ids or [0]))):
            try:
                last = mention_to_inbox(db, mention)
                converted += 1
            except AppError:
                continue
        if not converted:
            raise AppError(_("None of these mentions can be answered from the inbox. Open the originals to "
                             "reply."), code="radar_no_inbox")
        result.update(url=f"/inbox/{last.id}" if converted == 1 else "/inbox", converted=converted)
        ref = f"conversations:{converted}"
    else:
        if action not in ("studio", "planner", "approval"):
            raise AppError(_("Unknown action."), code="bad_action")
        workspace = db.get(Workspace, event.workspace_id)
        planned = None
        if action == "planner":
            tz = workspace_tz(workspace)
            planned = day_to_dt((utcnow().astimezone(tz) + timedelta(days=1)).date())
        accounts = account_ids if account_ids is not None else (
            _publish_accounts(db, event) if action == "approval" else [])
        post = social.create_post(db, event.workspace_id, user_id, content=body, account_ids=accounts,
                                  name=event.title[:120], planned_date=planned, source_ref=f"radar:{event.id}",
                                  ai_brief=f"{event.what}\n{event.why}\n{event.suggestion}")
        if action == "approval":
            if not accounts:
                raise AppError(_("Connect an account to publish on first."), code="radar_no_account")
            publishing.send_for_approval(db, post, user_id, "best_time")
        result.update(post_id=post.id, url={"studio": f"/studio?post={post.id}",
                                            "planner": f"/planner?post={post.id}",
                                            "approval": f"/approvals?post={post.id}"}[action])
        ref = f"post:{post.id}"
    event.state, event.acted_action, event.acted_ref, event.acted_by_id = "acted", action, ref, user_id
    db.flush()
    return result


def check_query_limits(db: Session, workspace_id: int, sources: list[str], adding: bool) -> None:
    limits.require(db, workspace_id, "listening")
    if adding:
        limits.check(db, workspace_id, "listening_queries")
    if "x" in sources:
        limits.require(db, workspace_id, "listening_x")


# ---------------------------------------------------------------------------------------------- reports
def report_block(db: Session, workspace: Workspace, start: datetime, end: datetime) -> dict | None:
    """The Radar section of scheduled reports: own-brand numbers for [start, end) against the span before,
    the most used words and the events of the period. None when the workspace listens to nothing."""
    query = db.scalar(select(ListeningQuery).where(ListeningQuery.workspace_id == workspace.id,
                                                   ListeningQuery.active.is_(True)).order_by(ListeningQuery.id))
    if not query:
        return None
    span = end - start
    rows = _rows(db, query, start - span, end)
    now_all = [m for m in rows if _aware(m.published_at) >= start]
    prev_all = [m for m in rows if _aware(m.published_at) < start]
    own, prev_own = [m for m in now_all if m.brand is None], [m for m in prev_all if m.brand is None]
    events = list(db.scalars(select(RadarEvent).where(RadarEvent.query_id == query.id,
                                                      RadarEvent.started_at >= start, RadarEvent.started_at < end,
                                                      RadarEvent.severity != "info")))
    events.sort(key=lambda e: SEVERITY_ORDER.get(e.severity, 9))
    sov = round(len(own) / len(now_all) * 100) if query.competitors and now_all else None
    return {"mentions": len(own), "mentions_delta": _delta(len(own), len(prev_own)),
            "net_sentiment": net_sentiment(own), "sentiment": _split(own), "share_of_voice": sov,
            "words": [w["word"] for w in word_cloud(own, _brand_exclude(query), 10)],
            "events": [{"title": e.title, "what": e.what, "severity": e.severity} for e in events[:3]]}
