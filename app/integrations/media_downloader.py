from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw

from app.core.config import get_settings


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
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
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
        draw.text((24, 18), title[:48], fill=(255, 255, 255))
        draw.text((36, 100), subtitle[:70], fill=(74, 74, 74))
        img.save(path, format="PNG")
        return {
            "local_path": str(path),
            "original_url": None,
            "width": 640,
            "height": 400,
            "is_valid": True,
        }
