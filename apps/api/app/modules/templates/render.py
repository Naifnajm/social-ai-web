"""Brand frames engine: put a photo (or a video) behind a PNG frame with a transparent window.

Pure functions on bytes and a *spec* dict (no database) — ``service.frame_spec(db, template)`` builds the spec::

    {
        "width": 1080, "height": 1350,
        "frame": b"<png>" or None,
        "box": (x, y, w, h),            # photo window, % of the canvas
        "fit": "cover" | "contain",
        "background": "#111111",
        "text": {"x", "y", "w", "h", "size", "color", "align", "bold", "max_lines", "background", "default"} or None,
        "logo": {"content": b"<png>", "position": "top_left", "size": 18} or None,
    }

Arabic text is shaped right-to-left with RAQM (libraqm) and drawn with the bundled Tajawal font
(Arabic + Latin + Arabic-Indic digits); system fonts are the fallback.
"""
import glob
import io
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, features

from app.core.errors import AppError
from app.core.i18n import _

FORMATS = {
    "post_4x5": (1080, 1350),
    "post_1x1": (1080, 1080),
    "story_9x16": (1080, 1920),
    "landscape_16x9": (1920, 1080),
}
ASPECT_OF = {"post_4x5": "4:5", "post_1x1": "1:1", "story_9x16": "9:16", "landscape_16x9": "16:9"}
VIDEO_EXT = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm", "video/x-matroska": ".mkv"}

RTL_RE = re.compile("[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufefc]")

BUNDLED_FONTS = Path(__file__).resolve().parent / "fonts"
# Fonts that draw Arabic *and* Latin, best first. Bundled Tajawal (OFL) comes first; an extra folder can be
# given with SAI_TEMPLATE_FONTS_DIR (e.g. to use Cairo or Noto Kufi), then the usual system folders.
FONT_CANDIDATES = {
    True: ["Tajawal-Bold.ttf", "Cairo-Bold.ttf", "NotoKufiArabic-Bold.ttf", "NotoSansArabicUI-Bold.ttf",
           "DejaVuSans-Bold.ttf", "FreeSansBold.ttf", "arialbd.ttf"],
    False: ["Tajawal-Regular.ttf", "Cairo-Regular.ttf", "NotoKufiArabic-Regular.ttf", "NotoSansArabicUI-Regular.ttf",
            "DejaVuSans.ttf", "FreeSans.ttf", "arial.ttf"],
}
_FONT_CACHE: dict = {}


class FrameError(AppError):
    """A file that cannot be framed (not an image, ffmpeg missing or failing…)."""


def _font_dirs() -> list[str]:
    dirs = [str(BUNDLED_FONTS)]
    if os.environ.get("SAI_TEMPLATE_FONTS_DIR"):
        dirs.insert(0, os.environ["SAI_TEMPLATE_FONTS_DIR"])
    return dirs + ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
                   os.path.expanduser("~/.local/share/fonts"), "/Library/Fonts", "C:/Windows/Fonts"]


# ---------------------------------------------------------------------------- helpers
def has_raqm() -> bool:
    try:
        return bool(features.check("raqm"))
    except (ValueError, OSError):  # pragma: no cover - very old Pillow
        return False


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def is_rtl(text: str | None) -> bool:
    return bool(RTL_RE.search(text or ""))


