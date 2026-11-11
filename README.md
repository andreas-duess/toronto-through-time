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
```

## How a building gets its year

Toronto has no public year-built record, so `pipeline/build.py` takes the best
source that covers each building: named landmarks (Wikidata and
`data/manual/landmarks.csv`), the Heritage Register, the apartment building
registration, new-building permits since 2001, the first yearly 3D massing
snapshot the building appears in (2018 on), and for the remaining 86% an
estimate from 2021 census construction periods and the dates of nearby
buildings. `web/public/sources.html` has the full list with licences.

## Known limits

- Only buildings standing today are shown; nothing demolished.
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
- The water is historic from 1834 to 1931 (`pipeline/water.py`, sources and hand-made parts listed
  at the top of that file); today's shore fades in between 1950 and 1960.
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
`places_README.md` lists what is estimated or unsourced.
