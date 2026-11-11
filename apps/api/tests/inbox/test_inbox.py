"""Inbox + AI assistant — port of the Odoo module's tests (social_ai_bridge/tests/test_inbox.py)."""
import json
import sys
import time
import types
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.models import Media, Notification
from app.modules.auth.models import User
from app.modules.inbox import service, sources, webhook_auth
from app.modules.inbox.bot import parse_bot_answer
from app.modules.inbox.models import BotTrigger, Contact
from app.modules.inbox.router import inbox_stats
from app.modules.inbox.sources import account_state
from app.modules.inbox.text import normalize_text, picture_expired, utcnow
from app.modules.social.models import PUBLISH_PLATFORMS, Post, PostTarget
from app.modules.workspaces.settings import set_setting
from .helpers import answer


def _user(ib):
    return ib.db.get(User, ib.auth.user_id)


# ====================================================================== assistant
def test_facebook_message_creates_conversation_contact_and_auto_reply(ib):
    calls = ib.deliver(ib.fb_message("Hi, when are you open?", "m_in_1"))
    [conv] = ib.convs(ib.fb)
    assert conv.kind == "dm" and conv.external_thread_id == "PSID1"
    assert conv.customer_name == "Sara Ali"
    assert conv.contact and conv.contact.name == "Sara Ali"
    assert conv.intent == "question"
    send = [c for c in ib.sends(calls) if c["url"].endswith("/PAGE1/messages")]
    assert len(send) == 1
    assert send[0]["json"]["recipient"] == {"id": "PSID1"}
    assert send[0]["json"]["message"]["text"] == "Hello! We are open 9-17."
    assert send[0]["json"]["messaging_type"] == "RESPONSE"
    [out] = ib.messages(conv, direction="out")
    assert out.state == "sent" and out.is_bot and out.external_id.startswith("m_out_")
    assert ib.messages(conv, direction="in")[0].bot_state == "done"
    assert conv.first_response_at
    # the prompt carries the customer's message and the JSON contract
    prompt = ib.ai_prompts[0]
    assert "Hi, when are you open?" in prompt["user"]
    assert "customer's language" in prompt["system"]
    # the same person writing again re-uses the conversation and the contact
    ib.deliver(ib.fb_message("Thanks!", "m_in_2"))
    assert len(ib.convs(ib.fb)) == 1
    assert ib.db.scalar(select(func.count()).select_from(Contact).where(Contact.name == "Sara Ali")) == 1


def test_suggest_mode_only_drafts(ib, client):
    ib.fb.bot_settings = {"mode": "suggest"}
    calls = ib.deliver(ib.fb_message("Do you deliver to Utrecht?", "m_in_s"))
    [conv] = ib.convs(ib.fb)
    assert not [c for c in ib.sends(calls) if c["url"].endswith("/messages")]
    [suggestion] = ib.messages(conv, state="suggested")
    assert suggestion.body == "Hello! We are open 9-17."
    assert conv.state == "open"
    # a human sends the (edited) suggestion
    calls = ib.http()
    r = client.post(f"/api/inbox/suggestions/{suggestion.id}/send", json={"body": "Yes, we deliver to Utrecht!"},
                    headers=ib.auth.headers)
    assert r.status_code == 200, r.text
    assert r.json()["message"]["state"] == "sent"
    assert calls[0]["json"]["message"]["text"] == "Yes, we deliver to Utrecht!"
    assert not ib.messages(conv, state="suggested")
    assert conv.bot_paused


def test_low_confidence_hands_over_without_sending(ib):
    ib.ai = answer("Maybe we can refund you?", confidence=40, intent="complaint", sentiment="negative")
    calls = ib.deliver(ib.fb_message("My order is broken, I want my money back", "m_in_low"))
    [conv] = ib.convs(ib.fb)
    assert not [c for c in ib.sends(calls) if c["url"].endswith("/messages")]
    assert conv.state == "pending"
    assert conv.sentiment == "negative"
    assert "40" in conv.handover_reason
    assert ib.messages(conv, state="suggested")
    # the team is told (in-app + push): no assignee → admins / owners
    note = ib.db.scalar(select(Notification).where(Notification.kind == "inbox.handover"))
    assert note and note.user_id == ib.auth.user_id and note.link == f"/inbox/{conv.id}"


