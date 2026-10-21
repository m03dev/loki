// node wasm/test/test_engine.js [path/to/sculpt.wasm] - exercises every engine call
const path = require("path");
const SculptEngine = require(path.join(__dirname, "..", "sculpt_engine.js"));
const wasm = process.argv[2] || path.join(__dirname, "..", "..", "build-wasm", "sculpt.wasm");

function sphere(seg, rings) {
  const p = [], t = [];
  for (let r = 0; r <= rings; r++) for (let s = 0; s <= seg; s++) {
    const th = Math.PI * r / rings, ph = 2 * Math.PI * s / seg;
    p.push(Math.sin(th) * Math.cos(ph), Math.cos(th), Math.sin(th) * Math.sin(ph));
  }
  const W = seg + 1;
  for (let r = 0; r < rings; r++) for (let s = 0; s < seg; s++) {
    const a = r * W + s, b = a + W;
    if (r > 0) t.push(a, a + 1, b);
    if (r < rings - 1) t.push(a + 1, b + 1, b);
  }
  return { p: new Float32Array(p), t: new Int32Array(t) };
}
let fails = 0;
const check = (ok, what) => { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) fails++; };
const ray = (x, y) => ({ origin: [x, y, 5], dir: [0, 0, -1] });

(async () => {
  const e = await SculptEngine.create(wasm);
  const m = sphere(128, 64);
  e.load(m.p, m.t);
  check(e.vertexCount === m.p.length / 3 && e.triCount > 15000, "load " + e.vertexCount + " verts, " + e.triCount + " tris");
  check(!!e.raycast([0.013, 0.007, 5], [0, 0, -1]), "raycast hits the sphere");

  const z0 = e.positions()[0];
  const nearest = () => { const P = e.positions(); let best = -1, bz = -9; for (let i = 0; i < P.length; i += 3) if (Math.abs(P[i]) < 0.05 && Math.abs(P[i + 1]) < 0.05 && P[i + 2] > bz) { bz = P[i + 2]; best = i / 3; } return bz; };
  const before = nearest();
  for (const k of ["Standard", "Clay", "ClayStrips", "Inflate", "Crease", "Flatten", "Scrape", "Pinch", "Layer", "Blob", "Smooth"]) {
    e.setBrush({ kernel: k, strength: 0.6 });
    const t0 = Date.now();
    let ok = e.press(ray(-0.2, 0), 1, 0.3);
    for (let i = 1; i <= 20; i++) ok = e.drag(ray(-0.2 + i * 0.02, 0), 1, 0.3) && ok;
    e.release();
    check(ok && e.takeDirty().length > 0, k.padEnd(11) + " stroke (" + (Date.now() - t0) + " ms)");
  }
  check(nearest() !== before, "surface moved");
  e.setBrush({ kernel: "Standard", strength: 1 });
  const b2 = nearest(); e.press(ray(0, 0), 1, 0.4); e.drag(ray(0.01, 0), 1, 0.4); e.release();
  const a2 = nearest(); e.undo(); const u2 = nearest(); e.redo();
  check(a2 > b2 && Math.abs(u2 - b2) < 1e-5 && Math.abs(nearest() - a2) < 1e-5, "undo / redo");

  e.setBrush({ kernel: "Move", strength: 1 });
  check(e.isGrab, "Move is a grab brush");
  const bm = nearest(); e.press(ray(0, 0), 1, 0.5); e.drag({ origin: [0, 0.4, 5], dir: [0, 0, -1] }, 1, 0.5); e.release();
  check(e.takeDirty().length > 0, "Move drags vertices");

  e.setSymmetry(1);
  e.setBrush({ kernel: "Standard", strength: 0.8 });
  e.press(ray(0.5, 0.3), 1, 0.2); e.release();
  const d = e.takeDirty(); const P = e.positions();
  check(d.some(i => P[i * 3] < 0) && d.some(i => P[i * 3] > 0), "X symmetry");
  e.setSymmetry(0);

  const v0 = e.topologyVersion, n0 = e.triCount;
  e.setDyntopo(true, 0.05);
  e.setBrush({ kernel: "Standard", strength: 0.5 });
  let t0 = Date.now();
  e.press(ray(-0.3, -0.3), 1, 0.3); for (let i = 1; i <= 15; i++) e.drag(ray(-0.3 + i * 0.04, -0.3), 1, 0.3);
  const rk = e.release();
  check(rk === 2 && e.topologyVersion !== v0 && e.triCount > n0, "dyntopo adds detail: " + n0 + " -> " + e.triCount + " tris (" + (Date.now() - t0) + " ms)");
  e.undo(); check(e.triCount === n0, "dyntopo undo restores topology");
  e.setDyntopo(false);

  t0 = Date.now();
  check(e.voxelRemesh(96), "voxel remesh -> " + e.vertexCount + " verts (" + (Date.now() - t0) + " ms)");
  t0 = Date.now();
  const q = e.quadRemesh(1500);
  check(q > 500 && e.polygons(), "quad remesh -> " + q + " quads (" + (Date.now() - t0) + " ms)");
  const base = e.vertexCount;
  t0 = Date.now();
  check(e.divide() === 2 && e.vertexCount > base * 3, "divide -> level 1, " + e.vertexCount + " verts (" + (Date.now() - t0) + " ms)");
  check(e.divide() === 3, "divide -> level 2, " + e.vertexCount + " verts");
  e.setBrush({ kernel: "Standard", strength: 0.8 }); e.press(ray(0, 0), 1, 0.2); e.release();
  check(e.setLevel(0) && e.vertexCount === base, "step down to level 0");
  check(e.setLevel(2) && e.level === 2, "back up to level 2 (detail kept)");
  e.setBrush({ kernel: "Paint", strength: 1, color: [0, 0, 1] });
  e.press(ray(0, 0), 1, 0.3); e.release();
  check(e.colors().some((c, i) => i % 3 === 2 && c > 0.5), "polypaint");
  e.setBrush({ kernel: "Mask", strength: 1 }); e.press(ray(0, 0), 1, 0.3); e.release();
  check(e.mask().some(x => x > 0.5), "mask brush"); e.maskOp("clear"); check(!e.mask().some(x => x > 0), "mask clear");

  // ---- staying smooth: the Smooth brush keeps volume, auto-smooth evens out Clay's ripples
  const patch = (P) => {   // mean radius, radius spread and roughness (|normal part of the umbrella Laplacian|) on the stroked patch
    const T = e.tris(), deg = new Int32Array(P.length / 3), acc = new Float64Array(P.length);
    for (let i = 0; i < T.length; i += 3) for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) if (a !== b && T[i] >= 0) { const u = T[i + a], v = T[i + b]; deg[u]++; for (let c = 0; c < 3; c++) acc[u * 3 + c] += P[v * 3 + c]; }
    let n = 0, sr = 0, sr2 = 0, rough = 0;
    for (let v = 0; v < P.length / 3; v++) {
      const x = P[v * 3], y = P[v * 3 + 1], z = P[v * 3 + 2];
      if (z < 0.5 || Math.abs(x) > 0.25 || Math.abs(y) > 0.12 || !deg[v]) continue;
      const r = Math.hypot(x, y, z); n++; sr += r; sr2 += r * r;
      rough += Math.abs((acc[v * 3] / deg[v] - x) * x + (acc[v * 3 + 1] / deg[v] - y) * y + (acc[v * 3 + 2] / deg[v] - z) * z) / r;
    }
    const mean = sr / n; return { mean, sd: Math.sqrt(Math.max(0, sr2 / n - mean * mean)), rough: rough / n };
  };
  const strokes = (radius) => { for (let pass = 0; pass < 4; pass++) { const y = (pass - 1.5) * 0.08; e.press(ray(-0.3, y), 1, radius); for (let i = 1; i <= 30; i++) e.drag(ray(-0.3 + i * 0.02, y), 1, radius); e.release(); } };
  const noisy = (amp) => {
    const s = sphere(256, 128); let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    for (let i = 0; i < s.p.length; i += 3) { const k = 1 + (rnd() - 0.5) * 2 * amp; s.p[i] *= k; s.p[i + 1] *= k; s.p[i + 2] *= k; }
    return s;
  };
  const smoothRes = {};
  for (const vol of [0, 1]) {
    const s = noisy(0.01); e.load(s.p, s.t);
    const n0 = patch(e.positions());
    e.setBrush({ kernel: "Smooth", strength: 0.6, smoothVolume: vol }); strokes(0.35);
    smoothRes[vol] = Object.assign(patch(e.positions()), { rough0: n0.rough });
  }
  const L = smoothRes[0], H = smoothRes[1];
  check(H.rough < H.rough0 / 5 && L.rough < L.rough0 / 5, "Smooth removes noise (roughness " + L.rough0.toExponential(1) + " -> classic " + L.rough.toExponential(1) + ", volume " + H.rough.toExponential(1) + ")");
  check(Math.abs(1 - H.mean) < 0.25 * Math.abs(1 - L.mean) && Math.abs(1 - H.mean) < 0.002,
    "Smooth keeps volume with smoothVolume 1 (patch radius " + L.mean.toFixed(4) + " classic -> " + H.mean.toFixed(4) + ")");
  const clayRes = {};
  for (const as of [0, 0.15]) {
    const s = sphere(256, 128); e.load(s.p, s.t);
    e.setBrush({ kernel: "Clay", strength: 0.5, autoSmooth: as }); strokes(0.35);
    clayRes[as] = patch(e.positions());
  }
  check(clayRes[0.15].rough < clayRes[0].rough * 0.7 && clayRes[0.15].mean > 1.3,
    "auto-smooth evens Clay out and keeps its build (roughness " + clayRes[0].rough.toExponential(1) + " -> " + clayRes[0.15].rough.toExponential(1) + ", height " + clayRes[0.15].mean.toFixed(2) + ")");

  // zero-weight vertices stay put: a front-faces-only dab with a radius bigger than the sphere leaves its back alone
  { const s = sphere(128, 64); e.load(s.p, s.t);
    const back = []; for (let i = 0; i < s.p.length; i += 3) if (s.p[i + 2] < -0.3) back.push(i);
    e.setBrush({ kernel: "Inflate", strength: 0.8 });
    const ok = e.press(ray(0.013, 0.007), 1, 2.5) && e.drag(ray(0.063, 0.007), 1, 2.5); e.release();
    const P = e.positions(); let moved = 0, front = 0; for (let i = 0; i < P.length; i += 3) if (Math.abs(P[i + 2] - s.p[i + 2]) > 1e-6) { if (s.p[i + 2] < -0.3) moved++; else front++; }
    const d = e.takeDirty();
    check(ok && front > 1000 && moved === 0 && d.length < s.p.length / 3 * 0.75,
      "a huge front-faces dab leaves the back faces alone (" + front + " moved, " + d.length + " of " + s.p.length / 3 + " vertices sent)"); }

  // ---- Tube (curve brush) and Insert Mesh add geometry, one undo step each
  { const s = sphere(128, 64); e.load(s.p, s.t); const v0 = e.vertexCount, t0v = e.topologyVersion;
    const pts = []; for (let i = 0; i <= 20; i++) { const a = -0.6 + i * 0.06; pts.push(a, 0, Math.sqrt(1 - a * a)); }
    const added = e.tube(pts, 0.05, 10);
    check(added > 100 && e.vertexCount === v0 + added && e.topologyVersion !== t0v && e.polygons(), "Tube sweeps a tube along the stroke (+" + added + " vertices, quads kept)");
    e.undo(); check(e.vertexCount === v0, "Tube undo");
    const ins = e.insert(0, [0, 0, 1], [0, 0, 1], 0.2);
    check(ins > 100 && e.vertexCount === v0 + ins && !!e.raycast([0, 0, 5], [0, 0, -1]), "Insert Mesh adds a sphere at the surface point (+" + ins + " vertices)");
    const cube = e.insert(1, [0.5, 0.5, 0.7], [0.5, 0.5, 0.7], 0.15);
    check(cube > 20, "Insert Mesh adds a cube (+" + cube + " vertices)");
    e.undo(); e.undo(); check(e.vertexCount === v0, "Insert undo"); }

  // ---- speed on a denser mesh (printed; a loose bound so a slow CI box still passes)
  { const s = sphere(1024, 256); e.load(s.p, s.t);
    e.setBrush({ kernel: "Clay", strength: 0.5, autoSmooth: 0.15 });
    let t1 = performance.now(); e.press(ray(-0.3, 0), 1, 0.3); for (let i = 1; i <= 20; i++) e.drag(ray(-0.3 + i * 0.015, 0), 1, 0.3); e.release();
    const ms = (performance.now() - t1) / 21;
    check(ms < 60, "Clay + auto-smooth dab on " + e.vertexCount + " vertices: " + ms.toFixed(2) + " ms"); }
  console.log(fails ? fails + " FAILED" : "ALL OK");
  process.exit(fails ? 1 : 0);
})().catch(err => { console.error(err); process.exit(1); });
