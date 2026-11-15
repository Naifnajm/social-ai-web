"""Text helpers for the radar: Arabic-aware normalization, query matching, words and phrases, and a small
lexicon classifier used when the workspace has no AI (or the AI answer cannot be read).

The lexicon is deliberately short and conservative: Gulf and Egyptian everyday words plus English. It is a
fallback, not the main classifier; people can correct any mention and the correction is kept.
"""
import re
from collections import Counter

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")  # harakat + tatweel
_ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})
_WORD = re.compile(r"[#@]?[\w\u0621-\u064a\u066e-\u06d3]+(?:['’][\w]+)?", re.UNICODE)  # letters only, no ؟ ، ؛
_URL = re.compile(r"https?://\S+|www\.\S+")
_REPEAT = re.compile(r"(.)\1{2,}")  # "حلوووو" → "حلوو"

STOPWORDS = set(["في", "من", "على", "الى", "إلى", "عن", "مع", "هذا", "هذه", "ذلك", "تلك", "هو", "هي", "هم", "انا", "أنا", "انت", "أنت", "نحن", "ما", "ماذا", "لا", "لم", "لن", "ان", "إن", "أن", "كان", "كانت", "يكون", "و", "او", "أو", "ثم", "بل", "قد", "كل", "بعض", "اي", "أي", "الي", "اللي", "الذي", "التي", "الذين", "هنا", "هناك", "عند", "لكن", "لان", "لأن", "حتى", "اذا", "إذا", "كما", "مثل", "بين", "فيه", "فيها", "يا", "وش", "ايش", "شو", "مو", "مب", "كذا", "عشان", "علشان", "بس", "جدا", "جداً", "واجد", "مره", "مرة", "اليوم", "امس", "أمس", "بعد", "قبل", "كمان", "برضو", "يعني", "والله", "ان", "شاء", "الله", "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by", "from", "is", "are", "was", "were", "be", "been", "it", "this", "that", "these", "those", "i", "you", "he", "she", "we", "they", "my", "your", "our", "their", "me", "us", "them", "so", "but", "not", "no", "yes", "just", "very", "really", "too", "also", "there", "here", "what", "when", "where", "how", "why", "who", "which", "will", "would", "can", "could", "should", "do", "does", "did", "have", "has", "had", "im", "it's", "its", "rt", "via", "amp", "الحين", "للحين", "عندهم", "عندكم", "عنده", "عندي", "احد", "أحد", "بدون", "غير", "لهم", "لنا", "له", "لها", "منهم", "فيهم", "معهم", "صار", "صارت", "كله", "كلها", "شي", "شيء", "ايه", "ايوه", "نعم", "مثلا", "حق", "حقهم", "هل", "كم", "متى", "وين", "كيف", "ليش"])

POSITIVE = set(["لذيذ", "لذيذه", "رهيب", "رهيبه", "حلو", "حلوه", "ممتاز", "ممتازه", "افضل", "أفضل", "يجنن", "تجنن", "روعه", "رائع", "رائعه", "جميل", "جميله", "احب", "أحب", "حبيت", "عجبني", "عجبتني", "شكرا", "شكراً", "ذوق", "سريع", "نظيف", "مرتب", "انصح", "أنصح", "يستاهل", "تستاهل", "خرافي", "خرافيه", "فخم", "فخمه", "مبدع", "مبدعين", "تحفه", "بطل", "ابطال", "love", "great", "amazing", "awesome", "best", "delicious", "excellent", "perfect", "recommend", "nice", "good", "fantastic", "thanks", "thank", "fresh", "friendly"])
NEGATIVE = set(["سيء", "سيئ", "سيئه", "سيئة", "تاخر", "تأخر", "متاخر", "متأخر", "تاخير", "تأخير", "غالي", "غاليه", "بارد", "بارده", "زفت", "خايس", "خايسه", "مقرف", "وسخ", "وسخه", "اسوا", "أسوأ", "زحمه", "خربان", "يعلق", "معلق", "فاشل", "فاشله", "ردي", "رديء", "رديئه", "سيئين", "حرامي", "نصب", "ضعيف", "ضعيفه", "خيبه", "محبط", "محبطه", "ندمت", "مستحيل", "كارثه", "مشكله", "مشكلة", "شكوى", "زعلان", "زعلانه", "غلط", "ناقص", "ماوصل", "ماوصلني", "bad", "worst", "terrible", "awful", "late", "slow", "cold", "expensive", "dirty", "rude", "disappointed", "disappointing", "never", "refund", "scam", "broken", "problem", "complaint", "horrible", "poor", "wrong"])
NEGATIVE_PHRASES = ("ما وصل", "ما وصلني", "ما رد", "ما يردون", "ما ردوا", "لا انصح", "لا أنصح", "مو زين", "مب زين",
                    "not good", "not worth", "never again", "waste of")
