"""Railway lines in the rest of the city, outside the old City of Toronto: web/public/data/rail_city.json.

streets.py draws the railways of the old city, each from the year its line opened. Outside it the
map has no history (see district.py): like the streets there, these tracks are today's and are
shown from 1998, the year the districts joined the city. Main tracks from OpenStreetMap; yards,
sidings and spurs are left out, as in the old city.

Run: uv run --with geopandas pipeline/rail_city.py
"""
import json
import pathlib
import urllib.parse
import urllib.request

import geopandas as gpd
import shapely

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "web" / "public" / "data" / "rail_city.json"
UTM = 26917
JOIN_M = 300      # streets.py draws the old city's tracks to this far outside it
FROM = 1998

if __name__ == "__main__":
    kept = RAW / "osm" / "rail_city.json"
    if not kept.exists():
        query = '[out:json][timeout:120];way[railway=rail][!service](43.58,-79.64,43.86,-79.11);out tags geom;'
        req = urllib.request.Request("https://overpass-api.de/api/interpreter", urllib.parse.urlencode({"data": query}).encode(),
                                     {"User-Agent": "toronto-through-time"})
        kept.write_bytes(urllib.request.urlopen(req, timeout=200).read())
    ways = json.loads(kept.read_text())["elements"]
    g = gpd.GeoDataFrame({"name": [w["tags"].get("name", "") for w in ways]},
                         geometry=[shapely.LineString([(p["lon"], p["lat"]) for p in w["geometry"]]) for w in ways], crs=4326).to_crs(UTM)
    parts = gpd.read_file(RAW / "former_municipalities.geojson").to_crs(UTM)
    old = parts[parts.AREA_NAME == "TORONTO"].geometry.iloc[0]
    rest = shapely.union_all(parts.geometry.values).buffer(50).difference(old.buffer(JOIN_M))
    g["geometry"] = g.geometry.intersection(rest)
    g = g[~g.geometry.is_empty]
    feats = []
    for name, part in g.groupby("name"):
        line = shapely.simplify(shapely.line_merge(shapely.union_all(part.geometry.values)), 1.0)
        feats.append({"type": "Feature", "properties": {"name": name, "y": FROM},
                      "geometry": shapely.geometry.mapping(shapely.set_precision(gpd.GeoSeries([line], crs=UTM).to_crs(4326).iloc[0], 1e-6))})
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    print(f"{len(g):,} tracks as {len(feats)} lines, {g.length.sum() / 1000:.0f} km, {OUT.stat().st_size / 1000:.0f} kB:", sorted(f["properties"]["name"] for f in feats))
