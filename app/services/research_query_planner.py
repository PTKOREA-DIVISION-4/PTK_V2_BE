from __future__ import annotations

from dataclasses import dataclass

from app.models.project import Project
from app.schemas.common import SectionCode


@dataclass(frozen=True)
class ResearchQuerySpec:
    section_code: str
    title: str
    prompt: str


def build_perplexity_queries(project: Project) -> list[ResearchQuerySpec]:
    """Constructs 8 focused research queries covering Market, Own Brand, Competitors (Price & 6-Category Marketing), and Consumer/Benchmarks."""
    brand = project.brand_name
    product = project.product_name
    industry = project.industry_category
    period = f"{project.period_start.isoformat()} ~ {project.period_end.isoformat()}"
    comp_list = [f"{c.brand_name} {c.product_name}".strip() for c in project.competitors]
    comp_brands = [c.brand_name for c in project.competitors]
    comp_str = ", ".join(comp_list) or "주요 직접 경쟁 브랜드"
    comp_brands_str = ", ".join(comp_brands) or "주요 경쟁 브랜드"

    return [
        ResearchQuerySpec(
            section_code=SectionCode.MARKET.value,
            title=f"{industry}({product}) 글로벌·국내 시장 규모 및 거시 수요 추이",
            prompt=(
                f"조사 기준일({period}) 기준으로 '{industry}' 산업의 '{product}' 카테고리 관련 "
                "글로벌 시장 규모(리서치 기관명·연도·성장률 CAGR 포함), 한국 국내 수요·소비 통계, "
                "최근 1~2년 시장 성장/정체 요인을 확인 가능한 수치와 출처 중심으로 정리해줘. "
                "확인되지 않는 수치는 추측하지 말고 미확인으로 표기해줘."
            ),
        ),
        ResearchQuerySpec(
            section_code=SectionCode.MARKET.value,
            title=f"국내 {product} 카테고리 신호·가격 양극화·유통 변화 및 플레이어 지형",
            prompt=(
                f"한국 '{industry}' 내 '{product}' 시장의 최근 카테고리 신호(객단가·주문 증가 구간·온라인/홈쇼핑/자사몰 유통 변화), "
                f"가격 양극화 양상, 그리고 국내 주요 플레이어 유형({brand}, {comp_brands_str} 각각의 운영사·포지셔닝·매출/성장 지표·주력 유통채널)과 "
                "관련 법규·표시광고·규제 포인트를 출처와 함께 정리해줘."
            ),
        ),
        ResearchQuerySpec(
            section_code=SectionCode.OWN.value,
            title=f"{brand}({product}) 기업 실적·주력/신제품 라인업 및 공식몰 가격·할인 구조",
            prompt=(
                f"'{brand}'(한국 법인/글로벌 그룹 포함)의 최근 실적(매출·영업이익·성장률), "
                f"'{product}' 주력/신제품 라인업(출시일·핵심 소재/기능 USP), 그리고 공식몰 정가 vs 행사가(할인율·주력 가격대)를 "
                "구체적 수치·모델명·출처 URL과 함께 정리해줘."
            ),
        ),
        ResearchQuerySpec(
            section_code=SectionCode.OWN.value,
            title=f"{brand} {product} 최근 언론 보도 동향·대표 캠페인·팝업/협업 성과",
            prompt=(
                f"{period} 기간 중심으로 '{brand}'의 '{product}' 관련 주요 언론 보도 이슈(신제품 출시·팝업·체험·협업·IR/실적), "
                "대표 캠페인/팝업 사례와 진행 방식·성과, 크리에이터 시딩 및 브랜드 커뮤니케이션 포지셔닝을 출처와 함께 정리해줘."
            ),
        ),
        ResearchQuerySpec(
            section_code=SectionCode.COMPETITOR.value,
            title=f"{brand} vs 경쟁 {comp_brands_str} 대표 {product} 라인업·가격 포지션·유통 채널 비교",
            prompt=(
                f"한국 '{product}' 시장에서 '{brand}'와 경쟁 브랜드 각각({comp_str})의 "
                "운영사, 브랜드 포지셔닝, 대표/인기 제품 모델별 공식 판매가·할인가(규격·인치/용량 기준 가격대), 주력 유통 채널(자사몰·백화점·홈쇼핑·창고형 할인점·온라인몰 등)을 "
                "특정 단일 SKU 가격만 없을 경우 해당 브랜드의 주력 동급 제품 가격 범위까지 포함해 출처와 함께 정확히 정리해줘."
            ),
        ),
        ResearchQuerySpec(
            section_code=SectionCode.COMPETITOR.value,
            title=f"{brand} vs 경쟁 {comp_brands_str} 마케팅 활동 6분류(캠페인·이벤트·소셜·협업·바이럴·PR) 심층 조사",
            prompt=(
                f"한국 시장에서 {brand} 및 각 경쟁 브랜드({comp_brands_str})가 '{product}' 카테고리에서 전개한 마케팅 활동을 "
                "브랜드별로 6가지 분류(1.디지털 캠페인·모델 기용, 2.온라인 프로모션·이벤트·라이브커머스, 3.공식 소셜 콘텐츠, "
                "4.인플루언서·크리에이터 협업, 5.바이럴·커뮤니티 화제, 6.언론·미디어 PR)로 나누어 확인 가능한 실제 사례와 출처 URL 중심으로 정리해줘. "
                "개별 브랜드가 해당 영역에서 확인되지 않으면 '확인 불가'로 구분해줘."
            ),
        ),
        ResearchQuerySpec(
            section_code=SectionCode.CONSUMER.value,
            title=f"{brand} {product} 핵심 타깃·구매 기준(KBF) 및 선택/이탈 요인",
            prompt=(
                f"한국 '{product}' 시장의 핵심 타깃 세그먼트(연령·구매 목적·이용 상황별 요구 스펙), "
                f"소비자가 '{brand}'를 선택하는 이유(KBF) vs 경쟁사로 이탈하거나 구매를 망설이는 불만/허들 요인(가격·무게·디자인·소재·AS·보증 등)을 출처와 함께 정리해줘."
            ),
        ),
        ResearchQuerySpec(
            section_code=SectionCode.CONSUMER.value,
            title=f"{industry}({product}) 소셜·소비 트렌드 및 타 카테고리 성공 캠페인 벤치마크",
            prompt=(
                f"{period} 기준 '{industry}'·'{product}' 시장의 최근 소비 트렌드(프리미엄화·미니멀리즘·실사용 검증·로컬 컬렉션 등), "
                "유튜브/인스타그램/라이브커머스 고성과 콘텐츠 포맷, 그리고 국내 타 소비재/라이프스타일 브랜드의 성공적인 SNS·협업·팝업 벤치마크 사례를 출처와 함께 정리해줘."
            ),
        ),
    ]
