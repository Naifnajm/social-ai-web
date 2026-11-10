"""Brand templates: a PNG frame with a transparent window, made once, used for every post and story.

* ``BrandTemplate`` — one frame for one format (feed 4:5, square, story 9:16, landscape).
* ``BrandTemplateSet`` — templates used together, e.g. "Offers" = a 4:5 post + a 9:16 story.
"""
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, WorkspaceMixin

TEMPLATE_FORMATS = ("post_4x5", "post_1x1", "story_9x16", "landscape_16x9")
CATEGORIES = ("offers", "product", "event", "quote", "other")
LOGO_POSITIONS = ("top_left", "top_right", "bottom_left", "bottom_right")
PHOTO_FITS = ("cover", "contain")
TEXT_ALIGNS = ("auto", "left", "center", "right")


class BrandTemplateSet(WorkspaceMixin, Base):
    __tablename__ = "brand_template_sets"

    name: Mapped[str] = mapped_column(String(120))  # what you type after /post in Telegram
    sequence: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    category: Mapped[str] = mapped_column(String(20), default="other")
    brand_kit_id: Mapped[int | None] = mapped_column(ForeignKey("brand_kits.id", ondelete="SET NULL"))

    templates = relationship("BrandTemplate", back_populates="set", order_by="(BrandTemplate.sequence, BrandTemplate.id)")


class BrandTemplate(WorkspaceMixin, Base):
    __tablename__ = "brand_templates"

    name: Mapped[str] = mapped_column(String(120))
    sequence: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    set_id: Mapped[int | None] = mapped_column(ForeignKey("brand_template_sets.id", ondelete="SET NULL"), index=True)
    brand_kit_id: Mapped[int | None] = mapped_column(ForeignKey("brand_kits.id", ondelete="SET NULL"))
    category: Mapped[str] = mapped_column(String(20), default="other")
    format: Mapped[str] = mapped_column(String(20), default="post_4x5")
    frame_media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    frame_has_window: Mapped[bool] = mapped_column(Boolean, default=True)
    background_color: Mapped[str | None] = mapped_column(String(9))  # empty: the brand kit's main colour

    # photo window (% of the canvas)
    box_x: Mapped[float] = mapped_column(Float, default=5.0)
    box_y: Mapped[float] = mapped_column(Float, default=5.0)
    box_w: Mapped[float] = mapped_column(Float, default=90.0)
    box_h: Mapped[float] = mapped_column(Float, default=72.0)
    photo_fit: Mapped[str] = mapped_column(String(10), default="cover")  # cover | contain

    # text zone (% of the canvas)
    text_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    text_x: Mapped[float] = mapped_column(Float, default=6.0)
    text_y: Mapped[float] = mapped_column(Float, default=80.0)
    text_w: Mapped[float] = mapped_column(Float, default=88.0)
    text_h: Mapped[float] = mapped_column(Float, default=14.0)
    text_size: Mapped[int] = mapped_column(Integer, default=64)  # px at the canvas size, shrinks to fit
    text_color: Mapped[str] = mapped_column(String(9), default="#ffffff")
    text_bg_color: Mapped[str | None] = mapped_column(String(9))  # optional label behind the text (price tag)
    text_align: Mapped[str] = mapped_column(String(8), default="auto")
    text_bold: Mapped[bool] = mapped_column(Boolean, default=True)
    text_max_lines: Mapped[int] = mapped_column(Integer, default=2)
    text_default: Mapped[str | None] = mapped_column(String(200))

    # logo (from the brand kit)
    logo_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    logo_position: Mapped[str] = mapped_column(String(12), default="top_right")
    logo_size: Mapped[float] = mapped_column(Float, default=16.0)  # % of the canvas width

    preview_media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    preview_hash: Mapped[str | None] = mapped_column(String(40))
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    set = relationship("BrandTemplateSet", back_populates="templates")

    @property
    def is_story(self) -> bool:
        return self.format == "story_9x16"
