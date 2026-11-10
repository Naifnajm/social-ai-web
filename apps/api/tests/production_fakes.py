"""Fakes of the contracts Production depends on (AI text/media, posts, brand templates) for its tests."""
import io
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.errors import AppError
from app.core.storage import save_media
from app.modules.ai import media as ai_media
from app.modules.ai import service as ai_service
from app.modules.ai.models import MediaJob
from app.modules.ai.service import Usage
from app.modules.social import service as social
from app.modules.social.models import Post, PostMedia, SocialAccount
from app.modules.templates import frame
from app.modules.workspaces.models import Membership
from tests.conftest import signup

HAS_FFMPEG = bool(shutil.which("ffmpeg"))


def png(size=(64, 48), color=(20, 20, 20)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


@lru_cache
def real_media() -> tuple[bytes, bytes]:
    """A real 1-second MP4 (with sound) and MP3, so ffmpeg really runs."""
    with tempfile.TemporaryDirectory() as tmp:
        mp4, mp3 = os.path.join(tmp, "v.mp4"), os.path.join(tmp, "a.mp3")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1", "-f", "lavfi",
                        "-i", "sine=frequency=300:duration=1", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", mp4], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", mp3],
                       check=True, capture_output=True)
        with open(mp4, "rb") as v, open(mp3, "rb") as a:
            return v.read(), a.read()


class FakeAI:
    """AI text + media jobs. Images and audio finish at once (the callback fires synchronously, like a real
    provider may do); videos stay running until ``finish_videos``."""

    PRICES = {"text": 0.001, "image": 0.04, "video": 0.8, "audio": 0.02}

    def __init__(self, monkeypatch):
        self.texts: list[dict] = []
        self.jobs: list[dict] = []
        self.fail_kinds: set[str] = set()
        self.text_reply = lambda n, user: "Text %d" % n
        self.segments = [{"start": 0, "end": 2, "text": "أهلاً وسهلاً"}]
        self.transcribed: list[dict] = []
        monkeypatch.setattr(ai_service, "generate_text_with_usage", self.generate)
        monkeypatch.setattr(ai_media, "start_job", self.start_job)
        monkeypatch.setattr(ai_media, "estimate", self.estimate)
        monkeypatch.setattr(ai_media, "transcribe", self.transcribe)

    def generate(self, db, workspace_id, system, user, **kwargs):
        self.texts.append({"system": system, "user": user, "workspace_id": workspace_id, **kwargs})
        return self.text_reply(len(self.texts), user), Usage(provider_id=None, model="gpt-test", cost=0.001)

    def start_job(self, db, workspace_id, kind, prompt, **kwargs):
        if kind in self.fail_kinds:
            raise AppError("The provider refused the request", code="provider")
        self.jobs.append({"kind": kind, "prompt": prompt, "workspace_id": workspace_id, **kwargs})
        job = MediaJob(workspace_id=workspace_id, kind=kind, prompt=prompt, state="running", cost=self.PRICES[kind],
                       aspect=kwargs.get("aspect", "1:1"), audio_mode=kwargs.get("audio_mode", "speech"),
                       voice=kwargs.get("voice"), input_media_ids=kwargs.get("inputs"), model_name="fake-" + kind,
                       callback=kwargs.get("callback"), callback_context=kwargs.get("callback_context"))
        db.add(job)
        db.flush()
        if kind != "video":
            self._finish(db, job)
            self._callback(db, job)
        return job

    def _finish(self, db, job):
        if job.kind == "image":
            content, name, mime = png(color=(len(self.jobs) * 20 % 255, 0, 0)), "img.png", "image/png"
        elif job.kind == "audio":
            content, name, mime = (real_media()[1] if HAS_FFMPEG else b"ID3audio"), "a.mp3", "audio/mpeg"
        else:
            content, name, mime = (real_media()[0] if HAS_FFMPEG else b"\x00\x00mp4"), "v.mp4", "video/mp4"
        media = save_media(db, job.workspace_id, content, name, mime, source="ai")
        job.media_id, job.state, job.progress = media.id, "done", 100

    @staticmethod
    def _callback(db, job):
        if job.callback:
            from app.core.jobs import _resolve
            _resolve(job.callback)(db, job)

    def finish_videos(self, db, fail=False):
        for job in db.scalars(select(MediaJob).where(MediaJob.state == "running", MediaJob.kind == "video")).all():
            if fail:
                job.state, job.error = "failed", "Video provider error"
            else:
                self._finish(db, job)
            db.flush()
            self._callback(db, job)

    def estimate(self, db, workspace_id, kind, prompt="", **kwargs):
        return {"cost": self.PRICES[kind], "model": "fake-" + kind}

    def transcribe(self, db, workspace_id, media_id, language=None):
        self.transcribed.append({"media_id": media_id, "language": language})
        return {"segments": self.segments, "duration": 2.0, "cost": 0.0002}


