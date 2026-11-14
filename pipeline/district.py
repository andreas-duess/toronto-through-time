"""A former municipality outside the old city, for the web page: web/public/data/d/<name>/.

The old city has its whole history on the map. The others (Etobicoke, York, North York, East
York, Scarborough) joined Toronto in 1998 and are drawn from then on at most: there are no fire
insurance plans read for them and few building dates. This writes a district as it stands today:
its buildings with their real shapes (pipeline/shapes.py --area NAME, run first), sloped roofs on
its houses, its streets and its parks.

The page loads a district piece by piece as the view reaches it, so it is cut into square cells
of CELL_M metres, one file each (cell.<n>.bin, gzip), and an index:
  index.json: {name, from (first year shown), origin, cells: [{file, box: [w, s, e, n], buildings}]}
  a cell: four uint32 (buildings, corners, roofs, 0), then for the buildings corner counts,
    heights, bases (dm) and years, all uint16; the corners as pipeline/pack.py packs positions;
    the roofs' middles packed the same way, and their five uint16 each as build.write_roofs has them
  streets.json: lines with kind (as streets.json has it) and name
  parks.json: polygons
  cell.<n>.json: {"a": [street address of each building, "" if none], "n": {building: name}}, fetched
    when a building of the cell is clicked. Addresses are the City's address points; names are
    OpenStreetMap's named buildings (data/raw/osm/named_city.json).
  trees.<n>.bin (gzip): today's trees of a cell, placed as pipeline/trees.py places the old city's:
    a uint32 count, the positions packed as above, a uint8 crown radius (dm) each

Run: uv run --with rasterio --with pyogrio --with scipy pipeline/district.py ETOBICOKE
(with --ground: its streets and parks only, from 1998; with --no-trees: without the trees)
"""
import gzip
import json
import pathlib
import sys

import geopandas as gpd
import numpy as np
import shapely

import build
import pack
import pandas as pd
import streets as streets_

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CELL_M = 2000
TODAY = build.LAST_YEAR


def cell_file(b, roof_of, middle, info):
    """One cell's buildings (rows of b, in order) and roofs as bytes."""
    geom = shapely.simplify(b.geometry.to_crs(4326).values, 2e-6)
    rings = shapely.get_exterior_ring(shapely.orient_polygons(geom))
    coords, ring_of = shapely.get_coordinates(rings, return_index=True)
    counts = np.bincount(ring_of, minlength=len(b))
    assert counts.max() < 65536
    parts = [np.array([len(b), len(coords), len(roof_of), 0], "<u4").tobytes(),
             counts.astype("<u2").tobytes(), pack.decimetres(b.top - b.base).tobytes(), pack.decimetres(b.base).tobytes(),
             b.year.to_numpy("<u2").tobytes(), np.ascontiguousarray(pack.deltas(coords - build.ORIGIN)).tobytes()]
    if len(roof_of):
        packed = np.column_stack([np.round(info[:, :4] * 100), np.round(info[:, 4] / np.pi * 65535)])
        parts += [roof_of.astype("<u4").tobytes(), np.ascontiguousarray(pack.deltas(middle - build.ORIGIN)).tobytes(), packed.astype("<u2").tobytes()]
    return gzip.compress(b"".join(parts), 9, mtime=0)


JOINED = 1998     # the year the six municipalities became one city


