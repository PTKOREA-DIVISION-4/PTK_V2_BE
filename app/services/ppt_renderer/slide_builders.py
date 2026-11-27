from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
from pptx.slide import Slide
from pptx.util import Inches, Pt

from app.models.collection import DataLabSeries
from app.models.factbook import SlideDraft
from app.models.project import Project
from app.services.deck_blueprint import clean_slide_text, smart_truncate
from app.services.ppt_renderer.channel_icons import normalize_channel_key, render_channel_icon
from app.services.ppt_renderer.chart_builder import (
    build_consumer_sentiment_chart,
    build_datalab_trend_chart,
    build_horizontal_bar_chart,
    build_marketing_heatmap_chart,
    build_press_brand_chart,
    build_press_monthly_chart,
    build_price_discount_chart,
    build_share_of_search_chart,
)
from app.services.ppt_renderer.media_layout import add_contained_image, render_sns_top5_grid
from app.services.ppt_renderer.theme import (
    COLOR_AMBER,
    COLOR_BLACK,
    COLOR_BORDER,
    COLOR_BORDER_STRONG,
    COLOR_GREEN,
    COLOR_MUTED_BG,
    COLOR_ORANGE,
    COLOR_SURFACE,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_SUB,
    COLOR_WHITE,
    FONT_FAMILY,
    SECTION_BADGE_LABELS,
    SLIDE_HEIGHT,
    SLIDE_WIDTH,
    TYPO_BODY,
    TYPO_DISPLAY,
    TYPO_FOOTNOTE,
    TYPO_HEADCOPY,
    TYPO_KPI_VALUE,
    TYPO_LABEL,
    TYPO_PANEL_TITLE,
    TYPO_SECTION,
    TYPO_SLIDE_TITLE,
    TYPO_TABLE_CELL,
    TYPO_TABLE_HEADER,
)


def _format_url_label(url: str) -> str:
    try:
        host = urlparse(url).netloc.replace("www.", "")
        return f"{host} ↗" if host else "출처 링크 ↗"
    except Exception:
        return "출처 링크 ↗"


def _add_hyperlink_run(
    paragraph: Any,
    *,
    label: str,
    url: str,
    size: Any = TYPO_FOOTNOTE,
    color: RGBColor = COLOR_ORANGE,
    bold: bool = True,
) -> None:
    run = paragraph.add_run()
    run.text = label
    run.font.name = FONT_FAMILY
    run.font.size = size
    run.font.bold = bold
    run.font.underline = True
    run.font.color.rgb = color
    run.hyperlink.address = url


