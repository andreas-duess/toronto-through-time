"""Give every street segment in the old City of Toronto a year and write the files the web map
draws instead of a modern base map: streets.json, street-labels.json, places.json, rail.json,
sites.json, forest.json, parks.json, area.json.

The city's centreline file has no dates, so a segment's year is an estimate, the earliest of:
  - the buildings along it (within FRONT_M): the 10th percentile of their years, and the oldest
    one dated from a record
  - the buildings around it (within AREA_M): the 5th percentile of their years
  - data/manual/town_extents.csv and map_extents.csv: the extent of the early town, from the
    surveyed plans and from outlines read off the maps of 1834 and 1842
A street has no holes: a segment is no later than the later of its two neighbours on the same
street. Then two corrections:
  - data/manual/street_years.csv: documented opening years, which replace the estimate
  - no street before its ground was dry land, from the historic water maps (pipeline/water.py)

Only buildings that still stand have a year, so streets in rebuilt areas come out too late.

Run after build.py: uv run pipeline/streets.py
"""
import csv
import json
import pathlib
import re
import urllib.request
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import box

import water

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MANUAL = ROOT / "data" / "manual"
OUT = ROOT / "web" / "public" / "data"
UTM = 26917
FIRST_YEAR, LAST_YEAR = 1793, 2026

OLD_TOWN_URL = "https://maps.library.utoronto.ca/dvhmp/data/2009_05_10/york_boundary/old_town.zip"

HARBOUR = (-79.47, -79.357)  # longitudes between which railway tracks are kept off the old lake
MAX_SHIFT_M = 500
CLEAR_M = 150  # forest gives way this far around a new street or building
WOODS_YEAR = 1851
FARM_M = 2500  # by 1851 farms have cleared the land this far from the first roads
FRONT_M = 45
AREA_M = 250
RECORD_TIERS = 3  # landmark, heritage, apartment, permit: years from a record
# centreline class -> kind drawn by the web map (0 lane, 1 local, 2 collector, 3 arterial, 4 expressway)
KINDS = {"Laneway": 0, "Local": 1, "Access Road": 1, "Collector": 2, "Collector Ramp": 2,
         "Minor Arterial": 3, "Minor Arterial Ramp": 3, "Major Arterial": 3, "Major Arterial Ramp": 3,
         "Expressway": 4, "Expressway Ramp": 4}
EXPRESSWAY = 4


def log(*a):
    print(*a, flush=True)


def load_buildings():
    """Centre, year and tier of every building, from the files build.py wrote."""
    meta = json.loads((OUT / "meta.json").read_text())
    pos = np.frombuffer((OUT / "positions.bin").read_bytes(), "<f4").reshape(-1, 3)
    starts = np.frombuffer((OUT / "starts.bin").read_bytes(), "<u4")
    years = np.frombuffer((OUT / "years.bin").read_bytes(), "<u2").astype(float)
    tiers = np.frombuffer((OUT / "tiers.bin").read_bytes(), "u1")
    n = np.diff(starts)
    ok = n > 0  # a few outlines are empty
    first = starts[:-1][ok]
    lon = np.add.reduceat(pos[:, 0], first)[: ok.sum()] / n[ok] + meta["origin"][0]
    lat = np.add.reduceat(pos[:, 1], first)[: ok.sum()] / n[ok] + meta["origin"][1]
    xy = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=4326).to_crs(UTM)
    return np.c_[xy.x, xy.y], years[ok], tiers[ok]


def load_segments(old):
    s = gpd.read_file(RAW / "centreline.gpkg").to_crs(UTM)
    s = s[s.FEATURE_CODE_DESC.isin(KINDS)]
    s = s[shapely.intersects(shapely.buffer(old, 20), s.geometry.values)].reset_index(drop=True)
    s["geometry"] = shapely.line_merge(s.geometry.values)
    s = s[s.geometry.geom_type == "LineString"].reset_index(drop=True)
    s["kind"] = s.FEATURE_CODE_DESC.map(KINDS)
    s["name"] = s.LINEAR_NAME_FULL.fillna("")
    s["name_words"] = s.name.map(words)
    log(f"street segments in old Toronto: {len(s):,}", s.kind.value_counts().sort_index().to_dict())
    return s[["name", "name_words", "kind", "FROM_INTERSECTION_ID", "TO_INTERSECTION_ID", "geometry"]]


