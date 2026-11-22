"""Accounts: the admin CLI (passwords at a hidden prompt), Platform admin › Users (every action, permissions and
audit), temporary passwords, memberships and ownership, erasure and export, "view as" (impersonation), two-step
sign-in and the person's own account center."""
import io
import json
import re
import time
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.mail import OUTBOX
from app.modules.auth.models import User
from app.modules.billing import cli
from app.modules.users import service
from app.modules.users.models import UserEvent
from app.modules.workspaces.models import Membership, Role

from .conftest import signup

STRONG = "Correct-Horse-Battery-42"


@pytest.fixture()
def admin(client, db):
    a = signup(client, email="root@example.com", name="Root", workspace="HQ")
    db.get(User, a.user_id).is_superadmin = True
    db.flush()
    return a


def _events(db, user_id, type_=None):
    query = select(UserEvent).where(UserEvent.user_id == user_id)
    if type_:
        query = query.where(UserEvent.type == type_)
    return db.scalars(query.order_by(UserEvent.id)).all()


def _login(client, email, password, **extra):
    client.cookies.clear()
    return client.post("/api/auth/login", json={"email": email, "password": password, **extra})


def _bearer(token, workspace_id=None):
    headers = {"Authorization": f"Bearer {token}"}
    if workspace_id:
        headers["X-Workspace"] = str(workspace_id)
    return headers


# ------------------------------------------------------------------------------------------------ passwords
def test_password_strength_rules():
    assert service.password_problem("short") is not None
    assert service.password_problem("password1234") is not None            # common word + digits
    assert service.password_problem("aaaaaaaaaaaaaa") is not None          # one character
    assert service.password_problem("123456789012") is not None            # a sequence
    assert service.password_problem("someone@example.com") is not None     # an e-mail address
    assert service.password_problem("naif.najm2024", email="naif.najm@example.com") is not None
    assert service.password_problem(STRONG, email="naif@example.com") is None
    generated = service.generate_password()
    assert len(generated) == 23 and service.password_problem(generated) is None


# ------------------------------------------------------------------------------------------------ CLI
def test_cli_set_password_prompts_and_signs_out(client, db, auth, monkeypatch, capsys):
    answers = iter(["weak", STRONG, "something-else-entirely", STRONG, STRONG])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    user = db.get(User, auth.user_id)
    version = user.token_version
    assert cli.main(["set-password", auth.email]) == 0
    out, err = capsys.readouterr()
    assert STRONG not in out and STRONG not in err                       # never printed
    assert "at least 12 characters" in err and "different" in err
    assert user.token_version == version + 1 and user.email_verified
    assert client.get("/api/auth/me", headers=auth.headers).status_code == 401   # signed out everywhere
    assert _login(client, auth.email, STRONG).status_code == 200
    assert [e.type for e in _events(db, user.id, "cli.password_set")] == ["cli.password_set"]


def test_cli_set_password_generate_and_errors(client, db, auth, monkeypatch, capsys):
    assert cli.main(["set-password", auth.email, "--generate"]) == 0
    out = capsys.readouterr().out
    password = out.strip().rsplit(": ", 1)[-1]
    assert _login(client, auth.email, password).status_code == 200
    assert cli.main(["set-password", "ghost@example.com", "--generate"]) == 1
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "weak")
    assert cli.main(["set-password", auth.email]) == 2                     # three weak tries: nothing changes
    assert _login(client, auth.email, password).status_code == 200
    assert cli.main(["set-password", auth.email, "--password", STRONG]) == 0
    assert "shell history" in capsys.readouterr().err


def test_cli_superadmins_check_and_last_guard(db, monkeypatch, capsys):
    assert cli.main(["check"]) == 1
    assert "NOT OK" in capsys.readouterr().out
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": STRONG)
    assert cli.main(["create-superadmin", "boss@example.com", "--name", "Boss"]) == 0
    out = capsys.readouterr().out
    assert "Created superadmin boss@example.com" in out and STRONG not in out
    assert cli.main(["list-superadmins"]) == 0
    assert "boss@example.com" in capsys.readouterr().out
    assert cli.main(["check"]) == 0
    assert "OK: 1 active" in capsys.readouterr().out
    assert cli.main(["revoke-superadmin", "boss@example.com"]) == 3
    assert "last active" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------------ admin: access
