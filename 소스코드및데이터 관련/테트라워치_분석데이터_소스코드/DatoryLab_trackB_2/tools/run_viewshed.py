#!/usr/bin/env python3
"""Run terrain viewshed for all coastal CCTV observers and summarise coverage per coastline segment."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_viewshed import viewshed  # noqa: E402


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    vs_dir = project_root / "outputs" / "viewshed"
    parser = argparse.ArgumentParser()
    parser.add_argument("--dem", type=Path, default=project_root / "data/raw/dem/busan_copernicus_dsm30_5186.tif")
    args = parser.parse_args()

    params = json.loads((vs_dir / "viewshed_params.json").read_text(encoding="utf-8"))
    observers = gpd.read_file(vs_dir / "viewshed_inputs.gpkg", layer="observers")
    zone = gpd.read_file(vs_dir / "viewshed_inputs.gpkg", layer="target_zone")
    observers = observers[observers["can_reach_zone"]].reset_index(drop=True)

    with rasterio.open(args.dem) as src:
        dem = src.read(1)
        dem = np.where(dem == src.nodata, 0.0, dem).astype("float32")
        transform, profile = src.transform, src.profile
    cell_ha = transform.a * -transform.e / 1e4

    # 구간 ID 격자: 셀마다 가장 가까운 구간 (prepare_viewshed.py가 저장)
    zone["zone_idx"] = np.arange(1, len(zone) + 1)
    with rasterio.open(vs_dir / "target_zone_index.tif") as src:
        zone_grid = src.read(1)

    # current: 가정 방위각+화각 / omni: 같은 위치에서 360° (방향 조정만으로 얻을 수 있는 상한)
    count_current = np.zeros(dem.shape, dtype="uint16")
    count_omni = np.zeros(dem.shape, dtype="uint16")
    per_obs = []
    start = time.perf_counter()
    for i, o in observers.iterrows():
        common = (dem, transform, o.geometry.x, o.geometry.y, o.mount_height_m,
                  params["target_height_m"], o.view_range_m)
        omni = viewshed(*common, 0.0, 360.0)
        current = omni if o.fov_deg >= 360 else viewshed(*common, o.azimuth_deg, o.fov_deg)
        count_current += current
        count_omni += omni
        per_obs.append({
            "integrated_id": o.integrated_id,
            "visible_ha_current": round(current.sum() * cell_ha, 3),
            "visible_zone_ha_current": round((current & (zone_grid > 0)).sum() * cell_ha, 3),
            "visible_zone_ha_omni": round((omni & (zone_grid > 0)).sum() * cell_ha, 3),
        })
        if (i + 1) % 300 == 0:
            print(f"  {i + 1:,}/{len(observers):,} ({time.perf_counter() - start:.0f}s)")

    out_profile = {**profile, "dtype": "uint16", "nodata": 0, "compress": "deflate"}
    for name, grid in (("current", count_current), ("omni", count_omni)):
        with rasterio.open(vs_dir / f"viewshed_count_{name}.tif", "w", **out_profile) as dst:
            dst.write(grid, 1)

    obs_table = observers.drop(columns="geometry").merge(pd.DataFrame(per_obs), on="integrated_id")
    obs_table.to_csv(vs_dir / "viewshed_by_observer.csv", index=False, encoding="utf-8-sig")

    # 구간별 집계
    idx = zone_grid.ravel()
    in_zone = idx > 0
    def area_by_zone(mask: np.ndarray) -> np.ndarray:
        return np.bincount(idx[in_zone], weights=mask.ravel()[in_zone], minlength=len(zone) + 1)[1:] * cell_ha
    zone_ha = area_by_zone(np.ones(dem.shape, dtype=bool))
    seg = zone[["segment_id", "SGG_NAM", "zone_idx", "geometry"]].copy()
    seg["zone_ha"] = zone_ha.round(3)
    seg["covered_ha_current"] = area_by_zone(count_current > 0).round(3)
    seg["covered_ha_omni"] = area_by_zone(count_omni > 0).round(3)
    seg["blind_ha_current"] = (seg["zone_ha"] - seg["covered_ha_current"]).round(3)
    with np.errstate(invalid="ignore", divide="ignore"):
        seg["coverage_pct_current"] = (seg["covered_ha_current"] / seg["zone_ha"] * 100).round(1)
        seg["coverage_pct_omni"] = (seg["covered_ha_omni"] / seg["zone_ha"] * 100).round(1)
    seg = seg.drop(columns="zone_idx")

    seg.to_file(vs_dir / "viewshed_results.gpkg", layer="segment_coverage", driver="GPKG")
    seg.drop(columns="geometry").to_csv(vs_dir / "viewshed_by_segment.csv", index=False, encoding="utf-8-sig")

    district = seg.groupby("SGG_NAM").agg(
        segments=("segment_id", "size"),
        zone_ha=("zone_ha", "sum"),
        covered_ha_current=("covered_ha_current", "sum"),
        covered_ha_omni=("covered_ha_omni", "sum"),
    )
    total = district.sum().to_frame("부산 전체").T
    district = pd.concat([district, total])
    district["coverage_pct_current"] = (district["covered_ha_current"] / district["zone_ha"] * 100).round(1)
    district["coverage_pct_omni"] = (district["covered_ha_omni"] / district["zone_ha"] * 100).round(1)
    district["rotate_gain_pp"] = (district["coverage_pct_omni"] - district["coverage_pct_current"]).round(1)
    district = district.round(1)
    district.to_csv(vs_dir / "viewshed_by_district.csv", encoding="utf-8-sig")

    print(f"done {len(observers):,} observers in {time.perf_counter() - start:.0f}s")
    print(district.to_string())
    zero = ((seg["covered_ha_current"] == 0) & (seg["zone_ha"] > 0)).sum()
    print(f"segments with zero visible area (current, area>0): {zero:,} / {int((seg['zone_ha'] > 0).sum()):,} (zero-area {int((seg['zone_ha'] == 0).sum())})")


if __name__ == "__main__":
    main()
