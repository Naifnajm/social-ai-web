"""Platform admin › Users (superadmins only): find any account, see everything that belongs to it, and act on it.
Every change is recorded in the account's trail (``UserEvent``) with the administrator as the actor.

Safety rules: the last active platform administrator cannot be disabled or demoted, an administrator cannot
disable or demote themselves, workspaces never lose their last owner, other administrators cannot be viewed as,
and erasing an account keeps billing and audit rows."""
import csv
import io
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import (
    ACCESS_COOKIE,
    IMPERSONATION_RETURN_COOKIE,
    REFRESH_COOKIE,
    superadmin,
)
from app.core.errors import AppError, NotFound
from app.core.hardening import rate_limit
from app.core.i18n import LOCALES, _
from app.core.security import (
    IMPERSONATION_MINUTES,
    create_impersonation_token,
    create_refresh_token,
    hash_password,
)
from app.modules.auth.models import User
from app.modules.workspaces.models import Membership, Role, Workspace
from app.modules.workspaces.service import owners_count

from . import service
from .models import UserEvent

router = APIRouter(prefix="/admin/users", tags=["platform admin"])
sensitive = rate_limit("admin-users-sensitive", 60, 600)


# ------------------------------------------------------------------------------------------------ schemas
class AdminUserOut(BaseModel):
    id: int
    name: str
    email: str
    username: str | None = None
    is_active: bool
    is_superadmin: bool
    email_verified: bool = False
    totp_enabled: bool = False
    must_change_password: bool = False
    deleted_at: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime
    workspaces: list[str] = []
    plans: list[str] = []


class AdminUserPage(BaseModel):
    items: list[AdminUserOut]
    total: int
    page: int
    page_size: int


class FlagIn(BaseModel):
    value: bool


class AdminUserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    locale: str | None = None
    timezone: str | None = Field(default=None, max_length=64)
    email_verified: bool | None = None


class MembershipIn(BaseModel):
    workspace_id: int
    role: Role = Role.editor


class RoleIn(BaseModel):
    role: Role


class TransferIn(BaseModel):
    to_user_id: int


class DeleteIn(BaseModel):
    confirm_email: str
    delete_workspaces: list[int] = []


# ------------------------------------------------------------------------------------------------ helpers
def _user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound(_("User not found."))
    return user


def _live(db: Session, user_id: int) -> User:
    user = _user(db, user_id)
    if user.deleted_at:
        raise AppError(_("This account was deleted."), code="deleted_user")
    return user


def _plan_of():
    from app.modules.billing.models import Subscription
    return func.coalesce(Subscription.plan_code, Workspace.plan_code)


def _row(db: Session, user: User) -> AdminUserOut:
    from app.modules.billing.models import Subscription
    rows = db.execute(select(Workspace.name, _plan_of()).join(Membership, Membership.workspace_id == Workspace.id)
                      .outerjoin(Subscription, Subscription.workspace_id == Workspace.id)
                      .where(Membership.user_id == user.id).order_by(Workspace.name)).all()
    return AdminUserOut(id=user.id, name=user.name, email=user.email, username=user.username,
                        is_active=user.is_active, is_superadmin=user.is_superadmin,
                        email_verified=user.email_verified, totp_enabled=user.totp_enabled,
                        must_change_password=user.must_change_password, deleted_at=user.deleted_at,
                        last_login_at=user.last_login_at, created_at=user.created_at,
                        workspaces=[name for name, _plan in rows], plans=sorted({plan for _name, plan in rows}))


def _audit(db: Session, request: Request, user: User, admin: User, type_: str, summary: str = "",
           payload: dict | None = None) -> None:
    service.audit(db, user.id, type_, actor_id=admin.id, summary=summary, payload=payload, request=request)


def active_superadmins(db: Session, exclude: int | None = None) -> int:
    query = select(func.count()).select_from(User).where(User.is_superadmin.is_(True), User.is_active.is_(True))
    if exclude is not None:
        query = query.where(User.id != exclude)
    return db.scalar(query) or 0


