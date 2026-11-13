"""Today's streetcar tracks for the page, which keeps the live streetcars on them:
web/public/data/tracks.json, a list of lines of [lon, lat], each drawn in its direction of travel.

From OpenStreetMap (railway=tram, data/raw/osm/tram.json from download.py).
Run: uv run pipeline/tracks.py
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    ways = json.loads((ROOT / "data" / "raw" / "osm" / "tram.json").read_text())["elements"]
    lines = [[[round(n["lon"], 6), round(n["lat"], 6)] for n in w["geometry"]] for w in ways
             if len(w.get("geometry", [])) >= 2 and w.get("tags", {}).get("service") not in ("yard", "siding")]
    (ROOT / "web" / "public" / "data" / "tracks.json").write_text(json.dumps(lines, separators=(",", ":")))
    print(f"{len(lines)} lines of track, {sum(len(l) for l in lines)} points")
