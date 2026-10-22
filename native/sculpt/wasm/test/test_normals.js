// node wasm/test/test_normals.js [sculpt.wasm] - soft / hard corner normals (ks_corner_normals)
const path = require("path");
const SculptEngine = require(path.join(__dirname, "..", "sculpt_engine.js"));
const wasm = process.argv[2] || path.join(__dirname, "..", "..", "build-wasm", "sculpt.wasm");
let fails = 0;
const check = (ok, what) => { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) fails++; };
const near = (a, b) => Math.abs(a - b) < 1e-4;
(async () => {
  const e = await SculptEngine.create(wasm);
  const v = new Float32Array([-1,-1,-1, 1,-1,-1, 1,1,-1, -1,1,-1, -1,-1,1, 1,-1,1, 1,1,1, -1,1,1]);
  const F = [[0,3,2,1],[4,5,6,7],[0,1,5,4],[2,3,7,6],[1,2,6,5],[0,4,7,3]];
  const sizes = new Int32Array(F.map((f) => f.length)), idx = new Int32Array(F.flat());
  const edges = []; F.forEach((f) => f.forEach((a, k) => { const b = f[(k + 1) % 4]; if (a < b) edges.push(a, b); }));
  const hard = e.cornerNormals(v, sizes, idx, new Int32Array(edges));
  check(hard.length === 24 * 3 && near(hard[0], 0) && near(hard[1], 0) && near(Math.abs(hard[2]), 1), "every edge hard: each corner takes its face's normal");
  const soft = e.cornerNormals(v, sizes, idx, new Int32Array(0));
  const s3 = 1 / Math.sqrt(3);
  check(near(Math.abs(soft[0]), s3) && near(Math.abs(soft[1]), s3) && near(Math.abs(soft[2]), s3), "every edge soft: a cube corner points along the diagonal");
  // hard edges 0-1 and 0-3 cut face 0 off at vertex 0 (one hard edge alone would not: the fan stays joined the other
  // way round, as in the pro tool); faces 2 and 5 still share their normal over the soft edge 0-4
  const two = e.cornerNormals(v, sizes, idx, new Int32Array([0, 1, 0, 3]));
  const at = (c) => [two[c * 3], two[c * 3 + 1], two[c * 3 + 2]], same = (a, b) => a.every((x, i) => near(x, b[i]));
  check(same(at(0), [0, 0, -1]) && same(at(8), at(20)) && !same(at(0), at(8)), "two hard edges split a face's corner off; the others still share over the soft edge");
  // speed on a dense cage
  const r = e.cageSubdivide(v, sizes, idx, 7, 200000);
  const tri = r.idx, n = tri.length / 3;
  const t0 = Date.now();
  const big = e.cornerNormals(r.pos, new Int32Array(n).fill(3), new Int32Array(tri), new Int32Array(0));
  const ms = Date.now() - t0;
  check(big.length === n * 9, "dense cage: " + n.toLocaleString() + " triangles in " + ms + " ms");
  console.log(fails ? fails + " FAILED" : "ALL OK");
  process.exit(fails ? 1 : 0);
})();
