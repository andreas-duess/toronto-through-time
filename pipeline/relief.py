"""The shape of the ground, for the shaded hills and valleys: web/public/relief/{z}/{x}/{y}.png.

From Natural Resources Canada's High Resolution Digital Elevation Model (the bare-earth "DTM" of
the 2 m mosaic), which over Toronto is made from the lidar surveys Ontario flies. The file is
read over the internet, only the part over the city and at the detail needed. It is today's
ground: filled ravines and buried creeks are as they are now.

Writes map tiles for zooms 10 to 14 (about 7 m of ground per pixel at 14) in the "terrarium"
encoding MapLibre reads: height = red * 256 + green + blue / 256 - 32768 metres. Heights are
kept to a quarter metre, which makes the files much smaller.

Run: uv run --with rasterio --with pillow --with shapely pipeline/relief.py
"""
import math
import pathlib

import json

import numpy as np
import rasterio
import shapely
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "relief"
SOURCE = "https://canelevation-dem.s3.ca-central-1.amazonaws.com/hrdem-mosaic-2m/8_2-mosaic-2m-dtm.tif"
BOX = (-79.66, 43.56, -79.09, 43.88)      # west, south, east, north: the city and a little around it
ZOOM, FIRST_ZOOM = 14, 10
LAKE = 74.0                               # metres: where the model has no ground, Lake Ontario
EARTH = 20037508.342789244
CITY = shapely.union_all([shapely.geometry.shape(f["geometry"]) for f in
                           json.loads((ROOT / "data" / "raw" / "former_municipalities.geojson").read_text())["features"]]).buffer(0.01)


def tile(lon, lat, z):
    n = 2 ** z
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def lonlat(x, y, z):
    n = 2 ** z
    return x / n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))


def wanted(z, x, y):
    """Whether a tile is kept: at the two closest zooms, only those over the city."""
    (w, n), (e, s) = lonlat(x, y, z), lonlat(x + 1, y + 1, z)
    return z < 13 or CITY.intersects(shapely.box(w, s, e, n))


if __name__ == "__main__":
    x0, y0 = tile(BOX[0], BOX[3], ZOOM)
    x1, y1 = tile(BOX[2], BOX[1], ZOOM)
    # whole tiles at the first zoom, so every zoom's tiles are complete
    step = 2 ** (ZOOM - FIRST_ZOOM)
    x0, y0, x1, y1 = x0 // step * step, y0 // step * step, (x1 // step + 1) * step, (y1 // step + 1) * step
    wide, high = (x1 - x0) * 256, (y1 - y0) * 256
    size = 2 * EARTH / 2 ** ZOOM
    bounds = (-EARTH + x0 * size, EARTH - y1 * size, -EARTH + x1 * size, EARTH - y0 * size)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"), rasterio.open(SOURCE) as src:
        with WarpedVRT(src, crs="EPSG:3857", transform=from_bounds(*bounds, wide, high), width=wide, height=high,
                       resampling=Resampling.bilinear) as vrt:
            ground = vrt.read(1, masked=True).astype("float32").filled(np.nan)
    print(f"{wide} x {high} pixels, {np.isnan(ground).mean():.0%} without ground, {np.nanmin(ground):.0f} to {np.nanmax(ground):.0f} m", flush=True)
    ground = np.where(np.isnan(ground) | (ground < LAKE), LAKE, ground)
    files = total = 0
    for z in range(ZOOM, FIRST_ZOOM - 1, -1):
        k = 2 ** (ZOOM - z)
        level = ground.reshape(high // k, k, wide // k, k).mean(axis=(1, 3)) if k > 1 else ground
        v = np.round(level * 4) / 4 + 32768
        rgb = np.dstack([v // 256, v % 256 // 1, v % 1 * 256]).astype("uint8")
        for i in range((x1 - x0) // k):
            for j in range((y1 - y0) // k):
                part = rgb[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256]
                if (level[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256] == LAKE).all():
                    continue        # open lake
                if not wanted(z, x0 // k + i, y0 // k + j):
                    continue
                f = OUT / str(z) / str(x0 // k + i) / f"{y0 // k + j}.png"
                f.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(part).save(f, optimize=True)
                files += 1
                total += f.stat().st_size
        print(f"zoom {z}: {files} files, {total / 1e6:.1f} MB so far", flush=True)
