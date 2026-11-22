"""The newer radar sources, with the same contract as ``collectors.py`` (``collect_<source>(db, query, cursor)``
returns item dicts; the cursor is kept per source; ``SourceBlocked`` explains why a source cannot run).

* threads          — keyword search of public posts (``GET /keyword_search``, needs Meta's threads_keyword_search
                     permission; free) with a connected Threads account, plus replies to the account's recent posts.
* youtube_comments — commentThreads (1 unit per page) for the connected channel's latest videos and the videos
                     the YouTube search found; at most ``listening.youtube_units_per_run`` units per run.
* web              — Brave Search API, web + news endpoints (paid per query; platform or the workspace's key).
* reddit           — official API with client credentials (paid per call; needs a commercial agreement).
* tiktok           — a third-party data provider (``providers.py``; ScrapeCreators, beta).
* telegram         — recent posts of the public channels listed in the setup (t.me/s/<channel> preview pages).
* linkedin         — comments on the connected organization page's recent posts (Community Management API).
* app_store        — Apple's public customer-reviews feed (JSON) for the app ids listed in the setup.
* google_play      — needs a Play Console service account (not connected yet): always blocked with an explanation.

Written from each provider's reference pages and NOT verified against the live APIs (no keys in development).
"""
import hashlib
import re
from datetime import UTC, datetime, timedelta
from html import unescape
from html.parser import HTMLParser

from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.http import ApiError

from . import collectors as base
from . import metering, registry
from . import text as tx
from .metering import SourceBlocked

THREADS = "https://graph.threads.net/v1.0"
BRAVE = "https://api.search.brave.com/res/v1"
REDDIT_TOKEN = "https://www.reddit.com/api/v1/access_token"
REDDIT = "https://oauth.reddit.com"
LINKEDIN = "https://api.linkedin.com/rest"
APPLE_REVIEWS = "https://itunes.apple.com/{country}/rss/customerreviews/page=1/id={app}/sortby=mostrecent/json"
TELEGRAM = "https://t.me/s/{channel}"
USER_AGENT = "StravicaRadar/1.0 (social listening)"

THREADS_EVERY = timedelta(minutes=30)
COMMENTS_EVERY = timedelta(hours=3)
WEB_EVERY = timedelta(hours=6)
REDDIT_EVERY = timedelta(hours=2)
TIKTOK_EVERY = timedelta(hours=6)
TELEGRAM_EVERY = timedelta(hours=1)
LINKEDIN_EVERY = timedelta(hours=3)
APPS_EVERY = timedelta(hours=6)
MAX_CHANNELS = 10
MAX_APPS = 5
TIKTOK_REQUESTS_PER_RUN = 4


def _due(cursor: dict, every: timedelta) -> bool:
    return not cursor.get("at") or base._date(cursor["at"]) <= utcnow() - every


def _stamp(cursor: dict) -> None:
    cursor["at"] = utcnow().isoformat()


def _or(terms: list[str], quote: str = '"') -> str:
    return " OR ".join(f"{quote}{t}{quote}" if " " in t else t for t in terms)


def _unix(value) -> datetime:
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return utcnow()


def _int(value) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------------------------- threads
def collect_threads(db: Session, query, cursor: dict) -> list[dict]:
    if not _due(cursor, THREADS_EVERY):
        return []
    accounts = base._accounts(db, query.workspace_id, "threads")
    if not accounts:
        raise SourceBlocked("needs_connection", "", {"kind": "connect", "platform": "threads"})
    account = accounts[0]
    token = base._token(db, account)
    items: list[dict] = []
    fields = "id,text,media_type,permalink,timestamp,username"
    since = int(base._date(cursor["since"]).timestamp()) if cursor.get("since") else None
    newest = cursor.get("since")
    blocked = None
    for term in [t.lstrip("#") for t in tx.search_terms(query)][:5]:
        params = {"q": term, "search_type": "RECENT", "fields": fields, "limit": 50, "access_token": token}
        if since:
            params["since"] = since
        try:
            data = base._call(query, "Threads keyword search", f"{THREADS}/keyword_search", params=params)
        except ApiError as exc:
            if exc.status in (400, 403) and ("permission" in str(exc).lower() or exc.status == 403):
                blocked = SourceBlocked("needs_permission", "")
                break
            raise
        for post in data.get("data") or []:
            items.append(_threads_item(post, account, owned=False))
            newest = max(newest or "", post.get("timestamp") or "") or None
    # replies to the account's own recent posts (threads_read_replies)
    try:
        own = base._call(query, "Threads own posts", f"{THREADS}/me/threads",
                         params={"fields": "id,timestamp", "limit": 5, "access_token": token})
        for post in own.get("data") or []:
            replies = base._call(query, "Threads replies", f"{THREADS}/{post.get('id')}/replies",
                                 params={"fields": fields, "access_token": token})
            for reply in replies.get("data") or []:
                items.append(_threads_item(reply, account, owned=True))
    except ApiError:
        pass  # replies need threads_read_replies; keyword results still count
    _stamp(cursor)
    cursor["since"] = newest
    if blocked and not items:
        raise blocked
    if blocked:
        cursor["_health"] = {"status": "needs_permission", "message": "", "at": utcnow().isoformat()}
    return items