def _bounds(start: date | None, end: date | None, column):
    conditions = []
    if start:
        conditions.append(column >= datetime.combine(start, time.min, timezone.utc))
    if end:
        conditions.append(column < datetime.combine(end + timedelta(days=1), time.min, timezone.utc))
    return conditions


SORTS = {"created": User.id.asc(), "-created": User.id.desc(), "name": func.lower(User.name).asc(),
         "-name": func.lower(User.name).desc(), "email": func.lower(User.email).asc(),
         "-email": func.lower(User.email).desc(), "last_login": User.last_login_at.asc().nulls_first(),
         "-last_login": User.last_login_at.desc().nulls_last()}


def _query(q: str, status: str, superadmin_: bool | None, verified: bool | None, two_factor: bool | None,
           plan: str, created_from: date | None, created_to: date | None, login_from: date | None,
           login_to: date | None, sort: str) -> Select:
    query = select(User)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        conditions = [func.lower(User.name).like(like), func.lower(User.email).like(like),
                      func.lower(func.coalesce(User.username, "")).like(like)]
        if q.strip().isdigit():
            conditions.append(User.id == int(q.strip()))
        query = query.where(or_(*conditions))
    if status == "active":
        query = query.where(User.is_active.is_(True), User.deleted_at.is_(None))
    elif status == "disabled":
        query = query.where(User.is_active.is_(False), User.deleted_at.is_(None))
    elif status == "deleted":
        query = query.where(User.deleted_at.is_not(None))
    elif status == "must_change":
        query = query.where(User.must_change_password.is_(True))
    if superadmin_ is not None:
        query = query.where(User.is_superadmin.is_(superadmin_))
    if verified is not None:
        query = query.where(User.email_verified.is_(verified))
    if two_factor is not None:
        query = query.where(User.totp_enabled.is_(two_factor))
    if plan:
        from app.modules.billing.models import Subscription
        members = (select(Membership.user_id).join(Workspace, Workspace.id == Membership.workspace_id)
                   .outerjoin(Subscription, Subscription.workspace_id == Workspace.id).where(_plan_of() == plan))
        query = query.where(User.id.in_(members))
    conditions = _bounds(created_from, created_to, User.created_at) + _bounds(login_from, login_to,
                                                                              User.last_login_at)
    if conditions:
        query = query.where(and_(*conditions))
    return query.order_by(SORTS.get(sort, User.id.desc()), User.id.desc())


def _filters(q: str = "", status: str = "", superadmin_: bool | None = Query(None, alias="superadmin"),
             verified: bool | None = None, two_factor: bool | None = None, plan: str = "",
             created_from: date | None = None, created_to: date | None = None, login_from: date | None = None,
             login_to: date | None = None, sort: str = "-created") -> Select:
    return _query(q, status, superadmin_, verified, two_factor, plan, created_from, created_to, login_from,
                  login_to, sort)


# ------------------------------------------------------------------------------------------------ list & export
@router.get("", response_model=AdminUserPage)
def list_users(query: Select = Depends(_filters), page: int = Query(1, ge=1),
               page_size: int = Query(25, ge=1, le=100), admin: User = Depends(superadmin),
               db: Session = Depends(get_db)):
    """Every account on the platform. Filters: ``q`` (name, e-mail, username or id), ``status`` (active, disabled,
    deleted, must_change), ``superadmin``, ``verified``, ``two_factor``, ``plan``, ``created_from``/``created_to``,
    ``login_from``/``login_to`` (dates); ``sort``: created, name, email, last_login (``-`` for descending)."""
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = db.scalars(query.limit(page_size).offset((page - 1) * page_size)).all()
    return AdminUserPage(items=[_row(db, u) for u in rows], total=total, page=page, page_size=page_size)


def _cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text  # no formulas in spreadsheets


