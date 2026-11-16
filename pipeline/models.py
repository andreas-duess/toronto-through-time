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


def by_era(parts, axis, era, whole=False):
    """Each part cut by the masks of a building's eras. `era(u, v, part)` names the era of a point
    along and across the building; a part is cut where it crosses from one era into another, or,
    `whole`, goes entirely to the era of its middle."""
    import shapely
    ax, ay = axis
    to_uv = lambda x, y: (x * ax + y * ay, -x * ay + y * ax)
    from_uv = lambda u, v: (ax * u - ay * v, ay * u + ax * v)
    out = []
    for p in parts:
        if not p["top"] > p["foot"]:
            continue
        shape = shapely.Polygon([to_uv(*xy) for xy in p["ring"]]).buffer(0)
        if whole:
            c = shape.representative_point()
            out.append({**p, "era": era(c.x, c.y, p)})
            continue
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


def uv_frame(ways, host):
    """For the models drawn by hand in the web map: the origin, the direction of the longest side
    and the outline, in metres; the web map places its pieces along (u) and across (v) that side."""
    origin, ax, ay = frame(ways, host)
    return {"origin": origin, "axis": [round(ax, 5), round(ay, 5)], "outline": local(ring(ways[host]), origin),
            "hide": [ring(ways[host])]}


def cut(points, axis, keep):
    """The part of an outline (metres) where `keep(u, v)`, as the outline of its largest piece."""
    import shapely
    ax, ay = axis
    shape = shapely.Polygon([(x * ax + y * ay, -x * ay + y * ax) for x, y in points]).buffer(0)
    u0, v0, u1, v1 = shape.bounds
    cells = [shapely.box(u, v, u + 1, v + 1) for u in range(int(u0) - 1, int(u1) + 2)
             for v in range(int(v0) - 1, int(v1) + 2) if keep(u + 0.5, v + 0.5)]
    piece = shape.intersection(shapely.unary_union(cells)).simplify(0.3)
    piece = max(getattr(piece, "geoms", [piece]), key=lambda g: g.area)
    return [[round(ax * u - ay * v, 2), round(ay * u + ax * v, 2)] for u, v in piece.exterior.coords[:-1]]


OLD_CITY_HALL, LEGISLATURE, UNIVERSITY_COLLEGE, UNION = 3116, 15089986, 8032167, 14744491
ST_MICHAELS, METROPOLITAN, HOLY_TRINITY = 43808581, 34007361, 34545830
ST_MICHAELS_SPIRE = 289215698


def old_city_hall(ways):
    """Its parts as mapped in OpenStreetMap, the clock tower to 103.6 m; one era."""
    origin = centre(ring(ways[OLD_CITY_HALL]))
    return {"origin": origin, "parts": [part(w, origin) for w in parts_inside(ways, OLD_CITY_HALL)],
            "hide": [ring(ways[OLD_CITY_HALL])]}


def legislature(ways):
    """The Legislative Building's parts; the north wing of 1909 is the block north of the courtyard
    (v above 15, within 25 m of the middle) and the link to it, read off the city's air photo."""
    origin, ax, ay = frame(ways, LEGISLATURE)
    parts = [part(w, origin) for w in parts_inside(ways, LEGISLATURE)]
    era = lambda u, v, p: "1909" if (v > 15 and abs(u) < 25) or (abs(u) < 5 and v > -9) else "1893"
    return {"origin": origin, "parts": by_era(parts, (ax, ay), era, whole=True), "hide": [ring(ways[LEGISLATURE])]}


def university_college(ways):
    """University College's parts; the Laidlaw wing of the 1960s is the flat-roofed range that
    closes the quadrangle on the north (u -42 to 18, v below -32), read off the city's air photo."""
    origin, ax, ay = frame(ways, UNIVERSITY_COLLEGE)
    parts = [part(w, origin) for w in parts_inside(ways, UNIVERSITY_COLLEGE)]
    era = lambda u, v, p: "1964" if -42 <= u <= 18 and v < -32 else "1859"
    return {"origin": origin, "parts": by_era(parts, (ax, ay), era, whole=True),
            "hide": [ring(ways[UNIVERSITY_COLLEGE])]}


