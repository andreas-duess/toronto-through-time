"""Pictures of the sources for the "How it was made" page: web/public/img/.

One downtown block (Bay Street to Yonge Street, Front Street to King Street) as each source shows
it: Goad's fire insurance plans of 1889, 1903, 1913 and 1924, the 1913 plan with the outlines
plans.py read from it drawn on top, and the City's air photos of 1965 and 2025. Plus the town on Cane's map of 1842,
one of the early maps the streets come from.

Run: uv run --with geopandas --with pillow pipeline/figures.py
"""
import io
import math
import pathlib
import urllib.request

import geopandas as gpd
import shapely
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "web" / "public" / "img"
Z = 18
X, Y, WIDE, HIGH = 73267, 95676, 4, 3        # tiles: the block north of Front Street, west of Yonge
AIR = "https://gis.toronto.ca/arcgis/rest/services/basemap/cot_{service}/MapServer/tile/{z}/{y}/{x}"


def block(tile):
    """The block as one picture, from a function that gives the tile at (x, y)."""
    out = Image.new("RGB", (WIDE * 256, HIGH * 256), "white")
    for i in range(WIDE):
        for j in range(HIGH):
            t = tile(X + i, Y + j)
            if t:
                out.paste(t.convert("RGB"), (i * 256, j * 256))
    return out


def plan(year):
    def tile(x, y):
        f = RAW / "plans" / str(year) / str(Z) / str(x) / f"{y}.png"
        return Image.open(f) if f.exists() else None
    return block(tile)


def air(service):
    def tile(x, y):
        req = urllib.request.Request(AIR.format(service=service, z=Z, x=x, y=y), headers={"User-Agent": "toronto-through-time"})
        return Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=60).read()))
    return block(tile)


def lonlat(x, y):
    n = 2 ** Z
    return x / n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))


def read(year):
    """The plan with the outlines read from it."""
    picture = plan(year).convert("RGBA")
    w, n = lonlat(X, Y)
    e, s = lonlat(X + WIDE, Y + HIGH)
    found = gpd.read_file(ROOT / "data" / "interim" / "plans" / f"{year}.gpkg").to_crs(3857)
    corner = gpd.GeoSeries(gpd.points_from_xy([w, e], [n, s]), crs=4326).to_crs(3857)
    x0, y0, x1, y1 = corner.x[0], corner.y[0], corner.x[1], corner.y[1]
    layer = Image.new("RGBA", picture.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for g in found.geometry[found.intersects(shapely.box(x0, y1, x1, y0))]:
        for part in shapely.get_parts(g):
            ring = [((px - x0) / (x1 - x0) * picture.width, (py - y0) / (y1 - y0) * picture.height) for px, py in part.exterior.coords]
            draw.polygon(ring, outline=(29, 78, 216, 255), width=4)
    return Image.alpha_composite(picture, layer).convert("RGB")


def save(picture, name, wide=900):
    picture = picture.resize((wide, round(picture.height * wide / picture.width)), Image.LANCZOS)
    picture.save(OUT / name, quality=78, optimize=True, progressive=True)
    print(name, picture.size, f"{(OUT / name).stat().st_size / 1000:.0f} kB")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for year in (1889, 1903, 1913, 1924):      # (the 1880 scan has a hole over this block)
        save(plan(year), f"plan-{year}.jpg")
    save(read(1913), "plan-1913-read.jpg")
    save(air("historic_aerial_1965"), "air-1965.jpg")
    save(air("ortho_2025_color_8cm"), "air-2025.jpg")
    cane = Image.open(RAW / "histmaps" / "Cane_1842" / "Cane_1842.jpg").convert("RGB")      # the town, out of the middle of the sheet
    save(cane.crop((round(cane.width * 0.3), round(cane.height * 0.47), round(cane.width * 0.8), round(cane.height * 0.75))), "map-1842.jpg", 1200)
