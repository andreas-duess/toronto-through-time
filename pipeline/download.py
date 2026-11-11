"""Download the raw inputs from the City of Toronto open data portal into data/raw/.

Files that already exist are skipped. Run: uv run pipeline/download.py
"""
import json
import pathlib
import urllib.request
import zipfile

CKAN = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action"
RAW = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw"

# local file name -> CKAN resource id
RESOURCES = {
    "massing_2025.zip": "667237d6-4d3c-4cf3-8cb7-e91c48d59375",
    # earlier snapshots of the same model: a building's first appearance dates it
    "massing_2016.zip": "18cd7933-a44a-454b-92f1-73384661b61b",
    "massing_2017.zip": "2edb15fb-5f8a-4e70-b71b-57e11402dd1b",
    "massing_2018.zip": "97abd447-3119-4ded-a8d1-605e49f9efcd",
    "massing_2019.zip": "240bc13d-9e15-4e2a-95b4-73c3e45c0d19",
    "massing_2020.zip": "9166d5e7-0a94-4b32-99b4-221c53891ce7",
    "massing_2021.zip": "cfb74289-d120-4de9-bb9e-0a725a6fdfff",
    "massing_2022.zip": "e6e0596e-8cb5-4ec4-b543-22ba21acbc07",
    "massing_2023.zip": "246c8ae2-3d5a-40e4-a8c0-9d597725cf70",
    "permits_cleared_2017_on.csv": "b41c3e9e-4d2d-4b09-a789-9569d8da407c",
    "permits_cleared_2000_2016.csv": "c647bdae-0127-425e-86e6-2d88ff0e2adf",
    "permits_active.csv": "dfce3b7b-4f17-4a9d-9155-5e390a5ffa97",
    "apartment_registration.csv": "97b8b7a4-baca-49c7-915d-335322dbcf95",
    "heritage_register.zip": "108b1080-d048-439f-a9e8-e8d6cd81bddb",
    "shoreline_evolution.zip": "1a907476-53a2-40b2-abbb-a3a32b44e33a",
    "neighbourhoods.geojson": "0719053b-28b7-48ea-b863-068823a93aaa",
    "neighbourhood_profiles_2021.xlsx": "19d4a806-7385-4889-acf2-256f1e079060",
    "address_points.csv": "64d4e54b-738f-4cd9-a9e7-8050fac8a52f",
    "centreline.gpkg": "6bb36aba-9747-4255-abb6-b8754fc23c0f",
}
# local file name -> (package id, resource name), for packages not looked up by hand
BY_NAME = {
    "former_municipalities.geojson": ("former-municipality-boundaries", "4326.geojson"),
    "green_spaces.geojson": ("green-spaces", "4326.geojson"),
}


def resource_url(resource_id):
    with urllib.request.urlopen(f"{CKAN}/resource_show?id={resource_id}") as r:
        return json.load(r)["result"]["url"]


def package_resource_url(package, name_part):
    with urllib.request.urlopen(f"{CKAN}/package_show?id={package}") as r:
        for res in json.load(r)["result"]["resources"]:
            if name_part in res["name"]:
                return res["url"]
    raise SystemExit(f"no resource matching {name_part!r} in {package}")


def fetch(name, url):
    dest = RAW / name
    if dest.exists() and dest.stat().st_size > 0:
        print(f"have  {name}")
        return
    print(f"get   {name}  <- {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)
    print(f"done  {name}  {dest.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    for name, rid in RESOURCES.items():
        fetch(name, resource_url(rid))
    for name, (package, part) in BY_NAME.items():
        fetch(name, package_resource_url(package, part))
    for archive in RAW.glob("*.zip"):
        if not (RAW / archive.stem).exists():
            with zipfile.ZipFile(archive) as z:
                z.extractall(RAW / archive.stem)
