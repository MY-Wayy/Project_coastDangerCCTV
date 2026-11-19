"""판넬 「분석 결과」 패널(원본 1368×765 PNG) 재생성.

왼쪽(구·군별 커버율 막대, 해안유형 표, 핵심 발견 카드)은 제출 폴더 데이터로 다시 계산해 HTML로 그리고,
오른쪽 지도는 원본 판넬 PPTX에 들어 있던 그림에서 잘라 그대로 쓴다.

python build_panel_result.py <원본 판넬 .pptx>   → out/panel_result.png (2배 해상도 2736×1530)
"""
from __future__ import annotations

import io
import subprocess
import sys
import zipfile
from pathlib import Path
from string import Template

import numpy as np
import pandas as pd
from PIL import Image

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "테트라워치_분석데이터_소스코드" / "DatoryLab_trackB_2"
OUT = HERE / "out"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
W, H, LEFT_W = 1368, 765, 684
R = lambda p: pd.read_csv(p, encoding="utf-8-sig")
pct = lambda a, b, d=1: f"{a / b * 100:.{d}f}%"
fmt = lambda n: f"{int(n):,}"

seg = R(DATA / "outputs/trackD/segments.csv")
v4 = R(DATA / "outputs/trackD/cctv_candidates_v4.csv")
dist = R(DATA / "outputs/viewshed/viewshed_by_district.csv")
dist = dist.set_index(dist.columns[0])

# ── 구·군별 2D 반경 커버율 vs 3D 실제 가시율 ────────────────────────────────
gu = seg.groupby("구").agg(n=("segment_id", "size"), c2=("cctv_gap_500m", lambda s: (~s.astype(bool)).mean() * 100))
gu["c3"] = [dist.loc["부산광역시 " + k, "coverage_pct_current"] for k in gu.index]
gu["ha"] = [dist.loc["부산광역시 " + k, "zone_ha"] for k in gu.index]
gu = gu.sort_values("c3", ascending=False)
all_2d = (~seg["cctv_gap_500m"].astype(bool)).mean() * 100
all_3d = float(dist.loc["부산 전체", "coverage_pct_current"])
all_ha = float(dist.loc["부산 전체", "zone_ha"])


def bar(label, n, ha, c2, c3, total=False):
    blind = 100 - c3
    cls = " ".join(c for c in ["row", "red" if blind >= 70 else "", "total" if total else ""] if c)
    return (f'<div class="{cls}"><div class="lab">{label} ({fmt(n)}구간·{fmt(round(ha))}ha)</div>'
            f'<div class="track"><div class="gap" style="width:{100 - c2:.1f}%"></div><div class="f3" style="width:{c3:.1f}%"></div></div>'
            f'<div class="val">2D반경 {c2:.1f}% → 실제가시 {c3:.1f}% (사각 {blind:.1f}%)</div></div>')


bars = "\n".join(bar(k, r.n, r.ha, r.c2, r.c3) for k, r in gu.iterrows())
bars += "\n" + bar("부산 전체", len(seg), all_ha, all_2d, all_3d, total=True)

# ── 해안유형 표 (build_figures.py fig07과 동일 계산) ─────────────────────────
B = lambda s: s.astype(str).isin(["True", "1", "Y"])
land = seg[B(seg["설치대상"])]
rows = {}
for ty, g in land.groupby("해안유형"):
    hi = g["위험등급"].astype(str).str.contains("4|5")
    blind = g["view_coverage_pct_conservative"] == 0
    rows[ty] = dict(n=len(g), T=g["T_유형위험"].mean(), W=g["W_파랑노출"].mean(), Rm=g["위험지수"].mean(),
                    hi=int(hi.sum()), hi_p=hi.mean() * 100, bl=int(blind.sum()), bl_p=blind.mean() * 100)
assert set(rows) == {"방파제·테트라포드", "항포구", "갯바위", "해안가", "미분류"}, rows.keys()


def tr(ty, label_cls, r, risk_note, risk_cls, hi_txt, hi_cls, bl_cls):
    return (f'<tr><td class="{label_cls}">{ty}</td><td>{r["n"]}구간</td><td>{r["T"]:.2f}</td><td>{r["W"]:.2f}</td>'
            f'<td class="{risk_cls}">{r["Rm"]:.3f}{risk_note}</td><td class="{hi_cls}">{hi_txt}</td>'
            f'<td class="{bl_cls}">{r["bl_p"]:.1f}% ({r["bl"]}구간)</td></tr>')


