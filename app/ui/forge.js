// Forge: make 3D things. Three ways in - Draw (a canvas), Add an image (drop or pick), Describe it (text ->
// picture, shown first so it can be redone) - then the engine lifts the picture to a 3D model
// (engine/forge3d.py: TripoSR on this computer, a free online Space, or the offline lift that always works).
// The model opens in a viewer (orbit, zoom, wireframe, clay, lighting) with a SCULPT mode in the spirit of
// Nomad Sculpt / ZBrush: Draw, Inflate, Smooth, Flatten, Grab, Pinch, radius/strength, X symmetry,
// undo/redo, Subdivide (curved midpoint). Sculpting moves the mesh's own vertices (no voxels).
// Save .glb / .obj puts the file in the workspace's models/ (POST /forge/save) - shown in Files.
//
// three.js (vendored, MIT) is imported only when Forge opens. The GLB reader/writer and the orbit control
// are LOKI's own (the three.js add-ons could not be vendored from the build sandbox). Uses api(), el(),
// state from app.js and the icon pattern of icons.js (data-icon + data-tip-name/-what). Plain DOM, CSP-safe.
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
  mirror: '<path d="M12 3v18" stroke-dasharray="2 2"/><path d="M9 7L4 12l5 5zM15 7l5 5-5 5z"/>',
  subdivide: '<path d="M12 3.5l8.5 15h-17z"/><path d="M7.75 11h8.5M12 18.5l-4.25-7.5M12 18.5l4.25-7.5"/>',
  save: '<path d="M5 3.5h11l3.5 3.5v13.5H5z"/><path d="M8 3.5v5h7v-5M8 20.5v-6h8v6"/>',
});

const forge = { way: "draw", job: "", jobTimer: 0, three: null, view: null, model: null, imageRel: "", backend: "auto",
  drawing: { ctx: null, hist: [], tool: "brush", color: "#ed782b", size: 14, down: false, last: null }, picked: "" };
const FORGE_BRUSHES = [
  ["draw", "brush", "Draw", "Push the surface out along its normal (hold Alt or Ctrl to dig in)."],
  ["inflate", "inflate", "Inflate", "Swell the surface, each point along its own normal (Alt/Ctrl deflates)."],
  ["smooth", "smooth", "Smooth", "Relax bumps toward their neighbours (Shift smooths with any brush)."],
  ["flatten", "flatten", "Flatten", "Press the surface onto a plane - planes and hard surfaces."],
  ["grab", "grab", "Grab", "Pull a whole area along with the mouse - big shape changes."],
  ["pinch", "pinch", "Pinch", "Pull the surface toward the brush centre - sharp creases and edges."],
];
const FORGE_LIGHTS = [
  ["Studio", 0xdfe6f2, 0x2a2e36, 1.0, 0xffffff, 2.4],
  ["Warm", 0xffe2c4, 0x2c241f, 1.0, 0xfff1dc, 2.4],
  ["Cool", 0xcfe0ff, 0x1d2430, 1.1, 0xe4efff, 2.2],
  ["Soft", 0xffffff, 0x60646e, 1.8, 0xffffff, 0.8],
];

function forgeBtn(icon, name, what, onClick, cls) {
  const b = el("button", "mini icon-mini forge-btn" + (cls ? " " + cls : ""), name);
  b.type = "button"; b.dataset.icon = icon; b.dataset.tipName = name; b.dataset.tipWhat = what;
  b.addEventListener("click", onClick);
  return b;
}

function forgeSay(text, bad) {
  const s = document.getElementById("forge-status");
  if (s) { s.textContent = text || ""; s.classList.toggle("bad", !!bad); }
}

// ------------------------------------------------------------------------------------------ the sheet
function forgeBuild() {
  if (document.getElementById("forge")) return;
  const sheet = el("div", "sheet forge-sheet"); sheet.id = "forge"; sheet.hidden = true;
  const panel = el("div", "sheet-panel forge-panel");
  panel.setAttribute("role", "dialog"); panel.setAttribute("aria-modal", "true"); panel.setAttribute("aria-labelledby", "forge-title");
  const head = el("header", "sheet-head");
  const title = el("h2", "", "Forge"); title.id = "forge-title";
  const status = el("span", "forge-status"); status.id = "forge-status"; status.setAttribute("role", "status");
  head.append(title, status, forgeBtn("close", "Close", "Close Forge (Esc).", forgeClose));
  const body = el("div", "forge-body");
  body.append(forgeSide(), forgeStage());
  panel.append(head, body);
  sheet.append(panel);
  document.body.append(sheet);
  sheet.addEventListener("click", (e) => { if (e.target === sheet) forgeClose(); });
}

