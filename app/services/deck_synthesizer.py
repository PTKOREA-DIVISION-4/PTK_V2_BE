from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import copy
import json
import logging
from typing import Any
import uuid

from app.integrations.anthropic_client import AnthropicClient
from app.models.collection import DataLabSeries, MediaAsset, RawSourceItem, SnsTopPost
from app.models.factbook import FactItem, SlideDraft
from app.models.project import Project
from app.schemas.common import SectionCode, SummarySplitMode
from app.services.deck_blueprint import (
    attach_verified_source_urls,
    build_deterministic_deck,
    clean_slide_text,
    recompute_index_slide,
    sanitize_slide_draft,
    smart_truncate,
)

logger = logging.getLogger(__name__)

SYNTHESIS_BATCH_SPECS: list[tuple[str, str]] = [
    ("batch_overview_own", "개요·자사 프로필·가격 장표 AI 합성"),
    ("batch_own_channels", "자사 채널·인스타·유튜브·언론 장표 AI 합성"),
    ("batch_market", "시장 규모·수요·유통·플레이어 장표 AI 합성"),
    ("batch_comp_core", "경쟁 매트릭스·1:1 심층 비교 장표 AI 합성"),
    ("batch_comp_mkt", "경쟁 SNS·언론·6분류 히트맵 장표 AI 합성"),
    ("batch_consumer_voc", "소비자 타깃·VOC·브랜드 인식 장표 AI 합성"),
    ("batch_consumer_bench", "소셜 트렌드·크로스 벤치마크 장표 AI 합성"),
    ("batch_summary_qc", "3C 종합 요약·AS-IS→TO-BE·공백 감사 장표 합성"),
]


def clone_slide_draft(slide: SlideDraft) -> SlideDraft:
    """Create a detached SlideDraft copy preserving id so incremental DB snapshots keep selection stable."""
    return SlideDraft(
        id=slide.id,
        project_id=slide.project_id,
        section_code=slide.section_code,
        slide_order=slide.slide_order,
        slide_type=slide.slide_type,
        title=slide.title,
        headcopy=slide.headcopy,
        kpi_cards_json=copy.deepcopy(slide.kpi_cards_json or []),
        bullets_json=copy.deepcopy(slide.bullets_json or []),
        table_json=copy.deepcopy(slide.table_json),
        visual_assets_json=copy.deepcopy(slide.visual_assets_json or []),
        as_is_to_be_json=copy.deepcopy(slide.as_is_to_be_json),
        footnote=slide.footnote,
        review_status=slide.review_status,
    )


