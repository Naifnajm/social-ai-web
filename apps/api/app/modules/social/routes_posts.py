"""/api/posts, /api/studio, /api/approvals — composer, posts list, publishing, scheduling and approvals."""
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.core.db import utcnow
from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.modules.auth.models import User
from app.modules.files.router import media_out
from app.modules.workspaces.models import Role
from app.modules.workspaces.settings import set_setting

from . import publishing
from .analytics import next_best_slots, workspace_tz
from .models import PUBLISH_PLATFORMS, POST_STATES, Post, PostTarget, SocialAccount, post_accounts
from .platforms import STORY_PLATFORMS, platform_rules
from .routes_accounts import account_out
from .schemas import (ApprovalSettings, BestSlot, ChangesIn, ComposeIn, PostIn, PostOut, PostPage, Problem,
                      StudioKpis, StudioOut, SubmitIn, TargetOut, ValidationOut)

router = APIRouter(tags=["posts"])
TOTAL_KEYS = ("impressions", "reach", "likes", "comments", "shares", "saves", "clicks", "video_views", "engagements")


def _names(ctx: Ctx, ids) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(ctx.db.execute(select(User.id, User.name).where(User.id.in_(ids))).all())


def post_out(ctx: Ctx, post: Post, names: dict[int, str] | None = None) -> PostOut:
    db = ctx.db
    names = names if names is not None else _names(ctx, [post.author_id, post.approval_requested_by_id])
    accounts = {a.id: a for a in post.accounts}
    targets = []
    for target in sorted(post.targets, key=lambda t: t.id):
        out = TargetOut.model_validate(target)
        account = accounts.get(target.account_id) or target.account
        out.account_name = account.name if account else ""
        out.account_avatar = account.avatar_url if account else None
        targets.append(out)
    posted = [t for t in post.targets if t.state == "posted"]
    totals = {k: float(sum(getattr(t, k) or 0 for t in posted)) for k in TOTAL_KEYS}
    base = totals["impressions"] or totals["reach"]
    totals["engagement_rate"] = round(100.0 * totals["engagements"] / base, 2) if base else 0.0
    feed = [link for link in post.media_links if link.role != "story"]
    stories = [link for link in post.media_links if link.role == "story"]
    media_rows = {m.id: m for m in publishing._media_rows(db, post.workspace_id,
                                                           [link.media_id for link in post.media_links])}
    return PostOut(
        id=post.id, name=post.name, content=post.content or "", variants=post.variants or {}, state=post.state,
        publish_as=post.publish_as or "feed", scheduled_at=post.scheduled_at, published_at=post.published_at,
        planned_date=post.planned_date, created_at=post.created_at, updated_at=post.updated_at,
        author_id=post.author_id, author_name=names.get(post.author_id),
        accounts=[{"id": a.id, "name": a.name, "platform": a.platform, "avatar_url": a.avatar_url,
                   "username": a.username} for a in post.accounts],
        account_ids=[a.id for a in post.accounts], platforms=publishing.post_platforms(post),
        media=[media_out(media_rows[link.media_id]) for link in feed if link.media_id in media_rows],
        story_media=[media_out(media_rows[link.media_id]) for link in stories if link.media_id in media_rows],
        platform_media=post.platform_media or {}, campaign_id=post.campaign_id, pillar_id=post.pillar_id,
        ai_brief=post.ai_brief, source_ref=post.source_ref, requested_action=post.requested_action,
        approval_requested_by_id=post.approval_requested_by_id,
        approval_requested_by_name=names.get(post.approval_requested_by_id),
        approval_requested_at=post.approval_requested_at, approved_by_id=post.approved_by_id,
        approved_at=post.approved_at, approval_note=post.approval_note, targets=targets,
        can_edit=post.state in publishing.EDITABLE_STATES, can_retry=post.state in ("failed", "partial"),
        totals=totals,
    )


def posts_out(ctx: Ctx, posts: list[Post]) -> list[PostOut]:
    names = _names(ctx, [i for p in posts for i in (p.author_id, p.approval_requested_by_id)])
    return [post_out(ctx, p, names) for p in posts]


def get_post(ctx: Ctx, post_id: int) -> Post:
    post = ctx.db.get(Post, post_id)
    if not post or post.workspace_id != ctx.workspace.id:
        raise NotFound(_("Post not found."))
    return post


