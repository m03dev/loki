// Forge's Model bar (owner 2026-10-18: "primitives, dynomesh ... poly modeling", "loves modular things with sliders").
// Add a primitive and shape it with sliders; select vertices, edges or faces the Maya way (F9 F10 F11, click,
// box, double-click loops - app/ui/forge_edit.js), move / rotate / scale them (w e r handles, soft selection b),
// then Extrude / Inset / Delete / Flip /
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
  const mode = forgeBtn("poly", "Model", "Component mode (F8): add primitives; vertices / edges / faces on F9 / F10 / F11 - click, drag a box, double-click an edge for its loop; w / e / r handles; extrude (Ctrl+E), inset, smooth, DynaMesh.",
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

  const sel = el("div", "forge-model-grid");
  for (const [m, icon, name, what] of [["vert", "selvert", "Vertex", "Vertex (F9): click a point, drag a box round several."],
    ["edge", "seledge", "Edge", "Edge (F10): click an edge; double-click selects the whole edge loop."],
    ["face", "selface", "Face", "Face (F11): click a face; double-click selects the whole piece."]]) {
    const b = forgeBtn(icon, name, what, () => forge.view && forge.view.setSelMode && forge.view.setSelMode(m), m === "face" ? "on" : "");
    b.dataset.selmode = m; sel.append(b);
  }
  const xr = forgeBtn("xray", "X-ray", "X-ray (Alt+X): see and select through the model - a box then takes the hidden side too.", () => forge.view && forge.view.setXray());
  xr.dataset.xray = "1";
  sel.append(xr,
    forgeBtn("selectall", "All / none", "Select everything (Ctrl+Shift+A), or nothing (Alt+D).", () => forgeSelectAll()),
    forgeBtn("grow", "More", "Grow the selection by one ring (>).", () => forge.view && forge.view.selectGrow(true)),
    forgeBtn("shrink", "Less", "Shrink the selection by one ring (<).", () => forge.view && forge.view.selectGrow(false)),
    forgeBtn("linked", "Linked", "Select everything connected to the selection (a double-click picks the piece under the mouse).", () => forge.view && forge.view.selectLinked()),
    forgeBtn("invert", "Invert", "Select what is not selected (Ctrl+Shift+I).", () => forge.view && forge.view.selectInvert()));
  const tools = el("div", "forge-model-grid");
  for (const [t, icon, name, what, key] of [["translate", "move", "Move", "A move handle on the selection (w).", "W"],
    ["rotate", "rotate", "Rotate", "A rotate handle on the selection (e).", "E"],
    ["scale", "scale", "Scale", "A scale handle on the selection (r).", "R"]]) {
    const b = forgeBtn(icon, name, what + " Hold x to snap to the grid, v to a vertex, c to an edge.", () => forge.view && forge.view.setTool(t));
    b.dataset.tool = t; b.dataset.key = key; tools.append(b);
  }
  const prop = forgeBtn("magnet", "Proportional", "Soft selection (b): the vertices around the selection follow, fading with distance.",
    () => forge.view && forge.view.setProportional(!forge.view.edit.prop));
  prop.dataset.prop = "1";
  tools.append(prop);
  const propRow = el("div", "forge-model-params");
  propRow.append(forgeHSlider("Falloff radius", "How far soft selection reaches (a share of the model's size).", 0.02, 1, 0.01, 0.25,
    (v) => forge.view && forge.view.setProportional(null, v)));
  const fall = document.createElement("select"); fall.className = "forge-backend forge-falloff"; fall.setAttribute("aria-label", "Falloff");
  fall.dataset.tipName = "Falloff"; fall.dataset.tipWhat = "The curve of the soft-selection pull.";
  for (const f of ["smooth", "sphere", "root", "inverse", "sharp", "linear", "constant"]) { const o = el("option", "", f[0].toUpperCase() + f.slice(1)); o.value = f; fall.append(o); }
  fall.addEventListener("change", () => forge.view && forge.view.setProportional(null, null, fall.value));
  propRow.append(fall);

  const faces = el("div", "forge-model-grid");
  faces.append(
    forgeBtn("extrude", "Extrude", "Pull the picked faces out as one piece (E). The slider below sets how far, live.", () => forgeFaceOp("extrude")),
    forgeBtn("inset", "Inset", "A smaller face inside each picked face (I); the slider sets how far in.", () => forgeFaceOp("inset")),
    forgeBtn("smooth", "Smooth", "Catmull-Clark: every face becomes quads, rounder.", () => forgeFaceOp("smooth")),
    forgeBtn("flip", "Flip", "Turn the picked faces (or all) inside out.", () => forgeFaceOp("flip")),
    forgeBtn("trash", "Delete", "Delete the selection (X or Delete): in vertex / edge mode the faces that use it go too.", () => forgeFaceOp("delete")));
  const redo = el("div", "forge-model-params"); redo.id = "forge-model-redo";

  const dyna = el("div", "forge-model-params");
  dyna.append(
    forgeHSlider("Resolution", "DynaMesh resolution: voxels across the longest side. Higher = finer, slower.", 24, 200, 1, forgeModel.dyna.res, (v) => { forgeModel.dyna.res = v; }),
    forgeHSlider("Relax", "How many smoothing passes take the voxel steps off.", 0, 6, 1, forgeModel.dyna.smooth, (v) => { forgeModel.dyna.smooth = v; }));
  const dynaBtn = forgeBtn("dynamesh", "DynaMesh", "Rebuild the whole model as even quads (like ZBrush's DynaMesh): closes holes, merges overlaps, ready to sculpt on.", () => forgeDynamesh(), "forge-wide");

  bar.append(el("span", "forge-model-head", "Add"), add, params, el("span", "forge-model-head", "Select"), sel,
    el("span", "forge-model-head", "Transform"), tools, propRow, el("span", "forge-model-head", "Faces"), faces, redo,
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
  if (!v.onChange) v.onChange = () => forgeModelSync();
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
    if (t.idx.length / 3 <= 60000) { v.showPoly(window.ForgePoly.fromTriangles(t.pos, t.idx), true); forgeHistReset(); }
  }
  if (want && v.selStats) v.selStats();
  if (want && !v.poly) forgeSay("Components: F9 vertex, F10 edge, F11 face - click, Shift toggles, drag a box, double-click an edge for its loop; w / e / r handles; Alt/Option + mouse turns the view.");
  else if (!want) forgeSay("");
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
        if (forgeModel.hist && forgeModel.hist.ops.length) {         // rebuild the chain, not just this step
          forgeModel.hist.ops[forgeModel.hist.ops.length - 1].amount = x;
          const poly = forgeHistRebuild();
          last.out = poly;
          forge.view.showPoly(poly, true, true);
          forge.view.select(last.pick(poly));
          return;
        }
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
  forgeHistReset();
  forge.model = null;
  document.getElementById("forge-empty").hidden = true;
  v.start();
  forgeSay(window.ForgePoly.PRIMITIVES[kind].name + ": " + poly.f.length + " faces. Shape it with the sliders, or click faces.");
}

