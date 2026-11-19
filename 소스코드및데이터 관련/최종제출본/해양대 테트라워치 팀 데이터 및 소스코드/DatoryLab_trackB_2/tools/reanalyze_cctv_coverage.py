#!/usr/bin/env python3
"""Rebuild Datory Lab CCTV coverage using MOIS, Busan ITS and disaster CCTV data."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


CRS_WGS84 = "EPSG:4326"
CRS_ANALYSIS = "EPSG:5186"
DEDUP_DISTANCE_M = 20.0


def read_csv(path: Path) -> pd.DataFrame:
    for encoding in ("cp949", "euc-kr", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Unable to decode {path}")


def classify_mois(value: object) -> str:
    text = str(value).strip()
    mapping = {
        "생활방범": "crime_prevention",
        "차량방범": "crime_prevention",
        "다목적": "multi_purpose",
        "교통단속": "enforcement",
        "어린이보호": "child_safety",
        "시설물관리": "facility_management",
        "재난재해": "disaster",
        "쓰레기단속": "enforcement",
        "기타": "unknown",
    }
    return mapping.get(text, "unknown")


def load_mois(path: Path) -> tuple[gpd.GeoDataFrame, dict[str, int]]:
    raw = read_csv(path)
    raw["WGS84위도"] = pd.to_numeric(raw["WGS84위도"], errors="coerce")
    raw["WGS84경도"] = pd.to_numeric(raw["WGS84경도"], errors="coerce")
    valid = raw[
        raw["WGS84위도"].between(34.0, 36.0)
        & raw["WGS84경도"].between(128.0, 130.0)
    ].copy()
    valid["purpose_std"] = valid["설치목적구분"].map(classify_mois)
    valid["camera_count"] = pd.to_numeric(valid["카메라대수"], errors="coerce").fillna(1)
    valid["coord_key"] = (
        valid["WGS84위도"].round(7).astype(str)
        + ","
        + valid["WGS84경도"].round(7).astype(str)
    )

    def joined(series: pd.Series) -> str:
        return "|".join(sorted({str(v).strip() for v in series.dropna() if str(v).strip()}))

    facilities = (
        valid.groupby("coord_key", as_index=False)
        .agg(
            lon=("WGS84경도", "first"),
            lat=("WGS84위도", "first"),
            camera_count=("camera_count", "sum"),
            purpose_std=("purpose_std", joined),
            purpose_original=("설치목적구분", joined),
            manager=("관리기관명", joined),
            road_address=("소재지도로명주소", joined),
            parcel_address=("소재지지번주소", joined),
            source_rows=("관리번호", "size"),
        )
    )
    facilities["source"] = "MOIS_CCTV"
    facilities["name"] = facilities["road_address"].where(
        facilities["road_address"].ne(""), facilities["parcel_address"]
    )
    gdf = gpd.GeoDataFrame(
        facilities,
        geometry=gpd.points_from_xy(facilities.lon, facilities.lat),
        crs=CRS_WGS84,
    ).to_crs(CRS_ANALYSIS)
    stats = {
        "raw_rows": len(raw),
        "valid_rows": len(valid),
        "invalid_rows": len(raw) - len(valid),
        "unique_locations": len(gdf),
        "camera_count_sum": int(valid["camera_count"].sum()),
    }
    return gdf, stats


def load_its(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path).to_crs(CRS_ANALYSIS).copy()
    gdf["source"] = "BUSAN_ITS_2026"
    gdf["purpose_std"] = "traffic"
    gdf["purpose_original"] = "교통정보"
    gdf["camera_count"] = 1
    gdf["source_rows"] = 1
    gdf["manager"] = "부산광역시 교통정보서비스센터"
    gdf["road_address"] = ""
    gdf["parcel_address"] = ""
    return gdf[["name", "camera_count", "purpose_std", "purpose_original", "manager",
                "road_address", "parcel_address", "source_rows", "source", "geometry"]]


def load_existing(gpkg: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(gpkg, layer="cctv_busan").to_crs(CRS_ANALYSIS).copy()
    gdf["name"] = gdf["instlPos"]
    gdf["source"] = "BUSAN_TRAFFIC_API_EXISTING"
    gdf["purpose_std"] = "traffic"
    gdf["purpose_original"] = "교통정보"
    gdf["camera_count"] = 1
    gdf["source_rows"] = 1
    gdf["manager"] = "부산광역시"
    gdf["road_address"] = ""
    gdf["parcel_address"] = ""
    return gdf[["name", "camera_count", "purpose_std", "purpose_original", "manager",
                "road_address", "parcel_address", "source_rows", "source", "geometry"]]


def load_disaster(path: Path) -> tuple[gpd.GeoDataFrame, dict[str, int]]:
    raw = read_csv(path)
    busan = raw[raw["시도명"].eq("부산광역시")].copy()
    cctv = busan[busan["시설종류"].astype(str).str.contains("CCTV|영상", case=False, na=False)].copy()
    cctv["위도"] = pd.to_numeric(cctv["위도"], errors="coerce")
    cctv["경도"] = pd.to_numeric(cctv["경도"], errors="coerce")
    cctv = cctv[cctv["위도"].between(34.0, 36.0) & cctv["경도"].between(128.0, 130.0)]
    gdf = gpd.GeoDataFrame(
        {
            "name": cctv["시설명"].fillna(""),
            "camera_count": 1,
            "purpose_std": "disaster",
            "purpose_original": cctv["시설종류"].fillna(""),
            "manager": cctv["제공기관명"].fillna(""),
            "road_address": cctv["소재지도로명주소"].fillna(""),
            "parcel_address": cctv["소재지지번주소"].fillna(""),
            "source_rows": 1,
            "source": "DISASTER_WARNING_CCTV",
        },
        geometry=gpd.points_from_xy(cctv["경도"], cctv["위도"]),
        crs=CRS_WGS84,
    ).to_crs(CRS_ANALYSIS)
    return gdf, {"national_rows": len(raw), "busan_rows": len(busan), "busan_cctv_rows": len(gdf)}


def append_unique(canonical: gpd.GeoDataFrame, incoming: gpd.GeoDataFrame, source_name: str):
    kept = []
    duplicate_distances = []
    duplicate_indices = []
    for idx, row in incoming.iterrows():
        distances = canonical.geometry.distance(row.geometry)
        nearest_idx = distances.idxmin()
        nearest_dist = float(distances.loc[nearest_idx])
        if nearest_dist <= DEDUP_DISTANCE_M:
            duplicate_indices.append(idx)
            duplicate_distances.append(nearest_dist)
            canonical.at[nearest_idx, "sources"] = "|".join(sorted(set(
                str(canonical.at[nearest_idx, "sources"]).split("|") + [source_name]
            )))
            canonical.at[nearest_idx, "purpose_std"] = "|".join(sorted(set(
                str(canonical.at[nearest_idx, "purpose_std"]).split("|")
                + str(row["purpose_std"]).split("|")
            )))
        else:
            kept.append(idx)
    if kept:
        additions = incoming.loc[kept].copy()
        additions["sources"] = additions["source"]
        additions["canonical_source"] = additions["source"]
        for column in canonical.columns:
            if column not in additions.columns:
                additions[column] = np.nan
        canonical = pd.concat([canonical, additions[canonical.columns]], ignore_index=True)
        canonical = gpd.GeoDataFrame(canonical, geometry="geometry", crs=CRS_ANALYSIS)
    report = {
        "source": source_name,
        "input_locations": len(incoming),
        "duplicates_within_20m": len(duplicate_indices),
        "new_locations_added": len(kept),
        "median_duplicate_distance_m": round(float(np.median(duplicate_distances)), 2)
        if duplicate_distances else np.nan,
    }
    return canonical, report


def integrate(mois, its, existing, disaster):
    canonical = mois.copy()
    canonical["sources"] = canonical["source"]
    canonical["canonical_source"] = canonical["source"]
    reports = []
    for incoming, name in (
        (its, "BUSAN_ITS_2026"),
        (existing, "BUSAN_TRAFFIC_API_EXISTING"),
        (disaster, "DISASTER_WARNING_CCTV"),
    ):
        canonical, report = append_unique(canonical, incoming, name)
        reports.append(report)
    canonical = canonical.reset_index(drop=True)
    canonical["integrated_id"] = [f"ICCTV_{i:05d}" for i in range(1, len(canonical) + 1)]
    return canonical, pd.DataFrame(reports)


def add_coverage(segments: gpd.GeoDataFrame, points: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = segments.copy()
    nearest = gpd.sjoin_nearest(
        out[["segment_id", "geometry"]],
        points[["integrated_id", "geometry"]],
        how="left",
        distance_col="nearest_cctv_all_m",
    ).sort_values("nearest_cctv_all_m").drop_duplicates("segment_id")
    nearest = nearest.set_index("segment_id")
    out["nearest_cctv_all_m"] = out["segment_id"].map(nearest["nearest_cctv_all_m"]).round(2)

    # buffer(500) 대신 거리 조인: GEOS 3.11의 짧은 곡선 버퍼 오류(면적 축소)를 피한다
    joined = gpd.sjoin(
        points[["integrated_id", "purpose_std", "geometry"]], out[["segment_id", "geometry"]],
        predicate="dwithin", distance=500, how="inner",
    )
    all_counts = joined.groupby("segment_id")["integrated_id"].nunique()
    out["cctv_all_count_500m"] = out["segment_id"].map(all_counts).fillna(0).astype(int)
    out["cctv_all_gap_500m"] = out["cctv_all_count_500m"].eq(0)

    category_patterns = {
        "traffic": "traffic",
        "crime": "crime_prevention|multi_purpose",
        "disaster": "disaster",
        "enforcement": "enforcement|child_safety",
        "facility": "facility_management",
    }
    for label, pattern in category_patterns.items():
        subset = joined[joined["purpose_std"].str.contains(pattern, regex=True, na=False)]
        counts = subset.groupby("segment_id")["integrated_id"].nunique()
        out[f"cctv_{label}_count_500m"] = out["segment_id"].map(counts).fillna(0).astype(int)
    safety = joined[joined["purpose_std"].str.contains(
        "traffic|crime_prevention|multi_purpose|disaster|facility_management",
        regex=True,
        na=False,
    )]
    safety_counts = safety.groupby("segment_id")["integrated_id"].nunique()
    out["cctv_safety_count_500m"] = out["segment_id"].map(safety_counts).fillna(0).astype(int)
    out["cctv_safety_gap_500m"] = out["cctv_safety_count_500m"].eq(0)
    return out


def district_summary(segments: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for district, group in segments.groupby("SGG_NAM", dropna=False):
        n = len(group)
        rows.append({
            "district": district,
            "segments": n,
            "old_traffic_covered_segments": int((~group["cctv_gap_500m"]).sum()),
            "old_traffic_coverage_pct": round((~group["cctv_gap_500m"]).mean() * 100, 1),
            "new_all_covered_segments": int((~group["cctv_all_gap_500m"]).sum()),
            "new_all_coverage_pct": round((~group["cctv_all_gap_500m"]).mean() * 100, 1),
            "new_safety_covered_segments": int((~group["cctv_safety_gap_500m"]).sum()),
            "new_safety_coverage_pct": round((~group["cctv_safety_gap_500m"]).mean() * 100, 1),
            "median_nearest_all_m": round(group["nearest_cctv_all_m"].median(), 1),
            "disaster_covered_segments": int((group["cctv_disaster_count_500m"] > 0).sum()),
        })
    return pd.DataFrame(rows).sort_values("new_safety_coverage_pct")


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir", type=Path, default=project_root / "data" / "raw" / "cctv_reanalysis"
    )
    parser.add_argument("--output-dir", type=Path, default=project_root / "outputs" / "cctv_reanalysis")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    gpkg_in = args.input_dir / "coastal_safety_busan.gpkg"
    its_shp = next((args.input_dir / "its_cctv_2026").glob("*.shp"))
    mois, mois_stats = load_mois(args.input_dir / "cctv_mois_busan.csv")
    its = load_its(its_shp)
    existing = load_existing(gpkg_in)
    disaster, disaster_stats = load_disaster(args.input_dir / "disaster_warning_facilities.csv")
    integrated, dedup = integrate(mois, its, existing, disaster)

    segments = gpd.read_file(gpkg_in, layer="coastline_monitoring_segments").to_crs(CRS_ANALYSIS)
    updated_segments = add_coverage(segments, integrated)
    districts = district_summary(updated_segments)

    gpkg_out = args.output_dir / "coastal_safety_busan_cctv_updated.gpkg"
    shutil.copy2(gpkg_in, gpkg_out)
    mois.to_file(gpkg_out, layer="cctv_mois_locations", driver="GPKG")
    its.to_file(gpkg_out, layer="cctv_its_2026", driver="GPKG")
    disaster.to_file(gpkg_out, layer="cctv_disaster_warning", driver="GPKG")
    integrated.to_file(gpkg_out, layer="cctv_integrated_locations", driver="GPKG")
    updated_segments.to_file(gpkg_out, layer="coastline_monitoring_segments_cctv_updated", driver="GPKG")

    integrated.drop(columns="geometry").to_csv(
        args.output_dir / "cctv_integrated_locations.csv", index=False, encoding="utf-8-sig"
    )
    districts.to_csv(args.output_dir / "cctv_coverage_by_district.csv", index=False, encoding="utf-8-sig")
    dedup.to_csv(args.output_dir / "cctv_deduplication_report.csv", index=False, encoding="utf-8-sig")

    total = len(updated_segments)
    summary = pd.DataFrame([
        ("기존 교통 CCTV 위치", len(existing)),
        ("행안부 원본 행", mois_stats["raw_rows"]),
        ("행안부 유효 좌표 행", mois_stats["valid_rows"]),
        ("행안부 좌표 무효 행", mois_stats["invalid_rows"]),
        ("행안부 고유 설치지점", mois_stats["unique_locations"]),
        ("행안부 카메라 대수 합", mois_stats["camera_count_sum"]),
        ("부산 ITS 위치", len(its)),
        ("부산 재난예경보 CCTV 행", disaster_stats["busan_cctv_rows"]),
        ("통합 고유 CCTV 위치", len(integrated)),
        ("분석 해안구간", total),
        ("기존 교통 CCTV 500m 커버 구간", int((~updated_segments["cctv_gap_500m"]).sum())),
        ("기존 교통 CCTV 500m 커버리지(%)", round((~updated_segments["cctv_gap_500m"]).mean()*100, 1)),
        ("신규 전체 CCTV 500m 커버 구간", int((~updated_segments["cctv_all_gap_500m"]).sum())),
        ("신규 전체 CCTV 500m 커버리지(%)", round((~updated_segments["cctv_all_gap_500m"]).mean()*100, 1)),
        ("신규 안전목적 CCTV 500m 커버 구간", int((~updated_segments["cctv_safety_gap_500m"]).sum())),
        ("신규 안전목적 CCTV 500m 커버리지(%)", round((~updated_segments["cctv_safety_gap_500m"]).mean()*100, 1)),
        ("신규 전체 CCTV 최근접거리 중앙값(m)", round(updated_segments["nearest_cctv_all_m"].median(), 1)),
        ("재난 CCTV 500m 커버 구간", int((updated_segments["cctv_disaster_count_500m"] > 0).sum())),
    ], columns=["metric", "value"])
    summary.to_csv(args.output_dir / "cctv_reanalysis_summary.csv", index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))
    print("\nDeduplication\n", dedup.to_string(index=False))
    print("\nDistricts\n", districts.to_string(index=False))


if __name__ == "__main__":
    main()
