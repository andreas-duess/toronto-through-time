"""Build the historic water of Toronto harbour for the web map: web/public/data/water.json.

The base map shows today's land. For each mapped year this writes the area that was water then,
so the web map can paint it over land that has been filled in since.

Sources (University of Toronto Map & Data Library, digitised from georeferenced historic maps):
  - Historical Hydrography of Toronto: 1834, 1851 (whole harbour), 1857, 1872, 1878 (downtown shore only)
  - Don Valley Historical Mapping Project: 1891, 1894, 1909, 1918, 1931 (harbour and Ashbridge's Bay;
    the Island is not drawn in these)
  - Goad's fire insurance plans of 1913 and 1924, for the Island (pipeline/island.py; run it first)
  - today's buildings (pipeline/build.py; run it first): each stands on land by its year

Run: uv run pipeline/water.py
"""
import json
import pathlib
import urllib.request
import zipfile

import geopandas as gpd
import numpy as np
import shapely
from shapely.affinity import translate
from shapely.geometry import Polygon, box

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "web" / "public" / "data"
UTM = 26917

HYDRO = "https://maps.library.utoronto.ca/datapub/toronto/historicalhydro/"
DVHMP = "https://maps.library.utoronto.ca/dvhmp/data/2009_05_10/river_shoreline_polygons/"
# year -> (folder, shapefile name, download url, name of the source map)
LAYERS = {
    1834: ("histhydro/1834", "1834.shp", HYDRO + "1834.zip", "Chewett 1834"),
    1851: ("histhydro/1851", "1851.shp", HYDRO + "1851.zip", "Browne 1851"),
    1857: ("histhydro/1857", "1857.shp", HYDRO + "1857.zip", "Waterlow 1857"),
    1872: ("histhydro/1872", "1872.shp", HYDRO + "1872.zip", "Wadsworth & Unwin 1872"),
    1878: ("histhydro/1878", "1878_Cotterell.shp", HYDRO + "1878.zip", "Cotterell 1878"),
    1891: ("dvhmp/G_3501_C5_1891_22g", "G_3501_C5_1891_22g.shp", DVHMP + "G_3501_C5_1891_22g.zip", "1891 map"),
    1894: ("dvhmp/NMC97370", "NMC97370.shp", DVHMP + "NMC97370.zip", "1894 map"),
    1909: ("dvhmp/NTS_1909", "NTS_1909.shp", DVHMP + "NTS_1909.zip", "1909 topographic map"),
    1918: ("dvhmp/NTS_1918", "NTS_1918.shp", DVHMP + "NTS_1918.zip", "1918 topographic map"),
    1931: ("dvhmp/NTS_1931", "NTS_1931.shp", DVHMP + "NTS_1931.zip", "1931 topographic map"),
}
# maps that only cover the downtown shore; they replace that stretch of the frame before them
PARTIAL = {1857, 1872, 1878}

# Hand-drawn helper shapes, lon/lat. None of them is a historic outline.
# The Island and the west end of the peninsula. The Don Valley layers draw no Island, so inside this
# shape the 1891 to 1909 frames keep the 1851 outline; from 1913 the Island is read off Goad's plans.
ISLAND_ZONE = [(-79.418, 43.596), (-79.418, 43.627), (-79.400, 43.6335), (-79.343, 43.6335), (-79.343, 43.596)]
# The storm of 1858 cut the peninsula here and made it an island. Position is approximate.
EASTERN_GAP = [(-79.3500, 43.6285), (-79.3440, 43.6285), (-79.3440, 43.6335), (-79.3500, 43.6335)]
GAP_YEAR = 1858
# Joins the Island zone to the bar along the marsh, so the 1834 peninsula is unbroken.
NECK = [(-79.352, 43.6335), (-79.338, 43.6335), (-79.338, 43.641), (-79.352, 43.641)]
# East of this the 1918 and 1931 maps are used inside the Island zone too (open water, where the
# Leslie Street Spit is today).
ISLAND_EAST = -79.351
# Open lake, well clear of every historic shore. The source maps stop at arbitrary lines in the lake;
# this keeps modern landfill beyond those lines (the Leslie Street Spit) under water.
OPEN_LAKE = [(-79.60, 43.50), (-79.60, 43.585), (-79.43, 43.603), (-79.39, 43.6055), (-79.36, 43.611),
             (-79.34, 43.620), (-79.30, 43.638), (-79.24, 43.655), (-79.24, 43.50)]
