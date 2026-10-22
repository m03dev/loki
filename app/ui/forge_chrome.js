// Forge dressed as a pro package - the window chrome and the viewport, matched to the reference package on the owner's Mac (2026-10-19:
// "make it look and feel more like pro ... do more research"). Everything here was checked against screenshots of the
// real app: the colours were sampled off them (panels #444444, lists #373737, fields #2b2b2b, selection #5285a6,
// viewport gradient #879bb3 -> #131418, matte grey shading, teal-green selection wireframe).
//
//   the window   menu bar (File Edit Create Select Modify Display Windows Mesh Edit Mesh Mesh Tools Mesh Display Help),
//                status line (menu set, selection modes, snapping, symmetry, panel toggles), shelf with tabs, the tool
//                box down the left, and the help line + command line along the bottom
//   the viewport its own menu bar (View Shading Lighting Show Renderer Panels) and icon bar, the heads-up poly count,
//                the camera name, the axis triad, the view cube, the pro grid and the pro default lighting
//
// Behaviour, not code: nothing of the vendor's is used. Every command runs through FORGE_PRO_CMDS (forge_pro.js), so
// the menus, the shelf, the hotbox, the wheel and the hotkeys stay one set. Each part can be hidden from
// Windows > UI Elements (or all at once with Ctrl+Space), and nothing that was there before was taken away.
"use strict";

const FMY_SVG = {
  sphere: '<circle cx="12" cy="12" r="8"/><ellipse cx="12" cy="12" rx="8" ry="3"/><path d="M12 4v16"/>',
  cube: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
  cylinder: '<ellipse cx="12" cy="6" rx="7" ry="2.6"/><path d="M5 6v12c0 1.5 3 2.6 7 2.6s7-1.1 7-2.6V6"/>',
  cone: '<path d="M12 3l7 15c0 1.5-3 2.6-7 2.6s-7-1.1-7-2.6z"/><ellipse cx="12" cy="18" rx="7" ry="2.6"/>',
  torus: '<ellipse cx="12" cy="12" rx="9" ry="5"/><ellipse cx="12" cy="11.5" rx="3.6" ry="1.6"/>',
  plane: '<path d="M3 15l7-6h11l-7 6z"/>',
  quadsphere: '<circle cx="12" cy="12" r="8"/><path d="M6 7.5c4 2 8 2 12 0M6 16.5c4-2 8-2 12 0M8 5c-1.5 4.5-1.5 9.5 0 14M16 5c1.5 4.5 1.5 9.5 0 14"/>',
  extrude: '<path d="M5 15l7-4 7 4-7 4z"/><path d="M5 9l7-4 7 4-7 4z" stroke-dasharray="2 1.5"/><path d="M12 13v-6"/>',
  inset: '<path d="M4 12l8-6 8 6-8 6z"/><path d="M8.5 12L12 9.4l3.5 2.6L12 14.6z"/>',
  bevel: '<path d="M4 18V9l5-5h11v14z"/><path d="M9 4v5H4"/>',
  edgeLoop: '<rect x="4" y="4" width="16" height="16" rx="1"/><path d="M12 4v16" stroke-dasharray="2 1.6"/>',
  multiCut: '<path d="M5 19L19 5"/><path d="M14 5h5v5"/><circle cx="7" cy="17" r="1.6"/>',
  smooth: '<rect x="5" y="5" width="14" height="14" rx="6"/>',
  reverse: '<path d="M6 8h11l-3-3M18 16H7l3 3"/>',
  dynamesh: '<path d="M4 4h16v16H4z"/><path d="M4 9.3h16M4 14.6h16M9.3 4v16M14.6 4v16"/>',
  sculpt: '<path d="M4 20c3-1 5-4 7-8l5-7 3 3-7 5c-4 2-7 4-8 7z"/>',
  select: '<path d="M6 3l12 9-6 1 3 7-2.5 1-3-7-3.5 4z" fill="currentColor"/>',
  lasso: '<ellipse cx="13" cy="9" rx="7" ry="5"/><path d="M8 13c-2 2-1 5 1 6"/>',
  paint: '<path d="M14 4l6 6-8 8-4-1-1-4z"/><path d="M5 19l3-3"/>',
  move: '<path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M21 12l-3-3M21 12l-3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3"/>',
  rotate: '<path d="M19 12a7 7 0 1 1-2.05-4.95"/><path d="M19.5 4v4h-4"/>',
  scale: '<rect x="4" y="11" width="9" height="9"/><path d="M11 4h9v9M20 4l-8 8"/>',
  single: '<rect x="4" y="4" width="16" height="16"/>',
  four: '<rect x="4" y="4" width="16" height="16"/><path d="M12 4v16M4 12h16"/>',
  outliner: '<rect x="4" y="4" width="16" height="16"/><path d="M9 4v16M11 8h7M11 12h7M11 16h7"/>',
  channel: '<rect x="4" y="4" width="16" height="16"/><path d="M14 4v16M5.5 8h7M5.5 12h7M5.5 16h7"/>',
  toolkit: '<rect x="4" y="4" width="16" height="16"/><path d="M15 4v16M16.5 8h2M16.5 12h2"/>',
  create: '<rect x="4" y="4" width="16" height="16"/><path d="M9 4v16M5.5 9h2M5.5 13h2"/>',
  materials: '<circle cx="12" cy="12" r="8"/><path d="M6 10c3 2 9 2 12 0"/>',
  objmode: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" fill="currentColor" fill-opacity=".35"/>',
  vertmode: '<path d="M4 7l8-4 8 4v10l-8 4-8-4z" stroke-opacity=".35"/><circle cx="12" cy="3.8" r="2" fill="currentColor"/><circle cx="4.5" cy="7.5" r="2" fill="currentColor"/><circle cx="19.5" cy="7.5" r="2" fill="currentColor"/><circle cx="12" cy="20" r="2" fill="currentColor"/>',
  edgemode: '<path d="M4 7l8-4 8 4v10l-8 4-8-4z" stroke-opacity=".35"/><path d="M4 7l8 4 8-4M12 11v10" stroke-width="2.4"/>',
  facemode: '<path d="M4 7l8-4 8 4v10l-8 4-8-4z" stroke-opacity=".35"/><path d="M4 7l8 4v10l-8-4z" fill="currentColor"/>',
  snapgrid: '<path d="M4 8h16M4 16h16M8 4v16M16 4v16"/><circle cx="16" cy="16" r="2.2" fill="currentColor"/>',
  snapedge: '<path d="M4 18C8 6 16 6 20 18"/><circle cx="12" cy="9" r="2.2" fill="currentColor"/>',
  snappoint: '<path d="M4 18L12 6l8 12z" stroke-opacity=".5"/><circle cx="12" cy="6" r="2.6" fill="currentColor"/>',
  symmetry: '<path d="M12 3v18" stroke-dasharray="2 2"/><path d="M9 7L4 12l5 5M15 7l5 5-5 5"/>',
  save: '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
  undo: '<path d="M9 7L4 12l5 5"/><path d="M4 12h10a6 6 0 0 1 0 12" transform="translate(0 -6)"/>',
  redo: '<path d="M15 7l5 5-5 5"/><path d="M20 12H10a6 6 0 0 0 0 12" transform="translate(0 -6)"/>',
  frameall: '<rect x="4" y="4" width="16" height="16" stroke-dasharray="3 2"/><rect x="8" y="8" width="8" height="8"/>',
  framesel: '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/><rect x="9" y="9" width="6" height="6" fill="currentColor"/>',
  wire: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l16 9M20 7.5l-16 9M12 3v18"/>',
  shaded: '<circle cx="12" cy="12" r="8" fill="currentColor" fill-opacity=".55"/>',
  textured: '<circle cx="12" cy="12" r="8"/><path d="M6 8l12 8M6 14l8 5M10 5l9 6"/>',
  xray: '<rect x="4" y="4" width="11" height="11"/><rect x="9" y="9" width="11" height="11" stroke-dasharray="2 2"/>',
  grid: '<path d="M3 15l9-5 9 5-9 5z"/><path d="M7.5 12.5l9 5M16.5 12.5l-9 5"/>',
  light: '<circle cx="12" cy="10" r="5"/><path d="M10 16h4v3h-4z"/>',
  isolate: '<rect x="4" y="4" width="16" height="16" stroke-dasharray="3 2"/><circle cx="12" cy="12" r="3.5" fill="currentColor"/>',
  hud: '<rect x="4" y="5" width="16" height="14"/><path d="M6.5 8.5h5M6.5 11h5M6.5 13.5h5"/>',
  camera: '<rect x="3" y="8" width="13" height="9" rx="1"/><path d="M16 11l5-3v9l-5-3z"/>',
  home: '<path d="M4 12l8-7 8 7M7 10v9h10v-9"/>',
};
// the symmetry bitmask as text: 1 X, 2 Y, 4 Z (shared by the status button and the periodic label update)
function fmySymText(bits, radial, axis) {
  bits = bits | 0; radial = radial | 0;
  const out = [];
  if (bits) out.push("Object " + ["X", "Y", "Z"].filter((_, i) => bits & (1 << i)).join(""));
  if (radial > 1) out.push("Radial " + radial + " " + (["X", "Y", "Z"][axis | 0] || "Y"));
  return out.length ? out.join(" \u00b7 ") : "Off";
}

