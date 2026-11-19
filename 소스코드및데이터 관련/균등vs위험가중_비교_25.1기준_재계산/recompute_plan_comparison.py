#!/usr/bin/env python3
"""fig08 왼쪽(핵심 사각 v4 34구간 가시율) 균등 vs 위험도 가중 비교를 기준선 두 개로 다시 계산.

원본 tools/trackA_compare_plans.py 는 기준선이 conservative_after_rotation(기존 커버율 31.98%)으로
고정되어 있어, 보고서 본문·fig08 오른쪽(구·군 배분)이 쓰는 original_360(25.1%)과 맞지 않는다.

- 원본 폴더(통합완료 데이터 관련/DatoryLab_trackB_2)의 모듈·데이터는 읽기만 한다
- 신규 입지 순위는 원본 new_sites_ranked*.csv 의 해당 baseline 행을 그대로 쓴다 (그리디 재실행 없음)
- conservative_after_rotation 결과는 원본 plan_comparison.csv 와 같아야 한다 (계산 검증용)

필요 패키지:  pip install geopandas rasterio shapely pandas numpy
실행:  python recompute_plan_comparison.py   → 같은 폴더에 plan_comparison_both_baselines.csv 생성
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
TRACK = HERE.parent / "통합완료 데이터 관련" / "DatoryLab_trackB_2"
sys.path.insert(0, str(TRACK / "tools"))
from viewshed_new_sites import baselines, candidate_cells, candidate_sites  # noqa: E402
from viewshed_sensitivity import VS_DIR, Context  # noqa: E402

WEIGHTS = TRACK / "outputs" / "trackD" / "trackB_weights.csv"  # 위험지수, 섬 0
CANDIDATES = TRACK / "outputs" / "trackD" / "cctv_candidates_v4.csv"
ORIGINAL_TABLE = TRACK / "outputs" / "trackD" / "plan_comparison.csv"
PLANS = {
    "균등 배치": VS_DIR / "new_sites_ranked.csv",
    "위험도 가중 배치": VS_DIR / f"new_sites_ranked_{WEIGHTS.stem}.csv",
}
BASELINES = ["original_360", "conservative_after_rotation"]
N_LIST = [0, 10, 20, 50]
OUT = HERE / "plan_comparison_both_baselines.csv"


def main() -> None:
    ctx = Context()
    base_sets = baselines(ctx)
    cands = candidate_sites(ctx)
    cells = candidate_cells(ctx, cands)
    index = {cid: i for i, cid in enumerate(cands["candidate_id"])}

    w = pd.read_csv(WEIGHTS, encoding="utf-8-sig").set_index("segment_id")["weight"]
    seg_w = pd.Series(ctx.zone["segment_id"]).map(w).fillna(0).to_numpy()
    cell_w = np.concatenate([[0.0], seg_w])[ctx.zone_grid]
    cand_ids = set(pd.read_csv(CANDIDATES, encoding="utf-8-sig")["segment_id"])
    cand_seg = pd.Series(ctx.zone["segment_id"]).isin(cand_ids).to_numpy()
    cand_cell = np.concatenate([[False], cand_seg])[ctx.zone_grid]

    rows = []
    for baseline in BASELINES:
        for plan, path in PLANS.items():
            ranked = pd.read_csv(path, encoding="utf-8-sig")
            ranked = ranked[ranked["baseline"] == baseline]
            for n in N_LIST:
                covered = base_sets[baseline].copy()
                for cid in ranked.loc[ranked["rank"] <= n, "candidate_id"]:
                    covered[cells[index[cid]]] = True
                rows.append({
                    "baseline": baseline, "plan": plan, "new_cameras": n,
                    "coast_coverage_pct": round(covered.sum() / ctx.zone_cells * 100, 1),
                    "risk_weighted_coverage_pct": round(cell_w[covered].sum() / cell_w.sum() * 100, 1),
                    "candidates_v4_coverage_pct": round(covered[cand_cell].sum() / cand_cell.sum() * 100, 1),
                })
    table = pd.DataFrame(rows)
    table.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(table.to_string(index=False))

    # 원본 표(conservative_after_rotation, 10·20·50대)와 일치하는지 확인
    original = pd.read_csv(ORIGINAL_TABLE, encoding="utf-8-sig")
    mine = table[table["baseline"] == "conservative_after_rotation"].drop(columns="baseline")
    merged = original.merge(mine, on=["plan", "new_cameras"], suffixes=("_orig", "_new"))
    cols = ["coast_coverage_pct", "risk_weighted_coverage_pct", "candidates_v4_coverage_pct"]
    same = all((merged[f"{c}_orig"] == merged[f"{c}_new"]).all() for c in cols)
    print("\n원본 plan_comparison.csv 재현:", "일치" if same and len(merged) == len(original) else "불일치")
    print("saved", OUT)


if __name__ == "__main__":
    main()
