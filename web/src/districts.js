// The former municipalities outside the old city (pipeline/district.py): loaded piece by piece as
// the view reaches them. A district has an index of square cells; a cell is one file with its
// buildings and the sloped roofs of its houses.
const STEP = 2e-6;

async function gunzip(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return new Response(r.body.pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
}

// positions packed as pipeline/pack.py packs them: `n` points from `bytes`, as [x, y, ...] with `size` numbers a point
function unpackPoints(bytes, n, size) {
  const out = new Float32Array(n * size);
  let x = 0, y = 0;
  for (let i = 0, k = 0; i < n; i++, k += 2) {
    x += bytes[k] | (bytes[2 * n + k] << 8) | (bytes[4 * n + k] << 16) | (bytes[6 * n + k] << 24);
    y += bytes[k + 1] | (bytes[2 * n + k + 1] << 8) | (bytes[4 * n + k + 1] << 16) | (bytes[6 * n + k + 1] << 24);
    out[i * size] = x * STEP;
    out[i * size + 1] = y * STEP;
  }
  return out;
}

function readCell(buffer) {
  const [buildings, corners, roofs] = new Uint32Array(buffer, 0, 4);
  let at = 16;
  const take = (Type, n) => { const a = new Type(buffer.slice(at, at + n * Type.BYTES_PER_ELEMENT)); at += n * Type.BYTES_PER_ELEMENT; return a; };
  const counts = take(Uint16Array, buildings);
  const heights = Float32Array.from(take(Uint16Array, buildings), (v) => v / 10);
  const bases = take(Uint16Array, buildings);
  const years = take(Uint16Array, buildings);
  const positions = unpackPoints(take(Uint8Array, corners * 8), corners, 3);
  const startIndices = new Uint32Array(buildings + 1);
  for (let b = 0; b < buildings; b++) {
    startIndices[b + 1] = startIndices[b] + counts[b];
    for (let i = startIndices[b]; i < startIndices[b + 1]; i++) positions[i * 3 + 2] = bases[b] / 10;
  }
  const cell = { heights, years, data: { length: buildings, startIndices, attributes: { getPolygon: { value: positions, size: 3 } } }, roofs: null };
  if (roofs) {
    const of = take(Uint32Array, roofs);
    const middles = unpackPoints(take(Uint8Array, roofs * 8), roofs, 2);
    const size = Float32Array.from(take(Uint16Array, roofs * 5), (v, i) => (i % 5 === 4 ? (v / 65535) * 180 : v / 100));
    cell.roofs = { length: roofs, of, middles, size };
  }
  return cell;
}

const districts = [];     // { dir, name, from, cells: [{ file, box, state: undefined | "loading" | cell }] }

export async function loadDistricts(dir, names) {
  for (const name of names) {
    const index = await fetch(`${dir}d/${name}/index.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (index) districts.push({ ...index, slug: name, dir: `${dir}d/${name}/` });
  }
  return districts;
}

// The cells of the districts shown in `year` that lie in the view box [w, s, e, n]; those not yet
// loaded are fetched, and `onLoad` is called as each arrives.
export function districtCells(year, box, onLoad) {
  const out = [];
  for (const d of districts) {
    if (year < d.from) continue;
    for (const c of d.cells) {
      if (c.box[0] > box[2] || c.box[2] < box[0] || c.box[1] > box[3] || c.box[3] < box[1]) continue;
      if (!c.state) {
        c.state = "loading";
        gunzip(d.dir + c.file).then((buffer) => { c.state = readCell(buffer); onLoad(); }).catch(() => { c.state = undefined; });
      } else if (c.state !== "loading") {
        out.push({ id: `${d.slug}-${c.file}`, ...c.state });
      }
    }
  }
  return out;
}
