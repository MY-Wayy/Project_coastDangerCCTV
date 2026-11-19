#!/usr/bin/env python3
"""Scenario ②: greedy placement of N new coastal CCTVs maximising (weighted) viewshed coverage of blind areas."""

from __future__ import annotations

import argparse
import heapq
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import rasterize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_viewshed import robust_buffer, viewshed  # noqa: E402
from site_exclusions import excluded_mask  # noqa: E402
from viewshed_sensitivity import VS_DIR, Context, fov_for, omni_cells, optimize_azimuths, sector  # noqa: E402


NEW_CAMERA = {"mount_height_m": 8.0, "fov_deg": 360.0, "view_range_m": 300.0}  # 신규 = 해안 감시용 PTZ
CANDIDATE_COAST_M = 60.0   # 해안선에서 이 거리 이내 육지 셀을 후보로
CANDIDATE_SPACING = 3      # DEM 3칸(90m) 간격으로 솎음
LAND_MIN_Z = 1.0
REPORT_N = [5, 10, 20, 30, 50, 100, 150, 200]


def baselines(ctx: Context) -> dict[str, np.ndarray]:
    """기존 CCTV 커버 셀. 보수적: 미상=고정60° + 방향 최적화(①) 적용 후 / 기존: 미상=360°."""
    omni = omni_cells(ctx, 0.0, ctx.params["view_range_m"])
    out = {}
    for name, unknown_fov in (("conservative_after_rotation", 60.0), ("original_360", None)):
        fovs = np.array([fov_for(r, unknown_fov) for r in omni.itertuples()])
        if unknown_fov is None:
            sets = [sector(r.cells, r.bearings, r.azimuth_coast, fovs[i]) for i, r in enumerate(omni.itertuples())]
        else:
            sets = optimize_azimuths(ctx, omni, fovs)
        covered = np.zeros(ctx.zone_grid.size, dtype=bool)
        for s in sets:
            covered[s] = True
        out[name] = covered
    return out


def candidate_sites(ctx: Context) -> gpd.GeoDataFrame:
    coast = gpd.read_file(
        Path(__file__).resolve().parents[1] / "outputs/cctv_reanalysis/coastal_safety_busan_cctv_updated.gpkg",
        layer="coastline_monitoring_segments_cctv_updated",
    ).to_crs("EPSG:5186")
    island = excluded_mask(coast)  # 섬(도서부) + 수동 제외 목록

    def band(lines) -> np.ndarray:
        return rasterize(
            [(robust_buffer(g, CANDIDATE_COAST_M), 1) for g in lines],
            out_shape=ctx.dem.shape, transform=ctx.transform, fill=0, dtype="uint8",
        ).astype(bool)

    # 섬·수동 제외 구간은 도보 접근·전원 공급이 어려워 설치 대상에서 뺀다: 설치 가능 띠에서 제외 구간 주변 띠를 뺀다
    coast_band = band(coast.geometry[~island]) & ~band(coast.geometry[island])
    rows, cols = np.indices(ctx.dem.shape)
    pick = (
        coast_band & (ctx.dem > LAND_MIN_Z)
        & (rows % CANDIDATE_SPACING == 0) & (cols % CANDIDATE_SPACING == 0)
    )
    r, c = np.nonzero(pick)
    x, y = ctx.transform * (c + 0.5, r + 0.5)
    return gpd.GeoDataFrame(
        {"candidate_id": [f"CAND_{i:05d}" for i in range(1, len(r) + 1)], "ground_z_m": ctx.dem[r, c]},
        geometry=gpd.points_from_xy(x, y), crs="EPSG:5186",
    )


def candidate_cells(ctx: Context, cands: gpd.GeoDataFrame) -> list[np.ndarray]:
    zone = ctx.zone_grid > 0
    out = []
    for p in cands.geometry:
        vis = viewshed(ctx.dem, ctx.transform, p.x, p.y, NEW_CAMERA["mount_height_m"],
                       ctx.params["target_height_m"], NEW_CAMERA["view_range_m"], 0.0, 360.0).ravel()
        out.append(np.flatnonzero(vis & zone))
    return out