def test_handover_message_sent_once(ib):
    set_setting(ib.db, ib.ws, "inbox.handover_message", "A colleague will reply soon.")
    ib.ai = answer("", confidence=10, handover=True, handover_reason="Refund request",
                   handover_message="Een collega antwoordt snel.")
    calls = ib.deliver(ib.fb_message("Ik wil mijn geld terug", "m_in_h1"))
    texts = [c["json"]["message"]["text"] for c in ib.sends(calls) if c["url"].endswith("/messages")]
    assert texts == ["Een collega antwoordt snel."]
    [conv] = ib.convs(ib.fb)
    assert conv.state == "pending"
    assert conv.handover_reason == "Refund request"
    calls = ib.deliver(ib.fb_message("Hallo??", "m_in_h2"))
    assert not [c for c in ib.sends(calls) if c["url"].endswith("/messages")]


def test_unreadable_ai_answer_hands_over(ib):
    ib.ai = "Sorry, I cannot produce JSON today."
    ib.deliver(ib.fb_message("Hello", "m_in_bad"))
    [conv] = ib.convs(ib.fb)
    assert conv.state == "pending"


def test_ai_provider_missing_is_an_error_not_a_handover(ib):
    ib.ai = AppError("No AI provider is set up yet.", code="no_ai_provider")
    ib.deliver(ib.fb_message("Hello", "m_in_noai"))
    [conv] = ib.convs(ib.fb)
    assert conv.state == "open"
    assert conv.bot_error
    assert ib.messages(conv, direction="in")[0].bot_state == "error"


def test_parse_bot_answer():
    parsed = parse_bot_answer('```json\n{"reply": "مرحبا", "confidence": "88", "handover": "false", '
                              '"intent": "ORDER"}\n```')
    assert parsed["reply"] == "مرحبا"
    assert parsed["confidence"] == 88
    assert parsed["handover"] is False
    assert parsed["intent"] == "order"
    assert parse_bot_answer('Sure! {"reply": "Hi", "confidence": 0.9} hope it helps')["confidence"] == 90
    assert parse_bot_answer("nope")["handover"] is True
    assert parse_bot_answer({"reply": "x", "sentiment": "furious"})["sentiment"] == "neutral"


def test_dedupe_repeated_webhook(ib):
    payload = ib.fb_message("Hello there", "m_dup")
    calls = ib.deliver(payload)
    calls += ib.deliver(payload)
    [conv] = ib.convs(ib.fb)
    assert len(ib.messages(conv, direction="in")) == 1
    assert len([c for c in ib.sends(calls) if c["url"].endswith("/messages")]) == 1
    assert len(ib.ai_prompts) == 1


def test_echoes(ib, monkeypatch):
    from app.modules.inbox import config
    monkeypatch.setattr(config.inbox_settings(), "meta_app_id", "4242")
    ib.deliver(ib.fb_message("Hi", "m_e1"))
    [conv] = ib.convs(ib.fb)
    count = len(ib.messages(conv))
    # our own API message coming back: ignored
    echo = ib.fb_message("Hello! We are open 9-17.", "m_echo_ours", sender="PAGE1", is_echo=True, app_id=4242)
    echo["entry"][0]["messaging"][0]["recipient"] = {"id": "PSID1"}
    ib.deliver(echo)
    assert len(ib.messages(conv)) == count
    assert not conv.bot_paused
    # a colleague answering in Meta Business Suite: stored, and the assistant steps back
    echo = ib.fb_message("I'll check for you", "m_echo_human", sender="PAGE1", is_echo=True, app_id=263902037430900)
    echo["entry"][0]["messaging"][0]["recipient"] = {"id": "PSID1"}
    ib.deliver(echo)
    [human] = ib.messages(conv, external_id="m_echo_human")
    assert human.direction == "out"
    assert conv.bot_paused


def test_human_reply_pauses_bot_until_closed(ib, client):
    ib.deliver(ib.fb_message("Hi", "m_p1"))
    [conv] = ib.convs(ib.fb)
    ib.http()
    r = client.post(f"/api/inbox/conversations/{conv.id}/messages", json={"body": "Hi Sara, Tom here."},
                    headers=ib.auth.headers)
    assert r.status_code == 201, r.text
    assert conv.bot_paused
    assert conv.assignee_id == ib.auth.user_id
    ib.ai_prompts.clear()
    ib.deliver(ib.fb_message("Great, thanks Tom", "m_p2"))
    assert not ib.ai_prompts
    assert ib.messages(conv, external_id="m_p2")[0].bot_state == "skipped"
    r = client.patch(f"/api/inbox/conversations/{conv.id}", json={"state": "done"}, headers=ib.auth.headers)
    assert r.status_code == 200 and not conv.bot_paused
    calls = ib.deliver(ib.fb_message("One more question", "m_p3"))
    assert conv.state == "open"
    assert len(ib.ai_prompts) == 1
    assert [c for c in ib.sends(calls) if c["url"].endswith("/messages")]


