from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app.core.config import get_settings


class ResponseCache:
    """Content-addressable JSON cache backed by local filesystem with TTL."""

    def __init__(self, cache_dir: Path | None = None, default_ttl: int | None = None) -> None:
        settings = get_settings()
        self.cache_dir = cache_dir or settings.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = settings.CACHE_TTL_SECONDS if default_ttl is None else default_ttl

    @staticmethod
    def build_key(provider: str, endpoint: str, params: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"provider": provider, "endpoint": endpoint, "params": params},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _path_for_key(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(
        self,
        provider: str,
        endpoint: str,
        params: dict[str, Any],
        *,
        ttl_seconds: int | None = None,
        force_refresh: bool = False,
    ) -> Any | None:
        if force_refresh:
            return None
        key = self.build_key(provider, endpoint, params)
        path = self._path_for_key(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        ttl = self.default_ttl if ttl_seconds is None else ttl_seconds
        stored_at = float(payload.get("stored_at", 0.0))
        if ttl > 0 and (time.time() - stored_at) > ttl:
            return None
        return payload.get("data")

    def set(
        self,
        provider: str,
        endpoint: str,
        params: dict[str, Any],
        data: Any,
    ) -> None:
        key = self.build_key(provider, endpoint, params)
        path = self._path_for_key(key)
        envelope = {
            "provider": provider,
            "endpoint": endpoint,
            "stored_at": time.time(),
            "data": data,
        }
        try:
            path.write_text(
                json.dumps(envelope, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except OSError:
            # Caching must never break business pipelines
            pass
