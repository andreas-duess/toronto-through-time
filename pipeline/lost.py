"""Buildings that are gone: the outlines read off Goad's fire insurance plans (pipeline/plans.py),
minus the ones that still stand. Writes web/public/data/lost.*.

The plans are first moved onto today's street grid, square by square (see register()).
Each plan's outlines are drawn from that plan's year until the next plan's. The same building is
read a little differently on every plan (row houses joined or split, plates a few metres off),
so outlines are not matched one to one. Instead, each outline is cut where the plan before and the
plan after have building and where they do not. Ground built on in two plans running is taken as
built on throughout: there the map swaps one plan's outlines for the next at the later plan's
year, without the building coming down. The parts of an outline that stand today are cut away. What is known and what is estimated:
  outline   from the plan
  material  brick or wood, from the plan's colour
  built     an outline on ground the plan before leaves empty went up between the two plans; the
            year in that gap is picked at random. On the earliest plan that covers the place,
            the year lies between that of the nearest street and the plan, spread the way the
            city's population grew over those years: an estimate.
  gone      an outline on ground the next plan leaves empty came down between the two plans;
            again a random year in the gap. After the latest plan: the year before the
            building that stands there today went up; if nothing stands there, the typical
            year its lost neighbours within NEAR_M went: an estimate.
  height    not read from the plans. HEIGHTS by material: an assumption.

Today's buildings whose own year is only an estimate, but which sit on built ground on the plans,
are taken as standing since the first of those plans; build.py picks that up from
data/interim/plan_years.csv, so run build.py again after the first run of this.

Run after plans.py, build.py and streets.py: uv run --with rasterio pipeline/lost.py
"""
import csv
import json
import pathlib

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio.features

import water
import shapely
from affine import Affine
from scipy.signal import fftconvolve
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLANS = ROOT / "data" / "interim" / "plans"
OUT = ROOT / "web" / "public" / "data"
UTM = 26917

BUILT_ON = 0.6    # share of one of today's buildings that a plan must show as building
SLACK_M = 1.5     # outlines of two plans within this of each other are the same wall
SLIVER_M = 1.2    # pieces thinner than twice this are slivers
MIN_M2 = 15
CELL_M, REACH_M = 300, 45   # squares the plans are fitted in, and how far they may be moved
ROAD_HALF_M = 6   # half the width of a street that buildings are kept off
COVERED_M = 60    # a plan covers a place if it shows a building this near
ESTIMATE = 5      # build.py's tier for a year that is only an estimate
LOW_M = 15        # a taller undated building is not taken for the one on the plans
ISLAND_MAX_M2 = 2500
NEAR_M = 200
HEIGHTS = {"wood": 6.5, "brick": 10.0}  # metres; about two and three storeys


def log(*a):
    print(*a, flush=True)


def scatter(n, salt):
    """The same pseudo-random numbers in [0, 1) on every run."""
    return ((np.arange(n, dtype=np.uint64) * 2654435761 + salt * 40503) % 10007) / 10007


def todays_buildings():
    meta = json.loads((OUT / "meta.json").read_text())
    pos = np.frombuffer((OUT / "positions.bin").read_bytes(), "<f4").reshape(-1, 3)
    starts = np.frombuffer((OUT / "starts.bin").read_bytes(), "<u4")
    years = np.frombuffer((OUT / "years.bin").read_bytes(), "<u2")
    tiers = np.frombuffer((OUT / "tiers.bin").read_bytes(), "u1")
    counts = np.diff(starts)
    ok = counts >= 4  # a few outlines are empty
    xy = (pos[:, :2].astype(float) + meta["origin"])[np.repeat(ok, counts)]
    rings = shapely.linearrings(xy, indices=np.repeat(np.arange(ok.sum()), counts[ok]))
    heights = np.frombuffer((OUT / "heights.bin").read_bytes(), "<f4")
    g = gpd.GeoDataFrame({"year": years[ok], "estimate": (tiers[ok] == ESTIMATE) & (heights[ok] <= LOW_M)},
                         geometry=shapely.polygons(rings), crs=4326).to_crs(UTM)
    g["geometry"] = shapely.make_valid(g.geometry.values)
    return g, tuple(meta["origin"])


