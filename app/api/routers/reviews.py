from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ErrorEnvelope, SectionCode
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
from app.services.llm_structuring_service import LlmStructuringService
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