def test_rate_limit(ib):
    for index in range(8):
        ib.deliver(ib.fb_message("question %s" % index, "m_rate_%s" % index))
    [conv] = ib.convs(ib.fb)
    assert len(ib.messages(conv, is_bot=True, state="sent")) == 6
    assert conv.state == "pending"


def test_24h_window(ib):
    ib.deliver(ib.fb_message("Hi", "m_w1"))
    [conv] = ib.convs(ib.fb)
    conv.last_inbound_at = utcnow() - timedelta(days=2)
    calls = ib.http()
    with pytest.raises(AppError) as exc:
        service.send_reply(ib.db, conv, "Sorry for the late answer", "dm", user=_user(ib))
    assert "24" in exc.value.detail
    assert not calls
    # with the HUMAN_AGENT option a human can still answer within 7 days
    set_setting(ib.db, ib.ws, "inbox.human_agent_tag", True)
    calls = ib.http()
    service.send_reply(ib.db, conv, "Sorry for the late answer", "dm", user=_user(ib))
    assert calls[0]["json"]["tag"] == "HUMAN_AGENT"
    assert calls[0]["json"]["messaging_type"] == "MESSAGE_TAG"
    # …but never the assistant
    with pytest.raises(AppError):
        service.send_reply(ib.db, conv, "bot", "dm", is_bot=True)
    # WhatsApp has no such tag
    wa = service.find_or_create(ib.db, ib.wa, "dm", "31600000000", customer={"name": "Ali"})
    wa.last_inbound_at = utcnow() - timedelta(hours=30)
    with pytest.raises(AppError):
        service.send_reply(ib.db, wa, "hello", "dm", user=_user(ib))


def test_instagram_comment_trigger_public_and_private_reply(ib):
    trigger = BotTrigger(workspace_id=ib.ws, name="Prices", keywords="price, سعر", account_ids=[ib.ig.id],
                         public_reply="Thanks {name}! Check your messages 📩", dm_text="Hi {name}, our prices: …")
    ib.db.add(trigger)
    ib.db.flush()
    calls = ib.deliver(ib.ig_comment("What is the سِعر please?", "C1"))
    [conv] = ib.convs(ib.ig, kind="comment")
    assert conv.external_thread_id == "C1"
    private = [c for c in calls if c["url"].endswith("/me/messages")]
    assert private[0]["json"]["recipient"] == {"comment_id": "C1"}
    assert private[0]["json"]["message"]["text"] == "Hi sara, our prices: …"
    public = [c for c in calls if c["url"].endswith("/C1/replies")]
    assert public[0]["data"]["message"] == "Thanks sara! Check your messages 📩"
    assert not ib.ai_prompts  # handled by the trigger, no AI needed
    assert trigger.hit_count == 1
    sent = ib.messages(conv, direction="out")
    assert sorted(m.channel for m in sent) == ["private", "public"]
    assert {m.trigger_id for m in sent} == {trigger.id}
    # the same person commenting again does not get the campaign twice
    calls = ib.deliver(ib.ig_comment("price?", "C2"))
    assert not [c for c in calls if c["url"].endswith("/me/messages")]
    assert trigger.hit_count == 1


def test_keyword_normalization():
    assert normalize_text("السِّعْر") == normalize_text("السعر")
    assert normalize_text("أسعار") == normalize_text("اسعار")
    assert normalize_text("مكتبة") == normalize_text("مكتبه")
    assert normalize_text("PRÍCE") == "price"


def test_offensive_comment_is_hidden(ib):
    ib.ig.bot_settings = {"mode": "auto", "comment_mode": "suggest", "hide_offensive": True}
    ib.ai = answer("", confidence=95, intent="spam", sentiment="negative", hide=True)
    calls = ib.deliver(ib.ig_comment("You are all idiots, buy followers at spam.example", "C9", user="BAD"))
    hide = [c for c in calls if c["url"].endswith("/C9") and c["method"] == "POST"]
    assert hide[0]["data"]["hide"] == "true"
    [conv] = ib.convs(ib.ig, external_thread_id="C9")
    assert conv.is_hidden
    assert conv.state == "done"
    assert conv.intent == "spam"
    assert not [c for c in calls if c["url"].endswith("/replies")]


