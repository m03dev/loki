// Forge's panels resize like the pro tools (owner 2026-10-21: "make all the ui panels adjustable when i hover over
// with mouse i can pull wider or not ... everything is %"). Every side panel of the workspace - the Outliner, the
// Create panel, Materials, the Channel Box - gets a splitter on its inner edge: hover it (the cursor turns into a
// resize arrow and the edge lights up), drag to make the panel wider or narrower. The width is stored as a
// percentage of Forge's width, so the layout keeps its proportions on any screen or window size. Inside the
// Channel Box column a second, horizontal splitter sets how much of it the Display Layers take.
// Double-click a splitter to put that panel back to its default size. Saved per viewer (localStorage).
"use strict";

const FORGE_SPLIT_STORE = "loki-forge-split";
// [panel id, side of the viewport it sits on, default %, min %, max %]
const FORGE_SPLIT_PANELS = [
  ["forge-outcol", "left", 17, 8, 45],
  ["forge-left", "left", 24, 12, 50],
  ["forge-materials", "right", 36, 15, 60],
  ["forge-chancol", "right", 19, 10, 45],
];
const FORGE_SPLIT_LAYERS = { def: 28, min: 8, max: 80 };     // Display Layers: % of the Channel Box column

function forgeSplitLoad() {
  try { return JSON.parse(localStorage.getItem(FORGE_SPLIT_STORE) || "{}") || {}; } catch (_) { return {}; }
}
function forgeSplitSave(s) {
  try { localStorage.setItem(FORGE_SPLIT_STORE, JSON.stringify(s)); } catch (_) { /* private window: not kept */ }
}

// the current sizes, in % (what was saved, else the defaults) - for tests and the Hotbox
function forgeSplitSizes() {
  const s = forgeSplitLoad(), out = {};
  for (const [id, , def] of FORGE_SPLIT_PANELS) out[id] = typeof s[id] === "number" ? s[id] : def;
  out.layers = typeof s.layers === "number" ? s.layers : FORGE_SPLIT_LAYERS.def;
  return out;
}

function forgeSplitApply() {
  forgeSplitLayers();
  const sz = forgeSplitSizes();
  for (const [id] of FORGE_SPLIT_PANELS) {
    const p = document.getElementById(id);
    if (p) { p.style.flex = "0 0 " + sz[id] + "%"; p.style.width = sz[id] + "%"; p.style.minWidth = "0"; p.style.maxWidth = "none"; }
  }
  const col = document.getElementById("forge-chancol"), lay = document.getElementById("forge-layer-editor");
  if (col && lay) {
    col.classList.add("forge-split-col");
    lay.style.flex = "0 0 " + sz.layers + "%";
  }
  forgeSplitSync();
}

// a splitter shows only next to a panel that is showing
function forgeSplitSync() {
  for (const s of document.querySelectorAll("#forge .forge-split")) {
    const p = document.getElementById(s.dataset.panel);
    s.hidden = !p || p.hidden || getComputedStyle(p).display === "none";
  }
  const hs = document.getElementById("forge-split-layers"), lay = document.getElementById("forge-layer-editor");
  if (hs) hs.hidden = !lay || lay.hidden || getComputedStyle(lay).display === "none";
}

function forgeSplitDrag(handle, onMove, onEnd) {
  handle.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    try { handle.setPointerCapture(e.pointerId); } catch (_) { /* gone */ }
    handle.classList.add("drag"); document.body.classList.add("forge-splitting");
    const move = (ev) => { onMove(ev); if (window.forge && forge.view) { forge.view.dirty = true; if (forge.view.resize) forge.view.resize(); } };
    const up = () => {
      handle.classList.remove("drag"); document.body.classList.remove("forge-splitting");
      handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", up); handle.removeEventListener("pointercancel", up);
      onEnd();
    };
    handle.addEventListener("pointermove", move); handle.addEventListener("pointerup", up); handle.addEventListener("pointercancel", up);
  });
}

