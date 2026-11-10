"""Production flow tools: variations, reuse of unchanged results, undo-able edits, paste, groups, variables
and batches, brand kits, formats per network, captions, approvals, publishing, Studio links, isolation."""
import io
import os
import subprocess
import tempfile

import pytest
from PIL import Image

from app.core.models import Media, Notification
from app.core.storage import read_media
from app.modules.brand.models import BrandKit
from app.modules.production import media_tools
from app.modules.production.models import Node
from app.modules.social.models import Post, PostMedia
from tests.conftest import signup
from tests.production_fakes import (  # noqa: F401
    HAS_FFMPEG,
    Api,
    account,
    add_member,
    fake_ai,
    fake_frame,
    fake_social,
    png,
    real_media,
)


@pytest.fixture()
def api(client, auth):
    return Api(client, auth)


# ---------------------------------------------------------------------------- variations, history, reuse
def test_variations_history_and_reuse(api, fake_ai):
    board = api.board()
    text = api.node(board, "text", text_value="A cozy cafe")
    image = api.node(board, "image", 300, 0, variations=3)
    api.connect(board, text["id"], image["id"])
    graph = api.run(board)
    assert len(fake_ai.jobs) == 3
    node = api.by_id(graph, image["id"])
    assert node["state"] == "done" and len(node["outputs"]) == 3
    assert {o["run"] for o in node["outputs"]} == {1}
    assert graph["run_all"]["cost"] == 0 and graph["run_all"]["reused"] == 1
    api.run(board)  # nothing changed → nothing is generated again
    assert len(fake_ai.jobs) == 3
    other = node["outputs"][0]  # pick another variation: free, and downstream blocks see it
    picked = api.post(f"/nodes/{image['id']}/select-output", {"output_id": other["id"]})
    assert picked["output"]["id"] == other["media"]["id"]
    api.patch(f"/nodes/{text['id']}", {"text_value": "A cozy cafe at night"})  # changed text → new images
    assert api.graph(board)["run_all"]["cost"] > 0
    graph = api.run(board)
    assert len(fake_ai.jobs) == 6 and len(api.by_id(graph, image["id"])["outputs"]) == 6
    api.run(board, [image["id"]], force=True)  # forced regeneration of one block
    assert len(fake_ai.jobs) == 9


def test_llm_variations(api, fake_ai):
    board = api.board()
    llm = api.node(board, "llm", prompt="Write a slogan", variations=2)
    graph = api.run(board)
    node = api.by_id(graph, llm["id"])
    assert len(node["outputs"]) == 2
    assert "Version 2 of 2" in fake_ai.texts[1]["user"]
    assert node["output_text"] == "Text 1" and node["out_type"] == "text"
    assert fake_ai.texts[0]["purpose"] == "Production: AI writer"


