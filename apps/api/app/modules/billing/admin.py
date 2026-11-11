"""Platform admin (superadmins only): workspaces with plan/status/usage, support view (no impersonation),
suspend/reactivate, extend trial, manual plan changes, platform stats and platform-wide settings."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import superadmin
from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.core.models import ApiLog
from app.modules.auth.models import User
from app.modules.workspaces.models import Membership, Role, Workspace

from . import limits, platform, service
from .config import billing_settings
from .models import BillingEvent, Subscription
from .plans import PLANS, RESOURCES, get_plan
from .schemas import (
    AdminErrorOut,
    AdminEventOut,
    AdminMemberOut,
    AdminPlanIn,
    AdminWorkspaceDetail,
    AdminWorkspacePage,
    AdminWorkspaceRow,
    DayCount,
    ExtendTrialIn,
    PlatformSettingsIn,
    PlatformSettingsOut,
    PlatformStatsOut,
    SuspendIn,
    UsageItem,
)

router = APIRouter(prefix="/admin", tags=["platform admin"])


def _workspace(db: Session, workspace_id: int) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFound(_("Workspace not found."))
    return workspace


def _owner_email(db: Session, workspace_id: int) -> str | None:
    return db.scalar(select(User.email).join(Membership, Membership.user_id == User.id).where(
        Membership.workspace_id == workspace_id, Membership.role == Role.owner).order_by(Membership.id).limit(1))


def _row(db: Session, workspace: Workspace) -> AdminWorkspaceRow:
    sub = service.ensure_subscription(db, workspace)
    state = service.billing_state(db, workspace.id)
    return AdminWorkspaceRow(
        id=workspace.id, name=workspace.name, slug=workspace.slug, status=workspace.status, plan=sub.plan_code,
        subscription_status=sub.status, blocked=state.blocked, interval=sub.interval,
        trial_ends_at=state.trial_ends_at, current_period_end=state.current_period_end, provider=sub.provider,
        owner_email=_owner_email(db, workspace.id),
        members=db.scalar(select(func.count()).select_from(Membership).where(
            Membership.workspace_id == workspace.id)) or 0,
        social_accounts=limits.count_social_accounts(db, workspace.id),
        posts_month=limits.count_posts_month(db, workspace.id), created_at=workspace.created_at,
    )


def _audit(db: Session, workspace: Workspace, admin: User, type_: str, summary: str, payload: dict | None = None):
    service.log_event(db, "admin", f"admin-{workspace.id}-{type_}-{service.utcnow().timestamp()}", type_,
                      workspace.id, summary=summary, payload=payload, actor_id=admin.id)


# ---------------------------------------------------------------- stats
@router.get("/stats", response_model=PlatformStatsOut)
def stats(admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    now = service.utcnow()
    workspaces = db.scalars(select(Workspace)).all()
    subs = {s.workspace_id: s for s in db.scalars(select(Subscription)).all()}
    by_plan: dict[str, int] = {code: 0 for code in PLANS}
    paying = trialing = past_due = active = suspended = 0
    mrr = 0.0
    for workspace in workspaces:
        sub = subs.get(workspace.id)
        state = service.billing_state(db, workspace.id)
        by_plan[state.plan.code] = by_plan.get(state.plan.code, 0) + 1
        if workspace.status != "active":
            suspended += 1
        if not state.blocked:
            active += 1
        if state.status == "trialing" and not state.blocked:
            trialing += 1
        if state.status == "past_due":
            past_due += 1
        if sub and state.status in ("active", "past_due") and state.plan.is_paid and not state.blocked:
            paying += 1
            mrr += state.plan.monthly_value(sub.interval)
    since30 = now - timedelta(days=30)
    signup_days = db.execute(
        # Bucket by UTC day: date_trunc alone uses the database session's time zone, which shifted late signups.
        select(func.date_trunc("day", func.timezone("UTC", Workspace.created_at)).label("d"), func.count())
        .where(Workspace.created_at >= since30).group_by("d").order_by("d")).all()
    counts = {d.date().isoformat(): c for d, c in signup_days}
    series = [DayCount(day=(now - timedelta(days=i)).date().isoformat(),
                       count=counts.get((now - timedelta(days=i)).date().isoformat(), 0)) for i in range(29, -1, -1)]
    return PlatformStatsOut(
        workspaces_total=len(workspaces), workspaces_active=active, workspaces_suspended=suspended,
        users_total=db.scalar(select(func.count()).select_from(User)) or 0,
        signups_7d=sum(1 for w in workspaces if service._aware(w.created_at) >= now - timedelta(days=7)),
        signups_30d=sum(1 for w in workspaces if service._aware(w.created_at) >= since30),
        signups_by_day=series, paying=paying, trialing=trialing, past_due=past_due,
        mrr_usd=round(mrr, 2), arr_usd=round(mrr * 12, 2), by_plan=by_plan,
    )


# ---------------------------------------------------------------- workspaces
@router.get("/workspaces", response_model=AdminWorkspacePage)
def list_workspaces(q: str = "", plan: str = "", status: str = "", page: int = Query(1, ge=1),
                    page_size: int = Query(25, ge=1, le=100), admin: User = Depends(superadmin),
                    db: Session = Depends(get_db)):
    query = select(Workspace).outerjoin(Subscription, Subscription.workspace_id == Workspace.id)
    if q.strip():
        term = f"%{q.strip().lower()}%"
        owners = select(Membership.workspace_id).join(User, User.id == Membership.user_id).where(
            func.lower(User.email).like(term))
        query = query.where(or_(func.lower(Workspace.name).like(term), func.lower(Workspace.slug).like(term),
                                Workspace.id.in_(owners)))
    if plan:
        query = query.where(func.coalesce(Subscription.plan_code, Workspace.plan_code) == plan)
    if status == "suspended":
        query = query.where(Workspace.status != "active")
    elif status:
        query = query.where(Subscription.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Workspace.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return AdminWorkspacePage(items=[_row(db, w) for w in rows], total=total, page=page, page_size=page_size)


@router.get("/workspaces/{workspace_id}", response_model=AdminWorkspaceDetail)
def workspace_detail(workspace_id: int, admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    """Support view: everything needed to help a customer, without signing in as them."""
    workspace = _workspace(db, workspace_id)
    sub = service.ensure_subscription(db, workspace)
    state = service.billing_state(db, workspace.id)
    members = db.execute(select(Membership, User).join(User, User.id == Membership.user_id)
                         .where(Membership.workspace_id == workspace.id).order_by(Membership.id)).all()
    events = db.scalars(select(BillingEvent).where(BillingEvent.workspace_id == workspace.id)
                        .order_by(BillingEvent.id.desc()).limit(30)).all()
    errors = db.scalars(select(ApiLog).where(ApiLog.workspace_id == workspace.id, ApiLog.error.is_not(None))
                        .order_by(ApiLog.id.desc()).limit(20)).all()
    return AdminWorkspaceDetail(
        workspace=_row(db, workspace), locale=workspace.locale, timezone=workspace.timezone,
        currency=workspace.currency, note=sub.note, limit_overrides=sub.limit_overrides,
        usage={k: UsageItem(**v) for k, v in limits.usage(db, workspace.id, state).items()},
        features=list(state.plan.features),
        members=[AdminMemberOut(user_id=u.id, name=u.name, email=u.email, role=m.role, last_login_at=u.last_login_at,
                                is_active=u.is_active) for m, u in members],
        events=[AdminEventOut(id=e.id, provider=e.provider, type=e.type, summary=e.summary, created_at=e.created_at)
                for e in events],
        recent_errors=[AdminErrorOut(id=e.id, service=e.service, operation=e.operation, status_code=e.status_code,
                                     error=(e.error or "")[:500], created_at=e.created_at) for e in errors],
        provider_customer_id=sub.provider_customer_id, provider_subscription_id=sub.provider_subscription_id,
    )


@router.post("/workspaces/{workspace_id}/suspend", response_model=AdminWorkspaceRow)
def suspend(workspace_id: int, data: SuspendIn, admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    workspace = _workspace(db, workspace_id)
    workspace.status = "suspended"
    _audit(db, workspace, admin, "admin.suspend", data.reason or "suspended")
    return _row(db, workspace)


@router.post("/workspaces/{workspace_id}/reactivate", response_model=AdminWorkspaceRow)
def reactivate(workspace_id: int, admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    workspace = _workspace(db, workspace_id)
    workspace.status = "active"
    _audit(db, workspace, admin, "admin.reactivate", "reactivated")
    return _row(db, workspace)


@router.post("/workspaces/{workspace_id}/extend-trial", response_model=AdminWorkspaceRow)
def extend_trial(workspace_id: int, data: ExtendTrialIn, admin: User = Depends(superadmin),
                 db: Session = Depends(get_db)):
    workspace = _workspace(db, workspace_id)
    sub = service.ensure_subscription(db, workspace)
    if sub.status in ("active", "past_due") and get_plan(sub.plan_code).code != "trial":
        raise AppError(_("This workspace has a paid plan; change the plan instead."), code="has_paid_plan")
    service.extend_trial(db, sub, data.days)
    _audit(db, workspace, admin, "admin.extend_trial", f"+{data.days} days",
           {"trial_ends_at": sub.trial_ends_at.isoformat()})
    return _row(db, workspace)


@router.post("/workspaces/{workspace_id}/plan", response_model=AdminWorkspaceRow)
def change_plan(workspace_id: int, data: AdminPlanIn, admin: User = Depends(superadmin),
                db: Session = Depends(get_db)):
    """Manual plan (invoice/bank transfer customers, enterprise deals, goodwill). A plan billed by Stripe should
    be changed in Stripe (the next webhook would overwrite a manual change)."""
    workspace = _workspace(db, workspace_id)
    sub = service.ensure_subscription(db, workspace)
    status = "trialing" if data.plan == "trial" else data.status
    service.apply_plan(db, sub, data.plan, status=status, interval=data.interval, period_end=data.period_end)
    if data.plan == "trial" and not sub.trial_ends_at:
        sub.trial_ends_at = service.utcnow() + timedelta(days=service.trial_days(db))
    if sub.provider in ("none",) and data.plan != "trial":
        sub.provider = "manual"
    if data.limit_overrides is not None:
        sub.limit_overrides = {k: v for k, v in data.limit_overrides.items() if k in RESOURCES} or None
    if data.note is not None:
        sub.note = data.note or None
    _audit(db, workspace, admin, "admin.plan", f"{data.plan} / {status}",
           {"plan": data.plan, "status": status, "interval": data.interval,
            "limit_overrides": sub.limit_overrides})
    return _row(db, workspace)


# ---------------------------------------------------------------- platform settings
def _settings_out(db: Session) -> PlatformSettingsOut:
    return PlatformSettingsOut(
        values=platform.all_settings(db), schema=platform.SETTINGS_SCHEMA,
        stripe_configured=bool(billing_settings().stripe_secret_key),
        stripe_webhook_configured=bool(billing_settings().stripe_webhook_secret),
        webhook_url=f"{settings.public_api_url.rstrip('/')}/billing/webhooks/stripe",
    )


@router.get("/settings", response_model=PlatformSettingsOut)
def read_settings(admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    return _settings_out(db)


@router.put("/settings", response_model=PlatformSettingsOut)
def write_settings(data: PlatformSettingsIn, admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    for key, value in data.values.items():
        kind = platform.SETTINGS_SCHEMA.get(key)
        if kind is None:
            raise AppError(_("Unknown setting: {key}", key=key), code="bad_setting")
        if kind == "secret":
            if value is None or isinstance(value, bool):
                continue  # untouched (the UI shows secrets as configured/not configured)
            platform.set_secret(db, key, str(value).strip(), admin.id)
            continue
        if value in ("", None):
            platform.set_setting(db, key, None, admin.id)
            continue
        try:
            if kind == "int":
                value = int(value)
            elif kind == "bool":
                value = bool(value)
            elif kind == "dict":
                if not isinstance(value, dict):
                    raise ValueError
                value = {str(k): str(v).strip() for k, v in value.items() if v}
            else:
                value = str(value).strip()
        except (TypeError, ValueError):
            raise AppError(_("Invalid value for {key}.", key=key), code="bad_setting") from None
        platform.set_setting(db, key, value, admin.id)
    return _settings_out(db)


# ------------------------------------------------------------------ users
from pydantic import BaseModel  # noqa: E402


class AdminUserOut(BaseModel):
    id: int
    name: str
    email: str
    username: str | None = None
    is_active: bool
    is_superadmin: bool
    last_login_at: datetime | None = None
    created_at: datetime
    workspaces: list[str] = []


class AdminUserPage(BaseModel):
    items: list[AdminUserOut]
    total: int
    page: int
    page_size: int


class FlagIn(BaseModel):
    value: bool


def _user_out(db: Session, user: User) -> AdminUserOut:
    names = db.scalars(select(Workspace.name).join(Membership, Membership.workspace_id == Workspace.id)
                       .where(Membership.user_id == user.id).order_by(Workspace.name)).all()
    return AdminUserOut(id=user.id, name=user.name, email=user.email, username=user.username,
                        is_active=user.is_active, is_superadmin=user.is_superadmin,
                        last_login_at=user.last_login_at, created_at=user.created_at, workspaces=list(names))


def _user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound(_("User not found."))
    return user


@router.get("/users", response_model=AdminUserPage)
def list_users(q: str = "", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
               admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    """Every account on the platform, newest first; ``q`` matches the name, e-mail or username."""
    query = select(User)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(User.name).like(like), func.lower(User.email).like(like),
                                func.lower(func.coalesce(User.username, "")).like(like)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(User.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    return AdminUserPage(items=[_user_out(db, u) for u in rows], total=total, page=page, page_size=page_size)


@router.post("/users/{user_id}/active", response_model=AdminUserOut)
def set_user_active(user_id: int, data: FlagIn, admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    """Disable or enable an account. A disabled account is signed out everywhere and cannot sign in."""
    user = _user(db, user_id)
    if user.id == admin.id and not data.value:
        raise AppError(_("You cannot disable your own account."), code="self_action")
    user.is_active = data.value
    if not data.value:
        user.token_version += 1
    return _user_out(db, user)


@router.post("/users/{user_id}/superadmin", response_model=AdminUserOut)
def set_user_superadmin(user_id: int, data: FlagIn, admin: User = Depends(superadmin),
                        db: Session = Depends(get_db)):
    user = _user(db, user_id)
    if user.id == admin.id and not data.value:
        raise AppError(_("You cannot remove your own administrator rights."), code="self_action")
    user.is_superadmin = data.value
    user.token_version += 1
    return _user_out(db, user)


# ------------------------------------------------------------------ platform-paid AI
class AdminAiRow(BaseModel):
    key: str
    label: str
    cost: float
    calls: int
    limit: float | None = None


class AdminAiOut(BaseModel):
    month_total: float
    keys: dict[str, bool]
    by_provider: list[AdminAiRow]
    by_workspace: list[AdminAiRow]


@router.get("/ai", response_model=AdminAiOut)
def ai_overview(admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    """What the platform's own AI keys cost this month: per provider and for the ten heaviest workspaces."""
    from app.modules.ai import catalog
    from app.modules.ai.models import AIProvider, AIUsage
    since = limits.month_start()
    paid = [AIUsage.provider_id == AIProvider.id, AIProvider.managed.is_(True), AIUsage.created_at >= since]
    cost, calls = func.coalesce(func.sum(AIUsage.cost), 0.0), func.count(AIUsage.id)
    providers = db.execute(select(AIProvider.provider_type, cost, calls).where(*paid)
                           .group_by(AIProvider.provider_type).order_by(cost.desc())).all()
    workspaces = db.execute(select(Workspace.id, Workspace.name, cost, calls).where(*paid, Workspace.id == AIUsage.workspace_id)
                            .group_by(Workspace.id, Workspace.name).order_by(cost.desc()).limit(10)).all()
    return AdminAiOut(
        month_total=round(sum(float(row[1]) for row in providers), 4),
        keys={name: bool(platform.ai_key(db, name)) for name in platform.AI_PROVIDERS},
        by_provider=[AdminAiRow(key=t, label=catalog.info(t)["label"], cost=round(float(c), 4), calls=n)
                     for t, c, n in providers],
        by_workspace=[AdminAiRow(key=str(wid), label=name, cost=round(float(c), 4), calls=n,
                                 limit=limits.usage(db, wid).get("ai_credits", {}).get("limit"))
                      for wid, name, c, n in workspaces])


