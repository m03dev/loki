// Mesh Display > Conform (forge_polyops.js P.conformNormals)    node tests/js/test_forge_conform.js
"use strict";
global.window = global;
require("../../app/ui/forge_poly.js");
require("../../app/ui/forge_polyops.js");
const P = window.ForgePoly;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + String(JSON.stringify(d)).slice(0, 300))); };
const cube = P.primitive("cube"), vol0 = P.volume(cube);
const rev = (m, ids) => ({ v: m.v, f: m.f.map((f, i) => (ids.includes(i) ? f.slice().reverse() : f.slice())) });
// consistent: every inside edge is run both ways
const consistent = (m) => { const T = P.topology(m); return T.edges.every((e) => { if (e.faces.length !== 2) return true;
  const d = (f) => { for (let k = 0; k < f.length; k++) { if (f[k] === e.a && f[(k + 1) % f.length] === e.b) return 1; if (f[k] === e.b && f[(k + 1) % f.length] === e.a) return -1; } return 0; };
  return d(m.f[e.faces[0]]) === -d(m.f[e.faces[1]]); }); };
let r = P.conformNormals(rev(cube, [1, 4]), null);
check("two faces of six turned in: they turn back (the four win), the cube faces out again", consistent(r.m) && Math.abs(P.volume(r.m) - vol0) < 1e-9, P.volume(r.m));
r = P.conformNormals(rev(cube, [0, 1, 2, 3, 4]), null);
check("five of six turned in: the five win - the last one turns in too (all consistent, inside out)", consistent(r.m) && P.volume(r.m) < 0);
r = P.conformNormals(rev(cube, [0, 2, 4]), null);
check("three and three: a tie on a closed piece goes outward", consistent(r.m) && P.volume(r.m) > 0, P.volume(r.m));
r = P.conformNormals(cube, null);
check("an already consistent cube: nothing changes", JSON.stringify(r.m.f) === JSON.stringify(cube.f));
const bad = rev(cube, [1, 4]);
r = P.conformNormals(bad, [1]);
check("only the picked face may flip: face 1 turns back, face 4 stays turned in", JSON.stringify(r.m.f[1]) === JSON.stringify(cube.f[1]) && JSON.stringify(r.m.f[4]) === JSON.stringify(bad.f[4]));
const two = P.combine([rev(cube, [2]), P.transform(rev(cube, [0, 1, 2, 3, 4, 5]), [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, 0, 0, 1])]);
r = P.conformNormals(two, null);
check("two pieces are conformed each on its own (the second, all turned in, stays as it is)", consistent(r.m)
  && JSON.stringify(r.m.f.slice(6)) === JSON.stringify(two.f.slice(6)) && JSON.stringify(r.m.f[2]) === JSON.stringify(cube.f[2]));
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
