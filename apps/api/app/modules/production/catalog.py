"""Block kinds, typed ports and board templates of Production."""
from app.core.i18n import _, lazy

KINDS = ("text", "llm", "upload", "image", "video", "audio", "merge", "design", "template", "reframe", "captions",
         "approval", "post")
KIND_LABELS = {
    "text": lazy("Text"), "llm": lazy("AI writer"), "upload": lazy("Upload"), "image": lazy("Image"),
    "video": lazy("Video"), "audio": lazy("Voice & sound"), "merge": lazy("Composition"), "design": lazy("Design"),
    "template": lazy("Template"), "reframe": lazy("Formats"), "captions": lazy("Captions"),
    "approval": lazy("Approval"), "post": lazy("Post"),
}
# What each block produces ("media" = depends on the file / the inputs).
OUTPUT = {"text": "text", "llm": "text", "upload": "media", "image": "image", "video": "video", "audio": "audio",
          "merge": "video", "design": "image", "post": None, "reframe": "media", "captions": "video",
          "approval": "media", "template": "image"}
# Named input ports per block: (key, label, accepted types, accepts several links)
PORTS: dict[str, list[tuple[str, str, frozenset, bool]]] = {
    "text": [], "upload": [],
    "llm": [("text", lazy("Text in"), frozenset({"text"}), True)],
    "image": [("prompt", lazy("Prompt"), frozenset({"text"}), True),
              ("images", lazy("Reference images"), frozenset({"image"}), True)],
    "video": [("prompt", lazy("Prompt"), frozenset({"text"}), True),
              ("first_frame", lazy("Start image"), frozenset({"image"}), False)],
    "audio": [("script", lazy("Script / prompt"), frozenset({"text"}), True)],
    "merge": [("visual", lazy("Video or image"), frozenset({"image", "video"}), False),
              ("tracks", lazy("Audio tracks"), frozenset({"audio"}), True)],
    "design": [("background", lazy("Background"), frozenset({"image"}), False),
               ("headline", lazy("Headline"), frozenset({"text"}), True)],
    "post": [("caption", lazy("Caption"), frozenset({"text"}), True),
             ("media", lazy("Media"), frozenset({"image", "video", "audio"}), True)],
    "reframe": [("media", lazy("Image or video"), frozenset({"image", "video"}), False)],
    "captions": [("video", lazy("Video"), frozenset({"video"}), False),
                 ("speech", lazy("Speech (optional)"), frozenset({"audio"}), False)],
    "approval": [("content", lazy("Content to review"), frozenset({"text", "image", "video", "audio"}), True)],
    "template": [("photo", lazy("Photo"), frozenset({"image"}), False),
                 ("text", lazy("Template text (optional)"), frozenset({"text"}), True)],
}
ACCEPTS = {kind: frozenset().union(*(p[2] for p in ports)) if ports else frozenset() for kind, ports in PORTS.items()}
CAPABILITY = {"llm": "text", "image": "image", "video": "video", "audio": "audio"}
NODE_STATES = ("idle", "queued", "running", "waiting", "done", "failed")
BUSY_STATES = ("queued", "running")
STYLES = ("photo", "illustration", "3d", "minimal", "cinematic", "product")
AUDIO_MODES = ("speech", "sfx", "music")
PUBLISH_MODES = ("draft", "now", "best", "at")
FORMATS = ("9:16", "4:5", "1:1", "16:9")
# parameters that change the result of a block (unchanged blocks reuse their result for free)
HASH_FIELDS = ("kind", "text_value", "aspect", "style", "seconds", "audio_mode", "variations", "formats", "fit_mode",
               "caption_position", "caption_size", "caption_language", "publish_mode", "publish_at", "design",
               "template_ref")
# preferred formats per network, best first
NETWORK_FORMATS = {
    "instagram": ("4:5", "1:1", "9:16"), "facebook": ("4:5", "1:1", "16:9", "9:16"), "threads": ("4:5", "1:1"),
    "tiktok": ("9:16",), "x": ("16:9", "1:1"), "linkedin": ("1:1", "4:5", "16:9"), "telegram": ("16:9", "1:1", "4:5"),
    "pinterest": ("9:16", "4:5", "1:1"), "google_business": ("4:5", "1:1", "16:9"),
}
NETWORK_VIDEO_FORMATS = {"instagram": ("9:16", "4:5"), "facebook": ("9:16", "4:5", "16:9"), "tiktok": ("9:16",),
                         "youtube": ("16:9", "9:16")}


def kind_label(kind: str) -> str:
    return _(KIND_LABELS.get(kind, kind))


def kinds_payload() -> list[dict]:
    return [{"key": kind, "label": kind_label(kind), "output": OUTPUT[kind], "accepts": sorted(ACCEPTS[kind]),
             "generative": kind in CAPABILITY,
             "ports": [{"key": key, "label": _(label), "accepts": sorted(types), "multi": multi}
                       for key, label, types, multi in PORTS[kind]]}
            for kind in KINDS]


