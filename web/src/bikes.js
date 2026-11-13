// Bike Share Toronto's stations and how many bikes each has now, from its public feed (GBFS).
const FEED = "https://tor.publicbikesystem.net/ube/gbfs/v1/en/";
const EVERY_MS = 60000;
const BOX = [-79.52, 43.6, -79.26, 43.73];

let stations = [];     // [{ id, name, position, capacity, bikes, ebikes, docks }]
let places = null;     // id -> station, from station_information (asked once)
let timer = 0;

async function refresh(onChange) {
  if (!places) {
    const info = await fetch(FEED + "station_information").then((r) => r.json());
    places = new Map();
    for (const s of info.data.stations) {
      if (s.lon > BOX[0] && s.lon < BOX[2] && s.lat > BOX[1] && s.lat < BOX[3]) {
        places.set(s.station_id, { id: s.station_id, name: s.name.replace(/\s+/g, " "), position: [s.lon, s.lat, 0], capacity: s.capacity });
      }
    }
  }
  const status = await fetch(FEED + "station_status").then((r) => r.json());
  const next = [];
  for (const s of status.data.stations) {
    const place = places.get(s.station_id);
    if (!place || s.status !== "IN_SERVICE") continue;
    next.push({ ...place, bikes: s.num_bikes_available, ebikes: s.num_bikes_available_types?.ebike ?? 0, docks: s.num_docks_available });
  }
  stations = next;
  onChange();
}

// Keeps the counts fresh while `on`; onChange is called when new counts are in.
export function watchBikes(on, onChange) {
  if (!on) { clearInterval(timer); timer = 0; return; }
  if (timer) return;
  const ask = () => { if (!document.hidden) refresh(onChange).catch(() => {}); };
  ask();
  timer = setInterval(ask, EVERY_MS);
}

// the same list until the next counts come in, so that the layer is only worked out again then
export const bikeStations = () => stations;
