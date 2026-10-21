// Forge, the way pro works: the pro hotkeys, its marking menus (by context, released by direction), the
// Space-bar hotbox with its zones, the Space tap between one and four views, the pro Alt/Option camera, pick-walk,
// pivot editing (d / Insert) and the rest of docs/FORGE_PRO_SPEC.md - which was read off the reference package itself.
// (owner 2026-10-19: "pro is my love I want it exactly on here ... the hotkeys especially the movement command
// control option shift")
//
// the pro interaction DESIGN, re-written for a web canvas: no the vendor code, MEL, art or icons are used.
// Ctrl and Cmd are the same key here (pro binds both on the Mac); Alt is Option.
// pro only (owner 2026-10-19: "remove blender hotkeys and movements, only keep pro stuff"). The window is pro's
// workspace: a big viewport, the Outliner on the left, the Channel Box on the right; everything else is hidden and
// comes back from the Space menu (Windows) - see forgeProPanels. Snapping is pro's: hold x (grid), c (edge /
// curve), v (point / vertex), or switch them on in the hotbox's Snap menu.
"use strict";

const FORGE_PRO_R = 88;           // marking-menu ring radius, px (tight: owner 17:06 'too far apart')
const FORGE_PRO_DEAD = 22;        // px from the centre before a direction counts (the pro dead zone)
const FORGE_PRO_HOLD = 0;         // the right-button menu opens the moment the button goes down (kept for scripts)
const FORGE_PRO_TAP = 230;        // a Space press shorter than this, with nothing chosen, is a tap
const FORGE_KEYMAP_STORE = "loki-forge-keymap";
const FORGE_COMPASS = { N: -90, NE: -45, E: 0, SE: 45, S: 90, SW: 135, W: 180, NW: -135 };

function forgeKeymap() { return "pro"; }          // the pro keys only; the old Blender set is gone (owner, 2026-10-19)
function forgeSetKeymap() {
  try { localStorage.removeItem(FORGE_KEYMAP_STORE); } catch (_) { /* private mode */ }
  return "pro";
}
try { localStorage.removeItem(FORGE_KEYMAP_STORE); } catch (_) { /* an old "blender" choice is not kept */ }

function proEl(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
const proSay = (t, bad) => { if (t && typeof forgeSay === "function") forgeSay(t, bad); };

// ================================================================== the commands (menus, hotbox, hotkeys share them)
// each returns a short note for the status line, or "" / undefined for silence
function forgeProTree(v) { return v && v.tree && v.tree.api; }
function forgeProComp(v) { return !!(v && v.mode === "poly"); }

function forgeProTool(v, mode) {                 // q / w / e / r
  const t = forgeProTree(v);
  if (v.pro) v.pro.tool = mode;
  if (forgeProComp(v)) {                          // pro: pressing w again keeps the move tool (no toggle)
    if (v.setTool && !(v.tool && v.tool() === mode)) v.setTool(mode);
    return "";
  }
  if (!mode) { if (v.transform && v.transform.object) v.transform.detach(); if (v.gizmo && v.gizmo.object) v.gizmo.detach(); v.dirty = true; return "Select"; }
  if (t && t.attachTool) t.attachTool(mode); else v.toggleTransform(mode);
  for (const b of document.querySelectorAll("#forge .forge-transform")) b.classList.toggle("on", true);
  return "";
}

async function forgeProComponents(v, sel) {      // F9 / F10 / F11, or a component wedge on an object
  const t = forgeProTree(v);
  const n = t && t.active();
  if (n && !n.root && n.kind === "mesh") t.makeWorking(n.id);
  if (!forgeProComp(v) && typeof forgeModelMode === "function") await forgeModelMode(true);
  if (sel && v.setSelMode) v.setSelMode(sel);
  return "";
}
async function forgeProObjectMode(v) {
  if (forgeProComp(v) && typeof forgeModelMode === "function") await forgeModelMode(false);
  return "Object mode.";
}
async function forgeProF8(v) { return forgeProComp(v) ? forgeProObjectMode(v) : forgeProComponents(v, null); }

async function forgeProSculpt(v) {
  const t = forgeProTree(v), n = t && t.active();
  if (n && !n.root && n.kind === "mesh") t.makeWorking(n.id);
  if (forgeProComp(v)) await forgeProObjectMode(v);
  if (v.mode !== "sculpt" && typeof forgeMode === "function") forgeMode();
  return "";
}

// f / a, the pro way (owner 2026-10-21: "when you have a vert selected and you press f you should zoom to that vert, a
// is everything in the scene, f is whatever is selected ... works on edge as well"):
//   a  every object in the scene (components or not)
//   f  in component mode the selected vertices / edges / faces (one vertex frames it and its edges); otherwise the
//      selected objects; with nothing selected, everything
// Framing moves the camera only - the brush / soft-selection scale (view.size) stays the model's.
function forgeProFrame(v, all) {
  const t = forgeProTree(v);
  const keep = v.size;
  if (v.rememberView) v.rememberView();
  if (!all && forgeProComp(v) && v.poly && v.selectedVerts) {
    const ids = v.selectedVerts().filter((i) => v.poly.v[i]);
    if (ids.length) {
      const THREE = v.THREE, box = new THREE.Box3(), p = new THREE.Vector3();
      v.holder.updateMatrixWorld(true);
      for (const i of ids) box.expandByPoint(p.fromArray(v.poly.v[i]).applyMatrix4(v.holder.matrixWorld));
      // pad by the length of the edges around the selection, so one vertex (or a tiny edge) is not a dot on screen
      let edge = 0, n = 0;
      const sel = new Set(ids);
      for (const f of v.poly.f) for (let k = 0; k < f.length; k++) {
        const a = f[k], b = f[(k + 1) % f.length];
        if (!sel.has(a) && !sel.has(b)) continue;
        const pa = v.poly.v[a], pb = v.poly.v[b];
        edge += Math.hypot(pa[0] - pb[0], pa[1] - pb[1], pa[2] - pb[2]); n++;
      }
      const s = v.holder.matrixWorld.getMaxScaleOnAxis ? v.holder.matrixWorld.getMaxScaleOnAxis() : 1;
      const pad = (n ? edge / n : 0.1) * s * (ids.length === 1 ? 0.25 : 0.12);
      box.expandByScalar(pad);
      v.frameBox(box);
      v.size = keep;
      return ids.length === 1 ? "Framed the vertex." : "Framed " + ids.length + " vertices.";
    }
  }
  if (!t) { v.frame(); return ""; }
  const ids = all || !t.selected().length ? t.allIds() : t.selected();
  v.frameBox(t.worldBox(ids));
  v.size = keep || v.size;
  return all ? "Framed everything." : "";
}

function forgeProView(v, name) {
  if (v.quad) v.setLook("quad", false);
  if (v.rememberView) v.rememberView();
  v.setView(name);
  return { persp: "Perspective", top: "Top", front: "Front", side: "Side" }[name] + " view.";
}

function forgeProLook(v, what, on) {
  v.setLook(what, !!on);
  if (what === "wire" && typeof fmyWireOnly === "function") return fmyWireOnly(v, !!on && v.mode !== "sculpt");   // 4: edges only
  return what === "wire" ? (on ? "Wireframe (4)." : "Shaded (5).") : "";
}

function forgeProIsolate(v) {                     // Ctrl+1: show only the selection, again to come back
  const t = forgeProTree(v);
  if (!t) return "";
  const m = v.pro;
  if (m.isolated) { t.show(m.isolated); m.isolated = null; return "Isolate off."; }
  if (!t.selected().length) return "Select something to isolate.";
  t.hideUnselected(); m.isolated = v.tree.hiddenLast.slice();
  return "Isolate select (Ctrl+1 again to come back).";
}

function forgeProNudge(v, dx, dy) {               // Alt + arrows: a small step along the screen
  const t = forgeProTree(v);
  if (!t || forgeProComp(v) || !t.selected().length) return "";
  const THREE = v.THREE, cam = v.camera;
  const right = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 0).normalize();
  const up = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 1).normalize();
  const step = Math.max(v.size || 1, 0.1) * 0.01;
  const d = right.multiplyScalar(dx * step).add(up.multiplyScalar(dy * step));
  for (const id of t.selected()) {
    const n = t.node(id);
    if (!n || !n.grp.parent) continue;
    const p = n.grp.getWorldPosition(new THREE.Vector3()).add(d);
    n.grp.position.copy(n.grp.parent.worldToLocal(p));
    n.grp.updateMatrixWorld(true);
  }
  v.tree.build(); v.dirty = true;
  return "";
}

// pivot edit mode (hold d, or Insert to toggle): the manipulator moves the pivot, not the object
function forgeProPivotMode(v, on) {
  const t = forgeProTree(v), m = v.pro, tc = v.transform;
  if (!t || !tc || forgeProComp(v)) return "";
  if (on == null) on = !t.pivotMode;
  if (on === !!t.pivotMode) return "";
  const THREE = v.THREE;
  if (on) {
    const n = t.active();
    if (!n) return "";
    if (!m.pivotProxy) {
      m.pivotProxy = new THREE.Object3D(); m.pivotProxy.name = "forge-pivot-proxy";
      tc.addEventListener("objectChange", () => {
        if (!t.pivotMode || tc.object !== m.pivotProxy) return;
        const node = t.node(m.pivotFor);
        if (!node) return;
        const p = m.pivotProxy.getWorldPosition(new THREE.Vector3());
        t.setPivot(node.id, node.inner.worldToLocal(p));
      });
    }
    const scene = v.holder.parent ? (() => { let s = v.holder; while (s.parent) s = s.parent; return s; })() : null;
    if (scene) scene.add(m.pivotProxy);
    m.pivotProxy.position.copy(t.pivotWorld(n.id));
    m.pivotFor = n.id;
    m.toolBefore = tc.object ? tc.mode : null;
    tc.attach(m.pivotProxy); tc.setMode("translate");
    t.pivotMode = true;
    document.getElementById("forge-stage")?.classList.add("pivot-edit");
    v.dirty = true;
    return "Pivot edit: drag the handle to move " + n.name + "'s pivot (d / Insert to leave).";
  }
  t.pivotMode = false;
  document.getElementById("forge-stage")?.classList.remove("pivot-edit");
  const node = t.node(m.pivotFor);
  if (m.pivotProxy && m.pivotProxy.parent) m.pivotProxy.parent.remove(m.pivotProxy);
  if (node && m.toolBefore) { tc.attach(node.grp); tc.setMode(m.toolBefore); } else tc.detach();
  v.tree.build(); v.dirty = true;
  return "";
}

function forgeProSpace(v, space) {                // w / e + left button: World / Object
  const tc = v.transform;
  if (tc && tc.setSpace) tc.setSpace(space === "world" ? "world" : "local");
  if (v.gizmo && v.gizmo.setSpace) v.gizmo.setSpace(space === "world" ? "world" : "local");
  return space === "world" ? "Axes: World." : "Axes: Object.";
}

// ---- snapping, the pro way: hold x = grid, c = curve / edge, v = point / vertex (or switch them on in the Snap menu)
const FORGE_SNAP_KEY = { grid: "x", edge: "c", point: "v" };
function forgeProSnapOn(v, kind) {
  const m = v && v.pro;
  return !!(m && (m.snap[kind] || m.held.has(FORGE_SNAP_KEY[kind])));
}
function forgeProSnapAny(v) { return forgeProSnapOn(v, "grid") || forgeProSnapOn(v, "edge") || forgeProSnapOn(v, "point"); }
function forgeProGridStep(v) { return (v && v.pro && v.pro.gridStep) || 0.25; }

