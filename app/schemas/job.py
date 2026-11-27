from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import JobStatus


class JobSubtaskResponse(BaseModel):
    id: str
    subtask_key: str
    label: str
    status: JobStatus
    progress_pct: int
    collected_count: int
    error_message: str | None = None


class JobStatusResponse(BaseModel):
    id: str
    project_id: str
    job_type: str
    status: JobStatus
    progress_pct: int = Field(..., ge=0, le=100)
    logs: list[str] = Field(default_factory=list)
    error_message: str | None = None
    subtasks: list[JobSubtaskResponse] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
