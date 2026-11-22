"""Make an uploaded SVG safe to keep and show: no scripts, no event handlers, no external references.

    clean = svg.sanitize(content)      # bytes, or None when it is not an SVG we can read safely

Kept: shapes, paths, gradients, text, styles without external urls, internal ``#id`` references and embedded
raster images (``data:image/png|jpeg|gif|webp``). Dropped: <script>, <foreignObject>, frames and media elements,
``on*`` attributes, ``javascript:`` and any http(s)/file reference, ``@import``. A DOCTYPE or ENTITY makes the
whole file refused (entity expansion attacks). The served file still carries the sandbox CSP of uploads.
"""
import re
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
DROP_TAGS = {"script", "foreignobject", "iframe", "embed", "object", "audio", "video", "canvas", "handler",
             "listener", "set", "animate", "animatemotion", "animatetransform", "animatecolor", "a", "meta", "link",
             "base"}
SAFE_DATA = re.compile(r"^data:image/(png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=\s]+$", re.I)
URL_IN_CSS = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
MAX_SVG = 5 * 1024 * 1024

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
