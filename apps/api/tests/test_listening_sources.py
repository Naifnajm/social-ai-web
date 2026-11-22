"""Radar sources: the registry and its health states, the new collectors (Threads, YouTube comments, web, news APIs,
Reddit, TikTok provider, Telegram, LinkedIn, App Store), paid reads through the AI credits (markup, refusal, own
keys, monthly caps), dedupe and spam, the AI budget, real reach only, the sources API (workspace and admin), mention
actions and the MCP tool."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.db import utcnow
from app.core.models import Notification
from app.modules.ai.models import AIUsage
from app.modules.billing import credits
from app.modules.billing import platform as platform_settings
from app.modules.billing import service as billing
from app.modules.listening import (
    analysis,
    collectors,
    collectors_ext,
    detection,
    registry,
    service,
)
from app.modules.listening.models import ListeningQuery, Mention
from app.modules.social.models import Post, SocialAccount


def _query(db, workspace_id, **values):
    data = dict(name="Nakhla", keywords=["nakhla", "نخلة", "#nakhla"], required=[], excluded=[], languages=[],
                countries=[], competitors=[], sources=["owned"], active=True, x_monthly_cap=1000)
    data.update(values)
    query = ListeningQuery(workspace_id=workspace_id, **data)
    db.add(query)
    db.flush()
    return query


def _account(db, workspace_id, platform, external_id="acc-1", **values):
    account = SocialAccount(workspace_id=workspace_id, name=platform, platform=platform, external_id=external_id,
                            access_token="tok", state="connected", **values)
    db.add(account)
    db.flush()
    return account


def _no_ai(monkeypatch):
    from app.modules.ai import service as ai
    monkeypatch.setattr(ai, "has_provider", lambda *a, **k: False)


def _mentions(db, query, source=None):
    stmt = select(Mention).where(Mention.query_id == query.id)
    if source:
        stmt = stmt.where(Mention.source == source)
    return list(db.scalars(stmt.order_by(Mention.id)))


def _status(db, ws, key, query=None):
    return registry.health(db, ws, key, query)


# ------------------------------------------------------------------------------------------- registry
def test_every_source_has_a_health_state_and_a_fix(db, auth):
    ws = auth.workspace_id
    assert set(registry.SOURCE_DEFS) >= {"owned", "instagram", "facebook", "threads", "youtube", "youtube_comments",
                                         "google_business", "linkedin", "news", "web", "x", "reddit", "tiktok",
                                         "telegram", "app_store", "google_play", "snapchat"}
    assert _status(db, ws, "owned")["status"] == "ready" and _status(db, ws, "news")["status"] == "ready"
    ig = _status(db, ws, "instagram")
    assert ig["status"] == "needs_connection" and ig["action"] == {"kind": "connect", "platform": "instagram"}
    assert _status(db, ws, "threads")["action"]["platform"] == "threads"
    for key in ("web", "x", "reddit", "tiktok"):
        state = _status(db, ws, key)
        assert state["status"] == "needs_key" and state["action"]["kind"] == "ask_admin", key
    assert "Brave" in _status(db, ws, "web")["message"]
    assert _status(db, ws, "snapchat")["status"] == "disabled"
    assert _status(db, ws, "google_play")["action"]["kind"] == "request_permission"
    assert _status(db, ws, "youtube")["status"] == "needs_connection"
    assert _status(db, ws, "linkedin")["status"] == "needs_connection"

    query = _query(db, ws, sources=["telegram", "app_store"])
    assert _status(db, ws, "telegram", query)["status"] == "needs_setup"
    assert _status(db, ws, "app_store", query)["action"] == {"kind": "edit_setup", "field": "app_store_ids"}
    query.options = {"telegram_channels": ["nakhla_news"]}
    assert _status(db, ws, "telegram", query)["status"] == "ready"

    platform_settings.set_secret(db, "listening.brave_api_key", "brave-key")
    assert _status(db, ws, "web")["status"] == "ready"
    platform_settings.set_setting(db, "listening.sources_off", ["web"])
    assert _status(db, ws, "web")["status"] == "disabled"
    platform_settings.set_setting(db, "listening.sources_off", [])

    _account(db, ws, "threads")
    threads = _status(db, ws, "threads")
    assert threads["status"] == "ready" and "threads_keyword_search" in threads["note"]
    query.sources = ["threads"]
    query.cursors = {"threads": {"_health": {"status": "needs_permission", "message": "missing",
                                             "at": utcnow().isoformat()}}}
    last = _status(db, ws, "threads", query)
    assert last["status"] == "needs_permission" and last["action"]["kind"] == "request_permission"
    assert last["action"]["permission"] == "threads_keyword_search" and last["action"]["doc"].startswith("https://")
    # an old failure no longer counts
    query.cursors = {"threads": {"_health": {"status": "error", "message": "x",
                                             "at": (utcnow() - timedelta(days=2)).isoformat()}}}
    assert _status(db, ws, "threads", query)["status"] == "ready"

    platform_settings.set_secret(db, "listening.youtube_api_key", "yt")
    assert _status(db, ws, "youtube_comments")["status"] == "ready"
    registry.spend_youtube_units(db, 0, exhausted=True)
    assert _status(db, ws, "youtube")["status"] == "quota_exhausted"

    _account(db, ws, "linkedin", external_id="urn:li:person:1")
    assert _status(db, ws, "linkedin")["status"] == "needs_connection"
    _account(db, ws, "linkedin", external_id="urn:li:organization:9", extra={"scopes": "openid w_member_social"})
    assert _status(db, ws, "linkedin")["status"] == "needs_permission"


def test_plan_and_credits_states(db, auth):
    ws = auth.workspace_id
    platform_settings.set_secret(db, "listening.brave_api_key", "brave-key")
    platform_settings.set_secret(db, "listening.tiktok_provider_key", "sc-key")
    assert _status(db, ws, "tiktok")["status"] == "ready"  # the trial has every feature
    # the plan's AI allowance used up and no bought credits: paid sources stop, free ones go on
    db.add(AIUsage(workspace_id=ws, capability="text", cost=2.0, price=2.0))
    db.flush()
    state = _status(db, ws, "web")
    assert state["status"] == "out_of_credits" and state["action"] == {"kind": "buy_credits"}
    assert _status(db, ws, "news")["status"] == "ready"
    credits.add(db, ws, "grant", 500)
    assert _status(db, ws, "web")["status"] == "ready"
    sub = billing.get_subscription(db, ws)
    billing.apply_plan(db, sub, "pro", status="active")
    db.flush()
    assert _status(db, ws, "tiktok")["status"] == "not_in_plan" and _status(db, ws, "x")["status"] == "not_in_plan"
    assert _status(db, ws, "web")["status"] == "ready"
    billing.apply_plan(db, sub, "starter", status="active")
    db.flush()
    assert _status(db, ws, "owned")["status"] == "not_in_plan"


# ----------------------------------------------------------------------------------------- collectors
def test_threads_keyword_search_and_replies(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    account = _account(db, auth.workspace_id, "threads", external_id="th-1")
    query = _query(db, auth.workspace_id, sources=["threads"])

    def handler(method, url, kwargs):
        params = kwargs.get("params") or {}
        if url.endswith("/keyword_search"):
            assert params["search_type"] == "RECENT" and params["access_token"] == "tok"
            if params["q"] == "nakhla":
                return mock_http.response(200, {"data": [
                    {"id": "t1", "text": "Nakhla latte is the best", "permalink": "https://threads.net/@a/post/1",
                     "timestamp": "2026-11-20T10:00:00+0000", "username": "a"},
                    {"id": "t2", "text": "unrelated", "timestamp": "2026-11-20T10:00:00+0000", "username": "b"}]})
            return mock_http.response(200, {"data": []})
        if url.endswith("/me/threads"):
            return mock_http.response(200, {"data": [{"id": "own1"}]})
        if url.endswith("/own1/replies"):
            return mock_http.response(200, {"data": [{"id": "r1", "text": "when do you open?", "username": "c",
                                                      "timestamp": "2026-11-20T11:00:00+0000"}]})
        raise AssertionError(url)

    mock_http(handler)
    result = service.collect(db, query)
    assert result["errors"] == {}
    rows = {m.external_id: m for m in _mentions(db, query)}
    assert set(rows) == {"t1", "r1"}  # t2 does not name the brand; the reply is on the brand's own post
    assert rows["t1"].platform == "threads" and rows["t1"].reach is None and rows["r1"].account_id == account.id
    assert query.cursors["threads"]["since"].startswith("2026-11-20")


def test_threads_without_the_permission_explains_it(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    _account(db, auth.workspace_id, "threads")
    query = _query(db, auth.workspace_id, sources=["threads"])
    mock_http(lambda m, u, k: mock_http.response(403, {"error": {"message": "Application does not have permission "
                                                                            "for this action", "code": 10}}))
    result = service.collect(db, query)
    assert "threads" in result["errors"]
    state = registry.health(db, auth.workspace_id, "threads", query)
    assert state["status"] == "needs_permission" and "threads_keyword_search" in state["message"]


def test_youtube_comments_spend_quota_units(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    platform_settings.set_secret(db, "listening.youtube_api_key", "yt-key")
    _account(db, auth.workspace_id, "youtube", external_id="UC-own")
    query = _query(db, auth.workspace_id, sources=["youtube_comments"],
                   cursors={"youtube": {"videos": ["found1"]}})

    def thread(cid, text, when):
        return {"id": cid, "snippet": {"totalReplyCount": 2, "topLevelComment": {"id": cid, "snippet": {
            "textOriginal": text, "authorDisplayName": "Viewer", "authorChannelId": {"value": "UCv"},
            "likeCount": 3, "publishedAt": when}}}}

    def handler(method, url, kwargs):
        params = kwargs["params"]
        assert params["key"] == "yt-key"
        if url.endswith("/channels"):
            return mock_http.response(200, {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]})
        if url.endswith("/playlistItems"):
            return mock_http.response(200, {"items": [{"contentDetails": {"videoId": "own1"}}]})
        if url.endswith("/commentThreads"):
            if params["videoId"] == "own1":
                return mock_http.response(200, {"items": [thread("c1", "great video, when is the next one?",
                                                                 "2026-11-20T09:00:00Z")]})
            return mock_http.response(200, {"items": [thread("c2", "nakhla coffee is too sweet", "2026-11-20T08:00:00Z"),
                                                      thread("c3", "first!", "2026-11-20T08:00:00Z")]})
        raise AssertionError(url)

    mock_http(handler)
    service.collect(db, query)
    rows = {m.external_id: m for m in _mentions(db, query)}
    assert set(rows) == {"c1", "c2"}  # own video comments always count; others must name the brand
    assert rows["c1"].engagement == 5 and "lc=c1" in rows["c1"].url and rows["c1"].platform == "youtube"
    assert registry.youtube_units_used(db) == 4 and query.cursors["youtube_comments"]["units_last_run"] == 4


def test_youtube_quota_exceeded_becomes_health(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    platform_settings.set_secret(db, "listening.youtube_api_key", "yt-key")
    query = _query(db, auth.workspace_id, sources=["youtube"])
    mock_http(lambda m, u, k: mock_http.response(403, {"error": {"message": "The request cannot be completed "
                                                                            "because you have exceeded your quota."}}))
    service.collect(db, query)
    assert registry.health(db, auth.workspace_id, "youtube", query)["status"] == "quota_exhausted"
    assert registry.youtube_units_used(db) == registry.YOUTUBE_DAILY_UNITS


BRAVE_WEB = {"web": {"results": [
    {"title": "Nakhla review: the best Spanish latte in Riyadh", "url": "https://blog.example.com/nakhla",
     "description": "We tried <strong>Nakhla</strong> coffee", "page_age": "2026-11-20T08:00:00",
     "meta_url": {"hostname": "blog.example.com"}},
    {"title": "Nakhla on a forum", "url": "https://forum.example.org/t/1", "description": "nakhla delivery was late",
     "meta_url": {"hostname": "forum.example.org"}}]}}
BRAVE_NEWS = {"results": [{"title": "Nakhla opens in Jeddah", "url": "https://news.example/jeddah",
                           "description": "Nakhla cafe opens", "page_age": "2026-11-20T07:00:00",
                           "meta_url": {"hostname": "news.example"}}]}


def test_web_search_is_charged_at_platform_price(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    platform_settings.set_secret(db, "listening.brave_api_key", "brave-key")
    platform_settings.set_setting(db, "billing.ai_markup_percent", 20)
    query = _query(db, auth.workspace_id, sources=["web"])

    def handler(method, url, kwargs):
        assert kwargs["headers"]["X-Subscription-Token"] == "brave-key"
        return mock_http.response(200, BRAVE_WEB if "/web/search" in url else BRAVE_NEWS)

    mock_http(handler)
    service.collect(db, query)
    rows = {m.url: m for m in _mentions(db, query, "web")}
    assert len(rows) == 3
    blog = rows["https://blog.example.com/nakhla"]
    assert blog.author_name == "blog.example.com" and "<strong>" not in blog.text and blog.reach is None
    usage = db.scalars(select(AIUsage).where(AIUsage.workspace_id == auth.workspace_id,
                                             AIUsage.capability == "data")).all()
    assert len(usage) == 2 and all(u.units == 1 for u in usage)
    assert usage[0].cost == pytest.approx(0.005) and usage[0].price == pytest.approx(0.006)  # +20% markup
    assert usage[0].model_name == registry.usage_name("web") and usage[0].provider_id is None
    assert service.spend(query)["usd"] == pytest.approx(0.012)
    assert registry.month_usage(db, auth.workspace_id)["web"]["units"] == 2


def test_own_key_is_not_charged(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    registry.set_own_key(db, auth.workspace_id, "web", "my-own-brave")
    query = _query(db, auth.workspace_id, sources=["web"])
    mock_http(lambda m, u, k: (mock_http.response(200, BRAVE_WEB) if k["headers"]["X-Subscription-Token"] ==
                               "my-own-brave" else pytest.fail("platform key used")))
    service.collect(db, query)
    assert _mentions(db, query, "web")
    assert not db.scalars(select(AIUsage).where(AIUsage.capability == "data")).all()
    assert query.cursors["web"]["spend"]["own_units"] == 2 and service.spend(query)["usd"] == 0
    assert registry.cost_view(db, "web", auth.workspace_id)["own_key"] is True


def test_out_of_credits_stops_before_fetching(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    platform_settings.set_secret(db, "listening.x_bearer_token", "x-token")
    db.add(AIUsage(workspace_id=auth.workspace_id, capability="text", cost=2.0, price=2.0))  # trial: $2 a month
    db.flush()
    query = _query(db, auth.workspace_id, sources=["x", "news"])
    calls = mock_http(lambda m, u, k: (mock_http.response(200, b"<rss><channel></channel></rss>")
                                       if "news.google" in u else pytest.fail("X must not be called")))
    result = service.collect(db, query)
    assert "x" in result["errors"] and "news" not in result["errors"]
    assert not [c for c in calls if "api.x.com" in c["url"]]
    assert registry.health(db, auth.workspace_id, "x", query)["status"] == "out_of_credits"


def test_x_reads_are_charged_and_the_monthly_cap_holds(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    platform_settings.set_secret(db, "listening.x_bearer_token", "x-token")
    query = _query(db, auth.workspace_id, sources=["x"], monthly_cap_usd=0.15)
    posts = [{"id": str(i), "text": f"nakhla post {i}", "author_id": "u", "created_at": "2026-11-20T08:00:00Z",
              "public_metrics": {"like_count": 1, "impression_count": 500 if i == 0 else 0}} for i in range(20)]
    calls = mock_http(lambda m, u, k: mock_http.response(200, {"data": posts, "includes": {"users": [
        {"id": "u", "username": "fan", "public_metrics": {"followers_count": 900}}]}, "meta": {"newest_id": "19"}}))
    service.collect(db, query)
    assert calls[0]["params"]["max_results"] == 27  # what $0.15 buys at $0.0055 a post
    usage = db.scalar(select(AIUsage).where(AIUsage.capability == "data"))
    assert usage.units == 20 and usage.cost == pytest.approx(0.1) and usage.price == pytest.approx(0.11)
    rows = {m.external_id: m for m in _mentions(db, query)}
    assert rows["0"].reach == 500 and rows["1"].reach is None and rows["1"].author_followers == 900
    # $0.04 left buys 7 posts, less than X's minimum of 10 a call: refused before calling X
    query.cursors = {**query.cursors, "x": {**query.cursors["x"], "at": None}}
    before = len(calls)
    mock_http(lambda m, u, k: pytest.fail("cap"))
    service.collect(db, query)
    assert len(calls) == before
    state = registry.health(db, auth.workspace_id, "x", query)
    assert state["status"] == "quota_exhausted" and state["action"]["field"] == "monthly_cap_usd"


def test_news_uses_a_paid_api_when_the_platform_has_a_key(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    platform_settings.set_secret(db, "listening.gnews_api_key", "gn")
    query = _query(db, auth.workspace_id, sources=["news"], languages=["en"])

    def handler(method, url, kwargs):
        assert "gnews.io" in url and kwargs["params"]["apikey"] == "gn"
        return mock_http.response(200, {"articles": [{"title": "Nakhla raises prices", "description": "Coffee chain",
                                                      "url": "https://n.example/a", "publishedAt": "2026-11-20T06:00:00Z",
                                                      "source": {"name": "N Daily"}}]})

    mock_http(handler)
    service.collect(db, query)
    (row,) = _mentions(db, query)
    assert row.source == "news" and row.author_name == "N Daily"


def test_reddit_needs_keys_then_reads_posts(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    query = _query(db, auth.workspace_id, sources=["reddit"], options={"subreddits": ["r/riyadh"]})
    calls = mock_http(lambda m, u, k: pytest.fail("no call without keys"))
    service.collect(db, query)
    assert not calls and registry.health(db, auth.workspace_id, "reddit", query)["status"] == "needs_key"
    platform_settings.set_secret(db, "listening.reddit_client_id", "cid")
    platform_settings.set_secret(db, "listening.reddit_client_secret", "csecret")

    def handler(method, url, kwargs):
        if url.endswith("/access_token"):
            assert method == "POST" and kwargs["headers"]["Authorization"].startswith("Basic ")
            return mock_http.response(200, {"access_token": "rt"})
        assert url.endswith("/r/riyadh/search") and kwargs["params"]["restrict_sr"] == 1
        return mock_http.response(200, {"data": {"children": [{"data": {
            "name": "t3_a", "title": "Is Nakhla open late?", "selftext": "", "author": "u1", "subreddit": "riyadh",
            "permalink": "/r/riyadh/comments/a/x/", "created_utc": 1763600000, "score": 10, "num_comments": 4}}]}})

    mock_http(handler)
    service.collect(db, query)
    (row,) = _mentions(db, query)
    assert row.external_id == "t3_a" and row.engagement == 14 and row.url.startswith("https://www.reddit.com/r/")
    usage = db.scalar(select(AIUsage).where(AIUsage.capability == "data"))
    assert usage.units == 2 and usage.cost == pytest.approx(0.00048)


def test_tiktok_provider_parses_videos_with_real_views(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    platform_settings.set_secret(db, "listening.tiktok_provider_key", "sc-key")
    query = _query(db, auth.workspace_id, sources=["tiktok"], keywords=["nakhla", "#nakhla"])
    aweme = {"aweme_id": "7301", "desc": "Trying nakhla coffee #nakhla", "create_time": 1763600000,
             "author": {"unique_id": "foodie", "nickname": "Foodie", "follower_count": 120000},
             "statistics": {"play_count": 45000, "digg_count": 900, "comment_count": 50, "share_count": 10},
             "share_url": "https://www.tiktok.com/@foodie/video/7301"}

    def handler(method, url, kwargs):
        assert kwargs["headers"]["x-api-key"] == "sc-key"
        if url.endswith("/search/keyword"):
            return mock_http.response(200, {"search_item_list": [{"aweme_info": aweme}, {"aweme_info": aweme}]})
        assert url.endswith("/search/hashtag") and kwargs["params"]["hashtag"] == "nakhla"
        return mock_http.response(200, {"aweme_list": [aweme]})

    mock_http(handler)
    service.collect(db, query)
    (row,) = _mentions(db, query)
    assert row.reach == 45000 and row.author_followers == 120000 and row.engagement == 960
    assert row.platform == "tiktok" and row.url.endswith("/7301")
    usage = db.scalar(select(AIUsage).where(AIUsage.capability == "data"))
    assert usage.units == 1 and usage.cost == pytest.approx(0.0015)
    assert len(db.scalars(select(AIUsage).where(AIUsage.capability == "data")).all()) == 2  # keyword + hashtag


TELEGRAM_HTML = """<html><body><section>
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message js-widget_message" data-post="riyadhnews/101">
 <div class="tgme_widget_message_bubble"><div class="tgme_widget_message_text js-message_text" dir="auto">افتتاح فرع جديد
 لـ <b>نخلة</b> في جدة<br/>اليوم &amp; غداً <script>alert(1)</script></div>
 <div class="tgme_widget_message_footer"><span class="tgme_widget_message_views">1.2K</span>
 <a class="tgme_widget_message_date" href="https://t.me/riyadhnews/101"><time datetime="2026-11-20T09:00:00+00:00">
 09:00</time></a></div></div></div></div>
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="riyadhnews/102">
 <div class="tgme_widget_message_text">weather today</div></div></div>
