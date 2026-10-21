// Forge's layout system (owner 2026-10-21: "make all the ui panels adjustable and close also some subpanels should
// be able to adjust ... i want all the menus to be adjustable so i can move them where i want ... everything should
// be made in % so it scales across devices and screens, also consider people with vertical monitors").
//
// Every panel of the workspace - the Tool Box, the Outliner, the Create panel, the Channel Box / Layer Editor, the
// UV Editor, Material Maker - can be
//   * moved: drag its title (or the grip on the Tool Box). While dragging, the edges of the workspace light up:
//     let go on the left / right edge to dock it there (the outer part of the edge = outermost, the inner part =
//     next to the viewport), on the top / bottom edge to dock it above / below the viewport, anywhere else to
//     float it. Right-click a title for the same choices as a menu.
//   * floated: the ⧉ button (or "Float" in the menu); a floating panel is dragged by its title and resized by its
//     corner; double-click its title to dock it back where it was.
//   * closed: the × button (Windows menu / Space menu bring it back, as before).
//   * resized: the edge between a panel and the viewport (forge_split.js) and, for top / bottom docks, the bar
//     above / below them. Inside the Channel Box column the Channel Box / INPUTS / Display Layers split moves too,
//     and INPUTS and Display Layers fold to their title.
// The floating bars over the viewport (Time Slider, sculpt bars, Options, Graph Editor ...) get a grip at their
// left end: drag it to move the bar anywhere over the viewport, double-click it to put the bar back.
//
// Every size and position is a % of the workspace, so a layout keeps its proportions on any screen. Layouts are
// kept per workspace (Modeling, UV Editing, Retopology, Baking, Materials) AND per screen shape: a tall (vertical)
// window has its own layout, which starts with the Outliner and the Channel Box docked under the viewport.
// Windows > Layouts: save a layout under a name, load it, reset to the default; the interface size (Auto follows
// the screen) is there too. Saved per viewer (localStorage, wrapped in try/catch).
"use strict";

const FORGE_DOCK_STORE = "loki-forge-dock";
const FORGE_DOCK_NAMED = "loki-forge-dock-named";
const FORGE_DOCK_FLOATS = "loki-forge-dock-bars";
// [id, title, kind, default dock, how to close it]
const FORGE_DOCK_PANELS = [
  ["fmy-toolbox", "Tool Box", "bar", "left", "toolbox"],
  ["forge-outcol", "Outliner", "panel", "left", "outliner"],
  ["forge-left", "Create", "panel", "left", "create"],
  ["forge-materials", "Material Maker", "panel", "right", "materials"],
  ["forge-uvpanel", "UV Editor", "panel", "right", "uv"],
  ["forge-bakepanel", "Baking", "panel", "right", "uv"],
  ["forge-chancol", "Channel Box / Layer Editor", "panel", "right", "channel"],
];
// a tall window starts with these under the viewport
const FORGE_DOCK_PORTRAIT = { "forge-outcol": "bottom", "forge-chancol": "bottom", "forge-left": "bottom" };
const FORGE_DOCK_EDGE = 0.07;        // how close to an edge (fraction of the workspace) a drop docks there

// panels other scripts add to the splitter list later are dockable too
function forgeDockList() {
  if (typeof FORGE_SPLIT_PANELS !== "undefined") {
    for (const [id, side] of FORGE_SPLIT_PANELS) {
      if (!FORGE_DOCK_PANELS.some((p) => p[0] === id)) FORGE_DOCK_PANELS.push([id, (document.getElementById(id) || {}).title || id.replace(/^forge-/, ""), "panel", side, ""]);
    }
  }
  return FORGE_DOCK_PANELS;
}
function forgeDockLoad(key, def) {
  try { const v = JSON.parse(localStorage.getItem(key) || "null"); return v && typeof v === "object" ? v : def; } catch (_) { return def; }
}
function forgeDockSave(key, v) {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch (_) { /* private window: not kept */ }
}
function forgeDockBody() { return document.querySelector("#forge .forge-body"); }
function forgeDockOrient() {
  const b = forgeDockBody(), r = b && b.getBoundingClientRect();
  const w = r && r.width ? r.width : window.innerWidth, h = r && r.height ? r.height : window.innerHeight;
  return h > w * 1.05 ? "portrait" : "landscape";
}
function forgeDockWorkspace() {
  try { return localStorage.getItem("loki-forge-workspace") || "model"; } catch (_) { return "model"; }
}
function forgeDockKey() { return forgeDockWorkspace() + ":" + forgeDockOrient(); }