def from_buildings(s, xy, years, tiers):
    pts = shapely.points(xy)
    si, bi = shapely.STRtree(pts).query(shapely.buffer(s.geometry.values, FRONT_M, cap_style="flat"),
                                        predicate="intersects")
    near = pd.DataFrame({"seg": si, "year": years[bi], "record": tiers[bi] <= RECORD_TIERS})
    by_seg = near.groupby("seg").year
    front = by_seg.quantile(0.1).where(by_seg.size() >= 3, by_seg.min())
    record = near[near.record].groupby("seg").year.min()

    mid = shapely.line_interpolate_point(s.geometry.values, 0.5, normalized=True)
    around = cKDTree(xy).query_ball_point(np.c_[shapely.get_x(mid), shapely.get_y(mid)], AREA_M)
    area = np.array([np.percentile(years[a], 5) if len(a) >= 10 else np.nan for a in around])
    est = pd.DataFrame({"front": front, "record": record}).reindex(range(len(s)))
    est["area"] = area
    return est.min(axis=1).to_numpy()


def neighbours(s):
    """For each segment, the segments of the same street at its two ends, and all segments there."""
    ends = pd.concat([pd.DataFrame({"node": s.FROM_INTERSECTION_ID, "seg": s.index, "end": 0}),
                      pd.DataFrame({"node": s.TO_INTERSECTION_ID, "seg": s.index, "end": 1})])
    at_node = ends.groupby("node").seg.apply(list)
    same, every = [], []
    for i, (a, b, name) in enumerate(zip(s.FROM_INTERSECTION_ID, s.TO_INTERSECTION_ID, s.name)):
        sides = [[j for j in at_node[node] if j != i] for node in (a, b)]
        every.append(sides)
        same.append([[j for j in side if name and s.name.values[j] == name] for side in sides])
    return same, every


def no_holes(year, same, every):
    # segments nothing dates (through a park, along the tracks) take the earliest neighbour, same
    # street first
    for _ in range(50):
        missing = np.flatnonzero(np.isnan(year))
        if not len(missing):
            break
        filled = year.copy()
        for i in missing:
            for sides in (same[i], every[i]):
                known = [year[j] for side in sides for j in side if not np.isnan(year[j])]
                if known:
                    filled[i] = min(known)
                    break
        if np.array_equal(np.isnan(filled), np.isnan(year)):
            break
        year = filled
    for _ in range(30):
        changed = False
        for i, (a, b) in enumerate(same):
            if a and b:
                cap = max(min(year[j] for j in a), min(year[j] for j in b))
                if cap < year[i]:
                    year[i], changed = cap, True
        if not changed:
            break
    return year


SHORT = {"street": "st", "avenue": "ave", "road": "rd", "boulevard": "blvd", "expressway": "xy",
         "parkway": "pkwy", "east": "e", "west": "w", "north": "n", "south": "s"}


def words(name):
    return {SHORT.get(w, w) for w in re.sub(r"[^a-z ]", "", name.lower()).split()}


def named(s, street):
    """Segments of a street: every word of the name is in the segment's name, so "King Street"
    finds King St E and King St W but not Kingston Rd."""
    want = words(street)
    return np.array([want <= w for w in s.name_words])


def crossing(s, a, b):
    """Where streets a and b meet (the middle of their crossings), or None."""
    first, second = s.geometry.values[named(s, a)], s.geometry.values[named(s, b)]
    if not len(first) or not len(second):
        return None
    hit = shapely.intersection(shapely.union_all(first), shapely.union_all(second).buffer(15))
    return None if hit.is_empty else hit.centroid


