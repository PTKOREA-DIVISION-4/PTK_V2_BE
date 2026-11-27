from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ErrorEnvelope
from app.schemas.export import ExportCreateRequest, ExportRecordResponse
from app.schemas.qc import QcReportResponse
from app.services.ppt_export_service import PptExportService

router = APIRouter(prefix="/projects/{project_id}/exports", tags=["Step 4. Pre-flight QC & PPTX Export"])


@router.post(
    "/qc",
    response_model=QcReportResponse,
    responses={404: {"model": ErrorEnvelope}},
    summary="PPT 출력 전 4대 사전 품질 검증(Pre-flight QC) 실행",
)
async def run_qc_check(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> QcReportResponse:
    return await PptExportService(db).run_qc(project_id)


@router.post(
    "/pptx",
    response_model=ExportRecordResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
    summary="사전 QC 검증 통과 시 0~5장 표준 목차 PPTX 파일 생성",
)
async def create_pptx_export(
    project_id: str,
    payload: ExportCreateRequest = ExportCreateRequest(),
    db: AsyncSession = Depends(get_db),
) -> ExportRecordResponse:
    return await PptExportService(db).export_pptx(project_id, payload)


@router.get(
    "",
    response_model=list[ExportRecordResponse],
    responses={404: {"model": ErrorEnvelope}},
    summary="생성된 PPTX 출력 이력 목록 조회",
)
async def list_exports(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[ExportRecordResponse]:
    return await PptExportService(db).list_exports(project_id)


@router.get(
    "/{export_id}/download",
    responses={404: {"model": ErrorEnvelope}},
    summary="생성된 PPTX 파일 바이너리 다운로드",
)
async def download_pptx(
    project_id: str,
    export_id: str,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    path, filename = await PptExportService(db).get_download_path(project_id, export_id)
    return FileResponse(
        path=str(path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
