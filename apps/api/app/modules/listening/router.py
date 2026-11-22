"""Radar API (social listening). Reading is open to every member; setting up, collecting and acting need an
editor. The plan feature ``listening`` is checked on every write (``GET /listening/status`` tells the web app
whether to show the radar or the upgrade card)."""
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.core.db import get_db, utcnow
from app.core.deps import Ctx, superadmin, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.core.jobs import enqueue
from app.modules.billing import limits
from app.modules.social.models import SocialAccount
from app.modules.workspaces.models import Role

from . import registry
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


SourceKey = Literal["owned", "instagram", "facebook", "threads", "youtube", "youtube_comments", "google_business", "linkedin", "news", "web", "x", "reddit", "tiktok", "telegram", "app_store", "google_play"]
DEFAULT_SOURCES = ["owned", "instagram", "facebook", "threads", "youtube", "youtube_comments", "google_business",
                   "news"]


class QueryOptions(BaseModel):
    """Lists some sources read: public Telegram channels, App Store / Google Play app ids, subreddits and extra
    YouTube channels whose video comments are read."""
    telegram_channels: list[str] = Field(default=[], max_length=10)
    app_store_ids: list[str] = Field(default=[], max_length=5)
    google_play_ids: list[str] = Field(default=[], max_length=5)
    subreddits: list[str] = Field(default=[], max_length=3)
    youtube_channel_ids: list[str] = Field(default=[], max_length=2)

    @field_validator("telegram_channels", "app_store_ids", "google_play_ids", "subreddits", "youtube_channel_ids")
    @classmethod
    def clean(cls, value):
        return _words(value, 10)


class QueryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    keywords: list[str] = Field(min_length=1)
    required: list[str] = []
    excluded: list[str] = []
    languages: list[Literal["ar", "en", "fr", "de", "nl"]] = []
    countries: list[str] = []
    competitors: list[Competitor] = Field(default=[], max_length=5)
    sources: list[SourceKey] = DEFAULT_SOURCES
    active: bool = True
    x_monthly_cap: int = Field(default=3000, ge=0, le=1_000_000)
    monthly_cap_usd: float | None = Field(default=None, ge=0, le=100_000)
    options: QueryOptions = QueryOptions()

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
    sources: list[SourceKey] | None = None
    active: bool | None = None
    x_monthly_cap: int | None = Field(default=None, ge=0, le=1_000_000)
    monthly_cap_usd: float | None = Field(default=None, ge=0, le=100_000)
    options: QueryOptions | None = None

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
    monthly_cap_usd: float | None = None
    options: dict = {}
    spend: dict = {}


class MentionPatch(BaseModel):
    status: Literal["new", "reviewed", "muted", "spam"] | None = None
    sentiment: Literal["positive", "neutral", "negative"] | None = None
    intent: Literal["question", "purchase", "complaint", "praise", "news", "other"] | None = None
    topic: str | None = Field(default=None, max_length=60)


class ActIn(BaseModel):
    action: Literal["studio", "planner", "approval", "inbox", "dismiss"]
    account_ids: list[int] | None = None
    text: str | None = Field(default=None, max_length=5000)


class BoardIn(BaseModel):
    template: str = Field(default="pipeline_quick", max_length=40)


class ReportIn(BaseModel):
    on: bool = True


class AssignIn(BaseModel):
    user_id: int | None = None
    note: str | None = Field(default=None, max_length=500)


class SourceToggleIn(BaseModel):
    query_id: int | None = None
    on: bool = True


