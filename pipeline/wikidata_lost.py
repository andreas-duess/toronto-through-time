"""Fetch Toronto buildings that are gone from Wikidata into data/raw/wikidata_lost.json, to give
some of the lost buildings of pipeline/lost.py their names.

An item here has coordinates in Toronto, a date it was demolished or closed (P576) and is an
architectural structure (or an amusement park, a stadium and the like: STRUCTURES). With its name
come the year it opened, if Wikidata has it, and its English Wikipedia article.

Run: uv run pipeline/wikidata_lost.py
"""
import json
import pathlib

from wikidata import qid, sparql

OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw" / "wikidata_lost.json"
ITEMS = """
SELECT ?item ?itemLabel ?coord ?class ?classLabel (MIN(?o) AS ?opened) (MAX(?g) AS ?gone) ?article WHERE {
  ?item wdt:P131* wd:Q172; wdt:P625 ?coord; wdt:P31 ?class; wdt:P576 ?g.
  OPTIONAL { { ?item wdt:P571 ?o } UNION { ?item wdt:P1619 ?o } }
  OPTIONAL { ?article schema:about ?item; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
} GROUP BY ?item ?itemLabel ?coord ?class ?classLabel ?article
"""
# architectural structure, amusement park, sports venue
STRUCTURES = "SELECT ?class WHERE { VALUES ?class { %s } VALUES ?kind { wd:Q811979 wd:Q194195 wd:Q1076486 } ?class wdt:P279* ?kind }"

if __name__ == "__main__":
    rows = sparql(ITEMS)
    classes = sorted({qid(r["class"]) for r in rows})
    kept = set()
    for i in range(0, len(classes), 40):
        kept |= {qid(r["class"]) for r in sparql(STRUCTURES % " ".join("wd:" + c for c in classes[i:i + 40]))}
    out = {}
    for r in rows:
        if qid(r["class"]) not in kept or r["itemLabel"]["value"].startswith("Q"):
            continue
        lon, lat = r["coord"]["value"][6:-1].split()
        # (a date Wikidata does not know comes as a link, not a year)
        year = lambda k: int(r[k]["value"][:4]) if k in r and r[k]["value"][:4].isdigit() else None
        out[qid(r["item"])] = {"name": r["itemLabel"]["value"], "lon": float(lon), "lat": float(lat), "kind": r["classLabel"]["value"],
                               "opened": year("opened"), "gone": year("gone"), "url": r.get("article", {}).get("value")}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(len(out), "lost buildings with a name")