function forgeSide() {
  const side = el("aside", "forge-side");
  const ways = el("div", "forge-ways"); ways.setAttribute("role", "tablist");
  for (const [way, icon, name, what] of [["draw", "pen", "Draw", "Draw it on a canvas, then make it 3D."],
    ["image", "image", "Add an image", "Drop or pick a picture, then make it 3D."],
    ["describe", "sparkle", "Describe it", "Say what you want: LOKI draws a picture first (redo it until you like it), then makes it 3D."]]) {
    const b = forgeBtn(icon, name, what, () => forgeWay(way), "forge-way");
    b.dataset.way = way; b.setAttribute("role", "tab");
    ways.append(b);
  }
  side.append(ways, forgeDrawPane(), forgeImagePane(), forgeDescribePane());
  const go = el("div", "forge-go");
  const pick = el("select", "forge-backend"); pick.id = "forge-backend";
  pick.setAttribute("aria-label", "How to make the 3D model");
  for (const [v, t] of [["auto", "Best available"], ["triposr", "TripoSR (this computer)"], ["online", "Online Space"], ["lift", "Offline lift (instant)"]]) {
    const o = el("option", "", t); o.value = v; pick.append(o);
  }
  pick.addEventListener("change", () => { forge.backend = pick.value; });
  const make = el("button", "send forge-make", "Make 3D"); make.type = "button"; make.id = "forge-make";
  make.addEventListener("click", forgeMake);
  go.append(pick, make);
  const prog = el("div", "forge-progress"); prog.id = "forge-progress"; prog.hidden = true;
  prog.append(el("span", "forge-stage-text"), el("div", "forge-bar"));
  prog.lastChild.append(el("i"));
  const listHead = el("div", "forge-sub", "Your models");
  const list = el("div", "forge-models"); list.id = "forge-models";
  side.append(go, prog, listHead, list);
  return side;
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
  const stage = el("section", "forge-stage");
  const cv = document.createElement("canvas"); cv.id = "forge-view"; cv.className = "forge-view";
  cv.setAttribute("aria-label", "3D view: drag to turn, wheel to zoom, right-drag or Shift-drag to move");
  const empty = el("p", "forge-empty", "Draw, add a picture or describe something - the model appears here.");
  empty.id = "forge-empty";
  const viewBar = el("div", "forge-float forge-viewbar");
  const mode = forgeBtn("sculpt", "Sculpt", "Sculpt mode: shape the model with brushes. Drag on empty space still turns it.", () => forgeMode(), "forge-mode");
  mode.id = "forge-mode";
  viewBar.append(mode,
    forgeBtn("wire", "Wireframe", "Show the mesh's triangles.", (e) => forgeToggle("wire", e.currentTarget)),
    forgeBtn("clay", "Clay", "Plain clay: hide the colours to judge the form.", (e) => forgeToggle("clay", e.currentTarget)),
    forgeBtn("sun", "Lighting", "Change the light: studio, warm, cool, soft.", forgeLight),
    forgeBtn("frame", "Frame", "Fit the model in view (F).", () => forge.view && forge.view.frame()));
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
  out.append(forgeBtn("save", "Save .glb", "Save this model (with your sculpting) as .glb in models/ - Blender, Godot, Maya and the web open it.", () => forgeSave("glb")),
    forgeBtn("file", "Save .obj", "Save it as .obj in models/ (ZBrush, Nomad Sculpt, any 3D app).", () => forgeSave("obj")),
    forgeBtn("folder", "Show in Files", "Open the models folder in Files.", () => {
      if (typeof openFiles === "function") { forgeClose(); openFiles(forge.model ? "models/" + forge.model : undefined); }
    }));
  stage.append(cv, empty, viewBar, sculpt, out);
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

function forgeWay(way) {
  forge.way = way;
  for (const b of document.querySelectorAll("#forge .forge-way")) {
    b.classList.toggle("on", b.dataset.way === way); b.setAttribute("aria-selected", String(b.dataset.way === way));
  }
  for (const p of document.querySelectorAll("#forge .forge-pane")) p.hidden = p.dataset.pane !== way;
}

function forgeOpen() {
  forgeBuild();
  const sheet = document.getElementById("forge");
  sheet.hidden = false;
  forgeWay(forge.way);
  forgeList();
  api("/forge/status").then((r) => {
    if (r && r.ok && r.order) forgeSay("Ready: " + r.order.join(" → ") + (r.backends && !r.backends.triposr ? " (TripoSR: python tools/setup_forge3d.py)" : ""));
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
  const r = await api("/forge/image", { prompt: text }).catch(() => null);
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
  const body = { backend: forge.backend };
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
    v.setMesh(await forgeParseGlb(await resp.arrayBuffer(), v.THREE));
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
  const data = kind === "glb" ? forgeWriteGlb(forge.view.sm) : new TextEncoder().encode(forgeWriteObj(forge.view.sm));
  const resp = await fetch("/forge/save?name=" + encodeURIComponent(base), {
    method: "POST", headers: { Authorization: "Bearer " + state.token, "Content-Type": "application/octet-stream" }, body: data,
  }).catch(() => null);
  const r = resp ? await resp.json().catch(() => ({})) : {};
  if (!r.ok) { forgeSay(r.error || "Could not save.", true); return; }
  forgeSay("Saved " + r.path);
  if (kind === "glb") forge.model = r.name;
  forgeList();
}

// ------------------------------------------------------------------------------------------ the mesh
// Sculpt mesh (sm): raw vertex arrays as the GPU sees them (pos, nrm, col, uv, idx) plus a "welded" view
// (wid: raw -> welded id; wpos/wnrm per welded vertex; adjacency), so a UV seam never tears when sculpted.
function forgeMeshFrom(pos, col, uv, idx, image) {
  const n = pos.length / 3;
  const sm = { n, pos, nrm: new Float32Array(n * 3), col, uv, idx, image };
  forgeWeld(sm);
  forgeNormals(sm);
  return sm;
}

function forgeWeld(sm) {
  const { n, pos } = sm;
  let lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
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
  // adjacency (CSR) over welded vertices
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

// Curved midpoint subdivision: every triangle -> 4. A new edge point is lifted off the straight edge using
// the two end normals (a cubic Hermite estimate), so a round shape stays round instead of faceting.
function forgeSubdivide(sm) {
  const { n, idx, wid, wpos, wnrm, col, uv } = sm;
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
    const [i, j] = extra[e], r = n + e, a = wid[i] * 3, b = wid[j] * 3;
    const dx = wpos[b] - wpos[a], dy = wpos[b + 1] - wpos[a + 1], dz = wpos[b + 2] - wpos[a + 2];
    const lift = ((dx * wnrm[b] + dy * wnrm[b + 1] + dz * wnrm[b + 2]) - (dx * wnrm[a] + dy * wnrm[a + 1] + dz * wnrm[a + 2])) / 8;
    let mx = wnrm[a] + wnrm[b], my = wnrm[a + 1] + wnrm[b + 1], mz = wnrm[a + 2] + wnrm[b + 2];
    const l = Math.hypot(mx, my, mz) || 1; mx /= l; my /= l; mz /= l;
    pos[r * 3] = (wpos[a] + wpos[b]) / 2 + lift * mx;
    pos[r * 3 + 1] = (wpos[a + 1] + wpos[b + 1]) / 2 + lift * my;
    pos[r * 3 + 2] = (wpos[a + 2] + wpos[b + 2]) / 2 + lift * mz;
    if (ncol) for (let k = 0; k < 3; k++) ncol[r * 3 + k] = (col[i * 3 + k] + col[j * 3 + k]) / 2;
    if (nuv) for (let k = 0; k < 2; k++) nuv[r * 2 + k] = (uv[i * 2 + k] + uv[j * 2 + k]) / 2;
  }
  return forgeMeshFrom(pos, ncol, nuv, out, sm.image);
}

// ------------------------------------------------------------------------------------------ GLB in / out
function forgeParseGlb(buf, THREE) {
  const dv = new DataView(buf);
  if (buf.byteLength < 20 || dv.getUint32(0, true) !== 0x46546C67) throw new Error("not a .glb");
  let off = 12, g = null, bin = null;
  while (off + 8 <= buf.byteLength) {
    const len = dv.getUint32(off, true), type = dv.getUint32(off + 4, true);
    if (type === 0x4E4F534A) g = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, off + 8, len)));
    else if (type === 0x004E4942) bin = buf.slice(off + 8, off + 8 + len);
    off += 8 + len;
  }
  if (!g) throw new Error("no glTF JSON");
  if ((g.extensionsRequired || []).length) throw new Error("needs " + g.extensionsRequired.join(", ") + " (not supported)");
  const SIZE = { 5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4 };
  const NORM = { 5120: 127, 5121: 255, 5122: 32767, 5123: 65535 };
  const COMPS = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 };
  const read = (i, wantInt) => {
    const a = g.accessors[i], v = g.bufferViews[a.bufferView], comps = COMPS[a.type] || 1, sz = SIZE[a.componentType];
    const view = new DataView(bin, (v.byteOffset || 0) + (a.byteOffset || 0));
    const stride = v.byteStride || comps * sz, out = wantInt ? new Uint32Array(a.count * comps) : new Float32Array(a.count * comps);
    const get = { 5120: (o) => view.getInt8(o), 5121: (o) => view.getUint8(o), 5122: (o) => view.getInt16(o, true),
      5123: (o) => view.getUint16(o, true), 5125: (o) => view.getUint32(o, true), 5126: (o) => view.getFloat32(o, true) }[a.componentType];
    const div = (!wantInt && (a.normalized || a.componentType !== 5126) && NORM[a.componentType]) || 1;
    for (let e = 0; e < a.count; e++) for (let c = 0; c < comps; c++) out[e * comps + c] = get(e * stride + c * sz) / div;
    return { data: out, comps };
  };
  const P = [], C = [], U = [], I = [];
  let image = null, count = 0, hasUv = false;
  const prims = [];
  const walk = (ni, parent) => {
    const node = g.nodes[ni], m = new THREE.Matrix4();
    if (node.matrix) m.fromArray(node.matrix);
    else m.compose(new THREE.Vector3(...(node.translation || [0, 0, 0])), new THREE.Quaternion(...(node.rotation || [0, 0, 0, 1])),
      new THREE.Vector3(...(node.scale || [1, 1, 1])));
    const world = parent.clone().multiply(m);
    if (node.mesh !== undefined) for (const p of g.meshes[node.mesh].primitives) if (p.mode === undefined || p.mode === 4) prims.push([p, world]);
    for (const c of node.children || []) walk(c, world);
  };
  const scene = g.scenes ? g.scenes[g.scene || 0] : { nodes: g.nodes.map((_, i) => i) };
  for (const ni of scene.nodes) walk(ni, new THREE.Matrix4());
  for (const [p] of prims) if (p.attributes.TEXCOORD_0 !== undefined) hasUv = true;
  for (const [p, world] of prims) {
    const pos = read(p.attributes.POSITION).data, nv = pos.length / 3;
    const v = new THREE.Vector3();
    for (let i = 0; i < nv; i++) { v.set(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]).applyMatrix4(world); P.push(v.x, v.y, v.z); }
    const mat = p.material !== undefined && g.materials ? g.materials[p.material] : {};
    const pbr = (mat && mat.pbrMetallicRoughness) || {}, factor = pbr.baseColorFactor || [1, 1, 1, 1];
    if (pbr.baseColorTexture && !image && g.textures) {
      const src = g.images[g.textures[pbr.baseColorTexture.index].source];
      if (src && src.bufferView !== undefined) {
        const bv = g.bufferViews[src.bufferView];
        image = { bytes: new Uint8Array(bin.slice(bv.byteOffset || 0, (bv.byteOffset || 0) + bv.byteLength)), mime: src.mimeType || "image/png" };
      }
    }
    if (p.attributes.COLOR_0 !== undefined) {
      const c = read(p.attributes.COLOR_0);
      for (let i = 0; i < nv; i++) C.push(c.data[i * c.comps] * factor[0], c.data[i * c.comps + 1] * factor[1], c.data[i * c.comps + 2] * factor[2]);
    } else for (let i = 0; i < nv; i++) C.push(factor[0], factor[1], factor[2]);
    if (hasUv) {
      if (p.attributes.TEXCOORD_0 !== undefined) U.push(...read(p.attributes.TEXCOORD_0).data);
      else for (let i = 0; i < nv; i++) U.push(0, 0);
    }
    if (p.indices !== undefined) for (const x of read(p.indices, true).data) I.push(x + count);
    else for (let i = 0; i < nv; i++) I.push(i + count);
    count += nv;
  }
  if (!count) throw new Error("no triangles in it");
  // centre on the origin, so X symmetry mirrors across the middle of the model
  const pos = Float32Array.from(P), box = new THREE.Box3().setFromArray(pos), c = box.getCenter(new THREE.Vector3());
  for (let i = 0; i < pos.length; i += 3) { pos[i] -= c.x; pos[i + 1] -= c.y; pos[i + 2] -= c.z; }
  return forgeMeshFrom(pos, Float32Array.from(C), hasUv ? Float32Array.from(U) : null, Uint32Array.from(I), image);
}

