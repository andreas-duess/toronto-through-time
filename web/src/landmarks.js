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

// The old Trinity College, Queen Street West. Source: built 1851 to Kivas Tully's design, opened
// January 1852, demolished in the 1950s. The footprint is the one on Goad's plan of 1913. Every
// height, and the tower and turrets on the south front, are judged from an early postcard view:
// three storeys under steep roofs, a tall central tower with a lantern, smaller turrets beside
// it and at the ends.
function trinityCollege({ outline, roof, front }) {
  const EAVES = 11, RIDGE = 15.5;
  const m = new Mesh().color("#d9cfb8");
  m.prism(outline, 0, EAVES);
  m.color("#7c8087").prism(roof, EAVES, RIDGE);
  // along the front and into the building
  const [a, b] = front;
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const along = [(b[0] - a[0]) / len, (b[1] - a[1]) / len];
  let inward = [-along[1], along[0]];
  const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  if (inward[0] * -mid[0] + inward[1] * -mid[1] < 0) inward = [along[1], -along[0]];
  const turn = Math.atan2(along[1], along[0]);
  const at = (s, d) => [mid[0] + along[0] * s + inward[0] * d, mid[1] + along[1] * s + inward[1] * d];
  const tower = (s, d, r, top, sides) => {
    const [x, y] = at(s, d);
    const shaft = new Mesh();
    shaft.rgb = m.rgb;
    shaft.lathe([[r, 0], [r, top * 0.8], [r * 0.72, top * 0.8], [r * 0.72, top * 0.93]], sides, turn + Math.PI / sides);
    m.positions.push(...shaft.positions.map((v, i) => v + (i % 3 === 0 ? x : i % 3 === 1 ? y : 0)));
    m.normals.push(...shaft.normals);
    m.colors.push(...shaft.colors);
    const cap = new Mesh().color("#7c8087").lathe([[r * 0.8, top * 0.93], [0.05, top]], sides, turn + Math.PI / sides);
    m.positions.push(...cap.positions.map((v, i) => v + (i % 3 === 0 ? x : i % 3 === 1 ? y : 0)));
    m.normals.push(...cap.normals);
    m.colors.push(...cap.colors);
  };
  m.color("#d9cfb8");
  tower(0, 7, 4.2, 31, 8);                                   // central tower with its lantern
  for (const s of [-7, 7]) tower(s, 3, 1.6, 22, 8);          // turrets beside the entrance
  for (const s of [-0.3, 0.3]) tower(s * len, 4, 1.8, 19, 8); // and towards the ends of the front
  return m.build();
}

// A building:part as OpenStreetMap maps it (pipeline/models.py): walls from its foot up to the
// eaves, and a roof of its tagged shape and height over them. Each roof is the outline at the eaves
// drawn in to a ridge, a point or a smaller ring: a gabled roof's corners go to the ridge line along
// the longest side (across it if tagged so), a hipped roof's to a ridge shortened by the width, a
// pyramid's to the middle. Skillion roofs slope down towards their tagged direction.
const middle = (ring) => [0, 1].map((k) => ring.reduce((s, p) => s + p[k], 0) / ring.length);

function longestSide(ring) {
  let [ax, ay] = [1, 0], longest = 0;
  ring.forEach(([x, y], i) => {
    const [u, v] = ring[(i + 1) % ring.length], len = Math.hypot(u - x, v - y);
    if (len > longest) [longest, ax, ay] = [len, (u - x) / len, (v - y) / len];
  });
  return [ax, ay];
}