function fmySvg(name) {
  return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + (FMY_SVG[name] || FMY_SVG.cube) + "</svg>";
}
function fmyEl(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
const fmyView = () => (typeof forge !== "undefined" ? forge.view : null);
const fmyCmd = (id) => (typeof FORGE_PRO_CMDS !== "undefined" ? FORGE_PRO_CMDS[id] : null);
function fmyRun(id) {
  const v = fmyView();
  if (!v || typeof forgeProRun !== "function") { if (typeof forgeSay === "function") forgeSay("Make or add something first.", true); return; }
  return forgeProRun(v, id);
}
function fmyOn(id) {                                          // is a switch command on? (the hotbox's ticks)
  const v = fmyView();
  try { return !!(typeof FORGE_PRO_TOGGLES !== "undefined" && FORGE_PRO_TOGGLES[id] && v && FORGE_PRO_TOGGLES[id](v)); } catch (_) { return false; }
}
// hotkey hints shown in the menus, pro-style
// the key shown beside a command: the user's own hotkey set first (forge_keys.js), else the printed default
function fmyKeyOf(id) {
  if (window.forgeHotkeys) { const k = window.forgeHotkeys.keysFor(id); if (k.length) return window.forgeHotkeys.label(k[0]); }
  return (typeof FMY_KEYS !== "undefined" && FMY_KEYS[id]) || "";
}
const FMY_KEYS = { undo: "Ctrl+Z", redo: "Ctrl+Shift+Z", duplicate: "Ctrl+D", duplicateT: "Shift+D", group: "Ctrl+G", ungroup: "Ctrl+Shift+G",
  parent: "P", unparent: "Shift+P", delete: "Del", selectAll: "Ctrl+Shift+A", selectNone: "Alt+D", invert: "Ctrl+Shift+I", grow: ">", shrink: "<",
  objComp: "F8", vertex: "F9", edge: "F10", face: "F11", select: "Q", move: "W", rotate: "E", scale: "R", pivotEdit: "D", frameSel: "F", frameAll: "A",
  wire: "4", shaded: "5", textured: "6", lights: "7", xray: "Alt+X", hide: "Ctrl+H", showLast: "Ctrl+Shift+H", hideOthers: "Alt+H", isolate: "Ctrl+1",
  extrude: "Ctrl+E", bevel: "Ctrl+B", deleteEdgeVert: "Ctrl+Delete", softSel: "B", hideUI: "Ctrl+Space", save: "Ctrl+S", snapGrid: "X", snapEdge: "C", snapPoint: "V", defaultView: "Alt+Home" };

// ================================================================== drop-down menus (pro's: click opens, hover switches)
let fmyOpenMenu = null;
function fmyCloseMenus() {
  document.querySelectorAll(".fmy-drop").forEach((d) => d.remove());
  document.querySelectorAll(".fmy-mb.open").forEach((b) => b.classList.remove("open"));
  fmyOpenMenu = null;
}
// keep a menu box inside the window: shift it back on screen, and let a long one scroll (owner 2026-10-22: menu rows
// that ran off the window "can't even click them")
function fmyFit(d) {
  d.style.maxHeight = Math.max(120, window.innerHeight - 12) + "px";
  const r = d.getBoundingClientRect();
  let x = parseFloat(d.style.left) || r.left, y = parseFloat(d.style.top) || r.top;
  if (r.right > window.innerWidth - 4) x -= r.right - (window.innerWidth - 4);
  if (x < 4) x = 4;
  if (r.bottom > window.innerHeight - 4) y -= r.bottom - (window.innerHeight - 4);
  if (y < 4) y = 4;
  d.style.left = Math.round(x) + "px"; d.style.top = Math.round(y) + "px";
}
// close every submenu deeper than depth
function fmyCloseDeeper(depth) {
  for (const d of document.querySelectorAll(".fmy-drop")) if ((+d.dataset.depth || 0) > depth) d.remove();
}
// one row of a menu: a command, a window row ([id, label, run, on]) or a submenu (["Label", [entries]])
function fmyRow(it, depth) {
  if (typeof forgeMenuIsSub === "function" ? forgeMenuIsSub(it) : (Array.isArray(it) && Array.isArray(it[1]))) {
    if (typeof forgeMenuSubLive === "function" && !forgeMenuSubLive(it)) return null;
    const b = fmyEl("button", "fmy-ditem fmy-dsub");
    b.type = "button"; b.dataset.sub = it[0];
    b.setAttribute("aria-haspopup", "menu");
    b.append(fmyEl("span", "fmy-tick", ""), fmyEl("span", "fmy-dlabel", it[0]), fmyEl("span", "fmy-dkey fmy-arrow", "\u25b8"));
    const open = () => {
      if (b.classList.contains("open") && document.querySelector('.fmy-drop[data-depth="' + (depth + 1) + '"]')) return;
      fmyCloseDeeper(depth);
      for (const x of b.parentElement.querySelectorAll(".fmy-dsub.open")) x.classList.remove("open");
      b.classList.add("open");
      fmySubDrop(b, it[1], depth + 1);
    };
    b.addEventListener("pointerenter", () => { clearTimeout(fmyRow.t); fmyRow.t = setTimeout(open, 110); });
    b.addEventListener("pointerleave", () => clearTimeout(fmyRow.t));
    b.addEventListener("click", (ev) => { ev.stopPropagation(); clearTimeout(fmyRow.t); open(); });
    return b;
  }
  const [id, label, run, on] = Array.isArray(it) ? it : [it];
  const c = fmyCmd(id);
  if (!run && !(c && c[1])) return null;                 // not in Forge yet: left out, a menu must not lie
  const b = fmyEl("button", "fmy-ditem");
  b.type = "button"; b.dataset.proId = id || "";
  const ticked = on != null ? on() : fmyOn(id);
  b.append(fmyEl("span", "fmy-tick", ticked ? "\u2713" : ""), fmyEl("span", "fmy-dlabel", label || (c ? c[0] : id)),
    fmyEl("span", "fmy-dkey", fmyKeyOf(id)));
  b.addEventListener("pointerenter", () => { clearTimeout(fmyRow.t); fmyRow.t = setTimeout(() => { fmyCloseDeeper(depth); for (const x of b.parentElement.querySelectorAll(".fmy-dsub.open")) x.classList.remove("open"); }, 160); });
  b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    clearTimeout(fmyRow.t);
    fmyCloseMenus();
    if (run) run(); else fmyRun(id);
  });
  return b;
}
// fill a menu box with its rows; separators and headings are dropped where nothing follows them
function fmyFill(d, items, depth) {
  let pend = [];
  for (const it of items) {
    if (it === "-") { if (d.querySelector(".fmy-ditem")) pend = [fmyEl("div", "fmy-sep")]; continue; }
    if (typeof it === "string" && it.startsWith("#")) { pend = pend.filter((x) => x.classList.contains("fmy-sep")).concat([fmyEl("div", "fmy-dhead", it.slice(1))]); continue; }
    if (it && it.note) { d.append(...pend, fmyEl("div", "fmy-dnote", it.note)); pend = []; continue; }
    const row = fmyRow(it, depth);
    if (!row) continue;
    d.append(...pend, row); pend = [];
  }
  if (!d.querySelector(".fmy-ditem")) d.append(fmyEl("div", "fmy-dhead", "Nothing here yet"));
}
// a submenu: beside its row, on the right (or the left when the right has no room)
function fmySubDrop(row, items, depth) {
  const d = fmyEl("div", "fmy-drop fmy-subdrop");
  d.setAttribute("role", "menu"); d.dataset.depth = String(depth); d.dataset.sub = row.dataset.sub;
  fmyFill(d, items, depth);
  document.body.append(d);
  const r = row.getBoundingClientRect(), w = d.getBoundingClientRect().width;
  const over = r.right + w + 4 - window.innerWidth;        // flip left only when a nudge would not do
  d.style.left = Math.round(over <= w / 3 ? Math.min(r.right - 2, window.innerWidth - w - 4) : r.left - w + 2) + "px";
  d.style.top = Math.round(r.top - 4) + "px";
  fmyFit(d);
  return d;
}
function fmyDrop(anchor, items) {
  fmyCloseMenus();
  const d = fmyEl("div", "fmy-drop");
  d.setAttribute("role", "menu"); d.dataset.depth = "0";
  fmyFill(d, items, 0);
  const r = anchor.getBoundingClientRect();
  d.style.left = Math.round(r.left) + "px";
  d.style.top = Math.round(r.bottom) + "px";
  document.body.append(d);
  fmyFit(d);
  anchor.classList.add("open");
  fmyOpenMenu = anchor;
  return d;
}
document.addEventListener("pointerdown", (e) => {
  if (!fmyOpenMenu) return;
  if (e.target.closest && (e.target.closest(".fmy-drop") || e.target.closest(".fmy-mb"))) return;
  fmyCloseMenus();
}, true);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && fmyOpenMenu) { e.preventDefault(); e.stopImmediatePropagation(); fmyCloseMenus(); }
}, true);
// the menu bar's menus: built from the catalogue, and rebuilt in place when the menu set changes
function fmyBuildMenubar(mb) {
  mb = mb || document.getElementById("fmy-menubar");
  if (!mb) return;
  for (const b of [...mb.querySelectorAll(".fmy-mb")]) b.remove();
  const tail = [...mb.children].find((c) => c.classList.contains("fmy-grow"));
  for (const [label, items] of FMY_MENUS()) {
    const b = fmyMenuButton(label, () => {
      const found = FMY_MENUS().find((m) => m[0] === label);
      return found ? found[1] : [];
    });
    mb.insertBefore(b, tail || null);
  }
}
window.fmyBuildMenubar = fmyBuildMenubar;
function fmyMenuButton(label, items, cls) {
  const b = fmyEl("button", "fmy-mb" + (cls ? " " + cls : ""), label);
  b.type = "button";
  b.dataset.menu = label;
  b._items = items;
  b.addEventListener("click", (e) => { e.stopPropagation(); if (fmyOpenMenu === b) fmyCloseMenus(); else fmyDrop(b, typeof items === "function" ? items() : items); });
  b.addEventListener("pointerenter", () => { if (fmyOpenMenu && fmyOpenMenu !== b && fmyOpenMenu.parentElement === b.parentElement) fmyDrop(b, typeof items === "function" ? items() : items); });
  return b;
}

// ================================================================== the UI elements (Windows > UI Elements), remembered
const FMY_UI = { statusline: "Status Line", shelfbar: "Shelf", toolbox: "Tool Box", timeslider: "Time Slider", helpline: "Help Line", hud: "Heads Up Display",
  viewcube: "View Cube", panelbar: "Panel Menus and Toolbar" };
const FMY_UI_OFF = new Set(["shelfbar"]);         // off until switched on
function fmyUi() {
  const p = typeof forgeProPanels === "function" ? forgeProPanels() : {};
  const out = {};
  // the shelf starts hidden (owner 17:06: "we don't need shelves") - Windows > UI Elements > Shelf brings it back
  for (const k of Object.keys(FMY_UI)) out[k] = FMY_UI_OFF.has(k) ? p[k] === true : p[k] !== false;
  return out;
}
function fmyUiSet(k, on) {
  let p = {};
  try { p = JSON.parse(localStorage.getItem("loki-forge-panels") || "{}") || {}; } catch (_) { p = {}; }
  p[k] = on == null ? !fmyUi()[k] : !!on;
  try { localStorage.setItem("loki-forge-panels", JSON.stringify(p)); } catch (_) { /* private mode */ }
  fmyApply();
  return p[k];
}
function fmyApply() {
  const u = fmyUi();
  const show = (sel, on) => document.querySelectorAll(sel).forEach((e) => { e.hidden = !on; });
  show("#fmy-status", u.statusline); show("#fmy-shelf", u.shelfbar); show("#fmy-toolbox", u.toolbox);
  show("#fmy-helpline", u.helpline); show("#fmy-time", u.timeslider); show("#fmy-hud", u.hud); show("#fmy-cube", u.viewcube); show("#fmy-panelbar", u.panelbar);
  fmySync();
  const v = fmyView(); if (v && v.resize) v.resize();
}
// Ctrl+Space / the UI button / forgePanels.hideAll: pro hides the UI elements too, and brings them back together
(function wrapPanels() {
  const wrap = () => {
    const P = window.forgePanels;
    if (!P || P.fmyWrapped) return !!P;
    const hideAll = P.hideAll, showAll = P.showAll;
    const bars = ["statusline", "shelfbar", "toolbox", "timeslider", "helpline"];
    P.hideAll = () => { const r = hideAll(); const u = fmyUi(); P.fmyWas = Object.fromEntries(bars.map((k) => [k, u[k]])); for (const k of bars) fmyUiSet(k, false); return r; };
    P.showAll = () => {   // back to what was showing before (the shelf only if it was on)
      const r = showAll(), was = P.fmyWas; P.fmyWas = null;
      for (const k of bars) fmyUiSet(k, was ? !!was[k] : !FMY_UI_OFF.has(k));
      return r;
    };
    P.fmyWrapped = true;
    return true;
  };
  if (!wrap()) document.addEventListener("DOMContentLoaded", () => { const t = setInterval(() => { if (wrap()) clearInterval(t); }, 300); });
})();