class OwnKeyIn(BaseModel):
    key: str | None = Field(default=None, max_length=500)


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
                    x_usage=svc.x_usage(query), monthly_cap_usd=query.monthly_cap_usd,
                    options=query.options or {}, spend=svc.spend(query))


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
    allowed = svc.allowed_sources(db, ws)
    health = {s: registry.health(db, ws, s) for s in SOURCES}
    from app.modules.billing.service import billing_state
    state = billing_state(db, ws)
    queries = list(db.scalars(select(ListeningQuery).where(ListeningQuery.workspace_id == ws)
                              .order_by(ListeningQuery.id)))
    return {
        "enabled": limits.feature(db, ws, "listening"),
        "x_enabled": limits.feature(db, ws, "listening_x"),
        "queries_used": len(queries), "queries_limit": state.limits.get("listening_queries"),
        "sources": [{"source": s, "in_plan": s in allowed, "ready": health[s]["status"] == "ready",
                     "paid": s in registry.PAID, "status": health[s]["status"],
                     "access": registry.SOURCE_DEFS[s].access, "beta": registry.SOURCE_DEFS[s].beta}
                    for s in SOURCES],
        "queries": [{"id": q.id, "name": q.name, "active": q.active} for q in queries],
        "x_price_per_post": registry.cost_view(db, "x", ws)["unit_price"],
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
    data["options"] = {k: v for k, v in (data.get("options") or {}).items() if v}
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
    if "options" in data:
        data["options"] = {k: v for k, v in (data["options"] or {}).items() if v}
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
    """What a setup costs: expected mentions per month (from the last 30 days) and, for each paid source, the units
    it used in the last 30 days and their price per month at the workspace's price (cost + markup)."""
    from app.modules.billing.service import billing_state
    query = svc.get_query(ctx.db, ctx.workspace.id, query_id) if query_id else None
    expected = None
    by_source: dict = {}
    costs: dict = {}
    if query:
        rows = ctx.db.execute(select(Mention.source, func.count()).where(
            Mention.query_id == query.id, Mention.published_at >= utcnow() - timedelta(days=30))
            .group_by(Mention.source)).all()
        by_source = {s: c for s, c in rows}
        expected = sum(by_source.values()) if by_source else None
        for source, cursor in (query.cursors or {}).items():
            if source in registry.PAID and isinstance(cursor, dict):
                spend = cursor.get("spend") or {}
                units = int(spend.get("units") or 0) + int(spend.get("own_units") or 0)
                costs[source] = {"units_month": units, "usd_month": round(float(spend.get("usd") or 0), 2)}
    defaults = {"web": 8 * 30, "reddit": 12 * 4 * 30, "tiktok": 4 * 4 * 30}  # units a month at the run cadence
    for source in registry.PAID:
        cost = registry.cost_view(ctx.db, source, ctx.workspace.id)
        units = (costs.get(source) or {}).get("units_month") or (
            (query.x_monthly_cap if query else 3000) if source == "x" else defaults.get(source, 0))
        costs.setdefault(source, {})
        costs[source].update(unit=cost["unit"], unit_price=cost["unit_price"], own_key=cost["own_key"],
                             expected_units=units, expected_usd=round(units * cost["unit_price"], 2))
    cap = query.x_monthly_cap if query else 3000
    return {"expected_month": expected, "by_source": by_source, "x": svc.x_usage(query) if query else None,
            "x_cap_cost_usd": round(cap * registry.cost_view(ctx.db, "x", ctx.workspace.id)["unit_price"], 2),
            "costs": costs, "spend": svc.spend(query) if query else None,
            "queries_used": ctx.db.scalar(select(func.count()).where(
                ListeningQuery.workspace_id == ctx.workspace.id)) or 0,
            "queries_limit": billing_state(ctx.db, ctx.workspace.id).limits.get("listening_queries")}


# ------------------------------------------------------------------------------------------------ sources
def _optional_query(ctx: Ctx, query_id: int | None) -> ListeningQuery | None:
    if query_id:
        return _query(ctx, query_id)
    return ctx.db.scalar(select(ListeningQuery).where(ListeningQuery.workspace_id == ctx.workspace.id)
                         .order_by(ListeningQuery.active.desc(), ListeningQuery.id))


def _source_key(key: str) -> str:
    if key not in registry.SOURCE_DEFS:
        raise NotFound(_("Source not found."))
    return key


@router.get("/sources")
def list_sources(query_id: int | None = None, ctx: Ctx = Depends(workspace_ctx())):
    """Every radar source with its status for this workspace (and setup), what it costs and the button that fixes
    it."""
    query = _optional_query(ctx, query_id)
    from app.modules.billing import credits
    return {"query_id": query.id if query else None, "sources": registry.workspace_view(ctx.db, ctx.workspace.id, query),
            "credits": credits.available(ctx.db, ctx.workspace.id), "spend": svc.spend(query) if query else None}


@router.post("/sources/{key}/test")
def test_source(key: str, body: SourceToggleIn | None = None, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Check the source again; when the setup uses it, read it once now (charged like any run)."""
    key = _source_key(key)
    query = _optional_query(ctx, body.query_id if body else None)
    result = None
    if query and key in (query.sources or []) and registry.health(ctx.db, ctx.workspace.id, key)["status"] == "ready":
        limits.require(ctx.db, ctx.workspace.id, "listening")
        cursors = dict(query.cursors or {})
        cursor = dict(cursors.get(key) or {})
        cursor.pop("at", None)  # a test ignores the source's waiting time
        cursors[key] = cursor
        query.cursors = cursors
        outcome = svc.collect(ctx.db, query, only=[key])
        result = {"new": outcome["new"], "error": outcome["errors"].get(key)}
    return {"key": key, "health": registry.health(ctx.db, ctx.workspace.id, key, query if query and key in (
        query.sources or []) else None), "result": result}


@router.post("/sources/{key}/toggle")
def toggle_source(key: str, body: SourceToggleIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Use (or stop using) a source in a setup."""
    key = _source_key(key)
    query = _optional_query(ctx, body.query_id)
    if not query:
        raise NotFound(_("Set up what to listen for first."))
    sources = [s for s in query.sources or [] if s != key]
    if body.on:
        if not registry.SOURCE_DEFS[key].available:
            raise AppError(_("This source cannot be used."), code="radar_source_unavailable")
        svc.check_query_limits(ctx.db, ctx.workspace.id, [key], adding=False)
        sources.append(key)
    query.sources = sources
    ctx.db.flush()
    return _query_out(ctx, query)


@router.put("/sources/{key}/own-key")
def set_own_key(key: str, body: OwnKeyIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """The workspace's own API key for X or Brave (its reads are then not charged). Write-only."""
    key = _source_key(key)
    if not registry.SOURCE_DEFS[key].byo:
        raise AppError(_("This source cannot use your own key."), code="radar_no_own_key")
    registry.set_own_key(ctx.db, ctx.workspace.id, key, (body.key or "").strip() or None)
    return {"key": key, "own_key": bool(registry.own_key(ctx.db, ctx.workspace.id, key))}


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
             status: Literal["new", "reviewed", "muted", "converted", "spam"] | None = None, q: str | None = None,
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


@router.post("/mentions/{mention_id}/reply")
def mention_reply(mention_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """A reply draft in the brand's voice (brand guard applied). Comments on your own accounts open in the inbox;
    public mentions come with the link to answer on the network."""
    return svc.mention_reply(ctx.db, _mention(ctx, mention_id), ctx.user.id)


@router.post("/mentions/{mention_id}/post")
def mention_post(mention_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """A draft post in Studio written by the AI from what the person said."""
    limits.require(ctx.db, ctx.workspace.id, "ai_studio")
    return svc.mention_to_post(ctx.db, _mention(ctx, mention_id), ctx.user.id)


@router.post("/mentions/{mention_id}/board")
def mention_board(mention_id: int, body: BoardIn | None = None, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """A production board (template) with the mention as its idea."""
    limits.require(ctx.db, ctx.workspace.id, "production")
    return svc.mention_to_board(ctx.db, _mention(ctx, mention_id), ctx.user.id,
                                (body.template if body else None) or "pipeline_quick")


@router.post("/mentions/{mention_id}/report")
def mention_report(mention_id: int, body: ReportIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Show (or stop showing) the mention in the next scheduled reports."""
    return svc.mention_report(ctx.db, _mention(ctx, mention_id), body.on)


@router.post("/mentions/{mention_id}/assign")
def mention_assign(mention_id: int, body: AssignIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Give the mention to a teammate (they get a notification); ``user_id`` null clears it."""
    return svc.mention_assign(ctx.db, _mention(ctx, mention_id), ctx.user.id, body.user_id, body.note)


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
           "evidence_count": len(event.evidence_ids or []),
           "links": {"inbox": "/inbox" if event.kind in ("crisis", "influencer", "opportunity") else None,
                     "ideas": "/ideas" if event.kind in ("opportunity", "rising", "competitor", "spike") else None}}
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


# ------------------------------------------------------------------------------------- platform admin
class AdminSourcesIn(BaseModel):
    secrets: dict[str, str | None] = {}            # setting key -> new value ("" or null clears it)
    prices: dict[str, float | None] = {}           # source -> $ per unit (null: back to the default)
    enabled: dict[str, bool] = {}                  # source -> on/off for every workspace
    youtube_units_per_run: int | None = Field(default=None, ge=1, le=10_000)


def _admin_out(db) -> dict:
    from app.modules.ai.models import AIUsage
    from app.modules.billing.limits import month_start
    from app.modules.workspaces.models import Workspace
    price = func.coalesce(func.sum(func.coalesce(AIUsage.price, AIUsage.cost)), 0.0)
    rows = db.execute(select(Workspace.id, Workspace.name, AIUsage.model_name, func.coalesce(func.sum(AIUsage.cost), 0.0),
                             price, func.coalesce(func.sum(AIUsage.units), 0.0))
                      .where(AIUsage.capability == "data", AIUsage.created_at >= month_start(),
                             Workspace.id == AIUsage.workspace_id)
                      .group_by(Workspace.id, Workspace.name, AIUsage.model_name).order_by(price.desc()).limit(200)).all()
    workspaces: dict[int, dict] = {}
    for wid, name, model_name, cost, charged, units in rows:
        row = workspaces.setdefault(wid, {"id": wid, "name": name, "cost": 0.0, "price": 0.0, "by_source": {}})
        source = registry.source_of_usage(model_name) or model_name
        row["cost"] = round(row["cost"] + float(cost), 4)
        row["price"] = round(row["price"] + float(charged), 4)
        row["by_source"][source] = {"cost": round(float(cost), 4), "units": round(float(units))}
    from app.modules.billing import credits, platform
    return {"sources": registry.admin_view(db), "markup_percent": credits.markup(db),
            "youtube_units_per_run": registry.youtube_units_per_run(db),
            "youtube_units_today": registry.youtube_units_used(db), "youtube_daily_units": registry.YOUTUBE_DAILY_UNITS,
            "workspaces": sorted(workspaces.values(), key=lambda r: -r["cost"])[:25],
            "month_cost": round(sum(r["cost"] for r in workspaces.values()), 4),
            "month_price": round(sum(r["price"] for r in workspaces.values()), 4),
            "settings_keys": [k for k in platform.SETTINGS_SCHEMA if k.startswith("listening.")]}


@router.get("/admin/sources")
def admin_sources(admin=Depends(superadmin), db=Depends(get_db)):
    """Platform admin: every source with its keys (configured or not, never the value), unit price, on/off and what
    it cost this month, per source and per workspace."""
    return _admin_out(db)


@router.put("/admin/sources")
def admin_update_sources(body: AdminSourcesIn, admin=Depends(superadmin), db=Depends(get_db)):
    from app.modules.billing import platform
    for key, value in body.secrets.items():
        if key not in registry.SECRET_KEYS:
            raise AppError(_("Unknown setting: {key}", key=key), code="bad_setting")
        platform.set_secret(db, key, (value or "").strip() or None, admin.id)
    if body.prices:
        prices = dict(platform.get_setting(db, "listening.unit_prices") or {})
        for source, value in body.prices.items():
            spec = registry.SOURCE_DEFS.get(source)
            if not spec or not spec.unit:
                raise AppError(_("Unknown source: {key}", key=source), code="bad_setting")
            if value is None:
                prices.pop(source, None)
            elif value < 0:
                raise AppError(_("Invalid value for {key}.", key=source), code="bad_setting")
            else:
                prices[source] = float(value)
        platform.set_setting(db, "listening.unit_prices", prices or None, admin.id)
    if body.enabled:
        off = registry.switched_off(db)
        for source, on in body.enabled.items():
            if source not in registry.SOURCE_DEFS:
                raise AppError(_("Unknown source: {key}", key=source), code="bad_setting")
            off = (off - {source}) if on else (off | {source})
        platform.set_setting(db, "listening.sources_off", sorted(off), admin.id)
    if body.youtube_units_per_run is not None:
        platform.set_setting(db, "listening.youtube_units_per_run", body.youtube_units_per_run, admin.id)
    return _admin_out(db)
