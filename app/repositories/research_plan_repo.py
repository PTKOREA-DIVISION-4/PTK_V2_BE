from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.research_plan import ResearchPlan


class ResearchPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_project_id(self, project_id: str) -> ResearchPlan | None:
        stmt = (
            select(ResearchPlan)
            .options(selectinload(ResearchPlan.items))
            .where(ResearchPlan.project_id == project_id)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def save(self, plan: ResearchPlan) -> ResearchPlan:
        self.session.add(plan)
        await self.session.flush()
        return plan
