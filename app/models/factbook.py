from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.project import Project


class FactItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Structured claim grounded in a verified raw source quote."""

    __tablename__ = "fact_items"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    category_tag: Mapped[str] = mapped_column(String(64), nullable=False, default="GENERAL")
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("raw_source_items.id", ondelete="SET NULL"), nullable=True
    )
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_quote_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="APPROVED"
    )

    project: Mapped["Project"] = relationship(back_populates="fact_items")


class SlideDraft(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Editable slide draft for sections 0 through 5 (including split summary & AS-IS->TO-BE)."""

    __tablename__ = "slide_drafts"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    slide_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    slide_type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    headcopy: Mapped[str] = mapped_column(String(400), nullable=False)
    kpi_cards_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    bullets_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    table_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    visual_assets_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    as_is_to_be_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    footnote: Mapped[str | None] = mapped_column(String(500), nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="NEEDS_REVIEW"
    )

    project: Mapped["Project"] = relationship(back_populates="slide_drafts")
    comments: Mapped[list["PlannerComment"]] = relationship(
        back_populates="slide",
        cascade="all, delete-orphan",
        order_by="PlannerComment.created_at.desc()",
    )


class PlannerComment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Planner review note with AI-refined before/after diff for slide drafts."""

    __tablename__ = "planner_comments"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slide_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("slide_drafts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raw_comment: Mapped[str] = mapped_column(Text, nullable=False)
    refined_comment: Mapped[str] = mapped_column(Text, nullable=False)
    before_draft_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    after_draft_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="PREVIEW_READY"
    )  # DRAFT | PREVIEW_READY | APPLIED | REVERTED

    project: Mapped["Project"] = relationship(back_populates="planner_comments")
    slide: Mapped["SlideDraft"] = relationship(back_populates="comments")
