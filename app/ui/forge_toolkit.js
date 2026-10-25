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
  extrudeFaces: ["Extrude", "extrudeFaces", "f", [["thickness", "Thickness", -2, 2, 0.01, 0], ["offset", "Offset", -1, 1, 0.01, 0], ["divisions", "Divisions", 1, 32, 1, 1], ["taper", "Taper", 0, 5, 0.01, 1], ["twist", "Twist", -360, 360, 1, 0], ["keepTogether", "Keep Faces Together", 0, 1, 1, 1]], "Extrude the faces; drag the manipulator to place them."],
  extrudeEdges: ["Extrude Edge", "extrudeEdges", "e", [["thickness", "Thickness", -2, 2, 0.01, 0], ["offset", "Offset", -1, 1, 0.01, 0], ["divisions", "Divisions", 1, 32, 1, 1], ["taper", "Taper", 0, 5, 0.01, 1], ["twist", "Twist", -360, 360, 1, 0]], "Extrude the edges into a strip of faces."],
  extrudeVerts: ["Extrude Vertex", "extrudeVerts", "v", [["length", "Length", -2, 2, 0.01, 0.1], ["width", "Width", 0, 1, 0.01, 0.1]], "Pull each vertex out into a small point."],
  bevel: ["Bevel", "bevel", "fe", [["fraction", "Fraction", 0.01, 1, 0.01, 0.5], ["segments", "Segments", 1, 12, 1, 1], ["depth", "Depth", -1, 1, 0.01, 1], ["chamfer", "Chamfer", 0, 1, 1, 1], ["offsetAsFraction", "Offset as fraction", 0, 1, 1, 1], ["offset", "Offset", 0, 2, 0.01, 0.2]], "Round the selected edges (faces: their border edges)."],
  bridge: ["Bridge", "bridge", "e", [["divisions", "Divisions", 0, 64, 1, 0], ["bridgeType", "Bridge type", 0, 0, 0, "linear", ["linear", "smooth", "curve"]], ["twist", "Twist", -360, 360, 1, 0], ["taper", "Taper", 0, 5, 0.01, 1]], "Join two open border edge chains with faces."],
  poke: ["Poke Face", "poke", "f", [["offset", "Offset", -1, 1, 0.01, 0]], "Add a vertex in the middle of each face."],
  wedge: ["Wedge", "wedge", "fw", [["angle", "Angle", -360, 360, 1, 90], ["divisions", "Divisions", 1, 32, 1, 4]], "Turn the faces round an edge of theirs (pick faces and one edge)."],
  chamferVerts: ["Chamfer Vertex", "chamferVerts", "v", [["width", "Width", 0.01, 1, 0.01, 0.25], ["removeFace", "Remove face", 0, 1, 1, 0]], "Cut each corner off."],
  collapse: ["Collapse", "collapse", "fe", [], "Shrink each edge or face to its centre point."],
  connect: ["Connect", "connect", "ve", [["edgeCount", "Segments", 1, 64, 1, 1], ["slide", "Slide", 0, 1, 0.01, 0.5]], "Join the selected edges' middles (or the selected vertices) across their faces."],
  detach: ["Detach", "detach", "ve", [], "Split the vertices so each face has its own."],
  dissolveEdges: ["Delete Edge", "dissolveEdges", "e", [["cleanVerts", "Clean up vertices", 0, 1, 1, 0]], "Remove the edges; their faces merge."],
  dissolveVerts: ["Delete Vertex", "dissolveVerts", "v", [], "Remove the vertices; their faces merge."],
  triangulate: ["Triangulate", "triangulateFaces", "f*", [], "Split the faces into triangles."],
  quadrangulate: ["Quadrangulate", "quadrangulate", "f*", [["angle", "Angle threshold", 0, 180, 1, 30], ["keepHardEdges", "Keep hard edges", 0, 1, 1, 0]], "Merge triangle pairs into quads."],
  duplicateFaces: ["Duplicate Face", "duplicateFaces", "f", [], "Copy the faces (a new piece of this mesh)."],
  extractFaces: ["Extract", "extractFaces", "f", [], "Cut the faces off into their own piece."],
  flatten: ["Flatten", "flatten", "v", [["axis", "Axis", 0, 0, 0, "y", ["x", "y", "z", "normal"]], ["amount", "Amount", 0, 1, 0.01, 1]], "Scale the selection to 0 on one axis - it lies flat on the plane through the handle (Maya / Unreal: scale to 0)."],
  averageVerts: ["Average Vertices", "averageVerts", "v*", [["iterations", "Iterations", 1, 20, 1, 1]], "Smooth the selected vertices' positions."],
  relax: ["Relax", "relax", "v*", [["iterations", "Iterations", 1, 20, 1, 3]], "Relax the vertices (borders stay)."],
  circularize: ["Circularize", "circularize", "fv", [], "Lay the selected loop out on a circle."],
  spinEdge: ["Spin Edge", "spinEdge", "e", [["dir", "Direction", -1, 1, 2, 1]], "Turn each edge to the next corners of its two faces."],
  slideEdge: ["Slide Edge", "slideEdge", "e", [["t", "Slide", -1, 1, 0.01, 0.3]], "Slide the edges along the edges beside them."],
  fillHole: ["Fill Hole", null, "e", [], "Close the holes the selection touches."],
  offsetEdgeLoop: ["Offset Edge Loop", "offsetEdgeLoop", "e1", [["distance", "Distance", 0.01, 0.49, 0.01, 0.25], ["count", "Loops", 1, 32, 1, 1], ["equalDistance", "Equal distance", 0, 1, 1, 0]], "Two loops either side of the loop through the edge."],
  insertEdgeLoop: ["Insert Edge Loop", "insertEdgeLoop", "e1", [["t", "Position", 0.01, 0.99, 0.01, 0.5], ["count", "Number of loops", 1, 64, 1, 1], ["equalDistance", "Equal distance", 0, 1, 1, 0]], "A loop across the ring of quads the edge crosses."],
  addDivisions: ["Add Divisions", "addDivisions", "f*", [["divisions", "Divisions", 1, 4, 1, 1]], "Split each picked face into quads round its middle (neighbours keep the new edge points, so nothing opens)."],
  flipTriangleEdge: ["Flip Triangle Edge", "flipTriangleEdge", "e", [], "Turn the edge between two triangles to join their other two corners."],
  symmetrize: ["Symmetrize", "symmetrize", "f*", [["axis", "Axis", 0, 0, 0, "x", ["x", "y", "z"]], ["direction", "Keep side", 0, 0, 0, "+", ["+", "-"]]], "Copy one side of the mesh onto the other (cut on the plane, mirrored, welded)."],
  flipMesh: ["Flip", "flipMesh", "f*", [["axis", "Axis", 0, 0, 0, "x", ["x", "y", "z"]]], "Mirror the mesh in place across the plane through its origin."],
  mergeVerts: ["Merge", "merge", "v", [["threshold", "Threshold", 0, 2, 0.001, 0.001], ["alwaysMergeTwo", "Always merge two", 0, 1, 1, 0]], "Merge the selected vertices closer than the threshold."],
};
// the construction-history node each tool leaves (INPUTS)
const FORGE_TK_NODES = { extrudeFaces: "polyExtrudeFace", extrudeEdges: "polyExtrudeEdge", extrudeVerts: "polyExtrudeVertex", bevel: "polyBevel",
  bridge: "polyBridgeEdge", poke: "polyPoke", wedge: "polyWedgeFace", chamferVerts: "polyChamferVtx", collapse: "polyCollapseEdge",
  connect: "polyConnectComponents", detach: "polySplitVert", dissolveEdges: "polyDelEdge", dissolveVerts: "polyDelVertex",
  triangulateFaces: "polyTriangulate", triangulate: "polyTriangulate", quadrangulate: "polyQuad", duplicateFaces: "polyChipOff", extractFaces: "polyChipOff",
  averageVerts: "polyAverageVertex", flatten: "polyMoveVertex", relax: "polyAverageVertex", circularize: "polyCircularize", spinEdge: "polyFlipEdge",
  softenEdges: "polySoftEdge", hardenEdges: "polySoftEdge", softHard: "polySoftEdge",
  slideEdge: "polyTweak", addDivisions: "polySubdFacet", flipTriangleEdge: "polyFlipEdge", symmetrize: "polySymmetrize", flipMesh: "polyFlip", insertEdgeLoop: "polySplitRing", merge: "polyMergeVert", cleanup: "polyCleanup", multiCut: "polySplit", targetWeld: "polyMergeVert", offsetEdgeLoop: "polySplitRing", sliceFaces: "polySplit" };
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
    case "e1": return sel.e.length ? sel.e[0] : null;      // the loop tools work from one edge
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
const FORGE_TK_NEED = { f: "Select faces first (F11).", e: "Select edges first (F10).", e1: "Select an edge first (F10), or use the tool and click one.", v: "Select vertices first (F9).",
  fe: "Select edges or faces first.", ve: "Select vertices or edges first.", fv: "Select a loop of vertices or faces first." };

