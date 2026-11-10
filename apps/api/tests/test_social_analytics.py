"""Performance dashboard (ported from the Odoo analytics tests), metrics sync and AI report."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.db import utcnow
from app.modules.ai import service as ai
from app.modules.social import analytics, tasks
from app.modules.social.models import AccountStat
from app.modules.workspaces.models import Workspace
from tests.social_common import account, ago, jobs_in_test_session, published  # noqa: F401


@pytest.fixture()
def ws(auth, db):
    db.get(Workspace, auth.workspace_id).timezone = "UTC"
    db.flush()
    return auth.workspace_id


def test_dashboard_kpis_and_breakdown(db, ws):
    x, fb = account(db, ws, "x"), account(db, ws, "facebook")
    published(db, x, ago(days=2), impressions=1000, likes=40, comments=10)
    published(db, fb, ago(days=3), impressions=500, likes=20, shares=5)
    published(db, fb, ago(days=40), impressions=100, likes=1)  # previous period
    data = analytics.dashboard(db, ws, 30)
    assert data["kpis"]["posts"] == 2
    assert data["kpis"]["impressions"] == 1500
    assert data["kpis"]["engagements"] == 75
    assert data["kpis"]["engagement_rate"] == 5.0
    assert data["deltas"]["posts"] == 100.0
    assert {r["platform"] for r in data["breakdown"]} == {"x", "facebook"}
    assert len(data["series"]) == 31
    assert data["top_posts"][0]["platform"] == "x"
    only_x = analytics.dashboard(db, ws, 30, "x")
    assert only_x["kpis"]["posts"] == 1 and only_x["breakdown"] == []


def test_best_times_benchmark_then_own_data(db, ws):
    x = account(db, ws, "x")
    data = analytics.dashboard(db, ws, 30)
    assert data["best_source"] == "benchmark"
    assert len(data["heatmap"]) == 7 and len(data["heatmap"][0]) == 24
    # 10 posts: Wednesdays 19:00 perform far better than Mondays 08:00
    today = utcnow().date()
    wednesday = today - timedelta(days=(today.weekday() - 2) % 7 or 7)
    base = datetime(wednesday.year, wednesday.month, wednesday.day, 19, tzinfo=timezone.utc)
    for week in range(5):
        published(db, x, base - timedelta(weeks=week), impressions=100, likes=30)
        published(db, x, base - timedelta(weeks=week, days=2, hours=11), impressions=100, likes=2)
    _grid, slots, source = analytics.best_times(db, ws)
    assert source == "own"
    assert (slots[0]["weekday"], slots[0]["hour"]) == (2, 19)
    upcoming = analytics.next_best_slots(db, ws, ["x"])
    assert upcoming and all(s["at"] > utcnow() for s in upcoming)
    assert upcoming[0]["label"]


def test_best_times_use_the_workspace_timezone(db, ws):
    db.get(Workspace, ws).timezone = "Asia/Riyadh"  # UTC+3
    x = account(db, ws, "x")
    base = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)  # Wednesday 19:00 in Riyadh
    for week in range(8):
        published(db, x, ago(days=1, weeks=week), impressions=1)  # low engagement noise
    for week in range(9):
        published(db, x, base - timedelta(weeks=week) + timedelta(weeks=3), impressions=100, likes=50)
    _grid, slots, source = analytics.best_times(db, ws)
    assert source == "own" and (slots[0]["weekday"], slots[0]["hour"]) == (2, 19)


def test_tips(db, ws):
    x, fb = account(db, ws, "x"), account(db, ws, "facebook")
    for i in range(3):
        published(db, fb, ago(days=5 + i), media_type="video", impressions=100, likes=20)
        published(db, fb, ago(days=9 + i), media_type="text", impressions=100, likes=2)
    x.state = "expired"
    tips = analytics.dashboard(db, ws, 30)["tips"]
    titles = " | ".join(t["title"] for t in tips)
    assert tips[0]["level"] == "danger"  # broken account first
    assert "Reconnect" in titles
    assert "Video works best" in titles


def test_sync_metrics_and_audience(db, ws, mock_http):
    x = account(db, ws, "x")
    target = published(db, x, ago(days=1))
    target.external_id, target.metrics_updated_at = "555", None

    def handler(method, url, kw):
        if url.endswith("/tweets"):
            return mock_http.response(200, {"data": [{"id": "555", "public_metrics": {
                "impression_count": 900, "like_count": 30, "reply_count": 4, "retweet_count": 5,
                "quote_count": 1, "bookmark_count": 2}}]})
        return mock_http.response(200, {"data": {"public_metrics": {"followers_count": 1234}}})

    mock_http(handler)
    result = analytics.refresh(db, ws, "x")
    assert result == {"posts": 1, "accounts": 1}
    assert (target.impressions, target.likes, target.shares, target.saves) == (900, 30, 6, 2)
    assert target.engagements == 42 and target.engagement_rate == 4.67
    assert x.followers == 1234
    stats = db.query(AccountStat).filter_by(account_id=x.id).all()
    assert [s.followers for s in stats] == [1234]
    # periodic tasks run for every workspace; a second sync the same day updates the same row
    mock_http(lambda m, u, k: mock_http.response(200, {"data": {"public_metrics": {"followers_count": 1300}}}))
    tasks.sync_followers()
    assert [s.followers for s in db.query(AccountStat).filter_by(account_id=x.id).all()] == [1300]


def test_dashboard_api_and_ai_report(client, auth, db, ws, monkeypatch):
    fb = account(db, ws, "facebook")
    published(db, fb, ago(days=1), impressions=10, likes=1)
    data = client.get("/api/analytics/dashboard?days=7", headers=auth.headers).json()
    assert data["kpis"]["posts"] == 1 and data["period"]["days"] == 7

    seen = {}

    def fake_generate(db_, workspace_id, system, user, **kwargs):
        seen.update(workspace_id=workspace_id, system=system, user=user, purpose=kwargs.get("purpose"))
        return "**Summary**\n• Post more videos"

    monkeypatch.setattr(ai, "generate_text", fake_generate)
    r = client.post("/api/analytics/ai-report", json={"days": 30}, headers=auth.headers)
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Summary\n• Post more videos"
    assert seen["workspace_id"] == ws and '"per_platform"' in seen["user"]


def test_ai_report_without_provider_is_a_clear_error(client, auth, ws):
    r = client.post("/api/analytics/ai-report", json={"days": 30}, headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "no_ai_provider"


def test_dashboard_extenders(db, ws):
    from app.modules.social import hooks

    def block(db_, workspace_id, data, start, end, prev_start, platform, account_ids):
        data["kpis"]["link_clicks"] = 7
        data["extra"]["results"] = {"has_sales": False}

    hooks.DASHBOARD_EXTENDERS.append(block)
    try:
        data = analytics.dashboard(db, ws, 30)
    finally:
        hooks.DASHBOARD_EXTENDERS.remove(block)
    assert data["kpis"]["link_clicks"] == 7 and data["extra"]["results"] == {"has_sales": False}