// ================================================================== the window: menu bar, status line, shelf, tool box, help line
// The window's menu bar is built from the SAME catalogue the hotbox uses (FORGE_PRO_MENUS, forge_pro.js), so the two
// cannot drift apart: the catalogue gives every menu's commands, in its own order, and FMY_ADD holds only what belongs
// to the window - the groups, separators and the few rows that are not commands (UI toggles, the Help text).
const FMY_MAIN_BAR = ["File", "Edit", "Create", "Select", "Modify", "Display", "Windows"];
// the menus the window's bar shows: the main ones, then the showing menu set's menus, then Help - exactly what the
// hotbox's rows show, from one list (FORGE_PRO_SETS)
function fmyBarMenus() {
  const names = (typeof FORGE_PRO_SETS !== "undefined" && typeof forgeMenuSet === "function")
    ? ((FORGE_PRO_SETS[forgeMenuSet()] || FORGE_PRO_SETS.forge).menus || []) : [];
  return FMY_MAIN_BAR.concat(names, ["Help"]);
}
const FMY_ADD = {
  File: [["import", "Import (add a picture or a model)", () => fmyRun("image")]],
  Select: ["-", ["Preferences", ["camSelAuto", "camSelOn", "camSelOff", "backfaces", "preselect"]]],
  // UV and Mesh Display come from the catalogue now; only the window's own extra (a toggle, not a command) stays here
  "Mesh Display": [["wos", "Wireframe on Shaded", () => fmyWireOnShaded(), () => !!(fmyView() && fmyView().wireOnShaded)]],
  // tips are text, not rows that look clickable and do nothing
  Help: ["-", ["Quick Help", [{ note: "Hold Space: the hotbox, at the mouse (Windows > Menus: the wheel)" },
    { note: "Hold the right button: marking menus (Shift / Ctrl for more)" },
    { note: "Option / Alt (or Command) + drag: tumble / track / dolly" },
    { note: "Hold x / c / v while moving: snap to grid / edge / point" },
    { note: "Type a command in the command line (polyCube, move 0 1 0 ...)" }, "-", "hotkeyEditor"]]],
};
const FMY_MENUS = () => {
  const cat = (typeof FORGE_PRO_MENUS !== "undefined") ? FORGE_PRO_MENUS : {};
  const out = [];
  for (const name of fmyBarMenus()) {
    const have = (cat[name] || []).slice();
    const seen = new Set(typeof forgeMenuFlat === "function" ? forgeMenuFlat(have) : have);
    const items = have.slice();
    const add = (name === "Windows") ? [["UI Elements", Object.entries(FMY_UI).map(([k, label]) => ["ui_" + k, label, () => fmyUiSet(k), () => fmyUi()[k]])]]
      : (FMY_ADD[name] || []);
    for (const it of add) {
      const isId = typeof it === "string" && !it.startsWith("-") && !it.startsWith("#");
      const id = Array.isArray(it) ? it[0] : (isId ? it : null);
      if (id && seen.has(id)) continue;                       // the catalogue already lists that command
      const prev = items.length ? items[items.length - 1] : "";
      if (it === "-" && (!items.length || prev === "-" || (typeof prev === "string" && prev.startsWith("#")))) continue;
      if (typeof it === "string" && it.startsWith("#")) { if (typeof prev === "string" && prev.startsWith("#")) items[items.length - 1] = it; else items.push(it); continue; }
      items.push(it);
      if (id) seen.add(id);
    }
    while (items.length && (items[items.length - 1] === "-" || (typeof items[items.length - 1] === "string" && items[items.length - 1].startsWith("#")))) items.pop();
    out.push([name, items]);
  }
  return out;
};

function fmyToolBtn(icon, id, title, run, extra) {
  const b = fmyEl("button", "fmy-ib" + (extra ? " " + extra : ""));
  b.type = "button";
  b.innerHTML = fmySvg(icon);
  b.dataset.proId = id || "";
  const c = fmyCmd(id);
  const off = !run && !(c && c[1]);
  if (off) b.classList.add("off");
  b.title = (title || (c ? c[0] : id)) + (fmyKeyOf(id) ? " (" + fmyKeyOf(id) + ")" : "") + (off && c && c[2] ? " - " + c[2] : "");
  b.setAttribute("aria-label", title || (c ? c[0] : id));
  b.addEventListener("click", (e) => { e.stopPropagation(); if (run) run(); else fmyRun(id); fmySync(); });
  return b;
}

const FMY_SHELVES = {
  "Poly Modeling": [["sphere", "sphere"], ["cube", "cube"], ["cylinder", "cylinder"], ["cone", "cone"], ["torus", "torus"], ["plane", "plane"],
    ["quadsphere", "quadsphere"], "|", ["extrude", "extrude"], ["inset", "inset"], ["bevel", "bevel"], ["edgeLoop", "edgeLoop"],
    ["multiCut", "multiCut"], "|", ["smooth", "smooth"], ["reverse", "reverse"], ["dynamesh", "dynamesh"], "|", ["sculpt", "sculpt"]],
  "Sculpting": [["sculpt", "sculpt", "Sculpt Tool"], "|"].concat([["draw", "Sculpt"], ["inflate", "Inflate"], ["smooth", "Smooth"], ["flatten", "Flatten"],
    ["grab", "Grab"], ["pinch", "Pinch"], ["crease", "Crease"]].map(([b, n]) => ["sculpt", "brush:" + b, n])),
  "Create": [["sphere", "draw", "Draw it"], ["textured", "image", "From an image"], ["light", "describe", "Describe it"], ["toolkit", "creature", "Creature"]],
  "Custom": [],
};
function fmyShelfItems(tab) {
  const items = FMY_SHELVES[tab] || [];
  if (tab === "Custom") {                          // the pro Custom shelf = your recent commands
    const v = fmyView();
    return ((v && v.pro && v.pro.recent) || []).slice(0, 12).map((id) => ["cube", id]);
  }
  return items;
}

function fmyBuildShelf(shelf, tab) {
  shelf.dataset.tab = tab;
  const tabs = shelf.querySelector(".fmy-shelf-tabs"), row = shelf.querySelector(".fmy-shelf-row");
  for (const t of tabs.querySelectorAll(".fmy-stab")) t.classList.toggle("on", t.dataset.tab === tab);
  row.textContent = "";
  for (const it of fmyShelfItems(tab)) {
    if (it === "|") { row.append(fmyEl("span", "fmy-shelf-sep")); continue; }
    const [icon, id, title] = it;
    if (id.startsWith("brush:")) {
      const brush = id.slice(6);
      row.append(fmyToolBtn(icon, "", title + " brush", async () => {
        const v = fmyView(); if (!v) return;
        if (v.mode !== "sculpt") await fmyRun("sculpt");
        if (typeof forgeBrush === "function") forgeBrush(brush);
        if (typeof forgeSay === "function") forgeSay(title + " brush - drag on the model (Ctrl/Cmd inverts, Shift smooths, hold b and drag for the size).");
      }, "fmy-shelf-btn fmy-brush"));
    } else row.append(fmyToolBtn(icon, id, title, null, "fmy-shelf-btn"));
  }
  if (!row.children.length) row.append(fmyEl("span", "fmy-shelf-empty", tab === "Custom" ? "Your recent commands appear here." : ""));
  try { localStorage.setItem("loki-forge-shelf", tab); } catch (_) { /* private mode */ }
}