/** Call a polyops function, whatever argument shape it takes: (m, items, opts) */
function forgeTkCall(op, m, items, opts) {
  const P = window.ForgePoly, fn = P && P[op];
  if (typeof fn !== "function") return { m: m, sel: null, warn: "This tool is not in this build of Forge yet." };
  let out;
  opts = opts || {};
  // the ops whose settings are plain arguments, not an options object (forge_polyops.js)
  const call = { slideEdge: () => fn(m, items, +opts.t || 0), spinEdge: () => fn(m, items, +opts.dir || 1),
    targetWeld: () => fn(m, items.from, items.to), wedge: () => fn(m, items.faces, items.hinge, opts),
    symmetrize: () => fn(m, opts), flipMesh: () => fn(m, opts) }[op];
  try { out = call ? call() : fn(m, items, opts); } catch (exc) { return { m: m, sel: null, warn: (exc && exc.message) || String(exc) }; }
  if (!out) return { m: m, sel: null, warn: "Nothing changed." };
  if (out.v && out.f && !out.m) return { m: out, sel: null, warn: "" };     // a bare mesh
  return { m: out.m || m, sel: out.sel || null, warn: out.warn || "" };
}

// tools that work on the whole mesh when the object is picked with no components (Maya's behaviour per object)
const FORGE_TK_WHOLE = { bevel: { e: 1 }, poke: "f", extrudeFaces: "f", flatten: "v", addDivisions: "f", symmetrize: "f", flipMesh: "f", softenEdges: { e: 1 }, hardenEdges: { e: 1 }, softHard: { e: 1 } };
/** Every face / edge / vertex of the mesh, in the form a tool takes ("f", "v", or { e } for the fe / edge tools). */
function forgeTkWhole(v, kind) {
  const m = v.poly;
  if (!m || !m.f.length) return null;
  if (kind === "f") return m.f.map((_, i) => i);
  if (kind === "v") return m.v.map((_, i) => i);
  const T = window.ForgePoly.topology(m), e = T.edges.map((x) => [x.a, x.b]);
  return e.length ? { e: e } : null;
}

