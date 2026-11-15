"""Radar (social listening): matching, sources, classification, detection, numbers and the actions that hand
mentions and events to the inbox, studio, planner and approvals."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.db import utcnow
from app.core.models import Notification
from app.modules.billing import platform as platform_settings
from app.modules.billing import service as billing
from app.modules.inbox.models import Conversation, Message
from app.modules.listening import analysis, detection, service
from app.modules.listening import text as tx
from app.modules.listening.models import ListeningQuery, Mention, RadarEvent
from app.modules.social.models import Post, SocialAccount

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Nakhla Cafe opens a new branch in Riyadh</title><link>https://news.example/1</link>
<guid>n-1</guid><pubDate>Sun, 15 Nov 2026 07:00:00 GMT</pubDate><description>&lt;b&gt;New&lt;/b&gt; branch</description>
<source url="https://news.example">Riyadh News</source></item>
<item><title>Nakhla dates harvest starts</title><link>https://news.example/2</link><guid>n-2</guid>
<pubDate>Sun, 15 Nov 2026 06:00:00 GMT</pubDate></item>
<item><title>Habba coffee launches 30% offer</title><link>https://news.example/3</link><guid>n-3</guid>
<pubDate>Sun, 15 Nov 2026 05:00:00 GMT</pubDate></item>
</channel></rss>"""


def _query(db, workspace_id, **values):
    data = dict(name="Nakhla", keywords=["nakhla", "نخلة", "#nakhla"], required=[], excluded=["dates"],
                languages=[], countries=[], competitors=[{"name": "Habba", "keywords": ["habba", "حبة"]}],
                sources=["owned", "news"], active=True, x_monthly_cap=100)
    data.update(values)
    query = ListeningQuery(workspace_id=workspace_id, **data)
    db.add(query)
    db.flush()
    return query


def _mention(db, query, text="nakhla", hours=1, **values):
    mention = Mention(workspace_id=query.workspace_id, query_id=query.id, source=values.pop("source", "x"),
                      external_id=values.pop("external_id", f"m{utcnow().timestamp()}{text[:8]}{hours}{values}"),
                      text=text, published_at=utcnow() - timedelta(hours=hours),
                      analyzed=values.pop("analyzed", True), **values)
    db.add(mention)
    db.flush()
    return mention


def _no_ai(monkeypatch):
    from app.modules.ai import service as ai
    monkeypatch.setattr(ai, "has_provider", lambda *a, **k: False)


# ------------------------------------------------------------------------------------------------ text
def test_matching_is_arabic_aware():
    assert tx.matches("رحت مقهى نخله اليوم", ["نخلة"])
    assert tx.matches("وبنخلة القهوة أحلى", ["نخلة"])
    assert not tx.matches("نخلات كثيرة", ["نخلة"])
    assert tx.matches("Love #Nakhla coffee", ["#nakhla"])
    assert not tx.matches("nakhla dates are sweet", ["nakhla"], excluded=["dates"])
    assert not tx.matches("nakhla coffee", ["nakhla"], required=["delivery"])
    assert tx.brand_of("habba is better", ["nakhla"], [{"name": "Habba", "keywords": ["habba"]}]) == (True, "Habba")
    assert tx.brand_of("nakhla and habba", ["nakhla"], [{"name": "Habba", "keywords": ["habba"]}]) == (True, None)


def test_lexicon_classifier_reads_dialect():
    late = tx.classify("طلبت من نخلة قبل ساعة وللحين ما وصل!! زفت")
    assert late["sentiment"] == "negative" and late["intent"] == "complaint" and late["emotion"] == "anger"
    assert tx.classify("السبانش لاتيه رهيب والموظفين ذوق")["sentiment"] == "positive"
    buyer = tx.classify("كم سعر القهوة عندكم؟ متوفر توصيل؟")
    assert buyer["intent"] == "purchase"
    assert "توصيل" in tx.words("التوصيل تأخر") or "توصيل" in tx.words("التوصيل")


