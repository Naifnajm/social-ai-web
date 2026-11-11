"""YouTube, Pinterest and Google Business Profile: rules, publishing, login and token renewal.

The network APIs are mocked: these tests pin down what we send, not what the networks accept.
"""
import base64
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.db import utcnow
from app.core.i18n import set_locale
from app.modules.social import accounts, oauth, publishing, service
from app.modules.social.platforms import platform_rules
from tests.social_common import PNG, account, image, jobs_in_test_session, public_https, video  # noqa: F401


@pytest.fixture()
def ws(auth):
    return auth.workspace_id


@pytest.fixture(autouse=True)
def _no_platform_apps(monkeypatch):
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "PINTEREST_APP_ID", "PINTEREST_APP_SECRET"):
        monkeypatch.delenv(f"SAI_{key}", raising=False)
    oauth.platform_apps.cache_clear()
    yield
    oauth.platform_apps.cache_clear()


def _post(db, ws, accounts_, content="Hello world", **kwargs):
    return service.create_post(db, ws, None, content=content, account_ids=[a.id for a in accounts_], **kwargs)


def _messages(db, post):
    return [p["message"] for p in publishing.problems(db, post)]


def _query(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


# ------------------------------------------------------------------ rules
def test_rules_of_the_new_networks(db, ws):
    yt, pin, gb = account(db, ws, "youtube"), account(db, ws, "pinterest"), account(db, ws, "google_business")
    picture, clip = image(db, ws).id, video(db, ws).id

    assert _messages(db, _post(db, ws, [yt])) == ["YouTube needs a video."]
    assert "YouTube publishes videos only." in _messages(db, _post(db, ws, [yt], media_ids=[picture]))
    assert _messages(db, _post(db, ws, [yt], media_ids=[clip])) == []

    assert _messages(db, _post(db, ws, [pin])) == ["Pinterest needs an image."]
    assert "Pinterest cannot publish videos from here." in _messages(db, _post(db, ws, [pin], media_ids=[clip]))
    two = [picture, image(db, ws, "b.png").id]
    assert "Pinterest accepts one image per post." in _messages(db, _post(db, ws, [pin], media_ids=two))
    assert _messages(db, _post(db, ws, [pin], media_ids=[picture])) == []

    assert _messages(db, _post(db, ws, [gb])) == []  # text only is fine
    assert any("too long" in m for m in _messages(db, _post(db, ws, [gb], content="a" * 1501)))
    assert "Google Business Profile cannot publish videos from here." in _messages(
        db, _post(db, ws, [gb], media_ids=[clip]))

    rules = platform_rules()
    assert rules["youtube"]["images"] is False and rules["youtube"]["video"] is True
    assert rules["pinterest"]["video"] is False and rules["google_business"]["max_chars"] == 1500


def test_new_rule_messages_are_translated(db, ws):
    yt = account(db, ws, "youtube")
    post = _post(db, ws, [yt])
    set_locale("ar")
    try:
        assert _messages(db, post) == ["تحتاج YouTube إلى فيديو."]
    finally:
        set_locale("en")


# ------------------------------------------------------------------ publishing
def test_youtube_uploads_the_video_in_two_steps(db, ws, mock_http):
    yt = account(db, ws, "youtube")
    post = _post(db, ws, [yt], content="Our new menu\nCome and taste it <today>", media_ids=[video(db, ws).id])
    sent = {}

    def handler(method, url, kw):
        if method == "POST" and url.startswith("https://www.googleapis.com/upload/youtube/v3/videos"):
            assert kw["params"] == {"uploadType": "resumable", "part": "snippet,status"}
            assert kw["headers"]["Authorization"] == "Bearer yttok"
            assert kw["headers"]["X-Upload-Content-Type"] == "video/mp4"
            sent["meta"] = json.loads(kw["data"])
            sent["length"] = int(kw["headers"]["X-Upload-Content-Length"])
            return mock_http.response(200, {}, headers={"Location": "https://upload.example/session-1"})
        assert method == "PUT" and url == "https://upload.example/session-1"
        assert len(kw["data"]) == sent["length"]
        return mock_http.response(200, {"id": "vid42"})

    mock_http(handler)
    service.submit(db, post, None, action="publish")
    target = post.targets[0]
    assert (target.state, target.external_id) == ("posted", "vid42")
    assert target.external_url == "https://www.youtube.com/watch?v=vid42"
    assert sent["meta"]["snippet"]["title"] == "Our new menu"
    assert "<" not in sent["meta"]["snippet"]["description"]  # YouTube rejects angle brackets
    assert sent["meta"]["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False}


def test_pinterest_pins_the_image_to_the_chosen_board_with_the_link(db, ws, mock_http, public_https):
    pin = account(db, ws, "pinterest")
    pin.extra = dict(pin.extra, board_id="b2")
    post = _post(db, ws, [pin], content="Lunch offer\nTwo for one until Friday https://rif.example/menu.",
                 media_ids=[image(db, ws).id])

    def handler(method, url, kw):
        assert (method, url) == ("POST", "https://api.pinterest.com/v5/pins")
        body = kw["json"]
        assert body["board_id"] == "b2" and body["title"] == "Lunch offer"
        # the link of the text (replaced by its tracked short link) is the pin's link, without the full stop
        assert body["link"].startswith("https://") and not body["link"].endswith(".")
        assert body["link"] + "." in body["description"]
        assert body["media_source"]["source_type"] == "image_base64"
        assert body["media_source"]["content_type"] == "image/png"
        assert base64.b64decode(body["media_source"]["data"]) == PNG
        return mock_http.response(201, {"id": "777"})

    mock_http(handler)
    service.submit(db, post, None, action="publish")
    assert post.targets[0].external_url == "https://www.pinterest.com/pin/777/"


def test_pinterest_falls_back_to_the_first_board_and_board_can_be_changed(client, auth, db, mock_http):
    pin = account(db, auth.workspace_id, "pinterest")
    db.commit()
    out = client.get(f"/api/accounts/{pin.id}", headers=auth.headers).json()
    assert out["board_id"] == "b1" and [b["name"] for b in out["boards"]] == ["Menu", "Offers"]
    r = client.patch(f"/api/accounts/{pin.id}", json={"board_id": "b2"}, headers=auth.headers)
    assert r.status_code == 200 and r.json()["board_id"] == "b2"
    r = client.patch(f"/api/accounts/{pin.id}", json={"board_id": "nope"}, headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "bad_board"


def test_google_business_post_with_photo_and_button(db, ws, mock_http, public_https):
    gb = account(db, ws, "google_business")
    post = _post(db, ws, [gb], content="Open on Sunday from 10:00. Book: https://rif.example/book",
                 media_ids=[image(db, ws).id])

    def handler(method, url, kw):
        assert (method, url) == ("POST", "https://mybusiness.googleapis.com/v4/accounts/1/locations/2/localPosts")
        body = kw["json"]
        assert body["topicType"] == "STANDARD" and body["summary"].startswith("Open on Sunday")
        assert body["media"][0]["mediaFormat"] == "PHOTO"
        assert body["media"][0]["sourceUrl"].startswith("https://api.example.com/")
        button = body["callToAction"]
        assert button["actionType"] == "LEARN_MORE" and body["summary"].endswith(button["url"])
        return mock_http.response(200, {"name": "accounts/1/locations/2/localPosts/9",
                                        "searchUrl": "https://local.google.com/place?id=9"})

    mock_http(handler)
    service.submit(db, post, None, action="publish")
    target = post.targets[0]
    assert target.external_id.endswith("/localPosts/9") and target.external_url.startswith("https://local.google")


def test_google_business_photo_needs_a_public_server(db, ws, mock_http):
    gb = account(db, ws, "google_business")
    post = _post(db, ws, [gb], media_ids=[image(db, ws).id])
    mock_http(lambda m, u, k: pytest.fail("must not call Google"))
    service.submit(db, post, None, action="publish")
    assert post.targets[0].state == "failed" and "public" in post.targets[0].error


# ------------------------------------------------------------------ login
def _own_app(client, auth, platform):
    r = client.put(f"/api/accounts/oauth/apps/{platform}", json={"client_id": "cid", "client_secret": "sec"},
                   headers=auth.headers)
    assert r.status_code == 200, r.text
    return r.json()["url"]


def test_one_google_app_serves_youtube_and_business_profile(client, auth, mock_http):
    url = _own_app(client, auth, "youtube")
    params = _query(url)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "youtube.upload" in params["scope"] and params["access_type"] == "offline"
    assert params["prompt"] == "consent"
    # the keys entered for YouTube are already there for Google Business Profile
    setup = client.get("/api/accounts/oauth/setup/google_business", headers=auth.headers).json()
    assert setup["configured"] and setup["own_app"] and setup["brand"] == "Google"

    def handler(method, url, kw):
        if url == "https://oauth2.googleapis.com/token":
            assert kw["data"]["client_secret"] == "sec" and kw["data"]["code"] == "c1"
            return mock_http.response(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
        assert url.endswith("/youtube/v3/channels")
        return mock_http.response(200, {"items": [{"id": "UC1", "snippet": {
            "title": "Rif Coffee", "customUrl": "@rifcoffee", "thumbnails": {"default": {"url": "https://i/a.jpg"}}}}]})

    mock_http(handler)
    r = client.get(f"/oauth/callback?state={params['state']}&code=c1", follow_redirects=False)
    assert "connected=1" in r.headers["location"], r.headers["location"]
    row = client.get("/api/accounts", headers=auth.headers).json()[0]
    assert (row["platform"], row["username"], row["can_refresh"]) == ("youtube", "rifcoffee", True)

    r = client.post("/api/accounts/oauth/start", json={"platform": "google_business"}, headers=auth.headers)
    assert "business.manage" in _query(r.json()["url"])["scope"]


def test_google_business_login_adds_one_account_per_location(client, auth, mock_http):
    params = _query(_own_app(client, auth, "google_business"))

    def handler(method, url, kw):
        if url == "https://oauth2.googleapis.com/token":
            return mock_http.response(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
        if url.endswith("/v1/accounts"):
            return mock_http.response(200, {"accounts": [{"name": "accounts/1"}]})
        assert url.endswith("/v1/accounts/1/locations") and kw["params"]["readMask"] == "name,title"
        return mock_http.response(200, {"locations": [{"name": "locations/2", "title": "Rif Coffee Utrecht"},
                                                      {"name": "locations/3", "title": "Rif Coffee Amsterdam"}]})

    mock_http(handler)
    r = client.get(f"/oauth/callback?state={params['state']}&code=c1", follow_redirects=False)
    assert "connected=2" in r.headers["location"], r.headers["location"]
    rows = client.get("/api/accounts", headers=auth.headers).json()
    assert sorted(a["external_id"] for a in rows) == ["accounts/1/locations/2", "accounts/1/locations/3"]
    assert {a["platform_label"] for a in rows} == {"Google Business Profile"}


def test_pinterest_login_reads_the_boards_and_keeps_the_chosen_one(client, auth, db, mock_http):
    url = _own_app(client, auth, "pinterest")
    params = _query(url)
    assert url.startswith("https://www.pinterest.com/oauth/") and "pins:write" in params["scope"]
    boards = [{"id": "b1", "name": "Menu"}, {"id": "b2", "name": "Offers"}]

    def handler(method, url, kw):
        if url == "https://api.pinterest.com/v5/oauth/token":
            assert kw["headers"]["Authorization"].startswith("Basic ")
            return mock_http.response(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 2592000})
        if url.endswith("/user_account"):
            return mock_http.response(200, {"id": "u1", "username": "rifcoffee", "follower_count": 12})
        assert url.endswith("/v5/boards")
        return mock_http.response(200, {"items": boards})

    mock_http(handler)
    client.get(f"/oauth/callback?state={params['state']}&code=c1", follow_redirects=False)
    row = client.get("/api/accounts", headers=auth.headers).json()[0]
    assert (row["platform"], row["board_id"]) == ("pinterest", "b1")
    client.patch(f"/api/accounts/{row['id']}", json={"board_id": "b2"}, headers=auth.headers)
    # connecting again must not move the pins back to the first board
    r = client.post("/api/accounts/oauth/start", json={"platform": "pinterest"}, headers=auth.headers)
    client.get(f"/oauth/callback?state={_query(r.json()['url'])['state']}&code=c2", follow_redirects=False)
    assert client.get(f"/api/accounts/{row['id']}", headers=auth.headers).json()["board_id"] == "b2"


# ------------------------------------------------------------------ token renewal
@pytest.mark.parametrize("platform,token_url", [("youtube", "https://oauth2.googleapis.com/token"),
                                                ("google_business", "https://oauth2.googleapis.com/token"),
                                                ("pinterest", "https://api.pinterest.com/v5/oauth/token")])
def test_tokens_renew_themselves(db, ws, mock_http, platform, token_url):
    oauth.save_workspace_credentials(db, ws, platform, "cid", "sec")
    acc = account(db, ws, platform, refresh_token="rt-old", token_expires_at=utcnow() - timedelta(minutes=1))

    def handler(method, url, kw):
        assert url == token_url and kw["data"]["grant_type"] == "refresh_token"
        assert kw["data"]["refresh_token"] == "rt-old"
        return mock_http.response(200, {"access_token": "fresh", "expires_in": 3600})  # no new refresh token

    mock_http(handler)
    assert accounts.valid_token(db, acc) == "fresh"
    assert acc.refresh_token == "rt-old" and acc.state == "connected"