// the vertex (point) or the nearest spot on an edge (edge) under the mouse, on any mesh but the ones in `skip`
function forgeProSnapTarget(v, kind, skip) {
  const t = forgeProTree(v), m = v.pro;
  if (!t || !m || !m.mouse || !v.camera || !v.canvas) return null;
  const THREE = v.THREE, r = v.canvas.getBoundingClientRect();
  const skipped = (o) => { for (let x = o; x; x = x.parent) if (skip.includes(x)) return true; return false; };
  const meshes = t.pickables().filter((o) => !skipped(o));
  v.camera.updateMatrixWorld();
  const ndc = new THREE.Vector2(((m.mouse[0] - r.left) / r.width) * 2 - 1, -((m.mouse[1] - r.top) / r.height) * 2 + 1);
  const ray = new THREE.Raycaster(); ray.setFromCamera(ndc, v.camera);
  const hit = ray.intersectObjects(meshes, false)[0];
  if (hit && hit.face) {
    const pos = hit.object.geometry.attributes.position;
    const P = [hit.face.a, hit.face.b, hit.face.c].map((i) => hit.object.localToWorld(new THREE.Vector3().fromBufferAttribute(pos, i)));
    if (kind === "point") return P.reduce((a, b) => (a.distanceTo(hit.point) <= b.distanceTo(hit.point) ? a : b));
    // edge: the closest point on the hit triangle's edges - leaving out the diagonal a quad was split along
    // (its longest side, clearly longer than the others), which is not an edge you modelled
    const len = [0, 1, 2].map((k) => P[k].distanceTo(P[(k + 1) % 3]));
    const order = [0, 1, 2].sort((x, y) => len[y] - len[x]);
    const diag = len[order[0]] > len[order[1]] * 1.3 ? order[0] : -1;
    let best = null, bd = Infinity;
    for (let k = 0; k < 3; k++) {
      if (k === diag) continue;
      const seg = new THREE.Line3(P[k], P[(k + 1) % 3]), q = seg.closestPointToPoint(hit.point, true, new THREE.Vector3());
      const d = q.distanceTo(hit.point); if (d < bd) { bd = d; best = q; }
    }
    return best;
  }
  if (kind !== "point") return null;
  let best = null, bd = 40;                           // nothing under the mouse: the nearest vertex on screen (40 px)
  const worldPoint = new THREE.Vector3(), screenPoint = new THREE.Vector3();
  for (const o of meshes) {
    const pos = o.geometry.attributes.position, n = Math.min(pos.count, 200000);
    o.updateMatrixWorld();
    for (let i = 0; i < n; i++) {
      worldPoint.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld);
      screenPoint.copy(worldPoint).project(v.camera);
      if (screenPoint.z > 1) continue;
      const d = Math.hypot(r.left + (screenPoint.x + 1) / 2 * r.width - m.mouse[0], r.top + (1 - screenPoint.y) / 2 * r.height - m.mouse[1]);
      if (d < bd) { bd = d; best = worldPoint.clone(); }
    }
  }
  return best;
}

// a dragged world point -> where the active snaps put it; `axis` (the handle's "X", "XZ", "XYZ" ...) keeps the
// drag's constraint: only those coordinates are taken from the snap target (pro does the same)
function forgeProSnapPoint(v, p, skip, axis) {
  let target = null;
  if (forgeProSnapOn(v, "point")) target = forgeProSnapTarget(v, "point", skip);
  if (!target && forgeProSnapOn(v, "edge")) target = forgeProSnapTarget(v, "edge", skip);
  if (!target && forgeProSnapOn(v, "grid")) {
    const s = forgeProGridStep(v);
    target = p.clone(); target.set(Math.round(p.x / s) * s, Math.round(p.y / s) * s, Math.round(p.z / s) * s);
  }
  if (!target) return null;
  const out = p.clone(), ax = /[XYZ]/.test(axis || "") ? axis : "XYZ";
  for (const c of "XYZ") if (ax.includes(c)) out[c.toLowerCase()] = target[c.toLowerCase()];
  return out;
}

function forgeProSnapToggle(v, kind) {
  v.pro.snap[kind] = !v.pro.snap[kind];
  forgeProSnapHud(v);
  return { grid: "Snap to grid", edge: "Snap to edge (curve)", point: "Snap to point (vertex)" }[kind] + (v.pro.snap[kind] ? " on." : " off.");
}
function forgeProSnapHud(v) {                       // the three snap chips in the viewport's corner (the status line)
  const hud = document.getElementById("forge-snaps");
  if (!hud || !v || !v.pro) return;
  for (const b of hud.querySelectorAll("[data-snap]")) b.classList.toggle("on", forgeProSnapOn(v, b.dataset.snap));
}

function forgeProSnap(v, kind, on) {              // j: the pro step snap for the move / rotate / scale handles
  const tcs = [v.transform, v.gizmo].filter((x) => x && x.setTranslationSnap);
  const step = forgeProGridStep(v);
  for (const tc of tcs) if (kind === "step") { tc.setTranslationSnap(on ? step : null); tc.setRotationSnap(on ? Math.PI / 12 : null); tc.setScaleSnap(on ? 0.1 : null); }
  return "";
}

// ---- the workspace: which panels show (pro: Windows menu, Ctrl+Space hides them all), remembered per machine
const FORGE_PANELS_STORE = "loki-forge-panels";
const FORGE_PANEL_DEFAULTS = { outliner: true, channel: true, create: false, materials: false, shelf: false, toolkit: false };
function forgeProPanels() {
  let p = {};
  try { p = JSON.parse(localStorage.getItem(FORGE_PANELS_STORE) || "{}") || {}; } catch (_) { p = {}; }
  return Object.assign({}, FORGE_PANEL_DEFAULTS, p);
}
function forgeProPanelsApply(p) {
  p = p || forgeProPanels();
  const body = document.querySelector("#forge .forge-body"), panel = document.querySelector("#forge .forge-panel");
  if (!body) return p;
  body.classList.add("pro"); if (panel) panel.classList.add("pro");
  const show = (id, on) => { const e = document.getElementById(id); if (e) e.hidden = !on; };
  show("forge-outcol", p.outliner);
  show("forge-chancol", p.channel);
  show("forge-left", p.create);
  show("forge-materials", p.materials);
  body.classList.toggle("show-shelf", !!p.shelf);
  body.classList.toggle("show-toolkit", !!p.toolkit);
  body.classList.toggle("mats", !!p.materials);
  if (p.materials && window.ForgeMaterials) {
    const mats = document.getElementById("forge-materials");
    if (mats && !mats.dataset.ready) {
      mats.dataset.ready = "1";
      window.ForgeMaterials.open(mats, (maps) => forge.view && forge.view.setMaterial(maps)).catch((e) => proSay("Materials: " + e.message, true));
    }
  }
  const v = typeof forge !== "undefined" && forge.view;
  if (v && v.resize) v.resize();
  return p;
}
function forgeProPanel(name, on) {
  const p = forgeProPanels();
  p[name] = on == null ? !p[name] : !!on;
  try { localStorage.setItem(FORGE_PANELS_STORE, JSON.stringify(p)); } catch (_) { /* private mode */ }
  forgeProPanelsApply(p);
  const label = { outliner: "Outliner", channel: "Channel Box", create: "Create panel", materials: "Materials", shelf: "Shelf", toolkit: "Modeling Toolkit" }[name];
  return label + (p[name] ? " shown." : " hidden.");
}
function forgeProHideUI() {                       // Ctrl+Space: every panel away, again to bring them back
  if (window.forgePanels && window.forgePanels.hideAll) {      // the same as the UI button in Forge's title
    const hidden = window.forgePanels.anyHidden();
    if (hidden) window.forgePanels.showAll(); else window.forgePanels.hideAll();
    return hidden ? "Panels back." : "Only the viewport (Ctrl+Space or the UI button brings the panels back).";
  }
  const p = forgeProPanels();
  const any = Object.keys(FORGE_PANEL_DEFAULTS).some((k) => p[k]);
  let next;
  if (any) { next = Object.fromEntries(Object.keys(FORGE_PANEL_DEFAULTS).map((k) => [k, false])); next._before = p; }
  else next = Object.assign({}, FORGE_PANEL_DEFAULTS, p._before || {});
  delete (next._before || {})._before;
  try { localStorage.setItem(FORGE_PANELS_STORE, JSON.stringify(next)); } catch (_) { /* private mode */ }
  forgeProPanelsApply(next);
  return any ? "Only the viewport (Ctrl+Space brings the panels back)." : "Panels back.";
}

function forgeProManipSize(v, bigger) {
  for (const tc of [v.transform, v.gizmo]) if (tc && tc.setSize) tc.setSize(Math.max(0.2, Math.min(4, (tc.size || 1) * (bigger ? 1.25 : 0.8))));
  v.dirty = true;
  return "";
}

const forgeProHas = (name) => typeof window[name] === "function";
const forgeProCall = (name, ...a) => (forgeProHas(name) ? window[name](...a) : undefined);

// the command table: id -> [label, run(v)] ; `null` run = not in Forge yet (shown greyed, with why)
// Symmetry bitmask helpers (1 X, 2 Y, 4 Z) - the sculpt engine and the posing tools mirror across every active plane
function forgeProRadial(v, n, axis) {
  if (!v || !v.brush) return "";
  v.brush.radial = n | 0;
  if (axis != null) v.brush.radialAxis = axis | 0;
  return "Symmetry: " + (v.brush.radial > 1 ? "Radial " + v.brush.radial + " " + ["X", "Y", "Z"][v.brush.radialAxis | 0] : "Off") + ".";
}

function forgeProSym(v, bits) {
  if (!v || !v.brush) return "";
  v.brush.symBits = bits | 0;
  if (bits) v.brush.symLast = v.brush.symBits;
  v.brush.symmetry = !!v.brush.symBits;
  v.brush.symModel = !!v.brush.symBits;   // turning symmetry on enables the modelling mirror too (its own command turns it off)
  const names = ["X", "Y", "Z"].filter((_, i) => v.brush.symBits & (1 << i));
  return "Symmetry: " + (names.length ? "Object " + names.join("") : "Off") + ".";
}

