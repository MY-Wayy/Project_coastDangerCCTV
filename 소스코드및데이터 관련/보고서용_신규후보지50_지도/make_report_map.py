#!/usr/bin/env python3
"""보고서 첨부용 정적 지도: 해안 가시 커버율 + 연안사고 + 기존 CCTV + 신규 후보지 1~50위 번호.

기준 웹사이트: 해안사각지대_기상위험도_통합지도/outputs/busan_blind_and_new_sites_기상위험도.html
- 같은 데이터·같은 색을 쓰고, 인쇄용으로 아이콘을 작게 줄였다
- 후보지가 몰린 두 구역(A 원도심, B 기장)은 확대 지도로 따로 보여 1~50위 번호가 모두 읽히게 했다
- 그 밖에서 번호 원이 겹치면 원을 옆으로 빼고 가는 선으로 실제 위치와 잇는다
- 배경지도: Esri World Light Gray Canvas (바탕 + 지명). 웹사이트의 CARTO 타일은 이제 API 키가 필요해 대체

원본 폴더(통합완료 데이터 관련/, 해안사각지대_기상위험도_통합지도/)는 읽기만 한다.
확장판의 load()·segment_layer_data()만 가져다 쓰고, 결과 CSV를 다시 쓰는 함수는 부르지 않는다.

필요 패키지:  pip install geopandas pyogrio folium pandas matplotlib contextily
실행:  python make_report_map.py   → 같은 폴더에 PNG(300dpi)·PDF 생성
"""

from __future__ import annotations

import sys
from pathlib import Path

import contextily as cx
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
WEB = HERE.parent / "해안사각지대_기상위험도_통합지도"
sys.path.insert(0, str(WEB / "tools"))
from plot_blind_map_weather import (  # noqa: E402
    ACC_BAD_COLOR, ACC_OK_COLOR, COLORS, DIRECTION_STYLES, ISLAND_COLOR, LABELS, PROJECT, VS_DIR,
    load, segment_layer_data,
)

OUT_STEM = "map_신규후보지50_촬영방향_보고서용"
DIRECTION_CSV = WEB / "outputs" / "top50_sites_direction_classified.csv"
ACC_CSV = PROJECT / "부산전체_행정안전부_연안사고.csv"
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
ATTRIBUTION = "배경지도: Esri World Light Gray Canvas\nEsri, HERE, Garmin,\n© OpenStreetMap contributors"
CCTV_COLOR = "#0D47A1"
WEB_CRS = 3857

# 확대 구역 (EPSG:5186 기준 범위)
INSETS = {
    "A": ("원도심 (중·동·영도·남구)", (385_700, 276_500, 394_100, 284_900)),
    "B": ("기장 (일광~장안)", (401_700, 289_000, 410_500, 306_900)),
}
MAIN_EXTENT = (364_500, 268_500, 412_500, 308_500)

FONT_DIR = Path.home() / "Library" / "Fonts"
for name in ("Pretendard-Regular.otf", "Pretendard-SemiBold.otf", "Pretendard-Bold.otf"):
    font_manager.fontManager.addfont(str(FONT_DIR / name))
plt.rcParams.update({"font.family": "Pretendard", "axes.unicode_minus": False})
CM = 1 / 2.54
INK, MUTED = "#111827", "#4B5563"
SHORT_TYPE = {
    "①": "① 해안 필수 직시형 (바다·테트라포드 고정)",
    "②": "② 해안·내륙 복합형 (PTZ 양방향 전환)",
    "③": "③ 내륙·진입로 감시형 (해안 직시 불필요)",
}


def read_accidents(seg: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """웹사이트와 같은 규칙: 좌표계 추정 → 해안 범위 ±3km → 기상상태 '양호' / 그 외(악기상)."""
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            df = pd.read_csv(ACC_CSV, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    df = df.rename(columns={"x": "X좌표", "y": "Y좌표", "wether_sn": "기상상태"})
    df["X좌표"] = pd.to_numeric(df["X좌표"], errors="coerce")
    df["Y좌표"] = pd.to_numeric(df["Y좌표"], errors="coerce")
    df = df.dropna(subset=["X좌표", "Y좌표"])
    src = "EPSG:3857" if df["X좌표"].median() > 2_000_000 else "EPSG:5179"
    acc = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["X좌표"], df["Y좌표"]), crs=src).to_crs(5186)
    minx, miny, maxx, maxy = seg.total_bounds
    acc = acc.cx[minx - 3000:maxx + 3000, miny - 3000:maxy + 3000].copy()
    acc["bad"] = ~acc["기상상태"].fillna("미상").astype(str).eq("양호")
    return acc


