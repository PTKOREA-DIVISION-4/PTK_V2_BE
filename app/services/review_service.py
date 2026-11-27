from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.factbook import SlideDraft
from app.models.project import Project
from app.repositories.project_repo import ProjectRepository
from app.repositories.slide_draft_repo import SlideDraftRepository
from app.repositories.source_item_repo import SourceItemRepository
from app.schemas.collection import (
    HighlightSpan,
    MediaAssetResponse,
    SourceBulkUpdateRequest,
    SourceBulkUpdateResponse,
    SourceFacetCounts,
    SourceItemDetail,
    SourceItemSummary,
    SourceListResponse,
)
from app.schemas.common import ReviewStatus, SectionCode, SlideReviewStatus, SummarySplitMode
from app.schemas.review import (
    ApplyCommentRequest,
    AsIsToBeContent,
    CommentDecisionRequest,
    CommentDiffPayload,
    CommentDiffResponse,
    KpiCard,
    SectionBulkApproveResponse,
    SlideBullet,
    SlideDraftResponse,
    SlideDraftUpdateRequest,
    SlideTable,
    SlideVisualAsset,
)
from app.services.llm_structuring_service import LlmStructuringService


class ReviewService:
    """Manages source bulk approval/rejection, slide draft editing, and planner comment Diff/Apply."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.project_repo = ProjectRepository(session)
        self.source_repo = SourceItemRepository(session)
        self.slide_repo = SlideDraftRepository(session)
        self.structuring = LlmStructuringService(session)

    async def list_sources(
        self,
        project_id: str,
        *,
        section_code: SectionCode | None = None,
        channel: str | None = None,
        provider: str | None = None,
        review_status: ReviewStatus | None = None,
        search_query: str | None = None,
        page: int = 1,
        page_size: int = 30,
    ) -> SourceListResponse:
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")

        rows, total = await self.source_repo.list_sources(
            project_id,
            section_code=section_code.value if section_code else None,
            channel=channel,
            provider=provider,
            review_status=review_status.value if review_status else None,
            search_query=search_query,
            page=page,
            page_size=page_size,
        )
        facets_raw = await self.source_repo.get_facets(project_id)
        facets = SourceFacetCounts.model_validate(facets_raw)
        summaries = [
            SourceItemSummary(
                id=r.id,
                section_code=SectionCode(r.section_code),
                provider=r.provider,
                channel=r.channel,
                title=r.title,
                source_url=r.source_url,
                author=r.author,
                published_at=r.published_at,
                evidence_quote=r.evidence_quote,
                sentiment=r.sentiment,
                review_status=ReviewStatus(r.review_status),
                has_media=bool(r.media_assets),
            )
            for r in rows
        ]
        return SourceListResponse(
            items=summaries,
            facets=facets,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_source_detail(self, project_id: str, source_id: str) -> SourceItemDetail:
        item = await self.source_repo.get_by_id(project_id, source_id)
        if not item:
            raise NotFoundError(f"수집 원문({source_id})을 찾을 수 없습니다.")
        return SourceItemDetail(
            id=item.id,
            section_code=SectionCode(item.section_code),
            provider=item.provider,
            channel=item.channel,
            title=item.title,
            content=item.content,
            source_url=item.source_url,
            author=item.author,
            published_at=item.published_at,
            evidence_quote=item.evidence_quote,
            highlight_spans=[
                HighlightSpan.model_validate(s) for s in (item.highlight_spans or [])
            ],
            sentiment=item.sentiment,
            review_status=ReviewStatus(item.review_status),
            has_media=bool(item.media_assets),
            metadata_json=dict(item.metadata_json or {}),
            media_assets=[
                MediaAssetResponse(
                    id=m.id,
                    asset_type=m.asset_type,
                    original_url=m.original_url,
                    local_path=m.local_path,
                    caption=m.caption,
                    annotation_text=m.annotation_text,
                    width=m.width,
                    height=m.height,
                    is_valid=m.is_valid,
                )
                for m in (item.media_assets or [])
            ],
        )

    async def bulk_update_sources(
        self, project_id: str, payload: SourceBulkUpdateRequest
    ) -> SourceBulkUpdateResponse:
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")

        updated = await self.source_repo.bulk_update_status(
            project_id,
            review_status=payload.review_status.value,
            source_ids=payload.source_ids,
            filter_section=payload.filter_section.value if payload.filter_section else None,
            filter_channel=payload.filter_channel,
            filter_all_matching=payload.filter_all_matching,
        )
        await self.session.commit()
        facets = SourceFacetCounts.model_validate(
            await self.source_repo.get_facets(project_id)
        )
        return SourceBulkUpdateResponse(
            updated_count=updated,
            review_status=payload.review_status,
            facets=facets,
        )

    async def list_slides(self, project_id: str) -> list[SlideDraftResponse]:
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")
        slides = await self.slide_repo.list_by_project(project_id)
        return [self.slide_to_response(s) for s in slides]

    async def update_slide(
        self, project_id: str, slide_id: str, payload: SlideDraftUpdateRequest
    ) -> SlideDraftResponse:
        slide = await self.slide_repo.get_by_id(project_id, slide_id)
        if not slide:
            raise NotFoundError(f"슬라이드({slide_id})를 찾을 수 없습니다.")

        if payload.title is not None:
            slide.title = payload.title.strip()
        if payload.headcopy is not None:
            slide.headcopy = payload.headcopy.strip()
        if payload.kpi_cards is not None:
            slide.kpi_cards_json = [k.model_dump() for k in payload.kpi_cards]
        if payload.bullets is not None:
            slide.bullets_json = [b.model_dump() for b in payload.bullets]
        if payload.table is not None:
            slide.table_json = payload.table.model_dump()
        if payload.as_is_to_be is not None:
            slide.as_is_to_be_json = payload.as_is_to_be.model_dump()
        if payload.footnote is not None:
            slide.footnote = payload.footnote.strip()
        if payload.review_status is not None:
            slide.review_status = payload.review_status.value

        await self.session.commit()
        fresh = await self.slide_repo.get_by_id(project_id, slide_id)
        assert fresh is not None
        return self.slide_to_response(fresh)

    async def apply_comment(
        self, project_id: str, slide_id: str, payload: ApplyCommentRequest
    ) -> CommentDiffResponse:
        comment = await self.structuring.refine_comment_for_slide(
            project_id=project_id,
            slide_id=slide_id,
            raw_comment=payload.raw_comment,
            auto_apply=payload.auto_apply,
        )
        return CommentDiffResponse(
            comment_id=comment.id,
            slide_id=comment.slide_id,
            raw_comment=comment.raw_comment,
            refined_comment=comment.refined_comment,
            status=comment.status,
            before_draft=CommentDiffPayload.model_validate(comment.before_draft_json),
            after_draft=CommentDiffPayload.model_validate(comment.after_draft_json),
        )

    async def decide_comment(
        self,
        project_id: str,
        slide_id: str,
        comment_id: str,
        payload: CommentDecisionRequest,
    ) -> SlideDraftResponse:
        slide = await self.slide_repo.get_by_id(project_id, slide_id)
        if not slide:
            raise NotFoundError(f"슬라이드({slide_id})를 찾을 수 없습니다.")
        comment = await self.slide_repo.get_comment(project_id, slide_id, comment_id)
        if not comment:
            raise NotFoundError(f"코멘트({comment_id})를 찾을 수 없습니다.")

        target = (
            comment.after_draft_json
            if payload.decision == "APPLY"
            else comment.before_draft_json
        )
        slide.headcopy = target.get("headcopy", slide.headcopy)
        slide.bullets_json = target.get("bullets", slide.bullets_json)
        if target.get("as_is_to_be") is not None:
            slide.as_is_to_be_json = target["as_is_to_be"]

        if payload.decision == "APPLY":
            comment.status = "APPLIED"
            slide.review_status = SlideReviewStatus.COMMENT_APPLIED.value
        else:
            comment.status = "REVERTED"
            slide.review_status = SlideReviewStatus.NEEDS_REVIEW.value

        await self.session.commit()
        fresh = await self.slide_repo.get_by_id(project_id, slide_id)
        assert fresh is not None
        return self.slide_to_response(fresh)

    async def update_summary_split(
        self, project_id: str, split_mode: SummarySplitMode
    ) -> list[SlideDraftResponse]:
        slides = await self.structuring.rebuild_summary_split(project_id, split_mode)
        return [self.slide_to_response(s) for s in slides]

    async def approve_section(
        self, project_id: str, section_code: SectionCode
    ) -> SectionBulkApproveResponse:
        project = await self.session.get(Project, project_id)
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")
        count = await self.slide_repo.approve_section(project_id, section_code.value)
        await self.session.commit()
        return SectionBulkApproveResponse(
            section_code=section_code,
            approved_slide_count=count,
        )

    @staticmethod
    def slide_to_response(slide: SlideDraft) -> SlideDraftResponse:
        latest_comment = slide.comments[0].status if getattr(slide, "comments", None) else None
        return SlideDraftResponse(
            id=slide.id,
            project_id=slide.project_id,
            section_code=SectionCode(slide.section_code),
            slide_order=slide.slide_order,
            slide_type=slide.slide_type,
            title=slide.title,
            headcopy=slide.headcopy,
            kpi_cards=[KpiCard.model_validate(k) for k in (slide.kpi_cards_json or [])],
            bullets=[SlideBullet.model_validate(b) for b in (slide.bullets_json or [])],
            table=SlideTable.model_validate(slide.table_json) if slide.table_json else None,
            visual_assets=[
                SlideVisualAsset.model_validate(v)
                for v in (slide.visual_assets_json or [])
            ],
            as_is_to_be=(
                AsIsToBeContent.model_validate(slide.as_is_to_be_json)
                if slide.as_is_to_be_json
                else None
            ),
            footnote=slide.footnote,
            review_status=SlideReviewStatus(slide.review_status),
            latest_comment_status=latest_comment,
            updated_at=slide.updated_at,
        )
