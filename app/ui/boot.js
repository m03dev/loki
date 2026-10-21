// Loaded first (not deferred): if LOKI's window fails to start - a script error, a stylesheet
// that did not load, an engine that never answers - show what went wrong instead of a blank
// white window, and send the errors to the engine's log (engine.out) so they can be read later.
"use strict";
(function () {
  const errors = [];
  const token = (/(?:^|[#&])token=([^&]+)/.exec(location.hash) || [])[1] || "";
  function report(text) {
    errors.push(String(text).slice(0, 600));
    if (errors.length > 20) errors.shift();
    if (!token) return;
    try {
      fetch("/ui/error", { method: "POST", headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
        body: JSON.stringify({ error: String(text).slice(0, 2000), ua: navigator.userAgent.slice(0, 200), url: location.pathname }) })
        .catch(() => {});
    } catch (_) { /* nothing else to do */ }
  }
  // what failed, said plainly: the PC's log kept getting "error at ?:0:0" with nothing to go on
  function describe(node) {
    if (!node || !node.tagName) return "";
    const attr = (n) => { const v = node.getAttribute && node.getAttribute(n); return v ? " " + n + '="' + String(v).slice(0, 160) + '"' : ""; };
    return "<" + node.tagName.toLowerCase() + attr("id") + attr("class") + attr("src") + attr("href") + attr("data") + ">";
  }
  window.addEventListener("error", (e) => {
    const t = e.target;
    if (t && t !== window && t.tagName) {
      const url = typeof t.src === "string" && t.src ? t.src : (t.href && t.href.baseVal !== undefined ? t.href.baseVal : t.href) || t.currentSrc || "";
      report("could not load " + (url || "(no address)") + " - " + describe(t));
      return;
    }
    const where = (e.filename || "?").replace(location.origin, "") + ":" + (e.lineno || 0) + ":" + (e.colno || 0);
    const stack = e.error && e.error.stack ? " | " + String(e.error.stack).split("\n").slice(0, 4).join(" <- ") : "";
    report((e.message || "error (no message: usually a script from another origin or a media element)") + " at " + where + stack);
  }, true);
  window.addEventListener("unhandledrejection", (e) => report("unhandled: " + ((e.reason && (e.reason.stack || e.reason.message)) || e.reason)));
  window.LOKI_BOOT = { errors, report };

  function rescue(reason) {
    if (window.LOKI_READY || document.getElementById("boot-rescue")) return;
    const box = document.createElement("div");
    box.id = "boot-rescue";
    const s = box.style;   // CSSOM styles: allowed by the CSP, and work even when app.css did not load
    s.position = "fixed"; s.inset = "0"; s.zIndex = "99999"; s.background = "#1f1f24"; s.color = "#e6e9ee";
    s.font = "14px -apple-system, system-ui, sans-serif"; s.padding = "40px"; s.overflow = "auto";
    const h = document.createElement("h2"); h.textContent = "LOKI's window did not start properly"; h.style.fontWeight = "600";
    const p = document.createElement("p"); p.textContent = reason; p.style.color = "#9aa0aa";
    const pre = document.createElement("pre"); pre.style.whiteSpace = "pre-wrap"; pre.style.color = "#ffb4a8";
    pre.textContent = errors.length ? errors.join("\n") : "(no script errors were reported)";
    const again = document.createElement("button"); again.textContent = "Reload"; again.type = "button";
    again.style.padding = "8px 16px"; again.style.marginRight = "8px";
    again.addEventListener("click", () => location.reload());
    const safe = document.createElement("button"); safe.textContent = "Reload in safe mode"; safe.type = "button";
    safe.style.padding = "8px 16px";
    safe.addEventListener("click", () => { try { localStorage.setItem("loki.safeMode", "1"); } catch (_) { /* ignore */ } location.reload(); });
    box.append(h, p, pre, again, safe);
    (document.body || document.documentElement).append(box);
    report("rescue screen shown: " + reason + " | " + errors.slice(-5).join(" | "));
  }
  // The page is ready when app.js says so (state.connected). If not in 25 s, or if app.js never
  // ran at all, show the rescue screen.
  setTimeout(() => {
    if (window.LOKI_READY) return;
    const css = document.styleSheets && document.styleSheets.length;
    if (typeof window.start !== "function") rescue("app.js did not run (a script error or a blocked file).");
    else if (!css) rescue("The stylesheets did not load.");
  }, 20000);
  setTimeout(() => rescue("The window never connected to the LOKI engine (it waited 2.5 minutes)."), 150000);

  // Speed watch (EVOLVE E6): once the window is ready, tell the engine how long the first paint and
  // the connection took (Settings > Lab shows them). One small POST per window start; never retried.
  const timing = setInterval(() => {
    if (!window.LOKI_READY) { if (performance.now() > 150000) clearInterval(timing); return; }
    clearInterval(timing);
    let auth = token;
    try { auth = auth || sessionStorage.getItem("loki-token") || ""; } catch (_) { /* private mode */ }
    if (!auth) return;
    let paint = 0;
    try {
      const p = performance.getEntriesByType("paint").find((e) => e.name === "first-contentful-paint")
        || performance.getEntriesByType("paint")[0];
      paint = p ? p.startTime : 0;
    } catch (_) { /* older WebKit: no paint timing */ }
    try {
      fetch("/ui/timing", { method: "POST", headers: { Authorization: "Bearer " + auth, "Content-Type": "application/json" },
        body: JSON.stringify({ first_paint_ms: Math.round(paint), ready_ms: Math.round(performance.now()), ua: navigator.userAgent.slice(0, 40) }) })
        .catch(() => {});
    } catch (_) { /* nothing else to do */ }
  }, 500);
})();
