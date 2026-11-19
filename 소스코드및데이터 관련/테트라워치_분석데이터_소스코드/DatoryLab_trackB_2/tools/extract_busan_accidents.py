#!/usr/bin/env python3
"""Extract Busan-sea coastal accidents from the national 생활안전지도 해양사고발생현황 file.

전국 31,911건 → 부산 해역 2,138건 (`부산전체_행정안전부_연안사고.csv`).
- x, y (EPSG:3857)를 WGS84로 바꿔 lon_exact, lat_exact 칼럼을 붙이고 아래 경위도 범위로 거른다
- 범위는 기존 추출본 2,138건과 같은 결과를 내는 값이다 (원래 추출 코드는 남아 있지 않음)
- 출력 파일이 이미 있으면 덮어쓰지 않고 비교만 한다. 다시 쓰려면 --overwrite
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

# 부산 해역 경위도 범위 (WGS84)
LON_RANGE = (128.7465, 129.402)
LAT_RANGE = (34.861, 35.337)


def extract(national: pd.DataFrame) -> pd.DataFrame:
    lon, lat = Transformer.from_crs(3857, 4326, always_xy=True).transform(
        national["x"].to_numpy(), national["y"].to_numpy()
    )
    out = national.assign(lon_exact=lon, lat_exact=lat)
    return out[out["lon_exact"].between(*LON_RANGE) & out["lat_exact"].between(*LAT_RANGE)]


def compare(new: pd.DataFrame, existing: pd.DataFrame) -> bool:
    """행·칼럼 순서와 값이 같은지. lon/lat_exact는 PROJ 버전에 따라 끝자리가 달라 1e-9°까지 허용."""
    if list(new.columns) != list(existing.columns) or len(new) != len(existing):
        return False
    new, existing = new.reset_index(drop=True), existing.reset_index(drop=True)
    exact = ["lon_exact", "lat_exact"]
    rest = [c for c in new.columns if c not in exact]
    return new[rest].equals(existing[rest]) and np.allclose(new[exact], existing[exact], rtol=0, atol=1e-9)


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--national", type=Path,
        default=project_root / "data" / "raw" / "accidents" / "행정안전부_생활안전지도 해양사고발생현황.csv",
    )
    parser.add_argument(
        "--output", type=Path,
        default=project_root / "부산전체_행정안전부_연안사고.csv",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    national = pd.read_csv(args.national, encoding="utf-8-sig", low_memory=False)
    busan = extract(national)
    print(f"national {len(national):,} rows → Busan sea {len(busan):,} rows")
    print(busan["polc_nm"].value_counts().to_string())

    if args.output.exists() and not args.overwrite:
        existing = pd.read_csv(args.output, encoding="utf-8-sig", low_memory=False)
        print(f"compare with {args.output.name}:", "일치" if compare(busan, existing) else "불일치")
        return
    # 기존 파일과 같은 형식 (utf-8 BOM, CRLF)
    busan.to_csv(args.output, index=False, encoding="utf-8-sig", lineterminator="\r\n")
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
