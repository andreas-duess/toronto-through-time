"""Give every building in the old City of Toronto a construction year and write
the files the web map loads (web/public/data/).

Year sources, best first (the tier number is stored per building):
  0 landmark   Wikidata inception / opening date, plus data/manual/landmarks.csv
  1 heritage   City of Toronto Heritage Register, construction date field
  2 apartment  RentSafeTO apartment building registration, YEAR_BUILT
  3 permit     "New Building" permits, 2001 onwards
  4 massing    first year the building shows up in the city's yearly 3D
               massing model (2018 onwards; 2017 is the baseline)
  5 estimate   everything else: 2021 census construction periods for the
               neighbourhood, ordered by the dates of nearby dated buildings
data/manual/sites.csv then sets one documented year for every building inside a site (Fort York).

Run: uv run pipeline/build.py
"""
import csv
import glob
import json
import pathlib
import re

import geopandas as gpd
import numpy as np
import openpyxl
import pandas as pd
import shapely
import shapely.affinity

import pack
import water
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MANUAL = ROOT / "data" / "manual"
OUT = ROOT / "web" / "public" / "data"

ACTIVE = "permits_active.csv"
UTM = "EPSG:26917"
ORIGIN = (-79.39, 43.66)  # the web map draws positions as offsets from here
FIRST_YEAR = 1793
LAST_YEAR = 2026
TIERS = ["landmark", "heritage", "apartment", "permit", "massing", "estimate"]
MASSING, ESTIMATE = 4, 5
BASELINE = 2017  # oldest massing snapshot with the same schema as today's
TALL = 20  # metres; about six storeys

# Wikidata classes whose date is a founding date or that are not buildings.
NOT_A_BUILDING = re.compile(
    r"hospital|bar$|café|bakery|golf|club|metro station|station located|elevated station|"
    r"square|street|park|monument|memorial|bridge|road|busway|airport|aerodrome|"
    r"destroyed|cemetery|statue|historic house museum")

CENSUS_PERIODS = [  # label in the neighbourhood profile -> (first year, last year)
    ("1960 or before", (FIRST_YEAR, 1960)),
    ("1961 to 1980", (1961, 1980)),
    ("1981 to 1990", (1981, 1990)),
    ("1991 to 2000", (1991, 2000)),
    ("2001 to 2005", (2001, 2005)),
    ("2006 to 2010", (2006, 2010)),
    ("2011 to 2015", (2011, 2015)),
    ("2016 to 2021", (2016, 2021)),
]
LAST_HOUSE_PERIOD = 3  # houses have reliable permits from 2001, towers do not


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- buildings

def load_buildings():
    old = gpd.read_file(RAW / "former_municipalities.geojson")
    old = old[old.AREA_NAME == "TORONTO"].to_crs(UTM).geometry.iloc[0]
    b = gpd.read_file(RAW / "massing_2025" / "3DMassingShapefile_2025_WGS84.shp").to_crs(UTM)
    b["geometry"] = shapely.force_2d(b.geometry.values)
    b = b[b.geometry.is_valid & ~b.geometry.is_empty]
    b = b[shapely.contains(old, b.geometry.centroid.values)].reset_index(drop=True)

    # Lidar houses: AVG_HEIGHT is the roof average, MAX_HEIGHT the ridge. Site-plan
    # and 3D-model rows carry the height in AVG_HEIGHT with MAX_HEIGHT = 0.
    low_lidar = (b.HEIGHT_SRC == "Lidar-Derived") & (b.MAX_HEIGHT <= 15)
    top = np.where(low_lidar, b.AVG_HEIGHT, np.maximum(b.MAX_HEIGHT, b.AVG_HEIGHT))
    base = b.MIN_HEIGHT.clip(lower=0).to_numpy()
    b["base"] = base
    b["top"] = np.where(top > base + 1, top, base + 3)
    b["area"] = b.geometry.area
    # The model started from aerial photogrammetry; buildings added since come
    # from site plans and 3D models, so the source marks the newer ones.
    b["newer_source"] = b.BLDG_SRC != "Photogrammetrics"
    # for the sloped roofs of houses (roofs()): the roof's average height and its highest point
    lidar = b.HEIGHT_SRC == "Lidar-Derived"
    b["roof_avg"], b["roof_peak"] = b.AVG_HEIGHT.where(lidar), b.MAX_HEIGHT.where(lidar)
    b = b[b.area >= 8].reset_index(drop=True)
    b = churches(shapes(b))
    log(f"buildings in old Toronto: {len(b):,} polygons")
    return b[["base", "top", "area", "newer_source", "church", "part_of", "shaped", "roof_avg", "roof_peak", "geometry"]], old


# ---------------------------------------------------------------- shapes

