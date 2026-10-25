// P.topology speed (task "speed up commit after a move on 50k+ face meshes"): a number edge key instead of the
// "a,b" string, and a moved copy of a cage (same faces) reuses the topology instead of rebuilding it.
//   node tests/js/test_forge_topology_speed.js
"use strict";
global.window = global;
require("../../app/ui/forge_poly.js");
require("../../app/ui/forge_polyops.js");
const P = window.ForgePoly;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d))); };
let m = P.primitive("cube");
for (let i = 0; i < 7; i++) m = P.addDivisions(m, m.f.map((_, k) => k), { divisions: 1 }).m;   // 98,304 quads
let t = Date.now(); const T1 = P.topology(m); const fresh = Date.now() - t;
check("a fresh topology of " + m.f.length + " faces is quick (" + fresh + " ms)", fresh < 1500, fresh);
const moved = P.clone(m); moved.v[0] = [moved.v[0][0], moved.v[0][1] + 0.1, moved.v[0][2]];
t = Date.now(); const T2 = P.topology(moved); const again = Date.now() - t;
check("a moved copy (same faces) reuses it (" + again + " ms)", T2 === T1 && again < fresh / 3, [again, fresh]);
const other = P.clone(m); other.f[0] = other.f[0].slice().reverse();
check("a copy with a changed face does NOT reuse it", P.topology(other) !== T1);
const e = T1.edges[100];
check("edge(a, b) finds edges either way round", T1.edge(e.a, e.b) === 100 && T1.edge(e.b, e.a) === 100 && T1.edge(0, m.v.length + 5) === undefined);
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
