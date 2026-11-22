"""The person's own account center: security overview and recent sign-ins, two-step sign-in, workspaces (leave),
avatar, e-mail preferences, export of their data and deleting the account.

Profile fields (name, username, language, time zone) stay on ``PATCH /auth/me``; the password and e-mail on
``/auth/password`` and ``/auth/email``."""
from datetime import datetime

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import current_user, not_impersonating
from app.core.errors import AppError, NotFound
from app.core.hardening import UPLOAD_HEADERS, rate_limit
from app.core.i18n import _
from app.core.security import verify_password
from app.modules.auth.models import User
from app.modules.workspaces.models import Membership

from . import service
from .models import UserEvent

router = APIRouter(prefix="/account", tags=["account"])
sensitive = rate_limit("account-sensitive", 10, 600)


# ------------------------------------------------------------------------------------------------ security
class SignInOut(BaseModel):
    at: datetime
    ip: str | None = None
    user_agent: str | None = None
    how: str | None = None


class SecurityOut(BaseModel):
    email: str
    email_verified: bool
    totp_enabled: bool
    recovery_codes_left: int
    password_changed_at: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime
    must_change_password: bool
    sign_ins: list[SignInOut]
    events: list[dict]


@router.get("/security", response_model=SecurityOut)
def security(user: User = Depends(current_user), db: Session = Depends(get_db)):
    logins = db.scalars(select(UserEvent).where(UserEvent.user_id == user.id, UserEvent.type == "login")
                        .order_by(UserEvent.id.desc()).limit(10)).all()
    events = db.scalars(select(UserEvent).where(UserEvent.user_id == user.id, UserEvent.type.not_in(
        ("login", "impersonation.action"))).order_by(UserEvent.id.desc()).limit(15)).all()
    return SecurityOut(
        email=user.email, email_verified=user.email_verified, totp_enabled=user.totp_enabled,
        recovery_codes_left=len(user.recovery_codes or []), password_changed_at=user.password_changed_at,
        last_login_at=user.last_login_at, created_at=user.created_at, must_change_password=user.must_change_password,
        sign_ins=[SignInOut(at=e.created_at, ip=e.ip, user_agent=e.user_agent, how=e.summary) for e in logins],
        events=[{"type": e.type, "at": e.created_at, "by_admin": bool(e.actor_id and e.actor_id != user.id)}
                for e in events])


# ------------------------------------------------------------------------------------------------ two-step sign-in
class PasswordIn(BaseModel):
    password: str


class TotpSetupOut(BaseModel):
    secret: str
    uri: str


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class DisableIn(BaseModel):
    password: str
    code: str = Field(min_length=6, max_length=20)


def _password_ok(user: User, password: str) -> None:
    if not verify_password(password, user.password_hash):
        raise AppError(_("The current password is wrong."), code="bad_password")


@router.post("/2fa/setup", response_model=TotpSetupOut, dependencies=[Depends(sensitive)])
def totp_setup(data: PasswordIn, user: User = Depends(not_impersonating)):
    """Start two-step sign-in: a new secret for the authenticator app (not active until a code is confirmed)."""
    _password_ok(user, data.password)
    if user.totp_enabled:
        raise AppError(_("Two-step sign-in is already on."), code="already_enabled")
    user.totp_secret = service.new_totp_secret()
    user.totp_last_step = None
    return TotpSetupOut(secret=user.totp_secret, uri=service.otpauth_uri(user.totp_secret, user.email))


@router.post("/2fa/enable", dependencies=[Depends(sensitive)])
def totp_enable(data: CodeIn, request: Request, user: User = Depends(not_impersonating),
                db: Session = Depends(get_db)):
    """Confirm the first code: two-step sign-in is on. Answers the recovery codes, shown this once."""
    if user.totp_enabled:
        raise AppError(_("Two-step sign-in is already on."), code="already_enabled")
    if not user.totp_secret or not service.verify_totp(user, data.code):
        raise AppError(_("The code is wrong or expired."), code="bad_code")
    user.totp_enabled = True
    codes = service.new_recovery_codes(user)
    service.audit(db, user.id, "2fa.enabled", actor_id=user.id, request=request)
    return {"recovery_codes": codes}


@router.post("/2fa/disable", status_code=204, dependencies=[Depends(sensitive)])
def totp_disable(data: DisableIn, request: Request, user: User = Depends(not_impersonating),
                 db: Session = Depends(get_db)):
    _password_ok(user, data.password)
    if not user.totp_enabled:
        return
    if not service.check_second_factor(user, data.code):
        raise AppError(_("The code is wrong or expired."), code="bad_code")
    service.reset_two_factor(user)
    service.audit(db, user.id, "2fa.disabled", actor_id=user.id, request=request)


@router.post("/2fa/recovery-codes", dependencies=[Depends(sensitive)])
def totp_recovery_codes(data: DisableIn, request: Request, user: User = Depends(not_impersonating),
                        db: Session = Depends(get_db)):
    """New recovery codes (the old ones stop working); shown this once."""
    _password_ok(user, data.password)
    if not user.totp_enabled:
        raise AppError(_("Two-step sign-in is off."), code="not_enabled")
    if not service.check_second_factor(user, data.code):
        raise AppError(_("The code is wrong or expired."), code="bad_code")
    codes = service.new_recovery_codes(user)
    service.audit(db, user.id, "2fa.recovery_codes", actor_id=user.id, request=request)
    return {"recovery_codes": codes}


