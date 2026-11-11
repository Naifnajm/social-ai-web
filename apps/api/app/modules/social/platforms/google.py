"""Google: YouTube (video upload) and Google Business Profile (posts on a business listing).

Both use the same Google OAuth client; the scopes differ (see ``oauth.PLATFORMS``).

* YouTube — ``external_id`` is the channel id. Only videos; the first line of the text is the title.
* Google Business Profile — ``external_id`` is ``accounts/<id>/locations/<id>``, one account per location.
  Posts are text with an optional photo, which Google downloads from this server (public HTTPS).

Written from Google's reference pages; not yet run against the live APIs (they need an approved Google project).
"""
import json
import re

from app.core.http import ApiError

from .base import BasePublisher

YOUTUBE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
BUSINESS = "https://mybusiness.googleapis.com/v4"
PRIVACY = ("public", "unlisted", "private")
URL_RE = re.compile(r"https?://[^\s<>\"']+")
TITLE_MAX = 100
DESCRIPTION_MAX = 5000


def first_link(text: str) -> str | None:
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(").,!?;:") if match else None


class YouTubePublisher(BasePublisher):
    platform = "youtube"
    max_chars = DESCRIPTION_MAX
    max_images = 0
    requires_media = True
    supports_text_only = False
    supports_images = False

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _channel(self, part: str) -> dict:
        data = self._call("GET", f"{YOUTUBE}/channels", "Read channel", headers=self._headers(),
                          params={"part": part, "mine": "true"})
        items = data.get("items") or []
        if not items:
            raise ApiError("This Google account has no YouTube channel.")
        return items[0]

    def fetch_profile(self):
        channel = self._channel("snippet")
        snippet = channel.get("snippet") or {}
        return {"name": snippet.get("title"),
                "username": (snippet.get("customUrl") or snippet.get("title") or "").lstrip("@"),
                "avatar_url": ((snippet.get("thumbnails") or {}).get("default") or {}).get("url"),
                "external_id": channel.get("id")}

    def publish_images(self, text, images):
        raise ApiError("YouTube publishes videos only.")

    def publish_video(self, text, video):
        lines = [line for line in (text or "").strip().splitlines() if line.strip()]
        title = (lines[0] if lines else "Video").replace("<", "").replace(">", "")[:TITLE_MAX]
        privacy = (self.account.extra or {}).get("privacy_status")
        body = {
            "snippet": {"title": title, "description": (text or "")[:DESCRIPTION_MAX].replace("<", "").replace(">", "")},
            "status": {"privacyStatus": privacy if privacy in PRIVACY else "public",
                       "selfDeclaredMadeForKids": False},
        }
        content = self._bytes(video)
        mimetype = video.mimetype or "video/mp4"
        # Resumable upload: open a session, then send the file to the address Google returns.
        start = self._call("POST", YOUTUBE_UPLOAD, "Start video upload", expect_json=False,
                           params={"uploadType": "resumable", "part": "snippet,status"},
                           headers={**self._headers(), "Content-Type": "application/json; charset=UTF-8",
                                    "X-Upload-Content-Length": str(len(content)),
                                    "X-Upload-Content-Type": mimetype},
                           data=json.dumps(body).encode())
        upload_url = start.headers.get("Location") or start.headers.get("location")
        if not upload_url:
            raise ApiError("YouTube did not return an upload address.")
        result = self._call("PUT", upload_url, "Upload video", data=content, timeout=600,
                            headers={**self._headers(), "Content-Type": mimetype})
        video_id = result.get("id")
        if not video_id:
            raise ApiError("YouTube did not return a video id.")
        return {"external_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}

    def fetch_audience(self):
        stats = self._channel("statistics").get("statistics") or {}
        if stats.get("hiddenSubscriberCount"):
            return {}
        return {"followers": int(stats.get("subscriberCount") or 0)}

    def fetch_metrics(self, targets):
        by_id = {target.external_id: target for target in targets if target.external_id}
        result = {}
        ids = list(by_id)
        for start in range(0, len(ids), 50):
            try:
                data = self._call("GET", f"{YOUTUBE}/videos", "Read video stats", headers=self._headers(),
                                  params={"part": "statistics", "id": ",".join(ids[start:start + 50])})
            except ApiError:
                continue
            for item in data.get("items") or []:
                target, stats = by_id.get(item.get("id")), item.get("statistics") or {}
                if target:
                    views = int(stats.get("viewCount") or 0)
                    result[target.id] = {"impressions": views, "video_views": views,
                                         "likes": int(stats.get("likeCount") or 0),
                                         "comments": int(stats.get("commentCount") or 0)}
        return result


class GoogleBusinessPublisher(BasePublisher):
    platform = "google_business"
    max_chars = 1500
    max_images = 1
    supports_video = False

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _location(self) -> str:
        location = self.account.external_id or ""
        if not re.fullmatch(r"accounts/[^/]+/locations/[^/]+", location):
            raise ApiError("The Google business location must look like accounts/123/locations/456. "
                           "Reconnect the account.")
        return location

    def fetch_profile(self):
        # The Business Information API names a location without its account: locations/<id>.
        location = self._location().split("/", 2)[2]
        data = self._call("GET", f"https://mybusinessbusinessinformation.googleapis.com/v1/{location}",
                          "Read location", headers=self._headers(), params={"readMask": "name,title"})
        return {"name": data.get("title"), "username": data.get("title"), "avatar_url": ""}

    def _language(self) -> str:
        from app.modules.workspaces.models import Workspace
        workspace = self.db.get(Workspace, self.account.workspace_id)
        return (workspace.locale if workspace else None) or "en"

    def publish_images(self, text, images):
        body = {"languageCode": self._language(), "summary": (text or "")[:self.max_chars], "topicType": "STANDARD"}
        if images:
            body["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": self._public_url(images[0])}]
        link = first_link(text)
        if link:
            body["callToAction"] = {"actionType": "LEARN_MORE", "url": link}
        data = self._call("POST", f"{BUSINESS}/{self._location()}/localPosts", "Publish post",
                          headers=self._headers(), json_body=body)
        if not data.get("name"):
            raise ApiError("Google did not return the post.")
        return {"external_id": data["name"], "url": data.get("searchUrl") or ""}
