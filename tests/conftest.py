from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.database import init_db
from app.core.job_manager import JobManager
from app.main import create_app


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mpl_dir = tmp_path / "mpl"
    mpl_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MPLCONFIGDIR", str(mpl_dir))
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("PERPLEXITY_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "")
    monkeypatch.setenv("APIFY_API_TOKEN", "")
    monkeypatch.setenv("X_NCP_APIGW_API_KEY_ID", "")
    monkeypatch.setenv("X_NCP_APIGW_API_KEY", "")
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def test_session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    await init_db(engine)
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def async_client(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    app.state.session_factory = test_session_factory
    app.state.job_manager = JobManager(test_session_factory)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
