from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import SectionCode, SlideReviewStatus, SummarySplitMode


class SlideGenerateRequest(BaseModel):
    summary_split_mode: SummarySplitMode | None = Field(
        default=None,
        description="현황 요약 분할 방식 (SPLIT_2: 2장 분할 권장, SPLIT_4: 4장 심층 분할)",
    )
    use_approved_only: bool = Field(
        default=True,
        description="true면 APPROVED 소스만 사용(단, APPROVED가 0건이면 REJECTED 제외 전체 활용)",
    )


class KpiCard(BaseModel):
    label: str = Field(..., examples=["경쟁군 내 검색 점유율"])
    value: str = Field(..., examples=["42.8%"])
    delta: str | None = Field(default=None, examples=["전기 대비 +6.4%p"])
    basis: str | None = Field(default=None, examples=["네이버 데이터랩 구간 합산"])


class SlideBullet(BaseModel):
    claim: str = Field(..., examples=["민감성 피부 소비자 사이에서 저자극 진정 체감 만족도가 높게 형성됨"])
    evidence_quote: str | None = Field(default=None, examples=["\"환절기마다 뒤집어지는데 3일 쓰니까 붉은기가 확 가라앉았어요\""])
    source_name: str | None = Field(default=None, examples=["더쿠 뷰티방"])
    source_url: str | None = None
    fact_id: str | None = None


class SlideTable(BaseModel):
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class SlideVisualAsset(BaseModel):
    asset_type: str = Field(..., examples=["DATALAB_TREND_CHART"])
    title: str
    local_path: str | None = None
    caption: str | None = None
    annotation_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AsIsToBeContent(BaseModel):
    as_is_points: list[str] = Field(default_factory=list)
    key_issues: list[str] = Field(default_factory=list)
    to_be_directions: list[str] = Field(default_factory=list)
    linked_fact_ids: list[str] = Field(default_factory=list)


class SlideDraftResponse(BaseModel):
    id: str
    project_id: str
    section_code: SectionCode
    slide_order: int
    slide_type: str
    title: str
    headcopy: str
    kpi_cards: list[KpiCard] = Field(default_factory=list)
    bullets: list[SlideBullet] = Field(default_factory=list)
    table: SlideTable | None = None
    visual_assets: list[SlideVisualAsset] = Field(default_factory=list)
    as_is_to_be: AsIsToBeContent | None = None
    footnote: str | None = None
    review_status: SlideReviewStatus
    latest_comment_status: str | None = None
    updated_at: datetime


class SlideDraftUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    headcopy: str | None = Field(default=None, min_length=1, max_length=400)
    kpi_cards: list[KpiCard] | None = None
    bullets: list[SlideBullet] | None = None
    table: SlideTable | None = None
    as_is_to_be: AsIsToBeContent | None = None
    footnote: str | None = Field(default=None, max_length=500)
    review_status: SlideReviewStatus | None = None


class ApplyCommentRequest(BaseModel):
    raw_comment: str = Field(
        ...,
        min_length=2,
        max_length=2000,
        examples=["초보 입문자 타겟 언급이 부족하니 2030 첫 안티에이징 니즈와 가성비 비교 관점을 리드 문장에 반영해줘"],
    )
    auto_apply: bool = Field(
        default=False,
        description="false면 변경 전/후 Diff 프리뷰(PREVIEW_READY)만 반환, true면 즉시 슬라이드에 반영",
    )


class CommentDiffPayload(BaseModel):
    headcopy: str
    bullets: list[SlideBullet] = Field(default_factory=list)
    as_is_to_be: AsIsToBeContent | None = None


class CommentDiffResponse(BaseModel):
    comment_id: str
    slide_id: str
    raw_comment: str
    refined_comment: str
    status: str
    before_draft: CommentDiffPayload
    after_draft: CommentDiffPayload


class CommentDecisionRequest(BaseModel):
    decision: Literal["APPLY", "REVERT"]


class SummarySplitUpdateRequest(BaseModel):
    summary_split_mode: SummarySplitMode = Field(
        ...,
        description="SPLIT_2(2장 분할) 또는 SPLIT_4(4장 분할) — 1장 과밀 압축 방지",
    )


class SectionBulkApproveResponse(BaseModel):
    section_code: SectionCode
    approved_slide_count: int
