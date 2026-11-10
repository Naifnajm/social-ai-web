"""Publishing engine (ported from the Odoo tests) + service contract + hooks + scheduling."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.db import utcnow
from app.core.errors import AppError, LimitReached, NotFound
from app.core.models import ApiLog, Notification
from app.modules.social import hooks, publishing, service, tasks
from app.modules.social.models import Post
from tests.social_common import account, image, jobs_in_test_session, public_https, video  # noqa: F401


@pytest.fixture()
def ws(auth):
    return auth.workspace_id


def _post(db, ws, accounts, content="Hello world", **kwargs):
    return service.create_post(db, ws, None, content=content, account_ids=[a.id for a in accounts], **kwargs)


def test_publish_facebook_and_x_with_variant(db, ws, mock_http):
    fb, x = account(db, ws, "facebook"), account(db, ws, "x")
    post = _post(db, ws, [fb, x], variants={"x": "Short for X"})

    def handler(method, url, kw):
        if "graph.facebook.com" in url:
            assert url.endswith("/111/feed")
            assert kw["data"]["message"] == "Hello world"
            return mock_http.response(200, {"id": "111_222"})
        assert url == "https://api.x.com/2/tweets"
        assert kw["json"]["text"] == "Short for X"
        return mock_http.response(201, {"data": {"id": "555"}})

    mock_http(handler)
    service.submit(db, post, None, action="publish")
    assert post.state == "posted"
    assert sorted(t.external_url for t in post.targets) == ["https://www.facebook.com/111_222",
                                                           "https://x.com/brand/status/555"]
    assert all(t.media_type == "text" and t.published_at for t in post.targets)
    assert post.published_at is not None


def test_one_network_failing_does_not_block_the_others_and_retry_sends_only_failed(db, ws, mock_http):
    fb, x = account(db, ws, "facebook"), account(db, ws, "x")
    post = _post(db, ws, [fb, x])

    def handler(method, url, kw):
        if "api.x.com" in url:
            return mock_http.response(401, {"title": "Unauthorized", "detail": "Token expired"})
        return mock_http.response(200, {"id": "111_333"})

    mock_http(handler)
    service.submit(db, post, None, action="publish")
    assert post.state == "partial"
    failed = [t for t in post.targets if t.state == "failed"]
    assert [t.account_id for t in failed] == [x.id]
    assert "Token expired" in failed[0].error
    assert x.state == "expired"

    x.state = "connected"
    calls = mock_http(lambda m, u, k: mock_http.response(201, {"data": {"id": "777"}}))
    before = len(calls)
    publishing.retry(db, post, None)
    assert len(calls) == before + 1 and "api.x.com" in calls[-1]["url"]
    assert post.state == "posted"


def test_rules_are_checked_before_sending(db, ws, mock_http):
    x = account(db, ws, "x")
    post = _post(db, ws, [x], content="a" * 300)
    mock_http(lambda m, u, k: pytest.fail("must not call the API"))
    with pytest.raises(AppError) as err:
        service.submit(db, post, None, action="publish")
    assert err.value.code == "invalid_post"
    assert "too long" in err.value.extra["problems"][0]["message"]
    # the engine also refuses on its own (e.g. a target added behind the composer's back)
    post.state = "publishing"
    publishing.sync_targets(db, post)
    publishing.run_publish(db, post.id)
    assert post.state == "failed"
    assert "too long" in post.targets[0].error


def test_instagram_requires_media_and_uses_public_url(db, ws, mock_http, public_https):
    ig = account(db, ws, "instagram")
    post = _post(db, ws, [ig])
    with pytest.raises(AppError) as err:
        service.submit(db, post, None, action="publish")
    assert "image" in err.value.detail

    media = image(db, ws)
    post = _post(db, ws, [ig], media_ids=[media.id])

    def handler(method, url, kw):
        if url.endswith("/999/media"):
            assert kw["data"]["image_url"].startswith("https://api.example.com/m/%d/" % media.id)
            return mock_http.response(200, {"id": "c1"})
        if url.endswith("/c1"):
            return mock_http.response(200, {"status_code": "FINISHED"})
        if url.endswith("/media_publish"):
            return mock_http.response(200, {"id": "m1"})
        return mock_http.response(200, {"permalink": "https://instagram.com/p/xyz"})

    mock_http(handler)
    service.submit(db, post, None, action="publish")
    assert post.state == "posted"
    assert post.targets[0].external_url == "https://instagram.com/p/xyz"
    assert post.targets[0].media_type == "image"


def test_instagram_refuses_a_private_server(db, ws, mock_http):
    ig = account(db, ws, "instagram")
    post = _post(db, ws, [ig], media_ids=[image(db, ws).id])
    mock_http(lambda m, u, k: pytest.fail("no call"))
    service.submit(db, post, None, action="publish")
    assert post.state == "failed"
    assert "public HTTPS" in post.targets[0].error


def test_linkedin_with_image_escapes_little_text(db, ws, mock_http):
    li = account(db, ws, "linkedin")
    post = _post(db, ws, [li], content="Big news (really) #launch", media_ids=[image(db, ws).id])

    def handler(method, url, kw):
        if "initializeUpload" in url:
            return mock_http.response(200, {"value": {"uploadUrl": "https://upload.linkedin.com/x",
                                                      "image": "urn:li:image:1"}})
        if url.startswith("https://upload.linkedin.com"):
            return mock_http.response(201, {})
        assert kw["json"]["content"] == {"media": {"id": "urn:li:image:1"}}
        assert kw["json"]["commentary"] == "Big news \\(really\\) #launch"
        return mock_http.response(201, {}, headers={"x-restli-id": "urn:li:share:42"})

    mock_http(handler)
    service.submit(db, post, None, action="publish")
    target = post.targets[0]
    assert target.external_id == "urn:li:share:42"
    assert target.hashtag_count == 1


def test_telegram_message_and_token_redacted_in_logs(db, ws, mock_http):
    tg = account(db, ws, "telegram")
    post = _post(db, ws, [tg])

    def handler(method, url, kw):
        assert "/bot123:ABC/sendMessage" in url
        return mock_http.response(200, {"ok": True, "result": {"message_id": 5, "chat": {"username": "brand"}}})

    mock_http(handler)
    service.submit(db, post, None, action="publish")
    assert post.targets[0].external_url == "https://t.me/brand/5"
    log = db.scalar(select(ApiLog).where(ApiLog.ref_model == "social_account", ApiLog.ref_id == tg.id))
    assert log.workspace_id == ws
    assert "ABC" not in log.endpoint


def test_carousel_and_video_rules(db, ws, mock_http):
    x = account(db, ws, "x")
    images = [image(db, ws, f"{i}.png").id for i in range(5)]
    post = _post(db, ws, [x], media_ids=images)
    found = publishing.problems(db, post)
    assert any("at most 4 images" in p["message"] for p in found)
    mixed = _post(db, ws, [x], media_ids=[images[0], video(db, ws).id])
    assert any("one video" in p["message"] for p in publishing.problems(db, mixed))


def test_platform_media_override_per_network(db, ws, mock_http):
    fb, tg = account(db, ws, "facebook"), account(db, ws, "telegram")
    square, vertical = image(db, ws, "square.png"), image(db, ws, "vertical.png")
    post = _post(db, ws, [fb, tg], media_ids=[square.id], platform_media={"telegram": [vertical.id]})
    sent = {}

    def handler(method, url, kw):
        if "telegram" in url:
            sent["telegram"] = kw["files"]["photo"][0]
            return mock_http.response(200, {"ok": True, "result": {"message_id": 1, "chat": {}}})
        sent["facebook"] = kw["files"]["source"][0]
        return mock_http.response(200, {"id": "p", "post_id": "111_1"})

    mock_http(handler)
    service.submit(db, post, None, action="publish")
    assert sent == {"facebook": "square.png", "telegram": "vertical.png"}


def test_story_and_feed_story(db, ws, mock_http, public_https):
    ig, x = account(db, ws, "instagram"), account(db, ws, "x")
    media = image(db, ws)
    post = _post(db, ws, [ig, x], media_ids=[media.id], publish_as="feed_story", content="Hi")
    calls = []

    def handler(method, url, kw):
        calls.append(url)
        if url.endswith("/999/media"):
            return mock_http.response(200, {"id": "story" if kw["data"].get("media_type") == "STORIES" else "c1"})
        if url.endswith("/media_publish"):
            return mock_http.response(200, {"id": "s1" if kw["data"]["creation_id"] == "story" else "m1"})
        if "api.x.com" in url and url.endswith("/tweets"):
            return mock_http.response(201, {"data": {"id": "9"}})
        if "api.x.com" in url:
            return mock_http.response(200, {"data": {"id": "mid"}})
        return mock_http.response(200, {"status_code": "FINISHED", "permalink": "https://instagram.com/p/1"})

    mock_http(handler)
    service.submit(db, post, None, action="publish")
    by_platform = {t.platform: t for t in post.targets}
    assert by_platform["instagram"].story_state == "posted"
    assert by_platform["instagram"].story_url == "https://www.instagram.com/stories/mybrand/"
    assert by_platform["x"].story_state == "skipped"  # X has no stories: feed only, not a failure
    assert post.state == "posted"

    # story only on a network without stories is refused before sending
    story_only = _post(db, ws, [x], media_ids=[media.id], publish_as="story")
    with pytest.raises(AppError):
        service.submit(db, story_only, None, action="publish")


def test_failed_story_is_retried_alone(db, ws, mock_http, public_https):
    fb = account(db, ws, "facebook")
    post = _post(db, ws, [fb], media_ids=[image(db, ws).id], publish_as="feed_story")

    def first(method, url, kw):
        if url.endswith("/photo_stories"):
            return mock_http.response(400, {"error": {"message": "Stories not allowed"}})
        if kw.get("data", {}).get("published") == "false":
            return mock_http.response(200, {"id": "ph1"})
        return mock_http.response(200, {"id": "ph", "post_id": "111_5"})

    mock_http(first)
    service.submit(db, post, None, action="publish")
    target = post.targets[0]
    assert (target.state, target.story_state, post.state) == ("posted", "failed", "partial")

    def second(method, url, kw):
        assert "photo_stories" in url or kw["data"].get("published") == "false"  # never the feed again
        return mock_http.response(200, {"id": "ph2", "post_id": "st1", "success": True})

    calls = mock_http(second)
    before = len(calls)
    publishing.retry(db, post, None)
    assert len(calls) == before + 2
    assert (target.story_state, post.state) == ("posted", "posted")


def test_never_double_publish(db, ws, mock_http):
    fb = account(db, ws, "facebook")
    post = _post(db, ws, [fb])
    calls = mock_http(lambda m, u, k: mock_http.response(200, {"id": "111_1"}))
    service.submit(db, post, None, action="publish")
    assert len(calls) == 1
    # running the job again (duplicate job, scheduler race) sends nothing
    post.state = "publishing"
    tasks.publish_post(post.id)
    assert len(calls) == 1
    assert post.state == "posted"
    with pytest.raises(AppError):
        service.submit(db, post, None, action="publish")
    # a target already claimed by another worker is left alone
    other = _post(db, ws, [fb])
    other.state = "publishing"
    publishing.sync_targets(db, other)
    other.targets[0].state = "sending"
    db.flush()
    publishing.run_publish(db, other.id)
    assert len(calls) == 1 and other.state == "publishing"


def test_schedule_and_periodic_task(db, ws, mock_http):
    fb = account(db, ws, "facebook")
    post = _post(db, ws, [fb])
    service.submit(db, post, None, action="schedule", when=utcnow() + timedelta(hours=1))
    assert post.state == "scheduled" and len(post.targets) == 1
    mock_http(lambda m, u, k: pytest.fail("too early"))
    assert tasks.publish_due_posts() == []
    assert post.state == "scheduled"

    post.scheduled_at = utcnow() - timedelta(minutes=1)
    db.flush()
    mock_http(lambda m, u, k: mock_http.response(200, {"id": "111_9"}))
    assert tasks.publish_due_posts() == [post.id]
    db.refresh(post)
    assert post.state == "posted"
    assert tasks.publish_due_posts() == []


def test_schedule_in_past_rejected_and_unschedule(db, ws):
    fb = account(db, ws, "facebook")
    post = _post(db, ws, [fb])
    with pytest.raises(AppError):
        service.submit(db, post, None, action="schedule", when=utcnow() - timedelta(days=1))
    service.submit(db, post, None, action="schedule", when=utcnow() + timedelta(days=1))
    service.submit(db, post, None, action="draft")
    assert post.state == "draft"


def test_best_time_schedules_in_the_future(db, ws):
    ig = account(db, ws, "instagram")
    post = _post(db, ws, [ig], media_ids=[image(db, ws).id])
    service.submit(db, post, None, action="best_time")
    assert post.state == "scheduled"
    assert post.scheduled_at > utcnow()
    slots = service.next_best_slots(db, ws, ["instagram"], count=3)
    assert len(slots) == 3 and all(s["at"] > utcnow() for s in slots)
    assert slots == sorted(slots, key=lambda s: s["at"])


def test_token_refresh_before_publish(db, ws, mock_http, monkeypatch):
    from app.modules.social import oauth
    oauth.platform_apps.cache_clear()
    monkeypatch.setenv("SAI_X_CLIENT_ID", "cid")
    monkeypatch.setenv("SAI_X_CLIENT_SECRET", "sec")
    x = account(db, ws, "x", refresh_token="rt", token_expires_at=utcnow() - timedelta(minutes=1),
                extra={"oauth_app": "platform"})
    post = _post(db, ws, [x])

    def handler(method, url, kw):
        if url.endswith("/oauth2/token"):
            assert kw["headers"]["Authorization"].startswith("Basic ")
            return mock_http.response(200, {"access_token": "new", "refresh_token": "rt2", "expires_in": 7200})
        assert kw["headers"]["Authorization"] == "Bearer new"
        return mock_http.response(201, {"data": {"id": "1"}})

    mock_http(handler)
    service.submit(db, post, None, action="publish")
    oauth.platform_apps.cache_clear()
    assert post.state == "posted"
    assert x.refresh_token == "rt2" and x.access_token == "new"


def test_hooks_are_called(db, ws, mock_http):
    fb = account(db, ws, "facebook")
    seen = {"filter": [], "before": [], "after": [], "limit": []}

    def text_filter(db_, post, acc, text):
        seen["filter"].append(acc.platform)
        return text + " https://s.example/1"

    def before(db_, post, user_id, action):
        seen["before"].append(action)

    def after(db_, post):
        seen["after"].append(post.state)

    def limit(db_, workspace_id):
        seen["limit"].append(workspace_id)

    for name, fn in (("TEXT_FILTERS", text_filter), ("BEFORE_SUBMIT", before), ("AFTER_PUBLISH", after),
                     ("POST_LIMIT_CHECKS", limit)):
        getattr(hooks, name).append(fn)
    try:
        def handler(method, url, kw):
            assert kw["data"]["message"] == "Hello world https://s.example/1"
            return mock_http.response(200, {"id": "111_1"})

        mock_http(handler)
        post = _post(db, ws, [fb])
        service.submit(db, post, None, action="publish")
    finally:
        hooks.TEXT_FILTERS.remove(text_filter)
        hooks.BEFORE_SUBMIT.remove(before)
        hooks.AFTER_PUBLISH.remove(after)
        hooks.POST_LIMIT_CHECKS.remove(limit)
    assert seen == {"filter": ["facebook"], "before": ["publish"], "after": ["posted"], "limit": [ws]}


def test_limit_and_before_submit_hooks_can_block_or_ask_approval(db, ws):
    fb = account(db, ws, "facebook")
    post = _post(db, ws, [fb])

    def full(db_, workspace_id):
        raise LimitReached("Monthly posts limit reached.", code="limit")

    hooks.POST_LIMIT_CHECKS.append(full)
    try:
        with pytest.raises(LimitReached):
            service.submit(db, post, None, action="publish")
    finally:
        hooks.POST_LIMIT_CHECKS.remove(full)

    def review(db_, post_, user_id, action):
        return "to_approve"

    hooks.BEFORE_SUBMIT.append(review)
    try:
        service.submit(db, post, None, action="publish")
    finally:
        hooks.BEFORE_SUBMIT.remove(review)
    assert post.state == "to_approve" and post.requested_action == "publish"


def test_create_post_checks_workspace_ids(client, db):
    from tests.conftest import signup
    a = signup(client, email="pa@example.com", workspace="PA")
    b = signup(client, email="pb@example.com", workspace="PB")
    fb_b = account(db, b.workspace_id, "facebook")
    media_b = image(db, b.workspace_id)
    with pytest.raises(NotFound):
        service.create_post(db, a.workspace_id, a.user_id, content="x", account_ids=[fb_b.id])
    with pytest.raises(NotFound):
        service.create_post(db, a.workspace_id, a.user_id, content="x", media_ids=[media_b.id])
    wa = account(db, a.workspace_id, "whatsapp")
    with pytest.raises(AppError) as err:
        service.create_post(db, a.workspace_id, a.user_id, content="x", account_ids=[wa.id])
    assert err.value.code == "inbox_only_account"
    post = service.create_post(db, a.workspace_id, a.user_id, content="First line here\nsecond",
                               media_ids=[image(db, a.workspace_id).id], story_media_ids=[], source_ref="quick")
    assert post.name == "First line here" and post.state == "draft" and post.source_ref == "quick"


def test_failure_notifies_author(db, auth, mock_http):
    fb = account(db, auth.workspace_id, "facebook")
    post = service.create_post(db, auth.workspace_id, auth.user_id, content="Hello", account_ids=[fb.id])
    mock_http(lambda m, u, k: mock_http.response(500, {"error": {"message": "boom"}}))
    service.submit(db, post, auth.user_id, action="publish")
    assert post.state == "failed"
    notes = db.scalars(select(Notification).where(Notification.user_id == auth.user_id,
                                                  Notification.kind == "post.failed")).all()
    assert len(notes) == 1


def test_stuck_targets_are_released_not_resent(db, ws):
    fb = account(db, ws, "facebook")
    post = _post(db, ws, [fb])
    post.state = "publishing"
    publishing.sync_targets(db, post)
    target = post.targets[0]
    target.state = "sending"
    db.flush()
    from sqlalchemy import update

    from app.modules.social.models import PostTarget
    db.execute(update(PostTarget).where(PostTarget.id == target.id).values(updated_at=utcnow() - timedelta(hours=1)))
    db.expire_all()
    assert publishing.release_stuck_targets(db) == 1
    post = db.get(Post, post.id)
    assert post.state == "failed" and "may already be published" in post.targets[0].error


def test_problems_are_translated(db, ws):
    from app.core.i18n import set_locale
    x = account(db, ws, "x")
    post = _post(db, ws, [x], content="a" * 300)
    set_locale("ar")
    try:
        message = publishing.problems(db, post)[0]["message"]
    finally:
        set_locale("en")
    assert message == "النص أطول من المسموح على X (300 / 280 حرفًا)."
