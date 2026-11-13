"""Read building outlines off Goad's fire insurance plans of Toronto (1880, 1889, 1903, 1913, 1924)
and write them to data/interim/plans/<year>.gpkg for pipeline/lost.py.

The plans are georeferenced scans served as map tiles (Toronto Public Library, Library and
Archives Canada and City of Toronto Archives, hosted by Esri Canada). They colour every building
by what it is made of: pink or red for brick, yellow for wood. A building here is ground whose
colour is clearly stronger than the paper around it, cut apart along the plan's ink lines.

It is a reading of the scans, not a survey: row houses whose party walls are drawn faintly come
out as one block, lettering leaves holes, and the plates sit a few metres off from one year to
the next.

Run: uv run --with pillow --with scipy --with rasterio pipeline/plans.py [year ...] [--area name] [--check out.png]
"""
import concurrent.futures
import io
import math
import pathlib
import sys
import urllib.request

import geopandas as gpd
import numpy as np
import rasterio.features
import shapely
from affine import Affine
from PIL import Image
from scipy import ndimage

ROOT = pathlib.Path(__file__).resolve().parent.parent
TILES = ROOT / "data" / "raw" / "plans"
OUT = ROOT / "data" / "interim" / "plans"
URL = "https://tiles.arcgis.com/tiles/jIL9msH9OI208GCb/arcgis/rest/services/Toronto{year}/MapServer/tile/{z}/{y}/{x}"
YEARS = [1880, 1889, 1903, 1913, 1924]
# The district read so far: Bathurst Street to the Don, the lake to Bloor Street (lon/lat).
DISTRICT = (-79.412, 43.636, -79.352, 43.674)
# Places outside the district, read with --area <name> and written to <year>_<name>.gpkg:
# box and the plans that draw it in detail
AREAS = {
    "island": ((-79.405, 43.609, -79.348, 43.636), [1913, 1924]),
    # (the old Trinity College on Queen Street West was read on its own at first; the district
    # and Parkdale now cover it between them, and its files were set aside so nothing is read twice)
    # Parkdale and the streets between it and the district: Bathurst Street to Roncesvalles
    # Avenue, the lake to Dundas Street. A village of its own until 1889.
    "parkdale": ((-79.452, 43.628, -79.412, 43.655), [1889, 1903, 1913, 1924]),
    # The rest of the old city, in boxes that do not overlap the ones above: the west end to the
    # Humber, everything north of Bloor Street, and east of the Don. The plans do not reach all
    # of it in every year; where a year has no plate, nothing is read.
    "west": ((-79.495, 43.628, -79.452, 43.655), [1889, 1903, 1913, 1924]),
    "northwest": ((-79.495, 43.655, -79.412, 43.674), [1880, 1889, 1903, 1913, 1924]),
    "north": ((-79.495, 43.674, -79.352, 43.735), [1880, 1889, 1903, 1913, 1924]),
    "east": ((-79.352, 43.640, -79.276, 43.735), [1880, 1889, 1903, 1913, 1924]),
}
Z = 18            # about 0.43 m of ground per pixel here
CHUNK = 6         # tiles per side worked on at once
UTM = 26917
EARTH = 20037508.342789244

VIVID = 30        # a building's colour: brightest channel less weakest, on average, at least
BRIGHT = 180      # ... and its brightest channel, on average, at least
STRONGER = 26     # how far below the paper a building's weakest colour channel lies (0-255)
INK = 115         # brightest channel darker than this is an ink line
MIN_M2, MAX_M2 = 18, 30000


def tile_of(lon, lat):
    n = 2 ** Z
    return (int((lon + 180) / 360 * n),
            int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n))


def fetch(year, x, y):
    path = TILES / str(year) / str(Z) / str(x) / f"{y}.png"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(URL.format(year=year, z=Z, x=x, y=y), headers={"User-Agent": "toronto-through-time"})
        try:
            data = urllib.request.urlopen(req, timeout=30).read()
        except Exception:  # no tile: outside the plates
            data = b""
        path.write_bytes(data)
    try:
        return np.asarray(Image.open(io.BytesIO(path.read_bytes())).convert("RGB"))
    except Exception:
        return np.full((256, 256, 3), 255, np.uint8)


def mosaic(year, x0, y0, nx, ny):
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        tiles = list(pool.map(lambda t: fetch(year, *t), [(x0 + i, y0 + j) for j in range(ny) for i in range(nx)]))
    return np.vstack([np.hstack(tiles[j * nx:(j + 1) * nx]) for j in range(ny)])


