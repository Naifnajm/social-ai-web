"""Pinterest API v5 — image pins on a board.

``external_id`` is the Pinterest user id; the board the pins go to is ``extra.board_id`` (chosen from
``extra.boards`` in the account settings; the first board by default). Testing the connection reads the boards
again. A link in the text becomes the pin's link.

Written from Pinterest's API reference; not yet run against the live API. Until Pinterest gives the app
"Standard" access, pins created through it are visible to the account owner only.
"""
import base64

from app.core.http import ApiError

from .base import BasePublisher
from .google import first_link

API = "https://api.pinterest.com/v5"
TITLE_MAX = 100
DESCRIPTION_MAX = 800
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")


def board_of(extra: dict | None) -> str | None:
    """The board pins go to: the chosen one when it still exists, else the first board."""
    extra = extra or {}
    ids = [str(b.get("id")) for b in extra.get("boards") or [] if b.get("id")]
    chosen = extra.get("board_id")
    if chosen and (str(chosen) in ids or not ids):
        return str(chosen)
    return ids[0] if ids else None


class PinterestPublisher(BasePublisher):
    platform = "pinterest"
    max_chars = DESCRIPTION_MAX
    max_images = 1
    requires_media = True
    supports_text_only = False
    supports_video = False

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def fetch_profile(self):
        data = self._call("GET", f"{API}/user_account", "Read profile", headers=self._headers())
        listed = self._call("GET", f"{API}/boards", "List boards", headers=self._headers(), params={"page_size": 100})
        boards = [{"id": str(b["id"]), "name": b.get("name") or str(b["id"])} for b in listed.get("items") or []
                  if b.get("id")]
        self.account.extra = dict(self.account.extra or {}, boards=boards)
        return {"name": data.get("business_name") or data.get("username"), "username": data.get("username"),
                "avatar_url": data.get("profile_image"), "external_id": data.get("id") or data.get("username")}

    def publish_images(self, text, images):
        board = board_of(self.account.extra)
        if not board:
            raise ApiError("This Pinterest account has no board. Create a board on Pinterest, then test the "
                           "connection again.")
        if not images:
            raise ApiError("Pinterest needs an image.")
        image = images[0]
        if image.mimetype not in IMAGE_TYPES:
            raise ApiError("Pinterest accepts JPEG, PNG or WebP images.")
        lines = [line for line in (text or "").strip().splitlines() if line.strip()]
        body = {
            "board_id": str(board),
            "title": (lines[0] if lines else "")[:TITLE_MAX],
            "description": (text or "")[:DESCRIPTION_MAX],
            "media_source": {"source_type": "image_base64", "content_type": image.mimetype,
                             "data": base64.b64encode(self._bytes(image)).decode()},
        }
        link = first_link(text)
        if link:
            body["link"] = link
        data = self._call("POST", f"{API}/pins", "Create pin", headers=self._headers(), json_body=body)
        pin_id = data.get("id")
        if not pin_id:
            raise ApiError("Pinterest did not return a pin id.")
        return {"external_id": str(pin_id), "url": f"https://www.pinterest.com/pin/{pin_id}/"}

    def fetch_audience(self):
        data = self._call("GET", f"{API}/user_account", "Read followers", headers=self._headers())
        return {"followers": int(data.get("follower_count") or 0)}

    def fetch_metrics(self, targets):
        result = {}
        for target in targets:
            try:
                data = self._call("GET", f"{API}/pins/{target.external_id}", "Read pin stats",
                                  headers=self._headers(), params={"pin_metrics": "true"})
            except ApiError:
                continue
            totals = ((data.get("pin_metrics") or {}).get("lifetime_metrics")
                      or (data.get("pin_metrics") or {}).get("all_time") or {})
            if totals:
                result[target.id] = {"impressions": int(totals.get("impression") or 0),
                                     "saves": int(totals.get("save") or 0),
                                     "clicks": int(totals.get("outbound_click") or totals.get("pin_click") or 0),
                                     "likes": int(totals.get("reaction") or 0),
                                     "comments": int(totals.get("comment") or 0)}
        return result
