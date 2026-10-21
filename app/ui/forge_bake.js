// Forge's Baking workspace (owner 2026-10-21: Alpaca3D's Bake lab "into forge ... a real system"). Workspace:
// Baking. The LOW object is the one being edited (a cage with UVs - UV Editing makes them); the HIGH object is any
// other mesh in the scene (a sculpt, the original before retopology). For every texel of the low's UV layout a ray
// is cast from a CAGE (the low pushed out along its smoothed normals by the cage distance) back along the normal
// into the high; what it hits becomes the maps:
//   Normal (tangent space, OpenGL or DirectX green), Normal (object space), Ambient occlusion (hemisphere rays on
//   the high), Curvature (convex light / concave dark), Height (how far the high is from the low), Thickness,
//   Position (the high's bounding box as RGB)
// with supersampling, edge padding (dilation), a cage you can push out or pull in, max distances, a live preview on
// the low (normal + AO maps on its material) and PNG downloads. The rays use the BVH from forge_retopo.js. Work
// runs in slices with a progress bar and Cancel, so the window never freezes.
"use strict";

const FORGE_BAKE_STORE = "loki-forge-bake";
const FORGE_BAKE_DEFAULTS = { res: 1024, aa: 1, cage: 0.02, maxDist: 0.05, pad: 8, aoSamples: 16, aoDist: 0.2,
  maps: { normal: true, normalObj: false, ao: true, curvature: true, height: false, thickness: false, position: false }, greenDX: false };
const FORGE_BAKE_MAPS = [["normal", "Normal (tangent)"], ["normalObj", "Normal (object)"], ["ao", "Ambient occlusion"], ["curvature", "Curvature"],
  ["height", "Height"], ["thickness", "Thickness"], ["position", "Position"]];

function forgeBakeSettings() {
  let s = {}; try { s = JSON.parse(localStorage.getItem(FORGE_BAKE_STORE) || "{}") || {}; } catch (_) { s = {}; }
  const out = Object.assign({}, FORGE_BAKE_DEFAULTS, s); out.maps = Object.assign({}, FORGE_BAKE_DEFAULTS.maps, s.maps || {});
  return out;
}
function forgeBakeSave(s) { try { localStorage.setItem(FORGE_BAKE_STORE, JSON.stringify(s)); } catch (_) { /* private window */ } }