def _sanitize_bullets(raw_list: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw_list, list) or not raw_list:
        return fallback
    cleaned: list[dict[str, Any]] = []
    seen_claims: set[str] = set()
    for item in raw_list[:4]:
        if isinstance(item, str):
            claim = smart_truncate(item, 150)
            if not claim or claim in seen_claims:
                continue
            seen_claims.add(claim)
            cleaned.append(
                {
                    "claim": claim,
                    "evidence_quote": None,
                    "source_name": "팩트북 종합",
                    "source_url": None,
                    "fact_id": None,
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        claim = smart_truncate(item.get("claim"), 150)
        if not claim or claim in seen_claims:
            continue
        seen_claims.add(claim)
        raw_url = str(item.get("source_url") or "").strip()
        cleaned.append(
            {
                "claim": claim,
                "evidence_quote": smart_truncate(item.get("evidence_quote"), 130) or None,
                "source_name": smart_truncate(item.get("source_name"), 40) or None,
                "source_url": raw_url if raw_url.startswith("http") else None,
                "fact_id": item.get("fact_id"),
            }
        )
    return cleaned or fallback


def _sanitize_table(raw_tbl: Any, fallback: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw_tbl, dict):
        return fallback
    headers = [smart_truncate(str(h), 26) for h in (raw_tbl.get("headers") or []) if clean_slide_text(str(h))]
    rows_raw = raw_tbl.get("rows") or []
    if not headers or not isinstance(rows_raw, list) or not rows_raw:
        return fallback
    n_cols = len(headers)
    clean_rows: list[list[str]] = []
    for r in rows_raw[:7]:
        if not isinstance(r, list):
            continue
        padded = [smart_truncate(str(r[i]), 82) if i < len(r) else "-" for i in range(n_cols)]
        clean_rows.append(padded)
    return {"headers": headers, "rows": clean_rows} if clean_rows else fallback


def _sanitize_kpis(raw_kpis: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw_kpis, list) or not raw_kpis:
        return fallback
    out: list[dict[str, Any]] = []
    for item in raw_kpis[:4]:
        if not isinstance(item, dict):
            continue
        label = clean_slide_text(item.get("label"))[:26]
        val = clean_slide_text(item.get("value"))[:24]
        if not label or not val:
            continue
        out.append(
            {
                "label": label,
                "value": val,
                "delta": clean_slide_text(item.get("delta"))[:32] or None,
                "basis": clean_slide_text(item.get("basis"))[:32] or None,
            }
        )
    return out or fallback


def _sanitize_bar_items(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in raw_items[:7]:
        if not isinstance(it, dict):
            continue
        label = clean_slide_text(it.get("label"))[:26]
        try:
            num = float(it.get("value"))
        except (TypeError, ValueError):
            continue
        if label and num > 0:
            out.append({"label": label, "value": round(num, 2), "highlight": bool(it.get("highlight", False))})
    return out


def _sanitize_price_discount_items(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in raw_items[:6]:
        if not isinstance(it, dict):
            continue
        label = clean_slide_text(it.get("label"))[:24]
        try:
            list_p = float(it.get("list_price", 0))
            sale_p = float(it.get("sale_price", list_p))
        except (TypeError, ValueError):
            continue
        if not label or list_p <= 0 or sale_p <= 0:
            continue
        disc = it.get("discount_pct")
        try:
            disc_val = round(float(disc), 1)
        except (TypeError, ValueError):
            disc_val = round(max(0.0, (1.0 - sale_p / list_p) * 100.0), 1)
        out.append(
            {
                "label": label,
                "list_price": round(list_p, 1),
                "sale_price": round(sale_p, 1),
                "discount_pct": disc_val,
            }
        )
    return out


def _sanitize_heatmap_rows(raw_rows: Any, brands: list[str]) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or not brands:
        return []
    out: list[dict[str, Any]] = []
    for row in raw_rows[:6]:
        if not isinstance(row, dict):
            continue
        axis = clean_slide_text(row.get("axis"))[:22]
        raw_scores = row.get("scores")
        if not axis or not isinstance(raw_scores, list):
            continue
        scores: list[dict[str, Any]] = []
        for idx, b in enumerate(brands):
            sc_obj = raw_scores[idx] if idx < len(raw_scores) else {}
            raw_val = sc_obj.get("score") if isinstance(sc_obj, dict) else sc_obj
            try:
                val = int(round(float(raw_val)))
            except (TypeError, ValueError):
                val = 1
            val = max(1, min(5, val))
            scores.append({"brand": b, "score": val})
        out.append({"axis": axis, "scores": scores})
    return out


class DeckSynthesizer:
    """Runs 8 focused concurrent Claude synthesis batches to transform evidence into 36~42 grounded Factbook slides."""

    def __init__(self, claude: AnthropicClient) -> None:
        self.claude = claude

    async def synthesize_deck(
        self,
        *,
        project: Project,
        sources: list[RawSourceItem],
        facts: list[FactItem],
        datalab_series: list[DataLabSeries],
        sns_posts: list[SnsTopPost],
        media_assets: list[MediaAsset],
        split_mode: SummarySplitMode,
        on_blueprint_ready: Callable[[list[SlideDraft]], Awaitable[None]] | None = None,
        on_batch_start: Callable[[str, str], Awaitable[None]] | None = None,
        on_batch_complete: Callable[[str, str, list[SlideDraft], Exception | None], Awaitable[None]] | None = None,
    ) -> list[SlideDraft]:
        deck = build_deterministic_deck(
            project=project,
            sources=sources,
            facts=facts,
            datalab_series=datalab_series,
            sns_posts=sns_posts,
            media_assets=media_assets,
            split_mode=split_mode,
        )
        for slide in deck:
            if not slide.id:
                slide.id = str(uuid.uuid4())

        recompute_index_slide(deck)
        attach_verified_source_urls(deck, sources, sns_posts)
        if on_blueprint_ready is not None:
            await on_blueprint_ready([sanitize_slide_draft(clone_slide_draft(s)) for s in deck])

        ctx = self._build_evidence_context(
            project=project,
            sources=sources,
            facts=facts,
            datalab_series=datalab_series,
            sns_posts=sns_posts,
        )

        merge_lock = asyncio.Lock()
        runners = [
            ("batch_overview_own", "개요·자사 프로필·가격", self._run_batch_overview_own_core(project, ctx)),
            ("batch_own_channels", "자사 채널·인스타·유튜브·언론", self._run_batch_own_channels_press(project, ctx)),
            ("batch_market", "시장 규모·수요·유통·플레이어", self._run_batch_market(project, ctx)),
            ("batch_comp_core", "경쟁 매트릭스·1:1 심층", self._run_batch_comp_matrix_detail(project, ctx)),
            ("batch_comp_mkt", "경쟁 SNS·언론·마케팅 6분류", self._run_batch_comp_sns_press_mkt(project, ctx)),
            ("batch_consumer_voc", "소비자 타깃·VOC·브랜드 인식", self._run_batch_consumer_voc(project, ctx)),
            ("batch_consumer_bench", "소셜 트렌드·벤치마크", self._run_batch_consumer_trends_bench(project, ctx)),
            ("batch_summary_qc", "3C 요약·AS-IS→TO-BE·공백 감사", self._run_batch_summary_conclusion(project, ctx, split_mode)),
        ]

        async def _execute_batch(key: str, label: str, coro: Awaitable[dict[str, Any]]) -> None:
            if on_batch_start is not None:
                await on_batch_start(key, label)
            err: Exception | None = None
            res: dict[str, Any] | None = None
            try:
                res = await coro
            except Exception as exc:
                err = exc
                logger.warning("Claude synthesis batch %s failed (fallback preserved): %s", key, exc)

            async with merge_lock:
                if isinstance(res, dict) and res:
                    self._apply_synthesis(deck, res, split_mode, project)
                    recompute_index_slide(deck)
                    attach_verified_source_urls(deck, sources, sns_posts)
                snapshot = [sanitize_slide_draft(clone_slide_draft(s)) for s in deck]

            if on_batch_complete is not None:
                await on_batch_complete(key, label, snapshot, err)

        await asyncio.gather(*(_execute_batch(k, lbl, coro) for k, lbl, coro in runners))
        return [sanitize_slide_draft(s) for s in deck]

    @staticmethod
    def _build_evidence_context(
        *,
        project: Project,
        sources: list[RawSourceItem],
        facts: list[FactItem],
        datalab_series: list[DataLabSeries],
        sns_posts: list[SnsTopPost],
    ) -> dict[str, Any]:
        perplexity_reports = [
            {
                "section": s.section_code,
                "title": clean_slide_text(s.title).replace('"', "'")[:100],
                "content": clean_slide_text(s.content).replace('"', "'")[:2000],
                "url": s.source_url,
                "citations": (s.metadata_json or {}).get("citations", [])[:5],
            }
            for s in sources
            if s.provider == "PERPLEXITY"
        ]
        news_items = [
            {
                "title": clean_slide_text(s.title).replace('"', "'")[:100],
                "content": clean_slide_text(s.content).replace('"', "'")[:220],
                "domain": (s.metadata_json or {}).get("publisher", s.author or ""),
                "date": (s.metadata_json or {}).get("published_at", ""),
                "topic": (s.metadata_json or {}).get("topic", ""),
                "url": s.source_url,
            }
            for s in sources
            if s.channel == "news_press"
        ][:16]
        sns_profiles = [
            {
                "content": clean_slide_text(s.content),
                "followers": (s.metadata_json or {}).get("followers", 0),
                "platform": (s.metadata_json or {}).get("platform", ""),
                "owner": (s.metadata_json or {}).get("owner_type", ""),
                "brand": (s.metadata_json or {}).get("brand_label", ""),
            }
            for s in sources
            if (s.metadata_json or {}).get("is_account_profile")
        ]
        voc_items = [
            {
                "fact_id": f.id,
                "channel": f.source_name,
                "sentiment": f.category_tag,
                "title": clean_slide_text(f.claim_text).replace('"', "'")[:100],
                "quote": clean_slide_text(f.evidence_quote).replace('"', "'")[:150],
                "url": f.source_url,
            }
            for f in facts
            if f.section_code == SectionCode.CONSUMER.value
        ][:24]
        dl_items = [
            {
                "metric": d.metric_type,
                "label": d.group_label,
                "owner": d.owner_type,
                "share_pct": d.share_of_search_pct,
                "growth_pct": d.growth_rate_pct,
                "peak": f"{d.peak_date} ({d.peak_value})",
            }
            for d in datalab_series
        ]
        sns_items = [
            {
                "owner": p.owner_type,
                "brand": p.brand_label,
                "platform": p.platform,
                "rank": p.rank_order,
                "views": p.views,
                "likes": p.likes,
                "comments": p.comments,
                "is_collab": p.is_creator_collab,
                "caption": clean_slide_text(p.caption)[:110],
                "url": p.post_url,
            }
            for p in sns_posts[:16]
        ]
        return {
            "target": f"{project.brand_name} / {project.product_name} ({project.industry_category})",
            "period": f"{project.period_start}~{project.period_end}",
            "competitors": [f"{c.brand_name} {c.product_name}".strip() for c in project.competitors],
            "perplexity_reports": perplexity_reports,
            "news_items": news_items,
            "datalab": dl_items,
            "sns_profiles": sns_profiles,
            "sns_posts": sns_items,
            "consumer_voc": voc_items,
        }

    async def _run_batch_overview_own_core(
        self, project: Project, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        own_reports = [r for r in ctx["perplexity_reports"] if r["section"] in {"1_OWN", "3_COMPETITOR"}]
        prompt = (
            f"타겟: {ctx['target']} | 기간: {ctx['period']} | 경쟁: {', '.join(ctx['competitors']) or '없음'}\n\n"
            f"[Perplexity 자사·경쟁 리서치]\n{json.dumps(own_reports, ensure_ascii=False)}\n\n"
            f"[데이터랩]\n{json.dumps(ctx['datalab'], ensure_ascii=False)}\n\n"
            "아래 4개 슬라이드 블록 JSON을 작성해줘. 근거 없는 숫자 창작 금지(없으면 '확인 못 함').\n"
            "중요: 음수('-') 부호 유지, 마크다운(**)/각주([1]) 금지, 문자열 내 큰따옴표 대신 작은따옴표(') 사용.\n"
            "각 블록은 서로 다른 관점의 bullets 3개({claim, evidence_quote, source_name, source_url}) 포함.\n"
            "반환 JSON 키:\n"
            "- overview: {headcopy, bullets(3개), footnote}\n"
            "- own_profile: {headcopy, kpi_cards(최대4개), table:{headers:['진단 구분','핵심 지표','출처'], rows}, bullets(3개), footnote}\n"
            "- own_new_products: {headcopy, table:{headers:['라인업/신제품','핵심 스펙·USP','타겟 용도','출처'], rows(3~4행)}, bullets(3개), footnote}\n"
            "- own_products_price: {headcopy, table:{headers:['라인업/규격','특징·소재','정가 / 할인가(할인율)','출처'], rows(3~5행)}, "
            "price_discount_items:[{label, list_price(만원 숫자), sale_price(만원 숫자), discount_pct(% 숫자)}](3~5개, 원문 가격 확인 시만), bullets(3개), footnote}"
        )
        return await self.claude.complete_json(
            system_prompt=(
                "You are a senior strategy director at PTKOREA Division 4 building a verified Korean Factbook. "
                "Never invent statistics or strip negative '-' signs. Return valid RFC8259 JSON only."
            ),
            user_prompt=prompt,
            max_tokens=5200,
        )

    async def _run_batch_own_channels_press(
        self, project: Project, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        own_reports = [r for r in ctx["perplexity_reports"] if r["section"] == "1_OWN"]
        own_posts = [p for p in ctx["sns_posts"] if p["owner"] == "OWN"]
        prompt = (
            f"타겟: {ctx['target']} | 기간: {ctx['period']}\n\n"
            f"[자사 리서치]\n{json.dumps(own_reports, ensure_ascii=False)}\n\n"
            f"[SNS 계정/자사 게시물]\n{json.dumps({'profiles': ctx['sns_profiles'], 'posts': own_posts}, ensure_ascii=False)}\n\n"
            f"[언론 보도 샘플]\n{json.dumps(ctx['news_items'][:10], ensure_ascii=False)}\n\n"
            "아래 5개 자사 채널·PR 블록 JSON을 작성해줘. 마크다운(**)/각주([1]) 금지, 문자열 내 작은따옴표(')만 사용.\n"
            "각 블록 bullets 3개({claim, evidence_quote, source_name, source_url}) 필수.\n"
            "반환 JSON 키:\n"
            "- own_channels: {headcopy, bullets(3개 — 공식 채널 팔로워·효율 진단), footnote}\n"
            "- own_instagram_top5: {headcopy, bullets(3개 — 자사 인스타그램 고반응 콘텐츠 패턴·시사점), footnote}\n"
            "- own_youtube_top5: {headcopy, bullets(3개 — 자사 유튜브 영상 조회·시청 지속 요인), footnote}\n"
            "- own_creator_collabs: {headcopy, table:{headers:['게시일','협업·캠페인명','채널','조회·반응','성과 특징'], rows(3~5행)}, bullets(3개), footnote}\n"
            "- own_press_analysis: {headcopy, bullets(3개 — 자사 언론 보도 시기별 이슈·핵심 PR 논조), footnote}"
        )
        return await self.claude.complete_json(
            system_prompt=(
                "You are a senior digital & PR director at PTKOREA Division 4. "
                "Analyze owned IG, YT, creator collaborations, and Korean news press strictly from provided data. "
                "Never put unescaped double quotes or newlines inside JSON string values; use single quotes only. Return valid RFC8259 JSON only."
            ),
            user_prompt=prompt,
            max_tokens=6400,
        )

    async def _run_batch_market(
        self, project: Project, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        mkt_reports = [r for r in ctx["perplexity_reports"] if r["section"] == "2_MARKET"]
        prompt = (
            f"타겟: {ctx['target']} | 기간: {ctx['period']} | 경쟁: {', '.join(ctx['competitors']) or '없음'}\n\n"
            f"[Perplexity 시장·유통·플레이어 리서치]\n{json.dumps(mkt_reports, ensure_ascii=False)}\n\n"
            f"[데이터랩 요약]\n{json.dumps(ctx['datalab'], ensure_ascii=False)}\n\n"
            "아래 4개 시장 분석 슬라이드 블록 JSON을 작성해줘. 근거 없는 숫자 금지(없으면 '확인 못 함').\n"
            "반환 JSON 키:\n"
            "- market_overview: {headcopy, kpi_cards(최대4개), table:{headers:['구분/기관','시장 수치','성장률·기준'], rows}, chart_items:[{label, value(숫자만), highlight(bool)}], chart_unit, chart_title, bullets(3개), footnote}\n"
            "- market_demand_trend: {headcopy, table:{headers:['검색 그룹','구분','전후반기 증감','피크 시점'], rows}, bullets(3개 — 계절성·검색 피크 드라이버), footnote}\n"
            "- market_signals: {headcopy, table:{headers:['신호/규제 항목','관찰 내용 및 근거 수치','전략적 시사점'], rows}, bullets(3개), footnote}\n"
            "- market_players: {headcopy, table:{headers:['유형','브랜드','포지션 근거','가격대','주 채널'], rows}, bullets(3개), footnote}"
        )
        return await self.claude.complete_json(
            system_prompt=(
                "You are a senior market research director at PTKOREA Division 4. "
                "Synthesize macro market sizing, seasonal demand, retail signals, and player landscape strictly from verified sources. Return valid JSON only."
            ),
            user_prompt=prompt,
            max_tokens=5000,
        )

    async def _run_batch_comp_matrix_detail(
        self, project: Project, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        comp_reports = [r for r in ctx["perplexity_reports"] if r["section"] in {"3_COMPETITOR", "1_OWN"}]
        n_comp = min(4, len(project.competitors))
        comp_list_desc = ", ".join(f"{c.brand_name} {c.product_name}" for c in project.competitors[:4]) or "없음"
        prompt = (
            f"타겟: {ctx['target']} | 비교 경쟁사({n_comp}개): {comp_list_desc}\n\n"
            f"[경쟁·자사 리서치]\n{json.dumps(comp_reports, ensure_ascii=False)}\n\n"
            f"[데이터랩]\n{json.dumps(ctx['datalab'], ensure_ascii=False)}\n\n"
            "아래 3개 키(경쟁 매트릭스·가격 추이·경쟁사 1:1 상세 배열) JSON을 작성해줘.\n"
            "마크다운(**)/각주([1]) 금지, 문자열 내 작은따옴표(') 사용.\n"
            "반환 JSON 키:\n"
            "- competitor_matrix: {headcopy, table:{headers:['구분','자사','경쟁1','경쟁2','경쟁3'], rows(최대5행)}, bullets(3개), footnote}\n"
            "- competitor_price_trend: {headcopy, table:{headers:['브랜드/모델','규격·기준 가격','포지션 특징'], rows}, bullets(3개), footnote}\n"
            f"- competitor_details: 길이 {n_comp} 배열(경쟁사 순서 일치). 각 원소={{headcopy, table:{{headers:['비교 항목','경쟁사 현황','자사 대비 시사점'], rows(3~4행)}}, bullets(3개), footnote}}"
        )
        return await self.claude.complete_json(
            system_prompt=(
                "You are a senior competitive intelligence director at PTKOREA Division 4. "
                "Produce sharp 1:1 competitor deep dives strictly grounded in collected research and DataLab metrics. Return valid JSON only."
            ),
            user_prompt=prompt,
            max_tokens=5800,
        )

    async def _run_batch_comp_sns_press_mkt(
        self, project: Project, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        comp_reports = [r for r in ctx["perplexity_reports"] if r["section"] in {"3_COMPETITOR", "1_OWN"}]
        brands = [project.brand_name, *[c.brand_name for c in project.competitors[:3]]]
        prompt = (
            f"타겟: {ctx['target']} | 브랜드 비교축: {', '.join(brands)}\n\n"
            f"[경쟁 리서치]\n{json.dumps(comp_reports, ensure_ascii=False)}\n\n"
            f"[SNS 게시물]\n{json.dumps(ctx['sns_posts'], ensure_ascii=False)}\n\n"
            f"[언론 보도]\n{json.dumps(ctx['news_items'], ensure_ascii=False)}\n\n"
            "아래 4개 경쟁사 SNS·언론보도·마케팅 6분류 블록 JSON을 작성해줘. 각 블록 bullets 3개 필수.\n"
            "반환 JSON 키:\n"
            "- competitor_sns_top5: {headcopy, bullets(3개 — 경쟁사 콘텐츠 강점·자사 대비 차이), footnote}\n"
            "- competitor_press: {headcopy, bullets(3개 — 자사 vs 경쟁사 언론 보도량 및 PR 메시지 차이), footnote}\n"
            "- competitor_marketing_6: {headcopy, table:{headers:['활동 분류','자사','경쟁1','경쟁2','경쟁3'], "
            "rows(정확히 6행: 디지털 캠페인, 온라인 이벤트, 소셜 콘텐츠, 인플루언서 협업, 바이럴·커뮤니티, 미디어·PR — 각 셀 <=34자 완결형)}, "
            f"heatmap_scores:[{{axis, scores:[{{brand, score(1~5 정수)}}]}}] (6축 x 브랜드 {brands}), bullets(3개), footnote}}\n"
            "- competitor_marketing_detail: {headcopy, table:{headers:['마케팅 축','경쟁사 대표 실행 사례','자사 전략 시사점'], rows(4~5행)}, bullets(3개), footnote}"
        )
        return await self.claude.complete_json(
            system_prompt=(
                "You are a marketing strategist at PTKOREA Division 4 auditing competitor SNS, PR coverage, and 6-axis marketing intensity. "
                "Score heatmap cells 1-5 strictly based on collected evidence. Return valid JSON only."
            ),
            user_prompt=prompt,
            max_tokens=5600,
        )

    async def _run_batch_consumer_voc(
        self, project: Project, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        cons_reports = [r for r in ctx["perplexity_reports"] if r["section"] in {"4_CONSUMER", "1_OWN"}]
        prompt = (
            f"타겟: {ctx['target']} | 경쟁: {', '.join(ctx['competitors']) or '없음'}\n\n"
            f"[Perplexity 소비자 리서치]\n{json.dumps(cons_reports, ensure_ascii=False)}\n\n"
            f"[실소비자 커뮤니티/블로그 VOC]\n{json.dumps(ctx['consumer_voc'], ensure_ascii=False)}\n\n"
            "아래 4개 소비자 분석 블록 JSON을 작성해줘. 각 블록 bullets 3개({claim, evidence_quote, source_name, source_url}) 필수.\n"
            "반환 JSON 키:\n"
            "- consumer_target: {headcopy, table:{headers:['타깃 페르소나','이용 장면','핵심 구매 기준(KBF)','불만/이탈 장벽'], rows(3~4행)}, bullets(3개), footnote}\n"
            "- consumer_voc: {headcopy, bullets(3개 — 감성 분포 및 채널별 발화 특성), footnote}\n"
            "- consumer_voc_voices: {headcopy, table:{headers:['믿고 사는 이유 (긍정 KBF 발화)','이탈·고민 요인 (우려/허들 발화)'], rows(3~4행)}, bullets(3개), footnote}\n"
            "- consumer_brand_compare: {headcopy, table:{headers:['브랜드','핵심 호감·연상 키워드','우려·이탈 키워드','표본 근거'], rows(3~4행)}, bullets(3개), footnote}"
        )
        return await self.claude.complete_json(
            system_prompt=(
                "You are a senior consumer insights director at PTKOREA Division 4. "
                "Extract real KBF triggers, friction points, and brand perception differences strictly from Korean VOC & reports. "
                "Never put unescaped double quotes or newlines inside JSON string values; use single quotes only. Return valid RFC8259 JSON only."
            ),
            user_prompt=prompt,
            max_tokens=6400,
        )

    async def _run_batch_consumer_trends_bench(
        self, project: Project, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        cons_reports = [r for r in ctx["perplexity_reports"] if r["section"] in {"4_CONSUMER", "2_MARKET"}]
        prompt = (
            f"타겟: {ctx['target']} | 기간: {ctx['period']}\n\n"
            f"[소비자·소셜 트렌드 및 타 업종 벤치마크 리서치]\n{json.dumps(cons_reports, ensure_ascii=False)}\n\n"
            f"[SNS 고반응 포맷 참고]\n{json.dumps(ctx['sns_posts'][:8], ensure_ascii=False)}\n\n"
            "아래 3개 트렌드·벤치마크 블록 JSON을 작성해줘. 구체적 사례 브랜드와 메커니즘이 확인되면 명시하고, 없으면 '확인 못 함'.\n"
            "반환 JSON 키:\n"
            "- consumer_trends_social: {headcopy, table:{headers:['트렌드 영역','최근 소비·콘텐츠 변화','캠페인 적용 기회'], rows(3~4행)}, bullets(3개), footnote}\n"
            "- consumer_benchmarks: {headcopy, table:{headers:['벤치마크 영역','선도 브랜드·사례','성과/반응 메커니즘','적용 가능성'], rows(3~4행)}, bullets(3개), footnote}\n"
            "- consumer_benchmark_detail: {headcopy, table:{headers:['이식 과제','현재 공백(AS-IS)','실행 이식 방향(TO-BE)','기대 KPI'], rows(3~4행)}, bullets(3개), footnote}"
        )
        return await self.claude.complete_json(
            system_prompt=(
                "You are a creative & trend strategist at PTKOREA Division 4 translating social trends and cross-industry benchmarks into actionable plans. Return valid JSON only."
            ),
            user_prompt=prompt,
            max_tokens=4800,
        )

    async def _run_batch_summary_conclusion(
        self, project: Project, ctx: dict[str, Any], split_mode: SummarySplitMode
    ) -> dict[str, Any]:
        summary_count = 4 if split_mode == SummarySplitMode.SPLIT_4 else 2
        prompt = (
            f"타겟: {ctx['target']} | 기간: {ctx['period']} | 경쟁: {', '.join(ctx['competitors']) or '없음'}\n\n"
            f"[Perplexity 요약]\n{json.dumps([{'section': r['section'], 'title': r['title'], 'excerpt': r['content'][:800]} for r in ctx['perplexity_reports']], ensure_ascii=False)}\n\n"
            f"[데이터랩]\n{json.dumps(ctx['datalab'], ensure_ascii=False)}\n\n"
            f"[SNS·뉴스 요약]\n{json.dumps({'profiles': ctx['sns_profiles'], 'top_posts': ctx['sns_posts'][:6], 'press_count': len(ctx['news_items'])}, ensure_ascii=False)}\n\n"
            f"[VOC 샘플]\n{json.dumps(ctx['consumer_voc'][:10], ensure_ascii=False)}\n\n"
            "아래 3개 섹션 JSON을 작성해줘. 마크다운(**), 각주([1]) 금지, 문자열 내부 작은따옴표(') 사용.\n"
            f"- summary_parts: 길이 {summary_count} 배열. 각 원소={{headcopy, table:{{headers:['영역','확인된 핵심 사실','전략적 의미'], rows}}, bullets:[{{claim, evidence_quote, source_name}}] (반드시 3개)}}\n"
            "- as_is_to_be: {headcopy, as_is_points(3개 완결 문장), key_issues(3개 완결 문장), to_be_directions(3개 완결 문장)}\n"
            "- data_gaps: {headcopy, table:{headers:['확인 불가(공백) 항목','미수집 사유','보완 과제'], rows(4~5행)}, bullets:[{{claim, evidence_quote, source_name}}] (2개)}"
        )
        return await self.claude.complete_json(
            system_prompt=(
                "You synthesize executive 3C recaps, AS-IS->TO-BE strategy, and transparent data-gap audits for PTKOREA Division 4. "
                "Return valid JSON only without markdown."
            ),
            user_prompt=prompt,
            max_tokens=5000,
        )

    @staticmethod
    def _apply_synthesis(
        deck: list[SlideDraft],
        res: dict[str, Any],
        split_mode: SummarySplitMode,
        project: Project,
    ) -> None:
        key_map = {
            "OVERVIEW": "overview",
            "OWN_PROFILE": "own_profile",
            "OWN_NEW_PRODUCTS": "own_new_products",
            "OWN_PRODUCTS_PRICE": "own_products_price",
            "OWN_CHANNELS": "own_channels",
            "OWN_INSTAGRAM_TOP5": "own_instagram_top5",
            "OWN_YOUTUBE_TOP5": "own_youtube_top5",
            "OWN_CREATOR_COLLABS": "own_creator_collabs",
            "OWN_PRESS_ANALYSIS": "own_press_analysis",
            "MARKET_OVERVIEW": "market_overview",
            "MARKET_DEMAND_TREND": "market_demand_trend",
            "MARKET_SIGNALS": "market_signals",
            "MARKET_PLAYERS": "market_players",
            "COMPETITOR_MATRIX": "competitor_matrix",
            "COMPETITOR_PRICE_TREND": "competitor_price_trend",
            "COMPETITOR_SNS_TOP5": "competitor_sns_top5",
            "COMPETITOR_PRESS": "competitor_press",
            "COMPETITOR_MARKETING_6": "competitor_marketing_6",
            "COMPETITOR_MARKETING_DETAIL": "competitor_marketing_detail",
            "CONSUMER_TARGET": "consumer_target",
            "CONSUMER_VOC": "consumer_voc",
            "CONSUMER_VOC_VOICES": "consumer_voc_voices",
            "CONSUMER_BRAND_COMPARE": "consumer_brand_compare",
            "CONSUMER_TRENDS_SOCIAL": "consumer_trends_social",
            "CONSUMER_BENCHMARKS": "consumer_benchmarks",
            "CONSUMER_BENCHMARK_DETAIL": "consumer_benchmark_detail",
            "DATA_GAP": "data_gaps",
        }
        brands = [project.brand_name, *[c.brand_name for c in project.competitors[:3]]]
        comp_details = res.get("competitor_details") if isinstance(res.get("competitor_details"), list) else []
        comp_detail_idx = 0
        summary_parts = res.get("summary_parts") if isinstance(res.get("summary_parts"), list) else []
        summary_idx = 0

        sns_slides = {"OWN_INSTAGRAM_TOP5", "OWN_YOUTUBE_TOP5", "COMPETITOR_SNS_TOP5"}
        press_slides = {"OWN_PRESS_ANALYSIS", "COMPETITOR_PRESS"}

        for slide in deck:
            if slide.slide_type in key_map:
                block = res.get(key_map[slide.slide_type])
                if not isinstance(block, dict):
                    continue
                hc = clean_slide_text(block.get("headcopy"))
                if hc:
                    slide.headcopy = hc[:360]
                if "kpi_cards" in block and slide.slide_type not in (sns_slides | press_slides):
                    slide.kpi_cards_json = _sanitize_kpis(block.get("kpi_cards"), list(slide.kpi_cards_json or []))
                if "table" in block and slide.slide_type not in press_slides:
                    slide.table_json = _sanitize_table(block.get("table"), slide.table_json)
                if "bullets" in block:
                    slide.bullets_json = _sanitize_bullets(block.get("bullets"), list(slide.bullets_json or []))
                fn = clean_slide_text(block.get("footnote"))
                if fn and not slide.footnote:
                    slide.footnote = fn[:480]

                # Handle chart metadata per asset_type
                assets = list(slide.visual_assets_json or [])
                if assets:
                    first = dict(assets[0])
                    atype = first.get("asset_type")
                    if atype == "HORIZONTAL_BAR_CHART":
                        bar_items = _sanitize_bar_items(block.get("chart_items"))
                        if bar_items:
                            first["title"] = clean_slide_text(block.get("chart_title"))[:60] or first.get("title")
                            first["metadata"] = {"unit": clean_slide_text(block.get("chart_unit"))[:16], "items": bar_items}
                            slide.visual_assets_json = [first, *assets[1:]]
                        else:
                            slide.visual_assets_json = []
                    elif atype == "PRICE_DISCOUNT_BAR":
                        pd_items = _sanitize_price_discount_items(block.get("price_discount_items"))
                        if pd_items:
                            first["metadata"] = {"unit": "만원", "items": pd_items}
                            slide.visual_assets_json = [first, *assets[1:]]
                        else:
                            slide.visual_assets_json = []
                    elif atype == "MARKETING_HEATMAP":
                        hm_rows = _sanitize_heatmap_rows(block.get("heatmap_scores"), brands)
                        if hm_rows:
                            first["metadata"] = {"brands": brands, "rows": hm_rows}
                            slide.visual_assets_json = [first, *assets[1:]]

            elif slide.slide_type == "COMPETITOR_DETAIL":
                if comp_detail_idx < len(comp_details) and isinstance(comp_details[comp_detail_idx], dict):
                    block = comp_details[comp_detail_idx]
                    hc = clean_slide_text(block.get("headcopy"))
                    if hc:
                        slide.headcopy = hc[:360]
                    slide.table_json = _sanitize_table(block.get("table"), slide.table_json)
                    slide.bullets_json = _sanitize_bullets(block.get("bullets"), list(slide.bullets_json or []))
                comp_detail_idx += 1

            elif slide.slide_type == "SUMMARY_PART":
                if summary_idx < len(summary_parts) and isinstance(summary_parts[summary_idx], dict):
                    block = summary_parts[summary_idx]
                    hc = clean_slide_text(block.get("headcopy"))
                    if hc:
                        slide.headcopy = hc[:360]
                    slide.table_json = _sanitize_table(block.get("table"), slide.table_json)
                    slide.bullets_json = _sanitize_bullets(block.get("bullets"), list(slide.bullets_json or []))
                summary_idx += 1

            elif slide.slide_type == "CONCLUSION_ASIS_TOBE":
                a2b = res.get("as_is_to_be")
                if isinstance(a2b, dict):
                    hc = clean_slide_text(a2b.get("headcopy"))
                    if hc:
                        slide.headcopy = hc[:360]
                    existing_a2b = slide.as_is_to_be_json or {}
                    slide.as_is_to_be_json = {
                        "as_is_points": [
                            clean_slide_text(x)[:135]
                            for x in (a2b.get("as_is_points") or existing_a2b.get("as_is_points", []))
                            if clean_slide_text(x)
                        ][:3],
                        "key_issues": [
                            clean_slide_text(x)[:135]
                            for x in (a2b.get("key_issues") or existing_a2b.get("key_issues", []))
                            if clean_slide_text(x)
                        ][:3],
                        "to_be_directions": [
                            clean_slide_text(x)[:135]
                            for x in (a2b.get("to_be_directions") or existing_a2b.get("to_be_directions", []))
                            if clean_slide_text(x)
                        ][:3],
                        "linked_fact_ids": existing_a2b.get("linked_fact_ids", []),
                    }