def test_facebook_comment_private_reply_when_details_needed(ib):
    ib.ai = answer("Hi Sara, please send us your order number here.", confidence=90, private_reply=True,
                   public_reply="We've sent you a message 📩")
    payload = {"object": "page", "entry": [{"id": "PAGE1", "time": int(time.time()), "changes": [{
        "field": "feed", "value": {"item": "comment", "verb": "add", "comment_id": "P_1_C5",
                                   "post_id": "PAGE1_77", "parent_id": "PAGE1_77",
                                   "from": {"id": "FBU1", "name": "Sara Ali"}, "message": "Where is my order?",
                                   "created_time": int(time.time())}}]}]}
    calls = ib.deliver(payload)
    private = [c for c in calls if c["url"].endswith("/PAGE1/messages")]
    assert private[0]["json"]["recipient"] == {"comment_id": "P_1_C5"}
    public = [c for c in calls if c["url"].endswith("/P_1_C5/comments")]
    assert public[0]["data"]["message"] == "We've sent you a message 📩"
    # our own public reply coming back through the feed webhook is not answered again
    mine = {"object": "page", "entry": [{"id": "PAGE1", "time": int(time.time()), "changes": [{
        "field": "feed", "value": {"item": "comment", "verb": "add", "comment_id": "P_1_C6",
                                   "post_id": "PAGE1_77", "parent_id": "P_1_C5",
                                   "from": {"id": "PAGE1", "name": "Brand Page"},
                                   "message": "We've sent you a message 📩", "created_time": int(time.time())}}]}]}
    ib.ai_prompts.clear()
    ib.deliver(mine)
    assert not ib.ai_prompts
    assert len(ib.convs(ib.fb, external_thread_id="P_1_C5")) == 1


