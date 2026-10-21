// Forge's UV Editing workspace (owner 2026-10-21: "give them a tab within forge like a workspace ... camera based, then
// select edges, cut, select UV shell, unfold and layout, make sure you have settings, everything modular, a real
// system"). Workspace: Modeling | UV Editing, top right of Forge (like the pro tool's workspace picker). UV Editing
// opens the UV Editor beside the viewport (its left edge drags to resize, in %), with:
//   - Create UVs: Camera-based (what the viewport sees), Planar (best plane / X / Y / Z), Cylindrical, Spherical,
//     Automatic (3 / 4 / 6 planes) - on the selected faces, or all
//   - Cut / Sew / Move and Sew on the edges selected in the viewport (F10 edges)
//   - Unfold (C++: LSCM + area-preserving optimisation, pins kept) and Layout (C++: shell packing into 0-1)
//   - select faces / shells (double-click) / UV points in the editor, move (w) / rotate (e) / scale (r) them by
//     dragging, flip, rotate 90, pin / unpin, texel density get / set, a checker on the model, distortion shading
// Every number is a setting (the gear), remembered per viewer. Every change is one undo step (it goes through the
// cage, like any modelling step). The model is app/ui/forge_uv.js, the maths native/sculpt (uv_unwrap.cpp).
"use strict";

const FORGE_UV_STORE = "loki-forge-uv", FORGE_WS_STORE = "loki-forge-workspace";
const FORGE_UV_DEFAULTS = {
  unfoldIterations: 6, unfoldWorldScale: true,
  layoutPadding: 4, layoutResolution: 1024, layoutRotate: 1, layoutScale: 1, layoutMargin: 0.005,
  autoPlanes: 6, planarAxis: "best", cylAxis: "y",
  density: 512, densityRes: 1024,
  checkerTiles: 8, showDistortion: false, showChecker: false, showGrid: true,
  // Smart Unwrap (UVgami's seam logic, app/ui/forge_uvgami.js)
  optcutsBudget: 20, smartMode: "auto", smartAngle: 66, smartPriority: "BALANCED", smartSymmetry: false, smartSymAxis: "x", smartStack: false, smartRectify: true,
};

function forgeUvSettings() {
  let s = {};
  try { s = JSON.parse(localStorage.getItem(FORGE_UV_STORE) || "{}") || {}; } catch (_) { s = {}; }
  return Object.assign({}, FORGE_UV_DEFAULTS, s);
}
function forgeUvSaveSettings(s) { try { localStorage.setItem(FORGE_UV_STORE, JSON.stringify(s)); } catch (_) { /* private window */ } }