function forgeProChrome() {
  const panel = document.querySelector("#forge .forge-panel");
  const body = panel && panel.querySelector(".forge-body");
  if (!panel || !body || panel.querySelector("#fmy-menubar")) { fmySync(); return; }
  panel.classList.add("fmy");
  document.getElementById("forge")?.classList.add("fmy-sheet");
  const head = panel.querySelector(".forge-head");
  if (head) { const t = head.querySelector("h2"); if (t) t.textContent = "Forge - untitled"; }

  // ---- the menu bar
  const mb = fmyEl("div", "fmy-menubar"); mb.id = "fmy-menubar"; mb.setAttribute("role", "menubar");
  fmyBuildMenubar(mb);
  mb.append(fmyEl("span", "fmy-grow"), fmyEl("span", "fmy-ws", "Workspace:"), fmyEl("span", "fmy-wsname", "Forge"));

  // ---- the status line: menu set, history, selection mode, snapping, symmetry ... panel toggles
  const st = fmyEl("div", "fmy-status"); st.id = "fmy-status";
  // The menu set: which menus the menu bar and the hotbox's rows show (Maya's own idea, and the same list drives both).
  // Sculpting also switches to the sculpt tools and Modeling comes back out, as before.
  const set = fmyEl("select", "fmy-menuset"); set.id = "fmy-menuset";
  const setNames = (typeof FORGE_PRO_SETS !== "undefined") ? FORGE_PRO_SETS : { forge: { label: "Forge" } };
  for (const k of Object.keys(setNames)) { const o = fmyEl("option", "", setNames[k].label || k); o.value = k; set.append(o); }
  if (typeof forgeMenuSet === "function") set.value = forgeMenuSet();
  set.title = "Menu set: Forge, Modeling, Sculpting, Animation or Rendering - it decides which menus the bar shows.";
  set.addEventListener("change", async () => {
    const v = fmyView(); if (!v) return;
    if (typeof forgeMenuSet === "function") forgeMenuSet(set.value);
    if (set.value === "sculpting" && v.mode !== "sculpt") await fmyRun("sculpt");
    if (set.value === "modeling" && v.mode === "sculpt" && typeof forgeMode === "function") forgeMode();
    fmyBuildMenubar();
    fmySync();
  });
  const sep = () => fmyEl("span", "fmy-vsep");
  st.append(set, sep(), fmyToolBtn("save", "save"), fmyToolBtn("undo", "undo"), fmyToolBtn("redo", "redo"), sep(),
    fmyToolBtn("objmode", "objectMode", "Object mode", () => fmyRun("objectMode"), "fmy-selmode"),
    fmyToolBtn("vertmode", "vertex", null, null, "fmy-selmode"), fmyToolBtn("edgemode", "edge", null, null, "fmy-selmode"),
    fmyToolBtn("facemode", "face", null, null, "fmy-selmode"), sep());
  const snaps = fmyEl("span", "fmy-snaps");
  snaps.append(fmyToolBtn("snapgrid", "snapGrid", "Snap to grid", null, "fmy-snap"), fmyToolBtn("snapedge", "snapEdge", "Snap to curves / edges", null, "fmy-snap"),
    fmyToolBtn("snappoint", "snapPoint", "Snap to points / vertices", null, "fmy-snap"));
  const setSym = (bits) => { const v = fmyView(); if (!v) return; v.brush.symBits = bits | 0; if (bits) v.brush.symLast = v.brush.symBits; v.brush.symmetry = !!v.brush.symBits; v.brush.symModel = !!v.brush.symBits;
    if (typeof forgeSay === "function") forgeSay("Symmetry: " + fmySymText(v.brush.symBits) + "."); };
  const symm = fmyToolBtn("symmetry", "", "Symmetry: mirror strokes and edits across the object's planes (right-click to choose X / Y / Z)", () => {
    const v = fmyView(); if (!v) return;
    setSym(v.brush.symBits ? 0 : (v.brush.symLast || 1));
  }, "fmy-symm");
  symm.id = "fmy-symm";
  symm.addEventListener("contextmenu", (ev) => {
    ev.preventDefault();
    const v = fmyView(), t = v && v.tree && v.tree.api; if (!v || !t || !t.popMenu) return;
    const tick = (b) => ((v.brush.symBits & b) ? "\u2713 " : "\u2003");
    const rad = (n) => { v.brush.radial = n | 0; if (typeof forgeSay === "function") forgeSay("Symmetry: " + fmySymText(v.brush.symBits, n, v.brush.radialAxis) + "."); };
    const axisName = (ax) => { v.brush.radialAxis = ax | 0; if (typeof forgeSay === "function") forgeSay("Symmetry: " + fmySymText(v.brush.symBits, v.brush.radial, ax) + "."); };
    t.popMenu(symm, [
      [tick(1) + "X (mirror across YZ)", () => setSym(v.brush.symBits ^ 1)],
      [tick(2) + "Y (mirror across XZ)", () => setSym(v.brush.symBits ^ 2)],
      [tick(4) + "Z (mirror across XY)", () => setSym(v.brush.symBits ^ 4)],
      ["Symmetry: Off", () => setSym(0)],
      ["Radial 3", () => rad(3)], ["Radial 4", () => rad(4)], ["Radial 6", () => rad(6)], ["Radial 8", () => rad(8)], ["Radial Off", () => rad(0)],
      [(v.brush.radialAxis === 0 ? "\u2713 " : "\u2003") + "Radial axis X", () => axisName(0)],
      [(v.brush.radialAxis === 1 ? "\u2713 " : "\u2003") + "Radial axis Y", () => axisName(1)],
      [(v.brush.radialAxis === 2 ? "\u2713 " : "\u2003") + "Radial axis Z", () => axisName(2)],
    ]);
  });
  const symLabel = fmyEl("span", "fmy-symlabel", "Symmetry: Off"); symLabel.id = "fmy-symlabel";
  st.append(snaps, sep(), symm, symLabel, fmyEl("span", "fmy-grow"));
  const toggles = fmyEl("span", "fmy-paneltoggles");
  for (const [icon, id, title] of [["toolkit", "winToolkit", "Show / hide the Modeling Toolkit"], ["create", "winCreate", "Show / hide the Create panel (draw, picture, describe)"],
    ["materials", "winMaterials", "Show / hide Materials"], ["outliner", "winOutliner", "Show / hide the Outliner"], ["channel", "winChannel", "Show / hide the Channel Box"]]) {
    toggles.append(fmyToolBtn(icon, id, title, null, "fmy-ptoggle"));
  }
  st.append(toggles);

  // ---- the shelf, with the pro tabs
  const shelf = fmyEl("div", "fmy-shelf"); shelf.id = "fmy-shelf";
  const tabs = fmyEl("div", "fmy-shelf-tabs");
  for (const t of Object.keys(FMY_SHELVES)) {
    const b = fmyEl("button", "fmy-stab", t); b.type = "button"; b.dataset.tab = t;
    b.addEventListener("click", () => fmyBuildShelf(shelf, t));
    tabs.append(b);
  }
  shelf.append(tabs, fmyEl("div", "fmy-shelf-row"));
  let tab0 = "Poly Modeling";
  try { tab0 = localStorage.getItem("loki-forge-shelf") || tab0; } catch (_) { /* private mode */ }
  fmyBuildShelf(shelf, FMY_SHELVES[tab0] ? tab0 : "Poly Modeling");

  // ---- the tool box down the left: tools, then the quick layouts
  const tb = fmyEl("div", "fmy-toolbox"); tb.id = "fmy-toolbox";
  tb.append(fmyToolBtn("select", "select", "Select Tool", null, "fmy-tool"),
    // (Lasso and Paint Selection were here as dead "off" buttons - left out until Forge has them: a button that does
    // nothing is a button that lies, owner 2026-10-22)
    fmyToolBtn("move", "move", "Move Tool", null, "fmy-tool"), fmyToolBtn("rotate", "rotate", "Rotate Tool", null, "fmy-tool"),
    fmyToolBtn("scale", "scale", "Scale Tool", null, "fmy-tool"), fmyEl("span", "fmy-hsep"),
    fmyToolBtn("single", "single", "Single Perspective View", null, "fmy-layout"), fmyToolBtn("four", "four", "Four View", null, "fmy-layout"),
    fmyToolBtn("outliner", "winOutliner", "Outliner", null, "fmy-layout"), fmyToolBtn("channel", "winChannel", "Channel Box", null, "fmy-layout"));

  // ---- the help line and the command line along the bottom
  const hl = fmyEl("div", "fmy-helpline"); hl.id = "fmy-helpline";
  const help = fmyEl("span", "fmy-help", ""); help.id = "fmy-help";
  const melLbl = fmyEl("span", "fmy-mel", "Cmd");
  const cmd = fmyEl("input", "fmy-cmd"); cmd.id = "fmy-cmd"; cmd.type = "text"; cmd.spellcheck = false;
  cmd.placeholder = "polyCube; move 0 1 0; select -cl ...";
  cmd.setAttribute("aria-label", "Command line");
  const result = fmyEl("span", "fmy-result", ""); result.id = "fmy-result";
  const hist = []; let hi = 0;
  cmd.addEventListener("keydown", async (e) => {
    e.stopPropagation();                                       // typing is not a hotkey
    if (e.key === "Enter") {
      const line = cmd.value.trim(); if (!line) return;
      hist.push(line); hi = hist.length; cmd.value = "";
      result.textContent = await forgeProCommandLine(line);
    } else if (e.key === "ArrowUp") { e.preventDefault(); if (hi > 0) cmd.value = hist[--hi]; }
    else if (e.key === "ArrowDown") { e.preventDefault(); hi = Math.min(hist.length, hi + 1); cmd.value = hist[hi] || ""; }
    else if (e.key === "Escape") cmd.blur();
  });
  hl.append(help, melLbl, cmd, result);

  // ---- the time slider and the range slider (pro: frames 1-120 at 24 fps); it plays and scrubs a model's own clips
  const ts = fmyEl("div", "fmy-time"); ts.id = "fmy-time";
  const ruler = fmyEl("div", "fmy-ruler"); ruler.id = "fmy-ruler";
  const ticks = fmyEl("div", "fmy-ticks");
  const cursor = fmyEl("div", "fmy-tcursor"); cursor.id = "fmy-tcursor";
  ruler.append(ticks, cursor);
  const frameIn = fmyEl("input", "fmy-tfield"); frameIn.id = "fmy-frame"; frameIn.type = "number"; frameIn.value = "1";
  const play = fmyEl("div", "fmy-playback");
  const PB = [["start", "\u23EE", "Go to start"], ["back", "\u23F4\u2009|", "Step back one frame"], ["play", "\u25B6", "Play / stop the model's animation"],
    ["fwd", "|\u2009\u23F5", "Step forward one frame"], ["end", "\u23ED", "Go to end"]];
  for (const [k, sym, tip] of PB) {
    const b = fmyEl("button", "fmy-pbtn", sym); b.type = "button"; b.dataset.pb = k; b.title = tip;
    b.addEventListener("click", () => fmyPlayback(k));
    play.append(b);
  }
  const range = fmyEl("div", "fmy-range");
  const rs = fmyEl("input", "fmy-tfield"); rs.id = "fmy-rstart"; rs.type = "number"; rs.value = "1";
  const bar = fmyEl("div", "fmy-rbar"); bar.append(fmyEl("span", "fmy-rknob", "1"), fmyEl("span", "fmy-rknob", "120"));
  const re = fmyEl("input", "fmy-tfield"); re.id = "fmy-rend"; re.type = "number"; re.value = "120";
  const clipSel = fmyEl("select", "fmy-menuset fmy-clip"); clipSel.id = "fmy-clip"; clipSel.title = "The model's animation (a creature's Walk / Idle)";
  clipSel.addEventListener("change", () => { const v = fmyView(); if (v && v.playAnim) { v.playAnim(clipSel.value || null); if (typeof forgeAnimBar === "function") forgeAnimBar(); } fmyTimeSync(); });
  const fps = fmyEl("span", "fmy-fps", "24 fps");
  range.append(rs, bar, re, clipSel, fps);
  for (const f of [frameIn, rs, re]) f.addEventListener("keydown", (e) => e.stopPropagation());
  frameIn.addEventListener("change", () => fmySeekFrame(+frameIn.value));
  rs.addEventListener("change", fmyTimeSync); re.addEventListener("change", fmyTimeSync);
  const scrub = (e) => {
    const r = ruler.getBoundingClientRect(), a = +rs.value || 1, b = +re.value || 120;
    fmySeekFrame(Math.round(a + Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * (b - a)));
  };
  ruler.addEventListener("pointerdown", (e) => { ruler.setPointerCapture(e.pointerId); scrub(e); ruler.addEventListener("pointermove", scrub); });
  ruler.addEventListener("pointerup", () => ruler.removeEventListener("pointermove", scrub));
  const top = fmyEl("div", "fmy-trow"); top.append(ruler, frameIn, play);
  ts.append(top, range);
  // the help line repeats Forge's status (the pro help line)
  const status = document.getElementById("forge-status");
  if (status) new MutationObserver(() => { help.textContent = status.textContent || fmyToolHint(); help.classList.toggle("bad", status.classList.contains("bad")); })
    .observe(status, { childList: true, characterData: true, subtree: true, attributes: true });
  help.textContent = fmyToolHint();

  panel.insertBefore(mb, body);
  panel.insertBefore(st, body);
  panel.insertBefore(shelf, body);
  body.insertBefore(tb, body.firstChild);
  body.after(ts);
  ts.after(hl);
  // the snap chips stay where they were (they are the viewport's own, and tests and scripts click them)
  fmyApply();
  if (!fmySync.timer) fmySync.timer = setInterval(() => { const s = document.getElementById("forge"); if (s && !s.hidden && !document.hidden) fmySync(); }, 750);
}