</section></body></html>"""


def test_telegram_public_channels(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    posts = collectors_ext.parse_telegram(TELEGRAM_HTML)
    assert [p["id"] for p in posts] == ["riyadhnews/101", "riyadhnews/102"]
    assert posts[0]["views"] == 1200 and "نخلة" in posts[0]["text"] and "\n" in posts[0]["text"]
    assert "&amp;" not in posts[0]["text"] and "<b>" not in posts[0]["text"]
    query = _query(db, auth.workspace_id, sources=["telegram"], options={"telegram_channels": ["https://t.me/riyadhnews"]})
    calls = mock_http(lambda m, u, k: mock_http.response(200, TELEGRAM_HTML.encode()))
    service.collect(db, query)
    assert calls[0]["url"] == "https://t.me/s/riyadhnews"
    (row,) = _mentions(db, query)
    assert row.reach == 1200 and row.url == "https://t.me/riyadhnews/101"
    assert query.cursors["telegram"]["last"]["riyadhnews"] == 102
    query.cursors = {"telegram": {**query.cursors["telegram"], "at": None}}
    service.collect(db, query)
    assert len(_mentions(db, query)) == 1  # already read posts are skipped


def test_linkedin_page_comments(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    org = _account(db, auth.workspace_id, "linkedin", external_id="urn:li:organization:77")
    query = _query(db, auth.workspace_id, sources=["linkedin"])

    def handler(method, url, kwargs):
        if url.endswith("/rest/posts"):
            assert kwargs["params"]["author"] == "urn:li:organization:77"
            return mock_http.response(200, {"elements": [{"id": "urn:li:share:1"}]})
        assert "socialActions/urn%3Ali%3Ashare%3A1/comments" in url
        return mock_http.response(200, {"elements": [{"$URN": "urn:li:comment:(urn:li:share:1,5)",
                                                      "actor": "urn:li:person:abc", "message": {"text": "Great team!"},
                                                      "created": {"time": 1763600000000}}]})

    mock_http(handler)
    service.collect(db, query)
    (row,) = _mentions(db, query)
    assert row.text == "Great team!" and row.account_id == org.id and row.platform == "linkedin"


def test_app_store_reviews(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    query = _query(db, auth.workspace_id, sources=["app_store", "google_play"], countries=["SA"],
                   options={"app_store_ids": ["id1234567"], "google_play_ids": ["com.nakhla"]})
    feed = {"feed": {"entry": [
        {"im:name": {"label": "Nakhla"}},
        {"id": {"label": "r1"}, "im:rating": {"label": "1"}, "title": {"label": "يعلق"},
         "content": {"label": "التطبيق يعلق عند الدفع"}, "author": {"name": {"label": "Sara"}},
         "updated": {"label": "2026-11-20T05:00:00-07:00"}},
        {"id": {"label": "r2"}, "im:rating": {"label": "5"}, "title": {"label": "Great"},
         "content": {"label": "Fast ordering"}, "author": {"name": {"label": "Ali"}},
         "updated": {"label": "2026-11-20T06:00:00-07:00"}}]}}
    calls = mock_http(lambda m, u, k: mock_http.response(200, feed))
    result = service.collect(db, query)
    assert "/sa/rss/customerreviews/page=1/id=1234567/" in calls[0]["url"]
    rows = {m.external_id: m for m in _mentions(db, query)}
    assert set(rows) == {"1234567-r1", "1234567-r2"}
    assert rows["1234567-r1"].sentiment == "negative" and rows["1234567-r2"].sentiment == "positive"
    assert "google_play" in result["errors"]
    assert registry.health(db, auth.workspace_id, "google_play", query)["status"] == "needs_key"


# ----------------------------------------------------------------------------------- quality fixes
def test_dedupe_across_sources_and_spam(client, auth, db, monkeypatch):
    _no_ai(monkeypatch)
    query = _query(db, auth.workspace_id)
    now = utcnow()
    base = dict(published_at=now, author_handle="blog.example.com")
    service.store(db, query, [
        {"source": "web", "external_id": "w1", "url": "https://blog.example.com/nakhla",
         "text": "Nakhla review: the best latte in town", **base},
        {"source": "news", "external_id": "n1", "url": "https://blog.example.com/nakhla",
         "text": "Nakhla review: the best latte in town", **base},
        {"source": "x", "external_id": "x1", "author_handle": "fan1", "published_at": now,
         "text": "I really love the new nakhla pistachio latte!!"},
        {"source": "threads", "external_id": "t1", "author_handle": "fan1", "published_at": now,
         "text": "I really love the new Nakhla pistachio latte https://t.co/abc"},
        {"source": "x", "external_id": "x2", "author_handle": "bot77", "published_at": now,
         "text": "I really love the new nakhla pistachio latte!!"},
        {"source": "x", "external_id": "x3", "author_handle": "farm", "published_at": now,
         "text": "nakhla deals https://a.io https://b.io https://c.io https://d.io"},
    ])
    rows = {m.external_id: m for m in _mentions(db, query)}
    assert set(rows) == {"w1", "x1", "x2", "x3"}
    assert rows["w1"].extra["also_on"] == ["news"] and rows["x1"].extra["also_on"] == ["threads"]
    assert rows["x2"].status == "spam" and rows["x2"].extra["spam_reason"] == "repeated"
    assert rows["x3"].status == "spam" and rows["x3"].extra["spam_reason"] == "links"
    h = auth.headers
    data = client.get("/api/listening/mentions", params={"brand": "all"}, headers=h).json()
    assert data["total"] == 2 and data["counts"]["spam"] == 2
    spam = client.get("/api/listening/mentions", params={"status": "spam"}, headers=h).json()
    assert {m["spam_reason"] for m in spam["items"]} == {"repeated", "links"}
    undone = client.patch(f"/api/listening/mentions/{rows['x2'].id}", json={"status": "new"}, headers=h).json()
    assert undone["status"] == "new"
    assert client.get("/api/listening/mentions", headers=h).json()["total"] == 3


def test_ai_budget_scales_with_plan_and_crisis(db, auth, monkeypatch):
    from app.modules.ai import service as ai
    ws = auth.workspace_id
    assert analysis.ai_budget(db, ws) == 120  # trial
    sub = billing.get_subscription(db, ws)
    billing.apply_plan(db, sub, "business", status="active")
    db.flush()
    assert analysis.ai_budget(db, ws) == 1000
    query = _query(db, ws)
    for i in range(10):
        db.add(Mention(workspace_id=ws, query_id=query.id, source="x", external_id=f"neg{i}", text=f"nakhla bad {i}",
                       published_at=utcnow() - timedelta(minutes=10 + i), sentiment="negative", topic="Delivery",
                       analyzed=True))
    db.flush()
    monkeypatch.setattr(ai, "has_provider", lambda *a, **k: False)
    events = detection.detect(db, query)
    assert any(e.kind == "crisis" for e in events)
    assert analysis.ai_budget(db, ws) == 4000  # ×4 for six hours


def test_news_and_web_are_classified_by_ai(db, auth, monkeypatch):
    from app.modules.ai import service as ai
    query = _query(db, auth.workspace_id)
    for source in ("news", "web", "x"):
        db.add(Mention(workspace_id=auth.workspace_id, query_id=query.id, source=source, external_id=source,
                       text=f"nakhla story from {source}", published_at=utcnow(), analyzed=False))
    db.add(Mention(workspace_id=auth.workspace_id, query_id=query.id, source="x", external_id="spam",
                   text="nakhla spam", published_at=utcnow(), analyzed=False, status="spam"))
    db.flush()
    seen = {}

    def fake_json(db_, ws, system, user, **kwargs):
        seen["user"] = user
        return {"items": [{"i": i, "sentiment": "negative", "intent": "complaint", "emotion": "anger",
                           "topic": "Prices"} for i in range(3)]}

    monkeypatch.setattr(ai, "has_provider", lambda *a, **k: True)
    monkeypatch.setattr(ai, "generate_json", fake_json)
    analysis.classify_pending(db, auth.workspace_id)
    assert "(news)" in seen["user"] and "(web)" in seen["user"] and "spam" not in seen["user"]
    news = db.scalar(select(Mention).where(Mention.external_id == "news"))
    assert news.sentiment == "negative" and news.topic == "Prices"


def test_reach_is_never_invented(client, auth, db):
    item = collectors._ig_item({"id": "1", "caption": "x", "like_count": 100, "comments_count": 10},
                               SocialAccount(id=1), owned=True)
    assert item["reach"] is None and item["engagement"] == 110
    query = _query(db, auth.workspace_id)
    service.store(db, query, [
        {"source": "instagram", "external_id": "i1", "text": "nakhla is lovely today", "published_at": utcnow(),
         "author_followers": 5000, "reach": None, "author_handle": "a"},
        {"source": "tiktok", "external_id": "t1", "text": "nakhla tiktok video review", "published_at": utcnow(),
         "author_followers": 100, "reach": 3000, "author_handle": "b"}])
    ov = client.get("/api/listening/overview", params={"days": 7}, headers=auth.headers).json()
    reach = ov["kpis"]["reach"]
    assert reach["value"] == 3000 and reach["measured"] == 1 and reach["potential"] == 5000 and reach["estimated"]
    items = {m["source"]: m for m in client.get("/api/listening/mentions", headers=auth.headers).json()["items"]}
    assert items["instagram"]["reach"] is None and items["instagram"]["reach_estimated"] == 5000
    assert items["tiktok"]["reach"] == 3000 and items["tiktok"]["reach_estimated"] is None


# ----------------------------------------------------------------------------------------- API & roles
def test_sources_api_for_the_workspace(client, auth, db, mock_http, monkeypatch):
    from tests.test_connect import add_member
    _no_ai(monkeypatch)
    mock_http(lambda m, u, k: mock_http.response(200, BRAVE_WEB if "/web/" in u else BRAVE_NEWS))
    query = _query(db, auth.workspace_id, sources=["owned", "news"])
    viewer = add_member(client, db, auth, "viewer@example.com", "viewer")
    data = client.get("/api/listening/sources", headers=viewer.headers).json()
    rows = {s["key"]: s for s in data["sources"]}
    assert data["query_id"] == query.id and rows["news"]["in_query"] and rows["owned"]["health"]["status"] == "ready"
    assert rows["web"]["cost"]["unit"] == "query" and rows["web"]["cost"]["per_1000"] == pytest.approx(5.5)
    assert rows["tiktok"]["access"] == "provider" and rows["tiktok"]["beta"] and rows["tiktok"]["terms_note"]
    assert rows["x"]["quota"]["limit"] == 1000
    assert client.post("/api/listening/sources/web/toggle", json={"on": True}, headers=viewer.headers).status_code == 403
    on = client.post("/api/listening/sources/web/toggle", json={"query_id": query.id, "on": True}, headers=auth.headers)
    assert on.status_code == 200 and "web" in on.json()["sources"]
    assert client.post("/api/listening/sources/snapchat/toggle", json={"on": True},
                       headers=auth.headers).status_code == 400
    # the workspace's own Brave key: admins only, never shown back
    assert client.put("/api/listening/sources/web/own-key", json={"key": "k"},
                      headers=viewer.headers).status_code == 403
    r = client.put("/api/listening/sources/web/own-key", json={"key": "k-123"}, headers=auth.headers)
    assert r.json() == {"key": "web", "own_key": True}
    assert "k-123" not in client.get("/api/listening/sources", headers=auth.headers).text
    assert client.put("/api/listening/sources/news/own-key", json={"key": "k"}, headers=auth.headers).status_code == 400
    status = client.get("/api/listening/status", headers=auth.headers).json()
    assert {s["source"] for s in status["sources"]} >= {"threads", "tiktok", "web"}
    test = client.post("/api/listening/sources/web/test", json={"query_id": query.id}, headers=auth.headers).json()
    assert test["health"]["status"] == "ready" and test["result"]["new"] == 3
    assert not db.scalars(select(AIUsage).where(AIUsage.capability == "data")).all()  # own key: not charged


def test_query_options_and_cap(client, auth, db, mock_http):
    mock_http(lambda m, u, k: mock_http.response(200, b"<rss><channel></channel></rss>"))
    body = {"name": "Brand", "keywords": ["nakhla"], "sources": ["news", "telegram", "app_store"],
            "monthly_cap_usd": 25, "options": {"telegram_channels": ["riyadhnews", "riyadhnews"],
                                               "app_store_ids": ["123"]}}
    r = client.post("/api/listening/queries", json=body, headers=auth.headers)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["monthly_cap_usd"] == 25 and out["options"] == {"telegram_channels": ["riyadhnews"],
                                                               "app_store_ids": ["123"]}
    est = client.get("/api/listening/estimate", params={"query_id": out["id"]}, headers=auth.headers).json()
    assert est["costs"]["web"]["unit_price"] == pytest.approx(0.0055) and est["costs"]["web"]["expected_usd"] > 0
    sub = billing.get_subscription(db, auth.workspace_id)
    billing.apply_plan(db, sub, "pro", status="active")
    db.flush()
    refused = client.patch(f"/api/listening/queries/{out['id']}", json={"sources": ["news", "tiktok"]},
                           headers=auth.headers)
    assert refused.status_code == 402 and refused.json()["reason"] == "feature"


def test_admin_sources_keys_prices_and_costs(client, auth, db):
    from app.modules.auth.models import User
    assert client.get("/api/listening/admin/sources", headers=auth.headers).status_code == 403
    db.get(User, auth.user_id).is_superadmin = True
    db.flush()
    r = client.put("/api/listening/admin/sources", headers=auth.headers, json={
        "secrets": {"listening.brave_api_key": "brave-secret"}, "prices": {"web": 0.004, "x": None},
        "enabled": {"reddit": False}, "youtube_units_per_run": 500})
    assert r.status_code == 200, r.text
    assert "brave-secret" not in r.text
    rows = {s["key"]: s for s in r.json()["sources"]}
    assert rows["web"]["keys"]["listening.brave_api_key"] is True and rows["web"]["unit_price"] == 0.004
    assert rows["web"]["workspace_price"] == pytest.approx(0.0044) and rows["x"]["unit_price"] == 0.005
    assert rows["reddit"]["enabled"] is False and r.json()["youtube_units_per_run"] == 500
    assert registry.health(db, auth.workspace_id, "reddit")["status"] == "disabled"
    assert client.put("/api/listening/admin/sources", headers=auth.headers,
                      json={"secrets": {"ai.openai_api_key": "x"}}).status_code == 400
    assert client.put("/api/listening/admin/sources", headers=auth.headers,
                      json={"prices": {"news": 1}}).status_code == 400
    # the platform settings page shows the new keys as configured / not configured only
    settings = client.get("/api/admin/settings", headers=auth.headers).json()
    assert settings["values"]["listening.brave_api_key"] is True
    query = _query(db, auth.workspace_id)
    from app.modules.listening import metering
    metering.charge(db, query, "web", {}, 3)
    out = client.get("/api/listening/admin/sources", headers=auth.headers).json()
    assert out["workspaces"][0]["by_source"]["web"]["units"] == 3
    assert out["month_cost"] == pytest.approx(0.012)
    assert {s["key"]: s for s in out["sources"]}["web"]["usage"]["units"] == 3


# ------------------------------------------------------------------------------------ mention actions
def test_mention_actions_reach_the_rest_of_the_platform(client, auth, db, monkeypatch):
    from tests.test_connect import add_member
    _no_ai(monkeypatch)
    query = _query(db, auth.workspace_id)
    _account(db, auth.workspace_id, "instagram", external_id="17841")
    public = Mention(workspace_id=auth.workspace_id, query_id=query.id, source="x", external_id="p1",
                     url="https://x.com/a/status/1", text="Is nakhla open on Friday?", author_name="Sara",
                     published_at=utcnow(), topic="Hours")
    owned = Mention(workspace_id=auth.workspace_id, query_id=query.id, source="instagram", platform="instagram",
                    external_id="c-9", text="nakhla my order is late", author_handle="omar", published_at=utcnow())
    db.add_all([public, owned])
    db.flush()
    h = auth.headers
    reply = client.post(f"/api/listening/mentions/{public.id}/reply", headers=h).json()
    assert reply["url"] == public.url and "Sara" in reply["draft"] and reply["inbox_url"] is None
    inbox = client.post(f"/api/listening/mentions/{owned.id}/reply", headers=h).json()
    assert inbox["inbox_url"].startswith("/inbox/") and inbox["draft"]

    post = client.post(f"/api/listening/mentions/{public.id}/post", headers=h).json()
    row = db.get(Post, post["post_id"])
    assert row.source_ref == f"radar-mention:{public.id}" and row.state == "draft" and "Hours" in row.content
    assert post["url"] == f"/studio?post={row.id}" and db.get(Mention, public.id).status == "reviewed"

    board = client.post(f"/api/listening/mentions/{public.id}/board", json={"template": "quote_card"}, headers=h)
    assert board.status_code == 200, board.text
    from app.modules.production.models import Board, Node
    created = db.get(Board, board.json()["board_id"])
    texts = [n.text_value for n in db.scalars(select(Node).where(Node.board_id == created.id)) if n.text_value]
    assert any("Is nakhla open on Friday?" in t for t in texts) and board.json()["url"] == f"/production/{created.id}"

    assert client.post(f"/api/listening/mentions/{public.id}/report", json={"on": True},
                       headers=h).json()["in_report"] is True
    from app.modules.workspaces.models import Workspace
    block = service.report_block(db, db.get(Workspace, auth.workspace_id), utcnow() - timedelta(days=1),
                                 utcnow() + timedelta(hours=1))
    assert block["highlights"][0]["text"] == "Is nakhla open on Friday?"

    mate = add_member(client, db, auth, "mate@example.com", "editor")
    assigned = client.post(f"/api/listening/mentions/{public.id}/assign", json={"user_id": mate.user_id,
                                                                                "note": "Answer this"}, headers=h)
    assert assigned.json()["assigned_to_id"] == mate.user_id
    note = db.scalar(select(Notification).where(Notification.kind == "radar.assigned"))
    assert note.user_id == mate.user_id and note.body == "Answer this"
    assert client.post(f"/api/listening/mentions/{public.id}/assign", json={"user_id": 999999},
                       headers=h).status_code == 404
    viewer = add_member(client, db, auth, "v@example.com", "viewer")
    assert client.post(f"/api/listening/mentions/{public.id}/post", headers=viewer.headers).status_code == 403


def test_reply_draft_uses_ai_and_the_brand_guard(client, auth, db, monkeypatch):
    from app.modules.ai import service as ai
    from app.modules.brand import guard
    query = _query(db, auth.workspace_id)
    m = Mention(workspace_id=auth.workspace_id, query_id=query.id, source="web", external_id="w", text="nakhla?",
                published_at=utcnow())
    db.add(m)
    db.flush()
    monkeypatch.setattr(ai, "has_provider", lambda *a, **k: True)
    monkeypatch.setattr(ai, "generate_text", lambda *a, **k: "Thanks, cheap prices!")
    monkeypatch.setattr(guard, "enforce_text", lambda db_, ws, kit, text, user_id=None: (
        text.replace("cheap", "great"), ["Brand guard fixed: cheap"]))
    out = client.post(f"/api/listening/mentions/{m.id}/reply", headers=auth.headers).json()
    assert out["draft"] == "Thanks, great prices!" and out["ai"] and out["notes"]


def test_mcp_lists_radar_sources(client, auth, db):
    from tests.test_connect import call, connect
    _query(db, auth.workspace_id, sources=["owned", "x"])
    tokens, _cid = connect(client, auth, scopes=("read",))
    data = call(client, tokens["access_token"], "list_radar_sources")["structuredContent"]
    rows = {s["key"]: s for s in data["sources"]}
    assert rows["x"]["used_by_setup"] and rows["x"]["status"] == "needs_key" and rows["x"]["fix"]["kind"] == "ask_admin"
    assert rows["owned"]["status"] == "ready" and rows["tiktok"]["access"] == "provider"


def test_every_new_server_message_is_translated_to_arabic():
    import ast
    import json
    from pathlib import Path
    app = Path(__file__).resolve().parent.parent / "app"
    catalog = {}
    for path in [app / "i18n" / "ar.json", *sorted((app / "modules").glob("*/i18n/ar.json"))]:
        if path.exists():
            catalog.update(json.loads(path.read_text(encoding="utf-8")))
    missing = []
    for path in (app / "modules" / "listening").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("_", "lazy") and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value not in catalog:
                    missing.append(arg.value)
    assert not missing