class FakeSocial:
    def __init__(self, monkeypatch):
        self.submitted: list[tuple[int, str]] = []
        monkeypatch.setattr(social, "create_post", self.create_post)
        monkeypatch.setattr(social, "submit", self.submit)

    def create_post(self, db, workspace_id, user_id, *, content="", media_ids=None, account_ids=None,
                    platform_media=None, name=None, source_ref=None, **kwargs):
        post = Post(workspace_id=workspace_id, content=content, name=name, platform_media=platform_media,
                    source_ref=source_ref, author_id=user_id, state="draft")
        post.accounts = [db.get(SocialAccount, i) for i in account_ids or []]
        post.media_links = [PostMedia(media_id=m, position=i) for i, m in enumerate(media_ids or [])]
        db.add(post)
        db.flush()
        return post

    def submit(self, db, post, user_id, *, action, when=None):
        self.submitted.append((post.id, action))
        if action == "publish":
            post.state = "posted"
        elif action == "best_time":
            post.state, post.scheduled_at = "scheduled", datetime.now(timezone.utc) + timedelta(days=1)
        elif action == "schedule":
            post.state, post.scheduled_at = "scheduled", when
        db.flush()
        return post


class FakeFrame:
    def __init__(self, monkeypatch):
        self.calls: list[tuple] = []
        monkeypatch.setattr(frame, "compose", self.compose)
        monkeypatch.setattr(frame, "compose_for_post", self.compose_for_post)
        monkeypatch.setattr(frame, "choices", lambda db, ws: [{"key": "template:7", "name": "Sale 4:5"},
                                                              {"key": "set:3", "name": "Launch set"}], raising=False)

    def compose(self, db, workspace_id, template_id, media_id, text=None):
        self.calls.append(("compose", template_id, media_id, text))
        return save_media(db, workspace_id, png((1080, 1350)), "framed.png", "image/png", source="template")

    def compose_for_post(self, db, workspace_id, ref, media_id, text=None, story=False):
        self.calls.append(("set", ref, media_id, text, story))
        size = (1080, 1920) if story else (1080, 1350)
        return save_media(db, workspace_id, png(size), "framed.png", "image/png", source="template")


@pytest.fixture()
def fake_ai(monkeypatch):
    return FakeAI(monkeypatch)


@pytest.fixture()
def fake_social(monkeypatch):
    return FakeSocial(monkeypatch)


@pytest.fixture()
def fake_frame(monkeypatch):
    return FakeFrame(monkeypatch)


# ---------------------------------------------------------------------------- API helpers
class Api:
    """Small client for the Production API of one signed-in user."""

    def __init__(self, client, auth, locale="en"):
        self.client, self.auth = client, auth
        self.headers = {**auth.headers, "Accept-Language": locale}

    def _ok(self, response, status=(200, 201, 204)):
        assert response.status_code in status, response.text
        return response.json() if response.content else None

    def get(self, path, **params):
        return self._ok(self.client.get("/api/production" + path, params=params, headers=self.headers))

    def post(self, path, body=None, status=(200, 201, 204)):
        return self._ok(self.client.post("/api/production" + path, json=body or {}, headers=self.headers),
                        status)

    def patch(self, path, body):
        return self._ok(self.client.patch("/api/production" + path, json=body, headers=self.headers))

    def put(self, path, body):
        return self._ok(self.client.put("/api/production" + path, json=body, headers=self.headers))

    def raw(self, method, path, body=None):
        return self.client.request(method, "/api/production" + path, json=body, headers=self.headers)

    def board(self, template="blank", name=None):
        return self.post("/boards", {"template": template, "name": name})["id"]

    def node(self, board_id, kind, x=0, y=0, **params):
        return self.post(f"/boards/{board_id}/nodes", {"kind": kind, "x": x, "y": y, **params})

    def connect(self, board_id, source, target, port=None):
        return self.post(f"/boards/{board_id}/edges", {"source_id": source, "target_id": target, "port": port})

    def graph(self, board_id, light=False):
        return self.get(f"/boards/{board_id}", light=str(light).lower())

    def run(self, board_id, node_ids=None, force=False, downstream=True):
        return self.post(f"/boards/{board_id}/run", {"node_ids": node_ids, "force": force,
                                                     "downstream": downstream})

    def by_id(self, graph, node_id):
        return next(n for n in graph["nodes"] if n["id"] == node_id)

    def by_name(self, graph, name):
        return next(n for n in graph["nodes"] if n["name"] == name)

    def upload_media(self, content, filename="photo.png", mimetype="image/png"):
        r = self.client.post("/api/media", files={"file": (filename, content, mimetype)}, headers=self.headers)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def upload_node(self, board_id, content=None, filename="photo.png", mimetype="image/png", x=0, y=0):
        node = self.node(board_id, "upload", x, y)
        media_id = self.upload_media(content or png(), filename, mimetype)
        return self.post(f"/nodes/{node['id']}/upload", {"media_id": media_id})


def add_member(client, db, owner, email, role="editor"):
    """Sign up another user and make them a member of the owner's workspace."""
    other = signup(client, email=email, name=email.split("@")[0].title(), workspace=email)
    db.add(Membership(user_id=other.user_id, workspace_id=owner.workspace_id, role=role))
    db.flush()
    other.workspace_id = owner.workspace_id
    return other


def account(db, workspace_id, platform, name=None):
    item = SocialAccount(workspace_id=workspace_id, name=name or platform.title(), platform=platform,
                         external_id="x-" + platform, access_token="t", state="connected")
    db.add(item)
    db.flush()
    return item
