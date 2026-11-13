import maplibregl from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { COORDINATE_SYSTEM } from "@deck.gl/core";
import { SolidPolygonLayer } from "@deck.gl/layers";
import { SimpleMeshLayer } from "@deck.gl/mesh-layers";
import { TimeExtension } from "./time.js";
import { landmarkParts, FACTS } from "./landmarks.js";
import { fetchPacked, fetchMetres, fetchStarts, fetchPositions } from "./pack.js";
import { loadTrees, treeMesh, TREE_COLORS } from "./trees.js";
import { SunEffect, today, sunAt, clock } from "./sun.js";
import { loadRoofs, roofMesh } from "./roofs.js";

const $ = (id) => document.getElementById(id);
const DATA = "./data/";
// A building takes this many years to rise, and fades from the highlight colour to the
// plain one by the time it is NEW_SPAN years old.
const RISE_YEARS = 1.5;
const NEW_SPAN = 6;
const OLD_COLOR = [214, 205, 190];
const NEW_COLOR = [217, 84, 43];
const NEW_TINT = NEW_COLOR.map((c, i) => c / OLD_COLOR[i]);
// The light is the sun over Toronto today, at the time of day on the sun slider: the time it is
// now, or mid-afternoon when the sun is down.
// Cast shadows are written but switched off. With them on (true), clicking a building finds
// nothing (deck.gl's picking comes back empty once its shadow module is in the shaders) and the
// frame rate about halves; neither is solved. See sun.js.
const SHADOWS = false;
const day = today();
const sun = { minute: day.now >= day.first && day.now <= day.last ? day.now : Math.min(day.last, 15 * 60), live: true };
Object.assign(sun, sunAt(day, sun.minute));
const LIGHTING = new SunEffect(sun, SHADOWS);
// with shadows the sides away from the sun are darkened by the shadow; without, by less light
const MATERIAL = { ambient: SHADOWS ? 0.72 : 0.56, diffuse: 0.5, shininess: 8, specularColor: [0, 0, 0] };
const riseExtension = new TimeExtension({ mode: "rise", shadows: SHADOWS });
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
    // paint changes at once: the year sets every opacity itself, frame by frame
    transition: { duration: 0, delay: 0 },
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
  // smooth edges on the buildings
  canvasContextAttributes: { antialias: true },
  minZoom: 9,
  maxZoom: 19,
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
map.on("moveend", writeHash);
// A tip beside the zoom buttons on how to turn the map, until the visitor has turned it once.
function hintRotate() {
  const seen = () => { try { return localStorage.getItem("rotated"); } catch { return null; } };
  if (seen()) return;
  const hint = document.getElementById("rotate-hint");
  hint.textContent = window.matchMedia?.("(pointer: coarse)").matches ? "Twist with two fingers to rotate" : "Right-drag to rotate and tilt";
  hint.hidden = false;
  map.once("rotate", () => { hint.hidden = true; try { localStorage.setItem("rotated", "1"); } catch { /* private window */ } });
}
hintRotate();
// the trees come and go with the zoom
let treesOn = 0;
map.on("zoom", () => { if (meta && treeSets() !== treesOn) render(); });
// and so do the batches of buildings, with the view
let drawn = "";
map.on("move", () => { if (buildings && drawnKey() !== drawn) render(); });
// taking hold of the map stops the story from moving it
for (const type of ["mousedown", "wheel", "touchstart"]) {
  map.getCanvasContainer().addEventListener(type, () => {
    if (!story.playing) return;
    story.playing = false;
    map.stop();
    syncStoryButton();
  }, { passive: true });
}

const overlay = new MapboxOverlay({ interleaved: true, layers: [], effects: [LIGHTING], onClick: showBuilding });
map.addControl(overlay);
// What the sun sees is drawn before the map starts on its frame (sun.js). The map has no hook
// there, so its painter is wrapped; it is told afterwards that the drawing state has changed.
if (SHADOWS) {
  const paint = map.painter.render.bind(map.painter);
  map.painter.render = (...args) => {
    if (LIGHTING.drawEarly(overlay._deck, map, { nearZ: map.transform.nearZ, farZ: map.transform.farZ })) map.painter.context.setDirty();
    return paint(...args);
  };
}

