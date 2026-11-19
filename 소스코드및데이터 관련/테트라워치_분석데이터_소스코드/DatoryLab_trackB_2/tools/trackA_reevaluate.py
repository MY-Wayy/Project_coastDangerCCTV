#!/usr/bin/env python3
"""Re-evaluate Track A CCTV install candidates against integrated CCTV + viewshed coverage, and export risk weights."""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from viewshed_new_sites import baselines  # noqa: E402
from viewshed_sensitivity import Context  # noqa: E402


PROJECT = Path(__file__).resolve().parents[1]
CANDIDATES = PROJECT / "data" / "raw" / "trackA" / "5_CCTV설치후보.csv"
OUT_DIR = PROJECT / "outputs" / "trackA"
CLASS_BINS = [-0.1, 0, 50, 100]
CLASS_LABELS = ["실제 사각(0%)", "부분 커버(0–50%)", "이미 커버(50% 이상)"]
NO_AREA = "면적 없음(짧은 구간)"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cand = pd.read_csv(CANDIDATES, encoding="utf-8-sig")

    seg = gpd.read_file(
        PROJECT / "outputs/cctv_reanalysis/coastal_safety_busan_cctv_updated.gpkg",
        layer="coastline_monitoring_segments_cctv_updated",
    )[["segment_id", "nearest_cctv_all_m", "cctv_all_count_500m", "cctv_all_gap_500m"]]

    # 구간별 지형 반영 커버율: 기존 가정(미상=360°) / 보수적(미상=고정60°+방향 최적화)
    ctx = Context()
    base = baselines(ctx)
    n_seg = len(ctx.zone)
    zone_cells = np.bincount(ctx.zone_grid, minlength=n_seg + 1)[1:]
    cov = pd.DataFrame({"segment_id": ctx.zone["segment_id"].to_numpy(), "zone_ha": zone_cells * ctx.cell_ha})
    for name, covered in base.items():
        cells = np.bincount(ctx.zone_grid[covered], minlength=n_seg + 1)[1:]
        with np.errstate(invalid="ignore", divide="ignore"):
            cov[f"view_pct_{name}"] = np.where(zone_cells > 0, cells / zone_cells * 100, np.nan).round(1)

    out = cand.merge(seg, on="segment_id", how="left").merge(cov, on="segment_id", how="left")
    out = out.rename(columns={"nearest_cctv_m": "nearest_traffic_cctv_m", "cctv_gap_500m": "traffic_gap_500m"})
    for name in base:
        # 대상구역이 30m 격자에 잡히지 않는 짧은 구간(면적 0)은 사각으로 세지 않는다
        out[f"class_{name}"] = (
            pd.cut(out[f"view_pct_{name}"], CLASS_BINS, labels=CLASS_LABELS)
            .cat.add_categories(NO_AREA).fillna(NO_AREA)
        )
    out.to_csv(OUT_DIR / "trackA_candidates_reevaluated.csv", index=False, encoding="utf-8-sig")

    # 위험 가중치: 후보 구간 = 위험지수, 그 외 0 (트랙 A 전체 1,832구간 등급을 받으면 교체)
    out[["segment_id", "위험지수"]].rename(columns={"위험지수": "weight"}).to_csv(
        OUT_DIR / "risk_weights_trackA.csv", index=False, encoding="utf-8-sig"
    )

    print(f"후보 {len(out)}구간, 위험지수 = sqrt(T×W) 확인:",
          round(float((np.sqrt(out['T_유형위험'] * out['W_파랑노출']) - out['위험지수']).abs().max()), 3))
    print(f"통합 CCTV 500m 이내 없음: {int(out['cctv_all_gap_500m'].sum())} / {len(out)}")
    for name in base:
        print(f"\n[{name}]")
        print(out[f"class_{name}"].value_counts().reindex(CLASS_LABELS + [NO_AREA]).to_string())
        print(pd.crosstab(out["구"], out[f"class_{name}"]).reindex(columns=CLASS_LABELS + [NO_AREA], fill_value=0).to_string())


if __name__ == "__main__":
    main()
