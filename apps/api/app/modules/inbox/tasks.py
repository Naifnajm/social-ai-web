"""Background work of the inbox: the assistant (one job per conversation) and the polling fallback."""
import logging

from sqlalchemy import select

from app.core.i18n import get_locale, set_locale
from app.core.jobs import periodic, session_scope
from app.modules.workspaces.models import Workspace

from . import bot, history, service, sources, subscription
from .config import inbox_settings
from .models import Conversation, Message

_logger = logging.getLogger(__name__)


def run_bot(conversation_id: int) -> None:
    """Let the assistant handle the new messages of one conversation (row-locked: never two replies)."""
    previous = get_locale()
    try:
        _run_bot(conversation_id)
    finally:
        set_locale(previous)


def _run_bot(conversation_id: int) -> None:
    with session_scope() as db:
        conv = db.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
        if conv is None:
            return
        set_locale(db.scalar(select(Workspace.locale).where(Workspace.id == conv.workspace_id)))
        try:
            with db.begin_nested():
                bot.handle(db, conv)
        except Exception as exc:
            _logger.exception("inbox assistant failed on conversation %s", conversation_id)
            for message in db.scalars(select(Message).where(Message.conversation_id == conversation_id,
                                                            Message.bot_state == "pending")):
                message.bot_state, message.ai_note = "error", str(exc)[:300]


def run_pending(limit: int = 50) -> int:
    """Handle every conversation with messages waiting for the assistant (safety net for lost jobs)."""
    with session_scope() as db:
        ids = bot.pending_conversation_ids(db, limit)
    for conversation_id in ids:
        run_bot(conversation_id)
    return len(ids)


@periodic(seconds=60)
def assistant_safety_net():
    run_pending()


@periodic(seconds=inbox_settings().inbox_poll_seconds)
def poll_inboxes():
    """Read new messages and comments of every account (when webhooks cannot reach the server)."""
    with session_scope() as db:
        result = sources.poll_accounts(db)
        db.commit()
        service.run_scheduled(db)
    if result["errors"]:
        _logger.info("inbox polling: %s", "; ".join(result["errors"])[:1000])


@periodic(seconds=6 * 3600)
def check_page_subscriptions():
    """Meta sends nothing to a page that is not subscribed to the app (it happens silently after a reconnect, a
    permission change or when the page admin changes). Check every page and repair the ones that lost it."""
    with session_scope() as db:
        result = subscription.ensure_all(db)
        db.commit()
    if result["problems"]:
        _logger.warning("inbox: %s of %s Meta accounts are not subscribed to webhooks", result["problems"],
                        result["checked"])


@periodic(seconds=1800)
def sync_meta_scheduled():
    """Posts scheduled in Meta's own tools, so they show here as well (Facebook Pages)."""
    with session_scope() as db:
        result = history.sync_all_scheduled(db)
        db.commit()
    if result["errors"]:
        _logger.info("meta scheduled posts: %s", "; ".join(result["errors"])[:1000])