// Trees are today's only: they grow in over the last TREE_YEARS of the slider. A quarter of them
// show from the first zoom of TREE_ZOOMS, half from the second and all from the third; while some
// are left out, the others are drawn larger.
const TREE_YEARS = 1;
const TREE_ZOOMS = [13, 14.5, 15.5];
const TREE_LARGER = [1.5, 1.25, 1];
const TREE_MESH = treeMesh();
let trees = null;
// Sloped roofs of the houses. They come in ROOF_SETS sets in order of their year. A set whose
// houses are all older than NEW_SPAN is drawn as it is; the roofs of newer houses are drawn apart,
// rising and losing their colour with the walls below them.
const ROOF_MESH = roofMesh();
const ROOF_COLOR = [176, 163, 150];
const ROOF_SETS = 12;
let roofs = null;
// the rise of the roof on a building (m), for the height in its card
const roofRise = new Map();
let meta, buildings, years, heights, tiers, names, water, population, stops, streets, streetLabels, places, area, rail, sites, forest, parks, lost, addresses, landmarks;
// buildings of the city's model that a hand-built landmark stands in for
const replaced = new Set();

// Buildings are drawn in batches: those that stand at about the same time in the same part of the
// city. A year and a view then only cost the batches standing in that year and lying in that view,
// which matters because every building is drawn a second time for the shadows.
// groups: [{ ids (building numbers), since, until }], split here by where the buildings are.
// starts and positions are the packed polygons, `size` numbers per corner.
const TILES = [5, 3];   // across and up
function batches(groups, starts, positions, size) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i < positions.length; i += size) {
    x0 = Math.min(x0, positions[i]); x1 = Math.max(x1, positions[i]);
    y0 = Math.min(y0, positions[i + 1]); y1 = Math.max(y1, positions[i + 1]);
  }
  const out = [];
  for (const group of groups) {
    const tiles = Array.from({ length: TILES[0] * TILES[1] }, () => []);
    for (const id of group.ids) {
      const tx = Math.min(TILES[0] - 1, Math.floor(((positions[starts[id] * size] - x0) / (x1 - x0)) * TILES[0]));
      const ty = Math.min(TILES[1] - 1, Math.floor(((positions[starts[id] * size + 1] - y0) / (y1 - y0)) * TILES[1]));
      tiles[ty * TILES[0] + tx].push(id);
    }
    for (const ids of tiles) {
      if (!ids.length) continue;
      const startIndices = new Uint32Array(ids.length + 1);
      ids.forEach((id, i) => { startIndices[i + 1] = startIndices[i] + starts[id + 1] - starts[id]; });
      const value = new Float32Array(startIndices[ids.length] * size);
      ids.forEach((id, i) => value.set(positions.subarray(starts[id] * size, starts[id + 1] * size), startIndices[i] * size));
      // the box around the batch, in degrees from the map's origin
      const box = [Infinity, Infinity, -Infinity, -Infinity];
      for (let i = 0; i < value.length; i += size) {
        box[0] = Math.min(box[0], value[i]); box[2] = Math.max(box[2], value[i]);
        box[1] = Math.min(box[1], value[i + 1]); box[3] = Math.max(box[3], value[i + 1]);
      }
      out.push({ key: out.length, ids: Uint32Array.from(ids), since: group.since, until: group.until, box,
        data: { length: ids.length, startIndices, attributes: { getPolygon: { value, size } } } });
    }
  }
  return out;
}

// The batches standing in the year and in view. Buildings beyond the edge of the view still
// throw shadows into it, so the view is taken wider by MARGIN degrees (about 500 m).
const MARGIN = 0.005;
function inView(list) {
  const b = map.getBounds();
  const [ox, oy] = meta.origin;
  const w = b.getWest() - ox - MARGIN, e = b.getEast() - ox + MARGIN, s = b.getSouth() - oy - MARGIN, n = b.getNorth() - oy + MARGIN;
  return list.filter((t) => t.since <= state.year && state.year < t.until && t.box[0] <= e && t.box[2] >= w && t.box[1] <= n && t.box[3] >= s);
}
// which batches are drawn, to see when moving the map changes them
const drawnKey = () => [buildings, lost?.batches ?? []].map((list) => inView(list).map((t) => t.key).join(",")).join("|");

const BUILT_GROUPS = 5;