function osmPart(m, p, wall, roof) {
  const ring = ccw(p.ring);
  const at = (z) => ring.map(([x, y]) => [x, y, z]);
  const eaves = p.top - p.roof;
  m.color(wall);
  if (p.foot > 0) m.cap(at(p.foot), false);
  if (p.shape === "skillion" && p.direction != null && p.roof > 0) {
    const d = (p.direction * Math.PI) / 180, s = ring.map(([x, y]) => x * Math.sin(d) + y * Math.cos(d));
    const lo = Math.min(...s), hi = Math.max(...s);
    const top = ring.map(([x, y], i) => [x, y, p.top - (p.roof * (s[i] - lo)) / (hi - lo || 1)]);
    m.loft([at(p.foot), top]).color(roof).cap(top);
    return;
  }
  if (!(p.roof > 0) || !["gabled", "hipped", "pyramidal", "cone", "dome", "round", "onion"].includes(p.shape)) {
    const z = p.roof > 0 ? p.top - p.roof / 2 : p.top;     // other shapes: flat at half the roof
    m.loft([at(p.foot), at(z)]).cap(at(z));
    return;
  }
  m.loft([at(p.foot), at(eaves)]).color(roof);
  const [cx, cy] = middle(ring);
  let rings;
  if (p.shape === "gabled" || p.shape === "hipped") {
    let [ax, ay] = longestSide(ring);
    if (p.across) [ax, ay] = [-ay, ax];
    const along = ring.map(([x, y]) => (x - cx) * ax + (y - cy) * ay);
    const wide = ring.map(([x, y]) => Math.abs((x - cx) * -ay + (y - cy) * ax));
    const reach = p.shape === "hipped" ? Math.max(0, Math.max(...along.map(Math.abs)) - Math.max(...wide)) : Infinity;
    rings = [ring.map((_, i) => {
      const t = Math.max(-reach, Math.min(reach, along[i]));
      return [cx + ax * t, cy + ay * t, p.top];
    })];
  } else {
    const steps = p.shape === "onion" ? [[1.2, 0.25], [1.05, 0.5], [0.55, 0.75], [0.2, 0.9], [0, 1]]
      : p.shape === "dome" || p.shape === "round" ? [1, 2, 3, 4, 5, 6].map((k) => [Math.cos((k * Math.PI) / 12), Math.sin((k * Math.PI) / 12)])
      : [[0, 1]];
    rings = steps.map(([r, h]) => ring.map(([x, y]) => [cx + (x - cx) * r, cy + (y - cy) * r, eaves + p.roof * h]));
  }
  m.loft([at(eaves), ...rings]);
}

// Casa Loma. Source: built 1911 to 1914 to E. J. Lennox's design; work stopped with the war in
// 1914 and parts of the inside were never finished. Shapes and heights are OpenStreetMap's, whose
// mappers estimated the heights; colours (grey-buff stone, red-brown tile roofs) are judged from a
// photograph.
function casaLoma({ parts }) {
  const m = new Mesh();
  for (const p of parts) osmPart(m, p, "#c2b8a5", "#8f5244");
  return m.build();
}

// St. James' Cathedral. Source: built from 1850 and opened 19 June 1853; Henry Langley's tower and
// spire, 92.9 m, were finished 1873 to 1874; white (buff) brick and Ohio sandstone. Shapes and
// heights are OpenStreetMap's; the copper green of the roofs and spire is judged from a photograph.
function stJames({ parts }, tower) {
  const m = new Mesh();
  for (const p of parts.filter((q) => q.tower === tower)) {
    const stone = p.shape === "pyramidal" && p.roof < 5;      // the pinnacles
    osmPart(m, p, "#cfbb91", stone ? "#cfbb91" : "#6e9c86");
  }
  return m.build();
}

// OCAD's main building and the Sharp Centre for Design, 100 McCaul Street. Source: George Reid's
// wing opened 1921 and the A. J. Casson wing 17 January 1957 (floors and an atrium added in 1963,
// 1967 and 1981 are not shown apart); Will Alsop's tabletop, chosen in 2002 and finished in 2004,
// is 84 by 31 m and 9 m deep, 26 m above the ground, on multi-coloured pillars at different angles.
// Outlines are OpenStreetMap's, and so are the two cores that carry the box; the Casson wing's
// 13 m is the city's measured height. The colours of the pillars (mostly black, with blue, yellow,
// purple and white ones and a red brace), their steep angles and the red-brown brick below are
// from photographs; the number and places of the pillars are judged from them.
const PILLARS = ["#262626", "#3a6db5", "#d9b324", "#d9b324", "#262626", "#7b4f9d", "#e4e1d9", "#262626",
  "#3a6db5", "#262626", "#d9b324", "#7b4f9d"];

