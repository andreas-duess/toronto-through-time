"""Fetch dated Toronto buildings from Wikidata into data/raw/wikidata_buildings.json.

Only items that are an instance of an architectural structure (Q811979) or one
of its subclasses, so that founding dates of schools, companies and
neighbourhoods are not mistaken for construction years. The subclass test runs
as a second query over the classes found, because the one-query form times out.
"""
import json
import pathlib
import time
import urllib.parse
import urllib.request

OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw" / "wikidata_buildings.json"
ITEMS = """
SELECT ?item ?itemLabel ?coord ?class ?classLabel (MIN(?d) AS ?date) ?article WHERE {
  ?item wdt:P131* wd:Q172; wdt:P625 ?coord; wdt:P31 ?class.
  { ?item wdt:P571 ?d } UNION { ?item wdt:P1619 ?d }
  FILTER NOT EXISTS { ?item wdt:P576 ?demolished }
  OPTIONAL { ?article schema:about ?item; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
} GROUP BY ?item ?itemLabel ?coord ?class ?classLabel ?article
"""
STRUCTURES = "SELECT ?class WHERE { VALUES ?class { %s } ?class wdt:P279* wd:Q811979 }"


def sparql(query):
    req = urllib.request.Request(
        "https://query.wikidata.org/sparql",
        data=urllib.parse.urlencode({"query": query}).encode(),
        headers={
            "Accept": "application/sparql-results+json",
            "User-Agent": "toronto-through-time/0.1 (andreas@duess.com)",
        })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["results"]["bindings"]
        except OSError:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def qid(binding):
    return binding["value"].rsplit("/", 1)[1]


if __name__ == "__main__":
    rows = sparql(ITEMS)
    classes = sorted({qid(r["class"]) for r in rows})
    structures = set()
    for i in range(0, len(classes), 40):
        values = " ".join("wd:" + c for c in classes[i:i + 40])
        structures |= {qid(r["class"]) for r in sparql(STRUCTURES % values)}
    out = {}
    for row in rows:
        if qid(row["class"]) not in structures:
            continue
        lon, lat = row["coord"]["value"][6:-1].split()
        if qid(row["item"]) in out:
            out[qid(row["item"])]["classes"].append(row["classLabel"]["value"])
            continue
        out[qid(row["item"])] = {
            "id": qid(row["item"]),
            "classes": [row["classLabel"]["value"]],
            "name": row["itemLabel"]["value"],
            "lon": float(lon), "lat": float(lat),
            "year": int(row["date"]["value"][:4]),
            "url": row.get("article", {}).get("value") or row["item"]["value"],
        }
    OUT.write_text(json.dumps(list(out.values()), indent=1))
    print(len(out), "buildings ->", OUT)
