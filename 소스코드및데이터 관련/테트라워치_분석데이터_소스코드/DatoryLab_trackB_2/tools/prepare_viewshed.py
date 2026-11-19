#!/usr/bin/env python3
"""Prepare viewshed inputs (observers, target zone) for Busan coastal CCTV and run a smoke test."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
import shapely
from shapely.geometry import LineString, Point
from shapely.ops import unary_union


CRS_ANALYSIS = "EPSG:5186"

# 가정값: 원본에 설치 높이·방위각이 없으므로 명시적으로 고정하고 결과에 기록한다
PARAMS = {
    "coast_search_m": 1000.0,      # 해안선에서 이 거리 이내 CCTV만 관측점으로 사용
    "mount_height_m": 6.0,         # 일반 지주형
    "mount_height_traffic_m": 8.0, # 교통·ITS(교차로 F형 지주)
    "target_height_m": 1.6,        # 사람 눈높이 표적
    "view_range_m": 300.0,         # 사람 식별 가능 거리
    "default_fov_deg": 360.0,      # 화각 미상 → PTZ 가정
    "fixed_unknown_fov_deg": 60.0, # '고정'인데 각도 미기재
    "target_zone_m": 100.0,        # 해안선 양쪽 분석 대상 폭
}


def robust_buffer(geom, distance: float):
    """Flat-cap, round-join line buffer built from straight pieces.

    GEOS 3.11's buffer shrinks the polygon of short, wiggly coastline segments
    (checked against this construction: ~4% mean area error locally, none in
    newer GEOS). Buffering each straight piece and adding vertex discs gives
    the same exact shape on every GEOS version.
    """
    lines = [geom] if geom.geom_type == "LineString" else list(getattr(geom, "geoms", []))
    parts = []
    for line in lines:
        coords = [c for i, c in enumerate(line.coords) if i == 0 or c != line.coords[i - 1]]
        if len(coords) < 2:
            continue
        parts += [LineString(coords[i:i + 2]).buffer(distance, cap_style="flat") for i in range(len(coords) - 1)]
        parts += [Point(c).buffer(distance) for c in coords[1:-1]]
    return unary_union(parts) if parts else geom.buffer(distance, cap_style="flat")


ZONE_INDEX_FILE = "target_zone_index.tif"


def nearest_segment_grid(zone_mask: np.ndarray, lines, transform) -> np.ndarray:
    """대상구역 격자마다 가장 가까운 해안 구간 번호(1부터, target_zone 레이어 순서). 구역 밖은 0.

    인접 구간 버퍼가 겹치는 셀을 '나중에 그린 구간'이 가져가면 짧은 구간이 면적을 잃으므로
    셀 중심에서 가장 가까운 구간에 배정한다.
    """
    rows, cols = np.nonzero(zone_mask)
    xs, ys = transform * (cols + 0.5, rows + 0.5)
    tree = shapely.STRtree(np.asarray(lines))
    nearest = tree.nearest(shapely.points(xs, ys))
    grid = np.zeros(zone_mask.shape, dtype="int32")
    grid[rows, cols] = nearest + 1
    return grid


def observer_table(
    sites: pd.DataFrame,
    coast: gpd.GeoDataFrame,
    dem: rasterio.io.DatasetReader,
    dem_arr: np.ndarray | None = None,
    transform=None,
    zone_mask: np.ndarray | None = None,
) -> gpd.GeoDataFrame:
    points = gpd.GeoDataFrame(
        sites, geometry=gpd.points_from_xy(sites.lon, sites.lat), crs="EPSG:4326"
    ).to_crs(CRS_ANALYSIS)

    coast_union = coast.geometry.union_all()
    points["coast_distance_m"] = points.geometry.distance(coast_union)
    obs = points[points["coast_distance_m"] <= PARAMS["coast_search_m"]].copy()

    # 각 관측점에서 가장 가까운 해안선 지점 방위각 계산
    nearest = obs.geometry.apply(lambda p: coast_union.interpolate(coast_union.project(p)))
    dx = nearest.x.values - obs.geometry.x.values
    dy = nearest.y.values - obs.geometry.y.values
    obs["nearest_coast_azimuth_deg"] = (np.degrees(np.arctan2(dx, dy)) + 360.0) % 360.0

    is_traffic = obs["purpose_std"].fillna("").str.contains("traffic|enforcement")
    obs["mount_height_m"] = np.where(
        is_traffic, PARAMS["mount_height_traffic_m"], PARAMS["mount_height_m"]
    )
    obs["fov_assumed"] = obs["fov_deg_max"].isna()
    obs["view_range_m"] = PARAMS["view_range_m"]
    # 가시거리+대상폭보다 멀면 현재 가정으로는 대상 구역에 닿을 수 없음
    obs["can_reach_zone"] = obs["coast_distance_m"] <= PARAMS["view_range_m"] + PARAMS["target_zone_m"]

    xs, ys = obs.geometry.x.values, obs.geometry.y.values
    obs["ground_z_m"] = [v[0] for v in dem.sample(zip(xs, ys))]
    obs["x_5186"], obs["y_5186"] = xs.round(2), ys.round(2)

    # [기존 1,782개 해안 관측 CCTV 3분류 기준 적용]
    # 모든 CCTV가 가장 가까운 해안선을 정면 직시한다는 일괄 가정을 해제하고,
    # 3D 지형 차폐 여부·화각(PTZ)·설치 목적·해안선 거리에 따라 3그룹(6세부유형)으로 차등 설정
    non_ocean_purposes = {"어린이보호", "생활방범|어린이보호", "교통단속", "교통단속|생활방범"}
    az_list, fov_list, src_list, grp_list, dtl_list = [], [], [], [], []

    for _, o in obs.iterrows():
        c_az = float(o["nearest_coast_azimuth_deg"])
        p = str(o.get("purpose_original") or "").strip()
        vt = str(o.get("view_type") or "").strip()
        d = float(o["coast_distance_m"])
        f_max = o.get("fov_deg_max")
        known_fixed_fov = float(f_max) if (pd.notna(f_max) and float(f_max) < 360.0) else PARAMS["fixed_unknown_fov_deg"]

        if not bool(o["can_reach_zone"]):
            az_list.append(c_az)
            fov_list.append(0.0)
            src_list.append("out_of_reach_gt400m")
            grp_list.append("범위외(>400m)")
            dtl_list.append("범위외(>400m)")
            continue

        # 3D 지형 완전 차폐 여부 확인 (360° 전방위 시선에서 해안 대상구역 가시 셀 존재 여부)
        omni_blocked = False
        if dem_arr is not None and transform is not None and zone_mask is not None:
            vis_omni = viewshed(
                dem_arr, transform, o.geometry.x, o.geometry.y,
                float(o["mount_height_m"]), PARAMS["target_height_m"], float(o["view_range_m"]),
                0.0, 360.0
            )
            omni_blocked = int((vis_omni & (zone_mask > 0)).sum()) == 0

        if omni_blocked:
            # 🔴 그룹 3-1: 3D 지형 완전 차폐 (124곳, 7.0%) -> 0%
            az_list.append((c_az + 180.0) % 360.0)
            fov_list.append(0.0)
            src_list.append("group3_terrain_blocked_0pct")
            grp_list.append("🔴 3. 전혀 보고 있지 않음")
            dtl_list.append("3-1. 3D 지형 완전 차폐 (omni == 0ha)")
        elif p in non_ocean_purposes:
            # 🔴 그룹 3-2: 어린이보호(스쿨존) 및 교통단속(차선·번호판 전용) (126곳, 7.1%) -> 완전 제외(0%)
            az_list.append((c_az + 180.0) % 360.0)
            fov_list.append(0.0)
            src_list.append("group3_non_ocean_purpose_0pct")
            grp_list.append("🔴 3. 전혀 보고 있지 않음")
            dtl_list.append("3-2. 어린이보호(스쿨존)·교통단속(차선 전용)")
        elif vt == "ptz_360":
            # 🟢 그룹 1-1: 지형 가시 + 360° 회전형(ptz_360) (516곳, 29.0%) -> 360° 전방위 100% 반영
            az_list.append(c_az)
            fov_list.append(360.0)
            src_list.append("group1_ptz_360_full")
            grp_list.append("🟢 1. 해양을 확실히 봄")
            dtl_list.append("1-1. 지형 가시 + 360° 회전형(ptz_360)")
        elif ("재난재해" in p) or ("시설물관리" in p):
            # 🟢 그룹 1-2: 지형 가시 + 재난재해·시설물관리 목적 (149곳, 8.4%) -> 해안 방향 직시 100% 반영
            az_list.append(c_az)
            fov_list.append(known_fixed_fov)
            src_list.append("group1_disaster_facility_direct")
            grp_list.append("🟢 1. 해양을 확실히 봄")
            dtl_list.append("1-2. 지형 가시 + 재난재해·시설물관리 목적")
        elif d <= 50.0:
            # 🟡 그룹 2-1: 지형 가시 + 해안 50m 이내 초근접 (137곳, 7.7%) -> 고정60° 해안방향 반영
            az_list.append(c_az)
            fov_list.append(known_fixed_fov)
            src_list.append("group2_near50m_direct_60deg")
            grp_list.append("🟡 2. 어느 정도(조건부) 봄")
            dtl_list.append("2-1. 지형 가시 + 해안 50m 이내 초근접")
        else:
            # 🟡 그룹 2-2: 지형 가시 + 해안 50~400m 내륙 (730곳, 41.0%) -> 해안 직시 해제(비스듬한 60° 부분 반영)
            az_list.append((c_az + 60.0) % 360.0)
            fov_list.append(known_fixed_fov)
            src_list.append("group2_inland_oblique_60deg")
            grp_list.append("🟡 2. 어느 정도(조건부) 봄")
            dtl_list.append("2-2. 지형 가시 + 해안 50~400m 거리(방향 미상)")

    obs["azimuth_deg"] = az_list
    obs["fov_deg"] = fov_list
    obs["azimuth_source"] = src_list
    obs["ocean_view_group"] = grp_list
    obs["ocean_view_detail"] = dtl_list
    return obs


def viewshed(dem: np.ndarray, transform, x: float, y: float, eye_h: float, target_h: float,
             max_range: float, azimuth: float, fov: float) -> np.ndarray:
    """Boolean visibility grid (same shape as dem) via per-cell line-of-sight ray sampling."""
    if fov <= 0:
        return np.zeros(dem.shape, dtype=bool)
    res = transform.a
    col0, row0 = ~transform * (x, y)
    r = int(np.ceil(max_range / res))
    rows = np.arange(int(row0) - r, int(row0) + r + 1)
    cols = np.arange(int(col0) - r, int(col0) + r + 1)
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    inside = (rr >= 0) & (rr < dem.shape[0]) & (cc >= 0) & (cc < dem.shape[1])

    cx, cy = transform * (cc + 0.5, rr + 0.5)
    dx, dy = cx - x, cy - y
    dist = np.hypot(dx, dy)
    cand = inside & (dist <= max_range) & (dist > 0)
    if fov < 360:
        bearing = (np.degrees(np.arctan2(dx, dy)) + 360.0) % 360.0
        diff = np.abs((bearing - azimuth + 180.0) % 360.0 - 180.0)
        cand &= diff <= fov / 2.0

    visible = np.zeros(dem.shape, dtype=bool)
    r0, c0 = int(np.clip(row0, 0, dem.shape[0] - 1)), int(np.clip(col0, 0, dem.shape[1] - 1))
    eye_z = dem[r0, c0] + eye_h
    for tr, tc, d in zip(rr[cand], cc[cand], dist[cand]):
        steps = max(2, int(d / (res / 2)))
        t = np.linspace(0, 1, steps, endpoint=False)[1:]
        sr = np.clip((row0 + (tr + 0.5 - row0) * t).astype(int), 0, dem.shape[0] - 1)
        sc = np.clip((col0 + (tc + 0.5 - col0) * t).astype(int), 0, dem.shape[1] - 1)
        target_angle = (dem[tr, tc] + target_h - eye_z) / d
        if np.all((dem[sr, sc] - eye_z) / (t * d) <= target_angle):
            visible[tr, tc] = True
    return visible


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    out_dir = project_root / "outputs" / "viewshed"
    parser = argparse.ArgumentParser()
    parser.add_argument("--dem", type=Path, default=project_root / "data/raw/dem/busan_copernicus_dsm30_5186.tif")
    parser.add_argument("--sites", type=Path, default=project_root / "outputs/cctv_reanalysis/cctv_integrated_locations_fov.csv")
    parser.add_argument("--gpkg", type=Path, default=project_root / "outputs/cctv_reanalysis/coastal_safety_busan_cctv_updated.gpkg")
    args = parser.parse_args()
    out_dir.mkdir(parents=True, exist_ok=True)

    coast = gpd.read_file(args.gpkg, layer="coastline_monitoring_segments_cctv_updated").to_crs(CRS_ANALYSIS)
    sites = pd.read_csv(args.sites, encoding="utf-8-sig")

    # 분석 대상: 해안선 양쪽 100m 버퍼(구간 ID 유지) + DEM 격자 마스크
    with rasterio.open(args.dem) as src:
        dem = src.read(1)
        dem = np.where(dem == src.nodata, 0.0, dem).astype("float32")
        transform, profile = src.transform, src.profile
        zone = coast[["segment_id", "SGG_NAM", "geometry"]].copy()
        zone["geometry"] = [robust_buffer(g, PARAMS["target_zone_m"]) for g in zone.geometry]
        zone["zone_area_m2"] = zone.geometry.area.round(1)
        zone_mask = rasterize(
            [(g, 1) for g in zone.geometry], out_shape=dem.shape, transform=transform, fill=0, dtype="uint8"
        )
        zone_index = nearest_segment_grid(zone_mask, coast.geometry, transform)
        observers = observer_table(sites, coast, src, dem_arr=dem, transform=transform, zone_mask=zone_mask)

    gpkg_out = out_dir / "viewshed_inputs.gpkg"
    observers.to_file(gpkg_out, layer="observers", driver="GPKG")
    zone.to_file(gpkg_out, layer="target_zone", driver="GPKG")
    observers.drop(columns="geometry").to_csv(out_dir / "viewshed_observers.csv", index=False, encoding="utf-8-sig")
    mask_profile = {**profile, "dtype": "uint8", "nodata": 0}
    with rasterio.open(out_dir / "target_zone_mask.tif", "w", **mask_profile) as dst:
        dst.write(zone_mask, 1)
    with rasterio.open(out_dir / ZONE_INDEX_FILE, "w", **{**profile, "dtype": "int32", "nodata": 0}) as dst:
        dst.write(zone_index, 1)
    (out_dir / "viewshed_params.json").write_text(json.dumps(PARAMS, ensure_ascii=False, indent=2), encoding="utf-8")

    # 스모크 테스트: PTZ 1대 + 고정 1대
    tests = pd.concat([
        observers[observers["view_type"].eq("ptz_360") & observers["can_reach_zone"]].head(1),
        observers[observers["view_type"].eq("fixed") & observers["fov_deg"].lt(360) & observers["can_reach_zone"]].head(1),
    ])
    cell_area = transform.a * -transform.e
    for _, o in tests.iterrows():
        start = time.perf_counter()
        vis = viewshed(dem, transform, o.geometry.x, o.geometry.y, o.mount_height_m,
                       PARAMS["target_height_m"], o.view_range_m, o.azimuth_deg, o.fov_deg)
        elapsed = time.perf_counter() - start
        print(
            f"{o.integrated_id} {o.view_type} fov={o.fov_deg:.0f} az={o.azimuth_deg:.0f} "
            f"visible={vis.sum() * cell_area / 1e4:.2f}ha in_zone={(vis & (zone_mask == 1)).sum() * cell_area / 1e4:.2f}ha "
            f"({elapsed:.2f}s)"
        )

    zone_area = zone_mask.sum() * cell_area
    print(f"observers {len(observers):,} (of {len(sites):,} sites within {PARAMS['coast_search_m']:.0f}m)")
    print(f"can reach target zone {observers['can_reach_zone'].sum():,}")
    print(pd.crosstab(observers["view_type"], observers["can_reach_zone"]).to_string())
    reach_obs = observers[observers["can_reach_zone"]]
    print("\n[전체 1,782개 해안 관측 CCTV 3분류 요약]")
    print(reach_obs.groupby(["ocean_view_group", "ocean_view_detail"]).size().to_string())
    print(f"fov assumed {observers['fov_assumed'].sum():,} / target zone {zone_area / 1e6:.2f} km2")


if __name__ == "__main__":
    main()

