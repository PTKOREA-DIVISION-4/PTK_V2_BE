from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import get_settings
from app.core.exceptions import ExternalApiError
from app.integrations.base_client import BaseApiClient


class AnthropicClient(BaseApiClient):
    """Anthropic Claude API client for schema mapping, evidence extraction, comment refinement, and slide synthesis."""

    provider_name = "anthropic"

    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(
            base_url=settings.ANTHROPIC_BASE_URL,
            max_concurrency=settings.MAX_CONCURRENT_ANTHROPIC,
            timeout_seconds=max(settings.HTTP_TIMEOUT_SECONDS, 90.0),
        )
        self.api_key = settings.ANTHROPIC_API_KEY.strip()
        self.model = settings.ANTHROPIC_MODEL

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _ensure_key(self) -> None:
        if not self.api_key:
            raise ExternalApiError(
                provider=self.provider_name,
                code="API_KEY_NOT_CONFIGURED",
                message="ANTHROPIC_API_KEY 환경변수가 설정되어 있지 않습니다.",
                user_action_hint="backend/.env에 ANTHROPIC_API_KEY를 설정해 주세요.",
                retryable=False,
            )

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        if fence:
            cleaned = fence.group(1)
        else:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start : end + 1]
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", cleaned)
        try:
            parsed = json.loads(cleaned, strict=False)
        except json.JSONDecodeError:
            # Strip trailing commas before closing braces/brackets if present
            repaired = re.sub(r",\s*([}\]])", r"\1", cleaned)
            parsed = json.loads(repaired, strict=False)
        if not isinstance(parsed, dict):
            raise ValueError("Claude response JSON root is not an object")
        return parsed

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        self._ensure_key()
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "thinking": {"type": "between_tools"},
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }

        last_err: Exception | None = None
        for attempt in range(2):
            raw = await self.request_json(
                "POST",
                "/v1/messages",
                headers=headers,
                json_body=payload,
                cache_key_params={"system": system_prompt, "user": user_prompt, "attempt": attempt},
                force_refresh=force_refresh or attempt > 0,
            )
            blocks = raw.get("content") or []
            text_parts = [
                b.get("text", "")
                for b in blocks
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            combined = "\n".join(text_parts)
            try:
                return self._extract_json_object(combined)
            except (json.JSONDecodeError, ValueError) as exc:
                last_err = exc
                payload["messages"] = [
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": combined},
                    {
                        "role": "user",
                        "content": "Return ONLY a valid RFC8259 JSON object matching the schema without markdown fences.",
                    },
                ]
        raise ExternalApiError(
            provider=self.provider_name,
            code="ANTHROPIC_INVALID_JSON",
            message=f"Claude 응답을 JSON으로 파싱하지 못했습니다: {last_err}",
            retryable=True,
        )