// ------------------------------------------------------------------ the baker (no DOM: arrays in, Float32 images out)
// low: {pos (world xyz per vertex), f (faces), fuv, uv, nrm? (smooth world normals per vertex)}; high: {pos, idx, nrm (world,
// per vertex) or null}; opts: settings (+ size: the scene's size, for the relative distances). Returns a job:
// job.step(ms) bakes for ~ms and returns progress 0-1; job.result() -> {res, maps: {name: Float32Array(res*res*4)}, mask}
function forgeBakeJob(low, high, opts) {
  const S = Object.assign({}, FORGE_BAKE_DEFAULTS, opts), res = S.res | 0, aa = Math.max(1, S.aa | 0), size = S.size || 1;
  const cage = S.cage * size, maxD = cage + S.maxDist * size + cage, aoD = S.aoDist * size;
  const bvh = high.bvh || forgeRetopoBVH(high.pos, high.idx, null);
  const want = Object.keys(S.maps).filter((k) => S.maps[k]);
  const maps = {}; for (const k of want) maps[k] = new Float32Array(res * res * 4);
  const weight = new Float32Array(res * res);
  // ---- low: smoothed vertex normals (by position, so split corners share one) and tangents from the UVs
  const nv = low.pos.length / 3, key = (i) => Math.round(low.pos[i * 3] * 1e5) + ":" + Math.round(low.pos[i * 3 + 1] * 1e5) + ":" + Math.round(low.pos[i * 3 + 2] * 1e5);
  const groupOf = new Int32Array(nv), groups = new Map();
  for (let i = 0; i < nv; i++) { const k = key(i); if (!groups.has(k)) groups.set(k, groups.size); groupOf[i] = groups.get(k); }
  const gN = new Float32Array(groups.size * 3), tri = [];
  low.f.forEach((f, fi) => { for (let k = 1; k + 1 < f.length; k++) tri.push([fi, 0, k, k + 1]); });
  const P = (i) => [low.pos[i * 3], low.pos[i * 3 + 1], low.pos[i * 3 + 2]];
  for (const [fi, a, b, c] of tri) {
    const f = low.f[fi], pa = P(f[a]), pb = P(f[b]), pc = P(f[c]);
    const e1 = [pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]], e2 = [pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]];
    const n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
    for (const vi of [f[a], f[b], f[c]]) { const g = groupOf[vi] * 3; gN[g] += n[0]; gN[g + 1] += n[1]; gN[g + 2] += n[2]; }
  }
  for (let g = 0; g < gN.length; g += 3) { const l = Math.hypot(gN[g], gN[g + 1], gN[g + 2]) || 1; gN[g] /= l; gN[g + 1] /= l; gN[g + 2] /= l; }
  // per-corner tangent / bitangent (by UV), averaged per (vertex, uv)
  const tanOf = new Map();
  for (const [fi, a, b, c] of tri) {
    const f = low.f[fi], cu = low.fuv[fi];
    const pa = P(f[a]), pb = P(f[b]), pc = P(f[c]), ua = low.uv[cu[a]], ub = low.uv[cu[b]], uc = low.uv[cu[c]];
    const e1 = [pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]], e2 = [pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]];
    const du1 = ub[0] - ua[0], dv1 = ub[1] - ua[1], du2 = uc[0] - ua[0], dv2 = uc[1] - ua[1];
    const r = du1 * dv2 - du2 * dv1; if (Math.abs(r) < 1e-14) continue;
    const k = 1 / r;
    const T = [(e1[0] * dv2 - e2[0] * dv1) * k, (e1[1] * dv2 - e2[1] * dv1) * k, (e1[2] * dv2 - e2[2] * dv1) * k];
    const B = [(e2[0] * du1 - e1[0] * du2) * k, (e2[1] * du1 - e1[1] * du2) * k, (e2[2] * du1 - e1[2] * du2) * k];
    for (const cc of [a, b, c]) {
      const id = f[cc] + "/" + cu[cc]; let t = tanOf.get(id); if (!t) tanOf.set(id, (t = [0, 0, 0, 0, 0, 0]));
      t[0] += T[0]; t[1] += T[1]; t[2] += T[2]; t[3] += B[0]; t[4] += B[1]; t[5] += B[2];
    }
  }
  // ---- high: curvature per vertex (welded by position): mean of dot(nj - ni, pj - pi) / |pj - pi|^2 over edges
  let hiCurv = null, hiN = high.nrm, hBox = null;
  const hpos = high.pos, hnv = hpos.length / 3;
  if (S.maps.curvature || !hiN) {
    const hk = new Map(), hg = new Int32Array(hnv);
    for (let i = 0; i < hnv; i++) { const k = Math.round(hpos[i * 3] * 1e5) + ":" + Math.round(hpos[i * 3 + 1] * 1e5) + ":" + Math.round(hpos[i * 3 + 2] * 1e5); if (!hk.has(k)) hk.set(k, hk.size); hg[i] = hk.get(k); }
    const G = hk.size, gp = new Float32Array(G * 3), gn = new Float32Array(G * 3);
    const nt = (high.idx ? high.idx.length : hnv) / 3, cor = (t, k) => (high.idx ? high.idx[t * 3 + k] : t * 3 + k);
    for (let i = 0; i < hnv; i++) { const g = hg[i] * 3; gp[g] = hpos[i * 3]; gp[g + 1] = hpos[i * 3 + 1]; gp[g + 2] = hpos[i * 3 + 2]; }
    for (let t = 0; t < nt; t++) {
      const a = cor(t, 0), b = cor(t, 1), c = cor(t, 2);
      const e1 = [hpos[b * 3] - hpos[a * 3], hpos[b * 3 + 1] - hpos[a * 3 + 1], hpos[b * 3 + 2] - hpos[a * 3 + 2]];
      const e2 = [hpos[c * 3] - hpos[a * 3], hpos[c * 3 + 1] - hpos[a * 3 + 1], hpos[c * 3 + 2] - hpos[a * 3 + 2]];
      const n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
      for (const vi of [a, b, c]) { const g = hg[vi] * 3; gn[g] += n[0]; gn[g + 1] += n[1]; gn[g + 2] += n[2]; }
    }
    for (let g = 0; g < gn.length; g += 3) { const l = Math.hypot(gn[g], gn[g + 1], gn[g + 2]) || 1; gn[g] /= l; gn[g + 1] /= l; gn[g + 2] /= l; }
    if (!hiN) { hiN = new Float32Array(hnv * 3); for (let i = 0; i < hnv; i++) hiN.set(gn.subarray(hg[i] * 3, hg[i] * 3 + 3), i * 3); }
    if (S.maps.curvature) {
      const sum = new Float32Array(G), cnt = new Float32Array(G);
      for (let t = 0; t < nt; t++) for (let k = 0; k < 3; k++) {
        const i = hg[cor(t, k)], j = hg[cor(t, (k + 1) % 3)]; if (i === j) continue;
        const dx = gp[j * 3] - gp[i * 3], dy = gp[j * 3 + 1] - gp[i * 3 + 1], dz = gp[j * 3 + 2] - gp[i * 3 + 2], L = dx * dx + dy * dy + dz * dz || 1e-12;
        const c = ((gn[j * 3] - gn[i * 3]) * dx + (gn[j * 3 + 1] - gn[i * 3 + 1]) * dy + (gn[j * 3 + 2] - gn[i * 3 + 2]) * dz) / L;
        sum[i] += c; cnt[i]++; sum[j] += c; cnt[j]++;
      }
      hiCurv = new Float32Array(hnv);
      for (let i = 0; i < hnv; i++) { const g = hg[i]; hiCurv[i] = cnt[g] ? (sum[g] / cnt[g]) * size : 0; }
    }
  }
  if (S.maps.position) {
    hBox = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
    for (let i = 0; i < hnv; i++) for (let a = 0; a < 3; a++) { const v = hpos[i * 3 + a]; if (v < hBox[a]) hBox[a] = v; if (v > hBox[a + 3]) hBox[a + 3] = v; }
  }
  const hiAttr = (hit, arr, comps) => {
    const [a, b, c] = bvh.corners(hit.tri), w0 = 1 - hit.u - hit.v, w1 = hit.u, w2 = hit.v;
    const out = []; for (let q = 0; q < comps; q++) out.push(arr[a * comps + q] * w0 + arr[b * comps + q] * w1 + arr[c * comps + q] * w2);
    return out;
  };
  // ---- a stratified cosine hemisphere around n (for AO)
  let seed = 1234567;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  function aoAt(p, n) {
    const up = Math.abs(n[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
    let t = [up[1] * n[2] - up[2] * n[1], up[2] * n[0] - up[0] * n[2], up[0] * n[1] - up[1] * n[0]];
    const tl = Math.hypot(t[0], t[1], t[2]) || 1; t = [t[0] / tl, t[1] / tl, t[2] / tl];
    const b = [n[1] * t[2] - n[2] * t[1], n[2] * t[0] - n[0] * t[2], n[0] * t[1] - n[1] * t[0]];
    const o = [p[0] + n[0] * size * 1e-4, p[1] + n[1] * size * 1e-4, p[2] + n[2] * size * 1e-4];
    const N = S.aoSamples | 0, side = Math.max(1, Math.round(Math.sqrt(N)));
    let hit = 0, total = 0;
    for (let i = 0; i < side; i++) for (let j = 0; j < side; j++) {
      const u1 = (i + rnd()) / side, u2 = (j + rnd()) / side, r = Math.sqrt(u1), ph = 2 * Math.PI * u2;
      const x = r * Math.cos(ph), y = r * Math.sin(ph), z = Math.sqrt(Math.max(0, 1 - u1));
      const d = [t[0] * x + b[0] * y + n[0] * z, t[1] * x + b[1] * y + n[1] * z, t[2] * x + b[2] * y + n[2] * z];
      total++; if (bvh.ray(o, d, aoD)) hit++;
    }
    return total ? 1 - hit / total : 1;
  }
  // ---- the raster walk: one triangle at a time, one texel row at a time (resumable)
  let ti = 0, row = -1, box = null, done = false, misses = 0, texels = 0;
  const startTri = () => {
    if (ti >= tri.length) { done = true; return; }
    const [fi, a, b, c] = tri[ti], cu = low.fuv[fi];
    const A = low.uv[cu[a]], B = low.uv[cu[b]], C = low.uv[cu[c]];
    const x0 = Math.max(0, Math.floor(Math.min(A[0], B[0], C[0]) * res)), x1 = Math.min(res - 1, Math.ceil(Math.max(A[0], B[0], C[0]) * res));
    const y0 = Math.max(0, Math.floor(Math.min(A[1], B[1], C[1]) * res)), y1 = Math.min(res - 1, Math.ceil(Math.max(A[1], B[1], C[1]) * res));
    box = { fi, a, b, c, A, B, C, x0, x1, y0, y1 }; row = y0;
  };
  function texel(x, y, sx, sy) {
    const { fi, a, b, c, A, B, C } = box, u = (x + sx) / res, v = (y + sy) / res;
    const d = (B[1] - C[1]) * (A[0] - C[0]) + (C[0] - B[0]) * (A[1] - C[1]); if (Math.abs(d) < 1e-14) return null;
    const w0 = ((B[1] - C[1]) * (u - C[0]) + (C[0] - B[0]) * (v - C[1])) / d, w1 = ((C[1] - A[1]) * (u - C[0]) + (A[0] - C[0]) * (v - C[1])) / d, w2 = 1 - w0 - w1;
    if (w0 < -1e-6 || w1 < -1e-6 || w2 < -1e-6) return null;
    const f = low.f[fi], cu = low.fuv[fi], ids = [f[a], f[b], f[c]], ws = [w0, w1, w2];
    const p = [0, 0, 0], n = [0, 0, 0], T = [0, 0, 0], Bt = [0, 0, 0];
    ids.forEach((vi, k) => {
      const w = ws[k], g = groupOf[vi] * 3;
      p[0] += low.pos[vi * 3] * w; p[1] += low.pos[vi * 3 + 1] * w; p[2] += low.pos[vi * 3 + 2] * w;
      n[0] += gN[g] * w; n[1] += gN[g + 1] * w; n[2] += gN[g + 2] * w;
      const tt = tanOf.get(vi + "/" + cu[[a, b, c][k]]); if (tt) { T[0] += tt[0] * w; T[1] += tt[1] * w; T[2] += tt[2] * w; Bt[0] += tt[3] * w; Bt[1] += tt[4] * w; Bt[2] += tt[5] * w; }
    });
    const nl = Math.hypot(n[0], n[1], n[2]) || 1; n[0] /= nl; n[1] /= nl; n[2] /= nl;
    // Gram-Schmidt: T orthogonal to n, B = handedness * (n x T)
    const tn = T[0] * n[0] + T[1] * n[1] + T[2] * n[2];
    let Tn = [T[0] - n[0] * tn, T[1] - n[1] * tn, T[2] - n[2] * tn]; const tl = Math.hypot(Tn[0], Tn[1], Tn[2]) || 1; Tn = [Tn[0] / tl, Tn[1] / tl, Tn[2] / tl];
    let Bn = [n[1] * Tn[2] - n[2] * Tn[1], n[2] * Tn[0] - n[0] * Tn[2], n[0] * Tn[1] - n[1] * Tn[0]];
    if (Bn[0] * Bt[0] + Bn[1] * Bt[1] + Bn[2] * Bt[2] < 0) Bn = [-Bn[0], -Bn[1], -Bn[2]];
    // the cage ray: from p + n * cage, back along -n
    const o = [p[0] + n[0] * cage, p[1] + n[1] * cage, p[2] + n[2] * cage];
    let hit = bvh.ray(o, [-n[0], -n[1], -n[2]], maxD);
    if (!hit) { misses++; return { p, n, Tn, Bn, hit: null }; }
    return { p, n, Tn, Bn, hit };
  }
  function shade(s, out) {
    const { n, Tn, Bn, hit } = s;
    let hn = n;
    if (hit) { const q = hiAttr(hit, hiN, 3), l = Math.hypot(q[0], q[1], q[2]) || 1; hn = [q[0] / l, q[1] / l, q[2] / l]; if (hn[0] * n[0] + hn[1] * n[1] + hn[2] * n[2] < 0 && !high.nrm) hn = [-hn[0], -hn[1], -hn[2]]; }
    if (maps.normal) { const x = hn[0] * Tn[0] + hn[1] * Tn[1] + hn[2] * Tn[2], y = hn[0] * Bn[0] + hn[1] * Bn[1] + hn[2] * Bn[2], z = hn[0] * n[0] + hn[1] * n[1] + hn[2] * n[2];
      out.normal = [x * 0.5 + 0.5, (S.greenDX ? -y : y) * 0.5 + 0.5, z * 0.5 + 0.5]; }
    if (maps.normalObj) out.normalObj = [hn[0] * 0.5 + 0.5, hn[1] * 0.5 + 0.5, hn[2] * 0.5 + 0.5];
    if (maps.ao) { const a = hit ? aoAt(hit.p, hn) : 1; out.ao = [a, a, a]; }
    if (maps.curvature) { const c = hit && hiCurv ? hiAttr(hit, hiCurv, 1)[0] : 0, g = Math.max(0, Math.min(1, 0.5 + c * 0.15)); out.curvature = [g, g, g]; }
    if (maps.height) { const h = hit ? Math.max(0, Math.min(1, 0.5 + (cage - hit.t) / (2 * cage || 1))) : 0.5; out.height = [h, h, h]; }
    if (maps.thickness) {
      let th = 1;
      if (hit) { const back = bvh.ray([hit.p[0] - hn[0] * size * 1e-4, hit.p[1] - hn[1] * size * 1e-4, hit.p[2] - hn[2] * size * 1e-4], [-hn[0], -hn[1], -hn[2]], size); th = back ? Math.min(1, back.t / (0.25 * size)) : 1; }
      out.thickness = [th, th, th];
    }
    if (maps.position) { const q = hit ? hit.p : s.p; out.position = [0, 1, 2].map((a) => (q[a] - hBox[a]) / ((hBox[a + 3] - hBox[a]) || 1)); }
  }
  function step(ms) {
    const t0 = performance.now();
    if (row < 0 && !done) startTri();
    while (!done && performance.now() - t0 < ms) {
      if (row > box.y1) { ti++; startTri(); continue; }
      for (let x = box.x0; x <= box.x1; x++) {
        let any = false; const acc = {};
        for (let sy = 0; sy < aa; sy++) for (let sx = 0; sx < aa; sx++) {
          const s = texel(x, row, (sx + 0.5) / aa, (sy + 0.5) / aa); if (!s) continue;
          any = true; const o = {}; shade(s, o);
          for (const k in o) { const a = acc[k] || (acc[k] = [0, 0, 0, 0]); a[0] += o[k][0]; a[1] += o[k][1]; a[2] += o[k][2]; a[3]++; }
        }
        if (!any) continue;
        const pi = (res - 1 - row) * res + x;              // images are top-down; UV v = 0 is the bottom
        texels++;
        for (const k in acc) { const a = acc[k], m = maps[k], w = weight[pi] + a[3];
          for (let q = 0; q < 3; q++) m[pi * 4 + q] = (m[pi * 4 + q] * weight[pi] + a[q]) / w; m[pi * 4 + 3] = 1; }
        weight[pi] += acc[want[0]] ? acc[want[0]][3] : 1;
      }
      row++;
    }
    return done ? 1 : ti / Math.max(1, tri.length);
  }
  function dilate() {                                       // edge padding: grow every map into the empty texels
    const filled = new Uint8Array(res * res); for (let i = 0; i < weight.length; i++) filled[i] = weight[i] > 0 ? 1 : 0;
    for (let it = 0; it < (S.pad | 0); it++) {
      const next = filled.slice(), add = [];
      for (let y = 0; y < res; y++) for (let x = 0; x < res; x++) {
        const i = y * res + x; if (filled[i]) continue;
        let n = 0; const s = {};
        for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
          const X = x + dx, Y = y + dy; if (X < 0 || Y < 0 || X >= res || Y >= res) continue;
          const j = Y * res + X; if (!filled[j]) continue; n++;
          for (const k of want) { const a = s[k] || (s[k] = [0, 0, 0]); a[0] += maps[k][j * 4]; a[1] += maps[k][j * 4 + 1]; a[2] += maps[k][j * 4 + 2]; }
        }
        if (n) { add.push([i, n, s]); next[i] = 1; }
      }
      for (const [i, n, s] of add) for (const k of want) { maps[k][i * 4] = s[k][0] / n; maps[k][i * 4 + 1] = s[k][1] / n; maps[k][i * 4 + 2] = s[k][2] / n; maps[k][i * 4 + 3] = 1; }
      filled.set(next);
    }
  }
  return {
    step, get done() { return done; },
    result() { dilate(); return { res, maps, coverage: texels, misses, triangles: tri.length }; },
  };
}