const ForgeUVEditor = (() => {
  const S = { view: null, panel: null, canvas: null, ctx: null, status: null, tool: "move", mode: "face",
    cam: { u: 0.5, v: 0.5, z: 0 }, selUV: new Set(), drag: null, hover: false, lastPoly: null, lastSel: "", checkerTex: null, matKeep: null };
  const say = (t, bad) => { if (typeof forgeSay === "function") forgeSay(t, bad); if (S.status) { S.status.textContent = t; S.status.classList.toggle("bad", !!bad); } };
  const U = () => window.ForgeUV;
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const poly = () => (S.view && S.view.poly) || null;
  const selFaces = () => { const v = S.view; return v && v.edit && v.mode === "poly" ? [...v.edit.sel.f] : []; };

  // ---------------------------------------------------------------- committing a change (one undo step)
  function commit(next, label, keepFaces, base) {
    const v = S.view; if (!v || !next) return false;
    // an engine answer that arrives after the mesh changed (an undo, another step) must not overwrite it
    if (base && poly() !== base) { say("The mesh changed while that ran - nothing applied; run it again.", true); return false; }
    const faces = keepFaces || selFaces();
    if (poly() && poly().uvPins) next.uvPins = poly().uvPins.filter((i) => i < next.uv.length);
    v.showPoly(next, true);
    if (faces.length && v.select) v.select(faces);
    if (v.mode !== "poly" && typeof forgeModelMode === "function") { /* keep the user's mode */ }
    applyChecker();
    draw();
    if (label) say(label);
    return true;
  }
  function need(withUV) {
    const m = poly();
    if (!m) { say("UVs work on a modelled mesh: Create a primitive, or DynaMesh / Quad Remesh a sculpt first.", true); return null; }
    if (withUV && !U().has(m)) { say("No UVs yet: Create UVs first (Camera-based, Planar, Automatic ...).", true); return null; }
    return m;
  }

  // ---------------------------------------------------------------- the operations (also the commands)
  const OPS = {
    camera() {
      const m = need(false); if (!m) return;
      const v = S.view, THREE = v.THREE;
      v.camera.updateMatrixWorld(); v.holder.updateMatrixWorld();
      const M = new THREE.Matrix4().multiplyMatrices(v.camera.projectionMatrix, v.camera.matrixWorldInverse).multiply(v.holder.matrixWorld);
      const r = v.canvas.getBoundingClientRect(), aspect = r.width / (r.height || 1), p = new THREE.Vector3();
      const next = U().camera(m, selFaces(), (q) => { p.set(q[0], q[1], q[2]).applyMatrix4(M); return [p.x * aspect, p.y]; });
      commit(next, "Camera-based projection: what the view sees, on " + (selFaces().length || "every") + " face(s).");
    },
    planar(axis) { const m = need(false); if (!m) return; const a = axis || forgeUvSettings().planarAxis; commit(U().planar(m, selFaces(), a), "Planar projection (" + (a === "best" ? "best plane" : a.toUpperCase()) + ")."); },
    cylindrical() { const m = need(false); if (!m) return; commit(U().cylindrical(m, selFaces(), forgeUvSettings().cylAxis), "Cylindrical projection."); },
    spherical() { const m = need(false); if (!m) return; commit(U().spherical(m, selFaces()), "Spherical projection."); },
    async automatic() {
      const m = need(false); if (!m) return;
      const st = forgeUvSettings();
      let next = U().automatic(m, selFaces(), st.autoPlanes);
      try { next = await U().layout(next, selFaces(), layoutOpts()); } catch (e) { say("Automatic made the shells; Layout could not run: " + e.message, true); }
      commit(next, "Automatic: " + U().shells(next).length + " shells, laid out.", null, m);
    },
    cut() {
      const m = need(true); if (!m) return;
      const pairs = S.view.edgePairs ? S.view.edgePairs() : [];
      if (!pairs.length) { say("Select edges in the viewport first (F10, then click edges), then Cut.", true); return; }
      const next = U().cut(m, pairs), n0 = U().shells(m).length, n1 = U().shells(next).length;
      commit(next, "Cut " + pairs.length + " edge(s)" + (n1 > n0 ? ": " + (n1 - n0) + " new shell(s)." : " (a cut opens the shell once it reaches a border or another seam)."));
    },
    sew() {
      const m = need(true); if (!m) return;
      const pairs = S.view.edgePairs ? S.view.edgePairs() : [];
      if (!pairs.length) { say("Select the edges to sew in the viewport first.", true); return; }
      commit(U().sew(m, pairs), "Sewed " + pairs.length + " edge(s).");
    },
    moveSew() {
      const m = need(true); if (!m) return;
      const pairs = S.view.edgePairs ? S.view.edgePairs() : [];
      if (!pairs.length) { say("Select the edges to sew in the viewport first.", true); return; }
      commit(U().moveAndSew(m, pairs), "Moved and sewed " + pairs.length + " edge(s).");
    },
    async unfold() {
      const m = need(true); if (!m) return;
      const st = forgeUvSettings();
      say("Unfolding...");
      try {
        const next = await U().unfold(m, selFaces(), { iterations: st.unfoldIterations, pinned: new Set(m.uvPins || []), scaleToDensity: 1 });
        const i = next.uvInfo || {};
        commit(next, "Unfolded " + i.shells + " shell(s) in " + Math.round(i.ms || 0) + " ms" + (i.flips ? ", " + i.flips + " flipped triangle(s) left" : ", no flips") + ".", null, m);
      } catch (e) { say("Unfold: " + e.message + (window.ForgeGeom && ForgeGeom.lastError ? " (" + ForgeGeom.lastError + ")" : ""), true); }
    },
    async layout() {
      const m = need(true); if (!m) return;
      say("Laying out...");
      try { const next = await U().layout(m, selFaces(), layoutOpts()); commit(next, "Layout: " + (next.uvInfo || {}).shells + " shell(s) packed into 0-1" + ((next.uvInfo || {}).basic ? " (basic packer - the C++ engine is not in this build)." : "."), null, m); }
      catch (e) { say("Layout: " + e.message + (window.ForgeGeom && ForgeGeom.lastError ? " (" + ForgeGeom.lastError + ")" : ""), true); }
    },
    // Smart Unwrap: seams placed by UVgami's rules (hard edges, cylinders, sweeps, symmetry ...), cut, flattened by the
    // C++ unfold (UVgami's own rigid unfold when the engine build has none), split / straightened / stacked, then Layout
    async smart() {
      const m = need(false); if (!m) return;
      if (typeof window.ForgeUVgami === "undefined") { say("Smart Unwrap is not loaded.", true); return; }
      const st = forgeUvSettings(), base = U().has(m) ? m : U().planar(m, [], "best");
      say("Smart Unwrap: placing seams...");
      let engine = "C++ unfold";
      const flatten = async (c) => {
        try { return await U().unfold(c, [], { iterations: st.unfoldIterations }); }
        catch (_) { engine = "rigid unfold (the C++ unfold is not in this engine build)"; return ForgeUVgami.flattenRigid(c); }
      };
      try {
        const next = await ForgeUVgami.unwrap(base, { surfaceMode: st.smartMode, hardAngle: st.smartAngle, priority: st.smartPriority,
          useSymmetry: !!st.smartSymmetry, symAxes: [st.smartSymAxis], stackSimilar: !!st.smartStack, rectify: !!st.smartRectify,
          flatten, pack: (c) => U().layout(c, [], layoutOpts()) });
        const i = next.uvInfo || {};
        commit(next, "Smart Unwrap: " + U().shells(next).length + " shells, " + (i.seams || 0) + " seam edges, " + engine + ", " + Math.round(i.ms || 0) + " ms.", null, m);
      } catch (e) { say("Smart Unwrap: " + e.message, true); }
    },
    // Atlas: xatlas in C++ - fully automatic charts + unfold + packing (fast to read, slower on big meshes)
    async atlas() {
      const m = need(false); if (!m) return;
      say("Atlas: unwrapping (C++)...");
      try { const next = await U().autoAtlas(m, { opts: { padding: forgeUvSettings().layoutPadding, resolution: forgeUvSettings().layoutResolution } });
        commit(next, "Atlas: " + next.uvInfo.charts + " charts in " + Math.round(next.uvInfo.ms || 0) + " ms.", null, m); }
      catch (e) { say("Atlas: " + e.message, true); }
    },
    // OptCuts: seams + unfold optimised together (C++), then Layout. Cancel = the Stop button (keeps the best map so far)
    async optcuts() {
      const m = need(false); if (!m) return;
      const st = forgeUvSettings(), bound = { LESS_STRETCH: 4.05, BALANCED: 4.2, FEWER_SEAMS: 5.0 }[st.smartPriority] || 4.2;
      say("OptCuts: optimising seams and the unfold...");
      try {
        let next = await U().optcuts(m, { distortionBound: bound, timeBudgetMs: Math.max(1, st.optcutsBudget) * 1000 },
          (p) => say("OptCuts: iteration " + p.iter + ", distortion " + (p.distortion || 0).toFixed(2) + " (aim " + bound + ")..."));
        const i = next.uvInfo;
        next = await U().layout(next, [], layoutOpts());
        commit(next, "OptCuts: " + U().shells(next).length + " shells, distortion " + (i.distortion || 0).toFixed(2) + (i.converged ? "" : " (stopped at the time limit - the best map so far)")
          + ", " + Math.round(i.ms || 0) + " ms.", null, m);
      } catch (e) { say("OptCuts: " + e.message, true); }
    },
    // Auto Seams: only the seams (cut where Smart Unwrap would), nothing flattened - then Unfold yourself
    autoSeams() {
      const m = need(false); if (!m || typeof window.ForgeUVgami === "undefined") return;
      const st = forgeUvSettings(), base = U().has(m) ? m : U().planar(m, [], "best");
      let seams = ForgeUVgami.hardSurfaceSeams(base, { surfaceMode: st.smartMode === "organic" ? "hard" : st.smartMode, hardAngle: st.smartAngle });
      if (st.smartSymmetry) seams = ForgeUVgami.symmetrySeams(base, seams, { useSymmetry: true, symAxes: [st.smartSymAxis] });
      commit(ForgeUVgami.applySeams(base, seams), "Auto Seams: " + seams.size + " seam edges placed - Unfold next.");
    },
    flipU() { xform({ scale: [-1, 1] }, "Flipped U."); },
    flipV() { xform({ scale: [1, -1] }, "Flipped V."); },
    rotCW() { xform({ rotate: -90 }, "Rotated 90 clockwise."); },
    rotCCW() { xform({ rotate: 90 }, "Rotated 90 counter-clockwise."); },
    pin() { pinSel(true); },
    unpin() { pinSel(false); },
    getDensity() {
      const m = need(true); if (!m) return;
      const st = forgeUvSettings(), d = U().density(m, selFaces(), st.densityRes);
      st.density = Math.round(d * 10) / 10; forgeUvSaveSettings(st); syncSettings();
      say("Texel density: " + st.density + " px per unit at " + st.densityRes + " px.");
    },
    setDensity() {
      const m = need(true); if (!m) return;
      const st = forgeUvSettings();
      commit(U().setDensity(m, selFaces(), st.density, st.densityRes), "Texel density set to " + st.density + " px per unit (" + st.densityRes + " px).");
    },
    selectShell() {
      const m = need(true); if (!m) return;
      const fs = selFaces(); if (!fs.length) { say("Select a face first.", true); return; }
      const all = new Set(); for (const sh of U().shells(m)) if (sh.faces.some((f) => fs.includes(f))) sh.faces.forEach((f) => all.add(f));
      selectFaces([...all], "set");
    },
    checker() { const st = forgeUvSettings(); st.showChecker = !st.showChecker; forgeUvSaveSettings(st); applyChecker(); syncSettings(); say(st.showChecker ? "Checker on the model." : "Checker off."); },
    distortion() { const st = forgeUvSettings(); st.showDistortion = !st.showDistortion; forgeUvSaveSettings(st); draw(); syncSettings(); },
    frame() { frame(); },
  };
  function layoutOpts() { const st = forgeUvSettings(); return { paddingPx: st.layoutPadding, resolution: st.layoutResolution, rotate: st.layoutRotate, scaleMode: st.layoutScale, margin: st.layoutMargin }; }
  function targetUVs(m) {
    if (S.mode === "uv" && S.selUV.size) return new Set([...S.selUV].filter((i) => i < m.uv.length));
    const fs = selFaces();
    return U().uvsOfFaces(m, fs.length ? fs : m.f.map((_, i) => i));
  }
  function xform(t, label) { const m = need(true); if (!m) return; commit(U().transform(m, targetUVs(m), t), label); }
  function pinSel(on) {
    const m = need(true); if (!m) return;
    const ids = targetUVs(m), pins = new Set(m.uvPins || []);
    for (const i of ids) { if (on) pins.add(i); else pins.delete(i); }
    m.uvPins = [...pins];
    draw(); say((on ? "Pinned " : "Unpinned ") + ids.size + " UV(s). Unfold keeps pinned UVs where they are.");
  }
  function selectFaces(faces, how) {
    const v = S.view; if (!v || !v.select) return;
    if (v.mode !== "poly" && typeof forgeModelMode === "function") forgeModelMode(true);
    if (v.setSelMode && v.edit && v.edit.mode !== "face") v.setSelMode("face");
    const cur = new Set(selFaces());
    if (how === "toggle") for (const f of faces) { if (cur.has(f)) cur.delete(f); else cur.add(f); }
    else if (how === "add") for (const f of faces) cur.add(f);
    else if (how === "remove") for (const f of faces) cur.delete(f);
    else { cur.clear(); for (const f of faces) cur.add(f); }
    v.select([...cur]);
    draw();
  }

  // ---------------------------------------------------------------- the checker on the model
  function checkerTexture() {
    const st = forgeUvSettings(), THREE = S.view.THREE;
    const key = st.checkerTiles;
    if (S.checkerTex && S.checkerTex.userData.key === key) return S.checkerTex;
    const c = document.createElement("canvas"); c.width = c.height = 512;
    const g = c.getContext("2d"), n = Math.max(2, key | 0), t = 512 / n;
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      g.fillStyle = (x + y) % 2 ? "#3b4250" : "#c9ced8"; g.fillRect(x * t, y * t, t, t);
    }
    g.fillStyle = "#e0632a"; g.font = "bold " + Math.round(t * 0.45) + "px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if ((x + y) % 2) g.fillText(String.fromCharCode(65 + (x % 26)) + (n - y), x * t + t / 2, y * t + t / 2);
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.anisotropy = 4;
    if ("colorSpace" in tex && THREE.SRGBColorSpace) tex.colorSpace = THREE.SRGBColorSpace;
    tex.userData.key = key;
    if (S.checkerTex) S.checkerTex.dispose();
    S.checkerTex = tex; S.checkerImg = c;
    return tex;
  }
  function applyChecker() {
    const v = S.view; if (!v || !v.material) return;
    const on = forgeUvSettings().showChecker && workspace() === "uv";
    const mat = v.material;
    if (on) {
      if (!S.matKeep) S.matKeep = { map: mat.map, color: mat.color ? mat.color.clone() : null };
      mat.map = checkerTexture(); if (mat.color) mat.color.set(0xffffff); mat.needsUpdate = true;
    } else if (S.matKeep) {
      mat.map = S.matKeep.map; if (mat.color && S.matKeep.color) mat.color.copy(S.matKeep.color); mat.needsUpdate = true; S.matKeep = null;
    }
    v.dirty = true;
  }

  // ---------------------------------------------------------------- the 2D view
  function size() { const r = S.canvas.getBoundingClientRect(); return [r.width, r.height]; }
  function toPx(u, v) { const [w, h] = size(); return [w / 2 + (u - S.cam.u) * S.cam.z, h / 2 - (v - S.cam.v) * S.cam.z]; }
  function toUV(x, y) { const [w, h] = size(); return [S.cam.u + (x - w / 2) / S.cam.z, S.cam.v - (y - h / 2) / S.cam.z]; }
  function frame(all) {
    const m = poly(); const [w, h] = size();
    let b = { x0: 0, y0: 0, x1: 1, y1: 1 };
    if (m && U().has(m)) {
      const fs = all ? [] : selFaces();
      const ids = fs.length ? U().uvsOfFaces(m, fs) : new Set(m.uv.map((_, i) => i));
      const bb = U().bbox(m, ids);
      if (isFinite(bb.x0)) b = { x0: Math.min(bb.x0, fs.length ? bb.x0 : 0), y0: Math.min(bb.y0, fs.length ? bb.y0 : 0), x1: Math.max(bb.x1, fs.length ? bb.x1 : 1), y1: Math.max(bb.y1, fs.length ? bb.y1 : 1) };
    }
    const span = Math.max(b.x1 - b.x0, b.y1 - b.y0, 1e-4);
    S.cam = { u: (b.x0 + b.x1) / 2, v: (b.y0 + b.y1) / 2, z: Math.max(10, (Math.min(w, h) * 0.86) / span) };
    draw();
  }
  function draw() {
    if (!S.canvas || S.panel.hidden) return;
    const c = S.canvas, g = S.ctx, dpr = window.devicePixelRatio || 1, [w, h] = size();
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
    if (!S.cam.z) { S.cam.z = 1; frame(true); return; }
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = "#232427"; g.fillRect(0, 0, w, h);
    const st = forgeUvSettings();
    const [ax, ay] = toPx(0, 1), [bx, by] = toPx(1, 0);
    // the 0-1 tile: the checker image when it is on the model, else a lighter square + grid
    if (st.showChecker && S.checkerImg) { g.globalAlpha = 0.55; g.drawImage(S.checkerImg, ax, ay, bx - ax, by - ay); g.globalAlpha = 1; }
    else { g.fillStyle = "#2c2e33"; g.fillRect(ax, ay, bx - ax, by - ay); }
    if (st.showGrid) {
      g.strokeStyle = "rgba(255,255,255,.06)"; g.lineWidth = 1; g.beginPath();
      const step = S.cam.z > 1600 ? 0.025 : S.cam.z > 500 ? 0.1 : 0.25;
      const [u0, v1] = toUV(0, 0), [u1, v0] = toUV(w, h);
      for (let u = Math.floor(u0 / step) * step; u <= u1; u += step) { const [x] = toPx(u, 0); g.moveTo(Math.round(x) + 0.5, 0); g.lineTo(Math.round(x) + 0.5, h); }
      for (let v = Math.floor(v0 / step) * step; v <= v1; v += step) { const [, y] = toPx(0, v); g.moveTo(0, Math.round(y) + 0.5); g.lineTo(w, Math.round(y) + 0.5); }
      g.stroke();
    }
    g.strokeStyle = "rgba(120,170,230,.8)"; g.lineWidth = 1.5; g.strokeRect(ax, ay, bx - ax, by - ay);
    const m = poly();
    if (!m) { g.fillStyle = "#8b9099"; g.font = "13px sans-serif"; g.textAlign = "center"; g.fillText("Create a primitive (or remesh a sculpt) to edit its UVs.", w / 2, h / 2); updateInfo(); return; }
    if (!U().has(m)) { g.fillStyle = "#8b9099"; g.font = "13px sans-serif"; g.textAlign = "center"; g.fillText("No UVs yet - Create UVs: Camera-based, Planar or Automatic.", w / 2, h / 2); updateInfo(); return; }
    const sel = new Set(selFaces()), dist = st.showDistortion ? U().distortion(m) : null, fresh = new Set(m.uvNew || []);
    // faces
    m.fuv.forEach((cix, fi) => {
      g.beginPath();
      cix.forEach((i, k) => { const [x, y] = toPx(m.uv[i][0], m.uv[i][1]); if (k) g.lineTo(x, y); else g.moveTo(x, y); });
      g.closePath();
      if (dist) {
        const d = dist[fi];
        if (d.flipped) g.fillStyle = "rgba(230,40,40,.55)";
        else { const t = Math.max(-1, Math.min(1, Math.log2(d.stretch || 1e-6) / 2)); g.fillStyle = t > 0 ? "rgba(235,90,60," + (0.15 + 0.5 * t) + ")" : "rgba(70,130,240," + (0.15 - 0.5 * t) + ")"; }
        g.fill();
      } else if (fresh.has(fi)) { g.fillStyle = "rgba(240,200,60,.22)"; g.fill(); }
      else { g.fillStyle = "rgba(150,170,200,.07)"; g.fill(); }
      if (sel.has(fi)) { g.fillStyle = "rgba(255,138,26,.38)"; g.fill(); }
    });
    // edges: inner edges thin, shell borders (seams + open borders) thicker
    const E = U().edges(m);
    g.lineWidth = 1; g.strokeStyle = "rgba(170,190,215,.55)"; g.beginPath();
    const borders = [];
    for (const e of E.values()) for (const u of e.uses) {
      const f = m.f[u.fi], c = m.fuv[u.fi], k1 = (u.k + 1) % f.length;
      const p = m.uv[c[u.k]], q = m.uv[c[k1]];
      if (e.seam) { borders.push([p, q]); continue; }
      const [x0, y0] = toPx(p[0], p[1]), [x1, y1] = toPx(q[0], q[1]); g.moveTo(x0, y0); g.lineTo(x1, y1);
    }
    g.stroke();
    g.lineWidth = 2; g.strokeStyle = "rgba(235,240,248,.95)"; g.beginPath();
    for (const [p, q] of borders) { const [x0, y0] = toPx(p[0], p[1]), [x1, y1] = toPx(q[0], q[1]); g.moveTo(x0, y0); g.lineTo(x1, y1); }
    g.stroke();
    // UV points: selected ones, and pins
    const pins = new Set(m.uvPins || []);
    if (S.mode === "uv" || pins.size) {
      for (let i = 0; i < m.uv.length; i++) {
        const isSel = S.mode === "uv" && S.selUV.has(i), isPin = pins.has(i);
        if (!isSel && !isPin && S.mode !== "uv") continue;
        const [x, y] = toPx(m.uv[i][0], m.uv[i][1]);
        g.fillStyle = isPin ? "#ff4fd8" : isSel ? "#ffd52e" : "rgba(169,79,209,.9)";
        g.fillRect(x - (isSel || isPin ? 3 : 2), y - (isSel || isPin ? 3 : 2), isSel || isPin ? 6 : 4, isSel || isPin ? 6 : 4);
      }
    }
    if (S.drag && S.drag.box) {
      const b = S.drag.box; g.strokeStyle = "rgba(255,255,255,.8)"; g.setLineDash([4, 3]); g.lineWidth = 1;
      g.strokeRect(Math.min(b[0], b[2]) + 0.5, Math.min(b[1], b[3]) + 0.5, Math.abs(b[2] - b[0]), Math.abs(b[3] - b[1])); g.setLineDash([]);
    }
    updateInfo();
  }
  function updateInfo() {
    const box = S.panel && S.panel.querySelector(".fuv-info"); if (!box) return;
    const m = poly();
    if (!m || !U().has(m)) { box.textContent = m ? "No UVs" : "No modelled mesh"; return; }
    const st = forgeUvSettings(), sh = U().shells(m), dist = U().distortion(m), flips = dist.filter((d) => d.flipped).length;
    box.textContent = sh.length + " shell" + (sh.length === 1 ? "" : "s") + " · " + m.uv.length + " UVs · " + selFaces().length + " faces sel."
      + " · " + Math.round(U().density(m, selFaces(), st.densityRes)) + " px/u" + (flips ? " · " + flips + " flipped" : "")
      + (U().overlapCount(m) ? " · shells overlap" : "") + ((m.uvNew || []).length ? " · " + m.uvNew.length + " new faces need UVs" : "");
  }

  // ---------------------------------------------------------------- picking in the 2D view
  function inPoly(pt, pts) {
    let ins = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const [xi, yi] = pts[i], [xj, yj] = pts[j];
      if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi || 1e-12) + xi) ins = !ins;
    }
    return ins;
  }
  function faceAt(x, y) {
    const m = poly(); if (!m || !U().has(m)) return -1;
    const p = toUV(x, y);
    for (let fi = m.fuv.length - 1; fi >= 0; fi--) if (inPoly(p, m.fuv[fi].map((i) => m.uv[i]))) return fi;
    return -1;
  }
  function uvAt(x, y, r) {
    const m = poly(); if (!m || !U().has(m)) return -1;
    let best = -1, bd = (r || 7) * (r || 7);
    m.uv.forEach((q, i) => { const [px, py] = toPx(q[0], q[1]); const d = (px - x) * (px - x) + (py - y) * (py - y); if (d < bd) { bd = d; best = i; } });
    return best;
  }
  const how = (e) => (e.shiftKey && (e.ctrlKey || e.metaKey) ? "add" : e.ctrlKey || e.metaKey ? "remove" : e.shiftKey ? "toggle" : "set");

  function onDown(e) {
    const r = S.canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    S.canvas.setPointerCapture(e.pointerId);
    if (e.button === 1 || (e.altKey && e.button === 0)) { S.drag = { pan: true, x, y, u: S.cam.u, v: S.cam.v }; e.preventDefault(); return; }
    if (e.altKey && e.button === 2) { S.drag = { zoom: true, x, y, z: S.cam.z }; e.preventDefault(); return; }
    if (e.button !== 0) return;
    const m = poly();
    const onSel = (() => {
      if (!m || !U().has(m)) return false;
      if (S.mode === "uv") { const i = uvAt(x, y); return i >= 0 && S.selUV.has(i); }
      const fi = faceAt(x, y); return fi >= 0 && selFaces().includes(fi);
    })();
    if (onSel && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      const ids = targetUVs(m), b = U().bbox(m, ids);
      S.drag = { xf: S.tool, x, y, ids, start: m, pivot: [b.cx, b.cy], uv0: toUV(x, y) };
      return;
    }
    S.drag = { box: [x, y, x, y], how: how(e), click: true };
  }
  function onMove(e) {
    const r = S.canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const d = S.drag; if (!d) return;
    if (d.pan) { S.cam.u = d.u - (x - d.x) / S.cam.z; S.cam.v = d.v + (y - d.y) / S.cam.z; draw(); return; }
    if (d.zoom) { S.cam.z = Math.max(10, d.z * Math.pow(1.01, (x - d.x) - (y - d.y))); draw(); return; }
    if (d.box) { d.box[2] = x; d.box[3] = y; if (Math.abs(x - d.box[0]) + Math.abs(y - d.box[1]) > 4) d.click = false; draw(); return; }
    if (d.xf) {
      const [u, v] = toUV(x, y);
      let t;
      if (d.xf === "rotate") t = { rotate: (x - d.x) * 0.5, pivot: d.pivot };
      else if (d.xf === "scale") { const k = Math.max(0.01, Math.pow(1.01, x - d.x)); t = { scale: [k, k], pivot: d.pivot }; }
      else { let du = u - d.uv0[0], dv = v - d.uv0[1]; if (e.shiftKey) { if (Math.abs(du) > Math.abs(dv)) dv = 0; else du = 0; } t = { move: [du, dv] }; }
      if (forgeUvSettings().snapPixels && d.xf === "move") { const px = 1 / forgeUvSettings().layoutResolution; t.move = t.move.map((q) => Math.round(q / px) * px); }
      d.live = U().transform(d.start, d.ids, t);
      // live: the editor draws the moved UVs; the model's GPU mesh too (UVs only)
      S.view.poly = d.live; draw(); S.view.poly = d.start;
      liveGpu(d.live);
    }
  }
  function liveGpu(m) {
    const v = S.view, mesh = v.meshObj && v.meshObj(), cuv = U().cornerUVs(m);
    if (!mesh || !cuv || !mesh.geometry.attributes.uv || mesh.geometry.attributes.uv.array.length !== cuv.length) return;
    mesh.geometry.attributes.uv.array.set(cuv); mesh.geometry.attributes.uv.needsUpdate = true; v.dirty = true;
  }
  function onUp(e) {
    const d = S.drag; S.drag = null;
    if (!d) return;
    if (d.xf) {
      if (d.live) { commit(d.live, { move: "Moved", rotate: "Rotated", scale: "Scaled" }[d.xf] + " " + d.ids.size + " UV(s)."); return; }
      d.box = [d.x, d.y, d.x, d.y]; d.click = true; d.how = how(e);   // pressed on the selection without moving: a click
    }
    if (d.box) {
      const m = poly(); if (!m || !U().has(m)) { draw(); return; }
      if (d.click) {
        const r = S.canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, now = performance.now();
        // a second click in the same place soon after = the shell (our own double-click: pointer capture can eat dblclick)
        const L = S.lastClick;
        if (L && now - L.t < 400 && Math.abs(L.x - x) < 6 && Math.abs(L.y - y) < 6) { S.lastClick = null; onDbl(e); return; }
        S.lastClick = { t: now, x, y };
        if (S.mode === "uv") { const i = uvAt(x, y); pickUVs(i >= 0 ? [i] : [], d.how); }
        else { const fi = faceAt(x, y); selectFaces(fi >= 0 ? [fi] : [], d.how); }
      } else {
        const [x0, x1] = [Math.min(d.box[0], d.box[2]), Math.max(d.box[0], d.box[2])], [y0, y1] = [Math.min(d.box[1], d.box[3]), Math.max(d.box[1], d.box[3])];
        const inside = (q) => { const [px, py] = toPx(q[0], q[1]); return px >= x0 && px <= x1 && py >= y0 && py <= y1; };
        if (S.mode === "uv") pickUVs(m.uv.map((q, i) => (inside(q) ? i : -1)).filter((i) => i >= 0), d.how);
        else selectFaces(m.fuv.map((c, fi) => (c.some((i) => inside(m.uv[i])) && inside(centroidUV(m, fi)) ? fi : -1)).filter((fi) => fi >= 0), d.how);
      }
      draw();
    }
  }
  function centroidUV(m, fi) { const c = m.fuv[fi]; let u = 0, v = 0; for (const i of c) { u += m.uv[i][0]; v += m.uv[i][1]; } return [u / c.length, v / c.length]; }
  function pickUVs(ids, h) {
    if (h === "set") S.selUV = new Set(ids);
    else for (const i of ids) { if (h === "remove" || (h === "toggle" && S.selUV.has(i))) S.selUV.delete(i); else S.selUV.add(i); }
    draw();
  }
  function onDbl(e) {
    const r = S.canvas.getBoundingClientRect(), fi = faceAt(e.clientX - r.left, e.clientY - r.top), m = poly();
    if (fi < 0 || !m) return;
    const sh = U().shells(m).find((s) => s.faces.includes(fi));
    if (!sh) return;
    if (S.mode === "uv") pickUVs([...sh.uvs], e.shiftKey ? "add" : "set");
    else selectFaces(sh.faces, e.shiftKey ? "add" : "set");
    say("Shell: " + sh.faces.length + " face(s).");
  }
  function onWheel(e) {
    e.preventDefault();
    const r = S.canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, before = toUV(x, y);
    S.cam.z = Math.max(10, Math.min(200000, S.cam.z * Math.pow(1.0015, -e.deltaY)));
    const after = toUV(x, y); S.cam.u += before[0] - after[0]; S.cam.v += before[1] - after[1];
    draw();
  }

  // ---------------------------------------------------------------- the panel
  function iconBtn(label, tip, fn, id) {
    const b = el("button", "fuv-btn", label); b.type = "button"; b.title = tip; b.dataset.tipName = label; b.dataset.tipWhat = tip;
    if (id) b.dataset.op = id;
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
    return b;
  }
  function group(name, kids) { const g = el("div", "fuv-group"); g.append(el("span", "fuv-glabel", name), ...kids); return g; }
  function settingRow(label, key, kind, opt) {
    const r = el("label", "fuv-set-row"); r.append(el("span", "", label));
    let inp;
    if (kind === "select") { inp = el("select"); for (const [v, t] of opt) { const o = el("option", "", t); o.value = String(v); inp.append(o); } }
    else if (kind === "bool") { inp = el("input"); inp.type = "checkbox"; }
    else { inp = el("input"); inp.type = "number"; Object.assign(inp, opt || {}); }
    inp.dataset.key = key;
    inp.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter" || e.key === "Escape") inp.blur(); });
    inp.addEventListener("change", () => {
      const st = forgeUvSettings(), d = FORGE_UV_DEFAULTS[key];
      st[key] = kind === "bool" ? inp.checked : typeof d === "number" ? (isFinite(+inp.value) ? +inp.value : d) : inp.value;
      forgeUvSaveSettings(st);
      if (key === "checkerTiles" || key === "showChecker") applyChecker();
      draw();
    });
    r.append(inp);
    return r;
  }
  function syncSettings() {
    if (!S.panel) return;
    const st = forgeUvSettings();
    for (const inp of S.panel.querySelectorAll("[data-key]")) {
      const v = st[inp.dataset.key];
      if (inp.type === "checkbox") inp.checked = !!v; else if (document.activeElement !== inp) inp.value = String(v);
    }
    for (const b of S.panel.querySelectorAll("[data-tool]")) b.classList.toggle("on", b.dataset.tool === S.tool);
    for (const b of S.panel.querySelectorAll("[data-mode]")) b.classList.toggle("on", b.dataset.mode === S.mode);
    const ck = S.panel.querySelector('[data-op="checker"]'); if (ck) ck.classList.toggle("on", !!st.showChecker);
    const ds = S.panel.querySelector('[data-op="distortion"]'); if (ds) ds.classList.toggle("on", !!st.showDistortion);
  }
  function build() {
    const body = document.querySelector("#forge .forge-body");
    if (!body || document.getElementById("forge-uvpanel")) return document.getElementById("forge-uvpanel");
    const p = el("aside", "forge-uvpanel"); p.id = "forge-uvpanel"; p.hidden = true;
    const head = el("div", "fuv-head");
    head.append(el("span", "fuv-title", "UV Editor"));
    const tb = el("div", "fuv-toolbar");
    const toolBtn = (t, label, tip) => { const b = iconBtn(label, tip, () => { S.tool = t; syncSettings(); }); b.dataset.tool = t; return b; };
    const modeBtn = (md, label, tip) => { const b = iconBtn(label, tip, () => { S.mode = md; syncSettings(); draw(); }); b.dataset.mode = md; return b; };
    tb.append(
      group("Select", [modeBtn("face", "Face", "Select faces (the viewport's face selection, kept in step). Double-click: the whole shell."),
        modeBtn("uv", "UV", "Select UV points (to pin, or move single UVs).")]),
      group("Tool", [toolBtn("move", "Move", "Drag selected UVs to move them (w). Shift: along one axis."), toolBtn("rotate", "Rotate", "Drag sideways to rotate the selection about its centre (e)."),
        toolBtn("scale", "Scale", "Drag sideways to scale the selection about its centre (r).")]),
      group("Create", [iconBtn("Camera", "Camera-based: project the selected faces (or all) as the viewport sees them.", OPS.camera, "camera"),
        iconBtn("Planar", "Planar projection on the best plane (Settings: or X / Y / Z).", () => OPS.planar(), "planar"),
        iconBtn("Cyl", "Cylindrical projection around the axis in Settings.", OPS.cylindrical, "cylindrical"),
        iconBtn("Sph", "Spherical projection.", OPS.spherical, "spherical"),
        iconBtn("Auto", "Automatic: one shell per facing direction (Settings: 3 / 4 / 6 planes), then Layout.", OPS.automatic, "automatic"),
        iconBtn("Atlas", "Atlas: a fully automatic unwrap (charts, seams, unfold and packing) by the C++ engine.", () => OPS.atlas(), "atlas"),
        iconBtn("OptCuts", "OptCuts: the shortest seams that keep stretch under the Priority's bound, unfolded together, no overlaps (C++; Stop keeps the best so far).", () => OPS.optcuts(), "optcuts"),
        iconBtn("Stop", "Stop OptCuts (keeps the best map found so far).", () => U().optcutsCancel()),
        iconBtn("Smart", "Smart Unwrap: seams where a texture artist would put them (hard edges, cylinders, symmetry), cut, unfold, straighten, layout - one click.", () => OPS.smart(), "smart")]),
      group("Cut & Sew", [iconBtn("Seams", "Auto Seams: only place the seams (Smart Unwrap's rules), then Unfold yourself.", () => OPS.autoSeams(), "autoSeams"), iconBtn("Cut", "Cut the edges selected in the viewport: they become UV seams.", OPS.cut, "cut"),
        iconBtn("Sew", "Sew the selected edges: the two sides become one again.", OPS.sew, "sew"),
        iconBtn("Move+Sew", "Move the smaller shell onto the bigger one, then sew.", OPS.moveSew, "moveSew")]),
      group("Unfold", [iconBtn("Unfold", "Unfold the selected shells (or all): flat, with little stretch (C++). Pinned UVs stay put.", OPS.unfold, "unfold"),
        iconBtn("Layout", "Pack the shells into the 0-1 square (C++; padding, rotation and scale in Settings).", OPS.layout, "layout")]),
      group("Arrange", [iconBtn("⟲90", "Rotate 90 counter-clockwise.", OPS.rotCCW), iconBtn("⟳90", "Rotate 90 clockwise.", OPS.rotCW),
        iconBtn("Flip U", "Flip horizontally.", OPS.flipU), iconBtn("Flip V", "Flip vertically.", OPS.flipV),
        iconBtn("Pin", "Pin the selected UVs (Unfold keeps them).", OPS.pin, "pin"), iconBtn("Unpin", "Unpin the selected UVs.", OPS.unpin)]),
      group("Density", [iconBtn("Get", "Read the texel density of the selection into Settings.", OPS.getDensity), iconBtn("Set", "Scale each selected shell to the texel density in Settings.", OPS.setDensity)]),
      group("Show", [iconBtn("Checker", "A checker texture on the model, to see stretch and seams.", OPS.checker, "checker"),
        iconBtn("Distort", "Shade the UVs by stretch: blue = squashed, red = stretched, bright red = flipped.", OPS.distortion, "distortion"),
        iconBtn("Frame", "Frame the selection, or everything (f over the editor).", () => frame())]),
    );
    const gear = iconBtn("⚙", "Settings: unfold, layout, projections, density, checker.", () => { set.hidden = !set.hidden; });
    gear.id = "forge-uv-gear";
    head.append(tb, gear);
    const set = el("div", "fuv-settings"); set.hidden = true;
    const sec = (name, rows) => { const d = el("div", "fuv-sec"); d.append(el("div", "fuv-sec-title", name), ...rows); return d; };
    set.append(
      sec("Unfold", [settingRow("Optimise iterations", "unfoldIterations", "num", { min: 0, max: 50, step: 1 })]),
      sec("Smart Unwrap", [settingRow("Surface", "smartMode", "select", [["auto", "Auto (per part)"], ["hard", "Hard surface"], ["organic", "Organic"]]),
        settingRow("Hard edge angle", "smartAngle", "num", { min: 1, max: 179, step: 1 }),
        settingRow("Priority", "smartPriority", "select", [["BALANCED", "Balanced"], ["LESS_STRETCH", "Less stretch"], ["FEWER_SEAMS", "Fewer seams"]]),
        settingRow("Symmetry", "smartSymmetry", "bool"), settingRow("Symmetry axis", "smartSymAxis", "select", [["x", "X"], ["y", "Y"], ["z", "Z"]]),
        settingRow("OptCuts time limit (s)", "optcutsBudget", "num", { min: 1, max: 600, step: 1 }),
        settingRow("Stack identical pieces", "smartStack", "bool"), settingRow("Straighten strips", "smartRectify", "bool")]),
      sec("Layout", [settingRow("Padding (px)", "layoutPadding", "num", { min: 0, max: 64, step: 1 }),
        settingRow("Texture size (px)", "layoutResolution", "select", [[256, "256"], [512, "512"], [1024, "1024"], [2048, "2048"], [4096, "4096"], [8192, "8192"]]),
        settingRow("Rotate shells", "layoutRotate", "select", [[0, "No"], [1, "90 degree steps"], [2, "Free (tightest)"]]),
        settingRow("Scale shells", "layoutScale", "select", [[1, "Uniform texel density"], [0, "Keep their sizes"], [2, "Do not scale"]]),
        settingRow("Border margin (0-1)", "layoutMargin", "num", { min: 0, max: 0.2, step: 0.001 })]),
      sec("Projections", [settingRow("Planar axis", "planarAxis", "select", [["best", "Best plane"], ["x", "X"], ["y", "Y"], ["z", "Z"]]),
        settingRow("Cylinder axis", "cylAxis", "select", [["y", "Y"], ["x", "X"], ["z", "Z"]]),
        settingRow("Automatic planes", "autoPlanes", "select", [[6, "6 (box)"], [4, "4"], [3, "3"]])]),
      sec("Texel density", [settingRow("Pixels per unit", "density", "num", { min: 1, max: 100000, step: 1 }),
        settingRow("At texture size (px)", "densityRes", "select", [[512, "512"], [1024, "1024"], [2048, "2048"], [4096, "4096"]])]),
      sec("Display", [settingRow("Checker tiles", "checkerTiles", "num", { min: 2, max: 64, step: 1 }), settingRow("Grid", "showGrid", "bool"),
        settingRow("Snap moves to pixels", "snapPixels", "bool")]),
    );
    const cv = el("canvas", "fuv-canvas"); cv.id = "forge-uv-canvas"; cv.tabIndex = 0;
    const info = el("div", "fuv-info"); const status = el("div", "fuv-status");
    const stage = el("div", "fuv-stage"); stage.append(cv);   // the canvas fills a box (its own size never drives the layout)
    p.append(head, set, stage, info, status);
    const chan = document.getElementById("forge-chancol");
    if (chan && chan.parentElement === body) body.insertBefore(p, chan); else body.append(p);
    S.panel = p; S.canvas = cv; S.ctx = cv.getContext("2d"); S.status = status;
    cv.addEventListener("pointerdown", onDown); cv.addEventListener("pointermove", onMove); cv.addEventListener("pointerup", onUp);
    cv.addEventListener("pointercancel", () => { S.drag = null; draw(); });
    cv.addEventListener("wheel", onWheel, { passive: false });   // double-click: onUp (two clicks in one place)
    cv.addEventListener("contextmenu", (e) => e.preventDefault());
    p.addEventListener("pointerenter", () => { S.hover = true; }); p.addEventListener("pointerleave", () => { S.hover = false; });
    // keys over the editor: q / w / e / r tools, f frame - before Forge's own hotkeys
    document.addEventListener("keydown", (e) => {
      if (!S.hover || p.hidden || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
      const k = e.key.toLowerCase();
      const act = { w: () => { S.tool = "move"; }, e: () => { S.tool = "rotate"; }, r: () => { S.tool = "scale"; }, q: () => { S.tool = "move"; }, f: () => frame(e.shiftKey) }[k];
      if (!act) return;
      e.preventDefault(); e.stopImmediatePropagation(); act(); syncSettings();
    }, true);
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(() => draw()).observe(stage);
    syncSettings();
    return p;
  }

  // ---------------------------------------------------------------- workspaces: Modeling | UV Editing
  function workspace() { try { return localStorage.getItem(FORGE_WS_STORE) || "model"; } catch (_) { return "model"; } }
  function setWorkspace(ws) {
    try { localStorage.setItem(FORGE_WS_STORE, ws); } catch (_) { /* private window */ }
    const p = build(); if (!p) return "";
    p.hidden = ws !== "uv";
    const pick = document.getElementById("forge-workspace"); if (pick && pick.value !== ws) pick.value = ws;
    let note = "";
    if (typeof ForgeRetopo !== "undefined") {           // Retopology: Quad Draw on, everywhere else off
      if (ws === "retopo" && !ForgeRetopo.state.on) note = ForgeRetopo.start();
      else if (ws !== "retopo" && ForgeRetopo.state.on) ForgeRetopo.stop();
    }
    if (typeof ForgeBake !== "undefined") ForgeBake.show(ws === "bake");
    document.querySelector("#forge .forge-body")?.classList.toggle("ws-uv", ws === "uv");
    if (typeof forgeSplitAttach === "function") forgeSplitAttach();   // its drag edge (forge_split.js)
    applyChecker();
    if (ws === "uv") {
      const v = S.view;
      if (v && v.poly && v.mode !== "poly" && typeof forgeModelMode === "function") forgeModelMode(true);
      requestAnimationFrame(() => { if (!S.cam.z || S.cam.z < 11) frame(true); else draw(); });
    }
    if (S.view) { S.view.dirty = true; if (S.view.resize) S.view.resize(); }
    return ws === "uv" ? "UV Editing workspace." : ws === "retopo" ? (note || "Retopology workspace: select the object to draw over, then pick Retopology again.")
      : ws === "bake" ? "Baking workspace: the edited object (with UVs) is the low; pick the high, then Bake." : "Modeling workspace.";
  }
  function workspacePicker() {
    const name = document.querySelector("#forge .fmy-wsname");
    if (!name || document.getElementById("forge-workspace")) return;
    const sel = el("select", "fmy-menuset fmy-wspick"); sel.id = "forge-workspace";
    sel.title = "Workspace: Modeling, UV Editing (the UV Editor beside the viewport) Retopology (Quad Draw on a live surface) or Baking (high to low maps).";
    for (const [v, t] of [["model", "Modeling"], ["uv", "UV Editing"], ["retopo", "Retopology"], ["bake", "Baking"]]) { const o = el("option", "", t); o.value = v; sel.append(o); }
    sel.value = workspace();
    sel.addEventListener("change", () => say(setWorkspace(sel.value)));
    name.replaceWith(sel);
  }

  // ---------------------------------------------------------------- attach to the viewer (once it exists)
  function attach(v) {
    if (S.view === v) return;
    S.view = v;
    build(); workspacePicker();
    const prev = v.onSelect;
    v.onSelect = function () { if (prev) prev.apply(this, arguments); draw(); };
    if (Array.isArray(v.frameHooks)) v.frameHooks.push(() => {   // the cage changed somewhere else (undo, a modelling step)
      if (S.panel && !S.panel.hidden && v.poly !== S.lastPoly && !S.drag) { S.lastPoly = v.poly; draw(); }
    });
    setWorkspace(workspace());
  }
  setInterval(() => { const v = typeof forge !== "undefined" && forge.view; if (v && v !== S.view && document.querySelector("#forge .forge-body")) attach(v); else if (v && !document.getElementById("forge-workspace")) workspacePicker(); }, 400);

  return { OPS, setWorkspace, workspace, draw, frame, state: S, attach, select: selectFaces, pickUVs };
})();

