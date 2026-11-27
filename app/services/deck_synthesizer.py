from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.integrations.anthropic_client import AnthropicClient
from app.models.collection import DataLabSeries, MediaAsset, RawSourceItem, SnsTopPost
from app.models.factbook import FactItem, SlideDraft
from app.models.project import Project
from app.schemas.common import SectionCode, SummarySplitMode
from app.services.deck_blueprint import (
    build_deterministic_deck,
    clean_slide_text,
    sanitize_slide_draft,
    smart_truncate,
)

logger = logging.getLogger(__name__)


def _sanitize_bullets(raw_list: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw_list, list) or not raw_list:
        return fallback
    cleaned: list[dict[str, Any]] = []
    seen_claims: set[str] = set()
    for item in raw_list[:4]:
        if isinstance(item, str):
            claim = smart_truncate(item, 145)
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
        claim = smart_truncate(item.get("claim"), 145)
        if not claim or claim in seen_claims:
            continue
        seen_claims.add(claim)
        cleaned.append(
            {
                "claim": claim,
                "evidence_quote": smart_truncate(item.get("evidence_quote"), 130) or None,
                "source_name": smart_truncate(item.get("source_name"), 36) or None,
                "source_url": item.get("source_url"),
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
    for r in rows_raw[:6]:
        if not isinstance(r, list):
            continue
        padded = [smart_truncate(str(r[i]), 78) if i < len(r) else "-" for i in range(n_cols)]
        clean_rows.append(padded)
    return {"headers": headers, "rows": clean_rows} if clean_rows else fallback


def _sanitize_kpis(raw_kpis: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw_kpis, list) or not raw_kpis:
        return fallback
    out: list[dict[str, Any]] = []
    for item in raw_kpis[:4]:
        if not isinstance(item, dict):
            continue
        label = clean_slide_text(item.get("label"))[:24]
        val = clean_slide_text(item.get("value"))[:22]
        if not label or not val:
            continue
        out.append(
            {
                "label": label,
                "value": val,
                "delta": clean_slide_text(item.get("delta"))[:28] or None,
                "basis": clean_slide_text(item.get("basis"))[:30] or None,
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
        val = it.get("value")
        try:
            num = float(val)
        except (TypeError, ValueError):
            continue
        if label and num > 0:
            out.append(
                {
                    "label": label,
                    "value": round(num, 2),
                    "highlight": bool(it.get("highlight", False)),
                }
            )
    return out


class DeckSynthesizer:
    """Enriches grounded deterministic slides via 3 concurrent Claude synthesis batches."""

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

        context_payload = self._build_evidence_context(
            project=project,
            sources=sources,
            facts=facts,
            datalab_series=datalab_series,
            sns_posts=sns_posts,
        )

        batch1a_task = self._run_batch_overview_own(project, context_payload)
        batch1b_task = self._run_batch_market(project, context_payload)
        batch2_task = self._run_batch_competitor(project, context_payload)
        batch3_task = self._run_batch_consumer(project, context_payload)
        batch4_task = self._run_batch_summary_conclusion(project, context_payload, split_mode)

        batches = await asyncio.gather(
            batch1a_task, batch1b_task, batch2_task, batch3_task, batch4_task, return_exceptions=True
        )

        merged: dict[str, Any] = {}
        for idx, res in enumerate(batches, start=1):
            if isinstance(res, Exception):
                logger.warning("Claude synthesis batch %d failed (fallback preserved): %s", idx, res)
            elif isinstance(res, dict):
                merged.update(res)

        if merged:
            self._apply_synthesis(deck, merged, split_mode)
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
                "title": clean_slide_text(s.title)[:100],
                "content": clean_slide_text(s.content)[:2500],
                "citations": (s.metadata_json or {}).get("citations", [])[:5],
            }
            for s in sources
            if s.provider == "PERPLEXITY"
        ]
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
                "title": clean_slide_text(f.claim_text)[:100],
                "quote": clean_slide_text(f.evidence_quote)[:160],
                "url": f.source_url,
            }
            for f in facts
            if f.section_code == SectionCode.CONSUMER.value
        ][:26]
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
            for p in sns_posts[:14]
        ]
        return {
            "target": f"{project.brand_name} / {project.product_name} ({project.industry_category})",
            "period": f"{project.period_start}~{project.period_end}",
            "competitors": [f"{c.brand_name} {c.product_name}".strip() for c in project.competitors],
            "perplexity_reports": perplexity_reports,
            "datalab": dl_items,
            "sns_profiles": sns_profiles,
            "sns_posts": sns_items,
            "consumer_voc": voc_items,
        }

    async def _run_batch_overview_own(
        self, project: Project, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        own_reports = [
            r for r in ctx["perplexity_reports"] if r["section"] in {"1_OWN", "3_COMPETITOR"}
        ]
        market_brief = [
            {"title": r["title"], "excerpt": r["content"][:900]}
            for r in ctx["perplexity_reports"]
            if r["section"] == "2_MARKET"
        ]
        prompt = (
            f"타겟: {ctx['target']} | 기간: {ctx['period']} | 경쟁: {', '.join(ctx['competitors']) or '없음'}\n\n"
            f"[Perplexity 자사·경쟁 리서치]\n{json.dumps(own_reports, ensure_ascii=False)}\n\n"
            f"[시장 요약]\n{json.dumps(market_brief, ensure_ascii=False)}\n\n"
            f"[데이터랩]\n{json.dumps(ctx['datalab'], ensure_ascii=False)}\n\n"
            f"[SNS 계정/게시물]\n{json.dumps({'profiles': ctx['sns_profiles'], 'posts': ctx['sns_posts']}, ensure_ascii=False)}\n\n"
            "아래 6개 슬라이드 블록 JSON을 작성해줘. 제공된 자료에 없는 숫자는 절대 지어내지 말고 '확인 못 함'으로 표기해.\n"
            "중요 규칙: 음수(-12.5%, -3.4% 등)의 마이너스(-) 부호를 절대 빼먹지 말 것! 마크다운(**)과 [1][2] 각주 기호 금지.\n"
            "JSON 문자열 값 안에서는 큰따옴표(\") 대신 작은따옴표(')만 사용하고 줄바꿈을 넣지 마.\n"
            "모든 표 셀은 완결된 짧은 명사/문장(<=36자, 문장 중간 끊김 금지)으로 작성하고, headcopy는 겹치지 않는 결론형 1문장(50~85자).\n"
            "모든 슬라이드 블록에는 반드시 서로 다른 관점의 bullets 3개({claim, evidence_quote, source_name})를 포함해.\n"
            "반환 JSON 키:\n"
            "- overview: {headcopy, bullets(3개), footnote}\n"
            "- own_profile: {headcopy, kpi_cards:[{label, value, delta, basis}] (최대4개 — 하락폭은 반드시 '-' 표기), table:{headers, rows}, bullets(3개), footnote}\n"
            "- own_products_price: {headcopy, table:{headers:['모델/라인','특징·소재','공식가/행사가','출처'], rows}, chart_items:[{label, value(숫자만, 예: 31.9), highlight(bool)}] (최소 3개 이상), chart_unit:'만원', chart_title, bullets(3개), footnote}\n"
            "- own_channels: {headcopy(자사 공식 SNS 팔로워/구독자 규모 및 채널 운영 밀도를 핵심으로), bullets(3개 — 자사 유튜브/인스타 팔로워 vs 경쟁 SNS 계정 규모·조회 효율·유통 채널 연결 진단), footnote}\n"
            "- own_sns_top5: {headcopy, bullets(3개 — 자사 TOP 5 포맷·조회수·협찬 패턴 관찰), footnote}\n"
            "- own_campaigns: {headcopy, table:{headers:['구분/일시','활동/보도명','핵심 내용·성과','출처'], rows}, bullets(3개), footnote}"
        )
        return await self.claude.complete_json(
            system_prompt=(
                "You are a senior strategy director at PTKOREA Division 4 building a verified Korean Factbook. "
                "Never invent statistics or strip negative '-' signs from declines. Never use unescaped double quotes inside JSON strings. "
                "Write '확인 못 함' only when genuinely unverified. Return valid RFC8259 JSON only."
            ),
            user_prompt=prompt,
            max_tokens=5800,
        )

    async def _run_batch_market(
        self, project: Project, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        mkt_reports = [
            r for r in ctx["perplexity_reports"] if r["section"] in {"2_MARKET"}
        ]
        comp_price_brief = [
            {"title": r["title"], "excerpt": r["content"][:1200]}
            for r in ctx["perplexity_reports"]
            if r["section"] == "3_COMPETITOR"
        ]
        prompt = (
            f"타겟: {ctx['target']} | 기간: {ctx['period']} | 경쟁: {', '.join(ctx['competitors']) or '없음'}\n\n"
            f"[Perplexity 시장·유통·플레이어 리서치]\n{json.dumps(mkt_reports, ensure_ascii=False)}\n\n"
            f"[경쟁 가격/라인 참고]\n{json.dumps(comp_price_brief, ensure_ascii=False)}\n\n"
            f"[데이터랩 요약]\n{json.dumps(ctx['datalab'], ensure_ascii=False)}\n\n"
            "아래 3개 시장 분석 슬라이드 블록 JSON을 작성해줘. 제공된 자료에 없는 숫자는 절대 지어내지 말고 '확인 못 함'으로 표기해.\n"
            "중요 규칙: 음수(-3.4% 등)의 마이너스(-) 부호를 절대 빼먹지 말 것! 마크다운(**)과 [1][2] 각주 기호 금지.\n"
            "JSON 문자열 값 안에서는 큰따옴표(\") 대신 작은따옴표(')만 사용하고 줄바꿈을 넣지 마.\n"
            "모든 표 셀은 완결된 짧은 명사/문장(<=36자, 문장 중간 끊김 금지)으로 작성하고, headcopy는 결론형 1문장(50~85자).\n"
            "반환 JSON 키:\n"
            "- market_overview: {headcopy, kpi_cards(최대4개), table:{headers:['구분/기관','시장 수치','성장률·기준'], rows}, chart_items:[{label, value(숫자만, 예: 13.7), highlight(bool)}] (최소 3개), chart_unit, chart_title, bullets(3개), footnote}\n"
            "- market_signals: {headcopy, table:{headers:['신호/규제 항목','관찰 내용 및 근거 수치','전략적 시사점'], rows}, bullets(3개), footnote}\n"
            "- market_players: {headcopy, table:{headers:['유형','브랜드','포지션 근거','가격대','주 채널'], rows}, bullets(3개), footnote}"
        )
        return await self.claude.complete_json(
            system_prompt=(
                "You are a senior market research director at PTKOREA Division 4. "
                "Synthesize macro market sizing, retail signals, and player landscape strictly from verified Perplexity reports. "
                "Never use unescaped double quotes inside JSON strings. Return valid RFC8259 JSON only."
            ),
            user_prompt=prompt,
            max_tokens=4500,
        )

    async def _run_batch_competitor(
        self, project: Project, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        comp_reports = [r for r in ctx["perplexity_reports"] if r["section"] in {"3_COMPETITOR", "1_OWN", "2_MARKET"}]
        prompt = (
            f"타겟: {ctx['target']} | 경쟁: {', '.join(ctx['competitors']) or '없음'}\n\n"
            f"[Perplexity 경쟁·자사·시장 리서치]\n{json.dumps(comp_reports, ensure_ascii=False)}\n\n"
            f"[데이터랩]\n{json.dumps(ctx['datalab'], ensure_ascii=False)}\n\n"
            f"[SNS 게시물]\n{json.dumps(ctx['sns_posts'], ensure_ascii=False)}\n\n"
            "아래 4개 경쟁사 슬라이드 블록 JSON을 작성해줘. 근거 없는 수치 생성 금지(자료에 전혀 없는 항목만 '확인 못 함').\n"
            "중요: 리서치에서 경쟁 브랜드별 대표 캐리어 가격대·포지셔닝·마케팅 활동(캠페인·이벤트·SNS·협업·바이럴·PR)이 확인되면 반드시 구체적으로 채워 넣고(완결된 36자 이내 명사구), 정말 확인되지 않는 셀만 '확인 못 함' 표기.\n"
            "마크다운(**) 및 [1] 금지. JSON 문자열 값 안에서는 큰따옴표(\") 대신 작은따옴표(')만 사용해.\n"
            "모든 슬라이드 블록에는 반드시 서로 다른 관점의 bullets 3개({claim, evidence_quote, source_name})를 포함해줘.\n"
            "반환 JSON 키:\n"
            "- competitor_matrix: {headcopy, table:{headers:['구분','자사','경쟁1','경쟁2','경쟁3'], rows(최대5행)}, bullets(3개 — 검색 vs 쇼핑 SoS 격차 해석 포함), footnote}\n"
            "- competitor_price_trend: {headcopy, table:{headers:['브랜드/모델','규격·기준 가격','포지션 특징'], rows}, bullets(3개), footnote}\n"
            "- competitor_sns_top5: {headcopy, bullets(3개 — 경쟁사 콘텐츠 강점·자사 대비 차이), footnote}\n"
            "- competitor_marketing_6: {headcopy, table:{headers:['활동 분류','자사','경쟁1','경쟁2','경쟁3'], rows(정확히 6행: 디지털 캠페인, 온라인 이벤트, 소셜 콘텐츠, 인플루언서 협업, 바이럴·커뮤니티, 미디어·PR — 각 셀 <=36자 완결형)}, bullets(3개), footnote}"
        )
        return await self.claude.complete_json(
            system_prompt=(
                "You are a senior competitive intelligence director at PTKOREA Division 4. "
                "Extract every verified competitor fact from Perplexity, DataLab, and SNS sources without inventing numbers. Keep cells concise and complete (no mid-sentence truncation). Return valid RFC8259 JSON only."
            ),
            user_prompt=prompt,
            max_tokens=6200,
        )

    async def _run_batch_consumer(
        self, project: Project, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        cons_reports = [r for r in ctx["perplexity_reports"] if r["section"] in {"4_CONSUMER", "2_MARKET", "1_OWN"}]
        prompt = (
            f"타겟: {ctx['target']} | 경쟁: {', '.join(ctx['competitors']) or '없음'}\n\n"
            f"[Perplexity 소비자·시장 리서치]\n{json.dumps(cons_reports, ensure_ascii=False)}\n\n"
            f"[실소비자 커뮤니티/블로그 VOC]\n{json.dumps(ctx['consumer_voc'], ensure_ascii=False)}\n\n"
            "아래 4개 소비자 슬라이드 블록 JSON을 작성해줘. 근거 없는 수치 생성 금지(없으면 '확인 못 함').\n"
            "마크다운(**) 및 [1] 금지. JSON 문자열 값 안에서는 큰따옴표(\") 대신 작은따옴표(')만 사용해.\n"
            "중요: 모든 슬라이드 블록에는 반드시 서로 다른 관점의 bullets 3개({claim, evidence_quote, source_name})를 빠짐없이 포함해줘.\n"
            "반환 JSON 키:\n"
            "- consumer_target: {headcopy, table:{headers:['타깃 페르소나','이용 장면','핵심 구매 기준(KBF)','불만/이탈 장벽'], rows(3~4행)}, bullets(3개), footnote}\n"
            "- consumer_voc: {headcopy, bullets(3개 — 감성 분포 및 채널별 발화 특성), footnote}\n"
            "- consumer_voc_voices: {headcopy, table:{headers:['믿고 사는 이유 (긍정 KBF 발화)','이탈·고민 요인 (우려/허들 발화)'], rows(3~4행)}, bullets(3개), footnote}\n"
            "- consumer_trends: {headcopy, table:{headers:['트렌드/벤치마크','관찰 내용 및 성공 요인','자사 적용 방향'], rows(3~5행)}, bullets(3개), footnote}"
        )
        return await self.claude.complete_json(
            system_prompt=(
                "You are a senior consumer insights director at PTKOREA Division 4. "
                "Extract real KBF triggers and friction points strictly from provided Korean VOC & Perplexity reports. "
                "Never use unescaped double quotes inside string values. Return valid RFC8259 JSON only."
            ),
            user_prompt=prompt,
            max_tokens=6000,
        )

    async def _run_batch_summary_conclusion(
        self, project: Project, ctx: dict[str, Any], split_mode: SummarySplitMode
    ) -> dict[str, Any]:
        summary_count = 4 if split_mode == SummarySplitMode.SPLIT_4 else 2
        prompt = (
            f"타겟: {ctx['target']} | 기간: {ctx['period']} | 경쟁: {', '.join(ctx['competitors']) or '없음'}\n\n"
            f"[Perplexity 요약]\n{json.dumps([{'section': r['section'], 'title': r['title'], 'excerpt': r['content'][:950]} for r in ctx['perplexity_reports']], ensure_ascii=False)}\n\n"
            f"[데이터랩]\n{json.dumps(ctx['datalab'], ensure_ascii=False)}\n\n"
            f"[SNS 요약]\n{json.dumps({'profiles': ctx['sns_profiles'], 'top_posts': ctx['sns_posts'][:6]}, ensure_ascii=False)}\n\n"
            f"[VOC 샘플]\n{json.dumps(ctx['consumer_voc'][:10], ensure_ascii=False)}\n\n"
            "아래 3개 섹션 JSON을 작성해줘. 마크다운(**), 각주([1]) 금지, 문자열 내부 큰따옴표 대신 작은따옴표(') 사용.\n"
            "모든 표 셀은 완결형 55자 이하(중간 단어 잘림 금지).\n"
            f"- summary_parts: 길이 {summary_count} 배열. 각 원소={{headcopy, table:{{headers:['영역','확인된 핵심 사실','전략적 의미'], rows}}, bullets:[{{claim, evidence_quote, source_name}}] (반드시 3개 객체, 겹치지 않게)}}\n"
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
        deck: list[SlideDraft], res: dict[str, Any], split_mode: SummarySplitMode
    ) -> None:
        key_map = {
            "OVERVIEW": "overview",
            "OWN_PROFILE": "own_profile",
            "OWN_PRODUCTS_PRICE": "own_products_price",
            "OWN_CHANNELS": "own_channels",
            "OWN_SNS_TOP5": "own_sns_top5",
            "OWN_CAMPAIGNS": "own_campaigns",
            "MARKET_OVERVIEW": "market_overview",
            "MARKET_SIGNALS": "market_signals",
            "MARKET_PLAYERS": "market_players",
            "COMPETITOR_MATRIX": "competitor_matrix",
            "COMPETITOR_PRICE_TREND": "competitor_price_trend",
            "COMPETITOR_SNS_TOP5": "competitor_sns_top5",
            "COMPETITOR_MARKETING_6": "competitor_marketing_6",
            "CONSUMER_TARGET": "consumer_target",
            "CONSUMER_VOC": "consumer_voc",
            "CONSUMER_VOC_VOICES": "consumer_voc_voices",
            "CONSUMER_TRENDS": "consumer_trends",
            "DATA_GAP": "data_gaps",
        }
        summary_idx = 0
        summary_parts = res.get("summary_parts") if isinstance(res.get("summary_parts"), list) else []

        for slide in deck:
            if slide.slide_type in key_map:
                block = res.get(key_map[slide.slide_type])
                if not isinstance(block, dict):
                    continue
                hc = clean_slide_text(block.get("headcopy"))
                if hc:
                    slide.headcopy = hc[:360]
                if "kpi_cards" in block and slide.slide_type not in {"OWN_SNS_TOP5", "COMPETITOR_SNS_TOP5"}:
                    slide.kpi_cards_json = _sanitize_kpis(block.get("kpi_cards"), list(slide.kpi_cards_json or []))
                if "table" in block:
                    slide.table_json = _sanitize_table(block.get("table"), slide.table_json)
                if "bullets" in block:
                    slide.bullets_json = _sanitize_bullets(block.get("bullets"), list(slide.bullets_json or []))
                fn = clean_slide_text(block.get("footnote"))
                if fn and not slide.footnote:
                    slide.footnote = fn[:480]

                # Populate HORIZONTAL_BAR_CHART metadata if real numbers extracted
                bar_items = _sanitize_bar_items(block.get("chart_items"))
                if bar_items and slide.visual_assets_json:
                    first = dict(slide.visual_assets_json[0])
                    if first.get("asset_type") == "HORIZONTAL_BAR_CHART":
                        first["title"] = clean_slide_text(block.get("chart_title"))[:60] or first.get("title")
                        first["metadata"] = {
                            "unit": clean_slide_text(block.get("chart_unit"))[:16],
                            "items": bar_items,
                        }
                        slide.visual_assets_json = [first, *slide.visual_assets_json[1:]]
                elif slide.visual_assets_json and slide.visual_assets_json[0].get("asset_type") == "HORIZONTAL_BAR_CHART" and not bar_items:
                    # Drop empty chart asset so UI & PPTX render clean table/KPI without blank chart box
                    slide.visual_assets_json = []

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
