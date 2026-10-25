// Forge: make 3D things. Three ways in - Draw (a canvas), Add an image (drop or pick), Describe it (text ->
// picture, shown first so it can be redone) - then the engine lifts the picture to a 3D model
// (engine/forge3d.py: TripoSR on this computer, a free online Space, or the offline lift that always works).
// Output: a collapsible panel of modular sliders (forge3d.OPTIONS, served by GET /forge/status) passed to every
// backend that honours them, remembered in localStorage, greyed out when the chosen backend ignores them.
// Model: three.js (vendored, MIT) with its own GLTFLoader, GLTFExporter, OBJExporter, OrbitControls and
// TransformControls (app/ui/vendor/three/addons). Sculpt: the brushes of SculptGL by Stéphane Ginier (MIT,
// github.com/stephomi/sculptgl - the web sculpting app Nomad Sculpt's author made first), ported below:
// Brush (clay), Inflate, Smooth (Laplacian), Flatten, Move (grab), Pinch, Crease, with its smooth falloff
// 3t^4 - 4t^3 + 1, its stroke spacing (0.15 x radius), X symmetry, undo/redo, and Subdivide.
// Materials: the Material Maker side (forge_materials.js + forge_mm.js), applied to the model live.
// Save .glb / .obj puts the file in the workspace's models/ (POST /forge/save) - shown in Files.
// Uses api(), el(), state from app.js and the icon pattern of icons.js. Plain DOM, CSP-safe.
"use strict";

Object.assign(ICON_PATHS, {
  cube: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
  brush: '<path d="M19.5 4.5l-8 8"/><path d="M11.5 12.5c-2.5-.5-5 1-5 3.5 0 1.5-1 2.5-2.5 3 3.5 1 7.5.5 8.5-3 .3-1.2 0-2.6-1-3.5z"/>',
  eraser: '<path d="M8 19.5h12"/><path d="M4.5 14.5l9-9 6 6-8 8H9z"/><path d="M9.5 9.5l6 6"/>',
  undo: '<path d="M9 7.5L4.5 12 9 16.5"/><path d="M4.5 12h10a5 5 0 0 1 0 10h-2"/>',
  redo: '<path d="M15 7.5l4.5 4.5-4.5 4.5"/><path d="M19.5 12h-10a5 5 0 0 0 0 10h2"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
  sparkle: '<path d="M12 3.5l1.8 5 5 1.8-5 1.8-1.8 5-1.8-5-5-1.8 5-1.8z"/><path d="M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
  wire: '<path d="M4 6.5h16v11H4z"/><path d="M4 6.5l16 11M12 6.5v11M4 12h16"/>',
  sun: '<circle cx="12" cy="12" r="3.8"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>',
  clay: '<circle cx="12" cy="12" r="8"/><path d="M8 9.5c1.5-1.5 3.5-2 5.5-1.2"/>',
  frame: '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/><circle cx="12" cy="12" r="2.5"/>',
  sculpt: '<path d="M5 19.5c2-6 5-9 9-11"/><circle cx="16.5" cy="7" r="3"/><path d="M3.5 20.5h17"/>',
  inflate: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.5 5.5l2 2M16.5 16.5l2 2M5.5 18.5l2-2M16.5 7.5l2-2"/>',
  smooth: '<path d="M3.5 15c3-5 5-5 8.5 0s5.5 5 8.5 0"/><path d="M3.5 9h17"/>',
  flatten: '<path d="M3.5 14.5h17"/><path d="M6 10.5c2-3 4-3 6 0s4 3 6 0"/><path d="M12 17v3.5"/>',
  grab: '<path d="M8 11V5.5a1.5 1.5 0 0 1 3 0V10M11 9.5V4a1.5 1.5 0 0 1 3 0v6M14 10V5.5a1.5 1.5 0 0 1 3 0V13c0 4-2.5 7-6 7-2.5 0-4-1.5-5.5-4L4 12.5a1.5 1.5 0 0 1 2.5-1.5L8 13"/>',
  pinch: '<path d="M4 6l6 6-6 6M20 6l-6 6 6 6"/>',
  crease: '<path d="M3.5 8c4 0 6 8 8.5 8s4.5-8 8.5-8"/>',
  mirror: '<path d="M12 3v18" stroke-dasharray="2 2"/><path d="M9 7L4 12l5 5zM15 7l5 5-5 5z"/>',
  compress: '<path d="M12 3.5l8.5 15h-17z"/><path d="M8 7.5h8M9.5 4.5l2.5 2.5 2.5-2.5M9.5 21l2.5-2.5 2.5 2.5"/>',
  subdivide: '<path d="M12 3.5l8.5 15h-17z"/><path d="M7.75 11h8.5M12 18.5l-4.25-7.5M12 18.5l4.25-7.5"/>',
  save: '<path d="M5 3.5h11l3.5 3.5v13.5H5z"/><path d="M8 3.5v5h7v-5M8 20.5v-6h8v6"/>',
  move: '<path d="M12 3v18M3 12h18"/><path d="M9 6l3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3"/>',
  material: '<circle cx="12" cy="12" r="8.5"/><path d="M5 9.5c4 1.5 10 1.5 14 0M4 14c5 2 11 2 16 0"/>',
  chevron: '<path d="M8 10l4 4 4-4"/>',
  popout: '<path d="M14 4h6v6"/><path d="M20 4l-8 8"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
});

const forge = { way: "draw", job: "", jobTimer: 0, view: null, model: null, imageRel: "", backend: "auto", side: "make",
  drawing: { ctx: null, hist: [], tool: "brush", color: "#ed782b", size: 14, down: false, last: null }, picked: "",
  options: [], values: {} };
// [id, icon, name, what] - the algorithm of each is SculptGL's (src/editing/tools/<Name>.js), see forgeMakeView
const FORGE_BRUSHES = [
  ["draw", "brush", "Clay", "Clay: build the surface up along the area's plane (Alt/Ctrl digs in)."],
  ["inflate", "inflate", "Inflate", "Swell the surface, each point along its own normal (Alt/Ctrl deflates)."],
  ["smooth", "smooth", "Smooth", "Laplacian smooth toward the neighbours (Shift smooths with any brush)."],
  ["flatten", "flatten", "Flatten", "Press the surface onto the area's plane - planes and hard surfaces."],
  ["grab", "grab", "Grab", "Grab: pull a whole area along with the mouse."],
  ["pinch", "pinch", "Pinch", "Pull the surface toward the brush centre - sharpen edges."],
  ["crease", "crease", "Crease", "Pinch and dig at once - folds, cuts and wrinkles (Alt/Ctrl raises a ridge)."],
];
const FORGE_LIGHTS = [
  ["Studio", 0xdfe6f2, 0x2a2e36, 1.0, 0xffffff, 2.4],
  ["Warm", 0xffe2c4, 0x2c241f, 1.0, 0xfff1dc, 2.4],
  ["Cool", 0xcfe0ff, 0x1d2430, 1.1, 0xe4efff, 2.2],
  ["Soft", 0xffffff, 0x60646e, 1.8, 0xffffff, 0.8],
];
const FORGE_STORE = "loki-forge-output";
const FORGE_NATIVE_NORMALS_MIN = 4000;   // faces: from here the soft / hard normals come from the C++ engine (forge_geom.js)
const FORGE_PRO_GREY = 0x9a9a9a;   // lambert1 under the pro default light reads #626262-#717171 on screen (measured)

function forgeBtn(icon, name, what, onClick, cls) {
  const b = el("button", "mini icon-mini forge-btn" + (cls ? " " + cls : ""), name);
  b.type = "button"; b.dataset.icon = icon; b.dataset.tipName = name; b.dataset.tipWhat = what;
  b.addEventListener("click", onClick);
  return b;
}

function forgeSay(text, bad) {
  const s = document.getElementById("forge-status");
  if (s) { s.textContent = text || ""; s.classList.toggle("bad", !!bad); s.title = text || ""; }
}

// ------------------------------------------------------------------------------------------ the sheet
function forgeBuild() {
  if (document.getElementById("forge")) return;
  const sheet = el("div", "sheet forge-sheet"); sheet.id = "forge"; sheet.hidden = true;
  const panel = el("div", "sheet-panel forge-panel");
  panel.setAttribute("role", "dialog"); panel.setAttribute("aria-modal", "true"); panel.setAttribute("aria-labelledby", "forge-title");
  const head = el("header", "sheet-head forge-head");
  const title = el("h2", "", "Forge"); title.id = "forge-title";
  const tabs = el("div", "forge-tabs"); tabs.setAttribute("role", "tablist");
  for (const [id, icon, name, what] of [["make", "cube", "Model", "Make, view and sculpt the 3D model."],
    ["materials", "material", "Materials", "Procedural materials from node graphs - applied to the model live."]]) {
    const b = forgeBtn(icon, name, what, () => forgeSide(id), "forge-tab"); b.dataset.side = id; b.setAttribute("role", "tab");
    tabs.append(b);
  }
  const status = el("span", "forge-status"); status.id = "forge-status"; status.setAttribute("role", "status");
  head.append(title, tabs, status, forgeBtn("close", "Close", "Close Forge (Esc).", forgeClose));
  const body = el("div", "forge-body pro");
  // the pro workspace (owner 2026-10-19): the Outliner on the left, the viewport, the Channel Box on the right;
  // the Create panel, Materials, the shelf and the toolkit come back from the Space menu (Windows) - forge_pro.js
  const outCol = el("aside", "forge-outcol"); outCol.id = "forge-outcol";
  const chanCol = el("aside", "forge-chancol"); chanCol.id = "forge-chancol";
  body.append(outCol, forgeLeft(), forgeStage());
  const mats = el("section", "forge-materials"); mats.id = "forge-materials"; mats.hidden = true;
  body.append(mats, chanCol);
  panel.classList.add("pro");
  panel.append(head, body);
  sheet.append(panel);
  document.body.append(sheet);
  sheet.addEventListener("click", (e) => { if (e.target === sheet) forgeClose(); });
}

function forgeLeft() {
  const side = el("aside", "forge-side"); side.id = "forge-left";
  const ways = el("div", "forge-ways"); ways.setAttribute("role", "tablist");
  for (const [way, icon, name, what] of [["draw", "pen", "Draw", "Draw it on a canvas, then make it 3D."],
    ["image", "image", "Add an image", "Drop or pick a picture, then make it 3D."],
    ["describe", "sparkle", "Describe it", "Say what you want: LOKI draws a picture first (redo it until you like it), then makes it 3D."],
    ["creature", "grid", "Creature", "Paste an anyCreature spec (JSON) and compile it: a skinned, animated creature you judge in the four-view panel."]]) {
    const b = forgeBtn(icon, name, what, () => forgeWay(way), "forge-way");
    b.dataset.way = way; b.setAttribute("role", "tab");
    ways.append(b);
  }
  // the Generate panel (owner 2026-10-21: "improve the ui like you did with the creature ... all those ai gen tools
  // ... organize everything better and more logical"): one tool window with a title bar (fold / float / close, like
  // the Creature Editor), named tabs for the four ways in, the way's own input, then Output and Your models as
  // folds, and the Make button pinned at the bottom.
  for (const b of ways.querySelectorAll(".forge-way")) b.dataset.lab = ({ draw: "Draw", image: "Image", describe: "Describe", creature: "Creature" })[b.dataset.way];   // a label under the icon (CSS ::after)
  side.classList.add("forge-gen");
  side.append(forgeGenBar(side), ways, forgeDrawPane(), forgeImagePane(), forgeDescribePane(), forgeCreaturePane());
  const go = el("div", "forge-go");
  const pick = el("select", "forge-backend"); pick.id = "forge-backend";
  pick.setAttribute("aria-label", "How to make the 3D model");
  for (const [v, t] of [["auto", "Best available"], ["triposr", "TripoSR (this computer)"], ["online", "Online Space"], ["lift", "Offline lift (instant)"]]) {
    const o = el("option", "", t); o.value = v; pick.append(o);
  }
  pick.addEventListener("change", () => { forge.backend = pick.value; forgeOutputState(); });
  const make = el("button", "send forge-make", "Make 3D"); make.type = "button"; make.id = "forge-make";
  make.addEventListener("click", forgeMake);
  go.append(pick, make);
  const out = document.createElement("details"); out.className = "forge-output"; out.id = "forge-output";
  const sum = document.createElement("summary"); sum.textContent = "Output";
  const outBody = el("div", "forge-output-body"); outBody.id = "forge-output-body";
  out.append(sum, outBody);
  try { out.open = localStorage.getItem(FORGE_STORE + "-open") === "1"; } catch (_) { /* private mode */ }
  out.addEventListener("toggle", () => { try { localStorage.setItem(FORGE_STORE + "-open", out.open ? "1" : "0"); } catch (_) { /* */ } });
  const prog = el("div", "forge-progress"); prog.id = "forge-progress"; prog.hidden = true;
  prog.append(el("span", "forge-stage-text"), el("div", "forge-bar"));
  prog.lastChild.append(el("i"));
  const listHead = el("div", "forge-sub", "Your models");
  const list = el("div", "forge-models"); list.id = "forge-models";
  const models = document.createElement("details"); models.className = "forge-gen-models"; models.open = !forgeGenUi().modelsShut;
  const msum = el("summary", "forge-gen-sum"); msum.append(listHead);
  models.append(msum, list);
  models.addEventListener("toggle", () => forgeGenUi({ modelsShut: !models.open }));
  go.classList.add("forge-gen-foot");
  side.append(out, prog, models, go);
  setTimeout(() => { if (forgeGenUi().floating) forgeGenDock("float"); if (forgeGenUi().folded) side.classList.add("folded"); }, 0);
  return side;
}

const FORGE_GEN_UI = "loki-forge-genui";
function forgeGenUi(patch) {
  let ui = {};
  try { ui = JSON.parse(localStorage.getItem(FORGE_GEN_UI) || "{}") || {}; } catch (_) { ui = {}; }
  if (patch) { Object.assign(ui, patch); try { localStorage.setItem(FORGE_GEN_UI, JSON.stringify(ui)); } catch (_) { /* private mode */ } }
  return ui;
}
function forgeGenBar(side) {
  const bar = el("div", "forge-gen-bar");
  const fold = forgeBtn("chevron", "Fold", "Fold the Generate panel to its title bar.", () => forgeGenDock(side.classList.contains("folded") ? "unfold" : "fold"), "forge-gen-fold");
  const title = el("span", "forge-gen-title", "Generate");
  const what = el("span", "forge-gen-what", ""); what.id = "forge-gen-what";
  const flo = forgeBtn("popout", "Float", "Float the Generate panel over the viewport (drag it by this bar), or dock it back.", () => forgeGenDock(side.classList.contains("floating") ? "dock" : "float"), "forge-gen-float");
  const x = forgeBtn("close", "Close", "Close the Generate panel (Windows > Generate panel, or Create > Draw it / From an image / Describe it / Creature brings it back).", () => forgeGenDock("close"), "forge-gen-close");
  bar.append(fold, title, what, flo, x);
  bar.addEventListener("dblclick", (e) => { if (!e.target.closest("button")) forgeGenDock(side.classList.contains("folded") ? "unfold" : "fold"); });
  bar.addEventListener("pointerdown", (e) => {
    if (!side.classList.contains("floating") || e.target.closest("button")) return;
    const r = side.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
    bar.setPointerCapture(e.pointerId);
    const mv = (ev) => { side.style.left = Math.max(0, Math.min(window.innerWidth - 120, ev.clientX - dx)) + "px"; side.style.top = Math.max(0, Math.min(window.innerHeight - 30, ev.clientY - dy)) + "px"; };
    const up = () => { bar.removeEventListener("pointermove", mv); bar.removeEventListener("pointerup", up); const q = side.getBoundingClientRect(); forgeGenUi({ pos: [Math.round(q.left), Math.round(q.top)] }); };
    bar.addEventListener("pointermove", mv); bar.addEventListener("pointerup", up);
  });
  return bar;
}
function forgeGenDock(how) {                  // "fold" | "unfold" | "float" | "dock" | "close"
  const side = document.getElementById("forge-left");
  if (!side) return false;
  if (how === "fold" || how === "unfold") { side.classList.toggle("folded", how === "fold"); forgeGenUi({ folded: how === "fold" }); return true; }
  if (how === "close") { if (typeof forgeProPanel === "function") forgeProPanel("create", false); else side.hidden = true; forgeSay("Generate panel closed - Windows > Generate panel brings it back."); return true; }
  const panel = document.querySelector("#forge .forge-panel");
  if (how === "float" && panel) {
    if (!side._home) side._home = { parent: side.parentElement, next: side.nextSibling };
    panel.append(side);
    const pos = forgeGenUi().pos || [Math.round(window.innerWidth * 0.3), 96];
    side.style.left = Math.max(0, Math.min(window.innerWidth - 260, pos[0])) + "px";
    side.style.top = Math.max(0, Math.min(window.innerHeight - 80, pos[1])) + "px";
    side.classList.add("floating"); forgeGenUi({ floating: true });
  } else if (how === "dock" && side._home) {
    side._home.parent.insertBefore(side, side._home.next && side._home.next.parentElement === side._home.parent ? side._home.next : null);
    side.style.left = side.style.top = "";
    side.classList.remove("floating"); forgeGenUi({ floating: false });
  }
  if (forge.view) forge.view.resize();
  return true;
}

