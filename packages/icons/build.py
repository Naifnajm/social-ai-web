"""Build packages/icons/icons.json: semantic icon keys -> Solar icon SVG bodies (24x24), "linear" and "duo".

Solar icon set by 480 Design (CC BY 4.0). Source: npm pack @iconify-json/solar@1.2.16 (later versions may redraw a few icons)
Usage: python3 packages/icons/build.py path/to/package/icons.json
       cp packages/icons/icons.json apps/web/src/components/icons.json   # the web app's copy
To add an icon: add "key": "solar-name" to MAP (and to DUO for a bold-duotone variant), then rebuild and copy.
Never edit the web copy by hand: `node apps/web/scripts/check-icons.mjs` checks that it matches and that every
icon name used in the web app and the API exists here.
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
    # UI
    "add_circle": "add-circle", "business_center": "case", "menu": "hamburger-menu", "help": "question-circle",
    # camera panel (apps/api/app/modules/ai/camera.py: GROUPS, PRESETS, GROUP_ICONS)
    "360": "refresh-circle", "3d_rotation": "camera-rotate", "ac_unit": "snowflake",
    "accessibility_new": "user-hand-up", "animation": "videocamera-record", "arrow_forward": "arrow-right",
    "back_hand": "hand", "blur_circular": "circle-dot-dashed", "blur_on": "radial-blur", "brightness_7": "sun",
    "camera": "camera-minimalistic", "camera_enhance": "camera-square", "camera_roll": "reel",
    "center_focus_strong": "target", "change_history": "face-scan-circle", "cloud": "cloud",
    "colorize": "pipette", "contrast": "contrast", "crop_3_2": "crop-minimalistic", "crop_free": "crop",
    "crop_portrait": "face-scan-square", "dark_mode": "moon", "deblur": "circle-dot",
    "directions_walk": "walking", "face": "user-circle", "filter_b_and_w": "filters",
    "filter_center_focus": "magnifer-bug", "flash_on": "flashlight-on", "flight": "airplane",
    "grid_view": "widget", "height": "arrow-up-from-line", "highlight": "flashlight", "inventory_2": "box",
    "landscape": "mountains", "lens_blur": "circle-dashed", "light": "lamp", "light_mode": "sun-2",
    "local_cafe": "cup-hot", "local_fire_department": "fire", "location_city": "city", "motion_blur": "wind",
    "nature": "leaf", "nightlife": "lightbulb-bolt", "nights_stay": "moon-stars", "north": "arrow-up",
    "panorama_wide_angle": "panorama", "pause_circle": "pause-circle", "photo_camera": "camera",
    "portrait": "user-rounded", "radio_button_checked": "record-circle", "receipt_long": "bill-list",
    "restaurant": "chef-hat", "rotate_right": "rotate-clockwise", "savings": "money-bag",
    "shield": "shield-check", "shutter_speed": "stopwatch", "south": "arrow-down",
    "sports_motorsports": "running", "street_view": "streets", "swap_horiz": "transfer-horizontal",
    "swap_vert": "transfer-vertical", "timelapse": "hourglass", "toll": "wallet-money", "tune": "tuning-2",
    "videocam": "videocamera", "visibility_lock": "eye-scan", "wb_sunny": "sun", "wb_twilight": "sunset",
    "window": "window-frame", "zoom_in": "magnifer-zoom-in", "zoom_in_map": "maximize-square",
    "zoom_out": "magnifer-zoom-out",
}
DUO = ["text_fields", "wand_stars", "upload", "image", "movie", "mic", "call_merge", "brush", "send",
       "campaign", "visibility", "favorite", "percent", "play_circle", "add", "format_quote", "music_note",
       "account_tree", "error", "link_off", "event_upcoming", "rocket_launch", "schedule", "sync_alt",
       "lightbulb", "trophy", "key", "show_chart", "tag", "aspect_ratio", "subtitles", "verified_user",
       "forum", "smart_toy", "photo_frame", "recycle", "photo_library", "description", "shopping_cart", "storefront",
       "bolt", "smartphone", "chat", "menu_book", "trending_up", "auto_awesome", "flag", "mood", "mood_bad", "inbox",
       "360", "3d_rotation", "ac_unit", "accessibility_new", "animation", "arrow_forward", "back_hand",
       "blur_circular", "blur_on", "brightness_7", "camera", "camera_enhance", "camera_roll",
       "center_focus_strong", "change_history", "cloud", "colorize", "contrast", "crop_3_2", "crop_free",
       "crop_portrait", "dark_mode", "deblur", "directions_walk", "face", "filter_b_and_w",
       "filter_center_focus", "flash_on", "flight", "grid_view", "height", "highlight", "inventory_2",
       "landscape", "lens_blur", "light", "light_mode", "local_cafe", "local_fire_department", "location_city",
       "motion_blur", "nature", "nightlife", "nights_stay", "north", "panorama_wide_angle", "pause_circle",
       "photo_camera", "portrait", "radio_button_checked", "receipt_long", "restaurant", "rotate_right",
       "savings", "shield", "shutter_speed", "south", "sports_motorsports", "street_view", "swap_horiz",
       "swap_vert", "timelapse", "toll", "tune", "videocam", "visibility_lock", "wb_sunny", "wb_twilight",
       "window", "zoom_in", "zoom_in_map", "zoom_out", "add_circle", "business_center"]


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
