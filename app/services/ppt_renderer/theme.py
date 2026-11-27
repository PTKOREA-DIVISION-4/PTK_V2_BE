from __future__ import annotations

from pptx.dml.color import RGBColor
from pptx.util import Inches


SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)

# Division 4 Design System Palette (matches Frontend Light UI + Black Main + Orange Accent)
COLOR_BLACK = RGBColor(17, 17, 17)         # #111111 Primary ink, cover, table header
COLOR_ORANGE = RGBColor(233, 80, 31)       # #E9501F Point accent (restrained)
COLOR_WHITE = RGBColor(255, 255, 255)      # #FFFFFF Slide surface
COLOR_SURFACE = RGBColor(250, 250, 250)    # #FAFAFA Subtle card fill
COLOR_MUTED_BG = RGBColor(245, 245, 245)   # #F5F5F5 Tag / strip background
COLOR_BORDER = RGBColor(229, 229, 229)     # #E5E5E5 1px divider
COLOR_BORDER_STRONG = RGBColor(212, 212, 212)
COLOR_TEXT_MAIN = RGBColor(17, 17, 17)     # #111111
COLOR_TEXT_SUB = RGBColor(74, 74, 74)      # #4A4A4A
COLOR_TEXT_MUTED = RGBColor(140, 140, 140) # #8C8C8C

# Semantic feedback accents
COLOR_GREEN = RGBColor(31, 138, 91)        # #1F8A5B Positive
COLOR_AMBER = RGBColor(217, 119, 6)        # #D97706 Key Issue / Warning
COLOR_RED = RGBColor(220, 38, 38)          # #DC2626 Negative / Risk

# Backward-compatible aliases for existing helpers/tests
COLOR_NAVY = COLOR_BLACK
COLOR_TEAL = COLOR_ORANGE
COLOR_CORAL = COLOR_RED
COLOR_SLATE_900 = COLOR_TEXT_MAIN
COLOR_SLATE_700 = COLOR_TEXT_SUB
COLOR_SLATE_500 = COLOR_TEXT_MUTED
COLOR_CARD_BG = COLOR_SURFACE
COLOR_HEADCOPY_BG = COLOR_SURFACE

FONT_FAMILY = "Apple SD Gothic Neo"

SECTION_BADGE_LABELS: dict[str, str] = {
    "0_OVERVIEW": "0. 분석 개요",
    "1_OWN": "1. 자사 분석",
    "2_MARKET": "2. 시장 분석",
    "3_COMPETITOR": "3. 경쟁사 분석",
    "4_CONSUMER": "4. 소비자 분석",
    "5_SUMMARY_CONCLUSION": "5. 현황 요약 · 결론",
}