// the commands (menus, hotbox, the command line): uvEditor, uvCamera, uvPlanar ... uvLayout
if (typeof FORGE_PRO_CMDS !== "undefined") {
  const O = ForgeUVEditor.OPS;
  const add = (id, label, fn) => { if (!FORGE_PRO_CMDS[id]) FORGE_PRO_CMDS[id] = [label, fn]; };
  add("uvEditor", "UV Editor (UV Editing workspace)", () => ForgeUVEditor.setWorkspace(ForgeUVEditor.workspace() === "uv" ? "model" : "uv"));
  add("uvCamera", "Camera-based UVs", () => O.camera());
  add("uvPlanar", "Planar UVs", () => O.planar());
  add("uvCylindrical", "Cylindrical UVs", () => O.cylindrical());
  add("uvSpherical", "Spherical UVs", () => O.spherical());
  add("uvAutomatic", "Automatic UVs", () => O.automatic());
  add("uvCut", "Cut UV Edges", () => O.cut());
  add("uvSew", "Sew UV Edges", () => O.sew());
  add("uvMoveSew", "Move and Sew UV Edges", () => O.moveSew());
  add("uvUnfold", "Unfold", () => O.unfold());
  add("uvLayout", "Layout", () => O.layout());
  add("uvShell", "Select UV Shell", () => O.selectShell());
  add("uvSmart", "Smart Unwrap", () => O.smart());
  add("uvAutoSeams", "Auto Seams", () => O.autoSeams());
  add("uvAtlas", "Atlas Unwrap", () => O.atlas());
  add("uvOptCuts", "OptCuts Unwrap", () => O.optcuts());
  add("uvChecker", "UV Checker on the Model", () => O.checker());
}
