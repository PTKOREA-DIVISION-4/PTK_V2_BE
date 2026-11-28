from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.models.collection import DataLabSeries, MediaAsset, RawSourceItem, SnsTopPost
from app.models.factbook import FactItem, SlideDraft
from app.models.project import CompetitorTarget, Project
from app.schemas.common import SectionCode, SummarySplitMode
from app.services.press_metrics_service import PressMetricsService

PART_LABELS: dict[str, tuple[str, str]] = {
    SectionCode.OVERVIEW.value: ("PART 0", "분석 개요"),
    SectionCode.OWN.value: ("PART 1", "자사 분석 (제품·SNS·언론보도)"),
    SectionCode.MARKET.value: ("PART 2", "시장 분석 (규모·수요·플레이어)"),
    SectionCode.COMPETITOR.value: ("PART 3", "경쟁사 분석 (1:1 심층·PR·마케팅)"),
    SectionCode.CONSUMER.value: ("PART 4", "소비자 분석 · 트렌드 · 벤치마크"),
    SectionCode.SUMMARY_CONCLUSION.value: ("PART 5", "종합 요약 · 전략 방향 · 출처"),
}


def clean_slide_text(text: str | None) -> str:
    """Remove markdown emphasis and perplexity citation brackets while keeping URLs and signs intact."""
    if not text:
        return ""
    cleaned = text.replace("\xa0", " ").replace("**", "").replace("__", "").replace("`", "")
    cleaned = re.sub(r"\[(\d{1,2})\](?=\s|$|[.,;:\)])", "", cleaned)
    cleaned = cleaned.replace("###", "").replace("##", "").replace("# ", "")
    cleaned = re.sub(r"\.{2,}", "…", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def smart_truncate(text: str | None, max_len: int) -> str:
    """Truncate text cleanly at word boundary without leaving trailing orphan fragments."""
    t = clean_slide_text(text)
    if len(t) <= max_len:
        return t
    if max_len <= 3:
        return t[:max_len]
    cut = t[: max_len - 1]
    if " " in cut and cut.rfind(" ") >= int(max_len * 0.55):
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,·;/(-") + "…"


def format_post_metrics_caption(p: SnsTopPost) -> str:
    """Format post engagement stats cleanly without zero-view noise for IG photo posts."""
    parts = [f"좋아요 {p.likes:,}", f"댓글 {p.comments:,}"]
    if p.views > 0:
        parts.insert(0, f"조회 {p.views:,}")
    return f"{p.published_at.strftime('%Y-%m-%d')} | " + " / ".join(parts)


def facts_to_bullets(
    facts: list[FactItem], *, limit: int = 3, fallback_claim: str
) -> list[dict[str, Any]]:
    bullets: list[dict[str, Any]] = []
    seen_claims: set[str] = set()
    for f in facts:
        claim = smart_truncate(f.claim_text, 145)
        if not claim or claim in seen_claims:
            continue
        seen_claims.add(claim)
        bullets.append(
            {
                "claim": claim,
                "evidence_quote": smart_truncate(f.evidence_quote, 130) or None,
                "source_name": f.source_name,
                "source_url": f.source_url,
                "fact_id": f.id,
            }
        )
        if len(bullets) >= limit:
            break
    if not bullets:
        bullets.append(
            {
                "claim": fallback_claim,
                "evidence_quote": "확인 못 함 (수집 원문 부족 — 추가 리서치 권장)",
                "source_name": "팩트북 검증 기준",
                "source_url": None,
                "fact_id": None,
            }
        )
    return bullets


def sanitize_slide_draft(slide: SlideDraft) -> SlideDraft:
    """Apply clean_slide_text to top-level text, bullets, KPIs, and table cells."""
    slide.title = smart_truncate(slide.title, 120)
    slide.headcopy = clean_slide_text(slide.headcopy)[:360]
    slide.footnote = clean_slide_text(slide.footnote)[:480] if slide.footnote else None
    if slide.bullets_json:
        slide.bullets_json = [
            {
                **b,
                "claim": smart_truncate(b.get("claim"), 155),
                "evidence_quote": smart_truncate(b.get("evidence_quote"), 135) or None,
                "source_name": smart_truncate(b.get("source_name"), 44) or None,
            }
            for b in slide.bullets_json
        ]
    if slide.kpi_cards_json:
        slide.kpi_cards_json = [
            {
                **k,
                "label": clean_slide_text(k.get("label"))[:28],
                "value": clean_slide_text(k.get("value"))[:26],
                "delta": clean_slide_text(k.get("delta"))[:34] or None,
                "basis": clean_slide_text(k.get("basis"))[:34] or None,
            }
            for k in slide.kpi_cards_json
        ]
    return slide


def make_section_divider(
    *,
    project_id: str,
    section_code: str,
    order: int,
    part_title: str,
    subtitle: str,
    slide_topics: list[str],
    kpi_chips: list[dict[str, Any]],
    footnote: str,
) -> SlideDraft:
    return SlideDraft(
        project_id=project_id,
        section_code=section_code,
        slide_order=order,
        slide_type="SECTION_DIVIDER",
        title=part_title,
        headcopy=subtitle,
        kpi_cards_json=kpi_chips[:4],
        bullets_json=[
            {
                "claim": topic,
                "evidence_quote": None,
                "source_name": "섹션 구성 안내",
                "source_url": None,
                "fact_id": None,
            }
            for topic in slide_topics[:4]
        ],
        footnote=footnote,
    )


def recompute_index_slide(deck: list[SlideDraft]) -> None:
    """Update slide_order sequentially (1..N) and populate concise INDEX table with exact page ranges."""
    for idx, slide in enumerate(deck, start=1):
        slide.slide_order = idx

    index_slide = next((s for s in deck if s.slide_type == "INDEX"), None)
    if index_slide is None:
        return

    has_cover = any(s.slide_type == "COVER" for s in deck)
    page_offset = 0 if has_cover else 1

    ranges: dict[str, tuple[int, int, int, list[str]]] = {}
    for s in deck:
        if s.slide_type in {"COVER", "INDEX"}:
            continue
        pdf_page = s.slide_order + page_offset
        sec = s.section_code
        if sec not in ranges:
            ranges[sec] = (pdf_page, pdf_page, 1, [s.title])
        else:
            start_p, _, cnt, titles = ranges[sec]
            if s.slide_type != "SECTION_DIVIDER":
                titles.append(s.title)
            ranges[sec] = (start_p, pdf_page, cnt + 1, titles)

    rows: list[list[str]] = []
    for sec_enum in SectionCode:
        sec_code = sec_enum.value
        if sec_code not in ranges:
            continue
        part_tag, part_desc = PART_LABELS[sec_code]
        start_p, end_p, cnt, _ = ranges[sec_code]
        page_str = f"p.{start_p}" if start_p == end_p else f"p.{start_p} ~ p.{end_p}"
        rows.append([part_tag, part_desc, f"{cnt}장", page_str])

    total_pdf_pages = len(deck) + page_offset
    index_slide.title = "INDEX"
    index_slide.headcopy = f"총 {total_pdf_pages}페이지 구성"
    index_slide.kpi_cards_json = []
    index_slide.table_json = {
        "headers": ["PART", "핵심 분석 영역", "장표 수", "페이지"],
        "rows": rows,
    }
    index_slide.bullets_json = []


def attach_verified_source_urls(
    slides: list[SlideDraft],
    sources: list[RawSourceItem],
    sns_posts: list[SnsTopPost],
) -> None:
    """Attach un-truncated verified http(s) source URLs onto synthesized bullets without broken short strings."""
    fact_url_by_id: dict[str, str] = {}
    url_by_channel_sec: dict[tuple[str, str], str] = {}
    urls_by_section: dict[str, list[str]] = {}
    all_valid_urls: list[str] = []

    for src in sources:
        candidates: list[str] = []
        if src.source_url and src.source_url.startswith("http"):
            candidates.append(src.source_url.strip())
        meta = src.metadata_json or {}
        if isinstance(meta, dict):
            for cit in meta.get("citations") or []:
                c_str = str(cit).strip()
                if c_str.startswith("http"):
                    candidates.append(c_str)
        for u in candidates:
            url_by_channel_sec.setdefault((src.section_code, src.channel.lower()), u)
            sec_list = urls_by_section.setdefault(src.section_code, [])
            if u not in sec_list:
                sec_list.append(u)
            if u not in all_valid_urls:
                all_valid_urls.append(u)

    for post in sns_posts:
        if post.post_url and post.post_url.startswith("http"):
            u = post.post_url.strip()
            sec = SectionCode.OWN.value if post.owner_type == "OWN" else SectionCode.COMPETITOR.value
            url_by_channel_sec.setdefault((sec, post.platform.lower()), u)
            sec_list = urls_by_section.setdefault(sec, [])
            if u not in sec_list:
                sec_list.append(u)

    for s in slides:
        for b in s.bullets_json or []:
            fid = b.get("fact_id")
            if fid and b.get("source_url") and str(b.get("source_url")).startswith("http"):
                fact_url_by_id[str(fid)] = str(b["source_url"]).strip()

    for s in slides:
        if s.slide_type in {"COVER", "INDEX", "SECTION_DIVIDER", "DATA_GAP"}:
            continue
        sec_pool = urls_by_section.get(s.section_code) or all_valid_urls
        new_bullets: list[dict[str, Any]] = []
        for idx, b in enumerate(s.bullets_json or []):
            nb = dict(b)
            existing_url = str(nb.get("source_url") or "").strip()
            if existing_url.startswith("http"):
                new_bullets.append(nb)
                continue
            fid = nb.get("fact_id")
            if fid and str(fid) in fact_url_by_id:
                nb["source_url"] = fact_url_by_id[str(fid)]
                new_bullets.append(nb)
                continue
            src_name = str(nb.get("source_name") or "").lower()
            matched_url: str | None = None
            for (sec, ch), u in url_by_channel_sec.items():
                if sec == s.section_code and (ch in src_name or src_name in ch):
                    matched_url = u
                    break
            if not matched_url and sec_pool:
                matched_url = sec_pool[idx % len(sec_pool)]
            if matched_url:
                nb["source_url"] = matched_url
            new_bullets.append(nb)
        if new_bullets:
            s.bullets_json = new_bullets


def _sns_cards_for_posts(
    posts: list[SnsTopPost], asset_by_id: dict[str, MediaAsset]
) -> list[dict[str, Any]]:
    return [
        {
            "asset_type": "SNS_TOP5_CARD",
            "title": f"TOP {p.rank_order} | {p.brand_label} · {p.platform}",
            "local_path": (
                asset_by_id[p.media_asset_id].local_path
                if p.media_asset_id in asset_by_id
                else None
            ),
            "caption": format_post_metrics_caption(p),
            "annotation_text": smart_truncate(p.caption, 78),
            "metadata": {
                "is_collab": p.is_creator_collab,
                "post_url": p.post_url,
                "platform": p.platform,
                "brand_label": p.brand_label,
                "views": p.views,
                "likes": p.likes,
                "comments": p.comments,
            },
        }
        for p in posts[:5]
    ]


def _sns_bullets_for_posts(
    posts: list[SnsTopPost], empty_claim: str, platform_label: str
) -> list[dict[str, Any]]:
    if not posts:
        return [
            {
                "claim": empty_claim,
                "evidence_quote": "확인 못 함 (공식 계정 URL 또는 기간 내 게시물 부족)",
                "source_name": platform_label,
                "source_url": None,
                "fact_id": None,
            }
        ]
    return [
        {
            "claim": f"[TOP {p.rank_order}] {smart_truncate(p.caption, 90)}",
            "evidence_quote": format_post_metrics_caption(p),
            "source_name": f"{p.brand_label} {p.platform}",
            "source_url": p.post_url,
            "fact_id": None,
        }
        for p in posts[:3]
    ]


def _filter_brand_sources(
    sources: list[RawSourceItem], brand: str, section_code: str | None = None
) -> list[RawSourceItem]:
    key = brand.lower().strip()
    out: list[RawSourceItem] = []
    for s in sources:
        if section_code and s.section_code != section_code:
            continue
        haystack = f"{s.title or ''} {s.content or ''} {s.evidence_quote or ''}".lower()
        if key and key in haystack:
            out.append(s)
    return out


def _filter_brand_facts(facts: list[FactItem], brand: str) -> list[FactItem]:
    key = brand.lower().strip()
    return [
        f
        for f in facts
        if key and key in f"{f.claim_text or ''} {f.evidence_quote or ''}".lower()
    ]


def build_own_section_slides(
    *,
    project: Project,
    sources: list[RawSourceItem],
    facts_by_sec: dict[str, list[FactItem]],
    own_dl: list[DataLabSeries],
    own_sns: list[SnsTopPost],
    collab_sns: list[SnsTopPost],
    profile_sources: list[RawSourceItem],
    asset_by_id: dict[str, MediaAsset],
    start_order: int,
) -> tuple[list[SlideDraft], int]:
    """Build Part 1 (Own Analysis): divider + 8 detailed slides."""
    slides: list[SlideDraft] = []
    order = start_order
    own_facts = facts_by_sec.get(SectionCode.OWN.value, [])
    own_share = own_dl[0].share_of_search_pct if own_dl else 0.0
    own_growth = own_dl[0].growth_rate_pct if own_dl else 0.0
    dl_note = own_dl[0].methodology_note if own_dl else f"출처: 네이버 데이터랩 ({project.period_start}~{project.period_end})"

    press_summary = PressMetricsService.summarize_press(
        sources=sources, brand_names=[project.brand_name]
    )

    slides.append(
        make_section_divider(
            project_id=project.id,
            section_code=SectionCode.OWN.value,
            order=order,
            part_title="PART 1 · 1. 자사 분석 (Own Brand & Channels)",
            subtitle=f"{project.brand_name} '{project.product_name}'의 검색 모멘텀·제품 포트폴리오·SNS 반응·언론 보도 전수 점검",
            slide_topics=[
                "1-1~1-3: 기업·제품 포지셔닝, 신제품 USP 및 가격·할인 구조",
                "1-4~1-6: 공식 채널 규모, 인스타그램·유튜브 TOP 5 콘텐츠",
                "1-7~1-8: 크리에이터 협업 성과 및 최근 언론 보도(News/PR) 추이",
            ],
            kpi_chips=[
                {"label": "검색 점유율(SoS)", "value": f"{own_share:.1f}%", "delta": f"{own_growth:+.1f}%", "basis": "데이터랩"},
                {"label": "자사 SNS TOP", "value": f"{len(own_sns)}건", "delta": f"협업 {len(collab_sns)}건", "basis": "IG/YT 수집"},
                {"label": "언론 보도 기사", "value": f"{press_summary['total_articles']}건", "delta": "News/PR 집계", "basis": "자사 언급 기준"},
            ],
            footnote=f"PART 1 범위: {project.brand_name} {project.product_name} ({project.period_start}~{project.period_end})",
        )
    )
    order += 1

    # 1-1. 자사 실적 & 포지셔닝
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OWN.value,
            slide_order=order,
            slide_type="OWN_PROFILE",
            title="1-1. 자사 분석 — 기업 실적 및 브랜드·제품 포지셔닝",
            headcopy=(
                f"{project.brand_name} '{project.product_name}'의 검색 점유율은 {own_share:.1f}%({own_growth:+.1f}%)이며 "
                "실적·공식 포지셔닝 핵심 동인을 점검함"
            ),
            kpi_cards_json=[
                {"label": "경쟁군 검색 점유율(SoS)", "value": f"{own_share:.1f}%", "delta": f"전기 대비 {own_growth:+.1f}%", "basis": "네이버 데이터랩 합산"},
                {"label": "공식 SNS TOP 콘텐츠", "value": f"{len(own_sns)}건", "delta": f"최고 반응 {int(own_sns[0].engagement_score):,}" if own_sns else "수집 없음", "basis": "기간 내 게시물 기준"},
                {"label": "크리에이터 협업", "value": f"{len(collab_sns)}건", "delta": "유튜브/인스타 탐지", "basis": "협찬·공동작성 태그"},
                {"label": "언론 보도·검증 팩트", "value": f"{len(own_facts)}건", "delta": f"보도 {press_summary['total_articles']}건", "basis": "Perplexity·뉴스 수집"},
            ],
            table_json={
                "headers": ["진단 구분", "확인된 핵심 지표", "출처/근거"],
                "rows": [
                    ["검색 점유율(SoS)", f"{own_share:.1f}% (후반기 {own_growth:+.1f}%)", "네이버 데이터랩"],
                    ["공식 채널 TOP 1", format_post_metrics_caption(own_sns[0]) if own_sns else "확인 못 함", own_sns[0].platform if own_sns else "-"],
                    ["주력 제품 포지션", f"{project.brand_name} {project.product_name}", "리서치 원문 구조화"],
                ],
            },
            bullets_json=facts_to_bullets(own_facts, fallback_claim=f"{project.brand_name} 실적 및 브랜드 포지셔닝 요약"),
            footnote=f"출처: Perplexity 리서치 및 {dl_note.removeprefix('출처: ').strip()}",
        )
    )
    order += 1

    # 1-2. 신제품 출시 동향 & USP
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OWN.value,
            slide_order=order,
            slide_type="OWN_NEW_PRODUCTS",
            title="1-2. 자사 분석 — 신제품 출시 동향 및 주력 라인업 USP",
            headcopy=f"{project.brand_name} 최근 신제품 출시 방향성과 '{project.product_name}' 핵심 기능·소재 차별점 점검",
            table_json={
                "headers": ["라인업/신제품", "핵심 스펙·소재 USP", "타겟 용도", "출처"],
                "rows": [
                    [f"{project.product_name} (주력)", "수집 원문 기반 핵심 기능 정리", "핵심 고객층", "공식몰·리서치"],
                    ["신규 확장 라인업", "리서치 확인 신제품 스펙 반영", "세분화 수요", "보도자료·웹"],
                ],
            },
            bullets_json=facts_to_bullets(
                own_facts[1:] or own_facts,
                fallback_claim=f"{project.brand_name} 신규 출시 라인업 및 기술·디자인 USP 분석",
            ),
            footnote="출처: Perplexity 브랜드 신제품 리서치 및 공식 홈페이지 공개 스펙",
        )
    )
    order += 1

    # 1-3. 가격·할인율 & 프로모션 구조
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OWN.value,
            slide_order=order,
            slide_type="OWN_PRODUCTS_PRICE",
            title="1-3. 자사 분석 — 주요 라인업 가격대·할인율 및 프로모션 구조",
            headcopy=f"{project.brand_name} '{project.product_name}' 라인업별 공식 정가 대비 온라인 실판매가·할인 폭 구조 분석",
            table_json={
                "headers": ["라인업/규격", "소재·특징", "공식가 / 실판매가(할인)", "판매 채널"],
                "rows": [
                    [f"{project.product_name} 대표 규격", "공식 판매 상품 스펙 기준", "확인 못 함", "공식몰·이커머스"],
                ],
            },
            visual_assets_json=[
                {
                    "asset_type": "PRICE_DISCOUNT_BAR",
                    "title": f"{project.brand_name} 주요 라인업 정가 vs 할인가 비교 (만원)",
                    "caption": "수집 원문 및 공식 판매처 기준 가격 분포",
                    "metadata": {"unit": "만원", "items": []},
                }
            ],
            bullets_json=facts_to_bullets(
                own_facts,
                fallback_claim=f"{project.brand_name} 정가·행사가 차이 및 유통 채널별 가격 정책 분석",
            ),
            footnote="출처: Perplexity 제품 가격 리서치 및 공식몰·주요 오픈마켓 판매 정보",
        )
    )
    order += 1

    # 1-4. Owned SNS 채널 현황
    account_rows: list[list[str]] = []
    for psrc in profile_sources:
        meta = psrc.metadata_json or {}
        account_rows.append(
            [
                str(meta.get("platform") or psrc.channel),
                f"@{psrc.author or '-'}",
                f"{int(meta.get('followers', 0)):,}명",
                f"TOP {int(meta.get('top_period_posts', 0))}건",
                f"{'자사' if meta.get('owner_type') == 'OWN' else '경쟁사'} ({meta.get('brand_label', '')})",
            ]
        )
    if not account_rows:
        account_rows.append(["공식 SNS", "계정 URL 미등록 또는 미수집", "확인 못 함", "0건", "수집 설정 확인 필요"])

    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OWN.value,
            slide_order=order,
            slide_type="OWN_CHANNELS",
            title="1-4. 자사 분석 — Owned SNS 채널 현황 및 운영 규모",
            headcopy=f"등록된 공식 SNS 채널({len(account_rows)}개) 팔로워·구독자 모수 및 기간 내 유효 반응 밀도 비교",
            table_json={
                "headers": ["플랫폼", "계정 핸들", "팔로워/구독자", "기간 내 TOP", "소유 구분"],
                "rows": account_rows[:6],
            },
            bullets_json=[
                {
                    "claim": smart_truncate(psrc.content, 130),
                    "evidence_quote": psrc.evidence_quote,
                    "source_name": f"{psrc.channel}",
                    "source_url": psrc.source_url,
                    "fact_id": None,
                }
                for psrc in profile_sources[:3]
            ]
            or facts_to_bullets(own_facts, fallback_claim="등록 SNS 채널 URL 기준 공식 계정 규모 점검"),
            footnote="출처: ScrapeCreators 공식 SNS 프로필·게시물 수집 결과",
        )
    )
    order += 1

    # 1-5. 공식 인스타그램 TOP 5
    ig_posts = [p for p in own_sns if p.platform.upper() == "INSTAGRAM"]
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OWN.value,
            slide_order=order,
            slide_type="OWN_INSTAGRAM_TOP5",
            title="1-5. 자사 분석 — 공식 인스타그램 기간 내 인기 게시물 TOP 5",
            headcopy=f"조사 기간({project.period_start}~{project.period_end}) 내 자사 인스타그램 고반응 콘텐츠 TOP 5 성과 및 소구점",
            kpi_cards_json=[
                {
                    "label": f"IG TOP {p.rank_order}",
                    "value": f"좋아요 {p.likes:,}",
                    "delta": f"댓글 {p.comments:,}" + (f" · 조회 {p.views:,}" if p.views > 0 else ""),
                    "basis": p.published_at.strftime("%Y-%m-%d"),
                }
                for p in ig_posts[:4]
            ]
            or [{"label": "Instagram TOP 5", "value": "수집 0건", "delta": "계정/기간 확인", "basis": "INSTAGRAM"}],
            bullets_json=_sns_bullets_for_posts(
                ig_posts,
                empty_claim="기간 내 자사 인스타그램 게시물이 없거나 인스타그램 계정 URL이 등록되지 않았습니다.",
                platform_label="INSTAGRAM",
            ),
            visual_assets_json=_sns_cards_for_posts(ig_posts, asset_by_id),
            footnote="기준: 설정 기간 내 자사 Instagram 게시물 반응 지수 정렬 TOP 5 (ScrapeCreators)",
        )
    )
    order += 1

    # 1-6. 공식 유튜브 TOP 5
    yt_posts = [p for p in own_sns if p.platform.upper() == "YOUTUBE"]
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OWN.value,
            slide_order=order,
            slide_type="OWN_YOUTUBE_TOP5",
            title="1-6. 자사 분석 — 공식 유튜브 기간 내 인기 영상 TOP 5",
            headcopy=f"조사 기간({project.period_start}~{project.period_end}) 내 자사 유튜브 조회수·인게이지먼트 상위 영상 포맷 분석",
            kpi_cards_json=[
                {
                    "label": f"YT TOP {p.rank_order}",
                    "value": f"조회 {p.views:,}" if p.views > 0 else f"좋아요 {p.likes:,}",
                    "delta": f"좋아요 {p.likes:,} / 댓글 {p.comments:,}",
                    "basis": p.published_at.strftime("%Y-%m-%d"),
                }
                for p in yt_posts[:4]
            ]
            or [{"label": "YouTube TOP 5", "value": "수집 0건", "delta": "계정/기간 확인", "basis": "YOUTUBE"}],
            bullets_json=_sns_bullets_for_posts(
                yt_posts,
                empty_claim="기간 내 자사 유튜브 영상이 없거나 유튜브 채널 URL이 등록되지 않았습니다.",
                platform_label="YOUTUBE",
            ),
            visual_assets_json=_sns_cards_for_posts(yt_posts, asset_by_id),
            footnote="기준: 설정 기간 내 자사 YouTube 영상 조회·반응 정렬 TOP 5 (ScrapeCreators)",
        )
    )
    order += 1

    # 1-7. 크리에이터 협업 & 캠페인
    collab_rows = [
        [
            p.published_at.strftime("%Y-%m-%d"),
            smart_truncate(p.caption, 36) or "-",
            p.platform,
            f"조회 {p.views:,}" if p.views > 0 else "-",
            f"좋아요 {p.likes:,} / 댓글 {p.comments:,}",
        ]
        for p in collab_sns[:6]
    ] or [["기간 내 수집", "크리에이터 협업 탐지 건 부족", "-", "확인 못 함", "-"]]

    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OWN.value,
            slide_order=order,
            slide_type="OWN_CREATOR_COLLABS",
            title="1-7. 자사 분석 — 크리에이터 협업·시딩 및 대표 캠페인 성과",
            headcopy=f"{project.brand_name} '{project.product_name}' 관련 크리에이터 시딩·협찬 성과 및 주요 브랜딩 캠페인 흐름",
            table_json={
                "headers": ["게시일", "협업/캠페인 콘텐츠", "채널", "조회수", "반응 지표"],
                "rows": collab_rows,
            },
            bullets_json=facts_to_bullets(own_facts, fallback_claim="크리에이터 협업·팝업·대표 캠페인 성과 요약"),
            footnote="출처: ScrapeCreators 협업 탐색 및 Perplexity 브랜드 캠페인 리서치",
        )
    )
    order += 1

    # 1-8. 자사 언론 보도(News/PR) 추이
    press_rows = [
        [r[0], r[1], r[2], r[3], r[4]] for r in press_summary["sample_rows"][:6]
    ] or [["수집 기간", project.brand_name, "일반", "확인된 자사 언론 보도 건 없음", "-"]]
    monthly_items = press_summary["monthly_items"]
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OWN.value,
            slide_order=order,
            slide_type="OWN_PRESS_ANALYSIS",
            title="1-8. 자사 분석 — 언론 보도(News/PR) 월별 추이 및 핵심 보도 논조",
            headcopy=(
                f"{project.brand_name} 관련 국내 언론 보도 {press_summary['total_articles']}건 기준 "
                "시기별 PR 스파이크와 주요 커뮤니케이션 주제 분석"
            ),
            kpi_cards_json=[
                {"label": "누적 수집 보도", "value": f"{press_summary['total_articles']}건", "delta": f"{len(monthly_items)}개월 분포", "basis": "국내 언론 News/PR"},
                *[
                    {"label": f"주제: {t['label']}", "value": f"{t['value']}건", "delta": "기사 키워드 분류", "basis": "PressMetrics"}
                    for t in press_summary["topic_items"][:3]
                ],
            ],
            table_json={
                "headers": ["보도일", "브랜드", "주제 분류", "기사 제목", "출처 URL"],
                "rows": press_rows,
            },
            visual_assets_json=(
                [
                    {
                        "asset_type": "PRESS_MONTHLY_BAR",
                        "title": f"{project.brand_name} 월별 언론 보도량 추이 (건)",
                        "caption": f"수집된 {press_summary['total_articles']}건 기준 월별 기사 건수",
                        "metadata": {"unit": "건", "items": monthly_items},
                    }
                ]
                if monthly_items
                else []
            ),
            bullets_json=facts_to_bullets(own_facts, fallback_claim="언론 보도 집중 시기와 핵심 브랜드 PR 메시지 요약"),
            footnote="출처: Apify 국내 뉴스 검색 수집 결과 및 PressMetricsService 정량 집계",
        )
    )
    order += 1
    return slides, order


