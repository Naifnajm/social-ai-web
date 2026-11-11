"""Two-step sign-in and passkeys.

* Authenticator app: after the password, a 6-digit code from Google Authenticator, Microsoft Authenticator,
  Apple Passwords, 1Password… (TOTP, RFC 6238). Ten single-use recovery codes are given when it is switched on.
* Passkeys: sign in with Face ID, Touch ID, Windows Hello or a phone, without a password (WebAuthn). A passkey is
  already two factors (the device and the face or fingerprint), so it does not ask for a code as well.

    POST /api/auth/login                 a session, or {"two_step": true, "challenge": ...} when the app is on
    POST /api/auth/login/two-step        {challenge, code}              code: 6 digits or a recovery code
    GET  /api/auth/security              what is set up
    POST /api/auth/two-step/setup        secret + QR code to scan (not active until confirmed)
    POST /api/auth/two-step/enable       {code}                         returns the recovery codes, once
    POST /api/auth/two-step/disable      {password, code}
    POST /api/auth/two-step/recovery     {code}                         new recovery codes
    POST /api/auth/passkeys/register     options for the browser; then .../register/verify {token, credential, name}
    POST /api/auth/passkeys/login        options for the browser; then .../login/verify {token, credential}
    PATCH/DELETE /api/auth/passkeys/{id}
"""
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import pyotp
import segno
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import Unauthorized, current_user
from app.core.errors import AppError, NotFound
from app.core.hardening import first_use, rate_limit
from app.core.i18n import _, set_locale
from app.core.security import create_purpose_token, decode_token, verify_password

from .models import Passkey, User

router = APIRouter(tags=["auth"])  # mounted inside the /auth router
CHALLENGE_MINUTES = 10
RECOVERY_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i


# ------------------------------------------------------------------ helpers
def relying_party() -> tuple[str, str]:
    """``(rp_id, origin)`` of the web app: passkeys are bound to this domain."""
    url = urlparse(settings.web_url)
    return url.hostname or "localhost", f"{url.scheme}://{url.netloc}"


def two_step_challenge(user: User) -> dict:
    """What /login answers instead of a session when the account asks for a code."""
    token = create_purpose_token("two-step", f"{user.id}:{user.token_version}", minutes=CHALLENGE_MINUTES)
    return {"two_step": True, "challenge": token, "methods": ["totp", "recovery"]}


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _clean(code: str | None) -> str:
    return re.sub(r"[\s-]", "", (code or "")).lower()


def _new_recovery_codes(user: User) -> list[str]:
    codes = ["".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10)) for _ in range(RECOVERY_COUNT)]
    user.recovery_codes = [_hash(code) for code in codes]
    return [f"{code[:5]}-{code[5:]}" for code in codes]


def check_code(user: User, code: str | None, *, recovery: bool = True) -> bool:
    """A current authenticator code (each works once) or, when allowed, an unused recovery code (used up)."""
    code = _clean(code)
    if re.fullmatch(r"\d{6}", code) and user.totp_secret:
        totp = pyotp.TOTP(user.totp_secret)
        now = int(time.time()) // 30
        for step in (now - 1, now, now + 1):  # 30 seconds of clock drift either way
            if step > (user.totp_last_step or 0) and hmac.compare_digest(totp.generate_otp(step), code):
                user.totp_last_step = step
                return True
        return False
    if recovery and re.fullmatch(r"[a-z0-9]{10}", code) and user.recovery_codes:
        hashed = _hash(code)
        if hashed in user.recovery_codes:
            user.recovery_codes = [h for h in user.recovery_codes if h != hashed]
            return True
    return False


def _require_code(user: User, code: str | None) -> None:
    if not check_code(user, code):
        raise AppError(_("This code is not right, or it was already used. Try the newest code."), code="bad_code")


# ------------------------------------------------------------------ schemas
class CodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)


class ChallengeIn(CodeIn):
    challenge: str = Field(min_length=10, max_length=2000)


class DisableIn(CodeIn):
    password: str


class PasskeyOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    last_used_at: datetime | None = None


class SecurityOut(BaseModel):
    two_step: bool
    two_step_since: datetime | None = None
    recovery_codes_left: int = 0
    passkeys: list[PasskeyOut]


class SetupOut(BaseModel):
    secret: str
    uri: str
    qr_svg: str


class RecoveryOut(BaseModel):
    recovery_codes: list[str]


class OptionsOut(BaseModel):
    token: str
    options: dict