// ------------------------------------------------------------------------------------------ Output (modular)
function forgeOutputBackend() {   // which backend the sliders apply to now ("auto" = the first one that is ready)
  if (forge.backend !== "auto") return forge.backend;
  return (forge.order && forge.order[0]) || "lift";
}

function forgeOutputBuild(options) {
  forge.options = options || [];
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(FORGE_STORE) || "{}") || {}; } catch (_) { saved = {}; }
  forge.values = {};
  const body = document.getElementById("forge-output-body");
  if (!body) return;
  body.replaceChildren();
  for (const o of forge.options) {
    forge.values[o.id] = saved[o.id] !== undefined ? saved[o.id] : o.default;
    const row = el("label", "forge-opt"); row.dataset.opt = o.id;
    row.dataset.tipName = o.label; row.dataset.tipWhat = o.what + " (" + o.applies_to.join(", ") + ")";
    const name = el("span", "forge-opt-name", o.label);
    let input;
    const val = el("span", "forge-opt-val");
    if (o.kind === "toggle") {
      input = document.createElement("input"); input.type = "checkbox"; input.checked = !!forge.values[o.id];
      input.addEventListener("change", () => forgeOutputSet(o.id, input.checked));
    } else if (o.kind === "number") {
      input = document.createElement("input"); input.type = "number"; input.min = String(o.min); input.max = String(o.max);
      input.step = String(o.step); input.value = String(forge.values[o.id]);
      input.addEventListener("change", () => forgeOutputSet(o.id, Number(input.value) || 0));
    } else {
      input = document.createElement("input"); input.type = "range"; input.min = String(o.min); input.max = String(o.max);
      input.step = String(o.step); input.value = String(forge.values[o.id]);
      val.textContent = String(forge.values[o.id]);
      input.addEventListener("input", () => { val.textContent = input.value; forgeOutputSet(o.id, Number(input.value)); });
    }
    input.setAttribute("aria-label", o.label);
    input.dataset.opt = o.id;
    row.append(name, input, val);
    body.append(row);
  }
  const reset = el("button", "quiet small", "Defaults"); reset.type = "button";
  reset.addEventListener("click", () => { try { localStorage.removeItem(FORGE_STORE); } catch (_) { /* */ } forgeOutputBuild(forge.options); });
  body.append(reset);
  forgeOutputState();
}

function forgeOutputSet(id, value) {
  forge.values[id] = value;
  try { localStorage.setItem(FORGE_STORE, JSON.stringify(forge.values)); } catch (_) { /* private mode: not remembered */ }
}

function forgeOutputState() {   // grey out what the current backend ignores (and the picture step when there is none)
  const backend = forgeOutputBackend();
  const usesImage = forge.way === "describe";
  for (const row of document.querySelectorAll("#forge-output-body .forge-opt")) {
    const o = forge.options.find((x) => x.id === row.dataset.opt);
    const on = !!o && (o.applies_to.includes(backend) || (usesImage && o.applies_to.includes("image")));
    row.classList.toggle("off", !on);
    row.querySelector("input").disabled = !on;
  }
}

function forgeDrawPane() {
  const pane = el("section", "forge-pane"); pane.dataset.pane = "draw";
  const cv = document.createElement("canvas"); cv.width = 512; cv.height = 512; cv.className = "forge-canvas"; cv.id = "forge-canvas";
  cv.setAttribute("aria-label", "Drawing canvas");
  const d = forge.drawing;
  d.ctx = cv.getContext("2d");
  d.ctx.fillStyle = "#ffffff"; d.ctx.fillRect(0, 0, 512, 512);
  const pos = (e) => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * 512 / r.width, (e.clientY - r.top) * 512 / r.height]; };
  const line = (a, b) => {
    const c = d.ctx;
    c.strokeStyle = d.tool === "eraser" ? "#ffffff" : d.color; c.lineWidth = d.size * (d.tool === "eraser" ? 2 : 1);
    c.lineCap = "round"; c.lineJoin = "round";
    c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(b[0], b[1]); c.stroke();
  };
  cv.addEventListener("pointerdown", (e) => {
    d.hist.push(d.ctx.getImageData(0, 0, 512, 512)); if (d.hist.length > 30) d.hist.shift();
    d.down = true; d.last = pos(e); line(d.last, d.last); cv.setPointerCapture(e.pointerId);
  });
  cv.addEventListener("pointermove", (e) => { if (!d.down) return; const p = pos(e); line(d.last, p); d.last = p; });
  const up = () => { d.down = false; };
  cv.addEventListener("pointerup", up); cv.addEventListener("pointercancel", up);
  const tools = el("div", "forge-tools");
  const brush = forgeBtn("brush", "Brush", "Paint with the colour.", () => setTool("brush"), "on");
  const eraser = forgeBtn("eraser", "Eraser", "Rub out (paints the white background back).", () => setTool("eraser"));
  function setTool(t) { d.tool = t; brush.classList.toggle("on", t === "brush"); eraser.classList.toggle("on", t === "eraser"); }
  const color = document.createElement("input"); color.type = "color"; color.value = d.color; color.className = "forge-color";
  color.setAttribute("aria-label", "Colour"); color.title = "Colour";
  color.addEventListener("input", () => { d.color = color.value; setTool("brush"); });
  const size = document.createElement("input"); size.type = "range"; size.min = "2"; size.max = "60"; size.value = String(d.size);
  size.className = "forge-range"; size.setAttribute("aria-label", "Brush size"); size.title = "Brush size";
  size.addEventListener("input", () => { d.size = +size.value; });
  tools.append(brush, eraser, color, size,
    forgeBtn("undo", "Undo", "Take back the last stroke.", () => { const h = d.hist.pop(); if (h) d.ctx.putImageData(h, 0, 0); }),
    forgeBtn("trash", "Clear", "Start a new drawing.", () => {
      d.hist.push(d.ctx.getImageData(0, 0, 512, 512)); d.ctx.fillStyle = "#ffffff"; d.ctx.fillRect(0, 0, 512, 512);
    }));
  pane.append(cv, tools, el("p", "note", "Draw one thing on the white: a filled shape works best. Its colours become the model's."));
  return pane;
}

function forgeImagePane() {
  const pane = el("section", "forge-pane"); pane.dataset.pane = "image"; pane.hidden = true;
  const drop = el("div", "forge-drop", "Drop a picture here, or click to pick one");
  drop.tabIndex = 0; drop.setAttribute("role", "button");
  const input = document.createElement("input"); input.type = "file"; input.accept = "image/*"; input.hidden = true;
  const img = document.createElement("img"); img.className = "forge-preview"; img.alt = "The picture"; img.hidden = true;
  const take = (file) => {
    if (!file || !/^image\//.test(file.type)) { forgeSay("That is not a picture.", true); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const im = new Image();
      im.onload = () => {   // at most 1536 px on the long side, as PNG (keeps transparency)
        const s = Math.min(1, 1536 / Math.max(im.width, im.height));
        const c = document.createElement("canvas"); c.width = Math.round(im.width * s); c.height = Math.round(im.height * s);
        c.getContext("2d").drawImage(im, 0, 0, c.width, c.height);
        forge.picked = c.toDataURL("image/png"); img.src = forge.picked; img.hidden = false; forgeSay("");
      };
      im.onerror = () => forgeSay("Could not read that picture.", true);
      im.src = reader.result;
    };
    reader.readAsDataURL(file);
  };
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") input.click(); });
  input.addEventListener("change", () => take(input.files && input.files[0]));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); take(e.dataTransfer.files[0]); });
  pane.append(drop, input, img, el("p", "note", "One object on a plain background works best; the background is cut away."));
  return pane;
}

function forgeDescribePane() {
  const pane = el("section", "forge-pane"); pane.dataset.pane = "describe"; pane.hidden = true;
  const box = document.createElement("textarea"); box.id = "forge-prompt"; box.rows = 3; box.className = "forge-prompt";
  box.placeholder = "a cute fox figurine, a treasure chest, a mushroom house...";
  box.setAttribute("aria-label", "Describe what to make");
  const img = document.createElement("img"); img.className = "forge-preview"; img.id = "forge-gen"; img.alt = "The picture LOKI made"; img.hidden = true;
  const row = el("div", "forge-tools");
  const draw = el("button", "quiet small", "Make the picture"); draw.type = "button"; draw.id = "forge-picture";
  draw.addEventListener("click", forgePicture);
  row.append(draw);
  pane.append(box, row, img, el("p", "note", "LOKI draws it first (its image specialist). Redo until you like it, then Make 3D."));
  return pane;
}

function forgeStage() {
  const stage = el("section", "forge-stage"); stage.id = "forge-stage";
  const cv = document.createElement("canvas"); cv.id = "forge-view"; cv.className = "forge-view";
  cv.setAttribute("aria-label", "3D view: drag to turn, wheel to zoom, right-drag to move");
  const empty = el("p", "forge-empty", "Hold Space for every menu. Shift + right-click on empty space: Create (cube, sphere ...). Alt/Option + mouse: the camera.");
  empty.id = "forge-empty";
  const viewBar = el("div", "forge-float forge-viewbar");
  const mode = forgeBtn("sculpt", "Sculpt", "Sculpt mode: shape the model with brushes. Drag off the model still turns it.", () => forgeMode(), "forge-mode");
  mode.id = "forge-mode";
  viewBar.append(mode,
    forgeBtn("move", "Move", "Move, turn or scale the whole model with handles (W/E/R).", () => forge.view && forge.view.toggleTransform(), "forge-transform"),
    forgeBtn("wire", "Wireframe", "Show the mesh's triangles.", (e) => forgeToggle("wire", e.currentTarget)),
    forgeBtn("clay", "Clay", "Plain clay: hide the colours and material to judge the form.", (e) => forgeToggle("clay", e.currentTarget)),
    forgeBtn("sun", "Lighting", "Change the light: studio, warm, cool, soft.", forgeLight),
    forgeBtn("frame", "Frame", "Fit the model in view (F).", () => forge.view && forge.view.frame()),
    forgeBtn("grid", "Quad view", "Front, side, top and the three-quarter view at once - the four views a modeller reads a shape from.",
      () => forgeQuad(!(forge.view && forge.view.quad))));
  const sculpt = el("div", "forge-float forge-sculptbar"); sculpt.id = "forge-sculpt"; sculpt.hidden = true;
  const brushes = el("div", "forge-brushes");
  for (const [id, icon, name, what] of FORGE_BRUSHES) {
    const b = forgeBtn(icon, name, what, () => forgeBrush(id), id === "draw" ? "on" : "");
    b.dataset.brush = id; brushes.append(b);
  }
  const radius = forgeSlider("Radius", "forge-radius", 0.02, 0.4, 0.12, (v) => { if (forge.view) forge.view.brush.radius = v; });
  const strength = forgeSlider("Strength", "forge-strength", 0.05, 1, 0.5, (v) => { if (forge.view) forge.view.brush.strength = v; });
  const sym = forgeBtn("mirror", "Symmetry X", "Mirror every stroke across the middle (left/right).", (e) => {
    if (!forge.view) return; forge.view.brush.symmetry = !forge.view.brush.symmetry; e.currentTarget.classList.toggle("on", forge.view.brush.symmetry);
  }, "on");
  sculpt.append(brushes, radius, strength, sym,
    forgeBtn("undo", "Undo", "Take back the last stroke (Ctrl+Z).", () => forge.view && forge.view.undo()),
    forgeBtn("redo", "Redo", "Do it again (Ctrl+Shift+Z).", () => forge.view && forge.view.redo()),
    forgeBtn("subdivide", "Subdivide", "Split every triangle in four (curved), for finer detail.", () => forge.view && forge.view.subdivide()));
  const out = el("div", "forge-float forge-exportbar"); out.id = "forge-exportbar";   // the menubar commands select this by id
  out.append(forgeBtn("save", "Save .glb", "Save this model (sculpting and material included) as .glb in models/ - any 3D app opens it.", () => forgeSave("glb")),
    forgeBtn("file", "Save .obj", "Save it as .obj in models/ (any 3D app).", () => forgeSave("obj")),
    forgeBtn("export", "Export\u2026", "Export with options: glTF / OBJ / STL (3D printing) / PLY, a unit scale and a name.", () => forgeExportDialog()),
    forgeBtn("folder", "Show in Files", "Open the models folder in Files.", () => {
      if (typeof openFiles === "function") { forgeClose(); openFiles(forge.model ? "models/" + forge.model : undefined); }
    }));
  const model = typeof forgeModelBar === "function" ? forgeModelBar(viewBar) : null;   // forge_model.js
  const quadLabels = el("div", "forge-quad-labels");
  quadLabels.id = "forge-quad-labels"; quadLabels.hidden = true;
  quadLabels.append(el("span", "", "Front"), el("span", "", "Side"), el("span", "", "Top"), el("span", "", "3/4 view"));
  const animBar = el("div", "forge-float forge-animbar"); animBar.id = "forge-anim"; animBar.hidden = true;
  stage.append(cv, empty, viewBar, sculpt, out, quadLabels, animBar);
  if (model) stage.append(model);
  return stage;
}

function forgeSlider(name, id, min, max, value, onInput) {
  const wrap = el("label", "forge-slider");
  wrap.dataset.tipName = name; wrap.dataset.tipWhat = name === "Radius" ? "How big the brush is ([ and ])." : "How hard the brush works.";
  const r = document.createElement("input"); r.type = "range"; r.id = id; r.min = String(min); r.max = String(max); r.step = "0.01";
  r.value = String(value); r.setAttribute("aria-label", name);
  r.addEventListener("input", () => onInput(+r.value));
  wrap.append(el("span", "forge-slider-name", name[0]), r);
  return wrap;
}

// The Creature Editor (owner 2026-10-21: "the creature tab needs a panel so we can hide it, creature tab needs
// rework"): its own panel with a title bar - fold it to the bar, float it over the viewport (drag it by the bar) or
// dock it back, close it (Windows > Creature Editor or Create > Creature brings it back) - and every part of the
// form is a section you can fold (remembered). Its own Make button and Live switch sit at the bottom, so it works
// floating too. Nothing was taken out: the same starters, sliders, coats, colours, name and spec.
const FORGE_CR_UI = FORGE_STORE + "-crui";

function forgeCrUi(patch) {
  let ui = {};
  try { ui = JSON.parse(localStorage.getItem(FORGE_CR_UI) || "{}") || {}; } catch (_) { ui = {}; }
  if (patch) { Object.assign(ui, patch); try { localStorage.setItem(FORGE_CR_UI, JSON.stringify(ui)); } catch (_) { /* private mode */ } }
  return ui;
}
// a foldable section of the editor; its open state is remembered by name
function forgeCrSection(name, ...kids) {
  const d = document.createElement("details");
  d.className = "forge-cr-sec"; d.dataset.sec = name;
  const shut = (forgeCrUi().shut || []).includes(name);
  d.open = !shut;
  const sum = el("summary", "forge-cr-sum");
  sum.append(el("span", "forge-cr-head", name));
  d.append(sum, ...kids);
  d.addEventListener("toggle", () => {
    const list = new Set(forgeCrUi().shut || []);
    if (d.open) list.delete(name); else list.add(name);
    forgeCrUi({ shut: [...list] });
  });
  return d;
}
function forgeCreatureDock(how) {               // "dock" | "float" | "fold" | "unfold" | "close" | "open"
  const pane = document.querySelector('#forge .forge-pane[data-pane="creature"]');
  if (!pane) return false;
  const ui = forgeCrUi();
  if (how === "fold" || how === "unfold") { forgeCrUi({ folded: how === "fold" }); pane.classList.toggle("folded", how === "fold"); return true; }
  if (how === "close") {
    pane.classList.add("closed"); forgeCrUi({ closed: true });
    if (pane.classList.contains("floating")) pane.hidden = true;
    else if (typeof forgeProPanel === "function") forgeProPanel("create", false);
    forgeSay("Creature Editor closed - Windows > Creature Editor (or Create > Creature) brings it back.");
    return true;
  }
  if (how === "open") {
    pane.classList.remove("closed"); forgeCrUi({ closed: false });
    if (!pane.classList.contains("floating") && typeof forgeProPanel === "function") forgeProPanel("create", true);
    forgeWay("creature");
    return true;
  }
  const float = how === "float" ? true : how === "dock" ? false : !!ui.floating;
  const home = document.querySelector("#forge .forge-side");
  const stage = document.querySelector("#forge .forge-panel");
  if (float && stage && pane.parentElement !== stage) {
    pane._home = pane._home || { parent: pane.parentElement, next: pane.nextSibling };
    stage.append(pane);
    const pos = ui.pos || [Math.round(window.innerWidth * 0.62), 90];
    pane.style.left = Math.max(0, Math.min(window.innerWidth - 260, pos[0])) + "px";
    pane.style.top = Math.max(0, Math.min(window.innerHeight - 80, pos[1])) + "px";
  } else if (!float && pane._home && pane.parentElement !== pane._home.parent) {
    pane._home.parent.insertBefore(pane, pane._home.next && pane._home.next.parentElement === pane._home.parent ? pane._home.next : null);
    pane.style.left = pane.style.top = "";
  } else if (!float && home && !home.contains(pane) && !pane._home) home.append(pane);
  pane.classList.toggle("floating", float);
  forgeCrUi({ floating: float });
  return true;
}
function forgeCreatureBar(pane) {
  const bar = el("div", "forge-cr-bar");
  const title = el("span", "forge-cr-title", "Creature Editor");
  const who = el("span", "forge-cr-who", ""); who.id = "forge-creature-who";
  const fold = forgeBtn("chevron", "Fold", "Fold the Creature Editor to its title bar (click again to open it).", () => forgeCreatureDock(pane.classList.contains("folded") ? "unfold" : "fold"), "forge-cr-fold");
  const flo = forgeBtn("popout", "Float", "Float the editor over the viewport (drag it by this bar), or dock it back in the side panel.", () => forgeCreatureDock(pane.classList.contains("floating") ? "dock" : "float"), "forge-cr-float");
  const x = forgeBtn("close", "Close", "Close the Creature Editor (Windows > Creature Editor brings it back).", () => forgeCreatureDock("close"), "forge-cr-close");
  bar.append(fold, title, who, flo, x);
  bar.addEventListener("dblclick", (e) => { if (!e.target.closest("button")) forgeCreatureDock(pane.classList.contains("folded") ? "unfold" : "fold"); });
  bar.addEventListener("pointerdown", (e) => {          // drag the floating editor by its bar
    if (!pane.classList.contains("floating") || e.target.closest("button")) return;
    const r = pane.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
    bar.setPointerCapture(e.pointerId);
    const mv = (ev) => { pane.style.left = Math.max(0, Math.min(window.innerWidth - 120, ev.clientX - dx)) + "px"; pane.style.top = Math.max(0, Math.min(window.innerHeight - 30, ev.clientY - dy)) + "px"; };
    const up = () => { bar.removeEventListener("pointermove", mv); bar.removeEventListener("pointerup", up); const q = pane.getBoundingClientRect(); forgeCrUi({ pos: [Math.round(q.left), Math.round(q.top)] }); };
    bar.addEventListener("pointermove", mv); bar.addEventListener("pointerup", up);
  });
  return bar;
}

