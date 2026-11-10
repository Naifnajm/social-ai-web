"""AI assistant of the inbox: understands each new message and drafts, sends or hands over the reply.

Flow per conversation (``handle``): skip what was already answered → comment triggers → moderation → AI
(``ai.service.generate_json``) → auto-send when confident (mode "auto"), otherwise store a suggestion and/or
hand over to a human (state "pending" + notification).
"""
import json
import logging
import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, LimitReached
from app.core.http import ApiError
from app.core.i18n import _
from app.modules.ai import service as ai
from app.modules.brand.models import BrandKit
from app.modules.social.models import PostTarget
from app.modules.workspaces.models import Workspace

from . import service
from .bot_config import bot_config, is_active_now, mode_for, workspace_option
from .messaging import LABELS
from .models import INTENTS, SENTIMENTS, BotTrigger, CannedReply, Conversation, KnowledgeEntry, Message
from .text import aware, contains_keyword, first_name, keyword_list, utcnow

_logger = logging.getLogger(__name__)

BOT_MAX_PER_HOUR = 6  # automatic replies per conversation and hour (loop / abuse safety)
HISTORY = 12  # messages of context
KNOWLEDGE_CHARS = 12000

SYSTEM_PROMPT = """You are the customer-care assistant of {company}, answering {where} on {network}.
Help customers quickly, kindly and correctly, turn interest into sales and protect the brand.

Rules:
- Always answer in the customer's language and script (Arabic → Arabic, Dutch → Dutch, English → English…).
- Use ONLY facts from COMPANY, KNOWLEDGE and APPROVED ANSWERS. Never invent prices, stock, discounts,
  delivery times, opening hours, policies, links or phone numbers. When the answer is not there, say that a
  colleague will follow up, and set "handover" to true.
- {length} Plain text, no markdown, at most one emoji. Address the customer by first name when natural.
- Never ask for passwords or card numbers.
- Complaints, refunds, legal or medical questions, angry customers, or anything you are unsure about: "handover"
  true and a short, warm reply that a colleague will help.
- "confidence" (0-100) = how sure you are that "reply" is correct, complete and safe to send without a human.
- "lead" true when the person shows buying interest (price, availability, quote, booking, order).
{comment_rules}
Answer with ONLY one JSON object (no code fences, no text around it):
{{"intent": "question|order|complaint|lead|praise|spam|other", "sentiment": "positive|neutral|negative",
"reply": "…", "public_reply": "…", "confidence": 0, "handover": false, "handover_reason": "", "hide": false,
"private_reply": false, "lead": false, "handover_message": "…"}}"""

COMMENT_RULES = """- This is a PUBLIC comment under a post. Never share personal data in public.
- If the person needs personal details (order status, personal price, address, complaint), set "private_reply"
  true, write the private message in "reply" and a short public answer in "public_reply".
- "hide" true only for insults, hate, harassment, scams or obvious spam (then "reply" may be empty)."""

UNREADABLE = {"intent": "other", "sentiment": "neutral", "reply": "", "public_reply": "", "confidence": 0,
              "handover": True, "handover_reason": "The assistant's answer could not be read.", "hide": False,
              "private_reply": False, "lead": False, "handover_message": "", "parsed": False}


def _loads(text: str):
    raw = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", (text or "").strip()).strip()
    try:
        return json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except ValueError:
                return None
    return None


def parse_bot_answer(data) -> dict:
    """Normalize the model's answer (a dict, or text holding JSON). Unreadable → hand over to a human."""
    if isinstance(data, str):
        data = _loads(data)
    if not isinstance(data, dict):
        return dict(UNREADABLE)

    def boolean(key):
        value = data.get(key)
        return value.strip().lower() in ("true", "yes", "1") if isinstance(value, str) else bool(value)

    try:
        number = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        number = 0.0
    confidence = int(round(number * 100 if 0 < number < 1 else number))  # some models answer 0.9
    intent = str(data.get("intent") or "other").strip().lower()
    sentiment = str(data.get("sentiment") or "neutral").strip().lower()
    return {
        "intent": intent if intent in INTENTS else "other",
        "sentiment": sentiment if sentiment in SENTIMENTS else "neutral",
        "reply": str(data.get("reply") or "").strip(),
        "public_reply": str(data.get("public_reply") or "").strip(),
        "confidence": max(0, min(confidence, 100)),
        "handover": boolean("handover"),
        "handover_reason": str(data.get("handover_reason") or "").strip(),
        "hide": boolean("hide"),
        "private_reply": boolean("private_reply"),
        "lead": boolean("lead"),
        "handover_message": str(data.get("handover_message") or "").strip(),
        "parsed": True,
    }


