#!/usr/bin/env python3
"""Export one shareable per-segment CSV combining radius coverage, viewshed coverage, Track A risk and new-site plans."""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from viewshed_new_sites import baselines, candidate_cells, candidate_sites  # noqa: E402
from viewshed_sensitivity import VS_DIR, Context  # noqa: E402


PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "outputs" / "segment_results_busan.csv"
TOP_N = 50
BASELINE = "conservative_after_rotation"
PLANS = {
    "균등50": VS_DIR / "new_sites_ranked.csv",
    "위험50": VS_DIR / "new_sites_ranked_trackB_weights.csv",  # 트랙 D 가중치(위험지수, 섬 0)
}


def seg_pct(ctx: Context, covered: np.ndarray, zone_cells: np.ndarray) -> np.ndarray:
    cells = np.bincount(ctx.zone_grid[covered], minlength=len(ctx.zone) + 1)[1:]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(zone_cells > 0, cells / zone_cells * 100, np.nan).round(1)


def main() -> None:
    ctx = Context()
    zone_cells = np.bincount(ctx.zone_grid, minlength=len(ctx.zone) + 1)[1:]
    base = baselines(ctx)
    cands = candidate_sites(ctx)
    cells = candidate_cells(ctx, cands)
    index = {cid: i for i, cid in enumerate(cands["candidate_id"])}

    out = pd.DataFrame({
        "segment_id": ctx.zone["segment_id"].to_numpy(),
        "구군": ctx.zone["SGG_NAM"].str.replace("부산광역시 ", "", regex=False).to_numpy(),
        "대상구역_ha": (zone_cells * ctx.cell_ha).round(2),
        "가시커버율_기존가정_pct": seg_pct(ctx, base["original_360"], zone_cells),
        "가시커버율_보수적_pct": seg_pct(ctx, base[BASELINE], zone_cells),
    })
    out["사각면적_보수적_ha"] = (out["대상구역_ha"] * (1 - out["가시커버율_보수적_pct"].fillna(0) / 100)).round(2)
    for plan, path in PLANS.items():
        ranked = pd.read_csv(path, encoding="utf-8-sig")
        ranked = ranked[(ranked["baseline"] == BASELINE) & (ranked["rank"] <= TOP_N)]
        covered = base[BASELINE].copy()
        for cid in ranked["candidate_id"]:
            covered[cells[index[cid]]] = True
        out[f"가시커버율_{plan}배치후_pct"] = seg_pct(ctx, covered, zone_cells)
        counts = ranked.groupby("main_segment_id").size()
        out[f"{plan}_신규설치수"] = out["segment_id"].map(counts).fillna(0).astype(int)

    seg = gpd.read_file(
        PROJECT / "outputs/cctv_reanalysis/coastal_safety_busan_cctv_updated.gpkg",
        layer="coastline_monitoring_segments_cctv_updated",
    )
    radius = seg[["segment_id", "segment_length_m", "CAT_COA", "nearest_cctv_m", "cctv_gap_500m",
                  "nearest_cctv_all_m", "cctv_all_count_500m", "cctv_all_gap_500m"]].rename(columns={
        "segment_length_m": "구간길이_m",
        "nearest_cctv_m": "최근접CCTV_교통만_m",
        "cctv_gap_500m": "공백500m_교통만",
        "nearest_cctv_all_m": "최근접CCTV_통합_m",
        "cctv_all_count_500m": "CCTV수500m_통합",
        "cctv_all_gap_500m": "공백500m_통합",
    })
    trackA = pd.read_csv(PROJECT / "outputs/trackA/trackA_candidates_reevaluated.csv", encoding="utf-8-sig")
    trackA = trackA[["segment_id", "해안유형", "노출그룹", "배정관측소", "위험지수", "위험등급",
                     f"class_{BASELINE}"]].rename(columns={f"class_{BASELINE}": "TrackA후보_재분류"})
    trackA.insert(1, "TrackA후보", True)

    result = (
        out.merge(radius, on="segment_id", how="left")
        .merge(trackA, on="segment_id", how="left")
    )
    result["TrackA후보"] = result["TrackA후보"].eq(True)
    front = ["segment_id", "구군", "구간길이_m", "CAT_COA"]
    result = result[front + [c for c in result.columns if c not in front]].sort_values("segment_id")
    result.to_csv(OUT, index=False, encoding="utf-8-sig")

    # 트랙 D 입력용 영문판: CCTV 3개 컬럼은 예전 이름 그대로, 값은 통합 기준
    english = {
        "segment_id": "segment_id",
        "최근접CCTV_통합_m": "nearest_cctv_m", "CCTV수500m_통합": "cctv_count_500m", "공백500m_통합": "cctv_gap_500m",
        "대상구역_ha": "view_zone_ha",
        "가시커버율_기존가정_pct": "view_coverage_pct_original",
        "가시커버율_보수적_pct": "view_coverage_pct_conservative",
        "사각면적_보수적_ha": "view_blind_ha_conservative",
        "가시커버율_균등50배치후_pct": "view_coverage_pct_after_uniform50", "균등50_신규설치수": "new_sites_uniform50",
        "가시커버율_위험50배치후_pct": "view_coverage_pct_after_risk50", "위험50_신규설치수": "new_sites_risk50",
        "최근접CCTV_교통만_m": "nearest_cctv_traffic_only_m", "공백500m_교통만": "cctv_gap_500m_traffic_only",
    }
    result[list(english)].rename(columns=english).to_csv(
        OUT.with_name("input_trackB_segments.csv"), index=False, encoding="utf-8-sig"
    )

    print(f"saved {OUT} ({len(result):,} rows, {len(result.columns)} cols)")
    print(result.head(3).T.to_string())


if __name__ == "__main__":
    main()