# ------------------------------------------------------------------------------------------------ workspaces
class MyWorkspaceOut(BaseModel):
    workspace_id: int
    name: str
    role: str
    plan: str
    status: str
    members: int
    sole_owner: bool


@router.get("/workspaces", response_model=list[MyWorkspaceOut])
def my_workspaces(user: User = Depends(current_user), db: Session = Depends(get_db)):
    sole = {b["workspace_id"] for b in service.sole_owned(db, user.id)}
    rows = db.scalars(select(Membership).where(Membership.user_id == user.id).order_by(Membership.id)).all()
    out = []
    for m in rows:
        members = db.scalar(select(func.count()).select_from(Membership).where(
            Membership.workspace_id == m.workspace_id)) or 0
        out.append(MyWorkspaceOut(workspace_id=m.workspace_id, name=m.workspace.name, role=m.role,
                                  plan=m.workspace.plan_code, status=m.workspace.status, members=members,
                                  sole_owner=m.workspace_id in sole))
    return out


@router.post("/workspaces/{workspace_id}/leave", status_code=204, dependencies=[Depends(sensitive)])
def leave_workspace(workspace_id: int, request: Request, user: User = Depends(not_impersonating),
                    db: Session = Depends(get_db)):
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id,
                                                    Membership.workspace_id == workspace_id))
    if not membership:
        raise NotFound(_("You are not a member of this workspace."))
    if any(b["workspace_id"] == workspace_id for b in service.sole_owned(db, user.id)):
        raise AppError(_("You are the only owner. Make another member owner first."), code="last_owner")
    if db.scalar(select(func.count()).select_from(Membership).where(Membership.user_id == user.id)) <= 1:
        raise AppError(_("This is your only workspace. Create or join another one first."), code="only_workspace")
    name = membership.workspace.name
    db.delete(membership)
    if user.last_workspace_id == workspace_id:
        user.last_workspace_id = None
    service.audit(db, user.id, "workspace.left", actor_id=user.id, summary=name,
                  payload={"workspace_id": workspace_id}, request=request)


# ------------------------------------------------------------------------------------------------ avatar
MAX_AVATAR = 5 * 1024 * 1024


@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(not_impersonating),
                        db: Session = Depends(get_db)):
    content = await file.read(MAX_AVATAR + 1)
    if len(content) > MAX_AVATAR:
        raise AppError(_("The image is too large (5 MB at most)."), code="too_large")
    user.avatar_url = service.save_avatar(user, content)
    return {"avatar_url": user.avatar_url}


@router.get("/avatars/{name}")
def avatar(name: str):
    """Profile pictures (public: other members see them; the name is random)."""
    path = service.avatar_path(name)
    if not path:
        raise NotFound(_("Not found."))
    return FileResponse(path, media_type="image/png",
                        headers={**UPLOAD_HEADERS, "Cache-Control": "public, max-age=31536000, immutable"})


# ------------------------------------------------------------------------------------------------ e-mail preferences
class PrefsIn(BaseModel):
    email_security: bool = True   # password, e-mail and two-step sign-in changes
    email_product: bool = True    # reports, tips and product news


@router.get("/notifications", response_model=PrefsIn)
def read_prefs(user: User = Depends(current_user)):
    return PrefsIn(**(user.notification_prefs or {}))


@router.put("/notifications", response_model=PrefsIn)
def write_prefs(data: PrefsIn, user: User = Depends(current_user)):
    user.notification_prefs = data.model_dump()
    return data


# ------------------------------------------------------------------------------------------------ data
@router.get("/export", dependencies=[Depends(rate_limit("account-export", 5, 3600))])
def export(request: Request, user: User = Depends(not_impersonating), db: Session = Depends(get_db)):
    service.audit(db, user.id, "data.exported", actor_id=user.id, request=request)
    return JSONResponse(service.export_user(db, user),
                        headers={"Content-Disposition": f'attachment; filename="account-{user.id}.json"'})


@router.get("/delete-check")
def delete_check(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """What stands in the way of deleting the account: workspaces the person owns alone."""
    return {"workspaces": service.sole_owned(db, user.id), "is_superadmin": user.is_superadmin}


class DeleteIn(BaseModel):
    password: str
    confirm_email: str
    code: str | None = None             # two-step code when it is on
    delete_workspaces: list[int] = []   # workspaces owned alone with nobody else in them


@router.post("/delete", status_code=204, dependencies=[Depends(sensitive)])
def delete_account(data: DeleteIn, request: Request, user: User = Depends(not_impersonating),
                   db: Session = Depends(get_db)):
    """Delete my account: personal data is anonymized, memberships removed, sessions, keys and apps revoked.
    Invoices and audit records stay (legal obligation), without the person's data."""
    _password_ok(user, data.password)
    if data.confirm_email.strip().lower() != user.email.lower():
        raise AppError(_("Type your e-mail address exactly to confirm."), code="confirm_mismatch")
    if user.totp_enabled and not service.check_second_factor(user, data.code or ""):
        raise AppError(_("The code is wrong or expired."), code="bad_code")
    if user.is_superadmin and _active_superadmins(db) <= 1:
        raise AppError(_("You are the last platform administrator. Make someone else administrator first."),
                       code="last_superadmin")
    service.audit(db, user.id, "account.deleted", actor_id=user.id, request=request)
    service.erase_user(db, user, delete_workspaces=data.delete_workspaces)


def _active_superadmins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.is_superadmin.is_(True),
                                                                  User.is_active.is_(True))) or 0

