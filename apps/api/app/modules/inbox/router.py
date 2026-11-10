"""Inbox API (web + mobile): conversations, replies, the assistant, canned replies, knowledge, triggers,
per-account assistant settings, WhatsApp accounts, statistics and the unread badge counter."""
import base64
import secrets as pysecrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.http import ApiError
from app.core.i18n import _
from app.core.models import Media
from app.modules.auth.models import User
from app.modules.billing import limits
from app.modules.brand.models import BrandKit
from app.modules.social.models import Post, PostTarget, SocialAccount
from app.modules.workspaces.models import Membership, Role
from app.modules.workspaces.settings import set_setting

from . import bot, service, sources
from .bot_config import (WORKSPACE_DEFAULTS, account_secrets, bot_config, mode_for, set_account_secret,
                         update_bot_config, whatsapp_provider, workspace_option)
from .config import inbox_settings
from .messaging import get_messenger
from .models import (INBOX_PLATFORMS, INTENTS, SENTIMENTS, BotTrigger, CannedReply, Contact, Conversation,
                     ConversationTag, KnowledgeEntry, Message, MetaApp)
from .public import meta_webhook_url, telegram_webhook_url, twilio_webhook_url
from .schemas import (AccountCheckOut, AttachmentOut, BotSettings, CannedIn, CannedOut, ContactOut, ContactUpdate,
                      ConversationPage, ConversationRow, ConversationUpdate, FolderCounts, HideIn,
                      InboxAccountOut, InboxAccountUpdate, InboxMeta, InboxSettingsIn, InboxSettingsOut,
                      InboxStats, KnowledgeIn, KnowledgeOut, MessageOut, PlatformStat, PostRef, SendIn, SendOut,
                      SuggestionSendIn, SyncOut, TagIn, TagOut, ThreadOut, TriggerIn, TriggerOut, UnreadOut,
                      UserRef, WhatsAppAccountIn, WhatsAppAccountUpdate, WindowOut)
from .text import utcnow

router = APIRouter(prefix="/inbox", tags=["inbox"])

FOLDERS = ("all", "unassigned", "mine", "pending", "done")


# ------------------------------------------------------------------ serialization
def _users(ctx: Ctx, ids) -> dict[int, User]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: u for u in ctx.db.scalars(select(User).where(User.id.in_(ids)))}


def _user_ref(user: User | None) -> UserRef | None:
    return UserRef(id=user.id, name=user.name, avatar_url=user.avatar_url) if user else None


def _rows(ctx: Ctx, convs: list[Conversation]) -> list[ConversationRow]:
    if not convs:
        return []
    ids = [c.id for c in convs]
    suggested = set(ctx.db.scalars(select(Message.conversation_id).where(
        Message.conversation_id.in_(ids), Message.state == "suggested")))
    users = _users(ctx, [c.assignee_id for c in convs])
    return [ConversationRow(
        id=c.id, account_id=c.account_id, account_name=c.account.name, platform=c.platform, kind=c.kind,
        name=c.display_name, handle=c.customer_handle, avatar_url=c.avatar_url, snippet=c.snippet,
        last_message_at=c.last_message_at, unread=c.unread, state=c.state, intent=c.intent, sentiment=c.sentiment,
        assignee=_user_ref(users.get(c.assignee_id)), tags=[TagOut.model_validate(t) for t in c.tags],
        has_suggestion=c.id in suggested, bot_paused=c.bot_paused, is_hidden=c.is_hidden,
    ) for c in convs]


def _messages_out(ctx: Ctx, messages: list[Message]) -> list[MessageOut]:
    media_ids = {mid for m in messages for mid in (m.media_ids or [])}
    media = {}
    if media_ids:
        media = {x.id: x for x in ctx.db.scalars(select(Media).where(Media.id.in_(media_ids),
                                                                       Media.workspace_id == ctx.workspace.id))}
    users = _users(ctx, [m.user_id for m in messages])
    return [MessageOut(
        id=m.id, direction=m.direction, channel=m.channel, author=m.author_name, body=m.body or "",
        sent_at=m.sent_at, is_bot=m.is_bot, user=_user_ref(users.get(m.user_id)), state=m.state, error=m.error,
        confidence=m.ai_confidence or 0, note=m.ai_note, hidden=m.is_hidden,
        trigger=m.trigger.name if m.trigger_id and m.trigger else None,
        attachments=[AttachmentOut(id=x.id, filename=x.filename, mimetype=x.mimetype, url=f"/api/media/{x.id}/file")
                     for x in (media.get(i) for i in (m.media_ids or [])) if x],
    ) for m in messages]


def _contact_out(ctx: Ctx, contact: Contact | None) -> ContactOut | None:
    if not contact:
        return None
    out = ContactOut.model_validate(contact)
    out.conversations = ctx.db.scalar(select(func.count()).select_from(Conversation).where(
        Conversation.contact_id == contact.id)) or 0
    return out


