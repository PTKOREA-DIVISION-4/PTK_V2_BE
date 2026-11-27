from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SectionCode(str, Enum):
    OVERVIEW = "0_OVERVIEW"
    OWN = "1_OWN"
    MARKET = "2_MARKET"
    COMPETITOR = "3_COMPETITOR"
    CONSUMER = "4_CONSUMER"
    SUMMARY_CONCLUSION = "5_SUMMARY_CONCLUSION"


class AnalysisTrack(str, Enum):
    REVIEW_CENTRIC = "REVIEW_CENTRIC"
    MARKET_CENTRIC = "MARKET_CENTRIC"


class ProjectStage(str, Enum):
    SETUP = "SETUP"
    PLAN = "PLAN"
    COLLECT = "COLLECT"
    REVIEW = "REVIEW"
    EXPORT = "EXPORT"


class SummarySplitMode(str, Enum):
    SPLIT_2 = "SPLIT_2"
    SPLIT_4 = "SPLIT_4"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SlideReviewStatus(str, Enum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    COMMENT_APPLIED = "COMMENT_APPLIED"
    APPROVED = "APPROVED"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class QcSeverity(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKER = "BLOCKER"


class OwnerType(str, Enum):
    OWN = "OWN"
    COMPETITOR = "COMPETITOR"
    INDUSTRY = "INDUSTRY"


class SnsPlatform(str, Enum):
    INSTAGRAM = "INSTAGRAM"
    YOUTUBE = "YOUTUBE"
    TIKTOK = "TIKTOK"
    OTHER = "OTHER"


class KeywordGroupType(str, Enum):
    OWN = "OWN"
    COMPETITOR = "COMPETITOR"
    INDUSTRY = "INDUSTRY"


class ErrorDetail(BaseModel):
    code: str = Field(..., examples=["QC_BLOCKED"])
    message: str = Field(..., examples=["사전 품질 검증(QC)을 통과하지 못했습니다."])
    user_action_hint: str | None = Field(
        default=None,
        examples=["누락된 장표 초안을 생성하거나 내용을 보완해 주세요."],
    )
    details: list[dict[str, Any]] = Field(default_factory=list)
    retryable: bool = Field(default=False)


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class WorkflowMeta(BaseModel):
    """Frontend step-navigation badges and next-action cues."""

    current_stage: ProjectStage
    plan_confirmed: bool = False
    total_sources_count: int = 0
    pending_sources_count: int = 0
    approved_sources_count: int = 0
    rejected_sources_count: int = 0
    total_slides_count: int = 0
    unreviewed_slides_count: int = 0
    missing_sections: list[SectionCode] = Field(default_factory=list)
    can_export: bool = False
    next_step_hint: str = Field(
        default="조사 계획을 확인하고 자료 수집을 시작해 주세요.",
        description="상단 할 일 안내 헤더에 그대로 표시할 행동 가이드 문구",
    )
