// Forge's Modeling Toolkit and the pro polygon tools (owner 2026-10-21: "add poly modeling tools like the loop cut and
// every tool [the pro modeller] has and how they work ... there are rules, things you can and can't do").
//
// The geometry is app/ui/forge_polyops.js (pure functions on the poly cage, each returning { m, sel, warn }); this file
// is what you touch:
//   - one runner (forgeTkRun) for every tool: it takes the selection the tool needs (faces / edges / vertices, converted
//     the pro way when you picked another kind), refuses with the tool's own message when the rules say no (warn),
//     makes the change ONE undo step, records it in the construction history (INPUTS: polyBevel1, polyExtrudeEdge1 ...)
//     and leaves selected what the pro tool leaves selected;
//   - the tool's settings stay live after it ran (Tool Settings in the toolkit, and the INPUTS amount): change Offset or
//     Segments and the step is redone in place, like adjusting polyBevel1's attributes;
//   - context tools: Ctrl+E extrudes faces, edges or vertices - whatever is selected - and hands you the move manipulator;
//     Delete follows the pro rules (edges and vertices DISSOLVE into the faces around them; Ctrl+Delete also cleans up
//     the vertices left on a straight edge; faces delete);
//   - interactive tools: Multi-Cut (click on edges / vertices, Enter or right-click to finish, Esc cancels), Target Weld
//     (click the vertex to move, then the one to weld to), Offset Edge Loop (click an edge);
//   - the Modeling Toolkit panel: a tab beside the Channel Box (Windows > Modeling Toolkit) with selection modes, soft
//     selection, every tool grouped Mesh / Components / Tools, and Tool Settings.
"use strict";

// [id, label, op, takes, params, what]  takes: "f" faces, "e" edges, "v" vertices, "ve" vertices or edges, "fe" ...
// params: [key, label, min, max, step, default]; the first is the one INPUTS shows as the step's amount
const FORGE_TK_TOOLS = {
  extrudeFaces: ["Extrude", "extrudeFaces", "f", [["thickness", "Thickness", -2, 2, 0.01, 0], ["offset", "Offset", -1, 1, 0.01, 0], ["keepTogether", "Keep Faces Together", 0, 1, 1, 1]], "Extrude the faces; drag the manipulator to place them."],
  extrudeEdges: ["Extrude Edge", "extrudeEdges", "e", [["thickness", "Thickness", -2, 2, 0.01, 0], ["offset", "Offset", -1, 1, 0.01, 0]], "Extrude the edges into a strip of faces."],
  extrudeVerts: ["Extrude Vertex", "extrudeVerts", "v", [["length", "Length", -2, 2, 0.01, 0.1], ["width", "Width", 0, 1, 0.01, 0.1]], "Pull each vertex out into a small point."],
  bevel: ["Bevel", "bevel", "fe", [["fraction", "Fraction", 0.01, 1, 0.01, 0.5], ["segments", "Segments", 1, 12, 1, 1]], "Round the selected edges (faces: their border edges)."],
  bridge: ["Bridge", "bridge", "e", [["divisions", "Divisions", 0, 20, 1, 0]], "Join two open border edge chains with faces."],
  poke: ["Poke Face", "poke", "f", [["offset", "Offset", -1, 1, 0.01, 0]], "Add a vertex in the middle of each face."],
  wedge: ["Wedge", "wedge", "fw", [["angle", "Angle", -360, 360, 1, 90], ["divisions", "Divisions", 1, 32, 1, 4]], "Turn the faces round an edge of theirs (pick faces and one edge)."],
  chamferVerts: ["Chamfer Vertex", "chamferVerts", "v", [["width", "Width", 0.01, 1, 0.01, 0.25]], "Cut each corner off."],
  collapse: ["Collapse", "collapse", "fe", [], "Shrink each edge or face to its centre point."],
  connect: ["Connect", "connect", "ve", [], "Join the selected edges' middles (or the selected vertices) across their faces."],
  detach: ["Detach", "detach", "ve", [], "Split the vertices so each face has its own."],
  dissolveEdges: ["Delete Edge", "dissolveEdges", "e", [["cleanVerts", "Clean up vertices", 0, 1, 1, 0]], "Remove the edges; their faces merge."],
  dissolveVerts: ["Delete Vertex", "dissolveVerts", "v", [], "Remove the vertices; their faces merge."],
  triangulate: ["Triangulate", "triangulateFaces", "f*", [], "Split the faces into triangles."],
  quadrangulate: ["Quadrangulate", "quadrangulate", "f*", [], "Merge triangle pairs into quads."],
  duplicateFaces: ["Duplicate Face", "duplicateFaces", "f", [], "Copy the faces (a new piece of this mesh)."],
  extractFaces: ["Extract", "extractFaces", "f", [], "Cut the faces off into their own piece."],
  averageVerts: ["Average Vertices", "averageVerts", "v*", [["iterations", "Iterations", 1, 20, 1, 1]], "Smooth the selected vertices' positions."],
  relax: ["Relax", "relax", "v*", [["iterations", "Iterations", 1, 20, 1, 3]], "Relax the vertices (borders stay)."],
  circularize: ["Circularize", "circularize", "fv", [], "Lay the selected loop out on a circle."],
  spinEdge: ["Spin Edge", "spinEdge", "e", [["dir", "Direction", -1, 1, 2, 1]], "Turn each edge to the next corners of its two faces."],
  slideEdge: ["Slide Edge", "slideEdge", "e", [["t", "Slide", -1, 1, 0.01, 0.3]], "Slide the edges along the edges beside them."],
  fillHole: ["Fill Hole", null, "e", [], "Close the holes the selection touches."],
};
// the construction-history node each tool leaves (INPUTS)
const FORGE_TK_NODES = { extrudeFaces: "polyExtrudeFace", extrudeEdges: "polyExtrudeEdge", extrudeVerts: "polyExtrudeVertex", bevel: "polyBevel",
  bridge: "polyBridgeEdge", poke: "polyPoke", wedge: "polyWedgeFace", chamferVerts: "polyChamferVtx", collapse: "polyCollapseEdge",
  connect: "polyConnectComponents", detach: "polySplitVert", dissolveEdges: "polyDelEdge", dissolveVerts: "polyDelVertex",
  triangulateFaces: "polyTriangulate", triangulate: "polyTriangulate", quadrangulate: "polyQuad", duplicateFaces: "polyChipOff", extractFaces: "polyChipOff",
  averageVerts: "polyAverageVertex", relax: "polyAverageVertex", circularize: "polyCircularize", spinEdge: "polyFlipEdge",
  slideEdge: "polyTweak", multiCut: "polySplit", targetWeld: "polyMergeVert", offsetEdgeLoop: "polySplitRing", sliceFaces: "polySplit" };
