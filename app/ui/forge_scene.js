// Forge's scene - the pro DAG: transform nodes with shapes and children, real pivots, and the Outliner
// (owner 2026-10-19: "the groups different object and hierarchy, history and transforms. Reset pivot all of it ...
// especially the outliner and the logic behind it all"). The behaviour is read off the reference package itself -
// docs/FORGE_PRO_SPEC.md - and re-written here; no the vendor code is used.
//
// Every node is two three.js groups:
//     outer  (the transform node: position = T + C + P, rotation R, scale S)
//       inner  (position -P: the pivot offset)
//         shape mesh + the children's outer groups
// so   world = parent * T(translate) * T(C) * T(P) * R * S * T(-P)   - the pro matrix with one pivot P and the
// pivot-translate C that keeps the object still when its pivot moves: C += (I - R*S)(P_old - P_new).
// The Channel Box shows T, which a pivot move never changes (the pro rule).
//
// One node is the WORKING object: its inner group is the viewer's `holder`, the mesh the sculpt and poly tools
// edit. Any other mesh node becomes the working one when you edit it (api.makeWorking) - the holder moves into
// that node and the old working object keeps a static copy of its geometry - so every object is editable, like
// pro, while the tools still edit one mesh.
"use strict";

// the pro construction-history node for each Forge step
const FORGE_HIST_NODE = { extrude: "polyExtrudeFace", inset: "polyExtrudeFace", flip: "polyNormal", delete: "deleteComponent",
  smooth: "polySmoothFace", deleteVerts: "deleteComponent", deleteEdges: "polyDelEdge", dynamesh: "polyRemesh",
  sculpt: "sculpt", loopCut: "polySplitRing", loopcut: "polySplitRing", mirror: "polyMirror", merge: "polyMergeVert", fillHole: "polyCloseBorder", bevel: "polyBevel", tweak: "polyTweak" };

