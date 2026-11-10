"""Accounts API: OAuth (workspace app or platform-wide app), state handling, manual tokens, tests, isolation."""
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.core.db import utcnow
from app.core.errors import LimitReached
from app.modules.social import oauth
from app.modules.social.models import AccountStat, OAuthSession, SocialAccount
from app.modules.workspaces.models import WorkspaceSetting
from tests.conftest import signup
from tests.social_common import account, jobs_in_test_session  # noqa: F401


@pytest.fixture(autouse=True)
def _no_platform_apps(monkeypatch):
    for key in ("META_APP_ID", "META_APP_SECRET", "X_CLIENT_ID", "X_CLIENT_SECRET"):
        monkeypatch.delenv(f"SAI_{key}", raising=False)
    oauth.platform_apps.cache_clear()
    yield
    oauth.platform_apps.cache_clear()


def _query(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_guided_setup_then_meta_login_creates_page_and_instagram(client, auth, db, mock_http):
    setup = client.get("/api/accounts/oauth/setup/instagram", headers=auth.headers).json()
    assert setup["platform"] == "facebook" and not setup["configured"]
    assert setup["redirect_uri"].endswith("/oauth/callback") and setup["steps"]
    r = client.post("/api/accounts/oauth/start", json={"platform": "facebook"}, headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "oauth_not_configured"
    assert client.put("/api/accounts/oauth/apps/facebook", json={"client_id": "app", "client_secret": " "},
                      headers=auth.headers).status_code == 400

    r = client.put("/api/accounts/oauth/apps/facebook", json={"client_id": " app42 ", "client_secret": "s3cret"},
                   headers=auth.headers)
    assert r.status_code == 200
    params = _query(r.json()["url"])
    assert params["client_id"] == "app42" and "facebook.com" in r.json()["url"]
    # the secret is stored encrypted and never returned
    row = db.scalar(select(WorkspaceSetting).where(WorkspaceSetting.key == "social.app.facebook"))
    assert row.value["client_secret"] != "s3cret"
    setup = client.get("/api/accounts/oauth/setup/facebook", headers=auth.headers).json()
    assert setup["configured"] and setup["own_app"] and setup["source"] == "workspace"
    assert "s3cret" not in str(setup)

    def handler(method, url, kw):
        if url.endswith("/oauth/access_token"):
            assert kw["params"]["client_secret"] == "s3cret"
            return mock_http.response(200, {"access_token": "user-token"})
        return mock_http.response(200, {"data": [{
            "id": "p1", "name": "My Page", "access_token": "page-token",
            "instagram_business_account": {"id": "ig1", "username": "mybrand"},
        }]})

    mock_http(handler)
    r = client.get(f"/oauth/callback?state={params['state']}&code=code123", follow_redirects=False)
    assert r.status_code == 303
    assert "/en/settings/accounts?connected=2" in r.headers["location"]
    accounts = client.get("/api/accounts", headers=auth.headers).json()
    assert sorted(a["platform"] for a in accounts) == ["facebook", "instagram"]
    assert all(a["state"] == "connected" and a["oauth_app"] == "workspace" for a in accounts)
    assert "access_token" not in accounts[0] and accounts[0]["has_token"]
    # the state is single use
    r = client.get(f"/oauth/callback?state={params['state']}&code=code123", follow_redirects=False)
    assert "error=" in r.headers["location"]


def test_platform_wide_app_from_environment(client, auth, monkeypatch, mock_http):
    monkeypatch.setenv("SAI_X_CLIENT_ID", "platform-x")
    monkeypatch.setenv("SAI_X_CLIENT_SECRET", "platform-secret")
    oauth.platform_apps.cache_clear()
    options = {o["key"]: o for o in client.get("/api/accounts/platforms", headers=auth.headers).json()}
    assert options["x"]["configured"] and options["x"]["source"] == "platform"
    assert options["telegram"]["method"] == "token" and not options["facebook"]["configured"]
    url = client.post("/api/accounts/oauth/start", json={"platform": "x"}, headers=auth.headers).json()["url"]
    params = _query(url)
    assert params["client_id"] == "platform-x" and params["code_challenge_method"] == "S256"

    def handler(method, url, kw):
        if url.endswith("/oauth2/token"):
            assert kw["data"]["code_verifier"]
            return mock_http.response(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 7200})
        return mock_http.response(200, {"data": {"id": "42", "name": "Brand", "username": "brand"}})

    mock_http(handler)
    r = client.get(f"/oauth/callback?state={params['state']}&code=c", follow_redirects=False)
    assert "connected=1" in r.headers["location"]
    acc = client.get("/api/accounts", headers=auth.headers).json()[0]
    assert acc["oauth_app"] == "platform" and acc["can_refresh"] and acc["token_expires_at"]


def test_oauth_state_handling(client, auth, db, monkeypatch, mock_http):
    monkeypatch.setenv("SAI_META_APP_ID", "app")
    monkeypatch.setenv("SAI_META_APP_SECRET", "secret")
    oauth.platform_apps.cache_clear()
    mock_http(lambda m, u, k: pytest.fail("no network call for a bad state"))
    r = client.get("/oauth/callback?state=forged&code=x", follow_redirects=False)
    assert r.status_code == 303 and "error=" in r.headers["location"]
    # refused consent
    url = client.post("/api/accounts/oauth/start", json={"platform": "instagram"}, headers=auth.headers).json()["url"]
    state = _query(url)["state"]
    r = client.get(f"/oauth/callback?state={state}&error=access_denied&error_description=Denied",
                   follow_redirects=False)
    assert "error=Denied" in r.headers["location"]
    # expired session
    url = client.post("/api/accounts/oauth/start", json={"platform": "facebook"}, headers=auth.headers).json()["url"]
    session = db.scalar(select(OAuthSession).where(OAuthSession.state_token == _query(url)["state"]))
    session.created_at = utcnow() - timedelta(hours=2)
    db.flush()
    r = client.get(f"/oauth/callback?state={session.state_token}&code=x", follow_redirects=False)
    assert "expired" in r.headers["location"] or "error=" in r.headers["location"]
    assert client.get("/api/accounts", headers=auth.headers).json() == []


def test_editors_cannot_connect_accounts(client, auth):
    editor = signup(client, email="ed@example.com", workspace="Ed")
    from app.core.mail import OUTBOX
    client.post("/api/workspace/invitations", json={"email": "ed@example.com", "role": "editor"},
                headers=auth.headers)
    token = OUTBOX[-1].get_body(("plain",)).get_content().strip().rsplit("/", 1)[-1]
    client.post(f"/api/invitations/{token}/accept", headers=editor.headers)
    as_editor = {**editor.headers, "X-Workspace": str(auth.workspace_id)}
    assert client.get("/api/accounts", headers=as_editor).status_code == 200
    assert client.post("/api/accounts/oauth/start", json={"platform": "x"}, headers=as_editor).status_code == 403
    assert client.post("/api/accounts", json={"platform": "telegram", "access_token": "1:A", "external_id": "@c"},
                       headers=as_editor).status_code == 403


def test_manual_telegram_connection_test_and_disconnect(client, auth, db, mock_http):
    def handler(method, url, kw):
        if url.endswith("/getMe"):
            return mock_http.response(200, {"ok": True, "result": {"first_name": "Bot", "username": "brandbot"}})
        if url.endswith("/getChat"):
            return mock_http.response(200, {"ok": True, "result": {"title": "Brand news", "username": "brandnews"}})
        return mock_http.response(200, {"ok": True, "result": 321})

    mock_http(handler)
    r = client.post("/api/accounts", json={"platform": "telegram", "access_token": "123:SECRET",
                                           "external_id": "@brandnews", "name": "News"}, headers=auth.headers)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["ok"] and data["account"]["state"] == "connected" and data["account"]["username"] == "brandnews"
    assert "SECRET" not in r.text
    account_id = data["account"]["id"]
    assert client.post(f"/api/accounts/{account_id}/test", headers=auth.headers).json()["ok"]
    r = client.post(f"/api/accounts/{account_id}/sync", headers=auth.headers)
    assert r.json()["accounts"] == 1
    acc = db.get(SocialAccount, account_id)
    assert acc.followers == 321
    assert db.scalar(select(AccountStat).where(AccountStat.account_id == account_id)).followers == 321
    # missing channel
    r = client.post("/api/accounts", json={"platform": "telegram", "access_token": "1:A"}, headers=auth.headers)
    assert r.json()["code"] == "missing_external_id"
    # disconnect keeps history but erases the token
    assert client.delete(f"/api/accounts/{account_id}", headers=auth.headers).status_code == 204
    db.refresh(acc)
    assert acc.access_token is None and not acc.active and acc.state == "disconnected"
    assert client.get("/api/accounts", headers=auth.headers).json() == []
    assert len(client.get("/api/accounts?include_inactive=true", headers=auth.headers).json()) == 1


def test_failed_connection_is_reported(client, auth, mock_http):
    mock_http(lambda m, u, k: mock_http.response(401, {"error": {"message": "Invalid OAuth access token"}}))
    r = client.post("/api/accounts", json={"platform": "facebook", "access_token": "bad", "external_id": "1"},
                    headers=auth.headers)
    data = r.json()
    assert not data["ok"] and data["account"]["state"] == "expired"
    assert "Invalid OAuth" in data["message"]


def test_whatsapp_is_listed_as_inbox_only(client, auth, db):
    account(db, auth.workspace_id, "whatsapp", name="Support")
    account(db, auth.workspace_id, "facebook", name="Page")
    rows = {a["platform"]: a for a in client.get("/api/accounts", headers=auth.headers).json()}
    assert rows["whatsapp"]["inbox_only"] and not rows["whatsapp"]["can_publish"]
    assert rows["facebook"]["can_publish"]
    studio = client.get("/api/studio", headers=auth.headers).json()
    assert [a["platform"] for a in studio["accounts"]] == ["facebook"]
    assert client.delete(f"/api/accounts/{rows['whatsapp']['id']}", headers=auth.headers).status_code == 400


def test_account_limit_is_checked(client, auth, monkeypatch, mock_http):
    from app.modules.billing import limits

    def full(db, workspace_id, resource, amount=1):
        if resource == "social_accounts":
            raise LimitReached("Your plan allows no more accounts.", code="limit_social_accounts")

    monkeypatch.setattr(limits, "check", full)
    mock_http(lambda m, u, k: pytest.fail("no call"))
    r = client.post("/api/accounts", json={"platform": "telegram", "access_token": "1:A", "external_id": "@c"},
                    headers=auth.headers)
    assert r.status_code == 402


def test_accounts_are_isolated_between_workspaces(client, db, mock_http):
    a = signup(client, email="ia@example.com", workspace="IA")
    b = signup(client, email="ib@example.com", workspace="IB")
    acc_b = account(db, b.workspace_id, "facebook", name="B page")
    assert client.get("/api/accounts", headers=a.headers).json() == []
    for method, path in (("get", ""), ("patch", ""), ("delete", ""), ("post", "/test"), ("post", "/sync")):
        kwargs = {"json": {"name": "hack"}} if method == "patch" else {}
        r = getattr(client, method)(f"/api/accounts/{acc_b.id}{path}", headers=a.headers, **kwargs)
        assert r.status_code == 404, (method, path)
    db.refresh(acc_b)
    assert acc_b.name == "B page" and acc_b.active
    # workspace B's own app is not used by A
    client.put("/api/accounts/oauth/apps/facebook", json={"client_id": "b-app", "client_secret": "b-secret",
                                                          "connect": False}, headers=b.headers)
    assert not client.get("/api/accounts/oauth/setup/facebook", headers=a.headers).json()["configured"]


def test_refresh_tokens_task(db, auth, mock_http, monkeypatch):
    from app.modules.social import tasks
    monkeypatch.setenv("SAI_LINKEDIN_CLIENT_ID", "li")
    monkeypatch.setenv("SAI_LINKEDIN_CLIENT_SECRET", "lis")
    oauth.platform_apps.cache_clear()
    soon = account(db, auth.workspace_id, "linkedin", refresh_token="rt", token_expires_at=utcnow() + timedelta(days=1),
                   extra={"oauth_app": "platform"})
    dead = account(db, auth.workspace_id, "x", token_expires_at=utcnow() + timedelta(days=1))
    mock_http(lambda m, u, k: mock_http.response(200, {"access_token": "fresh", "expires_in": 5184000}))
    assert tasks.refresh_tokens() == 1
    assert soon.access_token == "fresh" and soon.state == "connected"
    assert dead.state == "expired" and "reconnect" in dead.last_error.lower()