def _thread(ctx: Ctx, conv: Conversation, *, mark_read: bool = False) -> ThreadOut:
    if mark_read and conv.unread:
        conv.unread = False
    messages = list(ctx.db.scalars(select(Message).where(Message.conversation_id == conv.id)
                                   .order_by(Message.sent_at, Message.id)))
    suggestion = [m for m in messages if m.state == "suggested"][-1:]
    shown = [m for m in messages if m.state != "suggested"]
    row = _rows(ctx, [conv])[0]
    post = None
    if conv.kind == "comment":
        target = ctx.db.get(PostTarget, conv.post_target_id) if conv.post_target_id else None
        post = PostRef(url=conv.post_url or (target.external_url if target else None),
                       preview=conv.post_preview, post_id=target.post_id if target else None)
    meta = conv.platform in ("facebook", "instagram")
    return ThreadOut(
        **row.model_dump(), external_user_id=conv.external_user_id, messages=_messages_out(ctx, shown),
        suggestion=_messages_out(ctx, suggestion)[0] if suggestion else None,
        contact=_contact_out(ctx, conv.contact), post=post, note=conv.note, handover_reason=conv.handover_reason,
        bot_error=conv.bot_error, window=WindowOut(**service.window_info(ctx.db, conv)),
        bot_mode=mode_for(conv.account, conv.kind), can_private=conv.kind == "comment" and meta,
        can_hide=conv.kind == "comment" and meta, can_like=conv.kind == "comment" and conv.platform == "facebook",
        first_inbound_at=conv.first_inbound_at,
    )


def _conv(ctx: Ctx, conversation_id: int, lock: bool = False) -> Conversation:
    return service.get_conversation(ctx.db, ctx.workspace.id, conversation_id, lock=lock)


# ------------------------------------------------------------------ listing
def _encode_cursor(conv: Conversation) -> str:
    raw = f"{conv.last_message_at.isoformat()}|{conv.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, _sep, ident = raw.rpartition("|")
        return datetime.fromisoformat(stamp), int(ident)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError(_("Invalid cursor."), code="bad_cursor") from exc


def _base_filters(ctx: Ctx, platform, kind, tag_id, account_id, search) -> list:
    where = [Conversation.workspace_id == ctx.workspace.id]
    if platform:
        where.append(Conversation.platform == platform)
    if kind in ("dm", "comment"):
        where.append(Conversation.kind == kind)
    if account_id:
        where.append(Conversation.account_id == account_id)
    if tag_id:
        where.append(Conversation.tags.any(ConversationTag.id == tag_id))
    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        where.append(or_(Conversation.customer_name.ilike(like), Conversation.customer_handle.ilike(like),
                         Conversation.snippet.ilike(like),
                         Conversation.id.in_(select(Message.conversation_id).where(
                             Message.workspace_id == ctx.workspace.id, Message.body.ilike(like)))))
    return where


def _folder_filter(ctx: Ctx, folder: str) -> list:
    if folder == "done":
        return [Conversation.state == "done"]
    if folder == "pending":
        return [Conversation.state == "pending"]
    where = [Conversation.state != "done"]
    if folder == "unassigned":
        where.append(Conversation.assignee_id.is_(None))
    elif folder == "mine":
        where.append(Conversation.assignee_id == ctx.user.id)
    return where


def _count(ctx: Ctx, where: list) -> int:
    return ctx.db.scalar(select(func.count()).select_from(Conversation).where(*where)) or 0


@router.get("/conversations", response_model=ConversationPage)
def list_conversations(folder: str = "all", platform: str | None = None, kind: str | None = None,
                       tag_id: int | None = None, account_id: int | None = None, search: str | None = None,
                       unread: bool = False, cursor: str | None = None, limit: int = Query(40, ge=1, le=100),
                       ctx: Ctx = Depends(workspace_ctx())):
    folder = folder if folder in FOLDERS else "all"
    base = _base_filters(ctx, platform, kind, tag_id, account_id, search)
    where = base + _folder_filter(ctx, folder)
    if unread:
        where.append(Conversation.unread.is_(True))
    if cursor:
        stamp, ident = _decode_cursor(cursor)
        where.append(or_(Conversation.last_message_at < stamp,
                         and_(Conversation.last_message_at == stamp, Conversation.id < ident)))
    convs = list(ctx.db.scalars(select(Conversation).where(*where)
                                .order_by(Conversation.last_message_at.desc(), Conversation.id.desc())
                                .limit(limit + 1)))
    more = len(convs) > limit
    convs = convs[:limit]
    counts = FolderCounts(**{f: _count(ctx, base + _folder_filter(ctx, f)) for f in FOLDERS if f != "done"},
                          unread=_count(ctx, base + _folder_filter(ctx, "all") + [Conversation.unread.is_(True)]))
    return ConversationPage(items=_rows(ctx, convs), next_cursor=_encode_cursor(convs[-1]) if more else None,
                            counts=counts)


