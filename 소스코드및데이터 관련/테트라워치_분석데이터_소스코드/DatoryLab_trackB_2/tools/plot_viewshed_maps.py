#!/usr/bin/env python3
"""Draw blind-area and new-site maps (static PNG + interactive HTML) from viewshed outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.lines import Line2D

matplotlib.use("Agg")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from site_exclusions import excluded_mask  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]
VS_DIR = PROJECT / "outputs" / "viewshed"
MAP_DIR = VS_DIR / "maps"
BINS = [-0.1, 0, 25, 50, 75, 100]
LABELS = ["0% (완전 사각)", "0–25%", "25–50%", "50–75%", "75–100%"]
COLORS = ["#b2182b", "#ef8a62", "#fddbc7", "#92c5de", "#2166ac"]
ISLAND_COLOR = "#9e9e9e"
ZOOMS = {"강서·사하": ["부산광역시 강서구", "부산광역시 사하구"], "기장": ["부산광역시 기장군"]}


def set_korean_font() -> None:
    # Colab: apt로 설치한 나눔글꼴을 캐시와 무관하게 등록
    for path in Path("/usr/share/fonts/truetype/nanum").glob("*.ttf"):
        font_manager.fontManager.addfont(str(path))
    for name in ("AppleGothic", "NanumGothic", "Malgun Gothic", "Noto Sans CJK KR"):
        if any(f.name == name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False


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


def draw(ax, seg, sites, obs, label_top: int) -> None:
    cmap = ListedColormap(COLORS)
    norm = BoundaryNorm(range(len(COLORS) + 1), cmap.N)
    obs.plot(ax=ax, color="#666666", markersize=2, alpha=0.5, zorder=1)
    land = seg[~seg["island"]]
    land.plot(ax=ax, column="class", cmap=cmap, norm=norm, linewidth=1.6, zorder=2)
    if seg["island"].any():
        seg[seg["island"]].plot(ax=ax, color=ISLAND_COLOR, linewidth=1.4, zorder=2)
    sites.plot(ax=ax, color="#ffd700", edgecolor="black", marker="*", markersize=140, linewidth=0.6, zorder=3)
    for _, s in sites[sites["rank"] <= label_top].iterrows():
        ax.annotate(str(s["rank"]), (s.geometry.x, s.geometry.y), xytext=(4, 4),
                    textcoords="offset points", fontsize=8, weight="bold", zorder=4)
    ax.set_axis_off()


def legend(ax, top_n: int) -> None:
    handles = [Line2D([0], [0], color=c, lw=3, label=l) for c, l in zip(COLORS, LABELS)]
    handles += [
        Line2D([0], [0], color=ISLAND_COLOR, lw=3, label="섬·설치 제외 구간 — 설치 대상 아님"),
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#ffd700", markeredgecolor="black",
               markersize=13, label=f"신규 설치 우선순위 상위 {top_n}"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#666666", markersize=4, label="기존 CCTV(관측점)"),
    ]
    ax.legend(handles=handles, title="구간 가시 커버율", loc="lower right", fontsize=8, title_fontsize=9, frameon=True)


def static_maps(seg, sites, obs, top_n: int, baseline_label: str) -> list[Path]:
    MAP_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    fig, ax = plt.subplots(figsize=(14, 10))
    draw(ax, seg, sites, obs, label_top=10)
    legend(ax, top_n)
    land = seg[~seg["island"]]
    blind = (land["coverage_pct_current"] == 0).sum()  # 육지부, 면적 0(NaN) 구간 제외
    ax.set_title(f"부산 해안 CCTV 가시 커버율과 신규 설치 우선지점 (상위 {top_n}대)\n"
                 f"구간 색: 기존 CCTV 3분류(확실665·조건부867·제외250) 가시 커버율, 육지부 완전 사각 {blind:,}/{len(land):,} · 별: {baseline_label} 기준 배치", fontsize=13)
    path = MAP_DIR / "busan_blind_and_new_sites.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)

    for name, districts in ZOOMS.items():
        s = seg[seg["SGG_NAM"].isin(districts)]
        xmin, ymin, xmax, ymax = s.total_bounds
        pad = 800
        fig, ax = plt.subplots(figsize=(12, 10))
        draw(ax, s, sites[sites["SGG_NAM"].isin(districts)], obs.cx[xmin - pad:xmax + pad, ymin - pad:ymax + pad], label_top=top_n)
        ax.set_xlim(xmin - pad, xmax + pad)
        ax.set_ylim(ymin - pad, ymax + pad)
        legend(ax, top_n)
        ax.set_title(f"{name} 확대 — 사각지대와 신규 설치 우선지점", fontsize=13)
        path = MAP_DIR / f"zoom_{name.replace('·', '_')}.png"
        fig.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)

    curve = pd.read_csv(VS_DIR / "new_sites_curve.csv", encoding="utf-8-sig")
    fig, ax = plt.subplots(figsize=(9, 5.5))
    names = {"conservative_after_rotation": "보수적 (3분류+고정60° 방향조정 후)", "original_360": "3분류 기본 반영 (확실665·조건부867·제외250)"}
    for key, g in curve.groupby("baseline"):
        ax.plot(g["new_cameras"], g["coverage_pct"], marker="o", label=names.get(key, key))
    ax.set_xlabel("신규 설치 대수")
    ax.set_ylabel("해안 대상구역 가시 커버율 (%)")
    ax.set_title("신규 CCTV 대수별 커버율 (시나리오 ②)")
    ax.grid(alpha=0.3)
    ax.legend()
    path = MAP_DIR / "new_sites_curve.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)
    return paths


def trackA_map(seg, obs, baseline: str, top_n: int) -> Path | None:
    """트랙 D 설치후보 v4(위험등급 4·5, 설치 대상, 보수적 커버율 0%) + 위험도 가중 배치 상위 N."""
    cand_path = PROJECT / "outputs/trackD/cctv_candidates_v4.csv"
    layer = "new_sites_ranked_trackB_weights"
    if not cand_path.exists():
        return None
    cand = pd.read_csv(cand_path, encoding="utf-8-sig")[["segment_id", "위험등급"]]
    cand_seg = seg.merge(cand, on="segment_id")
    sites = gpd.read_file(VS_DIR / "viewshed_results.gpkg", layer=layer)
    sites = sites[(sites["baseline"] == baseline) & (sites["rank"] <= top_n)]
    grade_colors = {5: "#b2182b", 4: "#ef8a62"}

    south = cand_seg[cand_seg["SGG_NAM"].str.contains("남구|서구|영도구|동구|중구")]
    fig, axes = plt.subplots(1, 2, figsize=(20, 10), gridspec_kw={"width_ratios": [1, 1.2]})
    for ax, bounds in zip(axes, (None, south.total_bounds)):
        seg[~seg["island"]].plot(ax=ax, color="#d0d0d0", linewidth=0.8, zorder=1)
        seg[seg["island"]].plot(ax=ax, color=ISLAND_COLOR, linewidth=0.8, linestyle=":", zorder=1)
        obs.plot(ax=ax, color="#888888", markersize=1, alpha=0.3, zorder=1)
        for grade, color in grade_colors.items():
            part = cand_seg[cand_seg["위험등급"] == grade]
            if not part.empty:
                part.plot(ax=ax, color=color, linewidth=4 if bounds is not None else 3, zorder=2)
        sites.plot(ax=ax, color="#ffd700", edgecolor="black", marker="*",
                   markersize=220 if bounds is not None else 110, linewidth=0.6, zorder=3)
        label_top = top_n if bounds is not None else 10
        for _, s in sites[sites["rank"] <= label_top].iterrows():
            if bounds is None or (bounds[0] <= s.geometry.x <= bounds[2] and bounds[1] <= s.geometry.y <= bounds[3]):
                ax.annotate(str(s["rank"]), (s.geometry.x, s.geometry.y), xytext=(5, 5),
                            textcoords="offset points", fontsize=8, weight="bold", zorder=4)
        if bounds is not None:
            pad = 600
            ax.set_xlim(bounds[0] - pad, bounds[2] + pad)
            ax.set_ylim(bounds[1] - pad, bounds[3] + pad)
            ax.set_title("남구·영도구·서구·동구·중구 확대", fontsize=12)
        ax.set_axis_off()
    handles = [Line2D([0], [0], color=c, lw=3, label=f"설치후보(사각) 위험등급 {g}") for g, c in grade_colors.items()]
    handles += [
        Line2D([0], [0], color="#d0d0d0", lw=2, label="그 외 육지부 해안"),
        Line2D([0], [0], color=ISLAND_COLOR, lw=2, linestyle=":", label="섬·설치 제외 구간 — 설치 대상 아님"),
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#ffd700", markeredgecolor="black",
               markersize=13, label=f"위험도 가중 배치 상위 {top_n}"),
    ]
    axes[0].legend(handles=handles, loc="lower right", fontsize=9, frameon=True)
    fig.suptitle(f"설치후보 {len(cand_seg)}구간(위험등급 4·5, 설치 대상, 가시 커버율 0%)과 "
                 f"위험도 가중 신규 배치 상위 {top_n}대 — 가중치: 트랙 D trackB_weights(위험지수, 섬·설치 제외 구간 0)", fontsize=14)
    path = MAP_DIR / "trackA_candidates_and_risk_sites.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return path


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

    out_csv = VS_DIR / "top50_sites_direction_classified.csv"
    sites_w.drop(columns="geometry").to_csv(out_csv, encoding="utf-8-sig", index=False)
    return sites_w, gdf_acc


def interactive_map(seg, sites, obs, baseline: str = "original_360", top_n: int = 50) -> Path:
    sites_w, gdf_acc = load_accidents_and_classify_sites(baseline, top_n, sites)
    seg4326, sites4326, obs4326 = seg.to_crs(4326), sites_w.to_crs(4326), obs.to_crs(4326)
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

    seg4326 = seg4326.assign(color=seg4326["class"].map(dict(enumerate(COLORS))).fillna(COLORS[0]))
    seg4326.loc[seg4326["island"], "color"] = ISLAND_COLOR
    folium.GeoJson(
        seg4326[["segment_id", "SGG_NAM", "coverage_pct_current", "blind_ha_current", "color", "geometry"]],
        name="해안 구간 가시 커버율",
        style_function=lambda f: {"color": f["properties"]["color"], "weight": 4},
        tooltip=folium.GeoJsonTooltip(
            ["segment_id", "SGG_NAM", "coverage_pct_current", "blind_ha_current"],
            aliases=["구간", "구·군", "커버율(%)", "사각 면적(ha)"],
        ),
    ).add_to(m)

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

    acc_busan_cnt = 0
    if gdf_acc is not None and not gdf_acc.empty:
        minx, miny, maxx, maxy = seg.total_bounds
        pad = 3000
        acc_busan = gdf_acc.cx[minx - pad:maxx + pad, miny - pad:maxy + pad].to_crs(4326)
        acc_busan_cnt = len(acc_busan)
        acc_fg = folium.FeatureGroup(name=f"행안부 연안사고 발생지점 ({acc_busan_cnt}건)", show=True)
        acc_type_col = "발생유형" if "발생유형" in acc_busan.columns else "사고종류"
        for _, a in acc_busan.iterrows():
            loc_str = str(a.get("사고위치내용", "-")).replace("`", "'")
            tip = (
                f"<b>연안사고</b> ({a.get('발생년월일', '-')})<br>"
                f"· 유형: {a.get(acc_type_col, '-')} ({a.get('발생위치', '-')})<br>"
                f"· 위치: {loc_str}"
            )
            folium.CircleMarker(
                [a.geometry.y, a.geometry.x],
                radius=3.5,
                color="#7E57C2",
                fill=True,
                fill_color="#7E57C2",
                fill_opacity=0.45,
                weight=0.7,
                tooltip=tip,
            ).add_to(acc_fg)
        acc_fg.add_to(m)

    type_counts = {}
    for dtype, (bg_color, border_color, text_color) in DIRECTION_STYLES.items():
        sub = sites4326[sites4326["camera_direction_type"] == dtype]
        type_counts[dtype] = len(sub)
        fg = folium.FeatureGroup(name=f"신규 후보지 {dtype} ({len(sub)}곳)", show=True)
        for _, s in sub.iterrows():
            c_type = s.get("coast_type", s.get("CAT_COA", "-"))
            w_val = s.get("added_weight", None)
            w_str = f" · 가중치 +{w_val}" if pd.notna(w_val) else ""
            tooltip_html = (
                f"<div style='font-size:12px;line-height:1.4'>"
                f"<b>#{int(s['rank'])} {s['SGG_NAM']}</b> ({s.get('segment_id', '')})<br>"
                f"· 추가 가시면적: <b>+{s['added_ha']}ha</b>{w_str}<br>"
                f"· 해안유형: {c_type}<br>"
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
      <div style="margin-top:4px;"><span style="display:inline-block;width:10px;height:10px;background:#7E57C2;border-radius:50%;opacity:0.7;vertical-align:middle;margin-right:8px;"></span>행안부 연안사고 발생지점 ({acc_busan_cnt}건)</div>
      <div style="margin-top:3px;"><span style="display:inline-block;width:9px;height:9px;background:#0D47A1;border:1px solid #FFFFFF;box-shadow:0 0 1px #555;border-radius:50%;vertical-align:middle;margin-right:8px;"></span>기존 CCTV (1,782곳: 확실665·조건부867·제외250)</div>
      <hr style="margin: 7px 0; border: none; border-top: 1px solid #e0e0e0;">
      <div style="font-weight: bold; margin-bottom: 4px;">해안 구간 가시 커버율 (기존 CCTV 3분류 반영)</div>
      <div><span style="display:inline-block;width:18px;height:4px;background:#b2182b;vertical-align:middle;margin-right:6px;"></span>0% (완전 사각) &nbsp;
           <span style="display:inline-block;width:18px;height:4px;background:#ef8a62;vertical-align:middle;margin-right:6px;"></span>0–25% &nbsp;
           <span style="display:inline-block;width:18px;height:4px;background:#fddbc7;vertical-align:middle;margin-right:6px;"></span>25–50%</div>
      <div><span style="display:inline-block;width:18px;height:4px;background:#92c5de;vertical-align:middle;margin-right:6px;"></span>50–75% &nbsp;
           <span style="display:inline-block;width:18px;height:4px;background:#2166ac;vertical-align:middle;margin-right:6px;"></span>75–100% &nbsp;
           <span style="display:inline-block;width:18px;height:4px;background:#9e9e9e;vertical-align:middle;margin-right:6px;"></span>섬·제외 구간</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    folium.LayerControl(collapsed=False).add_to(m)
    path = MAP_DIR / "busan_blind_and_new_sites.html"
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
    set_korean_font()
    label = "보수적(3분류+고정60° 방향조정 후)" if args.baseline == "conservative_after_rotation" else "3분류 기본 반영(확실665·조건부867·제외250)"
    seg, sites, obs = load(args.baseline, args.top)
    paths = static_maps(seg, sites, obs, args.top, label) + [interactive_map(seg, sites, obs, args.baseline, args.top)]
    paths.append(trackA_map(seg, obs, args.baseline, args.top))
    for p in filter(None, paths):
        print("saved", p)


if __name__ == "__main__":
    main()
