"""Moyasar (Saudi gateway: mada, Apple Pay, STC Pay, cards) — DOCUMENTED STUB, not active yet.

How to finish it (no native subscriptions at Moyasar, so the platform runs the recurring charge):

1. ``checkout``: return the URL of a small hosted page of ours that embeds Moyasar's payment form
   (publishable key ``SAI_MOYASAR_PUBLISHABLE_KEY``) with ``save_card: true`` and
   ``metadata[workspace_id|plan_code|interval]``; amount in halalas (SAR × 100) from ``Plan.price_*_sar``.
2. The form's ``callback_url`` (and the webhook ``payment_paid``) gives a payment with ``source.token``:
   store the token in ``Subscription.provider_customer_id`` (it is a card token, not a secret key), set
   ``provider="moyasar"``, ``apply_plan(..., status="active", period_end=now + 1 month/year)``.
3. A ``@periodic(seconds=3600)`` task charges due subscriptions:
   ``POST https://api.moyasar.com/v1/payments`` (basic auth with ``SAI_MOYASAR_SECRET_KEY``) with
   ``source[type]=token&source[token]=...`` — success → extend ``current_period_end``; failure →
   ``service.mark_past_due`` (the grace period and read-only mode work exactly like Stripe).
4. Webhooks (``/billing/webhooks/moyasar``): Moyasar sends JSON with a ``secret_token`` field equal to the
   secret configured in the dashboard (``SAI_MOYASAR_WEBHOOK_SECRET``) — compare with ``hmac.compare_digest``;
   events ``payment_paid`` / ``payment_failed`` / ``payment_refunded``.
5. ``invoices``: ``GET /v1/payments?metadata[workspace_id]=...``; ``portal``: our own page to replace the card
   (a new tokenisation) and cancel (``cancel_at_period_end``).
Register it by adding ``"moyasar": MoyasarProvider()`` in ``providers/__init__.py`` (already listed) and set
``SAI_BILLING_PROVIDER=moyasar``.
"""
import hmac
import json

from app.core.errors import AppError
from app.core.i18n import _

from ..config import billing_settings
from .base import PaymentProvider, WebhookError, WebhookEvent


class MoyasarProvider(PaymentProvider):
    name = "moyasar"

    def configured(self, db) -> bool:
        return False  # until steps 1–3 above are implemented

    def _unavailable(self):
        raise AppError(_("This payment method is not available yet. Please contact support."),
                       code="billing_not_configured")

    def checkout(self, *args, **kwargs):
        self._unavailable()

    def portal(self, *args, **kwargs):
        self._unavailable()

    def invoices(self, db, workspace, sub):
        return []

    def verify_webhook(self, body: bytes, headers: dict) -> WebhookEvent:
        secret = billing_settings().moyasar_webhook_secret
        try:
            payload = json.loads(body)
        except ValueError:
            raise WebhookError("invalid JSON") from None
        if not secret or not hmac.compare_digest(str(payload.get("secret_token") or ""), secret):
            raise WebhookError("bad secret token")
        return WebhookEvent(id=str(payload.get("id") or ""), type=str(payload.get("type") or ""),
                            data=payload.get("data") or {})

    def handle_event(self, db, event: WebhookEvent):
        return None  # see step 4
