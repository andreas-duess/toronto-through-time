// The TTC's buses and streetcars where they are now, from the TTC's public feed of vehicle
// positions (run by Umo, open to browsers). The whole fleet reports about every 30 seconds, so
// between reports each vehicle is moved on at its reported speed, and eased onto its new place when
// the next report comes. A streetcar is put on the nearest track and runs along it, straight on
// where tracks meet; a bus runs along its heading.
const FEED = "https://webservices.umoiq.com/service/publicJSONFeed?a=ttc&command=";
const EVERY_MS = 15000;      // between requests
const COAST_S = 40;          // a vehicle is moved on for this long after a report, then waits
const STALE_S = 180;         // a report older than this is a parked or lost vehicle
const EASE_MS = 3000;        // time to slide onto a new report
const BOX = [-79.52, 43.6, -79.26, 43.73];
const NIGHT_CARS = new Set(["301", "303", "304", "305", "306", "310", "312"]);
const M_PER_LAT = 111200, M_PER_LON = 80400;   // metres per degree at Toronto

const ON_TRACK_M = 30;        // a streetcar this close to a track is on it

// The tracks (pipeline/tracks.py), in metres east and north of the first point: lines of points
// with the distance along the line at each, a grid of their pieces to find the nearest, and which
// lines start where another ends.
let tracks = null;
const CELL = 120;
const cellOf = (x, y) => `${Math.floor(x / CELL)},${Math.floor(y / CELL)}`;
async function loadTracks(url) {
  const lines = await fetch(url).then((r) => r.json());
  const [lon0, lat0] = lines[0][0];
  const t = { lon0, lat0, lines: [], grid: new Map(), next: new Map() };
  const starts = new Map();
  lines.forEach((line, i) => {
    const pts = line.map(([lon, lat]) => [(lon - lon0) * M_PER_LON, (lat - lat0) * M_PER_LAT]);
    const along = [0];
    for (let k = 1; k < pts.length; k++) {
      along.push(along[k - 1] + Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]));
      // every piece goes into the cells it may touch
      const [a, b] = [pts[k - 1], pts[k]];
      for (let x = Math.floor(Math.min(a[0], b[0]) / CELL); x <= Math.floor(Math.max(a[0], b[0]) / CELL); x++) {
        for (let y = Math.floor(Math.min(a[1], b[1]) / CELL); y <= Math.floor(Math.max(a[1], b[1]) / CELL); y++) {
          const key = `${x},${y}`;
          if (!t.grid.has(key)) t.grid.set(key, []);
          t.grid.get(key).push([i, k]);
        }
      }
    }
    t.lines.push({ pts, along });
    const key = line[0].join(",");
    if (!starts.has(key)) starts.set(key, []);
    starts.get(key).push(i);
  });
  lines.forEach((line, i) => t.next.set(i, (starts.get(line[line.length - 1].join(",")) ?? []).filter((j) => j !== i)));
  tracks = t;
}

// The nearest track to a place for a vehicle heading (east, north): [line, metres along it], or null.
// Tracks are drawn in their direction of travel; one running the other way counts as further off.
function onTrack(lon, lat, east, north) {
  if (!tracks) return null;
  const x = (lon - tracks.lon0) * M_PER_LON, y = (lat - tracks.lat0) * M_PER_LAT;
  const speed = Math.hypot(east, north);
  let best = null, least = ON_TRACK_M;
  for (let dx = -1; dx <= 1; dx++) {
    for (let dy = -1; dy <= 1; dy++) {
      for (const [i, k] of tracks.grid.get(cellOf(x + dx * CELL, y + dy * CELL)) ?? []) {
        const { pts, along } = tracks.lines[i];
        const [ax, ay] = pts[k - 1], [bx, by] = pts[k];
        const len = along[k] - along[k - 1];
        if (!len) continue;
        const t = Math.min(1, Math.max(0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / (len * len)));
        let d = Math.hypot(ax + (bx - ax) * t - x, ay + (by - ay) * t - y);
        if (speed > 0.5 && (east * (bx - ax) + north * (by - ay)) / (speed * len) < 0) d += 12;
        if (d < least) { least = d; best = [i, along[k - 1] + len * t]; }
      }
    }
  }
  return best;
}

// A place on the tracks, `metres` on from [line, along]: [lon, lat, heading]. At the end of a line
// it goes on along the line that leaves most nearly straight ahead, or stops.
function rideTrack([line, at], metres, target) {
  let i = line, s = at + metres;
  for (let hops = 0; hops < 20; hops++) {
    const { pts, along } = tracks.lines[i];
    const total = along[along.length - 1];
    if (s > total) {
      const [px, py] = pts[pts.length - 2], [qx, qy] = pts[pts.length - 1];
      let on = -1, straightest = 0.3;
      for (const j of tracks.next.get(i)) {
        const [ax, ay] = tracks.lines[j].pts[0], [bx, by] = tracks.lines[j].pts[1];
        const cos = ((qx - px) * (bx - ax) + (qy - py) * (by - ay)) / (Math.hypot(qx - px, qy - py) * Math.hypot(bx - ax, by - ay) || 1);
        if (cos > straightest) { straightest = cos; on = j; }
      }
      if (on >= 0) { s -= total; i = on; continue; }
      s = total;
    }
    let k = 1;
    while (k < along.length - 1 && along[k] < s) k++;
    const [ax, ay] = pts[k - 1], [bx, by] = pts[k];
    const t = (s - along[k - 1]) / (along[k] - along[k - 1] || 1);
    target[0] = tracks.lon0 + (ax + (bx - ax) * t) / M_PER_LON;
    target[1] = tracks.lat0 + (ay + (by - ay) * t) / M_PER_LAT;
    target[2] = (Math.atan2(bx - ax, by - ay) * 180) / Math.PI;
    return target;
  }
  return target;
}

