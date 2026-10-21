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
  };
  const node = (id) => tree.byId[id];
  const kidsOf = (id) => tree.nodes.filter((n) => n.parent === id);

  // ---------------------------------------------------------------- pivots (the pro transform matrix)
  function rsMatrix(n) { return new THREE.Matrix4().compose(new THREE.Vector3(), n.grp.quaternion, n.grp.scale); }
  function translateOf(n) { return n.grp.position.clone().sub(n.pc).sub(n.piv); }
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
      open: true, piv: new THREE.Vector3(), pc: new THREE.Vector3(), tri: null, poly: null, hist: null };
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
    for (const k of kidsOf(src.id)) cloneNode(k, n.id);
    return n;
  }

  // ---------------------------------------------------------------- selection highlight in the viewport
  const marks = new Map(), edgeCache = new WeakMap();
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
          if (!ec || ec.ver !== ver) { ec = { ver, geo: new THREE.EdgesGeometry(o.geometry, 1) }; edgeCache.set(o.geometry, ec); }
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
  const api = {
    node: node,
    kids: kidsOf,
    list: () => tree.nodes.slice(),
    order: () => order().map((n) => n.id),
    root: () => root(),
    nextName: nextName,

    // a static copy of the working mesh as a new object (kept for older callers - Duplicate is the pro way)
    add(name) {
      const r = root();
      if (!hasGeometry(r)) return null;
      const n = cloneNode(r, r.parent);
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
      n.visible = !!on; n.grp.visible = n.visible;
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

    remove(id) {                                     // the node and everything under it (the pro Delete)
      const n = node(id);
      if (!n) return false;
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
      ids = ids.filter((id) => node(id));
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
    pickables() {
      const out = [];
      for (const n of tree.nodes) {
        if (!n.visible) continue;
        let vis = true; for (let p = n.parent; p; p = node(p).parent) if (!node(p).visible) { vis = false; break; }
        if (!vis) continue;
        const s = shapeOf(n); if (s && s.geometry) out.push(s);
      }
      return out;
    },

    // ---- every object is editable: the holder (the tools' mesh) moves into the node you edit
    makeWorking(id) {
      const n = node(id), r = root();
      if (!n || n.root || n.kind !== "mesh") return n ? n.root : false;
      if (view.modalActive && view.modalActive()) return false;
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

    // a new, empty working object (pro: every Create command makes a new node) - the old one stays as it is
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
    tc.addEventListener("objectChange", () => { if (tree.syncChannel) tree.syncChannel(); });
    tc.addEventListener("dragging-changed", (ev) => { if (!ev.value) { drawMarks(); if (tree.syncChannel) tree.syncChannel(); } });
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
        if (!ec || ec.ver !== ver) { ec = { ver, geo: new THREE.EdgesGeometry(o.geometry, 1) }; edgeCache.set(o.geometry, ec); }
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
    const r = scnEl("div", "forge-out-row" + (tree.sel.includes(n.id) ? " on" : "") + (lead ? " lead" : "") + (n.root ? " working" : ""));
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
    const kind = scnEl("span", "forge-out-kind " + (n.kind === "group" ? "kind-group" : "kind-mesh"), "");
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
          const hit = !f || n.name.toLowerCase().includes(f);
          if (hit) list.append(row(n, f ? 0 : depth));
          if (n.open || f) walk(n.id, depth + 1);
        }
      };
      walk(0, 0);
      if (tree.panel) tree.panel.dataset.count = String(tree.nodes.length);
    }
    if (tree.syncChannel) tree.syncChannel();
    if (tree.syncHistory) tree.syncHistory();
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
    mk("Channels", () => [["Key Selected", null], ["Reset to Default", () => { api.resetTransform(); tree.build(); }]]);
    mk("Edit", () => [["Delete History", () => { if (window.forgeHistory) window.forgeHistory.clear(); tree.build(); }],
      ["Freeze Transformations", () => { api.freeze(); tree.build(); }], ["Reset Transformations", () => { api.resetTransform(); tree.build(); }]]);
    mk("Object", () => [["Center Pivot", () => { api.centerPivot(); tree.build(); }], ["Reset Pivot", () => { api.resetPivot(); tree.build(); }],
      ["Select Hierarchy", () => api.selectHierarchy()]]);
    mk("Show", () => [["Shapes", () => { box.classList.toggle("no-shapes"); }], ["Inputs", () => { const h = document.getElementById("forge-history"); if (h) h.hidden = !h.hidden; }]]);
    const title = scnEl("div", "forge-ch-title", "");
    title.id = "forge-ch-name";
    box.append(tab, menus, title);
    const inputs = {};
    const ROWS = [];
    for (const [part, label, step] of [["translate", "Translate", 0.1], ["rotate", "Rotate", 5], ["scale", "Scale", 0.1]]) {
      for (let a = 0; a < 3; a++) ROWS.push([part, label + " " + AXES[a].toUpperCase(), a, step]);
    }
    for (const [part, label, a, step] of ROWS) {
      const r = scnEl("div", "forge-ch-row");
      const lbl = scnEl("span", "forge-ch-label", label);
      lbl.title = label + ": drag left / right to scrub the value (the pro virtual slider).";
      const inp = document.createElement("input");
      inp.type = "number"; inp.step = String(step);
      inp.id = "forge-ch-" + part.slice(0, 1) + AXES[a];
      inp.className = "forge-ch-in";
      inp.title = label + " - the selected object's own transform.";
      inp.addEventListener("input", () => {
        if (inp.value === "" || inp.value === "-") return;
        api.setTransform(null, part, a, inp.value);
      });
      inp.addEventListener("keydown", (e) => e.stopPropagation());      // typing a number is not a hotkey
      // scrub: press on the channel's name and drag sideways
      lbl.addEventListener("pointerdown", (e) => {
        if (e.button !== 0 && e.button !== 1) return;
        e.preventDefault();
        const t0 = api.transform(); if (!t0) return;
        const from = t0[part][a], x0 = e.clientX;
        lbl.setPointerCapture(e.pointerId); lbl.classList.add("scrub");
        const move = (ev) => { const v = from + (ev.clientX - x0) * step * (ev.shiftKey ? 0.1 : 0.25); api.setTransform(null, part, a, v); inp.value = String(Math.round(v * 1000) / 1000); };
        const up = () => { lbl.classList.remove("scrub"); lbl.removeEventListener("pointermove", move); lbl.removeEventListener("pointerup", up); tree.build(); };
        lbl.addEventListener("pointermove", move); lbl.addEventListener("pointerup", up);
      });
      inputs[part + a] = inp;
      r.append(lbl, inp);
      box.append(r);
    }
    const vis = scnEl("div", "forge-ch-row");
    const visIn = scnEl("button", "forge-ch-in forge-ch-vis", "on");
    visIn.type = "button"; visIn.id = "forge-ch-vis";
    visIn.addEventListener("click", () => { const n = api.active(); if (n) api.setVisible(n.id, !n.visible); });
    vis.append(scnEl("span", "forge-ch-label", "Visibility"), visIn);
    box.append(vis);
    const shapesHead = scnEl("div", "forge-ch-section", "SHAPES");
    const shapeRow = scnEl("div", "forge-ch-node", "");
    shapesHead.classList.add("forge-ch-shapes"); shapeRow.classList.add("forge-ch-shapes");
    box.append(shapesHead, shapeRow);
    host.append(box);
    tree.syncChannel = () => {
      const t = api.transform(), n = api.active();
      title.textContent = n ? n.name : "";
      shapeRow.textContent = n && n.kind === "mesh" ? n.name + "Shape" : "";
      shapesHead.hidden = shapeRow.hidden = !(n && n.kind === "mesh");
      visIn.textContent = n && !n.visible ? "off" : "on";
      if (!t) return;
      for (const part of ["translate", "rotate", "scale"]) {
        const vals = t[part];
        for (let a = 0; a < 3; a++) {
          const inp = inputs[part + a];
          if (inp && document.activeElement !== inp) inp.value = String(Math.round(vals[a] * 1000) / 1000);
        }
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
        const base = FORGE_HIST_NODE[op.kind] || op.kind;
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
    const a = [tree.rootId, tree.sel.join(",")];
    for (const n of tree.nodes) {
      a.push(n.id, n.name, n.parent, n.visible ? 1 : 0, n.inner.uuid);
      a.push.apply(a, n.grp.position.toArray()); a.push.apply(a, n.grp.quaternion.toArray()); a.push.apply(a, n.grp.scale.toArray());
      a.push.apply(a, n.piv.toArray()); a.push.apply(a, n.pc.toArray());
    }
    return a.join("|");
  }
  const histCopy = (h) => (h && typeof forgeHistCopy === "function" ? forgeHistCopy(h) : h ? JSON.parse(JSON.stringify(h)) : null);
  view.sceneCapture = () => ({
    sig: sceneSig(),
    nodes: tree.nodes.map((n) => ({ n: n, name: n.name, kind: n.kind, parent: n.parent, visible: n.visible, open: n.open,
      root: !!n.root, auto: !!n.auto, inner: n.inner, innerPos: n.inner.position.clone(), piv: n.piv.clone(), pc: n.pc.clone(),
      pos: n.grp.position.clone(), quat: n.grp.quaternion.clone(), scale: n.grp.scale.clone(),
      shape: n.root ? null : shapeOf(n), poly: n.poly, hist: n.root ? null : histCopy(n.hist), tri: n.tri })),
    sel: tree.sel.slice(), anchor: tree.anchor, next: tree.next, rootId: tree.rootId,
    hiddenLast: (tree.hiddenLast || []).slice(), lastDup: tree.lastDup ? tree.lastDup.slice() : null,
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
          auto: x.auto, inner: x.inner, poly: x.poly, hist: histCopy(x.hist), tri: x.tri });
        n.piv.copy(x.piv); n.pc.copy(x.pc);
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
      if (rootChanged && typeof forgeModel !== "undefined") { forgeModel.last = null; forgeModel.prim = null; }
      scene.updateMatrixWorld(true);
    } finally { restoring = false; }
  };
  view.sceneRestored = () => {
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
    "setTransform", "setPivot", "centerPivot", "resetPivot", "freeze", "resetTransform", "groupSelected", "makeWorking",
    "combine", "separate", "newObject", "dropOn"];
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