def test_poll_facebook_comments(ib):
    post = Post(workspace_id=ib.ws, content="New menu!", state="posted")
    ib.db.add(post)
    ib.db.flush()
    target = PostTarget(workspace_id=ib.ws, post_id=post.id, account_id=ib.fb.id, platform="facebook",
                        state="posted", external_id="PAGE1_99", external_url="https://www.facebook.com/PAGE1_99",
                        published_at=utcnow())
    ib.db.add(target)
    ib.db.flush()
    now = utcnow()
    ib.comments["PAGE1_99"] = [  # newest first, like the Graph API
        {"id": "C_2", "message": "Thank you!", "from": {"id": "PAGE1", "name": "Brand Page"},
         "created_time": (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S+0000"), "parent": {"id": "C_1"}},
        {"id": "C_1", "message": "Looks delicious 😍", "from": {"id": "U5", "name": "Omar"},
         "created_time": (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S+0000")},
    ]
    ib.fb.bot_settings = {"mode": "auto", "comment_mode": "suggest"}
    ib.http()
    result = sources.poll_accounts(ib.db, [ib.fb])
    ib.run_bot()
    assert result["new"] == 2
    [conv] = ib.convs(ib.fb, kind="comment")
    assert conv.post_target_id == target.id
    assert conv.post_preview == "New menu!"
    assert conv.customer_name == "Omar"
    assert [m.direction for m in ib.messages(conv) if m.state != "suggested"] == ["in", "out"]
    assert not ib.ai_prompts  # already answered by the page
    assert account_state(ib.db, ib.fb).last_sync_at
    ib.http()
    assert sources.poll_accounts(ib.db, [ib.fb])["new"] == 0


def test_poll_messenger_conversations(ib):
    now = utcnow()

    def stamp(minutes):
        return (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S+0000")

    ib.threads = [{"id": "t_1", "participants": {"data": [{"id": "PSID7", "name": "Huda"},
                                                         {"id": "PAGE1", "name": "Brand Page"}]},
                   "messages": {"data": [  # newest first
                       {"id": "m_poll_3", "message": "And on Sunday?", "from": {"id": "PSID7"},
                        "to": {"data": [{"id": "PAGE1"}]}, "created_time": stamp(1)},
                       {"id": "m_poll_2", "message": "We open at 9.", "from": {"id": "PAGE1"},
                        "to": {"data": [{"id": "PSID7"}]}, "created_time": stamp(3)},
                       {"id": "m_poll_1", "message": "When do you open?", "from": {"id": "PSID7"},
                        "to": {"data": [{"id": "PAGE1"}]}, "created_time": stamp(5)}]}}]
    ib.http()
    assert sources.poll_accounts(ib.db, [ib.fb])["new"] == 3
    ib.run_bot()
    [conv] = ib.convs(ib.fb, kind="dm")
    assert conv.customer_name == "Huda"  # the thread's name wins over the profile's
    assert conv.avatar_url == "https://cdn.example.com/sara.jpg"  # polled threads get the picture too
    assert conv.contact.name == "Huda"
    assert [m.body for m in ib.messages(conv, state="sent")] == ["We open at 9.", "Hello! We are open 9-17."]
    # the question answered by the page is not answered again; only the last one is
    assert len(ib.ai_prompts) == 1
    assert "And on Sunday?" in ib.ai_prompts[0]["user"]
    assert "NEW MESSAGE TO ANSWER" in ib.ai_prompts[0]["user"]


def test_picture_expired():
    future, past = int(time.time()) + 10 * 86400, int(time.time()) - 60
    assert picture_expired(None) and picture_expired("")
    assert not picture_expired("https://cdn.example.com/sara.jpg")  # no expiry parameter
    assert not picture_expired("https://platform-lookaside.fbsbx.com/platform/profilepic/?psid=1&ext=%d" % future)
    assert picture_expired("https://platform-lookaside.fbsbx.com/platform/profilepic/?psid=1&ext=%d" % past)
    assert picture_expired("https://scontent.xx.fbcdn.net/v/p.jpg?oe=%X" % past)
    assert not picture_expired("https://scontent.xx.fbcdn.net/v/p.jpg?oe=%X" % future)


def test_expired_profile_picture_is_refreshed(ib):
    ib.deliver(ib.fb_message("Hi", "m_pic1"))
    [conv] = ib.convs(ib.fb, kind="dm")
    assert conv.avatar_url == "https://cdn.example.com/sara.jpg"
    calls = ib.deliver(ib.fb_message("Again", "m_pic2"))  # picture still valid: no second profile call
    assert not [c for c in calls if c["method"] == "GET" and c["url"].endswith("/PSID1")]
    conv.avatar_url = "https://platform-lookaside.fbsbx.com/platform/profilepic/?psid=PSID1&ext=%d" % (time.time() - 60)
    ib.db.flush()
    calls = ib.deliver(ib.fb_message("Still there?", "m_pic3"))
    assert [c for c in calls if c["method"] == "GET" and c["url"].endswith("/PSID1")]
    assert conv.avatar_url == "https://cdn.example.com/sara.jpg"
    assert conv.customer_name == "Sara Ali"


def test_inbox_stats(ib, client):
    ib.deliver(ib.fb_message("Hi", "m_s1"))
    ib.fb.bot_settings = {"mode": "suggest"}
    ib.deliver(ib.fb_message("Hello", "m_s2", sender="PSID2"))
    [conv2] = ib.convs(ib.fb, external_thread_id="PSID2")
    ib.http()
    assert client.post(f"/api/inbox/conversations/{conv2.id}/messages", json={"body": "Hello from a human"},
                       headers=ib.auth.headers).status_code == 201
    conv2.state = "done"
    ib.db.flush()
    stats = inbox_stats(ib.db, ib.ws, 30)
    assert stats.conversations == 2
    assert (stats.done, stats.open) == (1, 1)
    assert (stats.replies, stats.bot_replies, stats.bot_share) == (2, 1, 50.0)
    assert stats.avg_first_response_minutes >= 0
    assert stats.by_platform[0].platform == "facebook"
    assert stats.sentiment["neutral"] == 2
    api = client.get("/api/inbox/stats?days=7", headers=ib.auth.headers).json()
    assert api["conversations"] == 2 and api["days"] == 7


def test_inbox_ui_api(ib, client):
    ib.fb.bot_settings = {"mode": "suggest"}
    ib.deliver(ib.fb_message("Hi", "m_ui"))
    [conv] = ib.convs(ib.fb)
    h = ib.auth.headers
    meta = client.get("/api/inbox/meta", headers=h).json()
    assert "whatsapp" in meta["platforms"] and meta["can_manage"] and meta["has_provider"]
    data = client.get("/api/inbox/conversations", params={"folder": "all"}, headers=h).json()
    assert data["items"][0]["id"] == conv.id
    assert data["items"][0]["has_suggestion"]
    assert data["counts"]["unassigned"] == 1 and data["counts"]["unread"] == 1
    thread = client.get(f"/api/inbox/conversations/{conv.id}", headers=h).json()
    assert thread["suggestion"]["body"] == "Hello! We are open 9-17."
    assert thread["window"]["limited"] and thread["window"]["open"]
    assert not conv.unread
    tag = client.post("/api/inbox/tags", json={"name": "Wholesale"}, headers=h).json()
    assert client.post("/api/inbox/tags", json={"name": "wholesale"}, headers=h).json()["id"] == tag["id"]
    thread = client.patch(f"/api/inbox/conversations/{conv.id}", headers=h, json={
        "tag_ids": [tag["id"]], "assignee_id": ib.auth.user_id, "note": "Big customer", "unread": True}).json()
    assert thread["tags"][0]["name"] == "Wholesale" and thread["assignee"]["id"] == ib.auth.user_id
    assert client.get("/api/inbox/conversations", params={"folder": "mine"}, headers=h).json()["counts"]["mine"] == 1
    assert conv.note == "Big customer"
    assert len(client.get("/api/inbox/conversations", params={"search": "Sara"}, headers=h).json()["items"]) == 1
    assert len(client.get("/api/inbox/conversations", params={"search": "Hi"}, headers=h).json()["items"]) == 1
    assert not client.get("/api/inbox/conversations", params={"platform": "telegram"}, headers=h).json()["items"]
    assert len(client.get("/api/inbox/conversations", params={"tag_id": tag["id"]}, headers=h).json()["items"]) == 1
    ib.ai = answer("Fresh draft")
    thread = client.post(f"/api/inbox/conversations/{conv.id}/suggest", headers=h).json()
    assert thread["suggestion"]["body"] == "Fresh draft"
    thread = client.delete(f"/api/inbox/suggestions/{thread['suggestion']['id']}", headers=h).json()
    assert thread["suggestion"] is None
    assert client.get("/api/inbox/unread", headers=h).json() == {"unread": 1, "pending": 0}
    thread = client.patch(f"/api/inbox/conversations/{conv.id}", json={"assignee_id": None}, headers=h).json()
    assert thread["assignee"] is None


def test_whatsapp_accounts_are_inbox_only(ib, client):
    assert "whatsapp" not in PUBLISH_PLATFORMS
    calls = ib.http(lambda m, u, k: ib._mock_http.response(body={"verified_name": "Cafe", "display_phone_number":
                                                                 "+31 6 1234"}))
    r = client.post("/api/inbox/whatsapp-accounts", headers=ib.auth.headers, json={
        "name": "Cafe WhatsApp", "provider": "cloud", "phone_number_id": "PN77", "access_token": "EAAG-secret"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["platform"] == "whatsapp" and data["state"] == "connected" and data["has_token"]
    assert data["webhook_kind"] == "meta" and "EAAG-secret" not in r.text
    assert calls[0]["headers"]["Authorization"] == "Bearer EAAG-secret"
    r = client.post("/api/inbox/whatsapp-accounts", headers=ib.auth.headers, json={
        "name": "Twilio", "provider": "twilio", "twilio_account_sid": "AC9", "twilio_auth_token": "tok",
        "whatsapp_number": "+31612340000", "verify": False})
    assert r.status_code == 201
    assert r.json()["webhook_kind"] == "twilio" and r.json()["webhook_url"].endswith(f"/webhooks/twilio/{r.json()['id']}")


# ====================================================================== channels
def test_telegram_message_and_reply(ib):
    ib.http()
    calls = ib.http()
    sources.telegram_webhook(ib.db, ib.tg, ib.tg_update("مرحبا، هل لديكم توصيل؟"))
    ib.run_bot()
    [conv] = ib.convs(ib.tg)
    assert conv.external_thread_id == "7001"
    assert conv.customer_name == "Lina" and conv.customer_handle == "@lina"
    send = [c for c in calls if c["url"].endswith("/sendMessage")]
    assert send[0]["data"]["chat_id"] == "7001"
    [out] = ib.messages(conv, direction="out")
    assert out.external_id.startswith("7001:")
    # group messages and channel posts are not inbox conversations
    group = ib.tg_update("hi all", update_id=2, message_id=11)
    group["message"]["chat"] = {"id": -100, "type": "group"}
    assert sources.telegram_webhook(ib.db, ib.tg, group) == 0


def test_telegram_photo_without_hook(ib):
    update = ib.tg_update(None, photo=[{"file_id": "small", "file_size": 10, "width": 90},
                                       {"file_id": "big", "file_size": 999, "width": 1280}], caption="Like this one")
    ib.tg.bot_settings = {"mode": "off"}
    calls = ib.http()
    sources.telegram_webhook(ib.db, ib.tg, update)
    get_file = [c for c in calls if c["url"].endswith("/getFile")]
    assert get_file[0]["params"]["file_id"] == "big"
    [conv] = ib.convs(ib.tg)
    [message] = ib.messages(conv)
    assert message.body == "Like this one"
    media = ib.db.get(Media, message.media_ids[0])
    assert media.mimetype == "image/jpeg" and media.source == "inbox" and media.workspace_id == ib.ws


def test_telegram_photo_with_template_hook(ib, monkeypatch):
    seen = []

    def handle_command(db, account, message, media_ids):
        seen.append((account.id, message.get("caption"), media_ids))
        return "Your design is ready ✅"

    module = types.ModuleType("app.modules.templates.telegram")
    module.handle_command = handle_command
    monkeypatch.setitem(sys.modules, "app.modules.templates.telegram", module)
    update = ib.tg_update(None, photo=[{"file_id": "big", "file_size": 999}], caption="/post Summer sale")
    calls = ib.http()
    sources.telegram_webhook(ib.db, ib.tg, update)
    assert len(seen) == 1
    assert seen[0][0] == ib.tg.id and seen[0][1] == "/post Summer sale"
    assert ib.db.get(Media, seen[0][2][0]).mimetype == "image/jpeg"
    send = [c for c in calls if c["url"].endswith("/sendMessage")]
    assert send[0]["data"]["text"] == "Your design is ready ✅"
    assert not ib.convs(ib.tg)


def test_telegram_polling_when_no_webhook(ib):
    state = account_state(ib.db, ib.tg)

    def handler(method, url, kw):
        if url.endswith("/getUpdates"):
            assert kw["params"]["offset"] == state.telegram_offset
            return ib._mock_http.response(body={"ok": True, "result": [ib.tg_update("hello", update_id=41)]})
        return ib.handler(method, url, kw)

    ib.tg.bot_settings = {"mode": "off"}
    ib.http(handler)
    assert sources.poll_accounts(ib.db, [ib.tg])["new"] == 1
    assert state.telegram_offset == 42


def test_whatsapp_cloud_inbound_and_reply(ib):
    payload = {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": [{
        "field": "messages", "value": {
            "messaging_product": "whatsapp", "metadata": {"phone_number_id": "PNID"},
            "contacts": [{"profile": {"name": "Yusuf"}, "wa_id": "31612345678"}],
            "messages": [{"from": "31612345678", "id": "wamid.IN1", "timestamp": str(int(time.time())),
                          "type": "text", "text": {"body": "Is the shop open on Sunday?"}}]}}]}]}
    calls = ib.deliver(payload)
    [conv] = ib.convs(ib.wa)
    assert conv.customer_name == "Yusuf"
    assert conv.contact.phone == "+31612345678"
    send = [c for c in calls if c["url"].endswith("/PNID/messages")]
    assert send[0]["json"]["to"] == "31612345678"
    assert send[0]["json"]["text"]["body"] == "Hello! We are open 9-17."
    assert send[0]["headers"]["Authorization"] == "Bearer watok"
    [out] = ib.messages(conv, direction="out")
    # a failed delivery status marks the message
    status = {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": [{
        "field": "messages", "value": {"metadata": {"phone_number_id": "PNID"}, "statuses": [
            {"id": out.external_id, "status": "failed", "errors": [{"title": "Re-engagement message"}]}]}}]}]}
    ib.deliver(status)
    assert out.state == "failed"
    assert out.error == "Re-engagement message"


