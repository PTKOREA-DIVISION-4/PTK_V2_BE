from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.models.base import generate_uuid
from app.models.project import CompetitorTarget, KeywordGroup, Project, SnsAccount
from app.repositories.project_repo import ProjectRepository
from app.repositories.research_plan_repo import ResearchPlanRepository
from app.repositories.slide_draft_repo import SlideDraftRepository
from app.repositories.source_item_repo import SourceItemRepository
from app.schemas.common import (
    AnalysisTrack,
    KeywordGroupType,
    ProjectStage,
    SectionCode,
    SummarySplitMode,
    WorkflowMeta,
)
from app.schemas.project import (
    KeywordGroupInput,
    KeywordRecommendRequest,
    KeywordRecommendResponse,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectSummaryResponse,
    ProjectUpdateRequest,
    detect_sns_platform,
    extract_handle_from_url,
)
from app.services.research_plan_service import ResearchPlanService


REVIEW_CENTRIC_KEYWORDS = (
    "뷰티",
    "화장품",
    "코스메틱",
    "스킨케어",
    "f&b",
    "식품",
    "음료",
    "패션",
    "의류",
    "생활용품",
    "건기식",
    "건강기능",
    "소형가전",
    "리빙",
)

SHOPPING_CATEGORY_MAP = {
    "뷰티": "50000002",
    "화장품": "50000002",
    "패션잡화": "50000001",
    "잡화": "50000001",
    "캐리어": "50000001",
    "패션": "50000000",
    "식품": "50000006",
    "음료": "50000006",
    "생활": "50000008",
    "가전": "50000003",
    "디지털": "50000003",
    "건강": "50000006",
}


def resolve_analysis_track(
    industry_category: str, explicit_track: AnalysisTrack | None = None
) -> AnalysisTrack:
    if explicit_track is not None:
        return explicit_track
    lower = industry_category.lower()
    if any(kw in lower for kw in REVIEW_CENTRIC_KEYWORDS):
        return AnalysisTrack.REVIEW_CENTRIC
    return AnalysisTrack.MARKET_CENTRIC


