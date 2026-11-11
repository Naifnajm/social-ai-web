"""Where inbox messages come from: Meta / Telegram / WhatsApp / Twilio webhooks and the polling fallback.

Multi-tenant routing: webhooks name the network account (page id, IG user id, phone_number_id). The same
account may be connected in several workspaces: each event is delivered to every matching account (each in its
own workspace), never across workspaces. Every function returns the number of new messages.
"""
import importlib
import logging
import mimetypes
import secrets as pysecrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.http import ApiError
from app.core.storage import save_media
from app.modules.social.models import PostTarget, SocialAccount

from . import service
from .bot_config import whatsapp_provider
from .config import inbox_settings
from .messaging import get_messenger
from .models import INBOX_PLATFORMS, AccountInboxState, Conversation, MetaApp
from .text import digits, parse_dt, utcnow

_logger = logging.getLogger(__name__)

MAX_ATTACHMENTS = 4
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
POLL_POST_DAYS = 14


# ------------------------------------------------------------------ helpers
def inbox_accounts(db: Session, platform: str, external_id, *, provider: str | None = None) -> list[SocialAccount]:
    """Every inbox-enabled account (any workspace) with this network id."""
    if not external_id:
        return []
    accounts = db.scalars(select(SocialAccount).where(
        SocialAccount.platform == platform, SocialAccount.external_id == str(external_id),
        SocialAccount.inbox_enabled.is_(True), SocialAccount.active.is_(True)).order_by(SocialAccount.id)).all()
    if provider:
        accounts = [a for a in accounts if whatsapp_provider(a) == provider]
    return list(accounts)


def account_state(db: Session, account: SocialAccount) -> AccountInboxState:
    state = db.scalar(select(AccountInboxState).where(AccountInboxState.account_id == account.id))
    if state is None:
        state = AccountInboxState(workspace_id=account.workspace_id, account_id=account.id,
                                  webhook_secret=pysecrets.token_urlsafe(24))
        db.add(state)
        db.flush()
    elif not state.webhook_secret:
        state.webhook_secret = pysecrets.token_urlsafe(24)
    return state


def store_attachment(db: Session, account: SocialAccount, content: bytes, mimetype: str | None,
                     name: str) -> int | None:
    if not content or len(content) > MAX_ATTACHMENT_BYTES:
        return None
    mimetype = mimetype or mimetypes.guess_type(name or "")[0] or "application/octet-stream"
    if "." not in (name or ""):
        name = "%s%s" % (name or "file", mimetypes.guess_extension(mimetype) or "")
    return save_media(db, account.workspace_id, content, name, mimetype, source="inbox").id


def download(db: Session, account: SocialAccount, messenger, url: str, name: str) -> int | None:
    try:
        content, mimetype = messenger.download(url)
    except ApiError as exc:
        _logger.info("inbox: could not download %s: %s", name, exc.message)
        return None
    return store_attachment(db, account, content, mimetype, name)


def our_meta_app_ids(db: Session, workspace_id: int) -> set[str]:
    ids = {inbox_settings().meta_app_id} if inbox_settings().meta_app_id else set()
    app = db.scalar(select(MetaApp).where(MetaApp.workspace_id == workspace_id))
    if app and app.app_id:
        ids.add(app.app_id)
    return ids


# ------------------------------------------------------------------ Meta webhook
def meta_entry_workspaces(db: Session, kind: str | None, entry: dict) -> list[SocialAccount]:
    """Accounts an entry would be delivered to (used to pick the app secrets that may sign it)."""
    if kind == "whatsapp_business_account":
        accounts = []
        for change in entry.get("changes") or []:
            phone_id = ((change.get("value") or {}).get("metadata") or {}).get("phone_number_id")
            accounts += inbox_accounts(db, "whatsapp", phone_id, provider="cloud")
        return accounts
    platform = {"page": "facebook", "instagram": "instagram"}.get(kind or "")
    return inbox_accounts(db, platform, entry.get("id")) if platform else []