def test_twilio_inbound_and_outbound(ib, client):
    params = {"MessageSid": "SM1", "From": "whatsapp:+31687654321", "To": "whatsapp:+14155238886",
              "Body": "Hoi, prijs?", "ProfileName": "Noor", "WaId": "31687654321", "NumMedia": "0"}
    calls = ib.http()
    sources.twilio_inbound(ib.db, ib.twilio, params)
    sources.twilio_inbound(ib.db, ib.twilio, params)  # retried by Twilio
    ib.run_bot()
    [conv] = ib.convs(ib.twilio)
    assert len(ib.messages(conv, direction="in")) == 1
    assert ib.messages(conv, state="suggested")  # suggest mode
    assert not [c for c in calls if "api.twilio.com" in c["url"]]
    calls = ib.http()
    r = client.post(f"/api/inbox/conversations/{conv.id}/messages",
                    json={"body": "Hoi Noor! Onze prijzen staan op de site."}, headers=ib.auth.headers)
    assert r.status_code == 201, r.text
    assert calls[0]["url"].endswith("/Accounts/AC123/Messages.json")
    assert calls[0]["data"]["From"] == "whatsapp:+14155238886"
    assert calls[0]["data"]["To"] == "whatsapp:+31687654321"
    assert calls[0]["headers"]["Authorization"].startswith("Basic ")
    assert ib.messages(conv, state="sent")[0].external_id.startswith("SMout")