def union_station(ways):
    """Union Station: OpenStreetMap maps the Great Hall, the colonnade, the train sheds and the glass
    atrium in 3D but not the office wings either side of the hall; those are the outline along Front
    Street (v above -8) outside the hall, drawn 17 m high, where the pavilion roofs on the wings
    start. The atrium's outline is also the middle of the old shed, which it replaced."""
    origin, ax, ay = frame(ways, UNION)
    raw = [(part(w, origin), w) for w in parts_inside(ways, UNION)]

    def era(p, w):
        if w["tags"].get("building:material") == "glass":
            return "atrium"
        return "shed" if w["tags"].get("building:levels") == "1" and not w["tags"].get("height") else "1920"
    parts = [{**p, "era": era(p, w)} for p, w in raw]
    atrium = next(p for p in parts if p["era"] == "atrium")
    wings = [cut(local(ring(ways[UNION]), origin), (ax, ay), lambda u, v, s=s: v > -8 and s * (u - (11 if s > 0 else -69)) > 0)
             for s in (-1, 1)]
    parts += [{"ring": r, "foot": 0, "top": 17, "roof": 0, "shape": "flat", "era": "1920"} for r in wings]
    parts.append({**atrium, "top": 3.3, "era": "old-shed"})
    return {"origin": origin, "parts": parts, "hide": [ring(ways[UNION])]}


def st_michaels(ways):
    """St. Michael's Cathedral: the outline and frame for the hand-drawn model, and the tower and
    spire as OpenStreetMap maps them (79.25 m, the spire from 40 m)."""
    out = uv_frame(ways, ST_MICHAELS)
    out["spire"] = part(ways[ST_MICHAELS_SPIRE], out["origin"])
    return out


def metropolitan(ways):
    """Metropolitan United: the outline cut into the tower at the south end (u from 17.3, where
    the outline narrows to the tower's 9 m) and the church, which burned in 1928."""
    out = uv_frame(ways, METROPOLITAN)
    out["tower"] = cut(out["outline"], out["axis"], lambda u, v: u >= 17.3)
    out["body"] = cut(out["outline"], out["axis"], lambda u, v: u < 17.3)
    return out


if __name__ == "__main__":
    elements = json.loads(OSM.read_text())["elements"]
    ways = {e["id"]: e for e in elements if e["type"] == "way"}
    # a building mapped as a multipolygon relation, as a way along its largest outer ring
    import shapely
    from shapely.ops import polygonize, unary_union
    for e in elements:
        if e["type"] == "relation" and e.get("tags", {}).get("building") and e.get("members"):
            lines = [shapely.LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
                     for m in e["members"] if m["role"] == "outer" and m.get("geometry")]
            polys = list(polygonize(unary_union(lines)))
            if polys:
                outer = max(polys, key=lambda p: p.area)
                ways[e["id"]] = {**e, "type": "way", "geometry": [{"lon": x, "lat": y} for x, y in outer.exterior.coords]}
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
        "oldCityHall": old_city_hall(ways),
        "legislature": legislature(ways),
        "universityCollege": university_college(ways),
        "unionStation": union_station(ways),
        "stMichaels": st_michaels(ways),
        "metropolitan": metropolitan(ways),
        "holyTrinity": uv_frame(ways, HOLY_TRINITY),
    }
    # without the 1913 plan here, keep the Trinity College already written
    trinity = trinity_college() or (json.loads(OUT.read_text()).get("trinityCollege") if OUT.exists() else None)
    if trinity:
        out["trinityCollege"] = trinity
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print("wrote landmarks.json", OUT.stat().st_size, "bytes")
