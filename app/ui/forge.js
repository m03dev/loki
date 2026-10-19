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
  subdivide: '<path d="M12 3.5l8.5 15h-17z"/><path d="M7.75 11h8.5M12 18.5l-4.25-7.5M12 18.5l4.25-7.5"/>',
  save: '<path d="M5 3.5h11l3.5 3.5v13.5H5z"/><path d="M8 3.5v5h7v-5M8 20.5v-6h8v6"/>',
  move: '<path d="M12 3v18M3 12h18"/><path d="M9 6l3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3"/>',
  material: '<circle cx="12" cy="12" r="8.5"/><path d="M5 9.5c4 1.5 10 1.5 14 0M4 14c5 2 11 2 16 0"/>',
  chevron: '<path d="M8 10l4 4 4-4"/>',
});

const forge = { way: "draw", job: "", jobTimer: 0, view: null, model: null, imageRel: "", backend: "auto", side: "make",
  drawing: { ctx: null, hist: [], tool: "brush", color: "#ed782b", size: 14, down: false, last: null }, picked: "",
  options: [], values: {} };
// [id, icon, name, what] - the algorithm of each is SculptGL's (src/editing/tools/<Name>.js), see forgeMakeView
const FORGE_BRUSHES = [
  ["draw", "brush", "Clay", "SculptGL's Brush (clay): build up along the area's plane (Alt/Ctrl digs in)."],
  ["inflate", "inflate", "Inflate", "Swell the surface, each point along its own normal (Alt/Ctrl deflates)."],
  ["smooth", "smooth", "Smooth", "Laplacian smooth toward the neighbours (Shift smooths with any brush)."],
  ["flatten", "flatten", "Flatten", "Press the surface onto the area's plane - planes and hard surfaces."],
  ["grab", "grab", "Grab", "SculptGL's Move: pull a whole area along with the mouse."],
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
    ["materials", "material", "Materials", "Procedural materials with Material Maker's nodes - applied to the model live."]]) {
    const b = forgeBtn(icon, name, what, () => forgeSide(id), "forge-tab"); b.dataset.side = id; b.setAttribute("role", "tab");
    tabs.append(b);
  }
  const status = el("span", "forge-status"); status.id = "forge-status"; status.setAttribute("role", "status");
  head.append(title, tabs, status, forgeBtn("close", "Close", "Close Forge (Esc).", forgeClose));
  const body = el("div", "forge-body");
  body.append(forgeLeft(), forgeStage());
  const mats = el("section", "forge-materials"); mats.id = "forge-materials"; mats.hidden = true;
  body.append(mats);
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
  side.append(ways, forgeDrawPane(), forgeImagePane(), forgeDescribePane(), forgeCreaturePane());
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
  side.append(go, out, prog, listHead, list);
  return side;
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
  const empty = el("p", "forge-empty", "Draw, add a picture or describe something - the model appears here.");
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
  const out = el("div", "forge-float forge-exportbar");
  out.append(forgeBtn("save", "Save .glb", "Save this model (sculpting and material included) as .glb in models/ - Blender, Godot, Maya and the web open it.", () => forgeSave("glb")),
    forgeBtn("file", "Save .obj", "Save it as .obj in models/ (ZBrush, Nomad Sculpt, any 3D app).", () => forgeSave("obj")),
    forgeBtn("folder", "Show in Files", "Open the models folder in Files.", () => {
      if (typeof openFiles === "function") { forgeClose(); openFiles(forge.model ? "models/" + forge.model : undefined); }
    }));
  const model = typeof forgeModelBar === "function" ? forgeModelBar(viewBar) : null;   // forge_model.js
  const quadLabels = el("div", "forge-quad-labels");
  quadLabels.id = "forge-quad-labels"; quadLabels.hidden = true;
  quadLabels.append(el("span", "", "Front"), el("span", "", "Side"), el("span", "", "Top"), el("span", "", "3/4 view"));
  stage.append(cv, empty, viewBar, sculpt, out, quadLabels);
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

