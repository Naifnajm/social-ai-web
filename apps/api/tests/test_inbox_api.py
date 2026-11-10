"""Inbox API, settings and multi-tenant isolation (workspaces never see each other's conversations)."""
import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.modules.brand.models import BrandKit
from app.modules.inbox import bot_config, sources, webhook_auth
from app.modules.inbox.models import CannedReply, Conversation, KnowledgeEntry, MetaApp
from app.modules.social.models import SocialAccount
from app.modules.workspaces.models import Membership, Role
from tests.conftest import signup
from tests.inbox_helpers import answer, ib, make_account  # noqa: F401  (fixture)


def _other_workspace(client, ib):
    """A second company that connected the same Facebook page (PAGE1)."""
    other = signup(client, email="other@example.com", name="Other", workspace="Other Co")
    page = make_account(ib.db, other.workspace_id, "facebook", "PAGE1", "Same page elsewhere", access_token="tok2",
                        bot_settings={"mode": "off"})
    return other, page


def test_same_page_in_two_workspaces_is_delivered_to_each_and_isolated(ib, client):
    other, page_b = _other_workspace(client, ib)
    ib.fb.bot_settings = {"mode": "suggest"}
    ib.deliver(ib.fb_message("Hello both", "m_mt_1"))
    [conv_a] = ib.convs(ib.fb)
    [conv_b] = ib.convs(page_b)
    assert conv_a.workspace_id == ib.ws and conv_b.workspace_id == other.workspace_id
    assert ib.messages(conv_a)[0].body == ib.messages(conv_b)[0].body == "Hello both"
    assert conv_a.contact_id != conv_b.contact_id
    # the AI of workspace A only (B's assistant is off)
    assert [p["workspace_id"] for p in ib.ai_prompts] == [ib.ws]
    # each workspace lists only its own conversations
    ids_a = [c["id"] for c in client.get("/api/inbox/conversations", headers=ib.auth.headers).json()["items"]]
    ids_b = [c["id"] for c in client.get("/api/inbox/conversations", headers=other.headers).json()["items"]]
    assert ids_a == [conv_a.id] and ids_b == [conv_b.id]
    # B cannot read or change A's data, even with A's ids
    suggestion_a = ib.messages(conv_a, state="suggested")[0]
    h = other.headers
    assert client.get(f"/api/inbox/conversations/{conv_a.id}", headers=h).status_code == 404
    assert client.patch(f"/api/inbox/conversations/{conv_a.id}", json={"state": "done"}, headers=h).status_code == 404
    assert client.post(f"/api/inbox/conversations/{conv_a.id}/messages", json={"body": "x"},
                       headers=h).status_code == 404
    assert client.post(f"/api/inbox/suggestions/{suggestion_a.id}/send", json={}, headers=h).status_code == 404
    assert client.delete(f"/api/inbox/suggestions/{suggestion_a.id}", headers=h).status_code == 404
    assert client.get(f"/api/inbox/contacts/{conv_a.contact_id}", headers=h).status_code == 404
    assert client.patch(f"/api/inbox/accounts/{ib.fb.id}", json={"inbox_enabled": False},
                        headers=h).status_code == 404
    # nor assign A's conversation-like rows to its own members / tags
    tag_a = client.post("/api/inbox/tags", json={"name": "VIP"}, headers=ib.auth.headers).json()
    assert client.patch(f"/api/inbox/conversations/{conv_b.id}", json={"tag_ids": [tag_a["id"]]},
                        headers=h).status_code == 404
    assert client.patch(f"/api/inbox/conversations/{conv_b.id}", json={"assignee_id": ib.auth.user_id},
                        headers=h).status_code == 404
    # forging the workspace header does not help
    forged = {**h, "X-Workspace": str(ib.ws)}
    assert client.get(f"/api/inbox/conversations/{conv_a.id}", headers=forged).status_code == 404
    assert client.get("/api/inbox/unread", headers=h).json()["unread"] == 1
    assert conv_a.state == "open"


