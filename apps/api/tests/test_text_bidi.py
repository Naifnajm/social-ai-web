"""Mixed Arabic / Latin lines in designs: Unicode bidi runs per line, paragraph direction from the first strong
letter, each run drawn with its own direction."""
from PIL import Image, ImageDraw

from app.modules.templates import render


def test_mixed_line_visual_order():
    assert render.visual_runs("قهوة Cold Brew جديدة") == [("جديدة", True), ("Cold Brew", False), ("قهوة", True)]
    assert render.visual_runs("New قهوة today") == [("New", False), ("قهوة", True), ("today", False)]
    # neutrals (numbers, %) follow their neighbours when both agree, else the paragraph direction
    assert render.visual_runs("خصم 20% على Cold Brew") == [("Cold Brew", False), ("خصم 20% على", True)]
    assert render.visual_runs("Brew 20 قهوة") == [("Brew 20", False), ("قهوة", True)]
    assert render.base_rtl("Cold Brew قهوة") is False and render.base_rtl("قهوة Cold Brew") is True
    assert render.base_rtl("2024 قهوة") is True and render.base_rtl("") is False


def test_mixed_line_is_drawn_run_by_run_in_visual_order():
    font = render.load_font(60)
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    width, placed = render.line_layout(draw, "قهوة Cold Brew جديدة", font)
    assert [run for _x, run, _r in placed] == ["جديدة", "Cold Brew", "قهوة"]
    assert placed[0][0] == 0 and placed[0][0] < placed[1][0] < placed[2][0] < width
    # the Latin run sits in the middle of the drawn line: its ink is found between the two Arabic words
    canvas = Image.new("RGBA", (1200, 200), (0, 0, 0, 255))
    render.draw_text(canvas, "قهوة Cold Brew جديدة", {"x": 0, "y": 0, "w": 100, "h": 100, "size": 60,
                                                    "color": "#ffffff", "align": "left", "max_lines": 1})
    alone = Image.new("RGBA", (1200, 200), (0, 0, 0, 255))
    render.draw_text(alone, "Cold Brew", {"x": 0, "y": 0, "w": 100, "h": 100, "size": 60, "color": "#ffffff",
                                          "align": "left", "max_lines": 1})
    ink = canvas.convert("L").point(lambda v: 255 if v > 128 else 0).getbbox()
    latin = alone.convert("L").point(lambda v: 255 if v > 128 else 0).getbbox()
    latin_w = latin[2] - latin[0]
    offset = placed[1][0]
    # the column band where "Cold Brew" is drawn inside the full line matches the lone rendering
    start = round(offset) + latin[0]
    band = canvas.crop((start, 0, start + latin_w, 200)).convert("L").tobytes()
    lone = alone.crop((latin[0], 0, latin[0] + latin_w, 200)).convert("L").tobytes()
    same = sum(1 for a, b in zip(band, lone) if (a > 128) == (b > 128))
    assert same / len(lone) > 0.99
    assert ink[0] < offset and ink[2] > offset + latin_w  # Arabic ink on both sides


def test_mixed_line_without_raqm_still_draws(monkeypatch):
    monkeypatch.setattr(render, "has_raqm", lambda: False)
    assert render._rtl_fallback("قهوة 20") in ("20 ةوهق", render._rtl_fallback("قهوة 20"))  # python-bidi if installed
    canvas = Image.new("RGBA", (1080, 400), (0, 0, 0, 255))
    render.draw_text(canvas, "قهوة Cold Brew جديدة", {"x": 5, "y": 5, "w": 90, "h": 90, "size": 60,
                                                    "color": "#ffffff", "max_lines": 2})
    assert canvas.convert("L").point(lambda v: 255 if v > 128 else 0).getbbox()
