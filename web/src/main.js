import maplibregl from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { COORDINATE_SYSTEM } from "@deck.gl/core";
import { SolidPolygonLayer } from "@deck.gl/layers";
import { SimpleMeshLayer } from "@deck.gl/mesh-layers";
import { TimeExtension } from "./time.js";
import { landmarkParts, FACTS } from "./landmarks.js";

const $ = (id) => document.getElementById(id);
const DATA = "./data/";
// A building takes this many years to rise, and fades from the highlight colour to the
// plain one by the time it is NEW_SPAN years old.
const RISE_YEARS = 1.5;
const NEW_SPAN = 6;
const OLD_COLOR = [214, 205, 190];
const NEW_COLOR = [217, 84, 43];
const NEW_TINT = NEW_COLOR.map((c, i) => c / OLD_COLOR[i]);
const riseExtension = new TimeExtension({ mode: "rise" });
const LOST_COLOR = [120, 94, 74];
const TIER_COLORS = {
  landmark: [44, 123, 182],
  heritage: [0, 150, 136],
  apartment: [123, 104, 174],
  permit: [230, 159, 0],
  massing: [204, 102, 119],
  estimate: [200, 200, 200],
};
const TIER_LABELS = {
  landmark: "Named landmark (Wikidata, hand-checked list)",
  heritage: "Heritage Register construction date",
  apartment: "Apartment registration, year built",
  massing: "First seen in the city's yearly 3D model",
  permit: "Building permit for a new building",
  estimate: "Estimate: census period and nearby dated buildings",
};

const LAND_COLOR = "#e9e3d3";
const STREET_COLOR = "#fdfcf8";
const WATER_COLOR = "#b5cfe0";
const MARSH_COLOR = "#bcd3bd";
const FOREST_COLOR = "#b9c8a2";
const PARK_COLOR = "#cbdcae";

const fetchJson = (name) => fetch(DATA + name).then((r) => r.json());
const fetchArray = (name, Type) => fetch(DATA + name).then((r) => r.arrayBuffer()).then((b) => new Type(b));

const state = { year: 1793, playing: false, speed: 6, quality: false };
// index: the stop on the card (-1 when closed); run: bumped to cancel a stop's animation
const story = { index: -1, playing: false, run: 0 };
const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
// time to read a story card
const readMs = (text) => Math.max(7000, text.split(/\s+/).length * 330);
// camera flight and year sweep to a story stop: longer for stops further away
function flyMs(s) {
  if (reducedMotion) return 0;
  const c = map.getCenter();
  const km = Math.hypot((s.lon - c.lng) * 80.4, (s.lat - c.lat) * 111.2);
  return Math.min(5500, 2500 + km * 500);
}

// The address keeps the year and the camera, so a view can be shared as a link:
// #year=1904.0&c=-79.38100,43.64700&z=15.60&p=60&b=10
function readHash() {
  const q = new URLSearchParams(location.hash.slice(1));
  const num = (k) => (q.has(k) && Number.isFinite(Number(q.get(k))) ? Number(q.get(k)) : undefined);
  const c = (q.get("c") ?? "").split(",").map(Number);
  return { year: num("year"), zoom: num("z"), pitch: num("p"), bearing: num("b"),
    center: c.length === 2 && c.every(Number.isFinite) ? c : undefined };
}
const opened = readHash();
let hashTimer = 0;
function writeHash() {
  clearTimeout(hashTimer);
  hashTimer = setTimeout(() => {
    const c = map.getCenter();
    history.replaceState(null, "", `#year=${state.year.toFixed(1)}&c=${c.lng.toFixed(5)},${c.lat.toFixed(5)}` +
      `&z=${map.getZoom().toFixed(2)}&p=${map.getPitch().toFixed(0)}&b=${map.getBearing().toFixed(0)}`);
  }, 400);
}

