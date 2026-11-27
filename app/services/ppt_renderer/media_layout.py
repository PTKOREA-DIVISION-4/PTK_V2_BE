from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
from pptx.slide import Slide
from pptx.util import Inches, Pt

from app.services.deck_blueprint import clean_slide_text
from app.services.ppt_renderer.channel_icons import normalize_channel_key, render_channel_icon
from app.services.ppt_renderer.theme import (
    COLOR_BLACK,
    COLOR_BORDER,
    COLOR_ORANGE,
    COLOR_SURFACE,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_SUB,
    COLOR_WHITE,
    FONT_FAMILY,
    TYPO_FOOTNOTE,
    TYPO_LABEL,
)


def add_contained_image(
    slide: Slide,
    *,
    image_path: str | Path,
    box_left: float,
    box_top: float,
    box_width: float,
    box_height: float,
) -> bool:
    """Places an image inside the target box preserving its natural aspect ratio."""
    path = Path(image_path)
    if not path.exists():
        return False
    try:
        with Image.open(path) as im:
            iw, ih = im.size
    except Exception:
        return False
    if iw <= 0 or ih <= 0:
        return False

    box_ratio = box_width / box_height
    img_ratio = iw / ih
    if img_ratio >= box_ratio:
        render_w = box_width
        render_h = box_width / img_ratio
    else:
        render_h = box_height
        render_w = box_height * img_ratio

    offset_x = box_left + (box_width - render_w) / 2.0
    offset_y = box_top + (box_height - render_h) / 2.0
    slide.shapes.add_picture(
        str(path),
        Inches(offset_x),
        Inches(offset_y),
        width=Inches(render_w),
        height=Inches(render_h),
    )
    return True


def render_sns_top5_grid(
    slide: Slide,
    *,
    visual_assets: list[dict[str, Any]],
    top: float = 2.55,
    height: float = 3.25,
    icon_dir: Path | None = None,
) -> None:
    """Renders up to 5 horizontal SNS cards with Pretendard >=9pt typography, channel icons, and links."""
    cards = visual_assets[:5]
    if not cards:
        return
    margin_x = 0.55
    gap = 0.16
    total_w = 13.333 - (margin_x * 2)
    card_w = (total_w - gap * (len(cards) - 1)) / len(cards)

    for idx, card in enumerate(cards):
        left = margin_x + idx * (card_w + gap)
        bg = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(left),
            Inches(top),
            Inches(card_w),
            Inches(height),
        )
        bg.adjustments[0] = 0.04
        bg.fill.solid()
        bg.fill.fore_color.rgb = COLOR_WHITE
        bg.line.color.rgb = COLOR_ORANGE if idx == 0 else COLOR_BORDER
        bg.line.width = Pt(1.25 if idx == 0 else 1)

        pill = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(left),
            Inches(top),
            Inches(card_w),
            Inches(0.34),
        )
        pill.fill.solid()
        pill.fill.fore_color.rgb = COLOR_ORANGE if idx == 0 else COLOR_BLACK
        pill.line.fill.background()

        meta = card.get("metadata") or {}
        ch_raw = str(meta.get("platform") or card.get("title") or "official")
        ch_key = normalize_channel_key(ch_raw)
        has_icon = False
        if icon_dir is not None:
            icon_path = render_channel_icon(ch_key, icon_dir, size_px=48)
            if icon_path.exists():
                slide.shapes.add_picture(
                    str(icon_path),
                    Inches(left + 0.06),
                    Inches(top + 0.05),
                    width=Inches(0.24),
                    height=Inches(0.24),
                )
                has_icon = True

        tf = pill.text_frame
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        if has_icon:
            tf.margin_left = Inches(0.34)
        p = tf.paragraphs[0]
        p.text = str(card.get("title") or f"TOP {idx+1}")[:24]
        p.font.name = FONT_FAMILY
        p.font.size = TYPO_LABEL
        p.font.bold = True
        p.font.color.rgb = COLOR_WHITE

        img_top = top + 0.40
        img_h = max(1.25, height * 0.48)
        placed = False
        lp = card.get("local_path")
        if lp:
            placed = add_contained_image(
                slide,
                image_path=lp,
                box_left=left + 0.08,
                box_top=img_top,
                box_width=card_w - 0.16,
                box_height=img_h,
            )
        if not placed:
            placeholder = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(left + 0.08),
                Inches(img_top),
                Inches(card_w - 0.16),
                Inches(img_h),
            )
            placeholder.fill.solid()
            placeholder.fill.fore_color.rgb = COLOR_SURFACE
            placeholder.line.color.rgb = COLOR_BORDER
            ptf = placeholder.text_frame
            ptf.word_wrap = True
            pp = ptf.paragraphs[0]
            pp.text = "대표 이미지\n(썸네일 미제공)"
            pp.font.name = FONT_FAMILY
            pp.font.size = TYPO_FOOTNOTE
            pp.font.color.rgb = COLOR_TEXT_MUTED

        cap_top = img_top + img_h + 0.06
        cap_h = max(0.65, (top + height) - cap_top - 0.06)
        cap_box = slide.shapes.add_textbox(
            Inches(left + 0.08),
            Inches(cap_top),
            Inches(card_w - 0.16),
            Inches(cap_h),
        )
        ctf = cap_box.text_frame
        ctf.word_wrap = True
        cp1 = ctf.paragraphs[0]
        cp1.text = clean_slide_text(str(card.get("caption") or ""))[:52]
        cp1.font.name = FONT_FAMILY
        cp1.font.size = TYPO_FOOTNOTE
        cp1.font.bold = True
        cp1.font.color.rgb = COLOR_TEXT_MAIN

        ann = clean_slide_text(str(card.get("annotation_text") or ""))
        if ann:
            cp2 = ctf.add_paragraph()
            cp2.space_before = Pt(2)
            cp2.text = ann[:56]
            cp2.font.name = FONT_FAMILY
            cp2.font.size = TYPO_FOOTNOTE
            cp2.font.color.rgb = COLOR_TEXT_SUB

        post_url = str(meta.get("post_url") or "").strip()
        if post_url.startswith("http"):
            cp3 = ctf.add_paragraph()
            cp3.space_before = Pt(2)
            run = cp3.add_run()
            run.text = "원문 보기 ↗"
            run.font.name = FONT_FAMILY
            run.font.size = TYPO_FOOTNOTE
            run.font.bold = True
            run.font.color.rgb = COLOR_ORANGE
            run.font.underline = True
            run.hyperlink.address = post_url
