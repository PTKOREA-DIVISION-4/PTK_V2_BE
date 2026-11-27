from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError
from app.models.job import AsyncJob, JobSubtask


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


JobCoroutineFactory = Callable[["JobContext"], Awaitable[None]]


class JobContext:
    """Thread-safe/async helper passed into background jobs to report subtask progress & logs."""

    def __init__(
        self,
        *,
        job_id: str,
        project_id: str,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.job_id = job_id
        self.project_id = project_id
        self.session_factory = session_factory
        self._lock = asyncio.Lock()

    async def append_log(self, message: str) -> None:
        async with self._lock:
            async with self.session_factory() as session:
                job = await session.get(AsyncJob, self.job_id)
                if not job:
                    return
                logs = list(job.logs_json or [])
                timestamp = utcnow().strftime("%H:%M:%S")
                logs.append(f"[{timestamp}] {message}")
                job.logs_json = logs[-100:]
                await session.commit()

    async def update_subtask(
        self,
        subtask_key: str,
        *,
        status: str | None = None,
        progress_pct: int | None = None,
        collected_count: int | None = None,
        error_message: str | None = None,
        log_message: str | None = None,
    ) -> None:
        async with self._lock:
            async with self.session_factory() as session:
                stmt = (
                    select(AsyncJob)
                    .options(selectinload(AsyncJob.subtasks))
                    .where(AsyncJob.id == self.job_id)
                )
                result = await session.execute(stmt)
                job = result.scalar_one_or_none()
                if not job:
                    return

                target = next(
                    (s for s in job.subtasks if s.subtask_key == subtask_key),
                    None,
                )
                if target:
                    if status is not None:
                        target.status = status
                    if progress_pct is not None:
                        target.progress_pct = max(0, min(100, progress_pct))
                    if collected_count is not None:
                        target.collected_count = collected_count
                    if error_message is not None:
                        target.error_message = error_message[:1000]

                if job.subtasks:
                    avg = sum(s.progress_pct for s in job.subtasks) / len(job.subtasks)
                    job.progress_pct = int(round(avg))

                if log_message:
                    logs = list(job.logs_json or [])
                    timestamp = utcnow().strftime("%H:%M:%S")
                    logs.append(f"[{timestamp}] [{subtask_key}] {log_message}")
                    job.logs_json = logs[-100:]

                await session.commit()

    async def set_progress(self, progress_pct: int, log_message: str | None = None) -> None:
        async with self._lock:
            async with self.session_factory() as session:
                job = await session.get(AsyncJob, self.job_id)
                if not job:
                    return
                job.progress_pct = max(0, min(100, progress_pct))
                if log_message:
                    logs = list(job.logs_json or [])
                    timestamp = utcnow().strftime("%H:%M:%S")
                    logs.append(f"[{timestamp}] {log_message}")
                    job.logs_json = logs[-100:]
                await session.commit()


class JobManager:
    """Coordinates long-running collection, structuring, and PPTX export jobs."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}

    async def get_active_job(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        job_type: str,
    ) -> AsyncJob | None:
        stmt = (
            select(AsyncJob)
            .where(
                AsyncJob.project_id == project_id,
                AsyncJob.job_type == job_type,
                AsyncJob.status.in_(["PENDING", "RUNNING"]),
            )
            .order_by(AsyncJob.created_at.desc())
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    async def find_by_idempotency_key(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        job_type: str,
        idempotency_key: str,
    ) -> AsyncJob | None:
        stmt = (
            select(AsyncJob)
            .options(selectinload(AsyncJob.subtasks))
            .where(
                AsyncJob.project_id == project_id,
                AsyncJob.job_type == job_type,
                AsyncJob.idempotency_key == idempotency_key,
            )
            .order_by(AsyncJob.created_at.desc())
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    async def start_job(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        job_type: str,
        subtasks: list[tuple[str, str]],
        coro_factory: JobCoroutineFactory,
        idempotency_key: str | None = None,
    ) -> AsyncJob:
        if idempotency_key:
            existing_idem = await self.find_by_idempotency_key(
                session,
                project_id=project_id,
                job_type=job_type,
                idempotency_key=idempotency_key,
            )
            if existing_idem is not None:
                return existing_idem

        active = await self.get_active_job(
            session, project_id=project_id, job_type=job_type
        )
        if active is not None:
            raise ConflictError(
                message=f"이미 진행 중인 {job_type} 작업({active.id})이 있습니다.",
                code="JOB_ALREADY_RUNNING",
                details=[{"active_job_id": active.id}],
            )

        job = AsyncJob(
            project_id=project_id,
            job_type=job_type,
            status="PENDING",
            progress_pct=0,
            idempotency_key=idempotency_key,
            logs_json=[f"[{utcnow().strftime('%H:%M:%S')}] 작업이 대기열에 등록되었습니다."],
        )
        session.add(job)
        await session.flush()

        for key, label in subtasks:
            session.add(
                JobSubtask(
                    job_id=job.id,
                    subtask_key=key,
                    label=label,
                    status="PENDING",
                    progress_pct=0,
                    collected_count=0,
                )
            )
        await session.commit()

        stmt = (
            select(AsyncJob)
            .options(selectinload(AsyncJob.subtasks))
            .where(AsyncJob.id == job.id)
        )
        created = (await session.execute(stmt)).scalar_one()

        ctx = JobContext(
            job_id=created.id,
            project_id=project_id,
            session_factory=self.session_factory,
        )
        task = asyncio.create_task(self._run_wrapper(created.id, ctx, coro_factory))
        self._running_tasks[created.id] = task
        task.add_done_callback(lambda _: self._running_tasks.pop(created.id, None))
        return created

    async def _run_wrapper(
        self,
        job_id: str,
        ctx: JobContext,
        coro_factory: JobCoroutineFactory,
    ) -> None:
        async with self.session_factory() as session:
            job = await session.get(AsyncJob, job_id)
            if not job:
                return
            job.status = "RUNNING"
            job.started_at = utcnow()
            await session.commit()

        try:
            await coro_factory(ctx)
        except asyncio.CancelledError:
            async with self.session_factory() as session:
                job = await session.get(AsyncJob, job_id)
                if job:
                    job.status = "CANCELLED"
                    job.finished_at = utcnow()
                    logs = list(job.logs_json or [])
                    logs.append(f"[{utcnow().strftime('%H:%M:%S')}] 사용자 요청으로 작업이 취소되었습니다.")
                    job.logs_json = logs[-100:]
                    await session.commit()
            return
        except Exception as exc:
            async with self.session_factory() as session:
                job = await session.get(AsyncJob, job_id)
                if job:
                    job.status = "FAILED"
                    job.error_message = str(exc)[:1000]
                    job.finished_at = utcnow()
                    logs = list(job.logs_json or [])
                    logs.append(f"[{utcnow().strftime('%H:%M:%S')}] 치명적 오류: {exc}")
                    job.logs_json = logs[-100:]
                    await session.commit()
            return

        async with self.session_factory() as session:
            stmt = (
                select(AsyncJob)
                .options(selectinload(AsyncJob.subtasks))
                .where(AsyncJob.id == job_id)
            )
            job = (await session.execute(stmt)).scalar_one_or_none()
            if not job:
                return
            subtasks = list(job.subtasks)
            if subtasks:
                failed = [s for s in subtasks if s.status == "FAILED"]
                succeeded = [s for s in subtasks if s.status == "COMPLETED"]
                if failed and succeeded:
                    job.status = "PARTIAL_SUCCESS"
                elif failed and not succeeded:
                    job.status = "FAILED"
                else:
                    job.status = "COMPLETED"
                    job.progress_pct = 100
            else:
                job.status = "COMPLETED"
                job.progress_pct = 100
            job.finished_at = utcnow()
            await session.commit()

    async def cancel_job(self, session: AsyncSession, job_id: str) -> AsyncJob:
        stmt = (
            select(AsyncJob)
            .options(selectinload(AsyncJob.subtasks))
            .where(AsyncJob.id == job_id)
        )
        job = (await session.execute(stmt)).scalar_one_or_none()
        if not job:
            raise NotFoundError(f"작업({job_id})을 찾을 수 없습니다.")
        if job.status in ("COMPLETED", "FAILED", "CANCELLED", "PARTIAL_SUCCESS"):
            return job
        task = self._running_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
        else:
            job.status = "CANCELLED"
            job.finished_at = utcnow()
            await session.commit()
        return job

    async def wait_for_job(self, job_id: str, timeout: float = 30.0) -> None:
        """Helper mainly for tests or synchronous awaiters to await completion."""
        task = self._running_tasks.get(job_id)
        if task:
            await asyncio.wait_for(task, timeout=timeout)
