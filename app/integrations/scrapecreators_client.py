from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from app.core.config import get_settings
from app.core.exceptions import ExternalApiError
from app.integrations.base_client import BaseApiClient


def _parse_relative_time_text(text: str) -> datetime | None:
    lower = text.lower().strip()
    m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)", lower)
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2)
    days = {
        "second": 0,
        "minute": 0,
        "hour": 0,
        "day": val,
        "week": val * 7,
        "month": val * 30,
        "year": val * 365,
    }.get(unit, 0)
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)


class ScrapeCreatorsClient(BaseApiClient):
    """ScrapeCreators API client for official SNS metrics, period TOP 5 posts, and creator collabs."""

    provider_name = "scrapecreators"

    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(
            base_url=settings.SCRAPECREATORS_BASE_URL,
            max_concurrency=settings.MAX_CONCURRENT_SCRAPECREATORS,
        )
        self.api_key = settings.SCRAPECREATORS_API_KEY.strip()

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ExternalApiError(
                provider=self.provider_name,
                code="API_KEY_NOT_CONFIGURED",
                message="SCRAPECREATORS_API_KEY 환경변수가 설정되어 있지 않습니다.",
                user_action_hint="backend/.env에 SCRAPECREATORS_API_KEY를 설정해 주세요.",
                retryable=False,
            )
        return {"x-api-key": self.api_key}

    async def fetch_profile_and_posts(
        self,
        *,
        platform: str,
        handle: str,
        account_url: str,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        headers = self._headers()
        plat = platform.upper()
        if plat == "INSTAGRAM":
            profile = await self.request_json(
                "GET",
                "/v1/instagram/profile",
                headers=headers,
                params={"handle": handle},
                force_refresh=force_refresh,
            )
            posts = await self.request_json(
                "GET",
                "/v1/instagram/user/posts",
                headers=headers,
                params={"handle": handle},
                force_refresh=force_refresh,
            )
            return self._normalize_payload("INSTAGRAM", profile, posts)
        if plat == "YOUTUBE":
            channel = await self.request_json(
                "GET",
                "/v1/youtube/channel",
                headers=headers,
                params={"handle": handle, "url": account_url},
                force_refresh=force_refresh,
            )
            videos = await self.request_json(
                "GET",
                "/v1/youtube/channel-videos",
                headers=headers,
                params={"handle": handle, "url": account_url},
                force_refresh=force_refresh,
            )
            return self._normalize_payload("YOUTUBE", channel, videos)
        if plat == "TIKTOK":
            profile = await self.request_json(
                "GET",
                "/v1/tiktok/profile",
                headers=headers,
                params={"handle": handle},
                force_refresh=force_refresh,
            )
            videos = await self.request_json(
                "GET",
                "/v1/tiktok/profile/videos",
                headers=headers,
                params={"handle": handle},
                force_refresh=force_refresh,
            )
            return self._normalize_payload("TIKTOK", profile, videos)

        raise ExternalApiError(
            provider=self.provider_name,
            code="UNSUPPORTED_PLATFORM",
            message=f"ScrapeCreators 미지원 플랫폼입니다: {platform}",
            retryable=False,
        )

    async def search_creator_collabs(
        self,
        *,
        platform: str,
        keyword: str,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        headers = self._headers()
        plat = platform.upper()
        if plat == "TIKTOK":
            raw = await self.request_json(
                "GET",
                "/v1/tiktok/search/keyword",
                headers=headers,
                params={"query": keyword, "keyword": keyword},
                force_refresh=force_refresh,
            )
            items = raw.get("items") or raw.get("data") or raw.get("videos") or []
            return [
                self._normalize_post("TIKTOK", item)
                for item in items
                if isinstance(item, dict)
            ]

        # Default & YOUTUBE: /v1/youtube/search returns videos + shorts with query=
        raw = await self.request_json(
            "GET",
            "/v1/youtube/search",
            headers=headers,
            params={"query": keyword},
            force_refresh=force_refresh,
        )
        items = list(raw.get("videos") or []) + list(raw.get("shorts") or []) + list(raw.get("items") or [])
        return [
            self._normalize_post("YOUTUBE", item)
            for item in items
            if isinstance(item, dict)
        ]

    def _normalize_payload(
        self, platform: str, profile: dict[str, Any], posts_raw: dict[str, Any]
    ) -> dict[str, Any]:
        profile_data = (
            profile.get("data", {}).get("user", profile.get("data", profile))
            if isinstance(profile.get("data"), dict)
            else profile
        )
        followers = (
            profile_data.get("follower_count")
            or profile_data.get("followers")
            or profile_data.get("subscriberCount")
            or (profile_data.get("edge_followed_by") or {}).get("count")
            or 0
        )
        raw_items = (
            list(posts_raw.get("items") or [])
            + list(posts_raw.get("posts") or [])
            + list(posts_raw.get("videos") or [])
            + list(posts_raw.get("shorts") or [])
            + (
                list(posts_raw.get("data") or [])
                if isinstance(posts_raw.get("data"), list)
                else []
            )
        )
        normalized_posts = [
            self._normalize_post(platform, item)
            for item in raw_items
            if isinstance(item, dict)
        ]
        return {
            "platform": platform,
            "followers": int(followers or 0),
            "posts": normalized_posts,
        }

    @staticmethod
    def _normalize_post(platform: str, item: dict[str, Any]) -> dict[str, Any]:
        node = item.get("node") if isinstance(item.get("node"), dict) else item

        ts_raw = (
            node.get("published_at")
            or node.get("taken_at")
            or node.get("taken_at_timestamp")
            or node.get("publishedTime")
            or node.get("createTime")
            or node.get("created_at")
        )
        published_at: datetime | None = None
        if isinstance(ts_raw, (int, float)):
            published_at = datetime.fromtimestamp(ts_raw, tz=timezone.utc).replace(tzinfo=None)
        elif isinstance(ts_raw, str):
            try:
                published_at = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                published_at = _parse_relative_time_text(ts_raw)

        if published_at is None and isinstance(node.get("publishedTimeText"), str):
            published_at = _parse_relative_time_text(node["publishedTimeText"])

        # Extract Instagram GraphQL caption if nested, or enrich YouTube title + description
        caption = node.get("caption") or node.get("title") or node.get("desc") or ""
        if isinstance(caption, dict):
            caption = caption.get("text") or ""
        if not caption and isinstance(node.get("edge_media_to_caption"), dict):
            edges = node["edge_media_to_caption"].get("edges") or []
            if edges and isinstance(edges[0], dict):
                caption = ((edges[0].get("node") or {}).get("text")) or ""

        if platform.upper() == "YOUTUBE":
            yt_desc = node.get("description") or node.get("descriptionSnippet") or ""
            if isinstance(yt_desc, dict):
                yt_desc = yt_desc.get("simpleText") or ""
            if isinstance(yt_desc, list):
                yt_desc = " ".join(str(x.get("text") or "") for x in yt_desc if isinstance(x, dict))
            yt_desc_str = str(yt_desc).strip()
            if yt_desc_str and yt_desc_str not in str(caption):
                caption = f"{caption} — {yt_desc_str}" if caption else yt_desc_str

        shortcode = node.get("shortcode")
        post_url = node.get("url") or node.get("permalink") or node.get("link") or ""
        if not post_url and shortcode and platform.upper() == "INSTAGRAM":
            post_url = f"https://www.instagram.com/p/{shortcode}/"
        if not post_url and platform.upper() == "YOUTUBE":
            raw_vid = str(node.get("videoId") or node.get("id") or "").strip()
            if raw_vid and len(raw_vid) >= 6:
                post_url = f"https://www.youtube.com/watch?v={raw_vid}"

        views = (
            node.get("video_play_count")
            or node.get("play_count")
            or node.get("view_count")
            or node.get("video_view_count")
            or node.get("views")
            or node.get("viewCountInt")
            or node.get("playCount")
            or 0
        )
        likes = (
            node.get("like_count")
            or node.get("likeCountInt")
            or node.get("likes")
            or node.get("diggCount")
            or (node.get("edge_media_preview_like") or {}).get("count")
            or 0
        )
        comments = (
            node.get("comment_count")
            or node.get("commentCountInt")
            or node.get("comments")
            or (node.get("edge_media_to_parent_comment") or {}).get("count")
            or (node.get("edge_media_preview_comment") or {}).get("count")
            or 0
        )
        raw_thumb = (
            node.get("thumbnail_url")
            or node.get("display_url")
            or node.get("thumbnail_src")
            or node.get("thumbnail")
            or node.get("thumbnails")
            or node.get("cover")
            or ""
        )
        if isinstance(raw_thumb, dict):
            thumb = raw_thumb.get("url") or ""
        elif isinstance(raw_thumb, list) and raw_thumb:
            first_t = raw_thumb[-1]
            thumb = first_t.get("url", "") if isinstance(first_t, dict) else str(first_t)
        else:
            thumb = str(raw_thumb or "")

        if not thumb and platform.upper() == "YOUTUBE":
            vid = str(node.get("videoId") or node.get("id") or "").strip()
            if not vid and post_url:
                m = re.search(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{6,})", str(post_url))
                if m:
                    vid = m.group(1)
            if vid:
                thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

        coauthors = node.get("coauthor_producers") or []
        is_collab = bool(
            node.get("is_paid_partnership")
            or node.get("is_ad")
            or (isinstance(coauthors, list) and len(coauthors) > 0)
        )

        return {
            "platform": platform,
            "post_url": post_url,
            "caption": str(caption),
            "published_at": published_at,
            "views": int(views or 0),
            "likes": int(likes or 0),
            "comments": int(comments or 0),
            "thumbnail_url": str(thumb),
            "is_creator_collab": is_collab,
        }