function forgeProCommands() {
  const T = (v) => forgeProTree(v);
  const comp = forgeProComp;
  return {
    select: ["Select", (v) => forgeProTool(v, null)],
    move: ["Move", (v) => forgeProTool(v, "translate")],
    rotate: ["Rotate", (v) => forgeProTool(v, "rotate")],
    scale: ["Scale", (v) => forgeProTool(v, "scale")],
    lastTool: ["Last Tool", (v) => forgeProTool(v, v.pro.lastTool || "translate")],
    undo: ["Undo", (v) => { v.undo(); if (T(v)) v.tree.build(); }],
    // the sculpting engine (forge_sculpt.js)
    sculptRemesh: ["Remesh (Even Surface)", () => { window.ForgeSculpt && window.ForgeSculpt.op("voxelRemesh", +((document.getElementById("forge-sculpt-res") || {}).value || 128)); }],
    sculptQuadRemesh: ["Quad Remesh", () => { window.ForgeSculpt && window.ForgeSculpt.op("quadRemesh", 4000); }],
    sculptDivide: ["Divide (Subdivision Level)", () => { window.ForgeSculpt && window.ForgeSculpt.op("divide"); }],
    sculptDynamic: ["Toggle Dynamic Detail", () => { const b = document.getElementById("forge-sculpt-dyn"); if (b) b.click(); }],
    matcapNext: ["Next Matcap", () => { if (typeof forgeCycleMatcap === "function") forgeCycleMatcap(1); }],
    matcapPrev: ["Previous Matcap", () => { if (typeof forgeCycleMatcap === "function") forgeCycleMatcap(-1); }],
    redo: ["Redo", (v) => { v.redo(); if (T(v)) v.tree.build(); }],
    duplicate: ["Duplicate", (v) => { const n = T(v).duplicate(); return n ? "Duplicated: " + n.name + "." : ""; }],
    duplicateT: ["Duplicate with Transform", (v) => { const n = T(v).duplicateWithTransform(); return n ? n.name + " (Shift+D repeats the offset)." : ""; }],
    group: ["Group", (v) => { const g = T(v).groupSelected(); return g ? "Grouped: " + g.name + " (pivot at the centre)." : ""; }],
    ungroup: ["Ungroup", (v) => { for (const id of T(v).selected()) T(v).ungroup(id); return "Ungrouped."; }],
    parent: ["Parent", (v) => (T(v).parentSelected() ? "Parented under the last selected." : "Select the children, then the parent last (p).")],
    unparent: ["Unparent", (v) => (T(v).unparentSelected() ? "Unparented to the world." : "")],
    hideToggle: ["Toggle Visibility", (v) => { T(v).toggleVisible(); }],
    hide: ["Hide Selection", (v) => { const k = T(v).hide(); return k ? "Hidden (Ctrl+Shift+H shows the last hidden)." : ""; }],
    show: ["Show Selection", (v) => { T(v).show(); }],
    showLast: ["Show Last Hidden", (v) => { T(v).showLastHidden(); }],
    hideOthers: ["Hide Unselected", (v) => { T(v).hideUnselected(); }],
    showAll: ["Show All", (v) => { T(v).showAll(); }],
    isolate: ["Isolate Select", (v) => forgeProIsolate(v)],
    selectAll: ["Select All", (v) => { if (comp(v)) v.selectAll(true); else T(v).selectAll(); }],
    selectNone: ["Select None", (v) => { if (comp(v)) v.selectAll(false); else T(v).selectNone(); }],
    invert: ["Invert Selection", (v) => { if (comp(v)) v.selectInvert(); else T(v).invertSelection(); }],
    hierarchy: ["Select Hierarchy", (v) => { T(v).selectHierarchy(); }],
    grow: ["Grow Selection", (v) => { if (comp(v)) v.selectGrow(true); }],
    shrink: ["Shrink Selection", (v) => { if (comp(v)) v.selectGrow(false); }],
    delete: ["Delete", (v) => { if (comp(v)) forgeProCall("forgeFaceOp", "delete"); else { const k = T(v).removeSelected(); return k ? "Deleted." : "The object being edited stays - select another, or empty it."; } }],
    frameSel: ["Frame Selection", (v) => forgeProFrame(v, false)],
    frameAll: ["Frame All", (v) => forgeProFrame(v, true)],
    defaultView: ["Default View", (v) => { forgeProView(v, "persp"); forgeProFrame(v, true); return ""; }],
    persp: ["Perspective", (v) => forgeProView(v, "persp")],
    top: ["Top", (v) => forgeProView(v, "top")],
    front: ["Front", (v) => forgeProView(v, "front")],
    side: ["Side", (v) => forgeProView(v, "side")],
    single: ["Single View", (v) => { v.setLook("quad", false); return "One view."; }],
    four: ["Four View", (v) => { v.setLook("quad", true); return "Four views."; }],
    wire: ["Wireframe", (v) => forgeProLook(v, "wire", true)],
    shaded: ["Shaded", (v) => forgeProLook(v, "wire", false)],
    textured: ["Textured", (v) => { v.setLook("clay", !v.clay); return v.clay ? "Clay (6 again for colours)." : "Colours and textures."; }],
    lights: ["Next Light", (v) => "Light: " + v.nextLight()],
    centerPivot: ["Center Pivot", (v) => (T(v).centerPivot() ? "Pivot centred." : "")],
    resetPivot: ["Reset Pivot", (v) => (T(v).resetPivot() ? "Pivot back on the object's origin." : "")],
    pivotEdit: ["Edit Pivot", (v) => forgeProPivotMode(v, null)],
    freeze: ["Freeze Transformations", (v) => (T(v).freeze() ? "Frozen: reads 0 / 0 / 1, nothing moved." : "")],
    resetXf: ["Reset Transformations", (v) => (T(v).resetTransform() ? "Back to 0 / 0 / 1." : "")],
    channelBox: ["Channel Box", () => forgeProPanel("channel")],
    outliner: ["Outliner", () => forgeProPanel("outliner")],
    layerEditor: ["Layer Editor", () => { const b = document.getElementById("forge-layer-editor"); if (!b) return "The Layer Editor is not built here."; b.hidden = !b.hidden; if (!b.hidden && !forgeProPanels().channel) forgeProPanel("channel", true); return b.hidden ? "Layer Editor hidden." : "Layer Editor shown (under the Channel Box)."; }],
    layerAdd: ["Create Empty Layer", () => { const t = forge.view && forge.view.tree && forge.view.tree.api; if (!t) return "Open Forge first."; const l = t.layerAdd(); return "Layer " + l.name + " created."; }],
    layerAssign: ["Assign to Current Layer", () => { const t = forge.view && forge.view.tree && forge.view.tree.api; if (!t) return "Open Forge first."; t.layerAssign(t.curLayer, t.sel); return "Assigned the selection to the current layer."; }],
    symX: ["Symmetry X", (v) => forgeProSym(v, (v.brush.symBits || 0) ^ 1)],
    symY: ["Symmetry Y", (v) => forgeProSym(v, (v.brush.symBits || 0) ^ 2)],
    symZ: ["Symmetry Z", (v) => forgeProSym(v, (v.brush.symBits || 0) ^ 4)],
    symOff: ["Symmetry Off", (v) => forgeProSym(v, 0)],
    symModel: ["Modelling Symmetry", (v) => { if (!v || !v.brush) return ""; v.brush.symModel = !v.brush.symModel; return "Modelling symmetry " + (v.brush.symModel ? "on" : "off") + "."; }],
    symRadialOff: ["Radial Symmetry Off", (v) => forgeProRadial(v, 0)],
    symRadial3: ["Radial Symmetry 3", (v) => forgeProRadial(v, 3)],
    symRadial4: ["Radial Symmetry 4", (v) => forgeProRadial(v, 4)],
    symRadial6: ["Radial Symmetry 6", (v) => forgeProRadial(v, 6)],
    symRadial8: ["Radial Symmetry 8", (v) => forgeProRadial(v, 8)],
    symAxisX: ["Radial Axis X", (v) => forgeProRadial(v, (v.brush && v.brush.radial) || 0, 0)],
    symAxisY: ["Radial Axis Y", (v) => forgeProRadial(v, (v.brush && v.brush.radial) || 0, 1)],
    symAxisZ: ["Radial Axis Z", (v) => forgeProRadial(v, (v.brush && v.brush.radial) || 0, 2)],
    objComp: ["Object/Component", (v) => forgeProF8(v)],
    vertex: ["Vertex", (v) => forgeProComponents(v, "vert")],
    edge: ["Edge", (v) => forgeProComponents(v, "edge")],
    face: ["Face", (v) => forgeProComponents(v, "face")],
    objectMode: ["Object Mode", (v) => forgeProObjectMode(v)],
    uv: ["UV", null, "UV editing is not in Forge yet"],
    vertexFace: ["Vertex Face", null, "Vertex faces are not in Forge yet"],
    uvShell: ["UV Shell", null, "UV shells are not in Forge yet"],
    multi: ["Multi", null, "Multi-component selection is not in Forge yet"],
    extrude: ["Extrude", async (v) => { if (!comp(v)) await forgeProComponents(v, "face"); forgeProCall("forgeFaceOp", "extrude"); }],
    inset: ["Inset", (v) => forgeProCall("forgeFaceOp", "inset")],
    reverse: ["Reverse Normals", (v) => forgeProCall("forgeFaceOp", "flip")],
    smooth: ["Smooth", (v) => forgeProCall("forgeFaceOp", "smooth")],
    dynamesh: ["DynaMesh", () => forgeProCall("forgeDynamesh")],
    sculpt: ["Sculpt Tool", (v) => forgeProSculpt(v)],
    deleteComp: ["Delete Components", () => forgeProCall("forgeFaceOp", "delete")],
    bevel: ["Bevel", null, "Bevel is not in Forge yet"],
    edgeLoop: ["Insert Edge Loop", () => forgeProCall("forgeLoopCut")],
    multiCut: ["Multi-Cut", null, "Multi-Cut is not in Forge yet (T8)"],
    merge: ["Merge", () => forgeProCall("forgeMeshOp", "merge")],
    mergeCenter: ["Merge to Center", () => forgeProCall("forgeMeshOp", "mergeCenter")],
    fillHole: ["Fill Hole", () => forgeProCall("forgeMeshOp", "fillHole")],
    softHard: ["Soften/Harden", null, "Soft/hard edges are not in Forge yet"],
    chamfer: ["Chamfer Vertex", null, "Chamfer is not in Forge yet (T8)"],
    poke: ["Poke Face", null, "Poke is not in Forge yet (T8)"],
    wedge: ["Wedge", null, "Wedge is not in Forge yet"],
    toUV: ["To UVs", null, "UVs are not in Forge yet"],
    loopSel: ["To Edge Loop", (v) => { if (!comp(v) || !v.convertEdges) return "Select edges first (F10)."; const n = v.convertEdges("loop"); return n ? n + " edges in the loop(s)." : "Select an edge first."; }],
    ringSel: ["To Edge Ring", (v) => { if (!comp(v) || !v.convertEdges) return "Select edges first (F10)."; const n = v.convertEdges("ring"); return n ? n + " edges in the ring(s)." : "Select an edge first."; }],
    cube: ["Cube", () => forgeProCall("forgeAddPrimitive", "cube")],
    sphere: ["Sphere", () => forgeProCall("forgeAddPrimitive", "sphere")],
    cylinder: ["Cylinder", () => forgeProCall("forgeAddPrimitive", "cylinder")],
    cone: ["Cone", () => forgeProCall("forgeAddPrimitive", "cone")],
    plane: ["Plane", () => forgeProCall("forgeAddPrimitive", "plane")],
    torus: ["Torus", () => forgeProCall("forgeAddPrimitive", "torus")],
    quadsphere: ["Quad Sphere", () => forgeProCall("forgeAddPrimitive", "quadsphere")],
    draw: ["Draw it", () => { forgeProPanel("create", true); forgeProCall("forgeWay", "draw"); }],
    image: ["From an image", () => { forgeProPanel("create", true); forgeProCall("forgeWay", "image"); }],
    describe: ["Describe it", () => { forgeProPanel("create", true); forgeProCall("forgeWay", "describe"); }],
    creature: ["Creature", () => { forgeProPanel("create", true); forgeProCall("forgeWay", "creature"); }],
    winCreature: ["Creature Editor", () => { if (typeof forgeCreatureDock === "function") { forgeCreatureDock("open"); return "Creature Editor open (its bar: fold, float, close)."; } forgeProPanel("create", true); forgeProCall("forgeWay", "creature"); return ""; }],
    save: ["Save .glb", () => { document.querySelector('#forge-exportbar [data-icon="save"]')?.click(); }],
    export: ["Export\u2026", () => { if (typeof forgeExportDialog !== "function") return "Open Forge first."; forgeExportDialog(); return "Pick a format (glTF / OBJ / STL / PLY), a unit scale and a name."; }],
    close: ["Close Forge", () => forgeProCall("forgeClose")],
    panelModel: ["Create panel", () => forgeProPanel("create")],
    panelMaterials: ["Materials", () => forgeProPanel("materials")],
    worldAxes: ["World", (v) => forgeProSpace(v, "world")],
    objectAxes: ["Object", (v) => forgeProSpace(v, "local")],
    marquee: ["Marquee", () => "Drag a box to select (Shift toggles, Ctrl/Cmd removes)."],
    snapGrid: ["Snap to Grid", (v) => forgeProSnapToggle(v, "grid")],
    snapEdge: ["Snap to Edge (Curve)", (v) => forgeProSnapToggle(v, "edge")],
    snapPoint: ["Snap to Point (Vertex)", (v) => forgeProSnapToggle(v, "point")],
    grid: ["Grid", (v) => { const g = v.pro && v.pro.grid; if (!g) return ""; g.visible = !g.visible; v.dirty = true; return g.visible ? "Grid on." : "Grid off."; }],
    xray: ["X-Ray", async (v) => { if (!comp(v)) await forgeProComponents(v, null); v.setXray(); }],
    softSel: ["Soft Selection", (v) => { if (!comp(v)) return "Soft selection works on components (F9 / F10 / F11)."; v.setProportional(!v.edit.prop); return v.edit.prop ? "Soft selection on (b)." : "Soft selection off."; }],
    winOutliner: ["Outliner", () => forgeProPanel("outliner")],
    winChannel: ["Channel Box", () => forgeProPanel("channel")],
    winCreate: ["Generate panel", () => forgeProPanel("create")],
    winMaterials: ["Materials", () => forgeProPanel("materials")],
    winShelf: ["Shelf", () => forgeProPanel("shelf")],
    winToolkit: ["Modeling Toolkit", () => forgeProPanel("toolkit")],
    hideUI: ["Hide UI (Ctrl+Space)", () => forgeProHideUI()],
    saveObj: ["Save .obj", () => forgeProCall("forgeSave", "obj")],
    more: ["More...", (v) => { forgeProHotboxOpen(v); }],
    combine: ["Combine", (v) => { const t = T(v); if (!t || !t.combine) return ""; const n = t.combine(); return n ? "Combined into " + n.name + "." : "Select two or more meshes to combine."; }],
    separate: ["Separate", (v) => { const t = T(v); if (!t || !t.separate) return ""; const l = t.separate(); return l && l.length ? "Separated into " + l.length + " objects." : "Nothing to separate - the mesh is one piece."; }],
    mirror: ["Mirror", async (v) => { const t = T(v), n = t && t.active(); if (n && !n.root && n.kind === "mesh") t.makeWorking(n.id); return forgeProCall("forgeMirror", "x"); }],
    mirrorY: ["Mirror Y", async (v) => { const t = T(v), n = t && t.active(); if (n && !n.root && n.kind === "mesh") t.makeWorking(n.id); return forgeProCall("forgeMirror", "y"); }],
    mirrorZ: ["Mirror Z", async (v) => { const t = T(v), n = t && t.active(); if (n && !n.root && n.kind === "mesh") t.makeWorking(n.id); return forgeProCall("forgeMirror", "z"); }],
    smooth1: ["Cage (1)", () => (typeof fmySmoothPreview === "function" ? fmySmoothPreview(1) : "")],
    smooth2: ["Cage + Smooth (2)", () => (typeof fmySmoothPreview === "function" ? fmySmoothPreview(2) : "")],
    smooth3: ["Smooth Preview (3)", () => (typeof fmySmoothPreview === "function" ? fmySmoothPreview(3) : "")],
    wheel: ["Radial Menus", (v) => { forgeProWheelOpen(v, v.pro && v.pro.mouse); }],
    completeTool: ["Complete Tool", (v) => { forgeProTool(v, null); return "Tool completed."; }],
    repeatLast: ["Repeat Last", (v) => { const id = v.pro && v.pro.last; if (!id || id === "repeatLast") return "Nothing to repeat yet."; forgeProRun(v, id); }],
    sculptModel: ["Sculpt/Model", () => forgeProCall("forgeMode")],
    quadToggle: ["Quad view", (v) => { v.setLook("quad", !v.quad); return v.quad ? "Four views." : "One view."; }],
    makeLive: ["Edit this mesh", (v) => { const t = T(v), n = t.active(); return n && t.makeWorking(n.id) ? n.name + " is the one the tools edit now." : ""; }],
  };
}
const FORGE_PRO_CMDS = forgeProCommands();

