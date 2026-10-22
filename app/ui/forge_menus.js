// Forge's menus, your way (owner 2026-10-21: "i want all the menus to be adjustable so i can move them where i want
// even the quick menu and the wheels i want to adjust that").
//
//   * Tear-off menus (the pro tools' dashed line at the top of a menu): every menu bar menu, every hotbox menu and
//     every wheel menu has one. Click it and the menu becomes a small floating window you can drag anywhere, keep
//     open while you work and close with x. Torn-off menus come back where you left them.
//   * The Quick Menu (Alt+Q, Windows > Quick Menu): your own eight favourite commands around the mouse plus a list
//     under them. Right-click any item in a menu bar menu to add it to (or take it off) the Quick Menu.
//   * Menu Settings (Windows > Settings/Preferences > Menu Settings, or the Quick Menu's "Edit..."): the size and
//     opacity of the wheel, the hotbox, the marking menus and the Quick Menu; where the wheel and the hotbox open
//     (at the mouse, in the middle of the viewport, or where you put them - drag the wheel's middle or the hotbox's
//     grip while one is open); and an editor for the Quick Menu and every marking menu: pick a menu, put any command
//     on any of its eight directions, add / remove / reorder its list. Reset puts every menu back.
// Kept per viewer (localStorage, wrapped in try/catch). Uses the commands of forge_pro.js (FORGE_PRO_CMDS).
"use strict";

const FORGE_MENUS_STORE = "loki-forge-menus";
const FORGE_TEAR_STORE = "loki-forge-tearoffs";
const FORGE_COMPASS_ORDER = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const FORGE_QUICK_DEFAULT = {
  ring: { N: "multiCut", NE: "extrude", E: "bevel", SE: "merge", S: "edgeLoop", SW: "targetWeld", W: "frameSel", NW: "deleteHistory" },
  list: ["smooth", "centerPivot", "freeze", "duplicate", "uvSmart", "sculptReduce"],
};

function forgeMenusPrefs() {
  let p = null;
  try { p = JSON.parse(localStorage.getItem(FORGE_MENUS_STORE) || "null"); } catch (_) { p = null; }
  p = p && typeof p === "object" ? p : {};
  return Object.assign({ scale: 1, opacity: 1, open: "mouse", wheelAt: null, hotboxAt: null, quick: null, custom: {} }, p, { custom: p.custom || {} });
}
function forgeMenusSave(p) { try { localStorage.setItem(FORGE_MENUS_STORE, JSON.stringify(p)); } catch (_) { /* private window */ } }
function forgeMenusSay(msg) { if (msg && typeof forgeSay === "function") forgeSay(msg); return msg; }
function forgeMenusQuick() { const q = forgeMenusPrefs().quick; return q && q.ring ? q : JSON.parse(JSON.stringify(FORGE_QUICK_DEFAULT)); }
const forgeMenusLabel = (id) => { const c = typeof FORGE_PRO_CMDS !== "undefined" && FORGE_PRO_CMDS[id]; return c ? c[0] : id; };

// size + opacity on whichever menu just opened
function forgeMenusLook(el) {
  if (!el) return;
  const p = forgeMenusPrefs();
  el.style.scale = p.scale && p.scale !== 1 ? String(p.scale) : "";
  el.style.opacity = p.opacity && p.opacity < 1 ? String(p.opacity) : "";
}

// ------------------------------------------------------------------------------------------ the marking menus
// which set a menu is (so an edit sticks to "Edge tools", not to an object's name)
function forgeMenusKeyOf(menu) {
  if (!menu) return "";
  if (menu.quick) return "Quick Menu";
  const r = menu.ring || {};
  if (r.N === "edge" && r.W === "vertex") return "Components";
  if (!menu.title) return "Empty space";
  return menu.title;
}
if (typeof forgeProMenu === "function") {
  const orig = forgeProMenu;
  window.forgeProMenu = function (v, ctx) {
    const m = orig.apply(this, arguments);
    const c = forgeMenusPrefs().custom[forgeMenusKeyOf(m)];
    if (m && c) return Object.assign({}, m, { ring: c.ring ? Object.assign({}, c.ring) : m.ring, list: Array.isArray(c.list) ? c.list.slice() : m.list });
    return m;
  };
}
if (typeof forgeProMarkShow === "function") {
  const orig = forgeProMarkShow;
  window.forgeProMarkShow = function () {
    const r = orig.apply(this, arguments);
    const host = document.getElementById("forge-pro-marking");
    if (host) host.classList.toggle("fmenu-quick", !!(arguments[3] && arguments[3].quick));
    forgeMenusLook(host);
    return r;
  };
}

