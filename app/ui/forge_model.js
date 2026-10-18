// Forge's Model bar (owner 2026-10-18: "primitives, dynomesh ... poly modeling", "loves modular things with sliders").
// Add a primitive and shape it with sliders; click faces to select them, then Extrude / Inset / Delete / Flip /
// Smooth (Catmull-Clark); every last operation keeps a slider that re-does it live (like Blender's redo panel);
// DynaMesh rebuilds any model - a sculpt included - as even quads at the resolution you pick, so you can sculpt
// on, or edit its faces again. The geometry is app/ui/forge_poly.js (GoBuild's operations, GPL-3.0).
"use strict";

Object.assign(ICON_PATHS, {
  poly: '<path d="M12 3.5l8 5v7l-8 5-8-5v-7z"/><circle cx="12" cy="3.5" r="1.4"/><circle cx="20" cy="8.5" r="1.4"/><circle cx="4" cy="8.5" r="1.4"/><circle cx="12" cy="20.5" r="1.4"/>',
  sphere: '<circle cx="12" cy="12" r="8"/><ellipse cx="12" cy="12" rx="8" ry="3"/><path d="M12 4c-3 3-3 13 0 16"/>',
  quadsphere: '<circle cx="12" cy="12" r="8"/><path d="M6.5 6.5c3.5 2 7.5 2 11 0M6.5 17.5c3.5-2 7.5-2 11 0M6.5 6.5c2 3.5 2 7.5 0 11M17.5 6.5c-2 3.5-2 7.5 0 11"/>',
  cylinder: '<ellipse cx="12" cy="6" rx="6.5" ry="2.5"/><path d="M5.5 6v12c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5V6"/>',
  cone: '<path d="M12 3.5L5.5 18M12 3.5L18.5 18"/><ellipse cx="12" cy="18" rx="6.5" ry="2.5"/>',
  torus: '<ellipse cx="12" cy="12" rx="8.5" ry="5.5"/><ellipse cx="12" cy="11.5" rx="3.5" ry="1.8"/>',
  plane: '<path d="M3.5 15l6-6h11l-6 6z"/><path d="M6.5 12h11M12 9l-3 6"/>',
  extrude: '<path d="M5 14.5h14v5H5z"/><path d="M8 14.5V9h8v5.5M12 9V3.5M9.5 6L12 3.5 14.5 6"/>',
  inset: '<path d="M4 4h16v16H4z"/><path d="M8.5 8.5h7v7h-7zM4 4l4.5 4.5M20 4l-4.5 4.5M4 20l4.5-4.5M20 20l-4.5-4.5"/>',
  flip: '<path d="M4 12h16"/><path d="M8 8l4-4.5L16 8M8 16l4 4.5 4-4.5"/>',
  dynamesh: '<path d="M4 4h16v16H4z"/><path d="M4 9.3h16M4 14.7h16M9.3 4v16M14.7 4v16"/>',
  selectall: '<path d="M4 4h16v16H4z" stroke-dasharray="3 2"/><path d="M8 12l3 3 5-6"/>',
});

const forgeModel = { prim: null, last: null, dyna: { res: 96, smooth: 2 } };

function forgeModelBar(viewBar) {
  const mode = forgeBtn("poly", "Model", "Model mode: add primitives, click faces to pick them (Shift adds), extrude, inset, smooth, DynaMesh.",
    () => forgeModelMode(), "forge-model-mode");
  mode.id = "forge-model-mode";
  viewBar.prepend(mode);
  const bar = el("div", "forge-float forge-modelbar"); bar.id = "forge-model"; bar.hidden = true;

  const add = el("div", "forge-model-grid");
  for (const [kind, p] of Object.entries(window.ForgePoly.PRIMITIVES)) {
    const b = forgeBtn(kind === "cube" ? "cube" : kind, p.name, p.what + " Replaces the model (Undo brings it back).", () => forgeAddPrimitive(kind));
    b.dataset.prim = kind; add.append(b);
  }
  const params = el("div", "forge-model-params"); params.id = "forge-model-params";

  const faces = el("div", "forge-model-grid");
  faces.append(
    forgeBtn("extrude", "Extrude", "Pull the picked faces out as one piece (E). The slider below sets how far, live.", () => forgeFaceOp("extrude")),
    forgeBtn("inset", "Inset", "A smaller face inside each picked face (I); the slider sets how far in.", () => forgeFaceOp("inset")),
    forgeBtn("smooth", "Smooth", "Catmull-Clark: every face becomes quads, rounder (Ctrl+number like Maya's smooth).", () => forgeFaceOp("smooth")),
    forgeBtn("flip", "Flip", "Turn the picked faces (or all) inside out.", () => forgeFaceOp("flip")),
    forgeBtn("trash", "Delete", "Delete the picked faces (Delete key).", () => forgeFaceOp("delete")),
    forgeBtn("selectall", "All / none", "Pick every face, or none (A).", () => forgeSelectAll()));
  const redo = el("div", "forge-model-params"); redo.id = "forge-model-redo";

  const dyna = el("div", "forge-model-params");
  dyna.append(
    forgeHSlider("Resolution", "DynaMesh resolution: voxels across the longest side. Higher = finer, slower.", 24, 200, 1, forgeModel.dyna.res, (v) => { forgeModel.dyna.res = v; }),
    forgeHSlider("Relax", "How many smoothing passes take the voxel steps off.", 0, 6, 1, forgeModel.dyna.smooth, (v) => { forgeModel.dyna.smooth = v; }));
  const dynaBtn = forgeBtn("dynamesh", "DynaMesh", "Rebuild the whole model as even quads (like ZBrush's DynaMesh): closes holes, merges overlaps, ready to sculpt on.", () => forgeDynamesh(), "forge-wide");

  bar.append(el("span", "forge-model-head", "Add"), add, params, el("span", "forge-model-head", "Faces"), faces, redo,
    el("span", "forge-model-head", "Remesh"), dyna, dynaBtn);
  return bar;
}