// the layout in use: { panels: { id: { dock, rank, x, y, w, h, back } }, topH, bottomH, scale }
function forgeDockLayout() {
  const all = forgeDockLoad(FORGE_DOCK_STORE, {});
  const key = forgeDockKey();
  let L = all[key];
  if (!L) {                                   // a new screen shape / workspace starts from its default
    L = { panels: {}, topH: 30, bottomH: 34 };
    if (forgeDockOrient() === "portrait") for (const [id, dock] of Object.entries(FORGE_DOCK_PORTRAIT)) L.panels[id] = { dock, rank: 0 };
  }
  L.panels = L.panels || {};
  return L;
}
function forgeDockStore(L) {
  const all = forgeDockLoad(FORGE_DOCK_STORE, {});
  all[forgeDockKey()] = L;
  forgeDockSave(FORGE_DOCK_STORE, all);
}
function forgeDockOf(L, id) {
  const def = FORGE_DOCK_PANELS.find((p) => p[0] === id);
  return Object.assign({ dock: def ? def[3] : "left", rank: 0 }, L.panels[id] || {});
}

// ------------------------------------------------------------------------------------------ apply the layout
function forgeDockApply() {
  const body = forgeDockBody();
  if (!body) return;
  body.classList.add("fdock");
  const L = forgeDockLayout();
  body.classList.toggle("fdock-portrait", forgeDockOrient() === "portrait");
  const stage = document.getElementById("forge-stage");
  if (stage) stage.style.order = "50";
  const sides = { left: [], right: [], top: [], bottom: [], float: [] };
  for (const [id, , kind] of forgeDockList()) {
    const p = document.getElementById(id);
    if (!p || p.parentElement !== body) continue;
    forgeDockDress(p);
    const st = forgeDockOf(L, id);
    const dock = kind === "bar" && (st.dock === "top" || st.dock === "bottom") ? "left" : st.dock;
    p.dataset.dock = dock;
    sides[dock] ? sides[dock].push([p, st]) : sides.left.push([p, st]);
  }
  const visible = (p) => !p.hidden && getComputedStyle(p).display !== "none";
  // left: rank 0 is the outermost; the Tool Box always first unless moved to the right
  const kids = [...body.children];
  // ties keep the page order: on the left the first is outermost, on the right the last is
  const order = (list, base, step) => list.sort((a, b) => (a[1].rank || 0) - (b[1].rank || 0) || (step > 0 ? 1 : -1) * (kids.indexOf(a[0]) - kids.indexOf(b[0])))
    .forEach(([p], i) => { p.style.order = String(base + step * i); forgeDockHandle(p, base + step * i + (step > 0 ? 1 : -1), step > 0 ? "left" : "right"); });
  order(sides.left, 2, 2);
  order(sides.right, 98, -2);
  sides.top.forEach(([p], i) => { p.style.order = String(-40 + i); forgeDockHandle(p, null); });
  sides.bottom.forEach(([p], i) => { p.style.order = String(110 + i); forgeDockHandle(p, null); });
  for (const [p, st] of sides.float) {
    forgeDockHandle(p, null);
    p.classList.add("fdock-float");
    p.style.order = "";
    p.style.left = (st.x != null ? st.x : 30) + "%"; p.style.top = (st.y != null ? st.y : 12) + "%";
    p.style.width = (st.w != null ? st.w : 24) + "%"; p.style.height = (st.h != null ? st.h : 60) + "%";
    p.style.flex = "none"; p.style.maxWidth = "none";
  }
  for (const [p] of sides.left.concat(sides.right, sides.top, sides.bottom)) {
    if (p.classList.contains("fdock-float")) { p.classList.remove("fdock-float"); p.style.left = p.style.top = p.style.height = ""; p.style.width = ""; p.style.flex = ""; }
  }
  for (const [p] of sides.top.concat(sides.bottom)) { p.style.width = ""; p.style.flex = ""; }
  // the top / bottom docks: a full-width bar that starts the new row and resizes it
  const anyTop = sides.top.some(([p]) => visible(p)), anyBottom = sides.bottom.some(([p]) => visible(p));
  body.classList.toggle("fdock-has-top", anyTop);
  body.classList.toggle("fdock-has-bottom", anyBottom);
  body.style.setProperty("--fdock-top", anyTop ? (L.topH || 30) + "%" : "0%");
  body.style.setProperty("--fdock-bottom", anyBottom ? (L.bottomH || 34) + "%" : "0%");
  body.style.setProperty("--fdock-gap", (6 * ((anyTop ? 1 : 0) + (anyBottom ? 1 : 0))) + "px");
  forgeDockRowBar(body, "top", anyTop, -10);
  forgeDockRowBar(body, "bottom", anyBottom, 105);
  forgeDockScale(L);
  forgeDockSubpanels();
  if (typeof forgeSplitSync === "function") forgeSplitSync();
  const v = typeof forge !== "undefined" && forge.view;
  if (v) { v.dirty = true; if (v.resize) v.resize(); }
}

// a panel's side splitter (forge_split.js) follows the panel: its order and which side it pulls from
function forgeDockHandle(p, ord, side) {
  const h = document.querySelector('#forge .forge-split[data-panel="' + p.id + '"]');
  if (!h) return;
  if (ord == null) { h.dataset.dockOff = "1"; h.hidden = true; return; }
  delete h.dataset.dockOff;
  h.style.order = String(ord);
  h.dataset.side = side;
}