function ocad({ table, reid, main, cores }) {
  const old = new Mesh();
  osmPart(old, reid, "#9c5e47", "#3f4044");
  const casson = new Mesh().color("#a2654f").prism(main, 0, 13.1);
  const legs = new Mesh().color("#b7b2a8");
  for (const c of cores) legs.prism(c, 0, 26);
  // pillars in pairs along the box, leaning steeply and crossing; the red brace rises from the
  // ground by the old building
  const ring = ccw(table), [cx, cy] = middle(ring), [ax, ay] = longestSide(ring), [nx, ny] = [-ay, ax];
  const pt = (s, w, z) => [cx + ax * s + nx * w, cy + ay * s + ny * w, z];
  const strut = (foot, head, r) => {
    const square = ([x, y, z]) => [[x - r, y - r, z], [x + r, y - r, z], [x + r, y + r, z], [x - r, y + r, z]];
    legs.loft([square(foot), square(head)]);
  };
  [[-34, 4, 9], [-21, -5, -8], [-8, 6, 7], [7, -4, -9], [20, 5, 8], [34, -6, -7]].forEach(([s, lean, shift], k) => {
    for (const side of [-1, 1]) {
      legs.color(PILLARS[k * 2 + (side > 0)]);
      strut(pt(s + side * shift, side * (12 + lean), 0), pt(s - side * shift * 0.3, side * 11, 26), 0.6);
    }
  });
  legs.color("#c23b2e");
  strut(pt(-16, 4, 0), pt(2, 1, 26), 1.5);
  const box = new Mesh().color("#ecebe6").prism(table, 26, 35).cap(ring.map(([x, y]) => [x, y, 26]), false);
  return { reid: old.build(), casson: casson.build(), legs: legs.build(), box: box.build() };
}

// The Royal Ontario Museum. Source: Darling and Pearson's building along Philosopher's Walk opened
// 19 March 1914 (yellow brick); Chapman and Oxley's wing on Queen's Park opened 12 October 1933;
// the terrace galleries along Bloor and the curatorial centre to the south were built 1978 to
// 1984; the terraces were torn down for Libeskind's Crystal (glass and aluminium), opened 2 June
// 2007. Shapes and heights are OpenStreetMap's; which part belongs to which era is read off the
// city's air photos of 1939, 1978 and 1999 (pipeline/models.py), and so are the terraces, whose
// heights are judged; the starts of work in 1910 and 1931, the copper roofs of the 1933 wing and
// the colours are judged from photographs.
function rom({ parts, terraces }, era) {
  const m = new Mesh();
  const look = { 1914: ["#d3bf8c", "#7a7c80"], 1933: ["#c8b99c", "#6e9c86"], 1984: ["#bdb8ae", "#bdb8ae"], 2007: ["#cbcfd3", "#cbcfd3"] }[era];
  for (const p of parts.filter((q) => q.era === era)) osmPart(m, p, ...look);
  if (era === "terraces") for (const t of terraces) m.color("#c4beb2").prism(t.ring, 0, t.top);
  return m.build();
}

// The Art Gallery of Ontario. Source: the first galleries, by Darling and Pearson, opened beside
// the Grange in 1918; Walker Court, its galleries and the Dundas Street entrance 1924 and 1926;
// galleries east and west 1935; the Henry Moore Sculpture Centre, with its skylight, 26 October
// 1974; galleries along Beverley Street 1977; Barton Myers and KPMB's expansion 1993; Frank Gehry's
// Transformation AGO, 2004 to November 2008: the glass Galleria Italia along Dundas and the
// five-storey block of glass and titanium to the south. Shapes and heights are OpenStreetMap's;
// which part belongs to which era is read off the city's air photos of 1939, 1965, 1978 and 1999
// (pipeline/models.py); the 1935 galleries are not told apart from those of 1926, nor the lower
// buildings along Dundas before 1993. Starts of work are judged; colours are OpenStreetMap's.
const AGO_COLOURS = { "#1e90ff": "#5d88b9", "#ADD8E6": "#bcd4de", white: "#e6e2d8" };