def shapes(b):
    """Gives the buildings that are more than one block their real shape.

    The outline edition of the City's model has one outline per building with one height, so a
    building with towers, wings and a deck (West Lodge) stood as one slab as tall as its highest
    point. pipeline/shapes.py reads the blocks of such buildings off the City's detailed model.
    Here each block goes to the outline it lies in; an outline whose blocks cover most of it is
    replaced by them: the largest block takes the outline's place, the others are added as parts
    of it. Blocks stand on the ground. Churches whose parts OpenStreetMap has are left as they
    are (churches()).
    """
    b["church"], b["part_of"], b["shaped"] = False, np.nan, False
    path = ROOT / "data" / "interim" / "shapes.gpkg"
    if not path.exists():
        return b
    blocks = gpd.read_file(path)
    bi, oi = b.sindex.query(blocks.geometry, predicate="intersects")
    inside = shapely.area(shapely.intersection(blocks.geometry.values[bi], b.geometry.values[oi]))
    pairs = pd.DataFrame({"block": bi, "outline": b.index[oi], "inside": inside})
    pairs = pairs.sort_values("inside").drop_duplicates("block", keep="last")
    pairs = pairs[pairs.inside >= 0.5 * blocks.geometry.area.values[pairs.block]]
    worship, parts = osm_polygons("worship.json"), osm_polygons("parts.json")
    mapped = worship.iloc[np.unique(worship.sindex.query(parts.geometry, predicate="intersects")[1])]
    keep_out = set(b.index[np.unique(mapped.sindex.query(b.geometry, predicate="intersects")[0])])
    extra = []
    for outline, group in pairs.groupby("outline"):
        mine = blocks.iloc[group.block.values].sort_values("height", ascending=False)
        if outline in keep_out or len(mine) < 2 or group.inside.sum() < 0.6 * b.area[outline]:
            continue
        mine = mine.assign(area=mine.geometry.area).sort_values("area", ascending=False)
        first = mine.iloc[0]
        b.loc[outline, ["base", "top", "area", "shaped", "roof_avg", "roof_peak"]] = [0, first.height, first.area, True, np.nan, np.nan]
        b.loc[[outline], "geometry"] = [first.geometry]
        for block in mine.iloc[1:].itertuples():
            extra.append({"base": 0.0, "top": block.height, "area": block.area, "geometry": block.geometry, "part_of": outline,
                          "newer_source": b.newer_source[outline], "church": False, "shaped": True})
    log(f"shapes: {int(b.shaped.sum()):,} outlines replaced by {int(b.shaped.sum()) + len(extra):,} blocks of the detailed model")
    return pd.concat([b, gpd.GeoDataFrame(extra, geometry="geometry", crs=UTM)], ignore_index=True) if extra else b


# ---------------------------------------------------------------- churches

SPIRE_STEPS = 5      # a spire is drawn as this many blocks, each smaller than the one below
POINTED = ("pyramidal", "dome", "onion", "cone", "round", "hipped")


def osm_polygons(name):
    """Closed ways of an Overpass file as polygons (UTM), with their tags."""
    rows = []
    for e in json.loads((RAW / "osm" / name).read_text())["elements"]:
        ring = [(n["lon"], n["lat"]) for n in e.get("geometry", [])]
        if len(ring) >= 4 and ring[0] == ring[-1]:
            rows.append({**e["tags"], "geometry": shapely.Polygon(ring)})
    g = gpd.GeoDataFrame(rows, geometry="geometry", crs=4326).to_crs(UTM)
    g["geometry"] = g.geometry.buffer(0)
    return g[~g.geometry.is_empty].reset_index(drop=True)


def metres(value):
    try:
        return float(str(value).replace("m", "").strip())
    except ValueError:
        return np.nan


def spire(shape, foot, tip):
    """Blocks standing in for a pointed roof over a shape, from foot to tip."""
    centre = shape.centroid
    rows = []
    for k in range(SPIRE_STEPS):
        size = 1 - (k + 0.5) / SPIRE_STEPS
        rows.append({"base": foot + (tip - foot) * k / SPIRE_STEPS, "top": foot + (tip - foot) * (k + 1) / SPIRE_STEPS,
                     "geometry": shapely.affinity.scale(shape, size, size, origin=centre)})
    return rows


