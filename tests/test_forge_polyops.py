"""Forge poly ops (app/ui/forge_polyops.js) in node: every Edit Mesh operation of the pro tools gives a valid mesh -
no degenerate or duplicate faces, no unused vertices, closed meshes stay closed and manifold with every face pointing
outward (signed volume > 0) - plus a check of what each op is for (face counts, volumes, positions, the selection it
leaves, the warning when it cannot run, and that the input mesh is never changed). Skips without node. A few seconds.

    python tests/test_forge_polyops.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:600],)))


JS = r"""
const P = require(process.argv[1]);
const out = {};
// an independent checker (not P.meshCheck): structure, manifold, orientation, area
function valid(m, wantClosed, allowZeroArea) {
  const r = { ok: true, why: [] };
  const bad = (w) => { r.ok = false; r.why.push(w); };
  const used = new Uint8Array(m.v.length), dir = new Map(), und = new Map(), seen = new Set();
  m.f.forEach((f, fi) => {
    if (f.length < 3) bad("face " + fi + " has " + f.length + " vertices");
    if (new Set(f).size !== f.length) bad("face " + fi + " repeats a vertex");
    if (f.some((i) => !(i >= 0 && i < m.v.length))) { bad("face " + fi + " bad index"); return; }
    const k = f.slice().sort((a, b) => a - b).join(",");
    if (seen.has(k)) bad("duplicate face " + fi); seen.add(k);
    let n = [0, 0, 0];
    for (let i = 0; i < f.length; i++) {
      const a = m.v[f[i]], b = m.v[f[(i + 1) % f.length]];
      n = [n[0] + (a[1] - b[1]) * (a[2] + b[2]), n[1] + (a[2] - b[2]) * (a[0] + b[0]), n[2] + (a[0] - b[0]) * (a[1] + b[1])];
      used[f[i]] = 1;
      const d = f[i] + ">" + f[(i + 1) % f.length], u = Math.min(f[i], f[(i + 1) % f.length]) + "," + Math.max(f[i], f[(i + 1) % f.length]);
      dir.set(d, (dir.get(d) || 0) + 1); und.set(u, (und.get(u) || 0) + 1);
    }
    if (!allowZeroArea && Math.hypot(...n) < 1e-10) bad("face " + fi + " has no area");
  });
  if (used.some((u) => !u)) bad("unused vertices");
  for (const [d, c] of dir) if (c > 1) bad("directed edge " + d + " used twice (flipped faces)");
  let border = 0;
  for (const c of und.values()) { if (c > 2) bad("non-manifold edge"); if (c === 1) border++; }
  if (wantClosed) {
    if (border) bad(border + " border edges");
    for (const d of dir.keys()) { const [a, b] = d.split(">"); if (!dir.has(b + ">" + a)) { bad("open at " + d); break; } }
    if (!(P.volume(m) > 0)) bad("volume " + P.volume(m));
  }
  r.border = border; r.vol = P.volume(m); r.F = m.f.length; r.V = m.v.length;
  r.why = r.why.slice(0, 4);
  return r;
}
const snap = (m) => JSON.stringify([m.v, m.f]);
function run(name, m, fn, wantClosed, extra, allowZero) {
  const before = snap(m), res = fn(m);
  const r = valid(res.m, wantClosed, allowZero);
  r.untouched = snap(m) === before;
  r.warn = res.warn; r.sel = { v: res.sel.v.length, e: res.sel.e.length, f: res.sel.f.length };
  // the selection is in the new mesh's ids
  const keys = new Set();
  for (const f of res.m.f) for (let k = 0; k < f.length; k++) keys.add(P.edgeKey(f[k], f[(k + 1) % f.length]));
  r.selOk = res.sel.v.every((i) => i >= 0 && i < res.m.v.length) && res.sel.f.every((i) => i >= 0 && i < res.m.f.length)
    && res.sel.e.every(([a, b]) => keys.has(P.edgeKey(a, b)));
  if (extra) Object.assign(r, extra(res));
  out[name] = r;
  return res;
}
const near = (a, b, e) => Math.abs(a - b) < (e || 1e-6);
const cube = P.primitive("cube", { segments: 1 }), c2 = P.primitive("cube", { segments: 2 }), c3 = P.primitive("cube", { segments: 3 });
const T1 = P.topology(cube), T2 = P.topology(c2), T3 = P.topology(c3);
const top = cube.f.findIndex((f) => P.faceNormal(cube, f)[1] > 0.9), topF = cube.f[top];
const topsOf = (m) => m.f.map((f, i) => [i, P.faceNormal(m, f)[1]]).filter((x) => x[1] > 0.9).map((x) => x[0]);
const pair = (T, ei) => [T.edges[ei].a, T.edges[ei].b];
const allE1 = T1.edges.map((e) => [e.a, e.b]);
// an edge in the middle of a flat side of the 3x3x3 cube (both ends valence 4)
const flatE = T3.edges.findIndex((e) => [e.a, e.b].every((i) => Math.abs(c3.v[i][2] - 0.5) < 1e-6 && Math.abs(Math.abs(c3.v[i][0]) - 0.5) > 0.01 && Math.abs(Math.abs(c3.v[i][1]) - 0.5) > 0.01));
const plane2 = P.primitive("plane", { segments: 2 });