const map = new maplibregl.Map({
  container: "map",
  // No modern base map: only the ground and today's water come from the map tiles. Streets,
  // names and the old shore are our own dated layers, added in addMapLayers().
  style: {
    version: 8,
    glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
    sources: { openmaptiles: { type: "vector", url: "https://tiles.openfreemap.org/planet" } },
    layers: [
      { id: "background", type: "background", paint: { "background-color": LAND_COLOR } },
      { id: "water", type: "fill", source: "openmaptiles", "source-layer": "water",
        // everything but swimming pools: ponds such as Grenadier Pond are old
        filter: ["all", ["!=", ["get", "brunnel"], "tunnel"], ["!=", ["get", "class"], "swimming_pool"]],
        paint: { "fill-color": WATER_COLOR } },
    ],
  },
  center: opened.center ?? [-79.383, 43.653],
  zoom: opened.zoom ?? 13.6,
  pitch: opened.pitch ?? 55,
  bearing: opened.bearing ?? -17,
  maxPitch: 75,
  minZoom: 9,
  maxZoom: 19,
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
map.on("moveend", writeHash);
// taking hold of the map stops the story from moving it
for (const type of ["mousedown", "wheel", "touchstart"]) {
  map.getCanvasContainer().addEventListener(type, () => {
    if (!story.playing) return;
    story.playing = false;
    map.stop();
    syncStoryButton();
  }, { passive: true });
}

const overlay = new MapboxOverlay({ interleaved: true, layers: [], onClick: showBuilding });
map.addControl(overlay);

let meta, buildings, years, heights, tiers, names, water, population, stops, streets, streetLabels, places, area, rail, sites, forest, parks, lost, addresses, landmarks;
// buildings of the city's model that a hand-built landmark stands in for
const replaced = new Set();

async function load() {
  meta = await fetchJson("meta.json");
  const [positions, starts] = await Promise.all([
    fetchArray("positions.bin", Float32Array),
    fetchArray("starts.bin", Uint32Array),
  ]);
  [years, heights, tiers, names, water, population, stops, streets, streetLabels, places, area, rail, sites, forest, parks] = await Promise.all([
    fetchArray("years.bin", Uint16Array),
    fetchArray("heights.bin", Float32Array),
    fetchArray("tiers.bin", Uint8Array),
    fetchJson("names.json"),
    fetchJson("water.json"),
    fetchJson("population.json"),
    fetchJson("story.json"),
    fetchJson("streets.json"),
    fetchJson("street-labels.json"),
    fetchJson("places.json"),
    fetchJson("area.json"),
    fetchJson("rail.json"),
    fetchJson("sites.json"),
    fetchJson("forest.json"),
    fetchJson("parks.json"),
  ]);
  buildings = {
    length: meta.count,
    startIndices: starts,
    attributes: { getPolygon: { value: positions, size: 3 } },
  };
  lost = await loadLost();
  landmarks = landmarkParts(await fetchJson("landmarks.json"));
  const standIns = new Set(Object.values(FACTS).flatMap((f) => f.replaces));
  for (const [i, n] of Object.entries(names)) if (standIns.has(n.name)) replaced.add(Number(i));
  addresses = (await fetch(DATA + "addresses.txt").then((r) => r.text())).split("\n");
  for (const s of stops) {
    for (const k of ["year", "lon", "lat", "zoom", "bearing", "pitch", "orbit"]) s[k] = Number(s[k]);
    s.yearEnd = Number(s.year_end) > s.year ? Number(s.year_end) : s.year;
  }
  population = population.map((p) => [Number(p.year), Number(p.population)]);
  state.year = opened.year >= meta.firstYear && opened.year <= meta.lastYear ? opened.year : meta.firstYear;
  setupControls();
  render();
  if (map.isStyleLoaded()) addMapLayers(); else map.once("load", addMapLayers);
  $("loading").classList.add("done");
}

// Buildings that are gone, read off the fire insurance plans. Absent if lost.json is.
async function loadLost() {
  const info = await fetch(DATA + "lost.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (!info) return null;
  const [positions, starts, span, tall, about] = await Promise.all([
    fetchArray("lost.positions.bin", Float32Array),
    fetchArray("lost.starts.bin", Uint32Array),
    fetchArray("lost.years.bin", Uint16Array),
    fetchArray("lost.heights.bin", Float32Array),
    fetchArray("lost.info.bin", Uint8Array),
  ]);
  return { ...info, span, tall, about,
    data: { length: info.count, startIndices: starts, attributes: { getPolygon: { value: positions, size: 2 } } } };
}

function lostLayer() {
  return new SolidPolygonLayer({
    id: "lost",
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: lost.data,
    positionFormat: "XY",
    coordinateSystem: COORDINATE_SYSTEM.LNGLAT_OFFSETS,
    coordinateOrigin: meta.origin,
    _normalize: false,
    _windingOrder: "CCW",
    extruded: true,
    getElevation: (_, { index }) => lost.tall[index],
    getFillColor: state.quality ? LOST_COLOR : OLD_COLOR,
    updateTriggers: { getFillColor: state.quality },
    material: { ambient: 0.55, diffuse: 0.6, shininess: 8 },
    pickable: true,
    autoHighlight: true,
    highlightColor: [255, 255, 255, 90],
    getYears: (_, { index, target }) => { for (let k = 0; k < 4; k++) target[k] = lost.span[index * 4 + k]; return target; },
    currentYear: state.year,
    growYears: RISE_YEARS,
    tint: state.quality ? [1, 1, 1] : NEW_TINT,
    tintYears: NEW_SPAN,
    extensions: [riseExtension],
  });
}

// Hand-built landmarks: each part rises while it is being built.
function landmarkLayers() {
  return landmarks.filter((p) => state.year >= p.from && state.year < (p.until ?? 9999)).map((p) => new SimpleMeshLayer({
    id: `landmark-${p.id}`,
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: [p],
    mesh: p.mesh,
    coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
    coordinateOrigin: [...p.origin, 0],
    getPosition: [0, 0, 0],
    getColor: [255, 255, 255],
    getScale: [1, 1, Math.max(0.02, Math.min(1, (state.year - p.from) / (p.to - p.from)))],
    updateTriggers: { getScale: Math.min(state.year, p.to) },
    material: { ambient: 0.6, diffuse: 0.6, shininess: 12 },
    pickable: true,
  }));
}

function buildingLayer() {
  return new SolidPolygonLayer({
    id: "buildings",
    // drawn inside the map, over the street names and under the place names
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: buildings,
    coordinateSystem: COORDINATE_SYSTEM.LNGLAT_OFFSETS,
    coordinateOrigin: meta.origin,
    _normalize: false,
    _windingOrder: "CCW",
    extruded: true,
    getElevation: (_, { index }) => heights[index],
    getFillColor: state.quality ? (_, { index }) => TIER_COLORS[meta.tiers[tiers[index]]] : OLD_COLOR,
    updateTriggers: { getFillColor: state.quality },
    material: { ambient: 0.55, diffuse: 0.6, shininess: 8 },
    pickable: true,
    autoHighlight: true,
    highlightColor: [255, 255, 255, 90],
    getYears: (_, { index, target }) => {
      target[0] = replaced.has(index) ? 9999 : years[index];
      target[1] = 9999; target[2] = 0; target[3] = 0;
      return target;
    },
    currentYear: state.year,
    growYears: RISE_YEARS,
    tint: state.quality ? [1, 1, 1] : NEW_TINT,
    tintYears: NEW_SPAN,
    extensions: [riseExtension],
  });
}

// Each mapped shore blends into the next over the years before the next map, this many at most.
const SHORE_BLEND = 8;
const EMPTY = { type: "Polygon", coordinates: [] };
let waterStep = -1;

// Width of a street by kind (lane, local, collector, arterial, expressway), growing with the zoom
// the way a width in metres would.
const streetWidth = (scale) => ["interpolate", ["exponential", 2], ["zoom"],
  11, ["*", scale, ["match", ["get", "kind"], 0, 0.2, 1, 0.6, 2, 0.8, 3, 1.1, 1.3]],
  18, ["*", scale, ["match", ["get", "kind"], 0, 8, 1, 18, 2, 22, 3, 30, 34]]];
const PLACE_STYLE = {
  city: { font: "Noto Sans Bold", size: 19, color: "#2b2620" },
  district: { font: "Noto Sans Regular", size: 11.5, color: "#5b5346", caps: true },
  site: { font: "Noto Sans Regular", size: 11.5, color: "#5b5346" },
  water: { font: "Noto Sans Italic", size: 13, color: "#55768c" },
  landform: { font: "Noto Sans Italic", size: 13, color: "#6a5a3c" },
};
let mapYear = null;

// Our own map, bottom to top: the historic water (painted over today's land), the outline of
// the area covered, the streets of the year, and the names in use that year. Historic water has
// three pieces per step: water in both this map and the next, water lost by the next map, and
// water gained by it.
function addMapLayers() {
  // Today's parks, then the forest not yet cleared, both under today's ponds and rivers: a park
  // is forest until the land around it is cleared and stays green after.
  map.addSource("parks", { type: "geojson", data: parks });
  map.addLayer({ id: "parks", type: "fill", source: "parks", paint: { "fill-color": PARK_COLOR } }, "water");
  map.addSource("forest", { type: "geojson", data: forest });
  map.addLayer({ id: "forest", type: "fill", source: "forest", paint: { "fill-color": FOREST_COLOR } }, "water");
  // land the old maps show where there is water today; the water of the year is painted on top
  for (const part of ["islandLand", "barLand"]) {
    map.addSource(part, { type: "geojson", data: water[part] });
    map.addLayer({ id: part, type: "fill", source: part, paint: { "fill-color": LAND_COLOR } });
  }
  map.addSource("marsh", { type: "geojson", data: water.marsh });
  map.addLayer({ id: "marsh", type: "fill", source: "marsh", paint: { "fill-color": MARSH_COLOR } });
  for (const part of ["common", "lost", "gained"]) {
    map.addSource(`water-${part}`, { type: "geojson", data: EMPTY });
    map.addLayer({ id: `water-${part}`, type: "fill", source: `water-${part}`, paint: { "fill-color": WATER_COLOR } });
  }

  map.addSource("area", { type: "geojson", data: area });
  map.addLayer({ id: "area", type: "line", source: "area",
    paint: { "line-color": "#a79f8c", "line-width": 1, "line-dasharray": [3, 3] } });

  // earthworks of documented sites (the ramparts of Fort York)
  map.addSource("sites", { type: "geojson", data: sites });
  map.addLayer({ id: "sites", type: "fill", source: "sites", paint: { "fill-color": "#d5d3ad" } });
  map.addLayer({ id: "sites-edge", type: "line", source: "sites",
    paint: { "line-color": "#9c9870", "line-width": ["interpolate", ["linear"], ["zoom"], 12, 1, 17, 5] } });

  map.addSource("streets", { type: "geojson", data: streets });
  map.addLayer({ id: "streets-edge", type: "line", source: "streets", minzoom: 14,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#d9d2c0", "line-width": streetWidth(1) } });
  map.addLayer({ id: "streets", type: "line", source: "streets",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": STREET_COLOR, "line-width": streetWidth(0.82) } });

  // railways: a dark line with sleepers
  map.addSource("rail", { type: "geojson", data: rail });
  map.addLayer({ id: "rail", type: "line", source: "rail",
    paint: { "line-color": "#6f675b", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 0.8, 17, 2] } });
  map.addLayer({ id: "rail-ties", type: "line", source: "rail", minzoom: 13,
    paint: { "line-color": "#6f675b", "line-dasharray": [0.15, 1.6],
      "line-width": ["interpolate", ["linear"], ["zoom"], 13, 3, 17, 8] } });

  map.addSource("street-labels", { type: "geojson", data: streetLabels });
  map.addLayer({ id: "street-labels", type: "symbol", source: "street-labels", minzoom: 13.5,
    layout: { "symbol-placement": "line", "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"],
      "text-size": ["interpolate", ["linear"], ["zoom"], 13.5, 9.5, 17, 12.5], "symbol-spacing": 320,
      "symbol-sort-key": ["-", 0, ["get", "kind"]] },
    paint: { "text-color": "#7b7365", "text-halo-color": STREET_COLOR, "text-halo-width": 1.4 } });

  map.addSource("places", { type: "geojson", data: places });
  for (const [kind, st] of Object.entries(PLACE_STYLE)) {
    map.addLayer({ id: `places-${kind}`, type: "symbol", source: "places",
      layout: { "text-field": ["get", "name"], "text-font": [st.font], "text-size": st.size,
        "text-transform": st.caps ? "uppercase" : "none", "text-letter-spacing": st.caps ? 0.12 : 0,
        "text-max-width": 7 },
      paint: { "text-color": st.color, "text-halo-color": "rgba(250,248,242,0.85)", "text-halo-width": 1.5 } });
  }
  waterStep = -1;
  mapYear = null;
  render();
}

// The streets and names of a year. Filters are only set when the whole year changes.
function updateMap(year) {
  const y = Math.floor(year);
  if (y === mapYear || !map.getLayer("streets")) return;
  mapYear = y;
  const built = ["<=", ["get", "y"], y];
  map.setFilter("streets", built);
  map.setFilter("streets-edge", built);
  map.setFilter("street-labels", built);
  map.setFilter("forest", [">", ["get", "y"], y]);
  map.setFilter("sites", built);
  map.setFilter("sites-edge", built);
  const running = ["all", built, [">", ["get", "end"], y]];
  map.setFilter("rail", running);
  map.setFilter("rail-ties", running);
  for (const kind of Object.keys(PLACE_STYLE)) {
    map.setFilter(`places-${kind}`, ["all", ["==", ["get", "kind"], kind], ["<=", ["get", "from"], y], [">", ["get", "to"], y]]);
  }
}

const fade = (year, [from, to]) => Math.min(1, Math.max(0, (year - from) / (to - from)));

// Sets the water for this year and returns the name of the map it comes from, or null once
// today's shore is in place.
function updateWater(year) {
  if (!map.getLayer("water-common")) return null;
  const steps = water.steps;
  let i = 0;
  while (i + 1 < steps.length && steps[i + 1].year <= year) i++;
  const cur = steps[i], next = steps[i + 1];
  let k;
  if (next) {
    const span = Math.min(SHORE_BLEND, next.year - cur.year);
    k = Math.max(0, (year - (next.year - span)) / span);
  } else {
    k = fade(year, water.modernFade);
  }
  if (i !== waterStep) {
    waterStep = i;
    for (const part of ["common", "lost", "gained"]) map.getSource(`water-${part}`).setData(cur[part]);
  }
  map.setPaintProperty("water-lost", "fill-opacity", 1 - k);
  map.setPaintProperty("water-gained", "fill-opacity", k);
  map.setPaintProperty("marsh", "fill-opacity", 1 - fade(year, water.marshFade));
  map.setPaintProperty("islandLand", "fill-opacity", 1 - fade(year, water.islandLandFade));
  map.setPaintProperty("barLand", "fill-opacity", 1 - fade(year, water.modernFade));
  if (!next) return k < 1 ? cur.source : null;
  return k > 0.5 ? next.source : cur.source;
}

function render() {
  const y = Math.floor(state.year);
  const shore = updateWater(state.year);
  updateMap(state.year);
  overlay.setProps({ layers: [...(lost ? [lostLayer()] : []), buildingLayer(), ...landmarkLayers()] });
  writeHash();

  $("year-label").textContent = String(y);
  $("population-value").textContent = populationAt(state.year);
  $("standing").textContent = `${countStanding(y).toLocaleString("en-CA")} of today's buildings standing`;
  const note = $("shoreline-note");
  note.hidden = !shore;
  if (shore) note.textContent = `Historic shoreline of Lake Ontario (${shore})`;
  if (document.activeElement !== $("slider") || state.playing) $("slider").value = String(state.year);
}

function populationAt(year) {
  if (year < population[0][0]) return "—";
  for (let i = 1; i < population.length; i++) {
    const [y0, p0] = population[i - 1];
    const [y1, p1] = population[i];
    if (year <= y1) return Math.round(p0 + ((p1 - p0) * (year - y0)) / (y1 - y0)).toLocaleString("en-CA");
  }
  return population[population.length - 1][1].toLocaleString("en-CA");
}

// years.bin is sorted, so the number standing is a binary search
function countStanding(year) {
  let lo = 0, hi = years.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (years[mid] <= year) lo = mid + 1; else hi = mid;
  }
  return lo;
}

function setPlaying(on) {
  if (on) pauseStory();
  state.playing = on;
  $("play").textContent = on ? "❚❚" : "▶";
  $("play").setAttribute("aria-label", on ? "Pause" : "Play");
  if (!on) return;
  if (state.year >= meta.lastYear) state.year = meta.firstYear;
  let last = performance.now();
  const tick = (now) => {
    if (!state.playing) return;
    state.year = Math.min(meta.lastYear, state.year + Math.min(0.1, (now - last) / 1000) * state.speed);
    last = now;
    cardFollowsYear();
    render();
    if (state.year >= meta.lastYear) return setPlaying(false);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function setupControls() {
  const slider = $("slider");
  slider.min = String(meta.firstYear);
  slider.max = String(meta.lastYear);
  slider.value = String(state.year);
  slider.addEventListener("input", () => { pauseStory(); state.year = Number(slider.value); cardFollowsYear(); render(); });
  $("play").addEventListener("click", () => setPlaying(!state.playing));
  $("speed").addEventListener("change", (e) => { state.speed = Number(e.target.value); });
  $("quality").addEventListener("click", () => {
    state.quality = !state.quality;
    $("quality").setAttribute("aria-pressed", String(state.quality));
    $("legend").hidden = !state.quality;
    render();
  });
  $("legend").innerHTML = meta.tiers.map((t) =>
    `<div><span class="swatch" style="background:rgb(${TIER_COLORS[t].join(",")})"></span>${TIER_LABELS[t]}` +
    `<span class="count">${(meta.countsByTier[t] ?? 0).toLocaleString("en-CA")}</span></div>`).join("") +
    (lost ? `<div><span class="swatch" style="background:rgb(${LOST_COLOR.join(",")})"></span>Lost building, from fire insurance plans` +
      `<span class="count">${lost.count.toLocaleString("en-CA")}</span></div>` : "");

  const span = meta.lastYear - meta.firstYear;
  stops.forEach((s, i) => {
    const tick = document.createElement("div");
    tick.className = "tick";
    tick.style.left = `${((s.year - meta.firstYear) / span) * 100}%`;
    tick.title = `${s.year} · ${s.title}`;
    tick.addEventListener("click", () => openStop(i, false));
    $("event-ticks").appendChild(tick);
  });
  $("story-toggle").addEventListener("click", () => {
    if (story.index >= 0) return closeStory();
    // start from the last stop at or before the year on screen
    let i = 0;
    while (i + 1 < stops.length && stops[i + 1].year <= state.year) i++;
    openStop(state.year >= meta.lastYear ? 0 : i, true);
  });
  $("story-close").addEventListener("click", closeStory);
  $("story-prev").addEventListener("click", () => openStop(Math.max(0, story.index - 1), story.playing));
  $("story-next").addEventListener("click", () => openStop(Math.min(stops.length - 1, story.index + 1), story.playing));
  $("story-play").addEventListener("click", () => {
    if (!story.playing) return openStop(story.index, true);
    // keep the run going so the year still arrives at the stop's year
    story.playing = false;
    map.stop();
    syncStoryButton();
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "SELECT") return;
    if (e.code === "Space") {
      e.preventDefault();
      if (story.index >= 0) $("story-play").click(); else setPlaying(!state.playing);
    }
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      if (document.activeElement === slider) return;
      const step = e.key === "ArrowRight" ? 1 : -1;
      if (story.index >= 0) return $(step > 0 ? "story-next" : "story-prev").click();
      state.year = Math.max(meta.firstYear, Math.min(meta.lastYear, Math.floor(state.year) + step));
      cardFollowsYear();
      render();
    }
  });
}

// Show a story stop: fly the camera there while the year runs to the stop's year.
// With autoplay, the camera then turns slowly for as long as the card takes to read, the year
// runs on to the stop's end year if it has one, and the next stop follows.
function openStop(i, autoplay) {
  setPlaying(false);
  const s = stops[i];
  const run = ++story.run;
  story.index = i;
  story.playing = autoplay;
  $("story").hidden = false;
  $("info").hidden = true;
  $("story-toggle").setAttribute("aria-pressed", "true");
  fillCard(i);
  syncStoryButton();
  const fly = flyMs(s);
  const read = readMs(s.text);
  const view = { center: [s.lon, s.lat], zoom: s.zoom, bearing: s.bearing, pitch: s.pitch };
  if (fly) map.flyTo({ ...view, duration: fly, essential: true }); else map.jumpTo(view);

  const from = state.year;
  const start = performance.now();
  let arrived = 0;
  const frame = (now) => {
    if (run !== story.run) return;
    if (!arrived) {
      const k = fly ? Math.min(1, (now - start) / fly) : 1;
      state.year = from + (s.year - from) * (k * k * (3 - 2 * k));
      render();
      if (k >= 1) {
        arrived = now;
        if (story.playing && s.orbit && !reducedMotion) {
          map.easeTo({ bearing: s.bearing + s.orbit, duration: read, easing: (t) => t, essential: true });
        }
      }
    } else if (story.playing) {
      const k = Math.min(1, (now - arrived) / read);
      if (s.yearEnd > s.year) {
        state.year = s.year + (s.yearEnd - s.year) * k;
        render();
      }
      $("story-progress").firstElementChild.style.width = `${k * 100}%`;
      if (k >= 1) {
        if (i + 1 < stops.length) return openStop(i + 1, true);
        story.playing = false;
        return syncStoryButton();
      }
    }
    if (arrived && !story.playing) return;
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

function fillCard(i) {
  const s = stops[i];
  story.index = i;
  $("story-count").textContent = `${i + 1} / ${stops.length}`;
  $("story-title").textContent = s.title;
  $("story-text").textContent = s.text;
  $("story-source").href = s.url;
  $("story-progress").firstElementChild.style.width = "0";
  document.querySelectorAll("#event-ticks .tick").forEach((t, k) => t.classList.toggle("current", k === i));
}

// When the year is moved with the slider or the play button while the card is open,
// the card shows the last stop at or before that year. The camera stays where it is.
function cardFollowsYear() {
  if (story.index < 0) return;
  let i = 0;
  while (i + 1 < stops.length && stops[i + 1].year <= state.year) i++;
  if (i !== story.index) fillCard(i);
}

function syncStoryButton() {
  $("story-play").textContent = story.playing ? "❚❚" : "▶";
  $("story-play").setAttribute("aria-label", story.playing ? "Pause story" : "Play story");
}

// stops the card advancing and the year sweep; the card stays open
function pauseStory() {
  story.run++;
  if (story.playing) map.stop();
  story.playing = false;
  syncStoryButton();
}

function closeStory() {
  pauseStory();
  story.index = -1;
  $("story").hidden = true;
  $("story-toggle").setAttribute("aria-pressed", "false");
  document.querySelectorAll("#event-ticks .tick.current").forEach((t) => t.classList.remove("current"));
}

function showBuilding(info) {
  if (info.picked && info.layer?.id.startsWith("landmark-")) {
    const fact = FACTS[info.object.key];
    return showInfo(fact.name, [...fact.rows, ["More", `<a href="${fact.url}" target="_blank" rel="noopener">article</a>`]]);
  }
  if (!info.picked || info.index < 0 || !["buildings", "lost"].includes(info.layer?.id)) {
    $("info").hidden = true;
    return;
  }
  const i = info.index;
  if (info.layer.id === "lost") {
    const [brick, plan, estimated] = lost.about.subarray(i * 3, i * 3 + 3);
    const [built, gone, kept, stays] = lost.span.subarray(i * 4, i * 4 + 4);
    // a piece that takes over from the plan before, or hands over to the next, has no date of its own
    const known = lost.names?.[i];
    return showInfo(known?.name ?? "Lost building", [
      [kept ? "Standing by" : "Built about", built],
      [stays ? "Still standing in" : "Gone about", gone],
      ["Outline from", `the ${lost.plans[plan]} plan`],
      ["Material", brick ? "brick" : "wood"],
      ["Source", `Goad's fire insurance plans. Outline and material are from the plan; ${known ? "the years are from the article" : estimated ? "a year here is an estimate" : "the years lie between plan years"}; the height is assumed.`],
      ...(known?.url ? [["More", `<a href="${escapeHtml(known.url)}" target="_blank" rel="noopener">article</a>`]] : []),
    ]);
  }
  const tier = meta.tiers[tiers[i]];
  const named = names[i];
  const rows = [
    [tier === "estimate" ? "Built about" : "Built", years[i]],
    ["Source", TIER_LABELS[tier]],
    ["Height", `${Math.round(heights[i])} m`],
  ];
  if (named?.url) rows.push(["More", `<a href="${escapeHtml(named.url)}" target="_blank" rel="noopener">article</a>`]);
  // the name if it has one, otherwise the street address
  const address = addresses[i];
  if (named?.name && address) rows.unshift(["Address", address]);
  showInfo(named?.name ?? (address || "Building"), rows);
}

function showInfo(title, rows) {
  const box = $("info");
  box.hidden = false;
  box.innerHTML = `<button class="close" aria-label="Close">✕</button><h3>${escapeHtml(title)}</h3><table>` +
    rows.map(([k, v]) => `<tr><td>${k}</td><td>${typeof v === "string" && v.startsWith("<a ") ? v : escapeHtml(String(v))}</td></tr>`).join("") +
    "</table>";
  box.querySelector(".close").addEventListener("click", () => { box.hidden = true; });
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

load();

// handles for debugging from the console
window.__map = map;
window.__state = state;
window.__story = story;