@router.get("/export.csv")
def export_csv(request: Request, query: Select = Depends(_filters), admin: User = Depends(superadmin),
               db: Session = Depends(get_db)):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "name", "email", "username", "status", "superadmin", "email_verified", "two_factor",
                     "created_at", "last_login_at", "workspaces", "plans"])
    count = 0
    for user in db.scalars(query.limit(50000)):
        row = _row(db, user)
        status = "deleted" if user.deleted_at else ("active" if user.is_active else "disabled")
        writer.writerow([_cell(v) for v in (row.id, row.name, row.email, row.username, status, row.is_superadmin,
                                            row.email_verified, row.totp_enabled, row.created_at.isoformat(),
                                            row.last_login_at.isoformat() if row.last_login_at else "",
                                            " | ".join(row.workspaces), " | ".join(row.plans))])
        count += 1
    service.audit(db, None, "admin.users_export", actor_id=admin.id, summary=f"{count} rows", request=request)
    return Response("﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="users.csv"'})


# ------------------------------------------------------------------------------------------------ detail
@router.get("/{user_id}")
def detail(user_id: int, admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    """Everything about one account: workspaces and roles, keys and connected apps, sign-ins and the trail of
    changes, AI use this month, files, support tickets, and what blocks deleting it."""
    from app.core.models import Media
    from app.modules.ai.models import AIUsage
    from app.modules.billing import limits
    from app.modules.billing.models import Subscription
    from app.modules.connect.models import ApiKey, OAuthGrant
    from app.modules.support.models import SupportTicket
    user = _user(db, user_id)
    sole = {b["workspace_id"] for b in service.sole_owned(db, user.id)}
    workspaces = []
    for m, ws, plan in db.execute(select(Membership, Workspace, _plan_of())
                                  .join(Workspace, Workspace.id == Membership.workspace_id)
                                  .outerjoin(Subscription, Subscription.workspace_id == Workspace.id)
                                  .where(Membership.user_id == user.id).order_by(Membership.id)).all():
        members = db.scalar(select(func.count()).select_from(Membership).where(
            Membership.workspace_id == ws.id)) or 0
        workspaces.append({"workspace_id": ws.id, "name": ws.name, "role": m.role, "plan": plan,
                           "status": ws.status, "members": members, "owners": owners_count(db, ws.id),
                           "sole_owner": ws.id in sole, "joined_at": m.created_at,
                           "ai_spent_month": limits.ai_spend_month(db, ws.id, user.id)})
    names = {w["workspace_id"]: w["name"] for w in workspaces}

    def ws_name(workspace_id: int) -> str:
        if workspace_id not in names:
            names[workspace_id] = db.scalar(select(Workspace.name).where(Workspace.id == workspace_id)) or "—"
        return names[workspace_id]

    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.id.desc())).all()
    grants = db.scalars(select(OAuthGrant).where(OAuthGrant.user_id == user.id).order_by(OAuthGrant.id.desc())).all()
    events = db.scalars(select(UserEvent).where(UserEvent.user_id == user.id)
                        .order_by(UserEvent.id.desc()).limit(60)).all()
    actor_ids = {e.actor_id for e in events if e.actor_id} | {e.impersonator_id for e in events if e.impersonator_id}
    actors = dict(db.execute(select(User.id, User.email).where(User.id.in_(actor_ids))).all()) if actor_ids else {}
    month = limits.month_start()
    calls, charged = db.execute(select(func.count(AIUsage.id),
                                       func.coalesce(func.sum(func.coalesce(AIUsage.price, AIUsage.cost)), 0.0))
                                .where(AIUsage.user_id == user.id, AIUsage.created_at >= month)).one()
    tickets = db.execute(select(SupportTicket.status, func.count()).where(SupportTicket.user_id == user.id)
                         .group_by(SupportTicket.status)).all()
    return {
        "user": _row(db, user).model_dump(),
        "locale": user.locale, "timezone": user.timezone, "avatar_url": user.avatar_url,
        "password_changed_at": user.password_changed_at, "has_password": bool(user.password_hash),
        "recovery_codes_left": len(user.recovery_codes or []), "token_version": user.token_version,
        "workspaces": workspaces,
        "api_keys": [{"id": k.id, "name": k.name, "prefix": k.prefix, "workspace": ws_name(k.workspace_id),
                      "scopes": k.scopes, "created_at": k.created_at, "expires_at": k.expires_at,
                      "last_used_at": k.last_used_at, "revoked_at": k.revoked_at} for k in keys],
        "apps": [{"id": g.id, "name": g.client.client_name, "workspace": ws_name(g.workspace_id), "scopes": g.scopes,
                  "created_at": g.created_at, "last_used_at": g.last_used_at, "revoked_at": g.revoked_at}
                 for g in grants],
        "events": [{"id": e.id, "type": e.type, "summary": e.summary, "ip": e.ip, "user_agent": e.user_agent,
                    "at": e.created_at, "actor": actors.get(e.actor_id) if e.actor_id != user.id else None,
                    "impersonator": actors.get(e.impersonator_id)} for e in events],
        "ai_month": {"calls": int(calls or 0), "charged_usd": round(float(charged or 0), 4)},
        "storage_bytes": int(db.scalar(select(func.coalesce(func.sum(Media.size), 0)).where(
            Media.created_by_id == user.id)) or 0),
        "files": db.scalar(select(func.count()).select_from(Media).where(Media.created_by_id == user.id)) or 0,
        "support_tickets": {"total": sum(n for _s, n in tickets), "open": sum(n for s, n in tickets if s == "open")},
        "delete_blockers": service.sole_owned(db, user.id),
        "can_impersonate": user.is_active and not user.is_superadmin and not user.deleted_at,
        "last_superadmin": user.is_superadmin and user.is_active and active_superadmins(db, exclude=user.id) == 0,
    }


