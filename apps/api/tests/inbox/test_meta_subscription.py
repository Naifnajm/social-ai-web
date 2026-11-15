"""Page subscription to the Meta app, independent polling, history import and posts scheduled on Meta."""
import logging
import time

from sqlalchemy import func, select

from app.modules.inbox import history, sources, subscription
from app.modules.inbox.models import AccountInboxState, Message
from app.modules.inbox.public import _RedactVerifyToken
from app.modules.social.models import ExternalPost, Post


def graph_error(response, message="(#200) Requires permission: pages_messaging"):
    return response(400, {"error": {"message": message, "code": 200, "type": "OAuthException"}})


def link_instagram(ib):
    ib.ig.extra = {"page_id": "PAGE1"}
    ib.db.flush()


def test_connect_subscribes_each_page_once_with_messages_and_feed(ib):
    link_instagram(ib)
    posts = []

    def handler(method, url, kw):
        if url.endswith("/PAGE1/subscribed_apps") and method == "POST":
            posts.append(kw["data"])
            return ib._mock_http.response(body={"success": True})
        raise AssertionError("unexpected %s %s" % (method, url))

    ib.http(handler)
    result = subscription.ensure(ib.db, [ib.fb, ib.ig], force=True)
    assert len(posts) == 1 and posts[0]["subscribed_fields"] == "messages,feed"  # shared by the page's two accounts
    assert result == {ib.fb.id: True, ib.ig.id: True}
    assert ib.fb.extra["webhook"]["ok"] is True and ib.ig.extra["webhook"]["fields"] == ["messages", "feed"]


def test_messages_refused_falls_back_to_feed(ib):
    link_instagram(ib)
    tried = []

    def handler(method, url, kw):
        tried.append(kw["data"]["subscribed_fields"])
        if "messages" in kw["data"]["subscribed_fields"]:
            return graph_error(ib._mock_http.response)
        return ib._mock_http.response(body={"success": True})

    ib.http(handler)
    result = subscription.ensure(ib.db, [ib.fb, ib.ig], force=True)
    assert tried[:2] == ["messages,feed", "feed"]
    assert result[ib.fb.id] is True          # Facebook only needs feed
    assert result[ib.ig.id] is False         # Instagram needs messages: flagged, with Meta's reason
    assert "pages_messaging" in ib.ig.extra["webhook"]["error"]


def test_check_repairs_only_when_the_subscription_is_missing(ib):
    calls = ib.http(lambda m, u, kw: ib._mock_http.response(
        body={"data": [{"id": "APP", "subscribed_fields": ["messages", "feed"]}]}))
    assert subscription.ensure(ib.db, [ib.fb]) == {ib.fb.id: True}
    assert [c["method"] for c in calls] == ["GET"]  # healthy: nothing written at Meta

    def empty_then_ok(method, url, kw):
        if method == "GET":
            return ib._mock_http.response(body={"data": []})
        return ib._mock_http.response(body={"success": True})

    calls = ib.http(empty_then_ok)
    assert subscription.ensure(ib.db, [ib.fb]) == {ib.fb.id: True}
    assert [c["method"] for c in calls] == ["GET", "POST"]


def test_one_failing_source_does_not_hide_the_other(ib):
    """Facebook without Messenger permission: conversations fail, comments of the page's posts still sync."""
    ib.comments["MEDIA1"] = [{"id": "c1", "text": "Great!", "username": "sara", "from": {"id": "U1", "username": "sara"},
                              "timestamp": "2026-11-11T10:00:00+0000"}]

    def media(method, url, kw):
        if method == "GET" and url.endswith("/media"):
            return ib._mock_http.response(body={"data": [{"id": "MEDIA1", "caption": "Hi", "permalink": "https://i/p"}]})
        if method == "GET" and url.endswith("/conversations"):
            return graph_error(ib._mock_http.response)
        return ib.handler(method, url, kw)

    ib.http(media)
    result = sources.poll_accounts(ib.db, [ib.ig])
    assert result["new"] == 1                                    # the comment came through
    state = ib.db.scalar(select(AccountInboxState).where(AccountInboxState.account_id == ib.ig.id))
    assert state.sync_error.startswith("messages:")              # and the problem is visible
    assert result["errors"] and state.last_sync_at is not None


def thread(tid, mid, text, when):
    return {"id": tid, "updated_time": when, "participants": {"data": [{"id": "PSID1", "name": "Sara"},
                                                                       {"id": "PAGE1", "name": "Brand Page"}]},
            "messages": {"data": [{"id": mid, "message": text, "from": {"id": "PSID1"}, "to": {"data": [{"id": "PAGE1"}]},
                                   "created_time": when}]}}