# ---------------------------------------------------------------------------- editing
def test_archive_restore_paste_and_groups(api):
    board = api.board()
    a = api.node(board, "text", text_value="hi")
    b = api.node(board, "llm", 300, 0, prompt="Shorten")
    edge = api.connect(board, a["id"], b["id"])
    removed = api.post(f"/boards/{board}/archive", {"node_ids": [a["id"]]})
    assert removed == {"node_ids": [a["id"]], "edge_ids": [edge["id"]]}
    graph = api.graph(board)
    assert len(graph["nodes"]) == 1 and not graph["edges"]
    graph = api.post(f"/boards/{board}/restore", removed)  # undo
    assert len(graph["nodes"]) == 2 and len(graph["edges"]) == 1
    # single-input ports keep the newest link; the replaced one can be restored (undo)
    video = api.node(board, "video", 600, 0)
    up1 = api.upload_node(board, y=300)
    up2 = api.post(f"/boards/{board}/paste", {"node_ids": [up1["id"]], "dx": 0, "dy": 200})["nodes"][0]
    assert up2["output"]["id"] == up1["output"]["id"] and up2["state"] == "done"
    first = api.connect(board, up1["id"], video["id"], "first_frame")
    second = api.connect(board, up2["id"], video["id"], "first_frame")
    assert second["replaced"] == [first["id"]]
    # paste copies inner links too
    pasted = api.post(f"/boards/{board}/paste", {"node_ids": [a["id"], b["id"]]})
    assert len(pasted["nodes"]) == 2 and len(pasted["edges"]) == 1
    assert pasted["nodes"][0]["x"] == a["x"] + 40
    # cross-board paste
    other = api.board()
    assert len(api.post(f"/boards/{other}/paste", {"node_ids": [a["id"]]})["nodes"]) == 1
    group = api.post(f"/boards/{board}/groups", {"node_ids": [a["id"], b["id"]], "name": "Script"})
    assert sorted(group["nodes"]) == sorted([a["id"], b["id"]])
    assert api.graph(board)["groups"][0]["name"] == "Script"
    renamed = api.patch(f"/groups/{group['id']}", {"name": "Voice script"})
    assert renamed["name"] == "Voice script"
    assert sorted(api.raw("DELETE", f"/groups/{group['id']}").json()) == sorted([a["id"], b["id"]])
    assert api.by_id(api.graph(board), a["id"])["group_id"] is None
    # positions and node edits
    api.post(f"/boards/{board}/positions", {"positions": {str(a["id"]): [10, 20]}})
    moved = api.by_id(api.graph(board), a["id"])
    assert (moved["x"], moved["y"]) == (10, 20)
    edited = api.patch(f"/nodes/{b['id']}", {"name": "Shorter", "variations": 4, "formats": ["4:5", "4:5", "1:1"]})
    assert edited["name"] == "Shorter" and edited["formats"] == ["4:5", "1:1"] and edited["variations"] == 4
    assert api.raw("PATCH", f"/nodes/{b['id']}", {"variations": 9}).status_code == 422


def test_board_crud_duplicate_and_view(api, client, auth):
    board = api.board("talking_slide", name="Weekend tips")
    graph = api.patch(f"/boards/{board}", {"name": "Weekend tips v2"})
    assert graph["board"]["name"] == "Weekend tips v2"
    assert client.put(f"/api/production/boards/{board}/view", json={"zoom": 0.6, "pan_x": 10, "pan_y": -5},
                      headers=auth.headers).status_code == 204
    assert api.graph(board)["board"]["zoom"] == 0.6
    copy = api.post(f"/boards/{board}/duplicate")
    assert copy["name"] == "Weekend tips v2 (copy)" and copy["node_count"] == 6
    copy_graph = api.graph(copy["id"])
    assert len(copy_graph["edges"]) == 7
    assert api.raw("DELETE", f"/boards/{board}").status_code == 204
    assert api.raw("GET", f"/boards/{board}").status_code == 404
    assert [b["id"] for b in api.get("/boards")] == [copy["id"]]


# ---------------------------------------------------------------------------- variables & batches
def test_variables_and_batch(api, fake_ai):
    board = api.board()
    text = api.node(board, "text", text_value="Launch of {{product}} — {{offer}} off")
    llm = api.node(board, "llm", 300, 0, prompt="Write an ad for {{product}}")
    api.connect(board, text["id"], llm["id"])
    graph = api.put(f"/boards/{board}/variables", {"variables": [{"key": "product", "value": "Kiosk"},
                                                                 {"key": "offer", "value": "20%"}]})
    assert api.by_id(graph, text["id"])["output_text"] == "Launch of Kiosk — 20% off"
    assert sorted(graph["board"]["used_variables"]) == ["offer", "product"]
    api.run(board)
    assert "Write an ad for Kiosk" in fake_ai.texts[0]["user"]
    boards = api.post(f"/boards/{board}/batch", {"rows": [{"product": "POS"}, {"product": "Tablet"}]})
    assert len(boards) == 2 and "Tablet" in boards[1]["name"]
    copy = api.graph(boards[1]["id"])
    copy_text = next(n for n in copy["nodes"] if n["kind"] == "text")
    assert copy_text["output_text"] == "Launch of Tablet — 20% off"
    assert next(n for n in copy["nodes"] if n["kind"] == "llm")["state"] == "done"  # each copy is run
    assert any("Write an ad for Tablet" in t["user"] for t in fake_ai.texts)
    assert api.raw("POST", f"/boards/{board}/batch", {"rows": []}).status_code == 400
    too_many = [{"product": str(i)} for i in range(21)]
    assert api.raw("POST", f"/boards/{board}/batch", {"rows": too_many}).status_code == 400


