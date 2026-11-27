from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.job import AsyncJob


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, job_id: str) -> AsyncJob | None:
        stmt = (
            select(AsyncJob)
            .options(selectinload(AsyncJob.subtasks))
            .where(AsyncJob.id == job_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_project(self, project_id: str) -> list[AsyncJob]:
        stmt = (
            select(AsyncJob)
            .options(selectinload(AsyncJob.subtasks))
            .where(AsyncJob.project_id == project_id)
            .order_by(AsyncJob.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())
