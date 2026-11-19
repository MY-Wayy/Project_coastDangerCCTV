"""30m 격자가 해안선 구간에 어떻게 배정됐는지 지도로 그린다.

입력(읽기만 함): 소스코드및데이터 관련/테트라워치_분석데이터_소스코드/DatoryLab_trackB_2/
  outputs/viewshed/target_zone_index.tif  (격자 → 배정된 구간 번호 1~1832, 0 = 대상구역 밖)
  outputs/viewshed/viewshed_inputs.gpkg    (target_zone: 구간별 ±100m 띠 폴리곤)
  outputs/cctv_reanalysis/coastal_safety_busan_cctv_updated.gpkg (해안선 구간 1,832개)
  outputs/trackD/segments.csv              (구간별 위험지수·등급·설치대상)
  data/raw/dem/busan_copernicus_dsm30_5186.tif (육지/바다 배경)
출력: 이 폴더의 PNG 3장
"""
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd, rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm, LinearSegmentedColormap
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

HERE = Path(__file__).resolve().parent
D = HERE.parent / "소스코드및데이터 관련" / "테트라워치_분석데이터_소스코드" / "DatoryLab_trackB_2"
plt.rcParams["font.family"] = ["Pretendard", "Apple SD Gothic Neo", "AppleGothic"]
plt.rcParams["axes.unicode_minus"] = False

with rasterio.open(D / "outputs/viewshed/target_zone_index.tif") as src:
    idx = src.read(1).astype(int); T = src.transform; B = src.bounds
with rasterio.open(D / "data/raw/dem/busan_copernicus_dsm30_5186.tif") as src:
    dem = src.read(1); dem = np.where(dem == src.nodata, 0, dem)
zone = gpd.read_file(D / "outputs/viewshed/viewshed_inputs.gpkg", layer="target_zone")
coast = gpd.read_file(D / "outputs/cctv_reanalysis/coastal_safety_busan_cctv_updated.gpkg",
                      layer="coastline_monitoring_segments_cctv_updated")
seg = pd.read_csv(D / "outputs/trackD/segments.csv", encoding="utf-8-sig")
seg_ids = zone["segment_id"].to_numpy()                      # 격자 번호 k ↔ zone의 k-1번째 구간
order = {sid: i + 1 for i, sid in enumerate(seg_ids)}
seg["k"] = seg["segment_id"].map(order)
risk = np.zeros(len(seg_ids) + 1); risk[seg["k"]] = seg["위험지수"]
grade = np.zeros(len(seg_ids) + 1, dtype=int); grade[seg["k"]] = seg["위험등급"]
target = np.zeros(len(seg_ids) + 1, dtype=bool); target[seg["k"]] = seg["설치대상"].astype(str).isin(["True", "1"])
coast["k"] = coast["segment_id"].map(order)
extent = (B.left, B.right, B.bottom, B.top)

n_cells = int((idx > 0).sum())
print(f"격자 {n_cells:,}개, 구간 {len(seg_ids):,}개, 셀 0.09ha → {n_cells * 0.09:,.1f}ha")

def background(ax, win):
    x0, x1, y0, y1 = win
    land = np.where(dem > 1.0, 1.0, np.nan)
    ax.imshow(np.ones_like(dem), extent=extent, cmap=ListedColormap(["#DCEAF5"]), interpolation="nearest", zorder=0)
    ax.imshow(land, extent=extent, cmap=ListedColormap(["#F3F1EC"]), interpolation="nearest", zorder=1)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])

def scalebar(ax, win, km, top=False):
    x0, x1, y0, y1 = win; w = x1 - x0; h = y1 - y0
    xs = x0 + w * 0.05; ys = y1 - h * 0.06 if top else y0 + h * 0.05
    ax.plot([xs, xs + km * 1000], [ys, ys], color="#1F2937", lw=3, zorder=20)
    ax.text(xs + km * 500, ys + h * 0.012, f"{km} km", ha="center", va="bottom", fontsize=10, color="#1F2937", zorder=20)