# ---------------------------------------------------------------------------- brand kit
def test_brand_kit_applies_everywhere(api, fake_ai, db, auth):
    kit = BrandKit(workspace_id=auth.workspace_id, name="Stravica", tone="Warm and short", guidelines="No emojis",
                   visual_style="Soft daylight", color_primary="#111111", voice="nova")
    db.add(kit)
    db.flush()
    board = api.board()
    graph = api.patch(f"/boards/{board}", {"brand_kit_id": kit.id})
    assert graph["brand"]["name"] == "Stravica" and graph["brand_kits"] == [{"id": kit.id, "name": "Stravica"}]
    llm = api.node(board, "llm", prompt="Slogan")
    image = api.node(board, "image", 300, 0, prompt="A kiosk")
    voice = api.node(board, "audio", 300, 300, prompt="Hello there")
    graph = api.run(board)
    system = fake_ai.texts[0]["system"]
    assert "Warm and short" in system and "No emojis" in system
    image_job = next(j for j in fake_ai.jobs if j["kind"] == "image")
    assert "Soft daylight" in image_job["prompt"] and "#111111" in image_job["prompt"]
    assert next(j for j in fake_ai.jobs if j["kind"] == "audio")["voice"] == "nova"
    assert all(api.by_id(graph, n["id"])["state"] == "done" for n in (llm, image, voice))
    # changing the kit invalidates the results
    assert api.graph(board)["run_all"]["reused"] == 3
    kit.tone = "Formal"
    db.flush()
    assert api.graph(board)["run_all"]["reused"] == 0
    assert api.raw("PATCH", f"/boards/{board}", {"brand_kit_id": 999999}).status_code == 404


# ---------------------------------------------------------------------------- formats & publishing
def test_formats_per_network_and_post_modes(api, fake_social, db, auth):
    ig, tt = account(db, auth.workspace_id, "instagram"), account(db, auth.workspace_id, "tiktok")
    board = api.board()
    upload = api.upload_node(board, png((400, 300)))
    reframe = api.node(board, "reframe", 300, 0, formats=["9:16", "4:5", "1:1"], fit_mode="blur")
    caption = api.node(board, "text", 0, 300, text_value="New menu!")
    post = api.node(board, "post", 600, 0, account_ids=[ig.id, tt.id])
    api.connect(board, upload["id"], reframe["id"])
    edge = api.connect(board, reframe["id"], post["id"])
    assert edge["type"] == "image"
    api.connect(board, caption["id"], post["id"])
    graph = api.run(board)
    node = api.by_id(graph, reframe["id"])
    assert node["state"] == "done", node["error"]
    sizes = {o["aspect"]: Image.open(io.BytesIO(read_media(db.get(Media, o["media"]["id"])))).size
             for o in node["outputs"]}
    assert sizes == {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080)}
    by_aspect = {o["aspect"]: o["media"]["id"] for o in node["outputs"]}
    created = db.get(Post, api.by_id(graph, post["id"])["post_id"])
    assert created.content == "New menu!" and {a.id for a in created.accounts} == {ig.id, tt.id}
    assert created.platform_media == {"instagram": [by_aspect["4:5"]], "tiktok": [by_aspect["9:16"]]}
    assert graph["board"]["post"]["id"] == created.id
    # best time: the same draft is scheduled on the next good slot
    api.patch(f"/nodes/{post['id']}", {"publish_mode": "best"})
    graph = api.run(board, [post["id"]], force=True)
    assert fake_social.submitted[-1] == (created.id, "best_time")
    assert created.state == "scheduled" and created.scheduled_at
    assert api.by_id(graph, post["id"])["notice"].startswith("Scheduled for")
    # a date is required for "at a date"
    api.patch(f"/nodes/{post['id']}", {"publish_mode": "at"})
    graph = api.run(board, [post["id"]], force=True)
    assert "publishing date" in api.by_id(graph, post["id"])["error"]