/** Run a tool on the selection: one undo step, one history step, the pro selection afterwards. */
/** Scale handle -> flat, never past it (owner 2026-10-25: "it should be flat but it just goes past it making
 *  non-manifold geometry"). Scaling through 0 MIRRORS the selection: faces turn inside out and, with soft selection or
 *  a partial pick, fold through their neighbours - inverted, overlapping, non-manifold. Maya and Blender allow it (a
 *  negative scale); Forge stops at flat instead: while the Scale handle drags, an axis within `eps` of 0 OR below it
 *  is held at `floor` (a hair above 0 - three.js decomposes the handle's matrix every frame and must not divide by 0).
 *  Flip on purpose with Mesh > Mirror or Normals > Reverse. `s` is a THREE.Vector3-like {x, y, z}; `axis` is
 *  TransformControls' "X", "YZ", "XYZ" ... Pure. */
function forgeScaleZeroSnap(s, axis, eps, floor) {
  if (!s || !axis) return false;
  let hit = false;
  const z = floor || 0;
  for (const a of "xyz") {
    if (axis.indexOf(a.toUpperCase()) < 0 || !(s[a] < (eps || 0.06))) continue;   // near 0, or past it (negative)
    if (s[a] !== z) { s[a] = z; hit = true; }
  }
  return hit;
}

