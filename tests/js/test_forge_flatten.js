// Forge's Flatten = scale to 0 (app/ui/forge_polyops.js flatten; owner 2026-10-25: "scale down to flatten verts/faces/
// edges ... scales them all to 0", as Maya / Unreal do), and the Scale handle's snap to 0 (forge_toolkit.js).
//   node tests/js/test_forge_flatten.js        (< 1 s)
"use strict";
const path = require("path"), fs = require("fs");
global.window = global;
require(path.join(__dirname, "../../app/ui/forge_poly.js"));
require(path.join(__dirname, "../../app/ui/forge_polyops.js"));
const P = window.ForgePoly;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d).slice(0, 300))); };
const near = (a, b) => Math.abs(a - b) < 1e-9;

const cube = P.primitive("cube");
const all = cube.v.map((_, i) => i);
const top = all.filter((i) => cube.v[i][1] > 0);
const r = P.flatten(cube, all, { axis: "y" });
const ys = r.m.v.map((p) => p[1]);
check("Flatten Y on the whole cube: every vertex on one plane (Y scaled to 0)", ys.every((y) => near(y, ys[0])), ys);
check("...about the handle (the median): the plane goes through the middle", near(ys[0], P.median(cube, all)[1]), ys[0]);
check("...X and Z untouched", r.m.v.every((p, i) => near(p[0], cube.v[i][0]) && near(p[2], cube.v[i][2])));
check("...same topology, nothing merged or lost", r.m.v.length === cube.v.length && r.m.f.length === cube.f.length);
check("...the input mesh is not changed", cube.v.some((p) => p[1] > 0) && cube.v.some((p) => p[1] < 0));
const x = P.flatten(cube, all, { axis: "x" }).m.v.map((p) => p[0]);
check("Flatten X", x.every((v) => near(v, x[0])), x);
const half = P.flatten(cube, all, { axis: "z", amount: 0.5 }).m.v;
check("Amount 0.5 = scale Z to 0.5", half.every((p, i) => near(p[2], cube.v[i][2] * 0.5 + P.median(cube, all)[2] * 0.5)));
// a bumpy top face flattened along its normal
const bumped = { v: cube.v.map((p, i) => (top.includes(i) && i === top[0] ? [p[0], p[1] + 0.3, p[2]] : p.slice())), f: cube.f.map((f) => f.slice()) };
const n = P.flatten(bumped, top, { axis: "normal" }).m.v;
const [a, b, c, d] = top.map((i) => n[i]);
const sub = (p, q) => [p[0] - q[0], p[1] - q[1], p[2] - q[2]];
const cr = (u, w) => [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]];
const vol = (() => { const k = cr(sub(b, a), sub(c, a)), e = sub(d, a); return Math.abs(k[0] * e[0] + k[1] * e[1] + k[2] * e[2]); })();
check("Flatten Along Normal: a bumpy top face lies on one plane again (across its average normal)", vol < 1e-9, vol);
check("...only the picked vertices move", all.filter((i) => !top.includes(i)).every((i) => near(n[i][1], bumped.v[i][1])));
check("one vertex is not a selection to flatten", !!P.flatten(cube, [0], { axis: "y" }).warn);

// the Scale handle: an axis near 0 sticks at 0 (objects keep a floor so they stay pickable)
const tk = fs.readFileSync(path.join(__dirname, "../../app/ui/forge_toolkit.js"), "utf8");
const src = tk.slice(tk.indexOf("function forgeScaleZeroSnap"), tk.indexOf("function forgeTkRun"));
const snap = new Function(src + "; return forgeScaleZeroSnap;")();
const s1 = { x: 0.03, y: 1, z: -0.02 };
check("handle: X near 0 snaps to 0 when dragging X", snap(s1, "X", 0.06, 0) && s1.x === 0 && s1.z === -0.02, s1);
const s2 = { x: 0.03, y: 0.02, z: 0.04 };
snap(s2, "XYZ", 0.06, 1e-4);
check("handle: uniform scale near 0 on an object = the floor on every axis", s2.x === 1e-4 && s2.y === 1e-4 && s2.z === 1e-4, s2);
const s3 = { x: 0.5, y: 1, z: 1 };
check("handle: far from 0 nothing snaps", !snap(s3, "X", 0.06, 0) && s3.x === 0.5);

console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
