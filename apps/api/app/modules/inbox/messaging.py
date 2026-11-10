"""Customer messaging per network: send direct messages and comment replies, moderate comments and read new
messages (polling fallback). Every request goes through :func:`app.core.http.call` (logged, secrets redacted).
"""
import base64
import json

from app.core.http import ApiError, call
from app.modules.social.models import SocialAccount

from .bot_config import account_secrets, whatsapp_provider
from .config import inbox_settings

GRAPH = "https://graph.facebook.com"
TELEGRAM = "https://api.telegram.org"
TWILIO = "https://api.twilio.com/2010-04-01"

# Text limits per network (longer replies are cut, never rejected).
MAX_TEXT = {"facebook": 2000, "instagram": 1000, "telegram": 4096, "whatsapp": 4096}
LABELS = {"facebook": "Facebook", "instagram": "Instagram", "telegram": "Telegram", "whatsapp": "WhatsApp"}


class BaseMessenger:
    platform = ""

    def __init__(self, account: SocialAccount):
        self.account = account

    @property
    def label(self) -> str:
        return LABELS.get(self.account.platform, self.account.platform)

    def _call(self, method, url, operation, **kwargs):
        return call(method, url, service="social", operation=f"Inbox · {operation}",
                    workspace_id=self.account.workspace_id, ref=("social_account", self.account.id), **kwargs)

    @property
    def token(self) -> str:
        if not self.account.access_token:
            raise ApiError("The account %s has no access token: reconnect it." % self.account.name, 401)
        return self.account.access_token

    def clip(self, text: str) -> str:
        limit = MAX_TEXT.get(self.account.platform, 2000)
        text = (text or "").strip()
        return text if len(text) <= limit else text[:limit - 1] + "…"

    # -- to implement -------------------------------------------------------
    def send_dm(self, recipient, text, *, reply_to=None, tag=None) -> dict:
        """Send a direct message. Returns ``{"external_id": str}``."""
        raise ApiError("%s cannot send direct messages from here." % self.label)

    def reply_comment(self, comment_id, text) -> dict:
        raise ApiError("%s comments cannot be answered from here." % self.label)

    def private_reply(self, comment_id, text) -> dict:
        raise ApiError("%s does not support private replies to comments." % self.label)

    def hide_comment(self, comment_id, hide=True) -> bool:
        raise ApiError("%s comments cannot be hidden from here." % self.label)

    def like_comment(self, comment_id) -> bool:
        raise ApiError("%s comments cannot be liked from here." % self.label)

    def download(self, url) -> tuple[bytes, str]:
        """``(bytes, mimetype)`` of a media URL sent by the customer."""
        response = self._call("GET", url, "Download media", expect_json=False, binary=True, timeout=60)
        return response.content, (response.headers.get("Content-Type") or "").split(";")[0]

    def check(self) -> dict:
        """Profile values ``{"name", "username"}``."""
        return {}


