// The site's Worker. Everything is a static file except the archive photographs, which come out
// of the R2 bucket PHOTOS (copied there once from OldTO's storage; see pipeline/photos.py).

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
    if (url.pathname === "/geo") {
      const country = request.cf?.country;
      const ask = !country || request.cf?.isEUCountry === "1" || ["GB", "CH", "NO", "IS", "LI"].includes(country);
      return Response.json({ ask }, { headers: { "cache-control": "private, no-store" } });
    }
    return env.ASSETS.fetch(request);
  },
};
