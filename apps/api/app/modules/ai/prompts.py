"""Prompt construction and answer parsing for post writing ("Write with AI"), ported from the Odoo module."""
import json
import re

TONES = {
    "professional": "Professional",
    "friendly": "Friendly",
    "inspiring": "Inspiring",
    "playful": "Playful",
    "persuasive": "Persuasive / sales",
    "informative": "Informative",
}

LANGUAGES = {
    "auto": "Same as the brief",
    "ar": "Arabic",
    "en": "English",
    "nl": "Dutch",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "tr": "Turkish",
}

LENGTHS = {"short": "Short", "medium": "Medium", "long": "Long"}

# Character limits of the networks (kept here so writing does not depend on the publishing module).
PLATFORM_LIMITS = {
    "facebook": 63206,
    "instagram": 2200,
    "threads": 500,
    "linkedin": 3000,
    "x": 280,
    "tiktok": 4000,
    "telegram": 4096,
    "whatsapp": 4096,
    "youtube": 5000,
    "pinterest": 800,
    "google_business": 1500,
}

PLATFORM_STYLE = {
    "facebook": "conversational, can be a few short paragraphs, end with a question or call to action",
    "instagram": "visual storytelling, short lines, emojis welcome, hashtags grouped at the end (max 15)",
    "linkedin": "professional insight, hook in the first line, short paragraphs, 3-5 hashtags at the end",
    "x": "punchy, ONE single post of at most 270 characters including hashtags (max 2 hashtags)",
    "tiktok": "first line is a catchy title (max 90 chars), then a casual caption with trending-style hashtags",
    "threads": "casual and conversational, at most 480 characters",
    "telegram": "clear announcement style, may use line breaks and emojis, no hashtags needed",
    "whatsapp": "short and personal, like a message to a customer, no hashtags",
    "youtube": "first line is the video title (max 90 chars, no clickbait), then a description that says what the "
               "video shows, with 3-5 hashtags at the end",
    "pinterest": "first line is a short searchable title (max 90 chars), then one or two sentences with the "
                 "keywords people search for, at most 3 hashtags",
    "google_business": "a short update for people who found the business on Google Maps: what is new, when, and "
                       "what to do next; plain sentences, no hashtags, at most 600 characters",
}

# System presets for other uses of the text endpoint (replies, ideas, hashtags…)
PRESETS = {
    "post": None,  # built by build_prompts
    "reply": "You answer comments and messages for a brand. Be helpful, warm and brief. Answer in the language of "
             "the message. Return only the reply text.",
    "ideas": "You are a social media strategist. Suggest concrete, varied post ideas as a short numbered list. "
             "Answer in the language of the brief.",
    "hashtags": "You suggest relevant hashtags for a social media post. Return only the hashtags separated by "
                "spaces, max 15, in the language of the post.",
    "rewrite": "You improve social media copy. Keep the meaning and the language, make it clearer and more "
               "engaging. Return only the rewritten text.",
    "free": "You are a helpful assistant for a social media team. Answer concisely.",
}