def test_publish_now_needs_accounts(api, fake_social, db, auth):
    board = api.board()
    text = api.node(board, "text", text_value="Hi")
    post = api.node(board, "post", 300, 0, publish_mode="now")
    api.connect(board, text["id"], post["id"])
    graph = api.run(board)
    assert api.by_id(graph, post["id"])["state"] == "failed"
    tg = account(db, auth.workspace_id, "telegram")
    api.patch(f"/nodes/{post['id']}", {"account_ids": [tg.id]})
    graph = api.run(board, [post["id"]], force=True)
    node = api.by_id(graph, post["id"])
    assert node["post_state"] == "posted" and node["notice"] == "Published: Published"


# ---------------------------------------------------------------------------- local media tools
def test_srt_and_reframe_sizes():
    srt = media_tools.to_srt([{"start": 0, "end": 1.5, "text": "مرحبا بكم"}, {"start": 1.5, "end": 3.25,
                                                                              "text": "Hello"}])
    assert srt == "1\n00:00:00,000 --> 00:00:01,500\nمرحبا بكم\n\n2\n00:00:01,500 --> 00:00:03,250\nHello\n"
    for aspect, size in media_tools.SIZES.items():
        for mode in ("blur", "crop"):
            assert Image.open(io.BytesIO(media_tools.reframe_image(png((640, 480)), aspect, mode))).size == size
    assert media_tools.aspect_of(1080, 1350) == "4:5" and media_tools.aspect_of(None, 3) is None


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg is not installed")
def test_merge_and_reframe_video_with_ffmpeg(api, fake_ai, db):
    mp4, mp3 = real_media()
    board = api.board()
    video = api.upload_node(board, mp4, "clip.mp4", "video/mp4")
    voice = api.upload_node(board, mp3, "voice.mp3", "audio/mpeg", y=200)
    music = api.upload_node(board, mp3, "music.mp3", "audio/mpeg", y=400)
    merge = api.node(board, "merge", 300, 0, aspect="9:16")
    reframe = api.node(board, "reframe", 600, 0, formats=["9:16"], fit_mode="crop")
    for source in (video, voice, music):
        api.connect(board, source["id"], merge["id"])
    api.connect(board, merge["id"], reframe["id"])
    graph = api.run(board)
    merged = api.by_id(graph, merge["id"])
    assert merged["state"] == "done", merged["error"]
    out = api.by_id(graph, reframe["id"])
    assert out["state"] == "done", out["error"]
    assert out["output"]["mimetype"] == "video/mp4" and out["out_type"] == "video"
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", "-"],
                           input=read_media(db.get(Media, out["output"]["id"])), capture_output=True)
    assert probe.stdout.decode().strip() == "720,1280"


@pytest.mark.skipif(not media_tools.subtitles_available(), reason="ffmpeg with libass is not installed")
def test_captions_block(api, fake_ai, db):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "v.mp4")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=2", "-f", "lavfi",
                        "-i", "sine=frequency=300:duration=2", "-shortest", "-c:v", "libx264", "-pix_fmt",
                        "yuv420p", "-c:a", "aac", path], check=True, capture_output=True)
        with open(path, "rb") as fh:
            mp4 = fh.read()
    board = api.board()
    upload = api.upload_node(board, mp4, "v.mp4", "video/mp4")
    captions = api.node(board, "captions", 300, 0, caption_language="ar", caption_position="top")
    api.connect(board, upload["id"], captions["id"])
    graph = api.run(board)
    node = api.by_id(graph, captions["id"])
    assert node["state"] == "done", node["error"]
    assert "أهلاً وسهلاً" in node["output_text"]
    assert node["output"]["mimetype"] == "video/mp4" and node["cost"] > 0
    assert fake_ai.transcribed[0]["language"] == "ar"
    assert fake_ai.transcribed[0]["media_id"] == upload["output"]["id"]  # the video's own soundtrack
    fake_ai.segments = []
    graph = api.run(board, [captions["id"]], force=True)
    assert "No speech" in api.by_id(graph, captions["id"])["error"]