async function load() {
  meta = await fetchJson("meta.json");
  const [starts, bases] = await Promise.all([fetchStarts(DATA + "counts.pack"), fetchMetres(DATA + "bases.pack")]);
  const positions = await fetchPositions(DATA + "positions.pack", starts, bases);
  [years, heights, tiers, names, water, population, stops, streets, streetLabels, places, area, rail, sites, forest, parks] = await Promise.all([
    fetchPacked(DATA + "years.pack", Uint16Array),
    fetchMetres(DATA + "heights.pack"),
    fetchPacked(DATA + "tiers.pack", Uint8Array),
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
  // today's buildings are in order of their year: groups of about as many corners each
  const groups = [];
  for (let k = 0, from = 0; k < BUILT_GROUPS; k++) {
    let to = from;
    while (to < meta.count && starts[to] < (starts[meta.count] * (k + 1)) / BUILT_GROUPS) to++;
    if (k === BUILT_GROUPS - 1) to = meta.count;
    if (to > from) groups.push({ ids: Uint32Array.from({ length: to - from }, (_, i) => from + i), since: years[from], until: Infinity });
    from = to;
  }
  buildings = batches(groups, starts, positions, 3);
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
  roofs = await loadRoofs(DATA).catch(() => null);
  if (roofs) for (let i = 0; i < roofs.length; i++) roofRise.set(roofs.ids[i], roofs.size[i * 5 + 3]);
  // the trees come after everything else; the page does not wait for them
  loadTrees(DATA).then((t) => { trees = t; render(); }).catch(() => {});
}

// Buildings that are gone, read off the fire insurance plans. Absent if lost.json is.
async function loadLost() {
  const info = await fetch(DATA + "lost.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (!info) return null;
  const [positions, starts, span, tall, about] = await Promise.all([
    fetchPositions(DATA + "lost.positions.pack"),
    fetchStarts(DATA + "lost.counts.pack"),
    fetchPacked(DATA + "lost.years.pack", Uint16Array),
    fetchMetres(DATA + "lost.heights.pack"),
    fetchPacked(DATA + "lost.info.pack", Uint8Array),
  ]);
  // groups of lost buildings that went at about the same time and, within those, came at about
  // the same time
  const order = Uint32Array.from({ length: info.count }, (_, i) => i).sort((a, b) => span[a * 4 + 1] - span[b * 4 + 1]);
  const GONE = 4, BUILT = 2, groups = [];
  for (let g = 0; g < GONE; g++) {
    const g0 = Math.floor((info.count * g) / GONE), g1 = Math.floor((info.count * (g + 1)) / GONE);
    order.subarray(g0, g1).sort((a, b) => span[a * 4] - span[b * 4]);
    for (let k = 0; k < BUILT; k++) {
      const ids = order.slice(g0 + Math.floor(((g1 - g0) * k) / BUILT), g0 + Math.floor(((g1 - g0) * (k + 1)) / BUILT));
      if (!ids.length) continue;
      let until = 0;
      for (const id of ids) until = Math.max(until, span[id * 4 + 1]);
      groups.push({ ids, since: span[ids[0] * 4], until });
    }
  }
  return { ...info, span, tall, about, batches: batches(groups, starts, positions, 2) };
}

function lostLayers() {
  return inView(lost.batches).map((b) => new SolidPolygonLayer({
    id: `lost-${b.key}`,
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: b.data,
    positionFormat: "XY",
    coordinateSystem: COORDINATE_SYSTEM.LNGLAT_OFFSETS,
    coordinateOrigin: meta.origin,
    _normalize: false,
    _windingOrder: "CCW",
    extruded: true,
    getElevation: (_, { index }) => lost.tall[b.ids[index]],
    getFillColor: state.quality ? LOST_COLOR : OLD_COLOR,
    updateTriggers: { getFillColor: state.quality },
    material: MATERIAL,
    pickable: true,
    autoHighlight: true,
    highlightColor: [255, 255, 255, 90],
    getYears: (_, { index, target }) => { for (let k = 0; k < 4; k++) target[k] = lost.span[b.ids[index] * 4 + k]; return target; },
    currentYear: state.year,
    growYears: RISE_YEARS,
    tint: state.quality ? [1, 1, 1] : NEW_TINT,
    tintYears: NEW_SPAN,
    sunDirection: sun.direction,
    extensions: [riseExtension],
  }));
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
    material: MATERIAL,
    pickable: true,
  }));
}

// Roofs [from, to) as one layer. `settled` roofs are full height and plain; the others follow the
// year the way the walls do (time.js).
function roofLayer(id, from, to, settled) {
  const year = (i) => years[roofs.ids[from + i]];
  const grown = (i) => {
    const k = Math.min(1, Math.max(0, (state.year - year(i)) / RISE_YEARS));
    return Math.max(0.02, k * k * (3 - 2 * k));
  };
  return new SimpleMeshLayer({
    id,
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: { length: to - from },
    mesh: ROOF_MESH,
    coordinateSystem: COORDINATE_SYSTEM.LNGLAT_OFFSETS,
    coordinateOrigin: meta.origin,
    getPosition: (_, { index, target }) => {
      const k = from + index;
      target[0] = roofs.positions[k * 2]; target[1] = roofs.positions[k * 2 + 1];
      target[2] = roofs.size[k * 5 + 2] * (settled ? 1 : grown(index));
      return target;
    },
    getScale: (_, { index }) => {
      const k = (from + index) * 5;
      return [roofs.size[k], roofs.size[k + 1], roofs.size[k + 3] * (settled ? 1 : grown(index))];
    },
    getOrientation: (_, { index }) => [0, roofs.size[(from + index) * 5 + 4], 0],
    getColor: settled || state.quality ? ROOF_COLOR : (_, { index }) => {
      const k = Math.min(1, Math.max(0, (state.year - year(index) - RISE_YEARS) / (NEW_SPAN - RISE_YEARS)));
      return ROOF_COLOR.map((c, n) => c * (NEW_TINT[n] + (1 - NEW_TINT[n]) * k));
    },
    updateTriggers: settled ? {} : { getPosition: state.year, getScale: state.year, getColor: [state.year, state.quality] },
    material: MATERIAL,
  });
}

