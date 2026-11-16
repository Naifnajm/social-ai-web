"""Camera settings for AI images and videos: shoot it as if with a real camera.

A "shot" is a small dict chosen with icons in the UI (or left on "auto" so the description decides):

    {"mode": "manual", "camera": "full_frame", "lens": "85", "aperture": "1.8", "angle": "low",
     "framing": "close_up", "light": "golden_hour", "light_dir": "back", "look": "warm", "movement": "push_in"}

``describe(shot, kind)`` turns it into the photography words image and video models understand
("Shot on a full-frame camera, 85mm portrait lens at f/1.8, shallow depth of field…"). Unknown keys and values
are dropped, "auto" adds nothing, and ``movement`` only applies to video.

    from app.modules.ai import camera
    camera.clean(data)                 # keep only known groups/values
    camera.describe(shot, "image")     # prompt sentence (empty for auto)
    camera.options()                   # groups, options and presets for the UI (translated)
"""
from app.core.i18n import _, lazy

# group -> option key -> (label, icon, prompt words). Icons are Material Symbols names.
GROUPS: dict[str, dict[str, tuple]] = {
    "camera": {
        "full_frame": (lazy("Full-frame camera"), "photo_camera", "shot on a full-frame mirrorless camera"),
        "medium_format": (lazy("Medium format"), "camera", "shot on a medium format camera, very fine detail"),
        "cinema": (lazy("Cinema camera"), "videocam", "shot on a digital cinema camera, cinematic dynamic range"),
        "film_35": (lazy("35mm film"), "camera_roll", "shot on 35mm film, natural film grain"),
        "phone": (lazy("Phone"), "smartphone", "shot on a modern smartphone, authentic social media look"),
        "drone": (lazy("Drone"), "flight", "aerial shot from a drone"),
        "action": (lazy("Action camera"), "sports_motorsports", "shot on a wide action camera"),
    },
    "lens": {
        "14": (lazy("14mm ultra-wide"), "panorama_wide_angle", "14mm ultra-wide lens, dramatic perspective"),
        "24": (lazy("24mm wide"), "landscape", "24mm wide-angle lens"),
        "35": (lazy("35mm"), "street_view", "35mm lens, natural documentary perspective"),
        "50": (lazy("50mm standard"), "center_focus_strong", "50mm standard lens, true-to-eye perspective"),
        "85": (lazy("85mm portrait"), "portrait", "85mm portrait lens, flattering compression"),
        "135": (lazy("135mm telephoto"), "zoom_in", "135mm telephoto lens, compressed background"),
        "macro": (lazy("100mm macro"), "filter_center_focus", "100mm macro lens, extreme close detail and texture"),
        "fisheye": (lazy("Fisheye"), "radio_button_checked", "fisheye lens, strong barrel distortion"),
        "anamorphic": (lazy("Anamorphic"), "aspect_ratio", "anamorphic lens, oval bokeh and horizontal flares"),
    },
    "aperture": {
        "1.4": (lazy("f/1.4"), "blur_on", "aperture f/1.4, very shallow depth of field, creamy bokeh"),
        "1.8": (lazy("f/1.8"), "blur_circular", "aperture f/1.8, shallow depth of field, soft background"),
        "2.8": (lazy("f/2.8"), "lens_blur", "aperture f/2.8, subject sharp with gently blurred background"),
        "5.6": (lazy("f/5.6"), "camera", "aperture f/5.6, moderate depth of field"),
        "8": (lazy("f/8"), "deblur", "aperture f/8, everything sharp from front to back"),
        "16": (lazy("f/16"), "brightness_7", "aperture f/16, deep focus, sun stars on highlights"),
    },
    "shutter": {
        "freeze": (lazy("Freeze motion"), "pause_circle", "fast shutter speed, motion frozen crisply"),
        "motion_blur": (lazy("Motion blur"), "motion_blur", "slow shutter, natural motion blur"),
        "long_exposure": (lazy("Long exposure"), "timelapse", "long exposure, light trails, silky movement"),
    },
    "angle": {
        "eye_level": (lazy("Eye level"), "visibility", "eye-level camera angle"),
        "low": (lazy("Low angle"), "north", "low-angle shot looking up, the subject feels strong"),
        "high": (lazy("High angle"), "south", "high-angle shot looking down"),
        "top_down": (lazy("Top-down"), "grid_view", "top-down flat lay, camera directly above"),
        "dutch": (lazy("Dutch tilt"), "rotate_right", "dutch angle, tilted horizon, dynamic tension"),
        "over_shoulder": (lazy("Over the shoulder"), "person", "over-the-shoulder shot"),
        "pov": (lazy("Point of view"), "visibility_lock", "first-person point-of-view shot"),
    },
    "framing": {
        "extreme_close": (lazy("Extreme close-up"), "zoom_in_map", "extreme close-up on a detail"),
        "close": (lazy("Close-up"), "crop_portrait", "close-up shot"),
        "medium": (lazy("Medium shot"), "crop_3_2", "medium shot, waist up"),
        "full": (lazy("Full shot"), "accessibility_new", "full shot, the whole subject in frame"),
        "wide": (lazy("Wide shot"), "crop_landscape", "wide shot showing the surroundings"),
        "establishing": (lazy("Establishing shot"), "location_city", "establishing shot of the whole place"),
    },
    "light": {
        "daylight": (lazy("Natural daylight"), "wb_sunny", "natural daylight"),
        "golden_hour": (lazy("Golden hour"), "wb_twilight", "warm golden hour sunlight, long soft shadows"),
        "blue_hour": (lazy("Blue hour"), "nights_stay", "blue hour light, cool calm tones"),
        "overcast": (lazy("Soft overcast"), "cloud", "soft overcast light, no harsh shadows"),
        "window": (lazy("Window light"), "window", "soft directional window light"),
        "softbox": (lazy("Studio softbox"), "light", "studio softbox lighting, soft even light, clean shadows"),
        "flash": (lazy("Hard flash"), "flash_on", "direct hard flash, crisp shadows, editorial look"),
        "neon": (lazy("Neon"), "nightlife", "colourful neon lighting, night mood"),
        "candle": (lazy("Candle light"), "local_fire_department", "warm candle light, intimate mood"),
        "low_key": (lazy("Low key"), "contrast", "low-key lighting, dark background, dramatic contrast"),
        "high_key": (lazy("High key"), "light_mode", "high-key lighting, bright airy background"),
    },
    "light_dir": {
        "front": (lazy("Front"), "arrow_upward", "light from the front"),
        "side": (lazy("Side"), "arrow_forward", "side light sculpting shape and texture"),
        "back": (lazy("Back / rim"), "arrow_downward", "backlight with a glowing rim around the subject"),
        "top": (lazy("Top"), "vertical_align_top", "light from above"),
        "rembrandt": (lazy("Rembrandt"), "change_history", "Rembrandt lighting, a small triangle of light on the "
                                                          "shadow side of the face"),
    },
    "look": {
        "natural": (lazy("Natural"), "nature", "natural true-to-life colours"),
        "warm": (lazy("Warm"), "local_fire_department", "warm colour grade"),
        "cool": (lazy("Cool"), "ac_unit", "cool colour grade"),
        "film": (lazy("Film"), "movie", "analogue film colour grade with soft grain"),
        "pastel": (lazy("Pastel"), "palette", "soft pastel colours"),
        "vivid": (lazy("Vivid"), "colorize", "vivid saturated colours"),
        "moody": (lazy("Moody"), "dark_mode", "moody desaturated grade, deep shadows"),
        "bw": (lazy("Black & white"), "filter_b_and_w", "black and white photograph"),
    },
    "movement": {  # video only
        "static": (lazy("Static"), "videocam", "static locked-off camera"),
        "push_in": (lazy("Slow push-in"), "zoom_in", "slow dolly push-in towards the subject"),
        "pull_out": (lazy("Pull out"), "zoom_out", "slow dolly pull-out revealing the scene"),
        "pan": (lazy("Pan"), "swap_horiz", "smooth horizontal pan"),
        "tilt": (lazy("Tilt"), "swap_vert", "smooth vertical tilt"),
        "orbit": (lazy("Orbit"), "360", "camera orbits around the subject"),
        "tracking": (lazy("Tracking"), "directions_walk", "tracking shot following the subject"),
        "handheld": (lazy("Handheld"), "back_hand", "handheld camera, natural subtle shake"),
        "crane": (lazy("Crane"), "height", "crane shot rising up"),
        "fpv": (lazy("FPV drone"), "flight", "fast FPV drone fly-through"),
    },
}
GROUP_LABELS = {
    "camera": lazy("Camera"), "lens": lazy("Lens"), "aperture": lazy("Aperture"), "shutter": lazy("Shutter"),
    "angle": lazy("Angle"), "framing": lazy("Framing"), "light": lazy("Lighting"),
    "light_dir": lazy("Light direction"), "look": lazy("Colour look"), "movement": lazy("Camera movement"),
}
GROUP_ICONS = {"camera": "photo_camera", "lens": "camera", "aperture": "camera_enhance", "shutter": "shutter_speed",
               "angle": "3d_rotation", "framing": "crop_free", "light": "light", "light_dir": "highlight",
               "look": "palette", "movement": "animation"}