// keep the status line, tool box and toggles showing the real state
function fmySync() {
  const v = fmyView();
  const set = (sel, on) => document.querySelectorAll(sel).forEach((b) => b.classList.toggle("on", !!on));
  if (v) {
    const comp = v.mode === "poly", mode = v.edit ? v.edit.mode : "";
    set('#fmy-status .fmy-selmode[data-pro-id="objectMode"]', !comp);
    set('#fmy-status .fmy-selmode[data-pro-id="vertex"]', comp && mode === "vert");
    set('#fmy-status .fmy-selmode[data-pro-id="edge"]', comp && mode === "edge");
    set('#fmy-status .fmy-selmode[data-pro-id="face"]', comp && mode === "face");
    for (const k of ["snapGrid", "snapEdge", "snapPoint"]) set('#fmy-status [data-pro-id="' + k + '"]', fmyOn(k));
    const tc = comp ? v.gizmo : v.transform;
    const tool = tc && tc.object ? tc.mode : null;
    set('#fmy-toolbox [data-pro-id="select"]', !tool);
    set('#fmy-toolbox [data-pro-id="move"]', tool === "translate");
    set('#fmy-toolbox [data-pro-id="rotate"]', tool === "rotate");
    set('#fmy-toolbox [data-pro-id="scale"]', tool === "scale");
    set('#fmy-toolbox [data-pro-id="single"]', !v.quad);
    set('#fmy-toolbox [data-pro-id="four"]', !!v.quad);
    const sym = document.getElementById("fmy-symlabel");
    if (sym) sym.textContent = "Symmetry: " + fmySymText(v.brush && v.brush.symBits, v.brush && v.brush.radial, v.brush && v.brush.radialAxis);
    set("#fmy-symm", !!(v.brush && (v.brush.symBits || (v.brush.radial | 0) > 1)));
    const ms = document.getElementById("fmy-menuset");
    if (ms && document.activeElement !== ms) {
      // the menu set's values are keys ("sculpting", "modeling" ...): sculpt mode shows the Sculpting set, otherwise
      // the set the owner picked stays (writing a label here left the box blank)
      if (v.mode === "sculpt" && typeof forgeMenuSet === "function" && forgeMenuSet() !== "sculpting") forgeMenuSet("sculpting");
      else if (typeof forgeMenuSet === "function" && ms.value !== forgeMenuSet()) ms.value = forgeMenuSet();
    }
    const camName = document.getElementById("fmy-camname");
    if (camName) camName.textContent = v.quad ? "" : (v.cam || "persp");
    set("#fmy-panelbar [data-pro-id='wire']", !!v.wire);
    set("#fmy-panelbar [data-pro-id='shaded']", !v.wire);
    set("#fmy-panelbar [data-pro-id='textured']", !v.clay);
    set("#fmy-panelbar [data-pro-id='xray']", v.edit && v.edit.xray);
    set("#fmy-panelbar [data-pro-id='grid']", v.pro && v.pro.grid && v.pro.grid.visible);
    set("#fmy-panelbar [data-pro-id='wos']", !!v.wireOnShaded);
  }
  for (const [id, k] of [["winOutliner", "outliner"], ["winChannel", "channel"], ["winToolkit", "toolkit"], ["winCreate", "create"], ["winMaterials", "materials"]]) {
    const on = typeof forgeProPanels === "function" ? !!forgeProPanels()[k] : false;
    set('#fmy-status [data-pro-id="' + id + '"], #fmy-toolbox [data-pro-id="' + id + '"]', on);
  }
  if (v) fmyHudUpdate(v);
  const help = document.getElementById("fmy-help"), status = document.getElementById("forge-status");
  if (help && status && !status.textContent) help.textContent = fmyToolHint();
  fmyTimeSync();
}

// the pro help line names the tool and says what it does when nothing else is being said
function fmyToolHint() {
  const v = fmyView();
  if (!v) return "Select Tool: select an object";
  if (v.mode === "sculpt") return "Sculpt Tool: drag on the surface - Ctrl/Cmd inverts, Shift smooths, hold b and drag to resize";
  const tc = v.mode === "poly" ? v.gizmo : v.transform, tool = tc && tc.object ? tc.mode : null;
  const what = v.mode === "poly" ? ({ vert: "vertices", edge: "edges", face: "faces" }[v.edit && v.edit.mode] || "components") : "object(s)";
  if (tool === "translate") return "Move Tool: use manipulator to move " + what + ". Shift+drag duplicates, hold x / c / v to snap.";
  if (tool === "rotate") return "Rotate Tool: use manipulator to rotate " + what + ".";
  if (tool === "scale") return "Scale Tool: use manipulator to scale " + what + ".";
  return "Select Tool: select " + (v.mode === "poly" ? what : "an object");
}

// ---- the time slider
const FMY_FPS = 24;
function fmyTimeSync() {
  const ts = document.getElementById("fmy-time");
  if (!ts || ts.hidden) return;
  const v = fmyView();
  const a = +document.getElementById("fmy-rstart").value || 1, b = Math.max(a + 1, +document.getElementById("fmy-rend").value || 120);
  const ticks = ts.querySelector(".fmy-ticks");
  if (ticks.dataset.range !== a + ":" + b) {                      // pro numbers every 5th frame
    ticks.dataset.range = a + ":" + b; ticks.textContent = "";
    const step = b - a > 200 ? 20 : b - a > 80 ? 5 : 1;
    for (let f = a; f <= b; f++) {
      if (f % step && f !== a) continue;                         // on the multiples (5, 10, 15 ...), like the pro tools
      const t = fmyEl("span", "fmy-tick" + ((f % 5 === 0 || f === a) ? " lab" : ""), (f % 5 === 0 || f === a) ? String(f) : "");
      t.style.left = ((f - a) / (b - a) * 100) + "%";
      ticks.append(t);
    }
    const knobs = ts.querySelectorAll(".fmy-rknob"); if (knobs.length === 2) { knobs[0].textContent = String(a); knobs[1].textContent = String(b); }
  }
  const clipSel = document.getElementById("fmy-clip");
  const names = (v && v.anims) || [];
  if (clipSel.dataset.names !== names.join("|")) {
    clipSel.dataset.names = names.join("|"); clipSel.textContent = "";
    const none = fmyEl("option", "", names.length ? "No Animation" : "No Anim Layer"); none.value = ""; clipSel.append(none);
    for (const n of names) { const o = fmyEl("option", "", n); o.value = n; clipSel.append(o); }
  }
  const info = v && v.animInfo ? v.animInfo() : null;
  if (document.activeElement !== clipSel) clipSel.value = info ? info.name : "";
  const frame = info ? Math.min(b, a + Math.floor(info.t * FMY_FPS) % (b - a + 1)) : (+document.getElementById("fmy-frame").value || a);
  const cur = document.getElementById("fmy-tcursor");
  if (cur) cur.style.left = ((Math.max(a, Math.min(b, frame)) - a) / (b - a) * 100) + "%";
  const fi = document.getElementById("fmy-frame");
  if (fi && document.activeElement !== fi) fi.value = String(frame);
  const pb = ts.querySelector('[data-pb="play"]');
  if (pb) { pb.textContent = info && !info.paused ? "\u25A0" : "\u25B6"; pb.classList.toggle("on", !!(info && !info.paused)); }
}
function fmySeekFrame(f) {
  const v = fmyView();
  const a = +document.getElementById("fmy-rstart").value || 1, b = +document.getElementById("fmy-rend").value || 120;
  f = Math.max(a, Math.min(b, Math.round(f || a)));
  document.getElementById("fmy-frame").value = String(f);
  if (v && v.animInfo && v.animInfo()) { v.animPause(true); v.animSeek((f - a) / FMY_FPS); }
  fmyTimeSync();
}
function fmyPlayback(k) {
  const v = fmyView();
  const a = +document.getElementById("fmy-rstart").value || 1, b = +document.getElementById("fmy-rend").value || 120;
  const f = +document.getElementById("fmy-frame").value || a;
  if (k === "start") return fmySeekFrame(a);
  if (k === "end") return fmySeekFrame(b);
  if (k === "back") return fmySeekFrame(f - 1);
  if (k === "fwd") return fmySeekFrame(f + 1);
  if (k === "play") {
    if (!v) return;
    if (!(v.animInfo && v.animInfo())) {
      const first = (v.anims || [])[0];
      if (!first) { if (typeof forgeSay === "function") forgeSay("Nothing is animated - a creature has Walk and Idle clips to play.", true); return; }
      v.playAnim(first);
      if (typeof forgeAnimBar === "function") forgeAnimBar();
    } else v.animPause();
    fmyTimeSync();
  }
}

