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
    return env.ASSETS.fetch(request);
  },
};
