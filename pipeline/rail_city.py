"""Railway lines in the rest of the city, outside the old City of Toronto: web/public/data/rail_city.json.

streets.py draws the railways of the old city, each from the year its line opened. This carries
them on to the city limits, from the same years (data/manual/rail_years.csv, by the line's name).
So before 1998 a line runs across ground the map otherwise leaves empty. The tracks are today's.
A track with no name, or a name the table does not have, is shown from 1998, when the streets
around it are. Main tracks from OpenStreetMap; yards, sidings and spurs are left out, as in the
old city.

Run: uv run --with geopandas pipeline/rail_city.py
"""
import csv
import json
import pathlib
import re
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
AGINCOURT_LON = -79.27

if __name__ == "__main__":
    kept = RAW / "osm" / "rail_city.json"
    if not kept.exists():
        query = '[out:json][timeout:120];way[railway=rail][!service](43.58,-79.64,43.86,-79.11);out tags geom;'
        req = urllib.request.Request("https://overpass-api.de/api/interpreter", urllib.parse.urlencode({"data": query}).encode(),
                                     {"User-Agent": "toronto-through-time"})
        kept.write_bytes(urllib.request.urlopen(req, timeout=200).read())
    ways = json.loads(kept.read_text())["elements"]
    opened = {r["line"]: int(r["year"]) for r in csv.DictReader((ROOT / "data" / "manual" / "rail_years.csv").open())
              if r["year"].strip() and not r["end_year"].strip() and not r["line"].startswith("STATION")}
    opened["Union Station Rail Corridor"] = 1857
    g = gpd.GeoDataFrame({"name": [re.sub(r"^(GO Transit - |GO Transit |Metrolinx )", "", w["tags"].get("name", "")) for w in ways]},
                         geometry=[shapely.LineString([(p["lon"], p["lat"]) for p in w["geometry"]]) for w in ways], crs=4326)
    g["y"] = [opened.get(n, FROM) for n in g.name]
    # East of Agincourt the Belleville Subdivision is a later line than the one of 1884 it joins:
    # the Canadian Pacific's lakeshore line, opened in 1914.
    g.loc[(g.name == "Belleville Subdivision") & (g.geometry.centroid.x > AGINCOURT_LON), "y"] = 1914
    g = g.to_crs(UTM)
    parts = gpd.read_file(RAW / "former_municipalities.geojson").to_crs(UTM)
    old = parts[parts.AREA_NAME == "TORONTO"].geometry.iloc[0]
    rest = shapely.union_all(parts.geometry.values).buffer(50).difference(old.buffer(JOIN_M))
    g["geometry"] = g.geometry.intersection(rest)
    g = g[~g.geometry.is_empty]
    feats = []
    for (name, y), part in g.groupby(["name", "y"]):
        line = shapely.simplify(shapely.line_merge(shapely.union_all(part.geometry.values)), 1.0)
        feats.append({"type": "Feature", "properties": {"name": name, "y": int(y)},
                      "geometry": shapely.geometry.mapping(shapely.set_precision(gpd.GeoSeries([line], crs=UTM).to_crs(4326).iloc[0], 1e-6))})
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    print(f"{len(g):,} tracks as {len(feats)} lines, {g.length.sum() / 1000:.0f} km, {OUT.stat().st_size / 1000:.0f} kB:", sorted((f["properties"]["y"], f["properties"]["name"]) for f in feats))