function forgeDockRowBar(body, where, on, ord) {
  let bar = document.getElementById("fdock-row-" + where);
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "fdock-row-" + where; bar.className = "forge-split-h fdock-rowbar";
    bar.title = "Drag to make the panels " + (where === "top" ? "above" : "below") + " the viewport taller or shorter (double-click resets).";
    bar.setAttribute("role", "separator"); bar.setAttribute("aria-orientation", "horizontal");
    body.append(bar);
    forgeDockDrag(bar, null, (ev) => {
      const r = body.getBoundingClientRect();
      const pct = where === "top" ? ((ev.clientY - r.top) / (r.height || 1)) * 100 : ((r.bottom - ev.clientY) / (r.height || 1)) * 100;
      const v = Math.max(10, Math.min(75, pct));
      body.style.setProperty("--fdock-" + where, v.toFixed(2) + "%");
      bar.dataset.pct = v.toFixed(1);
      const fv = typeof forge !== "undefined" && forge.view; if (fv && fv.resize) fv.resize();
    }, () => { const L = forgeDockLayout(); if (bar.dataset.pct) L[where + "H"] = Number(bar.dataset.pct); forgeDockStore(L); });
    bar.addEventListener("dblclick", () => { const L = forgeDockLayout(); L[where + "H"] = where === "top" ? 30 : 34; forgeDockStore(L); forgeDockApply(); });
  }
  bar.hidden = !on;
  bar.style.order = String(ord);
}

// ------------------------------------------------------------------------------------------ a panel's title + buttons
// panels that have their own title: it becomes the drag handle (no second title bar). Built later than the panel,
// so a panel waits to be dressed until its title is there.
const FORGE_DOCK_TITLES = { "forge-outcol": ".forge-out-title", "forge-chancol": "#forge-channel .forge-panel-tab" };
function forgeDockDress(p) {
  if (p.dataset.fdock) return;
  const def = FORGE_DOCK_PANELS.find((x) => x[0] === p.id) || [p.id, p.id, "panel"];
  let grip = FORGE_DOCK_TITLES[p.id] ? p.querySelector(FORGE_DOCK_TITLES[p.id]) : null;
  if (FORGE_DOCK_TITLES[p.id] && !grip) return;
  p.dataset.fdock = "1";
  if (def[2] === "bar") {
    grip = document.createElement("div");
    grip.className = "fdock-grip"; grip.title = def[1] + ": drag to move it (left / right edge, or float it); right-click for more.";
    p.prepend(grip);
  } else if (!grip) {
    grip = document.createElement("div");
    grip.className = "fdock-head";
    grip.append(Object.assign(document.createElement("span"), { className: "fdock-title", textContent: def[1] }));
    p.prepend(grip);
  }
  grip.classList.add("fdock-handle");
  if (!grip.title) grip.title = def[1] + ": drag to move or dock it; double-click a floating panel to dock it back; right-click for more.";
  const btns = document.createElement("span");
  btns.className = "fdock-btns";
  const mk = (cls, label, what, fn) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "fdock-btn " + cls; b.setAttribute("aria-label", label);
    b.title = label + " - " + what;
    b.addEventListener("pointerdown", (e) => e.stopPropagation());
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
    return b;
  };
  btns.append(
    mk("fdock-b-float", "Float / dock", "float this panel over the workspace, or dock it back", () => forgeDockToggleFloat(p.id)),
    mk("fdock-b-close", "Close", "hide this panel (the Windows menu brings it back)", () => forgeDockClose(p.id)));
  if (def[2] === "bar") btns.querySelector(".fdock-b-float").remove();
  p.classList.add("fdock-panel");
  p.append(btns);
  forgeDockDrag(grip, p, null, null);
  grip.addEventListener("contextmenu", (e) => { e.preventDefault(); e.stopPropagation(); forgeDockMenu(p.id, e.clientX, e.clientY); });
  grip.addEventListener("dblclick", (e) => {
    if (p.dataset.dock !== "float") return;
    e.stopPropagation();
    const L = forgeDockLayout(), st = forgeDockOf(L, p.id);
    forgeDockSet(p.id, st.back || def[3]);
  });
  if (typeof ResizeObserver === "function") {           // a floating panel's corner resize is kept, in %
    let t = 0;
    new ResizeObserver(() => {
      if (p.dataset.dock !== "float" || document.body.classList.contains("fdock-dragging")) return;
      clearTimeout(t);
      t = setTimeout(() => {
        const b = forgeDockBody(); if (!b) return;
        const br = b.getBoundingClientRect(), r = p.getBoundingClientRect();
        if (!br.width || !r.width) return;
        const L = forgeDockLayout(), st = forgeDockOf(L, p.id);
        st.w = +(r.width / br.width * 100).toFixed(2); st.h = +(r.height / br.height * 100).toFixed(2);
        L.panels[p.id] = st; forgeDockStore(L);
        const fv = typeof forge !== "undefined" && forge.view; if (fv) fv.dirty = true;
      }, 160);
    }).observe(p);
  }
}

