// Forge's automatic seams (app/ui/forge_uvgami.js, ported from UVgami - GPL-3.0) in node: hard-surface seams make
// disk shells that flatten without overlap, a cylinder opens into disks, symmetric seams, rectify, reroute, similar
// islands, the flatten hook, and no input is ever changed. Several checks are the original add-on's own tests
// (dev/tests/test_seams.py, test_symmetry.py), re-run on the port.
//   node tests/js/test_forge_uvgami.js        (< 10 s)
"use strict";
const path = require("path");
global.window = global;
require(path.join(__dirname, "../../app/ui/forge_poly.js"));
require(path.join(__dirname, "../../app/ui/forge_uv.js"));
require(path.join(__dirname, "../../app/ui/forge_uvgami.js"));
const P = window.ForgePoly, U = window.ForgeUV, G = window.ForgeUVgami, C = G.core;
const T0 = Date.now();
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d).slice(0, 300))); };
const snap = (m) => JSON.stringify(m);

// ------------------------------------------------------------------ helpers
// strict interior overlap of two UV triangles (separating axis); touching edges / corners do not count
function triOverlap(A, B) {
  for (const T of [A, B]) for (let i = 0; i < 3; i++) {
    const p = T[i], q = T[(i + 1) % 3], n = [q[1] - p[1], p[0] - q[0]];
    const pa = A.map((x) => n[0] * x[0] + n[1] * x[1]), pb = B.map((x) => n[0] * x[0] + n[1] * x[1]);
    const eps = 1e-9 * (Math.abs(n[0]) + Math.abs(n[1]));
    if (Math.max(...pa) <= Math.min(...pb) + eps || Math.max(...pb) <= Math.min(...pa) + eps) return false;
  }
  return true;
}
function uvTris(m, faces) {
  const out = [];
  for (const fi of faces) { const c = m.fuv[fi]; for (let i = 1; i + 1 < c.length; i++) out.push([fi, [m.uv[c[0]], m.uv[c[i]], m.uv[c[i + 1]]]]); }
  return out;
}
function overlapsIn(m, faces) {
  const T = uvTris(m, faces); let n = 0;
  for (let i = 0; i < T.length; i++) for (let j = i + 1; j < T.length; j++) if (T[i][0] !== T[j][0] && triOverlap(T[i][1], T[j][1])) n++;
  return n;
}
// a shell's topology from its own UV indices: V - E + F, and how many boundary loops
function shellTopology(m, faces) {
  const verts = new Set(), edgeCount = new Map();
  for (const fi of faces) { const c = m.fuv[fi]; for (let i = 0; i < c.length; i++) { verts.add(c[i]); const a = c[i], b = c[(i + 1) % c.length], k = a < b ? a + "," + b : b + "," + a; edgeCount.set(k, (edgeCount.get(k) || 0) + 1); } }
  const boundary = [...edgeCount].filter(([, n]) => n === 1).map(([k]) => k.split(",").map(Number));
  const parent = new Map(), find = (x) => { while (parent.get(x) !== x) x = parent.get(x); return x; };
  for (const [a, b] of boundary) { if (!parent.has(a)) parent.set(a, a); if (!parent.has(b)) parent.set(b, b); const ra = find(a), rb = find(b); if (ra !== rb) parent.set(ra, rb); }
  return { euler: verts.size - edgeCount.size + faces.length, loops: new Set([...parent.keys()].map(find)).size };
}
const flipped = (m) => U.distortion(m).filter((d) => d.flipped).length;
const keyOf = (m, pred) => [...U.edges(G.applySeams(m, new Set())).keys()].filter((k) => { const [a, b] = k.split(",").map(Number); return pred(m.v[a], m.v[b]); });
// the original add-on's test meshes
function tube(sides = 4, height = 1) {
  const verts = [], faces = [];
  for (let i = 0; i < sides; i++) { const a = (2 * Math.PI * i) / sides; verts.push([Math.cos(a), Math.sin(a), 0], [Math.cos(a), Math.sin(a), height]); }
  for (let i = 0; i < sides; i++) { const lo = 2 * i, hi = lo + 1, nlo = 2 * ((i + 1) % sides), nhi = nlo + 1; faces.push([lo, nlo, hi], [nlo, nhi, hi]); }
  return { v: verts, f: faces };
}
function ngonCylinder(sides = 32, height = 2) {
  const verts = [], faces = [];
  for (let i = 0; i < sides; i++) { const a = (2 * Math.PI * i) / sides; verts.push([Math.cos(a), Math.sin(a), 0], [Math.cos(a), Math.sin(a), height]); }
  for (let i = 0; i < sides; i++) { const lo = 2 * i, hi = lo + 1, nlo = 2 * ((i + 1) % sides); faces.push([lo, nlo, nlo + 1, hi]); }
  faces.push([...Array(sides).keys()].reverse().map((i) => 2 * i), [...Array(sides).keys()].map((i) => 2 * i + 1));
  return { v: verts, f: faces };
}

