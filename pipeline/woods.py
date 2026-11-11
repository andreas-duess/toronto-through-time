"""Find the woods drawn on J.O. Browne's Map of the Township of York (1851) and write them to
data/interim/woods_1851.geojson for pipeline/streets.py.

The map fills wooded land with small tree symbols and leaves cleared land blank. This looks for
ground with that scatter of symbols: compact clumps of ink darker than the paper around them
(lines, hatching and large letters are longer pieces), counted in a window of WINDOW_M, and kept
where the area is at least OPEN_M wide and MIN_HA in size. Houses are clumps too, so the built-up
town is cut away afterwards, with the water (streets.py only uses woods
on dry land outside the built-up town). It is a reading of the scan, not a survey: an orchard
drawn with the same symbols counts as woods.

Run: uv run --with pillow --with scipy pipeline/woods.py [check.png]
"""
import json
import pathlib
import sys
import urllib.request
import zipfile

import geopandas as gpd
import numpy as np
import shapely
from PIL import Image
from scipy import ndimage

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAP = ROOT / "data" / "raw" / "histmaps" / "Browne_1851"
URL = "https://maps.library.utoronto.ca/datapub/toronto/historicalhydro/Browne_1851.zip"
OUT = ROOT / "data" / "interim" / "woods_1851.geojson"
UTM = 26917
CELL = 4          # metres per cell of the working grid
INK = 28          # how much darker than the paper around it a mark must be (0-255)
CLUMP_M2 = 190    # a tree symbol is a clump of ink at least this big ...
CLUMP_M = 64      # ... and no longer than this; they stand about 80 m apart
WINDOW_M = 200
CLUMPS = 3        # woods have at least this many clumps in a window
OPEN_M = 120      # dense areas narrower than this are lettering or lines
MIN_HA = 4
WORN = 20         # mean lightening over 40 m that marks a worn fold

Image.MAX_IMAGE_PIXELS = None


def load():
    if not (MAP / "1851Browne.york-1851x.jpg").exists():
        MAP.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(URL, headers={"User-Agent": "toronto-through-time"})
        (MAP / "Browne_1851.zip").write_bytes(urllib.request.urlopen(req).read())
        with zipfile.ZipFile(MAP / "Browne_1851.zip") as z:
            z.extractall(MAP)
    a, d, b, e, c, f = [float(x) for x in (MAP / "1851Browne.york-1851x.jgw").read_text().split()]
    return np.asarray(Image.open(MAP / "1851Browne.york-1851x.jpg").convert("L"), dtype=np.float32), (a, d, b, e, c, f)


def resample(img, world, bounds):
    """The scan on a north-up grid of CELL metres over bounds (UTM)."""
    a, d, b, e, c, f = world
    x0, y0, x1, y1 = bounds
    xs = np.arange(x0, x1, CELL) + CELL / 2
    ys = np.arange(y1, y0, -CELL) - CELL / 2
    X, Y = np.meshgrid(xs, ys)
    det = a * e - b * d
    col = (e * (X - c) - b * (Y - f)) / det
    row = (-d * (X - c) + a * (Y - f)) / det
    inside = (col >= 0) & (col < img.shape[1] - 1) & (row >= 0) & (row < img.shape[0] - 1)
    grid = ndimage.map_coordinates(img, [row, col], order=1, mode="nearest")
    return grid, inside


def find_woods(bounds):
    img, world = load()
    grid, inside = resample(img, world, bounds)
    paper = ndimage.median_filter(ndimage.zoom(grid, 0.25, order=1), size=25)
    paper = ndimage.zoom(paper, np.array(grid.shape) / np.array(paper.shape), order=1)
    ink = (paper - grid > INK) & inside
    # the folds of the sheet are worn pale and speckled: no reading there
    worn = ndimage.uniform_filter(np.maximum(grid - paper, 0), size=int(40 / CELL)) > WORN
    ink &= ~ndimage.binary_dilation(worn, iterations=int(16 / CELL))
    # a tree symbol is a compact clump of ink; lines, hatching and large letters are longer pieces
    labels, n = ndimage.label(ink, structure=np.ones((3, 3)))
    boxes = ndimage.find_objects(labels)
    size = ndimage.sum_labels(ink, labels, np.arange(1, n + 1))
    extent = np.array([max(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start) for sl in boxes]) * CELL
    clump = np.flatnonzero((size * CELL * CELL >= CLUMP_M2) & (extent <= CLUMP_M)) + 1
    centres = np.array(ndimage.center_of_mass(ink, labels, clump)).round().astype(int)
    count = np.zeros(ink.shape, np.float32)
    np.add.at(count, (centres[:, 0], centres[:, 1]), 1)
    w = int(WINDOW_M / CELL)
    dense = ndimage.binary_closing(ndimage.uniform_filter(count, size=w) * w * w >= CLUMPS, iterations=5)
    r = int(OPEN_M / 2 / CELL)
    disk = np.hypot(*np.mgrid[-r:r + 1, -r:r + 1]) <= r
    woods = ndimage.binary_closing(ndimage.binary_opening(dense, disk), disk)
    return woods, inside


def polygons(mask, bounds):
    x0, _, _, y1 = bounds
    labels, n = ndimage.label(mask)
    polys = []
    for i, sl in enumerate(ndimage.find_objects(labels), 1):
        part = labels[sl] == i
        if part.sum() * CELL * CELL < MIN_HA * 1e4:
            continue
        rows, cols = np.nonzero(part)
        cells = shapely.box(x0 + (sl[1].start + cols) * CELL, y1 - (sl[0].start + rows + 1) * CELL,
                            x0 + (sl[1].start + cols + 1) * CELL, y1 - (sl[0].start + rows) * CELL)
        polys.append(shapely.union_all(cells).buffer(8).buffer(-8).simplify(8))
    return polys


if __name__ == "__main__":
    old = gpd.read_file(ROOT / "data" / "raw" / "former_municipalities.geojson")
    old = old[old.AREA_NAME == "TORONTO"].to_crs(UTM).geometry.iloc[0]
    bounds = tuple(np.round(old.bounds, -1))
    woods, inside = find_woods(bounds)
    polys = polygons(woods, bounds)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(geometry=polys, crs=UTM).to_file(OUT, driver="GeoJSON")
    print(f"woods 1851: {len(polys)} areas, {sum(p.area for p in polys) / 1e4:.0f} ha;",
          f"the scan covers {inside.mean():.0%} of the grid")
    if len(sys.argv) > 1:  # picture for checking by eye: the scan with the woods outlined
        img, world = load()
        grid, _ = resample(img, world, bounds)
        rgb = np.stack([grid] * 3, -1).astype(np.uint8)
        import rasterio.features  # only for this picture
        from affine import Affine
        kept = rasterio.features.rasterize(polys, out_shape=woods.shape,
                                           transform=Affine(CELL, 0, bounds[0], 0, -CELL, bounds[3])) > 0
        rgb[kept] = (rgb[kept] * 0.6 + np.array([0, 100, 0])).astype(np.uint8)
        rgb[~inside] = [255, 200, 200]
        Image.fromarray(rgb).save(sys.argv[1])
