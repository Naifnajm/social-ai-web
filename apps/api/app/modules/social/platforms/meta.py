"""Facebook Pages, Instagram (Business/Creator) and Threads."""
import json
import time

from app.core.http import ApiError

from .base import BasePublisher, kind_of

GRAPH = "https://graph.facebook.com"
DEFAULT_GRAPH_VERSION = "v24.0"


def sleep(seconds: float) -> None:  # patched in tests
    time.sleep(seconds)


class _GraphMixin:
    def _version(self):
        return self._setting("meta_graph_version", DEFAULT_GRAPH_VERSION)

    def _graph(self):
        return f"{GRAPH}/{self._version()}"


class FacebookPublisher(_GraphMixin, BasePublisher):
    platform = "facebook"
    max_chars = 63206
    supports_story = True

    def fetch_profile(self):
        data = self._call("GET", f"{self._graph()}/{self.account.external_id}", "Read page",
                          params={"fields": "name,username,picture{url}", "access_token": self.token})
        return {
            "name": data.get("name"),
            "username": data.get("username") or data.get("name"),
            "avatar_url": ((data.get("picture") or {}).get("data") or {}).get("url"),
        }

    def publish_images(self, text, images):
        base = f"{self._graph()}/{self.account.external_id}"
        if not images:
            data = self._call("POST", f"{base}/feed", "Publish post",
                              data={"message": text or "", "access_token": self.token})
            post_id = data.get("id")
        elif len(images) == 1:
            media = images[0]
            data = self._call("POST", f"{base}/photos", "Publish photo",
                              data={"caption": text or "", "access_token": self.token},
                              files={"source": (media.filename, self._bytes(media), media.mimetype)})
            post_id = data.get("post_id") or data.get("id")
        else:
            payload = {"message": text or "", "access_token": self.token}
            for index, media in enumerate(images):
                photo = self._call("POST", f"{base}/photos", "Upload photo",
                                   data={"published": "false", "access_token": self.token},
                                   files={"source": (media.filename, self._bytes(media), media.mimetype)})
                payload[f"attached_media[{index}]"] = json.dumps({"media_fbid": photo["id"]})
            data = self._call("POST", f"{base}/feed", "Publish post", data=payload)
            post_id = data.get("id")
        if not post_id:
            raise ApiError("Facebook did not return a post id.")
        return {"external_id": post_id, "url": f"https://www.facebook.com/{post_id}"}

    def publish_video(self, text, video):
        page = self.account.external_id
        data = self._call("POST", f"https://graph-video.facebook.com/{self._version()}/{page}/videos", "Publish video",
                          data={"description": text or "", "access_token": self.token},
                          files={"source": (video.filename, self._bytes(video), video.mimetype)}, timeout=600)
        video_id = data.get("id")
        if not video_id:
            raise ApiError("Facebook did not return a video id.")
        return {"external_id": video_id, "url": f"https://www.facebook.com/{page}/videos/{video_id}"}

    # -- stories ------------------------------------------------------------------
    def publish_story(self, media):
        """Page stories: one story per image or video."""
        if not media:
            raise ApiError("A story needs an image or a video.")
        ids = [self._video_story(item) if kind_of(item) == "video" else self._photo_story(item) for item in media]
        page = self.account.external_id
        return {"external_id": ",".join(i for i in ids if i), "url": f"https://www.facebook.com/stories/{page}"}

    def _photo_story(self, media):
        base = f"{self._graph()}/{self.account.external_id}"
        photo = self._call("POST", f"{base}/photos", "Upload story photo",
                           data={"published": "false", "access_token": self.token},
                           files={"source": (media.filename, self._bytes(media), media.mimetype)})
        if not photo.get("id"):
            raise ApiError("Facebook did not return a photo id for the story.")
        data = self._call("POST", f"{base}/photo_stories", "Publish photo story",
                          data={"photo_id": photo["id"], "access_token": self.token})
        if data.get("success") is False:
            raise ApiError("Facebook refused the photo story.")
        return data.get("post_id") or photo["id"]

    def _video_story(self, media):
        base = f"{self._graph()}/{self.account.external_id}"
        start = self._call("POST", f"{base}/video_stories", "Start video story",
                           data={"upload_phase": "start", "access_token": self.token})
        video_id, upload_url = start.get("video_id"), start.get("upload_url")
        if not video_id or not upload_url:
            raise ApiError("Facebook did not return an upload address for the video story.")
        content = self._bytes(media)
        self._call("POST", upload_url, "Upload video story",
                   headers={"Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(len(content))},
                   data=content, timeout=600)
        data = self._call("POST", f"{base}/video_stories", "Publish video story",
                          data={"upload_phase": "finish", "video_id": video_id, "access_token": self.token})
        if data.get("success") is False:
            raise ApiError("Facebook refused the video story.")
        return data.get("post_id") or video_id

    def fetch_audience(self):
        data = self._call("GET", f"{self._graph()}/{self.account.external_id}", "Read followers",
                          params={"fields": "followers_count,fan_count", "access_token": self.token})
        return {"followers": data.get("followers_count") or data.get("fan_count") or 0}

    def fetch_metrics(self, targets):
        result = {}
        for target in targets:
            post_id = target.external_id
            metrics = {}
            try:
                data = self._call("GET", f"{self._graph()}/{post_id}", "Read post stats", params={
                    "fields": "shares,reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)",
                    "access_token": self.token})
                metrics.update(
                    likes=((data.get("reactions") or {}).get("summary") or {}).get("total_count", 0),
                    comments=((data.get("comments") or {}).get("summary") or {}).get("total_count", 0),
                    shares=(data.get("shares") or {}).get("count", 0),
                )
            except ApiError:
                continue
            try:
                insights = self._call("GET", f"{self._graph()}/{post_id}/insights", "Read post insights",
                                      params={"metric": "post_impressions,post_impressions_unique,post_clicks",
                                              "access_token": self.token})
                values = {row["name"]: (row.get("values") or [{}])[0].get("value", 0)
                          for row in insights.get("data", [])}
                metrics.update(impressions=values.get("post_impressions", 0),
                               reach=values.get("post_impressions_unique", 0),
                               clicks=values.get("post_clicks", 0))
            except ApiError:
                pass  # insights need pages_read_engagement; the counts above are still useful
            result[target.id] = metrics
        return result


class InstagramPublisher(_GraphMixin, BasePublisher):
    """Instagram Graph API — media must be reachable by Meta through a public URL."""

    platform = "instagram"
    max_chars = 2200
    requires_media = True
    supports_text_only = False
    supports_story = True

    def fetch_profile(self):
        data = self._call("GET", f"{self._graph()}/{self.account.external_id}", "Read profile",
                          params={"fields": "username,name,profile_picture_url", "access_token": self.token})
        return {
            "name": data.get("name") or data.get("username"),
            "username": data.get("username"),
            "avatar_url": data.get("profile_picture_url"),
        }

    def _create_container(self, params, operation):
        params["access_token"] = self.token
        data = self._call("POST", f"{self._graph()}/{self.account.external_id}/media", operation, data=params)
        if not data.get("id"):
            raise ApiError("Instagram did not return a media container.")
        return data["id"]

    def _wait_ready(self, container_id, attempts=10, delay=2):
        for _i in range(attempts):
            data = self._call("GET", f"{self._graph()}/{container_id}", "Check media status",
                              params={"fields": "status_code", "access_token": self.token})
            status = data.get("status_code")
            if status in (None, "FINISHED", "PUBLISHED"):
                return
            if status in ("ERROR", "EXPIRED"):
                raise ApiError(f"Instagram could not process the media ({status}).")
            sleep(delay)
        raise ApiError("Instagram is still processing the media. Try again in a minute.")

    def publish_images(self, text, images):
        if len(images) == 1:
            container = self._create_container(
                {"image_url": self._public_url(images[0]), "caption": text or ""}, "Create media")
        else:
            children = [self._create_container({"image_url": self._public_url(item), "is_carousel_item": "true"},
                                               "Create carousel item") for item in images]
            container = self._create_container(
                {"media_type": "CAROUSEL", "children": ",".join(children), "caption": text or ""}, "Create carousel")
        return self._finish(container)

    def publish_video(self, text, video):
        container = self._create_container(
            {"media_type": "REELS", "video_url": self._public_url(video), "caption": text or "",
             "share_to_feed": "true"}, "Create reel")
        return self._finish(container, attempts=40, delay=5)

    def _finish(self, container, attempts=10, delay=2):
        self._wait_ready(container, attempts, delay)
        data = self._call("POST", f"{self._graph()}/{self.account.external_id}/media_publish", "Publish media",
                          data={"creation_id": container, "access_token": self.token})
        media_id = data.get("id")
        if not media_id:
            raise ApiError("Instagram did not return a post id.")
        url = ""
        try:
            url = self._call("GET", f"{self._graph()}/{media_id}", "Read permalink",
                             params={"fields": "permalink", "access_token": self.token}).get("permalink", "")
        except ApiError:
            pass
        return {"external_id": media_id, "url": url}

    def publish_story(self, media):
        """Instagram stories (``media_type=STORIES``): one story per image or video."""
        if not media:
            raise ApiError("A story needs an image or a video.")
        ids = []
        for item in media:
            if kind_of(item) == "video":
                container = self._create_container(
                    {"media_type": "STORIES", "video_url": self._public_url(item)}, "Create video story")
                self._wait_ready(container, attempts=40, delay=5)
            else:
                container = self._create_container(
                    {"media_type": "STORIES", "image_url": self._public_url(item)}, "Create story")
                self._wait_ready(container)
            data = self._call("POST", f"{self._graph()}/{self.account.external_id}/media_publish", "Publish story",
                              data={"creation_id": container, "access_token": self.token})
            if not data.get("id"):
                raise ApiError("Instagram did not return a story id.")
            ids.append(data["id"])
        username = (self.account.username or "").lstrip("@")
        return {"external_id": ",".join(ids), "url": f"https://www.instagram.com/stories/{username}/" if username else ""}

    def fetch_audience(self):
        data = self._call("GET", f"{self._graph()}/{self.account.external_id}", "Read followers",
                          params={"fields": "followers_count", "access_token": self.token})
        return {"followers": data.get("followers_count", 0)}

    def fetch_metrics(self, targets):
        result = {}
        for target in targets:
            try:
                data = self._call("GET", f"{self._graph()}/{target.external_id}", "Read post stats",
                                  params={"fields": "like_count,comments_count,media_product_type",
                                          "access_token": self.token})
            except ApiError:
                continue
            metrics = {"likes": data.get("like_count", 0), "comments": data.get("comments_count", 0)}
            try:
                insights = self._call("GET", f"{self._graph()}/{target.external_id}/insights", "Read post insights",
                                      params={"metric": "reach,saved,shares,views", "access_token": self.token})
                values = {row["name"]: (row.get("values") or [{}])[0].get("value", 0)
                          for row in insights.get("data", [])}
                metrics.update(reach=values.get("reach", 0), saves=values.get("saved", 0),
                               shares=values.get("shares", 0), impressions=values.get("views", 0),
                               video_views=values.get("views", 0) if data.get("media_product_type") == "REELS" else 0)
            except ApiError:
                pass
            result[target.id] = metrics
        return result


class ThreadsPublisher(BasePublisher):
    """Threads API (graph.threads.net)."""

    platform = "threads"
    max_chars = 500
    max_images = 20

    def _base(self):
        return f"https://graph.threads.net/{self._setting('threads_api_version', 'v1.0')}"

    def _user(self):
        return self.account.external_id or "me"

    def fetch_profile(self):
        data = self._call("GET", f"{self._base()}/me", "Read profile",
                          params={"fields": "id,username,name,threads_profile_picture_url",
                                  "access_token": self.token})
        return {
            "name": data.get("name") or data.get("username"),
            "username": data.get("username"),
            "avatar_url": data.get("threads_profile_picture_url"),
            "external_id": data.get("id"),
        }

    def _container(self, params, operation):
        params["access_token"] = self.token
        return self._call("POST", f"{self._base()}/{self._user()}/threads", operation, data=params)["id"]

    def _publish_container(self, container):
        data = self._call("POST", f"{self._base()}/{self._user()}/threads_publish", "Publish thread",
                          data={"creation_id": container, "access_token": self.token})
        media_id = data.get("id")
        if not media_id:
            raise ApiError("Threads did not return a post id.")
        url = ""
        try:
            url = self._call("GET", f"{self._base()}/{media_id}", "Read permalink",
                             params={"fields": "permalink", "access_token": self.token}).get("permalink", "")
        except ApiError:
            pass
        return {"external_id": media_id, "url": url}

    def publish_images(self, text, images):
        if not images:
            container = self._container({"media_type": "TEXT", "text": text or ""}, "Create thread")
        elif len(images) == 1:
            container = self._container({"media_type": "IMAGE", "image_url": self._public_url(images[0]),
                                         "text": text or ""}, "Create thread")
        else:
            children = [self._container({"media_type": "IMAGE", "image_url": self._public_url(item),
                                         "is_carousel_item": "true"}, "Create carousel item") for item in images]
            container = self._container({"media_type": "CAROUSEL", "children": ",".join(children),
                                         "text": text or ""}, "Create carousel")
        if images:
            sleep(2)  # Meta recommends a short wait before publishing media
        return self._publish_container(container)

    def publish_video(self, text, video):
        container = self._container({"media_type": "VIDEO", "video_url": self._public_url(video),
                                     "text": text or ""}, "Create video thread")
        for _i in range(40):
            status = self._call("GET", f"{self._base()}/{container}", "Check video status",
                                params={"fields": "status,error_message", "access_token": self.token})
            if status.get("status") in (None, "FINISHED", "PUBLISHED"):
                break
            if status.get("status") in ("ERROR", "EXPIRED"):
                raise ApiError(f"Threads could not process the video: {status.get('error_message', '')}")
            sleep(5)
        return self._publish_container(container)

    def fetch_audience(self):
        data = self._call("GET", f"{self._base()}/{self._user()}/threads_insights", "Read followers",
                          params={"metric": "followers_count", "access_token": self.token})
        row = (data.get("data") or [{}])[0]
        return {"followers": (row.get("total_value") or {}).get("value", 0)}

    def fetch_metrics(self, targets):
        result = {}
        for target in targets:
            try:
                data = self._call("GET", f"{self._base()}/{target.external_id}/insights", "Read post insights",
                                  params={"metric": "views,likes,replies,reposts,quotes", "access_token": self.token})
            except ApiError:
                continue
            values = {row["name"]: (row.get("values") or [{}])[0].get("value", 0) for row in data.get("data", [])}
            result[target.id] = {"impressions": values.get("views", 0), "likes": values.get("likes", 0),
                                 "comments": values.get("replies", 0),
                                 "shares": values.get("reposts", 0) + values.get("quotes", 0)}
        return result
