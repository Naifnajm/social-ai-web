"""Payment providers by name. The active one is ``SAI_BILLING_PROVIDER`` (default: stripe)."""
from ..config import billing_settings
from .base import CheckoutResult, Invoice, PaymentProvider, WebhookError, WebhookEvent
from .moyasar import MoyasarProvider
from .stripe import StripeProvider

PROVIDERS: dict[str, PaymentProvider] = {"stripe": StripeProvider(), "moyasar": MoyasarProvider()}


def get_provider(name: str | None = None) -> PaymentProvider:
    return PROVIDERS.get(name or billing_settings().billing_provider) or PROVIDERS["stripe"]


__all__ = ["PROVIDERS", "CheckoutResult", "Invoice", "PaymentProvider", "WebhookError", "WebhookEvent",
           "get_provider"]