def churches(b):
    """Gives churches a body and a tower in place of one block as tall as the spire.

    The city's model has one outline per church with the height of its highest point, so St.
    James' Cathedral stood as a 71 m block. A church here is a building on a place of worship in
    OpenStreetMap. Its outline goes down to the model's average height, the body of the church.
    Towers and spires come from OpenStreetMap where it has the building's parts with heights
    (St. James': the tower, the spire to 93 m, the nave). Elsewhere a small outline of the model
    that is itself the tower keeps its height with a spire on top, and a church with neither gets
    a tower at the street end of its long side, as tall as the model's highest point: a guess at
    where the tower stands.
    """
    worship = osm_polygons("worship.json")
    parts = osm_polygons("parts.json")
    bi, wi = worship.sindex.query(b.geometry, predicate="intersects")
    inside = shapely.area(shapely.intersection(b.geometry.values[bi], worship.geometry.values[wi])) > 0.5 * b.area.values[bi]
    site = pd.Series(wi[inside], index=b.index[bi[inside]])
    site = site[~site.index.duplicated()]
    b.loc[site.index, "church"] = True
    streets = gpd.read_file(RAW / "centreline.gpkg").to_crs(UTM).geometry
    streets = streets[~streets.is_empty]

    extra = []
    pi, wi = worship.sindex.query(parts.geometry, predicate="intersects")
    mapped = set(wi)        # places of worship with parts in OpenStreetMap
    for k in np.unique(pi):
        part = parts.iloc[k]
        top, foot, roof = metres(part.get("height")), metres(part.get("min_height")), metres(part.get("roof:height"))
        if not top > 0 or part.geometry.area < 2:
            continue
        foot, roof = (0 if np.isnan(foot) else foot), (0 if np.isnan(roof) else min(roof, top))
        if part.get("roof:shape") in POINTED and roof >= 3:
            if top - roof > foot:
                extra.append({"base": foot, "top": top - roof, "geometry": part.geometry})
            extra += spire(part.geometry, max(foot, top - roof), top)
        elif top - roof / 2 > foot:
            extra.append({"base": foot, "top": top - roof / 2, "geometry": part.geometry})

    spiky = b.church & ~b.shaped.astype(bool) & (b.HEIGHT_SRC == "Lidar-Derived") & (b.MAX_HEIGHT > 15) & (b.MAX_HEIGHT > 1.5 * b.AVG_HEIGHT.clip(lower=1))
    small = b.area < 150      # an outline this small is the tower itself
    guessed = 0
    for i in b.index[spiky]:
        row = b.loc[i]
        body = max(row.AVG_HEIGHT, row.base + 3)
        b.loc[i, "top"] = body
        if site[i] in mapped:
            continue
        if small[i]:
            extra += spire(row.geometry, body, row.MAX_HEIGHT)
            continue
        others = site.index[(site == site[i]).values]
        if (small[others] & (b.MAX_HEIGHT[others] >= 0.8 * row.MAX_HEIGHT)).any() or row.MAX_HEIGHT < body + 8:
            continue
        # a tower at the end of the long side that is nearer a street
        box = shapely.get_coordinates(shapely.minimum_rotated_rectangle(row.geometry))[:4]
        a, c = (box[0] + box[1]) / 2, (box[2] + box[3]) / 2
        short = np.hypot(*(box[1] - box[0]))
        if np.hypot(*(c - a)) < short:
            a, c, short = (box[1] + box[2]) / 2, (box[3] + box[0]) / 2, np.hypot(*(box[2] - box[1]))
        side = float(np.clip(0.35 * short, 4, 8))
        ends = [e + (o - e) / np.hypot(*(o - e)) * (side / 2 + 0.5) for e, o in ((a, c), (c, a))]
        near = [streets.distance(shapely.Point(e)).min() for e in ends]
        tower = shapely.Point(ends[int(np.argmin(near))]).buffer(side / 2, cap_style="square")
        shaft = max(body + 2, 0.55 * row.MAX_HEIGHT)
        extra.append({"base": row.base, "top": shaft, "geometry": tower})
        extra += spire(tower, shaft, row.MAX_HEIGHT)
        guessed += 1

    add = gpd.GeoDataFrame(extra, geometry="geometry", crs=UTM)
    add["area"] = add.geometry.area
    add = add[(add.area >= 2) & (add.top > 3)].reset_index(drop=True)
    add["newer_source"], add["church"] = False, True
    # each block belongs to the church outline it stands on most; one that stands on none goes
    own = b[b.church]
    ai, oi = own.sindex.query(add.geometry, predicate="intersects")
    shared = pd.DataFrame({"add": ai, "of": own.index[oi],
                           "area": shapely.area(shapely.intersection(add.geometry.values[ai], own.geometry.values[oi]))})
    shared = shared.sort_values("area").drop_duplicates("add", keep="last")
    add["part_of"] = pd.Series(shared.of.values, index=shared["add"].values)
    add = add[add.part_of.notna()]
    log(f"churches: {int(b.church.sum())} outlines on {site.nunique()} places of worship, {int(spiky.sum())} lowered to their body, "
        f"{len(mapped)} with parts from OpenStreetMap, {guessed} with a guessed tower, {len(add)} blocks added")
    return pd.concat([b, add], ignore_index=True)


def first_seen(b, old):
    """First massing snapshot (BASELINE..2025) that already has each building."""
    bounds = tuple(gpd.GeoSeries([old], crs=UTM).to_crs(3857).total_bounds)
    first = np.full(len(b), 2025)
    for year in range(2023, BASELINE - 1, -1):
        path = glob.glob(str(RAW / f"massing_{year}" / "**" / "*.shp"), recursive=True)[0]
        try:
            s = gpd.read_file(path, bbox=bounds)
        except Exception:  # the 2018 file's spatial index is broken
            s = gpd.read_file(path)
        s = s.to_crs(UTM)
        geom = shapely.make_valid(shapely.force_2d(s.geometry.values))
        top = np.maximum(s.MAX_HEIGHT, s.AVG_HEIGHT).values
        bi, si = shapely.STRtree(geom).query(b.geometry.values, predicate="intersects")
        # a shorter building on the same lot is the one that was replaced
        # (a block of a building's real shape can be much lower than the outline it came from)
        same = (top[si] >= 0.6 * b.top.values[bi]) | b.shaped.values[bi].astype(bool)
        bi, si = bi[same], si[same]
        inter = shapely.area(shapely.intersection(b.geometry.values[bi], geom[si]))
        covered = np.bincount(bi, weights=inter, minlength=len(b)) / b.area.values
        first[covered >= 0.5] = year
    return first


def group_parts(b):
    """Stacked parts of one building (podium, tower) overlap; neighbours only touch."""
    left, right = b.sindex.query(b.geometry, predicate="intersects")
    keep = left < right
    left, right = left[keep], right[keep]
    inter = shapely.area(shapely.intersection(b.geometry.values[left], b.geometry.values[right]))
    same = inter > 0.5 * np.minimum(b.area.values[left], b.area.values[right])
    parent = np.arange(len(b))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in zip(left[same], right[same]):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri
    b["group"] = [find(i) for i in range(len(b))]
    # the towers and spires added to a church are part of it
    added = b.part_of.notna()
    b.loc[added, "group"] = b.group[b.part_of[added].astype(int)].values
    log(f"  grouped into {b.group.nunique():,} buildings")


# ------------------------------------------------------------- dated points

def norm_address(s):
    s = re.sub(r"\s+", " ", str(s).upper()).strip()
    return re.sub(r"^(\d+)[A-Z]?\s*-\s*\d+[A-Z]?", r"\1", s)  # "181-183 X ST" -> "181 X ST"


def load_address_points():
    ap = pd.read_csv(RAW / "address_points.csv", dtype=str,
                     usecols=["ADDRESS_POINT_ID", "ADDRESS_FULL", "geometry"])
    xy = ap.geometry.str.extract(r"\[\[([-\d.]+), ([-\d.]+)\]")
    ap["lon"], ap["lat"] = xy[0].astype(float), xy[1].astype(float)
    ap["addr"] = ap.ADDRESS_FULL.map(norm_address)
    return ap.drop(columns=["geometry"]).rename(columns={"ADDRESS_FULL": "address"})