def read_buildings(rgb):
    """Label image of the buildings in a mosaic (0 = none) and a mask of the wooden ones."""
    rgb = rgb.astype(np.int16)
    weakest, brightest = rgb.min(-1), rgb.max(-1)
    # the paper: the palest ground within about 100 m
    small = weakest[::8, ::8]
    paper = ndimage.zoom(ndimage.percentile_filter(small, 88, size=31), 8, order=1)[:weakest.shape[0], :weakest.shape[1]]
    ink = brightest < INK
    # buildings are pink, red, yellow or orange; green and blue-green are water tints
    warm = rgb[..., 0] - rgb[..., 1] > 3
    coloured = (weakest < paper - STRONGER) & ~ink & warm
    coloured = ndimage.binary_opening(coloured, iterations=2)  # drops red street lines and specks
    # lettering on a building leaves holes; close small ones without bridging the ink lines
    filled = ndimage.binary_closing(coloured | (ink & ndimage.binary_dilation(coloured, iterations=3)), iterations=1)
    walls = ink & ~ndimage.binary_opening(ink, iterations=3)   # thin ink only: outlines, not black fills
    labels, _ = ndimage.label(filled & ~walls)
    wood = (rgb[..., 1] - rgb[..., 2]) > 1.2 * (rgb[..., 0] - rgb[..., 1])
    # A building is a bright, strong colour. Outside the detailed plates the atlas shows through
    # with its index map, whose brown lettering and stained paper would otherwise be read as
    # thousands of small buildings: those are dull, or dark.
    ids = np.arange(1, labels.max() + 1)
    if len(ids):
        strong = ndimage.mean(brightest - weakest, labels, ids) >= VIVID
        bright = ndimage.mean(brightest, labels, ids) >= BRIGHT
        labels = np.where(np.r_[False, strong & bright][labels], labels, 0)
        labels, _ = ndimage.label(labels > 0)      # numbered again without gaps
    return labels, wood


def polygons(labels, wood, x0, y0):
    """Buildings as polygons in web-mercator metres, with the share of each that is drawn as wood."""
    res = 2 * EARTH / (256 * 2 ** Z)
    transform = Affine(res, 0, x0 * 256 * res - EARTH, 0, -res, EARTH - y0 * 256 * res)
    n = labels.max()
    area = ndimage.sum_labels(np.ones_like(labels), labels, np.arange(1, n + 1))
    woody = ndimage.sum_labels(wood, labels, np.arange(1, n + 1)) / np.maximum(area, 1)
    rows = []
    for geom, value in rasterio.features.shapes(labels.astype(np.int32), mask=labels > 0, transform=transform):
        rows.append((shapely.geometry.shape(geom), woody[int(value) - 1]))
    return rows


def read_year(year, check=None, box=DISTRICT, suffix=""):
    x0, y1 = tile_of(box[0], box[1])
    x1, y0 = tile_of(box[2], box[3])
    rows = []
    for cy in range(y0, y1 + 1, CHUNK):
        for cx in range(x0, x1 + 1, CHUNK):
            # one tile of overlap, so a building on a seam is whole in one of the chunks
            rgb = mosaic(year, cx - 1, cy - 1, CHUNK + 2, CHUNK + 2)
            labels, wood = read_buildings(rgb)
            core = np.zeros(labels.shape, bool)
            core[256:-256, 256:-256] = True
            centre = ndimage.center_of_mass(np.ones_like(labels), labels, np.arange(1, labels.max() + 1))
            keep = np.zeros(labels.max() + 1, bool)
            for i, (r, c) in enumerate(centre, 1):
                keep[i] = core[int(r), int(c)]
            labels = np.where(keep[labels], labels, 0)
            rows += polygons(labels, wood, cx - 1, cy - 1)
            if check and cx == x0 + CHUNK * (((x1 - x0) // CHUNK) // 2) and cy == y0 + CHUNK * (((y1 - y0) // CHUNK) // 2):
                shade = rgb.copy()
                shade[labels > 0] = (0.45 * shade[labels > 0] + np.where(wood[labels > 0][:, None], [110, 90, 0], [0, 40, 140])).astype(np.uint8)
                edge = (labels > 0) & (ndimage.grey_erosion(labels, size=3) != ndimage.grey_dilation(labels, size=3))
                shade[edge] = [0, 0, 0]
                Image.fromarray(np.hstack([rgb, shade])[256:1280, :]).save(check)
        print(year, "row", cy - y0, "of", y1 - y0, len(rows), flush=True)
    g = gpd.GeoDataFrame({"wood": [w for _, w in rows]}, geometry=[p for p, _ in rows], crs=3857).to_crs(UTM)
    g["geometry"] = shapely.simplify(g.geometry.values, 0.6)
    g = g[(g.area >= MIN_M2) & (g.area <= MAX_M2)].reset_index(drop=True)
    OUT.mkdir(parents=True, exist_ok=True)
    g.to_file(OUT / f"{year}{suffix}.gpkg", driver="GPKG")
    print(year, f"{len(g):,} buildings, {g.area.sum() / 1e4:.0f} ha", flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    check = args[args.index("--check") + 1] if "--check" in args else None
    if "--area" in args:
        name = args[args.index("--area") + 1]
        for year in AREAS[name][1]:
            read_year(year, check, AREAS[name][0], f"_{name}")
    else:
        for year in [int(a) for a in args if a.isdigit()] or YEARS:
            read_year(year, check)
