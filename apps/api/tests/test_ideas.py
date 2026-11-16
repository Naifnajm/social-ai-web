"""Ideas of the day: context → ideas (AI or rules) → edit → approve (carousel slides rendered, scheduled,
approvals respected) → reject; the morning batch."""
import io
from datetime import timedelta

from PIL import Image
from sqlalchemy import select

from app.core.db import utcnow
from app.core.models import Media, Notification
from app.core.storage import read_media
from app.modules.ideas import service as ideas
from app.modules.ideas import tasks
from app.modules.ideas.models import ContentIdea
from app.modules.listening.models import ListeningQuery, Mention
from app.modules.planning.models import ContentPillar
from app.modules.products.models import Product
from app.modules.social.models import Post, SocialAccount
from app.modules.workspaces.models import Membership, Role, Workspace
from app.modules.workspaces.settings import set_setting


def _account(db, ws, platform="facebook"):
    account = SocialAccount(workspace_id=ws, name=f"{platform} page", platform=platform, external_id=f"{platform}-1",
                            access_token="tok")
    db.add(account)
    db.flush()
    return account


def _no_ai(monkeypatch):
    from app.modules.ai import service as ai
    monkeypatch.setattr(ai, "has_provider", lambda *a, **k: False)


def _signals(db, ws):
    query = ListeningQuery(workspace_id=ws, name="Brand", keywords=["acme"], required=[], excluded=[], languages=[],
                           countries=[], competitors=[], sources=["owned"], active=True)
    db.add(query)
    db.flush()
    now = utcnow()
    for i in range(6):
        db.add(Mention(workspace_id=ws, query_id=query.id, source="x", external_id=f"q{i}", text=f"acme decaf price? {i}",
                       published_at=now - timedelta(hours=2 + i), intent="purchase", topic="Decaf",
                       sentiment="neutral", analyzed=True))
    for i in range(4):
        db.add(Mention(workspace_id=ws, query_id=query.id, source="x", external_id=f"r{i}", text="acme cookies",
                       published_at=now - timedelta(hours=3 + i), sentiment="positive", analyzed=True))
    db.add(Product(workspace_id=ws, name="Cold brew", description="Slow steeped for 18 hours", active=True))
    db.add(ContentPillar(workspace_id=ws, name="Behind the scenes", target_share=30, active=True))
    db.flush()


def test_rules_make_ideas_from_real_signals(client, auth, db, monkeypatch):
    _no_ai(monkeypatch)
    fb = _account(db, auth.workspace_id)
    _signals(db, auth.workspace_id)
    r = client.post("/api/ideas/generate", json={"count": 4, "language": "en"}, headers=auth.headers)
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 4 and {i["format"] for i in items} >= {"carousel", "post", "video"}
    carousel = next(i for i in items if i["format"] == "carousel")
    assert carousel["reasons"][0] == {"kind": "question", "label": "6 people asked about Decaf this week"}
    assert carousel["slides"][0]["title"] == "Your questions about Decaf" and not carousel["ai_written"]
    assert carousel["reasons"][-1]["kind"] == "best_time" and carousel["suggested_at"]
    assert carousel["account_ids"] == [fb.id] and carousel["platforms"] == ["facebook"]
    times = [i["suggested_at"] for i in items]
    assert len(set(times)) == len(times)  # each idea gets its own slot
    assert any(i.get("product_id") for i in items) and any(i.get("pillar_id") for i in items)
    assert client.get("/api/ideas", headers=auth.headers).json()[0]["state"] == "new"