def meta_webhook(db: Session, payload: dict, allowed_workspaces: set[int] | None = None) -> int:
    """Facebook Page, Instagram and WhatsApp Cloud events. ``allowed_workspaces`` (None = all) restricts delivery
    to the workspaces whose app secret signed the request."""
    new = 0
    kind = payload.get("object")
    for entry in payload.get("entry") or []:
        try:
            with db.begin_nested():
                new += meta_entry(db, kind, entry, allowed_workspaces)
        except Exception:
            _logger.exception("inbox: could not process a Meta webhook entry")
    return new


def _allowed(account: SocialAccount, allowed_workspaces: set[int] | None) -> bool:
    return allowed_workspaces is None or account.workspace_id in allowed_workspaces


def meta_entry(db: Session, kind: str | None, entry: dict, allowed_workspaces: set[int] | None = None) -> int:
    new = 0
    if kind == "whatsapp_business_account":
        for change in entry.get("changes") or []:
            if change.get("field") == "messages":
                new += whatsapp_cloud_value(db, change.get("value") or {}, allowed_workspaces)
        return new
    platform = {"page": "facebook", "instagram": "instagram"}.get(kind or "")
    if not platform:
        return 0
    accounts = [a for a in inbox_accounts(db, platform, entry.get("id")) if _allowed(a, allowed_workspaces)]
    if not accounts:
        _logger.info("inbox: webhook for unknown %s account %s", platform, entry.get("id"))
    for account in accounts:
        with db.begin_nested():
            for event in entry.get("messaging") or []:
                new += meta_messaging(db, account, event)
            for change in entry.get("changes") or []:
                field, value = change.get("field"), change.get("value") or {}
                if platform == "facebook" and field == "feed" and value.get("item") == "comment":
                    new += facebook_comment(db, account, value)
                elif platform == "instagram" and field == "comments":
                    new += instagram_comment(db, account, value)
    return new


def meta_messaging(db: Session, account: SocialAccount, event: dict, from_poll: bool = False) -> int:
    message = event.get("message")
    if not isinstance(message, dict) or message.get("is_deleted"):
        return 0
    sender = str((event.get("sender") or {}).get("id") or "")
    recipient = str((event.get("recipient") or {}).get("id") or "")
    echo = bool(message.get("is_echo")) or sender == account.external_id
    if echo:
        app_id = str(message.get("app_id") or "")
        if app_id and app_id in our_meta_app_ids(db, account.workspace_id):
            return 0  # our own Send API call coming back
        customer_id = recipient
    else:
        customer_id = sender
    if not customer_id:
        return 0
    messenger = get_messenger(account)
    customer = {"user_id": customer_id, "name": event.get("customer_name"), "handle": event.get("customer_handle")}
    known = db.scalar(select(Conversation.id).where(
        Conversation.account_id == account.id, Conversation.kind == "dm",
        Conversation.external_thread_id == customer_id, Conversation.customer_name.is_not(None)))
    if not echo and not known and not from_poll:
        profile = messenger.user_profile(customer_id)  # name and picture (needs pages_messaging)
        customer.update(name=profile.get("name"), handle=profile.get("username"), avatar_url=profile.get("avatar_url"))
    if service.find_message(db, account.id, message.get("mid")):
        return 0
    conv = service.find_or_create(db, account, "dm", customer_id, customer=customer)
    media_ids = []
    for index, item in enumerate((message.get("attachments") or [])[:MAX_ATTACHMENTS]):
        url = (item.get("payload") or {}).get("url")
        if url and item.get("type") in ("image", "video", "audio", "file"):
            media_id = download(db, account, messenger, url, "%s-%s" % (item.get("type"), index + 1))
            if media_id:
                media_ids.append(media_id)
    date = parse_dt(event.get("timestamp"))
    direction = "out" if echo else "in"
    _msg, created = service.ingest(db, conv, {
        "direction": direction, "body": message.get("text") or "", "external_id": message.get("mid"),
        "sent_at": date, "author_name": account.name if echo else conv.customer_name,
        "author_external_id": sender, "media_ids": media_ids or None,
        "reply_to": (message.get("reply_to") or {}).get("mid"),
    }, bot=service.bot_wanted(direction, date))
    if created and echo and not from_poll:
        conv.bot_paused = True  # someone answered from Meta Business Suite
    return int(created)


def _parent_conversation(db: Session, account: SocialAccount, parent_id) -> Conversation | None:
    parent = service.find_message(db, account.id, parent_id) if parent_id else None
    return db.get(Conversation, parent.conversation_id) if parent else None


