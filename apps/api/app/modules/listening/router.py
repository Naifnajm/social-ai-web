"""Radar API (social listening). Reading is open to every member; setting up, collecting and acting need an
editor. The plan feature ``listening`` is checked on every write (``GET /listening/status`` tells the web app
whether to show the radar or the upgrade card)."""
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.core.db import utcnow
from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.core.jobs import enqueue
from app.modules.billing import limits
from app.modules.billing import platform as platform_settings
from app.modules.social.models import SocialAccount
from app.modules.workspaces.models import Role

from . import service as svc
from .models import (
    EMOTIONS,
    INTENTS,
    SENTIMENTS,
    SOURCES,
    ListeningQuery,
    Mention,
    RadarEvent,
)

router = APIRouter(prefix="/listening", tags=["radar"])
Days = Query(default=30, ge=1, le=365)


def _words(values: list[str], limit: int = 40) -> list[str]:
    out = []
    for value in values or []:
        value = " ".join(str(value).split())[:80]
        if value and value not in out:
            out.append(value)
    return out[:limit]


class Competitor(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    keywords: list[str] = []

    @field_validator("keywords")
    @classmethod
    def clean(cls, value):
        return _words(value, 15)


class QueryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    keywords: list[str] = Field(min_length=1)
    required: list[str] = []
    excluded: list[str] = []
    languages: list[Literal["ar", "en", "fr", "de", "nl"]] = []
    countries: list[str] = []
    competitors: list[Competitor] = Field(default=[], max_length=5)
    sources: list[Literal["owned", "instagram", "facebook", "youtube", "google_business", "news", "x"]] = \
        ["owned", "instagram", "facebook", "youtube", "google_business", "news"]
    active: bool = True
    x_monthly_cap: int = Field(default=3000, ge=0, le=1_000_000)

    @field_validator("keywords", "required", "excluded")
    @classmethod
    def clean(cls, value):
        return _words(value)

    @field_validator("countries")
    @classmethod
    def upper(cls, value):
        return [c.strip().upper()[:2] for c in value if c.strip()][:10]


class QueryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    keywords: list[str] | None = None
    required: list[str] | None = None
    excluded: list[str] | None = None
    languages: list[Literal["ar", "en", "fr", "de", "nl"]] | None = None
    countries: list[str] | None = None
    competitors: list[Competitor] | None = Field(default=None, max_length=5)
    sources: list[Literal["owned", "instagram", "facebook", "youtube", "google_business", "news", "x"]] | None = None
    active: bool | None = None
    x_monthly_cap: int | None = Field(default=None, ge=0, le=1_000_000)

    @field_validator("keywords", "required", "excluded")
    @classmethod
    def clean(cls, value):
        return _words(value) if value is not None else value

    @field_validator("countries")
    @classmethod
    def upper(cls, value):
        return [c.strip().upper()[:2] for c in value if c.strip()][:10] if value is not None else value


class QueryOut(BaseModel):
    id: int
    name: str
    keywords: list[str]
    required: list[str]
    excluded: list[str]
    languages: list[str]
    countries: list[str]
    competitors: list[dict]
    sources: list[str]
    active: bool
    x_monthly_cap: int
    last_collected_at: datetime | None = None
    last_error: str | None = None
    mentions: int = 0
    x_usage: dict


class MentionPatch(BaseModel):
    status: Literal["new", "reviewed", "muted"] | None = None
    sentiment: Literal["positive", "neutral", "negative"] | None = None
    intent: Literal["question", "purchase", "complaint", "praise", "news", "other"] | None = None
    topic: str | None = Field(default=None, max_length=60)


class ActIn(BaseModel):
    action: Literal["studio", "planner", "approval", "inbox", "dismiss"]
    account_ids: list[int] | None = None
    text: str | None = Field(default=None, max_length=5000)


class FeedbackIn(BaseModel):
    feedback: Literal["useful", "not_useful", "wrong"]


def _query(ctx: Ctx, query_id: int) -> ListeningQuery:
    query = ctx.db.get(ListeningQuery, query_id)
    if not query or query.workspace_id != ctx.workspace.id:
        raise NotFound(_("Listening setup not found."))
    return query


def _query_out(ctx: Ctx, query: ListeningQuery) -> QueryOut:
    count = ctx.db.scalar(select(func.count()).where(Mention.query_id == query.id)) or 0
    return QueryOut(id=query.id, name=query.name, keywords=query.keywords or [], required=query.required or [],
                    excluded=query.excluded or [], languages=query.languages or [],
                    countries=query.countries or [], competitors=query.competitors or [],
                    sources=query.sources or [], active=query.active, x_monthly_cap=query.x_monthly_cap,
                    last_collected_at=query.last_collected_at, last_error=query.last_error, mentions=count,
                    x_usage=svc.x_usage(query))


def _check_accounts(ctx: Ctx, ids: list[int] | None) -> None:
    if not ids:
        return
    valid = set(ctx.db.scalars(select(SocialAccount.id).where(SocialAccount.workspace_id == ctx.workspace.id,
                                                              SocialAccount.id.in_(ids))))
    if set(ids) - valid:
        raise NotFound(_("Account not found."))


# ------------------------------------------------------------------------------------------- status & setup
@router.get("/status")
def status(ctx: Ctx = Depends(workspace_ctx())):
    """Is the radar in the plan, which sources can be used, what is connected and what is used."""
    db, ws = ctx.db, ctx.workspace.id
    platforms = set(db.scalars(select(SocialAccount.platform).where(SocialAccount.workspace_id == ws,
                                                                    SocialAccount.active.is_(True))))
    youtube_key = bool(platform_settings.get_secret(db, "listening.youtube_api_key"))
    x_key = bool(platform_settings.get_secret(db, "listening.x_bearer_token"))
    allowed = svc.allowed_sources(db, ws)
    ready = {"owned": True, "instagram": "instagram" in platforms, "facebook": "facebook" in platforms,
             "youtube": youtube_key or "youtube" in platforms, "google_business": "google_business" in platforms,
             "news": True, "x": x_key}
    from app.modules.billing.service import billing_state
    state = billing_state(db, ws)
    queries = list(db.scalars(select(ListeningQuery).where(ListeningQuery.workspace_id == ws)
                              .order_by(ListeningQuery.id)))
    return {
        "enabled": limits.feature(db, ws, "listening"),
        "x_enabled": limits.feature(db, ws, "listening_x"),
        "queries_used": len(queries), "queries_limit": state.limits.get("listening_queries"),
        "sources": [{"source": s, "in_plan": s in allowed, "ready": ready[s], "paid": s == "x"} for s in SOURCES],
        "queries": [{"id": q.id, "name": q.name, "active": q.active} for q in queries],
        "x_price_per_post": svc.collectors.X_PRICE_PER_POST,
    }


@router.get("/queries", response_model=list[QueryOut])
def list_queries(ctx: Ctx = Depends(workspace_ctx())):
    rows = ctx.db.scalars(select(ListeningQuery).where(ListeningQuery.workspace_id == ctx.workspace.id)
                          .order_by(ListeningQuery.id))
    return [_query_out(ctx, q) for q in rows]


@router.post("/queries", response_model=QueryOut, status_code=201)
def create_query(body: QueryIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    svc.check_query_limits(ctx.db, ctx.workspace.id, body.sources, adding=True)
    data = body.model_dump()
    data["competitors"] = [c for c in data["competitors"]]
    query = ListeningQuery(workspace_id=ctx.workspace.id, **data)
    ctx.db.add(query)
    ctx.db.flush()
    ctx.db.commit()  # the first run happens in the worker
    enqueue("app.modules.listening.tasks.collect_query", query.id)
    ctx.db.refresh(query)
    return _query_out(ctx, query)


@router.get("/queries/{query_id}", response_model=QueryOut)
def one_query(query_id: int, ctx: Ctx = Depends(workspace_ctx())):
    return _query_out(ctx, _query(ctx, query_id))


@router.patch("/queries/{query_id}", response_model=QueryOut)
def update_query(query_id: int, body: QueryPatch, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    query = _query(ctx, query_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("keywords") is not None and not data["keywords"]:
        raise AppError(_("Add at least one word to listen for."), code="invalid")
    svc.check_query_limits(ctx.db, ctx.workspace.id, data.get("sources") or [], adding=False)
    for key, value in data.items():
        setattr(query, key, value)
    ctx.db.flush()
    return _query_out(ctx, query)


@router.delete("/queries/{query_id}", status_code=204)
def delete_query(query_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    ctx.db.delete(_query(ctx, query_id))
    ctx.db.flush()
    return Response(status_code=204)


@router.post("/queries/{query_id}/collect")
def collect_now(query_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    query = _query(ctx, query_id)
    limits.require(ctx.db, ctx.workspace.id, "listening")
    ctx.db.commit()
    result = enqueue("app.modules.listening.tasks.collect_query", query.id)
    return result if isinstance(result, dict) else {"queued": True}


@router.get("/estimate")
def estimate(query_id: int | None = None, ctx: Ctx = Depends(workspace_ctx())):
    """What a setup costs: expected mentions per month (from the last 30 days), X reads and their price."""
    from app.modules.billing.service import billing_state
    query = svc.get_query(ctx.db, ctx.workspace.id, query_id) if query_id else None
    expected = None
    by_source: dict = {}
    if query:
        rows = ctx.db.execute(select(Mention.source, func.count()).where(
            Mention.query_id == query.id, Mention.published_at >= utcnow() - timedelta(days=30))
            .group_by(Mention.source)).all()
        by_source = {s: c for s, c in rows}
        expected = sum(by_source.values()) if by_source else None
    cap = query.x_monthly_cap if query else 3000
    return {"expected_month": expected, "by_source": by_source, "x": svc.x_usage(query) if query else None,
            "x_cap_cost_usd": round(cap * svc.collectors.X_PRICE_PER_POST, 2),
            "queries_used": ctx.db.scalar(select(func.count()).where(
                ListeningQuery.workspace_id == ctx.workspace.id)) or 0,
            "queries_limit": billing_state(ctx.db, ctx.workspace.id).limits.get("listening_queries")}


# ------------------------------------------------------------------------------------------------ numbers
@router.get("/overview")
def overview(query_id: int | None = None, days: int = Days, ctx: Ctx = Depends(workspace_ctx())):
    return svc.overview(ctx.db, ctx.workspace, svc.get_query(ctx.db, ctx.workspace.id, query_id), days)


@router.get("/voice")
def voice(query_id: int | None = None, days: int = Days, ctx: Ctx = Depends(workspace_ctx())):
    return svc.voice(ctx.db, ctx.workspace, svc.get_query(ctx.db, ctx.workspace.id, query_id), days)


@router.get("/competitors")
def competitors(query_id: int | None = None, days: int = Days, ctx: Ctx = Depends(workspace_ctx())):
    return svc.competitors(ctx.db, ctx.workspace, svc.get_query(ctx.db, ctx.workspace.id, query_id), days)


@router.get("/breakdowns")
def breakdowns(query_id: int | None = None, days: int = Days, ctx: Ctx = Depends(workspace_ctx())):
    return svc.breakdowns(ctx.db, ctx.workspace, svc.get_query(ctx.db, ctx.workspace.id, query_id), days)


# ----------------------------------------------------------------------------------------------- mentions
@router.get("/mentions")
def mentions(query_id: int | None = None, days: int = Days,
             sentiment: Literal["positive", "neutral", "negative"] | None = None,
             intent: Literal["question", "purchase", "complaint", "praise", "news", "other"] | None = None,
             source: str | None = None, brand: str | None = "own",
             status: Literal["new", "reviewed", "muted", "converted"] | None = None, q: str | None = None,
             influencers: bool = False, unanswered: bool = False, offset: int = Query(default=0, ge=0),
             limit: int = Query(default=50, ge=1, le=200), ctx: Ctx = Depends(workspace_ctx())):
    query = svc.get_query(ctx.db, ctx.workspace.id, query_id)
    rows, total = svc.list_mentions(ctx.db, query, days=days, sentiment=sentiment, intent=intent, source=source,
                                    brand=brand, status=status, q=q, influencers=influencers,
                                    unanswered=unanswered, offset=offset, limit=limit)
    return {"items": [svc.mention_out(m) for m in rows], "total": total,
            "counts": svc.mention_counts(ctx.db, query, days)}


def _mention(ctx: Ctx, mention_id: int) -> Mention:
    mention = ctx.db.get(Mention, mention_id)
    if not mention or mention.workspace_id != ctx.workspace.id:
        raise NotFound(_("Mention not found."))
    return mention


@router.patch("/mentions/{mention_id}")
def update_mention(mention_id: int, body: MentionPatch, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    mention = _mention(ctx, mention_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("status"):
        mention.status = data["status"]
    for field in ("sentiment", "intent", "topic"):
        if field in data and data[field] is not None:
            setattr(mention, field, data[field].strip() if field == "topic" else data[field])
            mention.corrected = True
    ctx.db.flush()
    return svc.mention_out(mention)


@router.post("/mentions/{mention_id}/inbox")
def mention_to_inbox(mention_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    limits.require(ctx.db, ctx.workspace.id, "inbox")
    conv = svc.mention_to_inbox(ctx.db, _mention(ctx, mention_id))
    return {"conversation_id": conv.id, "url": f"/inbox/{conv.id}"}


# ------------------------------------------------------------------------------------------------- events
def _event(ctx: Ctx, event_id: int) -> RadarEvent:
    event = ctx.db.get(RadarEvent, event_id)
    if not event or event.workspace_id != ctx.workspace.id:
        raise NotFound(_("Event not found."))
    return event


def event_out(ctx: Ctx, event: RadarEvent, full: bool = False) -> dict:
    out = {"id": event.id, "query_id": event.query_id, "kind": event.kind, "severity": event.severity,
           "state": event.state, "brand": event.brand, "topic": event.topic, "title": event.title,
           "what": event.what, "why": event.why, "suggestion": event.suggestion, "draft": event.draft,
           "started_at": event.started_at, "ai_written": event.ai_written, "feedback": event.feedback,
           "acted_action": event.acted_action, "acted_ref": event.acted_ref, "metrics": event.metrics or {},
           "evidence_count": len(event.evidence_ids or [])}
    if full:
        rows, _total = svc.list_mentions(ctx.db, ctx.db.get(ListeningQuery, event.query_id),
                                         ids=event.evidence_ids or [0], brand="all", limit=20)
        order = {mid: i for i, mid in enumerate(event.evidence_ids or [])}
        out["evidence"] = [svc.mention_out(m) for m in sorted(rows, key=lambda m: order.get(m.id, 99))]
    return out


@router.get("/events")
def list_events(query_id: int | None = None, state: Literal["open", "acted", "dismissed", "all"] = "open",
                limit: int = Query(default=50, ge=1, le=200), ctx: Ctx = Depends(workspace_ctx())):
    stmt = select(RadarEvent).where(RadarEvent.workspace_id == ctx.workspace.id)
    if query_id:
        stmt = stmt.where(RadarEvent.query_id == query_id)
    if state != "all":
        stmt = stmt.where(RadarEvent.state == state)
    rows = list(ctx.db.scalars(stmt.order_by(RadarEvent.started_at.desc()).limit(limit)))
    rows.sort(key=lambda e: (svc.SEVERITY_ORDER.get(e.severity, 9), -e.started_at.timestamp()))
    return [event_out(ctx, e) for e in rows]


@router.get("/events/{event_id}")
def one_event(event_id: int, ctx: Ctx = Depends(workspace_ctx())):
    return event_out(ctx, _event(ctx, event_id), full=True)


@router.post("/events/{event_id}/act")
def act(event_id: int, body: ActIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    event = _event(ctx, event_id)
    _check_accounts(ctx, body.account_ids)
    if body.action in ("inbox",):
        limits.require(ctx.db, ctx.workspace.id, "inbox")
    if body.action == "approval":
        limits.require(ctx.db, ctx.workspace.id, "approvals")
    result = svc.act(ctx.db, event, ctx.user.id, body.action, account_ids=body.account_ids, text=body.text)
    return {**result, "event": event_out(ctx, event)}


@router.post("/events/{event_id}/feedback")
def feedback(event_id: int, body: FeedbackIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    event = _event(ctx, event_id)
    event.feedback = body.feedback
    if body.feedback == "wrong" and event.state == "open":
        event.state = "dismissed"
    ctx.db.flush()
    return event_out(ctx, event)


# ------------------------------------------------------------------------------------------- quick search
@router.get("/search")
def quick_search(q: str = Query(min_length=2, max_length=80), days: int = Days, live: bool = False,
                 ctx: Ctx = Depends(workspace_ctx())):
    """Search everything the radar stored (every setup), and optionally the news right now (editors)."""
    from . import collectors
    from . import text as tx

    term = q.strip()
    rows = list(ctx.db.scalars(select(Mention).where(
        Mention.workspace_id == ctx.workspace.id, Mention.published_at >= utcnow() - timedelta(days=days),
        Mention.text.ilike(f"%{term}%")).order_by(Mention.published_at.desc()).limit(200)))
    found = [svc.mention_out(m) for m in rows]
    news = []
    if live:
        ctx.require(Role.editor)
        limits.require(ctx.db, ctx.workspace.id, "listening")
        probe = ListeningQuery(id=0, workspace_id=ctx.workspace.id, name=term, keywords=[term],
                               languages=[ctx.workspace.locale if ctx.workspace.locale in ("ar", "en") else "ar"],
                               countries=[], competitors=[])
        try:
            for item in collectors.collect_news(ctx.db, probe, {})[:30]:
                result = tx.classify(item["text"])
                news.append({**item, **result, "id": None, "platform": "news"})
        except Exception:  # live news is a bonus; stored results still answer
            news = []
    split = {s: sum(1 for m in rows if m.sentiment == s) for s in SENTIMENTS}
    return {"q": term, "total": len(rows), "sentiment": split, "items": found[:50], "news": news,
            "intents": {i: sum(1 for m in rows if m.intent == i) for i in INTENTS},
            "emotions": {e: sum(1 for m in rows if m.emotion == e) for e in EMOTIONS if e != "none"}}