const ForgeBake = (() => {
  const B = { view: null, panel: null, job: null, result: null, highId: null, keep: null, cancel: false };
  const say = (t, bad) => { if (typeof forgeSay === "function") forgeSay(t, bad); const s = B.panel && B.panel.querySelector(".fbk-status"); if (s) { s.textContent = t; s.classList.toggle("bad", !!bad); } };
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

  function meshOf(n) { let m = null; if (n) n.inner.traverse((o) => { if (!m && o.isMesh && o.geometry && o.geometry.attributes.position && o.name !== "forge-sel" && o.name !== "forge-smooth") m = o; }); return m; }
  function highChoices() {
    const v = B.view, t = v && v.tree && v.tree.api; if (!t) return [];
    return t.sceneNodes().filter((n) => n.kind === "mesh" && !n.root && meshOf(n));
  }
  function lowData() {
    const v = B.view, m = v && v.poly;
    if (!m) throw new Error("The low object needs to be a modelled mesh (the one you are editing).");
    if (!window.ForgeUV || !ForgeUV.has(m)) throw new Error("The low object has no UVs yet - make them in the UV Editing workspace first.");
    v.holder.updateMatrixWorld(true);
    const e = v.holder.matrixWorld.elements, pos = new Float32Array(m.v.length * 3);
    m.v.forEach((p, i) => { pos[i * 3] = e[0] * p[0] + e[4] * p[1] + e[8] * p[2] + e[12]; pos[i * 3 + 1] = e[1] * p[0] + e[5] * p[1] + e[9] * p[2] + e[13]; pos[i * 3 + 2] = e[2] * p[0] + e[6] * p[1] + e[10] * p[2] + e[14]; });
    return { pos, f: m.f, fuv: m.fuv, uv: m.uv };
  }
  function highData(node) {
    const mesh = meshOf(node); if (!mesh) throw new Error("Pick a high-poly object.");
    mesh.updateMatrixWorld(true);
    const g = mesh.geometry, src = g.attributes.position.array, M = mesh.matrixWorld, e = M.elements, n = src.length / 3, pos = new Float32Array(src.length);
    for (let i = 0; i < n; i++) { const x = src[i * 3], y = src[i * 3 + 1], z = src[i * 3 + 2];
      pos[i * 3] = e[0] * x + e[4] * y + e[8] * z + e[12]; pos[i * 3 + 1] = e[1] * x + e[5] * y + e[9] * z + e[13]; pos[i * 3 + 2] = e[2] * x + e[6] * y + e[10] * z + e[14]; }
    let nrm = null;
    if (g.attributes.normal) {
      const NM = new B.view.THREE.Matrix3().getNormalMatrix(M).elements, s = g.attributes.normal.array; nrm = new Float32Array(s.length);
      for (let i = 0; i < n; i++) { const x = s[i * 3], y = s[i * 3 + 1], z = s[i * 3 + 2]; nrm[i * 3] = NM[0] * x + NM[3] * y + NM[6] * z; nrm[i * 3 + 1] = NM[1] * x + NM[4] * y + NM[7] * z; nrm[i * 3 + 2] = NM[2] * x + NM[5] * y + NM[8] * z; }
    }
    const idx = g.index ? g.index.array : null;
    return { pos, idx, nrm, bvh: forgeRetopoBVH(pos, idx, null) };
  }
  async function bake() {
    if (B.job) return;
    const st = forgeBakeSettings();
    let low, high;
    try {
      low = lowData();
      const choices = highChoices(), id = B.highId != null ? B.highId : (choices[0] && choices[0].id);
      const node = choices.find((n) => n.id === id);
      if (!node) throw new Error("Put the high-poly object in the scene next to the low one, then pick it as High.");
      high = highData(node);
    } catch (e) { say(e.message, true); return null; }
    const job = forgeBakeJob(low, high, Object.assign({}, st, { size: B.view.size || 1 }));
    B.job = job; B.cancel = false;
    const bar = B.panel && B.panel.querySelector(".fbk-progress"), t0 = performance.now();
    say("Baking...");
    while (!job.done) {
      if (B.cancel) { B.job = null; say("Bake cancelled."); return null; }
      const p = job.step(30);
      if (bar) bar.style.width = Math.round(p * 100) + "%";
      await new Promise((r) => setTimeout(r, 0));
    }
    const r = job.result(); B.job = null; B.result = r;
    if (bar) bar.style.width = "100%";
    previews();
    say("Baked " + Object.keys(r.maps).length + " map(s) at " + r.res + " px in " + ((performance.now() - t0) / 1000).toFixed(1) + " s"
      + (r.misses ? " - " + r.misses + " ray(s) missed the high (raise Max distance or the Cage)" : "") + ".");
    if (st.preview !== false) apply(true);
    return r;
  }
  function toCanvas(arr, res) {
    const c = document.createElement("canvas"); c.width = c.height = res;
    const g = c.getContext("2d"), img = g.createImageData(res, res);
    for (let i = 0; i < res * res; i++) { for (let q = 0; q < 3; q++) img.data[i * 4 + q] = Math.round(Math.max(0, Math.min(1, arr[i * 4 + q])) * 255); img.data[i * 4 + 3] = 255; }
    g.putImageData(img, 0, 0); return c;
  }
  function previews() {
    const box = B.panel && B.panel.querySelector(".fbk-maps"); if (!box || !B.result) return;
    box.textContent = "";
    for (const [k, label] of FORGE_BAKE_MAPS) {
      const arr = B.result.maps[k]; if (!arr) continue;
      const c = toCanvas(arr, B.result.res); c.className = "fbk-thumb"; c.dataset.map = k; c.title = label + " - click to download it as a PNG";
      const fig = el("figure", "fbk-fig"); fig.append(c, el("figcaption", "", label));
      c.addEventListener("click", () => download(k));
      box.append(fig);
    }
  }
  function download(k) {
    if (!B.result || !B.result.maps[k]) return;
    const c = toCanvas(B.result.maps[k], B.result.res), a = document.createElement("a");
    a.href = c.toDataURL("image/png"); a.download = (k === "normal" ? "normal" : k) + "_" + B.result.res + ".png"; document.body.append(a); a.click(); a.remove();
  }
  // show the maps on the low: the normal map (tangent) and AO on its material
  function apply(on) {
    const v = B.view, mat = v && v.material, THREE = v && v.THREE; if (!mat) return;
    if (on && B.result) {
      if (!B.keep) B.keep = { normalMap: mat.normalMap, aoMap: mat.aoMap };
      const tex = (k) => { const t = new THREE.CanvasTexture(toCanvas(B.result.maps[k], B.result.res)); t.flipY = true; return t; };
      if (B.result.maps.normal) { mat.normalMap = tex("normal"); if (mat.normalScale) mat.normalScale.set(1, forgeBakeSettings().greenDX ? 1 : -1); }
      if (B.result.maps.ao) mat.aoMap = tex("ao");
      mat.needsUpdate = true;
    } else if (B.keep) { mat.normalMap = B.keep.normalMap; mat.aoMap = B.keep.aoMap; B.keep = null; mat.needsUpdate = true; }
    v.dirty = true;
  }

  function build() {
    const body = document.querySelector("#forge .forge-body");
    if (!body) return null;
    if (B.panel) return B.panel;
    const p = el("aside", "forge-uvpanel forge-bakepanel"); p.id = "forge-bakepanel"; p.hidden = true;
    const head = el("div", "fuv-head"); head.append(el("span", "fuv-title", "Baking"));
    const tb = el("div", "fuv-toolbar");
    const highSel = el("select", "fbk-high"); highSel.title = "The high-poly object the details come from";
    const fillHigh = () => { highSel.textContent = ""; for (const n of highChoices()) { const o = el("option", "", n.name); o.value = String(n.id); highSel.append(o); }
      if (B.highId != null) highSel.value = String(B.highId); };
    highSel.addEventListener("focus", fillHigh); highSel.addEventListener("pointerdown", fillHigh);
    highSel.addEventListener("change", () => { B.highId = +highSel.value; });
    const btn = (label, tip, fn, id) => { const b = el("button", "fuv-btn", label); b.type = "button"; b.title = tip; if (id) b.dataset.bk = id; b.addEventListener("click", (e) => { e.stopPropagation(); fn(); }); return b; };
    tb.append(el("span", "fuv-glabel", "Low = the edited object · High"), highSel,
      btn("Bake", "Bake the checked maps from the high onto the low's UVs.", bake, "bake"),
      btn("Cancel", "Stop the bake.", () => { B.cancel = true; }),
      btn("Preview", "Show / hide the baked normal + AO on the low.", () => apply(!B.keep), "preview"));
    head.append(tb);
    const set = el("div", "fuv-settings");
    const st = forgeBakeSettings();
    const row = (label, key, kind, opt) => {
      const r = el("label", "fuv-set-row"); r.append(el("span", "", label));
      let i;
      if (kind === "select") { i = el("select"); for (const [v, t] of opt) { const o = el("option", "", t); o.value = String(v); i.append(o); } i.value = String(st[key]); }
      else if (kind === "bool") { i = el("input"); i.type = "checkbox"; i.checked = !!st[key]; }
      else { i = el("input"); i.type = "number"; Object.assign(i, opt); i.value = String(st[key]); }
      i.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter" || e.key === "Escape") i.blur(); });
      i.addEventListener("change", () => { const s = forgeBakeSettings(); s[key] = kind === "bool" ? i.checked : isFinite(+i.value) ? +i.value : FORGE_BAKE_DEFAULTS[key]; forgeBakeSave(s); });
      r.append(i); return r;
    };
    const mapsSec = el("div", "fuv-sec"); mapsSec.append(el("div", "fuv-sec-title", "Maps"));
    for (const [k, label] of FORGE_BAKE_MAPS) {
      const r = el("label", "fuv-set-row"), i = el("input"); i.type = "checkbox"; i.checked = !!st.maps[k]; i.dataset.map = k;
      i.addEventListener("change", () => { const s = forgeBakeSettings(); s.maps[k] = i.checked; forgeBakeSave(s); });
      r.append(el("span", "", label), i); mapsSec.append(r);
    }
    const sec = (name, rows) => { const d = el("div", "fuv-sec"); d.append(el("div", "fuv-sec-title", name), ...rows); return d; };
    set.append(mapsSec,
      sec("Output", [row("Size (px)", "res", "select", [[256, "256"], [512, "512"], [1024, "1024"], [2048, "2048"], [4096, "4096"]]), row("Supersampling", "aa", "select", [[1, "1x"], [2, "4x"], [3, "9x"]]),
        row("Edge padding (px)", "pad", "num", { min: 0, max: 64, step: 1 }), row("Normal: DirectX green", "greenDX", "bool")]),
      sec("Rays", [row("Cage push (x size)", "cage", "num", { min: 0, max: 0.5, step: 0.005 }), row("Max distance (x size)", "maxDist", "num", { min: 0, max: 1, step: 0.005 }),
        row("AO samples", "aoSamples", "num", { min: 1, max: 256, step: 1 }), row("AO distance (x size)", "aoDist", "num", { min: 0.01, max: 2, step: 0.01 })]));
    const prog = el("div", "fbk-bar"); prog.append(el("div", "fbk-progress"));
    const maps = el("div", "fbk-maps"), status = el("div", "fuv-status fbk-status");
    p.append(head, set, prog, maps, status);
    const chan = document.getElementById("forge-chancol");
    if (chan && chan.parentElement === body) body.insertBefore(p, chan); else body.append(p);
    B.panel = p; fillHigh();
    if (typeof FORGE_SPLIT_PANELS !== "undefined" && !FORGE_SPLIT_PANELS.some((x) => x[0] === "forge-bakepanel")) FORGE_SPLIT_PANELS.push(["forge-bakepanel", "right", 38, 20, 70]);
    if (typeof forgeSplitAttach === "function") forgeSplitAttach();
    return p;
  }
  function show(on) { const p = build(); if (!p) return; p.hidden = !on; if (on) { const s = p.querySelector(".fbk-high"); if (s) s.dispatchEvent(new Event("focus")); } if (typeof forgeSplitAttach === "function") forgeSplitAttach(); }
  setInterval(() => { const v = typeof forge !== "undefined" && forge.view; if (v && v !== B.view) B.view = v; }, 400);
  return { bake, show, apply, download, state: B, build, setHigh: (id) => { B.highId = id; } };
})();

if (typeof FORGE_PRO_CMDS !== "undefined" && !FORGE_PRO_CMDS.bakeMaps) FORGE_PRO_CMDS.bakeMaps = ["Bake Maps (high to low)", () => ForgeBake.bake()];