ADMIN_CALLS = [
    ("get", "/api/admin/users"), ("get", "/api/admin/users/export.csv"), ("get", "/api/admin/users/{id}"),
    ("patch", "/api/admin/users/{id}"), ("post", "/api/admin/users/{id}/temporary-password"),
    ("post", "/api/admin/users/{id}/password-reset-email"), ("post", "/api/admin/users/{id}/sign-out"),
    ("post", "/api/admin/users/{id}/revoke-access"), ("post", "/api/admin/users/{id}/reset-2fa"),
    ("post", "/api/admin/users/{id}/active"), ("post", "/api/admin/users/{id}/superadmin"),
    ("post", "/api/admin/users/{id}/memberships"), ("patch", "/api/admin/users/{id}/memberships/1"),
    ("delete", "/api/admin/users/{id}/memberships/1"), ("post", "/api/admin/users/{id}/memberships/1/transfer"),
    ("post", "/api/admin/users/{id}/impersonate"), ("get", "/api/admin/users/{id}/export"),
    ("post", "/api/admin/users/{id}/delete"), ("post", "/api/admin/users/{id}/send-verification"),
]


def test_admin_user_endpoints_need_superadmin(client, auth):
    other = signup(client, email="other@example.com", workspace="Other")
    for method, path in ADMIN_CALLS:
        kwargs = {"json": {}} if method in ("post", "patch") else {}
        r = getattr(client, method)(path.format(id=other.user_id), headers=auth.headers, **kwargs)
        assert r.status_code == 403, path


def test_admin_list_filters_sort_and_csv(client, db, admin, auth):
    other = signup(client, email="zed@example.com", name="Zed", workspace="Zeta")
    db.get(User, other.user_id).is_active = False
    db.get(User, auth.user_id).email_verified = True
    db.flush()
    get = lambda **q: client.get("/api/admin/users", params=q, headers=admin.headers).json()  # noqa: E731
    assert get()["total"] == 3
    assert [u["email"] for u in get(q="zed")["items"]] == ["zed@example.com"]
    assert [u["email"] for u in get(status="disabled")["items"]] == ["zed@example.com"]
    assert [u["email"] for u in get(superadmin="true")["items"]] == ["root@example.com"]
    assert [u["email"] for u in get(verified="true")["items"]] == ["owner@example.com"]
    assert get(plan="trial")["total"] == 3 and get(plan="pro")["total"] == 0
    assert get(created_from="2000-01-01", created_to="2000-01-02")["total"] == 0
    assert get(login_from="2000-01-01")["total"] == 3
    assert [u["name"] for u in get(sort="name")["items"]] == ["Owner", "Root", "Zed"]
    assert get(q=str(other.user_id))["items"][0]["id"] == other.user_id
    csv = client.get("/api/admin/users/export.csv", params={"status": "active"}, headers=admin.headers)
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert "owner@example.com" in csv.text and "zed@example.com" not in csv.text
    assert db.scalar(select(UserEvent).where(UserEvent.type == "admin.users_export")).actor_id == admin.user_id


def test_admin_detail(client, db, admin, auth):
    from app.modules.connect.models import ApiKey
    from app.modules.support.models import SupportTicket
    db.add(ApiKey(workspace_id=auth.workspace_id, user_id=auth.user_id, name="Zapier", prefix="sk_stravica_ab",
                  key_hash="x" * 64, scopes=["read"], expires_at=service.utcnow() + timedelta(days=30)))
    db.add(SupportTicket(workspace_id=auth.workspace_id, user_id=auth.user_id, subject="Help"))
    db.flush()
    data = client.get(f"/api/admin/users/{auth.user_id}", headers=admin.headers).json()
    assert data["user"]["email"] == "owner@example.com"
    assert data["workspaces"][0] | {"name": "Acme", "role": "owner", "plan": "trial", "sole_owner": True} == \
        data["workspaces"][0]
    assert data["api_keys"][0]["name"] == "Zapier" and data["api_keys"][0]["workspace"] == "Acme"
    assert data["support_tickets"] == {"total": 1, "open": 1}
    assert [e["type"] for e in data["events"]] == []        # signing up is not a sign-in event
    assert data["delete_blockers"][0]["action"] == "delete"
    assert data["can_impersonate"] is True and data["last_superadmin"] is False
    assert client.get("/api/admin/users/999999", headers=admin.headers).status_code == 404
    me = client.get(f"/api/admin/users/{admin.user_id}", headers=admin.headers).json()
    assert me["last_superadmin"] is True and me["can_impersonate"] is False


