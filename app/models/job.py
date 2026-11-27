from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.project import Project


class AsyncJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Background task tracking record for collection, slide generation, and PPTX export."""

    __tablename__ = "async_jobs"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", index=True)
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    logs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="jobs")
    subtasks: Mapped[list["JobSubtask"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobSubtask.created_at",
    )


class JobSubtask(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Per-source or per-stage progress unit within an AsyncJob."""

    __tablename__ = "job_subtasks"

    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("async_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subtask_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    collected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped["AsyncJob"] = relationship(back_populates="subtasks")


class ExportRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Pre-flight QC report snapshot and generated PPTX export file record."""

    __tablename__ = "export_records"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("async_jobs.id", ondelete="SET NULL"), nullable=True
    )
    qc_status: Mapped[str] = mapped_column(String(16), nullable=False)  # PASS | WARNING | BLOCKER
    qc_report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    summary_split_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="SPLIT_2")
    slide_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    download_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="exports")
