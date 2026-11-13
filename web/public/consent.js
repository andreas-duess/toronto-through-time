// Loads the Google tag, and asks visitors from Europe first.
// The Worker says whether the visitor is in the EU, the rest of the EEA, the UK or Switzerland
// (/geo). There the tag is loaded only after "Accept", and never after "No thanks". Elsewhere it
// is loaded at once. If the place cannot be found out, the visitor is asked. The choice is kept in
// this browser (localStorage "consent") and can be changed on the privacy page.
(function () {
  var TAG = "GTM-WGKX787M";
  function choice() { try { return localStorage.getItem("consent"); } catch (e) { return null; } }
  function keep(value) { try { localStorage.setItem("consent", value); } catch (e) { /* private window */ } }

  function loadTag() {
    if (window.__tagLoaded) return;
    window.__tagLoaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag("js", new Date());
    var s = document.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtm.js?id=" + TAG;
    document.head.appendChild(s);
  }

  function ask() {
    if (document.getElementById("consent")) return;
    var box = document.createElement("div");
    box.id = "consent";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "Cookies");
    box.style.cssText = "position:fixed;left:16px;right:16px;bottom:16px;z-index:1000;max-width:560px;margin:0 auto;padding:14px 16px;" +
      "background:#fff;color:#1d2733;border:1px solid rgba(29,39,51,.18);border-radius:10px;box-shadow:0 8px 30px rgba(29,39,51,.22);" +
      "font:14px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif";
    box.innerHTML = '<p style="margin:0 0 10px">This site would like to use Google Analytics cookies to count visits. ' +
      'The map works the same either way. <a href="/privacy" style="color:#b8431f">Privacy</a></p>' +
      '<button id="consent-yes" style="margin-right:8px;padding:7px 14px;border:0;border-radius:6px;background:#d9542b;color:#fff;font:inherit;cursor:pointer">Accept</button>' +
      '<button id="consent-no" style="padding:7px 14px;border:1px solid rgba(29,39,51,.25);border-radius:6px;background:#fff;color:#1d2733;font:inherit;cursor:pointer">No thanks</button>';
    document.body.appendChild(box);
    document.getElementById("consent-yes").onclick = function () { keep("granted"); box.remove(); loadTag(); };
    document.getElementById("consent-no").onclick = function () { keep("denied"); box.remove(); };
  }
  // for the "change my choice" link on the privacy page
  window.askConsent = function () { try { localStorage.removeItem("consent"); } catch (e) { /* private window */ } ask(); };

  function start() {
    var c = choice();
    if (c === "granted") return loadTag();
    if (c === "denied") return;
    fetch("/geo").then(function (r) { return r.json(); })
      .then(function (g) { if (g.ask) ask(); else loadTag(); })
      .catch(ask);
  }
  if (document.body) start(); else document.addEventListener("DOMContentLoaded", start);
})();