// --------------------------------------------------------------------------------- construction history
// docs/FORGE_MAYA.md T6. Every operation that builds the mesh is kept, in order, with the parameters it was
// made with, so any step can be re-opened, changed and the whole model rebuilt from the first one - Maya's
// construction history. The ops were already pure functions of (mesh, faces, amount), so this is the stack.
function forgeHistCopy(value) {
  if (ArrayBuffer.isView(value)) return value.slice();
  if (Array.isArray(value)) return value.map(forgeHistCopy);
  if (value && typeof value === "object") {
    const copy = {};
    for (const [key, item] of Object.entries(value)) copy[key] = forgeHistCopy(item);
    return copy;
  }
  return value;
}

function forgeHistReset() {
  forgeModel.hist = null;
  if (forge.view && forge.view.treeRefresh) forge.view.treeRefresh();
}

function forgeHistApplyOp(base, op) {
  const P = window.ForgePoly;
  switch (op.kind) {
    case "extrude": return P.extrude(base, op.faces, op.amount);
    case "inset": return P.inset(base, op.faces, op.amount);
    case "flip": return P.flip(base, op.faces);
    case "delete": return P.deleteFaces(base, op.faces);
    case "smooth": return P.smooth(base);
    case "deleteVerts": return P.deleteVerts(base, op.verts);
    case "deleteEdges": return P.deleteEdges(base, null, op.edges);
    case "dynamesh": return P.dynamesh(op.src.pos, op.src.idx, op.res, op.smooth);   // its own source, not the base
    default: return base;
  }
}