# ---------------------------------------------------------------------------
# Facebook Pages + Instagram (Messenger Platform, page access token)
# ---------------------------------------------------------------------------
class MetaMessenger(BaseMessenger):
    def _graph(self):
        return "%s/%s" % (GRAPH, inbox_settings().meta_graph_version)

    def _sender_node(self):
        # Facebook: the page itself. Instagram (Facebook login): "me" = the page linked to the account.
        return self.account.external_id if self.account.platform == "facebook" else "me"

    def _messages(self, recipient, message, operation, tag=None):
        body = {"recipient": recipient, "message": message,
                "messaging_type": "MESSAGE_TAG" if tag else "RESPONSE"}
        if tag:
            body["tag"] = tag
        data = self._call("POST", "%s/%s/messages" % (self._graph(), self._sender_node()), operation,
                          params={"access_token": self.token}, json_body=body)
        return {"external_id": data.get("message_id") or data.get("id") or ""}

    def send_dm(self, recipient, text, *, reply_to=None, tag=None):
        return self._messages({"id": recipient}, {"text": self.clip(text)}, "Send message", tag=tag)

    def private_reply(self, comment_id, text):
        return self._messages({"comment_id": comment_id}, {"text": self.clip(text)}, "Private reply")

    def reply_comment(self, comment_id, text):
        edge = "comments" if self.account.platform == "facebook" else "replies"
        data = self._call("POST", "%s/%s/%s" % (self._graph(), comment_id, edge), "Reply to comment",
                          data={"message": self.clip(text), "access_token": self.token})
        return {"external_id": data.get("id") or ""}

    def hide_comment(self, comment_id, hide=True):
        key = "is_hidden" if self.account.platform == "facebook" else "hide"
        self._call("POST", "%s/%s" % (self._graph(), comment_id), "Hide comment" if hide else "Unhide comment",
                   data={key: "true" if hide else "false", "access_token": self.token})
        return True

    def like_comment(self, comment_id):
        if self.account.platform != "facebook":
            return super().like_comment(comment_id)
        self._call("POST", "%s/%s/likes" % (self._graph(), comment_id), "Like comment",
                   data={"access_token": self.token})
        return True

    def user_profile(self, user_id) -> dict:
        fields = "name,profile_pic" if self.account.platform == "facebook" else "name,username,profile_pic"
        try:
            data = self._call("GET", "%s/%s" % (self._graph(), user_id), "Read customer profile",
                              params={"fields": fields, "access_token": self.token})
        except ApiError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {"name": data.get("name") or data.get("username") or "", "username": data.get("username") or "",
                "avatar_url": data.get("profile_pic") or ""}

    # -- polling --------------------------------------------------------------
    def fetch_conversations(self, limit=20) -> list:
        data = self._call("GET", "%s/me/conversations" % self._graph(), "Read conversations", params={
            "platform": "messenger" if self.account.platform == "facebook" else "instagram",
            "fields": "id,updated_time,participants,messages.limit(10){id,message,from,to,created_time}",
            "limit": limit, "access_token": self.token})
        return data.get("data") or []

    def fetch_comments(self, object_id, limit=50) -> list:
        """Comments (and replies) on one post / media, newest first."""
        if self.account.platform == "facebook":
            params = {"fields": "id,message,from,created_time,parent{id}", "filter": "stream",
                      "order": "reverse_chronological", "limit": limit}
        else:
            params = {"fields": "id,text,username,from{id,username},timestamp,"
                                "replies{id,text,username,from{id,username},timestamp}", "limit": limit}
        params["access_token"] = self.token
        data = self._call("GET", "%s/%s/comments" % (self._graph(), object_id), "Read comments", params=params)
        return data.get("data") or []

    def fetch_recent_media(self, limit=10) -> list:
        data = self._call("GET", "%s/%s/media" % (self._graph(), self.account.external_id), "Read recent media",
                          params={"fields": "id,caption,permalink,timestamp", "limit": limit,
                                  "access_token": self.token})
        return data.get("data") or []


# ---------------------------------------------------------------------------
# Telegram Bot API (private chats with the bot) — the bot token is the account's access token
# ---------------------------------------------------------------------------
class TelegramMessenger(BaseMessenger):
    def _url(self, method):
        return "%s/bot%s/%s" % (TELEGRAM, self.token, method)

    def _result(self, data):
        if not isinstance(data, dict) or not data.get("ok"):
            raise ApiError("Telegram: %s" % (data.get("description") if isinstance(data, dict) else data))
        return data["result"]

    def send_dm(self, recipient, text, *, reply_to=None, tag=None):
        payload = {"chat_id": str(recipient), "text": self.clip(text)}
        if reply_to:
            payload["reply_parameters"] = json.dumps({"message_id": int(reply_to),
                                                      "allow_sending_without_reply": True})
        message = self._result(self._call("POST", self._url("sendMessage"), "Send message", data=payload))
        # message ids are only unique per chat: store "chat:message"
        mid = message.get("message_id") if isinstance(message, dict) else None
        return {"external_id": "%s:%s" % (recipient, mid) if mid else ""}

    def set_webhook(self, url, secret):
        return self._result(self._call("POST", self._url("setWebhook"), "Set webhook", data={
            "url": url, "secret_token": secret, "allowed_updates": json.dumps(["message"]),
            "max_connections": 20}))

    def delete_webhook(self):
        return self._result(self._call("POST", self._url("deleteWebhook"), "Delete webhook", data={}))

    def get_updates(self, offset=0):
        return self._result(self._call("GET", self._url("getUpdates"), "Read updates", params={
            "offset": offset or 0, "timeout": 0, "limit": 100, "allowed_updates": json.dumps(["message"])}))

    def file_content(self, file_id):
        info = self._result(self._call("GET", self._url("getFile"), "Read file", params={"file_id": file_id}))
        url = "%s/file/bot%s/%s" % (TELEGRAM, self.token, info.get("file_path") or "")
        return self.download(url)

    def check(self):
        bot = self._result(self._call("GET", self._url("getMe"), "Check bot"))
        return {"username": bot.get("username") or "", "name": bot.get("first_name") or ""}


