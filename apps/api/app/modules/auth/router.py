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
from app.core.db import get_db, utcnow
from app.core.deps import (
    ACCESS_COOKIE,
    IMPERSONATION_RETURN_COOKIE,
    REFRESH_COOKIE,
    Unauthorized,
    current_user,
    impersonator_id,
    not_impersonating,
)
from app.core.errors import AppError
from app.core.hardening import rate_limit
from app.core.i18n import LOCALES, _, clean_locale, set_locale
from app.core.mail import send_mail
from app.core.security import (
    create_access_token,
    create_purpose_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.modules.users.service import audit, check_password, check_second_factor
from app.modules.workspaces.models import Membership, Role
from app.modules.workspaces.service import accept_invitation, create_workspace

from .models import User
from .schemas import (
    EmailChange,
    ForgotIn,
    ImpersonatorOut,
    LoginIn,
    MembershipOut,
    MeOut,
    MeUpdate,
    PasswordChange,
    RefreshIn,
    ResetIn,
    SessionOut,
    SignupIn,
    TokenIn,
    TwoFactorLoginIn,
    TwoFactorOut,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def me_payload(db: Session, user: User, request: Request | None = None) -> MeOut:
    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id).order_by(Membership.id)).all()
    current = user.last_workspace_id if any(m.workspace_id == user.last_workspace_id for m in memberships) else (
        memberships[0].workspace_id if memberships else None)
    impersonator = None
    admin_id = impersonator_id(request) if request is not None else None
    if admin_id:
        admin = db.get(User, admin_id)
        expires = getattr(request.state, "impersonation_expires", None)
        impersonator = ImpersonatorOut(id=admin.id, name=admin.name, email=admin.email,
                                       expires_at=datetime.fromtimestamp(expires, timezone.utc) if expires else None)
    return MeOut(user=UserOut.model_validate(user), current_workspace_id=current, impersonator=impersonator,
                 workspaces=[MembershipOut(workspace_id=m.workspace_id, workspace_name=m.workspace.name, role=m.role)
                             for m in memberships])


def cookie_options() -> dict:
    return {"httponly": True, "secure": settings.cookie_secure, "samesite": "lax", "domain": settings.cookie_domain}


def _session(db: Session, user: User, response: Response) -> SessionOut:
    access = create_access_token(user.id, user.token_version)
    refresh = create_refresh_token(user.id, user.token_version)
    cookie = cookie_options()
    response.set_cookie(ACCESS_COOKIE, access, max_age=settings.access_token_minutes * 60, **cookie)
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=settings.refresh_token_days * 86400, path="/api/auth", **cookie)
    response.delete_cookie(IMPERSONATION_RETURN_COOKIE, path="/api/auth", domain=settings.cookie_domain)
    return SessionOut(access_token=access, refresh_token=refresh, me=me_payload(db, user))


def _signed_in(db: Session, user: User, request: Request, response: Response, how: str = "password") -> SessionOut:
    user.last_login_at = utcnow()
    set_locale(user.locale)
    audit(db, user.id, "login", actor_id=user.id, summary=how, request=request)
    return _session(db, user, response)


def security_mail(user: User, subject: str, text: str) -> None:
    """Tell the person about a change to their account (unless they turned these e-mails off)."""
    if (user.notification_prefs or {}).get("email_security", True) is False or user.deleted_at:
        return
    send_mail(user.email, subject, f"<p>{_('Hello {name},', name=user.name)}</p><p>{text}</p>"
              f"<p>{_('If this was not you, reset your password now and contact support.')}</p>", text=text)


def send_verification(user: User) -> None:
    token = create_purpose_token("verify-email", f"{user.id}:{user.email}", hours=48)
    link = f"{settings.web_url.rstrip('/')}/{user.locale}/verify-email?token={token}"
    send_mail(user.email, _("Confirm your e-mail address"),
              f"<p>{_('Hello {name},', name=user.name)}</p><p>{_('Confirm this e-mail address for your account (valid 48 hours):')}</p>"
              f'<p><a href="{link}">{link}</a></p>', text=link)


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
                locale=clean_locale(data.locale), password_changed_at=utcnow())
    db.add(user)
    db.flush()
    if data.invitation_token:
        accept_invitation(db, data.invitation_token, user)
    else:
        create_workspace(db, data.workspace_name.strip(), owner=user)
    user.last_login_at = datetime.now(timezone.utc)
    return _session(db, user, response)