function forgeWriteGlb(sm) {
  const parts = [], views = [], accessors = [];
  let off = 0;
  const add = (arr, target, comps, ctype, extra) => {
    const bytes = new Uint8Array(arr.buffer, arr.byteOffset, arr.byteLength), pad = (4 - (bytes.length % 4)) % 4;
    parts.push(bytes, new Uint8Array(pad));
    const view = { buffer: 0, byteOffset: off, byteLength: bytes.length };
    if (target) view.target = target;
    views.push(view);
    off += bytes.length + pad;
    if (comps) accessors.push(Object.assign({ bufferView: views.length - 1, componentType: ctype, count: arr.length / comps,
      type: { 1: "SCALAR", 2: "VEC2", 3: "VEC3" }[comps] }, extra || {}));
    return accessors.length - 1;
  };
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < sm.pos.length; i++) { lo[i % 3] = Math.min(lo[i % 3], sm.pos[i]); hi[i % 3] = Math.max(hi[i % 3], sm.pos[i]); }
  const attrs = { POSITION: add(sm.pos, 34962, 3, 5126, { min: lo, max: hi }), NORMAL: add(sm.nrm, 34962, 3, 5126) };
  if (sm.col) attrs.COLOR_0 = add(sm.col, 34962, 3, 5126);
  if (sm.uv) attrs.TEXCOORD_0 = add(sm.uv, 34962, 2, 5126);
  const indices = add(sm.idx, 34963, 1, 5125);
  const material = { name: "forge", pbrMetallicRoughness: { baseColorFactor: [1, 1, 1, 1], metallicFactor: 0, roughnessFactor: 0.8 } };
  const doc = { asset: { version: "2.0", generator: "LOKI Forge" }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0, name: "forge" }],
    meshes: [{ name: "forge", primitives: [{ attributes: attrs, indices, material: 0, mode: 4 }] }], materials: [material] };
  if (sm.image && sm.uv) {
    add(sm.image.bytes, 0, 0);
    doc.images = [{ bufferView: views.length - 1, mimeType: sm.image.mime }];
    doc.samplers = [{}]; doc.textures = [{ source: 0, sampler: 0 }];
    material.pbrMetallicRoughness.baseColorTexture = { index: 0 };
  }
  Object.assign(doc, { accessors, bufferViews: views, buffers: [{ byteLength: off }] });
  let js = new TextEncoder().encode(JSON.stringify(doc));
  const jpad = (4 - (js.length % 4)) % 4;
  const total = 12 + 8 + js.length + jpad + 8 + off, out = new Uint8Array(total), dv = new DataView(out.buffer);
  dv.setUint32(0, 0x46546C67, true); dv.setUint32(4, 2, true); dv.setUint32(8, total, true);
  dv.setUint32(12, js.length + jpad, true); dv.setUint32(16, 0x4E4F534A, true);
  out.set(js, 20); out.fill(32, 20 + js.length, 20 + js.length + jpad);
  let o = 20 + js.length + jpad;
  dv.setUint32(o, off, true); dv.setUint32(o + 4, 0x004E4942, true); o += 8;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