function forgeHistRebuild() {
  const hist = forgeModel.hist;
  if (!hist) return null;
  let m = hist.base ? window.ForgePoly.clone(hist.base) : null;
  for (const op of hist.ops) m = forgeHistApplyOp(m, op);
  return m;
}

function forgeHistPush(op, base) {
  if (!forgeModel.hist) {
    if (!base && op.kind !== "dynamesh") return;      // DynaMesh starts a history: it IS the first mesh
    forgeModel.hist = { base: base ? window.ForgePoly.clone(base) : null, ops: [] };
  }
  forgeModel.hist.ops.push(op);
  if (forge.view && forge.view.treeRefresh) forge.view.treeRefresh();
}

function forgeHistRebuildShow() {
  const v = forge.view, hist = forgeModel.hist;
  if (!v || !hist) return false;
  // walk the steps in order: the polygonal ones rebuild the mesh, the sculpt ones re-apply their vertices
  let poly = hist.base ? window.ForgePoly.clone(hist.base) : null, sculpts = [], ok = true;
  for (const op of hist.ops) {
    if (op.kind === "sculpt") { sculpts.push(op); continue; }
    if (!poly && op.kind !== "dynamesh") { ok = false; continue; }
    poly = forgeHistApplyOp(poly, op);
  }
  if (poly) v.showPoly(poly, true, true);
  for (const op of sculpts) forgeHistSculpt(op, "to");
  if (v.treeRefresh) v.treeRefresh();
  return ok;
}

// a sculpt stroke (T6c): the welded vertices it moved, with their positions before and after
window.forgeHistPushSculpt = function (op) {
  if (!forgeModel.hist) forgeModel.hist = { base: null, ops: [] };   // the mesh came from the model, not a poly
  forgeModel.hist.ops.push(op);
  if (forge.view && forge.view.treeRefresh) forge.view.treeRefresh();
};

function forgeHistSculpt(op, which) {                 // which: "to" re-applies the stroke, "from" puts it back
  const v = forge.view, sm = v && v.sm;
  if (!sm || !sm.wpos || !op.verts) return false;
  const at = which === "to" ? 4 : 1;                  // each record is [id, fx,fy,fz, tx,ty,tz]
  let n = 0;
  for (let k = 0; k + 6 < op.verts.length; k += 7) {
    const id = op.verts[k];
    if (id * 3 + 2 >= sm.wpos.length) continue;       // the mesh was rebuilt smaller: this record is stale
    sm.wpos[id * 3] = op.verts[k + at]; sm.wpos[id * 3 + 1] = op.verts[k + at + 1]; sm.wpos[id * 3 + 2] = op.verts[k + at + 2];
    n++;
  }
  if (n && typeof forgeSync === "function") {
    forgeSync(sm);
    if (typeof forgeNormals === "function") forgeNormals(sm);
    if (v.refreshMesh) v.refreshMesh();
  }
  return n > 0;
}