# ------------------------------------------------------------------------------------------------ admin: profile
def test_admin_edit_profile_and_email(client, db, admin, auth):
    other = signup(client, email="taken@example.com", workspace="T")
    r = client.patch(f"/api/admin/users/{auth.user_id}", headers=admin.headers,
                     json={"name": "Sara", "locale": "nl", "email_verified": True})
    assert r.status_code == 200 and r.json()["name"] == "Sara" and r.json()["email_verified"] is True
    assert client.patch(f"/api/admin/users/{auth.user_id}", headers=admin.headers,
                        json={"email": "TAKEN@example.com"}).json()["code"] == "email_taken"
    sent = len(OUTBOX)
    r = client.patch(f"/api/admin/users/{auth.user_id}", headers=admin.headers, json={"email": " New@Example.com "})
    assert r.json()["email"] == "new@example.com" and r.json()["email_verified"] is False
    assert len(OUTBOX) == sent + 1 and OUTBOX[-1]["To"] == "new@example.com"
    token = OUTBOX[-1].get_body(("plain",)).get_content().strip().split("token=")[1]
    assert client.post("/api/auth/email/verify", json={"token": token}).status_code == 204
    assert db.get(User, auth.user_id).email_verified is True
    assert client.patch(f"/api/admin/users/{auth.user_id}", headers=admin.headers,
                        json={"locale": "xx"}).json()["code"] == "bad_locale"
    events = _events(db, auth.user_id, "admin.profile")
    assert len(events) == 2 and all(e.actor_id == admin.user_id for e in events)
    assert events[1].payload["changes"]["email"] == ["owner@example.com", "new@example.com"]
    assert db.get(User, other.user_id).email == "taken@example.com"


# ------------------------------------------------------------------------------------------------ admin: password
def test_temporary_password_forces_a_change(client, db, admin, auth):
    r = client.post(f"/api/admin/users/{auth.user_id}/temporary-password", headers=admin.headers)
    temporary = r.json()["password"]
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/api/auth/me", headers=auth.headers).status_code == 401       # signed out
    assert temporary not in json.dumps([e.payload for e in _events(db, auth.user_id)])
    login = _login(client, auth.email, temporary)
    assert login.json()["me"]["user"]["must_change_password"] is True
    headers = _bearer(login.json()["access_token"], auth.workspace_id)
    blocked = client.get("/api/workspace", headers=headers)
    assert blocked.status_code == 403 and blocked.json()["code"] == "password_change_required"
    assert client.post("/api/auth/password", headers=headers, json={
        "current_password": temporary, "new_password": temporary}).json()["code"] == "same_password"
    assert client.post("/api/auth/password", headers=headers, json={
        "current_password": temporary, "new_password": "password123"}).json()["code"] == "weak_password"
    changed = client.post("/api/auth/password", headers=headers,
                          json={"current_password": temporary, "new_password": STRONG})
    assert changed.status_code == 200 and changed.json()["me"]["user"]["must_change_password"] is False
    assert client.get("/api/workspace", headers=_bearer(changed.json()["access_token"], auth.workspace_id)).status_code == 200
    assert _events(db, auth.user_id, "admin.temporary_password")[0].actor_id == admin.user_id
    assert client.post(f"/api/admin/users/{admin.user_id}/temporary-password",
                       headers=admin.headers).json()["code"] == "self_action"