@router.post("/login", response_model=SessionOut | TwoFactorOut, dependencies=[Depends(rate_limit("login", 10, 300))])
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Sign in. With two-step sign-in on, the answer is a challenge (``two_factor_required``) unless ``code`` was
    sent along: then POST the code with the challenge to ``/auth/login/2fa``."""
    user = _find_login(db, data.email)
    if not user or not user.is_active or not verify_password(data.password, user.password_hash):
        raise Unauthorized(_("Wrong e-mail, username or password."), code="bad_credentials")
    if user.totp_enabled:
        if not data.code:
            return TwoFactorOut(challenge=create_purpose_token("2fa", f"{user.id}:{user.token_version}", minutes=5))
        if not check_second_factor(user, data.code):
            raise Unauthorized(_("The code is wrong or expired."), code="bad_code")
        return _signed_in(db, user, request, response, "password+2fa")
    return _signed_in(db, user, request, response)


@router.post("/login/2fa", response_model=SessionOut, dependencies=[Depends(rate_limit("login-2fa", 10, 300))])
def login_two_factor(data: TwoFactorLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    payload = decode_token(data.challenge, "2fa")
    match = re.fullmatch(r"(\d+):(\d+)", payload["sub"]) if payload else None
    user = db.get(User, int(match.group(1))) if match else None
    if not user or not user.is_active or not user.totp_enabled or user.token_version != int(match.group(2)):
        raise Unauthorized(_("This sign-in took too long. Start again."), code="challenge_expired")
    if not check_second_factor(user, data.code):
        raise Unauthorized(_("The code is wrong or expired."), code="bad_code")
    return _signed_in(db, user, request, response, "password+2fa")


@router.post("/refresh", response_model=SessionOut)
def refresh(request: Request, response: Response, data: RefreshIn | None = None, db: Session = Depends(get_db)):
    """New tokens. After a "view as" session of a platform administrator ends (its token is short and has no
    refresh token), this brings the administrator back to their own session."""
    token = (data.refresh_token if data else None) or request.cookies.get(REFRESH_COOKIE) \
        or request.cookies.get(IMPERSONATION_RETURN_COOKIE)
    payload = decode_token(token, "refresh") if token else None
    user = db.get(User, int(payload["sub"])) if payload else None
    if not user or not user.is_active or user.token_version != payload.get("ver"):
        raise Unauthorized(_("Your session has expired. Please sign in again."), code="unauthenticated")
    return _session(db, user, response)


def _end_impersonation(request: Request, db: Session) -> int | None:
    """Record the end of a "view as" session when the current access token is one; returns the administrator."""
    auth = request.headers.get("authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else request.cookies.get(ACCESS_COOKIE)
    payload = decode_token(token, "access") if token else None
    if payload and payload.get("imp"):
        audit(db, int(payload["sub"]), "impersonation.end", actor_id=int(payload["imp"]),
              impersonator_id=int(payload["imp"]), request=request)
        return int(payload["imp"])
    return None


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, domain=settings.cookie_domain)
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth", domain=settings.cookie_domain)
    response.delete_cookie(IMPERSONATION_RETURN_COOKIE, path="/api/auth", domain=settings.cookie_domain)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    _end_impersonation(request, db)
    _clear_cookies(response)


@router.post("/impersonation/end")
def end_impersonation(request: Request, response: Response, db: Session = Depends(get_db)):
    """Stop viewing the app as someone: back to the administrator's own session when it is still valid."""
    _end_impersonation(request, db)
    token = request.cookies.get(IMPERSONATION_RETURN_COOKIE)
    payload = decode_token(token, "refresh") if token else None
    admin = db.get(User, int(payload["sub"])) if payload else None
    if admin and admin.is_active and admin.token_version == payload.get("ver"):
        _session(db, admin, response)
        return {"restored": True}
    _clear_cookies(response)
    return {"restored": False}


@router.post("/logout-everywhere", status_code=204)
def logout_everywhere(request: Request, response: Response, user: User = Depends(not_impersonating),
                      db: Session = Depends(get_db)):
    user.token_version += 1
    audit(db, user.id, "logout.everywhere", actor_id=user.id, request=request)
    _clear_cookies(response)