bw, hp, gb, ha, mi = (rows[k] for k in ("방파제·테트라포드", "항포구", "갯바위", "해안가", "미분류"))
table_rows = "\n".join([
    tr("방파제 · 테트라포드", "red", bw, " (최고)", "red", f"{bw['hi_p']:.1f}% ({bw['hi']}구간)", "red", ""),
    tr("항포구", "org", hp, " (2위)", "org", f"{hp['hi_p']:.1f}% ({hp['hi']}구간)", "org", ""),
    tr("갯바위", "b", gb, "", "", f"{gb['hi_p']:.1f}% (3등급 집중)", "", "red"),
    tr("해안가 (모래·자갈 등)", "", ha, "", "", f"{ha['hi_p']:.1f}%", "", ""),
    tr("미분류 (기암·암벽 등)", "", mi, "", "", f"{mi['hi_p']:.1f}% ({mi['hi']}구간)", "", ""),
])

# ── v4 핵심 사각 34구간 ──────────────────────────────────────────────────────
n4 = len(v4)
v4_cctv = int((v4["cctv_count_500m"] > 0).sum())
v4_gap = n4 - v4_cctv
v4_ty = v4["해안유형"].value_counts()
v4_gu = v4["구"].value_counts()
v4_sea = (v4["노출그룹"] == "외해").mean() * 100

# ── 지도: 원본 판넬 PPTX의 1368×765 그림에서 오른쪽을 잘라 씀 ───────────────
src_pptx = Path(sys.argv[1])
with zipfile.ZipFile(src_pptx) as z:
    cands = [n for n in z.namelist() if n.startswith("ppt/media/") and n.endswith(".png")]
    for n in cands:
        im = Image.open(io.BytesIO(z.read(n)))
        if im.size == (W, H):
            orig = im.convert("RGB")
            break
    else:
        sys.exit("원본 판넬 PPTX에서 1368×765 그림을 찾지 못함")
a = np.asarray(orig).astype(int)
nonwhite = (np.abs(a[:, LEFT_W:] - 255).sum(axis=2) > 30).mean(axis=1) > 0.3  # 제목 글자는 제외, 지도만
nonwhite[:4] = False  # 원본 맨 윗줄의 회색 테두리 선 제외
ys = np.where(nonwhite)[0]
map_top, map_bot = int(ys.min()), int(ys.max()) + 1
OUT.mkdir(exist_ok=True)
map_png = OUT / "panel_result_map.png"
orig.crop((LEFT_W, map_top, W, map_bot)).save(map_png)
print(f"map crop: x≥{LEFT_W}, y {map_top}–{map_bot}")

values = dict(
    all_2d=f"{all_2d:.1f}%", all_3d=f"{all_3d:.1f}%", bars=bars, rows=table_rows, land_n=fmt(len(land)),
    n4=n4, v4_cctv_p=pct(v4_cctv, n4), v4_cctv=v4_cctv, v4_gap=v4_gap, v4_gap_p=pct(v4_gap, n4),
    v4_bw_p=pct(v4_ty.get("방파제·테트라포드", 0), n4), v4_bw=v4_ty.get("방파제·테트라포드", 0),
    v4_mi=v4_ty.get("미분류", 0), v4_hp=v4_ty.get("항포구", 0), v4_sea=f"{v4_sea:.0f}%",
    v4_gijang=v4_gu.get("기장군", 0), v4_nam=v4_gu.get("남구", 0),
    v4_gu=" · ".join(f"{g[:-1] if g.endswith(('구', '군')) and len(g) > 2 else g}({c})" for g, c in v4_gu.items()),
    map_top=f"{map_top}px", map_h=f"{map_bot - map_top}px", map_src=map_png.name,
)
html = Template((HERE / "templates" / "panel_result.html").read_text(encoding="utf-8")).substitute(values)
html_path = OUT / "panel_result.html"
html_path.write_text(html, encoding="utf-8")
png = OUT / "panel_result.png"
subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                f"--user-data-dir={OUT / '.chrome'}", f"--window-size={W},{H}", "--force-device-scale-factor=2",
                f"--screenshot={png}", html_path.as_uri()], check=True, capture_output=True)
print("wrote", png.relative_to(HERE), Image.open(png).size)
