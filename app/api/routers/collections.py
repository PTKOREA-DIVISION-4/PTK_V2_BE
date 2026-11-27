from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_db,
    get_idempotency_key,
    get_job_manager,
    get_session_factory,
)
from app.core.exceptions import NotFoundError
from app.core.job_manager import JobManager
from app.repositories.project_repo import ProjectRepository
from app.repositories.source_item_repo import SourceItemRepository
from app.schemas.collection import (
    CollectionRetryRequest,
    CollectionRunRequest,
    DataLabOverviewResponse,
    DataLabPoint,
    DataLabSeriesResponse,
    MediaAssetResponse,
    SourceBulkUpdateRequest,
    SourceBulkUpdateResponse,
    SourceItemDetail,
    SourceListResponse,
    SnsTopPostResponse,
    SnsTopPostsOverviewResponse,
)
from app.schemas.common import ErrorEnvelope, OwnerType, ReviewStatus, SectionCode, SnsPlatform
from app.schemas.job import JobStatusResponse
from app.services.collection_orchestrator import CollectionOrchestrator
from app.services.review_service import ReviewService

router = APIRouter(prefix="/projects/{project_id}", tags=["Step 2. Data Collection & Bulk Review"])


@router.post(
    "/collections/run",
    response_model=JobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={404: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}},
    summary="다중 소스 비동기 수집 파이프라인 실행 (Job ID 즉시 반환)",
)
async def run_collection(
    project_id: str,
    payload: CollectionRunRequest = CollectionRunRequest(),
    db: AsyncSession = Depends(get_db),
    job_manager: JobManager = Depends(get_job_manager),
    session_factory=Depends(get_session_factory),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> JobStatusResponse:
    orchestrator = CollectionOrchestrator(session_factory, job_manager)
    job = await orchestrator.start_collection(
        db, project_id=project_id, payload=payload, idempotency_key=idempotency_key
    )
    return _job_to_schema(job)


@router.post(
    "/collections/retry",
    response_model=JobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={404: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}},
    summary="실패 또는 선택한 소스만 부분 재수집",
)
async def retry_collection(
    project_id: str,
    payload: CollectionRetryRequest,
    db: AsyncSession = Depends(get_db),
    job_manager: JobManager = Depends(get_job_manager),
    session_factory=Depends(get_session_factory),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> JobStatusResponse:
    orchestrator = CollectionOrchestrator(session_factory, job_manager)
    job = await orchestrator.retry_subtasks(
        db, project_id=project_id, payload=payload, idempotency_key=idempotency_key
    )
    return _job_to_schema(job)


@router.get(
    "/sources",
    response_model=SourceListResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="수집 원문 인덱스, 필터별 카운트(Facets), 근거 문장 목록 조회",
)
async def list_sources(
    project_id: str,
    section_code: SectionCode | None = None,
    channel: str | None = None,
    provider: str | None = None,
    review_status: ReviewStatus | None = None,
    q: str | None = Query(default=None, description="제목/본문 검색어"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> SourceListResponse:
    return await ReviewService(db).list_sources(
        project_id,
        section_code=section_code,
        channel=channel,
        provider=provider,
        review_status=review_status,
        search_query=q,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/sources/{source_id}",
    response_model=SourceItemDetail,
    responses={404: {"model": ErrorEnvelope}},
    summary="수집 원문 전문, 하이라이트 좌표(highlight_spans), 참조 이미지 상세 조회",
)
async def get_source_detail(
    project_id: str,
    source_id: str,
    db: AsyncSession = Depends(get_db),
) -> SourceItemDetail:
    return await ReviewService(db).get_source_detail(project_id, source_id)


@router.patch(
    "/sources/bulk",
    response_model=SourceBulkUpdateResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="수집 자료 일괄 채택(APPROVED) / 일괄 제외(REJECTED)",
)
async def bulk_update_sources(
    project_id: str,
    payload: SourceBulkUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> SourceBulkUpdateResponse:
    return await ReviewService(db).bulk_update_sources(project_id, payload)


@router.get(
    "/datalab",
    response_model=DataLabOverviewResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="네이버 데이터랩 검색량 추이·점유율(SoS)·산출 기준 조회",
)
async def get_datalab_overview(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> DataLabOverviewResponse:
    project = await ProjectRepository(db).get_by_id(project_id)
    if not project:
        raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")
    series = await SourceItemRepository(db).list_datalab(project_id)
    search = []
    shopping = []
    for s in series:
        dto = DataLabSeriesResponse(
            id=s.id,
            metric_type=s.metric_type,
            group_label=s.group_label,
            owner_type=OwnerType(s.owner_type),
            period_start=s.period_start,
            period_end=s.period_end,
            time_unit=s.time_unit,
            points=[DataLabPoint.model_validate(p) for p in (s.points_json or [])],
            cumulative_index_sum=s.cumulative_index_sum,
            share_of_search_pct=s.share_of_search_pct,
            growth_rate_pct=s.growth_rate_pct,
            peak_date=s.peak_date,
            peak_value=s.peak_value,
            methodology_note=s.methodology_note,
        )
        if s.metric_type == "SHOPPING_INSIGHT":
            shopping.append(dto)
        else:
            search.append(dto)

    summary_note = (
        search[0].methodology_note
        if search
        else f"출처: 네이버 데이터랩 | 기간: {project.period_start}~{project.period_end} | 기준: 비교군 최댓값=100 상대지수"
    )
    return DataLabOverviewResponse(
        project_id=project_id,
        search_trends=search,
        shopping_insights=shopping,
        methodology_summary=summary_note,
    )


@router.get(
    "/sns-top5",
    response_model=SnsTopPostsOverviewResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="자사·경쟁사 기간 내 인기 게시물 TOP 5 및 크리에이터 협업 목록 조회",
)
async def get_sns_top5(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> SnsTopPostsOverviewResponse:
    project = await ProjectRepository(db).get_by_id(project_id)
    if not project:
        raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")
    repo = SourceItemRepository(db)
    posts = await repo.list_sns_top_posts(project_id)
    assets = {a.id: a for a in await repo.list_media_assets(project_id)}

    own: list[SnsTopPostResponse] = []
    comp: list[SnsTopPostResponse] = []
    collab: list[SnsTopPostResponse] = []

    for p in posts:
        m = assets.get(p.media_asset_id) if p.media_asset_id else None
        dto = SnsTopPostResponse(
            id=p.id,
            owner_type=OwnerType(p.owner_type),
            brand_label=p.brand_label,
            platform=SnsPlatform(p.platform),
            post_url=p.post_url,
            caption=p.caption,
            published_at=p.published_at,
            views=p.views,
            likes=p.likes,
            comments=p.comments,
            engagement_score=p.engagement_score,
            rank_order=p.rank_order,
            is_creator_collab=p.is_creator_collab,
            media_asset=(
                MediaAssetResponse(
                    id=m.id,
                    asset_type=m.asset_type,
                    original_url=m.original_url,
                    local_path=m.local_path,
                    caption=m.caption,
                    annotation_text=m.annotation_text,
                    width=m.width,
                    height=m.height,
                    is_valid=m.is_valid,
                )
                if m
                else None
            ),
            key_takeaway=p.key_takeaway,
        )
        if p.is_creator_collab:
            collab.append(dto)
        elif p.owner_type == "OWN":
            own.append(dto)
        else:
            comp.append(dto)

    return SnsTopPostsOverviewResponse(
        project_id=project_id,
        period_start=project.period_start,
        period_end=project.period_end,
        own_top_posts=own,
        competitor_top_posts=comp,
        creator_collabs=collab,
    )


def _job_to_schema(job) -> JobStatusResponse:
    return JobStatusResponse(
        id=job.id,
        project_id=job.project_id,
        job_type=job.job_type,
        status=job.status,
        progress_pct=job.progress_pct,
        logs=list(job.logs_json or []),
        error_message=job.error_message,
        subtasks=[
            {
                "id": s.id,
                "subtask_key": s.subtask_key,
                "label": s.label,
                "status": s.status,
                "progress_pct": s.progress_pct,
                "collected_count": s.collected_count,
                "error_message": s.error_message,
            }
            for s in (job.subtasks or [])
        ],
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
    )
