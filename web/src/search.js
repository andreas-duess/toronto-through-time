// Search over what the page has already loaded: the landmark models, the places on the map, the
// names of buildings and the street addresses of the old city. No geocoder: an address outside the
// old city, or one the city's address points do not give, is not found.

const SHORT = { street: "st", avenue: "ave", av: "ave", road: "rd", drive: "dr", boulevard: "blvd", crescent: "cres",
  place: "pl", court: "crt", square: "sq", terrace: "terr", lane: "ln", gardens: "gdns", circle: "crcl",
  east: "e", west: "w", north: "n", south: "s", saint: "st" };
// landmarks before places, places before named buildings, names before addresses
const RANK = { landmark: 0, place: 1, name: 2, address: 3 };

export function words(text) {
  return text.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/['’.]/g, "")
    .split(/[^a-z0-9]+/).filter(Boolean).map((w) => SHORT[w] ?? w);
}

// entries: { label, sub, kind, lon, lat, building, landmark, from, to }
export function searchIndex({ facts, models, names, addresses, centres, origin, replaced, places }) {
  const entries = [];
  for (const [key, fact] of Object.entries(facts)) {
    if (models[key]) entries.push({ label: fact.name, sub: "Landmark", kind: "landmark", landmark: key,
      lon: models[key].origin[0], lat: models[key].origin[1] });
  }
  for (const f of places.features ?? []) {
    const p = f.properties;
    entries.push({ label: p.name, sub: `${p.from} to ${p.to < 2026 ? p.to : "today"}`, kind: "place",
      lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], from: p.from, to: p.to });
  }
  // a name or an address shared by several buildings close together is one place; far apart, several
  const group = (kind, key, i, sub) => {
    const lon = centres[i * 2] + origin[0], lat = centres[i * 2 + 1] + origin[1];
    const near = (byKey.get(key) ?? []).find((e) => Math.abs(e.lon - lon) < 0.003 && Math.abs(e.lat - lat) < 0.002);
    if (near) { near.buildings.push(i); return; }
    const e = { label: key, sub, kind, lon, lat, building: i, buildings: [i] };
    byKey.set(key, [...(byKey.get(key) ?? []), e]);
    entries.push(e);
  };
  let byKey = new Map();
  const landmarkNames = new Set(Object.values(facts).map((f) => f.name));
  for (const [k, n] of Object.entries(names)) {
    const i = Number(k);
    if (!replaced.has(i) && !landmarkNames.has(n.name)) group("name", n.name, i, addresses[i] || "Building");
  }
  byKey = new Map();
  addresses.forEach((a, i) => { if (a && !replaced.has(i)) group("address", a, i, names[i]?.name ?? "Address"); });
  for (const e of entries) e.words = words(e.label);
  return entries;
}

// Every word but the last must be a whole word of the entry; the last may be the start of one.
export function search(entries, query, limit = 8) {
  const q = words(query);
  if (!q.length) return [];
  const last = q.pop();
  const hits = [];
  for (const e of entries) {
    if (!q.every((w) => e.words.includes(w))) continue;
    if (!e.words.some((w) => w.startsWith(last))) continue;
    const first = e.words[0] === (q[0] ?? last) || e.words[0].startsWith(q[0] ?? last);
    hits.push([RANK[e.kind] - (first ? 0.5 : 0), e.label.length, e]);
  }
  hits.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  return hits.slice(0, limit).map((h) => h[2]);
}
