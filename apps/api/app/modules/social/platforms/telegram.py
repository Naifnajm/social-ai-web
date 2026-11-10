"""Telegram Bot API. Token = bot token, external_id = channel (@name or -100…)."""
import json

from app.core.http import ApiError

from .base import BasePublisher

CAPTION_LIMIT = 1024


class TelegramPublisher(BasePublisher):
    platform = "telegram"
    max_chars = 4096
    supports_audio = True

    def _url(self, method):
        return f"https://api.telegram.org/bot{self.token}/{method}"

    @staticmethod
    def _result(data):
        if not isinstance(data, dict) or not data.get("ok"):
            raise ApiError(f"Telegram: {(data or {}).get('description', 'unknown error')}")
        return data["result"]

    def fetch_profile(self):
        bot = self._result(self._call("GET", self._url("getMe"), "Check bot"))
        chat = self._result(self._call("GET", self._url("getChat"), "Read channel",
                                       params={"chat_id": self.account.external_id}))
        return {"name": chat.get("title") or chat.get("first_name") or bot.get("first_name"),
                "username": chat.get("username") or bot.get("username"), "avatar_url": ""}

    @staticmethod
    def _link(message):
        chat = message.get("chat") or {}
        return f"https://t.me/{chat['username']}/{message['message_id']}" if chat.get("username") else ""

    def _follow_up(self, rest):
        if rest:  # long text that does not fit in a caption goes as a follow-up message
            self._result(self._call("POST", self._url("sendMessage"), "Send message",
                                    data={"chat_id": self.account.external_id, "text": rest}))

    def publish_images(self, text, images):
        chat_id = self.account.external_id
        text = text or ""
        caption, rest = (text, "") if len(text) <= CAPTION_LIMIT else ("", text)
        if not images:
            message = self._result(self._call("POST", self._url("sendMessage"), "Send message",
                                              data={"chat_id": chat_id, "text": text}))
            rest = ""
        elif len(images) == 1:
            item = images[0]
            message = self._result(self._call("POST", self._url("sendPhoto"), "Send photo",
                                              data={"chat_id": chat_id, "caption": caption},
                                              files={"photo": (item.filename, self._bytes(item), item.mimetype)}))
        else:
            media, files = [], {}
            for index, item in enumerate(images[:10]):
                key = f"photo{index}"
                entry = {"type": "photo", "media": f"attach://{key}"}
                if index == 0 and caption:
                    entry["caption"] = caption
                media.append(entry)
                files[key] = (item.filename, self._bytes(item), item.mimetype)
            messages = self._result(self._call("POST", self._url("sendMediaGroup"), "Send album",
                                               data={"chat_id": chat_id, "media": json.dumps(media)}, files=files))
            message = messages[0]
        self._follow_up(rest)
        return {"external_id": str(message.get("message_id")), "url": self._link(message)}

    def _send_file(self, method, field, text, item, operation):
        text = text or ""
        caption, rest = (text, "") if len(text) <= CAPTION_LIMIT else ("", text)
        message = self._result(self._call(
            "POST", self._url(method), operation, data={"chat_id": self.account.external_id, "caption": caption},
            files={field: (item.filename, self._bytes(item), item.mimetype)}, timeout=600))
        self._follow_up(rest)
        return {"external_id": str(message.get("message_id")), "url": self._link(message)}

    def publish_video(self, text, video):
        return self._send_file("sendVideo", "video", text, video, "Send video")

    def publish_audio(self, text, audio):
        return self._send_file("sendAudio", "audio", text, audio, "Send audio")

    def fetch_audience(self):
        count = self._result(self._call("GET", self._url("getChatMemberCount"), "Read members",
                                        params={"chat_id": self.account.external_id}))
        return {"followers": int(count or 0)}