def test_workspace_meta_app_secret_only_reaches_that_workspace(ib, client, monkeypatch):
    from app.modules.inbox import config
    from app.modules.inbox.messaging import MetaMessenger
    monkeypatch.setattr(config.inbox_settings(), "meta_app_secret", "")
    monkeypatch.setattr(MetaMessenger, "user_profile", lambda self, user_id: {"name": "Webhook User"})
    other, page_b = _other_workspace(client, ib)
    ib.fb.bot_settings = {"mode": "off"}
    r = client.put("/api/inbox/settings", json={"meta_app_id": "777", "meta_app_secret": "b-secret"},
                   headers=other.headers)
    assert r.status_code == 200
    out = r.json()
    assert out["has_meta_app_secret"] and out["meta_app_id"] == "777" and "b-secret" not in r.text
    verify_token = out["meta_verify_token"]
    ok = client.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": verify_token,
                                              "hub.challenge": "c1"})
    assert ok.status_code == 200 and ok.text == "c1"
    ib.http(lambda m, u, k: (_ for _ in ()).throw(AssertionError("no network")))
    payload = json.dumps(ib.fb_message("Only for B", "m_app_b")).encode()
    bad = client.post("/webhooks/meta", content=payload,
                      headers={"X-Hub-Signature-256": webhook_auth.meta_signature("wrong", payload)})
    assert bad.status_code == 401
    good = client.post("/webhooks/meta", content=payload,
                       headers={"X-Hub-Signature-256": webhook_auth.meta_signature("b-secret", payload)})
    assert good.status_code == 200
    assert len(ib.convs(page_b)) == 1
    assert not ib.convs(ib.fb)  # A did not sign it with its app: nothing delivered to A
    assert ib.db.scalar(select(MetaApp).where(MetaApp.workspace_id == other.workspace_id)).app_secret == "b-secret"


def test_unknown_account_webhook_is_ignored(ib):
    ib.deliver(ib.fb_message("Who am I?", "m_unknown", page="NOPE"))
    assert not ib.db.scalars(select(Conversation)).all()


def test_roles_viewer_reads_only(ib, client):
    ib.fb.bot_settings = {"mode": "off"}
    ib.deliver(ib.fb_message("Hi", "m_role"))
    [conv] = ib.convs(ib.fb)
    viewer = signup(client, email="viewer@example.com", name="Vera", workspace="Vera Co")
    ib.db.add(Membership(user_id=viewer.user_id, workspace_id=ib.ws, role=Role.viewer))
    ib.db.flush()
    h = {**viewer.headers, "X-Workspace": str(ib.ws)}
    assert client.get(f"/api/inbox/conversations/{conv.id}", headers=h).status_code == 200
    assert conv.unread  # a viewer does not mark as read
    assert client.post(f"/api/inbox/conversations/{conv.id}/messages", json={"body": "x"},
                       headers=h).status_code == 403
    assert client.post("/api/inbox/canned-replies", json={"name": "a", "body": "b"}, headers=h).status_code == 403
    assert client.get("/api/inbox/settings", headers=h).status_code == 403
    accounts = client.get("/api/inbox/accounts", headers=h).json()
    assert all(a["webhook_url"] is None for a in accounts)


def test_canned_knowledge_triggers_crud_and_prompt(ib, client):
    h = ib.auth.headers
    canned = client.post("/api/inbox/canned-replies", headers=h, json={
        "name": "Hours", "body": "Hi {name}, we are open 9-17.", "shortcut": "/hours"}).json()
    assert canned["shortcut"] == "hours"
    assert client.put(f"/api/inbox/canned-replies/{canned['id']}", headers=h, json={
        "name": "Opening hours", "body": "Hi {name}, we are open 9-17.", "shortcut": "hours"}).status_code == 200
    knowledge = client.post("/api/inbox/knowledge", headers=h, json={
        "title": "Delivery", "content": "We deliver in Riyadh within 2 days."}).json()
    assert client.get("/api/inbox/knowledge", headers=h).json()[0]["id"] == knowledge["id"]
    assert client.post("/api/inbox/triggers", headers=h, json={"name": "x", "keywords": "price"}).status_code == 400
    other = signup(client, email="z@example.com", workspace="Z")
    foreign = make_account(ib.db, other.workspace_id, "instagram", "IGX")
    assert client.post("/api/inbox/triggers", headers=h, json={
        "name": "x", "keywords": "price", "dm_text": "Hi", "account_ids": [foreign.id]}).status_code == 404
    trigger = client.post("/api/inbox/triggers", headers=h, json={
        "name": "Prices", "keywords": "price, سعر", "dm_text": "Hi {name}", "account_ids": [ib.ig.id]})
    assert trigger.status_code == 201 and trigger.json()["hit_count"] == 0
    # other workspace cannot touch them
    assert client.put(f"/api/inbox/canned-replies/{canned['id']}", headers=other.headers, json={
        "name": "x", "body": "y"}).status_code == 404
    assert client.delete(f"/api/inbox/knowledge/{knowledge['id']}", headers=other.headers).status_code == 404
    assert client.delete(f"/api/inbox/triggers/{trigger.json()['id']}", headers=other.headers).status_code == 404
    # the assistant uses the knowledge, approved answers, brand kit and company info
    ib.db.add(BrandKit(workspace_id=ib.ws, name="Acme Coffee", tone="Warm and short", is_default=True))
    client.put("/api/inbox/settings", headers=h, json={"company_info": "Phone: +966 11 000 0000",
                                                     "handover_message": "A colleague will answer."})
    ib.deliver(ib.fb_message("Do you deliver?", "m_prompt"))
    prompt = ib.ai_prompts[-1]
    assert "We deliver in Riyadh within 2 days." in prompt["user"]
    assert "Opening hours: Hi Sara, we are open 9-17." in prompt["user"]
    assert "Phone: +966 11 000 0000" in prompt["user"]
    assert "HANDOVER MESSAGE" in prompt["user"]
    assert "Brand: Acme Coffee" in prompt["system"] and "Warm and short" in prompt["system"]
    assert client.delete(f"/api/inbox/canned-replies/{canned['id']}", headers=h).status_code == 204
    assert not ib.db.scalars(select(CannedReply)).all()
    assert ib.db.scalars(select(KnowledgeEntry)).all()


