"""Today's runways, taxiways, aprons and terminals of Toronto Pearson and of the Island airport,
for the live aircraft to stand on: web/public/data/airports.json.

From OpenStreetMap (aeroway=*), asked from Overpass here. Pearson lies outside the old city: it
is the only thing the map draws out there.

Run: uv run pipeline/airports.py
"""
import json
import pathlib
import time
import urllib.parse
import urllib.request

OUT = pathlib.Path(__file__).resolve().parent.parent / "web" / "public" / "data" / "airports.json"
BOXES = ["43.652,-79.672,43.708,-79.578", "43.6215,-79.4060,43.6345,-79.3850"]   # Pearson, the Island (south, west, north, east)
QUERY = "[out:json][timeout:60];(" + "".join(f'way[aeroway~"^(runway|taxiway|taxilane|apron|terminal)$"]({b});relation[aeroway=terminal]({b});' for b in BOXES) + ");out geom;"

if __name__ == "__main__":
    for attempt in range(5):
        try:
            req = urllib.request.Request("https://overpass-api.de/api/interpreter", urllib.parse.urlencode({"data": QUERY}).encode(),
                                         {"User-Agent": "toronto-through-time"})
            ways = json.load(urllib.request.urlopen(req, timeout=120))["elements"]
            break
        except OSError:
            time.sleep(15)
    else:
        raise SystemExit("Overpass did not answer")
    # a terminal mapped as a relation: its outer rings, each as a way of its own
    for r in [w for w in ways if w["type"] == "relation"]:
        ways += [{"type": "way", "tags": r["tags"], "geometry": m["geometry"]} for m in r.get("members", []) if m.get("role") == "outer" and "geometry" in m]
    ways = [w for w in ways if w["type"] == "way"]
    feats = []
    for w in ways:
        kind = w["tags"]["aeroway"].replace("taxilane", "taxiway")
        ring = [[round(n["lon"], 6), round(n["lat"], 6)] for n in w["geometry"]]
        area = kind in ("apron", "terminal") and len(ring) >= 4 and ring[0] == ring[-1]
        if kind in ("apron", "terminal") and not area:
            continue
        feats.append({"type": "Feature", "properties": {"kind": kind, "name": w["tags"].get("name") or w["tags"].get("ref") or ""},
                      "geometry": {"type": "Polygon", "coordinates": [ring]} if area else {"type": "LineString", "coordinates": ring}})
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    kinds = [f["properties"]["kind"] for f in feats]
    print({k: kinds.count(k) for k in sorted(set(kinds))}, f"{OUT.stat().st_size / 1e3:.0f} kB")
