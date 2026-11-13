"""The buildings of Toronto Pearson airport in 3D: web/public/data/pearson.json.

Pearson lies in Mississauga, outside the old city. The City of Mississauga publishes a detailed
3D massing model ("Level of Detail (LOD2) 3D Massing", open data under its Terms of Use:
https://mississauga.maps.arcgis.com/sharing/rest/content/items/961c790805c14d8da258ec91bf4117e3/data)
as tiles, each a zip with a shapefile of roof and wall surfaces. This downloads the tiles over
the airport, keeps the buildings the model marks as airport, and turns each into blocks by
height the way pipeline/shapes.py does for Toronto's model. A building of one height is one block.

Writes [{"p": [[lon, lat], ...] (outline), "h": height in metres}, ...].

Run: uv run --no-project --python 3.12 --with fiona --with geopandas --with pyproj pipeline/pearson.py
"""
import io
import json
import pathlib
import re
import urllib.request
import zipfile

import fiona
import geopandas as gpd
import numpy as np
import shapely
import shapely.affinity

import shapes

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "mississauga"
TILES = "https://services6.arcgis.com/hM5ymMLbxIyWTjn2/arcgis/rest/services/Massing_Tiles/FeatureServer/4/query"
BOX = "-79.672,43.652,-79.578,43.708"      # the airport (west, south, east, north)
ASSUMED_M = 20


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "toronto-through-time"}), timeout=180)


def tiles():
    """Downloads the tiles over the airport (once) and returns their shapefiles."""
    RAW.mkdir(parents=True, exist_ok=True)
    q = f"{TILES}?where=1%3D1&geometry={BOX}&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=TileNum,SketchUp_DWG_Download&returnGeometry=false&f=json"
    for t in json.load(get(q))["features"]:
        n, link = t["attributes"]["TileNum"], t["attributes"]["SketchUp_DWG_Download"]
        if not (RAW / f"Tile{n}").exists():
            item = re.search(r"id=([0-9a-f]+)", get(link).geturl()).group(1)      # the short link leads to the item's page
            data = get(f"https://www.arcgis.com/sharing/rest/content/items/{item}/data").read()
            zipfile.ZipFile(io.BytesIO(data)).extractall(RAW / f"Tile{n}")
            print("got tile", n, flush=True)
    return sorted(RAW.glob("Tile*/**/*.shp"))


if __name__ == "__main__":
    scale = np.cos(np.radians(43.68))      # web mercator to metres at the airport
    rows = []
    for path in tiles():
        with fiona.open(path) as src:
            for f in src:
                g, use = f["geometry"], str(f["properties"].get("BLDG_USE") or "")
                if not g or g["type"] != "MultiPolygon" or "airport" not in use.lower():
                    continue
                try:
                    rings, heights = shapes.roofs(g, scale)
                    # A stray point at height 0 makes the foot of a few buildings 170 m too low: where the
                    # roofs come out far above the model's own height for the building, they are set to it.
                    known = f["properties"].get("BLDGHEIGHT")
                    if known and len(rings) and heights.max() > 100:      # nothing at the airport is that tall
                        heights = heights - (heights.max() - known)
                        keep = heights >= shapes.GROUND
                        rings, heights = [r for r, k in zip(rings, keep) if k], heights[keep]
                    found = shapes.blocks(rings, heights) if len(rings) else []
                except Exception:
                    found = []
                if not found and len(rings):     # one flat roof: its outline at its height
                    whole = shapely.union_all(shapely.make_valid(shapely.polygons([shapely.linearrings(r) for r in rings])))
                    found = [(p, float(heights.max())) for p in shapely.get_parts(whole) if p.geom_type == "Polygon" and p.area >= shapes.MIN_AREA]
                for outline, height in found:
                    rows.append({"h": round(height, 1), "geometry": shapely.affinity.scale(outline, 1 / scale, 1 / scale, origin=(0, 0))})
    g = gpd.GeoDataFrame(rows, geometry="geometry", crs=3857).to_crs(4326)
    # a building on the edge of two tiles is in both
    g = g[~g.assign(x=g.geometry.centroid.x.round(5), y=g.geometry.centroid.y.round(5)).duplicated(["x", "y", "h"])]
    g["geometry"] = shapely.simplify(g.geometry.values, 3e-6)
    # Terminal 1 is not in Mississauga's model. A terminal of OpenStreetMap (pipeline/airports.py, run
    # first) that the blocks do not cover is drawn from its outline there: at 4.5 m a storey where
    # OpenStreetMap counts storeys, otherwise at ASSUMED_M, which is a guess.
    covered = shapely.union_all(g.geometry.values)
    for f in json.loads((ROOT / "web" / "public" / "data" / "airports.json").read_text())["features"]:
        if f["properties"]["kind"] != "terminal" or not (-79.672 < f["geometry"]["coordinates"][0][0][0] < -79.578):
            continue
        outline = shapely.Polygon(f["geometry"]["coordinates"][0]).buffer(0)
        if outline.intersection(covered).area < 0.3 * outline.area:
            levels = f["properties"].get("levels")
            g.loc[len(g)] = {"h": 4.5 * levels if levels else ASSUMED_M, "geometry": max(shapely.get_parts(outline), key=lambda part: part.area)}
            print("from OpenStreetMap's outline:", f["properties"]["name"], g.h.iloc[-1], "m")
    out = [{"p": [[round(x, 6), round(y, 6)] for x, y in shapely.get_coordinates(shapely.orient_polygons(geom).exterior)], "h": h}
           for geom, h in zip(g.geometry, g.h) if geom.geom_type == "Polygon" and not geom.is_empty]
    (ROOT / "web" / "public" / "data" / "pearson.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"{len(out):,} blocks, tallest {max(o['h'] for o in out)} m, {sum(len(o['p']) for o in out):,} corners")