def comment(db: Session, account: SocialAccount, *, comment_id, root_id, post, author_id, author_name, handle,
            text, date, bot=True) -> int:
    if not comment_id:
        return 0
    own = bool(author_id) and str(author_id) == account.external_id
    conv = _parent_conversation(db, account, root_id if root_id != comment_id else None)
    if not conv:
        customer = {} if own else {"name": author_name, "handle": handle, "user_id": author_id}
        conv = service.find_or_create(db, account, "comment", root_id, customer=customer, post=post)
    direction = "out" if own else "in"
    _msg, created = service.ingest(db, conv, {
        "direction": direction, "channel": "public" if own else "dm", "body": text or "",
        "external_id": comment_id, "sent_at": date,
        "author_name": account.name if own else (author_name or handle),
        "author_external_id": str(author_id) if author_id else None,
        "reply_to": root_id if root_id != comment_id else None,
    }, bot=bot and service.bot_wanted(direction, date))
    return int(created)


def facebook_comment(db: Session, account: SocialAccount, value: dict) -> int:
    verb = value.get("verb")
    comment_id = value.get("comment_id")
    if not comment_id:
        return 0
    if verb == "edited":
        message = service.find_message(db, account.id, comment_id)
        if message:
            message.body = value.get("message") or message.body
        return 0
    if verb != "add":
        return 0
    post_id = value.get("post_id")
    parent_id = value.get("parent_id")
    root = parent_id if parent_id and parent_id != post_id else comment_id
    author = value.get("from") or {}
    return comment(db, account, comment_id=comment_id, root_id=root, post=service.post_info(db, account, post_id),
                   author_id=author.get("id"), author_name=author.get("name"), handle=None,
                   text=value.get("message"), date=parse_dt(value.get("created_time")))


def instagram_comment(db: Session, account: SocialAccount, value: dict) -> int:
    comment_id = value.get("id")
    if not comment_id:
        return 0
    author = value.get("from") or {}
    media = value.get("media") or {}
    root = value.get("parent_id") or comment_id
    return comment(db, account, comment_id=comment_id, root_id=root,
                   post=service.post_info(db, account, media.get("id")),
                   author_id=author.get("id"), author_name=author.get("username"), handle=author.get("username"),
                   text=value.get("text"), date=parse_dt(value.get("timestamp")))


# ------------------------------------------------------------------ WhatsApp Cloud
def whatsapp_cloud_value(db: Session, value: dict, allowed_workspaces: set[int] | None = None) -> int:
    phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
    accounts = [a for a in inbox_accounts(db, "whatsapp", phone_number_id, provider="cloud")
                if _allowed(a, allowed_workspaces)]
    if not accounts:
        _logger.info("inbox: WhatsApp webhook for unknown phone number id %s", phone_number_id)
    new = 0
    for account in accounts:
        with db.begin_nested():
            new += _whatsapp_cloud_account(db, account, value)
    return new


def _whatsapp_cloud_account(db: Session, account: SocialAccount, value: dict) -> int:
    for status in value.get("statuses") or []:
        if status.get("status") == "failed":
            message = service.find_message(db, account.id, status.get("id"))
            if message:
                error = "; ".join(e.get("title") or e.get("message") or "" for e in status.get("errors") or [])
                message.state, message.error = "failed", error or "WhatsApp could not deliver the message."
    names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
    messenger = get_messenger(account)
    new = 0
    for item in value.get("messages") or []:
        wa_id = item.get("from")
        if not wa_id or service.find_message(db, account.id, item.get("id")):
            continue
        kind = item.get("type")
        body, media_ids = "", []
        if kind == "text":
            body = (item.get("text") or {}).get("body") or ""
        elif kind in ("image", "document", "audio", "video", "sticker"):
            media = item.get(kind) or {}
            body = media.get("caption") or ""
            if media.get("id"):
                try:
                    content, mimetype = messenger.media_content(media["id"])
                    media_id = store_attachment(db, account, content, mimetype or media.get("mime_type"),
                                                media.get("filename") or kind)
                    if media_id:
                        media_ids.append(media_id)
                except ApiError as exc:
                    body = body or "[%s: %s]" % (kind, exc.message)
        elif kind == "interactive":
            reply = item.get("interactive") or {}
            body = (reply.get("button_reply") or reply.get("list_reply") or {}).get("title") or ""
        elif kind == "button":
            body = (item.get("button") or {}).get("text") or ""
        elif kind == "location":
            loc = item.get("location") or {}
            body = "📍 %s %s,%s" % (loc.get("name") or "", loc.get("latitude"), loc.get("longitude"))
        elif kind == "reaction":
            continue
        else:
            body = "[%s]" % kind
        conv = service.find_or_create(db, account, "dm", wa_id, customer={
            "name": names.get(wa_id), "user_id": wa_id, "handle": "+" + digits(wa_id), "phone": wa_id})
        date = parse_dt(item.get("timestamp"))
        _msg, created = service.ingest(db, conv, {
            "direction": "in", "body": body, "external_id": item.get("id"), "sent_at": date,
            "author_name": names.get(wa_id) or "+" + wa_id, "author_external_id": wa_id,
            "media_ids": media_ids or None, "reply_to": (item.get("context") or {}).get("id"),
        }, bot=service.bot_wanted("in", date))
        new += int(created)
    return new


