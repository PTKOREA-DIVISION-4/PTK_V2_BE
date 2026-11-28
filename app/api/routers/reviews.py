from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_db,
    get_idempotency_key,
    get_job_manager,
    get_session_factory,
)
from app.api.routers.jobs import _to_response as job_to_response
from app.core.exceptions import NotFoundError
from app.core.job_manager import JobContext, JobManager
from app.models.project import Project
from app.repositories.job_repo import JobRepository
from app.schemas.common import ErrorEnvelope, SectionCode
from app.schemas.job import JobStatusResponse
from app.schemas.review import (
    ApplyCommentRequest,
    CommentDecisionRequest,
    CommentDiffResponse,
    SectionBulkApproveResponse,
    SlideDraftResponse,
    SlideDraftUpdateRequest,
    SlideGenerateRequest,
    SummarySplitUpdateRequest,
)
from app.services.llm_structuring_service import (
    SLIDE_GENERATION_SUBTASKS,
    LlmStructuringService,
)
from app.services.review_service import ReviewService

router = APIRouter(prefix="/projects/{project_id}", tags=["Step 3. Slide Review & Planner Comments"])


@router.post(
    "/slides/generate",
    response_model=list[SlideDraftResponse],
    responses={404: {"model": ErrorEnvelope}},
    summary="채택된 자료 기반 0~5장 표준 목차 슬라이드 초안 생성",
)
async def generate_slides(
    project_id: str,
    payload: SlideGenerateRequest = SlideGenerateRequest(),
    db: AsyncSession = Depends(get_db),
) -> list[SlideDraftResponse]:
    slides = await LlmStructuringService(db).generate_slides(
        project_id,
        summary_split_mode=payload.summary_split_mode,
        use_approved_only=payload.use_approved_only,
    )
    return [ReviewService.slide_to_response(s) for s in slides]


@router.post(
    "/slides/generate-async",
    response_model=JobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={404: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}},
    summary="비동기 실시간 장표 생성 시작 (Job ID 즉시 반환 및 중간 스냅샷 반영)",
)
async def generate_slides_async(
    project_id: str,
    payload: SlideGenerateRequest = SlideGenerateRequest(),
    db: AsyncSession = Depends(get_db),
    job_manager: JobManager = Depends(get_job_manager),
    session_factory=Depends(get_session_factory),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> JobStatusResponse:
    project = await db.get(Project, project_id)
    if not project:
        raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")

    async def _runner(ctx: JobContext) -> None:
        async with session_factory() as s:
            await LlmStructuringService(s).generate_slides_with_progress(
                project_id,
                ctx,
                summary_split_mode=payload.summary_split_mode,
                use_approved_only=payload.use_approved_only,
            )

    job = await job_manager.start_job(
        db,
        project_id=project_id,
        job_type="SLIDE_GENERATION",
        subtasks=SLIDE_GENERATION_SUBTASKS,
        coro_factory=_runner,
        idempotency_key=idempotency_key,
    )
    return job_to_response(job)


@router.get(
    "/slides/generation-status",
    response_model=JobStatusResponse | None,
    responses={404: {"model": ErrorEnvelope}},
    summary="가장 최근 장표 생성 비동기 작업 상태 조회",
)
async def get_slide_generation_status(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> JobStatusResponse | None:
    project = await db.get(Project, project_id)
    if not project:
        raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")
    jobs = await JobRepository(db).list_by_project(project_id)
    latest = next((j for j in jobs if j.job_type == "SLIDE_GENERATION"), None)
    return job_to_response(latest) if latest else None


@router.get(
    "/slides",
    response_model=list[SlideDraftResponse],
    responses={404: {"model": ErrorEnvelope}},
    summary="0~5장 슬라이드 초안 전체 조회",
)
async def list_slides(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[SlideDraftResponse]:
    return await ReviewService(db).list_slides(project_id)


@router.patch(
    "/slides/{slide_id}",
    response_model=SlideDraftResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="슬라이드 리드 문장·핵심 팩트·표·결론 수동 편집",
)
async def update_slide(
    project_id: str,
    slide_id: str,
    payload: SlideDraftUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> SlideDraftResponse:
    return await ReviewService(db).update_slide(project_id, slide_id, payload)


@router.post(
    "/slides/{slide_id}/apply-comment",
    response_model=CommentDiffResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="기획자 코멘트 AI 윤문 및 변경 전/후 Diff 반환",
)
async def apply_comment(
    project_id: str,
    slide_id: str,
    payload: ApplyCommentRequest,
    db: AsyncSession = Depends(get_db),
) -> CommentDiffResponse:
    return await ReviewService(db).apply_comment(project_id, slide_id, payload)


@router.post(
    "/slides/{slide_id}/comments/{comment_id}/decide",
    response_model=SlideDraftResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="코멘트 윤문 결과 최종 반영(APPLY) 또는 원복(REVERT)",
)
async def decide_comment(
    project_id: str,
    slide_id: str,
    comment_id: str,
    payload: CommentDecisionRequest,
    db: AsyncSession = Depends(get_db),
) -> SlideDraftResponse:
    return await ReviewService(db).decide_comment(project_id, slide_id, comment_id, payload)


@router.patch(
    "/summary-split",
    response_model=list[SlideDraftResponse],
    responses={404: {"model": ErrorEnvelope}},
    summary="5. 현황 요약(Summary) 2장 분할 ↔ 4장 분할 모드 전환",
)
async def update_summary_split(
    project_id: str,
    payload: SummarySplitUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> list[SlideDraftResponse]:
    return await ReviewService(db).update_summary_split(project_id, payload.summary_split_mode)


@router.post(
    "/sections/{section_code}/approve",
    response_model=SectionBulkApproveResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="특정 섹션 내 슬라이드 일괄 검토 완료 처리",
)
async def approve_section(
    project_id: str,
    section_code: SectionCode,
    db: AsyncSession = Depends(get_db),
) -> SectionBulkApproveResponse:
    return await ReviewService(db).approve_section(project_id, section_code)