async function forgeProRun(v, id) {
  const c = FORGE_PRO_CMDS[id];
  if (!c || !v) return;
  if (!c[1]) { proSay(c[0] + ": " + (c[2] || "not in Forge yet") + ".", true); return; }
  let note = "";
  const rec = !/^(undo|redo)$/.test(id) && v.undoOpen;      // every command is one undo step (forge_scene.js)
  if (rec) v.undoOpen(c[0]);
  try { note = await c[1](v); } catch (exc) { proSay(c[0] + " could not run: " + exc.message, true); return; }
  finally { if (rec && v.undoClose) v.undoClose(); }
  if (v.pro && !/^(undo|redo|select|lastTool|repeatLast|completeTool|more)$/.test(id)) v.pro.last = id;     // g repeats this
  if (v.pro && !/^__/.test(id)) { v.pro.recent = [id].concat((v.pro.recent || []).filter((x) => x !== id)).slice(0, 10); }
  if (v.pro && /^(move|rotate|scale)$/.test(id)) v.pro.lastTool = { move: "translate", rotate: "rotate", scale: "scale" }[id];
  if (v.tree) v.tree.build();
  proSay(note || "");
}

// ================================================================== marking menus (the pro compass layout)
// a menu: { title, ring: { N: id, NE: id, ... }, list: [id, ...] }
function forgeProMenu(v, ctx) {
  const comp = forgeProComp(v), mode = v.edit ? v.edit.mode : "face";
  if (ctx.key === "q") return { title: "Select", ring: { NW: "marquee", SE: "selectNone", E: "selectAll", W: "invert" }, list: [] };
  if (ctx.key === "w" || ctx.key === "e") return { title: ctx.key === "w" ? "Move" : "Rotate", ring: { W: "worldAxes", NW: "objectAxes", N: "pivotEdit", S: "resetPivot" }, list: [] };
  if (ctx.ctrl) {                                   // convert the selection (polyConvertMM)
    return { title: "Convert", ring: { W: "vertex", N: "edge", S: "face", E: "toUV", NE: "grow", NW: "shrink", SE: "loopSel", SW: "ringSel" }, list: [] };
  }
  if (ctx.shift) {
    if (comp && mode === "vert") return { title: "Vertex tools", ring: { S: "extrude", E: "chamfer", SW: "deleteEdgeVert", N: "merge", NE: "averageVerts", W: "multiCut", NW: "connect", SE: "targetWeld" }, list: ["mergeCenter", "detach", "relax", "circularize", "grow", "shrink"] };
    if (comp && mode === "edge") return { title: "Edge tools", ring: { S: "extrude", E: "bevel", SW: "deleteEdgeVert", N: "bridge", NE: "edgeLoop", W: "multiCut", NW: "connect", SE: "offsetEdgeLoop" }, list: ["merge", "collapse", "slideEdge", "spinEdge", "detach", "fillHole", "loopSel", "ringSel", "grow", "shrink"] };
    if (comp) return { title: "Face tools", ring: { S: "extrude", E: "bevel", SW: "wedge", NE: "poke", SE: "reverse", W: "multiCut", NW: "inset", N: "duplicateFace" }, list: ["extractFace", "collapse", "triangulate", "quadrangulate", "circularize", "deleteComp", "smooth", "grow", "shrink"] };
    if (ctx.node) return { title: "Mesh tools", ring: { S: "extrude", SW: "edgeLoop", NE: "fillHole", N: "merge", W: "multiCut", NW: "sculpt", E: "softHard" }, list: ["smooth", "dynamesh", "makeLive"] };
    return { title: "Create", ring: { NE: "quadsphere", E: "sphere", SE: "torus", S: "cube", SW: "cone", W: "cylinder", NW: "plane" }, list: ["draw", "image", "describe", "creature"] };
  }
  if (ctx.node || comp) {                           // dagMenuProc: N Edge, W Vertex, S UV, E Face, SW VF, SE Shell, NW Multi, NE Object
    return { title: ctx.node ? ctx.node.name : "Components",
      ring: { N: "edge", W: "vertex", S: "uv", E: "face", SW: "vertexFace", SE: "uvShell", NW: "multi", NE: "objectMode" },
      list: ["select", "move", "rotate", "scale", "frameSel", "hierarchy", "invert", "duplicate", "group", "centerPivot", "resetPivot",
        "resetXf", "freeze", "makeLive", "delete", "more"] };
  }
  // on empty space: the short list of the standard empty-space menu - no camera ring (that lives in the hotbox's
  // centre zone, Space + left button)
  return { title: "", ring: {},
    list: ["completeTool", "selectAll", "selectNone", "undo", "redo", "repeatLast", "frameAll", "more"] };
}

function forgeProMarkHost() {
  let host = document.getElementById("forge-pro-marking");
  if (host) return host;
  host = proEl("div", "forge-pro-marking");
  host.id = "forge-pro-marking"; host.hidden = true;
  host.setAttribute("role", "menu");
  document.body.append(host);
  return host;
}

function forgeProMarkShow(v, x, y, menu) {
  const host = forgeProMarkHost();
  host.textContent = "";
  host.append(proEl("span", "forge-pro-hub" + (menu.title ? "" : " dot"), menu.title || ""));
  for (const [pos, id] of Object.entries(menu.ring)) {
    const c = FORGE_PRO_CMDS[id]; if (!c) continue;
    const a = FORGE_COMPASS[pos] * Math.PI / 180;
    const b = proEl("button", "forge-pro-wedge pos-" + pos.toLowerCase() + (c[1] ? "" : " off"), c[0]);
    b.type = "button"; b.dataset.proCmd = c[0]; b.dataset.proId = id; b.dataset.pos = pos;
    if (!c[1]) b.title = c[2] || "Not in Forge yet";
    b.style.left = Math.round(Math.cos(a) * FORGE_PRO_R) + "px";
    b.style.top = Math.round(Math.sin(a) * FORGE_PRO_R * 0.82) + "px";
    b.addEventListener("click", (ev) => { ev.stopPropagation(); forgeProMarkHide(); forgeProRun(v, id); });
    host.append(b);
  }
  if (menu.list && menu.list.length) {
    const list = proEl("div", "forge-pro-mlist");
    const ringed = Object.keys(menu.ring || {}).length > 0;
    list.classList.toggle("bare", !ringed);           // no ring (empty space): the list starts right at the pointer
    list.style.top = (ringed ? Math.round(FORGE_PRO_R * 0.82 + 22) : 6) + "px";
    for (const id of menu.list) {
      const c = FORGE_PRO_CMDS[id]; if (!c) continue;
      const b = proEl("button", "forge-pro-litem" + (c[1] ? "" : " off"), c[0]);
      b.type = "button"; b.dataset.proCmd = c[0]; b.dataset.proId = id;
      b.addEventListener("click", (ev) => { ev.stopPropagation(); forgeProMarkHide(); forgeProRun(v, id); });
      list.append(b);
    }
    host.append(list);
  }
  host.style.left = Math.round(x) + "px";
  host.style.top = Math.round(y) + "px";
  host.dataset.set = menu.title || "";
  host.hidden = false;
  // keep the list on screen: near the bottom it opens upward, near the right edge it shifts left
  const ml = host.querySelector(".forge-pro-mlist");
  if (ml) {
    const r = ml.getBoundingClientRect();
    if (r.bottom > window.innerHeight - 4) ml.style.top = (parseFloat(ml.style.top) - (r.bottom - window.innerHeight + 4)) + "px";
    if (r.right > window.innerWidth - 4) ml.style.left = (-(r.right - window.innerWidth + 4)) + "px";
  }
  host._at = [x, y]; host._menu = menu;
}

function forgeProMarkHide() {
  const host = document.getElementById("forge-pro-marking");
  if (host) { host.hidden = true; host.textContent = ""; host._menu = null; }
}

// which wedge does a release at (x, y) mean? pro picks by DIRECTION once past the dead zone
function forgeProMarkPick(x, y) {
  const host = document.getElementById("forge-pro-marking");
  if (!host || host.hidden || !host._at) return null;
  const hit = document.elementFromPoint(x, y);
  if (hit && hit.dataset && hit.dataset.proId && host.contains(hit)) return hit.dataset.proId;
  const dx = x - host._at[0], dy = y - host._at[1];
  if (Math.hypot(dx, dy) < FORGE_PRO_DEAD) return null;
  const ang = Math.atan2(dy, dx) * 180 / Math.PI;
  let best = null, bestD = 999;
  for (const pos of Object.keys(host._menu.ring)) {
    let d = Math.abs(((ang - FORGE_COMPASS[pos]) + 540) % 360 - 180);
    if (d < bestD) { bestD = d; best = host._menu.ring[pos]; }
  }
  return bestD <= 30 ? best : null;
}
function forgeProMarkHover(x, y) {
  const host = document.getElementById("forge-pro-marking");
  if (!host || host.hidden) return;
  const id = forgeProMarkPick(x, y);
  for (const b of host.querySelectorAll("[data-pro-id]")) b.classList.toggle("hot", b.dataset.proId === id);
}

// ================================================================== the hotbox (hold Space) - the pro layout
// the pro hotbox: rows of menu names centred on the mouse (the common menus above the middle, the modelling menu
// set below it), each opening its own list; "Recent Commands" first; the centre and the four zones around it
// open marking menus (press, flick, release). Every command in Forge is in here - the panels are optional.
const FORGE_PRO_ROWS = [
  ["Recent Commands", []],                      // filled from what you ran last
  ["File", ["save", "saveObj", "export", "close"]],
  ["Edit", ["undo", "redo", "duplicate", "duplicateT", "group", "ungroup", "parent", "unparent", "delete", "deleteHistory"]],
  ["Create", ["cube", "sphere", "cylinder", "cone", "plane", "torus", "quadsphere", "draw", "image", "describe", "creature"]],
  ["Select", ["selectAll", "selectNone", "invert", "hierarchy", "grow", "shrink", "objComp", "vertex", "edge", "face"]],
  ["Modify", ["select", "move", "rotate", "scale", "centerPivot", "resetPivot", "pivotEdit", "freeze", "resetXf", "frameSel", "makeLive"]],
  ["Display", ["wire", "shaded", "textured", "xray", "grid", "lights", "smooth1", "smooth2", "smooth3", "quadToggle", "hide", "showLast", "hideOthers", "showAll", "isolate", "frameAll", "layerEditor", "layerAdd", "layerAssign"]],
  ["Windows", ["winOutliner", "winChannel", "winCreate", "winMaterials", "winShelf", "winToolkit", "wheel", "hideUI", "winCreature", "hotkeyEditor"]],
  // the modelling menu set (the pro second row)
  ["Mesh", ["combine", "separate", "mirror", "mirrorY", "mirrorZ", "extractFace", "smooth", "triangulate", "quadrangulate", "fillHole", "cleanup", "meshStats", "dynamesh", "sculptModel"]],
  ["Edit Mesh", ["extrude", "bridge", "bevel", "inset", "chamfer", "circularize", "collapse", "connect", "detach", "merge", "mergeCenter",
    "poke", "wedge", "averageVerts", "relax", "spinEdge", "spinEdgeBack", "duplicateFace", "reverse", "deleteComp", "deleteEdgeVert"]],
  ["Mesh Tools", ["edgeLoop", "insertLoopTool", "offsetEdgeLoop", "multiCut", "targetWeld", "slideEdge", "softSel", "sculpt", "winToolkit"]],
  ["Snap", ["snapGrid", "snapEdge", "snapPoint"]],
  ["Symmetry", ["symX", "symY", "symZ", "symOff", "symModel", "symRadialOff", "symRadial4", "symRadial6", "symRadial8"]],
];
const FORGE_PRO_ROW_SPLIT = 8;                  // the first 8 menus sit above the middle, the rest below it
// the five zones (HotboxCenter/North/South/East/WestMenu.mel)
const FORGE_PRO_ZONES = {
  center: { title: "Views", ring: { N: "persp", W: "top", S: "front", E: "side" } },
  north: { title: "Layouts", ring: { N: "single", E: "four", S: "winOutliner", W: "hideUI" } },
  south: { title: "Panels", ring: { N: "winOutliner", E: "winMaterials", W: "winCreate", S: "winChannel" } },
  east: { title: "UI", ring: { N: "winOutliner", E: "winChannel", S: "winShelf", W: "winToolkit" } },
  west: { title: "Selection mode", ring: { NW: "objComp", NE: "hierarchy", SW: "face", N: "vertex", W: "edge" } },
};
// commands that are switches: the hotbox shows a tick when they are on
const FORGE_PRO_TOGGLES = {
  snapGrid: (v) => !!v.pro.snap.grid, snapEdge: (v) => !!v.pro.snap.edge, snapPoint: (v) => !!v.pro.snap.point,
  grid: (v) => !!(v.pro.grid && v.pro.grid.visible), xray: (v) => !!(v.edit && v.edit.xray),
  softSel: (v) => !!(v.edit && v.edit.prop), wire: (v) => !!v.wire, textured: (v) => !v.clay, quadToggle: (v) => !!v.quad,
  winOutliner: () => forgeProPanels().outliner, winChannel: () => forgeProPanels().channel, winCreate: () => forgeProPanels().create,
  winMaterials: () => forgeProPanels().materials, winShelf: () => forgeProPanels().shelf, winToolkit: () => forgeProPanels().toolkit,
};

