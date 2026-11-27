from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import (
    AnalysisTrack,
    KeywordGroupType,
    OwnerType,
    ProjectStage,
    SnsPlatform,
    SummarySplitMode,
    WorkflowMeta,
)


def detect_sns_platform(url: str) -> SnsPlatform:
    host = (urlparse(url).netloc or "").lower()
    if "instagram.com" in host:
        return SnsPlatform.INSTAGRAM
    if "youtube.com" in host or "youtu.be" in host:
        return SnsPlatform.YOUTUBE
    if "tiktok.com" in host:
        return SnsPlatform.TIKTOK
    return SnsPlatform.OTHER


def extract_handle_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return parsed.netloc
    return parts[-1].lstrip("@") or parsed.netloc


class CompetitorTargetInput(BaseModel):
    brand_name: str = Field(..., min_length=1, max_length=120, examples=["라네즈"])
    product_name: str = Field(..., min_length=1, max_length=150, examples=["워터뱅크 블루 히알루로닉 크림"])


class CompetitorTargetResponse(CompetitorTargetInput):
    id: str
    display_order: int = 0


class SnsAccountInput(BaseModel):
    owner_type: OwnerType = Field(..., examples=["OWN"])
    brand_label: str = Field(..., min_length=1, max_length=120, examples=["설화수"])
    platform: SnsPlatform | None = Field(
        default=None,
        description="미입력 시 URL에서 자동 감지(INSTAGRAM/YOUTUBE/TIKTOK)",
    )
    account_url: str = Field(
        ...,
        min_length=8,
        max_length=512,
        examples=["https://www.instagram.com/sulwhasoo.official/"],
    )
    handle: str | None = Field(default=None, max_length=120)

    @field_validator("account_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("올바른 http/https SNS 계정 URL을 입력해 주세요.")
        return value.strip()

    @model_validator(mode="after")
    def populate_defaults(self) -> "SnsAccountInput":
        if self.platform is None:
            self.platform = detect_sns_platform(self.account_url)
        if not self.handle:
            self.handle = extract_handle_from_url(self.account_url)
        return self


class SnsAccountResponse(BaseModel):
    id: str
    owner_type: OwnerType
    competitor_id: str | None = None
    brand_label: str
    platform: SnsPlatform
    account_url: str
    handle: str


class KeywordGroupInput(BaseModel):
    group_type: KeywordGroupType = Field(..., examples=["OWN"])
    label: str = Field(..., min_length=1, max_length=120, examples=["자사 브랜드·제품 키워드"])
    keywords: list[str] = Field(default_factory=list, examples=[["설화수", "윤조에센스", "윤조에센스 6세대"]])
    hashtags: list[str] = Field(default_factory=list, examples=[["#설화수", "#윤조에센스"]])


class KeywordGroupResponse(KeywordGroupInput):
    id: str


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200, examples=["2026 Q4 설화수 윤조에센스 팩트북"])
    brand_name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="단일 타겟 브랜드명",
        examples=["설화수"],
    )
    product_name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="단일 주력 제품 또는 히어로 라인명",
        examples=["윤조에센스 6세대"],
    )
    industry_category: str = Field(
        ...,
        min_length=1,
        max_length=80,
        description="산업군 (예: 뷰티/화장품, F&B, 패션, 금융/보험, IT/플랫폼, 가전, 자동차)",
        examples=["뷰티/화장품"],
    )
    analysis_track: AnalysisTrack | None = Field(
        default=None,
        description="미지정 시 산업군에 따라 REVIEW_CENTRIC 또는 MARKET_CENTRIC 자동 매핑",
    )
    period_start: date = Field(..., examples=["2026-06-01"])
    period_end: date = Field(..., examples=["2026-11-25"])
    naver_shopping_category_id: str | None = Field(
        default=None,
        description="네이버 쇼핑 인사이트 카테고리 ID (예: 50000002 화장품/미용)",
        examples=["50000002"],
    )
    competitors: list[CompetitorTargetInput] = Field(
        default_factory=list,
        max_length=4,
        description="비교 경쟁 브랜드+제품 페어 (권장 2~4개)",
    )
    sns_accounts: list[SnsAccountInput] = Field(default_factory=list)
    keyword_groups: list[KeywordGroupInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_period_and_single_target(self) -> "ProjectCreateRequest":
        if self.period_end < self.period_start:
            raise ValueError("조사 종료일(period_end)은 시작일(period_start) 이후여야 합니다.")
        if any(sep in self.brand_name for sep in [",", "/"]):
            raise ValueError("단일 브랜드 원칙에 따라 brand_name에는 하나의 브랜드만 입력해 주세요.")
        return self


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    industry_category: str | None = None
    analysis_track: AnalysisTrack | None = None
    period_start: date | None = None
    period_end: date | None = None
    naver_shopping_category_id: str | None = None
    competitors: list[CompetitorTargetInput] | None = Field(default=None, max_length=4)
    sns_accounts: list[SnsAccountInput] | None = None
    keyword_groups: list[KeywordGroupInput] | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    brand_name: str
    product_name: str
    industry_category: str
    analysis_track: AnalysisTrack
    period_start: date
    period_end: date
    current_stage: ProjectStage
    summary_split_mode: SummarySplitMode
    naver_shopping_category_id: str | None = None
    competitors: list[CompetitorTargetResponse] = Field(default_factory=list)
    sns_accounts: list[SnsAccountResponse] = Field(default_factory=list)
    keyword_groups: list[KeywordGroupResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProjectSummaryResponse(BaseModel):
    project: ProjectResponse
    workflow_meta: WorkflowMeta
    api_readiness: dict[str, bool] = Field(
        default_factory=dict,
        description="백엔드 외부 API 키 설정 준비 여부 (키 값은 노출되지 않음)",
    )


class KeywordRecommendRequest(BaseModel):
    brand_name: str = Field(..., min_length=1, examples=["설화수"])
    product_name: str = Field(..., min_length=1, examples=["윤조에센스 6세대"])
    industry_category: str = Field(..., min_length=1, examples=["뷰티/화장품"])
    competitor_brands: list[str] = Field(default_factory=list, examples=[["라네즈", "헤라"]])


class KeywordRecommendResponse(BaseModel):
    recommended_groups: list[KeywordGroupInput]
    suggested_naver_shopping_category_id: str | None = None
    suggested_analysis_track: AnalysisTrack
