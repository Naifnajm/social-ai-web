"""Third-party data providers for networks without an official public search (TikTok).

A provider adapter turns a keyword or hashtag search into plain video dicts:

    {"id", "caption", "url", "published_at", "author_name", "author_handle", "followers", "views", "engagement"}

``views`` and ``followers`` are None when the provider does not give them (never invented).

Implemented: **ScrapeCreators** (https://scrapecreators.com): simple REST GET with an ``x-api-key`` header, pay per
request (credits), no monthly minimum; ``/v1/tiktok/search/keyword`` and ``/v1/tiktok/search/hashtag``. The
answers mirror TikTok's own web JSON (``aweme_info`` / ``aweme_list`` with ``statistics`` and ``author``), parsed
defensively here. Unofficial: it collects public TikTok data, which TikTok's terms do not allow, so the source is
marked beta and the risk is shown to the admin. Not verified against the live API (no key in development).

To add another provider, write a class with ``name``, ``search_keyword(term)`` and ``search_hashtag(tag)`` and
return it from ``tiktok_provider``.
"""
from datetime import UTC, datetime

from app.core.db import utcnow

from . import registry

SCRAPECREATORS = "https://api.scrapecreators.com/v1/tiktok"


def _num(value) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def normalize_aweme(aweme: dict) -> dict | None:
    """One TikTok video (aweme) as the radar's video dict."""
    video_id = str(aweme.get("aweme_id") or aweme.get("id") or "")
    if not video_id:
        return None
    author = aweme.get("author") or {}
    stats = aweme.get("statistics") or aweme.get("stats") or {}
    handle = author.get("unique_id") or author.get("uniqueId")
    try:
        published = datetime.fromtimestamp(float(aweme.get("create_time") or aweme.get("createTime")), tz=UTC)
    except (TypeError, ValueError):
        published = utcnow()
    likes = _num(stats.get("digg_count") or stats.get("diggCount")) or 0
    comments = _num(stats.get("comment_count") or stats.get("commentCount")) or 0
    shares = _num(stats.get("share_count") or stats.get("shareCount")) or 0
    return {
        "id": video_id, "caption": aweme.get("desc") or "",
        "url": aweme.get("share_url") or (f"https://www.tiktok.com/@{handle}/video/{video_id}" if handle else None),
        "published_at": published, "author_name": author.get("nickname") or handle, "author_handle": handle,
        "followers": _num(author.get("follower_count") or author.get("followerCount")),
        "views": _num(stats.get("play_count") or stats.get("playCount")),
        "engagement": likes + comments + shares,
    }


def videos_from(data) -> list[dict]:
    """The videos of a provider answer, whichever list shape it uses."""
    if not isinstance(data, dict):
        return []
    rows = []
    for item in data.get("search_item_list") or []:
        rows.append(item.get("aweme_info") or item)
    rows += list(data.get("aweme_list") or [])
    if not rows and isinstance(data.get("data"), list):
        rows = [item.get("aweme_info") or item for item in data["data"]]
    out, seen = [], set()
    for row in rows:
        video = normalize_aweme(row) if isinstance(row, dict) else None
        if video and video["id"] not in seen:  # TikTok may repeat a video in one answer
            seen.add(video["id"])
            out.append(video)
    return out


class ScrapeCreators:
    name = "scrapecreators"

    def __init__(self, key: str, query):
        self.key, self.query = key, query

    def _get(self, path: str, params: dict) -> list[dict]:
        from .collectors import _call
        data = _call(self.query, "TikTok search (ScrapeCreators)", f"{SCRAPECREATORS}/{path}", params=params,
                     headers={"x-api-key": self.key}, timeout=45)
        return videos_from(data)

    def search_keyword(self, term: str) -> list[dict]:
        return self._get("search/keyword", {"query": term, "sort_by": "date_posted", "date_posted": "this-week"})

    def search_hashtag(self, tag: str) -> list[dict]:
        return self._get("search/hashtag", {"hashtag": tag})


def tiktok_provider(db, query):
    key = registry.secret(db, "listening.tiktok_provider_key")
    return ScrapeCreators(key, query) if key else None
