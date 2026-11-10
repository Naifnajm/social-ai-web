"""Publish from Telegram: send a photo to the bot with ``/post offers Caption…`` (or ``انشر عروض …``).

The inbox feature calls :func:`handle_command` for every *private* Telegram message the bot receives (after
downloading its photo/video as Media). A reply text means "handled — send this back to the sender";
``None`` means "not a publishing command (or the sender is not allowed)": the inbox treats it as a message.

Workspace settings (``templates.telegram.*``, see :class:`schemas.TelegramSettings`):
``publishers`` (user ids / @usernames allowed), ``mode`` (draft | publish | best_time), ``publish_as``,
``default_set_id``, ``account_ids`` (empty: Instagram + Facebook accounts), ``ai_caption``.
"""
import difflib
import logging
import re
import unicodedata
from contextlib import contextmanager
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.core.errors import ApiError, AppError
from app.core.i18n import _, get_locale, set_locale
from app.core.models import Media
from app.modules.brand.models import BrandKit
from app.modules.social.models import SocialAccount
from app.modules.workspaces.models import Workspace
from app.modules.workspaces.settings import get_setting, set_setting

from . import service
from .models import BrandTemplateSet
from .schemas import TelegramSettings

_logger = logging.getLogger(__name__)

PREFIX = "templates.telegram."

# command words → (publish_as, mode override)
VERBS = {
    "post": ("feed", None), "publish": ("feed", None), "انشر": ("feed", None), "نشر": ("feed", None),
    "بوست": ("feed", None), "منشور": ("feed", None),
    "story": ("story", None), "stories": ("story", None), "ستوري": ("story", None), "قصة": ("story", None),
    "قصه": ("story", None), "حالة": ("story", None),
    "both": ("feed_story", None), "all": ("feed_story", None), "الكل": ("feed_story", None),
    "الاثنين": ("feed_story", None),
    "draft": (None, "draft"), "مسودة": (None, "draft"), "مسوده": (None, "draft"),
}
LIST_WORDS = {"templates", "template", "sets", "قوالب", "القوالب", "قالب"}
HELP_WORDS = {"help", "start", "مساعدة", "مساعده"}
AI_WORDS = ("#ai", "+ai", "ai:", "#ذكاء", "+ذكاء", "بالذكاء")
TEXT_LINE_RE = re.compile(r"^\s*(?:text|price|نص|سعر|السعر)\s*[:：]\s*(.+)$", re.IGNORECASE | re.MULTILINE)
BRACKET_RE = re.compile(r"\[([^\[\]]{1,120})\]")
ARABIC_DIACRITICS_RE = re.compile("[ً-ٰٟـ]")
RTL_RE = re.compile("[؀-ۿ]")


# ---------------------------------------------------------------------------- settings
def load_settings(db: Session, workspace_id: int) -> TelegramSettings:
    def value(key, default):
        return get_setting(db, workspace_id, PREFIX + key, default)

    publishers = value("publishers", [])
    if isinstance(publishers, str):
        publishers = [p for p in re.split(r"[,;\s]+", publishers) if p]
    account_ids = value("account_ids", [])
    if isinstance(account_ids, str):
        account_ids = [int(x) for x in re.findall(r"\d+", account_ids)]
    data = {"publishers": [str(p) for p in publishers or []], "mode": value("mode", "draft"),
            "publish_as": value("publish_as", "feed"), "default_set_id": value("default_set_id", None),
            "account_ids": [int(a) for a in account_ids or []], "ai_caption": bool(value("ai_caption", False))}
    try:
        return TelegramSettings(**data)
    except ValueError:
        return TelegramSettings(publishers=data["publishers"], account_ids=data["account_ids"])


def save_settings(db: Session, workspace_id: int, values: TelegramSettings) -> TelegramSettings:
    cleaned = values.model_copy(update={
        "publishers": list(dict.fromkeys(p.strip() for p in values.publishers if p.strip()))})
    for key, value in cleaned.model_dump().items():
        set_setting(db, workspace_id, PREFIX + key, value)
    return cleaned


# ---------------------------------------------------------------------------- text helpers
def norm(text: str | None) -> str:
    """Lower-case, no diacritics/tatweel, unified alef/yeh/teh marbuta — for fuzzy matching."""
    text = unicodedata.normalize("NFKC", text or "").lower().strip()
    text = ARABIC_DIACRITICS_RE.sub("", text)
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"), ("ى", "ي"), ("ة", "ه")):
        text = text.replace(src, dst)
    return re.sub(r"[\s_\-]+", " ", text)


def norm_word(text: str | None) -> str:
    """Like :func:`norm`, also without the Arabic article (العروض → عروض)."""
    return " ".join(w[2:] if w.startswith("ال") and len(w) > 4 else w for w in norm(text).split())


def is_allowed(publishers: list[str], sender: dict | None) -> bool:
    entries = {e.strip().lower().lstrip("@") for e in publishers if e and e.strip()}
    if not entries or not sender:
        return False
    user_id = str(sender.get("id") or "")
    username = (sender.get("username") or "").lower().lstrip("@")
    return bool((user_id and user_id in entries) or (username and username in entries))


