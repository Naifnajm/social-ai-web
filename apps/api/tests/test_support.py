"""Support: failures carry a reference, people open tickets, the platform team answers."""
from sqlalchemy import select

from app.core.errors import ApiError
from app.core.models import ApiLog, ErrorEvent, Notification
from app.modules.auth.models import User
from app.modules.support.models import SupportTicket
from tests.conftest import signup


def _superadmin(client, db):
    admin = signup(client, email="root@example.com", name="Root", workspace="Platform")
    db.get(User, admin.user_id).is_superadmin = True
    db.flush()
    return admin


def _break(monkeypatch, exc):
    """Make ``GET /api/notifications`` fail the way a bug or a network would."""
    from app.modules.notifications import router as notifications

    def boom(*args, **kwargs):
        raise exc
    monkeypatch.setattr(notifications, "select", boom)


def test_an_unexpected_error_gets_a_reference_and_is_stored(client, auth, db, monkeypatch):
    _break(monkeypatch, RuntimeError("database exploded at 10.0.0.5"))
    r = client.get("/api/notifications", headers={**auth.headers, "Accept-Language": "en"})
    assert r.status_code == 500
    body = r.json()
    assert body["code"] == "server_error" and len(body["ref"]) == 8 and body["ref"] in body["detail"]
    assert r.headers["X-Request-ID"] == body["ref"]
    assert "exploded" not in r.text and "10.0.0.5" not in r.text  # the person never sees internals
    event = db.scalar(select(ErrorEvent).where(ErrorEvent.ref == body["ref"]))
    assert (event.status, event.path, event.user_id, event.workspace_id) == (
        500, "/api/notifications", auth.user_id, auth.workspace_id)
    assert "RuntimeError" in event.message and "Traceback" in event.detail


def test_the_message_is_in_the_language_of_the_person(client, auth, monkeypatch):
    _break(monkeypatch, RuntimeError("x"))
    r = client.get("/api/notifications", headers={**auth.headers, "Accept-Language": "ar"})
    assert "حدث خلل من جهتنا" in r.json()["detail"]


def test_a_failed_network_call_keeps_its_own_message_and_gets_a_reference(client, auth, db, monkeypatch):
    _break(monkeypatch, ApiError("Instagram: the token has expired."))
    r = client.get("/api/notifications", headers=auth.headers)
    assert r.status_code == 502 and r.json()["detail"] == "Instagram: the token has expired."
    assert db.scalar(select(ErrorEvent.code).where(ErrorEvent.ref == r.json()["ref"])) == "external_api"


def test_ticket_from_an_error_then_the_team_answers(client, auth, db, monkeypatch):
    admin = _superadmin(client, db)
    _break(monkeypatch, RuntimeError("boom"))
    ref = client.get("/api/notifications", headers=auth.headers).json()["ref"]
    monkeypatch.undo()
    db.add(ApiLog(workspace_id=auth.workspace_id, service="social", operation="Instagram: Publish post",
                  method="POST", endpoint="https://graph.facebook.com/x", status_code=400, error="Invalid token"))
    db.flush()

    r = client.post("/api/support/tickets", headers=auth.headers, json={
        "subject": "Publishing failed", "body": "I pressed publish and got an error.", "error_ref": ref.lower(),
        "context": {"code": "server_error", "page": "/en/studio", "secret": "must be dropped", "status": 500}})
    assert r.status_code == 201, r.text
    ticket = r.json()
    assert ticket["status"] == "open" and ticket["error_ref"] == ref and len(ticket["messages"]) == 1
    # the platform team is told, with a link to the ticket
    note = db.scalar(select(Notification).where(Notification.user_id == admin.user_id,
                                                Notification.kind == "support.ticket"))
    assert note.link == f"/admin/support?ticket={ticket['id']}"

    # only platform administrators see the admin side
    assert client.get("/api/admin/support/tickets", headers=auth.headers).status_code == 403
    page = client.get("/api/admin/support/tickets?status=open", headers=admin.headers).json()
    assert page["total"] == 1 and page["counts"] == {"open": 1, "answered": 0, "closed": 0}
    assert page["items"][0]["workspace"] == "Acme" and page["items"][0]["email"] == auth.email

    detail = client.get(f"/api/admin/support/tickets/{ticket['id']}", headers=admin.headers).json()
    assert detail["context"] == {"code": "server_error", "status": "500", "page": "/en/studio"}
    assert detail["error"]["path"] == "/api/notifications" and "Traceback" in detail["error"]["detail"]
    assert detail["failed_calls"][0]["operation"] == "Instagram: Publish post"

    r = client.post(f"/api/admin/support/tickets/{ticket['id']}/messages", headers=admin.headers,
                    json={"body": "Reconnect Instagram, the token expired."})
    assert r.json()["status"] == "answered" and r.json()["messages"][-1]["staff"] is True
    note = db.scalar(select(Notification).where(Notification.user_id == auth.user_id,
                                                Notification.kind == "support.reply"))
    assert note.link == f"/settings/support?ticket={ticket['id']}"

    mine = client.get("/api/support/tickets", headers=auth.headers).json()
    assert mine[0]["unread"] is True and mine[0]["status"] == "answered"
    opened = client.get(f"/api/support/tickets/{ticket['id']}", headers=auth.headers).json()
    assert opened["messages"][-1]["author"] is None  # the team answers as "Support", not by name
    assert client.get("/api/support/tickets", headers=auth.headers).json()[0]["unread"] is False

    # answering again reopens it; the person can close it
    r = client.post(f"/api/support/tickets/{ticket['id']}/messages", headers=auth.headers, json={"body": "Thanks!"})
    assert r.json()["status"] == "open"
    assert client.post(f"/api/support/tickets/{ticket['id']}/close", headers=auth.headers).json()["status"] == "closed"
    assert client.post(f"/api/admin/support/tickets/{ticket['id']}/status", headers=admin.headers,
                       json={"status": "nonsense"}).status_code == 400

    errors = client.get("/api/admin/support/errors", headers=admin.headers).json()
    assert errors[0]["ref"] == ref and errors[0]["ticket_id"] == ticket["id"] and errors[0]["detail"] is None
    assert "Traceback" in client.get(f"/api/admin/support/errors?ref={ref}", headers=admin.headers).json()[0]["detail"]


def test_tickets_stay_inside_the_workspace_and_with_their_author(client, auth, db):
    other = signup(client, email="other@example.com", name="Other", workspace="Other Co")
    r = client.post("/api/support/tickets", headers=auth.headers, json={"subject": "Question", "body": "Hello",
                                                                         "category": "question"})
    ticket_id = r.json()["id"]
    assert client.get(f"/api/support/tickets/{ticket_id}", headers=other.headers).status_code == 404
    assert client.get("/api/support/tickets", headers=other.headers).json() == []
    assert client.post(f"/api/support/tickets/{ticket_id}/messages", headers=other.headers,
                       json={"body": "x"}).status_code == 404
    assert db.get(SupportTicket, ticket_id).category == "question"


def test_the_team_can_send_a_test_error(client, auth, db):
    admin = _superadmin(client, db)
    assert client.post("/api/admin/support/test-error", headers=auth.headers).status_code == 403
    r = client.post("/api/admin/support/test-error", headers=admin.headers)
    assert r.status_code == 500 and r.json()["code"] == "server_error"
    assert client.get("/api/admin/support/errors", headers=admin.headers).json()[0]["ref"] == r.json()["ref"]

