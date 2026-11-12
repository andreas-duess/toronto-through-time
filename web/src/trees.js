import { fetchPacked, fetchPositions } from "./pack.js";

// Today's trees, placed by pipeline/trees.py from the city's canopy study: where each stands
// (offsets from the map's origin) and its crown radius in metres. They come in three sets, a
// quarter, a quarter and a half of them, each spread over the whole city: from far away only the
// first set is drawn.
export async function loadTrees(dir) {
  const [positions, sizes] = await Promise.all([
    fetchPositions(dir + "trees.positions.pack"),
    fetchPacked(dir + "trees.sizes.pack", Uint8Array),
  ]);
  const sets = [[], [], []];
  for (let i = 0; i < sizes.length; i++) sets[Math.min(2, (i * 7919) % 4)].push(i);
  return sets.map((ids) => ({
    length: ids.length,
    positions: Float32Array.from({ length: ids.length * 2 }, (_, k) => positions[ids[k >> 1] * 2 + (k & 1)]),
    sizes: Uint8Array.from(ids, (i) => sizes[i]),
  }));
}

// A tree of crown radius 1: a five-sided crown, pointed at both ends, three radii tall. The
// corners are shared between the sides, which keeps the work per tree small.
export function treeMesh() {
  const SIDES = 5, FOOT = 0.15, WIDEST = 1.3, TOP = 2.8;
  const positions = [0, 0, FOOT, 0, 0, TOP], normals = [0, 0, -1, 0, 0, 1], indices = [];
  for (let k = 0; k < SIDES; k++) {
    const x = Math.cos((k * 2 * Math.PI) / SIDES), y = Math.sin((k * 2 * Math.PI) / SIDES);
    positions.push(x, y, WIDEST);
    normals.push(x * 0.9, y * 0.9, 0.44);
    const a = 2 + k, b = 2 + ((k + 1) % SIDES);
    indices.push(0, b, a, 1, a, b);
  }
  return {
    indices: new Uint16Array(indices),
    attributes: {
      positions: { value: new Float32Array(positions), size: 3 },
      normals: { value: new Float32Array(normals), size: 3 },
    },
  };
}

// a few greens, so that a row of trees is not one colour
export const TREE_COLORS = [[122, 158, 96], [134, 168, 104], [110, 148, 92], [142, 172, 112]];
