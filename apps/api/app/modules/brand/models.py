"""Brand kits (logo, colours, font, tone, rules, visual style, voice) — shared by AI writing, templates,
the inbox assistant and production."""
from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, WorkspaceMixin

# How the AI should write for the brand (stored codes -> prompt words)
LANGUAGE_STYLES = {
    "msa": "Modern Standard Arabic", "gulf": "Arabic close to the Gulf dialect", "saudi": "Saudi dialect",
    "english": "English", "bilingual": "Arabic and English side by side",
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
