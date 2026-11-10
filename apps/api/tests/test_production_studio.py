"""Production boards: templates, link rules, the engine (image / video / voice / merge / design / post),
running videos finished by the media-job callback, versions, estimates and the periodic task."""
import base64
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.production import engine, tasks
from app.modules.production.models import Edge, Node
from tests.production_fakes import (  # noqa: F401
    HAS_FFMPEG,
    Api,
    fake_ai,
    fake_frame,
    fake_social,
    png,
)


@pytest.fixture()
def api(client, auth):
    return Api(client, auth)


def test_templates_create_wired_boards(api):
    templates = api.get("/templates")
    assert {"blank", "product_ad", "quote_card", "talking_slide", "music_reel"} <= {t["key"] for t in templates}
    board_id = api.board("product_ad")
    graph = api.graph(board_id)
    assert len(graph["nodes"]) == 8
    assert len(graph["edges"]) == 9
    names = {n["id"]: n for n in graph["nodes"]}
    ports = {(names[e["target"]]["kind"], e["port"]) for e in graph["edges"]}
    assert ("merge", "tracks") in ports
    assert ("video", "first_frame") in ports
    text = next(n for n in graph["nodes"] if n["kind"] == "text")
    assert (text["state"], text["output_text"]) == ("done", text["text_value"])
    kinds = {k["key"]: k for k in graph["kinds"]}
    assert {"image", "video", "audio", "merge", "design", "template", "approval", "post"} <= set(kinds)
    assert kinds["merge"]["ports"][1] == {"key": "tracks", "label": "Audio tracks", "accepts": ["audio"],
                                          "multi": True}
    hub = api.get("/boards")
    assert hub[0]["id"] == board_id and hub[0]["node_count"] == 8


def test_link_rules(api):
    board = api.board()
    text = api.node(board, "text", text_value="hello")
    image = api.node(board, "image", 300, 0)
    audio = api.node(board, "audio", 300, 300)
    post = api.node(board, "post", 600, 0)
    edge = api.connect(board, text["id"], image["id"])
    assert edge["port"] == "prompt" and edge["type"] == "text"
    bad = [(image, audio), (post, image), (text, text)]  # a voice block takes no image, a post has no output
    for source, target in bad:
        r = api.raw("POST", f"/boards/{board}/edges", {"source_id": source["id"], "target_id": target["id"]})
        assert r.status_code == 400, r.text
    llm = api.node(board, "llm", 0, 300)
    api.connect(board, text["id"], llm["id"])
    r = api.raw("POST", f"/boards/{board}/edges", {"source_id": llm["id"], "target_id": text["id"]})
    assert r.status_code == 400  # a text block takes no input
    llm2 = api.node(board, "llm", 0, 500)
    api.connect(board, llm["id"], llm2["id"])
    r = api.raw("POST", f"/boards/{board}/edges", {"source_id": llm2["id"], "target_id": llm["id"]})
    assert r.status_code == 400 and r.json()["code"] == "loop"
    # the same link twice is not duplicated; a wrong port name is refused
    assert api.connect(board, text["id"], image["id"])["id"] == edge["id"]
    r = api.raw("POST", f"/boards/{board}/edges", {"source_id": text["id"], "target_id": image["id"],
                                                   "port": "images"})
    assert r.status_code == 400


def test_image_from_upload_and_text(api, fake_ai):
    board = api.board()
    upload = api.upload_node(board)
    assert upload["state"] == "done" and upload["out_type"] == "image"
    text = api.node(board, "text", 0, 300, text_value="Make it look like a sunny terrace")
    image = api.node(board, "image", 300, 0, aspect="4:5", style="photo")
    api.connect(board, upload["id"], image["id"])
    api.connect(board, text["id"], image["id"])
    graph = api.run(board, [image["id"]])
    job = fake_ai.jobs[0]
    assert job["kind"] == "image" and "sunny terrace" in job["prompt"]
    assert job["inputs"] == [upload["output"]["id"]] and job["aspect"] == "4:5" and job["style"] == "photo"
    assert job["callback"] == "app.modules.production.engine.on_media_job"
    node = api.by_id(graph, image["id"])
    assert node["state"] == "done" and node["output"]["mimetype"] == "image/png"
    assert graph["board"]["cover_url"] == node["output"]["url"]
    assert not graph["busy"]


