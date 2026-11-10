"""Scheduled performance reports: dates, numbers, HTML (RTL) / PDF rendering, e-mail sending, isolation."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import AppError
from app.core.mail import OUTBOX
from app.modules.ai import service as ai
from app.modules.links import service as links
from app.modules.reports import service as reports
from app.modules.reports.models import ReportSchedule
from app.modules.workspaces.models import Membership, Workspace
from tests.conftest import signup
from tests.planning_fakes import make_account, make_media, make_post, publish

UTC = timezone.utc


@pytest.fixture()
def data(client, auth, db):
    workspace = db.get(Workspace, auth.workspace_id)
    workspace.timezone = "UTC"
    fb = make_account(db, auth.workspace_id, "facebook", "Cafe Page", followers=1200)
    ig = make_account(db, auth.workspace_id, "instagram", "Cafe IG", followers=800)
    photo = make_media(db, auth.workspace_id)
    post = make_post(db, auth.workspace_id, [fb, ig], name="Autumn sale", content="Visit https://shop.example.com",
                     media=[photo])
    publish(db, post, when=datetime.now(UTC) - timedelta(days=2), impressions=300, engagements=24, likes=20,
            engagement_rate=8.0)
    link = links.link_for(db, post, fb, "https://shop.example.com")
    links.register_click(db, link, "9.9.9.9", "Mozilla/5.0 (Macintosh)")
    links.record_conversion(db, auth.workspace_id, code=link.code, value=150, external_id="O-1")
    return {"workspace": workspace, "fb": fb, "ig": ig, "post": post}


def schedule_json(**values):
    return {"name": "Weekly results", "recipients": ["boss@example.com", "Team@Example.com"], "frequency": "weekly",
            "weekday": 0, "hour": 8, "period": "last_7", "language": "en", **values}


def test_next_occurrence_and_period():
    schedule = ReportSchedule(frequency="weekly", weekday=0, month_day=1, hour=8)
    tz = ZoneInfo("UTC")
    wednesday = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    assert reports.next_occurrence(schedule, wednesday, tz) == datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
    assert reports.next_occurrence(schedule, datetime(2026, 11, 9, 7, 59, tzinfo=UTC), tz) == \
        datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
    assert reports.next_occurrence(schedule, datetime(2026, 11, 9, 8, 0, tzinfo=UTC), tz) == \
        datetime(2026, 11, 16, 8, 0, tzinfo=UTC)
    schedule.frequency, schedule.month_day = "monthly", 5
    assert reports.next_occurrence(schedule, wednesday, tz) == datetime(2026, 11, 5, 8, 0, tzinfo=UTC)
    assert reports.next_occurrence(schedule, datetime(2026, 11, 20, tzinfo=UTC), tz) == \
        datetime(2026, 12, 5, 8, 0, tzinfo=UTC)
    assert reports.next_occurrence(schedule, datetime(2026, 12, 20, tzinfo=UTC), tz) == \
        datetime(2027, 1, 5, 8, 0, tzinfo=UTC)
    riyadh = ZoneInfo("Asia/Riyadh")  # 08:00 local = 05:00 UTC
    assert reports.next_occurrence(schedule, wednesday, riyadh) == datetime(2026, 11, 5, 5, 0, tzinfo=UTC)
    assert reports.period_range("prev_month", wednesday, tz) == \
        (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC))
    assert reports.period_range("last_7", wednesday, tz) == \
        (datetime(2026, 10, 28, tzinfo=UTC), datetime(2026, 11, 4, tzinfo=UTC))


def test_report_values_numbers(client, auth, db, data):
    tomorrow = datetime.now(UTC) + timedelta(days=1)  # today's clicks and sales are in "the last 7 days"
    values = reports.report_values(db, data["workspace"], period="last_7", language="en", now=tomorrow)
    kpis = {k["key"]: k["value"] for k in values["kpis"]}
    assert kpis["posts"] == "1" and kpis["impressions"] == "600" and kpis["engagements"] == "48"
    assert kpis["link_clicks"] == "1" and kpis["revenue"] == "150 SAR" and kpis["followers"] == "2,000"
    assert values["direction"] == "ltr" and values["show_revenue"]
    assert {n["platform"] for n in values["networks"]} == {"facebook", "instagram"}
    assert values["top_posts"][0]["name"] == "Autumn sale"
    assert values["top_posts"][0]["image"].startswith("data:image/jpeg;base64,")
    assert values["top_results"][0]["revenue"] == "150 SAR"
    assert len(values["best"]) == 3 and values["ai_text"] is None
    only_ig = reports.report_values(db, data["workspace"], language="en", account_ids=[data["ig"].id], now=tomorrow)
    assert {k["key"]: k["value"] for k in only_ig["kpis"]}["impressions"] == "300"
    assert only_ig["networks_label"] == "Cafe IG"


def test_report_rtl_and_ai(client, auth, db, data, monkeypatch):
    def broken(*args, **kwargs):
        raise AppError("quota", code="quota")

    monkeypatch.setattr(ai, "generate_text", broken)
    values = reports.report_values(db, data["workspace"], language="ar", include_ai=True)
    assert values["ai_text"] is None, "an AI failure never blocks the report"
    monkeypatch.setattr(ai, "generate_text", lambda *a, **k: "• انشر **فيديو** قصير يوم الأربعاء")
    values = reports.report_values(db, data["workspace"], language="ar", include_ai=True)
    assert values["direction"] == "rtl" and values["ai_text"] == "• انشر فيديو قصير يوم الأربعاء"
    html = reports.render("report.html", values)
    assert 'dir="rtl"' in html and "الأرقام الرئيسية" in html and "فيديو" in html
    assert "Key numbers" in reports.render("report.html", reports.report_values(db, data["workspace"], language="en"))


def test_schedule_api_send_now_and_preview(client, auth, db, data):
    r = client.post("/api/reports/schedules", json=schedule_json(account_ids=[data["fb"].id]), headers=auth.headers)
    assert r.status_code == 201, r.text
    schedule = r.json()
    assert schedule["recipients"] == ["boss@example.com", "team@example.com"]
    assert schedule["next_send_at"] > datetime.now(UTC).isoformat()
    assert client.post("/api/reports/schedules", json=schedule_json(month_day=31),
                       headers=auth.headers).status_code == 422
    assert client.post("/api/reports/schedules", json=schedule_json(recipients=["nope"]),
                       headers=auth.headers).status_code == 422

    preview = client.get(f"/api/reports/schedules/{schedule['id']}/preview", headers=auth.headers)
    assert preview.status_code == 200 and preview.headers["content-type"].startswith("text/html")
    assert "Autumn sale" in preview.text and "Link clicks" in preview.text
    adhoc = client.get("/api/reports/preview", params={"period": "last_30", "language": "ar"}, headers=auth.headers)
    assert 'dir="rtl"' in adhoc.text

    before = len(OUTBOX)
    r = client.post(f"/api/reports/schedules/{schedule['id']}/send", headers=auth.headers)
    assert r.status_code == 200, r.text
    assert r.json()["recipients"] == 2 and r.json()["schedule"]["send_count"] == 1
    mail = OUTBOX[-1]
    assert len(OUTBOX) == before + 1
    assert "Weekly results" in mail["Subject"] and "boss@example.com" in mail["To"]
    attachments = {part.get_filename(): part for part in mail.iter_attachments()}
    assert "Weekly results.html" in attachments
    assert b"Autumn sale" in attachments["Weekly results.html"].get_content().encode()
    meta = client.get("/api/reports/meta", headers=auth.headers).json()
    if meta["pdf_available"]:
        assert attachments["Weekly results.pdf"].get_content().startswith(b"%PDF")
        pdf = client.get(f"/api/reports/schedules/{schedule['id']}/pdf", headers=auth.headers)
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    else:
        assert r.json()["format"] == "html"
        assert client.get(f"/api/reports/schedules/{schedule['id']}/pdf", headers=auth.headers).status_code == 409

    r = client.patch(f"/api/reports/schedules/{schedule['id']}", json={"active": False}, headers=auth.headers)
    assert r.json()["next_send_at"] is None


def test_periodic_sending(client, auth, db, data):
    schedule = ReportSchedule(workspace_id=auth.workspace_id, name="Monthly", recipients=["boss@example.com"],
                              frequency="monthly", month_day=1, hour=8, period="prev_month", language="ar",
                              next_send_at=datetime.now(UTC) - timedelta(minutes=5))
    broken = ReportSchedule(workspace_id=auth.workspace_id, name="Nobody", recipients=[], frequency="weekly",
                            next_send_at=datetime.now(UTC) - timedelta(minutes=5))
    db.add_all([schedule, broken])
    db.flush()
    before = len(OUTBOX)
    assert reports.send_due(db) == 1
    assert len(OUTBOX) == before + 1
    assert schedule.last_sent_at and schedule.next_send_at > datetime.now(UTC)
    assert broken.last_error and broken.next_send_at > datetime.now(UTC)
    assert reports.send_due(db) == 0, "nothing is due any more"


def test_reports_isolation_and_roles(client, auth, db, data):
    schedule = client.post("/api/reports/schedules", json=schedule_json(), headers=auth.headers).json()
    other = signup(client, email="rep2@example.com", workspace="Rep2")
    for method, path in (("get", ""), ("patch", ""), ("delete", ""), ("get", "/preview"), ("post", "/send"),
                         ("get", "/pdf")):
        kwargs = {"json": {"name": "x"}} if method == "patch" else {}
        r = getattr(client, method)(f"/api/reports/schedules/{schedule['id']}{path}", headers=other.headers, **kwargs)
        assert r.status_code == 404, (method, path)
    assert client.get("/api/reports/schedules", headers=other.headers).json() == []
    assert client.post("/api/reports/schedules", json=schedule_json(account_ids=[data["fb"].id]),
                       headers=other.headers).status_code == 404
    other_report = reports.report_values(db, db.get(Workspace, other.workspace_id), language="en")
    assert {k["key"]: k["value"] for k in other_report["kpis"]}["impressions"] == "0"
    editor = signup(client, email="rep-editor@example.com", workspace="E")
    db.add(Membership(user_id=editor.user_id, workspace_id=auth.workspace_id, role="editor"))
    db.flush()
    headers = {**editor.headers, "X-Workspace": str(auth.workspace_id)}
    assert client.get("/api/reports/schedules", headers=headers).status_code == 403
