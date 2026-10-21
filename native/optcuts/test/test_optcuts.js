/* OptCuts (app/ui/vendor/optcuts/optcuts.wasm) in node: valid UV layouts on a closed sphere, an open cylinder and a
 * torus; bijectivity; the distortion bound; the seams cut the mesh into disks; determinism; the step API; bad input
 * refused; the worker protocol; timings at ~2k and ~10k triangles (with a time budget). Well under 40 s.
 *
 *   node native/optcuts/test/test_optcuts.js
 */
"use strict";
const path = require("path");
const fs = require("fs");
const vm = require("vm");
const REPO = path.resolve(__dirname, "..", "..", "..");
const VENDOR = path.join(REPO, "app", "ui", "vendor", "optcuts");
const OptCutsEngine = require(path.join(VENDOR, "optcuts_engine.js"));
const M = require("./meshes.js");

let pass = 0, fail = 0;
function check(name, ok, detail) {
  if (ok) pass++; else fail++;
  console.log((ok ? "  PASS " : "  FAIL ") + name + (ok ? "" : "  <- " + String(detail === undefined ? "" : detail).slice(0, 300)));
}
const T0 = Date.now();

// ---------------------------------------------------------------- layout checks
function signedArea(uv, c, t) {
  const a = c[3 * t], b = c[3 * t + 1], d = c[3 * t + 2];
  return 0.5 * ((uv[2 * b] - uv[2 * a]) * (uv[2 * d + 1] - uv[2 * a + 1]) - (uv[2 * b + 1] - uv[2 * a + 1]) * (uv[2 * d] - uv[2 * a]));
}
// Symmetric Dirichlet energy, area-weighted, exactly as OptCuts measures it (4 = isometric)
function symDirichlet(pos, tris, uv, c) {
  let E = 0, A = 0;
  for (let t = 0; t < tris.length / 3; t++) {
    const p = [0, 1, 2].map((k) => [pos[3 * tris[3 * t + k]], pos[3 * tris[3 * t + k] + 1], pos[3 * tris[3 * t + k] + 2]]);
    const e1 = [p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2]], e2 = [p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2]];
    const l1 = Math.hypot(...e1), cr = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
    const area = 0.5 * Math.hypot(...cr);
    // rest triangle in 2D: x0 = (0,0), x1 = (l1, 0), x2 = (e2.e1/l1, 2*area/l1)
    const x1 = [l1, 0], x2 = [(e2[0] * e1[0] + e2[1] * e1[1] + e2[2] * e1[2]) / l1, (2 * area) / l1];
    const u0 = [uv[2 * c[3 * t]], uv[2 * c[3 * t] + 1]], u1 = [uv[2 * c[3 * t + 1]], uv[2 * c[3 * t + 1] + 1]], u2 = [uv[2 * c[3 * t + 2]], uv[2 * c[3 * t + 2] + 1]];
    const U = [[u1[0] - u0[0], u2[0] - u0[0]], [u1[1] - u0[1], u2[1] - u0[1]]];
    const det = x1[0] * x2[1] - x1[1] * x2[0];
    const Xi = [[x2[1] / det, -x2[0] / det], [-x1[1] / det, x1[0] / det]];
    const J = [[U[0][0] * Xi[0][0] + U[0][1] * Xi[1][0], U[0][0] * Xi[0][1] + U[0][1] * Xi[1][1]],
               [U[1][0] * Xi[0][0] + U[1][1] * Xi[1][0], U[1][0] * Xi[0][1] + U[1][1] * Xi[1][1]]];
    const f2 = J[0][0] ** 2 + J[0][1] ** 2 + J[1][0] ** 2 + J[1][1] ** 2, dj = J[0][0] * J[1][1] - J[0][1] * J[1][0];
    E += area * (f2 + f2 / (dj * dj)); A += area;
  }
  return E / A;
}
// charts = connected components of triangles glued through shared UV vertices; each must be a disk
// (connected, one boundary loop, Euler characteristic 1 on the cut mesh)
function charts(tris, c, nuv) {
  const nt = tris.length / 3, parent = Int32Array.from({ length: nt }, (_, i) => i);
  const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  const byUV = new Map();
  for (let t = 0; t < nt; t++) for (let k = 0; k < 3; k++) {
    const u = c[3 * t + k]; if (byUV.has(u)) { const a = find(byUV.get(u)), b = find(t); if (a !== b) parent[a] = b; } else byUV.set(u, t);
  }
  const comp = new Map();
  for (let t = 0; t < nt; t++) { const r = find(t); if (!comp.has(r)) comp.set(r, []); comp.get(r).push(t); }
  const out = [];
  for (const ts of comp.values()) {
    const verts = new Set(), edges = new Map();
    for (const t of ts) for (let k = 0; k < 3; k++) {
      const a = c[3 * t + k], b = c[3 * t + (k + 1) % 3]; verts.add(a);
      const key = a < b ? a + "," + b : b + "," + a; edges.set(key, (edges.get(key) || 0) + 1);
    }
    let boundary = 0; const bverts = new Map();
    for (const [key, n] of edges) if (n === 1) { boundary++; for (const v of key.split(",")) bverts.set(v, (bverts.get(v) || 0) + 1); }
    // count boundary loops by walking boundary edges as a graph (vertices of degree 2 on a simple disk boundary)
    const adj = new Map();
    for (const [key, n] of edges) if (n === 1) { const [a, b] = key.split(","); (adj.get(a) || adj.set(a, []).get(a)).push(b); (adj.get(b) || adj.set(b, []).get(b)).push(a); }
    const seen = new Set(); let loops = 0;
    for (const v of adj.keys()) if (!seen.has(v)) { loops++; const st = [v]; seen.add(v); while (st.length) { const x = st.pop(); for (const y of adj.get(x)) if (!seen.has(y)) { seen.add(y); st.push(y); } } }
    out.push({ tris: ts.length, chi: verts.size - edges.size + ts.length, loops, nonManifoldBoundary: [...bverts.values()].some((d) => d !== 2) });
  }
  return out;
}