function forgeSplitAttach() {
  const body = document.querySelector("#forge .forge-body");
  if (!body || body.dataset.split) { forgeSplitApply(); return; }
  body.dataset.split = "1";
  for (const [id, side, def, lo, hi] of FORGE_SPLIT_PANELS) {
    const p = document.getElementById(id);
    if (!p || p.parentElement !== body) continue;
    const h = document.createElement("div");
    h.className = "forge-split"; h.dataset.panel = id; h.dataset.side = side;
    h.title = "Drag to resize - double-click for the default size.";
    h.setAttribute("role", "separator"); h.setAttribute("aria-orientation", "vertical");
    if (side === "left") p.after(h); else p.before(h);
    forgeSplitDrag(h, (ev) => {
      const b = body.getBoundingClientRect(), r = p.getBoundingClientRect();
      const px = side === "left" ? ev.clientX - r.left : r.right - ev.clientX;
      const pct = Math.max(lo, Math.min(hi, (px / (b.width || 1)) * 100));
      p.style.flex = "0 0 " + pct.toFixed(2) + "%"; p.style.width = pct.toFixed(2) + "%";
      h.dataset.pct = pct.toFixed(1);
    }, () => {
      const s = forgeSplitLoad(); if (h.dataset.pct) s[id] = Number(h.dataset.pct); forgeSplitSave(s);
    });
    h.addEventListener("dblclick", () => { const s = forgeSplitLoad(); delete s[id]; forgeSplitSave(s); forgeSplitApply(); if (window.forge && forge.view) forge.view.dirty = true; });
  }
  // panels come and go (Windows menu, Ctrl+Space, the toolkit tab): keep the splitters beside the visible ones
  const mo = forgeSplitAttach.mo = new MutationObserver(() => forgeSplitSync());
  for (const [id] of FORGE_SPLIT_PANELS) { const p = document.getElementById(id); if (p) mo.observe(p, { attributes: true, attributeFilter: ["hidden", "style", "class"] }); }
  mo.observe(body, { attributes: true, attributeFilter: ["class"] });
  forgeSplitApply();
}

// the Channel Box / Display Layers split - the Layer Editor is built with the scene, after the workspace, so this
// runs again on every apply until it is there
function forgeSplitLayers() {
  const col = document.getElementById("forge-chancol"), lay = document.getElementById("forge-layer-editor");
  if (col && lay && !document.getElementById("forge-split-layers")) {
    const h = document.createElement("div");
    h.className = "forge-split-h"; h.id = "forge-split-layers";
    h.title = "Drag up or down: how much of the column the Display Layers take (double-click resets).";
    h.setAttribute("role", "separator"); h.setAttribute("aria-orientation", "horizontal");
    lay.before(h);
    forgeSplitDrag(h, (ev) => {
      const c = col.getBoundingClientRect();
      const pct = Math.max(FORGE_SPLIT_LAYERS.min, Math.min(FORGE_SPLIT_LAYERS.max, ((c.bottom - ev.clientY) / (c.height || 1)) * 100));
      lay.style.flex = "0 0 " + pct.toFixed(2) + "%"; h.dataset.pct = pct.toFixed(1);
    }, () => { const s = forgeSplitLoad(); if (h.dataset.pct) s.layers = Number(h.dataset.pct); forgeSplitSave(s); });
    h.addEventListener("dblclick", () => { const s = forgeSplitLoad(); delete s.layers; forgeSplitSave(s); forgeSplitApply(); });
    if (forgeSplitAttach.mo) forgeSplitAttach.mo.observe(lay, { attributes: true, attributeFilter: ["hidden"] });
  }
}

function forgeSplitReset() { forgeSplitSave({}); forgeSplitApply(); if (window.forge && forge.view) forge.view.dirty = true; return "Panels back to their default sizes."; }