// ------------------------------------------------------------------------------------------ dragging
// drag(handle, panel, onMove, onEnd): with a panel = move/dock that panel; without = a plain resize drag
function forgeDockDrag(handle, panel, onMove, onEnd) {
  handle.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const ctl = panel && e.target.closest && e.target.closest("button, input, select, .forge-out-fold");
    if (ctl && ctl !== handle) return;
    const x0 = e.clientX, y0 = e.clientY;
    let moving = false, zone = null, off = null;
    try { handle.setPointerCapture(e.pointerId); } catch (_) { /* gone */ }
    const body = forgeDockBody();
    const move = (ev) => {
      if (!panel) { if (!moving) { moving = true; handle.classList.add("drag"); document.body.classList.add("fdock-dragging", "forge-splitting"); } onMove(ev); return; }
      if (!moving && Math.hypot(ev.clientX - x0, ev.clientY - y0) < 6) return;
      const br = body.getBoundingClientRect();
      if (!moving) {
        moving = true;
        ev.preventDefault();
        document.body.classList.add("fdock-dragging");
        const r = panel.getBoundingClientRect();
        if (panel.dataset.dock !== "float") {        // undock: it floats under the pointer at its own size
          const L = forgeDockLayout(), st = forgeDockOf(L, panel.id);
          st.back = panel.dataset.dock;
          st.w = Math.max(14, Math.min(60, r.width / br.width * 100)); st.h = Math.max(20, Math.min(90, r.height / br.height * 100));
          if (panel.id === "fmy-toolbox") { st.w = Math.max(2.5, r.width / br.width * 100); st.h = Math.min(90, r.height / br.height * 100); }
          st.x = (r.left - br.left) / br.width * 100; st.y = (r.top - br.top) / br.height * 100;
          st.dock = "float"; L.panels[panel.id] = st; forgeDockStore(L); forgeDockApply();
        }
        const r2 = panel.getBoundingClientRect();
        off = [x0 - r2.left, y0 - r2.top];
        forgeDockZones(true);
      }
      const nx = Math.max(br.left - panel.offsetWidth + 40, Math.min(br.right - 40, ev.clientX - off[0]));
      const ny = Math.max(br.top, Math.min(br.bottom - 24, ev.clientY - off[1]));
      panel.style.left = ((nx - br.left) / br.width * 100).toFixed(2) + "%";
      panel.style.top = ((ny - br.top) / br.height * 100).toFixed(2) + "%";
      zone = forgeDockZoneAt(ev.clientX, ev.clientY, br);
      forgeDockZones(true, zone);
    };
    const up = () => {
      handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", up); handle.removeEventListener("pointercancel", up);
      handle.classList.remove("drag"); document.body.classList.remove("fdock-dragging", "forge-splitting");
      forgeDockZones(false);
      if (!moving) return;
      // a title that is also a button (the Outliner's fold) must not take the click that ends a drag
      const eat = (ev) => { ev.stopPropagation(); ev.preventDefault(); };
      handle.addEventListener("click", eat, { capture: true, once: true });
      setTimeout(() => handle.removeEventListener("click", eat, { capture: true }), 0);
      if (!panel) { if (onEnd) onEnd(); return; }
      const L = forgeDockLayout(), st = forgeDockOf(L, panel.id);
      if (zone) {
        st.dock = zone.dock; st.rank = zone.rank;
        for (const [id] of FORGE_DOCK_PANELS) {            // make room: the others on that side move one along
          if (id === panel.id) continue;
          const o = forgeDockOf(L, id);
          if (o.dock === zone.dock && (o.rank || 0) >= zone.rank) { o.rank = (o.rank || 0) + 1; L.panels[id] = o; }
        }
      } else {
        const b = body.getBoundingClientRect(), r = panel.getBoundingClientRect();
        st.x = +((r.left - b.left) / b.width * 100).toFixed(2); st.y = +((r.top - b.top) / b.height * 100).toFixed(2);
      }
      L.panels[panel.id] = st; forgeDockStore(L);
      forgeDockApply();
      if (typeof forgeSplitApply === "function") forgeSplitApply();
    };
    handle.addEventListener("pointermove", move); handle.addEventListener("pointerup", up); handle.addEventListener("pointercancel", up);
  });
}

// which dock does a drop at (x, y) mean? null = float where it is
function forgeDockZoneAt(x, y, br) {
  const fx = (x - br.left) / br.width, fy = (y - br.top) / br.height, e = FORGE_DOCK_EDGE;
  if (fx < e) return { dock: "left", rank: fx < e / 2 ? -1 : 50 };
  if (fx > 1 - e) return { dock: "right", rank: fx > 1 - e / 2 ? -1 : 50 };
  if (fy < e) return { dock: "top", rank: 50 };
  if (fy > 1 - e) return { dock: "bottom", rank: 50 };
  return null;
}
function forgeDockZones(on, zone) {
  let host = document.getElementById("fdock-zones");
  const body = forgeDockBody();
  if (!host && on && body) {
    host = document.createElement("div"); host.id = "fdock-zones";
    for (const z of ["left", "right", "top", "bottom"]) { const d = document.createElement("div"); d.className = "fdock-zone fdock-zone-" + z; d.dataset.zone = z; host.append(d); }
    body.append(host);
  }
  if (!host) return;
  host.hidden = !on;
  for (const d of host.children) d.classList.toggle("hot", !!zone && zone.dock === d.dataset.zone);
}