def test_video_waits_for_its_job_then_board_continues(api, fake_ai, fake_social, db):
    board = api.board()
    upload = api.upload_node(board)
    video = api.node(board, "video", 300, 0, seconds=5)
    caption = api.node(board, "text", 0, 300, text_value="Our new kiosk")
    post = api.node(board, "post", 600, 0)
    api.connect(board, upload["id"], video["id"])
    api.connect(board, video["id"], post["id"])
    api.connect(board, caption["id"], post["id"])
    graph = api.run(board)
    assert graph["busy"]
    assert api.by_id(graph, video["id"])["state"] == "running"
    assert api.by_id(graph, post["id"])["state"] == "queued"
    assert fake_ai.jobs[0]["prompt"].startswith("Bring this image to life")  # no prompt: animate the image
    assert fake_ai.jobs[0]["inputs"] == [upload["output"]["id"]]
    light = api.graph(board, light=True)
    assert light["busy"] and light["kinds"] == [] and light["run_all"]["cost"] == 0
    fake_ai.finish_videos(db)  # the AI poller finishes the video and calls the callback
    graph = api.graph(board)
    assert not graph["busy"]
    assert api.by_id(graph, video["id"])["state"] == "done"
    final = api.by_id(graph, post["id"])
    assert final["state"] == "done", final["error"]
    created = db.get(engine.Post, final["post_id"])
    assert created.content == "Our new kiosk"
    assert [m.media_id for m in created.media_links] == [api.by_id(graph, video["id"])["output"]["id"]]
    assert created.source_ref == f"board:{board}"
    assert graph["board"]["post"]["id"] == created.id


def test_failed_video_fails_downstream(api, fake_ai, db):
    board = api.board()
    video = api.node(board, "video", 0, 0, prompt="Waves")
    merge = api.node(board, "merge", 300, 0)
    audio = api.node(board, "audio", 0, 300, prompt="Hello")
    api.connect(board, video["id"], merge["id"])
    api.connect(board, audio["id"], merge["id"])
    api.run(board)
    fake_ai.finish_videos(db, fail=True)
    graph = api.graph(board)
    assert api.by_id(graph, video["id"])["error"] == "Video provider error"
    assert api.by_id(graph, merge["id"])["state"] == "failed"
    assert api.by_id(graph, merge["id"])["error"] == "An input block failed."


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg is not installed")
def test_product_ad_end_to_end(api, fake_ai, fake_social, db):
    board = api.board("product_ad")
    fake_ai.text_reply = lambda n, user: "Order faster. Wait less. Stravica."
    api.run(board)
    fake_ai.finish_videos(db)
    graph = api.graph(board)
    states = {n["name"]: (n["state"], n["error"]) for n in graph["nodes"]}
    assert all(state == "done" for state, _e in states.values()), states
    kinds = [j["kind"] for j in fake_ai.jobs]
    assert sorted(kinds) == ["audio", "audio", "image", "video"]
    speech = next(j for j in fake_ai.jobs if j["kind"] == "audio" and j["audio_mode"] == "speech")
    assert speech["prompt"] == "Order faster. Wait less. Stravica."  # the script is spoken as is
    final = api.by_name(graph, "Final video")
    tracks = [e for e in graph["edges"] if e["target"] == final["id"] and e["port"] == "tracks"]
    assert len(tracks) == 2  # voice-over + music mixed together
    assert final["output"]["mimetype"] == "video/mp4"
    post = db.get(engine.Post, api.by_name(graph, "Post")["post_id"])
    assert post.content == "Order faster. Wait less. Stravica."
    assert [m.media_id for m in post.media_links] == [final["output"]["id"]]
    from app.core.storage import read_media
    assert len(read_media(db.get(engine.Media, final["output"]["id"]))) > 1000


def test_failures_propagate_and_design_needs_editor(api, fake_ai, fake_social, db):
    board = api.board("quote_card")
    api.run(board)
    graph = api.graph(board)
    design = api.by_name(graph, "Card design")
    post = api.by_name(graph, "Post")
    assert design["state"] == "failed" and "design editor" in design["error"]
    assert post["state"] == "failed"
    layers = {"aspect": "4:5", "layers": [{"type": "text", "text": "مرحبا"}]}
    bad = api.raw("POST", f"/nodes/{design['id']}/design", {"png": "bm90IGEgcG5n", "layers": layers})
    assert bad.status_code == 400
    saved = api.post(f"/nodes/{design['id']}/design",
                     {"png": "data:image/png;base64," + base64.b64encode(png(color=(255, 0, 0))).decode(),
                      "layers": layers})
    assert saved["state"] == "done" and saved["design"]["layers"][0]["text"] == "مرحبا"
    graph = api.run(board, [post["id"]])
    post = api.by_id(graph, post["id"])
    assert post["state"] == "done", post["error"]
    created = db.get(engine.Post, post["post_id"])
    assert [m.media_id for m in created.media_links] == [saved["output"]["id"]]
    assert created.content == "Text 1"


def test_sound_effects_music_and_failures(api, fake_ai):
    board = api.board()
    sfx = api.node(board, "audio", 0, 0, audio_mode="sfx", prompt="Coffee machine hiss", seconds=5)
    music = api.node(board, "audio", 0, 300, audio_mode="music", prompt="Calm piano", seconds=30)
    api.run(board)
    assert [(j["audio_mode"], j["seconds"]) for j in fake_ai.jobs] == [("sfx", 5), ("music", 30)]
    graph = api.graph(board)
    assert {api.by_id(graph, sfx["id"])["state"], api.by_id(graph, music["id"])["state"]} == {"done"}
    fake_ai.fail_kinds = {"audio"}
    graph = api.run(board, [music["id"]], force=True)
    failed = api.by_id(graph, music["id"])
    assert failed["state"] == "failed" and "refused" in failed["error"]
    # no prompt and nothing linked: a clear message, no call
    empty = api.node(board, "image", 600, 0)
    graph = api.run(board, [empty["id"]])
    assert "Write a prompt" in api.by_id(graph, empty["id"])["error"]