function validate(name, m, r, opts) {
  const nt = m.tris.length / 3, nuv = r.uv.length / 2;
  check(name + ": every corner has a UV (" + nt + " triangles, " + nuv + " UVs)",
    r.cornerUV.length === nt * 3 && r.cornerUV.every((u) => u >= 0 && u < nuv) && r.uv.every(Number.isFinite));
  // a UV vertex belongs to one 3D vertex
  const owner = new Int32Array(nuv).fill(-1); let ownerOk = true;
  for (let i = 0; i < nt * 3; i++) { const u = r.cornerUV[i]; if (owner[u] < 0) owner[u] = m.tris[i]; else if (owner[u] !== m.tris[i]) ownerOk = false; }
  check(name + ": each UV vertex maps back to one mesh vertex", ownerOk);
  let flipped = 0; for (let t = 0; t < nt; t++) if (!(signedArea(r.uv, r.cornerUV, t) > 0)) flipped++;
  if (opts.useBijectivity !== 0) check(name + ": 0 flipped triangles (bijectivity on)", flipped === 0 && r.flipped === 0, flipped);
  const sd = symDirichlet(m.pos, m.tris, r.uv, r.cornerUV);
  check(name + ": distortion " + sd.toFixed(4) + " <= bound " + (opts.distortionBound || 4.1) + " (+0.01), matches the engine's " + r.distortion.toFixed(4),
    sd <= (opts.distortionBound || 4.1) + 0.01 && Math.abs(sd - r.distortion) < 1e-3 * sd, sd + " vs " + r.distortion);
  const ch = charts(m.tris, r.cornerUV, nuv);
  check(name + ": the seams cut it into " + ch.length + " disk(s)", ch.every((c) => c.chi === 1 && c.loops === 1 && !c.nonManifoldBoundary), JSON.stringify(ch.slice(0, 4)));
  // seams = exactly the mesh edges whose two sides got different UVs
  const edgeFaces = new Map();
  for (let t = 0; t < nt; t++) for (let k = 0; k < 3; k++) {
    const a = m.tris[3 * t + k], b = m.tris[3 * t + (k + 1) % 3], key = Math.min(a, b) + "," + Math.max(a, b);
    (edgeFaces.get(key) || edgeFaces.set(key, []).get(key)).push([t, k]);
  }
  const uvOf = (t, v) => { for (let k = 0; k < 3; k++) if (m.tris[3 * t + k] === v) return r.cornerUV[3 * t + k]; return -1; };
  const split = new Set();
  for (const [key, fs2] of edgeFaces) if (fs2.length === 2) {
    const [a, b] = key.split(",").map(Number), t0 = fs2[0][0], t1 = fs2[1][0];
    if (uvOf(t0, a) !== uvOf(t1, a) || uvOf(t0, b) !== uvOf(t1, b)) split.add(key);
  }
  const given = new Set(); for (let i = 0; i < r.seams.length; i += 2) given.add(Math.min(r.seams[i], r.seams[i + 1]) + "," + Math.max(r.seams[i], r.seams[i + 1]));
  check(name + ": " + given.size + " seam edges, exactly the edges split in UV", given.size === split.size && [...split].every((k) => given.has(k)), given.size + " vs " + split.size);
  return { sd, charts: ch.length, flipped };
}

