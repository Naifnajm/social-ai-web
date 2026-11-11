"""Sign up (creates the user and their company workspace), sign in, refresh, profile, password reset.

Web: tokens are also set as httpOnly cookies. Mobile: send ``Authorization: Bearer <access>`` and refresh
with ``{"refresh_token": ...}``.
"""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import ACCESS_COOKIE, REFRESH_COOKIE, Unauthorized, current_user
from app.core.errors import AppError
from app.core.hardening import rate_limit
from app.core.i18n import LOCALES, _, clean_locale, set_locale
from app.core.mail import send_mail
from app.core.security import (create_access_token, create_purpose_token, create_refresh_token, decode_token,
                               hash_password, verify_password)
from app.modules.workspaces.models import Membership, Role
from app.modules.workspaces.service import accept_invitation, create_workspace

from .models import User
from .schemas import (ForgotIn, LoginIn, MeOut, MeUpdate, MembershipOut, PasswordChange, RefreshIn, ResetIn,
                      SessionOut, SignupIn, UserOut)

router = APIRouter(prefix="/auth", tags=["auth"])


def me_payload(db: Session, user: User) -> MeOut:
    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id).order_by(Membership.id)).all()
    current = user.last_workspace_id if any(m.workspace_id == user.last_workspace_id for m in memberships) else (
        memberships[0].workspace_id if memberships else None)
    return MeOut(user=UserOut.model_validate(user), current_workspace_id=current,
                 workspaces=[MembershipOut(workspace_id=m.workspace_id, workspace_name=m.workspace.name, role=m.role)
                             for m in memberships])


def _session(db: Session, user: User, response: Response) -> SessionOut:
    access = create_access_token(user.id, user.token_version)
    refresh = create_refresh_token(user.id, user.token_version)
    cookie = {"httponly": True, "secure": settings.cookie_secure, "samesite": "lax", "domain": settings.cookie_domain}
    response.set_cookie(ACCESS_COOKIE, access, max_age=settings.access_token_minutes * 60, **cookie)
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=settings.refresh_token_days * 86400, path="/api/auth", **cookie)
    return SessionOut(access_token=access, refresh_token=refresh, me=me_payload(db, user))


def _find_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,29}$")


def _find_login(db: Session, identifier: str) -> User | None:
    """The user signing in with an e-mail or, when there is no "@", a username."""
    identifier = identifier.strip().lower()
    if "@" in identifier:
        return _find_user(db, identifier)
    return db.scalar(select(User).where(User.username == identifier))


def _clean_username(db: Session, value: str, user: User) -> str | None:
    value = value.strip().lower()
    if not value:
        return None
    if not USERNAME.match(value):
        raise AppError(_("A username is 3 to 30 characters: English letters, digits, dot, dash or underscore."),
                       code="bad_username")
    taken = db.scalar(select(User.id).where(User.username == value, User.id != user.id))
    if taken:
        raise AppError(_("This username is taken. Choose another one."), code="username_taken")
    return value


@router.post("/signup", response_model=SessionOut, status_code=201,
             dependencies=[Depends(rate_limit("signup", 5, 3600))])
def signup(data: SignupIn, response: Response, db: Session = Depends(get_db)):
    set_locale(data.locale)
    if _find_user(db, data.email):
        raise AppError(_("An account with this e-mail already exists. Sign in instead."), code="email_taken")
    user = User(email=data.email.lower(), name=data.name.strip(), password_hash=hash_password(data.password),
                locale=clean_locale(data.locale))
    db.add(user)
    db.flush()
    if data.invitation_token:
        accept_invitation(db, data.invitation_token, user)
    else:
        create_workspace(db, data.workspace_name.strip(), owner=user)
    user.last_login_at = datetime.now(timezone.utc)
    return _session(db, user, response)


@router.post("/login", response_model=SessionOut, dependencies=[Depends(rate_limit("login", 10, 300))])
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = _find_login(db, data.email)
    if not user or not user.is_active or not verify_password(data.password, user.password_hash):
        raise Unauthorized(_("Wrong e-mail, username or password."), code="bad_credentials")
    user.last_login_at = datetime.now(timezone.utc)
    set_locale(user.locale)
    return _session(db, user, response)


@router.post("/refresh", response_model=SessionOut)
def refresh(request: Request, response: Response, data: RefreshIn | None = None, db: Session = Depends(get_db)):
    token = (data.refresh_token if data else None) or request.cookies.get(REFRESH_COOKIE)
    payload = decode_token(token, "refresh") if token else None
    user = db.get(User, int(payload["sub"])) if payload else None
    if not user or not user.is_active or user.token_version != payload.get("ver"):
        raise Unauthorized(_("Your session has expired. Please sign in again."), code="unauthenticated")
    return _session(db, user, response)


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(ACCESS_COOKIE, domain=settings.cookie_domain)
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth", domain=settings.cookie_domain)


@router.post("/logout-everywhere", status_code=204)
def logout_everywhere(response: Response, user: User = Depends(current_user)):
    user.token_version += 1
    logout(response)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return me_payload(db, user)


@router.patch("/me", response_model=MeOut)
def update_me(data: MeUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    for key, value in data.model_dump(exclude_unset=True).items():
        if key == "locale" and value not in LOCALES:
            continue
        if key == "username":
            value = _clean_username(db, value or "", user)
        setattr(user, key, value)
    return me_payload(db, user)


@router.post("/password", status_code=204)
def change_password(data: PasswordChange, user: User = Depends(current_user)):
    if not verify_password(data.current_password, user.password_hash):
        raise AppError(_("The current password is wrong."), code="bad_password")
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1


@router.post("/password/forgot", status_code=204, dependencies=[Depends(rate_limit("forgot", 5, 3600))])
def forgot_password(data: ForgotIn, db: Session = Depends(get_db)):
    user = _find_user(db, data.email)
    if not user or not user.is_active:
        return  # never reveal whether an e-mail exists
    set_locale(user.locale)
    token = create_purpose_token("reset", f"{user.id}:{user.token_version}", hours=2)
    link = f"{settings.web_url.rstrip('/')}/{user.locale}/reset-password?token={token}"
    send_mail(user.email, _("Reset your password"),
              f"<p>{_('Hello {name},', name=user.name)}</p><p>{_('Use this link to choose a new password (valid 2 hours):')}</p>"
              f'<p><a href="{link}">{link}</a></p>', text=link)


@router.post("/password/reset", response_model=SessionOut, dependencies=[Depends(rate_limit("reset", 10, 3600))])
def reset_password(data: ResetIn, response: Response, db: Session = Depends(get_db)):
    payload = decode_token(data.token, "reset")
    match = re.fullmatch(r"(\d+):(\d+)", payload["sub"]) if payload else None
    user = db.get(User, int(match.group(1))) if match else None
    if not user or user.token_version != int(match.group(2)):
        raise AppError(_("This link has expired. Ask for a new one."), code="bad_token")
    user.password_hash = hash_password(data.password)
    user.token_version += 1
    return _session(db, user, response)


def ensure_owner_membership(db: Session, user: User, workspace_id: int) -> None:  # used by tests/admin tools
    if not db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.workspace_id == workspace_id)):
        db.add(Membership(user_id=user.id, workspace_id=workspace_id, role=Role.owner))
