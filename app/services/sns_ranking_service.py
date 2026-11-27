from __future__ import annotations

from datetime import date, datetime
from typing import Any


COLLAB_MARKERS = ("#광고", "#협찬", "#유료광고", "#제공", "#체험단", "#ad", "#sponsored")


class SnsRankingService:
    """Filters SNS posts strictly within project period and extracts TOP 5 per brand."""

    @staticmethod
    def is_within_period(
        published_at: datetime | None, period_start: date, period_end: date
    ) -> bool:
        if published_at is None:
            return False
        pub_date = published_at.date()
        return period_start <= pub_date <= period_end

    @staticmethod
    def compute_engagement_score(
        *, platform: str, views: int, likes: int, comments: int
    ) -> float:
        """Transparent engagement formula documented per platform."""
        plat = platform.upper()
        if plat in {"YOUTUBE", "TIKTOK"} and views > 0:
            return float(views + (likes * 5) + (comments * 10))
        return float(likes + (comments * 3) + (views * 0.1))

    @staticmethod
    def detect_creator_collab(caption: str, brand_keywords: list[str] | None = None) -> bool:
        lower = (caption or "").lower()
        return any(marker in lower for marker in COLLAB_MARKERS)

    @classmethod
    def rank_top_posts(
        cls,
        *,
        posts: list[dict[str, Any]],
        period_start: date,
        period_end: date,
        limit: int = 5,
        brand_keywords: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        in_range: list[dict[str, Any]] = []
        for post in posts:
            pub = post.get("published_at")
            if isinstance(pub, str):
                try:
                    pub = datetime.fromisoformat(pub.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    pub = None
            if not cls.is_within_period(pub, period_start, period_end):
                continue

            views = int(post.get("views") or 0)
            likes = int(post.get("likes") or 0)
            comments = int(post.get("comments") or 0)
            platform = str(post.get("platform") or "INSTAGRAM").upper()
            score = cls.compute_engagement_score(
                platform=platform, views=views, likes=likes, comments=comments
            )
            caption = str(post.get("caption") or "")
            is_collab = bool(
                post.get("is_creator_collab")
                or cls.detect_creator_collab(caption, brand_keywords)
            )
            enriched = {
                **post,
                "platform": platform,
                "published_at": pub,
                "views": views,
                "likes": likes,
                "comments": comments,
                "engagement_score": round(score, 2),
                "is_creator_collab": is_collab,
            }
            in_range.append(enriched)

        in_range.sort(key=lambda p: p["engagement_score"], reverse=True)
        top_n = in_range[:limit]
        for idx, item in enumerate(top_n, start=1):
            item["rank_order"] = idx
        return top_n