def test_history_import_reads_messages_posts_comments_and_scheduled(ib):
    now = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(time.time() - 3 * 86400))
    soon = int(time.time()) + 86400
    pages = {"n": 0}

    def handler(method, url, kw):
        params = kw.get("params") or {}
        response = ib._mock_http.response
        if method == "GET" and url.endswith("/me/conversations"):
            pages["n"] += 1
            if "after" in params:
                return response(body={"data": [thread("t2", "m2", "second", now)], "paging": {}})
            return response(body={"data": [thread("t1", "m1", "first", now)],
                                  "paging": {"cursors": {"after": "CUR"}, "next": "https://next"}})
        if method == "GET" and url.endswith("/PAGE1/published_posts"):
            return response(body={"data": [{"id": "PAGE1_100", "message": "Old post", "created_time": now,
                                            "permalink_url": "https://fb/100", "full_picture": "https://img/1.jpg"}]})
        if method == "GET" and url.endswith("/PAGE1/scheduled_posts"):
            return response(body={"data": [{"id": "PAGE1_200", "message": "Coming soon",
                                            "scheduled_publish_time": soon, "created_time": now}]})
        return ib.handler(method, url, kw)

    ib.http(handler)
    ib.comments["PAGE1_100"] = [{"id": "fc1", "message": "Nice", "from": {"id": "U9", "name": "Omar"},
                                 "created_time": now}]
    result = history.import_history(ib.db, ib.fb, days=30)
    assert result["errors"] == []
    assert (result["messages"], result["comments"], result["posts"], result["scheduled"]) == (2, 1, 1, 1)
    kinds = {r.external_id: r.kind for r in ib.db.scalars(select(ExternalPost))}
    assert kinds == {"PAGE1_100": "published", "PAGE1_200": "scheduled"}
    assert ib.db.scalar(select(func.count()).select_from(Post)) == 0         # never a Post: it would publish twice
    assert not ib.db.scalars(select(Message).where(Message.bot_state == "pending")).first()  # old: no assistant

    again = history.import_history(ib.db, ib.fb, days=30)                    # idempotent
    assert (again["messages"], again["comments"], again["posts"]) == (0, 0, 0)
    assert ib.db.scalar(select(func.count()).select_from(ExternalPost)) == 2


def test_scheduled_mirror_drops_posts_no_longer_scheduled(ib):
    soon = int(time.time()) + 3600
    rows = [{"id": "S1", "message": "a", "scheduled_publish_time": soon},
            {"id": "S2", "message": "b", "scheduled_publish_time": soon + 60}]
    ib.http(lambda m, u, kw: ib._mock_http.response(body={"data": rows}))
    assert history.sync_scheduled(ib.db, ib.fb) == 2
    rows.pop(0)  # S1 was published or deleted on Meta
    ib.http(lambda m, u, kw: ib._mock_http.response(body={"data": rows}))
    assert history.sync_scheduled(ib.db, ib.fb) == 1
    assert [r.external_id for r in ib.db.scalars(select(ExternalPost))] == ["S2"]


def test_external_posts_endpoint_and_admin_actions(ib, client):
    soon = int(time.time()) + 3600
    ib.http(lambda m, u, kw: ib._mock_http.response(
        body={"data": [{"id": "S1", "message": "Soon", "scheduled_publish_time": soon}]}))
    history.sync_scheduled(ib.db, ib.fb)
    r = client.get("/api/posts/external?kind=scheduled", headers=ib.auth.headers)
    assert r.status_code == 200, r.text
    assert [p["external_id"] for p in r.json()] == ["S1"] and r.json()[0]["account_name"] == "Brand Page"

    ib.http(lambda m, u, kw: ib._mock_http.response(body={"success": True}))
    r = client.post("/api/inbox/accounts/%s/webhook/subscribe" % ib.fb.id, headers=ib.auth.headers)
    assert r.status_code == 200, r.text
    assert r.json()["webhook_ok"] is True and r.json()["webhook_fields"] == ["messages", "feed"]
    r = client.post("/api/inbox/accounts/%s/webhook/subscribe" % ib.tg.id, headers=ib.auth.headers)
    assert r.status_code == 400 or r.status_code == 422  # Telegram has no Meta webhook


def test_verify_token_is_hidden_from_access_logs():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4:0", "GET", "/webhooks/meta?hub.mode=subscribe&hub.verify_token=TOP&hub_verify_token=TOP&x=1",
                                "1.1", 200), None)
    _RedactVerifyToken().filter(record)
    text = record.getMessage()
    assert "TOP" not in text and "hub.verify_token=***" in text and "x=1" in text