# ------------------------------------------------------------------ helpers
def _messages(db: Session, conv: Conversation, *where) -> list[Message]:
    return list(db.scalars(select(Message).where(Message.conversation_id == conv.id, *where)
                           .order_by(Message.sent_at, Message.id)))


def _last_sent_out(db: Session, conv: Conversation) -> Message | None:
    return db.scalar(select(Message).where(Message.conversation_id == conv.id, Message.direction == "out",
                                           Message.state == "sent").order_by(Message.id.desc()).limit(1))


def _answered(message: Message, last_out: Message | None) -> bool:
    """True when a reply was stored after ``message`` (by us, a colleague or the network echo). Ids, not dates:
    network timestamps are rounded to the second, and polling stores threads oldest first."""
    return bool(last_out) and last_out.id > message.id


def recent_bot_count(db: Session, conv: Conversation) -> int:
    since = utcnow() - timedelta(hours=1)
    return db.scalar(select(func.count()).select_from(Message).where(
        Message.conversation_id == conv.id, Message.is_bot.is_(True), Message.direction == "out",
        Message.state == "sent", Message.sent_at >= since)) or 0


def pending_conversation_ids(db: Session, limit: int = 50) -> list[int]:
    rows = db.execute(select(Message.conversation_id, func.min(Message.sent_at)).where(Message.bot_state == "pending")
                      .group_by(Message.conversation_id).order_by(func.min(Message.sent_at)).limit(limit)).all()
    return [row[0] for row in rows]


# ------------------------------------------------------------------ main flow
def handle(db: Session, conv: Conversation) -> None:
    """Look at the new messages of one conversation (the caller holds a row lock on ``conv``)."""
    pending = _messages(db, conv, Message.bot_state == "pending")
    if not pending:
        return
    last_out = _last_sent_out(db, conv)
    answered = [m for m in pending if _answered(m, last_out)]
    if answered:
        service.mark_bot_state(db, answered, "skipped", "Already answered.")
        pending = [m for m in pending if m not in answered]
    if not pending:
        return

    def finish(state, note=None):
        service.mark_bot_state(db, pending, state, note)

    account = conv.account
    config = bot_config(account)
    latest = pending[-1]
    mode = mode_for(account, conv.kind)
    if utcnow() - aware(latest.sent_at) > service.BOT_MAX_AGE:
        return finish("skipped", "Too old to answer automatically.")
    if not account.inbox_enabled or not account.active:
        return finish("skipped", "Inbox disabled for this account.")
    if conv.kind == "comment" and not conv.bot_paused and run_triggers(db, conv, pending):
        return finish("done", "Comment trigger")
    moderate = conv.kind == "comment" and config["hide_offensive"]
    if not moderate and (mode == "off" or conv.bot_paused):
        return finish("skipped", "A human took over." if conv.bot_paused else "Assistant off.")
    try:
        answer = ask(db, conv, pending)
    except (ApiError, AppError) as exc:
        message = getattr(exc, "message", None) or getattr(exc, "detail", None) or str(exc)
        conv.bot_error = message[:300]
        return finish("error", message)
    conv.bot_error = None
    apply_answer(db, conv, answer, pending, mode)


def apply_answer(db: Session, conv: Conversation, answer: dict, pending: list[Message], mode: str) -> None:
    account = conv.account
    config = bot_config(account)
    conv.intent, conv.sentiment = answer["intent"], answer["sentiment"]
    for message in pending:
        message.ai_confidence = answer["confidence"]

    def finish(state, note=None):
        service.mark_bot_state(db, pending, state, note)

    # moderation first
    if conv.kind == "comment" and config["hide_offensive"] and answer["hide"]:
        try:
            service.hide_comment(db, conv, True)
        except ApiError as exc:
            return finish("error", exc.message)
        conv.state = "done"
        conv.intent = "spam" if answer["intent"] in ("other", "praise") else answer["intent"]
        return finish("done", "Hidden (offensive or spam).")
    if mode == "off" or conv.bot_paused:
        return finish("done", "Moderation only.")

    reply = answer["reply"]
    channel = "dm"
    if conv.kind == "comment":
        channel = "private" if answer["private_reply"] and config["private_reply"] else "public"
    confident = bool(reply) and not answer["handover"] and answer["confidence"] >= config["confidence"]
    rate_ok = recent_bot_count(db, conv) < BOT_MAX_PER_HOUR
    tz_name = db.scalar(select(Workspace.timezone).where(Workspace.id == conv.workspace_id))
    auto = mode == "auto" and is_active_now(account, tz_name)

    if auto and confident and rate_ok:
        error = None
        try:
            sent = service.send_reply(db, conv, reply, channel, is_bot=True, confidence=answer["confidence"])
        except AppError as exc:  # e.g. outside the 24 h window
            sent, error = None, exc.detail
        else:
            error = sent.error
        if sent and sent.state == "sent":
            if channel == "private":
                ack = (answer["public_reply"] or workspace_option(db, conv.workspace_id, "private_ack")
                       or _("We've sent you a private message 📩"))
                service.send_reply(db, conv, ack, "public", is_bot=True)
            return finish("done", "Answered automatically.")
        service.store_suggestion(db, conv, reply, channel, answer["confidence"], error)
        service.set_pending(db, conv, error)
        return finish("error", error)

    if reply:
        service.store_suggestion(db, conv, reply, channel, answer["confidence"], answer["handover_reason"])
    if answer["handover"] or not rate_ok or (mode == "auto" and not confident):
        reason = answer["handover_reason"] or (
            _("Too many automatic replies in one hour.") if not rate_ok else
            _("The assistant is not sure enough ({confidence}%).", confidence=answer["confidence"]))
        service.set_pending(db, conv, reason)
        if mode == "auto" and conv.kind == "dm" and not conv.handover_sent:
            send_handover(db, conv, answer)
    return finish("done", "Suggestion ready." if reply else "Handed over.")


