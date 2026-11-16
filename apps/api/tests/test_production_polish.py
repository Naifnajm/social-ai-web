"""Production canvas polish: quiet empty text blocks, the run preflight (missing providers, credits), stop."""
import pytest

from app.modules.ai import service as ai_service
from app.modules.ai.models import MediaJob
from app.modules.production.models import Node
from tests.production_fakes import Api, fake_ai, fake_frame, fake_social  # noqa: F401


@pytest.fixture()
def api(client, auth):
    return Api(client, auth)


def test_empty_text_waits_quietly_until_a_run_needs_it(api, fake_ai, db):
    board = api.board()
    text = api.node(board, "text")
    node = api.by_id(api.graph(board), text["id"])
    assert node["state"] == "idle" and not node["error"] and node["notice"] == "Write some text."
    image = api.node(board, "image", 300, 0)
    api.connect(board, text["id"], image["id"])
    graph = api.run(board)
    assert api.by_id(graph, text["id"])["state"] == "failed"
    assert api.by_id(graph, text["id"])["error"] == "Write some text."
    api.patch(f"/nodes/{text['id']}", {"text_value": "A latte"})
    assert api.by_id(api.graph(board), text["id"])["state"] == "done"


def test_run_preflight_lists_missing_providers_and_empty_texts(api, fake_ai, db, monkeypatch):
    board = api.board()
    text = api.node(board, "text")
    image = api.node(board, "image", 300, 0, prompt="A kiosk")
    video = api.node(board, "video", 600, 0, prompt="Move")
    api.connect(board, image["id"], video["id"])
    monkeypatch.setattr(ai_service, "has_provider", lambda db_, ws, cap="text": cap == "image")
    est = api.get(f"/boards/{board}/estimate")
    assert est["missing"] == [{"capability": "video", "node_ids": [video["id"]]}]
    assert est["empty_text"] == [text["id"]] and est["blocks"] == 2
    assert est["credits"] is None  # own keys (the fakes): no credits


def test_platform_ai_estimate_in_credits(api, fake_ai, db, monkeypatch):
    from app.modules.ai import media as ai_media
    monkeypatch.setattr(ai_media, "estimate", lambda *a, **k: {"cost": 0.044, "model": "img", "credits": 4.4})
    board = api.board()
    image = api.node(board, "image", 0, 0, prompt="A kiosk", variations=2)
    node = api.by_id(api.graph(board), image["id"])
    assert node["estimate"] == {"cost": pytest.approx(0.088), "model": "img", "credits": pytest.approx(8.8)}
    est = api.get(f"/boards/{board}/estimate")
    assert est["credits"] == pytest.approx(8.8) and est["credits_available"] is not None


def test_stop_a_run(api, fake_ai, db):
    board = api.board()
    video = api.node(board, "video", 0, 0, prompt="Waves")  # fake video jobs keep running
    after = api.node(board, "captions", 300, 0)
    api.connect(board, video["id"], after["id"])
    graph = api.run(board)
    assert api.by_id(graph, video["id"])["state"] == "running"
    row = db.get(Node, video["id"])
    job = db.get(MediaJob, row.run_job_ids[0])
    graph = api.post(f"/boards/{board}/stop")
    assert {api.by_id(graph, n)["state"] for n in (video["id"], after["id"])} == {"idle"}
    assert api.by_id(graph, video["id"])["notice"] == "Stopped."
    db.refresh(job)
    assert job.state == "failed" and graph["busy"] is False
    from app.modules.production import engine
    job.state = "done"  # the provider still delivers a late result
    engine.on_media_job(db, job)
    assert db.get(Node, video["id"]).state == "idle"  # it does not restart the stopped block
