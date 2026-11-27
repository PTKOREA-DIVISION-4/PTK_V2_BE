"""Deterministic aggregation service for News/PR coverage metrics."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any


def _extract_year_month(raw: Any) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    m = re.search(r"(20[2-3][0-9])[./-](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return None


class PressMetricsService:
    """Computes verified monthly counts, topic mix, and brand shares from collected news sources."""

    @staticmethod
    def summarize_press(
        *,
        sources: list[Any],
        brand_names: list[str],
    ) -> dict[str, Any]:
        press_items = [
            s
            for s in sources
            if getattr(s, "review_status", "PENDING") != "REJECTED"
            and (
                getattr(s, "channel", "") == "news_press"
                or "보도" in (getattr(s, "title", "") or "")
            )
        ]

        monthly: Counter[str] = Counter()
        topics: Counter[str] = Counter()
        by_brand: Counter[str] = Counter({b: 0 for b in brand_names if b})

        for item in press_items:
            meta = getattr(item, "metadata_json", None) or {}
            title = getattr(item, "title", "") or ""
            content = getattr(item, "content", "") or ""
            blob = f"{title} {content}"

            # Only count month if explicitly parsed from date metadata/article text (never invent fake months)
            ym = _extract_year_month(meta.get("published_date_raw")) or _extract_year_month(title)
            if ym:
                monthly[ym] += 1

            topic = str(meta.get("topic_tag") or "").strip()
            if not topic:
                if any(k in blob for k in ("출시", "신제품", "컬렉션", "런칭", "론칭")):
                    topic = "신제품 출시"
                elif any(k in blob for k in ("협업", "콜라보", "모델")):
                    topic = "협업·콜라보"
                elif any(k in blob for k in ("팝업", "플래그십", "스토어", "오픈")):
                    topic = "팝업·체험"
                elif any(k in blob for k in ("매출", "영업이익", "실적", "성장")):
                    topic = "실적·경영"
                else:
                    topic = "일반 보도"
            topics[topic] += 1

            b_name = str(meta.get("brand_name") or "").strip()
            if b_name and b_name in by_brand:
                by_brand[b_name] += 1
            else:
                for b in brand_names:
                    if b and b in blob:
                        by_brand[b] += 1
                        break

        sorted_months = sorted(monthly.items(), key=lambda x: x[0])
        sorted_topics = sorted(topics.items(), key=lambda x: (-x[1], x[0]))
        brand_items = [
            {"label": b, "value": by_brand.get(b, 0), "highlight": idx == 0}
            for idx, b in enumerate(brand_names)
            if b
        ]
        sample_rows = [
            [
                str((getattr(it, "metadata_json", None) or {}).get("published_date_raw") or "확인 못 함")[:12],
                str((getattr(it, "metadata_json", None) or {}).get("brand_name") or "-"),
                str((getattr(it, "metadata_json", None) or {}).get("topic_tag") or "보도"),
                (getattr(it, "title", "") or "")[:60],
                str(getattr(it, "source_url", "") or ""),
            ]
            for it in press_items[:8]
        ]
        return {
            "total_articles": len(press_items),
            "monthly_items": [{"label": m, "value": c, "highlight": False} for m, c in sorted_months],
            "topic_items": [{"label": t, "value": c, "highlight": i == 0} for i, (t, c) in enumerate(sorted_topics)],
            "brand_items": brand_items,
            "sample_rows": sample_rows,
        }
