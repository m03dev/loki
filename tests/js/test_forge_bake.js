// The baker (app/ui/forge_bake.js forgeBakeJob) in node: a low cube with UVs and a high sphere-ish blob inside it,
// and a flat high = a flat normal map; every map comes out, padding fills the gaps, misses are counted.
//   node tests/js/test_forge_bake.js   (< 10 s)
"use strict";
const path = require("path");
global.window = global; global.localStorage = { getItem: () => null, setItem: () => {} }; global.performance = global.performance || require("perf_hooks").performance;
global.document = { querySelector: () => null, getElementById: () => null, createElement: () => ({}) };
global.setInterval = () => 0;
require(path.join(__dirname, "../../app/ui/forge_poly.js"));
require(path.join(__dirname, "../../app/ui/forge_uv.js"));
const vm = require("vm"), fs = require("fs");
vm.runInThisContext(fs.readFileSync(path.join(__dirname, "../../app/ui/forge_retopo.js"), "utf8"));
vm.runInThisContext(fs.readFileSync(path.join(__dirname, "../../app/ui/forge_bake.js"), "utf8"));
const P = window.ForgePoly, U = window.ForgeUV;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d).slice(0, 300))); };
function lowOf(m) { const pos = new Float32Array(m.v.length * 3); m.v.forEach((p, i) => pos.set(p, i * 3)); return { pos, f: m.f, fuv: m.fuv, uv: m.uv }; }
function highOf(m) { const t = P.triangulate(m); return { pos: t.pos, idx: t.idx, nrm: null }; }
function run(job) { let n = 0; while (!job.done && n++ < 100000) job.step(50); return job.result(); }
// 1. a plane over a plane: the tangent normal map is flat (0.5, 0.5, 1)
const plane = U.planar(P.primitive("plane"), [], "y");
const hiPlane = P.transform(P.primitive("plane"), { translate: [0, -0.01, 0] }) || P.primitive("plane");
const r1 = run(forgeBakeJob(lowOf(plane), highOf(hiPlane), { res: 64, aa: 1, pad: 2, size: 1, maps: { normal: true, ao: true, curvature: true, height: true, thickness: true, position: true, normalObj: true } }));
const nm = r1.maps.normal; let flat = 0, cov = 0;
for (let i = 0; i < 64 * 64; i++) if (nm[i * 4 + 3]) { cov++; if (Math.abs(nm[i * 4] - 0.5) < 0.02 && Math.abs(nm[i * 4 + 1] - 0.5) < 0.02 && nm[i * 4 + 2] > 0.98) flat++; }
check("flat high under a flat low: the tangent normal map is flat blue (0.5, 0.5, 1)", cov > 3000 && flat / cov > 0.98, [cov, flat]);
check("all seven maps come out at the asked size", Object.keys(r1.maps).length === 7 && r1.maps.ao.length === 64 * 64 * 4, Object.keys(r1.maps));
const ao = r1.maps.ao; let open = 0; for (let i = 0; i < 64 * 64; i++) if (ao[i * 4 + 3] && ao[i * 4] > 0.95) open++;
check("AO on an open flat plane is (nearly) all white", open / cov > 0.9, open / cov);
// 2. a cube low over a smoothed cube high: the normal map is not flat (the high's rounded shape shows), few misses
const cube = U.layoutBasic(U.automatic(P.primitive("cube"), [], 6), [], { paddingPx: 4, resolution: 128 });
let hi = P.primitive("cube"); hi = P.smooth(P.smooth(hi));
const t0 = Date.now();
const r2 = run(forgeBakeJob(lowOf(cube), highOf(hi), { res: 128, aa: 1, pad: 4, size: 1, cage: 0.05, maxDist: 0.6, maps: { normal: true, curvature: true } }));
const ms = Date.now() - t0;
let bent = 0, cov2 = 0; const n2 = r2.maps.normal;
for (let i = 0; i < 128 * 128; i++) if (n2[i * 4 + 3]) { cov2++; if (Math.abs(n2[i * 4] - 0.5) > 0.05 || Math.abs(n2[i * 4 + 1] - 0.5) > 0.05) bent++; }
check("cube low over a smoothed-cube high: the normal map shows the rounded high (many texels tilted), the rays hit", bent > cov2 * 0.3 && r2.misses < r2.coverage * 0.02, [bent, cov2, r2.misses, r2.coverage]);
check("padding fills texels around the islands (more texels set than the rays covered)", cov2 > r2.coverage, [cov2, r2.coverage]);
console.log("  (cube bake 128 px with curvature: " + ms + " ms)");
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
