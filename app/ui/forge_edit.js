// Forge component mode - selecting and moving the parts of a poly mesh. the pro hands since 2026-10-19 (owner: "remove
// blender hotkeys and movements, only keep pro stuff"): F9 / F10 / F11 vertex / edge / face, click selects, Shift
// toggles, Ctrl/Cmd takes away, Ctrl/Cmd+Shift adds, a drag draws a box, a double-click on an edge takes the loop,
// w / e / r put the handle on the selection, b soft selection, Alt/Option is only ever the camera. The keys live
// in app/ui/forge_pro.js. The selection engine below is still the one re-written from Blender's (GPL-2.0+):
// (the original notes on that, kept:)
// (owner 2026-10-18: "poly modeling, vert selection, marquee selection, move tool works on faces and verts ...
// look at blender code and do that").
//
// What comes from Blender (GPL-2.0-or-later, LOKI is AGPL-3.0 - docs/THIRD_PARTY.md), re-written for a web view:
//   - three select modes, Vertex / Edge / Face (1 2 3), one selection flushed between them (editmesh_select.cc)
//   - picking from a SELECTION BUFFER: every face drawn in its own id colour off screen, so a click or a box only
//     hits what you can see (drawing the ids is what Blender's DRW_select_buffer does); X-ray (Alt+Z) selects
//     through the model instead
//   - click selects, Shift+click toggles, a click on nothing deselects; a drag draws a box (Shift adds, Ctrl
//     takes away); Alt+click selects an edge loop (a face loop in face mode); double-click selects linked
//   - the walkers (edge loop / edge ring / face loop) are bmesh_walkers_impl.cc's rules, in forge_poly.js
//   - soft selection (proportional editing) with its falloff curves; moving is the pro move / rotate / scale tools
//     (the Blender-style G / R / S modal was removed 2026-10-22: Forge is Maya-only)
//   - W shows a move handle on the selection (three.js' TransformControls, MIT) for people who think in pro
// The orbit view keeps working: middle-drag turns (Shift+middle pans), right-drag pans, Alt+left-drag turns.
"use strict";

Object.assign(ICON_PATHS, {
  selvert: '<path d="M5 19L12 5l7 14z" stroke-dasharray="2.5 2"/><rect x="10" y="3" width="4" height="4" fill="currentColor"/><rect x="3" y="17" width="4" height="4"/><rect x="17" y="17" width="4" height="4"/>',
  seledge: '<path d="M5 19L12 5" stroke-dasharray="2.5 2"/><path d="M5 19h14" stroke-dasharray="2.5 2"/><path d="M12 5l7 14" stroke-width="3"/>',
  selface: '<path d="M5 19L12 5l7 14z" fill="currentColor" fill-opacity=".45"/>',
  xray: '<rect x="4" y="4" width="11" height="11" rx="1"/><rect x="9" y="9" width="11" height="11" rx="1" stroke-dasharray="2 2"/>',
  rotate: '<path d="M19 12a7 7 0 1 1-2.05-4.95"/><path d="M19.5 4v4h-4"/>',
  scale: '<path d="M4 20l7-7M4 20v-5M4 20h5"/><path d="M20 4l-7 7M20 4v5M20 4h-5"/>',
  magnet: '<circle cx="12" cy="12" r="2.2" fill="currentColor"/><circle cx="12" cy="12" r="6" stroke-dasharray="2 2"/><circle cx="12" cy="12" r="9.5" stroke-dasharray="1.5 3"/>',
  grow: '<path d="M12 4v16M4 12h16"/>',
  shrink: '<path d="M4 12h16"/>',
  linked: '<circle cx="7" cy="12" r="3"/><circle cx="17" cy="12" r="3"/><path d="M10 12h4"/>',
  invert: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 20L20 4" /><path d="M4 4h8v8H4z" fill="currentColor" fill-opacity=".5"/>',
});

// Component display (owner 17:06: no Blender look): the mesh's edges thin and light blue, the selected ones orange,
// vertices purple dots only in vertex mode (selected yellow), selected faces a light orange tint. Nothing else.
const FORGE_SEL_COLORS = { wire: 0x86c6e6, wireSel: 0xff8a1a, vert: 0xa94fd1, vertSel: 0xffd52e };