function forgeCreaturePane() {
  const pane = el("div", "forge-pane forge-cr-pane"); pane.dataset.pane = "creature"; pane.hidden = true;
  const ui0 = forgeCrUi();
  if (ui0.folded) pane.classList.add("folded");
  pane.append(forgeCreatureBar(pane));
  pane.append(el("p", "note forge-cr-note", "Pick a body plan, shape it with the sliders, give it a coat. Every build is checked "
    + "for you and lands on the nearest build that stands - then it walks."));
  const presets = el("div", "forge-presets"); presets.id = "forge-creature-presets";
  const acts = el("div", "forge-cr-acts");
  acts.append(forgeBtn("sparkle", "Surprise me", "A random body plan and coat (inside the ranges that stand).", () => forgeCreatureRandom()),
    forgeBtn("undo", "Reset", "Back to the starter's own build and coat.", () => forgeCreatureStart(forge.creature && forge.creature.preset)));
  const live = el("label", "forge-cr-live");
  live.dataset.tipName = "Live"; live.dataset.tipWhat = "Rebuild by itself a moment after you stop moving a slider.";
  const liveBox = document.createElement("input"); liveBox.type = "checkbox"; liveBox.id = "forge-creature-live";
  try { liveBox.checked = localStorage.getItem(FORGE_STORE + "-crlive") === "1"; } catch (_) { /* private mode */ }
  liveBox.addEventListener("change", () => { try { localStorage.setItem(FORGE_STORE + "-crlive", liveBox.checked ? "1" : "0"); } catch (_) { /* */ } });
  live.append(liveBox, el("span", "", "Live"));          // sits in the editor's footer, next to Make creature
  const sliders = el("div", "forge-creature-sliders"); sliders.id = "forge-creature-sliders";
  const coats = el("div", "forge-coats"); coats.id = "forge-creature-coats";
  const colors = el("div", "forge-cr-colors"); colors.id = "forge-creature-colors";
  const row = el("label", "forge-cr-name");
  row.dataset.tipName = "Name"; row.dataset.tipWhat = "What the .glb is called in models/.";
  const nm = document.createElement("input"); nm.type = "text"; nm.id = "forge-creature-name"; nm.value = "creature";
  nm.setAttribute("aria-label", "Creature name");
  row.append(el("span", "forge-cr-head", "Name"), nm);
  const adv = document.createElement("details"); adv.className = "forge-advanced";
  adv.append(el("summary", "", "Advanced: edit the spec"));
  const ta = document.createElement("textarea"); ta.id = "forge-creature-spec"; ta.className = "forge-spec";
  ta.setAttribute("aria-label", "anyCreature ACS spec (JSON)"); ta.setAttribute("spellcheck", "false");
  ta.placeholder = '{"height": 1.8, "joints": { ... }, "volumes": [ ... ], "parts": [ ... ]}';
  adv.append(ta);
  // the form, in sections you can fold (the sliders' own groups - Build, Body, Head, Tail - are folds too)
  const body = el("div", "forge-cr-body");
  body.append(forgeCrSection("Starter", presets, acts), forgeCrSection("Shape", sliders),
    forgeCrSection("Coat", coats, colors), forgeCrSection("Export", row, adv));
  // its own Make button and Live switch, so the editor works floating too
  const foot = el("div", "forge-cr-foot");
  const mk = el("button", "send forge-cr-make", "Make creature"); mk.type = "button"; mk.id = "forge-creature-make";
  mk.title = "Build the creature with these settings (it lands in the viewport, rigged, with Walk / Idle).";
  mk.addEventListener("click", () => { if (forge.way !== "creature") forgeWay("creature"); forgeMake(); });
  foot.append(live, mk);
  pane.append(body, foot);
  setTimeout(() => { if (forgeCrUi().floating) forgeCreatureDock("float"); }, 0);
  return pane;
}

// a labelled horizontal slider with its value (the creature form is a column, not the sculpt bar)
function forgeCrSlider(s, value, onInput) {
  const wrap = el("label", "forge-hslider forge-cr-slider");
  wrap.dataset.tipName = s.label; wrap.dataset.tipWhat = s.what || s.label;
  const top = el("span", "forge-hslider-top"), out = el("span", "forge-hslider-val");
  top.append(el("span", "", s.label), out);
  const r = document.createElement("input"); r.type = "range"; r.id = "forge-cr-" + s.id;
  r.min = String(s.min); r.max = String(s.max); r.step = String(s.step || 0.01); r.value = String(value);
  r.setAttribute("aria-label", s.label); r.dataset.cr = s.id;
  const show = () => { const v = +r.value; out.textContent = s.id === "smooth" ? String(Math.round(v)) : (s.id === "size" ? v.toFixed(2) + "x" : Math.round(v * 100) + "%"); };
  show();
  r.addEventListener("input", () => { show(); onInput(+r.value); });
  r.addEventListener("change", () => forgeCreatureChanged());
  r.addEventListener("dblclick", () => { r.value = String(s.value); show(); onInput(+r.value); forgeCreatureChanged(); });   // back to the starter's 1.0
  wrap.append(top, r);
  wrap.setVal = (v) => { r.value = String(v); show(); };
  return wrap;
}

// the form comes FROM the backend (engine/anycreature.schema()): the window draws whatever it is given
async function forgeCreatureBuild() {
  if (forge.creature) return;
  if (forge.creatureLoading) return forge.creatureLoading;
  forge.creatureLoading = (async () => {
    const r = await api("/forge/creature").catch(() => null);
    const box = document.getElementById("forge-creature-presets");
    if (!box) return;
    if (!r || !r.ok) {
      forgeSay("anyCreature is not ready here" + (r && r.node === false ? " (Node is needed)" : "."), true);
      return;
    }
    forge.crSchema = r;
    forge.creature = { preset: "", size: 1, smooth: 50, shape: {}, coat: "", colors: {}, ui: {} };
    box.replaceChildren();
    for (const p of r.presets || []) {
      const b = forgeBtn(p.icon || "models", p.label, p.what, () => forgeCreatureStart(p.id));
      b.dataset.preset = p.id;
      box.append(b);
    }
    const sl = document.getElementById("forge-creature-sliders");
    sl.replaceChildren();
    const groups = new Map();
    for (const s of [...(r.sliders || []), ...(r.shape || [])]) {
      const g = s.group || "Shape";
      if (!groups.has(g)) {
        const grid = el("div", "forge-cr-group");
        const sec = forgeCrSection(g, grid); sec.classList.add("sub");
        groups.set(g, grid); sl.append(sec);
      }
      const isShape = (r.shape || []).includes(s);
      const w = forgeCrSlider(s, s.value, (v) => {
        if (isShape) forge.creature.shape[s.id] = v; else forge.creature[s.id] = v;
      });
      forge.creature.ui[s.id] = w;
      groups.get(g).append(w);
    }
    const coats = document.getElementById("forge-creature-coats");
    coats.replaceChildren();
    for (const c of r.coats || []) {
      const b = el("button", "forge-coat"); b.type = "button"; b.dataset.coat = c.id;
      b.dataset.tipName = c.label + " coat"; b.dataset.tipWhat = ["Paint the whole creature in the", c.label, "palette."].join(" ");
      b.setAttribute("aria-label", c.label + " coat");
      for (const k of ["body", "back", "belly", "head"]) { const i = el("i"); i.style.background = c.colors[k]; b.append(i); }
      b.addEventListener("click", () => { forgeCreatureCoat(c.id); forgeCreatureChanged(); });
      coats.append(b);
    }
    const cols = document.getElementById("forge-creature-colors");
    cols.replaceChildren();
    for (const c of r.colors || []) {
      const wrap = el("label", "forge-cr-swatch");
      wrap.dataset.tipName = c.label; wrap.dataset.tipWhat = c.id === "shadow" ? "The colour the shading fades to at the feet."
        : "The " + c.label.toLowerCase() + " colour.";
      const inp = document.createElement("input"); inp.type = "color"; inp.value = c.value; inp.id = "forge-crc-" + c.id;
      inp.setAttribute("aria-label", c.label);
      inp.addEventListener("input", () => { forge.creature.colors[c.id] = inp.value; forge.creature.coat = ""; forgeCreatureMarks(); });
      inp.addEventListener("change", () => forgeCreatureChanged());
      wrap.append(inp, el("span", "", c.label));
      cols.append(wrap);
    }
    forgeCreatureStart(((r.presets || [])[0] || {}).id || "");
  })();
  await forge.creatureLoading;
  forge.creatureLoading = null;
}

function forgeCreatureMarks() {   // which preset / coat is on
  const c = forge.creature;
  for (const b of document.querySelectorAll("#forge-creature-presets [data-preset]")) b.classList.toggle("on", b.dataset.preset === c.preset);
  for (const b of document.querySelectorAll("#forge-creature-coats [data-coat]")) b.classList.toggle("on", b.dataset.coat === c.coat);
}

function forgeCreatureCoat(id) {
  const c = forge.creature, coat = (forge.crSchema.coats || []).find((x) => x.id === id);
  if (!c || !coat) return;
  c.coat = id;
  c.colors = Object.assign({}, coat.colors);
  for (const [k, v] of Object.entries(c.colors)) { const i = document.getElementById("forge-crc-" + k); if (i) i.value = v; }
  forgeCreatureMarks();
}

function forgeCreatureSet(values) {   // {size, smooth, shape} -> the sliders and the state
  const c = forge.creature;
  for (const [k, v] of Object.entries(values.shape || {})) { c.shape[k] = v; if (c.ui[k]) c.ui[k].setVal(v); }
  for (const k of ["size", "smooth"]) if (values[k] != null) { c[k] = values[k]; if (c.ui[k]) c.ui[k].setVal(values[k]); }
}

// a starter: its skeleton, its own proportions and its coat (the sliders show them)
function forgeCreatureStart(pid) {
  const c = forge.creature, p = ((forge.crSchema && forge.crSchema.presets) || []).find((x) => x.id === pid);
  if (!c || !p) return;
  c.preset = pid;
  const who = document.getElementById("forge-creature-who");
  if (who) who.textContent = p.label || pid;
  const st = p.start || {};
  const smooth = ((forge.crSchema.sliders || []).find((x) => x.id === "smooth") || {}).value || 50;
  forgeCreatureSet({ size: st.size || 1, smooth, shape: st.shape || {} });
  forgeCreatureCoat(st.coat || "");
  forgeCreatureMarks();
  forgeCreatureChanged();
}

function forgeCreatureRandom() {
  const c = forge.creature, sch = forge.crSchema;
  if (!c || !sch) return;
  const rnd = (lo, hi) => lo + Math.random() * (hi - lo);
  const presets = sch.presets || [];
  c.preset = presets[Math.floor(Math.random() * presets.length)].id;
  const shape = {};
  for (const s of sch.shape || []) {   // mostly near the middle: two dice, like a creature, not a glitch
    const t = (Math.random() + Math.random()) / 2;
    shape[s.id] = +(s.min + t * (s.max - s.min)).toFixed(2);
  }
  forgeCreatureSet({ size: +rnd(0.75, 1.3).toFixed(2), shape });
  const coats = sch.coats || [];
  forgeCreatureCoat(coats[Math.floor(Math.random() * coats.length)].id);
  forgeCreatureMarks();
  const nm = document.getElementById("forge-creature-name");
  if (nm && /^creature(-\d+)?$/.test(nm.value)) nm.value = "creature-" + Math.floor(Math.random() * 900 + 100);
  forgeCreatureChanged(true);
}

// Live: rebuild a moment after the last change (a newer change wins; a stale result is dropped)
function forgeCreatureChanged(now) {
  const box = document.getElementById("forge-creature-live");
  if (!box || !box.checked || forge.way !== "creature") return;
  clearTimeout(forge.crTimer);
  forge.crTimer = setTimeout(() => forgeMake(), now ? 0 : 650);
}

// Walk / Idle: a rigged model (a creature) plays its own clips; the bar only shows when it has some
const FORGE_CLIPS = { move: ["play", "Walk", "Play the walk cycle."], idle: ["sparkle", "Idle", "Play the idle: breathing, a look round, the tail."] };
function forgeAnimBar() {
  const bar = document.getElementById("forge-anim"), v = forge.view;
  if (!bar) return;
  const clips = (v && v.anims) || [];
  bar.hidden = !clips.length;
  bar.replaceChildren();
  if (!clips.length) return;
  for (const name of clips) {
    const [icon, label, what] = FORGE_CLIPS[name] || ["play", name[0].toUpperCase() + name.slice(1), "Play the " + name + " clip."];
    const b = forgeBtn(icon, label, what, () => {
      v.playAnim(v.anim === name ? null : name);
      if (v.anim && v.quad) forgeQuad(false);
      forgeAnimBar();
    }, v.anim === name ? "on" : "");
    b.dataset.clip = name;
    bar.append(b);
  }
  if (v.anim) bar.append(forgeBtn("stop", "Stop", "Stop and show the mesh you can sculpt or edit.", () => { v.playAnim(null); forgeAnimBar(); }));
}

function forgeQuad(on) {
  if (!forge.view) return;
  forge.view.setLook("quad", !!on);
  const btn = document.querySelector("#forge .forge-viewbar button[data-tip-name='Quad view']");
  if (btn) btn.classList.toggle("on", !!on);
  const L = document.getElementById("forge-quad-labels");
  if (L) L.hidden = !on;
}

function forgeWay(way) {
  forge.way = way;
  const gw = document.getElementById("forge-gen-what");
  if (gw) gw.textContent = ({ draw: "Draw it", image: "From an image", describe: "Describe it", creature: "Creature" })[way] || "";
  for (const b of document.querySelectorAll("#forge .forge-way")) {
    b.classList.toggle("on", b.dataset.way === way); b.setAttribute("aria-selected", String(b.dataset.way === way));
  }
  for (const p of document.querySelectorAll("#forge .forge-pane")) p.hidden = p.dataset.pane !== way;
  const mk = document.getElementById("forge-make");
  if (mk) mk.textContent = way === "creature" ? "Make creature" : "Make 3D";
  const pick = document.getElementById("forge-backend"), out = document.getElementById("forge-output");
  if (pick) pick.hidden = way === "creature";          // the creature engine is its own backend: no picker, no picture options
  if (out) out.hidden = way === "creature";
  if (way === "creature") {
    forgeCreatureBuild();
    const cp = document.querySelector('#forge .forge-pane[data-pane="creature"]');
    if (cp && cp.classList.contains("closed")) { cp.classList.remove("closed"); forgeCrUi({ closed: false }); }
  }
  forgeOutputState();
}

function forgeSide(id) {
  forge.side = id;
  for (const b of document.querySelectorAll("#forge .forge-tab")) { b.classList.toggle("on", b.dataset.side === id); b.setAttribute("aria-selected", String(b.dataset.side === id)); }
  document.getElementById("forge-left").hidden = id !== "make";
  const mats = document.getElementById("forge-materials");
  mats.hidden = id !== "materials";
  document.querySelector("#forge .forge-body").classList.toggle("mats", id === "materials");
  if (id === "materials" && window.ForgeMaterials && !mats.dataset.ready) {
    mats.dataset.ready = "1";
    window.ForgeMaterials.open(mats, (maps) => forge.view && forge.view.setMaterial(maps)).catch((e) => forgeSay("Materials: " + e.message, true));
  }
  if (typeof forgeProPanelsApply === "function") forgeProPanelsApply();   // the pro workspace decides what shows
  if (forge.view) forge.view.resize();
}