function forgeTkRun(id, override) {
  const v = forgeTkView();
  if (!v) { forgeTkSay("Edit a polygon mesh first: Create a primitive, or DynaMesh a sculpt.", true); return false; }
  const tool = FORGE_TK_TOOLS[id];
  if (!tool) return false;
  if (id === "fillHole") { if (typeof forgeMeshOp === "function") forgeMeshOp("fillHole"); return true; }
  const [label, op, takes, params] = tool;
  const sel = forgeTkSel(v);
  let items = forgeTkItems(v, takes, sel), whole = false;
  // Maya / Unreal per object: with the object picked and no components, these tools work on the whole mesh
  // (Bevel = every edge, Poke = every face, Flatten = every vertex ...), as Maya's do on a selected object
  if (items == null && !sel.v.length && !sel.e.length && !sel.f.length && FORGE_TK_WHOLE[id]) { items = forgeTkWhole(v, FORGE_TK_WHOLE[id]); whole = !!items; }
  if (items == null) { forgeTkSay(label + ": " + (FORGE_TK_NEED[takes.replace("*", "")] || "select components first."), true); return false; }
  const opts = {};
  for (const [k, , , , , def, choices] of params) opts[k] = choices ? forgeTkPrefStr(id, k, def) : forgeTkPref(id, k, def);
  for (const [k, , min, max, step] of params) if (max - min === 1 && step === 1) opts[k] = !!opts[k];
  if (override) Object.assign(opts, override);

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
  forgeTkSay(label + (whole ? " (whole object)" : "") + (res.m.f.length !== base.f.length ? ": " + res.m.f.length.toLocaleString() + " faces." : "."));
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
  if (typeof L.rec.params[key] === "string") { L.rec.params[key] = String(value); forgeTkPrefStr(L.id, key, String(value), true); }
  else { L.rec.params[key] = typeof L.rec.params[key] === "boolean" ? !!+value : +value; forgeTkPref(L.id, key, +value, true); }
  const ok = typeof forgeHistRebuildShow === "function" ? forgeHistRebuildShow() : false;
  // keep the In-View Editor's fields in step (a change from Tool Settings, INPUTS or a script)
  const ive = document.getElementById("forge-ive");
  if (ive && !ive.hidden) for (const row of ive.querySelectorAll(".forge-ive-row")) {
    const k = row.dataset.k, val = L.rec.params[k], inp = row.querySelector("input, select");
    if (!inp || row.classList.contains("scrub") || document.activeElement === inp) continue;
    if (inp.type === "checkbox") inp.checked = !!val; else inp.value = typeof val === "string" ? val : String(Math.round(+val * 1000) / 1000);
  }
  return ok;
}

