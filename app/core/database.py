from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def build_engine(database_url: str | None = None, echo: bool | None = None) -> AsyncEngine:
    settings = get_settings()
    url = database_url or settings.DATABASE_URL
    is_sqlite = url.startswith("sqlite")

    kwargs: dict[str, Any] = {
        "echo": settings.DEBUG if echo is None else echo,
        "future": True,
    }
    if not is_sqlite:
        kwargs.update(
            {
                "pool_pre_ping": True,
                "pool_recycle": 1800,
                "pool_size": 10,
                "max_overflow": 20,
            }
        )
    return create_async_engine(url, **kwargs)


engine: AsyncEngine = build_engine()
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async SQLAlchemy session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db(target_engine: AsyncEngine | None = None) -> None:
    """Create all ORM tables if they do not exist yet."""
    from app.models import Base  # noqa: F401 - ensures all models are registered

    eng = target_engine or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