# ---------------------------------------------------------------------------- approval
def test_approval_gates_publishing(api, client, db, auth, fake_social):
    reviewer = add_member(client, db, auth, "reviewer@example.com", "editor")
    outsider = add_member(client, db, auth, "outsider@example.com", "editor")
    board = api.board()
    text = api.node(board, "text", text_value="Big news")
    approval = api.node(board, "approval", 300, 0, approver_id=reviewer.user_id)
    post = api.node(board, "post", 600, 0)
    api.connect(board, text["id"], approval["id"])
    edge = api.connect(board, approval["id"], post["id"])
    assert edge["port"] == "caption" and edge["type"] == "text"
    graph = api.run(board)
    assert api.by_id(graph, approval["id"])["state"] == "waiting"
    waiting = api.by_id(graph, post["id"])
    assert waiting["state"] == "idle" and waiting["post_id"] is None and "approval" in waiting["notice"]
    assert not graph["busy"]
    note = db.query(Notification).filter_by(user_id=reviewer.user_id, kind="production.approval").one()
    assert note.link.startswith(f"/production/{board}")
    as_outsider = Api(client, outsider)
    r = as_outsider.raw("POST", f"/nodes/{approval['id']}/approve", {})
    assert r.status_code == 403
    as_reviewer = Api(client, reviewer)
    assert as_reviewer.by_id(as_reviewer.graph(board), approval["id"])["can_approve"]
    graph = as_reviewer.post(f"/nodes/{approval['id']}/approve", {"comment": "Looks good"})
    assert api.by_id(graph, approval["id"])["state"] == "done"
    done = api.by_id(graph, post["id"])
    assert done["state"] == "done"
    assert db.get(Post, done["post_id"]).content == "Big news"  # content passes through the approval
    # a change needs a new approval
    api.patch(f"/nodes/{text['id']}", {"text_value": "Bigger news"})
    graph = api.run(board)
    assert api.by_id(graph, approval["id"])["state"] == "waiting"
    graph = api.post(f"/nodes/{approval['id']}/reject", {"comment": "Too loud"})  # the owner (admin) may decide
    rejected = api.by_id(graph, approval["id"])
    assert rejected["state"] == "failed" and "Too loud" in rejected["error"]
    r = api.raw("PATCH", f"/nodes/{approval['id']}", {"approver_id": signup(client, email="z@x.io").user_id})
    assert r.status_code == 404  # the approver must be a member


# ---------------------------------------------------------------------------- links with the Studio
def test_studio_and_production_links(api, db, auth, fake_social):
    ig = account(db, auth.workspace_id, "instagram")
    media_id = api.upload_media(png())
    post = Post(workspace_id=auth.workspace_id, content="Hello", state="draft")
    post.accounts = [ig]
    post.media_links = [PostMedia(media_id=media_id, position=0)]
    db.add(post)
    db.flush()
    card = api.post("/boards/from-post", {"post_id": post.id})
    graph = api.graph(card["id"])
    assert graph["board"]["post"]["id"] == post.id
    assert sorted(n["kind"] for n in graph["nodes"]) == ["post", "text", "upload"]
    post_node = next(n for n in graph["nodes"] if n["kind"] == "post")
    assert post_node["account_ids"] == [ig.id]
    text = next(n for n in graph["nodes"] if n["kind"] == "text")
    api.patch(f"/nodes/{text['id']}", {"text_value": "Hello again"})  # edit the text → the same post is updated
    graph = api.run(card["id"])
    assert post.content == "Hello again"
    assert api.by_id(graph, post_node["id"])["post_id"] == post.id
    assert [m.media_id for m in post.media_links] == [media_id]
    upload = next(n for n in graph["nodes"] if n["kind"] == "upload")
    new_post = db.get(Post, api.post(f"/nodes/{upload['id']}/send-to-studio")["post_id"])
    assert [m.media_id for m in new_post.media_links] == [media_id] and new_post.state == "draft"
    assert api.post(f"/nodes/{post_node['id']}/send-to-studio")["post_id"] == post.id
    empty = api.node(card["id"], "image", 0, 900)
    assert api.raw("POST", f"/nodes/{empty['id']}/send-to-studio").status_code == 400
    from_media = api.post("/boards/from-media", {"media_id": media_id, "text": "Draft"})
    kinds = [n["kind"] for n in api.graph(from_media["id"])["nodes"]]
    assert kinds == ["upload", "text"]


