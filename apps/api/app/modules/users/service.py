"""Accounts: the audit trail, password strength, two-step sign-in (TOTP, RFC 6238), sole-owner checks, revoking
access, the GDPR export and erasure.

    audit(db, user.id, "admin.email", actor_id=admin.id, summary="old → new", request=request)
    problem = password_problem(password, email=user.email)       # translated sentence or None
    ok = check_second_factor(user, "123456")                     # TOTP or a recovery code (used once)
"""
import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from datetime import datetime
from urllib.parse import quote

from fastapi import Request
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import utcnow
from app.core.errors import AppError
from app.core.i18n import _
from app.modules.auth.models import User
from app.modules.workspaces.models import Membership, Role, Workspace

from .models import UserEvent

# ------------------------------------------------------------------------------------------------ audit trail


def audit(db: Session, user_id: int | None, type_: str, *, actor_id: int | None = None,
          impersonator_id: int | None = None, summary: str = "", payload: dict | None = None,
          request: Request | None = None) -> UserEvent:
    """Record what happened to an account (never a password, code or token in ``summary``/``payload``)."""
    ip = agent = None
    if request is not None:
        from app.core.hardening import client_ip
        ip = client_ip(request)[:64] or None
        agent = (request.headers.get("user-agent") or "")[:300] or None
    event = UserEvent(user_id=user_id, actor_id=actor_id, impersonator_id=impersonator_id, type=type_[:60],
                      summary=summary[:500] or None, payload=payload, ip=ip, user_agent=agent)
    db.add(event)
    db.flush()
    return event


# ------------------------------------------------------------------------------------------------ passwords
# The most used passwords (and their obvious variants are caught by the rules below).
COMMON_PASSWORDS = {
    "password", "passw0rd", "p@ssword", "p@ssw0rd", "123456", "12345678", "123456789", "1234567890", "qwerty",
    "qwertyuiop", "azerty", "azertyuiop", "abc123", "letmein", "welcome", "admin", "administrator", "iloveyou",
    "monkey", "dragon", "football", "baseball", "sunshine", "princess", "master", "shadow", "superman", "trustno1",
    "starwars", "whatever", "freedom", "changeme", "secret", "login", "computer", "internet", "michael",
    "jennifer", "hello", "hellohello", "default", "root", "toor", "test", "testing", "guest", "stravica",
    "socialai", "wachtwoord", "passwort", "motdepasse", "mot2passe", "qazwsx", "zaq12wsx", "1q2w3e4r",
    "1qaz2wsx", "q1w2e3r4", "asdfgh", "asdfghjkl", "zxcvbnm", "11111111", "00000000", "88888888", "987654321",
    "ilovegod", "allahakbar", "bismillah", "saudiarabia", "riyadh", "admin123", "password1", "welcome1",
}
SEQUENCES = ("0123456789012345678901234567890", "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz",
             "qwertyuiopasdfghjklzxcvbnm", "azertyuiopqsdfghjklmwxcvbn")


def password_problem(password: str, *, email: str | None = None, name: str | None = None,
                     min_length: int = 12) -> str | None:
    """Why ``password`` is too weak (a translated sentence), or None when it is good enough."""
    if len(password) < min_length:
        return _("The password needs at least {n} characters.", n=min_length)
    if len(password) > 128:
        return _("The password can have at most 128 characters.")
    lower = password.lower()
    core = re.sub(r"[\d!@#$%^&*._\-+=?]+$", "", re.sub(r"^[\d!@#$%^&*._\-+=?]+", "", lower))
    if lower in COMMON_PASSWORDS or core in COMMON_PASSWORDS or len(set(lower)) <= 3:
        return _("This password is too common or too simple. Use a longer sentence or a password manager.")
    if any(lower in seq or lower[::-1] in seq for seq in SEQUENCES):
        return _("This password is too common or too simple. Use a longer sentence or a password manager.")
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", lower):
        return _("Do not use an e-mail address as the password.")
    local = (email or "").lower().split("@")[0]
    if email and (lower == email.lower() or (len(local) >= 4 and local in lower and len(lower) - len(local) < 6)):
        return _("The password must not look like your e-mail address.")
    first = (name or "").strip().lower().split(" ")[0]
    if len(first) >= 4 and first in lower and len(lower) - len(first) < 6:
        return _("The password must not look like your name.")
    return None


