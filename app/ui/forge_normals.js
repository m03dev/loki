// Forge - soft / hard edges and normals, the pro tool's way (owner 2026-10-21 12:46: "we need soften/harden/ and show
// normals look into these maya functions and implement them").
//
// A mesh's edges are soft or hard (m.hard: edge key -> 1 for hard, carried through every modelling op by
// forge_polyops.js). A soft edge shares its two vertices' normals with the face across it, so the surface shades
// smooth over it; a hard edge splits them (one normal per face at each vertex - "vertex-face" normals), so it shows as
// a crease. A mesh with no m.hard yet is drawn all hard (faceted), as before.
//
//   Mesh Display > Soften Edge         the selected edges (all, with nothing selected) soft    (normal angle 180)
//   Mesh Display > Harden Edge         ... hard                                                  (normal angle 0)
//   Mesh Display > Soften/Harden Edges edges whose faces meet at more than the Angle (30) hard, the rest soft
//   Display > Polygons > Face Normals / Vertex Normals, Normals Size (bigger / smaller)
//   Display > Polygons > Soft/Hard Edges: hard edges solid, soft edges dotted
// A new primitive gets the pro default (Soften/Harden at 30): a cube stays crisp, a sphere / cylinder shades round.
"use strict";

// one normal per face corner: corners meeting over a soft edge are joined and share the sum of their faces' normals
function forgeCornerNormals(poly) {
  const P = window.ForgePoly, hard = poly.hard instanceof Map ? poly.hard : null;
  const base = [], parent = [], fn = poly.f.map((f) => P.faceNormal(poly, f));
  let n = 0;
  poly.f.forEach((f) => { base.push(n); n += f.length; });
  for (let i = 0; i < n; i++) parent.push(i);
  const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  const join = (a, b) => { a = find(a); b = find(b); if (a !== b) parent[b] = a; };
  // edge -> the corners at its ends, per face
  const at = new Map();
  poly.f.forEach((f, fi) => {
    for (let k = 0; k < f.length; k++) {
      const a = f[k], b = f[(k + 1) % f.length], key = Math.min(a, b) + "," + Math.max(a, b);
      let list = at.get(key); if (!list) at.set(key, (list = []));
      list.push([fi, base[fi] + k, base[fi] + (k + 1) % f.length, a]);
    }
  });
  for (const [key, list] of at) {
    if (list.length !== 2 || (hard && hard.has(key)) || !hard) continue;
    const [x, y] = list;
    // join the corners of the same vertex on the two faces
    const cx = { [x[3]]: x[1] }, other = x[3] === +key.split(",")[0] ? +key.split(",")[1] : +key.split(",")[0];
    cx[other] = x[2];
    const cy = { [y[3]]: y[1] }, other2 = y[3] === +key.split(",")[0] ? +key.split(",")[1] : +key.split(",")[0];
    cy[other2] = y[2];
    for (const vtx of key.split(",").map(Number)) if (cx[vtx] != null && cy[vtx] != null) join(cx[vtx], cy[vtx]);
  }
  // area-weighted sum per group
  const sum = new Map(), cornerFace = new Array(n);
  poly.f.forEach((f, fi) => {
    const area = Math.max(1e-12, forgeFaceArea(poly, f));
    for (let k = 0; k < f.length; k++) {
      const c = base[fi] + k, r = find(c); cornerFace[c] = fi;
      const s = sum.get(r) || [0, 0, 0], nn = fn[fi];
      s[0] += nn[0] * area; s[1] += nn[1] * area; s[2] += nn[2] * area; sum.set(r, s);
    }
  });
  return poly.f.map((f, fi) => f.map((_, k) => {
    const s = sum.get(find(base[fi] + k)), l = Math.hypot(s[0], s[1], s[2]) || 1;
    return [s[0] / l, s[1] / l, s[2] / l];
  }));
}
function forgeFaceArea(poly, f) {
  let x = 0, y = 0, z = 0;
  const o = poly.v[f[0]];
  for (let k = 1; k + 1 < f.length; k++) {
    const a = poly.v[f[k]], b = poly.v[f[k + 1]];
    const u = [a[0] - o[0], a[1] - o[1], a[2] - o[2]], w = [b[0] - o[0], b[1] - o[1], b[2] - o[2]];
    x += u[1] * w[2] - u[2] * w[1]; y += u[2] * w[0] - u[0] * w[2]; z += u[0] * w[1] - u[1] * w[0];
  }
  return Math.hypot(x, y, z) / 2;
}

