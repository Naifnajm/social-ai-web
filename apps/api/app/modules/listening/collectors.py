"""Radar sources. Each collector returns plain dicts; ``service.collect`` matches them against the query, stores
new ones and keeps each collector's cursor in ``ListeningQuery.cursors``.

Item keys: source, external_id, text, published_at (aware datetime), url, author_name, author_handle,
author_followers, reach, engagement, lang, country, platform, account_id, extra, and ``owned`` (True when the
item is on or about the workspace's own account, so it is the brand by definition and is not keyword-matched).

Sources and what they cost:
* owned — public comments the inbox already received (no API call).
* instagram — posts that tag the account, and recent posts of brand #hashtags (Meta allows 30 different
  hashtags per account per 7 days). Uses the connected Instagram account.
* facebook — posts that tag the Page, and Page reviews. Uses the connected Page.
* youtube — video search (100 quota units each; at most every 6 hours per query). Platform key
  ``listening.youtube_api_key`` or a connected YouTube account.
* google_business — reviews of each connected location.
* news — Google News RSS search (free, no key).
* x — recent search, pay-per-use on X's side (platform key ``listening.x_bearer_token`` or the workspace's own
  key); every post read counts against the query's monthly cap and is charged from the AI credits (not with an
  own key).

The newer sources (Threads, YouTube comments, web, Reddit, TikTok, Telegram, LinkedIn, app stores) are in
``collectors_ext.py``; ``ALL`` there is the complete table. A collector that cannot run raises
``metering.SourceBlocked`` (needs a key, out of credits, quota used up…), which becomes the source's health.

``reach`` is only set when the network gives a real number (views, impressions); otherwise it stays None and the
author's followers are shown as an estimated potential reach. Nothing is invented.

Written from each network's reference pages; the live APIs need approved apps (Meta App Review for
Instagram Public Content Access, a Google project, an X developer account).
"""
import hashlib
import html
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.http import ApiError, call
from app.modules.social.models import SocialAccount

from . import registry
from . import text as tx
from .metering import SourceBlocked

GRAPH = "https://graph.facebook.com/v24.0"
YOUTUBE = "https://www.googleapis.com/youtube/v3"
BUSINESS = "https://mybusiness.googleapis.com/v4"
NEWS_RSS = "https://news.google.com/rss/search"
X_SEARCH = "https://api.x.com/2/tweets/search/recent"
X_PRICE_PER_POST = 0.005           # USD, X pay-per-use (Nov 2026); shown as an estimate only
IG_HASHTAGS_PER_WEEK = 30
YOUTUBE_EVERY = timedelta(hours=6)
X_EVERY = timedelta(minutes=30)
STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


