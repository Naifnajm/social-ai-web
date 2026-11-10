"""Campaigns, content pillars, the Planner (drag & drop, scheduling, best times) and evergreen reposting."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import AppError
from app.modules.ai import service as ai
from app.modules.planning import service as planning
from app.modules.planning.models import Campaign
from app.modules.social.models import Post
from tests.conftest import signup
from tests.planning_fakes import install_fake_social, make_account, make_media, make_post, publish

UTC = timezone.utc
TZ = ZoneInfo("Asia/Riyadh")  # default time zone of a new workspace


def today() -> date:
    return datetime.now(TZ).date()


@pytest.fixture()
def fake(monkeypatch, db):
    return install_fake_social(monkeypatch, db)


# ---------------------------------------------------------------------------------------------- campaigns
def test_campaign_crud_and_stats(client, auth, db, fake):
    fb = make_account(db, auth.workspace_id)
    r = client.post("/api/campaigns", json={"name": "Launch", "tagline": "Order in 30 seconds",
                                            "date_start": str(today() + timedelta(days=2)),
                                            "date_end": str(today() + timedelta(days=20)), "budget": 500},
                    headers=auth.headers)
    assert r.status_code == 201, r.text
    campaign = r.json()
    assert campaign["state"] == "planned"
    assert campaign["date_start"] == str(today() + timedelta(days=2))
    assert campaign["color"].startswith("#")
    cid = campaign["id"]

    published = make_post(db, auth.workspace_id, [fb], campaign_id=cid)
    publish(db, published, impressions=200, engagements=20)
    make_post(db, auth.workspace_id, [fb], campaign_id=cid, state="scheduled",
              scheduled_at=datetime.now(UTC) + timedelta(days=3))
    make_post(db, auth.workspace_id, [fb], campaign_id=cid)

    stats = client.get("/api/campaigns", headers=auth.headers).json()[0]["stats"]
    assert (stats["post_count"], stats["published_count"], stats["scheduled_count"]) == (3, 1, 1)
    assert (stats["impressions"], stats["engagements"], stats["engagement_rate"]) == (200, 20, 10.0)
    assert stats["progress"] == 33.3

    detail = client.get(f"/api/campaigns/{cid}", headers=auth.headers).json()
    assert len(detail["posts"]) == 3
    assert detail["networks"][0]["platform"] == "facebook"
    assert detail["networks"][0]["impressions"] == 200

    r = client.patch(f"/api/campaigns/{cid}", json={"date_end": str(today())}, headers=auth.headers)
    assert r.status_code == 400  # end before start
    r = client.patch(f"/api/campaigns/{cid}", json={"state": "running"}, headers=auth.headers)
    assert (r.json()["state"], r.json()["auto_state"]) == ("running", False)
    assert client.delete(f"/api/campaigns/{cid}", headers=auth.headers).status_code == 204
    db.refresh(published)
    assert published.campaign_id is None


def test_campaign_states_follow_dates(client, auth, db):
    running = client.post("/api/campaigns", json={"name": "Now", "date_start": str(today() - timedelta(days=1)),
                                                  "date_end": str(today() + timedelta(days=3))},
                          headers=auth.headers).json()
    assert running["state"] == "running"  # already started when created
    later = Campaign(workspace_id=auth.workspace_id, name="Later", state="planned",
                     date_start=planning.day_to_dt(today() + timedelta(days=1)))
    over = Campaign(workspace_id=auth.workspace_id, name="Over", state="running",
                    date_start=planning.day_to_dt(today() - timedelta(days=9)),
                    date_end=planning.day_to_dt(today() - timedelta(days=2)))
    manual = Campaign(workspace_id=auth.workspace_id, name="Manual", state="running", auto_state=False,
                      date_end=planning.day_to_dt(today() - timedelta(days=2)))
    db.add_all([later, over, manual])
    db.flush()
    assert planning.update_campaign_states(db) >= 1
    assert (later.state, over.state, manual.state) == ("planned", "finished", "running")
    planning.update_campaign_states(db, today=today() + timedelta(days=1))
    assert later.state == "running"


def test_campaign_viewer_and_isolation(client, auth, db):
    cid = client.post("/api/campaigns", json={"name": "Mine"}, headers=auth.headers).json()["id"]
    other = signup(client, email="other@example.com", workspace="Other")
    assert client.get(f"/api/campaigns/{cid}", headers=other.headers).status_code == 404
    assert client.patch(f"/api/campaigns/{cid}", json={"name": "x"}, headers=other.headers).status_code == 404
    assert client.delete(f"/api/campaigns/{cid}", headers=other.headers).status_code == 404
    assert client.get("/api/campaigns", headers=other.headers).json() == []
    # another workspace cannot put my post in its campaign, nor its post in mine
    their = client.post("/api/campaigns", json={"name": "Theirs"}, headers=other.headers).json()["id"]
    post = make_post(db, auth.workspace_id)
    assert client.patch(f"/api/planner/posts/{post.id}", json={"campaign_id": their},
                        headers=auth.headers).status_code == 404
    assert client.patch(f"/api/planner/posts/{post.id}", json={"campaign_id": their},
                        headers=other.headers).status_code == 404
    r = client.patch(f"/api/planner/posts/{post.id}", json={"campaign_id": cid}, headers=auth.headers)
    assert r.json()["campaign"]["name"] == "Mine"


# ---------------------------------------------------------------------------------------------- pillars
def test_pillars_share_and_order(client, auth, db):
    tips = client.post("/api/pillars", json={"name": "Tips", "target_share": 60}, headers=auth.headers).json()
    offers = client.post("/api/pillars", json={"name": "Offers", "target_share": 40}, headers=auth.headers).json()
    now = datetime.now(UTC)
    for pillar in (tips["id"], tips["id"], offers["id"], None):
        post = make_post(db, auth.workspace_id, pillar_id=pillar)
        post.state, post.published_at = "posted", now - timedelta(days=3)
    old = make_post(db, auth.workspace_id, pillar_id=offers["id"])
    old.state, old.published_at = "posted", now - timedelta(days=60)
    make_post(db, auth.workspace_id, pillar_id=offers["id"], planned_date=planning.day_to_dt(today() + timedelta(days=2)))
    db.flush()
    rows = {p["name"]: p for p in client.get("/api/pillars", headers=auth.headers).json()}
    assert (rows["Tips"]["share_30"], rows["Offers"]["share_30"]) == (50.0, 25.0)
    assert (rows["Tips"]["gap"], rows["Offers"]["gap"]) == (-10.0, -15.0)
    assert rows["Tips"]["published_30"] == 2
    assert rows["Offers"]["planned_share_30"] == 100.0
    ordered = client.put("/api/pillars/order", json={"ids": [offers["id"], tips["id"]]}, headers=auth.headers).json()
    assert [p["name"] for p in ordered] == ["Offers", "Tips"]
    r = client.patch(f"/api/pillars/{tips['id']}", json={"target_share": 101}, headers=auth.headers)
    assert r.status_code == 422
    other = signup(client, email="p2@example.com", workspace="P2")
    assert client.patch(f"/api/pillars/{tips['id']}", json={"name": "x"}, headers=other.headers).status_code == 404
    assert client.delete(f"/api/pillars/{tips['id']}", headers=other.headers).status_code == 404
    assert client.delete(f"/api/pillars/{tips['id']}", headers=auth.headers).status_code == 204


# ---------------------------------------------------------------------------------------------- planner
def test_planner_data_moves_and_schedule(client, auth, db, fake):
    fb = make_account(db, auth.workspace_id)
    campaign = client.post("/api/campaigns", json={"name": "Launch", "color": "#2563eb"}, headers=auth.headers).json()
    pillar = client.post("/api/pillars", json={"name": "Offers"}, headers=auth.headers).json()
    photo = make_media(db, auth.workspace_id)
    start = today().replace(day=1)
    end = (start + timedelta(days=40)).replace(day=1)
    tomorrow = today() + timedelta(days=1)
    at = datetime.combine(tomorrow, datetime.min.time(), tzinfo=TZ).replace(hour=15).astimezone(UTC)
    scheduled = make_post(db, auth.workspace_id, [fb], state="scheduled", scheduled_at=at, campaign_id=campaign["id"],
                          pillar_id=pillar["id"], media=[photo])
    planned = make_post(db, auth.workspace_id, [fb], planned_date=planning.day_to_dt(tomorrow))
    outside = make_post(db, auth.workspace_id, [fb], planned_date=planning.day_to_dt(end + timedelta(days=3)))
    loose = make_post(db, auth.workspace_id, [fb], name="No date")

    data = client.get("/api/planner", params={"start": str(start), "end": str(end)}, headers=auth.headers).json()
    ids = [p["id"] for p in data["posts"]]
    assert scheduled.id in ids and planned.id in ids and outside.id not in ids
    item = next(p for p in data["posts"] if p["id"] == scheduled.id)
    assert (item["day"], item["time"]) == (str(tomorrow), "15:00")
    assert item["campaign"] == {"id": campaign["id"], "name": "Launch", "color": "#2563eb"}
    assert item["pillar"]["name"] == "Offers"
    assert item["media"]["url"] == f"/api/media/{photo.id}/file"
    assert item["platforms"] == ["facebook"]
    assert [p["id"] for p in data["unplanned"]] == [loose.id]
    assert len(data["best"]) == 7 and data["best"][0]["weekday"] == 0
    assert len(data["best_slots"]) == 3 and data["best_slots"][0]["source"] == "service"
    assert data["today"] == str(today())
    filtered = client.get("/api/planner", params={"start": str(start), "end": str(end), "campaign_id": campaign["id"]},
                          headers=auth.headers).json()
    assert [p["id"] for p in filtered["posts"]] == [scheduled.id]

    # drag & drop keeps the time of a scheduled post and re-schedules it through publishing
    later = today() + timedelta(days=5)
    r = client.post(f"/api/planner/posts/{scheduled.id}/move", json={"day": str(later)}, headers=auth.headers)
    assert r.status_code == 200, r.text
    assert (r.json()["day"], r.json()["time"], r.json()["state"]) == (str(later), "15:00", "scheduled")
    assert fake.submits[-1][:2] == (scheduled.id, "schedule")
    r = client.post(f"/api/planner/posts/{scheduled.id}/move", json={"day": str(today() - timedelta(days=1))},
                    headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "past_day"
    # a draft only gets its planned day
    r = client.post(f"/api/planner/posts/{planned.id}/move", json={"day": str(later)}, headers=auth.headers).json()
    assert (r["day"], r["time"], r["state"]) == (str(later), None, "draft")
    # then an exact time: scheduled through the contract
    r = client.post(f"/api/planner/posts/{planned.id}/schedule", json={"day": str(later), "time": "10:30"},
                    headers=auth.headers).json()
    assert (r["state"], r["time"]) == ("scheduled", "10:30")
    r = client.post(f"/api/planner/posts/{outside.id}/schedule",
                    json={"day": str(today() - timedelta(days=2)), "time": "10:00"}, headers=auth.headers)
    assert r.status_code == 400
    done = make_post(db, auth.workspace_id, [fb])
    publish(db, done)
    r = client.post(f"/api/planner/posts/{done.id}/move", json={"day": str(later)}, headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "not_movable"
    r = client.post(f"/api/planner/posts/{loose.id}/move", json={"day": str(later)}, headers=auth.headers)
    assert client.post(f"/api/planner/posts/{loose.id}/unplan", headers=auth.headers).json()["day"] is None


def test_planner_past_time_today_and_isolation(client, auth, db, fake):
    post = make_post(db, auth.workspace_id)
    r = client.post(f"/api/planner/posts/{post.id}/schedule", json={"day": str(today()), "time": "00:00"},
                    headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "past_time"
    other = signup(client, email="planner2@example.com", workspace="Two")
    assert client.get(f"/api/planner/posts/{post.id}", headers=auth.headers).json()["id"] == post.id
    assert client.get(f"/api/planner/posts/{post.id}", headers=other.headers).status_code == 404
    assert client.get(f"/api/evergreen/{post.id}", headers=other.headers).status_code == 404
    make_account(db, auth.workspace_id, "instagram")
    assert [a["platform"] for a in client.get("/api/planner/accounts", headers=auth.headers).json()] == ["instagram"]
    assert client.get("/api/planner/accounts", headers=other.headers).json() == []
    assert client.post(f"/api/planner/posts/{post.id}/move", json={"day": str(today() + timedelta(days=2))},
                       headers=other.headers).status_code == 404
    data = client.get("/api/planner", params={"start": str(today()), "end": str(today() + timedelta(days=7))},
                      headers=other.headers).json()
    assert data["posts"] == [] and data["unplanned"] == []
    r = client.get("/api/planner", params={"start": str(today()), "end": str(today() + timedelta(days=200))},
                   headers=auth.headers)
    assert r.status_code == 400


def test_best_times_fall_back_to_benchmarks(client, auth, db, monkeypatch):
    # when the publishing service cannot answer, hints come from the benchmarks
    from app.modules.social import service as social

    def broken(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(social, "next_best_slots", broken)
    data = client.get("/api/planner/best-times", params={"platforms": ["instagram"]}, headers=auth.headers).json()
    assert len(data["by_weekday"]) == 7
    assert {s["source"] for s in data["slots"]} == {"benchmark"}
    assert all(s["at"] > datetime.now(UTC).isoformat()[:16] for s in data["slots"])


def test_best_times_from_publishing(client, auth, db):
    data = client.get("/api/planner/best-times", params={"platforms": ["instagram"]}, headers=auth.headers).json()
    assert data["slots"] and {s["source"] for s in data["slots"]} == {"service"}


def test_viewer_cannot_move(client, auth, db, fake):
    from app.modules.workspaces.models import Membership
    viewer = signup(client, email="viewer@example.com", workspace="Mine")
    db.add(Membership(user_id=viewer.user_id, workspace_id=auth.workspace_id, role="viewer"))
    db.flush()
    post = make_post(db, auth.workspace_id)
    headers = {**viewer.headers, "X-Workspace": str(auth.workspace_id)}
    assert client.get("/api/campaigns", headers=headers).status_code == 200
    assert client.post(f"/api/planner/posts/{post.id}/move", json={"day": str(today() + timedelta(days=1))},
                       headers=headers).status_code == 403
    assert client.post("/api/campaigns", json={"name": "x"}, headers=headers).status_code == 403


# ---------------------------------------------------------------------------------------------- evergreen
def _evergreen(db, workspace_id, accounts, **values):
    post = make_post(db, workspace_id, accounts, content="Evergreen tip", evergreen=True, recycle_interval_days=30,
                     **values)
    publish(db, post, when=datetime.now(UTC) - timedelta(days=31))
    return post


def test_evergreen_reposts_at_best_slot(client, auth, db, fake):
    fb = make_account(db, auth.workspace_id)
    campaign = Campaign(workspace_id=auth.workspace_id, name="Always on")
    db.add(campaign)
    db.flush()
    photo = make_media(db, auth.workspace_id)
    original = _evergreen(db, auth.workspace_id, [fb], media=[photo], campaign_id=campaign.id,
                          author_id=auth.user_id)
    not_due = make_post(db, auth.workspace_id, [fb], evergreen=True)
    publish(db, not_due, when=datetime.now(UTC) - timedelta(days=3))

    created = planning.recycle_due_posts(db)
    assert len(created) == 1
    copy = db.get(Post, created[0])
    assert copy.recycled_from_id == original.id
    assert (copy.state, copy.scheduled_at) == ("scheduled", fake.slot)
    assert copy.content == "Evergreen tip" and copy.campaign_id == campaign.id
    assert [link.media_id for link in copy.media_links] == [photo.id]
    assert [a.id for a in copy.accounts] == [fb.id]
    assert not copy.evergreen
    assert fake.submits[-1][1] == "best_time"
    assert original.recycle_count == 1 and original.last_recycled_at
    # one waiting copy at a time
    assert planning.recycle_due_posts(db) == []
    listed = client.get("/api/evergreen", headers=auth.headers).json()
    row = next(r for r in listed if r["post"]["id"] == original.id)
    assert row["waiting_copy"] and row["recycle_count"] == 1
    # the copy went out: the next repost waits for the interval again
    copy.state = "posted"
    db.flush()
    assert planning.recycle_due_posts(db) == []
    from app.core.models import Notification
    assert db.query(Notification).filter_by(user_id=auth.user_id, kind="planning.evergreen").count() == 1


def test_evergreen_rewrite_and_failures(client, auth, db, fake, monkeypatch):
    fb = make_account(db, auth.workspace_id)
    _evergreen(db, auth.workspace_id, [fb], recycle_rewrite=True, variants={"x": "Short tip"})
    prompts = []

    def generate(db_, ws, system, user, **kw):
        prompts.append(user)
        return "“A fresh way to say it”"

    monkeypatch.setattr(ai, "generate_text", generate)
    copy = db.get(Post, planning.recycle_due_posts(db)[0])
    assert copy.content == "A fresh way to say it"
    assert copy.variants == {"x": "A fresh way to say it"}
    assert "Evergreen tip" in prompts[0]

    # AI failure: the original text is used
    second = _evergreen(db, auth.workspace_id, [fb], recycle_rewrite=True)
    def no_provider(*args, **kwargs):
        raise AppError("No AI provider", code="no_ai_provider")

    monkeypatch.setattr(ai, "generate_text", no_provider)
    copy2 = db.get(Post, planning.recycle_due_posts(db)[0])
    assert copy2.recycled_from_id == second.id and copy2.content == "Evergreen tip"

    # until date passed: nothing
    stopped = _evergreen(db, auth.workspace_id, [fb], recycle_until=planning.day_to_dt(today() - timedelta(days=1)))
    assert stopped.id not in [db.get(Post, i).recycled_from_id for i in planning.recycle_due_posts(db)]


def test_evergreen_api(client, auth, db, fake):
    fb = make_account(db, auth.workspace_id)
    post = make_post(db, auth.workspace_id, [fb])
    publish(db, post)
    r = client.put(f"/api/evergreen/{post.id}", json={"evergreen": True, "interval_days": 14, "rewrite": True,
                                                      "until": str(today() + timedelta(days=90))},
                   headers=auth.headers)
    assert r.status_code == 200, r.text
    assert r.json()["interval_days"] == 14
    assert r.json()["next_recycle_at"][:10] == str((post.published_at + timedelta(days=14)).date())
    r = client.post(f"/api/evergreen/{post.id}/repost", headers=auth.headers)
    assert r.status_code == 200 and r.json()["state"] == "scheduled"
    assert client.post(f"/api/evergreen/{post.id}/repost", headers=auth.headers).json()["code"] == "copy_waiting"
    copy_id = r.json()["copy_id"]
    assert client.put(f"/api/evergreen/{copy_id}", json={"evergreen": True}, headers=auth.headers).status_code == 400
    other = signup(client, email="ever@example.com", workspace="E")
    assert client.put(f"/api/evergreen/{post.id}", json={"evergreen": False}, headers=other.headers).status_code == 404
    assert client.get("/api/evergreen", headers=other.headers).json() == []
