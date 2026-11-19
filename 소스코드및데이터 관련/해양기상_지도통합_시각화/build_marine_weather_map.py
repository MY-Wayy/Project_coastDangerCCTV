#!/usr/bin/env python3
"""해양기상(부이 배정·파고 임계·파랑노출 W)이 해안선 구간 지도에 통합된 결과를 시각화용 데이터로 만든다.

원본은 읽기만 한다 (통합완료 데이터 관련/ 아래 파일은 수정하지 않음).
  - 해안선 구간 형상 : DatoryLab_trackB_2/outputs/cctv_reanalysis/coastal_safety_busan_cctv_updated.gpkg
  - 구간별 통합표   : DatoryLab_trackB_2/outputs/trackD/segments.csv  (build_trackD_dataset.py 산출)
  - 관측소 임계     : DatoryLab_trackB_2/outputs/trackD/station_thresholds.csv
  - 연안사고        : 부산전체_행정안전부_연안사고.csv
  - 신규 상위 50곳  : trackB_2_results/csv/top50_sites_direction_classified.csv + new_sites_ranked_trackB_weights.csv(위험도 가중 순위 좌표)

출력 (이 폴더):
  data/segments_weather.geojson  해안선 1,832구간 (WGS84) + 기상·위험 속성
  data/accidents.geojson         연안사고 2,138건 + 기상상태 + 최근접 구간의 배정 부이(1km 이내)
  data/top50_sites.geojson       신규 상위 50곳 + 배정 부이
  data/station_summary.csv       부이별 요약
  해양기상_지도통합_시각화.html     map_template.html 에 위 데이터를 넣은 단일 파일 지도
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "통합완료 데이터 관련"
TRACK = SRC / "DatoryLab_trackB_2"
GPKG = TRACK / "outputs" / "cctv_reanalysis" / "coastal_safety_busan_cctv_updated.gpkg"
SEGMENTS = TRACK / "outputs" / "trackD" / "segments.csv"
THRESHOLDS = TRACK / "outputs" / "trackD" / "station_thresholds.csv"
ACCIDENTS = SRC / "부산전체_행정안전부_연안사고.csv"
TOP50 = SRC / "trackB_2_results" / "csv" / "top50_sites_direction_classified.csv"
RANKED = SRC / "trackB_2_results" / "csv" / "new_sites_ranked_trackB_weights.csv"

OUT = HERE / "data"
CRS = "EPSG:5186"
SIMPLIFY_M = 3.0          # 지도 표시용 단순화 허용오차
ACC_MATCH_M = 1000.0      # 사고 → 최근접 해안 구간 배정 최대 거리
STATIONS = ["기장", "오륙도", "다대포"]


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def to_geojson(gdf: gpd.GeoDataFrame, path: Path, precision: int = 5) -> dict:
    gj = json.loads(gdf.to_crs("EPSG:4326").to_json(drop_id=True, to_wgs84=False))

    def rnd(c):
        return [round(v, precision) for v in c] if isinstance(c[0], float) else [rnd(x) for x in c]

    for f in gj["features"]:
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
    path.write_text(json.dumps(gj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return gj


def main() -> None:
    OUT.mkdir(exist_ok=True)

    # 1) 해안선 구간 형상 + 트랙 D 통합표(기상 배정·임계·W·위험도·CCTV 가시율)
    geom = gpd.read_file(GPKG, layer="coastline_monitoring_segments_cctv_updated")[["segment_id", "geometry"]]
    seg = read_csv(SEGMENTS)
    keep = ["segment_id", "구", "해안유형", "segment_length_m", "노출그룹", "배정관측소", "파고임계_m",
            "T_유형위험", "W_파랑노출", "위험지수", "위험등급", "육지부", "설치대상",
            "view_coverage_pct_conservative", "cctv_count_500m"]
    segs = geom.merge(seg[keep], on="segment_id", how="left", validate="1:1")
    assert segs["배정관측소"].notna().all(), "구간-통합표 조인 누락"
    segs = segs.set_crs(CRS, allow_override=True)

    disp = segs.copy()
    disp["geometry"] = disp.geometry.simplify(SIMPLIFY_M, preserve_topology=False)
    disp = disp.rename(columns={
        "segment_id": "id", "구": "gu", "해안유형": "type", "segment_length_m": "len",
        "노출그룹": "exp", "배정관측소": "st", "파고임계_m": "hs", "T_유형위험": "T", "W_파랑노출": "W",
        "위험지수": "R", "위험등급": "grade", "육지부": "land", "설치대상": "site",
        "view_coverage_pct_conservative": "cov", "cctv_count_500m": "cctv",
    })
    disp["cov"] = disp["cov"].round(1)
    disp["len"] = disp["len"].round(0)
    seg_gj = to_geojson(disp, OUT / "segments_weather.geojson")

    # 2) 연안사고 — 기상상태(wether_sn) + 최근접 구간(1km 이내)의 배정 부이
    acc = read_csv(ACCIDENTS)
    acc = gpd.GeoDataFrame(acc, geometry=gpd.points_from_xy(acc["lon_exact"], acc["lat_exact"]), crs="EPSG:4326").to_crs(CRS)
    near = gpd.sjoin_nearest(acc, segs[["segment_id", "배정관측소", "geometry"]], how="left",
                             max_distance=ACC_MATCH_M, distance_col="dist_m")
    near = near[~near.index.duplicated(keep="first")]
    acc["st"] = near["배정관측소"]
    acc["dist_m"] = near["dist_m"].round(0)
    acc["bad_wx"] = acc["wether_sn"].ne("양호")
    acc_out = acc.rename(columns={"occu_ty": "kind", "wether_sn": "wx", "occu_year": "year",
                                  "occu_date": "date", "acdn_lc_cn": "place", "occu_lc": "zone"})
    acc_out = acc_out[["kind", "wx", "bad_wx", "year", "date", "place", "zone", "st", "dist_m", "geometry"]]
    acc_out["date"] = acc_out["date"].astype(str)
    acc_gj = to_geojson(acc_out, OUT / "accidents.geojson")

    # 3) 신규 상위 50곳 (위험도 가중 배치, original_360) — 좌표는 new_sites_ranked_trackB_weights.csv
    top = read_csv(TOP50)
    ranked = read_csv(RANKED)
    top = top.merge(ranked[["baseline", "rank", "candidate_id", "x_5186", "y_5186"]],
                    on=["baseline", "rank", "candidate_id"], how="left", validate="1:1")
    assert top["x_5186"].notna().all(), "상위 50곳 좌표 조인 누락"
    top = top.merge(seg[["segment_id", "배정관측소", "W_파랑노출", "파고임계_m"]], on="segment_id", how="left")
    top_g = gpd.GeoDataFrame(top, geometry=gpd.points_from_xy(top["x_5186"], top["y_5186"]), crs=CRS)
    top_g = top_g.rename(columns={"rank": "rank", "SGG_NAM": "gu", "coast_type": "type", "risk_index": "R",
                                  "acc_count_500m": "acc", "severe_acc_500m": "sev",
                                  "camera_direction_type": "dir", "배정관측소": "st", "W_파랑노출": "W",
                                  "파고임계_m": "hs"})
    top_g["gu"] = top_g["gu"].str.replace("부산광역시 ", "", regex=False)
    top_g = top_g[["rank", "candidate_id", "gu", "type", "R", "위험등급", "acc", "sev", "dir", "st", "W", "hs", "geometry"]]
    top_g = top_g.rename(columns={"위험등급": "grade"})
    top_gj = to_geojson(top_g, OUT / "top50_sites.geojson", precision=6)

    # 4) 부이별 요약
    th = read_csv(THRESHOLDS).set_index("배정관측소")
    rows = []
    for st in STATIONS:
        s = segs[segs["배정관측소"] == st]
        a = acc[acc["st"] == st]
        land = s[s["설치대상"]]
        rows.append({
            "관측소": st,
            "노출그룹": "/".join(sorted(s["노출그룹"].unique())),
            "구간수": len(s),
            "해안길이_km": round(s["segment_length_m"].sum() / 1000, 1),
            "파고임계_m": th.loc[st, "파고임계_m"],
            "풍속임계_ms": th.loc[st, "풍속임계_ms"],
            "W_파랑노출": round(s["W_파랑노출"].mean(), 3),
            "평균위험지수": round(s["위험지수"].mean(), 3),
            "위험등급45_구간": int(s["위험등급"].ge(4).sum()),
            "설치대상_보수적가시율_pct": round(
                (land["view_coverage_pct_conservative"].fillna(0) * land["segment_length_m"]).sum()
                / land["segment_length_m"].sum(), 1),
            "연안사고_1km": len(a),
            "악기상사고_1km": int(a["bad_wx"].sum()),
            "악기상비율_pct": round(100 * a["bad_wx"].mean(), 1) if len(a) else 0.0,
            "신규상위50": int((top_g["st"] == st).sum()),
        })
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / "station_summary.csv", index=False, encoding="utf-8-sig")

    wx_counts = acc["wether_sn"].value_counts().to_dict()
    meta = {
        "segments": len(segs), "accidents": len(acc), "acc_matched": int(acc["st"].notna().sum()),
        "acc_match_m": ACC_MATCH_M, "wx_counts": wx_counts,
        "years": [int(acc["occu_year"].min()), int(acc["occu_year"].max())],
    }

    # 5) 템플릿에 데이터 주입 → 단일 HTML
    payload = {"segments": seg_gj, "accidents": acc_gj, "top50": top_gj,
               "summary": summary.to_dict(orient="records"), "meta": meta}
    template = (HERE / "map_template.html").read_text(encoding="utf-8")
    leaflet_css = (HERE / "vendor" / "leaflet-1.9.4.css").read_text(encoding="utf-8")
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = template.replace("/*__LEAFLET_CSS__*/", leaflet_css).replace("/*__DATA__*/null", data_js)
    (HERE / "해양기상_지도통합_시각화.html").write_text(html, encoding="utf-8")

    print(summary.to_string(index=False))
    print(meta)


if __name__ == "__main__":
    main()
