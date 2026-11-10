"""Incoming webhooks of the inbox: Meta (Messenger, Instagram DMs, Page comments, Instagram comments, WhatsApp
Cloud), Telegram (per-account secret URL + header) and Twilio WhatsApp (signed form posts).

Handlers are fast (the assistant answers afterwards in a background job), idempotent (messages are de-duplicated
by their network id) and never fail towards the platform once authenticated: processing errors are logged and a
200 is returned, otherwise the platform keeps retrying and may disable the webhook.
"""
import json
import logging
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.modules.social.models import SocialAccount

from . import service, sources, webhook_auth
from .bot_config import account_secrets, whatsapp_provider
from .config import inbox_settings
from .models import AccountInboxState, MetaApp

_logger = logging.getLogger(__name__)
router = APIRouter(tags=["inbox webhooks"], include_in_schema=False)

META_PATH = "/webhooks/meta"
TELEGRAM_PATH = "/webhooks/telegram/{account_id}/{secret}"
TWILIO_PATH = "/webhooks/twilio/{account_id}"
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def public_base() -> str:
    return settings.public_api_url.rstrip("/")


def meta_webhook_url() -> str:
    return public_base() + META_PATH


def telegram_webhook_url(account_id: int, secret: str) -> str:
    return public_base() + TELEGRAM_PATH.format(account_id=account_id, secret=secret)


def twilio_webhook_url(account_id: int) -> str:
    return public_base() + TWILIO_PATH.format(account_id=account_id)


async def raw_body(request: Request) -> bytes:
    return await request.body()


# ------------------------------------------------------------------ Meta
@router.get(META_PATH)
def meta_verify(request: Request, db: Session = Depends(get_db)):
    """Subscription check: echo hub.challenge when the verify token matches (platform or a workspace's app)."""
    params = request.query_params
    token = params.get("hub.verify_token") or ""
    ok = params.get("hub.mode") == "subscribe" and token and (
        webhook_auth.secret_ok(inbox_settings().meta_verify_token, token)
        or db.scalar(select(MetaApp.id).where(MetaApp.verify_token == token)) is not None)
    if ok:
        return PlainTextResponse(params.get("hub.challenge") or "")
    _logger.warning("inbox: Meta webhook verification refused (wrong verify token)")
    return PlainTextResponse("Forbidden", status_code=403)


def meta_allowed_workspaces(db: Session, payload: dict, body: bytes, signature: str) -> tuple[set[int] | None, bool]:
    """Which workspaces this signed request may reach: ``(None, True)`` = all (platform app), a set = the workspaces
    whose own app secret signed it. Second value: whether any secret could check the request at all."""
    platform_secret = inbox_settings().meta_app_secret
    if webhook_auth.meta_signature_ok(platform_secret, body, signature):
        return None, True
    workspaces = set()
    for entry in payload.get("entry") or []:
        workspaces |= {a.workspace_id for a in sources.meta_entry_workspaces(db, payload.get("object"), entry)}
    apps = db.scalars(select(MetaApp).where(MetaApp.workspace_id.in_(workspaces))).all() if workspaces else []
    checked = bool(platform_secret) or any(app.app_secret for app in apps)
    allowed = {app.workspace_id for app in apps if webhook_auth.meta_signature_ok(app.app_secret, body, signature)}
    return allowed, checked


@router.post(META_PATH)
def meta_event(request: Request, body: bytes = Depends(raw_body), db: Session = Depends(get_db)):
    signature = request.headers.get("X-Hub-Signature-256", "")
    try:
        payload = json.loads(body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return PlainTextResponse("Bad request", status_code=400)
    if not isinstance(payload, dict):
        return PlainTextResponse("Bad request", status_code=400)
    allowed, checked = meta_allowed_workspaces(db, payload, body, signature)
    if not checked:
        _logger.warning("inbox: Meta webhook received but no Meta app secret is configured")
        return PlainTextResponse("ok")
    if allowed is not None and not allowed:
        _logger.warning("inbox: Meta webhook with an invalid signature was ignored")
        return PlainTextResponse("Invalid signature", status_code=401)
    try:
        sources.meta_webhook(db, payload, allowed)
        db.commit()
        service.run_scheduled(db)
    except Exception:
        _logger.exception("inbox: Meta webhook processing failed")
    return PlainTextResponse("ok")


# ------------------------------------------------------------------ Telegram
@router.post(TELEGRAM_PATH)
def telegram_event(account_id: int, secret: str, request: Request, body: bytes = Depends(raw_body),
                   db: Session = Depends(get_db)):
    account = db.get(SocialAccount, account_id)
    state = db.scalar(select(AccountInboxState).where(AccountInboxState.account_id == account_id))
    expected = state.webhook_secret if state else None
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if (not account or account.platform != "telegram" or not webhook_auth.secret_ok(expected, secret)
            or not webhook_auth.secret_ok(expected, header)):
        _logger.warning("inbox: Telegram webhook refused for account %s", account_id)
        return PlainTextResponse("Forbidden", status_code=403)
    try:
        update = json.loads(body.decode() or "{}")
        if account.inbox_enabled and account.active and isinstance(update, dict):
            sources.telegram_webhook(db, account, update)
            db.commit()
            service.run_scheduled(db)
    except Exception:
        _logger.exception("inbox: Telegram webhook processing failed")
    return PlainTextResponse("ok")


# ------------------------------------------------------------------ Twilio (WhatsApp)
@router.post(TWILIO_PATH)
def twilio_event(account_id: int, request: Request, body: bytes = Depends(raw_body), db: Session = Depends(get_db)):
    account = db.get(SocialAccount, account_id)
    if not account or account.platform != "whatsapp" or whatsapp_provider(account) != "twilio":
        return PlainTextResponse("Not found", status_code=404)
    params = dict(parse_qsl(body.decode(errors="replace"), keep_blank_values=True))
    url = str(request.url)
    candidates = {twilio_webhook_url(account_id), url, url.replace("http://", "https://", 1)}
    signature = request.headers.get("X-Twilio-Signature", "")
    token = account_secrets(account).get("twilio_auth_token")
    if not webhook_auth.twilio_signature_ok(token, candidates, params, signature):
        _logger.warning("inbox: Twilio webhook with an invalid signature was ignored (account %s)", account_id)
        return PlainTextResponse("Invalid signature", status_code=403)
    try:
        if account.inbox_enabled and account.active:
            with db.begin_nested():
                sources.twilio_inbound(db, account, params)
            db.commit()
            service.run_scheduled(db)
    except Exception:
        _logger.exception("inbox: Twilio webhook processing failed")
    return Response(EMPTY_TWIML, media_type="text/xml")
