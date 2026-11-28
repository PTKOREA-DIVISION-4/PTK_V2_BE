"""Automated 100-point Factbook quality evaluator v2 (High-density 36+, INDEX/Divider, Pretendard, Hyperlinks)."""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from pptx import Presentation

API = "http://127.0.0.1:8000/api/v1"


def get_json(path: str):
    return json.loads(urllib.request.urlopen(f"{API}{path}", timeout=30).read().decode("utf-8"))


def post_json(path: str, body: dict | None = None):
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))


def evaluate(pid: str, pptx_path: Path, api_base: str = API) -> dict:
    global API
    API = api_base.rstrip("/")
    slides = get_json(f"/projects/{pid}/slides")
    sources_res = get_json(f"/projects/{pid}/sources?page=1&page_size=200")
    sources = sources_res["items"]
    dl = get_json(f"/projects/{pid}/datalab")
    sns = get_json(f"/projects/{pid}/sns-top5")
    qc = post_json(f"/projects/{pid}/exports/qc")
    prs = Presentation(str(pptx_path))

    deductions: list[str] = []
    scores: dict[str, float] = {}
    slide_types = {s["slide_type"] for s in slides}

    # 1. Structural Completeness & High-Density Coverage (15 pts)
    s1 = 15.0
    required_secs = {"0_OVERVIEW", "1_OWN", "2_MARKET", "3_COMPETITOR", "4_CONSUMER", "5_SUMMARY_CONCLUSION"}
    present_secs = {s["section_code"] for s in slides}
    missing_secs = required_secs - present_secs
    if missing_secs:
        s1 -= len(missing_secs) * 2.5
        deductions.append(f"[Structure] Missing sections: {missing_secs}")

    if len(slides) < 35:
        pen = min(4.5, round((35 - len(slides)) * 0.6, 1))
        s1 -= pen
        deductions.append(f"[Structure] Body slides {len(slides)} < 35 high-density target (-{pen})")

    has_cover = bool(slides and slides[0].get("slide_type") == "COVER")
    has_index = any(s.get("slide_type") == "INDEX" for s in slides[:2])
    if not has_cover:
        s1 -= 1.0
        deductions.append("[Structure] Missing COVER slide at slide_order=1 (-1.0)")
    if not has_index:
        s1 -= 2.0
        deductions.append("[Structure] Missing INDEX slide (-2.0)")

    divider_cnt = sum(1 for s in slides if s.get("slide_type") == "SECTION_DIVIDER")
    if divider_cnt < 5:
        s1 -= 2.0
        deductions.append(f"[Structure] SECTION_DIVIDER count {divider_cnt} < 5 (-2.0)")

    required_types = {
        "OWN_PRODUCTS_PRICE",
        "OWN_CHANNELS",
        "OWN_INSTAGRAM_TOP5",
        "OWN_YOUTUBE_TOP5",
        "OWN_PRESS_ANALYSIS",
        "MARKET_OVERVIEW",
        "MARKET_DEMAND_TREND",
        "COMPETITOR_MATRIX",
        "COMPETITOR_DETAIL",
        "COMPETITOR_SNS_TOP5",
        "COMPETITOR_PRESS",
        "COMPETITOR_MARKETING_6",
        "CONSUMER_TARGET",
        "CONSUMER_VOC",
        "CONSUMER_VOC_VOICES",
        "CONSUMER_BENCHMARKS",
        "SUMMARY_PART",
        "CONCLUSION_ASIS_TOBE",
        "DATA_GAP",
        "APPENDIX_SOURCES",
    }
    missing_types = required_types - slide_types
    if missing_types:
        pen = min(5.0, round(len(missing_types) * 0.75, 1))
        s1 -= pen
        deductions.append(f"[Structure] Missing v2 slide types ({len(missing_types)}): {sorted(missing_types)} (-{pen})")
    scores["1_structural_completeness"] = max(0.0, round(s1, 1))

    # 2. Data Richness & Coverage (15 pts)
    s2 = 15.0
    if len(sources) < 50:
        s2 -= 2.0
        deductions.append(f"[Data] Total sources {len(sources)} < 50")
    if len(dl.get("search_trends", [])) < 4 or len(dl.get("shopping_insights", [])) < 4:
        s2 -= 3.0
        deductions.append(
            f"[Data] DataLab incomplete: search={len(dl.get('search_trends', []))}, shopping={len(dl.get('shopping_insights', []))}"
        )
    news_cnt = sum(1 for s in sources if s.get("channel") == "news_press")
    if news_cnt == 0:
        s2 -= 1.5
        deductions.append("[Data] Zero news_press articles collected (-1.5)")

    all_sns = sns.get("own_top_posts", []) + sns.get("competitor_top_posts", []) + sns.get("creator_collabs", [])
    comp_official = [p for p in all_sns if p["owner_type"] == "COMPETITOR"]
    if len(comp_official) < 5:
        s2 -= 1.5
        deductions.append(f"[Data] Competitor SNS TOP posts {len(comp_official)} < 5 (-1.5)")

    m6_slide = next((s for s in slides if s["slide_type"] == "COMPETITOR_MARKETING_6"), None)
    if m6_slide and m6_slide.get("table"):
        cells = [str(c) for r in m6_slide["table"]["rows"] for c in r[1:]]
        unknown_cnt = sum(1 for c in cells if "확인 못 함" in c or "확인 불가" in c)
        ratio = unknown_cnt / max(1, len(cells))
        if ratio > 0.45:
            pen = round(min(4.0, (ratio - 0.30) * 8), 1)
            s2 -= pen
            deductions.append(f"[Data] COMPETITOR_MARKETING_6 unknown ratio {ratio:.0%} (-{pen})")

    mp_slide = next((s for s in slides if s["slide_type"] == "MARKET_PLAYERS"), None)
    if mp_slide and mp_slide.get("table"):
        mp_cells = [str(c) for r in mp_slide["table"]["rows"] for c in r]
        mp_unk = sum(1 for c in mp_cells if "확인 못 함" in c)
        if mp_unk >= 3:
            s2 -= 1.5
            deductions.append(f"[Data] MARKET_PLAYERS has {mp_unk} '확인 못 함' cells (-1.5)")
    scores["2_data_richness_and_coverage"] = max(0.0, round(s2, 1))

    # 3. Quantitative Accuracy & Sign Integrity (15 pts)
    s3 = 15.0
    neg_dl_series = [d for d in dl.get("search_trends", []) + dl.get("shopping_insights", []) if d["growth_rate_pct"] < 0]
    neg_tokens = {f"{abs(float(d['growth_rate_pct'])):g}%" for d in neg_dl_series} | {
        f"{abs(float(d['growth_rate_pct'])):.1f}%" for d in neg_dl_series
    }
    own_prof = next((s for s in slides if s["slide_type"] == "OWN_PROFILE"), None)
    if own_prof and own_prof.get("kpi_cards") and neg_tokens:
        missing_minus = []
        for k in own_prof["kpi_cards"]:
            delta = str(k.get("delta") or "").strip()
            if any(tok in delta for tok in neg_tokens) and not delta.startswith("-"):
                missing_minus.append(f"{k['label']}:{delta}")
        if missing_minus:
            s3 -= 4.0
            deductions.append(f"[Accuracy] Stripped minus sign in OWN_PROFILE KPIs: {missing_minus} (-4.0)")

    double_src_slides = [s["slide_order"] for s in slides if "출처: 출처:" in str(s.get("footnote") or "")]
    if double_src_slides:
        s3 -= 2.0
        deductions.append(f"[Accuracy] Double '출처: 출처:' footnote on slides {double_src_slides} (-2.0)")

    true_urls: set[str] = set()
    for src in sources:
        if src.get("source_url"):
            true_urls.add(src["source_url"])
        for cit in (src.get("metadata") or {}).get("citations", []) if isinstance(src.get("metadata"), dict) else []:
            if cit:
                true_urls.add(str(cit))
    app_slide = next((s for s in slides if s["slide_type"] == "APPENDIX_SOURCES"), None)
    if app_slide and "6건" in app_slide["headcopy"] and len(true_urls) > 10:
        s3 -= 2.0
        deductions.append(f"[Accuracy] APPENDIX reports only 6 unique URLs despite {len(true_urls)} unique URLs in DB (-2.0)")

    voc_slide = next((s for s in slides if s["slide_type"] == "CONSUMER_VOC"), None)
    if voc_slide:
        kpis_str = json.dumps(voc_slide.get("kpi_cards") or [], ensure_ascii=False)
        if "부정 0.0%" in kpis_str or "부정 0 /" in kpis_str:
            s3 -= 2.5
            deductions.append("[Accuracy] CONSUMER_VOC reports 부정 0% despite critical concerns (-2.5)")
    scores["3_quantitative_accuracy"] = max(0.0, round(s3, 1))

    # 4. Analytical Synthesis Quality (15 pts)
    s4 = 15.0
    raw_fallback_slides = []
    dup_bullet_slides = []
    for s in slides:
        claims = [b.get("claim", "") for b in s.get("bullets", [])]
        if any(re.match(r"^\[(perplexity_research|instagram|youtube|naver_blog|dcinside|theqoo)\]", c) for c in claims):
            raw_fallback_slides.append(s["slide_order"])
        if len(claims) != len(set(claims)):
            dup_bullet_slides.append(s["slide_order"])
    if raw_fallback_slides:
        pen = min(5.0, len(raw_fallback_slides) * 2.0)
        s4 -= pen
        deductions.append(f"[Synthesis] Raw fallback '[channel] title' bullets on slides {raw_fallback_slides} (-{pen})")
    if dup_bullet_slides:
        s4 -= 2.5
        deductions.append(f"[Synthesis] Duplicate bullets on slides {dup_bullet_slides} (-2.5)")
    hcs = [s["headcopy"] for s in slides]
    if len(hcs) != len(set(hcs)):
        s4 -= 2.0
        deductions.append("[Synthesis] Duplicate headcopies detected (-2.0)")
    scores["4_analytical_synthesis"] = max(0.0, round(s4, 1))

    # 5. Alignment, Narrative Flow & Visual-to-Text Density (10 pts)
    s5 = 10.0
    own_ch = next((s for s in slides if s["slide_type"] == "OWN_CHANNELS"), None)
    if own_ch and own_ch.get("table"):
        joined = own_ch["headcopy"] + " " + " ".join(b["claim"] for b in own_ch.get("bullets", []))
        if "팔로워" not in joined and "SNS" not in joined and "구독자" not in joined and "계정" not in joined:
            s5 -= 2.5
            deductions.append("[Alignment] OWN_CHANNELS ignores SNS scale metrics (-2.5)")
    a2b = next((s for s in slides if s["slide_type"] == "CONCLUSION_ASIS_TOBE"), None)
    if not a2b or not a2b.get("as_is_to_be") or any(len(a2b["as_is_to_be"].get(k, [])) < 3 for k in ("as_is_points", "key_issues", "to_be_directions")):
        s5 -= 2.0
        deductions.append("[Alignment] CONCLUSION_ASIS_TOBE incomplete (-2.0)")
    body_slides = [s for s in slides if s.get("slide_type") not in {"COVER", "INDEX", "SECTION_DIVIDER"}]
    visual_ratio = sum(
        1 for s in body_slides if s.get("visual_assets") or s.get("table") or s.get("as_is_to_be")
    ) / max(1, len(body_slides))
    if visual_ratio < 0.70:
        s5 -= 2.0
        deductions.append(f"[Alignment] Visual/table slide density ratio {visual_ratio:.0%} < 70% (-2.0)")
    scores["5_alignment_and_flow"] = max(0.0, round(s5, 1))

    # 6. Hallucination-Zero & URL Traceability (10 pts)
    s6 = 10.0
    bad_tokens = ["확인 중", "추후 보강", "TODO", "TBD", "Lorem"]
    bad_hits = []
    truncated_urls = 0
    for s in slides:
        blob = json.dumps(s, ensure_ascii=False)
        for tok in bad_tokens:
            if tok in blob:
                bad_hits.append((s["slide_order"], tok))
        for b in s.get("bullets", []):
            u = str(b.get("source_url") or "")
            if u.startswith("http") and ("..." in u or u.endswith("…")):
                truncated_urls += 1
        for r in (s.get("table") or {}).get("rows", []):
            for cell in r:
                cs = str(cell or "")
                if cs.startswith("http") and ("..." in cs or cs.endswith("…")):
                    truncated_urls += 1
    if bad_hits:
        s6 -= min(5.0, len(bad_hits) * 1.5)
        deductions.append(f"[Trust] Forbidden placeholders found: {bad_hits}")
    if truncated_urls > 0:
        s6 -= min(2.5, truncated_urls * 0.5)
        deductions.append(f"[Trust] Truncated http URLs detected ({truncated_urls}) breaking hyperlinks")
    gap_slide = next((s for s in slides if s["slide_type"] == "DATA_GAP"), None)
    if not gap_slide or not gap_slide.get("table") or len(gap_slide["table"]["rows"]) < 4:
        s6 -= 2.0
        deductions.append("[Trust] DATA_GAP table < 4 rows (-2.0)")
    scores["6_hallucination_zero"] = max(0.0, round(s6, 1))

    # 7. Visual & Chart Density (10 pts)
    s7 = 10.0
    total_pics = sum(1 for sl in prs.slides for sh in sl.shapes if sh.shape_type == 13)
    if total_pics < 16:
        s7 -= 2.5
        deductions.append(f"[Visual] PPTX embedded pictures {total_pics} < 16 (-2.5)")
    comp_mat = next((s for s in slides if s["slide_type"] == "COMPETITOR_MATRIX"), None)
    if comp_mat and dl.get("shopping_insights") and not any("쇼핑" in (v.get("title") or "") for v in comp_mat.get("visual_assets", [])):
        s7 -= 1.5
        deductions.append("[Visual] COMPETITOR_MATRIX SoS chart misses Shopping Insight comparison (-1.5)")
    has_v2_visual = any(
        (v.get("asset_type") in {"PRICE_DISCOUNT_BAR", "PRESS_MONTHLY_BAR", "PRESS_BRAND_BAR", "MARKETING_HEATMAP"})
        for s in slides
        for v in s.get("visual_assets", [])
    )
    if not has_v2_visual:
        s7 -= 1.5
        deductions.append("[Visual] No v2 charts (PRICE_DISCOUNT_BAR / PRESS_* / MARKETING_HEATMAP) present (-1.5)")
    scores["7_visual_and_chart_density"] = max(0.0, round(s7, 1))

    # 8. Pretendard Typography, Min 9pt Floor, Hyperlinks & QC (10 pts)
    s8 = 10.0
    if qc["overall_status"] != "PASS":
        s8 -= 4.0
        deductions.append(f"[Typography] QC status {qc['overall_status']} != PASS (-4.0)")

    pretendard_runs = 0
    sub_9pt_runs = 0
    hyperlink_count = 0
    cutoff_hits = 0

    for sl in list(prs.slides):
        for sh in sl.shapes:
            frames = []
            texts: list[str] = []
            if sh.has_table:
                for row in sh.table.rows:
                    for cell in row.cells:
                        frames.append(cell.text_frame)
                        texts.append(cell.text.strip())
            elif sh.has_text_frame:
                frames.append(sh.text_frame)
                texts.append(sh.text_frame.text.strip())

            for tf in frames:
                for p in tf.paragraphs:
                    p_name = p.font.name if p.font else None
                    p_size = p.font.size.pt if (p.font and p.font.size) else None
                    if p_name == "Pretendard":
                        pretendard_runs += 1
                    if p_size is not None and p_size < 8.95:
                        sub_9pt_runs += 1
                    for r in p.runs:
                        r_name = (r.font.name if r.font else None) or p_name
                        r_size = (r.font.size.pt if (r.font and r.font.size) else None) or p_size
                        if r_name == "Pretendard":
                            pretendard_runs += 1
                        if r_size is not None and r_size < 8.95:
                            sub_9pt_runs += 1
                        try:
                            addr = r.hyperlink.address if r.hyperlink else None
                            if addr and str(addr).startswith("http"):
                                hyperlink_count += 1
                        except Exception:
                            pass

            for t in texts:
                for line in t.splitlines():
                    ln = line.strip()
                    if len(ln) >= 35 and (ln.endswith("에서") or ln.endswith("으로") or ln.endswith("하는") or ln.endswith("며,") or ln.endswith("..")):
                        cutoff_hits += 1

    if pretendard_runs == 0:
        s8 -= 2.0
        deductions.append("[Typography] Pretendard font family not applied to PPTX text runs (-2.0)")
    if sub_9pt_runs > 0:
        pen = min(2.5, round(sub_9pt_runs * 0.15, 1))
        s8 -= pen
        deductions.append(f"[Typography] Detected {sub_9pt_runs} text runs smaller than 9pt floor (-{pen})")
    if hyperlink_count == 0 and true_urls:
        s8 -= 1.5
        deductions.append("[Typography] Zero clickable PPTX hyperlinks (run.hyperlink.address) despite collected source URLs (-1.5)")
    if cutoff_hits > 0:
        pen = min(2.0, round(cutoff_hits * 0.5, 1))
        s8 -= pen
        deductions.append(f"[Typography] Detected {cutoff_hits} abrupt mid-phrase cutoffs in PPTX (-{pen})")
    scores["8_typography_and_qc"] = max(0.0, round(s8, 1))

    total = round(sum(scores.values()), 1)
    return {
        "total_score": total,
        "max_score": 100.0,
        "dimension_scores": scores,
        "deductions": deductions,
        "meta": {
            "slides": len(slides),
            "pptx_slides": len(prs.slides),
            "pptx_pics": total_pics,
            "sources": len(sources),
            "news_articles": news_cnt,
            "unique_urls": len(true_urls),
            "pretendard_runs": pretendard_runs,
            "sub_9pt_runs": sub_9pt_runs,
            "pptx_hyperlinks": hyperlink_count,
            "qc": qc["overall_status"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Factbook output against 100-point Rubric v2.")
    parser.add_argument("--project-id", required=True, help="Target project UUID")
    parser.add_argument("--pptx", required=True, type=Path, help="Path to exported .pptx file")
    parser.add_argument("--api", default=API, help="Backend API v1 base URL (default: http://127.0.0.1:8000/api/v1)")
    args = parser.parse_args()
    result = evaluate(args.project_id, args.pptx, api_base=args.api)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
