from __future__ import annotations

from datetime import date
import pytest

from app.integrations.media_downloader import MediaDownloader
from app.integrations.scrapecreators_client import ScrapeCreatorsClient
from app.models.collection import RawSourceItem, SnsTopPost
from app.models.factbook import SlideDraft
from app.models.project import Project
from app.repositories.source_item_repo import SourceItemRepository
from app.services.deck_sections import attach_verified_source_urls


@pytest.mark.asyncio
async def test_list_for_synthesis_includes_pending_when_only_profiles_approved(test_session_factory) -> None:
    async with test_session_factory() as session:
        proj = Project(
            name="테스트 프로젝트",
            brand_name="테스트브랜드",
            product_name="테스트제품",
            industry_category="패션/어패럴",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 11, 28),
        )
        session.add(proj)
        await session.flush()

        profile = RawSourceItem(
            project_id=proj.id,
            section_code="1_OWN",
            provider="SCRAPECREATORS",
            channel="instagram_profile",
            title="공식 프로필",
            content="프로필 요약",
            review_status="APPROVED",
            metadata_json={"is_account_profile": True},
        )
        news_pending = RawSourceItem(
            project_id=proj.id,
            section_code="1_OWN",
            provider="APIFY",
            channel="news_press",
            title="브랜드 신제품 보도기사",
            content="신제품 출시 내용",
            source_url="https://news.example.com/1",
            review_status="PENDING",
        )
        rejected_spam = RawSourceItem(
            project_id=proj.id,
            section_code="4_CONSUMER",
            provider="APIFY",
            channel="dcinside",
            title="광고글",
            content="제외 대상",
            review_status="REJECTED",
        )
        session.add_all([profile, news_pending, rejected_spam])
        await session.commit()

        repo = SourceItemRepository(session)
        items = await repo.list_for_synthesis(proj.id, use_approved_only=True)
        channels = {it.channel for it in items}
        assert "news_press" in channels
        assert "instagram_profile" in channels
        assert "dcinside" not in channels


def test_youtube_normalize_post_extracts_thumbnail_fallback_and_description() -> None:
    post = ScrapeCreatorsClient._normalize_post(
        "YOUTUBE",
        {
            "videoId": "Eqtjnt1VZog",
            "title": "브랜드 대표 영상",
            "description": "경량 소재와 내구성 테스트 상세 소개",
            "viewCountInt": 15000,
        },
    )
    assert post["post_url"] == "https://www.youtube.com/watch?v=Eqtjnt1VZog"
    assert post["thumbnail_url"] == "https://i.ytimg.com/vi/Eqtjnt1VZog/hqdefault.jpg"
    assert "브랜드 대표 영상" in post["caption"]
    assert "경량 소재와 내구성 테스트" in post["caption"]


def test_attach_verified_source_urls_does_not_attach_instagram_to_datalab_bullets() -> None:
    slide = SlideDraft(
        project_id="p1",
        section_code="1_OWN",
        slide_order=6,
        slide_type="OWN_PRODUCTS_PRICE",
        title="1-3. 가격 구조",
        headcopy="가격 비교",
        bullets_json=[
            {
                "claim": "쇼핑인사이트 지수 기반 가격 반응 요약",
                "source_name": "네이버 데이터랩 쇼핑인사이트",
                "source_url": None,
                "fact_id": None,
            },
            {
                "claim": "원문 리서치 미확인 항목",
                "source_name": "Perplexity 리서치(결과 없음)",
                "source_url": None,
                "fact_id": None,
            },
        ],
    )
    ig_post = SnsTopPost(
        project_id="p1",
        owner_type="OWN",
        brand_label="테스트",
        platform="INSTAGRAM",
        post_url="https://www.instagram.com/p/abc/",
        caption="인스타 캡션",
        published_at=__import__("datetime").datetime(2026, 10, 1),
        views=100,
        likes=10,
        comments=1,
        engagement_score=100.0,
        rank_order=1,
    )
    attach_verified_source_urls([slide], [], [ig_post])
    assert slide.bullets_json[0]["source_url"] is None
    assert slide.bullets_json[1]["source_url"] is None


def test_placeholder_card_renders_korean_without_crashing(tmp_path) -> None:
    downloader = MediaDownloader(media_root=tmp_path)
    out = downloader.create_placeholder_card(
        project_id="proj-1",
        filename="test_card.png",
        title="브랜드 | YOUTUBE TOP 1",
        subtitle="조회 11,042,911 / 좋아요 7 / 댓글 0",
    )
    assert out["is_valid"] is True
    assert out["width"] == 640
