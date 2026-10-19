// Forge's scene - the tree of objects Maya has and Forge did not (owner 2026-10-20: "the groups different
// object and hierarchy, history and transforms ... especially the outliner and the logic behind it all").
//
// This is task T1 of docs/FORGE_MAYA.md: Maya is a DAG of transform nodes with shapes under them, while Forge
// used to flatten every model into ONE welded mesh. Here that mesh becomes node 1 - the WORKING object, still
// the very same holder/mesh the sculpt and poly tools edit, so nothing that already works had to change - and
// every other node is a real object with its own three.js transform and its own copy of the geometry.
//
// With that, the Outliner (T2), Duplicate (T5) and Group / Ungroup (T3) become possible: a group is a
// transform node with children, grouping puts the new node's ORIGIN at the centre of the selection (which is
// why Maya's groups turn about the middle and not the world origin), and ungrouping re-parents each child
// while three.js' attach() preserves its world transform (Maya does not snap children to the origin).
"use strict";

function scnEl(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function forgeSceneAttach(view, ctx) {
  const { THREE, scene, holder, material } = ctx;
  if (!scene || !holder) return null;

  const tree = view.tree = {
    nodes: [], byId: {}, next: 1, sel: [],
    rootId: 0, panel: null, list: null,
  };

  const node = (id) => tree.byId[id];
  const kidsOf = (id) => tree.nodes.filter((n) => n.parent === id);

  // ---------------------------------------------------------------- the nodes
  function makeNode(name, grp, kind, parent, sm) {
    const n = { id: tree.next++, name: name, grp: grp, kind: kind, parent: parent || 0, sm: sm || null,
      visible: true };
    tree.nodes.push(n); tree.byId[n.id] = n;
    if (grp) grp.name = name;
    return n;
  }

  // node 1 is the working object - the one the tools edit (holder, with view.sm inside)
  function ensureRoot() {
    if (tree.rootId) return node(tree.rootId);
    const r = makeNode("object1", holder, "mesh", 0, null);
    r.root = true;
    tree.rootId = r.id;
    return r;
  }

  function smOf(n) { return n.root ? view.sm : n.sm; }
  function shapeOf(n) { return n.grp ? n.grp.children.find((o) => o.isMesh && o.geometry) : null; }

  // the middle of the working mesh, in the holder's own space
  function centreOf(sm) {
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < sm.n; i++) for (let k = 0; k < 3; k++) {
      const x = sm.wpos[i * 3 + k]; if (x < lo[k]) lo[k] = x; if (x > hi[k]) hi[k] = x;
    }
    return new THREE.Vector3((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2);
  }

  // transform every welded vertex of the working mesh (undoable), then push it back to the GPU
  function bakeRoot(m) {
    const sm = view.sm;
    if (!sm) return false;
    if (view.undoStack) {
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
    return true;
  }

  // ---------------------------------------------------------------- building extra objects
  function geometryFrom(tri, col) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(tri.pos, 3));
    if (col) { const c = new Float32Array(tri.pos.length); for (let i = 0; i < c.length; i++) c[i] = col[i % col.length]; g.setAttribute("color", new THREE.BufferAttribute(c, 3)); }
    g.setIndex(new THREE.BufferAttribute(tri.idx, 1));
    g.computeVertexNormals();
    return g;
  }

  function meshFor(src) {                       // a fresh object with its own copy of the geometry
    const tri = src.root ? view.triangles() : src.tri;
    if (!tri) return null;
    const grp = new THREE.Group();
    const m = new THREE.Mesh(geometryFrom(tri, src.root && view.sm ? view.sm.col : null),
      material ? material.clone() : undefined);
    m.name = "shape";
    grp.add(m);
    return grp;
  }

  // ---------------------------------------------------------------- the API the menus and the Outliner use
  const api = {
    node: node,
    kids: kidsOf,
    list: () => tree.nodes.slice(),

    add(name) {
      const grp = meshFor(ensureRoot());
      if (!grp) return null;
      const n = makeNode(name || ("object" + tree.next), grp, "mesh", 0, null);
      n.tri = view.triangles();
      if (holder.parent) holder.parent.add(grp); else scene.add(grp);
      grp.position.copy(holder.position); grp.quaternion.copy(holder.quaternion); grp.scale.copy(holder.scale);
      tree.build(); api.select(n.id);
      return n;
    },

    duplicate(name) { return api.add(name || (api.active().name + "_copy")); },

    rename(id, name) {
      const n = node(id); if (!n || !name) return false;
      n.name = name; if (n.grp) n.grp.name = name;
      tree.build(); return true;
    },

    setVisible(id, on) {
      const n = node(id); if (!n) return false;
      n.visible = !!on; if (n.grp) n.grp.visible = n.visible;
      tree.build(); return true;
    },

    remove(id) {
      const n = node(id);
      if (!n || n.root) return false;                 // the working object stays (the tools edit it)
      for (const k of kidsOf(id)) api.reparent(k.id, n.parent);
      if (n.grp && n.grp.parent) n.grp.parent.remove(n.grp);
      tree.nodes = tree.nodes.filter((x) => x !== n); delete tree.byId[id];
      tree.sel = tree.sel.filter((x) => x !== id);
      tree.build(); return true;
    },

    reparent(id, parentId) {                          // three.js' attach() keeps the world transform
      const n = node(id), p = parentId ? node(parentId) : null;
      if (!n || n === p || (p && p.kind !== "group" && p !== node(tree.rootId))) return false;
      if (p === n.grp) return false;
      const dest = p ? p.grp : (holder.parent || scene);
      if (n.grp && dest && n.grp.parent !== dest) dest.attach(n.grp);
      n.parent = p ? p.id : 0;
      tree.build(); return true;
    },

    // Maya's Group: a new transform node whose origin is the centre of the selection
    group(name, ids) {
      const list = (ids && ids.length ? ids : tree.sel).map(node).filter((n) => n && !n.root);
      const grp = new THREE.Group();
      (holder.parent || scene).add(grp);
      const box = new THREE.Box3();
      for (const n of list) box.expandByObject(n.grp);
      const centre = box.isEmpty() ? new THREE.Vector3() : box.getCenter(new THREE.Vector3());
      grp.position.copy(centre);                      // the pivot Maya would put at the selection's centre
      const g = makeNode(name || "group1", grp, "group", 0, null);
      for (const n of list) { grp.attach(n.grp); n.parent = g.id; }
      tree.build(); api.select(g.id);
      return g;
    },

    ungroup(id) {
      const g = node(id);
      if (!g || g.kind !== "group") return false;
      const parent = g.parent ? node(g.parent) : null;
      const dest = parent ? parent.grp : (holder.parent || scene);
      for (const k of kidsOf(id)) { dest.attach(k.grp); k.parent = g.parent; }
      if (g.grp.parent) g.grp.parent.remove(g.grp);
      tree.nodes = tree.nodes.filter((x) => x !== g); delete tree.byId[id];
      tree.build(); return true;
    },

    select(id, add) {
      if (id == null) tree.sel = [];
      else if (add) tree.sel = tree.sel.includes(id) ? tree.sel.filter((x) => x !== id) : tree.sel.concat([id]);
      else tree.sel = [id];
      tree.build(); return tree.sel.slice();
    },

    selected: () => tree.sel.slice(),

    // the node's own transform, local to its parent - what Maya's Channel Box shows
    transform(id) {
      const n = node(id || api.active().id);
      if (!n || !n.grp) return null;
      const r = n.grp.rotation;
      return { translate: n.grp.position.toArray(), rotate: [r.x, r.y, r.z].map((v) => v * 180 / Math.PI),
               scale: n.grp.scale.toArray() };
    },

    setTransform(id, part, axis, value) {
      const n = node(id || api.active().id);
      const v = Number(value);
      if (!n || !n.grp || !isFinite(v)) return false;
      if (part === "translate") n.grp.position["xyz"[axis]] = v;
      else if (part === "rotate") n.grp.rotation["xyz"[axis]] = v * Math.PI / 180;
      else if (part === "scale") n.grp.scale["xyz"[axis]] = v;
      n.grp.updateMatrixWorld(true);
      if (n.root && view.dirty !== undefined) view.dirty = true;
      return true;
    },

    // Maya's Modify > Center Pivot: the manipulator's origin moves to the middle of the object, and the
    // object does NOT move - so the vertices shift one way by the centre and the node's transform shifts the
    // other. Export bakes the node's transform, so the two cancel and what Save writes is unchanged.
    centerPivot(id) {
      const n = node(id || api.active().id);
      if (!n || !n.grp) return false;
      if (n.root) {
        const sm = view.sm;
        if (!sm) return false;
        const c = centreOf(sm);
        bakeRoot(new THREE.Matrix4().makeTranslation(-c.x, -c.y, -c.z));
        n.grp.position.add(c);
      } else {
        const m = shapeOf(n);
        if (!m) return false;
        m.geometry.computeBoundingBox();
        const c = m.geometry.boundingBox.getCenter(new THREE.Vector3());
        m.geometry.translate(-c.x, -c.y, -c.z);
        n.grp.position.add(c);
      }
      n.grp.updateMatrixWorld(true);
      return true;
    },

    // Maya's Modify > Freeze Transformations: the node's transform is baked into the vertices and the node
    // goes back to identity, so the object does not appear to move at all.
    freeze(id) {
      const n = node(id || api.active().id);
      if (!n || !n.grp) return false;
      n.grp.updateMatrix();
      const m = n.grp.matrix.clone();
      if (n.root) bakeRoot(m);
      else { const shape = shapeOf(n); if (!shape) return false; shape.geometry.applyMatrix4(m); }
      n.grp.position.set(0, 0, 0); n.grp.rotation.set(0, 0, 0); n.grp.scale.set(1, 1, 1);
      n.grp.updateMatrixWorld(true);
      return true;
    },

    resetTransform(id) {                              // Maya's Reset: the node back on the origin, unscaled
      const n = node(id || api.active().id);
      if (!n || !n.grp) return false;
      n.grp.position.set(0, 0, 0); n.grp.rotation.set(0, 0, 0); n.grp.scale.set(1, 1, 1);
      n.grp.updateMatrixWorld(true);
      return true;
    },
    active() { const n = node(tree.sel[tree.sel.length - 1]) || node(tree.rootId); return n || ensureRoot(); },

    groupSelected(name) { return api.group(name, tree.sel); },
  };
  tree.api = api;

  // ---------------------------------------------------------------- the Outliner
  function panel() {
    if (tree.panel && document.body.contains(tree.panel)) return tree.panel;
    const side = document.getElementById("forge-left") || document.getElementById("forge-stage");
    if (!side) return null;
    const box = scnEl("div", "forge-outliner");
    box.id = "forge-outliner";
    const head = scnEl("div", "forge-out-head");
    head.append(scnEl("span", "forge-out-title", "Outliner"));
    const bar = scnEl("div", "forge-out-bar");
    const btn = (label, what, run) => {
      const b = scnEl("button", "forge-out-btn", label);
      b.type = "button"; b.title = what; b.addEventListener("click", run); bar.append(b); return b;
    };
    btn("Copy", "Duplicate the selected object (T5).", () => { api.duplicate(); api.say("Duplicated."); });
    btn("Group", "Group the selection under a new node whose pivot is the selection's centre (Ctrl+G).", () => api.groupSelected());
    btn("Ungroup", "Take the children out of the selected group (Ctrl+Shift+G).", () => {
      for (const id of tree.sel.slice()) api.ungroup(id);
    });
    const reset = scnEl("button", "forge-out-btn", "Reset");
    reset.type = "button"; reset.id = "forge-ch-reset";
    reset.title = "Put the selected object back on the origin, unscaled (Maya's Reset).";
    reset.addEventListener("click", () => { api.resetTransform(); tree.build(); api.say("Transform reset."); });
    bar.append(reset);
    const pivot = scnEl("button", "forge-out-btn", "Pivot");
    pivot.type = "button"; pivot.id = "forge-ch-pivot";
    pivot.title = "Center Pivot: put the manipulator's origin on the middle of the object (the object does not move).";
    pivot.addEventListener("click", () => {
      if (api.centerPivot()) { tree.build(); api.say("Pivot centered on the object (Modify > Center Pivot)."); }
      else api.say("Select an object with a mesh first.", true);
    });
    const freeze = scnEl("button", "forge-out-btn", "Freeze");
    freeze.type = "button"; freeze.id = "forge-ch-freeze";
    freeze.title = "Freeze Transformations: bake the transform into the mesh, leave the object where it is.";
    freeze.addEventListener("click", () => {
      if (api.freeze()) { tree.build(); api.say("Transformations frozen into the mesh (Modify > Freeze Transformations)."); }
      else api.say("Select an object with a mesh first.", true);
    });
    bar.append(pivot, freeze);
    head.append(bar);
    const list = scnEl("div", "forge-out-list"); list.id = "forge-out-list";
    box.append(head, list);
    side.append(box);
    tree.panel = box; tree.list = list;
    return box;
  }

  api.say = (text) => { if (typeof forgeSay === "function") forgeSay(text); };

  function row(n, depth) {
    const r = scnEl("div", "forge-out-row" + (tree.sel.includes(n.id) ? " on" : ""));
    r.dataset.id = String(n.id); r.dataset.kind = n.kind;
    r.style.paddingLeft = (6 + depth * 12) + "px";
    r.draggable = !n.root;
    const eye = scnEl("button", "forge-out-eye" + (n.visible ? "" : " off"), n.visible ? "\u25c9" : "\u25cb");
    eye.type = "button"; eye.title = "Show or hide this object (v).";
    eye.addEventListener("click", (ev) => { ev.stopPropagation(); api.setVisible(n.id, !n.visible); });
    const lbl = scnEl("span", "forge-out-name", n.name);
    lbl.title = "Click to select, double-click to rename, drag onto a group to move it inside.";
    lbl.addEventListener("dblclick", (ev) => {
      ev.stopPropagation();
      const input = scnEl("input", "forge-out-edit"); input.value = n.name;
      const done = (ok) => {
        if (ok && input.value.trim()) api.rename(n.id, input.value.trim());
        tree.build();
      };
      input.addEventListener("keydown", (e2) => {
        e2.stopPropagation();
        if (e2.key === "Enter") done(true); else if (e2.key === "Escape") done(false);
      });
      input.addEventListener("blur", () => done(true));
      lbl.replaceWith(input); input.focus(); input.select();
    });
    r.append(eye, lbl);
    r.addEventListener("click", () => api.select(n.id, false));
    r.addEventListener("dragstart", (ev) => ev.dataTransfer.setData("text/plain", String(n.id)));
    r.addEventListener("dragover", (ev) => { ev.preventDefault(); r.classList.add("drop"); });
    r.addEventListener("dragleave", () => r.classList.remove("drop"));
    r.addEventListener("drop", (ev) => {
      ev.preventDefault(); r.classList.remove("drop");
      const from = parseInt(ev.dataTransfer.getData("text/plain"), 10);
      if (from) { api.reparent(from, n.kind === "group" ? n.id : n.parent); api.say("Moved under " + api.node(n.kind === "group" ? n.id : n.parent).name + "."); }
    });
    return r;
  }

  tree.build = () => {
    const list = tree.list;
    if (!list) return;
    list.textContent = "";
    const walk = (parent, depth) => {
      for (const n of tree.nodes) if (n.parent === parent) {
        list.append(row(n, depth));
        walk(n.id, depth + 1);
      }
    };
    walk(0, 0);
    const box = tree.panel;
    if (box) box.dataset.count = String(tree.nodes.length);
    if (tree.syncChannel) tree.syncChannel();
    if (tree.syncHistory) tree.syncHistory();
  };

  // ---------------------------------------------------------------- Ctrl+G / Ctrl+Shift+G, like Maya
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.key !== "g" && e.key !== "G") return;
    const sheet = document.getElementById("forge");
    if (!sheet || sheet.hidden || !view.sm) return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (e.shiftKey) { for (const id of tree.sel.slice()) api.ungroup(id); api.say("Ungrouped."); }
    else { const g = api.groupSelected(); if (g) api.say("Grouped " + g.name + " about the selection's centre."); }
  }, true);

  // ---------------------------------------------------------------- the Channel Box (T4): exact numbers
  const AXES = ["x", "y", "z"];
  function channelBox() {
    const host = document.getElementById("forge-outliner");   // Maya keeps the Channel Box under the Outliner
    if (!host) return null;
    const box = scnEl("div", "forge-ch-body");
    box.id = "forge-channel";
    box.append(scnEl("div", "forge-ch-title", "Channel Box"));
    const inputs = {};
    for (const [part, label, step] of [["translate", "Translate", 0.1], ["rotate", "Rotate", 5], ["scale", "Scale", 0.1]]) {
      const row = scnEl("div", "forge-ch-row");
      row.append(scnEl("span", "forge-ch-label", label));
      for (let a = 0; a < 3; a++) {
        const inp = document.createElement("input");
        inp.type = "number"; inp.step = String(step);
        inp.id = "forge-ch-" + part.slice(0, 1) + AXES[a];
        inp.className = "forge-ch-in";
        inp.title = label + " " + AXES[a].toUpperCase() + " (the selected object's own transform).";
        inp.addEventListener("input", () => {
          api.setTransform(null, part, a, inp.value);
          if (part === "scale" && Number(inp.value) === 0) inp.value = "1";   // a zero scale would vanish
        });
        inputs[part + a] = inp; row.append(inp);
      }
      box.append(row);
    }
    host.append(box);
    tree.syncChannel = () => {
      const t = api.transform();
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

  // ---------------------------------------------------------------- the History (T6, Maya's construction history)
  function historyBox() {
    const host = document.getElementById("forge-outliner");
    if (!host) return null;
    const box = scnEl("div", "forge-ch-body");
    box.id = "forge-history";
    const head = scnEl("div", "forge-hist-head");
    head.append(scnEl("div", "forge-ch-title", "History"));
    const del = scnEl("button", "forge-out-btn", "Delete History");
    del.type = "button"; del.id = "forge-hist-clear";
    del.title = "Forget how the mesh was built; the shape stays (Maya's Delete History).";
    del.addEventListener("click", () => { if (window.forgeHistory) window.forgeHistory.clear(); tree.build(); });
    head.append(del);
    const list = scnEl("div", "forge-hist-list"); list.id = "forge-hist-list";
    box.append(head, list);
    host.append(box);
    tree.syncHistory = () => {
      const H = window.forgeHistory;
      const ops = H && H.list ? H.list() : [];
      list.textContent = "";
      if (!ops.length) { list.append(scnEl("div", "forge-hist-empty", "Nothing yet - extrude or inset a face.")); return; }
      for (const op of ops) {
        const row = scnEl("div", "forge-hist-row");
        row.append(scnEl("span", "forge-hist-name", op.kind + (op.affected ? " \u00b7 " + op.affected + "v" : "")));
        if (op.amount != null) {
          const inp = document.createElement("input");
          inp.type = "number"; inp.step = "0.05"; inp.className = "forge-ch-in";
          inp.value = String(Math.round(op.amount * 1000) / 1000);
          inp.title = "Change this step's amount - the model rebuilds from the first step.";
          inp.addEventListener("input", () => H.setAmount(op.i, inp.value));
          row.append(inp);
        }
        const x = scnEl("button", "forge-hist-x", "\u00d7");
        x.type = "button"; x.title = "Remove this step and rebuild without it.";
        x.addEventListener("click", () => H.remove(op.i));
        row.append(x);
        list.append(row);
      }
    };
    return box;
  }

  const load = view.load;
  if (typeof load === "function") view.load = async (buf) => { const r = await load(buf); tree.build(); return r; };

  // ---------------------------------------------------------------- T6c: a sculpt stroke in the history
  // A stroke moves WELDED vertices, not polygons, so it is recorded as the vertices it changed with their
  // positions before and after - never as a list of dabs, which would be enormous. Maya's sculpt node keeps
  // the same kind of record, and it shares the limitation: a step ABOVE it that is later changed can make the
  // record stale (Maya warns too). forge.js calls snapshot() on stroke start, so the undo stack's top is the
  // state BEFORE the stroke - no change to the sculpting code was needed to read both ends.
  const canvas = ctx.canvas;
  function sculptRecordAfterStroke() {
    // forge.js snapshot()s at the START of a stroke, so the top of the undo stack is the state before it
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
  }
  if (canvas && canvas.addEventListener) {
    view.sculptStrokeEnd = sculptRecordAfterStroke;      // also the handle for tests and scripts
    canvas.addEventListener("pointerup", (e) => { if (e.button === 0) sculptRecordAfterStroke(); });
    canvas.addEventListener("pointerleave", () => sculptRecordAfterStroke());
  }

  // ---------------------------------------------------------------- T5: Shift + drag duplicates (Maya)
  // In Maya, shift-dragging a manipulator leaves the original where it was and drags a copy. The manipulator
  // here is attached to the object, so on the moment a drag starts with Shift down we make the copy and hand
  // the manipulator to it - the original stops moving at once and the copy follows the mouse.
  let shiftDown = false;
  document.addEventListener("keydown", (e) => { if (e.key === "Shift") shiftDown = true; }, true);
  document.addEventListener("keyup", (e) => { if (e.key === "Shift") shiftDown = false; }, true);
  api.shiftDown = () => shiftDown;
  const tc = ctx.transform || null;
  if (tc && tc.addEventListener) {
    tc.addEventListener("dragging-changed", (ev) => {
      if (!ev || !ev.value || !shiftDown) return;
      const from = api.active();
      if (!from || from.kind !== "mesh") return;
      const copy = api.duplicate(from.name + "_copy");
      if (copy && tc.attach) { tc.attach(copy.grp); tree.build(); api.say("Shift-drag: " + copy.name + " is the copy, the original stayed."); }
    });
  }

  ensureRoot();
  panel();
  channelBox();
  historyBox();
  tree.build();
  // the working object is created on the first Make, so the list keeps itself true
  view.treeRefresh = () => tree.build();
  return api;
}
