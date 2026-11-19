#!/usr/bin/env python3
"""Track D one-line query: segment info (+ that hour's weather when station_hourly.csv exists).

    python tools/trackD_query.py SEG_000123 ["2026-05-12 03:00"]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


OUT = Path(__file__).resolve().parents[1] / "outputs" / "trackD"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    seg_id = sys.argv[1]
    when = pd.Timestamp(sys.argv[2]) if len(sys.argv) > 2 else None

    seg = pd.read_csv(OUT / "segments.csv", encoding="utf-8-sig").set_index("segment_id")
    if seg_id not in seg.index:
        sys.exit(f"없는 구간: {seg_id}")
    s = seg.loc[seg_id]
    th = pd.read_csv(OUT / "station_thresholds.csv", encoding="utf-8-sig").set_index("배정관측소").loc[s["배정관측소"]]

    rows = [
        ("구간", "위치", f"{s['구']} ({s['lat']}, {s['lon']}) · {'육지부' if s['육지부'] else '도서부(섬)'}"),
        ("구간", "해안유형", f"{s['해안유형']} (CAT_COA {s['CAT_COA']}), {s['segment_length_m']} m"),
        ("구간", "위험등급", f"{s['위험등급']} (위험지수 {s['위험지수']})"),
        ("구간", "배정 관측소", f"{s['배정관측소']} ({s['노출그룹']}) · 임계 파고 {th['파고임계_m']} m / 풍속 {th['풍속임계_ms']} m/s"),
        ("구간", "최근접 CCTV", f"{s['nearest_cctv_m']:,.0f} m (500m 내 {s['cctv_count_500m']}개)"),
        ("구간", "지형 반영 가시 커버율", f"{s['view_coverage_pct_conservative']}% (보수적) / {s['view_coverage_pct_original']}% (기존 가정)"),
    ]

    hourly_path = OUT / "station_hourly.csv"
    if when is not None:
        if not hourly_path.exists():
            rows.append(("그 시각", "기상", "station_hourly.csv 없음 — 트랙 D 시간표를 outputs/trackD/에 넣으세요"))
        else:
            hourly = pd.read_csv(hourly_path, encoding="utf-8-sig")
            time_col = next(c for c in hourly.columns if c in ("시각", "datetime", "time", "tm"))
            station_col = next(c for c in hourly.columns if c in ("관측소", "station"))
            hourly[time_col] = pd.to_datetime(hourly[time_col])
            hit = hourly[(hourly[station_col] == s["배정관측소"]) & (hourly[time_col] == when)]
            if hit.empty:
                rows.append(("그 시각", "기상", f"{when} {s['배정관측소']} 자료 없음"))
            else:
                for col, val in hit.iloc[0].drop([time_col, station_col]).items():
                    rows.append(("그 시각", col, val))

    width = max(len(str(r[1])) for r in rows)
    print(f"{seg_id}" + (f" @ {when}" if when is not None else ""))
    for group, key, val in rows:
        print(f"  [{group}] {str(key).ljust(width)}  {val}")


if __name__ == "__main__":
    main()