# ------------------------------------------------------------------ system health
class AdminCheck(BaseModel):
    key: str
    ok: bool
    detail: str = ""


class AdminSystemOut(BaseModel):
    checks: list[AdminCheck]
    queues: dict[str, int]
    workers: int
    failed_jobs: int
    errors_24h: int
    posts_today: int
    failed_posts_today: int
    recent_errors: list[AdminErrorOut]


@router.get("/system", response_model=AdminSystemOut)
def system_health(admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    """Is everything running: database, Redis, the background worker and its queues, and recent failures."""
    from app.modules.social.models import Post
    now = service.utcnow()
    checks = [AdminCheck(key="database", ok=True)]
    queues, workers, failed = {}, 0, 0
    try:
        from redis import Redis
        from rq import Queue, Worker
        connection = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
        connection.ping()
        checks.append(AdminCheck(key="redis", ok=True))
        for name in ("default", "periodic", "media"):
            queue = Queue(name, connection=connection)
            queues[name] = queue.count
            failed += queue.failed_job_registry.count
        workers = len(Worker.all(connection=connection))
        checks.append(AdminCheck(key="worker", ok=workers > 0, detail=str(workers)))
    except Exception as error:  # noqa: BLE001 - the page must load when Redis is down: that is what it reports
        checks.append(AdminCheck(key="redis", ok=False, detail=str(error)[:200]))
        checks.append(AdminCheck(key="worker", ok=False))
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    errors = select(ApiLog).where(ApiLog.error.is_not(None))
    recent = db.scalars(errors.order_by(ApiLog.id.desc()).limit(15)).all()
    return AdminSystemOut(
        checks=checks, queues=queues, workers=workers, failed_jobs=failed,
        errors_24h=db.scalar(select(func.count()).select_from(
            errors.where(ApiLog.created_at >= now - timedelta(hours=24)).subquery())) or 0,
        posts_today=db.scalar(select(func.count()).select_from(Post).where(Post.published_at >= day)) or 0,
        failed_posts_today=db.scalar(select(func.count()).select_from(Post).where(
            Post.state.in_(("failed", "partial")), Post.updated_at >= day)) or 0,
        recent_errors=[AdminErrorOut(id=e.id, service=e.service, operation=e.operation, status_code=e.status_code,
                                     error=(e.error or "")[:300], created_at=e.created_at) for e in recent])
