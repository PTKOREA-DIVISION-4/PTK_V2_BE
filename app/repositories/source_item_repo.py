from __future__ import annotations

from collections import Counter

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.collection import DataLabSeries, MediaAsset, RawSourceItem, SnsTopPost


class SourceItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, project_id: str, source_id: str) -> RawSourceItem | None:
        stmt = (
            select(RawSourceItem)
            .options(selectinload(RawSourceItem.media_assets))
            .where(RawSourceItem.id == source_id, RawSourceItem.project_id == project_id)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_sources(
        self,
        project_id: str,
        *,
        section_code: str | None = None,
        channel: str | None = None,
        provider: str | None = None,
        review_status: str | None = None,
        search_query: str | None = None,
        page: int = 1,
        page_size: int = 30,
    ) -> tuple[list[RawSourceItem], int]:
        stmt = (
            select(RawSourceItem)
            .options(selectinload(RawSourceItem.media_assets))
            .where(RawSourceItem.project_id == project_id)
        )
        count_stmt = select(func.count(RawSourceItem.id)).where(
            RawSourceItem.project_id == project_id
        )

        filters = []
        if section_code:
            filters.append(RawSourceItem.section_code == section_code)
        if channel:
            filters.append(RawSourceItem.channel == channel)
        if provider:
            filters.append(RawSourceItem.provider == provider)
        if review_status:
            filters.append(RawSourceItem.review_status == review_status)
        if search_query:
            pattern = f"%{search_query.strip()}%"
            filters.append(
                RawSourceItem.title.ilike(pattern) | RawSourceItem.content.ilike(pattern)
            )

        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)

        total = int((await self.session.execute(count_stmt)).scalar() or 0)
        offset = max(0, (page - 1) * page_size)
        stmt = stmt.order_by(RawSourceItem.created_at.desc()).offset(offset).limit(page_size)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, total

    async def get_facets(self, project_id: str) -> dict[str, object]:
        stmt = select(
            RawSourceItem.review_status,
            RawSourceItem.section_code,
            RawSourceItem.channel,
            RawSourceItem.provider,
        ).where(RawSourceItem.project_id == project_id)
        rows = (await self.session.execute(stmt)).all()
        status_cnt = Counter(r[0] for r in rows)
        section_cnt = Counter(r[1] for r in rows)
        channel_cnt = Counter(r[2] for r in rows)
        provider_cnt = Counter(r[3] for r in rows)
        return {
            "total": len(rows),
            "by_review_status": dict(status_cnt),
            "by_section": dict(section_cnt),
            "by_channel": dict(channel_cnt),
            "by_provider": dict(provider_cnt),
        }

    async def bulk_update_status(
        self,
        project_id: str,
        *,
        review_status: str,
        source_ids: list[str] | None = None,
        filter_section: str | None = None,
        filter_channel: str | None = None,
        filter_all_matching: bool = False,
    ) -> int:
        stmt = (
            update(RawSourceItem)
            .where(RawSourceItem.project_id == project_id)
            .values(review_status=review_status)
        )
        if not filter_all_matching:
            if not source_ids:
                return 0
            stmt = stmt.where(RawSourceItem.id.in_(source_ids))
        else:
            if filter_section:
                stmt = stmt.where(RawSourceItem.section_code == filter_section)
            if filter_channel:
                stmt = stmt.where(RawSourceItem.channel == filter_channel)

        res = await self.session.execute(stmt)
        await self.session.flush()
        return int(res.rowcount or 0)

    async def list_for_synthesis(
        self, project_id: str, *, use_approved_only: bool = True
    ) -> list[RawSourceItem]:
        stmt = (
            select(RawSourceItem)
            .options(selectinload(RawSourceItem.media_assets))
            .where(RawSourceItem.project_id == project_id)
        )
        if use_approved_only:
            approved_stmt = stmt.where(RawSourceItem.review_status == "APPROVED")
            approved = list((await self.session.execute(approved_stmt)).scalars().all())
            if approved:
                return approved
        non_rejected = stmt.where(RawSourceItem.review_status != "REJECTED")
        return list((await self.session.execute(non_rejected)).scalars().all())

    async def clear_by_providers(self, project_id: str, providers: list[str]) -> None:
        await self.session.execute(
            delete(RawSourceItem).where(
                RawSourceItem.project_id == project_id,
                RawSourceItem.provider.in_(providers),
            )
        )

    async def list_datalab(self, project_id: str) -> list[DataLabSeries]:
        stmt = (
            select(DataLabSeries)
            .where(DataLabSeries.project_id == project_id)
            .order_by(DataLabSeries.metric_type, DataLabSeries.share_of_search_pct.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_sns_top_posts(self, project_id: str) -> list[SnsTopPost]:
        stmt = (
            select(SnsTopPost)
            .where(SnsTopPost.project_id == project_id)
            .order_by(SnsTopPost.owner_type, SnsTopPost.brand_label, SnsTopPost.rank_order)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_media_assets(self, project_id: str) -> list[MediaAsset]:
        stmt = select(MediaAsset).where(MediaAsset.project_id == project_id)
        return list((await self.session.execute(stmt)).scalars().all())