function scnEl(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

const FORGE_SEL_LEAD = 0x65fdcd, FORGE_SEL_REST = 0xf2f4f7;     // pro: the last selected teal-green (measured off the reference package), the rest white

function forgeSceneAttach(view, ctx) {
  const { THREE, scene, holder, material } = ctx;
  if (!scene || !holder) return null;

  const tree = view.tree = {
    nodes: [], byId: {}, next: 1, sel: [], anchor: 0, hiddenLast: [],
    rootId: 0, panel: null, list: null,
    sets: [], setNext: 1,                           // Create > Sets: saved selections (objects or one mesh's components)
    layers: [], layerNext: 1, curLayer: 0,          // the pro Display Layers (the Layer Editor under the Channel Box); 0 = Default
    time: { frame: 1, start: 1, end: 24, fps: 24, playing: false },   // the pro Time Slider + the playing flag
    autoKey: false, clipKeys: null,                                   // the pro Auto Keyframe + the animation clipboard
    defLayer: { visible: true, template: false, ref: false },          // the Display Layers' Default row (a node on no layer)
  };
  const node = (id) => tree.byId[id];
  const kidsOf = (id) => tree.nodes.filter((n) => n.parent === id);

  // ---------------------------------------------------------------- pivots (the pro transform matrix)
  function rsMatrix(n) { return new THREE.Matrix4().compose(new THREE.Vector3(), n.grp.quaternion, n.grp.scale); }
  function translateOf(n) { return n.grp.position.clone().sub(n.pc).sub(n.piv); }
  // one channel's value at a frame: before the first key / after the last it holds, between them the key's own
  // interpolation (step, linear, bezier = a smooth in / out ease) - the pro Time Slider's keys
  function keyValue(arr, f) {
    if (!arr || !arr.length) return null;
    if (f <= arr[0].f) return arr[0].v;
    const last = arr[arr.length - 1];
    if (f >= last.f) return last.v;
    for (let i = 0; i < arr.length - 1; i++) {
      const a = arr[i], b = arr[i + 1];
      if (f >= a.f && f <= b.f) {
        if (a.i === "step") return a.v;
        const t = (f - a.f) / Math.max(1e-9, b.f - a.f);
        const e = a.i === "bezier" ? t * t * (3 - 2 * t) : t;
        return a.v + (b.v - a.v) * e;
      }
    }
    return last.v;
  }
  function place(n, T) {
    n.grp.position.copy(T).add(n.pc).add(n.piv);
    n.inner.position.copy(n.piv).multiplyScalar(-1);
    n.grp.updateMatrixWorld(true);
    view.dirty = true;
  }
  function setPivot(n, P) {                          // the object does not move, its translate does not change
    const T = translateOf(n);
    const d = n.piv.clone().sub(P);
    const rsd = d.clone().applyMatrix4(rsMatrix(n));
    n.pc.add(d.sub(rsd));
    n.piv.copy(P);
    place(n, T);
  }
  function contentBox(n) {                           // the node's bounding box in its own (inner) space, children in
    n.grp.updateMatrixWorld(true);
    const inv = n.inner.matrixWorld.clone().invert();
    const box = new THREE.Box3();
    n.inner.traverse((o) => {
      if (!o.isMesh || !o.geometry || o.name === "forge-sel" || !o.visible) return;
      if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
      const b = o.geometry.boundingBox.clone().applyMatrix4(new THREE.Matrix4().multiplyMatrices(inv, o.matrixWorld));
      box.union(b);
    });
    return box;
  }

  // ---------------------------------------------------------------- the nodes
  function nextName(base) {                          // pCube1 -> pCube2: the pro next free number
    const stem = String(base || "object").replace(/\d+$/, "") || "object";
    let hi = 0;
    for (const n of tree.nodes) {
      const m = n.name.match(/^(.*?)(\d+)$/);
      if (m && m[1] === stem) hi = Math.max(hi, +m[2]);
      else if (n.name === stem) hi = Math.max(hi, 0);
    }
    return stem + (hi + 1);
  }
  function makeNode(name, kind, parent, inner) {
    const grp = new THREE.Group();
    const inn = inner || new THREE.Group();
    grp.add(inn);
    const n = { id: tree.next++, name: name, grp: grp, inner: inn, kind: kind, parent: parent || 0, visible: true,
      open: true, piv: new THREE.Vector3(), pc: new THREE.Vector3(), tri: null, poly: null, hist: null,
      rotOrder: "XYZ", chLock: {}, chHide: {}, attrs: [], keys: null };   // the pro Channel Box (rotate order, locked / hidden channels, custom attributes) + the animation keys
    grp.name = name; grp.userData.forgeNode = n.id;
    tree.nodes.push(n); tree.byId[n.id] = n;
    const dest = parent ? node(parent).inner : scene;
    dest.add(grp);
    return n;
  }

  // the working object: an outer transform around the viewer's holder
  function ensureRoot() {
    if (tree.rootId) return node(tree.rootId);
    const T = holder.position.clone(), Q = holder.quaternion.clone(), S = holder.scale.clone();
    if (holder.parent) holder.parent.remove(holder);
    holder.position.set(0, 0, 0); holder.quaternion.identity(); holder.scale.set(1, 1, 1);
    const r = makeNode("object1", "mesh", 0, holder);
    r.root = true; r.auto = true;              // named for real by the first Create / load
    r.grp.position.copy(T); r.grp.quaternion.copy(Q); r.grp.scale.copy(S);
    tree.rootId = r.id;
    return r;
  }
  const root = () => ensureRoot();

  function shapeOf(n) {                              // the node's own mesh (not its children's)
    if (n.root) return ctx.mesh ? ctx.mesh() : (n.inner.children.find((o) => o.isMesh && o.name === "forge") || null);
    return n.inner.children.find((o) => o.isMesh && o.name === "shape") || null;
  }
  function hasGeometry(n) { const s = shapeOf(n); return !!(s && s.geometry && s.geometry.attributes.position && s.geometry.attributes.position.count); }
  // the empty working object (the viewer's holder before anything is made, or after its mesh was deleted) is not a
  // scene object yet: like a new pro scene, the Outliner shows only the hidden cameras until you Create or load
  // something (owner 2026-10-21: "nothing in the scene no empty transform or box just the hidden cams")
  // the pro template look: a templated object draws as a thin grey wire, unlit (and back when the T goes off)
  function templateLook(n, on) {
    const s = shapeOf(n); if (!s || !s.material || Array.isArray(s.material)) return;
    const m = s.material, u = s.userData;
    if (on && !u.tplKeep) { u.tplKeep = { wireframe: m.wireframe, transparent: m.transparent, opacity: m.opacity, depthWrite: m.depthWrite };
      m.wireframe = true; m.transparent = true; m.opacity = 0.35; m.depthWrite = false; m.needsUpdate = true; }
    else if (!on && u.tplKeep) { Object.assign(m, u.tplKeep); delete u.tplKeep; m.needsUpdate = true; }
  }
  const ghost = (n) => !!(n && n.root && n.kind === "mesh" && !hasGeometry(n) && !kidsOf(n.id).length);

  function geometryFrom(tri, col) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(tri.pos.slice ? tri.pos.slice() : tri.pos, 3));
    if (col && col.length) {
      const c = new Float32Array(tri.pos.length);
      if (col.length === tri.pos.length) c.set(col); else for (let i = 0; i < c.length; i++) c[i] = col[i % col.length];
      g.setAttribute("color", new THREE.BufferAttribute(c, 3));
    }
    g.setIndex(new THREE.BufferAttribute(tri.idx.slice ? tri.idx.slice() : tri.idx, 1));
    g.computeVertexNormals();
    g.computeBoundingBox();
    return g;
  }
  function staticShape(tri, col) {
    const m = new THREE.Mesh(geometryFrom(tri, col), material ? material.clone() : undefined);
    if (m.material && !col) m.material.vertexColors = false;
    m.name = "shape";
    return m;
  }
  function triOfShape(n) {                           // a node's mesh as plain triangles in its own space
    if (n.root) {
      const t = view.triangles ? view.triangles() : null;
      return t ? { pos: t.pos, idx: t.idx, col: view.sm && view.sm.col && view.sm.col.length === t.pos.length ? view.sm.col.slice() : null } : null;
    }
    const s = shapeOf(n);
    if (!s) return null;
    const g = s.geometry, idx = g.index ? g.index.array : Uint32Array.from({ length: g.attributes.position.count }, (_, i) => i);
    return { pos: g.attributes.position.array.slice(), idx: Uint32Array.from(idx), col: g.attributes.color ? g.attributes.color.array.slice() : null };
  }

  // a node's mesh as a poly cage {v, f} in its own space: the edited object's cage, a kept cage, or its triangles
  function polyOfNode(n) {
    const P = window.ForgePoly;
    if (!P) return null;
    if (n.root && view.poly) return P.clone(view.poly);
    if (!n.root && n.poly) return P.clone(n.poly);
    const t = triOfShape(n);
    return t && t.pos.length ? P.fromTriangles(t.pos, t.idx) : null;
  }
  function polyNode(name, poly, parentId) {         // a new static mesh node holding this cage
    const P = window.ForgePoly;
    const n = makeNode(nextName(name), "mesh", parentId || 0, null);
    const t = P.triangulate(poly);
    n.inner.add(staticShape({ pos: t.pos, idx: t.idx }, null));
    n.poly = poly;
    return n;
  }

  // transform every welded vertex of the working mesh (undoable), then push it back to the GPU
  function bakeRoot(m) {
    const sm = view.sm;
    if (!sm) return false;
    if (view.pushUndo && view.undoState) view.pushUndo(view.undoState());
    else if (view.undoStack) {
      view.undoStack.push({ sm: sm, wpos: sm.wpos.slice(), poly: view.poly, tri2face: view.tri2face });
      if (view.undoStack.length > 40) view.undoStack.shift();
      view.redoStack = [];
    }
    const v = new THREE.Vector3();
    for (let i = 0; i < sm.n; i++) {
      v.set(sm.wpos[i * 3], sm.wpos[i * 3 + 1], sm.wpos[i * 3 + 2]).applyMatrix4(m);
      sm.wpos[i * 3] = v.x; sm.wpos[i * 3 + 1] = v.y; sm.wpos[i * 3 + 2] = v.z;
    }
    if (typeof forgeSync === "function") forgeSync(sm);
    if (typeof forgeNormals === "function") forgeNormals(sm);
    if (view.refreshMesh) view.refreshMesh();
    if (view.poly) { view.poly = null; view.tri2face = null; }         // the poly cage no longer matches
    return true;
  }

  function isAncestor(a, b) {                        // is a an ancestor of b?
    for (let p = node(b) && node(b).parent; p; p = node(p) ? node(p).parent : 0) if (p === a) return true;
    return false;
  }
  function order() {                                 // display order: depth first, siblings in array order
    const out = [];
    const walk = (parent) => { for (const n of tree.nodes) if (n.parent === parent) { out.push(n); walk(n.id); } };
    walk(0);
    return out;
  }
  function moveInArray(n, beforeId) {                // re-order n among its siblings (before another node or last)
    tree.nodes = tree.nodes.filter((x) => x !== n);
    const at = beforeId ? tree.nodes.findIndex((x) => x.id === beforeId) : -1;
    if (at < 0) tree.nodes.push(n); else tree.nodes.splice(at, 0, n);
  }

  function cloneNode(src, parentId) {                // a deep copy with its hierarchy (the pro Duplicate)
    const n = makeNode(nextName(src.name), src.kind, parentId, null);
    n.grp.quaternion.copy(src.grp.quaternion); n.grp.scale.copy(src.grp.scale);
    n.piv.copy(src.piv); n.pc.copy(src.pc);
    place(n, translateOf(src));
    n.visible = src.visible; n.grp.visible = src.visible;
    if (src.kind === "mesh") {
      const t = triOfShape(src);
      if (t) n.inner.add(staticShape(t, t.col));
      n.poly = src.root ? view.poly : src.poly;
      n.hist = src.root ? (typeof forgeModel !== "undefined" && forgeModel.hist ? JSON.parse(JSON.stringify(forgeModel.hist)) : null)
        : (src.hist ? JSON.parse(JSON.stringify(src.hist)) : null);
    }
    if (src.kind === "imagePlane") {                 // a free image plane: the same picture on a new plane
      const sh = shapeOf(src);
      if (sh) { const c = sh.clone(); c.material = sh.material.clone(); c.name = "shape"; n.inner.add(c); }
      n.image = src.image;
    }
    for (const k of kidsOf(src.id)) cloneNode(k, n.id);
    return n;
  }

  // ---------------------------------------------------------------- selection highlight in the viewport
  const marks = new Map(), edgeCache = new WeakMap();
  // the edges a selection wire shows: a modelled mesh's POLYGON edges (its cage), not the triangle diagonals
  function wireEdges(o) {
    const P = window.ForgePoly;
    let cage = null;
    if (ctx.mesh && o === ctx.mesh()) cage = view.poly;
    else { const id = (() => { for (let p = o; p; p = p.parent) if (p.userData && p.userData.forgeNode) return p.userData.forgeNode; return 0; })(); const n = id && node(id); cage = n && n.poly; }
    if (!cage || !P || !P.edges) return new THREE.EdgesGeometry(o.geometry, 1);
    const E = P.edges(cage), lp = new Float32Array(E.length * 6);
    E.forEach((e, i) => { lp.set(cage.v[e.a], i * 6); lp.set(cage.v[e.b], i * 6 + 3); });
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(lp, 3));
    return g;
  }
  function drawMarks() {
    for (const [id, h] of marks) { if (h.parent) h.parent.remove(h); h.geometry.dispose(); marks.delete(id); }
    tree.sel.forEach((id, i) => {
      const n = node(id);
      if (!n) return;
      const col = new THREE.Color(i === tree.sel.length - 1 ? FORGE_SEL_LEAD : FORGE_SEL_REST);
      // pro draws the selected object's own edges in the selection colour - a wireframe, not a box. The edges are the
      // polygon edges (EdgesGeometry hides the flat diagonals a quad is split into); a very big mesh keeps the box.
      const meshes = [];
      // the smooth preview (keys 2 / 3) is a display: the wire is the cage's, even while the cage itself is hidden
      n.inner.traverse((o) => { if (o.isMesh && o.geometry && o.name !== "forge-sel" && o.name !== "forge-smooth" && (o.visible || o === (ctx.mesh && ctx.mesh()))) meshes.push(o); });
      const tris = meshes.reduce((t, o) => t + (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count) / 3, 0);
      if (meshes.length && tris <= 80000) {
        const grp = new THREE.Group(); grp.name = "forge-sel";
        n.grp.updateMatrixWorld(true);
        const inv = n.inner.matrixWorld.clone().invert();
        for (const o of meshes) {
          // the edges are cached per geometry and only rebuilt when the mesh changed (tree.build runs often)
          const ver = o.geometry.attributes.position.version + ":" + (o.geometry.index ? o.geometry.index.version : 0);
          let ec = edgeCache.get(o.geometry);
          if (!ec || ec.ver !== ver) { ec = { ver, geo: wireEdges(o) }; edgeCache.set(o.geometry, ec); }
          const lines = new THREE.LineSegments(ec.geo,
            new THREE.LineBasicMaterial({ color: col, depthTest: true, transparent: true, opacity: 0.95 }));
          lines.matrixAutoUpdate = false;
          lines.matrix.multiplyMatrices(inv, o.matrixWorld);
          lines.renderOrder = 2; lines.raycast = () => {};
          lines.material.polygonOffset = true;
          lines.userData.src = o;
          grp.add(lines);
        }
        grp.raycast = () => {};
        grp.geometry = { dispose: () => grp.children.forEach((c) => c.material.dispose()) };   // the edges stay cached
        n.inner.add(grp); marks.set(id, grp);
        return;
      }
      const box = contentBox(n);
      if (box.isEmpty()) return;
      const h = new THREE.Box3Helper(box, col);
      h.name = "forge-sel"; h.raycast = () => {};
      n.inner.add(h); marks.set(id, h);
    });
    view.dirty = true;
  }

  // ---------------------------------------------------------------- the API (menus, hotkeys, Outliner, tests)
  // a component selection kept by where its vertices are (a session join / split renumbers them)
  function multiSelKeep() {
    const vs = view.selectedVerts ? view.selectedVerts() : [];
    if (!vs.length || !view.poly) return null;
    scene.updateMatrixWorld(true);
    const M = root().inner.matrixWorld, p = new THREE.Vector3();
    return { mode: view.selModeNow ? view.selModeNow() : null, at: vs.map((i) => p.fromArray(view.poly.v[i] || [0, 0, 0]).applyMatrix4(M).toArray().map((x) => Math.round(x * 1e4))) };
  }
  function multiSelRestore(k) {
    if (!k || !view.poly || !view.selectItems) return;
    scene.updateMatrixWorld(true);
    const want = new Set(k.at.map((a) => a.join(","))), M = root().inner.matrixWorld, p = new THREE.Vector3(), ids = [];
    view.poly.v.forEach((q, i) => { const w = p.fromArray(q).applyMatrix4(M).toArray().map((x) => Math.round(x * 1e4)).join(","); if (want.has(w)) ids.push(i); });
    view.selectItems("vert", ids, "set");
    if (k.mode && k.mode !== "vert" && view.setSelMode) view.setSelMode(k.mode);
  }

  const api = {
    node: node,
    kids: kidsOf,
    list: () => tree.nodes.slice(),
    isGhost: (id) => ghost(node(id)),
    sceneNodes: () => tree.nodes.filter((n) => !ghost(n)),     // what the Outliner shows (the empty working object is not one)
    order: () => order().map((n) => n.id),
    root: () => root(),
    nextName: nextName,

    // a static copy of the working mesh as a new object (kept for older callers - Duplicate is the pro way)
    add(name) {
      const r = root();
      if (!hasGeometry(r)) return null;
      const n = cloneNode(r, r.parent);
      const cur = tree.layers.find((l) => l.id === tree.curLayer); if (cur) cur.nodes.add(n.id);
      if (name) api.rename(n.id, name);
      tree.build(); api.select(n.id);
      return n;
    },

    // the pro Duplicate (Ctrl/Cmd+D): every selected node with its hierarchy, as a sibling, in place
    duplicate(name, ids) {
      const list = (ids || (tree.sel.length ? tree.sel : [root().id])).map(node).filter(Boolean)
        .filter((n, _, all) => !all.some((o) => o !== n && isAncestor(o.id, n.id)));
      if (!list.length) return null;
      const made = list.map((src) => {
        const c = cloneNode(src, src.parent);
        moveInArray(c, (tree.nodes[tree.nodes.indexOf(src) + 1] || {}).id);
        return c;
      });
      if (name && made.length === 1) api.rename(made[0].id, name);
      tree.lastDup = made.map((c, i) => ({ src: list[i].id, copy: c.id }));
      tree.sel = made.map((c) => c.id); tree.build();
      return made[made.length - 1];
    },

    // the pro Duplicate with Transform (Shift+D): one more copy, offset again by what moved the last copy
    duplicateWithTransform() {
      const pairs = (tree.lastDup || []).filter((p) => node(p.src) && node(p.copy) && tree.sel.includes(p.copy));
      if (!pairs.length) return api.duplicate();
      const made = pairs.map(({ src, copy }) => {
        const a = node(src).grp, b = node(copy).grp;
        a.updateMatrix(); b.updateMatrix();
        const delta = b.matrix.clone().multiply(a.matrix.clone().invert());
        const c = cloneNode(node(copy), node(copy).parent);
        c.grp.matrix.copy(delta.multiply(b.matrix));
        c.grp.matrix.decompose(c.grp.position, c.grp.quaternion, c.grp.scale);
        c.grp.updateMatrixWorld(true);
        return { src: copy, copy: c.id };
      });
      tree.lastDup = made;
      tree.sel = made.map((p) => p.copy); tree.build();
      return node(made[made.length - 1].copy);
    },

    rename(id, name) {
      const n = node(id); if (!n || !name) return false;
      n.name = String(name).trim().replace(/\s+/g, "_") || n.name; n.grp.name = n.name;
      tree.build(); return true;
    },

    setVisible(id, on) {
      const n = node(id); if (!n) return false;
      n.visible = !!on; api.applyLayers();
      tree.build(); view.dirty = true; return true;
    },
    toggleVisible(ids) { for (const id of ids || tree.sel) { const n = node(id); if (n) api.setVisible(id, !n.visible); } },
    hide(ids) { const l = (ids || tree.sel).filter((id) => node(id) && node(id).visible); for (const id of l) api.setVisible(id, false); tree.hiddenLast = l; return l.length; },
    show(ids) { for (const id of ids || tree.sel) api.setVisible(id, true); },
    showLastHidden() { const l = tree.hiddenLast || []; for (const id of l) api.setVisible(id, true); tree.hiddenLast = []; return l.length; },
    hideUnselected() {
      const keep = new Set();
      for (const id of tree.sel) { keep.add(id); for (let p = node(id) && node(id).parent; p; p = node(p).parent) keep.add(p);
        for (const n of tree.nodes) if (isAncestor(id, n.id)) keep.add(n.id); }
      return api.hide(tree.nodes.filter((n) => !keep.has(n.id)).map((n) => n.id));
    },
    showAll() { for (const n of tree.nodes) api.setVisible(n.id, true); },

    // ---- Display Layers (the pro Layer Editor under the Channel Box). A layer owns a set of nodes and can hide
    // or template them together; 0 is the Default layer (always there). An object shows when it is visible AND no
    // layer it is on is hidden or templated - the pro layer-over-object rule.
    layerList() { return tree.layers.map((l) => ({ id: l.id, name: l.name, color: l.color, visible: l.visible, template: l.template, ref: !!l.ref, count: l.nodes.size, current: l.id === tree.curLayer })); },
    layerOf(nid) { for (const l of tree.layers) if (l.nodes.has(nid)) return l.id; return 0; },
    layersTemplate(nid) { for (const l of tree.layers) if (l.nodes.has(nid) && l.template) return true; return api.layerOf(nid) === 0 && tree.defLayer.template; },
    layersRef(nid) { for (const l of tree.layers) if (l.nodes.has(nid) && l.ref) return true; return api.layerOf(nid) === 0 && tree.defLayer.ref; },
    // R (reference) and T (template) both lock the objects: shown, never selected by a click, a box or the Outliner
    layersLocked(nid) { return api.layersTemplate(nid) || api.layersRef(nid); },
    layerNorm(n) {
      if (!n.visible) return false;
      for (const l of tree.layers) if (l.nodes.has(n.id) && !l.visible) return false;
      return api.layerOf(n.id) === 0 ? tree.defLayer.visible : true;   // a node on no layer answers to Default
    },   // T templates (unselectable), it does not hide

    applyLayers() {
      for (const n of tree.nodes) {
        n.templated = api.layersTemplate(n.id); n.referenced = api.layersRef(n.id);
        n.grp.visible = api.layerNorm(n);
        templateLook(n, n.templated);
      }
      // a templated object leaves the selection (the pro layer rule: a template cannot be selected at all)
      const keep = tree.sel.filter((id) => !api.layersTemplate(id));
      if (keep.length !== tree.sel.length) { tree.sel = keep; if (api.onSelect) api.onSelect(); }
      view.dirty = true; return true;
    },
    layerAdd(name) {
      const l = { id: tree.layerNext++, name: String(name || ("layer" + tree.layerNext)).trim().replace(/\s+/g, "_"), color: 0x6e8fa8, visible: true, template: false, ref: false, nodes: new Set() };
      tree.layers.push(l); tree.curLayer = l.id;
      if (tree.syncLayers) tree.syncLayers(); return l;
    },
    layerRemove(id) { const i = tree.layers.findIndex((l) => l.id === id); if (i < 0) return false; tree.layers.splice(i, 1); if (tree.curLayer === id) tree.curLayer = 0; api.applyLayers(); tree.build(); return true; },
    layerRename(id, name) { const l = tree.layers.find((x) => x.id === id); if (!l || !String(name || "").trim()) return false; l.name = String(name).trim().replace(/\s+/g, "_"); tree.build(); return true; },
    layerSetVisible(id, on) { const l = tree.layers.find((x) => x.id === id) || (id === 0 ? tree.defLayer : null); if (!l) return false; l.visible = !!on; api.applyLayers(); tree.build(); return true; },
    layerSetTemplate(id, on) { const l = tree.layers.find((x) => x.id === id) || (id === 0 ? tree.defLayer : null); if (!l) return false; l.template = !!on; if (on) l.ref = false; api.applyLayers(); tree.build(); return true; },
    // R: reference - drawn as it is, but a click goes through it (T and R are one choice in the pro layer: blank / T / R)
    layerSetRef(id, on) { const l = tree.layers.find((x) => x.id === id) || (id === 0 ? tree.defLayer : null); if (!l) return false; l.ref = !!on; if (on) l.template = false; api.applyLayers(); tree.build(); return true; },
    layerSetColor(id, c) { const l = tree.layers.find((x) => x.id === id); if (!l) return false; l.color = c; tree.build(); return true; },
    layerCurrent(id) { tree.curLayer = tree.layers.some((l) => l.id === id) ? id : 0; tree.build(); return true; },
    layerAssign(id, ids) {                            // move nodes onto one layer (off every other)
      const list = (ids || tree.sel).filter((nid) => node(nid));
      for (const l of tree.layers) for (const nid of list) l.nodes.delete(nid);
      const l = tree.layers.find((x) => x.id === id);
      if (l) for (const nid of list) l.nodes.add(nid);
      api.applyLayers(); tree.build(); return true;
    },

    remove(id) {                                     // the node and everything under it (the pro Delete)
      const n = node(id);
      if (!n) return false;
      for (const l of tree.layers) l.nodes.delete(id);
      if (n.root || isAncestor(id, tree.rootId)) {   // never delete the holder: keep the children, empty the mesh
        if (n.root) { for (const k of kidsOf(id)) api.reparent(k.id, n.parent); return false; }
        api.reparent(tree.rootId, n.parent);
      }
      for (const k of kidsOf(id)) api.remove(k.id);
      if (n.grp.parent) n.grp.parent.remove(n.grp);
      n.inner.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
      tree.nodes = tree.nodes.filter((x) => x !== n); delete tree.byId[id];
      tree.sel = tree.sel.filter((x) => x !== id);
      tree.build(); return true;
    },
    removeSelected() { let k = 0; for (const id of tree.sel.slice()) if (api.remove(id)) k++; return k; },

    // parent under ANY node (pro parents under any transform); three.js' attach() keeps the world transform
    reparent(id, parentId, beforeId) {
      const n = node(id), p = parentId ? node(parentId) : null;
      if (!n || (parentId && !p) || n === p || (p && isAncestor(n.id, p.id))) return false;
      const dest = p ? p.inner : scene;
      if (n.grp.parent !== dest) dest.attach(n.grp);
      n.parent = p ? p.id : 0;
      moveInArray(n, beforeId || 0);
      tree.build(); return true;
    },
    // the pro p: the LAST selected is the parent of the others; Shift+P: back to the world
    parentSelected() {
      if (tree.sel.length < 2) return false;
      const parent = tree.sel[tree.sel.length - 1];
      for (const id of tree.sel.slice(0, -1)) api.reparent(id, parent);
      return true;
    },
    unparentSelected() { for (const id of tree.sel) api.reparent(id, 0); return tree.sel.length > 0; },

    // the pro Group: a new transform, translate 0, pivot at the centre of its contents, under the selection's parent
    group(name, ids) {
      const list = (ids && ids.length ? ids : tree.sel).map(node).filter(Boolean)
        .filter((n, _, all) => !all.some((o) => o !== n && isAncestor(o.id, n.id)));
      const parentId = list.length ? list[0].parent : 0;
      const g = makeNode(name || nextName("group"), "group", parentId && list.every((n) => n.parent === parentId) ? parentId : 0, null);
      if (list.length) moveInArray(g, list[0].id);
      for (const n of list) { g.inner.attach(n.grp); n.parent = g.id; }
      const box = contentBox(g);
      if (!box.isEmpty()) setPivot(g, box.getCenter(new THREE.Vector3()));
      tree.sel = [g.id]; tree.build();
      return g;
    },

    ungroup(id) {
      const g = node(id);
      if (!g || g.kind !== "group") return false;
      const dest = g.parent ? node(g.parent).inner : scene;
      for (const k of kidsOf(id)) { dest.attach(k.grp); k.parent = g.parent; moveInArray(k, g.id); }
      if (g.grp.parent) g.grp.parent.remove(g.grp);
      tree.nodes = tree.nodes.filter((x) => x !== g); delete tree.byId[id];
      tree.sel = tree.sel.filter((x) => x !== id);
      tree.build(); return true;
    },

    // how: "set" | "toggle" | "add" | "remove" | "range"  (true means toggle, for older callers)
    select(id, how) {
      if (id != null && id !== 0 && (api.layersTemplate(id) || ghost(node(id)))) return tree.sel.slice();   // templated: shown, not selectable (a referenced one still picks from the Outliner, as in pro)
      if (how === true) how = "toggle";
      if (id == null) tree.sel = [];
      else if (how === "toggle") tree.sel = tree.sel.includes(id) ? tree.sel.filter((x) => x !== id) : tree.sel.concat([id]);
      else if (how === "add") tree.sel = tree.sel.filter((x) => x !== id).concat([id]);
      else if (how === "remove") tree.sel = tree.sel.filter((x) => x !== id);
      else if (how === "range") {
        const ids = order().map((n) => n.id), a = ids.indexOf(tree.anchor || id), b = ids.indexOf(id);
        tree.sel = a < 0 || b < 0 ? [id] : ids.slice(Math.min(a, b), Math.max(a, b) + 1);
        if (a > b) tree.sel.reverse();
      } else tree.sel = node(id) ? [id] : [];
      if (id != null && how !== "range") tree.anchor = id;
      tree.build();
      if (api.onSelect) api.onSelect();
      return tree.sel.slice();
    },
    selectMany(ids, how) {                           // a marquee: set / toggle / add / remove many at once
      ids = ids.filter((id) => node(id) && !api.layersLocked(id) && !ghost(node(id)));
      if (how === "toggle") for (const id of ids) tree.sel = tree.sel.includes(id) ? tree.sel.filter((x) => x !== id) : tree.sel.concat([id]);
      else if (how === "add") tree.sel = tree.sel.filter((x) => !ids.includes(x)).concat(ids);
      else if (how === "remove") tree.sel = tree.sel.filter((x) => !ids.includes(x));
      else tree.sel = ids.slice();
      tree.build(); if (api.onSelect) api.onSelect();
      return tree.sel.slice();
    },
    selectAll() { return api.selectMany(tree.nodes.filter((n) => n.parent === 0).map((n) => n.id), "set"); },
    selectNone() { return api.selectMany([], "set"); },
    invertSelection() { return api.selectMany(tree.nodes.filter((n) => n.parent === 0 && !tree.sel.includes(n.id)).map((n) => n.id), "set"); },
    selectHierarchy() {
      const ids = new Set(tree.sel);
      for (const id of tree.sel) for (const n of tree.nodes) if (isAncestor(id, n.id)) ids.add(n.id);
      return api.selectMany([...ids], "set");
    },
    selected: () => tree.sel.slice(),

    // the pro pick-walk (the arrow keys): up to the parent, down to the first child, left/right to the siblings
    pickWalk(dir) {
      const n = node(tree.sel[tree.sel.length - 1]);
      if (!n) { const first = tree.nodes.find((x) => x.parent === 0); if (first) api.select(first.id); return !!first; }
      let to = null;
      if (dir === "up") to = n.parent ? node(n.parent) : null;
      else if (dir === "down") to = kidsOf(n.id)[0] || null;
      else {
        const sib = kidsOf(n.parent), i = sib.indexOf(n);
        to = sib.length > 1 ? sib[(i + (dir === "right" ? 1 : -1) + sib.length) % sib.length] : null;
      }
      if (!to) return false;
      if (dir === "up" || dir === "down") { const p = node(to.parent); if (p) p.open = true; }
      api.select(to.id);
      return true;
    },

    // the node's own transform - what the pro Channel Box shows (translate excludes the pivot terms)
    transform(id) {
      const n = node(id || api.active().id);
      if (!n) return null;
      const r = n.grp.rotation;
      return { translate: translateOf(n).toArray(), rotate: [r.x, r.y, r.z].map((v) => v * 180 / Math.PI),
               scale: n.grp.scale.toArray(), pivot: n.piv.toArray() };
    },

    setTransform(id, part, axis, value) {
      const n = node(id || api.active().id);
      const v = Number(value);
      if (!n || !isFinite(v)) return false;
      if (part === "translate") { const T = translateOf(n); T.setComponent(axis, v); place(n, T); }
      else {
        const T = translateOf(n);
        if (part === "rotate") n.grp.rotation["xyz"[axis]] = v * Math.PI / 180;
        else if (part === "scale") n.grp.scale["xyz"[axis]] = v === 0 ? 1e-4 : v;
        place(n, T);
      }
      if (tree.selMarks) drawMarks();
      return true;
    },

    // ---- the pro Time Slider: keyframes on the transform channels, the playhead, playback
    keyTimes(id) {
      const n = node(id || api.active().id);
      if (!n || !n.keys) return [];
      const set = new Set();
      for (const k of Object.keys(n.keys)) for (const x of n.keys[k]) set.add(x.f);
      return [...set].sort((a, b) => a - b);
    },
    setKey(id, frame, part, axis, value) {
      const n = node(id || api.active().id);
      if (!n) return false;
      n.keys = n.keys || {};
      const k = part + axis, arr = (n.keys[k] = n.keys[k] || []), f = Math.round(frame), v = Number(value);
      const at = arr.findIndex((x) => x.f === f);
      if (at >= 0) { arr[at].v = Number.isFinite(v) ? v : arr[at].v; }
      else { arr.push({ f: f, v: Number.isFinite(v) ? v : 0, i: "linear" }); arr.sort((a, b) => a.f - b.f); }
      if (tree.syncChannel) tree.syncChannel();
      if (tree.syncKeys) tree.syncKeys();
    if (tree.syncGraph) tree.syncGraph();
      return true;
    },
    deleteKey(id, frame, part, axis) {
      const n = node(id || api.active().id);
      if (!n || !n.keys) return false;
      const f = Math.round(frame);
      const drop = (k) => { const arr = n.keys[k]; if (!arr) return; const i = arr.findIndex((x) => x.f === f); if (i >= 0) { arr.splice(i, 1); if (!arr.length) delete n.keys[k]; } };
      if (part == null) for (const k of Object.keys(n.keys)) drop(k);
      else drop(part + axis);
      if (!Object.keys(n.keys).length) n.keys = null;
      if (tree.syncChannel) tree.syncChannel();
      if (tree.syncKeys) tree.syncKeys();
      return true;
    },
    clearKeys(id) {
      const n = node(id || api.active().id);
      if (!n) return false;
      n.keys = null;
      if (tree.syncChannel) tree.syncChannel();
      if (tree.syncKeys) tree.syncKeys();
      return true;
    },
    setInterp(id, frame, part, axis, how) {
      const n = node(id || api.active().id);
      if (!n || !n.keys) return false;
      const f = Math.round(frame);
      if (part == null) {                       // every channel's key at this frame
        for (const kk of Object.keys(n.keys)) for (const x of n.keys[kk]) if (x.f === f) x.i = how;
      } else {
        const arr = n.keys[part + axis];
        if (!arr) return false;
        for (const x of arr) if (x.f === f) x.i = how;
      }
      if (tree.syncKeys) tree.syncKeys();
      return true;
    },
    // ---- the pro Auto Keyframe: an object that moves writes a key at the playhead
    setAutoKey(on) { tree.autoKey = on == null ? !tree.autoKey : !!on; if (tree.syncKeys) tree.syncKeys(); return tree.autoKey; },
    autoKeyState() { return tree.autoKey; },
    autoKeyNow() {
      if (!tree.autoKey) return 0;
      const n = api.active();
      if (!n) return 0;
      const tr = api.transform();
      if (!tr) return 0;
      let c = 0;
      view.undoChunk("auto key", () => { for (const part of ["translate", "rotate", "scale"]) for (let a = 0; a < 3; a++) if (api.setKey(n.id, tree.time.frame, part, a, tr[part][a])) c++; });
      return c;
    },
    // ---- the pro Edit > Keys: Copy / Paste, and mirror the keys across an axis
    copyAnim(id) {
      const n = node(id || api.active().id);
      if (!n || !n.keys) return 0;
      tree.clipKeys = JSON.parse(JSON.stringify(n.keys));
      return api.keyTimes(n.id).length;
    },
    pasteAnim(id) {
      const n = node(id || api.active().id);
      if (!n || !tree.clipKeys) return false;
      let first = Infinity;
      for (const k of Object.keys(tree.clipKeys)) for (const x of tree.clipKeys[k]) first = Math.min(first, x.f);
      const off = Math.round(tree.time.frame) - (Number.isFinite(first) ? first : 0);
      const clip = JSON.parse(JSON.stringify(tree.clipKeys));
      for (const k of Object.keys(clip)) {
        const arr = clip[k];
        for (const x of arr) x.f += off;
        n.keys = n.keys || {};
        const merged = (n.keys[k] || []).filter((x) => !arr.some((y) => y.f === x.f)).concat(arr);
        merged.sort((a, b) => a.f - b.f);
        n.keys[k] = merged;
      }
      if (tree.syncChannel) tree.syncChannel();
      if (tree.syncKeys) tree.syncKeys();
      return true;
    },
    // mirror a node's keys across an axis plane (the pose is reflected, the frames stay)
    mirrorKeys(id, axis) {
      const n = node(id || api.active().id);
      if (!n || !n.keys) return false;
      const ax = axis | 0;
      const flip = (k, v) => {
        const part = k.slice(0, -1), a = Number(k.slice(-1));
        if (part === "scale") return v;
        if (part === "translate") return a === ax ? -v : v;
        if (part === "rotate") return a === ax ? v : -v;   // an axial vector keeps its own component, flips the rest
        return v;
      };
      for (const k of Object.keys(n.keys)) for (const x of n.keys[k]) x.v = flip(k, x.v);
      for (const nd of tree.nodes) if (nd.keys) api.evalKeys(nd);
      if (tree.syncChannel) tree.syncChannel();
      if (tree.syncKeys) tree.syncKeys();
      return true;
    },
    stepKey(id, dir) {
      const f = tree.time.frame, ts = api.keyTimes(id);
      const next = dir > 0 ? ts.find((t) => t > f + 1e-6) : [...ts].reverse().find((t) => t < f - 1e-6);
      if (next == null) return false;
      api.setFrame(next);
      return true;
    },
    evalKeys(n) {
      if (!n || !n.keys) return;
      const f = tree.time.frame;
      for (const k of Object.keys(n.keys)) {
        const v = keyValue(n.keys[k], f);
        if (v == null) continue;
        const part = k.slice(0, -1), axis = Number(k.slice(-1));
        if (part === "translate") { const T = translateOf(n); T.setComponent(axis, v); place(n, T); }
        else if (part === "rotate") { n.grp.rotation.order = n.rotOrder || "XYZ"; n.grp.rotation["xyz"[axis]] = v * Math.PI / 180; }
        else if (part === "scale") { n.grp.scale["xyz"[axis]] = v === 0 ? 1e-4 : v; }
      }
    },
    setFrame(f) {
      const t = tree.time;
      t.frame = Math.max(t.start, Math.min(t.end, Number(f) || t.start));
      for (const n of tree.nodes) if (n.keys) api.evalKeys(n);
      view.dirty = true;
      if (tree.syncChannel) tree.syncChannel();
      if (tree.syncKeys) tree.syncKeys();
      return t.frame;
    },
    play(on) {
      tree.time.playing = on == null ? true : !!on;
      if (tree.time.playing && view.start) view.start();   // the loop drives the playhead
      if (tree.syncKeys) tree.syncKeys();
      return tree.time.playing;
    },
    stop() { tree.time.playing = false; if (tree.syncKeys) tree.syncKeys(); return false; },
    togglePlay() { return api.play(!tree.time.playing); },
    playState() { return tree.time.playing; },
    setRange(start, end) {
      const t = tree.time;
      if (Number.isFinite(Number(start))) t.start = Math.round(Number(start));
      if (Number.isFinite(Number(end))) t.end = Math.max(t.start + 1, Math.round(Number(end)));
      t.frame = Math.max(t.start, Math.min(t.end, t.frame));
      if (tree.syncKeys) tree.syncKeys();
      return [t.start, t.end];
    },

    // the pro Channel Box "Rotate Order": the object keeps its orientation, the Euler angles are re-read in the new order
    setRotateOrder(id, order) {
      const n = node(id || api.active().id);
      if (!n || !/^(XYZ|YZX|ZXY|XZY|YXZ|ZYX)$/.test(order) || n.rotOrder === order) return false;
      const Q = n.grp.quaternion.clone();
      n.rotOrder = order; n.grp.rotation.order = order;
      n.grp.quaternion.copy(Q);
      if (tree.syncChannel) tree.syncChannel();
      return true;
    },

    // moving an object by the manipulator changes outer.position; tell the node to read T back
    pivotOf: (id) => { const n = node(id || api.active().id); return n ? n.piv.clone() : null; },
    setPivot(id, P) { const n = node(id || api.active().id); if (!n) return false; setPivot(n, P.isVector3 ? P : new THREE.Vector3(P[0], P[1], P[2])); return true; },
    // the pivot's place in the world (where the manipulator sits)
    pivotWorld(id) { const n = node(id || api.active().id); if (!n) return null; n.grp.updateMatrixWorld(true); return n.grp.getWorldPosition(new THREE.Vector3()); },

    // the pro Modify > Center Pivot: the pivot moves to the middle of the object (children included), nothing moves
    centerPivot(id) {
      const n = node(id || api.active().id);
      if (!n) return false;
      const box = contentBox(n);
      if (box.isEmpty()) return false;
      setPivot(n, box.getCenter(new THREE.Vector3()));
      return true;
    },
    // pivot placement (docs/FORGE_MODELING_FOUNDATION.md stage 3): the bottom middle of the object (where it stands on
    // the grid - the Baseline's partner), the world origin, or the middle of the picked components. Nothing moves.
    pivotBottom(id) {
      const n = node(id || api.active().id);
      if (!n) return false;
      const box = contentBox(n);
      if (box.isEmpty()) return false;
      const c = box.getCenter(new THREE.Vector3());
      setPivot(n, new THREE.Vector3(c.x, box.min.y, c.z));
      return true;
    },
    pivotOrigin(id) {
      const n = node(id || api.active().id);
      if (!n) return false;
      n.grp.updateMatrixWorld(true);
      setPivot(n, new THREE.Vector3().applyMatrix4(n.inner.matrixWorld.clone().invert()));
      return true;
    },
    pivotToSelection() {
      const r = root();
      const vs = view.selectedVerts ? view.selectedVerts() : [];
      if (!view.poly || !vs.length) return false;
      const c = new THREE.Vector3();
      for (const i of vs) c.add(new THREE.Vector3().fromArray(view.poly.v[i] || [0, 0, 0]));
      setPivot(r, c.multiplyScalar(1 / vs.length));      // the cage is in the working object's own space
      return true;
    },
    // the pro Reset Pivot: back on the object's own origin
    resetPivot(id) {
      const n = node(id || api.active().id);
      if (!n) return false;
      setPivot(n, new THREE.Vector3());
      return true;
    },

    // the pro Freeze Transformations: translate/rotate/scale go into the geometry (and the children), the node reads
    // 0 / 0 / 1, and the pivot stays where it was in the world
    freeze(id) {
      const n = node(id || api.active().id);
      if (!n) return false;
      n.grp.updateMatrix(); n.inner.updateMatrix();
      const F = n.grp.matrix.clone().multiply(n.inner.matrix);          // content space -> parent space
      const W = n.grp.position.clone();                                 // the pivot, in the parent's space
      if (n.kind === "mesh") {
        if (n.root) { if (!bakeRoot(F)) return false; }
        else { const s = shapeOf(n); if (s) { s.geometry.applyMatrix4(F); s.geometry.computeBoundingBox(); } }
      }
      for (const k of kidsOf(n.id)) { k.grp.applyMatrix4(F); k.grp.updateMatrixWorld(true); }
      n.grp.quaternion.identity(); n.grp.scale.set(1, 1, 1);
      n.pc.set(0, 0, 0); n.piv.copy(W);
      place(n, new THREE.Vector3());
      if (tree.selMarks) drawMarks();
      return true;
    },

    // the pro Reset Transformations: translate/rotate/scale back to 0/0/1, the geometry is not touched
    resetTransform(id) {
      const n = node(id || api.active().id);
      if (!n) return false;
      n.grp.quaternion.identity(); n.grp.scale.set(1, 1, 1); n.pc.set(0, 0, 0);
      place(n, new THREE.Vector3());
      if (tree.selMarks) drawMarks();
      return true;
    },

    active() { const n = node(tree.sel[tree.sel.length - 1]) || node(tree.rootId); return n || ensureRoot(); },
    groupSelected(name) { return api.group(name, tree.sel); },

    // the box of the selection (or of everything) in world space - for f / a (frame)
    worldBox(ids) {
      const box = new THREE.Box3();
      for (const id of ids || tree.sel) {
        const n = node(id); if (!n || !n.visible) continue;
        n.grp.updateMatrixWorld(true);
        n.inner.traverse((o) => {
          if (!o.isMesh || !o.geometry || o.name === "forge-sel") return;
          if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
          box.union(o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld));
        });
      }
      return box;
    },
    allIds: () => tree.nodes.map((n) => n.id),

    // which node does this three.js object belong to?
    nodeOfObject(o) {
      for (let x = o; x; x = x.parent) {
        if (x === holder) return node(tree.rootId);
        if (x.userData && x.userData.forgeNode && x.name !== "forge-sel") { const n = node(x.userData.forgeNode); if (n && n.grp === x) return n; }
      }
      return null;
    },
    // every visible mesh to pick against (the working mesh and every static shape)
    // opts.select: only what a click may select - a referenced (R) layer's objects are skipped, so a click goes
    // through them to what is behind (the pro reference layer) while snapping still sees them; a templated (T) one
    // is skipped by both
    pickables(opts) {
      const out = [], sel = !!(opts && opts.select);
      for (const n of tree.nodes) {
        if (!n.visible || !api.layerNorm(n)) continue;
        if (sel && (api.layersLocked(n.id) || ghost(n))) continue;
        if (api.layersTemplate(n.id)) continue;            // a template is not even snapped to (R still is - the pro rule)
        let vis = true; for (let p = n.parent; p; p = node(p).parent) if (!node(p).visible) { vis = false; break; }
        if (!vis) continue;
        const s = shapeOf(n); if (s && s.geometry) out.push(s);
      }
      return out;
    },

    // ---- every object is editable: the holder (the tools' mesh) moves into the node you edit
    makeWorking(id) {
      if (root().multiSession && node(id) && !node(id).root) api.multiEnd();   // a multi-edit session splits back first
      const n = node(id), r = root();
      if (!n || n.root || n.kind !== "mesh") return n ? n.root : false;
      // 1. the old working object keeps a static copy of what it is now
      const t = triOfShape(r);
      const keep = new THREE.Group();
      keep.position.copy(holder.position);
      if (t && t.pos.length) keep.add(staticShape(t, t.col));
      r.poly = view.poly; r.hist = typeof forgeModel !== "undefined" ? forgeModel.hist : null;
      for (const k of kidsOf(r.id)) keep.add(k.grp);                   // same local place: holder and keep match
      r.grp.remove(holder); r.grp.add(keep); r.inner = keep; r.root = false;
      // 2. the holder takes the node's place; its children move across
      const old = n.inner, s = shapeOf(n), src = triOfShape(n);
      holder.position.copy(old.position);
      for (const k of kidsOf(n.id)) holder.add(k.grp);
      n.grp.remove(old); n.grp.add(holder); n.inner = holder; n.root = true;
      tree.rootId = n.id;
      if (s) s.geometry.dispose();
      // 3. the tools get the node's mesh
      if (n.poly && view.showPoly) view.showPoly(n.poly, true, true);
      else if (src && view.setTriangles) view.setTriangles(src.pos, src.idx, src.col);
      if (typeof forgeModel !== "undefined") { forgeModel.hist = n.hist || null; forgeModel.last = null; forgeModel.prim = null; }
      n.poly = null; n.hist = null;
      // the undo queue is kept (2026-10-21): every entry holds the whole scene, so this switch undoes too
      tree.build();
      return true;
    },

    // Mesh > Combine: the selected meshes become ONE new object (polySurface1), in world space, the pivot at its
    // middle. The originals go (their children stay, moved up to the world). If the object being edited was one of
    // them, the combined one is the edited object now.
    combine(ids) {
      const P = window.ForgePoly;
      const list = (ids || tree.sel).map(node).filter((n) => n && n.kind === "mesh" && hasGeometry(n));
      if (list.length < 2 || !P) return null;
      scene.updateMatrixWorld(true);
      const parts = list.map((n) => { const m = polyOfNode(n); return m ? P.transform(m, n.inner.matrixWorld.elements) : null; }).filter(Boolean);
      if (parts.length < 2) return null;
      const wasWorking = list.some((n) => n.root);
      const out = polyNode("polySurface", P.combine(parts), 0);
      for (const n of list) for (const k of kidsOf(n.id)) api.reparent(k.id, 0);
      if (wasWorking) api.makeWorking(out.id);
      for (const n of list) api.remove(n.id);
      tree.sel = [out.id]; api.centerPivot(out.id);
      tree.build();
      return out;
    },
    // Mesh > Booleans (forge_boolean.js) needs the picked meshes in world space, in pick order (Maya: the first
    // picked is the one the others are cut from), and a way to put the result in their place - both like combine
    worldPolys(ids) {
      const P = window.ForgePoly;
      const list = (ids || tree.sel).map(node).filter((n) => n && n.kind === "mesh" && hasGeometry(n));
      scene.updateMatrixWorld(true);
      return list.map((n) => { const m = polyOfNode(n); return m ? { id: n.id, name: n.name, poly: P.transform(m, n.inner.matrixWorld.elements) } : null; }).filter(Boolean);
    },
    replaceWith(ids, poly, base) {
      const list = ids.map(node).filter(Boolean);
      if (!list.length || !poly || !poly.f.length) return null;
      const wasWorking = list.some((n) => n.root);
      const out = polyNode(base || "polySurface", poly, 0);
      for (const n of list) for (const k of kidsOf(n.id)) api.reparent(k.id, 0);
      if (wasWorking) api.makeWorking(out.id);
      for (const n of list) api.remove(n.id);
      tree.sel = [out.id]; api.centerPivot(out.id);
      tree.build();
      return out;
    },
    // Mesh > Separate: each piece of the selected mesh that shares no vertex with the rest becomes its own object,
    // grouped under the original's name (polySurface1, polySurface2 ...).
    separate(id) {
      const P = window.ForgePoly;
      const n = node(id || tree.sel[tree.sel.length - 1] || tree.rootId);
      if (!n || n.kind !== "mesh" || !hasGeometry(n) || !P) return null;
      scene.updateMatrixWorld(true);
      const m = polyOfNode(n);
      const shells = m ? P.shells(m) : [];
      if (shells.length < 2) return [];
      const M = n.inner.matrixWorld.elements.slice();
      const grp = makeNode(nextName(n.name.replace(/\d+$/, "") + "_parts"), "group", 0, null);
      const made = shells.map((sh) => polyNode("polySurface", P.transform(sh, M), grp.id));
      for (const k of kidsOf(n.id)) api.reparent(k.id, 0);
      if (n.root) api.makeWorking(made[0].id);
      api.remove(n.id);
      for (const x of made) api.centerPivot(x.id);
      tree.sel = made.map((x) => x.id); tree.build();
      return made;
    },

    // Create > Free Image Plane: a picture on a plane in the scene, its own node (imagePlane1 ...) that you move,
    // rotate, scale, hide, put on a reference layer ... like any object; the tools never edit it (forge_imageplane.js)
    addImagePlane(name, mesh, info) {
      const n = makeNode(nextName(name || "imagePlane"), "imagePlane", 0, null);
      mesh.name = "shape"; n.inner.add(mesh); n.image = info || null;
      const cur = tree.layers.find((l) => l.id === tree.curLayer); if (cur) cur.nodes.add(n.id);
      api.applyLayers(); tree.sel = [n.id]; tree.anchor = n.id;
      tree.build(); if (api.onSelect) api.onSelect();
      view.dirty = true;
      return n;
    },
    // the Level workspace's actors (forge_level.js): a node whose group IS the actor (its transform, scripts, props:
    // grp.userData.loki) and whose shape is the light / camera / gizmo (forge_level_core.js adoptActor). `asset` (a
    // placed Content Browser model) goes in as the node's content instead.
    addActor(name, type, opts, asset) {
      if (typeof ForgeLevel === "undefined") return null;
      const n = makeNode(nextName(name || type), "actor", 0, null);
      if (asset) { asset.name = "asset"; n.inner.add(asset); ForgeLevel.makeActor(n.grp, type); if (opts && opts.asset) n.grp.userData.loki.asset = opts.asset; }
      else ForgeLevel.adoptActor(THREE, type, n.grp, n.inner, opts);
      n.actor = type;
      const cur = tree.layers.find((l) => l.id === tree.curLayer); if (cur) cur.nodes.add(n.id);
      api.applyLayers(); tree.sel = [n.id]; tree.anchor = n.id;
      tree.build(); if (api.onSelect) api.onSelect();
      view.dirty = true;
      return n;
    },
    // which node an object belongs to (Play / Stop restore objects, the Details panel wants the node)
    nodeOf(obj) {
      for (let o = obj; o; o = o.parent) if (o.userData && o.userData.forgeNode != null) return node(o.userData.forgeNode);
      return null;
    },
    // an image plane's Alpha Gain (0 = invisible, 1 = solid), the pro image plane attribute
    setAlphaGain(id, a) {
      const n = node(id); const sh = n && n.kind === "imagePlane" && shapeOf(n);
      if (!sh) return false;
      const v = Math.max(0, Math.min(1, Number(a)));
      if (!isFinite(v)) return false;
      sh.material.opacity = v; sh.material.transparent = v < 1; sh.material.depthWrite = v >= 1; sh.material.needsUpdate = true;
      view.dirty = true; return true;
    },
    alphaGain(id) { const n = node(id); const sh = n && n.kind === "imagePlane" && shapeOf(n); return sh ? sh.material.opacity : null; },

    // ---- several objects' components at once (owner 2026-10-25: "I can't select a mesh's verts, Shift select
    // another mesh and see its verts and select them as well - that should be a thing, just like Maya").
    // The tools edit ONE cage (view.poly, the working object's), so a multi-edit session joins the other picked meshes
    // into it, each carried into the working object's space (ForgePoly.multiJoin); their own shapes step aside while
    // it runs. Leaving component mode (or editing another object, sculpting ...) splits the cage back (multiSplit):
    // every object gets its pieces in its own space again, its transform untouched. The session lives on the working
    // node (multiSession) and the shapes on their nodes, so undo / redo inside or across it restores it too.
    multiIds() { const s = root().multiSession; return s ? s.owners.map((o) => o.id) : []; },
    multiBegin(ids) {
      const P = window.ForgePoly;
      if (!P || !P.multiJoin || !view.showPoly) return false;
      let want = [...new Set((ids || []).map(Number))].map(node).filter((n) => n && n.kind === "mesh" && (n.root ? !!(view.poly && view.poly.f.length) : hasGeometry(n)));
      if (!want.length) return false;
      let r = root();
      const keepSel = view.mode === "poly" && view.poly ? multiSelKeep() : null;
      if (r.multiSession) {                                              // add to the running session: split, then join all
        const now = r.multiSession.owners.map((o) => o.id);
        if (want.every((n) => now.includes(n.id))) return false;
        want = now.map(node).filter(Boolean).concat(want.filter((n) => !now.includes(n.id)));
        api.multiEnd(true);
        r = root();
      }
      if (!want.some((n) => n.root)) { api.makeWorking(want[0].id); r = root(); }
      if (!view.poly || !view.poly.f.length) return false;
      want = [r].concat(want.filter((n) => n !== r));
      if (want.length < 2) return false;
      scene.updateMatrixWorld(true);
      const inv = new THREE.Matrix4().copy(r.inner.matrixWorld).invert();
      const owners = [], parts = [];
      for (const n of want) {
        if (n.root) { owners.push({ id: n.id, M: null }); parts.push(P.clone(view.poly)); continue; }
        const m = polyOfNode(n);
        if (!m || !m.f.length) continue;
        const M = new THREE.Matrix4().multiplyMatrices(inv, n.inner.matrixWorld);
        owners.push({ id: n.id, M: M.elements.slice() });
        parts.push(P.transform(m, M.elements));
      }
      if (owners.length < 2) return false;
      const j = P.multiJoin(parts);
      for (const o of owners.slice(1)) { const n = node(o.id), sh = shapeOf(n); if (sh) n.inner.remove(sh); }
      r.multiSession = { owners, info: j.info };
      if (typeof forgeModel !== "undefined") { forgeModel.prim = null; forgeModel.last = null; }
      view.showPoly(j.m, true, true);
      if (typeof forgeHistReset === "function") forgeHistReset();
      tree.sel = owners.map((o) => o.id); tree.anchor = r.id;
      if (keepSel) multiSelRestore(keepSel);
      tree.build(); view.dirty = true;
      return owners.length;
    },
    multiEnd(quietSel) {
      const P = window.ForgePoly, r = root(), sess = r.multiSession;
      if (!sess || !P) return false;
      const keepSel = !quietSel && view.mode === "poly" && view.poly ? multiSelKeep() : null;
      const parts = view.poly ? P.multiSplit(view.poly, sess.info) : sess.owners.map(() => ({ v: [], f: [] }));
      r.multiSession = null;
      sess.owners.forEach((o, i) => {
        const n = node(o.id), part = parts[i] || { v: [], f: [] };
        if (!n) return;
        if (n.root) return;
        const back = part.f.length ? P.transform(part, new THREE.Matrix4().fromArray(o.M).invert().elements) : part;
        const old = shapeOf(n); if (old) n.inner.remove(old);
        if (back.f.length) { const t = P.triangulate(back); n.inner.add(staticShape({ pos: t.pos, idx: t.idx }, null)); n.poly = back; }
        else n.poly = null;
        n.hist = null;
      });
      const mine = parts[sess.owners.findIndex((o) => node(o.id) && node(o.id).root)] || { v: [], f: [] };
      view.showPoly(mine, true, true);
      if (typeof forgeHistReset === "function") forgeHistReset();
      for (const o of sess.owners) { const n = node(o.id); if (n && !n.root && !hasGeometry(n) && !kidsOf(n.id).length) api.remove(n.id); }
      tree.sel = sess.owners.map((o) => o.id).filter((id) => node(id)); tree.anchor = r.id;
      if (keepSel) multiSelRestore(keepSel);
      tree.build(); view.dirty = true;
      return true;
    },

    // a new, empty working object (pro: every Create command makes a new node) - the old one stays as it is
    // ---- Create > Sets (Maya's sets / quick select sets): a saved selection - objects, or one mesh's components
    // { id, name, kind: "objects" | "vert" | "edge" | "face", node, items, nv } (nv: the mesh's vertex count then)
    setList: () => (tree.sets || []).map((x) => ({ ...x, items: x.items.slice(), count: x.items.length })),
    setAdd(set) {
      const id = tree.setNext++;
      let name = String(set.name || "").trim().replace(/[^\w-]+/g, "_");
      if (!name || tree.sets.some((x) => x.name === name)) { let k = id; while (tree.sets.some((x) => x.name === "set" + k)) k++; name = name ? name + id : "set" + k; }
      tree.sets.push({ id, name, kind: set.kind, node: set.node || 0, items: set.items.slice(), nv: set.nv || 0 });
      return id;
    },
    setGet: (id) => { const x = (tree.sets || []).find((y) => y.id === id || y.name === id); return x ? { ...x, items: x.items.slice() } : null; },
    setUpdate(id, items) { const x = tree.sets.find((y) => y.id === id); if (x) x.items = items.slice(); return !!x; },
    setRename(id, name) {
      const x = tree.sets.find((y) => y.id === id), clean = String(name || "").trim().replace(/[^\w-]+/g, "_");
      if (!x || !clean || tree.sets.some((y) => y !== x && y.name === clean)) return false;
      x.name = clean; return true;
    },
    setRemove(id) { const k = tree.sets.findIndex((y) => y.id === id); if (k >= 0) tree.sets.splice(k, 1); return k >= 0; },

    newObject(name) {
      const r = root();
      if (!hasGeometry(r)) { if (name) { r.name = "\u0000"; api.rename(r.id, nextName(name)); r.auto = false; } return r; }
      const n = makeNode(nextName(name || "object"), "mesh", 0, null);
      n.tri = null;
      api.makeWorking(n.id);
      tree.sel = [n.id]; tree.build();
      return n;
    },
  };
  tree.api = api;
  api.say = (text, bad) => { if (typeof forgeSay === "function") forgeSay(text, bad); };

  // the manipulator follows the selection (pro: the tool's handle sits on the selected object's pivot)
  const tc = ctx.transform || null;
  if (tc && tc.addEventListener) {                     // a manipulator drag is ONE undo step, Shift-drag's copy included
    tc.addEventListener("dragging-changed", (ev) => { if (!view.undoOpen) return; if (ev && ev.value) view.undoOpen({ translate: "Move", rotate: "Rotate", scale: "Scale" }[tc.mode] || "Move"); else view.undoClose(); });
  }
  api.attachTool = (mode) => {
    if (!tc) return false;
    const n = api.active();
    if (!n || (view.mode === "poly")) return false;
    if (mode === null) { tc.detach(); view.dirty = true; return true; }
    tc.attach(n.grp);
    if (mode) tc.setMode(mode);
    view.dirty = true;
    return true;
  };
  api.onSelect = () => {
    if (tc && tc.object && view.mode !== "poly") { const n = api.active(); if (n && tc.object !== n.grp) tc.attach(n.grp); }
    tree.selMarks = true; drawMarks();
  };
  if (tc && tc.addEventListener) {
    tc.addEventListener("objectChange", () => {
      // an object's Scale handle near 0 snaps flat (kept a hair above 0 so it can still be picked; the Channel Box reads 0)
      if (tc.mode === "scale" && tc.object && typeof forgeScaleZeroSnap === "function") forgeScaleZeroSnap(tc.object.scale, tc.axis, 0.06, 1e-4);
      if (tree.syncChannel) tree.syncChannel();
    });
    tc.addEventListener("dragging-changed", (ev) => { if (!ev.value) { drawMarks(); if (tree.syncChannel) tree.syncChannel(); if (tree.autoKey) api.autoKeyNow(); } });
  }
  // the viewer's own Move button attaches the handle to the SELECTED object, never to the bare holder
  if (typeof view.toggleTransform === "function") {
    const own = view.toggleTransform;
    view.toggleTransform = (mode) => {
      if (view.mode === "poly" || !tc) return own(mode);
      const n = api.active();
      if (!n || !n.grp) return own(mode);
      if (tc.object && !mode) tc.detach();
      else { tc.attach(n.grp); tc.setMode(mode || "translate"); }
      for (const b of document.querySelectorAll("#forge .forge-transform")) b.classList.toggle("on", !!tc.object);
      view.dirty = true;
    };
  }

  // ---------------------------------------------------------------- the Outliner panel
  let menuEl = null;
  function closeMenu() { if (menuEl) { menuEl.remove(); menuEl = null; } }
  function rowMenu(x, y, n) {                         // the Outliner's right-click menu
    closeMenu();
    if (n && !tree.sel.includes(n.id)) api.select(n.id);
    const m = menuEl = scnEl("div", "forge-out-menu");
    m.setAttribute("role", "menu");
    const item = (label, run, off) => {
      const b = scnEl("button", "forge-out-mi", label); b.type = "button"; b.disabled = !!off; b.dataset.cmd = label;
      b.addEventListener("click", (e) => { e.stopPropagation(); closeMenu(); run(); tree.build(); });
      m.append(b);
    };
    const one = tree.sel.length > 0;
    item("Select Hierarchy", () => api.selectHierarchy(), !one);
    item("Duplicate", () => api.duplicate(), !one);
    item("Group", () => api.groupSelected(), !one);
    item("Ungroup", () => { for (const id of tree.sel.slice()) api.ungroup(id); }, !one || !tree.sel.some((id) => node(id).kind === "group"));
    item("Rename", () => { const r = tree.list.querySelector('.forge-out-row[data-id="' + tree.sel[tree.sel.length - 1] + '"] .forge-out-name'); if (r) r.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); }, !one);
    item(n && !n.visible ? "Show" : "Hide", () => { if (n && !n.visible) api.show(); else api.hide(); }, !one);
    item("Edit this mesh", () => { if (api.makeWorking(n.id)) api.say(n.name + " is the one the tools edit now."); }, !n || n.kind !== "mesh" || n.root);
    item("Center Pivot", () => api.centerPivot(), !one);
    item("Reset Pivot", () => api.resetPivot(), !one);
    item("Freeze Transformations", () => api.freeze(), !one);
    item("Reset Transformations", () => api.resetTransform(), !one);
    item("Expand All", () => { for (const k of tree.nodes) k.open = true; });
    item("Collapse All", () => { for (const k of tree.nodes) k.open = false; });
    item("Delete", () => api.removeSelected(), !one);
    document.body.append(m);
    const w = m.offsetWidth || 170, h = m.offsetHeight || 300;
    m.style.left = Math.max(4, Math.min(x, window.innerWidth - w - 4)) + "px";
    m.style.top = Math.max(4, Math.min(y, window.innerHeight - h - 4)) + "px";
    setTimeout(() => document.addEventListener("pointerdown", function off(e) {
      if (menuEl && !menuEl.contains(e.target)) { closeMenu(); document.removeEventListener("pointerdown", off, true); }
    }, true), 0);
  }
  api.outlinerMenu = rowMenu;
  api.redrawSelection = () => { if (tree.selMarks) drawMarks(); };
  // The selection wire is the mesh's own edges. Owner 17:06: the wire left behind after moving an edge ("those weird
  // wireframes ... get rid of it") was this wire still showing the OLD shape - so it now follows every edit, and the
  // working object shows no object wire at all while you edit its components or sculpt (the component display or
  // the clean surface is all you see).
  const followEdits = () => {
    const editing = view.mode === "poly" || view.mode === "sculpt";
    for (const g of marks.values()) {
      if (!g.isGroup) continue;
      const working = g.parent === holder;
      g.visible = !(editing && working);
      if (!g.visible) continue;
      for (const lines of g.children) {
        const o = lines.userData.src;
        if (!o || !o.geometry) continue;
        const ver = o.geometry.attributes.position.version + ":" + (o.geometry.index ? o.geometry.index.version : 0);
        let ec = edgeCache.get(o.geometry);
        if (!ec || ec.ver !== ver) { ec = { ver, geo: wireEdges(o) }; edgeCache.set(o.geometry, ec); }
        if (lines.geometry !== ec.geo) lines.geometry = ec.geo;
      }
    }
  };
  if (Array.isArray(view.frameHooks)) view.frameHooks.push(followEdits); else view.frameHooks = [followEdits];
  document.addEventListener("keydown", (e) => {     // Esc closes the menu, and only the menu
    if (e.key === "Escape" && menuEl) { e.preventDefault(); e.stopImmediatePropagation(); closeMenu(); }
  }, true);

  function panel() {
    if (tree.panel && document.body.contains(tree.panel)) return tree.panel;
    const side = document.getElementById("forge-outcol") || document.getElementById("forge-left") || document.getElementById("forge-stage");
    if (!side) return null;
    const box = scnEl("div", "forge-outliner");
    box.id = "forge-outliner";
    const head = scnEl("div", "forge-out-head");
    const title = scnEl("button", "forge-out-title", "Outliner");
    title.type = "button"; title.id = "forge-out-fold";
    title.title = "Click to fold the Outliner away, or bring it back.";
    title.setAttribute("aria-expanded", "true");
    title.addEventListener("click", () => {
      if (!window.forgePanels) return;
      window.forgePanels.toggle("outliner");
      title.setAttribute("aria-expanded", String(!document.getElementById("forge-outliner").classList.contains("collapsed")));
    });
    head.append(title);
    const bar = scnEl("div", "forge-out-bar");
    const btn = (label, id, what, run) => {
      const b = scnEl("button", "forge-out-btn", label);
      b.type = "button"; b.title = what; if (id) b.id = id;
      b.addEventListener("click", () => { run(); tree.build(); });
      bar.append(b); return b;
    };
    btn("Copy", "forge-ch-dup", "Duplicate the selection with its hierarchy (Ctrl/Cmd+D; Shift+D repeats the last offset).", () => { if (api.duplicate()) api.say("Duplicated."); });
    btn("Group", "forge-ch-group", "Group the selection: a new node, pivot at the centre of its contents (Ctrl/Cmd+G).", () => api.groupSelected());
    btn("Ungroup", "forge-ch-ungroup", "Take the children out of the selected group (Ctrl/Cmd+Shift+G).", () => { for (const id of tree.sel.slice()) api.ungroup(id); });
    btn("Reset", "forge-ch-reset", "Reset Transformations: translate, rotate, scale back to 0, 0, 1 (the mesh is not touched).", () => { api.resetTransform(); api.say("Transformations reset."); });
    btn("Pivot", "forge-ch-pivot", "Center Pivot: the pivot moves to the middle of the object; the object does not move.", () => {
      if (api.centerPivot()) api.say("Pivot centred (Modify > Center Pivot)."); else api.say("Select an object first.", true);
    });
    btn("Reset Pivot", "forge-ch-rpivot", "Reset Pivot: the pivot goes back to the object's own origin; the object does not move.", () => {
      if (api.resetPivot()) api.say("Pivot back on the object's origin (Reset Pivot)."); else api.say("Select an object first.", true);
    });
    btn("Freeze", "forge-ch-freeze", "Freeze Transformations: bake the transform into the mesh; the object stays where it is and reads 0, 0, 1.", () => {
      if (api.freeze()) api.say("Transformations frozen (Modify > Freeze Transformations)."); else api.say("Select an object first.", true);
    });
    head.append(bar);
    // the pro Outliner: its own Display / Show / Help menu and a search field above the list
    const menus = scnEl("div", "forge-panel-menus");
    const mk = (label, items) => {
      const m = scnEl("button", "forge-pm", label); m.type = "button";
      m.addEventListener("click", (ev) => { ev.stopPropagation(); api.popMenu(m, items()); });
      menus.append(m);
    };
    mk("Display", () => [["Expand All", () => { for (const k of tree.nodes) k.open = true; tree.build(); }],
      ["Collapse All", () => { for (const k of tree.nodes) k.open = false; tree.build(); }],
      [(tree.showCams === false ? "Show" : "Hide") + " Cameras", () => { tree.showCams = tree.showCams === false; tree.build(); }],
      ["Reveal Selected", () => api.reveal()]]);
    mk("Show", () => [["Select Hierarchy", () => api.selectHierarchy()], ["Invert Selection", () => api.invertSelection()],
      ["Show All", () => api.showAll()], ["Hide Selected", () => api.hide()]]);
    mk("Help", () => [["Click selects, Ctrl/Cmd+click toggles, Shift+click a range", null], ["Drag onto a row to parent, between rows to re-order", null],
      ["Return renames, f reveals, right-click for more", null]]);
    const search = document.createElement("input");
    search.type = "search"; search.className = "forge-out-search"; search.id = "forge-out-search";
    search.placeholder = "Search...";
    search.addEventListener("input", () => { tree.filter = search.value.trim().toLowerCase(); tree.build(); });
    search.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Escape" || e.key === "Enter") search.blur(); });   // Esc / Return hand the keys back
    const list = scnEl("div", "forge-out-list"); list.id = "forge-out-list";
    list.tabIndex = 0;
    list.setAttribute("role", "tree");
    list.title = "Click selects, Ctrl/Cmd+click toggles, Shift+click selects a range. Drag onto an object to parent, between two to re-order, onto empty space to unparent. Right-click for more.";
    // dropping on empty space under the rows: back to the world, last
    list.addEventListener("dragover", (ev) => { if (ev.target === list) { ev.preventDefault(); list.classList.add("drop-world"); } });
    list.addEventListener("dragleave", () => list.classList.remove("drop-world"));
    list.addEventListener("drop", (ev) => {
      list.classList.remove("drop-world");
      if (ev.target !== list) return;
      ev.preventDefault();
      const from = parseInt(ev.dataTransfer.getData("text/plain"), 10);
      if (from && api.reparent(from, 0)) api.say(node(from).name + " is back under the world.");
    });
    list.addEventListener("contextmenu", (ev) => { if (ev.target === list) { ev.preventDefault(); rowMenu(ev.clientX, ev.clientY, null); } });
    // the Outliner's own keys: Return renames, f reveals, Delete deletes
    list.addEventListener("keydown", (ev) => {
      if (ev.target !== list) return;
      if (ev.key === "Enter") { ev.preventDefault(); ev.stopPropagation(); const lbl = list.querySelector('.forge-out-row[data-id="' + tree.sel[tree.sel.length - 1] + '"] .forge-out-name'); if (lbl) lbl.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); }
      else if (ev.key === "f" || ev.key === "F") { ev.preventDefault(); ev.stopPropagation(); api.reveal(); }
    });
    box.append(head, menus, search, list);
    side.append(box);
    tree.panel = box; tree.list = list;
    return box;
  }

  api.reveal = () => {                               // the pro Reveal Selected: open the parents, scroll to it
    for (const id of tree.sel) for (let p = node(id) && node(id).parent; p; p = node(p).parent) node(p).open = true;
    tree.build();
    const r = tree.list && tree.list.querySelector(".forge-out-row.on");
    if (r && r.scrollIntoView) r.scrollIntoView({ block: "nearest" });
  };

  function row(n, depth) {
    const lead = tree.sel[tree.sel.length - 1] === n.id;
    const r = scnEl("div", "forge-out-row" + (tree.sel.includes(n.id) ? " on" : "") + (lead ? " lead" : "") + (n.root ? " working" : "")
      + (!n.visible || !api.layerNorm(n) ? " hid" : "") + (api.layersRef(n.id) ? " ref" : "") + (api.layersTemplate(n.id) ? " tpl" : ""));
    r.dataset.id = String(n.id); r.dataset.kind = n.kind;
    r.setAttribute("role", "treeitem");
    r.style.paddingLeft = (4 + depth * 12) + "px";
    r.draggable = true;
    const kids = kidsOf(n.id).length;
    const tw = scnEl("button", "forge-out-tw" + (kids ? "" : " none"), kids ? (n.open ? "▾" : "▸") : "");
    tw.type = "button"; tw.tabIndex = -1;
    tw.title = kids ? "Open or close (Shift+click: the whole branch)." : "";
    tw.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (!kids) return;
      const to = !n.open;
      if (ev.shiftKey) { for (const k of tree.nodes) if (k === n || isAncestor(n.id, k.id)) k.open = to; } else n.open = to;
      tree.build();
    });
    const eye = scnEl("button", "forge-out-eye" + (n.visible ? "" : " off"), n.visible ? "◉" : "○");
    eye.type = "button"; eye.tabIndex = -1; eye.title = "Show or hide (h toggles the selection).";
    eye.addEventListener("click", (ev) => { ev.stopPropagation(); api.setVisible(n.id, !n.visible); });
    const kind = scnEl("span", "forge-out-kind " + (n.kind === "group" ? "kind-group" : n.kind === "imagePlane" ? "kind-imagePlane" : "kind-mesh"), "");
    kind.title = n.kind === "group" ? "Group (a transform node)" : n.root ? "Mesh - the one the tools are editing" : "Mesh";
    const lbl = scnEl("span", "forge-out-name", n.name);
    lbl.addEventListener("dblclick", (ev) => {
      ev.stopPropagation();
      const input = scnEl("input", "forge-out-edit"); input.value = n.name;
      let done = false;
      const finish = (ok) => {
        if (done) return; done = true;
        if (ok && input.value.trim()) api.rename(n.id, input.value.trim()); else tree.build();
      };
      input.addEventListener("keydown", (e2) => {
        e2.stopPropagation();
        if (e2.key === "Enter") finish(true); else if (e2.key === "Escape") finish(false);
      });
      input.addEventListener("blur", () => finish(true));
      lbl.replaceWith(input); input.focus(); input.select();
    });
    r.append(tw, eye, kind, lbl);
    r.addEventListener("click", (ev) => {
      const how = ev.shiftKey ? "range" : (ev.ctrlKey || ev.metaKey) ? "toggle" : "set";
      api.select(n.id, how);
      if (tree.list) tree.list.focus({ preventScroll: true });
    });
    r.addEventListener("contextmenu", (ev) => { ev.preventDefault(); ev.stopPropagation(); rowMenu(ev.clientX, ev.clientY, n); });
    r.addEventListener("dragstart", (ev) => { ev.dataTransfer.setData("text/plain", String(n.id)); ev.dataTransfer.effectAllowed = "move"; });
    const zone = (ev) => {                           // top quarter: before, bottom quarter: after, middle: into
      const b = r.getBoundingClientRect(), y = (ev.clientY - b.top) / (b.height || 1);
      return y < 0.25 ? "before" : y > 0.75 ? "after" : "into";
    };
    r.addEventListener("dragover", (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      r.classList.remove("drop", "drop-before", "drop-after");
      const z = zone(ev); r.classList.add(z === "into" ? "drop" : "drop-" + z);
    });
    r.addEventListener("dragleave", () => r.classList.remove("drop", "drop-before", "drop-after"));
    r.addEventListener("drop", (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      r.classList.remove("drop", "drop-before", "drop-after");
      const from = parseInt(ev.dataTransfer.getData("text/plain"), 10);
      if (!from || from === n.id) return;
      api.dropOn(from, n.id, zone(ev));
    });
    return r;
  }

  // drag-and-drop logic, testable without a mouse: into = parent under it; before / after = its sibling, there
  api.dropOn = (from, target, where) => {
    const t = node(target), f = node(from);
    if (!t || !f) return false;
    if (where === "into") {
      if (!api.reparent(from, target)) { api.say("Can't parent " + f.name + " under its own child.", true); return false; }
      t.open = true; tree.build();
      api.say(f.name + " is under " + t.name + " now.");
      return true;
    }
    const sib = kidsOf(t.parent).filter((x) => x !== f);
    const i = sib.indexOf(t);
    const before = where === "before" ? t.id : (sib[i + 1] ? sib[i + 1].id : 0);
    if (t.parent && isAncestor(from, t.parent)) return false;
    if (before === 0) {                              // after the last sibling: right after it in the array
      if (!api.reparent(from, t.parent, 0)) return false;
      const lastKid = order().filter((x) => isAncestor(t.id, x.id)).pop() || t;
      moveInArray(f, (tree.nodes[tree.nodes.indexOf(lastKid) + 1] || {}).id || 0);
      tree.build();
      return true;
    }
    return api.reparent(from, t.parent, before);
  };

  tree.build = () => {
    const list = tree.list;
    if (list) {
      list.textContent = "";
      const f = tree.filter || "";
      // pro lists its four default cameras first, greyed; a click looks through that camera
      if (tree.showCams !== false && !f) {
        for (const cam of ["persp", "top", "front", "side"]) {
          const r = scnEl("div", "forge-out-cam" + (view.cam === cam ? " looking" : ""));   // not a .forge-out-row: cameras are not scene nodes
          r.dataset.cam = cam; r.style.paddingLeft = "18px";
          r.append(scnEl("span", "forge-out-kind kind-camera", ""), scnEl("span", "forge-out-name", cam));
          r.title = "Look through " + cam + ".";
          r.addEventListener("click", () => { if (typeof forgeProView === "function") { forgeProView(view, cam); tree.build(); } });
          list.append(r);
        }
      }
      const walk = (parent, depth) => {
        for (const n of tree.nodes) if (n.parent === parent) {
          if (ghost(n)) continue;
          const hit = !f || n.name.toLowerCase().includes(f);
          if (hit) list.append(row(n, f ? 0 : depth));
          if (n.open || f) walk(n.id, depth + 1);
        }
      };
      walk(0, 0);
      if (tree.panel) tree.panel.dataset.count = String(tree.nodes.filter((n) => !ghost(n)).length);
    }
    if (tree.syncChannel) tree.syncChannel();
    if (tree.syncHistory) tree.syncHistory();
    if (tree.syncLayers) tree.syncLayers();
    if (tree.syncKeys) tree.syncKeys();
    if (tree.selMarks) drawMarks();
  };

  // ---------------------------------------------------------------- the Channel Box (the pro exact numbers)
  const AXES = ["x", "y", "z"];
  // the pro Channel Box, as it looks in the reference package (read off the owner's Mac): a Channels / Edit / Object / Show menu,
  // the object's name, then one row per channel - the label right-aligned, a dark value field - Translate X..Z,
  // Rotate X..Z, Scale X..Z, Visibility; then SHAPES (the mesh under the transform) and INPUTS (its construction
  // history, below). Drag a channel's NAME left / right to scrub its value (pro: select it, middle-drag).
  function channelBox() {
    const host = document.getElementById("forge-chancol") || document.getElementById("forge-outliner");
    if (!host) return null;
    const box = scnEl("div", "forge-ch-body");
    box.id = "forge-channel";
    const tab = scnEl("div", "forge-panel-tab", "Channel Box / Layer Editor");
    const menus = scnEl("div", "forge-panel-menus");
    const mk = (label, items) => {
      const m = scnEl("button", "forge-pm", label); m.type = "button";
      m.addEventListener("click", (ev) => { ev.stopPropagation(); api.popMenu(m, items()); });
      menus.append(m);
    };
    const cur = () => api.active();
    const nd = () => cur() || {};
    let showHidden = false, showAttrs = true;
    const addAttr = () => { const n = cur(); if (!n) return; n.attrs = n.attrs || []; n.attrs.push({ name: "attr" + (n.attrs.length + 1), value: 0 }); if (tree.syncChannel) tree.syncChannel(); };
    mk("Channels", () => [["Key Selected", null], ["Reset to Default", () => { api.resetTransform(); tree.build(); }]]);
    mk("Edit", () => [["Add Attribute", () => addAttr()],
      ["Unlock All Channels", () => { const n = cur(); if (n) { n.chLock = {}; if (tree.syncChannel) tree.syncChannel(); } }],
      ["Unhide All Channels", () => { const n = cur(); if (n) { n.chHide = {}; if (tree.syncChannel) tree.syncChannel(); } }],
      ["Delete History", () => { if (window.forgeHistory) window.forgeHistory.clear(); tree.build(); }],
      ["Freeze Transformations", () => { api.freeze(); tree.build(); }], ["Reset Transformations", () => { api.resetTransform(); tree.build(); }]]);
    mk("Object", () => [["Center Pivot", () => { api.centerPivot(); tree.build(); }], ["Reset Pivot", () => { api.resetPivot(); tree.build(); }],
      ["Select Hierarchy", () => api.selectHierarchy()]]);
    mk("Show", () => [["Shapes", () => { box.classList.toggle("no-shapes"); }], ["Inputs", () => { const h = document.getElementById("forge-history"); if (h) h.hidden = !h.hidden; }],
      ["Custom Attributes", () => { const w = document.getElementById("forge-ch-attrs"); if (w) { showAttrs = !showAttrs; w.hidden = !showAttrs; } }],
      ["Hidden Channels", () => { showHidden = !showHidden; if (tree.syncChannel) tree.syncChannel(); }]]);
    const title = scnEl("div", "forge-ch-title", "");
    title.id = "forge-ch-name";
    box.append(tab, menus, title);

    const focusNext = (inp, back) => {
      const list = [...box.querySelectorAll(".forge-ch-in")].filter((x) => !x.readOnly && x.offsetParent !== null);
      const i = list.indexOf(inp); if (i < 0 || !list.length) return;
      const j = (i + (back ? -1 : 1) + list.length) % list.length;
      list[j].focus(); if (list[j].select) list[j].select();
    };
    const locked = (key) => !!(nd().chLock && nd().chLock[key]);
    const hidden = (key) => !!(nd().chHide && nd().chHide[key]);
    const channelMenu = (row, part, a, key) => {
      const n = cur(); if (!n) return;
      n.chLock = n.chLock || {}; n.chHide = n.chHide || {};
      const isZero = part === "scale" ? 1 : 0;
      api.popMenu(row, [
        [locked(key) ? "Unlock This Channel" : "Lock This Channel", () => { n.chLock[key] = !locked(key); tree.syncChannel(); }],
        [hidden(key) ? "Show This Channel" : "Hide This Channel", () => { n.chHide[key] = !hidden(key); tree.syncChannel(); }],
        ["Set to " + isZero, () => { if (tree.syncChannel) api.undoChunk("set channel", () => api.setTransform(null, part, a, isZero)); }],
        ["Unlock All Channels", () => { n.chLock = {}; tree.syncChannel(); }],
        ["Unhide All Channels", () => { n.chHide = {}; tree.syncChannel(); }],
      ]);
    };

    const inputs = {}, rows = {};
    for (const [part, label, step] of [["translate", "Translate", 0.1], ["rotate", "Rotate", 5], ["scale", "Scale", 0.1]]) {
      for (let a = 0; a < 3; a++) {
        const key = part + a;
        const r = scnEl("div", "forge-ch-row"); r.dataset.ch = key;
        const lbl = scnEl("span", "forge-ch-label", label + " " + AXES[a].toUpperCase());
        lbl.title = label + ": drag left / right to scrub the value (the pro virtual slider); right-click the row to lock or hide the channel.";
        const inp = document.createElement("input");
        inp.type = "number"; inp.step = String(step);
        inp.id = "forge-ch-" + part.slice(0, 1) + AXES[a];
        inp.className = "forge-ch-in";
        inp.title = label + " - the selected object's own transform.";
        inp.addEventListener("input", () => { if (inp.value === "" || inp.value === "-" || locked(key)) return; api.setTransform(null, part, a, inp.value); });
        inp.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Tab") { e.preventDefault(); focusNext(inp, e.shiftKey); }
          else if (e.key === "Enter" || e.key === "Escape") inp.blur(); });   // Enter / Esc give the keys back to the viewport (h, w, e ... work again)
        inp.addEventListener("change", () => { if (tree.autoKey) api.autoKeyNow(); });   // Auto Keyframe: a committed value writes a key   // Enter / Esc give the keys back to the viewport (h, w, e ... work again)
        lbl.addEventListener("pointerdown", (e) => {
          if ((e.button !== 0 && e.button !== 1) || locked(key)) return;
          e.preventDefault();
          const t0 = api.transform(); if (!t0) return;
          const from = t0[part][a], x0 = e.clientX;
          lbl.setPointerCapture(e.pointerId); lbl.classList.add("scrub");
          const move = (ev) => { const v = from + (ev.clientX - x0) * step * (ev.shiftKey ? 0.1 : 0.25); api.setTransform(null, part, a, v); inp.value = String(Math.round(v * 1000) / 1000); };
          const up = () => { lbl.classList.remove("scrub"); lbl.removeEventListener("pointermove", move); lbl.removeEventListener("pointerup", up); tree.build(); };
          lbl.addEventListener("pointermove", move); lbl.addEventListener("pointerup", up);
        });
        r.addEventListener("contextmenu", (ev) => { ev.preventDefault(); channelMenu(r, part, a, key); });
        inputs[key] = inp; rows[key] = { r, inp };
        r.append(lbl, inp);
        box.append(r);
      }
    }
    // the pro Rotate Order channel
    const orderRow = scnEl("div", "forge-ch-row"); orderRow.dataset.ch = "order";
    const orderSel = document.createElement("select"); orderSel.className = "forge-ch-order"; orderSel.id = "forge-ch-order";
    orderSel.title = "Rotate Order - the order the X / Y / Z angles are applied in. The object does not move.";
    for (const o of ["XYZ", "YZX", "ZXY", "XZY", "YXZ", "ZYX"]) { const op = document.createElement("option"); op.value = o; op.textContent = o; orderSel.append(op); }
    orderSel.addEventListener("change", () => api.undoChunk("rotate order", () => api.setRotateOrder(null, orderSel.value)));
    orderRow.append(scnEl("span", "forge-ch-label", "Rotate Order"), orderSel);
    box.append(orderRow);

    const vis = scnEl("div", "forge-ch-row"); vis.dataset.ch = "vis";
    const visIn = scnEl("button", "forge-ch-in forge-ch-vis", "on");
    visIn.type = "button"; visIn.id = "forge-ch-vis";
    visIn.addEventListener("click", () => { const n = cur(); if (n) api.setVisible(n.id, !n.visible); });
    vis.append(scnEl("span", "forge-ch-label", "Visibility"), visIn);
    vis.addEventListener("contextmenu", (ev) => { ev.preventDefault(); channelMenu(vis, "vis", 0, "vis"); });
    box.append(vis);
    // an image plane's own attribute: Alpha Gain (shown only when one is selected)
    const ag = scnEl("div", "forge-ch-row forge-ch-ip"); ag.hidden = true;
    const agIn = document.createElement("input"); agIn.type = "number"; agIn.step = "0.05"; agIn.min = "0"; agIn.max = "1";
    agIn.id = "forge-ch-alpha"; agIn.className = "forge-ch-in"; agIn.title = "Alpha Gain: how see-through the picture is (0 - 1).";
    agIn.addEventListener("input", () => { const n = api.active(); if (n && agIn.value !== "") api.setAlphaGain(n.id, agIn.value); });
    agIn.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter" || e.key === "Escape") agIn.blur(); });
    ag.append(scnEl("span", "forge-ch-label", "Alpha Gain"), agIn);
    box.append(ag);
    const shapesHead = scnEl("div", "forge-ch-section", "SHAPES");
    const shapeRow = scnEl("div", "forge-ch-node", "");
    shapesHead.classList.add("forge-ch-shapes"); shapeRow.classList.add("forge-ch-shapes");
    const attrHead = scnEl("div", "forge-ch-section", "ATTRIBUTES"); attrHead.id = "forge-ch-attrhead";
    const attrWrap = scnEl("div", "forge-ch-attrs"); attrWrap.id = "forge-ch-attrs";
    box.append(shapesHead, shapeRow, attrHead, attrWrap);
    host.append(box);

    tree.syncChannel = () => {
      const t = api.transform(), n = api.active();
      // pro: with nothing selected the Channel Box is empty (the values still follow the working object underneath)
      box.classList.toggle("forge-ch-none", !tree.sel.length || ghost(n));
      title.textContent = n && tree.sel.length ? n.name : "";
      shapeRow.textContent = n && (n.kind === "mesh" || n.kind === "imagePlane") ? n.name + "Shape" : "";
      shapesHead.hidden = shapeRow.hidden = !(n && (n.kind === "mesh" || n.kind === "imagePlane"));
      ag.hidden = !(n && n.kind === "imagePlane" && tree.sel.length);
      if (!ag.hidden && document.activeElement !== agIn) agIn.value = String(Math.round((api.alphaGain(n.id) ?? 1) * 100) / 100);
      visIn.textContent = n && !n.visible ? "off" : "on";
      orderSel.value = (n && n.rotOrder) || "XYZ";
      if (t) for (const part of ["translate", "rotate", "scale"]) {
        const vals = t[part];
        for (let a = 0; a < 3; a++) {
          const key = part + a, cell = rows[key];
          if (!cell) continue;
          const isLocked = locked(key);
          cell.r.classList.toggle("keyed", !!(n && n.keys && n.keys[key]));
          cell.inp.readOnly = isLocked;
          cell.r.classList.toggle("locked", isLocked);
          cell.r.hidden = hidden(key) && !showHidden;
          if (document.activeElement !== cell.inp) cell.inp.value = String(Math.round(vals[a] * 1000) / 1000);
        }
      }
      const attrs = (n && n.attrs) || [];
      attrHead.hidden = !attrs.length;
      attrHead.textContent = attrs.length ? "ATTRIBUTES" : "";
      attrWrap.textContent = "";
      attrWrap.hidden = !attrs.length || !showAttrs;
      attrs.forEach((at, i) => {
        const r = scnEl("div", "forge-ch-row forge-ch-attrrow");
        const nm = document.createElement("input"); nm.type = "text"; nm.className = "forge-ch-attrname"; nm.value = at.name;
        nm.title = "Custom attribute name (double-click to rename).";
        nm.addEventListener("input", () => { at.name = nm.value; });
        nm.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Tab") { e.preventDefault(); focusNext(nm, e.shiftKey); } });
        const vl = document.createElement("input"); vl.type = "number"; vl.className = "forge-ch-in"; vl.step = "0.1"; vl.value = String(at.value);
        vl.title = "Custom attribute value.";
        vl.addEventListener("input", () => { at.value = Number(vl.value) || 0; });
        vl.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Tab") { e.preventDefault(); focusNext(vl, e.shiftKey); } });
        r.addEventListener("contextmenu", (ev) => { ev.preventDefault(); api.popMenu(r, [["Rename Attribute", () => { nm.focus(); nm.select(); }], ["Delete Attribute", () => { attrs.splice(i, 1); tree.syncChannel(); }]]); });
        r.append(nm, vl);
        attrWrap.append(r);
      });
    };
    return box;
  }
  // ---------------------------------------------------------------- the Layer Editor (Display Layers, under the Channel Box)
  // The pro Layer Editor: a list of display layers, each with V (visibility), T (template - shown but not
  // selectable), a colour, its object count, a delete, and the current layer highlighted. Assign puts the
  // selected objects on the current layer; a new object lands on it too.
  function layerBox() {
    const host = document.getElementById("forge-chancol") || document.getElementById("forge-outliner");
    if (!host) return null;
    const box = scnEl("div", "forge-ch-body forge-layer-editor");
    box.id = "forge-layer-editor";
    const head = scnEl("div", "forge-layer-head");
    head.append(scnEl("div", "forge-ch-section", "Display Layers"));
    const add = scnEl("button", "forge-out-btn", "+"); add.type = "button"; add.id = "forge-layer-add";
    add.title = "New display layer (Layers > Create Empty Layer).";
    add.addEventListener("click", () => api.undoChunk("create layer", () => api.layerAdd(null)));
    const asg = scnEl("button", "forge-out-btn", "Assign"); asg.type = "button"; asg.id = "forge-layer-assign";
    asg.title = "Put the selected objects on the current layer.";
    asg.addEventListener("click", () => api.undoChunk("assign layer", () => api.layerAssign(tree.curLayer, tree.sel)));
    head.append(add, asg);
    const list = scnEl("div", "forge-layer-list"); list.id = "forge-layer-list";
    box.append(head, list);
    host.append(box);
    const hex = (c) => "#" + ((c >>> 0) & 0xffffff).toString(16).padStart(6, "0");
    if (typeof forgeSplitAttach === "function") setTimeout(forgeSplitAttach, 0);   // its drag edge (forge_split.js)
    tree.syncLayers = () => {
      list.textContent = "";
      const rows = [{ id: 0, name: "Default", color: 0x8a8f98, visible: tree.defLayer.visible, template: tree.defLayer.template, ref: tree.defLayer.ref, count: 0, current: tree.curLayer === 0 }].concat(api.layerList());
      for (const l of rows) {
        const r = scnEl("div", "forge-layer-row" + (l.current ? " cur" : "") + (l.id === 0 ? " default" : ""));
        r.dataset.layer = String(l.id);
        const v = scnEl("button", "forge-layer-tog" + (l.visible ? " on" : ""), "V"); v.type = "button"; v.dataset.role = "vis";
        v.title = "Visibility"; v.addEventListener("click", (e) => { e.stopPropagation(); api.undoChunk("layer visibility", () => api.layerSetVisible(l.id, !l.visible)); });
        const t = scnEl("button", "forge-layer-tog" + (l.template ? " on" : ""), "T"); t.type = "button"; t.dataset.role = "tpl";
        t.title = "Template: shown but not selectable"; t.addEventListener("click", (e) => { e.stopPropagation(); api.undoChunk("layer template", () => api.layerSetTemplate(l.id, !l.template)); });
        const rf = scnEl("button", "forge-layer-tog" + (l.ref ? " on" : ""), "R"); rf.type = "button"; rf.dataset.role = "ref";
        rf.title = "Reference: shown as it is, but you cannot click it - clicks go through to what is behind"; rf.addEventListener("click", (e) => { e.stopPropagation(); api.undoChunk("layer reference", () => api.layerSetRef(l.id, !l.ref)); });
        const sw = scnEl("span", "forge-layer-swatch"); sw.style.background = hex(l.color);
        const nm = scnEl("span", "forge-layer-name", l.name); nm.title = "Click to make current; double-click to rename.";
        const ct = scnEl("span", "forge-layer-count", l.count ? String(l.count) : "");
        r.append(v, t, rf, sw, nm, ct);
        if (l.id !== 0) { const x = scnEl("button", "forge-ch-x", "\u00d7"); x.type = "button"; x.title = "Delete this layer (its objects stay in the scene).";
          x.addEventListener("click", (e) => { e.stopPropagation(); api.undoChunk("delete layer", () => api.layerRemove(l.id)); }); r.append(x); }
        r.addEventListener("click", () => { if (l.id !== 0) api.layerCurrent(l.id); });
        nm.addEventListener("dblclick", (ev) => {
          ev.stopPropagation(); if (l.id === 0) return;
          nm.contentEditable = "true"; nm.focus();
          try { document.execCommand("selectAll", false, null); } catch (_) { /* ignore */ }
          const fin = (ok) => { nm.contentEditable = "false"; if (ok) api.undoChunk("rename layer", () => api.layerRename(l.id, nm.textContent)); else if (tree.syncLayers) tree.syncLayers(); };
          nm.addEventListener("blur", () => fin(true), { once: true });
          nm.addEventListener("keydown", (k) => { k.stopPropagation(); if (k.key === "Enter") { k.preventDefault(); nm.blur(); } else if (k.key === "Escape") { nm.textContent = l.name; nm.blur(); } });
        });
        list.append(r);
      }
    };
    return box;
  }

  // a small drop-down under a panel's menu name (the Channel Box's and the Outliner's own menus)
  api.popMenu = (anchor, items) => {
    document.querySelectorAll(".forge-pm-pop").forEach((x) => x.remove());
    const pop = scnEl("div", "forge-pm-pop");
    for (const [label, run] of items) {
      const b = scnEl("button", "forge-pm-item", label); b.type = "button"; b.disabled = !run;
      b.addEventListener("click", (ev) => { ev.stopPropagation(); pop.remove(); if (run) run(); });
      pop.append(b);
    }
    const r = anchor.getBoundingClientRect();
    pop.style.left = Math.round(r.left) + "px"; pop.style.top = Math.round(r.bottom + 1) + "px";
    document.body.append(pop);
    setTimeout(() => document.addEventListener("pointerdown", function off(e) {
      if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("pointerdown", off, true); }
    }, true), 0);
    return pop;
  };
  api.toggleChannelBox = () => {
    const b = document.getElementById("forge-channel"), h = document.getElementById("forge-history");
    if (!b) return false;
    b.hidden = !b.hidden; if (h) h.hidden = b.hidden;
    return !b.hidden;
  };

  // ---------------------------------------------------------------- the History (the pro construction history)
  function historyBox() {
    const host = document.getElementById("forge-chancol") || document.getElementById("forge-outliner");   // pro: the Channel Box on the right
    if (!host) return null;
    const box = scnEl("div", "forge-ch-body");
    box.id = "forge-history";
    const head = scnEl("div", "forge-hist-head");
    head.append(scnEl("div", "forge-ch-section", "INPUTS"));
    const del = scnEl("button", "forge-out-btn", "Delete History");
    del.type = "button"; del.id = "forge-hist-clear";
    del.title = "Forget how the mesh was built; the shape stays (Delete History).";
    del.addEventListener("click", () => { if (window.forgeHistory) window.forgeHistory.clear(); tree.build(); });
    head.append(del);
    const list = scnEl("div", "forge-hist-list"); list.id = "forge-hist-list";
    box.append(head, list);
    host.append(box);
    tree.syncHistory = () => {
      const H = window.forgeHistory;
      const ops = H && H.list ? H.list() : [];
      list.textContent = "";
      if (!ops.length) { list.append(scnEl("div", "forge-hist-empty", "No history - extrude, inset or sculpt and each step lands here.")); return; }
      const count = {};
      for (const op of ops) {
        const r = scnEl("div", "forge-hist-row");
        // the pro node names for each step (polyExtrudeFace1, polySmoothFace1 ...); the step kind stays in the tooltip
        const base = op.node || FORGE_HIST_NODE[op.kind] || op.kind;
        count[base] = (count[base] || 0) + 1;
        const nm = scnEl("span", "forge-hist-name", base + count[base] + (op.affected ? " \u00b7 " + op.affected + "v" : ""));
        nm.title = op.kind;
        r.dataset.kind = op.kind;
        r.append(nm);
        if (op.amount != null) {
          const inp = document.createElement("input");
          inp.type = "number"; inp.step = "0.05"; inp.className = "forge-ch-in";
          inp.value = String(Math.round(op.amount * 1000) / 1000);
          inp.title = "Change this step's amount - the model rebuilds from the first step.";
          inp.addEventListener("input", () => H.setAmount(op.i, inp.value));
          inp.addEventListener("keydown", (e) => e.stopPropagation());
          r.append(inp);
        }
        const x = scnEl("button", "forge-hist-x", "×");
        x.type = "button"; x.title = "Remove this step and rebuild without it.";
        x.addEventListener("click", () => H.remove(op.i));
        r.append(x);
        list.append(r);
      }
    };
    return box;
  }

  // ---------------------------------------------------------------- the viewer's loads reset the working object
  const load = view.load;
  if (typeof load === "function") view.load = async (buf) => {
    const r = root();
    const out = await load(buf);
    r.grp.quaternion.identity(); r.grp.scale.set(1, 1, 1); r.piv.set(0, 0, 0); r.pc.set(0, 0, 0);
    place(r, new THREE.Vector3());
    tree.build();
    return out;
  };
  const showPoly = view.showPoly;
  if (typeof showPoly === "function") view.showPoly = (poly, keepView, noUndo) => {
    const r = root();
    const out = showPoly(poly, keepView, noUndo);
    if (!keepView) { r.grp.quaternion.identity(); r.grp.scale.set(1, 1, 1); r.piv.set(0, 0, 0); r.pc.set(0, 0, 0); place(r, new THREE.Vector3()); }
    holder.position.copy(r.piv).multiplyScalar(-1);
    if (tree.selMarks) drawMarks();
    return out;
  };
  // ---------------------------------------------------------------- T6c (Ziva): a sculpt stroke in the history
  // A stroke moves WELDED vertices, not polygons, so it is recorded as the vertices it changed with their
  // positions before and after - never as a list of dabs. forge.js snapshot()s at the START of a stroke, so the
  // undo stack's top is the state before it. Only a real stroke is recorded (view.stroked, set when one starts) -
  // a left click that selects in object mode must not record the last stroke a second time.
  const canvas = ctx.canvas;
  function sculptRecordAfterStroke() {
    if (!view.stroked) return;
    view.stroked = false;
    const sm = view.sm, top = view.undoStack && view.undoStack[view.undoStack.length - 1];
    if (!sm || !sm.wpos || !top || !top.wpos || top.sm !== sm || !window.forgeHistPushSculpt) return;
    const before = top.wpos, after = sm.wpos, verts = [];
    for (let i = 0; i + 2 < before.length && i + 2 < after.length; i += 3) {
      if (before[i] !== after[i] || before[i + 1] !== after[i + 1] || before[i + 2] !== after[i + 2]) {
        verts.push(i / 3, before[i], before[i + 1], before[i + 2], after[i], after[i + 1], after[i + 2]);
      }
    }
    if (!verts.length) return;
    window.forgeHistPushSculpt({ kind: "sculpt", verts: verts });
    if (tree.selMarks) drawMarks();                   // the selection wireframe follows the new shape
  }
  if (canvas && canvas.addEventListener) {
    view.sculptStrokeEnd = () => { view.stroked = true; sculptRecordAfterStroke(); };   // tests and scripts
    canvas.addEventListener("pointerup", (e) => { if (e.button === 0) sculptRecordAfterStroke(); });
    canvas.addEventListener("pointerleave", () => sculptRecordAfterStroke());
  }

  // ---------------------------------------------------------------- Shift + drag duplicates
  // Shift held when a manipulator drag starts: the copy is made and takes the manipulator, the original stays.
  let shiftDown = false;
  document.addEventListener("keydown", (e) => { if (e.key === "Shift") shiftDown = true; }, true);
  document.addEventListener("keyup", (e) => { if (e.key === "Shift") shiftDown = false; }, true);
  window.addEventListener("blur", () => { shiftDown = false; });
  api.shiftDown = () => shiftDown;
  if (tc && tc.addEventListener) {
    tc.addEventListener("dragging-changed", (ev) => {
      if (!ev || !ev.value || !shiftDown || view.mode === "poly" || api.pivotMode) return;
      const from = api.active();
      if (!from || !tc.object || tc.object !== from.grp) return;
      const copy = api.duplicate(null, [from.id]);
      if (copy) { tc.attach(copy.grp); tree.build(); api.say("Shift-drag: " + copy.name + " is the copy, the original stayed."); }
    });
  }

  // ---------------------------------------------------------------- hiding / collapsing (window.forgePanels)
  // Owner 2026-10-20: "improve all the ui everything should be abable to hide with slide or toggle". The
  // Outliner folds its own body, the left column slides away, and "floats" clears every bar off the viewport
  // (the pro clean view). What is hidden is remembered, so Forge comes back the way it was left.
  // One store for Forge's panels: the pro workspace in forge_pro.js (forgeProPanels, key "loki-forge-panels") owns
  // what shows; this keeps Ziva's API (forgePanels.*, the UI button, the Outliner's fold) on top of it, so the two
  // never disagree (merged 2026-10-19 - both had picked the same storage key with different meanings).
  window.forgePanels = (function () {
    const has = () => typeof forgeProPanels === "function";
    const read = () => (has() ? forgeProPanels() : {});
    const write = (p) => { try { localStorage.setItem("loki-forge-panels", JSON.stringify(p)); } catch (_) { /* private mode */ } };
    function apply() {
      const p = read();
      if (has() && typeof forgeProPanelsApply === "function") forgeProPanelsApply(p);
      const sheet = document.getElementById("forge");
      if (sheet) sheet.classList.toggle("forge-bare", p.floats === false);
      const out = document.getElementById("forge-outliner");
      if (out) out.classList.toggle("collapsed", p.outlinerFold === true);
      const ui = document.getElementById("forge-ui-btn");
      if (ui) ui.classList.toggle("on", api2.anyHidden());
    }
    function set(which, on) {
      const p = read();
      if (which === "outliner") p.outlinerFold = !on;           // the title folds the list; the column stays
      else if (which === "side") p.create = !!on;               // the left column = the Create panel
      else if (which === "floats") p.floats = !!on;             // every bar over the viewport
      else p[which] = !!on;
      write(p); apply();
      return !!on;
    }
    const api2 = {
      state: () => Object.assign({}, read()),
      apply: apply,
      set: set,
      toggle: (which) => {
        const p = read();
        const now = which === "outliner" ? !p.outlinerFold : which === "side" ? !!p.create : which === "floats" ? p.floats !== false : !!p[which];
        return set(which, !now);
      },
      show: (which) => set(which, true),
      hide: (which) => set(which, false),
      hideAll: () => {                                          // only the viewport, like the pro Ctrl+Space
        const p = read();
        if (!(p.outliner === false && p.channel === false)) { p._before = Object.assign({}, p); delete p._before._before; }
        Object.assign(p, { outliner: false, channel: false, create: false, materials: false, shelf: false, toolkit: false, floats: false });
        write(p); apply(); return true;
      },
      showAll: () => {
        const p = read(), b = p._before || {};
        const next = Object.assign({}, p, { outliner: true, channel: true, floats: true, outlinerFold: false },
          { create: !!b.create, materials: !!b.materials, shelf: !!b.shelf, toolkit: !!b.toolkit });
        delete next._before;
        write(next); apply(); return true;
      },
      anyHidden: () => { const p = read(); return p.outliner === false || p.channel === false || p.floats === false || p.outlinerFold === true; },
    };
    return api2;
  })();

  // ---------------------------------------------------------------- undo for the scene (2026-10-21)
  // Owner: "the history in forge doesn't work". The undo queue (forge.js) only knew the working mesh: Create, Delete,
  // Group, Parent, a manipulator drag, a typed channel, a rename, hide/show or picking another object were not
  // undoable, and editing another object wiped the queue. Now every entry carries the scene too, and every scene
  // change is ONE entry: api calls, menu / hotkey commands (forgeProRun), manipulator drags, Channel Box edits and
  // scrubs, the Outliner's drag-and-drop. Nested calls (Group calls reparent ...) collapse into the outermost chunk.
  let undoDepth = 0, undoBefore = null, undoLabel = "", restoring = false;
  function sceneSig() {
    const a = [tree.rootId, tree.sel.join(","), root().multiSession ? "M" + root().multiSession.owners.map((o) => o.id).join(".") : ""];
    for (const l of tree.layers) a.push("L" + l.id, l.name, l.visible ? 1 : 0, l.template ? 1 : 0, l.ref ? 1 : 0, [...l.nodes].sort().join("."));
    a.push("cur" + tree.curLayer, "d" + [tree.defLayer.visible ? 1 : 0, tree.defLayer.template ? 1 : 0, tree.defLayer.ref ? 1 : 0].join(""));
    for (const n of tree.nodes) {
      a.push(n.id, n.name, n.parent, n.visible ? 1 : 0, n.inner.uuid, n.rotOrder || "XYZ");
      if (n.keys) a.push(JSON.stringify(n.keys));
      a.push.apply(a, n.grp.position.toArray()); a.push.apply(a, n.grp.quaternion.toArray()); a.push.apply(a, n.grp.scale.toArray());
      a.push.apply(a, n.piv.toArray()); a.push.apply(a, n.pc.toArray());
    }
    a.push("sets:" + JSON.stringify(tree.sets || []));
    return a.join("|");
  }
  const histCopy = (h) => (h && typeof forgeHistCopy === "function" ? forgeHistCopy(h) : h ? JSON.parse(JSON.stringify(h)) : null);
  view.sceneCapture = () => ({
    sig: sceneSig(),
    nodes: tree.nodes.map((n) => ({ n: n, name: n.name, kind: n.kind, parent: n.parent, visible: n.visible, open: n.open,
      root: !!n.root, auto: !!n.auto, inner: n.inner, innerPos: n.inner.position.clone(), piv: n.piv.clone(), pc: n.pc.clone(),
      rotOrder: n.rotOrder || "XYZ", attrs: (n.attrs || []).map((a) => ({ name: a.name, value: a.value })),
      keys: n.keys ? JSON.parse(JSON.stringify(n.keys)) : null,
      pos: n.grp.position.clone(), quat: n.grp.quaternion.clone(), scale: n.grp.scale.clone(),
      shape: n.root ? null : shapeOf(n), poly: n.poly, hist: n.root ? null : histCopy(n.hist), tri: n.tri, multi: n.multiSession || null })),
    sel: tree.sel.slice(), anchor: tree.anchor, next: tree.next, rootId: tree.rootId,
    hiddenLast: (tree.hiddenLast || []).slice(), lastDup: tree.lastDup ? tree.lastDup.slice() : null,
    layers: tree.layers.map((l) => ({ id: l.id, name: l.name, color: l.color, visible: l.visible, template: l.template, ref: !!l.ref, nodes: [...l.nodes] })),
    layerNext: tree.layerNext, curLayer: tree.curLayer, defLayer: { ...tree.defLayer },
    sets: JSON.parse(JSON.stringify(tree.sets || [])), setNext: tree.setNext,
  });
  view.sceneRestore = (st) => {
    if (!st || !st.nodes) return;
    restoring = true;
    try {
      const keep = new Set(st.nodes.map((x) => x.n));
      for (const n of tree.nodes) if (!keep.has(n) && n.grp.parent) n.grp.parent.remove(n.grp);
      const rootChanged = st.rootId !== tree.rootId;
      for (const x of st.nodes) {
        const n = x.n;
        for (const c of n.grp.children.slice()) if (c !== x.inner) n.grp.remove(c);
        if (x.inner.parent !== n.grp) n.grp.add(x.inner);
        for (const c of x.inner.children.slice()) {
          if (c.isMesh && c.name === "shape" && c !== x.shape) x.inner.remove(c);
          else if (c.userData && c.userData.forgeNode) x.inner.remove(c);          // children go back below
        }
        if (x.shape && x.shape.parent !== x.inner) x.inner.add(x.shape);
        Object.assign(n, { name: x.name, kind: x.kind, parent: x.parent, visible: x.visible, open: x.open, root: x.root,
          auto: x.auto, inner: x.inner, poly: x.poly, hist: histCopy(x.hist), tri: x.tri, multiSession: x.multi || null });
        n.piv.copy(x.piv); n.pc.copy(x.pc);
        n.rotOrder = x.rotOrder || "XYZ"; n.grp.rotation.order = n.rotOrder;   // before the quaternion, so the Euler re-derives in the right order
        n.attrs = (x.attrs || []).map((a) => ({ name: a.name, value: a.value }));
        n.keys = x.keys ? JSON.parse(JSON.stringify(x.keys)) : null;
        n.grp.position.copy(x.pos); n.grp.quaternion.copy(x.quat); n.grp.scale.copy(x.scale);
        n.inner.position.copy(x.innerPos);
        n.grp.visible = x.visible; n.grp.name = x.name;
      }
      tree.nodes = st.nodes.map((x) => x.n);
      tree.byId = {}; for (const n of tree.nodes) tree.byId[n.id] = n;
      for (const n of tree.nodes) {
        const dest = n.parent && tree.byId[n.parent] ? tree.byId[n.parent].inner : scene;
        if (n.grp.parent !== dest) dest.add(n.grp);
      }
      tree.sel = st.sel.filter((id) => tree.byId[id]); tree.anchor = st.anchor; tree.next = Math.max(tree.next, st.next);
      tree.rootId = st.rootId; tree.hiddenLast = st.hiddenLast.slice(); tree.lastDup = st.lastDup ? st.lastDup.slice() : null;
      tree.layers = (st.layers || []).map((l) => ({ id: l.id, name: l.name, color: l.color, visible: l.visible, template: l.template, ref: !!l.ref, nodes: new Set(l.nodes) }));
      tree.layerNext = st.layerNext || tree.layerNext; tree.curLayer = st.curLayer || 0;
      tree.defLayer = Object.assign({ visible: true, template: false, ref: false }, st.defLayer || {}); api.applyLayers();
      tree.sets = JSON.parse(JSON.stringify(st.sets || [])); tree.setNext = st.setNext || tree.setNext || 1;
      if (rootChanged && typeof forgeModel !== "undefined") { forgeModel.last = null; forgeModel.prim = null; }
      scene.updateMatrixWorld(true);
    } finally { restoring = false; }
  };
  view.sceneRestored = () => {
    // an undo / redo that lands on a multi-edit state while you are in object mode: split it back at once (quietly),
    // so a whole object is never moved or exported with other objects' pieces inside it
    if (view.mode !== "poly" && root().multiSession) view.undoQuiet(() => api.multiEnd(true));
    for (const tcx of [tc]) if (tcx && tcx.object) {
      const n = api.active();
      let inScene = false; tcx.object.traverseAncestors((o) => { if (o === scene) inScene = true; });
      if (!inScene || !n) tcx.detach(); else if (view.mode !== "poly" && tcx.object !== n.grp) tcx.attach(n.grp);
    }
    tree.selMarks = true;
    drawMarks(); tree.build();
    view.dirty = true;
  };
  function undoChanged(b) {
    if (!b) return false;
    if (!b.scene || b.scene.sig !== sceneSig()) return true;
    if (b.sm !== (view.sm || null) || b.poly !== view.poly) return true;
    const w = view.sm && view.sm.wpos;
    if (b.wpos && w) { if (b.wpos.length !== w.length) return true; for (let i = 0; i < w.length; i++) if (w[i] !== b.wpos[i]) return true; }
    const h = window.forgeHistory && window.forgeHistory.list ? window.forgeHistory.list().length : 0;
    const hb = b.history && b.history.ops ? b.history.ops.length : 0;
    return h !== hb;
  }
  view.undoOpen = (label) => {
    if (restoring || !view.undoState) return;
    if (undoDepth++ === 0) { undoBefore = view.undoState(); undoLabel = label || ""; }
  };
  view.undoClose = () => {
    if (restoring || undoDepth <= 0) return;
    if (--undoDepth > 0) return;
    const b = undoBefore; undoBefore = null;
    if (b && undoChanged(b)) { b.label = undoLabel; view.pushUndo(b); }
  };
  view.undoHold = () => undoDepth > 0;
  view.undoQuiet = (fn) => { const was = restoring; restoring = true; try { return fn(); } finally { restoring = was; } };
  view.undoChunk = (label, fn) => { view.undoOpen(label); try { return fn(); } finally { view.undoClose(); } };
  api.undoChunk = view.undoChunk;
  const RECORDED = ["add", "duplicate", "duplicateWithTransform", "rename", "setVisible", "toggleVisible", "hide", "show",
    "showLastHidden", "hideUnselected", "showAll", "remove", "removeSelected", "reparent", "parentSelected", "unparentSelected",
    "group", "ungroup", "select", "selectMany", "selectAll", "selectNone", "invertSelection", "selectHierarchy", "pickWalk",
    "setTransform", "setPivot", "centerPivot", "resetPivot", "pivotBottom", "pivotOrigin", "pivotToSelection", "freeze", "resetTransform", "groupSelected", "makeWorking",
    "combine", "separate", "replaceWith", "newObject", "dropOn", "multiBegin", "multiEnd",
    "layerAdd", "layerRemove", "layerRename", "layerSetVisible", "layerSetTemplate", "layerSetRef", "layerAssign", "layerCurrent", "addImagePlane",
    "setKey", "deleteKey", "clearKeys"];
  for (const name of RECORDED) {
    const fn = api[name];
    if (typeof fn !== "function" || fn.recorded) continue;
    const w = function () { view.undoOpen(name); try { return fn.apply(this, arguments); } finally { view.undoClose(); } };
    w.recorded = true;
    api[name] = w;
  }
  for (const id of ["forge-channel", "forge-history"]) {   // a typed or scrubbed channel, a history amount: one step
    const box = () => document.getElementById(id);
    setTimeout(() => {
      const b = box(); if (!b) return;
      b.addEventListener("focusin", (e) => { if (e.target.tagName === "INPUT") view.undoOpen("setAttr"); });
      b.addEventListener("focusout", (e) => { if (e.target.tagName === "INPUT") view.undoClose(); });
      b.addEventListener("pointerdown", (e) => { if (e.target.classList && e.target.classList.contains("forge-ch-label")) { view.undoOpen("scrub");
        const up = () => { document.removeEventListener("pointerup", up, true); setTimeout(() => view.undoClose(), 0); };
        document.addEventListener("pointerup", up, true); } });
      b.addEventListener("click", (e) => { if (e.target.closest && e.target.closest("button")) { /* buttons run their own recorded api calls */ } }, true);
    }, 0);
  }

  ensureRoot();
  panel();
  channelBox();
  historyBox();
  layerBox();
  tree.build();
  if (window.forgePanels) {
    const head = document.querySelector("#forge .forge-head");
    if (head && !document.getElementById("forge-ui-btn")) {
      const ui = scnEl("button", "mini icon-mini forge-btn", "UI");
      ui.type = "button"; ui.id = "forge-ui-btn"; ui.dataset.icon = "chevron";
      ui.title = "Hide every panel (only the viewport), or bring them back - the same as Ctrl+Space.";
      ui.addEventListener("click", () => { if (window.forgePanels.anyHidden()) window.forgePanels.showAll(); else window.forgePanels.hideAll(); });
      head.insertBefore(ui, head.lastElementChild);
    }
    window.forgePanels.apply();
  }
  view.treeRefresh = () => { tree.build(); if (window.forgePanels) window.forgePanels.apply(); };
  // component mode: Shift + click on ANOTHER mesh adds it to what you edit - its vertices / edges / faces show and
  // are selectable with the first one's (Maya's hilite). The click only adds; a second Shift + click picks components.
  window.addEventListener("pointerdown", (e) => {
    if (e.target !== canvas || view.mode !== "poly" || e.button !== 0 || !e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) return;
    if ((view.gizmo && view.gizmo.axis) || (typeof forgeCamMod === "function" && forgeCamMod(e)) || typeof forgeProPickAt !== "function") return;
    const n = forgeProPickAt(view, e.clientX, e.clientY);
    if (!n || n.root || n.kind !== "mesh" || !hasGeometry(n)) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const now = api.multiIds(), all = (now.length ? now : [root().id]).concat([n.id]);
    const k = api.multiBegin(all);
    if (k) api.say(n.name + " added: " + k + " objects' components together (Shift + click another to add it; F8 splits them back).");
  }, true);
  // leaving component mode (object mode, sculpt ...) splits a multi-edit session back into its objects
  const setModeOwn = view.setMode;
  if (typeof setModeOwn === "function") view.setMode = (m) => {
    if (m !== "poly" && view.mode === "poly" && root().multiSession) api.multiEnd();
    return setModeOwn(m);
  };
  return api;
}