# ---------------------------------------------------------------------------- board templates
def templates() -> dict[str, dict]:
    """Ready-made boards. Texts are translated in the user's language (they become the blocks' content)."""
    return {
        "blank": {"name": _("Blank board"), "icon": "add", "description": _("Start from an empty canvas."),
                  "nodes": [], "edges": []},
        "product_ad": {
            "name": _("Product video ad"), "icon": "movie",
            "description": _("Image → animated video, AI voice-over + music, composed and sent to a post."),
            "nodes": [
                {"kind": "text", "name": _("Product idea"), "x": 40, "y": 60,
                 "text_value": _("A sleek self-order kiosk in a cozy restaurant, warm evening light")},
                {"kind": "image", "name": _("Hero image"), "x": 360, "y": 40, "aspect": "9:16", "style": "product"},
                {"kind": "video", "name": _("Animate it"), "x": 680, "y": 40, "aspect": "9:16", "seconds": 8,
                 "prompt": _("Slow cinematic dolly-in, soft light flicker, customers in the background")},
                {"kind": "llm", "name": _("Voice-over script"), "x": 360, "y": 380,
                 "prompt": _("Write a 15-second energetic voice-over script (max 40 words) for this product.")},
                {"kind": "audio", "name": _("Voice-over"), "x": 680, "y": 380, "audio_mode": "speech"},
                {"kind": "merge", "name": _("Final video"), "x": 1000, "y": 200, "aspect": "9:16"},
                {"kind": "post", "name": _("Post"), "x": 1300, "y": 200},
                {"kind": "audio", "name": _("Music bed"), "x": 680, "y": 590, "audio_mode": "music", "seconds": 10,
                 "prompt": _("Warm upbeat acoustic background music")},
            ],
            "edges": [(0, 1), (1, 2), (0, 3), (3, 4), (2, 5), (4, 5), (7, 5), (5, 6), (3, 6)],
        },
        "quote_card": {
            "name": _("Branded quote card"), "icon": "format_quote",
            "description": _("AI background + headline in your brand design, ready for Instagram."),
            "nodes": [
                {"kind": "text", "name": _("Topic"), "x": 40, "y": 80,
                 "text_value": _("Why restaurants switch to self-ordering")},
                {"kind": "llm", "name": _("Headline"), "x": 360, "y": 260,
                 "prompt": _("Write one punchy headline (max 8 words) about this topic.")},
                {"kind": "image", "name": _("Background"), "x": 360, "y": 20, "aspect": "4:5", "style": "minimal",
                 "prompt": _("Soft abstract background, lots of empty space for text")},
                {"kind": "design", "name": _("Card design"), "x": 700, "y": 120, "aspect": "4:5"},
                {"kind": "post", "name": _("Post"), "x": 1020, "y": 120},
            ],
            "edges": [(0, 1), (0, 2), (2, 3), (1, 3), (3, 4), (1, 4)],
        },
        "talking_slide": {
            "name": _("Narrated slide"), "icon": "mic",
            "description": _("Script → voice, image → slide video with the narration."),
            "nodes": [
                {"kind": "text", "name": _("Message"), "x": 40, "y": 120,
                 "text_value": _("Three tips to serve guests faster this weekend")},
                {"kind": "llm", "name": _("Narration"), "x": 360, "y": 260,
                 "prompt": _("Turn this into a warm 20-second narration (max 55 words).")},
                {"kind": "audio", "name": _("Voice"), "x": 680, "y": 260, "audio_mode": "speech"},
                {"kind": "image", "name": _("Slide visual"), "x": 360, "y": 20, "aspect": "1:1",
                 "style": "illustration"},
                {"kind": "merge", "name": _("Slide video"), "x": 1000, "y": 120, "aspect": "1:1"},
                {"kind": "post", "name": _("Post"), "x": 1300, "y": 120},
            ],
            "edges": [(0, 1), (1, 2), (0, 3), (3, 4), (2, 4), (4, 5), (1, 5)],
        },
        "music_reel": {
            "name": _("Reel with music"), "icon": "music_note",
            "description": _("Vertical video with an original AI soundtrack."),
            "nodes": [
                {"kind": "text", "name": _("Scene"), "x": 40, "y": 60,
                 "text_value": _("Barista pouring latte art in slow motion, morning sun")},
                {"kind": "video", "name": _("Clip"), "x": 360, "y": 20, "aspect": "9:16", "seconds": 8},
                {"kind": "audio", "name": _("Soundtrack"), "x": 360, "y": 320, "audio_mode": "music", "seconds": 10,
                 "prompt": _("Upbeat acoustic lo-fi, warm and positive")},
                {"kind": "merge", "name": _("Reel"), "x": 700, "y": 160, "aspect": "9:16"},
                {"kind": "post", "name": _("Post"), "x": 1000, "y": 160},
            ],
            "edges": [(0, 1), (1, 3), (2, 3), (3, 4)],
        },
    }