// ------------------------------------------------------------------------------------------ the wheel and the hotbox
function forgeMenusPlace(kind) {
  const p = forgeMenusPrefs();
  if (kind === "wheel") {
    const host = document.getElementById("forge-pro-wheel");
    if (!host || host.hidden) return;
    forgeMenusLook(host);
    const par = (host.parentElement || document.body).getBoundingClientRect();
    if (p.open === "centre") { host.style.left = Math.round(par.width / 2) + "px"; host.style.top = Math.round(par.height / 2) + "px"; }
    else if (p.open === "fixed" && p.wheelAt) { host.style.left = Math.round(par.width * p.wheelAt[0]) + "px"; host.style.top = Math.round(par.height * p.wheelAt[1]) + "px"; }
    forgeMenusWheelGrip(host);
  } else {
    const host = document.getElementById("forge-pro-hotbox"), box = host && host.querySelector(".forge-pro-hbbox");
    if (!box || host.hidden) return;
    forgeMenusLook(box);
    const stage = document.getElementById("forge-stage"), r = stage ? stage.getBoundingClientRect() : { left: 0, top: 0, width: innerWidth, height: innerHeight };
    if (p.open === "centre") { box.style.left = Math.round(r.left + r.width / 2) + "px"; box.style.top = Math.round(r.top + r.height / 2) + "px"; }
    else if (p.open === "fixed" && p.hotboxAt) { box.style.left = Math.round(innerWidth * p.hotboxAt[0]) + "px"; box.style.top = Math.round(innerHeight * p.hotboxAt[1]) + "px"; }
    forgeMenusHotboxGrip(host, box);
  }
}
if (typeof forgeProWheelOpen === "function") {
  const orig = forgeProWheelOpen;
  window.forgeProWheelOpen = function () { const r = orig.apply(this, arguments); forgeMenusPlace("wheel"); return r; };
}
if (typeof forgeProHotboxOpen === "function") {
  const orig = forgeProHotboxOpen;
  window.forgeProHotboxOpen = function () { const r = orig.apply(this, arguments); forgeMenusPlace("hotbox"); forgeMenusTearRows(); return r; };
}
if (typeof forgeProWheelSub === "function") {        // a wheel menu gets a pin: tear it off
  const orig = forgeProWheelSub;
  window.forgeProWheelSub = function (v, head, ids) {
    const r = orig.apply(this, arguments);
    const sub = document.querySelector("#forge-pro-wheel .forge-wheel-sub");
    if (sub && !sub.querySelector(".fmenu-tear")) sub.prepend(forgeMenusTearLine(head, "rows"));
    return r;
  };
}

