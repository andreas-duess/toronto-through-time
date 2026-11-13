"""Archive photographs for the map: web/public/data/photos.json.

From OldTO (Sidewalk Labs, 2018, Apache 2.0; github.com/sidewalklabs/oldto, data/images.geojson
saved as data/raw/oldto/images.geojson), which placed the City of Toronto Archives' digitized
photographs on the map from their titles: by landmark, address or street corner. Kept here: the
photographs inside the old city that the Archives' record marks "OPEN - No restrictions", with a
year. The picture files are still served from OldTO's own storage (BASE); the Archives' record
links in the data no longer work, so the citation (fonds and item) is the credit.

Writes {base, photos: [[lon, lat, year, about (1 if "ca."), file, title, citation], ...]} in
order of year.

Run: uv run pipeline/photos.py
"""
import json
import pathlib
import re

import geopandas as gpd
import shapely

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "https://storage.googleapis.com/sidewalk-old-toronto/"

if __name__ == "__main__":
    old = gpd.read_file(ROOT / "data" / "raw" / "former_municipalities.geojson")
    old = old[old.AREA_NAME == "TORONTO"].geometry.iloc[0]
    shapely.prepare(old)
    rows = []
    for f in json.loads((ROOT / "data" / "raw" / "oldto" / "images.geojson").read_text())["features"]:
        p, at = f["properties"], f.get("geometry")
        image, record = p.get("image") or {}, p.get("archives_fields") or {}
        url = image.get("url") or ""
        year = re.search(r"1[789]\d\d|20[012]\d", str(p.get("date") or ""))
        if not (at and year and url.startswith(BASE + "images/") and (record.get("condition") or "").startswith("OPEN - No restrictions")):
            continue
        lon, lat = at["coordinates"]
        if not shapely.contains_xy(old, lon, lat):
            continue
        about = int(bool(re.search(r"ca\.|\?|-|between|or ", str(record.get("date") or ""))))
        title = re.sub(r"\s+", " ", p.get("title") or "").strip()
        rows.append([round(lon, 5), round(lat, 5), int(year.group()), about, url[len(BASE) + 7:-4], title, record.get("citation") or ""])
    rows = [r for r in rows if 1793 <= r[2] <= 2026]
    rows.sort(key=lambda r: (r[2], r[4]))
    out = ROOT / "web" / "public" / "data" / "photos.json"
    out.write_text(json.dumps({"base": BASE, "photos": rows}, separators=(",", ":"), ensure_ascii=False))
    print(f"{len(rows):,} photographs, {out.stat().st_size / 1e6:.1f} MB")
