import { LightingEffect, AmbientLight, DirectionalLight, MapView } from "@deck.gl/core";
import { getSunPosition, getSunDirection } from "@math.gl/sun";

// The sun over Toronto for a time of day, and the light and shadows it gives.
const LAT = 43.653, LON = -79.383;
const ZONE = "America/Toronto";
// The sun counts as up above this height (degrees): lower, the shadows run across the whole city.
const LOWEST = 8;
const SHADOW_COLOR = [18 / 255, 22 / 255, 40 / 255, 0.3];

// minutes that Toronto's clocks are ahead of UTC at a moment (negative)
function offsetMinutes(ms) {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: ZONE, hourCycle: "h23",
    year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" })
    .formatToParts(new Date(ms)).map((x) => [x.type, Number(x.value)]));
  return Math.round((Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - ms) / 60000);
}

// Today in Toronto: the start of the day, the minute of the day it is now, and the first and last
// minutes with the sun up.
export function today(now = Date.now()) {
  const offset = offsetMinutes(now);
  const local = now + offset * 60000;
  const midnight = Math.floor(local / 86400000) * 86400000 - offset * 60000;
  const up = [];
  for (let m = 0; m < 1440; m += 5) {
    if (getSunPosition(midnight + m * 60000, LAT, LON).altitude * 180 / Math.PI >= LOWEST) up.push(m);
  }
  return { midnight, now: Math.floor((now - midnight) / 60000), first: up[0], last: up[up.length - 1] };
}

export const clock = (minute) => `${(Math.floor(minute / 60) + 11) % 12 + 1}:${String(minute % 60).padStart(2, "0")} ${minute < 720 ? "am" : "pm"}`;

// Where the sunlight travels at a minute of the day (east, north, up), and the sun's height (0 to 1).
export function sunAt(day, minute) {
  const t = day.midnight + minute * 60000;
  return { direction: getSunDirection(t, LAT, LON), height: Math.sin(getSunPosition(t, LAT, LON).altitude) };
}

// The sun, and the light of the sky from above for the sides the sun does not reach. A low sun
// is warmer and weaker.
// Under cloud (0 to 1) the sun is weaker and the light from all sides stronger.
function lights({ direction, height, cloud = 0 }, shadows) {
  const low = 1 - Math.min(1, height / 0.5);
  return {
    ambient: new AmbientLight({ color: [255, 255, 255], intensity: 1 + 0.22 * cloud }),
    sun: new DirectionalLight({ color: [255, 250 - 30 * low, 240 - 70 * low], intensity: ((shadows ? 0.85 : 1) - 0.15 * low) * (1 - 0.75 * cloud), direction, _shadow: shadows }),
    sky: new DirectionalLight({ color: [225, 235, 255], intensity: shadows ? 0.2 : 0.3, direction: [-direction[0] * 0.4, -direction[1] * 0.4, -1] }),
  };
}

// deck.gl's shadows, with a sharper test. Its own test only starts to count something as shadowed
// when it lies 0.1% of the whole depth of the view behind what the sun sees, so a house casts
// none. Here the depth the sun sees is compared along the slope of the surface being drawn, over
// the nine texels around it for a soft edge. A wall turned away from the sun is in shadow whatever
// the shadow map says (shadow_facing, set by time.js).
const SHADOW_TEST = /* glsl */ `
float shadow_facing = 1.0;

float shadow_getShadowWeight(vec3 position, sampler2D shadowMap) {
  if (any(lessThan(position.xy, vec2(0.0))) || any(greaterThan(position.xy, vec2(1.0)))) return 0.0;
  vec2 size = vec2(textureSize(shadowMap, 0));
  // how the depth changes across the surface, per texel of the shadow map
  vec3 dx = dFdx(position), dy = dFdy(position);
  float det = dx.x * dy.y - dx.y * dy.x;
  vec2 slope = abs(det) > 1e-14 ? vec2(dy.y * dx.z - dx.y * dy.z, dx.x * dy.z - dy.x * dx.z) / det / size : vec2(0.0);
  slope = clamp(slope, -0.004, 0.004);
  float margin = 0.00015 + 2.0 * (abs(slope.x) + abs(slope.y));
  vec2 at = position.xy * size - 0.5;
  vec2 corner = floor(at), part = at - corner;
  float sum = 0.0;
  for (int i = 0; i < 3; i++) {
    for (int j = 0; j < 3; j++) {
      vec2 texel = corner + vec2(float(i), float(j));
      float z = dot(texelFetch(shadowMap, ivec2(clamp(texel, vec2(0.0), size - 1.0)), 0), bitUnpackShift);
      float here = position.z + dot(slope, texel - at);
      float weight = (i == 0 ? 1.0 - part.x : i == 2 ? part.x : 1.0) * (j == 0 ? 1.0 - part.y : j == 2 ? part.y : 1.0);
      sum += weight * step(z + margin, here);
    }
  }
  return sum / 4.0;
}
`;

