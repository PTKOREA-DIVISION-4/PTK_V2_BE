from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from pptx import Presentation

from app.integrations.media_downloader import MediaDownloader
from app.models.collection import DataLabSeries, MediaAsset, RawSourceItem, SnsTopPost
from app.models.factbook import SlideDraft
from app.models.project import CompetitorTarget, Project
from app.schemas.common import QcSeverity, SectionCode, SummarySplitMode
from app.services.llm_structuring_service import LlmStructuringService
from app.services.ppt_renderer.renderer import PPTXRenderer
from app.services.qc_service import QcService


@pytest.mark.asyncio
async def test_qc_blocks_incomplete_two_slide_and_empty_decks(test_session_factory) -> None:
    async with test_session_factory() as session:
        proj = Project(
            name="테스트 프로젝트",
            brand_name="테스트브랜드",
            product_name="히어로제품",
            industry_category="뷰티/화장품",
            analysis_track="REVIEW_CENTRIC",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 11, 25),
        )
        session.add(proj)
        await session.flush()

        # Simulate fatal bug: only 2 slides generated, one with empty headcopy
        session.add_all(
            [
                SlideDraft(
                    project_id=proj.id,
                    section_code=SectionCode.OVERVIEW.value,
                    slide_order=1,
                    slide_type="OVERVIEW",
                    title="0. 개요",
                    headcopy="요약 헤드카피",
                    bullets_json=[{"claim": "내용"}],
                ),
                SlideDraft(
                    project_id=proj.id,
                    section_code=SectionCode.OWN.value,
                    slide_order=2,
                    slide_type="OWN_PROFILE",
                    title="1. 자사",
                    headcopy="",
                    bullets_json=[],
                ),
            ]
        )
        await session.commit()

        report = await QcService(session).evaluate_project(proj.id)
        assert report.can_export is False
        assert report.overall_status == QcSeverity.BLOCKER
        gate_codes = {c.gate_code for c in report.checks if c.severity == QcSeverity.BLOCKER}
        assert "REQUIRED_SECTIONS" in gate_codes
        assert "NO_EMPTY_SLIDES" in gate_codes
        assert SectionCode.CONSUMER in report.missing_sections