def test_account_bot_settings_and_webhook_urls(ib, client):
    h = ib.auth.headers
    accounts = {a["platform"] + a["name"]: a for a in client.get("/api/inbox/accounts", headers=h).json()}
    tg = accounts["telegramBrand bot"]
    assert tg["webhook_kind"] == "telegram" and f"/webhooks/telegram/{ib.tg.id}/" in tg["webhook_url"]
    assert accounts["facebookBrand Page"]["webhook_url"].endswith("/webhooks/meta")
    r = client.patch(f"/api/inbox/accounts/{ib.fb.id}", headers=h, json={
        "bot": {"mode": "auto", "confidence": 90, "when": "office_hours", "instructions": "Only Riyadh."}})
    assert r.status_code == 200, r.text
    bot = r.json()["bot"]
    assert (bot["mode"], bot["confidence"], bot["when"], bot["comment_mode"]) == ("auto", 90, "office_hours", "auto")
    assert ib.fb.bot_settings["instructions"] == "Only Riyadh."
    assert client.patch(f"/api/inbox/accounts/{ib.fb.id}", headers=h, json={"bot": {"confidence": 120}}
                        ).status_code == 422
    assert client.patch(f"/api/inbox/accounts/{ib.fb.id}", headers=h, json={"bot": {"brand_kit_id": 999999}}
                        ).status_code == 404
    # Telegram instant webhook needs a public HTTPS API address
    r = client.post(f"/api/inbox/accounts/{ib.tg.id}/telegram-webhook", headers=h)
    assert r.status_code == 400 and r.json()["code"] == "no_public_url"
    old = tg["webhook_url"]
    rotated = client.post(f"/api/inbox/accounts/{ib.tg.id}/rotate-secret", headers=h).json()
    assert rotated["webhook_url"] != old


def test_office_hours_rule(ib):
    ib.fb.bot_settings = {"when": "office_hours", "hour_from": 9, "hour_to": 17}
    monday_10_riyadh = datetime(2026, 11, 9, 7, 0, tzinfo=timezone.utc)
    monday_20_riyadh = datetime(2026, 11, 9, 17, 0, tzinfo=timezone.utc)
    friday_10_riyadh = datetime(2026, 11, 13, 7, 0, tzinfo=timezone.utc)  # weekend days: Sat/Sun
    assert bot_config.is_active_now(ib.fb, "Asia/Riyadh", monday_10_riyadh)
    assert not bot_config.is_active_now(ib.fb, "Asia/Riyadh", monday_20_riyadh)
    assert bot_config.is_active_now(ib.fb, "Asia/Riyadh", friday_10_riyadh)
    ib.fb.bot_settings = {"when": "outside_hours"}
    assert bot_config.is_active_now(ib.fb, "Asia/Riyadh", monday_20_riyadh)
    assert bot_config.bot_config(SocialAccount(bot_settings={"mode": "weird", "confidence": "x"}))["mode"] == "suggest"


def test_cursor_pagination_and_filters(ib, client):
    for account in (ib.fb, ib.tg):
        account.bot_settings = {"mode": "off"}
    for index in range(5):
        ib.deliver(ib.fb_message(f"Message {index}", f"m_page_{index}", sender=f"P{index}"))
    ib.http()
    sources.telegram_webhook(ib.db, ib.tg, ib.tg_update("Telegram hi"))
    h = ib.auth.headers
    first = client.get("/api/inbox/conversations", params={"limit": 4}, headers=h).json()
    assert len(first["items"]) == 4 and first["next_cursor"]
    second = client.get("/api/inbox/conversations", params={"limit": 4, "cursor": first["next_cursor"]},
                        headers=h).json()
    assert len(second["items"]) == 2 and second["next_cursor"] is None
    ids = [c["id"] for c in first["items"] + second["items"]]
    assert len(set(ids)) == 6
    assert first["counts"]["all"] == 6
    assert len(client.get("/api/inbox/conversations", params={"platform": "telegram"},
                          headers=h).json()["items"]) == 1
    assert client.get("/api/inbox/conversations", params={"kind": "comment"}, headers=h).json()["items"] == []
    assert client.get("/api/inbox/conversations", params={"cursor": "%%%"}, headers=h).status_code == 400
    done = client.patch(f"/api/inbox/conversations/{ids[0]}", json={"state": "done"}, headers=h).json()
    assert done["state"] == "done" and not done["unread"]
    assert client.get("/api/inbox/conversations", params={"folder": "done"}, headers=h).json()["items"][0]["id"] \
        == ids[0]
    assert client.post(f"/api/inbox/conversations/{ids[0]}/unread", headers=h).status_code == 204


