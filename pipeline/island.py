"""Read the outline of the Toronto Islands off Goad's fire insurance plans and write it to
data/interim/island/<year>.geojson for pipeline/water.py.

The 1913 and 1924 atlases have detailed Island plates, laid over the small index map: land on
pale paper, lagoons tinted blue-green, the lake and harbour the index map's olive green. Land is
what is redder than it is green, inside the Island zone of water.py. Where no detailed plate
covers the Island, the land is the index map's, which is small-scale and rough.
The 1889 and 1903 atlases draw the Island in outline only, without colour, so this cannot read
them.

Run: uv run --with pillow --with scipy --with rasterio pipeline/island.py [check.png]
"""
import pathlib
import sys

import geopandas as gpd
import numpy as np
import rasterio.features
import shapely
from affine import Affine
from PIL import Image
from scipy import ndimage

import plans
import water

OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "interim" / "island"
YEARS = [1913, 1924]
BOX = (-79.418, 43.606, -79.343, 43.6345)   # lon/lat around the Island
Z = 16            # about 1.7 m of ground per pixel
MIN_HA = 1
EARTH = 20037508.342789244


def tile_of(lon, lat):
    plans.Z, keep = Z, plans.Z
    try:
        return plans.tile_of(lon, lat)
    finally:
        plans.Z = keep


def mosaic(year):
    x0, y1 = tile_of(BOX[0], BOX[1])
    x1, y0 = tile_of(BOX[2], BOX[3])
    plans.Z, keep = Z, plans.Z
    try:
        rgb = plans.mosaic(year, x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    finally:
        plans.Z = keep
    res = 2 * EARTH / (256 * 2 ** Z)
    return rgb, Affine(res, 0, x0 * 256 * res - EARTH, 0, -res, EARTH - y0 * 256 * res)


def land_mask(rgb):
    smooth = ndimage.uniform_filter(rgb.astype(np.float32), size=(7, 7, 1))
    r, g, b = smooth[..., 0], smooth[..., 1], smooth[..., 2]
    blank = (rgb.max(-1) < 12) | (rgb.min(-1) > 250)      # outside the plates
    # The water of the index map is olive green and the lagoons blue-green. Land is cream (pale,
    # a little redder than green), white, or the index map's strong yellow and orange. Brown
    # stains on the water are a little redder than green too, but dull.
    cream = (r - g >= REDDER) & ((b > 165) | (r - g >= 22))
    white = (b > 185) & (g - r < 4)
    land = (cream | white) & ~blank
    land = ndimage.binary_opening(land, iterations=5)     # drops lettering and red lines on the water
    return ndimage.binary_closing(land, iterations=3), blank


REDDER = 5        # land is redder than it is green by at least this much (0-255)


if __name__ == "__main__":
    zone = gpd.GeoSeries([shapely.Polygon(water.ISLAND_ZONE)], crs=4326).to_crs(3857).iloc[0]
    OUT.mkdir(parents=True, exist_ok=True)
    panels = []
    for year in YEARS:
        rgb, transform = mosaic(year)
        land, blank = land_mask(rgb)
        shapes = [shapely.geometry.shape(g) for g, v in rasterio.features.shapes(land.astype(np.uint8), mask=land, transform=transform)]
        g = gpd.GeoSeries(shapes, crs=3857).intersection(zone).to_crs(water.UTM)
        g = g[g.area >= MIN_HA * 1e4]
        island = shapely.simplify(shapely.union_all(g.values).buffer(0), 4)
        gpd.GeoSeries([island], crs=water.UTM).to_file(OUT / f"{year}.geojson", driver="GeoJSON")
        print(year, f"{island.area / 1e4:.0f} ha in {len(shapely.get_parts(island))} pieces; plates cover {1 - blank.mean():.0%}", flush=True)
        shade = rgb.copy()
        shade[land] = (0.5 * shade[land] + [120, 0, 0]).astype(np.uint8)
        panels.append(np.vstack([rgb, shade]))
    if len(sys.argv) > 1:
        Image.fromarray(np.hstack(panels)).save(sys.argv[1])
