// The weather in Toronto now: Environment and Climate Change Canada's current conditions (observed
// at Pearson airport), with Open-Meteo for the snow lying on the ground and for the sky when
// Environment Canada gives no description. One reading for the whole city.
const CANADA = "https://api.weather.gc.ca/collections/citypageweather-realtime/items?f=json&limit=1&identifier=on-143";
const OPEN_METEO = "https://api.open-meteo.com/v1/forecast?latitude=43.653&longitude=-79.383" +
  "&current=temperature_2m,snow_depth,weather_code,cloud_cover,wind_speed_10m&timezone=America%2FToronto";
const EVERY_MS = 15 * 60000;

// cloud: 0 clear to 1 overcast; rain and snow: 0 none to 1 heavy; lying: snow on the ground;
// wind in km/h; text for the readout
export const weather = { known: false, cloud: 0, rain: 0, snow: 0, lying: false, wind: 0, text: "" };
let timer = 0;

// a description such as "Light Rain Shower" or "Mostly Cloudy"
function read(words) {
  const w = words.toLowerCase();
  const much = /heavy/.test(w) ? 1 : /light|drizzle|flurr/.test(w) ? 0.35 : 0.65;
  const snow = /snow|flurr|ice pellets|blizzard/.test(w) ? much : 0;
  const rain = /rain|drizzle|shower|thunder/.test(w) && !/snow shower/.test(w) ? much : 0;
  const cloud = snow || rain || /overcast|fog|mist|haze|smoke|^cloudy/.test(w) ? 1
    : /mostly cloudy/.test(w) ? 0.75 : /partly cloudy|mix/.test(w) ? 0.45 : /mainly (sunny|clear)/.test(w) ? 0.2 : 0;
  return { cloud, rain, snow };
}

// the same from Open-Meteo's weather code (WMO) and cloud cover in percent
function readCode(code, cover) {
  const rain = (code >= 51 && code <= 67) || (code >= 80 && code <= 82) || code >= 95 ? ([55, 65, 67, 82].includes(code) ? 1 : [51, 61, 80].includes(code) ? 0.35 : 0.65) : 0;
  const snow = (code >= 71 && code <= 77) || code === 85 || code === 86 ? ([75, 86].includes(code) ? 1 : [71, 77].includes(code) ? 0.35 : 0.65) : 0;
  return { cloud: rain || snow ? 1 : cover / 100, rain, snow };
}

async function refresh(onChange) {
  const [canada, meteo] = await Promise.all([
    fetch(CANADA).then((r) => r.json()).then((d) => d.features[0].properties.currentConditions).catch(() => null),
    fetch(OPEN_METEO).then((r) => r.json()).then((d) => d.current).catch(() => null),
  ]);
  if (!canada && !meteo) return;
  const words = canada?.condition?.en ?? "";
  const sky = words ? read(words) : meteo ? readCode(meteo.weather_code, meteo.cloud_cover) : { cloud: 0, rain: 0, snow: 0 };
  const degrees = canada?.temperature?.value?.en ?? meteo?.temperature_2m;
  Object.assign(weather, sky, {
    known: true,
    lying: (meteo?.snow_depth ?? 0) >= 0.01,
    wind: canada?.wind?.speed?.value?.en ?? meteo?.wind_speed_10m ?? 0,
    text: [Number.isFinite(Number(degrees)) ? `${Math.round(Number(degrees))}°C` : "", words.toLowerCase()].filter(Boolean).join(", "),
  });
  onChange();
}

export function watchWeather(on, onChange) {
  if (!on) { clearInterval(timer); timer = 0; return; }
  if (timer) return;
  // ?weather=rain, snow or cloud shows that weather, to see what it looks like
  const forced = new URLSearchParams(location.search).get("weather");
  if (forced) {
    Object.assign(weather, { known: true, cloud: 1, rain: forced === "rain" ? 0.65 : 0, snow: forced === "snow" ? 0.65 : 0,
      lying: forced === "snow", wind: 20, text: `${forced} (a test)` });
    timer = -1;
    return onChange();
  }
  const ask = () => { if (!document.hidden) refresh(onChange).catch(() => {}); };
  ask();
  timer = setInterval(ask, EVERY_MS);
}

// Rain or snow falling, drawn on its own sheet over the map so that the map is not drawn again
// for it. Call with how much of each (0 to 1); 0 and 0 stops it.
let frame = 0, drops = [], falling = { rain: 0, snow: 0, wind: 0 };
export function fall(canvas, rain, snow, wind) {
  falling = { rain, snow, wind };
  canvas.hidden = !(rain || snow);
  if (canvas.hidden) { cancelAnimationFrame(frame); frame = 0; return; }
  if (frame) return;
  const ctx = canvas.getContext("2d");
  let last = performance.now();
  const draw = (now) => {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    const w = canvas.clientWidth, h = canvas.clientHeight, ratio = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) { canvas.width = Math.round(w * ratio); canvas.height = Math.round(h * ratio); }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const snowing = falling.snow > 0;
    const count = Math.round(((w * h) / 6000) * (snowing ? falling.snow : falling.rain) * (snowing ? 1.6 : 1));
    while (drops.length < count) drops.push({ x: Math.random() * w, y: Math.random() * h, z: 0.4 + Math.random() * 0.6, phase: Math.random() * 6.3 });
    drops.length = Math.min(drops.length, count);
    const lean = Math.min(0.5, falling.wind / 80);
    ctx.strokeStyle = "rgba(70,95,125,0.6)";
    ctx.fillStyle = "rgba(255,255,255,0.9)";
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    for (const d of drops) {
      const speed = (snowing ? 70 : 900) * d.z;
      d.y += speed * dt;
      d.x += speed * lean * dt + (snowing ? Math.sin(now / 700 + d.phase) * 12 * dt : 0);
      if (d.y > h) { d.y = -10; d.x = Math.random() * w; }
      if (d.x > w) d.x -= w;
      if (snowing) { ctx.moveTo(d.x + 1.8 * d.z, d.y); ctx.arc(d.x, d.y, 1.8 * d.z, 0, 6.3); }
      else { ctx.moveTo(d.x, d.y); ctx.lineTo(d.x - 20 * d.z * lean, d.y - 20 * d.z); }
    }
    if (snowing) ctx.fill(); else ctx.stroke();
    frame = requestAnimationFrame(draw);
  };
  frame = requestAnimationFrame(draw);
}
