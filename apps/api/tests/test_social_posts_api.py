"""Posts API: composer, list filters, approvals flow, tenant isolation."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.db import utcnow
from app.core.models import Notification
from app.modules.social.models import Post
from tests.conftest import signup
from tests.social_common import account, image, jobs_in_test_session  # noqa: F401


def _member(client, owner, email, role):
    from app.core.mail import OUTBOX
    user = signup(client, email=email, workspace=f"{email} ws")
    client.post("/api/workspace/invitations", json={"email": email, "role": role}, headers=owner.headers)
    token = OUTBOX[-1].get_body(("plain",)).get_content().strip().rsplit("/", 1)[-1]
    assert client.post(f"/api/invitations/{token}/accept", headers=user.headers).status_code == 200
    user.workspace_id = owner.workspace_id
    return user


def test_compose_draft_publish_and_list(client, auth, db, mock_http):
    fb = account(db, auth.workspace_id, "facebook")
    media = image(db, auth.workspace_id)
    r = client.post("/api/posts/compose", json={"content": "Hello\nworld", "account_ids": [fb.id],
                                                "media_ids": [media.id]}, headers=auth.headers)
    assert r.status_code == 200, r.text
    post = r.json()
    assert post["state"] == "draft" and post["name"] == "Hello" and post["media"][0]["id"] == media.id

    mock_http(lambda m, u, k: mock_http.response(200, {"id": "ph", "post_id": "111_7"}))
    r = client.post("/api/posts/compose", json={"post_id": post["id"], "content": "Hello again", "action": "publish"},
                    headers=auth.headers)
    data = r.json()
    assert data["state"] == "posted" and data["targets"][0]["external_url"] == "https://www.facebook.com/111_7"
    assert not data["can_edit"]
    assert client.patch(f"/api/posts/{post['id']}", json={"content": "x"}, headers=auth.headers).status_code == 400
    assert client.delete(f"/api/posts/{post['id']}", headers=auth.headers).status_code == 400

    client.post("/api/posts", json={"content": "Draft two", "account_ids": [fb.id]}, headers=auth.headers)
    page = client.get("/api/posts?state=draft", headers=auth.headers).json()
    assert page["total"] == 1 and page["items"][0]["content"] == "Draft two"
    assert client.get("/api/posts?platform=facebook", headers=auth.headers).json()["total"] == 2
    assert client.get("/api/posts?q=again", headers=auth.headers).json()["total"] == 1
    studio = client.get("/api/studio", headers=auth.headers).json()
    assert studio["kpis"]["published"] == 1 and studio["rules"]["x"]["max_chars"] == 280
    assert not studio["needs_approval"] and studio["can_connect"]


def test_validate_endpoint_saves_nothing(client, auth, db):
    x = account(db, auth.workspace_id, "x")
    r = client.post("/api/posts/validate", json={"content": "a" * 300, "account_ids": [x.id]}, headers=auth.headers)
    data = r.json()
    assert not data["ok"] and data["problems"][0]["platform"] == "x"
    assert db.scalar(select(Post).where(Post.workspace_id == auth.workspace_id)) is None
    r = client.post("/api/posts/compose", json={"content": "a" * 300, "account_ids": [x.id], "action": "publish"},
                    headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "invalid_post" and r.json()["problems"]


def test_schedule_best_time_and_unschedule_via_api(client, auth, db):
    fb = account(db, auth.workspace_id, "facebook")
    when = (utcnow() + timedelta(days=2)).isoformat()
    post = client.post("/api/posts/compose", json={"content": "Later", "account_ids": [fb.id], "action": "schedule",
                                                   "when": when}, headers=auth.headers).json()
    assert post["state"] == "scheduled" and post["scheduled_at"]
    post = client.post(f"/api/posts/{post['id']}/submit", json={"action": "draft"}, headers=auth.headers).json()
    assert post["state"] == "draft"
    post = client.post(f"/api/posts/{post['id']}/submit", json={"action": "best_time"}, headers=auth.headers).json()
    assert post["state"] == "scheduled"
    slots = client.get("/api/posts/best-slots?platforms=facebook&count=2", headers=auth.headers).json()
    assert len(slots) == 2 and slots[0]["label"]


def test_approval_flow(client, auth, db, mock_http):
    fb = account(db, auth.workspace_id, "facebook")
    editor = _member(client, auth, "editor@example.com", "editor")
    approver = _member(client, auth, "approver@example.com", "approver")
    assert client.put("/api/approvals/settings", json={"required": True}, headers=editor.headers).status_code == 403
    assert client.put("/api/approvals/settings", json={"required": True}, headers=auth.headers).json()["required"]
    assert client.get("/api/studio", headers=editor.headers).json()["needs_approval"]

    mock_http(lambda m, u, k: pytest.fail("nothing is published before approval"))
    post = client.post("/api/posts/compose", json={"content": "Please approve", "account_ids": [fb.id],
                                                   "action": "publish"}, headers=editor.headers).json()
    assert post["state"] == "to_approve" and post["requested_action"] == "publish"
    assert post["approval_requested_by_name"]
    notes = db.scalars(select(Notification).where(Notification.kind == "post.approval")).all()
    assert {n.user_id for n in notes} == {auth.user_id, approver.user_id}  # approvers and up, not the editor

    assert client.get("/api/approvals", headers=editor.headers).status_code == 403
    queue = client.get("/api/approvals", headers=approver.headers).json()
    assert [p["id"] for p in queue] == [post["id"]]
    assert client.post(f"/api/posts/{post['id']}/approve", headers=editor.headers).status_code == 403

    # request changes → back to draft, the editor is told
    r = client.post(f"/api/posts/{post['id']}/request-changes", json={"note": "Shorter please"},
                    headers=approver.headers).json()
    assert r["state"] == "draft" and r["approval_note"] == "Shorter please"
    assert db.scalar(select(Notification).where(Notification.kind == "post.changes_requested",
                                                Notification.user_id == editor.user_id))

    # schedule → to approve → approved → scheduled at the planned time
    when = (utcnow() + timedelta(days=1)).isoformat()
    r = client.post(f"/api/posts/{post['id']}/submit", json={"action": "schedule", "when": when},
                    headers=editor.headers).json()
    assert r["state"] == "to_approve" and r["requested_action"] == "schedule"
    r = client.post(f"/api/posts/{post['id']}/approve", headers=approver.headers).json()
    assert r["state"] == "scheduled" and r["approved_by_id"] == approver.user_id

    # an editor changing an approved scheduled post withdraws the approval
    r = client.patch(f"/api/posts/{post['id']}", json={"content": "Changed after approval"},
                     headers=editor.headers).json()
    assert r["state"] == "to_approve" and r["approved_by_id"] is None

    # approve a "publish now" request → published
    client.post(f"/api/posts/{post['id']}/submit", json={"action": "draft"}, headers=editor.headers)
    client.post(f"/api/posts/{post['id']}/submit", json={"action": "publish"}, headers=editor.headers)
    mock_http(lambda m, u, k: mock_http.response(200, {"id": "111_1"}))
    r = client.post(f"/api/posts/{post['id']}/approve", headers=approver.headers).json()
    assert r["state"] == "posted"
    assert db.scalar(select(Notification).where(Notification.kind == "post.approved",
                                                Notification.user_id == editor.user_id))

    # approvers (and admins) publish directly
    mock_http(lambda m, u, k: mock_http.response(200, {"id": "111_2"}))
    direct = client.post("/api/posts/compose", json={"content": "Direct", "account_ids": [fb.id],
                                                     "action": "publish"}, headers=approver.headers).json()
    assert direct["state"] == "posted"


def test_viewers_cannot_write(client, auth, db):
    fb = account(db, auth.workspace_id, "facebook")
    viewer = _member(client, auth, "viewer@example.com", "viewer")
    assert client.get("/api/posts", headers=viewer.headers).status_code == 200
    assert client.post("/api/posts", json={"content": "x", "account_ids": [fb.id]},
                       headers=viewer.headers).status_code == 403


def test_posts_are_isolated_between_workspaces(client, db):
    a = signup(client, email="xa@example.com", workspace="XA")
    b = signup(client, email="xb@example.com", workspace="XB")
    fb_b = account(db, b.workspace_id, "facebook")
    media_b = image(db, b.workspace_id)
    post_b = client.post("/api/posts", json={"content": "B secret", "account_ids": [fb_b.id]},
                         headers=b.headers).json()
    assert client.get("/api/posts", headers=a.headers).json()["total"] == 0
    for method, path, body in (("get", "", None), ("patch", "", {"content": "hack"}), ("delete", "", None),
                               ("post", "/submit", {"action": "publish"}), ("post", "/retry", None),
                               ("post", "/duplicate", None), ("post", "/approve", None)):
        kwargs = {"json": body} if body is not None else {}
        r = getattr(client, method)(f"/api/posts/{post_b['id']}{path}", headers=a.headers, **kwargs)
        assert r.status_code == 404, (method, path, r.text)
    # A cannot attach B's accounts or media to its own posts
    assert client.post("/api/posts", json={"content": "x", "account_ids": [fb_b.id]},
                       headers=a.headers).status_code == 404
    assert client.post("/api/posts", json={"content": "x", "media_ids": [media_b.id]},
                       headers=a.headers).status_code == 404
    assert client.post("/api/posts/compose", json={"post_id": post_b["id"], "content": "hack"},
                       headers=a.headers).status_code == 404
    assert client.get(f"/api/posts/{post_b['id']}", headers=b.headers).json()["content"] == "B secret"
    assert client.get("/api/analytics/dashboard", headers=a.headers).json()["kpis"]["posts"] == 0
    assert client.get(f"/api/analytics/dashboard?account_id={fb_b.id}", headers=a.headers).status_code == 404