# ── 색 ────────────────────────────────────────────────────────────────────
risk_cmap = LinearSegmentedColormap.from_list("risk", ["#FDE9D6", "#F6B26B", "#E8650B", "#B4320A"])
cat_colors = ["#4E79A7", "#F28E2B", "#59A14F", "#E15759", "#B07AA1", "#EDC948", "#76B7B2", "#FF9DA7", "#9C755F", "#BAB0AC"]
cat_cmap = ListedColormap(cat_colors)

# ── 그림 1: 부산 전체, 격자에 물려받은 위험지수 ────────────────────────────
fig, ax = plt.subplots(figsize=(16, 13), dpi=150)
win = (B.left + 2000, B.right - 1000, B.bottom + 4000, B.top - 9000)
background(ax, win)
cell_risk = np.where(idx > 0, risk[idx], np.nan)
cell_risk = np.where((idx > 0) & ~target[idx], np.nan, cell_risk)
excl = np.where((idx > 0) & ~target[idx], 1.0, np.nan)
ax.imshow(excl, extent=extent, cmap=ListedColormap(["#9CA3AF"]), interpolation="nearest", zorder=2)
im = ax.imshow(cell_risk, extent=extent, cmap=risk_cmap, vmin=0, vmax=1, interpolation="nearest", zorder=3)
coast.plot(ax=ax, color="#111827", linewidth=0.35, zorder=4)
cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01); cb.set_label("격자가 물려받은 구간 위험지수 R (0~1)", fontsize=11)
ax.legend(handles=[Patch(color="#9CA3AF", label="설치 제외 구간의 격자 (섬·항만보안 등, 가중치 0)"),
                   Line2D([0], [0], color="#111827", lw=1, label="해안선 구간 1,832개")],
          loc="lower right", fontsize=10, frameon=True)
ax.set_title(f"가시권 분석 격자 {n_cells:,}개 (30m, 해안선 양쪽 100m 띠)와 물려받은 위험지수\n"
             "격자 색 = 그 격자가 배정된 해안선 구간의 위험지수 · 같은 구간의 격자는 모두 같은 값", fontsize=14, loc="left")
