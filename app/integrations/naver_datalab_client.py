from __future__ import annotations

from datetime import date
from typing import Any

from app.core.config import get_settings
from app.core.exceptions import ExternalApiError
from app.integrations.base_client import BaseApiClient


class NaverDataLabClient(BaseApiClient):
    """NAVER Cloud Platform (NAVER API HUB) DataLab Search Trend & Shopping Insight client."""

    provider_name = "naver_datalab"

    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(
            base_url=settings.NAVER_APIGW_BASE_URL,
            max_concurrency=settings.MAX_CONCURRENT_NAVER,
        )
        self.key_id = settings.X_NCP_APIGW_API_KEY_ID.strip()
        self.key_secret = settings.X_NCP_APIGW_API_KEY.strip()

    def _headers(self) -> dict[str, str]:
        if not self.key_id or not self.key_secret:
            raise ExternalApiError(
                provider=self.provider_name,
                code="API_KEY_NOT_CONFIGURED",
                message="NAVER API HUB 키(X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY)가 설정되지 않았습니다.",
                user_action_hint="backend/.env에 네이버 클라우드 API Gateway 키를 입력해 주세요.",
                retryable=False,
            )
        return {
            "X-NCP-APIGW-API-KEY-ID": self.key_id,
            "X-NCP-APIGW-API-KEY": self.key_secret,
            "Content-Type": "application/json",
        }

    async def fetch_search_trend(
        self,
        *,
        start_date: date,
        end_date: date,
        keyword_groups: list[dict[str, Any]],
        time_unit: str = "week",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Calls /search-trend/v1/search with up to 5 keywordGroups per batch (anchor-normalized if >5)."""
        headers = self._headers()
        if not keyword_groups:
            return {"results": [], "is_anchor_normalized": False}

        if len(keyword_groups) <= 5:
            body = {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "timeUnit": time_unit,
                "keywordGroups": keyword_groups,
            }
            raw = await self.request_json(
                "POST",
                "/search-trend/v1/search",
                headers=headers,
                json_body=body,
                force_refresh=force_refresh,
            )
            raw["is_anchor_normalized"] = False
            return raw

        # Anchor scaling when total groups exceed 5 (keep index 0 as shared anchor)
        anchor = keyword_groups[0]
        batches: list[list[dict[str, Any]]] = []
        idx = 1
        while idx < len(keyword_groups):
            batches.append([anchor, *keyword_groups[idx : idx + 4]])
            idx += 4

        first_raw = await self.request_json(
            "POST",
            "/search-trend/v1/search",
            headers=headers,
            json_body={
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "timeUnit": time_unit,
                "keywordGroups": batches[0],
            },
            force_refresh=force_refresh,
        )
        merged_results = list(first_raw.get("results") or [])
        anchor_base_sum = sum(float(p.get("ratio", 0.0)) for p in (merged_results[0].get("data") or [])) if merged_results else 1.0

        for batch in batches[1:]:
            b_raw = await self.request_json(
                "POST",
                "/search-trend/v1/search",
                headers=headers,
                json_body={
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "timeUnit": time_unit,
                    "keywordGroups": batch,
                },
                force_refresh=force_refresh,
            )
            b_results = list(b_raw.get("results") or [])
            if not b_results:
                continue
            b_anchor_sum = sum(float(p.get("ratio", 0.0)) for p in (b_results[0].get("data") or [])) or 1.0
            scale = anchor_base_sum / b_anchor_sum
            for series in b_results[1:]:
                scaled_data = [
                    {"period": pt["period"], "ratio": round(float(pt["ratio"]) * scale, 4)}
                    for pt in (series.get("data") or [])
                ]
                merged_results.append({"title": series.get("title"), "keywords": series.get("keywords"), "data": scaled_data})

        # Re-normalize peak across merged results to 100
        global_max = max(
            (float(pt["ratio"]) for r in merged_results for pt in (r.get("data") or [])),
            default=100.0,
        ) or 100.0
        if global_max > 0:
            for r in merged_results:
                for pt in (r.get("data") or []):
                    pt["ratio"] = round((float(pt["ratio"]) / global_max) * 100.0, 4)

        return {"results": merged_results, "is_anchor_normalized": True}

    async def fetch_shopping_insight(
        self,
        *,
        start_date: date,
        end_date: date,
        category_id: str,
        keyword_groups: list[dict[str, Any]],
        time_unit: str = "week",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Calls /datalab/v1/shopping/category/keywords with up to 5 keyword items."""
        headers = self._headers()
        formatted_keywords = [
            {"name": g["groupName"], "param": list(g.get("keywords") or [g["groupName"]])[:1]}
            for g in keyword_groups[:5]
        ]
        if not formatted_keywords:
            return {"results": []}

        body = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "timeUnit": time_unit,
            "category": category_id,
            "keyword": formatted_keywords,
        }
        return await self.request_json(
            "POST",
            "/shopping/v1/category/keywords",
            headers=headers,
            json_body=body,
            force_refresh=force_refresh,
        )
