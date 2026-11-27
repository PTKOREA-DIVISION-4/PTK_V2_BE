from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ErrorEnvelope
from app.schemas.research_plan import ResearchPlanResponse, ResearchPlanUpdateRequest
from app.services.project_service import ProjectService
from app.services.research_plan_service import ResearchPlanService

router = APIRouter(prefix="/projects/{project_id}/research-plan", tags=["Step 1. Research Plan"])


@router.get(
    "",
    response_model=ResearchPlanResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="산업군 분기가 적용된 0~5장 조사 계획 조회",
)
async def get_research_plan(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> ResearchPlanResponse:
    plan = await ResearchPlanService(db).get_plan(project_id)
    project = await ProjectService(db).get_project(project_id)
    plan.workflow_meta = await ProjectService(db).get_workflow_meta(project)
    return plan


@router.put(
    "",
    response_model=ResearchPlanResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="조사 항목 선택·커뮤니티·데이터랩 그룹 확정 저장",
)
async def update_research_plan(
    project_id: str,
    payload: ResearchPlanUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> ResearchPlanResponse:
    plan = await ResearchPlanService(db).update_plan(project_id, payload)
    project = await ProjectService(db).get_project(project_id)
    plan.workflow_meta = await ProjectService(db).get_workflow_meta(project)
    return plan