def test_versions_reuse_force_and_select(api, fake_ai, db):
    board = api.board()
    upload = api.upload_node(board)
    video = api.node(board, "video", 300, 0)
    api.connect(board, upload["id"], video["id"])
    api.run(board, [video["id"]])
    fake_ai.finish_videos(db)
    first = api.by_id(api.graph(board), video["id"])
    graph = api.run(board, [video["id"]])  # nothing changed: the result is reused for free
    again = api.by_id(graph, video["id"])
    assert len(fake_ai.jobs) == 1 and len(again["outputs"]) == 1
    assert "reused" in again["notice"] and again["fresh"]
    api.run(board, [video["id"]], force=True)  # "Regenerate"
    fake_ai.finish_videos(db)
    node = api.by_id(api.graph(board), video["id"])
    assert len(fake_ai.jobs) == 2 and len(node["outputs"]) == 2
    assert node["output"]["id"] != first["output"]["id"]
    oldest = node["outputs"][-1]
    selected = api.post(f"/nodes/{video['id']}/select-output", {"output_id": oldest["id"]})
    assert selected["output"]["id"] == first["output"]["id"]
    assert [o["selected"] for o in selected["outputs"]] == [False, True]
    other = api.node(board, "video", 0, 600)
    r = api.raw("POST", f"/nodes/{other['id']}/select-output", {"output_id": oldest["id"]})
    assert r.status_code == 404


def test_estimates_per_block_and_run(api, fake_ai):
    board = api.board()
    text = api.node(board, "text", text_value="A cozy cafe")
    image = api.node(board, "image", 300, 0, variations=3)
    llm = api.node(board, "llm", 300, 300, prompt="Slogan")
    api.connect(board, text["id"], image["id"])
    graph = api.graph(board)
    assert api.by_id(graph, image["id"])["estimate"] == {"cost": pytest.approx(0.12), "model": "fake-image"}
    assert api.by_id(graph, llm["id"])["estimate"]["cost"] == pytest.approx(0.001)
    assert api.by_id(graph, text["id"])["estimate"] is None
    assert graph["run_all"] == {"cost": pytest.approx(0.121), "reused": 0, "blocks": 2}
    api.run(board)
    estimate = api.get(f"/boards/{board}/estimate")
    assert estimate == {"cost": 0, "reused": 2, "blocks": 0}
    forced = api.get(f"/boards/{board}/estimate", node_ids=[image["id"]], force="true")
    assert forced["cost"] == pytest.approx(0.12) and forced["blocks"] == 1
    node = api.by_id(api.graph(board), image["id"])
    assert node["cost"] == pytest.approx(0.12) and len(node["outputs"]) == 3


def test_template_block(api, fake_ai, fake_frame):
    board = api.board()
    upload = api.upload_node(board)
    text = api.node(board, "text", 0, 300, text_value="{{price}} SAR")
    api.put(f"/boards/{board}/variables", {"variables": [{"key": "price", "value": "99"}]})
    template = api.node(board, "template", 300, 0)
    api.connect(board, upload["id"], template["id"])
    api.connect(board, text["id"], template["id"])
    graph = api.run(board)
    assert "Choose a brand template" in api.by_id(graph, template["id"])["error"]
    assert graph["brand_templates"][0] == {"value": "template:7", "label": "Sale 4:5"}
    api.patch(f"/nodes/{template['id']}", {"template_ref": "set:3"})
    graph = api.run(board)
    node = api.by_id(graph, template["id"])
    assert node["state"] == "done", node["error"]
    assert sorted(o["aspect"] for o in node["outputs"]) == ["4:5", "9:16"]
    assert fake_frame.calls[0] == ("set", "set:3", upload["output"]["id"], "99 SAR", False)
    api.patch(f"/nodes/{template['id']}", {"template_ref": "template:7"})
    graph = api.run(board)
    assert fake_frame.calls[-1][0:2] == ("compose", 7)
    assert api.by_id(graph, template["id"])["outputs"][0]["aspect"] == "4:5"


def test_periodic_task_advances_boards_and_purges(api, fake_ai, db):
    board = api.board()
    llm = api.node(board, "llm", 0, 0, prompt="Say hi")
    node = db.get(Node, llm["id"])
    node.state = "queued"  # e.g. a worker crashed after queuing
    other = api.node(board, "text", 0, 300, text_value="old")
    removed = api.post(f"/boards/{board}/archive", {"node_ids": [other["id"]]})
    db.get(Node, other["id"]).archived_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.flush()
    tasks.step_boards()
    db.expire_all()
    assert (node.state, node.output_text) == ("done", "Text 1")
    assert db.get(Node, removed["node_ids"][0]) is None
    assert db.query(Edge).filter(Edge.board_id == board).count() == 0
