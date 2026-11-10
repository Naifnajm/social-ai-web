"""Planning API: campaigns, content pillars, the Planner calendar and evergreen reposting."""
from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.modules.social.models import Post, PostTarget, SocialAccount
from app.modules.workspaces.models import Membership, Role

from . import service as svc
from .models import Campaign, ContentPillar
from .schemas import (BestTimesOut, CampaignDetail, CampaignIn, CampaignOut, CampaignRef, CampaignStats,
                      CampaignUpdate, EvergreenIn, EvergreenOut, MoveIn, NetworkRow, PillarIn, PillarOrder, PillarOut,
                      PillarUpdate, PlannerOut, PlannerPost, PostPlanUpdate, RecycleOut, ScheduleIn)

router = APIRouter(tags=["planning"])


# ---------------------------------------------------------------------------------------------- helpers
def get_campaign(ctx: Ctx, campaign_id: int) -> Campaign:
    campaign = ctx.db.get(Campaign, campaign_id)
    if not campaign or campaign.workspace_id != ctx.workspace.id:
        raise NotFound(_("Campaign not found."))
    return campaign


def get_pillar(ctx: Ctx, pillar_id: int) -> ContentPillar:
    pillar = ctx.db.get(ContentPillar, pillar_id)
    if not pillar or pillar.workspace_id != ctx.workspace.id:
        raise NotFound(_("Content pillar not found."))
    return pillar


def _check_owner(ctx: Ctx, owner_id: int | None) -> None:
    if owner_id and not ctx.db.scalar(select(Membership.id).where(Membership.workspace_id == ctx.workspace.id,
                                                                  Membership.user_id == owner_id)):
        raise NotFound(_("This person is not a member of the workspace."))


