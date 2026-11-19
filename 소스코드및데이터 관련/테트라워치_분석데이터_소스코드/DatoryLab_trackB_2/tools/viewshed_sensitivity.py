#!/usr/bin/env python3
"""Sensitivity of coastal CCTV viewshed coverage to FOV / azimuth / height / range assumptions."""

from __future__ import annotations

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


PROJECT = Path(__file__).resolve().parents[1]
VS_DIR = PROJECT / "outputs" / "viewshed"
DEM_PATH = PROJECT / "data/raw/dem/busan_copernicus_dsm30_5186.tif"
RANDOM_SEEDS = 30
AZIMUTH_STEP = 15.0  # 최적화 시 탐색 간격


class Context:
    def __init__(self) -> None:
        self.params = json.loads((VS_DIR / "viewshed_params.json").read_text(encoding="utf-8"))
        self.observers = gpd.read_file(VS_DIR / "viewshed_inputs.gpkg", layer="observers")
        zone = gpd.read_file(VS_DIR / "viewshed_inputs.gpkg", layer="target_zone")
        with rasterio.open(DEM_PATH) as src:
            dem = src.read(1)
            self.dem = np.where(dem == src.nodata, 0.0, dem).astype("float32")
            self.transform = src.transform
        self.zone = zone
        # 셀별 최근접 구간 번호 (prepare_viewshed.py가 저장)
        with rasterio.open(VS_DIR / "target_zone_index.tif") as src:
            self.zone_grid = src.read(1).ravel()
        self.zone_cells = int((self.zone_grid > 0).sum())
        self.cell_ha = self.transform.a * -self.transform.e / 1e4


def omni_cells(ctx: Context, height_offset: float, view_range: float) -> pd.DataFrame:
    """관측점별 360° 가시 '대상구역' 셀 인덱스와 방위각. 부채꼴 가시 = 360° 가시 ∩ 부채꼴."""
    obs = ctx.observers[ctx.observers["coast_distance_m"] <= view_range + ctx.params["target_zone_m"]]
    rows = []
    for _, o in obs.iterrows():
        vis = viewshed(ctx.dem, ctx.transform, o.geometry.x, o.geometry.y,
                       o.mount_height_m + height_offset, ctx.params["target_height_m"],
                       view_range, 0.0, 360.0).ravel()
        flat = np.flatnonzero(vis & (ctx.zone_grid > 0))
        r, c = np.divmod(flat, ctx.dem.shape[1])
        cx, cy = ctx.transform * (c + 0.5, r + 0.5)
        bearing = (np.degrees(np.arctan2(cx - o.geometry.x, cy - o.geometry.y)) + 360.0) % 360.0
        rows.append({
            "integrated_id": o.integrated_id, "view_type": o.view_type, "fov_deg": o.fov_deg,
            "fov_assumed": o.fov_assumed, "azimuth_coast": o.azimuth_deg, "SGG_NAM": None,
            "cells": flat, "bearings": bearing,
        })
    return pd.DataFrame(rows)


def sector(cells: np.ndarray, bearings: np.ndarray, azimuth: float, fov: float) -> np.ndarray:
    if fov <= 0:
        return cells[:0]
    if fov >= 360:
        return cells
    diff = np.abs((bearings - azimuth + 180.0) % 360.0 - 180.0)
    return cells[diff <= fov / 2.0]


def coverage(ctx: Context, cell_sets: list[np.ndarray]) -> dict:
    covered = np.zeros(ctx.zone_grid.size, dtype=bool)
    for cells in cell_sets:
        covered[cells] = True
    seg_cov = np.bincount(ctx.zone_grid[covered], minlength=len(ctx.zone) + 1)[1:]
    seg_total = np.bincount(ctx.zone_grid, minlength=len(ctx.zone) + 1)[1:]
    return {
        "coverage_pct": round(covered.sum() / ctx.zone_cells * 100, 2),
        "covered_ha": round(covered.sum() * ctx.cell_ha, 1),
        "zero_segments": int(((seg_cov == 0) & (seg_total > 0)).sum()),  # 면적 0 구간 제외
        "_covered": covered,
    }


def fov_for(row: pd.Series, unknown_fov: float | None) -> float:
    """3분류 제외 그룹(fov_deg <= 0)은 항상 0 유지. unknown_fov 지정 시 미상 화각 대체."""
    if row.fov_deg <= 0:
        return 0.0
    if row.view_type == "unknown" and unknown_fov is not None:
        return unknown_fov
    return row.fov_deg


