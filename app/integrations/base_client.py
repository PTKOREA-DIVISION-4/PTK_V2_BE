from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from app.core.cache import ResponseCache
from app.core.config import get_settings
from app.core.exceptions import ExternalApiError


class _RetryableHttpError(Exception):
    def __init__(self, status_code: int, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retry_after = retry_after


class BaseApiClient:
    """Shared async HTTP client with concurrency semaphore, exponential backoff, and caching."""

    provider_name: str = "base"

    def __init__(
        self,
        *,
        base_url: str,
        max_concurrency: int = 3,
        timeout_seconds: float | None = None,
        cache: ResponseCache | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds or settings.HTTP_TIMEOUT_SECONDS
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self.cache = cache or ResponseCache()

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        cache_key_params: dict[str, Any] | None = None,
        force_refresh: bool = False,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        cache_params = cache_key_params or {
            "method": method,
            "params": params or {},
            "json": json_body or {},
        }
        if not force_refresh:
            cached = self.cache.get(
                self.provider_name, path, cache_params, force_refresh=force_refresh
            )
            if isinstance(cached, dict):
                return cached

        url = path if path.startswith("http") else f"{self.base_url}{path}"
        last_exc: Exception | None = None

        async with self._semaphore:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                for attempt in range(1, max_attempts + 1):
                    try:
                        response = await client.request(
                            method=method,
                            url=url,
                            headers=headers,
                            params=params,
                            json=json_body,
                        )
                        if response.status_code in {429, 500, 502, 503, 504}:
                            retry_after_raw = response.headers.get("Retry-After")
                            retry_after = (
                                float(retry_after_raw)
                                if retry_after_raw and retry_after_raw.isdigit()
                                else None
                            )
                            raise _RetryableHttpError(
                                response.status_code,
                                response.text[:300],
                                retry_after=retry_after,
                            )
                        if response.status_code >= 400:
                            raise ExternalApiError(
                                provider=self.provider_name,
                                code=f"{self.provider_name.upper()}_HTTP_{response.status_code}",
                                message=f"{self.provider_name} 요청 오류 (HTTP {response.status_code})",
                                details=[{"body": response.text[:300]}],
                                retryable=False,
                            )
                        data = response.json()
                        if not isinstance(data, dict):
                            data = {"items": data}
                        self.cache.set(self.provider_name, path, cache_params, data)
                        return data
                    except _RetryableHttpError as exc:
                        last_exc = exc
                        if attempt >= max_attempts:
                            break
                        backoff = exc.retry_after or ((2 ** attempt) + random.uniform(0.1, 0.8))
                        await asyncio.sleep(min(backoff, 20.0))
                    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                        last_exc = exc
                        if attempt >= max_attempts:
                            break
                        backoff = (2 ** attempt) + random.uniform(0.1, 0.8)
                        await asyncio.sleep(min(backoff, 15.0))
                    except ExternalApiError:
                        raise

        raise ExternalApiError(
            provider=self.provider_name,
            code=f"{self.provider_name.upper()}_UNAVAILABLE",
            message=f"{self.provider_name} 호출이 {max_attempts}회 재시도 후 실패했습니다: {last_exc}",
            retryable=True,
        )
