from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.core.job_manager import JobContext, JobManager
from app.integrations.apify_client import ApifyClient
from app.integrations.media_downloader import MediaDownloader
from app.integrations.naver_datalab_client import NaverDataLabClient
from app.integrations.perplexity_client import PerplexityClient
from app.integrations.scrapecreators_client import ScrapeCreatorsClient
from app.models.base import utcnow_naive
from app.models.collection import DataLabSeries, MediaAsset, RawSourceItem, SnsTopPost
from app.models.project import Project
from app.models.research_plan import ResearchPlan
from app.schemas.collection import CollectionRetryRequest, CollectionRunRequest
from app.schemas.common import ProjectStage, SectionCode
from app.services.datalab_metrics_service import DataLabMetricsService
from app.services.research_query_planner import build_perplexity_queries
from app.services.sns_ranking_service import SnsRankingService

logger = logging.getLogger(__name__)


ALL_COLLECTION_SUBTASKS: list[tuple[str, str]] = [
    ("perplexity_research", "거시 시장·규제·자사/경쟁 기초 리서치 (Perplexity)"),
    ("naver_datalab", "네이버 데이터랩 검색어 트렌드·쇼핑 인사이트 정량 수집"),
    ("sns_official_top5", "자사·경쟁사 공식 SNS 채널 지표 및 기간 내 TOP 5 추출"),
    ("creator_collab", "크리에이터 협업 콘텐츠 및 시딩 레퍼런스 수집"),
    ("community_voc", "국내 커뮤니티·블로그·카페·리뷰 실소비자 VOC 수집"),
    ("media_archiving", "참조 이미지·영상 주요 장면 스크린샷 로컬 아카이빙"),
]


def compute_highlight_spans(content: str, quote: str | None) -> tuple[list[dict[str, Any]], bool]:
    """Locates evidence_quote inside raw content so frontend can highlight verbatim spans."""
    if not content or not quote or not quote.strip():
        return [], False
    q = quote.strip()
    idx = content.find(q)
    if idx != -1:
        return [{"start": idx, "end": idx + len(q), "quote": q}], True

    compact_q = re.sub(r"\s+", " ", q).strip()
    if len(compact_q) >= 12:
        snippet = compact_q[:28]
        idx2 = content.find(snippet)
        if idx2 != -1:
            return [
                {
                    "start": idx2,
                    "end": idx2 + len(snippet),
                    "quote": content[idx2 : idx2 + len(snippet)],
                }
            ], True
    return [], False


def extract_best_evidence_quote(content: str, keywords: list[str] | None = None) -> str | None:
    if not content:
        return None
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?다요])\s+|\n+", content)
        if len(s.strip()) >= 15
    ]
    if not sentences:
        return content[:160].strip() or None
    if keywords:
        for sent in sentences:
            if any(kw.lower() in sent.lower() for kw in keywords if kw):
                return sent[:280]
    return sentences[0][:280]


