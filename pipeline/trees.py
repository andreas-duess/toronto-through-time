"""Today's trees, for the last year of the map: web/public/data/trees.positions.pack and
trees.sizes.pack.

The city's 2018 tree canopy study (Forest and Land Cover, open data) classed every 0.6 m of
ground from satellite images and lidar; class 1 is tree canopy. It gives the canopy, not single
trees, so the trees are placed here: one in the middle of every crown or clump, sized to it, and
more on a loose grid where the canopy is wider than one tree. Where trees stand is from the
study; how many there are in a wood, and each one's size, is drawn.

Needs data/raw/landcover_2018 (download.py) and the buildings (build.py).
Run: uv run --with rasterio --with pyogrio --with scipy pipeline/trees.py
"""
import json
import pathlib

import geopandas as gpd
import numpy as np
import rasterio.features
import shapely
from affine import Affine
from scipy import ndimage
from scipy.spatial import cKDTree

import pack

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "web" / "public" / "data"
MTM = 2952        # the study's own grid, in metres
CELL = 1.5        # metres
MIN_CROWN = 1.5   # canopy narrower than twice this is left out
MAX_CROWN = 6.0   # the widest crown radius drawn
APART = 7.5       # metres between the middles of two crowns, at least
GRID = 8.0        # spacing of the trees that fill wide canopy


def canopy(area="TORONTO", roofs=None):
    """The tree canopy of a former municipality as a grid, without what lies over a building
    (roofs: the buildings' outlines; for the old city they are read from the page's files)."""
    old = gpd.read_file(RAW / "former_municipalities.geojson")
    old = old[old.AREA_NAME == area].to_crs(MTM).geometry.iloc[0]
    x0, y0, x1, y1 = old.bounds
    shape = (int((y1 - y0) / CELL) + 1, int((x1 - x0) / CELL) + 1)
    transform = Affine(CELL, 0, x0, 0, -CELL, y0 + shape[0] * CELL)
    cover = gpd.read_file(RAW / "landcover_2018" / "LandCover2018.gdb", bbox=old.bounds, engine="pyogrio",
                          where="gridcode = 1", columns=["gridcode"])
    grid = rasterio.features.rasterize(shapely.make_valid(cover.geometry.values), shape, transform=transform, dtype="uint8")
    grid &= rasterio.features.rasterize([old], shape, transform=transform, dtype="uint8")
    if roofs is None:
        origin = json.loads((OUT / "meta.json").read_text())["origin"]
        pos = np.fromfile(OUT / "positions.bin", "<f4").reshape(-1, 3)[:, :2].astype(float) + origin
        starts = np.fromfile(OUT / "starts.bin", "<u4")
        roofs = gpd.GeoSeries([shapely.Polygon(pos[a:b]) for a, b in zip(starts[:-1], starts[1:]) if b - a >= 3], crs=4326)
    roofs = roofs.to_crs(MTM)
    grid[rasterio.features.rasterize(roofs.values, shape, transform=transform, dtype="uint8") == 1] = 0
    return grid, transform


def place(grid, rng):
    """Middles (row, column) and crown radii (m) of the trees."""
    inside = ndimage.distance_transform_edt(grid).astype(np.float32) * CELL    # metres to the canopy's edge
    inside += rng.random(inside.shape, dtype=np.float32) * 0.01                # no ties on flat tops
    size = int(APART / CELL) | 1
    crowns = np.argwhere((inside == ndimage.maximum_filter(inside, size)) & (inside >= MIN_CROWN))
    # wide canopy: a loose grid, each tree moved a little, kept where no crown is close
    step = GRID / CELL
    rows, cols = np.mgrid[0:grid.shape[0]:step, 0:grid.shape[1]:step]
    fill = np.stack([rows.ravel(), cols.ravel()], 1) + rng.uniform(-0.3, 0.3, (rows.size, 2)) * step
    fill = fill[(fill[:, 0] < grid.shape[0] - 1) & (fill[:, 1] < grid.shape[1] - 1) & (fill.min(1) >= 0)].round().astype(int)
    fill = fill[inside[fill[:, 0], fill[:, 1]] >= MIN_CROWN + 1]
    near, _ = cKDTree(crowns).query(fill, distance_upper_bound=0.8 * APART / CELL)
    fill = fill[np.isinf(near)]
    at = np.vstack([crowns, fill])
    radius = inside[at[:, 0], at[:, 1]] * 1.15
    radius[len(crowns):] = 3.6
    return at, np.clip(radius * rng.uniform(0.85, 1.15, len(at)), 2, MAX_CROWN)


if __name__ == "__main__":
    rng = np.random.default_rng(1)
    grid, transform = canopy()
    print(f"canopy {grid.sum() * CELL ** 2 / 1e4:.0f} ha", flush=True)
    at, radius = place(grid, rng)
    x, y = transform * (at[:, 1] + 0.5, at[:, 0] + 0.5)
    lonlat = shapely.get_coordinates(gpd.GeoSeries(gpd.points_from_xy(x, y), crs=MTM).to_crs(4326).values)
    origin = json.loads((OUT / "meta.json").read_text())["origin"]
    # in strips from west to east, so that a tree is close to the one before it in the file
    order = np.lexsort([np.where((at[:, 0] // 100) % 2, -at[:, 1], at[:, 1]), at[:, 0] // 100])
    size = pack.write("trees.positions.pack", pack.deltas((lonlat - origin)[order]))
    size += pack.write("trees.sizes.pack", np.round(radius[order] * 10).astype("u1"))
    print(f"{len(at):,} trees, {size / 1e6:.1f} MB", flush=True)