const vehicles = new Map();   // id -> { route, car, lon, lat, east, north (m/s), heading, at (ms), slip: [lon, lat, since] }
const titles = new Map();     // route number -> "501-Queen"
let timer = 0;

const isCar = (route) => (route.length === 3 && route[0] === "5") || NIGHT_CARS.has(route);

// where a vehicle is drawn at a moment, [lon, lat, heading]: its report, moved on, plus what is
// left of the slide
function place(v, now, target) {
  const s = Math.min(COAST_S, Math.max(0, (now - v.at) / 1000));
  if (v.track) {
    rideTrack(v.track, v.speed * s, target);
  } else {
    target[0] = v.lon + (v.east * s) / M_PER_LON;
    target[1] = v.lat + (v.north * s) / M_PER_LAT;
    target[2] = v.heading;
  }
  if (v.slip) {
    const left = Math.max(0, 1 - (now - v.slip[2]) / EASE_MS);
    const k = left * left * (3 - 2 * left);
    target[0] += v.slip[0] * k;
    target[1] += v.slip[1] * k;
  }
  return target;
}

async function refresh() {
  const now = Date.now();
  const feed = await fetch(FEED + "vehicleLocations&t=0").then((r) => r.json());
  const list = Array.isArray(feed.vehicle) ? feed.vehicle : feed.vehicle ? [feed.vehicle] : [];
  const seen = new Set();
  for (const f of list) {
    const lon = Number(f.lon), lat = Number(f.lat), age = Number(f.secsSinceReport);
    if (!(lon > BOX[0] && lon < BOX[2] && lat > BOX[1] && lat < BOX[3]) || !(age <= STALE_S)) continue;
    const heading = Number(f.heading), speed = Math.max(0, Number(f.speedKmHr) || 0) / 3.6;
    const turn = (heading * Math.PI) / 180;
    const next = { route: f.routeTag, car: isCar(f.routeTag), lon, lat, heading: heading >= 0 ? heading : 0, speed,
      east: heading >= 0 ? Math.sin(turn) * speed : 0, north: heading >= 0 ? Math.cos(turn) * speed : 0, at: now - age * 1000, slip: null };
    if (next.car) next.track = onTrack(lon, lat, Math.sin(turn), Math.cos(turn));
    const before = vehicles.get(f.id);
    if (before) {
      if (before.lon === lon && before.lat === lat && Math.abs(before.at - next.at) < 5000) { seen.add(f.id); continue; }   // the same report
      // start from where it is drawn now and slide to where the new report puts it
      const was = place(before, now, [0, 0, 0]), is = place(next, now, [0, 0, 0]);
      next.slip = [was[0] - is[0], was[1] - is[1], now];
      if (heading < 0) next.heading = before.heading;
    }
    vehicles.set(f.id, next);
    seen.add(f.id);
  }
  for (const id of vehicles.keys()) if (!seen.has(id)) vehicles.delete(id);
}

// Keeps the positions fresh while `on`; stops asking when off.
export function watchTransit(on, tracksUrl) {
  if (!on) { clearInterval(timer); timer = 0; return; }
  if (timer) return;
  if (!tracks) loadTracks(tracksUrl).catch(() => {});
  if (!titles.size) {
    fetch(FEED + "routeList").then((r) => r.json())
      .then((d) => { for (const r of d.route ?? []) titles.set(r.tag, r.title); }).catch(() => {});
  }
  const ask = () => { if (!document.hidden) refresh().catch(() => {}); };
  ask();
  timer = setInterval(ask, EVERY_MS);
}

// The vehicles now, for drawing: [{ id, route, car, heading, position: [lon, lat] }]
export function transitNow() {
  const now = Date.now();
  return Array.from(vehicles, ([id, v]) => {
    const [lon, lat, heading] = place(v, now, [0, 0, 0]);
    return { id, route: v.route, car: v.car, heading, position: [lon, lat, 0] };
  });
}

// "510-Spadina" as "510 Spadina streetcar"
export function transitName(v) {
  const title = (titles.get(v.route) ?? v.route).replace("-", " ");
  return `${title} ${v.car ? "streetcar" : "bus"}`;
}

// A box one long, one wide and one high, standing on the ground, its length along x.
export function boxMesh() {
  const positions = [], normals = [];
  const face = (n, a, b, c, d) => { for (const p of [a, b, c, a, c, d]) { positions.push(...p); normals.push(...n); } };
  const x = 0.5, y = 0.5;
  face([0, 0, 1], [-x, -y, 1], [x, -y, 1], [x, y, 1], [-x, y, 1]);
  face([0, -1, 0], [-x, -y, 0], [x, -y, 0], [x, -y, 1], [-x, -y, 1]);
  face([0, 1, 0], [x, y, 0], [-x, y, 0], [-x, y, 1], [x, y, 1]);
  face([1, 0, 0], [x, -y, 0], [x, y, 0], [x, y, 1], [x, -y, 1]);
  face([-1, 0, 0], [-x, y, 0], [-x, -y, 0], [-x, -y, 1], [-x, y, 1]);
  return { positions: { value: new Float32Array(positions), size: 3 }, normals: { value: new Float32Array(normals), size: 3 } };
}
