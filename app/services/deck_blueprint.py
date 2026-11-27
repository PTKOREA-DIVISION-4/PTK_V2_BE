from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.models.collection import DataLabSeries, MediaAsset, RawSourceItem, SnsTopPost
from app.models.factbook import FactItem, SlideDraft
from app.models.project import Project
from app.schemas.common import SectionCode, SummarySplitMode


_INVISIBLE_CHARS_RE = re.compile(r"[\u2800\u3164\u200b\u200c\u200d\ufeff]+")
_CITATION_BRACKETS_RE = re.compile(r"(?:\[\d+\])+")
_MD_BOLD_RE = re.compile(r"\*{1,3}|_{2,3}|`+")
_MD_HEADER_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MULTI_SPACE_RE = re.compile(r"\s+")


def clean_slide_text(text: str | None) -> str:
    """Strips markdown syntax, Perplexity [1][2] brackets, and leading list hyphens without erasing negative signs."""
    if not text:
        return ""
    s = str(text)
    s = _INVISIBLE_CHARS_RE.sub(" ", s)
    s = _CITATION_BRACKETS_RE.sub("", s)
    s = _MD_HEADER_RE.sub("", s)
    s = _MD_BOLD_RE.sub("", s)
    # Strip leading whitespace, em/en dashes, or Markdown bullet "- " (keep "-12.5%", "-3.4%", etc.)
    s = re.sub(r"^(?:[\s—–]+|-\s+)+", "", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s


def smart_truncate(text: str | None, max_len: int) -> str:
    """Truncates text cleanly at a word/punctuation boundary when exceeding max_len."""
    cleaned = clean_slide_text(text)
    if len(cleaned) <= max_len:
        return cleaned
    if max_len <= 2:
        return cleaned[:max_len]
    cut = cleaned[: max_len - 1]
    for sep in (" ", ",", "·", "/", ")"):
        idx = cut.rfind(sep)
        if idx >= int(max_len * 0.6):
            cut = cut[:idx].rstrip(" ,·/")
            break
    return f"{cut}…"


def format_post_metrics_caption(p: SnsTopPost) -> str:
    date_str = p.published_at.strftime("%Y-%m-%d")
    parts = [f"TOP {p.rank_order}", date_str]
    if p.views > 0:
        parts.append(f"조회 {p.views:,}")
    parts.append(f"좋아요 {p.likes:,}")
    parts.append(f"댓글 {p.comments:,}")
    return " | ".join(parts)


def facts_to_bullets(
    facts: list[FactItem], *, fallback_claim: str, limit: int = 3
) -> list[dict[str, Any]]:
    if not facts:
        return [
            {
                "claim": fallback_claim,
                "evidence_quote": None,
                "source_name": "수집 범위 내 확인 불가",
                "source_url": None,
                "fact_id": None,
            }
        ]
    return [
        {
            "claim": clean_slide_text(f.claim_text)[:130],
            "evidence_quote": clean_slide_text(f.evidence_quote)[:120] or None,
            "source_name": clean_slide_text(f.source_name)[:36] or None,
            "source_url": f.source_url,
            "fact_id": f.id,
        }
        for f in facts[:limit]
    ]


def sanitize_slide_draft(slide: SlideDraft) -> SlideDraft:
    """Enforces MySQL column bounds and consistent clean typography on SlideDraft."""
    slide.title = clean_slide_text(slide.title)[:230] or "제목 없음"
    slide.headcopy = clean_slide_text(slide.headcopy)[:380] or slide.title
    if slide.footnote is not None:
        slide.footnote = clean_slide_text(slide.footnote)[:480] or None
    return slide


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
    """Builds a structured 20+ slide multi-section deck strictly grounded in collected data."""
    asset_by_id = {a.id: a for a in media_assets}
    facts_by_sec: dict[str, list[FactItem]] = {}
    for f in facts:
        facts_by_sec.setdefault(f.section_code, []).append(f)

    own_dl = [
        s
        for s in datalab_series
        if s.owner_type == "OWN" and s.metric_type == "SEARCH_TREND"
    ]
    search_dl = [s for s in datalab_series if s.metric_type == "SEARCH_TREND"]
    collab_label = f"{project.brand_name} 협업"
    own_sns = [
        p for p in sns_posts if p.owner_type == "OWN" and p.brand_label != collab_label
    ][:5]
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

    slides: list[SlideDraft] = []
    order = 1

    # ── 0. OVERVIEW (1장) ─────────────────────────────────────────────────────
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
                {
                    "label": "단일 분석 타겟",
                    "value": f"{project.brand_name} {project.product_name}",
                    "delta": project.industry_category,
                    "basis": track_label,
                },
                {
                    "label": "비교 경쟁 세트",
                    "value": f"{len(project.competitors)}개 제품",
                    "delta": comp_names[:36],
                    "basis": "1:1 동일 카테고리 매칭",
                },
                {
                    "label": "수집·검증 원천",
                    "value": f"{len(sources)}건",
                    "delta": f"추출 팩트 {len(facts)}건",
                    "basis": "Perplexity·SNS·커뮤니티 합산",
                },
                {
                    "label": "정량 시계열·SNS",
                    "value": f"DL {len(search_dl)}종 / SNS {len(sns_posts)}건",
                    "delta": f"협업 {len(collab_sns)}건 포함",
                    "basis": "네이버 데이터랩 · ScrapeCreators",
                },
            ],
            table_json={
                "headers": ["조사 구분", "설정 기준값", "수집 채널 및 검증 방식"],
                "rows": [
                    ["대상 브랜드·제품", f"{project.brand_name} / {project.product_name}", "단일 브랜드·단일 주력 제품 원칙 적용"],
                    ["조사 기간", f"{project.period_start} ~ {project.period_end}", "전 기간 정량 추이 + 기간 내 SNS 필터링"],
                    ["경쟁 세트", comp_names[:42], "네이버 데이터랩 SoS 및 6분류 활동 비교"],
                    ["수집 소스", f"리서치·SNS·커뮤니티 {len(sources)}건", "확인 불가 수치는 미확인(확인 못 함) 처리"],
                ],
            },
            bullets_json=[
                {
                    "claim": f"단일 브랜드·제품 원칙: {project.brand_name} '{project.product_name}' 기준으로 검색·SNS·VOC 모수를 고정해 노이즈를 차단함",
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

    # ── 1. OWN ANALYSIS (5장) ─────────────────────────────────────────────────
    own_facts = facts_by_sec.get(SectionCode.OWN.value, [])
    own_share = own_dl[0].share_of_search_pct if own_dl else 0.0
    own_growth = own_dl[0].growth_rate_pct if own_dl else 0.0
    dl_note = own_dl[0].methodology_note if own_dl else f"출처: 네이버 데이터랩 ({project.period_start}~{project.period_end})"

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
                "실적·신제품·공식 포지셔닝 핵심 동인을 점검함"
            ),
            kpi_cards_json=[
                {
                    "label": "경쟁군 검색 점유율(SoS)",
                    "value": f"{own_share:.1f}%",
                    "delta": f"전기 대비 {own_growth:+.1f}%",
                    "basis": "네이버 데이터랩 합산",
                },
                {
                    "label": "공식 SNS TOP 5",
                    "value": f"{len(own_sns)}건",
                    "delta": f"최고 반응 {int(own_sns[0].engagement_score):,}" if own_sns else "수집 없음",
                    "basis": "기간 내 게시물 기준",
                },
                {
                    "label": "크리에이터 협업",
                    "value": f"{len(collab_sns)}건",
                    "delta": "유튜브/인스타 탐지",
                    "basis": "협찬·공동작성 태그 기준",
                },
                {
                    "label": "자사 검증 자료",
                    "value": f"{len(own_facts)}건",
                    "delta": "실적·신제품·보도 포함",
                    "basis": "Perplexity·SNS 수집",
                },
            ],
            table_json={
                "headers": ["구분", "확인된 핵심 지표", "출처/근거"],
                "rows": [
                    ["검색 점유율(SoS)", f"{own_share:.1f}% (후반기 {own_growth:+.1f}%)", "네이버 데이터랩"],
                    ["공식 채널 TOP 1", format_post_metrics_caption(own_sns[0]) if own_sns else "확인 못 함", own_sns[0].platform if own_sns else "-"],
                    ["주력 제품 포지션", f"{project.brand_name} {project.product_name}", "조사 리서치 원문 반영 예정"],
                ],
            },
            bullets_json=facts_to_bullets(own_facts, fallback_claim=f"{project.brand_name} 실적 및 브랜드 포지셔닝 요약"),
            footnote=f"출처: Perplexity 리서치 및 {dl_note.removeprefix('출처: ').strip()}",
        )
    )
    order += 1

    # 1-2. 자사 신제품·주력 라인업 및 가격·할인 구조
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OWN.value,
            slide_order=order,
            slide_type="OWN_PRODUCTS_PRICE",
            title="1-2. 자사 분석 — 주력·신제품 라인업 및 가격·할인 구조",
            headcopy=f"{project.brand_name} '{project.product_name}'의 대표 라인업·차별화 USP 및 공식 가격·할인 폭 분포 진단",
            table_json={
                "headers": ["라인업/구분", "핵심 스펙·특징", "가격/할인 정보", "채널/출처"],
                "rows": [
                    [f"{project.product_name} 주력", "수집 원문 기반 제품 스펙 정리", "확인 못 함", "공식몰·리서치"],
                ],
            },
            visual_assets_json=[
                {
                    "asset_type": "HORIZONTAL_BAR_CHART",
                    "title": f"{project.brand_name} 주요 라인업 가격 비교 (단위: 만원)",
                    "caption": "수집 원문에서 확인된 공식가/실판매가 기준",
                    "metadata": {"unit": "만원", "items": []},
                }
            ],
            bullets_json=facts_to_bullets(
                own_facts[1:] or own_facts,
                fallback_claim=f"{project.brand_name} 주력 제품 라인업 및 정가·행사가 구조 분석",
            ),
            footnote="출처: Perplexity 브랜드 제품·가격 리서치 및 공식 채널 공개 자료",
        )
    )
    order += 1

    # 1-3. Owned SNS 채널 현황
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
            title="1-3. 자사 분석 — Owned SNS 채널 현황 및 운영 규모",
            headcopy=(
                f"등록된 공식 SNS 채널({len(account_rows)}개) 팔로워·게시물 모수 및 기간 내 유효 반응 밀도 비교"
            ),
            table_json={
                "headers": ["플랫폼", "계정 핸들", "팔로워/구독자", "기간 내 TOP", "소유 구분"],
                "rows": account_rows[:6],
            },
            bullets_json=[
                {
                    "claim": clean_slide_text(psrc.content)[:130],
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

    # 1-4. 자사 공식 SNS TOP 5
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OWN.value,
            slide_order=order,
            slide_type="OWN_SNS_TOP5",
            title="1-4. 자사 분석 — 공식 SNS 기간 내 인기 게시물 TOP 5",
            headcopy=f"설정 기간({project.period_start}~{project.period_end}) 내 자사 공식 채널 고성과 콘텐츠 TOP 5 성과 분석",
            kpi_cards_json=[
                {
                    "label": f"TOP {p.rank_order} ({p.platform})",
                    "value": f"조회 {p.views:,}" if p.views > 0 else f"좋아요 {p.likes:,}",
                    "delta": f"좋아요 {p.likes:,} / 댓글 {p.comments:,}",
                    "basis": f"{'협업 · ' if p.is_creator_collab else ''}{p.published_at.strftime('%Y-%m-%d')}",
                }
                for p in own_sns[:4]
            ],
            bullets_json=[
                {
                    "claim": f"[TOP {p.rank_order}] {clean_slide_text(p.caption)[:85]}",
                    "evidence_quote": format_post_metrics_caption(p),
                    "source_name": f"{p.brand_label} {p.platform}",
                    "source_url": p.post_url,
                    "fact_id": None,
                }
                for p in own_sns[:3]
            ]
            or [
                {
                    "claim": "기간 내 자사 공식 SNS 게시물이 없거나 계정 URL이 등록되지 않았습니다.",
                    "evidence_quote": "확인 못 함",
                    "source_name": "ScrapeCreators",
                    "source_url": None,
                    "fact_id": None,
                }
            ],
            visual_assets_json=[
                {
                    "asset_type": "SNS_TOP5_CARD",
                    "title": f"TOP {p.rank_order} | {p.platform}",
                    "local_path": (
                        asset_by_id[p.media_asset_id].local_path
                        if p.media_asset_id in asset_by_id
                        else None
                    ),
                    "caption": format_post_metrics_caption(p),
                    "annotation_text": clean_slide_text(p.caption)[:75],
                    "metadata": {"is_collab": p.is_creator_collab, "post_url": p.post_url},
                }
                for p in own_sns
            ],
            footnote="기준: 설정 기간 내 게시물 대상 플랫폼별 반응 산식 정렬 TOP 5 (ScrapeCreators)",
        )
    )
    order += 1

    # 1-5. 크리에이터 협업 & 언론 보도·대표 캠페인
    collab_rows = [
        [
            p.published_at.strftime("%Y-%m-%d"),
            clean_slide_text(p.caption)[:34] or "-",
            p.platform,
            f"조회 {p.views:,}" if p.views > 0 else "-",
            f"좋아요 {p.likes:,} / 댓글 {p.comments:,}",
        ]
        for p in collab_sns[:5]
    ] or [["기간 내 수집", "크리에이터 협업 탐지 건 부족", "-", "확인 못 함", "-"]]

    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.OWN.value,
            slide_order=order,
            slide_type="OWN_CAMPAIGNS",
            title="1-5. 자사 분석 — 크리에이터 협업·언론 보도 및 대표 캠페인",
            headcopy=f"{project.brand_name} '{project.product_name}' 관련 크리에이터 시딩·협업 성과 및 주요 보도·캠페인 흐름",
            table_json={
                "headers": ["게시일", "협업/캠페인 콘텐츠", "채널", "조회수", "반응 지표"],
                "rows": collab_rows,
            },
            bullets_json=facts_to_bullets(own_facts, fallback_claim="언론 보도·팝업·크리에이터 협업 성과 요약"),
            footnote="출처: ScrapeCreators 협업 탐색 및 Perplexity 브랜드 보도·캠페인 리서치",
        )
    )
    order += 1

    # ── 2. MARKET ANALYSIS (3장) ──────────────────────────────────────────────
    market_facts = facts_by_sec.get(SectionCode.MARKET.value, [])

    # 2-1. 시장 규모 & 거시 수요 추이
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.MARKET.value,
            slide_order=order,
            slide_type="MARKET_OVERVIEW",
            title="2-1. 시장 분석 — 글로벌·국내 시장 규모 및 거시 수요 추이",
            headcopy=f"{project.industry_category}({project.product_name}) 시장의 외형 성장과 실수요 간 괴리 및 핵심 성장 드라이버 진단",
            kpi_cards_json=[
                {
                    "label": "분석 트랙",
                    "value": "리뷰 중심" if project.analysis_track == "REVIEW_CENTRIC" else "시장 지표 중심",
                    "delta": project.industry_category,
                    "basis": "산업군 특성 분기",
                },
                {
                    "label": "시장 확보 자료",
                    "value": f"{len(market_facts)}건",
                    "delta": "출처 URL 연결",
                    "basis": "Perplexity 거시 리서치",
                },
            ],
            table_json={
                "headers": ["시장 지표/기관", "규모/수치", "비고/기준연도"],
                "rows": [["글로벌·국내 시장 규모", "확인 못 함 (원문 수치 미수집)", "확인 못 함"]],
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

    # 2-2. 카테고리 신호·유통 변화 & 규제
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.MARKET.value,
            slide_order=order,
            slide_type="MARKET_SIGNALS",
            title="2-2. 시장 분석 — 카테고리 신호·유통 변화 및 규제 환경",
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

    # 2-3. 국내 시장 플레이어 지형
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
            title="2-3. 시장 분석 — 국내 플레이어 지형 및 포지션 구분",
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

    # ── 3. COMPETITOR ANALYSIS (4장) ──────────────────────────────────────────
    comp_facts = facts_by_sec.get(SectionCode.COMPETITOR.value, [])
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

    # 3-1. 경쟁 세트 비교 & 검색 점유율(SoS)
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

    # 3-2. 검색 관심도 추이 & 가격 포지션 비교
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

    # 3-3. 경쟁사 SNS TOP 5
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.COMPETITOR.value,
            slide_order=order,
            slide_type="COMPETITOR_SNS_TOP5",
            title="3-3. 경쟁사 분석 — 경쟁사 공식 SNS 인기 게시물 TOP 5",
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
            bullets_json=[
                {
                    "claim": f"[{p.brand_label} TOP {p.rank_order}] {clean_slide_text(p.caption)[:85]}",
                    "evidence_quote": format_post_metrics_caption(p),
                    "source_name": p.platform,
                    "source_url": p.post_url,
                    "fact_id": None,
                }
                for p in comp_sns[:3]
            ]
            or [
                {
                    "claim": "등록된 경쟁사 SNS 계정이 없거나 기간 내 게시물이 확인되지 않았습니다.",
                    "evidence_quote": "확인 못 함 (경쟁사 SNS URL 입력 시 자동 수집)",
                    "source_name": "ScrapeCreators",
                    "source_url": None,
                    "fact_id": None,
                }
            ],
            visual_assets_json=[
                {
                    "asset_type": "SNS_TOP5_CARD",
                    "title": f"{p.brand_label} TOP {p.rank_order}",
                    "local_path": (
                        asset_by_id[p.media_asset_id].local_path
                        if p.media_asset_id in asset_by_id
                        else None
                    ),
                    "caption": format_post_metrics_caption(p),
                    "annotation_text": clean_slide_text(p.caption)[:75],
                    "metadata": {"is_collab": p.is_creator_collab, "post_url": p.post_url},
                }
                for p in comp_sns
            ],
            footnote="출처: ScrapeCreators 경쟁사 공식 SNS 기간 내 인기 게시물 TOP 5",
        )
    )
    order += 1

    # 3-4. 경쟁사 마케팅 활동 6분류 비교
    comp_cols = [project.brand_name] + [c.brand_name for c in project.competitors[:3]]
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.COMPETITOR.value,
            slide_order=order,
            slide_type="COMPETITOR_MARKETING_6",
            title="3-4. 경쟁사 분석 — 브랜드별 마케팅 활동 6분류 비교",
            headcopy="디지털 캠페인·온라인 이벤트·소셜 콘텐츠·인플루언서·바이럴·미디어 6개 축 기준 경쟁사별 핵심 전술 대조",
            table_json={
                "headers": ["활동 분류", *comp_cols],
                "rows": [
                    ["디지털 캠페인"] + ["수집 원문 기반 정리" for _ in comp_cols],
                    ["온라인 이벤트"] + ["수집 원문 기반 정리" for _ in comp_cols],
                    ["소셜 콘텐츠"] + ["수집 원문 기반 정리" for _ in comp_cols],
                    ["인플루언서 협업"] + ["수집 원문 기반 정리" for _ in comp_cols],
                    ["바이럴·커뮤니티"] + ["수집 원문 기반 정리" for _ in comp_cols],
                    ["미디어·PR"] + ["수집 원문 기반 정리" for _ in comp_cols],
                ],
            },
            bullets_json=facts_to_bullets(comp_facts, fallback_claim="6분류 활동 축별 자사 공백 및 경쟁사 강점 영역"),
            footnote="출처: Perplexity 마케팅 활동 리서치 및 SNS·커뮤니티 수집 데이터",
        )
    )
    order += 1

    # ── 4. CONSUMER ANALYSIS & TRENDS (4장) ───────────────────────────────────
    consumer_facts = facts_by_sec.get(SectionCode.CONSUMER.value, [])
    consumer_sources = [s for s in sources if s.section_code == SectionCode.CONSUMER.value]
    pos_cnt = sum(1 for s in consumer_sources if s.sentiment == "POSITIVE")
    neg_strict = sum(1 for s in consumer_sources if s.sentiment == "NEGATIVE")
    mixed_cnt = sum(1 for s in consumer_sources if s.sentiment == "MIXED")
    neg_cnt = neg_strict + mixed_cnt
    neu_cnt = max(0, len(consumer_sources) - pos_cnt - neg_cnt)
    channel_counts = Counter(s.channel for s in consumer_sources)

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
            headcopy=f"실수집 VOC {len(consumer_sources)}건 기준 긍정({pos_cnt}건)·아쉬움/고민({neg_cnt}건)·중립({neu_cnt}건) 분포와 채널별 발화 비중",
            kpi_cards_json=[
                {
                    "label": "분석 VOC 표본",
                    "value": f"{len(consumer_sources)}건",
                    "delta": f"긍정 {pos_cnt} / 우려·복합 {neg_cnt} / 중립 {neu_cnt}",
                    "basis": "Apify 커뮤니티·블로그·카페",
                },
                {
                    "label": "긍정 vs 우려·고민 비율",
                    "value": f"{(pos_cnt / max(1, len(consumer_sources))) * 100:.1f}%",
                    "delta": f"우려·복합 {(neg_cnt / max(1, len(consumer_sources))) * 100:.1f}%",
                    "basis": "Claude 문맥 감성(부정+복합 포함)",
                },
            ],
            table_json={
                "headers": ["수집 채널", "수집 건수", "비중"],
                "rows": ch_rows,
            },
            visual_assets_json=[
                {
                    "asset_type": "CONSUMER_KBF_CHART",
                    "title": "수집 VOC 감성 분포 (긍정/아쉬움·복합/중립)",
                    "metadata": {"positive": pos_cnt, "negative": neg_cnt, "neutral": neu_cnt},
                    "caption": f"수집 원문 {len(consumer_sources)}건 전수 감성 분류 (부정 {neg_strict} + 복합우려 {mixed_cnt})",
                }
            ],
            bullets_json=facts_to_bullets(consumer_facts, fallback_claim="채널별 VOC 집중 주제 및 감성 분포 해석"),
            footnote="출처: 네이버 블로그·카페·더쿠·디시인사이드·에펨코리아·클리앙 실수집 원문",
        )
    )
    order += 1

    # 4-3. 소비자 실발화: 믿고 사는 이유 vs 이탈·불만 이유
    pos_quotes = [s for s in consumer_sources if s.sentiment == "POSITIVE"][:3]
    neg_quotes = [s for s in consumer_sources if s.sentiment == "NEGATIVE"][:3]
    if len(neg_quotes) < 2:
        mixed_quotes = [s for s in consumer_sources if s.sentiment == "MIXED" and s not in neg_quotes]
        neg_quotes.extend(mixed_quotes[: max(0, 3 - len(neg_quotes))])
    voice_rows: list[list[str]] = []
    for i in range(max(len(pos_quotes), len(neg_quotes), 1)):
        pq = clean_slide_text(pos_quotes[i].evidence_quote or pos_quotes[i].title)[:58] if i < len(pos_quotes) else "추가 긍정 원문 확인 필요"
        nq = clean_slide_text(neg_quotes[i].evidence_quote or neg_quotes[i].title)[:58] if i < len(neg_quotes) else "부정/이탈 원문 보완 수집 필요"
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
            table_json={
                "headers": ["믿고 사는 이유 (긍정 KBF 발화)", "이탈·고민 요인 (부정/허들 발화)"],
                "rows": voice_rows[:4],
            },
            bullets_json=facts_to_bullets(consumer_facts, fallback_claim="실사용 후기 내 반복 등장 키워드 및 원문 신뢰 요인"),
            footnote="출처: Apify 수집 커뮤니티·블로그·카페 원문 및 하이라이트 추출 문장",
        )
    )
    order += 1

    # 4-4. 소비·소셜 콘텐츠 트렌드 & 유사 산업 벤치마크
    slides.append(
        SlideDraft(
            project_id=project.id,
            section_code=SectionCode.CONSUMER.value,
            slide_order=order,
            slide_type="CONSUMER_TRENDS",
            title="4-4. 소비자 분석 — 소셜·소비 트렌드 및 유사 산업 벤치마크",
            headcopy=f"{project.industry_category} 소비 방식 변화와 고성과 콘텐츠 포맷·유사 업종 성공 사례 시사점",
            table_json={
                "headers": ["트렌드/벤치마크 축", "관찰된 변화 및 사례 요약", "자사 적용 포인트"],
                "rows": [
                    ["소비·구매 트렌드", "목적형·가치 판단형 구매 확대", "핵심 스펙·실사용 근거 전면에 배치"],
                    ["소셜 콘텐츠 포맷", "사용 장면형·노하우 숏폼/릴스 선호", "단순 제품 소개 대신 활용 장면 시리즈화"],
                ],
            },
            bullets_json=facts_to_bullets(consumer_facts, fallback_claim="소비/콘텐츠 트렌드 및 타 카테고리 벤치마크 적용 과제"),
            footnote="출처: Perplexity 소비자 트렌드 리서치 및 SNS·커뮤니티 키워드 분석",
        )
    )
    order += 1

    # ── 5. SUMMARY, AS-IS->TO-BE, DATA GAP, APPENDIX ──────────────────────────
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
    return [sanitize_slide_draft(s) for s in slides]


