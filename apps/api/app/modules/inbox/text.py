"""Small text and date helpers of the inbox (keyword matching, names, network timestamps)."""
import re
import unicodedata
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta, timezone

_ARABIC_MARKS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")


def normalize_text(text: str | None) -> str:
    """Lower-case, accent-free text for keyword matching (Arabic: no tashkeel, one alef, ya/alef maqsura)."""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = _ARABIC_MARKS.sub("", text)
    text = re.sub("[آأإٱ]", "ا", text)  # آ أ إ ٱ → ا
    text = text.replace("ى", "ي").replace("ة", "ه")  # ى → ي, ة → ه
    text = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def keyword_list(keywords: str | None) -> list[str]:
    return [k for k in (normalize_text(part) for part in re.split(r"[,،\n]", keywords or "")) if k]


def contains_keyword(text: str, keywords: list[str]) -> bool:
    haystack = " %s " % normalize_text(text)
    return any(re.search(r"(?<!\w)%s(?!\w)" % re.escape(k), haystack) for k in keywords)


def first_name(name: str | None) -> str:
    return (name or "").strip().split(" ")[0] if name else ""


def digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value) -> datetime:
    """Network timestamps (epoch s / ms, ISO 8601 with offset) → aware UTC datetime (now when unreadable)."""
    if not value:
        return utcnow().replace(microsecond=0)
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            number = float(value)
            if number > 1e11:
                number /= 1000.0
            return datetime.fromtimestamp(number, tz=timezone.utc).replace(microsecond=0)
        text = str(value).replace("Z", "+00:00")
        text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0)
    except (TypeError, ValueError, OverflowError):
        return utcnow().replace(microsecond=0)


def aware(value: datetime | None) -> datetime | None:
    """Treat naive datetimes read back from the database as UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def picture_expired(url: str | None, margin: timedelta = timedelta(days=1)) -> bool:
    """Meta profile picture URLs are signed and stop working: ``ext`` (lookaside, unix seconds) or ``oe`` (fbcdn,
    hex) holds the expiry. A missing URL counts as expired; a URL without either parameter never expires."""
    if not url:
        return True
    query = parse_qs(urlparse(url).query)
    try:
        if query.get("ext"):
            expires = int(query["ext"][0])
        elif query.get("oe"):
            expires = int(query["oe"][0], 16)
        else:
            return False
    except ValueError:
        return False
    return datetime.fromtimestamp(expires, timezone.utc) - margin <= datetime.now(timezone.utc)