def wikidata_points():
    rows = json.loads((RAW / "wikidata_buildings.json").read_text())
    rows = [r for r in rows if not any(NOT_A_BUILDING.search(c) for c in r["classes"])]
    df = pd.DataFrame(rows)[["name", "lon", "lat", "year", "url"]]
    # manual rows are hand-checked and win over Wikidata for the same building
    df = pd.concat([pd.read_csv(MANUAL / "landmarks.csv").assign(checked=True), df], ignore_index=True)
    df["tier"] = 0
    return df


def heritage_points():
    h = gpd.read_file(RAW / "heritage_register" / "HRAPQ32026_OpenData.shp")
    h = h[h.CONSTRUCTI.notna() & ~h.BUILDING_T.isin(["Demolished", "Miscellaneous"])]
    # "1903-1910 (circa)" -> 1910: the year the building was finished
    years = h.CONSTRUCTI.str.findall(r"\b(1[6-9]\d\d|20[0-2]\d)\b").map(lambda y: int(y[-1]) if y else None)
    # "Fort York Armouries, 1933, Marani, Lawson & Morris -adopted ..." -> "Fort York Armouries"
    names = h.DESCRIPTIO.str.extract(r"^([A-Z][^,;\n]{2,60}?),\s*(?:c\.?\s*)?(?:1[6-9]\d\d|20[0-2]\d)")[0]
    # not names: "House", "Semi-detached house", "Included on the City's Heritage Register on ..."
    generic = names.fillna("").str.match(
        r"(?i)^((semi-)?detached |row |pair of )?(houses?|apartments?|apartment building|stores?|shops?|"
        r"residence|building|commercial building|warehouse|factory|garage)$|^(Part of|Included|Listed)\b")
    names = names.where(~generic)
    return pd.DataFrame({"lon": h.geometry.x, "lat": h.geometry.y, "year": years,
                         "name": names, "url": None, "tier": 1}).dropna(subset=["year"])


def apartment_points(ap):
    a = pd.read_csv(RAW / "apartment_registration.csv", dtype=str)
    a["addr"] = a.SITE_ADDRESS.map(norm_address)
    a["year"] = pd.to_numeric(a.YEAR_BUILT, errors="coerce")
    a = a[a.year.between(1850, LAST_YEAR)].merge(ap.drop_duplicates("addr"), on="addr")
    return pd.DataFrame({"lon": a.lon, "lat": a.lat, "year": a.year, "name": None, "url": None, "tier": 2})


def permit_points(ap):
    cols = ["PERMIT_TYPE", "STRUCTURE_TYPE", "WORK", "STREET_NUM", "STREET_NAME", "STREET_TYPE",
            "STREET_DIRECTION", "GEO_ID", "ISSUED_DATE", "COMPLETED_DATE", "STATUS"]
    p = pd.concat(pd.read_csv(RAW / f, dtype=str, usecols=cols, low_memory=False).assign(active=f == ACTIVE)
                  for f in ["permits_cleared_2000_2016.csv", "permits_cleared_2017_on.csv", ACTIVE])
    # Large projects often stay "active" for decades after people move in, so
    # active permits count too, as long as they were issued early enough for
    # the building to stand in the 2025 massing model.
    p = p[(p.WORK == "New Building") & np.where(
        p.active, p.STATUS.isin(["Inspection", "Revision Issued", "Permit Issued"])
        & (p.ISSUED_DATE.str[:4] <= "2022"), p.STATUS == "Closed")]
    p = p[~p.STRUCTURE_TYPE.fillna("").str.contains("Garage|Accessory|Temporary|Tent|Transit", case=False)]
    done = pd.to_numeric(p.COMPLETED_DATE.str[:4], errors="coerce")
    issued = pd.to_numeric(p.ISSUED_DATE.str[:4], errors="coerce")
    # Many permits were closed in bulk years after the work ended (2025 and 2026
    # have twice the usual count), so cap the year at a normal build time.
    build_time = np.where(p.STRUCTURE_TYPE.fillna("").str.startswith(("SFD", "2 Unit", "3+ Unit")), 2, 5)
    p["year"] = np.fmin(done, issued + build_time).clip(upper=2025)
    p = p.dropna(subset=["year"])
    p["addr"] = (p.STREET_NUM.fillna("") + " " + p.STREET_NAME.fillna("") + " " + p.STREET_TYPE.fillna("")
                 + " " + p.STREET_DIRECTION.fillna("")).map(norm_address)
    by_id = p.merge(ap, left_on="GEO_ID", right_on="ADDRESS_POINT_ID")
    rest = p[~p.GEO_ID.isin(ap.ADDRESS_POINT_ID)].merge(ap.drop_duplicates("addr"), on="addr")
    log(f"  permits: {len(p):,} new buildings, {len(by_id):,} located by id, {len(rest):,} by address")
    j = pd.concat([by_id, rest])
    return pd.DataFrame({"lon": j.lon, "lat": j.lat, "year": j.year, "name": None, "url": None, "tier": 3})


def too_tall_for_year(year, height):
    """An old date on a tower means a kept facade or a mismatch: the date belongs to an old
    building on the site, the height to the tower that replaced it. Before 1950 the city had only
    a handful of buildings over 60 m, and those are listed by hand (data/manual/tall_old.csv)."""
    return ((year < 1905) & (height > 45)) | ((year < 1950) & (height > 60)) | ((year < 1967) & (height > 110))


def tall_and_old(main):
    """Groups of the buildings in data/manual/tall_old.csv, whose old dates are right."""
    t = pd.read_csv(MANUAL / "tall_old.csv")
    pts = gpd.GeoSeries(gpd.points_from_xy(t.lon, t.lat), crs=4326).to_crs(UTM)
    _, bi = main.sindex.nearest(pts, max_distance=20, return_all=False)
    return set(main.group.values[bi])