function roofLayers() {
  // roofs are in order of their year: the first `standing` of them have their house
  let lo = 0, standing = roofs.length;
  while (lo < standing) { const mid = (lo + standing) >> 1; if (years[roofs.ids[mid]] <= state.year) lo = mid + 1; else standing = mid; }
  const layers = [];
  let from = 0;
  for (let k = 0; k < ROOF_SETS; k++) {
    const to = Math.floor((roofs.length * (k + 1)) / ROOF_SETS);
    if (to > standing || years[roofs.ids[to - 1]] > state.year - NEW_SPAN) break;
    layers.push(roofLayer(`roofs-${k}`, from, to, true));
    from = to;
  }
  if (standing > from) layers.push(roofLayer("roofs-new", from, standing, false));
  return layers;
}

// how many of the three sets of trees show
function treeSets() {
  if (!trees || state.year <= meta.lastYear - TREE_YEARS) return 0;
  return TREE_ZOOMS.filter((z) => map.getZoom() >= z).length;
}

function treeLayers() {
  const sets = treeSets();
  const grown = Math.min(1, (state.year - (meta.lastYear - TREE_YEARS)) / TREE_YEARS);
  return trees.slice(0, sets).map((set, i) => new SimpleMeshLayer({
    id: `trees-${i}`,
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: set,
    mesh: TREE_MESH,
    coordinateSystem: COORDINATE_SYSTEM.LNGLAT_OFFSETS,
    coordinateOrigin: meta.origin,
    getPosition: (_, { index, target }) => {
      target[0] = set.positions[index * 2]; target[1] = set.positions[index * 2 + 1]; target[2] = 0;
      return target;
    },
    getScale: (_, { index }) => { const r = set.sizes[index] / 10; return [r, r, r]; },
    getColor: (_, { index }) => TREE_COLORS[(index * 7919) % TREE_COLORS.length],
    sizeScale: grown * TREE_LARGER[sets - 1],
    material: MATERIAL,
  }));
}

// An unseen sheet over the ground, which takes the shadows of the buildings and trees.
function groundLayer() {
  return new SolidPolygonLayer({
    id: "ground",
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: [[[-79.7, 43.5], [-79.1, 43.5], [-79.1, 43.85], [-79.7, 43.85]]],
    getPolygon: (d) => d,
    getFillColor: [0, 0, 0, 0],
    material: false,
    parameters: { depthWriteEnabled: false },
  });
}

function buildingLayers() {
  return inView(buildings).map((b) => new SolidPolygonLayer({
    id: `buildings-${b.key}`,
    // drawn inside the map, over the street names and under the place names
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: b.data,
    coordinateSystem: COORDINATE_SYSTEM.LNGLAT_OFFSETS,
    coordinateOrigin: meta.origin,
    _normalize: false,
    _windingOrder: "CCW",
    extruded: true,
    getElevation: (_, { index }) => heights[b.ids[index]],
    getFillColor: state.quality ? (_, { index }) => TIER_COLORS[meta.tiers[tiers[b.ids[index]]]] : OLD_COLOR,
    updateTriggers: { getFillColor: state.quality },
    material: MATERIAL,
    pickable: true,
    autoHighlight: true,
    highlightColor: [255, 255, 255, 90],
    getYears: (_, { index, target }) => {
      const id = b.ids[index];
      target[0] = replaced.has(id) ? 9999 : years[id];
      target[1] = 9999; target[2] = 0; target[3] = 0;
      return target;
    },
    currentYear: state.year,
    growYears: RISE_YEARS,
    tint: state.quality ? [1, 1, 1] : NEW_TINT,
    tintYears: NEW_SPAN,
    sunDirection: sun.direction,
    extensions: [riseExtension],
  }));
}