(function forgeNormalsSetup() {
  const P = window.ForgePoly;
  if (P && P.setHard && !P.softenEdges) {
    P.softenEdges = (m, edges) => P.setHard(m, edges, false);
    P.hardenEdges = (m, edges) => P.setHard(m, edges, true);
  }
  // the pro default on a new primitive: Soften/Harden at 30 degrees
  if (P && P.primitive && P.softHard && !P.primitive.fnSoft) {
    const orig = P.primitive;
    P.primitive = function () {
      const m = orig.apply(this, arguments);
      try { if (m && m.f && m.f.length && !(m.hard instanceof Map)) { const r = P.softHard(m, null, { angle: 30 }); if (r && r.m && r.m.hard) m.hard = r.m.hard; } } catch (_) { /* keep it faceted */ }
      return m;
    };
    P.primitive.fnSoft = true;
  }
})();

const FORGE_NRM_STORE = "loki-forge-normals";
function forgeNrmPrefs() {
  try { return Object.assign({ face: false, vertex: false, size: 0.4, softHard: false, angle: 30 }, JSON.parse(localStorage.getItem(FORGE_NRM_STORE) || "{}") || {}); }
  catch (_) { return { face: false, vertex: false, size: 0.4, softHard: false, angle: 30 }; }
}
function forgeNrmSave(p) { try { localStorage.setItem(FORGE_NRM_STORE, JSON.stringify(p)); } catch (_) { /* private window */ } }

// the selected edges as [a, b] pairs; nothing selected (or object mode) = every edge, as the pro tool does
function forgeNrmEdges(v) {
  if (!v || v.mode !== "poly" || !v.edit) return [];
  const sel = v.edit.sel || {};
  if (sel.e && sel.e.size && v.edgePairs) return v.edgePairs();
  // faces or vertices selected: the edges they touch
  const P = window.ForgePoly, m = v.poly, out = [];
  if (sel.f && sel.f.size) for (const fi of sel.f) { const f = m.f[fi]; for (let k = 0; k < f.length; k++) out.push([f[k], f[(k + 1) % f.length]]); }
  else if (sel.v && sel.v.size) for (const e of P.edges(m)) if (sel.v.has(e.a) && sel.v.has(e.b)) out.push([e.a, e.b]);
  return out;
}
function forgeNrmApply(op, opts, label) {
  const v = typeof forge !== "undefined" ? forge.view : null;
  if (!v || !v.poly) return "Soften / Harden works on a modelled mesh (Create a primitive first).";
  const items = forgeNrmEdges(v);
  if (typeof forgeTkApplyOp === "function") forgeTkApplyOp(op, items, opts || {}, label);
  forgeNrmDraw(true);
  return label + (items.length ? " on " + items.length + " edge" + (items.length === 1 ? "" : "s") : " on every edge") + ".";
}

// ---------------------------------------------------------------- the display: normals and soft / hard edges
const NS = { lines: null, edges: null, key: "" };
function forgeNrmDrop(k) { const o = NS[k]; if (!o) return; if (o.parent) o.parent.remove(o); o.geometry.dispose(); o.material.dispose(); NS[k] = null; }
function forgeNrmDraw(force) {
  const v = typeof forge !== "undefined" ? forge.view : null;
  if (!v || !v.THREE || !v.holder) return;
  const p = forgeNrmPrefs(), poly = v.polyWork || v.poly;
  const key = [p.face, p.vertex, p.size, p.softHard, v.polyEpoch || 0, poly ? poly.f.length : 0, poly && poly.hard instanceof Map ? poly.hard.size : -1, v.mode].join("|");
  if (!force && key === NS.key) return;
  NS.key = key;
  forgeNrmDrop("lines"); forgeNrmDrop("edges");
  if (!poly || v.mode === "sculpt") { v.dirty = true; return; }
  const THREE = v.THREE, segs = [], cols = [];
  const len = Math.max(0.001, p.size) * 0.12 * Math.max(0.2, Math.min(4, v.size || 1));
  const push = (o, d, c) => { segs.push(o[0], o[1], o[2], o[0] + d[0] * len, o[1] + d[1] * len, o[2] + d[2] * len); cols.push(...c, ...c); };
  if (p.face) poly.f.forEach((f) => {
    const n = window.ForgePoly.faceNormal(poly, f), c = [0, 0, 0];
    for (const i of f) { c[0] += poly.v[i][0] / f.length; c[1] += poly.v[i][1] / f.length; c[2] += poly.v[i][2] / f.length; }
    push(c, n, [0.35, 0.85, 1]);
  });
  if (p.vertex) {
    const cn = poly.hard instanceof Map ? forgeCornerNormals(poly) : poly.f.map((f) => f.map(() => window.ForgePoly.faceNormal(poly, f)));
    const seen = new Set();
    poly.f.forEach((f, fi) => f.forEach((vi, k) => {
      const n = cn[fi][k], key2 = vi + ":" + n.map((x) => x.toFixed(3)).join(",");
      if (seen.has(key2)) return;                     // a soft vertex: one line; a vertex on hard edges: one per face
      seen.add(key2); push(poly.v[vi], n, [1, 0.85, 0.25]);
    }));
  }
  if (segs.length) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(segs), 3));
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(cols), 3));
    NS.lines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, depthTest: true }));
    NS.lines.name = "forge-normals"; NS.lines.renderOrder = 6; NS.lines.raycast = () => {};
    v.holder.add(NS.lines);
  }
  if (p.softHard) {                                   // hard edges solid, soft edges dotted
    const hardPts = [], softPts = [], hard = poly.hard instanceof Map ? poly.hard : null;
    for (const e of window.ForgePoly.edges(poly)) {
      const key2 = Math.min(e.a, e.b) + "," + Math.max(e.a, e.b), isHard = !hard || hard.has(key2);
      (isHard ? hardPts : softPts).push(...poly.v[e.a], ...poly.v[e.b]);
    }
    const grp = new THREE.Group(); grp.name = "forge-softhard";
    const add = (pts, dashed) => {
      if (!pts.length) return;
      const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(pts), 3));
      const mat = dashed ? new THREE.LineDashedMaterial({ color: 0xd8e2ec, dashSize: len * 0.25, gapSize: len * 0.2, transparent: true, opacity: 0.85 })
        : new THREE.LineBasicMaterial({ color: 0x101114 });
      const l = new THREE.LineSegments(g, mat); if (dashed) l.computeLineDistances(); l.raycast = () => {}; l.renderOrder = 5; grp.add(l);
    };
    add(hardPts, false); add(softPts, true);
    grp.geometry = { dispose() { for (const c of grp.children) c.geometry.dispose(); } };
    grp.material = { dispose() { for (const c of grp.children) c.material.dispose(); } };
    grp.raycast = () => {};
    NS.edges = grp; v.holder.add(grp);
  }
  v.dirty = true;
}
setInterval(() => { try { forgeNrmDraw(false); } catch (_) { /* the next tick tries again */ } }, 250);

