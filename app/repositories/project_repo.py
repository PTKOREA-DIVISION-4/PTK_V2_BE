from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import CompetitorTarget, KeywordGroup, Project, SnsAccount


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, project_id: str) -> Project | None:
        stmt = (
            select(Project)
            .options(
                selectinload(Project.competitors),
                selectinload(Project.sns_accounts),
                selectinload(Project.keyword_groups),
            )
            .where(Project.id == project_id)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_all(self, *, limit: int = 50, offset: int = 0) -> list[Project]:
        stmt = (
            select(Project)
            .options(
                selectinload(Project.competitors),
                selectinload(Project.sns_accounts),
                selectinload(Project.keyword_groups),
            )
            .order_by(Project.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create(self, project: Project) -> Project:
        self.session.add(project)
        await self.session.flush()
        return project

    async def replace_children(
        self,
        project: Project,
        *,
        competitors: list[CompetitorTarget] | None = None,
        sns_accounts: list[SnsAccount] | None = None,
        keyword_groups: list[KeywordGroup] | None = None,
    ) -> None:
        if competitors is not None:
            project.competitors.clear()
            await self.session.flush()
            project.competitors.extend(competitors)
        if sns_accounts is not None:
            project.sns_accounts.clear()
            await self.session.flush()
            project.sns_accounts.extend(sns_accounts)
        if keyword_groups is not None:
            project.keyword_groups.clear()
            await self.session.flush()
            project.keyword_groups.extend(keyword_groups)

    async def delete(self, project: Project) -> None:
        await self.session.delete(project)
        await self.session.flush()