QUESTION_WORDS = ("?", "؟", "هل ", "وش ", "ايش ", "شو ", "كم ", "متى ", "وين ", "كيف ", "ليش ", "how ", "what ",
                  "when ", "where ", "which ", "is there", "do you", "anyone")
PURCHASE_WORDS = ("سعر", "اسعار", "بكم", "كم سعر", "اطلب", "أطلب", "طلب", "متوفر", "يتوفر", "توصيل", "اشتري", "أشتري",
                  "حجز", "احجز", "منيو", "price", "cost", "order", "buy", "available", "delivery", "book", "menu")
EMOTION_WORDS = {
    "anger": ("زفت", "مقرف", "حرامي", "نصب", "زعلان", "قهر", "angry", "furious", "scam", "worst", "!!"),
    "sadness": ("خيبه", "محبط", "ندمت", "للاسف", "للأسف", "حزين", "sad", "disappointed", "unfortunately"),
    "joy": ("يجنن", "رهيب", "حبيت", "عجبني", "خرافي", "love", "amazing", "awesome", "😍", "❤", "🔥"),
    "trust": ("انصح", "أنصح", "دايم", "دائما", "ثقه", "ثقة", "recommend", "always", "trust", "reliable"),
    "anticipation": ("متى", "قريبا", "قريباً", "انتظر", "ننتظر", "متحمس", "soon", "waiting", "can't wait"),
    "surprise": ("صدمه", "صدمة", "ما توقعت", "مفاجاه", "مفاجأة", "wow", "surprised", "unexpected", "😮"),
}


def normalize(text: str | None) -> str:
    """Lower-case, no diacritics/tatweel, unified alef/ya/ta marbuta, squeezed repeated letters."""
    value = _DIACRITICS.sub("", (text or "")).translate(_ALEF).lower()
    return _REPEAT.sub(r"\1\1", value)


def _term_in(term: str, text_norm: str) -> bool:
    term = normalize(term).strip()
    if not term:
        return False
    if term[0] in "#@" or not re.match(r"[\w؀-ۿ]", term):
        return term in text_norm
    # whole words; Arabic prefixes (و ف ب ل ك ال and their combinations) may stand before the term
    return re.search(r"(?<![\w؀-ۿ])(?:[وف]?لل|[وف]?[بلك]?(?:ال)?)" + re.escape(term) + r"(?![\w])",
                     text_norm) is not None


def matches(text: str, keywords: list[str], required: list[str] | None = None,
            excluded: list[str] | None = None) -> bool:
    norm = normalize(text)
    if not any(_term_in(k, norm) for k in keywords or []):
        return False
    if required and not any(_term_in(k, norm) for k in required):
        return False
    return not any(_term_in(k, norm) for k in excluded or [])


def brand_of(text: str, own: list[str], competitors: list[dict]) -> tuple[bool, str | None]:
    """(matched, brand): brand None = the workspace's own brand, else the competitor's name."""
    norm = normalize(text)
    if any(_term_in(k, norm) for k in own or []):
        return True, None
    for competitor in competitors or []:
        words = list(competitor.get("keywords") or []) or [competitor.get("name") or ""]
        if any(_term_in(k, norm) for k in words):
            return True, (competitor.get("name") or "")[:120]
    return False, None