if (typeof FORGE_HIST_NODE !== "undefined") Object.assign(FORGE_HIST_NODE, { op: "polyModifier" });

const forgeTk = { last: null, tool: null };          // last: the op whose settings are live; tool: an interactive tool

function forgeTkView() { return typeof forge !== "undefined" && forge.view && forge.view.poly ? forge.view : null; }
function forgeTkSay(t, bad) { if (typeof forgeSay === "function") forgeSay(t, bad); }

/** The selection as the tools take it: vertex ids, edges as vertex pairs, face ids (and which kind is picked). */
function forgeTkSel(v) {
  const s = v.edit && v.edit.sel;
  return { mode: v.edit ? v.edit.mode : "face", v: s ? [...s.v] : [], e: v.edgePairs ? v.edgePairs() : [], f: s ? [...s.f] : [] };
}

/** Put a tool's result selection { v, e: [[a,b]], f } on the mesh, in the component mode it belongs to. */
function forgeTkSelect(v, sel) {
  if (!sel || !v.selectItems) return;
  const f = (sel.f || []).filter((i) => i >= 0 && i < v.poly.f.length);
  const e = (sel.e || []).map(([a, b]) => v.edgeIdOf(a, b)).filter((i) => i >= 0);
  const vs = (sel.v || []).filter((i) => v.poly.v[i]);
  const kind = f.length ? "face" : e.length ? "edge" : vs.length ? "vert" : null;
  if (!kind) { v.selectItems(v.edit.mode, [], "set"); return; }
  if (v.setSelMode && v.edit.mode !== kind) v.setSelMode(kind);
  v.selectItems(kind, kind === "face" ? f : kind === "edge" ? e : vs, "set");
}

// the items a tool works on, from what is picked (the pro tools convert: an edge tool on faces takes their edges ...)
function forgeTkItems(v, takes, sel) {
  const P = window.ForgePoly, T = P.topology(v.poly);
  const allF = () => v.poly.f.map((_, i) => i);
  const edgesOfFaces = (faces) => { const out = new Map(); for (const fi of faces) { const f = v.poly.f[fi]; for (let k = 0; k < f.length; k++) { const a = f[k], b = f[(k + 1) % f.length]; out.set(Math.min(a, b) + "," + Math.max(a, b), [a, b]); } } return [...out.values()]; };
  const vertsOf = () => [...new Set([...sel.v, ...sel.e.flat(), ...sel.f.flatMap((fi) => v.poly.f[fi])])];
  switch (takes.replace("*", "")) {
    case "f": return sel.f.length ? sel.f : (takes.endsWith("*") ? allF() : null);
    case "e": return sel.e.length ? sel.e : (sel.f.length ? edgesOfFaces(sel.f) : null);
    case "v": { const vs = vertsOf(); return vs.length ? vs : (takes.endsWith("*") ? v.poly.v.map((_, i) => i) : null); }
    case "fe": return sel.mode === "face" && sel.f.length ? { f: sel.f } : sel.e.length ? { e: sel.e } : sel.f.length ? { f: sel.f } : null;
    case "ve": return sel.mode === "vert" && sel.v.length ? { v: sel.v } : sel.e.length ? { e: sel.e } : sel.v.length ? { v: sel.v } : null;
    case "fv": return sel.f.length ? { f: sel.f } : sel.v.length ? { v: sel.v } : sel.e.length ? { e: sel.e } : null;
    case "fw": {                                      // Wedge: the faces, turned about a border edge of theirs
      if (!sel.f.length) return null;
      const uses = new Map();
      for (const e of edgesOfFaces(sel.f)) uses.set(e.join(","), 0);
      for (const fi of sel.f) { const f = v.poly.f[fi]; for (let k = 0; k < f.length; k++) { const a = f[k], b = f[(k + 1) % f.length]; const key = Math.min(a, b) + "," + Math.max(a, b); uses.set(key, (uses.get(key) || 0) + 1); } }
      const border = [...uses.entries()].filter(([, n]) => n === 1).map(([k]) => k.split(",").map(Number));
      return border.length ? { faces: sel.f, hinge: border[0] } : null;
    }
    default: return null;
  }
  void T;
}
const FORGE_TK_NEED = { f: "Select faces first (F11).", e: "Select edges first (F10).", v: "Select vertices first (F9).",
  fe: "Select edges or faces first.", ve: "Select vertices or edges first.", fv: "Select a loop of vertices or faces first." };

/** Call a polyops function, whatever argument shape it takes: (m, items, opts) */
function forgeTkCall(op, m, items, opts) {
  const P = window.ForgePoly, fn = P && P[op];
  if (typeof fn !== "function") return { m: m, sel: null, warn: "This tool is not in this build of Forge yet." };
  let out;
  opts = opts || {};
  // the ops whose settings are plain arguments, not an options object (forge_polyops.js)
  const call = { slideEdge: () => fn(m, items, +opts.t || 0), spinEdge: () => fn(m, items, +opts.dir || 1),
    targetWeld: () => fn(m, items.from, items.to), wedge: () => fn(m, items.faces, items.hinge, opts) }[op];
  try { out = call ? call() : fn(m, items, opts); } catch (exc) { return { m: m, sel: null, warn: (exc && exc.message) || String(exc) }; }
  if (!out) return { m: m, sel: null, warn: "Nothing changed." };
  if (out.v && out.f && !out.m) return { m: out, sel: null, warn: "" };     // a bare mesh
  return { m: out.m || m, sel: out.sel || null, warn: out.warn || "" };
}