@router.get("/unread", response_model=UnreadOut)
def unread_counter(ctx: Ctx = Depends(workspace_ctx())):
    """Badge counter (web nav + mobile tab)."""
    return UnreadOut(**service.unread_count(ctx.db, ctx.workspace.id))


@router.get("/conversations/{conversation_id}", response_model=ThreadOut)
def get_thread(conversation_id: int, mark_read: bool = True, ctx: Ctx = Depends(workspace_ctx())):
    return _thread(ctx, _conv(ctx, conversation_id), mark_read=mark_read and ctx.can(Role.editor))


# ------------------------------------------------------------------ actions
@router.post("/conversations/{conversation_id}/messages", response_model=SendOut, status_code=201)
def send_message(conversation_id: int, data: SendIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    conv = _conv(ctx, conversation_id, lock=True)
    channel = data.channel
    if conv.kind == "comment" and channel == "dm":
        channel = "public"
    if conv.kind == "dm":
        channel = "dm"
    message = service.send_reply(ctx.db, conv, data.body, channel, user=ctx.user, raise_on_error=False)
    ctx.db.flush()
    return SendOut(message=_messages_out(ctx, [message])[0], thread=_thread(ctx, conv))


@router.post("/conversations/{conversation_id}/suggest", response_model=ThreadOut)
def write_with_ai(conversation_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    conv = _conv(ctx, conversation_id, lock=True)
    bot.suggest_now(ctx.db, conv, user_id=ctx.user.id)
    return _thread(ctx, conv)


def _suggestion(ctx: Ctx, message_id: int) -> Message:
    message = ctx.db.scalar(select(Message).where(Message.id == message_id, Message.workspace_id == ctx.workspace.id))
    if not message or message.state != "suggested":
        raise NotFound(_("This suggestion was already used or discarded."), code="not_found")
    return message


@router.post("/suggestions/{message_id}/send", response_model=SendOut)
def send_suggestion(message_id: int, data: SuggestionSendIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    suggestion = _suggestion(ctx, message_id)
    conv = _conv(ctx, suggestion.conversation_id, lock=True)
    text = data.body if data.body is not None else suggestion.body
    channel = suggestion.channel
    ctx.db.delete(suggestion)
    ctx.db.flush()
    message = service.send_reply(ctx.db, conv, text, channel, user=ctx.user)
    return SendOut(message=_messages_out(ctx, [message])[0], thread=_thread(ctx, conv))


@router.delete("/suggestions/{message_id}", response_model=ThreadOut)
def discard_suggestion(message_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    suggestion = _suggestion(ctx, message_id)
    conv = _conv(ctx, suggestion.conversation_id)
    ctx.db.delete(suggestion)
    ctx.db.flush()
    return _thread(ctx, conv)


@router.post("/conversations/{conversation_id}/hide", response_model=ThreadOut)
def hide(conversation_id: int, data: HideIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    conv = _conv(ctx, conversation_id)
    try:
        service.hide_comment(ctx.db, conv, data.hide)
    except ApiError as exc:
        raise AppError(exc.message, code="external_api") from exc
    return _thread(ctx, conv)


@router.post("/conversations/{conversation_id}/like", status_code=204)
def like(conversation_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Like the customer's last comment (Facebook)."""
    conv = _conv(ctx, conversation_id)
    last = service.last_inbound(ctx.db, conv)
    if conv.kind != "comment" or not last:
        raise AppError(_("There is no comment to like."), code="no_comment")
    try:
        get_messenger(conv.account).like_comment(last.external_id)
    except ApiError as exc:
        raise AppError(exc.message, code="external_api") from exc


@router.patch("/conversations/{conversation_id}", response_model=ThreadOut)
def update_conversation(conversation_id: int, data: ConversationUpdate,
                        ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    conv = _conv(ctx, conversation_id)
    fields = data.model_fields_set
    if "assignee_id" in fields:
        if data.assignee_id and not ctx.db.scalar(select(Membership.id).where(
                Membership.workspace_id == ctx.workspace.id, Membership.user_id == data.assignee_id)):
            raise NotFound(_("This person is not a member of the workspace."), code="not_found")
        conv.assignee_id = data.assignee_id
    if "tag_ids" in fields:
        ids = set(data.tag_ids or [])
        tags = list(ctx.db.scalars(select(ConversationTag).where(ConversationTag.workspace_id == ctx.workspace.id,
                                                                ConversationTag.id.in_(ids)))) if ids else []
        if len(tags) != len(ids):
            raise NotFound(_("Tag not found."), code="not_found")
        conv.tags = tags
    for key in ("note", "intent", "sentiment", "unread", "bot_paused"):
        if key in fields and (getattr(data, key) is not None or key in ("note", "intent", "sentiment")):
            setattr(conv, key, getattr(data, key))
    if "state" in fields and data.state:
        service.set_state(conv, data.state)
        if data.state != "pending":
            conv.handover_reason = None
    ctx.db.flush()
    return _thread(ctx, conv)


@router.post("/conversations/{conversation_id}/unread", status_code=204)
def mark_unread(conversation_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    _conv(ctx, conversation_id).unread = True


@router.post("/sync", response_model=SyncOut)
def sync_now(ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """"Sync now": read new messages of this workspace's accounts (polling)."""
    accounts = list(ctx.db.scalars(select(SocialAccount).where(
        SocialAccount.workspace_id == ctx.workspace.id, SocialAccount.inbox_enabled.is_(True),
        SocialAccount.active.is_(True), SocialAccount.platform.in_(INBOX_PLATFORMS))))
    result = sources.poll_accounts(ctx.db, accounts)
    ctx.db.commit()
    service.run_scheduled(ctx.db)
    return SyncOut(**result)


# ------------------------------------------------------------------ contacts
def _contact(ctx: Ctx, contact_id: int) -> Contact:
    contact = ctx.db.get(Contact, contact_id)
    if not contact or contact.workspace_id != ctx.workspace.id:
        raise NotFound(_("Contact not found."), code="not_found")
    return contact


@router.get("/contacts/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: int, ctx: Ctx = Depends(workspace_ctx())):
    return _contact_out(ctx, _contact(ctx, contact_id))


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(contact_id: int, data: ContactUpdate, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    contact = _contact(ctx, contact_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(contact, key, value)
    return _contact_out(ctx, contact)


# ------------------------------------------------------------------ tags
@router.get("/tags", response_model=list[TagOut])
def list_tags(ctx: Ctx = Depends(workspace_ctx())):
    return ctx.db.scalars(select(ConversationTag).where(ConversationTag.workspace_id == ctx.workspace.id)
                          .order_by(ConversationTag.name)).all()


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(data: TagIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    name = data.name.strip()
    tag = ctx.db.scalar(select(ConversationTag).where(ConversationTag.workspace_id == ctx.workspace.id,
                                                      func.lower(ConversationTag.name) == name.lower()))
    if tag:
        return tag
    tag = ConversationTag(workspace_id=ctx.workspace.id, name=name, color=data.color)
    ctx.db.add(tag)
    ctx.db.flush()
    return tag


def _tag(ctx: Ctx, tag_id: int) -> ConversationTag:
    tag = ctx.db.get(ConversationTag, tag_id)
    if not tag or tag.workspace_id != ctx.workspace.id:
        raise NotFound(_("Tag not found."), code="not_found")
    return tag


@router.patch("/tags/{tag_id}", response_model=TagOut)
def update_tag(tag_id: int, data: TagIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    tag = _tag(ctx, tag_id)
    tag.name, tag.color = data.name.strip(), data.color
    try:
        with ctx.db.begin_nested():
            ctx.db.flush()
    except IntegrityError as exc:
        raise AppError(_("This tag already exists."), code="duplicate") from exc
    return tag


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    ctx.db.delete(_tag(ctx, tag_id))


# ------------------------------------------------------------------ canned replies
def _owned(ctx: Ctx, model, item_id: int, message: str):
    item = ctx.db.get(model, item_id)
    if not item or item.workspace_id != ctx.workspace.id:
        raise NotFound(message, code="not_found")
    return item


@router.get("/canned-replies", response_model=list[CannedOut])
def list_canned(ctx: Ctx = Depends(workspace_ctx())):
    return ctx.db.scalars(select(CannedReply).where(CannedReply.workspace_id == ctx.workspace.id)
                          .order_by(CannedReply.sequence, CannedReply.name)).all()


@router.post("/canned-replies", response_model=CannedOut, status_code=201)
def create_canned(data: CannedIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    item = CannedReply(workspace_id=ctx.workspace.id, **data.model_dump())
    item.shortcut = (item.shortcut or "").strip().lstrip("/") or None
    ctx.db.add(item)
    ctx.db.flush()
    return item


@router.put("/canned-replies/{item_id}", response_model=CannedOut)
def update_canned(item_id: int, data: CannedIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    item = _owned(ctx, CannedReply, item_id, _("Canned reply not found."))
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    item.shortcut = (item.shortcut or "").strip().lstrip("/") or None
    return item


@router.delete("/canned-replies/{item_id}", status_code=204)
def delete_canned(item_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    ctx.db.delete(_owned(ctx, CannedReply, item_id, _("Canned reply not found.")))


# ------------------------------------------------------------------ knowledge
@router.get("/knowledge", response_model=list[KnowledgeOut])
def list_knowledge(ctx: Ctx = Depends(workspace_ctx())):
    return ctx.db.scalars(select(KnowledgeEntry).where(KnowledgeEntry.workspace_id == ctx.workspace.id)
                          .order_by(KnowledgeEntry.sequence, KnowledgeEntry.id)).all()


@router.post("/knowledge", response_model=KnowledgeOut, status_code=201)
def create_knowledge(data: KnowledgeIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    item = KnowledgeEntry(workspace_id=ctx.workspace.id, **data.model_dump())
    ctx.db.add(item)
    ctx.db.flush()
    return item


@router.put("/knowledge/{item_id}", response_model=KnowledgeOut)
def update_knowledge(item_id: int, data: KnowledgeIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    item = _owned(ctx, KnowledgeEntry, item_id, _("Knowledge entry not found."))
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    return item


@router.delete("/knowledge/{item_id}", status_code=204)
def delete_knowledge(item_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    ctx.db.delete(_owned(ctx, KnowledgeEntry, item_id, _("Knowledge entry not found.")))


# ------------------------------------------------------------------ triggers
def _check_trigger(ctx: Ctx, data: TriggerIn) -> None:
    if not (data.public_reply or "").strip() and not (data.dm_text or "").strip():
        raise AppError(_("Write a public reply, a private message, or both."), code="empty_trigger")
    if data.account_ids:
        found = ctx.db.scalar(select(func.count()).select_from(SocialAccount).where(
            SocialAccount.workspace_id == ctx.workspace.id, SocialAccount.id.in_(set(data.account_ids)),
            SocialAccount.platform.in_(("facebook", "instagram"))))
        if found != len(set(data.account_ids)):
            raise NotFound(_("Account not found."), code="not_found")
    if data.post_id and not ctx.db.scalar(select(Post.id).where(Post.id == data.post_id,
                                                                Post.workspace_id == ctx.workspace.id)):
        raise NotFound(_("Post not found."), code="not_found")


@router.get("/triggers", response_model=list[TriggerOut])
def list_triggers(ctx: Ctx = Depends(workspace_ctx())):
    rows = ctx.db.scalars(select(BotTrigger).where(BotTrigger.workspace_id == ctx.workspace.id)
                          .order_by(BotTrigger.sequence, BotTrigger.id)).all()
    return [TriggerOut(id=t.id, hit_count=t.hit_count, name=t.name, keywords=t.keywords, public_reply=t.public_reply,
                       dm_text=t.dm_text, account_ids=t.account_ids or [], post_id=t.post_id, active=t.active,
                       sequence=t.sequence) for t in rows]


def _trigger_out(t: BotTrigger) -> TriggerOut:
    return TriggerOut(id=t.id, hit_count=t.hit_count or 0, name=t.name, keywords=t.keywords,
                      public_reply=t.public_reply, dm_text=t.dm_text, account_ids=t.account_ids or [],
                      post_id=t.post_id, active=t.active, sequence=t.sequence)


@router.post("/triggers", response_model=TriggerOut, status_code=201)
def create_trigger(data: TriggerIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    _check_trigger(ctx, data)
    item = BotTrigger(workspace_id=ctx.workspace.id, **data.model_dump())
    ctx.db.add(item)
    ctx.db.flush()
    return _trigger_out(item)


@router.put("/triggers/{item_id}", response_model=TriggerOut)
def update_trigger(item_id: int, data: TriggerIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    item = _owned(ctx, BotTrigger, item_id, _("Trigger not found."))
    _check_trigger(ctx, data)
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    return _trigger_out(item)


@router.delete("/triggers/{item_id}", status_code=204)
def delete_trigger(item_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    ctx.db.delete(_owned(ctx, BotTrigger, item_id, _("Trigger not found.")))


# ------------------------------------------------------------------ accounts (assistant settings, webhooks)
def _inbox_account(ctx: Ctx, account_id: int) -> SocialAccount:
    account = ctx.db.get(SocialAccount, account_id)
    if not account or account.workspace_id != ctx.workspace.id or account.platform not in INBOX_PLATFORMS:
        raise NotFound(_("Account not found."), code="not_found")
    return account


def _account_out(ctx: Ctx, account: SocialAccount, open_counts: dict | None = None) -> InboxAccountOut:
    state = sources.account_state(ctx.db, account)
    kind, url = None, None
    provider = whatsapp_provider(account) if account.platform == "whatsapp" else None
    if account.platform in ("facebook", "instagram") or provider == "cloud":
        kind, url = "meta", meta_webhook_url()
    elif account.platform == "telegram":
        kind, url = "telegram", telegram_webhook_url(account.id, state.webhook_secret)
    elif provider == "twilio":
        kind, url = "twilio", twilio_webhook_url(account.id)
    extra = account.extra or {}
    has_token = bool(account_secrets(account).get("twilio_auth_token")) if provider == "twilio" else \
        bool(account.access_token)
    return InboxAccountOut(
        id=account.id, name=account.name, platform=account.platform, username=account.username,
        avatar_url=account.avatar_url, state=account.state, inbox_enabled=account.inbox_enabled,
        bot=BotSettings(**bot_config(account)), webhook_kind=kind, webhook_url=url if ctx.can(Role.admin) else None,
        telegram_webhook_active=state.telegram_webhook_active, last_sync_at=state.last_sync_at,
        sync_error=state.sync_error, whatsapp_provider=provider,
        whatsapp_number=extra.get("whatsapp_number") if account.platform == "whatsapp" else None,
        has_token=has_token, open_conversations=(open_counts or {}).get(account.id, 0),
    )


def _accounts(ctx: Ctx) -> list[SocialAccount]:
    return list(ctx.db.scalars(select(SocialAccount).where(
        SocialAccount.workspace_id == ctx.workspace.id, SocialAccount.platform.in_(INBOX_PLATFORMS),
        SocialAccount.active.is_(True)).order_by(SocialAccount.platform, SocialAccount.name)))


def _open_counts(ctx: Ctx) -> dict:
    return dict(ctx.db.execute(select(Conversation.account_id, func.count()).where(
        Conversation.workspace_id == ctx.workspace.id, Conversation.state != "done")
        .group_by(Conversation.account_id)).all())


@router.get("/accounts", response_model=list[InboxAccountOut])
def list_accounts(ctx: Ctx = Depends(workspace_ctx())):
    counts = _open_counts(ctx)
    return [_account_out(ctx, a, counts) for a in _accounts(ctx)]


@router.patch("/accounts/{account_id}", response_model=InboxAccountOut)
def update_account(account_id: int, data: InboxAccountUpdate, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    account = _inbox_account(ctx, account_id)
    if data.inbox_enabled is not None:
        account.inbox_enabled = data.inbox_enabled
    if data.bot is not None:
        values = data.bot.model_dump(exclude_unset=True)
        if values.get("brand_kit_id") and not ctx.db.scalar(select(BrandKit.id).where(
                BrandKit.id == values["brand_kit_id"], BrandKit.workspace_id == ctx.workspace.id)):
            raise NotFound(_("Brand kit not found."), code="not_found")
        update_bot_config(account, values)
    return _account_out(ctx, account)


@router.post("/accounts/{account_id}/sync", response_model=SyncOut)
def sync_account(account_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    account = _inbox_account(ctx, account_id)
    result = sources.poll_accounts(ctx.db, [account])
    ctx.db.commit()
    service.run_scheduled(ctx.db)
    return SyncOut(**result)


@router.post("/accounts/{account_id}/telegram-webhook", response_model=InboxAccountOut)
def set_telegram_webhook(account_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """Instant delivery: register this server's webhook with the Telegram bot (needs a public HTTPS API URL)."""
    account = _inbox_account(ctx, account_id)
    if account.platform != "telegram":
        raise AppError(_("Only Telegram bots use this webhook."), code="bad_platform")
    base = settings.public_api_url
    if not base.startswith("https://") or "localhost" in base or "127.0.0.1" in base:
        raise AppError(_("Telegram needs a public HTTPS address for the API (current: {url}). Without it the inbox "
                         "reads new messages every few minutes instead.", url=base), code="no_public_url")
    state = sources.account_state(ctx.db, account)
    try:
        get_messenger(account).set_webhook(telegram_webhook_url(account.id, state.webhook_secret),
                                           state.webhook_secret)
    except ApiError as exc:
        raise AppError(exc.message, code="external_api") from exc
    state.telegram_webhook_active, state.sync_error = True, None
    return _account_out(ctx, account)


@router.delete("/accounts/{account_id}/telegram-webhook", response_model=InboxAccountOut)
def remove_telegram_webhook(account_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    account = _inbox_account(ctx, account_id)
    if account.platform != "telegram":
        raise AppError(_("Only Telegram bots use this webhook."), code="bad_platform")
    try:
        get_messenger(account).delete_webhook()
    except ApiError as exc:
        raise AppError(exc.message, code="external_api") from exc
    sources.account_state(ctx.db, account).telegram_webhook_active = False
    return _account_out(ctx, account)


@router.post("/accounts/{account_id}/rotate-secret", response_model=InboxAccountOut)
def rotate_secret(account_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """New secret for the account's webhook URL (Telegram). Re-registers the Telegram webhook when it is set."""
    account = _inbox_account(ctx, account_id)
    state = sources.account_state(ctx.db, account)
    state.webhook_secret = pysecrets.token_urlsafe(24)
    if account.platform == "telegram" and state.telegram_webhook_active:
        try:
            get_messenger(account).set_webhook(telegram_webhook_url(account.id, state.webhook_secret),
                                               state.webhook_secret)
        except ApiError as exc:
            state.sync_error = exc.message[:300]
    return _account_out(ctx, account)


# ------------------------------------------------------------------ WhatsApp accounts (inbox only)
def _check_whatsapp(ctx: Ctx, account: SocialAccount) -> AccountCheckOut:
    try:
        profile = get_messenger(account).check()
    except ApiError as exc:
        account.state = "expired" if exc.status == 401 else "error"
        account.last_error, account.last_check_at = exc.message[:500], utcnow()
        return AccountCheckOut(ok=False, state=account.state, error=exc.message)
    account.state, account.last_error, account.last_check_at = "connected", None, utcnow()
    if profile.get("username") and not account.username:
        account.username = profile["username"][:160]
    return AccountCheckOut(ok=True, state=account.state)


def _apply_whatsapp(account: SocialAccount, provider: str, data) -> None:
    extra = dict(account.extra or {})
    extra["whatsapp_provider"] = provider
    values = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data)
    if values.get("name"):
        account.name = values["name"]
    if values.get("whatsapp_number") is not None:
        extra["whatsapp_number"] = values["whatsapp_number"].strip()
    if provider == "cloud":
        if values.get("phone_number_id"):
            account.external_id = values["phone_number_id"].strip()
        if values.get("access_token"):
            account.access_token = values["access_token"].strip()
    else:
        if values.get("twilio_account_sid"):
            extra["twilio_account_sid"] = values["twilio_account_sid"].strip()
        if values.get("twilio_auth_token"):
            set_account_secret(account, "twilio_auth_token", values["twilio_auth_token"].strip())
        number = extra.get("whatsapp_number") or ""
        account.external_id = "".join(ch for ch in number if ch.isdigit()) or account.external_id
        account.username = number or account.username
    account.extra = extra


@router.post("/whatsapp-accounts", response_model=InboxAccountOut, status_code=201)
def create_whatsapp_account(data: WhatsAppAccountIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    if data.provider == "cloud" and not (data.phone_number_id and data.access_token):
        raise AppError(_("Enter the phone number ID and the access token of the WhatsApp Cloud API."),
                       code="missing_fields")
    if data.provider == "twilio" and not (data.twilio_account_sid and data.twilio_auth_token and data.whatsapp_number):
        raise AppError(_("Enter the Twilio Account SID, Auth token and your WhatsApp sender number."),
                       code="missing_fields")
    limits.check(ctx.db, ctx.workspace.id, "social_accounts")
    account = SocialAccount(workspace_id=ctx.workspace.id, name=data.name.strip(), platform="whatsapp",
                            state="draft", inbox_enabled=True, active=True, bot_settings=None)
    _apply_whatsapp(account, data.provider, data)
    ctx.db.add(account)
    ctx.db.flush()
    if data.verify:
        _check_whatsapp(ctx, account)
    return _account_out(ctx, account)


@router.patch("/whatsapp-accounts/{account_id}", response_model=InboxAccountOut)
def update_whatsapp_account(account_id: int, data: WhatsAppAccountUpdate,
                            ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    account = _inbox_account(ctx, account_id)
    if account.platform != "whatsapp":
        raise NotFound(_("Account not found."), code="not_found")
    _apply_whatsapp(account, whatsapp_provider(account), data)
    return _account_out(ctx, account)


@router.post("/whatsapp-accounts/{account_id}/check", response_model=AccountCheckOut)
def check_whatsapp_account(account_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    account = _inbox_account(ctx, account_id)
    if account.platform != "whatsapp":
        raise NotFound(_("Account not found."), code="not_found")
    return _check_whatsapp(ctx, account)


@router.delete("/whatsapp-accounts/{account_id}", status_code=204)
def delete_whatsapp_account(account_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    account = _inbox_account(ctx, account_id)
    if account.platform != "whatsapp":
        raise NotFound(_("Account not found."), code="not_found")
    ctx.db.delete(account)


# ------------------------------------------------------------------ workspace inbox settings
def _settings_out(ctx: Ctx) -> InboxSettingsOut:
    app = ctx.db.scalar(select(MetaApp).where(MetaApp.workspace_id == ctx.workspace.id))
    values = {key: workspace_option(ctx.db, ctx.workspace.id, key) for key in WORKSPACE_DEFAULTS}
    return InboxSettingsOut(**values, meta_webhook_url=meta_webhook_url(),
                            platform_meta_app=bool(inbox_settings().meta_app_secret),
                            meta_app_id=app.app_id if app else None,
                            has_meta_app_secret=bool(app and app.app_secret),
                            meta_verify_token=app.verify_token if app else None)


@router.get("/settings", response_model=InboxSettingsOut)
def read_settings(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    return _settings_out(ctx)


@router.put("/settings", response_model=InboxSettingsOut)
def write_settings(data: InboxSettingsIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    values = data.model_dump(exclude_unset=True)
    for key in WORKSPACE_DEFAULTS:
        if key in values and values[key] is not None:
            value = values[key].strip() if isinstance(values[key], str) else values[key]
            set_setting(ctx.db, ctx.workspace.id, f"inbox.{key}", value)
    if "meta_app_id" in values or "meta_app_secret" in values:
        app = ctx.db.scalar(select(MetaApp).where(MetaApp.workspace_id == ctx.workspace.id))
        if app is None:
            app = MetaApp(workspace_id=ctx.workspace.id, verify_token=pysecrets.token_urlsafe(24))
            ctx.db.add(app)
        if "meta_app_id" in values:
            app.app_id = (values["meta_app_id"] or "").strip() or None
        if values.get("meta_app_secret") is not None:
            app.app_secret = values["meta_app_secret"].strip() or None
        if not app.verify_token:
            app.verify_token = pysecrets.token_urlsafe(24)
        ctx.db.flush()
    return _settings_out(ctx)


@router.post("/settings/rotate-verify-token", response_model=InboxSettingsOut)
def rotate_verify_token(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    app = ctx.db.scalar(select(MetaApp).where(MetaApp.workspace_id == ctx.workspace.id))
    if app is None:
        app = MetaApp(workspace_id=ctx.workspace.id)
        ctx.db.add(app)
    app.verify_token = pysecrets.token_urlsafe(24)
    ctx.db.flush()
    return _settings_out(ctx)


# ------------------------------------------------------------------ meta (screen data)
def _has_provider(ctx: Ctx) -> bool:
    try:
        from app.modules.ai import service as ai
        return bool(ai.has_provider(ctx.db, ctx.workspace.id, "text"))
    except NotImplementedError:
        return False


@router.get("/meta", response_model=InboxMeta)
def inbox_meta(ctx: Ctx = Depends(workspace_ctx())):
    accounts = _accounts(ctx)
    counts = _open_counts(ctx)
    members = ctx.db.scalars(select(User).join(Membership, Membership.user_id == User.id).where(
        Membership.workspace_id == ctx.workspace.id, Membership.role != Role.viewer, User.is_active.is_(True))
        .order_by(User.name)).all()
    return InboxMeta(
        accounts=[_account_out(ctx, a, counts) for a in accounts],
        platforms=[p for p in INBOX_PLATFORMS if any(a.platform == p for a in accounts)],
        members=[_user_ref(u) for u in members],
        tags=[TagOut.model_validate(t) for t in list_tags(ctx)],
        canned=[CannedOut.model_validate(c) for c in ctx.db.scalars(select(CannedReply).where(
            CannedReply.workspace_id == ctx.workspace.id, CannedReply.active.is_(True))
            .order_by(CannedReply.sequence, CannedReply.name))],
        has_provider=_has_provider(ctx), user_id=ctx.user.id, can_reply=ctx.can(Role.editor),
        can_manage=ctx.can(Role.admin),
    )


# ------------------------------------------------------------------ statistics
def inbox_stats(db, workspace_id: int, days: int = 30) -> InboxStats:
    """Numbers for the dashboard: workload, speed, assistant share, mood, networks."""
    days = max(1, min(int(days or 30), 365))
    since = utcnow() - timedelta(days=days)
    convs = list(db.scalars(select(Conversation).where(Conversation.workspace_id == workspace_id,
                                                       Conversation.last_message_at >= since)))
    ids = [c.id for c in convs]
    counts = {state: sum(1 for c in convs if c.state == state) for state in ("open", "pending", "done")}
    delays = [(c.first_response_at - c.first_inbound_at).total_seconds() / 60.0 for c in convs
              if c.first_inbound_at and c.first_response_at and c.first_inbound_at >= since]
    sent = db.execute(select(Message.is_bot, func.count()).where(
        Message.conversation_id.in_(ids), Message.direction == "out", Message.state == "sent",
        Message.sent_at >= since).group_by(Message.is_bot)).all() if ids else []
    sent_by = dict(sent)
    replies = sum(sent_by.values())
    bot_replies = sent_by.get(True, 0)
    received = db.scalar(select(func.count()).select_from(Message).where(
        Message.conversation_id.in_(ids), Message.direction == "in", Message.sent_at >= since)) if ids else 0
    platforms: dict[str, dict] = {}
    for conv in convs:
        row = platforms.setdefault(conv.platform, {"platform": conv.platform, "conversations": 0, "dm": 0,
                                                   "comment": 0, "pending": 0})
        row["conversations"] += 1
        row[conv.kind] += 1
        row["pending"] += conv.state == "pending"
    return InboxStats(
        days=days, conversations=len(convs), unread=sum(1 for c in convs if c.unread), received=received or 0,
        replies=replies, bot_replies=bot_replies, bot_share=round(100.0 * bot_replies / replies, 1) if replies else 0.0,
        avg_first_response_minutes=round(sum(delays) / len(delays), 1) if delays else 0.0,
        sentiment={k: sum(1 for c in convs if c.sentiment == k) for k in SENTIMENTS},
        intents={k: sum(1 for c in convs if c.intent == k) for k in INTENTS},
        by_platform=[PlatformStat(**r) for r in sorted(platforms.values(), key=lambda r: -r["conversations"])],
        **counts,
    )


@router.get("/stats", response_model=InboxStats)
def stats(days: int = Query(30, ge=1, le=365), ctx: Ctx = Depends(workspace_ctx())):
    return inbox_stats(ctx.db, ctx.workspace.id, days)
