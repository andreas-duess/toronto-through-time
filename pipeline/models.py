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
    if t.get("building:colour"):
        out["colour"] = t["building:colour"]
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


def frame(ways, host):
    """A building's origin (the middle of its outline) and the direction of its longest side: masks
    for the eras of a building are drawn in metres along (u) and across (v) that side."""
    origin = centre(ring(ways[host]))
    pts = local(ring(ways[host]), origin)
    i = max(range(len(pts)), key=lambda k: math.dist(pts[k], pts[(k + 1) % len(pts)]))
    (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % len(pts)]
    d = math.dist((x0, y0), (x1, y1))
    return origin, (x1 - x0) / d, (y1 - y0) / d


def by_era(parts, axis, era):
    """Each part cut by the masks of a building's eras. `era(u, v, part)` names the era of a point
    along and across the building; a part is cut where it crosses from one era into another."""
    import shapely
    ax, ay = axis
    to_uv = lambda x, y: (x * ax + y * ay, -x * ay + y * ax)
    from_uv = lambda u, v: (ax * u - ay * v, ay * u + ax * v)
    out = []
    for p in parts:
        if not p["top"] > p["foot"]:
            continue
        shape = shapely.Polygon([to_uv(*xy) for xy in p["ring"]]).buffer(0)
        u0, v0, u1, v1 = shape.bounds
        cells = {}
        # the masks are rectangles, so a fine grid of cells finds each era's piece of the part
        for u in range(int(u0) - 1, int(u1) + 2):
            for v in range(int(v0) - 1, int(v1) + 2):
                cells.setdefault(era(u + 0.5, v + 0.5, p), []).append(shapely.box(u, v, u + 1, v + 1))
        for name, boxes in cells.items():
            piece = shape.intersection(shapely.unary_union(boxes)).simplify(0.3)
            for poly in getattr(piece, "geoms", [piece]):
                if poly.geom_type == "Polygon" and poly.area > 4:
                    out.append({**p, "ring": [[round(c, 2) for c in from_uv(u, v)] for u, v in poly.exterior.coords[:-1]],
                                "era": name})
    return out


ROM, AGO = 4942687, 141693334
AGO_GEHRY = {959903559, 959903560, 960781588, 960781589, 960781590}   # the Galleria's east end and the spiral stair


def rom(ways):
    """The Royal Ontario Museum by era, its masks read off the city's air photos of 1939, 1978 and
    1999: the 1914 wing along Philosopher's Walk (v below -33), the 1933 wing on Queen's Park (v
    above 22) and the centre block between them (u -6 to 12), the courtyard south of it filled in
    1984 around the curatorial centre, and the Crystal: every metal part, and whatever stands in the
    north courtyard, where the terrace galleries were. Those are drawn from the 1999 photo as three
    steps rising from Bloor."""
    origin, ax, ay = frame(ways, ROM)
    raw = [(part(w, origin), w) for w in parts_inside(ways, ROM)]
    metal = [p for p, w in raw if w["tags"].get("building:material") == "metal"]
    stone = [p for p, w in raw if w["tags"].get("building:material") != "metal"]

    def era(u, v, p):
        if v < -33:
            return "1914"
        if v > 22 or -6 <= u <= 12:
            return "1933"
        return "1984" if u > 12 else "2007"
    parts = by_era(stone, (ax, ay), era) + [{**p, "era": "2007"} for p in metal]
    from_uv = lambda u, v: [round(ax * u - ay * v, 2), round(ay * u + ax * v, 2)]
    terraces = [{"ring": [from_uv(u, v) for u, v in ((start, -33), (-6, -33), (-6, 22), (start, 22))], "top": top}
                for start, top in ((-48, 7), (-38, 13), (-28, 19))]
    return {"origin": origin, "parts": parts, "terraces": terraces, "hide": [ring(ways[ROM])]}


def ago(ways):
    """The Art Gallery of Ontario by era, its masks read off the city's air photos of 1939, 1965,
    1978 and 1999: the gallery around Walker Court (u -46 to 18, v -52 to 6), its south side the
    first galleries of 1918 and the rest 1924 to 1926 (with the 1935 galleries, which the photos do
    not tell apart); the skylit Henry Moore Sculpture Centre (1974) and the east wings standing by
    1978; the Beverley Street galleries (1977); the block along Dundas, built out to the street by
    1999 (1993); and Gehry's work of 2008: every glass and metal part, the stair and the Galleria's
    ends."""
    origin, ax, ay = frame(ways, AGO)
    raw = [(part(w, origin), w) for w in parts_inside(ways, AGO)]
    gehry = [p for p, w in raw if w["tags"].get("building:material") in ("glass", "metal") or w["id"] in AGO_GEHRY]
    moore = [p for p, w in raw if w["id"] == 959819118]
    rest = [p for p, w in raw if p not in gehry and p not in moore]

    def era(u, v, p):
        if -46 <= u <= 18 and -52 <= v <= 6:
            return "1918" if v < -35 else "1926"
        if v > 6 and -75 <= u:
            return "1993"
        return "1977" if u < -46 else "1974"
    parts = (by_era(rest, (ax, ay), era) + [{**p, "era": "1974"} for p in moore]
             + [{**p, "era": "2008"} for p in gehry])
    return {"origin": origin, "parts": parts, "hide": [ring(ways[AGO])]}


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
        "rom": rom(ways),
        "ago": ago(ways),
    }
    # without the 1913 plan here, keep the Trinity College already written
    trinity = trinity_college() or (json.loads(OUT.read_text()).get("trinityCollege") if OUT.exists() else None)
    if trinity:
        out["trinityCollege"] = trinity
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print("wrote landmarks.json", OUT.stat().st_size, "bytes")
