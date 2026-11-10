"""LinkedIn Posts API. ``external_id`` is the author URN (``urn:li:person:…`` or ``urn:li:organization:…``)."""
from urllib.parse import quote

from app.core.http import ApiError

from .base import BasePublisher

API = "https://api.linkedin.com"
DEFAULT_VERSION = "202510"


def escape_little_text(text: str) -> str:
    """LinkedIn 'commentary' uses the Little Text format: reserved characters must be escaped or the post is
    truncated/rejected. '#' is kept so hashtags keep working."""
    out = []
    for char in text:
        if char in "\\|{}@[]()<>*_~":
            out.append("\\" + char)
        else:
            out.append(char)
    return "".join(out)


class LinkedInPublisher(BasePublisher):
    platform = "linkedin"
    max_chars = 3000
    max_images = 20

    def _headers(self, json_body=True):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "LinkedIn-Version": self._setting("linkedin_api_version", DEFAULT_VERSION),
            "X-Restli-Protocol-Version": "2.0.0",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def fetch_profile(self):
        urn = self.account.external_id or ""
        if urn.startswith("urn:li:organization:"):
            data = self._call("GET", f"{API}/rest/organizations/{urn.rsplit(':', 1)[-1]}", "Read organization",
                              headers=self._headers(False))
            name = data.get("localizedName") or data.get("vanityName")
            return {"name": name, "username": data.get("vanityName") or name, "avatar_url": ""}
        data = self._call("GET", f"{API}/v2/userinfo", "Read profile", headers={"Authorization": f"Bearer {self.token}"})
        return {
            "name": data.get("name"),
            "username": data.get("email") or data.get("name"),
            "avatar_url": data.get("picture"),
            "external_id": f"urn:li:person:{data['sub']}" if data.get("sub") else None,
        }

    def _upload_image(self, media):
        init = self._call("POST", f"{API}/rest/images?action=initializeUpload", "Init image upload",
                          headers=self._headers(),
                          json_body={"initializeUploadRequest": {"owner": self.account.external_id}})
        value = init.get("value") or {}
        upload_url, image_urn = value.get("uploadUrl"), value.get("image")
        if not upload_url or not image_urn:
            raise ApiError("LinkedIn did not return an upload URL.")
        self._call("PUT", upload_url, "Upload image", headers={"Authorization": f"Bearer {self.token}"},
                   data=self._bytes(media), expect_json=False)
        return image_urn

    def _base_body(self, text):
        if not (self.account.external_id or "").startswith("urn:li:"):
            raise ApiError("LinkedIn author must be a URN like urn:li:person:xxxx or urn:li:organization:1234.")
        return {
            "author": self.account.external_id,
            "commentary": escape_little_text(text or ""),
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                             "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

    def publish_images(self, text, images):
        body = self._base_body(text)
        urns = [self._upload_image(item) for item in images]
        if len(urns) == 1:
            body["content"] = {"media": {"id": urns[0]}}
        elif urns:
            body["content"] = {"multiImage": {"images": [{"id": urn} for urn in urns]}}
        return self._create_post(body)

    def publish_video(self, text, video):
        body = self._base_body(text)
        content = self._bytes(video)
        init = self._call("POST", f"{API}/rest/videos?action=initializeUpload", "Init video upload",
                          headers=self._headers(), json_body={"initializeUploadRequest": {
                              "owner": self.account.external_id, "fileSizeBytes": len(content),
                              "uploadCaptions": False, "uploadThumbnail": False}})
        value = init.get("value") or {}
        etags = []
        for part in value.get("uploadInstructions") or []:
            chunk = content[int(part["firstByte"]):int(part["lastByte"]) + 1]
            response = self._call("PUT", part["uploadUrl"], "Upload video part", data=chunk, expect_json=False,
                                  timeout=300, headers={"Content-Type": "application/octet-stream"})
            etags.append(response.headers.get("etag") or response.headers.get("ETag"))
        self._call("POST", f"{API}/rest/videos?action=finalizeUpload", "Finalize video",
                   headers=self._headers(), json_body={"finalizeUploadRequest": {
                       "video": value.get("video"), "uploadToken": value.get("uploadToken") or "",
                       "uploadedPartIds": etags}})
        body["content"] = {"media": {"id": value.get("video"), "title": ((text or "Video").splitlines() or ["Video"])[0][:100]}}
        return self._create_post(body)

    def _create_post(self, body):
        response = self._call("POST", f"{API}/rest/posts", "Publish post", headers=self._headers(),
                              json_body=body, expect_json=False)
        post_urn = response.headers.get("x-restli-id") or response.headers.get("x-linkedin-id") or ""
        url = f"https://www.linkedin.com/feed/update/{quote(post_urn, safe=':')}/" if post_urn else ""
        return {"external_id": post_urn, "url": url}

    def fetch_audience(self):
        urn = self.account.external_id or ""
        if not urn.startswith("urn:li:organization:"):
            return {}
        data = self._call("GET", f"{API}/rest/networkSizes/{quote(urn, safe='')}", "Read followers",
                          headers=self._headers(False), params={"edgeType": "COMPANY_FOLLOWED_BY_MEMBER"})
        return {"followers": data.get("firstDegreeSize", 0)}

    def fetch_metrics(self, targets):
        result = {}
        for target in targets:
            try:
                data = self._call("GET", f"{API}/rest/socialActions/{quote(target.external_id, safe='')}",
                                  "Read post stats", headers=self._headers(False))
            except ApiError:
                continue
            result[target.id] = {
                "likes": (data.get("likesSummary") or {}).get("totalLikes", 0),
                "comments": (data.get("commentsSummary") or {}).get("aggregatedTotalComments", 0),
            }
        return result
