// Aircraft over Toronto now, from the adsb.lol network of volunteer receivers (open data), by way
// of the site's Worker (/planes), which asks it at most every ten seconds. Between reports each
// aircraft is moved on along its track at its speed.
const EVERY_MS = 10000;
const COAST_S = 30;          // an aircraft is moved on for this long after a report, then waits
const M_PER_LAT = 111200, M_PER_LON = 80400;   // metres per degree at Toronto

const planes = new Map();    // hex -> { flight, type, lon, lat, up (m), east, north (m/s), track, at (ms) }
let timer = 0;

async function refresh() {
  const now = Date.now();
  const list = await fetch("/planes").then((r) => r.json());
  const seen = new Set();
  for (const [hex, flight, type, lat, lon, up, speed, track, age] of list) {
    const turn = (track * Math.PI) / 180;
    planes.set(hex, { flight, type, lon, lat, up, track, speed, east: Math.sin(turn) * speed, north: Math.cos(turn) * speed, at: now - age * 1000 });
    seen.add(hex);
  }
  for (const hex of planes.keys()) if (!seen.has(hex)) planes.delete(hex);
}

// Keeps the positions fresh while `on`; stops asking when off.
export function watchPlanes(on) {
  if (!on) { clearInterval(timer); timer = 0; return; }
  if (timer) return;
  const ask = () => { if (!document.hidden) refresh().catch(() => {}); };
  ask();
  timer = setInterval(ask, EVERY_MS);
}

// The aircraft now, for drawing: [{ hex, flight, type, up, speed, track, position: [lon, lat, m] }]
export function planesNow() {
  const now = Date.now();
  return Array.from(planes, ([hex, p]) => {
    const s = Math.min(COAST_S, Math.max(0, (now - p.at) / 1000));
    return { hex, flight: p.flight, type: p.type, up: p.up, speed: p.speed, track: p.track,
      position: [p.lon + (p.east * s) / M_PER_LON, p.lat + (p.north * s) / M_PER_LAT, p.up] };
  });
}

// An aircraft seen from above, one long, nose towards +x: body, wings, tailplane and a fin.
export function planeMesh() {
  const positions = [], normals = [];
  const flat = (...pts) => {
    for (let i = 1; i + 1 < pts.length; i++) for (const p of [pts[0], pts[i], pts[i + 1]]) { positions.push(p[0], p[1], 0.02); normals.push(0, 0, 1); }
  };
  flat([0.5, 0], [0.42, 0.045], [-0.42, 0.045], [-0.5, 0.02], [-0.5, -0.02], [-0.42, -0.045], [0.42, -0.045]);   // body
  flat([0.12, 0.04], [-0.08, 0.5], [-0.17, 0.5], [-0.1, 0.04]);       // left wing
  flat([0.12, -0.04], [-0.1, -0.04], [-0.17, -0.5], [-0.08, -0.5]);   // right wing
  flat([-0.36, 0.03], [-0.46, 0.19], [-0.5, 0.19], [-0.47, 0.03]);    // tailplane, left
  flat([-0.36, -0.03], [-0.47, -0.03], [-0.5, -0.19], [-0.46, -0.19]);
  for (const p of [[-0.3, 0, 0.02], [-0.5, 0, 0.02], [-0.5, 0, 0.16]]) { positions.push(...p); normals.push(0, 1, 0); }   // fin
  return { positions: { value: new Float32Array(positions), size: 3 }, normals: { value: new Float32Array(normals), size: 3 } };
}