// ================================================================== the command line (a small command language)
async function forgeProCommandLine(line) {
  const v = fmyView();
  const t = v && v.tree && v.tree.api;
  const out = [];
  for (const raw of line.split(";")) {
    const s = raw.trim(); if (!s) continue;
    const [w, ...args] = s.split(/\s+/);
    const nums = args.filter((a) => /^-?\d*\.?\d+$/.test(a)).map(Number);
    const flags = args.filter((a) => a.startsWith("-"));
    const names = args.filter((a) => !a.startsWith("-") && !/^-?\d*\.?\d+$/.test(a));
    const prim = { polyCube: "cube", polySphere: "sphere", polyCylinder: "cylinder", polyCone: "cone", polyTorus: "torus", polyPlane: "plane" }[w];
    try {
      if (prim) { await fmyRun(prim); out.push(t ? t.root().name : prim); continue; }
      if (!v || !t) { out.push("// Error: make or add something first"); continue; }
      if (w === "select") {
        if (flags.includes("-cl") || flags.includes("-clear")) t.selectNone();
        else if (flags.includes("-all")) t.selectAll();
        else {
          const ids = names.map((n) => t.list().find((x) => x.name === n)).filter(Boolean).map((x) => x.id);
          t.selectMany(ids, flags.includes("-add") || flags.includes("-tgl") ? "add" : flags.includes("-d") ? "remove" : "set");
        }
        out.push(t.selected().map((id) => t.node(id).name).join(" ") || "nothing selected");
      } else if (w === "move" || w === "rotate" || w === "scale") {
        const part = { move: "translate", rotate: "rotate", scale: "scale" }[w];
        for (const id of t.selected()) {
          const cur = t.transform(id)[part];
          nums.slice(0, 3).forEach((n, a) => t.setTransform(id, part, a, flags.includes("-r") ? cur[a] + n : n));
        }
        v.tree.build(); out.push(w + " " + nums.join(" "));
      } else if (w === "setAttr" && names[0] && nums.length) {
        const [obj, attr] = names[0].split(".");
        const n = t.list().find((x) => x.name === obj);
        const m = /^(translate|rotate|scale)([XYZ])$/.exec(attr || "");
        if (n && m) { t.setTransform(n.id, m[1], "XYZ".indexOf(m[2]), nums[0]); v.tree.build(); out.push(names[0] + " = " + nums[0]); }
        else if (n && attr === "visibility") { t.setVisible(n.id, !!nums[0]); out.push(names[0] + " = " + nums[0]); }
        else out.push("// Error: no attribute " + names[0]);
      } else if (w === "rename" && names.length >= 1) {
        const target = names.length > 1 ? t.list().find((x) => x.name === names[0]) : t.active();
        if (target) { t.rename(target.id, names[names.length - 1]); out.push(t.node(target.id).name); }
      } else {
        const alias = { delete: "delete", duplicate: "duplicate", group: "group", ungroup: "ungroup", parent: "parent", undo: "undo", redo: "redo",
          makeIdentity: "freeze", FreezeTransformations: "freeze", CenterPivot: "centerPivot", ResetTransformations: "resetXf", hide: "hide",
          showHidden: "showAll", viewFit: "frameAll", fitPanel: "frameAll", polyExtrudeFacet: "extrude", polySmooth: "smooth", polyNormal: "reverse",
          polySplitRing: "edgeLoop", polyBevel: "bevel", polyBevel3: "bevel", isolateSelect: "isolate",
          polyUnite: "combine", polySeparate: "separate", polyMirrorFace: "mirror", polyMirror: "mirror",
          polyMergeVertex: "merge", polyMergeVert: "merge", polyCloseBorder: "fillHole" }[w];
        let id = alias || w;
        if (w === "xform" && flags.includes("-cp")) id = "centerPivot";
        if (w === "parent" && flags.includes("-w")) id = "unparent";
        if (id === "mirror") { const ax = nums.length ? nums[0] : 0; id = ["mirror", "mirrorY", "mirrorZ"][ax] || "mirror"; }   // -axis 0 / 1 / 2
        if (!fmyCmd(id)) {
          const byLabel = typeof FORGE_PRO_CMDS !== "undefined" ? Object.entries(FORGE_PRO_CMDS).find(([, c]) => c[0].toLowerCase() === s.toLowerCase()) : null;
          if (byLabel) id = byLabel[0];
        }
        if (!fmyCmd(id)) { out.push("// Error: Cannot find procedure \"" + w + "\""); continue; }
        await fmyRun(id);
        out.push(fmyCmd(id)[0]);
      }
    } catch (exc) { out.push("// Error: " + exc.message); }
  }
  fmySync();
  return out.length ? "// Result: " + out.join("; ") : "";
}

// ================================================================== the viewport: panel menus, HUD, view cube, grid, lighting
function forgeProViewportAttach(view, ctx) {
  if (Array.isArray(view.frameHooks)) view.frameHooks.push(() => { if (view.smoothLevel > 1 || view.smoothPrev) fmySmoothRefresh(view, false); });
  if (Array.isArray(view.frameHooks)) view.frameHooks.push(() => { if (view.wireOnly || view._wireWas) { fmyWireSync(view, false); view._wireWas = !!view.wireOnly; } });
  const { THREE, scene, camera, controls, canvas, lights } = ctx;
  const stage = canvas && canvas.parentElement;
  if (!stage || stage.querySelector("#fmy-panelbar")) return;
  stage.classList.add("fmy-stage");
  view.proShade = true;                                      // matte grey lambert1, like the pro tools (forge.js applyLook)
  view.cam = view.cam || "persp";

  // ---- the pro default lighting: one light from the camera, a little ambient, no rim; the old presets stay on 7
  const defaultLight = () => {
    if (!lights) return;
    lights.hemi.color.setHex(0xffffff); lights.hemi.groundColor.setHex(0x9a9a9a); lights.hemi.intensity = 0.55;
    lights.key.color.setHex(0xffffff); lights.key.intensity = 1.55; lights.key.position.set(0.25, 0.3, 1);
    if (lights.rim) lights.rim.intensity = 0;
    view.light = -1; view.dirty = true;
  };
  defaultLight();
  const nextLight = view.nextLight;
  view.nextLight = () => { const n = nextLight(); if (lights && lights.rim && lights.rim.intensity === 0) lights.rim.intensity = 1.2; return n; };
  view.defaultLighting = () => { defaultLight(); return "Default Lighting"; };
  if (view.applyLook) view.applyLook();

  // ---- the pro grid: dark lines over the gradient, a darker line on each axis through the origin
  const g = view.pro && view.pro.grid;
  if (g) {
    const [fine, major] = g.children;
    for (const [h, op] of [[fine, 0.2], [major, 0.42]]) {
      if (!h) continue;
      const mats = Array.isArray(h.material) ? h.material : [h.material];
      for (const m of mats) { m.color && m.color.setHex(0x000000); m.vertexColors = false; m.opacity = op; m.transparent = true; m.needsUpdate = true; }
    }
    const axisGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-6, 0, 0), new THREE.Vector3(6, 0, 0), new THREE.Vector3(0, 0, -6), new THREE.Vector3(0, 0, 6)]);
    const axes = new THREE.LineSegments(axisGeo, new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.8, depthWrite: false }));
    axes.name = "forge-grid-axes"; axes.raycast = () => {};
    g.add(axes);
  }

  // ---- the panel's own menu bar and icon bar
  const pb = fmyEl("div", "fmy-panelbar"); pb.id = "fmy-panelbar";
  const pm = fmyEl("div", "fmy-panelmenus");
  const look = (cam) => () => fmyRun(cam);
  pm.append(
    fmyMenuButton("View", () => [["camSel", "Select Camera", () => { if (typeof forgeSay === "function") forgeSay("Camera: " + (view.cam || "persp") + "."); }], "-",
      "frameAll", "frameSel", "defaultView", "-", ["prevView", "Previous View", () => view.viewUndo && view.viewUndo()], ["nextView", "Next View", () => view.viewRedo && view.viewRedo()], "-",
      "#Look Through", ["persp", "persp", look("persp"), () => view.cam === "persp"], ["top", "top", look("top"), () => view.cam === "top"],
      ["front", "front", look("front"), () => view.cam === "front"], ["side", "side", look("side"), () => view.cam === "side"]], "fmy-pmb"),
    fmyMenuButton("Shading", () => ["wire", "shaded", "textured", "-", ["wos", "Wireframe on Shaded", () => fmyWireOnShaded(), () => !!view.wireOnShaded], "xray",
      ["proShade", "Default Material (lambert1)", () => { view.proShade = !view.proShade; if (view.applyLook) view.applyLook(); }, () => !!view.proShade]], "fmy-pmb"),
    fmyMenuButton("Lighting", () => [["defLight", "Use Default Lighting", () => view.defaultLighting(), () => view.light === -1], "lights"], "fmy-pmb"),
    fmyMenuButton("Show", () => [["grid", "Grid", () => fmyRun("grid"), () => !!(view.pro && view.pro.grid && view.pro.grid.visible)],
      ["hudT", "Heads Up Display", () => fmyUiSet("hud"), () => fmyUi().hud], ["cubeT", "View Cube", () => fmyUiSet("viewcube"), () => fmyUi().viewcube],
      ["snapsT", "Snap chips", () => { const s = document.getElementById("forge-snaps"); if (s) s.hidden = !s.hidden; }, () => { const s = document.getElementById("forge-snaps"); return !!(s && !s.hidden); }]], "fmy-pmb"),
    fmyMenuButton("Renderer", () => [["vp2", "Viewport 2.0 (WebGL)", () => { if (typeof forgeSay === "function") forgeSay("Viewport 2.0 is the live viewport (WebGL); Path Traced Preview refines it while the view is still."); }, () => true],
      // the path tracer (app/ui/forge_render.js): the viewport refining itself, and the Render window
      ...(window.ForgeRender ? ["-", ["renderPreview", "Path Traced Preview", () => window.ForgeRender.togglePreview(), () => window.ForgeRender.previewOn()],
        ["renderDialog", "Render...", () => window.ForgeRender.openDialog(true)]] : []),
      // Render Studio (app/ui/render_studio.js): this camera and the Time Slider's range, in the Render tab
      ...(window.LokiRenderStudio && window.LokiModeBar ? ["-", ["renderStudio", "Send to Render Studio", () => window.LokiModeBar.go("render", { fromForge: true })]] : [])], "fmy-pmb"),
    fmyMenuButton("Panels", () => ["#Perspective", ["persp", "persp", look("persp"), () => view.cam === "persp"], "#Orthographic",
      ["top", "top", look("top"), () => view.cam === "top"], ["front", "front", look("front"), () => view.cam === "front"], ["side", "side", look("side"), () => view.cam === "side"],
      "-", "#Layouts", "single", "four", "-", "winOutliner", "winChannel"], "fmy-pmb"));
  const icons = fmyEl("div", "fmy-panelicons");
  icons.append(
    fmyToolBtn("camera", "", "Select the camera", () => { if (typeof forgeSay === "function") forgeSay("Camera: " + (view.cam || "persp") + "."); }, "fmy-pib"),
    fmyToolBtn("frameall", "frameAll", null, null, "fmy-pib"), fmyToolBtn("framesel", "frameSel", null, null, "fmy-pib"), fmyEl("span", "fmy-vsep"),
    fmyToolBtn("grid", "grid", "Grid", null, "fmy-pib"), fmyEl("span", "fmy-vsep"),
    fmyToolBtn("wire", "wire", "Wireframe", null, "fmy-pib"), fmyToolBtn("shaded", "shaded", "Smooth Shade All", null, "fmy-pib"),
    fmyToolBtn("wire", "wos", "Wireframe on Shaded", () => fmyWireOnShaded(), "fmy-pib fmy-wos"),
    fmyToolBtn("textured", "textured", "Textured", null, "fmy-pib"), fmyToolBtn("xray", "xray", "X-Ray", null, "fmy-pib"), fmyEl("span", "fmy-vsep"),
    fmyToolBtn("light", "", "Use Default Lighting", () => view.defaultLighting(), "fmy-pib"), fmyToolBtn("isolate", "isolate", "Isolate Select", null, "fmy-pib"),
    fmyToolBtn("hud", "", "Heads Up Display", () => fmyUiSet("hud"), "fmy-pib"));
  // a narrow viewport (a split, a vertical monitor, the UV workspace): the panel menus fold into one "Menus" button whose
  // menus open as submenus, instead of being cut off at the edge (owner 2026-10-22: menus that look weird / can't be
  // clicked). The icon row scrolls sideways with the wheel instead of hiding what does not fit.
  const fold = fmyMenuButton("Menus", () => [...pm.querySelectorAll(".fmy-pmb:not(.fmy-pfold)")].map((b) => [b.dataset.menu, typeof b._items === "function" ? b._items() : b._items]), "fmy-pmb fmy-pfold");
  fold.hidden = true;
  pm.append(fold);
  const refold = () => {
    const menus = [...pm.querySelectorAll(".fmy-pmb:not(.fmy-pfold)")];
    for (const b of menus) b.hidden = false;
    fold.hidden = true;
    if (pm.scrollWidth > pm.clientWidth + 1) { for (const b of menus) b.hidden = true; fold.hidden = false; }
  };
  if (typeof ResizeObserver === "function") new ResizeObserver(refold).observe(pm);
  icons.addEventListener("wheel", (e) => { if (icons.scrollWidth > icons.clientWidth && Math.abs(e.deltaY) > Math.abs(e.deltaX)) { icons.scrollLeft += e.deltaY; e.preventDefault(); } }, { passive: false });
  pb.append(pm, icons);
  stage.append(pb);

  // ---- heads-up display: the poly count, the camera's name, the axis triad
  const hud = fmyEl("div", "fmy-hud"); hud.id = "fmy-hud";
  const table = fmyEl("table", "fmy-polycount"); table.id = "fmy-polycount";
  for (const k of ["Verts", "Edges", "Faces", "Tris", "UVs"]) {
    const tr = fmyEl("tr");
    tr.append(fmyEl("th", "", k + ":"), fmyEl("td", "", "0"), fmyEl("td", "", "0"), fmyEl("td", "", "0"));
    tr.dataset.k = k.toLowerCase();
    table.append(tr);
  }
  const camName = fmyEl("div", "fmy-camname", "persp"); camName.id = "fmy-camname";
  const triad = fmyEl("div", "fmy-triad"); triad.id = "fmy-triad";
  triad.innerHTML = '<svg viewBox="-20 -20 40 40" width="40" height="40"><line id="fmy-tx" x1="0" y1="0" x2="10" y2="0" stroke="#e8423b" stroke-width="1.6"/><line id="fmy-ty" x1="0" y1="0" x2="0" y2="-10" stroke="#61e84a" stroke-width="1.6"/><line id="fmy-tz" x1="0" y1="0" x2="0" y2="10" stroke="#3b6ff0" stroke-width="1.6"/><text id="fmy-tlx" font-size="6" fill="#e8423b">x</text><text id="fmy-tly" font-size="6" fill="#61e84a">y</text><text id="fmy-tlz" font-size="6" fill="#3b6ff0">z</text></svg>';
  hud.append(table, camName, triad);
  stage.append(hud);

  // ---- the view cube: turns with the camera; a face click looks from that side, the house goes home
  const cubeWrap = fmyEl("div", "fmy-cube"); cubeWrap.id = "fmy-cube";
  const cube = fmyEl("div", "fmy-cube-inner");
  const FACES = [["front", "FRONT", [0, 0, 1]], ["back", "BACK", [0, 0, -1]], ["right", "RIGHT", [1, 0, 0]], ["left", "LEFT", [-1, 0, 0]],
    ["top", "TOP", [0, 1, 0.0001]], ["bottom", "BOTTOM", [0, -1, 0.0001]]];
  for (const [cls, label, dir] of FACES) {
    const f = fmyEl("button", "fmy-cf fmy-cf-" + cls, label);
    f.type = "button"; f.title = "Look from the " + label.toLowerCase();
    f.addEventListener("click", (e) => { e.stopPropagation(); fmyLookFrom(view, THREE, camera, controls, cls, dir); });
    cube.append(f);
  }
  const home = fmyEl("button", "fmy-cube-home"); home.type = "button"; home.innerHTML = fmySvg("home"); home.title = "Home view (Alt+Home)";
  home.addEventListener("click", (e) => { e.stopPropagation(); fmyRun("defaultView"); });
  cubeWrap.append(cube, home);
  stage.append(cubeWrap);

  // follow the camera: the cube and the triad turn with it, the HUD counts what is in the scene
  let lastQ = "";
  const tick = () => {
    if (!document.body.contains(stage)) return;
    const sheet = document.getElementById("forge");
    if (sheet && !sheet.hidden) {
      const q = camera.quaternion;
      const key = q.x.toFixed(4) + q.y.toFixed(4) + q.z.toFixed(4) + q.w.toFixed(4);
      if (key !== lastQ) {
        lastQ = key;
        const m = new THREE.Matrix4().makeRotationFromQuaternion(q.clone().invert());
        const e = m.elements;
        // CSS: the cube's world axes seen from the camera (y flipped for the screen)
        cube.style.transform = "matrix3d(" + [e[0], -e[1], e[2], 0, -e[4], e[5], -e[6], 0, e[8], -e[9], e[10], 0, 0, 0, 0, 1].join(",") + ")";
        for (const [axis, v3] of [["x", new THREE.Vector3(1, 0, 0)], ["y", new THREE.Vector3(0, 1, 0)], ["z", new THREE.Vector3(0, 0, 1)]]) {
          const p = v3.applyQuaternion(q.clone().invert());
          const ln = triad.querySelector("#fmy-t" + axis), tx = triad.querySelector("#fmy-tl" + axis);
          if (ln) { ln.setAttribute("x2", (p.x * 12).toFixed(2)); ln.setAttribute("y2", (-p.y * 12).toFixed(2)); }
          if (tx) { tx.setAttribute("x", (p.x * 15 - 1.5).toFixed(2)); tx.setAttribute("y", (-p.y * 15 + 2).toFixed(2)); }
        }
      }
    }
    const ai = view.animInfo ? view.animInfo() : null;          // the time slider's cursor runs with a playing clip
    if (ai && !ai.paused && performance.now() - (tick.last || 0) > 80) { tick.last = performance.now(); fmyTimeSync(); }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  if (controls) controls.addEventListener("change", () => { lastQ = ""; });
  fmyApply();
}

