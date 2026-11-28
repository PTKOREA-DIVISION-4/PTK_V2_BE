from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_async_slide_generation_creates_cover_and_concise_index(async_client) -> None:
    create_res = await async_client.post(
        "/api/v1/projects",
        json={
            "name": "비동기 장표 생성 테스트",
            "brand_name": "테스트브랜드",
            "product_name": "테스트제품",
            "industry_category": "뷰티/화장품",
            "analysis_track": "REVIEW_CENTRIC",
            "period_start": "2026-06-01",
            "period_end": "2026-11-25",
            "competitors": [{"brand_name": "경쟁브랜드", "product_name": "경쟁제품"}],
            "sns_accounts": [],
            "keyword_groups": [],
        },
    )
    assert create_res.status_code == 201
    project_id = create_res.json()["id"]

    gen_res = await async_client.post(
        f"/api/v1/projects/{project_id}/slides/generate-async",
        json={"summary_split_mode": "SPLIT_2", "use_approved_only": True},
    )
    assert gen_res.status_code == 202
    job_data = gen_res.json()
    job_id = job_data["id"]
    assert job_data["job_type"] == "SLIDE_GENERATION"
    assert len(job_data["subtasks"]) == 10

    await async_client._transport.app.state.job_manager.wait_for_job(job_id, timeout=15.0)

    status_res = await async_client.get(
        f"/api/v1/projects/{project_id}/slides/generation-status"
    )
    assert status_res.status_code == 200
    status_json = status_res.json()
    assert status_json["status"] == "COMPLETED"
    assert status_json["progress_pct"] == 100

    slides_res = await async_client.get(f"/api/v1/projects/{project_id}/slides")
    assert slides_res.status_code == 200
    slides = slides_res.json()
    assert len(slides) >= 36
    assert slides[0]["slide_type"] == "COVER"
    assert slides[1]["slide_type"] == "INDEX"
    assert slides[1]["kpi_cards"] == []
    assert slides[1]["bullets"] == []
    assert len(slides[1]["table"]["rows"]) == 6