def guess_shopping_category_id(industry_category: str) -> str:
    lower = industry_category.lower()
    for key, cat_id in SHOPPING_CATEGORY_MAP.items():
        if key in lower:
            return cat_id
    return get_settings().DEFAULT_NAVER_SHOPPING_CATEGORY_ID


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ProjectRepository(session)
        self.plan_repo = ResearchPlanRepository(session)
        self.source_repo = SourceItemRepository(session)
        self.slide_repo = SlideDraftRepository(session)
        self.plan_service = ResearchPlanService(session)

    async def create_project(self, payload: ProjectCreateRequest) -> ProjectResponse:
        track = resolve_analysis_track(payload.industry_category, payload.analysis_track)
        shopping_cat = payload.naver_shopping_category_id or guess_shopping_category_id(
            payload.industry_category
        )

        project_id = generate_uuid()
        project = Project(
            id=project_id,
            name=payload.name.strip(),
            brand_name=payload.brand_name.strip(),
            product_name=payload.product_name.strip(),
            industry_category=payload.industry_category.strip(),
            analysis_track=track.value,
            period_start=payload.period_start,
            period_end=payload.period_end,
            current_stage=ProjectStage.PLAN.value,
            summary_split_mode=SummarySplitMode.SPLIT_2.value,
            naver_shopping_category_id=shopping_cat,
        )

        comp_id_by_brand: dict[str, str] = {}
        for idx, comp in enumerate(payload.competitors):
            comp_id = generate_uuid()
            brand = comp.brand_name.strip()
            comp_id_by_brand[brand] = comp_id
            project.competitors.append(
                CompetitorTarget(
                    id=comp_id,
                    project_id=project_id,
                    brand_name=brand,
                    product_name=comp.product_name.strip(),
                    display_order=idx,
                )
            )

        for acc in payload.sns_accounts:
            platform = acc.platform or detect_sns_platform(acc.account_url)
            handle = acc.handle or extract_handle_from_url(acc.account_url)
            comp_id = (
                comp_id_by_brand.get(acc.brand_label)
                if acc.owner_type.value == "COMPETITOR"
                else None
            )
            project.sns_accounts.append(
                SnsAccount(
                    project_id=project_id,
                    owner_type=acc.owner_type.value,
                    competitor_id=comp_id,
                    brand_label=acc.brand_label.strip(),
                    platform=platform.value,
                    account_url=acc.account_url,
                    handle=handle,
                )
            )

        keyword_groups = list(payload.keyword_groups)
        if not keyword_groups:
            keyword_groups = self._default_keyword_groups(payload)

        for kg in keyword_groups:
            project.keyword_groups.append(
                KeywordGroup(
                    project_id=project_id,
                    group_type=kg.group_type.value,
                    label=kg.label.strip(),
                    keywords=list(dict.fromkeys(k.strip() for k in kg.keywords if k.strip())),
                    hashtags=list(dict.fromkeys(h.strip() for h in kg.hashtags if h.strip())),
                )
            )

        await self.repo.create(project)
        await self.plan_service.create_default_plan_for_project(project)
        await self.session.commit()

        fresh = await self.repo.get_by_id(project.id)
        assert fresh is not None
        return self.to_response(fresh)

    async def list_projects(self) -> list[ProjectResponse]:
        rows = await self.repo.list_all()
        return [self.to_response(r) for r in rows]

    async def get_project(self, project_id: str) -> Project:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")
        return project

    async def get_project_response(self, project_id: str) -> ProjectResponse:
        return self.to_response(await self.get_project(project_id))

    async def update_project(
        self, project_id: str, payload: ProjectUpdateRequest
    ) -> ProjectResponse:
        project = await self.get_project(project_id)
        if payload.name is not None:
            project.name = payload.name.strip()
        if payload.industry_category is not None:
            project.industry_category = payload.industry_category.strip()
            if payload.analysis_track is None:
                project.analysis_track = resolve_analysis_track(
                    payload.industry_category
                ).value
        if payload.analysis_track is not None:
            project.analysis_track = payload.analysis_track.value
        if payload.period_start is not None:
            project.period_start = payload.period_start
        if payload.period_end is not None:
            project.period_end = payload.period_end
        if payload.naver_shopping_category_id is not None:
            project.naver_shopping_category_id = payload.naver_shopping_category_id

        competitors_models = None
        if payload.competitors is not None:
            competitors_models = [
                CompetitorTarget(
                    project_id=project.id,
                    brand_name=c.brand_name.strip(),
                    product_name=c.product_name.strip(),
                    display_order=idx,
                )
                for idx, c in enumerate(payload.competitors)
            ]

        sns_models = None
        if payload.sns_accounts is not None:
            sns_models = [
                SnsAccount(
                    project_id=project.id,
                    owner_type=s.owner_type.value,
                    brand_label=s.brand_label.strip(),
                    platform=(s.platform or detect_sns_platform(s.account_url)).value,
                    account_url=s.account_url,
                    handle=s.handle or extract_handle_from_url(s.account_url),
                )
                for s in payload.sns_accounts
            ]

        kw_models = None
        if payload.keyword_groups is not None:
            kw_models = [
                KeywordGroup(
                    project_id=project.id,
                    group_type=kg.group_type.value,
                    label=kg.label.strip(),
                    keywords=kg.keywords,
                    hashtags=kg.hashtags,
                )
                for kg in payload.keyword_groups
            ]

        await self.repo.replace_children(
            project,
            competitors=competitors_models,
            sns_accounts=sns_models,
            keyword_groups=kw_models,
        )
        await self.session.commit()
        return self.to_response(await self.get_project(project_id))

    async def delete_project(self, project_id: str) -> None:
        project = await self.get_project(project_id)
        await self.repo.delete(project)
        await self.session.commit()

    async def get_workflow_meta(self, project: Project) -> WorkflowMeta:
        plan = await self.plan_repo.get_by_project_id(project.id)
        facets = await self.source_repo.get_facets(project.id)
        slides = await self.slide_repo.list_by_project(project.id)

        by_status = facets.get("by_review_status", {})
        pending_sources = int(by_status.get("PENDING", 0))
        approved_sources = int(by_status.get("APPROVED", 0))
        rejected_sources = int(by_status.get("REJECTED", 0))
        total_sources = int(facets.get("total", 0))

        present_sections = {s.section_code for s in slides}
        missing = [sec for sec in SectionCode if sec.value not in present_sections]
        unreviewed_slides = sum(1 for s in slides if s.review_status == "NEEDS_REVIEW")
        has_empty = any(not (s.headcopy or "").strip() for s in slides)
        can_export = bool(slides) and len(missing) == 0 and not has_empty

        if not (plan and plan.is_confirmed):
            hint = "0~5장 조사 항목과 수집 대상 커뮤니티를 확정한 뒤 자료 수집을 시작해 주세요."
        elif total_sources == 0:
            hint = "확정된 조사 계획을 바탕으로 다중 소스 자료 수집을 실행해 주세요."
        elif total_sources > 0 and approved_sources == 0 and len(slides) == 0:
            hint = "수집된 원문과 근거 문장을 검토하고 일괄 채택/제외를 완료해 주세요."
        elif len(slides) == 0:
            hint = "채택된 자료를 기반으로 0~5장 팩트북 장표 초안을 생성해 주세요."
        elif missing or has_empty:
            hint = f"누락 섹션({len(missing)}개)을 보완해야 PPTX 출력이 가능합니다."
        elif unreviewed_slides > 0:
            hint = f"미검토 장표 {unreviewed_slides}건을 확인하고 기획자 코멘트를 반영해 주세요."
        else:
            hint = "사전 QC 검증을 실행하고 완성된 팩트북 PPTX를 다운로드할 수 있습니다."

        return WorkflowMeta(
            current_stage=ProjectStage(project.current_stage),
            plan_confirmed=bool(plan and plan.is_confirmed),
            total_sources_count=total_sources,
            pending_sources_count=pending_sources,
            approved_sources_count=approved_sources,
            rejected_sources_count=rejected_sources,
            total_slides_count=len(slides),
            unreviewed_slides_count=unreviewed_slides,
            missing_sections=missing,
            can_export=can_export,
            next_step_hint=hint,
        )

    async def get_project_summary(self, project_id: str) -> ProjectSummaryResponse:
        project = await self.get_project(project_id)
        meta = await self.get_workflow_meta(project)
        return ProjectSummaryResponse(
            project=self.to_response(project),
            workflow_meta=meta,
            api_readiness=get_settings().api_key_readiness(),
        )

    @staticmethod
    def recommend_keywords(payload: KeywordRecommendRequest) -> KeywordRecommendResponse:
        track = resolve_analysis_track(payload.industry_category)
        cat_id = guess_shopping_category_id(payload.industry_category)
        brand = payload.brand_name.strip()
        product = payload.product_name.strip()

        own_group = KeywordGroupInput(
            group_type=KeywordGroupType.OWN,
            label=f"{brand} {product}",
            keywords=[brand, product, f"{brand} {product}", f"{product} 후기"],
            hashtags=[f"#{brand.replace(' ', '')}", f"#{product.replace(' ', '')}"],
        )
        comp_kws = [c.strip() for c in payload.competitor_brands if c.strip()]
        comp_group = KeywordGroupInput(
            group_type=KeywordGroupType.COMPETITOR,
            label="경쟁사 비교 키워드",
            keywords=comp_kws + [f"{c} 비교" for c in comp_kws],
            hashtags=[f"#{c.replace(' ', '')}" for c in comp_kws],
        )
        ind_group = KeywordGroupInput(
            group_type=KeywordGroupType.INDUSTRY,
            label=f"{payload.industry_category} 시장 키워드",
            keywords=[payload.industry_category, f"{payload.industry_category} 추천", f"{payload.industry_category} 트렌드"],
            hashtags=[f"#{payload.industry_category.replace('/', '').replace(' ', '')}"],
        )
        return KeywordRecommendResponse(
            recommended_groups=[own_group, comp_group, ind_group],
            suggested_naver_shopping_category_id=cat_id,
            suggested_analysis_track=track,
        )

    @staticmethod
    def _default_keyword_groups(payload: ProjectCreateRequest) -> list[KeywordGroupInput]:
        comp_brands = [c.brand_name for c in payload.competitors]
        rec = ProjectService.recommend_keywords(
            KeywordRecommendRequest(
                brand_name=payload.brand_name,
                product_name=payload.product_name,
                industry_category=payload.industry_category,
                competitor_brands=comp_brands,
            )
        )
        return rec.recommended_groups

    @staticmethod
    def to_response(project: Project) -> ProjectResponse:
        return ProjectResponse.model_validate(
            {
                "id": project.id,
                "name": project.name,
                "brand_name": project.brand_name,
                "product_name": project.product_name,
                "industry_category": project.industry_category,
                "analysis_track": project.analysis_track,
                "period_start": project.period_start,
                "period_end": project.period_end,
                "current_stage": project.current_stage,
                "summary_split_mode": project.summary_split_mode,
                "naver_shopping_category_id": project.naver_shopping_category_id,
                "competitors": [
                    {
                        "id": c.id,
                        "brand_name": c.brand_name,
                        "product_name": c.product_name,
                        "display_order": c.display_order,
                    }
                    for c in project.competitors
                ],
                "sns_accounts": [
                    {
                        "id": s.id,
                        "owner_type": s.owner_type,
                        "competitor_id": s.competitor_id,
                        "brand_label": s.brand_label,
                        "platform": s.platform,
                        "account_url": s.account_url,
                        "handle": s.handle,
                    }
                    for s in project.sns_accounts
                ],
                "keyword_groups": [
                    {
                        "id": kg.id,
                        "group_type": kg.group_type,
                        "label": kg.label,
                        "keywords": list(kg.keywords or []),
                        "hashtags": list(kg.hashtags or []),
                    }
                    for kg in project.keyword_groups
                ],
                "created_at": project.created_at,
                "updated_at": project.updated_at,
            }
        )