function forgeCreaturePane() {
  const pane = el("div", "forge-pane"); pane.dataset.pane = "creature"; pane.hidden = true;
  pane.append(el("p", "note", "Pick a body plan, then make it yours. Every build is checked for you and "
    + "lands on the nearest size that stands - no JSON, no guesswork."));
  const presets = el("div", "forge-presets"); presets.id = "forge-creature-presets";
  const sliders = el("div", "forge-creature-sliders"); sliders.id = "forge-creature-sliders";
  const colors = el("div", "forge-colors"); colors.id = "forge-creature-colors";
  const row = el("label", "forge-slider");
  row.dataset.tipName = "Name"; row.dataset.tipWhat = "What the .glb is called in models/.";
  const nm = document.createElement("input"); nm.type = "text"; nm.id = "forge-creature-name"; nm.value = "creature";
  nm.setAttribute("aria-label", "Creature name");
  row.append(el("span", "forge-slider-name", "N"), nm);
  const adv = document.createElement("details"); adv.className = "forge-advanced";
  adv.append(el("summary", "", "Advanced: edit the spec"));
  const ta = document.createElement("textarea"); ta.id = "forge-creature-spec"; ta.className = "forge-spec";
  ta.setAttribute("aria-label", "anyCreature ACS spec (JSON)"); ta.setAttribute("spellcheck", "false");
  ta.placeholder = '{"height": 1.8, "joints": { ... }, "volumes": [ ... ], "parts": [ ... ]}';
  adv.append(ta);
  pane.append(presets, sliders, colors, row, adv);
  return pane;
}

// the form comes FROM the backend (engine/anycreature.schema()): the window draws whatever it is given
async function forgeCreatureBuild() {
  if (forge.creature) return;
  const r = await api("/forge/creature").catch(() => null);
  const box = document.getElementById("forge-creature-presets");
  if (!box) return;
  if (!r || !r.ok) {
    forgeSay("anyCreature is not ready here" + (r && r.node === false ? " (Node is needed)" : "."), true);
    return;
  }
  forge.creature = { preset: ((r.presets || [])[0] || {}).id || "", colors: {} };
  box.replaceChildren();
  for (const p of r.presets || []) {
    const b = forgeBtn(p.icon || "models", p.label, p.what, () => {
      forge.creature.preset = p.id;
      for (const x of box.children) x.classList.toggle("on", x.dataset.preset === p.id);
    }, p.id === forge.creature.preset ? "on" : "");
    b.dataset.preset = p.id;
    box.append(b);
  }
  const sl = document.getElementById("forge-creature-sliders");
  sl.replaceChildren();
  for (const s of r.sliders || []) {
    sl.append(forgeSlider(s.label, "forge-cr-" + s.id, s.min, s.max, s.value, (v) => { forge.creature[s.id] = v; }));
  }
  const cols = document.getElementById("forge-creature-colors");
  cols.replaceChildren();
  for (const c of r.colors || []) {
    const wrap = el("label", "forge-color");
    wrap.dataset.tipName = c.label; wrap.dataset.tipWhat = c.label;
    const inp = document.createElement("input"); inp.type = "color"; inp.value = c.value; inp.id = "forge-cr-" + c.id;
    inp.setAttribute("aria-label", c.label);
    inp.addEventListener("input", () => { forge.creature.colors[c.id] = inp.value; });
    forge.creature.colors[c.id] = c.value;
    wrap.append(inp, el("span", "", c.label));
    cols.append(wrap);
  }
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
  for (const b of document.querySelectorAll("#forge .forge-way")) {
    b.classList.toggle("on", b.dataset.way === way); b.setAttribute("aria-selected", String(b.dataset.way === way));
  }
  for (const p of document.querySelectorAll("#forge .forge-pane")) p.hidden = p.dataset.pane !== way;
  const mk = document.getElementById("forge-make");
  if (mk) mk.textContent = way === "creature" ? "Make creature" : "Make 3D";
  if (way === "creature") forgeCreatureBuild();
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
  if (forge.view) forge.view.resize();
}