def test_ai_ideas_are_checked_against_the_signals(db, auth, monkeypatch):
    from app.modules.ai import service as ai
    _account(db, auth.workspace_id)
    _account(db, auth.workspace_id, "x")
    _signals(db, auth.workspace_id)
    seen = {}

    def fake(db_, ws, system, user, **kwargs):
        seen["system"], seen["user"] = system, user
        return {"ideas": [
            {"format": "carousel", "title": "Decaf FAQ", "reason_keys": ["question:Decaf", "invented:1"],
             "caption": "All about decaf ☕", "hashtags": ["decaf", "#acme"], "variants": {"x": "Decaf FAQ", "tiktok": "x"},
             "slides": [{"title": "Decaf?", "body": "Yes"}, {"title": "Taste", "body": "Same"}, {"title": "Order", "body": "Now"}]},
            {"format": "video", "title": "Cookie reel", "reason_keys": ["rising:cookies"], "caption": "Cookies!",
             "video": {"hook": "Listen to this crunch", "duration_seconds": 20,
                       "scenes": [{"visual": "Close-up", "text": "Crunch"}], "voiceover": "Fresh every morning"}},
            {"format": "carousel", "title": "Too short", "caption": "x", "slides": [{"title": "one"}]},
            {"format": "post", "title": "", "caption": "no title"},
        ]}

    monkeypatch.setattr(ai, "has_provider", lambda *a, **k: True)
    monkeypatch.setattr(ai, "generate_json", fake)
    workspace = db.get(Workspace, auth.workspace_id)
    made = ideas.generate(db, workspace, auth.user_id, count=4, language="en")
    assert [i.format for i in made] == ["carousel", "video", "post"]  # a 1-slide carousel became a post
    faq = made[0]
    assert faq.ai_written and [r["kind"] for r in faq.reasons] == ["question", "best_time"]  # invented key dropped
    assert faq.hashtags == ["#decaf", "#acme"] and faq.variants == {"x": "Decaf FAQ"}
    assert made[1].video["hook"] == "Listen to this crunch" and made[1].video["duration"] == 20
    assert "English" in seen["system"] and '"key": "question:Decaf"' in seen["user"]
    assert "Cold brew" in seen["user"] and "Behind the scenes" in seen["user"]


