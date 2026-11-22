"""SVG logos: sanitized on upload, rasterized with resvg-py (size limits, use-bomb guard, cache) wherever a design
is drawn (templates, carousel slides). Every fixture is synthetic and built here."""
import io

from PIL import Image

from app.modules.brand import svg
from app.modules.ideas import slides
from app.modules.templates import render

RED = (230, 20, 30)
LOGO_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
            b'<rect x="0" y="0" width="200" height="100" rx="20" fill="#e6141e"/></svg>')


def _img(content: bytes) -> Image.Image:
    return Image.open(io.BytesIO(content)).convert("RGBA")


def _close(a, b, tolerance=40) -> bool:
    return all(abs(int(x) - int(y)) <= tolerance for x, y in zip(a[:3], b[:3]))


def _count(image: Image.Image, colour) -> int:
    return sum(n for n, c in image.convert("RGB").getcolors(1 << 22) if _close(c, colour))


# ---------------------------------------------------------------------------- rasterizer
def test_rasterize_fits_the_box_and_keeps_transparency():
    assert svg.renderer() == "resvg" and svg.can_rasterize()
    png = svg.rasterize(LOGO_SVG, 300, 300)
    image = _img(png)
    assert image.size == (300, 150)  # aspect kept, fitted in the box
    assert _close(image.getpixel((150, 75)), RED) and image.getpixel((150, 75))[3] == 255
    assert image.getpixel((1, 1))[3] < 255  # the rounded corner stays transparent
    assert svg.rasterize(LOGO_SVG, 300, 300) is png  # cached
    assert svg.intrinsic_size(LOGO_SVG) == (200, 100)


def test_malicious_svgs_are_handled_safely():
    evil = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            b'viewBox="0 0 10 10" onload="alert(1)"><script>alert(2)</script>'
            b'<image xlink:href="https://evil.example/x.png" width="10" height="10"/>'
            b'<image href="file:///etc/passwd" width="10" height="10"/>'
            b'<rect width="10" height="10" fill="#e6141e"/></svg>')
    clean = svg.sanitize(evil).decode()
    assert "script" not in clean and "onload" not in clean and "evil.example" not in clean and "file:" not in clean
    assert _close(_img(svg.rasterize(evil, 20, 20)).getpixel((10, 10)), RED)  # drawn without the bad parts
    # entities (billion laughs) and DOCTYPEs are refused outright
    bomb = (b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg"><text>&b;</text></svg>')
    assert svg.sanitize(bomb) is None and svg.rasterize(bomb, 50) is None
    # a huge viewBox / declared size never makes a huge bitmap: the output is capped
    huge = (b'<svg xmlns="http://www.w3.org/2000/svg" width="100000000" height="100000000" '
            b'viewBox="0 0 100000000 100000000"><rect width="100%" height="100%" fill="#e6141e"/></svg>')
    image = _img(svg.rasterize(huge, 100000, 64))
    assert max(image.size) <= svg.MAX_PX and image.size == (64, 64)
    # <use> fan-out bomb: refused before rendering
    layers = ['<rect id="l0" width="1" height="1"/>']
    for i in range(1, 9):
        layers.append(f'<g id="l{i}">' + "".join(f'<use href="#l{i - 1}"/>' for _ in range(10)) + "</g>")
    use_bomb = ('<svg xmlns="http://www.w3.org/2000/svg"><defs>' + "".join(layers) + '</defs><use href="#l8"/></svg>')
    assert svg.sanitize(use_bomb.encode()) is not None and svg.rasterize(use_bomb.encode(), 100) is None
    assert svg.rasterize(b"<html><body>no</body></html>", 50) is None


def test_svg_logo_is_drawn_into_a_template_and_a_slide():
    spec = {"width": 1080, "height": 1080, "frame": None, "box": (0, 0, 100, 100), "fit": "cover",
            "background": "#ffffff", "text": None,
            "logo": {"content": LOGO_SVG, "position": "top_left", "size": 20}}
    photo = Image.new("RGB", (400, 400), (255, 255, 255))
    out = _img(render.compose(spec, _png(photo), fmt="PNG"))
    corner = out.crop((0, 0, 300, 200))
    assert _count(corner, RED) > 10000  # the logo (216 px wide) is in the top left corner
    assert _count(out.crop((700, 700, 1080, 1080)), RED) == 0
    slide = _img(slides.render_slide({"title": "Hello", "body": "World"}, 0, 2,
                                     {"name": "Acme", "colors": {"primary": "#ffffff", "text": "#111111"}},
                                     logo={"content": LOGO_SVG, "position": "bottom_left", "size": 12}))
    assert _count(slide.crop((0, 1100, 300, 1350)), RED) > 5000


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def test_carousel_uses_an_svg_logo_from_the_media_library(db, client, auth):
    from app.core.storage import save_media
    media = save_media(db, auth.workspace_id, LOGO_SVG, "logo.svg", "image/svg+xml", source="brand")
    assert media.width == 200 and media.height == 100
    brand = {"name": "Acme", "logo_media_id": media.id, "colors": {"primary": "#ffffff", "text": "#111111"}}
    out = slides.render_carousel(db, auth.workspace_id, [{"title": "A"}, {"title": "B"}], brand)
    from app.core.storage import read_media
    first = _img(read_media(out[0]))
    assert _count(first.crop((0, 1100, 300, 1350)), RED) > 5000


# ---------------------------------------------------------------------------- upload
def test_svg_upload_is_sanitised(client, auth, db):
    evil = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10" onload="alert(1)">'
            b'<script>alert(2)</script><rect width="20" height="10" fill="#e6141e"/></svg>')
    r = client.post("/api/media", headers=auth.headers, files={"file": ("logo.svg", evil, "image/svg+xml")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mimetype"] == "image/svg+xml" and body["width"] == 20 and body["height"] == 10
    served = client.get(body["url"], headers=auth.headers)
    assert b"script" not in served.content and b"onload" not in served.content and b"<rect" in served.content
    assert "sandbox" in served.headers["content-security-policy"]
    assert served.headers["x-content-type-options"] == "nosniff"
    # one that cannot be made safe is refused
    bad = b'<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>'
    r = client.post("/api/media", headers=auth.headers, files={"file": ("x.svg", bad, "image/svg+xml")})
    assert r.status_code == 400 and r.json()["code"] == "bad_svg"
    # the uploaded SVG works as the kit logo (an image)
    kit = client.post("/api/brand-kits", headers=auth.headers, json={"name": "Acme", "logo_media_id": body["id"]})
    assert kit.status_code == 201 and kit.json()["logo_url"] == body["url"]


def test_save_media_never_stores_an_unsafe_svg_as_an_image(db, auth):
    from app.core.storage import read_media, save_media
    media = save_media(db, auth.workspace_id, b'<!DOCTYPE x><svg xmlns="http://www.w3.org/2000/svg"/>', "a.svg",
                       "image/svg+xml", source="inbox")
    assert media.mimetype == "application/octet-stream"
    media = save_media(db, auth.workspace_id, b'<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>',
                       "b.svg", None)
    assert media.mimetype == "image/svg+xml" and b"script" not in read_media(media)