// look at the scene from one of the view cube's sides (top / front / side are the pro orthographic cameras)
function fmyLookFrom(view, THREE, camera, controls, side, dir) {
  const ortho = { top: "top", front: "front", right: "side" }[side];
  if (ortho) { fmyRun(ortho); return; }
  if (view.cam !== "persp") fmyRun("persp");
  if (view.rememberView) view.rememberView();
  const t = controls.target.clone(), d = camera.position.distanceTo(t) || 3;
  camera.position.copy(t).addScaledVector(new THREE.Vector3(dir[0], dir[1], dir[2]).normalize(), d);
  camera.lookAt(t); controls.update(); view.dirty = true;
}

// Display smoothness - the keys 1 / 2 / 3: 1 the cage as it is, 2 the smoothed surface with the cage drawn over it,
// 3 only the smoothed surface. A display only: the cage is still what the tools edit. Two rounds of Catmull-Clark
// (one when the cage is big); off while sculpting.
const FMY_SMOOTH_LIMIT = 60000;
const FMY_SMOOTH_NATIVE_MIN = 400;   // cages with this many faces or more are smoothed by the C++ engine (forge_geom.js)
function fmySmoothPreview(level) {
  const v = fmyView();
  if (!v) return "";
  v.smoothLevel = Math.max(1, Math.min(3, level | 0));
  fmySmoothRefresh(v, true);
  if (v.smoothLevel > 1 && !v.poly) return "Smooth preview works on a modelled mesh (Create a primitive, or DynaMesh a sculpt).";
  return ["", "Display: the cage (1).", "Display: smooth, with the cage (2).", "Display: smooth (3)."][v.smoothLevel];
}
function fmySmoothRefresh(v, force) {
  const THREE = v.THREE, P = window.ForgePoly, base = v.meshObj && v.meshObj();
  if (!THREE || !P || !v.holder) return;
  const st = v.smoothPrev || (v.smoothPrev = { mesh: null, cage: null, of: null, ver: -1 });
  const want = (v.smoothLevel || 1) >= 2 && !!v.poly && v.mode !== "sculpt";
  const drop = () => {
    for (const k of ["mesh", "cage"]) if (st[k]) { if (st[k].parent) st[k].parent.remove(st[k]); st[k].geometry.dispose(); st[k] = null; }
    st.of = null;
  };
  if (!want) {
    if (st.mesh || st.cage) drop();
    if (base && !base.visible) { base.visible = true; v.dirty = true; }
    return;
  }
  // what the preview was built from: the cage on screen (the live drag's copy while dragging), a change counter that
  // every new cage and live drag moves, and the shown geometry - a cage edited in place, or a new geometry whose
  // version counter starts again at 0, used to leave the old smooth mesh and wire on screen ("weird wires linger")
  const src = v.polyWork || v.poly;
  const gpos = base && base.geometry && base.geometry.attributes.position;
  const ver = (v.polyEpoch || 0) + ":" + (base && base.geometry ? base.geometry.uuid : "") + ":" + (gpos ? gpos.version : 0);
  // the smoothed mesh + the cage lines, from triangles (the JS's or the C++ engine's - the same result)
  const build = (t, poly, at) => {
    drop();
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(t.pos, 3)); g.setIndex(new THREE.BufferAttribute(t.idx, 1));
    g.computeVertexNormals();
    const mat = (base && base.material ? base.material : new THREE.MeshStandardMaterial()).clone();
    mat.vertexColors = false; if (base && base.material && base.material.color) mat.color.copy(base.material.color);
    st.mesh = new THREE.Mesh(g, mat); st.mesh.name = "forge-smooth"; st.mesh.raycast = () => {};
    const E = P.edges(poly), lp = new Float32Array(E.length * 6);
    E.forEach((e, i) => { lp.set(poly.v[e.a], i * 6); lp.set(poly.v[e.b], i * 6 + 3); });
    const lg = new THREE.BufferGeometry(); lg.setAttribute("position", new THREE.BufferAttribute(lp, 3));
    st.cage = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: 0xc9d3de, transparent: true, opacity: 0.55 }));
    st.cage.name = "forge-cage"; st.cage.raycast = () => {};
    v.holder.add(st.mesh, st.cage);
    st.of = poly; st.ver = at;
  };
  if (force || st.of !== src || st.ver !== ver) {
    // a big cage goes to the C++ engine, off the window's thread (6x faster, and the viewport never stalls):
    // the last preview stays on screen until the new one is back; one request at a time, the latest wins
    const G = window.ForgeGeom;
    if (G && G.usable() && v.poly.f.length >= FMY_SMOOTH_NATIVE_MIN) {
      if (st.pending) { st.again = true; }
      else {
        const poly = src, at = ver;
        st.pending = G.smooth(poly, 2, FMY_SMOOTH_LIMIT).then((t) => {
          st.pending = null;
          const again = st.again; st.again = false;
          if (v.smoothPrev !== st || !((v.smoothLevel || 1) >= 2 && v.poly && v.mode !== "sculpt")) return;
          const now = v.polyWork || v.poly;
          if (t && now === poly) { build(t, poly, at); fmySmoothShow(v, st, base); }
          if (!t || again || now !== poly) fmySmoothRefresh(v, !t);    // the cage moved on meanwhile: once more
        });
        st.native = true;
      }
      if (!st.mesh) { if (base && !base.visible) { base.visible = true; v.dirty = true; } return; }   // the first one is on its way
    } else {
      let m = src;
      for (let k = 0; k < 2 && m.f.length * 4 <= FMY_SMOOTH_LIMIT; k++) m = P.smooth(m);
      build(P.triangulate(m), src, ver);
      st.native = false;
    }
  }
  fmySmoothShow(v, st, base);
}
function fmySmoothShow(v, st, base) {
  if (!st.mesh || !st.cage) return;
  st.cage.visible = v.smoothLevel === 2 && v.mode !== "poly";     // in component mode the component display is the cage
  if (base) base.visible = false;
  v.dirty = true;
}

