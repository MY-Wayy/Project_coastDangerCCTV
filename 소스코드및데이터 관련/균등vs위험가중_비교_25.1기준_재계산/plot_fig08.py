#!/usr/bin/env python3
"""fig08(면적 균등 배치 vs 위험도 가중 배치 성과 비교)을 기존 커버율 25.1% 기준으로 다시 그림.

인쇄용: 그림 크기를 실제 인쇄 폭(A4 본문 17cm)으로 잡고 pt 단위 글자 크기를 그대로 쓴다.
- 왼쪽: 핵심 사각 v4 34구간 가시율 ← plan_comparison_both_baselines.csv (original_360)
- 오른쪽: 상위 50대 구·군 배분 ← 원본 new_sites_ranked*.csv (original_360, 읽기만)
- 색: 흑백 인쇄에서도 두 막대가 구분되도록 회색은 밝게, 주황은 진하게 (OKLab 명도 0.81 vs 0.64)

실행:  python plot_fig08.py   → 같은 폴더에 PNG(300dpi)·PDF 생성
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch

HERE = Path(__file__).resolve().parent
VS_DIR = HERE.parent / "통합완료 데이터 관련" / "DatoryLab_trackB_2" / "outputs" / "viewshed"
TABLE = HERE / "plan_comparison_both_baselines.csv"
RANKED = {"균등": VS_DIR / "new_sites_ranked.csv", "위험": VS_DIR / "new_sites_ranked_trackB_weights.csv"}
BASELINE = "original_360"
OUT_STEM = "fig08_균등배치_vs_위험도가중배치_성과비교_white_25.1기준_인쇄용"

FONT_DIR = Path.home() / "Library" / "Fonts"
for name in ("Pretendard-Regular.otf", "Pretendard-SemiBold.otf", "Pretendard-Bold.otf"):
    font_manager.fontManager.addfont(str(FONT_DIR / name))
plt.rcParams.update({"font.family": "Pretendard", "axes.unicode_minus": False})

CM = 1 / 2.54
UNIFORM = "#B9C1CD"   # 면적 균등 배치
RISK = "#D9650A"      # 위험도 가중 배치
INK, INK2, MUTED = "#111827", "#374151", "#6B7280"
BADGE = "#E8710A"

# 구·군 표시 순서와 원본 그림의 해안 특성 설명 (원본에 설명이 없던 중구·강서구는 비움)
DISTRICTS = [
    ("기장군", "외해 방파제·항포구"), ("영도구", "절벽·항포구"), ("남구", "외해 암벽·항포구"),
    ("동구", "북항 사고밀집"), ("해운대구", "청사포·방파제"), ("서구", "송도·암남"),
    ("중구", ""), ("사하구", "다대포·항포구"), ("강서구", ""),
]


def load():
    t = pd.read_csv(TABLE, encoding="utf-8-sig")
    t = t[(t["baseline"] == BASELINE) & (t["new_cameras"] > 0)]
    v4 = t.pivot(index="new_cameras", columns="plan", values="candidates_v4_coverage_pct")
    coast = t.pivot(index="new_cameras", columns="plan", values="coast_coverage_pct")
    counts = {}
    for key, path in RANKED.items():
        r = pd.read_csv(path, encoding="utf-8-sig")
        r = r[(r["baseline"] == BASELINE) & (r["rank"] <= 50)]
        counts[key] = r["SGG_NAM"].str.replace("부산광역시 ", "").value_counts()
    return v4, coast, counts


def bar(ax, y, width, h, color, x=0.0):
    ax.add_patch(FancyBboxPatch((x, y - h / 2), width, h, boxstyle="round,pad=0,rounding_size=0.6",
                                fc=color, ec="none", mutation_aspect=0.05))


def main() -> None:
    v4, coast, counts = load()
    u10, r10 = v4.loc[10, "균등 배치"], v4.loc[10, "위험도 가중 배치"]
    u50, r50 = v4.loc[50, "균등 배치"], v4.loc[50, "위험도 가중 배치"]
    area_loss = coast.loc[50, "균등 배치"] - coast.loc[50, "위험도 가중 배치"]

    fig = plt.figure(figsize=(17 * CM, 13.2 * CM), dpi=300)
    fig.patch.set_facecolor("white")

    # ── 머리글
    fig.text(0.012, 0.955, " 분석 결과 ③ ", fontsize=10, fontweight="bold", color="white", va="center",
             bbox=dict(boxstyle="round,pad=0.35,rounding_size=0.8", fc=BADGE, ec="none"))
    fig.text(0.15, 0.955, "면적 균등 배치 vs 위험도 가중 배치 성과 비교", fontsize=14.5,
             fontweight="bold", color=INK, va="center")
    fig.text(0.012, 0.895,
             f"위험도 가중 배치 시 전체 해안 가시 면적 손실은 {area_loss:.1f}%p에 불과하나, "
             f"핵심 고위험 사각(v4 34구간) 가시율은 +{r50 - u50:.1f}%p 상승",
             fontsize=9.5, color=INK2, va="center")
    fig.text(0.012, 0.855, "기존 CCTV 가시 커버율 25.1% 기준 · 신규 후보지 2,081곳 중 레이지 그리디 선정",
             fontsize=8.5, color=MUTED, va="center")
    fig.add_artist(plt.Line2D([0.012, 0.988], [0.825, 0.825], color="#E5E7EB", lw=0.8))

    # ── 범례 (두 패널 공통)
    for x, c, label in ((0.012, UNIFORM, "면적 균등 배치"), (0.21, RISK, "위험도 가중 배치")):
        fig.patches.append(FancyBboxPatch((x, 0.775), 0.018, 0.026, boxstyle="round,pad=0,rounding_size=0.003",
                                          fc=c, ec="none", transform=fig.transFigure, figure=fig))
        fig.text(x + 0.026, 0.788, label, fontsize=10, color=INK, va="center", fontweight="semibold")

    # ── 왼쪽: 핵심 사각 34구간 가시율
    axl = fig.add_axes([0.012, 0.02, 0.47, 0.725])
    axl.set_xlim(0, 100)
    axl.set_ylim(9.6, -1.2)
    axl.axis("off")
    axl.text(0, -1.0, "1. 핵심 고위험 사각지대(v4 34구간) 가시율", fontsize=11.5, fontweight="bold", color=INK)
    axl.text(0, -0.25, f"초기 10대 투입 시 위험도 가중 배치가 균등 배치의 {r10 / u10:.2f}배",
             fontsize=9, color=INK2)
    h = 0.62
    for i, n in enumerate((10, 20, 50)):
        y0 = 1.0 + i * 3.0
        u, r = v4.loc[n, "균등 배치"], v4.loc[n, "위험도 가중 배치"]
        axl.text(0, y0, f"신규 {n}대 투입", fontsize=10.5, fontweight="bold", color=INK, va="center")
        bar(axl, y0 + 0.85, u, h, UNIFORM)
        bar(axl, y0 + 1.6, r, h, RISK)
        axl.text(u + 1.2, y0 + 0.85, f"{u:.1f}%", fontsize=10, color=INK2, va="center")
        axl.text(r + 1.2, y0 + 1.6, f"{r:.1f}%  (+{r - u:.1f}%p)", fontsize=10.5, fontweight="bold",
                 color=INK, va="center")

    # ── 오른쪽: 상위 50대 구·군 배분
    axr = fig.add_axes([0.53, 0.02, 0.458, 0.725])
    n_rows = len(DISTRICTS)
    axr.set_xlim(0, 100)
    axr.set_ylim(n_rows + 0.1, -1.95)
    axr.axis("off")
    axr.text(0, -1.75, "2. 신규 50대 배치 시 구·군별 배정 대수", fontsize=11.5, fontweight="bold", color=INK)
    axr.text(0, -1.0, "같은 신규 50대의 배정 비교 (기존 CCTV 철거 아님)", fontsize=9, color=INK2)
    axr.text(100, -0.3, "균등 : 위험도 가중", fontsize=8.5, color=MUTED, va="center", ha="right")
    scale = 32 / max(max(counts["균등"]), max(counts["위험"]))  # 막대 최대 폭 32 (오른쪽 숫자와 겹치지 않게)
    x0 = 31
    bh = 0.3
    for i, (name, note) in enumerate(DISTRICTS):
        y = i + 0.35
        u = int(counts["균등"].get(name, 0))
        r = int(counts["위험"].get(name, 0))
        axr.text(0, y - 0.08, name, fontsize=10.5, fontweight="bold", color=INK, va="center")
        axr.text(0, y + 0.3, note, fontsize=7.5, color=MUTED, va="center")
        if u:
            bar(axr, y - 0.17, u * scale, bh, UNIFORM, x=x0)
        if r:
            bar(axr, y + 0.17, r * scale, bh, RISK, x=x0)
        # "균등 : 위험도 가중" — 위험도 가중 값만 주황. 오른쪽 값을 먼저 그려 폭을 잰 뒤 왼쪽 값을 붙인다
        risk_text = axr.text(100, y, f"{r}대", fontsize=10.5, fontweight="bold", color=RISK,
                             va="center", ha="right")
        fig.canvas.draw()
        left_x = axr.transData.inverted().transform(risk_text.get_window_extent().p0)[0]
        axr.text(left_x - 0.8, y, f"{u}대 :", fontsize=10.5, fontweight="semibold", color=INK,
                 va="center", ha="right")

    fig.savefig(HERE / f"{OUT_STEM}.png", dpi=300, facecolor="white")
    fig.savefig(HERE / f"{OUT_STEM}.pdf", facecolor="white")
    print("saved", HERE / f"{OUT_STEM}.png")
    print("saved", HERE / f"{OUT_STEM}.pdf")


if __name__ == "__main__":
    main()
