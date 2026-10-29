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

// ---------------------------------------------------------------------------------------------------------------
// The keyboard stays where the owner is typing - in EVERY text box of the window (owner 2026-10-29: "whever i try to
// type ... i get pushed out of the typing box ... this logic should apply every where"). Panels refresh themselves
// (For you every 10 s, Home, Lab, the chat): when a refresh takes a box out of the page and puts it back, rebuilds it,
// or another piece of code focuses something else, the box loses the keyboard. Fixing each panel one by one kept
// missing one, so this guard covers them all: when a text box loses focus WITHOUT the owner doing it (a click, a tap,
// Tab, Escape, Enter or a shortcut in the last moment), focus and the caret go straight back to it - or, when it was
// rebuilt, to the new box in its place.
(function () {
  "use strict";
  const TEXT = 'textarea, input:not([type]), input[type=text], input[type=search], input[type=email], input[type=url], ' +
               'input[type=number], input[type=password], input[type=tel], [contenteditable=""], [contenteditable=true]';
  let gestureAt = 0, gestureOn = null;   // when he last clicked / pressed a leaving key, and on what
  const gesture = (e) => { gestureAt = performance.now(); gestureOn = e && e.type !== "keydown" && e.type !== "blur" ? e.target : null; };
  for (const ev of ["pointerdown", "mousedown", "touchstart"]) document.addEventListener(ev, gesture, true);
  document.addEventListener("keydown", (e) => {
    // typing letters is not "leaving the box"; Tab / Escape / Enter / a shortcut may be
    if (e.key === "Tab" || e.key === "Escape" || e.key === "Enter" || e.metaKey || e.ctrlKey || e.altKey || /^F\d+$/.test(e.key)) gesture(e);
  }, true);
  window.addEventListener("blur", gesture);              // switching to another app is his doing too
  /** He moved away himself just now: a click somewhere ELSE than this box, or a leaving key (clicking INTO the box
      and typing straight away is not leaving it). */
  const left = (box) => performance.now() - gestureAt < 600 && !(gestureOn && gestureOn.nodeType === 1 && (gestureOn === box || (box.contains && box.contains(gestureOn))));

  const isText = (n) => !!(n && n.nodeType === 1 && n.matches && n.matches(TEXT) && !n.disabled && !n.readOnly);
  const caretOf = (n) => { try { return [n.selectionStart, n.selectionEnd]; } catch (_) { return null; } };
  /** The same box after a rebuild: its id, else the same kind of box (class, name, placeholder, label) inside the
      nearest container that has an id / data-id / data-key. */
  function twin(old, anchor) {
    if (old.id) { const n = document.getElementById(old.id); if (isText(n)) return n; }
    const scope = anchor && anchor.id ? document.getElementById(anchor.id)
      : anchor && anchor.dataset && (anchor.dataset.id || anchor.dataset.key)
        ? document.querySelector('[data-id="' + CSS.escape(anchor.dataset.id || "") + '"]') || document.querySelector('[data-key="' + CSS.escape(anchor.dataset.key || "") + '"]')
        : null;
    if (!scope) return null;
    const same = (n) => n.tagName === old.tagName && n.className === old.className && (n.getAttribute("name") || "") === (old.getAttribute("name") || "")
      && (n.getAttribute("placeholder") || "") === (old.getAttribute("placeholder") || "") && (n.getAttribute("aria-label") || "") === (old.getAttribute("aria-label") || "");
    return [...scope.querySelectorAll(TEXT)].find((n) => isText(n) && same(n)) || null;
  }

  // the box he is in, where its caret is, and the container that names it (to find it again after a rebuild)
  let cur = null, curCaret = null, curValue = "", curAnchor = null;
  const remember = (n) => { cur = n; curCaret = caretOf(n); curValue = n.value; curAnchor = n.closest("[id], [data-id], [data-key]"); };
  document.addEventListener("focusin", (e) => { if (isText(e.target)) remember(e.target); else if (cur && left(cur)) cur = null; }, true);
  for (const ev of ["input", "keyup", "select", "click"]) document.addEventListener(ev, (e) => { if (e.target === cur) remember(cur); }, true);

  function restore(box, caret, value, anchor) {
    if (left(box) || !document.hasFocus()) return;   // he left it himself
    const now = document.activeElement;
    if (now && now !== document.body && now !== box && isText(now)) return;    // he is in another box already
    const to = box.isConnected ? box : twin(box, anchor);
    if (!to || to.disabled || (to.offsetParent === null && to.getClientRects().length === 0)) { cur = null; return; }   // gone for real / hidden
    if (to !== box && value && !to.value) to.value = value;                    // a rebuilt box keeps his words
    if (document.activeElement !== to) to.focus({ preventScroll: true });
    if (caret && caret[0] != null) try { to.setSelectionRange(caret[0], caret[1]); } catch (_) { /* no caret here */ }
    if (gestureOn && to !== box && (gestureOn === box || (box.contains && box.contains(gestureOn)))) gestureOn = to;   // his click was on this box's old self
    remember(to);
    window.LOKI_FOCUS_KEPT = (window.LOKI_FOCUS_KEPT || 0) + 1;
  }

  // 1) something else took the keyboard (a timer focusing a button, a card moved by a refresh)
  document.addEventListener("focusout", (e) => {
    const box = e.target;
    if (!isText(box) || left(box) || !document.hasFocus()) return;
    const caret = caretOf(box), value = box.value, anchor = box.closest("[id], [data-id], [data-key]");
    requestAnimationFrame(() => restore(box, caret, value, anchor));   // after the refresh that caused it
  }, true);
  // 2) the box was taken out of the page or rebuilt - the browser sends NO focus event for that, and his next keys went
  //    to the chat box (it catches typing when nothing has focus)
  new MutationObserver(() => {
    if (cur && !cur.isConnected) { const b = cur, c = curCaret, v = curValue, a = curAnchor; restore(b, c, v, a); }
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