// ---- extrude
run("exFace", cube, (m) => P.extrudeFaces(m, [top], { thickness: 0.5 }), true, (r) => ({ capSel: r.sel.f[0] === top, capY: r.m.f[top].every((i) => near(r.m.v[i][1], 1)) }));
run("exOffset", cube, (m) => P.extrudeFaces(m, [top], { thickness: 0.5, offset: 0.1 }), true, (r) => ({ capW: Math.max(...r.m.f[top].map((i) => Math.abs(r.m.v[i][0]))) }));
run("exRegion", c2, (m) => P.extrudeFaces(m, topsOf(c2), { thickness: 0.25 }), true);
run("exSeparate", c2, (m) => P.extrudeFaces(m, topsOf(c2), { thickness: 0.25, keepTogether: false }), true);
run("exZero", cube, (m) => P.extrudeFaces(m, [top]), true, null, true);
run("exNone", cube, (m) => P.extrudeFaces(m, []), true, (r) => ({ same: r.m === cube }));
const pl = P.primitive("plane", { segments: 1 }), TP = P.topology(pl), plB = TP.edges.find((e) => e.faces.length === 1);
run("exEdgeBorder", pl, (m) => P.extrudeEdges(m, [[plB.a, plB.b]], { offset: 0.5 }), false, (r) => ({ outward: r.sel.e[0].every((i) => Math.max(Math.abs(r.m.v[i][0]), Math.abs(r.m.v[i][2])) > 0.99) }));
const plBorder = P.topology(plane2).edges.filter((e) => e.faces.length === 1).map((e) => [e.a, e.b]);
run("exEdgeRim", plane2, (m) => P.extrudeEdges(m, plBorder, { thickness: 0.3 }), false, null, false);
const samePos = (p, q) => p.every((x, k) => near(x, q[k]));
run("exEdgeZero", pl, (m) => P.extrudeEdges(m, [[plB.a, plB.b]]), false, (r) => ({ onOld: r.sel.e[0].every((i) => samePos(r.m.v[i], pl.v[plB.a]) || samePos(r.m.v[i], pl.v[plB.b])) && !samePos(r.m.v[r.sel.e[0][0]], r.m.v[r.sel.e[0][1]]) }), true);
const finRes = P.extrudeEdges(cube, [allE1[0]], { thickness: 0.3 });
out.exEdgeFin = { F: finRes.m.f.length, nm: P.meshCheck(finRes.m).nonManifold, warn: finRes.warn };
run("exVert", cube, (m) => P.extrudeVerts(m, [0], { length: 0.3, width: 0.2 }), true, (r) => ({ tipOut: Math.hypot(...r.m.v[r.sel.v[0]]) > Math.hypot(...cube.v[0]) }));

// ---- delete: dissolve edges / vertices
run("disEdge", c2, (m) => P.dissolveEdges(m, [pair(T2, 0)]), true);
const eqLoop = (() => { const ei = T2.edges.findIndex((e) => near(c2.v[e.a][1], 0) && near(c2.v[e.b][1], 0)); return P.edgeLoop(c2, T2, ei).map((i) => pair(T2, i)); })();
run("disLoopClean", c2, (m) => P.dissolveEdges(m, eqLoop, { cleanVerts: true }), true);
run("disLoopKeep", c2, (m) => P.dissolveEdges(m, eqLoop), true);
run("disBorder", plane2, (m) => P.dissolveEdges(m, [plBorder[0]]), false);
const centre2 = c2.v.findIndex((p) => near(p[1], 0.5) && near(p[0], 0) && near(p[2], 0));
run("disVert", c2, (m) => P.dissolveVerts(m, [centre2]), true);
// a multi-cut point on an edge, then on to its own end: the vertex is inserted, nothing is split (a winged vertex)
const split1 = P.multiCut(cube, [{ e: allE1[0], t: 0.5 }, { v: allE1[0][0] }]);
const midId = split1.m.v.findIndex((p) => samePos(p, [0, 1, 2].map((k) => (cube.v[allE1[0][0]][k] + cube.v[allE1[0][1]][k]) / 2)));
out.winged = { warn: split1.warn, V: split1.m.v.length, F: split1.m.f.length, mid: midId };
run("disWinged", split1.m, (m) => P.dissolveVerts(m, [midId]), true);
run("disCorner", P.primitive("plane", { segments: 1 }), (m) => P.dissolveVerts(m, [0]), false, (r) => ({ same: r.m.v.length === 4 }));
const plMid = plane2.v.findIndex((p) => near(p[0], 0) && near(p[2], 0));
run("disVertPlane", plane2, (m) => P.dissolveVerts(m, [plMid]), false);

// ---- bevel
run("bevelAll", cube, (m) => P.bevel(m, allE1), true);
run("bevelAllS3", cube, (m) => P.bevel(m, allE1, { segments: 3 }), true);
run("bevelOne", cube, (m) => P.bevel(m, [allE1[0]]), true);
run("bevelOneS3", cube, (m) => P.bevel(m, [allE1[0]], { segments: 3 }), true);
run("bevelFace", cube, (m) => P.bevel(m, { f: [top] }), true);
run("bevelGrid", c3, (m) => P.bevel(m, [flatE]), true);
run("bevelGridS2", c3, (m) => P.bevel(m, [flatE], { segments: 2 }), true);
run("bevelLoop", c3, (m) => P.bevel(m, P.edgeLoop(c3, T3, flatE).map((i) => pair(T3, i))), true);
run("bevelBorder", pl, (m) => P.bevel(m, [[plB.a, plB.b]]), false, (r) => ({ same: r.m === pl }));