def send_handover(db: Session, conv: Conversation, answer: dict) -> None:
    text = workspace_option(db, conv.workspace_id, "handover_message")
    if not (text or "").strip():
        return
    text = answer.get("handover_message") or text
    try:
        message = service.send_reply(db, conv, text, "dm", is_bot=True)
    except AppError:
        return
    if message.state == "sent":
        conv.handover_sent = True


def trigger_matches(db: Session, trigger: BotTrigger, conv: Conversation, text: str) -> bool:
    if trigger.account_ids and conv.account_id not in [int(a) for a in trigger.account_ids]:
        return False
    if trigger.post_id:
        target = db.get(PostTarget, conv.post_target_id) if conv.post_target_id else None
        if not target or target.post_id != trigger.post_id:
            return False
    return contains_keyword(text, keyword_list(trigger.keywords))


def run_triggers(db: Session, conv: Conversation, pending: list[Message]) -> bool:
    """Comment-to-DM campaigns: keyword in the comment → public reply and/or private message."""
    text = " ".join(m.body or "" for m in pending)
    if not text.strip() or conv.platform not in ("facebook", "instagram"):
        return False
    triggers = db.scalars(select(BotTrigger).where(BotTrigger.workspace_id == conv.workspace_id,
                                                   BotTrigger.active.is_(True))
                          .order_by(BotTrigger.sequence, BotTrigger.id)).all()
    for trigger in triggers:
        if not trigger_matches(db, trigger, conv, text):
            continue
        already = db.scalar(select(func.count()).select_from(Message).join(
            Conversation, Conversation.id == Message.conversation_id).where(
            Message.trigger_id == trigger.id, Message.state == "sent",
            Conversation.account_id == conv.account_id,
            Conversation.external_user_id == (conv.external_user_id or "-")))
        if already:
            return True  # one campaign answer per person is enough
        name = first_name(conv.customer_name or conv.customer_handle)
        if (trigger.dm_text or "").strip():
            service.send_reply(db, conv, trigger.dm_text.replace("{name}", name), "private", is_bot=True,
                               trigger=trigger)
        if (trigger.public_reply or "").strip():
            service.send_reply(db, conv, trigger.public_reply.replace("{name}", name), "public", is_bot=True,
                               trigger=trigger)
        trigger.hit_count = (trigger.hit_count or 0) + 1
        conv.intent = conv.intent or "lead"
        return True
    return False


# ------------------------------------------------------------------ AI call
def ask(db: Session, conv: Conversation, pending: list[Message] | None = None, user_id: int | None = None) -> dict:
    system, prompt = build_prompts(db, conv, pending)
    try:
        data = ai.generate_json(db, conv.workspace_id, system=system, user=prompt,
                                purpose=f"inbox reply · {conv.display_name}"[:150], user_id=user_id)
    except (ApiError, LimitReached):
        raise
    except AppError as exc:
        if exc.code in ("no_ai_provider", "ai_budget", "limit_reached", "forbidden"):
            raise
        _logger.info("inbox assistant: unreadable answer (%s)", exc.detail)
        return dict(UNREADABLE)
    return parse_bot_answer(data)


def render_canned(reply: CannedReply, conv: Conversation | None = None) -> str:
    name = first_name(conv.customer_name) if conv else ""
    return (reply.body or "").replace("{name}", name).replace("  ", " ").strip()


def _brand_kit(db: Session, conv: Conversation) -> BrandKit | None:
    kit_id = bot_config(conv.account).get("brand_kit_id")
    query = select(BrandKit).where(BrandKit.workspace_id == conv.workspace_id, BrandKit.active.is_(True))
    if kit_id:
        kit = db.scalar(query.where(BrandKit.id == int(kit_id)))
        if kit:
            return kit
    return db.scalar(query.order_by(BrandKit.is_default.desc(), BrandKit.id).limit(1))