// The vertex step, for the one light that casts shadows. The depth the sun sees is written from
// the vertex position, not from gl_FragCoord: inside the map's own drawing the depth range is not
// 0 to 1, which shifted every depth and put all flat ground in shadow.
const VERTEX_STEP = /* glsl */ `
vec4 shadow_setVertexPosition(vec4 position_commonspace) {
  if (shadow.drawShadowMap || shadow.useShadowMap) {
    vec4 seen = project_common_position_to_clipspace(position_commonspace, shadow.viewProjectionMatrix0, shadow.projectCenter0);
    shadow_vPosition[0] = (seen.xyz / seen.w + 1.0) / 2.0;
    if (shadow.drawShadowMap) return seen;
  }
  return gl_Position;
}
`;

function sharpen(module) {
  if (module.name !== "shadow" || module.sharpened) return;
  const step = module.vs.indexOf("vec4 shadow_setVertexPosition");
  if (step < 0 || !module.fs.includes("gl_FragCoord.z * bitPackShift")) return;
  module.vs = module.vs.slice(0, step) + VERTEX_STEP;
  module.fs = module.fs.replace("gl_FragCoord.z * bitPackShift", "shadow_vPosition[0].z * bitPackShift");
  const from = module.fs.indexOf("float shadow_getShadowWeight"), to = module.fs.indexOf("vec4 shadow_filterShadowColor");
  if (from < 0 || to < 0) return;
  module.fs = module.fs.slice(0, from) + SHADOW_TEST + module.fs.slice(to)
    .replace("shadowAlpha *= shadow.color.a / shadow.lightCount;",
      "shadowAlpha = max(shadowAlpha, 1.0 - smoothstep(0.0, 0.15, shadow_facing)) * shadow.color.a;")
    // the unseen ground sheet: nothing to mix where no shadow falls
    .replace("shadowAlpha / blendedAlpha", "shadowAlpha / max(blendedAlpha, 0.0001)");
  module.sharpened = true;
}

export class SunEffect extends LightingEffect {
  constructor(sun, shadows) {
    super(lights(sun, shadows));
    this.shadows = shadows;
    this.shadowColor = SHADOW_COLOR;
  }

  setSun(sun) {
    this.setProps(lights(sun, this.shadows));
  }

  // deck.gl draws what the sun sees in the middle of the map's frame, between the ground and the
  // buildings. Leaving the map's picture and coming back to it cost more than the shadows
  // themselves, so this is called before the map starts on its frame, with the same view the
  // buildings are then drawn in (as @deck.gl/mapbox makes it). Returns whether it drew.
  drawEarly(deck, map, args) {
    if (!this.shadow || !this.dummyShadowMap || !deck?.isInitialized || !Number.isFinite(args.nearZ)) return false;
    const { lng, lat } = map.getCenter();
    const view = deck.getView("mapbox") || new MapView({ id: "mapbox" });
    view.props.nearZMultiplier = 0.2;
    const viewport = view.makeViewport({ width: deck.width, height: deck.height, viewState: {
      longitude: ((lng + 540) % 360) - 180, latitude: lat, zoom: map.getZoom(), bearing: map.getBearing(),
      pitch: map.getPitch(), padding: map.getPadding(), repeat: map.getRenderWorldCopies(),
      nearZ: args.nearZ / map.transform.height, farZ: args.farZ / map.transform.height } });
    super.preRender({ layers: deck.layerManager.getLayers(), viewports: [viewport],
      onViewportActive: deck.layerManager.activateViewport, views: deck.viewManager.getViews() });
    this.drawn = true;
    return true;
  }

  preRender(opts) {
    if (this.drawn) this.drawn = false; else super.preRender(opts);
  }

  setup(context) {
    const { deck } = context;
    const add = deck._addDefaultShaderModule;
    deck._addDefaultShaderModule = (module) => { sharpen(module); return add.call(deck, module); };
    try { super.setup(context); } finally { deck._addDefaultShaderModule = add; }
  }
}