def build_market_section_slides(
    *,
    project: Project,
    facts_by_sec: dict[str, list[FactItem]],
    search_dl: list[DataLabSeries],
    dl_note: str,
    start_order: int,
) -> tuple[list[SlideDraft], int]:
    """Build Part 2 (Market Analysis): divider + 4 detailed slides."""
    slides: list[SlideDraft] = []
    order = start_order
    market_facts = facts_by_sec.get(SectionCode.MARKET.value, [])
    track_name = "리뷰 중심" if project.analysis_track == "REVIEW_CENTRIC" else "시장 지표 중심"

    slides.append(
        make_section_divider(
            project_id=project.id,
            section_code=SectionCode.MARKET.value,
            order=order,
            part_title="PART 2 · 2. 시장 분석 (Market Size, Demand & Players)",
            subtitle=f"{project.industry_category} 내 {project.product_name} 시장의 외형 규모·검색 수요 추이·유통 변화·플레이어 구도 정리",
            slide_topics=[
                "2-1~2-2: 글로벌·국내 시장 규모 및 시즌별 검색 수요 변동 흐름",
                "2-3~2-4: 유통 채널 전환 신호·규제 체크 및 국내 플레이어 포지션",
            ],
            kpi_chips=[
                {"label": "분석 트랙", "value": track_name, "delta": project.industry_category[:18], "basis": "조사 프레임"},
                {"label": "시장 확보 팩트", "value": f"{len(market_facts)}건", "delta": "Perplexity+통계", "basis": "검증 원천"},
                {"label": "비교 검색 시리즈", "value": f"{len(search_dl)}종", "delta": "주간 시계열", "basis": "네이버 데이터랩"},
            ],
            footnote=f"PART 2 범위: {project.industry_category} 거시 환경 및 카테고리 신호",
        )
    )
    order += 1

    # 2-1. 시장 규모 & 성장률
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.MARKET.value,
            slide_order=order,
            slide_type="MARKET_OVERVIEW",
            title="2-1. 시장 분석 — 글로벌·국내 시장 규모 및 거시 성장 지표",
            headcopy=f"{project.industry_category}({project.product_name}) 시장의 외형 성장과 실수요 간 괴리 및 핵심 성장 동인 진단",
            kpi_cards_json=[
                {"label": "분석 트랙", "value": track_name, "delta": project.industry_category, "basis": "산업군 특성 분기"},
                {"label": "시장 확보 자료", "value": f"{len(market_facts)}건", "delta": "출처 URL 연결", "basis": "Perplexity 거시 리서치"},
            ],
            table_json={
                "headers": ["시장 지표/기관", "규모/수치", "비고/기준연도"],
                "rows": [["글로벌·국내 시장 규모", "확인 못 함 (원문 수치 구조화)", "확인 못 함"]],
            },
            visual_assets_json=[
                {
                    "asset_type": "HORIZONTAL_BAR_CHART",
                    "title": f"{project.industry_category} 주요 시장 규모 지표",
                    "caption": "리서치 출처별 확인 수치",
                    "metadata": {"unit": "", "items": []},
                }
            ],
            bullets_json=facts_to_bullets(market_facts, fallback_claim=f"{project.industry_category} 시장 규모 및 성장률"),
            footnote="출처: Perplexity 거시 리서치 인용 보고서 및 통계 자료",
        )
    )
    order += 1

    # 2-2. 시즌별 검색 관심도 및 거시 수요 흐름
    dl_summary_rows = [
        [
            d.group_label,
            "자사" if d.owner_type == "OWN" else "경쟁",
            f"{d.growth_rate_pct:+.1f}%",
            f"{d.peak_date or '-'} ({d.peak_value:.0f})",
        ]
        for d in search_dl[:5]
    ] or [[f"{project.brand_name} {project.product_name}", "자사", "-", "-"]]

    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.MARKET.value,
            slide_order=order,
            slide_type="MARKET_DEMAND_TREND",
            title="2-2. 시장 분석 — 시즌별 검색 관심도 및 카테고리 수요 변곡점",
            headcopy=f"조사 기간({project.period_start}~{project.period_end}) 카테고리 검색 지수 파동과 성수기·이슈성 수요 피크 분석",
            table_json={
                "headers": ["검색 키워드 그룹", "구분", "전후반기 증감", "피크 시점(지수)"],
                "rows": dl_summary_rows,
            },
            visual_assets_json=[
                {
                    "asset_type": "DATALAB_TREND_CHART",
                    "title": f"{project.product_name} 카테고리 주간 검색 관심도 흐름",
                    "caption": dl_note,
                }
            ],
            bullets_json=facts_to_bullets(market_facts, fallback_claim="검색 시계열 상 피크 구간과 시즌성 수요 드라이버 해석"),
            footnote=dl_note,
        )
    )
    order += 1

    # 2-3. 유통 신호 & 규제
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.MARKET.value,
            slide_order=order,
            slide_type="MARKET_SIGNALS",
            title="2-3. 시장 분석 — 카테고리 신호·유통 변화 및 규제 환경",
            headcopy=f"{project.product_name} 카테고리 내 객단가·온라인 전환 신호 및 표시·광고/품질 규제 체크포인트",
            table_json={
                "headers": ["카테고리 신호/이슈", "구체적 시장 변화 및 수치", "시사점"],
                "rows": [["유통·가격 신호", "확인 못 함 (원문 구조화 필요)", "확인 못 함"]],
            },
            bullets_json=facts_to_bullets(market_facts[1:] or market_facts, fallback_claim="유통 채널 변화 및 규제 이슈 요약"),
            footnote="출처: Perplexity 산업 동향 및 규제 리서치",
        )
    )
    order += 1

    # 2-4. 국내 플레이어 지형
    player_rows = [
        ["자사 (주력)", project.brand_name, f"{project.product_name} 중심", "확인 못 함", "공식몰·유통"],
    ] + [
        ["경쟁군", c.brand_name, c.product_name, "확인 못 함", "자사몰·온라인"]
        for c in project.competitors
    ]
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.MARKET.value,
            slide_order=order,
            slide_type="MARKET_PLAYERS",
            title="2-4. 시장 분석 — 국내 플레이어 지형 및 포지션 구분",
            headcopy=f"국내 {project.product_name} 시장 내 {project.brand_name}와 주요 경쟁 플레이어 간 유통·가격대 포지션 구조화",
            table_json={
                "headers": ["구분", "브랜드", "핵심 포지션 근거", "주요 가격대", "주력 채널"],
                "rows": player_rows[:6],
            },
            bullets_json=facts_to_bullets(market_facts, fallback_claim="국내 주요 플레이어 유형별 경쟁 구도 요약"),
            footnote="출처: Perplexity 산업 플레이어 리서치 및 공식 유통 채널 자료",
        )
    )
    order += 1
    return slides, order


