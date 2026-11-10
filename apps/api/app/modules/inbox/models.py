"""Unified inbox: contacts, conversations (DMs and comment threads), messages, tags, canned replies,
assistant knowledge, comment-to-DM triggers and the per-account / per-workspace inbox state.

Per-account assistant settings live in ``SocialAccount.bot_settings`` (JSON, see ``bot_config.py``).
"""
from datetime import datetime

from sqlalchemy import (JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.crypto import EncryptedString
from app.core.db import Base, TimestampMixin, WorkspaceMixin, utcnow

INTENTS = ("question", "order", "complaint", "lead", "praise", "spam", "other")
SENTIMENTS = ("positive", "neutral", "negative")
CONVERSATION_STATES = ("open", "pending", "done")
KINDS = ("dm", "comment")
CHANNELS = ("dm", "public", "private")
MESSAGE_STATES = ("received", "suggested", "sent", "failed")
BOT_STATES = ("none", "pending", "done", "skipped", "error")
INBOX_PLATFORMS = ("facebook", "instagram", "telegram", "whatsapp")


class Contact(WorkspaceMixin, Base):
    """A customer who wrote to the workspace (lightweight CRM contact, re-used across conversations)."""

    __tablename__ = "inbox_contacts"

    name: Mapped[str] = mapped_column(String(200))
    handle: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40), index=True)
    email: Mapped[str | None] = mapped_column(String(254))
    platform: Mapped[str | None] = mapped_column(String(20))
    external_user_id: Mapped[str | None] = mapped_column(String(200), index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1000))
    note: Mapped[str | None] = mapped_column(Text)


class ConversationTag(WorkspaceMixin, Base):
    __tablename__ = "inbox_tags"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    name: Mapped[str] = mapped_column(String(60))
    color: Mapped[int] = mapped_column(Integer, default=0)


conversation_tags = Table(
    "inbox_conversation_tags", Base.metadata,
    Column("conversation_id", ForeignKey("inbox_conversations.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("inbox_tags.id", ondelete="CASCADE"), primary_key=True),
)


class Conversation(WorkspaceMixin, Base):
    __tablename__ = "inbox_conversations"
    __table_args__ = (UniqueConstraint("account_id", "kind", "external_thread_id"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("social_accounts.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="dm", index=True)  # dm | comment
    # DM: the customer / chat id. Comment: the root comment id.
    external_thread_id: Mapped[str] = mapped_column(String(255), index=True)
    post_target_id: Mapped[int | None] = mapped_column(ForeignKey("post_targets.id", ondelete="SET NULL"),
                                                       index=True)
    external_post_id: Mapped[str | None] = mapped_column(String(255))
    post_url: Mapped[str | None] = mapped_column(String(1000))
    post_preview: Mapped[str | None] = mapped_column(String(300))

    customer_name: Mapped[str | None] = mapped_column(String(200))
    customer_handle: Mapped[str | None] = mapped_column(String(200))
    external_user_id: Mapped[str | None] = mapped_column(String(200), index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1000))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("inbox_contacts.id", ondelete="SET NULL"), index=True)

    state: Mapped[str] = mapped_column(String(10), default="open", index=True)  # open | pending | done
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    unread: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    snippet: Mapped[str | None] = mapped_column(String(200))
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # Meta/WhatsApp 24 h window
    first_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sentiment: Mapped[str | None] = mapped_column(String(10))
    intent: Mapped[str | None] = mapped_column(String(12))
    bot_paused: Mapped[bool] = mapped_column(Boolean, default=False)  # a human took over
    handover_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    handover_reason: Mapped[str | None] = mapped_column(String(300))
    bot_error: Mapped[str | None] = mapped_column(String(300))
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)

    account = relationship("SocialAccount")
    contact = relationship("Contact")
    tags = relationship("ConversationTag", secondary=conversation_tags, order_by="ConversationTag.name")
    messages = relationship("Message", back_populates="conversation", order_by="Message.sent_at, Message.id",
                            cascade="all, delete-orphan", passive_deletes=True)

    @property
    def display_name(self) -> str:
        return self.customer_name or self.customer_handle or self.external_user_id or "Customer"


class BotTrigger(WorkspaceMixin, Base):
    """Comment-to-DM campaigns: "Comment PRICE and we send you the details"."""

    __tablename__ = "inbox_triggers"

    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sequence: Mapped[int] = mapped_column(Integer, default=10)
    account_ids: Mapped[list | None] = mapped_column(JSON)  # empty: every Facebook / Instagram account
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))  # only on this post
    keywords: Mapped[str] = mapped_column(String(500))  # comma-separated, e.g. "price, سعر"
    public_reply: Mapped[str | None] = mapped_column(Text)  # {name} = first name
    dm_text: Mapped[str | None] = mapped_column(Text)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)


class Message(WorkspaceMixin, Base):
    __tablename__ = "inbox_messages"
    __table_args__ = (UniqueConstraint("account_id", "external_id"),)

    conversation_id: Mapped[int] = mapped_column(ForeignKey("inbox_conversations.id", ondelete="CASCADE"),
                                                 index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("social_accounts.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(3), default="in")  # in | out
    channel: Mapped[str] = mapped_column(String(10), default="dm")  # dm | public | private
    author_name: Mapped[str | None] = mapped_column(String(200))
    author_external_id: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    media_ids: Mapped[list | None] = mapped_column(JSON)  # attachments (Media ids, source "inbox")
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    reply_to: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    state: Mapped[str] = mapped_column(String(10), default="received", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    bot_state: Mapped[str] = mapped_column(String(10), default="none", index=True)
    ai_confidence: Mapped[int] = mapped_column(Integer, default=0)
    ai_note: Mapped[str | None] = mapped_column(String(300))
    trigger_id: Mapped[int | None] = mapped_column(ForeignKey("inbox_triggers.id", ondelete="SET NULL"))
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)

    conversation = relationship("Conversation", back_populates="messages")
    user = relationship("User")
    trigger = relationship("BotTrigger")


class CannedReply(WorkspaceMixin, Base):
    __tablename__ = "inbox_canned_replies"

    name: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)  # {name} = customer's first name
    shortcut: Mapped[str | None] = mapped_column(String(40))  # "/shortcut" in the composer
    sequence: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class KnowledgeEntry(WorkspaceMixin, Base):
    """Facts the assistant may use (opening hours, delivery, returns…)."""

    __tablename__ = "inbox_knowledge"

    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AccountInboxState(WorkspaceMixin, Base):
    """Inbox plumbing of one social account: webhook secret, Telegram polling offset, last sync."""

    __tablename__ = "inbox_account_states"

    account_id: Mapped[int] = mapped_column(ForeignKey("social_accounts.id", ondelete="CASCADE"), unique=True)
    webhook_secret: Mapped[str | None] = mapped_column(EncryptedString(500))
    telegram_webhook_active: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_offset: Mapped[int] = mapped_column(Integer, default=0)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_error: Mapped[str | None] = mapped_column(String(300))


class MetaApp(TimestampMixin, Base):
    """A workspace's own Meta app (optional; the platform app from the environment is used otherwise)."""

    __tablename__ = "inbox_meta_apps"

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True)
    app_id: Mapped[str | None] = mapped_column(String(64))
    app_secret: Mapped[str | None] = mapped_column(EncryptedString(500))
    verify_token: Mapped[str | None] = mapped_column(String(80), unique=True)