def check_password(password: str, *, email: str | None = None, name: str | None = None, min_length: int = 12) -> None:
    problem = password_problem(password, email=email, name=name, min_length=min_length)
    if problem:
        raise AppError(problem, code="weak_password")


def generate_password() -> str:
    """A strong random password (about 120 bits), easy to type: four groups of five characters."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        raw = "".join(secrets.choice(alphabet) for _i in range(20))
        value = "-".join(raw[i:i + 5] for i in range(0, 20, 5))
        if any(c.isdigit() for c in value) and any(c.isupper() for c in value) and any(c.islower() for c in value):
            return value


# ------------------------------------------------------------------------------------------------ two-step sign-in
TOTP_PERIOD = 30
TOTP_DIGITS = 6
RECOVERY_CODES = 10


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _totp_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** TOTP_DIGITS).zfill(TOTP_DIGITS)


def totp_now(secret: str, at: float | None = None) -> str:
    return _totp_at(secret, int((at if at is not None else time.time()) // TOTP_PERIOD))


def otpauth_uri(secret: str, account: str) -> str:
    issuer = settings.app_name
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}")


def verify_totp(user: User, code: str, secret: str | None = None) -> bool:
    """A 6-digit code of the current 30 s step (± one for clock drift), never one already used."""
    secret = secret or user.totp_secret
    code = re.sub(r"\s", "", code or "")
    if not secret or not re.fullmatch(r"\d{6}", code):
        return False
    now = int(time.time() // TOTP_PERIOD)
    matched = None
    for step in (now - 1, now, now + 1):  # compare all of them: the time taken does not tell which matched
        if hmac.compare_digest(_totp_at(secret, step), code):
            matched = step
    if matched is None or matched <= (user.totp_last_step or 0):
        return False
    user.totp_last_step = matched
    return True


def _code_hash(code: str) -> str:
    return hashlib.sha256(re.sub(r"[\s-]", "", code).lower().encode()).hexdigest()


def new_recovery_codes(user: User) -> list[str]:
    """Replace the person's recovery codes; returns the plain codes (shown once, only their hashes are kept)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    codes = []
    for _i in range(RECOVERY_CODES):
        raw = "".join(secrets.choice(alphabet) for _j in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    user.recovery_codes = [_code_hash(c) for c in codes]
    return codes


def use_recovery_code(user: User, code: str) -> bool:
    wanted = _code_hash(code or "")
    left, found = [], False
    for stored in user.recovery_codes or []:
        if not found and hmac.compare_digest(stored, wanted):
            found = True
            continue
        left.append(stored)
    if found:
        user.recovery_codes = left
    return found


def check_second_factor(user: User, code: str) -> bool:
    code = (code or "").strip()
    if re.fullmatch(r"\d{3}\s?\d{3}", code):
        return verify_totp(user, code)
    return use_recovery_code(user, code)


def reset_two_factor(user: User) -> None:
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_last_step = None
    user.recovery_codes = None


# ------------------------------------------------------------------------------------------------ workspaces
def sole_owned(db: Session, user_id: int) -> list[dict]:
    """Workspaces where ``user_id`` is the only owner: someone else must own them (or they are deleted) before the
    person can leave them or be erased. ``action`` says which: "transfer" when there are other members, else
    "delete"."""
    out = []
    owned = db.scalars(select(Membership).where(Membership.user_id == user_id, Membership.role == Role.owner)).all()
    for membership in owned:
        owners = db.scalar(select(func.count()).select_from(Membership).where(
            Membership.workspace_id == membership.workspace_id, Membership.role == Role.owner)) or 0
        if owners > 1:
            continue
        others = db.scalar(select(func.count()).select_from(Membership).where(
            Membership.workspace_id == membership.workspace_id, Membership.user_id != user_id)) or 0
        out.append({"workspace_id": membership.workspace_id, "workspace_name": membership.workspace.name,
                    "other_members": others, "action": "transfer" if others else "delete"})
    return out


def delete_workspace(db: Session, workspace: Workspace) -> None:
    """Delete a workspace and everything in it (its files too). Billing and audit rows stay (workspace set to
    null). Refused while a payment provider still bills it."""
    from app.core.models import Media
    from app.core.storage import delete_media_file
    from app.modules.billing.models import Subscription
    sub = db.scalar(select(Subscription).where(Subscription.workspace_id == workspace.id))
    if sub and sub.provider == "stripe" and sub.status in ("active", "past_due", "trialing") \
            and sub.provider_subscription_id:
        raise AppError(_("“{name}” still has a paid subscription. Cancel it first.", name=workspace.name),
                       code="has_subscription")
    for media in db.scalars(select(Media).where(Media.workspace_id == workspace.id)):
        try:
            delete_media_file(media)
        except OSError:
            pass
    db.execute(update(User).where(User.last_workspace_id == workspace.id).values(last_workspace_id=None))
    db.flush()
    db.execute(delete(Workspace).where(Workspace.id == workspace.id))
    db.expire_all()


# ------------------------------------------------------------------------------------------------ access
def revoke_access(db: Session, user: User) -> dict:
    """Revoke every personal API key and connected app of the person (in all workspaces)."""
    from app.modules.connect import auth as connect_auth
    from app.modules.connect.models import ApiKey, OAuthGrant
    now = utcnow()
    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))).all()
    for key in keys:
        key.revoked_at = now
    grants = db.scalars(select(OAuthGrant).where(OAuthGrant.user_id == user.id, OAuthGrant.revoked_at.is_(None))).all()
    for grant in grants:
        connect_auth.revoke_grant(db, grant)
    return {"api_keys": len(keys), "apps": len(grants)}