def build_competitor_section_slides(
    *,
    project: Project,
    sources: list[RawSourceItem],
    facts: list[FactItem],
    facts_by_sec: dict[str, list[FactItem]],
    search_dl: list[DataLabSeries],
    sns_posts: list[SnsTopPost],
    comp_sns: list[SnsTopPost],
    asset_by_id: dict[str, MediaAsset],
    dl_note: str,
    start_order: int,
) -> tuple[list[SlideDraft], int]:
    """Build Part 3 (Competitor Analysis): divider + matrix + price + 1:1 details + SNS + Press + 6-axis heatmap + tactics."""
    slides: list[SlideDraft] = []
    order = start_order
    comp_facts = facts_by_sec.get(SectionCode.COMPETITOR.value, [])
    brands = [project.brand_name, *[c.brand_name for c in project.competitors[:3]]]
    press_summary = PressMetricsService.summarize_press(sources=sources, brand_names=brands)

    slides.append(
        make_section_divider(
            project_id=project.id,
            section_code=SectionCode.COMPETITOR.value,
            order=order,
            part_title="PART 3 · 3. 경쟁사 분석 (1:1 Deep Dive & 6-Axis Activity)",
            subtitle=f"{len(project.competitors)}개 직접 경쟁 제품 대상 검색 점유율(SoS)·1:1 심층 해부·SNS·보도량·마케팅 6분류 강도 대조",
            slide_topics=[
                "3-1~3-2: 경쟁 세트 SoS·쇼핑 관심도 및 동일 규격 가격 포지션",
                f"3-3: 경쟁사별({len(project.competitors[:4])}개) 1:1 제품·메시지·강약점 심층 분석",
                "3-4~3-7: 경쟁 SNS TOP 5, 언론 보도량 비교 및 마케팅 6분류 히트맵",
            ],
            kpi_chips=[
                {"label": "직접 경쟁 제품", "value": f"{len(project.competitors)}종", "delta": "1:1 동일 카테고리", "basis": "경쟁 세트"},
                {"label": "경쟁 SNS TOP", "value": f"{len(comp_sns)}건", "delta": "공식 채널 추출", "basis": "ScrapeCreators"},
                {"label": "언론 보도 비교", "value": f"{press_summary['total_articles']}건", "delta": f"{len(brands)}개 브랜드 합산", "basis": "PressMetrics"},
            ],
            footnote=f"PART 3 범위: {project.brand_name} vs {', '.join(c.brand_name for c in project.competitors) or '경쟁군'}",
        )
    )
    order += 1

    # 3-1. 경쟁 매트릭스 & SoS
    dl_rows = [
        [
            g.group_label,
            "자사" if g.owner_type == "OWN" else "경쟁사",
            f"{g.share_of_search_pct:.1f}%",
            f"{g.growth_rate_pct:+.1f}%",
            f"{g.peak_date or '-'} ({g.peak_value:.0f})",
        ]
        for g in search_dl
    ] or [[f"{project.brand_name} {project.product_name}", "자사", "-", "-", "-"]]

    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.COMPETITOR.value,
            slide_order=order,
            slide_type="COMPETITOR_MATRIX",
            title="3-1. 경쟁사 분석 — 경쟁 세트 비교 매트릭스 및 검색 점유율(SoS)",
            headcopy=f"네이버 데이터랩 기준 {project.brand_name} vs {len(project.competitors)}개 경쟁 브랜드 검색 점유율과 포지셔닝 비교",
            kpi_cards_json=[
                {
                    "label": s.group_label[:18],
                    "value": f"{s.share_of_search_pct:.1f}%",
                    "delta": f"증감 {s.growth_rate_pct:+.1f}%",
                    "basis": "검색 점유율(SoS)",
                }
                for s in search_dl[:4]
            ],
            table_json={
                "headers": ["브랜드/제품", "구분", "검색 점유율(SoS)", "전기 대비", "피크(지수)"],
                "rows": dl_rows[:6],
            },
            visual_assets_json=[
                {
                    "asset_type": "DATALAB_SOS_BAR",
                    "title": "경쟁군 검색(SoS) vs 쇼핑 관심 점유율 비교 (%)",
                    "caption": dl_note,
                }
            ],
            bullets_json=facts_to_bullets(comp_facts, fallback_claim="경쟁 브랜드별 핵심 포지셔닝 및 SoS 격차 진단"),
            footnote=dl_note,
        )
    )
    order += 1

    # 3-2. 검색 관심도 추이 & 가격 포지션
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.COMPETITOR.value,
            slide_order=order,
            slide_type="COMPETITOR_PRICE_TREND",
            title="3-2. 경쟁사 분석 — 주간 검색 관심도 추이 및 가격 포지션",
            headcopy=f"조사 기간({project.period_start}~{project.period_end}) 주간 검색 지수 흐름과 동일 규격 기준 가격대 격차 분석",
            visual_assets_json=[
                {
                    "asset_type": "DATALAB_TREND_CHART",
                    "title": "자사·경쟁사 주간 검색 관심도 추이",
                    "caption": dl_note,
                }
            ],
            table_json={
                "headers": ["브랜드/대표 모델", "가격/구분", "포지셔닝 특징"],
                "rows": [
                    [f"{project.brand_name} {project.product_name}", "자사", "공식가/행사가 비교 기준"],
                    *[
                        [f"{c.brand_name} {c.product_name}", "경쟁사", "직접 비교군"]
                        for c in project.competitors[:4]
                    ],
                ],
            },
            bullets_json=facts_to_bullets(comp_facts, fallback_claim="가격 포지션 및 검색 시즌성 변곡점 분석"),
            footnote=f"{dl_note} 및 경쟁사 공개 상품 가격",
        )
    )
    order += 1

    # 3-3. 경쟁사 1:1 개별 심층 분석 (up to 4 competitors; at least 1 placeholder slot if 0 competitors configured)
    brand_counts = {b["label"]: int(b.get("value", 0)) for b in press_summary["brand_items"]}
    comp_targets: list[CompetitorTarget] = list(project.competitors[:4])
    for c_idx, comp in enumerate(comp_targets, start=1):
        c_facts = _filter_brand_facts(facts, comp.brand_name) or comp_facts
        c_dl = next((d for d in search_dl if comp.brand_name.lower() in d.group_label.lower()), None)
        c_posts = [p for p in sns_posts if comp.brand_name.lower() in p.brand_label.lower()][:2]
        c_press = brand_counts.get(comp.brand_name, 0)
        slides.append(
            SlideDraft(
                project_id=project.id,
                section_code=SectionCode.COMPETITOR.value,
                slide_order=order,
                slide_type="COMPETITOR_DETAIL",
                title=f"3-3-{c_idx}. 경쟁사 1:1 심층 — {comp.brand_name} '{comp.product_name}'",
                headcopy=(
                    f"{comp.brand_name} '{comp.product_name}'의 검색 점유({c_dl.share_of_search_pct:.1f}% · {c_dl.growth_rate_pct:+.1f}%)"
                    if c_dl
                    else f"{comp.brand_name} '{comp.product_name}'의 제품 차별점·가격·SNS/PR 활동 전수 진단"
                ),
                kpi_cards_json=[
                    {"label": "검색 점유율(SoS)", "value": f"{c_dl.share_of_search_pct:.1f}%" if c_dl else "확인 못 함", "delta": f"{c_dl.growth_rate_pct:+.1f}%" if c_dl else "-", "basis": "데이터랩"},
                    {"label": "언론 보도 기사", "value": f"{c_press}건", "delta": "News/PR", "basis": comp.brand_name},
                    {"label": "SNS TOP 게시물", "value": f"{len(c_posts)}건", "delta": f"좋아요 {c_posts[0].likes:,}" if c_posts else "수집 없음", "basis": c_posts[0].platform if c_posts else "SNS"},
                ],
                table_json={
                    "headers": ["비교 항목", f"{comp.brand_name} 현황", f"자사({project.brand_name}) 대비 시사점"],
                    "rows": [
                        ["주력 모델·스펙", comp.product_name, f"{project.product_name}과 직접 소구점 대조"],
                        ["핵심 소구 메시지", "수집 원문 기반 USP 추출", "자사 메시지 차별화 여지 점검"],
                        ["유통·프로모션", "주요 온라인/공식몰 운영", "할인·번들 구성 경쟁력 점검"],
                    ],
                },
                bullets_json=facts_to_bullets(c_facts, fallback_claim=f"{comp.brand_name} {comp.product_name}의 핵심 강점·약점 및 마케팅 전술 요약"),
                footnote=f"출처: Perplexity {comp.brand_name} 1:1 딥리서치·데이터랩·SNS·뉴스 수집 결과",
            )
        )
        order += 1

    # 3-4. 경쟁사 공식 SNS TOP 5
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.COMPETITOR.value,
            slide_order=order,
            slide_type="COMPETITOR_SNS_TOP5",
            title="3-4. 경쟁사 분석 — 경쟁사 공식 SNS 인기 게시물 TOP 5",
            headcopy="경쟁사 공식 채널 고성과 콘텐츠 포맷과 크리에이터 협업 반응 패턴 비교",
            kpi_cards_json=[
                {
                    "label": f"{p.brand_label} TOP {p.rank_order}",
                    "value": f"조회 {p.views:,}" if p.views > 0 else f"좋아요 {p.likes:,}",
                    "delta": f"좋아요 {p.likes:,} / 댓글 {p.comments:,}",
                    "basis": p.platform,
                }
                for p in comp_sns[:4]
            ],
            bullets_json=_sns_bullets_for_posts(
                comp_sns,
                empty_claim="등록된 경쟁사 SNS 계정이 없거나 기간 내 게시물이 확인되지 않았습니다.",
                platform_label="ScrapeCreators",
            ),
            visual_assets_json=_sns_cards_for_posts(comp_sns, asset_by_id),
            footnote="출처: ScrapeCreators 경쟁사 공식 SNS 기간 내 인기 게시물 TOP 5",
        )
    )
    order += 1

    # 3-5. 자사 vs 경쟁사 언론 보도량 비교
    brand_bar_items = [b for b in press_summary["brand_items"] if int(b.get("value", 0)) > 0]
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.COMPETITOR.value,
            slide_order=order,
            slide_type="COMPETITOR_PRESS",
            title="3-5. 경쟁사 분석 — 자사·경쟁사 언론 보도(News/PR) 비교",
            headcopy=f"국내 뉴스 수집 결과 기준 {project.brand_name} vs 경쟁 브랜드 보도 비중과 핵심 PR 이슈 대조",
            table_json={
                "headers": ["보도일", "브랜드", "주제 분류", "주요 보도 헤드라인", "출처 URL"],
                "rows": [
                    [r[0], r[1], r[2], r[3], r[4]] for r in press_summary["sample_rows"][:6]
                ]
                or [["-", "수집 뉴스 없음", "-", "추가 뉴스 검색 필요", "-"]],
            },
            visual_assets_json=(
                [
                    {
                        "asset_type": "PRESS_BRAND_BAR",
                        "title": "브랜드별 언론 보도 기사 건수 비교 (건)",
                        "caption": f"총 {press_summary['total_articles']}건 보도 원문 브랜드 매칭 결과",
                        "metadata": {"unit": "건", "items": press_summary["brand_items"]},
                    }
                ]
                if brand_bar_items
                else []
            ),
            bullets_json=facts_to_bullets(comp_facts, fallback_claim="브랜드별 홍보(PR) 주력 주제 및 언론 노출 격차 분석"),
            footnote="출처: Apify 국내 뉴스 수집 및 브랜드별 보도 정량 집계",
        )
    )
    order += 1

    # 3-6. 마케팅 활동 6분류 히트맵
    axes = [
        ("디지털 캠페인", ["캠페인", "광고", "영상", "브랜드필름", "tv"]),
        ("온라인 이벤트", ["이벤트", "프로모션", "할인", "기획전", "증정"]),
        ("소셜 콘텐츠", ["인스타", "유튜브", "릴스", "쇼츠", "sns"]),
        ("인플루언서 협업", ["협업", "협찬", "크리에이터", "인플루언서", "유튜버"]),
        ("바이럴·커뮤니티", ["후기", "커뮤니티", "블로그", "카페", "입소문"]),
        ("미디어·PR", ["보도", "뉴스", "팝업", "기사", "런칭"]),
    ]
    heatmap_rows: list[dict[str, Any]] = []
    for axis_name, kws in axes:
        scores: list[dict[str, Any]] = []
        for b in brands:
            b_srcs = _filter_brand_sources(sources, b)
            hits = sum(
                1
                for s in b_srcs
                if any(kw in f"{s.title or ''} {s.content or ''}".lower() for kw in kws)
            )
            score = min(5, max(1, 1 + hits)) if b_srcs else 1
            scores.append({"brand": b, "score": score})
        heatmap_rows.append({"axis": axis_name, "scores": scores})

    comp_cols = [project.brand_name] + [c.brand_name for c in project.competitors[:3]]
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.COMPETITOR.value,
            slide_order=order,
            slide_type="COMPETITOR_MARKETING_6",
            title="3-6. 경쟁사 분석 — 브랜드별 마케팅 활동 6분류 강도 히트맵",
            headcopy="디지털 캠페인·이벤트·SNS·인플루언서·바이럴·PR 6개 축 기준 브랜드별 활동 집중도 비교",
            table_json={
                "headers": ["활동 분류", *comp_cols],
                "rows": [
                    [axis_name] + ["수집 원문 기반 정리" for _ in comp_cols]
                    for axis_name, _ in axes
                ],
            },
            visual_assets_json=[
                {
                    "asset_type": "MARKETING_HEATMAP",
                    "title": "마케팅 활동 6분류 × 브랜드 실행 강도 (1~5점)",
                    "caption": "수집된 리서치·SNS·커뮤니티·뉴스 근거 빈도 및 합성 평가 기준",
                    "metadata": {"brands": comp_cols, "rows": heatmap_rows},
                }
            ],
            bullets_json=facts_to_bullets(comp_facts, fallback_claim="6분류 활동 축별 자사 공백 및 경쟁사 강점 영역"),
            footnote="출처: Perplexity 마케팅 활동 리서치 및 SNS·커뮤니티·뉴스 수집 데이터",
        )
    )
    order += 1

    # 3-7. 6분류 대표 실행 상세
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.COMPETITOR.value,
            slide_order=order,
            slide_type="COMPETITOR_MARKETING_DETAIL",
            title="3-7. 경쟁사 분석 — 마케팅 6분류별 대표 전술 및 크리에이티브 실행",
            headcopy="경쟁사별 고효율 캠페인·인플루언서 시딩·이벤트 전술의 구체적 실행 방식 및 벤치마크 포인트",
            table_json={
                "headers": ["마케팅 축", "경쟁사 대표 실행 사례", "자사 전략 시사점"],
                "rows": [
                    ["디지털 캠페인·영상", "주요 시즌 브랜드 캠페인 사례", "핵심 메시지 선명도 강화"],
                    ["인플루언서·소셜 포맷", "사용 장면 중심 릴스·유튜브 협업", "타겟 접점 크리에이터 확장"],
                    ["이벤트·커뮤니티 바이럴", "기획전·실후기 확산 장치", "구매 전환 트리거 설계"],
                ],
            },
            bullets_json=facts_to_bullets(comp_facts[1:] or comp_facts, fallback_claim="경쟁사 주요 마케팅 실행 사례별 성과 포인트 분석"),
            footnote="출처: Perplexity 마케팅 전술 리서치 및 SNS·언론 수집 원문",
        )
    )
    order += 1
    return slides, order