def test_admin_reset_email_sign_out_and_revoke_access(client, db, admin, auth):
    from app.modules.connect.models import ApiKey, OAuthClient, OAuthGrant
    sent = len(OUTBOX)
    assert client.post(f"/api/admin/users/{auth.user_id}/password-reset-email",
                       headers=admin.headers).status_code == 204
    assert len(OUTBOX) == sent + 1 and "reset-password?token=" in OUTBOX[-1].get_body(("plain",)).get_content()
    app_client = OAuthClient(client_id="https://claude.ai/x", client_name="Claude", redirect_uris=[])
    db.add(app_client)
    db.flush()
    db.add(OAuthGrant(client_pk=app_client.id, user_id=auth.user_id, workspace_id=auth.workspace_id,
                      scopes=["read"], resource="https://x/mcp"))
    db.add(ApiKey(workspace_id=auth.workspace_id, user_id=auth.user_id, name="Zap", prefix="sk_1", key_hash="y" * 64,
                  scopes=["read"], expires_at=service.utcnow() + timedelta(days=30)))
    db.flush()
    r = client.post(f"/api/admin/users/{auth.user_id}/revoke-access", headers=admin.headers)
    assert r.json() == {"api_keys": 1, "apps": 1}
    assert db.scalar(select(ApiKey).where(ApiKey.user_id == auth.user_id)).revoked_at is not None
    assert client.post(f"/api/admin/users/{auth.user_id}/sign-out", headers=admin.headers).status_code == 204
    assert client.get("/api/auth/me", headers=auth.headers).status_code == 401
    types = [e.type for e in _events(db, auth.user_id) if e.actor_id == admin.user_id]
    assert types == ["admin.password_reset_email", "admin.revoke_access", "admin.sign_out"]


# ------------------------------------------------------------------------------------------------ admin: rights
def test_superadmin_self_and_last_guards(client, db, admin, auth):
    from app.modules.users.admin import active_superadmins
    for what in ("active", "superadmin"):
        r = client.post(f"/api/admin/users/{admin.user_id}/{what}", json={"value": False}, headers=admin.headers)
        assert r.json()["code"] == "self_action"
    assert client.post(f"/api/admin/users/{auth.user_id}/superadmin", json={"value": True},
                       headers=admin.headers).json()["is_superadmin"] is True
    assert active_superadmins(db) == 2 and active_superadmins(db, exclude=admin.user_id) == 1
    # the new administrator signs in again (promotion signs out) and demotes the first one: one remains
    second = _login(client, auth.email, "secret123").json()["access_token"]
    assert client.post(f"/api/admin/users/{admin.user_id}/superadmin", json={"value": False},
                       headers=_bearer(second)).json()["is_superadmin"] is False
    assert client.get("/api/admin/users", headers=admin.headers).status_code == 401    # signed out by the change
    assert active_superadmins(db) == 1
    # the last one: neither the API (self) nor the CLI nor deleting the account removes it
    assert client.post(f"/api/admin/users/{auth.user_id}/active", json={"value": False},
                       headers=_bearer(second)).json()["code"] == "self_action"
    assert cli.main(["revoke-superadmin", auth.email]) == 3
    assert client.post("/api/account/delete", headers=_bearer(second), json={
        "password": "secret123", "confirm_email": auth.email}).json()["code"] == "last_superadmin"
    assert [e.type for e in _events(db, admin.user_id) if e.type.startswith("admin.")] == ["admin.superadmin_revoked"]
    assert _events(db, auth.user_id, "admin.superadmin_granted")[0].actor_id == admin.user_id


def test_disable_and_enable_user(client, db, admin, auth):
    r = client.post(f"/api/admin/users/{auth.user_id}/active", json={"value": False}, headers=admin.headers)
    assert r.json()["is_active"] is False
    assert client.get("/api/auth/me", headers=auth.headers).status_code == 401
    assert _login(client, auth.email, "secret123").status_code == 401
    assert client.post(f"/api/admin/users/{auth.user_id}/impersonate", headers=admin.headers).json()["code"] == \
        "inactive_user"
    client.post(f"/api/admin/users/{auth.user_id}/active", json={"value": True}, headers=admin.headers)
    assert _login(client, auth.email, "secret123").status_code == 200
    assert [e.type for e in _events(db, auth.user_id) if e.actor_id == admin.user_id] == ["admin.disabled",
                                                                                          "admin.enabled"]


