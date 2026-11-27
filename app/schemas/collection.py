from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import OwnerType, ReviewStatus, SectionCode, SnsPlatform


class CollectionRunRequest(BaseModel):
    force_refresh: bool = Field(
        default=False,
        description="true일 경우 24시간 응답 캐시를 무시하고 외부 API를 새로 호출",
    )
    selected_sources: list[str] | None = Field(
        default=None,
        description="특정 서브태스크만 실행할 때 지정 (미지정 시 조사 계획 기반 전체 실행)",
        examples=[["perplexity_research", "naver_datalab", "sns_official_top5", "creator_collab", "community_voc"]],
    )


class CollectionRetryRequest(BaseModel):
    subtask_keys: list[str] = Field(
        ...,
        min_length=1,
        description="재시도할 실패/부족 서브태스크 키 목록",
        examples=[["community_voc", "sns_official_top5"]],
    )
    force_refresh: bool = True


class HighlightSpan(BaseModel):
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    quote: str


class MediaAssetResponse(BaseModel):
    id: str
    asset_type: str
    original_url: str | None = None
    local_path: str
    caption: str | None = None
    annotation_text: str | None = None
    width: int = 0
    height: int = 0
    is_valid: bool = True


class SourceItemSummary(BaseModel):
    id: str
    section_code: SectionCode
    provider: str
    channel: str
    title: str
    source_url: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    evidence_quote: str | None = None
    sentiment: str
    review_status: ReviewStatus
    has_media: bool = False


class SourceItemDetail(SourceItemSummary):
    content: str
    highlight_spans: list[HighlightSpan] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    media_assets: list[MediaAssetResponse] = Field(default_factory=list)


class SourceFacetCounts(BaseModel):
    total: int = 0
    by_review_status: dict[str, int] = Field(default_factory=dict)
    by_section: dict[str, int] = Field(default_factory=dict)
    by_channel: dict[str, int] = Field(default_factory=dict)
    by_provider: dict[str, int] = Field(default_factory=dict)


class SourceListResponse(BaseModel):
    items: list[SourceItemSummary]
    facets: SourceFacetCounts
    total: int
    page: int
    page_size: int


class SourceBulkUpdateRequest(BaseModel):
    source_ids: list[str] = Field(
        default_factory=list,
        description="대상 소스 ID 목록 (filter_all_matching=true일 경우 생략 가능)",
    )
    review_status: ReviewStatus = Field(..., examples=["APPROVED"])
    filter_section: SectionCode | None = None
    filter_channel: str | None = None
    filter_all_matching: bool = Field(
        default=False,
        description="현재 필터 조건에 해당하는 항목 전체를 일괄 채택/제외할 때 true",
    )


class SourceBulkUpdateResponse(BaseModel):
    updated_count: int
    review_status: ReviewStatus
    facets: SourceFacetCounts


class DataLabPoint(BaseModel):
    period: str
    ratio: float


class DataLabSeriesResponse(BaseModel):
    id: str
    metric_type: str
    group_label: str
    owner_type: OwnerType
    period_start: date
    period_end: date
    time_unit: str
    points: list[DataLabPoint]
    cumulative_index_sum: float
    share_of_search_pct: float
    growth_rate_pct: float
    peak_date: str | None = None
    peak_value: float
    methodology_note: str


class DataLabOverviewResponse(BaseModel):
    project_id: str
    search_trends: list[DataLabSeriesResponse] = Field(default_factory=list)
    shopping_insights: list[DataLabSeriesResponse] = Field(default_factory=list)
    methodology_summary: str


class SnsTopPostResponse(BaseModel):
    id: str
    owner_type: OwnerType
    brand_label: str
    platform: SnsPlatform
    post_url: str
    caption: str
    published_at: datetime
    views: int
    likes: int
    comments: int
    engagement_score: float
    rank_order: int
    is_creator_collab: bool
    media_asset: MediaAssetResponse | None = None
    key_takeaway: str | None = None


class SnsTopPostsOverviewResponse(BaseModel):
    project_id: str
    period_start: date
    period_end: date
    own_top_posts: list[SnsTopPostResponse] = Field(default_factory=list)
    competitor_top_posts: list[SnsTopPostResponse] = Field(default_factory=list)
    creator_collabs: list[SnsTopPostResponse] = Field(default_factory=list)
