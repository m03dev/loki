// UV > Split UVs / Merge UVs / Delete UVs (app/ui/forge_uv.js splitUVs / mergeUVs / deleteUVs)
//   node tests/js/test_forge_uvpoints.js
"use strict";
const path = require("path");
global.window = global;
require(path.join(__dirname, "../../app/ui/forge_poly.js"));
require(path.join(__dirname, "../../app/ui/forge_uv.js"));
const P = window.ForgePoly, U = window.ForgeUV;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + String(JSON.stringify(d)).slice(0, 300))); };
// a 2 x 1 strip of quads, planar along Z: the two faces share the middle edge's two UV points
const strip = { v: [[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0]], f: [[0, 1, 4, 3], [1, 2, 5, 4]] };
const m = U.planar(strip, [], "z");
const shared = m.fuv[0].filter((i) => m.fuv[1].includes(i));
check("(two quads share two UV points)", U.has(m) && shared.length === 2, m.fuv);
let s = U.splitUVs(m, shared);
check("Split UVs on the shared points: two more points, the faces share none now", s.uv.length === m.uv.length + 2 && !s.fuv[0].some((i) => s.fuv[1].includes(i)));
check("... nothing moved in UV space (the new points sit where the old ones were)", s.fuv[1].every((i, k) => JSON.stringify(s.uv[i]) === JSON.stringify(m.uv[m.fuv[1][k]])));
check("... and it is still one valid UV set", U.has(s));
const back = U.mergeUVs(s, s.uv.map((_, i) => i), 0.001);
check("Merge UVs (all picked, 0.001): back to the shared points, the same count as before the split", back.uv.length === m.uv.length && U.has(back), back.uv.length);
// two points apart: move one copy a little, merge with a distance that reaches it, they meet at the middle
const moved = U.splitUVs(m, shared);
const copy = moved.fuv[1].find((i) => !m.fuv[1].includes(i));
moved.uv[copy] = [moved.uv[copy][0] + 0.004, moved.uv[copy][1]];
let mg = U.mergeUVs(moved, moved.uv.map((_, i) => i), 0.002);
check("points 0.004 apart stay apart with a merge distance of 0.002", mg.uv.length === moved.uv.length - 1, [mg.uv.length, moved.uv.length]);
mg = U.mergeUVs(moved, moved.uv.map((_, i) => i), 0.01);
check("... and merge with 0.01 (Maya's default)", mg.uv.length === m.uv.length);
check("only the picked points merge", U.mergeUVs(s, [shared[0]], 1).uv.length === s.uv.length);
const d = U.deleteUVs(m);
check("Delete UVs: the mesh has none left, its shape is the same", !U.has(d) && d.v.length === m.v.length && d.f.length === m.f.length);
check("the inputs are never changed", m.uv.length === 6 && U.has(m));
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