VIDEO_ONLY = {"movement"}
IMAGE_ONLY = {"shutter"}

PRESETS: dict[str, tuple] = {
    "product": (lazy("Product hero"), "inventory_2",
                {"camera": "full_frame", "lens": "85", "aperture": "8", "angle": "eye_level", "framing": "close",
                 "light": "softbox", "light_dir": "side", "look": "natural", "movement": "orbit"}),
    "food": (lazy("Food close-up"), "restaurant",
             {"camera": "full_frame", "lens": "macro", "aperture": "2.8", "angle": "high", "framing": "close",
              "light": "window", "light_dir": "side", "look": "warm", "movement": "push_in"}),
    "flat_lay": (lazy("Flat lay"), "grid_view",
                 {"camera": "full_frame", "lens": "50", "aperture": "8", "angle": "top_down", "framing": "full",
                  "light": "overcast", "look": "natural", "movement": "static"}),
    "portrait": (lazy("Portrait"), "face",
                 {"camera": "full_frame", "lens": "85", "aperture": "1.8", "angle": "eye_level", "framing": "medium",
                  "light": "golden_hour", "light_dir": "back", "look": "warm", "movement": "push_in"}),
    "lifestyle": (lazy("Lifestyle"), "local_cafe",
                  {"camera": "full_frame", "lens": "35", "aperture": "2.8", "angle": "eye_level", "framing": "medium",
                   "light": "daylight", "look": "film", "movement": "handheld"}),
    "cinematic": (lazy("Cinematic"), "movie",
                  {"camera": "cinema", "lens": "anamorphic", "aperture": "1.8", "angle": "low", "framing": "wide",
                   "light": "low_key", "light_dir": "side", "look": "moody", "movement": "tracking"}),
    "ugc": (lazy("Phone / UGC"), "smartphone",
            {"camera": "phone", "lens": "24", "angle": "pov", "framing": "medium", "light": "daylight",
             "look": "natural", "movement": "handheld"}),
}