def test_approve_carousel_renders_slides_and_schedules(client, auth, db, monkeypatch):
    _no_ai(monkeypatch)
    fb = _account(db, auth.workspace_id)
    idea = ContentIdea(workspace_id=auth.workspace_id, format="carousel", language="ar", title="أسئلة القهوة",
                       caption="سألتونا عن القهوة منزوعة الكافيين 👇", hashtags=["#قهوة"],
                       slides=[{"title": "أسئلتكم عن القهوة", "body": "اسحب للأجوبة"},
                               {"title": "هل طعمها مختلف؟", "body": "لا، نفس الطعم تقريباً"},
                               {"title": "Order now", "body": "Link in bio"}],
                       platforms=["facebook"], account_ids=[fb.id], suggested_at=utcnow() + timedelta(days=1))
    db.add(idea)
    db.flush()
    h = auth.headers
    edited = client.patch(f"/api/ideas/{idea.id}", json={"caption": "سألتونا كثير 👇", "hashtags": ["قهوة مختصة"]},
                          headers=h).json()
    assert edited["edited"] and edited["hashtags"] == ["#قهوة_مختصة"]
    preview = client.post(f"/api/ideas/{idea.id}/slides", headers=h).json()
    assert len(preview["media_urls"]) == 3
    image = Image.open(io.BytesIO(read_media(db.get(Media, preview["media_ids"][0]))))
    assert image.size == (1080, 1350)
    r = client.post(f"/api/ideas/{idea.id}/approve", json={}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    post = db.get(Post, data["post_id"])
    assert post.state == "scheduled" and abs((post.scheduled_at - idea.suggested_at).total_seconds()) < 61
    assert post.content == "سألتونا كثير 👇\n\n#قهوة_مختصة" and len(post.media_links) == 3
    assert post.source_ref == f"idea:{idea.id}" and data["url"] == f"/planner?post={post.id}"
    assert data["idea"]["state"] == "scheduled"
    again = client.post(f"/api/ideas/{idea.id}/approve", json={}, headers=h)
    assert again.status_code == 400 and again.json()["code"] == "idea_done"


def test_approval_flow_video_draft_and_reject(client, auth, db, monkeypatch):
    from app.modules.auth.models import User
    _no_ai(monkeypatch)
    fb = _account(db, auth.workspace_id)
    set_setting(db, auth.workspace_id, "approvals.required", True)
    editor = User(email="ed@example.com", name="Editor")
    db.add(editor)
    db.flush()
    db.add(Membership(user_id=editor.id, workspace_id=auth.workspace_id, role=Role.editor))
    db.flush()
    workspace = db.get(Workspace, auth.workspace_id)

    post_idea = ContentIdea(workspace_id=auth.workspace_id, format="post", title="Tip", caption="A tip",
                            account_ids=[fb.id], platforms=["facebook"])
    video_idea = ContentIdea(workspace_id=auth.workspace_id, format="video", title="Reel", caption="Watch",
                             account_ids=[fb.id], platforms=["facebook"],
                             video={"hook": "Wait for it", "duration": 15, "voiceover": "Hello",
                                    "scenes": [{"visual": "Cup", "text": "Pour"}]})
    other = ContentIdea(workspace_id=auth.workspace_id, format="post", title="Meh", caption="x")
    db.add_all([post_idea, video_idea, other])
    db.flush()
    waiting = ideas.approve(db, workspace, post_idea, editor.id, mode="best_time")
    assert waiting["post_state"] == "to_approve" and waiting["url"].startswith("/approvals")
    draft = ideas.approve(db, workspace, video_idea, editor.id)
    post = db.get(Post, draft["post_id"])
    assert video_idea.state == "draft" and post.state == "draft" and "Wait for it" in post.ai_brief
    assert draft["url"] == f"/studio?post={post.id}"
    r = client.post(f"/api/ideas/{other.id}/reject", json={"reason": "not_our_tone"}, headers=auth.headers).json()
    assert r["state"] == "rejected"
    handled = client.get("/api/ideas", params={"state": "handled"}, headers=auth.headers).json()
    assert {i["state"] for i in handled} == {"scheduled", "draft", "rejected"}  # waiting for approval = scheduled


def test_morning_batch_once_a_day(db, auth, monkeypatch):
    _no_ai(monkeypatch)
    _account(db, auth.workspace_id)
    set_setting(db, auth.workspace_id, "ideas.hour", 0)
    assert tasks.daily_ideas() >= 1
    count = db.scalar(select(ContentIdea.id).where(ContentIdea.workspace_id == auth.workspace_id))
    assert count
    note = db.scalar(select(Notification).where(Notification.kind == "ideas.daily"))
    assert note and note.link == "/ideas"
    assert tasks.daily_ideas() == 0
    old = ContentIdea(workspace_id=auth.workspace_id, format="post", title="old", caption="x")
    db.add(old)
    db.flush()
    old.created_at = utcnow() - timedelta(days=5)
    db.flush()
    assert ideas.expire(db) >= 1 and old.state == "expired"


def test_text_posts_skip_networks_that_need_media(db, auth, monkeypatch):
    _no_ai(monkeypatch)
    fb, ig = _account(db, auth.workspace_id), _account(db, auth.workspace_id, "instagram")
    workspace = db.get(Workspace, auth.workspace_id)
    made = ideas.generate(db, workspace, auth.user_id, count=1, language="en")
    assert made[0].format == "post" and made[0].platforms == ["facebook"] and made[0].account_ids == [fb.id]
    both = ContentIdea(workspace_id=auth.workspace_id, format="post", title="t", caption="text only",
                       account_ids=[fb.id, ig.id], platforms=["facebook", "instagram"])
    only_ig = ContentIdea(workspace_id=auth.workspace_id, format="post", title="t", caption="text only",
                          account_ids=[ig.id], platforms=["instagram"])
    db.add_all([both, only_ig])
    db.flush()
    result = ideas.approve(db, workspace, both, auth.user_id, mode="best_time")
    assert result["skipped_accounts"] == [ig.name] and [a.id for a in db.get(Post, result["post_id"]).accounts] == [fb.id]
    import pytest

    from app.core.errors import AppError
    with pytest.raises(AppError):
        ideas.approve(db, workspace, only_ig, auth.user_id, mode="best_time")