def register(geoms, streets):
    """Shift a plan's outlines onto today's street grid. The plates sit up to some tens of metres
    off, by a different amount from place to place. In each square of CELL_M the outlines are
    moved (by up to REACH_M each way) to where the least of them lies on a street; squares with
    few buildings take the typical shift of their neighbours."""
    cen = np.c_[shapely.get_x(shapely.centroid(geoms)), shapely.get_y(shapely.centroid(geoms))]
    x0, y0 = cen.min(0)
    cell = np.floor((cen - [x0, y0]) / CELL_M).astype(int)
    shape = cell.max(0) + 1
    shifts = np.full((*shape, 2), np.nan)
    size = CELL_M + 2 * REACH_M
    for cx, cy in np.unique(cell, axis=0):
        here = np.flatnonzero((cell[:, 0] == cx) & (cell[:, 1] == cy))
        if len(here) < 25:
            continue
        left, top = x0 + cx * CELL_M - REACH_M, y0 + (cy + 1) * CELL_M + REACH_M
        transform = Affine(1, 0, left, 0, -1, top)
        window = shapely.box(left, top - size, left + size, top)
        roads = streets[shapely.intersects(streets, window)]
        if not len(roads):
            continue
        built = rasterio.features.rasterize(geoms[here], out_shape=(size, size), transform=transform).astype(np.float32)
        road = rasterio.features.rasterize(roads, out_shape=(size, size), transform=transform).astype(np.float32)
        # on_road[dy, dx]: building area on a street after moving the buildings by (dx, dy) pixels
        on_road = fftconvolve(road, built[::-1, ::-1], mode="same")
        c = size // 2
        near = on_road[c - REACH_M:c + REACH_M + 1, c - REACH_M:c + REACH_M + 1]
        dy, dx = np.unravel_index(near.argmin(), near.shape)
        shifts[cx, cy] = [dx - REACH_M, -(dy - REACH_M)]  # pixel rows run south
    # a square's shift is the median of itself and its neighbours: steadier, and fills the gaps
    smooth = np.full_like(shifts, np.nan)
    for cx in range(shape[0]):
        for cy in range(shape[1]):
            block = shifts[max(cx - 1, 0):cx + 2, max(cy - 1, 0):cy + 2].reshape(-1, 2)
            block = block[~np.isnan(block[:, 0])]
            if len(block):
                smooth[cx, cy] = np.median(block, axis=0)
    move = np.nan_to_num(smooth[cell[:, 0], cell[:, 1]])
    return shapely.transform(geoms, lambda xy: xy + np.repeat(move, shapely.get_num_coordinates(geoms), axis=0)), move


def covered(geoms, others, weight=None):
    """Share of each geometry's area lying on the other geometries (which do not overlap much)."""
    gi, oi = shapely.STRtree(others).query(geoms, predicate="intersects")
    inter = shapely.area(shapely.intersection(geoms[gi], others[oi]))
    if weight is not None:
        inter = inter * weight[oi]
    return np.bincount(gi, weights=inter, minlength=len(geoms)) / shapely.area(geoms)


def solid(geoms):
    """Geometries without their slivers: what survives shrinking and regrowing by SLIVER_M and
    is at least MIN_M2. Empty where nothing does."""
    opened = shapely.buffer(shapely.buffer(geoms, -SLIVER_M), SLIVER_M)
    parts, index = shapely.get_parts(opened, return_index=True)
    ok = shapely.area(parts) >= MIN_M2
    out = np.full(len(geoms), shapely.Polygon(), object)
    for i in np.unique(index[ok]):
        out[i] = shapely.union_all(parts[ok & (index == i)])
    return out


def within(geoms, others):
    """Each geometry's part lying on the other geometries (grown by SLACK_M), and the rest."""
    gi, oi = shapely.STRtree(others).query(geoms, predicate="intersects")
    order = np.argsort(gi, kind="stable")
    gi, oi = gi[order], oi[order]
    at = np.searchsorted(gi, np.arange(len(geoms) + 1))
    inside = np.full(len(geoms), shapely.Polygon(), object)
    for i in np.flatnonzero(np.diff(at)):
        inside[i] = shapely.union_all(others[oi[at[i]:at[i + 1]]]).buffer(SLACK_M)
    inside = shapely.intersection(geoms, inside)
    return inside, shapely.difference(geoms, inside)


