# Toronto Through Time

A 3D map of the old City of Toronto with a year slider from 1793 to 2026. Each
of today's buildings appears in the year it was built. Proof of concept,
modelled on [Bay Area Through Time](https://bay.theojaffee.net/).

## Run it

```
cd web
npm install
npm run dev        # or: npm run build && npm run preview
```

The built data files are in `web/public/data/`, so the map runs without the
pipeline. The address keeps the year and the camera (`#year=1904.0&c=-79.381,43.647&z=15.6&p=60&b=10`),
so any view can be shared as a link.

## Rebuild the data

```
uv sync
uv run pipeline/download.py    # about 2 GB into data/raw/ (not in git)
uv run pipeline/wikidata.py
uv run pipeline/build.py       # writes web/public/data/
uv run pipeline/water.py       # historic water; downloads its own sources
uv run --with pillow --with scipy pipeline/woods.py   # woods on the 1851 map, into data/interim/
uv run pipeline/streets.py     # dated streets, railways, forest, parks, names; needs the steps above
uv run --with pillow --with scipy --with rasterio pipeline/plans.py   # outlines off the fire insurance plans
uv run --with pillow --with scipy --with rasterio pipeline/plans.py --area island    # and --area trinity
uv run --with pillow --with scipy --with rasterio pipeline/island.py   # Island outline 1913, 1924; then water.py again
uv run --with rasterio pipeline/lost.py    # lost buildings; then run build.py, streets.py and this once more
uv run --with rasterio --with pyogrio --with scipy pipeline/trees.py   # today's trees, from the city's canopy study
uv run pipeline/tracks.py      # streetcar tracks, for the live streetcars
uv run --no-project --python 3.12 --with fiona --with geopandas --with pyproj pipeline/shapes.py --area ETOBICOKE   # then:
uv run pipeline/district.py ETOBICOKE   # a district outside the old city, as it stands today (web/public/data/d/etobicoke/)
for d in YORK "NORTH YORK" "EAST YORK" SCARBOROUGH; do uv run pipeline/district.py "$d" --ground; done   # streets and parks only, from 1998
uv run pipeline/chargers.py    # EV charging stations (needs ~/.config/secrets/NLR_API_KEY)
uv run pipeline/airports.py    # runways and terminals of Pearson and the Island airport, for the live aircraft
uv run --no-project --python 3.12 --with fiona --with geopandas --with pyproj pipeline/pearson.py   # Pearson's buildings from Mississauga's 3D model
uv run pipeline/narrate.py     # the story read aloud (ElevenLabs), after any change to data/manual/story.csv
uv run --no-project --python 3.12 --with fiona --with geopandas --with pyproj pipeline/shapes.py   # real shapes of big buildings, before build.py
uv run pipeline/photos.py      # archive photographs (needs data/raw/oldto/images.geojson from github.com/sidewalklabs/oldto);
                               # the pictures themselves are in the R2 bucket toronto-through-time-photos, served by web/worker.js
uv run --with shapely pipeline/commons.py   # photographs from Wikimedia Commons, 1990 on (slow the first time; answers are kept in data/raw/commons)
uv run --with geopandas --with pillow pipeline/figures.py   # pictures of the sources for the "How it was made" page
uv run pipeline/pack.py        # last: small copies of the building files for the page
```

## How a building gets its year

Toronto has no public year-built record, so `pipeline/build.py` takes the best
source that covers each building: named landmarks (Wikidata and
`data/manual/landmarks.csv`), the Heritage Register, the apartment building
registration, new-building permits since 2001, the first yearly 3D massing
snapshot the building appears in (2018 on), and for the remaining 86% an
estimate from 2021 census construction periods and the dates of nearby
buildings. `web/public/sources.html` has the full list with licences.

## Hand-built landmarks

`web/src/landmarks.js` builds the CN Tower, the Rogers Centre and BMO Field from simple shapes;
`pipeline/models.py` supplies their outlines from OpenStreetMap. The comment above each model says
which numbers are sourced and which are judged from photographs. To add one: a function that
returns a mesh, an entry in `landmarkParts` with its construction years, and an entry in `FACTS`.

## Known limits

- Lost buildings are shown only between Bathurst Street and the Don, the lake and Bloor Street,
  and only from Goad's fire insurance plans of 1880, 1889, 1903, 1913 and 1924
  (`pipeline/plans.py`, `pipeline/lost.py`; what is read and what is estimated is listed at the
  top of each). Outlines and brick or wood are from the plans; years fall between plan years or
  are estimates; heights are assumed (wood 6.5 m, brick 10 m). Row houses often come out as one
  block. Nothing demolished is shown elsewhere, and nothing that went up and came down between
  1924 and today.
- Estimated years are good to about a decade.
- Towers built 2001 to 2017 often have no usable permit and are estimated.
- There is no modern base map. Streets come from the city's centreline file, which has no dates:
  each segment's year is an estimate (`pipeline/streets.py`, method at the top of that file), so
  streets in rebuilt areas appear too late, and only streets that exist today are shown. Street
  names are today's in every year (Queen Street was Lot Street until 1844).
- Railways are today's tracks from OpenStreetMap, shown from the year each line opened
  (`data/manual/rail_years.csv`). Along the harbour, where today's tracks lie on later fill, they
  are moved to the shore of each mapped year.
- The forest has one source, the woods drawn on Browne's 1851 map, read off the scan by
  `pipeline/woods.py` (it misses some and adds some). Before 1851 the clearing is an estimate
  spreading out from the first roads; after 1851 woods go when a street or building comes within
  150 m.
- Parks are today's, shown green in every year once the forest around them is cleared.
- Not drawn: creeks. Today's Don River channel and today's ponds show in every year.
- Cast shadows are written (`web/src/sun.js`) but off (`SHADOWS` in `web/src/main.js`): with them on, clicking a
  building finds nothing and the frame rate about halves.
- The water is historic from 1834 to 1931 (`pipeline/water.py`, sources and hand-made parts listed
  at the top of that file); today's shore takes over in 1954 to 1956 (no map in between is used). In the harbour, the Port Lands and the lower Don only the water of the year is drawn; elsewhere today's water shows in every year.
- Courtyards are filled in.

## Hand-edited tables

`data/manual/`: `landmarks.csv` (dates that override everything), `story.csv`
(story stops: text, camera position, camera turn, optional end year and source link; also the
ticks on the slider), `population.csv` (census counts for the old city).

For the streets and names, each row with its source: `places.csv` (place names and the years they
are shown), `street_years.csv` (documented opening years, which replace the estimate; rows with a
blank year record what could not be sourced), `town_extents.csv` (documented town and city limits
by bounding streets), `map_extents.csv` (outlines of the built-up town traced by eye from the
georeferenced maps of 1834 and 1842), `rail_years.csv` (opening year of each railway line),
`sites.csv` (a site whose buildings share one documented year, with its outline: Fort York).
`lost_zones.csv` (places where written sources date the lost buildings: parts of the Island, the
old Trinity College), `island.csv` (the research behind the Island rows). `places_README.md` lists what is estimated or unsourced.

## The rest of the city, and keeping it current

Etobicoke, York, North York, East York and Scarborough are drawn as they stand today
(`web/public/data/d/<district>/`): streets and parks from 1998, buildings at the last year. They
have no history. To bring them up to date, about twice a year:

```sh
# 1. the City's newest 3D massing (outline and multipatch editions) into data/raw: add the new
#    edition's resource ids to pipeline/download.py and point build.py and shapes.py at it
uv run pipeline/download.py
# 2. each district: its shapes, then its cells, streets and parks
for d in ETOBICOKE YORK "NORTH YORK" "EAST YORK" SCARBOROUGH; do
  uv run --no-project --python 3.12 --with fiona --with geopandas --with pyproj pipeline/shapes.py --area "$d"
  uv run --with rasterio --with pyogrio --with scipy pipeline/district.py "$d"      # buildings, roofs, trees, addresses, names, streets, parks
done
# 3. live data that is a snapshot
uv run pipeline/chargers.py
# 4. publish
cd web && npm run deploy
```

`LAST_YEAR` in `pipeline/build.py` is the year "today" stands for; it moves with the calendar.
The old city's own refresh is the full run above.

## Online

Live at https://torontothroughtime.com (https://toronto.duess.com, the first address, and the www form redirect there:
`redirect/`, deployed with `cd redirect && npx wrangler deploy`), a static site on Cloudflare Workers (`web/wrangler.jsonc`).
To publish the current state: `cd web && npm run deploy` (builds, then uploads `web/dist`).

## Licence

The code is under the MIT licence (`LICENSE`). The data keeps the licence of its source; `web/public/sources.html` lists each one.