def build_consumer_section_slides(
    *,
    project: Project,
    sources: list[RawSourceItem],
    facts_by_sec: dict[str, list[FactItem]],
    start_order: int,
) -> tuple[list[SlideDraft], int]:
    """Build Part 4 (Consumer & Trends & Cross-Industry Benchmarks): divider + 7 detailed slides."""
    slides: list[SlideDraft] = []
    order = start_order
    consumer_facts = facts_by_sec.get(SectionCode.CONSUMER.value, [])
    consumer_sources = [s for s in sources if s.section_code == SectionCode.CONSUMER.value]
    pos_cnt = sum(1 for s in consumer_sources if s.sentiment == "POSITIVE")
    neg_strict = sum(1 for s in consumer_sources if s.sentiment == "NEGATIVE")
    mixed_cnt = sum(1 for s in consumer_sources if s.sentiment == "MIXED")
    neg_cnt = neg_strict + mixed_cnt
    neu_cnt = max(0, len(consumer_sources) - pos_cnt - neg_cnt)
    channel_counts = Counter(s.channel for s in consumer_sources)

    slides.append(
        make_section_divider(
            project_id=project.id,
            section_code=SectionCode.CONSUMER.value,
            order=order,
            part_title="PART 4 · 4. 소비자 분석 및 트렌드 (VOC & Benchmarks)",
            subtitle=f"실수집 VOC {len(consumer_sources)}건 기반 구매 요인(KBF)·브랜드별 인식·소셜 트렌드 및 유사 산업 벤치마크",
            slide_topics=[
                "4-1~4-3: 타깃 페르소나, VOC 감성·채널 비중 및 실발화 원문 대조",
                "4-4~4-5: 자사·경쟁 인식 비교 및 소셜·콘텐츠 소비 트렌드",
                "4-6~4-7: 타 업종 선도 사례 벤치마크 및 자사 실행 이식 방향",
            ],
            kpi_chips=[
                {"label": "분석 VOC 원문", "value": f"{len(consumer_sources)}건", "delta": f"긍정 {pos_cnt} / 우려 {neg_cnt}", "basis": "블로그·카페·커뮤니티"},
                {"label": "긍정 발화 비중", "value": f"{(pos_cnt / max(1, len(consumer_sources))) * 100:.1f}%", "delta": f"{len(channel_counts)}개 채널", "basis": "문맥 감성 분류"},
                {"label": "소비자 검증 팩트", "value": f"{len(consumer_facts)}건", "delta": "벤치마크 포함", "basis": "Perplexity+VOC"},
            ],
            footnote=f"PART 4 범위: {project.brand_name} 타겟 소비자 실사용 VOC 및 트렌드 벤치마크",
        )
    )
    order += 1

    # 4-1. 핵심 타깃 & 사용 장면 페르소나
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.CONSUMER.value,
            slide_order=order,
            slide_type="CONSUMER_TARGET",
            title="4-1. 소비자 분석 — 핵심 타깃 세그먼트 및 구매 장면(페르소나)",
            headcopy=f"{project.product_name} 구매 타깃의 이용 상황별 핵심 니즈(KBF) 및 진입 장벽 구조화",
            table_json={
                "headers": ["세그먼트/장면", "주요 이용 맥락", "핵심 구매 기준(KBF)", "불만/이탈 요인"],
                "rows": [
                    ["핵심 실용 타깃", "리서치·VOC 기반 상황 정의", "내구·기능·규격", "가격·사후관리"],
                    ["비교 탐색 타깃", "브랜드 vs 경쟁군 비교", "가성비·후기 신뢰", "정보 부족"],
                ],
            },
            bullets_json=facts_to_bullets(consumer_facts, fallback_claim="타깃 세그먼트별 사용 맥락 및 구매 기준 차이"),
            footnote="출처: Perplexity 소비자 타깃 리서치 및 수집 커뮤니티 VOC 종합",
        )
    )
    order += 1

    # 4-2. VOC 감성 & 출처 분포
    ch_rows = [
        [ch, f"{cnt}건", f"{(cnt / max(1, len(consumer_sources))) * 100:.1f}%"]
        for ch, cnt in channel_counts.most_common(6)
    ] or [["수집 원문", "0건", "0%"]]

    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.CONSUMER.value,
            slide_order=order,
            slide_type="CONSUMER_VOC",
            title="4-2. 소비자 분석 — 커뮤니티·블로그·카페 VOC 감성 및 출처 분포",
            headcopy=f"실수집 VOC {len(consumer_sources)}건 기준 긍정({pos_cnt}건)·아쉬움/고민({neg_cnt}건)·중립({neu_cnt}건) 분포와 채널 비중",
            kpi_cards_json=[
                {"label": "분석 VOC 표본", "value": f"{len(consumer_sources)}건", "delta": f"긍정 {pos_cnt} / 우려·복합 {neg_cnt}", "basis": "Apify 커뮤니티·블로그·카페"},
                {"label": "긍정 vs 우려 비율", "value": f"{(pos_cnt / max(1, len(consumer_sources))) * 100:.1f}%", "delta": f"우려·복합 {(neg_cnt / max(1, len(consumer_sources))) * 100:.1f}%", "basis": "문맥 감성 분류"},
            ],
            table_json={"headers": ["수집 채널", "수집 건수", "비중"], "rows": ch_rows},
            visual_assets_json=[
                {
                    "asset_type": "CONSUMER_KBF_CHART",
                    "title": "수집 VOC 감성 분포 (긍정/아쉬움·복합/중립)",
                    "metadata": {"positive": pos_cnt, "negative": neg_cnt, "neutral": neu_cnt},
                    "caption": f"수집 원문 {len(consumer_sources)}건 감성 분류 (부정 {neg_strict} + 복합우려 {mixed_cnt})",
                }
            ],
            bullets_json=facts_to_bullets(consumer_facts, fallback_claim="채널별 VOC 집중 주제 및 감성 분포 해석"),
            footnote="출처: 네이버 블로그·카페·더쿠·디시인사이드·에펨코리아·클리앙 실수집 원문",
        )
    )
    order += 1

    # 4-3. 실발화 원문
    pos_quotes = [s for s in consumer_sources if s.sentiment == "POSITIVE"][:3]
    neg_quotes = [s for s in consumer_sources if s.sentiment == "NEGATIVE"][:3]
    if len(neg_quotes) < 2:
        mixed_quotes = [s for s in consumer_sources if s.sentiment == "MIXED" and s not in neg_quotes]
        neg_quotes.extend(mixed_quotes[: max(0, 3 - len(neg_quotes))])
    voice_rows: list[list[str]] = []
    for i in range(max(len(pos_quotes), len(neg_quotes), 1)):
        pq = smart_truncate(pos_quotes[i].evidence_quote or pos_quotes[i].title, 62) if i < len(pos_quotes) else "추가 긍정 원문 확인 필요"
        nq = smart_truncate(neg_quotes[i].evidence_quote or neg_quotes[i].title, 62) if i < len(neg_quotes) else "부정/이탈 원문 보완 수집 필요"
        src_p = pos_quotes[i].channel if i < len(pos_quotes) else "-"
        src_n = neg_quotes[i].channel if i < len(neg_quotes) else "-"
        voice_rows.append([f"[{src_p}] {pq}", f"[{src_n}] {nq}"])

    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.CONSUMER.value,
            slide_order=order,
            slide_type="CONSUMER_VOC_VOICES",
            title="4-3. 소비자 분석 — 실발화 원문: 선택 이유 vs 불만·이탈 요인",
            headcopy="커뮤니티·블로그·리뷰 실사용 원문에서 검증된 핵심 추천 근거와 이탈·불만 트리거 대조",
            table_json={"headers": ["믿고 사는 이유 (긍정 KBF 발화)", "이탈·고민 요인 (부정/허들 발화)"], "rows": voice_rows[:4]},
            bullets_json=facts_to_bullets(consumer_facts, fallback_claim="실사용 후기 내 반복 등장 키워드 및 원문 신뢰 요인"),
            footnote="출처: Apify 수집 커뮤니티·블로그·카페 원문 및 하이라이트 추출 문장",
        )
    )
    order += 1

    # 4-4. 브랜드별 소비자 인식 비교
    comp_brand_rows = [
        [
            b,
            "긍정/실사용 키워드 요약",
            "가격·이탈 우려 키워드",
            f"VOC {_filter_brand_sources(consumer_sources, b).__len__()}건",
        ]
        for b in [project.brand_name, *[c.brand_name for c in project.competitors[:3]]]
    ]
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.CONSUMER.value,
            slide_order=order,
            slide_type="CONSUMER_BRAND_COMPARE",
            title="4-4. 소비자 분석 — 자사·경쟁사 브랜드별 소비자 인식 키워드 비교",
            headcopy=f"{project.brand_name} 대비 경쟁 브랜드 선택 시 소비자가 언급하는 인식 격차와 전환 장벽 진단",
            table_json={
                "headers": ["브랜드", "핵심 호감·연상 키워드", "우려·이탈 키워드", "표본 근거"],
                "rows": comp_brand_rows,
            },
            bullets_json=facts_to_bullets(consumer_facts, fallback_claim="브랜드 간 소비자 지각 이미지 및 선택 분기 요인"),
            footnote="출처: Apify 커뮤니티·블로그 브랜드별 발화 비교 및 Perplexity 인식 리서치",
        )
    )
    order += 1

    # 4-5. 소셜·소비 트렌드
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.CONSUMER.value,
            slide_order=order,
            slide_type="CONSUMER_TRENDS_SOCIAL",
            title="4-5. 소비자 분석 — 소셜·소비 트렌드 변화 및 고반응 콘텐츠 포맷",
            headcopy=f"{project.industry_category} 최신 소비 가치관 변화와 숏폼·실사용 기반 고성과 소셜 포맷 도출",
            table_json={
                "headers": ["트렌드 영역", "최근 소비·콘텐츠 변화", "캠페인 적용 기회"],
                "rows": [
                    ["구매 의사결정", "스펙 검증형·실사용 비교 탐색 확대", "객관적 사용 장면·비교 근거 제시"],
                    ["소셜 콘텐츠 소비", "짧은 사용 노하우·언박싱/후기 릴스 강세", "일상 밀착 숏폼 시리즈 포맷 전개"],
                ],
            },
            bullets_json=facts_to_bullets(consumer_facts, fallback_claim="소셜 미디어 내 소비자 관심 키워드 및 포맷 변화"),
            footnote="출처: Perplexity 소셜·소비 트렌드 리서치 및 SNS 반응 분석",
        )
    )
    order += 1

    # 4-6. 유사 산업 선도 벤치마크 요약
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.CONSUMER.value,
            slide_order=order,
            slide_type="CONSUMER_BENCHMARKS",
            title="4-6. 소비자 분석 — 유사 산업 선도 브랜드 마케팅 벤치마크",
            headcopy=f"{project.industry_category} 인접 라이프스타일·테크·소비재 선도 브랜드의 디지털 캠페인·콘텐츠 성공 요인",
            table_json={
                "headers": ["벤치마크 영역", "선도 사례 핵심 전략", "성과/반응 메커니즘", "적용 가능성"],
                "rows": [
                    ["체험·커뮤니티 시딩", "핵심 타깃 실사용 챌린지 설계", "자연 발화 및 저장·공유 유도", "높음"],
                    ["온·오프 경험 통합", "제품 USP 직관화 팝업·스토리텔링", "고관여 탐색층 신뢰 확보", "중간"],
                ],
            },
            bullets_json=facts_to_bullets(consumer_facts, fallback_claim="유사 산업 고성과 브랜드의 타겟 접점 확보 사례 요약"),
            footnote="출처: Perplexity 크로스 인더스트리 마케팅 벤치마크 리서치",
        )
    )
    order += 1

    # 4-7. 크로스 인더스트리 적용 방향 상세
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.CONSUMER.value,
            slide_order=order,
            slide_type="CONSUMER_BENCHMARK_DETAIL",
            title="4-7. 소비자 분석 — 벤치마크 인사이트 기반 자사 이식 실행안",
            headcopy=f"확인된 외부 성공 메커니즘을 {project.brand_name} '{project.product_name}' 캠페인·크리에이티브에 이식하는 방안",
            table_json={
                "headers": ["이식 과제", "현재 공백(AS-IS)", "실행 이식 방향(TO-BE)", "기대 KPI"],
                "rows": [
                    ["포맷 표준화", "단발성 제품 소개 위주", "실사용·노하우 시리즈화", "저장수·조회율 상승"],
                    ["신뢰 검증 장치", "공식 스펙 설명 편중", "크리에이터·실후기 결합 검증", "검색→구매 전환 개선"],
                ],
            },
            bullets_json=facts_to_bullets(consumer_facts, fallback_claim="타 업종 벤치마크의 자사 채널 및 캠페인 구체적 적용 방안"),
            footnote="출처: 종합 트렌드·벤치마크 리서치 및 자사 채널 진단 매핑",
        )
    )
    order += 1
    return slides, order


