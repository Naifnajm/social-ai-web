"""Brand templates: frame detection, composition, Arabic text, previews, Quick publish, Telegram command, isolation."""
import io
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image, ImageDraw

from app.core.errors import NotFound
from app.core.models import Media
from app.core.storage import read_media, save_media
from app.modules.social import service as social
from app.modules.social.models import Post, PostMedia, PostTarget, SocialAccount
from app.modules.templates import frame, render, service, telegram
from app.modules.templates.models import BrandTemplate
from app.modules.workspaces.settings import set_setting
from tests.conftest import signup

FRAME_COLOR = (17, 24, 39)
PHOTO_COLOR = (220, 30, 30)


def _frame_png(size=(1080, 1350), window=(100, 100, 980, 1000), extra_hole=None) -> bytes:
    """Opaque frame with a transparent rectangle (and optionally a second, smaller one)."""
    image = Image.new("RGBA", size, FRAME_COLOR + (255,))
    draw = ImageDraw.Draw(image)
    draw.rectangle((window[0], window[1], window[2] - 1, window[3] - 1), fill=(0, 0, 0, 0))
    if extra_hole:
        draw.rectangle(extra_hole, fill=(0, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _photo(size=(1600, 1000), color=PHOTO_COLOR, fmt="JPEG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


def _close(color, expected, tolerance=12):
    return all(abs(a - b) <= tolerance for a, b in zip(color, expected))


def _img(content: bytes) -> Image.Image:
    return Image.open(io.BytesIO(content)).convert("RGB")


def _upload_frame(client, auth, png=None, name="frame.png"):
    r = client.post("/api/templates/frames", files={"file": (name, png or _frame_png(), "image/png")},
                    headers=auth.headers)
    assert r.status_code == 201, r.text
    return r.json()


def _upload_photo(client, auth, content=None, name="shop.jpg", mimetype="image/jpeg"):
    r = client.post("/api/media", files={"file": (name, content or _photo(), mimetype)}, headers=auth.headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def offers(client, auth):
    """A set "Offers" with a 4:5 post template (text zone) and a 9:16 story template."""
    tset = client.post("/api/templates/sets", json={"name": "Offers", "category": "offers"}, headers=auth.headers).json()
    post_frame = _upload_frame(client, auth)
    story_frame = _upload_frame(client, auth, _frame_png((1080, 1920), (60, 200, 1020, 1500)))
    post_tpl = client.post("/api/templates", json={
        "name": "Offers post", "set_id": tset["id"], "frame_media_id": post_frame["media"]["id"],
        "text_enabled": True, "text_x": 5, "text_y": 76, "text_w": 90, "text_h": 20, "text_size": 60,
        "text_default": "99 SAR", "text_color": "#ffffff"}, headers=auth.headers)
    assert post_tpl.status_code == 201, post_tpl.text
    story_tpl = client.post("/api/templates", json={
        "name": "Offers story", "set_id": tset["id"], "frame_media_id": story_frame["media"]["id"]},
        headers=auth.headers)
    assert story_tpl.status_code == 201, story_tpl.text
    return {"set": tset, "post": post_tpl.json(), "story": story_tpl.json()}


@pytest.fixture()
def fake_social(monkeypatch, db):
    """Stand-in for the publishing contract: real Post rows, states driven by ``submit``."""
    calls = {"create": [], "submit": []}

    def create_post(db_, workspace_id, user_id, *, content="", media_ids=None, account_ids=None, publish_as="feed",
                    story_media_ids=None, name=None, source_ref=None, **_kw):
        post = Post(workspace_id=workspace_id, author_id=user_id, content=content, name=name, publish_as=publish_as,
                    source_ref=source_ref, state="draft")
        post.accounts = [db_.get(SocialAccount, a) for a in account_ids or []]
        for index, mid in enumerate(media_ids or []):
            post.media_links.append(PostMedia(media_id=mid, position=index, role="feed"))
        for index, mid in enumerate(story_media_ids or []):
            post.media_links.append(PostMedia(media_id=mid, position=index, role="story"))
        db_.add(post)
        db_.flush()
        calls["create"].append({"post": post, "media_ids": list(media_ids or []),
                                "story_media_ids": list(story_media_ids or []), "account_ids": list(account_ids or [])})
        return post

    def submit(db_, post, user_id, *, action, when=None):
        calls["submit"].append((post.id, action, when))
        if action == "publish":
            post.state = "posted"
            for account in post.accounts:
                db_.add(PostTarget(workspace_id=post.workspace_id, post_id=post.id, account_id=account.id,
                                   platform=account.platform, state="posted",
                                   external_url=f"https://example.com/{account.platform}/{post.id}"))
        elif action in ("schedule", "best_time"):
            post.state = "scheduled"
            post.scheduled_at = when or datetime(2030, 1, 7, 16, 0, tzinfo=UTC)
        db_.flush()
        return post

    def next_best_slots(db_, workspace_id, platforms=None, count=3):
        start = datetime(2030, 1, 7, 16, 0, tzinfo=UTC)
        return [{"at": start + timedelta(days=i), "label": f"Mon {19 + i}:00"} for i in range(count)]

    monkeypatch.setattr(social, "create_post", create_post)
    monkeypatch.setattr(social, "submit", submit)
    monkeypatch.setattr(social, "next_best_slots", next_best_slots)
    return calls


def _account(db, workspace_id, platform="instagram", name=None):
    account = SocialAccount(workspace_id=workspace_id, name=name or platform.title(), platform=platform,
                            external_id=f"{platform}-1", state="connected")
    db.add(account)
    db.flush()
    return account


# ---------------------------------------------------------------------------- frames
def test_detect_window_and_format(client, auth, offers):
    post, story = offers["post"], offers["story"]
    assert (post["format"], story["format"]) == ("post_4x5", "story_9x16")
    assert post["box_x"] == pytest.approx(100 / 1080 * 100, abs=0.1)
    assert post["box_y"] == pytest.approx(100 / 1350 * 100, abs=0.1)
    assert post["box_w"] == pytest.approx(880 / 1080 * 100, abs=0.1)
    assert post["box_h"] == pytest.approx(900 / 1350 * 100, abs=0.1)
    assert post["frame_has_window"] is True
    # the largest transparent area wins over a small hole
    found = render.detect_window(_frame_png(window=(500, 200, 1000, 1200), extra_hole=(20, 20, 120, 120)))
    x, _y, _w, h = found["box"]
    assert x == pytest.approx(500 / 1080 * 100, abs=0.1)
    assert h == pytest.approx(1000 / 1350 * 100, abs=0.1)
    # a frame without transparency: whole canvas, flagged, square format
    opaque = io.BytesIO()
    Image.new("RGB", (1080, 1080), (0, 0, 0)).save(opaque, "PNG")
    up = _upload_frame(client, auth, opaque.getvalue())
    assert up["detection"]["frame_has_window"] is False
    assert up["detection"]["format"] == "post_1x1"
    # editing the box by hand is kept; "detect" restores it
    r = client.patch(f"/api/templates/{post['id']}", json={"box_x": 20}, headers=auth.headers)
    assert r.json()["box_x"] == 20
    r = client.post(f"/api/templates/{post['id']}/detect", headers=auth.headers)
    assert r.json()["box_x"] == pytest.approx(9.26, abs=0.05)
    # not an image
    r = client.post("/api/templates/frames", files={"file": ("x.png", b"nope", "image/png")}, headers=auth.headers)
    assert r.status_code == 400


def test_compose_pixels_cover_contain_and_jpeg(db, client, auth, offers):
    ws = auth.workspace_id
    photo_id = _upload_photo(client, auth)
    framed = frame.compose(db, ws, offers["post"]["id"], photo_id, text="")
    assert (framed.mimetype, framed.source, framed.workspace_id) == ("image/jpeg", "template", ws)
    assert framed.filename.endswith("-4x5.jpg")
    image = _img(read_media(framed))
    assert image.size == (1080, 1350)
    assert _close(image.getpixel((540, 550)), PHOTO_COLOR)  # photo through the window
    assert _close(image.getpixel((40, 40)), FRAME_COLOR, 6)  # frame on top
    assert _close(image.getpixel((1060, 1300)), FRAME_COLOR, 6)
    assert read_media(framed)[:3] == b"\xff\xd8\xff"  # JPEG (Instagram)
    # a set picks its story template
    story = frame.compose_for_post(db, ws, f"set:{offers['set']['id']}", photo_id, story=True)
    image = _img(read_media(story))
    assert image.size == (1080, 1920)
    assert _close(image.getpixel((540, 850)), PHOTO_COLOR)
    assert _close(image.getpixel((540, 100)), FRAME_COLOR, 6)
    # contain: the whole (very wide) photo over a blurred copy, still only inside the window
    client.patch(f"/api/templates/{offers['story']['id']}", json={"photo_fit": "contain"}, headers=auth.headers)
    wide = _upload_photo(client, auth, _photo((2000, 400)))
    image = _img(read_media(frame.compose(db, ws, offers["story"]["id"], wide)))
    assert _close(image.getpixel((540, 850)), PHOTO_COLOR)
    assert _close(image.getpixel((540, 1800)), FRAME_COLOR, 6)
    # usage counted
    assert db.get(BrandTemplate, offers["post"]["id"]).usage_count == 1
    assert db.get(BrandTemplate, offers["story"]["id"]).usage_count == 2


def test_exif_palette_webp_and_logo(db, client, auth, offers):
    buffer = io.BytesIO()
    image = Image.new("RGB", (400, 200), PHOTO_COLOR)
    exif = image.getexif()
    exif[0x0112] = 6  # rotate 90°
    image.save(buffer, "JPEG", exif=exif)
    assert render.open_image(buffer.getvalue()).size == (200, 400)
    spec = service.frame_spec(db, db.get(BrandTemplate, offers["post"]["id"]))
    palette = io.BytesIO()
    Image.new("P", (300, 300), 3).save(palette, "PNG")
    assert _img(render.compose(spec, palette.getvalue())).size == (1080, 1350)
    webp = io.BytesIO()
    Image.new("RGB", (300, 300), PHOTO_COLOR).save(webp, "WEBP")
    assert _img(render.compose(spec, webp.getvalue())).size == (1080, 1350)
    # logo from the brand kit, bottom-left corner
    from app.modules.brand.models import BrandKit
    logo = save_media(db, auth.workspace_id, _photo((200, 200), (0, 200, 0), "PNG"), "logo.png", "image/png")
    kit = BrandKit(workspace_id=auth.workspace_id, name="Cafe", logo_media_id=logo.id, color_primary="#0000ff")
    db.add(kit)
    db.flush()
    r = client.patch(f"/api/templates/{offers['post']['id']}", json={
        "brand_kit_id": kit.id, "logo_enabled": True, "logo_position": "bottom_left", "logo_size": 20},
        headers=auth.headers)
    assert r.status_code == 200, r.text
    spec = service.frame_spec(db, db.get(BrandTemplate, offers["post"]["id"]))
    out = _img(render.compose(spec, _photo()))
    margin = int(1080 * 0.04)
    assert _close(out.getpixel((margin + 50, 1350 - margin - 50)), (0, 200, 0))


def test_arabic_and_latin_text(db, client, auth, offers):
    assert render.has_raqm()
    assert render.font_path(True).endswith("Tajawal-Bold.ttf")
    spec = service.frame_spec(db, db.get(BrandTemplate, offers["post"]["id"]))
    zone = (60, int(1350 * 0.78), 1020, int(1350 * 0.94))
    for text in ("خصم ٢٠٪ على كل القهوة — اليوم فقط", "Coffee 20% off today", "عرض Pizza ٩٩ SAR"):
        crop = _img(render.compose(spec, _photo(), text=text)).crop(zone)
        whites = [c for c in crop.getcolors(1 << 20) if min(c[1]) > 200]
        assert sum(count for count, _c in whites) > 500, f"white text should be drawn for {text!r}"
    # Arabic is right-aligned (auto) — ink on the right half of the zone, none at the far left
    crop = _img(render.compose(spec, _photo(), text="عرض")).crop(zone)
    left, right = crop.crop((0, 0, 300, crop.height)), crop.crop((crop.width - 300, 0, crop.width, crop.height))
    count = lambda part: sum(n for n, c in part.getcolors(1 << 20) if min(c) > 200)
    assert count(right) > 200 and count(left) == 0
    # RAQM shapes Arabic: the joined word is narrower than its isolated letters
    font = render.load_font(60)
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    joined = render._measure(draw, "مرحبا", font, True)[0]
    isolated = sum(render._measure(draw, ch, font, True)[0] for ch in "مرحبا")
    assert joined < isolated
    # very long text shrinks to the line limit instead of overflowing; a label background is drawn
    long_text = "عرض خاص " * 40
    spec["text"]["background"] = "#ff0000"
    out = _img(render.compose(spec, _photo((800, 800), (0, 0, 255)), text=long_text))
    assert any(_close(c, (255, 0, 0), 30) for _n, c in out.crop(zone).getcolors(1 << 20))


def test_previews_and_live_render(client, auth, offers):
    tpl = offers["post"]
    assert tpl["preview_media_id"]
    r = client.get(tpl["preview_url"], headers=auth.headers)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert max(_img(r.content).size) == 720
    old = tpl["preview_media_id"]
    updated = client.patch(f"/api/templates/{tpl['id']}", json={"text_size": 40}, headers=auth.headers).json()
    assert updated["preview_media_id"] != old  # re-rendered, old file removed
    assert client.get(f"/api/media/{old}", headers=auth.headers).status_code == 404
    # live preview of unsaved values (editor)
    r = client.post("/api/templates/render-preview", json={"template_id": tpl["id"], "box_x": 0, "box_y": 0,
                                                           "box_w": 100, "box_h": 100, "text": "سعر خاص"},
                    headers=auth.headers)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    r = client.post("/api/templates/render-preview", json={"format": "story_9x16"}, headers=auth.headers)
    assert _img(r.content).size[1] == 900
    # duplicate + delete
    copy = client.post(f"/api/templates/{tpl['id']}/duplicate", headers=auth.headers).json()
    assert copy["name"].startswith("Offers post") and copy["frame_media_id"] == tpl["frame_media_id"]
    assert client.delete(f"/api/templates/{copy['id']}", headers=auth.headers).status_code == 204
    assert client.get(f"/api/media/{tpl['frame_media_id']}", headers=auth.headers).status_code == 200  # shared
    sets = client.get("/api/templates/sets", headers=auth.headers).json()
    assert sets[0]["post_template_id"] == tpl["id"] and sets[0]["story_template_id"] == offers["story"]["id"]


# ---------------------------------------------------------------------------- quick publish
def test_quick_data_and_preview(db, client, auth, offers, fake_social):
    _account(db, auth.workspace_id, "instagram")
    _account(db, auth.workspace_id, "linkedin")
    photo = _upload_photo(client, auth)
    photo2 = _upload_photo(client, auth, _photo((800, 1200), (30, 30, 220), "PNG"), "cup.png", "image/png")
    data = client.get("/api/templates/quick", headers=auth.headers).json()
    assert data["choices"][0]["key"] == f"set:{offers['set']['id']}"
    assert [t["role"] for t in data["choices"][0]["templates"]] == ["post", "story"]
    assert {a["platform"]: a["can_story"] for a in data["accounts"]} == {"instagram": True, "linkedin": False}
    assert {m["id"] for m in data["recent"]} == {photo, photo2}  # frames and previews are not offered
    assert data["best_slots"][0]["label"] == "Mon 19:00"
    previews = client.post("/api/templates/quick/preview", json={
        "choice": f"set:{offers['set']['id']}", "media_ids": [photo, photo2], "text": "49 SAR"},
        headers=auth.headers).json()
    assert len(previews) == 2
    assert [i["role"] for i in previews[0]["items"]] == ["post", "story"]
    assert previews[0]["items"][0]["src"].startswith("data:image/jpeg;base64,")


def test_quick_publish_draft_and_carousel(db, client, auth, offers, fake_social):
    ig = _account(db, auth.workspace_id, "instagram")
    fb = _account(db, auth.workspace_id, "facebook")
    photo = _upload_photo(client, auth)
    photo2 = _upload_photo(client, auth, _photo((800, 1200), (30, 30, 220), "PNG"), "cup.png", "image/png")
    r = client.post("/api/templates/quick/publish", json={
        "choice": f"set:{offers['set']['id']}", "media_ids": [photo, photo2], "content": "New offers!",
        "text": "49 SAR", "account_ids": [ig.id, fb.id], "publish_as": "feed_story", "mode": "draft"},
        headers=auth.headers)
    assert r.status_code == 200, r.text
    result = r.json()
    assert len(result["posts"]) == 2 and result["posts"][0]["state"] == "draft"
    for created in fake_social["create"]:
        assert created["account_ids"] == [ig.id, fb.id]
        feed, story = db.get(Media, created["media_ids"][0]), db.get(Media, created["story_media_ids"][0])
        assert _img(read_media(feed)).size == (1080, 1350)
        assert _img(read_media(story)).size == (1080, 1920)
        assert created["post"].brand_template_id == offers["post"]["id"]
        assert created["post"].source_ref == "quick"
    assert {s[1] for s in fake_social["submit"]} == {"draft"}
    assert db.get(BrandTemplate, offers["post"]["id"]).usage_count == 2
    assert db.get(BrandTemplate, offers["story"]["id"]).usage_count == 2
    # one carousel, feed only
    fake_social["create"].clear()
    r = client.post("/api/templates/quick/publish", json={
        "choice": offers["set"]["id"] and f"set:{offers['set']['id']}", "media_ids": [photo, photo2],
        "content": "Carousel", "account_ids": [ig.id], "publish_as": "feed", "grouping": "carousel", "mode": "draft"},
        headers=auth.headers)
    assert len(r.json()["posts"]) == 1
    assert len(fake_social["create"][0]["media_ids"]) == 2 and fake_social["create"][0]["story_media_ids"] == []
    # without caption the post is named after the set
    r = client.post("/api/templates/quick/publish", json={
        "choice": f"template:{offers['story']['id']}", "media_ids": [photo], "publish_as": "story", "mode": "draft"},
        headers=auth.headers)
    assert r.json()["posts"][0]["name"].startswith("Offers — ")


def test_quick_publish_now_best_time_schedule_and_errors(db, client, auth, offers, fake_social):
    ig = _account(db, auth.workspace_id, "instagram")
    photo = _upload_photo(client, auth)
    base = {"choice": f"set:{offers['set']['id']}", "media_ids": [photo], "account_ids": [ig.id]}
    r = client.post("/api/templates/quick/publish", json={**base, "content": "Now", "mode": "now"}, headers=auth.headers)
    post = r.json()["posts"][0]
    assert post["state"] == "posted"
    assert post["results"][0]["url"] == f"https://example.com/instagram/{post['id']}"
    r = client.post("/api/templates/quick/publish", json={**base, "publish_as": "story", "mode": "best_time"},
                    headers=auth.headers)
    assert r.json()["posts"][0]["state"] == "scheduled" and r.json()["posts"][0]["scheduled_at"]
    when = "2030-02-01T10:00:00Z"
    client.post("/api/templates/quick/publish", json={**base, "mode": "schedule", "scheduled_at": when},
                headers=auth.headers)
    assert fake_social["submit"][-1][1:] == ("schedule", datetime(2030, 2, 1, 10, tzinfo=UTC))
    # errors: no account, no date, unknown choice
    r = client.post("/api/templates/quick/publish", json={**base, "account_ids": [], "mode": "now"}, headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "no_accounts"
    r = client.post("/api/templates/quick/publish", json={**base, "mode": "schedule"}, headers=auth.headers)
    assert r.json()["code"] == "no_date"
    r = client.post("/api/templates/quick/publish", json={**base, "choice": "set:999999"}, headers=auth.headers)
    assert r.status_code == 404


def test_compose_video(db, client, auth, offers, tmp_path):
    if not render.ffmpeg_available():
        pytest.skip("ffmpeg missing")
    path = tmp_path / "in.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=1", "-pix_fmt", "yuv420p",
                    str(path)], check=True, capture_output=True)
    video = save_media(db, auth.workspace_id, path.read_bytes(), "clip.mp4", "video/mp4")
    framed = frame.compose(db, auth.workspace_id, offers["post"]["id"], video.id)
    assert framed.mimetype == "video/mp4" and read_media(framed)[4:8] == b"ftyp"
    poster = _img(render.video_poster(read_media(framed), "video/mp4", at=0.2))
    assert poster.size == (720, 900)
    r, g, _b = poster.getpixel((360, 360))
    assert r > 180 and g < 80
    r, _g, b = poster.getpixel((20, 20))
    assert r < 60 and b < 80
    previews = service.quick_preview(db, auth.workspace_id, f"set:{offers['set']['id']}", [video.id], None)
    assert previews[0]["video"] and len(previews[0]["items"]) == 2


# ---------------------------------------------------------------------------- telegram
def _telegram(db, account, caption, media_ids, sender=None):
    message = {"message_id": 5, "from": sender or {"id": 4242, "username": "sara", "language_code": "en"},
               "chat": {"id": 4242, "type": "private"}, "caption": caption}
    return telegram.handle_command(db, account, message, media_ids)


def test_telegram_authorisation(db, client, auth, offers, fake_social):
    bot = _account(db, auth.workspace_id, "telegram", "Bot")
    photo = _upload_photo(client, auth)
    assert _telegram(db, bot, "/post offers Hello", [photo]) is None  # nobody allowed yet
    set_setting(db, auth.workspace_id, "templates.telegram.publishers", ["@Sara", "77"])
    assert _telegram(db, bot, "/post offers Hello", [photo], {"id": 1, "username": "eve"}) is None
    assert _telegram(db, bot, "/post offers Hello", [photo])
    assert _telegram(db, bot, "/post offers Hello", [photo], {"id": 77})
    assert _telegram(db, bot, "Hello, how are you?", [photo]) is None  # not a command: left to the inbox
    # settings API: admin only, ids checked
    r = client.put("/api/templates/telegram-settings", json={"publishers": [" @sara ", "", "77"], "mode": "publish"},
                   headers=auth.headers)
    assert r.json()["publishers"] == ["@sara", "77"]
    assert client.get("/api/templates/telegram-settings", headers=auth.headers).json()["mode"] == "publish"
    assert client.put("/api/templates/telegram-settings", json={"default_set_id": 999999},
                      headers=auth.headers).status_code == 404


def test_telegram_commands_english_and_arabic(db, client, auth, offers, fake_social):
    ws = auth.workspace_id
    bot = _account(db, ws, "telegram", "Bot")
    ig, fb = _account(db, ws, "instagram"), _account(db, ws, "facebook")
    photo = _upload_photo(client, auth)
    set_setting(db, ws, "templates.telegram.publishers", ["4242"])
    set_setting(db, ws, "templates.telegram.account_ids", [ig.id, fb.id])

    reply = _telegram(db, bot, "/post offers [99 SAR] Our new menu is here", [photo])
    created = fake_social["create"][-1]
    post = created["post"]
    assert "Offers" in reply and f"/posts/{post.id}" in reply and reply.startswith("📝")
    assert (post.state, post.publish_as, post.content) == ("draft", "feed", "Our new menu is here")
    assert created["account_ids"] == [ig.id, fb.id] and post.source_ref == "telegram"
    assert post.brand_template_id == offers["post"]["id"]

    # Arabic verb + Arabic set name with the article (fuzzy match); the reply is in Arabic
    client.patch(f"/api/templates/sets/{offers['set']['id']}", json={"name": "عروض"}, headers=auth.headers)
    reply = _telegram(db, bot, "ستوري العروض خصم على كل القهوة\nاليوم فقط", [photo])
    created = fake_social["create"][-1]
    assert created["post"].publish_as == "story"
    assert created["post"].content == "خصم على كل القهوة\nاليوم فقط"
    assert _img(read_media(db.get(Media, created["story_media_ids"][0]))).size == (1080, 1920)
    assert "عروض" in reply and "حُفظت المسودة" in reply

    # English "draft" verb with no set name: the default set is used
    set_setting(db, ws, "templates.telegram.default_set_id", offers["set"]["id"])
    _telegram(db, bot, "/draft just a caption", [photo])
    assert fake_social["create"][-1]["post"].content == "just a caption"

    # price line instead of brackets
    _telegram(db, bot, "post عروض Fresh bread\nprice: 5 SAR", [photo])
    assert fake_social["create"][-1]["post"].content == "Fresh bread"

    # list, help, missing photo (Arabic reply)
    assert "عروض" in _telegram(db, bot, "/templates", [])
    assert "/post" in _telegram(db, bot, "/help", [])
    assert "أرفق صورة" in _telegram(db, bot, "انشر عروض بدون صورة", [])
    # another workspace's media is ignored
    other = signup(client, email="eve@example.com", workspace="Eve")
    foreign = _upload_photo(client, other)
    assert "photo" in _telegram(db, bot, "/post offers Hi", [foreign])


def test_telegram_publish_mode_and_ai(db, client, auth, offers, fake_social, monkeypatch):
    from app.modules.ai import service as ai

    ws = auth.workspace_id
    bot = _account(db, ws, "telegram", "Bot")
    fb = _account(db, ws, "facebook", "Page")
    photo = _upload_photo(client, auth)
    set_setting(db, ws, "templates.telegram.publishers", ["@sara"])
    set_setting(db, ws, "templates.telegram.mode", "publish")
    set_setting(db, ws, "templates.telegram.account_ids", [fb.id])
    prompts = []

    def fake_generate(db_, workspace_id, system, user, **kwargs):
        prompts.append((workspace_id, system, user))
        return '"Polished caption #offers"'

    monkeypatch.setattr(ai, "generate_text", fake_generate)
    client.patch(f"/api/templates/sets/{offers['set']['id']}", json={"name": "العروض"}, headers=auth.headers)
    reply = _telegram(db, bot, "انشر عروض #ai قهوة جديدة", [photo])
    post = fake_social["create"][-1]["post"]
    assert post.content == "Polished caption #offers" and post.state == "posted"
    assert prompts[0][0] == ws and prompts[0][2] == "قهوة جديدة"
    assert "✅" in reply and f"https://example.com/facebook/{post.id}" in reply

    # AI failure keeps the caption
    def failing(*_a, **_k):
        from app.core.errors import AppError
        raise AppError("No AI provider", code="no_ai_provider")

    monkeypatch.setattr(ai, "generate_text", failing)
    _telegram(db, bot, "/post عروض #ai Keep me", [photo])
    assert fake_social["create"][-1]["post"].content == "Keep me"

    # best time: scheduled
    set_setting(db, ws, "templates.telegram.mode", "best_time")
    reply = _telegram(db, bot, "/post عروض Later", [photo])
    assert fake_social["create"][-1]["post"].state == "scheduled"
    assert "🗓" in reply and "2030-01-07" in reply

    # errors are reported, nothing half-created
    def broken_create(*_a, **_k):
        from app.core.errors import AppError
        raise AppError("Plan limit reached", code="limit")

    monkeypatch.setattr(social, "create_post", broken_create)
    assert _telegram(db, bot, "/post عروض Boom", [photo]).startswith("⚠️ Plan limit reached")


# ---------------------------------------------------------------------------- isolation & roles
def test_workspace_isolation(db, client, auth, offers, fake_social):
    other = signup(client, email="eve@example.com", workspace="Eve")
    tpl, tset = offers["post"], offers["set"]
    assert client.get("/api/templates", headers=other.headers).json() == []
    assert client.get("/api/templates/sets", headers=other.headers).json() == []
    assert client.get(f"/api/templates/{tpl['id']}", headers=other.headers).status_code == 404
    assert client.get(f"/api/templates/{tpl['id']}/preview", headers=other.headers).status_code == 404
    assert client.patch(f"/api/templates/{tpl['id']}", json={"name": "x"}, headers=other.headers).status_code == 404
    assert client.delete(f"/api/templates/{tpl['id']}", headers=other.headers).status_code == 404
    assert client.patch(f"/api/templates/sets/{tset['id']}", json={"name": "x"}, headers=other.headers).status_code == 404
    assert client.post(f"/api/templates/{tpl['id']}/duplicate", headers=other.headers).status_code == 404
    # cannot use the other workspace's frame, set or photo
    r = client.post("/api/templates", json={"name": "Steal", "frame_media_id": tpl["frame_media_id"]},
                    headers=other.headers)
    assert r.status_code == 404
    r = client.post("/api/templates", json={"name": "Steal", "set_id": tset["id"]}, headers=other.headers)
    assert r.status_code == 404
    mine = _upload_photo(client, auth)
    r = client.post("/api/templates/quick/preview", json={"choice": f"set:{tset['id']}", "media_ids": [mine]},
                    headers=other.headers)
    assert r.status_code == 404
    own_set = client.post("/api/templates/sets", json={"name": "Eve set"}, headers=other.headers).json()
    r = client.post("/api/templates/quick/preview", json={"choice": f"set:{own_set['id']}", "media_ids": [mine]},
                    headers=other.headers)
    assert r.status_code in (400, 404)
    r = client.post("/api/templates/render-preview", json={"template_id": tpl["id"]}, headers=other.headers)
    assert r.status_code == 404
    with pytest.raises(NotFound):
        frame.compose(db, other.workspace_id, tpl["id"], mine)
    with pytest.raises(NotFound):
        frame.compose_for_post(db, other.workspace_id, f"set:{tset['id']}", mine)
    # account of another workspace
    foreign_account = _account(db, auth.workspace_id, "instagram")
    eve_photo = _upload_photo(client, other)
    eve_frame = _upload_frame(client, other)
    eve_tpl = client.post("/api/templates", json={"name": "Eve", "frame_media_id": eve_frame["media"]["id"]},
                          headers=other.headers).json()
    r = client.post("/api/templates/quick/publish", json={
        "choice": f"template:{eve_tpl['id']}", "media_ids": [eve_photo], "account_ids": [foreign_account.id],
        "mode": "now"}, headers=other.headers)
    assert r.status_code == 404
    assert client.get("/api/templates/quick", headers=other.headers).json()["choices"][0]["name"] == "Eve"


def test_roles(client, auth, offers):
    other = signup(client, email="v@example.com", workspace="V")
    inv = client.post("/api/workspace/invitations", json={"email": "v@example.com", "role": "viewer"},
                      headers=auth.headers)
    assert inv.status_code == 201
    from app.core.mail import OUTBOX
    token = OUTBOX[-1].get_body(("plain",)).get_content().strip().rsplit("/", 1)[-1]
    assert client.post(f"/api/invitations/{token}/accept", headers=other.headers).status_code == 200
    viewer = {**other.headers, "X-Workspace": str(auth.workspace_id)}
    assert client.get("/api/templates", headers=viewer).status_code == 200
    assert client.post("/api/templates", json={"name": "x"}, headers=viewer).status_code == 403
    assert client.get("/api/templates/telegram-settings", headers=viewer).status_code == 403
