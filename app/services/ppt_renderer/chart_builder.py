from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


def _register_pretendard_fonts() -> None:
    font_dirs = [
        Path.home() / "Library" / "Fonts",
        Path("/Library/Fonts"),
        Path("/usr/share/fonts"),
    ]
    for base in font_dirs:
        if not base.exists():
            continue
        for ttf in base.glob("Pretendard-*.ttf"):
            try:
                fm.fontManager.addfont(str(ttf))
            except Exception:
                continue


def _configure_korean_font() -> None:
    _register_pretendard_fonts()
    preferred = [
        "Pretendard",
        "AppleGothic",
        "Apple SD Gothic Neo",
        "Malgun Gothic",
        "NanumGothic",
        "Noto Sans CJK KR",
        "Noto Sans KR",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in preferred:
        if name in available:
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False


_configure_korean_font()


def build_datalab_trend_chart(
    *,
    series_list: list[Any],
    output_path: Path,
    title: str = "네이버 데이터랩 검색 관심도 추이",
) -> Path | None:
    if not series_list:
        return None
    _configure_korean_font()
    fig, ax = plt.subplots(figsize=(6.4, 3.3), dpi=200)
    # Division 4 monochrome + orange accent palette
    palette = ["#111111", "#E9501F", "#6B7280", "#9CA3AF", "#D1D5DB"]

    has_points = False
    x: list[str] = []
    for idx, series in enumerate(series_list[:5]):
        pts = getattr(series, "points_json", None) or []
        if not pts:
            continue
        has_points = True
        x = [
            p["period"][5:] if len(str(p.get("period", ""))) >= 10 else str(p.get("period", ""))
            for p in pts
        ]
        y = [float(p.get("ratio", 0.0)) for p in pts]
        is_own = getattr(series, "owner_type", "") == "OWN"
        color = "#E9501F" if is_own else palette[(idx % (len(palette) - 1)) + 1 if idx > 0 else 2]
        if is_own and idx == 0:
            color = "#111111"
        ax.plot(
            x,
            y,
            label=getattr(series, "group_label", f"Series {idx+1}"),
            color=color,
            linewidth=2.6 if is_own else 1.8,
            marker="o" if len(x) <= 12 else None,
            markersize=4,
        )

    if not has_points:
        plt.close(fig)
        return None

    ax.set_title(title, fontsize=10.5, fontweight="bold", color="#111111", pad=8)
    ax.set_ylabel("상대 검색지수 (최대=100)", fontsize=8.5, color="#4A4A4A")
    ax.set_ylim(0, 108)
    ax.grid(axis="y", linestyle="--", alpha=0.35, color="#E5E5E5")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D4D4D4")
    ax.spines["bottom"].set_color("#D4D4D4")
    if len(x) > 8:
        ax.xaxis.set_major_locator(MaxNLocator(nbins=8))
    ax.tick_params(axis="x", labelsize=7.5, rotation=20, colors="#4A4A4A")
    ax.tick_params(axis="y", labelsize=8, colors="#4A4A4A")
    ax.legend(fontsize=7.5, frameon=False, loc="upper left", ncol=2)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, facecolor="#FFFFFF")
    plt.close(fig)
    return output_path


