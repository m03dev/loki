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
  console.log(fails ? fails + " FAILED" : "ALL OK");
  process.exit(fails ? 1 : 0);
})().catch(err => { console.error(err); process.exit(1); });