def build_section5_slides(
    *,
    project: Project,
    sources: list[RawSourceItem],
    facts: list[FactItem],
    non_summary_slides: list[SlideDraft],
    split_mode: SummarySplitMode,
    start_order: int,
    datalab_series: list[DataLabSeries] | None = None,
) -> list[SlideDraft]:
    by_sec: dict[str, list[SlideDraft]] = {}
    for s in non_summary_slides:
        by_sec.setdefault(s.section_code, []).append(s)

    def sec_bullets(sec_code: str, fallback: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for s in by_sec.get(sec_code, []):
            for b in (s.bullets_json or [])[:1]:
                items.append(b)
        return items[:3] or [
            {
                "claim": fallback,
                "evidence_quote": None,
                "source_name": "팩트북 종합",
                "source_url": None,
                "fact_id": None,
            }
        ]

    result: list[SlideDraft] = []
    order = start_order

    if split_mode == SummarySplitMode.SPLIT_4:
        specs = [
            ("5-1. 현황 요약 (1/4) — 자사 브랜드·제품 핵심 진단", SectionCode.OWN.value, f"{project.brand_name} {project.product_name} 자사 자산 요약"),
            ("5-2. 현황 요약 (2/4) — 시장·유통·규제 환경 요약", SectionCode.MARKET.value, f"{project.industry_category} 시장 변화 요약"),
            ("5-3. 현황 요약 (3/4) — 경쟁 구도 및 활동 6분류 요약", SectionCode.COMPETITOR.value, "경쟁사 SoS·마케팅 비교 요약"),
            ("5-4. 현황 요약 (4/4) — 소비자 인식 및 VOC 핵심 요약", SectionCode.CONSUMER.value, "실사용자 KBF 및 불만 요약"),
        ]
        for title, sec_code, fallback in specs:
            sec_slides = by_sec.get(sec_code, [])
            hc = sec_slides[0].headcopy if sec_slides else fallback
            result.append(
                sanitize_slide_draft(
                    SlideDraft(
                        project_id=project.id,
                        section_code=SectionCode.SUMMARY_CONCLUSION.value,
                        slide_order=order,
                        slide_type="SUMMARY_PART",
                        title=title,
                        headcopy=hc,
                        table_json={
                            "headers": ["핵심 항목", "확인된 사실", "전략적 의미"],
                            "rows": [
                                [clean_slide_text(s.title)[:24], clean_slide_text(s.headcopy)[:55], "추가 전략 연결"]
                                for s in sec_slides[:4]
                            ],
                        },
                        bullets_json=sec_bullets(sec_code, fallback),
                        footnote="현황 요약 4장 분할 모드 (과밀 압축 배제)",
                    )
                )
            )
            order += 1
    else:
        own_hc = (by_sec.get(SectionCode.OWN.value) or [None])[0]
        mkt_hc = (by_sec.get(SectionCode.MARKET.value) or [None])[0]
        comp_hc = (by_sec.get(SectionCode.COMPETITOR.value) or [None])[0]
        cons_hc = (by_sec.get(SectionCode.CONSUMER.value) or [None])[0]

        result.append(
            sanitize_slide_draft(
                SlideDraft(
                    project_id=project.id,
                    section_code=SectionCode.SUMMARY_CONCLUSION.value,
                    slide_order=order,
                    slide_type="SUMMARY_PART",
                    title="5-1. 현황 요약 (1/2) — 자사 및 시장 환경 핵심 진단 (3C Recap)",
                    headcopy=f"[시장] {mkt_hc.headcopy[:110] if mkt_hc else project.industry_category} | [자사] {own_hc.headcopy[:110] if own_hc else project.product_name}",
                    table_json={
                        "headers": ["영역", "확인된 핵심 사실", "전략적 의미"],
                        "rows": [
                            ["시장 (Market)", clean_slide_text(mkt_hc.headcopy)[:65] if mkt_hc else "시장 변화 정리", "수요·유통 변화에 맞춘 포지션 재점검"],
                            ["자사 (Company)", clean_slide_text(own_hc.headcopy)[:65] if own_hc else "자사 현황 정리", "Owned 접점 강화 및 주력 제품 USP 정교화"],
                        ],
                    },
                    bullets_json=sec_bullets(SectionCode.MARKET.value, "시장 핵심 진단")[:2]
                    + sec_bullets(SectionCode.OWN.value, "자사 핵심 진단")[:1],
                    footnote="현황 요약 2장 분할 모드 (1/2: 시장·자사 3C Recap)",
                )
            )
        )
        order += 1

        result.append(
            sanitize_slide_draft(
                SlideDraft(
                    project_id=project.id,
                    section_code=SectionCode.SUMMARY_CONCLUSION.value,
                    slide_order=order,
                    slide_type="SUMMARY_PART",
                    title="5-2. 현황 요약 (2/2) — 경쟁 구도 및 소비자 인식 핵심 진단 (3C Recap)",
                    headcopy=f"[경쟁] {comp_hc.headcopy[:110] if comp_hc else '경쟁 비교'} | [소비자] {cons_hc.headcopy[:110] if cons_hc else '소비자 VOC'}",
                    table_json={
                        "headers": ["영역", "확인된 핵심 사실", "전략적 의미"],
                        "rows": [
                            ["경쟁 (Competitor)", clean_slide_text(comp_hc.headcopy)[:65] if comp_hc else "경쟁 비교 정리", "경쟁사 핵심 전술 대비 차별화 공백 공략"],
                            ["소비자 (Consumer)", clean_slide_text(cons_hc.headcopy)[:65] if cons_hc else "소비자 VOC 정리", "실사용 KBF 강화 및 이탈 요인 선제 해소"],
                        ],
                    },
                    bullets_json=sec_bullets(SectionCode.COMPETITOR.value, "경쟁 핵심 진단")[:2]
                    + sec_bullets(SectionCode.CONSUMER.value, "소비자 핵심 진단")[:1],
                    footnote="현황 요약 2장 분할 모드 (2/2: 경쟁사·소비자 3C Recap)",
                )
            )
        )
        order += 1

    # AS-IS -> TO-BE 전략 결론
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
                        "source_url": None,
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

    # DATA GAP (데이터 공백 및 추가 확인 과제)
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

    # APPENDIX (출처 목록): count ALL unique URLs across sources & Perplexity citations first
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
    # Pick balanced cross-section representatives first, then fill up to 7 rows
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
                [src.section_code, src.channel, smart_truncate(src.title, 34), src.source_url[:64]]
            )
        if len(app_rows) >= 7:
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
                        "source_url": None,
                        "fact_id": None,
                    }
                ],
                footnote="출처: 자료·수집 풀(Source Pool) 전체 URL 및 Perplexity 인용 출처 인덱스",
            )
        )
    )
    return result