# ------------------------------------------------------------------------------------------------ admin: memberships
def test_memberships_and_ownership(client, db, admin, auth):
    member = signup(client, email="member@example.com", workspace="Mine")
    base = f"/api/admin/users/{member.user_id}/memberships"
    r = client.post(base, headers=admin.headers, json={"workspace_id": auth.workspace_id, "role": "editor"})
    assert r.status_code == 201
    assert client.post(base, headers=admin.headers,
                       json={"workspace_id": auth.workspace_id}).json()["code"] == "already_member"
    assert client.patch(f"{base}/{auth.workspace_id}", headers=admin.headers,
                        json={"role": "admin"}).json()["role"] == "admin"
    # the owner of Acme is the only owner: cannot be demoted or removed
    owner_base = f"/api/admin/users/{auth.user_id}/memberships/{auth.workspace_id}"
    assert client.patch(owner_base, headers=admin.headers, json={"role": "editor"}).json()["code"] == "last_owner"
    assert client.delete(owner_base, headers=admin.headers).json()["code"] == "last_owner"
    others = client.get(f"/api/admin/users/{auth.user_id}/workspace-members/{auth.workspace_id}",
                        headers=admin.headers).json()
    assert [o["email"] for o in others] == ["member@example.com"]
    r = client.post(f"{owner_base}/transfer", headers=admin.headers, json={"to_user_id": member.user_id})
    assert r.status_code == 200
    roles = dict(db.execute(select(Membership.user_id, Membership.role).where(
        Membership.workspace_id == auth.workspace_id)).all())
    assert roles == {auth.user_id: Role.admin, member.user_id: Role.owner}
    assert client.delete(owner_base, headers=admin.headers).status_code == 204
    assert _events(db, auth.user_id, "admin.ownership_transferred")[0].actor_id == admin.user_id
    assert [e.type for e in _events(db, member.user_id) if e.type.startswith("admin.")] == [
        "admin.membership_added", "admin.membership_role", "admin.ownership_received"]


# ------------------------------------------------------------------------------------------------ admin: GDPR
def test_export_and_delete_user(client, db, admin, auth):
    from app.modules.billing.models import BillingEvent
    member = signup(client, email="member@example.com", workspace="Solo")
    client.post(f"/api/admin/users/{member.user_id}/memberships", headers=admin.headers,
                json={"workspace_id": auth.workspace_id, "role": "editor"})
    exported = client.get(f"/api/admin/users/{member.user_id}/export", headers=admin.headers)
    assert exported.status_code == 200 and "attachment" in exported.headers["content-disposition"]
    data = exported.json()
    assert data["profile"]["email"] == "member@example.com" and len(data["workspaces"]) == 2
    assert "password_hash" not in exported.text and "totp_secret" not in exported.text
    db.add(BillingEvent(provider="admin", event_id="keep-me", type="admin.plan", workspace_id=member.workspace_id,
                        actor_id=member.user_id))
    db.flush()
    url = f"/api/admin/users/{member.user_id}/delete"
    assert client.post(url, headers=admin.headers, json={"confirm_email": "nope"}).json()["code"] == "confirm_mismatch"
    blocked = client.post(url, headers=admin.headers, json={"confirm_email": "member@example.com"}).json()
    assert blocked["code"] == "sole_owner" and blocked["workspaces"][0]["action"] == "delete"
    r = client.post(url, headers=admin.headers, json={"confirm_email": "MEMBER@example.com",
                                                      "delete_workspaces": [member.workspace_id]})
    assert r.status_code == 204, r.text
    user = db.get(User, member.user_id)
    assert user.email == f"deleted-{user.id}@deleted.invalid" and user.deleted_at and not user.is_active
    assert user.password_hash is None and user.name != "Member"
    assert not db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    event = db.scalar(select(BillingEvent).where(BillingEvent.event_id == "keep-me"))
    assert event is not None and event.workspace_id is None                    # billing history stays
    assert _login(client, "member@example.com", "secret123").status_code == 401
    assert client.get("/api/admin/users", params={"status": "deleted"}, headers=admin.headers).json()["total"] == 1
    assert client.post(f"/api/admin/users/{member.user_id}/sign-out", headers=admin.headers).json()["code"] == \
        "deleted_user"
    assert _events(db, member.user_id, "admin.deleted")[0].actor_id == admin.user_id


def test_delete_refuses_workspace_with_other_members(client, db, admin, auth):
    member = signup(client, email="member@example.com", workspace="M")
    client.post(f"/api/admin/users/{member.user_id}/memberships", headers=admin.headers,
                json={"workspace_id": auth.workspace_id, "role": "editor"})
    r = client.post(f"/api/admin/users/{auth.user_id}/delete", headers=admin.headers,
                    json={"confirm_email": auth.email, "delete_workspaces": [auth.workspace_id]})
    assert r.json()["code"] == "sole_owner" and r.json()["workspaces"][0]["action"] == "transfer"
    assert db.get(User, auth.user_id).deleted_at is None