function forgeProItem(id, host) {
  const c = FORGE_PRO_CMDS[id];
  if (!c) return null;
  const b = proEl("button", "forge-pro-item" + (c[1] ? "" : " off"));
  b.type = "button"; b.dataset.proCmd = c[0]; b.dataset.proId = id;
  const key = typeof fmyKeyOf === "function" ? fmyKeyOf(id) : (typeof FMY_KEYS !== "undefined" && FMY_KEYS[id]) || "";
  b.append(proEl("span", "forge-pro-tick", ""), proEl("span", "forge-pro-label", c[0]), proEl("span", "forge-pro-key", key));
  if (!c[1]) b.title = c[2] || "";
  b.addEventListener("pointerdown", (ev) => ev.stopPropagation());
  b.addEventListener("click", (ev) => { ev.stopPropagation(); const v = forge.view; host._used = true; forgeProHotboxHide(); if (v) forgeProRun(v, id); });
  return b;
}

function forgeProHotboxHost() {
  let host = document.getElementById("forge-pro-hotbox");
  if (host) return host;
  const sheet = document.getElementById("forge");
  if (!sheet) return null;
  host = proEl("div", "forge-pro-hotbox");
  host.id = "forge-pro-hotbox"; host.hidden = true;
  host.setAttribute("role", "menu");
  const rows = [proEl("div", "forge-pro-row up"), proEl("div", "forge-pro-row down")];
  FORGE_PRO_ROWS.forEach(([head, ids], i) => {
    const col = proEl("section", "forge-pro-col");
    col.dataset.menu = head;
    const h = proEl("button", "forge-pro-head", head);
    h.type = "button";
    const list = proEl("div", "forge-pro-list");
    list.hidden = true;
    for (const id of ids) { const b = forgeProItem(id, host); if (b) list.append(b); }
    // calm menus (owner 2026-10-21: holding Space the menus "glitch ... jittering"): a menu opens when the mouse
    // RESTS on its name (a short hover intent) or at once on a press - sweeping across the row no longer flips every
    // menu open and shut - and nothing is rewritten when it is already that way.
    const open = () => {
      clearTimeout(host._intent);
      for (const l of host.querySelectorAll(".forge-pro-list")) { const hide = l !== list; if (l.hidden !== hide) l.hidden = hide; }
      for (const x of host.querySelectorAll(".forge-pro-head")) { const on = x === h; if (x.classList.contains("open") !== on) x.classList.toggle("open", on); }
    };
    h.addEventListener("pointerenter", () => {
      clearTimeout(host._intent);
      if (!list.hidden) return;
      host._intent = setTimeout(open, host.querySelector(".forge-pro-list:not([hidden])") ? 160 : 90);
    });
    h.addEventListener("pointerleave", () => clearTimeout(host._intent));
    h.addEventListener("pointerdown", (ev) => { ev.stopPropagation(); open(); });
    // press on a menu name, drag to an item, let go: that item runs (the pro hotbox's press-drag-release)
    list.addEventListener("pointerup", (ev) => {
      const it = ev.target.closest && ev.target.closest(".forge-pro-item");
      if (it && ev.button === 0 && host._dragFrom === h) { host._dragFrom = null; it.click(); }
    });
    h.addEventListener("pointerdown", () => { host._dragFrom = h; });
    col.append(h, list);
    rows[i < FORGE_PRO_ROW_SPLIT ? 0 : 1].append(col);
  });
  const hub = proEl("div", "forge-pro-zonehub", "Forge");
  hub.title = "Press in the middle for the views (Perspective / Top / Front / Side); above, below, left and right are the other zones.";
  const labels = proEl("div", "forge-pro-zones");
  for (const [z, t] of [["north", "Layouts"], ["south", "Panels"], ["east", "UI"], ["west", "Selection"]]) labels.append(proEl("span", "z-" + z, t));
  const box = proEl("div", "forge-pro-hbbox");
  box.append(rows[0], hub, rows[1], labels);
  host.append(box);
  // a press in a zone (not on a menu) opens its marking menu; releasing picks by direction
  host.addEventListener("pointerdown", (ev) => {
    if (ev.target.closest(".forge-pro-col")) return;
    if (host.dataset.pinned) { ev.preventDefault(); forgeProHotboxHide(); return; }   // Space is up: a click away closes
    if (ev.button !== 0) return;
    ev.preventDefault();
    const c = host._center || [window.innerWidth / 2, window.innerHeight / 2];
    const dx = ev.clientX - c[0], dy = ev.clientY - c[1];
    const zone = Math.abs(dx) < 70 && Math.abs(dy) < 34 ? "center" : Math.abs(dy) > Math.abs(dx) ? (dy < 0 ? "north" : "south") : (dx < 0 ? "west" : "east");
    host._used = true;
    host._zone = zone;
    for (const l of host.querySelectorAll(".forge-pro-list")) l.hidden = true;
    forgeProMarkShow(forge.view, ev.clientX, ev.clientY, FORGE_PRO_ZONES[zone]);
  });
  // once Space is up and a menu stays dropped down, a press anywhere but on the menus closes the hotbox
  document.addEventListener("pointerdown", (ev) => {
    if (host.hidden || !host.dataset.pinned || (ev.target.closest && ev.target.closest("#forge-pro-hotbox .forge-pro-col"))) return;
    ev.preventDefault(); ev.stopPropagation(); forgeProHotboxHide();
  }, true);
  window.addEventListener("pointermove", (ev) => { if (host._zone) forgeProMarkHover(ev.clientX, ev.clientY); });
  window.addEventListener("pointerup", (ev) => {
    if (!host._zone) return;
    host._zone = null;
    const id = forgeProMarkPick(ev.clientX, ev.clientY);
    forgeProMarkHide(); forgeProHotboxHide();
    if (id) forgeProRun(forge.view, id);
  });
  document.body.append(host);                     // not inside the sheet: its transform would shift fixed positions
  return host;
}

function forgeProHotboxRefresh(v, host) {        // ticks on the switches, and the Recent Commands list
  for (const b of host.querySelectorAll(".forge-pro-item")) {
    const st = FORGE_PRO_TOGGLES[b.dataset.proId];
    let on = false;
    try { on = !!(st && v && st(v)); } catch (_) { on = false; }
    b.classList.toggle("on", on);
    b.firstChild.textContent = on ? "\u2713" : "";
  }
  const recent = host.querySelector('.forge-pro-col[data-menu="Recent Commands"] .forge-pro-list');
  if (recent) {
    recent.textContent = "";
    const ids = (v && v.pro && v.pro.recent) || [];
    if (!ids.length) recent.append(proEl("div", "forge-pro-empty", "Nothing yet"));
    for (const id of ids) { const b = forgeProItem(id, host); if (b) recent.append(b); }
  }
}

// ================================================================== the Space wheel (floats at the mouse) - Ziva, 644e291
// Owner, 2026-10-19 (to Ziva): "i want the space bar menue to float where my mouse is just like pro not a newhud its
// like a wheel and when you hover over it brings down a new menue". So Space opens a wheel AT THE POINTER, and
// hovering a wedge brings that menu down beside it. The wedges are the hotbox's own menus (FORGE_PRO_ROWS, Recent
// Commands first) and the commands come from FORGE_PRO_CMDS, so the two can never drift apart; every list ends
// with "All menus", which opens the full hotbox (the pro five zones) - nothing was taken away.
const FORGE_PRO_WHEEL_R = 165;          // an ellipse (165 x 122 px): twelve wedges that never overlap

function forgeProWheelHost() {
  let host = document.getElementById("forge-pro-wheel");
  if (host) return host;
  const stage = document.getElementById("forge-stage");
  if (!stage) return null;
  host = proEl("div", "forge-pro-wheel");
  host.id = "forge-pro-wheel"; host.hidden = true;
  host.setAttribute("role", "menu");
  stage.append(host);
  return host;
}

function forgeProWheelSub(v, head, ids, angle) {
  const host = document.getElementById("forge-pro-wheel");
  if (!host) return;
  const old = host.querySelector(".forge-wheel-sub");
  if (old) old.remove();
  for (const w of host.querySelectorAll(".forge-wheel-wedge")) w.classList.toggle("open", w.dataset.proHead === head);
  const sub = proEl("div", "forge-wheel-sub");
  sub.dataset.head = head;
  sub.append(proEl("span", "forge-wheel-subtitle", head));
  if (head === "Recent Commands") ids = (v && v.pro && v.pro.recent) || [];
  if (!ids.length) sub.append(proEl("span", "forge-wheel-subtitle", "Nothing yet"));
  for (const id of ids) {
    const c = FORGE_PRO_CMDS[id];
    if (!c) continue;
    const b = proEl("button", "forge-wheel-item" + (c[1] ? "" : " off"));
    b.type = "button"; b.dataset.proId = id;
    let on = false;
    try { on = !!(FORGE_PRO_TOGGLES[id] && FORGE_PRO_TOGGLES[id](v)); } catch (_) { on = false; }
    b.append(proEl("span", "forge-pro-tick", on ? "\u2713" : ""), proEl("span", "", c[0]));
    b.classList.toggle("on", on);
    if (!c[1]) b.title = c[2] || "";
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (!c[1]) { proSay(c[0] + ": " + (c[2] || "not in Forge yet") + ".", true); return; }
      const view = forge.view;
      host._used = true;
      forgeProWheelClose();
      if (view) forgeProRun(view, id);
    });
    sub.append(b);
  }
  const b2 = proEl("button", "forge-wheel-item forge-wheel-more", "All menus (the full menu grid)");
  b2.type = "button";
  b2.addEventListener("click", (ev) => { ev.stopPropagation(); host._used = true; forgeProWheelClose(); forgeProHotboxOpen(v, host._at); });
  sub.append(b2);
  // the menu opens OUTWARD from its wedge, its nearest edge just past it, so it never covers the ring
  const cx = Math.cos(angle), cy = Math.sin(angle);
  const ex = Math.cos(angle) * (FORGE_PRO_WHEEL_R + 48), ey = Math.sin(angle) * (FORGE_PRO_WHEEL_R * 0.74 + 22);
  sub.style.left = Math.round(ex) + "px";
  sub.style.top = Math.round(ey) + "px";
  sub.style.transform = Math.abs(cx) >= Math.abs(cy)
    ? (cx > 0 ? "translate(0, -50%)" : "translate(-100%, -50%)")
    : (cy > 0 ? "translate(-50%, 0)" : "translate(-50%, -100%)");
  host.append(sub);
  host.dataset.open = head;
}

function forgeProWheelOpen(v, at) {
  const host = forgeProWheelHost();
  if (!host) return;
  host.textContent = "";
  host._used = false;
  const menus = FORGE_PRO_ROWS;
  const n = menus.length;
  host.append(proEl("span", "forge-wheel-hub", "Space"));
  menus.forEach(([head, ids], i) => {
    const a = (-Math.PI / 2) + (i * 2 * Math.PI) / n;
    const b = proEl("button", "forge-wheel-wedge", head === "Recent Commands" ? "Recent" : head);
    b.type = "button"; b.dataset.proHead = head;
    b.style.left = Math.round(Math.cos(a) * FORGE_PRO_WHEEL_R) + "px";
    b.style.top = Math.round(Math.sin(a) * FORGE_PRO_WHEEL_R * 0.74) + "px";
    b.addEventListener("mouseenter", () => forgeProWheelSub(v, head, ids, a));
    b.addEventListener("click", (ev) => { ev.stopPropagation(); forgeProWheelSub(v, head, ids, a); });
    host.append(b);
  });
  const c = at || (v && v.pro && v.pro.mouse) || [window.innerWidth / 2, window.innerHeight / 2];
  const rect = (host.parentElement || document.body).getBoundingClientRect();
  host._at = c;
  // where the mouse is - kept far enough inside the viewport that the ring fits
  const x = Math.max(rect.left + 190, Math.min(rect.right - 190, c[0])), y = Math.max(rect.top + 140, Math.min(rect.bottom - 140, c[1]));
  host.style.left = Math.round((rect.width > 400 ? x : c[0]) - rect.left) + "px";
  host.style.top = Math.round((rect.height > 300 ? y : c[1]) - rect.top) + "px";
  host.hidden = false;
}