def read_sites() -> gpd.GeoDataFrame:
    sites = gpd.read_file(VS_DIR / "viewshed_results.gpkg", layer="new_sites_ranked_trackB_weights")
    sites = sites[(sites["baseline"] == "original_360") & (sites["rank"] <= 50)]
    types = pd.read_csv(DIRECTION_CSV, encoding="utf-8-sig")[["candidate_id", "camera_direction_type"]]
    sites = sites.merge(types, on="candidate_id", how="left", validate="1:1")
    assert sites["camera_direction_type"].notna().all() and len(sites) == 50
    return sites.to_crs(5186).sort_values("rank")


def to_web(bounds):
    x0, y0, x1, y1 = bounds
    return gpd.GeoSeries(gpd.points_from_xy([x0, x1], [y0, y1]), crs=5186).to_crs(WEB_CRS).total_bounds


def place_bubbles(xy: np.ndarray, d: float, bounds) -> np.ndarray:
    """순위 순서로 번호 원을 놓고, 앞서 놓인 원과 겹치면 8방향·거리를 늘려가며 빈 자리를 찾는다."""
    x0, y0, x1, y1 = bounds
    placed = []
    angles = np.radians([45, 135, 315, 225, 90, 270, 0, 180])
    for x, y in xy:
        best = None
        for ring in (0, 1.15, 1.7, 2.3, 2.9, 3.5):
            for a in (angles if ring else [0.0]):
                px, py = x + ring * d * np.cos(a), y + ring * d * np.sin(a)
                inside = x0 + d / 2 < px < x1 - d / 2 and y0 + d / 2 < py < y1 - d / 2
                if inside and all(np.hypot(px - qx, py - qy) >= d * 1.04 for qx, qy in placed):
                    best = (px, py)
                    break
            if best:
                break
        placed.append(best or (x, y))
    return np.array(placed)


def draw_layers(ax, seg, acc, obs, lw: float, acc_s: float, cctv_s: float) -> None:
    acc_ok, acc_bad = acc[~acc["bad"]], acc[acc["bad"]]
    ax.scatter(acc_ok.geometry.x, acc_ok.geometry.y, s=acc_s, c=ACC_OK_COLOR, alpha=0.55, lw=0, zorder=3)
    ax.scatter(acc_bad.geometry.x, acc_bad.geometry.y, s=acc_s * 1.6, c=ACC_BAD_COLOR, alpha=0.9,
               edgecolors="white", linewidths=0.25, zorder=3)
    ax.scatter(obs.geometry.x, obs.geometry.y, s=cctv_s, c=CCTV_COLOR, alpha=0.8, lw=0, zorder=4)
    seg.plot(ax=ax, color=seg["c_cov"], linewidth=lw, zorder=5)
    ax.set_xlabel("")  # geopandas가 좌표계 축 이름(Easting/Northing)을 붙이므로 지운다
    ax.set_ylabel("")