// drag the wheel by its middle: it stays there ("where I put it")
function forgeMenusWheelGrip(host) {
  const hub = host.querySelector(".forge-wheel-hub");
  if (!hub || hub.dataset.fmenu) return;
  hub.dataset.fmenu = "1";
  hub.classList.add("fmenu-movable");
  hub.title = "Drag to move the wheel; it opens there from now on (Menu Settings: back to the mouse).";
  hub.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    host._used = true;
    try { hub.setPointerCapture(e.pointerId); } catch (_) { /* gone */ }
    const par = (host.parentElement || document.body).getBoundingClientRect();
    const mv = (ev) => { host.style.left = Math.round(ev.clientX - par.left) + "px"; host.style.top = Math.round(ev.clientY - par.top) + "px"; };
    const up = (ev) => {
      hub.removeEventListener("pointermove", mv); hub.removeEventListener("pointerup", up);
      const p = forgeMenusPrefs();
      p.wheelAt = [Math.max(0, Math.min(1, (ev.clientX - par.left) / (par.width || 1))), Math.max(0, Math.min(1, (ev.clientY - par.top) / (par.height || 1)))];
      p.open = "fixed"; forgeMenusSave(p);
      forgeMenusSay("The wheel opens here now (Menu Settings: at the mouse again).");
    };
    hub.addEventListener("pointermove", mv); hub.addEventListener("pointerup", up);
  });
}
function forgeMenusHotboxGrip(host, box) {
  if (box.querySelector(".fmenu-hbgrip")) return;
  const g = document.createElement("button");
  g.type = "button"; g.className = "fmenu-hbgrip"; g.setAttribute("aria-label", "Move the hotbox");
  g.title = "Drag to move the hotbox; it opens there from now on (Menu Settings: back to the mouse).";
  box.append(g);
  g.addEventListener("pointerdown", (e) => {
    e.preventDefault(); e.stopPropagation();
    host.dataset.pinned = "1";
    try { g.setPointerCapture(e.pointerId); } catch (_) { /* gone */ }
    const start = [e.clientX, e.clientY], at = [parseFloat(box.style.left) || 0, parseFloat(box.style.top) || 0];
    const mv = (ev) => { box.style.left = Math.round(at[0] + ev.clientX - start[0]) + "px"; box.style.top = Math.round(at[1] + ev.clientY - start[1]) + "px"; };
    const up = () => {
      g.removeEventListener("pointermove", mv); g.removeEventListener("pointerup", up);
      const p = forgeMenusPrefs();
      p.hotboxAt = [(parseFloat(box.style.left) || 0) / innerWidth, (parseFloat(box.style.top) || 0) / innerHeight];
      p.open = "fixed"; forgeMenusSave(p);
      forgeMenusSay("The hotbox opens here now (Menu Settings: at the mouse again).");
    };
    g.addEventListener("pointermove", mv); g.addEventListener("pointerup", up);
  });
}