function forgeProWheelClose() {
  const host = document.getElementById("forge-pro-wheel");
  if (host) { host.hidden = true; host.textContent = ""; delete host.dataset.open; }
}

function forgeProWheelOpenNow() {
  const wh = document.getElementById("forge-pro-wheel");
  return !!(wh && !wh.hidden);
}
// a click anywhere outside the wheel puts it away
document.addEventListener("pointerdown", (ev) => {
  const wh = document.getElementById("forge-pro-wheel");
  if (wh && !wh.hidden && !wh.contains(ev.target)) forgeProWheelClose();
}, true);

function forgeProHotboxOpen(v, at) {
  const host = forgeProHotboxHost();
  if (!host) return;
  const c = at || (v && v.pro && v.pro.mouse) || [window.innerWidth / 2, window.innerHeight / 2];
  // centred ON the mouse (owner 17:06: menus must open at the cursor); moved only as far as needed to stay on screen
  let x = c[0], y = c[1];
  host._used = false; delete host.dataset.pinned;
  const box = host.querySelector(".forge-pro-hbbox");
  const place = () => { if (box) { box.style.left = Math.round(x) + "px"; box.style.top = Math.round(y) + "px"; } host._center = [x, y]; };
  place();
  for (const l of host.querySelectorAll(".forge-pro-list")) l.hidden = true;
  for (const h of host.querySelectorAll(".forge-pro-head")) h.classList.remove("open");
  forgeProHotboxRefresh(v, host);
  host.hidden = false;
  let lo = Infinity, hi = -Infinity, top = Infinity, bot = -Infinity;
  for (const r of host.querySelectorAll(".forge-pro-row")) {
    const b = r.getBoundingClientRect();
    lo = Math.min(lo, b.left); hi = Math.max(hi, b.right); top = Math.min(top, b.top); bot = Math.max(bot, b.bottom);
  }
  if (lo < 6) x += 6 - lo; else if (hi > window.innerWidth - 6) x -= hi - (window.innerWidth - 6);
  if (top < 6) y += 6 - top; else if (bot > window.innerHeight - 6) y -= bot - (window.innerHeight - 6);
  place();
}

function forgeProHotboxHide() {
  const host = document.getElementById("forge-pro-hotbox");
  if (host) { clearTimeout(host._intent); host._dragFrom = null; host.hidden = true; delete host.dataset.pinned; }
}

// a Space tap: one view <-> four views; a tap over a pane of the four maximises that pane
function forgeProTap(v) {
  const m = v.pro;
  if (!v.quad) { v.setLook("quad", true); return "Four views (tap Space over one to make it big)."; }
  let name = "persp";
  const r = v.canvas && v.canvas.getBoundingClientRect();
  if (r && m.mouse) {
    const left = m.mouse[0] < r.left + r.width / 2, topHalf = m.mouse[1] < r.top + r.height / 2;
    name = topHalf ? (left ? "front" : "side") : (left ? "top" : "persp");
  }
  v.setLook("quad", false);
  v.setView(name);
  return { persp: "Perspective", top: "Top", front: "Front", side: "Side" }[name] + " view.";
}

// ================================================================== the mouse in the viewport
function forgeProPickAt(v, x, y) {               // the node under the screen point (x, y), or null
  const t = forgeProTree(v);
  if (!t || !v.canvas || !v.camera) return null;
  const THREE = v.THREE, r = v.canvas.getBoundingClientRect();
  v.camera.updateMatrixWorld();
  const ray = new THREE.Raycaster();
  ray.setFromCamera(new THREE.Vector2(((x - r.left) / r.width) * 2 - 1, -((y - r.top) / r.height) * 2 + 1), v.camera);
  const hit = ray.intersectObjects(t.pickables(), false)[0];
  return hit ? t.nodeOfObject(hit.object) : null;
}

function forgeProBoxPick(v, x0, y0, x1, y1) {     // nodes whose middle is inside a screen box
  const t = forgeProTree(v);
  if (!t) return [];
  const THREE = v.THREE, r = v.canvas.getBoundingClientRect();
  v.camera.updateMatrixWorld();
  const lo = [Math.min(x0, x1), Math.min(y0, y1)], hi = [Math.max(x0, x1), Math.max(y0, y1)];
  const out = [];
  for (const id of t.allIds()) {
    const n = t.node(id);
    if (!n || n.kind !== "mesh" || !n.visible) continue;
    const b = t.worldBox([id]);
    if (b.isEmpty()) continue;
    const p = b.getCenter(new THREE.Vector3()).project(v.camera);
    const sx = r.left + (p.x + 1) / 2 * r.width, sy = r.top + (1 - p.y) / 2 * r.height;
    if (p.z < 1 && sx >= lo[0] && sx <= hi[0] && sy >= lo[1] && sy <= hi[1]) out.push(id);
  }
  return out;
}
// the pro modifiers: Shift toggles, Ctrl/Cmd removes, Ctrl/Cmd+Shift adds
const forgeProHow = (e) => ((e.ctrlKey || e.metaKey) && e.shiftKey ? "add" : (e.ctrlKey || e.metaKey) ? "remove" : e.shiftKey ? "toggle" : "set");

// ================================================================== the camera controller (tumble / track / dolly)
const FORGE_CAM_TUMBLE = 0.0062;   // radians per pixel
const FORGE_CAM_DOLLY = 0.0058;    // per pixel, exponential (so it feels the same near and far)
const FORGE_CAM_WHEEL = 0.0014;    // per wheel delta unit
function forgeProCamera(view, ctx) {
  const { THREE, canvas, controls } = ctx;
  const camera = ctx.camera;
  if (!canvas || !controls || !camera) return;
  const pro = view.pro;
  const ortho = () => !!(view.cam && view.cam !== "persp");
  const dist = () => camera.position.distanceTo(controls.target);
  const clip = () => {                       // near / far follow the distance, so nothing clips while dollying
    const d = dist() || 1;
    camera.near = ortho() ? d / 50 : d / 100; camera.far = ortho() ? d * 50 : d * 100;
    camera.updateProjectionMatrix();
  };
  const changed = () => { controls.dispatchEvent({ type: "change" }); view.dirty = true; };
  const cam = view.camNav = {
    tumble(dx, dy) {
      if (ortho()) return false;
      const off = camera.position.clone().sub(controls.target);
      const up = new THREE.Vector3(0, 1, 0);
      off.applyAxisAngle(up, -dx * FORGE_CAM_TUMBLE);
      const right = new THREE.Vector3().crossVectors(up, off).normalize();
      const tilted = off.clone().applyAxisAngle(right, -dy * FORGE_CAM_TUMBLE);
      // stop just short of straight up / down (the up axis stays up, the way the default tumble does)
      const ang = tilted.angleTo(up);
      if (ang > 0.002 && ang < Math.PI - 0.002 && right.lengthSq() > 0) off.copy(tilted);
      camera.position.copy(controls.target).add(off);
      camera.lookAt(controls.target);
      changed();
      return true;
    },
    track(dx, dy) {
      const h = canvas.clientHeight || 1;
      const per = 2 * dist() * Math.tan((camera.fov * Math.PI) / 360) / h;      // world units per pixel at the COI
      camera.updateMatrixWorld();
      const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
      const upv = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
      const move = right.multiplyScalar(-dx * per).add(upv.multiplyScalar(dy * per));
      camera.position.add(move); controls.target.add(move);
      changed();
      return true;
    },
    dolly(amount) {                           // amount > 0 moves in
      const off = camera.position.clone().sub(controls.target);
      const len = off.length() || 1;
      const next = Math.min(Math.max(len * Math.exp(-amount), 1e-3), 1e5);
      camera.position.copy(controls.target).addScaledVector(off.normalize(), next);
      clip(); changed();
      return true;
    },
    boxDolly(x0, y0, x1, y1) {                // screen points (canvas-relative): left -> right in, right -> left out
      const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
      const bw = Math.max(Math.abs(x1 - x0), 4), bh = Math.max(Math.abs(y1 - y0), 4);
      const cx = (x0 + x1) / 2 - w / 2, cy = (y0 + y1) / 2 - h / 2;
      cam.track(cx, cy);                      // the box's middle comes to the middle of the view
      const f = Math.max(bw / w, bh / h);
      cam.dolly(x1 >= x0 ? -Math.log(f) : Math.log(f));
      return true;
    },
  };
  // a drag: which button + which keys decide what it is, at the press
  let drag = null;
  const box = document.createElement("div"); box.className = "forge-marquee forge-boxdolly"; box.hidden = true;
  canvas.parentElement.append(box);
  canvas.addEventListener("pointerdown", (e) => {
    if (!e.altKey || view.quad) return;
    const both = drag && drag.buttons !== e.buttons;
    e.preventDefault(); e.stopImmediatePropagation();
    if (both) { drag.kind = "dolly"; drag.buttons = e.buttons; return; }   // left + middle = dolly
    let kind = e.button === 0 ? "tumble" : e.button === 1 ? "track" : e.button === 2 ? "dolly" : null;
    if (!kind) return;
    if (kind === "tumble" && (e.ctrlKey || e.metaKey)) kind = "box";
    if (kind === "tumble" && ortho()) kind = "none";               // orthographic views do not tumble
    drag = { kind, x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, lock: null, shift: e.shiftKey, id: e.pointerId, buttons: e.buttons };
    try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* gone */ }
    controls.dispatchEvent({ type: "start" });
    canvas.classList.add("cam-" + kind);
  }, { capture: true });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) return;
    e.stopImmediatePropagation();
    let dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.x = e.clientX; drag.y = e.clientY;
    if (drag.shift && (drag.kind === "tumble" || drag.kind === "track")) {
      if (!drag.lock) { const tx = e.clientX - drag.x0, ty = e.clientY - drag.y0; if (Math.hypot(tx, ty) > 3) drag.lock = Math.abs(tx) >= Math.abs(ty) ? "x" : "y"; }
      if (drag.lock === "x") dy = 0; else if (drag.lock === "y") dx = 0; else return;
    }
    if (drag.kind === "tumble") cam.tumble(dx, dy);
    else if (drag.kind === "track") cam.track(dx, dy);
    else if (drag.kind === "dolly") cam.dolly((dx + dy) * FORGE_CAM_DOLLY);
    else if (drag.kind === "box") {
      const r = canvas.getBoundingClientRect();
      box.hidden = false;
      Object.assign(box.style, { left: Math.min(drag.x0, e.clientX) - r.left + canvas.offsetLeft + "px", top: Math.min(drag.y0, e.clientY) - r.top + canvas.offsetTop + "px",
        width: Math.abs(e.clientX - drag.x0) + "px", height: Math.abs(e.clientY - drag.y0) + "px" });
    }
  }, { capture: true });
  const end = (e) => {
    if (!drag || (e.pointerId !== undefined && e.pointerId !== drag.id)) return;
    if (e.buttons) { drag.buttons = e.buttons; if (drag.kind === "dolly" && e.buttons === 1) drag.kind = ortho() ? "none" : "tumble"; return; }   // one of two buttons let go
    e.stopImmediatePropagation();
    const d = drag; drag = null;
    canvas.classList.remove("cam-" + d.kind);
    if (d.kind === "box") {
      box.hidden = true;
      const r = canvas.getBoundingClientRect();
      if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) > 6) cam.boxDolly(d.x0 - r.left, d.y0 - r.top, e.clientX - r.left, e.clientY - r.top);
    }
    controls.dispatchEvent({ type: "end" });
  };
  canvas.addEventListener("pointerup", end, { capture: true });
  canvas.addEventListener("pointercancel", end, { capture: true });
  canvas.addEventListener("wheel", (e) => {
    if (view.quad || (view.mode === "sculpt" && (pro.held.has("b") || pro.held.has("m")))) return;
    e.preventDefault();
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
    controls.dispatchEvent({ type: "start" });
    cam.dolly(-e.deltaY * unit * FORGE_CAM_WHEEL);
    clearTimeout(cam.wheelEnd); cam.wheelEnd = setTimeout(() => controls.dispatchEvent({ type: "end" }), 220);
  }, { passive: false });
}