# ------------------------------------------------------------------------------------- setup & plan limits
def test_setup_respects_the_plan(client, auth, db, monkeypatch, mock_http):
    mock_http(lambda m, u, k: mock_http.response(200, RSS))
    body = {"name": "Brand", "keywords": ["nakhla"], "sources": ["owned", "news"]}
    r = client.post("/api/listening/queries", json=body, headers=auth.headers)
    assert r.status_code == 201, r.text
    assert r.json()["mentions"] == 2  # the first run happened in the worker: two news items name the brand
    status = client.get("/api/listening/status", headers=auth.headers).json()
    assert status["enabled"] and status["queries_used"] == 1 and status["queries_limit"] == 1
    again = client.post("/api/listening/queries", json=body, headers=auth.headers)
    assert again.status_code == 402 and again.json()["resource"] == "listening_queries"

    sub = billing.get_subscription(db, auth.workspace_id)
    billing.apply_plan(db, sub, "starter", status="active")
    db.flush()
    blocked = client.patch(f"/api/listening/queries/{r.json()['id']}", json={"name": "x"}, headers=auth.headers)
    assert blocked.status_code == 402 and blocked.json()["reason"] == "feature"
    assert client.get("/api/listening/status", headers=auth.headers).json()["enabled"] is False

    billing.apply_plan(db, sub, "pro", status="active")
    db.flush()
    x = client.patch(f"/api/listening/queries/{r.json()['id']}", json={"sources": ["news", "x"]},
                     headers=auth.headers)
    assert x.status_code == 402  # X is a Business source
    billing.apply_plan(db, sub, "business", status="active")
    db.flush()
    assert client.patch(f"/api/listening/queries/{r.json()['id']}", json={"sources": ["news", "x"]},
                        headers=auth.headers).status_code == 200


