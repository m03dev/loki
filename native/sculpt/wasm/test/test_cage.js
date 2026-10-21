// The C++ cage subdivision (ks_cage_subdiv) against Forge's JS ForgePoly.smooth: the same vertices, the same
// triangles, on a cube, an open grid, n-gons, a cylinder with caps, a non-manifold fin and a bad cage; then speed.
//   node native/sculpt/wasm/test/test_cage.js [path/to/sculpt.wasm]      (~2 s)
"use strict";
const path = require("path");
const ROOT = path.resolve(__dirname, "../../../..");
global.window = global;
require(path.join(ROOT, "app/ui/forge_poly.js"));
const P = window.ForgePoly;
const SculptEngine = require(path.join(__dirname, "../sculpt_engine.js"));
const wasm = process.argv[2] || path.join(ROOT, "app/ui/vendor/sculpt/sculpt.wasm");
let pass = 0, fail = 0;
const check = (name, ok, detail) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + name + (ok ? "" : "  <- " + detail)); };

function flat(m) {
  const v = new Float32Array(m.v.length * 3); m.v.forEach((p, i) => v.set(p, i * 3));
  return { v, sizes: Int32Array.from(m.f.map((f) => f.length)), idx: Int32Array.from(m.f.flat()) };
}
function jsPreview(m, levels, max) {
  for (let k = 0; k < levels && m.f.length * 4 <= max; k++) m = P.smooth(m);
  return P.triangulate(m);
}
function same(E, name, m, levels = 2, max = 60000) {
  // the JS runs on doubles from the cage; the engine gets the cage as float32, so round the cage first for both
  const r = { v: m.v.map((p) => [Math.fround(p[0]), Math.fround(p[1]), Math.fround(p[2])]), f: m.f };
  const j = jsPreview(r, levels, max), F = flat(r), c = E.cageSubdivide(F.v, F.sizes, F.idx, levels, max);
  let dmax = 0;
  for (let i = 0; i < j.pos.length; i++) dmax = Math.max(dmax, Math.abs(j.pos[i] - c.pos[i]));
  const triSame = j.idx.length === c.idx.length && j.idx.every((x, i) => x === c.idx[i]);
  check(name + ": same " + (j.pos.length / 3) + " vertices and " + (j.idx.length / 3) + " triangles as the JS",
    j.pos.length === c.pos.length && triSame && dmax < 1e-6, JSON.stringify({ jv: j.pos.length, cv: c.pos.length, triSame, dmax }));
}
function grid(n) {
  const v = [], f = [];
  for (let j = 0; j <= n; j++) for (let i = 0; i <= n; i++) v.push([i / n, j / n, Math.sin(i * 0.3) * 0.05]);
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) { const a = j * (n + 1) + i; f.push([a, a + 1, a + n + 2, a + n + 1]); }
  return { v, f };
}
const cube = { v: [[-.5, -.5, -.5], [.5, -.5, -.5], [.5, .5, -.5], [-.5, .5, -.5], [-.5, -.5, .5], [.5, -.5, .5], [.5, .5, .5], [-.5, .5, .5]],
  f: [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [2, 3, 7, 6], [1, 2, 6, 5], [0, 4, 7, 3]] };
function cylinder(n) {   // n-gon caps + quads
  const v = [], f = [];
  for (let i = 0; i < n; i++) { const a = (i / n) * Math.PI * 2; v.push([Math.cos(a), -1, Math.sin(a)], [Math.cos(a), 1, Math.sin(a)]); }
  for (let i = 0; i < n; i++) { const j = (i + 1) % n; f.push([2 * i, 2 * j, 2 * j + 1, 2 * i + 1]); }
  f.push([...Array(n).keys()].map((i) => 2 * i).reverse(), [...Array(n).keys()].map((i) => 2 * i + 1));
  return { v, f };
}
const fin = { v: [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0.5, 2, 0.5]],   // three faces on one edge
  f: [[0, 1, 2, 3], [1, 0, 4, 5], [0, 1, 6]] };

SculptEngine.create(wasm).then((E) => {
  same(E, "cube", cube);
  same(E, "cube, 3 levels", cube, 3);
  same(E, "open 12x12 grid (boundary crease, corners stay)", grid(12));
  same(E, "cylinder with 9-gon caps", cylinder(9));
  same(E, "a triangle fan + quads", { v: [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0.5, 0.5, 1]], f: [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4], [3, 2, 1, 0]] });
  same(E, "non-manifold fin (an edge on three faces)", fin);
  same(E, "the face limit stops a step (max 100 faces)", grid(8), 2, 100);
  let bad = false; try { E.cageSubdivide(new Float32Array([0, 0, 0]), Int32Array.of(3), Int32Array.of(0, 1, 2)); } catch (_) { bad = true; }
  check("a cage pointing at a missing vertex is refused", bad, "no error");
  // speed: a 25 600-face cage, two levels (the JS takes about half a second)
  const g = grid(160), F = flat(g);
  let t = performance.now(); jsPreview(g, 2, 1e9); const tj = performance.now() - t;
  t = performance.now(); const c = E.cageSubdivide(F.v, F.sizes, F.idx, 2, 1e9); const tc = performance.now() - t;
  console.log("  speed: 25 600-face cage, 2 levels -> " + c.faces + " faces: JS " + tj.toFixed(0) + " ms, C++ " + tc.toFixed(0) + " ms (" + (tj / tc).toFixed(1) + "x)");
  check("the C++ preview is faster than the JS one on a big cage", tc < tj, tj + " vs " + tc);
  console.log("\n" + pass + " passed, " + fail + " failed");
  process.exit(fail ? 1 : 0);
});
