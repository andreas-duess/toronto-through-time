import { fetchPacked, fetchPositions } from "./pack.js";

// The sloped roofs of the houses, from pipeline/build.py: for each, the building it sits on, its
// middle (offsets from the map's origin), length, width, eaves and rise in metres, and the
// direction of the ridge in degrees anticlockwise from east. In order of the buildings' years.
export async function loadRoofs(dir) {
  const [ids, positions, info] = await Promise.all([
    fetchPacked(dir + "roofs.ids.pack", Uint32Array),
    fetchPositions(dir + "roofs.positions.pack"),
    fetchPacked(dir + "roofs.info.pack", Uint16Array),
  ]);
  const size = Float32Array.from(info, (v, i) => (i % 5 === 4 ? (v / 65535) * 180 : v / 100));
  return { length: ids.length, ids, positions, size };
}

// A gable roof one long, one wide and one high: the ridge along x, the eaves at 0. The sides of a
// roof are stretched very differently, which tilts the normals with them; they are set here so
// that a roof about two and a half times as wide as it is high is lit right.
export function roofMesh() {
  const positions = [], normals = [];
  const face = (normal, ...corners) => {
    for (const c of corners) { positions.push(...c); normals.push(...normal); }
  };
  const a = [-0.5, -0.5, 0], b = [0.5, -0.5, 0], c = [0.5, 0.5, 0], d = [-0.5, 0.5, 0], r0 = [-0.5, 0, 1], r1 = [0.5, 0, 1];
  face([0, -0.32, 0.95], a, b, r1, a, r1, r0);
  face([0, 0.32, 0.95], c, d, r0, c, r0, r1);
  face([-1, 0, 0], d, a, r0);
  face([1, 0, 0], b, c, r1);
  return { positions: { value: new Float32Array(positions), size: 3 }, normals: { value: new Float32Array(normals), size: 3 } };
}