# ---------------------------------------------------------------------------- multi-tenant isolation
def test_other_workspace_cannot_read_or_change(api, client, db, auth, fake_ai):
    board = api.board("quote_card")
    graph = api.graph(board)
    node = graph["nodes"][0]
    secret_media = api.upload_media(png())
    intruder = Api(client, signup(client, email="intruder@example.com", workspace="Other"))
    own = intruder.board()
    assert [b["id"] for b in intruder.get("/boards")] == [own]
    for method, path, body in [
        ("GET", f"/boards/{board}", None), ("PATCH", f"/boards/{board}", {"name": "x"}),
        ("DELETE", f"/boards/{board}", None), ("POST", f"/boards/{board}/run", {}),
        ("POST", f"/boards/{board}/duplicate", None), ("POST", f"/boards/{board}/nodes", {"kind": "text"}),
        ("PATCH", f"/nodes/{node['id']}", {"name": "x"}), ("POST", f"/boards/{board}/archive", {"node_ids": [1]}),
        ("PUT", f"/boards/{board}/variables", {"variables": []}), ("GET", f"/boards/{board}/estimate", None),
        ("POST", f"/nodes/{node['id']}/approve", {}), ("POST", f"/nodes/{node['id']}/send-to-studio", None),
    ]:
        assert intruder.raw(method, path, body).status_code == 404, (method, path)
    # ids of another workspace are refused inside the intruder's own board
    upload = intruder.node(own, "upload")
    assert intruder.raw("POST", f"/nodes/{upload['id']}/upload", {"media_id": secret_media}).status_code == 404
    assert intruder.raw("POST", f"/boards/{own}/paste", {"node_ids": [node["id"]]}).status_code == 404
    assert intruder.raw("POST", f"/boards/{own}/edges", {"source_id": node["id"],
                                                         "target_id": upload["id"]}).status_code == 400
    assert intruder.raw("POST", "/boards/from-media", {"media_id": secret_media}).status_code == 404
    other_account = account(db, auth.workspace_id, "instagram")
    post = intruder.node(own, "post")
    assert intruder.raw("PATCH", f"/nodes/{post['id']}", {"account_ids": [other_account.id]}).status_code == 404
    # the owner's board is untouched
    assert db.get(Node, node["id"]).name == node["name"]


def test_viewer_cannot_edit(api, client, db, auth):
    board = api.board()
    viewer = Api(client, add_member(client, db, auth, "viewer@example.com", "viewer"))
    assert viewer.graph(board)["board"]["id"] == board
    assert viewer.raw("POST", f"/boards/{board}/nodes", {"kind": "text"}).status_code == 403
    assert viewer.raw("POST", f"/boards/{board}/run", {}).status_code == 403


def test_every_server_message_is_translated_to_arabic():
    import json
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "app" / "modules" / "production"
    arabic = json.loads((root / "i18n" / "ar.json").read_text(encoding="utf-8"))
    pattern = re.compile(r'''(?:\b_|lazy)\(\s*"((?:[^"\\]|\\.)*)"''')
    messages = {m for path in root.glob("*.py") for m in pattern.findall(path.read_text(encoding="utf-8"))}
    assert not sorted(messages - set(arabic))
