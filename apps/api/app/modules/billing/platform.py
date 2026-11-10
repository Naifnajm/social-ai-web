"""Platform-wide settings (superadmin): default AI keys for platform-provided AI credits, Stripe price ids…

    from app.modules.billing import platform
    key = platform.ai_key(db, "openai")          # decrypted platform key or None (AI builder: platform credits)
    platform.get_setting(db, "billing.trial_days", 14)

Plain values are JSON; secrets are stored encrypted (``PlatformSetting.secret``) and never returned by the API.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PlatformSetting

# Platform-provided AI: providers whose key the platform pays for (usage is billed as plan "AI credits").
AI_PROVIDERS = ("openai", "anthropic", "gemini", "elevenlabs")

# Settings editable in the admin (key -> type). Secrets are write-only (the API returns configured: bool).
SETTINGS_SCHEMA: dict[str, str] = {
    "ai.default_provider": "str",          # openai | anthropic | gemini
    "ai.default_text_model": "str",
    "ai.default_image_model": "str",
    **{f"ai.{name}_api_key": "secret" for name in AI_PROVIDERS},
    "billing.trial_days": "int",
    "billing.grace_days": "int",
    "billing.stripe_prices": "dict",       # {"pro_month": "price_..."} — overrides the environment
    "platform.announcement": "str",        # optional banner text shown to every workspace
    "platform.signups_open": "bool",
}


def _row(db: Session, key: str) -> PlatformSetting | None:
    return db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))


def get_setting(db: Session, key: str, default=None):
    row = _row(db, key)
    return default if row is None or row.value is None else row.value


def set_setting(db: Session, key: str, value, user_id: int | None = None) -> None:
    row = _row(db, key)
    if row is None:
        row = PlatformSetting(key=key)
        db.add(row)
    row.value = value
    row.updated_by_id = user_id
    db.flush()


def get_secret(db: Session, key: str) -> str | None:
    row = _row(db, key)
    return row.secret if row else None


def set_secret(db: Session, key: str, value: str | None, user_id: int | None = None) -> None:
    row = _row(db, key)
    if row is None:
        row = PlatformSetting(key=key)
        db.add(row)
    row.secret = value or None
    row.updated_by_id = user_id
    db.flush()


def ai_key(db: Session, provider_type: str) -> str | None:
    """Platform API key for a provider type (for AI usage paid by the platform and billed as AI credits)."""
    return get_secret(db, f"ai.{provider_type}_api_key")


def all_settings(db: Session) -> dict:
    rows = {row.key: row for row in db.scalars(select(PlatformSetting)).all()}
    out: dict = {}
    for key, kind in SETTINGS_SCHEMA.items():
        row = rows.get(key)
        if kind == "secret":
            out[key] = bool(row and row.secret)
        else:
            out[key] = row.value if row else None
    return out
