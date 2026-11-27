from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ErrorEnvelope
from app.schemas.project import (
    KeywordRecommendRequest,
    KeywordRecommendResponse,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectSummaryResponse,
    ProjectUpdateRequest,
)
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Step 0. Project Setup"])


@router.post(
    "/recommend-keywords",
    response_model=KeywordRecommendResponse,
    summary="브랜드·제품·산업군 기반 추천 키워드 및 분석 트랙 조회",
)
async def recommend_keywords(
    payload: KeywordRecommendRequest,
) -> KeywordRecommendResponse:
    return ProjectService.recommend_keywords(payload)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": ErrorEnvelope}},
    summary="단일 브랜드·제품 기반 새 팩트북 프로젝트 생성",
)
async def create_project(
    payload: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    return await ProjectService(db).create_project(payload)


@router.get(
    "",
    response_model=list[ProjectResponse],
    summary="전체 프로젝트 목록 조회",
)
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[ProjectResponse]:
    return await ProjectService(db).list_projects()


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="프로젝트 상세 설정 조회",
)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    return await ProjectService(db).get_project_response(project_id)


@router.get(
    "/{project_id}/summary",
    response_model=ProjectSummaryResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="프로젝트 + 워크플로우 단계 가이드 메타(workflow_meta) 통합 조회",
)
async def get_project_summary(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> ProjectSummaryResponse:
    return await ProjectService(db).get_project_summary(project_id)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="프로젝트 기본 설정·경쟁사·SNS URL·키워드 수정",
)
async def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    return await ProjectService(db).update_project(project_id, payload)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorEnvelope}},
    summary="프로젝트 삭제",
)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    await ProjectService(db).delete_project(project_id)