function forgeOpen() {
  forgeBuild();
  if (typeof forgeProChrome === "function") { try { forgeProChrome(); } catch (exc) { console.warn("forge: pro chrome", exc); } }
  const sheet = document.getElementById("forge");
  sheet.hidden = false;
  forgeWay(forge.way);
  forgeSide(forge.side);
  forgeList();
  api("/forge/status").then((r) => {
    if (!r || !r.ok) return;
    forge.order = r.order || [];
    if (r.backends && r.backends.options && !forge.options.length) forgeOutputBuild(r.backends.options);
    forgeOutputState();
    if (r.order) forgeSay("Ready: " + r.order.join(" → ") + (r.backends && !r.backends.triposr ? " (TripoSR: python tools/setup_forge3d.py)" : ""));
  }).catch(() => {});
  forgeViewer().then((v) => { if (v) v.start(); });
}

function forgeClose() {
  const s = document.getElementById("forge");
  if (s) s.hidden = true;
  if (forge.view) forge.view.stop();
}

// ------------------------------------------------------------------------------------------ making
async function forgePoll(id, onDone, onEnd) {
  clearTimeout(forge.jobTimer);
  forge.job = id;
  const prog = document.getElementById("forge-progress");
  prog.hidden = false;
  const tick = async () => {
    const r = await api("/forge/status?id=" + encodeURIComponent(id)).catch(() => null);
    if (forge.job !== id) return;
    if (!r || !r.ok) { prog.hidden = true; forge.job = ""; document.getElementById("forge-make").disabled = false;
      forgeSay((r && r.error) || "Lost the job.", true); if (onEnd) onEnd(); return; }
    prog.querySelector(".forge-stage-text").textContent = r.stage || "";
    prog.querySelector(".forge-bar i").style.width = Math.round((r.progress || 0) * 100) + "%";
    if (!r.done) { forge.jobTimer = setTimeout(tick, 900); return; }
    prog.hidden = true;
    forge.job = "";
    document.getElementById("forge-make").disabled = false;
    const res = r.result || {};
    if (!res.ok) { forgeSay(res.error || "That did not work.", true); if (onEnd) onEnd(); return; }
    onDone(res);
  };
  tick();
}

async function forgePicture() {
  const text = document.getElementById("forge-prompt").value.trim();
  if (!text) { forgeSay("Describe what to make first.", true); return; }
  forgeSay("Drawing the picture…");
  const r = await api("/forge/image", { prompt: text, options: forge.values }).catch(() => null);
  if (!r || !r.ok) { forgeSay((r && r.error) || "Could not start.", true); return; }
  forgePoll(r.id, (res) => {
    forge.imageRel = res.image;
    const img = document.getElementById("forge-gen");
    img.src = "/creations/" + res.image.split("/").map(encodeURIComponent).join("/");
    img.hidden = false;
    document.getElementById("forge-picture").textContent = "Redo the picture";
    forgeSay("Like it? Make 3D. Or redo it.");
  });
}

async function forgeMake() {
  if (forge.way === "creature") {
    await forgeCreatureBuild();
    const name = document.getElementById("forge-creature-name").value.trim() || "creature";
    const spec = document.getElementById("forge-creature-spec").value.trim();
    const c = forge.creature;
    let body;
    if (spec) body = { spec, name };
    else if (c) body = { name, preset: c.preset, size: c.size, smooth: c.smooth, shape: Object.assign({}, c.shape), colors: Object.assign({}, c.colors) };
    else { forgeSay("anyCreature is not ready here.", true); return; }
    if (forge.job) { forge.crPending = true; return; }    // one build at a time: the newest settings go next
    document.getElementById("forge-make").disabled = true;
    forgeSay("Shaping the creature…");
    const r = await api("/forge/creature", body).catch(() => null);
    if (!r || !r.ok) { document.getElementById("forge-make").disabled = false; forgeSay((r && r.error) || "Could not start.", true); return; }
    const done = () => { if (forge.crPending) { forge.crPending = false; forgeMake(); } };
    forgePoll(r.id, (res) => {
      const sized = res.size ? (" It stands " + Number(res.size).toFixed(2) + "x"
        + (res.size_moved ? " (the nearest size that passed every check)" : "") + ".") : "";
      const eased = res.eased ? " Some sliders were eased " + Math.round((res.ease || 0) * 100) + "% back toward the starter so it stands - they show what was used." : "";
      if (res.eased && c && res.shape && !spec) forgeCreatureSet({ shape: res.shape });
      forgeSay("Made " + res.name + "." + sized + eased + " Walk / Idle play it; Frame, sculpt or export it.");
      forgeList();
      forgeLoad(res.name).then(() => { if (!forge.view || !forge.view.anim) forgeQuad(true); forgeAnimBar(); done(); });
    }, done);
    return;
  }
  const body = { backend: forge.backend, options: forge.values };
  if (forge.way === "draw") body.drawing = document.getElementById("forge-canvas").toDataURL("image/png");
  else if (forge.way === "image") {
    if (!forge.picked) { forgeSay("Add a picture first.", true); return; }
    body.drawing = forge.picked;
  } else {
    body.prompt = document.getElementById("forge-prompt").value.trim();
    if (forge.imageRel) body.image = forge.imageRel;
    else if (!body.prompt) { forgeSay("Describe what to make first.", true); return; }
  }
  document.getElementById("forge-make").disabled = true;
  forgeSay("Making the 3D model…");
  const r = await api("/forge/make", body).catch(() => null);
  if (!r || !r.ok) { document.getElementById("forge-make").disabled = false; forgeSay((r && r.error) || "Could not start.", true); return; }
  forgePoll(r.id, (res) => {
    forgeSay("Made " + res.name + " with " + res.backend + (res.backend === "lift" ? " (the offline lift - install TripoSR for real 3D)" : ""));
    forgeList();
    forgeLoad(res.name);
  });
}

async function forgeList() {
  const box = document.getElementById("forge-models");
  if (!box) return;
  const r = await api("/forge/list").catch(() => null);
  box.replaceChildren();
  const items = (r && r.items) || [];
  if (!items.length) { box.append(el("p", "note", "Nothing yet.")); return; }
  for (const it of items.slice(0, 40)) {
    const b = el("button", "forge-model" + (it.name === forge.model ? " on" : ""));
    b.type = "button";
    b.append(el("span", "forge-model-name", it.prompt || it.name.replace(/^\d{8}-\d{6}-/, "").replace(/\.glb$/, "")),
      el("span", "forge-model-meta", [it.backend, it.triangles ? it.triangles.toLocaleString() + " tris" : ""].filter(Boolean).join(" · ")));
    b.title = it.name;
    b.addEventListener("click", () => forgeLoad(it.name));
    box.append(b);
  }
}

async function forgeLoad(name) {
  const v = await forgeViewer();
  if (!v) { forgeSay("3D view is not available here (WebGL).", true); return; }
  const resp = await fetch("/forge/file/" + encodeURIComponent(name), { headers: { Authorization: "Bearer " + state.token } });
  if (!resp.ok) { forgeSay("Could not load " + name, true); return; }
  try {
    await v.load(await resp.arrayBuffer());
    forge.model = name;
    forgeAnimBar();
    document.getElementById("forge-empty").hidden = true;
    for (const b of document.querySelectorAll("#forge .forge-model")) b.classList.toggle("on", b.title === name);
  } catch (exc) {
    forgeSay("Could not read " + name + ": " + exc.message, true);
  }
}


// ------------------------------------------------------------------------------------------ export
// Formats three.js' vendored exporters do not cover (STL for printing, PLY for scan tools) - written here so
// every export is one self-contained file. Geometry comes out of the baked mesh: positions, normals, indices.
function forgeGeomArrays(bake, wantNormals) {
  const g = bake.geometry;
  if (wantNormals) g.computeVertexNormals();
  const p = g.attributes.position;
  if (!p) return { pos: new Float32Array(0), nrm: new Float32Array(0), idx: new Uint32Array(0) };
  const n = p.count, pos = new Float32Array(n * 3), nrm = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    pos[i * 3] = p.getX(i); pos[i * 3 + 1] = p.getY(i); pos[i * 3 + 2] = p.getZ(i);
    if (wantNormals && g.attributes.normal) { nrm[i * 3] = g.attributes.normal.getX(i); nrm[i * 3 + 1] = g.attributes.normal.getY(i); nrm[i * 3 + 2] = g.attributes.normal.getZ(i); }
  }
  let idx;
  if (g.index) idx = Uint32Array.from(g.index.array);
  else { idx = new Uint32Array(n); for (let i = 0; i < n; i++) idx[i] = i; }
  return { pos, nrm, idx };
}

function forgeTriNormal(pos, a, b, c) {
  const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
  const vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
  const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
  const L = Math.hypot(nx, ny, nz) || 1;
  return [nx / L, ny / L, nz / L];
}

// STL: binary (80-byte header + count + 50 bytes a triangle) or the ASCII "solid" text form
function forgeWriteStl(A, ascii, title) {
  const { pos, idx } = A, tri = (idx.length / 3) | 0, num = (v) => (Number.isFinite(v) ? v : 0);
  if (ascii) {
    let out = "solid " + (title || "forge") + "\n";
    for (let t = 0; t < tri; t++) {
      const a = idx[t * 3] * 3, b = idx[t * 3 + 1] * 3, c = idx[t * 3 + 2] * 3, n = forgeTriNormal(pos, a, b, c);
      out += "  facet normal " + n.join(" ") + "\n    outer loop\n";
      for (const o of [a, b, c]) out += "      vertex " + num(pos[o]) + " " + num(pos[o + 1]) + " " + num(pos[o + 2]) + "\n";
      out += "    endloop\n  endfacet\n";
    }
    return new TextEncoder().encode(out + "endsolid " + (title || "forge") + "\n");
  }
  const buf = new ArrayBuffer(84 + tri * 50), dv = new DataView(buf);
  dv.setUint32(80, tri, true);
  let o = 84;
  for (let t = 0; t < tri; t++) {
    const a = idx[t * 3] * 3, b = idx[t * 3 + 1] * 3, c = idx[t * 3 + 2] * 3, n = forgeTriNormal(pos, a, b, c);
    for (const v of [n[0], n[1], n[2]]) { dv.setFloat32(o, num(v), true); o += 4; }
    for (const p of [a, b, c]) for (let k = 0; k < 3; k++) { dv.setFloat32(o, num(pos[p + k]), true); o += 4; }
    dv.setUint16(o, 0, true); o += 2;
  }
  return new Uint8Array(buf);
}

// PLY: binary little-endian, xyz + normals per vertex and a per-face index list
function forgeWritePly(A, title) {
  const { pos, nrm, idx } = A, n = pos.length / 3, tri = (idx.length / 3) | 0;
  let h = "ply\nformat binary_little_endian 1.0\ncomment made by Forge\ncomment " + (title || "forge") + "\n";
  h += "element vertex " + n + "\nproperty float x\nproperty float y\nproperty float z\nproperty float nx\nproperty float ny\nproperty float nz\n";
  h += "element face " + tri + "\nproperty list uchar uint vertex_indices\nend_header\n";
  const head = new TextEncoder().encode(h), vbytes = n * 24, fbytes = tri * 13;
  const out = new Uint8Array(head.length + vbytes + fbytes);
  out.set(head, 0);
  const dv = new DataView(out.buffer, head.length, vbytes + fbytes);
  let o = 0;
  for (let i = 0; i < n; i++) {
    for (let k = 0; k < 3; k++) { dv.setFloat32(o, pos[i * 3 + k], true); o += 4; }
    for (let k = 0; k < 3; k++) { dv.setFloat32(o, nrm[i * 3 + k] || 0, true); o += 4; }
  }
  for (let t = 0; t < tri; t++) {
    out[head.length + o] = 3; o += 1;
    dv.setUint32(o, idx[t * 3], true); dv.setUint32(o + 4, idx[t * 3 + 1], true); dv.setUint32(o + 8, idx[t * 3 + 2], true); o += 12;
  }
  return out;
}

// the Export options dialog: format, name, a unit scale, and the STL text mode. One button exports it.
const forgeExport = { fmt: "glb", scale: "1", stlAscii: false, dlg: null };
const FORGE_EXPORT_FMTS = [
  ["glb", "glTF (.glb)", "Binary glTF - geometry, vertex colours and the material in one file (any 3D app)."],
  ["obj", "Wavefront (.obj)", "Geometry only - the format every tool reads."],
  ["stl", "STL (.stl)", "Faceted triangles with per-face normals, for 3D printing and CAD."],
  ["ply", "PLY (.ply)", "Binary point/face file with normals - what scan and print tools expect."],
];
function forgeExportDialog() {
  const host = document.getElementById("forge");
  if (!host) return;
  if (!forge.view || !forge.view.sm) { forgeSay("Make or open a model first.", true); return; }
  let dlg = forgeExport.dlg;
  if (!dlg) {
    dlg = el("div", "forge-float forge-exportdlg"); dlg.id = "forge-exportdlg";
    const head = el("div", "fx-head"); head.append(el("b", "", "Export"));
    const x = el("button", "mini forge-btn", "\u00d7"); x.type = "button"; x.dataset.icon = "close"; x.dataset.tipName = "Close";
    x.addEventListener("click", () => { dlg.hidden = true; });
    head.append(x);
    const fmts = el("div", "fx-fmts"); fmts.id = "forge-export-fmts";
    for (const [id, label, what] of FORGE_EXPORT_FMTS) {
      const b = forgeBtn(id, label, what, () => { forgeExport.fmt = id; forgeExportRender(); });
      b.dataset.fmt = id; fmts.append(b);
    }
    const nameRow = el("label", "fx-row"); nameRow.append(el("span", "", "Name"));
    const name = el("input", "fx-name"); name.id = "forge-export-name"; name.type = "text"; name.setAttribute("aria-label", "File name");
    name.addEventListener("input", () => { forgeExport.name = name.value; });
    nameRow.append(name);
    const scaleRow = el("label", "fx-row"); scaleRow.append(el("span", "", "Scale"));
    const scale = el("input", "fx-scale"); scale.id = "forge-export-scale"; scale.type = "number"; scale.min = "0.001"; scale.step = "0.1"; scale.value = "1";
    scale.addEventListener("input", () => { forgeExport.scale = scale.value; });
    scaleRow.append(scale, el("em", "", "model units per metre"));
    const stlRow = el("div", "fx-row fx-stlrow"); stlRow.id = "forge-export-stlrow"; stlRow.append(el("span", "", "STL"));
    for (const [ascii, label] of [[false, "Binary"], [true, "ASCII"]]) {
      const b = forgeBtn("file", label, label + " STL: binary is smaller and exact, ASCII is readable text.", () => { forgeExport.stlAscii = ascii; forgeExportRender(); });
      b.dataset.stl = ascii ? "ascii" : "binary"; stlRow.append(b);
    }
    const info = el("div", "fx-info"); info.id = "forge-export-info";
    const foot = el("div", "fx-foot");
    const cancel = el("button", "mini forge-btn", "Cancel"); cancel.type = "button"; cancel.addEventListener("click", () => { dlg.hidden = true; });
    const go = el("button", "mini forge-btn fx-go", "Export"); go.type = "button"; go.id = "forge-export-go";
    go.addEventListener("click", () => { dlg.hidden = true; forgeSave(forgeExport.fmt === "stl" && forgeExport.stlAscii ? "stl-ascii" : forgeExport.fmt, { scale: forgeExport.scale }); });
    foot.append(cancel, go);
    dlg.append(head, fmts, nameRow, scaleRow, stlRow, info, foot);
    host.append(dlg);
    forgeExport.dlg = dlg;
  }
  const sm = forge.view.sm;
  forgeExport.name = (forgeExport.name || "").trim() || (forge.model || "model.glb").replace(/\.(glb|gltf|obj|stl|ply)$/i, "").replace(/-sculpt(-\d+)?$/, "") + "-sculpt";
  document.getElementById("forge-export-name").value = forgeExport.name;
  dlg.hidden = false;
  forgeExportRender();
}
function forgeExportRender() {
  const dlg = forgeExport.dlg || document.getElementById("forge-exportdlg");
  if (!dlg) return;
  const fmt = forgeExport.fmt;
  dlg.querySelectorAll("[data-fmt]").forEach((b) => b.classList.toggle("on", b.dataset.fmt === fmt));
  dlg.querySelectorAll("[data-stl]").forEach((b) => b.classList.toggle("on", (b.dataset.stl === "ascii") === !!forgeExport.stlAscii));
  const stlRow = document.getElementById("forge-export-stlrow");
  if (stlRow) stlRow.style.display = fmt === "stl" ? "" : "none";
  const info = document.getElementById("forge-export-info");
  const sm = forge.view && forge.view.sm;
  if (info && sm) {
    const tris = (sm.idx ? sm.idx.length : 0) / 3 | 0;
    info.textContent = (sm.n || 0).toLocaleString() + " vertices, " + tris.toLocaleString() + " triangles  \u00b7  scale " + (forgeExport.scale || "1");
  }
}

