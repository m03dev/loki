// ForgePoly.fixTJunctions (forge_poly.js): a vertex inside another face's border edge is put into that edge, so the
// two sides share edges and the seam closes (the open booleans' Split Edges needs it).   node tests/js/test_forge_tjunction.js
"use strict";
global.window = global;
require("../../app/ui/forge_poly.js");
const P = window.ForgePoly;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + String(JSON.stringify(d)).slice(0, 300))); };
const open = (m) => P.topology(m).edges.filter((e) => e.faces.length === 1).length;
// one quad on the left, two on the right: (1, 0.5) sits in the middle of the left quad's right edge
const m = { v: [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [2, 0, 0], [2, 0.5, 0], [1, 0.5, 0], [2, 1, 0]],
  f: [[0, 1, 2, 3], [1, 4, 5, 6], [6, 5, 7, 2]] };
check("(before: the seam is 3 open edges more than the outline's 7)", open(m) === 10, open(m));
const out = P.fixTJunctions(m, 1e-6);
check("after: only the outline is open (7 edges)", open(out) === 7, open(out));
check("the left quad took the middle vertex into its right edge (5 corners, in order)", out.f[0].join() === "0,1,6,2,3", out.f[0]);
check("nothing else changed", out.f[1].join() === "1,4,5,6" && out.f[2].join() === "6,5,7,2" && out.v.length === 8);
check("a mesh with no T-junction comes back the same", JSON.stringify(P.fixTJunctions(P.primitive("cube"), 1e-6).f) === JSON.stringify(P.primitive("cube").f));
check("the input is not changed", m.f[0].length === 4);
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
