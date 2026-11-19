#!/usr/bin/env python3
"""보고서·판넬 그림 4종을 제출 폴더 데이터로 다시 계산해 만든다 (2026-11-02).

  fig00  연도별 해양사고 발생 추이 (판넬 분석배경, 1600×1060)
  fig01  해양사고 기상·해역 특성 (판넬 분석배경, 1600×900)
  fig07  해안유형별 위험지수·사각지대 비율 및 v4 34구간 (판넬·보고서 <그림 4>, 1600×900)
  trend  부산 해역 해양사고 발생 추이 (건) (보고서 <그림 1-0>, 2222×1300)

수치는 테트라워치_분석데이터_소스코드/DatoryLab_trackB_2 의 CSV에서 계산한다. 예외는 fig01의
'주요 사고 원인 상위 5개'로, 원본 그림의 분류 기준(occu_ty 묶음)을 확인할 수 없어 원본 값을 그대로 둔다.
HTML 틀(templates/*.html)에 값을 채운 뒤 Chrome 헤드리스로 PNG를 찍는다. 결과는 out/ 에 생긴다.

실행:  python build_figures.py
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from string import Template

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "테트라워치_분석데이터_소스코드" / "DatoryLab_trackB_2"
OUT = HERE / "out"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
R = lambda p: pd.read_csv(p, encoding="utf-8-sig")
pct = lambda a, b, d=1: f"{a / b * 100:.{d}f}%"
fmt = lambda n: f"{int(n):,}"

# ── 데이터 ─────────────────────────────────────────────────────────────────
acc = R(DATA / "부산전체_행정안전부_연안사고.csv")
seg = R(DATA / "outputs/trackD/segments.csv")
v4 = R(DATA / "outputs/trackD/cctv_candidates_v4.csv")
dist = R(DATA / "outputs/viewshed/viewshed_by_district.csv")
N = len(acc)

# 연도별
years = list(range(2015, 2025))
yc = acc["occu_year"].value_counts().reindex(years).astype(int)
early = yc.loc[2015:2017].mean()
late = yc.loc[2018:2024].mean()
yoy = {y: (yc[y] - yc[y - 1]) / yc[y - 1] * 100 for y in years[1:]}

# 기상
w = acc["wether_sn"].value_counts()
weather = [
    ("기상 양호 (평시 일상 환경)", w.get("양호", 0)),
    ("풍랑주의보 · 풍랑경보", w.get("풍랑주의보", 0) + w.get("풍랑경보", 0)),
    ("황천 3~6급 (고파랑 악기상)", sum(w.get(f"황천{k}급", 0) for k in (3, 4, 5, 6))),
    ("저시정 (안개 · 해무)", w.get("저시정", 0)),
    ("태풍경보 · 태풍주의보", w.get("태풍경보", 0) + w.get("태풍주의보", 0)),
]
assert sum(v for _, v in weather) == N, "기상 분류 합계가 전체와 다름"
good = weather[0][1]
bad = N - good

# 해역
lc = acc["occu_lc"].value_counts()
harbor = lc.get("항계 내", 0) + lc.get("항계내", 0)
sea = lc.get("영해", 0)
sea_strait = sea + lc.get("협수로", 0)

# 해안유형 (육지 설치대상)
B = lambda s: s.astype(str).isin(["True", "1", "Y"])
land = seg[B(seg["설치대상"])]
rows = {}
for ty, g in land.groupby("해안유형"):
    hi = g["위험등급"].astype(str).str.contains("4|5")
    blind = g["view_coverage_pct_conservative"] == 0
    rows[ty] = dict(n=len(g), T=g["T_유형위험"].mean(), W=g["W_파랑노출"].mean(), Rm=g["위험지수"].mean(),
                    hi=int(hi.sum()), hi_p=hi.mean() * 100, bl=int(blind.sum()), bl_p=blind.mean() * 100)
assert set(rows) == {"방파제·테트라포드", "항포구", "갯바위", "해안가", "미분류"}, rows.keys()

# v4
n4 = len(v4)
v4_cctv = int((v4["cctv_count_500m"] > 0).sum())
v4_gap = n4 - v4_cctv
v4_ty = v4["해안유형"].value_counts()
v4_gu = v4["구"].value_counts()
v4_sea = (v4["노출그룹"] == "외해").mean() * 100
blind_pct = 100 - float(dist.set_index(dist.columns[0]).loc["부산 전체", "coverage_pct_current"])

# ── 공통 ───────────────────────────────────────────────────────────────────
def render(name: str, values: dict, size: tuple[int, int], scale: int = 1) -> None:
    OUT.mkdir(exist_ok=True)
    html = Template((HERE / "templates" / f"{name}.html").read_text(encoding="utf-8")).substitute(values)
    html_path = OUT / f"{name}.html"
    html_path.write_text(html, encoding="utf-8")
    png = OUT / f"{name}.png"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                    f"--user-data-dir={OUT / '.chrome'}", f"--window-size={size[0]},{size[1]}",
                    f"--force-device-scale-factor={scale}", f"--screenshot={png}", html_path.as_uri()],
                   check=True, capture_output=True)
    print("wrote", png.relative_to(HERE))


def sign(v: float) -> str:
    return f"{v:+.1f}%"


# ── fig07 ──────────────────────────────────────────────────────────────────
def tr(ty, label_cls, r, risk_note, risk_cls, hi_txt, hi_cls, bl_cls):
    return (f'<tr><td class="{label_cls}">{ty}</td><td>{r["n"]}구간</td><td>{r["T"]:.2f}</td><td>{r["W"]:.2f}</td>'
            f'<td class="{risk_cls}">{r["Rm"]:.3f}{risk_note}</td><td class="{hi_cls}">{hi_txt}</td>'
            f'<td class="{bl_cls}">{r["bl_p"]:.1f}% ({r["bl"]}구간)</td></tr>')

bw, hp, gb, ha, mi = (rows[k] for k in ("방파제·테트라포드", "항포구", "갯바위", "해안가", "미분류"))
fig07 = dict(
    land_n=fmt(len(land), ), bw_r=f"{bw['Rm']:.3f}", hp_r=f"{hp['Rm']:.3f}", gb_bl=f"{gb['bl_p']:.1f}%",
    rows="\n".join([
        tr("방파제 · 테트라포드", "red", bw, " (최고)", "red", f"{bw['hi_p']:.1f}% ({bw['hi']}구간)", "red", ""),
        tr("항포구", "org", hp, " (2위)", "org", f"{hp['hi_p']:.1f}% ({hp['hi']}구간)", "org", ""),
        tr("갯바위", "b", gb, "", "", f"{gb['hi_p']:.1f}% (3등급 집중)", "", "red"),
        tr("해안가 (모래·자갈 등)", "", ha, "", "", f"{ha['hi_p']:.1f}%", "", ""),
        tr("미분류 (기암·암벽 등)", "", mi, "", "", f"{mi['hi_p']:.1f}% ({mi['hi']}구간)", "", ""),
    ]),
    n4=n4, v4_cctv_p=pct(v4_cctv, n4), v4_cctv=v4_cctv, v4_gap=v4_gap, v4_gap_p=pct(v4_gap, n4),
    v4_bw_p=pct(v4_ty.get("방파제·테트라포드", 0), n4), v4_bw=v4_ty.get("방파제·테트라포드", 0),
    v4_mi=v4_ty.get("미분류", 0), v4_hp=v4_ty.get("항포구", 0), v4_sea=f"{v4_sea:.0f}%",
    v4_gijang=v4_gu.get("기장군", 0), v4_nam=v4_gu.get("남구", 0),
    v4_gu=" · ".join(f"{g[:-1] if g.endswith(('구', '군')) and len(g) > 2 else g}({c})" for g, c in v4_gu.items()),
)

# ── fig01 ──────────────────────────────────────────────────────────────────
colors = ["#E8650B", "#1E88E5", "#1E88E5", "#5B6B7F", "#D32F2F"]
val_cls = ["org", "blu", "blu", "gry", "red"]
wrows = "\n".join(
    f'<div class="row"><div class="lab">{lab}</div><div class="track"><div class="fill" style="width:{v / good * 100:.1f}%;background:{c}"></div></div>'
    f'<div class="val {vc}">{fmt(v)}건 ({pct(v, N)})</div></div>'
    for (lab, v), c, vc in zip(weather, colors, val_cls))
# 원본 그림 값 유지 (분류 기준 미확인)
causes = [("1위. 정비불량 (기관·설비)", 802, "#1E2A3A", ""), ("2위. 운항부주의 (충돌·좌초)", 578, "#E8650B", "org"),
          ("3위. 관리소홀 (계류·침수)", 221, "#1E88E5", "blu"), ("4위. 안전부주의 (추락·익수·고립)", 126, "#D32F2F", "red"),
          ("5위. 기상악화 · 기타", 411, "#5B6B7F", "gry")]
crows = "\n".join(
    f'<div class="row"><div class="lab">{lab}</div><div class="track"><div class="fill" style="width:{v / 802 * 100:.1f}%;background:{c}"></div></div>'
    f'<div class="val {vc}">{fmt(v)}건 ({pct(v, N)})</div></div>' for lab, v, c, vc in causes)
fig01 = dict(N=fmt(N), good=fmt(good), good_p=pct(good, N), bad=fmt(bad), bad_p=pct(bad, N), good_w=f"{good / N * 100:.1f}",
             harbor=fmt(harbor), harbor_p=pct(harbor, N), sea_p=pct(sea, N), sea_strait=fmt(sea_strait), sea_strait_p=pct(sea_strait, N),
             coast_p=pct(harbor + sea, N), weather_rows=wrows, cause_rows=crows)

# ── fig00 ──────────────────────────────────────────────────────────────────
def bar_chart(w, h, left, right, top, bottom, ymax, step, bar_w, font, colors_by_year, trend=True, extra=""):
    slot = (right - left) / len(years)
    y = lambda v: bottom - v / ymax * (bottom - top)
    s = []
    for v in range(0, ymax + 1, step):
        s.append(f'<line x1="{left}" y1="{y(v):.1f}" x2="{right}" y2="{y(v):.1f}" stroke="#E5E7EB" stroke-width="1"/>'
                 f'<text x="{left - 14}" y="{y(v) + 6:.1f}" text-anchor="end" font-size="{font}" fill="#6B7280">{v}건</text>')
    pts = []
    for i, yr in enumerate(years):
        cx = left + slot * (i + 0.5)
        x0 = cx - bar_w / 2
        pts.append((cx, y(yc[yr])))
        s.append(f'<rect x="{x0:.1f}" y="{y(yc[yr]):.1f}" width="{bar_w}" height="{bottom - y(yc[yr]):.1f}" rx="6" fill="{colors_by_year[yr]}"/>')
        s.append(f'<text x="{cx:.1f}" y="{bottom + 36}" text-anchor="middle" font-size="{font + 4}" font-weight="{700 if yr in (2021, 2024) else 500}" fill="#1F2937">{yr}년</text>')
    if trend:
        s.append('<polyline points="' + " ".join(f"{a:.1f},{b:.1f}" for a, b in pts) + '" fill="none" stroke="#6B7280" stroke-width="3" stroke-dasharray="3 6"/>')
        for a, b in pts:
            s.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="6" fill="#fff" stroke="#374151" stroke-width="2.5"/>')
    return s, y, slot

L, Rr, T, Bt = 90, 1480, 60, 440
col = {yr: ("#9CA3AF" if yr <= 2017 else "#E53935" if yr == 2021 else "#E8650B" if yr == 2024 else "#3B82F6") for yr in years}
s, y, slot = bar_chart(1500, 500, L, Rr, T, Bt, 350, 50, 78, 16, col)
s.insert(0, f'<line x1="{L}" y1="{y(200):.1f}" x2="{Rr}" y2="{y(200):.1f}" stroke="#E8650B" stroke-width="2" stroke-dasharray="8 6"/>'
            f'<text x="{L - 14}" y="{y(200) + 6:.1f}" text-anchor="end" font-size="16" font-weight="700" fill="#E8650B">200건</text>')
s = [e for e in s if not e.endswith(">200건</text>") or "E8650B" in e]  # 회색 200건 눈금 라벨은 주황 라벨로 대체
for i, yr in enumerate(years):
    cx = L + slot * (i + 0.5); top_y = y(yc[yr])
    vc = "#E53935" if yr == 2021 else "#E8650B" if yr == 2024 else "#1F2937"
    s.append(f'<text x="{cx:.1f}" y="{top_y - 22:.1f}" text-anchor="middle" font-size="{30 if yr in (2021, 2024) else 26}" font-weight="800" fill="{vc}">{yc[yr]}건</text>')
    if yr in yoy:
        s.append(f'<text x="{cx:.1f}" y="{top_y - 56:.1f}" text-anchor="middle" font-size="16" font-weight="700" fill="{"#D32F2F" if yoy[yr] > 0 else "#1E5BD1"}">{sign(yoy[yr])}</text>')
    if yr == 2021:
        s.append(f'<rect x="{cx - 48:.1f}" y="{top_y - 108:.1f}" width="96" height="30" rx="15" fill="#D32F2F"/><text x="{cx:.1f}" y="{top_y - 87:.1f}" text-anchor="middle" font-size="15" font-weight="700" fill="#fff">역대 최다</text>')
    if yr == 2024:
        s.append(f'<rect x="{cx - 60:.1f}" y="{top_y - 108:.1f}" width="120" height="30" rx="15" fill="#E8650B"/><text x="{cx:.1f}" y="{top_y - 87:.1f}" text-anchor="middle" font-size="15" font-weight="700" fill="#fff">최근 급증·2위</text>')
fig00 = dict(N=fmt(N), avg10=f"{N / 10:.1f}", daily=f"{N / 3652:.1f}", late=f"{late:.1f}", early=f"{early:.1f}",
             late_up=f"+{(late - early) / early * 100:.1f}%", y24=yc[2024], y23=yc[2023], yoy24=sign(yoy[2024]), y21=yc[2021],
             good_p=pct(good, N), blind_p=f"{blind_pct:.1f}%", svg="\n".join(s))

# ── trend (보고서 그림 1-0, 1111×650 @2x) ─────────────────────────────────
L, Rr, T, Bt = 110, 1085, 70, 540
col2 = {yr: ("#7F7F7F" if yr <= 2017 else "#E05A4F" if yr == 2021 else "#E8842C" if yr == 2024 else "#2E5F82") for yr in years}
s, y, slot = bar_chart(1111, 650, L, Rr, T, Bt, 300, 50, 62, 17, col2, trend=False)
s = [e for e in s if "년</text>" not in e]  # x축 라벨은 기울여 다시 그린다
for i, yr in enumerate(years):
    cx = L + slot * (i + 0.5); top_y = y(yc[yr])
    vc = "#B71C1C" if yr == 2021 else "#C2410C" if yr == 2024 else "#1F2937"
    s.append(f'<text x="{cx:.1f}" y="{top_y - 12:.1f}" text-anchor="middle" font-size="{24 if yr in (2021, 2024) else 21}" font-weight="{800 if yr in (2021, 2024) else 500}" fill="{vc}">{yc[yr]}</text>')
    s.append(f'<text transform="translate({cx + 8:.1f},{Bt + 20}) rotate(-45)" text-anchor="end" font-size="21" fill="#1F2937">{yr}</text>')
x_e0, x_e1 = L + slot * 0 + 2, L + slot * 3 - 2
x_l0 = L + slot * 3 + 2
s.append(f'<line x1="{x_e0:.1f}" y1="{y(early):.1f}" x2="{x_e1:.1f}" y2="{y(early):.1f}" stroke="#111" stroke-width="3" stroke-dasharray="3 5"/>')
s.append(f'<line x1="{x_l0:.1f}" y1="{y(late):.1f}" x2="{Rr}" y2="{y(late):.1f}" stroke="#E53935" stroke-width="3" stroke-dasharray="3 5"/>')
ax = L + slot * 3
s.append(f'<line x1="{ax:.1f}" y1="{y(early):.1f}" x2="{ax:.1f}" y2="{y(late) + 14:.1f}" stroke="#E8842C" stroke-width="9"/>'
         f'<polygon points="{ax - 14:.1f},{y(late) + 16:.1f} {ax + 14:.1f},{y(late) + 16:.1f} {ax:.1f},{y(late):.1f}" fill="#E8842C"/>')
s.append(f'<text x="{ax - 20:.1f}" y="{y(late) + 30:.1f}" text-anchor="end" font-size="17" font-weight="700" fill="#E8842C">평균 {(late - early) / early * 100:.1f}%</text>'
         f'<text x="{ax - 20:.1f}" y="{y(late) + 52:.1f}" text-anchor="end" font-size="17" font-weight="700" fill="#E8842C">급증</text>')
cx24 = L + slot * 9.5
s.append(f'<text x="{cx24:.1f}" y="{y(yc[2024]) - 62:.1f}" text-anchor="middle" font-size="15" font-weight="600" fill="#D32F2F">전년대비</text>'
         f'<text x="{cx24:.1f}" y="{y(yc[2024]) - 42:.1f}" text-anchor="middle" font-size="15" font-weight="600" fill="#D32F2F">{sign(yoy[2024])}</text>')
trend = dict(svg="\n".join(s))

if __name__ == "__main__":
    render("fig07", fig07, (1600, 900))
    render("fig01", fig01, (1600, 900))
    render("fig00", fig00, (1600, 1060))
    render("trend", trend, (1111, 650), scale=2)
    print(f"\n요약: 양호 {good}/{N}={pct(good, N)}, 항계+영해 {pct(harbor + sea, N)}, v4 500m 내 CCTV {v4_cctv}/{n4}, "
          f"방파제 완전사각 {bw['bl']}({bw['bl_p']:.1f}%), 갯바위 {gb['bl']}({gb['bl_p']:.1f}%), 2024 전년비 {sign(yoy[2024])}")