def test_signatures():
    body = b'{"object": "page"}'
    good = webhook_auth.meta_signature("app-secret", body)
    assert webhook_auth.meta_signature_ok("app-secret", body, good)
    assert not webhook_auth.meta_signature_ok("app-secret", body + b" ", good)
    assert not webhook_auth.meta_signature_ok("", body, good)
    params = {"Body": "Hi", "From": "whatsapp:+31600000000"}
    url = "https://api.example.com/webhooks/twilio/1"
    signature = webhook_auth.twilio_signature("token", url, params)
    assert webhook_auth.twilio_signature_ok("token", {"http://wrong", url}, params, signature)
    assert not webhook_auth.twilio_signature_ok("token", {url}, dict(params, Body="Ho"), signature)
    assert not webhook_auth.twilio_signature_ok("other", {url}, params, signature)
    assert not webhook_auth.secret_ok("", "")
    assert webhook_auth.secret_ok("a", "a") and not webhook_auth.secret_ok("a", "b")


# ====================================================================== real HTTP webhooks
@pytest.fixture()
def webhooks(ib, monkeypatch):
    """Webhook endpoints with the assistant off: no outgoing call may happen except the profile lookup."""
    from app.modules.inbox import config
    from app.modules.inbox.messaging import MetaMessenger
    monkeypatch.setattr(config.inbox_settings(), "meta_app_secret", "app-secret")
    monkeypatch.setattr(config.inbox_settings(), "meta_verify_token", "verify-me")
    monkeypatch.setattr(MetaMessenger, "user_profile", lambda self, user_id: {"name": "Webhook User"})
    for account in (ib.fb, ib.tg, ib.twilio):
        account.bot_settings = {"mode": "off"}

    def no_network(method, url, kw):
        raise AssertionError("no outgoing call expected: %s %s" % (method, url))

    ib.http(no_network)
    return ib


