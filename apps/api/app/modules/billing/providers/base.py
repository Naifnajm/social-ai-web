"""Payment provider interface. Stripe is implemented (``stripe.py``); Moyasar is a documented stub.

A provider turns "workspace X wants plan P billed every month/year" into a hosted payment page, lets the
customer manage their card, lists invoices, and reports changes through signed webhooks that end in
``service.apply_plan / mark_past_due / mark_paid``.
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.auth.models import User
from app.modules.workspaces.models import Workspace

from ..models import Subscription


@dataclass
class CheckoutResult:
    url: str | None = None   # hosted payment page to redirect the customer to
    updated: bool = False    # True when an existing subscription was changed in place (no redirect needed)


@dataclass
class Invoice:
    id: str
    number: str | None
    status: str              # draft | open | paid | void | uncollectible
    amount: float            # in major units (e.g. 49.00)
    currency: str
    created: datetime
    period_end: datetime | None = None
    hosted_url: str | None = None
    pdf_url: str | None = None


@dataclass
class WebhookEvent:
    id: str
    type: str
    data: dict


class WebhookError(Exception):
    """Bad signature or malformed payload (answered with HTTP 400)."""


class PaymentProvider:
    name = "base"

    def configured(self, db: Session) -> bool:
        raise NotImplementedError

    def checkout(self, db: Session, workspace: Workspace, sub: Subscription, plan_code: str, interval: str,
                 user: User, success_url: str, cancel_url: str) -> CheckoutResult:
        """Start (or change) a paid subscription."""
        raise NotImplementedError

    def portal(self, db: Session, workspace: Workspace, sub: Subscription, return_url: str) -> str:
        """URL of the self-service page (card, invoices, cancel)."""
        raise NotImplementedError

    def invoices(self, db: Session, workspace: Workspace, sub: Subscription) -> list[Invoice]:
        raise NotImplementedError

    def verify_webhook(self, body: bytes, headers: dict) -> WebhookEvent:
        """Check the signature and parse the event. Raise ``WebhookError`` when it is not authentic."""
        raise NotImplementedError

    def handle_event(self, db: Session, event: WebhookEvent) -> int | None:
        """Apply the event to the matching subscription; return the workspace id (or None if unrelated)."""
        raise NotImplementedError