def names_and_addresses(b):
    """For each building its street address ("" if none) and its name (None if none)."""
    ap = build.load_address_points()
    pts = gpd.GeoDataFrame(ap[["address"]], geometry=gpd.points_from_xy(ap.lon, ap.lat), crs=4326).to_crs(build.UTM)
    address = gpd.sjoin(pts, b[["geometry"]], predicate="within").groupby("index_right").address.first().reindex(b.index).fillna("")
    named = [e for e in json.loads((RAW / "osm" / "named_city.json").read_text())["elements"] if "bounds" in e]
    centre = gpd.GeoDataFrame({"name": [e["tags"]["name"] for e in named]}, crs=4326, geometry=gpd.points_from_xy(
        [(e["bounds"]["minlon"] + e["bounds"]["maxlon"]) / 2 for e in named], [(e["bounds"]["minlat"] + e["bounds"]["maxlat"]) / 2 for e in named])).to_crs(build.UTM)
    name = gpd.sjoin(centre, b[["geometry"]], predicate="within").groupby("index_right").name.first().reindex(b.index)
    # the other outlines of the same building: inside the named one's box (not boxes over 1.5 ha), or at its address
    boxes = gpd.GeoDataFrame({"name": [e["tags"]["name"] for e in named]}, crs=4326, geometry=[
        shapely.box(e["bounds"]["minlon"], e["bounds"]["minlat"], e["bounds"]["maxlon"], e["bounds"]["maxlat"]) for e in named]).to_crs(build.UTM)
    boxes = boxes[boxes.area <= 15000]
    cen = gpd.GeoDataFrame(geometry=b.geometry.centroid, crs=build.UTM)
    name = name.fillna(gpd.sjoin(cen, boxes, predicate="within").groupby(level=0).name.first().reindex(b.index))
    at = pd.DataFrame({"address": address, "name": name})
    same = at[(at.address != "") & at.name.notna()].groupby("address").name.first()
    return address, name.fillna(address.map(same))


def tree_files(area, b, out):
    """Today's trees, cell by cell. Returns the index entries."""
    import trees
    rng = np.random.default_rng(1)
    grid, transform = trees.canopy(area, b.geometry)
    at, radius = trees.place(grid, rng)
    x, y = transform * (at[:, 1] + 0.5, at[:, 0] + 0.5)
    pts = gpd.GeoSeries(gpd.points_from_xy(x, y), crs=trees.MTM)
    utm = shapely.get_coordinates(pts.to_crs(build.UTM).values)
    lonlat = shapely.get_coordinates(pts.to_crs(4326).values)
    cx, cy = np.floor(utm[:, 0] / CELL_M).astype(int), np.floor(utm[:, 1] / CELL_M).astype(int)
    entries = []
    for n, (cxx, cyy) in enumerate(sorted(set(zip(cx, cy)))):
        rows = np.flatnonzero((cx == cxx) & (cy == cyy))
        rows = rows[np.lexsort([lonlat[rows, 0], np.round(lonlat[rows, 1], 3)])]      # in rows from west to east, so that the file packs small
        data = gzip.compress(np.array([len(rows)], "<u4").tobytes() + np.ascontiguousarray(pack.deltas(lonlat[rows] - build.ORIGIN)).tobytes()
                             + np.round(radius[rows] * 10).astype("u1").tobytes(), 9, mtime=0)
        (out / f"trees.{n}.bin").write_bytes(data)
        w, s, e, nn = lonlat[rows, 0].min(), lonlat[rows, 1].min(), lonlat[rows, 0].max(), lonlat[rows, 1].max()
        entries.append({"file": f"trees.{n}.bin", "box": [round(w, 5), round(s, 5), round(e, 5), round(nn, 5)], "trees": len(rows)})
    return entries, len(at)