def build_section5_slides(
    *,
    project: Project,
    sources: list[RawSourceItem],
    facts: list[FactItem],
    datalab_series: list[DataLabSeries],
    non_summary_slides: list[SlideDraft],
    split_mode: SummarySplitMode,
    start_order: int,
) -> list[SlideDraft]:
    """Build Part 5 divider + Summary (2 or 4) + AS-IS->TO-BE + Data Gap + Appendix with full URLs."""
    by_sec: dict[str, list[SlideDraft]] = {}
    facts_by_sec: dict[str, list[FactItem]] = {}
    for s in non_summary_slides:
        by_sec.setdefault(s.section_code, []).append(s)
    for f in facts:
        facts_by_sec.setdefault(f.section_code, []).append(f)

    def sec_bullets(sec_code: str, fallback: str) -> list[dict[str, Any]]:
        sec_facts = facts_by_sec.get(sec_code, [])
        if sec_facts:
            return facts_to_bullets(sec_facts, limit=3, fallback_claim=fallback)
        sec_slides = by_sec.get(sec_code, [])
        out: list[dict[str, Any]] = []
        for sl in sec_slides:
            for b in sl.bullets_json or []:
                out.append(b)
                if len(out) >= 3:
                    return out
        return facts_to_bullets([], limit=2, fallback_claim=fallback)

    result: list[SlideDraft] = []
    order = start_order

    # PART 5 Divider
    result.append(
        make_section_divider(
            project_id=project.id,
            section_code=SectionCode.SUMMARY_CONCLUSION.value,
            order=order,
            part_title="PART 5 · 5. 종합 요약 및 전략 제언 (Summary & Appendix)",
            subtitle="1~4장 실증 팩트 종합 요약·AS-IS→TO-BE 전략 과제·데이터 공백 투명 공개 및 전체 검증 출처 인덱스",
            slide_topics=[
                "5-1~5-2(또는 5-4): 3C+C 핵심 현황 요약",
                "AS-IS → TO-BE 전략 방향 및 액션 플랜 도출",
                "데이터 공백 명시 및 검증된 고유 출처 URL 부록",
            ],
            kpi_chips=[
                {"label": "요약 분할 모드", "value": split_mode.value, "delta": "2~4장 분할", "basis": "과밀 방지"},
                {"label": "검증 팩트 풀", "value": f"{len(facts)}건", "delta": "추적 가능", "basis": "1~4장 기반"},
                {"label": "전체 원천 자료", "value": f"{len(sources)}건", "delta": "부록 URL 연결", "basis": "Source Pool"},
            ],
            footnote=f"PART 5 범위: {project.brand_name} 종합 전략 도출 및 출처 무결성 인덱스",
        )
    )
    order += 1

    if split_mode == SummarySplitMode.SPLIT_4:
        summary_specs = [
            ("5-1. 현황 요약 (1/4) — 자사 브랜드·제품 핵심 진단", SectionCode.OWN.value, f"{project.brand_name} {project.product_name} 자사 자산 요약"),
            ("5-2. 현황 요약 (2/4) — 시장·유통·규제 환경 요약", SectionCode.MARKET.value, f"{project.industry_category} 시장 변화 요약"),
            ("5-3. 현황 요약 (3/4) — 경쟁 구도 및 활동 6분류 요약", SectionCode.COMPETITOR.value, "경쟁사 SoS·마케팅 비교 요약"),
            ("5-4. 현황 요약 (4/4) — 소비자 인식 및 VOC 핵심 요약", SectionCode.CONSUMER.value, "실사용자 KBF 및 불만 요약"),
        ]
        for title, sec_code, fallback in summary_specs:
            sec_slides = by_sec.get(sec_code, [])
            non_div = [sl for sl in sec_slides if sl.slide_type != "SECTION_DIVIDER"]
            summary_rows = [
                [smart_truncate(sl.title, 34), smart_truncate(sl.headcopy, 76)]
                for sl in non_div[:4]
            ] or [[sec_code, fallback]]
            result.append(
                sanitize_slide_draft(
                    SlideDraft(
                        project_id=project.id,
                        section_code=SectionCode.SUMMARY_CONCLUSION.value,
                        slide_order=order,
                        slide_type="SUMMARY_PART",
                        title=title,
                        headcopy=non_div[0].headcopy if non_div else fallback,
                        table_json={"headers": ["세부 분석 영역", "핵심 요약 포인트"], "rows": summary_rows},
                        bullets_json=sec_bullets(sec_code, fallback),
                        footnote="출처: 1~4장 검증 슬라이드 및 원문 팩트 기반 요약",
                    )
                )
            )
            order += 1
    else:
        own_hc = next((sl for sl in by_sec.get(SectionCode.OWN.value, []) if sl.slide_type != "SECTION_DIVIDER"), None)
        mkt_hc = next((sl for sl in by_sec.get(SectionCode.MARKET.value, []) if sl.slide_type != "SECTION_DIVIDER"), None)
        comp_hc = next((sl for sl in by_sec.get(SectionCode.COMPETITOR.value, []) if sl.slide_type != "SECTION_DIVIDER"), None)
        cons_hc = next((sl for sl in by_sec.get(SectionCode.CONSUMER.value, []) if sl.slide_type != "SECTION_DIVIDER"), None)
        result.extend(
            [
                sanitize_slide_draft(
                    SlideDraft(
                        project_id=project.id,
                        section_code=SectionCode.SUMMARY_CONCLUSION.value,
                        slide_order=order,
                        slide_type="SUMMARY_PART",
                        title="5-1. 현황 요약 (1/2) — 자사 자산 및 시장 기회 요약",
                        headcopy=f"{project.brand_name} '{project.product_name}'의 브랜드 자산과 시장 수요·규제 변화 핵심 정리",
                        table_json={
                            "headers": ["영역", "핵심 진단 내용"],
                            "rows": [
                                ["1. 자사 진단", smart_truncate(own_hc.headcopy, 78) if own_hc else "자사 현황 점검"],
                                ["2. 시장 환경", smart_truncate(mkt_hc.headcopy, 78) if mkt_hc else "시장 현황 점검"],
                            ],
                        },
                        bullets_json=sec_bullets(SectionCode.MARKET.value, "시장 핵심 진단")[:2]
                        + sec_bullets(SectionCode.OWN.value, "자사 핵심 진단")[:1],
                        footnote="출처: PART 1(자사)·PART 2(시장) 검증 팩트 요약",
                    )
                ),
                sanitize_slide_draft(
                    SlideDraft(
                        project_id=project.id,
                        section_code=SectionCode.SUMMARY_CONCLUSION.value,
                        slide_order=order + 1,
                        slide_type="SUMMARY_PART",
                        title="5-2. 현황 요약 (2/2) — 경쟁 구도 및 소비자 VOC 핵심 요약",
                        headcopy="경쟁사 검색 점유율(SoS)·마케팅 공백과 실소비자 구매·이탈 요인 종합",
                        table_json={
                            "headers": ["영역", "핵심 진단 내용"],
                            "rows": [
                                ["3. 경쟁 구도", smart_truncate(comp_hc.headcopy, 78) if comp_hc else "경쟁 현황 점검"],
                                ["4. 소비자 VOC", smart_truncate(cons_hc.headcopy, 78) if cons_hc else "소비자 인식 점검"],
                            ],
                        },
                        bullets_json=sec_bullets(SectionCode.COMPETITOR.value, "경쟁 핵심 진단")[:2]
                        + sec_bullets(SectionCode.CONSUMER.value, "소비자 핵심 진단")[:1],
                        footnote="출처: PART 3(경쟁사)·PART 4(소비자) 검증 팩트 요약",
                    )
                ),
            ]
        )
        order += 2

    linked_ids = [f.id for f in facts[:6]]
    result.append(
        sanitize_slide_draft(
            SlideDraft(
                project_id=project.id,
                section_code=SectionCode.SUMMARY_CONCLUSION.value,
                slide_order=order,
                slide_type="CONCLUSION_ASIS_TOBE",
                title="5-3. 전략적 시사점 및 과제 방향 (AS-IS → TO-BE)",
                headcopy=f"{project.brand_name} '{project.product_name}'의 현재 진단(AS-IS)과 제안서 핵심 과제(TO-BE)",
                bullets_json=[
                    {
                        "claim": f"1~4장 검증 팩트 {len(facts)}건을 토대로 도출한 AS-IS → TO-BE 실행 방향",
                        "evidence_quote": facts[0].evidence_quote[:110] if facts else None,
                        "source_name": "팩트북 종합 결론",
                        "source_url": facts[0].source_url if facts else None,
                        "fact_id": facts[0].id if facts else None,
                    }
                ],
                as_is_to_be_json={
                    "as_is_points": [
                        f"{project.brand_name} {project.product_name}의 핵심 검색 모멘텀과 공식 채널 도달 구조 점검 필요",
                        "경쟁사 대비 차별화된 선택 이유(KBF)와 가격/구매 접점 정렬 필요",
                    ],
                    "key_issues": [
                        "Owned 콘텐츠 성과 편차 완화 및 크리에이터·장면형 숏폼 포맷 전환 과제",
                        "실사용자 VOC 불만/이탈 장벽(가격·AS·신뢰) 해소 메시지 보강 필요",
                    ],
                    "to_be_directions": [
                        "타겟·메시지: 검증된 실사용 KBF 중심의 장면형 크리에이티브 전개",
                        "채널 전략: 고성과 숏폼/협업 포맷 확산 및 비교 탐색 키워드 장악",
                        "신뢰 전환: 사후관리·정가 대비 가치 설득으로 구매 허들 완화",
                    ],
                    "linked_fact_ids": linked_ids,
                },
                footnote="출처: 1~4장 검증 팩트 기반 AS-IS → TO-BE 전략 브릿지",
            )
        )
    )
    order += 1

    # DATA GAP
    gap_rows: list[list[str]] = []
    if len(project.sns_accounts) < 4:
        gap_rows.append(["일부 경쟁사 공식 SNS TOP 5", "계정 URL 미등록 또는 비공개", "경쟁사 인스타그램/유튜브 URL 추가 등록 후 재수집"])
    if not any(s.metric_type == "SHOPPING_INSIGHT" for s in (datalab_series or [])):
        gap_rows.append(["네이버 쇼핑 클릭 인사이트", "일부 비표준/잡화 세부 카테고리 제한", "적합 네이버 쇼핑 카테고리 ID 매핑 후 재수집"])
    gap_rows.append(["오프라인·유통사 실판매 점유율", "공개 API 및 웹 자료 내 미공개", "클라이언트 내부 POS/매출 자료 및 유료 리포트 대조 필요"])
    gap_rows.append(["비공개 네이버 카페 본문 원문", "회원 로그인 제한으로 일부 제목·스니펫만 수집", "오픈 커뮤니티 및 공식 리뷰 채널 교차 검증 권장"])

    result.append(
        sanitize_slide_draft(
            SlideDraft(
                project_id=project.id,
                section_code=SectionCode.SUMMARY_CONCLUSION.value,
                slide_order=order,
                slide_type="DATA_GAP",
                title="5-4. 데이터 공백 및 추가 확인 과제 (Hallucination-Zero 기준)",
                headcopy="수집 범위·공개 자료 한계로 확인하지 못한 항목은 임의 생성 없이 공백 사유와 후속 보완 경로를 명시함",
                table_json={
                    "headers": ["확인 불가(공백) 항목", "미수집 사유", "보완 방법 및 다음 과제"],
                    "rows": gap_rows[:5],
                },
                bullets_json=[
                    {
                        "claim": "미확인 수치 배제: API·공개 리서치에서 검증되지 않은 점유율·캠페인 매출 등은 '확인 못 함'으로 투명 표기함",
                        "evidence_quote": None,
                        "source_name": "팩트북 신뢰성 기준",
                        "source_url": None,
                        "fact_id": None,
                    }
                ],
                footnote="출처: 다중 API 수집 로그 및 사전 QC 데이터 공백 점검 결과",
            )
        )
    )
    order += 1

    # APPENDIX SOURCES — preserve full un-truncated URLs so FE/PPTX hyperlinks never break
    all_unique_urls: set[str] = set()
    by_sec_sources: dict[str, list[RawSourceItem]] = {}
    for src in sources:
        if src.source_url:
            all_unique_urls.add(src.source_url)
            by_sec_sources.setdefault(src.section_code, []).append(src)
        for cit in (src.metadata_json or {}).get("citations", []) if isinstance(src.metadata_json, dict) else []:
            if cit:
                all_unique_urls.add(str(cit))

    app_rows: list[list[str]] = []
    picked_urls: set[str] = set()
    ordered_pool: list[RawSourceItem] = []
    sec_buckets = list(by_sec_sources.values())
    for idx in range(max((len(b) for b in sec_buckets), default=0)):
        for bucket in sec_buckets:
            if idx < len(bucket):
                ordered_pool.append(bucket[idx])
    for src in ordered_pool:
        if src.source_url and src.source_url not in picked_urls:
            picked_urls.add(src.source_url)
            app_rows.append(
                [src.section_code, src.channel, smart_truncate(src.title, 36), src.source_url.strip()]
            )
        if len(app_rows) >= 12:
            break
    if not app_rows:
        app_rows.append(["전체", "다중 API", "수집 출처 URL 기록", "상세 URL 원문 풀 참조"])

    result.append(
        sanitize_slide_draft(
            SlideDraft(
                project_id=project.id,
                section_code=SectionCode.SUMMARY_CONCLUSION.value,
                slide_order=order,
                slide_type="APPENDIX_SOURCES",
                title="부록. 주요 출처 및 검증 URL 목록",
                headcopy=f"수집 원문 및 인용 근거에서 확인된 총 {len(all_unique_urls)}건의 고유 출처 URL을 섹션·채널별로 연결해 검증 가능성을 확보함",
                table_json={
                    "headers": ["섹션", "채널", "자료명 (대표 샘플)", "출처 URL"],
                    "rows": app_rows,
                },
                bullets_json=[
                    {
                        "claim": f"전체 수집 원문 {len(sources)}건 및 리서치 인용에서 고유 URL {len(all_unique_urls)}건이 자료·수집 풀(Source Pool)과 연결됨",
                        "evidence_quote": None,
                        "source_name": "출처 검증 인덱스",
                        "source_url": next(iter(picked_urls), None),
                        "fact_id": None,
                    }
                ],
                footnote="출처: 자료·수집 풀(Source Pool) 전체 URL 및 Perplexity 인용 출처 인덱스",
            )
        )
    )
    return result
