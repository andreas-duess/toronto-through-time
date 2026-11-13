"""Homes of Torontonians who died in the Second World War: web/public/data/poppies.json.

data/manual/war_dead_addresses.txt is a list of street addresses, one a line, from a published
map of Toronto's war dead (pasted in by hand; its notes such as "geocoded from 1940 city
directory" are kept in the file). The list has addresses only: no names. Each address is looked
up in the City's address points (data/raw/address_points.csv). Where today's city has the street
but not the number, the nearest number on the same side of that street is used. Addresses whose
street cannot be found today are left out.

Writes [[lon, lat, address as given, 1 if the place is the nearest number only], ...].

Run: uv run pipeline/poppies.py
"""
import json
import pathlib
import re

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHORT = {"AVENUE": "AVE", "STREET": "ST", "ROAD": "RD", "CRESCENT": "CRES", "CRES": "CRES", "BOULEVARD": "BLVD", "DRIVE": "DR",
         "GARDENS": "GDNS", "PARKWAY": "PKWY", "SQUARE": "SQ", "PLACE": "PL", "TERRACE": "TER", "EAST": "E", "WEST": "W",
         "NORTH": "N", "SOUTH": "S", "AV": "AVE", "CRESENT": "CRES", "MT": "MOUNT", "SAINT": "ST"}


def key(address):
    """(number, street) of an address, both normalised; (None, None) if it has no number."""
    a = re.sub(r"\(.*?\)", " ", str(address).upper())
    a = re.sub(r"[.,`']", "", a).split(",")[0]
    words = [SHORT.get(w, w) for w in a.split()]
    if not words or not re.fullmatch(r"\d+[A-Z]?", words[0]):
        return None, None
    return int(re.match(r"\d+", words[0]).group()), " ".join(words[1:])


KINDS = {"AVE", "ST", "RD", "CRES", "BLVD", "DR", "GDNS", "PKWY", "SQ", "PL", "TER", "GRV", "GROVE", "LANE", "CRT", "CT", "E", "W", "N", "S", "HTS", "PK", "PARK"}


def name(street):
    """A street's name without its kind and direction, except where that would leave nothing."""
    words = street.split()
    while len(words) > 1 and words[-1] in KINDS:
        words.pop()
    return " ".join(words)


if __name__ == "__main__":
    ap = pd.read_csv(ROOT / "data" / "raw" / "address_points.csv", dtype=str, usecols=["ADDRESS_FULL", "geometry"])
    xy = ap.geometry.str.extract(r"\[\[([-\d.]+), ([-\d.]+)\]").astype(float)
    keys = ap.ADDRESS_FULL.map(key)
    ap = pd.DataFrame({"number": [k[0] for k in keys], "street": [k[1] for k in keys], "lon": xy[0], "lat": xy[1]}).dropna()
    streets = {street: g.sort_values("number") for street, g in ap.groupby("street")}
    by_name = {}
    for street in streets:
        by_name.setdefault(name(street), []).append(street)
    out, missed = [], []
    for line in (ROOT / "data" / "manual" / "war_dead_addresses.txt").read_text().splitlines():
        number, street = key(line)
        g = streets.get(street) if street else None
        if g is None and street:
            # "48 Albany" for Albany Ave, "310 Wellesley St" for Wellesley St E, "343 Indian Grove" for
            # Indian Grv: the streets of the same name whatever their kind and direction, and of
            # those the one with the nearest number
            like = [streets[s] for s in by_name.get(name(street), [])]
            g = min(like, key=lambda c: (c.number - number).abs().min()) if like else None
        if g is None:
            missed.append(line)
            continue
        same_side = g[g.number % 2 == number % 2]
        g = same_side if len(same_side) else g
        nearest = g.iloc[(g.number - number).abs().argmin()]
        if abs(nearest.number - number) > 40:
            missed.append(line)
            continue
        out.append([round(nearest.lon, 5), round(nearest.lat, 5), re.sub(r"\s*\(.*?\)", "", line).strip(), int(nearest.number != number)])
    (ROOT / "web" / "public" / "data" / "poppies.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"{len(out):,} placed ({sum(o[3] for o in out)} at the nearest number), {len(missed)} not found:", "; ".join(missed[:14]))
