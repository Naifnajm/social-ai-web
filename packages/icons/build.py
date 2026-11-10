"""Build packages/icons/icons.json: semantic icon keys -> Solar icon SVG bodies (24x24), "linear" and "duo".

Solar icon set by 480 Design (CC BY 4.0). Source: npm pack @iconify-json/solar
Usage: python3 packages/icons/build.py path/to/icons.json
To add an icon: add "key": "solar-name" to MAP (and to DUO for a bold-duotone variant), then rebuild.
"""
import json
import sys
from pathlib import Path

MAP = {
    "account_balance": "wallet", "account_tree": "routing-2", "add": "add-circle", "apps": "widget-5",
    "arrow_back": "arrow-left", "arrow_downward": "arrow-down", "arrow_upward": "arrow-up",
    "autorenew": "refresh", "bar_chart": "chart-2", "brush": "paint-brush", "calendar_today": "calendar",
    "call_merge": "layers", "campaign": "speaker", "check": "check-read", "check_circle": "check-circle",
    "close": "close-circle", "content_copy": "copy", "crop_landscape": "crop-minimalistic",
    "delete": "trash-bin-minimalistic", "download": "download-minimalistic", "east": "arrow-right",
    "edit_square": "pen-new-square", "error": "danger-circle", "event_upcoming": "calendar-mark",
    "expand_less": "alt-arrow-up", "expand_more": "alt-arrow-down", "fast_forward": "forward",
    "favorite": "heart", "flip_to_back": "square-bottom-down", "flip_to_front": "square-top-up",
    "format_align_left": "align-left", "format_align_center": "align-horizontal-center",
    "format_align_right": "align-right", "format_bold": "text-bold", "format_quote": "quote",
    "graphic_eq": "soundwave", "group": "users-group-rounded", "history": "history", "image": "gallery",
    "info": "info-circle", "key": "key-minimalistic", "lightbulb": "lightbulb-bolt", "link_off": "link-broken",
    "lock": "lock-keyhole-minimalistic", "mic": "microphone-3", "mode_comment": "chat-round-dots",
    "movie": "clapperboard-play", "music_note": "music-note-2", "open_in_new": "square-arrow-right-up",
    "palette": "palette", "payments": "wad-of-money", "percent": "sale", "play_arrow": "play",
    "play_circle": "play-circle", "progress_activity": "refresh", "refresh": "refresh",
    "remove": "minus-circle", "rocket_launch": "rocket-2", "save": "diskette", "schedule": "clock-circle",
    "send": "plain-2", "settings": "settings", "share": "share", "show_chart": "graph-up", "square": "stop",
    "sync_alt": "transfer-horizontal", "table": "list-check-minimalistic", "tag": "hashtag",
    "text_fields": "text-field", "title": "text", "trophy": "cup-star", "upload": "upload-minimalistic",
    "verified": "verified-check", "vertical_align_bottom": "align-bottom",
    "vertical_align_center": "align-vertical-center", "vertical_align_top": "align-top",
    "view_list": "list", "aspect_ratio": "monitor-smartphone", "subtitles": "subtitles",
    "verified_user": "shield-check", "undo": "undo-left-round", "redo": "undo-right-round",
    "select_group": "object-scan", "data_object": "code-square", "thumb_up": "like", "thumb_down": "dislike",
    "link": "link-minimalistic-2", "content_paste": "clipboard", "branding": "sticker-square",
    "outbox": "export", "forum": "chat-round-line", "reply": "reply", "smart_toy": "cpu-bolt", "person": "user",
    "support_agent": "user-speak-rounded", "mood": "smile-circle", "mood_bad": "sad-circle", "filter_list": "filter",
    "search": "magnifer", "push_pin": "pin", "archive": "archive", "flag": "flag", "mail": "letter",
    "photo_frame": "gallery-wide", "recycle": "restart", "photo_library": "folder-with-files",
    "description": "document-text", "shopping_cart": "cart-large-2", "storefront": "shop", "bolt": "bolt",
    "smartphone": "smartphone", "chat": "chat-square", "menu_book": "book-bookmark", "visibility_off": "eye-closed",
    "block": "forbidden-circle", "event_add": "calendar-add", "trending_up": "graph-new-up", "auto_awesome": "stars",
    "add_photo": "gallery-add", "inbox": "import", "group_off": "widget-add", "people_check": "user-check", "visibility": "eye", "wand_stars": "magic-stick-3", "warning": "danger-triangle",
}
DUO = ["text_fields", "wand_stars", "upload", "image", "movie", "mic", "call_merge", "brush", "send",
       "campaign", "visibility", "favorite", "percent", "play_circle", "add", "format_quote", "music_note",
       "account_tree", "error", "link_off", "event_upcoming", "rocket_launch", "schedule", "sync_alt",
       "lightbulb", "trophy", "key", "show_chart", "tag", "aspect_ratio", "subtitles", "verified_user",
       "forum", "smart_toy", "photo_frame", "recycle", "photo_library", "description", "shopping_cart", "storefront",
       "bolt", "smartphone", "chat", "menu_book", "trending_up", "auto_awesome", "flag", "mood", "mood_bad", "inbox"]


def main(source):
    data = json.loads(Path(source).read_text())
    icons = dict(data["icons"])
    for alias, spec in data.get("aliases", {}).items():
        if spec.get("parent") in data["icons"] and set(spec) <= {"parent"}:
            icons[alias] = data["icons"][spec["parent"]]
    out = {}
    for key, name in sorted(MAP.items()):
        entry = {"linear": icons[name + "-linear"]["body"]}
        if key in DUO and name + "-bold-duotone" in icons:
            entry["duo"] = icons[name + "-bold-duotone"]["body"]
        out[key] = entry
    target = Path(__file__).with_name("icons.json")
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(len(out), "icons ->", target)


if __name__ == "__main__":
    main(sys.argv[1])