async function forgeSave(kind, opts) {
  opts = opts || {};
  if (!forge.view || !forge.view.sm) { forgeSay("Nothing to save yet.", true); return; }
  const ext = kind === "stl-ascii" ? "stl" : kind;
  const given = opts.name || forgeExport.name;
  const stem = (given && given.trim() ? given.trim() : (forge.model || "model.glb").replace(/\.(glb|gltf|obj|stl|ply)$/i, "").replace(/-sculpt(-\d+)?$/, "") + "-sculpt")
    .replace(/\.(glb|gltf|obj|stl|ply)$/i, "").replace(/[^\w.-]+/g, "_") || "model";
  const base = stem + "." + ext;
  let data;
  try { data = await forge.view.exportFile(kind, opts); } catch (exc) { forgeSay("Export failed: " + exc.message, true); return; }
  const resp = await fetch("/forge/save?name=" + encodeURIComponent(base), {
    method: "POST", headers: { Authorization: "Bearer " + state.token, "Content-Type": "application/octet-stream" }, body: data,
  }).catch(() => null);
  const r = resp ? await resp.json().catch(() => ({})) : {};
  if (!r.ok) { forgeSay(r.error || "Could not save.", true); return; }
  forgeSay("Saved " + r.path);
  if (kind === "glb") forge.model = r.name;
  forgeList();
}

// ------------------------------------------------------------------------------------------ the sculpt mesh
// Sculpt mesh (sm): raw vertex arrays as the GPU sees them (pos, nrm, col, uv, idx) plus a "welded" view
// (wid: raw -> welded id; wpos/wnrm per welded vertex; adjacency = SculptGL's vertex ring), so a UV seam never
// tears when sculpted. Built from a three.js BufferGeometry (GLTFLoader's) and back.
function forgeMeshFrom(pos, col, uv, idx, given) {
  const n = pos.length / 3;
  const sm = { n, pos, nrm: new Float32Array(n * 3), col, uv, idx };
  forgeWeld(sm, given);
  forgeNormals(sm);
  return sm;
}

// given: a known raw -> welded map (a poly mesh's corners already know their vertex), else weld by position
function forgeWeld(sm, given) {
  const { n, pos } = sm;
  let wid, first;
  if (given) {
    wid = Int32Array.from(given);
    first = [];
    for (let i = 0; i < n; i++) if (first[wid[i]] === undefined) first[wid[i]] = i;
  } else {
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], pos[i * 3 + k]); hi[k] = Math.max(hi[k], pos[i * 3 + k]); }
    const q = 1e5 / Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2], 1e-9);
    const map = new Map();
    wid = new Int32Array(n); first = [];
    for (let i = 0; i < n; i++) {
      const key = Math.round(pos[i * 3] * q) + "," + Math.round(pos[i * 3 + 1] * q) + "," + Math.round(pos[i * 3 + 2] * q);
      let w = map.get(key);
      if (w === undefined) { w = first.length; map.set(key, w); first.push(i); }
      wid[i] = w;
    }
  }
  const wn = first.length, wpos = new Float32Array(wn * 3);
  for (let w = 0; w < wn; w++) if (first[w] !== undefined) for (let k = 0; k < 3; k++) wpos[w * 3 + k] = pos[first[w] * 3 + k];
  sm.wid = wid; sm.wn = wn; sm.wpos = wpos; sm.wnrm = new Float32Array(wn * 3);
  // the one-ring of every welded vertex, as flat typed arrays (count, fill, then drop repeats with a stamp per
  // vertex) - the old array + Set per vertex was most of a commit on a big cage (~90 ms of 400 on 70k faces)
  const idx = sm.idx, nt = idx.length;
  const deg = new Int32Array(wn + 1);
  for (let t = 0; t < nt; t += 3) { deg[wid[idx[t]]] += 2; deg[wid[idx[t + 1]]] += 2; deg[wid[idx[t + 2]]] += 2; }
  const at = new Int32Array(wn + 1);
  for (let w = 0; w < wn; w++) at[w + 1] = at[w] + deg[w];
  const raw = new Int32Array(at[wn]), fill = at.slice(0, wn);
  for (let t = 0; t < nt; t += 3) {
    const a = wid[idx[t]], b = wid[idx[t + 1]], c = wid[idx[t + 2]];
    raw[fill[a]++] = b; raw[fill[a]++] = c; raw[fill[b]++] = a; raw[fill[b]++] = c; raw[fill[c]++] = a; raw[fill[c]++] = b;
  }
  const stamp = new Int32Array(wn), start = new Int32Array(wn + 1), adj = new Int32Array(at[wn]);
  let o = 0;
  for (let w = 0; w < wn; w++) {
    start[w] = o;
    const mark = w + 1;
    stamp[w] = mark;                                  // never itself
    for (let q = at[w]; q < at[w + 1]; q++) { const x = raw[q]; if (stamp[x] !== mark) { stamp[x] = mark; adj[o++] = x; } }
  }
  start[wn] = o;
  sm.adjStart = start; sm.adj = adj.slice(0, o);
}

function forgeSync(sm) {   // welded positions -> raw positions
  const { pos, wpos, wid, n } = sm;
  for (let i = 0; i < n; i++) { const w = wid[i] * 3; pos[i * 3] = wpos[w]; pos[i * 3 + 1] = wpos[w + 1]; pos[i * 3 + 2] = wpos[w + 2]; }
}

function forgeNormals(sm) {
  const { wpos, wnrm, wid, idx, nrm, n } = sm;
  wnrm.fill(0);
  for (let t = 0; t < idx.length; t += 3) {
    const a = wid[idx[t]] * 3, b = wid[idx[t + 1]] * 3, c = wid[idx[t + 2]] * 3;
    const ux = wpos[b] - wpos[a], uy = wpos[b + 1] - wpos[a + 1], uz = wpos[b + 2] - wpos[a + 2];
    const vx = wpos[c] - wpos[a], vy = wpos[c + 1] - wpos[a + 1], vz = wpos[c + 2] - wpos[a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    for (const v of [a, b, c]) { wnrm[v] += nx; wnrm[v + 1] += ny; wnrm[v + 2] += nz; }
  }
  for (let w = 0; w < wnrm.length; w += 3) {
    const l = Math.hypot(wnrm[w], wnrm[w + 1], wnrm[w + 2]) || 1;
    wnrm[w] /= l; wnrm[w + 1] /= l; wnrm[w + 2] /= l;
  }
  for (let i = 0; i < n; i++) { const w = wid[i] * 3; nrm[i * 3] = wnrm[w]; nrm[i * 3 + 1] = wnrm[w + 1]; nrm[i * 3 + 2] = wnrm[w + 2]; }
}

// Subdivide: every triangle -> 4 (SculptGL's halfEdgeSplit midpoints, applied to all edges), then SculptGL's
// tangential smoothing of the new vertices (Subdivision.js: smo.smoothTangent(newVerts, 1.0)) so the surface
// gets rounder instead of only denser.
function forgeSubdivide(sm) {
  const { n, idx, col, uv } = sm;
  const raw = new Map(), extra = [];
  const mid = (i, j) => {
    const key = i < j ? i * 4294967296 + j : j * 4294967296 + i;
    let m = raw.get(key);
    if (m === undefined) { m = n + extra.length; raw.set(key, m); extra.push([i, j]); }
    return m;
  };
  const out = new Uint32Array(idx.length * 4);
  for (let t = 0, o = 0; t < idx.length; t += 3) {
    const a = idx[t], b = idx[t + 1], c = idx[t + 2];
    const ab = mid(a, b), bc = mid(b, c), ca = mid(c, a);
    out.set([a, ab, ca, ab, b, bc, ca, bc, c, ab, bc, ca], o); o += 12;
  }
  const m = n + extra.length;
  const pos = new Float32Array(m * 3); pos.set(sm.pos);
  const ncol = col ? new Float32Array(m * 3) : null; if (ncol) ncol.set(col);
  const nuv = uv ? new Float32Array(m * 2) : null; if (nuv) nuv.set(uv);
  for (let e = 0; e < extra.length; e++) {
    const [i, j] = extra[e], r = n + e;
    for (let k = 0; k < 3; k++) pos[r * 3 + k] = (sm.pos[i * 3 + k] + sm.pos[j * 3 + k]) / 2;
    if (ncol) for (let k = 0; k < 3; k++) ncol[r * 3 + k] = (col[i * 3 + k] + col[j * 3 + k]) / 2;
    if (nuv) for (let k = 0; k < 2; k++) nuv[r * 2 + k] = (uv[i * 2 + k] + uv[j * 2 + k]) / 2;
  }
  const out2 = forgeMeshFrom(pos, ncol, nuv, out);
  // SculptGL Smooth.smoothTangent on the new (welded) vertices: Laplacian, minus its normal part
  const isNew = new Uint8Array(out2.wn);
  for (let r = n; r < m; r++) isNew[out2.wid[r]] = 1;
  forgeSmoothTangent(out2, isNew, 1.0);
  forgeSync(out2); forgeNormals(out2);
  return out2;
}

function forgeSmoothTangent(sm, pick, intensity) {
  const { wpos, wnrm, adjStart, adj, wn } = sm;
  const next = new Float32Array(wpos);
  for (let w = 0; w < wn; w++) {
    if (!pick[w]) continue;
    const a = adjStart[w], b = adjStart[w + 1];
    if (b - a < 3) continue;
    let x = 0, y = 0, z = 0;
    for (let i = a; i < b; i++) { const v = adj[i] * 3; x += wpos[v]; y += wpos[v + 1]; z += wpos[v + 2]; }
    const k = 1 / (b - a);
    let dx = x * k - wpos[w * 3], dy = y * k - wpos[w * 3 + 1], dz = z * k - wpos[w * 3 + 2];
    const d = dx * wnrm[w * 3] + dy * wnrm[w * 3 + 1] + dz * wnrm[w * 3 + 2];
    dx -= wnrm[w * 3] * d; dy -= wnrm[w * 3 + 1] * d; dz -= wnrm[w * 3 + 2] * d;
    next[w * 3] += dx * intensity; next[w * 3 + 1] += dy * intensity; next[w * 3 + 2] += dz * intensity;
  }
  wpos.set(next);
}

// my own small GLB writer: only the fallback when the vendored GLTFExporter cannot load
function forgeWriteGlb(sm) {
  const parts = [], views = [], accessors = [];
  let off = 0;
  const add = (arr, target, comps, ctype, extra) => {
    const bytes = new Uint8Array(arr.buffer, arr.byteOffset, arr.byteLength), pad = (4 - (bytes.length % 4)) % 4;
    parts.push(bytes, new Uint8Array(pad));
    views.push({ buffer: 0, byteOffset: off, byteLength: bytes.length, target });
    off += bytes.length + pad;
    accessors.push(Object.assign({ bufferView: views.length - 1, componentType: ctype, count: arr.length / comps,
      type: { 1: "SCALAR", 2: "VEC2", 3: "VEC3" }[comps] }, extra || {}));
    return accessors.length - 1;
  };
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < sm.pos.length; i++) { lo[i % 3] = Math.min(lo[i % 3], sm.pos[i]); hi[i % 3] = Math.max(hi[i % 3], sm.pos[i]); }
  const attrs = { POSITION: add(sm.pos, 34962, 3, 5126, { min: lo, max: hi }), NORMAL: add(sm.nrm, 34962, 3, 5126) };
  if (sm.col) attrs.COLOR_0 = add(sm.col, 34962, 3, 5126);
  if (sm.uv) attrs.TEXCOORD_0 = add(sm.uv, 34962, 2, 5126);
  const indices = add(sm.idx, 34963, 1, 5125);
  const doc = { asset: { version: "2.0", generator: "LOKI Forge" }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: attrs, indices, material: 0, mode: 4 }] }],
    materials: [{ pbrMetallicRoughness: { baseColorFactor: [1, 1, 1, 1], metallicFactor: 0, roughnessFactor: 0.8 } }],
    accessors, bufferViews: views, buffers: [{ byteLength: off }] };
  const js = new TextEncoder().encode(JSON.stringify(doc)), jpad = (4 - (js.length % 4)) % 4;
  const total = 28 + js.length + jpad + off, out = new Uint8Array(total), dv = new DataView(out.buffer);
  dv.setUint32(0, 0x46546C67, true); dv.setUint32(4, 2, true); dv.setUint32(8, total, true);
  dv.setUint32(12, js.length + jpad, true); dv.setUint32(16, 0x4E4F534A, true);
  out.set(js, 20); out.fill(32, 20 + js.length, 20 + js.length + jpad);
  let o = 20 + js.length + jpad;
  dv.setUint32(o, off, true); dv.setUint32(o + 4, 0x004E4942, true); o += 8;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

// ------------------------------------------------------------------------------------------ the viewer
async function forgeViewer() {
  if (forge.view) return forge.view;
  if (forge.viewLoading) return forge.viewLoading;
  forge.viewLoading = (async () => {
    let lib;
    try {
      const [THREE, gl, ge, oe, oc, tc] = await Promise.all([
        import("/ui/vendor/three/three.module.js"),
        import("/ui/vendor/three/addons/loaders/GLTFLoader.js"),
        import("/ui/vendor/three/addons/exporters/GLTFExporter.js"),
        import("/ui/vendor/three/addons/exporters/OBJExporter.js"),
        import("/ui/vendor/three/addons/controls/OrbitControls.js"),
        import("/ui/vendor/three/addons/controls/TransformControls.js"),
      ]);
      // the manipulator drawn the pro way (app/ui/forge_manip.js); the plain three.js one if that file fails
      let manip = null;
      try { manip = await import("/ui/forge_manip.js"); } catch (exc) { console.warn("forge_manip.js:", exc); }
      lib = { THREE, GLTFLoader: gl.GLTFLoader, GLTFExporter: ge.GLTFExporter, OBJExporter: oe.OBJExporter,
        OrbitControls: oc.OrbitControls, TransformControls: manip && manip.ForgeManip ? manip.ForgeManip : tc.TransformControls,
        TransformControlsPlain: tc.TransformControls };
    } catch (exc) { forgeSay("3D view could not load: " + exc.message, true); return null; }
    const canvas = document.getElementById("forge-view");
    let renderer;
    try { renderer = new lib.THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true }); } catch (_) { return null; }
    forge.view = forgeMakeView(lib, renderer, canvas);
    return forge.view;
  })();
  return forge.viewLoading;
}