# ------------------------------------------------------------------------------------------------ GDPR
def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def export_user(db: Session, user: User) -> dict:
    """Everything the platform keeps about the person (GDPR art. 15/20), as JSON. No secrets: no password hash,
    no two-step secret, no key hashes."""
    from app.core.models import Media, Notification
    from app.modules.ai.models import AIUsage
    from app.modules.connect.models import ApiKey, ConnectAudit, OAuthGrant
    from app.modules.support.models import SupportMessage, SupportTicket
    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    tickets = db.scalars(select(SupportTicket).where(SupportTicket.user_id == user.id)).all()
    usage = db.execute(select(AIUsage.workspace_id, func.count(), func.coalesce(func.sum(AIUsage.price), 0.0))
                       .where(AIUsage.user_id == user.id).group_by(AIUsage.workspace_id)).all()
    return {
        "exported_at": utcnow().isoformat(),
        "profile": {"id": user.id, "email": user.email, "username": user.username, "name": user.name,
                    "locale": user.locale, "timezone": user.timezone, "avatar_url": user.avatar_url,
                    "email_verified": user.email_verified, "two_factor_enabled": user.totp_enabled,
                    "created_at": _iso(user.created_at), "last_login_at": _iso(user.last_login_at),
                    "password_changed_at": _iso(user.password_changed_at),
                    "notification_prefs": user.notification_prefs or {}},
        "workspaces": [{"workspace_id": m.workspace_id, "name": m.workspace.name, "role": m.role,
                        "joined_at": _iso(m.created_at)} for m in memberships],
        "api_keys": [{"name": k.name, "prefix": k.prefix, "scopes": k.scopes, "workspace_id": k.workspace_id,
                      "created_at": _iso(k.created_at), "expires_at": _iso(k.expires_at),
                      "revoked_at": _iso(k.revoked_at)}
                     for k in db.scalars(select(ApiKey).where(ApiKey.user_id == user.id))],
        "connected_apps": [{"app": g.client.client_name, "scopes": g.scopes, "workspace_id": g.workspace_id,
                            "created_at": _iso(g.created_at), "last_used_at": _iso(g.last_used_at),
                            "revoked_at": _iso(g.revoked_at)}
                           for g in db.scalars(select(OAuthGrant).where(OAuthGrant.user_id == user.id))],
        "connected_app_activity": [{"app": a.client_name, "tool": a.tool, "ok": a.ok, "summary": a.summary,
                                    "at": _iso(a.created_at)}
                                   for a in db.scalars(select(ConnectAudit).where(ConnectAudit.user_id == user.id)
                                                       .order_by(ConnectAudit.id.desc()).limit(500))],
        "support_tickets": [{"subject": t.subject, "category": t.category, "status": t.status,
                             "created_at": _iso(t.created_at),
                             "messages": [{"from_team": m.staff, "body": m.body, "at": _iso(m.created_at)}
                                          for m in t.messages]} for t in tickets],
        "support_messages_written": db.scalar(select(func.count()).select_from(SupportMessage).where(
            SupportMessage.user_id == user.id)) or 0,
        "notifications": [{"kind": n.kind, "title": n.title, "body": n.body, "at": _iso(n.created_at),
                           "read_at": _iso(n.read_at)}
                          for n in db.scalars(select(Notification).where(Notification.user_id == user.id)
                                              .order_by(Notification.id.desc()).limit(500))],
        "files_uploaded": [{"filename": m.filename, "mimetype": m.mimetype, "size": m.size,
                            "workspace_id": m.workspace_id, "at": _iso(m.created_at)}
                           for m in db.scalars(select(Media).where(Media.created_by_id == user.id)
                                               .order_by(Media.id.desc()).limit(2000))],
        "ai_usage": [{"workspace_id": w, "calls": n, "charged_usd": round(float(c), 4)} for w, n, c in usage],
        "account_events": [{"type": e.type, "summary": e.summary, "ip": e.ip, "at": _iso(e.created_at),
                            "by_administrator": bool(e.actor_id and e.actor_id != user.id)}
                           for e in db.scalars(select(UserEvent).where(UserEvent.user_id == user.id)
                                               .order_by(UserEvent.id.desc()).limit(1000))],
    }


