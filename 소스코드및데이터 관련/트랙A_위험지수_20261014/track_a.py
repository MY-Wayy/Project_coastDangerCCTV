"""트랙 A — 해안 구간 위험지수 v1 (권찬희, 2026-10-14)

입력
  - 정민혁 integrated.zip : coastline_monitoring_segments.csv (1,832구간), accidents_busan_2017_2023.csv (397건)
  - 권찬희 data/ : 파고부이_일별_2024_2026.csv, 등표_일별_2024_2026.csv, 시간별_영도근처_2026Q2.csv
출력 (이 폴더)
  - 1_관측소배정.csv, 2_관측소별임계.csv, 3_해안유형별사고율.csv, 4_구간별위험지수.csv, 5_CCTV설치후보.csv
  - charts/*.png

실행: python track_a.py   (pandas, matplotlib 필요)
"""
import zipfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ZIP = ROOT / "권찬희_해양기상분석_20260820/jung data/integrated.zip"
DATA = ROOT / "권찬희_해양기상분석_20260820/data"
CHARTS = HERE / "charts"
CHARTS.mkdir(exist_ok=True)

with zipfile.ZipFile(ZIP) as z:
    seg = pd.read_csv(z.open("integrated/tables/coastline_monitoring_segments.csv"), encoding="utf-8-sig")
    acc = pd.read_csv(z.open("integrated/tables/accidents_busan_2017_2023.csv"), encoding="utf-8-sig")
wave = pd.read_csv(DATA / "파고부이_일별_2024_2026.csv")
lhaws = pd.read_csv(DATA / "등표_일별_2024_2026.csv")
hourly = pd.read_csv(DATA / "시간별_영도근처_2026Q2.csv")

seg["구"] = seg["SGG_NAM"].str.replace("부산광역시 ", "", regex=False)

# CCTV 지표: 트랙 B 통합 CCTV(4개 출처, 12,808지점) 결과가 있으면 GPKG 교통 CCTV(238대) 값을 대체
TRACK_B = ROOT / "트랙B/input_trackB_segments.csv"
CCTV_COLS = ["nearest_cctv_m", "cctv_count_500m", "cctv_gap_500m"]
CCTV_BASIS = "교통CCTV_238"
if TRACK_B.exists():
    tb = pd.read_csv(TRACK_B, encoding="utf-8-sig")[["segment_id"] + CCTV_COLS + ["view_coverage_pct_conservative"]]
    seg = seg.drop(columns=CCTV_COLS).merge(tb, on="segment_id", how="left")
    CCTV_BASIS = "통합CCTV_12808"

# ---------------------------------------------------------------------------
# ① 관측소 배정 — 거리 아닌 외해노출 그룹 기준 (8월 분석: 오륙도↔기장 r=0.93, 오륙도↔다대포 r=0.73)
# ---------------------------------------------------------------------------
STATION_BY_GU = {
    "강서구": ("내만", "다대포"), "사하구": ("내만", "다대포"),
    "기장군": ("외해", "기장"), "해운대구": ("외해", "기장"),
    "수영구": ("외해", "오륙도"), "남구": ("외해", "오륙도"), "동구": ("외해", "오륙도"),
    "중구": ("외해", "오륙도"), "서구": ("외해", "오륙도"), "영도구": ("외해", "오륙도"),
}
seg["노출그룹"] = seg["구"].map(lambda g: STATION_BY_GU[g][0])
seg["배정관측소"] = seg["구"].map(lambda g: STATION_BY_GU[g][1])
seg[["segment_id", "구", "노출그룹", "배정관측소"]].to_csv(HERE / "1_관측소배정.csv", index=False, encoding="utf-8-sig")

# ---------------------------------------------------------------------------
# ② (B층) 관측소별 위험 임계 — 유의파고 일별 P85. 전역 0.90 m 대신 지점별
# ---------------------------------------------------------------------------
GLOBAL_THR = 0.90
rows = []
for st, g in wave.groupby("관측소명"):
    hs = g["유의파고(m)"].dropna()
    thr = hs.quantile(0.85)
    rows.append({
        "관측소": st,
        "유효일수": len(hs),
        "평균유의파고_m": round(hs.mean(), 3),
        "지점별임계_P85_m": round(thr, 2),
        "전역0.90m_초과일비율": round((hs > GLOBAL_THR).mean(), 3),
        "지점별임계_초과일비율": round((hs > thr).mean(), 3),
    })
thr_df = pd.DataFrame(rows)
gust = lhaws["최대순간풍속(m/s)"].dropna()
gust_thr = round(gust.quantile(0.85), 1)
thr_df["풍속임계_오륙도등표_P85_ms"] = gust_thr
thr_df.to_csv(HERE / "2_관측소별임계.csv", index=False, encoding="utf-8-sig")
THR = dict(zip(thr_df["관측소"], thr_df["지점별임계_P85_m"]))