def build_share_of_search_chart(
    *,
    series_list: list[Any],
    output_path: Path,
    title: str = "경쟁군 검색 점유율 (Share of Search, %)",
    shopping_series: list[Any] | None = None,
) -> Path | None:
    if not series_list:
        return None
    _configure_korean_font()
    search_items = list(series_list[:5])
    labels = [getattr(s, "group_label", "")[:18] for s in search_items]
    search_vals = [float(getattr(s, "share_of_search_pct", 0.0)) for s in search_items]

    # Match Shopping Insight by group_label when available to visualize funnel gap cleanly
    shop_by_label = {
        getattr(s, "group_label", ""): float(getattr(s, "share_of_search_pct", 0.0))
        for s in (shopping_series or [])
    }
    has_shopping = bool(shopping_series) and any(
        getattr(s, "group_label", "") in shop_by_label for s in search_items
    )

    fig, ax = plt.subplots(figsize=(5.6, 3.0), dpi=200)
    y_pos = list(range(len(labels)))

    if has_shopping:
        shop_vals = [shop_by_label.get(getattr(s, "group_label", ""), 0.0) for s in search_items]
        bar_h = 0.34
        bars_s = ax.barh(
            [y - bar_h / 2 for y in y_pos],
            search_vals,
            height=bar_h,
            color="#111111",
            label="통합검색 SoS (%)",
        )
        bars_sh = ax.barh(
            [y + bar_h / 2 for y in y_pos],
            shop_vals,
            height=bar_h,
            color="#E9501F",
            label="쇼핑 클릭 점유율 (%)",
        )
        max_x = max(search_vals + shop_vals + [10.0])
        ax.set_xlim(0, max_x * 1.28)
        for bar, val in zip(bars_s, search_vals):
            ax.text(
                bar.get_width() + 0.8,
                bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}%",
                va="center",
                fontsize=7.6,
                fontweight="bold",
                color="#111111",
            )
        for bar, val in zip(bars_sh, shop_vals):
            ax.text(
                bar.get_width() + 0.8,
                bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}%",
                va="center",
                fontsize=7.6,
                fontweight="bold",
                color="#E9501F",
            )
        ax.legend(fontsize=7.8, frameon=False, loc="lower right")
    else:
        colors = [
            "#E9501F" if getattr(s, "owner_type", "") == "OWN" else "#262626"
            for s in search_items
        ]
        bars = ax.barh(y_pos, search_vals, color=colors, height=0.52)
        ax.set_xlim(0, max(search_vals + [10.0]) * 1.25)
        for bar, val in zip(bars, search_vals):
            ax.text(
                bar.get_width() + 1.0,
                bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}%",
                va="center",
                fontsize=8.5,
                fontweight="bold",
                color="#111111",
            )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8.5, color="#111111")
    ax.invert_yaxis()
    ax.set_title(title[:42], fontsize=9.8, fontweight="bold", color="#111111", pad=8)
    ax.set_xlabel("구간 합산 점유율 (%)", fontsize=8, color="#4A4A4A")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D4D4D4")
    ax.spines["bottom"].set_color("#D4D4D4")
    ax.grid(axis="x", linestyle="--", alpha=0.35, color="#E5E5E5")

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, facecolor="#FFFFFF")
    plt.close(fig)
    return output_path


def build_horizontal_bar_chart(
    *,
    items: list[dict[str, Any]],
    unit: str,
    title: str,
    output_path: Path,
) -> Path | None:
    """Renders crisp Division 4 horizontal bar charts for market sizes, prices, or frequencies."""
    valid = [
        it for it in items
        if isinstance(it, dict) and str(it.get("label") or "").strip() and isinstance(it.get("value"), (int, float))
    ][:7]
    if not valid:
        return None
    _configure_korean_font()
    labels = [str(it["label"])[:20] for it in valid]
    values = [float(it["value"]) for it in valid]
    colors = ["#E9501F" if it.get("highlight") else "#111111" for it in valid]

    fig, ax = plt.subplots(figsize=(5.8, 3.0), dpi=200)
    y_pos = list(range(len(labels)))
    bars = ax.barh(y_pos, values, color=colors, height=0.52)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8.5, color="#111111")
    ax.invert_yaxis()
    max_v = max(values) if values else 1.0
    ax.set_xlim(0, max_v * 1.28)
    ax.set_title(title[:45], fontsize=10, fontweight="bold", color="#111111", pad=8)
    if unit:
        ax.set_xlabel(f"단위: {unit}", fontsize=8, color="#4A4A4A")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D4D4D4")
    ax.spines["bottom"].set_color("#D4D4D4")
    ax.grid(axis="x", linestyle="--", alpha=0.35, color="#E5E5E5")

    for bar, val in zip(bars, values):
        fmt_v = f"{val:,.0f}" if abs(val - round(val)) < 0.01 else f"{val:,.1f}"
        suffix = f" {unit}" if unit and len(unit) <= 6 else ""
        ax.text(
            bar.get_width() + (max_v * 0.02),
            bar.get_y() + bar.get_height() / 2,
            f"{fmt_v}{suffix}",
            va="center",
            fontsize=8.2,
            fontweight="bold",
            color="#111111",
        )

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, facecolor="#FFFFFF")
    plt.close(fig)
    return output_path