function forgeHSlider(name, what, min, max, step, value, onInput) {
  const wrap = el("label", "forge-hslider");
  wrap.dataset.tipName = name; wrap.dataset.tipWhat = what;
  const top = el("span", "forge-hslider-top");
  const label = el("span", "", name), out = el("span", "forge-hslider-val", String(value));
  top.append(label, out);
  const r = document.createElement("input"); r.type = "range"; r.min = String(min); r.max = String(max); r.step = String(step);
  r.value = String(value); r.setAttribute("aria-label", name);
  r.addEventListener("input", () => { out.textContent = String(+(+r.value).toFixed(2)); onInput(+r.value); });
  wrap.append(top, r);
  return wrap;
}

async function forgeModelView() {
  const v = await forgeViewer();
  if (!v) { forgeSay("3D view is not available here (WebGL).", true); return null; }
  if (!v.onPick) {
    v.onPick = (face, addTo) => {
      if (face < 0) { if (!addTo) v.select([]); return; }
      const s = new Set(addTo ? v.selected : []);
      if (addTo && s.has(face)) s.delete(face); else s.add(face);
      v.select([...s]);
      forgeSay(v.selected.length + " face" + (v.selected.length === 1 ? "" : "s") + " picked");
    };
    v.onChange = () => forgeModelSync();
  }
  return v;
}

async function forgeModelMode(on) {
  const v = await forgeModelView();
  if (!v) return;
  const want = on == null ? v.mode !== "poly" : !!on;
  v.setMode(want ? "poly" : "view");
  document.getElementById("forge-model").hidden = !want;
  document.getElementById("forge-model-mode").classList.toggle("on", want);
  const sc = document.getElementById("forge-sculpt"); if (sc && want) sc.hidden = true;
  const sm = document.getElementById("forge-mode"); if (sm && want) sm.classList.remove("on");
  if (want && !v.poly && v.sm) {   // a sculpt or a loaded .glb: edit it as polygons (DynaMesh first gives quads)
    const t = v.triangles();
    if (t.idx.length / 3 <= 60000) v.showPoly(window.ForgePoly.fromTriangles(t.pos, t.idx), true);
  }
  forgeSay(want ? "Model: add a primitive, or click faces (Shift adds), then Extrude / Inset. Drag still turns the view." : "");
  forgeModelSync();
}

