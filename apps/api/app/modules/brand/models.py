"""Brand kits (logo, colours, font, tone, rules, visual style, voice) — shared by AI writing, templates,
the inbox assistant and production."""
from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, WorkspaceMixin


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
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    def llm_profile(self) -> str:
        parts = [f"Brand: {self.name}"]
        for label, value in (("Tagline", self.tagline), ("Tone of voice", self.tone), ("Rules", self.guidelines),
                             ("Brand hashtags", self.hashtags)):
            if (value or "").strip():
                parts.append(f"{label}: {value.strip()}")
        return "\n".join(parts)

    def visual_hint(self) -> str:
        parts = []
        if (self.visual_style or "").strip():
            parts.append(f"Visual style: {self.visual_style.strip()}.")
        colors = [c for c in (self.color_primary, self.color_secondary) if c]
        if colors:
            parts.append("Brand colours: " + ", ".join(colors) + ".")
        return " ".join(parts)