// ------------------------------------------------------------------------------------------ actions
function forgeDockSet(id, dock, rank) {
  const L = forgeDockLayout(), st = forgeDockOf(L, id);
  if (dock === "float" && st.dock !== "float") {
    st.back = st.dock;
    const b = forgeDockBody(), p = document.getElementById(id);
    if (b && p) {
      const br = b.getBoundingClientRect(), r = p.getBoundingClientRect();
      if (br.width && r.width) {
        st.w = Math.max(14, Math.min(50, r.width / br.width * 100)); st.h = Math.max(25, Math.min(80, r.height / br.height * 100));
        st.x = Math.min(100 - st.w - 2, Math.max(2, (r.left - br.left) / br.width * 100 + 4)); st.y = 8;
      }
    }
  }
  st.dock = dock;
  if (rank != null) st.rank = rank;
  L.panels[id] = st; forgeDockStore(L);
  forgeDockApply();
  if (typeof forgeSplitApply === "function") forgeSplitApply();
  const def = FORGE_DOCK_PANELS.find((x) => x[0] === id);
  return (def ? def[1] : id) + (dock === "float" ? " floats." : " docked " + dock + ".");
}
function forgeDockToggleFloat(id) {
  const L = forgeDockLayout(), st = forgeDockOf(L, id);
  const def = FORGE_DOCK_PANELS.find((x) => x[0] === id);
  return forgeDockSay(st.dock === "float" ? forgeDockSet(id, st.back || (def ? def[3] : "left")) : forgeDockSet(id, "float"));
}
function forgeDockClose(id) {
  const def = FORGE_DOCK_PANELS.find((x) => x[0] === id);
  const how = def ? def[4] : "";
  let msg = "";
  if (how === "toolbox" && typeof fmyUiSet === "function") { fmyUiSet("toolbox", false); msg = "Tool Box hidden (Windows > UI Elements brings it back)."; }
  else if (how === "uv" || how === "materials") {
    if (window.ForgeUVEditor) msg = ForgeUVEditor.setWorkspace("model");
  } else if (how && typeof forgeProPanel === "function") msg = forgeProPanel(how, false);
  else { const p = document.getElementById(id); if (p) p.hidden = true; }
  forgeDockApply();
  return forgeDockSay(msg);
}
function forgeDockSay(msg) { if (msg && typeof forgeSay === "function") forgeSay(msg); return msg; }

function forgeDockMenu(id, x, y) {
  document.getElementById("fdock-menu")?.remove();
  const m = document.createElement("div");
  m.id = "fdock-menu"; m.className = "fmy-drop fdock-menu"; m.setAttribute("role", "menu");
  const item = (label, fn) => {
    const b = document.createElement("button"); b.type = "button"; b.className = "fmy-ditem";
    b.append(Object.assign(document.createElement("span"), { className: "fmy-tick" }), Object.assign(document.createElement("span"), { className: "fmy-dlabel", textContent: label }));
    b.addEventListener("click", (e) => { e.stopPropagation(); m.remove(); forgeDockSay(fn()); });
    m.append(b);
  };
  const def = FORGE_DOCK_PANELS.find((p) => p[0] === id) || [id, id, "panel"];
  item("Dock left", () => forgeDockSet(id, "left", 50));
  item("Dock right", () => forgeDockSet(id, "right", 50));
  if (def[2] !== "bar") { item("Dock above the viewport", () => forgeDockSet(id, "top")); item("Dock below the viewport", () => forgeDockSet(id, "bottom")); item("Float", () => forgeDockSet(id, "float")); }
  m.append(Object.assign(document.createElement("div"), { className: "fmy-sep" }));
  item("Close", () => forgeDockClose(id));
  item("Reset the layout", () => forgeDockReset());
  item("Layouts...", () => forgeDockLayoutsPanel());
  m.style.left = Math.round(Math.min(x, window.innerWidth - 230)) + "px";
  m.style.top = Math.round(Math.min(y, window.innerHeight - 260)) + "px";
  document.body.append(m);
  const off = (e) => { if (!m.contains(e.target)) { m.remove(); document.removeEventListener("pointerdown", off, true); } };
  setTimeout(() => document.addEventListener("pointerdown", off, true), 0);
}

function forgeDockReset() {
  const all = forgeDockLoad(FORGE_DOCK_STORE, {});
  delete all[forgeDockKey()];
  forgeDockSave(FORGE_DOCK_STORE, all);
  forgeDockSave(FORGE_DOCK_FLOATS, {});
  if (typeof forgeSplitReset === "function") forgeSplitReset();
  forgeDockApply();
  forgeDockBarsApply();
  return "Layout back to the default for this workspace and screen shape.";
}