def draw_sites(ax, sites, size_mm: float, font: float, bounds, mm_to_data: float, numbered=None) -> None:
    """numbered: 번호를 다는 후보지 마스크 (없으면 전부). 번호를 안 다는 곳은 작은 점만."""
    numbered = np.ones(len(sites), bool) if numbered is None else numbered
    xy = np.c_[sites.geometry.x, sites.geometry.y]
    d = size_mm * mm_to_data
    pos = np.full_like(xy, np.nan)
    pos[numbered] = place_bubbles(xy[numbered], d, bounds)
    ms = size_mm / 25.4 * 72  # 지름(pt)
    for (x, y), (px, py), num, t, show in zip(xy, pos, sites["rank"], sites["camera_direction_type"], numbered):
        bg, edge, text = DIRECTION_STYLES[t]
        if not show:
            ax.plot(x, y, "o", ms=ms * 0.45, mfc=bg, mec="white", mew=0.4, zorder=7)
            continue
        if np.hypot(px - x, py - y) > 1e-6:  # 옮긴 원: 실제 위치 점 + 연결선
            ax.plot([x, px], [y, py], color="#374151", lw=0.45, zorder=6)
            ax.plot(x, y, "o", ms=ms * 0.28, mfc=bg, mec="#111", mew=0.3, zorder=7)
        ax.plot(px, py, "o", ms=ms, mfc=bg, mec=edge, mew=0.7, zorder=8)
        ax.text(px, py, str(int(num)), fontsize=font, fontweight="bold", color=text,
                ha="center", va="center_baseline", zorder=9)


def setup_map(ax, bounds5186, zoom: int, label_zoom: int):
    """바탕은 zoom, 지명은 한 단계 낮은 label_zoom으로 받아 인쇄에서도 지명 글씨가 읽히게 한다."""
    b = to_web(bounds5186)
    ax.set_xlim(b[0], b[2])
    ax.set_ylim(b[1], b[3])
    cx.add_basemap(ax, source=ESRI.format("Base"), zoom=zoom, crs=f"EPSG:{WEB_CRS}", attribution=False)
    cx.add_basemap(ax, source=ESRI.format("Reference"), zoom=label_zoom, crs=f"EPSG:{WEB_CRS}",
                   attribution=False)
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_edgecolor("#9CA3AF")
        s.set_linewidth(0.6)
    return b


def mm_scale(ax, b) -> float:
    """데이터 단위/mm (EPSG:3857)."""
    w_mm = ax.get_position().width * ax.figure.get_figwidth() * 25.4
    return (b[2] - b[0]) / w_mm


def legend(ax, seg, acc, obs, sites) -> None:
    ax.axis("off")
    y = 0.99
    def head(t):
        nonlocal y
        ax.text(0.0, y, t, fontsize=7.5, fontweight="bold", color=INK, va="top", transform=ax.transAxes)
        y -= 0.052
    def row(handle, label):
        nonlocal y
        handle(0.06, y - 0.012)
        ax.text(0.15, y, label, fontsize=6.6, color=INK, va="top", transform=ax.transAxes)
        y -= 0.043
    line = lambda c: (lambda x, yy: ax.add_line(Line2D([x - 0.05, x + 0.05], [yy, yy], color=c, lw=1.8,  # noqa: E731
                                                       transform=ax.transAxes)))
    dot = lambda c, s, ec="none": (lambda x, yy: ax.scatter([x], [yy], s=s, c=c, edgecolors=ec,  # noqa: E731
                                                          linewidths=0.4, transform=ax.transAxes))

    land = seg[~seg["island"]]
    n_cls = land["class"].value_counts()
    head("해안 가시 커버율 (기존 CCTV 3분류)")
    for i, (c, lab) in enumerate(zip(COLORS, LABELS)):
        row(line(c), f"{lab} ({int(n_cls.get(i, 0)):,}구간)")
    row(line(ISLAND_COLOR), f"섬·설치 제외 ({int(seg['island'].sum()):,}구간)")
    y -= 0.02
    head("연안사고 · 기존 CCTV")
    row(dot(ACC_OK_COLOR, 7), f"연안사고 · 기상 양호 ({int((~acc['bad']).sum()):,}건)")
    row(dot(ACC_BAD_COLOR, 11, "white"), f"연안사고 · 악기상 ({int(acc['bad'].sum()):,}건)")
    row(dot(CCTV_COLOR, 5), f"기존 CCTV ({len(obs):,}곳)")
    y -= 0.02
    head("신규 후보지 (숫자 = 우선순위)")
    for key, t in SHORT_TYPE.items():
        bg, edge, text = DIRECTION_STYLES[t]
        n = int((sites["camera_direction_type"] == t).sum())
        label = t.split(" (")[0][2:]
        def h(x, yy, bg=bg, edge=edge, text=text, key=key):
            ax.scatter([x], [yy], s=42, c=bg, edgecolors=edge, linewidths=0.7, transform=ax.transAxes, zorder=3)
        row(h, f"{key} {label} ({n}곳)")
    ax.text(0.0, 0.0, ATTRIBUTION, fontsize=5.5, color=MUTED, va="bottom", transform=ax.transAxes)