class RegisterIn(BaseModel):
    token: str = Field(max_length=2000)
    credential: dict
    name: str | None = Field(default=None, max_length=80)


class PasskeyLoginIn(BaseModel):
    token: str = Field(max_length=2000)
    credential: dict


class PasskeyRename(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _security(user: User) -> SecurityOut:
    return SecurityOut(two_step=user.two_step, two_step_since=user.totp_enabled_at,
                       recovery_codes_left=len(user.recovery_codes or []) if user.two_step else 0,
                       passkeys=[PasskeyOut(id=p.id, name=p.name, created_at=p.created_at, last_used_at=p.last_used_at)
                                 for p in user.passkeys])


# ------------------------------------------------------------------ second step of the sign-in
@router.post("/login/two-step", dependencies=[Depends(rate_limit("two-step", 10, 300))])
def login_two_step(data: ChallengeIn, response: Response, db: Session = Depends(get_db)):
    from .router import session_for  # late import: router imports this module

    payload = decode_token(data.challenge, "two-step")
    match = re.fullmatch(r"(\d+):(\d+)", payload["sub"]) if payload else None
    user = db.get(User, int(match.group(1))) if match else None
    if not user or not user.is_active or user.token_version != int(match.group(2)) or not user.two_step:
        raise Unauthorized(_("This sign-in has expired. Enter your password again."), code="two_step_expired")
    set_locale(user.locale)
    _require_code(user, data.code)
    user.last_login_at = datetime.now(timezone.utc)
    return session_for(db, user, response)


# ------------------------------------------------------------------ authenticator app
@router.get("/security", response_model=SecurityOut)
def security(user: User = Depends(current_user)):
    return _security(user)


@router.post("/two-step/setup", response_model=SetupOut)
def two_step_setup(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.two_step:
        raise AppError(_("Two-step sign-in is already on."), code="two_step_on")
    user.totp_secret = pyotp.random_base32()
    user.totp_last_step = None
    db.flush()
    uri = pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.username or user.email,
                                                         issuer_name=settings.app_name)
    svg = segno.make(uri, error="m").svg_inline(scale=5, border=2, dark="#0a0a0a", light="#ffffff")
    return SetupOut(secret=user.totp_secret, uri=uri, qr_svg=svg)


@router.post("/two-step/enable", response_model=RecoveryOut)
def two_step_enable(data: CodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.two_step:
        raise AppError(_("Two-step sign-in is already on."), code="two_step_on")
    if not user.totp_secret:
        raise AppError(_("Start the setup again."), code="two_step_setup")
    if not check_code(user, data.code, recovery=False):
        raise AppError(_("This code is not right. Check that the phone's clock is automatic and try the newest "
                         "code."), code="bad_code")
    user.totp_enabled_at = datetime.now(timezone.utc)
    codes = _new_recovery_codes(user)
    db.flush()
    return RecoveryOut(recovery_codes=codes)


@router.post("/two-step/disable", response_model=SecurityOut)
def two_step_disable(data: DisableIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.two_step:
        return _security(user)
    if not verify_password(data.password, user.password_hash):
        raise AppError(_("The password is not right."), code="bad_password")
    _require_code(user, data.code)
    user.totp_secret = user.totp_enabled_at = user.totp_last_step = user.recovery_codes = None
    db.flush()
    return _security(user)


@router.post("/two-step/recovery", response_model=RecoveryOut)
def two_step_recovery(data: CodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.two_step:
        raise AppError(_("Two-step sign-in is off."), code="two_step_off")
    if not check_code(user, data.code, recovery=False):
        raise AppError(_("This code is not right, or it was already used. Try the newest code."), code="bad_code")
    codes = _new_recovery_codes(user)
    db.flush()
    return RecoveryOut(recovery_codes=codes)


def reset_two_step(user: User) -> None:
    """Support: the person lost the phone. Switches the app off and removes the passkeys."""
    user.totp_secret = user.totp_enabled_at = user.totp_last_step = user.recovery_codes = None
    user.passkeys.clear()
    user.token_version += 1


# ------------------------------------------------------------------ passkeys
def _options(options) -> dict:
    return json.loads(options_to_json(options))


def _challenge_of(token: str, purpose: str) -> tuple[str, bytes]:
    payload = decode_token(token, purpose)
    if not payload or ":" not in payload.get("sub", ""):
        raise AppError(_("This request has expired. Try again."), code="passkey_expired")
    subject, challenge = payload["sub"].rsplit(":", 1)
    if not first_use(f"{purpose}:{challenge}", 15 * 60):
        raise AppError(_("This request has expired. Try again."), code="passkey_expired")
    return subject, base64url_to_bytes(challenge)


@router.post("/passkeys/register", response_model=OptionsOut)
def passkey_register_options(user: User = Depends(current_user)):
    rp_id, _origin = relying_party()
    options = generate_registration_options(
        rp_id=rp_id, rp_name=settings.app_name, user_id=f"sai-{user.id}".encode(),
        user_name=user.username or user.email, user_display_name=user.name,
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED,
                                                               user_verification=UserVerificationRequirement.PREFERRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id))
                             for p in user.passkeys])
    token = create_purpose_token("passkey-register", f"{user.id}:{bytes_to_base64url(options.challenge)}", minutes=5)
    return OptionsOut(token=token, options=_options(options))


@router.post("/passkeys/register/verify", response_model=SecurityOut)
def passkey_register(data: RegisterIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    subject, challenge = _challenge_of(data.token, "passkey-register")
    if subject != str(user.id):
        raise AppError(_("This request has expired. Try again."), code="passkey_expired")
    rp_id, origin = relying_party()
    try:
        verified = verify_registration_response(credential=data.credential, expected_challenge=challenge,
                                                expected_rp_id=rp_id, expected_origin=origin)
    except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
        raise AppError(_("The passkey could not be saved: {reason}", reason=str(exc)[:200]), code="passkey_failed")
    credential_id = bytes_to_base64url(verified.credential_id)
    if db.scalar(select(Passkey.id).where(Passkey.credential_id == credential_id)):
        raise AppError(_("This passkey is already saved."), code="passkey_exists")
    transports = (data.credential.get("response") or {}).get("transports")
    user.passkeys.append(Passkey(credential_id=credential_id,
                                 public_key=bytes_to_base64url(verified.credential_public_key),
                                 sign_count=verified.sign_count, name=(data.name or "Passkey").strip()[:80],
                                 transports=transports if isinstance(transports, list) else None))
    db.flush()
    return _security(user)


@router.post("/passkeys/login", response_model=OptionsOut, dependencies=[Depends(rate_limit("passkey", 20, 300))])
def passkey_login_options():
    rp_id, _origin = relying_party()
    options = generate_authentication_options(rp_id=rp_id, user_verification=UserVerificationRequirement.PREFERRED)
    token = create_purpose_token("passkey-login", f"-:{bytes_to_base64url(options.challenge)}", minutes=5)
    return OptionsOut(token=token, options=_options(options))


@router.post("/passkeys/login/verify", dependencies=[Depends(rate_limit("passkey", 20, 300))])
def passkey_login(data: PasskeyLoginIn, response: Response, db: Session = Depends(get_db)):
    from .router import session_for

    _subject, challenge = _challenge_of(data.token, "passkey-login")
    credential_id = str(data.credential.get("id") or "")
    passkey = db.scalar(select(Passkey).where(Passkey.credential_id == credential_id)) if credential_id else None
    if not passkey or not passkey.user.is_active:
        raise Unauthorized(_("This passkey is not linked to an account here. Sign in with your password."),
                           code="passkey_unknown")
    rp_id, origin = relying_party()
    try:
        verified = verify_authentication_response(
            credential=data.credential, expected_challenge=challenge, expected_rp_id=rp_id, expected_origin=origin,
            credential_public_key=base64url_to_bytes(passkey.public_key),
            credential_current_sign_count=passkey.sign_count)
    except (WebAuthnException, ValueError, KeyError, TypeError):
        raise Unauthorized(_("The passkey could not be checked. Try again or sign in with your password."),
                           code="passkey_failed")
    user = passkey.user
    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = user.last_login_at = datetime.now(timezone.utc)
    set_locale(user.locale)
    return session_for(db, user, response)


def _passkey(user: User, passkey_id: int) -> Passkey:
    passkey = next((p for p in user.passkeys if p.id == passkey_id), None)
    if not passkey:
        raise NotFound(_("Passkey not found."))
    return passkey


@router.patch("/passkeys/{passkey_id}", response_model=SecurityOut)
def passkey_rename(passkey_id: int, data: PasskeyRename, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    _passkey(user, passkey_id).name = data.name.strip()
    db.flush()
    return _security(user)


@router.delete("/passkeys/{passkey_id}", response_model=SecurityOut)
def passkey_delete(passkey_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.passkeys.remove(_passkey(user, passkey_id))
    db.flush()
    return _security(user)
