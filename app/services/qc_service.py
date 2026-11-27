from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories.project_repo import ProjectRepository
from app.repositories.slide_draft_repo import SlideDraftRepository
from app.repositories.source_item_repo import SourceItemRepository
from app.schemas.common import QcSeverity, SectionCode, SummarySplitMode
from app.schemas.qc import QcCheckItem, QcReportResponse


class QcService:
    """4-Gate Pre-flight Quality Control blocking incomplete, empty, or ungrounded PPTX exports."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.project_repo = ProjectRepository(session)
        self.slide_repo = SlideDraftRepository(session)
        self.source_repo = SourceItemRepository(session)

    async def evaluate_project(self, project_id: str) -> QcReportResponse:
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError(f"프로젝트({project_id})를 찾을 수 없습니다.")

        slides = await self.slide_repo.list_by_project(project_id)
        datalab_series = await self.source_repo.list_datalab(project_id)
        split_mode = SummarySplitMode(project.summary_split_mode)

        checks: list[QcCheckItem] = []

        # Gate 1: Required Sections (0_OVERVIEW through 5_SUMMARY_CONCLUSION)
        present_set = {s.section_code for s in slides}
        present_sections = [sec for sec in SectionCode if sec.value in present_set]
        missing_sections = [sec for sec in SectionCode if sec.value not in present_set]

        if not slides:
            checks.append(
                QcCheckItem(
                    gate_code="REQUIRED_SECTIONS",
                    severity=QcSeverity.BLOCKER,
                    message="생성된 슬라이드 초안이 없습니다. 최소 0~5장 표준 섹션이 모두 존재해야 합니다.",
                    user_action_hint="자료 검수 완료 후 '0~5장 장표 초안 생성'을 먼저 실행해 주세요.",
                )
            )
        elif missing_sections:
            missing_names = ", ".join(m.value for m in missing_sections)
            checks.append(
                QcCheckItem(
                    gate_code="REQUIRED_SECTIONS",
                    severity=QcSeverity.BLOCKER,
                    message=f"필수 목차 섹션이 누락되어 출력할 수 없습니다: {missing_names}",
                    target_section=missing_sections[0],
                    user_action_hint="누락된 섹션을 포함하여 장표 초안을 다시 생성해 주세요.",
                )
            )
        else:
            checks.append(
                QcCheckItem(
                    gate_code="REQUIRED_SECTIONS",
                    severity=QcSeverity.PASS,
                    message="0. 분석 개요 ~ 5. 현황 요약 및 결론 전체 표준 섹션이 모두 구성되었습니다.",
                )
            )
            if len(slides) >= 6 and not any(s.slide_type == "INDEX" for s in slides):
                checks.append(
                    QcCheckItem(
                        gate_code="REQUIRED_SECTIONS",
                        severity=QcSeverity.WARNING,
                        message="목차(INDEX) 슬라이드가 누락되었습니다. 전체 장표 탐색을 위해 포함을 권장합니다.",
                        target_section=SectionCode.OVERVIEW,
                        user_action_hint="장표 초안을 다시 생성해 목차 슬라이드를 포함하세요.",
                    )
                )

        # Gate 2: No Empty Slides (every slide must have headcopy & concrete body content)
        empty_found = False
        for s in slides:
            has_headcopy = bool((s.headcopy or "").strip())
            has_body = any(
                [
                    bool(s.bullets_json),
                    bool(s.kpi_cards_json),
                    bool(s.table_json and (s.table_json.get("rows") or [])),
                    bool(s.visual_assets_json),
                    bool(
                        s.as_is_to_be_json
                        and (
                            s.as_is_to_be_json.get("as_is_points")
                            or s.as_is_to_be_json.get("to_be_directions")
                        )
                    ),
                ]
            )
            if not has_headcopy or not has_body:
                empty_found = True
                checks.append(
                    QcCheckItem(
                        gate_code="NO_EMPTY_SLIDES",
                        severity=QcSeverity.BLOCKER,
                        message=f"빈 장표 감지: '{s.title}' 슬라이드에 리드 문장 또는 본문 데이터가 비어 있습니다.",
                        target_section=SectionCode(s.section_code),
                        target_slide_id=s.id,
                        user_action_hint="해당 슬라이드로 이동해 리드 문장과 팩트/코멘트를 채워 주세요.",
                    )
                )
        if slides and not empty_found:
            checks.append(
                QcCheckItem(
                    gate_code="NO_EMPTY_SLIDES",
                    severity=QcSeverity.PASS,
                    message=f"전체 {len(slides)}장 슬라이드에 리드 문장과 본문 콘텐츠가 정상 채워져 있습니다.",
                )
            )

        # Gate 3: Evidence & DataLab Transparent Basis
        bad_datalab = [
            d for d in datalab_series if not (d.methodology_note or "").strip()
        ]
        if bad_datalab:
            checks.append(
                QcCheckItem(
                    gate_code="EVIDENCE_AND_DATALAB_BASIS",
                    severity=QcSeverity.BLOCKER,
                    message="데이터랩 지표에 출처·기간·산출 기준(methodology_note)이 누락되었습니다.",
                    target_section=SectionCode.COMPETITOR,
                    user_action_hint="네이버 데이터랩 수집을 다시 실행해 기준 표기를 생성해 주세요.",
                )
            )
        else:
            ungrounded_slides = [
                s for s in slides if s.bullets_json and not (s.footnote or "").strip()
            ]
            if ungrounded_slides:
                checks.append(
                    QcCheckItem(
                        gate_code="EVIDENCE_AND_DATALAB_BASIS",
                        severity=QcSeverity.WARNING,
                        message=f"출처 각주가 비어 있는 슬라이드가 {len(ungrounded_slides)}장 있습니다.",
                        target_section=SectionCode(ungrounded_slides[0].section_code),
                        target_slide_id=ungrounded_slides[0].id,
                        user_action_hint="슬라이드 하단 출처 표기를 보완하는 것을 권장합니다.",
                    )
                )
            else:
                checks.append(
                    QcCheckItem(
                        gate_code="EVIDENCE_AND_DATALAB_BASIS",
                        severity=QcSeverity.PASS,
                        message="모든 데이터랩 산식 기준 표기 및 장표별 출처 각주가 확인되었습니다.",
                    )
                )

        # Gate 4: Media Assets Integrity & Summary Split / Overflow Guard
        summary_parts = [
            s
            for s in slides
            if s.section_code == SectionCode.SUMMARY_CONCLUSION.value
            and s.slide_type == "SUMMARY_PART"
        ]
        if slides and len(summary_parts) < 2:
            checks.append(
                QcCheckItem(
                    gate_code="MEDIA_AND_OVERFLOW",
                    severity=QcSeverity.BLOCKER,
                    message="현황 요약(Summary)은 1장 과밀 압축을 방지하기 위해 최소 2장 또는 4장 분할 구성이 필요합니다.",
                    target_section=SectionCode.SUMMARY_CONCLUSION,
                    user_action_hint="요약 분할 모드(SPLIT_2 또는 SPLIT_4)를 선택해 요약 장표를 재구성해 주세요.",
                )
            )
        else:
            missing_media_count = 0
            for s in slides:
                for asset in s.visual_assets_json or []:
                    lp = asset.get("local_path")
                    if lp and not Path(lp).exists():
                        missing_media_count += 1
            if missing_media_count > 0:
                checks.append(
                    QcCheckItem(
                        gate_code="MEDIA_AND_OVERFLOW",
                        severity=QcSeverity.WARNING,
                        message=f"참조 이미지 파일 {missing_media_count}건이 디스크에서 확인되지 않아 대체 카드 레이아웃으로 출력됩니다.",
                        user_action_hint="필요 시 미디어 아카이빙 서브태스크를 재실행하세요.",
                    )
                )
            else:
                checks.append(
                    QcCheckItem(
                        gate_code="MEDIA_AND_OVERFLOW",
                        severity=QcSeverity.PASS,
                        message=f"Summary {len(summary_parts)}장 분할 구성 및 참조 이미지 무결성이 확인되었습니다.",
                    )
                )

        severities = [c.severity for c in checks]
        if QcSeverity.BLOCKER in severities:
            overall = QcSeverity.BLOCKER
        elif QcSeverity.WARNING in severities:
            overall = QcSeverity.WARNING
        else:
            overall = QcSeverity.PASS

        return QcReportResponse(
            project_id=project_id,
            overall_status=overall,
            can_export=(overall != QcSeverity.BLOCKER),
            summary_split_mode=split_mode,
            total_slides_checked=len(slides),
            present_sections=present_sections,
            missing_sections=missing_sections,
            checks=checks,
        )
