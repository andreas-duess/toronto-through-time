// toronto.duess.com, the site's first address, sends every visitor on to torontothroughtime.com.
// The part of a link after the # (the year and the view) is kept by the browser.
export default {
  fetch(request) {
    const url = new URL(request.url);
    return Response.redirect(`https://torontothroughtime.com${url.pathname}${url.search}`, 301);
  },
};