# ---------------------------------------------------------------------------
# WhatsApp Cloud API (Meta) — external_id = phone_number_id, access_token = permanent token
# ---------------------------------------------------------------------------
class WhatsAppCloudMessenger(BaseMessenger):
    def _graph(self):
        return "%s/%s" % (GRAPH, inbox_settings().meta_graph_version)

    def _headers(self):
        return {"Authorization": "Bearer %s" % self.token}

    def send_dm(self, recipient, text, *, reply_to=None, tag=None):
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": recipient,
                "type": "text", "text": {"body": self.clip(text), "preview_url": False}}
        if reply_to:
            body["context"] = {"message_id": reply_to}
        data = self._call("POST", "%s/%s/messages" % (self._graph(), self.account.external_id), "Send message",
                          headers=self._headers(), json_body=body)
        return {"external_id": ((data.get("messages") or [{}])[0]).get("id") or ""}

    def media_content(self, media_id):
        info = self._call("GET", "%s/%s" % (self._graph(), media_id), "Read media", headers=self._headers())
        response = self._call("GET", info.get("url") or "", "Download media", headers=self._headers(),
                              expect_json=False, binary=True)
        return response.content, info.get("mime_type") or (response.headers.get("Content-Type") or "").split(";")[0]

    def check(self):
        data = self._call("GET", "%s/%s" % (self._graph(), self.account.external_id), "Read phone number",
                          headers=self._headers(), params={"fields": "display_phone_number,verified_name"})
        return {"name": data.get("verified_name") or "", "username": data.get("display_phone_number") or ""}


# ---------------------------------------------------------------------------
# WhatsApp through Twilio
# ---------------------------------------------------------------------------
def wa_address(number: str) -> str:
    number = (number or "").strip()
    if number.startswith("whatsapp:"):
        return number
    return "whatsapp:%s" % (number if number.startswith("+") else "+" + number.lstrip("0"))


class TwilioMessenger(BaseMessenger):
    @property
    def sid(self):
        return (self.account.extra or {}).get("twilio_account_sid") or ""

    @property
    def number(self):
        return (self.account.extra or {}).get("whatsapp_number") or ""

    def _auth(self):
        token = account_secrets(self.account).get("twilio_auth_token")
        if not self.sid or not token:
            raise ApiError("Add the Twilio Account SID and Auth token on the WhatsApp account first.", 401)
        raw = "%s:%s" % (self.sid, token)
        return {"Authorization": "Basic %s" % base64.b64encode(raw.encode()).decode()}

    def send_dm(self, recipient, text, *, reply_to=None, tag=None):
        headers = self._auth()
        data = self._call("POST", "%s/Accounts/%s/Messages.json" % (TWILIO, self.sid), "Send message",
                          headers=headers, data={"From": wa_address(self.number), "To": wa_address(recipient),
                                                 "Body": self.clip(text)})
        return {"external_id": data.get("sid") or ""}

    def download(self, url):
        response = self._call("GET", url, "Download media", headers=self._auth(), expect_json=False, binary=True)
        return response.content, (response.headers.get("Content-Type") or "").split(";")[0]

    def check(self):
        data = self._call("GET", "%s/Accounts/%s.json" % (TWILIO, self.sid), "Check account", headers=self._auth())
        return {"name": data.get("friendly_name") or "", "username": self.number}


def get_messenger(account: SocialAccount) -> BaseMessenger:
    platform = account.platform
    if platform in ("facebook", "instagram"):
        return MetaMessenger(account)
    if platform == "telegram":
        return TelegramMessenger(account)
    if platform == "whatsapp":
        return TwilioMessenger(account) if whatsapp_provider(account) == "twilio" else WhatsAppCloudMessenger(account)
    raise ApiError("The inbox does not support %s yet." % LABELS.get(platform, platform))
