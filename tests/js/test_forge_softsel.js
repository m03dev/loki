// Soft selection Falloff Mode (app/ui/forge_poly.js weights / weightsSurface): Volume = straight-line distance,
// Surface = distance along the mesh's edges (Maya's Falloff mode; Blockbench / Wings "connected"), so a fold of the
// mesh that is close in space but far along the surface does not follow.   node tests/js/test_forge_softsel.js (< 1 s)
"use strict";
const path = require("path");
global.window = global;
require(path.join(__dirname, "../../app/ui/forge_poly.js"));
const P = window.ForgePoly;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d).slice(0, 300))); };

// a hairpin strip: out along x, then back 0.1 away - the two ends are 0.1 apart in space, 2.1 along the surface
const path0 = [[0, 0, 0], [1, 0, 0], [1, 0, 0.1], [0, 0, 0.1]];
const v = [], f = [];
for (const [x, , z] of path0) { v.push([x, 0, z], [x, 1, z]); }
for (let i = 0; i + 1 < path0.length; i++) f.push([2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1]);
const m = { v, f };
const sel = [0, 1];                                   // the first end
const vol = P.weights(m, sel, 0.5, "linear"), sur = P.weightsSurface(m, sel, 0.5, "linear");
check("Volume: the other end of the fold (0.1 away in space) follows", vol.has(6) && vol.has(7), [...vol.keys()]);
check("Surface: it does not (2.1 away along the mesh)", !sur.has(6) && !sur.has(7), [...sur.keys()]);
check("both keep the picked vertices at full weight", vol.get(0) === 1 && sur.get(0) === 1 && sur.get(1) === 1);
const far = P.weightsSurface(m, sel, 2.5, "linear");
check("Surface with a big radius reaches along the strip, fading with distance", far.has(6) && far.get(6) < far.get(2) && far.get(2) < 1, [...far]);
check("radius 0 = only the picked vertices", P.weightsSurface(m, sel, 0, "linear").size === 2);
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