function forgeNrmToggle(k) {
  const p = forgeNrmPrefs(); p[k] = !p[k]; forgeNrmSave(p); forgeNrmDraw(true);
  return { face: "Face normals", vertex: "Vertex normals", softHard: "Soft / hard edge display" }[k] + (p[k] ? " on." : " off.");
}
function forgeNrmSize(f) {
  const p = forgeNrmPrefs(); p.size = Math.max(0.02, Math.min(20, +(p.size * f).toFixed(3))); forgeNrmSave(p); forgeNrmDraw(true);
  return "Normals size " + p.size + ".";
}

if (typeof FORGE_PRO_CMDS !== "undefined") {
  const C = FORGE_PRO_CMDS;
  C.softEdge = ["Soften Edge", () => forgeNrmApply("softenEdges", {}, "Soften Edge")];
  C.hardEdge = ["Harden Edge", () => forgeNrmApply("hardenEdges", {}, "Harden Edge")];
  // Mesh Display > Set to Face / Average (Maya's vertex-normal rows): the picked faces' (or the object's) edges
  // hard - faceted - or soft - smooth
  C.setToFace = ["Set to Face", () => forgeNrmApply("hardenEdges", {}, "Set to Face")];
  C.averageNormals = ["Average", () => forgeNrmApply("softenEdges", {}, "Average")];
  C.softHard = ["Soften/Harden Edges (30°)", () => forgeNrmApply("softHard", { angle: forgeNrmPrefs().angle }, "Soften/Harden Edges")];
  C.softHardAngle = ["Soften/Harden Angle...", () => {
    const p = forgeNrmPrefs(), opts = [10, 20, 30, 45, 60, 90, 120, 180];
    p.angle = opts[(opts.indexOf(p.angle) + 1) % opts.length] || 30; forgeNrmSave(p);
    if (C.softHard) C.softHard[0] = "Soften/Harden Edges (" + p.angle + "°)";
    return "Soften/Harden angle: " + p.angle + "° (edges meeting more sharply than that turn hard).";
  }];
  C.faceNormals = ["Face Normals", () => forgeNrmToggle("face")];
  C.vertexNormals = ["Vertex Normals", () => forgeNrmToggle("vertex")];
  C.normalsBigger = ["Normals Size: Bigger", () => forgeNrmSize(1.5)];
  C.normalsSmaller = ["Normals Size: Smaller", () => forgeNrmSize(1 / 1.5)];
  C.softHardDisplay = ["Soft/Hard Edges (display)", () => forgeNrmToggle("softHard")];
  C.conformNormals = C.conformNormals || ["Conform Normals", () => { if (typeof forgeTkRun === "function" && window.ForgePoly.conform) return forgeTkRun("conform"); return ""; }];
  C.softHard[0] = "Soften/Harden Edges (" + forgeNrmPrefs().angle + "°)";
}
if (typeof FORGE_PRO_TOGGLES !== "undefined") {
  FORGE_PRO_TOGGLES.faceNormals = () => forgeNrmPrefs().face;
  FORGE_PRO_TOGGLES.vertexNormals = () => forgeNrmPrefs().vertex;
  FORGE_PRO_TOGGLES.softHardDisplay = () => forgeNrmPrefs().softHard;
}
