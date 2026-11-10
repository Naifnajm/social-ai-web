"""Conversation operations shared by webhooks, polling, the assistant and the API.

    conv = find_or_create(db, account, "dm", "PSID1", customer={"name": "Sara"})
    message, created = ingest(db, conv, {"direction": "in", "body": "Hi", "external_id": "m_1"}, bot=True)
    send_reply(db, conv, "Hello!", "dm", user=ctx.user)
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.core.http import ApiError
from app.core.i18n import _
from app.core.notify import notify, notify_role
from app.modules.social.models import PostTarget, SocialAccount
from app.modules.workspaces.models import Role

from .bot_config import workspace_option
from .messaging import LABELS, get_messenger
from .models import Contact, Conversation, Message
from .text import aware, digits, utcnow

_logger = logging.getLogger(__name__)

# Meta / WhatsApp: free-form replies are only allowed within 24 h of the customer's last message.
REPLY_WINDOW = timedelta(hours=24)
HUMAN_AGENT_WINDOW = timedelta(days=7)
WINDOW_PLATFORMS = ("facebook", "instagram", "whatsapp")
BOT_MAX_AGE = timedelta(hours=24)  # never answer older messages (first sync of an old inbox)
# a new conversation sorts by its first message (set by after_message), whatever its date
NO_MESSAGE_YET = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ------------------------------------------------------------------ bot scheduling (after commit)
def schedule_bot(db: Session, conversation_id: int) -> None:
    """Remember that the assistant must look at this conversation once the transaction is committed."""
    db.info.setdefault("inbox_bot", set()).add(conversation_id)


def run_scheduled(db: Session) -> int:
    """Enqueue the assistant for the conversations scheduled in this session (call after ``commit``)."""
    from app.core.jobs import enqueue
    ids = sorted(db.info.pop("inbox_bot", set()))
    for conversation_id in ids:
        try:
            enqueue("app.modules.inbox.tasks.run_bot", conversation_id)
        except Exception:  # Redis down: the periodic task picks the messages up later
            _logger.warning("could not enqueue the inbox assistant", exc_info=True)
    return len(ids)


def bot_wanted(direction: str, date) -> bool:
    return direction == "in" and utcnow() - aware(date) <= BOT_MAX_AGE


# ------------------------------------------------------------------ ingestion
def post_info(db: Session, account: SocialAccount, post_id: str | None) -> dict:
    target = None
    if post_id:
        target = db.scalar(select(PostTarget).where(PostTarget.account_id == account.id,
                                                    PostTarget.external_id == str(post_id)).limit(1))
    return {"target_id": target.id if target else None, "external_id": post_id,
            "url": target.external_url if target else None}


def find_conversation(db: Session, account: SocialAccount, kind: str, thread_id: str) -> Conversation | None:
    return db.scalar(select(Conversation).where(Conversation.account_id == account.id, Conversation.kind == kind,
                                                Conversation.external_thread_id == str(thread_id)))


def find_or_create(db: Session, account: SocialAccount, kind: str, thread_id, customer: dict | None = None,
                   post: dict | None = None) -> Conversation:
    """Conversation for a thread of one account, created on the first message."""
    thread_id = str(thread_id)
    customer = {k: v for k, v in (customer or {}).items() if v}
    post = {k: v for k, v in (post or {}).items() if v}
    conv = find_conversation(db, account, kind, thread_id)
    if conv:
        for key, field in (("name", "customer_name"), ("handle", "customer_handle"),
                           ("avatar_url", "avatar_url"), ("user_id", "external_user_id")):
            if customer.get(key) and not getattr(conv, field):
                setattr(conv, field, str(customer[key])[:200] if key != "avatar_url" else customer[key])
        if post.get("target_id") and not conv.post_target_id:
            conv.post_target_id = post["target_id"]
        return conv
    conv = Conversation(
        workspace_id=account.workspace_id, account_id=account.id, platform=account.platform, kind=kind,
        external_thread_id=thread_id, customer_name=(customer.get("name") or None),
        customer_handle=customer.get("handle"), external_user_id=customer.get("user_id"),
        avatar_url=customer.get("avatar_url"), post_target_id=post.get("target_id"),
        external_post_id=post.get("external_id"), post_url=post.get("url"),
        post_preview=(post.get("text") or "")[:280] or None, last_message_at=NO_MESSAGE_YET,
    )
    if conv.post_target_id and not (conv.post_url and conv.post_preview):
        target = db.get(PostTarget, conv.post_target_id)
        if target:
            conv.post_url = conv.post_url or target.external_url
            conv.post_preview = conv.post_preview or ((target.post.content or "")[:280] if target.post else None)
    try:
        with db.begin_nested():
            db.add(conv)
            db.flush()
    except IntegrityError:  # created meanwhile by a parallel webhook
        conv = find_conversation(db, account, kind, thread_id)
        if conv:
            return conv
        raise
    if not conv.contact_id:
        match_contact(db, conv, customer.get("phone"))
    return conv


def find_message(db: Session, account_id: int, external_id) -> Message | None:
    if not external_id:
        return None
    return db.scalar(select(Message).where(Message.account_id == account_id,
                                           Message.external_id == str(external_id)))


def ingest(db: Session, conv: Conversation, vals: dict, *, bot: bool = True) -> tuple[Message, bool]:
    """Store one message of ``conv``. Idempotent: returns the existing message for a known network id.

    ``vals``: direction, body, external_id, sent_at, author_name, author_external_id, media_ids, reply_to,
    channel, is_bot, user_id, trigger_id, ai_confidence, state."""
    external_id = vals.get("external_id")
    existing = find_message(db, conv.account_id, external_id)
    if existing:
        return existing, False
    now = utcnow()
    date = aware(vals.get("sent_at")) or now
    if date > now + timedelta(minutes=5):  # clock skew from the network
        date = now
    inbound = vals.get("direction", "in") == "in"
    values = dict(vals, sent_at=date, external_id=str(external_id) if external_id else None)
    values.setdefault("state", "received" if inbound else "sent")
    if inbound and bot:
        values["bot_state"] = "pending"
    message = Message(workspace_id=conv.workspace_id, conversation_id=conv.id, account_id=conv.account_id,
                      **values)
    try:
        with db.begin_nested():
            db.add(message)
            db.flush()
    except IntegrityError:
        existing = find_message(db, conv.account_id, external_id)
        if existing:
            return existing, False
        raise
    after_message(conv, message)
    if inbound and bot:
        schedule_bot(db, conv.id)
    return message, True


def after_message(conv: Conversation, message: Message) -> None:
    date = aware(message.sent_at)
    if message.state == "suggested":
        return
    if not conv.last_message_at or date >= aware(conv.last_message_at):
        conv.last_message_at = date
        conv.snippet = (message.body or "").strip()[:160] or (_("📎 Attachment") if message.media_ids else None)
    if message.direction == "in":
        if not conv.last_inbound_at or date >= aware(conv.last_inbound_at):
            conv.last_inbound_at = date
        conv.unread = True
        if not conv.first_inbound_at:
            conv.first_inbound_at = date
        if conv.state == "done":
            conv.state, conv.bot_paused, conv.handover_sent = "open", False, False
    elif message.state == "sent":
        if conv.first_inbound_at and not conv.first_response_at and date >= aware(conv.first_inbound_at):
            conv.first_response_at = date


def match_contact(db: Session, conv: Conversation, phone: str | None = None) -> Contact | None:
    """Re-use the contact of an earlier conversation, match WhatsApp numbers, else create one."""
    contact = None
    if conv.external_user_id:
        contact_id = db.scalar(select(Conversation.contact_id).where(
            Conversation.workspace_id == conv.workspace_id, Conversation.platform == conv.platform,
            Conversation.external_user_id == conv.external_user_id, Conversation.contact_id.is_not(None),
            Conversation.id != conv.id).limit(1))
        contact = db.get(Contact, contact_id) if contact_id else None
    phone = phone or (conv.external_user_id if conv.platform == "whatsapp" else None)
    number = digits(phone)
    if not contact and len(number) >= 8:
        contact = db.scalar(select(Contact).where(Contact.workspace_id == conv.workspace_id,
                                                  Contact.phone.like(f"%{number[-9:]}")).limit(1))
    if not contact:
        if not workspace_option(db, conv.workspace_id, "create_contacts"):
            return None
        label = LABELS.get(conv.platform, conv.platform)
        contact = Contact(workspace_id=conv.workspace_id,
                          name=(conv.customer_name or conv.customer_handle
                                or f"{label} {conv.external_user_id or conv.external_thread_id}")[:200],
                          handle=conv.customer_handle, platform=conv.platform,
                          external_user_id=conv.external_user_id, avatar_url=conv.avatar_url,
                          phone=("+" + number) if number else None)
        db.add(contact)
        db.flush()
    conv.contact_id = contact.id
    return contact


# ------------------------------------------------------------------ sending
def window_tag(db: Session, conv: Conversation, is_bot: bool) -> str | None:
    """None when a normal reply is allowed, "HUMAN_AGENT" for late human Meta replies; raises otherwise."""
    if conv.kind != "dm" or conv.platform not in WINDOW_PLATFORMS or not conv.last_inbound_at:
        return None
    age = utcnow() - aware(conv.last_inbound_at)
    if age <= REPLY_WINDOW:
        return None
    if (not is_bot and conv.platform in ("facebook", "instagram") and age <= HUMAN_AGENT_WINDOW
            and workspace_option(db, conv.workspace_id, "human_agent_tag")):
        return "HUMAN_AGENT"
    if conv.platform == "whatsapp":
        raise AppError(_("WhatsApp only accepts free replies within 24 hours of the customer's last message "
                         "(last message: {days} days ago). Ask the customer to write again, or use an approved "
                         "template from WhatsApp Manager.", days=age.days), code="window_closed")
    raise AppError(_("{network} only accepts replies within 24 hours of the customer's last message (last message: "
                     "{hours} hours ago). Enable “Allow late human replies” in the inbox settings to answer up to "
                     "7 days later.", network=LABELS.get(conv.platform, conv.platform),
                     hours=int(age.total_seconds() // 3600)), code="window_closed")


def window_info(db: Session, conv: Conversation) -> dict:
    if conv.kind != "dm" or conv.platform not in WINDOW_PLATFORMS or not conv.last_inbound_at:
        return {"limited": False, "open": True, "hours_left": 0.0, "human_agent": False}
    age = utcnow() - aware(conv.last_inbound_at)
    human_agent = (conv.platform in ("facebook", "instagram") and age <= HUMAN_AGENT_WINDOW
                   and bool(workspace_option(db, conv.workspace_id, "human_agent_tag")))
    left = (REPLY_WINDOW - age).total_seconds() / 3600.0
    return {"limited": True, "open": age <= REPLY_WINDOW, "hours_left": max(0.0, round(left, 1)),
            "human_agent": human_agent}


def last_inbound(db: Session, conv: Conversation) -> Message | None:
    return db.scalar(select(Message).where(Message.conversation_id == conv.id, Message.direction == "in",
                                           Message.external_id.is_not(None))
                     .order_by(Message.sent_at.desc(), Message.id.desc()).limit(1))


def send_reply(db: Session, conv: Conversation, body: str, channel: str = "dm", *, is_bot: bool = False,
               user=None, trigger=None, confidence: int = 0, raise_on_error: bool = False) -> Message:
    """Send ``body`` to the customer and record it. Returns the message (state sent / failed)."""
    body = (body or "").strip()
    if not body:
        raise AppError(_("The message is empty."), code="empty")
    account = conv.account
    tag = None
    if channel == "dm":
        if conv.kind != "dm":
            raise AppError(_("This is a comment: reply publicly or privately."), code="bad_channel")
        tag = window_tag(db, conv, is_bot)
    elif conv.kind != "comment":
        raise AppError(_("Public and private replies are only for comments."), code="bad_channel")
    external_id, error = None, None
    try:
        messenger = get_messenger(account)
        if channel == "dm":
            result = messenger.send_dm(conv.external_thread_id, body, tag=tag)
        else:
            last_in = last_inbound(db, conv)
            if channel == "public":
                target = conv.external_thread_id if conv.platform == "instagram" else (
                    last_in.external_id if last_in else conv.external_thread_id)
                result = messenger.reply_comment(target, body)
            else:
                result = messenger.private_reply(last_in.external_id if last_in else conv.external_thread_id, body)
        external_id = result.get("external_id") or None
    except ApiError as exc:
        error = exc.message
        if exc.status == 401:
            account.state, account.last_error = "expired", exc.message[:500]
    message, _created = ingest(db, conv, {
        "direction": "out", "channel": channel, "body": body, "external_id": external_id,
        "author_name": account.name, "is_bot": is_bot, "user_id": None if is_bot else (user.id if user else None),
        "trigger_id": trigger.id if trigger else None, "ai_confidence": confidence,
        "state": "failed" if error else "sent", "error": error,
    }, bot=False)
    if error:
        if raise_on_error:
            raise AppError(error, code="send_failed")
        return message
    if not is_bot:
        conv.bot_paused = True
        conv.unread = False
        if conv.state == "pending":
            conv.state = "open"
        if not conv.assignee_id and user:
            conv.assignee_id = user.id
    return message


def hide_comment(db: Session, conv: Conversation, hide: bool = True) -> None:
    if conv.kind != "comment":
        raise AppError(_("Only comments can be hidden."), code="bad_kind")
    targets = db.scalars(select(Message).where(Message.conversation_id == conv.id, Message.direction == "in",
                                               Message.external_id.is_not(None),
                                               Message.is_hidden.is_not(hide))).all()
    messenger = get_messenger(conv.account)
    for message in targets:
        messenger.hide_comment(message.external_id, hide)
        message.is_hidden = hide
    conv.is_hidden = hide


def set_state(conv: Conversation, state: str) -> None:
    if state == "done":
        # closing ends a human take-over: the assistant may answer again when the customer comes back
        conv.bot_paused, conv.handover_sent, conv.unread = False, False, False
    elif conv.state == "done":
        conv.bot_paused = False
    conv.state = state


def set_pending(db: Session, conv: Conversation, reason: str | None) -> None:
    """A human must answer: flag the conversation and tell the team (once) — in-app + mobile push."""
    already = conv.state == "pending"
    conv.state = "pending"
    conv.handover_reason = (reason or "")[:300] or None
    if already:
        return
    title = _("Customer waiting: {name}", name=conv.display_name)
    body = reason or _("The assistant needs a human.")
    link = f"/inbox/{conv.id}"
    if conv.assignee_id:
        notify(db, conv.workspace_id, [conv.assignee_id], kind="inbox.handover", title=title, body=body, link=link)
    else:
        notify_role(db, conv.workspace_id, Role.admin, kind="inbox.handover", title=title, body=body, link=link)


def get_conversation(db: Session, workspace_id: int, conversation_id: int, *, lock: bool = False) -> Conversation:
    query = select(Conversation).where(Conversation.id == conversation_id, Conversation.workspace_id == workspace_id)
    if lock:
        query = query.with_for_update()
    conv = db.scalar(query)
    if not conv:
        raise NotFound(_("This conversation no longer exists."), code="not_found")
    return conv


def suggestion_of(db: Session, conv: Conversation) -> Message | None:
    return db.scalar(select(Message).where(Message.conversation_id == conv.id, Message.state == "suggested")
                     .order_by(Message.id.desc()).limit(1))


def store_suggestion(db: Session, conv: Conversation, body: str, channel: str, confidence: int,
                     note: str | None = None) -> Message:
    """Keep one AI draft per conversation, waiting for a human."""
    for old in db.scalars(select(Message).where(Message.conversation_id == conv.id, Message.state == "suggested")):
        db.delete(old)
    message = Message(workspace_id=conv.workspace_id, conversation_id=conv.id, account_id=conv.account_id,
                      direction="out", channel=channel, body=body, state="suggested", is_bot=True,
                      ai_confidence=confidence, ai_note=(note or "")[:300] or None, author_name=conv.account.name,
                      sent_at=utcnow())
    db.add(message)
    db.flush()
    return message


def mark_bot_state(db: Session, messages: list[Message], state: str, note: str | None = None) -> None:
    for message in messages:
        message.bot_state = state
        message.ai_note = (note or "")[:300] or None


def unread_count(db: Session, workspace_id: int) -> dict:
    rows = db.execute(select(Conversation.state, func.count()).where(
        Conversation.workspace_id == workspace_id, Conversation.unread.is_(True),
        Conversation.state != "done").group_by(Conversation.state)).all()
    counts = dict(rows)
    pending = db.scalar(select(func.count()).select_from(Conversation).where(
        Conversation.workspace_id == workspace_id, Conversation.state == "pending")) or 0
    return {"unread": sum(counts.values()), "pending": pending}
