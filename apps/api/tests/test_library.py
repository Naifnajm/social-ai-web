"""Media library: search & filters, tags, favourites, usage, safe delete, "use in Studio", isolation."""
import pytest

from app.core.models import Media
from app.modules.workspaces.models import Membership
from tests.conftest import signup
from tests.planning_fakes import install_fake_social, make_media, make_post, png


@pytest.fixture()
def files(db, auth):
    used = make_media(db, auth.workspace_id, "used.png", user_id=auth.user_id)
    ai_cat = make_media(db, auth.workspace_id, "ai-cat.png", source="ai")
    clip = make_media(db, auth.workspace_id, "clip.mp3", content=b"ID3fake", mimetype="audio/mpeg",
                      user_id=auth.user_id)
    video = make_media(db, auth.workspace_id, "reel.mp4", content=b"\x00\x00video", mimetype="video/mp4",
                       source="production")
    other_kind = make_media(db, auth.workspace_id, "doc.pdf", content=b"%PDF", mimetype="application/pdf")
    make_post(db, auth.workspace_id, media=[used])
    make_post(db, auth.workspace_id, platform_media={"instagram": [ai_cat.id]})
    return {"used": used, "ai": ai_cat, "clip": clip, "video": video, "pdf": other_kind}


def ids(page):
    return [item["id"] for item in page["items"]]


def test_search_filters_and_usage(client, auth, files):
    page = client.get("/api/library/media", headers=auth.headers).json()
    names = {i["filename"]: i for i in page["items"]}
    assert set(names) == {"used.png", "ai-cat.png", "clip.mp3", "reel.mp4"}, "only images, videos and audio"
    assert page["total"] == 4
    assert page["counts"] == {"image": 2, "video": 1, "audio": 1}
    assert names["used.png"]["used"] == 1
    assert names["ai-cat.png"]["used"] == 1, "per-network media count too"
    assert names["clip.mp3"]["used"] == 0
    assert names["ai-cat.png"]["source"] == "ai" and names["used.png"]["author"] == "Owner"
    assert names["used.png"]["thumb_url"] == f"/api/media/{files['used'].id}/file"
    assert names["clip.mp3"]["thumb_url"] == ""

    h = auth.headers
    assert ids(client.get("/api/library/media?kind=audio", headers=h).json()) == [files["clip"].id]
    assert ids(client.get("/api/library/media?source=ai", headers=h).json()) == [files["ai"].id]
    assert ids(client.get("/api/library/media?q=CAT", headers=h).json()) == [files["ai"].id]
    assert set(ids(client.get("/api/library/media?unused=true", headers=h).json())) == \
        {files["clip"].id, files["video"].id, files["ai"].id}
    assert ids(client.get("/api/library/media?sort=name&limit=2", headers=h).json()) == \
        [files["ai"].id, files["clip"].id]
    usage = client.get(f"/api/library/media/{files['ai'].id}/usage", headers=h).json()
    assert usage["total"] == 1 and usage["posts"][0]["state"] == "draft"


def test_tags_favourites_and_bulk(client, auth, files):
    h = auth.headers
    cat = files["ai"].id
    r = client.patch(f"/api/library/media/{cat}", json={"tags": ["Cats", "cats ", " Summer  sale", ""]}, headers=h)
    assert r.json()["tags"] == ["Cats", "Summer sale"]
    assert ids(client.get("/api/library/media?tag=Cats", headers=h).json()) == [cat]
    assert client.post(f"/api/library/media/{cat}/favorite", headers=h).json()["favorite"] is True
    assert ids(client.get("/api/library/media?favorite=true", headers=h).json()) == [cat]
    assert client.post(f"/api/library/media/{cat}/favorite", headers=h).json()["favorite"] is False

    r = client.post("/api/library/media/bulk", json={"ids": [files["clip"].id, cat], "action": "add_tag",
                                                     "tag": "Cats"}, headers=h)
    assert sorted(r.json()["done"]) == sorted([files["clip"].id, cat])
    tags = {t["name"]: t["count"] for t in client.get("/api/library/tags", headers=h).json()}
    assert tags == {"Cats": 2, "Summer sale": 1}
    tags = client.post("/api/library/tags/rename", json={"old": "cats", "new": "Kittens"}, headers=h).json()
    assert {t["name"] for t in tags} == {"Kittens", "Summer sale"}
    assert {t["name"] for t in client.delete("/api/library/tags/Kittens", headers=h).json()} == {"Summer sale"}
    r = client.post("/api/library/media/bulk", json={"ids": [files["clip"].id, files["used"].id],
                                                     "action": "delete"}, headers=h).json()
    assert r == {"done": [files["clip"].id], "skipped": [files["used"].id]}


def test_delete_rules(client, auth, db, files):
    h = auth.headers
    r = client.delete(f"/api/library/media/{files['used'].id}", headers=h)
    assert r.status_code == 409 and r.json()["code"] == "in_use"
    assert client.delete(f"/api/library/media/{files['ai'].id}", headers=h).status_code == 409
    # an editor may delete only the files they added
    editor = signup(client, email="editor@example.com", workspace="Ed")
    db.add(Membership(user_id=editor.user_id, workspace_id=auth.workspace_id, role="editor"))
    db.flush()
    as_editor = {**editor.headers, "X-Workspace": str(auth.workspace_id)}
    assert client.delete(f"/api/library/media/{files['clip'].id}", headers=as_editor).status_code == 403
    mine = client.post("/api/media", files={"file": ("mine.png", png(), "image/png")}, headers=as_editor).json()
    assert client.delete(f"/api/library/media/{mine['id']}", headers=as_editor).status_code == 204
    assert client.delete(f"/api/library/media/{files['clip'].id}", headers=h).status_code == 204
    assert db.get(Media, files["clip"].id) is None


def test_use_in_studio(client, auth, db, monkeypatch, files):
    fake = install_fake_social(monkeypatch, db)
    r = client.post(f"/api/library/media/{files['video'].id}/use", headers=auth.headers)
    assert r.status_code == 200, r.text
    post = fake.created[-1]
    assert r.json() == {"post_id": post.id, "studio_url": f"/studio?post={post.id}"}
    assert [link.media_id for link in post.media_links] == [files["video"].id]
    assert post.name == "reel" and post.source_ref == f"library:{files['video'].id}"


def test_isolation(client, auth, files):
    other = signup(client, email="lib2@example.com", workspace="Lib2")
    h = other.headers
    assert client.get("/api/library/media", headers=h).json()["items"] == []
    assert client.get("/api/library/tags", headers=h).json() == []
    for method, path in (("get", ""), ("get", "/usage"), ("patch", ""), ("delete", ""), ("post", "/favorite"),
                         ("post", "/use")):
        kwargs = {"json": {"tags": ["x"]}} if method == "patch" else {}
        r = getattr(client, method)(f"/api/library/media/{files['clip'].id}{path}", headers=h, **kwargs)
        assert r.status_code == 404, (method, path)
    r = client.post("/api/library/media/bulk", json={"ids": [files["clip"].id], "action": "favorite"}, headers=h)
    assert r.status_code == 404
    client.post("/api/library/tags/rename", json={"old": "Cats", "new": "Hacked"}, headers=h)
    viewer_page = client.get("/api/library/media", headers=auth.headers).json()
    assert all("Hacked" not in i["tags"] for i in viewer_page["items"])
