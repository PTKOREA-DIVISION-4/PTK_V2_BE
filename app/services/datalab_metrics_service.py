from __future__ import annotations

from datetime import date
from typing import Any

from app.models.collection import DataLabSeries


class DataLabMetricsService:
    """Computes transparent search volume sums, Share of Search (%), growth rate, and peaks.

    Strictly avoids opaque/arbitrary scoring; every metric embeds its exact calculation basis.
    """

    @staticmethod
    def compute_series_metrics(
        *,
        project_id: str,
        metric_type: str,
        raw_results: list[dict[str, Any]],
        owner_type_by_label: dict[str, str],
        period_start: date,
        period_end: date,
        time_unit: str = "week",
        is_anchor_normalized: bool = False,
    ) -> list[DataLabSeries]:
        if not raw_results:
            return []

        per_series_sums: list[tuple[dict[str, Any], list[dict[str, Any]], float]] = []
        total_sum = 0.0

        for entry in raw_results:
            points = [
                {
                    "period": str(pt.get("period", "")),
                    "ratio": round(float(pt.get("ratio", 0.0)), 4),
                }
                for pt in (entry.get("data") or [])
                if isinstance(pt, dict)
            ]
            s_sum = round(sum(pt["ratio"] for pt in points), 4)
            total_sum += s_sum
            per_series_sums.append((entry, points, s_sum))

        denom = total_sum if total_sum > 0 else 1.0
        anchor_note = (
            " (5개 초과 비교군으로 자사 기준 Anchor 비례 환산 적용)"
            if is_anchor_normalized
            else ""
        )
        basis_label = (
            "검색량 상대지수(최댓값=100) 구간 합산 점유율"
            if metric_type == "SEARCH_TREND"
            else "쇼핑 클릭 상대지수(최댓값=100) 구간 합산 점유율"
        )
        methodology = (
            f"출처: 네이버 데이터랩 | 기간: {period_start.isoformat()}~{period_end.isoformat()} ({time_unit}) | "
            f"기준: {basis_label}{anchor_note}"
        )

        entities: list[DataLabSeries] = []
        # Compute share percentages and normalize last element if rounding drifts slightly from 100.0
        raw_shares = [
            round((s_sum / denom) * 100.0, 2) if total_sum > 0 else 0.0
            for _, _, s_sum in per_series_sums
        ]
        if total_sum > 0 and raw_shares:
            diff = round(100.0 - sum(raw_shares), 2)
            raw_shares[0] = round(raw_shares[0] + diff, 2)

        for idx, (entry, points, s_sum) in enumerate(per_series_sums):
            label = str(entry.get("title") or entry.get("groupName") or f"Group {idx+1}")
            owner_type = owner_type_by_label.get(label, "COMPETITOR")

            # Growth rate: second half average vs first half average
            growth_rate = 0.0
            if len(points) >= 2:
                mid = len(points) // 2
                first_half = [p["ratio"] for p in points[:mid]]
                second_half = [p["ratio"] for p in points[mid:]]
                first_avg = sum(first_half) / max(1, len(first_half))
                second_avg = sum(second_half) / max(1, len(second_half))
                if first_avg > 0:
                    growth_rate = round(((second_avg - first_avg) / first_avg) * 100.0, 2)

            peak_pt = max(points, key=lambda p: p["ratio"], default=None)
            entities.append(
                DataLabSeries(
                    project_id=project_id,
                    metric_type=metric_type,
                    group_label=label,
                    owner_type=owner_type,
                    period_start=period_start,
                    period_end=period_end,
                    time_unit=time_unit,
                    points_json=points,
                    cumulative_index_sum=round(s_sum, 2),
                    share_of_search_pct=raw_shares[idx],
                    growth_rate_pct=growth_rate,
                    peak_date=peak_pt["period"] if peak_pt else None,
                    peak_value=round(peak_pt["ratio"], 2) if peak_pt else 0.0,
                    methodology_note=methodology,
                )
            )
        return entities
