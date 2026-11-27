from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, LongText, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.project import Project


class RawSourceItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Collected raw document, post, review, or research snippet with evidence span."""

    __tablename__ = "raw_source_items"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(LongText, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    author: Mapped[str | None] = mapped_column(String(160), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    highlight_spans: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    sentiment: Mapped[str] = mapped_column(String(16), nullable=False, default="NEUTRAL")
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    project: Mapped["Project"] = relationship(back_populates="raw_sources")
    media_assets: Mapped[list["MediaAsset"]] = relationship(
        back_populates="source_item",
        cascade="all, delete-orphan",
    )


class MediaAsset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Archived local visual asset (SNS thumbnail, video keyframe, annotated example, chart)."""

    __tablename__ = "media_assets"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("raw_source_items.id", ondelete="SET NULL"), nullable=True
    )
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    local_path: Mapped[str] = mapped_column(String(512), nullable=False)
    caption: Mapped[str | None] = mapped_column(String(500), nullable=True)
    annotation_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    project: Mapped["Project"] = relationship(back_populates="media_assets")
    source_item: Mapped["RawSourceItem | None"] = relationship(back_populates="media_assets")


class DataLabSeries(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Naver DataLab Search Trend / Shopping Insight time-series and transparent metrics."""

    __tablename__ = "datalab_series"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_type: Mapped[str] = mapped_column(String(32), nullable=False)  # SEARCH_TREND | SHOPPING_INSIGHT
    group_label: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(24), nullable=False)  # OWN | COMPETITOR | INDUSTRY
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    time_unit: Mapped[str] = mapped_column(String(16), nullable=False, default="week")
    points_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    cumulative_index_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    share_of_search_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    growth_rate_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    peak_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    peak_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    methodology_note: Mapped[str] = mapped_column(String(500), nullable=False)

    project: Mapped["Project"] = relationship(back_populates="datalab_series")


class SnsTopPost(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Period-filtered TOP 5 official SNS posts or creator collaboration posts per brand."""

    __tablename__ = "sns_top_posts"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_type: Mapped[str] = mapped_column(String(24), nullable=False)  # OWN | COMPETITOR
    brand_label: Mapped[str] = mapped_column(String(120), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    post_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    likes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    engagement_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rank_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_creator_collab: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    media_asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )
    key_takeaway: Mapped[str | None] = mapped_column(String(500), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="sns_top_posts")
