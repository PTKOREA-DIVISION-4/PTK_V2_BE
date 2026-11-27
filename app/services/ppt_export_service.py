from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, QcBlockedError
from app.models.job import ExportRecord
from app.repositories.export_repo import ExportRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.slide_draft_repo import SlideDraftRepository
from app.repositories.source_item_repo import SourceItemRepository
from app.schemas.common import ProjectStage, QcSeverity, SummarySplitMode
from app.schemas.export import ExportCreateRequest, ExportRecordResponse
from app.schemas.qc import QcReportResponse
from app.services.ppt_renderer.renderer import PPTXRenderer
from app.services.qc_service import QcService


class PptExportService:
    """Runs Pre-flight QC gate and generates downloadable 0~5 standard-outline PPTX files."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.project_repo = ProjectRepository(session)
        self.slide_repo = SlideDraftRepository(session)
        self.source_repo = SourceItemRepository(session)
        self.export_repo = ExportRepository(session)
        self.qc_service = QcService(session)
        self.renderer = PPTXRenderer()

    async def run_qc(self, project_id: str) -> QcReportResponse:
        return await self.qc_service.evaluate_project(project_id)

    async def export_pptx(
        self, project_id: str, payload: ExportCreateRequest
    ) -> ExportRecordResponse:
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")

        qc_report = await self.qc_service.evaluate_project(project_id)
        if not qc_report.can_export:
            raise QcBlockedError(
                message="사전 품질 검증(QC)에서 차단 항목(BLOCKER)이 발견되어 PPTX를 생성할 수 없습니다.",
                details=[c.model_dump() for c in qc_report.checks if c.severity == QcSeverity.BLOCKER],
            )
        if not payload.allow_warnings and qc_report.overall_status == QcSeverity.WARNING:
            raise QcBlockedError(
                message="경고(WARNING) 항목이 존재하며 allow_warnings=false로 요청되었습니다.",
                details=[c.model_dump() for c in qc_report.checks if c.severity == QcSeverity.WARNING],
            )

        slides = await self.slide_repo.list_by_project(project_id)
        datalab = await self.source_repo.list_datalab(project_id)

        settings = get_settings()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_brand = "".join(c for c in project.brand_name if c.isalnum() or c in "-_") or "factbook"
        filename = f"Factbook_{safe_brand}_{ts}.pptx"
        output_path = settings.exports_dir / project_id / filename

        rendered_count = self.renderer.render(
            project=project,
            slides=slides,
            datalab_series=datalab,
            output_path=output_path,
        )
        file_size = output_path.stat().st_size if output_path.exists() else 0

        record = ExportRecord(
            project_id=project_id,
            qc_status=qc_report.overall_status.value,
            qc_report_json=qc_report.model_dump(mode="json"),
            summary_split_mode=project.summary_split_mode,
            slide_count=rendered_count,
            file_path=str(output_path),
            file_size_bytes=file_size,
            download_filename=filename,
        )
        await self.export_repo.create(record)
        project.current_stage = ProjectStage.EXPORT.value
        await self.session.commit()
        return self._to_response(record, qc_report)

    async def list_exports(self, project_id: str) -> list[ExportRecordResponse]:
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")
        rows = await self.export_repo.list_by_project(project_id)
        return [
            self._to_response(r, QcReportResponse.model_validate(r.qc_report_json))
            for r in rows
        ]

    async def get_download_path(self, project_id: str, export_id: str) -> tuple[Path, str]:
        record = await self.export_repo.get_by_id(project_id, export_id)
        if not record or not record.file_path:
            raise NotFoundError(f"출력 이력({export_id})을 찾을 수 없습니다.")
        path = Path(record.file_path)
        if not path.exists():
            raise NotFoundError("생성된 PPTX 파일이 스토리지에 존재하지 않습니다.")
        return path, (record.download_filename or path.name)

    @staticmethod
    def _to_response(record: ExportRecord, qc_report: QcReportResponse) -> ExportRecordResponse:
        return ExportRecordResponse(
            id=record.id,
            project_id=record.project_id,
            job_id=record.job_id,
            qc_status=QcSeverity(record.qc_status),
            qc_report=qc_report,
            summary_split_mode=SummarySplitMode(record.summary_split_mode),
            slide_count=record.slide_count,
            file_size_bytes=record.file_size_bytes,
            download_filename=record.download_filename,
            download_url=f"/api/v1/projects/{record.project_id}/exports/{record.id}/download",
            created_at=record.created_at,
        )
