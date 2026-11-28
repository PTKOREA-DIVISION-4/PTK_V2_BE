"""Pure-Pillow 2x-supersampled crisp PNG renderer for Division 4 channel brand symbols."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CHANNEL_SPECS: dict[str, dict[str, str]] = {
    "instagram": {"label": "Instagram", "bg": "#E1306C", "fg": "#FFFFFF", "glyph": "IG"},
    "youtube": {"label": "YouTube", "bg": "#DC2626", "fg": "#FFFFFF", "glyph": "PLAY"},
    "naver_blog": {"label": "Naver Blog", "bg": "#03C75A", "fg": "#FFFFFF", "glyph": "B"},
    "naver_cafe": {"label": "Naver Cafe", "bg": "#029E47", "fg": "#FFFFFF", "glyph": "C"},
    "naver_datalab": {"label": "DataLab", "bg": "#03C75A", "fg": "#FFFFFF", "glyph": "N"},
    "dcinside": {"label": "DCInside", "bg": "#1D4ED8", "fg": "#FFFFFF", "glyph": "DC"},
    "fmkorea": {"label": "FMKorea", "bg": "#2563EB", "fg": "#FFFFFF", "glyph": "FM"},
    "theqoo": {"label": "Theqoo", "bg": "#7C3AED", "fg": "#FFFFFF", "glyph": "Q"},
    "clien": {"label": "Clien", "bg": "#0F766E", "fg": "#FFFFFF", "glyph": "CL"},
    "news_press": {"label": "News / PR", "bg": "#111111", "fg": "#FFFFFF", "glyph": "NEWS"},
    "perplexity_research": {"label": "Deep Research", "bg": "#0E7490", "fg": "#FFFFFF", "glyph": "AI"},
    "official": {"label": "Official", "bg": "#E9501F", "fg": "#FFFFFF", "glyph": "OFF"},
}


def normalize_channel_key(raw: str | None) -> str:
    val = (raw or "").strip().lower()
    if "insta" in val or val == "ig":
        return "instagram"
    if "youtube" in val or val == "yt" or "shorts" in val:
        return "youtube"
    if "blog" in val:
        return "naver_blog"
    if "cafe" in val or "카페" in val:
        return "naver_cafe"
    if "datalab" in val or "데이터랩" in val or "naver" in val:
        return "naver_datalab"
    if "dcinside" in val or "디시" in val:
        return "dcinside"
    if "fmkorea" in val or "에펨" in val:
        return "fmkorea"
    if "theqoo" in val or "더쿠" in val:
        return "theqoo"
    if "clien" in val or "클리앙" in val:
        return "clien"
    if "news" in val or "press" in val or "언론" in val or "보도" in val:
        return "news_press"
    if "perplexity" in val or "research" in val or "리서치" in val:
        return "perplexity_research"
    if "official" in val or "공식" in val:
        return "official"
    return "official"


@lru_cache(maxsize=8)
def _load_font(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path.home() / "Library" / "Fonts" / "Pretendard-Bold.ttf",
        Path("/Library/Fonts/Pretendard-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size_px)
            except Exception:
                continue
    return ImageFont.load_default()


ASSET_ICON_DIR = Path(__file__).resolve().parent / "assets" / "channel_icons"


def render_channel_icon(channel_key: str, output_dir: Path, size_px: int = 64) -> Path:
    """Loads authentic service icon PNG if bundled, or renders a 2x-supersampled Pillow badge fallback."""
    norm = normalize_channel_key(channel_key)
    spec = CHANNEL_SPECS.get(norm, CHANNEL_SPECS["official"])
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"icon_{norm}_{size_px}.png"
    if out_path.exists():
        return out_path

    bundled = ASSET_ICON_DIR / f"{norm}.png"
    if bundled.exists():
        try:
            with Image.open(bundled) as raw_im:
                icon = raw_im.convert("RGBA").resize((size_px, size_px), Image.Resampling.LANCZOS)
                mask = Image.new("L", (size_px, size_px), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.rounded_rectangle(
                    [(0, 0), (size_px - 1, size_px - 1)],
                    radius=max(4, int(size_px * 0.2)),
                    fill=255,
                )
                rounded = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
                rounded.paste(icon, (0, 0), mask)
                rounded.save(out_path, format="PNG")
                return out_path
        except Exception:
            pass

    hi = size_px * 2
    img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = int(hi * 0.24)
    draw.rounded_rectangle([(0, 0), (hi - 1, hi - 1)], radius=radius, fill=spec["bg"])

    glyph = spec["glyph"]
    if norm == "youtube":
        # White rounded play triangle centered
        cx, cy = hi // 2, hi // 2
        r = int(hi * 0.26)
        pts = [(cx - int(r * 0.55), cy - r), (cx + r, cy), (cx - int(r * 0.55), cy + r)]
        draw.polygon(pts, fill=spec["fg"])
    elif norm == "instagram":
        # Stylized camera frame + lens circle
        pad = int(hi * 0.22)
        draw.rounded_rectangle(
            [(pad, pad), (hi - pad, hi - pad)],
            radius=int(hi * 0.16),
            outline=spec["fg"],
            width=max(3, hi // 16),
        )
        r_in = int(hi * 0.15)
        draw.ellipse(
            [(hi // 2 - r_in, hi // 2 - r_in), (hi // 2 + r_in, hi // 2 + r_in)],
            outline=spec["fg"],
            width=max(3, hi // 16),
        )
        dot_r = max(2, hi // 24)
        dx, dy = int(hi * 0.68), int(hi * 0.32)
        draw.ellipse([(dx - dot_r, dy - dot_r), (dx + dot_r, dy + dot_r)], fill=spec["fg"])
    else:
        font_sz = int(hi * (0.28 if len(glyph) >= 4 else 0.42))
        font = _load_font(font_sz)
        bbox = draw.textbbox((0, 0), glyph, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (hi - tw) / 2 - bbox[0]
        ty = (hi - th) / 2 - bbox[1]
        draw.text((tx, ty), glyph, font=font, fill=spec["fg"])

    final = img.resize((size_px, size_px), Image.Resampling.LANCZOS)
    final.save(out_path, format="PNG")
    return out_path