// ================================================================== attach to a viewer
function forgeProAttach(view, ctx) {
  const { THREE, canvas, controls } = ctx;
  const pro = view.pro = { timer: 0, at: null, down: false, last: null, open: false, saved: null, controls: controls,
    held: new Set(), mouse: null, spaceAt: 0, tool: null, lastTool: "translate", isolated: null,
    snap: { grid: false, edge: false, point: false }, gridStep: 0.25, recent: [], grid: null };
  if (!canvas || !controls) return pro;

  // the pro grid on the ground plane: a line every unit, a fainter one every grid step (what x snaps to)
  if (ctx.scene) {
    const g = new THREE.Group(); g.name = "forge-grid";
    const fine = new THREE.GridHelper(12, 12 / pro.gridStep, 0x3a3f49, 0x2c3038);
    const major = new THREE.GridHelper(12, 12, 0x7b818d, 0x4a505a);
    for (const h of [fine, major]) { h.material.transparent = true; h.material.depthWrite = false; h.raycast = () => {}; }
    fine.material.opacity = 0.35; major.material.opacity = 0.6;
    g.add(fine, major); g.renderOrder = -1;
    ctx.scene.add(g);
    pro.grid = g;
  }

  // the buttons: pro - Alt/Option + left / middle / right = tumble / track / dolly; without Alt the left button
  // selects and the right button is the marking menu
  // The camera is Forge's own (owner 17:06: "I want to move like im in [the pro app] right now it doesn't feel
  // right"): OrbitControls only keeps the centre of interest (controls.target); no mouse button drives it. What
  // the mouse does, read from each press (never from a remembered Alt state that a lost key-up can leave stuck):
  //   Alt/Option + left drag    tumble about the centre of interest (left / right turns about the world's up axis,
  //                             up / down tilts); an orthographic view (top / front / side) does not tumble
  //   Alt/Option + middle drag  track: the picture moves 1:1 with the mouse
  //   Alt/Option + right drag   dolly toward / away from the centre of interest: right or down = in, left or up = out
  //   Alt/Option + left + middle dolly too;  + Shift locks a tumble / track to the first direction you move
  //   Alt/Option + Ctrl/Cmd + left drag  box dolly: a box drawn left -> right moves in to fill the view with it,
  //                             right -> left moves out
  //   wheel                     dolly in / out in steps
  const buttons = pro.buttons = () => {
    const mb = controls.mouseButtons;
    mb.LEFT = null; mb.MIDDLE = null; mb.RIGHT = null;
    controls.enableZoom = false; controls.enablePan = false;
  };
  const proAlt = pro.alt = (on) => { pro.altOn = !!on; buttons(); };   // kept for older callers; the press decides now
  buttons();
  forgeProCamera(view, ctx);
  const setMode = view.setMode;
  view.setMode = (m) => { setMode(m); buttons(); };   // forge_edit puts orbit on the middle button in poly mode

  // ------------------------------------------------ left button: select (click / Shift / Ctrl / box), q/w/e + left = menu
  const box = proEl("div", "forge-marquee"); box.hidden = true;
  canvas.parentElement.append(box);
  let gest = null;
  canvas.addEventListener("pointerdown", (e) => {
    pro.mouse = [e.clientX, e.clientY];
    if (e.button !== 0 || e.altKey) return;              // every view, the four-view layout included (Ziva)
    const held = ["q", "w", "e"].find((k) => pro.held.has(k));
    if (held && view.mode !== "sculpt") {               // hold q / w / e + left button: that tool's marking menu
      e.preventDefault(); e.stopImmediatePropagation();
      pro.open = "key";
      forgeProMarkShow(view, e.clientX, e.clientY, forgeProMenu(view, { key: held }));
      return;
    }
    if (view.mode !== "view") return;                    // sculpt strokes and component picking own the button there
    const tc = view.transform;
    if (tc && tc.object && tc.axis) return;            // the handle
    gest = { at: [e.clientX, e.clientY], how: forgeProHow(e), box: false, id: e.pointerId };
  }, { capture: true });
  canvas.addEventListener("pointermove", (e) => {
    pro.mouse = [e.clientX, e.clientY];
    if (pro.open) { forgeProMarkHover(e.clientX, e.clientY); return; }
    if (!gest) return;
    if (!gest.box && Math.hypot(e.clientX - gest.at[0], e.clientY - gest.at[1]) > 4) {
      gest.box = true;
      try { canvas.setPointerCapture(gest.id); } catch (_) { /* gone */ }
    }
    if (gest.box) {
      const r = canvas.getBoundingClientRect(), x0 = gest.at[0] - r.left, y0 = gest.at[1] - r.top, x1 = e.clientX - r.left, y1 = e.clientY - r.top;
      box.hidden = false; box.classList.toggle("sub", gest.how === "remove");
      Object.assign(box.style, { left: Math.min(x0, x1) + canvas.offsetLeft + "px", top: Math.min(y0, y1) + canvas.offsetTop + "px",
        width: Math.abs(x1 - x0) + "px", height: Math.abs(y1 - y0) + "px" });
    }
  });
  const endLeft = (e) => {
    if (e.button !== 0) return;
    if (pro.open === "key") {
      pro.open = false;
      const id = forgeProMarkPick(e.clientX, e.clientY);
      forgeProMarkHide();
      if (id) forgeProRun(view, id);
      return;
    }
    if (!gest) return;
    const g = gest; gest = null; box.hidden = true;
    const t = forgeProTree(view);
    if (!t) return;
    if (g.box) { t.selectMany(forgeProBoxPick(view, g.at[0], g.at[1], e.clientX, e.clientY), g.how === "set" ? "set" : g.how); return; }
    const n = forgeProPickAt(view, e.clientX, e.clientY);
    if (n) t.select(n.id, g.how);
    else if (g.how === "set") t.selectNone();
  };
  canvas.addEventListener("pointerup", endLeft);
  window.addEventListener("pointerup", (e) => { if (pro.open === "key") endLeft(e); });

  // ------------------------------------------------ right button: press and HOLD - the marking menu is there at once,
  // under the mouse, for as long as the button is down. Let go over a wedge or an item (or flick toward one) and it
  // runs; let go in the middle and the menu just closes. A quick click does nothing - the menu never stays pinned
  // open (owner 17:06: "right click doesnt do that ... fix the systems").
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 2 || e.altKey) return;              // every view, the four-view layout included
    e.preventDefault();
    pro.down = true; pro.at = [e.clientX, e.clientY];
    window.clearTimeout(pro.timer);
    const how = { shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey };
    const node = view.mode === "view" ? forgeProPickAt(view, pro.at[0], pro.at[1]) : null;
    pro.open = "right";
    forgeProMarkShow(view, pro.at[0], pro.at[1], forgeProMenu(view, Object.assign({ node: node }, how)));
  });
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  const endRight = (e) => {
    if (e.button !== 2) return;
    pro.down = false; window.clearTimeout(pro.timer);
    if (pro.open !== "right") return;
    pro.open = false;
    const id = forgeProMarkPick(e.clientX, e.clientY);
    forgeProMarkHide();
    if (id) {
      // the menu was opened over an object that is not selected: what you pick acts on THAT object
      const t = forgeProTree(view), at = pro.at || [e.clientX, e.clientY];
      const node = view.mode === "view" ? forgeProPickAt(view, at[0], at[1]) : null;
      if (node && t && !t.selected().includes(node.id) && !e.shiftKey && !e.ctrlKey && !e.metaKey) t.select(node.id);
      forgeProRun(view, id);
    }
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && pro.open === "right") { pro.open = false; pro.down = false; forgeProMarkHide(); }
  }, true);
  canvas.addEventListener("pointerup", endRight);
  window.addEventListener("pointerup", endRight);
  window.addEventListener("pointermove", (e) => { if (pro.open === "right") forgeProMarkHover(e.clientX, e.clientY); });

  // ------------------------------------------------ snapping while the handle drags (objects, the pivot, components)
  const tc = ctx.transform || view.transform;
  if (tc && tc.addEventListener) {
    tc.addEventListener("objectChange", () => {
      if (!tc.object || tc.mode !== "translate" || !forgeProSnapAny(view)) return;
      const o = tc.object, w = o.getWorldPosition(new THREE.Vector3());
      const t = forgeProTree(view), n = t && t.pivotMode ? t.node(pro.pivotFor) : null;
      const skip = [o].concat(n ? [n.grp] : []);           // never snap onto the thing being moved
      const s = forgeProSnapPoint(view, w, skip, tc.axis);
      if (!s || !o.parent) return;
      o.position.copy(o.parent.worldToLocal(s.clone()));
      o.updateMatrixWorld(true);
      view.dirty = true;
    });
  }
  view.snapPivot = (pivot) => {                         // forge_edit.js asks before it moves the components
    if (!forgeProSnapAny(view) || !pivot.parent) return;
    pivot.parent.updateMatrixWorld(true);
    const w = pivot.getWorldPosition(new THREE.Vector3());
    const s = forgeProSnapPoint(view, w, [view.holder], view.gizmo && view.gizmo.axis);   // onto other objects, or the grid
    if (s) pivot.position.copy(pivot.parent.worldToLocal(s.clone()));
  };
  const hud = proEl("div", "forge-snaps"); hud.id = "forge-snaps";
  for (const [k, label, key] of [["grid", "Grid", "x"], ["edge", "Edge", "c"], ["point", "Point", "v"]]) {
    const b = proEl("button", "forge-snap", label);
    b.type = "button"; b.dataset.snap = k;
    b.title = "Snap to " + label.toLowerCase() + ": hold " + key + " while you drag, or click to keep it on (the status line).";
    b.addEventListener("click", () => proSay(forgeProSnapToggle(view, k)));
    hud.append(b);
  }
  // the viewport's Grid / Edge / Point chips are not part of the pro viewport (owner 2026-10-21: "get rid of the ...
  // grid edge point buttons on the top right"): kept, hidden; snapping lives on the status line, the hotbox's Snap
  // menu and the x / c / v holds
  hud.hidden = true;
  canvas.parentElement.append(hud);

  // ------------------------------------------------ sculpt: hold b and drag = brush size, m and drag = strength
  let brushDrag = null;
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || view.mode !== "sculpt" || !(pro.held.has("b") || pro.held.has("m"))) return;
    e.preventDefault(); e.stopImmediatePropagation();
    brushDrag = { x: e.clientX, what: pro.held.has("b") ? "radius" : "strength", from: view.brush[pro.held.has("b") ? "radius" : "strength"] };
    try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* gone */ }
  }, { capture: true });
  canvas.addEventListener("pointermove", (e) => {
    if (!brushDrag) return;
    e.stopImmediatePropagation();
    const k = brushDrag.what, lo = k === "radius" ? 0.02 : 0.05, hi = k === "radius" ? 0.4 : 1;
    view.brush[k] = Math.max(lo, Math.min(hi, brushDrag.from * Math.pow(1.01, e.clientX - brushDrag.x)));
    const inp = document.getElementById(k === "radius" ? "forge-radius" : "forge-strength"); if (inp) inp.value = String(view.brush[k]);
    proSay((k === "radius" ? "Brush size " : "Strength ") + view.brush[k].toFixed(2));
  }, { capture: true });
  canvas.addEventListener("pointerup", (e) => { if (brushDrag) { e.stopImmediatePropagation(); brushDrag = null; } }, { capture: true });

  view.proRestore = () => { proAlt(false); forgeProPivotMode(view, false); };
  forgeProKeys();                       // after forge_edit's own keys, so its modal wins while it runs
  return pro;
}