def old_town():
    """Outline of the 1793 townsite, from the Don Valley Historical Mapping Project."""
    folder = RAW / "dvhmp" / "old_town"
    if not (folder / "old_town.shp").exists():
        req = urllib.request.Request(OLD_TOWN_URL, headers={"User-Agent": "toronto-through-time"})
        archive = RAW / "dvhmp" / "old_town.zip"
        archive.write_bytes(urllib.request.urlopen(req).read())
        with zipfile.ZipFile(archive) as z:
            z.extractall(folder)
    return gpd.read_file(folder / "old_town.shp").to_crs(UTM).geometry.iloc[0]


def mapped_extents(s):
    """Year by which each street lay inside the town: the surveyed plans in town_extents.csv
    (given by their bounding streets) and the outlines read off historic maps in map_extents.csv."""
    areas = []
    for r in csv.DictReader((MANUAL / "town_extents.csv").open()):
        corners = [crossing(s, r[a], r[b]) if r[a] and r[b] else None for a, b in
                   [("west", "south"), ("east", "south"), ("east", "north"), ("west", "north")]]
        if any(c is None for c in corners):
            log(f"  {r['id']}: not bounded by four streets, not used")
            continue
        areas.append((r["id"], float(r["year"]), shapely.Polygon([(c.x, c.y) for c in corners])))
    for r in csv.DictReader((MANUAL / "map_extents.csv").open()):
        if r["wkt"]:
            area = gpd.GeoSeries([shapely.from_wkt(r["wkt"])], crs=4326).to_crs(UTM).iloc[0]
        else:
            area = old_town()
        areas.append((r["id"], float(r["year"]), area))
    cap = np.full(len(s), np.nan)
    streets = (s.kind.values > 0) & (s.kind.values < EXPRESSWAY)
    for name, year, area in areas:
        inside = streets & (shapely.length(shapely.intersection(area.buffer(25), s.geometry.values))
                            >= 0.8 * s.geometry.length.values)
        cap[inside] = np.fmin(cap[inside], year)
        log(f"  {name} ({year:.0f}): {inside.sum()} segments")
    return cap


def documented(s, year):
    """Opening years from data/manual/street_years.csv replace the estimate."""
    fixed = np.zeros(len(s), bool)
    mid = shapely.line_interpolate_point(s.geometry.values, 0.5, normalized=True)
    for r in csv.DictReader((MANUAL / "street_years.csv").open()):
        if not r["year"].strip():
            continue
        on = named(s, r["street"])
        ends = [r["from_street"].strip(), r["to_street"].strip()]
        if any(ends):
            a, b = (crossing(s, r["street"], e) if e else None for e in ends)
            if a is None or b is None:
                log(f"  {r['street']}, {ends[0]} to {ends[1]}: crossing not found, not used")
                continue
            # between the two crossings, with room for a bend in the street
            on &= shapely.distance(mid, a) + shapely.distance(mid, b) <= 1.15 * a.distance(b) + 60
        year[on], fixed[on] = float(r["year"]), True
        log(f"  {r['street']} {ends[0]} {ends[1]} = {r['year']}: {on.sum()} segments")
    # expressway pieces and ramps the table does not name take the year of the nearest piece it does
    known = np.flatnonzero(fixed & (s.kind.values == EXPRESSWAY))
    rest = np.flatnonzero(~fixed & (s.kind.values == EXPRESSWAY))
    if len(known) and len(rest):
        xy = np.c_[shapely.get_x(mid), shapely.get_y(mid)]
        year[rest] = year[known[cKDTree(xy[known]).query(xy[rest])[1]]]
        fixed[rest] = True
    return year, fixed


def dry_since(lines):
    """First year the ground under each line was land: the mapped year after the last one that
    shows water at both ends and the middle."""
    frames = water.frames()[0]
    pts = [shapely.line_interpolate_point(lines, f, normalized=True) for f in (0.02, 0.5, 0.98)]
    since = np.full(len(lines), float(FIRST_YEAR))
    steps = sorted(frames)
    for year, nxt in zip(steps, steps[1:] + [water.MODERN_FADE[1]]):
        wet = np.all([shapely.contains(frames[year], p) for p in pts], axis=0)
        since[wet] = nxt
    return since


