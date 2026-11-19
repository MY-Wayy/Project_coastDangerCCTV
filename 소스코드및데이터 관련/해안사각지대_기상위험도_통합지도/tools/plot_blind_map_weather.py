#!/usr/bin/env python3
"""사각지대·신규 후보지 인터랙티브 지도에 해양기상·위험도 정보를 통합한 버전.

원본: 통합완료 데이터 관련/DatoryLab_trackB_2/tools/plot_viewshed_maps.py 의 복제본.
원본 프로젝트는 읽기만 하고, 결과(HTML·CSV)는 이 폴더의 outputs/ 에만 쓴다.
원본 대비 바뀐 점
  - 해안선 툴팁: 트랙 D 구간표(배정 부이·파고/풍속 임계·W·T·R·위험등급) 추가
  - 해안선 색 기준 전환 버튼: 가시 커버율 / 위험등급 / 배정 부이 / 파랑노출 W
  - 연안사고: 사고 당시 기상상태(양호 / 악기상)로 레이어·색 구분, 툴팁에 기상 추가
  - 신규 후보지 툴팁: 배정 부이·W·위험등급 추가
  - 정적 PNG 지도는 만들지 않음
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from site_exclusions import excluded_mask  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
PROJECT = HERE.parent / "통합완료 데이터 관련" / "DatoryLab_trackB_2"  # 원본 (읽기 전용)
VS_DIR = PROJECT / "outputs" / "viewshed"
OUT_DIR = HERE / "outputs"
MAP_DIR = OUT_DIR
OUT_DIR.mkdir(exist_ok=True)
BINS = [-0.1, 0, 25, 50, 75, 100]
LABELS = ["0% (완전 사각)", "0–25%", "25–50%", "50–75%", "75–100%"]
COLORS = ["#b2182b", "#ef8a62", "#fddbc7", "#92c5de", "#2166ac"]
ISLAND_COLOR = "#9e9e9e"


def load(baseline: str, top_n: int):
    gpkg = VS_DIR / "viewshed_results.gpkg"
    seg = gpd.read_file(gpkg, layer="segment_coverage")
    # 구간 표시는 버퍼가 아니라 해안선으로
    lines = gpd.read_file(
        PROJECT / "outputs/cctv_reanalysis/coastal_safety_busan_cctv_updated.gpkg",
        layer="coastline_monitoring_segments_cctv_updated",
    )[["segment_id", "GRP_ISL", "geometry"]].to_crs(seg.crs)
    seg = lines.merge(seg.drop(columns="geometry"), on="segment_id")
    seg["island"] = excluded_mask(seg)  # 섬(도서부) + 수동 제외: 설치 대상 아님 → 회색
    seg["class"] = pd.cut(seg["coverage_pct_current"].fillna(0), BINS, labels=False)
    sites = gpd.read_file(gpkg, layer="new_sites_ranked")
    sites = sites[(sites["baseline"] == baseline) & (sites["rank"] <= top_n)]
    obs = gpd.read_file(VS_DIR / "viewshed_inputs.gpkg", layer="observers")
    obs = obs[obs["can_reach_zone"]]
    return seg, sites, obs


DIRECTION_STYLES = {
    "① 해안 필수 직시형 (바다·테트라포드 고정)": ("#D50000", "#FFEB3B", "#FFFFFF"),
    "② 해안·내륙 복합형 (PTZ 양방향 전환)": ("#FF9100", "#212121", "#111111"),
    "③ 내륙·진입로 감시형 (해안 직시 불필요)": ("#00C853", "#FFFFFF", "#FFFFFF"),
}


def load_accidents_and_classify_sites(baseline: str, top_n: int, fallback_sites: gpd.GeoDataFrame):
    """위험도 가중 배치 상위 N개 후보지와 행안부 연안사고를 결합하여 촬영방향 3분류를 수행합니다."""
    gpkg = VS_DIR / "viewshed_results.gpkg"
    try:
        sites_w = gpd.read_file(gpkg, layer="new_sites_ranked_trackB_weights")
        sites_w = sites_w[(sites_w["baseline"] == baseline) & (sites_w["rank"] <= top_n)].copy()
    except Exception:
        sites_w = fallback_sites.copy()

    if sites_w.empty:
        sites_w = fallback_sites.copy()

    sites_w = sites_w.to_crs("EPSG:5186")
    if "main_segment_id" in sites_w.columns and "segment_id" not in sites_w.columns:
        sites_w["segment_id"] = sites_w["main_segment_id"]

    seg_csv = PROJECT / "outputs/trackD/segments.csv"
    if seg_csv.exists():
        seg_df = pd.read_csv(seg_csv, encoding="utf-8-sig")
        if "coast_type" not in seg_df.columns and "해안유형" in seg_df.columns:
            seg_df["coast_type"] = seg_df["해안유형"]
        if "risk_index" not in seg_df.columns and "위험지수" in seg_df.columns:
            seg_df["risk_index"] = seg_df["위험지수"]
        merge_cols = ["segment_id"] + [
            c for c in ["coast_type", "CAT_COA", "risk_index", "위험등급"]
            if c in seg_df.columns and c not in sites_w.columns
        ]
        sites_w = sites_w.merge(seg_df[merge_cols], on="segment_id", how="left")

    csv_candidates = [
        PROJECT / "부산전체_행정안전부_연안사고.csv",
        PROJECT.parent / "부산전체_행정안전부_연안사고.csv",
        Path("/home/alsgu/datory_work/부산전체_행정안전부_연안사고.csv"),
    ]
    acc_csv_path = next((p for p in csv_candidates if p.exists()), None)
    gdf_acc = None
    if acc_csv_path is not None:
        df_acc = None
        for enc in ("cp949", "euc-kr", "utf-8-sig", "utf-8"):
            try:
                df_acc = pd.read_csv(acc_csv_path, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        if df_acc is not None:
            col_map = {
                "objt_id": "OBJECTID",
                "acdn_lc_cn": "사고위치내용",
                "lon": "경도",
                "polc_nm": "해경서명",
                "occu_mt": "발생월",
                "occu_ca_de": "발생원인상세",
                "occu_ty_cd": "발생유형코드",
                "occu_ty": "발생유형",
                "occu_year": "발생년",
                "occu_de": "발생일",
                "x": "X좌표",
                "y": "Y좌표",
                "occu_date": "발생년월일",
                "occu_lc": "발생위치",
                "wether_sn": "기상상태",
                "lat": "위도",
                "occu_tm": "발생시간",
            }
            df_acc = df_acc.rename(
                columns={k: v for k, v in col_map.items() if k in df_acc.columns and v not in df_acc.columns}
            )
            df_acc["X좌표"] = pd.to_numeric(df_acc["X좌표"], errors="coerce")
            df_acc["Y좌표"] = pd.to_numeric(df_acc["Y좌표"], errors="coerce")
            df_acc = df_acc.dropna(subset=["X좌표", "Y좌표"]).copy()
            src_crs = "EPSG:3857" if df_acc["X좌표"].median() > 2_000_000 else "EPSG:5179"
            gdf_acc = gpd.GeoDataFrame(
                df_acc,
                geometry=gpd.points_from_xy(df_acc["X좌표"], df_acc["Y좌표"]),
                crs=src_crs,
            ).to_crs("EPSG:5186")

    human_acc_types = [
        "추락", "익수", "고립", "실종", "표류", "전복", "침몰",
        "좌초", "좌초/좌주", "충돌", "조난", "인명사상", "작업 중 인명사상",
    ]
    acc_type_col = "발생유형" if (gdf_acc is not None and "발생유형" in gdf_acc.columns) else "사고종류"

    directions, acc_counts_500m, human_acc_counts = [], [], []
    for _, row in sites_w.iterrows():
        if gdf_acc is not None:
            buf_500 = row.geometry.buffer(500)
            nearby_acc = gdf_acc[gdf_acc.geometry.within(buf_500)]
            total_cnt = len(nearby_acc)
            severe_cnt = len(
                nearby_acc[
                    nearby_acc[acc_type_col].isin(human_acc_types)
                    | nearby_acc["발생위치"].astype(str).str.replace(" ", "").eq("항계내")
                ]
            )
        else:
            total_cnt, severe_cnt = 0, 0

        c_type = str(row.get("coast_type", row.get("CAT_COA", "")))
        if total_cnt >= 3 or (severe_cnt >= 2 and any(k in c_type for k in ["방파제", "암벽", "테트라포드", "갯바위", "인공"])):
            d_label = "① 해안 필수 직시형 (바다·테트라포드 고정)"
        elif total_cnt >= 1 or any(k in c_type for k in ["항포구", "해수욕장", "모래"]):
            d_label = "② 해안·내륙 복합형 (PTZ 양방향 전환)"
        else:
            d_label = "③ 내륙·진입로 감시형 (해안 직시 불필요)"

        acc_counts_500m.append(total_cnt)
        human_acc_counts.append(severe_cnt)
        directions.append(d_label)

    sites_w["acc_count_500m"] = acc_counts_500m
    sites_w["severe_acc_500m"] = human_acc_counts
    sites_w["camera_direction_type"] = directions

    out_csv = OUT_DIR / "top50_sites_direction_classified.csv"  # 원본 대신 이 폴더에 저장
    sites_w.drop(columns="geometry").to_csv(out_csv, encoding="utf-8-sig", index=False)
    return sites_w, gdf_acc


SEG_CSV = PROJECT / "outputs/trackD/segments.csv"

# 해안선 색 기준별 색 (위험등급·부이·W는 해양기상_지도통합_시각화와 같은 값)
GRADE_COLORS = {2: "#2a78d6", 3: "#78abeb", 4: "#ef8f84", 5: "#c9302f"}
STATION_COLORS = {"기장": "#2a78d6", "오륙도": "#eb6834", "다대포": "#1baf7a"}
W_COLORS = [(0.5, "#86b6ef"), (0.99, "#1c5cab"), (9.0, "#0d366b")]  # 0.249 / 0.941 / 1.000
ACC_OK_COLOR, ACC_BAD_COLOR = "#7b93e8", "#6250d6"

def fmt(v, d: int = 0, unit: str = "") -> str:
    return "–" if v is None or pd.isna(v) else f"{v:,.{d}f}{unit}"


def segment_layer_data(seg: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """해안선에 트랙 D 구간표(해양기상 배정·임계·위험도)를 붙이고 색 기준별 색·툴팁 문자열을 만든다."""
    sd = pd.read_csv(SEG_CSV, encoding="utf-8-sig")
    th = pd.read_csv(PROJECT / "outputs/trackD/station_thresholds.csv", encoding="utf-8-sig")
    sd = sd.merge(th[["배정관측소", "풍속임계_ms"]], on="배정관측소", how="left")
    out = seg.merge(sd, on="segment_id", how="left", validate="1:1", suffixes=("", "_d"))
    assert out["배정관측소"].notna().all(), "해안선-구간표 조인 누락"

    cov_color = out["class"].map(dict(enumerate(COLORS))).fillna(COLORS[0])
    out["c_cov"] = cov_color.where(~out["island"], ISLAND_COLOR)
    out["c_grade"] = out["위험등급"].map(GRADE_COLORS)
    out["c_st"] = out["배정관측소"].map(STATION_COLORS)
    out["c_w"] = [next(c for lim, c in W_COLORS if w < lim) for w in out["W_파랑노출"]]

    def status(r) -> str:
        if not r["육지부"]:
            return "섬(도서부) · 설치 제외"
        return "육지부 · 설치 대상" if r["설치대상"] else "육지부 · 설치 제외(항만·터널 등)"

    out["tip"] = [
        "<div style='font-size:12px;line-height:1.5;min-width:230px'>"
        f"<b>{r['segment_id']}</b> · {r['SGG_NAM'].replace('부산광역시 ', '')} · {r['해안유형']}<br>"
        f"<span style='color:#666'>{status(r)} · 길이 {fmt(r['segment_length_m'])}m</span>"
        "<hr style='margin:4px 0;border:none;border-top:1px solid #ddd'>"
        f"<b>가시 커버율</b> {fmt(r['coverage_pct_current'], 1, '%')} · 사각 {fmt(r['blind_ha_current'], 2)}ha"
        f" · 500m 내 CCTV {fmt(r['cctv_count_500m'])}곳<br>"
        f"<b>배정 부이</b> {r['배정관측소']} ({r['노출그룹']}) · 파고 임계 {fmt(r['파고임계_m'], 1)}m"
        f" · 풍속 임계 {fmt(r['풍속임계_ms'], 1)}m/s<br>"
        f"<b>파랑노출 W</b> {fmt(r['W_파랑노출'], 3)} · <b>해안유형 위험 T</b> {fmt(r['T_유형위험'], 3)}<br>"
        f"<b>위험지수 R</b> {fmt(r['위험지수'], 3)} · "
        f"<b style='color:{GRADE_COLORS[r['위험등급']]}'>위험 {r['위험등급']}등급</b>"
        "</div>"
        for _, r in out.iterrows()
    ]
    return out


def interactive_map(seg, sites, obs, baseline: str = "original_360", top_n: int = 50) -> Path:
    sites_w, gdf_acc = load_accidents_and_classify_sites(baseline, top_n, sites)
    sd = pd.read_csv(SEG_CSV, encoding="utf-8-sig")[["segment_id", "배정관측소", "노출그룹", "W_파랑노출", "파고임계_m"]]
    sites_w = sites_w.merge(sd, on="segment_id", how="left")
    seg_d = segment_layer_data(seg)
    seg4326, sites4326, obs4326 = seg_d.to_crs(4326), sites_w.to_crs(4326), obs.to_crs(4326)
    m = folium.Map(location=[35.12, 129.02], zoom_start=11, tiles=None)

    carto_key = "eyJhbGciOiJIUzI1NiJ9.eyJhIjoiYWNfYmg2c28zZ2siLCJqdGkiOiJjYzJjMThmYmQwZTFjMThmOTY4YzJlNTBhZDliMjk4ZCIsImV4cCI6MTgyMzgzNzA0MH0.xqdQK2iIOz229nb1iQX75ehsPmxUy6H8ZKremXlc_Ps"
    carto_attr = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'

    # 1) CARTO Positron (밝은 회색 배경지도 — Vector GL로 렌더링)
    folium.TileLayer(
        tiles=f"https://basemaps.cartocdn.com/gl/positron-gl-style/style.json?key={carto_key}",
        attr=carto_attr,
        name="CARTO Positron (밝은 회색 지도)",
        max_zoom=20,
        control=True,
    ).add_to(m)

    # 2) CARTO Voyager (컬러 상세지도 — Vector GL로 렌더링)
    folium.TileLayer(
        tiles=f"https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json?key={carto_key}",
        attr=carto_attr,
        name="CARTO Voyager (컬러 상세지도)",
        max_zoom=20,
        control=True,
    ).add_to(m)

    # 해안선: 데이터는 하나, 색 기준(c_cov / c_grade / c_st / c_w)은 아래 버튼이 바꾼다
    seg_geo = folium.GeoJson(
        seg4326[["segment_id", "c_cov", "c_grade", "c_st", "c_w", "tip", "geometry"]],
        name="해안 구간 (가시 커버율·위험도·해양기상)",
        style_function=lambda f: {"color": f["properties"]["c_cov"], "weight": 4},
        highlight_function=lambda f: {"weight": 8},
        tooltip=folium.GeoJsonTooltip(["tip"], labels=False, sticky=True),
    )
    seg_geo.add_to(m)

    existing = folium.FeatureGroup(name="기존 CCTV(관측점 1,782곳 — 3분류)", show=False)
    for _, o in obs4326.iterrows():
        grp = str(o.get("ocean_view_group", "-"))
        dtl = str(o.get("ocean_view_detail", "-"))
        purp = str(o.get("purpose_original", "-"))
        cdist = round(float(o.get("coast_distance_m", 0.0)), 1)
        tip_obs = (
            f"<b>기존 CCTV ({o.get('integrated_id', '')})</b><br>"
            f"· 3분류: <b>{grp}</b><br>"
            f"· 세부기준: {dtl}<br>"
            f"· 설치목적: {purp} · 해안거리: {cdist}m"
        )
        folium.CircleMarker(
            [o.geometry.y, o.geometry.x],
            radius=3,
            color="#FFFFFF",
            weight=0.8,
            fill=True,
            fill_color="#0D47A1",
            fill_opacity=0.85,
            tooltip=tip_obs,
        ).add_to(existing)
    existing.add_to(m)

    # 연안사고: 사고 당시 기상상태로 양호 / 악기상을 나눠 두 레이어로
    acc_counts = {"양호": 0, "악기상": 0}
    if gdf_acc is not None and not gdf_acc.empty:
        minx, miny, maxx, maxy = seg.total_bounds
        pad = 3000
        acc_busan = gdf_acc.cx[minx - pad:maxx + pad, miny - pad:maxy + pad].to_crs(4326)
        acc_type_col = "발생유형" if "발생유형" in acc_busan.columns else "사고종류"
        wx = acc_busan["기상상태"].fillna("미상").astype(str)
        for label, sub, color, radius in [
            ("양호", acc_busan[wx.eq("양호")], ACC_OK_COLOR, 3.5),
            ("악기상", acc_busan[~wx.eq("양호")], ACC_BAD_COLOR, 5),
        ]:
            acc_counts[label] = len(sub)
            name = (f"연안사고 · 기상 양호 ({len(sub)}건)" if label == "양호"
                    else f"연안사고 · 악기상 (풍랑·태풍·황천·저시정 등, {len(sub)}건)")
            acc_fg = folium.FeatureGroup(name=name, show=True)
            for _, a in sub.iterrows():
                loc_str = str(a.get("사고위치내용", "-")).replace("`", "'")
                tip = (
                    f"<b>연안사고</b> ({a.get('발생년월일', '-')})<br>"
                    f"· 유형: {a.get(acc_type_col, '-')} ({a.get('발생위치', '-')})<br>"
                    f"· 사고 당시 기상: <b>{a.get('기상상태', '-')}</b><br>"
                    f"· 위치: {loc_str}"
                )
                folium.CircleMarker(
                    [a.geometry.y, a.geometry.x],
                    radius=radius,
                    color="#FFFFFF" if label == "악기상" else color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.9 if label == "악기상" else 0.55,
                    weight=1.2 if label == "악기상" else 0.8,
                    tooltip=tip,
                ).add_to(acc_fg)
            acc_fg.add_to(m)
    acc_busan_cnt = sum(acc_counts.values())

    type_counts = {}
    for dtype, (bg_color, border_color, text_color) in DIRECTION_STYLES.items():
        sub = sites4326[sites4326["camera_direction_type"] == dtype]
        type_counts[dtype] = len(sub)
        fg = folium.FeatureGroup(name=f"신규 후보지 {dtype} ({len(sub)}곳)", show=True)
        for _, s in sub.iterrows():
            c_type = s.get("coast_type", s.get("CAT_COA", "-"))
            w_val = s.get("added_weight", None)
            w_str = f" · 가중치 +{w_val}" if pd.notna(w_val) else ""
            grade = s.get("위험등급")
            grade_str = (f"<b style='color:{GRADE_COLORS.get(int(grade), '#333')}'>{int(grade)}등급</b>"
                         if pd.notna(grade) else "–")
            tooltip_html = (
                f"<div style='font-size:12px;line-height:1.4'>"
                f"<b>#{int(s['rank'])} {s['SGG_NAM']}</b> ({s.get('segment_id', '')})<br>"
                f"· 추가 가시면적: <b>+{s['added_ha']}ha</b>{w_str}<br>"
                f"· 해안유형: {c_type}<br>"
                f"· 배정 부이: {s.get('배정관측소', '-')} ({s.get('노출그룹', '-')}) · 파고 임계 {fmt(s.get('파고임계_m'), 1)}m<br>"
                f"· 파랑노출 W {fmt(s.get('W_파랑노출'), 3)} · 위험지수 R {fmt(s.get('risk_index'), 3)} · 위험 {grade_str}<br>"
                f"· 반경 500m 연안사고: <b>{int(s['acc_count_500m'])}건</b> (고위험·항계내 {int(s['severe_acc_500m'])}건)<br>"
                f"· 촬영방향 제안: <span style='color:{bg_color};font-weight:bold'>{dtype}</span>"
                f"</div>"
            )
            folium.Marker(
                [s.geometry.y, s.geometry.x],
                tooltip=folium.Tooltip(tooltip_html, sticky=True),
                icon=folium.DivIcon(
                    html=(
                        f"<div style='background:{bg_color};color:{text_color};"
                        f"border:2px solid {border_color};border-radius:50%;"
                        f"box-shadow:0 1px 4px rgba(0,0,0,0.45);"
                        f"width:22px;height:22px;font-size:10px;font-weight:bold;"
                        f"text-align:center;line-height:18px'>{int(s['rank'])}</div>"
                    )
                ),
            ).add_to(fg)
        fg.add_to(m)

    # 해안선 색 기준별 범례 (버튼을 누르면 이 내용으로 바뀜)
    def sw(color: str, label: str, n: int | None = None) -> str:
        cnt = f" <span style='color:#888'>({n:,})</span>" if n is not None else ""
        return (f"<div><span style='display:inline-block;width:18px;height:4px;background:{color};"
                f"vertical-align:middle;margin-right:6px;'></span>{label}{cnt}</div>")

    vc = lambda col: seg_d[col].value_counts()  # noqa: E731
    cls_n = seg_d.loc[~seg_d["island"], "class"].value_counts()
    legends = {
        "cov": ("해안 구간 가시 커버율 (기존 CCTV 3분류 반영)",
                "".join(sw(c, l, int(cls_n.get(i, 0))) for i, (c, l) in enumerate(zip(COLORS, LABELS)))
                + sw(ISLAND_COLOR, "섬·제외 구간", int(seg_d["island"].sum()))),
        "grade": ("위험등급 (파랑 = 덜 위험 · 빨강 = 고위험)",
                  "".join(sw(GRADE_COLORS[g], l, int(vc("위험등급").get(g, 0))) for g, l in [
                      (2, "2등급 · R 0.27–0.34 (가장 낮음)"), (3, "3등급 · R 0.47–0.55"),
                      (4, "4등급 · R 0.67–0.69 (고위험)"), (5, "5등급 · R 0.92–1.00 (가장 위험)")])),
        "st": ("배정 해양기상부이 (구간별 파고 임계 적용)",
               "".join(sw(STATION_COLORS[s], f"{s} 부이 · {e} · 파고 임계 {h}m", int(vc("배정관측소").get(s, 0)))
                       for s, e, h in [("기장", "외해", "1.0"), ("오륙도", "외해", "1.0"), ("다대포", "내만", "0.7")])),
        "w": ("파랑노출 W (배정 부이 값 · 세 단계)",
              "".join(sw(c, l, n) for c, l, n in [
                  (W_COLORS[0][1], "0.249 · 다대포 (내만)", int((seg_d["W_파랑노출"] < 0.5).sum())),
                  (W_COLORS[1][1], "0.941 · 오륙도 (외해)", int(seg_d["W_파랑노출"].between(0.5, 0.99).sum())),
                  (W_COLORS[2][1], "1.000 · 기장 (외해)", int((seg_d["W_파랑노출"] > 0.99).sum()))])),
    }

    legend_html = f"""
    <div style="position: fixed; bottom: 24px; left: 24px; z-index: 9999;
                background: rgba(255,255,255,0.94); padding: 12px 14px;
                border: 1px solid #ccc; border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.18);
                font-family: 'NanumGothic', sans-serif; font-size: 12px; line-height: 1.5;">
      <div style="font-weight: bold; font-size: 13px; margin-bottom: 6px;">
        신규 후보지 상위 {top_n}대 촬영방향 3분류 (위험도 가중 배치)
      </div>
      <div><span style="display:inline-block;width:12px;height:12px;background:#D50000;border:2px solid #FFEB3B;border-radius:50%;vertical-align:middle;margin-right:6px;"></span>① 해안 필수 직시형 (바다·테트라포드 고정) <b>({type_counts.get('① 해안 필수 직시형 (바다·테트라포드 고정)', 0)}곳)</b></div>
      <div><span style="display:inline-block;width:12px;height:12px;background:#FF9100;border:2px solid #212121;border-radius:50%;vertical-align:middle;margin-right:6px;"></span>② 해안·내륙 복합형 (PTZ 양방향 전환) <b>({type_counts.get('② 해안·내륙 복합형 (PTZ 양방향 전환)', 0)}곳)</b></div>
      <div><span style="display:inline-block;width:12px;height:12px;background:#00C853;border:2px solid #999;border-radius:50%;vertical-align:middle;margin-right:6px;"></span>③ 내륙·진입로 감시형 (해안 직시 불필요) <b>({type_counts.get('③ 내륙·진입로 감시형 (해안 직시 불필요)', 0)}곳)</b></div>
      <div style="margin-top:4px;"><span style="display:inline-block;width:8px;height:8px;background:{ACC_OK_COLOR};border-radius:50%;vertical-align:middle;margin-right:8px;margin-left:1px;"></span>연안사고 · 기상 양호 ({acc_counts['양호']:,}건)</div>
      <div><span style="display:inline-block;width:10px;height:10px;background:{ACC_BAD_COLOR};border:1px solid #fff;box-shadow:0 0 1px #555;border-radius:50%;vertical-align:middle;margin-right:8px;"></span>연안사고 · 악기상 ({acc_counts['악기상']:,}건)</div>
      <div style="margin-top:3px;"><span style="display:inline-block;width:9px;height:9px;background:#0D47A1;border:1px solid #FFFFFF;box-shadow:0 0 1px #555;border-radius:50%;vertical-align:middle;margin-right:8px;"></span>기존 CCTV (1,782곳: 확실665·조건부867·제외250)</div>
      <hr style="margin: 7px 0; border: none; border-top: 1px solid #e0e0e0;">
      <div id="seg-legend-title" style="font-weight: bold; margin-bottom: 4px;">{legends['cov'][0]}</div>
      <div id="seg-legend-body">{legends['cov'][1]}</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    # 해안선 색 기준 전환 버튼 (줌 버튼 오른쪽)
    buttons = [("cov", "가시 커버율"), ("grade", "위험등급"), ("st", "배정 부이"), ("w", "파랑노출 W")]
    switch_html = (
        "<div id='seg-mode' style=\"position:fixed;top:12px;left:60px;z-index:9999;background:rgba(255,255,255,0.96);"
        "border:1px solid #ccc;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.18);padding:6px 8px;"
        "font-family:'NanumGothic',sans-serif;font-size:12px;display:flex;gap:4px;align-items:center;flex-wrap:wrap\">"
        "<b style='margin-right:4px'>해안선 색 기준</b>"
        + "".join(
            f"<button type='button' data-mode='{k}' aria-pressed='{str(k == 'cov').lower()}' "
            f"style='font:inherit;border:1px solid #bbb;border-radius:6px;padding:4px 9px;cursor:pointer;"
            f"background:{'#263238' if k == 'cov' else '#fff'};color:{'#fff' if k == 'cov' else '#263238'}'>{label}</button>"
            for k, label in buttons)
        + "</div>"
    )
    m.get_root().html.add_child(folium.Element(switch_html))
    colkey = {"cov": "c_cov", "grade": "c_grade", "st": "c_st", "w": "c_w"}
    # folium이 지도·레이어 변수를 이 스크립트보다 뒤에 선언하므로 문서 로딩이 끝난 뒤 실행
    switch_js = f"""
    document.addEventListener('DOMContentLoaded', function () {{
      var layer = {seg_geo.get_name()};
      var colkey = {json.dumps(colkey)};
      var legends = {json.dumps(legends, ensure_ascii=False)};
      var mode = "cov";
      layer.options.style = function (f) {{ return {{color: f.properties[colkey[mode]], weight: 4}}; }};
      document.querySelectorAll('#seg-mode button').forEach(function (b) {{
        b.addEventListener('click', function () {{
          mode = b.dataset.mode;
          layer.setStyle(layer.options.style);
          document.getElementById('seg-legend-title').textContent = legends[mode][0];
          document.getElementById('seg-legend-body').innerHTML = legends[mode][1];
          document.querySelectorAll('#seg-mode button').forEach(function (x) {{
            var on = x === b;
            x.setAttribute('aria-pressed', on);
            x.style.background = on ? '#263238' : '#fff';
            x.style.color = on ? '#fff' : '#263238';
          }});
        }});
      }});
    }});
    """
    m.get_root().script.add_child(folium.Element(switch_js))

    folium.LayerControl(collapsed=False).add_to(m)
    path = MAP_DIR / "busan_blind_and_new_sites_기상위험도.html"
    m.save(path)

    # leaflet.js가 먼저 로드된 뒤 MapLibre GL + leaflet-maplibre-gl 플러그인이 로드되도록 </head> 직전에 삽입하고,
    # style.json URL을 사용하는 L.tileLayer 호출을 MapLibre GL 벡터 레이어(L.maplibreGL)로 변환
    import re
    html_txt = path.read_text(encoding="utf-8")
    maplibre_scripts = (
        '    <link href="https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet" />\n'
        '    <script src="https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>\n'
        '    <script src="https://cdn.jsdelivr.net/npm/@maplibre/maplibre-gl-leaflet@0.0.22/leaflet-maplibre-gl.js"></script>\n'
        '</head>'
    )
    html_txt = html_txt.replace("</head>", maplibre_scripts, 1)
    html_txt = re.sub(
        r'L\.tileLayer\(\s*"(https://basemaps\.cartocdn\.com/gl/[^"]+)"\s*,\s*\{',
        r'L.maplibreGL({\n  "style": "\1",\n  "pane": "tilePane",',
        html_txt,
    )
    path.write_text(html_txt, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="original_360",
                        choices=["conservative_after_rotation", "original_360"])
    parser.add_argument("--top", type=int, default=50)
    args = parser.parse_args()
    seg, sites, obs = load(args.baseline, args.top)
    print("saved", interactive_map(seg, sites, obs, args.baseline, args.top))


if __name__ == "__main__":
    main()