def test_comment_thread_send_public_private_hide_like(ib, client):
    ib.fb.bot_settings = {"mode": "off", "comment_mode": "off"}
    payload = {"object": "page", "entry": [{"id": "PAGE1", "changes": [{"field": "feed", "value": {
        "item": "comment", "verb": "add", "comment_id": "PC_1", "post_id": "PAGE1_5", "parent_id": "PAGE1_5",
        "from": {"id": "U9", "name": "Omar Saleh"}, "message": "كم السعر؟"}}]}]}
    ib.deliver(payload)
    [conv] = ib.convs(ib.fb, kind="comment")
    h = ib.auth.headers
    thread = client.get(f"/api/inbox/conversations/{conv.id}", headers=h).json()
    assert thread["can_private"] and thread["can_hide"] and thread["can_like"] and not thread["window"]["limited"]
    calls = ib.http()
    r = client.post(f"/api/inbox/conversations/{conv.id}/messages", json={"body": "أرسلنا لك رسالة", "channel": "private"},
                    headers=h)
    assert r.status_code == 201 and r.json()["message"]["channel"] == "private"
    assert calls[-1]["json"]["recipient"] == {"comment_id": "PC_1"}
    r = client.post(f"/api/inbox/conversations/{conv.id}/messages", json={"body": "شكراً!", "channel": "dm"},
                    headers=h)
    assert r.json()["message"]["channel"] == "public" and calls[-1]["url"].endswith("/PC_1/comments")
    assert client.post(f"/api/inbox/conversations/{conv.id}/hide", json={"hide": True}, headers=h).json()["is_hidden"]
    assert calls[-1]["data"]["is_hidden"] == "true"
    assert client.post(f"/api/inbox/conversations/{conv.id}/like", headers=h).status_code == 204
    assert calls[-1]["url"].endswith("/PC_1/likes")
    # a failed send is stored with its error (no exception for the UI)
    ib.http(lambda m, u, k: ib._mock_http.response(400, {"error": {"message": "(#10) Not allowed"}}))
    r = client.post(f"/api/inbox/conversations/{conv.id}/messages", json={"body": "again", "channel": "public"},
                    headers=h)
    assert r.status_code == 201 and r.json()["message"]["state"] == "failed"
    assert "Not allowed" in r.json()["message"]["error"]


def test_settings_roundtrip(ib, client):
    h = ib.auth.headers
    out = client.get("/api/inbox/settings", headers=h).json()
    assert out["create_contacts"] is True and out["meta_webhook_url"].endswith("/webhooks/meta")
    out = client.put("/api/inbox/settings", headers=h, json={"human_agent_tag": True, "private_ack": "📩",
                                                             "create_contacts": False}).json()
    assert out["human_agent_tag"] and out["private_ack"] == "📩" and not out["create_contacts"]
    ib.fb.bot_settings = {"mode": "off"}
    ib.deliver(ib.fb_message("No contact please", "m_nc"))
    assert ib.convs(ib.fb)[0].contact_id is None
    token = out["meta_verify_token"]
    rotated = client.post("/api/inbox/settings/rotate-verify-token", headers=h).json()["meta_verify_token"]
    assert rotated and rotated != token


def test_auto_reply_answer_variants(ib):
    """Auto mode with a private reply on a comment sends the configured acknowledgement publicly."""
    ib.fb.bot_settings = {"mode": "auto", "comment_mode": "auto", "private_reply": True}
    ib.ai = answer("Your order ships tomorrow.", confidence=95, private_reply=True)
    payload = {"object": "page", "entry": [{"id": "PAGE1", "changes": [{"field": "feed", "value": {
        "item": "comment", "verb": "add", "comment_id": "PC_9", "post_id": "PAGE1_5", "parent_id": "PAGE1_5",
        "from": {"id": "U7", "name": "Lama"}, "message": "Where is my order 123?"}}]}]}
    calls = ib.deliver(payload)
    public = [c for c in calls if c["url"].endswith("/PC_9/comments")]
    assert public and public[0]["data"]["message"] == "We've sent you a private message 📩"
