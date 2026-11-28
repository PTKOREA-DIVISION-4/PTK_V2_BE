from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

import pytest
from pptx import Presentation

from app.models.collection import DataLabSeries, RawSourceItem, SnsTopPost
from app.services.collection_orchestrator import compute_highlight_spans


@pytest.mark.asyncio
async def test_full_api_e2e_workflow_and_fault_isolation(
    async_client, test_session_factory
) -> None:
    # 0-a. Keyword recommendation
    rec_res = await async_client.post(
        "/api/v1/projects/recommend-keywords",
        json={
            "brand_name": "설화수",
            "product_name": "윤조에센스 6세대",
            "industry_category": "뷰티/화장품",
            "competitor_brands": ["라네즈"],
        },
    )
    assert rec_res.status_code == 200
    assert rec_res.json()["suggested_analysis_track"] == "REVIEW_CENTRIC"

    # 0-b. Reject multi-brand input (single brand x single product enforcement)
    bad_proj = await async_client.post(
        "/api/v1/projects",
        json={
            "name": "잘못된 다중 브랜드",
            "brand_name": "설화수, 라네즈",
            "product_name": "에센스",
            "industry_category": "뷰티/화장품",
            "period_start": "2026-09-01",
            "period_end": "2026-11-25",
        },
    )
    assert bad_proj.status_code == 422

    # 0-c. Create valid single-brand/product project
    create_res = await async_client.post(
        "/api/v1/projects",
        json={
            "name": "2026 설화수 윤조에센스 팩트북",
            "brand_name": "설화수",
            "product_name": "윤조에센스 6세대",
            "industry_category": "뷰티/화장품",
            "period_start": "2026-09-01",
            "period_end": "2026-11-25",
            "competitors": [{"brand_name": "라네즈", "product_name": "워터뱅크 크림"}],
            "sns_accounts": [
                {
                    "owner_type": "OWN",
                    "brand_label": "설화수",
                    "account_url": "https://www.instagram.com/sulwhasoo.official/",
                }
            ],
        },
    )
    assert create_res.status_code == 201
    project_id = create_res.json()["id"]

    # 1. Confirm research plan
    plan_res = await async_client.get(f"/api/v1/projects/{project_id}/research-plan")
    assert plan_res.status_code == 200
    assert len(plan_res.json()["items"]) >= 8

    confirm_res = await async_client.put(
        f"/api/v1/projects/{project_id}/research-plan",
        json={
            "is_confirmed": True,
            "target_communities": ["theqoo", "dcinside", "fmkorea", "naver_blog"],
            "items": [{"item_key": "consumer_voc_and_kbf", "is_enabled": True}],
        },
    )
    assert confirm_res.status_code == 200
    assert confirm_res.json()["is_confirmed"] is True

    # 2-a. Trigger async collection with unconfigured API keys -> must isolate cleanly & respect Idempotency-Key
    run_res = await async_client.post(
        f"/api/v1/projects/{project_id}/collections/run",
        headers={"Idempotency-Key": "idem-collect-001"},
        json={"force_refresh": False, "selected_sources": ["perplexity_research", "media_archiving"]},
    )
    assert run_res.status_code == 202
    job_id = run_res.json()["id"]

    dup_res = await async_client.post(
        f"/api/v1/projects/{project_id}/collections/run",
        headers={"Idempotency-Key": "idem-collect-001"},
        json={"force_refresh": False, "selected_sources": ["perplexity_research", "media_archiving"]},
    )
    assert dup_res.status_code == 202
    assert dup_res.json()["id"] == job_id

    # Wait for background job completion
    await async_client._transport.app.state.job_manager.wait_for_job(job_id, timeout=10.0)
    job_status = await async_client.get(f"/api/v1/jobs/{job_id}")
    assert job_status.status_code == 200
    assert job_status.json()["status"] in {"PARTIAL_SUCCESS", "COMPLETED", "FAILED"}

    # 2-b. Seed collected multi-source records (simulating API responses) & verify bulk review + highlight_spans
    content_text = "세안 직후 윤조에센스 6세대를 쓰면 속건조가 빠르게 완화되고 다음 단계 흡수력이 좋아집니다."
    quote_text = "속건조가 빠르게 완화되고 다음 단계 흡수력이 좋아집니다."
    spans, _ = compute_highlight_spans(content_text, quote_text)

    async with test_session_factory() as session:
        s1 = RawSourceItem(
            project_id=project_id,
            section_code="4_CONSUMER",
            provider="APIFY",
            channel="theqoo",
            title="더쿠 실사용 후기",
            content=content_text,
            source_url="https://theqoo.net/beauty/999",
            evidence_quote=quote_text,
            highlight_spans=spans,
            sentiment="POSITIVE",
            review_status="PENDING",
        )
        s2 = RawSourceItem(
            project_id=project_id,
            section_code="2_MARKET",
            provider="PERPLEXITY",
            channel="perplexity_research",
            title="스킨케어 시장 리포트",
            content="국내 기능성 안티에이징 스킨케어 시장은 전년 대비 성장세를 이어가고 있습니다.",
            source_url="https://news.example.com/report",
            evidence_quote="국내 기능성 안티에이징 스킨케어 시장은 전년 대비 성장세를 이어가고 있습니다.",
            sentiment="NEUTRAL",
            review_status="PENDING",
        )
        s_spam = RawSourceItem(
            project_id=project_id,
            section_code="4_CONSUMER",
            provider="APIFY",
            channel="dcinside",
            title="스팸 광고글",
            content="무관한 광고 링크",
            review_status="PENDING",
        )
        session.add_all([s1, s2, s_spam])
        session.add_all(
            [
                DataLabSeries(
                    project_id=project_id,
                    metric_type="SEARCH_TREND",
                    group_label="설화수 윤조에센스",
                    owner_type="OWN",
                    period_start=date(2026, 9, 1),
                    period_end=date(2026, 11, 25),
                    time_unit="week",
                    points_json=[{"period": "2026-09-01", "ratio": 70.0}, {"period": "2026-10-01", "ratio": 100.0}],
                    cumulative_index_sum=170.0,
                    share_of_search_pct=60.0,
                    growth_rate_pct=42.8,
                    peak_date="2026-10-01",
                    peak_value=100.0,
                    methodology_note="출처: 네이버 데이터랩 | 기간: 2026-09-01~2026-11-25 | 기준: 최댓값=100",
                ),
                SnsTopPost(
                    project_id=project_id,
                    owner_type="OWN",
                    brand_label="설화수",
                    platform="INSTAGRAM",
                    post_url="https://instagram.com/p/abc",
                    caption="윤조에센스 캠페인 영상",
                    published_at=datetime(2026, 10, 10, 10, 0),
                    views=25000,
                    likes=4100,
                    comments=120,
                    engagement_score=6960.0,
                    rank_order=1,
                    is_creator_collab=False,
                    key_takeaway="조회 25,000 / 좋아요 4,100",
                ),
            ]
        )
        await session.commit()
        s1_id, s2_id, spam_id = s1.id, s2.id, s_spam.id

    # Verify source detail returns highlight_spans
    detail_res = await async_client.get(f"/api/v1/projects/{project_id}/sources/{s1_id}")
    assert detail_res.status_code == 200
    assert len(detail_res.json()["highlight_spans"]) == 1

    # Bulk approve valid sources & reject spam
    bulk_approve = await async_client.patch(
        f"/api/v1/projects/{project_id}/sources/bulk",
        json={"source_ids": [s1_id, s2_id], "review_status": "APPROVED"},
    )
    assert bulk_approve.status_code == 200
    assert bulk_approve.json()["updated_count"] == 2

    bulk_reject = await async_client.patch(
        f"/api/v1/projects/{project_id}/sources/bulk",
        json={"source_ids": [spam_id], "review_status": "REJECTED"},
    )
    assert bulk_reject.status_code == 200
    assert bulk_reject.json()["facets"]["by_review_status"]["APPROVED"] == 2

    # Check DataLab & SNS TOP 5 endpoints
    dl_res = await async_client.get(f"/api/v1/projects/{project_id}/datalab")
    assert dl_res.status_code == 200
    assert len(dl_res.json()["search_trends"]) == 1

    sns_res = await async_client.get(f"/api/v1/projects/{project_id}/sns-top5")
    assert sns_res.status_code == 200
    assert len(sns_res.json()["own_top_posts"]) == 1

    # 3. Generate slides -> apply planner comment (diff preview & apply) -> switch Summary to SPLIT_4
    gen_res = await async_client.post(
        f"/api/v1/projects/{project_id}/slides/generate",
        json={"summary_split_mode": "SPLIT_2", "use_approved_only": True},
    )
    assert gen_res.status_code == 200
    slides = gen_res.json()
    assert len(slides) >= 9

    target_slide_id = slides[1]["id"]
    diff_res = await async_client.post(
        f"/api/v1/projects/{project_id}/slides/{target_slide_id}/apply-comment",
        json={"raw_comment": "2030 입문자 첫 에센스 포지셔닝 강조", "auto_apply": False},
    )
    assert diff_res.status_code == 200
    diff_body = diff_res.json()
    assert diff_body["status"] == "PREVIEW_READY"
    assert diff_body["before_draft"]["headcopy"] != diff_body["after_draft"]["headcopy"]

    decide_res = await async_client.post(
        f"/api/v1/projects/{project_id}/slides/{target_slide_id}/comments/{diff_body['comment_id']}/decide",
        json={"decision": "APPLY"},
    )
    assert decide_res.status_code == 200
    assert decide_res.json()["review_status"] == "COMMENT_APPLIED"

    split4_res = await async_client.patch(
        f"/api/v1/projects/{project_id}/summary-split",
        json={"summary_split_mode": "SPLIT_4"},
    )
    assert split4_res.status_code == 200
    summary_parts = [s for s in split4_res.json() if s["slide_type"] == "SUMMARY_PART"]
    assert len(summary_parts) == 4

    # 4. Pre-flight QC -> Export PPTX -> Download binary
    qc_res = await async_client.post(f"/api/v1/projects/{project_id}/exports/qc")
    assert qc_res.status_code == 200
    assert qc_res.json()["can_export"] is True

    exp_res = await async_client.post(
        f"/api/v1/projects/{project_id}/exports/pptx",
        json={"allow_warnings": True},
    )
    assert exp_res.status_code == 201
    export_id = exp_res.json()["id"]
    assert exp_res.json()["slide_count"] == len(split4_res.json())

    dl_file = await async_client.get(
        f"/api/v1/projects/{project_id}/exports/{export_id}/download"
    )
    assert dl_file.status_code == 200
    assert dl_file.content[:2] == b"PK"  # Valid PPTX ZIP archive signature
    prs = Presentation(BytesIO(dl_file.content))
    assert len(prs.slides) == exp_res.json()["slide_count"]

    # Workflow summary check
    sum_res = await async_client.get(f"/api/v1/projects/{project_id}/summary")
    assert sum_res.status_code == 200
    assert sum_res.json()["workflow_meta"]["can_export"] is True
