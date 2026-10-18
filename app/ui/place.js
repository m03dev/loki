// Keep every menu, popover and dropdown on screen (owner, 2026-10-17: "sometimes the menus open but there's not
// enough screen space so I can't click on them ... be smart"). One helper for all of them:
//
//   LokiPlace.place(anchor, pop, {prefer: "below"|"above", align: "start"|"end", gap, minWidth, matchWidth, maxVh})
//       fixed position next to `anchor`; flips above/below to the side with more room, shifts left/right to stay
//       inside the window, caps the height to the room there is (and maxVh % of the window) and scrolls inside.
//   LokiPlace.at(x, y, pop)        a context menu at the mouse, flipped/clamped the same way
//   LokiPlace.release(pop)         stop following it (it is closed)
// An open popover follows window resizes and scrolling. Plain DOM; CSP script-src 'self'.
"use strict";

// The title strip (modebar.js): the app says `titlebar=mac` (or `titlebar=win`: frameless, the strip is the title bar) in the URL
// fragment when the page is drawn under the
// macOS title bar (app/loki_app.py). Read it here - before app.js clears the fragment - and keep it for reloads.
(function () {
  const m = /(?:^|[#&])titlebar=(mac|win)\b/.exec(location.hash);
  let kind = m ? m[1] : "";
  try { if (kind) sessionStorage.setItem("loki-titlebar", kind); else kind = sessionStorage.getItem("loki-titlebar") || ""; } catch (_) { /* no storage */ }
  document.documentElement.classList.add("has-titlestrip");
  if (kind === "mac") document.documentElement.classList.add("titlebar-mac");
  if (kind === "win") document.documentElement.classList.add("titlebar-win");
})();

// The home screen shows the live LOKI World behind the word "Loki". Only LOKI's own window asks for it
// (`worldbg=1`, the same way the app says `titlebar=win`): the published web build and the test harnesses never
// start a whole Godot game in the background. Read it before app.js clears the fragment; keep it for reloads.
(function () {
  const m = /(?:^|[#&])worldbg=(1|on|0|off)(?:$|[&#])/.exec(location.hash);
  let on = m ? m[1] : "";
  try { if (on) sessionStorage.setItem("loki-worldbg", on); else on = sessionStorage.getItem("loki-worldbg") || ""; } catch (_) { /* no storage */ }
  if (on === "1" || on === "on") document.documentElement.classList.add("world-home-on");
})();

const LokiPlace = (() => {
  const MARGIN = 8;
  const open = new Map();   // pop -> () => re-place

  function viewport() {
    const top = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--titlebar-h")) || 0;
    return { top: top + MARGIN, left: MARGIN, right: window.innerWidth - MARGIN, bottom: window.innerHeight - MARGIN };
  }

  function prep(pop) {
    if (pop.parentNode !== document.body) document.body.append(pop);   // out of any overflow:hidden / transformed parent
    pop.style.position = "fixed";
    pop.style.right = pop.style.bottom = "auto";
    pop.style.margin = "0";
    pop.style.overflowY = "auto";
    pop.style.boxSizing = "border-box";
    pop.style.maxWidth = (window.innerWidth - 2 * MARGIN) + "px";
    pop.classList.add("placed");
  }

  function place(anchor, pop, opts) {
    const o = Object.assign({ prefer: "below", align: "start", gap: 6, minWidth: 0, matchWidth: false, maxVh: 0.7 }, opts || {});
    const run = () => {
      if (!pop.isConnected || pop.hidden || !anchor.isConnected) return;
      prep(pop);
      const v = viewport();
      const r = anchor.getBoundingClientRect();
      if (o.matchWidth) pop.style.width = Math.min(v.right - v.left, Math.max(r.width, o.minWidth)) + "px";
      else if (o.minWidth) pop.style.minWidth = Math.min(v.right - v.left, o.minWidth) + "px";
      pop.style.maxHeight = "none";
      const natural = pop.scrollHeight;
      const below = v.bottom - r.bottom - o.gap, above = r.top - o.gap - v.top;
      const cap = Math.max(120, Math.floor(window.innerHeight * o.maxVh));
      let down = o.prefer !== "above";
      if (down && natural > below && above > below) down = false;
      if (!down && natural > above && below > above) down = true;
      const room = Math.max(80, Math.min(cap, down ? below : above));
      pop.style.maxHeight = room + "px";
      const h = Math.min(natural, room);
      const top = down ? r.bottom + o.gap : r.top - o.gap - h;
      pop.style.top = Math.max(v.top, Math.min(top, v.bottom - h)) + "px";
      const w = Math.min(pop.offsetWidth, v.right - v.left);
      let left = o.align === "end" ? r.right - w : r.left;
      left = Math.max(v.left, Math.min(left, v.right - w));
      pop.style.left = left + "px";
      pop.dataset.side = down ? "below" : "above";
    };
    open.set(pop, run);
    run();
    return run;
  }

  function at(x, y, pop) {
    const run = () => {
      if (!pop.isConnected || pop.hidden) return;
      prep(pop);
      const v = viewport();
      pop.style.maxHeight = Math.max(120, v.bottom - v.top) + "px";
      const w = Math.min(pop.offsetWidth, v.right - v.left), h = Math.min(pop.offsetHeight, v.bottom - v.top);
      pop.style.left = Math.max(v.left, x + w > v.right ? x - w : x) + "px";
      pop.style.top = Math.max(v.top, y + h > v.bottom ? y - h : y) + "px";
    };
    open.set(pop, run);
    run();
    return run;
  }

  function release(pop) { open.delete(pop); }

  function again() {
    for (const [pop, run] of open) { if (!pop.isConnected) open.delete(pop); else run(); }
  }
  window.addEventListener("resize", again);
  window.addEventListener("scroll", again, true);

  return { place, at, release, again };
})();
window.LokiPlace = LokiPlace;