// Each mapped shore blends into the next over the years before the next map, this many at most.
const SHORE_BLEND = 2;
const WATER_PARTS = ["common", "lost", "gained"];
// opacity last set on each layer, so that only changes go to the map
const opacities = {};
function setOpacity(layer, value) {
  if (opacities[layer] === value) return;
  opacities[layer] = value;
  map.setPaintProperty(layer, "fill-opacity", value);
}

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
// water gained by it. Every step has its own layers, all loaded at the start and shown by opacity:
// swapping the data of one set of layers showed the next step's water for a moment.
function addMapLayers() {
  // Today's parks, then the forest not yet cleared, both under today's ponds and rivers: a park
  // is forest until the land around it is cleared and stays green after.
  map.addSource("parks", { type: "geojson", data: parks });
  map.addLayer({ id: "parks", type: "fill", source: "parks", paint: { "fill-color": PARK_COLOR } }, "water");
  map.addSource("forest", { type: "geojson", data: forest });
  map.addLayer({ id: "forest", type: "fill", source: "forest", paint: { "fill-color": FOREST_COLOR } }, "water");
  // Hides today's water in the harbour, the lower Don and around the Island, so that only the
  // water of the year shows there; it is painted on top.
  map.addSource("old-land", { type: "geojson", data: water.land });
  map.addLayer({ id: "old-land", type: "fill", source: "old-land", paint: { "fill-color": LAND_COLOR } });
  map.addSource("marsh", { type: "geojson", data: water.marsh });
  map.addLayer({ id: "marsh", type: "fill", source: "marsh", paint: { "fill-color": MARSH_COLOR } });
  water.steps.forEach((step, i) => {
    for (const part of WATER_PARTS) {
      map.addSource(`water-${i}-${part}`, { type: "geojson", data: step[part] });
      map.addLayer({ id: `water-${i}-${part}`, type: "fill", source: `water-${i}-${part}`,
        paint: { "fill-color": WATER_COLOR, "fill-opacity": 0 } });
    }
  });
  for (const k of Object.keys(opacities)) delete opacities[k];

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
  if (!map.getLayer("water-0-common")) return null;
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
  steps.forEach((_, j) => {
    setOpacity(`water-${j}-common`, j === i ? 1 : 0);
    setOpacity(`water-${j}-lost`, j === i ? 1 - k : 0);
    setOpacity(`water-${j}-gained`, j === i ? k : 0);
  });
  setOpacity("marsh", 1 - fade(year, water.marshFade));
  setOpacity("old-land", 1 - fade(year, water.modernFade));
  if (!next) return k < 1 ? cur.source : null;
  return k > 0.5 ? next.source : cur.source;
}

function render() {
  const y = Math.floor(state.year);
  const shore = updateWater(state.year);
  updateMap(state.year);
  overlay.setProps({ layers: [...(SHADOWS ? [groundLayer()] : []), ...(lost ? lostLayers() : []), ...buildingLayers(), ...(roofs ? roofLayers() : []), ...landmarkLayers(), ...(trees ? treeLayers() : [])] });
  treesOn = treeSets();
  drawn = drawnKey();
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

// The sun slider: the time of day, today, between sunrise and sunset. Left alone it follows the clock.
function setSun(minute, live) {
  Object.assign(sun, sunAt(day, minute), { minute, live });
  LIGHTING.setSun(sun);
  $("sun-time").textContent = clock(minute);
  $("sun-slider").value = String(minute);
  $("sun-now").hidden = live;
  render();
}

function setupSun() {
  const slider = $("sun-slider");
  slider.min = String(day.first);
  slider.max = String(day.last);
  slider.addEventListener("input", () => setSun(Number(slider.value), false));
  const now = () => { const t = today().now; return t >= day.first && t <= day.last ? t : null; };
  $("sun-now").addEventListener("click", () => setSun(now() ?? sun.minute, true));
  setInterval(() => { if (sun.live && now() !== null && now() !== sun.minute) setSun(now(), true); }, 30000);
  setSun(sun.minute, true);
  $("sun").hidden = false;
}

function setupControls() {
  setupSun();
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
  const [kind, key] = (info.layer?.id ?? "").split("-");
  if (!info.picked || info.index < 0 || !["buildings", "lost"].includes(kind)) {
    $("info").hidden = true;
    return;
  }
  // the building's place in the batch, back to its number
  const i = (kind === "lost" ? lost.batches : buildings)[Number(key)].ids[info.index];
  if (kind === "lost") {
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
    ["Height", `${Math.round(heights[i] + (roofRise.get(i) ?? 0))} m`],
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
window.__lighting = LIGHTING;
window.__overlay = overlay;
