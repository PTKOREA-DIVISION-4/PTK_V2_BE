from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import QcSeverity, SectionCode, SummarySplitMode


class QcCheckItem(BaseModel):
    gate_code: str = Field(..., examples=["REQUIRED_SECTIONS"])
    severity: QcSeverity
    message: str
    target_section: SectionCode | None = None
    target_slide_id: str | None = None
    user_action_hint: str | None = None


class QcReportResponse(BaseModel):
    project_id: str
    overall_status: QcSeverity
    can_export: bool
    summary_split_mode: SummarySplitMode
    total_slides_checked: int
    present_sections: list[SectionCode] = Field(default_factory=list)
    missing_sections: list[SectionCode] = Field(default_factory=list)
    checks: list[QcCheckItem] = Field(default_factory=list)