class CollectionOrchestrator:
    """Runs multi-source async collection jobs with fault isolation, media archiving, and selective retry."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        job_manager: JobManager,
    ) -> None:
        self.session_factory = session_factory
        self.job_manager = job_manager
        # Serialize DB write commits across concurrent subtasks to prevent MySQL InnoDB gap-lock deadlocks
        self._db_write_lock = asyncio.Lock()

    async def start_collection(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        payload: CollectionRunRequest,
        idempotency_key: str | None = None,
    ) -> Any:
        project = await session.get(Project, project_id)
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")

        selected = set(payload.selected_sources) if payload.selected_sources else None
        subtasks = [
            (key, label)
            for key, label in ALL_COLLECTION_SUBTASKS
            if selected is None or key in selected
        ]
        if not subtasks:
            subtasks = list(ALL_COLLECTION_SUBTASKS)

        project.current_stage = ProjectStage.COLLECT.value
        await session.commit()

        subtask_keys = [s[0] for s in subtasks]
        return await self.job_manager.start_job(
            session,
            project_id=project_id,
            job_type="COLLECTION",
            subtasks=subtasks,
            coro_factory=lambda ctx: self._execute_pipeline(
                ctx,
                project_id=project_id,
                subtask_keys=subtask_keys,
                force_refresh=payload.force_refresh,
            ),
            idempotency_key=idempotency_key,
        )

    async def retry_subtasks(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        payload: CollectionRetryRequest,
        idempotency_key: str | None = None,
    ) -> Any:
        run_req = CollectionRunRequest(
            force_refresh=payload.force_refresh,
            selected_sources=payload.subtask_keys,
        )
        return await self.start_collection(
            session,
            project_id=project_id,
            payload=run_req,
            idempotency_key=idempotency_key,
        )

    async def _execute_pipeline(
        self,
        ctx: JobContext,
        *,
        project_id: str,
        subtask_keys: list[str],
        force_refresh: bool,
    ) -> None:
        async with self.session_factory() as session:
            stmt = (
                select(Project)
                .options(
                    selectinload(Project.competitors),
                    selectinload(Project.sns_accounts),
                    selectinload(Project.keyword_groups),
                    selectinload(Project.research_plan).selectinload(ResearchPlan.items),
                )
                .where(Project.id == project_id)
            )
            project = (await session.execute(stmt)).scalar_one()

        tasks = []
        key_set = set(subtask_keys)
        if "perplexity_research" in key_set:
            tasks.append(self._run_perplexity(ctx, project, force_refresh))
        if "naver_datalab" in key_set:
            tasks.append(self._run_naver_datalab(ctx, project, force_refresh))
        if "sns_official_top5" in key_set:
            tasks.append(self._run_sns_official_top5(ctx, project, force_refresh))
        if "creator_collab" in key_set:
            tasks.append(self._run_creator_collab(ctx, project, force_refresh))
        if "community_voc" in key_set:
            tasks.append(self._run_community_voc(ctx, project, force_refresh))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if "media_archiving" in key_set:
            await self._run_media_archiving(ctx, project_id)

    async def _run_perplexity(
        self, ctx: JobContext, project: Project, force_refresh: bool
    ) -> None:
        key = "perplexity_research"
        await ctx.update_subtask(key, status="RUNNING", progress_pct=15, log_message="Perplexity 6대 영역 심층 리서치 시작")
        client = PerplexityClient()
        try:
            queries = build_perplexity_queries(project)

            async def _fetch_one(spec):
                return spec, await client.research_topic(
                    topic_title=spec.title,
                    query_prompt=spec.prompt,
                    force_refresh=force_refresh,
                )

            results = await asyncio.gather(
                *(_fetch_one(spec) for spec in queries),
                return_exceptions=True,
            )
            items: list[RawSourceItem] = []
            errors: list[str] = []
            for idx, outcome in enumerate(results, start=1):
                if isinstance(outcome, Exception):
                    logger.warning("Perplexity query %d failed: %s", idx, outcome)
                    errors.append(str(outcome))
                    continue
                spec, res = outcome
                content = str(res.get("content") or "")
                citations = res.get("citations") or []
                primary_url = str(citations[0]) if citations else None
                quote = extract_best_evidence_quote(
                    content, [project.brand_name, project.product_name]
                )
                spans, verified = compute_highlight_spans(content, quote)
                items.append(
                    RawSourceItem(
                        project_id=project.id,
                        section_code=spec.section_code,
                        provider="PERPLEXITY",
                        channel="perplexity_research",
                        title=spec.title[:480],
                        content=content,
                        source_url=primary_url,
                        published_at=utcnow_naive(),
                        evidence_quote=quote,
                        highlight_spans=spans,
                        sentiment="NEUTRAL",
                        review_status="PENDING",
                        metadata_json={"citations": citations, "is_quote_verified": verified},
                    )
                )
                await ctx.update_subtask(key, progress_pct=20 + int((idx / max(1, len(queries))) * 75))

            if not items and errors:
                raise RuntimeError(errors[0])

            async with self._db_write_lock:
                async with self.session_factory() as session:
                    await session.execute(
                        delete(RawSourceItem).where(
                            RawSourceItem.project_id == project.id,
                            RawSourceItem.provider == "PERPLEXITY",
                        )
                    )
                    session.add_all(items)
                    await session.commit()

            msg = f"Perplexity 심층 리서치 {len(items)}/{len(queries)}건 저장 완료"
            if errors:
                msg += f" (일부 {len(errors)}건 오류)"
            await ctx.update_subtask(
                key,
                status="COMPLETED",
                progress_pct=100,
                collected_count=len(items),
                log_message=msg,
            )
        except Exception as exc:
            logger.exception("Perplexity collection failed for %s", project.id)
            await ctx.update_subtask(
                key,
                status="FAILED",
                progress_pct=100,
                error_message=str(exc),
                log_message=f"실패: {exc}",
            )

    async def _run_naver_datalab(
        self, ctx: JobContext, project: Project, force_refresh: bool
    ) -> None:
        key = "naver_datalab"
        await ctx.update_subtask(key, status="RUNNING", progress_pct=20, log_message="네이버 데이터랩 호출 중")
        client = NaverDataLabClient()
        try:
            plan_groups = (
                list(project.research_plan.datalab_groups_config)
                if project.research_plan and project.research_plan.datalab_groups_config
                else []
            )
            if not plan_groups:
                plan_groups = [
                    {
                        "groupName": f"{project.brand_name} {project.product_name}",
                        "ownerType": "OWN",
                        "keywords": [project.brand_name, f"{project.brand_name} {project.product_name}"],
                    }
                ]
                for comp in project.competitors[:4]:
                    plan_groups.append(
                        {
                            "groupName": f"{comp.brand_name} {comp.product_name}",
                            "ownerType": "COMPETITOR",
                            "keywords": [
                                comp.brand_name,
                                f"{comp.brand_name} {project.product_name}",
                                f"{comp.brand_name} {comp.product_name}",
                            ],
                        }
                    )

            owner_map = {g["groupName"]: g.get("ownerType", "COMPETITOR") for g in plan_groups}
            api_groups = [{"groupName": g["groupName"], "keywords": g["keywords"]} for g in plan_groups]

            search_raw = await client.fetch_search_trend(
                start_date=project.period_start,
                end_date=project.period_end,
                keyword_groups=api_groups,
                time_unit="week",
                force_refresh=force_refresh,
            )
            search_entities = DataLabMetricsService.compute_series_metrics(
                project_id=project.id,
                metric_type="SEARCH_TREND",
                raw_results=list(search_raw.get("results") or []),
                owner_type_by_label=owner_map,
                period_start=project.period_start,
                period_end=project.period_end,
                is_anchor_normalized=bool(search_raw.get("is_anchor_normalized")),
            )

            shopping_entities: list[DataLabSeries] = []
            if project.naver_shopping_category_id:
                try:
                    shop_raw = await client.fetch_shopping_insight(
                        start_date=project.period_start,
                        end_date=project.period_end,
                        category_id=project.naver_shopping_category_id,
                        keyword_groups=api_groups,
                        time_unit="week",
                        force_refresh=force_refresh,
                    )
                    shopping_entities = DataLabMetricsService.compute_series_metrics(
                        project_id=project.id,
                        metric_type="SHOPPING_INSIGHT",
                        raw_results=list(shop_raw.get("results") or []),
                        owner_type_by_label=owner_map,
                        period_start=project.period_start,
                        period_end=project.period_end,
                    )
                except Exception:
                    shopping_entities = []

            all_series = search_entities + shopping_entities
            async with self._db_write_lock:
                async with self.session_factory() as session:
                    await session.execute(
                        delete(DataLabSeries).where(DataLabSeries.project_id == project.id)
                    )
                    session.add_all(all_series)
                    await session.commit()

            await ctx.update_subtask(
                key,
                status="COMPLETED",
                progress_pct=100,
                collected_count=len(all_series),
                log_message=f"데이터랩 시계열 {len(all_series)}건 산출 완료",
            )
        except Exception as exc:
            await ctx.update_subtask(
                key,
                status="FAILED",
                progress_pct=100,
                error_message=str(exc),
                log_message=f"실패: {exc}",
            )

    async def _run_sns_official_top5(
        self, ctx: JobContext, project: Project, force_refresh: bool
    ) -> None:
        key = "sns_official_top5"
        await ctx.update_subtask(key, status="RUNNING", progress_pct=15, log_message="공식 SNS TOP 5 수집 시작")
        client = ScrapeCreatorsClient()
        try:
            if not project.sns_accounts:
                await ctx.update_subtask(
                    key,
                    status="COMPLETED",
                    progress_pct=100,
                    collected_count=0,
                    log_message="등록된 공식 SNS 계정 URL이 없어 건너뛰었습니다.",
                )
                return

            top_entities: list[SnsTopPost] = []
            raw_sources: list[RawSourceItem] = []
            account_errors: list[str] = []

            for acc in project.sns_accounts:
                try:
                    res = await client.fetch_profile_and_posts(
                        platform=acc.platform,
                        handle=acc.handle,
                        account_url=acc.account_url,
                        force_refresh=force_refresh,
                    )
                except Exception as acc_exc:
                    logger.warning("SNS account fetch failed (%s/%s): %s", acc.platform, acc.handle, acc_exc)
                    account_errors.append(f"{acc.brand_label}({acc.handle}): {acc_exc}")
                    continue

                sec = (
                    SectionCode.OWN.value
                    if acc.owner_type == "OWN"
                    else SectionCode.COMPETITOR.value
                )
                all_posts = res.get("posts") or []
                top5 = SnsRankingService.rank_top_posts(
                    posts=all_posts,
                    period_start=project.period_start,
                    period_end=project.period_end,
                    limit=5,
                    brand_keywords=[acc.brand_label, project.product_name],
                )
                collab_cnt = sum(1 for p in top5 if p.get("is_creator_collab"))
                summary_text = (
                    f"[{acc.brand_label} 공식 {acc.platform}] 계정 @{acc.handle} | "
                    f"팔로워/구독자 {int(res.get('followers', 0)):,}명 | "
                    f"수집 게시물 {len(all_posts)}건 중 기간 내 TOP {len(top5)}건(크리에이터 협업 {collab_cnt}건)"
                )
                raw_sources.append(
                    RawSourceItem(
                        project_id=project.id,
                        section_code=sec,
                        provider="SCRAPECREATORS",
                        channel=f"{acc.platform.lower()}_profile",
                        title=f"[{acc.brand_label}] 공식 {acc.platform} 계정 규모 ({int(res.get('followers', 0)):,}명)",
                        content=summary_text,
                        source_url=acc.account_url,
                        author=acc.handle,
                        published_at=utcnow_naive(),
                        evidence_quote=summary_text,
                        highlight_spans=[{"start": 0, "end": len(summary_text), "quote": summary_text}],
                        sentiment="NEUTRAL",
                        review_status="APPROVED",
                        metadata_json={
                            "followers": int(res.get("followers", 0)),
                            "total_fetched_posts": len(all_posts),
                            "top_period_posts": len(top5),
                            "collab_count": collab_cnt,
                            "platform": acc.platform,
                            "owner_type": acc.owner_type,
                            "brand_label": acc.brand_label,
                            "is_account_profile": True,
                        },
                    )
                )

                for post in top5:
                    caption = str(post.get("caption") or "")
                    pub_at = post.get("published_at") or utcnow_naive()
                    quote = extract_best_evidence_quote(caption) or caption[:180]
                    spans, _ = compute_highlight_spans(caption, quote)
                    raw_item = RawSourceItem(
                        project_id=project.id,
                        section_code=sec,
                        provider="SCRAPECREATORS",
                        channel=acc.platform.lower(),
                        title=f"[{acc.brand_label} TOP {post['rank_order']}] {caption[:60]}",
                        content=caption or "(본문 없음)",
                        source_url=post.get("post_url"),
                        author=acc.handle,
                        published_at=pub_at,
                        evidence_quote=quote,
                        highlight_spans=spans,
                        sentiment="POSITIVE",
                        review_status="PENDING",
                        metadata_json={
                            "views": post["views"],
                            "likes": post["likes"],
                            "comments": post["comments"],
                            "thumbnail_url": post.get("thumbnail_url"),
                            "followers": res.get("followers", 0),
                            "is_creator_collab": post["is_creator_collab"],
                        },
                    )
                    raw_sources.append(raw_item)
                    top_entities.append(
                        SnsTopPost(
                            project_id=project.id,
                            owner_type=acc.owner_type,
                            brand_label=acc.brand_label,
                            platform=acc.platform,
                            post_url=post.get("post_url") or acc.account_url,
                            caption=caption,
                            published_at=pub_at,
                            views=post["views"],
                            likes=post["likes"],
                            comments=post["comments"],
                            engagement_score=post["engagement_score"],
                            rank_order=post["rank_order"],
                            is_creator_collab=post["is_creator_collab"],
                            key_takeaway=f"조회 {post['views']:,} / 좋아요 {post['likes']:,} / 댓글 {post['comments']:,}",
                        )
                    )

            collab_label = f"{project.brand_name} 협업"
            async with self._db_write_lock:
                async with self.session_factory() as session:
                    await session.execute(
                        delete(RawSourceItem).where(
                            RawSourceItem.project_id == project.id,
                            RawSourceItem.provider == "SCRAPECREATORS",
                        )
                    )
                    await session.execute(
                        delete(SnsTopPost).where(
                            SnsTopPost.project_id == project.id,
                            SnsTopPost.brand_label != collab_label,
                        )
                    )
                    session.add_all(raw_sources)
                    session.add_all(top_entities)
                    await session.commit()

            msg = f"SNS 기간 내 인기 게시물 {len(top_entities)}건 추출 완료"
            if account_errors:
                msg += f" (일부 계정 조회 실패: {len(account_errors)}건)"
            await ctx.update_subtask(
                key,
                status="COMPLETED" if top_entities or not account_errors else "PARTIAL_SUCCESS",
                progress_pct=100,
                collected_count=len(top_entities),
                error_message="; ".join(account_errors) if account_errors else None,
                log_message=msg,
            )
        except Exception as exc:
            await ctx.update_subtask(
                key,
                status="FAILED",
                progress_pct=100,
                error_message=str(exc),
                log_message=f"실패: {exc}",
            )

    async def _run_creator_collab(
        self, ctx: JobContext, project: Project, force_refresh: bool
    ) -> None:
        key = "creator_collab"
        await ctx.update_subtask(key, status="RUNNING", progress_pct=20, log_message="크리에이터 협업 콘텐츠 탐색 중")
        client = ScrapeCreatorsClient()
        try:
            posts = await client.search_creator_collabs(
                platform="YOUTUBE",
                keyword=f"{project.brand_name} {project.product_name}",
                force_refresh=force_refresh,
            )
            ranked = SnsRankingService.rank_top_posts(
                posts=posts,
                period_start=project.period_start,
                period_end=project.period_end,
                limit=5,
                brand_keywords=[project.brand_name, project.product_name],
            )
            collab_entities = [
                SnsTopPost(
                    project_id=project.id,
                    owner_type="OWN",
                    brand_label=f"{project.brand_name} 협업",
                    platform=p["platform"],
                    post_url=p.get("post_url") or "https://instagram.com",
                    caption=p.get("caption") or "",
                    published_at=p.get("published_at") or utcnow_naive(),
                    views=p["views"],
                    likes=p["likes"],
                    comments=p["comments"],
                    engagement_score=p["engagement_score"],
                    rank_order=p["rank_order"],
                    is_creator_collab=True,
                    key_takeaway=f"크리에이터 협업 | 좋아요 {p['likes']:,} / 댓글 {p['comments']:,}",
                )
                for p in ranked
            ]
            collab_label = f"{project.brand_name} 협업"
            async with self._db_write_lock:
                async with self.session_factory() as session:
                    await session.execute(
                        delete(SnsTopPost).where(
                            SnsTopPost.project_id == project.id,
                            SnsTopPost.brand_label == collab_label,
                        )
                    )
                    session.add_all(collab_entities)
                    await session.commit()

            await ctx.update_subtask(
                key,
                status="COMPLETED",
                progress_pct=100,
                collected_count=len(collab_entities),
                log_message=f"크리에이터 협업 {len(collab_entities)}건 수집 완료",
            )
        except Exception as exc:
            await ctx.update_subtask(
                key,
                status="FAILED",
                progress_pct=100,
                error_message=str(exc),
                log_message=f"실패: {exc}",
            )

    async def _run_community_voc(
        self, ctx: JobContext, project: Project, force_refresh: bool
    ) -> None:
        key = "community_voc"
        await ctx.update_subtask(key, status="RUNNING", progress_pct=20, log_message="국내 커뮤니티·블로그·카페 VOC 수집 중")
        client = ApifyClient()
        try:
            communities = (
                list(project.research_plan.target_communities)
                if project.research_plan and project.research_plan.target_communities
                else ["dcinside", "fmkorea", "theqoo", "clien", "naver_blog", "naver_cafe"]
            )
            keywords = [project.brand_name, project.product_name]
            extra_queries = [
                f"site:blog.naver.com {project.brand_name} {project.product_name} 후기",
                f"site:cafe.naver.com {project.brand_name} {project.product_name} 추천 단점",
            ]
            if project.competitors:
                comp_b = project.competitors[0].brand_name
                extra_queries.append(f"{project.brand_name} vs {comp_b} {project.product_name} 비교 후기")
            rows = await client.collect_korean_community_voc(
                keywords=keywords,
                communities=communities,
                extra_queries=extra_queries,
                force_refresh=force_refresh,
            )
            entities: list[RawSourceItem] = []
            for r in rows:
                content = str(r.get("content") or r.get("title") or "")
                quote = extract_best_evidence_quote(content, keywords)
                spans, verified = compute_highlight_spans(content, quote)
                entities.append(
                    RawSourceItem(
                        project_id=project.id,
                        section_code=SectionCode.CONSUMER.value,
                        provider="APIFY",
                        channel=str(r.get("channel") or "community_web"),
                        title=str(r.get("title") or "커뮤니티 게시글")[:480],
                        content=content,
                        source_url=r.get("source_url"),
                        published_at=utcnow_naive(),
                        evidence_quote=quote,
                        highlight_spans=spans,
                        sentiment="NEUTRAL",
                        review_status="PENDING",
                        metadata_json={"is_quote_verified": verified},
                    )
                )

            async with self._db_write_lock:
                async with self.session_factory() as session:
                    await session.execute(
                        delete(RawSourceItem).where(
                            RawSourceItem.project_id == project.id,
                            RawSourceItem.provider == "APIFY",
                        )
                    )
                    session.add_all(entities)
                    await session.commit()

            await ctx.update_subtask(
                key,
                status="COMPLETED",
                progress_pct=100,
                collected_count=len(entities),
                log_message=f"커뮤니티·블로그·카페 VOC {len(entities)}건 저장 완료",
            )
        except Exception as exc:
            await ctx.update_subtask(
                key,
                status="FAILED",
                progress_pct=100,
                error_message=str(exc),
                log_message=f"실패: {exc}",
            )

    async def _run_media_archiving(self, ctx: JobContext, project_id: str) -> None:
        key = "media_archiving"
        await ctx.update_subtask(key, status="RUNNING", progress_pct=20, log_message="참조 이미지 로컬 아카이빙 중")
        downloader = MediaDownloader()
        archived_count = 0
        try:
            async with self.session_factory() as session:
                posts = list(
                    (
                        await session.execute(
                            select(SnsTopPost).where(SnsTopPost.project_id == project_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                raw_items = list(
                    (
                        await session.execute(
                            select(RawSourceItem).where(
                                RawSourceItem.project_id == project_id,
                                RawSourceItem.provider == "SCRAPECREATORS",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                url_by_post_url = {
                    r.source_url: (r.metadata_json or {}).get("thumbnail_url")
                    for r in raw_items
                    if r.source_url
                }

                for post in posts:
                    thumb_url = url_by_post_url.get(post.post_url)
                    if not thumb_url and post.platform == "YOUTUBE" and post.post_url:
                        vid_match = re.search(r"(?:v=|/shorts/)([A-Za-z0-9_-]{6,})", post.post_url)
                        if vid_match:
                            thumb_url = f"https://i.ytimg.com/vi/{vid_match.group(1)}/hqdefault.jpg"
                    downloaded = None
                    if thumb_url:
                        downloaded = await downloader.download_image(
                            project_id=project_id,
                            image_url=str(thumb_url),
                            prefix=f"sns_{post.rank_order}",
                        )
                    if downloaded is None:
                        downloaded = downloader.create_placeholder_card(
                            project_id=project_id,
                            filename=f"sns_{post.owner_type.lower()}_{post.rank_order}_{post.id[:8]}.png",
                            title=f"{post.brand_label} | {post.platform} TOP {post.rank_order}",
                            subtitle=post.key_takeaway or post.caption[:60],
                        )
                    asset = MediaAsset(
                        project_id=project_id,
                        asset_type="SNS_THUMBNAIL",
                        original_url=downloaded.get("original_url"),
                        local_path=downloaded["local_path"],
                        caption=f"[{post.brand_label}] {post.platform} TOP {post.rank_order}",
                        annotation_text=post.key_takeaway,
                        width=downloaded["width"],
                        height=downloaded["height"],
                        is_valid=downloaded["is_valid"],
                    )
                    session.add(asset)
                    await session.flush()
                    post.media_asset_id = asset.id
                    archived_count += 1
                await session.commit()

            await ctx.update_subtask(
                key,
                status="COMPLETED",
                progress_pct=100,
                collected_count=archived_count,
                log_message=f"참조 이미지 {archived_count}건 아카이빙 완료",
            )
        except Exception as exc:
            await ctx.update_subtask(
                key,
                status="FAILED",
                progress_pct=100,
                error_message=str(exc),
                log_message=f"미디어 아카이빙 오류: {exc}",
            )
