"""Brand kits (logo, colours, font, tone, rules, visual style, voice) — shared by AI writing, templates,
the inbox assistant and production."""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, WorkspaceMixin

# How the AI should write for the brand (stored codes -> prompt words)
LANGUAGE_STYLES = {
    "msa": "Modern Standard Arabic", "gulf": "Arabic close to the Gulf dialect", "saudi": "Saudi dialect",
    "english": "English", "bilingual": "Arabic and English side by side",
    "dutch": "Dutch", "german": "German", "french": "French",
}
EMOJI_STYLES = {"none": "no emojis", "light": "a few emojis", "rich": "emojis welcome"}


class BrandKit(WorkspaceMixin, Base):
    __tablename__ = "brand_kits"

    name: Mapped[str] = mapped_column(String(120))
    logo_media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    color_primary: Mapped[str] = mapped_column(String(9), default="#111111")
    color_secondary: Mapped[str] = mapped_column(String(9), default="#71717a")
    color_text: Mapped[str] = mapped_column(String(9), default="#ffffff")
    font_family: Mapped[str] = mapped_column(String(80), default="system-ui")
    tagline: Mapped[str | None] = mapped_column(String(200))
    tone: Mapped[str | None] = mapped_column(Text)
    guidelines: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[str | None] = mapped_column(String(500))
    visual_style: Mapped[str | None] = mapped_column(Text)
    voice: Mapped[str | None] = mapped_column(String(120))
    # identity details (all optional): more colours, a heading font, who the brand is and how it speaks
    color_accent: Mapped[str | None] = mapped_column(String(9))
    color_background: Mapped[str | None] = mapped_column(String(9))
    font_heading: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(120))
    audience: Mapped[str | None] = mapped_column(Text)
    personality: Mapped[str | None] = mapped_column(String(300))
    language_style: Mapped[str | None] = mapped_column(String(20))
    emoji_style: Mapped[str | None] = mapped_column(String(10))
    cta: Mapped[str | None] = mapped_column(String(200))
    banned_words: Mapped[str | None] = mapped_column(Text)
    sample_posts: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(300))
    # brand guard: off | guide | strict (see guard.py), the approved camera settings and do/don't rules for visuals
    guard_mode: Mapped[str] = mapped_column(String(10), default="guide", server_default="guide")
    photo_style: Mapped[dict | None] = mapped_column(JSON)
    visual_rules: Mapped[str | None] = mapped_column(Text)
    # the logo variant for dark backgrounds and brand reference images (both optional, e.g. from a design system)
    logo_dark_media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    reference_media_ids: Mapped[list | None] = mapped_column(JSON)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    def llm_profile(self) -> str:
        parts = [f"Brand: {self.name}"]
        for label, value in (("About", self.description), ("Industry", self.industry), ("Website", self.website),
                             ("Audience", self.audience), ("Personality", self.personality),
                             ("Tagline", self.tagline), ("Tone of voice", self.tone),
                             ("Language", LANGUAGE_STYLES.get(self.language_style or "")),
                             ("Emojis", EMOJI_STYLES.get(self.emoji_style or "")), ("Usual call to action", self.cta),
                             ("Rules", self.guidelines), ("Never use these words", self.banned_words),
                             ("Brand hashtags", self.hashtags), ("Example posts in the brand's voice", self.sample_posts)):
            if (value or "").strip():
                parts.append(f"{label}: {value.strip()}")
        return "\n".join(parts)

    def visual_hint(self) -> str:
        parts = []
        if (self.visual_style or "").strip():
            parts.append(f"Visual style: {self.visual_style.strip()}.")
        colors = [c for c in (self.color_primary, self.color_secondary, self.color_accent) if c]
        if colors:
            parts.append("Brand colours: " + ", ".join(colors) + ".")
        return " ".join(parts)


class BrandFont(WorkspaceMixin, Base):
    """A font file of a brand kit (imported from a design system). The renderers use the file whose family is
    the kit's heading / body font (``fonts.py``); Tajawal draws what the file has no glyphs for."""

    __tablename__ = "brand_fonts"

    brand_kit_id: Mapped[int] = mapped_column(ForeignKey("brand_kits.id", ondelete="CASCADE"), index=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media.id", ondelete="CASCADE"))
    family: Mapped[str] = mapped_column(String(120))
    weight: Mapped[int] = mapped_column(Integer, default=400)
    style: Mapped[str] = mapped_column(String(10), default="normal")  # normal | italic
    role: Mapped[str] = mapped_column(String(10), default="other")  # heading | body | other
    has_arabic: Mapped[bool | None] = mapped_column(Boolean)


class BrandImport(WorkspaceMixin, Base):
    """An uploaded design system waiting for the person to choose what to keep (short-lived, see importer.py).
    The file itself sits in the storage folder under ``storage_key``; ``draft`` is what the preview found."""

    __tablename__ = "brand_imports"

    token: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(10))  # zip | md | json | css
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    storage_key: Mapped[str] = mapped_column(String(500))
    draft: Mapped[dict | None] = mapped_column(JSON)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
