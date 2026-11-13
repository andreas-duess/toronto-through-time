// The TTC's buses and streetcars where they are now, from the TTC's public feed of vehicle
// positions (run by Umo, open to browsers). The whole fleet reports about every 30 seconds, so
// between reports each vehicle is moved on along its heading at its reported speed, and eased
// onto its new place when the next report comes.
const FEED = "https://webservices.umoiq.com/service/publicJSONFeed?a=ttc&command=";
const EVERY_MS = 15000;      // between requests
const COAST_S = 40;          // a vehicle is moved on for this long after a report, then waits
const STALE_S = 180;         // a report older than this is a parked or lost vehicle
const EASE_MS = 3000;        // time to slide onto a new report
const BOX = [-79.52, 43.6, -79.26, 43.73];
const NIGHT_CARS = new Set(["301", "303", "304", "305", "306", "310", "312"]);
const M_PER_LAT = 111200, M_PER_LON = 80400;   // metres per degree at Toronto

const vehicles = new Map();   // id -> { route, car, lon, lat, east, north (m/s), heading, at (ms), slip: [lon, lat, since] }
const titles = new Map();     // route number -> "501-Queen"
let timer = 0;

const isCar = (route) => (route.length === 3 && route[0] === "5") || NIGHT_CARS.has(route);

// where a vehicle is drawn at a moment: its report, moved on, plus what is left of the slide
function place(v, now, target) {
  const s = Math.min(COAST_S, Math.max(0, (now - v.at) / 1000));
  const left = v.slip ? Math.max(0, 1 - (now - v.slip[2]) / EASE_MS) : 0;
  const k = left * left * (3 - 2 * left);
  target[0] = v.lon + (v.east * s) / M_PER_LON + (v.slip ? v.slip[0] * k : 0);
  target[1] = v.lat + (v.north * s) / M_PER_LAT + (v.slip ? v.slip[1] * k : 0);
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
    const next = { route: f.routeTag, car: isCar(f.routeTag), lon, lat, heading: heading >= 0 ? heading : 0,
      east: heading >= 0 ? Math.sin(turn) * speed : 0, north: heading >= 0 ? Math.cos(turn) * speed : 0, at: now - age * 1000, slip: null };
    const before = vehicles.get(f.id);
    if (before) {
      if (before.lon === lon && before.lat === lat && Math.abs(before.at - next.at) < 5000) { seen.add(f.id); continue; }   // the same report
      // start from where it is drawn now and slide to where the new report puts it
      const was = place(before, now, [0, 0]), is = place(next, now, [0, 0]);
      next.slip = [was[0] - is[0], was[1] - is[1], now];
      if (heading < 0) next.heading = before.heading;
    }
    vehicles.set(f.id, next);
    seen.add(f.id);
  }
  for (const id of vehicles.keys()) if (!seen.has(id)) vehicles.delete(id);
}

// Keeps the positions fresh while `on`; stops asking when off.
export function watchTransit(on) {
  if (!on) { clearInterval(timer); timer = 0; return; }
  if (timer) return;
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
  return Array.from(vehicles, ([id, v]) => ({ id, route: v.route, car: v.car, heading: v.heading, position: place(v, now, [0, 0, 0]) }));
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