// ================================================================== the hotkeys (the pro default set)
// Installed from forgeProAttach and NOT at page load: forge_edit.js registers its capture listener while the
// viewer is built and its modal move owns every key while it runs; registering later keeps that order.
function forgeProKeys() {
  if (forgeProKeys.done) return;
  forgeProKeys.done = true;
  const inField = (el) => el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
  const sheetOpen = () => { const s = document.getElementById("forge"); return !!(s && !s.hidden && forge.view); };
  const take = (e) => { e.preventDefault(); e.stopImmediatePropagation(); };

  document.addEventListener("keydown", (e) => { if (e.key === "Alt" && sheetOpen() && !inField(e.target)) { const m = forge.view.pro; if (m && m.alt) m.alt(true); } }, true);
  document.addEventListener("keyup", (e) => { if (e.key === "Alt" && sheetOpen()) { const m = forge.view.pro; if (m && m.alt) m.alt(false); } }, true);
  window.addEventListener("blur", () => {
    const v = typeof forge !== "undefined" && forge.view;
    if (v && v.pro) { v.pro.held.clear(); if (v.pro.alt) v.pro.alt(false); forgeProSnap(v, "step", false); forgeProSnapHud(v); }
  });

  document.addEventListener("keydown", (e) => {
    if (!sheetOpen() || inField(e.target)) return;
    const hk = document.getElementById("forge-hotkeys");
    if (hk && !hk.hidden && (hk.dataset.capturing || hk.contains(e.target))) return;   // the Hotkey Editor has the keys
    const v = forge.view, m = v.pro || {};
    if (v.modalActive && v.modalActive()) return;            // Blender's G/R/S modal is running: its keys
    const k = e.key, mod = e.ctrlKey || e.metaKey, sh = e.shiftKey, alt = e.altKey;
    const run = (id) => { take(e); forgeProRun(v, id); };
    if ((k === " " || e.code === "Space") && mod) { take(e); if (!e.repeat) forgeProRun(v, "hideUI"); return; }   // Ctrl+Space
    if (k === " " || e.code === "Space") {                   // Space: hold = hotbox, tap = one/four views
      take(e);
      if (e.repeat) return;
      const hb = document.getElementById("forge-pro-hotbox");
      if (hb && !hb.hidden) return;
      if (forgeProWheelOpenNow()) { forgeProWheelClose(); return; }   // Space again puts the wheel away
      m.spaceAt = performance.now();
      // Space: the hotbox, centred on the mouse - the menu rows tight around the pointer, each menu dropping
      // down where you hover (owner 17:06: "neat and tidy", "open up on the cursor"). The wheel (Ziva) is kept:
      // Windows > Radial Menus.
      forgeProHotboxOpen(v, m.mouse);
      return;
    }
    if (k === "Escape") {
      if (hk && !hk.hidden) { take(e); hk.hidden = true; return; }   // Esc closes the Hotkey Editor first
      const hb = document.getElementById("forge-pro-hotbox"), mk = document.getElementById("forge-pro-marking");
      if (hb && !hb.hidden) { take(e); forgeProHotboxHide(); return; }
      if (forgeProWheelOpenNow()) { take(e); forgeProWheelClose(); return; }
      if (mk && !mk.hidden) { take(e); forgeProMarkHide(); m.open = false; return; }
      const t = forgeProTree(v);
      if (t && t.pivotMode) { take(e); forgeProPivotMode(v, false); return; }
      take(e);                                                 // pro: Esc cancels, it never closes the window
      if ((v.transform && v.transform.object) || (v.gizmo && v.gizmo.object)) forgeProTool(v, null);
      return;
    }
    // ---- every other key: the hotkey table (app/ui/forge_keys.js - the pro default set, or the owner's own set
    // from the Hotkey Editor). The old switch is kept below as the fallback when forge_keys.js is missing.
    if (typeof forgeKeyChord === "function") {
      const chord = forgeKeyChord(e), act = forgeKeyAction(chord);
      if (!act) return;                                        // unbound: Ctrl/Cmd+S, C, V ... stay the app's
      const hold = forgeHotkeys.hold(act);
      if (hold && !e.repeat) { m.held.add(hold); (m.holdCodes = m.holdCodes || {})[e.code || k] = hold; }
      if (act.startsWith("@") && !e.repeat) (m.holdActs = m.holdActs || {})[e.code || k] = act;
      if (e.repeat && !forgeHotkeys.repeats(act)) { take(e); return; }
      return forgeProKeyAct(v, act, e, take, run);
    }
    if (!e.repeat && /^[qwexcvbm]$/i.test(k) && !mod && !alt) m.held.add(k.toLowerCase());
    const lower = k.length === 1 ? k.toLowerCase() : k;

    // ---- Ctrl / Cmd
    if (mod) {
      if (lower === "z") return run(sh ? "redo" : "undo");
      if (lower === "y") return run("redo");
      if (lower === "d") return run("duplicate");
      if (lower === "g") return run(sh ? "ungroup" : "group");
      if (lower === "h") return run(sh ? "showLast" : alt ? "showAll" : "hide");
      if (lower === "a" && sh) return run("selectAll");
      if (lower === "a") return run("channelBox");
      if (lower === "i" && sh) return run("invert");
      if (k === "1") return run("isolate");
      if (lower === "e") return run("extrude");
      if (lower === "b") return run("bevel");
      if (k === "Backspace" || k === "Delete") return run("deleteComp");
      if (k === " " || e.code === "Space") return run("hideUI");
      return;                                                  // Ctrl/Cmd+S, C, V ... stay the app's
    }
    // ---- Alt / Option
    if (alt) {
      if (lower === "d") return run("selectNone");
      if (lower === "h") return run("hideOthers");
      if (lower === "x") return run("xray");
      if (k === "Home") return run("defaultView");
      if (k.startsWith("Arrow")) { take(e); forgeProNudge(v, k === "ArrowRight" ? 1 : k === "ArrowLeft" ? -1 : 0, k === "ArrowUp" ? 1 : k === "ArrowDown" ? -1 : 0); return; }
      return;
    }
    // ---- bare keys (Shift for the capitals)
    if (k.startsWith("Arrow")) {                               // pick-walk the hierarchy
      const t = forgeProTree(v);
      if (!t || forgeProComp(v)) return;
      take(e); t.pickWalk({ ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" }[k]); return;
    }
    if (e.repeat && !/^[\[\]\-=+]$/.test(k)) { if (/^[qwedxjcvbm]$/i.test(k)) take(e); return; }
    switch (k) {
      case "q": return run("select");
      case "w": return run("move");
      case "e": return run("rotate");
      case "r": return run("scale");
      case "y": return run("lastTool");
      case "t": return run("move");
      case "g": take(e); if (m.last) forgeProRun(v, m.last); return;
      case "z": return run("undo");
      case "Z": return run("redo");
      case "D": return run("duplicateT");
      case "p": return run("parent");
      case "P": return run("unparent");
      case "h": return run("hideToggle");
      case "H": return run("show");
      case "a": return run("frameAll");
      case "A": return run("frameAll");
      case "f": return run("frameSel");
      case "F": return run("frameSel");
      case "1": return run("smooth1");
      case "2": return run("smooth2");
      case "3": return run("smooth3");
      case "4": return run("wire");
      case "5": return run("shaded");
      case "6": return run("textured");
      case "7": return run("lights");
      case "d": take(e); proSay(forgeProPivotMode(v, true)); return;
      case "Insert": take(e); proSay(forgeProPivotMode(v, null)); return;
      case "Home": return run("pivotEdit");
      case "x": case "X": take(e); forgeProSnapHud(v); proSay("Snap to grid while x is held."); return;
      case "c": case "C": take(e); forgeProSnapHud(v); proSay("Snap to edges while c is held."); return;
      case "v": case "V": take(e); forgeProSnapHud(v); proSay("Snap to vertices while v is held."); return;
      case "b": take(e); if (forgeProComp(v)) forgeProRun(v, "softSel"); else if (v.mode === "sculpt") proSay("Hold b and drag left / right: brush size."); return;
      case "m": take(e); if (v.mode === "sculpt") proSay("Hold m and drag left / right: strength."); return;
      case "j": case "J": take(e); forgeProSnap(v, "step", true); return;
      case "-": return run("__smaller");
      case "=": case "+": return run("__bigger");
      case "Delete": case "Backspace": return run("delete");
      case ">": return run("grow");
      case "<": return run("shrink");
      case "F8": return run("objComp");
      case "F9": return run("vertex");
      case "F10": return run("edge");
      case "F11": return run("face");
      case "Enter": take(e); forgeProTool(v, null); return;
      case "[": case "]":
        if (v.mode === "sculpt") return;                       // the brush size there (forge.js)
        take(e); if (k === "[") v.viewUndo(); else v.viewRedo(); return;
      default: return;
    }
  }, true);

  document.addEventListener("keyup", (e) => {
    const v = typeof forge !== "undefined" && forge.view;
    if (!v || !v.pro) return;
    const m = v.pro, k = e.key;
    if (k.length === 1) m.held.delete(k.toLowerCase());
    const hc = m.holdCodes && m.holdCodes[e.code || k];
    if (hc) { m.held.delete(hc); delete m.holdCodes[e.code || k]; }
    const ha = m.holdActs && m.holdActs[e.code || k];
    if (ha) {
      delete m.holdActs[e.code || k];
      if (ha === "@pivotHold") { const t = forgeProTree(v); if (t && t.pivotMode) forgeProPivotMode(v, false); }
      if (ha === "@snapStep") forgeProSnap(v, "step", false);
      if (/^@snap(Grid|Edge|Point)$/.test(ha)) forgeProSnapHud(v);
    }
    if (k === " " || e.code === "Space") {
      const wh = document.getElementById("forge-pro-wheel");
      if (wh && !wh.hidden) {                                  // the wheel (the owner's Space menus)
        if (wh.dataset.open) return;                           // a menu is down: it stays so it can be clicked
        const quickW = performance.now() - (m.spaceAt || 0) < FORGE_PRO_TAP;
        const usedW = !!wh._used;
        forgeProWheelClose();
        if (quickW && !usedW && sheetOpen()) proSay(forgeProTap(v));
        return;
      }
      const hb = document.getElementById("forge-pro-hotbox");
      if (!hb || hb.hidden || hb.dataset.pinned) return;
      const quick = performance.now() - (m.spaceAt || 0) < FORGE_PRO_TAP;
      const used = !!hb._used;
      if (hb._zone) return;                                    // a zone menu is open: the mouse release decides
      // a menu is dropped down under the mouse: it stays until you click an item (or anywhere else to close)
      if (!quick && hb.querySelector(".forge-pro-list:not([hidden])")) { hb.dataset.pinned = "1"; return; }
      forgeProHotboxHide();
      if (quick && !used && sheetOpen()) proSay(forgeProTap(v));
      return;
    }
    if (k === "d" || k === "D") { const t = forgeProTree(v); if (t && t.pivotMode) forgeProPivotMode(v, false); }
    if (/^[xcv]$/i.test(k)) forgeProSnapHud(v);
    if (k === "j" || k === "J") forgeProSnap(v, "step", false);
  });
}

// what a hotkey does (forge_keys.js maps the key to this action): a command, or one of the special "@" actions
function forgeProKeyAct(v, act, e, take, run) {
  if (!act.startsWith("@")) return run(act);
  const nudge = { "@nudgeUp": [0, 1], "@nudgeDown": [0, -1], "@nudgeLeft": [-1, 0], "@nudgeRight": [1, 0] }[act];
  if (nudge) { take(e); forgeProNudge(v, nudge[0], nudge[1]); return; }
  const walk = { "@pickUp": "up", "@pickDown": "down", "@pickLeft": "left", "@pickRight": "right" }[act];
  if (walk) { const t = forgeProTree(v); if (!t || forgeProComp(v)) return; take(e); t.pickWalk(walk); return; }
  const m = v.pro || {};
  take(e);
  switch (act) {
    case "@repeatLast": if (m.last) forgeProRun(v, m.last); return;
    case "@completeTool": forgeProTool(v, null); return;
    case "@pivotHold": proSay(forgeProPivotMode(v, true)); return;
    case "@pivotToggle": proSay(forgeProPivotMode(v, null)); return;
    case "@snapGrid": forgeProSnapHud(v); proSay("Snap to grid while the key is held."); return;
    case "@snapEdge": forgeProSnapHud(v); proSay("Snap to edges while the key is held."); return;
    case "@snapPoint": forgeProSnapHud(v); proSay("Snap to vertices while the key is held."); return;
    case "@snapStep": forgeProSnap(v, "step", true); return;
    case "@brushSize": if (forgeProComp(v)) forgeProRun(v, "softSel"); else if (v.mode === "sculpt") proSay("Hold the key and drag left / right: brush size."); return;
    case "@brushStrength": if (v.mode === "sculpt") proSay("Hold the key and drag left / right: strength."); return;
    case "@viewUndo": if (v.mode === "sculpt") return; v.viewUndo(); return;
    case "@viewRedo": if (v.mode === "sculpt") return; v.viewRedo(); return;
    default: return;
  }
}

// manipulator size has no menu entry; give the two keys commands of their own
FORGE_PRO_CMDS.hotkeyEditor = ["Hotkey Editor", () => { if (typeof forgeHotkeyEditor === "function") { forgeHotkeyEditor(true); return "Hotkey Editor: click a key box and press the new key."; } return "The Hotkey Editor is not loaded."; }];
FORGE_PRO_CMDS.deleteHistory = ["Delete History", (v) => { if (!window.forgeHistory) return ""; window.forgeHistory.clear(); if (v.tree) v.tree.build(); return "History deleted (Alt+Shift+D)."; }];
FORGE_PRO_CMDS.__smaller = ["Smaller manipulator", (v) => forgeProManipSize(v, false)];
FORGE_PRO_CMDS.__bigger = ["Bigger manipulator", (v) => forgeProManipSize(v, true)];

// older callers (forge.js's buttons, tests) - the marking menu's 8 wedges and the hotbox, by name
function forgeProSets(v) {
  const toPairs = (menu) => Object.values(menu.ring).map((id) => [FORGE_PRO_CMDS[id][0], () => forgeProRun(v, id)]);
  return { object: toPairs(forgeProMenu(v, { node: v && forgeProTree(v) ? forgeProTree(v).active() : null })),
           shift: toPairs(forgeProMenu(v, { shift: true })), ctrl: toPairs(forgeProMenu(v, { ctrl: true })) };
}
