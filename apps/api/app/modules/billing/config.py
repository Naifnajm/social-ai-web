"""Billing configuration from the environment (prefix ``SAI_``), separate from the core settings.

    SAI_STRIPE_SECRET_KEY=sk_live_...           SAI_STRIPE_WEBHOOK_SECRET=whsec_...
    SAI_STRIPE_PRICE_STARTER_MONTH=price_...    SAI_STRIPE_PRICE_STARTER_YEAR=price_...   (same for PRO, BUSINESS)
    SAI_BILLING_PROVIDER=stripe                 SAI_BILLING_GRACE_DAYS=7

Price ids can also be set (and override the environment) in the platform admin › Settings.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BillingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAI_", env_file=".env", extra="ignore")

    billing_provider: str = "stripe"  # stripe | moyasar (stub)
    billing_grace_days: int = 7       # days a past_due workspace keeps working before it becomes read-only
    billing_trial_reminder_days: int = 3

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_api_base: str = "https://api.stripe.com"
    stripe_webhook_tolerance: int = 300  # seconds
    stripe_price_starter_month: str = ""
    stripe_price_starter_year: str = ""
    stripe_price_pro_month: str = ""
    stripe_price_pro_year: str = ""
    stripe_price_business_month: str = ""
    stripe_price_business_year: str = ""

    moyasar_secret_key: str = ""
    moyasar_publishable_key: str = ""
    moyasar_webhook_secret: str = ""

    def stripe_price(self, plan: str, interval: str) -> str:
        return getattr(self, f"stripe_price_{plan}_{interval}", "") or ""


@lru_cache
def billing_settings() -> BillingSettings:
    return BillingSettings()