// ---- connect / multi-cut / slice
const tE = (k) => [topF[k], topF[(k + 1) % 4]];
run("conEdges", cube, (m) => P.connect(m, { e: [tE(0), tE(2)] }), true);
run("conFour", cube, (m) => P.connect(m, { e: [tE(0), tE(1), tE(2), tE(3)] }), true);
run("conRing", c3, (m) => P.connect(m, { e: P.edgeRing(c3, T3, flatE).edges.map((i) => pair(T3, i)) }), true);
run("conVerts", cube, (m) => P.connect(m, { v: [topF[0], topF[2]] }), true);
run("conAdj", cube, (m) => P.connect(m, { v: [topF[0], topF[1]] }), true, (r) => ({ same: r.m === cube }));
run("mcut", cube, (m) => P.multiCut(m, [{ e: tE(0), t: 0.25 }, { e: tE(2), t: 0.75 }, { e: tE(1), t: 0.5 }]), true);
run("mcutFar", cube, (m) => { const p = cube.v[topF[0]], far = cube.v.findIndex((q) => samePos(q, p.map((x) => -x))); return P.multiCut(m, [{ v: topF[0] }, { v: far }]); }, true, (r) => ({ same: r.m === cube }));
run("slice", c2, (m) => P.sliceFaces(m, [], [0, 0.25, 0], [0, 1, 0]), true, (r) => ({ onPlane: r.sel.e.every(([a, b]) => near(r.m.v[a][1], 0.25) && near(r.m.v[b][1], 0.25)) }));

// ---- poke / bridge / fill / append
run("poke", cube, (m) => P.poke(m, [top], { offset: 0.2 }), true);
const half = P.deleteFaces(cube, [cube.f.findIndex((f) => P.faceNormal(cube, f)[0] > 0.9)]);
const other = P.deleteFaces(P.transform(cube, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, 0, 0, 1]), [cube.f.findIndex((f) => P.faceNormal(cube, f)[0] < -0.9)]);
const two = P.combine([half, other]), TT = P.topology(two), holes = TT.edges.filter((e) => e.faces.length === 1).map((e) => [e.a, e.b]);
run("bridge", two, (m) => P.bridge(m, holes), true);
run("bridgeDiv", two, (m) => P.bridge(m, holes, { divisions: 3 }), true);
const strip = P.combine([pl, P.transform(pl, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 0, 0, 1])]), TS = P.topology(strip);
const rightA = TS.edges.find((e) => e.faces.length === 1 && near(strip.v[e.a][0], 0.5) && near(strip.v[e.b][0], 0.5));
const leftB = TS.edges.find((e) => e.faces.length === 1 && near(strip.v[e.a][0], 1.5) && near(strip.v[e.b][0], 1.5));
run("bridgeOpen", strip, (m) => P.bridge(m, [[rightA.a, rightA.b], [leftB.a, leftB.b]], { divisions: 1 }), false);
run("bridgeBad", cube, (m) => P.bridge(m, [allE1[0], allE1[1]]), true, (r) => ({ same: r.m === cube }));
run("bridgeUneven", two, (m) => P.bridge(m, holes.slice(0, 3)), true, (r) => ({ same: r.m === two }));
const holed = P.deleteFaces(c2, topsOf(c2));
const rim = P.topology(holed).edges.filter((e) => e.faces.length === 1).map((e) => [e.a, e.b]);
run("fillHole", holed, (m) => P.fillHole(m, [rim[0]]), true);
const open1 = P.deleteFaces(cube, [top]);
run("append", open1, (m) => P.appendPolygon(m, P.topology(open1).edges.filter((e) => e.faces.length === 1).length === 4 ? (() => {
  const T = P.topology(open1), nx = new Map();
  for (const e of T.edges) if (e.faces.length === 1) { const f = open1.f[e.faces[0]], k = f.indexOf(e.a); if (f[(k + 1) % f.length] === e.b) nx.set(e.a, e.b); else nx.set(e.b, e.a); }
  const s = [...nx.keys()][0], loop = [s]; let x = nx.get(s); while (x !== s) { loop.push(x); x = nx.get(x); } return loop;   // the face's own direction: must be reversed
})() : []), true);

// ---- collapse / chamfer / weld
run("collapseE", c2, (m) => P.collapse(m, { e: [pair(T2, 0)] }), true);
run("collapseF", c2, (m) => P.collapse(m, { f: [0] }), true);
run("chamfer", cube, (m) => P.chamferVerts(m, [0, 1, 2, 3, 4, 5, 6, 7]), true);
run("chamferBorder", plane2, (m) => P.chamferVerts(m, [plMid, 0]), false);
run("weld", c2, (m) => P.targetWeld(m, T2.edges[0].a, T2.edges[0].b), true, (r) => ({ at: r.m.v[r.sel.v[0]].every((x, k) => near(x, c2.v[T2.edges[0].b][k])) }));
run("weldSame", c2, (m) => P.targetWeld(m, 3, 3), true, (r) => ({ same: r.m === c2 }));

