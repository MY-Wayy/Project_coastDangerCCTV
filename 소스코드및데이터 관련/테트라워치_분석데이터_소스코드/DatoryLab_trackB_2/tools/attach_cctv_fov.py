#!/usr/bin/env python3
"""Attach MOIS view-angle (촬영방면정보) attributes to integrated CCTV locations."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


# 촬영방면정보 → (view_type, horizontal FOV degrees)
VIEW_TYPE = {
    "360도 전방면": ("ptz_360", 360.0),
    "360도 전방향": ("ptz_360", 360.0),
    "회전": ("ptz_360", 360.0),
    "회전(열화상)": ("ptz_360", 360.0),
    "90도 정면": ("fixed", 90.0),
    "90도 전방": ("fixed", 90.0),
    "60도 단방향": ("fixed", 60.0),
    "고정": ("fixed", np.nan),
}


def read_csv(path: Path) -> pd.DataFrame:
    for encoding in ("cp949", "euc-kr", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Unable to decode {path}")


def site_view_attributes(mois_path: Path) -> pd.DataFrame:
    """Aggregate per coord_key using the same key as reanalyze_cctv_coverage.load_mois."""
    raw = read_csv(mois_path)
    raw["WGS84위도"] = pd.to_numeric(raw["WGS84위도"], errors="coerce")
    raw["WGS84경도"] = pd.to_numeric(raw["WGS84경도"], errors="coerce")
    valid = raw[
        raw["WGS84위도"].between(34.0, 36.0) & raw["WGS84경도"].between(128.0, 130.0)
    ].copy()
    valid["coord_key"] = (
        valid["WGS84위도"].round(7).astype(str) + "," + valid["WGS84경도"].round(7).astype(str)
    )
    view = valid["촬영방면정보"].map(VIEW_TYPE)
    valid["view_type"] = view.str[0].fillna("unknown")
    valid["fov_deg"] = pd.to_numeric(view.str[1], errors="coerce")
    valid["pixel_10k"] = pd.to_numeric(valid["카메라화소수"], errors="coerce")

    def joined(series: pd.Series) -> str:
        return "|".join(sorted({str(v).strip() for v in series.dropna() if str(v).strip()}))

    def site_type(series: pd.Series) -> str:
        # PTZ가 하나라도 있으면 지점 전체를 PTZ로 본다(가장 넓은 화각 기준)
        for value in ("ptz_360", "fixed"):
            if (series == value).any():
                return value
        return "unknown"

    return valid.groupby("coord_key", as_index=False).agg(
        view_raw=("촬영방면정보", joined),
        view_type=("view_type", site_type),
        fov_deg_max=("fov_deg", "max"),
        fov_known_rows=("fov_deg", "count"),
        pixel_10k_max=("pixel_10k", "max"),
        install_ym_min=("설치연월", "min"),
    )


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mois", type=Path,
        default=project_root / "data" / "raw" / "cctv_reanalysis" / "cctv_mois_busan.csv",
    )
    parser.add_argument(
        "--integrated", type=Path,
        default=project_root / "outputs" / "cctv_reanalysis" / "cctv_integrated_locations.csv",
    )
    parser.add_argument(
        "--output", type=Path,
        default=project_root / "outputs" / "cctv_reanalysis" / "cctv_integrated_locations_fov.csv",
    )
    args = parser.parse_args()

    integrated = pd.read_csv(args.integrated, encoding="utf-8-sig")
    views = site_view_attributes(args.mois)
    merged = integrated.merge(views, on="coord_key", how="left")
    # 행안부 외 출처(ITS·재난·교통 API)는 화각 원본이 없다
    merged["view_type"] = merged["view_type"].fillna("unknown")
    merged.to_csv(args.output, index=False, encoding="utf-8-sig")

    print(f"saved {args.output} ({len(merged):,} rows)")
    print(merged["view_type"].value_counts().to_string())
    print(merged.groupby("view_type")["fov_deg_max"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
