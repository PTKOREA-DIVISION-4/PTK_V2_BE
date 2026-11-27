from __future__ import annotations

from pathlib import Path

from pptx import Presentation

from app.models.collection import DataLabSeries
from app.models.factbook import SlideDraft
from app.models.project import Project
from app.services.ppt_renderer.slide_builders import SlideBuilder
from app.services.ppt_renderer.theme import SLIDE_HEIGHT, SLIDE_WIDTH


SECTION_ORDER = {
    "0_OVERVIEW": 0,
    "1_OWN": 1,
    "2_MARKET": 2,
    "3_COMPETITOR": 3,
    "4_CONSUMER": 4,
    "5_SUMMARY_CONCLUSION": 5,
}


class PPTXRenderer:
    """Assembles the full 0~5 standard-outline 16:9 Factbook PPTX deck."""

    def render(
        self,
        *,
        project: Project,
        slides: list[SlideDraft],
        datalab_series: list[DataLabSeries],
        output_path: Path,
    ) -> int:
        prs = Presentation()
        prs.slide_width = SLIDE_WIDTH
        prs.slide_height = SLIDE_HEIGHT

        ordered = sorted(
            slides,
            key=lambda s: (SECTION_ORDER.get(s.section_code, 99), s.slide_order),
        )

        builder = SlideBuilder(work_dir=output_path.parent / "charts")
        builder.add_cover_slide(prs, project, total_body_slides=len(ordered))

        for idx, draft in enumerate(ordered, start=1):
            builder.build_content_slide(
                prs,
                draft,
                datalab_series=datalab_series,
                slide_number=idx,
                total_slides=len(ordered),
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(output_path))
        return len(prs.slides)
