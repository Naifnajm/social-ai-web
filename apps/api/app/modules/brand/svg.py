"""Make an uploaded SVG safe to keep and show: no scripts, no event handlers, no external references.

    clean = svg.sanitize(content)      # bytes, or None when it is not an SVG we can read safely

Kept: shapes, paths, gradients, text, styles without external urls, internal ``#id`` references and embedded
raster images (``data:image/png|jpeg|gif|webp``). Dropped: <script>, <foreignObject>, frames and media elements,
``on*`` attributes, ``javascript:`` and any http(s)/file reference, ``@import``. A DOCTYPE or ENTITY makes the
whole file refused (entity expansion attacks). The served file still carries the sandbox CSP of uploads.

    png = svg.rasterize(content, 640, 640)   # PNG bytes fitted in 640×640 (transparent), or None
    svg.can_rasterize()                       # resvg-py (or cairosvg) is installed

Rasterizing always sanitizes first, caps the output at ``MAX_PX`` per side, refuses ``<use>`` fan-out bombs and
very large documents, and caches the last results in memory (keyed by content hash and size).
"""
import hashlib
import io
import re
import threading
import xml.etree.ElementTree as ET
from collections import OrderedDict

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
DROP_TAGS = {"script", "foreignobject", "iframe", "embed", "object", "audio", "video", "canvas", "handler",
             "listener", "set", "animate", "animatemotion", "animatetransform", "animatecolor", "a", "meta", "link",
             "base"}
SAFE_DATA = re.compile(r"^data:image/(png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=\s]+$", re.I)
URL_IN_CSS = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
MAX_SVG = 5 * 1024 * 1024
MAX_PX = 4096  # longest side of a rasterized SVG
MAX_ELEMENTS = 20000  # elements drawn after <use> expansion
CACHE_SIZE = 64

ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def _safe_ref(value: str) -> bool:
    value = (value or "").strip()
    return value.startswith("#") or bool(SAFE_DATA.match(value))


def _safe_css(value: str) -> str | None:
    lowered = (value or "").lower()
    if "@import" in lowered or "javascript:" in lowered or "expression(" in lowered or "behavior:" in lowered:
        return None
    for match in URL_IN_CSS.finditer(value or ""):
        if not _safe_ref(match.group(2)):
            return None
    return value


def _clean(element: ET.Element) -> None:
    for child in list(element):
        tag = _local(child.tag) if isinstance(child.tag, str) else ""
        if not tag or tag in DROP_TAGS:  # comments / processing instructions have a non-string tag
            element.remove(child)
            continue
        if tag == "style":
            if child.text and _safe_css(child.text) is None:
                element.remove(child)
                continue
        _clean(child)
    for name in list(element.attrib):
        local, value = _local(name), element.attrib[name]
        if local.startswith("on") or "javascript:" in value.lower().replace(" ", ""):
            del element.attrib[name]
        elif local in ("href", "src", "action", "formaction"):
            if not _safe_ref(value):
                del element.attrib[name]
        elif local == "style" or "url(" in value.lower():
            if _safe_css(value) is None:
                del element.attrib[name]


def sanitize(content: bytes) -> bytes | None:
    if not content or len(content) > MAX_SVG:
        return None
    head = content[:4096].lower()
    if b"<!doctype" in content.lower() or b"<!entity" in head or b"<!entity" in content.lower():
        return None
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None
    if _local(root.tag) != "svg":
        return None
    _clean(root)
    for name in list(root.attrib):
        if _local(name).startswith("on"):
            del root.attrib[name]
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8", xml_declaration=False)


def is_light(content: bytes) -> bool | None:
    """Rough guess whether an SVG logo is drawn in light colours (white logo for dark backgrounds)."""
    text = content.decode("utf-8", "ignore").lower()
    fills = re.findall(r"(?:fill|stroke|color)\s*[:=]\s*['\"]?\s*(#[0-9a-f]{3,6}|white|black)", text)
    if not fills:
        return None
    light = sum(1 for f in fills if f in ("white", "#fff", "#ffffff") or (f.startswith("#") and _bright(f)))
    return light > len(fills) / 2


def _bright(value: str) -> bool:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        return False
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) > 200


