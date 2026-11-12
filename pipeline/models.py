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
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print("wrote landmarks.json", OUT.stat().st_size, "bytes")