def assign_dated(b, points, old):
    pts = gpd.GeoDataFrame(points, geometry=gpd.points_from_xy(points.lon, points.lat), crs=4326).to_crs(UTM)
    pts = pts[shapely.contains(shapely.buffer(old, 50), pts.geometry.values)].reset_index(drop=True)
    main = b[b.area >= 30]
    pi, bi = main.sindex.nearest(pts.geometry, max_distance=20, return_all=False)
    hit = pd.DataFrame({"poly": main.index.values[bi], "group": main.group.values[bi],
                        "height": (main.top - main.base).values[bi],
                        "year": pts.year.values[pi].astype(int), "tier": pts.tier.values[pi],
                        "name": pts.name.values[pi], "url": pts.url.values[pi],
                        "checked": pts.checked.values[pi] == True})  # noqa: E712 (NaN is not checked)
    # and no church is too tall for its year: its height is its spire
    known = tall_and_old(main) | set(b.group[b.church])
    hit = hit[~(too_tall_for_year(hit.year, hit.height) & ~hit.checked & ~hit.group.isin(known))
              & hit.year.between(FIRST_YEAR, LAST_YEAR)]
    log("  dated points matched to a building, by tier:",
        {TIERS[t]: n for t, n in hit.tier.value_counts().sort_index().items()})
    # Best tier wins; within a tier the latest year (a rebuild replaces the old
    # date). A part keeps the point that landed on it; the building's best
    # point fills the parts that got none.
    hit = hit.sort_values(["tier", "year"], ascending=[True, False], kind="stable")
    own = hit.drop_duplicates("poly").set_index("poly")
    shared = hit.drop_duplicates("group").set_index("group")
    # A tower standing on a dated old base (a kept facade) is its own building.
    split = ~b.index.isin(own.index) & too_tall_for_year(b.group.map(shared.year), b.top - b.base) & ~b.group.isin(known)
    b.loc[split, "group"] = b.group.max() + 1 + np.arange(split.sum())
    for col in ["year", "tier", "name", "url"]:
        b[col] = b.index.map(own[col]).where(b.index.isin(own.index), b.group.map(shared[col]))
    # every part of a named landmark carries its name
    for col in ["name", "url"]:
        b[col] = b[col].fillna(b.group.map(shared[col]))


def assign_massing(b, old):
    b["first_seen"] = first_seen(b, old)
    new = b.year.isna() & (b.first_seen > BASELINE)
    b.loc[new, "year"] = b.first_seen[new]
    b.loc[new, "tier"] = MASSING
    log(f"  first seen in the massing model after {BASELINE}: {new.sum():,} undated polygons")


# ---------------------------------------------------------------- estimates

