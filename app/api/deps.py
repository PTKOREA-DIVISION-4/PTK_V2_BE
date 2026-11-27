from __future__ import annotations

from fastapi import Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.core.job_manager import JobManager


def get_job_manager(request: Request) -> JobManager:
    jm = getattr(request.app.state, "job_manager", None)
    if jm is None:
        jm = JobManager(AsyncSessionLocal)
        request.app.state.job_manager = jm
    return jm


def get_session_factory(request: Request):
    return getattr(request.app.state, "session_factory", AsyncSessionLocal)


def get_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str | None:
    return idempotency_key.strip() if idempotency_key else None


__all__ = ["AsyncSession", "get_db", "get_job_manager", "get_session_factory", "get_idempotency_key"]