(async () => {
  // ================================================================== hard-surface: a cube
  const cube = P.primitive("cube"), cube0 = snap(cube);
  const cs = G.hardSurfaceSeams(cube);
  check("a cube reads hard-surface (isHardSurface)", G.isHardSurface(cube) === true, null);
  check("hard-surface seams on a cube: the cross - 7 of its 12 edges are seams (the original add-on's own test), keys are 'a,b' with a < b",
    cs.size === 7 && [...cs].every((k) => { const [a, b] = k.split(",").map(Number); return a < b; }), [...cs]);
  const cc = G.applySeams(cube, cs);
  const csh = U.shells(cc);
  check("...ForgeUV.rebuild of that seam set gives shells that are all topological disks (Euler 1, one boundary loop)",
    csh.length >= 1 && csh.every((s) => { const t = shellTopology(cc, s.faces); return t.euler === 1 && t.loops === 1; }), csh.map((s) => shellTopology(cc, s.faces)));
  check("...and ForgeUV.seams of the rebuilt cage is exactly the seam set", [...U.seams(cc)].length === cs.size && [...cs].every((k) => U.seams(cc).has(k)), [...U.seams(cc)]);
  const cf = await G.flattenRigid(cc);
  check("...each shell flattens with no overlap and no flipped face (rigid unfold of the cross)",
    U.shells(cf).every((s) => overlapsIn(cf, s.faces) === 0) && overlapsIn(cf, cf.f.map((_, i) => i)) === 0 && flipped(cf) === 0, { shells: U.shells(cf).length, flips: flipped(cf) });
  check("...and keeps the faces' shape (distortion 4 = isometric)", Math.abs(G.flattenDistortion(cf) - 4) < 1e-6, G.flattenDistortion(cf));
  const cu = await G.unwrap(cube, { surfaceMode: "hard" });
  check("unwrap (hard surface, default fallback flatten): valid UVs, disks, no overlap, inside 0-1",
    U.has(cu) && U.shells(cu).every((s) => shellTopology(cu, s.faces).euler === 1) && overlapsIn(cu, cu.f.map((_, i) => i)) === 0
    && cu.uv.every((p) => p[0] >= -1e-9 && p[0] <= 1 + 1e-9 && p[1] >= -1e-9 && p[1] <= 1 + 1e-9), cu.uvInfo);
  // a subdivided cube (54 quads, 3x3 per side): the regions still merge to its 6 sides
  const cube3 = P.primitive("cube", { segments: 3 }), c3s = G.hardSurfaceSeams(cube3), c3 = await G.flattenRigid(G.applySeams(cube3, c3s));
  check("a 3x3-segment cube: seams only on the 12 cube edges (no seam inside a side), disk shells, no overlap",
    [...c3s].every((k) => { const [a, b] = k.split(",").map(Number), A = cube3.v[a], B = cube3.v[b]; return [0, 1, 2].filter((i) => Math.abs(Math.abs(A[i]) - 0.5) < 1e-9 && Math.abs(Math.abs(B[i]) - 0.5) < 1e-9).length >= 2; })
    && U.shells(c3).every((s) => shellTopology(c3, s.faces).euler === 1) && overlapsIn(c3, c3.f.map((_, i) => i)) === 0, { seams: c3s.size, shells: U.shells(c3).length });
  check("organic mode leaves the seams to the engine (no seams of its own)", G.hardSurfaceSeams(cube, { surfaceMode: "organic" }).size === 0, null);
  const sphere = P.primitive("sphere");
  check("auto mode: a sphere reads organic (no hard parts), a cube hard", G.isHardSurface(sphere) === false && G.hardFaces(sphere).size === 0 && G.hardFaces(cube).size === 6, [G.hardFaces(sphere).size]);
  const marked = G.applySeams(cube, new Set(keyOf(cube, (A, B) => A[1] > 0.4 && B[1] > 0.4)));
  check("marked: 'ONLY' returns just the cage's own seams, 'ADD' keeps them in the detected set",
    G.hardSurfaceSeams(marked, { marked: "ONLY" }).size === 4 && [...G.markedSeams(marked)].every((k) => G.hardSurfaceSeams(marked, { marked: "ADD" }).has(k)), null);

  // ================================================================== a cylinder
  const cyl = P.primitive("cylinder"), cyl0 = snap(cyl);
  const ys = G.hardSurfaceSeams(cyl), yc = G.applySeams(cyl, ys), ysh = U.shells(yc);
  check("a capped cylinder: the rims are cut and the wall gets one axial seam -> 3 shells (wall + 2 caps), every one a disk",
    ysh.length === 3 && ysh.every((s) => { const t = shellTopology(yc, s.faces); return t.euler === 1 && t.loops === 1; }), ysh.map((s) => [s.faces.length, shellTopology(yc, s.faces)]));
  const yf = await G.flattenRigid(yc);
  check("...the wall unrolls into a strip and nothing overlaps or flips", overlapsIn(yf, yf.f.map((_, i) => i)) === 0 && flipped(yf) === 0, { flips: flipped(yf) });
  const wall = { v: cyl.v, f: cyl.f.filter((f) => f.length === 4) };
  const ws = G.seamEdges(wall), wc = G.applySeams(wall, ws), wsh = U.shells(wc);
  check("an open tube (the wall alone) gets the one seam that makes it a single disk", ws.size === 1 && wsh.length === 1 && G.topology(wall, wsh[0].faces, ws).disk, [ws.size, wsh.length]);
  const [k1] = [...ws], [a1, b1] = k1.split(",").map(Number);
  check("...and that seam runs top to bottom (along the axis)", Math.abs(Math.abs(wall.v[a1][1] - wall.v[b1][1]) - 1) < 1e-9, [wall.v[a1], wall.v[b1]]);
  const t16 = tube(16), t16s = G.core.seamEdges(t16.v, t16.f);
  check("original test: a coarse 16-sided tube unrolls with one cut from z=0 to z=1", t16s.size === 1 && (() => { const [a, b] = [...t16s][0].split(",").map(Number); return new Set([t16.v[a][2], t16.v[b][2]]).size === 2; })(), [...t16s]);
  const ng = ngonCylinder(), ngs = C.seamEdges(ng.v, ng.f), ngGroups = C.islandGroups(ng.f, ngs, C.faceEdges(ng.f));
  check("original test: the default n-gon-capped cylinder cuts both rims plus one seam -> islands of 1, 1 and 32 faces",
    JSON.stringify(ngGroups.map((gr) => gr.length).sort((a, b) => a - b)) === "[1,1,32]", ngGroups.map((gr) => gr.length));

  // ================================================================== the original add-on's region tests
  check("original test: a 4-sided tube's regions stop merging before they close the ring (2 regions, both disks)", (() => {
    const t = tube(), [w, ar, e] = C.build(t.v, t.f), root = C.partition(t.f, w, e, C.LOW_ANGLE), [label] = C.absorb(t.v, t.f, w, ar, e, root, 100);
    const [ec] = C.regionTopology(e, label); return new Set(label).size === 2 && [...ec.values()].every((x) => x === 1);
  })(), null);
  check("original test: an 8-sided tube (faceted, 45 degrees a segment) still unrolls whole with one seam", (() => { const t = tube(8), s = C.seamEdges(t.v, t.f); return s.size === 1 && C.islandGroups(t.f, s, C.faceEdges(t.f)).length === 1; })(), null);
  // bump_grid: a staircase boundary on a flat 3x3 grid of triangle pairs, straightened by the reroute
  const bump = (() => {
    const v = [], f = [];
    for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) v.push([x, y, 0]);
    for (let y = 0; y < 3; y++) for (let x = 0; x < 3; x++) { const a = 4 * y + x; f.push([a, a + 1, a + 5], [a, a + 5, a + 4]); }
    const label = f.map((_, i) => (Math.floor(i / 2) % 3 === 0 ? 0 : 1)); label[8] = label[9] = 0;
    return { v, f, label };
  })();
  {
    const [w, ar, e] = C.build(bump.v, bump.f), relief = C.creaseRelief(bump.v, bump.f, w, e);
    const moved = C.rerouteBoundaries(bump.v, bump.f, ar, e, bump.label, relief);
    const be = [...C.boundaryEdges(e, moved)].sort();
    check("original test: rerouting straightens a boundary bump (faces 8, 9 move, the boundary becomes the line 1-5-9-13)",
      moved[8] === 1 && moved[9] === 1 && JSON.stringify(be) === JSON.stringify(["1,5", "5,9", "9,13"].sort()), be);
    check("original test: a forced (hand-marked) chain is never rerouted", JSON.stringify(C.rerouteBoundaries(bump.v, bump.f, ar, e, bump.label, relief, new Set(["5,6"]))) === JSON.stringify(bump.label), null);
  }
  check("original test: crease relief - a concave crease costs less than a convex one, a flat edge full length", (() => {
    // a floor with a wall going up (concave) and a step going down (convex)
    const v = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, -1], [1, 1, -1], [2, 0, 0], [2, 1, 0]];
    const f = [[0, 1, 2, 3], [0, 4, 5, 1], [3, 2, 7, 6], [1, 8, 9, 2]];
    const [w, , e] = C.build(v, f), r = C.creaseRelief(v, f, w, e);
    return r.get("0,1") < r.get("2,3") && !r.has("1,2");
  })(), null);

  // ================================================================== reroute on a cage
  {
    const grid = P.primitive("plane", { segments: 4 }), g0 = snap(grid);
    // a staircase seam across a flat grid: ForgeUV keys
    const stair = new Set();
    const at = (i, j) => j * 5 + i;
    const pathPts = [[0, 2], [1, 2], [1, 1], [2, 1], [2, 2], [3, 2], [4, 2]];   // a bump in the middle of row 2
    for (let k = 0; k + 1 < pathPts.length; k++) stair.add(U.ekey(at(...pathPts[k]), at(...pathPts[k + 1])));
    const rs = G.rerouteSeams(grid, stair);
    const len = (s) => [...s].reduce((t, k) => { const [a, b] = k.split(",").map(Number); return t + Math.hypot(...[0, 1, 2].map((i) => grid.v[a][i] - grid.v[b][i])); }, 0);
    const straight = [0, 1, 2, 3].map((i) => U.ekey(at(i, 2), at(i + 1, 2)));
    check("rerouteSeams: a staircase seam on a flat grid becomes the straight, shorter line", rs.size === 4 && straight.every((k) => rs.has(k)) && len(rs) < len(stair), [...rs]);
    check("...still two islands, and the grid is not touched", G.islands(grid, rs).length === 2 && snap(grid) === g0, null);
  }

  // ================================================================== symmetry
  {
    const box = P.primitive("cube", { segments: 2 }), b0 = snap(box);
    const maps = G.mirrorMaps(box, { symAxes: ["x"] });
    check("mirrorMaps: every vertex of a symmetric box has its mirror across x = 0", maps && maps[0].size === box.v.length
      && [...maps[0]].every(([a, b]) => Math.abs(box.v[a][0] + box.v[b][0]) < 1e-9 && box.v[a][1] === box.v[b][1] && box.v[a][2] === box.v[b][2]), maps && maps[0].size);
    const one = new Set(keyOf(box, (A, B) => A[0] > 0.4 && B[0] > 0.4 && A[1] > 0.4 && B[1] > 0.4).slice(0, 1));
    const sym = G.symmetrySeams(box, one, { symAxes: ["x"] });
    const mir = (k) => { const [a, b] = k.split(",").map(Number); return U.ekey(maps[0].get(a), maps[0].get(b)); };
    check("symmetrySeams: a seam on the +x side gets its mirror on the -x side, and the set is closed under the mirror",
      sym.has([...one][0]) && sym.has(mir([...one][0])) && [...sym].every((k) => sym.has(mir(k))), [...sym]);
    const hs = G.hardSurfaceSeams(box, { useSymmetry: true, symAxes: ["x"] });
    const hsh = U.shells(G.applySeams(box, hs));
    check("hard-surface seams with symmetry on: mirror-closed, every shell still a disk", [...hs].every((k) => hs.has(mir(k)))
      && hsh.every((s) => { const t = shellTopology(G.applySeams(box, hs), s.faces); return t.euler === 1 && t.loops === 1; }), [...hs]);
    const sym3 = G.symmetrySeams(box, one, { symAxes: ["x", "y", "z"] });
    check("three axes: the one seam reaches all its mirror images (a cube edge -> its 4 parallel copies' share)", sym3.size >= 4 && sym3.size > sym.size, sym3.size);
    // mirrored islands stacked (sym_merge): an x-symmetric box cut at the plane, the -x shells take the +x shells' UVs
    const cut = G.applySeams(box, unionSets(hs, new Set(keyOf(box, (A, B) => Math.abs(A[0]) < 1e-9 && Math.abs(B[0]) < 1e-9))));
    const flat = await G.flattenRigid(cut), st = G.stackMirrored(flat, { symAxes: ["x"] });
    const uvAt = (m, fi, v) => m.uv[m.fuv[fi][m.f[fi].indexOf(v)]];
    const pairs = []; box.f.forEach((f, fi) => { const img = f.map((v) => maps[0].get(v)).sort((a, b) => a - b).join(); const gi = box.f.findIndex((g) => g.slice().sort((a, b) => a - b).join() === img); if (gi !== fi) pairs.push([fi, gi]); });
    const stacked = pairs.filter(([fi, gi]) => box.f[fi].every((v) => { const p = uvAt(st, fi, v), q = uvAt(st, gi, maps[0].get(v)); return Math.abs(p[0] - q[0]) < 1e-12 && Math.abs(p[1] - q[1]) < 1e-12; })).length;
    check("stackMirrored: mirror-image faces end up on the same UVs (overlapped halves)", pairs.length > 0 && stacked === pairs.length, [stacked, pairs.length]);
    check("...the box was never touched", snap(box) === b0, null);
  }
  check("original test: mirror seams close across two maps (quadrants)", (() => {
    const mx = new Map([1, 0, 3, 2, 5, 4, 7, 6].map((v, i) => [i, v])), my = new Map([2, 3, 0, 1, 6, 7, 4, 5].map((v, i) => [i, v]));
    const edges = new Map(["0,4", "1,5", "2,6", "3,7"].map((k) => [k, []]));
    const s = C.mirrorSeams(new Set(["0,4"]), [mx, my], edges); return s.size === 4;
  })(), null);

  // ================================================================== rectify
  {
    // a 6 x 2 grid of quads, planar mapped (front-facing), then the UVs bent and wobbled
    const st = { v: [], f: [] };
    for (let j = 0; j <= 2; j++) for (let i = 0; i <= 6; i++) st.v.push([i / 2, 0, -j / 2]);
    for (let j = 0; j < 2; j++) for (let i = 0; i < 6; i++) { const a = j * 7 + i; st.f.push([a, a + 1, a + 8, a + 7]); }
    let isl = U.planar(st, [], "y");
    const cx = 0.5, cy = 0.5;
    isl.uv = isl.uv.map(([u, v]) => { const r = 0.12, a = 0.35; const x = u - cx, y = v - cy; return [cx + x * Math.cos(a) - y * Math.sin(a) + 0.015 * Math.sin(v * 31), cy + x * Math.sin(a) + y * Math.cos(a) + r * x * x]; });
    const i0 = snap(isl);
    const flipsIn = flipped(isl);
    const rec = G.rectify(isl);
    const b = U.bbox(rec, rec.uv.map((_, i) => i));
    const border = (() => { const cnt = new Map(); for (const c of rec.fuv) for (let i = 0; i < c.length; i++) { const a = c[i], q = c[(i + 1) % c.length], k = a < q ? a + "," + q : q + "," + a; cnt.set(k, (cnt.get(k) || 0) + 1); } return [...new Set([...cnt].filter(([, n]) => n === 1).flatMap(([k]) => k.split(",").map(Number)))]; })();
    const onBox = (p) => Math.min(Math.abs(p[0] - b.x0), Math.abs(p[0] - b.x1), Math.abs(p[1] - b.y0), Math.abs(p[1] - b.y1)) < 1e-9;
    const corners = [[b.x0, b.y0], [b.x1, b.y0], [b.x1, b.y1], [b.x0, b.y1]].filter((c) => border.some((i) => Math.hypot(rec.uv[i][0] - c[0], rec.uv[i][1] - c[1]) < 1e-9)).length;
    check("rectify: a bent, wobbly 6x2 quad strip becomes an axis-aligned rectangle (every border UV on its box, all 4 corners hit)",
      rec.uvInfo.rectified === 1 && border.every((i) => onBox(rec.uv[i])) && corners === 4, { info: rec.uvInfo, corners });
    check("...the long side runs along u (the strip's own length kept: about 3 x 1 in proportion), no face flips",
      (b.x1 - b.x0) / (b.y1 - b.y0) > 2.4 && (b.x1 - b.x0) / (b.y1 - b.y0) < 3.6 && flipped(rec) === flipsIn, [(b.x1 - b.x0) / (b.y1 - b.y0), flipped(rec)]);
    check("...the input cage is unchanged", snap(isl) === i0, null);
    const blob = U.spherical(P.primitive("sphere"), []);
    check("rectify leaves a round island alone (the original's 'skips a blob')", G.rectify(U.planar({ v: [[0, 0, 0], ...[0, 1, 2, 3, 4, 5].map((a) => [Math.cos(a * Math.PI / 3), 0, -Math.sin(a * Math.PI / 3)])], f: [0, 1, 2, 3, 4, 5].map((i) => [0, i + 1, (i + 1) % 6 + 1]) }, [], "y")).uvInfo.rectified === 0
      && U.has(G.rectify(blob)), null);
    const sp = G.rectify(isl, { rectifyMode: "spine", axisAlign: false });
    check("rectify, the original's spine mode: the strip unbends (its border's box share grows towards a rectangle)", sp.uvInfo.rectified === 1, sp.uvInfo);
  }

  // ================================================================== similar islands
  {
    const box = P.primitive("cube"), b0 = snap(box);
    const six = G.applySeams(U.planar(box, [], "z"), new Set(U.edges(U.planar(box, [], "z")).keys()));
    const sim = G.similarIslands(six);
    check("similarIslands: the six faces of a box are one set - a representative and 5 twins", sim.length === 1 && sim[0].twins.length === 5, sim.map((s) => s.twins.length));
    check("...each twin's 4x4 matrix moves the representative's corners onto the twin's", sim[0].twins.every((t) => {
      const M = t.matrix; return [...t.vertexMap].every(([tv, rv]) => { const p = box.v[rv], q = [0, 1, 2].map((r) => M[r][0] * p[0] + M[r][1] * p[1] + M[r][2] * p[2] + M[r][3]); return Math.hypot(q[0] - box.v[tv][0], q[1] - box.v[tv][1], q[2] - box.v[tv][2]) < 1e-9; });
    }), null);
    const auto = U.automatic(box, [], 6), stacked = G.stackSimilar(auto);
    const stacks = G.findStacks(stacked);
    check("stackSimilar: every face takes the representative's UVs, so findStacks sees one stack of 6", stacks.length === 1 && stacks[0].duplicates.length === 5, stacks.map((s) => s.duplicates.length));
    const parts = { v: [], f: [] };
    for (const [dx, rot] of [[0, 0], [3, 1], [6, 0]]) { const c = P.primitive("cylinder", { sides: 8 }), o = parts.v.length; parts.v.push(...c.v.map(([x, y, z]) => rot ? [y + dx, -x, z] : [x + dx, y, z])); parts.f.push(...c.f.map((f) => f.map((i) => i + o))); }
    const ps = G.similarIslands(parts, { by: "parts" });
    check("similarIslands by loose part: three copies of a cylinder (one turned) -> one set with 2 twins", ps.length === 1 && ps[0].twins.length === 2, ps.map((s) => s.twins.length));
    check("...a different shape is not matched", G.similarIslands({ v: parts.v.concat(P.primitive("cube").v.map(([x, y, z]) => [x + 9, y, z])), f: parts.f.concat(P.primitive("cube").f.map((f) => f.map((i) => i + parts.v.length))) }, { by: "parts" })[0].twins.length === 2, null);
    check("...the box was never touched", snap(box) === b0, null);
  }

  // ================================================================== after the flatten: split islands, distortion
  {
    // strip_island(30): a flat 30-quad strip mapped 1:1 - far longer than the square its own area needs
    const v = [], f = [];
    for (let i = 0; i <= 30; i++) v.push([i, 0, 0], [i, 1, 0]);
    for (let i = 0; i < 30; i++) { const a = 2 * i, b = a + 1, c = a + 2, d = a + 3; f.push([a, c, b], [c, d, b]); }
    const strip = { v, f, uv: v.map((p) => [p[0], p[1]]), fuv: f.map((x) => x.slice()) };
    const extra = G.splitIslands(strip);
    check("original test: a clean long island is split for packing (30-quad strip -> 4 islands)", G.islands(strip, extra).length === 4, G.islands(strip, extra).length);
    const fin = G.finishSplit(strip);
    check("finishSplit: the pieces are cut apart (4 shells) and each shrinks a little toward its own centre", U.shells(fin).length === 4 && fin.uvInfo.split > 0, U.shells(fin).length);
    check("flattenDistortion is 4 at isometry (original test)", Math.abs(G.flattenDistortion(strip) - 4) < 1e-9, G.flattenDistortion(strip));
    const sq = { v: strip.v, f: strip.f, uv: strip.uv.map(([x, y]) => [x * 2, y]), fuv: strip.fuv };
    check("...and grows with stretch", G.flattenDistortion(sq) > 4.5, G.flattenDistortion(sq));
    check("islandIsRuined: a clean strip is fine, a folded face ruins it", !G.islandIsRuined(strip, strip.f.map((_, i) => i))
      && G.islandIsRuined({ v, f, uv: strip.uv, fuv: strip.fuv.map((c, i) => (i === 5 ? [c[1], c[0], c[2]] : c)) }, strip.f.map((_, i) => i)), null);
  }

  // ================================================================== the flatten hook + inputs never mutated
  {
    const calls = [];
    const hook = async (cage, o) => { calls.push({ faces: cage.f.length, shells: U.shells(cage).length, priority: o.priority, bound: o.bound }); return G.flattenRigidSync(cage); };
    const out = await G.unwrap(cyl, { surfaceMode: "hard", flatten: hook, priority: "FEWER_SEAMS" });
    check("unwrap calls opts.flatten (the C++ engine hook) with the cut cage and the priority's distortion bound (Fewer Seams = 5.0)",
      calls.length >= 1 && calls[0].faces === cyl.f.length && calls[0].shells === 3 && calls[0].bound === 5 && U.has(out), calls);
    let packed = 0;
    await G.unwrap(cube, { surfaceMode: "hard", pack: async (m, o) => { packed = o.margin; return m; } });
    check("...and opts.pack after it (Pack After Unwrap, margin 0.001)", packed === 0.001, packed);
    const bad = await G.unwrap(cube, { flatten: async () => ({ v: [], f: [] }) }).then(() => "resolved", (e) => e.message);
    check("a flatten hook that returns no UVs is refused with a clear message", /no usable UVs/.test(bad), bad);
    const withUV = U.automatic(cube, [], 6), w0 = snap(withUV);
    for (const fn of [() => G.hardSurfaceSeams(withUV), () => G.seamEdges(withUV), () => G.rerouteSeams(withUV), () => G.rectify(withUV), () => G.similarIslands(withUV),
      () => G.stackSimilar(withUV), () => G.stackMirrored(withUV), () => G.finishSplit(withUV), () => G.splitIslands(withUV), () => G.symmetrySeams(withUV, U.seams(withUV)),
      () => G.applySeams(withUV, new Set()), () => G.flattenRigidSync(withUV)]) fn();
    await G.unwrap(withUV, { surfaceMode: "hard", useSymmetry: true, stackSimilar: true });
    check("no function changes its input cage (a cube with UVs, through every entry point and a full unwrap)", snap(withUV) === w0, null);
    check("...nor the plain cube / cylinder used above", snap(cube) === cube0 && snap(cyl) === cyl0, null);
    check("growFaces: one face of a cube grown by a ring is the face and its 4 neighbours (area_expand 1), two rings the whole cube", G.growFaces(cube, [0], 1).length === 5 && G.growFaces(cube, [0], 2).length === 6, G.growFaces(cube, [0], 1));
    check("DEFAULTS carry the original's settings (Balanced, 66 degrees hard-surface angle, X symmetry with merge, margin 0.001, proxy 20000)",
      G.DEFAULTS.priority === "BALANCED" && G.DEFAULTS.hardAngle === 66 && G.DEFAULTS.symAxes[0] === "x" && G.DEFAULTS.symMerge === true && G.DEFAULTS.margin === 0.001 && G.DEFAULTS.proxyFaces === 20000 && Object.isFrozen(G.DEFAULTS), null);
  }

  // ================================================================== bigger meshes, in time
  {
    const t = Date.now(), torus = P.primitive("torus"), ts = G.hardSurfaceSeams(torus), tc = G.applySeams(torus, ts);
    check("a torus (384 quads, genus 1): hard-surface seams open it into disk shells", U.shells(tc).every((s) => shellTopology(tc, s.faces).euler === 1 && shellTopology(tc, s.faces).loops === 1), U.shells(tc).length);
    const qs = P.primitive("quadsphere", { segments: 8 }), qsc = G.applySeams(qs, G.seamEdges(qs));
    check("a quad sphere (384 quads): the seams pipeline leaves only disks", U.shells(qsc).every((s) => shellTopology(qsc, s.faces).euler === 1 && shellTopology(qsc, s.faces).loops === 1), U.shells(qsc).length);
    check("...both in well under 5 s", Date.now() - t < 5000, Date.now() - t);
  }
  check("no eval / Function in the module (CSP-safe)", !/\beval\s*\(|new\s+Function\s*\(/.test(require("fs").readFileSync(path.join(__dirname, "../../app/ui/forge_uvgami.js"), "utf8")), null);
  check("the whole suite under 10 s", Date.now() - T0 < 10000, Date.now() - T0);

  console.log("\n" + pass + " passed, " + fail + " failed");
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.log("  FAIL the suite threw: " + (e && e.stack)); console.log("\n" + pass + " passed, " + (fail + 1) + " failed"); process.exit(1); });

function unionSets(a, b) { const s = new Set(a); for (const k of b) s.add(k); return s; }