def lonlat_json(geom):
    geom = gpd.GeoSeries([geom], crs=UTM).to_crs(4326).iloc[0]
    return json.loads(shapely.to_geojson(shapely.set_precision(geom, 1e-6, mode="pointwise")))


def write_streets(s):
    # one line per street, kind and year
    feats = []
    for (name, kind, year), g in s.groupby(["name", "kind", "year"]):
        line = shapely.simplify(shapely.line_merge(shapely.union_all(g.geometry.values)), 1.0)
        feats.append({"type": "Feature", "geometry": lonlat_json(line),
                      "properties": {"y": int(year), "kind": int(kind)}})
    (OUT / "streets.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                                 separators=(",", ":")))

    # labels: one line per street and decade, named from the decade's first year on
    named = s[(s.name != "") & (s.kind > 0) & ~s.name.str.contains("Ramp")].copy()
    named["decade"] = named.year // 10
    labels = []
    for (name, _), g in named.groupby(["name", "decade"]):
        line = shapely.simplify(shapely.line_merge(shapely.union_all(g.geometry.values)), 3.0)
        labels.append({"type": "Feature", "geometry": lonlat_json(line),
                       "properties": {"name": name, "y": int(g.year.min()), "kind": int(g.kind.max())}})
    (OUT / "street-labels.json").write_text(json.dumps({"type": "FeatureCollection", "features": labels},
                                                       separators=(",", ":")))
    log(f"wrote {len(s):,} street segments as {len(feats):,} lines and {len(labels):,} label lines;",
        f"{(OUT / 'streets.json').stat().st_size / 1e6:.1f} MB + "
        f"{(OUT / 'street-labels.json').stat().st_size / 1e6:.1f} MB")


def write_places():
    path = MANUAL / "places.csv"
    feats = []
    if path.exists():
        for r in csv.DictReader(path.open()):
            if not r["from_year"]:  # no sourced first year
                continue
            feats.append({"type": "Feature",
                          "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
                          "properties": {"name": r["name"], "kind": r["kind"],
                                         "from": int(r["from_year"]), "to": int(r["to_year"] or 9999)}})
    (OUT / "places.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    log(f"wrote {len(feats)} place names")


def write_rail(old):
    """Railway lines from OpenStreetMap, each from the year in data/manual/rail_years.csv that its
    line opened (and until it closed). The tracks are today's: the corridors have been widened,
    raised and shifted since they opened."""
    rows = [r for r in csv.DictReader((MANUAL / "rail_years.csv").open()) if r["year"].strip()]
    lines_named = {r["line"] for r in rows}

    def row(name, lon):
        """The table row for a track: by line name, and by longitude where a line has two rows."""
        return next(r for r in rows if r["line"] == name
                    and float(r["min_lon"] or -180) <= lon < float(r["max_lon"] or 180))

    ways = json.loads((RAW / "osm" / "rail_fort.json").read_text())["elements"]
    found, lines = [], []
    for w in ways:
        t = w["tags"]
        name = re.sub(r"^(GO Transit - |Metrolinx )", "", t.get("name", ""))
        # main tracks only: yards, sidings and crossovers would crowd the corridor
        if "railway" not in t or name not in lines_named or t.get("service"):
            continue
        line = shapely.LineString([(p["lon"], p["lat"]) for p in w["geometry"]])
        found.append(row(name, line.centroid.x))
        lines.append(line)
    g = gpd.GeoDataFrame({"name": [r["line"] for r in found], "opened": [float(r["year"]) for r in found],
                          "end": [int(r["end_year"] or 9999) for r in found]}, geometry=lines, crs=4326).to_crs(UTM)
    g = g[shapely.intersects(shapely.buffer(old, 300), g.geometry.values)].reset_index(drop=True)

    # Along the harbour today's tracks lie on ground filled in since. For each mapped shore, the
    # stretches then under water are moved to the shore of that year, where the first tracks ran;
    # the real track is drawn from the year all of it is on land.
    frames = water.frames()[0]
    steps = sorted(frames)
    harbour = gpd.GeoSeries([box(HARBOUR[0], 43.60, HARBOUR[1], 43.66)], crs=4326).to_crs(UTM).iloc[0]
    pts = [shapely.points(shapely.get_coordinates(shapely.segmentize(line, 15))) for line in g.geometry.values]
    dry_from = np.full(len(g), float(FIRST_YEAR))
    moved = []
    for start, stop in zip(steps, steps[1:] + [water.MODERN_FADE[1]]):
        # the shore without its wharves, a little inland
        ground = harbour.difference(frames[start]).buffer(-35).buffer(35).buffer(-10)
        for i, p in enumerate(pts):
            wet = shapely.contains(harbour, p) & ~shapely.contains(ground, p)
            if not wet.any():
                continue
            dry_from[i] = stop
            if stop <= g.opened[i] or start >= g.end[i]:
                continue
            ashore = shapely.get_coordinates(shapely.shortest_line(p[wet], ground))[1::2]
            xy = shapely.get_coordinates(p)
            if np.hypot(*(ashore - xy[wet]).T).max() > MAX_SHIFT_M:
                continue  # too far out to say where it ran
            xy[wet] = ashore
            line = shapely.LineString(xy).simplify(4)
            if line.length > 1:
                moved.append({"name": g.name[i], "y": int(max(g.opened[i], start)),
                              "end": int(min(g.end[i], stop)), "geometry": line})
    g["y"] = np.maximum(g.opened, dry_from).astype(int)
    drawn = pd.concat([g[g.y < g.end][["name", "y", "end", "geometry"]],
                       gpd.GeoDataFrame(moved, columns=["name", "y", "end", "geometry"], crs=UTM)])
    feats = []
    for (name, y, end), part in drawn.groupby(["name", "y", "end"]):
        line = shapely.simplify(shapely.line_merge(shapely.union_all(part.geometry.values)), 1.0)
        feats.append({"type": "Feature", "geometry": lonlat_json(line),
                      "properties": {"name": name, "y": int(y), "end": int(end)}})
    (OUT / "rail.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                              separators=(",", ":")))
    log(f"wrote {len(g):,} railway tracks as {len(feats)} lines, {len(moved)} pieces moved to the old shore:",
        g.groupby("name").y.agg(["min", "max", "size"]).to_string())
    return g


def write_sites():
    """Outlines of the sites in data/manual/sites.csv (the ramparts of Fort York)."""
    feats = [{"type": "Feature", "geometry": json.loads(shapely.to_geojson(shapely.from_wkt(r["wkt"]))),
              "properties": {"name": r["name"], "kind": r["kind"], "y": int(r["year"])}}
             for r in csv.DictReader((MANUAL / "sites.csv").open())]
    (OUT / "sites.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))


def write_forest(old, s, xy, years, rail):
    """Forest, as one ring per year: the ground cleared that year. Three parts:
      - 1793: everything is forest. An assumption.
      - 1851: woods stand where J.O. Browne's map of the Township of York draws them
        (pipeline/woods.py). Between the two, the other land is cleared outward from the roads of
        the 1790s, reaching FARM_M from them by 1851. The spread is an estimate.
      - everywhere and always: a place is cleared when the first street, building or named site
        comes within CLEAR_M of it (60 m for a railway). After 1851 this is the only way the woods
        on the map go, so woods far from any street stay to the present."""
    frames, marsh, _ = water.frames()
    zone = water.to_utm(water.ISLAND_ZONE)
    land = old.difference(shapely.union_all([frames[min(frames)], frames[WOODS_YEAR], marsh, zone]))
    land = land.buffer(-30).buffer(30)  # drops the wharves
    woods = shapely.union_all(gpd.read_file(ROOT / "data" / "interim" / "woods_1851.geojson").geometry.values)
    cleared_by = {}

    def add(year, geoms):
        cleared_by.setdefault(int(year), []).extend(geoms)

    for year, g in s.groupby("year"):
        add(year, shapely.buffer(g.geometry.values, CLEAR_M, quad_segs=4))
    for year, g in rail.groupby("y"):
        add(year, shapely.buffer(g.geometry.values, 60, quad_segs=4))
    for year in np.unique(years):
        add(year, shapely.buffer(shapely.points(xy[years == year]), CLEAR_M, quad_segs=4))
    first_roads = shapely.union_all(s.geometry.values[s.year.values <= 1800])
    for year in range(FIRST_YEAR + 4, WOODS_YEAR, 3):
        reach = FARM_M * (year - FIRST_YEAR) / (WOODS_YEAR - FIRST_YEAR)
        add(year, [first_roads.buffer(reach, quad_segs=4).difference(woods)])
    add(WOODS_YEAR, [land.difference(woods)])
    for r in csv.DictReader((MANUAL / "places.csv").open()):
        if r["kind"] in ("city", "site") and r["from_year"]:
            pt = gpd.GeoSeries(gpd.points_from_xy([float(r["lon"])], [float(r["lat"])]), crs=4326).to_crs(UTM)
            add(r["from_year"], [pt.iloc[0].buffer(2 * CLEAR_M)])

    feats, left = [], land
    for year in sorted(cleared_by):
        ring = left.intersection(shapely.union_all(cleared_by[year]))
        left = left.difference(ring)
        if not ring.is_empty and year > FIRST_YEAR:
            feats.append({"type": "Feature", "geometry": lonlat_json(shapely.simplify(ring, 4)),
                          "properties": {"y": year}})
    feats.append({"type": "Feature", "geometry": lonlat_json(shapely.simplify(left, 4)), "properties": {"y": 9999}})
    (OUT / "forest.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                                separators=(",", ":")))
    log(f"wrote forest: {len(feats)} rings, {(OUT / 'forest.json').stat().st_size / 1e6:.1f} MB;",
        f"never cleared {left.area / land.area:.0%} of the land")


def write_parks(old):
    """Today's parks, cemeteries and golf courses from the City's Green Spaces file. They have no
    dates: the web map shows them green in every year, under the forest, so a park is forest until
    its surroundings are cleared and a park from then on, whenever it was really laid out."""
    g = gpd.read_file(RAW / "green_spaces.geojson")
    g = g[g.AREA_CLASS.isin(["Park", "Cemetery", "OTHER_CEMETERY", "Golf Course", "OTHER_GOLFCOURSE",
                             "Open Green Space", "OTHER_TRCA"])].to_crs(UTM)
    green = shapely.union_all(shapely.make_valid(g.geometry.values)).intersection(old)
    green = shapely.simplify(green.buffer(0), 3)
    (OUT / "parks.json").write_text(json.dumps(lonlat_json(green), separators=(",", ":")))
    log(f"wrote parks: {green.area / 1e4:.0f} ha, {(OUT / 'parks.json').stat().st_size / 1e6:.1f} MB")


def write_area(old):
    """Outline of the area the map covers."""
    line = gpd.GeoSeries([shapely.simplify(old, 5).boundary], crs=UTM).to_crs(4326).iloc[0]
    (OUT / "area.json").write_text(shapely.to_geojson(shapely.set_precision(line, 1e-6)))


if __name__ == "__main__":
    old = gpd.read_file(RAW / "former_municipalities.geojson")
    old = old[old.AREA_NAME == "TORONTO"].to_crs(UTM).geometry.iloc[0]
    xy, years, tiers = load_buildings()
    s = load_segments(old)
    year = from_buildings(s, xy, years, tiers)
    log(f"  dated from buildings: {np.isfinite(year).sum():,} of {len(s):,}")
    year = np.fmin(year, mapped_extents(s))
    same, every = neighbours(s)
    year = no_holes(year, same, every)
    year, fixed = documented(s, year)
    year = np.where(np.isnan(year), LAST_YEAR, year)
    dry = dry_since(s.geometry.values)
    late = ~fixed & (dry > year)
    year[late] = dry[late]
    log(f"  held back until the ground was dry land: {late.sum():,}")
    s["year"] = np.clip(np.round(year), FIRST_YEAR, LAST_YEAR).astype(int)
    log((s.year // 10 * 10).value_counts().sort_index().to_string())
    write_streets(s)
    write_places()
    write_forest(old, s, xy, years, write_rail(old))
    write_sites()
    write_parks(old)
    write_area(old)
