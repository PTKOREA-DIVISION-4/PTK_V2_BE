from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.project import Project


class ResearchPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Confirmed scope and target sources for a Factbook project."""

    __tablename__ = "research_plans"

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    is_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    target_communities: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    datalab_groups_config: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    estimated_duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=120
    )

    project: Mapped["Project"] = relationship(back_populates="research_plan")
    items: Mapped[list["ResearchPlanItem"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="ResearchPlanItem.display_order",
    )


class ResearchPlanItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Toggleable research module belonging to sections 0 through 5."""

    __tablename__ = "research_plan_items"

    plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("research_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    item_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    data_sources: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    plan: Mapped["ResearchPlan"] = relationship(back_populates="items")