function ago({ parts }, era) {
  const m = new Mesh();
  for (const p of parts.filter((q) => q.era === era)) {
    const wall = AGO_COLOURS[p.colour] ?? (era === "2008" ? "#c9ccd0" : "#d9d0bf");
    osmPart(m, p, wall, era === "2008" ? wall : "#9aa2a6");
  }
  return m.build();
}

// A building from OpenStreetMap's parts, all of them or those of one era, in one wall colour and
// one roof colour; domes take the third colour.
function osmBuilding({ parts }, era, wall, roof, dome = roof) {
  const m = new Mesh();
  for (const p of parts.filter((q) => era === undefined || q.era === era)) {
    osmPart(m, p, wall, ["dome", "onion", "round"].includes(p.shape) ? dome : roof);
  }
  return m.build();
}

// Old City Hall. Source: built 1889 to 1899 to E. J. Lennox's design, opened 18 September 1899;
// clock tower 103.6 m; light brown-grey New Brunswick sandstone with darker reddish-brown Sackville
// sandstone. Shapes and heights are OpenStreetMap's; colours are judged from a photograph.
// The Ontario Legislative Building. Source: built from 1886 to Richard Waite's design, opened 4
// April 1893; pink Credit Valley sandstone; G. W. Gouinlock's north wing, closing the courtyard,
// 1909. The west wing, rebuilt after the fire of 1909 with a fourth floor under a gabled roof,
// is shown as it is now from 1893. Shapes and heights are OpenStreetMap's; which part is the north
// wing is read off the city's air photo; the domes' green is judged from a photograph.
// University College. Source: built 1856 to 1859 to Cumberland and Storm's design; stone and pale
// yellow brick; the Laidlaw wing completed in the 1960s (shown from 1964, judged). Shapes and
// heights are OpenStreetMap's; which part is the Laidlaw wing is read off the city's air photo.
// Union Station. Source: built 1914 to 1920 to Ross and Macdonald's design, opened 6 August 1927;
// 229 m long; limestone; the train shed 1929 to 1930; the middle of the shed replaced by a glass
// atrium from 2010 (shown done by 2015, judged). OpenStreetMap maps the Great Hall, the colonnade,
// the sheds and the atrium; the office wings beside the hall are drawn 17 m high (pipeline/models.py).

// The models below are drawn by hand along (u) and across (v) the longest side of each outline
// (pipeline/models.py, uv_frame); every number is in metres in that frame.
function framed([ax, ay]) {
  const at = (u, v) => [ax * u - ay * v, ay * u + ax * v];
  return { at, rect: (u0, u1, v0, v1) => [at(u0, v0), at(u1, v0), at(u1, v1), at(u0, v1)] };
}
const roofOver = (ring, eaves, ridge) => ({ ring, foot: eaves, top: ridge, roof: ridge - eaves, shape: "gabled" });

// St. Michael's Cathedral Basilica. Source: built from 7 April 1845 to William Thomas's design,
// dedicated 29 August 1848; the tower and spire, 79 m, by Gundry and Langley, 1865 to 1867; dormers
// 1890; cream brick with stone, teal shingles. The outline and the tower and spire (to 40 m, the
// spire above) are OpenStreetMap's, and so is the ridge at 27.8 m; the eaves at 14 m and the
// dormers' number and size are judged from a photograph.
function stMichaels({ axis, outline, spire }, piece) {
  const { rect } = framed(axis);
  const m = new Mesh();
  if (piece === "church") {
    m.color("#d8c59c").prism(outline, 0, 14);
    osmPart(m, roofOver(rect(-12.9, 13.6, -35.4, 21.5), 14, 27.8), "#d8c59c", "#56676a");
  } else if (piece === "spire") {
    osmPart(m, spire, "#d8c59c", "#4b5559");
  } else {
    // nine on each slope, their sills where the roof is 3.8 m above the eaves
    for (let v = -31; v <= 17; v += 6) {
      for (const s of [-1, 1]) {
        const u0 = 0.35 + s * 6.4, u1 = 0.35 + s * 9.6;
        osmPart(m, { ring: rect(Math.min(u0, u1), Math.max(u0, u1), v - 1.1, v + 1.1), foot: 17.6, top: 21.6, roof: 1.5, shape: "gabled" },
          "#e2d8c2", "#56676a");
      }
    }
  }
  return m.build();
}