# ------------------------------------------------------------------ Twilio WhatsApp
def twilio_inbound(db: Session, account: SocialAccount, params: dict) -> int:
    status = params.get("MessageStatus") or params.get("SmsStatus")
    sid = params.get("MessageSid") or params.get("SmsSid")
    if status in ("failed", "undelivered") and sid:
        message = service.find_message(db, account.id, sid)
        if message:
            message.state = "failed"
            message.error = params.get("ErrorMessage") or (
                "Twilio could not deliver the message (%s)." % (params.get("ErrorCode") or status))
        return 0
    if "Body" not in params and not int(params.get("NumMedia") or 0):
        return 0  # delivery receipt
    wa_id = digits(params.get("WaId") or params.get("From"))
    if not wa_id:
        return 0
    own_number = digits((account.extra or {}).get("whatsapp_number"))
    if own_number and wa_id == own_number:
        return 0
    if sid and service.find_message(db, account.id, sid):
        return 0
    messenger = get_messenger(account)
    media_ids = []
    for index in range(min(int(params.get("NumMedia") or 0), MAX_ATTACHMENTS)):
        url = params.get("MediaUrl%d" % index)
        if url:
            media_id = download(db, account, messenger, url, "media-%s" % (index + 1))
            if media_id:
                media_ids.append(media_id)
    name = params.get("ProfileName")
    conv = service.find_or_create(db, account, "dm", wa_id, customer={
        "name": name, "user_id": wa_id, "handle": "+" + wa_id, "phone": wa_id})
    _msg, created = service.ingest(db, conv, {
        "direction": "in", "body": params.get("Body") or "", "external_id": sid,
        "author_name": name or "+" + wa_id, "author_external_id": wa_id, "media_ids": media_ids or None,
    })
    return int(created)


# ------------------------------------------------------------------ Telegram
def _telegram_command_hook():
    """``app.modules.templates.telegram.handle_command`` when the templates feature provides it."""
    try:
        module = importlib.import_module("app.modules.templates.telegram")
    except ImportError:
        return None
    return getattr(module, "handle_command", None)


