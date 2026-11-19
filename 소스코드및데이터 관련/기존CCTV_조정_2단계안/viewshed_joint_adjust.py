#!/usr/bin/env python3
"""기존 CCTV 조정 2단계안: 위치·화각을 고정하고 높이·방향만 변수로 둔 가시 커버율 '상한' 분석.

원본 `통합완료 데이터 관련/DatoryLab_trackB_2/tools/viewshed_sensitivity.py`(2026-10)를 복사해 고친 것이다.
원본 폴더의 DEM·관측점·구간 격자·핵심 사각 34구간·신규 50곳 순위는 읽기만 하고, 출력은 이 폴더에 쓴다.

핵심 전제
- 현재 방위각은 실측이 아니라 가정(최근접 해안 직시 / 비스듬 60°)이다. 따라서 기준 커버율 25.1%는
  가정값이지만, 방향을 최적화한 상한은 각 관측점의 360° 가시 셀과 화각만으로 계산하므로 현재 방위각
  가정과 무관하다. 이 스크립트는 "돌려야 할 각도"를 내지 않고 "권장 방위각과 그때 추가로 보이는 구간"만 낸다.
- 조정 가능 여부는 행정안전부 표준데이터의 설치 목적으로 보수적으로 나눈다 (legal_tier 참고).
  A: 재난재해·시설물관리 목적 → 설치 목적 범위 내. 운영·관리 방침과 안내판의 촬영 범위 갱신으로 조정 가능
  B: 생활방범·다목적·차량방범 목적 → 표준 개인정보 보호지침 제38조에 따라 연안 안전 목적을 추가
     (관계 전문가·이해관계인 의견 수렴, 안내판 현행화)한 뒤 조정 가능
  C: 교통단속·어린이보호·쓰레기단속 등 단속 목적, 목적 미상(기타), 3D 지형 완전 차폐 → 조정 대상 제외
- 높이 조정(+2m, +4m)도 같은 집합(A 또는 A+B)에만 적용한다. PTZ 360°는 방향 조정이 필요 없으므로 높이만 올린다.
- 3분류(제외 그룹 fov=0, PTZ 360°)는 원본 그대로 고정한다. 3-1 지형 완전 차폐 124곳은 높이를 올리면 보일 수
  있으나 분류를 바꾸지 않는다(보수적).
- 신규 50곳은 원본 순위(`new_sites_ranked*.csv`)를 그대로 쓰고 재배치하지 않는다. 순위는 기준선 두 가지(conservative_after_rotation =
  방향 최적화 후 32.0%, original_360 = 현재 가정 25.1%)가 있으며, md 통합본은 전자, HWPX 메인 보고서는 후자의 수치를 쓴다.

실행:  <geopandas·rasterio·shapely·pandas·numpy가 있는 python> viewshed_joint_adjust.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent / "통합완료 데이터 관련" / "DatoryLab_trackB_2"  # 원본, 읽기 전용
sys.path.insert(0, str(PROJECT / "tools"))
from viewshed_new_sites import candidate_cells, candidate_sites  # noqa: E402
from viewshed_sensitivity import VS_DIR, Context, coverage, omni_cells, sector  # noqa: E402

CORE34 = PROJECT / "outputs" / "trackD" / "cctv_candidates_v4.csv"
RANKED = {
    "위험도 가중 배치": VS_DIR / "new_sites_ranked_trackB_weights.csv",
    "균등 배치": VS_DIR / "new_sites_ranked.csv",
}
RANK_BASELINES = {  # 원본 순위 파일의 기준선 두 가지
    "conservative_after_rotation": "방향 최적화 후(32.0%) 기준선 순위",
    "original_360": "현재 가정(25.1%) 기준선 순위",
}
N_NEW = 50
AZIMUTH_STEP = 15.0
HEIGHTS = [0.0, 2.0, 4.0]
TIER_DESC = {
    "A": "즉시 조정 가능(재난재해·시설물관리 목적, 설치 목적 범위 내)",
    "B": "목적 추가 절차 후 조정 가능(생활방범·다목적·차량방범)",
    "C": "조정 대상 제외(단속·어린이보호·목적 미상·지형 차폐)",
}


def legal_tier(purpose: str, detail: str) -> str:
    p = str(purpose or "")
    if str(detail).startswith("3-"):  # 3-1 지형 완전 차폐, 3-2 어린이보호·교통단속 (화각 0 고정)
        return "C"
    if any(k in p for k in ("교통단속", "어린이보호", "쓰레기단속")):
        return "C"
    if ("재난재해" in p) or ("시설물관리" in p):
        return "A"
    if any(k in p for k in ("생활방범", "다목적", "차량방범")):
        return "B"
    return "C"  # 기타·미상


def observer_meta(ctx: Context) -> pd.DataFrame:
    obs = ctx.observers[ctx.observers["coast_distance_m"] <= ctx.params["view_range_m"] + ctx.params["target_zone_m"]]
    meta = obs.drop(columns="geometry").reset_index(drop=True).copy()
    meta["lon"], meta["lat"] = meta["lon"].round(5), meta["lat"].round(5)
    meta["district"] = meta["manager"].astype(str).str.replace("부산광역시 ", "", regex=False).str.replace("청", "", regex=False).str.split("|").str[-1]
    meta["tier"] = [legal_tier(p, d) for p, d in zip(meta["purpose_original"], meta["ocean_view_detail"])]
    meta["camera_kind"] = np.select(
        [meta["fov_deg"] <= 0, meta["fov_deg"] >= 360], ["제외(화각0)", "PTZ 360°"], default="고정형"
    )
    return meta


def greedy_azimuths(ctx: Context, cells, bearings, fovs, rot_idx, base_sets):
    """원본 optimize_azimuths와 같은 그리디(15° 간격, 2회 반복). 선택한 방위각도 돌려준다."""
    candidates = np.arange(0.0, 360.0, AZIMUTH_STEP)
    chosen, chosen_az = {}, {}
    order = sorted(rot_idx, key=lambda i: -len(cells[i]))
    for _ in range(2):
        covered = coverage(ctx, base_sets + [chosen[j] for j in rot_idx if j in chosen])["_covered"]
        for i in order:
            if i in chosen:
                covered[chosen[i]] = False  # 자기 기여 제거 후 재선택(겹침은 근사, 원본과 동일)
            best_az, best = max(
                ((a, sector(cells[i], bearings[i], a, fovs[i])) for a in candidates),
                key=lambda t: int((~covered[t[1]]).sum()),
            )
            chosen[i], chosen_az[i] = best, float(best_az)
            covered[best] = True
    return chosen, chosen_az


class Scenario:
    def __init__(self, ctx, omni_by_h, meta, sid, label, adjust_tiers, dh, optimize):
        self.id, self.label, self.adjust_tiers, self.dh, self.optimize = sid, label, adjust_tiers, dh, optimize
        n = len(meta)
        fovs = meta["fov_deg"].to_numpy(float)
        az_now = meta["azimuth_deg"].to_numpy(float)
        adj = meta["tier"].isin(adjust_tiers).to_numpy()
        self.cells = [omni_by_h[dh if adj[i] else 0.0].cells.iloc[i] for i in range(n)]
        self.bearings = [omni_by_h[dh if adj[i] else 0.0].bearings.iloc[i] for i in range(n)]
        base_sets, rot_idx = [], []
        for i in range(n):
            if fovs[i] <= 0:
                continue
            if fovs[i] >= 360:
                base_sets.append(self.cells[i])
            elif adj[i] and optimize:
                rot_idx.append(i)
            else:
                base_sets.append(sector(self.cells[i], self.bearings[i], az_now[i], fovs[i]))
        self.rot_idx = rot_idx
        self.n_height = int((adj & (fovs > 0)).sum()) if dh else 0
        self.chosen, self.chosen_az = greedy_azimuths(ctx, self.cells, self.bearings, fovs, rot_idx, base_sets)
        self.sets = base_sets + [self.chosen[i] for i in rot_idx]
        res = coverage(ctx, self.sets)
        self.covered = res["_covered"]
        self.coverage_pct, self.covered_ha, self.zero_segments = res["coverage_pct"], res["covered_ha"], res["zero_segments"]
        # 관측점별 배타적 기여(다른 어떤 카메라도 보지 못하는 셀)
        count = np.zeros(ctx.zone_grid.size, dtype=np.int32)
        for s in self.sets:
            count[s] += 1
        self.exclusive = {i: self.chosen[i][count[self.chosen[i]] == 1] for i in rot_idx}

    def seg_covered_cells(self, ctx):
        return np.bincount(ctx.zone_grid[self.covered], minlength=len(ctx.zone) + 1)[1:]


def seg_cells_of(ctx, covered):
    return np.bincount(ctx.zone_grid[covered], minlength=len(ctx.zone) + 1)[1:]


def main() -> None:
    start = time.perf_counter()
    log = []

    def say(msg=""):
        print(msg)
        log.append(str(msg))

    ctx = Context()
    meta = observer_meta(ctx)
    seg_ids = ctx.zone["segment_id"].to_numpy()
    seg_total = np.bincount(ctx.zone_grid, minlength=len(seg_ids) + 1)[1:]
    has_area = seg_total > 0
    core = pd.read_csv(CORE34, encoding="utf-8-sig")
    core_mask = pd.Series(seg_ids).isin(set(core["segment_id"])).to_numpy()
    core_cell = np.concatenate([[False], core_mask])[ctx.zone_grid]
    say(f"관측점 {len(meta):,} / 구간 {len(seg_ids):,} (면적>0 {int(has_area.sum()):,}) / 핵심 사각 {int(core_mask.sum())}구간")

    # 1. 설치 목적별 조정 가능 구분
    say("\n[1] 설치 목적별 조정 가능 구분 (관측점 수)")
    tab = pd.crosstab(meta["tier"], meta["camera_kind"], margins=True)
    say(tab.to_string())
    tiers_out = meta[["integrated_id", "district", "manager", "purpose_original", "view_type", "fov_deg",
                      "ocean_view_detail", "tier", "coast_distance_m", "mount_height_m", "camera_count", "lon", "lat", "road_address"]].copy()
    tiers_out["tier_desc"] = tiers_out["tier"].map(TIER_DESC)
    tiers_out["coast_distance_m"] = tiers_out["coast_distance_m"].round(1)
    tiers_out.to_csv(HERE / "observer_tiers.csv", index=False, encoding="utf-8-sig")

    # 2. 높이별 360° 가시 셀
    say("\n[2] 높이별 360° 가시 셀 계산")
    omni_by_h = {}
    for dh in HEIGHTS:
        t0 = time.perf_counter()
        omni_by_h[dh] = omni_cells(ctx, dh, ctx.params["view_range_m"])
        assert list(omni_by_h[dh]["integrated_id"]) == list(meta["integrated_id"])
        say(f"  +{dh:.0f}m: {time.perf_counter() - t0:.0f}s")

    # 3. 시나리오
    say("\n[3] 시나리오")
    specs = [
        ("base", "기준(현재 가정 각도, 기준 높이)", set(), 0.0, False),
        ("A_h0", "A만 방향 최적화", {"A"}, 0.0, True),
        ("A_h2", "A만 높이 +2m + 방향 최적화", {"A"}, 2.0, True),
        ("A_h4", "A만 높이 +4m + 방향 최적화", {"A"}, 4.0, True),
        ("AB_h2_dir0", "A+B 높이 +2m만(각도 현재 가정)", {"A", "B"}, 2.0, False),
        ("AB_h4_dir0", "A+B 높이 +4m만(각도 현재 가정)", {"A", "B"}, 4.0, False),
        ("AB_h0", "A+B 방향 최적화", {"A", "B"}, 0.0, True),
        ("AB_h2", "A+B 높이 +2m + 방향 최적화", {"A", "B"}, 2.0, True),
        ("AB_h4", "A+B 높이 +4m + 방향 최적화", {"A", "B"}, 4.0, True),
        ("ALL_h0", "참고: 고정형 1,016대 전부 방향 최적화(원본 민감도 분석 재현)", {"A", "B", "C"}, 0.0, True),
    ]
    sc = {}
    for sid, label, tiers, dh, opt in specs:
        t0 = time.perf_counter()
        sc[sid] = Scenario(ctx, omni_by_h, meta, sid, label, tiers, dh, opt)
        s = sc[sid]
        say(f"  {sid:10s} {s.coverage_pct:6.2f}%  {s.covered_ha:8.1f}ha  완전사각 {s.zero_segments}  회전 {len(s.rot_idx)}  높이조정 {s.n_height}  ({time.perf_counter() - t0:.0f}s)")

    # 4. 신규 50곳(원본 순위 그대로) 가시 셀
    say("\n[4] 신규 50곳 가시 셀 (원본 순위 재사용)")
    top = {}
    for plan, path in RANKED.items():
        r = pd.read_csv(path, encoding="utf-8-sig")
        for bl in RANK_BASELINES:
            rr = r[(r["baseline"] == bl) & (r["rank"] <= N_NEW)]
            top[(plan, bl)] = list(rr["candidate_id"])
    need = sorted(set(sum(top.values(), [])))
    cands = candidate_sites(ctx)
    sub = cands[cands["candidate_id"].isin(need)].reset_index(drop=True)
    cells = dict(zip(sub["candidate_id"], candidate_cells(ctx, sub)))
    say(f"  후보 {len(cands):,}곳 중 상위 50곳 {len(need)}개 고유 지점의 가시 셀 계산")

    def with_new(covered, plan, bl="conservative_after_rotation"):
        c = covered.copy()
        for cid in top[(plan, bl)]:
            c[cells[cid]] = True
        return c

    # 5. 요약표
    base_seg = seg_cells_of(ctx, sc["base"].covered)
    base_zero = (base_seg == 0) & has_area

    def summarize(sid, label, covered, s=None, new_plan="", new_n=0):
        segc = seg_cells_of(ctx, covered)
        core_c = segc[core_mask]
        core_t = seg_total[core_mask]
        return {
            "scenario": sid, "label": label,
            "adjust_set": "" if s is None else "+".join(sorted(s.adjust_tiers)),
            "height_offset_m": 0 if s is None else s.dh,
            "direction": "" if s is None else ("최적화" if s.optimize else "현재 가정"),
            "cameras_rotated": 0 if s is None else len(s.rot_idx),
            "cameras_height_raised": 0 if s is None else s.n_height,
            "new_sites": new_n, "new_site_plan": new_plan,
            "coverage_pct": round(covered.sum() / ctx.zone_cells * 100, 2),
            "covered_ha": round(covered.sum() * ctx.cell_ha, 1),
            "zero_segments": int(((segc == 0) & has_area).sum()),
            "zero_resolved_vs_base": int((base_zero & (segc > 0)).sum()),
            "core34_nonzero": int((core_c > 0).sum()),
            "core34_ge50pct": int((core_c / core_t >= 0.5).sum()),
            "core34_area_pct": round(covered[core_cell].sum() / core_cell.sum() * 100, 1),
        }

    rows = [summarize(sid, s.label, s.covered, s) for sid, s in sc.items()]
    for sid in ("AB_h0", "AB_h2", "AB_h4", "ALL_h0"):
        for plan in RANKED:
            s = sc[sid]
            rows.append(summarize(f"{sid}+new{N_NEW}_{'w' if '가중' in plan else 'u'}",
                                  f"{s.label} + 신규 {N_NEW}곳({plan})", with_new(s.covered, plan), s, plan, N_NEW))
    for plan in RANKED:  # HWPX 메인 보고서가 쓰는 25.1% 기준선 순위: 조정 없이 신규 50곳만
        rows.append(summarize(f"base+new{N_NEW}_{'w' if '가중' in plan else 'u'}_o360",
                              f"기준(25.1%) + 신규 {N_NEW}곳({plan}, 25.1% 기준선 순위)",
                              with_new(sc["base"].covered, plan, "original_360"), None, plan, N_NEW))
    summary = pd.DataFrame(rows)
    summary.to_csv(HERE / "summary_scenarios.csv", index=False, encoding="utf-8-sig")
    say("\n[5] 요약")
    say(summary.drop(columns=["label"]).to_string(index=False))

    # 검증: 원본 민감도·plan_comparison 재현 여부
    say("\n[검증] 원본 재현")
    say(f"  ALL_h0 최적화 {sc['ALL_h0'].coverage_pct}% (원본 sensitivity_fov_azimuth optimized_pct 31.98)")
    say(f"  base {sc['base'].coverage_pct}% (원본 25.1), 완전사각 {sc['base'].zero_segments} (원본 889), ALL_h0 완전사각 {sc['ALL_h0'].zero_segments} (원본 804)")
    chk = summary.set_index("scenario")
    say(f"  ALL_h0+new50_w: 전체 {chk.loc['ALL_h0+new50_w', 'coverage_pct']}% / 핵심사각 {chk.loc['ALL_h0+new50_w', 'core34_area_pct']}% (원본 43.9 / 61.3)")
    say(f"  ALL_h0+new50_u: 전체 {chk.loc['ALL_h0+new50_u', 'coverage_pct']}% / 핵심사각 {chk.loc['ALL_h0+new50_u', 'core34_area_pct']}% (원본 45.6 / 47.8)")
    say(f"  base+new50_w_o360: 전체 {chk.loc['base+new50_w_o360', 'coverage_pct']}% / 핵심사각 {chk.loc['base+new50_w_o360', 'core34_area_pct']}% (원본 original_360 37.7 / 61.3)")
    say(f"  base+new50_u_o360: 전체 {chk.loc['base+new50_u_o360', 'coverage_pct']}% / 핵심사각 {chk.loc['base+new50_u_o360', 'core34_area_pct']}% (원본 original_360 39.3 / 47.5)")

    # 6. 구간별 상태 (전체 + 핵심 34)
    say("\n[6] 구간별 상태")
    fovs = meta["fov_deg"].to_numpy(float)
    adjAB = meta["tier"].isin({"A", "B"}).to_numpy() & (0 < fovs) & (fovs < 360)
    reach = {}
    for dh in (0.0, 4.0):
        any_dir = sc["base"].covered.copy()  # 기준 커버 + A+B 고정형을 어느 방향으로든 돌렸을 때 닿는 셀
        for i in np.flatnonzero(adjAB):
            any_dir[omni_by_h[dh].cells.iloc[i]] = True
        reach[dh] = seg_cells_of(ctx, any_dir)
    seg = pd.DataFrame({"segment_id": seg_ids, "SGG_NAM": ctx.zone["SGG_NAM"].to_numpy(), "zone_ha": (seg_total * ctx.cell_ha).round(2)})
    cols = {"base": "기준", "A_h0": "A_h0", "AB_h0": "AB_h0", "AB_h2": "AB_h2", "AB_h4": "AB_h4"}
    for sid, name in cols.items():
        c = seg_cells_of(ctx, sc[sid].covered)
        seg[f"covered_ha_{name}"] = (c * ctx.cell_ha).round(2)
        with np.errstate(invalid="ignore", divide="ignore"):
            seg[f"pct_{name}"] = np.where(has_area, c / np.maximum(seg_total, 1) * 100, np.nan).round(1)
    for plan, tag in (("위험도 가중 배치", "w"), ("균등 배치", "u")):
        c = seg_cells_of(ctx, with_new(sc["AB_h0"].covered, plan))
        seg[f"covered_ha_AB_h0_new50{tag}"] = (c * ctx.cell_ha).round(2)
        with np.errstate(invalid="ignore", divide="ignore"):
            seg[f"pct_AB_h0_new50{tag}"] = np.where(has_area, c / np.maximum(seg_total, 1) * 100, np.nan).round(1)
        c = seg_cells_of(ctx, with_new(sc["base"].covered, plan, "original_360"))
        seg[f"covered_ha_base_new50{tag}_o360"] = (c * ctx.cell_ha).round(2)
        with np.errstate(invalid="ignore", divide="ignore"):
            seg[f"pct_base_new50{tag}_o360"] = np.where(has_area, c / np.maximum(seg_total, 1) * 100, np.nan).round(1)
    seg["unreachable_any_direction_h0"] = has_area & (reach[0.0] == 0)
    seg["unreachable_any_direction_h4"] = has_area & (reach[4.0] == 0)
    seg["is_core34"] = core_mask

    def status(r):
        if not r["zone_ha"] > 0:
            return "면적 0"
        if r["covered_ha_기준"] > 0:
            return "기준에서 일부 가시"
        if r["covered_ha_A_h0"] > 0:
            return "1단계-A: 재난·시설 카메라 방향 조정으로 해소"
        if r["covered_ha_AB_h0"] > 0:
            return "1단계-B: 목적 추가 후 방향 조정으로 해소"
        if r["covered_ha_AB_h4"] > 0:
            return "1단계-B+높이: 높이 +4m까지 올려야 해소"
        if r["covered_ha_AB_h0_new50w"] > 0:
            return "2단계: 신규 50곳(위험도 가중)으로 해소"
        return "남음: 추가 신규 설치 필요"

    seg["status"] = seg.apply(status, axis=1)
    seg.to_csv(HERE / "segments_adjustment_status.csv", index=False, encoding="utf-8-sig")
    core_out = core[["segment_id", "구", "해안유형", "노출그룹", "위험지수", "위험등급", "cctv_count_500m", "view_zone_ha"]].merge(
        seg.drop(columns=["SGG_NAM", "zone_ha", "is_core34"]), on="segment_id", how="left")
    core_out.to_csv(HERE / "core34_segments_status.csv", index=False, encoding="utf-8-sig")
    say(core_out["status"].value_counts().to_string())
    say(f"  핵심 34구간 중 어느 방향으로도 기존 A+B 카메라가 못 보는 구간: h0 {int(core_out['unreachable_any_direction_h0'].sum())}, h4 {int(core_out['unreachable_any_direction_h4'].sum())}")
    for tag, plan in (("w", "위험도 가중"), ("u", "균등")):
        col = f"covered_ha_base_new50{tag}_o360"
        nz = core_out[col] > 0
        ge = core_out[f"pct_base_new50{tag}_o360"] >= 50
        say(f"  [25.1% 기준선 순위] 기준 + 신규 50곳({plan}): 핵심 34구간 중 가시 면적 생김 {int(nz.sum())}, 50% 이상 {int(ge.sum())}, 남음 {sorted(core_out.loc[~nz, 'segment_id'])}")
    say(f"  전체(면적>0) 완전 사각 {int(base_zero.sum())} 중 어느 방향으로도 불가: h0 {int((base_zero & (reach[0.0] == 0)).sum())}, h4 {int((base_zero & (reach[4.0] == 0)).sum())}")

    # 7. 관측점별 권장 방위각 (돌릴 각도는 내지 않는다: 현재 각도가 가정이므로)
    say("\n[7] 관측점별 권장 방위각")
    cam_rows = []
    for sid in ("A_h0", "AB_h0", "AB_h2", "AB_h4"):
        s = sc[sid]
        for i in s.rot_idx:
            ex = s.exclusive[i]
            hits = np.bincount(ctx.zone_grid[ex], minlength=len(seg_ids) + 1)[1:]
            touched = np.flatnonzero(hits > 0)
            m = meta.iloc[i]
            cam_rows.append({
                "scenario": sid, "integrated_id": m["integrated_id"], "district": m["district"],
                "purpose_original": m["purpose_original"], "tier": m["tier"], "group": m["ocean_view_detail"],
                "fov_deg": m["fov_deg"], "mount_height_m": m["mount_height_m"] + s.dh,
                "recommended_azimuth_deg": s.chosen_az[i],
                "sector_zone_ha": round(len(s.chosen[i]) * ctx.cell_ha, 2),
                "exclusive_gain_ha": round(len(ex) * ctx.cell_ha, 2),
                "exclusive_gain_cells": int(len(ex)),
                "main_segment_id": seg_ids[int(hits.argmax())] if len(ex) else "",
                "segments_touched": int(len(touched)),
                "segment_ids": ";".join(seg_ids[touched]),
                "core34_segments": ";".join(seg_ids[t] for t in touched if core_mask[t]),
                "lon": m["lon"], "lat": m["lat"], "road_address": m["road_address"], "camera_count": m["camera_count"],
            })
    cam = pd.DataFrame(cam_rows)
    cam = cam.sort_values(["scenario", "exclusive_gain_cells"], ascending=[True, False])
    cam.to_csv(HERE / "camera_recommended_azimuth.csv", index=False, encoding="utf-8-sig")

    chk_list = cam[(cam["scenario"] == "AB_h0") & (cam["exclusive_gain_cells"] > 0)].copy()
    chk_list = chk_list.sort_values("exclusive_gain_cells", ascending=False).reset_index(drop=True)
    chk_list.insert(0, "rank", np.arange(1, len(chk_list) + 1))
    chk_list["cumulative_gain_share_pct"] = (chk_list["exclusive_gain_cells"].cumsum() / chk_list["exclusive_gain_cells"].sum() * 100).round(1)
    chk_list = chk_list.drop(columns=["scenario"])
    chk_list.to_csv(HERE / "camera_field_check_list.csv", index=False, encoding="utf-8-sig")
    for sid in ("A_h0", "AB_h0"):
        sub_ = cam[cam["scenario"] == sid]
        pos = sub_[sub_["exclusive_gain_cells"] > 0]
        say(f"  {sid}: 회전 대상 {len(sub_)} 중 배타적 기여 >0 {len(pos)} (A {int((pos['tier']=='A').sum())}, B {int((pos['tier']=='B').sum())}), 배타적 기여 합 {pos['exclusive_gain_ha'].sum():.1f}ha")
    n80 = int((chk_list["cumulative_gain_share_pct"] < 80).sum()) + 1
    say(f"  AB_h0 현장 확인 목록 {len(chk_list)}대, 상위 {n80}대가 배타적 기여의 80%")
    say(f"  구별: {chk_list['district'].value_counts().to_dict()}")

    say(f"\ntotal {time.perf_counter() - start:.0f}s")
    (HERE / "run_log.txt").write_text("\n".join(log), encoding="utf-8")


if __name__ == "__main__":
    main()