function forgeWriteObj(sm) {
  const srgb = (c) => { c = Math.min(1, Math.max(0, c)); return c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055; };
  const lines = ["# LOKI Forge"];
  for (let i = 0; i < sm.n; i++) {
    const p = [sm.pos[i * 3], sm.pos[i * 3 + 1], sm.pos[i * 3 + 2]].map((x) => x.toFixed(5));
    if (sm.col) p.push(...[0, 1, 2].map((k) => srgb(sm.col[i * 3 + k]).toFixed(4)));
    lines.push("v " + p.join(" "));
  }
  for (let i = 0; i < sm.n; i++) lines.push("vn " + [0, 1, 2].map((k) => sm.nrm[i * 3 + k].toFixed(4)).join(" "));
  if (sm.uv) for (let i = 0; i < sm.n; i++) lines.push("vt " + sm.uv[i * 2].toFixed(5) + " " + (1 - sm.uv[i * 2 + 1]).toFixed(5));
  for (let t = 0; t < sm.idx.length; t += 3) {
    const f = [0, 1, 2].map((k) => { const v = sm.idx[t + k] + 1; return sm.uv ? v + "/" + v + "/" + v : v + "//" + v; });
    lines.push("f " + f.join(" "));
  }
  return lines.join("\n") + "\n";
}