def census_periods():
    wb = openpyxl.load_workbook(RAW / "neighbourhood_profiles_2021.xlsx", read_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    names = [str(n).strip() for n in rows[0][1:]]
    start = next(i for i, r in enumerate(rows) if str(r[0]).startswith("Total - Occupied private dwellings by period"))
    table = {}
    for r in rows[start + 1:start + 9]:
        table[str(r[0]).strip()] = [float(v or 0) for v in r[1:]]
    return pd.DataFrame(table, index=names)


def neighbour_year(b, dated, undated, max_year):
    """Distance-weighted median year of the 8 nearest dated buildings up to max_year."""
    src = dated[dated.year <= max_year]
    cen = np.c_[src.geometry.centroid.x, src.geometry.centroid.y]
    dist, idx = cKDTree(cen).query(np.c_[undated.geometry.centroid.x, undated.geometry.centroid.y], k=8)
    years = src.year.values[idx]
    weight = 1 / (dist + 30)
    order = np.argsort(years, axis=1)
    years, weight = np.take_along_axis(years, order, 1), np.take_along_axis(weight, order, 1)
    half = (np.cumsum(weight, 1) >= weight.sum(1, keepdims=True) / 2).argmax(1)
    return years[np.arange(len(years)), half]


def hand_out(dwellings, left, newest):
    """Give each building (ordered oldest to newest) a census period.

    Walks from the newest building back, handing out the dwellings the census
    still has unexplained in period `newest`, then the one before, down to
    period 1. Buildings left over when those run out get period 0.
    """
    newest_first = dwellings[::-1]
    before = (np.cumsum(newest_first) - newest_first / 2)[::-1]
    edges = np.cumsum(left[newest:0:-1])
    return newest - np.searchsorted(edges, before)


def spread(period, k, y0, y1):
    """Years for the buildings of period k, in order, evenly across y0..y1."""
    sel = np.flatnonzero(period == k)
    return sel, y0 + (np.arange(len(sel)) + 0.5) / max(1, len(sel)) * (y1 - y0 + 1) - 0.5


def estimate_rest(b):
    hoods = gpd.read_file(RAW / "neighbourhoods.geojson").to_crs(UTM)[["AREA_NAME", "geometry"]]
    cen = gpd.GeoDataFrame(geometry=b.geometry.centroid, crs=UTM)
    b["hood"] = gpd.sjoin_nearest(cen, hoods, how="left").groupby(level=0).AREA_NAME.first()
    census = census_periods()

    # one row per building: stacked parts share a year and their floor area adds up
    b["dwellings"] = np.maximum(1, b.area * np.maximum(1, (b.top - b.base) / 3) / 100)
    g = b.dissolve("group", aggfunc={"year": "first", "hood": "first", "dwellings": "sum",
                                     "top": "max", "newer_source": "max"})
    dated = g[g.year.notna() & (g.year <= 2000)]
    undated = g[g.year.isna()].copy()
    undated["rank_year"] = neighbour_year(g, dated, undated, 2000)
    undated["old_year"] = neighbour_year(g, dated, undated, 1960)
    last = len(CENSUS_PERIODS) - 1

    est = pd.Series(index=undated.index, dtype=float)
    for hood, u in undated.groupby("hood"):
        known = g[(g.hood == hood) & g.year.notna()]
        # census dwellings per period still unexplained by dated buildings
        left = []
        for label, (y0, y1) in CENSUS_PERIODS:
            have = known.dwellings[known.year.between(y0, y1)].sum()
            left.append(max(0.0, census.at[hood, label] - have) if hood in census.index else 0.0)

        # Towers first. An undated building over about six storeys is almost never
        # older than 1960 (the old tall ones are in the registers), and all of
        # these were standing in the baseline snapshot.
        tall = u[u.top >= TALL].sort_values(["newer_source", "rank_year"])
        period = hand_out(tall.dwellings.values, left, last)
        # towers the census has no room for: by source, before or after 2000
        stray = period == 0
        newer = tall.newer_source.values.astype(bool)
        for mask, lo, hi in [(stray & ~newer, 1, LAST_HOUSE_PERIOD), (stray & newer, LAST_HOUSE_PERIOD + 1, last)]:
            period[mask] = lo + np.arange(mask.sum()) * (hi - lo + 1) // max(1, mask.sum())
        years = np.empty(len(tall))
        for k, (_, (y0, y1)) in enumerate(CENSUS_PERIODS):
            sel, yrs = spread(period, k, y0, min(y1, BASELINE))
            years[sel] = yrs
            left[k] = max(0.0, left[k] - tall.dwellings.values[sel].sum())
        est[tall.index] = np.round(years)

        # Then the rest, which without a permit are older than 2001. Whatever is
        # left when the 1961-2000 dwellings run out is older than 1961, and
        # there the neighbours' dates are the only evidence.
        low = u[u.top < TALL].sort_values(["rank_year", "old_year"])
        period = hand_out(low.dwellings.values, left, LAST_HOUSE_PERIOD)
        years = low.old_year.values.astype(float)
        for k, (_, (y0, y1)) in enumerate(CENSUS_PERIODS[:LAST_HOUSE_PERIOD + 1]):
            if k > 0:
                sel, yrs = spread(period, k, y0, y1)
                years[sel] = yrs
        # Neighbours share one typical year, which would make whole blocks appear
        # at once. Scatter the pre-1961 estimates by up to three years either
        # way, well inside their accuracy, the same way on every run.
        scatter = (low.index.values * 2654435761 % 7) - 3
        years = np.where(period == 0, np.minimum(years + scatter, 1960), years)
        est[low.index] = np.round(years)
    # parts with no date of their own in a building that has one take that date
    for col in ["year", "tier"]:
        b[col] = b[col].fillna(b.groupby("group")[col].transform("max"))
    missing = b.year.isna()
    b.loc[missing, "year"] = b.group[missing].map(est)
    b.loc[missing, "tier"] = ESTIMATE


def apply_names(b, ap):
    """Names for buildings that have none yet, from OpenStreetMap: a named building, or a named
    hospital, school, church and the like whose grounds the building stands on. And for every
    building the street address of an address point inside it."""
    named = json.loads((RAW / "osm" / "named.json").read_text())["elements"]
    named = [e for e in named if "building" in e["tags"] and "bounds" in e]
    pts = gpd.GeoDataFrame(
        {"osm_name": [e["tags"]["name"] for e in named]},
        geometry=gpd.points_from_xy([(e["bounds"]["minlon"] + e["bounds"]["maxlon"]) / 2 for e in named],
                                    [(e["bounds"]["minlat"] + e["bounds"]["maxlat"]) / 2 for e in named]), crs=4326).to_crs(UTM)
    own = gpd.sjoin(pts, b[["geometry"]], predicate="within").groupby("index_right").osm_name.first()

    areas = [e for e in json.loads((RAW / "osm" / "named_areas.json").read_text())["elements"]
             if len(e.get("geometry", [])) >= 4 and e["geometry"][0] == e["geometry"][-1]]
    grounds = gpd.GeoDataFrame(
        {"osm_name": [e["tags"]["name"] for e in areas]},
        geometry=[shapely.Polygon([(p["lon"], p["lat"]) for p in e["geometry"]]) for e in areas], crs=4326).to_crs(UTM)
    cen = gpd.GeoDataFrame(geometry=b.geometry.centroid, crs=UTM)
    on = gpd.sjoin(cen, grounds, predicate="within").groupby(level=0).osm_name.first()

    before = b.name.notna().sum()
    b["name"] = b.name.fillna(b.index.to_series().map(own)).fillna(b.index.to_series().map(on))
    # every part of a named building carries the name
    b["name"] = b.name.fillna(b.groupby("group").name.transform("first"))
    a = gpd.GeoDataFrame(ap[["address"]], geometry=gpd.points_from_xy(ap.lon, ap.lat), crs=4326).to_crs(UTM)
    inside = gpd.sjoin(a, b[["geometry"]], predicate="within").groupby("index_right").address.first()
    b["address"] = b.index.to_series().map(inside)
    b["address"] = b.address.fillna(b.groupby("group").address.transform("first"))
    log(f"  street address for {b.address.notna().sum():,} of {len(b):,}")
    # outlines at the same street address as a named one are the same place
    at = b[b.name.notna() & b.address.notna()].groupby("address").name.first()
    b["name"] = b.name.fillna(b.address.map(at))
    # A school or a hospital is often several outlines in the City's model and one building in
    # OpenStreetMap. Outlines without a name inside the box around a named building take its
    # name (not for boxes over 1.5 ha, which take in the neighbours).
    boxes = gpd.GeoDataFrame(
        {"osm_name": [e["tags"]["name"] for e in named]},
        geometry=[shapely.box(e["bounds"]["minlon"], e["bounds"]["minlat"], e["bounds"]["maxlon"], e["bounds"]["maxlat"]) for e in named],
        crs=4326).to_crs(UTM)
    boxes = boxes[boxes.area <= 15000]
    cen = gpd.GeoDataFrame(geometry=b.geometry.centroid, crs=UTM)
    boxed = gpd.sjoin(cen, boxes, predicate="within").groupby(level=0).osm_name.first()
    b["name"] = b.name.fillna(b.index.to_series().map(boxed))
    # One building, two dates: an article dates the Eaton Centre to 1977, and a heritage listing at
    # an address inside it (an old front kept in the new building) dates one of its blocks to 1861.
    # Within one building, a part dated earlier than the building's landmark year by a lesser
    # source takes the landmark year.
    landmark = b[b.tier == 0].groupby("group").year.min()
    of_group = b.group.map(landmark)
    early = (b.tier > 0) & of_group.notna() & (b.year < of_group)
    b.loc[early, "year"] = of_group[early]
    b.loc[early, "tier"] = 0
    log(f"  {int(early.sum()):,} parts dated before their own building's landmark year moved to it")
    # ... and where one part of a named building has a year on record and another only a guess,
    # the guess gives way to the record. (An addition built later is then dated too early.)
    # Only within 200 m: a name can stand for a chain of shops across the city.
    cx, cy = b.geometry.centroid.x, b.geometry.centroid.y
    rec = b[b.name.notna() & (b.tier < ESTIMATE)]
    rec = pd.DataFrame({"name": rec.name, "rx": cx[rec.index], "ry": cy[rec.index], "ryear": rec.year, "rtier": rec.tier})
    gue = b[b.name.notna() & (b.tier == ESTIMATE)]
    pairs = pd.DataFrame({"i": gue.index, "name": gue.name, "x": cx[gue.index], "y": cy[gue.index]}).merge(rec, on="name")
    pairs = pairs[np.hypot(pairs.x - pairs.rx, pairs.y - pairs.ry) <= 200]
    # (of several parts on record, the one with the best source, then the earliest)
    near = pairs.sort_values(["rtier", "ryear"]).groupby("i").ryear.first()
    guessed = b.index.isin(near.index)
    b.loc[near.index, "year"] = near.values
    log(f"  {int(guessed.sum()):,} parts of named buildings take the year of the part on record")
    log(f"  names: {before:,} from the registers, {b.name.notna().sum() - before:,} more from OpenStreetMap")



def apply_plans(b):
    """data/interim/plan_years.csv (pipeline/lost.py): buildings whose year is only an estimate
    but which the fire insurance plans already show. The year becomes the one lost.py worked out
    from the plans; it stays an estimate, now with an upper limit."""
    path = ROOT / "data" / "interim" / "plan_years.csv"
    if not path.exists():
        return
    p = pd.read_csv(path)
    pts = gpd.GeoDataFrame(p, geometry=gpd.points_from_xy(p.lon, p.lat), crs=4326).to_crs(UTM)
    hit = gpd.sjoin(pts, b[["geometry"]], predicate="within").groupby("index_right").year.min()
    low = (b.top - b.base)[hit.index] <= 15  # a tower on old ground is not the building on the plan
    hit = hit[(b.tier[hit.index] == ESTIMATE) & (b.year[hit.index] > hit) & low]
    b.loc[hit.index, "year"] = hit
    log(f"  on the fire insurance plans earlier than estimated: {len(hit):,} buildings")


def hold_until_dry(b):
    """An estimated year cannot be earlier than the land: where the old maps show water under a
    building, its year is held back to the first map that shows land (pipeline/water.py). Not on
    the Island, whose outline off the plans is too rough for this."""
    frames = water.frames(pads=False)[0]
    cen = b.geometry.centroid.values
    since = np.full(len(b), float(FIRST_YEAR))
    steps = sorted(frames)
    for year, nxt in zip(steps, steps[1:] + [water.MODERN_FADE[1]]):
        shapely.prepare(frames[year])
        since[shapely.contains(frames[year], cen)] = nxt
    late = (b.tier == ESTIMATE).values & (b.year.values < since) & ~shapely.contains(water.to_utm(water.ISLAND_ZONE), cen)
    b.loc[late, "year"] = since[late]
    log(f"  estimated years held back until the ground was dry land: {late.sum():,}")


def apply_sites(b):
    """data/manual/sites.csv: a documented site whose buildings all share one year (Fort York).
    Overrides every other source for the buildings inside the outline."""
    for r in csv.DictReader((MANUAL / "sites.csv").open()):
        area = gpd.GeoSeries([shapely.from_wkt(r["wkt"])], crs=4326).to_crs(UTM).iloc[0]
        inside = shapely.contains(area, b.geometry.centroid.values)
        b.loc[inside, ["year", "tier", "name", "url"]] = [float(r["year"]), 1, r["name"], r["url"]]
        if r["max_height"]:
            b.loc[inside, "top"] = np.minimum(b.top[inside], b.base[inside] + float(r["max_height"]))
        log(f"  site {r['name']}: {inside.sum()} buildings set to {r['year']}")


# ------------------------------------------------------------------- output

def roofs(b):
    """Sloped roofs for the houses: lowers their walls to the eaves and returns, per roof, the
    building's number, the middle (lon, lat), and [length, width, eaves, rise (all m), direction
    of the ridge (radians, anticlockwise from east)].

    A house here is a low, small outline close to a rectangle, with heights from lidar. The
    city's model gives its roof's average height and highest point. The roof drawn is a plain
    gable over the rectangle around the outline, its ridge along the long side: the average
    height is kept, the ridge is the highest point but no steeper than ROOF_PITCH (the highest
    point is often a tree or a chimney). The shape and the direction of the ridge are drawn.
    """
    box = shapely.minimum_rotated_rectangle(b.geometry.values)
    corners = shapely.get_coordinates(shapely.get_exterior_ring(box)).reshape(-1, 5, 2)
    side_a, side_b = corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 1]
    len_a, len_b = np.hypot(*side_a.T), np.hypot(*side_b.T)
    along = np.where((len_a >= len_b)[:, None], side_a, side_b)
    length, width = np.maximum(len_a, len_b), np.minimum(len_a, len_b)
    # a highest point far above a house is a tree: a gentler roof then
    pitch = np.where(b.roof_peak <= 16, ROOF_PITCH, 0.6 * ROOF_PITCH)
    rise = np.minimum(2 * (b.roof_peak - b.roof_avg), pitch * width / 2)
    eaves = b.roof_avg - rise / 2
    house = ((b.base <= 0.5) & ~b.church & b.part_of.isna() & b.area.between(25, 450) & (b.roof_avg <= 12)
             & (b.area / shapely.area(box) >= 0.72) & (width >= 3.5) & (rise >= 0.8) & (eaves >= 2.2)).to_numpy()
    b.loc[house, "top"] = b.base[house] + eaves[house]
    middle = gpd.GeoSeries(shapely.centroid(box[house]), crs=UTM).to_crs(4326)
    info = np.column_stack([length[house], width[house], eaves[house], rise[house],
                            np.arctan2(along[house, 1], along[house, 0]) % np.pi])
    log(f"sloped roofs: {house.sum():,} of {len(b):,} outlines")
    return np.flatnonzero(house), shapely.get_coordinates(middle.values), info


