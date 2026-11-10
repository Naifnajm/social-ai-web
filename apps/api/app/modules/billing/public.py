"""Payment webhooks (mounted at the root, no session): ``POST /billing/webhooks/{stripe|moyasar}``.

Each event is verified (signature), recorded once in ``billing_events`` (provider + event id → idempotent:
Stripe retries and replays are ignored) and applied to the subscription.
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db

from .models import BillingEvent
from .providers import PROVIDERS, WebhookError
from .service import log_event

_logger = logging.getLogger(__name__)
router = APIRouter(tags=["billing webhooks"], include_in_schema=False)


@router.post("/billing/webhooks/{provider_name}")
async def webhook(provider_name: str, request: Request, db: Session = Depends(get_db)):
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        return JSONResponse({"detail": "unknown provider"}, status_code=404)
    body = await request.body()
    try:
        event = provider.verify_webhook(body, {k.lower(): v for k, v in request.headers.items()})
    except WebhookError as exc:
        _logger.warning("rejected %s webhook: %s", provider_name, exc)
        return JSONResponse({"detail": "invalid signature"}, status_code=400)
    if not event.id:
        return JSONResponse({"detail": "missing event id"}, status_code=400)
    return await run_in_threadpool(_process, db, provider, event)


def _process(db: Session, provider, event) -> dict:
    if db.scalar(select(BillingEvent.id).where(BillingEvent.provider == provider.name,
                                               BillingEvent.event_id == event.id)):
        return {"received": True, "duplicate": True}
    workspace_id = provider.handle_event(db, event)
    log_event(db, provider.name, event.id, event.type, workspace_id, summary=event.type,
              payload={"object": event.data.get("object"), "id": event.data.get("id"),
                       "status": event.data.get("status")})
    return {"received": True}
