// Forge component mode - selecting and moving the parts of a poly mesh. Maya's hands since 2026-10-19 (owner: "remove
// blender hotkeys and movements, only keep maya stuff"): F9 / F10 / F11 vertex / edge / face, click selects, Shift
// toggles, Ctrl/Cmd takes away, Ctrl/Cmd+Shift adds, a drag draws a box, a double-click on an edge takes the loop,
// w / e / r put the handle on the selection, b soft selection, Alt/Option is only ever the camera. The keys live
// in app/ui/forge_maya.js. The selection engine below is still the one re-written from Blender's (GPL-2.0+):
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
//   - G / R / S: grab, rotate, scale with the mouse; X / Y / Z lock to an axis (again to unlock); type a number
//     for an exact value; Ctrl snaps; Enter or click confirms, Esc or right-click cancels (transform.cc's modal)
//   - proportional editing (O), its radius on the mouse wheel while moving, and Blender's falloff curves
//   - W shows a move handle on the selection (three.js' TransformControls, MIT) for people who think in Maya
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

const FORGE_SEL_COLORS = { wire: 0x15181f, wireSel: 0xffa04a, vert: 0x0d0f14, vertSel: 0xff8a1f };

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
  const lineMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.85 });
  const pointMat = new THREE.PointsMaterial({ size: 6, sizeAttenuation: false, vertexColors: true });
  const faceMat = new THREE.MeshBasicMaterial({ color: 0xed782b, transparent: true, opacity: 0.38, side: THREE.DoubleSide,
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
      + " · Faces " + s.f.size + "/" + view.poly.f.length + (ed.xray ? " · X-ray" : "") + (ed.prop ? " · Proportional" : ""));
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
  const seesVert = (i, s) => ed.xray || seenNear(s[0], s[1], 3, topo().vertFaces[i]);
  const seesEdge = (ei, s) => ed.xray || seenNear(s[0], s[1], 2, topo().edges[ei].faces);
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
    if (!ed.xray) return idAtBuf(...bufXY(pt[0], pt[1]));
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
    } else if (ed.xray) view.poly.f.forEach((f, i) => { if (inside(proj(P.centroid(view.poly, f)))) hits.push(i); });
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
  ctx.scene.add(gizmo.getHelper ? gizmo.getHelper() : gizmo);
  gizmo.addEventListener("dragging-changed", (e) => { controls.enabled = !e.value; });
  gizmo.addEventListener("change", () => { view.dirty = true; });
  let edit = null;
  function placePivot() {
    if (edit) return;
    const verts = view.selectedVerts();
    if (!view.poly || !verts.length || view.mode !== "poly") { if (gizmo.object) gizmo.detach(); return; }
    pivot.position.fromArray(P.median(view.poly, verts)); pivot.rotation.set(0, 0, 0); pivot.scale.set(1, 1, 1);
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
    return true;
  }
  function reweigh() {
    if (!edit) return;
    edit.weights = P.weights(edit.base, edit.verts, ed.prop ? ed.propRadius * (view.size || 1) : 0, ed.falloff);
  }
  function applyM(M) {
    P.applyMatrix(edit.base, edit.weights, M.elements, edit.work);   // writes only the weighted vertices
    view.polyLive(edit.work);
    moveOverlay(edit.work);
  }
  function commit() {
    if (!edit) return;
    const { work, base, keep } = edit;
    edit = null;
    view.polyLive(base);                              // put the shown mesh back so undo has the true "before"
    view.showPoly(work, true);
    setSel(keep);
    if (typeof forgeModel !== "undefined") { forgeModel.last = null; forgeModel.prim = null; }
    if (typeof forgeModelSync === "function") forgeModelSync();
  }
  function cancel() {
    if (!edit) return;
    const base = edit.base;
    edit = null;
    view.polyLive(base);
    moveOverlay(base);
    placePivot();
  }
  gizmo.addEventListener("mouseDown", () => { if (!begin("handle")) gizmo.detach(); });
  gizmo.addEventListener("objectChange", () => {
    if (!edit || edit.kind !== "handle") return;
    if (view.snapPivot) view.snapPivot(pivot);        // Maya's x / c / v snapping (forge_maya.js) moves the handle first
    pivot.updateMatrix();
    applyM(new THREE.Matrix4().multiplyMatrices(pivot.matrix, edit.start.clone().invert()));
  });
  gizmo.addEventListener("mouseUp", () => { if (edit && edit.kind === "handle") { commit(); stats(); } });

  // G / R / S, Blender's modal transform
  let modal = null;
  const toWorld = (p) => holder.localToWorld(new THREE.Vector3(p[0], p[1], p[2]));
  const ray = (pt) => {
    const r = canvas.getBoundingClientRect(), rc = new THREE.Raycaster();
    rc.setFromCamera(new THREE.Vector2((pt[0] / r.width) * 2 - 1, -(pt[1] / r.height) * 2 + 1), camera);
    return rc.ray;
  };
  const AX = [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1)];
  function axisParam(r, origin, dir) {             // where along the axis line the mouse ray passes closest
    const w0 = origin.clone().sub(r.origin), a = dir.dot(dir), b = dir.dot(r.direction), c = r.direction.dot(r.direction);
    const d = dir.dot(w0), e = r.direction.dot(w0), den = a * c - b * b;
    return Math.abs(den) < 1e-9 ? 0 : (b * e - c * d) / den;
  }
  view.modalStart = (type) => {
    if (modal || view.mode !== "poly" || !begin("modal")) return false;
    const r = canvas.getBoundingClientRect();
    const m = ed.mouse || [r.width / 2, r.height / 2];
    modal = { type, axis: null, typed: "", from: m.slice(), at: m.slice(), snap: false };
    const s = projector()(edit.pivot);
    modal.pivotPx = s || [r.width / 2, r.height / 2];
    if (gizmo.object) gizmo.detach();
    canvas.style.cursor = type === "G" ? "move" : "crosshair";
    modalUpdate();
    return true;
  };
  view.modalActive = () => !!modal;
  function modalMatrix() {
    const T = new THREE.Matrix4(), pv = new THREE.Vector3().fromArray(edit.pivot);
    const toLocalDir = (v) => v.clone().transformDirection(holder.matrixWorld.clone().invert());
    const typed = modal.typed !== "" && modal.typed !== "-" && modal.typed !== "." ? parseFloat(modal.typed) : null;
    const axis = modal.axis != null ? AX[modal.axis] : null;
    let label;
    if (modal.type === "G") {
      let d = new THREE.Vector3();
      if (typed != null) d.copy(axis || AX[0]).multiplyScalar(typed);
      else if (axis) {
        const o = toWorld(edit.pivot), dir = axis.clone().transformDirection(holder.matrixWorld);
        const t = axisParam(ray(modal.at), o, dir) - axisParam(ray(modal.from), o, dir);
        d.copy(axis).multiplyScalar(t / holder.getWorldScale(new THREE.Vector3()).x);
      } else {
        const o = toWorld(edit.pivot), plane = new THREE.Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()), o);
        const a = ray(modal.from).intersectPlane(plane, new THREE.Vector3()), b = ray(modal.at).intersectPlane(plane, new THREE.Vector3());
        if (a && b) d = holder.worldToLocal(b.clone()).sub(holder.worldToLocal(a.clone()));
      }
      if (modal.snap && typed == null) { const st = 0.05 * (view.size || 1); d.set(Math.round(d.x / st) * st, Math.round(d.y / st) * st, Math.round(d.z / st) * st); }
      T.makeTranslation(d.x, d.y, d.z);
      label = "Move " + (axis ? "XYZ"[modal.axis] + " " : "") + [d.x, d.y, d.z].map((x) => x.toFixed(3)).join(", ");
    } else if (modal.type === "R") {
      let ang;
      if (typed != null) ang = typed * Math.PI / 180;
      else {
        const p = modal.pivotPx, a0 = Math.atan2(-(modal.from[1] - p[1]), modal.from[0] - p[0]), a1 = Math.atan2(-(modal.at[1] - p[1]), modal.at[0] - p[0]);
        ang = a1 - a0;
      }
      const toViewer = toLocalDir(camera.getWorldDirection(new THREE.Vector3()).negate()).normalize();
      let ax = axis ? axis.clone() : toViewer;
      if (axis && typed == null && axis.dot(toViewer) < 0) ang = -ang;   // turn the way the mouse turns on screen
      if (modal.snap && typed == null) ang = Math.round(ang / (Math.PI / 36)) * (Math.PI / 36);   // 5 degrees
      T.makeTranslation(pv.x, pv.y, pv.z).multiply(new THREE.Matrix4().makeRotationAxis(ax.normalize(), ang))
        .multiply(new THREE.Matrix4().makeTranslation(-pv.x, -pv.y, -pv.z));
      label = "Rotate " + (axis ? "XYZ"[modal.axis] + " " : "") + (ang * 180 / Math.PI).toFixed(1) + "°";
    } else {
      let k;
      if (typed != null) k = typed;
      else {
        const p = modal.pivotPx, d0 = Math.hypot(modal.from[0] - p[0], modal.from[1] - p[1]) || 1;
        k = Math.hypot(modal.at[0] - p[0], modal.at[1] - p[1]) / d0;
      }
      if (modal.snap && typed == null) k = Math.round(k * 10) / 10;
      const sv = axis ? [modal.axis === 0 ? k : 1, modal.axis === 1 ? k : 1, modal.axis === 2 ? k : 1] : [k, k, k];
      T.makeTranslation(pv.x, pv.y, pv.z).multiply(new THREE.Matrix4().makeScale(sv[0], sv[1], sv[2]))
        .multiply(new THREE.Matrix4().makeTranslation(-pv.x, -pv.y, -pv.z));
      label = "Scale " + (axis ? "XYZ"[modal.axis] + " " : "") + k.toFixed(3);
    }
    return [T, label];
  }
  function modalUpdate() {
    if (!modal || !edit) return;
    const [M, label] = modalMatrix();
    applyM(M);
    say(label + (modal.typed ? "  [" + modal.typed + "]" : "") + (ed.prop ? "  · proportional " + ed.propRadius.toFixed(2) + " (wheel)" : "")
      + "  - X/Y/Z lock, type a number, Ctrl snaps, Enter/click confirms, Esc/right-click cancels");
  }
  function modalEnd(ok) {
    if (!modal) return;
    modal = null;
    canvas.style.cursor = "";
    if (ok) commit(); else cancel();
    placePivot();
    stats();
  }
  view.modalConfirm = () => modalEnd(true);
  view.modalCancel = () => modalEnd(false);
  view.modalMove = (pt, snap) => { if (!modal) return; modal.at = pt.slice(); modal.snap = !!snap; modalUpdate(); };
  view.modalAxis = (i) => { if (!modal) return; modal.axis = modal.axis === i ? null : i; modalUpdate(); };
  view.modalType = (ch) => {
    if (!modal) return;
    if (ch === "Backspace") modal.typed = modal.typed.slice(0, -1);
    else if (ch === "-") modal.typed = modal.typed.startsWith("-") ? modal.typed.slice(1) : "-" + modal.typed;
    else modal.typed += ch;
    modalUpdate();
  };
  view.setProportional = (on, radius, falloff) => {
    if (on != null) ed.prop = !!on;
    if (radius != null) ed.propRadius = Math.max(0.01, Math.min(2, radius));
    if (falloff && P.FALLOFF[falloff]) ed.falloff = falloff;
    reweigh();
    if (modal) modalUpdate();
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
    if (modal) {                                     // click confirms, right-click cancels
      e.stopImmediatePropagation(); e.preventDefault();
      modalEnd(e.button === 0);
      return;
    }
    if (e.button !== 0) return;                     // middle turns, right pans: the orbit controls keep those
    if (gizmo.object && gizmo.axis) return;        // the move handle
    if (e.altKey) return;                           // Alt / Option is Maya's camera, nothing else
    e.stopImmediatePropagation();
    canvas.setPointerCapture(e.pointerId);
    // Maya's modifiers, for a click and for a box: Shift toggles, Ctrl/Cmd takes away, Ctrl/Cmd+Shift adds
    const mod = e.ctrlKey || e.metaKey;
    const how = mod && e.shiftKey ? "add" : mod ? "sub" : e.shiftKey ? "toggle" : "set";
    gest = { at: ed.mouse, box: false, how: how, click: how };
  }, { capture: true });
  canvas.addEventListener("pointermove", (e) => {
    if (view.mode !== "poly") return;
    ed.mouse = local(e);
    if (modal) { e.stopImmediatePropagation(); view.modalMove(ed.mouse, e.ctrlKey || e.metaKey); return; }
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
  canvas.addEventListener("dblclick", (e) => {
    if (view.mode !== "poly" || !view.poly || modal) return;
    if (ed.mode === "edge") { view.loopSelect(local(e), e.shiftKey ? "add" : "set"); return; }   // Maya: double-click an edge = its loop
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
  canvas.addEventListener("wheel", (e) => {          // proportional radius while moving (Blender: the wheel)
    if (!modal || !ed.prop) return;
    e.preventDefault(); e.stopImmediatePropagation();
    view.setProportional(null, ed.propRadius * (e.deltaY < 0 ? 1.1 : 1 / 1.1));
  }, { capture: true, passive: false });
  document.addEventListener("keydown", (e) => {     // while G/R/S runs, the keys belong to it
    if (!modal) return;
    const k = e.key;
    e.preventDefault(); e.stopImmediatePropagation();
    if (k === "Escape") modalEnd(false);
    else if (k === "Enter" || k === " ") modalEnd(true);
    else if (/^[xyz]$/i.test(k)) view.modalAxis("xyz".indexOf(k.toLowerCase()));
    else if (/^[0-9.]$/.test(k) || k === "-" || k === "Backspace") view.modalType(k);
    else if (k === "o" || k === "O") view.setProportional(!ed.prop);
    else if ((k === "g" || k === "r" || k === "s") && k.toUpperCase() !== modal.type) {   // switch tool mid-move, like Blender
      const pt = modal.at;
      modalEnd(false); view.modalStart(k.toUpperCase()); view.modalMove(pt);
    }
  }, true);

  // keep everything in step with the viewer
  const setMode = view.setMode;
  view.setMode = (m) => {
    if (modal) modalEnd(false);
    setMode(m);
    if (m !== "poly") { if (gizmo.object) gizmo.detach(); if (ed.xray) { ed.xray = false; xrayLook(); } }
    drawOverlay(); placePivot(); stats();
  };
  const onChange = () => { ed.topoOf = null; if (!edit) drawOverlay(); };
  const showPoly = view.showPoly;
  view.showPoly = (poly, keepView, noUndo) => { showPoly(poly, keepView, noUndo); onChange(); };
  const undo = view.undo, redo = view.redo;
  // after an undo / redo the handle must start from where the selection is NOW: re-attach it, or the first drag
  // after Ctrl+Z starts from the old place and does nothing (found 2026-10-19)
  const rehandle = () => { if (gizmo.object) { gizmo.object.updateMatrixWorld(true); (gizmo.getHelper ? gizmo.getHelper() : gizmo).updateMatrixWorld(true); } };
  view.undo = () => { if (modal) { modalEnd(false); return; } undo(); onChange(); placePivot(); rehandle(); };
  view.redo = () => { redo(); onChange(); placePivot(); rehandle(); };
  view.gizmo = gizmo;
  view.project = (p) => projector()(p);            // a mesh point -> canvas pixels (tests, scripts)
}
