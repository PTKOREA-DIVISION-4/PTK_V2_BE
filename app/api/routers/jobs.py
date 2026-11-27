from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_job_manager, get_session_factory
from app.core.exceptions import NotFoundError
from app.core.job_manager import JobManager
from app.repositories.job_repo import JobRepository
from app.schemas.common import ErrorEnvelope
from app.schemas.job import JobStatusResponse

router = APIRouter(prefix="/jobs", tags=["Async Jobs & Progress"])


def _to_response(job) -> JobStatusResponse:
    return JobStatusResponse(
        id=job.id,
        project_id=job.project_id,
        job_type=job.job_type,
        status=job.status,
        progress_pct=job.progress_pct,
        logs=list(job.logs_json or []),
        error_message=job.error_message,
        subtasks=[
            {
                "id": s.id,
                "subtask_key": s.subtask_key,
                "label": s.label,
                "status": s.status,
                "progress_pct": s.progress_pct,
                "collected_count": s.collected_count,
                "error_message": s.error_message,
            }
            for s in (job.subtasks or [])
        ],
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
    )


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="비동기 작업 상태 및 서브태스크 진행률 폴링 조회",
)
async def get_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> JobStatusResponse:
    job = await JobRepository(db).get_by_id(job_id)
    if not job:
        raise NotFoundError(f"작업({job_id})을 찾을 수 없습니다.")
    return _to_response(job)


@router.get(
    "/{job_id}/stream",
    summary="비동기 작업 진행률 실시간 SSE(Server-Sent Events) 스트리밍",
)
async def stream_job_status(
    job_id: str,
    session_factory=Depends(get_session_factory),
) -> StreamingResponse:
    async def event_generator():
        while True:
            async with session_factory() as session:
                job = await JobRepository(session).get_by_id(job_id)
                if not job:
                    yield f"event: error\ndata: {json.dumps({'message': 'Job not found'})}\n\n"
                    break
                payload = _to_response(job).model_dump(mode="json")
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if job.status in {"COMPLETED", "PARTIAL_SUCCESS", "FAILED", "CANCELLED"}:
                    break
            await asyncio.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post(
    "/{job_id}/cancel",
    response_model=JobStatusResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="실행 중인 비동기 작업 취소",
)
async def cancel_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    job_manager: JobManager = Depends(get_job_manager),
) -> JobStatusResponse:
    job = await job_manager.cancel_job(db, job_id)
    return _to_response(job)