def match_choice(choices: list[dict], words: list[str]) -> tuple[dict | None, int]:
    """Fuzzy-match the first word(s) of the command to a template set name → ``(choice, words used)``."""
    if not choices or not words:
        return None, 0
    best, best_score, best_used = None, 0.0, 0
    for used in range(min(4, len(words)), 0, -1):
        candidate = norm_word(" ".join(words[:used]))
        for choice in choices:
            name = norm_word(choice["name"])
            if not name:
                continue
            score = 1.0 if candidate == name else difflib.SequenceMatcher(None, candidate, name).ratio()
            if used == 1 and len(candidate) >= 3 and name.startswith(candidate):
                score = max(score, 0.86)
            if score > best_score:
                best, best_score, best_used = choice, score, used
        if best_score >= 0.999:
            break
    return (best, best_used) if best_score >= 0.78 else (None, 0)


@contextmanager
def _locale(locale: str):
    previous = get_locale()
    set_locale(locale)
    try:
        yield
    finally:
        set_locale(previous)


def _reply_locale(workspace: Workspace | None, message: dict, text: str) -> str:
    if RTL_RE.search(text):
        return "ar"
    code = ((message.get("from") or {}).get("language_code") or "")[:2]
    if code in ("ar", "en"):
        return code
    if re.search(r"[A-Za-z]", text):
        return "en"
    return workspace.locale if workspace else app_settings.default_locale


# ---------------------------------------------------------------------------- entry point
def handle_command(db: Session, account: SocialAccount, message: dict, media_ids: list[int]) -> str | None:
    """Handle a private Telegram message to the bot. Returns the reply text, or ``None`` when the message is
    not a publishing command (or the sender is not allowed) so the inbox treats it normally.

    ``account``: the Telegram bot account that received it (gives the workspace); ``message``: the raw
    Telegram ``message`` dict; ``media_ids``: Media already saved from its photo/video.
    """
    message = message or {}
    text = (message.get("caption") or message.get("text") or "").strip()
    if not text or account is None:
        return None
    workspace_id = account.workspace_id
    config = load_settings(db, workspace_id)
    if not is_allowed(config.publishers, message.get("from") or {}):
        return None
    first, rest = re.match(r"(\S+)\s*(.*)", text, re.DOTALL).groups()  # type: ignore[union-attr]
    verb = first.lstrip("/").split("@", 1)[0].lower()
    verb_norm = norm(verb)
    if verb_norm in {norm(w) for w in LIST_WORDS}:
        kind = "list"
    elif verb_norm in {norm(w) for w in HELP_WORDS}:
        kind = "help"
    else:
        action = VERBS.get(verb) or next((v for k, v in VERBS.items() if norm(k) == verb_norm), None)
        if not action:
            return None
        kind = "publish"
    workspace = db.get(Workspace, workspace_id)
    with _locale(_reply_locale(workspace, message, text)):
        if kind == "list":
            return _list(db, workspace_id)
        if kind == "help":
            return usage()
        media = [m for m in (db.get(Media, mid) for mid in media_ids or [])
                 if m is not None and m.workspace_id == workspace_id and m.kind in ("image", "video")]
        if not media:
            return _("Please attach a photo (or a video) to the command.") + "\n\n" + usage()
        try:
            with db.begin_nested():
                return _publish(db, workspace, config, action, rest, media)
        except (AppError, ApiError) as exc:
            return "⚠️ " + (exc.detail if isinstance(exc, AppError) else exc.message)


def usage() -> str:
    return _("Send a photo with a caption like:\n"
             "/post offers Our new menu is here!\n"
             "/story offers [20% off] Today only\n"
             "انشر عروض نص المنشور…\n\n"
             "Words: post / story / both / draft (or انشر / ستوري / الكل / مسودة). "
             "Put the text for the image (e.g. a price) in [brackets]. Add #ai to let the AI polish the caption.\n"
             "/templates lists the template sets.")


def _list(db: Session, workspace_id: int) -> str:
    choices = service.choices(db, workspace_id)
    if not choices:
        return _("No brand templates yet. Create them in Settings › Brand templates.")
    lines = [_("Template sets:")]
    for choice in choices:
        formats = ", ".join(t["aspect"] for t in choice["templates"])
        lines.append(f"• {choice['name']} ({formats})")
    return "\n".join(lines)


def _post_link(workspace: Workspace, post_id: int) -> str:
    return f"{app_settings.web_url.rstrip('/')}/{get_locale()}/posts/{post_id}"


def _format_when(workspace: Workspace, when) -> str:
    if not when:
        return ""
    try:
        tz = ZoneInfo(workspace.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):  # unknown zone name
        tz = ZoneInfo("UTC")
    return when.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def _accounts(db: Session, workspace_id: int, config: TelegramSettings) -> list[SocialAccount]:
    accounts = []
    for account_id in config.account_ids:
        account = db.get(SocialAccount, account_id)
        if account and account.workspace_id == workspace_id and account.active:
            accounts.append(account)
    if not accounts:
        accounts = list(db.scalars(select(SocialAccount).where(
            SocialAccount.workspace_id == workspace_id, SocialAccount.active.is_(True),
            SocialAccount.platform.in_(service.STORY_PLATFORMS),
            SocialAccount.state.in_(("connected", "draft"))).order_by(SocialAccount.id)))
    return accounts


