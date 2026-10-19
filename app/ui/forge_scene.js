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

  const load = view.load;
  if (typeof load === "function") view.load = async (buf) => { const r = await load(buf); tree.build(); return r; };

  ensureRoot();
  panel();
  tree.build();
  // the working object is created on the first Make, so the list keeps itself true
  view.treeRefresh = () => tree.build();
  return api;
}
