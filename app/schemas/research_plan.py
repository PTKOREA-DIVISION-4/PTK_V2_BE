from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import AnalysisTrack, SectionCode, WorkflowMeta


class ResearchPlanItemResponse(BaseModel):
    id: str
    section_code: SectionCode
    item_key: str
    title: str
    description: str
    data_sources: list[str]
    is_enabled: bool
    display_order: int


class ResearchPlanResponse(BaseModel):
    id: str
    project_id: str
    analysis_track: AnalysisTrack
    is_confirmed: bool
    target_communities: list[str] = Field(
        default_factory=list,
        examples=[["dcinside", "fmkorea", "theqoo", "clien", "naver_blog", "naver_cafe"]],
    )
    datalab_groups_config: list[dict[str, Any]] = Field(default_factory=list)
    estimated_duration_seconds: int
    items: list[ResearchPlanItemResponse] = Field(default_factory=list)
    workflow_meta: WorkflowMeta | None = None


class ResearchPlanItemToggle(BaseModel):
    item_key: str
    is_enabled: bool


class ResearchPlanUpdateRequest(BaseModel):
    is_confirmed: bool = True
    target_communities: list[str] | None = None
    datalab_groups_config: list[dict[str, Any]] | None = None
    items: list[ResearchPlanItemToggle] = Field(default_factory=list)