/** Run a tool on the selection: one undo step, one history step, the pro selection afterwards. */
function forgeTkRun(id, override) {
  const v = forgeTkView();
  if (!v) { forgeTkSay("Edit a polygon mesh first: Create a primitive, or DynaMesh a sculpt.", true); return false; }
  const tool = FORGE_TK_TOOLS[id];
  if (!tool) return false;
  if (id === "fillHole") { if (typeof forgeMeshOp === "function") forgeMeshOp("fillHole"); return true; }
  const [label, op, takes, params] = tool;
  const sel = forgeTkSel(v);
  const items = forgeTkItems(v, takes, sel);
  if (items == null) { forgeTkSay(label + ": " + (FORGE_TK_NEED[takes.replace("*", "")] || "select components first."), true); return false; }
  const opts = {};
  for (const [k, , , , , def] of params) opts[k] = forgeTkPref(id, k, def);
  if (override) Object.assign(opts, override);
  if (params.some((p) => p[0] === "keepTogether")) opts.keepTogether = !!opts.keepTogether;
  if (params.some((p) => p[0] === "cleanVerts")) opts.cleanVerts = !!opts.cleanVerts;
  const base = v.poly;
  const res = forgeTkCall(op, base, items, opts);
  if (res.warn) { forgeTkSay(/^[\w ]+: /.test(res.warn) ? res.warn : label + ": " + res.warn, true); return false; }
  if (res.m === base) { forgeTkSay(label + ": nothing to do here.", true); return false; }
  if (v.undoOpen) v.undoOpen(label);
  try {
    v.showPoly(res.m, true);
    const rec = { kind: "op", op: op, tool: id, items: items, params: Object.assign({}, opts), main: params[0] ? params[0][0] : null };
    if (typeof forgeHistPush === "function") forgeHistPush(rec, base);
    forgeTk.last = { id: id, rec: rec, histIndex: window.forgeHistory ? window.forgeHistory.list().length - 1 : -1 };
    forgeTkSelect(v, res.sel);
    if (typeof forgeModel !== "undefined") { forgeModel.last = null; forgeModel.prim = null; }
  } finally { if (v.undoClose) v.undoClose(); }
  forgeTkSay(label + (res.m.f.length !== base.f.length ? ": " + res.m.f.length.toLocaleString() + " faces." : "."));
  forgeTkSettings();
  if (typeof forgeModelSync === "function") forgeModelSync();
  return true;
}

/** Change a setting of the last tool and redo it in place (no new undo step). */
function forgeTkTweak(key, value) {
  const L = forgeTk.last, H = window.forgeHistory, v = forgeTkView();
  if (!L || !H || !v) return false;
  const h = typeof forgeModel !== "undefined" && forgeModel.hist;
  if (!h || h.ops[L.histIndex] !== L.rec) { forgeTk.last = null; forgeTkSettings(); return false; }
  L.rec.params[key] = typeof L.rec.params[key] === "boolean" ? !!+value : +value;
  forgeTkPref(L.id, key, +value, true);
  const ok = typeof forgeHistRebuildShow === "function" ? forgeHistRebuildShow() : false;
  return ok;
}

// remembered tool settings (the pro option boxes keep what you set last)
function forgeTkPref(id, key, def, set) {
  const k = "loki-forge-tk-" + id + "-" + key;
  try {
    if (set) { localStorage.setItem(k, String(def)); return def; }
    const s = localStorage.getItem(k);
    return s == null ? def : +s;
  } catch (_) { return def; }
}

// ---------------------------------------------------------------- the context tools
/** Ctrl+E / Shift + drag: extrude what is selected (faces, edges or vertices), then the move manipulator. */
function forgeTkExtrude() {
  const v = forgeTkView();
  if (!v) return false;
  const sel = forgeTkSel(v);
  const id = sel.mode === "face" && sel.f.length ? "extrudeFaces" : sel.mode === "edge" && sel.e.length ? "extrudeEdges"
    : sel.mode === "vert" && sel.v.length ? "extrudeVerts" : sel.f.length ? "extrudeFaces" : sel.e.length ? "extrudeEdges" : sel.v.length ? "extrudeVerts" : null;
  if (!id) { forgeTkSay("Extrude: select faces, edges or vertices first.", true); return false; }
  const ok = forgeTkRun(id, id === "extrudeVerts" ? null : { thickness: 0, offset: 0 });
  if (ok && v.setTool && !(v.tool && v.tool())) v.setTool("translate");
  return ok;
}

/** Delete in component mode, the pro rules: faces go; edges and vertices dissolve (clean: Ctrl+Delete). */
function forgeTkDelete(clean) {
  const v = forgeTkView();
  if (!v) return false;
  const sel = forgeTkSel(v);
  if (sel.mode === "face" && sel.f.length) { if (typeof forgeFaceOp === "function") forgeFaceOp("delete"); return true; }
  if (sel.mode === "edge" && sel.e.length && window.ForgePoly.dissolveEdges) return forgeTkRun("dissolveEdges", { cleanVerts: clean ? 1 : 0 });
  if (sel.mode === "vert" && sel.v.length && window.ForgePoly.dissolveVerts) return forgeTkRun("dissolveVerts");
  if (typeof forgeFaceOp === "function") forgeFaceOp("delete");
  return true;
}

