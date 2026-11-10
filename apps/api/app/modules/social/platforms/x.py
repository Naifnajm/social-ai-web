"""X (Twitter) API v2 with an OAuth 2.0 user token (tweet.read tweet.write users.read media.write offline.access)."""
from app.core.http import ApiError

from .base import BasePublisher
from .meta import sleep

API = "https://api.x.com/2"


class XPublisher(BasePublisher):
    platform = "x"
    max_chars = 280
    max_images = 4
    CHUNK = 4 * 1024 * 1024

    def _headers(self, json_body=False):
        headers = {"Authorization": f"Bearer {self.token}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def fetch_profile(self):
        data = self._call("GET", f"{API}/users/me", "Read profile", headers=self._headers(),
                          params={"user.fields": "profile_image_url,username,name"}).get("data", {})
        return {"name": data.get("name"), "username": data.get("username"),
                "avatar_url": data.get("profile_image_url"), "external_id": data.get("id")}

    def _upload(self, media):
        data = self._call("POST", f"{API}/media/upload", "Upload media", headers=self._headers(),
                          data={"media_category": "tweet_image", "media_type": media.mimetype},
                          files={"media": (media.filename, self._bytes(media), media.mimetype)})
        media_id = (data.get("data") or {}).get("id") or data.get("media_id_string")
        if not media_id:
            raise ApiError("X did not return a media id.")
        return media_id

    def publish_images(self, text, images):
        body = {"text": text or ""}
        if images:
            body["media"] = {"media_ids": [self._upload(item) for item in images]}
        return self._post_tweet(body)

    def _upload_video(self, video):
        """Chunked upload: initialize → append → finalize → wait for processing."""
        content = self._bytes(video)
        init = self._call("POST", f"{API}/media/upload/initialize", "Init video upload", headers=self._headers(True),
                          json_body={"media_type": video.mimetype or "video/mp4", "total_bytes": len(content),
                                     "media_category": "tweet_video"})
        media_id = (init.get("data") or {}).get("id")
        if not media_id:
            raise ApiError("X did not return a media id.")
        for index, start in enumerate(range(0, len(content), self.CHUNK)):
            self._call("POST", f"{API}/media/upload/{media_id}/append", "Upload video part", headers=self._headers(),
                       data={"segment_index": index},
                       files={"media": ("chunk", content[start:start + self.CHUNK], "application/octet-stream")},
                       timeout=300)
        final = self._call("POST", f"{API}/media/upload/{media_id}/finalize", "Finalize video",
                           headers=self._headers())
        info = (final.get("data") or {}).get("processing_info")
        for _i in range(40):
            if not info or info.get("state") == "succeeded":
                return media_id
            if info.get("state") == "failed":
                raise ApiError(f"X could not process the video: {(info.get('error') or {}).get('message', '')}")
            sleep(min(int(info.get("check_after_secs") or 3), 10))
            status = self._call("GET", f"{API}/media/upload", "Check video", headers=self._headers(),
                                params={"command": "STATUS", "media_id": media_id})
            info = (status.get("data") or {}).get("processing_info")
        raise ApiError("X is still processing the video. Try again in a minute.")

    def publish_video(self, text, video):
        return self._post_tweet({"text": text or "", "media": {"media_ids": [self._upload_video(video)]}})

    def _post_tweet(self, body):
        data = self._call("POST", f"{API}/tweets", "Publish post", headers=self._headers(True), json_body=body)
        tweet_id = (data.get("data") or {}).get("id")
        if not tweet_id:
            raise ApiError("X did not return a post id.")
        return {"external_id": tweet_id, "url": f"https://x.com/{self.account.username or 'i/web'}/status/{tweet_id}"}

    def fetch_audience(self):
        data = self._call("GET", f"{API}/users/me", "Read followers", headers=self._headers(),
                          params={"user.fields": "public_metrics"}).get("data", {})
        return {"followers": (data.get("public_metrics") or {}).get("followers_count", 0)}

    def fetch_metrics(self, targets):
        result = {}
        by_id = {t.external_id: t for t in targets if t.external_id}
        ids = list(by_id)
        for start in range(0, len(ids), 100):
            try:
                data = self._call("GET", f"{API}/tweets", "Read post stats", headers=self._headers(),
                                  params={"ids": ",".join(ids[start:start + 100]), "tweet.fields": "public_metrics"})
            except ApiError:
                continue
            for tweet in data.get("data", []):
                m = tweet.get("public_metrics") or {}
                target = by_id.get(str(tweet.get("id")))
                if target is None:
                    continue
                result[target.id] = {
                    "impressions": m.get("impression_count", 0), "likes": m.get("like_count", 0),
                    "comments": m.get("reply_count", 0),
                    "shares": m.get("retweet_count", 0) + m.get("quote_count", 0),
                    "saves": m.get("bookmark_count", 0),
                }
        return result