def telegram_update(db: Session, account: SocialAccount, update: dict) -> int:
    """One Bot API update (webhook or getUpdates). Private chats only."""
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    if chat.get("type") != "private" or sender.get("is_bot") or not chat.get("id"):
        return 0
    chat_id = str(chat["id"])
    external_id = "%s:%s" % (chat_id, message.get("message_id"))
    if service.find_message(db, account.id, external_id):
        return 0
    messenger = get_messenger(account)
    files = []
    if message.get("photo"):
        best = max(message["photo"], key=lambda p: p.get("file_size") or p.get("width", 0))
        files.append((best.get("file_id"), "photo.jpg"))
    for key in ("document", "video", "voice", "audio"):
        item = message.get(key)
        if item and item.get("file_id") and (item.get("file_size") or 0) <= MAX_ATTACHMENT_BYTES:
            files.append((item["file_id"], item.get("file_name") or key))
    media_ids = []
    for file_id, name in files[:MAX_ATTACHMENTS]:
        try:
            content, mimetype = messenger.file_content(file_id)
        except ApiError as exc:
            _logger.info("inbox: Telegram file not downloaded: %s", exc.message)
            continue
        if name == "photo.jpg" and not (mimetype or "").startswith("image/"):
            mimetype = "image/jpeg"
        media_id = store_attachment(db, account, content, mimetype, name)
        if media_id:
            media_ids.append(media_id)

    # Hook for the templates feature: a bot command answered directly (no inbox conversation).
    handler = _telegram_command_hook()
    if handler:
        try:
            with db.begin_nested():
                reply = handler(db, account, message, media_ids)
        except Exception:
            _logger.exception("inbox: Telegram command hook failed")
            reply = None
        if reply:
            try:
                messenger.send_dm(chat_id, str(reply), reply_to=message.get("message_id"))
            except ApiError as exc:
                _logger.info("inbox: Telegram command reply failed: %s", exc.message)
            return 0

    name = " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")])) or sender.get("username")
    conv = service.find_or_create(db, account, "dm", chat_id, customer={
        "name": name, "handle": ("@" + sender["username"]) if sender.get("username") else None,
        "user_id": str(sender.get("id") or chat_id)})
    date = parse_dt(message.get("date"))
    reply_to = (message.get("reply_to_message") or {}).get("message_id")
    _msg, created = service.ingest(db, conv, {
        "direction": "in", "body": message.get("text") or message.get("caption") or "",
        "external_id": external_id, "sent_at": date, "author_name": name,
        "author_external_id": str(sender.get("id") or ""), "media_ids": media_ids or None,
        "reply_to": "%s:%s" % (chat_id, reply_to) if reply_to else None,
    }, bot=service.bot_wanted("in", date))
    return int(created)


def telegram_webhook(db: Session, account: SocialAccount, update: dict) -> int:
    try:
        with db.begin_nested():
            return telegram_update(db, account, update)
    except Exception:
        _logger.exception("inbox: could not process a Telegram update")
        return 0


# ------------------------------------------------------------------ polling fallback
def poll_accounts(db: Session, accounts: list[SocialAccount] | None = None) -> dict:
    """Read new messages and comments (works without public webhooks). Returns {"new", "errors"}."""
    if accounts is None:
        accounts = db.scalars(select(SocialAccount).where(
            SocialAccount.inbox_enabled.is_(True), SocialAccount.active.is_(True),
            SocialAccount.platform.in_(INBOX_PLATFORMS),
            SocialAccount.state.in_(("connected", "draft"))).order_by(SocialAccount.id)).all()
    result = {"new": 0, "errors": []}
    for account in accounts:
        state = account_state(db, account)
        try:
            with db.begin_nested():
                state.sync_error = None
                result["new"] += poll_account(db, account, state)
            state.last_sync_at = utcnow()
            if state.sync_error:
                result["errors"].append("%s: %s" % (account.name, state.sync_error))
        except ApiError as exc:
            state.last_sync_at, state.sync_error = utcnow(), exc.message[:300]
            result["errors"].append("%s: %s" % (account.name, exc.message))
        except Exception as exc:
            _logger.exception("inbox: sync failed for account %s", account.id)
            result["errors"].append("%s: %s" % (account.name, exc))
    return result


def _meta_poll_error(account: SocialAccount, label: str, exc: ApiError) -> str:
    if label == "messages" and account.platform == "facebook" and "pages_messaging" in exc.message:
        return "Messenger messages need the Messenger permission (pages_messaging); comments still sync."
    return exc.message


def poll_account(db: Session, account: SocialAccount, state: AccountInboxState) -> int:
    if not account.inbox_enabled or account.platform not in INBOX_PLATFORMS:
        return 0
    if account.platform in ("facebook", "instagram"):
        # Messages and comments are independent: one failing (for example Messenger without its permission) must
        # never hide the other.
        comments = poll_facebook_comments if account.platform == "facebook" else poll_instagram_comments
        new, errors = 0, []
        for label, step in (("messages", poll_meta_conversations), ("comments", comments)):
            try:
                with db.begin_nested():
                    new += step(db, account)
            except ApiError as exc:
                errors.append("%s: %s" % (label, _meta_poll_error(account, label, exc)))
        state.sync_error = "; ".join(errors)[:300] or None
        return new
    if account.platform == "telegram" and not state.telegram_webhook_active:
        return poll_telegram(db, account, state)
    return 0  # WhatsApp: webhooks only