def clean(data) -> dict | None:
    """A valid shot dict (or None when nothing is set). ``mode`` is "auto" or "manual"."""
    if not isinstance(data, dict):
        return None
    out = {group: str(data[group]) for group in GROUPS if data.get(group) and str(data[group]) in GROUPS[group]}
    preset = data.get("preset") if data.get("preset") in PRESETS else None
    mode = "manual" if data.get("mode") == "manual" or out else "auto"
    if not out and not preset:
        return {"mode": "auto"} if data.get("mode") == "auto" else None
    return {"mode": mode, **({"preset": preset} if preset else {}), **out}


def resolved(shot: dict | None) -> dict:
    """The preset's values under the person's own choices."""
    shot = clean(shot) or {}
    base = dict(PRESETS[shot["preset"]][2]) if shot.get("preset") else {}
    base.update({k: v for k, v in shot.items() if k in GROUPS})
    return base


def describe(shot: dict | None, kind: str = "image") -> str:
    """Photography words for the prompt ("" when the shot is auto or empty)."""
    values = resolved(shot)
    if not values:
        return ""
    words = []
    for group, key in values.items():
        if kind != "video" and group in VIDEO_ONLY or kind == "video" and group in IMAGE_ONLY:
            continue
        words.append(GROUPS[group][key][2])
    if not words:
        return ""
    return "Camera and lighting: " + "; ".join(words) + "."


def merge(base: dict | None, override: dict | None) -> dict | None:
    """``override`` (the person's choice) over ``base`` (e.g. the brand's approved photo style)."""
    base, override = clean(base), clean(override)
    if not override or not any(k in GROUPS or k == "preset" for k in override):
        return base or override
    if not base:
        return override
    merged = resolved(base)
    merged.update(resolved(override))
    return clean({"mode": "manual", **merged})


def options() -> dict:
    """Groups, options (label + icon) and presets for the camera panel, in the current language."""
    return {
        "groups": [{"key": group, "label": _(GROUP_LABELS[group]), "icon": GROUP_ICONS[group],
                    "kinds": ["video"] if group in VIDEO_ONLY else ["image"] if group in IMAGE_ONLY
                    else ["image", "video"],
                    "options": [{"key": key, "label": _(label), "icon": icon}
                                for key, (label, icon, _words) in values.items()]}
                   for group, values in GROUPS.items()],
        "presets": [{"key": key, "label": _(label), "icon": icon, "values": values}
                    for key, (label, icon, values) in PRESETS.items()],
    }