// ------------------------------------------------------------------------------------------ the Channel Box column's parts
// [column, part, default % of the column (null = its own height), can fold]
const FORGE_DOCK_SUBS = [["forge-chancol", "forge-history", null, true], ["forge-chancol", "forge-layer-editor", null, true]];
function forgeDockSubpanels() {
  const folds = forgeDockLoad("loki-forge-folds", {});
  for (const [col, id] of FORGE_DOCK_SUBS) {
    const c = document.getElementById(col), s = document.getElementById(id);
    if (!c || !s) continue;
    const head = s.querySelector(".forge-hist-head, .forge-layer-head");
    if (head && !head.querySelector(".fdock-fold")) {
      const f = document.createElement("button");
      f.type = "button"; f.className = "fdock-fold"; f.setAttribute("aria-label", "Fold");
      f.title = "Fold / unfold " + (id === "forge-history" ? "INPUTS (the construction history)" : "the Display Layers");
      f.addEventListener("click", (e) => {
        e.stopPropagation();
        const fl = forgeDockLoad("loki-forge-folds", {}); fl[id] = !fl[id]; forgeDockSave("loki-forge-folds", fl);
        forgeDockSubpanels();
        const fv = typeof forge !== "undefined" && forge.view; if (fv) fv.dirty = true;
      });
      head.prepend(f);
    }
    s.classList.toggle("fdock-folded", !!folds[id]);
  }
  // a second splitter: how much of the column INPUTS takes (the Display Layers one is forge_split.js)
  const c = document.getElementById("forge-chancol"), hist = document.getElementById("forge-history");
  if (c && hist && !document.getElementById("forge-split-hist")) {
    const h = document.createElement("div");
    h.className = "forge-split-h"; h.id = "forge-split-hist";
    h.title = "Drag up or down: how much of the column INPUTS takes (double-click resets).";
    h.setAttribute("role", "separator"); h.setAttribute("aria-orientation", "horizontal");
    hist.before(h);
    forgeDockDrag(h, null, (ev) => {
      const lay = document.getElementById("forge-layer-editor");
      const cr = c.getBoundingClientRect(), lr = lay && !lay.hidden ? lay.getBoundingClientRect() : null;
      const bottom = lr && lr.height ? lr.top : cr.bottom;
      const pct = Math.max(4, Math.min(70, ((bottom - ev.clientY) / (cr.height || 1)) * 100));
      hist.style.flex = "0 0 " + pct.toFixed(2) + "%"; h.dataset.pct = pct.toFixed(1);
    }, () => { const L = forgeDockLayout(); if (h.dataset.pct) L.hist = Number(h.dataset.pct); forgeDockStore(L); });
    h.addEventListener("dblclick", () => { const L = forgeDockLayout(); delete L.hist; forgeDockStore(L); hist.style.flex = ""; });
  }
  const L = forgeDockLayout();
  if (hist && L.hist && !hist.classList.contains("fdock-folded")) hist.style.flex = "0 0 " + L.hist + "%";
  else if (hist) hist.style.flex = "";
  const hs = document.getElementById("forge-split-hist");
  if (hs && hist) hs.hidden = hist.hidden || hist.classList.contains("fdock-folded");
}

// ------------------------------------------------------------------------------------------ interface size
// Auto: the panels' contents follow the screen (a big screen gets bigger text and buttons, a small one smaller);
// a fixed % overrides. The viewport is never scaled (picking stays exact).
const FORGE_DOCK_SCALED = ["#fmy-menubar", "#fmy-status", "#fmy-shelf", "#fmy-toolbox", "#forge-outcol", "#forge-chancol", "#forge-left", "#fmy-time", "#fmy-helpline"];
function forgeDockAutoScale() {
  const s = Math.min(window.innerWidth / 1440, window.innerHeight / 900);
  const c = Math.max(0.8, Math.min(1.35, s));
  return c > 0.88 && c < 1.12 ? 1 : +c.toFixed(2);    // close to a normal screen: leave it exactly as drawn
}
function forgeDockScaleValue() {
  const g = forgeDockLoad("loki-forge-ui-scale", { mode: "auto", pct: 100 });
  return g.mode === "auto" ? forgeDockAutoScale() : Math.max(0.6, Math.min(2, (g.pct || 100) / 100));
}
function forgeDockScale() {
  const z = forgeDockScaleValue();
  for (const sel of FORGE_DOCK_SCALED) for (const e of document.querySelectorAll("#forge " + sel)) e.style.zoom = z === 1 ? "" : String(z);
  return z;
}

