"""Archive photographs for the map: web/public/data/photos.json.

From OldTO (Sidewalk Labs, 2018, Apache 2.0; github.com/sidewalklabs/oldto, data/images.geojson
saved as data/raw/oldto/images.geojson), which placed the City of Toronto Archives' digitized
photographs on the map from their titles: by landmark, address or street corner. Kept here: the
photographs inside the old city that the Archives' record marks "OPEN - No restrictions", with a
year. The picture files were copied once from OldTO's storage (BASE) into the site's own R2
bucket, toronto-through-time-photos, which web/worker.js serves at /photos/<file>.jpg. The
Archives' record links in the data no longer work, so the citation (fonds and item) is the credit.

Writes {base (where the page finds the pictures), photos: [[lon, lat, year, about (1 if "ca."), file, title, citation], ...]} in
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

# Words OldTO took for a landmark that are too loose to place a picture by: "Boating on the bay"
# went to The Bay, the department store at Yonge and Bloor.
VAGUE = {"the bay", "st. andrew", "post office", "old toronto", "mr. barber", "main building", "war memorial", "boiler house",
         "dental clinic", "george brown", "egerton ryerson", "ned hanlan", "edward hanlan", "mt. pleasant", "russell hill",
         "royal oak", "island park", "the archer", "press building", "reference library", "police headquarters", "york school"}
# A landmark that was not there yet: a picture older than this was of something else of the name.
NOT_BEFORE = {"cn tower": 1972, "skydome": 1985, "ontario place": 1969, "nathan phillips square": 1958, "royal bank": 1976,
              "canada life": 1929, "general hospital": 1913, "toronto general hospital": 1913, "maple leaf gardens": 1930,
              "harbour square": 1965, "city hall": 1899, "toronto city hall": 1899, "knox college": 1915, "college park": 1928,
              "royal york": 1927, "king edward hotel": 1900, "commerce court": 1929}
# A name that moved: before the year, the picture goes to where the name then stood (lon, lat).
MOVED = {"city hall": (1965, (-79.3817, 43.6525)), "toronto city hall": (1965, (-79.3817, 43.6525)),     # Old City Hall
         "trinity college": (1925, (-79.4142, 43.6467))}                                                  # Queen Street West


if __name__ == "__main__":
    old = gpd.read_file(ROOT / "data" / "raw" / "former_municipalities.geojson")
    old = old[old.AREA_NAME == "TORONTO"].geometry.iloc[0]
    shapely.prepare(old)
    rows, skipped = [], 0
    for f in json.loads((ROOT / "data" / "raw" / "oldto" / "images.geojson").read_text())["features"]:
        p, at = f["properties"], f.get("geometry")
        image, record = p.get("image") or {}, p.get("archives_fields") or {}
        url = image.get("url") or ""
        year = re.search(r"1[789]\d\d|20[012]\d", str(p.get("date") or ""))
        # OldTO put 2018, the year it was made, where it could not read the Archives' date
        # ("December 24,1923", "[ca. 19--]"). The year is then read here; a date without one is left out.
        if year and year.group() == "2018" and "2018" not in str(record.get("date") or ""):
            year = re.search(r"1[789]\d\d|20[01]\d", re.sub(r"Digitized \d{4}", "", str(record.get("date") or "")))
        if not (at and year and url.startswith(BASE + "images/") and (record.get("condition") or "").startswith("OPEN - No restrictions")):
            continue
        lon, lat = at["coordinates"]
        # Where OldTO placed a picture by a landmark's name, the name can be the wrong one.
        place = p.get("geocode") or {}
        if (place.get("technique") or [None])[0] == "POI":
            term, y = place.get("search_term"), int(year.group())
            if term in VAGUE or y < NOT_BEFORE.get(term, 0):
                skipped += 1
                continue
            if term in MOVED and y < MOVED[term][0]:
                lon, lat = MOVED[term][1]
        if not shapely.contains_xy(old, lon, lat):
            continue
        about = int(bool(re.search(r"ca\.|\?|-|between|or ", str(record.get("date") or ""))))
        title = re.sub(r"\s+", " ", p.get("title") or "").strip()
        rows.append([round(lon, 5), round(lat, 5), int(year.group()), about, url[len(BASE) + 7:-4], title, record.get("citation") or ""])
    rows = [r for r in rows if 1793 <= r[2] <= 2026]
    rows.sort(key=lambda r: (r[2], r[4]))
    out = ROOT / "web" / "public" / "data" / "photos.json"
    out.write_text(json.dumps({"base": "./photos/", "photos": rows}, separators=(",", ":"), ensure_ascii=False))
    print(f"left out for a doubtful place: {skipped:,}")
    print(f"{len(rows):,} photographs, {out.stat().st_size / 1e6:.1f} MB")