if __name__ == "__main__":
    area = sys.argv[1].upper()
    ground_only = "--ground" in sys.argv        # streets and parks only; the buildings come later
    slug = area.lower().replace(" ", "_")
    out = ROOT / "web" / "public" / "data" / "d" / slug
    out.mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("cell.*.bin"), *out.glob("cell.*.json"), *out.glob("trees.*.bin")]:
        old.unlink()
    tree_cells, n_trees = [], 0

    cells, size, n_buildings, n_roofs = [], 0, 0, 0
    if ground_only:
        limits = gpd.read_file(RAW / "former_municipalities.geojson")
        limits = limits[limits.AREA_NAME == area].to_crs(build.UTM).geometry.iloc[0]
    else:
        b, limits = build.load_buildings(area)
        b["year"] = TODAY          # as it stands today; years from 1998 on are a later step
        # An outline in several pieces becomes several outlines. Written as one it has no outer ring,
        # so no corners, and the page then draws every building after it in the cell from the wrong corners.
        b = b.explode(index_parts=False).reset_index(drop=True)
        b = b[(b.geometry.geom_type == "Polygon") & (b.geometry.area >= 8)].reset_index(drop=True)
        b["area"] = b.geometry.area
        corners = shapely.get_num_coordinates(shapely.get_exterior_ring(shapely.simplify(b.geometry.to_crs(4326).values, 2e-6)))
        b = b[corners >= 4].reset_index(drop=True)
        roof_of, middle, info = build.roofs(b)        # lowers the walls of the houses to their eaves
        roof_at = np.full(len(b), -1)
        roof_at[roof_of] = np.arange(len(roof_of))
        n_buildings, n_roofs = len(b), len(roof_of)
        address, name = names_and_addresses(b)
        if "--no-trees" not in sys.argv:
            tree_cells, n_trees = tree_files(area, b, out)

        cen = b.geometry.centroid
        cx, cy = np.floor(cen.x / CELL_M).astype(int), np.floor(cen.y / CELL_M).astype(int)
        for n, (x, y) in enumerate(sorted(set(zip(cx, cy)))):
            rows = np.flatnonzero((cx == x) & (cy == y))
            mine = b.iloc[rows]
            has = roof_at[rows] >= 0
            data = cell_file(mine, np.flatnonzero(has), middle[roof_at[rows][has]], info[roof_at[rows][has]])
            (out / f"cell.{n}.bin").write_bytes(data)
            named = {int(i): v for i, v in enumerate(name.values[rows]) if isinstance(v, str)}
            (out / f"cell.{n}.json").write_text(json.dumps({"a": [a.title() for a in address.values[rows]], "n": named}, separators=(",", ":"), ensure_ascii=False))
            size += len(data)
            w, s_, e, nn = mine.to_crs(4326).total_bounds
            cells.append({"file": f"cell.{n}.bin", "box": [round(w, 5), round(s_, 5), round(e, 5), round(nn, 5)], "buildings": len(mine)})

    # Streets: the City's centreline inside the district, by kind, one line (or several) per street
    # name. They are today's streets, shown from the year the district joined the city: a street
    # laid out since then is on the map too early.
    centre = gpd.read_file(RAW / "centreline.gpkg").to_crs(build.UTM)
    centre = centre[centre.intersects(limits)]
    centre["kind"] = centre.FEATURE_CODE_DESC.map(streets_.KINDS)
    centre = centre[centre.kind.notna()]
    lines = gpd.GeoDataFrame({"kind": centre.kind.astype(int), "name": centre.LINEAR_NAME_FULL.fillna("")},
                             geometry=centre.geometry.intersection(limits).values, crs=build.UTM)
    lines = lines[~lines.geometry.is_empty].dissolve(["name", "kind"]).reset_index()
    lines["geometry"] = shapely.simplify(shapely.line_merge(lines.geometry.values), 2.5)
    lines = lines.to_crs(4326)
    lines["geometry"] = shapely.set_precision(lines.geometry.values, 1e-5)
    (out / "streets.json").write_text(lines[~lines.geometry.is_empty].to_json(drop_id=True))
    parks = gpd.read_file(RAW / "green_spaces.geojson").to_crs(build.UTM)
    parks = parks[parks.intersects(limits)]
    parks = gpd.GeoDataFrame(geometry=shapely.simplify(shapely.make_valid(parks.geometry.values), 4), crs=build.UTM).to_crs(4326)
    parks["geometry"] = shapely.set_precision(parks.geometry.values, 1e-5)
    (out / "parks.json").write_text(parks[~parks.geometry.is_empty].to_json(drop_id=True))

    w, s_, e, nn = gpd.GeoSeries([limits], crs=build.UTM).to_crs(4326).total_bounds
    (out / "index.json").write_text(json.dumps({"name": area.title(), "ground": JOINED, "from": TODAY, "origin": build.ORIGIN,
                                                "box": [round(w, 4), round(s_, 4), round(e, 4), round(nn, 4)], "cells": cells, "trees": tree_cells}))
    if not ground_only:
        print(f"  with a name: {int(name.notna().sum()):,}; with an address: {int((address != '').sum()):,}; trees: {n_trees:,} in {len(tree_cells)} files,",
              f"{sum((out / t['file']).stat().st_size for t in tree_cells) / 1e6:.1f} MB")
    print(f"{area.title()}: {n_buildings:,} buildings, {n_roofs:,} sloped roofs, {len(cells)} cells, {size / 1e6:.1f} MB;",
          f"streets {(out / 'streets.json').stat().st_size / 1e6:.1f} MB, parks {(out / 'parks.json').stat().st_size / 1e6:.1f} MB")