// Metropolitan United Church. Source: built 1870 to 1872 to Henry Langley's design, of white brick
// with cut stone; burned in 1928 but for the tower, parts of the south front and the porches;
// rebuilt on the old foundations to J. Gibb Morton's design and opened December 1929. The outline
// is OpenStreetMap's; every height, the corner pinnacles and the colours are judged from a
// photograph, and the fire is shown at the start of 1928.
function metropolitan({ axis, tower, body }, piece) {
  const { rect } = framed(axis);
  const m = new Mesh();
  if (piece === "tower") {
    m.color("#d6caa8").prism(tower, 0, 46);
    for (const [u, v] of [[18.2, -3.5], [18.2, 3.7], [28.4, -3.5], [28.4, 3.7]]) {
      osmPart(m, { ring: rect(u - 0.9, u + 0.9, v - 0.9, v + 0.9), foot: 46, top: 58, roof: 6, shape: "pyramidal" }, "#d6caa8", "#6e9c86");
    }
  } else {
    m.color("#d6caa8").prism(body, 0, 15);
    osmPart(m, roofOver(rect(-46.5, 17.3, -11, 11.2), 15, 26), "#d6caa8", "#646a6e");
    osmPart(m, roofOver(rect(-20.9, -13, -16.9, 16.7), 15, 26), "#d6caa8", "#646a6e");
  }
  return m.build();
}

// The Church of the Holy Trinity. Source: built in 1847 to Henry Bowyer Lane's design, dedicated
// 27 October 1847; late Gothic (Tudor) style, about five storeys tall, with two towers flanking
// the west entrance. The outline is OpenStreetMap's; the heights, the towers' size and shape
// (octagonal, with crenellated tops) and the colours are judged from a photograph.
function holyTrinity({ axis, outline }) {
  const { at, rect } = framed(axis);
  const m = new Mesh().color("#bfb298").prism(outline, 0, 10);
  osmPart(m, roofOver(rect(-0.4, 23.9, -10.2, 5.9), 10, 17), "#bfb298", "#6b6e70");
  osmPart(m, roofOver(rect(-18, -0.4, -16.3, 17.5), 10, 17), "#bfb298", "#6b6e70");
  for (const v of [-6.6, 2.2]) {
    const [x, y] = at(25.1, v);
    const t = new Mesh().color("#bfb298").lathe([[2.1, 0], [2.1, 18], [1.8, 18.6], [1.8, 23], [2.2, 23], [2.2, 24.5]], 8, Math.PI / 8);
    m.positions.push(...t.positions.map((c, i) => c + (i % 3 === 0 ? x : i % 3 === 1 ? y : 0)));
    m.normals.push(...t.normals);
    m.colors.push(...t.colors);
  }
  return m.build();
}