function forgeMakeView(lib, renderer, canvas) {
  const { THREE } = lib;
  // sharper (owner 17:06: "make pixels sharper higher density"): the picture is drawn at least 1.5x the screen's
  // pixels on a standard screen (supersampled - thin, crisp edges and lines) and at the full density of a Retina /
  // high-DPI screen up to 3x. Automated test browsers stay at 1x so the suites keep their minute.
  const dpr = window.devicePixelRatio || 1;
  renderer.setPixelRatio(navigator.webdriver ? Math.min(dpr, 2) : Math.min(3, Math.max(1.5, dpr)));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100);
  // the pro default persp camera: up and to the right, looking down at the origin (the reference package's persp sits
  // at 28, 21, 28) - a 3/4 view of the grid, not edge-on from the front (owner 2026-10-21: "just like" the pro tool)
  camera.position.set(28, 21, 28).normalize().multiplyScalar(4.6);
  scene.add(camera);
  const hemi = new THREE.HemisphereLight(0xdfe6f2, 0x2a2e36, 1.0);
  const key = new THREE.DirectionalLight(0xffffff, 2.4); key.position.set(1.2, 1.6, 2);
  const rim = new THREE.DirectionalLight(0x9fb6d8, 1.2); rim.position.set(-2, 0.5, -2);
  scene.add(hemi); camera.add(key, rim);   // the light turns with the camera: the side you look at is lit
  const controls = new lib.OrbitControls(camera, canvas);
  controls.enableDamping = false;   // the pro camera stops the moment the mouse does - no glide (owner: "feel like pro")
  controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
  const holder = new THREE.Group(); scene.add(holder);
  const transform = new lib.TransformControls(camera, canvas);
  // Shift held over a handle: the drag makes a copy and moves it (forge_scene.js) - the manipulator turns orange
  transform.shiftHint = (tc) => (view.mode === "poly" ? "" : "Shift + drag: duplicate the object and " + ({ translate: "move", rotate: "rotate", scale: "scale" }[tc.mode] || "move") + " the copy.");
  transform.addEventListener("dragging-changed", (e) => { controls.enabled = !e.value; });
  transform.addEventListener("change", () => { view.dirty = true; });
  const gizmo = transform.getHelper ? transform.getHelper() : transform;
  scene.add(gizmo);
  const material = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.62, metalness: 0, vertexColors: true });
  const clayColor = new THREE.Color(0xc9b8a8);
  let mesh = null, baseMap = null, matMaps = null, wireMesh = null;
  const wireMat = new THREE.MeshBasicMaterial({ color: 0x0b0e14, wireframe: true, transparent: true, opacity: 0.5, depthWrite: false });
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.92, 1, 48), new THREE.MeshBasicMaterial({ color: 0xbfd4ff, transparent: true,
    opacity: 0.85, depthTest: false, side: THREE.DoubleSide }));
  ring.renderOrder = 10; ring.visible = false; scene.add(ring);
  const view = { THREE, sm: null, mode: "view", brush: { tool: "draw", radius: 0.12, strength: 0.5, symmetry: true, symBits: 1, symModel: false, radial: 0, radialAxis: 1 },   // symBits: 1 X, 2 Y, 4 Z (the core bitmask); symModel: modelling symmetry; radial: N copies about radialAxis
    undoStack: [], redoStack: [], light: 0, running: false, dirty: true, size: 1, quad: false, controls, lib };
  const raycaster = new THREE.Raycaster();

  // Front / side / top / three-quarter at once, orthographic - the four views a modeller reads a shape
  // from, the same four anyCreature's harness/outline.py draws (front, side, top, hero).
  const quadCams = [["front", [0, 0, 1], [0, 1, 0]], ["side", [1, 0, 0], [0, 1, 0]],
                    ["top", [0, 1, 0], [0, 0, -1]], ["hero", [0.62, 0.42, 0.86], [0, 1, 0]]]
    .map(([name, dir, up]) => {
      const c = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.001, 100);
      c.userData = { name, dir: new THREE.Vector3(dir[0], dir[1], dir[2]).normalize() };
      c.up.set(up[0], up[1], up[2]);
      return c;
    });

  function frameQuad() {
    const target = new THREE.Vector3();
    let radius = 1;
    if (mesh) {
      mesh.geometry.computeBoundingSphere();
      const bs = mesh.geometry.boundingSphere;
      radius = bs.radius || 1;
      target.copy(bs.center).applyMatrix4(holder.matrixWorld);
    }
    const aspect = (canvas.clientWidth || 1) / (canvas.clientHeight || 1) || 1;
    const fit = radius * 1.12;
    const hw = fit * Math.max(1, aspect), hh = Math.max(fit, fit / aspect);
    for (const c of quadCams) {
      c.left = -hw; c.right = hw; c.top = hh; c.bottom = -hh;
      const d = radius * 4 + 1;
      c.position.copy(target).addScaledVector(c.userData.dir, d);
      c.near = 0.001; c.far = d * 4 + radius * 4;
      c.lookAt(target);
      c.updateProjectionMatrix();
    }
  }

  function renderQuad() {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    const vw = Math.max(1, Math.floor(w / 2)), vh = Math.max(1, Math.floor(h / 2));
    renderer.setScissorTest(true);
    for (let i = 0; i < quadCams.length; i++) {
      const vx = (i % 2) * vw, vy = (i < 2 ? 1 : 0) * vh;   // front/side on top, top/hero below (WebGL y is up)
      renderer.setViewport(vx, vy, vw, vh);
      renderer.setScissor(vx, vy, vw, vh);
      renderer.render(scene, quadCams[i]);
    }
    renderer.setScissorTest(false);
    renderer.setViewport(0, 0, w, h);
  }

  function resize() {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    if (canvas.width !== Math.round(w * renderer.getPixelRatio()) || canvas.height !== Math.round(h * renderer.getPixelRatio())) {
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); view.dirty = true;
    }
  }
  controls.addEventListener("change", () => { view.dirty = true; });
  view.frameHooks = view.frameHooks || [];
  // wire opacity from the average edge length on screen: full at >= 10 px apart, gone below ~2 px
  view.frameHooks.push(function wireLook() {
    if (!wireMesh || !wireMesh.visible || !view.sm) return;
    const geo = mesh.geometry; if (!geo.boundingSphere) geo.computeBoundingSphere();
    const r = geo.boundingSphere.radius * holder.getWorldScale(new THREE.Vector3()).x, tris = Math.max(1, view.sm.idx.length / 3);
    const edge = Math.sqrt((4 * Math.PI * r * r) * 4 / (Math.sqrt(3) * tris));
    const c = geo.boundingSphere.center.clone().applyMatrix4(mesh.matrixWorld);
    const dist = Math.max(1e-6, camera.position.distanceTo(c) - r * 0.5);
    const px = edge / (2 * dist * Math.tan(camera.fov * Math.PI / 360)) * (canvas.clientHeight || 600);
    const o = Math.max(0, Math.min(1, (px - 2) / 8)) * (view.wireOpacity == null ? 0.55 : view.wireOpacity);
    if (Math.abs(o - wireMat.opacity) > 0.01) { wireMat.opacity = o; wireMesh.visible = o > 0.01 || !!view.wire; view.dirty = true; }
  });      // run before a frame is drawn (the selection wire follows edits)
  const hooks = () => { for (const f of view.frameHooks) { try { f(); } catch (exc) { console.warn("forge: frame hook", exc); } } };
  function loop() {
    if (!view.running) return;
    resize();
    if (view.dirty) hooks();
    if (anim.mixer) { const dt = Math.min(0.1, anim.clock.getDelta()); if (!anim.paused) { anim.mixer.update(dt); view.dirty = true; } }
    if (view.tickTime) view.tickTime();   // the Time Slider's clock (keyframe playback)
    if (view.playing) {                   // the Level workspace's Play / Simulate (forge_level.js): its clock, its camera
      const cam = view.playing.frame() || camera;
      if (cam === camera) controls.update();
      hooks(); renderer.render(scene, cam); view.dirty = false;
    } else if (view.quad) {
      if (view.dirty) { frameQuad(); renderQuad(); view.dirty = false; }
    } else {
      controls.update();
      if (view.dirty) { renderer.render(scene, camera); view.dirty = false; }
    }
    requestAnimationFrame(loop);
  }
  view.resize = () => { view.dirty = true; };
  view.start = () => { if (!view.running) { view.running = true; requestAnimationFrame(loop); } };
  view.stop = () => { view.running = false; };
  view.frame = () => {
    if (!mesh) return;
    mesh.geometry.computeBoundingSphere();
    const bs = mesh.geometry.boundingSphere;
    view.size = bs.radius * 2 || 1;
    // Create never moves the camera (owner 2026-10-25: "the camera focus and moves when i make a new object ...
    // that's a bug"): Maya / Unreal leave the view where it is; f / a frame when you ask
    if (view.keepCameraOnce) { view.keepCameraOnce = false; view.dirty = true; return; }
    controls.target.copy(bs.center).applyMatrix4(holder.matrixWorld);
    const dist = bs.radius / Math.sin((camera.fov * Math.PI) / 360) * 1.15;
    const dir = camera.position.clone().sub(controls.target).normalize();
    camera.position.copy(controls.target).addScaledVector(dir.lengthSq() ? dir : new THREE.Vector3(0, 0.15, 1).normalize(), dist);
    camera.near = dist / 100; camera.far = dist * 100; camera.updateProjectionMatrix();
    controls.update();
    if (view.quad) frameQuad();
    view.dirty = true;
  };

  function geometryOf(sm) {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(sm.pos, 3));
    geo.setAttribute("normal", new THREE.BufferAttribute(sm.nrm, 3));
    if (sm.col) geo.setAttribute("color", new THREE.BufferAttribute(sm.col, 3));
    geo.setAttribute("uv", new THREE.BufferAttribute(sm.uv || forgeBoxUv(sm), 2));
    geo.setIndex(new THREE.BufferAttribute(sm.idx, 1));
    geo.computeBoundingSphere();
    return geo;
  }
  function useMesh(sm, keepView) {
    if (mesh) { holder.remove(mesh); mesh.geometry.dispose(); }
    view.sm = sm;
    mesh = new THREE.Mesh(geometryOf(sm), material);
    mesh.name = "forge";
    wireMesh = new THREE.Mesh(mesh.geometry, wireMat);   // the wire overlay shares the geometry (no copy)
    wireMesh.name = "forge-wire"; wireMesh.visible = !!view.wire; wireMesh.raycast = () => {};
    mesh.add(wireMesh);
    holder.add(mesh);
    applyLook();
    if (!keepView) view.frame();
    view.dirty = true;
  }
  // ---- playing a rigged model's own clips (idle, walk ...) with three.js' AnimationMixer
  const anim = { scene: null, clips: [], mixer: null, clock: new THREE.Clock(), name: null };
  view.anims = [];
  view.anim = null;
  view.playAnim = (name) => {
    if (anim.mixer) { anim.mixer.stopAllAction(); anim.mixer = null; }
    if (anim.scene && anim.scene.parent) anim.scene.parent.remove(anim.scene);
    const clip = name && anim.clips.find((a) => a.name === name);
    view.anim = clip ? clip.name : null;
    if (mesh) mesh.visible = !clip;
    if (clip) {
      holder.add(anim.scene);
      anim.mixer = new THREE.AnimationMixer(anim.scene);
      anim.mixer.clipAction(clip).play();
      anim.clock.getDelta();
    }
    view.dirty = true;
  };
  // the time slider (forge_chrome.js) reads and moves the playing clip
  view.animInfo = () => {
    const clip = view.anim && anim.clips.find((a) => a.name === view.anim);
    return clip && anim.mixer ? { name: clip.name, dur: clip.duration || 1, t: anim.mixer.time % (clip.duration || 1), paused: !!anim.paused } : null;
  };
  view.animSeek = (t) => { if (!anim.mixer) return false; anim.mixer.setTime(Math.max(0, t)); view.dirty = true; return true; };
  view.animPause = (on) => { anim.paused = on == null ? !anim.paused : !!on; anim.clock.getDelta(); return anim.paused; };
  // load a .glb with three.js' own GLTFLoader, then merge every mesh into one sculptable mesh
  view.load = async (buf) => {
    const gltf = await new lib.GLTFLoader().parseAsync(buf, "");
    gltf.scene.updateMatrixWorld(true);
    const P = [], C = [], U = [], I = [];
    let count = 0, map = null, hasUv = false;
    gltf.scene.traverse((o) => { if (o.isMesh && o.geometry.attributes.uv) hasUv = true; });
    gltf.scene.traverse((o) => {
      if (!o.isMesh) return;
      const g = o.geometry, p = g.attributes.position, v = new THREE.Vector3();
      const mat = Array.isArray(o.material) ? o.material[0] : o.material;
      if (!map && mat && mat.map) map = mat.map;
      const tint = mat && mat.color ? mat.color : new THREE.Color(1, 1, 1);
      for (let i = 0; i < p.count; i++) { v.fromBufferAttribute(p, i).applyMatrix4(o.matrixWorld); P.push(v.x, v.y, v.z); }
      const c = g.attributes.color;
      for (let i = 0; i < p.count; i++) C.push(c ? c.getX(i) * tint.r : tint.r, c ? c.getY(i) * tint.g : tint.g, c ? c.getZ(i) * tint.b : tint.b);
      if (hasUv) { const u = g.attributes.uv; for (let i = 0; i < p.count; i++) U.push(u ? u.getX(i) : 0, u ? u.getY(i) : 0); }
      if (g.index) for (let i = 0; i < g.index.count; i++) I.push(g.index.getX(i) + count);
      else for (let i = 0; i < p.count; i++) I.push(i + count);
      count += p.count;
    });
    if (!count) throw new Error("no triangles in it");
    const pos = Float32Array.from(P), box = new THREE.Box3().setFromArray(pos), c = box.getCenter(new THREE.Vector3());
    for (let i = 0; i < pos.length; i += 3) { pos[i] -= c.x; pos[i + 1] -= c.y; pos[i + 2] -= c.z; }
    view.playAnim(null);
    if (anim.scene) { anim.scene.traverse((o) => { if (o.isMesh) o.geometry.dispose(); }); anim.scene = null; }
    // a skinned, animated model (an anyCreature build): keep the rig so Walk / Idle can play it
    let skinned = false;
    gltf.scene.traverse((o) => { if (o.isSkinnedMesh) skinned = true; });
    anim.clips = skinned ? (gltf.animations || []) : [];
    if (anim.clips.length) { anim.scene = gltf.scene; anim.scene.position.set(-c.x, -c.y, -c.z); }
    view.anims = anim.clips.map((a) => a.name);
    view.undoStack = []; view.redoStack = [];
    holder.position.set(0, 0, 0); holder.rotation.set(0, 0, 0); holder.scale.set(1, 1, 1);
    baseMap = map;
    useMesh(forgeMeshFrom(pos, Float32Array.from(C), hasUv ? Float32Array.from(U) : null, Uint32Array.from(I)), false);
  };
  function applyLook() {
    const clay = !!view.clay, m = matMaps;
    material.vertexColors = !clay && !(m && m.albedo) && !!(view.sm && view.sm.col);
    material.map = clay ? null : (m && m.albedo) || (view.sm && view.sm.uv ? baseMap : null);
    material.normalMap = !clay && m ? m.normal : null;
    material.roughnessMap = !clay && m ? m.roughness : null;
    material.metalnessMap = !clay && m ? m.metallic : null;
    material.aoMap = !clay && m ? m.ao : null;
    // the pro default look (view.proShade, on by default): a matte grey lambert1 - no shine - unless the model has its
    // own colours or a material; Lighting > "Studio colours" turns it off (forge_chrome.js)
    const plain = !clay && !m && !material.map && !material.vertexColors;
    const pro = !!view.proShade && plain;
    material.roughness = m ? 1 : (pro ? 1 : 0.62);
    material.metalness = m ? 1 : 0;
    material.color.copy(clay ? clayColor : new THREE.Color(pro ? FORGE_PRO_GREY : 0xffffff));
    // the wire is an overlay that fades as edges get closer than a few pixels on screen (wireLook, every
    // frame), so a dense sculpt never turns solid black; the surface itself stays shaded under it
    material.wireframe = false;
    material.polygonOffset = !!view.wire; material.polygonOffsetFactor = 1; material.polygonOffsetUnits = 1;
    material.needsUpdate = true;
    // matcap (forge_sculpt.js gallery): a lit-sphere look to judge the form, unless the model shows its own maps
    const useCap = !!view.matcapMat && !m && !(material.map) && !material.vertexColors;
    if (mesh) mesh.material = useCap ? view.matcapMat : material;
    if (view.matcapMat) { view.matcapMat.polygonOffset = !!view.wire; view.matcapMat.polygonOffsetFactor = 1; view.matcapMat.polygonOffsetUnits = 1; }
    if (wireMesh) wireMesh.visible = !!view.wire;
    view.dirty = true;
  }
  // Material Maker maps (canvases) -> textures on the model, live
  view.setMaterial = (maps) => {
    if (matMaps) for (const t of Object.values(matMaps)) t.dispose();
    matMaps = null;
    if (maps) {
      matMaps = {};
      for (const [k, cv] of Object.entries(maps)) {
        const t = new THREE.CanvasTexture(cv);
        t.wrapS = t.wrapT = THREE.RepeatWrapping; t.flipY = false;
        if (k === "albedo") t.colorSpace = THREE.SRGBColorSpace;
        matMaps[k] = t;
      }
      // glTF packs roughness in G and metalness in B of one texture: build it so the export is correct
      const rm = document.createElement("canvas"); rm.width = maps.roughness.width; rm.height = maps.roughness.height;
      const ctx = rm.getContext("2d"), w = rm.width, h = rm.height;
      const r = maps.roughness.getContext("2d").getImageData(0, 0, w, h).data, mt = maps.metallic.getContext("2d").getImageData(0, 0, w, h).data;
      const out = ctx.createImageData(w, h);
      for (let i = 0; i < out.data.length; i += 4) { out.data[i] = 255; out.data[i + 1] = r[i]; out.data[i + 2] = mt[i]; out.data[i + 3] = 255; }
      ctx.putImageData(out, 0, 0);
      matMaps.roughness.dispose(); matMaps.metallic.dispose();
      matMaps.roughness = matMaps.metallic = new THREE.CanvasTexture(rm);
      matMaps.roughness.flipY = false; matMaps.roughness.wrapS = matMaps.roughness.wrapT = THREE.RepeatWrapping;
    }
    applyLook();
  };
  view.applyLook = () => applyLook();
  view.setLook = (what, on) => {
    view[what] = on;
    if (what === "quad") { controls.enabled = !on; if (on) frameQuad(); }
    applyLook();
  };
  view.nextLight = () => {
    view.light = (view.light + 1) % FORGE_LIGHTS.length;
    const [name, sky, ground, hi, keyColor, ki] = FORGE_LIGHTS[view.light];
    hemi.color.setHex(sky); hemi.groundColor.setHex(ground); hemi.intensity = hi; key.color.setHex(keyColor); key.intensity = ki;
    view.dirty = true;
    return name;
  };
  view.setMode = (m) => {
    view.mode = m; ring.visible = false; controls.enableRotate = true; view.dirty = true;
    if (m !== "view" && view.anim) { view.playAnim(null); if (typeof forgeAnimBar === "function") forgeAnimBar(); }   // edit the mesh, not the pose
  };
  view.toggleTransform = (mode) => {
    if (!mesh) return;
    if (transform.object && !mode) { transform.detach(); }
    else { transform.attach(holder); transform.setMode(mode || "translate"); }
    for (const b of document.querySelectorAll("#forge .forge-transform")) b.classList.toggle("on", !!transform.object);
    view.dirty = true;
  };
  // export with three.js' own exporters (GLTFExporter binary / OBJExporter); my writer is only the fallback
  view.exportFile = async (kind, opts) => {
    opts = opts || {};
    const sc = Number(opts.scale) > 0 ? Number(opts.scale) : 1;
    const bake = new THREE.Mesh(mesh.geometry.clone(), material.clone());
    bake.geometry.applyMatrix4(holder.matrixWorld);
    if (sc !== 1) bake.geometry.applyMatrix4(new THREE.Matrix4().makeScale(sc, sc, sc));
    const title = ((opts.name || forgeExport.name || "forge").replace(/\.[a-z0-9]+$/i, "").replace(/[^\w.-]+/g, "_") || "forge");
    bake.name = title;
    if (kind === "obj") return new TextEncoder().encode(new lib.OBJExporter().parse(bake));
    if (kind === "stl" || kind === "stl-ascii") return forgeWriteStl(forgeGeomArrays(bake, false), kind === "stl-ascii", title);
    if (kind === "ply") return forgeWritePly(forgeGeomArrays(bake, true), title);
    try {
      const out = await new lib.GLTFExporter().parseAsync(bake, { binary: true, maxTextureSize: 4096 });
      return new Uint8Array(out);
    } catch (exc) {
      console.warn("GLTFExporter failed, using Forge's writer:", exc);
      return forgeWriteGlb(view.sm);
    }
  };

  // what forge_sculpt.js (the native sculpting engine) works with
  view.internals = { THREE, holder, camera, canvas, raycaster, material, useMesh: (sm, keep) => useMesh(sm, keep),
    get mesh() { return mesh; }, refresh: () => refresh(), snapshot: () => snapshot(), applyLook: () => applyLook() };
  // ---- sculpting: SculptGL's tools (src/editing/tools/*.js), on the welded vertices
  // ---- undo / redo: ONE queue for everything (owner 2026-10-21: "the history in forge doesn't work").
  // Every entry is the whole state: the working mesh (its welded vertices, poly cage, construction history) AND the
  // scene (forge_scene.js view.sceneCapture: every object, its transform, pivot, parent, visibility, the selection,
  // which object the tools edit). So Create, Delete, Group, a manipulator drag, a channel typed in, a sculpt stroke and
  // an extrude are all one undo step each, in the order they happened - like the pro tools' undo queue. Switching
  // the object you edit no longer empties the queue. The queue size is a preference (50 by default).
  let wposCache = null;                                  // vertices unchanged since the last entry share one copy
  function wposCopy(sm) {
    const w = sm.wpos, c = wposCache;
    if (c && c.sm === sm && c.arr.length === w.length) {
      let same = true;
      for (let i = 0; i < w.length; i++) if (w[i] !== c.arr[i]) { same = false; break; }
      if (same) return c.arr;
    }
    const arr = w.slice();
    wposCache = { sm: sm, arr: arr };
    return arr;
  }
  function state() {
    const sm = view.sm || null;
    return { sm: sm, wpos: sm && sm.wpos ? wposCopy(sm) : null, poly: view.poly, tri2face: view.tri2face,
      history: window.forgeHistory && window.forgeHistory.snapshot ? window.forgeHistory.snapshot() : null,
      scene: view.sceneCapture ? view.sceneCapture() : null };
  }
  view.undoLimit = (() => { try { return Math.max(5, Math.min(500, +localStorage.getItem("loki-forge-undo-limit") || 50)); } catch (_) { return 50; } })();
  function pushUndo(entry) {
    if (view.undoHold && view.undoHold()) return;       // inside a recorded chunk: the chunk is the one step
    view.undoStack.push(entry);
    while (view.undoStack.length > view.undoLimit) view.undoStack.shift();
    view.redoStack = [];
    if (view.onUndoChange) view.onUndoChange();
  }
  view.undoState = state;                                // forge_scene.js records scene steps with these
  view.pushUndo = pushUndo;
  function snapshot() {
    pushUndo(state());
  }
  function restore(from, to) {
    const snap = from.pop();
    if (!snap) { forgeSay(from === view.undoStack ? "There are no more commands to undo." : "There are no more commands to redo.", true); return false; }
    const back = state(); back.label = snap.label; to.push(back);
    if (snap.label) forgeSay((from === view.undoStack ? "Undo: " : "Redo: ") + snap.label);
    if (snap.scene && view.sceneRestore) view.sceneRestore(snap.scene);
    if (snap.sm) {
      const changed = snap.sm !== view.sm;
      view.poly = snap.poly || null; view.tri2face = snap.tri2face || null;
      if (window.forgeHistory && window.forgeHistory.restore) window.forgeHistory.restore(snap.history || null);
      if (snap.wpos) snap.sm.wpos.set(snap.wpos);
      forgeSync(snap.sm); forgeNormals(snap.sm);
      if (changed) useMesh(snap.sm, true); else refresh();
      if (view.poly) flatNormals(); else view.select([]);
    }
    if (snap.scene && view.sceneRestored) view.sceneRestored(snap.scene);
    wposCache = null;
    view.dirty = true;
    if (view.onChange) view.onChange();
    if (view.onUndoChange) view.onUndoChange();
    return true;
  }
  view.undo = () => restore(view.undoStack, view.redoStack);
  view.redo = () => restore(view.redoStack, view.undoStack);
  view.subdivide = () => {
    if (!view.sm) return;
    if (view.anim) view.playAnim(null);
    if (view.sm.idx.length / 3 > 150000) { forgeSay("Already very detailed (" + (view.sm.idx.length / 3).toLocaleString() + " triangles).", true); return; }
    snapshot();
    view.poly = null; view.select([]);
    useMesh(forgeSubdivide(view.sm), true);
    forgeSay((view.sm.idx.length / 3).toLocaleString() + " triangles");
  };
  function refresh() {
    const g = mesh.geometry;
    g.attributes.position.needsUpdate = true; g.attributes.normal.needsUpdate = true;
    g.computeBoundingSphere(); g.computeBoundingBox();
    view.dirty = true;
  }
  const toLocal = (p) => holder.worldToLocal(p.clone());
  function hitAt(e) {
    if (!mesh) return null;
    // the engine's BVH answers in microseconds; three.js' raycast walks every triangle (slow on dense sculpts)
    const fast = window.ForgeSculpt && window.ForgeSculpt.ready(view) ? window.ForgeSculpt.hit(view, e) : undefined;
    if (fast !== undefined) return fast;
    const r = canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    const hit = raycaster.intersectObject(mesh, false)[0];
    return hit ? { point: toLocal(hit.point), tri: hit.faceIndex } : null;
  }
  // SculptGL picking: the vertices inside the brush sphere
  function picked(c, R2) {
    const { wpos, wn } = view.sm, out = [];
    for (let w = 0; w < wn; w++) {
      const dx = wpos[w * 3] - c.x, dy = wpos[w * 3 + 1] - c.y, dz = wpos[w * 3 + 2] - c.z;
      if (dx * dx + dy * dy + dz * dz < R2) out.push(w);
    }
    return out;
  }
  // SculptBase.areaNormal / areaCenter (front-facing vertices: SculptBase.getFrontVertices)
  function areaNormalCenter(iv) {
    const { wpos, wnrm } = view.sm;
    const eye = camera.getWorldDirection(new THREE.Vector3()).transformDirection(holder.matrixWorld.clone().invert());
    let nx = 0, ny = 0, nz = 0, cx = 0, cy = 0, cz = 0, k = 0;
    for (const w of iv) {
      if (wnrm[w * 3] * eye.x + wnrm[w * 3 + 1] * eye.y + wnrm[w * 3 + 2] * eye.z > 0) continue;
      nx += wnrm[w * 3]; ny += wnrm[w * 3 + 1]; nz += wnrm[w * 3 + 2];
      cx += wpos[w * 3]; cy += wpos[w * 3 + 1]; cz += wpos[w * 3 + 2]; k++;
    }
    const l = Math.hypot(nx, ny, nz);
    if (!l || !k) return null;
    return { n: [nx / l, ny / l, nz / l], c: [cx / k, cy / k, cz / k] };
  }
  // SculptGL's falloff: 3t^4 - 4t^3 + 1 (t = distance / radius)
  const fall = (d) => { const f = d * d; return 3 * f * f - 4 * f * d + 1; };
  function dab(tool, c, negative) {
    const sm = view.sm, v = sm.wpos, nAr = sm.wnrm;
    const radius = view.brush.radius * view.size, r2 = radius * radius, intensity = view.brush.strength;
    const iv = picked(c, r2);
    if (!iv.length) return;
    if (tool === "draw" || tool === "flatten") {   // Brush.js (clay) and Flatten.js: Flatten.flatten() onto a plane
      const a = areaNormalCenter(iv);
      if (!a) return;
      const [anx, any, anz] = a.n;
      let [ax, ay, az] = a.c;
      if (tool === "draw") { const off = radius * 0.1 * (negative ? -1 : 1); ax += anx * off; ay += any * off; az += anz * off; }
      const comp = negative ? -1 : 1;   // Flatten.flatten: only the side of the plane the brush works on
      for (const w of iv) {
        const i = w * 3, vx = v[i], vy = v[i + 1], vz = v[i + 2];
        const toPlane = (vx - ax) * anx + (vy - ay) * any + (vz - az) * anz;
        if (tool === "draw" && toPlane * comp > 0) continue;
        const d = Math.hypot(vx - c.x, vy - c.y, vz - c.z) / radius;
        if (d >= 1) continue;
        const f = fall(d) * toPlane * intensity;
        v[i] -= anx * f; v[i + 1] -= any * f; v[i + 2] -= anz * f;
      }
    } else if (tool === "inflate") {   // Inflate.js
      const k = intensity * radius * 0.1 * (negative ? -1 : 1);
      for (const w of iv) {
        const i = w * 3, d = Math.hypot(v[i] - c.x, v[i + 1] - c.y, v[i + 2] - c.z) / radius;
        if (d >= 1) continue;
        const f = k * fall(d);
        v[i] += nAr[i] * f; v[i + 1] += nAr[i + 1] * f; v[i + 2] += nAr[i + 2] * f;
      }
    } else if (tool === "smooth") {   // Smooth.js + SculptBase.laplacianSmooth
      const { adjStart, adj } = sm, next = new Float32Array(iv.length * 3);
      iv.forEach((w, j) => {
        const a = adjStart[w], b = adjStart[w + 1];
        if (b - a <= 2) { next[j * 3] = v[w * 3]; next[j * 3 + 1] = v[w * 3 + 1]; next[j * 3 + 2] = v[w * 3 + 2]; return; }
        let x = 0, y = 0, z = 0;
        for (let i = a; i < b; i++) { const q = adj[i] * 3; x += v[q]; y += v[q + 1]; z += v[q + 2]; }
        next[j * 3] = x / (b - a); next[j * 3 + 1] = y / (b - a); next[j * 3 + 2] = z / (b - a);
      });
      iv.forEach((w, j) => {
        const i = w * 3, d = Math.hypot(v[i] - c.x, v[i + 1] - c.y, v[i + 2] - c.z) / radius;
        const m = Math.min(1, intensity * Math.max(0, fall(Math.min(1, d)))), keep = 1 - m;
        v[i] = v[i] * keep + next[j * 3] * m; v[i + 1] = v[i + 1] * keep + next[j * 3 + 1] * m; v[i + 2] = v[i + 2] * keep + next[j * 3 + 2] * m;
      });
    } else if (tool === "pinch") {   // Pinch.js
      const k = intensity * 0.05 * (negative ? -1 : 1);
      for (const w of iv) {
        const i = w * 3, dx = c.x - v[i], dy = c.y - v[i + 1], dz = c.z - v[i + 2];
        const f = fall(Math.hypot(dx, dy, dz) / radius) * k;
        v[i] += dx * f; v[i + 1] += dy * f; v[i + 2] += dz * f;
      }
    } else if (tool === "crease") {   // Crease.js
      const a = areaNormalCenter(iv);
      if (!a) return;
      const deform = intensity * 0.07, brushFactor = deform * radius * (negative ? 1 : -1);
      for (const w of iv) {
        const i = w * 3, dx = c.x - v[i], dy = c.y - v[i + 1], dz = c.z - v[i + 2];
        const d = Math.hypot(dx, dy, dz) / radius;
        if (d >= 1) continue;
        let f = fall(d);
        const mod = Math.pow(f, 5) * brushFactor;
        f *= deform;
        v[i] += dx * f + a.n[0] * mod; v[i + 1] += dy * f + a.n[1] * mod; v[i + 2] += dz * f + a.n[2] * mod;
      }
    }
  }
  // every non-empty subset of the active symmetry axes is one mirror instance (the core does the same)
  function symCopies(p, bits) {
    bits = bits | 0; const out = [];
    for (let m = 1; m < 8; m++) {
      if ((m & ~bits) !== 0) continue;
      const sign = [1, 1, 1];
      for (let i = 0; i < 3; i++) if (m & (1 << i)) sign[i] = -1;
      out.push({ p: new THREE.Vector3(p.x * sign[0], p.y * sign[1], p.z * sign[2]), sign: sign });
    }
    return out;
  }
  view.symCopies = (p, bits) => symCopies(new THREE.Vector3(p[0], p[1], p[2]), bits).map((c) => ({ p: c.p.toArray(), sign: c.sign }));
  function stroke(tool, c, negative) {
    dab(tool, c, negative);
    for (const cp of symCopies(c, view.brush.symBits)) dab(tool, cp.p, negative);
    forgeSync(view.sm); forgeNormals(view.sm); refresh();
  }
  // Move.js: the picked vertices and their proxy positions, moved along the mouse's drag in the view plane
  function grabStart(c) {
    const sm = view.sm, R = view.brush.radius * view.size, sel = [];
    const pick = (pt, sign) => { for (const w of picked(new THREE.Vector3(pt.x, pt.y, pt.z), R * R)) sel.push([w, fall(Math.hypot(sm.wpos[w * 3] - pt.x, sm.wpos[w * 3 + 1] - pt.y, sm.wpos[w * 3 + 2] - pt.z) / R), sign]); };
    pick(c, [1, 1, 1]);
    for (const cp of symCopies(c, view.brush.symBits)) pick(cp.p, cp.sign);
    const world = holder.localToWorld(c.clone());
    return { sel, orig: sm.wpos.slice(), plane: new THREE.Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()), world), from: c.clone() };
  }
  function grabMove(g, e) {
    const r = canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    const p = raycaster.ray.intersectPlane(g.plane, new THREE.Vector3());
    if (!p) return;
    const d = toLocal(p).sub(g.from).multiplyScalar(view.brush.strength * 0.6 + 0.4), sm = view.sm;
    for (const [w, f, sign] of g.sel) {
      sm.wpos[w * 3] = g.orig[w * 3] + d.x * sign[0] * f;
      sm.wpos[w * 3 + 1] = g.orig[w * 3 + 1] + d.y * sign[1] * f;
      sm.wpos[w * 3 + 2] = g.orig[w * 3 + 2] + d.z * sign[2] * f;
    }
    forgeSync(sm); forgeNormals(sm); refresh();
  }
  function showRing(hit) {
    if (!hit || view.mode !== "sculpt") { if (ring.visible) { ring.visible = false; view.dirty = true; } return; }
    const en = hit.normal || null;   // the engine's hit carries the surface normal: no scan of every vertex
    const iv = en ? [] : picked(hit.point, (view.brush.radius * view.size) ** 2), a = en ? { n: en } : (iv.length ? areaNormalCenter(iv) : null);
    const n = a ? new THREE.Vector3(...a.n) : new THREE.Vector3(0, 0, 1);
    ring.position.copy(holder.localToWorld(hit.point.clone().addScaledVector(n, view.size * 0.002)));
    ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n.transformDirection(holder.matrixWorld));
    ring.scale.setScalar(view.brush.radius * view.size * holder.getWorldScale(new THREE.Vector3()).x);
    ring.visible = true; view.dirty = true;
  }

  // ---- pointer: in Sculpt mode a left-drag on the model sculpts (OrbitControls keeps everything else)
  let drag = null;
  canvas.addEventListener("pointerdown", (e) => {
    if (view.mode !== "sculpt" || e.button !== 0 || forgeCamMod(e) || transform.dragging) return;   // Alt/Option or Cmd is the camera
    const hit = hitAt(e);
    if (!hit || !view.sm) return;
    e.stopImmediatePropagation();   // OrbitControls does not turn the camera while sculpting
    canvas.setPointerCapture(e.pointerId);
    snapshot();
    view.stroked = true;                // forge_scene.js records the stroke in the history when it ends (T6c)
    if (view.poly) { view.poly = null; view.tri2face = null; view.select([]); }   // sculpted: the poly cage no longer fits
    const tool = e.shiftKey ? "smooth" : view.brush.tool;
    // the native sculpting engine (forge_sculpt.js) runs the stroke when it is loaded; the brushes above are the fallback
    const engine = window.ForgeSculpt && window.ForgeSculpt.ready(view) ? window.ForgeSculpt : null;
    if (engine && engine.press(view, e)) { drag = { engine, last: hit.point.clone() }; return; }
    drag = { tool, negative: e.ctrlKey || e.metaKey, last: hit.point.clone() };
    if (tool === "grab") drag.grab = grabStart(hit.point);
    else stroke(tool, hit.point, drag.negative);
  }, { capture: true });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) { if (view.mode === "sculpt") showRing(hitAt(e)); return; }
    e.stopImmediatePropagation();
    if (drag.engine) { drag.engine.drag(view, e); return; }
    if (drag.grab) { grabMove(drag.grab, e); return; }
    const hit = hitAt(e);
    showRing(hit);
    if (!hit) return;
    // SculptBase.sculptStroke: dabs spaced 0.15 x radius apart along the stroke
    const step = view.brush.radius * view.size * 0.15, dist = hit.point.distanceTo(drag.last);
    if (dist < step) return;
    const n = Math.floor(dist / step);
    for (let i = 1; i <= n; i++) dab(drag.tool, drag.last.clone().lerp(hit.point, i / n), drag.negative);
    for (let i = 1; i <= n; i++) {
      const p = drag.last.clone().lerp(hit.point, i / n);
      for (const cp of symCopies(p, view.brush.symBits)) dab(drag.tool, cp.p, drag.negative);
    }
    forgeSync(view.sm); forgeNormals(view.sm); refresh();
    drag.last.copy(hit.point);
  }, { capture: true });
  const end = () => { if (drag && drag.engine) drag.engine.release(view); drag = null; };
  canvas.addEventListener("pointerup", end); canvas.addEventListener("pointercancel", end);
  canvas.addEventListener("pointerleave", () => { if (!drag) showRing(null); });
  // ---- poly modelling + DynaMesh (app/ui/forge_poly.js, the bar is forge_model.js): a poly mesh shown with hard
  // edges (every face its own corners, so the sculpt weld still joins them), faces picked by click, selection drawn
  // over the model, and every change undoable like a stroke.
  view.poly = null; view.tri2face = null;
  flatNormals.seq = 0;
  function flatNormals(poly) {
    poly = poly || view.poly;
    if (!poly || !view.sm || !view.polyCorners) return;
    const nrm = view.sm.nrm;
    if (poly.hard instanceof Map && poly.f.length >= FORGE_NATIVE_NORMALS_MIN && window.ForgeGeom && ForgeGeom.usable()) {
      // a big cage: flat now (instant), the soft / hard normals from the C++ engine a moment later, off this thread
      // (the JS took ~0.9 s on 98k faces and froze every edit; C++ ~0.17 s in a worker)
      poly.f.forEach((f, fi) => { const n = window.ForgePoly.faceNormal(poly, f), at = view.polyCorners[fi]; for (let k = 0; k < f.length; k++) nrm.set(n, (at + k) * 3); });
      const corners = view.polyCorners, sm = view.sm, want = ++flatNormals.seq;
      ForgeGeom.cornerNormals(poly).then((r) => {
        if (!r || want !== flatNormals.seq || view.sm !== sm || view.polyCorners !== corners) return;
        const out = view.sm.nrm;
        let c = 0;
        poly.f.forEach((f, fi) => { const at = corners[fi]; for (let k = 0; k < f.length; k++, c++) { out[(at + k) * 3] = r.nrm[c * 3]; out[(at + k) * 3 + 1] = r.nrm[c * 3 + 1]; out[(at + k) * 3 + 2] = r.nrm[c * 3 + 2]; } });
        if (mesh) { mesh.geometry.attributes.normal.needsUpdate = true; view.dirty = true; }
      });
      if (mesh) { mesh.geometry.attributes.normal.needsUpdate = true; view.dirty = true; }
      return;
    }
    if (poly.hard instanceof Map && typeof forgeCornerNormals === "function") {
      // soft / hard edges (forge_normals.js, the pro tool's polySoftEdge): a soft edge shares its vertices' normals
      // with the face across it, a hard edge splits them
      const cn = forgeCornerNormals(poly);
      poly.f.forEach((f, fi) => { const at = view.polyCorners[fi]; for (let k = 0; k < f.length; k++) nrm.set(cn[fi][k], (at + k) * 3); });
      if (mesh) { mesh.geometry.attributes.normal.needsUpdate = true; view.dirty = true; }
      return;
    }
    poly.f.forEach((f, fi) => {
      const n = window.ForgePoly.faceNormal(poly, f), at = view.polyCorners[fi];
      for (let k = 0; k < f.length; k++) nrm.set(n, (at + k) * 3);
    });
    if (mesh) { mesh.geometry.attributes.normal.needsUpdate = true; view.dirty = true; }
  }
  view.showPoly = (poly, keepView, noUndo) => {
    if (view.anim) view.playAnim(null);
    anim.clips = []; view.anims = [];          // a poly mesh has no rig
    if (!noUndo && view.sm) snapshot();
    let corners = 0;
    for (const f of poly.f) corners += f.length;
    const pos = new Float32Array(corners * 3), idx = [], tri2face = [], start = [], vid = new Int32Array(corners);
    let c = 0;
    poly.f.forEach((f, fi) => {
      start.push(c);
      for (let k = 0; k < f.length; k++) { pos.set(poly.v[f[k]], (c + k) * 3); vid[c + k] = f[k]; }
      for (let k = 1; k + 1 < f.length; k++) { idx.push(c, c + k, c + k + 1); tri2face.push(fi); }
      c += f.length;
    });
    if (!keepView) { holder.position.set(0, 0, 0); holder.rotation.set(0, 0, 0); holder.scale.set(1, 1, 1); }
    // map UVs (forge_uv.js): a modelling step's new cage keeps the old one's UVs where its faces are still there
    if (window.ForgeUV && keepView && view.poly && view.poly !== poly && !ForgeUV.has(poly) && ForgeUV.has(view.poly) && !poly.uvDropped) {   // a step, not a new object (nor Delete UVs)
      const kept = ForgeUV.carry(view.poly, poly);
      if (kept && kept !== poly) { poly.uv = kept.uv; poly.fuv = kept.fuv; poly.uvNew = kept.uvNew; }
    }
    view.poly = poly; view.tri2face = Int32Array.from(tri2face); view.polyCorners = start;
    view.polyWork = null; view.polyEpoch = (view.polyEpoch || 0) + 1;   // every new cage: previews rebuild (no stale wires)
    const sm = forgeMeshFrom(pos, null, null, Uint32Array.from(idx), vid);   // corners know their vertex: no weld by position
    const cuv = window.ForgeUV ? ForgeUV.cornerUVs(poly) : null;
    if (cuv) sm.uv = cuv;                                                     // one UV per corner: seams for free
    view.polyCorners = start;
    view.sm = sm; flatNormals();
    useMesh(sm, keepView);
    view.select([]);
    if (view.onChange) view.onChange();
  };
  // a poly mesh of the SAME topology as view.poly, shown live (dragging vertices): positions and flat normals
  // only, nothing rebuilt and nothing put on the undo stack - commit with showPoly once the drag is done
  view.polyLive = (work) => {
    if (!view.poly || !view.sm || !view.polyCorners || work.f.length !== view.poly.f.length) return;
    view.polyWork = work === view.poly ? null : work;   // the smooth preview and the wire follow the drag (forge_chrome.js)
    view.polyEpoch = (view.polyEpoch || 0) + 1;
    const { pos, wpos, wid, n } = view.sm;
    work.f.forEach((f, fi) => { const at = view.polyCorners[fi]; for (let k = 0; k < f.length; k++) pos.set(work.v[f[k]], (at + k) * 3); });
    for (let i = 0; i < n; i++) { const w = wid[i] * 3; wpos[w] = pos[i * 3]; wpos[w + 1] = pos[i * 3 + 1]; wpos[w + 2] = pos[i * 3 + 2]; }
    flatNormals(work);
    refresh();
  };
  // the current model as triangles (welded, sculpted shape) - for DynaMesh and "edit as polygons"
  view.triangles = () => {
    if (!view.sm) return null;
    const sm = view.sm, idx = new Uint32Array(sm.idx.length);
    for (let i = 0; i < idx.length; i++) idx[i] = sm.wid[sm.idx[i]];
    return { pos: sm.wpos.slice(), idx };
  };
  // selection, picking, box select, the move tool: app/ui/forge_edit.js (component mode, the pro keys)
  view.selected = [];
  view.select = (faces) => { view.selected = faces.slice(); };   // replaced by forge_edit.js
  if (typeof forgeEditAttach === "function") {
    forgeEditAttach(view, { THREE, lib, canvas, camera, renderer, holder, controls, scene, material,
      mesh: () => mesh, refresh: () => refresh(), hitAt: (e) => hitAt(e) });
  }
  // the pro markings, hotbox, hotkeys and camera: app/ui/forge_pro.js
  if (typeof forgeProAttach === "function") {
    forgeProAttach(view, { THREE, lib, canvas, camera, renderer, holder, controls, scene, material, transform,
      mesh: () => mesh, refresh: () => refresh() });
  }
  // the scene layer (forge_scene.js) hands the tools another object's mesh: plain triangles in the holder's space
  view.setTriangles = (pos, idx, col) => {
    view.poly = null; view.tri2face = null;
    useMesh(forgeMeshFrom(Float32Array.from(pos), col && col.length === pos.length ? Float32Array.from(col) : null, null, Uint32Array.from(idx)), true);
    // the undo queue is kept: its entries hold the whole scene, so switching the edited object is undoable too
  };
  // the pro panels: the perspective camera, or top / front / side. An orthographic view here is the same camera far
  // away with a 1.5-degree lens - it reads as orthographic, and picking, sculpting and the handles keep working.
  const VIEWS = { top: [0, 1, 0.0001], front: [0, 0, 1], side: [1, 0, 0] };
  view.cam = "persp";
  let perspSaved = null;
  view.setView = (name) => {
    if (!VIEWS[name] && name !== "persp") return false;
    const t = controls.target.clone();
    const span = Math.max(view.size || 1, 0.2) * 1.4;
    if (name === "persp") {
      if (view.cam !== "persp" && perspSaved) {
        camera.fov = perspSaved.fov; camera.position.copy(perspSaved.pos); controls.target.copy(perspSaved.target);
      }
      perspSaved = null; controls.enableRotate = true;
    } else {
      if (view.cam === "persp") perspSaved = { fov: camera.fov, pos: camera.position.clone(), target: t.clone() };
      camera.fov = 1.5;
      const d = span / Math.tan((camera.fov * Math.PI) / 360) / 2;
      const dir = new THREE.Vector3(...VIEWS[name]).normalize();
      camera.position.copy(t).addScaledVector(dir, d);
      camera.near = d / 50; camera.far = d * 50;
      controls.enableRotate = false;                       // pro: no tumbling in an orthographic view
    }
    if (name === "persp") { const d = camera.position.distanceTo(controls.target) || 3; camera.near = d / 100; camera.far = d * 100; }
    camera.updateProjectionMatrix(); controls.update();
    view.cam = name; view.dirty = true;
    return true;
  };
  // frame a box (the pro f / a): keep the direction, fit the distance
  view.frameBox = (box) => {
    if (!box || box.isEmpty()) return view.frame();
    const bs = box.getBoundingSphere(new THREE.Sphere());
    const r = Math.max(bs.radius, 1e-3);
    view.size = r * 2;
    controls.target.copy(bs.center);
    const dist = r / Math.sin((camera.fov * Math.PI) / 360) * 1.15;
    const dir = camera.position.clone().sub(controls.target).normalize();
    camera.position.copy(controls.target).addScaledVector(dir.lengthSq() ? dir : new THREE.Vector3(0, 0.15, 1).normalize(), dist);
    camera.near = dist / 100; camera.far = dist * 100; camera.updateProjectionMatrix();
    controls.update();
    view.dirty = true;
  };
  // the pro [ and ]: undo / redo a view change (every camera move that ends is remembered)
  const views = { past: [], future: [], at: null };
  const camState = () => ({ pos: camera.position.clone(), target: controls.target.clone(), fov: camera.fov, cam: view.cam || "persp" });
  controls.addEventListener("start", () => { views.at = camState(); });
  controls.addEventListener("end", () => {
    if (!views.at) return;
    if (views.at.pos.distanceTo(camera.position) > 1e-6 || views.at.target.distanceTo(controls.target) > 1e-6) {
      views.past.push(views.at); if (views.past.length > 50) views.past.shift(); views.future = [];
    }
    views.at = null;
  });
  const goView = (from, to) => {
    const s = from.pop(); if (!s) return false;
    to.push(camState());
    camera.position.copy(s.pos); controls.target.copy(s.target); camera.fov = s.fov;
    view.cam = s.cam || "persp"; controls.enableRotate = view.cam === "persp";   // the view's camera comes back with it
    const d = camera.position.distanceTo(controls.target) || 3; camera.near = d / 100; camera.far = d * 100;
    camera.updateProjectionMatrix(); controls.update(); view.dirty = true;
    return true;
  };
  view.viewUndo = () => goView(views.past, views.future);
  view.viewRedo = () => goView(views.future, views.past);
  view.rememberView = () => { views.past.push(camState()); views.future = []; };
  view.camera = camera;
  view.controls = controls;                          // the Level workspace's Play turns editor navigation off (forge_level.js)
  view.canvas = canvas;
  view.renderer = renderer;                          // the path-traced preview draws with it (app/ui/forge_render.js)
  view.scene = scene;
  view.worldScale = () => holder.getWorldScale(new THREE.Vector3()).x;
  view.dab = (tool, x, y, z, negative) => { snapshot(); stroke(tool, new THREE.Vector3(x, y, z), !!negative); };   // tests / scripts
  view.transform = transform;
  view.holder = holder;
  // the scene: objects, groups and the Outliner (docs/FORGE_PRO.md T1/T2/T3): app/ui/forge_scene.js
  if (typeof forgeSceneAttach === "function") {
    forgeSceneAttach(view, { THREE, scene, holder, material, camera, transform: transform, canvas, controls,
      mesh: () => mesh });
  }
  // the pro Time Slider (keyframes on the transform channels, the playhead and playback): app/ui/forge_anim.js
  if (typeof forgeTimeAttach === "function") {
    try { forgeTimeAttach(view); } catch (exc) { console.warn("forge: time slider", exc); }
  }
  // the Graph Editor (the keyframe curves of the selected object): app/ui/forge_graph.js
  if (typeof forgeGraphAttach === "function") {
    try { forgeGraphAttach(view); } catch (exc) { console.warn("forge: graph editor", exc); }
  }
  // tool previews (the loop an Insert Edge Loop click would make, under the cursor): app/ui/forge_preview.js
  if (typeof forgePreviewAttach === "function") {
    try { forgePreviewAttach(); } catch (exc) { console.warn("forge: tool preview", exc); }
  }
  // the Options panel (the cog): app/ui/forge_options.js
  if (typeof forgeOptionsAttach === "function") {
    try { forgeOptionsAttach(view); } catch (exc) { console.warn("forge: options", exc); }
  }
  // the pro viewport dressing - its panel menu bar, heads-up display, view cube, grid and lighting: app/ui/forge_chrome.js
  view.lights = { hemi, key, rim };
  view.material = material;
  if (typeof forgeProViewportAttach === "function") {
    try { forgeProViewportAttach(view, { THREE, scene, camera, controls, renderer, canvas, holder, material, lights: view.lights }); }
    catch (exc) { console.warn("forge: pro viewport layer", exc); }
  }
  // the scene layer (app/ui/forge_scene.js) bakes geometry - Freeze Transformations, Center Pivot - and
  // needs the aliased buffers pushed back to the GPU afterwards
  view.refreshMesh = () => refresh();
  view.meshObj = () => mesh;                         // the edited object's mesh (the smooth preview hides it)
  return view;
}