def _check_dates(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise AppError(_("The end date must be after the start date."), code="bad_dates")


def campaign_out(ctx: Ctx, campaign: Campaign, stats: dict, owners: dict | None = None) -> CampaignOut:
    tz = svc.workspace_tz(ctx.workspace)
    start, end = svc.as_day(campaign.date_start, tz), svc.as_day(campaign.date_end, tz)
    days_left = (end - svc.local_today(tz)).days if end and campaign.state != "finished" else None
    return CampaignOut(
        id=campaign.id, name=campaign.name, tagline=campaign.tagline, goal=campaign.goal, date_start=start,
        date_end=end, color=campaign.color, state=campaign.state, budget=campaign.budget,
        owner_id=campaign.owner_id, owner_name=(owners or {}).get(campaign.owner_id), auto_state=campaign.auto_state,
        archived=campaign.archived, target_posts=campaign.target_posts,
        days_left=max(days_left, 0) if days_left is not None else None, stats=CampaignStats(**stats))


def _owners(ctx: Ctx, campaigns: list[Campaign]) -> dict:
    from app.modules.auth.models import User
    ids = {c.owner_id for c in campaigns if c.owner_id}
    return {u.id: u.name for u in ctx.db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def _initial_state(campaign: Campaign, tz) -> None:
    """A new campaign whose dates already started is running (when it follows its dates)."""
    if campaign.auto_state:
        today = svc.local_today(tz)
        start, end = svc.as_day(campaign.date_start, tz), svc.as_day(campaign.date_end, tz)
        if end and end < today:
            campaign.state = "finished"
        elif start and start <= today and campaign.state == "planned":
            campaign.state = "running"


# ---------------------------------------------------------------------------------------------- campaigns
@router.get("/campaigns", response_model=list[CampaignOut])
def list_campaigns(state: str | None = None, q: str | None = None, include_archived: bool = False,
                   ctx: Ctx = Depends(workspace_ctx())):
    query = select(Campaign).where(Campaign.workspace_id == ctx.workspace.id)
    if state:
        query = query.where(Campaign.state == state)
    if not include_archived:
        query = query.where(Campaign.archived.is_(False))
    if q and q.strip():
        query = query.where(Campaign.name.ilike(f"%{q.strip()}%"))
    campaigns = ctx.db.scalars(query.order_by(Campaign.date_start.desc().nulls_last(), Campaign.id.desc())).all()
    stats = svc.campaign_stats(ctx.db, ctx.workspace.id, [c.id for c in campaigns])
    owners = _owners(ctx, campaigns)
    return [campaign_out(ctx, c, stats[c.id], owners) for c in campaigns]


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
def create_campaign(body: CampaignIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    _check_dates(body.date_start, body.date_end)
    _check_owner(ctx, body.owner_id)
    campaign = Campaign(
        workspace_id=ctx.workspace.id, name=body.name.strip(), tagline=body.tagline, goal=body.goal,
        date_start=svc.day_to_dt(body.date_start), date_end=svc.day_to_dt(body.date_end),
        color=body.color or svc.next_color(ctx.db, Campaign, ctx.workspace.id), state=body.state or "planned",
        budget=body.budget, owner_id=body.owner_id or ctx.user.id, auto_state=body.auto_state,
        target_posts=body.target_posts)
    if not body.state:
        _initial_state(campaign, svc.workspace_tz(ctx.workspace))
    ctx.db.add(campaign)
    ctx.db.flush()
    stats = svc.campaign_stats(ctx.db, ctx.workspace.id, [campaign.id])
    return campaign_out(ctx, campaign, stats[campaign.id], _owners(ctx, [campaign]))


def _networks(ctx: Ctx, campaign: Campaign) -> list[NetworkRow]:
    rows = ctx.db.execute(
        select(PostTarget.platform, func.count(func.distinct(PostTarget.post_id)),
               func.coalesce(func.sum(PostTarget.impressions), 0), func.coalesce(func.sum(PostTarget.reach), 0),
               func.coalesce(func.sum(PostTarget.engagements), 0))
        .join(Post, Post.id == PostTarget.post_id)
        .where(PostTarget.workspace_id == ctx.workspace.id, PostTarget.state == "posted",
               Post.campaign_id == campaign.id)
        .group_by(PostTarget.platform)).all()
    from app.modules.links import service as links
    results = links.results_by(ctx.db, ctx.workspace.id, "platform", campaign_ids=[campaign.id])
    out = []
    for platform, posts, impressions, reach, engagements in rows:
        base = impressions or reach
        extra = results.get(platform) or {}
        out.append(NetworkRow(platform=platform, posts=posts, impressions=impressions, engagements=engagements,
                              engagement_rate=round(100.0 * engagements / base, 2) if base else 0.0,
                              clicks=extra.get("clicks", 0), revenue=extra.get("revenue", 0.0)))
    seen = {row.platform for row in out}
    for platform, extra in results.items():
        if platform not in seen and platform:
            out.append(NetworkRow(platform=platform, posts=0, impressions=0, engagements=0, engagement_rate=0.0,
                                  clicks=extra.get("clicks", 0), revenue=extra.get("revenue", 0.0)))
    return sorted(out, key=lambda r: (-r.engagements, -r.clicks))


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetail)
def campaign_detail(campaign_id: int, ctx: Ctx = Depends(workspace_ctx())):
    campaign = get_campaign(ctx, campaign_id)
    stats = svc.campaign_stats(ctx.db, ctx.workspace.id, [campaign.id])[campaign.id]
    posts = ctx.db.scalars(select(Post).where(Post.workspace_id == ctx.workspace.id, Post.campaign_id == campaign.id)
                           .options(selectinload(Post.accounts), selectinload(Post.media_links))
                           .order_by(func.coalesce(Post.published_at, Post.scheduled_at, Post.planned_date,
                                                   Post.created_at).desc()).limit(300)).unique().all()
    base = campaign_out(ctx, campaign, stats, _owners(ctx, [campaign]))
    return CampaignDetail(**base.model_dump(), networks=_networks(ctx, campaign),
                          posts=[PlannerPost(**i) for i in svc.items_for(ctx.db, ctx.workspace, list(posts))],
                          currency=ctx.workspace.currency)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
def update_campaign(campaign_id: int, body: CampaignUpdate, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    campaign = get_campaign(ctx, campaign_id)
    tz = svc.workspace_tz(ctx.workspace)
    data = body.model_dump(exclude_unset=True)
    start = data["date_start"] if "date_start" in data else svc.as_day(campaign.date_start, tz)
    end = data["date_end"] if "date_end" in data else svc.as_day(campaign.date_end, tz)
    _check_dates(start, end)
    if "owner_id" in data:
        _check_owner(ctx, data["owner_id"])
    for key, value in data.items():
        if key in ("date_start", "date_end"):
            value = svc.day_to_dt(value)
        elif key == "name":
            value = value.strip()
        setattr(campaign, key, value)
    if "state" in data:
        campaign.auto_state = data.get("auto_state", False)  # a manual state wins over the dates
    elif campaign.auto_state and {"date_start", "date_end", "auto_state"} & set(data):
        campaign.state = "planned"  # follow the (new) dates
        _initial_state(campaign, tz)
    ctx.db.flush()
    stats = svc.campaign_stats(ctx.db, ctx.workspace.id, [campaign.id])
    return campaign_out(ctx, campaign, stats[campaign.id], _owners(ctx, [campaign]))


@router.delete("/campaigns/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    campaign = get_campaign(ctx, campaign_id)
    ctx.db.delete(campaign)  # posts keep existing (campaign_id is set to NULL)
    ctx.db.flush()
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------- pillars
def _pillar_out(ctx: Ctx, pillar_id: int) -> PillarOut:
    row = next(r for r in svc.pillar_rows(ctx.db, ctx.workspace.id) if r["id"] == pillar_id)
    return PillarOut(**row)


@router.get("/pillars", response_model=list[PillarOut])
def list_pillars(active_only: bool = False, ctx: Ctx = Depends(workspace_ctx())):
    return [PillarOut(**row) for row in svc.pillar_rows(ctx.db, ctx.workspace.id, include_inactive=not active_only)]


@router.post("/pillars", response_model=PillarOut, status_code=201)
def create_pillar(body: PillarIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    last = ctx.db.scalar(select(func.max(ContentPillar.position)).where(
        ContentPillar.workspace_id == ctx.workspace.id)) or 0
    pillar = ContentPillar(workspace_id=ctx.workspace.id, name=body.name.strip(), description=body.description,
                           color=body.color or svc.next_color(ctx.db, ContentPillar, ctx.workspace.id),
                           target_share=body.target_share, active=body.active, position=last + 10)
    ctx.db.add(pillar)
    ctx.db.flush()
    return _pillar_out(ctx, pillar.id)


@router.patch("/pillars/{pillar_id}", response_model=PillarOut)
def update_pillar(pillar_id: int, body: PillarUpdate, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    pillar = get_pillar(ctx, pillar_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(pillar, key, value.strip() if key == "name" else value)
    ctx.db.flush()
    return _pillar_out(ctx, pillar.id)


@router.put("/pillars/order", response_model=list[PillarOut])
def reorder_pillars(body: PillarOrder, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    pillars = {p.id: p for p in ctx.db.scalars(select(ContentPillar).where(
        ContentPillar.workspace_id == ctx.workspace.id))}
    for index, pillar_id in enumerate(body.ids):
        if pillar_id not in pillars:
            raise NotFound(_("Content pillar not found."))
        pillars[pillar_id].position = (index + 1) * 10
    ctx.db.flush()
    return [PillarOut(**row) for row in svc.pillar_rows(ctx.db, ctx.workspace.id)]


@router.delete("/pillars/{pillar_id}", status_code=204)
def delete_pillar(pillar_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    ctx.db.delete(get_pillar(ctx, pillar_id))
    ctx.db.flush()
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------- planner
@router.get("/planner", response_model=PlannerOut)
def planner(start: date, end: date, account_id: int | None = None, campaign_id: int | None = None,
            pillar_id: int | None = None, state: str | None = None, platform: str | None = None,
            ctx: Ctx = Depends(workspace_ctx())):
    if end <= start or (end - start).days > 120:
        raise AppError(_("Choose a period of at most 120 days."), code="bad_period")
    accounts = ctx.db.scalars(select(SocialAccount).where(
        SocialAccount.workspace_id == ctx.workspace.id, SocialAccount.platform != "whatsapp",
        SocialAccount.active.is_(True)).order_by(SocialAccount.platform, SocialAccount.name)).all()
    if account_id and account_id not in {a.id for a in accounts}:
        raise NotFound(_("Account not found."))
    if campaign_id:
        get_campaign(ctx, campaign_id)
    if pillar_id:
        get_pillar(ctx, pillar_id)
    selected = next((a for a in accounts if a.id == account_id), None)
    platforms = [selected.platform] if selected else ([platform] if platform else sorted({a.platform for a in accounts}))
    campaigns = ctx.db.scalars(select(Campaign).where(Campaign.workspace_id == ctx.workspace.id,
                                                      Campaign.archived.is_(False))
                               .order_by(Campaign.date_start.desc().nulls_last(), Campaign.id.desc())).all()
    tz = svc.workspace_tz(ctx.workspace)
    filters = dict(account_id=account_id, campaign_id=campaign_id, pillar_id=pillar_id, state=state,
                   platform=platform)
    return PlannerOut(
        start=start, end=end, today=svc.local_today(tz), timezone=ctx.workspace.timezone,
        posts=[PlannerPost(**i) for i in svc.planner_posts(ctx.db, ctx.workspace, start, end, **filters)],
        unplanned=[PlannerPost(**i) for i in svc.unplanned_posts(ctx.db, ctx.workspace)],
        best=svc.best_by_weekday(ctx.db, ctx.workspace, platforms),
        best_slots=svc.best_slots(ctx.db, ctx.workspace, platforms, count=3),
        accounts=[{"id": a.id, "name": a.name, "platform": a.platform, "avatar_url": a.avatar_url} for a in accounts],
        campaigns=[CampaignRef(id=c.id, name=c.name, color=c.color, state=c.state,
                               date_start=svc.as_day(c.date_start, tz), date_end=svc.as_day(c.date_end, tz))
                   for c in campaigns],
        pillars=[PillarOut(**row) for row in svc.pillar_rows(ctx.db, ctx.workspace.id, include_inactive=False)],
    )


@router.get("/planner/best-times", response_model=BestTimesOut)
def best_times(platforms: list[str] = Query(default=[]), ctx: Ctx = Depends(workspace_ctx())):
    return BestTimesOut(by_weekday=svc.best_by_weekday(ctx.db, ctx.workspace, platforms or None),
                        slots=svc.best_slots(ctx.db, ctx.workspace, platforms or None, count=5))


@router.post("/planner/posts/{post_id}/move", response_model=PlannerPost)
def move(post_id: int, body: MoveIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    post = svc.get_post(ctx.db, ctx.workspace.id, post_id)
    return svc.move_post(ctx.db, ctx.workspace, post, body.day, body.time, ctx.user.id)


@router.post("/planner/posts/{post_id}/schedule", response_model=PlannerPost)
def schedule(post_id: int, body: ScheduleIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    post = svc.get_post(ctx.db, ctx.workspace.id, post_id)
    return svc.schedule_post(ctx.db, ctx.workspace, post, body.day, body.time, ctx.user.id)


@router.post("/planner/posts/{post_id}/unplan", response_model=PlannerPost)
def unplan(post_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    post = svc.get_post(ctx.db, ctx.workspace.id, post_id)
    return svc.unplan_post(ctx.db, ctx.workspace, post)


@router.patch("/planner/posts/{post_id}", response_model=PlannerPost)
def set_plan(post_id: int, body: PostPlanUpdate, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Put a post in a campaign / content pillar."""
    post = svc.get_post(ctx.db, ctx.workspace.id, post_id)
    if body.campaign_id:
        post.campaign_id = get_campaign(ctx, body.campaign_id).id
    elif body.clear_campaign:
        post.campaign_id = None
    if body.pillar_id:
        post.pillar_id = get_pillar(ctx, body.pillar_id).id
    elif body.clear_pillar:
        post.pillar_id = None
    ctx.db.flush()
    return svc.items_for(ctx.db, ctx.workspace, [post])[0]


# ---------------------------------------------------------------------------------------------- evergreen
def _evergreen_out(ctx: Ctx, posts: list[Post]) -> list[EvergreenOut]:
    items = {i["id"]: i for i in svc.items_for(ctx.db, ctx.workspace, posts)}
    waiting = svc.open_copies(ctx.db, [p.id for p in posts])
    tz = svc.workspace_tz(ctx.workspace)
    return [EvergreenOut(post=PlannerPost(**items[p.id]), evergreen=p.evergreen,
                         interval_days=p.recycle_interval_days or 30, until=svc.as_day(p.recycle_until, tz),
                         rewrite=p.recycle_rewrite, recycle_count=p.recycle_count or 0,
                         last_recycled_at=svc.aware(p.last_recycled_at), next_recycle_at=svc.next_recycle_at(p),
                         waiting_copy=p.id in waiting) for p in posts]


@router.get("/evergreen", response_model=list[EvergreenOut])
def list_evergreen(ctx: Ctx = Depends(workspace_ctx())):
    posts = ctx.db.scalars(select(Post).where(Post.workspace_id == ctx.workspace.id, Post.evergreen.is_(True))
                           .options(selectinload(Post.accounts), selectinload(Post.media_links))
                           .order_by(Post.published_at.desc().nulls_last(), Post.id.desc())).unique().all()
    return _evergreen_out(ctx, list(posts))


@router.put("/evergreen/{post_id}", response_model=EvergreenOut)
def set_evergreen(post_id: int, body: EvergreenIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    post = svc.get_post(ctx.db, ctx.workspace.id, post_id)
    if post.recycled_from_id and body.evergreen:
        raise AppError(_("This post is already a repost: make the original post evergreen."), code="is_copy")
    post.evergreen = body.evergreen
    post.recycle_interval_days = body.interval_days
    post.recycle_until = svc.day_to_dt(body.until)
    post.recycle_rewrite = body.rewrite
    ctx.db.flush()
    return _evergreen_out(ctx, [post])[0]


@router.post("/evergreen/{post_id}/repost", response_model=RecycleOut)
def repost_now(post_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    post = svc.get_post(ctx.db, ctx.workspace.id, post_id)
    if post.state not in svc.PUBLISHED:
        raise AppError(_("Only published posts can be reposted."), code="not_published")
    if svc.open_copies(ctx.db, [post.id]):
        raise AppError(_("A repost of this post is already waiting to go out."), code="copy_waiting")
    copy = svc.recycle(ctx.db, post)
    return RecycleOut(post_id=post.id, copy_id=copy.id, state=copy.state)