def _threads_item(post: dict, account, owned: bool) -> dict:
    return {"source": "threads", "external_id": str(post.get("id")), "text": post.get("text") or "",
            "published_at": base._date(post.get("timestamp")), "url": post.get("permalink"),
            "author_name": post.get("username"), "author_handle": post.get("username"), "platform": "threads",
            "account_id": account.id, "owned": owned, "reach": None}


# ------------------------------------------------------------------------------------- youtube comments
def collect_youtube_comments(db: Session, query, cursor: dict) -> list[dict]:
    if not _due(cursor, COMMENTS_EVERY):
        return []
    budget = registry.youtube_units_per_run(db)
    spent = 0
    own_videos: list[str] = []
    channels = list((query.options or {}).get("youtube_channel_ids") or [])
    channels += [a.external_id for a in base._accounts(db, query.workspace_id, "youtube") if a.external_id]
    for channel in list(dict.fromkeys(channels))[:2]:
        if spent + 2 > budget:
            break
        data = base.youtube_call(db, query, "YouTube channel", "channels", 1, {"part": "contentDetails",
                                                                             "id": channel})
        spent += 1
        uploads = (((data.get("items") or [{}])[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get(
            "uploads")
        if not uploads:
            continue
        videos = base.youtube_call(db, query, "YouTube uploads", "playlistItems", 1, {
            "part": "contentDetails", "playlistId": uploads, "maxResults": 10})
        spent += 1
        own_videos += [(v.get("contentDetails") or {}).get("videoId") for v in videos.get("items") or []]
    own_videos = [v for v in own_videos if v]
    found = list(((query.cursors or {}).get("youtube") or {}).get("videos") or [])
    seen = dict(cursor.get("seen") or {})  # video id -> newest comment time already read
    items: list[dict] = []
    for video, owned in [(v, True) for v in own_videos] + [(v, False) for v in found if v not in own_videos]:
        if spent + 1 > budget:
            break
        try:
            data = base.youtube_call(db, query, "YouTube comments", "commentThreads", 1, {
                "part": "snippet", "videoId": video, "maxResults": 100, "order": "time", "textFormat": "plainText"})
        except ApiError as exc:
            if exc.status in (403, 404):  # comments turned off, or a private video
                spent += 1
                continue
            raise
        spent += 1
        newest = seen.get(video) or ""
        for thread in data.get("items") or []:
            top = ((thread.get("snippet") or {}).get("topLevelComment") or {})
            snippet = top.get("snippet") or {}
            published = snippet.get("publishedAt") or ""
            if published and published <= (seen.get(video) or ""):
                continue
            newest = max(newest, published)
            likes = _int(snippet.get("likeCount")) or 0
            replies = _int((thread.get("snippet") or {}).get("totalReplyCount")) or 0
            items.append({"source": "youtube_comments", "external_id": str(thread.get("id") or top.get("id")),
                          "text": snippet.get("textOriginal") or unescape(snippet.get("textDisplay") or ""),
                          "published_at": base._date(published), "platform": "youtube", "owned": owned,
                          "url": f"https://www.youtube.com/watch?v={video}&lc={top.get('id') or thread.get('id')}",
                          "author_name": snippet.get("authorDisplayName"),
                          "author_handle": (snippet.get("authorChannelId") or {}).get("value"),
                          "engagement": likes + replies, "reach": None, "extra": {"video_id": video}})
        seen[video] = newest
    cursor["seen"] = dict(list(seen.items())[-60:])
    cursor["units_last_run"] = spent
    _stamp(cursor)
    return items


# -------------------------------------------------------------------------------------------------- web
def collect_web(db: Session, query, cursor: dict) -> list[dict]:
    if not _due(cursor, WEB_EVERY):
        return []
    key, own = registry.key_for(db, query.workspace_id, "web", "listening.brave_api_key")
    if not key:
        raise SourceBlocked("needs_key", "")
    terms = [t.lstrip("#@") for t in tx.search_terms(query)][:6]
    if not terms:
        return []
    search = _or(terms)[:400]
    lang = (query.languages or [None])[0]
    country = (query.countries or [None])[0]
    params = {"q": search, "count": 20, "freshness": "pd" if cursor.get("at") else "pw"}
    if lang in ("ar", "en", "fr", "de", "nl"):
        params["search_lang"] = lang
    if country:
        params["country"] = country.upper()
    headers = {"X-Subscription-Token": key, "Accept": "application/json"}
    items: list[dict] = []
    for endpoint, label in (("web/search", "Brave web search"), ("news/search", "Brave news search")):
        metering.afford(db, query, "web", cursor, 1, own=own)
        data = base._call(query, label, f"{BRAVE}/{endpoint}", params=params, headers=headers)
        metering.charge(db, query, "web", cursor, 1, own=own)
        rows = ((data.get("web") or {}).get("results") if endpoint.startswith("web") else data.get("results")) or []
        for row in rows:
            url = row.get("url")
            if not url:
                continue
            domain = (row.get("meta_url") or {}).get("hostname") or re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", url)
            text = re.sub(r"<[^>]+>", "", unescape(f"{row.get('title') or ''}\n{row.get('description') or ''}"))
            items.append({"source": "web", "external_id": hashlib.sha1(url.encode()).hexdigest()[:24], "url": url,
                          "text": text.strip(), "published_at": base._date(row.get("page_age")),
                          "author_name": (row.get("profile") or {}).get("name") or domain,
                          "author_handle": domain, "reach": None,
                          "extra": {"kind": "news" if endpoint.startswith("news") else "web", "domain": domain}})
    _stamp(cursor)
    return items


# ----------------------------------------------------------------------------------------------- reddit
def collect_reddit(db: Session, query, cursor: dict) -> list[dict]:
    if not _due(cursor, REDDIT_EVERY):
        return []
    client_id = registry.secret(db, "listening.reddit_client_id")
    client_secret = registry.secret(db, "listening.reddit_client_secret")
    if not client_id or not client_secret:
        raise SourceBlocked("needs_key", "")
    terms = [t.lstrip("#@") for t in tx.search_terms(query)][:6]
    if not terms:
        return []
    subs = [s.strip().removeprefix("r/") for s in (query.options or {}).get("subreddits") or [] if s.strip()][:3]
    calls = 1 + max(1, len(subs))
    metering.afford(db, query, "reddit", cursor, calls)
    import base64
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    token = base.call("POST", REDDIT_TOKEN, service="listening", operation="Radar: Reddit token",
                      workspace_id=query.workspace_id, ref=("listening_query", query.id),
                      headers={"Authorization": f"Basic {basic}", "User-Agent": USER_AGENT},
                      data={"grant_type": "client_credentials"}).get("access_token")
    headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    items: list[dict] = []
    made = 1
    for sub in subs or [None]:
        path = f"/r/{sub}/search" if sub else "/search"
        params = {"q": _or(terms)[:500], "sort": "new", "limit": 50, "t": "week" if not cursor.get("at") else "day",
                  "type": "link"}
        if sub:
            params["restrict_sr"] = 1
        data = base._call(query, "Reddit search", f"{REDDIT}{path}", params=params, headers=headers)
        made += 1
        for child in (data.get("data") or {}).get("children") or []:
            post = child.get("data") or {}
            items.append({"source": "reddit", "external_id": str(post.get("name") or post.get("id")),
                          "text": f"{post.get('title') or ''}\n{post.get('selftext') or ''}".strip(),
                          "published_at": _unix(post.get("created_utc")),
                          "url": f"https://www.reddit.com{post.get('permalink')}" if post.get("permalink") else None,
                          "author_name": post.get("author"), "author_handle": post.get("author"),
                          "engagement": (_int(post.get("score")) or 0) + (_int(post.get("num_comments")) or 0),
                          "reach": None, "extra": {"subreddit": post.get("subreddit")}})
    metering.charge(db, query, "reddit", cursor, made)
    _stamp(cursor)
    return items


# ----------------------------------------------------------------------------------------------- tiktok
def collect_tiktok(db: Session, query, cursor: dict) -> list[dict]:
    if not _due(cursor, TIKTOK_EVERY):
        return []
    from .providers import tiktok_provider
    provider = tiktok_provider(db, query)
    if provider is None:
        raise SourceBlocked("needs_key", "")
    terms = tx.search_terms(query)
    searches = [("hashtag", t.lstrip("#")) if t.startswith("#") else ("keyword", t.lstrip("@")) for t in terms]
    items: list[dict] = []
    for kind, term in searches[:TIKTOK_REQUESTS_PER_RUN]:
        metering.afford(db, query, "tiktok", cursor, 1)
        videos = provider.search_hashtag(term) if kind == "hashtag" else provider.search_keyword(term)
        metering.charge(db, query, "tiktok", cursor, 1)
        for video in videos:
            items.append({"source": "tiktok", "platform": "tiktok", "external_id": video["id"],
                          "text": video["caption"], "published_at": video["published_at"], "url": video["url"],
                          "author_name": video["author_name"], "author_handle": video["author_handle"],
                          "author_followers": video["followers"] or 0, "reach": video["views"],
                          "engagement": video["engagement"], "extra": {"provider": provider.name}})
    _stamp(cursor)
    return items


# --------------------------------------------------------------------------------------------- telegram
class _TelegramPage(HTMLParser):
    """Reads the public preview page of a channel (t.me/s/<channel>): posts, text, time and views."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.posts: list[dict] = []
        self._post: dict | None = None
        self._depth = 0          # div depth inside the current post
        self._in_text = 0        # div depth inside the text block (0 = outside)
        self._in_views = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "div" and "tgme_widget_message" in classes and attrs.get("data-post"):
            self._post = {"id": attrs["data-post"], "text": [], "time": None, "views": None}
            self.posts.append(self._post)
            self._depth = 1
            return
        if self._post is None:
            return
        if tag == "div":
            self._depth += 1
            if "tgme_widget_message_text" in classes and not self._in_text:
                self._in_text = self._depth
            elif self._in_text:
                pass
        if tag == "br" and self._in_text:
            self._post["text"].append("\n")
        if tag == "time" and attrs.get("datetime") and not self._post["time"]:
            self._post["time"] = attrs["datetime"]
        if tag == "span" and "tgme_widget_message_views" in classes:
            self._in_views = True

    def handle_endtag(self, tag):
        if self._post is None:
            return
        if tag == "span":
            self._in_views = False
        if tag == "div":
            if self._in_text and self._depth == self._in_text:
                self._in_text = 0
            self._depth -= 1
            if self._depth <= 0:
                self._post = None

    def handle_data(self, data):
        if self._post is None:
            return
        if self._in_text:
            self._post["text"].append(data)
        elif self._in_views:
            self._post["views"] = data.strip()


def _views(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"([\d.,]+)\s*([KkMm]?)", value.strip())
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    return int(number * {"k": 1_000, "m": 1_000_000}.get(match.group(2).lower(), 1))


def parse_telegram(html_text: str) -> list[dict]:
    page = _TelegramPage()
    try:
        page.feed(html_text)
    except Exception:  # broken markup: keep what was read
        pass
    return [{"id": p["id"], "text": "".join(p["text"]).strip(), "time": p["time"], "views": _views(p["views"])}
            for p in page.posts]


def collect_telegram(db: Session, query, cursor: dict) -> list[dict]:
    if not _due(cursor, TELEGRAM_EVERY):
        return []
    channels = [re.sub(r"^(https?://)?(t\.me/)?(s/)?@?", "", c.strip()).strip("/")
                for c in (query.options or {}).get("telegram_channels") or [] if c.strip()]
    channels = [c for c in channels if re.fullmatch(r"[A-Za-z0-9_]{4,64}", c)][:MAX_CHANNELS]
    if not channels:
        raise SourceBlocked("needs_setup", "", {"kind": "edit_setup", "field": "telegram_channels"})
    last = dict(cursor.get("last") or {})
    items: list[dict] = []
    for channel in channels:
        response = base._call(query, "Telegram channel", TELEGRAM.format(channel=channel), expect_json=False,
                              headers={"User-Agent": USER_AGENT, "Accept-Language": "ar,en"}, timeout=20)
        posts = parse_telegram(response.text or "")
        newest = int(last.get(channel) or 0)
        for post in posts:
            number = _int(str(post["id"]).rsplit("/", 1)[-1]) or 0
            if number <= int(last.get(channel) or 0) or not post["text"]:
                continue
            newest = max(newest, number)
            items.append({"source": "telegram", "platform": "telegram", "external_id": str(post["id"]),
                          "text": post["text"][:5000], "published_at": base._date(post["time"]),
                          "url": f"https://t.me/{post['id']}", "author_name": channel, "author_handle": channel,
                          "reach": post["views"]})
        last[channel] = newest
    cursor["last"] = last
    _stamp(cursor)
    return items


# --------------------------------------------------------------------------------------------- linkedin
def collect_linkedin(db: Session, query, cursor: dict) -> list[dict]:
    if not _due(cursor, LINKEDIN_EVERY):
        return []
    orgs = [a for a in base._accounts(db, query.workspace_id, "linkedin")
            if (a.external_id or "").startswith("urn:li:organization:")]
    if not orgs:
        raise SourceBlocked("needs_connection", "", {"kind": "connect", "platform": "linkedin"})
    from app.modules.workspaces.settings import get_setting
    version = get_setting(db, query.workspace_id, "social.linkedin_api_version", "202510") or "202510"
    items: list[dict] = []
    seen = set(cursor.get("seen") or [])
    for account in orgs[:2]:
        headers = {"Authorization": f"Bearer {base._token(db, account)}", "LinkedIn-Version": version,
                   "X-Restli-Protocol-Version": "2.0.0"}
        try:
            posts = base._call(query, "LinkedIn posts", f"{LINKEDIN}/posts", headers=headers,
                               params={"author": account.external_id, "q": "author", "count": 10})
        except ApiError as exc:
            if exc.status == 403:
                raise SourceBlocked("needs_permission", "") from None
            raise
        from urllib.parse import quote
        for post in posts.get("elements") or []:
            urn = post.get("id")
            if not urn:
                continue
            data = base._call(query, "LinkedIn comments", f"{LINKEDIN}/socialActions/{quote(urn, safe='')}/comments",
                              headers=headers, params={"count": 50})
            for comment in data.get("elements") or []:
                key = str(comment.get("$URN") or comment.get("commentUrn") or comment.get("id") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                created = (comment.get("created") or {}).get("time")
                items.append({"source": "linkedin", "platform": "linkedin", "external_id": key[:255],
                              "text": ((comment.get("message") or {}).get("text") or "").strip(),
                              "published_at": _unix(created / 1000) if isinstance(created, (int, float))
                              else utcnow(), "url": f"https://www.linkedin.com/feed/update/{urn}",
                              "author_handle": comment.get("actor"), "account_id": account.id, "owned": True,
                              "reach": None})
    cursor["seen"] = list(seen)[-1000:]
    _stamp(cursor)
    return items


# ------------------------------------------------------------------------------------------- app stores
def collect_app_store(db: Session, query, cursor: dict) -> list[dict]:
    if not _due(cursor, APPS_EVERY):
        return []
    apps = [re.sub(r"\D", "", str(a)) for a in (query.options or {}).get("app_store_ids") or []]
    apps = [a for a in apps if a][:MAX_APPS]
    if not apps:
        raise SourceBlocked("needs_setup", "", {"kind": "edit_setup", "field": "app_store_ids"})
    countries = [c.lower() for c in (query.countries or ["SA"])][:3]
    items: list[dict] = []
    for app in apps:
        for country in countries:
            data = base._call(query, "App Store reviews", APPLE_REVIEWS.format(country=country, app=app))
            entries = (data.get("feed") or {}).get("entry") or []
            if isinstance(entries, dict):
                entries = [entries]
            for entry in entries:
                if "im:rating" not in entry:
                    continue  # the first entry of older feeds describes the app
                stars = _int((entry.get("im:rating") or {}).get("label")) or 0
                title = (entry.get("title") or {}).get("label") or ""
                body = (entry.get("content") or {}).get("label") or ""
                review_id = (entry.get("id") or {}).get("label") or hashlib.sha1(f"{title}{body}".encode()).hexdigest()
                items.append({"source": "app_store", "external_id": f"{app}-{review_id}"[:255],
                              "text": f"{title}\n{body}".strip(), "country": country.upper(),
                              "published_at": base._date((entry.get("updated") or {}).get("label")),
                              "url": f"https://apps.apple.com/{country}/app/id{app}?see-all=reviews",
                              "author_name": ((entry.get("author") or {}).get("name") or {}).get("label"),
                              "owned": True, "reach": None,
                              "extra": {"kind": "review", "stars": stars, "app_id": app,
                                        "sentiment": "positive" if stars >= 4 else "negative" if 0 < stars <= 2
                                        else None}})
    _stamp(cursor)
    return items


def collect_google_play(db: Session, query, cursor: dict) -> list[dict]:
    raise SourceBlocked("needs_key", "")


ALL = {
    **base.COLLECTORS,
    "threads": collect_threads, "youtube_comments": collect_youtube_comments, "web": collect_web,
    "reddit": collect_reddit, "tiktok": collect_tiktok, "telegram": collect_telegram, "linkedin": collect_linkedin,
    "app_store": collect_app_store, "google_play": collect_google_play,
}