# ------------------------------------------------------------------------------------------------ view as
def test_impersonation(client, db, admin, auth):
    other_admin = signup(client, email="admin2@example.com", workspace="A2")
    db.get(User, other_admin.user_id).is_superadmin = True
    db.flush()
    assert client.post(f"/api/admin/users/{other_admin.user_id}/impersonate",
                       headers=admin.headers).json()["code"] == "cannot_impersonate"
    # sign in as the administrator with cookies (like the browser)
    _login(client, "root@example.com", "secret123")
    r = client.post(f"/api/admin/users/{auth.user_id}/impersonate")
    assert r.status_code == 200 and r.json()["me"]["user"]["email"] == auth.email
    assert "sai_imp_return" in client.cookies and "sai_refresh" not in client.cookies
    me = client.get("/api/auth/me").json()
    assert me["user"]["email"] == auth.email and me["impersonator"]["email"] == "root@example.com"
    assert me["impersonator"]["expires_at"]
    # the admin area is closed, and so are the person's credentials and anything that deletes
    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/auth/password", json={"current_password": "secret123",
                                                   "new_password": STRONG}).json()["code"] == "impersonation_forbidden"
    assert client.post("/api/auth/email", json={"email": "x@example.com", "password": "secret123"}).status_code == 403
    assert client.post("/api/account/2fa/setup", json={"password": "secret123"}).status_code == 403
    assert client.get("/api/account/export").status_code == 403
    assert client.delete("/api/workspace/invitations/1").json()["code"] == "impersonation_forbidden"
    # changes are possible and recorded with the administrator's name
    assert client.patch("/api/workspace", json={"name": "Acme 2"}, headers={"X-Workspace": str(auth.workspace_id)}
                        ).status_code == 200
    action = _events(db, auth.user_id, "impersonation.action")[0]
    assert action.impersonator_id == admin.user_id and action.summary == "PATCH /api/workspace"
    # end: back to the administrator
    assert client.post("/api/auth/impersonation/end").json() == {"restored": True}
    me = client.get("/api/auth/me").json()
    assert me["user"]["email"] == "root@example.com" and me["impersonator"] is None
    types = [e.type for e in _events(db, auth.user_id) if e.type.startswith("impersonation")]
    assert types == ["impersonation.start", "impersonation.action", "impersonation.end"]


def test_impersonation_token_limits(client, db, admin, auth):
    from app.core import security
    token = security.create_impersonation_token(auth.user_id, 1, admin.user_id, 1)
    assert security.decode_token(token, "access")["imp"] == admin.user_id
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=_bearer(token)).json()["impersonator"]["id"] == admin.user_id
    expired = security._encode({"sub": str(auth.user_id), "typ": "access", "ver": 1, "imp": admin.user_id,
                                "imp_ver": 1}, timedelta(seconds=-5))
    assert client.get("/api/auth/me", headers=_bearer(expired)).status_code == 401
    db.get(User, admin.user_id).is_superadmin = False     # no longer an administrator: the view ends
    db.flush()
    assert client.get("/api/auth/me", headers=_bearer(token)).status_code == 401
    db.get(User, admin.user_id).is_superadmin = True
    db.get(User, admin.user_id).token_version += 1         # the administrator signed out everywhere
    db.flush()
    assert client.get("/api/auth/me", headers=_bearer(token)).status_code == 401


def test_impersonation_ends_on_logout(client, db, admin, auth):
    _login(client, "root@example.com", "secret123")
    client.post(f"/api/admin/users/{auth.user_id}/impersonate")
    assert client.post("/api/auth/logout").status_code == 204
    assert "sai_imp_return" not in client.cookies and "sai_access" not in client.cookies
    assert _events(db, auth.user_id, "impersonation.end")[0].actor_id == admin.user_id


# ------------------------------------------------------------------------------------------------ two-step sign-in
def _enable_2fa(client, headers):
    setup = client.post("/api/account/2fa/setup", headers=headers, json={"password": "secret123"}).json()
    assert setup["uri"].startswith("otpauth://totp/") and f"secret={setup['secret']}" in setup["uri"]
    r = client.post("/api/account/2fa/enable", headers=headers, json={"code": service.totp_now(setup["secret"])})
    assert r.status_code == 200, r.text
    return setup["secret"], r.json()["recovery_codes"]