function forgeModelSync() {
  const v = forge.view, params = document.getElementById("forge-model-params");
  if (!params) return;
  params.textContent = "";
  for (const b of document.querySelectorAll("#forge [data-prim]")) b.classList.toggle("on", !!forgeModel.prim && b.dataset.prim === forgeModel.prim.kind);
  if (forgeModel.prim && v && v.poly === forgeModel.prim.poly) {
    const p = window.ForgePoly.PRIMITIVES[forgeModel.prim.kind];
    for (const [k, [def, lo, hi]] of Object.entries(p.params)) {
      const val = forgeModel.prim.opts[k] != null ? forgeModel.prim.opts[k] : def;
      params.append(forgeHSlider(k[0].toUpperCase() + k.slice(1), "Change the " + p.name.toLowerCase() + " live.", lo, hi,
        k === "thickness" ? 0.01 : 1, val, (x) => {
          forgeModel.prim.opts[k] = x;
          const poly = window.ForgePoly.primitive(forgeModel.prim.kind, forgeModel.prim.opts);
          forgeModel.prim.poly = poly;
          forge.view.showPoly(poly, true, true);
        }));
    }
  } else forgeModel.prim = forgeModel.prim && v && v.poly === forgeModel.prim.poly ? forgeModel.prim : null;
  const redo = document.getElementById("forge-model-redo");
  redo.textContent = "";
  const last = forgeModel.last;
  if (last && v && v.poly === last.out && (last.kind === "extrude" || last.kind === "inset")) {
    const ex = last.kind === "extrude";
    redo.append(forgeHSlider(ex ? "Distance" : "Inset", ex ? "How far the last extrude goes (negative pushes in)." : "How far in the last inset goes.",
      ex ? -1 : 0.02, ex ? 1 : 0.9, 0.01, last.amount, (x) => {
        last.amount = x;
        last.out = window.ForgePoly[last.kind](last.base, last.faces, x);
        forge.view.showPoly(last.out, true, true);
        forge.view.select(last.pick(last.out));
      }));
  }
}

async function forgeAddPrimitive(kind) {
  const v = await forgeModelView();
  if (!v) return;
  if (v.mode !== "poly") await forgeModelMode(true);
  const opts = {}, poly = window.ForgePoly.primitive(kind, opts);
  forgeModel.prim = { kind, opts, poly };
  forgeModel.last = null;
  v.showPoly(poly, false);
  forge.model = null;
  document.getElementById("forge-empty").hidden = true;
  v.start();
  forgeSay(window.ForgePoly.PRIMITIVES[kind].name + ": " + poly.f.length + " faces. Shape it with the sliders, or click faces.");
}

function forgeFaceOp(kind) {
  const v = forge.view;
  if (!v || !v.poly) { forgeSay("Add a primitive first (or DynaMesh a sculpt).", true); return; }
  const P = window.ForgePoly, base = v.poly, faces = v.selected.slice();
  if ((kind === "extrude" || kind === "inset" || kind === "delete") && !faces.length) { forgeSay("Click a face first (Shift adds more).", true); return; }
  let out, pick = () => [];
  if (kind === "extrude") {
    out = P.extrude(base, faces, 0.2);
    pick = () => faces;                             // the moved faces keep their numbers: still picked, extrude again
  } else if (kind === "inset") {
    out = P.inset(base, faces, 0.25);
    pick = () => faces;
  } else if (kind === "smooth") {
    if (base.f.length > 40000) { forgeSay("Already very detailed (" + base.f.length.toLocaleString() + " faces).", true); return; }
    out = P.smooth(base);
  } else if (kind === "flip") out = P.flip(base, faces);
  else if (kind === "delete") out = P.deleteFaces(base, faces);
  else return;
  forgeModel.last = { kind, base, faces, amount: kind === "extrude" ? 0.2 : 0.25, out, pick };
  v.showPoly(out, true);
  v.select(pick(out));
  forgeSay(out.f.length.toLocaleString() + " faces");
}

function forgeSelectAll() {
  const v = forge.view;
  if (!v || !v.poly) return;
  v.select(v.selected.length ? [] : v.poly.f.map((_, i) => i));
}

async function forgeDynamesh() {
  const v = await forgeModelView();
  if (!v || !v.sm) { forgeSay("Make or add a model first.", true); return; }
  forgeSay("DynaMesh at " + forgeModel.dyna.res + "...");
  await new Promise((r) => setTimeout(r, 30));      // let the status paint before the work
  const t = v.triangles(), t0 = performance.now();
  let out;
  try { out = window.ForgePoly.dynamesh(t.pos, t.idx, forgeModel.dyna.res, forgeModel.dyna.smooth); }
  catch (exc) { forgeSay("DynaMesh failed: " + exc.message, true); return; }
  if (!out.f.length) { forgeSay("DynaMesh found no closed volume at this resolution - raise it.", true); return; }
  forgeModel.last = null; forgeModel.prim = null;
  v.showPoly(out, true);
  forgeSay("DynaMesh: " + out.f.length.toLocaleString() + " even quads in " + Math.round(performance.now() - t0) + " ms - sculpt on, or edit faces.");
}

document.addEventListener("keydown", (e) => {
  const sheet = document.getElementById("forge");
  if (!sheet || sheet.hidden || !forge.view || forge.view.mode !== "poly") return;
  if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === "e") { e.preventDefault(); e.stopImmediatePropagation(); forgeFaceOp("extrude"); }
  else if (k === "i") { e.preventDefault(); forgeFaceOp("inset"); }
  else if (k === "a") { e.preventDefault(); forgeSelectAll(); }
  else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); forgeFaceOp("delete"); }
}, true);