# ------------------------------------------------------------------ studio bootstrap
@router.get("/studio", response_model=StudioOut)
def studio(ctx: Ctx = Depends(workspace_ctx())):
    """Everything the composer needs at start: publishable accounts, network rules, approval flags, KPIs."""
    db, ws = ctx.db, ctx.workspace.id
    accounts = db.scalars(select(SocialAccount).where(SocialAccount.workspace_id == ws,
                                                      SocialAccount.platform.in_(PUBLISH_PLATFORMS),
                                                      SocialAccount.active.is_(True))
                          .order_by(SocialAccount.platform, SocialAccount.name)).all()
    since = utcnow() - timedelta(days=30)

    def count(*where):
        return db.scalar(select(func.count(Post.id)).where(Post.workspace_id == ws, *where)) or 0

    published = db.scalar(select(func.count(PostTarget.id)).where(PostTarget.workspace_id == ws,
                                                                  PostTarget.state == "posted",
                                                                  PostTarget.published_at >= since)) or 0
    recent = db.scalars(select(Post).where(Post.workspace_id == ws).order_by(Post.updated_at.desc()).limit(8)).all()
    is_approver = ctx.can(Role.approver)
    enabled = publishing.approvals_enabled(db, ws)
    return StudioOut(
        accounts=[account_out(a) for a in accounts], rules=platform_rules(), story_platforms=list(STORY_PLATFORMS),
        needs_approval=enabled and not is_approver, is_approver=is_approver, approvals_enabled=enabled,
        kpis=StudioKpis(published=published, scheduled=count(Post.state == "scheduled"),
                        failed=count(Post.state.in_(("failed", "partial"))),
                        to_approve=count(Post.state == "to_approve"),
                        accounts=sum(1 for a in accounts if a.state == "connected")),
        recent_posts=posts_out(ctx, list(recent)), timezone=str(workspace_tz(db, ws)), can_connect=ctx.can(Role.admin),
    )


# ------------------------------------------------------------------ posts
@router.get("/posts", response_model=PostPage)
def list_posts(state: list[str] = Query(default=[]), platform: str | None = None, account_id: int | None = None,
               campaign_id: int | None = None, q: str | None = None, limit: int = 30, offset: int = 0,
               ctx: Ctx = Depends(workspace_ctx())):
    query = select(Post).where(Post.workspace_id == ctx.workspace.id)
    states = [s for s in state if s in POST_STATES]
    if states:
        query = query.where(Post.state.in_(states))
    if platform:
        query = query.where(Post.id.in_(select(post_accounts.c.post_id).join(
            SocialAccount, SocialAccount.id == post_accounts.c.account_id).where(SocialAccount.platform == platform)))
    if account_id:
        query = query.where(Post.id.in_(select(post_accounts.c.post_id).where(post_accounts.c.account_id == account_id)))
    if campaign_id:
        query = query.where(Post.campaign_id == campaign_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Post.content.ilike(like), Post.name.ilike(like)))
    total = ctx.db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_key = func.coalesce(Post.published_at, Post.scheduled_at, Post.updated_at)
    rows = ctx.db.scalars(query.order_by(sort_key.desc(), Post.id.desc())
                          .limit(max(1, min(limit, 100))).offset(max(0, offset))).all()
    return PostPage(items=posts_out(ctx, list(rows)), total=total)


