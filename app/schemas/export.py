from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import QcSeverity, SummarySplitMode
from app.schemas.qc import QcReportResponse


class ExportCreateRequest(BaseModel):
    allow_warnings: bool = Field(
        default=True,
        description="WARNING 등급 QC 항목이 있어도 BLOCKER만 없으면 PPTX 생성을 허용할지 여부",
    )


class ExportRecordResponse(BaseModel):
    id: str
    project_id: str
    job_id: str | None = None
    qc_status: QcSeverity
    qc_report: QcReportResponse
    summary_split_mode: SummarySplitMode
    slide_count: int
    file_size_bytes: int
    download_filename: str | None = None
    download_url: str | None = Field(
        default=None,
        examples=["/api/v1/projects/proj_123/exports/exp_456/download"],
    )
    created_at: datetime