def test_meta_verification(webhooks, client):
    ok = client.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                              "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    bad = client.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "wrong",
                                               "hub.challenge": "12345"})
    assert bad.status_code == 403


def test_meta_signature(webhooks, client):
    ib = webhooks
    payload = json.dumps({"object": "page", "entry": [{"id": "PAGE1", "time": 1, "messaging": [{
        "sender": {"id": "U1"}, "recipient": {"id": "PAGE1"}, "timestamp": int(time.time() * 1000),
        "message": {"mid": "m_web_1", "text": "Hello from Messenger"}}]}]}).encode()
    bad = client.post("/webhooks/meta", content=payload, headers={"Content-Type": "application/json",
                                                                  "X-Hub-Signature-256": "sha256=deadbeef"})
    assert bad.status_code == 401
    assert not ib.convs(ib.fb)
    good = client.post("/webhooks/meta", content=payload, headers={
        "Content-Type": "application/json", "X-Hub-Signature-256": webhook_auth.meta_signature("app-secret", payload)})
    assert good.status_code == 200
    [conv] = ib.convs(ib.fb)
    assert ib.messages(conv)[0].body == "Hello from Messenger"
    assert conv.customer_name == "Webhook User"
    # broken payload: still 200 for Meta, nothing stored
    broken = b'{"object": "page", "entry": [{"id": "PAGE1", "messaging": [{"message": 5}]}]}'
    response = client.post("/webhooks/meta", content=broken, headers={
        "Content-Type": "application/json", "X-Hub-Signature-256": webhook_auth.meta_signature("app-secret", broken)})
    assert response.status_code == 200
    assert len(ib.messages(conv)) == 1


def test_telegram_secret(webhooks, client):
    ib = webhooks
    token = account_state(ib.db, ib.tg).webhook_secret
    update = {"update_id": 5, "message": {"message_id": 3, "date": int(time.time()), "text": "hi bot",
                                           "chat": {"id": 55, "type": "private"},
                                           "from": {"id": 55, "first_name": "Rami"}}}
    url = f"/webhooks/telegram/{ib.tg.id}/{token}"
    wrong = client.post(f"/webhooks/telegram/{ib.tg.id}/nope", json=update,
                        headers={"X-Telegram-Bot-Api-Secret-Token": token})
    assert wrong.status_code == 403
    assert client.post(url, json=update).status_code == 403  # no header
    ok = client.post(url, json=update, headers={"X-Telegram-Bot-Api-Secret-Token": token})
    assert ok.status_code == 200
    [conv] = ib.convs(ib.tg)
    assert conv.customer_name == "Rami"


def test_twilio_signature(webhooks, client):
    from app.core.config import settings
    ib = webhooks
    path = f"/webhooks/twilio/{ib.twilio.id}"
    params = {"MessageSid": "SMx1", "From": "whatsapp:+31611111111", "To": "whatsapp:+14155238886",
              "Body": "Hallo", "ProfileName": "Eva", "WaId": "31611111111", "NumMedia": "0"}
    bad = client.post(path, data=params, headers={"X-Twilio-Signature": "nope"})
    assert bad.status_code == 403
    signature = webhook_auth.twilio_signature("tw-secret", settings.public_api_url.rstrip("/") + path, params)
    ok = client.post(path, data=params, headers={"X-Twilio-Signature": signature})
    assert ok.status_code == 200
    assert "<Response>" in ok.text
    [conv] = ib.convs(ib.twilio)
    assert conv.customer_name == "Eva"
    assert ib.messages(conv)[0].body == "Hallo"