// ------------------------------------------------------------------------------------------ the bars over the viewport
// every .forge-float in the stage gets a grip; a moved bar is offset with the CSS `translate` property (its own code
// keeps setting left/top), stored as a fraction of the stage so it keeps its place on any size
function forgeDockBars() {
  const stage = document.getElementById("forge-stage");
  if (!stage) return;
  for (const f of stage.querySelectorAll(":scope > .forge-float")) {
    if (!f.id || f.classList.contains("forge-opt-btn") || f.querySelector(":scope > .fdock-bargrip")) continue;
    const g = document.createElement("span");
    g.className = "fdock-bargrip";
    g.title = "Drag to move this bar anywhere over the viewport - double-click puts it back.";
    g.setAttribute("aria-label", "Move");
    f.prepend(g);
    let start = null;
    g.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopPropagation();
      try { g.setPointerCapture(e.pointerId); } catch (_) { /* gone */ }
      const all = forgeDockLoad(FORGE_DOCK_FLOATS, {}), o = all[f.id] || { dx: 0, dy: 0 };
      start = { x: e.clientX, y: e.clientY, dx: o.dx, dy: o.dy };
      document.body.classList.add("fdock-dragging");
    });
    g.addEventListener("pointermove", (e) => {
      if (!start) return;
      const r = stage.getBoundingClientRect();
      const o = { dx: start.dx + (e.clientX - start.x) / (r.width || 1), dy: start.dy + (e.clientY - start.y) / (r.height || 1) };
      forgeDockBarPlace(f, o, r);
      f.dataset.fdockMove = JSON.stringify(o);
    });
    const end = () => {
      if (!start) return;
      start = null; document.body.classList.remove("fdock-dragging");
      if (f.dataset.fdockMove) { const all = forgeDockLoad(FORGE_DOCK_FLOATS, {}); all[f.id] = JSON.parse(f.dataset.fdockMove); forgeDockSave(FORGE_DOCK_FLOATS, all); }
    };
    g.addEventListener("pointerup", end); g.addEventListener("pointercancel", end);
    g.addEventListener("dblclick", (e) => { e.stopPropagation(); const all = forgeDockLoad(FORGE_DOCK_FLOATS, {}); delete all[f.id]; forgeDockSave(FORGE_DOCK_FLOATS, all); f.style.translate = ""; f.classList.remove("fdock-moved"); });
  }
  forgeDockBarsApply();
}
function forgeDockBarPlace(f, o, r) {
  // keep at least 40 px of the bar on the stage
  const fr = f.getBoundingClientRect();
  const cur = (f.style.translate || "0px 0px").split(" ").map(parseFloat);
  const baseL = fr.left - (cur[0] || 0), baseT = fr.top - (cur[1] || 0);
  let dx = o.dx * r.width, dy = o.dy * r.height;
  dx = Math.max(r.left - baseL - fr.width + 40, Math.min(r.right - baseL - 40, dx));
  dy = Math.max(r.top - baseT, Math.min(r.bottom - baseT - 20, dy));
  f.style.translate = Math.round(dx) + "px " + Math.round(dy) + "px";
  f.classList.add("fdock-moved");
}
function forgeDockBarsApply() {
  const stage = document.getElementById("forge-stage");
  if (!stage) return;
  const all = forgeDockLoad(FORGE_DOCK_FLOATS, {}), r = stage.getBoundingClientRect();
  for (const f of stage.querySelectorAll(":scope > .forge-float")) {
    if (all[f.id] && r.width) forgeDockBarPlace(f, all[f.id], r);
    else if (!all[f.id]) { f.style.translate = ""; f.classList.remove("fdock-moved"); }
  }
}