# ------------------------------------------------------------------------------------------------ profile
@router.patch("/{user_id}", response_model=AdminUserOut)
def update(user_id: int, data: AdminUserUpdate, request: Request, admin: User = Depends(superadmin),
           db: Session = Depends(get_db)):
    """Name, e-mail (unique; becomes unconfirmed and a confirmation link is sent), language, time zone, and the
    e-mail confirmed flag."""
    from app.modules.auth.router import _find_user, _valid_timezone, send_verification
    user = _live(db, user_id)
    changes = {}
    if data.name is not None and data.name.strip() != user.name:
        changes["name"] = [user.name, data.name.strip()]
        user.name = data.name.strip()
    if data.locale is not None and data.locale != user.locale:
        if data.locale not in LOCALES:
            raise AppError(_("Unknown language."), code="bad_locale")
        changes["locale"] = [user.locale, data.locale]
        user.locale = data.locale
    if data.timezone is not None and data.timezone != user.timezone:
        if not _valid_timezone(data.timezone):
            raise AppError(_("Unknown time zone."), code="bad_timezone")
        changes["timezone"] = [user.timezone, data.timezone]
        user.timezone = data.timezone
    email_changed = False
    if data.email is not None and data.email.strip().lower() != user.email:
        email = data.email.strip().lower()
        other = _find_user(db, email)
        if other and other.id != user.id:
            raise AppError(_("An account with this e-mail already exists."), code="email_taken")
        changes["email"] = [user.email, email]
        user.email = email
        user.email_verified = False
        email_changed = True
    if data.email_verified is not None and not email_changed and data.email_verified != user.email_verified:
        changes["email_verified"] = [user.email_verified, data.email_verified]
        user.email_verified = data.email_verified
    if changes:
        _audit(db, request, user, admin, "admin.profile", ", ".join(sorted(changes)), {"changes": changes})
    if email_changed:
        send_verification(user)
    return _row(db, user)


@router.post("/{user_id}/send-verification", status_code=204, dependencies=[Depends(sensitive)])
def send_verification_mail(user_id: int, request: Request, admin: User = Depends(superadmin),
                           db: Session = Depends(get_db)):
    from app.modules.auth.router import send_verification
    user = _live(db, user_id)
    send_verification(user)
    _audit(db, request, user, admin, "admin.verification_sent")


