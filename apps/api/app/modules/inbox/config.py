"""Platform-wide inbox configuration (environment variables, prefix ``SAI_``).

``SAI_META_APP_ID`` / ``SAI_META_APP_SECRET`` / ``SAI_META_VERIFY_TOKEN``: the platform's Meta app that receives
Messenger, Instagram, Page-feed and WhatsApp Cloud webhooks for every workspace. A workspace may also use its own
Meta app (stored encrypted in ``inbox_meta_apps``); both secrets are accepted for that workspace's events.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class InboxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAI_", env_file=".env", extra="ignore")

    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_verify_token: str = ""
    meta_graph_version: str = "v24.0"
    inbox_poll_seconds: int = 300


@lru_cache
def inbox_settings() -> InboxSettings:
    return InboxSettings()