# 시간별 자료에 지점별 임계 적용 → 경보 시간 수 (B층 시연)
hourly["관측소"] = hourly["관측소명"].str.replace(r"\(.*\)", "", regex=True).str.strip()
hb = hourly[hourly["관측소"].isin(THR) & hourly["파고(m)"].notna()].copy()
hb = hb[hb["관측소명"].str.contains("파고부이") | ~hb["관측소명"].str.contains("등표")]
hb["경보"] = hb["파고(m)"] > hb["관측소"].map(THR)
hourly_alert = hb.groupby("관측소")["경보"].agg(["sum", "count"]).rename(columns={"sum": "경보시간", "count": "유효시간"})

# ---------------------------------------------------------------------------
# ③ (A층) 해안 유형별 사고율 — 사고 장소유형 ↔ 해안선 CAT_COA 매칭, km당 사고 건수
#    사고 자료에 좌표·구가 없으므로 '유형' 축으로 공간에 내린다
# ---------------------------------------------------------------------------
TYPE_BY_COA = {
    11: "방파제·테트라포드", 12: "방파제·테트라포드",
    13: "항포구", 14: "항포구", 16: "항포구", 17: "항포구",
    51: "갯바위", 54: "갯바위",
    15: "해안가", 52: "해안가", 53: "해안가", 55: "해안가",
}
ACC_TYPE = {"테트라포드": "방파제·테트라포드", "방파제": "방파제·테트라포드", "항포구": "항포구",
            "갯바위": "갯바위", "해안가": "해안가", "해수욕장": "해안가"}
seg["해안유형"] = seg["CAT_COA"].map(TYPE_BY_COA).fillna("미분류")
acc["해안유형"] = acc["장소유형"].map(ACC_TYPE)  # 해양·기타·무인도서는 해안선 유형이 아니므로 제외(NaN)

type_km = seg.groupby("해안유형")["segment_length_m"].sum() / 1000
type_acc = acc["해안유형"].value_counts()
rate = pd.DataFrame({"해안길이_km": type_km.round(1), "사고건수": type_acc}).fillna(0)
rate = rate.drop(index="미분류")
rate["km당사고"] = (rate["사고건수"] / rate["해안길이_km"]).round(3)
rate["구간수"] = seg["해안유형"].value_counts()
rate.sort_values("km당사고", ascending=False).to_csv(HERE / "3_해안유형별사고율.csv", encoding="utf-8-sig")
type_rate = rate["km당사고"].to_dict()
type_rate["미분류"] = rate["사고건수"].sum() / rate["해안길이_km"].sum()  # 전체 평균으로 대체

# ---------------------------------------------------------------------------
# ④ 위험지수 v1 = sqrt(T × W)  (USGS CVI 방식의 기하평균, 0~1 비율척도)
#    T: 해안유형 사고율 / 최대값   W: 배정관측소 전역임계(0.90 m) 초과일비율 / 최대값
#    W는 '절대적 파랑 에너지 노출'이므로 지점별 임계가 아닌 공통 임계로 계산한다
#    (지점별 임계는 B층 시간 경보용)
# ---------------------------------------------------------------------------
w_exp = thr_df.set_index("관측소")["전역0.90m_초과일비율"]
seg["T_유형위험"] = seg["해안유형"].map(type_rate) / max(type_rate.values())
seg["W_파랑노출"] = seg["배정관측소"].map(w_exp) / w_exp.max()
seg["위험지수"] = np.sqrt(seg["T_유형위험"] * seg["W_파랑노출"]).round(3)
seg["위험등급"] = pd.cut(seg["위험지수"], [-0.01, 0.2, 0.4, 0.6, 0.8, 1.0], labels=[1, 2, 3, 4, 5]).astype(int)

out_cols = ["segment_id", "구", "해안유형", "CAT_COA", "노출그룹", "배정관측소", "segment_length_m",
            "T_유형위험", "W_파랑노출", "위험지수", "위험등급", "nearest_cctv_m", "cctv_count_500m", "cctv_gap_500m"]
if "view_coverage_pct_conservative" in seg.columns:
    out_cols.append("view_coverage_pct_conservative")
seg["cctv_기준"] = CCTV_BASIS
out_cols.append("cctv_기준")
seg[out_cols].round(3).to_csv(HERE / "4_구간별위험지수.csv", index=False, encoding="utf-8-sig")

# ⑤ CCTV 설치 후보 — 위험등급 4·5 이면서 CCTV 사각 (→ 트랙 B 입력)
#    사각 판정: 트랙 B 결과가 있으면 지형 반영 가시 커버율(보수적) 0%, 없으면 500m 내 CCTV 없음
#    도서부(GRP_ISL=2)는 제외: 육지와 떨어진 해상 방파제라 도보 접근 불가 + 전원·통신 인입 비용이 커 최소비용 목표에 부적합
if "view_coverage_pct_conservative" in seg.columns:
    blind = seg["view_coverage_pct_conservative"] == 0
    BLIND_RULE = "가시 커버율 0%"