function forgeOpen() {
  forgeBuild();
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
async function forgePoll(id, onDone) {
  clearTimeout(forge.jobTimer);
  forge.job = id;
  const prog = document.getElementById("forge-progress");
  prog.hidden = false;
  const tick = async () => {
    const r = await api("/forge/status?id=" + encodeURIComponent(id)).catch(() => null);
    if (forge.job !== id) return;
    if (!r || !r.ok) { prog.hidden = true; forgeSay((r && r.error) || "Lost the job.", true); return; }
    prog.querySelector(".forge-stage-text").textContent = r.stage || "";
    prog.querySelector(".forge-bar i").style.width = Math.round((r.progress || 0) * 100) + "%";
    if (!r.done) { forge.jobTimer = setTimeout(tick, 900); return; }
    prog.hidden = true;
    forge.job = "";
    document.getElementById("forge-make").disabled = false;
    const res = r.result || {};
    if (!res.ok) { forgeSay(res.error || "That did not work.", true); return; }
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
    let body;
    if (spec) body = { spec, name };
    else if (forge.creature) body = { name, preset: forge.creature.preset, size: forge.creature.size,
      smooth: forge.creature.smooth, colors: forge.creature.colors };
    else { forgeSay("anyCreature is not ready here.", true); return; }
    document.getElementById("forge-make").disabled = true;
    forgeSay("Shaping the creature…");
    const r = await api("/forge/creature", body).catch(() => null);
    if (!r || !r.ok) { document.getElementById("forge-make").disabled = false; forgeSay((r && r.error) || "Could not start.", true); return; }
    forgePoll(r.id, (res) => {
      const sized = res.size ? (" It stands " + Number(res.size).toFixed(2) + "x"
        + (res.size_moved ? " (the nearest size that passed every check)" : "") + ".") : "";
      forgeSay("Made " + res.name + "." + sized + " The four panels show its front, side, top and three-quarter "
        + "views - Frame it, then sculpt it or export it.");
      forgeList();
      forgeLoad(res.name).then(() => forgeQuad(true));
    });
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
    document.getElementById("forge-empty").hidden = true;
    for (const b of document.querySelectorAll("#forge .forge-model")) b.classList.toggle("on", b.title === name);
  } catch (exc) {
    forgeSay("Could not read " + name + ": " + exc.message, true);
  }
}

async function forgeSave(kind) {
  if (!forge.view || !forge.view.sm) { forgeSay("Nothing to save yet.", true); return; }
  const base = (forge.model || "model.glb").replace(/\.glb$/i, "").replace(/-sculpt(-\d+)?$/, "") + "-sculpt." + kind;
  let data;
  try { data = await forge.view.exportFile(kind); } catch (exc) { forgeSay("Export failed: " + exc.message, true); return; }
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
function forgeMeshFrom(pos, col, uv, idx) {
  const n = pos.length / 3;
  const sm = { n, pos, nrm: new Float32Array(n * 3), col, uv, idx };
  forgeWeld(sm);
  forgeNormals(sm);
  return sm;
}

function forgeWeld(sm) {
  const { n, pos } = sm;
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], pos[i * 3 + k]); hi[k] = Math.max(hi[k], pos[i * 3 + k]); }
  const q = 1e5 / Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2], 1e-9);
  const map = new Map(), wid = new Int32Array(n), first = [];
  for (let i = 0; i < n; i++) {
    const key = Math.round(pos[i * 3] * q) + "," + Math.round(pos[i * 3 + 1] * q) + "," + Math.round(pos[i * 3 + 2] * q);
    let w = map.get(key);
    if (w === undefined) { w = first.length; map.set(key, w); first.push(i); }
    wid[i] = w;
  }
  const wn = first.length, wpos = new Float32Array(wn * 3);
  for (let w = 0; w < wn; w++) for (let k = 0; k < 3; k++) wpos[w * 3 + k] = pos[first[w] * 3 + k];
  sm.wid = wid; sm.wn = wn; sm.wpos = wpos; sm.wnrm = new Float32Array(wn * 3);
  const sets = Array.from({ length: wn }, () => []);
  const idx = sm.idx;
  for (let t = 0; t < idx.length; t += 3) {
    const a = wid[idx[t]], b = wid[idx[t + 1]], c = wid[idx[t + 2]];
    sets[a].push(b, c); sets[b].push(a, c); sets[c].push(a, b);
  }
  const start = new Int32Array(wn + 1), flat = [];
  for (let w = 0; w < wn; w++) { start[w] = flat.length; for (const x of new Set(sets[w])) if (x !== w) flat.push(x); }
  start[wn] = flat.length;
  sm.adjStart = start; sm.adj = Int32Array.from(flat);
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
      lib = { THREE, GLTFLoader: gl.GLTFLoader, GLTFExporter: ge.GLTFExporter, OBJExporter: oe.OBJExporter,
        OrbitControls: oc.OrbitControls, TransformControls: tc.TransformControls };
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
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100);
  camera.position.set(0, 0.4, 2.6);
  scene.add(camera);
  const hemi = new THREE.HemisphereLight(0xdfe6f2, 0x2a2e36, 1.0);
  const key = new THREE.DirectionalLight(0xffffff, 2.4); key.position.set(1.2, 1.6, 2);
  const rim = new THREE.DirectionalLight(0x9fb6d8, 1.2); rim.position.set(-2, 0.5, -2);
  scene.add(hemi); camera.add(key, rim);   // the light turns with the camera: the side you look at is lit
  const controls = new lib.OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.dampingFactor = 0.12;
  controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
  const holder = new THREE.Group(); scene.add(holder);
  const transform = new lib.TransformControls(camera, canvas);
  transform.addEventListener("dragging-changed", (e) => { controls.enabled = !e.value; });
  transform.addEventListener("change", () => { view.dirty = true; });
  const gizmo = transform.getHelper ? transform.getHelper() : transform;
  scene.add(gizmo);
  const material = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.62, metalness: 0, vertexColors: true });
  const clayColor = new THREE.Color(0xc9b8a8);
  let mesh = null, baseMap = null, matMaps = null;
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.92, 1, 48), new THREE.MeshBasicMaterial({ color: 0xbfd4ff, transparent: true,
    opacity: 0.85, depthTest: false, side: THREE.DoubleSide }));
  ring.renderOrder = 10; ring.visible = false; scene.add(ring);
  const view = { THREE, sm: null, mode: "view", brush: { tool: "draw", radius: 0.12, strength: 0.5, symmetry: true },
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
  function loop() {
    if (!view.running) return;
    resize();
    if (view.quad) {
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
    holder.add(mesh);
    applyLook();
    if (!keepView) view.frame();
    view.dirty = true;
  }
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
    material.roughness = m ? 1 : 0.62;
    material.metalness = m ? 1 : 0;
    material.color.copy(clay ? clayColor : new THREE.Color(0xffffff));
    material.wireframe = !!view.wire;
    material.needsUpdate = true;
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
  view.setMode = (m) => { view.mode = m; ring.visible = false; controls.enableRotate = true; view.dirty = true; };
  view.toggleTransform = (mode) => {
    if (!mesh) return;
    if (transform.object && !mode) { transform.detach(); }
    else { transform.attach(holder); transform.setMode(mode || "translate"); }
    for (const b of document.querySelectorAll("#forge .forge-transform")) b.classList.toggle("on", !!transform.object);
    view.dirty = true;
  };
  // export with three.js' own exporters (GLTFExporter binary / OBJExporter); my writer is only the fallback
  view.exportFile = async (kind) => {
    const bake = new THREE.Mesh(mesh.geometry.clone(), material.clone());
    bake.geometry.applyMatrix4(holder.matrixWorld);
    bake.name = "forge";
    if (kind === "obj") return new TextEncoder().encode(new lib.OBJExporter().parse(bake));
    try {
      const out = await new lib.GLTFExporter().parseAsync(bake, { binary: true, maxTextureSize: 4096 });
      return new Uint8Array(out);
    } catch (exc) {
      console.warn("GLTFExporter failed, using Forge's writer:", exc);
      return forgeWriteGlb(view.sm);
    }
  };

  // ---- sculpting: SculptGL's tools (src/editing/tools/*.js), on the welded vertices
  function snapshot() {
    view.undoStack.push({ sm: view.sm, wpos: view.sm.wpos.slice(), poly: view.poly, tri2face: view.tri2face });
    if (view.undoStack.length > 40) view.undoStack.shift();
    view.redoStack = [];
  }
  function restore(from, to) {
    const snap = from.pop();
    if (!snap) return;
    to.push({ sm: view.sm, wpos: view.sm.wpos.slice(), poly: view.poly, tri2face: view.tri2face });
    const changed = snap.sm !== view.sm;
    view.poly = snap.poly || null; view.tri2face = snap.tri2face || null;
    snap.sm.wpos.set(snap.wpos);
    forgeSync(snap.sm); forgeNormals(snap.sm);
    if (changed) useMesh(snap.sm, true); else refresh();
    if (view.poly) flatNormals(); else view.select([]);
    if (view.onChange) view.onChange();
  }
  view.undo = () => restore(view.undoStack, view.redoStack);
  view.redo = () => restore(view.redoStack, view.undoStack);
  view.subdivide = () => {
    if (!view.sm) return;
    if (view.sm.idx.length / 3 > 150000) { forgeSay("Already very detailed (" + (view.sm.idx.length / 3).toLocaleString() + " triangles).", true); return; }
    view.undoStack.push({ sm: view.sm, wpos: view.sm.wpos.slice(), poly: view.poly, tri2face: view.tri2face }); view.redoStack = [];
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
  function stroke(tool, c, negative) {
    dab(tool, c, negative);
    if (view.brush.symmetry && Math.abs(c.x) > view.brush.radius * view.size * 0.05) dab(tool, new THREE.Vector3(-c.x, c.y, c.z), negative);
    forgeSync(view.sm); forgeNormals(view.sm); refresh();
  }
  // Move.js: the picked vertices and their proxy positions, moved along the mouse's drag in the view plane
  function grabStart(c) {
    const sm = view.sm, R = view.brush.radius * view.size, sel = [];
    const pick = (cx, mirror) => { for (const w of picked(new THREE.Vector3(cx, c.y, c.z), R * R)) sel.push([w, fall(Math.hypot(sm.wpos[w * 3] - cx, sm.wpos[w * 3 + 1] - c.y, sm.wpos[w * 3 + 2] - c.z) / R), mirror]); };
    pick(c.x, false);
    if (view.brush.symmetry && Math.abs(c.x) > R * 0.5) pick(-c.x, true);
    const world = holder.localToWorld(c.clone());
    return { sel, orig: sm.wpos.slice(), plane: new THREE.Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()), world), from: c.clone() };
  }
  function grabMove(g, e) {
    const r = canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    const p = raycaster.ray.intersectPlane(g.plane, new THREE.Vector3());
    if (!p) return;
    const d = toLocal(p).sub(g.from).multiplyScalar(view.brush.strength * 0.6 + 0.4), sm = view.sm;
    for (const [w, f, mirror] of g.sel) {
      sm.wpos[w * 3] = g.orig[w * 3] + (mirror ? -d.x : d.x) * f;
      sm.wpos[w * 3 + 1] = g.orig[w * 3 + 1] + d.y * f;
      sm.wpos[w * 3 + 2] = g.orig[w * 3 + 2] + d.z * f;
    }
    forgeSync(sm); forgeNormals(sm); refresh();
  }
  function showRing(hit) {
    if (!hit || view.mode !== "sculpt") { if (ring.visible) { ring.visible = false; view.dirty = true; } return; }
    const iv = picked(hit.point, (view.brush.radius * view.size) ** 2), a = iv.length ? areaNormalCenter(iv) : null;
    const n = a ? new THREE.Vector3(...a.n) : new THREE.Vector3(0, 0, 1);
    ring.position.copy(holder.localToWorld(hit.point.clone().addScaledVector(n, view.size * 0.002)));
    ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n.transformDirection(holder.matrixWorld));
    ring.scale.setScalar(view.brush.radius * view.size * holder.scale.x);
    ring.visible = true; view.dirty = true;
  }

  // ---- pointer: in Sculpt mode a left-drag on the model sculpts (OrbitControls keeps everything else)
  let drag = null;
  canvas.addEventListener("pointerdown", (e) => {
    if (view.mode !== "sculpt" || e.button !== 0 || transform.dragging) return;
    const hit = hitAt(e);
    if (!hit || !view.sm) return;
    e.stopImmediatePropagation();   // OrbitControls does not turn the camera while sculpting
    canvas.setPointerCapture(e.pointerId);
    snapshot();
    if (view.poly) { view.poly = null; view.tri2face = null; view.select([]); }   // sculpted: the poly cage no longer fits
    const tool = e.shiftKey ? "smooth" : view.brush.tool;
    drag = { tool, negative: e.altKey || e.ctrlKey || e.metaKey, last: hit.point.clone() };
    if (tool === "grab") drag.grab = grabStart(hit.point);
    else stroke(tool, hit.point, drag.negative);
  }, { capture: true });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) { if (view.mode === "sculpt") showRing(hitAt(e)); return; }
    e.stopImmediatePropagation();
    if (drag.grab) { grabMove(drag.grab, e); return; }
    const hit = hitAt(e);
    showRing(hit);
    if (!hit) return;
    // SculptBase.sculptStroke: dabs spaced 0.15 x radius apart along the stroke
    const step = view.brush.radius * view.size * 0.15, dist = hit.point.distanceTo(drag.last);
    if (dist < step) return;
    const n = Math.floor(dist / step);
    for (let i = 1; i <= n; i++) dab(drag.tool, drag.last.clone().lerp(hit.point, i / n), drag.negative);
    if (view.brush.symmetry) for (let i = 1; i <= n; i++) {
      const p = drag.last.clone().lerp(hit.point, i / n);
      if (Math.abs(p.x) > view.brush.radius * view.size * 0.05) dab(drag.tool, new THREE.Vector3(-p.x, p.y, p.z), drag.negative);
    }
    forgeSync(view.sm); forgeNormals(view.sm); refresh();
    drag.last.copy(hit.point);
  }, { capture: true });
  const end = () => { drag = null; };
  canvas.addEventListener("pointerup", end); canvas.addEventListener("pointercancel", end);
  canvas.addEventListener("pointerleave", () => { if (!drag) showRing(null); });
  // ---- poly modelling + DynaMesh (app/ui/forge_poly.js, the bar is forge_model.js): a poly mesh shown with hard
  // edges (every face its own corners, so the sculpt weld still joins them), faces picked by click, selection drawn
  // over the model, and every change undoable like a stroke.
  view.poly = null; view.tri2face = null;
  function flatNormals() {
    if (!view.poly || !view.sm || !view.polyCorners) return;
    const nrm = view.sm.nrm;
    view.poly.f.forEach((f, fi) => {
      const n = window.ForgePoly.faceNormal(view.poly, f), at = view.polyCorners[fi];
      for (let k = 0; k < f.length; k++) nrm.set(n, (at + k) * 3);
    });
    if (mesh) { mesh.geometry.attributes.normal.needsUpdate = true; view.dirty = true; }
  }
  view.showPoly = (poly, keepView, noUndo) => {
    if (!noUndo && view.sm) snapshot();
    let corners = 0;
    for (const f of poly.f) corners += f.length;
    const pos = new Float32Array(corners * 3), idx = [], tri2face = [], start = [];
    let c = 0;
    poly.f.forEach((f, fi) => {
      start.push(c);
      for (let k = 0; k < f.length; k++) pos.set(poly.v[f[k]], (c + k) * 3);
      for (let k = 1; k + 1 < f.length; k++) { idx.push(c, c + k, c + k + 1); tri2face.push(fi); }
      c += f.length;
    });
    if (!keepView) { holder.position.set(0, 0, 0); holder.rotation.set(0, 0, 0); holder.scale.set(1, 1, 1); }
    view.poly = poly; view.tri2face = Int32Array.from(tri2face); view.polyCorners = start;
    const sm = forgeMeshFrom(pos, null, null, Uint32Array.from(idx));
    view.polyCorners = start;
    view.sm = sm; flatNormals();
    useMesh(sm, keepView);
    view.select([]);
    if (view.onChange) view.onChange();
  };
  // the current model as triangles (welded, sculpted shape) - for DynaMesh and "edit as polygons"
  view.triangles = () => {
    if (!view.sm) return null;
    const sm = view.sm, idx = new Uint32Array(sm.idx.length);
    for (let i = 0; i < idx.length; i++) idx[i] = sm.wid[sm.idx[i]];
    return { pos: sm.wpos.slice(), idx };
  };
  const selMat = new THREE.MeshBasicMaterial({ color: 0xed782b, transparent: true, opacity: 0.5, side: THREE.DoubleSide,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2, depthWrite: false });
  let selMesh = null;
  view.selected = [];
  view.select = (faces) => {
    view.selected = faces.slice();
    if (selMesh) { holder.remove(selMesh); selMesh.geometry.dispose(); selMesh = null; }
    if (view.poly && faces.length) {
      const P = [];
      for (const fi of faces) {
        const f = view.poly.f[fi];
        if (!f) continue;
        for (let k = 1; k + 1 < f.length; k++) P.push(...view.poly.v[f[0]], ...view.poly.v[f[k]], ...view.poly.v[f[k + 1]]);
      }
      const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(P, 3));
      selMesh = new THREE.Mesh(g, selMat); selMesh.renderOrder = 5; holder.add(selMesh);
    }
    view.dirty = true;
  };
  let tap = null;   // Model mode: a click (not a drag - that still turns the view) picks the face under it
  canvas.addEventListener("pointerdown", (e) => { tap = view.mode === "poly" && e.button === 0 ? { x: e.clientX, y: e.clientY } : null; });
  canvas.addEventListener("pointerup", (e) => {
    if (!tap || view.mode !== "poly") return;
    const moved = Math.hypot(e.clientX - tap.x, e.clientY - tap.y);
    tap = null;
    if (moved > 5 || !view.tri2face) return;
    const hit = hitAt(e);
    const face = hit && hit.tri != null ? view.tri2face[hit.tri] : -1;
    if (view.onPick) view.onPick(face, e.shiftKey || e.ctrlKey || e.metaKey);
  });
  view.dab = (tool, x, y, z, negative) => { snapshot(); stroke(tool, new THREE.Vector3(x, y, z), !!negative); };   // tests / scripts
  view.transform = transform;
  view.holder = holder;
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
  forgeSay(v.mode === "sculpt" ? "Sculpt: drag on the model. Alt/Ctrl inverts, Shift smooths, [ ] radius, drag off the model to turn." : "");
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
  document.addEventListener("keydown", (e) => {
    const sheet = document.getElementById("forge");
    if (!sheet || sheet.hidden) return;
    if (e.key === "Escape") { forgeClose(); return; }
    if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    const v = forge.view;
    if (!v) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) v.redo(); else v.undo(); }
    else if (e.key === "f" || e.key === "F") v.frame();
    else if (e.key === "w" || e.key === "e" || e.key === "r") v.toggleTransform({ w: "translate", e: "rotate", r: "scale" }[e.key]);
    else if (e.key === "[" || e.key === "]") {
      v.brush.radius = Math.min(0.4, Math.max(0.02, v.brush.radius * (e.key === "]" ? 1.15 : 1 / 1.15)));
      const r = document.getElementById("forge-radius"); if (r) r.value = String(v.brush.radius);
    }
  });
});