def build_consumer_sentiment_chart(
    *,
    positive: int,
    negative: int,
    neutral: int,
    output_path: Path,
) -> Path:
    _configure_korean_font()
    labels = ["긍정 / 만족", "중립 / 정보", "부정 / 불만"]
    vals = [positive, neutral, negative]
    colors = ["#1F8A5B", "#737373", "#DC2626"]

    fig, ax = plt.subplots(figsize=(5.2, 2.5), dpi=200)
    bars = ax.bar(labels, vals, color=colors, width=0.45)
    ax.set_title("수집 VOC 감성 분포 (건수)", fontsize=10, fontweight="bold", color="#111111", pad=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D4D4D4")
    ax.spines["bottom"].set_color("#D4D4D4")
    ax.grid(axis="y", linestyle="--", alpha=0.35, color="#E5E5E5")
    ax.set_ylim(0, max(vals + [1]) * 1.32)
    for bar, val in zip(bars, vals):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.15,
            f"{val}건",
            ha="center",
            va="bottom",
            fontsize=8.5,
            fontweight="bold",
            color="#111111",
        )
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, facecolor="#FFFFFF")
    plt.close(fig)
    return output_path


def build_price_discount_chart(
    *,
    items: list[dict[str, Any]],
    unit: str = "만원",
    title: str = "주요 라인업 정가 vs 할인가 비교",
    output_path: Path,
) -> Path | None:
    """Render dual horizontal bar chart comparing list price vs sale price."""
    valid = [
        it for it in items
        if isinstance(it, dict) and str(it.get("label") or "").strip() and float(it.get("list_price") or 0) > 0
    ][:6]
    if not valid:
        return None
    _configure_korean_font()
    labels = [str(it["label"])[:18] for it in valid]
    list_vals = [float(it.get("list_price") or 0) for it in valid]
    sale_vals = [float(it.get("sale_price") or it.get("list_price") or 0) for it in valid]

    fig, ax = plt.subplots(figsize=(5.8, 3.2), dpi=200)
    y_pos = list(range(len(labels)))
    bar_h = 0.34
    ax.barh([y - bar_h / 2 for y in y_pos], list_vals, height=bar_h, color="#D4D4D4", label="공식 정가")
    bars_s = ax.barh([y + bar_h / 2 for y in y_pos], sale_vals, height=bar_h, color="#E9501F", label="실판매/할인가")

    max_v = max(list_vals + sale_vals + [10.0])
    ax.set_xlim(0, max_v * 1.32)
    for idx, _bar in enumerate(bars_s):
        disc = valid[idx].get("discount_pct")
        disc_str = f" (-{float(disc):.0f}%)" if disc else ""
        ax.text(
            max(list_vals[idx], sale_vals[idx]) + max_v * 0.02,
            y_pos[idx],
            f"{sale_vals[idx]:g}{unit}{disc_str}",
            va="center",
            fontsize=8.5,
            fontweight="bold",
            color="#111111",
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8.8, color="#111111")
    ax.invert_yaxis()
    ax.set_title(title[:45], fontsize=10, fontweight="bold", color="#111111", pad=8)
    ax.set_xlabel(f"단위: {unit}", fontsize=8.5, color="#4A4A4A")
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", linestyle="--", alpha=0.35, color="#E5E5E5")

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, facecolor="#FFFFFF")
    plt.close(fig)
    return output_path