def search_terms(query) -> list[str]:
    """The words a keyword search sends to a network (own brand first, then competitors)."""
    terms = [k for k in (query.keywords or []) if k.strip()]
    for competitor in query.competitors or []:
        terms += [k for k in (competitor.get("keywords") or [competitor.get("name")]) if k and k.strip()]
    return list(dict.fromkeys(t.strip() for t in terms))


def detect_lang(text: str) -> str | None:
    arabic = len(re.findall(r"[؀-ۿ]", text or ""))
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    if not arabic and not latin:
        return None
    return "ar" if arabic >= latin else "en"


def words(text: str, exclude: set[str] | None = None) -> list[str]:
    """Content words of ``text`` (no stopwords, links, mentions, numbers or the brand's own words)."""
    out = []
    for raw in _WORD.findall(_URL.sub(" ", text or "")):
        if raw[0] in "#@" or raw.isdigit() or len(raw) < 2:
            continue
        norm = normalize(raw)
        for prefix in ("وال", "بال", "لل", "ال"):
            if norm.startswith(prefix) and len(norm) - len(prefix) >= 3:
                norm = norm[len(prefix):]
                break
        if norm[:1] in "وف" and norm[1:] in _STOP:  # "وللحين", "فيه" style joined stopwords
            continue
        norm = norm.rstrip("؟?،,.!")
        if norm in _STOP or (exclude and norm in exclude) or len(norm) < 2:
            continue
        out.append(norm)
    return out


def hashtags(text: str) -> list[str]:
    return [h.lower() for h in re.findall(r"#[\w؀-ۿ]+", text or "")]


def phrases(text: str, exclude: set[str] | None = None) -> list[str]:
    tokens = words(text, exclude)
    return [f"{a} {b}" for a, b in zip(tokens, tokens[1:]) if a != b]


def display_forms(texts: list[str], exclude: set[str] | None = None) -> dict[str, str]:
    """Most frequent original spelling for each normalized word (so the cloud shows "التوصيل", not "توصيل")."""
    seen: dict[str, Counter] = {}
    for text in texts:
        for raw in _WORD.findall(_URL.sub(" ", text or "")):
            if raw[0] in "#@":
                continue
            norm = words(raw, exclude)
            if norm:
                seen.setdefault(norm[0], Counter())[raw] += 1
    return {key: counter.most_common(1)[0][0] for key, counter in seen.items()}


def classify(text: str) -> dict:
    """Lexicon classification: sentiment, intent, emotion (topic is left to the AI)."""
    norm = normalize(text)
    tokens = set(words(text))
    pos = len(tokens & {normalize(w) for w in POSITIVE})
    neg = len(tokens & {normalize(w) for w in NEGATIVE}) + sum(2 for p in NEGATIVE_PHRASES if normalize(p) in norm)
    sentiment = "negative" if neg > pos else "positive" if pos > neg else "neutral"
    padded = f" {norm} "
    question = any(normalize(q) in padded for q in QUESTION_WORDS)
    purchase = any(_term_in(w, norm) for w in PURCHASE_WORDS)
    if sentiment == "negative":
        intent = "complaint"
    elif purchase and question:
        intent = "purchase"
    elif question:
        intent = "question"
    elif sentiment == "positive":
        intent = "praise"
    else:
        intent = "other"
    emotion = "none"
    for name, cues in EMOTION_WORDS.items():
        if any(normalize(c) in norm for c in cues):
            emotion = name
            break
    if emotion == "none" and sentiment == "negative":
        emotion = "anger" if "!" in (text or "") else "sadness"
    return {"sentiment": sentiment, "intent": intent, "emotion": emotion}


_STOP = {normalize(w) for w in STOPWORDS}
