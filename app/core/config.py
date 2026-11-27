from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings loaded securely from backend/.env."""

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    APP_NAME: str = "PTKOREA Factbook API"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # MySQL 8.0 (utf8mb4)
    DATABASE_URL: str = (
        "mysql+aiomysql://factbook:factbook_pw@127.0.0.1:3306/factbook?charset=utf8mb4"
    )
    DATABASE_SYNC_URL: str = (
        "mysql+pymysql://factbook:factbook_pw@127.0.0.1:3306/factbook?charset=utf8mb4"
    )
    DB_AUTO_CREATE_TABLES: bool = True

    # External API keys (strictly kept on backend)
    PERPLEXITY_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    SCRAPECREATORS_API_KEY: str = ""
    APIFY_API_TOKEN: str = ""

    X_NCP_APIGW_API_KEY_ID: str = Field(
        default="",
        validation_alias=AliasChoices(
            "X_NCP_APIGW_API_KEY_ID",
            "X-NCP-APIGW-API-KEY-ID",
            "NCP_APIGW_API_KEY_ID",
        ),
    )
    X_NCP_APIGW_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices(
            "X_NCP_APIGW_API_KEY",
            "X-NCP-APIGW-API-KEY",
            "NCP_APIGW_API_KEY",
        ),
    )

    # Endpoints & model defaults
    PERPLEXITY_BASE_URL: str = "https://api.perplexity.ai"
    PERPLEXITY_MODEL: str = "sonar-pro"

    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    ANTHROPIC_MODEL: str = "claude-sonnet-5-5"

    SCRAPECREATORS_BASE_URL: str = "https://api.scrapecreators.com"
    APIFY_BASE_URL: str = "https://api.apify.com/v2"
    NAVER_APIGW_BASE_URL: str = "https://naverapihub.apigw.ntruss.com"

    DEFAULT_NAVER_SHOPPING_CATEGORY_ID: str = "50000002"

    # Storage, Cache & Concurrency
    STORAGE_ROOT: str = "./storage"
    CACHE_TTL_SECONDS: int = 86400
    HTTP_TIMEOUT_SECONDS: float = 45.0
    MAX_CONCURRENT_PERPLEXITY: int = 3
    MAX_CONCURRENT_NAVER: int = 5
    MAX_CONCURRENT_SCRAPECREATORS: int = 4
    MAX_CONCURRENT_APIFY: int = 3
    MAX_CONCURRENT_ANTHROPIC: int = 3

    @property
    def storage_root_path(self) -> Path:
        raw = Path(self.STORAGE_ROOT)
        if raw.is_absolute():
            return raw
        return (BACKEND_ROOT / raw).resolve()

    @property
    def media_dir(self) -> Path:
        path = self.storage_root_path / "media"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def exports_dir(self) -> Path:
        path = self.storage_root_path / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def cache_dir(self) -> Path:
        path = self.storage_root_path / "cache"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def api_key_readiness(self) -> dict[str, bool]:
        """Return non-sensitive boolean availability of configured external providers."""
        return {
            "perplexity": bool(self.PERPLEXITY_API_KEY.strip()),
            "anthropic": bool(self.ANTHROPIC_API_KEY.strip()),
            "scrapecreators": bool(self.SCRAPECREATORS_API_KEY.strip()),
            "apify": bool(self.APIFY_API_TOKEN.strip()),
            "naver_datalab": bool(
                self.X_NCP_APIGW_API_KEY_ID.strip() and self.X_NCP_APIGW_API_KEY.strip()
            ),
        }

    def model_post_init(self, __context: Any) -> None:
        # Ensure base storage directories exist on settings initialization
        _ = self.media_dir
        _ = self.exports_dir
        _ = self.cache_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