// ---- offset loop / slide / spin
run("offsetLoop", c3, (m) => P.offsetEdgeLoop(m, pair(T3, flatE), { distance: 0.3 }), true);
const slideRes = P.slideEdge(c3, [pair(T3, flatE)], 0.5), slideNeg = P.slideEdge(c3, [pair(T3, flatE)], -0.5);
const moved = (r) => [T3.edges[flatE].a, T3.edges[flatE].b].map((i) => Math.hypot(...r.m.v[i].map((x, k) => x - c3.v[i][k])));
out.slide = { valid: valid(slideRes.m, true).ok && valid(slideNeg.m, true).ok, d: moved(slideRes), dn: moved(slideNeg),
  opposite: (() => { const i = T3.edges[flatE].a; const a = slideRes.m.v[i].map((x, k) => x - c3.v[i][k]), b = slideNeg.m.v[i].map((x, k) => x - c3.v[i][k]); return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] < 0; })(),
  sameTopo: slideRes.m.f.length === c3.f.length, sel: slideRes.sel.e.length };
run("slideLoop", c3, (m) => P.slideEdge(m, P.edgeLoop(c3, T3, flatE).map((i) => pair(T3, i)), 0.4), true);
run("spin", cube, (m) => P.spinEdge(m, [allE1[0]]), true, (r) => ({ gone: !P.topology(r.m).edge(...allE1[0]) && P.topology(r.m).edge(...r.sel.e[0]) !== undefined, quads: r.m.f.every((f) => f.length === 4) }));
const g21 = P.primitive("plane", { segments: 2 });
const midEdge = P.topology(g21).edges.find((e) => e.faces.length === 2);
run("spinPlane", g21, (m) => P.spinEdge(m, [[midEdge.a, midEdge.b]], -1), false);
run("spinBorder", pl, (m) => P.spinEdge(m, [[plB.a, plB.b]]), false, (r) => ({ same: r.m === pl }));

// ---- detach / extract / duplicate
run("detachV", cube, (m) => P.detach(m, { v: [0] }), false, (r) => ({ copies: r.sel.v.length }));
run("detachE", c2, (m) => P.detach(m, { e: eqLoop }), false, (r) => ({ shells: P.shells(r.m).map((s) => s.f.length) }));
run("detachOne", c2, (m) => P.detach(m, { e: [pair(T2, 0)] }), true, (r) => ({ same: r.m === c2 }));
run("extract", cube, (m) => P.extractFaces(m, [top]), false, (r) => ({ shells: P.shells(r.m).map((s) => s.f.length), sameId: r.sel.f[0] === top }));
run("duplicate", cube, (m) => P.duplicateFaces(m, [top]), false, (r) => ({ shells: P.shells(r.m).map((s) => s.f.length) }));

// ---- triangulate / quadrangulate
run("tri", cube, (m) => P.triangulateFaces(m, []), true);
const hexagon = { v: [0, 1, 2, 3, 4, 5].map((i) => [Math.cos(i), 0, -Math.sin(i)].map((x, k) => (k === 1 ? 0 : x))), f: [[0, 1, 2, 3, 4, 5]] };
const Lshape = { v: [[0, 0, 0], [2, 0, 0], [2, 0, -1], [1, 0, -1], [1, 0, -2], [0, 0, -2]], f: [[0, 1, 2, 3, 4, 5]] };
run("triConcave", Lshape, (m) => P.triangulateFaces(m, [0]), false, (r) => ({ area: r.m.f.reduce((s, f) => { const [a, b, c] = f.map((i) => r.m.v[i]); return s + Math.abs((b[0] - a[0]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[0] - a[0])) / 2; }, 0) }));
run("quad", P.triangulateFaces(cube, []).m, (m) => P.quadrangulate(m, []), true);
run("quadSphere", P.triangulateFaces(P.primitive("sphere", { segments: 12, rings: 6 }), []).m, (m) => P.quadrangulate(m, []), true);

// ---- average / relax / circularize
const bumpy = P.clone(c3); const cTop = bumpy.v.findIndex((p) => near(p[1], 0.5) && Math.abs(p[0]) < 0.2 && Math.abs(p[2]) < 0.2); bumpy.v[cTop] = [bumpy.v[cTop][0], 0.9, bumpy.v[cTop][2]];
run("average", bumpy, (m) => P.averageVerts(m, [cTop], { iterations: 1 }), true, (r) => ({ y: r.m.v[cTop][1] }));
run("relax", plane2, (m) => P.relax(m, [], { iterations: 3 }), false, (r) => ({ borderKept: r.m.v.every((p, i) => i === plMid || p.every((x, k) => near(x, plane2.v[i][k]))) }));
run("circFaces", c3, (m) => P.circularize(m, { f: topsOf(c3) }), true, (r) => {
  const rim = P.topology(r.m).edges.filter((e) => { const fs = e.faces.map((fi) => topsOf(c3).includes(fi)); return fs[0] !== fs[1]; });
  const vs = [...new Set(rim.flatMap((e) => [e.a, e.b]))], rad = vs.map((i) => Math.hypot(r.m.v[i][0], r.m.v[i][2]));
  return { rimN: vs.length, rSpread: Math.max(...rad) - Math.min(...rad), flat: vs.every((i) => near(r.m.v[i][1], 0.5)) };
});
run("circVerts", cube, (m) => P.circularize(m, { v: topF }), true, (r) => ({ rSpread: (() => { const rad = topF.map((i) => Math.hypot(r.m.v[i][0], r.m.v[i][2])); return Math.max(...rad) - Math.min(...rad); })() }));

