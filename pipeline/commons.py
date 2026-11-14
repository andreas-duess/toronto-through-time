"""Photographs of Toronto from Wikimedia Commons, for the years the Archives' pictures thin out:
web/public/data/photos_commons.json.

Commons has the place and the date of a photograph as its uploader gave them, and a free licence
for each. This asks Commons for every file located inside the city (in tiles, split where a tile
is full), reads each file's date taken, author and licence, and keeps JPEGs from FIRST_YEAR on
under a Creative Commons licence or in the public domain. Of a burst of pictures taken in one
spot in one year, the first PER_SPOT are kept.

The picture files stay on Wikimedia's servers; the page links each to its Commons page, which
the licences ask for along with the author's name.

Writes [[lon, lat, year, file name, author, licence], ...] in order of year. The answers from
Commons are kept in data/raw/commons/ so that a second run only asks for what is new.

Run: uv run pipeline/commons.py
"""
import html
import json
import pathlib
import re
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "commons"
BOX = (43.58, -79.64, 43.86, -79.11)      # south, west, north, east: the city
FIRST_YEAR = 1990
PER_SPOT = 3
SPOT = 0.0015                             # degrees: about 150 m


def api(**params):
    params.update(format="json", action="query")
    req = urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "toronto-through-time/0.1 (hi@torontothroughtime.com)"})
    for attempt in range(8):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=90))
        except OSError as e:
            r = {"error": str(e)}
        if "error" not in r:
            time.sleep(0.2)
            return r
        print("  Commons:", str(r["error"])[:160], flush=True)     # asked too fast, or busy: wait and ask again
        time.sleep(15 * (attempt + 1))
    raise SystemExit("Commons did not answer")


def located(s, w, n, e, depth=0):
    """The files located in a box: {pageid: (lat, lon)}. A full answer means there are more: the box is quartered."""
    hits = api(list="geosearch", gsbbox=f"{n}|{w}|{s}|{e}", gsnamespace="6", gslimit="500", gsprimary="all").get("query", {}).get("geosearch", [])
    if len(hits) < 500 or depth >= 6:
        return {h["pageid"]: (h["lat"], h["lon"]) for h in hits}
    out, ms, mw = {}, (s + n) / 2, (w + e) / 2
    for box in ((s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)):
        out.update(located(*box, depth + 1))
    return out


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    places_file, facts_file = RAW / "places.json", RAW / "facts.json"
    if places_file.exists():
        places = {int(k): v for k, v in json.loads(places_file.read_text()).items()}
    else:
        places, lat = {}, BOX[0]
        while lat < BOX[2]:
            lon = BOX[1]
            while lon < BOX[3]:
                places.update(located(lat, lon, lat + 0.02, lon + 0.028))
                lon += 0.028
            lat += 0.02
            print(f"  up to latitude {lat:.2f}: {len(places):,} files", flush=True)
        places_file.write_text(json.dumps(places))
    facts = json.loads(facts_file.read_text()) if facts_file.exists() else {}
    todo = [p for p in places if str(p) not in facts]
    for i in range(0, len(todo), 50):
        r = api(pageids="|".join(map(str, todo[i:i + 50])), prop="imageinfo", iiprop="extmetadata|mime|size")
        for page in r["query"]["pages"].values():
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            text = lambda k: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", (meta.get(k) or {}).get("value", "")))).strip()
            facts[str(page["pageid"])] = [page.get("title", "")[5:], text("DateTimeOriginal"), text("Artist"), text("LicenseShortName"), info.get("mime"), info.get("width")]
        if i % 5000 == 0:
            facts_file.write_text(json.dumps(facts))
            print(f"  facts for {i:,} of {len(todo):,}", flush=True)
    facts_file.write_text(json.dumps(facts))

    rows, spots = [], {}
    for pid, (lat, lon) in sorted(places.items()):
        name, taken, author, licence, mime, width = facts.get(str(pid), [""] * 6)
        year = re.search(r"(?<!\d)(19[5-9]\d|20[012]\d)(?!\d)", taken or "")
        if not year or mime != "image/jpeg" or (width or 0) < 800 or not re.match(r"CC|Public domain", licence or ""):
            continue
        y = int(year.group())
        if not FIRST_YEAR <= y <= 2026:
            continue
        spot = (round(lat / SPOT), round(lon / SPOT), y)
        spots[spot] = spots.get(spot, 0) + 1
        if spots[spot] > PER_SPOT:
            continue
        rows.append([round(lon, 5), round(lat, 5), y, name, author[:60], licence])
    rows.sort(key=lambda r: (r[2], r[3]))
    out = ROOT / "web" / "public" / "data" / "photos_commons.json"
    out.write_text(json.dumps(rows, separators=(",", ":"), ensure_ascii=False))
    by = {}
    for r in rows:
        by[r[2] // 10 * 10] = by.get(r[2] // 10 * 10, 0) + 1
    print(f"{len(places):,} located files; {len(rows):,} kept, {out.stat().st_size / 1e6:.1f} MB; by decade {sorted(by.items())}")