// ---------------------------------------------------------------- interactive tools
// Multi-Cut: click points on edges / vertices; each pair that shares a face cuts it. Enter / right-click finishes,
// Backspace takes the last point back, Esc cancels. Target Weld: click the vertex to move, then the target.
// Offset Edge Loop: click an edge.
function forgeTkTool(kind) {
  const v = forgeTkView();
  if (!v) { forgeTkSay("Edit a polygon mesh first.", true); return false; }
  forgeTkToolEnd(false);
  if (kind === "targetWeld" && v.setSelMode) v.setSelMode("vert");
  if (kind === "offsetEdgeLoop" && v.setSelMode) v.setSelMode("edge");
  forgeTk.tool = { kind: kind, pts: [], marks: [] };
  const help = { multiCut: "Multi-Cut: click on edges or vertices to cut; Enter or right-click finishes, Backspace undoes a point, Esc cancels.",
    targetWeld: "Target Weld: click the vertex to move, then the vertex to weld it to.",
    offsetEdgeLoop: "Offset Edge Loop: click an edge - two loops are added either side of its loop." }[kind];
  forgeTkSay(help);
  const h = document.getElementById("fmy-help"); if (h) h.textContent = help;
  document.body.classList.add("forge-tk-tool");
  return true;
}
function forgeTkToolEnd(apply) {
  const t = forgeTk.tool, v = forge.view;
  if (!t) return;
  forgeTk.tool = null;
  document.body.classList.remove("forge-tk-tool");
  if (v && v.holder) for (const mk of t.marks) { if (mk.parent) mk.parent.remove(mk); mk.geometry.dispose(); mk.material.dispose(); }
  if (v) v.dirty = true;
  if (apply && t.kind === "multiCut" && t.pts.length >= 2) forgeTkApplyOp("multiCut", t.pts.map(({ v: vi, e, t: tt }) => (vi != null ? { v: vi } : { e: e, t: tt })), {}, "Multi-Cut");
}
function forgeTkMark(v, at) {
  const THREE = v.THREE;
  const g = new THREE.SphereGeometry(Math.max(1e-3, (v.size || 1) * 0.008), 8, 6);
  const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: 0xff3d3d, depthTest: false }));
  m.position.fromArray(at); m.renderOrder = 10; m.raycast = () => {};
  v.holder.add(m); v.dirty = true;
  return m;
}
/** Run an op with explicit items (the interactive tools), as one undo + history step. */
function forgeTkApplyOp(op, items, opts, label) {
  const v = forgeTkView();
  if (!v) return false;
  const base = v.poly, res = forgeTkCall(op, base, items, opts);
  if (res.warn || res.m === base) { forgeTkSay(res.warn && /^[\w ]+: /.test(res.warn) ? res.warn : label + ": " + (res.warn || "nothing to do here."), true); return false; }
  if (v.undoOpen) v.undoOpen(label);
  try {
    v.showPoly(res.m, true);
    if (typeof forgeHistPush === "function") forgeHistPush({ kind: "op", op: op, tool: op, items: items, params: Object.assign({}, opts), main: null }, base);
    forgeTkSelect(v, res.sel);
  } finally { if (v.undoClose) v.undoClose(); }
  forgeTkSay(label + ": " + res.m.f.length.toLocaleString() + " faces.");
  return true;
}
// the viewport clicks while an interactive tool is on (capture: before selection)
function forgeTkPointer(e) {
  const t = forgeTk.tool, v = forge.view;
  if (!t || !v || v.mode !== "poly" || e.altKey) return;
  if (e.button === 2) { e.preventDefault(); e.stopImmediatePropagation(); forgeTkToolEnd(true); return; }
  if (e.button !== 0) return;
  e.preventDefault(); e.stopImmediatePropagation();
  const r = v.canvas.getBoundingClientRect(), pt = [e.clientX - r.left, e.clientY - r.top];
  const hit = v.cutPointAt ? v.cutPointAt(pt) : null;
  if (!hit || hit.face != null) { forgeTkSay("Click on an edge or a vertex.", true); return; }
  if (t.kind === "multiCut") { t.pts.push(hit); t.marks.push(forgeTkMark(v, hit.at)); forgeTkSay("Multi-Cut: " + t.pts.length + " point" + (t.pts.length === 1 ? "" : "s") + " - Enter finishes."); return; }
  if (t.kind === "targetWeld") {
    if (hit.v == null) { forgeTkSay("Target Weld: click a vertex.", true); return; }
    t.pts.push(hit); t.marks.push(forgeTkMark(v, hit.at));
    if (t.pts.length === 2) { const [a, b] = t.pts; forgeTkToolEnd(false); forgeTkApplyOp("targetWeld", { from: a.v, to: b.v }, {}, "Target Weld"); }
    return;
  }
  if (t.kind === "offsetEdgeLoop") {
    if (!hit.e) { forgeTkSay("Offset Edge Loop: click an edge.", true); return; }
    forgeTkToolEnd(false);
    forgeTkApplyOp("offsetEdgeLoop", hit.e, { distance: forgeTkPref("offsetEdgeLoop", "distance", 0.25) }, "Offset Edge Loop");
  }
}
function forgeTkKey(e) {
  const t = forgeTk.tool;
  if (!t) return;
  if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); forgeTkToolEnd(false); forgeTkSay("Tool cancelled."); }
  else if (e.key === "Enter") { e.preventDefault(); e.stopImmediatePropagation(); forgeTkToolEnd(true); }
  else if (e.key === "Backspace" && t.pts.length) { e.preventDefault(); e.stopImmediatePropagation(); t.pts.pop(); const mk = t.marks.pop(); if (mk && mk.parent) mk.parent.remove(mk); if (forge.view) forge.view.dirty = true; }
}
document.addEventListener("keydown", forgeTkKey, true);
document.addEventListener("pointerdown", (e) => { if (forgeTk.tool && e.target && e.target.id === "forge-view") forgeTkPointer(e); }, true);
document.addEventListener("contextmenu", (e) => { if (forgeTk.tool && e.target && e.target.id === "forge-view") e.preventDefault(); }, true);

