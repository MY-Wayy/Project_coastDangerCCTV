#!/usr/bin/env python3
"""Download Copernicus GLO-30 DSM for the Busan coast window and reproject to EPSG:5186."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import Resampling, calculate_default_transform, reproject


BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"
CRS_ANALYSIS = "EPSG:5186"
# 부산 해안선 범위(128.761–129.305E, 34.884–35.330N) + 약 2km 여유
BUSAN_BOUNDS = (128.739, 34.862, 129.328, 35.352)
TILES = ["N34_00_E128_00", "N34_00_E129_00", "N35_00_E128_00", "N35_00_E129_00"]
RESOLUTION_M = 30.0


def tile_url(tile: str) -> str:
    name = f"Copernicus_DSM_COG_10_{tile}_DEM"
    return f"/vsicurl/{BUCKET}/{name}/{name}.tif"


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path,
        default=project_root / "data" / "raw" / "dem" / "busan_copernicus_dsm30_5186.tif",
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # COG 범위 요청으로 부산 창(window)만 읽는다
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        sources = [rasterio.open(tile_url(tile)) for tile in TILES]
        mosaic, transform = merge(sources, bounds=BUSAN_BOUNDS, nodata=-9999.0)
        src_crs = sources[0].crs
        for src in sources:
            src.close()

    data = mosaic[0].astype("float32")
    height, width = data.shape
    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs, CRS_ANALYSIS, width, height,
        *rasterio.transform.array_bounds(height, width, transform),
        resolution=RESOLUTION_M,
    )
    out = np.full((dst_height, dst_width), -9999.0, dtype="float32")
    reproject(
        data, out,
        src_transform=transform, src_crs=src_crs, src_nodata=-9999.0,
        dst_transform=dst_transform, dst_crs=CRS_ANALYSIS, dst_nodata=-9999.0,
        resampling=Resampling.bilinear,
    )

    profile = {
        "driver": "GTiff", "dtype": "float32", "count": 1,
        "width": dst_width, "height": dst_height,
        "crs": CRS_ANALYSIS, "transform": dst_transform, "nodata": -9999.0,
        "compress": "deflate", "tiled": True,
    }
    with rasterio.open(args.output, "w", **profile) as dst:
        dst.write(out, 1)
        dst.update_tags(
            source="Copernicus GLO-30 DSM (ESA, AWS open data)",
            note="DSM: includes some building/vegetation height; sea ~0m",
        )

    valid = out[out != -9999.0]
    print(f"saved {args.output} {dst_width}x{dst_height} @ {RESOLUTION_M}m")
    print(f"elevation min {valid.min():.1f} / median {np.median(valid):.1f} / max {valid.max():.1f} m")


if __name__ == "__main__":
    main()