def optimize_azimuths(ctx: Context, omni: pd.DataFrame, fovs: np.ndarray) -> list[np.ndarray]:
    """고정형 방위각을 15° 간격으로 탐색해 대상구역 신규 커버를 최대화(그리디 2회 반복)."""
    candidates = np.arange(0.0, 360.0, AZIMUTH_STEP)
    chosen = [None] * len(omni)
    fixed = [i for i in range(len(omni)) if 0 < fovs[i] < 360]
    base = [omni.cells.iloc[i] for i in range(len(omni)) if fovs[i] >= 360]
    order = sorted(fixed, key=lambda i: -len(omni.cells.iloc[i]))
    for _ in range(2):
        covered = coverage(ctx, base + [chosen[j] for j in fixed if chosen[j] is not None])["_covered"]
        for i in order:
            if chosen[i] is not None:
                covered[chosen[i]] = False  # 자기 자신 기여 제거 후 재선택(겹침은 근사)
            cells, bearings = omni.cells.iloc[i], omni.bearings.iloc[i]
            best = max(
                (sector(cells, bearings, a, fovs[i]) for a in candidates),
                key=lambda s: int((~covered[s]).sum()),
            )
            chosen[i] = best
            covered[best] = True
    return base + [chosen[i] for i in fixed]


def fov_scenarios(ctx: Context, omni: pd.DataFrame) -> pd.DataFrame:
    results = []
    rng_master = np.random.default_rng(42)
    for unknown_label, unknown_fov in (("3분류기본(미상=고정60°)", None), ("미상=고정60°", 60.0), ("미상=고정90°", 90.0)):
        fovs = np.array([fov_for(r, unknown_fov) for r in omni.itertuples()])

        def run(az_fn) -> dict:
            sets = [sector(r.cells, r.bearings, az_fn(i, r), fovs[i]) for i, r in enumerate(omni.itertuples())]
            return coverage(ctx, sets)

        toward = run(lambda i, r: r.azimuth_coast)
        away = run(lambda i, r: (r.azimuth_coast + 180.0) % 360.0)
        randoms = []
        for _ in range(RANDOM_SEEDS):
            az = rng_master.uniform(0, 360, len(omni))
            randoms.append(run(lambda i, r: az[i]))
        optimized = coverage(ctx, optimize_azimuths(ctx, omni, fovs))
        rand_pct = np.array([r["coverage_pct"] for r in randoms])
        rand_zero = np.array([r["zero_segments"] for r in randoms])
        results.append({
            "unknown_fov": unknown_label,
            "fixed_cameras": int(((fovs > 0) & (fovs < 360)).sum()),
            "away_from_coast_pct": away["coverage_pct"],
            "random_mean_pct": round(rand_pct.mean(), 2),
            "random_min_pct": round(rand_pct.min(), 2),
            "random_max_pct": round(rand_pct.max(), 2),
            "toward_coast_pct": toward["coverage_pct"],
            "optimized_pct": optimized["coverage_pct"],
            "gain_from_random_pp": round(optimized["coverage_pct"] - rand_pct.mean(), 2),
            "gain_from_away_pp": round(optimized["coverage_pct"] - away["coverage_pct"], 2),
            "zero_segments_random_mean": round(rand_zero.mean(), 1),
            "zero_segments_optimized": optimized["zero_segments"],
        })
        print(f"  {unknown_label}: done")
    return pd.DataFrame(results)


def physical_scenarios(ctx: Context) -> pd.DataFrame:
    """설치 높이·가시거리 one-at-a-time (방위각·화각은 기존 가정)."""
    settings = [
        ("기준 (6/8m, 300m)", 0.0, 300.0),
        ("높이 -2m (4/6m)", -2.0, 300.0),
        ("높이 +2m (8/10m)", 2.0, 300.0),
        ("가시거리 200m", 0.0, 200.0),
        ("가시거리 500m", 0.0, 500.0),
    ]
    rows = []
    for label, dh, rng in settings:
        omni = omni_cells(ctx, dh, rng)
        sets = [sector(r.cells, r.bearings, r.azimuth_coast, r.fov_deg) for r in omni.itertuples()]
        res = coverage(ctx, sets)
        rows.append({"scenario": label, "observers": len(omni),
                     "coverage_pct": res["coverage_pct"], "covered_ha": res["covered_ha"],
                     "zero_segments": res["zero_segments"]})
        print(f"  {label}: {res['coverage_pct']}%")
    return pd.DataFrame(rows)


def main() -> None:
    start = time.perf_counter()
    ctx = Context()
    print("1/3 기준 가시 셀 계산")
    omni = omni_cells(ctx, 0.0, ctx.params["view_range_m"])
    print("2/3 화각·방위각 시나리오")
    fov_table = fov_scenarios(ctx, omni)
    print("3/3 높이·가시거리 시나리오")
    phys_table = physical_scenarios(ctx)

    fov_table.to_csv(VS_DIR / "sensitivity_fov_azimuth.csv", index=False, encoding="utf-8-sig")
    phys_table.to_csv(VS_DIR / "sensitivity_height_range.csv", index=False, encoding="utf-8-sig")
    print(fov_table.to_string(index=False))
    print(phys_table.to_string(index=False))
    print(f"total {time.perf_counter() - start:.0f}s")


if __name__ == "__main__":
    main()
