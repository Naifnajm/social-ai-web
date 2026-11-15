"""Classify new mentions: sentiment, intent, emotion and topic.

With an AI provider (the workspace's own key, or platform AI credits) mentions are classified in batches by
the cheapest text model the workspace routes to; without one — or past the per-run AI budget — the lexicon in
``text.classify`` is used and the topic comes from a short keyword list. A review's star rating and a person's
correction always win.
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.i18n import _, lazy, set_locale
from app.modules.workspaces.models import Workspace
from app.modules.workspaces.settings import get_setting

from . import text as tx
from .models import EMOTIONS, INTENTS, SENTIMENTS, Mention

_logger = logging.getLogger(__name__)
BATCH = 30
AI_PER_RUN = 120

TOPIC_WORDS = {
    lazy("Orders and delivery"): ("توصيل", "مندوب", "طلبي", "الطلب", "وصل", "تأخر", "تاخر", "delivery", "courier",
                                  "shipping", "my order", "late"),
    lazy("Prices"): ("سعر", "اسعار", "غالي", "رخيص", "بكم", "خصم", "price", "expensive", "cheap"),
    lazy("Quality"): ("طعم", "جوده", "جودة", "لذيذ", "بارد", "طازج", "taste", "quality", "fresh", "cold"),
    lazy("Service"): ("خدمه", "خدمة", "موظف", "الموظفين", "تعامل", "ذوق", "service", "staff", "rude", "friendly"),
    lazy("App and ordering"): ("تطبيق", "التطبيق", "موقع", "يعلق", "الدفع", "app", "website", "checkout", "payment"),
    lazy("Place"): ("فرع", "الفرع", "جلسه", "جلسة", "زحمه", "زحمة", "مواقف", "branch", "place", "parking", "crowded"),
    lazy("Offers"): ("عرض", "العرض", "عروض", "كوبون", "offer", "deal", "coupon", "discount"),
}

SYSTEM = """You classify public social media mentions for the brand "{brand}". For every mention give:
- "sentiment": positive | neutral | negative (towards the brand or company named in the mention),
- "intent": question | purchase (wants to buy, price, availability, booking) | complaint | praise | news | other,
- "emotion": joy | trust | anger | anticipation | sadness | surprise | none,
- "topic": 1-3 words in {language}, what the mention is about (e.g. delivery, prices, taste, staff, app).
Reuse one of these existing topics when it fits: {topics}.
Read Arabic dialects (Gulf, Egyptian, Levantine) and sarcasm carefully: "يا حلو التأخير" is negative.
Answer with ONLY one JSON object: {{"items": [{{"i": 0, "sentiment": "…", "intent": "…", "emotion": "…",
"topic": "…"}}]}} with one item per mention, same "i" as the input."""


def topic_of(text: str) -> str | None:
    norm = tx.normalize(text)
    for label, cues in TOPIC_WORDS.items():
        if any(tx.normalize(c) in norm for c in cues):
            return _(label)
    return None


def apply_lexicon(mention: Mention) -> None:
    result = tx.classify(mention.text)
    mention.sentiment, mention.intent, mention.emotion = result["sentiment"], result["intent"], result["emotion"]
    if mention.source == "news" and mention.intent in ("other", "praise"):
        mention.intent = "news"
    mention.topic = mention.topic or topic_of(mention.text)


def _apply_hints(mention: Mention) -> None:
    hint = (mention.extra or {}).get("sentiment")
    if hint in SENTIMENTS:
        mention.sentiment = hint
        if hint == "negative" and mention.intent in (None, "other", "praise"):
            mention.intent = "complaint"


def existing_topics(db: Session, workspace_id: int, limit: int = 15) -> list[str]:
    rows = db.execute(select(Mention.topic, func.count()).where(Mention.workspace_id == workspace_id,
                                                                Mention.topic.is_not(None))
                      .group_by(Mention.topic).order_by(func.count().desc()).limit(limit)).all()
    return [row[0] for row in rows]


def _ai_batch(db: Session, workspace: Workspace, brand: str, mentions: list[Mention], topics: list[str]) -> bool:
    from app.core.i18n import LANGUAGE_NAMES
    from app.modules.ai import service as ai

    lines = "\n".join(f"[{i}] ({m.source}) {(m.text or '')[:500]}" for i, m in enumerate(mentions))
    system = SYSTEM.format(brand=brand, language=LANGUAGE_NAMES.get(workspace.locale, "Arabic"),
                           topics=", ".join(topics) or "-")
    try:
        data = ai.generate_json(db, workspace.id, system, lines, purpose="Radar: classify mentions",
                                max_tokens=80 * len(mentions) + 200)
    except Exception as exc:  # no provider, spend limit, unreadable answer: the lexicon takes over
        _logger.info("radar AI classification skipped for workspace %s: %s", workspace.id, exc)
        return False
    for item in data.get("items") or []:
        try:
            mention = mentions[int(item.get("i"))]
        except (TypeError, ValueError, IndexError):
            continue
        sentiment = str(item.get("sentiment") or "").lower()
        intent = str(item.get("intent") or "").lower()
        emotion = str(item.get("emotion") or "").lower()
        mention.sentiment = sentiment if sentiment in SENTIMENTS else mention.sentiment
        mention.intent = intent if intent in INTENTS else mention.intent
        mention.emotion = emotion if emotion in EMOTIONS else mention.emotion
        topic = str(item.get("topic") or "").strip()[:60]
        mention.topic = topic or mention.topic
        if topic and topic not in topics:
            topics.append(topic)
    return True


def classify_pending(db: Session, workspace_id: int, *, use_ai: bool | None = None) -> int:
    """Classify the workspace's unanalyzed mentions. Returns how many were classified."""
    workspace = db.get(Workspace, workspace_id)
    pending = list(db.scalars(select(Mention).where(Mention.workspace_id == workspace_id,
                                                    Mention.analyzed.is_(False))
                              .order_by(Mention.published_at.desc()).limit(2000)))
    if not pending or workspace is None:
        return 0
    set_locale(workspace.locale)
    for mention in pending:  # a baseline for every mention, refined by the AI below
        apply_lexicon(mention)
    if use_ai is None:
        from app.modules.ai import service as ai
        use_ai = bool(get_setting(db, workspace_id, "listening.ai_classify", True)) and ai.has_provider(
            db, workspace_id, "text")
    if use_ai:
        topics = existing_topics(db, workspace_id)
        own = [m for m in pending if m.source != "news"][:AI_PER_RUN]
        for start in range(0, len(own), BATCH):
            if not _ai_batch(db, workspace, workspace.name, own[start:start + BATCH], topics):
                break
    for mention in pending:
        _apply_hints(mention)
        mention.analyzed = True
    db.flush()
    return len(pending)