// ------------------------------------------------------------------------------------------ tear-off menus
function forgeMenusTearLine(title, source) {
  const t = document.createElement("button");
  t.type = "button"; t.className = "fmenu-tear"; t.setAttribute("aria-label", "Tear off " + title);
  t.title = "Tear off: keep " + title + " open as a small window you can move anywhere.";
  t.addEventListener("pointerdown", (e) => e.stopPropagation());
  t.addEventListener("click", (e) => {
    e.stopPropagation();
    if (typeof fmyCloseMenus === "function") fmyCloseMenus();
    if (typeof forgeProHotboxHide === "function") forgeProHotboxHide();
    if (typeof forgeProWheelClose === "function") forgeProWheelClose();
    forgeMenusTearOff({ title, source, x: Math.min(0.7, (e.clientX + 20) / innerWidth), y: Math.min(0.7, e.clientY / innerHeight) });
  });
  return t;
}
function forgeMenusTearRows() {
  for (const col of document.querySelectorAll("#forge-pro-hotbox .forge-pro-col")) {
    const list = col.querySelector(".forge-pro-list");
    if (list && !list.querySelector(".fmenu-tear") && col.dataset.menu !== "Recent Commands") list.prepend(forgeMenusTearLine(col.dataset.menu, "rows"));
  }
}
if (typeof fmyDrop === "function") {
  const orig = fmyDrop;
  window.fmyDrop = function (anchor, items) {
    const d = orig.apply(this, arguments);
    const title = anchor && anchor.dataset && anchor.dataset.menu;
    if (d && title) {
      d.prepend(forgeMenusTearLine(title, "bar"));
      forgeMenusQuickRows(d);
    }
    return d;
  };
}
// right-click a menu row: in / out of the Quick Menu (top menus and their submenus alike)
function forgeMenusQuickRows(d) {
  for (const b of d.querySelectorAll(".fmy-ditem[data-pro-id]")) {
    const id = b.dataset.proId;
    if (!id || !(typeof FORGE_PRO_CMDS !== "undefined" && FORGE_PRO_CMDS[id])) continue;
    b.addEventListener("contextmenu", (e) => { e.preventDefault(); e.stopPropagation(); forgeMenusSay(forgeMenusQuickToggle(id)); if (typeof fmyCloseMenus === "function") fmyCloseMenus(); });
  }
}
if (typeof fmySubDrop === "function") {
  const origSub = fmySubDrop;
  window.fmySubDrop = function () { const d = origSub.apply(this, arguments); if (d) forgeMenusQuickRows(d); return d; };
}
// a menu tree as flat rows [id, label, run, on] (a torn-off menu lists every command of its submenus too)
function forgeMenusRows(list, out) {
  out = out || [];
  for (const it of list || []) {
    if (Array.isArray(it) && Array.isArray(it[1])) forgeMenusRows(it[1], out);
    else if (Array.isArray(it)) out.push(it);
    else if (typeof it === "string" && it !== "-" && it[0] !== "#") out.push([it]);
  }
  return out;
}
// the items of a torn-off menu, from where it came from: [id, label, run, on]
function forgeMenusItems(t) {
  if (t.source === "quick") {
    const q = forgeMenusQuick();
    return FORGE_COMPASS_ORDER.map((k) => q.ring[k]).filter((x) => typeof x === "string").concat(q.list || []).map((id) => [id]);
  }
  if (t.source === "bar" && typeof FMY_MENUS === "function") {
    const m = FMY_MENUS().find((x) => x[0] === t.title);
    return m ? forgeMenusRows(m[1]) : [];
  }
  const row = typeof FORGE_PRO_ROWS !== "undefined" && FORGE_PRO_ROWS.find((x) => x[0] === t.title);
  return row ? forgeMenusRows(row[1]) : [];
}
function forgeMenusTearOff(t, restoring) {
  const list = forgeMenusLoadTears();
  if (!restoring) {
    const same = list.findIndex((x) => x.title === t.title && x.source === t.source);
    if (same >= 0) list.splice(same, 1);
    list.push({ title: t.title, source: t.source, x: t.x, y: t.y });
    forgeMenusSaveTears(list);
  }
  const id = "fmenu-tear-" + (t.source + "-" + t.title).replace(/[^A-Za-z0-9]+/g, "-");
  document.getElementById(id)?.remove();
  const w = document.createElement("div");
  w.id = id; w.className = "fmenu-torn"; w.setAttribute("role", "menu"); w.setAttribute("aria-label", t.title);
  w.style.left = (t.x * 100).toFixed(2) + "%"; w.style.top = (t.y * 100).toFixed(2) + "%";
  const h = document.createElement("div"); h.className = "fmenu-torn-head";
  h.append(Object.assign(document.createElement("span"), { textContent: t.title }));
  const x = document.createElement("button"); x.type = "button"; x.className = "fdock-btn fdock-b-close"; x.title = "Close this menu"; x.setAttribute("aria-label", "Close");
  x.addEventListener("pointerdown", (e) => e.stopPropagation());
  x.addEventListener("click", () => { w.remove(); forgeMenusSaveTears(forgeMenusLoadTears().filter((o) => !(o.title === t.title && o.source === t.source))); });
  h.append(x);
  const body = document.createElement("div"); body.className = "fmenu-torn-body";
  const fill = () => {
    body.textContent = "";
    for (const [cid, label, run, on] of forgeMenusItems(t)) {
      const c = typeof FORGE_PRO_CMDS !== "undefined" && FORGE_PRO_CMDS[cid];
      if (!c && !run) continue;
      const b = document.createElement("button"); b.type = "button"; b.className = "fmy-ditem"; b.dataset.proId = cid || "";
      const ticked = on ? on() : (typeof fmyOn === "function" && fmyOn(cid));
      b.append(Object.assign(document.createElement("span"), { className: "fmy-tick", textContent: ticked ? "✓" : "" }),
        Object.assign(document.createElement("span"), { className: "fmy-dlabel", textContent: label || (c ? c[0] : cid) }),
        Object.assign(document.createElement("span"), { className: "fmy-dkey", textContent: typeof fmyKeyOf === "function" ? fmyKeyOf(cid) : "" }));
      if (c && !c[1] && !run) continue;                      // not in Forge yet: left out
      b.addEventListener("click", () => { if (run) run(); else if (typeof fmyRun === "function") fmyRun(cid); setTimeout(fill, 60); });
      body.append(b);
    }
  };
  fill();
  w.append(h, body);
  (document.getElementById("forge") || document.body).append(w);
  let st = null;
  h.addEventListener("pointerdown", (e) => { if (e.button !== 0) return; const r = w.getBoundingClientRect(); st = [e.clientX - r.left, e.clientY - r.top]; try { h.setPointerCapture(e.pointerId); } catch (_) { /* gone */ } });
  h.addEventListener("pointermove", (e) => {
    if (!st) return;
    w.style.left = (Math.max(0, Math.min(innerWidth - 60, e.clientX - st[0])) / innerWidth * 100).toFixed(2) + "%";
    w.style.top = (Math.max(0, Math.min(innerHeight - 24, e.clientY - st[1])) / innerHeight * 100).toFixed(2) + "%";
  });
  h.addEventListener("pointerup", () => {
    if (!st) return; st = null;
    const l = forgeMenusLoadTears(), o = l.find((q) => q.title === t.title && q.source === t.source);
    if (o) { o.x = parseFloat(w.style.left) / 100; o.y = parseFloat(w.style.top) / 100; forgeMenusSaveTears(l); }
  });
  return w;
}
function forgeMenusLoadTears() { try { const l = JSON.parse(localStorage.getItem(FORGE_TEAR_STORE) || "[]"); return Array.isArray(l) ? l : []; } catch (_) { return []; } }
function forgeMenusSaveTears(l) { try { localStorage.setItem(FORGE_TEAR_STORE, JSON.stringify(l)); } catch (_) { /* private window */ } }
// a torn-off menu shows only while Forge is open
(function forgeMenusTearWatch() {
  let was = false;
  setInterval(() => {
    const f = document.getElementById("forge"), open = !!(f && !f.hidden && document.querySelector("#forge .forge-body"));
    if (open && !was) for (const t of forgeMenusLoadTears()) forgeMenusTearOff(t, true);
    if (!open && was) document.querySelectorAll(".fmenu-torn").forEach((w) => w.remove());
    was = open;
  }, 600);
})();

