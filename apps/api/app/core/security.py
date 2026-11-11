"""Passwords (bcrypt) and tokens (JWT: short access token, long refresh token, single-purpose tokens)."""
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def _encode(payload: dict, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({**payload, "iat": now, "exp": now + lifetime}, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(user_id: int, token_version: int) -> str:
    return _encode({"sub": str(user_id), "typ": "access", "ver": token_version},
                   timedelta(minutes=settings.access_token_minutes))


def create_refresh_token(user_id: int, token_version: int) -> str:
    return _encode({"sub": str(user_id), "typ": "refresh", "ver": token_version, "jti": secrets.token_hex(8)},
                   timedelta(days=settings.refresh_token_days))


def create_purpose_token(purpose: str, subject: str, hours: int = 24, minutes: int | None = None) -> str:
    """Single-purpose signed token (password reset, e-mail links, the second sign-in step…)."""
    return _encode({"sub": subject, "typ": purpose}, timedelta(minutes=minutes) if minutes else timedelta(hours=hours))


def decode_token(token: str, expected_type: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("typ") == expected_type else None


def random_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)
