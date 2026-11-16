"""Outlines for the landmarks the web map builds by hand (web/src/landmarks.js), from
OpenStreetMap, as metres east and north of each landmark's own origin.
Writes web/public/data/landmarks.json.

Run: uv run pipeline/models.py
"""
import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OSM = ROOT / "data" / "raw" / "osm" / "landmarks.json"
OUT = ROOT / "web" / "public" / "data" / "landmarks.json"

# OpenStreetMap way ids
CN_TOWER, ROGERS_CENTRE = 32742038, 7969701
BMO_PITCH = 22952579
BMO_STANDS = {"east": 971275703, "south": 971275705, "west": 971275707, "north": 1550075048}


def ring(way):
    return [(p["lon"], p["lat"]) for p in way["geometry"]]


def centre(points):
    return [sum(p[0] for p in points[:-1]) / (len(points) - 1), sum(p[1] for p in points[:-1]) / (len(points) - 1)]


def local(points, origin):
    """Lon/lat as metres east and north of the origin, without the closing point."""
    east = 111320 * math.cos(math.radians(origin[1]))
    return [[round((lon - origin[0]) * east, 2), round((lat - origin[1]) * 111132, 2)] for lon, lat in points[:-1]]


def trinity_college():
    """The old Trinity College: its footprint on Goad's 1913 plan (pipeline/plans.py --area
    trinity), the same drawn in by 3 m for the roof, and the line of its south front."""
    import geopandas as gpd
    import shapely
    path = ROOT / "data" / "interim" / "plans" / "1913_trinity.gpkg"
    if not path.exists():
        return None
    g = gpd.read_file(path)
    at = gpd.GeoSeries(gpd.points_from_xy([-79.4140], [43.6468]), crs=4326).to_crs(g.crs).iloc[0]
    near = g[(g.distance(at) < 150) & g.area.between(1500, 9000)]
    print("  Trinity College candidates:", [(round(a), round(d)) for a, d in zip(near.area, near.distance(at))])
    shape = near.geometry.loc[near.distance(at).idxmin()]
    shape = shapely.Polygon(shape.exterior).simplify(1.2)
    lonlat = gpd.GeoSeries([shape, shape.buffer(-3, join_style="mitre").simplify(0.8), shape.centroid,
                            shape.minimum_rotated_rectangle], crs=g.crs).to_crs(4326)
    origin = [lonlat.iloc[2].x, lonlat.iloc[2].y]
    inner = max(shapely.get_parts(lonlat.iloc[1]), key=lambda p: p.area)
    rect = local(list(lonlat.iloc[3].exterior.coords), origin)
    # the south front, facing Queen Street: the southernmost side of the surrounding rectangle
    sides = [(rect[i], rect[(i + 1) % 4]) for i in range(4)]
    front = min(sides, key=lambda s: s[0][1] + s[1][1])
    return {"origin": origin, "outline": local(list(lonlat.iloc[0].exterior.coords), origin),
            "roof": local(list(inner.exterior.coords), origin), "front": [list(front[0]), list(front[1])]}


def metres(value):
    try:
        return float(str(value).replace("m", "").strip())
    except (TypeError, ValueError):
        return None


def part(way, origin):
    """A building:part as the web map's model reads it: outline, foot and top in metres, and roof."""
    t = way["tags"]
    top = metres(t.get("height")) or (metres(t.get("building:levels")) or 1) * 3.3
    foot = metres(t.get("min_height")) or (metres(t.get("building:min_level")) or 0) * 3.3
    shape = t.get("roof:shape", "flat")
    roof = min(metres(t.get("roof:height")) or 0, top - foot) if shape != "flat" else 0
    out = {"ring": local(ring(way), origin), "foot": foot, "top": top, "roof": roof, "shape": shape}
    if t.get("roof:direction") is not None:
        out["direction"] = metres(t["roof:direction"])
    if t.get("roof:orientation") == "across":
        out["across"] = True
    if t.get("building:part") == "roof":      # a roof on posts: nothing under it
        out["foot"] = top - roof
    return out


def parts_inside(ways, host):
    """The building:parts whose middles fall inside a building, as OpenStreetMap maps it in 3D."""
    import shapely
    outline = shapely.Polygon(ring(ways[host]))
    return [w for w in ways.values() if "building:part" in w["tags"] and len(w["geometry"]) >= 4
            and outline.contains(shapely.Polygon(ring(w)).buffer(0).representative_point())]


# Casa Loma, OCAD's Sharp Centre and St. James' Cathedral (OpenStreetMap way ids)
CASA_LOMA = 198471666
OCAD_MAIN, OCAD_TABLE, OCAD_REID, OCAD_FOURSTOREY, OCAD_CORES = 225377144, 27616814, 961216770, 961216769, (961216771, 961216772)
ST_JAMES = 35154281


def casa_loma(ways):
    """Its hundred parts, with heights and roofs, as mapped in OpenStreetMap (heights there are estimates)."""
    origin = centre(ring(ways[CASA_LOMA]))
    return {"origin": origin, "parts": [part(w, origin) for w in parts_inside(ways, CASA_LOMA)],
            "hide": [ring(ways[CASA_LOMA])]}


def st_james(ways):
    """The cathedral's parts; the tower and what stands on it (from 47 m up) are marked, as they
    went up twenty years after the church."""
    origin = centre(ring(ways[ST_JAMES]))
    parts = [part(w, origin) for w in parts_inside(ways, ST_JAMES)]
    for p in parts:
        p["tower"] = p["foot"] >= 47 or p["top"] == 47
    return {"origin": origin, "parts": parts, "hide": [ring(ways[ST_JAMES])]}


def ocad(ways):
    """The main building at 100 McCaul (the 1921 wing with a gabled roof, the rest four storeys),
    the two cores that carry the Sharp Centre and the tabletop's outline."""
    origin = centre(ring(ways[OCAD_TABLE]))
    return {"origin": origin, "table": local(ring(ways[OCAD_TABLE]), origin),
            "reid": part(ways[OCAD_REID], origin), "main": local(ring(ways[OCAD_FOURSTOREY]), origin),
            "cores": [local(ring(ways[c]), origin) for c in OCAD_CORES],
            "hide": [ring(ways[OCAD_MAIN]), ring(ways[OCAD_TABLE])]}


if __name__ == "__main__":
    ways = {e["id"]: e for e in json.loads(OSM.read_text())["elements"] if e["type"] == "way"}
    cn = centre(ring(ways[CN_TOWER]))
    rogers = centre(ring(ways[ROGERS_CENTRE]))
    bmo = centre(ring(ways[BMO_PITCH]))
    out = {
        "cnTower": {"origin": cn},
        "rogersCentre": {"origin": rogers, "outline": local(ring(ways[ROGERS_CENTRE]), rogers)},
        "bmoField": {"origin": bmo, "pitch": local(ring(ways[BMO_PITCH]), bmo),
                     "stands": {side: local(ring(ways[i]), bmo) for side, i in BMO_STANDS.items()}},
        "casaLoma": casa_loma(ways),
        "stJames": st_james(ways),
        "ocad": ocad(ways),
    }
    # without the 1913 plan here, keep the Trinity College already written
    trinity = trinity_college() or (json.loads(OUT.read_text()).get("trinityCollege") if OUT.exists() else None)
    if trinity:
        out["trinityCollege"] = trinity
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print("wrote landmarks.json", OUT.stat().st_size, "bytes")
