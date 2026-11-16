"""Google: Gemini image model (generation + editing) and Veo video (text or image to video)."""
import base64

from app.core.http import ApiError

from .base import BaseMediaClient, download


class GeminiMediaClient(BaseMediaClient):
    supports_image_edit = True
    supports_image_to_video = True

    def _headers(self):
        return {"Content-Type": "application/json", "x-goog-api-key": self.api_key}

    @staticmethod
    def _model(name):
        return name if name.startswith("models/") else "models/%s" % name

    def test(self):
        data = self._call("GET", "/models", "List models", headers=self._headers(), params={"pageSize": 200},
                          timeout=20)
        return [m["name"].split("/", 1)[-1] for m in data.get("models") or []]

    def image(self, prompt, aspect="1:1", refs=None):
        parts = [{"inlineData": {"mimeType": ref.mimetype, "data": ref.b64()}} for ref in (refs or [])[:3]]
        parts.append({"text": prompt})
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}},
        }
        data = self._call("POST", "/%s:generateContent" % self._model(self.image_model), "Generate image",
                          headers=self._headers(), json_body=body, timeout=240)
        for candidate in data.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return {"content": base64.b64decode(inline["data"]),
                            "mimetype": inline.get("mimeType") or inline.get("mime_type") or "image/png"}
        reason = (data.get("promptFeedback") or {}).get("blockReason")
        raise ApiError("Gemini returned no image%s." % (" (%s)" % reason if reason else ""))

    # -- Gemini Omni (Interactions API) --------------------------------------------
    # Omni models run on the stateful Interactions API (/v1beta/interactions), not on generateContent or
    # predictLongRunning. Clips are 3-15 seconds. Written from Google's announcement and developer guides
    # (November 2026); not yet run against the live API.
    @staticmethod
    def is_omni(model) -> bool:
        return (model or "").startswith("gemini-omni")

    def _omni_start(self, prompt, aspect, seconds, image):
        parts = [{"type": "text", "text": prompt}]
        if image:
            parts.insert(0, {"type": "image", "mime_type": image.mimetype, "data": image.b64()})
        body = {"model": self.video_model, "input": parts,
                "response_format": {"type": "video", "duration": "%ss" % max(3, min(int(seconds or 8), 15)),
                                    "resolution": "720p", "aspect_ratio": aspect if aspect in ("16:9", "9:16")
                                    else ("9:16" if aspect in ("4:5", "3:4") else "16:9"),
                                    "delivery": "uri"}}
        data = self._call("POST", "/interactions", "Start Omni video", headers=self._headers(), json_body=body,
                          timeout=90)
        found = self._omni_video(data)
        if found:
            return found
        if not data.get("id"):
            raise ApiError("Gemini Omni did not return an interaction id.")
        return {"job": "interactions/%s" % data["id"]}

    def _omni_video(self, data):
        """The video of a finished interaction (a URI to download or inline bytes), else None."""
        status = str(data.get("status") or data.get("state") or "").lower()
        if status in ("failed", "cancelled", "canceled") or data.get("error"):
            message = (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else None
            raise ApiError("Video generation failed: %s" % (message or status or "unknown reason"))

        def walk(node):
            if isinstance(node, dict):
                mime = str(node.get("mime_type") or node.get("mimeType") or "")
                if node.get("type") == "video" or mime.startswith("video/"):
                    if node.get("uri") or node.get("url"):
                        return {"uri": node.get("uri") or node.get("url")}
                    if node.get("data"):
                        return {"data": node["data"], "mimetype": mime or "video/mp4"}
                for value in node.values():
                    hit = walk(value)
                    if hit:
                        return hit
            elif isinstance(node, list):
                for value in node:
                    hit = walk(value)
                    if hit:
                        return hit
            return None

        hit = walk(data.get("outputs") or data.get("output") or [])
        if not hit:
            return None
        if hit.get("data"):
            return {"content": base64.b64decode(hit["data"]), "mimetype": hit["mimetype"]}
        content, mimetype = download(hit["uri"], self.provider, headers={"x-goog-api-key": self.api_key},
                                     default_mimetype="video/mp4")
        return {"content": content, "mimetype": mimetype}

    def video_start(self, prompt, aspect="16:9", seconds=8, image=None):
        if self.is_omni(self.video_model):
            return self._omni_start(prompt, aspect, seconds, image)
        instance = {"prompt": prompt}
        if image:
            instance["image"] = {"bytesBase64Encoded": image.b64(), "mimeType": image.mimetype}
        body = {"instances": [instance],
                "parameters": {"aspectRatio": "9:16" if aspect in ("9:16", "4:5") else "16:9"}}
        data = self._call("POST", "/%s:predictLongRunning" % self._model(self.video_model), "Start video",
                          headers=self._headers(), json_body=body, timeout=60)
        if not data.get("name"):
            raise ApiError("Veo did not return an operation id.")
        return {"job": data["name"]}

    def video_poll(self, job):
        if str(job).startswith("interactions/"):
            data = self._call("GET", "/%s" % job, "Check Omni video", headers=self._headers(), timeout=30)
            return self._omni_video(data) or {"status": "running", "progress": 0}
        data = self._call("GET", "/%s" % job, "Check video", headers=self._headers(), timeout=30)
        if not data.get("done"):
            return {"status": "running", "progress": 0}
        if data.get("error"):
            raise ApiError("Video generation failed: %s" % data["error"].get("message", "unknown reason"))
        response = data.get("response") or {}
        samples = (response.get("generateVideoResponse") or {}).get("generatedSamples") \
            or response.get("generatedVideos") or []
        uri = samples and (samples[0].get("video") or {}).get("uri")
        if not uri:
            raise ApiError("Veo finished without a video (it may have been filtered).")
        content, mimetype = download(uri, self.provider, headers={"x-goog-api-key": self.api_key},
                                     default_mimetype="video/mp4")
        return {"content": content, "mimetype": mimetype}