# The last mapped shore (1931) gives way to today's between these years.
MODERN_FADE = [1954, 1956]
# The 1834 marsh at Ashbridge's Bay stays until the 1891 map takes over, which draws the bay as water.
MARSH_FADE = [1883, 1891]
# The harbour, the Port Lands and the lower Don, where every mapped year draws the water. Inside
# this shape, the Island zone and the bar, the web map hides today's water (the ship channel, the
# straightened Don, the slips) and shows only the water of the year, until today's shore takes over.
HARBOUR = [(-79.405, 43.6335), (-79.405, 43.648), (-79.368, 43.655), (-79.368, 43.672), (-79.348, 43.672),
           (-79.348, 43.662), (-79.31, 43.668), (-79.31, 43.60), (-79.343, 43.60), (-79.343, 43.6335)]

ISLAND = ROOT / "data" / "interim" / "island"
ISLAND_YEARS = (1913, 1924)
# frames that are not one map: name shown by the web map
COMBINED = {GAP_YEAR: f"{LAYERS[1857][3]}, with the {GAP_YEAR} breach added by hand",
            1913: "1909 topographic map, Island from Goad's plan of 1913",
            1924: "1918 topographic map, Island from Goad's plan of 1924"}
ISLAND_FROM = {1918: "Goad's plan of 1913", 1931: "Goad's plan of 1924"}

SIMPLIFY_M = 1.5
GROUND_M = 12     # ground kept around a standing building on the Island


def log(*a):
    print(*a, flush=True)


def to_utm(lonlat):
    return gpd.GeoSeries([Polygon(lonlat)], crs=4326).to_crs(UTM).iloc[0]


def read(year):
    folder, shp, url, _ = LAYERS[year]
    path = RAW / folder / shp
    if not path.exists():
        archive = RAW / (folder + ".zip")
        archive.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "toronto-through-time"})
        archive.write_bytes(urllib.request.urlopen(req).read())
        with zipfile.ZipFile(archive) as z:
            z.extractall(RAW / folder)
    g = gpd.read_file(path).to_crs(UTM)
    g["geometry"] = shapely.make_valid(g.geometry.values)
    return g


def area_of(g):
    return shapely.union_all(g.geometry.values)


def polygons_only(geom):
    parts = [p for p in shapely.get_parts(geom) if p.geom_type == "Polygon" and p.area > 20]
    return shapely.union_all(parts) if parts else Polygon()


def standing(zone):
    """Today's buildings inside the zone with a little ground around each, and their years (from
    pipeline/build.py, if it has run). A building that stands in a year stands on land, also
    where the old map's outline misses it or lies a few metres off."""
    try:
        origin = json.loads((OUT / "meta.json").read_text())["origin"]
        pos = np.fromfile(OUT / "positions.bin", "<f4").reshape(-1, 3)[:, :2].astype(float) + origin
        starts = np.fromfile(OUT / "starts.bin", "<u4")
        years = np.fromfile(OUT / "years.bin", "<u2")
    except FileNotFoundError:
        return np.array([], object), np.array([], int)
    first = gpd.GeoSeries(gpd.points_from_xy(*pos[starts[:-1]].T), crs=4326).to_crs(UTM)
    shapely.prepare(zone)
    inside = np.flatnonzero(shapely.contains(zone, first.values))
    outlines = [Polygon(pos[starts[i]:starts[i + 1]]) for i in inside]
    ground = gpd.GeoSeries(outlines, crs=4326).to_crs(UTM).buffer(0).buffer(GROUND_M)
    return ground.values, years[inside]