def cut(geoms, others):
    """Each geometry cut in two: the part the other plan also shows as building, and the rest.
    A part that is only a sliver goes to the other part."""
    inside, outside = within(geoms, others)
    a, b = solid(inside), solid(outside)
    whole_in = shapely.is_empty(b) & (shapely.area(inside) >= shapely.area(outside))
    whole_out = shapely.is_empty(a) | (shapely.is_empty(b) & ~whole_in)
    a = np.where(whole_in, geoms, np.where(whole_out, shapely.Polygon(), a))
    b = np.where(whole_out, geoms, np.where(whole_in, shapely.Polygon(), b))
    return a, b


def explode(geoms, *columns):
    """The polygons the geometries are made of, with each column's value repeated for them."""
    parts, index = shapely.get_parts(geoms, return_index=True)
    ok = ~shapely.is_empty(parts) & (shapely.get_type_id(parts) == 3)
    return (parts[ok], *(np.asarray(c)[index[ok]] for c in columns))


def street_years(geoms):
    """Year of the street nearest each building."""
    s = gpd.read_file(OUT / "streets.json").to_crs(UTM)
    s = s[s.kind > 0]
    return s.y.values[s.sindex.nearest(shapely.centroid(geoms), return_all=False)[1]]


def population_year(low, high, salt):
    """A year between low and high for each building, more of them where the city grew faster."""
    pop = np.array([(1793, 0)] + [(int(r["year"]), int(r["population"])) for r in
                                  csv.DictReader((ROOT / "data" / "manual" / "population.csv").open())], float)
    people = np.interp(low, pop[:, 0], pop[:, 1])
    people += scatter(len(low), salt) * (np.interp(high, pop[:, 0], pop[:, 1]) - people)
    return np.minimum(np.interp(people, pop[:, 1], pop[:, 0]), high - 1)