def build_press_monthly_chart(
    *,
    items: list[dict[str, Any]],
    title: str = "월별 언론 보도(News/PR) 추이",
    output_path: Path,
) -> Path | None:
    """Render vertical bar chart for monthly News/PR volume highlighting the peak month."""
    valid = [it for it in items if isinstance(it, dict) and str(it.get("label") or "").strip()]
    if not valid:
        return None
    _configure_korean_font()
    labels = [str(it["label"]) for it in valid]
    vals = [int(it.get("value") or 0) for it in valid]
    peak = max(vals) if vals else 0
    colors = ["#E9501F" if (v == peak and peak > 0) else "#111111" for v in vals]

    fig, ax = plt.subplots(figsize=(5.6, 3.0), dpi=200)
    bars = ax.bar(labels, vals, color=colors, width=0.52)
    ax.set_ylim(0, max(vals + [1]) * 1.32)
    ax.set_title(title[:45], fontsize=10, fontweight="bold", color="#111111", pad=8)
    ax.set_ylabel("보도 기사 수 (건)", fontsize=8.5, color="#4A4A4A")
    ax.tick_params(axis="x", labelsize=8.2, rotation=15, colors="#111111")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.35, color="#E5E5E5")
    for bar, v in zip(bars, vals):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.12,
            f"{v}건",
            ha="center",
            va="bottom",
            fontsize=8.5,
            fontweight="bold",
            color="#111111",
        )

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, facecolor="#FFFFFF")
    plt.close(fig)
    return output_path


def build_press_brand_chart(
    *,
    items: list[dict[str, Any]],
    title: str = "브랜드별 언론 보도 기사 건수 비교",
    output_path: Path,
) -> Path | None:
    return build_horizontal_bar_chart(
        items=items,
        unit="건",
        title=title,
        output_path=output_path,
    )


def build_marketing_heatmap_chart(
    *,
    brands: list[str],
    rows: list[dict[str, Any]],
    title: str = "마케팅 활동 6분류 강도 히트맵 (1~5점)",
    output_path: Path,
) -> Path | None:
    """Render annotated 6xN matrix heatmap in Division 4 Cream/Orange scale."""
    if not brands or not rows:
        return None
    _configure_korean_font()

    axes_labels = [str(r.get("axis") or "")[:14] for r in rows[:6]]
    matrix: list[list[int]] = []
    for r in rows[:6]:
        scores = r.get("scores") or []
        row_vals: list[int] = []
        for idx, b in enumerate(brands):
            matched = next((sc for sc in scores if isinstance(sc, dict) and sc.get("brand") == b), None)
            if matched is None and idx < len(scores) and isinstance(scores[idx], dict):
                matched = scores[idx]
            val = int(matched.get("score", 1)) if isinstance(matched, dict) else 1
            row_vals.append(max(1, min(5, val)))
        matrix.append(row_vals)

    color_map = {
        1: ("#F5F5F5", "#8C8C8C"),
        2: ("#E5E5E5", "#111111"),
        3: ("#262626", "#FFFFFF"),
        4: ("#F48A66", "#111111"),
        5: ("#E9501F", "#FFFFFF"),
    }

    fig, ax = plt.subplots(figsize=(5.8, 3.2), dpi=200)
    ax.set_xlim(0, len(brands))
    ax.set_ylim(0, len(axes_labels))
    for r_idx, row_vals in enumerate(matrix):
        y = len(axes_labels) - 1 - r_idx
        for c_idx, val in enumerate(row_vals):
            bg, fg = color_map.get(val, ("#F5F5F5", "#111111"))
            rect = plt.Rectangle((c_idx + 0.05, y + 0.08), 0.90, 0.84, facecolor=bg, edgecolor="#D4D4D4", linewidth=0.8)
            ax.add_patch(rect)
            ax.text(
                c_idx + 0.5,
                y + 0.5,
                f"{val}점",
                ha="center",
                va="center",
                fontsize=9,
                fontweight="bold",
                color=fg,
            )

    ax.set_xticks([i + 0.5 for i in range(len(brands))])
    ax.set_xticklabels([b[:12] for b in brands], fontsize=8.8, fontweight="bold", color="#111111")
    ax.xaxis.tick_top()
    ax.set_yticks([len(axes_labels) - 1 - i + 0.5 for i in range(len(axes_labels))])
    ax.set_yticklabels(axes_labels, fontsize=8.8, fontweight="bold", color="#111111")
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)
    ax.set_title(title[:45], fontsize=10, fontweight="bold", color="#111111", pad=20)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, facecolor="#FFFFFF")
    plt.close(fig)
    return output_path
