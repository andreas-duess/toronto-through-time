import maplibregl from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { COORDINATE_SYSTEM } from "@deck.gl/core";
import { SolidPolygonLayer, IconLayer } from "@deck.gl/layers";
import { SimpleMeshLayer } from "@deck.gl/mesh-layers";
import { TimeExtension } from "./time.js";
import { landmarkParts, FACTS } from "./landmarks.js";
import { fetchPacked, fetchMetres, fetchStarts, fetchPositions } from "./pack.js";
import { loadTrees, treeMesh, TREE_COLORS } from "./trees.js";
import { SunEffect, today, sunAt, clock } from "./sun.js";
import { loadRoofs, roofMesh } from "./roofs.js";
import { watchTransit, transitNow, transitName, boxMesh } from "./transit.js";
import { watchBikes, bikeStations } from "./bikes.js";
import { watchPlanes, planesNow, planeMesh } from "./planes.js";
import { weather, watchWeather, fall } from "./weather.js";
import { loadPhotos, photoPins, photo, cameraIcon } from "./photos.js";
import { loadDistricts, districtCells } from "./districts.js";

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
  landmark: "Well-known building. The year is from an article about it.",
  heritage: "The year is from the city's list of heritage buildings.",
  apartment: "The year is from the city's apartment records.",
  massing: "Built since 2016. The year is when it first showed up in the city's 3D model.",
  permit: "The year is from its building permit.",
  estimate: "Best guess, from the age of the area and the buildings around it.",
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
// voice: whether the story is read aloud; narration: the sound of the stop being read, if any
const story = { index: -1, playing: false, run: 0, voice: true, narration: null, files: [], sound: null, left: null };
// A few stops have a sound under the voice (a battle, a fire, hooves): quiet, in a loop, fading in and out.
const SOUND_LEVEL = 0.16;
// some louder, some softer
const SOUND_LEVELS = { fire: 0.34, storm: 0.13, lastpost: 0.15, cheer: 0.09, toast: 0.11,
  // one stop apart from the others that share its sound: "<sound>@<year of the stop>"
  "cheer@1867": 0.072 };
