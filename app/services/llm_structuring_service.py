from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.core.job_manager import JobContext
from app.integrations.anthropic_client import AnthropicClient
from app.models.collection import RawSourceItem
from app.models.factbook import FactItem, PlannerComment, SlideDraft
from app.models.project import Project
from app.repositories.fact_item_repo import FactItemRepository
from app.repositories.slide_draft_repo import SlideDraftRepository
from app.repositories.source_item_repo import SourceItemRepository
from app.schemas.common import ProjectStage, SectionCode, SummarySplitMode
from app.services.collection_orchestrator import extract_best_evidence_quote
from app.services.deck_blueprint import (
    build_deterministic_deck,
    build_section5_slides,
    clean_slide_text,
    sanitize_slide_draft,
)
from app.services.deck_synthesizer import (
    SYNTHESIS_BATCH_SPECS,
    DeckSynthesizer,
    clone_slide_draft,
)

logger = logging.getLogger(__name__)

SLIDE_GENERATION_SUBTASKS: list[tuple[str, str]] = [
    ("classify_facts", "승인 자료 분류 및 핵심 팩트 구조화"),
    ("init_blueprint", "표지·목차 및 전체 장표 골격 생성"),
    *SYNTHESIS_BATCH_SPECS,
]


class LlmStructuringService:
    """Synthesizes verified sources into 0~5 Factbook slides & refines planner comments via Claude."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.source_repo = SourceItemRepository(session)
        self.fact_repo = FactItemRepository(session)
        self.slide_repo = SlideDraftRepository(session)
        self.claude = AnthropicClient()
        self.synthesizer = DeckSynthesizer(self.claude)

    async def generate_slides(
        self,
        project_id: str,
        *,
        summary_split_mode: SummarySplitMode | None = None,
        use_approved_only: bool = True,
    ) -> list[SlideDraft]:
        stmt = (
            select(Project)
            .options(
                selectinload(Project.competitors),
                selectinload(Project.sns_accounts),
                selectinload(Project.keyword_groups),
            )
            .where(Project.id == project_id)
        )
        project = (await self.session.execute(stmt)).scalar_one_or_none()
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")

        if summary_split_mode is not None:
            project.summary_split_mode = summary_split_mode.value
        split_mode = SummarySplitMode(project.summary_split_mode)

        sources = await self.source_repo.list_for_synthesis(
            project_id, use_approved_only=use_approved_only
        )
        datalab_series = await self.source_repo.list_datalab(project_id)
        sns_posts = await self.source_repo.list_sns_top_posts(project_id)
        media_assets = await self.source_repo.list_media_assets(project_id)

        relevant_sources = sources
        tag_by_source_id: dict[str, str] = {}
        if self.claude.is_configured() and sources:
            try:
                relevant_sources, tag_by_source_id = await self._classify_and_filter_sources(
                    project, sources
                )
            except Exception as exc:
                logger.warning("Claude source classification failed, keeping all sources: %s", exc)
                relevant_sources = sources

        facts = self._build_fact_items(project, relevant_sources, tag_by_source_id)
        await self.fact_repo.replace_for_project(project_id, facts)

        if self.claude.is_configured() and relevant_sources:
            try:
                slides = await self.synthesizer.synthesize_deck(
                    project=project,
                    sources=relevant_sources,
                    facts=facts,
                    datalab_series=datalab_series,
                    sns_posts=sns_posts,
                    media_assets=media_assets,
                    split_mode=split_mode,
                )
            except Exception as exc:
                logger.warning("Claude deck synthesis failed, using grounded deterministic deck: %s", exc)
                slides = build_deterministic_deck(
                    project=project,
                    sources=relevant_sources,
                    facts=facts,
                    datalab_series=datalab_series,
                    sns_posts=sns_posts,
                    media_assets=media_assets,
                    split_mode=split_mode,
                )
        else:
            slides = build_deterministic_deck(
                project=project,
                sources=relevant_sources,
                facts=facts,
                datalab_series=datalab_series,
                sns_posts=sns_posts,
                media_assets=media_assets,
                split_mode=split_mode,
            )

        await self.slide_repo.replace_all_slides(project_id, slides)
        project.current_stage = ProjectStage.REVIEW.value
        await self.session.commit()
        return await self.slide_repo.list_by_project(project_id)

    async def generate_slides_with_progress(
        self,
        project_id: str,
        ctx: JobContext,
        *,
        summary_split_mode: SummarySplitMode | None = None,
        use_approved_only: bool = True,
    ) -> None:
        """Run slide synthesis in background while streaming incremental SlideDraft snapshots to DB."""
        db_write_lock = asyncio.Lock()

        async def _save_snapshot(snapshot: list[SlideDraft]) -> None:
            async with db_write_lock:
                async with ctx.session_factory() as s:
                    await SlideDraftRepository(s).replace_all_slides(
                        project_id,
                        [sanitize_slide_draft(clone_slide_draft(sl)) for sl in snapshot],
                    )
                    await s.commit()

        await ctx.update_subtask(
            "classify_facts",
            status="RUNNING",
            progress_pct=15,
            log_message="승인 자료 로드 및 팩트 구조화 중",
        )

        async with ctx.session_factory() as s:
            stmt = (
                select(Project)
                .options(
                    selectinload(Project.competitors),
                    selectinload(Project.sns_accounts),
                    selectinload(Project.keyword_groups),
                )
                .where(Project.id == project_id)
            )
            project = (await s.execute(stmt)).scalar_one_or_none()
            if not project:
                raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")
            if summary_split_mode is not None:
                project.summary_split_mode = summary_split_mode.value
                await s.commit()
            split_mode = SummarySplitMode(project.summary_split_mode)
            src_repo = SourceItemRepository(s)
            sources = await src_repo.list_for_synthesis(project_id, use_approved_only=use_approved_only)
            datalab_series = await src_repo.list_datalab(project_id)
            sns_posts = await src_repo.list_sns_top_posts(project_id)
            media_assets = await src_repo.list_media_assets(project_id)

        relevant_sources = sources
        tag_by_source_id: dict[str, str] = {}
        if self.claude.is_configured() and sources:
            try:
                relevant_sources, tag_by_source_id = await self._classify_and_filter_sources(
                    project, sources
                )
            except Exception as exc:
                logger.warning("Claude source classification failed, keeping all sources: %s", exc)
                relevant_sources = sources

        facts = self._build_fact_items(project, relevant_sources, tag_by_source_id)
        async with db_write_lock:
            async with ctx.session_factory() as s:
                await FactItemRepository(s).replace_for_project(project_id, facts)
                await s.commit()

        await ctx.update_subtask(
            "classify_facts",
            status="COMPLETED",
            progress_pct=100,
            collected_count=len(facts),
            log_message=f"승인 자료 {len(relevant_sources)}건 → 팩트 {len(facts)}건 구조화 완료",
        )

        await ctx.update_subtask(
            "init_blueprint",
            status="RUNNING",
            progress_pct=20,
            log_message="표지(COVER)·목차(INDEX) 및 전체 장표 골격 생성 중",
        )

        if self.claude.is_configured() and relevant_sources:
            async def _on_blueprint(snapshot: list[SlideDraft]) -> None:
                await _save_snapshot(snapshot)
                await ctx.update_subtask(
                    "init_blueprint",
                    status="COMPLETED",
                    progress_pct=100,
                    collected_count=len(snapshot),
                    log_message=f"표지·목차 포함 {len(snapshot)}장 골격 생성 완료 (AI 8배치 실시간 합성 시작)",
                )

            async def _on_batch_start(key: str, label: str) -> None:
                await ctx.update_subtask(
                    key,
                    status="RUNNING",
                    progress_pct=30,
                    log_message=f"{label} 진행 중",
                )

            async def _on_batch_complete(
                key: str, label: str, snapshot: list[SlideDraft], err: Exception | None
            ) -> None:
                await _save_snapshot(snapshot)
                msg = (
                    f"{label} 완료 (총 {len(snapshot)}장 실시간 반영)"
                    if err is None
                    else f"{label} 폴백 반영 ({err})"
                )
                await ctx.update_subtask(
                    key,
                    status="COMPLETED",
                    progress_pct=100,
                    collected_count=len(snapshot),
                    log_message=msg,
                )

            try:
                final_slides = await self.synthesizer.synthesize_deck(
                    project=project,
                    sources=relevant_sources,
                    facts=facts,
                    datalab_series=datalab_series,
                    sns_posts=sns_posts,
                    media_assets=media_assets,
                    split_mode=split_mode,
                    on_blueprint_ready=_on_blueprint,
                    on_batch_start=_on_batch_start,
                    on_batch_complete=_on_batch_complete,
                )
                await _save_snapshot(final_slides)
            except Exception as exc:
                logger.warning("Claude async deck synthesis failed, saving deterministic deck: %s", exc)
                fallback = build_deterministic_deck(
                    project=project,
                    sources=relevant_sources,
                    facts=facts,
                    datalab_series=datalab_series,
                    sns_posts=sns_posts,
                    media_assets=media_assets,
                    split_mode=split_mode,
                )
                for sl in fallback:
                    if not sl.id:
                        sl.id = str(uuid.uuid4())
                await _save_snapshot(fallback)
                await ctx.update_subtask("init_blueprint", status="COMPLETED", progress_pct=100, collected_count=len(fallback))
                for k, lbl in SYNTHESIS_BATCH_SPECS:
                    await ctx.update_subtask(k, status="COMPLETED", progress_pct=100, collected_count=len(fallback), log_message=f"{lbl} 기본 덱 반영")
        else:
            fallback = build_deterministic_deck(
                project=project,
                sources=relevant_sources,
                facts=facts,
                datalab_series=datalab_series,
                sns_posts=sns_posts,
                media_assets=media_assets,
                split_mode=split_mode,
            )
            for sl in fallback:
                if not sl.id:
                    sl.id = str(uuid.uuid4())
            await _save_snapshot(fallback)
            await ctx.update_subtask(
                "init_blueprint",
                status="COMPLETED",
                progress_pct=100,
                collected_count=len(fallback),
                log_message=f"표지·목차 포함 {len(fallback)}장 골격 생성 완료",
            )
            for k, lbl in SYNTHESIS_BATCH_SPECS:
                await ctx.update_subtask(
                    k,
                    status="COMPLETED",
                    progress_pct=100,
                    collected_count=len(fallback),
                    log_message=f"{lbl} 완료",
                )

        async with db_write_lock:
            async with ctx.session_factory() as s:
                proj = await s.get(Project, project_id)
                if proj:
                    proj.current_stage = ProjectStage.REVIEW.value
                    await s.commit()
        await ctx.append_log("전체 장표 생성 및 검증 저장이 완료되었습니다.")

    async def refine_comment_for_slide(
        self,
        *,
        project_id: str,
        slide_id: str,
        raw_comment: str,
        auto_apply: bool = False,
    ) -> PlannerComment:
        slide = await self.slide_repo.get_by_id(project_id, slide_id)
        if not slide:
            raise NotFoundError(f"슬라이드({slide_id})를 찾을 수 없습니다.")

        before_draft = {
            "headcopy": slide.headcopy,
            "bullets": list(slide.bullets_json or []),
            "as_is_to_be": slide.as_is_to_be_json,
        }

        if self.claude.is_configured():
            try:
                refined = await self._refine_with_claude(slide, raw_comment)
            except Exception as exc:
                logger.warning("Claude comment refinement failed, using deterministic fallback: %s", exc)
                refined = self._refine_deterministic(slide, raw_comment)
        else:
            refined = self._refine_deterministic(slide, raw_comment)

        after_draft = {
            "headcopy": clean_slide_text(refined["headcopy"])[:380],
            "bullets": refined["bullets"],
            "as_is_to_be": refined.get("as_is_to_be", slide.as_is_to_be_json),
        }

        comment = PlannerComment(
            project_id=project_id,
            slide_id=slide_id,
            raw_comment=raw_comment.strip(),
            refined_comment=clean_slide_text(refined["refined_comment"]),
            before_draft_json=before_draft,
            after_draft_json=after_draft,
            status="APPLIED" if auto_apply else "PREVIEW_READY",
        )
        self.session.add(comment)

        if auto_apply:
            slide.headcopy = after_draft["headcopy"]
            slide.bullets_json = after_draft["bullets"]
            if after_draft.get("as_is_to_be") is not None:
                slide.as_is_to_be_json = after_draft["as_is_to_be"]
            slide.review_status = "COMMENT_APPLIED"

        await self.session.commit()
        await self.session.refresh(comment)
        return comment

    async def rebuild_summary_split(
        self, project_id: str, split_mode: SummarySplitMode
    ) -> list[SlideDraft]:
        stmt = (
            select(Project)
            .options(
                selectinload(Project.competitors),
                selectinload(Project.sns_accounts),
            )
            .where(Project.id == project_id)
        )
        project = (await self.session.execute(stmt)).scalar_one_or_none()
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")
        project.summary_split_mode = split_mode.value

        existing = await self.slide_repo.list_by_project(project_id)
        if not existing:
            await self.session.commit()
            return []

        facts = await self.fact_repo.list_by_project(project_id)
        sources = await self.source_repo.list_for_synthesis(project_id, use_approved_only=False)
        datalab_series = await self.source_repo.list_datalab(project_id)
        non_summary = [
            s for s in existing if s.section_code != SectionCode.SUMMARY_CONCLUSION.value
        ]
        next_order = (max((s.slide_order for s in non_summary), default=0)) + 1
        new_section5 = build_section5_slides(
            project=project,
            sources=sources,
            facts=facts,
            datalab_series=datalab_series,
            non_summary_slides=non_summary,
            split_mode=split_mode,
            start_order=next_order,
        )
        await self.slide_repo.replace_section_slides(
            project_id, SectionCode.SUMMARY_CONCLUSION.value, new_section5
        )
        await self.session.commit()
        return await self.slide_repo.list_by_project(project_id)

    async def _classify_and_filter_sources(
        self, project: Project, sources: list[RawSourceItem]
    ) -> tuple[list[RawSourceItem], dict[str, str]]:
        """Stage A: Filter off-topic noise and classify sentiment/KBF tags via Claude."""
        compact = [
            {
                "id": s.id,
                "section": s.section_code,
                "channel": s.channel,
                "title": clean_slide_text(s.title)[:100],
                "snippet": clean_slide_text(s.evidence_quote or s.content)[:220],
            }
            for s in sources[:50]
            if not (s.metadata_json or {}).get("is_account_profile")
        ]
        if not compact:
            return sources, {}

        prompt = (
            f"분석 타겟: 브랜드='{project.brand_name}', 단일 제품='{project.product_name}', 산업군='{project.industry_category}'\n"
            "아래 수집 자료 목록을 검수해서 JSON으로 분류해줘.\n"
            "규칙:\n"
            "1. is_relevant: 타겟 브랜드/제품/경쟁제품/해당 산업 시장과 실질적으로 관련 있는 자료만 true.\n"
            "2. sentiment: POSITIVE | NEGATIVE | NEUTRAL | MIXED 중 하나로 정확히 판정.\n"
            "3. category_tag: 짧은 한국어 주제 태그.\n\n"
            f"자료 목록:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
            "반환 JSON 형식: {\"classifications\": [{\"id\": \"...\", \"is_relevant\": true, \"sentiment\": \"POSITIVE\", \"category_tag\": \"...\"}]}"
        )
        res = await self.claude.complete_json(
            system_prompt="You are a rigorous Korean marketing data analyst. Return RFC8259 JSON only.",
            user_prompt=prompt,
            max_tokens=4096,
        )
        class_map: dict[str, dict[str, Any]] = {
            str(item["id"]): item
            for item in (res.get("classifications") or [])
            if isinstance(item, dict) and item.get("id")
        }

        filtered: list[RawSourceItem] = []
        tag_by_id: dict[str, str] = {}
        valid_sentiments = {"POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED"}
        for src in sources:
            if (src.metadata_json or {}).get("is_account_profile"):
                filtered.append(src)
                continue
            info = class_map.get(src.id)
            if info:
                sent = str(info.get("sentiment") or "").upper()
                if sent in valid_sentiments:
                    src.sentiment = sent
                if info.get("category_tag"):
                    tag_by_id[src.id] = clean_slide_text(str(info["category_tag"]))[:60]
                if info.get("is_relevant") is False:
                    continue
            filtered.append(src)

        if not filtered:
            filtered = sources
        return filtered, tag_by_id

    @staticmethod
    def _build_fact_items(
        project: Project,
        sources: list[RawSourceItem],
        tag_by_source_id: dict[str, str] | None = None,
    ) -> list[FactItem]:
        tags = tag_by_source_id or {}
        facts: list[FactItem] = []
        for src in sources:
            raw_quote = (
                src.evidence_quote
                or extract_best_evidence_quote(src.content)
                or src.title
            )
            quote = clean_slide_text(raw_quote)
            claim = f"[{src.channel}] {clean_slide_text(src.title)}"
            facts.append(
                FactItem(
                    project_id=project.id,
                    section_code=src.section_code,
                    category_tag=tags.get(src.id) or src.sentiment or "GENERAL",
                    claim_text=claim[:450],
                    evidence_quote=quote[:600],
                    source_item_id=src.id,
                    source_name=src.channel,
                    source_url=src.source_url,
                    published_at=src.published_at,
                    is_quote_verified=bool(
                        (src.metadata_json or {}).get("is_quote_verified", True)
                    ),
                    review_status="APPROVED",
                )
            )
        return facts

    async def _refine_with_claude(
        self, slide: SlideDraft, raw_comment: str
    ) -> dict[str, Any]:
        prompt = (
            f"슬라이드 제목: {slide.title}\n"
            f"현재 리드 문장: {slide.headcopy}\n"
            f"현재 핵심 불릿: {json.dumps(slide.bullets_json, ensure_ascii=False)}\n"
            f"기획자 요청 코멘트: {raw_comment}\n\n"
            "기획자의 의도를 제안서 수준의 간결하고 근거 중심의 문장으로 윤문하고, "
            "JSON 키 refined_comment(윤문 요약), headcopy(수정된 리드 문장, 마크다운 금지), "
            "bullets(기존 bullets 구조 [{claim, evidence_quote, source_name, source_url, fact_id}] 유지)로 반환해줘."
        )
        res = await self.claude.complete_json(
            system_prompt="You refine Korean Factbook slides faithfully based on verified facts. No markdown. Return valid JSON only.",
            user_prompt=prompt,
        )
        raw_bullets = list(res.get("bullets") or slide.bullets_json or [])
        clean_bullets = [
            {
                "claim": clean_slide_text(b.get("claim"))[:150],
                "evidence_quote": clean_slide_text(b.get("evidence_quote"))[:140] or None,
                "source_name": clean_slide_text(b.get("source_name"))[:40] or None,
                "source_url": b.get("source_url"),
                "fact_id": b.get("fact_id"),
            }
            for b in raw_bullets
            if isinstance(b, dict) and clean_slide_text(b.get("claim"))
        ]
        return {
            "refined_comment": clean_slide_text(str(res.get("refined_comment") or raw_comment)),
            "headcopy": clean_slide_text(str(res.get("headcopy") or slide.headcopy))[:360],
            "bullets": clean_bullets or list(slide.bullets_json or []),
        }

    @staticmethod
    def _refine_deterministic(slide: SlideDraft, raw_comment: str) -> dict[str, Any]:
        cleaned = clean_slide_text(raw_comment)
        refined_note = f"[기획자 관점 반영] {cleaned}"
        new_headcopy = f"{slide.headcopy} — ({cleaned[:60]})"[:360]
        bullets = list(slide.bullets_json or [])
        bullets.append(
            {
                "claim": refined_note,
                "evidence_quote": "기획자 전략 코멘트 기반 보완 항목",
                "source_name": "기획자 검수 코멘트",
                "source_url": None,
                "fact_id": None,
            }
        )
        as_is_to_be = slide.as_is_to_be_json
        if as_is_to_be:
            as_is_to_be = {
                **as_is_to_be,
                "to_be_directions": [
                    *list(as_is_to_be.get("to_be_directions") or []),
                    refined_note,
                ],
            }
        return {
            "refined_comment": refined_note,
            "headcopy": new_headcopy,
            "bullets": bullets,
            "as_is_to_be": as_is_to_be,
        }