// Mesh Display / Shading > Wireframe on Shaded: every mesh shows its edges in dark grey
function fmyWireOnShaded() {
  const v = fmyView();
  if (!v || !v.tree) return "";
  v.wireOnShaded = !v.wireOnShaded;
  const THREE = v.THREE;
  const scene = (() => { let s = v.holder; while (s.parent) s = s.parent; return s; })();
  scene.traverse((o) => { if (o.userData && o.userData.fmyWos) o.visible = false; });
  const old = []; scene.traverse((o) => { if (o.userData && o.userData.fmyWos) old.push(o); });
  for (const o of old) { o.parent.remove(o); o.geometry.dispose(); o.material.dispose(); }
  if (v.wireOnShaded) {
    for (const m of v.tree.api.pickables()) {
      const tris = (m.geometry.index ? m.geometry.index.count : m.geometry.attributes.position.count) / 3;
      if (tris > 150000) continue;
      const l = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry, 1), new THREE.LineBasicMaterial({ color: 0x1b1b1b, transparent: true, opacity: 0.6 }));
      l.userData.fmyWos = true; l.raycast = () => {};
      m.add(l);
    }
  }
  v.dirty = true;
  fmySync();
  return v.wireOnShaded ? "Wireframe on Shaded." : "Shaded.";
}

// Display 4 = wireframe ONLY, the pro way (owner 2026-10-21: "4 is wireframe"): every object's shaded surface hides
// and its polygon edges draw instead (dark navy; the selection keeps its colour); 5 brings the shading back. The
// edges follow edits (rebuilt when a geometry changes) and the hidden surfaces still pick. A very dense mesh
// (> 150k triangles) shows its triangles instead of a polygon-edge overlay.
// the pro wireframe (owner 2026-10-21: "wireframe mode needs to be better, it's gotta work like [the pro tools]"):
// every edge of every object shows - the back ones too, nothing hides them - unselected objects in dark blue, the
// selected ones white and the last selected (the lead) light green; in component mode the cage colours of the
// component display take over. Selection goes through the model in wireframe (camera based selection: automatic).
const FMY_WIRE_COLOR = 0x101e66, FMY_WIRE_SEL = 0xffffff, FMY_WIRE_LEAD = 0x65fdcd;
function fmyWireOnly(v, on) {
  if (!v) return "";
  v.wireOnly = !!on;
  fmyWireSync(v, true);
  return on ? "Wireframe (4)." : "Shaded (5).";
}
function fmyWireTargets(v) {
  const out = [];
  if (!v || !v.holder) return out;
  let scene = v.holder; while (scene.parent) scene = scene.parent;
  scene.traverse((o) => {
    if (!o.isMesh || !o.geometry || !o.material) return;
    if (o.name === "forge" || o.name === "shape" || o.name === "forge-smooth") out.push(o);
  });
  return out;
}
function fmyWireSync(v, force) {
  const want = !!v.wireOnly;
  for (const m of fmyWireTargets(v)) {
    const ud = m.userData;
    const g = m.geometry, ver = (g.attributes.position ? g.attributes.position.version : 0) + ":" + g.uuid + (m.name === "forge" && v.poly ? ":" + v.poly.v.length + "/" + v.poly.f.length : "");
    const mats = Array.isArray(m.material) ? m.material : [m.material];
    if (!want) {
      if (ud.fmyWire) { m.remove(ud.fmyWire); ud.fmyWire.geometry.dispose(); ud.fmyWire.material.dispose(); ud.fmyWire = null; }
      if (ud.fmyHid) { for (const mt of mats) { mt.colorWrite = true; mt.depthWrite = true; mt.wireframe = false; } ud.fmyHid = false; }
      continue;
    }
    // the surface draws nothing - no colour and no depth - so the far side's edges show through, the pro way
    if (!ud.fmyHid || force) { for (const mt of mats) { mt.colorWrite = false; mt.depthWrite = false; } ud.fmyHid = true; }
    if (m.visible === false) continue;
    if (!ud.fmyWire || ud.fmyWireVer !== ver || force) {
      if (ud.fmyWire) { m.remove(ud.fmyWire); ud.fmyWire.geometry.dispose(); ud.fmyWire.material.dispose(); }
      const tris = (g.index ? g.index.count : g.attributes.position.count) / 3;
      // a modelled mesh draws its POLYGON edges (the cage's quads, never the triangles they are drawn with); a sculpt
      // or a scan has no cage: its triangle edges, the flat diagonals left out
      const tn = v.tree && v.tree.api && v.tree.api.nodeOfObject ? v.tree.api.nodeOfObject(m) : null;
      const cage = m.name === "forge" ? v.poly : m.name === "forge-smooth" ? null : tn && tn.poly;
      let eg;
      if (cage && window.ForgePoly && window.ForgePoly.edges) {
        const E = window.ForgePoly.edges(cage), lp = new Float32Array(E.length * 6);
        E.forEach((e, i) => { lp.set(cage.v[e.a], i * 6); lp.set(cage.v[e.b], i * 6 + 3); });
        eg = new v.THREE.BufferGeometry(); eg.setAttribute("position", new v.THREE.BufferAttribute(lp, 3));
      } else eg = tris > 150000 ? new v.THREE.WireframeGeometry(g) : new v.THREE.EdgesGeometry(g, 1);
      const l = new v.THREE.LineSegments(eg, new v.THREE.LineBasicMaterial({ color: FMY_WIRE_COLOR }));
      l.name = "fmy-wire"; l.raycast = () => {}; l.renderOrder = 1;
      m.add(l); ud.fmyWire = l; ud.fmyWireVer = ver;
    }
    // the colour says what is selected
    let col = FMY_WIRE_COLOR;
    const t = v.tree && v.tree.api, n = t && t.nodeOfObject ? t.nodeOfObject(m) : null, sel = t ? t.selected() : [];
    if (n && sel.includes(n.id)) col = sel[sel.length - 1] === n.id ? FMY_WIRE_LEAD : FMY_WIRE_SEL;
    if (v.mode === "poly" && m.name === "forge") col = 0x5c6f8a;      // component mode: the component display draws the cage
    if (ud.fmyWire.material.color.getHex() !== col) ud.fmyWire.material.color.setHex(col);
  }
  v.dirty = true;
}

// the heads-up poly count: all visible objects | the selected objects | the selected components (the pro 3 columns)
const fmyCountCache = new WeakMap(), fmyTopo = new WeakMap();
function fmyCountGeo(g) {
  let c = fmyCountCache.get(g);
  const ver = (g.attributes.position && g.attributes.position.version) || 0;
  if (c && c.ver === ver) return c;
  const pos = g.attributes.position, n = pos ? pos.count : 0;
  const idx = g.index ? g.index.array : null, tris = (idx ? idx.length : n) / 3;
  // vertices and edges by position (a shape's corners are split per face for flat shading)
  const key = (i) => pos.getX(i).toFixed(5) + "," + pos.getY(i).toFixed(5) + "," + pos.getZ(i).toFixed(5);
  let verts = n, edges = Math.round(tris * 1.5);
  if (n && n < 120000) {
    const id = new Map(), vid = new Int32Array(n);
    for (let i = 0; i < n; i++) { const k = key(i); let x = id.get(k); if (x == null) { x = id.size; id.set(k, x); } vid[i] = x; }
    verts = id.size;
    const es = new Set();
    for (let t = 0; t < tris; t++) {
      const a = vid[idx ? idx[t * 3] : t * 3], b = vid[idx ? idx[t * 3 + 1] : t * 3 + 1], cc = vid[idx ? idx[t * 3 + 2] : t * 3 + 2];
      for (const [p, q] of [[a, b], [b, cc], [cc, a]]) es.add(p < q ? p * 1048576 + q : q * 1048576 + p);
    }
    edges = es.size;
  }
  c = { ver, verts, edges, faces: tris, tris, uvs: g.attributes.uv ? g.attributes.uv.count : 0 };
  fmyCountCache.set(g, c);
  return c;
}
function fmyHudUpdate(v) {
  const table = document.getElementById("fmy-polycount");
  if (!table || table.closest("[hidden]") || !v.tree) return;
  const t = v.tree.api;
  const sum = (ids) => {
    const r = { verts: 0, edges: 0, faces: 0, tris: 0, uvs: 0 };
    for (const id of ids) {
      const n = t.node(id); if (!n || !n.visible) continue;
      n.inner.children.forEach((o) => {
        // only real shapes count - not the smooth preview, the cut-point markers or any other helper drawn in the holder
        if (!o.isMesh || !o.geometry || (o.name !== "forge" && o.name !== "shape")) return;
        let c;
        if (n.root && v.sm && !v.poly) {              // the edited mesh: Forge already knows its welded vertices
          const tris = v.sm.idx ? v.sm.idx.length / 3 : 0;
          c = { verts: v.sm.n || 0, edges: Math.round(tris * 1.5), faces: tris, tris, uvs: v.sm.uv ? v.sm.uv.length / 2 : 0 };
        } else c = fmyCountGeo(o.geometry);
        if (n.root && v.poly) {                      // the edited mesh: its real polygons and edges
          const P = window.ForgePoly;
          let e = c.edges;
          try {
            if (P && P.topology) {
              let T = fmyTopo.get(v.poly);
              if (!T) { T = P.topology(v.poly); fmyTopo.set(v.poly, T); }
              e = T.edges.length;
            }
          } catch (_) { /* keep the estimate */ }
          c = Object.assign({}, c, { verts: v.poly.v.length, faces: v.poly.f.length, edges: e });
        }
        for (const k of Object.keys(r)) r[k] += c[k];
      });
    }
    return r;
  };
  const all = sum(t.allIds()), sel = sum(t.selected());
  const inComp = v.mode === "poly" && !!v.edit;
  const comp = inComp ? { verts: v.edit.sel.v.size, edges: v.edit.sel.e.size, faces: v.edit.sel.f.size, tris: 0, uvs: 0 } : { verts: 0, edges: 0, faces: 0, tris: 0, uvs: 0 };
  // Maya's poly count is two columns - the whole scene and the selection. Forge's component counts are a third one,
  // shown only while there is a component selection to count.
  if (table.classList.contains("fmy-comp") !== inComp) table.classList.toggle("fmy-comp", inComp);
  for (const tr of table.rows) {
    const k = tr.dataset.k;
    tr.cells[1].textContent = String(all[k]); tr.cells[2].textContent = String(sel[k]); tr.cells[3].textContent = String(comp[k]);
  }
}
