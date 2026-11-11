# Hand tables: places, street years, town extents

Researched 2026-11-11. Every row carries the URL of a page that was opened and states the fact. Nothing was filled from memory. Where a source gives only a decade, the first year of the decade is used and the note says so. Where no year could be found, the year is blank and the note says why.

## Files

- `places.csv` (46 rows): period place names to label. `name,kind,lon,lat,from_year,to_year,note,url`. `to_year` blank = still in use. `from_year` 1793 on natural features means "map start", not the age of the name.
- `street_years.csv` (49 rows): documented opening years for streets. `street,from_street,to_street,year,note,url`. Blank cross streets = whole street inside the old city. 9 rows have a blank year (kept so the gap is visible; filter on `year`).
- `town_extents.csv` (11 rows): extent of the town or city at a date, by bounding streets (today's names). `id,year,west,east,south,north,note,url`. `york_1793_reserves` is a note row with no bounds.

## Coordinates

Taken from the Wikipedia article's coordinates where the article has them. Estimated by hand (flagged "Label point estimated" in the note) for: Lake Ontario, Don River, Ashbridge's Bay (the former marsh, not today's small bay), Taddle Creek, Old Town, New Town, Macaulaytown, Corktown, Riverside, Chinatown (Elizabeth Street), Distillery District. Garrison Creek uses the Trinity Bellwoods Park coordinates; King's College uses the University of Toronto coordinates; the Peninsula uses the Toronto Islands coordinates.

## Editorial end dates (not stated in a source)

- New Town: `to_year` 1834 (incorporation; wards replaced the old names).
- St. John's Ward (The Ward) and Chinatown (Elizabeth Street): `to_year` 1960, from "expropriated and razed starting in the late 1950s".
- The Garrison / Fort York switch at 1870: source says the name Fort York emerged "during the 1870s".

## Decade-only dates (first year of the decade used)

Cabbagetown (late 1840s, 1850 used), Parkdale, Seaton Village, Leslieville (1850s), Kensington Market (1920s), Chinatown at Spadina (1950s to 1960s, 1960 used), Chinatown at Elizabeth Street (early 1900s).

## Candidates not sourced, or only partly

Places:
- **Riverdale**: no source dates the name; only "Riverside" is tied to a date (1884 annexation). Left out.
- **Macaulaytown**: no start year found (Wikipedia, Lost Rivers). Row kept with blank `from_year`.
- **Corktown**: "early 19th century" only. Row kept with blank `from_year`.
- **Toronto Bay vs Toronto Harbour**: sources use both names and give no date for a change. One row.
- **West Toronto Junction**: folded into The Junction row (name changes in the note).
- **Regent Park 1948**: not found; source gives approval 1947 and first tenants 1949 (1949 used).
- **Liberty Village, St. James Town, Port Lands, Kensington Market**: the name itself is not dated in the source; the year used is the earliest dated event tied to the name (see notes).
- **The Beaches, Sunnyside, Swansea, Humber Bay, Moss Park**: looked at, no dated origin of the name found; left out.

Streets:
- **Queens Quay**: only "sometime after 1919 to the early 1920s". Year blank.
- **Rosedale Valley Road**: approved 1887, built in the 1890s; no opening year. Year blank. Source is a local history blog (scenesto.com) quoting the Globe; Wikipedia has no article text.
- **Bloor Street, St. Clair Avenue**: concession roads, no opening year. Year blank.
- **Yonge Street, Queen to Bloor**: no year (a path, "road to Yonge Street"). Year blank.
- **Dundas Street**: Arthur, Agnes and Wilton stretches and the 1950s extension east of Broadview have no year. Year blank.
- **Lake Shore Boulevard**: no opening year for the Sunnyside stretch on its own; 1924 is when the route reached Bathurst. 1959 for the downtown and eastern stretches is the renaming of older streets (Fleet, Keating), not their first opening.
- **Jarvis Street north of Queen**: 1846 is when the Jarvis estate began to be sold, not a stated opening date.
- **Davenport Road**: 1797 is the first documented name; the trail is far older.

Town extents:
- **Yorkville (1883) and The Annex (1887) annexations**: no source describes the annexed area by bounding streets. Left out.
- **Seaton Village (1888)**: bounds are today's neighbourhood limits, not a stated annexation boundary.
- **1834 north limit**: "400 yards north of Queen" (Old Toronto) vs "a line analogous to Dundas Street" (Amalgamation of Toronto). Roughly the same line.
- **1797 extension**: sources give the west limit (Peter Street) clearly; the east edge of the New Town is given as Jarvis, leaving George to Jarvis unassigned.