// ------------------------------------------------------------------------------------------ the Quick Menu
function forgeMenusQuickOpen(v, at) {
  if (typeof forgeProMarkShow !== "function") return "";
  const q = forgeMenusQuick();
  const p = at || (v && v.pro && v.pro.mouse) || [innerWidth / 2, innerHeight / 2];
  forgeProMarkShow(v, p[0], p[1], { title: "Quick", quick: true, ring: Object.assign({}, q.ring), list: (q.list || []).concat(["menuSettings"]) });
  const host = document.getElementById("forge-pro-marking");
  if (host) {
    host.classList.add("fmenu-quick");
    const off = (e) => {
      if (host.hidden) { document.removeEventListener("pointerdown", off, true); return; }
      if (!host.contains(e.target)) { forgeProMarkHide(); host.classList.remove("fmenu-quick"); document.removeEventListener("pointerdown", off, true); }
    };
    setTimeout(() => document.addEventListener("pointerdown", off, true), 0);
  }
  return "Quick Menu: click a command (right-click any menu item to add it here; Edit... changes it).";
}
function forgeMenusQuickToggle(id) {
  const p = forgeMenusPrefs(), q = forgeMenusQuick();
  const inRing = FORGE_COMPASS_ORDER.find((k) => q.ring[k] === id);
  if (inRing) delete q.ring[inRing];
  else if ((q.list || []).includes(id)) q.list = q.list.filter((x) => x !== id);
  else {
    const free = FORGE_COMPASS_ORDER.find((k) => !q.ring[k]);
    if (free) q.ring[free] = id; else q.list = (q.list || []).concat([id]);
    p.quick = q; forgeMenusSave(p);
    return forgeMenusLabel(id) + " added to the Quick Menu (Alt+Q).";
  }
  p.quick = q; forgeMenusSave(p);
  return forgeMenusLabel(id) + " taken off the Quick Menu.";
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { const h = document.getElementById("forge-pro-marking"); if (h && !h.hidden && h.classList.contains("fmenu-quick")) { forgeProMarkHide(); h.classList.remove("fmenu-quick"); } }
}, true);