def build_prompts(brand_voice: str, brief: str, tone: str | None, language: str | None, length: str | None,
                  platforms: list[str], hashtags: bool = True, emojis: bool = True, tailor: bool = False,
                  current_text: str = "") -> tuple[str, str]:
    lang_line = ("Write in the same language as the brief." if language in (False, None, "", "auto")
                 else "Write in %s." % LANGUAGES.get(language, language))
    system = [
        "You are an expert social media copywriter.",
        "Write ready-to-publish posts: no explanations, no quotes around the text, no markdown headings, "
        "no **bold** markers.",
        lang_line,
        "Tone: %s." % TONES.get(tone or "", tone or "professional"),
        "Length: %s." % LENGTHS.get(length or "", "medium").lower(),
        "Use hashtags where they fit the platform." if hashtags else "Do not use hashtags.",
        "Emojis are welcome but not excessive." if emojis else "Do not use emojis.",
    ]
    if brand_voice:
        system.append("Brand profile and voice to respect:\n%s" % brand_voice.strip())

    platform_lines = []
    for platform in platforms:
        limit = PLATFORM_LIMITS.get(platform)
        platform_lines.append("- %s: %s (hard limit %s characters)" % (platform, PLATFORM_STYLE.get(platform, ""),
                                                                        limit))

    user = []
    if current_text:
        user.append("Improve or rewrite this existing draft according to the instructions:\n<<<\n%s\n>>>" % current_text)
    user.append("Brief: %s" % (brief or "Write an engaging post."))
    if platform_lines:
        user.append("Target platforms:\n%s" % "\n".join(platform_lines))
    if tailor and platforms:
        shape = ", ".join('"%s": "<version adapted to %s>"' % (p, p) for p in platforms)
        user.append(
            "Return ONLY a JSON object, no code fence, with this shape: "
            '{"main": "<one version that works everywhere>", "variants": {%s}}. '
            "Every variant must respect its platform limit." % shape
        )
    else:
        strictest = min((PLATFORM_LIMITS.get(p) or 10**6 for p in platforms), default=None)
        if strictest and strictest < 10**6:
            user.append("Keep the post under %d characters so it fits every platform." % (strictest - 10))
        user.append("Return only the post text.")
    return "\n".join(system), "\n\n".join(user)


def parse_answer(text: str, tailor: bool = False, platforms=()) -> tuple[str, dict]:
    """Return (main_text, {platform: text})."""
    text = (text or "").strip()
    if not tailor:
        return clean(text), {}
    data = parse_json(text)
    if isinstance(data, dict) and ("main" in data or "variants" in data):
        variants = {key: clean(str(value)) for key, value in (data.get("variants") or {}).items()
                    if key in platforms and value}
        main = clean(str(data.get("main") or ""))
        return main or next(iter(variants.values()), ""), variants
    return clean(text), {}


def clean(text: str) -> str:
    text = (text or "").strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'“”" or len(text) > 1 and text[0] == "“" and text[-1] == "”":
        text = text[1:-1].strip()
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.DOTALL)


# ------------------------------------------------------------------ robust JSON
_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def _balanced(text: str, opener: str, closer: str) -> str | None:
    """First balanced {...} / [...] block (string-aware)."""
    start = text.find(opener)
    while start != -1:
        depth, in_str, escape = 0, False, False
        for index in range(start, len(text)):
            char = text[index]
            if in_str:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_str = False
                continue
            if char == '"':
                in_str = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
        start = text.find(opener, start + 1)
    return None


def _loads(candidate: str):
    try:
        return json.loads(candidate)
    except ValueError:
        pass
    fixed = re.sub(r",\s*([}\]])", r"\1", candidate)  # trailing commas
    fixed = fixed.replace("“", '"').replace("”", '"')
    try:
        return json.loads(fixed)
    except ValueError:
        return None


def parse_json(text: str):
    """Parse a JSON value from a model answer: plain JSON, ```json fences, or JSON inside extra prose.
    Returns the parsed object/list, or None."""
    text = (text or "").strip().lstrip("﻿")
    if not text:
        return None
    candidates = [text]
    candidates += [m.group(1).strip() for m in _FENCE.finditer(text)]
    for source in list(candidates):
        pairs = sorted((("{", "}"), ("[", "]")),
                       key=lambda pair: source.find(pair[0]) if source.find(pair[0]) >= 0 else len(source))
        for opener, closer in pairs:  # the structure that starts first wins
            block = _balanced(source, opener, closer)
            if block:
                candidates.append(block)
    for candidate in candidates:
        value = _loads(candidate)
        if isinstance(value, (dict, list)):
            return value
    return None


VISUAL_SYSTEM = ("You write prompts for AI {kind} generators. Answer with ONE prompt in English, max 80 words, "
                 "describing subject, setting, composition, lighting and mood. No text or logos in the visual. "
                 "No quotes, no explanations.")
