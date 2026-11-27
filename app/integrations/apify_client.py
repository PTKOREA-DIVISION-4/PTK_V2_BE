from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.exceptions import ExternalApiError
from app.integrations.base_client import BaseApiClient


COMMUNITY_DOMAIN_MAP: dict[str, str] = {
    "dcinside": "site:gall.dcinside.com",
    "fmkorea": "site:fmkorea.com",
    "theqoo": "site:theqoo.net",
    "clien": "site:clien.net",
    "naver_blog": "site:blog.naver.com",
    "naver_cafe": "site:cafe.naver.com",
}


class ApifyClient(BaseApiClient):
    """Apify Actor client for Korean communities, blogs/cafes, reviews, and video/web screenshots."""

    provider_name = "apify"

    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(
            base_url=settings.APIFY_BASE_URL,
            max_concurrency=settings.MAX_CONCURRENT_APIFY,
            timeout_seconds=max(settings.HTTP_TIMEOUT_SECONDS, 120.0),
        )
        self.token = settings.APIFY_API_TOKEN.strip()

    def _ensure_token(self) -> None:
        if not self.token:
            raise ExternalApiError(
                provider=self.provider_name,
                code="API_KEY_NOT_CONFIGURED",
                message="APIFY_API_TOKEN 환경변수가 설정되어 있지 않습니다.",
                user_action_hint="backend/.env에 APIFY_API_TOKEN을 설정해 주세요.",
                retryable=False,
            )

    async def run_actor_sync_items(
        self,
        *,
        actor_id: str,
        run_input: dict[str, Any],
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Starts an Apify Actor run, polls run status until SUCCEEDED, and fetches dataset items without HTTP timeout drops."""
        self._ensure_token()
        import asyncio
        import time

        cache_params = {"actor": actor_id, "input": run_input}
        if not force_refresh:
            cached = self.cache.get(
                self.provider_name, f"actor/{actor_id}", cache_params, force_refresh=False
            )
            if isinstance(cached, dict) and isinstance(cached.get("items"), list):
                return [i for i in cached["items"] if isinstance(i, dict)]

        encoded_actor = actor_id.replace("/", "~")
        start_res = await self.request_json(
            "POST",
            f"/acts/{encoded_actor}/runs",
            params={"token": self.token},
            json_body=run_input,
            force_refresh=True,
        )
        run_data = start_res.get("data") if isinstance(start_res.get("data"), dict) else start_res
        run_id = str(run_data.get("id") or "")
        dataset_id = str(run_data.get("defaultDatasetId") or "")
        if not run_id:
            return []

        deadline = time.monotonic() + 110.0
        status = str(run_data.get("status") or "RUNNING")
        while status in {"READY", "RUNNING"} and time.monotonic() < deadline:
            await asyncio.sleep(2.5)
            poll = await self.request_json(
                "GET",
                f"/actor-runs/{run_id}",
                params={"token": self.token},
                force_refresh=True,
            )
            pdata = poll.get("data") if isinstance(poll.get("data"), dict) else poll
            status = str(pdata.get("status") or "")
            dataset_id = str(pdata.get("defaultDatasetId") or dataset_id)

        if status != "SUCCEEDED" or not dataset_id:
            raise ExternalApiError(
                provider=self.provider_name,
                code="APIFY_RUN_FAILED",
                message=f"Apify 액터({actor_id}) 실행이 완료되지 않았습니다 (status={status}).",
                retryable=True,
            )

        ds_res = await self.request_json(
            "GET",
            f"/datasets/{dataset_id}/items",
            params={"token": self.token, "format": "json"},
            force_refresh=True,
        )
        items = [i for i in (ds_res.get("items") or []) if isinstance(i, dict)]
        self.cache.set(self.provider_name, f"actor/{actor_id}", cache_params, {"items": items})
        return items

    async def collect_korean_community_voc(
        self,
        *,
        keywords: list[str],
        communities: list[str],
        max_results_per_query: int = 10,
        extra_queries: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Collects discussions from dcinside, fmkorea, theqoo, clien, naver blog/cafe via consolidated Apify Google Search queries."""
        self._ensure_token()
        queries: list[str] = []
        primary_kw = " ".join(keywords[:2]).strip()
        if primary_kw:
            # Keep Naver Blog and Cafe separate, consolidate forum communities with OR for fast reliable runs
            forum_sites: list[str] = []
            for comm in communities:
                site_filter = COMMUNITY_DOMAIN_MAP.get(comm)
                if not site_filter:
                    continue
                if comm in {"naver_blog", "naver_cafe"}:
                    queries.append(f"{site_filter} {primary_kw}")
                else:
                    forum_sites.append(site_filter)
            if forum_sites:
                queries.append(f"({' OR '.join(forum_sites)}) {primary_kw}")

        for q in (extra_queries or [])[:1]:
            if q.strip() and q.strip() not in queries:
                queries.append(q.strip())

        if not queries:
            return []

        items = await self.run_actor_sync_items(
            actor_id="apify/google-search-scraper",
            run_input={
                "queries": "\n".join(queries[:4]),
                "maxPagesPerQuery": 1,
                "resultsPerPage": max_results_per_query,
                "countryCode": "kr",
                "languageCode": "ko",
            },
            force_refresh=force_refresh,
        )
        normalized: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for page in items:
            organic = page.get("organicResults") or []
            for res in organic:
                if not isinstance(res, dict):
                    continue
                url = str(res.get("url") or "").strip()
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                channel = self._detect_channel_from_url(url)
                normalized.append(
                    {
                        "channel": channel,
                        "title": res.get("title") or "커뮤니티 게시글",
                        "content": res.get("description") or res.get("snippet") or "",
                        "source_url": url,
                        "published_at": res.get("date"),
                    }
                )
        return normalized

    async def capture_reference_screenshots(
        self,
        *,
        urls: list[str],
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Captures webpage / video scene screenshots via Apify screenshot actor."""
        if not urls:
            return []
        self._ensure_token()
        items = await self.run_actor_sync_items(
            actor_id="apify/screenshot-url",
            run_input={
                "urls": [{"url": u} for u in urls[:5]],
                "viewportWidth": 1280,
                "viewportHeight": 720,
                "waitUntil": "networkidle2",
            },
            force_refresh=force_refresh,
        )
        return items

    @staticmethod
    def _detect_channel_from_url(url: str) -> str:
        lower = url.lower()
        if "dcinside" in lower:
            return "dcinside"
        if "fmkorea" in lower:
            return "fmkorea"
        if "theqoo" in lower:
            return "theqoo"
        if "clien" in lower:
            return "clien"
        if "blog.naver" in lower:
            return "naver_blog"
        if "cafe.naver" in lower:
            return "naver_cafe"
        return "community_web"
