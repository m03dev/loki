// Edit Edge Flow (forge_polyops.js P.editEdgeFlow; Maya polyEditEdgeFlow)    node tests/js/test_forge_edgeflow.js
"use strict";
global.window = global;
require("../../app/ui/forge_poly.js");
require("../../app/ui/forge_polyops.js");
const P = window.ForgePoly;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + String(JSON.stringify(d)).slice(0, 300))); };
// a sheet curved like y = x^2 across x = -2..2, 5 rows deep in z; the middle column (x = 0) dented down to -0.5
const sheet = (dent, curve) => {
  const m = { v: [], f: [] }, I = (x, z) => z * 5 + x;
  for (let z = 0; z < 5; z++) for (let x = 0; x < 5; x++) { const X = x - 2; m.v.push([X, x === 2 ? dent : curve ? X * X : 0, z]); }
  for (let z = 0; z < 4; z++) for (let x = 0; x < 4; x++) m.f.push([I(x, z), I(x + 1, z), I(x + 1, z + 1), I(x, z + 1)]);
  return { m, I };
};
let { m, I } = sheet(-0.5, true);
const col = []; for (let z = 0; z < 4; z++) col.push([I(2, z), I(2, z + 1)]);
let r = P.editEdgeFlow(m, col, { adjust: 1 });
const ys = [1, 2, 3].map((z) => +r.m.v[I(2, z)][1].toFixed(6));
check("the dented loop goes back onto the curve (y = 0 where x = 0) where it has two rows each side", !r.warn && ys.every((y) => Math.abs(y) < 1e-6), [r.warn, ys]);
check("... x and z stay (it moves in the curve's own direction only)", [1, 2, 3].every((z) => Math.abs(r.m.v[I(2, z)][0]) < 1e-9 && Math.abs(r.m.v[I(2, z)][2] - z) < 1e-9));
check("... the border ends of the loop (only one row beyond) stay", r.m.v[I(2, 0)][1] === -0.5 && r.m.v[I(2, 4)][1] === -0.5);
check("... no other vertex moves", r.m.v.every((p, i) => (i % 5 === 2) || JSON.stringify(p) === JSON.stringify(m.v[i])));
r = P.editEdgeFlow(m, col, { adjust: 0.5 });
check("Adjust 0.5: half way (-0.25)", Math.abs(r.m.v[I(2, 2)][1] + 0.25) < 1e-6, r.m.v[I(2, 2)]);
({ m, I } = sheet(0, false));
r = P.editEdgeFlow(m, col, {});
check("a flat sheet: nothing moves", r.m.v.every((p, i) => p.every((x, k) => Math.abs(x - m.v[i][k]) < 1e-9)));
r = P.editEdgeFlow(m, [[I(2, 2), I(2, 3)]], {});
check("one edge picked: its two vertices are fitted (the loop's direction comes from the mesh)", !r.warn);
check("a cube's edge (poles at the ends, one row each side): it says what it needs", !!P.editEdgeFlow(P.primitive("cube"), [[0, 1]], {}).warn);
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