// ------------------------------------------------------------------------------------------ Menu Settings
// the menus you can edit: the Quick Menu and the marking menu sets (forge_pro.js forgeProMenu)
const FORGE_MENU_SETS = [
  ["Quick Menu", null],
  ["Create", { shift: true }], ["Vertex tools", { shift: true, mode: "vert" }], ["Edge tools", { shift: true, mode: "edge" }],
  ["Face tools", { shift: true, mode: "face" }], ["Mesh tools", { shift: true, node: true }], ["Components", { node: true }],
  ["Empty space", {}], ["Convert", { ctrl: true }],
];
function forgeMenusDefaultOf(name) {
  if (name === "Quick Menu") return JSON.parse(JSON.stringify(FORGE_QUICK_DEFAULT));
  const known = {
    Create: { ring: { NE: "quadsphere", E: "sphere", SE: "torus", S: "cube", SW: "cone", W: "cylinder", NW: "plane" }, list: ["imagePlane", "draw", "image", "describe", "creature"] },
    "Vertex tools": { ring: { S: "extrude", E: "chamfer", SW: "deleteEdgeVert", N: "merge", NE: "averageVerts", W: "multiCut", NW: "connect", SE: "targetWeld" }, list: ["mergeCenter", "detach", "relax", "circularize", "grow", "shrink"] },
    "Edge tools": { ring: { S: "extrude", E: "bevel", SW: "deleteEdgeVert", N: "bridge", NE: "edgeLoop", W: "multiCut", NW: "connect", SE: "offsetEdgeLoop" }, list: ["merge", "collapse", "slideEdge", "spinEdge", "detach", "fillHole", "loopSel", "ringSel", "grow", "shrink"] },
    "Face tools": { ring: { S: "extrude", E: "bevel", SW: "wedge", NE: "poke", SE: "reverse", W: "multiCut", NW: "inset", N: "duplicateFace" }, list: ["extractFace", "collapse", "triangulate", "quadrangulate", "circularize", "deleteComp", "smooth", "grow", "shrink"] },
    "Mesh tools": { ring: { S: "extrude", SW: "edgeLoop", NE: "fillHole", N: "merge", W: "multiCut", NW: "sculpt", E: "softHard" }, list: ["smooth", "dynamesh", "makeLive"] },
    Components: { ring: { N: "edge", W: "vertex", S: "uv", E: "face", SW: "vertexFace", SE: "uvShell", NW: "multi", NE: "objectMode" }, list: ["select", "move", "rotate", "scale", "frameSel", "hierarchy", "invert", "duplicate", "group", "centerPivot", "resetPivot", "resetXf", "freeze", "makeLive", "delete", "more"] },
    "Empty space": { ring: {}, list: ["completeTool", "selectAll", "selectNone", "undo", "redo", "repeatLast", "frameAll", "more"] },
    Convert: { ring: { W: "vertex", N: "edge", S: "face", E: "toUV", NE: "grow", NW: "shrink", SE: "loopSel", SW: "ringSel" }, list: [] },
  };
  return JSON.parse(JSON.stringify(known[name] || { ring: {}, list: [] }));
}
function forgeMenusGet(name) {
  const p = forgeMenusPrefs();
  if (name === "Quick Menu") return forgeMenusQuick();
  return p.custom[name] ? JSON.parse(JSON.stringify(p.custom[name])) : forgeMenusDefaultOf(name);
}
function forgeMenusPut(name, m) {
  const p = forgeMenusPrefs();
  if (name === "Quick Menu") p.quick = m; else p.custom[name] = m;
  forgeMenusSave(p);
}

