"""Carousel slides in the brand's look: 1080×1350 images with the brand kit's colours, its logo and the
Tajawal font (Arabic shaped right-to-left, Latin left-to-right). The first slide is the hook, the last one the
call to action; a product idea uses the product photo behind the first slide."""
from PIL import Image, ImageDraw

from app.core.models import Media
from app.core.storage import read_media, save_media
from app.modules.templates import render

WIDTH, HEIGHT = render.FORMATS["post_4x5"]


def _colors(brand: dict) -> tuple[str, str, str]:
    colors = brand.get("colors") or {}
    background = colors.get("primary") or "#111111"
    text = colors.get("text") or "#ffffff"
    accent = colors.get("accent") or colors.get("secondary") or text
    return background, text, accent


def _logo(db, workspace_id: int, brand: dict) -> dict | None:
    media_id = brand.get("logo_media_id")
    media = db.get(Media, media_id) if media_id else None
    if not media or media.workspace_id != workspace_id:
        return None
    try:
        return {"content": read_media(media), "position": "bottom_left" if not render.is_rtl(brand.get("name"))
                else "bottom_right", "size": 12}
    except OSError:
        return None


def _photo(db, workspace_id: int, media_id: int | None) -> Image.Image | None:
    media = db.get(Media, media_id) if media_id else None
    if not media or media.workspace_id != workspace_id or media.kind != "image":
        return None
    try:
        photo = render.place_photo(render.open_image(read_media(media)).convert("RGBA"), (WIDTH, HEIGHT))
    except Exception:
        return None
    shade = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(shade)
    for y in range(HEIGHT):  # darker towards the bottom so the text stays readable
        draw.line([(0, y), (WIDTH, y)], fill=(0, 0, 0, int(40 + 150 * y / HEIGHT)))
    photo.alpha_composite(shade)
    return photo


def render_slide(slide: dict, index: int, total: int, brand: dict, *, logo: dict | None = None,
                 photo: Image.Image | None = None) -> bytes:
    background, text, accent = _colors(brand)
    canvas = photo.copy() if photo is not None else Image.new("RGBA", (WIDTH, HEIGHT),
                                                              render.hex_color(background) + (255,))
    text_color = "#ffffff" if photo is not None else text
    draw = ImageDraw.Draw(canvas)
    first, last = index == 0, index == total - 1
    rtl = render.is_rtl((slide.get("title") or "") + (slide.get("body") or ""))
    align = "right" if rtl else "left"
    bar_x = WIDTH - 96 - 120 if rtl else 96
    draw.rounded_rectangle((bar_x, 120, bar_x + 120, 132), radius=6, fill=render.hex_color(accent) + (255,))
    render.draw_text(canvas, f"{index + 1}/{total}", {"x": 8, "y": 5, "w": 84, "h": 4, "size": 30, "bold": False,
                                                      "color": text_color, "align": "left" if rtl else "right",
                                                      "max_lines": 1})
    title_box = {"x": 9, "y": 22 if first else 18, "w": 82, "h": 34 if first else 26}
    render.draw_text(canvas, slide.get("title"), {**title_box, "size": 104 if first else 84, "bold": True,
                                                  "color": text_color, "align": align, "max_lines": 4})
    body_top = title_box["y"] + title_box["h"] + 3
    render.draw_text(canvas, slide.get("body"), {"x": 9, "y": body_top, "w": 82, "h": 80 - body_top, "size": 50,
                                                 "bold": False, "color": text_color, "align": align, "max_lines": 7})
    if last:
        draw.rounded_rectangle((96, HEIGHT - 300, WIDTH - 96, HEIGHT - 296), radius=2,
                               fill=render.hex_color(accent) + (255,))
    render.draw_text(canvas, brand.get("name"), {"x": 9, "y": 88, "w": 82, "h": 5, "size": 34, "bold": True,
                                                 "color": text_color, "align": "left" if rtl else "right",
                                                 "max_lines": 1})
    canvas = render._paste_logo(canvas, logo)
    return render.to_jpeg(canvas.convert("RGB"), quality=92)


def render_carousel(db, workspace_id: int, slides: list[dict], brand: dict, *, product_image_id: int | None = None,
                    user_id: int | None = None, name: str = "idea") -> list[Media]:
    logo = _logo(db, workspace_id, brand)
    photo = _photo(db, workspace_id, product_image_id)
    media = []
    for index, slide in enumerate(slides):
        content = render_slide(slide, index, len(slides), brand, logo=logo, photo=photo if index == 0 else None)
        media.append(save_media(db, workspace_id, content, f"{name}-{index + 1}.jpg", "image/jpeg", source="ideas",
                                user_id=user_id))
    return media