def frames(pads=True):
    """The water of each mapped year (UTM), the 1834 marsh, and the area in which the web map
    hides today's water. With pads, today's buildings stand on land from the frame before their
    year (build.py asks for the frames without, to hold estimated years back until the land is
    there)."""
    zone, gap, lake = to_utm(ISLAND_ZONE), to_utm(EASTERN_GAP), to_utm(OPEN_LAKE)
    out = {}
    g = read(1834)
    marsh = area_of(g[g["type"] == "marsh"])
    out[1834] = area_of(g[g["type"] == "water"])
    out[1851] = area_of(read(1851))
    prev = out[1851]
    for year in (1857, 1872, 1878):
        part = area_of(read(year))
        # the stretch this map covers: its water along the shore and everything inland of it
        minx, miny, maxx, maxy = part.bounds
        shore = part.intersection(box(minx, miny, maxx, to_utm([(-79.4, 43.653), (-79.3, 43.653), (-79.3, 43.6)]).bounds[3]))
        covered = shapely.union_all([shore, translate(shore, 0, 4000)]).convex_hull
        # the sheets taper off at their ends; stay clear of them
        covered = covered.intersection(box(minx + 150, miny, maxx - 600, maxy + 4000))
        prev = prev.difference(covered).union(part.intersection(covered))
        out[year] = prev
        if year == 1857:
            prev = prev.union(gap)
            out[GAP_YEAR] = prev
    island_1858 = out[GAP_YEAR].intersection(zone)
    west = to_utm([(ISLAND_EAST, 43.5), (ISLAND_EAST, 43.7), (-79.6, 43.7), (-79.6, 43.5)])
    # The Island from 1913 on: its land as read off Goad's plans (pipeline/island.py). The frames
    # of 1913 and 1924 are the harbour of the map before with the Island of that year.
    island = {y: gpd.read_file(ISLAND / f"{y}.geojson").geometry.iloc[0] for y in ISLAND_YEARS
              if (ISLAND / f"{y}.geojson").exists()}
    zone_west = zone.intersection(west)
    for year, harbour in ((1891, 1891), (1894, 1894), (1909, 1909), (1913, 1909), (1918, 1918), (1924, 1918), (1931, 1931)):
        f = area_of(read(harbour))
        drawn = max((y for y in island if y <= year), default=None)
        if drawn is None:
            out[year] = f.difference(zone).union(island_1858) if year <= 1909 else f.difference(zone_west)
        else:
            out[year] = f.difference(zone_west).union(zone_west.difference(island[drawn]))
    if pads:
        built, built_year = standing(shapely.union_all(list(out.values())))
        steps = sorted(out)
        for year, nxt in zip(steps, steps[1:] + [MODERN_FADE[1]]):
            out[year] = out[year].difference(shapely.union_all(built[built_year < nxt]))
    # the half-metre in and out removes slivers left along the helper shapes
    out = {y: polygons_only(f.union(lake).buffer(-0.5).buffer(0.5)) for y, f in sorted(out.items())}
    # Where the old maps show land that is water today (the peninsula and the bar along the marsh),
    # the web map paints land first and the water of the year on top. Two areas: the Island zone, and
    # the marsh with a strip on its lake side for the bar.
    closed = marsh.buffer(300).buffer(-300)
    lake_side = marsh.buffer(350).intersection(translate(marsh.convex_hull, 250, -450))
    bar = shapely.union_all([to_utm(NECK), closed, lake_side])
    return out, polygons_only(marsh), polygons_only(shapely.union_all([zone, bar, to_utm(HARBOUR)]))


def to_lonlat(geom):
    """A (multi)polygon in UTM as a GeoJSON geometry in lon/lat, simplified."""
    geom = polygons_only(shapely.simplify(geom, SIMPLIFY_M))
    geom = gpd.GeoSeries([geom], crs=UTM).to_crs(4326).iloc[0]
    return json.loads(shapely.to_geojson(shapely.set_precision(geom, 1e-6)))


if __name__ == "__main__":
    water, marsh, land = frames()
    years = list(water)
    steps = []
    for i, year in enumerate(years):
        cur = water[year]
        nxt = water[years[i + 1]] if i + 1 < len(years) else Polygon()
        # lost and gained overlap the common part by a metre so no seam shows between them
        steps.append({
            "year": year,
            "source": COMBINED.get(year) or LAYERS[year][3] + (f", Island from {ISLAND_FROM[year]}" if year in ISLAND_FROM else ""),
            "common": to_lonlat(cur.intersection(nxt)),
            "lost": to_lonlat(cur.difference(nxt).buffer(-0.5).buffer(1.5)),
            "gained": to_lonlat(nxt.difference(cur).buffer(-0.5).buffer(1.5)),
        })
        log(year, f"water {cur.area / 1e6:.1f} km2, lost to next {cur.difference(nxt).area / 1e4:.0f} ha,"
                  f" gained {nxt.difference(cur).area / 1e4:.0f} ha")
    data = {"steps": steps, "modernFade": MODERN_FADE, "marsh": to_lonlat(marsh), "marshFade": MARSH_FADE,
            "land": to_lonlat(land)}
    (OUT / "water.json").write_text(json.dumps(data, separators=(",", ":")))
    log("wrote water.json", f"{(OUT / 'water.json').stat().st_size / 1e3:.0f} kB")