if __name__ == "__main__":
    plans = {int(p.stem): gpd.read_file(p).assign(island=False) for p in sorted(PLANS.glob("[0-9][0-9][0-9][0-9].gpkg"))}
    for p in sorted(PLANS.glob("*_*.gpkg")):  # places outside the district: the Island, Trinity College
        year = int(p.stem[:4])
        plans[year] = pd.concat([plans[year], gpd.read_file(p).assign(island=True)], ignore_index=True)
    years = sorted(plans)
    roads = gpd.read_file(OUT / "streets.json").to_crs(UTM)
    # the later water maps leave out the open harbour, so also: nothing further than 120 m from a street
    near_street = shapely.union_all(shapely.buffer(roads[roads.kind > 0].geometry.values, 120, quad_segs=2))
    shapely.prepare(near_street)
    roads = shapely.buffer(roads[roads.kind > 0].geometry.values, ROAD_HALF_M, cap_style="flat")
    # The plans tint and hatch the harbour, and the reading takes specks of that for buildings.
    # Nothing is kept that lies in the water of its year (pipeline/water.py), 15 m or more out.
    frames = water.frames()[0]
    geoms = []
    for y in years:
        wet = frames[max(f for f in frames if f <= y)].buffer(-15)
        cen = shapely.centroid(plans[y].geometry.values)
        # (not for the places read separately: the Island has no streets in the city's file, and
        # Trinity College stood back from them)
        keep = ~shapely.contains(wet, cen) & (shapely.contains(near_street, cen) | plans[y].island.values)
        # On the Island plates: only what stands on the Island's land of that plan, and nothing
        # bigger than a hotel. The plates lie on the index map, whose coloured strips and red
        # lines across the harbour would otherwise be read as buildings.
        shore = ROOT / "data" / "interim" / "island" / f"{y}.geojson"
        if shore.exists():
            land = gpd.read_file(shore).geometry.iloc[0].buffer(-4)
            box = gpd.GeoSeries([shapely.box(-79.405, 43.609, -79.348, 43.636)], crs=4326).to_crs(UTM).iloc[0]
            on_plate = plans[y].island.values & shapely.contains(box, cen)
            # ... and nothing long and thin: the plates' red survey lines
            rect = shapely.minimum_rotated_rectangle(plans[y].geometry.values)
            sides = shapely.get_coordinates(shapely.get_exterior_ring(rect)).reshape(-1, 5, 2)
            a, b = np.hypot(*(sides[:, 1] - sides[:, 0]).T), np.hypot(*(sides[:, 2] - sides[:, 1]).T)
            thin = np.maximum(a, b) > 5 * np.maximum(np.minimum(a, b), 1)
            keep &= ~on_plate | (shapely.contains(land, cen) & (plans[y].geometry.area.values <= ISLAND_MAX_M2) & ~thin)
        dry = plans[y][keep].reset_index(drop=True)
        # and no small outline standing alone: specks of plan lettering and lines, not sheds
        cen = np.c_[dry.geometry.centroid.x, dry.geometry.centroid.y]
        area = dry.geometry.area.values
        around = cKDTree(cen).query_ball_point(cen, 40)
        alone = np.array([area[a].sum() - area[i] < 250 for i, a in enumerate(around)]) & (area < 120)
        dry = dry[~alone].reset_index(drop=True)
        log(f"  {y}: {len(plans[y]) - len(dry):,} outlines in the water or small and alone dropped")
        plans[y] = dry
        g, move = register(shapely.make_valid(plans[y].geometry.values), roads)
        geoms.append(shapely.make_valid(g))
        log(f"  {y} plan moved onto the street grid: typically {np.median(np.hypot(*move.T)):.0f} m,",
            f"at most {np.hypot(*move.T).max():.0f} m")
    centres = [np.c_[shapely.get_x(shapely.centroid(g)), shapely.get_y(shapely.centroid(g))] for g in geoms]
    trees = [cKDTree(c) for c in centres]
    today, origin = todays_buildings()
    tgeom = today.geometry.values

    # today's undated buildings on built ground of the plans: standing since the first plan of
    # an unbroken run up to the latest one
    since = np.full(len(today), -1)
    undated = today.estimate.values & (today.year.values <= 1960)
    for k in range(len(years) - 1, -1, -1):
        on_plan = covered(tgeom, geoms[k]) >= BUILT_ON
        run = undated & on_plan & ((since == k + 1) | (k == len(years) - 1))
        since[run] = k
    log(f"today's undated buildings found on the plans: {(since >= 0).sum():,}")

    rows = []
    for k, year in enumerate(years):
        # what is left of each outline once the buildings that stand today are taken out
        older = (today.year.values <= year + 3) | ((since >= 0) & (since <= k))
        g = solid(shapely.difference(geoms[k], within(geoms[k], tgeom[older])[0]))
        g, wood = explode(g, plans[year].wood.values > 0.5)
        n_outlines, n = len(geoms[k]), len(g)
        cen = np.c_[shapely.get_x(shapely.centroid(g)), shapely.get_y(shapely.centroid(g))]
        # the plans before and after that cover each outline's place
        prev = np.full(n, -1)
        for j in range(k):
            prev[trees[j].query(cen, distance_upper_bound=COVERED_M)[0] < np.inf] = j
        nxt = np.full(n, -1)
        for j in range(len(years) - 1, k, -1):
            nxt[trees[j].query(cen, distance_upper_bound=COVERED_M)[0] < np.inf] = j

        # cut each outline into ground built on before or not, and ground still built on after or not
        pieces = []
        for j in np.unique(prev):
            sel = np.flatnonzero(prev == j)
            if j < 0:
                pieces.append((g[sel], wood[sel], np.full(len(sel), -1), np.zeros(len(sel), bool), nxt[sel]))
                continue
            for part, was in zip(cut(g[sel], geoms[j]), (True, False)):
                part, w, x = explode(part, wood[sel], nxt[sel])
                pieces.append((part, w, np.full(len(part), j), np.full(len(part), was), x))
        g, wood, prev, kept, nxt = (np.concatenate([p[i] for p in pieces]) for i in range(5))
        pieces = []
        for j in np.unique(nxt):
            sel = np.flatnonzero(nxt == j)
            if j < 0:
                pieces.append((g[sel], wood[sel], prev[sel], kept[sel], np.full(len(sel), -1), np.zeros(len(sel), bool)))
                continue
            for part, still in zip(cut(g[sel], geoms[j]), (True, False)):
                part, w, x, kp = explode(part, wood[sel], prev[sel], kept[sel])
                pieces.append((part, w, x, kp, np.full(len(part), j), np.full(len(part), still)))
        g, wood, prev, kept, nxt, stays = (np.concatenate([p[i] for p in pieces]) for i in range(6))
        n = len(g)

        ys = np.array(years)
        first, last = prev < 0, nxt < 0
        built = np.empty(n)
        built[first] = population_year(np.clip(street_years(g[first]), 1793, year - 1), year, 10 + k)
        gap = ys[np.maximum(prev, 0)]
        built[~first] = np.where(kept, year, gap + 1 + scatter(n, 20 + k) * (year - gap - 1))[~first]
        gap = ys[np.maximum(nxt, 0)]
        gone = np.where(last, np.nan, np.where(stays, gap, year + 1 + scatter(n, 30 + k) * (gap - year - 1)))
        # after the latest plan: the year before the building that stands there today went up
        gi, ti = shapely.STRtree(tgeom).query(g, predicate="intersects")
        big = shapely.area(shapely.intersection(g[gi], tgeom[ti])) >= 0.3 * shapely.area(g[gi])
        successor = np.full(n, 9999)
        np.minimum.at(successor, gi[big], today.year.values[ti[big]])
        replaced = last & (successor < 9999) & (successor > year)
        gone[replaced] = successor[replaced] - 1

        rows.append(gpd.GeoDataFrame({
            "plan": k, "built": built, "gone": gone, "kept": kept, "stays": stays,
            "wood": wood, "guess": first | (last & ~replaced),
        }, geometry=g, crs=UTM))
        log(f"  {year}: {n_outlines:,} outlines; {n:,} pieces not standing today,",
            f"{shapely.area(g).sum() / 1e4:.0f} ha; on ground built on before {shapely.area(g[kept]).sum() / 1e4:.0f} ha;",
            f"still built on in the next plan {shapely.area(g[stays]).sum() / 1e4:.0f} ha")
    lost = pd.concat(rows, ignore_index=True)
    lost["height"] = np.where(lost.wood, HEIGHTS["wood"], HEIGHTS["brick"])

    # data/manual/lost_zones.csv: places where written sources say when the buildings went up and
    # came down (the Island, the old Trinity College). The plans give the outlines; a building
    # that the earliest plan already shows, or the latest still shows, gets a year in the zone's
    # range, and the zone's name and height if it has them.
    lost["name"] = -1
    zone_names = []
    cen = lost.geometry.centroid.to_crs(4326)
    drop = np.zeros(len(lost), bool)
    made = json.loads((OUT / "landmarks.json").read_text())
    models = {}
    if "trinityCollege" in made:
        t = made["trinityCollege"]
        east = 111320 * np.cos(np.radians(t["origin"][1]))
        ring = [(t["origin"][0] + x / east, t["origin"][1] + y / 111132) for x, y in t["outline"]]
        models["trinity_college"] = gpd.GeoSeries([shapely.Polygon(ring)], crs=4326).to_crs(UTM).iloc[0].buffer(8)
    for r in csv.DictReader((ROOT / "data" / "manual" / "lost_zones.csv").open()):
        inside = ((cen.x >= float(r["lon_min"])) & (cen.x < float(r["lon_max"]))
                  & (cen.y >= float(r["lat_min"])) & (cen.y < float(r["lat_max"]))).values
        if not r["gone_from"]:
            drop |= inside
            continue
        if r["zone"] in models:
            # The web map builds this one by hand, so nothing from the plans is drawn in the zone.
            # (Here the plates overlap an inset at another scale, which reads as stray blocks.)
            drop |= inside
            continue
        early = inside & lost.guess.values & (lost.plan.values < len(years) - 1) & ~lost.kept.values
        lost.loc[early, "built"] = float(r["built_from"]) + scatter(early.sum(), 41) * (float(r["built_to"]) - float(r["built_from"]))
        late = inside & (lost.plan.values == len(years) - 1)
        lost.loc[late, "gone"] = float(r["gone_from"]) + scatter(late.sum(), 42) * (float(r["gone_to"]) - float(r["gone_from"]) + 1)
        lost.loc[inside, "guess"] = True
        if r["name"]:
            lost.loc[inside, "name"] = len(zone_names)
            zone_names.append({"name": r["name"], "url": r["url"]})
        if r["height"]:
            lost.loc[inside, "height"] = float(r["height"])
        log(f"  {r['zone']}: {inside.sum():,} pieces")
    lost = lost[~drop].reset_index(drop=True)

    # for build.py: the year by which today's undated buildings were standing
    found = np.flatnonzero(since >= 0)
    before = np.array(years)[np.maximum(since[found] - 1, 0)]
    by = np.where(since[found] == 0, years[0],
                  before + 1 + scatter(len(found), 5) * (np.array(years)[since[found]] - before - 1))
    cen = today.geometry.centroid.to_crs(4326)
    with open(ROOT / "data" / "interim" / "plan_years.csv", "w") as f:
        f.write("lon,lat,year\n")
        for t, y in zip(found, by):
            f.write(f"{cen.iloc[t].x:.6f},{cen.iloc[t].y:.6f},{int(y)}\n")

    # no next plan and no successor: the typical year the lost neighbours with a successor went
    unknown = lost.gone.isna().values
    xy = np.c_[lost.geometry.centroid.x, lost.geometry.centroid.y]
    known = np.flatnonzero((lost.plan.values == len(years) - 1) & ~unknown)
    around = cKDTree(xy[known]).query_ball_point(xy[unknown], NEAR_M)
    overall = np.median(lost.gone.values[known])
    lost.loc[unknown, "gone"] = [np.median(lost.gone.values[known[a]]) if len(a) >= 3 else overall for a in around]
    lost["built"] = np.round(lost.built)
    lost["gone"] = np.maximum(np.round(lost.gone), lost.built + 1)
    n = len(lost)
    log(f"lost outlines: {n:,}; end estimated from neighbours {unknown.sum():,}")

    lost = lost.sort_values("built", kind="stable").reset_index(drop=True)
    geom = shapely.simplify(lost.geometry.values, 0.8)
    geom = gpd.GeoSeries(geom, crs=UTM).to_crs(4326).values
    rings = shapely.get_exterior_ring(shapely.orient_polygons(geom))
    coords, ring_of = shapely.get_coordinates(rings, return_index=True)
    counts = np.bincount(ring_of, minlength=n)
    pos = (coords - origin).astype("<f4")
    files = {
        "lost.positions.bin": pos,
        "lost.starts.bin": np.concatenate([[0], np.cumsum(counts)]).astype("<u4"),
        # first year, last year, 1 if it does not rise, 1 if it does not come down
        "lost.years.bin": np.c_[lost.built, lost.gone, lost.kept, lost.stays].astype("<u2"),
        "lost.heights.bin": lost.height.to_numpy("<f4"),
        # material (0 wood, 1 brick), plan, 1 if a year is an estimate
        "lost.info.bin": np.c_[~lost.wood, lost.plan, lost.guess].astype("u1"),
    }
    for name, arr in files.items():
        (OUT / name).write_bytes(arr.tobytes())
    named = {int(i): zone_names[k] for i, k in lost.name[lost.name >= 0].items()}
    (OUT / "lost.json").write_text(json.dumps({"count": n, "plans": years, "kinds": list(HEIGHTS), "names": named}))
    log(f"wrote {n:,} outlines; {sum(a.nbytes for a in files.values()) / 1e6:.1f} MB")
    for y in (1870, 1885, 1900, 1920, 1950, 1980, 2020):
        log(f"  standing in {y}: {((lost.built <= y) & (lost.gone > y)).sum():,}")
