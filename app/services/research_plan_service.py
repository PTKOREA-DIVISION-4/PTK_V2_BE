from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.project import Project
from app.models.research_plan import ResearchPlan, ResearchPlanItem
from app.repositories.project_repo import ProjectRepository
from app.repositories.research_plan_repo import ResearchPlanRepository
from app.schemas.common import AnalysisTrack, ProjectStage, SectionCode
from app.schemas.research_plan import (
    ResearchPlanItemResponse,
    ResearchPlanResponse,
    ResearchPlanUpdateRequest,
)


REVIEW_CENTRIC_COMMUNITIES = [
    "theqoo",
    "dcinside",
    "fmkorea",
    "naver_blog",
    "naver_cafe",
]

MARKET_CENTRIC_COMMUNITIES = [
    "clien",
    "fmkorea",
    "dcinside",
    "naver_blog",
    "naver_cafe",
]


class ResearchPlanService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ResearchPlanRepository(session)
        self.project_repo = ProjectRepository(session)

    async def create_default_plan_for_project(self, project: Project) -> ResearchPlan:
        track = AnalysisTrack(project.analysis_track)
        communities = (
            list(REVIEW_CENTRIC_COMMUNITIES)
            if track == AnalysisTrack.REVIEW_CENTRIC
            else list(MARKET_CENTRIC_COMMUNITIES)
        )
        datalab_groups = self._build_default_datalab_groups(project)

        plan = ResearchPlan(
            project_id=project.id,
            is_confirmed=False,
            target_communities=communities,
            datalab_groups_config=datalab_groups,
            estimated_duration_seconds=90,
        )
        items_spec = self._build_items_for_track(project, track)
        for idx, spec in enumerate(items_spec):
            plan.items.append(
                ResearchPlanItem(
                    section_code=spec["section_code"],
                    item_key=spec["item_key"],
                    title=spec["title"],
                    description=spec["description"],
                    data_sources=spec["data_sources"],
                    is_enabled=True,
                    display_order=idx,
                )
            )
        await self.repo.save(plan)
        return plan

    async def get_plan(self, project_id: str) -> ResearchPlanResponse:
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")
        plan = await self.repo.get_by_project_id(project_id)
        if not plan:
            plan = await self.create_default_plan_for_project(project)
            await self.session.commit()
            plan = await self.repo.get_by_project_id(project_id)
            assert plan is not None
        return self._to_response(project, plan)

    async def update_plan(
        self, project_id: str, payload: ResearchPlanUpdateRequest
    ) -> ResearchPlanResponse:
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")
        plan = await self.repo.get_by_project_id(project_id)
        if not plan:
            plan = await self.create_default_plan_for_project(project)

        plan.is_confirmed = payload.is_confirmed
        if payload.target_communities is not None:
            plan.target_communities = payload.target_communities
        if payload.datalab_groups_config is not None:
            plan.datalab_groups_config = payload.datalab_groups_config

        toggle_map = {t.item_key: t.is_enabled for t in payload.items}
        enabled_count = 0
        for item in plan.items:
            if item.item_key in toggle_map:
                item.is_enabled = toggle_map[item.item_key]
            if item.is_enabled:
                enabled_count += 1

        plan.estimated_duration_seconds = max(30, enabled_count * 12)
        if payload.is_confirmed and project.current_stage == ProjectStage.PLAN.value:
            project.current_stage = ProjectStage.COLLECT.value

        await self.session.commit()
        fresh = await self.repo.get_by_project_id(project_id)
        assert fresh is not None
        return self._to_response(project, fresh)

    @staticmethod
    def _build_default_datalab_groups(project: Project) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = [
            {
                "groupName": f"{project.brand_name} {project.product_name}",
                "ownerType": "OWN",
                "keywords": list(
                    dict.fromkeys([project.brand_name, f"{project.brand_name} {project.product_name}"])
                ),
            }
        ]
        for comp in project.competitors[:4]:
            groups.append(
                {
                    "groupName": f"{comp.brand_name} {comp.product_name}",
                    "ownerType": "COMPETITOR",
                    "keywords": list(
                        dict.fromkeys([
                            comp.brand_name,
                            f"{comp.brand_name} {project.product_name}",
                            f"{comp.brand_name} {comp.product_name}",
                        ])
                    ),
                }
            )
        return groups

    @staticmethod
    def _build_items_for_track(
        project: Project, track: AnalysisTrack
    ) -> list[dict[str, Any]]:
        is_review = track == AnalysisTrack.REVIEW_CENTRIC
        return [
            {
                "section_code": SectionCode.OVERVIEW.value,
                "item_key": "overview_scope_definition",
                "title": "0. 분석 개요 및 단일 브랜드·제품 범위 정의",
                "description": (
                    f"{project.brand_name} '{project.product_name}' 단일 기준점, 경쟁군, 분석 기간 및 채널별 수집 모수 요약"
                ),
                "data_sources": ["project_meta"],
            },
            {
                "section_code": SectionCode.OWN.value,
                "item_key": "own_brand_product_profile",
                "title": "1-1. 자사 브랜드·주력 제품 프로필 및 최근 이슈",
                "description": "공식 제품 USP, 가격·유통 포지션, 최근 리뉴얼/캠페인 히스토리 조사",
                "data_sources": ["perplexity", "anthropic"],
            },
            {
                "section_code": SectionCode.OWN.value,
                "item_key": "own_datalab_interest",
                "title": "1-2. 자사 네이버 데이터랩 검색·쇼핑 관심도 추이",
                "description": (
                    "검색어 트렌드 + 쇼핑 인사이트 클릭 추이 및 변곡점 분석"
                    if is_review
                    else "검색어 트렌드(정보 탐색 추이) 및 시즌 피크 구간 분석"
                ),
                "data_sources": ["naver_datalab"],
            },
            {
                "section_code": SectionCode.OWN.value,
                "item_key": "own_sns_top5_and_collab",
                "title": "1-3. 자사 공식 SNS 지표 & 기간 내 인기 게시물 TOP 5",
                "description": "자사 계정 팔로워/조회·반응 지표, 기간 내 인기 게시물 TOP 5 및 크리에이터 협업 콘텐츠 추출",
                "data_sources": ["scrapecreators", "apify"],
            },
            {
                "section_code": SectionCode.MARKET.value,
                "item_key": "market_macro_and_regulation",
                "title": "2. 거시 시장 규모·성장 동력 및 정책·규제 환경",
                "description": (
                    "카테고리 시장 규모, 유통 채널 변화, 표시·광고/성분 규제 이슈"
                    if is_review
                    else "거시 산업 지표, 법규·정책/제도 변화, 기술·서비스 패러다임 전환"
                ),
                "data_sources": ["perplexity", "naver_datalab", "anthropic"],
            },
            {
                "section_code": SectionCode.COMPETITOR.value,
                "item_key": "competitor_matrix_and_sos",
                "title": "3-1. 경쟁 제품 비교 매트릭스 & 검색 점유율(Share of Search)",
                "description": "경쟁 브랜드·제품 스펙/가격/메시지 대조 및 네이버 데이터랩 기반 경쟁사 대비 검색 점유율(%) 산출",
                "data_sources": ["perplexity", "naver_datalab"],
            },
            {
                "section_code": SectionCode.COMPETITOR.value,
                "item_key": "competitor_sns_top5",
                "title": "3-2. 경쟁사 SNS 인기 게시물 TOP 5 & 크리에이터 레퍼런스",
                "description": "경쟁사 공식 채널 고성과 콘텐츠 TOP 5, 영상 주요 장면 스크린샷 및 크리에이터 시딩 전략 비교",
                "data_sources": ["scrapecreators", "apify"],
            },
            {
                "section_code": SectionCode.CONSUMER.value,
                "item_key": "consumer_voc_and_kbf",
                "title": "4. 커뮤니티·블로그·리뷰 실소비자 VOC 및 KBF 분석",
                "description": (
                    "더쿠·디시·펨코·블로그·카페·리뷰 기반 구매 결정 요인(KBF), 장단점 비중 및 원문 근거 발화 추출"
                    if is_review
                    else "클리앙·펨코·디시·블로그·카페 기반 고객 여정 장벽(Barrier), 신뢰·전환 트리거 및 원문 근거 발화 추출"
                ),
                "data_sources": ["apify", "anthropic"],
            },
            {
                "section_code": SectionCode.SUMMARY_CONCLUSION.value,
                "item_key": "summary_split_and_asis_tobe",
                "title": "5. 현황 요약(2장/4장 분할) 및 결론·과제 방향(AS-IS → TO-BE)",
                "description": "검증된 1~4장 팩트를 2장 또는 4장으로 분할 요약하고 AS-IS → 핵심 과제 → TO-BE 전략 방향 도출",
                "data_sources": ["anthropic"],
            },
        ]

    @staticmethod
    def _to_response(project: Project, plan: ResearchPlan) -> ResearchPlanResponse:
        return ResearchPlanResponse(
            id=plan.id,
            project_id=project.id,
            analysis_track=AnalysisTrack(project.analysis_track),
            is_confirmed=plan.is_confirmed,
            target_communities=list(plan.target_communities or []),
            datalab_groups_config=list(plan.datalab_groups_config or []),
            estimated_duration_seconds=plan.estimated_duration_seconds,
            items=[
                ResearchPlanItemResponse(
                    id=item.id,
                    section_code=SectionCode(item.section_code),
                    item_key=item.item_key,
                    title=item.title,
                    description=item.description,
                    data_sources=list(item.data_sources or []),
                    is_enabled=item.is_enabled,
                    display_order=item.display_order,
                )
                for item in plan.items
            ],
        )
