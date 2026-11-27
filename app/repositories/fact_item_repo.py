from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.factbook import FactItem


class FactItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_project(
        self, project_id: str, *, section_code: str | None = None
    ) -> list[FactItem]:
        stmt = select(FactItem).where(FactItem.project_id == project_id)
        if section_code:
            stmt = stmt.where(FactItem.section_code == section_code)
        stmt = stmt.order_by(FactItem.section_code, FactItem.created_at)
        return list((await self.session.execute(stmt)).scalars().all())

    async def replace_for_project(self, project_id: str, items: list[FactItem]) -> None:
        await self.session.execute(
            delete(FactItem).where(FactItem.project_id == project_id)
        )
        self.session.add_all(items)
        await self.session.flush()