@pytest.mark.asyncio
async def test_qc_passes_and_pptx_renders_all_standard_sections(
    test_session_factory, tmp_path: Path
) -> None:
    async with test_session_factory() as session:
        proj = Project(
            name="설화수 윤조에센스 팩트북",
            brand_name="설화수",
            product_name="윤조에센스 6세대",
            industry_category="뷰티/화장품",
            analysis_track="REVIEW_CENTRIC",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 11, 25),
            summary_split_mode=SummarySplitMode.SPLIT_2.value,
        )
        session.add(proj)
        await session.flush()
        session.add(
            CompetitorTarget(
                project_id=proj.id,
                brand_name="라네즈",
                product_name="워터뱅크 크림",
                display_order=0,
            )
        )

        # Create realistic media thumbnail on disk
        downloader = MediaDownloader(media_root=tmp_path / "media")
        card = downloader.create_placeholder_card(
            project_id=proj.id,
            filename="own_top1.png",
            title="설화수 Instagram TOP 1",
            subtitle="좋아요 12,400 / 댓글 320",
        )
        asset = MediaAsset(
            project_id=proj.id,
            asset_type="SNS_THUMBNAIL",
            local_path=card["local_path"],
            caption="설화수 TOP 1",
            width=card["width"],
            height=card["height"],
            is_valid=True,
        )
        session.add(asset)
        await session.flush()

        session.add_all(
            [
                RawSourceItem(
                    project_id=proj.id,
                    section_code=SectionCode.OWN.value,
                    provider="PERPLEXITY",
                    channel="perplexity_research",
                    title="설화수 윤조에센스 6세대 포지셔닝",
                    content="윤조에센스 6세대는 세안 후 첫 단계에 사용하는 퍼스트 에센스로 피부 장벽 개선을 강조합니다.",
                    source_url="https://example.com/own",
                    evidence_quote="세안 후 첫 단계에 사용하는 퍼스트 에센스로 피부 장벽 개선을 강조합니다.",
                    review_status="APPROVED",
                ),
                RawSourceItem(
                    project_id=proj.id,
                    section_code=SectionCode.MARKET.value,
                    provider="PERPLEXITY",
                    channel="perplexity_research",
                    title="국내 기능성 스킨케어 시장 동향",
                    content="국내 안티에이징 스킨케어 시장은 고기능 성분과 실사용 후기 중심으로 재편되고 있습니다.",
                    source_url="https://example.com/market",
                    evidence_quote="국내 안티에이징 스킨케어 시장은 고기능 성분과 실사용 후기 중심으로 재편되고 있습니다.",
                    review_status="APPROVED",
                ),
                RawSourceItem(
                    project_id=proj.id,
                    section_code=SectionCode.COMPETITOR.value,
                    provider="PERPLEXITY",
                    channel="perplexity_research",
                    title="라네즈 워터뱅크 비교",
                    content="라네즈 워터뱅크는 2030 수분 장벽 타겟으로 가벼운 텍스처를 소구합니다.",
                    source_url="https://example.com/comp",
                    evidence_quote="라네즈 워터뱅크는 2030 수분 장벽 타겟으로 가벼운 텍스처를 소구합니다.",
                    review_status="APPROVED",
                ),
                RawSourceItem(
                    project_id=proj.id,
                    section_code=SectionCode.CONSUMER.value,
                    provider="APIFY",
                    channel="theqoo",
                    title="더쿠 윤조에센스 실사용 후기",
                    content="환절기에 속건조 잡히는 느낌이 확실하고 다음 단계 크림 흡수가 잘 됩니다.",
                    source_url="https://theqoo.net/beauty/123",
                    evidence_quote="환절기에 속건조 잡히는 느낌이 확실하고 다음 단계 크림 흡수가 잘 됩니다.",
                    sentiment="POSITIVE",
                    review_status="APPROVED",
                ),
            ]
        )

        session.add_all(
            [
                DataLabSeries(
                    project_id=proj.id,
                    metric_type="SEARCH_TREND",
                    group_label="설화수 윤조에센스",
                    owner_type="OWN",
                    period_start=date(2026, 9, 1),
                    period_end=date(2026, 11, 25),
                    time_unit="week",
                    points_json=[
                        {"period": "2026-09-01", "ratio": 65.0},
                        {"period": "2026-10-01", "ratio": 85.0},
                        {"period": "2026-11-01", "ratio": 100.0},
                    ],
                    cumulative_index_sum=250.0,
                    share_of_search_pct=62.5,
                    growth_rate_pct=35.2,
                    peak_date="2026-11-01",
                    peak_value=100.0,
                    methodology_note="출처: 네이버 데이터랩 | 기간: 2026-09-01~2026-11-25 | 기준: 비교군 최댓값=100",
                ),
                DataLabSeries(
                    project_id=proj.id,
                    metric_type="SEARCH_TREND",
                    group_label="라네즈 워터뱅크",
                    owner_type="COMPETITOR",
                    period_start=date(2026, 9, 1),
                    period_end=date(2026, 11, 25),
                    time_unit="week",
                    points_json=[
                        {"period": "2026-09-01", "ratio": 55.0},
                        {"period": "2026-10-01", "ratio": 50.0},
                        {"period": "2026-11-01", "ratio": 45.0},
                    ],
                    cumulative_index_sum=150.0,
                    share_of_search_pct=37.5,
                    growth_rate_pct=-12.0,
                    peak_date="2026-09-01",
                    peak_value=55.0,
                    methodology_note="출처: 네이버 데이터랩 | 기간: 2026-09-01~2026-11-25 | 기준: 비교군 최댓값=100",
                ),
            ]
        )

        session.add(
            SnsTopPost(
                project_id=proj.id,
                owner_type="OWN",
                brand_label="설화수",
                platform="INSTAGRAM",
                post_url="https://instagram.com/p/top1",
                caption="윤조에센스 6세대 리추얼 캠페인",
                published_at=datetime(2026, 10, 15, 12, 0),
                views=54000,
                likes=12400,
                comments=320,
                engagement_score=18760.0,
                rank_order=1,
                is_creator_collab=False,
                media_asset_id=asset.id,
                key_takeaway="조회 54,000 / 좋아요 12,400",
            )
        )
        await session.commit()

        slides = await LlmStructuringService(session).generate_slides(
            proj.id, summary_split_mode=SummarySplitMode.SPLIT_2
        )
        assert len(slides) >= 9  # 0 + 1(2) + 2 + 3(2) + 4 + 5(2 summary + 1 conclusion)

        qc = await QcService(session).evaluate_project(proj.id)
        assert qc.can_export is True
        assert qc.overall_status == QcSeverity.PASS

        out_pptx = tmp_path / "factbook.pptx"
        datalab_rows = (
            await session.execute(
                DataLabSeries.__table__.select().where(DataLabSeries.project_id == proj.id)
            )
        ).all()
        # Use ORM list directly
        from app.repositories.source_item_repo import SourceItemRepository

        dl_entities = await SourceItemRepository(session).list_datalab(proj.id)
        rendered = PPTXRenderer().render(
            project=proj, slides=slides, datalab_series=dl_entities, output_path=out_pptx
        )
        assert rendered == len(slides) + 1  # cover + body slides
        assert out_pptx.exists()

        prs = Presentation(str(out_pptx))
        assert len(prs.slides) == len(slides) + 1
        all_texts = "\n".join(
            shape.text
            for s in prs.slides
            for shape in s.shapes
            if getattr(shape, "has_text_frame", False)
        )
        for required_marker in [
            "0. 분석 개요",
            "1. 자사 분석",
            "2. 시장 분석",
            "3. 경쟁사 분석",
            "4. 소비자 분석",
            "5-1. 현황 요약",
            "AS-IS",
            "TO-BE",
        ]:
            assert required_marker in all_texts