def test_two_factor_setup_login_recovery_and_admin_reset(client, db, admin, auth):
    assert client.post("/api/account/2fa/setup", headers=auth.headers,
                       json={"password": "wrong"}).json()["code"] == "bad_password"
    secret, codes = _enable_2fa(client, auth.headers)
    assert len(codes) == 10 and db.get(User, auth.user_id).totp_secret == secret
    from sqlalchemy import text
    raw = db.execute(text("SELECT totp_secret FROM users WHERE id = :id"), {"id": auth.user_id}).scalar()
    assert raw != secret                                                        # encrypted at rest
    challenge = _login(client, auth.email, "secret123").json()
    assert challenge["two_factor_required"] is True and "access_token" not in challenge
    assert client.post("/api/auth/login/2fa", json={"challenge": challenge["challenge"],
                                                    "code": "000000"}).json()["code"] == "bad_code"
    already = service.totp_now(secret)                     # used to enable: refused (a code works once)
    assert client.post("/api/auth/login/2fa", json={"challenge": challenge["challenge"],
                                                    "code": already}).status_code == 401
    ok = client.post("/api/auth/login/2fa", json={"challenge": challenge["challenge"],
                                                  "code": service.totp_now(secret, time.time() + 30)})
    assert ok.status_code == 200 and ok.json()["me"]["user"]["totp_enabled"] is True
    # a recovery code works once
    challenge = _login(client, auth.email, "secret123").json()["challenge"]
    assert client.post("/api/auth/login/2fa", json={"challenge": challenge, "code": codes[0]}).status_code == 200
    challenge = _login(client, auth.email, "secret123").json()["challenge"]
    assert client.post("/api/auth/login/2fa", json={"challenge": challenge, "code": codes[0]}).status_code == 401
    security = client.get("/api/account/security", headers=_bearer(ok.json()["access_token"])).json()
    assert security["totp_enabled"] and security["recovery_codes_left"] == 9
    assert security["sign_ins"][0]["how"] == "password+2fa"
    # the administrator resets it (lost phone): signed out, plain password sign-in again
    assert client.post(f"/api/admin/users/{auth.user_id}/reset-2fa", headers=admin.headers).status_code == 204
    assert _login(client, auth.email, "secret123").json()["me"]["user"]["totp_enabled"] is False
    assert _events(db, auth.user_id, "admin.reset_2fa")[0].actor_id == admin.user_id


def test_two_factor_disable_and_new_codes(client, db, auth):
    secret, codes = _enable_2fa(client, auth.headers)
    r = client.post("/api/account/2fa/recovery-codes", headers=auth.headers, json={"password": "secret123",
                                                                                 "code": codes[1]})
    new_codes = r.json()["recovery_codes"]
    assert len(new_codes) == 10 and not set(new_codes) & set(codes)
    assert client.post("/api/account/2fa/disable", headers=auth.headers,
                       json={"password": "secret123", "code": codes[2]}).json()["code"] == "bad_code"
    assert client.post("/api/account/2fa/disable", headers=auth.headers,
                       json={"password": "secret123", "code": new_codes[0]}).status_code == 204
    assert db.get(User, auth.user_id).totp_secret is None
    assert secret


# ------------------------------------------------------------------------------------------------ account center
def test_account_security_workspaces_and_prefs(client, db, auth):
    _login(client, auth.email, "secret123")
    security = client.get("/api/account/security", headers=auth.headers).json()
    assert security["sign_ins"] and security["totp_enabled"] is False and security["email_verified"] is False
    other = signup(client, email="boss@example.com", workspace="Boss Co")
    db.add(Membership(user_id=auth.user_id, workspace_id=other.workspace_id, role=Role.editor))
    db.flush()
    mine = client.get("/api/account/workspaces", headers=auth.headers).json()
    assert {(w["name"], w["role"], w["sole_owner"]) for w in mine} == {("Acme", "owner", True),
                                                                     ("Boss Co", "editor", False)}
    assert client.post(f"/api/account/workspaces/{auth.workspace_id}/leave",
                       headers=auth.headers).json()["code"] == "last_owner"
    assert client.post(f"/api/account/workspaces/{other.workspace_id}/leave", headers=auth.headers).status_code == 204
    assert client.get("/api/account/notifications", headers=auth.headers).json() == {"email_security": True,
                                                                                    "email_product": True}
    client.put("/api/account/notifications", headers=auth.headers, json={"email_security": False,
                                                                       "email_product": True})
    assert db.get(User, auth.user_id).notification_prefs == {"email_security": False, "email_product": True}
    sent = len(OUTBOX)
    changed = client.post("/api/auth/password", headers=auth.headers,
                          json={"current_password": "secret123", "new_password": STRONG})
    assert changed.status_code == 200 and len(OUTBOX) == sent                  # security e-mails turned off
    assert client.patch("/api/auth/me", headers=_bearer(changed.json()["access_token"]),
                        json={"timezone": "Mars/Base"}).json()["code"] == "bad_timezone"


