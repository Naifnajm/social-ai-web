"""TikTok Content Posting API — photos and videos pulled from a public URL.

The media URL domain must be verified in the TikTok developer portal, and unaudited apps can only post with
privacy ``SELF_ONLY`` (account ``extra.privacy_level``).
"""
from app.core.http import ApiError

from .base import BasePublisher

API = "https://open.tiktokapis.com/v2"
PRIVACY_LEVELS = ("SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE")


class TikTokPublisher(BasePublisher):
    platform = "tiktok"
    max_chars = 4000
    max_images = 35
    requires_media = True
    supports_text_only = False

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json; charset=UTF-8"}

    def _privacy(self):
        level = (self.account.extra or {}).get("privacy_level")
        return level if level in PRIVACY_LEVELS else "SELF_ONLY"

    def fetch_profile(self):
        data = self._call("GET", f"{API}/user/info/", "Read profile", headers=self._headers(),
                          params={"fields": "open_id,avatar_url,display_name,username"})
        user = (data.get("data") or {}).get("user") or {}
        return {"name": user.get("display_name"), "username": user.get("username") or user.get("display_name"),
                "avatar_url": user.get("avatar_url"), "external_id": user.get("open_id")}

    @staticmethod
    def _raise_error(data):
        error = data.get("error") or {}
        if error.get("code") not in (None, "ok"):
            raise ApiError(f"TikTok: {error.get('message') or error.get('code')}")

    def publish_images(self, text, images):
        lines = (text or "").strip().splitlines() or [""]
        body = {
            "post_info": {"title": lines[0][:90], "description": (text or "")[:4000],
                          "privacy_level": self._privacy(), "disable_comment": False, "auto_add_music": True},
            "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0,
                            "photo_images": [self._public_url(item) for item in images]},
            "post_mode": "DIRECT_POST",
            "media_type": "PHOTO",
        }
        data = self._call("POST", f"{API}/post/publish/content/init/", "Publish photo post", headers=self._headers(),
                          json_body=body)
        self._raise_error(data)
        publish_id = (data.get("data") or {}).get("publish_id")
        if not publish_id:
            raise ApiError("TikTok did not return a publish id.")
        return {"external_id": publish_id, "url": ""}  # processed asynchronously: no public URL yet

    def publish_video(self, text, video):
        body = {
            "post_info": {"title": (text or "")[:2200], "privacy_level": self._privacy(),
                          "disable_comment": False, "disable_duet": False, "disable_stitch": False},
            "source_info": {"source": "PULL_FROM_URL", "video_url": self._public_url(video)},
        }
        data = self._call("POST", f"{API}/post/publish/video/init/", "Publish video", headers=self._headers(),
                          json_body=body)
        self._raise_error(data)
        publish_id = (data.get("data") or {}).get("publish_id")
        if not publish_id:
            raise ApiError("TikTok did not return a publish id.")
        return {"external_id": publish_id, "url": ""}

    def fetch_audience(self):
        data = self._call("GET", f"{API}/user/info/", "Read followers", headers=self._headers(),
                          params={"fields": "follower_count"})
        return {"followers": ((data.get("data") or {}).get("user") or {}).get("follower_count", 0)}

    def fetch_metrics(self, targets):
        # TikTok returns a publish id first; the public video id appears once processing is done.
        video_ids = {}
        for target in targets:
            video_id = target.external_ref
            if not video_id:
                try:
                    status = self._call("POST", f"{API}/post/publish/status/fetch/", "Read publish status",
                                        headers=self._headers(), json_body={"publish_id": target.external_id})
                    ids = (status.get("data") or {}).get("publicaly_available_post_id") or []
                    video_id = str(ids[0]) if ids else None
                    if video_id:
                        target.external_ref = video_id
                        target.external_url = f"https://www.tiktok.com/@{self.account.username or ''}/video/{video_id}"
                except ApiError:
                    video_id = None
            if video_id:
                video_ids[video_id] = target
        if not video_ids:
            return {}
        try:
            data = self._call("POST", f"{API}/video/query/", "Read post stats", headers=self._headers(),
                              params={"fields": "id,like_count,comment_count,share_count,view_count"},
                              json_body={"filters": {"video_ids": list(video_ids)[:20]}})
        except ApiError:
            return {}
        result = {}
        for video in (data.get("data") or {}).get("videos", []):
            target = video_ids.get(str(video.get("id")))
            if target:
                result[target.id] = {"impressions": video.get("view_count", 0),
                                     "video_views": video.get("view_count", 0), "likes": video.get("like_count", 0),
                                     "comments": video.get("comment_count", 0), "shares": video.get("share_count", 0)}
        return result
