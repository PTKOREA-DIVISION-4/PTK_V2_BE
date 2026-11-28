from __future__ import annotations

from app.models.collection import DataLabSeries, MediaAsset, RawSourceItem, SnsTopPost
from app.models.factbook import FactItem, SlideDraft
from app.models.project import Project
from app.schemas.common import SectionCode, SummarySplitMode
from app.services.deck_sections import (
    attach_verified_source_urls,
    build_competitor_section_slides,
    build_consumer_section_slides,
    build_market_section_slides,
    build_own_section_slides,
    build_section5_slides,
    clean_slide_text,
    facts_to_bullets,
    format_post_metrics_caption,
    recompute_index_slide,
    sanitize_slide_draft,
    smart_truncate,
)

__all__ = [
    "attach_verified_source_urls",
    "build_deterministic_deck",
    "build_section5_slides",
    "clean_slide_text",
    "facts_to_bullets",
    "format_post_metrics_caption",
    "recompute_index_slide",
    "sanitize_slide_draft",
    "smart_truncate",
]


def build_deterministic_deck(
    *,
    project: Project,
    sources: list[RawSourceItem],
    facts: list[FactItem],
    datalab_series: list[DataLabSeries],
    sns_posts: list[SnsTopPost],
    media_assets: list[MediaAsset],
    split_mode: SummarySplitMode,
) -> list[SlideDraft]:
    """Build a high-density 36~42 slide multi-section deck with INDEX, section dividers, and verified links."""
    asset_by_id = {a.id: a for a in media_assets}
    facts_by_sec: dict[str, list[FactItem]] = {}
    for f in facts:
        facts_by_sec.setdefault(f.section_code, []).append(f)

    own_dl = [
        s for s in datalab_series if s.owner_type == "OWN" and s.metric_type == "SEARCH_TREND"
    ]
    search_dl = [s for s in datalab_series if s.metric_type == "SEARCH_TREND"]
    collab_label = f"{project.brand_name} 협업"
    own_sns = [
        p for p in sns_posts if p.owner_type == "OWN" and p.brand_label != collab_label
    ]
    comp_sns = [
        p for p in sns_posts if p.owner_type == "COMPETITOR" and p.brand_label != collab_label
    ][:5]
    collab_sns = [
        p for p in sns_posts if p.is_creator_collab or p.brand_label == collab_label
    ][:6]
    profile_sources = [
        s for s in sources if (s.metadata_json or {}).get("is_account_profile")
    ]

    comp_names = (
        ", ".join(f"{c.brand_name} {c.product_name}".strip() for c in project.competitors)
        or "주요 경쟁군"
    )
    track_label = (
        "리뷰·실사용 후기 중심(Track A)"
        if project.analysis_track == "REVIEW_CENTRIC"
        else "시장·검색 지표 중심(Track B)"
    )
    dl_note = (
        own_dl[0].methodology_note
        if own_dl
        else f"출처: 네이버 데이터랩 ({project.period_start}~{project.period_end})"
    )

    slides: list[SlideDraft] = []
    order = 1

    # ── 0-0. COVER (앞장 표지) ──────────────────────────────────────────────
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OVERVIEW.value,
            slide_order=order,
            slide_type="COVER",
            title=project.name[:90],
            headcopy=f"단일 분석 타겟: {project.brand_name} — {project.product_name}",
            kpi_cards_json=[
                {
                    "label": "단일 분석 타겟",
                    "value": f"{project.brand_name} · {project.product_name}",
                    "delta": project.industry_category,
                    "basis": "Single-Brand Scope",
                },
                {
                    "label": "수집·분석 기간",
                    "value": f"{project.period_start} ~ {project.period_end}",
                    "delta": f"경쟁 {len(project.competitors)}종",
                    "basis": "정량 시계열 · 실증 원천",
                },
                {
                    "label": "분석 트랙",
                    "value": "Track A (후기·실사용)" if project.analysis_track == "REVIEW_CENTRIC" else "Track B (시장·검색)",
                    "delta": track_label,
                    "basis": "Division 4 Factbook",
                },
            ],
            table_json=None,
            bullets_json=[],
            footnote=f"DIVISION 4 · FACTBOOK REPORT | {project.industry_category}",
        )
    )
    order += 1

    # ── 0-1. INDEX (populated dynamically after all slides assemble) ──────────
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OVERVIEW.value,
            slide_order=order,
            slide_type="INDEX",
            title="INDEX",
            headcopy=f"{project.brand_name} {project.product_name} 팩트북 목차",
            kpi_cards_json=[],
            table_json={"headers": ["PART", "핵심 분석 영역", "장표 수", "페이지"], "rows": []},
            bullets_json=[],
            footnote=f"{project.brand_name} · {project.product_name} ({project.period_start} ~ {project.period_end})",
        )
    )
    order += 1

    # ── 0. OVERVIEW ──────────────────────────────────────────────────────────
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OVERVIEW.value,
            slide_order=order,
            slide_type="OVERVIEW",
            title="0. 분석 개요 및 단일 브랜드·제품 조사 프레임",
            headcopy=(
                f"브랜드 '{project.brand_name}' · 단일 제품 '{project.product_name}'을 기준점으로 "
                f"{project.period_start}~{project.period_end} 기간의 시장·자사·경쟁·소비자 실증 팩트북 구성"
            ),
            kpi_cards_json=[
                {"label": "단일 분석 타겟", "value": f"{project.brand_name} {project.product_name}", "delta": project.industry_category, "basis": track_label},
                {"label": "비교 경쟁 세트", "value": f"{len(project.competitors)}개 제품", "delta": comp_names[:34], "basis": "1:1 동일 카테고리 매칭"},
                {"label": "수집·검증 원천", "value": f"{len(sources)}건", "delta": f"추출 팩트 {len(facts)}건", "basis": "리서치·SNS·뉴스·VOC"},
                {"label": "정량 시계열·SNS", "value": f"DL {len(search_dl)}종 / SNS {len(sns_posts)}건", "delta": f"협업 {len(collab_sns)}건 포함", "basis": "네이버 데이터랩 · ScrapeCreators"},
            ],
            table_json={
                "headers": ["조사 구분", "설정 기준값", "수집 채널 및 검증 방식"],
                "rows": [
                    ["대상 브랜드·제품", f"{project.brand_name} / {project.product_name}", "단일 브랜드·단일 주력 제품 원칙 적용"],
                    ["조사 기간", f"{project.period_start} ~ {project.period_end}", "전 기간 정량 추이 + 기간 내 SNS 필터링"],
                    ["경쟁 세트", comp_names[:42], "네이버 데이터랩 SoS 및 1:1 심층·6분류 비교"],
                    ["수집 소스", f"리서치·SNS·커뮤니티·언론 {len(sources)}건", "확인 불가 수치는 미확인(확인 못 함) 처리"],
                ],
            },
            bullets_json=[
                {
                    "claim": f"단일 브랜드·제품 원칙: {project.brand_name} '{project.product_name}' 기준으로 검색·SNS·VOC·뉴스 모수를 고정해 노이즈를 차단함",
                    "evidence_quote": None,
                    "source_name": "조사 설계 기준",
                    "source_url": None,
                    "fact_id": None,
                },
                {
                    "claim": f"트랙 분기: {track_label} 가중치를 적용해 시장 지표와 소비자 실사용 발화를 균형 있게 구조화함",
                    "evidence_quote": None,
                    "source_name": "조사 계획 설정",
                    "source_url": None,
                    "fact_id": None,
                },
                {
                    "claim": "투명성 원칙: 공개·API 데이터로 확인되지 않은 수치는 추측하지 않고 마지막 데이터 공백 장표에 별도 기록함",
                    "evidence_quote": None,
                    "source_name": "Division 4 QC 규칙",
                    "source_url": None,
                    "fact_id": None,
                },
            ],
            footnote=f"출처: 프로젝트 설정 및 다중 API 수집 결과 | 기간: {project.period_start}~{project.period_end}",
        )
    )
    order += 1

    # ── 1~4. CORE SECTIONS ───────────────────────────────────────────────────
    own_slides, order = build_own_section_slides(
        project=project,
        sources=sources,
        facts_by_sec=facts_by_sec,
        own_dl=own_dl,
        own_sns=own_sns,
        collab_sns=collab_sns,
        profile_sources=profile_sources,
        asset_by_id=asset_by_id,
        start_order=order,
    )
    slides.extend(own_slides)

    market_slides, order = build_market_section_slides(
        project=project,
        facts_by_sec=facts_by_sec,
        search_dl=search_dl,
        dl_note=dl_note,
        start_order=order,
    )
    slides.extend(market_slides)

    comp_slides, order = build_competitor_section_slides(
        project=project,
        sources=sources,
        facts=facts,
        facts_by_sec=facts_by_sec,
        search_dl=search_dl,
        sns_posts=sns_posts,
        comp_sns=comp_sns,
        asset_by_id=asset_by_id,
        dl_note=dl_note,
        start_order=order,
    )
    slides.extend(comp_slides)

    cons_slides, order = build_consumer_section_slides(
        project=project,
        sources=sources,
        facts_by_sec=facts_by_sec,
        start_order=order,
    )
    slides.extend(cons_slides)

    # ── 5. SUMMARY, AS-IS->TO-BE, DATA GAP, APPENDIX ─────────────────────────
    sec5 = build_section5_slides(
        project=project,
        sources=sources,
        facts=facts,
        datalab_series=datalab_series,
        non_summary_slides=slides,
        split_mode=split_mode,
        start_order=order,
    )
    slides.extend(sec5)

    recompute_index_slide(slides)
    attach_verified_source_urls(slides, sources, sns_posts)
    return [sanitize_slide_draft(s) for s in slides]
