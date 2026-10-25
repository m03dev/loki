// Select > Convert Selection, Similar, Shortest Edge Path (forge_polyops.js; FORGE_MODELING_FOUNDATION stage 4)
//   node tests/js/test_forge_select.js
"use strict";
global.window = global;
require("../../app/ui/forge_poly.js");
require("../../app/ui/forge_polyops.js");
const P = window.ForgePoly;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d).slice(0, 300))); };
const m = P.addDivisions(P.primitive("cube"), [0, 1, 2, 3, 4, 5], { divisions: 1 }).m;   // 24 quads
const f0 = m.f[0];
let o = P.convertSel(m, { f: [0] }, "verts");
check("face -> its 4 vertices", o.v.length === 4 && o.v.every((x) => f0.includes(x)));
o = P.convertSel(m, { f: [0] }, "edges");
check("face -> its 4 edges", o.e.length === 4);
o = P.convertSel(m, { v: [f0[0]] }, "faces");
check("vertex -> the faces around it", o.f.length >= 3 && o.f.includes(0));
o = P.convertSel(m, { v: f0 }, "containedFaces");
check("a face's vertices -> exactly that face (contained)", o.f.length === 1 && o.f[0] === 0, o.f);
o = P.convertSel(m, { v: f0 }, "containedEdges");
check("a face's vertices -> its 4 edges (contained)", o.e.length === 4);
const T = P.topology(m), nb = T.faceEdges[0].map((ei) => T.edges[ei].faces.find((fi) => fi !== 0))[0];
o = P.convertSel(m, { f: [0, nb] }, "edgePerimeter");
check("two neighbouring quads -> the 6 edges round them", o.e.length === 6, o.e.length);
o = P.convertSel(m, { f: [0, nb] }, "vertexPerimeter");
check("... -> the 6 vertices round them", o.v.length === 6, o.v.length);
o = P.convertSel(m, { v: [0] }, "shell");
check("one vertex -> the whole connected piece", o.f.length === 24);
const two = P.combine([m, P.transform(P.primitive("cube"), [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, 0, 0, 1])]);
check("To Shell stays on its own piece", P.convertSel(two, { v: [0] }, "shell").f.length === 24);
check("Similar: quads of the same size", P.similarFaces(m, [0]).length === 24 && P.similarFaces(two, [24]).length === 6);
const far = m.v.reduce((best, p, i) => (Math.hypot(...p.map((x, k) => x - m.v[f0[0]][k])) > Math.hypot(...m.v[best].map((x, k) => x - m.v[f0[0]][k])) ? i : best), 0);
const path = P.shortestPath(m, f0[0], far);
check("Shortest Edge Path: a chain of edges from one vertex to the other", path.length >= 3 && path[0][0] === f0[0]
  && path[path.length - 1][1] === far && path.every((e, i) => i === 0 || e[0] === path[i - 1][1]), path);
check("no path between two pieces", P.shortestPath(two, 0, two.v.length - 1).length === 0);
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
