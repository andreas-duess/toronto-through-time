// The site's Worker. Everything is a static file except the archive photographs, which come out
// of the R2 bucket PHOTOS (copied there once from OldTO's storage; see pipeline/photos.py).
import { EmailMessage } from "cloudflare:email";

const REPORT_FROM = "report@torontothroughtime.com";

// A note from the "Report a bug" form, as an email to the address in wrangler.jsonc (MAIL).
async function report(request, env) {
  const note = await request.json().catch(() => null);
  const text = String(note?.text ?? "").trim().slice(0, 4000);
  if (!text) return new Response("Nothing to send", { status: 400 });
  if (note.website) return new Response(null, { status: 204 });     // a field people cannot see: filled in by robots only
  const email = /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(String(note.email ?? "")) ? String(note.email).slice(0, 200) : "";
  const line = (v) => String(v ?? "").replace(/[\r\n]+/g, " ").slice(0, 120);
  const body = `${text}\n\nFrom: ${email || "no address given"}\nYear: ${line(note.year)}\nMap: ${line(note.view)}\nCountry: ${request.cf?.country ?? "?"}\n`;
  const bytes = new TextEncoder().encode(body);
  let b64 = "";
  for (let i = 0; i < bytes.length; i += 57) b64 += btoa(String.fromCharCode(...bytes.subarray(i, i + 57))) + "\r\n";
  const raw = [`From: Toronto Through Time <${REPORT_FROM}>`, `To: ${env.REPORT_TO}`, ...(email ? [`Reply-To: ${email}`] : []),
    "Subject: Map report", `Message-ID: <${crypto.randomUUID()}@torontothroughtime.com>`, `Date: ${new Date().toUTCString()}`,
    "MIME-Version: 1.0", "Content-Type: text/plain; charset=utf-8", "Content-Transfer-Encoding: base64", "", b64].join("\r\n");
  try {
    await env.MAIL.send(new EmailMessage(REPORT_FROM, env.REPORT_TO, raw));
  } catch (e) {
    console.error("report not sent:", e.message);
    return new Response("Not sent", { status: 502 });
  }
  return new Response(null, { status: 204 });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/photos/")) {
      const object = await env.PHOTOS.get(url.pathname.slice(8));
      if (!object) return new Response("No such photograph", { status: 404 });
      return new Response(object.body, { headers: { "content-type": "image/jpeg", "cache-control": "public, max-age=31536000, immutable", etag: object.httpEtag } });
    }
    // Whether to ask this visitor before loading the Google tag (public/consent.js): yes in the
    // EU, the rest of the EEA, the UK and Switzerland, and where the country is not known.
    if (url.pathname === "/report") return request.method === "POST" ? report(request, env) : new Response("Not here", { status: 405 });
    if (url.pathname === "/geo") {
      const country = request.cf?.country;
      const ask = !country || request.cf?.isEUCountry === "1" || ["GB", "CH", "NO", "IS", "LI"].includes(country);
      return Response.json({ ask }, { headers: { "cache-control": "private, no-store" } });
    }
    // Aircraft over Toronto now (src/planes.js): from adsb.lol, asked at most every ten seconds
    // however many visitors there are, and cut down to what the page draws:
    // { at: when adsb.lol was asked (ms), planes: [[hex, flight, type, lat, lon, height (m), speed (m/s),
    // track (degrees), age of the report then (s)], ...] }. The answer is kept for ten seconds, so `at` says how old it is.
    if (url.pathname === "/planes") {
      const key = new Request("https://torontothroughtime.com/planes");
      let hit = await caches.default.match(key);
      if (!hit) {
        const r = await fetch("https://api.adsb.lol/v2/point/43.66/-79.40/22", { headers: { "user-agent": "torontothroughtime.com" } });
        const list = r.ok ? (await r.json()).ac ?? [] : [];
        // Aircraft on the ground are in too, at height 0. Their heading is where the nose points when
        // they report no track. Airport vehicles (category C) and whatever has no heading are left out.
        const heading = (a) => a.track ?? a.true_heading ?? a.mag_heading;
        const out = list.filter((a) => Number.isFinite(a.lat) && Number.isFinite(a.lon) && Number.isFinite(heading(a))
            && (a.alt_baro === "ground" ? !String(a.category ?? "").startsWith("C") && Boolean(a.t || a.flight) : Number.isFinite(a.alt_baro)))
          .map((a) => [a.hex, (a.flight ?? "").trim(), a.t ?? "", a.lat, a.lon, a.alt_baro === "ground" ? 0 : Math.round(a.alt_baro * 0.3048),
            Math.round((a.gs ?? 0) * 0.5144), Math.round(heading(a)), Math.round(a.seen_pos ?? a.seen ?? 0)]);
        hit = Response.json({ at: Date.now(), planes: out }, { headers: { "cache-control": "public, max-age=10" } });
        if (r.ok) await caches.default.put(key, hit.clone());
      }
      return hit;
    }
    return env.ASSETS.fetch(request);
  },
};