# ------------------------------------------------------------------------------------------------ password & sessions
@router.post("/{user_id}/password-reset-email", status_code=204, dependencies=[Depends(sensitive)])
def password_reset_email(user_id: int, request: Request, admin: User = Depends(superadmin),
                         db: Session = Depends(get_db)):
    """Send the person the same reset link as "Forgot password"."""
    from app.modules.auth.router import send_reset_link
    user = _live(db, user_id)
    if not user.is_active:
        raise AppError(_("Enable the account first."), code="inactive_user")
    send_reset_link(user)
    _audit(db, request, user, admin, "admin.password_reset_email")


@router.post("/{user_id}/temporary-password", dependencies=[Depends(sensitive)])
def temporary_password(user_id: int, request: Request, admin: User = Depends(superadmin),
                       db: Session = Depends(get_db)):
    """Set a random temporary password, shown only in this answer. Every session is signed out and the person
    must choose their own password right after signing in."""
    user = _live(db, user_id)
    if user.id == admin.id:
        raise AppError(_("Change your own password in your account."), code="self_action")
    password = service.generate_password()
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.token_version += 1
    _audit(db, request, user, admin, "admin.temporary_password")
    return JSONResponse({"password": password}, headers={"Cache-Control": "no-store"})


@router.post("/{user_id}/sign-out", status_code=204, dependencies=[Depends(sensitive)])
def sign_out(user_id: int, request: Request, admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    """Sign the person out on every device (their next request asks them to sign in)."""
    user = _live(db, user_id)
    user.token_version += 1
    _audit(db, request, user, admin, "admin.sign_out")


@router.post("/{user_id}/revoke-access", dependencies=[Depends(sensitive)])
def revoke_access(user_id: int, request: Request, admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    """Revoke every personal API key and connected AI app of the person."""
    user = _user(db, user_id)
    counts = service.revoke_access(db, user)
    _audit(db, request, user, admin, "admin.revoke_access", f"{counts['api_keys']} keys, {counts['apps']} apps", counts)
    return counts


@router.post("/{user_id}/reset-2fa", status_code=204, dependencies=[Depends(sensitive)])
def reset_two_factor(user_id: int, request: Request, admin: User = Depends(superadmin),
                     db: Session = Depends(get_db)):
    """Turn two-step sign-in off (lost phone and recovery codes). The person is signed out everywhere."""
    user = _live(db, user_id)
    service.reset_two_factor(user)
    user.token_version += 1
    _audit(db, request, user, admin, "admin.reset_2fa")


# ------------------------------------------------------------------------------------------------ status & rights
@router.post("/{user_id}/active", response_model=AdminUserOut)
def set_active(user_id: int, data: FlagIn, request: Request, admin: User = Depends(superadmin),
               db: Session = Depends(get_db)):
    """Disable or enable an account. A disabled account is signed out everywhere and cannot sign in."""
    user = _live(db, user_id)
    if user.id == admin.id and not data.value:
        raise AppError(_("You cannot disable your own account."), code="self_action")
    if not data.value and user.is_superadmin and active_superadmins(db, exclude=user.id) == 0:
        raise AppError(_("This is the last platform administrator."), code="last_superadmin")
    if user.is_active != data.value:
        user.is_active = data.value
        if not data.value:
            user.token_version += 1
        _audit(db, request, user, admin, "admin.enabled" if data.value else "admin.disabled")
    return _row(db, user)


@router.post("/{user_id}/superadmin", response_model=AdminUserOut)
def set_superadmin(user_id: int, data: FlagIn, request: Request, admin: User = Depends(superadmin),
                   db: Session = Depends(get_db)):
    user = _live(db, user_id)
    if user.id == admin.id and not data.value:
        raise AppError(_("You cannot remove your own administrator rights."), code="self_action")
    if not data.value and user.is_superadmin and active_superadmins(db, exclude=user.id) == 0:
        raise AppError(_("This is the last platform administrator."), code="last_superadmin")
    if user.is_superadmin != data.value:
        user.is_superadmin = data.value
        user.token_version += 1
        _audit(db, request, user, admin, "admin.superadmin_granted" if data.value else "admin.superadmin_revoked")
    return _row(db, user)


# ------------------------------------------------------------------------------------------------ memberships
def _membership(db: Session, user_id: int, workspace_id: int) -> Membership:
    membership = db.scalar(select(Membership).where(Membership.user_id == user_id,
                                                    Membership.workspace_id == workspace_id))
    if not membership:
        raise NotFound(_("Member not found."))
    return membership


def _last_owner_error(workspace: Workspace) -> AppError:
    return AppError(_("“{name}” needs at least one owner. Transfer the ownership first.", name=workspace.name),
                    code="last_owner")


@router.post("/{user_id}/memberships", status_code=201)
def add_membership(user_id: int, data: MembershipIn, request: Request, admin: User = Depends(superadmin),
                   db: Session = Depends(get_db)):
    user = _live(db, user_id)
    workspace = db.get(Workspace, data.workspace_id)
    if not workspace:
        raise NotFound(_("Workspace not found."))
    if db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.workspace_id == workspace.id)):
        raise AppError(_("Already a member of this workspace."), code="already_member")
    db.add(Membership(user_id=user.id, workspace_id=workspace.id, role=data.role))
    db.flush()
    _audit(db, request, user, admin, "admin.membership_added", f"{workspace.name}: {data.role}",
           {"workspace_id": workspace.id, "role": data.role})
    return {"workspace_id": workspace.id, "role": data.role}