// box-projected UVs for a mesh without any (so a procedural material can be shown and exported on it)
function forgeBoxUv(sm) {
  const uv = new Float32Array(sm.n * 2), p = sm.pos, nr = sm.nrm;
  let lo = Infinity, hi = -Infinity;
  for (let i = 0; i < p.length; i++) { lo = Math.min(lo, p[i]); hi = Math.max(hi, p[i]); }
  const s = 1 / Math.max(hi - lo, 1e-6);
  for (let i = 0; i < sm.n; i++) {
    const ax = Math.abs(nr[i * 3]), ay = Math.abs(nr[i * 3 + 1]), az = Math.abs(nr[i * 3 + 2]);
    const [u, v] = ax >= ay && ax >= az ? [p[i * 3 + 2], p[i * 3 + 1]] : ay >= az ? [p[i * 3], p[i * 3 + 2]] : [p[i * 3], p[i * 3 + 1]];
    uv[i * 2] = (u - lo) * s; uv[i * 2 + 1] = (v - lo) * s;
  }
  sm.uv = uv;
  return uv;
}

function forgeMode() {
  const v = forge.view;
  if (!v) return;
  v.setMode(v.mode === "sculpt" ? "view" : "sculpt");
  const mb = document.getElementById("forge-model"); if (mb) mb.hidden = true;   // Model and Sculpt take turns
  document.getElementById("forge-model-mode")?.classList.remove("on");
  if (v.select) v.select([]);
  document.getElementById("forge-sculpt").hidden = v.mode !== "sculpt";
  document.getElementById("forge-mode").classList.toggle("on", v.mode === "sculpt");
  forgeSay(v.mode === "sculpt" ? "Sculpt: drag on the model. Ctrl/Cmd inverts, Shift smooths, hold b and drag for the size, m for the strength; Alt/Option + mouse turns the view." : "");
}

function forgeToggle(what, btn) {
  if (!forge.view) return;
  const on = !forge.view[what];
  forge.view.setLook(what, on);
  btn.classList.toggle("on", on);
}

function forgeLight() { if (forge.view) forgeSay("Light: " + forge.view.nextLight()); }

function forgeBrush(id) {
  if (forge.view) forge.view.brush.tool = id;
  for (const b of document.querySelectorAll("#forge [data-brush]")) b.classList.toggle("on", b.dataset.brush === id);
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("open-forge")?.addEventListener("click", forgeOpen);
  // Forge's keys are one table (forge_keys.js, run by forge_pro.js): the old handler here closed Forge on Esc and
  // gave w / e / r and [ ] second meanings - removed 2026-10-22 (owner: "nothing is used twice")
});