# --------------------------------------------------------------------------------------------- sources
def test_news_x_and_instagram_collection(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    platform_settings.set_secret(db, "listening.x_bearer_token", "x-token")
    ig = SocialAccount(workspace_id=auth.workspace_id, name="ig", platform="instagram", external_id="17841",
                       access_token="ig-token")
    db.add(ig)
    db.flush()
    query = _query(db, auth.workspace_id, sources=["news", "x", "instagram"])

    def handler(method, url, kwargs):
        params = kwargs.get("params") or {}
        if "news.google.com" in url:
            return mock_http.response(200, RSS)
        if "api.x.com" in url:
            assert kwargs["headers"]["Authorization"] == "Bearer x-token" and params["max_results"] == 100
            return mock_http.response(200, {
                "data": [{"id": "1", "text": "نخلة أفضل قهوة 😍", "author_id": "u1", "created_at": "2026-11-15T08:00:00Z",
                          "public_metrics": {"like_count": 5, "retweet_count": 1}},
                         {"id": "2", "text": "random post", "author_id": "u1", "created_at": "2026-11-15T08:00:00Z"}],
                "includes": {"users": [{"id": "u1", "username": "foodie", "name": "Foodie",
                                        "public_metrics": {"followers_count": 120000}}]},
                "meta": {"newest_id": "2"}})
        if url.endswith("/17841/tags"):
            return mock_http.response(200, {"data": [{"id": "t1", "caption": "great time here", "username": "sara",
                                                      "timestamp": "2026-11-15T07:00:00+0000", "like_count": 3}]})
        if url.endswith("/ig_hashtag_search"):
            assert params["q"] == "nakhla"
            return mock_http.response(200, {"data": [{"id": "h1"}]})
        if url.endswith("/h1/recent_media"):
            return mock_http.response(200, {"data": [{"id": "hm1", "caption": "#nakhla latte", "comments_count": 2}]})
        raise AssertionError(url)

    calls = mock_http(handler)
    result = service.collect(db, query)
    assert result["errors"] == {}
    rows = {(m.source, m.external_id): m for m in db.scalars(select(Mention).where(Mention.query_id == query.id))}
    news = [m for m in rows.values() if m.source == "news"]
    assert {m.brand for m in news} == {None, "Habba"} and len(news) == 2  # "dates" excluded
    assert ("x", "1") in rows and ("x", "2") not in rows
    assert rows[("x", "1")].author_followers == 120000 and rows[("x", "1")].sentiment == "positive"
    assert ("instagram", "t1") in rows and rows[("instagram", "t1")].brand is None  # tagged: own brand
    assert ("instagram", "hm1") in rows
    assert query.cursors["x"]["since_id"] == "2" and query.cursors["x"]["reads"] == 2
    assert "h1" in query.cursors["instagram"]["hashtag_ids"].values()
    # a second run reads nothing new from the news it already saw, and X waits 30 minutes
    count = len(calls)
    assert service.collect(db, query)["new"] == 0
    assert not any("api.x.com" in c["url"] for c in calls[count:])
    usage = service.x_usage(query)
    assert usage["reads"] == 2 and usage["cost_usd"] == 0.01


def test_x_stops_at_the_monthly_cap(db, auth, mock_http, monkeypatch):
    _no_ai(monkeypatch)
    platform_settings.set_secret(db, "listening.x_bearer_token", "x-token")
    query = _query(db, auth.workspace_id, sources=["x"], x_monthly_cap=100,
                   cursors={"x": {"month": utcnow().strftime("%Y-%m"), "reads": 95}})
    calls = mock_http(lambda m, u, k: pytest.fail("X must not be called past the cap"))
    service.collect(db, query)
    assert not calls and query.cursors["x"]["capped"] is True
    assert service.x_usage(query)["capped"]


def test_owned_comments_come_from_the_inbox(db, auth, monkeypatch):
    _no_ai(monkeypatch)
    account = SocialAccount(workspace_id=auth.workspace_id, name="page", platform="facebook", external_id="p1",
                            access_token="t")
    db.add(account)
    db.flush()
    conv = Conversation(workspace_id=auth.workspace_id, account_id=account.id, platform="facebook", kind="comment",
                        external_thread_id="c1", post_url="https://fb/p")
    db.add(conv)
    db.flush()
    db.add(Message(workspace_id=auth.workspace_id, conversation_id=conv.id, account_id=account.id, direction="in",
                   channel="public", body="الطلب تأخر كثير", external_id="c1"))
    db.add(Message(workspace_id=auth.workspace_id, conversation_id=conv.id, account_id=account.id, direction="in",
                   channel="dm", body="private message", external_id="d1"))
    db.flush()
    query = _query(db, auth.workspace_id, sources=["owned"])
    service.collect(db, query)
    mentions = db.scalars(select(Mention).where(Mention.query_id == query.id)).all()
    assert len(mentions) == 1
    m = mentions[0]
    assert m.platform == "facebook" and m.brand is None and m.conversation_id == conv.id and m.status == "converted"
    assert m.sentiment == "negative" and m.topic  # lexicon topic (delivery / orders)


# -------------------------------------------------------------------------------------------- analysis
def test_ai_classification_and_review_stars_win(db, auth, monkeypatch):
    from app.modules.ai import service as ai
    query = _query(db, auth.workspace_id)
    a = _mention(db, query, "nakhla latte was cold", analyzed=False)
    b = _mention(db, query, "nakhla ok", hours=2, analyzed=False, extra={"sentiment": "negative"},
                 source="google_business")
    seen = {}

    def fake_json(db_, ws, system, user, **kwargs):
        seen["system"], seen["user"] = system, user
        return {"items": [{"i": 0, "sentiment": "negative", "intent": "complaint", "emotion": "sadness",
                           "topic": "Temperature"},
                          {"i": 1, "sentiment": "positive", "intent": "praise", "emotion": "joy", "topic": "Service"}]}

    monkeypatch.setattr(ai, "has_provider", lambda *a, **k: True)
    monkeypatch.setattr(ai, "generate_json", fake_json)
    assert analysis.classify_pending(db, auth.workspace_id) == 2
    assert (a.sentiment, a.intent, a.emotion, a.topic) == ("negative", "complaint", "sadness", "Temperature")
    assert b.sentiment == "negative" and b.intent == "complaint"  # the star rating wins over the AI
    assert "sarcasm" in seen["system"] and "[0]" in seen["user"]


# ------------------------------------------------------------------------------------------- detection
def test_crisis_is_detected_written_and_notified(db, auth, monkeypatch):
    from app.modules.ai import service as ai
    query = _query(db, auth.workspace_id)
    for i in range(3):
        _mention(db, query, "nakhla nice", hours=24 * (i + 2), sentiment="positive")
    for i in range(10):
        _mention(db, query, f"nakhla delivery late {i}", hours=1, sentiment="negative", topic="Delivery",
                 reach=1000 * i, source="instagram", platform="instagram", external_id=f"ig{i}")
    monkeypatch.setattr(ai, "has_provider", lambda *a, **k: True)
    monkeypatch.setattr(ai, "generate_json", lambda *a, **k: {
        "title": "Delivery complaints tripled", "what": "10 negative mentions", "why": "One problem",
        "suggestion": "Reply once", "draft": "We are sorry, the team is on it."})
    created = detection.detect(db, query)
    crisis = [e for e in created if e.kind == "crisis"]
    assert len(crisis) == 1
    event = crisis[0]
    assert event.severity == "urgent" and event.topic == "Delivery" and event.ai_written
    assert event.draft.startswith("We are sorry") and len(event.evidence_ids) == 8
    assert event.metrics["count"] == 10 and len(event.metrics["hourly"]) == 24
    note = db.scalar(select(Notification).where(Notification.kind == "radar.event"))
    assert note and note.link == f"/radar/events/{event.id}"
    # the same crisis is not created twice in a day
    assert not [e for e in detection.detect(db, query) if e.kind == "crisis"]


def test_opportunity_influencer_competitor_and_rising(db, auth, monkeypatch):
    _no_ai(monkeypatch)
    query = _query(db, auth.workspace_id)
    for i in range(5):
        _mention(db, query, f"nakhla price of the decaf? {i}", hours=5 + i, intent="purchase", topic="Decaf",
                 sentiment="neutral")
    _mention(db, query, "nakhla is great", hours=2, author_followers=80000, author_handle="bigfoodie",
             sentiment="positive")
    for i in range(25):
        _mention(db, query, f"habba offer {i}", hours=3 + i, brand="Habba")
    for i in range(12):
        _mention(db, query, f"nakhla cookies {i}", hours=10 + i, sentiment="positive")
    kinds = {e.kind: e for e in detection.detect(db, query)}
    assert kinds["opportunity"].topic == "Decaf" and kinds["opportunity"].metrics["count"] == 5
    assert kinds["influencer"].severity == "normal" and "bigfoodie" in kinds["influencer"].title
    assert kinds["competitor"].brand == "Habba"
    assert kinds["rising"].severity == "info" and kinds["rising"].topic.lower() == "cookies"


# ---------------------------------------------------------------------------------------------- numbers
def test_overview_voice_competitors_and_breakdowns(client, auth, db):
    query = _query(db, auth.workspace_id)
    for i in range(6):
        _mention(db, query, "nakhla latte رهيب #nakhla_love", hours=2 + i, sentiment="positive", reach=100,
                 emotion="joy", topic="Taste", country="SA", lang="ar", author_followers=10 * i)
    for i in range(3):
        _mention(db, query, "nakhla delivery late", hours=30 + i, sentiment="negative", reach=50, topic="Delivery",
                 emotion="anger", intent="complaint")
    _mention(db, query, "nakhla muted", hours=1, sentiment="negative", status="muted")
    for i in range(4):
        _mention(db, query, "habba deal", hours=3 + i, brand="Habba", sentiment="neutral")
    h = auth.headers
    ov = client.get("/api/listening/overview", params={"days": 7}, headers=h).json()
    assert ov["kpis"]["mentions"]["value"] == 9 and ov["kpis"]["reach"]["value"] == 750
    assert ov["kpis"]["net_sentiment"]["value"] == 33 and ov["kpis"]["share_of_voice"]["value"] == 69
    assert len(ov["series"]) == 8 and sum(d["count"] for d in ov["series"]) == 9
    assert ov["sentiment"] == {"positive": 67, "neutral": 0, "negative": 33}
    assert ov["words"][0]["word"] in ("latte", "رهيب", "delivery", "late")
    voice = client.get("/api/listening/voice", params={"days": 7}, headers=h).json()
    assert voice["hashtags"][0] == {"tag": "#nakhla_love", "count": 6, "change": None}
    assert voice["top_negative"]["text"] == "nakhla delivery late"
    assert any(p["phrase"] == "delivery late" for p in voice["phrases"])
    comp = client.get("/api/listening/competitors", params={"days": 7}, headers=h).json()
    assert comp["brands"] == ["Acme", "Habba"]
    own = comp["table"][0]
    assert own["own"] and own["mentions"] == 9 and own["share_of_voice"] == 69 and own["passion"] == 100
    assert own["top_complaint"] == "Delivery"
    br = client.get("/api/listening/breakdowns", params={"days": 7}, headers=h).json()
    assert sum(map(sum, br["heatmap"])) == 9 and br["countries"] == [{"country": "SA", "share": 67}]
    assert br["emotions"][0] == {"emotion": "joy", "share": 67}
    assert {t["topic"] for t in br["topics"]} == {"Taste", "Delivery"}


def test_no_setup_yet_is_a_clear_404(client, auth):
    r = client.get("/api/listening/overview", headers=auth.headers)
    assert r.status_code == 404


# ------------------------------------------------------------------------------------- mentions & actions
def test_mentions_filters_correction_and_inbox(client, auth, db):
    query = _query(db, auth.workspace_id)
    ig = SocialAccount(workspace_id=auth.workspace_id, name="ig", platform="instagram", external_id="17841",
                       access_token="t")
    db.add(ig)
    db.flush()
    bad = _mention(db, query, "nakhla where is my order?", sentiment="negative", intent="complaint",
                   source="instagram", platform="instagram", external_id="c-55", author_handle="sara")
    _mention(db, query, "nakhla news article", source="news", intent="news", sentiment="neutral")
    _mention(db, query, "nakhla from a big account", author_followers=40000, sentiment="positive")
    h = auth.headers
    data = client.get("/api/listening/mentions", params={"sentiment": "negative"}, headers=h).json()
    assert data["total"] == 1 and data["items"][0]["can_inbox"] and data["counts"]["unanswered"] == 1
    assert data["counts"]["influencers"] == 1
    assert client.get("/api/listening/mentions", params={"influencers": True}, headers=h).json()["total"] == 1
    fixed = client.patch(f"/api/listening/mentions/{bad.id}", json={"sentiment": "neutral"}, headers=h).json()
    assert fixed["sentiment"] == "neutral" and fixed["corrected"]
    r = client.post(f"/api/listening/mentions/{bad.id}/inbox", headers=h)
    assert r.status_code == 200, r.text
    conv = db.get(Conversation, r.json()["conversation_id"])
    assert conv.account_id == ig.id and conv.kind == "comment" and conv.external_thread_id == "c-55"
    assert conv.intent == "complaint" and conv.messages[0].body == "nakhla where is my order?"
    assert db.get(Mention, bad.id).status == "converted"
    news = db.scalar(select(Mention).where(Mention.source == "news"))
    refused = client.post(f"/api/listening/mentions/{news.id}/inbox", headers=h)
    assert refused.status_code == 400 and refused.json()["code"] == "radar_no_inbox"


def _event(db, query, mentions, **values):
    event = RadarEvent(workspace_id=query.workspace_id, query_id=query.id, kind=values.pop("kind", "crisis"),
                       severity="urgent", key=f"k{len(mentions)}{values}", title="Delivery complaints",
                       what="10 negative", why="One problem", suggestion="Reply once", draft="We are sorry.",
                       evidence_ids=[m.id for m in mentions], started_at=utcnow(), **values)
    db.add(event)
    db.flush()
    return event


def test_event_actions_reach_studio_planner_approvals_and_inbox(client, auth, db):
    query = _query(db, auth.workspace_id)
    fb = SocialAccount(workspace_id=auth.workspace_id, name="page", platform="facebook", external_id="p1",
                       access_token="t")
    db.add(fb)
    db.flush()
    m = _mention(db, query, "nakhla late again", source="facebook", platform="facebook", external_id="fb-1",
                 sentiment="negative")
    h = auth.headers
    e1 = _event(db, query, [m])
    detail = client.get(f"/api/listening/events/{e1.id}", headers=h).json()
    assert detail["evidence"][0]["id"] == m.id and detail["draft"] == "We are sorry."
    studio = client.post(f"/api/listening/events/{e1.id}/act", json={"action": "studio"}, headers=h).json()
    post = db.get(Post, studio["post_id"])
    assert post.content == "We are sorry." and post.source_ref == f"radar:{e1.id}" and post.state == "draft"
    assert studio["url"] == f"/studio?post={post.id}" and studio["event"]["state"] == "acted"

    e2 = _event(db, query, [m], kind="opportunity")
    planner = client.post(f"/api/listening/events/{e2.id}/act", json={"action": "planner", "text": "Decaf is here"},
                          headers=h).json()
    planned = db.get(Post, planner["post_id"])
    assert planned.planned_date and planned.content == "Decaf is here"

    e3 = _event(db, query, [m], kind="spike")
    approval = client.post(f"/api/listening/events/{e3.id}/act", json={"action": "approval"}, headers=h)
    assert approval.status_code == 200, approval.text
    assert db.get(Post, approval.json()["post_id"]).state == "to_approve"

    e4 = _event(db, query, [m], kind="influencer")
    inbox = client.post(f"/api/listening/events/{e4.id}/act", json={"action": "inbox"}, headers=h).json()
    assert inbox["converted"] == 1 and inbox["url"].startswith("/inbox/")

    e5 = _event(db, query, [m], kind="rising")
    assert client.post(f"/api/listening/events/{e5.id}/feedback", json={"feedback": "wrong"},
                       headers=h).json()["state"] == "dismissed"
    listed = client.get("/api/listening/events", params={"state": "all"}, headers=h).json()
    assert len(listed) == 5 and listed[0]["severity"] == "urgent"


def test_brief_and_search(client, auth, db, monkeypatch):
    from app.modules.listening import tasks
    from app.modules.workspaces.models import Workspace
    query = _query(db, auth.workspace_id)
    _mention(db, query, "nakhla latte amazing", hours=3, sentiment="positive")
    _mention(db, query, "nakhla cold coffee", hours=4, sentiment="negative")
    workspace = db.get(Workspace, auth.workspace_id)
    assert tasks.send_brief(db, workspace, query)
    note = db.scalar(select(Notification).where(Notification.kind == "radar.brief"))
    assert note.link == "/radar" and "2" in note.title
    found = client.get("/api/listening/search", params={"q": "latte"}, headers=auth.headers).json()
    assert found["total"] == 1 and found["sentiment"]["positive"] == 1