@router.get("/me", response_model=MeOut)
def me(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return me_payload(db, user, request)


@router.patch("/me", response_model=MeOut)
def update_me(data: MeUpdate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.modules.users.service import remove_avatar_file
    for key, value in data.model_dump(exclude_unset=True).items():
        if key == "locale" and value not in LOCALES:
            continue
        if key == "timezone" and value and not _valid_timezone(value):
            raise AppError(_("Unknown time zone."), code="bad_timezone")
        if key == "username":
            value = _clean_username(db, value or "", user)
        if key == "avatar_url":
            if value and value != user.avatar_url:
                continue  # an avatar is set by uploading it (/account/avatar); here it can only be removed
            if not value and user.avatar_url:
                remove_avatar_file(user.avatar_url)
        setattr(user, key, value)
    return me_payload(db, user, request)


def _valid_timezone(name: str) -> bool:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


@router.post("/password", response_model=SessionOut, dependencies=[Depends(rate_limit("password", 10, 600))])
def change_password(data: PasswordChange, request: Request, response: Response,
                    user: User = Depends(not_impersonating), db: Session = Depends(get_db)):
    """Change the password with the current one. Every other session is signed out; this one gets new tokens."""
    if not verify_password(data.current_password, user.password_hash):
        raise AppError(_("The current password is wrong."), code="bad_password")
    if data.new_password == data.current_password:
        raise AppError(_("Choose a password different from the current one."), code="same_password")
    check_password(data.new_password, email=user.email, name=user.name, min_length=8)
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1
    user.must_change_password = False
    user.password_changed_at = utcnow()
    audit(db, user.id, "password.changed", actor_id=user.id, request=request)
    security_mail(user, _("Your password was changed"), _("The password of your account was just changed."))
    return _session(db, user, response)


@router.post("/email", response_model=MeOut, dependencies=[Depends(rate_limit("email-change", 5, 3600))])
def change_email(data: EmailChange, request: Request, user: User = Depends(not_impersonating),
                 db: Session = Depends(get_db)):
    """Change the sign-in e-mail (with the password). The new address must be confirmed; the old one is told."""
    if not verify_password(data.password, user.password_hash):
        raise AppError(_("The current password is wrong."), code="bad_password")
    email = data.email.strip().lower()
    if email == user.email:
        return me_payload(db, user, request)
    if _find_user(db, email):
        raise AppError(_("An account with this e-mail already exists."), code="email_taken")
    old = user.email
    security_mail(user, _("Your e-mail address was changed"),
                  _("The e-mail address of your account was changed to {email}.", email=email))
    user.email = email
    user.email_verified = False
    audit(db, user.id, "email.changed", actor_id=user.id, summary=f"{old} → {email}", request=request)
    send_verification(user)
    return me_payload(db, user, request)


@router.post("/email/verify-request", status_code=204, dependencies=[Depends(rate_limit("verify-mail", 5, 3600))])
def request_verification(user: User = Depends(current_user)):
    if not user.email_verified:
        send_verification(user)


@router.post("/email/verify", status_code=204, dependencies=[Depends(rate_limit("verify", 20, 3600))])
def verify_email(data: TokenIn, request: Request, db: Session = Depends(get_db)):
    payload = decode_token(data.token, "verify-email")
    match = re.fullmatch(r"(\d+):(.+)", payload["sub"]) if payload else None
    user = db.get(User, int(match.group(1))) if match else None
    if not user or user.email != match.group(2) or user.deleted_at:
        raise AppError(_("This link has expired. Ask for a new one."), code="bad_token")
    if not user.email_verified:
        user.email_verified = True
        audit(db, user.id, "email.verified", actor_id=user.id, request=request)


@router.post("/password/forgot", status_code=204, dependencies=[Depends(rate_limit("forgot", 5, 3600))])
def forgot_password(data: ForgotIn, db: Session = Depends(get_db)):
    user = _find_user(db, data.email)
    if not user or not user.is_active:
        return  # never reveal whether an e-mail exists
    send_reset_link(user)


def send_reset_link(user: User) -> None:
    """E-mail a password reset link (2 hours; it stops working once the password changes)."""
    set_locale(user.locale)
    token = create_purpose_token("reset", f"{user.id}:{user.token_version}", hours=2)
    link = f"{settings.web_url.rstrip('/')}/{user.locale}/reset-password?token={token}"
    send_mail(user.email, _("Reset your password"),
              f"<p>{_('Hello {name},', name=user.name)}</p><p>{_('Use this link to choose a new password (valid 2 hours):')}</p>"
              f'<p><a href="{link}">{link}</a></p>', text=link)


@router.post("/password/reset", response_model=SessionOut | TwoFactorOut,
             dependencies=[Depends(rate_limit("reset", 10, 3600))])
def reset_password(data: ResetIn, request: Request, response: Response, db: Session = Depends(get_db)):
    payload = decode_token(data.token, "reset")
    match = re.fullmatch(r"(\d+):(\d+)", payload["sub"]) if payload else None
    user = db.get(User, int(match.group(1))) if match else None
    if not user or not user.is_active or user.token_version != int(match.group(2)):
        raise AppError(_("This link has expired. Ask for a new one."), code="bad_token")
    check_password(data.password, email=user.email, name=user.name, min_length=8)
    user.password_hash = hash_password(data.password)
    user.token_version += 1
    user.must_change_password = False
    user.password_changed_at = utcnow()
    user.email_verified = True  # the link arrived in this mailbox
    audit(db, user.id, "password.reset", actor_id=user.id, request=request)
    if user.totp_enabled:  # a mailbox alone does not pass the two-step sign-in
        return TwoFactorOut(challenge=create_purpose_token("2fa", f"{user.id}:{user.token_version}", minutes=5))
    return _signed_in(db, user, request, response, "reset")


def ensure_owner_membership(db: Session, user: User, workspace_id: int) -> None:  # used by tests/admin tools
    if not db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.workspace_id == workspace_id)):
        db.add(Membership(user_id=user.id, workspace_id=workspace_id, role=Role.owner))