// what the panel (app/ui/forge_scene.js) reads and writes
window.forgeHistory = {
  snapshot() { return forgeHistCopy(forgeModel.hist); },
  restore(history) {
    forgeModel.hist = forgeHistCopy(history);
    forgeModel.last = null;
    if (forge.view && forge.view.treeRefresh) forge.view.treeRefresh();
  },
  list() {
    const h = forgeModel.hist;
    if (!h) return [];
    return h.ops.map((o, i) => ({ i: i, kind: o.kind, affected: o.kind === "sculpt" ? o.verts.length / 7 : null,
      amount: o.kind === "dynamesh" ? o.res : (o.amount == null ? null : o.amount) }));
  },
  setAmount(i, value) {
    const h = forgeModel.hist, op = h && h.ops[i];
    if (!op) return false;
    const x = Number(value);
    if (!isFinite(x)) return false;
    if (op.kind === "dynamesh") { op.res = Math.max(16, Math.min(256, Math.round(x))); return forgeHistRebuildShow(); }
    if (op.kind === "sculpt" || op.amount == null) return false;   // a stroke has no number to type
    op.amount = x;
    if (op.kind === "extrude" || op.kind === "inset") {
      forgeModel.last = { kind: op.kind, base: null, faces: op.faces, amount: x, out: null, pick: () => op.faces };
    }
    return forgeHistRebuildShow();
  },
  remove(i) {
    const h = forgeModel.hist, op = h && h.ops[i];
    if (!op) return false;
    if (i === 0 && !h.base && op.kind === "dynamesh" && h.ops.length > 1) {   // DynaMesh made the first mesh
      if (typeof forgeSay === "function") forgeSay("DynaMesh is the first step - it made the mesh the others work on. Delete History instead.", true);
      return false;
    }
    h.ops.splice(i, 1);
    if (op.kind === "sculpt") {                       // removing a stroke puts exactly those vertices back
      forgeHistSculpt(op, "from");
      if (h.ops.length) forgeHistRebuildShow(); else if (forge.view.treeRefresh) forge.view.treeRefresh();
      return true;
    }
    if (!h.ops.length) { forgeHistReset(); return true; }
    return forgeHistRebuildShow();
  },
  clear() { forgeHistReset(); forgeModel.last = null; if (typeof forgeSay === "function") forgeSay("History deleted - the mesh is now the model."); },
};

function forgeFaceOp(kind) {
  const v = forge.view;
  if (!v || !v.poly) { forgeSay("Add a primitive first (or DynaMesh a sculpt).", true); return; }
  const P = window.ForgePoly, base = v.poly, faces = v.selected.slice(), mode = v.edit ? v.edit.mode : "face";
  if (kind === "delete" && mode !== "face" && v.edit && v.edit.sel.v.size) {   // Blender: deleting vertices / edges takes their faces
    const out = mode === "vert" ? P.deleteVerts(base, [...v.edit.sel.v]) : P.deleteEdges(base, null, [...v.edit.sel.e]);
    forgeModel.last = null;
    v.showPoly(out, true);
    forgeHistPush(mode === "vert" ? { kind: "deleteVerts", verts: [...v.edit.sel.v] }
      : { kind: "deleteEdges", edges: [...v.edit.sel.e] }, base);
    forgeSay(out.f.length.toLocaleString() + " faces");
    return;
  }
  if ((kind === "extrude" || kind === "inset" || kind === "delete") && !faces.length) {
    forgeSay(mode === "face" ? "Select a face first (click; Shift adds, drag a box for several)."
      : "Extrude and Inset work on whole faces: select all the corners / edges of a face, or switch to faces (3).", true);
    return;
  }
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
  forgeHistPush({ kind, faces: faces.slice(), amount: (kind === "extrude" || kind === "inset") ? forgeModel.last.amount : null }, base);
  v.select(pick(out));
  forgeSay(out.f.length.toLocaleString() + " faces");
}

function forgeSelectAll() {
  const v = forge.view;
  if (!v || !v.poly) return;
  if (v.selectAll) { v.selectAll(); return; }
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
  forgeModel.last = null;
  forgeHistPush({ kind: "dynamesh", src: { pos: t.pos.slice(), idx: t.idx.slice() },
    res: forgeModel.dyna.res, smooth: forgeModel.dyna.smooth }, null);
  forgeSay("DynaMesh: " + out.f.length.toLocaleString() + " even quads in " + Math.round(performance.now() - t0) + " ms - sculpt on, or edit faces.");
}

// Model mode's keys are Maya's now (app/ui/forge_maya.js) - the owner had Blender's keys removed (2026-10-19).