def erase_user(db: Session, user: User, *, delete_workspaces: list[int] | None = None) -> None:
    """GDPR erasure: anonymize the account (the row stays so billing and audit rows keep pointing somewhere),
    remove memberships, revoke every session, key and connected app. Workspaces the person owns alone must have
    another owner first, or be listed in ``delete_workspaces`` when nobody else is in them."""
    from app.core.models import Device, Notification
    blockers = sole_owned(db, user.id)
    deletable = {b["workspace_id"] for b in blockers if b["action"] == "delete"}
    wanted = set(delete_workspaces or [])
    if any(b["action"] == "transfer" for b in blockers) or deletable - wanted:
        raise AppError(_("Some workspaces have no other owner. Transfer or delete them first."),
                       code="sole_owner", workspaces=blockers)
    for workspace_id in sorted(deletable & wanted):
        delete_workspace(db, db.get(Workspace, workspace_id))
    revoke_access(db, user)
    db.execute(delete(Membership).where(Membership.user_id == user.id))
    db.execute(delete(Device).where(Device.user_id == user.id))
    db.execute(delete(Notification).where(Notification.user_id == user.id))
    db.refresh(user)
    if user.avatar_url:
        remove_avatar_file(user.avatar_url)
    user.email = f"deleted-{user.id}@deleted.invalid"
    user.username = None
    user.name = _("Deleted user")
    user.password_hash = None
    user.avatar_url = None
    reset_two_factor(user)
    user.is_active = False
    user.is_superadmin = False
    user.email_verified = False
    user.must_change_password = False
    user.notification_prefs = None
    user.last_workspace_id = None
    user.deleted_at = utcnow()
    user.token_version += 1
    db.flush()


# ------------------------------------------------------------------------------------------------ avatars
AVATAR_PREFIX = "/api/account/avatars/"


def _avatar_dir():
    from pathlib import Path
    path = Path(settings.storage_dir) / "avatars"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_avatar(user: User, content: bytes) -> str:
    """Store a square 256 px PNG of the uploaded image; returns its URL (a random name: nothing to guess)."""
    from io import BytesIO

    from PIL import Image, ImageOps
    try:
        image = Image.open(BytesIO(content))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception:  # noqa: BLE001 - anything Pillow cannot read is not an image we accept
        raise AppError(_("This file is not an image we can read."), code="bad_image") from None
    image = ImageOps.fit(image, (256, 256))
    name = f"{user.id}-{secrets.token_urlsafe(12)}.png"
    buffer = BytesIO()
    image.save(buffer, "PNG", optimize=True)
    (_avatar_dir() / name).write_bytes(buffer.getvalue())
    if user.avatar_url:
        remove_avatar_file(user.avatar_url)
    return AVATAR_PREFIX + name


def avatar_path(name: str):
    if not re.fullmatch(r"\d+-[A-Za-z0-9_-]{10,40}\.png", name):
        return None
    path = _avatar_dir() / name
    return path if path.exists() else None


def remove_avatar_file(url: str) -> None:
    if url.startswith(AVATAR_PREFIX):
        path = avatar_path(url[len(AVATAR_PREFIX):])
        if path:
            path.unlink(missing_ok=True)
