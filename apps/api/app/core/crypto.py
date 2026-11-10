"""Encryption at rest for secrets (API keys, access tokens) — Fernet with a key derived from SAI_SECRET_KEY."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from .config import settings


def _fernet() -> Fernet:
    key = hashlib.sha256(("sai-secrets:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str | None) -> str | None:
    if not value:
        return value
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


class EncryptedString(TypeDecorator):
    """A string column stored encrypted. Never returned by the API (schemas expose `has_xxx` flags instead)."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)
