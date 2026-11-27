from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.collection import DataLabSeries, MediaAsset, RawSourceItem, SnsTopPost
    from app.models.factbook import FactItem, PlannerComment, SlideDraft
    from app.models.job import AsyncJob, ExportRecord
    from app.models.research_plan import ResearchPlan


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Single brand x single hero product/line Factbook project."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(150), nullable=False)
    industry_category: Mapped[str] = mapped_column(String(80), nullable=False)
    analysis_track: Mapped[str] = mapped_column(
        String(32), nullable=False, default="REVIEW_CENTRIC"
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    current_stage: Mapped[str] = mapped_column(
        String(24), nullable=False, default="SETUP"
    )
    summary_split_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="SPLIT_2"
    )
    naver_shopping_category_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )

    competitors: Mapped[list["CompetitorTarget"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="CompetitorTarget.display_order",
    )
    sns_accounts: Mapped[list["SnsAccount"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    keyword_groups: Mapped[list["KeywordGroup"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    research_plan: Mapped["ResearchPlan | None"] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        uselist=False,
    )
    raw_sources: Mapped[list["RawSourceItem"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    media_assets: Mapped[list["MediaAsset"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    datalab_series: Mapped[list["DataLabSeries"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    sns_top_posts: Mapped[list["SnsTopPost"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    fact_items: Mapped[list["FactItem"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    slide_drafts: Mapped[list["SlideDraft"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="SlideDraft.slide_order",
    )
    planner_comments: Mapped[list["PlannerComment"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    jobs: Mapped[list["AsyncJob"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    exports: Mapped[list["ExportRecord"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class CompetitorTarget(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Matched direct competitor brand + product pair."""

    __tablename__ = "competitor_targets"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_name: Mapped[str] = mapped_column(String(120), nullable=False)
    product_name: Mapped[str] = mapped_column(String(150), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    project: Mapped["Project"] = relationship(back_populates="competitors")


class SnsAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Official SNS account URL for target brand or a competitor."""

    __tablename__ = "sns_accounts"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_type: Mapped[str] = mapped_column(String(24), nullable=False)  # OWN | COMPETITOR
    competitor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("competitor_targets.id", ondelete="SET NULL"), nullable=True
    )
    brand_label: Mapped[str] = mapped_column(String(120), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)  # INSTAGRAM | YOUTUBE | TIKTOK | OTHER
    account_url: Mapped[str] = mapped_column(String(512), nullable=False)
    handle: Mapped[str] = mapped_column(String(120), nullable=False)

    project: Mapped["Project"] = relationship(back_populates="sns_accounts")


class KeywordGroup(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Search keywords and hashtags grouped by OWN, COMPETITOR, or INDUSTRY."""

    __tablename__ = "keyword_groups"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_type: Mapped[str] = mapped_column(String(24), nullable=False)  # OWN | COMPETITOR | INDUSTRY
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    hashtags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    project: Mapped["Project"] = relationship(back_populates="keyword_groups")