function forgeMenusSettings() {
  let d = document.getElementById("fmenu-settings");
  if (d) { d.remove(); return "Menu Settings closed."; }
  d = document.createElement("div");
  d.id = "fmenu-settings"; d.className = "fdock-dialog fmenu-settings";
  d.setAttribute("role", "dialog"); d.setAttribute("aria-label", "Menu Settings");
  const head = document.createElement("div"); head.className = "fdock-head";
  head.append(Object.assign(document.createElement("span"), { className: "fdock-title", textContent: "Menu Settings" }));
  const x = document.createElement("button"); x.type = "button"; x.className = "fdock-btn fdock-b-close"; x.title = "Close"; x.setAttribute("aria-label", "Close");
  x.addEventListener("click", () => d.remove()); head.append(x);
  const p = forgeMenusPrefs();
  const row = (label, input) => { const r = document.createElement("label"); r.className = "fdock-scale"; r.append(Object.assign(document.createElement("span"), { textContent: label }), input); return r; };
  const range = (id, min, max, step, val, fn) => { const i = document.createElement("input"); i.type = "range"; i.id = id; i.min = min; i.max = max; i.step = step; i.value = val; i.addEventListener("input", () => fn(+i.value)); return i; };
  const size = range("fmenu-scale", 0.6, 1.8, 0.05, p.scale, (v) => { const q = forgeMenusPrefs(); q.scale = v; forgeMenusSave(q); });
  const opac = range("fmenu-opacity", 0.4, 1, 0.05, p.opacity, (v) => { const q = forgeMenusPrefs(); q.opacity = v; forgeMenusSave(q); });
  const where = document.createElement("select"); where.id = "fmenu-open";
  for (const [v, t] of [["mouse", "At the mouse"], ["centre", "Middle of the viewport"], ["fixed", "Where I put them"]]) { const o = document.createElement("option"); o.value = v; o.textContent = t; where.append(o); }
  where.value = p.open;
  where.addEventListener("change", () => { const q = forgeMenusPrefs(); q.open = where.value; forgeMenusSave(q); });
  const tip = Object.assign(document.createElement("div"), { className: "fdock-empty", textContent: "Wheel and hotbox: drag the wheel's middle or the hotbox's grip while it is open to put it somewhere." });

  // the editor
  const pick = document.createElement("select"); pick.id = "fmenu-pick";
  for (const [n] of FORGE_MENU_SETS) { const o = document.createElement("option"); o.value = n; o.textContent = n; pick.append(o); }
  const ids = typeof FORGE_PRO_CMDS !== "undefined" ? Object.keys(FORGE_PRO_CMDS).filter((k) => !/^__/.test(k)).sort((a, b) => forgeMenusLabel(a).localeCompare(forgeMenusLabel(b))) : [];
  const cmdSelect = (val) => {
    const s = document.createElement("select"); s.className = "fmenu-cmd";
    const none = document.createElement("option"); none.value = ""; none.textContent = "-"; s.append(none);
    for (const k of ids) { const o = document.createElement("option"); o.value = k; o.textContent = forgeMenusLabel(k); s.append(o); }
    s.value = val || "";
    return s;
  };
  const ring = document.createElement("div"); ring.className = "fmenu-ring";
  const list = document.createElement("div"); list.className = "fmenu-list";
  const add = cmdSelect(""); add.id = "fmenu-add";
  const render = () => {
    const m = forgeMenusGet(pick.value);
    ring.textContent = ""; list.textContent = "";
    for (const k of FORGE_COMPASS_ORDER) {
      const cell = document.createElement("label"); cell.className = "fmenu-slot fmenu-" + k.toLowerCase();
      const s = cmdSelect(typeof m.ring[k] === "string" ? m.ring[k] : ""); s.dataset.slot = k;   // a sub-menu wedge reads as empty here
      s.addEventListener("change", () => { const mm = forgeMenusGet(pick.value); if (s.value) mm.ring[k] = s.value; else delete mm.ring[k]; forgeMenusPut(pick.value, mm); });
      cell.append(Object.assign(document.createElement("span"), { textContent: k }), s);
      ring.append(cell);
    }
    (m.list || []).forEach((cid, i) => {
      const r = document.createElement("div"); r.className = "fdock-row fmenu-item";
      const name = Object.assign(document.createElement("span"), { className: "fmenu-name", textContent: forgeMenusLabel(cid) });
      const mk = (t, what, fn) => { const b = document.createElement("button"); b.type = "button"; b.className = "mini"; b.textContent = t; b.title = what; b.addEventListener("click", () => { const mm = forgeMenusGet(pick.value); fn(mm.list); forgeMenusPut(pick.value, mm); render(); }); return b; };
      r.append(name, mk("↑", "Move up", (l) => { if (i > 0) l.splice(i - 1, 0, l.splice(i, 1)[0]); }), mk("↓", "Move down", (l) => { if (i < l.length - 1) l.splice(i + 1, 0, l.splice(i, 1)[0]); }), mk("×", "Remove", (l) => l.splice(i, 1)));
      list.append(r);
    });
  };
  pick.addEventListener("change", render);
  add.addEventListener("change", () => { if (!add.value) return; const mm = forgeMenusGet(pick.value); mm.list = (mm.list || []).concat([add.value]); forgeMenusPut(pick.value, mm); add.value = ""; render(); });
  const reset1 = document.createElement("button"); reset1.type = "button"; reset1.className = "mini"; reset1.textContent = "Reset this menu"; reset1.id = "fmenu-reset1";
  reset1.addEventListener("click", () => { const q = forgeMenusPrefs(); if (pick.value === "Quick Menu") q.quick = null; else delete q.custom[pick.value]; forgeMenusSave(q); render(); });
  const resetAll = document.createElement("button"); resetAll.type = "button"; resetAll.className = "mini"; resetAll.textContent = "Reset every menu"; resetAll.id = "fmenu-resetall";
  resetAll.addEventListener("click", () => { forgeMenusSave({}); forgeMenusSaveTears([]); document.querySelectorAll(".fmenu-torn").forEach((w) => w.remove()); d.remove(); forgeMenusSay("Every menu is back to its default (size, place, contents, torn-off menus)."); });
  const body = document.createElement("div"); body.className = "fmenu-body";
  body.append(row("Size", size), row("Opacity", opac), row("Wheel and hotbox open", where), tip,
    Object.assign(document.createElement("div"), { className: "fdock-sub", textContent: "Edit a menu" }), row("Menu", pick), ring, list, row("Add to its list", add),
    Object.assign(document.createElement("div"), { className: "fdock-row" }));
  body.lastChild.append(reset1, resetAll);
  d.append(head, body);
  (document.getElementById("forge") || document.body).append(d);
  render();
  let st = null;
  head.addEventListener("pointerdown", (e) => { if (e.target.closest("button")) return; const r = d.getBoundingClientRect(); st = [e.clientX - r.left, e.clientY - r.top]; try { head.setPointerCapture(e.pointerId); } catch (_) { /* gone */ } });
  head.addEventListener("pointermove", (e) => { if (!st) return; d.style.left = (Math.max(0, e.clientX - st[0]) / innerWidth * 100) + "%"; d.style.top = (Math.max(0, e.clientY - st[1]) / innerHeight * 100) + "%"; d.style.right = "auto"; });
  head.addEventListener("pointerup", () => { st = null; });
  return "Menu Settings: size, opacity, where the wheel and hotbox open, and what every menu holds.";
}