def main() -> None:
    seg, _, obs = load("original_360", 50)
    seg = segment_layer_data(seg)
    acc = read_accidents(seg)
    sites = read_sites()
    seg_w, acc_w, obs_w, sites_w = (g.to_crs(WEB_CRS) for g in (seg, acc, obs, sites))

    fig = plt.figure(figsize=(17 * CM, 24.5 * CM), dpi=300)
    fig.patch.set_facecolor("white")
    fig.text(0.012, 0.988, "부산 연안 CCTV 가시 커버율 및 신규 후보지 상위 50곳 촬영방향 제안",
             fontsize=11.5, fontweight="bold", color=INK, va="top")
    fig.text(0.012, 0.968, "기존 CCTV 3분류 반영 가시 커버율 · 위험도 가중 레이지 그리디 상위 50곳 · "
             "번호 원이 겹치는 곳은 선으로 실제 위치와 연결", fontsize=7.2, color=MUTED, va="top")

    # ── 전체 지도
    ax = fig.add_axes([0.012, 0.415, 0.976, 0.54])
    b = setup_map(ax, MAIN_EXTENT, zoom=12, label_zoom=11)
    draw_layers(ax, seg_w, acc_w, obs_w, lw=1.1, acc_s=1.6, cctv_s=0.8)
    in_inset = np.zeros(len(sites), bool)
    for key, (_, ib) in INSETS.items():
        wb = to_web(ib)
        sx, sy = sites_w.geometry.x.values, sites_w.geometry.y.values
        in_inset |= (sx > wb[0]) & (sx < wb[2]) & (sy > wb[1]) & (sy < wb[3])
        ax.add_patch(Rectangle((wb[0], wb[1]), wb[2] - wb[0], wb[3] - wb[1], fill=False,
                               ec=INK, lw=0.9, ls=(0, (3, 1.5)), zorder=10))
        ax.text(wb[0], wb[3], f" {key} ", fontsize=8.5, fontweight="bold", color="white", va="bottom",
                ha="left", zorder=11, bbox=dict(boxstyle="square,pad=0.15", fc=INK, ec="none"))
    draw_sites(ax, sites_w, size_mm=3.6, font=5.6, bounds=b, mm_to_data=mm_scale(ax, b), numbered=~in_inset)

    # ── 확대 지도 A, B + 범례
    layout = {"A": [0.012, 0.012, 0.47, 0.385], "B": [0.492, 0.012, 0.23, 0.385]}
    for key, (title, ib) in INSETS.items():
        axi = fig.add_axes(layout[key])
        bi = setup_map(axi, ib, zoom=13, label_zoom=12)  # Esri 회색 지도는 부산에서 14 미제공
        draw_layers(axi, seg_w, acc_w, obs_w, lw=1.6, acc_s=4, cctv_s=2.5)
        inside = ((sites_w.geometry.x > bi[0]) & (sites_w.geometry.x < bi[2])
                  & (sites_w.geometry.y > bi[1]) & (sites_w.geometry.y < bi[3])).values
        draw_sites(axi, sites_w[inside], size_mm=4.0, font=6.3, bounds=bi, mm_to_data=mm_scale(axi, bi))
        axi.text(0.02, 0.985, f" {key}  {title} ", transform=axi.transAxes, fontsize=7.5, fontweight="bold",
                 color="white", va="top", ha="left", zorder=12, bbox=dict(boxstyle="square,pad=0.2", fc=INK, ec="none"))

    legend(fig.add_axes([0.737, 0.012, 0.255, 0.385]), seg, acc, obs, sites)

    for ext in ("png", "pdf"):
        fig.savefig(HERE / f"{OUT_STEM}.{ext}", dpi=300, facecolor="white")
        print("saved", HERE / f"{OUT_STEM}.{ext}")


if __name__ == "__main__":
    main()
