from __future__ import annotations

from typing import Any

import pytest

from app.core.exceptions import ExternalApiError
from app.integrations import apify_client as apify_mod
from app.integrations.apify_client import ApifyClient


def test_apify_poll_timeout_is_at_least_240_seconds() -> None:
    assert apify_mod.APIFY_POLL_TIMEOUT_SECONDS >= 240.0


@pytest.mark.asyncio
async def test_apify_recovers_partial_items_when_running_times_out(monkeypatch) -> None:
    monkeypatch.setattr(apify_mod, "APIFY_POLL_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(apify_mod, "APIFY_POLL_INTERVAL_SECONDS", 0.001)

    client = ApifyClient()
    client.token = "dummy-token"
    cache_calls: list[Any] = []
    monkeypatch.setattr(client.cache, "set", lambda *args, **kwargs: cache_calls.append(args))

    async def fake_request_json(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if method == "POST" and "/runs" in path:
            return {"data": {"id": "run-1", "defaultDatasetId": "ds-1", "status": "RUNNING"}}
        if method == "GET" and "/actor-runs/" in path:
            return {"data": {"id": "run-1", "defaultDatasetId": "ds-1", "status": "RUNNING"}}
        if method == "GET" and "/datasets/ds-1/items" in path:
            return {"items": [{"organicResults": [{"title": "부분 수집 결과", "url": "https://example.com"}]}]}
        raise AssertionError(f"Unexpected request: {method} {path}")

    monkeypatch.setattr(client, "request_json", fake_request_json)

    items = await client.run_actor_sync_items(
        actor_id="apify/google-search-scraper",
        run_input={"queries": "sample-brand"},
        force_refresh=True,
    )
    assert len(items) == 1
    assert cache_calls == []


@pytest.mark.asyncio
async def test_apify_raises_when_timeout_has_empty_dataset_or_failed_status(monkeypatch) -> None:
    monkeypatch.setattr(apify_mod, "APIFY_POLL_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(apify_mod, "APIFY_POLL_INTERVAL_SECONDS", 0.001)

    client = ApifyClient()
    client.token = "dummy-token"

    async def fake_empty_timeout(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if method == "POST":
            return {"data": {"id": "run-2", "defaultDatasetId": "ds-2", "status": "RUNNING"}}
        if "/actor-runs/" in path:
            return {"data": {"id": "run-2", "defaultDatasetId": "ds-2", "status": "RUNNING"}}
        return {"items": []}

    monkeypatch.setattr(client, "request_json", fake_empty_timeout)
    with pytest.raises(ExternalApiError) as exc_info:
        await client.run_actor_sync_items(
            actor_id="apify/google-search-scraper",
            run_input={"queries": "sample-brand"},
            force_refresh=True,
        )
    assert exc_info.value.code == "APIFY_RUN_FAILED"

    async def fake_failed_status(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if method == "POST":
            return {"data": {"id": "run-3", "defaultDatasetId": "ds-3", "status": "RUNNING"}}
        return {"data": {"id": "run-3", "defaultDatasetId": "ds-3", "status": "FAILED"}}

    monkeypatch.setattr(client, "request_json", fake_failed_status)
    with pytest.raises(ExternalApiError) as exc_info2:
        await client.run_actor_sync_items(
            actor_id="apify/google-search-scraper",
            run_input={"queries": "sample-brand"},
            force_refresh=True,
        )
    assert exc_info2.value.code == "APIFY_RUN_FAILED"