// One entry per piece that has its own dates: built from `from` (work starts) to `to` (finished).
export function landmarkParts(data) {
  const bmo = bmoField(data.bmoField);
  const sharp = ocad(data.ocad);
  return [
    { id: "casa-loma", key: "casaLoma", mesh: casaLoma(data.casaLoma), from: 1911.4, to: 1914.6 },
    { id: "rom-1914", key: "rom", mesh: rom(data.rom, "1914"), from: 1910.5, to: 1914.21 },
    { id: "rom-1933", key: "rom", mesh: rom(data.rom, "1933"), from: 1931.5, to: 1933.78 },
    { id: "rom-terraces", key: "rom", mesh: rom(data.rom, "terraces"), from: 1978.3, to: 1984.3, until: 2005 },
    { id: "rom-1984", key: "rom", mesh: rom(data.rom, "1984"), from: 1978.3, to: 1984.3 },
    { id: "rom-crystal", key: "rom", mesh: rom(data.rom, "2007"), from: 2005, to: 2007.42 },
    { id: "ago-1918", key: "ago", mesh: ago(data.ago, "1918"), from: 1916.4, to: 1918.5 },
    { id: "ago-1926", key: "ago", mesh: ago(data.ago, "1926"), from: 1922.5, to: 1926.5 },
    { id: "ago-1974", key: "ago", mesh: ago(data.ago, "1974"), from: 1972.5, to: 1974.82 },
    { id: "ago-1977", key: "ago", mesh: ago(data.ago, "1977"), from: 1975.5, to: 1977.5 },
    { id: "ago-1993", key: "ago", mesh: ago(data.ago, "1993"), from: 1990.5, to: 1993 },
    { id: "ago-2008", key: "ago", mesh: ago(data.ago, "2008"), from: 2004.5, to: 2008.87 },
    { id: "old-city-hall", key: "oldCityHall", mesh: osmBuilding(data.oldCityHall, undefined, "#a8724f", "#5e4a3c"), from: 1889.3, to: 1899.71 },
    { id: "legislature", key: "legislature", mesh: osmBuilding(data.legislature, "1893", "#b8735f", "#6d6662", "#6e9c86"), from: 1886.3, to: 1893.26 },
    { id: "legislature-1909", key: "legislature", mesh: osmBuilding(data.legislature, "1909", "#b8735f", "#6d6662"), from: 1908.3, to: 1909.9 },
    { id: "university-college", key: "universityCollege", mesh: osmBuilding(data.universityCollege, "1859", "#b5ab97", "#5f6468"), from: 1856.4, to: 1859.75 },
    { id: "university-college-1964", key: "universityCollege", mesh: osmBuilding(data.universityCollege, "1964", "#c3bba9", "#8d8f90"), from: 1962.5, to: 1964.7 },
    { id: "union-station", key: "unionStation", mesh: osmBuilding(data.unionStation, "1920", "#d8d0bf", "#7d6656"), from: 1914.5, to: 1920.5 },
    { id: "union-shed", key: "unionStation", mesh: osmBuilding(data.unionStation, "shed", "#8e8f90", "#8e8f90"), from: 1929, to: 1930.9 },
    { id: "union-old-shed", key: "unionStation", mesh: osmBuilding(data.unionStation, "old-shed", "#8e8f90", "#8e8f90"), from: 1929, to: 1930.9, until: 2010 },
    { id: "union-atrium", key: "unionStation", mesh: osmBuilding(data.unionStation, "atrium", "#bcd4de", "#bcd4de"), from: 2010.1, to: 2015 },
    { id: "st-michaels", key: "stMichaels", mesh: stMichaels(data.stMichaels, "church"), from: 1845.27, to: 1848.66 },
    { id: "st-michaels-spire", key: "stMichaels", mesh: stMichaels(data.stMichaels, "spire"), from: 1865, to: 1867 },
    { id: "st-michaels-dormers", key: "stMichaels", mesh: stMichaels(data.stMichaels, "dormers"), from: 1889.6, to: 1890.5 },
    { id: "metropolitan-tower", key: "metropolitan", mesh: metropolitan(data.metropolitan, "tower"), from: 1870.65, to: 1872.5 },
    { id: "metropolitan-1872", key: "metropolitan", mesh: metropolitan(data.metropolitan, "body"), from: 1870.65, to: 1872.5, until: 1928.1 },
    { id: "metropolitan-1929", key: "metropolitan", mesh: metropolitan(data.metropolitan, "body"), from: 1928.4, to: 1929.95 },
    { id: "holy-trinity", key: "holyTrinity", mesh: holyTrinity(data.holyTrinity), from: 1846.6, to: 1847.82 },
    { id: "st-james", key: "stJames", mesh: stJames(data.stJames, false), from: 1850.5, to: 1853.46 },
    { id: "st-james-tower", key: "stJames", mesh: stJames(data.stJames, true), from: 1873.2, to: 1874.9 },
    { id: "ocad-reid", key: "ocad", mesh: sharp.reid, from: 1920.2, to: 1921.6 },
    { id: "ocad-casson", key: "ocad", mesh: sharp.casson, from: 1955.8, to: 1957.05 },
    { id: "ocad-legs", key: "ocad", mesh: sharp.legs, from: 2003, to: 2004.3 },
    // the box is lifted on at once, so that it does not grow from the street
    { id: "ocad-table", key: "ocad", mesh: sharp.box, from: 2004.3, to: 2004.32 },
    { id: "cn-tower", key: "cnTower", mesh: cnTower(), from: 1973.1, to: 1976.48 },
    { id: "rogers-centre", key: "rogersCentre", mesh: rogersCentre(data.rogersCentre), from: 1986.76, to: 1989.42 },
    { id: "bmo-field", key: "bmoField", mesh: bmo.base, from: 2006.73, to: 2007.33 },
    { id: "bmo-field-deck", key: "bmoField", mesh: bmo.deck, from: 2014.7, to: 2015.33 },
    { id: "bmo-field-roof", key: "bmoField", mesh: bmo.roof, from: 2015.7, to: 2016.33 },
    // gone: until
    ...(data.trinityCollege ? [{ id: "trinity-college", key: "trinityCollege", mesh: trinityCollege(data.trinityCollege),
      from: 1851, to: 1852, until: 1956 }] : []),
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
  trinityCollege: { name: "Trinity College (original building)", url: "https://en.wikipedia.org/wiki/Trinity_College,_Toronto", replaces: [], rows: [
    ["Built", "1851; opened January 1852. The college moved to Hoskin Avenue in 1925"],
    ["Gone", "Demolished in the 1950s; shown until 1956"],
    ["Model", "Footprint from Goad's fire insurance plan of 1913; heights, tower and turrets judged from a postcard view"],
  ] },
  casaLoma: { name: "Casa Loma", url: "https://en.wikipedia.org/wiki/Casa_Loma", replaces: [], rows: [
    ["Built", "1911 to 1914 for Sir Henry Pellatt, to E. J. Lennox's design; work stopped with the war"],
    ["Model", "Shapes and roofs from OpenStreetMap, whose heights are estimates; colours judged from a photograph"],
  ] },
  stJames: { name: "Cathedral Church of St. James", url: "https://en.wikipedia.org/wiki/Cathedral_Church_of_St._James_(Toronto)", replaces: [], rows: [
    ["Built", "1850 to 1853; tower and spire 1873 to 1874, by Henry Langley"],
    ["Height", "92.9 m to the top of the spire"],
    ["Model", "Shapes and heights from OpenStreetMap; colours judged from a photograph"],
  ] },
  ocad: { name: "OCAD University and the Sharp Centre for Design", url: "https://en.wikipedia.org/wiki/OCAD_University", replaces: [], rows: [
    ["Built", "Reid wing 1921; Casson wing 1957; Sharp Centre 2004, by Will Alsop"],
    ["Sharp Centre", "84 by 31 m and 9 m deep, 26 m above the ground"],
    ["Model", "Outlines from OpenStreetMap; the later additions to the main building are not shown apart; pillars judged from photographs"],
  ] },
  rom: { name: "Royal Ontario Museum", url: "https://en.wikipedia.org/wiki/Royal_Ontario_Museum", replaces: [], rows: [
    ["Built", "1914 wing on Philosopher's Walk; 1933 wing on Queen's Park; terrace galleries and curatorial centre 1978 to 1984; Michael Lee-Chin Crystal 2007"],
    ["Model", "Shapes and heights from OpenStreetMap; the eras of each part, and the terraces (torn down for the Crystal), read off the city's air photos; colours judged"],
  ] },
  ago: { name: "Art Gallery of Ontario", url: "https://en.wikipedia.org/wiki/Art_Gallery_of_Ontario", replaces: [], rows: [
    ["Built", "First galleries 1918; Walker Court 1924 to 1926; Henry Moore Sculpture Centre 1974; Beverley Street 1977; expansion 1993; Frank Gehry's Transformation AGO 2008"],
    ["Model", "Shapes and heights from OpenStreetMap; the eras of each part read off the city's air photos, so 1935 is shown with 1926; The Grange (1817) is the city's own"],
  ] },
  oldCityHall: { name: "Old City Hall", url: "https://en.wikipedia.org/wiki/Old_City_Hall_(Toronto)", replaces: [], rows: [
    ["Built", "1889 to 1899 to E. J. Lennox's design; opened 18 September 1899"],
    ["Height", "103.6 m to the top of the clock tower"],
    ["Model", "Shapes and heights from OpenStreetMap; colours judged from a photograph"],
  ] },
  legislature: { name: "Ontario Legislative Building", url: "https://en.wikipedia.org/wiki/Ontario_Legislative_Building", replaces: [], rows: [
    ["Built", "1886 to 1893 to Richard Waite's design; north wing 1909; west wing rebuilt after the 1909 fire"],
    ["Model", "Shapes and heights from OpenStreetMap; the north wing read off the city's air photo; the rebuilt west wing shown as it is now"],
  ] },
  universityCollege: { name: "University College", url: "https://en.wikipedia.org/wiki/University_College,_Toronto", replaces: [], rows: [
    ["Built", "1856 to 1859 to Cumberland and Storm's design; Laidlaw wing in the 1960s"],
    ["Model", "Shapes and heights from OpenStreetMap; the Laidlaw wing read off the city's air photo and shown from 1964"],
  ] },
  unionStation: { name: "Union Station", url: "https://en.wikipedia.org/wiki/Union_Station_(Toronto)", replaces: [], rows: [
    ["Built", "1914 to 1920; opened 6 August 1927; train shed 1929 to 1930; glass atrium in the 2010s"],
    ["Size", "229 m long; Great Hall 76 m long and 27 m high"],
    ["Model", "Great Hall, colonnade, sheds and atrium from OpenStreetMap; the office wings' height judged"],
  ] },
  stMichaels: { name: "St. Michael's Cathedral Basilica", url: "https://en.wikipedia.org/wiki/St._Michael%27s_Cathedral_Basilica", replaces: [], rows: [
    ["Built", "1845 to 1848 to William Thomas's design; tower and spire 1865 to 1867; dormers 1890"],
    ["Height", "79 m to the top of the spire"],
    ["Model", "Drawn by hand on OpenStreetMap's outline, tower and spire; eaves and dormers judged from a photograph"],
  ] },
  metropolitan: { name: "Metropolitan United Church", url: "https://en.wikipedia.org/wiki/Metropolitan_United_Church", replaces: [], rows: [
    ["Built", "1870 to 1872 to Henry Langley's design; burned in 1928 but for the tower; rebuilt by December 1929"],
    ["Model", "Drawn by hand on OpenStreetMap's outline; heights and pinnacles judged from a photograph"],
  ] },
  holyTrinity: { name: "Church of the Holy Trinity", url: "https://en.wikipedia.org/wiki/Church_of_the_Holy_Trinity_(Toronto)", replaces: [], rows: [
    ["Built", "1847 to Henry Bowyer Lane's design; dedicated 27 October 1847"],
    ["Model", "Drawn by hand on OpenStreetMap's outline; heights and the two towers judged from a photograph"],
  ] },
  bmoField: { name: "BMO Field", url: "https://en.wikipedia.org/wiki/BMO_Field", replaces: [], rows: [
    ["Built", "Opened 2007; east upper deck 2015; roof 2016"],
    ["Pitch", "105 by 68 m"],
    ["Model", "Outlines from OpenStreetMap; all heights judged from photographs"],
  ] },
};
