"""Settings from environment variables (prefix SAI_) or a .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAI_", env_file=".env", extra="ignore")

    env: str = "dev"  # dev | test | prod
    app_name: str = "Stravica Social"
    secret_key: str = "change-me-in-production-please-32-chars-min"
    database_url: str = "postgresql+psycopg://root:odoo@localhost:5432/stravica_dev"
    redis_url: str = "redis://localhost:6379/0"

    # Public URLs: the API (webhooks, OAuth callbacks, public media links) and the web app (links in emails)
    public_api_url: str = "http://localhost:8000"
    web_url: str = "http://localhost:3000"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8081"]

    access_token_minutes: int = 30
    refresh_token_days: int = 30
    cookie_secure: bool = False
    cookie_domain: str | None = None

    storage_dir: Path = Path("var/storage")
    max_upload_mb: int = 200

    # e-mail (console backend when smtp_host is empty)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True
    mail_from: str = "Stravica Social <no-reply@localhost>"

    default_locale: str = "ar"
    jobs_sync: bool = False  # run background jobs inline (tests, small installs)

    @property
    def is_test(self) -> bool:
        return self.env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
