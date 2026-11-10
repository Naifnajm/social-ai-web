"""Stripe through its REST API (form-encoded) and ``app.core.http.call`` — no SDK needed.

Flow:
1. ``checkout`` creates the Stripe customer once, then a Checkout Session (mode=subscription) carrying the
   workspace id in ``client_reference_id`` + metadata. A workspace that already pays is moved to the new price
   in place (``POST /v1/subscriptions/{id}`` with prorations) — no second subscription.
2. Stripe calls ``/billing/webhooks/stripe``; the ``Stripe-Signature`` header is verified (HMAC-SHA256 of
   ``"{t}.{body}"`` with the endpoint secret, 5-minute tolerance) and each event id is processed once.
3. Events → state: ``checkout.session.completed`` links the customer/subscription; ``customer.subscription.*``
   sets plan/status/period end; ``invoice.payment_failed`` → past_due (grace period starts);
   ``invoice.paid`` → active again; ``customer.subscription.deleted`` → canceled.

Configure the webhook endpoint in Stripe with these events: checkout.session.completed,
customer.subscription.created, customer.subscription.updated, customer.subscription.deleted,
invoice.paid, invoice.payment_failed.
"""
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.http import call
from app.core.i18n import _
from app.modules.auth.models import User
from app.modules.workspaces.models import Workspace

from .. import platform, service
from ..config import billing_settings
from ..models import Subscription
from ..plans import PAID_PLANS
from .base import CheckoutResult, Invoice, PaymentProvider, WebhookError, WebhookEvent

STATUS_MAP = {
    "trialing": "active",  # a Stripe-side trial is already a paid plan for us
    "active": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "canceled": "canceled",
    "incomplete_expired": "canceled",
    "paused": "past_due",
}


def _ts(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc) if value else None
    except (TypeError, ValueError):
        return None


def price_table(db: Session) -> dict[str, str]:
    """``{"pro_month": "price_..."}`` from the platform settings, falling back to the environment."""
    settings = billing_settings()
    table = {f"{plan}_{interval}": settings.stripe_price(plan, interval)
             for plan in PAID_PLANS for interval in ("month", "year")}
    overrides = platform.get_setting(db, "billing.stripe_prices") or {}
    if isinstance(overrides, dict):
        table.update({k: v for k, v in overrides.items() if k in table and v})
    return table


def plan_for_price(db: Session, price_id: str | None) -> tuple[str | None, str | None]:
    for key, value in price_table(db).items():
        if value and value == price_id:
            plan, _sep, interval = key.rpartition("_")
            return plan, interval
    return None, None


