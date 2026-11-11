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
    b = b[b.area >= 8].reset_index(drop=True)
    log(f"buildings in old Toronto: {len(b):,} polygons")
    return b[["base", "top", "area", "newer_source", "geometry"]], old


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
        same = top[si] >= 0.6 * b.top.values[bi]
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
    return ap.drop(columns=["geometry", "ADDRESS_FULL"])


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
    return pd.DataFrame({"lon": h.geometry.x, "lat": h.geometry.y, "year": years,
                         "name": None, "url": None, "tier": 1}).dropna(subset=["year"])


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
    """A 19th-century date on a tower means a kept facade or a mismatch."""
    return ((year < 1905) & (height > 45)) | ((year < 1925) & (height > 95))


def assign_dated(b, points, old):
    pts = gpd.GeoDataFrame(points, geometry=gpd.points_from_xy(points.lon, points.lat), crs=4326).to_crs(UTM)
    pts = pts[shapely.contains(shapely.buffer(old, 50), pts.geometry.values)].reset_index(drop=True)
    main = b[b.area >= 30]
    pi, bi = main.sindex.nearest(pts.geometry, max_distance=20, return_all=False)
    hit = pd.DataFrame({"poly": main.index.values[bi], "group": main.group.values[bi],
                        "height": main.top.values[bi],
                        "year": pts.year.values[pi].astype(int), "tier": pts.tier.values[pi],
                        "name": pts.name.values[pi], "url": pts.url.values[pi],
                        "checked": pts.checked.values[pi] == True})  # noqa: E712 (NaN is not checked)
    hit = hit[~(too_tall_for_year(hit.year, hit.height) & ~hit.checked)
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
    split = ~b.index.isin(own.index) & too_tall_for_year(b.group.map(shared.year), b.top)
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

def write_buildings(b):
    b = b.sort_values("year").reset_index(drop=True)
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
    names = {int(i): {"name": r["name"], "url": r.url} for i, r in named.iterrows()}
    (OUT / "names.json").write_text(json.dumps(names))
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
    apply_sites(b)
    b["year"] = b.year.clip(FIRST_YEAR, LAST_YEAR).astype(int)
    b["tier"] = b.tier.astype(int)
    log(b.groupby("tier").year.describe()[["count", "min", "50%", "max"]].to_string())
    log((b.year // 10 * 10).value_counts().sort_index().to_string())
    write_buildings(b)
    write_tables()