// ---------------------------------------------------------------- the commands (menus, hotbox, marking menus, hotkeys)
function forgeTkCommands() {
  if (typeof FORGE_PRO_CMDS === "undefined") return;
  const run = (id) => () => { forgeTkRun(id); return ""; };
  const C = FORGE_PRO_CMDS;
  const comp = (v) => !!(v && v.mode === "poly");
  const toComp = async (v, sel) => { if (!comp(v) && typeof forgeProComponents === "function") await forgeProComponents(v, sel); };
  Object.assign(C, {
    extrude: ["Extrude", async (v) => { if (!comp(v)) { await toComp(v, "face"); return "Pick faces, edges or vertices, then Ctrl+E."; } forgeTkExtrude(); return ""; }],
    bevel: ["Bevel", run("bevel")],
    bridge: ["Bridge", run("bridge")],
    poke: ["Poke Face", run("poke")],
    wedge: ["Wedge", run("wedge")],
    chamfer: ["Chamfer Vertex", run("chamferVerts")],
    collapse: ["Collapse", run("collapse")],
    connect: ["Connect", run("connect")],
    detach: ["Detach", run("detach")],
    triangulate: ["Triangulate", run("triangulate")],
    quadrangulate: ["Quadrangulate", run("quadrangulate")],
    duplicateFace: ["Duplicate Face", run("duplicateFaces")],
    extractFace: ["Extract", run("extractFaces")],
    averageVerts: ["Average Vertices", run("averageVerts")],
    relax: ["Relax", run("relax")],
    circularize: ["Circularize", run("circularize")],
    spinEdge: ["Spin Edge Forward", run("spinEdge")],
    spinEdgeBack: ["Spin Edge Backward", () => { forgeTkRun("spinEdge", { dir: -1 }); return ""; }],
    slideEdge: ["Slide Edge", run("slideEdge")],
    deleteEdgeVert: ["Delete Edge/Vertex", () => { forgeTkDelete(true); return ""; }],
    camSelAuto: ["Camera Based Selection: Automatic", (v) => { if (v.cameraBasedSelection) v.cameraBasedSelection("auto"); forgeTkSyncModes(); return "Selection: only what you see when shaded; through the model in wireframe (4) and X-ray."; }],
    camSelOn: ["Camera Based Selection: On", (v) => { if (v.cameraBasedSelection) v.cameraBasedSelection("on"); forgeTkSyncModes(); return "Selection: only what you can see."; }],
    camSelOff: ["Camera Based Selection: Off (select through)", (v) => { if (v.cameraBasedSelection) v.cameraBasedSelection("off"); forgeTkSyncModes(); return "Selection: through the model - a marquee takes the hidden vertices too."; }],
    backfaces: ["Backface Culling", (v) => forgeTkBackfaces(v)],
    multiCut: ["Multi-Cut", async (v) => { await toComp(v, "edge"); forgeTkTool("multiCut"); return ""; }],
    targetWeld: ["Target Weld", async (v) => { await toComp(v, "vert"); forgeTkTool("targetWeld"); return ""; }],
    offsetEdgeLoop: ["Offset Edge Loop", async (v) => { await toComp(v, "edge"); forgeTkTool("offsetEdgeLoop"); return ""; }],
  });
  // Delete in component mode follows the pro rules (dissolve edges / vertices); objects as before
  const del = C.delete;
  C.delete = ["Delete", (v) => { if (comp(v)) { forgeTkDelete(false); return ""; } return del[1](v); }];
  C.deleteComp = ["Delete Components", () => { forgeTkDelete(false); return ""; }];
  C.winToolkit = ["Modeling Toolkit", () => { forgeTkPanel(true); return "Modeling Toolkit (beside the Channel Box)."; }];
}

// Display > Backface Culling: faces pointing away from the camera are not drawn (every object), and in shaded mode
// what is behind them cannot be picked through either way
function forgeTkBackfaces(v, on) {
  if (!v || !v.THREE) return "";
  const was = v.backfaceCull !== false;              // three.js draws front faces only by default: culling starts on
  v.backfaceCull = on == null ? !was : !!on;
  let scene = v.holder; while (scene.parent) scene = scene.parent;
  scene.traverse((o) => {
    if (!o.isMesh || !(o.name === "forge" || o.name === "shape" || o.name === "forge-smooth")) return;
    for (const m of Array.isArray(o.material) ? o.material : [o.material]) { m.side = v.backfaceCull ? v.THREE.FrontSide : v.THREE.DoubleSide; m.needsUpdate = true; }
  });
  v.dirty = true;
  forgeTkSyncModes();
  return v.backfaceCull ? "Backface culling on." : "Backface culling off.";
}

