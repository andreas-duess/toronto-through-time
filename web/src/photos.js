// Photographs, in order of year. Two kinds: City of Toronto Archives pictures placed on the map by
// OldTO (pipeline/photos.py), and from 1990 on photographs from Wikimedia Commons, located and dated
// by the people who took them (pipeline/commons.py; rows of [lon, lat, year, file, author, licence]). Shown as pins for the pictures taken within SPAN years of the year on
// the slider; pictures that would sit on top of each other share a pin.
const SPAN = 2;
let base = "", photos = null;   // [lon, lat, year, about, file, title, citation]

export async function loadPhotos(url, commonsUrl) {
  const d = await fetch(url).then((r) => r.json());
  base = d.base;
  photos = d.photos;
  // the Commons photographs come after; the two lists are merged by year
  fetch(commonsUrl).then((r) => (r.ok ? r.json() : [])).then((more) => {
    if (more.length) photos = [...photos, ...more.map((m) => Object.assign(m, { commons: true }))].sort((a, b) => a[2] - b[2]);
  }).catch(() => {});
}

// The pins for a year: [{ position, ids }], one per square of `cell` degrees with a picture in it,
// at the place of its first picture. The pictures of a pin are in order of how near their year is.
export function photoPins(year, cell) {
  if (!photos) return [];
  let lo = 0, hi = photos.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (photos[mid][2] < year - SPAN) lo = mid + 1; else hi = mid; }
  const pins = new Map();
  for (let i = lo; i < photos.length && photos[i][2] <= year + SPAN; i++) {
    const key = `${Math.round(photos[i][0] / cell)},${Math.round(photos[i][1] / (cell * 0.72))}`;
    if (!pins.has(key)) pins.set(key, { position: [photos[i][0], photos[i][1], 0], ids: [] });
    pins.get(key).ids.push(i);
  }
  const out = [...pins.values()];
  for (const p of out) p.ids.sort((a, b) => Math.abs(photos[a][2] - year) - Math.abs(photos[b][2] - year));
  return out;
}

export function photo(i) {
  if (photos[i].commons) {
    const [, , taken, name, author, licence] = photos[i];
    const page = `https://commons.wikimedia.org/wiki/File:${encodeURIComponent(name.replace(/ /g, "_"))}`;
    return { commons: true, year: String(taken), title: name.replace(/\.[a-z]+$/i, "").replace(/_/g, " "), author, licence, page,
      image: `https://commons.wikimedia.org/wiki/Special:FilePath/${encodeURIComponent(name.replace(/ /g, "_"))}?width=900` };
  }
  const [, , year, about, file, title, citation] = photos[i];
  return { year: `${about ? "about " : ""}${year}`, title, citation, image: `${base}${file}.jpg` };
}

// a round pin with a camera on it, as a picture for the icon layer
export function cameraIcon() {
  const c = document.createElement("canvas");
  c.width = c.height = 96;
  const g = c.getContext("2d");
  g.scale(1.5, 1.5);
  g.beginPath(); g.arc(32, 32, 29, 0, 6.3); g.fillStyle = "#2f4858"; g.fill();
  g.lineWidth = 3; g.strokeStyle = "#fff"; g.stroke();
  g.fillStyle = "#fff";
  g.beginPath(); g.roundRect(15, 23, 34, 23, 4); g.fill();
  g.beginPath(); g.roundRect(25, 18, 14, 8, 2); g.fill();
  g.beginPath(); g.arc(32, 34.5, 7.5, 0, 6.3); g.fillStyle = "#2f4858"; g.fill();
  g.beginPath(); g.arc(32, 34.5, 3.5, 0, 6.3); g.fillStyle = "#fff"; g.fill();
  return c.toDataURL();
}
