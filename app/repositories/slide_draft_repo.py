from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.factbook import PlannerComment, SlideDraft


class SlideDraftRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_project(self, project_id: str) -> list[SlideDraft]:
        stmt = (
            select(SlideDraft)
            .options(selectinload(SlideDraft.comments))
            .where(SlideDraft.project_id == project_id)
            .order_by(SlideDraft.slide_order)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_id(self, project_id: str, slide_id: str) -> SlideDraft | None:
        stmt = (
            select(SlideDraft)
            .options(selectinload(SlideDraft.comments))
            .where(SlideDraft.id == slide_id, SlideDraft.project_id == project_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def replace_all_slides(
        self, project_id: str, slides: list[SlideDraft]
    ) -> list[SlideDraft]:
        await self.session.execute(
            delete(SlideDraft).where(SlideDraft.project_id == project_id)
        )
        self.session.add_all(slides)
        await self.session.flush()
        return slides

    async def replace_section_slides(
        self, project_id: str, section_code: str, slides: list[SlideDraft]
    ) -> None:
        await self.session.execute(
            delete(SlideDraft).where(
                SlideDraft.project_id == project_id,
                SlideDraft.section_code == section_code,
            )
        )
        self.session.add_all(slides)
        await self.session.flush()

    async def approve_section(self, project_id: str, section_code: str) -> int:
        stmt = (
            update(SlideDraft)
            .where(
                SlideDraft.project_id == project_id,
                SlideDraft.section_code == section_code,
            )
            .values(review_status="APPROVED")
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        return int(res.rowcount or 0)

    async def get_comment(
        self, project_id: str, slide_id: str, comment_id: str
    ) -> PlannerComment | None:
        stmt = select(PlannerComment).where(
            PlannerComment.id == comment_id,
            PlannerComment.slide_id == slide_id,
            PlannerComment.project_id == project_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