// the pro Create: a primitive is a NEW object (pCube1, pCube2 ...); whatever was there stays in the scene.
// Wrapped at load so the very first primitive is named too (forge_model.js loads before this file).
if (typeof window.forgeAddPrimitive === "function" && !window.forgeAddPrimitive.scene) {
  const forgeAddPrimitiveOwn = window.forgeAddPrimitive;
  const wrapped = async (kind) => {
    const P = window.ForgePoly && window.ForgePoly.PRIMITIVES[kind];
    const name = "p" + (P ? P.name.replace(/\s+/g, "") : "Mesh");
    const before = typeof forge !== "undefined" && forge.view && forge.view.tree && forge.view.tree.api;
    const v0 = typeof forge !== "undefined" && forge.view;
    if (v0 && v0.undoOpen) v0.undoOpen("create " + kind);              // Create is ONE undo step
    let out;
    try {
    if (before) before.newObject(name);
    out = await forgeAddPrimitiveOwn(kind);
    const t = forge.view && forge.view.tree && forge.view.tree.api;
    if (t) {
      const r = t.root();
      const name1 = () => {
        if (r.auto) { r.name = "\u0000"; t.rename(r.id, t.nextName(name)); r.auto = false; }
        t.select(r.id);
      };
      // the very first object of the session: naming it is part of making it, not a step of its own to undo
      if (!(v0 && v0.undoOpen) && forge.view.undoQuiet) forge.view.undoQuiet(name1); else name1();
    }
    } finally { if (v0 && v0.undoClose) v0.undoClose(); }
    return out;
  };
  wrapped.scene = true;
  window.forgeAddPrimitive = wrapped;
}