// ---------------------------------------------------------------- the Modeling Toolkit panel
const FORGE_TK_GROUPS = [
  ["Mesh", ["combine", "separate", "extractFace", "mirror", "smooth", "triangulate", "quadrangulate", "fillHole", "dynamesh"]],
  ["Components", ["extrude", "bevel", "bridge", "chamfer", "circularize", "collapse", "connect", "detach", "merge", "mergeCenter",
    "poke", "wedge", "averageVerts", "relax", "spinEdge", "duplicateFace", "deleteEdgeVert"]],
  ["Tools", ["edgeLoop", "offsetEdgeLoop", "multiCut", "targetWeld", "slideEdge", "softSel"]],
];
function forgeTkPanel(show) {
  const col = document.getElementById("forge-chancol");
  if (!col) return null;
  let tabs = document.getElementById("forge-tk-tabs"), box = document.getElementById("forge-toolkit");
  if (!box) {
    tabs = document.createElement("div"); tabs.id = "forge-tk-tabs"; tabs.className = "forge-tk-tabs";
    for (const [k, label] of [["channel", "Channel Box"], ["toolkit", "Modeling Toolkit"]]) {
      const b = document.createElement("button"); b.type = "button"; b.className = "forge-tk-tab"; b.dataset.tab = k; b.textContent = label;
      b.addEventListener("click", () => forgeTkPanel(k === "toolkit"));
      tabs.append(b);
    }
    col.prepend(tabs);
    box = document.createElement("div"); box.id = "forge-toolkit"; box.className = "forge-tk"; box.hidden = true;
    col.append(box);
    forgeTkBuild(box);
  }
  const on = show == null ? box.hidden : !!show;
  box.hidden = !on;
  for (const id of ["forge-channel", "forge-history"]) { const e = document.getElementById(id); if (e) e.classList.toggle("forge-tk-away", on); }
  for (const b of tabs.querySelectorAll(".forge-tk-tab")) b.classList.toggle("on", (b.dataset.tab === "toolkit") === on);
  if (on) { const p = typeof forgeProPanels === "function" ? forgeProPanels() : {}; if (!p.channel && typeof forgeProPanel === "function") forgeProPanel("channel", true); forgeTkSettings(); forgeTkSyncModes(); }
  try { localStorage.setItem("loki-forge-tk-open", on ? "1" : "0"); } catch (_) { /* private mode */ }
  return box;
}
function forgeTkBuild(box) {
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  // selection
  const selSec = mk("details", "forge-tk-sec"); selSec.open = true; selSec.append(mk("summary", "", "Selection"));
  const modes = mk("div", "forge-tk-modes");
  for (const [id, label] of [["objectMode", "Object"], ["vertex", "Vertex"], ["edge", "Edge"], ["face", "Face"]]) {
    const b = mk("button", "forge-tk-mode", label); b.type = "button"; b.dataset.proId = id;
    b.addEventListener("click", async () => { if (typeof forgeProRun === "function") await forgeProRun(forge.view, id); forgeTkSyncModes(); });
    modes.append(b);
  }
  const soft = mk("label", "forge-tk-row");
  const softBox = document.createElement("input"); softBox.type = "checkbox"; softBox.id = "forge-tk-soft";
  softBox.addEventListener("change", () => { const v = forge.view; if (v && v.setProportional) v.setProportional(softBox.checked); });
  soft.append(softBox, mk("span", "", "Soft Selection (b)"));
  const rad = forgeTkSlider("Falloff radius", 0.02, 2, 0.01, () => (forge.view && forge.view.edit ? forge.view.edit.propRadius : 0.25),
    (x) => { const v = forge.view; if (v && v.edit) { v.edit.propRadius = x; if (v.reweigh) v.reweigh(); } });
  const cam = mk("label", "forge-tk-row");
  const camSel = document.createElement("select"); camSel.id = "forge-tk-camsel"; camSel.className = "forge-tk-select";
  for (const [k, t] of [["auto", "Camera based: Automatic"], ["on", "Camera based: On (only what you see)"], ["off", "Off - select through"]]) {
    const o = document.createElement("option"); o.value = k; o.textContent = t; camSel.append(o);
  }
  camSel.title = "Whether a marquee / click can take vertices, edges and faces you cannot see (the back of the model).";
  camSel.addEventListener("change", () => { const v = forge.view; if (v && v.cameraBasedSelection) v.cameraBasedSelection(camSel.value); });
  cam.append(camSel);
  const bf = mk("label", "forge-tk-row");
  const bfBox = document.createElement("input"); bfBox.type = "checkbox"; bfBox.id = "forge-tk-backface";
  bfBox.addEventListener("change", () => forgeTkBackfaces(forge.view, bfBox.checked));
  bf.append(bfBox, mk("span", "", "Backface culling (hide faces pointing away)"));
  const loops = mk("div", "forge-tk-grid");
  for (const id of ["loopSel", "ringSel", "grow", "shrink", "invert", "selectAll"]) loops.append(forgeTkBtn(id));
  selSec.append(modes, cam, bf, soft, rad, loops);
  box.append(selSec);
  for (const [g, ids] of FORGE_TK_GROUPS) {
    const sec = mk("details", "forge-tk-sec"); sec.open = true; sec.append(mk("summary", "", g));
    const grid = mk("div", "forge-tk-grid");
    for (const id of ids) { const b = forgeTkBtn(id); if (b) grid.append(b); }
    sec.append(grid); box.append(sec);
  }
  const set = mk("details", "forge-tk-sec forge-tk-settings"); set.open = true; set.id = "forge-tk-settings";
  set.append(mk("summary", "", "Tool Settings"), mk("div", "forge-tk-setbody"));
  box.append(set);
}
function forgeTkBtn(id) {
  const c = typeof FORGE_PRO_CMDS !== "undefined" && FORGE_PRO_CMDS[id];
  if (!c) return null;
  const b = document.createElement("button"); b.type = "button"; b.className = "forge-tk-btn"; b.dataset.proId = id; b.textContent = c[0];
  const keys = window.forgeHotkeys ? window.forgeHotkeys.keysFor(id).map(window.forgeHotkeys.label).join(", ") : "";
  const tool = Object.entries(FORGE_TK_TOOLS).find(([tid]) => FORGE_PRO_CMDS[id] && FORGE_TK_TOOLS[tid][0] === c[0]);
  b.title = (tool ? tool[1][4] + " " : "") + (keys ? "(" + keys + ")" : "");
  if (!c[1]) b.disabled = true;
  b.addEventListener("click", () => { if (typeof forgeProRun === "function") forgeProRun(forge.view, id); });
  return b;
}
function forgeTkSlider(label, min, max, step, get, set) {
  const row = document.createElement("label"); row.className = "forge-tk-slider";
  const name = document.createElement("span"); name.textContent = label;
  const r = document.createElement("input"); r.type = "range"; r.min = String(min); r.max = String(max); r.step = String(step); r.value = String(get());
  const n = document.createElement("input"); n.type = "number"; n.min = String(min); n.max = String(max); n.step = String(step); n.value = String(get());
  const put = (x) => { r.value = String(x); n.value = String(Math.round(x * 1000) / 1000); set(x); };
  r.addEventListener("input", () => put(+r.value));
  n.addEventListener("change", () => put(+n.value));
  n.addEventListener("keydown", (e) => e.stopPropagation());
  row.append(name, r, n);
  return row;
}
/** Tool Settings: the last tool's settings, live (changing one redoes the step). */
function forgeTkSettings() {
  const body = document.querySelector("#forge-tk-settings .forge-tk-setbody");
  if (!body) return;
  body.textContent = "";
  const L = forgeTk.last;
  if (!L) { const p = document.createElement("p"); p.className = "forge-tk-note"; p.textContent = "Run a tool and its settings show here - change them and the step is redone."; body.append(p); return; }
  const tool = FORGE_TK_TOOLS[L.id];
  const head = document.createElement("div"); head.className = "forge-tk-sethead";
  head.textContent = tool[0] + " - " + (FORGE_TK_NODES[L.rec.op] || "poly") + " (INPUTS)";
  body.append(head);
  for (const [k, label, min, max, step] of tool[3]) {
    if (max - min === 1 && step === 1) {
      const row = document.createElement("label"); row.className = "forge-tk-row";
      const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !!L.rec.params[k];
      cb.addEventListener("change", () => forgeTkTweak(k, cb.checked ? 1 : 0));
      row.append(cb, document.createTextNode(" " + label)); body.append(row);
    } else body.append(forgeTkSlider(label, min, max, step, () => +L.rec.params[k] || 0, (x) => forgeTkTweak(k, x)));
  }
  if (!tool[3].length) { const p = document.createElement("p"); p.className = "forge-tk-note"; p.textContent = "This tool has no settings."; body.append(p); }
}
function forgeTkSyncModes() {
  const v = forge.view, box = document.getElementById("forge-toolkit");
  if (!box || !v) return;
  const comp = v.mode === "poly", mode = v.edit ? v.edit.mode : "";
  for (const b of box.querySelectorAll(".forge-tk-mode")) {
    const id = b.dataset.proId;
    b.classList.toggle("on", id === "objectMode" ? !comp : comp && ({ vertex: "vert", edge: "edge", face: "face" })[id] === mode);
  }
  const soft = document.getElementById("forge-tk-soft"); if (soft) soft.checked = !!(v.edit && v.edit.prop);
  const cs = document.getElementById("forge-tk-camsel"); if (cs && v.cameraBasedSelection) cs.value = v.cameraBasedSelection();
  const bf = document.getElementById("forge-tk-backface"); if (bf) bf.checked = v.backfaceCull !== false;
}