class SlideBuilder:
    """Renders Division 4 Black/White/Orange 16:9 Factbook slides with Pretendard >=9pt, icons, and hyperlinks."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.icon_dir = self.work_dir / "icons"
        self.icon_dir.mkdir(parents=True, exist_ok=True)

    def add_cover_slide(self, prs: Presentation, project: Project, total_body_slides: int) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_WIDTH, SLIDE_HEIGHT)
        bg.fill.solid()
        bg.fill.fore_color.rgb = COLOR_BLACK
        bg.line.fill.background()

        top_bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_WIDTH, Inches(0.06))
        top_bar.fill.solid()
        top_bar.fill.fore_color.rgb = COLOR_ORANGE
        top_bar.line.fill.background()

        accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.85), Inches(1.85), Inches(0.10), Inches(3.2))
        accent.fill.solid()
        accent.fill.fore_color.rgb = COLOR_ORANGE
        accent.line.fill.background()

        tb = slide.shapes.add_textbox(Inches(1.18), Inches(1.80), Inches(10.8), Inches(3.8))
        tf = tb.text_frame
        tf.word_wrap = True

        p0 = tf.paragraphs[0]
        p0.text = f"DIVISION 4  ·  FACTBOOK REPORT  |  {project.industry_category}"
        p0.font.name = FONT_FAMILY
        p0.font.size = TYPO_HEADCOPY
        p0.font.bold = True
        p0.font.color.rgb = COLOR_ORANGE

        p1 = tf.add_paragraph()
        p1.space_before = Pt(16)
        p1.text = project.name[:90]
        p1.font.name = FONT_FAMILY
        p1.font.size = TYPO_DISPLAY
        p1.font.bold = True
        p1.font.color.rgb = COLOR_WHITE

        p2 = tf.add_paragraph()
        p2.space_before = Pt(18)
        p2.text = f"단일 분석 타겟: {project.brand_name} — {project.product_name}"
        p2.font.name = FONT_FAMILY
        p2.font.size = Pt(17)
        p2.font.color.rgb = COLOR_WHITE

        p3 = tf.add_paragraph()
        p3.space_before = Pt(12)
        track_txt = (
            "후기·실사용 중심(Track A)"
            if project.analysis_track == "REVIEW_CENTRIC"
            else "시장·검색 지표 중심(Track B)"
        )
        p3.text = f"수집 기간: {project.period_start} ~ {project.period_end}  |  트랙: {track_txt}  |  본문 {total_body_slides}장 구성"
        p3.font.name = FONT_FAMILY
        p3.font.size = Pt(12)
        p3.font.color.rgb = COLOR_TEXT_MUTED

    def build_content_slide(
        self,
        prs: Presentation,
        draft: SlideDraft,
        *,
        datalab_series: list[DataLabSeries],
        slide_number: int,
        total_slides: int = 0,
    ) -> None:
        if draft.slide_type == "SECTION_DIVIDER":
            self._build_section_divider_slide(prs, draft, slide_number=slide_number, total_slides=total_slides)
            return
        if draft.slide_type == "INDEX":
            self._build_index_slide(prs, draft, slide_number=slide_number, total_slides=total_slides)
            return

        slide = prs.slides.add_slide(prs.slide_layouts[6])
        self._draw_chrome(slide, draft, slide_number, total_slides)
        self._draw_headcopy(slide, draft.headcopy)

        kpis = list(draft.kpi_cards_json or [])
        bullets = list(draft.bullets_json or [])
        sns_types = {"OWN_SNS_TOP5", "OWN_INSTAGRAM_TOP5", "OWN_YOUTUBE_TOP5", "COMPETITOR_SNS_TOP5"}
        is_sns_top5 = draft.slide_type in sns_types and bool(draft.visual_assets_json)
        is_asis_tobe = draft.slide_type == "CONCLUSION_ASIS_TOBE" and bool(draft.as_is_to_be_json)
        has_chart_or_table = bool(draft.table_json) or bool(draft.visual_assets_json)

        body_top = 1.56
        if kpis:
            self._draw_kpi_strip(slide, kpis, top=1.52, height=0.82)
            body_top = 2.44

        show_insight_strip = bool(bullets) and (has_chart_or_table or is_sns_top5)
        body_bottom = 5.76 if show_insight_strip else 6.80
        body_height = max(2.2, body_bottom - body_top)

        if is_sns_top5:
            render_sns_top5_grid(
                slide,
                visual_assets=list(draft.visual_assets_json),
                top=body_top,
                height=body_height,
                icon_dir=self.icon_dir,
            )
        elif is_asis_tobe:
            self._draw_asis_tobe(slide, draft.as_is_to_be_json or {}, top=body_top, height=6.80 - body_top)
        elif has_chart_or_table:
            self._draw_visual_and_table_body(
                slide,
                draft,
                datalab_series=datalab_series,
                top=body_top,
                height=body_height,
            )
        else:
            self._draw_bullets_panel(
                slide, bullets, left=0.55, top=body_top, width=12.23, height=6.80 - body_top
            )

        if show_insight_strip and not is_asis_tobe:
            self._draw_bottom_insight_strip(slide, bullets, top=5.84, height=0.98)

        self._draw_footnote(slide, draft.footnote or "")

    def _build_section_divider_slide(
        self, prs: Presentation, draft: SlideDraft, *, slide_number: int, total_slides: int
    ) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_WIDTH, SLIDE_HEIGHT)
        bg.fill.solid()
        bg.fill.fore_color.rgb = COLOR_BLACK
        bg.line.fill.background()

        top_edge = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_WIDTH, Inches(0.06))
        top_edge.fill.solid()
        top_edge.fill.fore_color.rgb = COLOR_ORANGE
        top_edge.line.fill.background()

        badge = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.85), Inches(0.75), Inches(2.6), Inches(0.36))
        badge.adjustments[0] = 0.14
        badge.fill.solid()
        badge.fill.fore_color.rgb = COLOR_ORANGE
        badge.line.fill.background()
        btf = badge.text_frame
        btf.vertical_anchor = MSO_ANCHOR.MIDDLE
        bp = btf.paragraphs[0]
        bp.text = SECTION_BADGE_LABELS.get(draft.section_code, draft.section_code)
        bp.font.name = FONT_FAMILY
        bp.font.size = TYPO_LABEL
        bp.font.bold = True
        bp.font.color.rgb = COLOR_WHITE

        num_box = slide.shapes.add_textbox(Inches(11.6), Inches(0.75), Inches(1.2), Inches(0.36))
        np = num_box.text_frame.paragraphs[0]
        np.text = f"{slide_number:02d} / {total_slides:02d}" if total_slides else f"{slide_number:02d}"
        np.font.name = FONT_FAMILY
        np.font.size = TYPO_FOOTNOTE
        np.font.bold = True
        np.font.color.rgb = COLOR_TEXT_MUTED

        stripe = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.85), Inches(1.45), Inches(0.10), Inches(2.25))
        stripe.fill.solid()
        stripe.fill.fore_color.rgb = COLOR_ORANGE
        stripe.line.fill.background()

        title_box = slide.shapes.add_textbox(Inches(1.18), Inches(1.42), Inches(11.3), Inches(2.4))
        ttf = title_box.text_frame
        ttf.word_wrap = True
        tp = ttf.paragraphs[0]
        tp.text = clean_slide_text(draft.title)[:80]
        tp.font.name = FONT_FAMILY
        tp.font.size = TYPO_SECTION
        tp.font.bold = True
        tp.font.color.rgb = COLOR_WHITE

        sp = ttf.add_paragraph()
        sp.space_before = Pt(14)
        sp.text = clean_slide_text(draft.headcopy)[:160]
        sp.font.name = FONT_FAMILY
        sp.font.size = TYPO_HEADCOPY
        sp.font.color.rgb = RGBColor(229, 229, 229)

        kpis = list(draft.kpi_cards_json or [])[:3]
        if kpis:
            card_w = (11.6 - 0.24 * (len(kpis) - 1)) / len(kpis)
            for idx, kpi in enumerate(kpis):
                cx = 0.85 + idx * (card_w + 0.24)
                card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(cx), Inches(4.15), Inches(card_w), Inches(1.15))
                card.adjustments[0] = 0.08
                card.fill.solid()
                card.fill.fore_color.rgb = RGBColor(28, 28, 28)
                card.line.color.rgb = RGBColor(64, 64, 64)
                ctf = card.text_frame
                ctf.word_wrap = True
                ctf.margin_left = Inches(0.16)
                cp1 = ctf.paragraphs[0]
                cp1.text = str(kpi.get("label") or "")[:24]
                cp1.font.name = FONT_FAMILY
                cp1.font.size = TYPO_LABEL
                cp1.font.color.rgb = RGBColor(163, 163, 163)
                cp2 = ctf.add_paragraph()
                cp2.text = str(kpi.get("value") or "-")[:22]
                cp2.font.name = FONT_FAMILY
                cp2.font.size = TYPO_KPI_VALUE
                cp2.font.bold = True
                cp2.font.color.rgb = COLOR_ORANGE if idx == 0 else COLOR_WHITE

        bullets = list(draft.bullets_json or [])[:3]
        if bullets:
            bx_box = slide.shapes.add_textbox(Inches(0.85), Inches(5.55), Inches(11.6), Inches(1.2))
            bt = bx_box.text_frame
            bt.word_wrap = True
            for idx, b in enumerate(bullets):
                p = bt.paragraphs[0] if idx == 0 else bt.add_paragraph()
                p.space_before = Pt(2 if idx > 0 else 0)
                p.text = f"• {clean_slide_text(str(b.get('claim') or ''))[:110]}"
                p.font.name = FONT_FAMILY
                p.font.size = TYPO_BODY
                p.font.color.rgb = RGBColor(212, 212, 212)

        fn_box = slide.shapes.add_textbox(Inches(0.85), Inches(6.95), Inches(11.6), Inches(0.36))
        fp = fn_box.text_frame.paragraphs[0]
        fp.text = clean_slide_text(draft.footnote or "PTKOREA Division 4 Factbook")[:150]
        fp.font.name = FONT_FAMILY
        fp.font.size = TYPO_FOOTNOTE
        fp.font.color.rgb = COLOR_TEXT_MUTED

    def _build_index_slide(
        self, prs: Presentation, draft: SlideDraft, *, slide_number: int, total_slides: int
    ) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        self._draw_chrome(slide, draft, slide_number, total_slides)
        self._draw_headcopy(slide, draft.headcopy)

        body_top = 1.54
        if draft.kpi_cards_json:
            self._draw_kpi_strip(slide, list(draft.kpi_cards_json), top=1.52, height=0.82)
            body_top = 2.46

        if draft.table_json:
            self._draw_table(slide, draft.table_json, left=0.55, top=body_top, width=12.23, height=3.45)

        if draft.bullets_json:
            self._draw_bottom_insight_strip(slide, list(draft.bullets_json), top=6.00, height=0.88)

        self._draw_footnote(slide, draft.footnote or "")

    def _draw_chrome(
        self, slide: Slide, draft: SlideDraft, slide_number: int, total_slides: int
    ) -> None:
        top_edge = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_WIDTH, Inches(0.03))
        top_edge.fill.solid()
        top_edge.fill.fore_color.rgb = COLOR_ORANGE
        top_edge.line.fill.background()

        badge_text = "00. INDEX" if draft.slide_type == "INDEX" else SECTION_BADGE_LABELS.get(draft.section_code, draft.section_code)
        badge = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.55), Inches(0.22), Inches(1.95), Inches(0.34))
        badge.adjustments[0] = 0.12
        badge.fill.solid()
        badge.fill.fore_color.rgb = COLOR_ORANGE if draft.slide_type == "INDEX" else COLOR_BLACK
        badge.line.fill.background()
        btf = badge.text_frame
        btf.vertical_anchor = MSO_ANCHOR.MIDDLE
        bp = btf.paragraphs[0]
        bp.text = badge_text
        bp.font.name = FONT_FAMILY
        bp.font.size = TYPO_LABEL
        bp.font.bold = True
        bp.font.color.rgb = COLOR_WHITE

        title_box = slide.shapes.add_textbox(Inches(2.62), Inches(0.18), Inches(9.2), Inches(0.42))
        ttf = title_box.text_frame
        ttf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tp = ttf.paragraphs[0]
        tp.text = clean_slide_text(draft.title)[:78]
        tp.font.name = FONT_FAMILY
        tp.font.size = TYPO_SLIDE_TITLE
        tp.font.bold = True
        tp.font.color.rgb = COLOR_TEXT_MAIN

        num_box = slide.shapes.add_textbox(Inches(11.88), Inches(0.22), Inches(0.92), Inches(0.35))
        np = num_box.text_frame.paragraphs[0]
        np.text = f"{slide_number:02d} / {total_slides:02d}" if total_slides else f"{slide_number:02d}"
        np.font.name = FONT_FAMILY
        np.font.size = TYPO_LABEL
        np.font.bold = True
        np.font.color.rgb = COLOR_TEXT_MUTED

    def _draw_headcopy(self, slide: Slide, headcopy: str) -> None:
        cleaned = clean_slide_text(headcopy)[:220]
        box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.55), Inches(0.68), Inches(12.23), Inches(0.76))
        box.adjustments[0] = 0.06
        box.fill.solid()
        box.fill.fore_color.rgb = COLOR_SURFACE
        box.line.color.rgb = COLOR_BORDER
        box.line.width = Pt(0.75)

        accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.55), Inches(0.68), Inches(0.07), Inches(0.76))
        accent.fill.solid()
        accent.fill.fore_color.rgb = COLOR_BLACK
        accent.line.fill.background()

        tf = box.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.20)
        tf.margin_right = Inches(0.16)
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.text = cleaned
        p.font.name = FONT_FAMILY
        p.font.size = Pt(12) if len(cleaned) <= 85 else Pt(10.5)
        p.font.bold = True
        p.font.color.rgb = COLOR_TEXT_MAIN

    def _draw_kpi_strip(
        self, slide: Slide, kpis: list[dict[str, Any]], *, top: float, height: float
    ) -> None:
        items = kpis[:4]
        margin_x = 0.55
        gap = 0.16
        total_w = 12.23
        card_w = (total_w - gap * (len(items) - 1)) / len(items)

        for idx, kpi in enumerate(items):
            left = margin_x + idx * (card_w + gap)
            card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(card_w), Inches(height))
            card.adjustments[0] = 0.06
            card.fill.solid()
            card.fill.fore_color.rgb = COLOR_SURFACE
            card.line.color.rgb = COLOR_BORDER
            card.line.width = Pt(0.85)

            tf = card.text_frame
            tf.word_wrap = True
            tf.margin_left = Inches(0.13)
            tf.margin_top = Inches(0.05)

            p1 = tf.paragraphs[0]
            p1.text = str(kpi.get("label") or "")[:24]
            p1.font.name = FONT_FAMILY
            p1.font.size = TYPO_LABEL
            p1.font.color.rgb = COLOR_TEXT_MUTED

            p2 = tf.add_paragraph()
            p2.text = str(kpi.get("value") or "-")[:22]
            p2.font.name = FONT_FAMILY
            p2.font.size = Pt(15)
            p2.font.bold = True
            p2.font.color.rgb = COLOR_ORANGE if idx == 0 else COLOR_TEXT_MAIN

            sub_parts = [str(kpi.get("delta") or ""), str(kpi.get("basis") or "")]
            sub = " · ".join(s for s in sub_parts if s)
            if sub:
                p3 = tf.add_paragraph()
                p3.text = sub[:34]
                p3.font.name = FONT_FAMILY
                p3.font.size = TYPO_FOOTNOTE
                p3.font.color.rgb = COLOR_TEXT_SUB

    def _draw_visual_and_table_body(
        self,
        slide: Slide,
        draft: SlideDraft,
        *,
        datalab_series: list[DataLabSeries],
        top: float,
        height: float,
    ) -> None:
        chart_path = self._resolve_chart(draft, datalab_series=datalab_series)
        has_table = bool(draft.table_json and (draft.table_json.get("rows") or []))

        if chart_path and chart_path.exists() and has_table:
            left_w = 5.85
            right_left = 6.56
            right_w = 6.22
            self._place_chart_frame(slide, chart_path, left=0.55, top=top, width=left_w, height=height)
            self._draw_table(slide, draft.table_json or {}, left=right_left, top=top, width=right_w, height=height)
        elif chart_path and chart_path.exists():
            self._place_chart_frame(slide, chart_path, left=0.55, top=top, width=12.23, height=height)
        elif has_table:
            self._draw_table(slide, draft.table_json or {}, left=0.55, top=top, width=12.23, height=height)
        else:
            self._draw_bullets_panel(slide, list(draft.bullets_json or []), left=0.55, top=top, width=12.23, height=height)

    def _resolve_chart(
        self, draft: SlideDraft, *, datalab_series: list[DataLabSeries]
    ) -> Path | None:
        search_series = [s for s in datalab_series if s.metric_type == "SEARCH_TREND"]
        shopping_series = [s for s in datalab_series if s.metric_type == "SHOPPING_INSIGHT"]
        assets = list(draft.visual_assets_json or [])
        if not assets:
            return None
        first = assets[0]
        asset_type = first.get("asset_type")
        meta = first.get("metadata") or {}
        if asset_type == "DATALAB_TREND_CHART" and search_series:
            return build_datalab_trend_chart(
                series_list=search_series,
                output_path=self.work_dir / f"trend_{draft.id[:8]}.png",
                title=str(first.get("title") or "검색 관심도 추이"),
            )
        if asset_type == "DATALAB_SOS_BAR" and search_series:
            return build_share_of_search_chart(
                series_list=search_series,
                shopping_series=shopping_series,
                output_path=self.work_dir / f"sos_{draft.id[:8]}.png",
                title=str(first.get("title") or "경쟁군 검색(SoS) vs 쇼핑 관심 점유율 (%)"),
            )
        if asset_type == "HORIZONTAL_BAR_CHART":
            items = list(meta.get("items") or [])
            if items:
                return build_horizontal_bar_chart(
                    items=items,
                    unit=str(meta.get("unit") or ""),
                    title=str(first.get("title") or "주요 정량 비교"),
                    output_path=self.work_dir / f"hbar_{draft.id[:8]}.png",
                )
            return None
        if asset_type == "PRICE_DISCOUNT_BAR":
            items = list(meta.get("items") or [])
            if items:
                return build_price_discount_chart(
                    items=items,
                    unit=str(meta.get("unit") or "만원"),
                    title=str(first.get("title") or "라인업 정가 vs 할인가 비교"),
                    output_path=self.work_dir / f"price_{draft.id[:8]}.png",
                )
            return None
        if asset_type == "PRESS_MONTHLY_BAR":
            items = list(meta.get("items") or [])
            if items:
                return build_press_monthly_chart(
                    items=items,
                    title=str(first.get("title") or "월별 언론 보도 추이"),
                    output_path=self.work_dir / f"press_m_{draft.id[:8]}.png",
                )
            return None
        if asset_type == "PRESS_BRAND_BAR":
            items = list(meta.get("items") or [])
            if items:
                return build_press_brand_chart(
                    items=items,
                    title=str(first.get("title") or "브랜드별 언론 보도량 비교"),
                    output_path=self.work_dir / f"press_b_{draft.id[:8]}.png",
                )
            return None
        if asset_type == "MARKETING_HEATMAP":
            brands = list(meta.get("brands") or [])
            rows = list(meta.get("rows") or [])
            if brands and rows:
                return build_marketing_heatmap_chart(
                    brands=brands,
                    rows=rows,
                    title=str(first.get("title") or "마케팅 활동 6분류 강도 히트맵"),
                    output_path=self.work_dir / f"hm_{draft.id[:8]}.png",
                )
            return None
        if asset_type == "CONSUMER_KBF_CHART":
            return build_consumer_sentiment_chart(
                positive=int(meta.get("positive", 1)),
                negative=int(meta.get("negative", 0)),
                neutral=int(meta.get("neutral", 1)),
                output_path=self.work_dir / f"voc_{draft.id[:8]}.png",
            )
        if first.get("local_path"):
            return Path(str(first["local_path"]))
        return None

    @staticmethod
    def _place_chart_frame(
        slide: Slide, chart_path: Path, *, left: float, top: float, width: float, height: float
    ) -> None:
        frame = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
        frame.adjustments[0] = 0.04
        frame.fill.solid()
        frame.fill.fore_color.rgb = COLOR_WHITE
        frame.line.color.rgb = COLOR_BORDER
        add_contained_image(
            slide,
            image_path=chart_path,
            box_left=left + 0.08,
            box_top=top + 0.08,
            box_width=width - 0.16,
            box_height=height - 0.16,
        )

    def _draw_table(
        self,
        slide: Slide,
        table_data: dict[str, Any],
        *,
        left: float,
        top: float,
        width: float,
        height: float,
    ) -> None:
        headers = list(table_data.get("headers") or [])
        rows = list(table_data.get("rows") or [])[:8]
        if not headers or not rows:
            return
        n_rows = len(rows) + 1
        n_cols = len(headers)
        shape = slide.shapes.add_table(n_rows, n_cols, Inches(left), Inches(top), Inches(width), Inches(height))
        tbl = shape.table
        hdr_sz = TYPO_TABLE_HEADER
        cell_sz = TYPO_TABLE_CELL if len(rows) <= 5 and n_cols <= 4 else TYPO_FOOTNOTE
        max_cell_chars = 78 if n_cols <= 3 else (52 if n_cols == 4 else 40)

        for c_idx, h in enumerate(headers):
            cell = tbl.cell(0, c_idx)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = COLOR_BLACK
            p = cell.text_frame.paragraphs[0]
            p.text = smart_truncate(str(h), 26)
            p.font.name = FONT_FAMILY
            p.font.size = hdr_sz
            p.font.bold = True
            p.font.color.rgb = COLOR_WHITE

        for r_idx, row in enumerate(rows, start=1):
            for c_idx in range(n_cols):
                raw_val = str(row[c_idx]).strip() if c_idx < len(row) else "-"
                cell = tbl.cell(r_idx, c_idx)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell.fill.solid()
                cell.fill.fore_color.rgb = COLOR_SURFACE if r_idx % 2 == 1 else COLOR_WHITE
                p = cell.text_frame.paragraphs[0]
                if raw_val.startswith("http://") or raw_val.startswith("https://"):
                    p.text = ""
                    _add_hyperlink_run(
                        p,
                        label=_format_url_label(raw_val),
                        url=raw_val,
                        size=cell_sz,
                        color=COLOR_ORANGE,
                        bold=True,
                    )
                else:
                    p.text = smart_truncate(raw_val, max_cell_chars)
                    p.font.name = FONT_FAMILY
                    p.font.size = cell_sz
                    p.font.bold = c_idx == 0
                    p.font.color.rgb = COLOR_TEXT_MAIN if c_idx == 0 else COLOR_TEXT_SUB

    def _draw_bullets_panel(
        self,
        slide: Slide,
        bullets: list[dict[str, Any]],
        *,
        left: float,
        top: float,
        width: float,
        height: float,
    ) -> None:
        panel = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
        panel.adjustments[0] = 0.04
        panel.fill.solid()
        panel.fill.fore_color.rgb = COLOR_SURFACE
        panel.line.color.rgb = COLOR_BORDER

        tb = slide.shapes.add_textbox(Inches(left + 0.18), Inches(top + 0.14), Inches(width - 0.36), Inches(height - 0.28))
        tf = tb.text_frame
        tf.word_wrap = True
        for idx, b in enumerate(bullets[:4]):
            claim_txt = clean_slide_text(str(b.get("claim") or ""))[:140]
            p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
            p.space_before = Pt(0 if idx == 0 else 8)
            p.text = f"• {claim_txt}"
            p.font.name = FONT_FAMILY
            p.font.size = TYPO_BODY
            p.font.bold = True
            p.font.color.rgb = COLOR_TEXT_MAIN

            quote = clean_slide_text(str(b.get("evidence_quote") or ""))
            src = clean_slide_text(str(b.get("source_name") or ""))
            url = str(b.get("source_url") or "").strip()
            if quote or src or url.startswith("http"):
                qp = tf.add_paragraph()
                qp.space_before = Pt(2)
                src_tag = f" [{src}]" if src else ""
                q_str = f"\"{quote[:105]}\"" if quote else ""
                r_txt = qp.add_run()
                r_txt.text = f"   └ 근거: {q_str}{src_tag} "
                r_txt.font.name = FONT_FAMILY
                r_txt.font.size = TYPO_FOOTNOTE
                r_txt.font.color.rgb = COLOR_TEXT_SUB
                if url.startswith("http"):
                    _add_hyperlink_run(qp, label=_format_url_label(url), url=url, size=TYPO_FOOTNOTE)

    def _draw_bottom_insight_strip(
        self, slide: Slide, bullets: list[dict[str, Any]], *, top: float, height: float
    ) -> None:
        """Sample-PDF style bottom 3-column '관찰된 특징 1 · 2 · 3' strip with >=9pt and clickable links."""
        items = bullets[:3]
        if not items:
            return
        strip = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.55), Inches(top), Inches(12.23), Inches(height))
        strip.adjustments[0] = 0.08
        strip.fill.solid()
        strip.fill.fore_color.rgb = COLOR_MUTED_BG
        strip.line.color.rgb = COLOR_BORDER

        lbl_box = slide.shapes.add_textbox(Inches(0.68), Inches(top + 0.12), Inches(0.92), Inches(height - 0.2))
        ltf = lbl_box.text_frame
        ltf.word_wrap = True
        lp = ltf.paragraphs[0]
        lp.text = "관찰된\n특징"
        lp.font.name = FONT_FAMILY
        lp.font.size = TYPO_LABEL
        lp.font.bold = True
        lp.font.color.rgb = COLOR_ORANGE

        col_start = 1.65
        col_total = 11.00
        col_gap = 0.18
        col_w = (col_total - col_gap * 2) / 3.0

        for idx, b in enumerate(items):
            cx = col_start + idx * (col_w + col_gap)
            box = slide.shapes.add_textbox(Inches(cx), Inches(top + 0.08), Inches(col_w), Inches(height - 0.12))
            tf = box.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            claim = smart_truncate(str(b.get("claim") or ""), 78)
            p.text = f"{idx + 1}. {claim}"
            p.font.name = FONT_FAMILY
            p.font.size = TYPO_FOOTNOTE
            p.font.bold = True
            p.font.color.rgb = COLOR_TEXT_MAIN

            quote = smart_truncate(str(b.get("evidence_quote") or ""), 52)
            url = str(b.get("source_url") or "").strip()
            if quote or url.startswith("http"):
                qp = tf.add_paragraph()
                qp.space_before = Pt(2)
                if quote:
                    r_q = qp.add_run()
                    r_q.text = f"{quote} "
                    r_q.font.name = FONT_FAMILY
                    r_q.font.size = TYPO_FOOTNOTE
                    r_q.font.color.rgb = COLOR_TEXT_SUB
                if url.startswith("http"):
                    _add_hyperlink_run(qp, label=_format_url_label(url), url=url, size=TYPO_FOOTNOTE)

    def _draw_asis_tobe(
        self, slide: Slide, data: dict[str, Any], *, top: float, height: float
    ) -> None:
        columns = [
            ("AS-IS (현재 진단)", list(data.get("as_is_points") or []), COLOR_TEXT_SUB),
            ("KEY ISSUE (핵심 과제)", list(data.get("key_issues") or []), COLOR_AMBER),
            ("TO-BE (전략 방향)", list(data.get("to_be_directions") or []), COLOR_BLACK),
        ]
        margin_x = 0.55
        gap = 0.25
        col_w = (12.23 - gap * 2) / 3.0

        for idx, (col_title, items, header_color) in enumerate(columns):
            left = margin_x + idx * (col_w + gap)
            box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(col_w), Inches(height))
            box.adjustments[0] = 0.04
            box.fill.solid()
            box.fill.fore_color.rgb = COLOR_SURFACE
            box.line.color.rgb = COLOR_BORDER_STRONG if idx == 2 else COLOR_BORDER

            hdr = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(top), Inches(col_w), Inches(0.46))
            hdr.fill.solid()
            hdr.fill.fore_color.rgb = header_color
            hdr.line.fill.background()
            htf = hdr.text_frame
            htf.vertical_anchor = MSO_ANCHOR.MIDDLE
            hp = htf.paragraphs[0]
            hp.text = col_title
            hp.font.name = FONT_FAMILY
            hp.font.size = TYPO_PANEL_TITLE
            hp.font.bold = True
            hp.font.color.rgb = COLOR_WHITE

            tb = slide.shapes.add_textbox(Inches(left + 0.16), Inches(top + 0.58), Inches(col_w - 0.32), Inches(height - 0.7))
            tf = tb.text_frame
            tf.word_wrap = True
            for j, text in enumerate(items[:3]):
                p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
                p.space_before = Pt(0 if j == 0 else 10)
                p.text = f"{j+1}. {clean_slide_text(str(text))[:130]}"
                p.font.name = FONT_FAMILY
                p.font.size = TYPO_BODY
                p.font.color.rgb = COLOR_TEXT_MAIN

    @staticmethod
    def _draw_footnote(slide: Slide, footnote: str) -> None:
        if not footnote:
            return
        tb = slide.shapes.add_textbox(Inches(0.55), Inches(6.92), Inches(12.23), Inches(0.38))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = clean_slide_text(footnote)[:160]
        p.font.name = FONT_FAMILY
        p.font.size = TYPO_FOOTNOTE
        p.font.color.rgb = COLOR_TEXT_MUTED