def test_account_email_change_and_verification(client, db, auth):
    assert client.post("/api/auth/email", headers=auth.headers, json={"email": "new@example.com",
                                                                      "password": "nope"}).json()["code"] == "bad_password"
    sent = len(OUTBOX)
    r = client.post("/api/auth/email", headers=auth.headers, json={"email": "New@example.com", "password": "secret123"})
    assert r.json()["user"]["email"] == "new@example.com" and r.json()["user"]["email_verified"] is False
    assert [m["To"] for m in OUTBOX[sent:]] == ["owner@example.com", "new@example.com"]   # old address told
    assert client.post("/api/auth/email/verify", json={"token": "bogus"}).json()["code"] == "bad_token"
    token = OUTBOX[-1].get_body(("plain",)).get_content().strip().split("token=")[1]
    assert client.post("/api/auth/email/verify", json={"token": token}).status_code == 204
    assert db.get(User, auth.user_id).email_verified
    assert client.post("/api/auth/email/verify-request", headers=auth.headers).status_code == 204


def test_account_avatar(client, db, auth):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (600, 400), "red").save(buffer, "JPEG")
    r = client.post("/api/account/avatar", headers=auth.headers, files={"file": ("me.jpg", buffer.getvalue(),
                                                                                  "image/jpeg")})
    url = r.json()["avatar_url"]
    assert re.fullmatch(r"/api/account/avatars/\d+-[\w-]+\.png", url)
    image = client.get(url)
    assert image.status_code == 200 and Image.open(io.BytesIO(image.content)).size == (256, 256)
    assert client.post("/api/account/avatar", headers=auth.headers,
                       files={"file": ("x.png", b"not an image", "image/png")}).json()["code"] == "bad_image"
    assert client.patch("/api/auth/me", headers=auth.headers, json={"avatar_url": None}).json()["user"]["avatar_url"] is None
    assert client.get(url).status_code == 404
    assert client.get("/api/account/avatars/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_account_export_and_delete(client, db, auth):
    data = client.get("/api/account/export", headers=auth.headers).json()
    assert data["profile"]["email"] == auth.email and data["workspaces"][0]["name"] == "Acme"
    check = client.get("/api/account/delete-check", headers=auth.headers).json()
    assert check["workspaces"][0]["action"] == "delete"
    body = {"password": "secret123", "confirm_email": auth.email}
    assert client.post("/api/account/delete", headers=auth.headers,
                       json={**body, "confirm_email": "x@y.z"}).json()["code"] == "confirm_mismatch"
    assert client.post("/api/account/delete", headers=auth.headers, json=body).json()["code"] == "sole_owner"
    assert client.post("/api/account/delete", headers=auth.headers,
                       json={**body, "delete_workspaces": [auth.workspace_id]}).status_code == 204
    assert db.get(User, auth.user_id).deleted_at is not None
    assert client.get("/api/auth/me", headers=auth.headers).status_code == 401


def test_every_accounts_message_is_translated_to_arabic():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "app"
    catalog = {}
    for path in [root / "i18n" / "ar.json", *sorted(root.glob("modules/*/i18n/ar.json"))]:
        catalog.update(json.loads(path.read_text(encoding="utf-8")))
    pattern = re.compile(r'''(?:\b_|lazy)\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')''')
    files = [*(root / "modules" / "users").glob("*.py"), *(root / "modules" / "auth").glob("*.py"),
             root / "core" / "deps.py"]
    messages = {a or b for path in files for a, b in pattern.findall(path.read_text(encoding="utf-8"))}
    assert not sorted(messages - set(catalog))