def import_thread(db: Session, account: SocialAccount, thread: dict) -> int:
    """Store the messages of one Graph conversation (oldest first: replies get later ids than questions)."""
    new = 0
    people = [p for p in ((thread.get("participants") or {}).get("data") or [])
              if str(p.get("id")) != account.external_id]
    person = people[0] if people else {}
    messages = (thread.get("messages") or {}).get("data") or []
    for item in reversed(messages):
        author = item.get("from") or {}
        recipients = (item.get("to") or {}).get("data") or [{}]
        event = {"sender": {"id": author.get("id")}, "recipient": {"id": recipients[0].get("id")},
                 "timestamp": int(parse_dt(item.get("created_time")).timestamp()),
                 "customer_name": person.get("name") or person.get("username"),
                 "customer_handle": person.get("username"),
                 "message": {"mid": item.get("id"), "text": item.get("message") or "",
                             "is_echo": str(author.get("id")) == account.external_id}}
        new += meta_messaging(db, account, event, from_poll=True)
    return new


def poll_meta_conversations(db: Session, account: SocialAccount) -> int:
    return sum(import_thread(db, account, thread) for thread in get_messenger(account).fetch_conversations())


def import_facebook_comments(db: Session, account: SocialAccount, messenger, post: dict) -> int:
    new = 0
    for item in reversed(messenger.fetch_comments(post["external_id"])):
        parent = (item.get("parent") or {}).get("id")
        author = item.get("from") or {}
        new += comment(db, account, comment_id=item.get("id"), root_id=parent or item.get("id"), post=post,
                       author_id=author.get("id"), author_name=author.get("name"), handle=None,
                       text=item.get("message"), date=parse_dt(item.get("created_time")))
    return new


def import_instagram_comments(db: Session, account: SocialAccount, messenger, post: dict) -> int:
    new = 0
    for item in reversed(messenger.fetch_comments(post["external_id"])):
        rows = [(item, item.get("id"))] + [
            (reply, item.get("id")) for reply in ((item.get("replies") or {}).get("data") or [])]
        for row, root in rows:
            author = row.get("from") or {}
            username = row.get("username") or author.get("username")
            author_id = author.get("id") or (account.external_id if username and username == account.username
                                             else None)
            new += comment(db, account, comment_id=row.get("id"), root_id=root, post=post,
                           author_id=author_id, author_name=username, handle=username,
                           text=row.get("text"), date=parse_dt(row.get("timestamp")))
    return new


def poll_facebook_comments(db: Session, account: SocialAccount) -> int:
    since = utcnow() - timedelta(days=POLL_POST_DAYS)
    targets = db.scalars(select(PostTarget).where(
        PostTarget.account_id == account.id, PostTarget.state == "posted", PostTarget.external_id.is_not(None),
        PostTarget.published_at >= since).order_by(PostTarget.published_at.desc()).limit(20)).all()
    messenger = get_messenger(account)
    new = 0
    for target in targets:
        post = {"target_id": target.id, "external_id": target.external_id, "url": target.external_url}
        new += import_facebook_comments(db, account, messenger, post)
    return new


def poll_instagram_comments(db: Session, account: SocialAccount) -> int:
    messenger = get_messenger(account)
    new = 0
    for media in messenger.fetch_recent_media():
        post = service.post_info(db, account, media.get("id"))
        post.update(url=post.get("url") or media.get("permalink"), text=media.get("caption"))
        new += import_instagram_comments(db, account, messenger, post)
    return new


def poll_telegram(db: Session, account: SocialAccount, state: AccountInboxState) -> int:
    messenger = get_messenger(account)
    try:
        updates = messenger.get_updates(state.telegram_offset)
    except ApiError as exc:
        if exc.status == 409:  # a webhook is set: Telegram pushes the messages instead
            state.telegram_webhook_active = True
            return 0
        raise
    new = 0
    offset = state.telegram_offset or 0
    for update in updates or []:
        offset = max(offset, int(update.get("update_id") or 0) + 1)
        new += telegram_webhook(db, account, update)
    state.telegram_offset = offset
    return new