// ------------------------------------------------------------------------------------------ the viewer
async function forgeViewer() {
  if (forge.view) return forge.view;
  if (forge.viewLoading) return forge.viewLoading;
  forge.viewLoading = (async () => {
    let THREE;
    try { THREE = await import("/ui/vendor/three/three.module.js"); } catch (_) { return null; }
    const canvas = document.getElementById("forge-view");
    let renderer;
    try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); } catch (_) { return null; }
    forge.view = forgeMakeView(THREE, renderer, canvas);
    return forge.view;
  })();
  return forge.viewLoading;
}

function forgeMakeView(THREE, renderer, canvas) {
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100);
  scene.add(camera);
  const hemi = new THREE.HemisphereLight(0xdfe6f2, 0x2a2e36, 1.0);
  const key = new THREE.DirectionalLight(0xffffff, 2.4); key.position.set(1.2, 1.6, 2);
  const rim = new THREE.DirectionalLight(0x9fb6d8, 1.2); rim.position.set(-2, 0.5, -2);
  scene.add(hemi); camera.add(key, rim);   // the light turns with the camera: the side you look at is lit
  const material = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.62, metalness: 0, vertexColors: true });
  const clayColor = new THREE.Color(0xc9b8a8);
  let mesh = null, texture = null;
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.92, 1, 48), new THREE.MeshBasicMaterial({ color: 0xbfd4ff, transparent: true,
    opacity: 0.85, depthTest: false, side: THREE.DoubleSide }));
  ring.renderOrder = 10; ring.visible = false; scene.add(ring);
  const orbit = { theta: 0.5, phi: 1.2, dist: 2.6, target: new THREE.Vector3() };
  const view = { THREE, sm: null, mode: "view", brush: { tool: "draw", radius: 0.12, strength: 0.5, symmetry: true },
    undoStack: [], redoStack: [], light: 0, running: false, dirty: true, size: 1 };
  const raycaster = new THREE.Raycaster();

  function place() {
    const s = Math.sin(orbit.phi);
    camera.position.set(orbit.target.x + orbit.dist * s * Math.sin(orbit.theta), orbit.target.y + orbit.dist * Math.cos(orbit.phi),
      orbit.target.z + orbit.dist * s * Math.cos(orbit.theta));
    camera.lookAt(orbit.target);
    view.dirty = true;
  }
  function resize() {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    if (canvas.width !== Math.round(w * renderer.getPixelRatio()) || canvas.height !== Math.round(h * renderer.getPixelRatio())) {
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); view.dirty = true;
    }
  }
  function loop() {
    if (!view.running) return;
    resize();
    if (view.dirty) { renderer.render(scene, camera); view.dirty = false; }
    requestAnimationFrame(loop);
  }
  view.start = () => { if (!view.running) { view.running = true; place(); requestAnimationFrame(loop); } };
  view.stop = () => { view.running = false; };
  view.frame = () => {
    if (!mesh) return;
    mesh.geometry.computeBoundingSphere();
    const bs = mesh.geometry.boundingSphere;
    orbit.target.copy(bs.center); view.size = bs.radius * 2 || 1;
    orbit.dist = bs.radius / Math.sin((camera.fov * Math.PI) / 360) * 1.15;
    camera.near = orbit.dist / 100; camera.far = orbit.dist * 100; camera.updateProjectionMatrix();
    place();
  };

  function geometryOf(sm) {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(sm.pos, 3));
    geo.setAttribute("normal", new THREE.BufferAttribute(sm.nrm, 3));
    if (sm.col) geo.setAttribute("color", new THREE.BufferAttribute(sm.col, 3));
    if (sm.uv) geo.setAttribute("uv", new THREE.BufferAttribute(sm.uv, 2));
    geo.setIndex(new THREE.BufferAttribute(sm.idx, 1));
    geo.computeBoundingSphere();
    return geo;
  }
  function useMesh(sm, keepView) {
    if (mesh) { scene.remove(mesh); mesh.geometry.dispose(); }
    view.sm = sm;
    mesh = new THREE.Mesh(geometryOf(sm), material);
    scene.add(mesh);
    applyLook();
    if (!keepView) view.frame();
    view.dirty = true;
  }
  view.setMesh = (sm) => {
    view.undoStack = []; view.redoStack = [];
    if (texture) { texture.dispose(); texture = null; }
    if (sm.image) {
      createImageBitmap(new Blob([sm.image.bytes], { type: sm.image.mime })).then((bmp) => {
        texture = new THREE.Texture(bmp); texture.flipY = false; texture.colorSpace = THREE.SRGBColorSpace; texture.needsUpdate = true;
        applyLook();
      }).catch(() => {});
    }
    useMesh(sm, false);
  };
  function applyLook() {
    const clay = !!view.clay;
    material.vertexColors = !clay && !!(view.sm && view.sm.col);
    material.map = !clay && texture && view.sm && view.sm.uv ? texture : null;
    material.color.copy(clay ? clayColor : new THREE.Color(0xffffff));
    material.wireframe = !!view.wire;
    material.needsUpdate = true;
    view.dirty = true;
  }
  view.setLook = (what, on) => { view[what] = on; applyLook(); };
  view.nextLight = () => {
    view.light = (view.light + 1) % FORGE_LIGHTS.length;
    const [name, sky, ground, hi, keyColor, ki] = FORGE_LIGHTS[view.light];
    hemi.color.setHex(sky); hemi.groundColor.setHex(ground); hemi.intensity = hi; key.color.setHex(keyColor); key.intensity = ki;
    view.dirty = true;
    return name;
  };
  view.setMode = (m) => { view.mode = m; ring.visible = false; view.dirty = true; };

  // ---- sculpting
  function snapshot() {
    view.undoStack.push({ sm: view.sm, wpos: view.sm.wpos.slice() });
    if (view.undoStack.length > 40) view.undoStack.shift();
    view.redoStack = [];
  }
  function restore(from, to) {
    const snap = from.pop();
    if (!snap) return;
    to.push({ sm: view.sm, wpos: view.sm.wpos.slice() });
    const changed = snap.sm !== view.sm;
    snap.sm.wpos.set(snap.wpos);
    forgeSync(snap.sm); forgeNormals(snap.sm);
    if (changed) useMesh(snap.sm, true); else refresh();
  }
  view.undo = () => restore(view.undoStack, view.redoStack);
  view.redo = () => restore(view.redoStack, view.undoStack);
  view.subdivide = () => {
    if (!view.sm) return;
    if (view.sm.idx.length / 3 > 150000) { forgeSay("Already very detailed (" + (view.sm.idx.length / 3).toLocaleString() + " triangles).", true); return; }
    view.undoStack.push({ sm: view.sm, wpos: view.sm.wpos.slice() }); view.redoStack = [];
    useMesh(forgeSubdivide(view.sm), true);
    forgeSay((view.sm.idx.length / 3).toLocaleString() + " triangles");
  };
  function refresh() {
    const g = mesh.geometry;
    g.attributes.position.needsUpdate = true; g.attributes.normal.needsUpdate = true;
    g.computeBoundingSphere(); g.computeBoundingBox();
    view.dirty = true;
  }
  function hitAt(e) {
    if (!mesh) return null;
    const r = canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    const hit = raycaster.intersectObject(mesh, false)[0];
    return hit || null;
  }
  function areaNormal(sm, c, R) {
    const { wpos, wnrm, wn } = sm, n = [0, 0, 0], R2 = R * R;
    for (let w = 0; w < wn; w++) {
      const dx = wpos[w * 3] - c.x, dy = wpos[w * 3 + 1] - c.y, dz = wpos[w * 3 + 2] - c.z, d2 = dx * dx + dy * dy + dz * dz;
      if (d2 < R2) { const f = 1 - d2 / R2; n[0] += wnrm[w * 3] * f; n[1] += wnrm[w * 3 + 1] * f; n[2] += wnrm[w * 3 + 2] * f; }
    }
    const l = Math.hypot(n[0], n[1], n[2]) || 1;
    return new THREE.Vector3(n[0] / l, n[1] / l, n[2] / l);
  }
  // one dab of the brush at c (world = model space; the mesh has no transform)
  function dab(tool, c, sign) {
    const sm = view.sm, { wpos, wnrm, wn, adjStart, adj } = sm;
    const R = view.brush.radius * view.size, R2 = R * R, s = view.brush.strength;
    const n = areaNormal(sm, c, R);
    let plane = 0;
    if (tool === "flatten") {   // the plane through the weighted middle of the area
      let sw = 0, px = 0, py = 0, pz = 0;
      for (let w = 0; w < wn; w++) {
        const dx = wpos[w * 3] - c.x, dy = wpos[w * 3 + 1] - c.y, dz = wpos[w * 3 + 2] - c.z, d2 = dx * dx + dy * dy + dz * dz;
        if (d2 < R2) { const f = 1 - d2 / R2; sw += f; px += wpos[w * 3] * f; py += wpos[w * 3 + 1] * f; pz += wpos[w * 3 + 2] * f; }
      }
      if (sw) plane = (px * n.x + py * n.y + pz * n.z) / sw;
    }
    const moves = [];
    for (let w = 0; w < wn; w++) {
      const x = wpos[w * 3], y = wpos[w * 3 + 1], z = wpos[w * 3 + 2];
      const dx = x - c.x, dy = y - c.y, dz = z - c.z, d2 = dx * dx + dy * dy + dz * dz;
      if (d2 >= R2) continue;
      const t = d2 / R2, f = (1 - t) * (1 - t);   // smooth falloff
      let mx = 0, my = 0, mz = 0;
      if (tool === "draw") { const k = sign * s * R * 0.06 * f; mx = n.x * k; my = n.y * k; mz = n.z * k; }
      else if (tool === "inflate") { const k = sign * s * R * 0.06 * f; mx = wnrm[w * 3] * k; my = wnrm[w * 3 + 1] * k; mz = wnrm[w * 3 + 2] * k; }
      else if (tool === "smooth") {
        const a = adjStart[w], b = adjStart[w + 1];
        if (b === a) continue;
        let ax = 0, ay = 0, az = 0;
        for (let i = a; i < b; i++) { const v = adj[i] * 3; ax += wpos[v]; ay += wpos[v + 1]; az += wpos[v + 2]; }
        const k = Math.min(1, s * f * 0.9), cnt = b - a;
        mx = (ax / cnt - x) * k; my = (ay / cnt - y) * k; mz = (az / cnt - z) * k;
      } else if (tool === "flatten") {
        const d = x * n.x + y * n.y + z * n.z - plane, k = -d * Math.min(1, s * f * 0.5);
        mx = n.x * k; my = n.y * k; mz = n.z * k;
      } else if (tool === "pinch") {
        const along = dx * n.x + dy * n.y + dz * n.z, k = -sign * s * f * 0.12;
        mx = (dx - n.x * along) * k; my = (dy - n.y * along) * k; mz = (dz - n.z * along) * k;
      }
      moves.push(w, mx, my, mz);
    }
    for (let i = 0; i < moves.length; i += 4) { const w = moves[i] * 3; wpos[w] += moves[i + 1]; wpos[w + 1] += moves[i + 2]; wpos[w + 2] += moves[i + 3]; }
  }
  function stroke(tool, c, sign) {
    dab(tool, c, sign);
    if (view.brush.symmetry && Math.abs(c.x) > view.brush.radius * view.size * 0.05) dab(tool, new THREE.Vector3(-c.x, c.y, c.z), sign);
    else if (view.brush.symmetry) { /* on the middle line: one dab covers both sides */ }
    forgeSync(view.sm); forgeNormals(view.sm); refresh();
  }
  function grabStart(c) {
    const sm = view.sm, R = view.brush.radius * view.size, R2 = R * R, sel = [];
    const pick = (cx, mirror) => {
      for (let w = 0; w < sm.wn; w++) {
        const dx = sm.wpos[w * 3] - cx, dy = sm.wpos[w * 3 + 1] - c.y, dz = sm.wpos[w * 3 + 2] - c.z, d2 = dx * dx + dy * dy + dz * dz;
        if (d2 < R2) { const t = d2 / R2; sel.push([w, (1 - t) * (1 - t), mirror]); }
      }
    };
    pick(c.x, false);
    if (view.brush.symmetry && Math.abs(c.x) > R * 0.5) pick(-c.x, true);
    return { sel, orig: sm.wpos.slice(), plane: new THREE.Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()), c), from: c.clone() };
  }
  function grabMove(g, e) {
    const r = canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    const p = raycaster.ray.intersectPlane(g.plane, new THREE.Vector3());
    if (!p) return;
    const d = p.sub(g.from).multiplyScalar(view.brush.strength * 0.6 + 0.4), sm = view.sm;
    for (const [w, f, mirror] of g.sel) {
      sm.wpos[w * 3] = g.orig[w * 3] + (mirror ? -d.x : d.x) * f;
      sm.wpos[w * 3 + 1] = g.orig[w * 3 + 1] + d.y * f;
      sm.wpos[w * 3 + 2] = g.orig[w * 3 + 2] + d.z * f;
    }
    forgeSync(sm); forgeNormals(sm); refresh();
  }
  function showRing(hit) {
    if (!hit || view.mode !== "sculpt") { if (ring.visible) { ring.visible = false; view.dirty = true; } return; }
    const n = areaNormal(view.sm, hit.point, view.brush.radius * view.size);
    ring.position.copy(hit.point).addScaledVector(n, view.size * 0.002);
    ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
    ring.scale.setScalar(view.brush.radius * view.size);
    ring.visible = true; view.dirty = true;
  }

  // ---- pointer: left = sculpt (on the model, in Sculpt mode) or turn; right/middle or Shift = move; wheel = zoom
  let drag = null;
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("pointerdown", (e) => {
    canvas.setPointerCapture(e.pointerId);
    const hit = view.mode === "sculpt" && e.button === 0 && !e.shiftKey ? hitAt(e) : null;
    if (hit && view.sm) {
      snapshot();
      const tool = view.brush.tool;
      drag = { kind: "sculpt", tool, sign: e.altKey || e.ctrlKey || e.metaKey ? -1 : 1, last: hit.point.clone() };
      if (tool === "grab") drag.grab = grabStart(hit.point);
      else stroke(e.shiftKey ? "smooth" : tool, hit.point, drag.sign);
      return;
    }
    drag = { kind: e.button === 0 && !e.shiftKey ? "turn" : "pan", x: e.clientX, y: e.clientY };
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) { if (view.mode === "sculpt") showRing(hitAt(e)); return; }
    if (drag.kind === "sculpt") {
      if (drag.grab) { grabMove(drag.grab, e); return; }
      const hit = hitAt(e);
      showRing(hit);
      if (!hit) return;
      if (hit.point.distanceTo(drag.last) < view.brush.radius * view.size * 0.25) return;   // even spacing
      drag.last.copy(hit.point);
      stroke(drag.tool, hit.point, drag.sign);
      return;
    }
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.x = e.clientX; drag.y = e.clientY;
    if (drag.kind === "turn") {
      orbit.theta -= dx * 0.008; orbit.phi = Math.min(Math.PI - 0.05, Math.max(0.05, orbit.phi - dy * 0.008));
    } else {
      const k = orbit.dist * 0.0016, right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0),
        up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
      orbit.target.addScaledVector(right, -dx * k).addScaledVector(up, dy * k);
    }
    place();
  });
  const end = () => { drag = null; };
  canvas.addEventListener("pointerup", end); canvas.addEventListener("pointercancel", end);
  canvas.addEventListener("pointerleave", () => { if (!drag) showRing(null); });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    orbit.dist = Math.max(view.size * 0.05, Math.min(view.size * 30, orbit.dist * Math.exp(e.deltaY * 0.0012)));
    place();
  }, { passive: false });
  view.dab = (tool, x, y, z, sign) => { snapshot(); stroke(tool, new THREE.Vector3(x, y, z), sign || 1); };   // tests / scripts
  return view;
}

function forgeMode() {
  const v = forge.view;
  if (!v) return;
  v.setMode(v.mode === "sculpt" ? "view" : "sculpt");
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
    else if (e.key === "[" || e.key === "]") {
      v.brush.radius = Math.min(0.4, Math.max(0.02, v.brush.radius * (e.key === "]" ? 1.15 : 1 / 1.15)));
      const r = document.getElementById("forge-radius"); if (r) r.value = String(v.brush.radius);
    }
  });
});