@router.post("/posts", response_model=PostOut, status_code=201)
def create(body: PostIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    from .service import create_post

    data = body.model_dump(exclude_unset=True)
    post = create_post(ctx.db, ctx.workspace.id, ctx.user.id, **{k: v for k, v in data.items()
                                                                if k not in ("scheduled_at",)})
    if data.get("scheduled_at"):
        publishing.apply_fields(ctx.db, post, {"scheduled_at": data["scheduled_at"]})
    return post_out(ctx, post)


@router.post("/posts/validate", response_model=ValidationOut)
def validate(body: ComposeIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Check the composer against each network's rules without saving anything."""
    savepoint = ctx.db.begin_nested()
    try:
        post = _compose_post(ctx, body)
        found = publishing.problems(ctx.db, post)
    finally:
        savepoint.rollback()
    return ValidationOut(ok=not found, problems=[Problem(**p) for p in found])


@router.get("/posts/rules")
def rules(ctx: Ctx = Depends(workspace_ctx())) -> dict[str, dict]:
    return platform_rules()


@router.get("/posts/best-slots", response_model=list[BestSlot])
def best_slots(platforms: list[str] = Query(default=[]), count: int = 3, ctx: Ctx = Depends(workspace_ctx())):
    return next_best_slots(ctx.db, ctx.workspace.id, platforms, max(1, min(count, 10)))


def _compose_post(ctx: Ctx, body: ComposeIn) -> Post:
    data = body.model_dump(exclude_unset=True, exclude={"post_id", "action", "when"})
    if body.post_id:
        post = get_post(ctx, body.post_id)
        return publishing.update_post(ctx.db, post, ctx.user.id, data)
    from .service import create_post

    post = create_post(ctx.db, ctx.workspace.id, ctx.user.id,
                       **{k: v for k, v in data.items() if k not in ("scheduled_at",)})
    if data.get("scheduled_at"):
        publishing.apply_fields(ctx.db, post, {"scheduled_at": data["scheduled_at"]})
    return post


@router.post("/posts/compose", response_model=PostOut)
def compose(body: ComposeIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Save the composer and draft / publish / schedule / best_time it in one call (Studio and mobile)."""
    post = _compose_post(ctx, body)
    if body.action != "draft":  # "Save draft" keeps a scheduled / waiting post as it is
        publishing.submit(ctx.db, post, ctx.user.id, action=body.action, when=body.when or body.scheduled_at)
    ctx.db.refresh(post)
    return post_out(ctx, post)


@router.get("/posts/{post_id}", response_model=PostOut)
def one(post_id: int, ctx: Ctx = Depends(workspace_ctx())):
    return post_out(ctx, get_post(ctx, post_id))


@router.patch("/posts/{post_id}", response_model=PostOut)
def update(post_id: int, body: PostIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    post = publishing.update_post(ctx.db, get_post(ctx, post_id), ctx.user.id, body.model_dump(exclude_unset=True))
    return post_out(ctx, post)


@router.delete("/posts/{post_id}", status_code=204)
def delete(post_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    post = get_post(ctx, post_id)
    if post.state not in publishing.DELETABLE_STATES or any(t.state in ("posted", "sending") for t in post.targets):
        raise AppError(_("A published post cannot be deleted here; remove it on the network."), code="not_deletable")
    ctx.db.delete(post)


@router.post("/posts/{post_id}/submit", response_model=PostOut)
def submit(post_id: int, body: SubmitIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    post = publishing.submit(ctx.db, get_post(ctx, post_id), ctx.user.id, action=body.action, when=body.when)
    ctx.db.refresh(post)
    return post_out(ctx, post)


@router.post("/posts/{post_id}/retry", response_model=PostOut)
def retry(post_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Send again only the networks (or stories) that failed."""
    post = publishing.retry(ctx.db, get_post(ctx, post_id), ctx.user.id)
    ctx.db.refresh(post)
    return post_out(ctx, post)


@router.post("/posts/{post_id}/duplicate", response_model=PostOut, status_code=201)
def duplicate(post_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    from .service import create_post

    source = get_post(ctx, post_id)
    post = create_post(ctx.db, ctx.workspace.id, ctx.user.id, content=source.content or "",
                       media_ids=[link.media_id for link in source.media_links if link.role != "story"],
                       story_media_ids=[link.media_id for link in source.media_links if link.role == "story"],
                       account_ids=[a.id for a in source.accounts if a.active], publish_as=source.publish_as,
                       platform_media=source.platform_media, variants=source.variants,
                       campaign_id=source.campaign_id, pillar_id=source.pillar_id)
    return post_out(ctx, post)


# ------------------------------------------------------------------ approvals
@router.get("/approvals", response_model=list[PostOut])
def approval_queue(ctx: Ctx = Depends(workspace_ctx(Role.approver))):
    rows = ctx.db.scalars(select(Post).where(Post.workspace_id == ctx.workspace.id, Post.state == "to_approve")
                          .order_by(Post.approval_requested_at.asc().nulls_last(), Post.id)).all()
    return posts_out(ctx, list(rows))


@router.get("/approvals/settings", response_model=ApprovalSettings)
def approval_settings(ctx: Ctx = Depends(workspace_ctx())):
    return ApprovalSettings(required=publishing.approvals_enabled(ctx.db, ctx.workspace.id))


@router.put("/approvals/settings", response_model=ApprovalSettings)
def save_approval_settings(body: ApprovalSettings, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    set_setting(ctx.db, ctx.workspace.id, publishing.APPROVALS_SETTING, body.required)
    return body


@router.post("/posts/{post_id}/approve", response_model=PostOut)
def approve(post_id: int, ctx: Ctx = Depends(workspace_ctx(Role.approver))):
    post = publishing.approve(ctx.db, get_post(ctx, post_id), ctx.user.id)
    ctx.db.refresh(post)
    return post_out(ctx, post)


@router.post("/posts/{post_id}/request-changes", response_model=PostOut)
def request_changes(post_id: int, body: ChangesIn, ctx: Ctx = Depends(workspace_ctx(Role.approver))):
    post = publishing.request_changes(ctx.db, get_post(ctx, post_id), ctx.user.id, body.note)
    return post_out(ctx, post)