// heard for this many seconds only, then faded out
const SOUND_SECONDS = { building: 9, boo: 5, lastpost: 9 };
// started only when the voice is this far through the stop (0 to 1)
const SOUND_FROM = { bell: 0.72, boo: 0.42, lastpost: 0.6 };
// played once, not in a loop
const SOUND_ONCE = new Set(["lastpost"]);
function fadeSound(sound, to, ms, then) {
  const from = sound.volume, start = performance.now();
  const step = (now) => {
    // (a frame's time can lie a moment before `start`, and a volume below 0 is an error that would stop the fade)
    const k = Math.min(1, Math.max(0, (now - start) / ms));
    sound.volume = Math.min(1, Math.max(0, from + (to - from) * k));
    if (k < 1) requestAnimationFrame(step); else then?.();
  };
  requestAnimationFrame(step);
}
function hush() {
  // where the voice was stopped, so that the same stop picks up there again
  if (story.narration && !story.narration.ended) story.left = { index: story.index, time: story.narration.currentTime };
  story.narration?.pause();
  story.narration = null;
  const sound = story.sound;
  story.sound = null;
  if (sound) fadeSound(sound, 0, 600, () => sound.pause());
}
// Reads a stop aloud. Without sound (switched off, or the browser refuses) the story keeps its own time.
function narrate(i) {
  hush();
  // a stop that was paused goes on from a moment before where it stopped
  const from = story.left?.index === i ? Math.max(0, story.left.time - 1) : 0;
  story.left = null;
  if (!story.voice || !story.files[i]) return;
  const sound = new Audio(`./audio/${story.files[i]}`);
  if (from) sound.currentTime = from;
  story.narration = sound;
  sound.play().catch(() => { if (story.narration === sound) story.narration = null; });
  if (stops[i].sound) {
    const under = new Audio(`./audio/fx-${stops[i].sound}.mp3`);
    under.loop = !SOUND_ONCE.has(stops[i].sound);
    under.volume = 0;
    story.sound = under;
    const begin = () => {
      if (story.sound !== under || !under.paused) return;
      const seconds = SOUND_SECONDS[stops[i].sound];
      if (seconds) setTimeout(() => { if (story.sound === under) { story.sound = null; fadeSound(under, 0, 2500, () => under.pause()); } }, seconds * 1000);
      under.play().then(() => fadeSound(under, SOUND_LEVELS[`${stops[i].sound}@${stops[i].year}`] ?? SOUND_LEVELS[stops[i].sound] ?? SOUND_LEVEL, 1500)).catch(() => { if (story.sound === under) story.sound = null; });
    };
    const from = SOUND_FROM[stops[i].sound];
    if (!from) begin();
    else sound.addEventListener("timeupdate", () => { if (sound.duration && sound.currentTime / sound.duration >= from) begin(); });
    // it fades out as the voice ends
    sound.addEventListener("ended", () => { if (story.sound === under) { story.sound = null; fadeSound(under, 0, 1800, () => under.pause()); } });
  }
}
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
  minZoom: 8.5,
  maxZoom: 19,
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
map.on("moveend", writeHash);
// the districts outside the old city are loaded for wherever the map comes to rest
map.on("moveend", () => { if (meta && districts.some((d) => state.year >= d.from)) render(); });
// A tip beside the zoom buttons on how to turn the map. It stays.
{
  const hint = document.getElementById("rotate-hint");
  hint.textContent = window.matchMedia?.("(pointer: coarse)").matches ? "Twist with two fingers to rotate" : "Control-click and drag to rotate";
  hint.hidden = false;
}
// the trees come and go with the zoom
let treesOn = 0;
let bikesShown = false;
map.on("zoom", () => { if (meta && (treeSets() !== treesOn || transitOn() || planesOn() || bikesOn() || bikesShown || photosShow.on || poppiesOn() || live.chargers)) render(); });
// and so do the batches of buildings, with the view
let drawn = "";
map.on("move", () => { if (buildings && drawnKey() !== drawn) render(); });
// taking hold of the map stops the story from moving it
for (const type of ["mousedown", "wheel", "touchstart"]) {
  map.getCanvasContainer().addEventListener(type, () => {
    if (!story.playing) return;
    story.playing = false;
    hush();
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
// The TTC's buses and streetcars, in today's year only and from TRANSIT_ZOOM in. They are drawn at
// their true size close in and larger from further away, so that they can still be seen.
const BOX_MESH = boxMesh();
const TRANSIT_ZOOM = 12.5;
const TRUE_SIZE_ZOOM = 16;
const STREETCAR = { size: [30, 2.5, 3.4], color: [200, 32, 38] };
const BUS = { size: [12, 2.5, 3], color: [58, 74, 96] };
// the switches of the two live layers in the panel
const live = { transit: true, bikes: true, planes: true, weather: true, chargers: true };
const transitOn = () => live.transit && Boolean(meta) && state.year >= meta.lastYear - 0.05 && map.getZoom() >= TRANSIT_ZOOM && !document.hidden;
function transitLayer() {
  const larger = Math.max(1, 2 ** (TRUE_SIZE_ZOOM - map.getZoom()) * 0.75);
  return new SimpleMeshLayer({
    id: "transit",
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: transitNow(),
    mesh: BOX_MESH,
    getPosition: (v) => v.position,
    getOrientation: (v) => [0, 90 - v.heading, 0],
    getScale: (v) => (v.car ? STREETCAR : BUS).size,
    getColor: (v) => (v.car ? STREETCAR : BUS).color,
    sizeScale: larger,
    material: MATERIAL,
    pickable: true,
  });
}
// The buildings of Pearson airport (pipeline/pearson.py), in today's year: the terminals, hangars
// and the tower, drawn like the city's buildings.
let pearson = null;
function pearsonLayer() {
  return new SolidPolygonLayer({
    id: "pearson",
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: pearson,
    getPolygon: (b) => b.p,
    extruded: true,
    getElevation: (b) => b.h,
    getFillColor: OLD_COLOR,
    material: MATERIAL,
    getYears: [0, 9999, 1, 1],
    currentYear: state.year,
    growYears: RISE_YEARS,
    tint: [1, 1, 1],
    tintYears: NEW_SPAN,
    sunDirection: sun.direction,
    extensions: [riseExtension],
  });
}

// The districts outside the old city (districts.js): their buildings and roofs cell by cell, for
// the part of the map in view, from DISTRICT_ZOOM in; their streets and parks as map layers.
const DISTRICT_ZOOM = 11.5;
let districts = [];
function districtLayers() {
  if (map.getZoom() < DISTRICT_ZOOM) return [];
  const b = map.getBounds();
  const cells = districtCells(state.year, [b.getWest() - 0.01, b.getSouth() - 0.01, b.getEast() + 0.01, b.getNorth() + 0.01], render);
  const before = map.getLayer("places-city") ? "places-city" : undefined;
  return cells.flatMap((c) => [
    new SolidPolygonLayer({
      id: `district-${c.id}`,
      beforeId: before,
      data: c.data,
      coordinateSystem: COORDINATE_SYSTEM.LNGLAT_OFFSETS,
      coordinateOrigin: meta.origin,
      _normalize: false,
      _windingOrder: "CCW",
      extruded: true,
      getElevation: (_, { index }) => c.heights[index],
      getFillColor: OLD_COLOR,
      material: MATERIAL,
      getYears: (_, { index, target }) => { target[0] = c.years[index]; target[1] = 9999; target[2] = 1; target[3] = 0; return target; },
      currentYear: state.year,
      growYears: RISE_YEARS,
      tint: [1, 1, 1],
      tintYears: NEW_SPAN,
      sunDirection: sun.direction,
      extensions: [riseExtension],
    }),
    ...(c.roofs ? [new SimpleMeshLayer({
      id: `district-roofs-${c.id}`,
      beforeId: before,
      data: c.roofs,
      mesh: ROOF_MESH,
      coordinateSystem: COORDINATE_SYSTEM.LNGLAT_OFFSETS,
      coordinateOrigin: meta.origin,
      getPosition: (_, { index, target }) => { target[0] = c.roofs.middles[index * 2]; target[1] = c.roofs.middles[index * 2 + 1]; target[2] = c.roofs.size[index * 5 + 2]; return target; },
      getScale: (_, { index }) => [c.roofs.size[index * 5], c.roofs.size[index * 5 + 1], c.roofs.size[index * 5 + 3]],
      getOrientation: (_, { index }) => [0, c.roofs.size[index * 5 + 4], 0],
      getColor: roofColor(),
      updateTriggers: { getColor: weatherShown },
      material: MATERIAL,
    })] : []),
  ]);
}
// a district's streets and parks, added to the map the first time its years come up
function districtGround(year) {
  if (!map.getLayer("streets")) return;
  for (const d of districts) {
    const on = year >= d.from;
    if (on && !map.getSource(`d-${d.slug}-streets`)) {
      map.addSource(`d-${d.slug}-parks`, { type: "geojson", data: d.dir + "parks.json" });
      map.addLayer({ id: `d-${d.slug}-parks`, type: "fill", source: `d-${d.slug}-parks`, paint: { "fill-color": PARK_COLOR } }, "water");
      map.addSource(`d-${d.slug}-streets`, { type: "geojson", data: d.dir + "streets.json" });
      map.addLayer({ id: `d-${d.slug}-streets-edge`, type: "line", source: `d-${d.slug}-streets`, minzoom: 14,
        layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#d9d2c0", "line-width": streetWidth(1) } }, "rail");
      map.addLayer({ id: `d-${d.slug}-streets`, type: "line", source: `d-${d.slug}-streets`,
        layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": STREET_COLOR, "line-width": streetWidth(0.82) } }, "rail");
      map.addLayer({ id: `d-${d.slug}-labels`, type: "symbol", source: `d-${d.slug}-streets`, minzoom: 13.5, filter: ["!=", ["get", "name"], ""],
        layout: { "symbol-placement": "line", "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 13.5, 9.5, 17, 12.5], "symbol-spacing": 320, "symbol-sort-key": ["-", 0, ["get", "kind"]] },
        paint: { "text-color": "#7b7365", "text-halo-color": STREET_COLOR, "text-halo-width": 1.4 } }, "street-labels");
    }
    for (const part of ["parks", "streets-edge", "streets", "labels"]) {
      if (map.getLayer(`d-${d.slug}-${part}`)) map.setLayoutProperty(`d-${d.slug}-${part}`, "visibility", on ? "visible" : "none");
    }
  }
}

// Aircraft, from zoom PLANE_ZOOM in: at their real height, and drawn much larger than they are so
// that they can be seen (about 34 pixels long).
const PLANE_MESH = planeMesh();
const PLANE_ZOOM = 9.5;
const planesOn = () => live.planes && Boolean(meta) && state.year >= meta.lastYear - 0.05 && map.getZoom() >= PLANE_ZOOM && !document.hidden;
function planeLayer() {
  const metres = Math.max(40, (34 * 56600) / 2 ** map.getZoom());
  return new SimpleMeshLayer({
    id: "planes",
    data: planesNow(),
    mesh: PLANE_MESH,
    getPosition: (p) => p.position,
    getOrientation: (p) => [0, 90 - p.track, 0],
    getColor: [24, 24, 27],
    sizeScale: metres,
    material: false,
    pickable: true,
  });
}

// While they show, the whole map is drawn again to move them: as often as it takes a vehicle at
// 40 km/h to move two pixels, between 2 and 10 times a second. From far away that is seldom.
let transitFrame = 0;
function runTransit() {
  watchTransit(transitOn(), DATA + "tracks.json");
  watchPlanes(planesOn());
  if (!(transitOn() || planesOn()) || transitFrame) return;
  let last = 0;
  const tick = (now) => {
    if (!(transitOn() || planesOn())) { transitFrame = 0; watchPlanes(false); return watchTransit(false); }
    const pixelsPerSecond = (11 * 2 ** map.getZoom()) / 56600;
    // render() comes back here through runTransit(): transitFrame stays set so that it starts no second loop
    if (now - last > 1000 / Math.min(10, Math.max(2, pixelsPerSecond / 2)) && !state.playing) { last = now; render(); }
    transitFrame = requestAnimationFrame(tick);
  };
  transitFrame = requestAnimationFrame(tick);
}
document.addEventListener("visibilitychange", () => { if (meta) runTransit(); });

// Bike Share stations, in today's year: an orange disc with a bicycle at each station, the same
// for all; the counts are in the card. The disc faces the screen and keeps its size, a little
// smaller from further away.
const BIKE_ZOOM = 13;
const today_ = () => Boolean(meta) && state.year >= meta.lastYear - 0.05;
const bikesOn = () => live.bikes && today_() && map.getZoom() >= BIKE_ZOOM;
const BIKE_ICON = (() => {
  const c = document.createElement("canvas");
  c.width = c.height = 96;
  const g = c.getContext("2d");
  g.scale(1.5, 1.5);
  g.beginPath(); g.arc(32, 32, 29, 0, 6.3); g.fillStyle = "#ff8a00"; g.fill();
  g.lineWidth = 3; g.strokeStyle = "#fff"; g.stroke();
  g.lineWidth = 2.6; g.lineCap = g.lineJoin = "round";
  // wheels, frame, fork, handlebar, saddle
  g.beginPath(); g.arc(19, 40, 9, 0, 6.3); g.moveTo(54, 40); g.arc(45, 40, 9, 0, 6.3); g.stroke();
  g.beginPath();
  g.moveTo(19, 40); g.lineTo(28, 26); g.lineTo(41, 26); g.lineTo(31, 40); g.lineTo(19, 40);
  g.moveTo(28, 26); g.lineTo(31, 40);
  g.moveTo(45, 40); g.lineTo(40, 21); g.lineTo(45, 20);
  g.moveTo(28, 26); g.lineTo(27, 22); g.moveTo(23, 22); g.lineTo(31, 22);
  g.stroke();
  return c.toDataURL();
})();
function bikeLayer() {
  return new IconLayer({
    id: "bikes",
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: bikeStations(),
    iconAtlas: BIKE_ICON,
    iconMapping: { bike: { x: 0, y: 0, width: 96, height: 96, anchorY: 96 } },
    getIcon: () => "bike",
    getPosition: (s) => s.position,
    getSize: Math.min(30, Math.max(14, 14 + (map.getZoom() - BIKE_ZOOM) * 5.5)),
    sizeUnits: "pixels",
    pickable: true,
  });
}

// The City of Toronto's aerial photographs, as the ground in place of the drawn map (the Aerial
// button): the one nearest the year on the slider, from the first year on. With one showing, the
// buildings, roofs and trees are left out: the photograph has its own.
const AERIALS = [[1931, "historic_aerial_1931"], [1939, "historic_aerial_1939"], [1954, "historic_aerial_1954"],
  [1965, "historic_aerial_1965"], [1978, "historic_aerial_1978"], [1999, "ortho_1999_greyscale_15cm"],
  [2003, "ortho_2003_greyscale_8cm"], [2005, "ortho_2005_color_20cm"], [2009, "ortho_2009_color_10cm"],
  [2011, "ortho_2011_color_10cm"], [2012, "ortho_2012_color_5cm"], [2013, "ortho_2013_color_8cm"],
  [2014, "ortho_2014_color_8cm"], [2015, "ortho_2015_color_8cm"], [2016, "ortho_2016_color_8cm"],
  [2017, "ortho_2017_color_8cm"], [2018, "ortho_2018_color_8cm"], [2020, "ortho_2020_color_8cm"],
  [2021, "ortho_2021_color_8cm"], [2022, "ortho_2022_color_8cm"], [2023, "ortho_2023_color_10cm"],
  [2024, "ortho_2024_color_8cm"], [2025, "ortho_2025_color_8cm"]];
const aerial = { on: false, shown: null };
function updateAerial() {
  $("aerial").disabled = state.year < AERIALS[0][0];
  if (!map.getLayer("street-labels")) return;
  let year = null, nearest = null;
  for (const [y] of AERIALS) if (nearest === null || Math.abs(y - state.year) < Math.abs(nearest - state.year)) nearest = y;
  if (aerial.on && state.year >= AERIALS[0][0]) year = nearest;
  // which survey it is, said in the explanation behind the "i"
  $("aerial-year").textContent = state.year < AERIALS[0][0] ? "" : `For ${Math.floor(state.year)}, the photo is from ${year ?? nearest}.`;
  if (year === aerial.shown) return;
  aerial.shown = year;
  for (const [y] of AERIALS) if (map.getLayer(`aerial-${y}`)) map.setLayoutProperty(`aerial-${y}`, "visibility", "none");
  if (year === null) return;
  // The 1931 photographs leave out downtown and those of 1939 the Island: each lies over the other.
  const stack = year === 1931 ? [1939, 1931] : year === 1939 ? [1931, 1939] : [year];
  for (const y of stack) {
    const id = `aerial-${y}`;
    if (!map.getLayer(id)) {
      const service = AERIALS.find((a) => a[0] === y)[1];
      map.addSource(id, { type: "raster", tileSize: 256, maxzoom: 19, attribution: "Aerial photographs: City of Toronto",
        tiles: [`https://gis.toronto.ca/arcgis/rest/services/basemap/cot_${service}/MapServer/tile/{z}/{y}/{x}`] });
      map.addLayer({ id, type: "raster", source: id, paint: { "raster-fade-duration": 0 } }, "street-labels");
    }
    map.setLayoutProperty(id, "visibility", "visible");
    // over the streets and the other photographs, under the names
    map.moveLayer(id, "street-labels");
  }
}

// Poppies: the homes of Torontonians who died in the Second World War (pipeline/poppies.py), shown
// in the years of the war and fading out after it.
const POPPY_YEARS = [1939, 1947];
const POPPY_ICON = (() => {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  g.fillStyle = "#c81e1e";
  for (const [x, y] of [[32, 19], [45, 32], [32, 45], [19, 32]]) { g.beginPath(); g.arc(x, y, 14, 0, 6.3); g.fill(); }
  g.beginPath(); g.arc(32, 32, 7, 0, 6.3); g.fillStyle = "#18181b"; g.fill();
  return c.toDataURL();
})();
let poppies = null;
const poppiesOn = () => poppies && state.year >= POPPY_YEARS[0] && state.year < POPPY_YEARS[1];
function poppyLayer() {
  return new IconLayer({
    id: "poppies",
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: poppies,
    iconAtlas: POPPY_ICON,
    iconMapping: { poppy: { x: 0, y: 0, width: 64, height: 64 } },
    getIcon: () => "poppy",
    getPosition: (p) => [p[0], p[1], 0],
    getSize: Math.min(22, Math.max(7, 7 + (map.getZoom() - 11) * 3)),
    sizeUnits: "pixels",
    opacity: Math.min(1, POPPY_YEARS[1] - state.year),
    parameters: { depthCompare: "always", depthWriteEnabled: false },
    pickable: true,
  });
}

// Archive photographs taken around the year on the slider, as camera pins (the Photos button).
// A pin stands for every picture within about its own width, so there are fewer from further
// away. Pins show through buildings: many pictures are placed at the middle of a building.
const PHOTO_ZOOM = 13;
const CAMERA_ICON = cameraIcon();
const photosShow = { on: true, loaded: false, key: "", pins: [] };
function photoLayer() {
  const size = Math.min(28, Math.max(14, 14 + (map.getZoom() - PHOTO_ZOOM) * 5));
  // pictures closer than a pin's width (in degrees of longitude) share a pin
  const cell = (size * 360) / (512 * 2 ** (Math.round(map.getZoom() * 2) / 2));
  const key = `${Math.floor(state.year)}|${cell}`;
  if (key !== photosShow.key) Object.assign(photosShow, { key, pins: photoPins(Math.floor(state.year), cell) });
  return new IconLayer({
    id: "photos",
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: photosShow.pins,
    iconAtlas: CAMERA_ICON,
    iconMapping: { camera: { x: 0, y: 0, width: 96, height: 96, anchorY: 96 } },
    getIcon: () => "camera",
    getPosition: (p) => p.position,
    getSize: size,
    sizeUnits: "pixels",
    parameters: { depthCompare: "always", depthWriteEnabled: false },
    pickable: true,
  });
}
const photosOn = () => photosShow.on && photosShow.loaded && map.getZoom() >= PHOTO_ZOOM;

// The card for a pin: one picture at a time, the nearest in year first.
function showPhotos(ids, n) {
  const p = photo(ids[n]);
  const box = $("info");
  box.hidden = false;
  box.className = "photo";
  box.innerHTML = `<button class="close" aria-label="Close">✕</button>` +
    `<a href="${escapeHtml(p.image)}" target="_blank" rel="noopener"><img src="${escapeHtml(p.image)}" alt=""></a>` +
    `<p class="caption">${escapeHtml(p.title)}, ${escapeHtml(p.year)}</p>` +
    `<p class="credit">Photo: City of Toronto Archives, ${escapeHtml(p.citation)}. The pin shows the place named in the photo's title.</p>` +
    (ids.length > 1 ? `<div class="turn"><button class="prev" aria-label="Previous">‹</button><span>${n + 1} of ${ids.length} here</span><button class="next" aria-label="Next">›</button></div>` : "");
  box.querySelector(".close").addEventListener("click", () => { box.hidden = true; });
  box.querySelector(".prev")?.addEventListener("click", () => showPhotos(ids, (n + ids.length - 1) % ids.length));
  box.querySelector(".next")?.addEventListener("click", () => showPhotos(ids, (n + 1) % ids.length));
}

// Public charging stations for electric cars (pipeline/chargers.py), each from the year it opened:
// a lightning bolt on a disc, red for Tesla's Superchargers and green for the rest.
// [lon, lat, name, network, address, level 2 chargers, fast chargers, plugs, year opened]
const CHARGER_ZOOM = 12.5;
const CHARGER_ICONS = (() => {
  const c = document.createElement("canvas");
  c.width = 128; c.height = 64;
  const g = c.getContext("2d");
  ["#c81e1e", "#15803d"].forEach((colour, i) => {
    g.beginPath(); g.arc(32 + i * 64, 32, 29, 0, 6.3); g.fillStyle = colour; g.fill();
    g.lineWidth = 4; g.strokeStyle = "#fff"; g.stroke();
    g.beginPath();
    for (const [x, y] of [[37, 10], [19, 36], [30, 36], [26, 54], [45, 27], [34, 27]]) g.lineTo(x + i * 64, y);
    g.closePath(); g.fillStyle = "#fff"; g.fill();
  });
  return c.toDataURL();
})();
// red for Tesla's Superchargers only; its slower "destination" chargers are green with the rest
const isTesla = (c) => c[3] === "Tesla";
let chargers = null;
const chargersShow = { year: null, list: [] };
const chargersOn = () => live.chargers && chargers && map.getZoom() >= CHARGER_ZOOM && state.year >= chargers[0][8];
function chargerLayer() {
  const y = Math.floor(state.year);
  if (y !== chargersShow.year) Object.assign(chargersShow, { year: y, list: chargers.filter((c) => c[8] <= y) });
  const size = Math.min(26, Math.max(9, 9 + (map.getZoom() - CHARGER_ZOOM) * 4.5));
  return new IconLayer({
    id: "chargers",
    beforeId: map.getLayer("places-city") ? "places-city" : undefined,
    data: chargersShow.list,
    iconAtlas: CHARGER_ICONS,
    iconMapping: { tesla: { x: 0, y: 0, width: 64, height: 64, anchorY: 64 }, other: { x: 64, y: 0, width: 64, height: 64, anchorY: 64 } },
    getIcon: (c) => (isTesla(c) ? "tesla" : "other"),
    getPosition: (c) => [c[0], c[1], 0],
    getSize: (c) => (isTesla(c) ? size * 1.25 : size),
    updateTriggers: { getSize: size },
    sizeUnits: "pixels",
    // seen through the buildings: most chargers are inside parking garages
    parameters: { depthCompare: "always", depthWriteEnabled: false },
    pickable: true,
  });
}

// Today's weather, in today's year: cloud dims the sun, rain and snow fall over the map, and
// lying snow whitens the ground and the sloped roofs.
const SNOW = "#f4f5f3";
let weatherShown = "";
function showWeather() {
  const on = live.weather && today_() && weather.known;
  watchWeather(today_(), render);
  const key = on ? `${weather.cloud}|${weather.rain}|${weather.snow}|${weather.lying}` : "";
  if (key === weatherShown || !map.getLayer("streets")) return;
  weatherShown = key;
  sun.cloud = on ? weather.cloud : 0;
  LIGHTING.setSun(sun);
  fall($("falling"), on ? weather.rain : 0, on ? weather.snow : 0, weather.wind);
  const white = on && (weather.lying || weather.snow > 0);
  map.setPaintProperty("background", "background-color", white ? SNOW : LAND_COLOR);
  if (map.getLayer("parks")) map.setPaintProperty("parks", "fill-color", white ? "#e6ece0" : PARK_COLOR);
  $("weather-now").hidden = !on || !weather.text;
  $("weather-now").textContent = weather.text;
}
const roofColor = () => (weatherShown && (weather.lying || weather.snow > 0) ? [236, 238, 236] : ROOF_COLOR);

// Sloped roofs of the houses. They come in ROOF_SETS sets in order of their year. A set whose
// houses are all older than NEW_SPAN is drawn as it is; the roofs of newer houses are drawn apart,
// rising and losing their colour with the walls below them.
const ROOF_MESH = roofMesh();
const ROOF_COLOR = [176, 163, 150];
const ROOF_SETS = 12;
let roofs = null;
// the rise of the roof on a building (m), for the height in its card
const roofRise = new Map();
let events = null;
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
  story.files = await fetchJson("narration.json").catch(() => []);
  events = await fetchJson("events.json").catch(() => null);
  fetchJson("poppies.json").then((p) => { poppies = p; render(); }).catch(() => {});
  fetchJson("pearson.json").then((p) => { pearson = p; render(); }).catch(() => {});
  loadDistricts(DATA, ["etobicoke"]).then((d) => { districts = d; render(); });
  fetchJson("chargers.json").then((c) => { chargers = c; render(); }).catch(() => {});
  state.year = opened.year >= meta.firstYear && opened.year <= meta.lastYear ? opened.year : meta.firstYear;
  setupControls();
  render();
  if (map.isStyleLoaded()) addMapLayers(); else map.once("load", addMapLayers);
  $("loading").classList.add("done");
  roofs = await loadRoofs(DATA).catch(() => null);
  if (roofs) for (let i = 0; i < roofs.length; i++) roofRise.set(roofs.ids[i], roofs.size[i * 5 + 3]);
  loadPhotos(DATA + "photos.json").then(() => { photosShow.loaded = true; render(); }).catch(() => {});
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

// the same object for the same run of roofs, so that a layer is only worked out again when its
// roofs change
const roofRuns = new Map();
function roofRun(from, to) {
  const key = `${from}-${to}`;
  if (!roofRuns.has(key)) {
    if (roofRuns.size > 200) roofRuns.clear();
    roofRuns.set(key, { length: to - from });
  }
  return roofRuns.get(key);
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
    data: roofRun(from, to),
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
    getColor: settled || state.quality ? roofColor() : (_, { index }) => {
      const k = Math.min(1, Math.max(0, (state.year - year(index) - RISE_YEARS) / (NEW_SPAN - RISE_YEARS)));
      return roofColor().map((c, n) => c * (NEW_TINT[n] + (1 - NEW_TINT[n]) * k));
    },
    updateTriggers: settled ? { getColor: weatherShown } : { getPosition: state.year, getScale: state.year, getColor: [state.year, state.quality, weatherShown] },
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

  // Today's airports (pipeline/airports.py): Pearson, west of the old city, and the Island airport.
  // Widths are in metres on the ground.
  const metresWide = (m) => ["interpolate", ["exponential", 2], ["zoom"], 9, (m * 2 ** 9) / 56600, 19, (m * 2 ** 19) / 56600];
  map.addSource("airports", { type: "geojson", data: DATA + "airports.json" });
  map.addLayer({ id: "airport-apron", type: "fill", source: "airports", filter: ["==", ["get", "kind"], "apron"], paint: { "fill-color": "#dcd9d2" } });
  map.addLayer({ id: "airport-taxiway", type: "line", source: "airports", filter: ["==", ["get", "kind"], "taxiway"],
    layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#c9c6bf", "line-width": metresWide(23) } });
  map.addLayer({ id: "airport-runway", type: "line", source: "airports", filter: ["==", ["get", "kind"], "runway"],
    paint: { "line-color": "#8f8d89", "line-width": metresWide(60) } });
  map.addLayer({ id: "airport-terminal", type: "fill", source: "airports", filter: ["==", ["get", "kind"], "terminal"], paint: { "fill-color": "#b3aa9b" } });
  map.addLayer({ id: "airport-name", type: "symbol", source: "airports", filter: ["all", ["==", ["get", "kind"], "terminal"], ["!=", ["get", "name"], ""]], minzoom: 12,
    layout: { "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"], "text-size": 12 },
    paint: { "text-color": "#52525b", "text-halo-color": "#ffffff", "text-halo-width": 1.5 } });

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

  // Battles and fires, drawn in their years (data/manual/events.geojson): the ground a fire burned,
  // the moves of a battle, and the places named in it.
  if (events) {
    const side = (american, british, other) => ["match", ["get", "side"], "american", american, "british", british, "plan", "#18181b", "subway", "#a16207", other];
    map.addSource("events", { type: "geojson", data: events });
    map.addLayer({ id: "events-fire", type: "fill", source: "events", filter: ["==", ["get", "kind"], "fire"],
      paint: { "fill-color": "#e2571c", "fill-opacity": 0.42 } });
    map.addLayer({ id: "events-fire-edge", type: "line", source: "events", filter: ["==", ["get", "kind"], "fire"],
      paint: { "line-color": "#b23a0c", "line-width": 2, "line-dasharray": [2, 1.5] } });
    map.addLayer({ id: "events-village", type: "fill", source: "events", filter: ["==", ["get", "kind"], "village"],
      paint: { "fill-color": "#1d4ed8", "fill-opacity": 0.16 } });
    map.addLayer({ id: "events-village-edge", type: "line", source: "events", filter: ["==", ["get", "kind"], "village"],
      paint: { "line-color": "#1e40af", "line-width": 2, "line-dasharray": [2, 1.5] } });
    map.addLayer({ id: "events-outline", type: "line", source: "events", filter: ["==", ["get", "kind"], "outline"],
      paint: { "line-color": "#18181b", "line-width": 2.5 } });
    map.addLayer({ id: "events-move", type: "line", source: "events", filter: ["==", ["get", "kind"], "move"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": side("#1d4ed8", "#b91c1c", "#444"), "line-width": 3.5, "line-dasharray": [1.5, 1.5] } });
  }

  map.addSource("places", { type: "geojson", data: places });
  for (const [kind, st] of Object.entries(PLACE_STYLE)) {
    map.addLayer({ id: `places-${kind}`, type: "symbol", source: "places",
      layout: { "text-field": ["get", "name"], "text-font": [st.font], "text-size": st.size,
        "text-transform": st.caps ? "uppercase" : "none", "text-letter-spacing": st.caps ? 0.12 : 0,
        "text-max-width": 7 },
      paint: { "text-color": st.color, "text-halo-color": "rgba(250,248,242,0.85)", "text-halo-width": 1.5 } });
  }
  // the words of the battles and fires go on top of everything
  if (events) {
    const side = (american, british, other) => ["match", ["get", "side"], "american", american, "british", british, "plan", "#18181b", "subway", "#a16207", other];
    map.addLayer({ id: "events-move-label", type: "symbol", source: "events", filter: ["==", ["get", "kind"], "move"],
      layout: { "symbol-placement": "line", "text-field": ["concat", ["get", "label"], "  ›››"], "text-font": ["Noto Sans Bold"], "text-size": 12.5,
        "symbol-spacing": 420, "text-offset": [0, -0.9] },
      paint: { "text-color": side("#1d4ed8", "#b91c1c", "#444"), "text-halo-color": "#ffffff", "text-halo-width": 1.8 } });
    map.addLayer({ id: "events-point", type: "circle", source: "events", filter: ["==", ["get", "kind"], "point"],
      paint: { "circle-radius": 6, "circle-color": side("#1d4ed8", "#b91c1c", "#e2571c"), "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });
    map.addLayer({ id: "events-label", type: "symbol", source: "events", filter: ["in", ["get", "kind"], ["literal", ["point", "fire", "village", "outline"]]],
      layout: { "text-field": ["get", "label"], "text-font": ["Noto Sans Bold"], "text-size": 12.5, "text-anchor": "top", "text-offset": [0, 0.8],
        "text-max-width": 14, "text-allow-overlap": true },
      paint: { "text-color": ["case", ["==", ["get", "kind"], "village"], "#1e40af", ["==", ["get", "kind"], "outline"], "#18181b", side("#1d4ed8", "#b91c1c", "#9a330b")], "text-halo-color": "#ffffff", "text-halo-width": 2 } });
  }
  mapYear = null;
  render();
}


// What is drawn for a battle, a fire or a plan fades out over its last year.
let eventsFade = "";
function fadeEvents(year) {
  if (!map.getLayer("events-move")) return;
  const key = year.toFixed(1);
  if (key === eventsFade) return;
  eventsFade = key;
  const left = ["max", 0, ["min", 1, ["-", ["get", "to"], Number(key)]]];
  map.setPaintProperty("events-fire", "fill-opacity", ["*", 0.42, left]);
  map.setPaintProperty("events-village", "fill-opacity", ["*", 0.16, left]);
  for (const id of ["events-outline", "events-fire-edge", "events-village-edge", "events-move"]) map.setPaintProperty(id, "line-opacity", left);
  map.setPaintProperty("events-point", "circle-opacity", left);
  map.setPaintProperty("events-point", "circle-stroke-opacity", left);
  for (const id of ["events-move-label", "events-label"]) map.setPaintProperty(id, "text-opacity", left);
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
  // battles and fires: in their years only
  for (const id of ["events-outline", "events-fire", "events-fire-edge", "events-village", "events-village-edge", "events-move", "events-move-label", "events-point", "events-label"]) {
    if (!map.getLayer(id)) continue;
    const kinds = { "events-fire": ["fire"], "events-fire-edge": ["fire"], "events-move": ["move"], "events-move-label": ["move"], "events-point": ["point"], "events-label": ["point", "fire", "village", "outline"], "events-outline": ["outline"], "events-village": ["village"], "events-village-edge": ["village"] }[id];
    map.setFilter(id, ["all", ["in", ["get", "kind"], ["literal", kinds]], ["<=", ["get", "from"], y], [">", ["get", "to"], y]]);
  }
  // the airports as they are today, in today's year
  for (const id of ["airport-apron", "airport-taxiway", "airport-runway", "airport-terminal", "airport-name"]) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", y >= meta.lastYear ? "visible" : "none");
  }
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
  showWeather();
  const shore = updateWater(state.year);
  updateMap(state.year);
  fadeEvents(state.year);
  districtGround(state.year);
  updateAerial();
  const model = aerial.shown === null;
  overlay.setProps({ layers: [...(SHADOWS ? [groundLayer()] : []), ...(model && lost ? lostLayers() : []), ...(model ? buildingLayers() : []), ...(model && roofs ? roofLayers() : []), ...(model ? landmarkLayers() : []), ...(model && trees ? treeLayers() : []), ...(bikesOn() ? [bikeLayer()] : []), ...(chargersOn() ? [chargerLayer()] : []), ...(poppiesOn() ? [poppyLayer()] : []), ...(photosOn() ? [photoLayer()] : []), ...districtLayers(), ...(pearson && state.year >= meta.lastYear ? [pearsonLayer()] : []), ...(transitOn() ? [transitLayer()] : []), ...(planesOn() ? [planeLayer()] : [])] });
  runTransit();
  watchBikes(bikesOn(), render);
  treesOn = treeSets();
  bikesShown = bikesOn();
  drawn = drawnKey();
  writeHash();

  $("panel").classList.toggle("past", !today_());
  $("year-label").textContent = String(y);
  $("population-value").textContent = populationAt(state.year);
  $("standing").textContent = `${countStanding(y).toLocaleString("en-CA")} of today's buildings are built`;
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

// The panel of layers: it folds away, each "i" opens a longer note, and the live layers have switches.
function setupPanel() {
  const head = $("panel-head"), body = $("panel-body");
  const fold = (open) => { head.setAttribute("aria-expanded", String(open)); body.hidden = !open; };
  let open = !window.matchMedia?.("(max-width: 640px)").matches;
  try { open = (localStorage.getItem("panel") ?? String(open)) === "true"; } catch { /* private window */ }
  fold(open);
  head.addEventListener("click", () => {
    fold(body.hidden);
    try { localStorage.setItem("panel", String(!body.hidden)); } catch { /* private window */ }
  });
  for (const about of document.querySelectorAll("#panel .about")) {
    about.addEventListener("click", () => {
      const more = about.closest(".layer").querySelector(".more");
      more.hidden = !more.hidden;
      about.setAttribute("aria-expanded", String(!more.hidden));
    });
  }
  for (const key of ["transit", "bikes", "planes", "weather", "chargers"]) {
    $(key).addEventListener("click", () => {
      live[key] = !live[key];
      $(key).setAttribute("aria-pressed", String(live[key]));
      render();
    });
  }
}

// a speaker with sound waves, and one crossed out
const SPEAKER = '<svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor"/>';
const SPEAKER_ON = SPEAKER + '<path d="M15.5 9a4.2 4.2 0 0 1 0 6"/><path d="M18.3 6.5a8 8 0 0 1 0 11"/></svg>';
const SPEAKER_OFF = SPEAKER + '<path d="M16 9.5l5 5"/><path d="M21 9.5l-5 5"/></svg>';

function setupControls() {
  $("story-sound").innerHTML = SPEAKER_ON;
  setupSun();
  setupPanel();
  const slider = $("slider");
  slider.min = String(meta.firstYear);
  slider.max = String(meta.lastYear);
  slider.value = String(state.year);
  slider.addEventListener("input", () => { pauseStory(); state.year = Number(slider.value); cardFollowsYear(); render(); });
  $("play").addEventListener("click", () => setPlaying(!state.playing));
  $("speed").addEventListener("change", (e) => { state.speed = Number(e.target.value); });
  $("aerial").addEventListener("click", () => {
    aerial.on = !aerial.on;
    $("aerial").setAttribute("aria-pressed", String(aerial.on));
    render();
  });
  $("photos").addEventListener("click", () => {
    photosShow.on = !photosShow.on;
    $("photos").setAttribute("aria-pressed", String(photosShow.on));
    render();
  });
  $("quality").addEventListener("click", () => {
    state.quality = !state.quality;
    $("quality").setAttribute("aria-pressed", String(state.quality));
    $("legend").hidden = !state.quality;
    render();
  });
  $("legend").innerHTML = meta.tiers.map((t) =>
    `<div><span class="swatch" style="background:rgb(${TIER_COLORS[t].join(",")})"></span>${TIER_LABELS[t]}` +
    `<span class="count">${(meta.countsByTier[t] ?? 0).toLocaleString("en-CA")}</span></div>`).join("") +
    (lost ? `<div><span class="swatch" style="background:rgb(${LOST_COLOR.join(",")})"></span>Gone today. Drawn on an old fire insurance map.` +
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
    // of several stops in the same year, the first
    while (i > 0 && stops[i - 1].year === stops[i].year) i--;
    // closed in the middle of a stop and the year not moved since: on from there
    const kept = story.left;
    if (kept && state.year >= stops[kept.index].year - 0.01 && state.year <= stops[kept.index].yearEnd + 0.01) return openStop(kept.index, true);
    openStop(state.year >= meta.lastYear ? 0 : i, true);
  });
  $("story-close").addEventListener("click", closeStory);
  // back and forward start a stop from its beginning
  $("story-prev").addEventListener("click", () => { hush(); story.left = null; openStop(Math.max(0, story.index - 1), story.playing); });
  $("story-next").addEventListener("click", () => { hush(); story.left = null; openStop(Math.min(stops.length - 1, story.index + 1), story.playing); });
  $("story-play").addEventListener("click", () => {
    if (!story.playing) return openStop(story.index, true);
    // keep the run going so the year still arrives at the stop's year
    story.playing = false;
    hush();
    map.stop();
    syncStoryButton();
  });
  $("story-sound").addEventListener("click", () => {
    story.voice = !story.voice;
    $("story-sound").setAttribute("aria-pressed", String(story.voice));
    $("story-sound").innerHTML = story.voice ? SPEAKER_ON : SPEAKER_OFF;
    if (!story.voice) hush(); else if (story.playing) openStop(story.index, true);
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
  if (autoplay) narrate(i); else hush();
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
      // read aloud, the stop lasts as long as the voice and a moment more
      const sound = story.narration;
      const k = !sound ? Math.min(1, (now - arrived) / read)
        : sound.ended ? Math.min(1, 0.97 + (now - (sound.over ??= now)) / 30000)
        : sound.duration ? Math.min(0.97, (sound.currentTime / sound.duration) * 0.97) : 0;
      if (s.yearEnd > s.year) {
        // the years run out three quarters of the way through, so that what the voice names last is on the map by then
        state.year = s.year + (s.yearEnd - s.year) * Math.min(1, k / 0.75);
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
  // the last stop gives an address to write to in place of a source
  $("story-source").textContent = s.url.startsWith("mailto:") ? s.url.slice(7) : "source";
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
  hush();
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
  if (info.picked && info.layer?.id === "photos") return showPhotos(info.object.ids, 0);
  if (info.picked && info.layer?.id === "chargers") {
    const [, , name, network, address, slow, fast, plugs, year] = info.object;
    const count = [slow ? `${slow} regular (Level 2)` : "", fast ? `${fast} fast` : ""].filter(Boolean).join(", ");
    return showInfo(name || "Charging station", [["Network", network === "Tesla" ? "Tesla Supercharger" : network], ["Address", address],
      ...(count ? [["Chargers", count]] : []), ...(plugs ? [["Plugs", plugs]] : []), ["Opened", year]]);
  }
  if (info.picked && info.layer?.id === "poppies") {
    return showInfo(info.object[2], [["", "Someone from this home died in the Second World War."],
      ...(info.object[3] ? [["", "This house number is not there today, so the poppy is at the nearest one."]] : [])]);
  }
  if (info.picked && info.layer?.id === "bikes") {
    const s = info.object;
    return showInfo(s.name, [["Bikes", s.ebikes ? `${s.bikes}, of them ${s.ebikes} electric` : s.bikes], ["Free docks", s.docks]]);
  }
  if (info.picked && info.layer?.id === "planes") {
    const p = info.object;
    const rows = (route) => [...(route ? [["Airline", route.airline], ["Usual route", route.text]] : []), ...(p.type ? [["Type", p.type]] : []),
      ["Height", p.up ? `${p.up.toLocaleString("en-CA")} m` : "on the ground"], ["Speed", `${Math.round(p.speed * 3.6)} km/h`]];
    showInfo(p.flight || "Aircraft", rows(null));
    // Where the flight usually goes, looked up by its flight number. Private aircraft have none.
    if (/^[A-Z]{3}\d/.test(p.flight)) {
      fetch(`https://api.adsbdb.com/v0/callsign/${encodeURIComponent(p.flight)}`).then((r) => r.json()).then((d) => {
        const f = d.response?.flightroute;
        if (!f?.origin || !f?.destination || $("info").hidden || $("info").querySelector("h3")?.textContent !== p.flight) return;
        showInfo(p.flight, rows({ airline: f.airline?.name ?? "", text: `${f.origin.municipality} (${f.origin.iata_code}) to ${f.destination.municipality} (${f.destination.iata_code})` }));
      }).catch(() => {});
    }
    return;
  }
  if (info.picked && info.layer?.id === "transit") {
    return showInfo(transitName(info.object), [["Route", info.object.route], ["Vehicle", info.object.id]]);
  }
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
      [kept ? "Here by" : "Built about", built],
      [stays ? "Still here in" : "Gone by about", gone],
      ["Shape from", `the ${lost.plans[plan]} map`],
      ["Made of", brick ? "brick" : "wood"],
      ["How we know", `This building is gone. It was drawn on an old fire insurance map. Its shape and what it was made of come from that map. ${known && known.years !== false ? "The years come from an article about it." : estimated ? "One of the years is a guess." : "The years fall between two of the maps."} The height is a guess.`],
      ...(known?.url ? [["More", `<a href="${escapeHtml(known.url)}" target="_blank" rel="noopener">article</a>`]] : []),
    ]);
  }
  const tier = meta.tiers[tiers[i]];
  const named = names[i];
  const rows = [
    [tier === "estimate" ? "Built about" : "Built", years[i]],
    ["How we know", TIER_LABELS[tier]],
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
  box.className = "";
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