scalebar(ax, win, 5)
fig.savefig(HERE / "격자_구간배정_전체.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

# ── 그림 2·3: 확대 (왼쪽 = 구간 배정, 오른쪽 = 물려받은 위험지수) ─────────
def zoom(name, win, label_ids=True):
    x0, x1, y0, y1 = win
    fig, axes = plt.subplots(1, 2, figsize=(20, 10.5), dpi=150)
    # 창 안의 구간
    from shapely.geometry import box
    inwin = coast.cx[x0:x1, y0:y1].copy()
    inwin["len_in"] = inwin.geometry.intersection(box(x0, y0, x1, y1)).length
    lab = inwin[inwin["len_in"] >= 150]
    for ax in axes: background(ax, win)
    # 왼쪽: 구간별 색 (이웃이 다르게 보이도록 번호 순환)
    cat = np.where(idx > 0, (idx - 1) % len(cat_colors), np.nan)
    axes[0].imshow(cat, extent=extent, cmap=cat_cmap, vmin=-0.5, vmax=len(cat_colors) - 0.5, interpolation="nearest", zorder=2, alpha=0.85)
    zone.cx[x0:x1, y0:y1].boundary.plot(ax=axes[0], color="#374151", linewidth=0.5, linestyle=(0, (2, 2)), zorder=3)
    # 격자선
    cols = np.arange(int((x0 - B.left) // 30) * 30 + B.left, x1, 30); rows = np.arange(int((y0 - B.bottom) // 30) * 30 + B.bottom, y1, 30)
    for cx_ in cols: axes[0].plot([cx_, cx_], [y0, y1], color="white", lw=0.25, zorder=4, alpha=0.7)
    for ry in rows: axes[0].plot([x0, x1], [ry, ry], color="white", lw=0.25, zorder=4, alpha=0.7)
    inwin.plot(ax=axes[0], color="#111827", linewidth=1.6, zorder=5)
    # 구간 경계점·번호
    for _, r in inwin.iterrows():
        p0 = r.geometry.coords[0]; axes[0].plot(p0[0], p0[1], marker="o", ms=4, color="white", mec="#111827", mew=1, zorder=6)
    for _, r in lab.iterrows():
        if label_ids:
            c = r.geometry.intersection(box(x0, y0, x1, y1)).centroid
            axes[0].annotate(r["segment_id"].replace("SEG_00", ""), (c.x, c.y), fontsize=6, color="#111827",
                             ha="center", va="center", zorder=7,
                             bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75))
    axes[0].set_title("① 격자 → 해안선 구간 배정\n색 = 배정된 구간(이웃 구분용 색 순환) · 점선 = 구간별 100m 띠 · 점 = 구간 시작점 · 숫자 = 구간 번호", fontsize=12, loc="left")
    axes[0].legend(handles=[Line2D([0], [0], color="#111827", lw=1.6, label="해안선 구간"),
                            Line2D([0], [0], color="#374151", lw=0.8, ls="--", label="구간별 ±100m 띠 (겹치면 가까운 구간이 가져감)"),
                            Patch(facecolor="#F3F1EC", edgecolor="#D1D5DB", label="육지 (DSM > 1m)")],
                   loc="lower right", fontsize=9)
    # 오른쪽: 위험지수
    cr = np.where(idx > 0, risk[idx], np.nan); cr = np.where((idx > 0) & ~target[idx], np.nan, cr)
    ex = np.where((idx > 0) & ~target[idx], 1.0, np.nan)
    axes[1].imshow(ex, extent=extent, cmap=ListedColormap(["#9CA3AF"]), interpolation="nearest", zorder=2)
    im = axes[1].imshow(cr, extent=extent, cmap=risk_cmap, vmin=0, vmax=1, interpolation="nearest", zorder=3)
    for cx_ in cols: axes[1].plot([cx_, cx_], [y0, y1], color="white", lw=0.25, zorder=4, alpha=0.7)
    for ry in rows: axes[1].plot([x0, x1], [ry, ry], color="white", lw=0.25, zorder=4, alpha=0.7)
    inwin.plot(ax=axes[1], color="#111827", linewidth=1.6, zorder=5)
    if label_ids:
        for _, r in lab.iterrows():
            s = seg[seg["segment_id"] == r["segment_id"]].iloc[0]
            c = r.geometry.intersection(box(x0, y0, x1, y1)).centroid
            txt = f"R {s['위험지수']:.2f}\n{int(s['위험등급'])}등급" if s["설치대상"] in (True, "True", 1) else "제외"
            axes[1].annotate(txt, (c.x, c.y), fontsize=6, color="#111827", ha="center", va="center", zorder=7,
                             bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75))
    cb = fig.colorbar(im, ax=axes[1], fraction=0.03, pad=0.01); cb.set_label("위험지수 R", fontsize=10)
    axes[1].set_title("② 같은 격자가 물려받은 위험지수\n격자 색 = 배정된 구간의 R · 회색 = 설치 제외 구간(가중치 0)", fontsize=12, loc="left")
    for ax in axes: scalebar(ax, win, 1, top=True)
    fig.suptitle(f"{name} 확대 — 30m 격자의 구간 배정과 위험지수 상속", fontsize=15, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(HERE / f"격자_구간배정_확대_{name}.png", bbox_inches="tight", facecolor="white"); plt.close(fig)

def window_around(sgg, frac_x=(0.0, 1.0), frac_y=(0.0, 1.0), size=(3000, 2200)):
    g = coast[coast["SGG_NAM"] == sgg]; xmin, ymin, xmax, ymax = g.total_bounds
    cx_ = xmin + (xmax - xmin) * np.mean(frac_x); cy_ = ymin + (ymax - ymin) * np.mean(frac_y)
    return (cx_ - size[0] / 2, cx_ + size[0] / 2, cy_ - size[1] / 2, cy_ + size[1] / 2)

def window_at(cx_, cy_, size=(2400, 1700)):
    return (cx_ - size[0] / 2, cx_ + size[0] / 2, cy_ - size[1] / 2, cy_ + size[1] / 2)

# 3·5등급, 네 가지 해안유형, 설치 제외 구간이 함께 보이는 지점 (SEG_000069 / SEG_000473 중심)
zoom("기장군", window_at(403068, 293610))
zoom("영도구", window_at(390340, 277574))
print("done")