def _line(message: Message) -> str:
    who = "Us" if message.direction == "out" else (message.author_name or "Customer")
    body = (message.body or "").strip()
    if message.media_ids:
        body += " [%d attachment(s)]" % len(message.media_ids)
    return "[%s] %s: %s" % (aware(message.sent_at).strftime("%Y-%m-%d %H:%M"), who, body or "(empty)")


def build_prompts(db: Session, conv: Conversation, pending: list[Message] | None = None) -> tuple[str, str]:
    account = conv.account
    config = bot_config(account)
    workspace = db.get(Workspace, conv.workspace_id)
    is_comment = conv.kind == "comment"
    system = SYSTEM_PROMPT.format(
        company=workspace.name,
        where="public comments under your posts" if is_comment else "private messages",
        network=LABELS.get(conv.platform, conv.platform),
        length=("Public replies: one or two short sentences." if is_comment
                else "Keep it short: one to four sentences."),
        comment_rules=COMMENT_RULES if is_comment else "",
    )
    kit = _brand_kit(db, conv)
    if kit:
        system += "\n\nBRAND\n" + kit.llm_profile()
    if (config.get("instructions") or "").strip():
        system += "\n\nINSTRUCTIONS FOR THIS ACCOUNT\n" + config["instructions"].strip()

    info = [f"Name: {workspace.name}"]
    company_info = (workspace_option(db, conv.workspace_id, "company_info") or "").strip()
    if company_info:
        info.append(company_info)
    parts = ["COMPANY\n" + "\n".join(info)]
    knowledge = db.scalars(select(KnowledgeEntry).where(KnowledgeEntry.workspace_id == conv.workspace_id,
                                                        KnowledgeEntry.active.is_(True))
                           .order_by(KnowledgeEntry.sequence, KnowledgeEntry.id)).all()
    if knowledge:
        chunks, size = [], 0
        for entry in knowledge:
            chunk = "## %s\n%s" % (entry.title, (entry.content or "").strip())
            if size + len(chunk) > KNOWLEDGE_CHARS:
                break
            chunks.append(chunk)
            size += len(chunk)
        parts.append("KNOWLEDGE\n" + "\n\n".join(chunks))
    canned = db.scalars(select(CannedReply).where(CannedReply.workspace_id == conv.workspace_id,
                                                  CannedReply.active.is_(True))
                        .order_by(CannedReply.sequence, CannedReply.id).limit(30)).all()
    if canned:
        parts.append("APPROVED ANSWERS (reuse when they fit)\n" + "\n".join(
            "- %s: %s" % (c.name, render_canned(c, conv)) for c in canned))
    handover = (workspace_option(db, conv.workspace_id, "handover_message") or "").strip()
    if handover:
        parts.append("HANDOVER MESSAGE (put it in \"handover_message\", translated into the customer's "
                     "language)\n" + handover)
    if is_comment and conv.post_preview:
        parts.append("POST (the comments are under this post)\n" + conv.post_preview[:1500])
    if not pending:
        pending = _messages(db, conv, Message.direction == "in")[-1:]
    pending_ids = {m.id for m in pending}
    history = [m for m in _messages(db, conv, Message.state != "suggested") if m.id not in pending_ids][-HISTORY:]
    if history:
        parts.append("CONVERSATION SO FAR (oldest first)\n" + "\n".join(_line(m) for m in history))
    parts.append("CUSTOMER: %s\nNEW MESSAGE%s TO ANSWER\n%s" % (
        conv.display_name, "S" if len(pending) > 1 else "", "\n".join(_line(m) for m in pending)))
    return system, "\n\n".join(parts)


def suggest_now(db: Session, conv: Conversation, user_id: int | None = None) -> Message:
    """"Write with AI": a fresh draft whatever the assistant mode."""
    inbound = _messages(db, conv, Message.direction == "in")
    last_out = _last_sent_out(db, conv)
    recent = [m for m in inbound if not _answered(m, last_out)] or inbound[-1:]
    try:
        answer = ask(db, conv, recent[-5:], user_id=user_id)
    except ApiError as exc:
        raise AppError(exc.message, code="ai_error") from exc
    conv.intent, conv.sentiment = answer["intent"], answer["sentiment"]
    channel = "dm"
    if conv.kind == "comment":
        channel = "private" if answer["private_reply"] and bot_config(conv.account)["private_reply"] else "public"
    if not answer["reply"]:
        raise AppError(answer["handover_reason"] if answer.get("parsed") and answer["handover_reason"]
                       else _("The assistant has no answer for this one."), code="no_answer")
    return service.store_suggestion(db, conv, answer["reply"], channel, answer["confidence"],
                                    answer["handover_reason"])