def greedy(cells: list[np.ndarray], covered: np.ndarray, weight: np.ndarray, n: int) -> list[tuple[int, float]]:
    """Lazy greedy (submodular max coverage). 반환: (후보 index, 추가 가중 셀 수)."""
    covered = covered.copy()
    heap = [(-weight[c].sum(), i) for i, c in enumerate(cells)]
    heapq.heapify(heap)
    picks = []
    while heap and len(picks) < n:
        neg, i = heapq.heappop(heap)
        gain = weight[cells[i][~covered[cells[i]]]].sum()
        if heap and gain < -heap[0][0] - 1e-9:
            heapq.heappush(heap, (-gain, i))
            continue
        if gain <= 0:
            break
        covered[cells[i]] = True
        picks.append((i, float(gain)))
    return picks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument(
        "--weights", type=Path, default=None,
        help="segment_id,weight CSV (예: 트랙 A 위험등급). 없으면 면적 가중치 1",
    )
    args = parser.parse_args()
    start = time.perf_counter()

    ctx = Context()
    seg_ids = ctx.zone["segment_id"].to_numpy()
    seg_weight = np.ones(len(seg_ids))
    weight_label = "uniform"
    if args.weights:
        w = pd.read_csv(args.weights, encoding="utf-8-sig").set_index("segment_id")["weight"]
        seg_weight = pd.Series(seg_ids).map(w).fillna(0).to_numpy()
        weight_label = args.weights.stem
    cell_weight = np.concatenate([[0.0], seg_weight])[ctx.zone_grid]
    seg_total = np.bincount(ctx.zone_grid, minlength=len(seg_ids) + 1)[1:]  # 면적 0 구간은 사각 수에서 제외

    print("1/4 기존 CCTV 커버(기준선)")
    base = baselines(ctx)
    print("2/4 후보지 생성·가시영역 계산")
    cands = candidate_sites(ctx)
    cells = candidate_cells(ctx, cands)
    print(f"   후보 {len(cands):,}개 ({time.perf_counter() - start:.0f}s)")

    print("3/4 그리디 배치")
    curve_rows, site_tables = [], []
    total_w = cell_weight.sum()
    for base_name, covered in base.items():
        picks = greedy(cells, covered, cell_weight, args.n)
        cov = covered.copy()
        base_pct = covered.sum() / ctx.zone_cells * 100
        base_w = cell_weight[covered].sum()
        curve_rows.append({"baseline": base_name, "new_cameras": 0, "coverage_pct": round(base_pct, 2),
                           "weighted_coverage_pct": round(base_w / total_w * 100, 2), "added_ha": 0.0,
                           "zero_segments": int(((np.bincount(ctx.zone_grid[cov], minlength=len(seg_ids) + 1)[1:] == 0) & (seg_total > 0)).sum())})
        rows = []
        for rank, (i, gain) in enumerate(picks, start=1):
            new = cells[i][~cov[cells[i]]]
            cov[cells[i]] = True
            seg_hits = np.bincount(ctx.zone_grid[new], minlength=len(seg_ids) + 1)[1:]
            main_seg = int(seg_hits.argmax())
            rows.append({
                "baseline": base_name, "rank": rank, "candidate_id": cands.candidate_id.iloc[i],
                "added_ha": round(len(new) * ctx.cell_ha, 2), "added_weight": round(gain, 2),
                "main_segment_id": seg_ids[main_seg], "SGG_NAM": ctx.zone["SGG_NAM"].iloc[main_seg],
                "segments_touched": int((seg_hits > 0).sum()),
                "geometry": cands.geometry.iloc[i],
            })
            if rank in REPORT_N or rank == len(picks):
                seg_cov = np.bincount(ctx.zone_grid[cov], minlength=len(seg_ids) + 1)[1:]
                curve_rows.append({
                    "baseline": base_name, "new_cameras": rank,
                    "coverage_pct": round(cov.sum() / ctx.zone_cells * 100, 2),
                    "weighted_coverage_pct": round(cell_weight[cov].sum() / total_w * 100, 2),
                    "added_ha": round((cov.sum() - covered.sum()) * ctx.cell_ha, 1),
                    "zero_segments": int(((seg_cov == 0) & (seg_total > 0)).sum()),
                })
        site_tables.append(gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:5186"))

    print("4/4 저장")
    curve = pd.DataFrame(curve_rows).drop_duplicates(["baseline", "new_cameras"])
    curve.insert(0, "weights", weight_label)
    sites = pd.concat(site_tables, ignore_index=True)
    suffix = "" if weight_label == "uniform" else f"_{weight_label}"
    curve.to_csv(VS_DIR / f"new_sites_curve{suffix}.csv", index=False, encoding="utf-8-sig")
    sites.drop(columns="geometry").assign(x_5186=sites.geometry.x.round(1), y_5186=sites.geometry.y.round(1)) \
        .to_csv(VS_DIR / f"new_sites_ranked{suffix}.csv", index=False, encoding="utf-8-sig")
    gpkg = VS_DIR / "viewshed_results.gpkg"
    cands.to_file(gpkg, layer="new_site_candidates", driver="GPKG")
    sites.to_file(gpkg, layer=f"new_sites_ranked{suffix}", driver="GPKG")

    by_district = (
        sites[sites["rank"] <= 50].groupby(["baseline", "SGG_NAM"]).size().unstack(0).fillna(0).astype(int)
    )
    by_district.to_csv(VS_DIR / f"new_sites_top50_by_district{suffix}.csv", encoding="utf-8-sig")

    print(curve.to_string(index=False))
    print(by_district.to_string())
    print(f"total {time.perf_counter() - start:.0f}s")


if __name__ == "__main__":
    main()