def font_path(bold: bool = True) -> str | None:
    """Path of a TrueType font that can draw Arabic (``None``: Pillow's built-in font)."""
    key = bool(bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    found = None
    for name in FONT_CANDIDATES[key] + FONT_CANDIDATES[not key]:
        for folder in _font_dirs():
            direct = os.path.join(folder, name)
            hits = [direct] if os.path.isfile(direct) else glob.glob(os.path.join(folder, "**", name), recursive=True)
            if hits:
                found = hits[0]
                break
        if found:
            break
    _FONT_CACHE[key] = found
    return found


def load_font(size: int, bold: bool = True):
    path = font_path(bold)
    if path:
        engine = ImageFont.Layout.RAQM if has_raqm() else ImageFont.Layout.BASIC
        try:
            return ImageFont.truetype(path, size, layout_engine=engine)
        except OSError:
            pass
    return ImageFont.load_default(size)


def hex_color(color: str | None, default=(17, 17, 17)) -> tuple[int, int, int]:
    value = (color or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except (ValueError, IndexError):
        return default


def open_image(content: bytes) -> Image.Image:
    """Open JPEG/PNG/WebP/… bytes, applying the EXIF rotation."""
    try:
        image = Image.open(io.BytesIO(content))
        image.load()
    except Exception as exc:
        raise FrameError(_("This file is not an image we can read."), code="bad_image") from exc
    return ImageOps.exif_transpose(image)


def to_jpeg(image: Image.Image, max_side: int | None = None, quality: int = 90) -> bytes:
    image = image.convert("RGB")
    if max_side:
        image.thumbnail((max_side, max_side), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def to_png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def box_px(box, width: int, height: int) -> tuple[int, int, int, int]:
    """(x, y, w, h) in % → integer pixel box clamped to the canvas, at least 1 px."""
    x, y, w, h = [float(v or 0) for v in box]
    left = max(0, min(width - 1, round(width * x / 100.0)))
    top = max(0, min(height - 1, round(height * y / 100.0)))
    right = max(left + 1, min(width, round(width * (x + w) / 100.0)))
    bottom = max(top + 1, min(height, round(height * (y + h) / 100.0)))
    return left, top, right - left, bottom - top


# ---------------------------------------------------------------------------- frame analysis
def detect_window(frame_content: bytes, threshold: int = 128, grid: int = 200) -> dict:
    """Find the largest transparent area of a PNG frame.

    Returns ``{"box": (x, y, w, h) in %, "size": (w, h), "transparent": bool}``. The search runs on a small
    copy (connected regions of transparent pixels), then the winner's edges are refined on the full alpha.
    """
    image = open_image(frame_content)
    width, height = image.size
    if "A" not in image.getbands() and not (image.mode == "P" and "transparency" in image.info):
        return {"box": (0.0, 0.0, 100.0, 100.0), "size": (width, height), "transparent": False}
    alpha = image.convert("RGBA").getchannel("A")
    mask = alpha.point(lambda a: 255 if a < threshold else 0)
    if not mask.getbbox():
        return {"box": (0.0, 0.0, 100.0, 100.0), "size": (width, height), "transparent": False}
    scale = min(1.0, grid / float(max(width, height)))
    small_w, small_h = max(1, int(width * scale)), max(1, int(height * scale))
    small = mask.resize((small_w, small_h), Image.NEAREST)
    pixels = small.load()
    seen = bytearray(small_w * small_h)
    best = None  # (area, x0, y0, x1, y1)
    for sy in range(small_h):
        for sx in range(small_w):
            index = sy * small_w + sx
            if seen[index] or not pixels[sx, sy]:
                continue
            stack = [(sx, sy)]
            seen[index] = 1
            area, x0, y0, x1, y1 = 0, sx, sy, sx, sy
            while stack:
                cx, cy = stack.pop()
                area += 1
                x0, y0, x1, y1 = min(x0, cx), min(y0, cy), max(x1, cx), max(y1, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < small_w and 0 <= ny < small_h:
                        n_index = ny * small_w + nx
                        if not seen[n_index] and pixels[nx, ny]:
                            seen[n_index] = 1
                            stack.append((nx, ny))
            if not best or area > best[0]:
                best = (area, x0, y0, x1, y1)
    if best is None:  # the transparent area vanished at the small scale (a few thin pixels)
        left, top, right, bottom = mask.getbbox()
    else:
        _area, x0, y0, x1, y1 = best
        # back to full size, one grid cell of margin, then the exact edges from the full alpha channel
        cell = 1.0 / scale
        region = (max(0, int((x0 - 1) * cell)), max(0, int((y0 - 1) * cell)),
                  min(width, int((x1 + 2) * cell) + 1), min(height, int((y1 + 2) * cell) + 1))
        exact = mask.crop(region).getbbox()
        if exact:
            left, top = region[0] + exact[0], region[1] + exact[1]
            right, bottom = region[0] + exact[2], region[1] + exact[3]
        else:  # pragma: no cover - defensive
            left, top, right, bottom = region
    pct = (round(100.0 * left / width, 2), round(100.0 * top / height, 2),
           round(100.0 * (right - left) / width, 2), round(100.0 * (bottom - top) / height, 2))
    return {"box": pct, "size": (width, height), "transparent": True}


def guess_format(width: int, height: int) -> str:
    """The template format whose aspect ratio is closest to ``width``×``height``."""
    ratio = width / float(height or 1)
    return min(FORMATS, key=lambda key: abs(FORMATS[key][0] / float(FORMATS[key][1]) - ratio))


# ---------------------------------------------------------------------------- photo placement
def _focus(image: Image.Image) -> tuple[float, float]:
    """Where the interesting part of a photo is (0-1, 0-1): the centre of its detail."""
    small = image.convert("L")
    small.thumbnail((64, 64))
    edges = small.filter(ImageFilter.FIND_EDGES)
    w, h = edges.size
    data = edges.load()
    total = sx = sy = 0.0
    for y in range(1, h - 1):  # the outer pixels of FIND_EDGES are noise
        for x in range(1, w - 1):
            value = data[x, y]
            if value > 24:
                total += value
                sx += value * x
                sy += value * y
    if not total:
        return 0.5, 0.45
    fx, fy = sx / total / max(1, w - 1), sy / total / max(1, h - 1)
    # stay near the middle: a centred crop is right most of the time
    return 0.5 + (fx - 0.5) * 0.6, 0.45 + (fy - 0.45) * 0.6


def place_photo(photo: Image.Image, size: tuple[int, int], fit: str = "cover") -> Image.Image:
    """The photo resized to ``size``: ``cover`` crops around the detail, ``contain`` keeps it whole over a
    blurred copy of itself."""
    photo = photo.convert("RGB")
    if fit == "contain":
        background = ImageOps.fit(photo, size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(max(8, size[0] // 25)))
        front = ImageOps.contain(photo, size, Image.LANCZOS)
        background.paste(front, ((size[0] - front.width) // 2, (size[1] - front.height) // 2))
        return background
    return ImageOps.fit(photo, size, Image.LANCZOS, centering=_focus(photo))


# ---------------------------------------------------------------------------- text
def _direction(rtl: bool) -> dict:
    return {"direction": "rtl", "language": "ar"} if rtl and has_raqm() else {}


def _measure(draw: ImageDraw.ImageDraw, text: str, font, rtl: bool):
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font, **_direction(rtl))
    except (KeyError, ValueError, OSError):
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top, left, top


def _wrap(draw, text: str, font, max_width: int, rtl: bool) -> list[str]:
    lines = []
    for paragraph in (text or "").splitlines() or [""]:
        words, line = paragraph.split(), ""
        for word in words:
            candidate = (line + " " + word).strip()
            # punctuation (— : !) never starts a line
            if line and any(c.isalnum() for c in word) and _measure(draw, candidate, font, rtl)[0] > max_width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return [line for line in lines if line.strip()] or [""]


def _layout_text(draw, text: str, spec: dict, box, rtl: bool):
    """Largest font size (≤ the template's) whose wrapped lines fit the box and the line limit."""
    _x, _y, w, h = box
    max_lines = max(1, int(spec.get("max_lines") or 2))
    size = max(10, int(spec.get("size") or 64))
    while True:
        font = load_font(size, spec.get("bold", True))
        lines = _wrap(draw, text, font, w, rtl)
        line_h = int(size * 1.35)
        widths = [_measure(draw, line, font, rtl)[0] for line in lines]
        if (len(lines) <= max_lines and line_h * len(lines) <= h and max(widths or [0]) <= w) or size <= 12:
            return font, lines[:max_lines], line_h, size
        size = int(size * 0.9)


def draw_text(canvas: Image.Image, text: str | None, spec: dict) -> Image.Image:
    """Draw ``text`` inside the template's text zone. Arabic is shaped right-to-left (RAQM)."""
    text = unicodedata.normalize("NFC", (text or "").strip())
    if not text:
        return canvas
    width, height = canvas.size
    box = box_px((spec.get("x"), spec.get("y"), spec.get("w"), spec.get("h")), width, height)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    rtl = is_rtl(text)
    font, lines, line_h, size = _layout_text(draw, text, spec, box, rtl)
    color = hex_color(spec.get("color"), (255, 255, 255))
    align = spec.get("align") or "auto"
    if align == "auto":
        align = "right" if rtl else "left"
    block_h = line_h * len(lines)
    top = box[1] + max(0, (box[3] - block_h) // 2)
    widths = [_measure(draw, line, font, rtl)[0] for line in lines]
    background = spec.get("background")
    if background:
        pad = max(8, size // 3)
        block_w = max(widths or [0])
        if align == "center":
            left = box[0] + (box[2] - block_w) // 2
        elif align == "right":
            left = box[0] + box[2] - block_w
        else:
            left = box[0]
        draw.rounded_rectangle((left - pad, top - pad // 2, left + block_w + pad, top + block_h + pad // 2),
                               radius=pad, fill=hex_color(background) + (235,))
    for index, line in enumerate(lines):
        line_w, _lh, off_x, _off_y = _measure(draw, line, font, rtl)
        if align == "center":
            x = box[0] + (box[2] - line_w) // 2
        elif align == "right":
            x = box[0] + box[2] - line_w
        else:
            x = box[0]
        middle = top + index * line_h + line_h // 2
        try:
            draw.text((x - off_x, middle), line, font=font, fill=color + (255,), anchor="lm", **_direction(rtl))
        except (KeyError, ValueError, OSError):
            draw.text((x - off_x, middle), line, font=font, fill=color + (255,), anchor="lm")
    canvas.alpha_composite(layer)
    return canvas


# ---------------------------------------------------------------------------- composition
def _paste_logo(canvas: Image.Image, logo: dict | None) -> Image.Image:
    if not logo or not logo.get("content"):
        return canvas
    try:
        image = open_image(logo["content"]).convert("RGBA")
    except FrameError:
        return canvas
    width, height = canvas.size
    target = max(16, int(width * float(logo.get("size") or 16) / 100.0))
    image = ImageOps.contain(image, (target, target), Image.LANCZOS)
    margin = int(min(width, height) * 0.04)
    position = logo.get("position") or "top_right"
    x = margin if position.endswith("left") else width - image.width - margin
    y = margin if position.startswith("top") else height - image.height - margin
    canvas.alpha_composite(image, (x, y))
    return canvas


def overlay(spec: dict, text: str | None = None) -> Image.Image:
    """Everything that sits *over* the photo — frame, logo, text — on a transparent canvas."""
    width, height = spec["width"], spec["height"]
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if spec.get("frame"):
        frame = open_image(spec["frame"]).convert("RGBA")
        if frame.size != (width, height):
            frame = ImageOps.fit(frame, (width, height), Image.LANCZOS)
        canvas.alpha_composite(frame)
    _paste_logo(canvas, spec.get("logo"))
    if spec.get("text"):
        value = text if text is not None else spec["text"].get("default")
        draw_text(canvas, value, spec["text"])
    return canvas


def compose_image(spec: dict, photo: Image.Image | None, text: str | None = None) -> Image.Image:
    """The framed picture (RGBA) at the canvas size. ``photo`` may be None (frame only)."""
    width, height = spec["width"], spec["height"]
    canvas = Image.new("RGBA", (width, height), hex_color(spec.get("background")) + (255,))
    x, y, w, h = box_px(spec.get("box") or (0, 0, 100, 100), width, height)
    if photo is not None:
        canvas.paste(place_photo(photo, (w, h), spec.get("fit") or "cover"), (x, y))
    canvas.alpha_composite(overlay(spec, text))
    return canvas


def compose(spec: dict, photo_bytes: bytes, text: str | None = None, fmt: str = "JPEG") -> bytes:
    """Frame a photo. Returns JPEG bytes (the only image format Instagram's API accepts) or PNG."""
    image = compose_image(spec, open_image(photo_bytes), text).convert("RGB")
    if fmt.upper() in ("JPEG", "JPG"):
        return to_jpeg(image, quality=92)
    return to_png(image)


def sample_photo(width: int = 1200, height: int = 1200) -> Image.Image:
    """A neutral placeholder photo (soft gradient, sun and hills) for template previews."""
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for row in range(height):
        t = row / float(height)
        draw.line([(0, row), (width, row)], fill=(int(150 + 70 * t), int(180 + 40 * t), int(210 - 30 * t)))
    radius = min(width, height) * 0.1
    draw.ellipse((width * 0.68 - radius, height * 0.26 - radius, width * 0.68 + radius, height * 0.26 + radius),
                 fill=(255, 236, 179))
    draw.polygon([(0, height * 0.72), (width * 0.35, height * 0.45), (width * 0.7, height * 0.74), (0, height)],
                 fill=(92, 128, 108))
    draw.polygon([(width * 0.3, height), (width * 0.72, height * 0.52), (width, height * 0.7), (width, height)],
                 fill=(64, 98, 86))
    return image


def preview(spec: dict, text: str | None = None, photo: Image.Image | None = None, max_side: int = 720) -> bytes:
    """A small JPEG of the template with a sample (or the given) photo."""
    image = compose_image(spec, photo if photo is not None else sample_photo(), text)
    return to_jpeg(image, max_side=max_side, quality=84)


# ---------------------------------------------------------------------------- video
def _run(args: list[str], timeout: int = 900) -> None:
    try:
        subprocess.run(args, check=True, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise FrameError(_("Framing a video needs ffmpeg on the server."), code="no_ffmpeg") from exc
    except subprocess.TimeoutExpired as exc:
        raise FrameError(_("Processing the video took too long."), code="ffmpeg_timeout") from exc
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or b"").decode(errors="ignore").strip().splitlines()[-1:] or ["unknown error"]
        raise FrameError(_("The video could not be processed: {error}", error=tail[0][:300]),
                         code="ffmpeg_failed") from exc


def _even(value: float) -> int:
    return max(2, int(value) // 2 * 2)


def video_poster(content: bytes, mimetype: str, at: float = 0.5) -> bytes:
    """A frame of a video as PNG bytes (for previews)."""
    if not ffmpeg_available():
        raise FrameError(_("Framing a video needs ffmpeg on the server."), code="no_ffmpeg")
    with tempfile.TemporaryDirectory(prefix="sai_tpl_") as tmp:
        src = os.path.join(tmp, "in" + VIDEO_EXT.get(mimetype, ".mp4"))
        out = os.path.join(tmp, "poster.png")
        with open(src, "wb") as fh:
            fh.write(content)
        try:
            _run(["ffmpeg", "-y", "-ss", str(at), "-i", src, "-frames:v", "1", out], timeout=120)
            if not os.path.exists(out):
                raise FrameError("no frame", code="ffmpeg_failed")
        except FrameError:
            _run(["ffmpeg", "-y", "-i", src, "-frames:v", "1", out], timeout=120)
        with open(out, "rb") as fh:
            return fh.read()


def compose_video(spec: dict, video_bytes: bytes, mimetype: str, text: str | None = None, scale: float = 2 / 3.0,
                  max_seconds: int = 90) -> bytes:
    """Frame a video: the clip is scaled/cropped into the photo window and the frame (with logo and text) is
    laid over it. Returns MP4 bytes (H.264 + AAC, 720p-class)."""
    if not ffmpeg_available():
        raise FrameError(_("Framing a video needs ffmpeg on the server."), code="no_ffmpeg")
    width, height = _even(spec["width"] * scale), _even(spec["height"] * scale)
    x, y, w, h = box_px(spec.get("box") or (0, 0, 100, 100), width, height)
    w, h = _even(w), _even(h)
    over = overlay(spec, text)
    if over.size != (width, height):
        over = over.resize((width, height), Image.LANCZOS)
    bg = "0x{:02x}{:02x}{:02x}".format(*hex_color(spec.get("background")))
    with tempfile.TemporaryDirectory(prefix="sai_tpl_") as tmp:
        src = os.path.join(tmp, "in" + VIDEO_EXT.get(mimetype, ".mp4"))
        frame_path = os.path.join(tmp, "frame.png")
        out = os.path.join(tmp, "out.mp4")
        with open(src, "wb") as fh:
            fh.write(video_bytes)
        over.save(frame_path, "PNG")
        fill = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
        if (spec.get("fit") or "cover") == "contain":
            photo = (f"[0:v]split[s1][s2];[s1]{fill},boxblur=20:4[blur];"
                     f"[s2]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
                     "[blur][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[ph]")
        else:
            photo = f"[0:v]{fill},setsar=1[ph]"
        graph = (f"{photo};color=c={bg}:s={width}x{height}:r=30[bg];[bg][ph]overlay={x}:{y}:shortest=1[base];"
                 "[base][1:v]overlay=0:0:shortest=1,format=yuv420p[v]")
        _run(["ffmpeg", "-y", "-t", str(max_seconds), "-i", src, "-loop", "1", "-i", frame_path,
              "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-r", "30",
              "-c:a", "aac", "-shortest", "-movflags", "+faststart", out])
        with open(out, "rb") as fh:
            return fh.read()