ROOF_PITCH = 1.0     # rise over half the width, at most (45 degrees)


def write_roofs(ids, middle, info):
    """roofs.ids.pack (uint32), roofs.positions.pack (as the buildings' corners), roofs.info.pack
    (uint16: length, width, eaves, rise in cm; direction of the ridge as 0-65535 for 0-180 degrees)."""
    packed = np.column_stack([np.round(info[:, :4] * 100), np.round(info[:, 4] / np.pi * 65535)])
    assert packed.min() >= 0 and packed.max() < 65536
    pack.write("roofs.ids.pack", ids.astype("<u4"))
    pack.write("roofs.positions.pack", pack.deltas(middle - ORIGIN))
    pack.write("roofs.info.pack", packed.astype("<u2"))


def write_buildings(b):
    b = b.sort_values("year").reset_index(drop=True)
    write_roofs(*roofs(b))
    # outer ring only (courtyards are filled in), wound counter-clockwise for the renderer
    geom = shapely.simplify(b.geometry.to_crs(4326).values, 2e-6)
    rings = shapely.get_exterior_ring(shapely.orient_polygons(geom))
    coords, ring_of = shapely.get_coordinates(rings, return_index=True)
    counts = np.bincount(ring_of, minlength=len(b))
    starts = np.concatenate([[0], np.cumsum(counts)]).astype("<u4")
    pos = np.empty((len(coords), 3), "<f4")
    pos[:, 0] = coords[:, 0] - ORIGIN[0]
    pos[:, 1] = coords[:, 1] - ORIGIN[1]
    pos[:, 2] = np.repeat(b.base.values, counts)

    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "positions.bin": pos,
        "starts.bin": starts,
        "heights.bin": (b.top - b.base).to_numpy("<f4"),
        "years.bin": b.year.to_numpy("<u2"),
        "tiers.bin": b.tier.to_numpy("u1"),
    }
    for name, arr in files.items():
        (OUT / name).write_bytes(arr.tobytes())
    named = b[b.name.notna()]
    names = {int(i): {"name": r["name"], "url": r.url if isinstance(r.url, str) else None} for i, r in named.iterrows()}
    (OUT / "names.json").write_text(json.dumps(names))
    # one line per building, in the same order
    (OUT / "addresses.txt").write_text("\n".join(b.address.fillna("")))
    counts_by_tier = {TIERS[int(t)]: int(n) for t, n in b.tier.value_counts().sort_index().items()}
    meta = {"count": len(b), "vertices": len(coords), "origin": ORIGIN, "tiers": TIERS,
            "firstYear": FIRST_YEAR, "lastYear": LAST_YEAR, "countsByTier": counts_by_tier}
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1))
    log("wrote", len(b), "polygons;", counts_by_tier,
        f"; {sum(a.nbytes for a in files.values()) / 1e6:.1f} MB")


def write_tables():
    for name in ["population", "story"]:
        with open(MANUAL / f"{name}.csv") as f:
            rows = list(csv.DictReader(f))
        (OUT / f"{name}.json").write_text(json.dumps(rows))


if __name__ == "__main__":
    b, old = load_buildings()
    group_parts(b)
    ap = load_address_points()
    points = pd.concat([wikidata_points(), heritage_points(), apartment_points(ap), permit_points(ap)],
                       ignore_index=True)
    assign_dated(b, points, old)
    assign_massing(b, old)
    estimate_rest(b)
    apply_plans(b)
    hold_until_dry(b)
    apply_sites(b)
    apply_names(b, ap)
    b["year"] = b.year.clip(FIRST_YEAR, LAST_YEAR).astype(int)
    b["tier"] = b.tier.astype(int)
    log(b.groupby("tier").year.describe()[["count", "min", "50%", "max"]].to_string())
    log((b.year // 10 * 10).value_counts().sort_index().to_string())
    write_buildings(b)
    write_tables()
