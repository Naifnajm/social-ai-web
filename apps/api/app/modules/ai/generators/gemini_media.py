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

    def video_start(self, prompt, aspect="16:9", seconds=8, image=None):
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