// ---- wedge
run("wedge", cube, (m) => P.wedge(m, [top], [topF[0], topF[1]], { angle: 90, divisions: 4 }), true);
run("wedgeBad", cube, (m) => P.wedge(m, [top], allE1.find(([a, b]) => !topF.includes(a) && !topF.includes(b))), true, (r) => ({ same: r.m === cube }));

// ---- crease / hard + they travel through clone and through the ops
// two opposite edges of face 0 (P.topology lists a face's edges in order)
const cr = P.crease(cube, [allE1[0], allE1[2]], 2), hd = P.softHard(c2, [], { angle: 30 });
const afterEx = P.extrudeFaces(cr.m, [cube.f.findIndex((f) => !f.some((i) => cube.f[0].includes(i)))], { thickness: 0.2 });
out.flags = { creases: cr.m.creases.size, val: cr.m.creases.get(P.edgeKey(...allE1[0])), viaClone: P.clone(cr.m).creases.size, viaOld: P.extrude(cr.m, [0], 0.1).creases instanceof Map,
  afterEx: afterEx.m.creases ? afterEx.m.creases.size : -1, input: cube.creases === undefined, hard: hd.m.hard.size, all: P.topology(c2).edges.length,
  soft: P.setHard(hd.m, [pair(T2, 0)], false).m.hard.size, geo: snap(cr.m) === snap(cube),
  afterBevel: (() => { const b = P.bevel(cr.m, [allE1[0]]); return b.m.creases.size; })() };
// vertex ids stay put when no vertex is removed (new ones are appended)
const stable = (r, m) => m.v.every((p, i) => samePos(r.m.v[i], p));
out.stable = { connect: stable(P.connect(c3, { e: P.edgeRing(c3, T3, flatE).edges.map((i) => pair(T3, i)) }), c3),
  poke: stable(P.poke(c3, [5]), c3), offset: stable(P.offsetEdgeLoop(c3, pair(T3, flatE)), c3), cut: stable(split1, cube) };
