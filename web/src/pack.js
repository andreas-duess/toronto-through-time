// Reads the packed building files written by pipeline/pack.py (the format is described there).
const STEP = 2e-6;

async function unpack(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return new Response(r.body.pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
}

export const fetchPacked = (url, Type) => unpack(url).then((b) => new Type(b));

// decimetres to metres
export const fetchMetres = (url) => unpack(url).then((b) => Float32Array.from(new Uint16Array(b), (v) => v / 10));

// vertices per building to start indices
export async function fetchStarts(url) {
  const counts = new Uint16Array(await unpack(url));
  const starts = new Uint32Array(counts.length + 1);
  for (let i = 0; i < counts.length; i++) starts[i + 1] = starts[i] + counts[i];
  return starts;
}

// Positions as [x, y] or, with bases (one ground level per building), [x, y, z].
export async function fetchPositions(url, starts, bases) {
  const bytes = new Uint8Array(await unpack(url));
  const n = bytes.length / 8, size = bases ? 3 : 2;
  const out = new Float32Array(n * size);
  let x = 0, y = 0;
  for (let i = 0, k = 0; i < n; i++, k += 2) {
    x += bytes[k] | (bytes[2 * n + k] << 8) | (bytes[4 * n + k] << 16) | (bytes[6 * n + k] << 24);
    y += bytes[k + 1] | (bytes[2 * n + k + 1] << 8) | (bytes[4 * n + k + 1] << 16) | (bytes[6 * n + k + 1] << 24);
    out[i * size] = x * STEP;
    out[i * size + 1] = y * STEP;
  }
  if (bases) for (let b = 0; b < bases.length; b++) for (let i = starts[b]; i < starts[b + 1]; i++) out[i * 3 + 2] = bases[b];
  return out;
}
