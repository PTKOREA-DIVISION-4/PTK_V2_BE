from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.exceptions import ExternalApiError
from app.integrations.base_client import BaseApiClient


class PerplexityClient(BaseApiClient):
    """Perplexity Sonar API client for macro market, regulation, and competitor research."""

    provider_name = "perplexity"

    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(
            base_url=settings.PERPLEXITY_BASE_URL,
            max_concurrency=settings.MAX_CONCURRENT_PERPLEXITY,
        )
        self.api_key = settings.PERPLEXITY_API_KEY.strip()
        self.model = settings.PERPLEXITY_MODEL

    def _ensure_key(self) -> None:
        if not self.api_key:
            raise ExternalApiError(
                provider=self.provider_name,
                code="API_KEY_NOT_CONFIGURED",
                message="PERPLEXITY_API_KEY 환경변수가 설정되어 있지 않습니다.",
                user_action_hint="backend/.env에 PERPLEXITY_API_KEY를 설정해 주세요.",
                retryable=False,
            )

    async def research_topic(
        self,
        *,
        topic_title: str,
        query_prompt: str,
        recency_filter: str = "year",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        self._ensure_key()
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a Korean strategic marketing & market intelligence researcher. "
                        "Provide factual, quantified insights with clear Korean prose and verifiable citations. "
                        "Do not fabricate numbers."
                    ),
                },
                {"role": "user", "content": query_prompt},
            ],
            "temperature": 0.1,
            "search_recency_filter": recency_filter,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        raw = await self.request_json(
            "POST",
            "/chat/completions",
            headers=headers,
            json_body=payload,
            cache_key_params={"topic": topic_title, "prompt": query_prompt, "recency": recency_filter},
            force_refresh=force_refresh,
        )
        choices = raw.get("choices") or []
        content = ""
        if choices and isinstance(choices[0], dict):
            content = (choices[0].get("message") or {}).get("content", "")
        citations = raw.get("citations") or []
        search_results = raw.get("search_results") or []
        return {
            "topic_title": topic_title,
            "content": content,
            "citations": citations,
            "search_results": search_results,
        }