def polish_caption(db: Session, workspace_id: int, caption: str, user_id: int | None = None) -> str:
    """Let the AI polish the caption (same language, prices and names kept). Falls back to the caption."""
    from app.modules.ai import service as ai

    system = ("You polish social media captions for Instagram and Facebook. Keep the language, the meaning, "
              "prices and names. Make it clear and engaging, add 2-4 relevant hashtags. "
              "Answer with the caption only.")
    kit = db.scalar(select(BrandKit).where(BrandKit.workspace_id == workspace_id, BrandKit.active.is_(True))
                    .order_by(BrandKit.is_default.desc(), BrandKit.id).limit(1))
    if kit is not None:
        system += "\n" + kit.llm_profile()
    try:
        answer = ai.generate_text(db, workspace_id, system, caption, purpose="telegram caption", user_id=user_id)
    except (AppError, ApiError, NotImplementedError) as exc:
        _logger.info("caption not polished: %s", exc)
        return caption
    return (answer or "").strip().strip('"').strip() or caption


def _publish(db: Session, workspace: Workspace, config: TelegramSettings, action: tuple, rest: str,
             media: list[Media]) -> str:
    workspace_id = workspace.id
    publish_as, mode_override = action
    publish_as = publish_as or config.publish_as or "feed"
    mode = mode_override or config.mode or "draft"

    # text on the image: [in brackets] or a "price: …" line
    template_text = None
    found = BRACKET_RE.search(rest)
    if found:
        template_text = found.group(1).strip()
        rest = (rest[:found.start()] + rest[found.end():]).strip()
    found = TEXT_LINE_RE.search(rest)
    if found:
        template_text = found.group(1).strip()
        rest = (rest[:found.start()] + rest[found.end():]).strip()

    # AI polish: a setting, or #ai anywhere in the caption
    use_ai = config.ai_caption
    for word in AI_WORDS:
        pattern = rf"(?<!\S){re.escape(word)}(?!\S)"
        if re.search(pattern, rest, re.IGNORECASE):
            use_ai = True
            rest = re.sub(pattern, "", rest, flags=re.IGNORECASE)
    rest = re.sub(r"[ \t]{2,}", " ", rest).strip()

    # which template set: the first word(s) of the caption, else the default set, else the only one
    all_choices = service.choices(db, workspace_id)
    choice, used = match_choice(all_choices, rest.split()[:4])
    if choice:
        rest = re.sub(r"^\s*(?:\S+\s*){" + str(used) + "}", "", rest)
    else:
        default = db.get(BrandTemplateSet, config.default_set_id) if config.default_set_id else None
        if default is not None and default.workspace_id == workspace_id:
            choice = {"key": f"set:{default.id}", "name": default.name}
        elif len(all_choices) == 1:
            choice = all_choices[0]
    if not choice:
        return _("Which template? Start the caption with a template set name.") + "\n\n" + _list(db, workspace_id)
    caption = rest.strip()
    if use_ai and caption:
        caption = polish_caption(db, workspace_id, caption)

    accounts = _accounts(db, workspace_id, config)
    if mode != "draft" and not accounts:
        mode = "draft"
    templates = service.resolve_choice(db, workspace_id, choice["key"])
    posts = service.create_framed_posts(db, workspace_id, None, templates, media, content=caption,
                                        text=template_text, account_ids=[a.id for a in accounts],
                                        publish_as=publish_as, source_ref="telegram")
    links = "\n".join(_post_link(workspace, p.id) for p in posts)
    if mode == "draft":
        service.submit_posts(db, posts, None, "draft")
        return "📝 " + _("Draft saved with “{name}”. Review and publish it here:", name=choice["name"]) + "\n" + links
    if mode == "best_time":
        service.submit_posts(db, posts, None, "best_time")
        when = _format_when(workspace, posts[0].scheduled_at)
        return "🗓 " + _("Scheduled for {when} on {accounts}.", when=when or "—",
                         accounts=", ".join(a.name for a in accounts)) + "\n" + links
    service.submit_posts(db, posts, None, "publish")
    results = []
    for post in posts:
        db.refresh(post)
        if post.state == "to_approve":
            results.append("⏳ " + _("Waiting for approval."))
            continue
        for target in post.targets:
            name = target.account.name if target.account else target.platform
            if target.state == "posted" or target.story_state == "posted":
                results.append("✅ " + name + (f" — {target.external_url}" if target.external_url else ""))
            elif target.state == "failed" or target.story_state == "failed":
                results.append(f"❌ {name}: {target.error or target.story_error or ''}".rstrip(": "))
            else:
                results.append("⏳ " + name)
    return _("Published with “{name}”:", name=choice["name"]) + "\n" + "\n".join(results) + "\n" + links