@router.patch("/{user_id}/memberships/{workspace_id}")
def change_membership(user_id: int, workspace_id: int, data: RoleIn, request: Request,
                      admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    user = _live(db, user_id)
    membership = _membership(db, user.id, workspace_id)
    if membership.role == Role.owner and data.role != Role.owner and owners_count(db, workspace_id) <= 1:
        raise _last_owner_error(membership.workspace)
    previous = membership.role
    membership.role = data.role
    _audit(db, request, user, admin, "admin.membership_role", f"{membership.workspace.name}: {previous} → {data.role}",
           {"workspace_id": workspace_id, "from": previous, "to": data.role})
    return {"workspace_id": workspace_id, "role": data.role}


@router.delete("/{user_id}/memberships/{workspace_id}", status_code=204)
def remove_membership(user_id: int, workspace_id: int, request: Request, admin: User = Depends(superadmin),
                      db: Session = Depends(get_db)):
    user = _user(db, user_id)
    membership = _membership(db, user.id, workspace_id)
    if membership.role == Role.owner and owners_count(db, workspace_id) <= 1:
        raise _last_owner_error(membership.workspace)
    name = membership.workspace.name
    db.delete(membership)
    if user.last_workspace_id == workspace_id:
        user.last_workspace_id = None
    _audit(db, request, user, admin, "admin.membership_removed", name, {"workspace_id": workspace_id})


@router.post("/{user_id}/memberships/{workspace_id}/transfer")
def transfer_ownership(user_id: int, workspace_id: int, data: TransferIn, request: Request,
                       admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    """Make another member of the workspace its owner; this person stays in it as an admin."""
    user = _user(db, user_id)
    membership = _membership(db, user.id, workspace_id)
    if membership.role != Role.owner:
        raise AppError(_("This person is not an owner of the workspace."), code="not_owner")
    if data.to_user_id == user.id:
        raise AppError(_("Choose another member."), code="same_user")
    target = db.scalar(select(Membership).where(Membership.user_id == data.to_user_id,
                                                Membership.workspace_id == workspace_id))
    if not target or not target.user.is_active or target.user.deleted_at:
        raise AppError(_("The new owner must be an active member of the workspace."), code="not_member")
    target.role = Role.owner
    membership.role = Role.admin
    workspace = membership.workspace.name
    _audit(db, request, user, admin, "admin.ownership_transferred", f"{workspace} → {target.user.email}",
           {"workspace_id": workspace_id, "to_user_id": target.user_id})
    _audit(db, request, target.user, admin, "admin.ownership_received", workspace, {"workspace_id": workspace_id})
    return {"workspace_id": workspace_id, "owner_user_id": target.user_id}


@router.get("/{user_id}/workspace-members/{workspace_id}")
def workspace_members(user_id: int, workspace_id: int, admin: User = Depends(superadmin),
                      db: Session = Depends(get_db)):
    """The other members of one of the person's workspaces (to choose a new owner)."""
    rows = db.execute(select(Membership, User).join(User, User.id == Membership.user_id).where(
        Membership.workspace_id == workspace_id, Membership.user_id != user_id, User.is_active.is_(True))
        .order_by(Membership.id)).all()
    return [{"user_id": u.id, "name": u.name, "email": u.email, "role": m.role} for m, u in rows]


# ------------------------------------------------------------------------------------------------ view as
@router.post("/{user_id}/impersonate", dependencies=[Depends(sensitive)])
def impersonate(user_id: int, request: Request, response: Response, admin: User = Depends(superadmin),
                db: Session = Depends(get_db)):
    """View the app as the person for 30 minutes (support). The administrator's own session waits in a separate
    cookie and comes back with ``/auth/impersonation/end``, on sign-out or when the 30 minutes are over. While it
    lasts nothing can be deleted, the person's password, e-mail, two-step sign-in and keys cannot be touched, the
    admin area is closed, and every change is recorded with the administrator's name."""
    from app.modules.auth.router import cookie_options, me_payload
    user = _live(db, user_id)
    if user.id == admin.id:
        raise AppError(_("You are already signed in as yourself."), code="self_action")
    if user.is_superadmin:
        raise AppError(_("Platform administrators cannot be viewed as."), code="cannot_impersonate")
    if not user.is_active:
        raise AppError(_("Enable the account first."), code="inactive_user")
    token = create_impersonation_token(user.id, user.token_version, admin.id, admin.token_version)
    cookie = cookie_options()
    response.set_cookie(ACCESS_COOKIE, token, max_age=IMPERSONATION_MINUTES * 60, **cookie)
    response.set_cookie(IMPERSONATION_RETURN_COOKIE, create_refresh_token(admin.id, admin.token_version),
                        max_age=settings.refresh_token_days * 86400, path="/api/auth", **cookie)
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth", domain=settings.cookie_domain)
    _audit(db, request, user, admin, "impersonation.start", f"{IMPERSONATION_MINUTES} min")
    expires = datetime.now(timezone.utc) + timedelta(minutes=IMPERSONATION_MINUTES)
    return {"access_token": token, "expires_at": expires, "me": me_payload(db, user).model_dump()}


# ------------------------------------------------------------------------------------------------ GDPR
@router.get("/{user_id}/export")
def export(user_id: int, request: Request, admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    """The person's data as JSON (for a GDPR access or portability request)."""
    user = _user(db, user_id)
    _audit(db, request, user, admin, "admin.data_exported")
    return JSONResponse(service.export_user(db, user),
                        headers={"Content-Disposition": f'attachment; filename="user-{user.id}.json"'})


@router.post("/{user_id}/delete", status_code=204, dependencies=[Depends(sensitive)])
def delete_user(user_id: int, data: DeleteIn, request: Request, admin: User = Depends(superadmin),
                db: Session = Depends(get_db)):
    """Erase an account (GDPR): type the e-mail to confirm. Workspaces the person owns alone must be transferred
    first, or listed in ``delete_workspaces`` when nobody else is in them (the answer lists them otherwise)."""
    user = _live(db, user_id)
    if user.id == admin.id:
        raise AppError(_("Delete your own account in your account center."), code="self_action")
    if data.confirm_email.strip().lower() != user.email.lower():
        raise AppError(_("Type the e-mail address exactly to confirm."), code="confirm_mismatch")
    if user.is_superadmin and active_superadmins(db, exclude=user.id) == 0:
        raise AppError(_("This is the last platform administrator."), code="last_superadmin")
    email = user.email
    service.erase_user(db, user, delete_workspaces=data.delete_workspaces)
    _audit(db, request, user, admin, "admin.deleted", payload={"email_domain": email.split("@")[-1],
                                                               "deleted_workspaces": data.delete_workspaces})
