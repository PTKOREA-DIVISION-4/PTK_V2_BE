from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont

from app.core.config import get_settings


def _load_korean_font(size: int = 16, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [
            Path("/usr/share/fonts/Pretendard-Bold.ttf"),
            Path("/usr/share/fonts/Pretendard-Regular.ttf"),
            Path.home() / "Library" / "Fonts" / "Pretendard-Bold.ttf",
            Path.home() / "Library" / "Fonts" / "Pretendard-Regular.ttf",
            Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
            Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        ]
        if bold
        else [
            Path("/usr/share/fonts/Pretendard-Regular.ttf"),
            Path.home() / "Library" / "Fonts" / "Pretendard-Regular.ttf",
            Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        ]
    )
    for fp in candidates:
        if fp.exists():
            try:
                return ImageFont.truetype(str(fp), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


class MediaDownloader:
    """Downloads and validates external SNS/reference images into backend/storage/media/."""

    def __init__(self, media_root: Path | None = None) -> None:
        settings = get_settings()
        self.media_root = media_root or settings.media_dir

    def project_dir(self, project_id: str) -> Path:
        path = self.media_root / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def download_image(
        self,
        *,
        project_id: str,
        image_url: str,
        prefix: str = "ref",
    ) -> dict[str, Any] | None:
        if not image_url or not image_url.startswith(("http://", "https://")):
            return None

        digest = hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:16]
        target_path = self.project_dir(project_id) / f"{prefix}_{digest}.png"

        if target_path.exists():
            return self._inspect_image(target_path, image_url)

        try:
            # IPv6 TLS 타임아웃 회피를 위해 IPv4 바인딩 + 재시도 적용
            transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0", retries=2)
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                )
            }
            async with httpx.AsyncClient(
                transport=transport,
                headers=headers,
                timeout=20.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                img.thumbnail((1280, 1280))
                img.save(target_path, format="PNG", optimize=True)
                return {
                    "local_path": str(target_path),
                    "original_url": image_url,
                    "width": img.width,
                    "height": img.height,
                    "is_valid": True,
                }
        except Exception:
            return None

    @staticmethod
    def _inspect_image(path: Path, original_url: str | None = None) -> dict[str, Any] | None:
        try:
            with Image.open(path) as img:
                return {
                    "local_path": str(path),
                    "original_url": original_url,
                    "width": img.width,
                    "height": img.height,
                    "is_valid": True,
                }
        except Exception:
            return None

    def create_placeholder_card(
        self,
        *,
        project_id: str,
        filename: str,
        title: str,
        subtitle: str,
    ) -> dict[str, Any]:
        """Generates a crisp local PNG preview card when live external media is unavailable."""
        path = self.project_dir(project_id) / filename
        img = Image.new("RGB", (640, 400), color=(250, 250, 250))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 640, 52], fill=(17, 17, 17))
        draw.rectangle([0, 52, 640, 56], fill=(233, 80, 31))
        draw.rectangle([20, 76, 620, 380], outline=(229, 229, 229), width=2, fill=(255, 255, 255))
        title_font = _load_korean_font(size=18, bold=True)
        body_font = _load_korean_font(size=15, bold=False)
        draw.text((24, 15), title[:44], fill=(255, 255, 255), font=title_font)
        draw.text((36, 108), subtitle[:64], fill=(74, 74, 74), font=body_font)
        img.save(path, format="PNG")
        return {
            "local_path": str(path),
            "original_url": None,
            "width": 640,
            "height": 400,
            "is_valid": True,
        }