// ------------------------------------------------------------------------------------------ Windows > Layouts
function forgeDockLayoutsPanel() {
  let p = document.getElementById("fdock-layouts");
  if (p) { p.remove(); return "Layouts closed."; }
  p = document.createElement("div");
  p.id = "fdock-layouts"; p.className = "fdock-dialog";
  p.setAttribute("role", "dialog"); p.setAttribute("aria-label", "Layouts");
  const h = document.createElement("div"); h.className = "fdock-head fdock-handle";
  h.append(Object.assign(document.createElement("span"), { className: "fdock-title", textContent: "Layouts" }));
  const x = document.createElement("button"); x.type = "button"; x.className = "fdock-btn fdock-b-close"; x.title = "Close"; x.setAttribute("aria-label", "Close");
  x.addEventListener("click", () => p.remove());
  h.append(x);
  const list = document.createElement("div"); list.className = "fdock-list";
  const name = document.createElement("input"); name.type = "text"; name.placeholder = "Name this layout"; name.id = "fdock-name";
  name.addEventListener("keydown", (e) => e.stopPropagation());
  const save = document.createElement("button"); save.type = "button"; save.className = "mini"; save.textContent = "Save"; save.id = "fdock-save";
  save.title = "Save the current layout (panels, sizes, the bars over the viewport) under this name.";
  const reset = document.createElement("button"); reset.type = "button"; reset.className = "mini"; reset.textContent = "Reset to default"; reset.id = "fdock-reset";
  reset.title = "Back to the default layout for this workspace and screen shape.";
  const scaleRow = document.createElement("label"); scaleRow.className = "fdock-scale";
  const sc = document.createElement("select"); sc.id = "fdock-scale";
  for (const [v, t] of [["auto", "Auto (follows the screen)"], ["80", "80%"], ["90", "90%"], ["100", "100%"], ["110", "110%"], ["125", "125%"], ["150", "150%"]]) { const o = document.createElement("option"); o.value = v; o.textContent = t; sc.append(o); }
  const g = forgeDockLoad("loki-forge-ui-scale", { mode: "auto", pct: 100 });
  sc.value = g.mode === "auto" ? "auto" : String(g.pct);
  sc.addEventListener("change", () => { forgeDockSave("loki-forge-ui-scale", sc.value === "auto" ? { mode: "auto", pct: 100 } : { mode: "pct", pct: +sc.value }); forgeDockScale(); forgeDockSay("Interface size: " + sc.options[sc.selectedIndex].textContent + "."); });
  scaleRow.append(Object.assign(document.createElement("span"), { textContent: "Interface size" }), sc);
  const render = () => {
    list.textContent = "";
    const named = forgeDockLoad(FORGE_DOCK_NAMED, {});
    const names = Object.keys(named).sort();
    if (!names.length) list.append(Object.assign(document.createElement("div"), { className: "fdock-empty", textContent: "No saved layouts yet." }));
    for (const n of names) {
      const row = document.createElement("div"); row.className = "fdock-row";
      const load = document.createElement("button"); load.type = "button"; load.className = "fdock-load"; load.textContent = n; load.title = "Use this layout.";
      load.addEventListener("click", () => forgeDockSay(forgeDockUse(n)));
      const del = document.createElement("button"); del.type = "button"; del.className = "fdock-btn fdock-b-close"; del.title = "Delete this saved layout"; del.setAttribute("aria-label", "Delete " + n);
      del.addEventListener("click", () => { const all = forgeDockLoad(FORGE_DOCK_NAMED, {}); delete all[n]; forgeDockSave(FORGE_DOCK_NAMED, all); render(); });
      row.append(load, del); list.append(row);
    }
  };
  save.addEventListener("click", () => { const n = name.value.trim(); if (!n) { name.focus(); return; } forgeDockSay(forgeDockSaveAs(n)); name.value = ""; render(); });
  reset.addEventListener("click", () => forgeDockSay(forgeDockReset()));
  const row = document.createElement("div"); row.className = "fdock-row"; row.append(name, save);
  p.append(h, row, list, scaleRow, reset);
  (document.getElementById("forge") || document.body).append(p);
  render();
  // the dialog itself moves by its title
  let st = null;
  h.addEventListener("pointerdown", (e) => { if (e.target.closest("button")) return; const r = p.getBoundingClientRect(); st = [e.clientX - r.left, e.clientY - r.top]; try { h.setPointerCapture(e.pointerId); } catch (_) { /* gone */ } });
  h.addEventListener("pointermove", (e) => { if (!st) return; p.style.left = Math.max(0, Math.min(window.innerWidth - 60, e.clientX - st[0])) / window.innerWidth * 100 + "%"; p.style.top = Math.max(0, Math.min(window.innerHeight - 30, e.clientY - st[1])) / window.innerHeight * 100 + "%"; p.style.right = "auto"; });
  h.addEventListener("pointerup", () => { st = null; });
  return "Layouts: save, load or reset the panel layout; the interface size is here too.";
}
function forgeDockSaveAs(n) {
  const named = forgeDockLoad(FORGE_DOCK_NAMED, {});
  named[n] = { layout: forgeDockLayout(), split: typeof forgeSplitLoad === "function" ? forgeSplitLoad() : {}, bars: forgeDockLoad(FORGE_DOCK_FLOATS, {}) };
  forgeDockSave(FORGE_DOCK_NAMED, named);
  return "Layout \"" + n + "\" saved.";
}
function forgeDockUse(n) {
  const named = forgeDockLoad(FORGE_DOCK_NAMED, {}), s = named[n];
  if (!s) return "No layout called " + n + ".";
  forgeDockStore(JSON.parse(JSON.stringify(s.layout || {})));
  if (s.split && typeof forgeSplitSave === "function") forgeSplitSave(s.split);
  forgeDockSave(FORGE_DOCK_FLOATS, s.bars || {});
  forgeDockApply();
  if (typeof forgeSplitApply === "function") forgeSplitApply();
  forgeDockBarsApply();
  return "Layout \"" + n + "\" in use.";
}

// ------------------------------------------------------------------------------------------ hooks
// the window changing shape (a monitor turned on its side, the window dragged to another screen) re-applies
(function forgeDockWatch() {
  let lastKey = "", t = 0;
  const tick = () => {
    const body = forgeDockBody();
    if (!body || !body.isConnected) return;
    const k = forgeDockKey();
    if (k !== lastKey) { lastKey = k; forgeDockApply(); if (typeof forgeSplitApply === "function") forgeSplitApply(); }
    for (const [id] of forgeDockList()) { const p = document.getElementById(id); if (p && !p.dataset.fdock && p.parentElement === body) forgeDockDress(p); }
    forgeDockBars();
  };
  window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => { tick(); forgeDockScale(); forgeDockBarsApply(); }, 120); });
  setInterval(tick, 700);
})();

if (typeof FORGE_PRO_CMDS !== "undefined") {
  const add = (id, label, fn) => { if (!FORGE_PRO_CMDS[id]) FORGE_PRO_CMDS[id] = [label, fn]; };
  add("layouts", "Layouts... (save / load / reset, interface size)", () => forgeDockLayoutsPanel());
  add("layoutReset", "Reset the Layout", () => forgeDockReset());
}