// fuzz: random selections on bigger meshes, every result must be valid (closed stays closed) or a clean refusal
let seed = 7;
const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
const pick = (n, k) => { const s = new Set(); while (s.size < Math.min(k, n)) s.add(Math.floor(rnd() * n)); return [...s]; };
const fz = { runs: 0, bad: [] };
for (const base of [P.primitive("torus", { segments: 12, sides: 8 }), P.primitive("sphere", { segments: 10, rings: 6 }), c3]) {
  const T = P.topology(base), E = T.edges.map((e) => [e.a, e.b]);
  for (let trial = 0; trial < 12; trial++) {
    const fs = pick(base.f.length, 1 + Math.floor(rnd() * 6)), es = pick(E.length, 1 + Math.floor(rnd() * 6)).map((i) => E[i]);
    const vs = pick(base.v.length, 1 + Math.floor(rnd() * 5));
    const ops = {
      extrudeT: () => P.extrudeFaces(base, fs, { thickness: 0.05 }), extrudeF: () => P.extrudeFaces(base, fs, { thickness: 0.05, keepTogether: false }),
      bevel: () => P.bevel(base, es, { fraction: 0.4 }), bevel2: () => P.bevel(base, es, { fraction: 0.4, segments: 2 }), bevelF: () => P.bevel(base, { f: fs }),
      dissolveE: () => P.dissolveEdges(base, es, { cleanVerts: true }), dissolveV: () => P.dissolveVerts(base, vs),
      chamfer: () => P.chamferVerts(base, vs, { width: 0.2 }), extrudeV: () => P.extrudeVerts(base, vs, { length: 0.05 }),
      connectE: () => P.connect(base, { e: es }), connectV: () => P.connect(base, { v: vs }), poke: () => P.poke(base, fs),
      collapse: () => P.collapse(base, { e: es.slice(0, 1) }), spin: () => P.spinEdge(base, es), tri: () => P.triangulateFaces(base, fs),
      offset: () => P.offsetEdgeLoop(base, es[0]), slide: () => P.slideEdge(base, es, 0.3), wedge: () => P.wedge(base, fs.slice(0, 1), base.f[fs[0]].slice(0, 2), { angle: 45, divisions: 2 }),
    };
    for (const [name, fn] of Object.entries(ops)) {
      fz.runs++;
      let r;
      try { r = fn(); } catch (e) { fz.bad.push(name + " threw " + e.message); continue; }
      if (r.warn && r.m === base) continue;
      const v = valid(r.m, true, true);
      // a fin-free op on a closed mesh must stay closed and manifold; spin may fold a sphere's pole fan flat (allow 0 volume)
      if (!v.ok && !(name === "spin" && v.why.every((w) => w.startsWith("volume")))) fz.bad.push(name + ": " + v.why.join("; "));
    }
  }
}
out.fuzz = { runs: fz.runs, bad: fz.bad.slice(0, 6), nbad: fz.bad.length };
out.rules = { n: Object.keys(P.polyRules).length, can: P.canRun("bevel", cube, allE1), cannot: P.canRun("bridge", cube, [allE1[0]]) };
console.log(JSON.stringify(out));
"""


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("SKIP: no node")
        return 0
    res = subprocess.run([node, "-e", JS, str(REPO / "app" / "ui" / "forge_polyops.js")], capture_output=True, text=True,
                         timeout=50, check=False)
    if res.returncode != 0:
        check("forge_polyops.js runs", False, res.stderr)
        return 1
    o = json.loads(res.stdout)

    def ok(name, cond=True, **_):
        r = o[name]
        good = r["ok"] and r["untouched"] and r["selOk"] and cond
        return good

    def c(label, name, cond=True):
        check(label, ok(name, cond), o[name])

    def refused(label, name):
        r = o[name]
        check(label, bool(r["warn"]) and r.get("same") is True and r["untouched"], r)

    vol = lambda n: o[n]["vol"]  # noqa: E731
    F = lambda n: o[n]["F"]  # noqa: E731

    # extrude
    c("extrude a face: closed, +0.5 volume, the cap stays selected (same face id) and sits at y = 1", "exFace",
      abs(vol("exFace") - 1.5) < 1e-6 and F("exFace") == 10 and o["exFace"]["capSel"] and o["exFace"]["capY"] and o["exFace"]["sel"]["f"] == 1)
    c("extrude with offset: a frustum (volume 1 + 0.5/3 (1 + 0.64 + 0.8)), the cap 0.1 in from every side", "exOffset",
      abs(vol("exOffset") - (1 + 0.5 / 3 * (1 + 0.64 + 0.8))) < 1e-6 and abs(o["exOffset"]["capW"] - 0.4) < 1e-9)
    c("Keep Faces Together: 4 faces move as one region (6 walls, no inner walls)", "exRegion",
      abs(vol("exRegion") - 1.25) < 1e-6 and F("exRegion") == 24 + 8)
    c("Keep Faces Together off: every face gets its own 4 walls (same volume, 16 walls)", "exSeparate",
      abs(vol("exSeparate") - 1.25) < 1e-6 and F("exSeparate") == 24 + 16)
    c("extrude with thickness 0 still builds the walls (zero area until dragged), closed", "exZero", F("exZero") == 10)
    refused("extrude with nothing selected warns and leaves the mesh as it was", "exNone")
    c("edge extrude on a border: a quad strip, the new edge pushed outward and selected", "exEdgeBorder",
      F("exEdgeBorder") == 2 and o["exEdgeBorder"]["outward"] and o["exEdgeBorder"]["sel"]["e"] == 1)
    c("edge extrude of a whole open rim: one connected wall (shared new vertices)", "exEdgeRim",
      F("exEdgeRim") == 4 + 8 and o["exEdgeRim"]["V"] == 9 + 8 and o["exEdgeRim"]["border"] == 8)
    c("edge extrude with thickness 0: the new edge sits on the old one", "exEdgeZero", o["exEdgeZero"]["onOld"])
    check("edge extrude of an interior edge makes a fin (the edge then has 3 faces, like the pro tool)",
          o["exEdgeFin"]["F"] == 7 and o["exEdgeFin"]["nm"] == 1 and not o["exEdgeFin"]["warn"], o["exEdgeFin"])
    c("vertex extrude: a spike - 3 faces cut, a 3-triangle fan to the tip pushed outward", "exVert",
      F("exVert") == 9 and o["exVert"]["tipOut"] and vol("exVert") > 1)
    # delete
    c("Delete Edge dissolves: two faces become one n-gon, still closed, same volume", "disEdge",
      F("disEdge") == 23 and abs(vol("disEdge") - 1) < 1e-6 and o["disEdge"]["sel"] == {"v": 0, "e": 0, "f": 0})
    c("Ctrl+Delete on an edge loop also removes the winged vertices (16 quads, 18 vertices)", "disLoopClean",
      F("disLoopClean") == 16 and o["disLoopClean"]["V"] == 18 and abs(vol("disLoopClean") - 1) < 1e-6)
    c("...plain Delete keeps them (16 hexagons, 26 vertices)", "disLoopKeep", F("disLoopKeep") == 16 and o["disLoopKeep"]["V"] == 26)
    c("Delete on a border edge deletes its face", "disBorder", F("disBorder") == 3)
    c("Delete Vertex on an interior vertex merges its 4 faces into one (no vertex left in the middle)", "disVert",
      F("disVert") == 21 and o["disVert"]["V"] == 25 and abs(vol("disVert") - 1) < 1e-6)
    check("a Multi-Cut point on an edge inserts a vertex into both faces (nothing split yet)",
          not o["winged"]["warn"] and o["winged"]["V"] == 9 and o["winged"]["F"] == 6 and o["winged"]["mid"] == 8, o["winged"])
    c("Delete Vertex on a winged vertex just takes it out of its faces (back to the plain cube)", "disWinged",
      F("disWinged") == 6 and o["disWinged"]["V"] == 8 and abs(vol("disWinged") - 1) < 1e-6)
    check("a corner vertex of a single face cannot be deleted (warns, mesh unchanged)",
          bool(o["disCorner"]["warn"]) and o["disCorner"]["same"] and o["disCorner"]["untouched"], o["disCorner"])
    c("Delete Vertex in the middle of a 2x2 plane: one square face with 8 border vertices", "disVertPlane",
      F("disVertPlane") == 1 and o["disVertPlane"]["V"] == 8)
    # bevel
    c("bevel all 12 cube edges: 26 faces (6 + 12 strips + 8 corner triangles), closed, the volume an independent "
      "integration gives (0.71828), the 20 new faces selected", "bevelAll",
      F("bevelAll") == 26 and abs(vol("bevelAll") - 0.71828) < 3e-4 and o["bevelAll"]["sel"]["f"] == 20)
    c("bevel all edges with 3 segments: closed, rounder (more volume kept than the chamfer)", "bevelAllS3",
      F("bevelAllS3") == 6 + 36 + 8 and vol("bevelAllS3") > vol("bevelAll") and vol("bevelAllS3") < 1)
    c("bevel one cube edge: 7 faces (the side faces become pentagons), the prism d^2/2 is gone", "bevelOne",
      F("bevelOne") == 7 and abs(vol("bevelOne") - (1 - (0.5 * 0.49) ** 2 / 2)) < 1e-9)
    c("bevel one edge with 3 segments: the side faces take the rounded profile (9 faces), less is cut", "bevelOneS3",
      F("bevelOneS3") == 9 and 1 - (0.5 * 0.49) ** 2 / 2 < vol("bevelOneS3") < 1)
    c("bevel a face (its 4 border edges): closed, 10 faces", "bevelFace", F("bevelFace") == 10)
    c("bevel an edge in a flat grid: one strip, the volume unchanged, no sliver faces", "bevelGrid",
      F("bevelGrid") == 55 and abs(vol("bevelGrid") - 1) < 1e-9)
    c("...with 2 segments", "bevelGridS2", abs(vol("bevelGridS2") - 1) < 1e-9)
    c("bevel a whole edge loop round the cube: a closed band of 12 strips", "bevelLoop",
      F("bevelLoop") == 54 + 12 and o["bevelLoop"]["sel"]["f"] == 12)
    refused("a border edge cannot be bevelled", "bevelBorder")
    # connect / multi-cut / slice
    c("Connect two opposite edges of a face: split through the midpoints, the new edge selected", "conEdges",
      F("conEdges") == 7 and o["conEdges"]["sel"]["e"] == 1)
    c("Connect all 4 edges of a face: a cross through a new centre vertex (4 quads)", "conFour",
      F("conFour") == 9 and o["conFour"]["sel"]["e"] == 4)
    c("Connect an edge ring: a new edge loop (12 new edges)", "conRing", F("conRing") == 66 and o["conRing"]["sel"]["e"] == 12)
    c("Connect two vertices of a face: split between them", "conVerts", F("conVerts") == 7)
    refused("Connect two neighbouring vertices warns (they already share an edge)", "conAdj")
    c("Multi-Cut across a face and on into the next: two splits", "mcut", F("mcut") == 8 and o["mcut"]["sel"]["e"] == 2)
    refused("Multi-Cut between points that share no face warns, mesh unchanged", "mcutFar")
    c("Slice the 2x2x2 cube at y = 0.25: 8 new edges, all on the plane", "slice",
      F("slice") == 32 and o["slice"]["sel"]["e"] == 8 and o["slice"]["onPlane"])
    # poke / bridge / fill / append
    c("Poke: 4 triangles to a raised centre (a pyramid on the cube)", "poke",
      F("poke") == 9 and abs(vol("poke") - (1 + 0.2 / 3)) < 1e-9 and o["poke"]["sel"]["f"] == 4)
    c("Bridge two open cubes facing each other: one closed mesh (volume 1 + 1 + the 2-long gap)", "bridge",
      abs(vol("bridge") - 4) < 1e-6 and o["bridge"]["sel"]["f"] == 4)
    c("Bridge with 3 divisions: 16 bridge faces, same volume", "bridgeDiv", abs(vol("bridgeDiv") - 4) < 1e-6 and o["bridgeDiv"]["sel"]["f"] == 16)
    c("Bridge two open border edges with 1 division: 2 quads, still one consistent surface", "bridgeOpen",
      F("bridgeOpen") == 4 and o["bridgeOpen"]["border"] == 10)
    refused("Bridge refuses edges that are not on a border", "bridgeBad")
    refused("Bridge refuses chains of different lengths", "bridgeUneven")
    c("Fill Hole on a selected border edge closes the cube's open top (volume 1)", "fillHole",
      abs(vol("fillHole") - 1) < 1e-6 and o["fillHole"]["sel"]["f"] == 1)
    c("Append to Polygon closes a hole, turned to face out (the given order was the wrong way)", "append",
      abs(vol("append") - 1) < 1e-6 and F("append") == 6)
    # collapse / chamfer / weld
    c("Collapse an edge: one vertex fewer, the two quads become triangles, closed", "collapseE",
      F("collapseE") == 24 and o["collapseE"]["V"] == 25 and o["collapseE"]["sel"]["v"] == 1)
    c("Collapse a face: it and its neighbours' sides fold to its centre, closed", "collapseF", F("collapseF") == 23 and o["collapseF"]["V"] == 23)
    c("Chamfer all 8 corners: 6 octagons + 8 triangles, volume 1 - 8 (w^3 / 6)", "chamfer",
      F("chamfer") == 14 and abs(vol("chamfer") - (1 - 8 * 0.25 ** 3 / 6)) < 1e-9 and o["chamfer"]["sel"]["f"] == 8)
    c("Chamfer on a plane (an inner and a corner vertex): valid, the corner just cut", "chamferBorder", F("chamferBorder") == 5)
    c("Target Weld merges a vertex into the other one, at the other's place", "weld", o["weld"]["V"] == 25 and o["weld"]["at"])
    refused("Target Weld onto itself warns", "weldSame")
    # offset loop / slide / spin
    c("Offset Edge Loop: two new loops either side (24 new faces), all quads, closed, volume 1", "offsetLoop",
      F("offsetLoop") == 78 and o["offsetLoop"]["sel"]["e"] == 24 and abs(vol("offsetLoop") - 1) < 1e-6)
    s = o["slide"]
    check("Edge Slide moves the edge half way along its side edges (1/6), +t and -t go opposite ways, topology kept",
          s["valid"] and all(abs(x - 1 / 6) < 1e-9 for x in s["d"] + s["dn"]) and s["opposite"] and s["sameTopo"] and s["sel"] == 1, s)
    c("Edge Slide of a whole loop stays closed", "slideLoop")
    c("Spin Edge: the edge turns to the next vertices, faces stay quads, still closed", "spin", o["spin"]["gone"] and o["spin"]["quads"])
    c("Spin Edge backward on a flat grid", "spinPlane", F("spinPlane") == 4)
    refused("Spin Edge refuses a border edge", "spinBorder")
    # detach / extract / duplicate
    c("Detach a cube corner: 3 copies, one per face", "detachV", o["detachV"]["copies"] == 3 and o["detachV"]["V"] == 10)
    c("Detach along a closed edge loop: the cube falls into two open halves", "detachE", o["detachE"]["shells"] == [12, 12])
    refused("Detach on one interior edge warns (it reaches no border)", "detachOne")
    c("Extract a face: its own shell, same face id, selected", "extract", o["extract"]["shells"] == [5, 1] and o["extract"]["sameId"])
    c("Duplicate a face: a copy as its own shell", "duplicate", o["duplicate"]["shells"] == [6, 1] and o["duplicate"]["sel"]["f"] == 1)
    # triangulate / quadrangulate
    c("Triangulate the cube: 12 triangles, closed", "tri", F("tri") == 12)
    c("Triangulate a concave L: 4 triangles covering exactly its area (3)", "triConcave",
      F("triConcave") == 4 and abs(o["triConcave"]["area"] - 3) < 1e-9)
    c("Quadrangulate the triangulated cube: back to 6 quads", "quad", F("quad") == 6)
    c("Quadrangulate a triangulated sphere: closed, fewer faces", "quadSphere", F("quadSphere") < 120)
    # average / relax / circularize
    c("Average Vertices pulls a raised vertex back among its 4 neighbours (y 0.9 -> 0.5)", "average", abs(o["average"]["y"] - 0.5) < 1e-9)
    c("Relax keeps border vertices pinned", "relax", o["relax"]["borderKept"])
    c("Circularize the 3x3 top: its 12 rim vertices on one circle in the top plane, closed", "circFaces",
      o["circFaces"]["rimN"] == 12 and o["circFaces"]["rSpread"] < 1e-9 and o["circFaces"]["flat"])
    c("Circularize a face's 4 vertices", "circVerts", o["circVerts"]["rSpread"] < 1e-9)
    # wedge
    c("Wedge the top face 90 degrees round its edge in 4 steps: closed, volume 1 + 2 sin(22.5)", "wedge",
      abs(vol("wedge") - (1 + 2 * 0.3826834323650898)) < 1e-9)
    refused("Wedge needs the hinge on the faces' border", "wedgeBad")
    # flags
    fl = o["flags"]
    check("Crease marks edges (2 of them, weight 2) without moving anything; the input mesh gets none",
          fl["creases"] == 2 and fl["val"] == 2 and fl["geo"] and fl["input"], fl)
    check("creases travel through P.clone, the old ops and the new ones (bevelling a creased edge drops its crease)",
          fl["viaClone"] == 2 and fl["viaOld"] and fl["afterEx"] == 2 and fl["afterBevel"] == 1, fl)
    check("Soften/Harden by angle: every edge of a cube is hard at 30 degrees except the flat ones; soften removes one",
          fl["hard"] == 24 and fl["soft"] == 23, fl)
    check("vertex ids stay stable when no vertex is removed (Connect, Poke, Offset Edge Loop, Multi-Cut)",
          all(o["stable"].values()), o["stable"])
    check("fuzz: %d random selections on a torus, a sphere and a 3x3x3 cube - every result valid and closed, or a clean refusal"
          % o["fuzz"]["runs"], o["fuzz"]["nbad"] == 0, o["fuzz"])
    check("the rules are written down and canRun follows the ops' warnings",
          o["rules"]["n"] >= 25 and o["rules"]["can"] and not o["rules"]["cannot"], o["rules"])
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