forgeTkCommands();
window.forgeToolkit = { run: forgeTkRun, tweak: forgeTkTweak, extrude: forgeTkExtrude, del: forgeTkDelete, tool: forgeTkTool,
  end: forgeTkToolEnd, panel: forgeTkPanel, tools: FORGE_TK_TOOLS, state: forgeTk, select: forgeTkSelect, sel: () => forgeTk.tool };

// ---------------------------------------------------------------- the In-View Editor (t: Show Manipulator Tool)
// (owner 2026-10-21: "press t and get the tools to edit whatever action - as soon as you bridge you get them and then
// you adjust the settings"). The pro In-View Editor: right after a tool runs, a small panel opens in the viewport
// with that step's attributes (polyBridgeEdge1: Divisions, Twist ...). Drag an attribute's NAME left / right (left or
// middle button) to scrub it - Shift faster, Ctrl / Cmd finer - or type a number; every change redoes the step in
// place (no new undo step). t brings it back for the last step (or a fresh primitive's own attributes); Esc or a
// click on the model closes it; Display > Heads Up Display > In-View Editors switches it off.
function forgeIveOn() { try { return localStorage.getItem("loki-forge-ive") !== "0"; } catch (_) { return true; } }
function forgeIveSet(on) { try { localStorage.setItem("loki-forge-ive", on ? "1" : "0"); } catch (_) { /* private mode */ } if (!on) forgeIveHide(); return on; }
function forgeIveHide() { const b = document.getElementById("forge-ive"); if (b) b.hidden = true; }
function forgeIveRows() {                         // what the editor edits now: the last tool step, else a fresh primitive
  const L = forgeTk.last, h = typeof forgeModel !== "undefined" && forgeModel.hist;
  if (L && h && h.ops[L.histIndex] === L.rec) {
    const tool = FORGE_TK_TOOLS[L.id], n = window.forgeHistory ? window.forgeHistory.list().filter((o, i) => i <= L.histIndex && o.node === FORGE_TK_NODES[L.rec.op]).length : 1;
    return { title: (FORGE_TK_NODES[L.rec.op] || "poly") + n, what: tool[0],
      rows: tool[3].map(([k, label, min, max, step]) => ({ k, label, min, max, step, bool: max - min === 1 && step === 1,
        get: () => +L.rec.params[k] || 0, set: (x) => forgeTkTweak(k, x) })) };
  }
  const v = forge.view, pr = typeof forgeModel !== "undefined" && forgeModel.prim;
  if (pr && v && v.poly === pr.poly) {
    const p = window.ForgePoly.PRIMITIVES[pr.kind];
    return { title: "poly" + p.name.replace(/\s+/g, "") + "1", what: p.name,
      rows: Object.entries(p.params).map(([k, [def, lo, hi]]) => ({ k, label: k[0].toUpperCase() + k.slice(1), min: lo, max: hi,
        step: k === "thickness" ? 0.01 : 1, get: () => (pr.opts[k] != null ? pr.opts[k] : def),
        set: (x) => { pr.opts[k] = x; const poly = window.ForgePoly.primitive(pr.kind, pr.opts); pr.poly = poly; v.showPoly(poly, true, true); if (typeof forgeModelSync === "function") forgeModelSync(); } })) };
  }
  return null;
}
function forgeIveShow(force) {
  if (!force && !forgeIveOn()) return false;
  const v = forge.view, info = forgeIveRows();
  if (!v || !info) { if (force) forgeTkSay("Nothing to adjust: run a modelling tool (or create a primitive), then press t.", true); return false; }
  let box = document.getElementById("forge-ive");
  if (!box) {
    box = document.createElement("div"); box.id = "forge-ive"; box.className = "forge-ive"; box.hidden = true;
    box.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Escape") forgeIveHide(); });
    box.addEventListener("pointerdown", (e) => e.stopPropagation());
    (v.canvas.parentElement || document.body).append(box);
  }
  box.textContent = "";
  const head = document.createElement("div"); head.className = "forge-ive-head";
  const t = document.createElement("span"); t.className = "forge-ive-title"; t.textContent = info.title;
  const w = document.createElement("span"); w.className = "forge-ive-what"; w.textContent = info.what;
  const x = document.createElement("button"); x.type = "button"; x.className = "forge-ive-x"; x.textContent = "×"; x.title = "Close (Esc; t brings it back)";
  x.addEventListener("click", forgeIveHide);
  head.append(t, w, x);
  box.append(head);
  // drag the editor by its title
  head.addEventListener("pointerdown", (e) => {
    if (e.target === x) return;
    const r = box.getBoundingClientRect(), pr = box.offsetParent ? box.offsetParent.getBoundingClientRect() : { left: 0, top: 0 };
    const dx = e.clientX - r.left, dy = e.clientY - r.top;
    head.setPointerCapture(e.pointerId);
    const mv = (ev) => { box.style.left = (ev.clientX - dx - pr.left) + "px"; box.style.top = (ev.clientY - dy - pr.top) + "px"; box.dataset.moved = "1"; };
    const up = () => { head.removeEventListener("pointermove", mv); head.removeEventListener("pointerup", up); };
    head.addEventListener("pointermove", mv); head.addEventListener("pointerup", up);
  });
  if (!info.rows.length) { const p = document.createElement("div"); p.className = "forge-ive-none"; p.textContent = "No attributes to adjust."; box.append(p); }
  for (const r of info.rows) {
    const row = document.createElement("div"); row.className = "forge-ive-row"; row.dataset.k = r.k;
    const lab = document.createElement("span"); lab.className = "forge-ive-label"; lab.textContent = r.label;
    row.append(lab);
    if (r.bool) {
      const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !!r.get();
      cb.addEventListener("change", () => r.set(cb.checked ? 1 : 0));
      row.append(cb);
    } else {
      const n = document.createElement("input"); n.type = "number"; n.className = "forge-ive-num";
      n.min = String(r.min); n.max = String(r.max); n.step = String(r.step);
      const show = () => { n.value = String(Math.round(r.get() * 1000) / 1000); };
      show();
      n.addEventListener("change", () => { r.set(Math.max(r.min, Math.min(r.max, +n.value))); show(); });
      // scrub: press on the name, drag sideways (the pro virtual slider)
      lab.title = "Drag left / right to change (Shift faster, Ctrl/Cmd finer), or type a number.";
      lab.addEventListener("pointerdown", (e) => {
        if (e.button !== 0 && e.button !== 1) return;
        e.preventDefault();
        const x0 = e.clientX, v0 = r.get(), span = r.max - r.min;
        lab.setPointerCapture(e.pointerId); row.classList.add("scrub");
        const mv = (ev) => {
          const k = (ev.shiftKey ? 4 : ev.ctrlKey || ev.metaKey ? 0.15 : 1) * (r.step >= 1 ? 0.08 : span / 400);
          let val = v0 + (ev.clientX - x0) * k;
          val = Math.max(r.min, Math.min(r.max, r.step >= 1 ? Math.round(val) : Math.round(val / r.step) * r.step));
          if (val !== r.get()) { r.set(val); show(); }
        };
        const up = () => { row.classList.remove("scrub"); lab.removeEventListener("pointermove", mv); lab.removeEventListener("pointerup", up); forgeTkSettings(); };
        lab.addEventListener("pointermove", mv); lab.addEventListener("pointerup", up);
      });
      row.append(n);
    }
    box.append(row);
  }
  box.hidden = false;
  if (!box.dataset.moved) {                        // beside the selection, inside the view
    const stage = box.parentElement.getBoundingClientRect();
    let px = stage.width * 0.62, py = stage.height * 0.18;
    try {
      const ids = v.selectedVerts ? v.selectedVerts() : [];
      if (ids.length && v.poly) {
        const THREE = v.THREE, c = new THREE.Vector3();
        for (const i of ids) c.add(new THREE.Vector3().fromArray(v.poly.v[i] || [0, 0, 0]));
        c.multiplyScalar(1 / ids.length); v.holder.updateMatrixWorld(true); c.applyMatrix4(v.holder.matrixWorld).project(v.camera);
        const cr = v.canvas.getBoundingClientRect();
        px = cr.left - stage.left + (c.x + 1) / 2 * cr.width + 60; py = cr.top - stage.top + (1 - c.y) / 2 * cr.height - 40;
      }
    } catch (_) { /* keep the default place */ }
    const bw = box.offsetWidth || 220, bh = box.offsetHeight || 120;
    box.style.left = Math.max(8, Math.min(stage.width - bw - 8, px)) + "px";
    box.style.top = Math.max(50, Math.min(stage.height - bh - 8, py)) + "px";
  }
  return true;
}
// open after every tool step; close when the model is clicked (a new selection) or the mode changes
(function () {
  const run = forgeTkRun;
  forgeTkRun = function (id, override) { const ok = run(id, override); if (ok) forgeIveShow(false); return ok; };   // eslint-disable-line no-func-assign
  document.addEventListener("pointerdown", (e) => {
    const b = document.getElementById("forge-ive"), v = forge.view;
    if (!b || b.hidden || !v || e.target !== v.canvas) return;
    if ((v.gizmo && v.gizmo.axis) || (v.transform && v.transform.axis) || e.altKey || e.button !== 0) return;   // using a handle or the camera
    forgeIveHide();
  }, true);
  if (typeof FORGE_PRO_CMDS !== "undefined") {
    FORGE_PRO_CMDS.showManip = ["Show Manipulator Tool", () => { forgeIveShow(true); return ""; }];
    FORGE_PRO_CMDS.iveToggle = ["In-View Editors", () => (forgeIveSet(!forgeIveOn()) ? "In-View Editors on (t shows the last step's)." : "In-View Editors off (t still opens one).")];
  }
  if (typeof FORGE_PRO_TOGGLES !== "undefined") Object.assign(FORGE_PRO_TOGGLES, { iveToggle: () => forgeIveOn(),
    camSelAuto: (v) => !!(v.cameraBasedSelection && v.cameraBasedSelection() === "auto"), camSelOn: (v) => !!(v.cameraBasedSelection && v.cameraBasedSelection() === "on"),
    camSelOff: (v) => !!(v.cameraBasedSelection && v.cameraBasedSelection() === "off"), backfaces: (v) => v.backfaceCull !== false });
})();
window.forgeToolkit.ive = { show: forgeIveShow, hide: forgeIveHide, on: forgeIveOn, set: forgeIveSet };