class StripeProvider(PaymentProvider):
    name = "stripe"

    # ---------------------------------------------------------------- HTTP
    def _request(self, method: str, path: str, *, data: dict | None = None, params: dict | None = None,
                 workspace_id: int | None = None, operation: str = ""):
        key = billing_settings().stripe_secret_key
        if not key:
            raise AppError(_("Online payments are not configured yet. Please contact support."),
                           code="billing_not_configured")
        return call(method, f"{billing_settings().stripe_api_base.rstrip('/')}{path}", service="billing",
                    operation=operation or f"Stripe {method} {path}", workspace_id=workspace_id,
                    headers={"Authorization": f"Bearer {key}", "Stripe-Version": "2024-06-20"},
                    data=data, params=params, timeout=30)

    def configured(self, db: Session) -> bool:
        return bool(billing_settings().stripe_secret_key)

    def _customer(self, db: Session, workspace: Workspace, sub: Subscription, user: User) -> str:
        if sub.provider_customer_id and sub.provider in ("stripe", "none", "manual"):
            return sub.provider_customer_id
        customer = self._request("POST", "/v1/customers", workspace_id=workspace.id, operation="Create customer",
                                 data={"name": workspace.name, "email": user.email,
                                       "metadata[workspace_id]": str(workspace.id),
                                       "preferred_locales[0]": workspace.locale or "ar"})
        sub.provider_customer_id = customer["id"]
        sub.provider = "stripe"
        db.flush()
        return customer["id"]

    # ---------------------------------------------------------------- checkout / portal / invoices
    def checkout(self, db, workspace, sub, plan_code, interval, user, success_url, cancel_url) -> CheckoutResult:
        price = price_table(db).get(f"{plan_code}_{interval}")
        if not price:
            raise AppError(_("This plan cannot be bought online yet. Please contact support."),
                           code="billing_not_configured")
        customer = self._customer(db, workspace, sub, user)
        if sub.provider == "stripe" and sub.provider_subscription_id and sub.status in ("active", "past_due"):
            return self._change_price(db, workspace, sub, plan_code, interval, price)
        session = self._request("POST", "/v1/checkout/sessions", workspace_id=workspace.id,
                                operation="Create checkout session", data={
                                    "mode": "subscription",
                                    "customer": customer,
                                    "client_reference_id": str(workspace.id),
                                    "line_items[0][price]": price,
                                    "line_items[0][quantity]": "1",
                                    "success_url": success_url,
                                    "cancel_url": cancel_url,
                                    "allow_promotion_codes": "true",
                                    "billing_address_collection": "auto",
                                    "tax_id_collection[enabled]": "true",
                                    "customer_update[name]": "auto",
                                    "customer_update[address]": "auto",
                                    "locale": "ar" if (workspace.locale or "ar") == "ar" else "auto",
                                    "metadata[workspace_id]": str(workspace.id),
                                    "metadata[plan_code]": plan_code,
                                    "metadata[interval]": interval,
                                    "subscription_data[metadata][workspace_id]": str(workspace.id),
                                    "subscription_data[metadata][plan_code]": plan_code,
                                    "subscription_data[metadata][interval]": interval,
                                })
        return CheckoutResult(url=session.get("url"))

    def _change_price(self, db, workspace, sub, plan_code, interval, price) -> CheckoutResult:
        current = self._request("GET", f"/v1/subscriptions/{sub.provider_subscription_id}",
                                workspace_id=workspace.id, operation="Read subscription")
        items = (current.get("items") or {}).get("data") or []
        if not items:
            raise AppError(_("The current subscription could not be read. Please try again."), code="billing_error")
        updated = self._request("POST", f"/v1/subscriptions/{sub.provider_subscription_id}",
                                workspace_id=workspace.id, operation="Change plan", data={
                                    "items[0][id]": items[0]["id"],
                                    "items[0][price]": price,
                                    "proration_behavior": "create_prorations",
                                    "cancel_at_period_end": "false",
                                    "metadata[plan_code]": plan_code,
                                    "metadata[interval]": interval,
                                    "metadata[workspace_id]": str(workspace.id),
                                })
        self._apply_subscription(db, sub, updated)
        return CheckoutResult(updated=True)

    def portal(self, db, workspace, sub, return_url) -> str:
        if not sub.provider_customer_id or sub.provider != "stripe":
            raise AppError(_("There is no payment method on file yet. Choose a plan first."), code="no_customer")
        session = self._request("POST", "/v1/billing_portal/sessions", workspace_id=workspace.id,
                                operation="Create portal session",
                                data={"customer": sub.provider_customer_id, "return_url": return_url})
        return session["url"]

    def invoices(self, db, workspace, sub) -> list[Invoice]:
        if not sub.provider_customer_id or sub.provider != "stripe" or not self.configured(db):
            return []
        data = self._request("GET", "/v1/invoices", workspace_id=workspace.id, operation="List invoices",
                             params={"customer": sub.provider_customer_id, "limit": 24})
        out = []
        for item in data.get("data") or []:
            if item.get("status") == "draft":
                continue
            amount = item.get("amount_paid") if item.get("status") == "paid" else item.get("amount_due")
            out.append(Invoice(
                id=item["id"], number=item.get("number"), status=item.get("status") or "open",
                amount=round((amount or 0) / 100, 2), currency=(item.get("currency") or "usd").upper(),
                created=_ts(item.get("created")) or service.utcnow(), period_end=_ts(item.get("period_end")),
                hosted_url=item.get("hosted_invoice_url"), pdf_url=item.get("invoice_pdf"),
            ))
        return out

    # ---------------------------------------------------------------- webhooks
    def verify_webhook(self, body: bytes, headers: dict) -> WebhookEvent:
        secret = billing_settings().stripe_webhook_secret
        if not secret:
            raise WebhookError("webhook secret not configured")
        header = headers.get("stripe-signature") or ""
        parts: dict[str, list[str]] = {}
        for item in header.split(","):
            key, _sep, value = item.strip().partition("=")
            parts.setdefault(key, []).append(value)
        try:
            timestamp = int((parts.get("t") or [""])[0])
        except ValueError:
            raise WebhookError("missing timestamp") from None
        if abs(time.time() - timestamp) > billing_settings().stripe_webhook_tolerance:
            raise WebhookError("timestamp outside the tolerance zone")
        expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", [])):
            raise WebhookError("bad signature")
        try:
            payload = json.loads(body)
        except ValueError:
            raise WebhookError("invalid JSON") from None
        if not isinstance(payload, dict) or "id" not in payload or "type" not in payload:
            raise WebhookError("not an event")
        return WebhookEvent(id=payload["id"], type=payload["type"], data=(payload.get("data") or {}).get("object") or {})

    def _find(self, db: Session, *, workspace_id=None, subscription_id=None, customer_id=None) -> Subscription | None:
        if subscription_id:
            sub = db.scalar(select(Subscription).where(Subscription.provider_subscription_id == subscription_id))
            if sub:
                return sub
        if workspace_id and str(workspace_id).isdigit() and db.get(Workspace, int(workspace_id)):
            workspace = db.get(Workspace, int(workspace_id))
            sub = service.ensure_subscription(db, workspace)
            # never let a customer id of another workspace hijack this one
            if not customer_id or not sub.provider_customer_id or sub.provider_customer_id == customer_id:
                return sub
        if customer_id:
            return db.scalar(select(Subscription).where(Subscription.provider_customer_id == customer_id))
        return None

    def _apply_subscription(self, db: Session, sub: Subscription, obj: dict) -> None:
        items = (obj.get("items") or {}).get("data") or []
        item = items[0] if items else {}
        price = item.get("price") or {}
        plan_code, interval = plan_for_price(db, price.get("id"))
        metadata = obj.get("metadata") or {}
        plan_code = plan_code or metadata.get("plan_code") or sub.plan_code
        interval = interval or (price.get("recurring") or {}).get("interval") or metadata.get("interval")
        status = STATUS_MAP.get(obj.get("status") or "")
        if status is None:  # incomplete: the first payment is not done yet — keep the current state
            return
        sub.provider = "stripe"
        sub.provider_subscription_id = obj.get("id") or sub.provider_subscription_id
        sub.provider_customer_id = obj.get("customer") or sub.provider_customer_id
        sub.provider_price_id = price.get("id") or sub.provider_price_id
        sub.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
        period_end = _ts(obj.get("current_period_end") or item.get("current_period_end"))
        service.apply_plan(db, sub, plan_code, status=status, interval=interval, period_end=period_end)
        if status == "past_due" and not sub.past_due_since:
            sub.past_due_since = service.utcnow()

    def handle_event(self, db: Session, event: WebhookEvent) -> int | None:
        obj = event.data
        metadata = obj.get("metadata") or {}
        if event.type == "checkout.session.completed":
            if obj.get("mode") != "subscription":
                return None
            sub = self._find(db, workspace_id=metadata.get("workspace_id") or obj.get("client_reference_id"),
                             customer_id=obj.get("customer"))
            if sub is None:
                return None
            sub.provider = "stripe"
            sub.provider_customer_id = obj.get("customer") or sub.provider_customer_id
            sub.provider_subscription_id = obj.get("subscription") or sub.provider_subscription_id
            if obj.get("payment_status") in ("paid", "no_payment_required"):
                service.apply_plan(db, sub, metadata.get("plan_code") or sub.plan_code, status="active",
                                   interval=metadata.get("interval"))
            return sub.workspace_id

        if event.type.startswith("customer.subscription."):
            sub = self._find(db, subscription_id=obj.get("id"), workspace_id=metadata.get("workspace_id"),
                             customer_id=obj.get("customer"))
            if sub is None:
                return None
            if sub.provider_subscription_id and obj.get("id") != sub.provider_subscription_id:
                # an older subscription of the same customer: only a new live one may replace the current
                if event.type == "customer.subscription.deleted" or STATUS_MAP.get(obj.get("status")) != "active":
                    return sub.workspace_id
            if event.type == "customer.subscription.deleted":
                sub.cancel_at_period_end = False
                service.apply_plan(db, sub, sub.plan_code, status="canceled",
                                   period_end=_ts(obj.get("ended_at")) or service.utcnow())
            else:
                self._apply_subscription(db, sub, obj)
            return sub.workspace_id

        if event.type in ("invoice.payment_failed", "invoice.paid", "invoice.payment_succeeded"):
            subscription_id = obj.get("subscription") or (
                ((obj.get("parent") or {}).get("subscription_details") or {}).get("subscription"))
            sub = self._find(db, subscription_id=subscription_id, customer_id=obj.get("customer"),
                             workspace_id=((obj.get("subscription_details") or {}).get("metadata") or {}).get("workspace_id"))
            if sub is None or (subscription_id and sub.provider_subscription_id
                               and subscription_id != sub.provider_subscription_id):
                return sub.workspace_id if sub else None
            if event.type == "invoice.payment_failed":
                service.mark_past_due(db, sub)
            else:
                service.mark_paid(db, sub)
                lines = ((obj.get("lines") or {}).get("data") or [])
                period_end = _ts(((lines[0] if lines else {}).get("period") or {}).get("end"))
                if period_end:
                    sub.current_period_end = period_end
            return sub.workspace_id
        return None