// ------------------------------------------------------------------------------------------ commands + keys
if (typeof FORGE_PRO_CMDS !== "undefined") {
  const add = (id, label, fn) => { if (!FORGE_PRO_CMDS[id]) FORGE_PRO_CMDS[id] = [label, fn]; };
  add("quickMenu", "Quick Menu", (v) => forgeMenusQuickOpen(v));
  add("menuSettings", "Menu Settings...", () => forgeMenusSettings());
}
if (typeof FORGE_KEY_DEFAULTS !== "undefined" && !FORGE_KEY_DEFAULTS.some((k) => k[1] === "quickMenu")) FORGE_KEY_DEFAULTS.push(["alt+q", "quickMenu"]);
if (typeof FORGE_KEY_GROUPS !== "undefined") {
  const w = FORGE_KEY_GROUPS.find((g) => g[0] === "Windows");
  if (w) for (const id of ["quickMenu", "menuSettings", "layouts", "layoutReset"]) if (!w[1].includes(id)) w[1].push(id);
}
if (typeof FORGE_PRO_ROWS !== "undefined") {             // the hotbox's Windows menu lists them too
  const w = FORGE_PRO_ROWS.find((r) => r[0] === "Windows");
  const have = w && (typeof forgeMenuFlat === "function" ? forgeMenuFlat(w[1]) : w[1]);
  if (w) for (const id of ["quickMenu", "menuSettings", "layouts"]) if (!have.includes(id)) w[1].push(id);
}
