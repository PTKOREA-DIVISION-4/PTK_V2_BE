from __future__ import annotations

from datetime import date, datetime

import pytest

from app.integrations.naver_datalab_client import NaverDataLabClient
from app.models.collection import RawSourceItem
from app.models.project import CompetitorTarget, Project
from app.services.datalab_metrics_service import DataLabMetricsService
from app.services.press_metrics_service import PressMetricsService
from app.services.research_query_planner import build_perplexity_queries
from app.services.sns_ranking_service import SnsRankingService


def test_datalab_share_of_search_and_methodology_note() -> None:
    raw_results = [
        {
            "title": "설화수 윤조에센스",
            "data": [
                {"period": "2026-09-01", "ratio": 40.0},
                {"period": "2026-09-08", "ratio": 60.0},
                {"period": "2026-09-15", "ratio": 80.0},
                {"period": "2026-09-22", "ratio": 100.0},
            ],
        },
        {
            "title": "라네즈 워터뱅크",
            "data": [
                {"period": "2026-09-01", "ratio": 50.0},
                {"period": "2026-09-08", "ratio": 50.0},
                {"period": "2026-09-15", "ratio": 40.0},
                {"period": "2026-09-22", "ratio": 40.0},
            ],
        },
    ]
    series = DataLabMetricsService.compute_series_metrics(
        project_id="proj_1",
        metric_type="SEARCH_TREND",
        raw_results=raw_results,
        owner_type_by_label={"설화수 윤조에센스": "OWN", "라네즈 워터뱅크": "COMPETITOR"},
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        time_unit="week",
    )
    assert len(series) == 2
    total_share = round(sum(s.share_of_search_pct for s in series), 2)
    assert total_share == 100.0

    own = series[0]
    assert own.cumulative_index_sum == 280.0
    assert own.peak_date == "2026-09-22"
    assert own.peak_value == 100.0
    assert own.growth_rate_pct > 0
    assert "출처: 네이버 데이터랩" in own.methodology_note
    assert "기준:" in own.methodology_note


@pytest.mark.asyncio
async def test_naver_datalab_anchor_scaling_over_5_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_NCP_APIGW_API_KEY_ID", "dummy-id")
    monkeypatch.setenv("X_NCP_APIGW_API_KEY", "dummy-secret")
    from app.core.config import get_settings

    get_settings.cache_clear()
    client = NaverDataLabClient()

    calls: list[dict] = []

    async def fake_request_json(method, path, **kwargs):
        body = kwargs["json_body"]
        calls.append(body)
        groups = body["keywordGroups"]
        # First batch anchor sum = 100, second batch anchor sum = 50 -> scale=2.0
        anchor_val = 50.0 if len(calls) == 1 else 25.0
        results = []
        for idx, g in enumerate(groups):
            val = anchor_val if idx == 0 else (20.0 if len(calls) == 1 else 10.0)
            results.append(
                {
                    "title": g["groupName"],
                    "data": [
                        {"period": "2026-09-01", "ratio": val},
                        {"period": "2026-09-08", "ratio": val},
                    ],
                }
            )
        return {"results": results}

    monkeypatch.setattr(client, "request_json", fake_request_json)
    groups = [{"groupName": f"G{i}", "keywords": [f"K{i}"]} for i in range(6)]
    res = await client.fetch_search_trend(
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        keyword_groups=groups,
    )
    assert res["is_anchor_normalized"] is True
    assert len(calls) == 2
    assert len(res["results"]) == 6
    # G5 (second batch, ratio 10 * scale 2.0 = 20) should match G1 (first batch, ratio 20)
    g1_ratio = res["results"][1]["data"][0]["ratio"]
    g5_ratio = res["results"][5]["data"][0]["ratio"]
    assert g1_ratio == g5_ratio


def test_sns_period_filter_and_top5_ranking() -> None:
    posts = [
        # Out of period (too old) -> must be excluded even with massive likes
        {
            "platform": "INSTAGRAM",
            "post_url": "https://instagram.com/p/old",
            "caption": "작년 게시물",
            "published_at": datetime(2025, 1, 10, 12, 0),
            "views": 0,
            "likes": 999999,
            "comments": 5000,
        },
        *[
            {
                "platform": "INSTAGRAM",
                "post_url": f"https://instagram.com/p/{i}",
                "caption": f"가을 캠페인 {i} " + ("#광고" if i == 4 else ""),
                "published_at": datetime(2026, 9, 10 + i, 12, 0),
                "views": 1000 * i,
                "likes": 100 * i,
                "comments": 10 * i,
            }
            for i in range(1, 8)
        ],
    ]
    top5 = SnsRankingService.rank_top_posts(
        posts=posts,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        limit=5,
        brand_keywords=["설화수"],
    )
    assert len(top5) == 5
    assert all(p["post_url"] != "https://instagram.com/p/old" for p in top5)
    assert [p["rank_order"] for p in top5] == [1, 2, 3, 4, 5]
    assert top5[0]["likes"] == 700
    collab_posts = [p for p in top5 if p["is_creator_collab"]]
    assert len(collab_posts) == 1


def test_research_query_planner_1on1_competitors_and_benchmarks() -> None:
    proj = Project(
        name="테스트 팩트북",
        brand_name="브랜드A",
        product_name="대표제품",
        industry_category="뷰티/화장품",
        analysis_track="REVIEW_CENTRIC",
        period_start=date(2026, 9, 1),
        period_end=date(2026, 11, 25),
    )
    proj.competitors = [
        CompetitorTarget(brand_name="경쟁사1", product_name="라인1", display_order=0),
        CompetitorTarget(brand_name="경쟁사2", product_name="라인2", display_order=1),
        CompetitorTarget(brand_name="경쟁사3", product_name="라인3", display_order=2),
    ]
    queries = build_perplexity_queries(proj)
    assert len(queries) == 11
    titles = "\n".join(q.title for q in queries)
    assert "[경쟁 1] 경쟁사1" in titles
    assert "[경쟁 2] 경쟁사2" in titles
    assert "[경쟁 3] 경쟁사3" in titles
    assert "벤치마크" in titles


def test_press_metrics_service_aggregation() -> None:
    sources = [
        RawSourceItem(
            project_id="p1",
            section_code="1_OWN",
            provider="APIFY",
            channel="news_press",
            title="브랜드A 신제품 컬렉션 출시 보도",
            content="2026.10 신제품 런칭 성과",
            source_url="https://news.example.com/1",
            review_status="APPROVED",
            metadata_json={
                "brand_name": "브랜드A",
                "topic_tag": "신제품 출시",
                "published_date_raw": "2026-10-12",
            },
        ),
        RawSourceItem(
            project_id="p1",
            section_code="3_COMPETITOR",
            provider="APIFY",
            channel="news_press",
            title="경쟁사1 팝업 스토어 오픈",
            content="2026.11 성수 팝업 오픈",
            source_url="https://news.example.com/2",
            review_status="PENDING",
            metadata_json={
                "brand_name": "경쟁사1",
                "topic_tag": "팝업·체험",
                "published_date_raw": "2026-11-03",
            },
        ),
    ]
    summary = PressMetricsService.summarize_press(
        sources=sources,
        brand_names=["브랜드A", "경쟁사1", "경쟁사2"],
    )
    assert summary["total_articles"] == 2
    assert summary["monthly_items"] == [
        {"label": "2026-10", "value": 1, "highlight": False},
        {"label": "2026-11", "value": 1, "highlight": False},
    ]
    assert summary["brand_items"][0]["value"] == 1
    assert summary["brand_items"][1]["value"] == 1
    assert summary["brand_items"][2]["value"] == 0