function forgeEditAttach(view, ctx) {
  const { THREE, canvas, camera, renderer, holder, controls, material } = ctx;
  const P = window.ForgePoly;
  const KEY = { vert: "v", edge: "e", face: "f" };
  const ed = view.edit = {
    mode: "face", xray: false, prop: false, propRadius: 0.25, falloff: "smooth",
    sel: { v: new Set(), e: new Set(), f: new Set() }, topo: null, topoOf: null, mouse: null,
  };
  const topo = () => {
    if (ed.topoOf !== view.poly) { ed.topo = view.poly ? P.topology(view.poly) : null; ed.topoOf = view.poly; }
    return ed.topo;
  };
  const say = (t, bad) => { if (typeof forgeSay === "function") forgeSay(t, bad); };

  // ---------------------------------------------------------------- overlays: wire, vertices, selected faces
  const lineMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.8 });
  const pointMat = new THREE.PointsMaterial({ size: 5, sizeAttenuation: false, vertexColors: true });
  const faceMat = new THREE.MeshBasicMaterial({ color: 0xff8a1a, transparent: true, opacity: 0.3, side: THREE.DoubleSide,
    polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1, depthWrite: false });
  const over = new THREE.Group(); over.name = "forge-edit-overlay"; holder.add(over);
  let wire = null, dots = null, fill = null;
  const dispose = (o) => { if (o) { over.remove(o); o.geometry.dispose(); } };
  function drawOverlay(poly) {
    poly = poly || view.poly;
    dispose(wire); dispose(dots); dispose(fill); wire = dots = fill = null;
    const on = view.mode === "poly" && !!poly;
    over.visible = on;
    material.polygonOffset = on; material.polygonOffsetFactor = 1; material.polygonOffsetUnits = 1;
    if (!on) { view.dirty = true; return; }
    const T = topo(), s = ed.sel, c0 = new THREE.Color(FORGE_SEL_COLORS.wire), c1 = new THREE.Color(FORGE_SEL_COLORS.wireSel);
    const lp = new Float32Array(T.edges.length * 6), lc = new Float32Array(T.edges.length * 6);
    T.edges.forEach((e, i) => {
      lp.set(poly.v[e.a], i * 6); lp.set(poly.v[e.b], i * 6 + 3);
      const c = s.e.has(i) ? c1 : c0;
      lc.set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6);
    });
    const lg = new THREE.BufferGeometry();
    lg.setAttribute("position", new THREE.BufferAttribute(lp, 3)); lg.setAttribute("color", new THREE.BufferAttribute(lc, 3));
    wire = new THREE.LineSegments(lg, lineMat); wire.renderOrder = 6; over.add(wire);
    if (ed.mode === "vert") {
      const pp = new Float32Array(poly.v.length * 3), pc = new Float32Array(poly.v.length * 3);
      const v0 = new THREE.Color(FORGE_SEL_COLORS.vert), v1 = new THREE.Color(FORGE_SEL_COLORS.vertSel);
      poly.v.forEach((p, i) => { pp.set(p, i * 3); const c = s.v.has(i) ? v1 : v0; pc.set([c.r, c.g, c.b], i * 3); });
      const pg = new THREE.BufferGeometry();
      pg.setAttribute("position", new THREE.BufferAttribute(pp, 3)); pg.setAttribute("color", new THREE.BufferAttribute(pc, 3));
      dots = new THREE.Points(pg, pointMat); dots.renderOrder = 7; over.add(dots);
    }
    if (s.f.size) {
      const F = [];
      for (const fi of s.f) {
        const f = poly.f[fi];
        if (f) for (let k = 1; k + 1 < f.length; k++) F.push(...poly.v[f[0]], ...poly.v[f[k]], ...poly.v[f[k + 1]]);
      }
      const fg = new THREE.BufferGeometry(); fg.setAttribute("position", new THREE.Float32BufferAttribute(F, 3));
      fill = new THREE.Mesh(fg, faceMat); fill.renderOrder = 5; over.add(fill);
    }
    for (const m of [lineMat, pointMat, faceMat]) { m.depthTest = !ed.xray; m.needsUpdate = true; }
    view.dirty = true;
  }
  // while a move runs: the same overlay, only its positions (rebuilding 100k edges every mouse move is too slow)
  function moveOverlay(poly) {
    const T = topo();
    if (!wire || !T) { drawOverlay(poly); return; }
    const lp = wire.geometry.attributes.position.array;
    T.edges.forEach((e, i) => { lp.set(poly.v[e.a], i * 6); lp.set(poly.v[e.b], i * 6 + 3); });
    wire.geometry.attributes.position.needsUpdate = true; wire.geometry.computeBoundingSphere();
    if (dots) {
      const pp = dots.geometry.attributes.position.array;
      poly.v.forEach((q, i) => pp.set(q, i * 3));
      dots.geometry.attributes.position.needsUpdate = true; dots.geometry.computeBoundingSphere();
    }
    if (fill) {
      const fp = fill.geometry.attributes.position.array;
      let o = 0;
      for (const fi of ed.sel.f) {
        const f = poly.f[fi];
        if (f) for (let k = 1; k + 1 < f.length; k++) { fp.set(poly.v[f[0]], o); fp.set(poly.v[f[k]], o + 3); fp.set(poly.v[f[k + 1]], o + 6); o += 9; }
      }
      fill.geometry.attributes.position.needsUpdate = true; fill.geometry.computeBoundingSphere();
    }
    view.dirty = true;
  }
  function xrayLook() {
    material.transparent = ed.xray; material.opacity = ed.xray ? 0.45 : 1; material.depthWrite = !ed.xray;
    material.needsUpdate = true;
    drawOverlay();
  }

  // ---------------------------------------------------------------- the selection
  function setSel(next, quiet) {
    ed.sel = { v: new Set(next.v), e: new Set(next.e), f: new Set(next.f) };
    view.selected = [...ed.sel.f].sort((a, b) => a - b);
    drawOverlay();
    placePivot();
    if (!quiet) stats();
    if (view.onSelect) view.onSelect();
  }
  const empty = () => ({ v: new Set(), e: new Set(), f: new Set() });
  view.select = (faces) => {                         // faces (the ops in forge_model.js) -> a flushed selection
    const T = topo();
    if (!T || !faces || !faces.length) { setSel(empty(), true); return; }
    setSel(P.flushSelection(view.poly, T, { v: [], e: [], f: faces.filter((i) => i >= 0 && i < view.poly.f.length) }, "face"), true);
  };
  // items of one kind (vert ids / edge ids / face ids), how: set | add | sub | toggle
  view.selectItems = (kind, items, how) => {
    const T = topo();
    if (!T) return;
    const k = KEY[kind], cur = new Set(how === "set" ? [] : ed.sel[k]);
    for (const x of items) {
      if (how === "sub") cur.delete(x);
      else if (how === "toggle" && cur.has(x)) cur.delete(x);
      else cur.add(x);
    }
    const base = { v: ed.sel.v, e: ed.sel.e, f: ed.sel.f };
    base[k] = cur;
    setSel(P.flushSelection(view.poly, T, base, kind));
  };
  view.setSelMode = (mode) => {
    if (!KEY[mode]) return;
    ed.mode = mode;
    const T = topo();
    if (T) setSel(P.flushSelection(view.poly, T, ed.sel, mode), true); else drawOverlay();
    for (const b of document.querySelectorAll("#forge [data-selmode]")) b.classList.toggle("on", b.dataset.selmode === mode);
    stats();
  };
  view.selectAll = (on) => {
    const T = topo();
    if (!T) return;
    if (on == null) on = ed.sel.v.size < view.poly.v.length;
    setSel(on ? P.flushSelection(view.poly, T, { v: view.poly.v.map((_, i) => i), e: [], f: [] }, "vert") : empty());
    if (ed.mode !== "vert") view.setSelMode(ed.mode);
  };
  view.selectInvert = () => {
    const T = topo();
    if (!T) return;
    const k = KEY[ed.mode], n = ed.mode === "vert" ? view.poly.v.length : ed.mode === "edge" ? T.edges.length : view.poly.f.length;
    view.selectItems(ed.mode, [...Array(n).keys()].filter((i) => !ed.sel[k].has(i)), "set");
  };
  view.selectGrow = (more) => {
    const T = topo();
    if (!T || !ed.sel.v.size) return;
    const v = more ? P.grow(view.poly, T, ed.sel.v) : P.shrink(view.poly, T, ed.sel.v);
    setSel(P.flushSelection(view.poly, T, { v, e: [], f: [] }, "vert"));
    if (ed.mode !== "vert") view.setSelMode(ed.mode);
  };
  view.selectLinked = (fromVerts, how) => {
    const T = topo();
    if (!T) return;
    const seed = fromVerts || [...ed.sel.v];
    if (!seed.length) return;
    const v = P.linked(view.poly, T, seed), next = P.flushSelection(view.poly, T, { v, e: [], f: [] }, "vert");
    if (how === "add") { for (const k of ["v", "e", "f"]) for (const x of ed.sel[k]) next[k].add(x); }
    setSel(next);
    if (ed.mode !== "vert") view.setSelMode(ed.mode);
  };
  // the vertices a move / rotate / scale works on (every mode moves vertices underneath)
  view.selectedVerts = () => [...ed.sel.v];
  function stats() {
    const T = topo();
    if (!T || view.mode !== "poly") return;
    const s = ed.sel;
    say("Verts " + s.v.size + "/" + view.poly.v.length + " · Edges " + s.e.size + "/" + T.edges.length
      + " · Faces " + s.f.size + "/" + view.poly.f.length + (ed.xray ? " · X-ray" : "") + (through() && !ed.xray ? " · Selects through" : "") + (ed.prop ? " · Proportional" : ""));
  }
  view.selStats = stats;

  // ---------------------------------------------------------------- screen space + the selection buffer
  function projector() {
    holder.updateMatrixWorld(); camera.updateMatrixWorld();
    const r = canvas.getBoundingClientRect();
    const e = new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse).multiply(holder.matrixWorld).elements;
    return (p) => {
      const x = p[0], y = p[1], z = p[2], w = e[3] * x + e[7] * y + e[11] * z + e[15];
      if (w <= 1e-9) return null;
      const nx = (e[0] * x + e[4] * y + e[8] * z + e[12]) / w, ny = (e[1] * x + e[5] * y + e[9] * z + e[13]) / w;
      const nz = (e[2] * x + e[6] * y + e[10] * z + e[14]) / w;
      if (nz < -1 || nz > 1) return null;
      return [(nx * 0.5 + 0.5) * r.width, (0.5 - ny * 0.5) * r.height];
    };
  }
  const pick = { rt: null, buf: null, w: 0, h: 0, geoOf: null, mesh: null, scene: new THREE.Scene() };
  const pickMat = new THREE.ShaderMaterial({
    vertexShader: "attribute vec3 pid; varying vec3 vId; void main() { vId = pid; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: "varying vec3 vId; void main() { gl_FragColor = vec4(floor(vId + 0.5) / 255.0, 1.0); }",
    side: THREE.DoubleSide,
  });
  function renderPick() {
    const mesh = ctx.mesh();
    if (!mesh || !view.poly || !view.polyCorners) return false;
    const size = renderer.getDrawingBufferSize(new THREE.Vector2()), w = size.x, h = size.y;
    if (!pick.rt || pick.w !== w || pick.h !== h) {
      if (pick.rt) pick.rt.dispose();
      pick.rt = new THREE.WebGLRenderTarget(w, h); pick.w = w; pick.h = h; pick.buf = new Uint8Array(w * h * 4);
    }
    if (pick.geoOf !== mesh.geometry) {
      if (pick.mesh) { pick.scene.remove(pick.mesh); pick.mesh.geometry.dispose(); }
      const g = new THREE.BufferGeometry(), n = mesh.geometry.attributes.position.count, pid = new Float32Array(n * 3);
      view.poly.f.forEach((f, fi) => {
        const id = fi + 1, at = view.polyCorners[fi];
        for (let k = 0; k < f.length; k++) pid.set([id & 255, (id >> 8) & 255, (id >> 16) & 255], (at + k) * 3);
      });
      g.setAttribute("position", mesh.geometry.attributes.position);
      g.setAttribute("pid", new THREE.BufferAttribute(pid, 3));
      g.setIndex(mesh.geometry.index);
      pick.mesh = new THREE.Mesh(g, pickMat); pick.mesh.matrixAutoUpdate = false; pick.mesh.frustumCulled = false;
      pick.scene.add(pick.mesh); pick.geoOf = mesh.geometry;
    }
    holder.updateMatrixWorld(); camera.updateMatrixWorld();
    // the buffer only changes when the camera, the object or the mesh does: reuse it otherwise (hover picking asks
    // every frame the mouse moves)
    const key = camera.matrixWorld.elements.join(",") + "|" + camera.projectionMatrix.elements[0] + "|" + holder.matrixWorld.elements.join(",")
      + "|" + mesh.geometry.attributes.position.version + "|" + w + "x" + h + "|" + mesh.geometry.uuid;
    if (pick.key === key && pick.rect) return true;
    pick.key = key;
    pick.mesh.matrix.copy(holder.matrixWorld); pick.mesh.matrixWorldNeedsUpdate = true;
    const prev = renderer.getRenderTarget(), cc = renderer.getClearColor(new THREE.Color()), ca = renderer.getClearAlpha();
    renderer.setScissorTest(false);
    renderer.setRenderTarget(pick.rt);
    renderer.setClearColor(0x000000, 0); renderer.clear();
    renderer.render(pick.scene, camera);
    renderer.readRenderTargetPixels(pick.rt, 0, 0, w, h, pick.buf);
    renderer.setRenderTarget(prev); renderer.setClearColor(cc, ca);
    const r = canvas.getBoundingClientRect();
    pick.rect = { width: r.width || 1, height: r.height || 1 };
    pick.px = pick.w / pick.rect.width;              // buffer pixels per canvas pixel
    return true;
  }
  function bufXY(cx, cy) {
    const r = pick.rect;
    return [Math.floor(cx * pick.w / r.width), Math.floor((r.height - cy) * pick.h / r.height)];
  }
  function idAtBuf(bx, by) {
    if (bx < 0 || by < 0 || bx >= pick.w || by >= pick.h) return -1;
    const o = (by * pick.w + bx) * 4, b = pick.buf;
    if (!b[o + 3]) return -1;
    return (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16)) - 1;
  }
  // is one of `faces` drawn within rad canvas pixels of (cx, cy)? - the element is visible, not behind something
  function seenNear(cx, cy, rad, faces) {
    const [bx, by] = bufXY(cx, cy), r = Math.max(1, Math.round(rad * pick.px));
    for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) {
      const f = idAtBuf(bx + dx, by + dy);
      if (f >= 0 && faces.includes(f)) return true;
    }
    return false;
  }
  // Camera based selection (the pro Selection preference, owner 2026-10-21: "when I marquee select I should be able to
  // grab the verts I don't see as well, make that a toggle"): "auto" (default) = only what you can see in shaded mode,
  // everything - front and back - in wireframe (4) and X-ray; "on" = always only what you see; "off" = always through
  // (the marquee takes the hidden side too). A click still takes the nearest seen element unless it is "off".
  const camSel = () => { try { return localStorage.getItem("loki-forge-camsel") || "auto"; } catch (_) { return "auto"; } };
  const through = () => { const c = camSel(); return c === "off" || ed.xray || (c === "auto" && !!view.wireOnly); };
  view.cameraBasedSelection = (mode) => {
    if (mode) { try { localStorage.setItem("loki-forge-camsel", mode); } catch (_) { /* private mode */ } }
    stats();
    return camSel();
  };
  view.selectsThrough = through;
  const seesVert = (i, s) => through() || seenNear(s[0], s[1], 3, topo().vertFaces[i]);
  const seesEdge = (ei, s) => through() || seenNear(s[0], s[1], 2, topo().edges[ei].faces);
  function segDist(p, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy;
    const t = l2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2)) : 0;
    const q = [a[0] + dx * t, a[1] + dy * t];
    return [Math.hypot(p[0] - q[0], p[1] - q[1]), q];
  }
  function nearestVert(pt, proj, maxPx) {
    let best = -1, bd = maxPx;
    view.poly.v.forEach((p, i) => {
      const s = proj(p);
      if (!s) return;
      const d = Math.hypot(s[0] - pt[0], s[1] - pt[1]);
      if (d < bd && seesVert(i, s)) { bd = d; best = i; }
    });
    return best;
  }
  function nearestEdge(pt, proj, maxPx, onlyFace) {
    const T = topo(), sv = view.poly.v.map((p) => proj(p));
    let best = -1, bd = maxPx;
    const list = onlyFace != null ? T.faceEdges[onlyFace] : T.edges.map((_, i) => i);
    for (const i of list) {
      const e = T.edges[i], a = sv[e.a], b = sv[e.b];
      if (!a || !b) continue;
      const [d, q] = segDist(pt, a, b);
      if (d < bd && (onlyFace != null || seesEdge(i, q))) { bd = d; best = i; }
    }
    return best;
  }
  function faceAt(pt, proj) {
    if (!ed.xray && !view.wireOnly) return idAtBuf(...bufXY(pt[0], pt[1]));   // wireframe: pick by the face centres, like X-ray
    let best = -1, bd = 26;                              // X-ray: the nearest face centre, like Blender's face dots
    view.poly.f.forEach((f, i) => {
      const s = proj(P.centroid(view.poly, f));
      if (!s) return;
      const d = Math.hypot(s[0] - pt[0], s[1] - pt[1]);
      if (d < bd) { bd = d; best = i; }
    });
    return best >= 0 ? best : idAtBuf(...bufXY(pt[0], pt[1]));
  }
  // a click at canvas point pt -> {kind, id} under it (or id -1)
  // what an interactive cut tool (Multi-Cut, Target Weld, Connect) clicked: a vertex when the mouse is within 10 px
  // of one, else a point along the nearest edge ({ e: [a, b], t } - t from a to b, as seen on screen), else a face
  view.cutPointAt = (pt) => {
    if (!view.poly) return null;
    renderPick();
    const proj = projector();
    const vi = nearestVert(pt, proj, 10);
    if (vi >= 0) return { v: vi, at: view.poly.v[vi].slice() };
    const ei = nearestEdge(pt, proj, 18);
    if (ei < 0) { const fi = faceAt(pt, proj); return fi >= 0 ? { face: fi } : null; }
    const T = topo(), e = T.edges[ei], a = proj(view.poly.v[e.a]), b = proj(view.poly.v[e.b]);
    const dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy;
    let t = l2 ? ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / l2 : 0.5;
    t = Math.max(0.02, Math.min(0.98, t));
    const pa = view.poly.v[e.a], pb = view.poly.v[e.b];
    return { e: [e.a, e.b], t: t, at: [pa[0] + (pb[0] - pa[0]) * t, pa[1] + (pb[1] - pa[1]) * t, pa[2] + (pb[2] - pa[2]) * t] };
  };
  view.edgePairs = () => { const T = topo(); return T ? [...ed.sel.e].map((i) => [T.edges[i].a, T.edges[i].b]) : []; };
  view.edgeIdOf = (a, b) => { const T = topo(); if (!T) return -1; const i = T.edge(a, b); return i == null ? -1 : i; };
  view.pickElement = (pt) => {
    if (!view.poly) return { kind: ed.mode, id: -1 };
    renderPick();
    const proj = projector();
    if (ed.mode === "vert") return { kind: "vert", id: nearestVert(pt, proj, 22) };
    if (ed.mode === "edge") return { kind: "edge", id: nearestEdge(pt, proj, 16) };
    return { kind: "face", id: faceAt(pt, proj) };
  };
  view.clickSelect = (pt, how) => {
    const hit = view.pickElement(pt);
    if (hit.id < 0) { if (how === "set") setSel(empty()); return hit; }
    view.selectItems(hit.kind, [hit.id], how === "remove" ? "sub" : (how === "set" || how === "toggle" || how === "add" || how === "sub") ? how : "toggle");
    return hit;
  };
  view.loopSelect = (pt, how) => {
    if (!view.poly) return;
    renderPick();
    const T = topo(), proj = projector();
    let next;
    if (ed.mode === "face") {
      const fi = faceAt(pt, proj);
      if (fi < 0) return;
      const ei = nearestEdge(pt, proj, 1e9, fi);
      next = P.flushSelection(view.poly, T, { v: [], e: [], f: P.edgeRing(view.poly, T, ei).faces }, "face");
    } else {
      const ei = nearestEdge(pt, proj, 24);
      if (ei < 0) return;
      next = P.flushSelection(view.poly, T, { v: [], e: P.edgeLoop(view.poly, T, ei), f: [] }, "edge");
      if (ed.mode === "vert") next = P.flushSelection(view.poly, T, next, "vert");
    }
    if (how === "add") for (const k of ["v", "e", "f"]) for (const x of ed.sel[k]) next[k].add(x);
    setSel(next);
  };
  // Select > Convert > To Edge Loop / To Edge Ring (the pro Ctrl + right-button menu): every selected edge grows
  // into its whole loop / ring; from faces or vertices the edges they touch are used first
  view.convertEdges = (kind) => {
    if (!view.poly) return 0;
    const T = topo();
    let seeds = [...ed.sel.e];
    if (!seeds.length) seeds = [...P.flushSelection(view.poly, T, { v: [...ed.sel.v], e: [], f: [...ed.sel.f] }, "edge").e];
    if (!seeds.length) return 0;
    const out = new Set();
    const dirOf = (ei) => { const e = T.edges[ei]; const d = [0, 1, 2].map((k) => view.poly.v[e.b][k] - view.poly.v[e.a][k]); const l = Math.hypot(d[0], d[1], d[2]) || 1; return [d[0] / l, d[1] / l, d[2] / l]; };
    for (const ei of seeds) {
      let got;
      if (kind === "ring") got = P.edgeRing(view.poly, T, ei).edges;
      else {
        got = P.edgeLoop(view.poly, T, ei);
        // (Ziva, Mac, 2026-10-21) a loop needs valence-4 vertices; where none exists (a cube corner is a 3-pole) the
        // standard tools fall back to the edge ring - the belt of edges around the pick; if a nearby edit stopped the
        // ring walk early, the edges parallel to the pick
        if (got.length < 3) {
          got = P.edgeRing(view.poly, T, ei).edges;
          if (got.length < 3) { const d0 = dirOf(ei); got = T.edges.map((e, i) => i).filter((i) => { const d = dirOf(i); return Math.abs(d0[0] * d[0] + d0[1] * d[1] + d0[2] * d[2]) > 0.98; }); }
        }
      }
      for (const x of got) out.add(x);
    }
    if (ed.mode !== "edge" && view.setSelMode) view.setSelMode("edge");
    setSel(P.flushSelection(view.poly, T, { v: [], e: [...out], f: [] }, "edge"));
    return out.size;
  };
  view.boxSelect = (x0, y0, x1, y1, how) => {
    if (!view.poly) return;
    renderPick();
    const T = topo(), proj = projector(), lo = [Math.min(x0, x1), Math.min(y0, y1)], hi = [Math.max(x0, x1), Math.max(y0, y1)];
    const inside = (s) => s && s[0] >= lo[0] && s[0] <= hi[0] && s[1] >= lo[1] && s[1] <= hi[1];
    const sv = view.poly.v.map((p) => proj(p)), hits = [];
    if (ed.mode === "vert") view.poly.v.forEach((_, i) => { if (inside(sv[i]) && seesVert(i, sv[i])) hits.push(i); });
    else if (ed.mode === "edge") {
      T.edges.forEach((e, i) => {
        const a = sv[e.a], b = sv[e.b];
        if (inside(a) && inside(b) && seesEdge(i, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2])) hits.push(i);
      });
    } else if (through()) view.poly.f.forEach((f, i) => { const c = proj(P.centroid(view.poly, f)); if (c && inside(c)) hits.push(i); });
    else {
      const [bx0, by1] = bufXY(lo[0], lo[1]), [bx1, by0] = bufXY(hi[0], hi[1]), seen = new Set();
      for (let y = Math.max(0, by0); y <= Math.min(pick.h - 1, by1); y++) for (let x = Math.max(0, bx0); x <= Math.min(pick.w - 1, bx1); x++) {
        const f = idAtBuf(x, y); if (f >= 0) seen.add(f);
      }
      hits.push(...seen);
    }
    view.selectItems(ed.mode, hits, how);
    return hits.length;
  };

  // ---------------------------------------------------------------- moving: one edit, shared by the handle and G/R/S
  const pivot = new THREE.Object3D(); pivot.name = "forge-edit-pivot"; holder.add(pivot);
  const gizmo = new ctx.lib.TransformControls(camera, canvas);
  gizmo.setSize(0.8);
  // the pro Shift + drag on a component manipulator: extrude first, then move / rotate / scale the new faces
  let shiftHeld = false;
  document.addEventListener("keydown", (e) => { if (e.key === "Shift") shiftHeld = true; }, true);
  document.addEventListener("keyup", (e) => { if (e.key === "Shift") shiftHeld = false; }, true);
  window.addEventListener("blur", () => { shiftHeld = false; });
  gizmo.shiftHint = (tc) => (ed.mode === "edge" && ed.sel.e.size ? "Shift + drag: extrude the edges and " + ({ translate: "move", rotate: "rotate", scale: "scale" }[tc.mode] || "move") + " them."
    : ed.mode === "vert" && ed.sel.v.size ? "Shift + drag: extrude the vertices." : view.selected && view.selected.length
    ? "Shift + drag: extrude the " + (view.selected.length === 1 ? "face" : view.selected.length + " faces") + " and " + ({ translate: "move", rotate: "rotate", scale: "scale" }[tc.mode] || "move") + (view.selected.length === 1 ? " it." : " them.")
    : "Shift + drag extrudes faces - pick whole faces first.");
  ctx.scene.add(gizmo.getHelper ? gizmo.getHelper() : gizmo);
  gizmo.addEventListener("dragging-changed", (e) => { controls.enabled = !e.value; });
  gizmo.addEventListener("change", () => { view.dirty = true; });
  let edit = null;
  function placePivot() {
    if (edit) return;
    const verts = view.selectedVerts();
    if (!view.poly || !verts.length || view.mode !== "poly") { if (gizmo.object) gizmo.detach(); return; }
    pivot.position.fromArray(P.median(view.poly, verts.filter((id) => view.poly.v[id] !== undefined))); pivot.rotation.set(0, 0, 0); pivot.scale.set(1, 1, 1);
    pivot.updateMatrix();
    if (ed.tool && !gizmo.object) { gizmo.attach(pivot); gizmo.setMode(ed.tool); }
    view.dirty = true;
  }
  view.setTool = (mode) => {                        // the handle: "translate" | "rotate" | "scale" | null
    ed.tool = ed.tool === mode ? null : mode;
    if (gizmo.object) gizmo.detach();
    if (ed.tool) placePivot();
    for (const b of document.querySelectorAll("#forge [data-tool]")) b.classList.toggle("on", b.dataset.tool === ed.tool);
    view.dirty = true;
    return ed.tool;
  };
  view.tool = () => ed.tool;
  function begin(kind) {
    const verts = view.selectedVerts();
    if (!view.poly || !verts.length) return false;
    const radius = ed.prop ? ed.propRadius * (view.size || 1) : 0;
    edit = { kind, base: view.poly, work: P.clone(view.poly), verts, weights: P.weights(view.poly, verts, radius, ed.falloff),
      pivot: P.median(view.poly, verts), start: pivot.matrix.clone(), keep: ed.sel };
    edit.sym = planSymmetry();
    return true;
  }
  function reweigh() {
    if (!edit) return;
    edit.weights = P.weights(edit.base, edit.verts, ed.prop ? ed.propRadius * (view.size || 1) : 0, ed.falloff);
    edit.sym = planSymmetry();
  }

  // ---- modelling symmetry: mirror the weighted vertices onto their mirror images and move them with the mirror
  // of the same matrix (M' = S M S), so the two halves move as one. Every non-empty subset of the active axes gets
  // its own mirrored weight map - the same rule the sculpt core uses (view.brush.symBits: 1 X, 2 Y, 4 Z).
  function mirrorMatrix(M, S) {          // S is the diagonal of +-1; M is a column-major 4x4 array
    const out = M.slice();
    for (let c = 0; c < 3; c++) for (let r = 0; r < 3; r++) out[c * 4 + r] = S[r] * M[c * 4 + r] * S[c];
    for (let r = 0; r < 3; r++) out[12 + r] = S[r] * M[12 + r];
    return out;
  }
  function planSymmetry() {
    const bits = (view.brush && view.brush.symBits) | 0;
    if (!bits || !view.brush.symModel || !edit || !edit.base) return null;   // modelling symmetry is opt-in
    const V = edit.base.v, sel = [...edit.weights.keys()].sort((a, b) => a - b);
    if (!sel.length) return null;
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (const p of V) for (let d = 0; d < 3; d++) { lo[d] = Math.min(lo[d], p[d]); hi[d] = Math.max(hi[d], p[d]); }
    const eps = Math.max(1e-6, Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) * 1e-4), cell = eps * 2;
    const gkey = (a, b, c) => a + "/" + b + "/" + c;
    const grid = new Map();
    V.forEach((p, i) => { const k = gkey(Math.floor(p[0] / cell), Math.floor(p[1] / cell), Math.floor(p[2] / cell)); if (!grid.has(k)) grid.set(k, []); grid.get(k).push(i); });
    const find = (q) => {
      const a = Math.floor(q[0] / cell), b = Math.floor(q[1] / cell), c = Math.floor(q[2] / cell);
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++)
        for (const j of grid.get(gkey(a + dx, b + dy, c + dz)) || []) {
          const r = V[j];
          if (Math.abs(r[0] - q[0]) <= eps && Math.abs(r[1] - q[1]) <= eps && Math.abs(r[2] - q[2]) <= eps) return j;
        }
      return -1;
    };
    const out = [];
    for (let m = 1; m < 8; m++) {
      if ((m & ~bits) !== 0) continue;
      const S = [(m & 1) ? -1 : 1, (m & 2) ? -1 : 1, (m & 4) ? -1 : 1], map = new Map(), done = new Set();
      for (const i of sel) {                  // ascending, so a mirrored pair splits once: the lower keeps M, the higher takes M'
        if (done.has(i)) continue;
        const p = V[i], j = find([p[0] * S[0], p[1] * S[1], p[2] * S[2]]);
        if (j < 0 || j === i) continue;
        map.set(j, Math.max(map.get(j) || 0, edit.weights.get(i)));
        done.add(j);
      }
      if (map.size) out.push({ map, S });
    }
    return out.length ? out : null;
  }

  function applyM(M) {
    P.applyMatrix(edit.base, edit.weights, M.elements, edit.work);   // writes only the weighted vertices
    if (edit.sym) for (const s of edit.sym) P.applyMatrix(edit.base, s.map, mirrorMatrix(M.elements, s.S), edit.work);
    view.polyLive(edit.work);
    moveOverlay(edit.work);
  }
  function commit() {
    if (!edit) return;
    const { work, base, keep } = edit;
    edit = null;
    view.polyLive(base);                              // put the shown mesh back so undo has the true "before"
    view.showPoly(work, true);
    // the move lands in the construction history (polyTweak), so changing an earlier step's amount keeps it
    if (typeof forgeHistPush === "function" && typeof forgeModel !== "undefined" && forgeModel.hist) {
      const moved = [];
      for (let i = 0; i < work.v.length; i++) {
        const a = base.v[i], b = work.v[i];
        if (a && b && (a[0] !== b[0] || a[1] !== b[1] || a[2] !== b[2])) moved.push(i, b[0], b[1], b[2]);
      }
      if (moved.length) forgeHistPush({ kind: "tweak", verts: moved });
    }
    setSel(keep);
    if (typeof forgeModel !== "undefined") { forgeModel.last = null; forgeModel.prim = null; }
    if (typeof forgeModelSync === "function") forgeModelSync();
  }
  let shiftExtrude = false;
  gizmo.addEventListener("mouseDown", () => {
    // Shift over the handle with EDGES or VERTICES picked: the pro edge / vertex extrude, then the drag moves them
    const P2 = window.ForgePoly;
    if (shiftHeld && view.poly && ed.mode !== "face" && P2 && (ed.mode === "edge" ? ed.sel.e.size && P2.extrudeEdges : ed.sel.v.size && P2.extrudeVerts)) {
      if (view.undoOpen) view.undoOpen("Extrude");
      shiftExtrude = true;
      const base = view.poly, isE = ed.mode === "edge";
      const items = isE ? view.edgePairs() : [...ed.sel.v];
      const op = isE ? "extrudeEdges" : "extrudeVerts", opts = isE ? { thickness: 0, offset: 0 } : { length: 0, width: 0.1 };
      const out = P2[op](base, items, opts);
      if (out && out.m && !out.warn && out.m !== base) {
        edit = { kind: "prep" };
        try {
          view.showPoly(out.m, true, true);
          if (typeof forgeHistPush === "function") forgeHistPush({ kind: "op", op: op, tool: op, items: items, params: opts, main: isE ? "thickness" : "length" }, base);
          if (typeof forgeTkSelect === "function") forgeTkSelect(view, out.sel);
        } finally { edit = null; }
      } else if (out && out.warn && typeof forgeSay === "function") forgeSay("Extrude: " + out.warn, true);
    } else if (shiftHeld && view.poly && view.selected && view.selected.length) {
      // one undo step for the extrude and the drag (forge_scene.js undo chunk); the history gets the extrude
      if (view.undoOpen) view.undoOpen("Extrude");
      shiftExtrude = true;
      const base = view.poly, faces = view.selected.slice();
      edit = { kind: "prep" };                        // keep the handle attached while the mesh is swapped
      try {
        view.showPoly(P.extrude(base, faces, 0), true, true);
        if (typeof forgeHistPush === "function") forgeHistPush({ kind: "extrude", faces: faces, amount: 0 }, base);
        view.select(faces);
      } finally { edit = null; }
      if (typeof forgeSay === "function") forgeSay("Extruded " + faces.length + " face" + (faces.length === 1 ? "" : "s") + " - drag to place them.");
    }
    if (!begin("handle")) gizmo.detach();
  });
  gizmo.addEventListener("objectChange", () => {
    if (!edit || edit.kind !== "handle") return;
    if (view.snapPivot) view.snapPivot(pivot);        // the pro x / c / v snapping (forge_pro.js) moves the handle first
    // scale the handle back through its centre and the axis sticks at 0: the components lie flat (Maya / Unreal)
    if (gizmo.mode === "scale" && typeof forgeScaleZeroSnap === "function") forgeScaleZeroSnap(pivot.scale, gizmo.axis, 0.06, 0);
    pivot.updateMatrix();
    applyM(new THREE.Matrix4().multiplyMatrices(pivot.matrix, edit.start.clone().invert()));
  });
  gizmo.addEventListener("mouseUp", () => {
    if (edit && edit.kind === "handle") { commit(); stats(); }
    if (shiftExtrude) { shiftExtrude = false; if (view.undoClose) view.undoClose(); }
  });

  view.setProportional = (on, radius, falloff) => {
    if (on != null) ed.prop = !!on;
    if (radius != null) ed.propRadius = Math.max(0.01, Math.min(2, radius));
    if (falloff && P.FALLOFF[falloff]) ed.falloff = falloff;
    reweigh();
    for (const b of document.querySelectorAll("#forge [data-prop]")) b.classList.toggle("on", ed.prop);
    stats();
    return ed;
  };
  view.setXray = (on) => {
    ed.xray = on == null ? !ed.xray : !!on;
    xrayLook();
    for (const b of document.querySelectorAll("#forge [data-xray]")) b.classList.toggle("on", ed.xray);
    stats();
  };

  // ---------------------------------------------------------------- the mouse, in Model mode
  const box = document.createElement("div"); box.className = "forge-marquee"; box.hidden = true;
  canvas.parentElement.append(box);
  const local = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  let gest = null;
  canvas.addEventListener("pointerdown", (e) => {
    if (view.mode !== "poly" || !view.poly || view.quad) return;
    ed.mouse = local(e);
    if (e.button !== 0) return;                     // middle turns, right pans: the orbit controls keep those
    if (gizmo.object && gizmo.axis) return;        // the move handle
    if (forgeCamMod(e)) return;                     // Alt / Option or Cmd is the camera, nothing else
    e.stopImmediatePropagation();
    canvas.setPointerCapture(e.pointerId);
    // the pro modifiers, for a click and for a box: Shift toggles, Ctrl/Cmd takes away, Ctrl/Cmd+Shift adds
    const mod = e.ctrlKey || e.metaKey;
    const how = mod && e.shiftKey ? "add" : mod ? "sub" : e.shiftKey ? "toggle" : "set";
    gest = { at: ed.mouse, box: false, how: how, click: how };
  }, { capture: true });
  canvas.addEventListener("pointermove", (e) => {
    if (view.mode !== "poly") return;
    ed.mouse = local(e);
    if (!gest || gest.alt) return;
    e.stopImmediatePropagation();
    const p = ed.mouse;
    if (!gest.box && Math.hypot(p[0] - gest.at[0], p[1] - gest.at[1]) > 4) gest.box = true;
    if (gest.box) {
      box.hidden = false;
      box.classList.toggle("sub", gest.how === "sub");
      Object.assign(box.style, { left: Math.min(p[0], gest.at[0]) + canvas.offsetLeft + "px", top: Math.min(p[1], gest.at[1]) + canvas.offsetTop + "px",
        width: Math.abs(p[0] - gest.at[0]) + "px", height: Math.abs(p[1] - gest.at[1]) + "px" });
    }
  }, { capture: true });
  canvas.addEventListener("pointerup", (e) => {
    if (!gest || view.mode !== "poly") { gest = null; return; }
    const g = gest, p = local(e);
    gest = null;
    box.hidden = true;
    if (g.box) view.boxSelect(g.at[0], g.at[1], p[0], p[1], g.how);
    else view.clickSelect(p, g.click);
  }, { capture: true });
  canvas.addEventListener("pointercancel", () => { gest = null; box.hidden = true; });

  // Preselection highlight (the pro Selection preference, on by default): the vertex / edge / face under the mouse
  // lights up red before you click, so you know what a click will take. Off: localStorage loki-forge-preselect = 0.
  const preOn = () => { try { return localStorage.getItem("loki-forge-preselect") !== "0"; } catch (_) { return true; } };
  view.preselectHighlight = (on) => { if (on != null) { try { localStorage.setItem("loki-forge-preselect", on ? "1" : "0"); } catch (_) { /* */ } if (!on) preClear(); } return preOn(); };
  const preMat = new THREE.LineBasicMaterial({ color: 0xff3d3d, depthTest: false, transparent: true });
  const prePt = new THREE.PointsMaterial({ color: 0xff3d3d, size: 8, sizeAttenuation: false, depthTest: false, transparent: true });
  let pre = null, preAt = null, preQueued = false, preKey = "";
  function preClear() { if (pre) { if (pre.parent) pre.parent.remove(pre); pre.geometry.dispose(); pre = null; preKey = ""; view.dirty = true; } }
  function preDraw() {
    preQueued = false;
    if (!preAt || view.mode !== "poly" || !view.poly || gest || edit || !preOn() || (gizmo.object && gizmo.axis)
      || (typeof window.forgeToolkit !== "undefined" && window.forgeToolkit.sel && window.forgeToolkit.sel())) { preClear(); return; }
    const hit = view.pickElement(preAt);
    const k = hit.kind + ":" + hit.id + ":" + view.poly.v.length;
    if (k === preKey) return;
    preClear();
    if (hit.id < 0) return;
    preKey = k;
    const g = new THREE.BufferGeometry(), m = view.poly;
    let obj;
    if (hit.kind === "vert") { g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(m.v[hit.id]), 3)); obj = new THREE.Points(g, prePt); }
    else {
      const segs = [];
      if (hit.kind === "edge") { const e = topo().edges[hit.id]; segs.push(m.v[e.a], m.v[e.b]); }
      else { const f = m.f[hit.id]; for (let i = 0; i < f.length; i++) segs.push(m.v[f[i]], m.v[f[(i + 1) % f.length]]); }
      const a = new Float32Array(segs.length * 3); segs.forEach((p, i) => a.set(p, i * 3));
      g.setAttribute("position", new THREE.BufferAttribute(a, 3));
      obj = new THREE.LineSegments(g, preMat);
    }
    obj.name = "forge-preselect"; obj.renderOrder = 20; obj.raycast = () => {};
    holder.add(obj); pre = obj; view.dirty = true;
  }
  canvas.addEventListener("pointermove", (e) => {
    if (view.mode !== "poly" || e.buttons) { if (pre) preClear(); return; }
    preAt = local(e);
    if (!preQueued) { preQueued = true; requestAnimationFrame(preDraw); }
  });
  canvas.addEventListener("pointerleave", () => { preAt = null; preClear(); });
  canvas.addEventListener("dblclick", (e) => {
    if (view.mode !== "poly" || !view.poly) return;
    if (ed.mode === "edge") { view.loopSelect(local(e), e.shiftKey ? "add" : "set"); return; }   // pro: double-click an edge = its loop
    const verts = view.linkedSeed(local(e));
    if (verts) view.selectLinked(verts, e.shiftKey ? "add" : "set");
  });
  // what "the piece under the mouse" starts from: the face under it (any mode), else the nearest element
  view.linkedSeed = (pt) => {
    if (!view.poly) return null;
    renderPick();
    const fi = idAtBuf(...bufXY(pt[0], pt[1]));
    if (fi >= 0) return view.poly.f[fi].slice();
    const hit = view.pickElement(pt);
    if (hit.id < 0) return null;
    return hit.kind === "vert" ? [hit.id] : hit.kind === "edge" ? [topo().edges[hit.id].a] : view.poly.f[hit.id].slice();
  };
  // keep everything in step with the viewer
  const setMode = view.setMode;
  view.setMode = (m) => {
    const was = view.mode;
    // one tool, two manipulators (the pro rule): the object manipulator never stays up in component mode - that
    // was why Shift over a face's handle duplicated the OBJECT instead of extruding the face - and the tool you had
    // carries across (move in object mode = move on the components, and back)
    const ot = view.transform;
    if (m === "poly" && was !== "poly" && ot && ot.object) { if (!ed.tool) ed.tool = ot.mode; ot.detach(); }
    setMode(m);
    if (m !== "poly") { if (gizmo.object) gizmo.detach(); if (ed.xray) { ed.xray = false; xrayLook(); } }
    if (m !== "poly" && was === "poly" && ed.tool && view.tree && view.tree.api && view.tree.api.active()) view.tree.api.attachTool(ed.tool);
    drawOverlay(); placePivot(); stats();
  };
  const onChange = () => { ed.topoOf = null; if (!edit) drawOverlay(); };
  const showPoly = view.showPoly;
  view.showPoly = (poly, keepView, noUndo) => { showPoly(poly, keepView, noUndo); onChange(); };
  const undo = view.undo, redo = view.redo;
  // after an undo / redo the handle must start from where the selection is NOW: re-attach it, or the first drag
  // after Ctrl+Z starts from the old place and does nothing (found 2026-10-19)
  const rehandle = () => { if (gizmo.object) { gizmo.object.updateMatrixWorld(true); (gizmo.getHelper ? gizmo.getHelper() : gizmo).updateMatrixWorld(true); } };
  view.undo = () => { undo(); onChange(); placePivot(); rehandle(); };
  view.redo = () => { redo(); onChange(); placePivot(); rehandle(); };
  view.gizmo = gizmo;
  view.project = (p) => projector()(p);            // a mesh point -> canvas pixels (tests, scripts)
}
