"""Public electric-vehicle charging stations in and around Toronto: web/public/data/chargers.json.

From the Alternative Fuels Station Locator (the US Department of Energy's database, which Natural
Resources Canada feeds for Canada), by its API. The key is in ~/.config/secrets/NLR_API_KEY
(free, from https://developer.nlr.gov/signup/). Stations that are open and public, inside BOX.

Writes [[lon, lat, name, network, address, level 2 chargers, fast chargers, plugs, year opened or 0], ...].

Run: uv run pipeline/chargers.py
"""
import json
import pathlib
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOX = (-79.70, 43.55, -79.10, 43.86)      # west, south, east, north: Toronto and its near neighbours
PLUGS = {"J1772": "J1772", "J1772COMBO": "CCS", "CHADEMO": "CHAdeMO", "TESLA": "Tesla (NACS)", "NACS": "Tesla (NACS)", "J3400": "Tesla (NACS)"}

if __name__ == "__main__":
    key = (pathlib.Path.home() / ".config" / "secrets" / "NLR_API_KEY").read_text().strip()
    q = urllib.parse.urlencode({"api_key": key, "fuel_type": "ELEC", "country": "CA", "state": "ON", "status": "E", "access": "public", "limit": "all"})
    stations = json.load(urllib.request.urlopen(f"https://developer.nlr.gov/api/alt-fuel-stations/v1.json?{q}", timeout=180))["fuel_stations"]
    out = []
    for s in stations:
        lon, lat = s.get("longitude"), s.get("latitude")
        if lon is None or lat is None or not (BOX[0] < lon < BOX[2] and BOX[1] < lat < BOX[3]):
            continue
        plugs = sorted({PLUGS.get(p, p) for p in s.get("ev_connector_types") or []})
        year = int(s["open_date"][:4]) if s.get("open_date") else 0
        out.append([round(lon, 5), round(lat, 5), (s.get("station_name") or "").strip(), s.get("ev_network") or "", (s.get("street_address") or "").strip(),
                    s.get("ev_level2_evse_num") or 0, s.get("ev_dc_fast_num") or 0, ", ".join(plugs), year])
    out.sort(key=lambda r: (r[8], r[2]))
    (ROOT / "web" / "public" / "data" / "chargers.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    nets = {}
    for r in out:
        nets[r[3]] = nets.get(r[3], 0) + 1
    print(len(stations), "in Ontario;", len(out), "in the box;", sorted(nets.items(), key=lambda t: -t[1])[:8])
    years = sorted(r[8] for r in out if r[8])
    print("years opened:", years[0], "to", years[-1], "| without a date:", sum(1 for r in out if not r[8]), "| by year:", {y: years.count(y) for y in sorted(set(years))})
