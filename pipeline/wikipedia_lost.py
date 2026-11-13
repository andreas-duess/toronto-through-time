"""Names for some of the lost buildings: data/raw/named_lost.json.

The articles in Wikipedia's categories of demolished buildings and former sports venues in
Toronto that give coordinates, with the years Wikidata has for them (opened, demolished), and
the demolished buildings Wikidata lists itself (pipeline/wikidata_lost.py, run first). A short
list by any measure: most lost buildings never had an article.

Run: uv run pipeline/wikidata_lost.py; uv run pipeline/wikipedia_lost.py
"""
import json
import pathlib
import re
import urllib.parse
import urllib.request

from wikidata import sparql

RAW = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw"
CATEGORIES = ["Demolished buildings and structures in Toronto", "Defunct sports venues in Toronto"]


def api(**params):
    params.update(format="json", action="query")
    req = urllib.request.Request("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "toronto-through-time/0.1 (andreas@duess.com)"})
    return json.load(urllib.request.urlopen(req, timeout=60))


if __name__ == "__main__":
    pages = {}
    for category in CATEGORIES:
        more = {}
        while True:
            d = api(generator="categorymembers", gcmtitle="Category:" + category, gcmlimit="500", gcmnamespace="0",
                    prop="coordinates|pageprops", ppprop="wikibase_item", colimit="500", **more)
            for page in d.get("query", {}).get("pages", {}).values():
                entry = pages.setdefault(page["title"], {})
                if "coordinates" in page:
                    entry.update(lat=page["coordinates"][0]["lat"], lon=page["coordinates"][0]["lon"])
                entry["q"] = page.get("pageprops", {}).get("wikibase_item", entry.get("q"))
            if "continue" not in d:
                break
            more = d["continue"]
    pages = {t: p for t, p in pages.items() if "lat" in p}
    ids = " ".join("wd:" + p["q"] for p in pages.values() if p.get("q"))
    years = {}
    for r in sparql("SELECT ?item (MIN(?o) AS ?opened) (MAX(?g) AS ?gone) WHERE { VALUES ?item { %s } "
                    "OPTIONAL { { ?item wdt:P571 ?o } UNION { ?item wdt:P1619 ?o } } OPTIONAL { ?item wdt:P576 ?g } } GROUP BY ?item" % ids):
        year = lambda k: int(r[k]["value"][:4]) if k in r and r[k]["value"][:4].isdigit() else None
        years[r["item"]["value"].rsplit("/", 1)[1]] = (year("opened"), year("gone"))
    out = []
    for title, p in sorted(pages.items()):
        opened, gone = years.get(p.get("q"), (None, None))
        out.append({"name": re.sub(r"\s*\((Toronto|Ontario|Canada)\)$", "", title), "lon": p["lon"], "lat": p["lat"], "opened": opened, "gone": gone,
                    "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))})
    have = {o["url"] for o in out}
    for v in json.loads((RAW / "wikidata_lost.json").read_text()).values():
        if v["url"] and v["url"] not in have:
            out.append({k: v[k] for k in ("name", "lon", "lat", "opened", "gone", "url")})
    (RAW / "named_lost.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(len(out), "named lost buildings;", sum(1 for o in out if o["gone"]), "with the year they went")
