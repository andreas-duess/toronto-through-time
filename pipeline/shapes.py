"""The shapes of buildings from the City's detailed 3D model: data/interim/shapes.gpkg.

The City publishes its 3D massing twice: as outlines with one height each (what build.py starts
from) and as a "multipatch" model with every roof surface of every building
(data/raw/multipatch_2025, open data "3D Massing"). For a house the two say the same. For a
building with towers, wings and decks the outline edition has one outline as tall as its highest
point; the detailed one has the real thing.

This reads the detailed model and turns each building that is more than one flat-topped block
into a few blocks: its roof surfaces are sorted into bands of height from the top down, and each
band becomes a block with the outline of what shows of it from above, at the band's average
height. A sloped roof comes out as steps. Overhangs, balconies and other pieces under 12 m2 or
narrower than 1.5 m are dropped. Buildings that are one block are left out: build.py keeps the
outline edition for them.

Writes blocks (UTM): feature (tile and number), height (m above the ground), geometry.

Run: uv run --no-project --python 3.12 --with fiona --with geopandas --with pyproj pipeline/shapes.py [tile ...] [--area ETOBICOKE]
(Python 3.12 because fiona, which can read this file, has no build for newer ones.)
"""
import multiprocessing
import pathlib
import sys

import fiona
import geopandas as gpd
import numpy as np
import shapely

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODEL = ROOT / "data" / "raw" / "multipatch_2025" / "3DMassingMultipatch_2025_WGS84.gdb"
OUT = ROOT / "data" / "interim" / "shapes.gpkg"
UTM = "EPSG:26917"
BAND = 3.0        # metres of height in one block, at least
MAX_BLOCKS = 10
MIN_AREA = 12     # m2
MIN_WIDTH = 1.5   # m
GROUND = 2.0      # roof surfaces lower than this above the building's foot are the ground


def roofs(geometry, scale):
    """The roof surfaces of a building: outlines (2D, metres) and their mean heights."""
    rings, heights = [], []
    foot = min(p[2] for poly in geometry["coordinates"] for p in poly[0])
    for poly in geometry["coordinates"]:
        ring = np.asarray(poly[0], float)[:, :3]
        if len(ring) < 4:
            continue
        xy = ring[:, :2] * scale
        x, y, z = xy[:-1, 0], xy[:-1, 1], ring[:-1, 2]
        xn, yn, zn = np.roll(x, -1), np.roll(y, -1), np.roll(z, -1)
        # twice the area of the surface seen from above, from the side and from the front
        up = np.sum(x * yn - xn * y)
        side = np.hypot(np.sum(y * zn - yn * z), np.sum(z * xn - zn * x))
        if abs(up) < 0.4 or abs(up) < 0.3 * np.hypot(up, side) or z.mean() < foot + GROUND:
            continue
        rings.append(xy)
        heights.append(z.mean() - foot)
    return rings, np.array(heights)


def blocks(rings, heights):
    """Blocks [(outline, height)] from roof surfaces, from the top band down."""
    faces = shapely.make_valid(shapely.polygons([shapely.linearrings(r) for r in rings]))
    order = np.argsort(-heights)
    faces, heights = faces[order], heights[order]
    areas = shapely.area(faces)
    band = max(BAND, 0.1 * heights[0])
    while True:
        out, covered, i = [], None, 0
        while i < len(faces):
            j = i
            while j < len(faces) and heights[j] >= heights[i] - band:
                j += 1
            part = shapely.union_all(faces[i:j])
            seen = part if covered is None else part.difference(covered)
            seen = seen.buffer(-MIN_WIDTH / 2).buffer(MIN_WIDTH / 2)
            for piece in shapely.get_parts(seen):
                if piece.geom_type == "Polygon" and piece.area >= MIN_AREA:
                    out.append((piece, float(np.average(heights[i:j], weights=np.maximum(areas[i:j], 1e-6)))))
            covered = part if covered is None else covered.union(part)
            i = j
        if len(out) <= MAX_BLOCKS:
            return out
        band *= 1.6


def tile(name):
    rows = []
    with fiona.open(MODEL, layer=name) as src:
        scale = np.cos(np.radians(43.66))     # web mercator to metres at Toronto
        for n, f in enumerate(src):
            g = f["geometry"]
            if not g or g["type"] != "MultiPolygon" or len(g["coordinates"]) < 12:
                continue        # a box: one roof, one floor and the walls
            try:
                rings, heights = roofs(g, scale)
                if len(rings) < 2 or heights.max() - heights.min() < BAND:
                    continue
                found = blocks(rings, heights)
            except Exception as e:      # a broken surface in one building
                print(f"  {name} {n}: {type(e).__name__}", flush=True)
                continue
            if len(found) < 2:
                continue
            for outline, height in found:
                rows.append({"feature": f"{name}/{n}", "height": round(height, 2),
                             "geometry": shapely.affinity.scale(outline, 1 / scale, 1 / scale, origin=(0, 0))})
    if not rows:
        return None
    g = gpd.GeoDataFrame(rows, geometry="geometry", crs=3857).to_crs(UTM)
    g["geometry"] = shapely.simplify(g.geometry.values, 0.3)
    return g


if __name__ == "__main__":
    import shapely.affinity  # noqa: F401
    # --area ETOBICOKE: the tiles over that former municipality, written to shapes_etobicoke.gpkg
    area = sys.argv[sys.argv.index("--area") + 1].upper() if "--area" in sys.argv else "TORONTO"
    if area != "TORONTO":
        OUT = OUT.with_name(f"shapes_{area.lower().replace(' ', '_')}.gpkg")
    names = [a for a in sys.argv[1:] if a.startswith("Multipatch")]
    if not names:
        old = gpd.read_file(ROOT / "data" / "raw" / "former_municipalities.geojson")
        old = old[old.AREA_NAME == area].to_crs(3857).geometry.iloc[0]
        for name in fiona.listlayers(MODEL):
            if name.startswith("Multipatch"):
                with fiona.open(MODEL, layer=name) as src:
                    if len(src) and shapely.box(*src.bounds).intersects(old):
                        names.append(name)
    print(len(names), "tiles", flush=True)
    with multiprocessing.Pool(8) as pool:
        parts = [p for p in pool.imap_unordered(tile, names) if p is not None]
    out = gpd.GeoDataFrame(__import__("pandas").concat(parts, ignore_index=True), crs=UTM)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_file(OUT, driver="GPKG")
    print(f"{out.feature.nunique():,} buildings in {len(out):,} blocks", flush=True)
