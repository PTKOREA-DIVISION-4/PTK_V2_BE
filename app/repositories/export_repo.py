from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import ExportRecord


class ExportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, record: ExportRecord) -> ExportRecord:
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_id(self, project_id: str, export_id: str) -> ExportRecord | None:
        stmt = select(ExportRecord).where(
            ExportRecord.id == export_id, ExportRecord.project_id == project_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_project(self, project_id: str) -> list[ExportRecord]:
        stmt = (
            select(ExportRecord)
            .where(ExportRecord.project_id == project_id)
            .order_by(ExportRecord.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())