function same(a, b) {
  return a.uv.length === b.uv.length && a.uv.every((v, i) => v === b.uv[i]) && a.cornerUV.every((v, i) => v === b.cornerUV[i]) &&
    a.seams.length === b.seams.length && a.seams.every((v, i) => v === b.seams[i]) && a.distortion === b.distortion;
}

(async () => {
  const wasmPath = path.join(VENDOR, "optcuts.wasm");
  check("optcuts.wasm is built (" + (fs.existsSync(wasmPath) ? Math.round(fs.statSync(wasmPath).size / 1024) + " KB" : "missing") + ")", fs.existsSync(wasmPath));
  const eng = await OptCutsEngine.create(wasmPath);

  // 1. closed sphere (genus 0): OptCuts' one-point initial cut, bijective
  const sph = M.icosphere(2);
  let t = Date.now();
  let progress = 0;
  const rS = eng.unwrap(sph.pos, sph.tris, { seed: 0 }, () => progress++, 200);
  const msS = Date.now() - t;
  check("icosphere (" + sph.tris.length / 3 + " tris) converged in " + msS + " ms, " + rS.iterations + " iterations, " + rS.topologyOps + " topology steps", rS.ok && rS.converged);
  validate("icosphere", sph, rS, {});
  check("progress came between slices (" + progress + "x)", progress > 0);

  // 2. determinism: same input and seed -> identical result (the seed picks where the one-point cut of a closed
  //    genus-0 mesh starts; 0 = OptCuts' own choice)
  const rS2 = eng.unwrap(sph.pos, sph.tris, { seed: 0 });
  check("same seed, same result (bit for bit)", same(rS, rS2));

  // 3. open cylinder (two boundary loops -> cut_to_disk) and torus (genus 1)
  const cyl = M.cylinder(24, 10);
  t = Date.now(); const rC = eng.unwrap(cyl.pos, cyl.tris, {});
  check("cylinder (" + cyl.tris.length / 3 + " tris) converged in " + (Date.now() - t) + " ms", rC.converged);
  validate("cylinder", cyl, rC, {});
  const tor = M.torus(24, 12);
  t = Date.now(); const rT = eng.unwrap(tor.pos, tor.tris, {});
  check("torus (" + tor.tris.length / 3 + " tris) converged in " + (Date.now() - t) + " ms", rT.converged);
  validate("torus", tor, rT, {});

  // 4. options: a looser bound gives fewer/shorter seams; bijectivity off; farthest-point cut; seams from input
  const rL = eng.unwrap(tor.pos, tor.tris, { distortionBound: 4.6 });
  validate("torus, bound 4.6", tor, rL, { distortionBound: 4.6 });
  check("a looser bound gives shorter seams (" + rL.seamLength.toFixed(2) + " < " + rT.seamLength.toFixed(2) + ")", rL.seamLength < rT.seamLength);
  const rN = eng.unwrap(cyl.pos, cyl.tris, { useBijectivity: 0 });
  validate("cylinder, bijectivity off", cyl, rN, { useBijectivity: 0 });
  // initial seams from the caller: the cylinder cut open along one vertical line
  const line = []; for (let j = 0; j < 10; j++) line.push(j * 24, (j + 1) * 24);
  const rI = eng.unwrap(cyl.pos, cyl.tris, { initialCutOption: 1, seams: line });
  validate("cylinder, initial seams from input", cyl, rI, {});

  // 5. step API by hand + a budget stop still returns a valid map
  eng.begin(tor.pos, tor.tris, { maxIterations: 5 });
  let steps = 0; while (!eng.step(1, 0)) steps++;
  const rB = eng.result();
  check("maxIterations 5 stops after " + rB.iterations + " Newton steps (" + steps + " step calls), converged=false", rB.iterations <= 5 && !rB.converged);
  check("the budget-stopped map is still valid: every corner has a UV, 0 flipped", rB.cornerUV.every((u) => u >= 0) && rB.flipped === 0);

  // 6. bad input refused (and the engine stays usable)
  const bad = [
    ["no triangles", sph.pos, new Int32Array(0)],
    ["index out of range", sph.pos, Int32Array.from([0, 1, 99999])],
    ["degenerate triangle", Float32Array.from([0, 0, 0, 1, 0, 0, 2, 0, 0, 0, 1, 0]), Int32Array.from([0, 1, 2, 0, 1, 3])],
    ["NaN position", Float32Array.from([NaN, 0, 0, 1, 0, 0, 0, 1, 0]), Int32Array.from([0, 1, 2])],
    ["repeated vertex", Float32Array.from([0, 0, 0, 1, 0, 0, 0, 1, 0]), Int32Array.from([0, 1, 1])],
    ["non-manifold edge", Float32Array.from([0, 0, 0, 1, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 1]), Int32Array.from([0, 1, 2, 1, 0, 3, 0, 1, 4])],
    ["inconsistent orientation", Float32Array.from([0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0]), Int32Array.from([0, 1, 2, 1, 2, 3])],
    ["bound <= 4", sph.pos, sph.tris, { distortionBound: 4 }],
  ];
  for (const [name, p, tr, o] of bad) {
    let err = "";
    try { eng.unwrap(p, tr, o || {}); } catch (e) { err = e.message; }
    check("refused: " + name + (err ? " (" + err + ")" : ""), !!err);
  }
  const rAfter = eng.unwrap(cyl.pos, cyl.tris, {});
  check("the engine still works after refusals", rAfter.converged && same(rAfter, rC));

  // 7. the worker protocol, run in a vm sandbox with this engine (importScripts / postMessage stubs)
  const posted = [];
  const sandbox = { console, setTimeout, performance, TextDecoder, WebAssembly, URL, BigInt, Math, Date, Promise,
    postMessage: (m) => posted.push(m),
    importScripts: (u) => vm.runInContext(fs.readFileSync(path.join(VENDOR, path.basename(u)), "utf8"), sandbox),
    fetch: async (u) => ({ arrayBuffer: async () => fs.readFileSync(path.join(VENDOR, path.basename(u))) }) };
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(VENDOR, "optcuts_worker.js"), "utf8"), sandbox);
  const waitFor = async (pred, ms = 15000) => { const end = Date.now() + ms; while (!pred()) { if (Date.now() > end) return false; await new Promise((r) => setTimeout(r, 5)); } return true; };
  check("worker: ready", await waitFor(() => posted.some((m) => m.t === "ready")), JSON.stringify(posted));
  sandbox.onmessage({ data: { t: "optcuts", seq: 7, pos: tor.pos, tris: tor.tris, opts: { sliceMs: 20 } } });
  sandbox.onmessage({ data: { t: "optcuts", seq: 8, pos: sph.pos, tris: Int32Array.from([0, 1, 99999]), opts: {} } });
  await waitFor(() => posted.some((m) => m.seq === 8));
  const w7 = posted.find((m) => m.t === "optcuts" && m.seq === 7), w8 = posted.find((m) => m.seq === 8);
  check("worker: progress {t, seq, iter, distortion} while it runs", posted.some((m) => m.t === "progress" && m.seq === 7 && m.iter > 0 && m.distortion > 0));
  check("worker: result {t: 'optcuts', seq, ok, uv, cornerUV, seams, distortion, iterations, ms}",
    w7 && w7.ok && Object.prototype.toString.call(w7.uv) === "[object Float32Array]" && w7.cornerUV.length === tor.tris.length && w7.seams.length > 0 && w7.iterations > 0 && w7.ms >= 0 && same(w7, rT));
  check("worker: bad input -> {t: 'fail', seq, error}", w8 && w8.t === "fail" && /out of range/.test(w8.error), JSON.stringify(w8));

  // 8. timings at ~2k and ~10k triangles (a 4 s budget each: a closed sphere at this size takes OptCuts longer)
  for (const [name, m] of [["torus ~2k", M.torus(50, 20)], ["sphere ~2k", M.uvSphere(40, 26)], ["torus ~10k", M.torus(100, 50)]]) {
    t = Date.now(); let first = 0;
    const r = eng.unwrap(m.pos, m.tris, { timeBudgetMs: 4000 }, () => { if (!first) first = Date.now() - t; }, 250);
    const ms = Date.now() - t;
    console.log("  TIME " + name + ": " + m.tris.length / 3 + " tris, " + ms + " ms, " + r.iterations + " iterations, " + r.topologyOps +
      " topology steps, distortion " + r.distortion.toFixed(4) + ", " + r.seams.length / 2 + " seam edges, " + (r.converged ? "converged" : "budget stop"));
    check(name + ": valid layout (every corner has a UV, 0 flipped)", r.cornerUV.every((u) => u >= 0) && r.flipped === 0);
  }

  console.log("\n" + pass + " passed, " + fail + " failed (" + ((Date.now() - T0) / 1000).toFixed(1) + " s)");
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.log("  FAIL crashed: " + (e && e.stack || e)); process.exit(1); });