function forgeTkPrefStr(id, key, def, set) {
  const k = "loki-forge-tk-" + id + "-" + key;
  try { if (set) { localStorage.setItem(k, String(def)); return def; } const s = localStorage.getItem(k); return s == null ? def : s; } catch (_) { return def; }
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
  const pick = id || "extrudeFaces";                  // nothing picked: every face of the object (Maya's Extrude per object)
  const ok = forgeTkRun(pick, pick === "extrudeVerts" ? null : { thickness: 0, offset: 0 });
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
  if ((kind === "offsetEdgeLoop" || kind === "insertEdgeLoop") && v.setSelMode) v.setSelMode("edge");
  forgeTk.tool = { kind: kind, pts: [], marks: [] };
  const help = { multiCut: "Multi-Cut: click edges / vertices to cut (Shift: snap " + forgeTkPref("multiCut", "snapStep", 25) + "% steps, middle-click: 50%); Ctrl: edge loop (Ctrl+Shift snapped, Ctrl+middle-click centred); Backspace undoes a point, Enter / right-click finishes, Esc cancels.",
    targetWeld: "Target Weld: click the vertex to move, then the vertex to weld it to.",
    offsetEdgeLoop: "Offset Edge Loop: click an edge - two loops are added either side of its loop.",
    insertEdgeLoop: "Insert Edge Loop Tool: click an edge - a loop goes across its ring (t: its settings)." }[kind];
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
  if (window.forgeMultiCut) window.forgeMultiCut.clear();
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
  if (!t || !v || v.mode !== "poly" || forgeCamMod(e)) return;
  if (t.kind === "multiCut" && window.forgeMultiCut) return window.forgeMultiCut.pointer(e, t);   // forge_multicut.js
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
  if (t.kind === "offsetEdgeLoop" || t.kind === "insertEdgeLoop") {
    if (!hit.e) { forgeTkSay("Offset Edge Loop: click an edge.", true); return; }
    forgeTkToolEnd(false);
    const kind = t.kind;
    const v2 = forgeTkView();
    if (v2 && v2.selectItems) { const ei = v2.edgeIdOf(hit.e[0], hit.e[1]); if (ei >= 0) v2.selectItems("edge", [ei], "set"); }
    forgeTkRun(kind);                                   // a normal step: undo, INPUTS, In-View Editor
  }
}
function forgeTkKey(e) {
  const t = forgeTk.tool;
  if (!t) return;
  if (t.kind === "multiCut" && window.forgeMultiCut && window.forgeMultiCut.key(e, t)) return;
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
  // Flatten = scale to 0 (Maya / Unreal). Components: they lie flat on the plane through the handle (forge_polyops.js
  // flatten, one undo + history step, its Axis / Amount in Tool Settings). Objects (the transform): Scale <axis> = 0 on
  // every selected object, about its own pivot - Maya's default (forge_scene.js keeps it a hair above 0 so it stays
  // pickable; the Channel Box reads 0).
  const flat = (axis) => (v) => {
    if (comp(v)) { forgeTkRun("flatten", { axis: axis, amount: 1, pivot: window.ForgeSettings && ForgeSettings.get("pivotPlacement") === "median" ? "median" : "bbox" }); return ""; }
    const t = v && v.tree && v.tree.api;
    const picked = t ? (typeof t.selected === "function" ? t.selected() : t.sel || []) : [];
    const ids = picked.slice();
    if (!t || !ids.length) return "Select objects (or vertices / edges / faces), then Flatten.";
    if (axis === "normal") return "Flatten Along Normal works on components - F9 / F10 / F11, pick them, then flatten.";
    const ai = "xyz".indexOf(axis);
    let n = 0;
    for (const id of ids) if (t.setTransform(id, "scale", ai, 0)) n++;
    if (v.tree.build) v.tree.build();
    return n ? "Scale " + axis.toUpperCase() + " = 0 on " + n + " object" + (n === 1 ? "" : "s") + " - flat." : "Nothing to flatten.";
  };
  Object.assign(C, {
    flattenX: ["Flatten X (Scale X to 0)", flat("x")],
    flattenY: ["Flatten Y (Scale Y to 0)", flat("y")],
    flattenZ: ["Flatten Z (Scale Z to 0)", flat("z")],
    flattenNormal: ["Flatten Along Normal", flat("normal")],
    // Maya: Extrude on a picked object extrudes all its faces; on components, what is picked
    extrude: ["Extrude", async (v) => { if (!comp(v)) await toComp(v, "face"); forgeTkExtrude(); return ""; }],
    bevel: ["Bevel", run("bevel")],
    bridge: ["Bridge", run("bridge")],
    poke: ["Poke Face", run("poke")],
    addDivisions: ["Add Divisions", run("addDivisions")],
    flipTriangleEdge: ["Flip Triangle Edge", run("flipTriangleEdge")],
    symmetrize: ["Symmetrize", run("symmetrize")],
    flipMesh: ["Flip", run("flipMesh")],
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
    preselect: ["Preselection Highlight", (v) => (v.preselectHighlight ? (v.preselectHighlight(!v.preselectHighlight()) ? "Preselection highlight on." : "Preselection highlight off.") : "")],
    multiCut: ["Multi-Cut", async (v) => { await toComp(v, "edge"); forgeTkTool("multiCut"); return ""; }],
    targetWeld: ["Target Weld", async (v) => { await toComp(v, "vert"); forgeTkTool("targetWeld"); return ""; }],
    offsetEdgeLoop: ["Offset Edge Loop", async (v) => { await toComp(v, "edge"); if (v.edit && v.edit.sel.e.size) forgeTkRun("offsetEdgeLoop"); else forgeTkTool("offsetEdgeLoop"); return ""; }],
    insertLoopTool: ["Insert Edge Loop Tool", async (v) => { await toComp(v, "edge"); if (v.edit && v.edit.sel.e.size) forgeTkRun("insertEdgeLoop"); else forgeTkTool("insertEdgeLoop"); return ""; }],
    mergeThreshold: ["Merge (threshold)", run("mergeVerts")],
    cleanup: ["Cleanup...", () => { forgeCleanupDialog(true); return ""; }],
    meshStats: ["Mesh Report", () => forgeCleanupReport()],
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
  ["Mesh", ["combine", "separate", "extractFace", "mirror", "smooth", "triangulate", "quadrangulate", "fillHole", "cleanup", "meshStats", "dynamesh"]],
  ["Components", ["extrude", "bevel", "bridge", "chamfer", "circularize", "collapse", "connect", "detach", "merge", "mergeCenter",
    "poke", "wedge", "averageVerts", "relax", "spinEdge", "duplicateFace", "deleteEdgeVert"]],
  ["Tools", ["edgeLoop", "insertLoopTool", "offsetEdgeLoop", "multiCut", "targetWeld", "slideEdge", "softSel"]],
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
  for (const id of ["forge-channel", "forge-history", "forge-layer-editor"]) { const e = document.getElementById(id); if (e) e.classList.toggle("forge-tk-away", on); }
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
  // Maya's Falloff mode: Volume (straight-line distance) / Surface (along the mesh - a lip moves without the other)
  const fmode = mk("label", "forge-tk-row");
  const fmSel = document.createElement("select"); fmSel.id = "forge-tk-fmode"; fmSel.className = "forge-tk-select";
  for (const [k, t] of [["volume", "Falloff mode: Volume"], ["surface", "Falloff mode: Surface"]]) {
    const o = document.createElement("option"); o.value = k; o.textContent = t; fmSel.append(o);
  }
  fmSel.title = "Volume: everything within the radius follows. Surface: only what is connected along the mesh within the radius.";
  fmSel.addEventListener("change", () => { const v = forge.view; if (v && v.setProportional) v.setProportional(null, null, null, fmSel.value); });
  fmode.append(fmSel);
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
  selSec.append(modes, cam, bf, soft, rad, fmode, loops);
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
  for (const [k, label, min, max, step, , choices] of tool[3]) {
    if (choices) {
      const row = document.createElement("label"); row.className = "forge-tk-slider";
      const sel = document.createElement("select"); sel.className = "forge-tk-select";
      for (const c of choices) { const o = document.createElement("option"); o.value = c; o.textContent = c[0].toUpperCase() + c.slice(1); o.selected = L.rec.params[k] === c; sel.append(o); }
      sel.addEventListener("change", () => forgeTkTweak(k, sel.value));
      const nm = document.createElement("span"); nm.textContent = label;
      row.append(nm, sel); body.append(row);
    } else if (max - min === 1 && step === 1) {
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
  end: forgeTkToolEnd, panel: forgeTkPanel, tools: FORGE_TK_TOOLS, state: forgeTk, select: forgeTkSelect, sel: () => forgeTk.tool,
  last: () => forgeTk.last };   // the op whose Tool Settings are live (forge_preview.js previews with them)

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
      rows: tool[3].map(([k, label, min, max, step, , choices]) => ({ k, label, min, max, step, bool: !choices && max - min === 1 && step === 1, choices,
        get: () => (choices ? L.rec.params[k] : +L.rec.params[k] || 0), set: (x) => forgeTkTweak(k, x) })) };
  }
  const v = forge.view, pr = typeof forgeModel !== "undefined" && forgeModel.prim;
  if (pr && v && v.poly === pr.poly) {
    const p = window.ForgePoly.PRIMITIVES[pr.kind];
    return { title: "poly" + p.name.replace(/\s+/g, "") + "1", what: p.name,
      rows: Object.entries(p.params).map(([k, [def, lo, hi]]) => ({ k, label: k[0].toUpperCase() + k.slice(1), min: lo, max: hi,
        step: (window.ForgePoly.PRIM_FLOAT || {})[k] || 1, get: () => (pr.opts[k] != null ? pr.opts[k] : def),
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
    if (r.choices) {
      const sel = document.createElement("select"); sel.className = "forge-ive-num";
      for (const c of r.choices) { const o = document.createElement("option"); o.value = c; o.textContent = c; o.selected = r.get() === c; sel.append(o); }
      sel.addEventListener("change", () => { r.set(sel.value); forgeTkSettings(); });
      row.append(sel);
    } else if (r.bool) {
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
  window.forgeToolkit.run = forgeTkRun;
  document.addEventListener("pointerdown", (e) => {
    const b = document.getElementById("forge-ive"), v = forge.view;
    if (!b || b.hidden || !v || e.target !== v.canvas) return;
    if ((v.gizmo && v.gizmo.axis) || (v.transform && v.transform.axis) || forgeCamMod(e) || e.button !== 0) return;   // using a handle or the camera
    forgeIveHide();
  }, true);
  if (typeof FORGE_PRO_CMDS !== "undefined") {
    FORGE_PRO_CMDS.showManip = ["Show Manipulator Tool", () => { forgeIveShow(true); return ""; }];
    FORGE_PRO_CMDS.iveToggle = ["In-View Editors", () => (forgeIveSet(!forgeIveOn()) ? "In-View Editors on (t shows the last step's)." : "In-View Editors off (t still opens one).")];
  }
  if (typeof FORGE_PRO_TOGGLES !== "undefined") Object.assign(FORGE_PRO_TOGGLES, { iveToggle: () => forgeIveOn(),
    camSelAuto: (v) => !!(v.cameraBasedSelection && v.cameraBasedSelection() === "auto"), camSelOn: (v) => !!(v.cameraBasedSelection && v.cameraBasedSelection() === "on"),
    camSelOff: (v) => !!(v.cameraBasedSelection && v.cameraBasedSelection() === "off"), backfaces: (v) => v.backfaceCull !== false, preselect: (v) => !!(v.preselectHighlight && v.preselectHighlight()) });
})();
window.forgeToolkit.ive = { show: forgeIveShow, hide: forgeIveHide, on: forgeIveOn, set: forgeIveSet };

// ---------------------------------------------------------------- Mesh > Cleanup (the pro Cleanup options)
// (owner 2026-10-21: "modeling rules fleshed out like nsides and whatever else the cleanup tool does"). A window with
// the pro option layout: Operation (select matching polygons to look first, or clean them up), Fix by tessellation
// (4-sided, more than 4 sides, concave, with holes, non-planar), Remove geometry (lamina, non-manifold - normals and
// geometry / geometry only, zero-length edges, zero-area faces) and the tolerances. Apply runs P.cleanup on the edited
// mesh: "select" selects what matches (and tells you how many of each), "cleanup" fixes it as ONE undo step with a
// polyCleanup step in INPUTS. Mesh Report (Mesh > Mesh Report) prints the counts without changing anything.
const FORGE_CLEAN_OPTS = [
  ["Fix by tessellation", [["quads", "4-sided faces", false], ["nsided", "Faces with more than 4 sides", true], ["concave", "Concave faces", true],
    ["holed", "Faces with holes", true], ["nonPlanar", "Non-planar faces", false]]],
  ["Remove geometry", [["lamina", "Lamina faces (faces sharing all edges)", true], ["nonManifold", "Non-manifold geometry", true],
    ["zeroEdges", "Edges with zero length", true], ["zeroFaces", "Faces with zero geometry area", true]]],
];
function forgeCleanupPrefs(patch) {
  let p = {};
  try { p = JSON.parse(localStorage.getItem("loki-forge-cleanup") || "{}") || {}; } catch (_) { p = {}; }
  if (patch) { Object.assign(p, patch); try { localStorage.setItem("loki-forge-cleanup", JSON.stringify(p)); } catch (_) { /* */ } }
  return p;
}
function forgeCleanupOpts() {
  const p = forgeCleanupPrefs(), o = { op: p.op || "select", lengthTol: +(p.lengthTol || 1e-5), areaTol: +(p.areaTol || 1e-5), planarTol: +(p.planarTol || 1) };
  for (const [, list] of FORGE_CLEAN_OPTS) for (const [k, , def] of list) o[k] = p[k] == null ? def : !!p[k];
  if (o.nonManifold && p.nmMode === "geometry") o.nonManifold = "geometry";
  return o;
}
function forgeCleanupText(rep) {
  const names = { quads: "4-sided", nsided: "n-sided (5+)", concave: "concave", holed: "with holes", nonPlanar: "non-planar", lamina: "lamina",
    nonManifoldEdges: "non-manifold edges", nonManifoldVerts: "non-manifold vertices", flipped: "flipped normals", zeroEdges: "zero-length edges", zeroFaces: "zero-area faces" };
  const parts = Object.entries(rep || {}).filter(([, n]) => n).map(([k, n]) => n + " " + (names[k] || k));
  return parts.length ? parts.join(", ") : "nothing";
}
/** Run Cleanup with the window's settings (or these), on the edited mesh. */
function forgeCleanupApply(over) {
  const v = forgeTkView(), P = window.ForgePoly;
  if (!v || !P || !P.cleanup) { forgeTkSay("Cleanup works on a polygon mesh: Create a primitive, or DynaMesh a sculpt.", true); return null; }
  const o = Object.assign(forgeCleanupOpts(), over || {});
  const base = v.poly;
  let res;
  try { res = P.cleanup(base, o); } catch (exc) { forgeTkSay("Cleanup: " + exc.message, true); return null; }
  const say = forgeCleanupText(res.report);
  if (o.op === "select") {
    if (v.setSelMode) forgeTkSelect(v, res.sel);
    forgeTkSay(say === "nothing" ? "Cleanup: nothing matches - the mesh is clean." : "Cleanup found (selected): " + say + ".");
  } else if (res.m === base || say === "nothing") {
    forgeTkSay("Cleanup: nothing to fix - the mesh is clean.");
  } else {
    if (v.undoOpen) v.undoOpen("Cleanup");
    try {
      v.showPoly(res.m, true);
      if (typeof forgeHistPush === "function") forgeHistPush({ kind: "op", op: "cleanup", tool: "cleanup", items: null, params: Object.assign({}, o), main: null }, base);
    } finally { if (v.undoClose) v.undoClose(); }
    forgeTkSay("Cleanup fixed: " + say + (res.warn ? " (" + res.warn + ")" : "") + ".");
  }
  const out = document.querySelector("#forge-cleanup .forge-hk-note");
  if (out) out.textContent = (o.op === "select" ? "Found: " : "Fixed: ") + say;
  return res;
}
function forgeCleanupReport() {
  const v = forgeTkView(), P = window.ForgePoly;
  if (!v || !P || !P.meshStats) return "Mesh Report works on a polygon mesh.";
  const s = P.meshStats(v.poly);
  return "Mesh: " + s.faces + " faces (" + s.tris + " tris, " + s.quads + " quads, " + s.ngons + " n-gons), " + s.verts + " vertices, "
    + s.border + " border edges, " + s.nonManifoldEdges + " non-manifold edges, " + s.lamina + " lamina, " + s.concave + " concave, "
    + s.nonPlanar + " non-planar, " + s.zeroEdges + " zero-length edges, " + s.zeroFaces + " zero-area faces, " + s.shells + " piece" + (s.shells === 1 ? "" : "s") + ".";
}
function forgeCleanupDialog(show) {
  let box = document.getElementById("forge-cleanup");
  if (!box) {
    box = document.createElement("div"); box.id = "forge-cleanup"; box.className = "forge-hk forge-clean"; box.hidden = true;
    box.setAttribute("role", "dialog"); box.setAttribute("aria-label", "Cleanup Options");
    const p = forgeCleanupPrefs();
    let html = '<div class="forge-hk-title"><span>Cleanup Options</span><button type="button" class="forge-hk-x" title="Close">×</button></div><div class="forge-clean-body">'
      + '<div class="forge-clean-sec">Cleanup effect</div><label class="forge-clean-row">Operation <select data-k="op"><option value="select">Select matching polygons</option><option value="cleanup">Cleanup matching polygons</option></select></label>';
    for (const [title, list] of FORGE_CLEAN_OPTS) {
      html += '<div class="forge-clean-sec">' + title + "</div>";
      for (const [k, label] of list) html += '<label class="forge-clean-row"><input type="checkbox" data-k="' + k + '"> ' + label + (k === "nonManifold" ? ' <select data-k="nmMode"><option value="normals">Normals and geometry</option><option value="geometry">Geometry only</option></select>' : "") + "</label>";
    }
    html += '<div class="forge-clean-sec">Tolerance</div>'
      + '<label class="forge-clean-row">Length tolerance <input type="number" step="0.00001" min="0" data-k="lengthTol"></label>'
      + '<label class="forge-clean-row">Area tolerance <input type="number" step="0.00001" min="0" data-k="areaTol"></label>'
      + '<label class="forge-clean-row">Non-planar tolerance (degrees) <input type="number" step="0.5" min="0" data-k="planarTol"></label>'
      + '</div><div class="forge-hk-bar"><span class="forge-hk-note"></span><button type="button" data-act="report">Mesh Report</button><button type="button" data-act="apply">Apply</button><button type="button" data-act="applyClose">Cleanup</button></div>';
    box.innerHTML = html;
    document.body.append(box);
    const o = forgeCleanupOpts();
    for (const el of box.querySelectorAll("[data-k]")) {
      const k = el.dataset.k;
      if (el.type === "checkbox") el.checked = !!o[k];
      else if (k === "nmMode") el.value = p.nmMode || "normals";
      else el.value = String(k === "op" ? o.op : o[k]);
      el.addEventListener("change", () => forgeCleanupPrefs({ [k]: el.type === "checkbox" ? el.checked : el.type === "number" ? +el.value : el.value }));
      el.addEventListener("keydown", (e) => e.stopPropagation());
    }
    box.querySelector(".forge-hk-x").addEventListener("click", () => { box.hidden = true; });
    box.querySelector('[data-act="apply"]').addEventListener("click", () => forgeCleanupApply());
    box.querySelector('[data-act="applyClose"]').addEventListener("click", () => { if (forgeCleanupApply()) box.hidden = true; });
    box.querySelector('[data-act="report"]').addEventListener("click", () => { const t = forgeCleanupReport(); box.querySelector(".forge-hk-note").textContent = t; forgeTkSay(t); });
    box.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Escape") box.hidden = true; });
    const title = box.querySelector(".forge-hk-title");
    title.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button")) return;
      const r = box.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      title.setPointerCapture(e.pointerId);
      const mv = (ev) => { box.style.left = Math.max(0, ev.clientX - dx) + "px"; box.style.top = Math.max(0, ev.clientY - dy) + "px"; box.style.right = "auto"; };
      const up = () => { title.removeEventListener("pointermove", mv); title.removeEventListener("pointerup", up); };
      title.addEventListener("pointermove", mv); title.addEventListener("pointerup", up);
    });
  }
  box.hidden = show === false;
  return box;
}
window.forgeToolkit.cleanup = { apply: forgeCleanupApply, report: forgeCleanupReport, dialog: forgeCleanupDialog, opts: forgeCleanupOpts };
