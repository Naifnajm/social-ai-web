"""Shared fixtures of the inbox tests: fake networks, fake AI and helpers to deliver webhooks."""
import json
import time

from sqlalchemy import select

from app.core.errors import AppError
from app.modules.ai import service as ai_service
from app.modules.inbox import service, sources
from app.modules.inbox.models import Conversation, Message
from app.modules.social.models import SocialAccount
from app.modules.workspaces.settings import set_setting


def answer(reply="Hello! We are open 9-17.", confidence=92, **extra):
    data = {"intent": "question", "sentiment": "neutral", "reply": reply, "confidence": confidence,
            "handover": False, "handover_reason": "", "hide": False, "private_reply": False, "lead": False}
    data.update(extra)
    return data


def make_account(db, workspace_id, platform, external_id, name=None, **extra):
    account = SocialAccount(workspace_id=workspace_id, name=name or f"{platform} account", platform=platform,
                            external_id=external_id, state="connected", inbox_enabled=True, active=True, **extra)
    db.add(account)
    db.flush()
    return account


class InboxEnv:
    def __init__(self, db, auth, mock_http, monkeypatch):
        self.db = db
        self.auth = auth
        self.ws = auth.workspace_id
        self._mock_http = mock_http
        self.ai = answer()
        self.ai_prompts = []
        self.comments = {}
        self.threads = []
        self.out_counter = 0
        set_setting(db, self.ws, "inbox.handover_message", "")
        self.fb = make_account(db, self.ws, "facebook", "PAGE1", "Brand Page", access_token="fbtok",
                               bot_settings={"mode": "auto", "comment_mode": "auto"})
        self.ig = make_account(db, self.ws, "instagram", "IG1", "Brand IG", username="brand", access_token="igtok",
                               bot_settings={"mode": "auto", "comment_mode": "suggest"})
        self.tg = make_account(db, self.ws, "telegram", "@brand", "Brand bot", access_token="123:ABC",
                               bot_settings={"mode": "auto"})
        self.wa = make_account(db, self.ws, "whatsapp", "PNID", "WhatsApp", access_token="watok",
                               extra={"whatsapp_provider": "cloud"}, bot_settings={"mode": "auto"})
        self.twilio = make_account(db, self.ws, "whatsapp", "14155238886", "WhatsApp Twilio",
                                   extra={"whatsapp_provider": "twilio", "twilio_account_sid": "AC123",
                                          "whatsapp_number": "+14155238886"},
                                   secrets=json.dumps({"twilio_auth_token": "tw-secret"}),
                                   bot_settings={"mode": "suggest"})

        def fake_generate_json(db, workspace_id, system, user, **kwargs):
            self.ai_prompts.append({"system": system, "user": user, "workspace_id": workspace_id})
            if isinstance(self.ai, Exception):
                raise self.ai
            if isinstance(self.ai, str):
                raise AppError("The AI answer could not be read as JSON.", code="ai_bad_json")
            return dict(self.ai)

        monkeypatch.setattr(ai_service, "generate_json", fake_generate_json)
        monkeypatch.setattr(ai_service, "has_provider", lambda db, ws, capability="text": True)

    # -------------------------------------------------------------- fake networks
    def handler(self, method, url, kw):
        response = self._mock_http.response
        self.out_counter += 1
        n = self.out_counter
        if "api.telegram.org" in url:
            if url.endswith("/sendMessage"):
                return response(body={"ok": True, "result": {"message_id": 500 + n}})
            if url.endswith("/getFile"):
                return response(body={"ok": True, "result": {"file_path": "photos/file_1.jpg"}})
            if "/file/bot" in url:
                return response(200, b"\xff\xd8jpegdata", {"Content-Type": "image/jpeg"})
            return response(body={"ok": True, "result": True})
        if "api.twilio.com" in url:
            return response(201, {"sid": "SMout%s" % n})
        if "graph.facebook.com" in url:
            if url.endswith("/PNID/messages"):
                return response(body={"messages": [{"id": "wamid.out%s" % n}]})
            if url.endswith("/messages"):
                return response(body={"recipient_id": "x", "message_id": "m_out_%s" % n})
            if method == "POST" and (url.endswith("/comments") or url.endswith("/replies")):
                return response(body={"id": "reply_%s" % n})
            if method == "GET" and url.endswith("/comments"):
                key = url.rsplit("/", 2)[-2]
                return response(body={"data": self.comments.get(key, [])})
            if method == "GET" and url.endswith("/conversations"):
                return response(body={"data": self.threads})
            if method == "GET" and url.endswith("/media"):
                return response(body={"data": []})
            if method == "POST":
                return response(body={"success": True})
            return response(body={"name": "Sara Ali", "profile_pic": "https://cdn.example.com/sara.jpg"})
        raise AssertionError("Unexpected call %s %s" % (method, url))

    def http(self, handler=None):
        """Install a fake network; returns the list of calls made from now on."""
        calls = []
        handler = handler or self.handler

        def record(method, url, kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            return handler(method, url, kwargs)

        self._mock_http(record)
        return calls

    @staticmethod
    def sends(calls):
        return [c for c in calls if c["method"] == "POST"]

    def run_bot(self):
        self.db.flush()
        service.run_scheduled(self.db)
        self.db.flush()

    def deliver(self, payload):
        calls = self.http()
        sources.meta_webhook(self.db, payload)
        self.run_bot()
        return calls

    def convs(self, account, **where):
        query = select(Conversation).where(Conversation.account_id == account.id)
        for key, value in where.items():
            query = query.where(getattr(Conversation, key) == value)
        return list(self.db.scalars(query.order_by(Conversation.id)))

    def messages(self, conv, **where):
        query = select(Message).where(Message.conversation_id == conv.id)
        for key, value in where.items():
            query = query.where(getattr(Message, key) == value)
        return list(self.db.scalars(query.order_by(Message.sent_at, Message.id)))

    # -------------------------------------------------------------- payloads
    @staticmethod
    def fb_message(text, mid, sender="PSID1", page="PAGE1", **message):
        return {"object": "page", "entry": [{"id": page, "time": int(time.time() * 1000), "messaging": [{
            "sender": {"id": sender}, "recipient": {"id": page}, "timestamp": int(time.time() * 1000),
            "message": dict({"mid": mid, "text": text}, **message)}]}]}

    @staticmethod
    def ig_comment(text, comment_id, user="IGU1", username="sara"):
        return {"object": "instagram", "entry": [{"id": "IG1", "time": int(time.time()), "changes": [{
            "field": "comments", "value": {"id": comment_id, "text": text, "from": {"id": user, "username": username},
                                           "media": {"id": "MEDIA1", "media_product_type": "FEED"}}}]}]}

    @staticmethod
    def tg_update(text=None, update_id=1, message_id=10, **extra):
        message = dict({"message_id": message_id, "date": int(time.time()),
                        "chat": {"id": 7001, "type": "private"},
                        "from": {"id": 7001, "is_bot": False, "first_name": "Lina", "username": "lina"}}, **extra)
        if text is not None:
            message["text"] = text
        return {"update_id": update_id, "message": message}
