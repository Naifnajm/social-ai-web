"""Production boards: a node canvas where text, images, video, voice, music and designs are created and
chained together (the output of one block feeds the next).

Every table carries ``workspace_id``; blocks, links and groups are soft-deleted (``active``) so the canvas
can undo a deletion; a periodic task purges them after a day.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, WorkspaceMixin


class Board(WorkspaceMixin, Base):
    __tablename__ = "production_boards"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    template: Mapped[str | None] = mapped_column(String(40))  # template key it was created from
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # owner
    cover_media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    zoom: Mapped[float] = mapped_column(Float, default=1.0)
    pan_x: Mapped[float] = mapped_column(Float, default=0.0)
    pan_y: Mapped[float] = mapped_column(Float, default=0.0)
    variables: Mapped[list | None] = mapped_column(JSON)  # [{"key": "product", "value": "Kiosk"}]
    brand_kit_id: Mapped[int | None] = mapped_column(ForeignKey("brand_kits.id", ondelete="SET NULL"))
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"))  # linked post


class Group(WorkspaceMixin, Base):
    __tablename__ = "production_groups"

    board_id: Mapped[int] = mapped_column(ForeignKey("production_boards.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    color: Mapped[str] = mapped_column(String(9), default="#71717a")


class Node(WorkspaceMixin, Base):
    __tablename__ = "production_nodes"

    board_id: Mapped[int] = mapped_column(ForeignKey("production_boards.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(160), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("production_groups.id", ondelete="SET NULL"))

    # parameters
    prompt: Mapped[str | None] = mapped_column(Text)
    text_value: Mapped[str | None] = mapped_column(Text)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("ai_providers.id", ondelete="SET NULL"))
    model_id: Mapped[int | None] = mapped_column(ForeignKey("ai_models.id", ondelete="SET NULL"))
    aspect: Mapped[str] = mapped_column(String(5), default="1:1")
    style: Mapped[str | None] = mapped_column(String(30))
    seconds: Mapped[int] = mapped_column(Integer, default=8)
    audio_mode: Mapped[str] = mapped_column(String(10), default="speech")  # speech | sfx | music
    design: Mapped[dict | None] = mapped_column(JSON)  # layers of the design editor
    variations: Mapped[int] = mapped_column(Integer, default=1)  # 1-4 versions per run
    formats: Mapped[str] = mapped_column(String(40), default="9:16,1:1,4:5,16:9")
    fit_mode: Mapped[str] = mapped_column(String(10), default="blur")  # blur | crop
    caption_position: Mapped[str] = mapped_column(String(10), default="bottom")  # bottom | center | top
    caption_size: Mapped[str] = mapped_column(String(2), default="m")  # s | m | l
    caption_language: Mapped[str | None] = mapped_column(String(10))
    template_ref: Mapped[str | None] = mapped_column(String(40))  # "template:<id>" | "set:<id>"
    approval_state: Mapped[str | None] = mapped_column(String(10))  # pending | approved | rejected
    approved_hash: Mapped[str | None] = mapped_column(String(40))
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approval_comment: Mapped[str | None] = mapped_column(Text)
    account_ids: Mapped[list | None] = mapped_column(JSON)  # social account ids (Post block)
    publish_mode: Mapped[str] = mapped_column(String(10), default="draft")  # draft | now | best | at
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # result
    state: Mapped[str] = mapped_column(String(10), default="idle", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    notice: Mapped[str | None] = mapped_column(String(500))
    output_text: Mapped[str | None] = mapped_column(Text)
    output_media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"))
    cost: Mapped[float] = mapped_column(Float, default=0.0)  # cost of the last run ($, approx.)
    run_no: Mapped[int] = mapped_column(Integer, default=0)
    run_expected: Mapped[int] = mapped_column(Integer, default=0)
    run_job_ids: Mapped[list | None] = mapped_column(JSON)  # media jobs of the current run
    run_hash: Mapped[str | None] = mapped_column(String(40))
    done_hash: Mapped[str | None] = mapped_column(String(40))  # fingerprint of the current result's inputs
    force_run: Mapped[bool] = mapped_column(Boolean, default=False)


class Edge(WorkspaceMixin, Base):
    __tablename__ = "production_edges"

    board_id: Mapped[int] = mapped_column(ForeignKey("production_boards.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("production_nodes.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("production_nodes.id", ondelete="CASCADE"), index=True)
    target_port: Mapped[str] = mapped_column(String(20), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Output(WorkspaceMixin, Base):
    """Every result a block produced: the variations of one run and the history of earlier runs."""

    __tablename__ = "production_outputs"

    node_id: Mapped[int] = mapped_column(ForeignKey("production_nodes.id", ondelete="CASCADE"), index=True)
    run_no: Mapped[int] = mapped_column(Integer, default=0)
    media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    text: Mapped[str | None] = mapped_column(Text)
    aspect: Mapped[str | None] = mapped_column(String(5))
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    model_label: Mapped[str | None] = mapped_column(String(160))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("media_jobs.id", ondelete="SET NULL"))
