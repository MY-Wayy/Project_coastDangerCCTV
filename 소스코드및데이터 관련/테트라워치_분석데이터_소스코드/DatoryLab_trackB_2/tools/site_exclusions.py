"""Segments where new CCTV must not be installed: islands (GRP_ISL 02) + a manual list."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
MANUAL = PROJECT / "data" / "raw" / "manual_site_exclusions.csv"
ISLAND_CODE = 2  # 해안선 GRP_ISL: 01 육지부, 02 도서부


def manual_ids() -> set[str]:
    """해안선 원본상 육지부지만 현장 사정으로 설치 대상에서 빼는 구간 (예: 해저터널 구간 섬)."""
    if not MANUAL.exists():
        return set()
    return set(pd.read_csv(MANUAL, encoding="utf-8-sig")["segment_id"])


def excluded_mask(segments: pd.DataFrame) -> pd.Series:
    """True = 설치 제외(섬 또는 수동 제외). `segments`에는 segment_id, GRP_ISL이 있어야 한다."""
    return segments["GRP_ISL"].eq(ISLAND_CODE) | segments["segment_id"].isin(manual_ids())