else:
    blind = seg["cctv_gap_500m"]
    BLIND_RULE = "500m 내 CCTV 없음"
cand = seg[(seg["위험등급"] >= 4) & blind & (seg["GRP_ISL"] == 1)].sort_values(
    ["위험지수", "nearest_cctv_m"], ascending=[False, False])
cand[out_cols].round(3).to_csv(HERE / "5_CCTV설치후보.csv", index=False, encoding="utf-8-sig")

# ---------------------------------------------------------------------------
# 차트
# ---------------------------------------------------------------------------
GRADE_COLORS = ["#d9ead3", "#b6d7a8", "#ffe599", "#f6b26b", "#cc0000"]

fig, ax = plt.subplots(figsize=(8, 4.5))
r = rate.sort_values("km당사고")
ax.barh(r.index, r["km당사고"], color="#3d6fb6")
for i, (v, n) in enumerate(zip(r["km당사고"], r["사고건수"])):
    ax.text(v, i, f" {v:.2f}건/km ({int(n)}건)", va="center", fontsize=9)
ax.set_title("해안 유형별 km당 사고 건수 (부산 2017–2023)")
ax.set_xlabel("km당 사고 건수")
ax.set_xlim(0, r["km당사고"].max() * 1.35)
fig.tight_layout(); fig.savefig(CHARTS / "A1_해안유형별사고율.png", dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(8, 4.5))
x = np.arange(len(thr_df))
ax.bar(x - 0.2, thr_df["전역0.90m_초과일비율"] * 100, 0.4, label="전역 임계 0.90 m", color="#999999")
ax.bar(x + 0.2, thr_df["지점별임계_초과일비율"] * 100, 0.4, label="지점별 임계 (P85)", color="#3d6fb6")
for i, t in enumerate(thr_df["지점별임계_P85_m"]):
    ax.text(i + 0.2, thr_df["지점별임계_초과일비율"].iloc[i] * 100 + 0.5, f"{t} m", ha="center", fontsize=9)
ax.set_xticks(x, thr_df["관측소"])
ax.set_ylabel("위험일 비율 (%)")
ax.set_title("관측소별 위험 임계: 전역 vs 지점별")
ax.legend(); fig.tight_layout(); fig.savefig(CHARTS / "A2_관측소별임계.png", dpi=150); plt.close(fig)

ct = pd.crosstab(seg["구"], seg["위험등급"]).reindex(columns=[1, 2, 3, 4, 5], fill_value=0)
ct = ct.loc[ct.sum(axis=1).sort_values().index]
fig, ax = plt.subplots(figsize=(8, 5))
left = np.zeros(len(ct))
for gcol, c in zip(ct.columns, GRADE_COLORS):
    ax.barh(ct.index, ct[gcol], left=left, color=c, label=f"{gcol}등급")
    left += ct[gcol].values
ax.set_title("구·군별 해안 구간 위험등급 분포 (1,832구간)")
ax.set_xlabel("구간 수"); ax.legend(loc="lower right")
fig.tight_layout(); fig.savefig(CHARTS / "A3_구별위험등급.png", dpi=150); plt.close(fig)

cg = cand.groupby("구").size().sort_values()
fig, ax = plt.subplots(figsize=(8, 4.5))
ax.barh(cg.index, cg.values, color="#cc0000")
for i, v in enumerate(cg.values):
    ax.text(v, i, f" {v}", va="center")
ax.set_title(f"CCTV 설치 후보 구간: 위험 4·5등급 × {BLIND_RULE} (총 {len(cand)}구간, {CCTV_BASIS})")
ax.set_xlabel("구간 수")
fig.tight_layout(); fig.savefig(CHARTS / "A4_CCTV설치후보.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------------------
print("=== ① 관측소 배정 ===")
print(seg.groupby(["노출그룹", "배정관측소"]).size())
print("\n=== ② 관측소별 임계 ===")
print(thr_df.to_string(index=False))
print("\n시간별(2026Q2) 지점별 임계 초과 시간:\n", hourly_alert)
print("\n=== ③ 해안 유형별 사고율 ===")
print(rate.sort_values("km당사고", ascending=False).to_string())
print("\n=== ④ 위험등급 분포 ===")
print(seg["위험등급"].value_counts().sort_index())
print(pd.crosstab(seg["구"], seg["위험등급"]))
print(f"\n=== ⑤ CCTV 설치 후보 ({CCTV_BASIS}, {BLIND_RULE}): {len(cand)}구간 (총 {cand['segment_length_m'].sum()/1000:.1f} km) ===")
print(cand.groupby(["구", "해안유형"]).size())
print(cand[out_cols].head(10).to_string(index=False))