def intrinsic_size(content: bytes) -> tuple[int | None, int | None]:
    """The drawing size an SVG declares (width/height, else the viewBox), rounded to pixels."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None, None

    def number(value: str | None) -> float | None:
        match = re.match(r"^\s*([0-9.]+)\s*(px)?\s*$", value or "")
        return float(match.group(1)) if match else None

    width, height = number(root.attrib.get("width")), number(root.attrib.get("height"))
    box = re.split(r"[\s,]+", (root.attrib.get("viewBox") or "").strip())
    if (width is None or height is None) and len(box) == 4:
        try:
            box_w, box_h = float(box[2]), float(box[3])
        except ValueError:
            box_w = box_h = 0
        if box_w > 0 and box_h > 0:
            width = width or (height * box_w / box_h if height else box_w)
            height = height or width * box_h / box_w
    if not width or not height:
        return None, None
    return max(1, round(width)), max(1, round(height))


# ---------------------------------------------------------------------------- rasterizing
def is_svg(content: bytes | None, mimetype: str | None = None, filename: str | None = None) -> bool:
    """Whether the bytes are an SVG document (by type, name or content)."""
    if (mimetype or "").split(";")[0].strip().lower() == "image/svg+xml":
        return True
    if (filename or "").lower().endswith(".svg"):
        return True
    head = (content or b"")[:2048].lstrip().lower()
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head)


def renderer() -> str | None:
    """The SVG rasterizer available here: "resvg", "cairosvg" or None."""
    try:
        import resvg_py  # noqa: F401
        return "resvg"
    except ImportError:
        pass
    try:  # pragma: no cover - only when resvg-py is missing
        import cairosvg  # noqa: F401
        return "cairosvg"
    except Exception:  # cairosvg raises OSError when libcairo is missing
        return None


def can_rasterize() -> bool:
    return renderer() is not None


def _expanded_size(root: ET.Element) -> int:
    """How many elements the drawing has once every ``<use>`` is expanded (a cheap guard against use bombs)."""
    by_id = {el.attrib["id"]: el for el in root.iter() if "id" in el.attrib}
    memo: dict[int, int] = {}

    def size(el: ET.Element, depth: int = 0) -> int:
        key = id(el)
        if key in memo:
            return memo[key]
        if depth > 32:
            return MAX_ELEMENTS + 1
        total = 1
        for child in el.iter():
            if child is el:
                continue
            total += 1
            if _local(child.tag if isinstance(child.tag, str) else "") == "use":
                ref = next((v for k, v in child.attrib.items() if _local(k) == "href"), "")
                target = by_id.get(ref[1:]) if ref.startswith("#") else None
                if target is not None:
                    total += size(target, depth + 1)
            if total > MAX_ELEMENTS:
                break
        memo[key] = total
        return total

    return size(root)


_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()


def _render(clean: bytes, width: int, height: int) -> bytes | None:
    engine = renderer()
    if engine == "resvg":
        import resvg_py
        return resvg_py.svg_to_bytes(svg_string=clean.decode("utf-8"), width=width, height=height)
    if engine == "cairosvg":  # pragma: no cover - fallback
        import cairosvg
        from PIL import Image, ImageOps
        png = cairosvg.svg2png(bytestring=clean, output_width=width, unsafe=False)
        with Image.open(io.BytesIO(png)) as image:  # cairosvg keeps the aspect from the width only: fit the box
            fitted = ImageOps.contain(image.convert("RGBA"), (width, height))
            out = io.BytesIO()
            fitted.save(out, "PNG")
            return out.getvalue()
    return None


def rasterize(content: bytes, width: int = 1024, height: int | None = None) -> bytes | None:
    """PNG bytes of the SVG fitted inside ``width``×``height`` (aspect kept, transparent background), or None when
    it is not a safe SVG, too complex, or no rasterizer is installed. The SVG is sanitized first."""
    if not content or not can_rasterize():
        return None
    width = max(1, min(MAX_PX, int(width or 1024)))
    height = max(1, min(MAX_PX, int(height or width)))
    key = (hashlib.sha256(content).hexdigest(), width, height)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    clean = sanitize(content)
    png = None
    if clean is not None:
        try:
            if _expanded_size(ET.fromstring(clean)) <= MAX_ELEMENTS:
                png = _render(clean, width, height)
        except Exception:  # invalid geometry, a zero-size result, a renderer error
            png = None
    with _lock:
        _cache[key] = png
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return png
