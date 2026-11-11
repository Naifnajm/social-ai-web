"""Server-side translations for messages the API returns (errors, notifications, e-mails).

Write messages in English with named placeholders: ``_("Post “{name}” was published.", name=post.name)``.
Catalogs live in ``app/i18n/<locale>.json`` and ``app/modules/<feature>/i18n/<locale>.json``
({english: translation}); all files are merged. The locale of the current request
comes from the user's preference or the Accept-Language header (set by the middleware in main.py).

A locale without a catalog (Dutch, German, French for now) gets the English messages, never the Arabic ones.
"""
import json
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from .config import settings

LOCALES = ("ar", "en", "nl", "de", "fr")
# English names of the same languages, for prompts ("Write in Dutch.")
LANGUAGE_NAMES = {"ar": "Arabic", "en": "English", "nl": "Dutch", "de": "German", "fr": "French"}
_current = ContextVar("sai_locale", default=settings.default_locale)


@lru_cache
def _catalog(locale: str) -> dict:
    root = Path(__file__).resolve().parent.parent
    catalog: dict = {}
    for path in [root / "i18n" / f"{locale}.json", *sorted((root / "modules").glob(f"*/i18n/{locale}.json"))]:
        if path.exists():
            catalog.update(json.loads(path.read_text(encoding="utf-8")))
    return catalog


def clean_locale(locale: str | None) -> str:
    """``locale`` when the app has it, else the default one."""
    return locale if locale in LOCALES else settings.default_locale


def set_locale(locale: str | None) -> None:
    _current.set(clean_locale(locale))


def get_locale() -> str:
    return _current.get()


def pick_locale(accept_language: str | None) -> str:
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LOCALES:
            return code
    return settings.default_locale


def _(message: str, /, **kwargs) -> str:
    text = _catalog(get_locale()).get(message) or message
    return text.format(**kwargs) if kwargs else text


def lazy(message: str) -> str:
    """Mark a module-level string for extraction; translate it later with ``_(...)``."""
    return message
