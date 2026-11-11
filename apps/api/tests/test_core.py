import io

from PIL import Image

from app.core.http import ApiError, call
from app.core.models import ApiLog
from tests.conftest import signup


def test_signup_login_me_refresh(client):
    auth = signup(client, email="sara@example.com", name="Sara", workspace="Sara Cafe")
    me = client.get("/api/auth/me", headers=auth.headers).json()
    assert me["user"]["email"] == "sara@example.com"
    assert me["workspaces"][0]["role"] == "owner"
    assert client.post("/api/auth/signup", json={"name": "x", "email": "SARA@example.com", "password": "secret123",
                                                  "workspace_name": "x"}).status_code == 400
    assert client.post("/api/auth/login", json={"email": "sara@example.com", "password": "nope"}).status_code == 401
    login = client.post("/api/auth/login", json={"email": "Sara@Example.com", "password": "secret123"})
    assert login.status_code == 200
    refreshed = client.post("/api/auth/refresh", json={"refresh_token": login.json()["refresh_token"]})
    assert refreshed.status_code == 200
    assert client.get("/api/auth/me").status_code in (200, 401)  # cookie session from the client


def test_workspace_isolation_and_roles(client):
    owner = signup(client, email="a@example.com", workspace="A")
    other = signup(client, email="b@example.com", workspace="B")
    # b cannot reach workspace A by forging the header: falls back to its own workspace
    r = client.get("/api/workspace", headers={**other.headers, "X-Workspace": str(owner.workspace_id)})
    assert r.json()["workspace"]["id"] == other.workspace_id
    # invite b as editor into A
    inv = client.post("/api/workspace/invitations", json={"email": "b@example.com", "role": "editor"},
                      headers=owner.headers)
    assert inv.status_code == 201
    from app.core.mail import OUTBOX
    token = OUTBOX[-1].get_body(("plain",)).get_content().strip().rsplit("/", 1)[-1]
    assert client.post(f"/api/invitations/{token}/accept", headers=other.headers).status_code == 200
    as_editor = {**other.headers, "X-Workspace": str(owner.workspace_id)}
    assert client.get("/api/workspace", headers=as_editor).json()["role"] == "editor"
    assert client.patch("/api/workspace", json={"name": "Hack"}, headers=as_editor).status_code == 403
    members = client.get("/api/workspace/members", headers=owner.headers).json()
    assert len(members) == 2
    owner_member = next(m for m in members if m["role"] == "owner")
    assert client.patch(f"/api/workspace/members/{owner_member['id']}", json={"role": "admin"},
                        headers=owner.headers).status_code == 400  # last owner


def test_settings_and_password_reset(client, auth):
    assert client.put("/api/workspace/settings", json={"inbox.mode": "suggest"}, headers=auth.headers).status_code == 200
    assert client.get("/api/workspace/settings?prefix=inbox.", headers=auth.headers).json() == {"mode": "suggest"}
    from app.core.mail import OUTBOX
    client.post("/api/auth/password/forgot", json={"email": auth.email})
    link = OUTBOX[-1].get_body(("plain",)).get_content().strip()
    token = link.split("token=")[1]
    r = client.post("/api/auth/password/reset", json={"token": token, "password": "newsecret1"})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=auth.headers).status_code == 401  # old sessions are revoked


def test_media_upload_and_public_link(client, auth):
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (255, 0, 0)).save(buffer, "PNG")
    r = client.post("/api/media", files={"file": ("red.png", buffer.getvalue(), "image/png")}, headers=auth.headers)
    assert r.status_code == 201, r.text
    media = r.json()
    assert (media["width"], media["height"]) == (40, 30)
    assert client.get(media["url"], headers=auth.headers).content == buffer.getvalue()
    url = client.get(f"/api/media/{media['id']}/public-url", headers=auth.headers).json()["url"]
    path = url.split("://", 1)[1].split("/", 1)[1]
    assert client.get("/" + path).status_code == 200
    assert client.get("/" + path[:-3] + "abc").status_code == 404


def test_http_call_logs_and_errors(db, mock_http):
    mock_http(lambda m, u, k: mock_http.response(401, {"error": {"message": "Invalid OAuth access token"}}))
    try:
        call("GET", "https://graph.facebook.com/me?access_token=SECRET", service="social", operation="Me")
    except ApiError as exc:
        assert "Authentication failed" in exc.message
        assert exc.status == 401
    log = db.query(ApiLog).order_by(ApiLog.id.desc()).first()
    assert log.status_code == 401 and "SECRET" not in log.endpoint


def test_sign_in_with_a_username(client, auth):
    """A user can pick a username in the profile and sign in with it instead of the e-mail."""
    r = client.patch("/api/auth/me", json={"username": "Rif.Admin"}, headers=auth.headers)
    assert r.status_code == 200 and r.json()["user"]["username"] == "rif.admin"
    assert client.patch("/api/auth/me", json={"username": "a b"}, headers=auth.headers).json()["code"] == "bad_username"
    email = auth.email
    for identifier in ("rif.admin", "RIF.ADMIN", email):
        ok = client.post("/api/auth/login", json={"email": identifier, "password": "secret123"})
        assert ok.status_code == 200, ok.text
    bad = client.post("/api/auth/login", json={"email": "rif.admin", "password": "wrong-password"},
                      headers={"Accept-Language": "ar"})
    assert bad.status_code == 401 and bad.json()["code"] == "bad_credentials" and "اسم المستخدم" in bad.json()["detail"]
    assert client.patch("/api/auth/me", json={"username": ""}, headers=auth.headers).json()["user"]["username"] is None


def test_sign_in_attempts_are_limited(client, monkeypatch):
    from app.core import hardening
    monkeypatch.setattr(hardening, "enabled", True)
    hardening._memory.clear()
    codes = [client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"}).status_code
             for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
    hardening._memory.clear()


def test_server_side_urls_must_be_public(monkeypatch):
    import pytest
    from app.core import hardening
    from app.core.errors import AppError
    monkeypatch.setattr(hardening.settings, "env", "prod")
    for url in ("http://example.com/v1", "https://localhost/v1", "https://127.0.0.1/v1", "https://10.0.0.5/v1",
                "https://169.254.169.254/latest/meta-data", "https://[::1]/v1", "ftp://example.com"):
        with pytest.raises(AppError):
            hardening.ensure_public_url(url)
    monkeypatch.setattr(hardening.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    assert hardening.ensure_public_url("https://api.example.com/v1") == "https://api.example.com/v1"


def test_uploads_cannot_run_script_and_api_sets_headers(client, auth):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    r = client.post("/api/media", files={"file": ("logo.svg", svg, "image/svg+xml")}, headers=auth.headers)
    if r.status_code in (200, 201):  # SVG uploads are accepted: opening one must stay inert
        got = client.get(f"/api/media/{r.json()["id"]}/file", headers=auth.headers)
        assert "sandbox" in got.headers["content-security-policy"] and got.headers["x-content-type-options"] == "nosniff"
    health = client.get("/api/health")
    assert health.headers["x-frame-options"] == "DENY" and health.headers["x-content-type-options"] == "nosniff"
