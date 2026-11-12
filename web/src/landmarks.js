import { earcut } from "@math.gl/polygon";

// Landmarks built by hand from simple shapes, in metres east, north and up from each one's own
// origin. Heights and dates marked "source" in FACTS come from the cited article; everything else
// (widths, roof curves, stand heights) is judged from the outline and from photographs.

class Mesh {
  constructor() {
    this.positions = [];
    this.normals = [];
    this.colors = [];
    this.rgb = [1, 1, 1];
  }

  color(hex) {
    const v = parseInt(hex.slice(1), 16);
    this.rgb = [(v >> 16) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
    return this;
  }

  // corners counter-clockwise seen from outside
  tri(a, b, c) {
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    const n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
    const len = Math.hypot(...n) || 1;
    for (const p of [a, b, c]) {
      this.positions.push(...p);
      this.normals.push(n[0] / len, n[1] / len, n[2] / len);
      this.colors.push(...this.rgb);
    }
  }

  quad(a, b, c, d) {
    this.tri(a, b, c);
    this.tri(a, c, d);
  }

  // Walls between rings of equal length, bottom ring first, each counter-clockwise seen from above.
  loft(rings) {
    for (let k = 0; k + 1 < rings.length; k++) {
      const lower = rings[k], upper = rings[k + 1];
      for (let i = 0; i < lower.length; i++) {
        const j = (i + 1) % lower.length;
        this.quad(lower[i], lower[j], upper[j], upper[i]);
      }
    }
    return this;
  }

  // A flat or sloping face over a ring of any shape; up says which way it faces.
  cap(ring, up = true) {
    const index = earcut(ring.flatMap((p) => [p[0], p[1]]));
    for (let i = 0; i < index.length; i += 3) {
      const [a, b, c] = [ring[index[i]], ring[index[i + 1]], ring[index[i + 2]]];
      const ccw = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 0;
      if (ccw === up) this.tri(a, b, c); else this.tri(a, c, b);
    }
    return this;
  }

  // A shape turned about the vertical axis: profile is [radius, height] pairs from the bottom up.
  lathe(profile, sides = 24, turn = 0) {
    this.loft(profile.map(([r, z]) => circle(r, z, sides, turn)));
    const [top] = profile.slice(-1);
    if (top[0] > 0.01) this.cap(circle(top[0], top[1], sides, turn));
    return this;
  }

  // An outline pushed straight up from z0 to z1, with a roof.
  prism(outline, z0, z1) {
    const ring = ccw(outline);
    this.loft([ring.map(([x, y]) => [x, y, z0]), ring.map(([x, y]) => [x, y, z1])]);
    return this.cap(ring.map(([x, y]) => [x, y, z1]));
  }

  build() {
    return { attributes: {
      positions: { value: new Float32Array(this.positions), size: 3 },
      normals: { value: new Float32Array(this.normals), size: 3 },
      colors: { value: new Float32Array(this.colors), size: 3 },
    } };
  }
}

const circle = (r, z, sides, turn = 0) => Array.from({ length: sides }, (_, i) => {
  const a = turn + (i / sides) * 2 * Math.PI;
  return [r * Math.cos(a), r * Math.sin(a), z];
});

function ccw(outline) {
  let area = 0;
  outline.forEach(([x, y], i) => { const [u, v] = outline[(i + 1) % outline.length]; area += x * v - u * y; });
  return area > 0 ? outline : [...outline].reverse();
}

const CONCRETE = "#cdc8bc";

// CN Tower. Source: 553.3 m to the tip; antenna 102 m; The Top at 447 m; main pod with decks at
// 342 to 356 m above a white radome at 338 m; a hexagonal core with three legs blended in below
// the pod. Widths are judged from the 52 m footprint and photographs.
function cnTower() {
  const m = new Mesh().color(CONCRETE);
  m.lathe([[12, 0], [9.5, 330], [7, 440]], 6, Math.PI / 6);
  // three legs, wide at the ground and gone by the pod
  const levels = [0, 20, 50, 90, 140, 200, 260, 330];
  for (let leg = 0; leg < 3; leg++) {
    const a = Math.PI / 2 + (leg * 2 * Math.PI) / 3;
    const out = [Math.cos(a), Math.sin(a)], side = [-Math.sin(a), Math.cos(a)];
    m.loft(levels.map((z) => {
      const reach = 9 + 20 * (1 - z / 330) ** 1.8;
      const half = 2 + 2.2 * (1 - z / 330);
      const at = (r, s) => [out[0] * r + side[0] * s, out[1] * r + side[1] * s, z];
      return [at(4, -half), at(reach, -half), at(reach, half), at(4, half)];
    }));
  }
  m.color("#f1f0ea").lathe([[9.5, 329], [17, 331.5], [19, 335], [17.5, 338.5]], 28);
  m.color("#6f7680").lathe([[15.5, 338.5], [18.5, 342], [19.5, 347], [19, 352], [16.5, 356], [8, 357.5]], 28);
  m.color(CONCRETE).lathe([[7, 440], [8.5, 443], [8.5, 449], [5, 451.3]], 16);
  m.color("#e9e7e1").lathe([[3.4, 451.3], [2.4, 500], [1.2, 535], [0.5, 553.3]], 8);
  return m.build();
}

// Rogers Centre. Source: opened 3 June 1989, ground broken 3 October 1986; the roof is 86 m
// (31 storeys) high. The outline is OpenStreetMap's; the height of the wall and the curve of
// the roof are judged from photographs.
function rogersCentre({ outline }) {
  const WALL = 36, TOP = 86;
  const ring = ccw(outline);
  const m = new Mesh().color("#c8c2b6");
  m.loft([ring.map(([x, y]) => [x, y, 0]), ring.map(([x, y]) => [x, y, WALL])]);
  // the roof: the outline drawn in towards the middle as it rises
  const cx = ring.reduce((s, p) => s + p[0], 0) / ring.length;
  const cy = ring.reduce((s, p) => s + p[1], 0) / ring.length;
  const steps = 10;
  m.color("#efede7").loft(Array.from({ length: steps + 1 }, (_, k) => {
    const t = (k / steps) * (Math.PI / 2) * 0.96;
    return ring.map(([x, y]) => [cx + (x - cx) * Math.cos(t), cy + (y - cy) * Math.cos(t), WALL + (TOP - WALL) * Math.sin(t)]);
  }));
  const t = (Math.PI / 2) * 0.96;
  m.cap(ring.map(([x, y]) => [cx + (x - cx) * Math.cos(t), cy + (y - cy) * Math.cos(t), WALL + (TOP - WALL) * Math.sin(t)]));
  return m.build();
}

// BMO Field. Source: opened 2007; pitch 105 by 68 m; an upper deck on the east stand and a roof
// over the seats added between 2014 and 2016 (deck by May 2015, roof by May 2016). Outlines of
// the pitch and the four stands are OpenStreetMap's; every height is judged from photographs.
function stand(m, outline, front, back) {
  const ring = ccw(outline);
  // seats rise from the side nearest the pitch (the origin) to the side furthest from it
  const cx = ring.reduce((s, p) => s + p[0], 0) / ring.length;
  const cy = ring.reduce((s, p) => s + p[1], 0) / ring.length;
  const len = Math.hypot(cx, cy);
  const far = ring.map(([x, y]) => (x * cx + y * cy) / len);
  const lo = Math.min(...far), hi = Math.max(...far);
  const top = ring.map(([x, y], i) => [x, y, front + (back - front) * ((far[i] - lo) / (hi - lo))]);
  m.loft([ring.map(([x, y]) => [x, y, 0]), top]).cap(top);
}

function bmoField({ pitch, stands }) {
  const base = new Mesh().color("#5f9a58");
  base.prism(pitch, 0, 0.4);
  base.color("#c4c0b6");
  stand(base, stands.west, 3, 17);
  stand(base, stands.east, 3, 13);
  stand(base, stands.south, 3, 11);
  stand(base, stands.north, 2, 7);
  const deck = new Mesh().color("#b9b5ab");
  stand(deck, stands.east, 13, 27);
  const roof = new Mesh().color("#f0eee8");
  for (const [side, z] of [["west", 27], ["east", 34], ["south", 20]]) roof.prism(stands[side], z, z + 1.2);
  return { base: base.build(), deck: deck.build(), roof: roof.build() };
}

// One entry per piece that has its own dates: built from `from` (work starts) to `to` (finished).
export function landmarkParts(data) {
  const bmo = bmoField(data.bmoField);
  return [
    { id: "cn-tower", key: "cnTower", mesh: cnTower(), from: 1973.1, to: 1976.48 },
    { id: "rogers-centre", key: "rogersCentre", mesh: rogersCentre(data.rogersCentre), from: 1986.76, to: 1989.42 },
    { id: "bmo-field", key: "bmoField", mesh: bmo.base, from: 2006.73, to: 2007.33 },
    { id: "bmo-field-deck", key: "bmoField", mesh: bmo.deck, from: 2014.7, to: 2015.33 },
    { id: "bmo-field-roof", key: "bmoField", mesh: bmo.roof, from: 2015.7, to: 2016.33 },
  ].map((p) => ({ ...p, origin: data[p.key].origin }));
}

export const FACTS = {
  cnTower: { name: "CN Tower", url: "https://en.wikipedia.org/wiki/CN_Tower", replaces: ["CN Tower"], rows: [
    ["Built", "1973 to 1976; opened 26 June 1976"],
    ["Height", "553.3 m, of which the antenna is 102 m"],
    ["Model", "Heights from the article; widths judged from the footprint and photographs"],
  ] },
  rogersCentre: { name: "Rogers Centre", url: "https://en.wikipedia.org/wiki/Rogers_Centre", replaces: ["Rogers Centre"], rows: [
    ["Built", "1986 to 1989; opened 3 June 1989 as SkyDome"],
    ["Height", "86 m to the top of the roof"],
    ["Model", "Outline from OpenStreetMap; roof curve judged from photographs; shown with the roof closed"],
  ] },
  bmoField: { name: "BMO Field", url: "https://en.wikipedia.org/wiki/BMO_Field", replaces: [], rows: [
    ["Built", "Opened 2007; east upper deck 2015; roof 2016"],
    ["Pitch", "105 by 68 m"],
    ["Model", "Outlines from OpenStreetMap; all heights judged from photographs"],
  ] },
};
