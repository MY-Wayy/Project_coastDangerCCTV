#!/usr/bin/env python3
"""Track D: join Track A risk outputs with Track B CCTV/viewshed results into one segment table.

Outputs (outputs/trackD/):
  segments.csv           1,832 segments x (location, coast type, island flag, station + thresholds,
                         Track A risk, Track B CCTV distance / viewshed coverage)
  trackB_weights.csv     segment_id,weight for Track B risk-weighted placement (island segments = 0)
  cctv_candidates_v4.csv Track A rule re-applied on the corrected Track B results (land only)
  station_thresholds.csv 관측소별 파고·풍속 임계 (풍속은 오륙도 등표 1곳 값)
  validation.json        row counts, uniqueness, constant-column and join checks
If outputs/trackD/station_hourly.csv (Track D weather table) exists, query.py joins it by station.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from site_exclusions import excluded_mask, manual_ids  # noqa: E402


PROJECT = Path(__file__).resolve().parents[1]
TRACK_A = PROJECT / "data" / "raw" / "trackA" / "track_a_csvs_20261014"
TRACK_B = PROJECT / "outputs" / "input_trackB_segments.csv"
GPKG = PROJECT / "outputs" / "cctv_reanalysis" / "coastal_safety_busan_cctv_updated.gpkg"
OUT = PROJECT / "outputs" / "trackD"
CANDIDATE_MIN_GRADE = 4
ISLAND_CODE = 2  # 해안선 GRP_ISL: 01 육지부, 02 도서부


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights-only", action="store_true",
                        help="trackB_weights.csv만 생성 (트랙 B 구간별 결과가 나오기 전 단계용)")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    risk = pd.read_csv(TRACK_A / "4_구간별위험지수.csv", encoding="utf-8-sig")
    thresholds = pd.read_csv(TRACK_A / "2_관측소별임계.csv", encoding="utf-8-sig")
    assign = pd.read_csv(TRACK_A / "1_관측소배정.csv", encoding="utf-8-sig")

    seg = gpd.read_file(GPKG, layer="coastline_monitoring_segments_cctv_updated")
    mid = seg.geometry.interpolate(0.5, normalized=True).to_crs("EPSG:4326")
    geo = pd.DataFrame({
        "segment_id": seg["segment_id"],
        "lat": mid.y.round(6),
        "lon": mid.x.round(6),
        "육지부": seg["GRP_ISL"].ne(ISLAND_CODE),
        # 설치대상 = 육지부이면서 수동 제외 목록(data/raw/manual_site_exclusions.csv)에 없음
        "설치대상": ~excluded_mask(seg),
        "GRP_ISL": seg["GRP_ISL"],
        "자연인공_GRP_CON": seg["GRP_CON"],
        "출입통제구역_거리_m": seg["restricted_distance_m"],
    })

    # 트랙 B 가중치: 위험지수, 섬(도서부: 도보 접근 불가)은 0 — 트랙 B 결과 없이 만들 수 있음
    weights = risk[["segment_id"]].merge(geo[["segment_id", "설치대상"]], on="segment_id")
    weights["weight"] = risk["위험지수"].where(weights["설치대상"], 0.0)
    weights[["segment_id", "weight"]].to_csv(OUT / "trackB_weights.csv", index=False, encoding="utf-8-sig")
    if args.weights_only:
        print(f"saved trackB_weights.csv (nonzero {int(weights['weight'].gt(0).sum())}, excluded 0: {int((~weights['설치대상']).sum())})")
        return
    trackb = pd.read_csv(TRACK_B, encoding="utf-8-sig")

    # Track A 구간표에서 예전 CCTV 컬럼은 버리고 트랙 B 최신값으로 교체
    old_cctv = ["nearest_cctv_m", "cctv_count_500m", "cctv_gap_500m", "view_coverage_pct_conservative", "cctv_기준"]
    base = risk.drop(columns=[c for c in old_cctv if c in risk.columns])
    th = thresholds.rename(columns={
        "관측소": "배정관측소",
        "지점별임계_P85_m": "파고임계_m",
        "풍속임계_오륙도등표_P85_ms": "풍속임계_ms",
    })[["배정관측소", "파고임계_m", "풍속임계_ms"]]
    # 풍속은 오륙도 등표 한 곳 값이라 전 구간 동일 → 구간표가 아니라 관측소 임계표에 둔다
    th.to_csv(OUT / "station_thresholds.csv", index=False, encoding="utf-8-sig")
    cctv = trackb[[
        "segment_id", "nearest_cctv_m", "cctv_count_500m", "cctv_gap_500m",
        "view_zone_ha", "view_coverage_pct_original", "view_coverage_pct_conservative",
        "view_blind_ha_conservative", "nearest_cctv_traffic_only_m",
    ]]

    segments = (
        base.merge(geo, on="segment_id", how="left")
        .merge(th[["배정관측소", "파고임계_m"]], on="배정관측소", how="left")
        .merge(cctv, on="segment_id", how="left")
    )
    front = ["segment_id", "구", "lat", "lon", "육지부", "설치대상", "해안유형", "CAT_COA", "segment_length_m",
             "노출그룹", "배정관측소", "파고임계_m",
             "T_유형위험", "W_파랑노출", "위험지수", "위험등급"]
    segments = segments[front + [c for c in segments.columns if c not in front]].sort_values("segment_id")
    segments.to_csv(OUT / "segments.csv", index=False, encoding="utf-8-sig")


    # 설치후보 재선정: 위험등급 4·5 + 육지부 + 보수적 가시 커버율 0% (면적 0 구간 제외)
    cand = segments[
        segments["위험등급"].ge(CANDIDATE_MIN_GRADE)
        & segments["설치대상"]
        & segments["view_coverage_pct_conservative"].eq(0)
    ].sort_values(["위험지수", "nearest_cctv_m"], ascending=[False, False])
    cand.to_csv(OUT / "cctv_candidates_v4.csv", index=False, encoding="utf-8-sig")

    prev = pd.read_csv(TRACK_A / "5_CCTV설치후보.csv", encoding="utf-8-sig")
    constant = [c for c in segments.columns if segments[c].nunique(dropna=False) <= 1]
    checks = {
        "segments_rows": int(len(segments)),
        "segment_id_unique": bool(segments["segment_id"].is_unique),
        "station_assignment_matches_file1": bool(
            segments.set_index("segment_id")["배정관측소"].eq(assign.set_index("segment_id")["배정관측소"]).all()
        ),
        "threshold_join_missing": int(segments["파고임계_m"].isna().sum()),
        "trackB_join_missing": int(segments["nearest_cctv_m"].isna().sum()),
        "constant_columns": constant,
        "island_segments": int((~segments["육지부"]).sum()),
        "manual_excluded_segments": sorted(manual_ids()),
        "install_excluded_segments": int((~segments["설치대상"]).sum()),
        "grade_counts": {int(k): int(v) for k, v in segments["위험등급"].value_counts().sort_index().items()},
        "weights_nonzero": int(weights["weight"].gt(0).sum()),
        "weights_zeroed_excluded_grade4plus": int((~segments["설치대상"] & segments["위험등급"].ge(4)).sum()),
        "candidates_v4": int(len(cand)),
        "candidates_trackA_v3": int(len(prev)),
        "candidates_kept": int(cand["segment_id"].isin(prev["segment_id"]).sum()),
        "candidates_added": sorted(set(cand["segment_id"]) - set(prev["segment_id"])),
        "candidates_dropped": sorted(set(prev["segment_id"]) - set(cand["segment_id"])),
        "zero_area_segments": int(segments["view_coverage_pct_conservative"].isna().sum()),
    }
    (OUT / "validation.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    print(cand.groupby("구").size().to_string())


if __name__ == "__main__":
    main()
