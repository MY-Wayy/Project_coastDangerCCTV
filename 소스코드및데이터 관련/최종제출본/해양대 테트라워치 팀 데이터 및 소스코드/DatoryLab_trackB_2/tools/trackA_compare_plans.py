#!/usr/bin/env python3
"""Compare uniform vs risk-weighted (Track D trackB_weights) new-site plans: coast, risk-weighted and candidate coverage."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from viewshed_new_sites import baselines, candidate_cells, candidate_sites  # noqa: E402
from viewshed_sensitivity import VS_DIR, Context  # noqa: E402


PROJECT = Path(__file__).resolve().parents[1]
WEIGHTS = PROJECT / "outputs" / "trackD" / "trackB_weights.csv"  # 위험지수, 섬 0
CANDIDATES = PROJECT / "outputs" / "trackD" / "cctv_candidates_v4.csv"
PLANS = {
    "균등 배치": VS_DIR / "new_sites_ranked.csv",
    "위험도 가중 배치": VS_DIR / f"new_sites_ranked_{WEIGHTS.stem}.csv",
}
N_LIST = [10, 20, 50]
BASELINE = "conservative_after_rotation"


def main() -> None:
    ctx = Context()
    base = baselines(ctx)[BASELINE]
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
    for plan, path in PLANS.items():
        ranked = pd.read_csv(path, encoding="utf-8-sig")
        ranked = ranked[ranked["baseline"] == BASELINE]
        for n in N_LIST:
            covered = base.copy()
            for cid in ranked.loc[ranked["rank"] <= n, "candidate_id"]:
                covered[cells[index[cid]]] = True
            rows.append({
                "plan": plan, "new_cameras": n,
                "coast_coverage_pct": round(covered.sum() / ctx.zone_cells * 100, 1),
                "risk_weighted_coverage_pct": round(cell_w[covered].sum() / cell_w.sum() * 100, 1),
                "candidates_v4_coverage_pct": round(covered[cand_cell].sum() / cand_cell.sum() * 100, 1),
            })
    table = pd.DataFrame(rows)
    out = PROJECT / "outputs" / "trackD" / "plan_comparison.csv"
    table.to_csv(out, index=False, encoding="utf-8-sig")
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
