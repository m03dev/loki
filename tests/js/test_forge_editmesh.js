// Edit Mesh rows from docs/FORGE_MAYA_PARITY.md: Add Divisions, Flip Triangle Edge, Symmetrize, Flip (forge_polyops.js)
//   node tests/js/test_forge_editmesh.js
"use strict";
global.window = global;
require("../../app/ui/forge_poly.js");
require("../../app/ui/forge_polyops.js");
const P = window.ForgePoly;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d).slice(0, 300))); };
const closed = (m) => { const s = P.meshStats(m); return s.border === 0 && s.nonManifoldEdges === 0; };
const move = (m, x) => P.transform(m, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, 0, 0, 1]);
const cube = P.primitive("cube");

let r = P.addDivisions(cube, [0], { divisions: 1 });
check("Add Divisions: one face -> 4 quads, the cube stays closed (neighbours take the edge points)", r.m.f.length === 9 && closed(r.m)
  && r.sel.f.length === 4, [r.m.f.length, P.meshStats(r.m)]);
r = P.addDivisions(cube, cube.f.map((_, i) => i), { divisions: 2 });
check("Add Divisions x2 on every face: 6 * 16 quads, closed, same shape", r.m.f.length === 96 && closed(r.m)
  && Math.abs(P.volume(r.m) - 1) < 1e-9 && r.m.f.every((f) => f.length === 4));
check("Add Divisions with nothing picked says so", P.addDivisions(cube, [], {}).warn.length > 0);

const tri = P.triangulateFaces(cube, [0]).m, T = P.topology(tri);
const inner = T.edges.find((e) => e.faces.length === 2 && e.faces.every((fi) => tri.f[fi].length === 3));
r = P.flipTriangleEdge(tri, [[inner.a, inner.b]]);
const T2 = P.topology(r.m);
check("Flip Triangle Edge: the shared edge now joins the other two corners, still closed, same faces",
  r.m.f.length === tri.f.length && closed(r.m) && T2.edge(inner.a, inner.b) === undefined && r.sel.e.length === 1, r.warn);
check("Flip Triangle Edge on a quad edge does nothing and says so", P.flipTriangleEdge(cube, [[0, 1]]).warn.length > 0);

r = P.symmetrize(move(cube, 0.3), { axis: "x" });
const xs = r.m.v.map((p) => p[0]);
check("Symmetrize X (+): the +X side mirrored onto -X, cut on the plane, welded, closed",
  Math.abs(Math.min(...xs) + 0.8) < 1e-9 && Math.abs(Math.max(...xs) - 0.8) < 1e-9 && closed(r.m) && Math.abs(P.volume(r.m) - 1.6) < 1e-9, [Math.min(...xs), Math.max(...xs)]);
r = P.symmetrize(move(cube, 0.3), [0, 1], { axis: "x", direction: "-" });
const xs2 = r.m.v.map((p) => p[0]);
check("Symmetrize keeping the - side (the history's (m, faces, opts) form too)", Math.abs(Math.max(...xs2) - 0.2) < 1e-9 && closed(r.m));

r = P.flipMesh(move(cube, 2), { axis: "x" });
check("Flip: mirrored in place across X, faces still face out (positive volume)", Math.abs(Math.min(...r.m.v.map((p) => p[0])) + 2.5) < 1e-9
  && P.volume(r.m) > 0.99);
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
