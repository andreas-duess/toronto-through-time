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

Run: uv run pipeline/district.py ETOBICOKE
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


if __name__ == "__main__":
    area = sys.argv[1].upper()
    slug = area.lower().replace(" ", "_")
    out = ROOT / "web" / "public" / "data" / "d" / slug
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("cell.*.bin"):
        old.unlink()

    b, limits = build.load_buildings(area)
    b["year"] = TODAY          # as it stands today; years from 1998 on are a later step
    b = b.reset_index(drop=True)
    roof_of, middle, info = build.roofs(b)        # lowers the walls of the houses to their eaves
    roof_at = np.full(len(b), -1)
    roof_at[roof_of] = np.arange(len(roof_of))

    cen = b.geometry.centroid
    cx, cy = np.floor(cen.x / CELL_M).astype(int), np.floor(cen.y / CELL_M).astype(int)
    cells, size = [], 0
    for n, (x, y) in enumerate(sorted(set(zip(cx, cy)))):
        rows = np.flatnonzero((cx == x) & (cy == y))
        mine = b.iloc[rows]
        has = roof_at[rows] >= 0
        data = cell_file(mine, np.flatnonzero(has), middle[roof_at[rows][has]], info[roof_at[rows][has]])
        (out / f"cell.{n}.bin").write_bytes(data)
        size += len(data)
        w, s, e, nn = mine.to_crs(4326).total_bounds
        cells.append({"file": f"cell.{n}.bin", "box": [round(w, 5), round(s, 5), round(e, 5), round(nn, 5)], "buildings": len(mine)})

    # streets: the City's centreline inside the district, by kind
    centre = gpd.read_file(RAW / "centreline.gpkg").to_crs(build.UTM)
    centre = centre[centre.intersects(limits)]
    centre["kind"] = centre.FEATURE_CODE_DESC.map(streets_.KINDS)
    centre = centre[centre.kind.notna()]
    lines = gpd.GeoDataFrame({"kind": centre.kind.astype(int), "name": centre.LINEAR_NAME_FULL.fillna("")},
                             geometry=shapely.simplify(centre.geometry.intersection(limits).values, 2), crs=build.UTM)
    lines = lines[~lines.geometry.is_empty].to_crs(4326)
    lines["geometry"] = shapely.set_precision(lines.geometry.values, 1e-6)
    (out / "streets.json").write_text(lines.to_json(drop_id=True))
    parks = gpd.read_file(RAW / "green_spaces.geojson").to_crs(build.UTM)
    parks = parks[parks.intersects(limits)]
    parks = gpd.GeoDataFrame(geometry=shapely.simplify(shapely.make_valid(parks.geometry.values), 3), crs=build.UTM).to_crs(4326)
    parks["geometry"] = shapely.set_precision(parks.geometry.values, 1e-6)
    (out / "parks.json").write_text(parks[~parks.geometry.is_empty].to_json(drop_id=True))

    (out / "index.json").write_text(json.dumps({"name": area.title(), "from": TODAY, "origin": build.ORIGIN, "cells": cells}))
    print(f"{area.title()}: {len(b):,} buildings, {len(roof_of):,} sloped roofs, {len(cells)} cells, {size / 1e6:.1f} MB;",
          f"streets {(out / 'streets.json').stat().st_size / 1e6:.1f} MB, parks {(out / 'parks.json').stat().st_size / 1e6:.1f} MB")