def _date(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return utcnow()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        try:
            return parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            return utcnow()


def _accounts(db: Session, workspace_id: int, platform: str) -> list[SocialAccount]:
    return list(db.scalars(select(SocialAccount).where(
        SocialAccount.workspace_id == workspace_id, SocialAccount.platform == platform,
        SocialAccount.active.is_(True), SocialAccount.state == "connected")))


def _token(db: Session, account: SocialAccount) -> str:
    from app.modules.social.accounts import valid_token
    return valid_token(db, account)


def _call(query, operation: str, url: str, **kwargs):
    return call("GET", url, service="listening", operation=f"Radar: {operation}", workspace_id=query.workspace_id,
                ref=("listening_query", query.id), **kwargs)


def _platform_secret(db: Session, key: str) -> str | None:
    from app.modules.billing import platform
    return platform.get_secret(db, key)


# ------------------------------------------------------------------------------------------------ owned
def collect_owned(db: Session, query, cursor: dict) -> list[dict]:
    """Public comments on the workspace's own posts that the inbox has stored."""
    from app.modules.inbox.models import Conversation, Message

    since = _date(cursor.get("since")) if cursor.get("since") else utcnow() - timedelta(days=30)
    rows = db.execute(select(Message, Conversation).join(Conversation, Conversation.id == Message.conversation_id)
                      .where(Message.workspace_id == query.workspace_id, Message.direction == "in",
                             Message.channel == "public", Message.sent_at > since)
                      .order_by(Message.sent_at).limit(1000)).all()
    items = []
    for message, conv in rows:
        if not (message.body or "").strip():
            continue
        items.append({
            "source": "owned", "platform": conv.platform, "external_id": f"msg-{message.id}",
            "text": message.body, "published_at": message.sent_at, "url": conv.post_url,
            "author_name": message.author_name or conv.customer_name, "author_handle": conv.customer_handle,
            "account_id": conv.account_id, "owned": True, "conversation_id": conv.id,
        })
        cursor["since"] = message.sent_at.isoformat()
    return items


# -------------------------------------------------------------------------------------------- instagram
def collect_instagram(db: Session, query, cursor: dict) -> list[dict]:
    items: list[dict] = []
    tags = [t.lstrip("#") for t in tx.search_terms(query) if t.startswith("#")]
    week = {tag: at for tag, at in (cursor.get("hashtag_week") or {}).items()
            if _date(at) > utcnow() - timedelta(days=7)}
    ids = cursor.setdefault("hashtag_ids", {})
    for account in _accounts(db, query.workspace_id, "instagram"):
        token = _token(db, account)
        data = _call(query, "Instagram tags", f"{GRAPH}/{account.external_id}/tags", params={
            "fields": "id,caption,permalink,timestamp,username,like_count,comments_count", "limit": 50,
            "access_token": token})
        for media in data.get("data") or []:
            items.append(_ig_item(media, account, owned=True))
        for tag in tags:
            if tag not in week and len(week) >= IG_HASHTAGS_PER_WEEK:
                continue  # Meta's limit: 30 different hashtags per account per 7 days
            if tag not in ids:
                found = _call(query, "Instagram hashtag id", f"{GRAPH}/ig_hashtag_search",
                              params={"user_id": account.external_id, "q": tag, "access_token": token})
                ids[tag] = ((found.get("data") or [{}])[0]).get("id")
            week.setdefault(tag, utcnow().isoformat())
            if not ids[tag]:
                continue
            data = _call(query, "Instagram hashtag posts", f"{GRAPH}/{ids[tag]}/recent_media", params={
                "user_id": account.external_id, "limit": 50, "access_token": token,
                "fields": "id,caption,permalink,timestamp,like_count,comments_count"})
            for media in data.get("data") or []:
                items.append(_ig_item(media, account, owned=False))
        break  # one connected account is enough to search
    cursor["hashtag_week"] = week
    return items


def _ig_item(media: dict, account: SocialAccount, owned: bool) -> dict:
    likes, comments = int(media.get("like_count") or 0), int(media.get("comments_count") or 0)
    return {"source": "instagram", "external_id": str(media.get("id")), "text": media.get("caption") or "",
            "published_at": _date(media.get("timestamp")), "url": media.get("permalink"),
            "author_handle": media.get("username"), "author_name": media.get("username"),
            "engagement": likes + comments, "reach": None, "account_id": account.id,
            "platform": "instagram", "owned": owned}


# --------------------------------------------------------------------------------------------- facebook
def collect_facebook(db: Session, query, cursor: dict) -> list[dict]:
    items: list[dict] = []
    for account in _accounts(db, query.workspace_id, "facebook"):
        token = _token(db, account)
        data = _call(query, "Facebook Page tags", f"{GRAPH}/{account.external_id}/tagged", params={
            "fields": "id,message,permalink_url,created_time,from", "limit": 50, "access_token": token})
        for post in data.get("data") or []:
            author = post.get("from") or {}
            items.append({"source": "facebook", "external_id": str(post.get("id")), "text": post.get("message") or "",
                          "published_at": _date(post.get("created_time")), "url": post.get("permalink_url"),
                          "author_name": author.get("name"), "account_id": account.id, "platform": "facebook",
                          "owned": True})
        try:
            data = _call(query, "Facebook Page reviews", f"{GRAPH}/{account.external_id}/ratings", params={
                "fields": "created_time,recommendation_type,review_text", "limit": 50, "access_token": token})
        except ApiError:
            continue  # reviews need pages_read_user_content; tags still count
        for review in data.get("data") or []:
            body = review.get("review_text") or ""
            key = hashlib.sha1(f"{account.id}{review.get('created_time')}{body}".encode()).hexdigest()[:24]
            hint = {"positive": "positive", "negative": "negative"}.get(review.get("recommendation_type"))
            items.append({"source": "facebook", "external_id": f"review-{key}", "text": body,
                          "published_at": _date(review.get("created_time")), "account_id": account.id,
                          "platform": "facebook", "owned": True, "extra": {"kind": "review", "sentiment": hint}})
    return items


# ---------------------------------------------------------------------------------------------- youtube
def youtube_auth(db: Session, query) -> tuple[dict, dict | None]:
    """(params, headers) for the YouTube Data API: the platform key, else a connected channel's token."""
    key = _platform_secret(db, "listening.youtube_api_key")
    if key:
        return {"key": key}, None
    accounts = _accounts(db, query.workspace_id, "youtube")
    if not accounts:
        raise SourceBlocked("needs_connection", "", {"kind": "connect", "platform": "youtube"})
    return {}, {"Authorization": f"Bearer {_token(db, accounts[0])}"}


def youtube_call(db: Session, query, operation: str, path: str, units: int, params: dict):
    """One YouTube call that counts against the platform's daily quota (10,000 units)."""
    if registry.youtube_units_used(db) + units > registry.YOUTUBE_DAILY_UNITS:
        raise SourceBlocked("quota_exhausted", "")
    auth, headers = youtube_auth(db, query)
    try:
        data = _call(query, operation, f"{YOUTUBE}/{path}", params={**params, **auth}, headers=headers)
    except ApiError as exc:
        if exc.status == 403 and "quota" in str(exc).lower():
            registry.spend_youtube_units(db, 0, exhausted=True)
            raise SourceBlocked("quota_exhausted", "") from None
        raise
    registry.spend_youtube_units(db, units)
    return data


def collect_youtube(db: Session, query, cursor: dict) -> list[dict]:
    if cursor.get("at") and _date(cursor["at"]) > utcnow() - YOUTUBE_EVERY:
        return []
    terms = [t.lstrip("#") for t in tx.search_terms(query)][:6]
    if not terms:
        return []
    params = {"part": "snippet", "type": "video", "order": "date", "maxResults": 25, "q": " | ".join(terms),
              "publishedAfter": (_date(cursor.get("since")) if cursor.get("since")
                                 else utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    data = youtube_call(db, query, "YouTube search", "search", 100, params)
    cursor["at"] = utcnow().isoformat()
    items = []
    found = list(cursor.get("videos") or [])
    for video in data.get("items") or []:
        snippet = video.get("snippet") or {}
        video_id = (video.get("id") or {}).get("videoId")
        if not video_id:
            continue
        items.append({"source": "youtube", "external_id": video_id,
                      "text": f"{snippet.get('title') or ''}\n{snippet.get('description') or ''}".strip(),
                      "published_at": _date(snippet.get("publishedAt")),
                      "url": f"https://www.youtube.com/watch?v={video_id}",
                      "author_name": snippet.get("channelTitle"), "author_handle": snippet.get("channelId")})
        if video_id not in found:
            found.append(video_id)
        cursor["since"] = max(cursor.get("since") or "", snippet.get("publishedAt") or "") or None
    cursor["videos"] = found[-50:]  # the comments source reads these videos too
    return items


# -------------------------------------------------------------------------------------- google business
def collect_google_business(db: Session, query, cursor: dict) -> list[dict]:
    items: list[dict] = []
    for account in _accounts(db, query.workspace_id, "google_business"):
        data = _call(query, "Google reviews", f"{BUSINESS}/{account.external_id}/reviews",
                     params={"pageSize": 50}, headers={"Authorization": f"Bearer {_token(db, account)}"})
        for review in data.get("reviews") or []:
            stars = STARS.get(review.get("starRating") or "", 0)
            items.append({
                "source": "google_business", "external_id": str(review.get("reviewId") or review.get("name")),
                "text": review.get("comment") or "", "published_at": _date(review.get("createTime")),
                "author_name": (review.get("reviewer") or {}).get("displayName"), "account_id": account.id,
                "platform": "google_business", "owned": True,
                "extra": {"kind": "review", "stars": stars,
                          "sentiment": "positive" if stars >= 4 else "negative" if 0 < stars <= 2 else None}})
    return items


# ------------------------------------------------------------------------------------------------- news
GNEWS = "https://gnews.io/api/v4/search"
NEWSAPI = "https://newsapi.org/v2/everything"


def _news_item(key: str, url: str | None, title: str, body: str, published, outlet: str | None, lang: str | None,
               country: str | None = None) -> dict:
    return {"source": "news", "external_id": key, "url": url or None, "lang": lang, "country": country,
            "text": f"{title or ''}\n{body or ''}".strip(), "published_at": _date(published), "author_name": outlet}


def _news_paid(db: Session, query, terms: list[str], langs: list[str], seen: set) -> list[dict] | None:
    """GNews or NewsAPI when the platform has a key (None: no key, use Google News RSS)."""
    search = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
    gnews, newsapi = _platform_secret(db, "listening.gnews_api_key"), _platform_secret(db, "listening.newsapi_key")
    if not gnews and not newsapi:
        return None
    items = []
    for lang in langs:
        if gnews:
            data = _call(query, "News search (GNews)", GNEWS, params={"q": search[:200], "lang": lang, "max": 25,
                                                                     "sortby": "publishedAt", "apikey": gnews})
            rows = [(a.get("url"), a.get("title"), a.get("description") or a.get("content"), a.get("publishedAt"),
                     (a.get("source") or {}).get("name")) for a in data.get("articles") or []]
        else:
            data = _call(query, "News search (NewsAPI)", NEWSAPI, params={"q": search[:500], "language": lang,
                                                                         "sortBy": "publishedAt", "pageSize": 25},
                         headers={"X-Api-Key": newsapi})
            rows = [(a.get("url"), a.get("title"), a.get("description"), a.get("publishedAt"),
                     (a.get("source") or {}).get("name")) for a in data.get("articles") or []]
        for url, title, body, published, outlet in rows:
            key = hashlib.sha1((url or title or "").encode()).hexdigest()[:24]
            if key in seen:
                continue
            seen.add(key)
            items.append(_news_item(key, url, title or "", body or "", published, outlet, lang))
    return items


def collect_news(db: Session, query, cursor: dict) -> list[dict]:
    terms = [t.lstrip("#@") for t in tx.search_terms(query)][:8]
    if not terms:
        return []
    langs = [lang for lang in (query.languages or ["ar"]) if lang in ("ar", "en")] or ["ar"]
    country = (query.countries or ["SA"])[0].upper()
    seen = set(cursor.get("seen") or [])
    paid = _news_paid(db, query, terms, langs, seen) if query.id else None
    if paid is not None:
        cursor["seen"] = list(seen)[-500:]
        return paid
    items = []
    for lang in langs:
        response = _call(query, "News search", NEWS_RSS, expect_json=False, params={
            "q": " OR ".join(f'"{t}"' if " " in t else t for t in terms), "hl": lang, "gl": country,
            "ceid": f"{country}:{lang}"})
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            continue
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or link).strip()
            key = hashlib.sha1(guid.encode()).hexdigest()[:24]
            if key in seen:
                continue
            seen.add(key)
            description = re.sub(r"<[^>]+>", " ", html.unescape(item.findtext("description") or ""))
            source = item.find("source")
            items.append(_news_item(key, link, item.findtext("title") or "", description, item.findtext("pubDate"),
                                    source.text if source is not None else None, lang, country))
    cursor["seen"] = list(seen)[-500:]
    return items


# ---------------------------------------------------------------------------------------------------- x
def x_reads_this_month(cursor: dict) -> int:
    month = utcnow().strftime("%Y-%m")
    return int(cursor.get("reads", 0)) if cursor.get("month") == month else 0


def collect_x(db: Session, query, cursor: dict) -> list[dict]:
    if cursor.get("at") and _date(cursor["at"]) > utcnow() - X_EVERY:
        return []
    bearer, own = registry.key_for(db, query.workspace_id, "x", "listening.x_bearer_token")
    if not bearer:
        raise SourceBlocked("needs_key", "")
    month = utcnow().strftime("%Y-%m")
    reads = x_reads_this_month(cursor)
    left = max(0, int(query.x_monthly_cap or 0) - reads)
    if left < 10:
        cursor["capped"] = True
        return []
    terms = tx.search_terms(query)[:10]
    if not terms:
        return []
    search = "(" + " OR ".join(f'"{t}"' if " " in t else t for t in terms) + ") -is:retweet"
    langs = [lang for lang in query.languages or [] if lang in ("ar", "en")]
    if len(langs) == 1:
        search += f" lang:{langs[0]}"
    from . import metering
    batch = metering.affordable_units(db, query, "x", cursor, max(10, min(100, left)), own=own)
    metering.afford(db, query, "x", cursor, max(batch, 10), own=own)  # X reads at least 10 posts per call
    params = {"query": search[:512], "max_results": batch, "expansions": "author_id",
              "tweet.fields": "created_at,public_metrics,lang,author_id",
              "user.fields": "username,name,public_metrics"}
    if cursor.get("since_id"):
        params["since_id"] = cursor["since_id"]
    data = _call(query, "X search", X_SEARCH, params=params, headers={"Authorization": f"Bearer {bearer}"})
    cursor["at"] = utcnow().isoformat()
    users = {u.get("id"): u for u in ((data.get("includes") or {}).get("users") or [])}
    posts = data.get("data") or []
    cursor.update(month=month, reads=reads + len(posts), capped=False)
    metering.charge(db, query, "x", cursor, len(posts), own=own)
    if (data.get("meta") or {}).get("newest_id"):
        cursor["since_id"] = data["meta"]["newest_id"]
    items = []
    for post in posts:
        user = users.get(post.get("author_id")) or {}
        metrics = post.get("public_metrics") or {}
        followers = int((user.get("public_metrics") or {}).get("followers_count") or 0)
        engagement = sum(int(metrics.get(k) or 0) for k in ("like_count", "reply_count", "retweet_count",
                                                             "quote_count"))
        items.append({"source": "x", "external_id": str(post.get("id")), "text": post.get("text") or "",
                      "published_at": _date(post.get("created_at")), "lang": post.get("lang"),
                      "url": f"https://x.com/{user.get('username') or 'i'}/status/{post.get('id')}",
                      "author_name": user.get("name"), "author_handle": user.get("username"),
                      "author_followers": followers,
                      "reach": int(metrics["impression_count"]) if metrics.get("impression_count") else None,
                      "engagement": engagement})
    return items


COLLECTORS = {
    "owned": collect_owned, "instagram": collect_instagram, "facebook": collect_facebook,
    "youtube": collect_youtube, "google_business": collect_google_business, "news": collect_news, "x": collect_x,
}
