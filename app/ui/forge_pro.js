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
// the ring's height per wedge: north / south sit a little further out than the diagonals, so the chips never touch
// (owner 2026-10-25: menus overlapped) while the ring stays as tight sideways as the owner asked
const forgeProRingY = (a) => Math.sin(a) * FORGE_PRO_R * (Math.abs(Math.sin(a)) > 0.9 ? 1.15 : 0.82);
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
  // several meshes picked: all their components at once (Maya) - one multi-edit session (forge_scene.js multiBegin)
  const meshes = t && t.selected ? t.selected().filter((id) => { const x = t.node(id); return x && x.kind === "mesh"; }) : [];
  if (meshes.length >= 2 && t.multiBegin && !forgeProComp(v)) {
    const k = t.multiBegin(meshes);
    if (typeof forgeModelMode === "function") await forgeModelMode(true);
    if (sel && v.setSelMode) v.setSelMode(sel);
    return k ? k + " objects: their components together - leave component mode (F8) to split them back." : "";
  }
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
  if (forgeProComp(v)) {                           // component mode: the components' own pivot (Maya: D on components)
    if (!v.compPivotEdit) return "";
    const want = on == null ? !v.edit.pivotEdit : !!on;
    if (want === !!v.edit.pivotEdit) return "";
    const got = v.compPivotEdit(want);
    if (want && !got) return "Pick components first, then D to place their pivot.";
    if (t) t.pivotMode = got;
    return got ? "Pivot edit: drag the handle to place the components' pivot (snap with x / c / v). Release D / Insert to use it."
      : v.customPivot() ? "Custom pivot set: move, rotate and scale turn about it (Reset Pivot drops it)." : "";
  }
  if (!t || !tc) return "";
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
  // the steps are Settings > Manipulators (move 0 = the grid step)
  const S = window.ForgeSettings, mv = S && +S.get("snapMove") > 0 ? +S.get("snapMove") : step;
  const rot = (S ? +S.get("snapRotate") || 15 : 15) * Math.PI / 180, sc = S ? +S.get("snapScale") || 0.1 : 0.1;
  for (const tc of tcs) if (kind === "step") { tc.setTranslationSnap(on ? mv : null); tc.setRotationSnap(on ? rot : null); tc.setScaleSnap(on ? sc : null); }
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
  // Material Maker has its own workspace now (owner 2026-10-21: "material maker needs to go to its own work space"):
  // it shows in Workspace: Materials, never as a side panel of Modeling
  let ws = "model"; try { ws = localStorage.getItem("loki-forge-workspace") || "model"; } catch (_) { /* private mode */ }
  p = Object.assign({}, p, { materials: ws === "mat" });
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
  if (typeof forgeSplitAttach === "function") forgeSplitAttach();   // the panels' drag-to-resize edges (forge_split.js)
  const v = typeof forge !== "undefined" && forge.view;
  if (v && v.resize) v.resize();
  return p;
}
function forgeProPanel(name, on) {
  if (name === "materials" && typeof ForgeUVEditor !== "undefined") {      // Material Maker = Workspace: Materials (owner 2026-10-21)
    const now = ForgeUVEditor.workspace() === "mat";
    const want = on == null ? !now : !!on;
    if (want === now) return want ? "Materials workspace." : "";
    return ForgeUVEditor.setWorkspace(want ? "mat" : "model");
  }
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

function forgeProInterp(v, how) {
  const t = v && v.tree;
  if (!t || !t.api) return "Open Forge first.";
  if (!t.api.active() || !t.api.active().keys) return "Nothing is keyed here.";
  t.api.undoChunk("key interpolation", () => t.api.setInterp(null, t.time.frame, null, null, how));
  return "Key interpolation: " + how + " at frame " + Math.round(t.time.frame) + ".";
}

function forgeProMirror(v, axis) {
  const t = v && v.tree;
  if (!t || !t.api) return "Open Forge first.";
  if (!t.api.active() || !t.api.active().keys) return "Nothing is keyed here.";
  t.api.undoChunk("mirror keys", () => t.api.mirrorKeys(null, axis));
  return "Mirrored the keys across " + ["YZ", "XZ", "XY"][axis] + ".";
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
    sculptReduce: ["Reduce (Decimate)", () => { window.ForgeSculpt && window.ForgeSculpt.op("decimate", { percent: +((document.getElementById("forge-sculpt-reduce") || {}).value || 50), lockBorder: true }); }],
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
    resetPivot: ["Reset Pivot", (v) => (forgeProComp(v) && v.resetComponentPivot ? (v.resetComponentPivot() ? "The components' pivot is back in their middle." : "No custom pivot on these components.")
      : T(v).resetPivot() ? "Pivot back on the object's origin." : "")],
    bakePivot: ["Bake Pivot", (v) => { if (forgeProComp(v)) return "Bake Pivot works on objects: F8 first."; const t = T(v); return t.bakePivot && t.bakePivot() ? "Pivot baked: it is the object's origin now, and the translate took its place. Nothing moved." : ""; }],
    pivotBottom: ["Pivot to Bottom", (v) => (T(v).pivotBottom() ? "Pivot on the bottom middle - the object stands on it." : "")],
    pivotOrigin: ["Pivot to World Origin", (v) => (T(v).pivotOrigin() ? "Pivot on the world origin." : "")],
    pivotToSelection: ["Pivot to Selection", (v) => (T(v).pivotToSelection() ? "Pivot on the middle of the picked components."
      : "Pick components first (F9 / F10 / F11) - the pivot goes to their middle.")],
    pivotEdit: ["Edit Pivot", (v) => forgeProPivotMode(v, null)],
    freeze: ["Freeze Transformations", (v) => (T(v).freeze() ? "Frozen: reads 0 / 0 / 1, nothing moved." : "")],
    resetXf: ["Reset Transformations", (v) => (T(v).resetTransform() ? "Back to 0 / 0 / 1." : "")],
    channelBox: ["Channel Box", () => forgeProPanel("channel")],
    outliner: ["Outliner", () => forgeProPanel("outliner")],
    layerEditor: ["Layer Editor", () => { const b = document.getElementById("forge-layer-editor"); if (!b) return "The Layer Editor is not built here."; b.hidden = !b.hidden; if (!b.hidden && !forgeProPanels().channel) forgeProPanel("channel", true); return b.hidden ? "Layer Editor hidden." : "Layer Editor shown (under the Channel Box)."; }],
    layerAdd: ["Create Empty Layer", () => { const t = forge.view && forge.view.tree && forge.view.tree.api; if (!t) return "Open Forge first."; const l = t.layerAdd(); return "Layer " + l.name + " created."; }],
    layerAssign: ["Assign to Current Layer", () => { const t = forge.view && forge.view.tree && forge.view.tree.api; if (!t) return "Open Forge first."; const cur = (t.layerList().find((l) => l.current) || { id: 0 }).id, ids = t.selected(); if (!ids.length) return "Select objects first."; t.layerAssign(cur, ids); return "Assigned the selection to the current layer."; }],
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
    setKey: ["Set Key", (v) => { const t = v && v.tree; if (!t || !t.api) return "Open Forge first."; const n = t.api.active(); if (!n) return "Select an object first."; const tr = t.api.transform(); if (!tr) return "Select an object first."; let c = 0;
      t.api.undoChunk("set key", () => { for (const part of ["translate", "rotate", "scale"]) for (let a = 0; a < 3; a++) if (t.api.setKey(n.id, t.time.frame, part, a, tr[part][a])) c++; });
      return "Keyed " + c + " channels of " + n.name + " at frame " + Math.round(t.time.frame) + "."; }],
    deleteKey: ["Delete Key", (v) => { const t = v && v.tree; if (!t || !t.api) return "Open Forge first."; const n = t.api.active(); if (!n || !n.keys) return "Nothing is keyed here."; const f = Math.round(t.time.frame);
      t.api.undoChunk("delete key", () => t.api.deleteKey(n.id, f)); return "Took the keys off " + n.name + " at frame " + f + "."; }],
    clearKeys: ["Delete All Keys", (v) => { const t = v && v.tree; if (!t || !t.api) return "Open Forge first."; const n = t.api.active(); if (!n || !n.keys) return "Nothing is keyed here."; t.api.undoChunk("clear keys", () => t.api.clearKeys(n.id)); return "Cleared " + n.name + "'s keys."; }],
    playPause: ["Play / Stop", (v) => { const t = v && v.tree; if (!t || !t.api) return "Open Forge first."; const on = t.api.togglePlay(); return on ? "Playing." : "Stopped at frame " + Math.round(t.time.frame) + "."; }],
    prevKey: ["Previous Key", (v) => { const t = v && v.tree; if (!t || !t.api) return "Open Forge first."; return t.api.stepKey(null, -1) ? "Frame " + Math.round(t.time.frame) + "." : "No earlier key."; }],
    nextKey: ["Next Key", (v) => { const t = v && v.tree; if (!t || !t.api) return "Open Forge first."; return t.api.stepKey(null, 1) ? "Frame " + Math.round(t.time.frame) + "." : "No later key."; }],
    rangeStart: ["Set Range Start", (v) => { const t = v && v.tree; if (!t) return "Open Forge first."; t.api.setRange(t.time.frame, t.time.end); return "Range " + t.time.start + "-" + t.time.end + "."; }],
    rangeEnd: ["Set Range End", (v) => { const t = v && v.tree; if (!t) return "Open Forge first."; t.api.setRange(t.time.start, t.time.frame); return "Range " + t.time.start + "-" + t.time.end + "."; }],
    graphEditor: ["Graph Editor", (v) => { const t = v && v.tree; if (!t || !t.api || !t.api.graphOpen) return "Open Forge first."; return "Graph Editor " + (t.api.graphOpen() ? "open" : "closed") + "."; }],
    animAutoKey: ["Auto Keyframe", (v) => { const t = v && v.tree; if (!t || !t.api) return "Open Forge first."; return "Auto Keyframe " + (t.api.setAutoKey() ? "on" : "off") + "."; }],
    keyLinear: ["Keys: Linear", (v) => forgeProInterp(v, "linear")],
    keySmooth: ["Keys: Smooth", (v) => forgeProInterp(v, "bezier")],
    keyStep: ["Keys: Step", (v) => forgeProInterp(v, "step")],
    copyAnim: ["Copy Animation", (v) => { const t = v && v.tree; if (!t || !t.api) return "Open Forge first."; const n = t.api.copyAnim(); return n ? "Copied " + n + " keys." : "Nothing is keyed here."; }],
    pasteAnim: ["Paste Animation", (v) => { const t = v && v.tree; if (!t || !t.api) return "Open Forge first."; if (!t.clipKeys) return "Copy some animation first."; t.api.undoChunk("paste animation", () => t.api.pasteAnim()); return "Pasted at frame " + Math.round(t.time.frame) + "."; }],
    mirrorKeysX: ["Mirror Keys across YZ", (v) => forgeProMirror(v, 0)],
    mirrorKeysY: ["Mirror Keys across XZ", (v) => forgeProMirror(v, 1)],
    mirrorKeysZ: ["Mirror Keys across XY", (v) => forgeProMirror(v, 2)],
    objComp: ["Object/Component", (v) => forgeProF8(v)],
    vertex: ["Vertex", (v) => forgeProComponents(v, "vert")],
    edge: ["Edge", (v) => forgeProComponents(v, "edge")],
    face: ["Face", (v) => forgeProComponents(v, "face")],
    objectMode: ["Object Mode", (v) => forgeProObjectMode(v)],
    uv: ["UV", null, "UV editing is not in Forge yet"],
    uvShell: ["UV Shell", null, "UV shells are not in Forge yet"],
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
    winMaterials: ["Material Maker (Materials workspace)", () => (typeof ForgeUVEditor !== "undefined" ? ForgeUVEditor.setWorkspace(ForgeUVEditor.workspace() === "mat" ? "model" : "mat") : forgeProPanel("materials"))],
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

// picking another tool in sculpt mode leaves it first, like the pro tools (owner 2026-10-22: sculpting "should feel
// like maya"); F8 (object / component) in sculpt mode just leaves it
const FORGE_PRO_LEAVE_SCULPT = /^(select|move|rotate|scale|showManip|lastTool|objComp|vertex|edge|face|uv|multiCut|softSel)$/;
async function forgeProRun(v, id) {
  const c = FORGE_PRO_CMDS[id];
  if (!c || !v) return;
  if (!c[1]) { proSay(c[0] + ": " + (c[2] || "not in Forge yet") + ".", true); return; }
  if (v.mode === "sculpt" && FORGE_PRO_LEAVE_SCULPT.test(id) && window.forgeSculptUI) {
    forgeSculptUI.exit();
    if (id === "objComp") return;
  }
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
  // sculpting: Shift + right button = the Mask menu (the plain right button is the brush wheel - one button, one menu)
  if (v.mode === "sculpt") return { title: "Mask", ring: { N: "maskInvert", S: "maskClear", E: "maskFill", W: "maskHideToggle", NE: "maskHide", NW: "maskShow" }, list: [] };
  if (ctx.key === "q") return { title: "Select", ring: { NW: "marquee", SE: "selectNone", E: "selectAll", W: "invert" }, list: [] };
  // hold r + left button: Scale's marking menu - flatten (scale to 0) on an axis, as Maya / Unreal do with 0 typed in
  if (ctx.key === "r") return { title: "Scale", ring: { W: "flattenX", N: "flattenY", E: "flattenZ", S: "flattenNormal", NW: "objectAxes", NE: "worldAxes" }, list: [] };
  if (ctx.key === "w" || ctx.key === "e") return { title: ctx.key === "w" ? "Move" : "Rotate", ring: { W: "worldAxes", NW: "objectAxes", N: "pivotEdit", S: "resetPivot" }, list: [] };
  if (ctx.ctrl) {                                   // convert the selection (polyConvertMM)
    return { title: "Convert", ring: { W: "vertex", N: "edge", S: "face", E: "toUV", NE: "grow", NW: "shrink", SE: "loopSel", SW: "ringSel" }, list: [] };
  }
  if (ctx.shift && typeof FORGE_MAYA !== "undefined") {   // Maya's contextPolyTools*MM, at Maya's compass places
    const mk = FORGE_MAYA.marking[comp ? (mode === "vert" ? "vertex" : mode === "edge" ? "edge" : "face") : ctx.node ? "object" : "empty"];
    return JSON.parse(JSON.stringify(mk));
  }
  if (ctx.node || comp) {                           // dagMenuProc: N Edge, W Vertex, S UV, E Face, SW VF, SE Shell, NW Multi, NE Object
    return { title: ctx.node ? ctx.node.name : "Components",
      ring: { N: "edge", W: "vertex", S: "uv", E: "face", SW: "loopSel", SE: "uvShell", NW: "ringSel", NE: "objectMode" },
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
  const labels = menu.labels || {};
  for (const [pos, id] of Object.entries(menu.ring)) {
    const a = FORGE_COMPASS[pos] * Math.PI / 180;
    if (id && typeof id === "object") {                // a wedge that opens a marking menu of its own (Maya's Face Normals ...)
      const b = proEl("button", "forge-pro-wedge forge-pro-wsub pos-" + pos.toLowerCase(), (labels[pos] || id.title || "") + " \u25b8");
      b.type = "button"; b.dataset.proSub = labels[pos] || id.title || ""; b.dataset.pos = pos;
      b.style.left = Math.round(Math.cos(a) * FORGE_PRO_R) + "px";
      b.style.top = Math.round(forgeProRingY(a)) + "px";
      b.addEventListener("click", (ev) => { ev.stopPropagation(); forgeProMarkRun(v, id, x + Math.cos(a) * FORGE_PRO_R, y + forgeProRingY(a)); });
      host.append(b);
      continue;
    }
    const c = FORGE_PRO_CMDS[id]; if (!c || !c[1]) continue;       // a wedge that does nothing is left out
    const text = labels[pos] || c[0];
    const b = proEl("button", "forge-pro-wedge pos-" + pos.toLowerCase(), text);
    b.type = "button"; b.dataset.proCmd = text; b.dataset.proId = id; b.dataset.pos = pos;
    b.style.left = Math.round(Math.cos(a) * FORGE_PRO_R) + "px";
    b.style.top = Math.round(forgeProRingY(a)) + "px";
    b.addEventListener("click", (ev) => { ev.stopPropagation(); forgeProMarkHide(); forgeProRun(v, id); });
    host.append(b);
  }
  if (menu.list && menu.list.length) {
    const list = proEl("div", "forge-pro-mlist");
    const ringed = Object.keys(menu.ring || {}).length > 0;
    list.classList.toggle("bare", !ringed);           // no ring (empty space): the list starts right at the pointer
    list.style.top = (ringed ? Math.round(FORGE_PRO_R * 1.15 + 24) : 6) + "px";
    // A list entry is an id, or ["Label", [ids]] for a submenu (the nested list the reference program's rings have:
    // one level deeper, with a Back row). A switch shows its tick, so it reads as a switch and not a command.
    const tickOf = (id) => {
      const st = FORGE_PRO_TOGGLES[id];
      let on = false;
      try { on = !!(st && v && st(v)); } catch (_) { on = false; }
      return on ? "\u2713" : "";
    };
    const row = (id, label) => {
      const c = FORGE_PRO_CMDS[id]; if (!c || !c[1]) return null;      // not in Forge yet: left out
      const b = proEl("button", "forge-pro-litem");
      b.type = "button"; b.dataset.proCmd = label || c[0]; b.dataset.proId = id;
      const t = tickOf(id);
      if (t) b.classList.add("on");
      b.append(proEl("span", "forge-pro-tick", t), proEl("span", "forge-pro-label", label || c[0]));
      b.addEventListener("click", (ev) => { ev.stopPropagation(); forgeProMarkHide(); forgeProRun(v, id); });
      return b;
    };
    const trail = [];
    const fill = (entries, backLabel) => {
      list.textContent = "";
      if (backLabel) {
        const back = proEl("button", "forge-pro-litem forge-back");
        back.type = "button"; back.dataset.proBack = "1";
        back.append(proEl("span", "forge-pro-tick", "\u25c2"), proEl("span", "forge-pro-label", backLabel));
        back.addEventListener("click", (ev) => { ev.stopPropagation(); const prev = trail.pop() || menu.list; fill(prev, trail.length ? "Back" : ""); });
        list.append(back);
      }
      for (const entry of entries) {
        if (Array.isArray(entry) && Array.isArray(entry[1])) {
          const sub = proEl("button", "forge-pro-litem forge-sub");
          sub.type = "button"; sub.dataset.proSub = entry[0];
          sub.append(proEl("span", "forge-pro-tick", "\u25b8"), proEl("span", "forge-pro-label", entry[0]));
          const kids = entry[1];
          sub.addEventListener("click", (ev) => { ev.stopPropagation(); trail.push(entries); fill(kids, "Back"); });
          list.append(sub);
          continue;
        }
        if (entry === "-" || (typeof entry === "string" && entry[0] === "#")) continue;
        const b = Array.isArray(entry) ? row(entry[0], entry[1]) : row(entry);
        if (b) list.append(b);
      }
    };
    fill(menu.list, "");
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
    if (r.bottom > window.innerHeight - 4) {
      // near the bottom the list goes ABOVE the ring - sliding it up over the ring put list items under the south wedge,
      // so a flick south picked "Draw it" instead of Cube. When it fits neither below nor above, it goes BESIDE the
      // ring (never over a wedge, owner 2026-10-25: the list covered the south chips)
      const ringed = !!Object.keys(menu.ring || {}).length;
      const above = ringed ? -(Math.round(FORGE_PRO_R * 1.15 + 24) + r.height) : -(r.height + 6);
      if (y + above >= 4) ml.style.top = above + "px";
      else if (ringed) {
        const side = Math.round(FORGE_PRO_R + 90);
        const right = x + side + r.width < window.innerWidth - 4;
        ml.style.left = (right ? side : -(side + r.width)) + "px";
        ml.style.top = Math.max(4 - y, Math.min(-r.height / 2, window.innerHeight - 4 - y - r.height)) + "px";
        ml.classList.add("beside");
      } else ml.style.top = (parseFloat(ml.style.top) - (r.bottom - window.innerHeight + 4)) + "px";
    }
    if (!ml.classList.contains("beside") && r.right > window.innerWidth - 4) ml.style.left = (-(r.right - window.innerWidth + 4)) + "px";
  }
  host._at = [x, y]; host._menu = menu;
}

function forgeProMarkHide() {
  const host = document.getElementById("forge-pro-marking");
  if (host) { host.hidden = true; host.textContent = ""; host._menu = null; }
}

// run what a marking menu pick means: a command, or - a sub-menu wedge - that wedge's own marking menu, opened where it
// is (it stays up for a click, like the pro tool's sub-menus after the button is let go)
function forgeProMarkRun(v, picked, x, y) {
  if (!picked) return;
  if (typeof picked === "object") { forgeProMarkShow(v, x, y, picked); return; }
  forgeProMarkHide();
  forgeProRun(v, picked);
}
// which wedge does a release at (x, y) mean? pro picks by DIRECTION once past the dead zone
function forgeProMarkPick(x, y) {
  const host = document.getElementById("forge-pro-marking");
  if (!host || host.hidden || !host._at) return null;
  const hit = document.elementFromPoint(x, y);
  if (hit && hit.dataset && hit.dataset.proId && host.contains(hit)) return hit.dataset.proId;
  if (hit && hit.dataset && hit.dataset.proSub && hit.dataset.pos && host.contains(hit)) return host._menu.ring[hit.dataset.pos];
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
  for (const b of host.querySelectorAll(".forge-pro-wsub")) b.classList.toggle("hot", !!id && typeof id === "object" && host._menu.ring[b.dataset.pos] === id);
}

// ================================================================== the hotbox (hold Space) - the pro layout
// the pro hotbox: rows of menu names centred on the mouse (the common menus above the middle, the modelling menu
// set below it), each opening its own list; "Recent Commands" first; the centre and the four zones around it
// open marking menus (press, flick, release). Every command in Forge is in here - the panels are optional.
// ================================================================== the menus, in one place
// Every menu is written down once here and the hotbox, the Space wheel and the window's menu bar all read it, so they
// cannot drift apart (they had: the hotbox knew no UV or Mesh Display menu). Forge's own commands only - a menu with
// nothing in it is a menu that lies about what the program can do.
// A menu is a TREE (owner 2026-10-22: "menus within menus within menus, everything should have a sub category that can
// get a sub category"). An entry is a command id, "-" (a separator), "#Heading" (a group title), or ["Label", [entries]]
// - a submenu, which may hold submenus of its own, to any depth. The menu bar cascades them sideways, the hotbox flies
// them out, the wheel and the marking lists drill in (with a Back row). forgeMenuFlat() walks a tree for its ids.
// Commands that are not in Forge yet are left out when a menu is drawn (a dead row is a row that lies).
// every command id in a menu tree, depth first (submenus included); "-" / "#..." skipped
function forgeMenuFlat(list, out) {
  out = out || [];
  for (const e of list || []) {
    if (Array.isArray(e)) { if (Array.isArray(e[1])) forgeMenuFlat(e[1], out); else if (e[0]) out.push(e[0]); }
    else if (typeof e === "string" && e && e !== "-" && e[0] !== "#") out.push(e);
  }
  return out;
}
// is this entry a submenu? (["Label", [...]]; a window row is ["id", "Label", fn])
const forgeMenuIsSub = (e) => Array.isArray(e) && Array.isArray(e[1]);
// does a command exist and work? (dead commands are left out of every menu)
const forgeMenuLive = (id) => { const c = typeof FORGE_PRO_CMDS !== "undefined" && FORGE_PRO_CMDS[id]; return !!(c && c[1]); };
// a submenu with nothing live inside is left out too
function forgeMenuSubLive(e) {
  const own = (l) => l.some((x) => (x && x.note) || (Array.isArray(x) && (Array.isArray(x[1]) ? own(x[1]) : typeof x[2] === "function")));
  return forgeMenuFlat(e[1]).some(forgeMenuLive) || own(e[1]);
}
window.forgeMenuFlat = forgeMenuFlat;
const FORGE_PRO_MENUS = {
  // the main menu bar - the order and the shape of a 3D program's own bar
  File: ["save", ["Export", ["saveObj", "export"]], "-", "close"],
  Edit: ["undo", "redo", "repeatLast", "-", ["Duplicate", ["duplicate", "duplicateT"]], ["Grouping", ["group", "ungroup"]],
    ["Parenting", ["parent", "unparent"]], "-", ["Delete", ["delete", ["Delete by Type", ["deleteHistory"]]]]],
  Create: [["Polygon Primitives", ["cube", "sphere", "cylinder", "cone", "plane", "torus", "quadsphere"]],
    ["Image Planes", ["imagePlane", "image"]], "-", ["Make with LOKI", ["draw", "describe", "creature"]]],
  Select: ["selectAll", "selectNone", "invert", "hierarchy", "marquee", "-",
    ["Components", ["objComp", "vertex", "edge", "face", "uv", "uvShell"]],
    ["Grow and Shrink", ["grow", "shrink"]], ["Loops and Rings", ["loopSel", "ringSel"]]],
  Modify: [["Transform Tools", ["select", "move", "rotate", "scale", "lastTool", "showManip"]],
    ["Axes", ["worldAxes", "objectAxes"]], ["Pivot", ["centerPivot", "resetPivot", "pivotEdit"]],
    ["Transformations", ["freeze", "resetXf"]], "-", "makeLive", ["Snap", ["snapGrid", "snapEdge", "snapPoint"]]],
  Display: [["Visibility", ["hideToggle", ["Hide", ["hide", "hideOthers"]], ["Show", ["show", "showLast", "showAll"]], "isolate"]],
    ["Display Layers", ["layerEditor", "layerAdd", "layerAssign"]], ["Smooth Mesh Preview", ["smooth1", "smooth2", "smooth3"]],
    ["Viewport", ["quadToggle", "xray", "grid"]], ["Polygons", ["softHard", "iveToggle", ["Normals", ["faceNormals", "vertexNormals", "softHardDisplay"]]]]],
  Windows: [["Workspaces", ["wsModel", "wsSculpt", "wsUv", "wsRetopo", "wsBake", "wsMat", "wsAnim"]],
    ["Panels", ["winOutliner", "winChannel", "winCreate", "winMaterials", "winShelf", "winToolkit", "winCreature", "panelModel", "panelMaterials"]],
    ["Menus", ["wheel", "quickMenu"]], ["Layouts", ["layouts", "layoutReset", "hideUI"]],
    ["Settings / Preferences", ["preferences", "hotkeyEditor", "menuSettings"]]],
  Help: ["hotkeyEditor", "preferences", "more"],
  // the panel menus (they belong to a view, not to the program - the row above the main menus, as in the reference)
  View: [["Cameras", ["persp", "top", "front", "side", "defaultView"]], ["Frame", ["frameAll", "frameSel"]], ["Layout", ["single", "four"]]],
  Shading: [["Draw Mode", ["wire", "shaded", "textured"]], ["Smooth Preview", ["smooth1", "smooth2", "smooth3"]], "xray", ["Matcap", ["matcapNext", "matcapPrev"]]],
  Lighting: ["lights"],
  Show: [["Visibility", ["hideToggle", ["Hide", ["hide", "hideOthers"]], ["Show", ["show", "showLast", "showAll"]], "isolate"]],
    ["Viewport", ["grid", "quadToggle", "xray"]], "softSel"],
  Renderer: ["renderDialog", "renderPreview", "-", "renderStudio", "bakeMaps"],
  Panels: [["Windows", ["winOutliner", "winChannel", "winCreate", "winMaterials", "winShelf", "winToolkit", "panelModel", "panelMaterials"]],
    ["Layout", ["single", "four", "hideUI"]]],
  // the menu sets' menus (Mesh, Edit Mesh, Mesh Tools, Mesh Display, UV, Key, Playback, Sculpt, Render) and Maya's
  // main menus come from FORGE_MAYA below - Maya 2027's order and labels (app/ui/forge_maya_layout.js, generated)
};
// Forge laid out like Maya 2027 (owner 2026-10-22: "almost 1:1 to maya"): every main and menu-set menu as Maya has it,
// built by tools/forge_maya/gen_layout.py from Maya's own layout (docs/forge/maya2027_layout.json)
if (typeof FORGE_MAYA !== "undefined") for (const [name, items] of Object.entries(FORGE_MAYA.menus)) FORGE_PRO_MENUS[name] = items;
// the row above the middle: the panel menus, then the main menus (the order the reference uses)
const FORGE_PRO_BAR = ["View", "Shading", "Lighting", "Show", "Renderer", "Panels"];
const FORGE_PRO_MAIN = ["File", "Edit", "Create", "Select", "Modify", "Display", "Windows", "Help"];
// the middle row's right-hand button
const FORGE_PRO_CONTROLS = ["hideUI", "wheel", "hotkeyEditor", "preferences"];
// the menu sets: which menus the rows under the middle show. A program's own set is the first one.
const FORGE_PRO_SETS = (typeof FORGE_MAYA !== "undefined") ? FORGE_MAYA.sets : {
  modeling: { label: "Modeling", menus: ["Mesh", "Edit Mesh", "Mesh Tools", "Mesh Display", "UV"] } };
// the hotbox's rows are the same menus, four to a row (the window's menu bar shows them in one line)
const FORGE_PRO_SET_ROWS = (key) => {
  const m = ((FORGE_PRO_SETS[key] || FORGE_PRO_SETS.modeling).menus) || [];
  const rows = [];
  for (let i = 0; i < m.length; i += 4) rows.push(m.slice(i, i + 4));
  return rows.length ? rows : [[]];
};
const FORGE_PRO_SET_STORE = "loki-forge-menuset";
// Maya starts in Modeling (F2); the old all-in-one "Forge" set is gone - a stored "forge" comes back as Modeling
let FORGE_PRO_SET = (() => { try { const k = localStorage.getItem(FORGE_PRO_SET_STORE); return FORGE_PRO_SETS[k] ? k : "modeling"; } catch (exc) { return "modeling"; } })();
// every menu, in a stable order - the Space wheel, the tear-off bar and the window's menu bar walk this
const FORGE_PRO_ROWS = FORGE_PRO_MAIN.concat(FORGE_PRO_BAR,
  [...new Set(Object.values(FORGE_PRO_SETS).flatMap((st) => st.menus))]).filter((n) => FORGE_PRO_MENUS[n]).map((n) => [n, FORGE_PRO_MENUS[n]]);
// the menus of the set that is showing, kept small enough for the wheel's ring
const FORGE_PRO_WHEEL_MENUS = () => {
  const menus = (FORGE_PRO_SETS[FORGE_PRO_SET] || FORGE_PRO_SETS.modeling).menus || [];
  return ["Recent Commands"].concat(menus).slice(0, 12).map((n) => [n, n === "Recent Commands" ? [] : FORGE_PRO_MENUS[n]]);
};

// the five zones (HotboxCenter/North/South/East/WestMenu.mel)
// the five zones, as Maya's HotboxCenter/North/South/East/WestMenu lay them out (forge_maya_layout.js)
const FORGE_PRO_ZONES = (typeof FORGE_MAYA !== "undefined") ? FORGE_MAYA.zones : {
  center: { title: "Views", ring: { N: "persp", W: "top", S: "front", E: "side" } } };
// commands that are switches: the hotbox shows a tick when they are on
const FORGE_PRO_TOGGLES = {
  snapGrid: (v) => !!v.pro.snap.grid, snapEdge: (v) => !!v.pro.snap.edge, snapPoint: (v) => !!v.pro.snap.point,
  grid: (v) => !!(v.pro.grid && v.pro.grid.visible), xray: (v) => !!(v.edit && v.edit.xray),
  softSel: (v) => !!(v.edit && v.edit.prop), wire: (v) => !!v.wire, textured: (v) => !v.clay, quadToggle: (v) => !!v.quad,
  winOutliner: () => forgeProPanels().outliner, winChannel: () => forgeProPanels().channel, winCreate: () => forgeProPanels().create,
  winMaterials: () => { try { return localStorage.getItem("loki-forge-workspace") === "mat"; } catch (_) { return false; } }, winShelf: () => forgeProPanels().shelf, winToolkit: () => forgeProPanels().toolkit,
};

function forgeProItem(id, host, label) {
  const c = FORGE_PRO_CMDS[id];
  if (!c) return null;
  const b = proEl("button", "forge-pro-item" + (c[1] ? "" : " off"));
  b.type = "button"; b.dataset.proCmd = c[0]; b.dataset.proId = id;
  const key = typeof fmyKeyOf === "function" ? fmyKeyOf(id) : (typeof FMY_KEYS !== "undefined" && FMY_KEYS[id]) || "";
  b.append(proEl("span", "forge-pro-tick", ""), proEl("span", "forge-pro-label", label || c[0]), proEl("span", "forge-pro-key", key));
  if (!c[1]) b.title = c[2] || "";
  b.addEventListener("pointerdown", (ev) => ev.stopPropagation());
  b.addEventListener("click", (ev) => { ev.stopPropagation(); const v = forge.view; host._used = true; forgeProHotboxHide(); if (v) forgeProRun(v, id); });
  return b;
}

// a hotbox list: commands, separators and submenus (["Label", [entries]]) that fly out beside their row, to any depth
function forgeProFillList(list, entries, host, depth) {
  let sep = false;
  for (const e of entries || []) {
    if (e === "-") { sep = !!list.querySelector(".forge-pro-item"); continue; }
    if (typeof e === "string" && e[0] === "#") continue;
    let b = null;
    if (forgeMenuIsSub(e)) {
      if (!forgeMenuSubLive(e)) continue;
      b = proEl("button", "forge-pro-item forge-pro-subitem");
      b.type = "button"; b.dataset.proSub = e[0];
      b.setAttribute("aria-haspopup", "menu");
      b.append(proEl("span", "forge-pro-tick", ""), proEl("span", "forge-pro-label", e[0]), proEl("span", "forge-pro-key", "\u25b8"));
      const open = () => {
        forgeProFlyClose(host, depth);
        for (const x of list.querySelectorAll(".forge-pro-subitem.open")) x.classList.remove("open");
        b.classList.add("open");
        const fly = proEl("div", "forge-pro-list forge-pro-fly");
        fly.dataset.depth = String(depth + 1); fly.dataset.sub = e[0];
        fly.addEventListener("pointerdown", (ev) => ev.stopPropagation());
        forgeProFillList(fly, e[1], host, depth + 1);
        host.append(fly);
        const r = b.getBoundingClientRect(), w = fly.getBoundingClientRect().width;
        // to the right; flipped left only when it would lose more than a third of itself (a small nudge keeps the
        // cascade reading left-to-right instead of folding back over the menus it came from)
        const over = r.right + w + 4 - window.innerWidth;
        fly.style.left = Math.round(over <= w / 3 ? Math.min(r.right, window.innerWidth - w - 4) : r.left - w) + "px";
        fly.style.top = Math.round(r.top - 3) + "px";
        forgeProFit(fly);
        forgeProHotboxRefresh(forge.view, fly);
      };
      b.addEventListener("pointerenter", () => { clearTimeout(host._flyT); host._flyT = setTimeout(open, 110); });
      b.addEventListener("pointerleave", () => clearTimeout(host._flyT));
      b.addEventListener("pointerdown", (ev) => ev.stopPropagation());
      b.addEventListener("click", (ev) => { ev.stopPropagation(); clearTimeout(host._flyT); open(); });
    } else {
      const id = Array.isArray(e) ? e[0] : e;
      if (!forgeMenuLive(id)) continue;                  // not in Forge yet: left out
      b = forgeProItem(id, host, Array.isArray(e) && typeof e[1] === "string" ? e[1] : "");
      if (!b) continue;
      b.addEventListener("pointerenter", () => { clearTimeout(host._flyT); host._flyT = setTimeout(() => { forgeProFlyClose(host, depth); for (const x of list.querySelectorAll(".forge-pro-subitem.open")) x.classList.remove("open"); }, 160); });
    }
    if (sep) { list.append(proEl("div", "forge-pro-sep")); sep = false; }
    list.append(b);
  }
}
function forgeProFlyClose(host, depth) {
  for (const f of (host || document).querySelectorAll(".forge-pro-fly")) if ((+f.dataset.depth || 0) > depth) f.remove();
}
// how much of the window's top the fixed title strip (LOKI's mode tabs, app/ui/modebar.js, z-index 50) covers. It is
// drawn OVER the hotbox (z-index 45), so a floating list that is nudged to the very top would sit under it and could
// not be clicked (owner idea I5: "hotbox > Windows > OpenChannelsLayers can't be clicked: covered by titlestrip-side").
// Menus keep clear of it. 0 when there is no strip (LOKI_TITLEBAR=native, tests about Forge alone).
function forgeTopInset() {
  if (typeof document === "undefined" || !document.documentElement.classList.contains("has-titlestrip")) return 0;
  const h = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--titlebar-h"));
  return h > 0 ? h : 0;
}

// keep a floating list inside the window: nudge it back on screen and let a long one scroll
function forgeProFit(el, box) {
  if (!el || el.hidden) return;
  // the space it may use: the window (under the title strip), or a clipping parent (the wheel lives inside the
  // viewport, which clips it)
  const b = box || { left: 0, top: forgeTopInset(), right: window.innerWidth, bottom: window.innerHeight };
  el.style.translate = "";
  el.style.maxHeight = Math.max(120, (b.bottom - b.top) - 12) + "px";
  el.style.overflowY = "auto";
  const r = el.getBoundingClientRect();
  let dx = 0, dy = 0;
  if (r.right > b.right - 4) dx = (b.right - 4) - r.right;
  if (r.left + dx < b.left + 4) dx = b.left + 4 - r.left;
  if (r.bottom > b.bottom - 4) dy = (b.bottom - 4) - r.bottom;
  if (r.top + dy < b.top + 4) dy = b.top + 4 - r.top;
  if (dx || dy) el.style.translate = Math.round(dx) + "px " + Math.round(dy) + "px";
}

// the middle row's menu-set button: Forge / Modeling / Sculpting / Animation / Rendering, remembered per machine
function forgeProSetCol() {
  const col = proEl("section", "forge-pro-col forge-pro-setcol"); col.dataset.menu = "Menu Set";
  const h = proEl("button", "forge-pro-head forge-pro-sethead", (FORGE_PRO_SETS[FORGE_PRO_SET] || {}).label || "Forge");
  h.type = "button"; h.dataset.proSetBtn = FORGE_PRO_SET;
  h.title = "The menu set: which menus the rows under the middle show.";
  const list = proEl("div", "forge-pro-list"); list.hidden = true;
  for (const key of Object.keys(FORGE_PRO_SETS)) {
    const b = proEl("button", "forge-pro-item");
    b.type = "button"; b.dataset.proSet = key;
    b.append(proEl("span", "forge-pro-tick", key === FORGE_PRO_SET ? "\u2713" : ""), proEl("span", "forge-pro-label", FORGE_PRO_SETS[key].label), proEl("span", "forge-pro-key", ""));
    b.addEventListener("click", (ev) => { ev.stopPropagation(); forgeProSetTo(key); });
    list.append(b);
  }
  h.addEventListener("pointerdown", (ev) => { ev.stopPropagation(); list.hidden = !list.hidden; });
  h.addEventListener("pointerenter", () => { if (list.hidden) return; list.hidden = false; });
  col.append(h, list);
  return col;
}
function forgeProSetApply(host) {
  host = host || document.getElementById("forge-pro-hotbox");
  if (!host) return;
  host.dataset.set = FORGE_PRO_SET;
  for (const r of host.querySelectorAll(".forge-pro-row[data-set]")) {
    const show = r.dataset.set === FORGE_PRO_SET;
    if (r.hidden === show) r.hidden = !show;
  }
  const head = host.querySelector(".forge-pro-sethead");
  if (head && head.textContent !== (FORGE_PRO_SETS[FORGE_PRO_SET] || {}).label) { head.textContent = (FORGE_PRO_SETS[FORGE_PRO_SET] || {}).label || "Forge"; head.dataset.proSetBtn = FORGE_PRO_SET; }
  const btn = host.querySelector("[data-pro-set-btn]");
  if (btn) btn.dataset.proSetBtn = FORGE_PRO_SET;
  for (const b of host.querySelectorAll(".forge-pro-item[data-pro-set]")) {
    const on = b.dataset.proSet === FORGE_PRO_SET;
    b.classList.toggle("on", on);
    const t = b.querySelector(".forge-pro-tick");
    if (t && t.textContent !== (on ? "\u2713" : "")) t.textContent = on ? "\u2713" : "";
  }
}
function forgeProSetTo(key) {
  if (!FORGE_PRO_SETS[key]) return;
  FORGE_PRO_SET = key;
  try { localStorage.setItem(FORGE_PRO_SET_STORE, key); } catch (exc) { /* private mode */ }
  forgeProSetApply();
  if (typeof fmyBuildMenubar === "function") fmyBuildMenubar();       // the window's menu bar shows the same set
  const sel = document.getElementById("fmy-menuset");
  if (sel && sel.value !== key) sel.value = key;
  const v = forge.view;
  if (v && v.pro) v.pro.recent = (v.pro.recent || []);       // nothing else to rebuild: the rows are all there
}
// the menu sets as commands (F2 / F4 / F6, as in Maya; Sculpting is Forge's own)
for (const [k, label] of [["Modeling", "modeling"], ["Animation", "animation"], ["Rendering", "rendering"], ["Sculpting", "sculpting"]]) {
  FORGE_PRO_CMDS["menuSet" + k] = [k + " Menu Set", () => { forgeProSetTo(label); return k + " menus."; }];
}
window.forgeMenuSet = (key) => { if (key == null) return FORGE_PRO_SET; forgeProSetTo(key); return FORGE_PRO_SET; };

function forgeProHotboxHost() {
  let host = document.getElementById("forge-pro-hotbox");
  if (host) return host;
  const sheet = document.getElementById("forge");
  if (!sheet) return null;
  host = proEl("div", "forge-pro-hotbox");
  host.id = "forge-pro-hotbox"; host.hidden = true;
  host.setAttribute("role", "menu");
  const mkCol = (head, ids) => {
    const col = proEl("section", "forge-pro-col");
    col.dataset.menu = head;
    const h = proEl("button", "forge-pro-head", head);
    h.type = "button";
    const list = proEl("div", "forge-pro-list");
    list.hidden = true;
    forgeProFillList(list, ids, host, 0);
    // calm menus (owner 2026-10-21: holding Space the menus "glitch ... jittering"): a menu opens when the mouse
    // RESTS on its name (a short hover intent) or at once on a press - sweeping across the row no longer flips every
    // menu open and shut - and nothing is rewritten when it is already that way.
    const open = () => {
      clearTimeout(host._intent);
      forgeProFlyClose(host, -1);
      for (const l of host.querySelectorAll(".forge-pro-list:not(.forge-pro-fly)")) { const hide = l !== list; if (l.hidden !== hide) l.hidden = hide; }
      for (const x of host.querySelectorAll(".forge-pro-head")) { const on = x === h; if (x.classList.contains("open") !== on) x.classList.toggle("open", on); }
      // the open menu's row goes on top (its list was drawn under the next row's menu names) and the list stays on screen
      for (const r of host.querySelectorAll(".forge-pro-row")) r.classList.toggle("has-open", r === col.parentElement);
      forgeProFit(list);
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
    return col;
  };
  // the rows, top to bottom: the panel menus, the main menus, the middle (Recent Commands | the menu set | Hotbox
  // Controls) and then the menus of the set that is showing - the shape the reference program's hotbox has.
  // top to bottom: the panel menus, the main menus, the middle row (Recent Commands | the menu set | Hotbox
  // Controls), and then the showing set's menus. The rows ladder away from the centre, which stays empty so a press
  // there still opens the zone marking menus.
  const mkRow = (side, i) => { const r = proEl("div", "forge-pro-row " + side); r.style.setProperty("--row-i", String(i)); return r; };
  const panelRow = mkRow("up", 2);
  for (const name of FORGE_PRO_BAR) if (FORGE_PRO_MENUS[name]) panelRow.append(mkCol(name, FORGE_PRO_MENUS[name]));
  const mainRow = mkRow("up", 1);
  for (const name of FORGE_PRO_MAIN) if (FORGE_PRO_MENUS[name]) mainRow.append(mkCol(name, FORGE_PRO_MENUS[name]));
  const centre = mkRow("up", 0);
  centre.dataset.mid = "1";
  centre.append(mkCol("Recent Commands", []), forgeProSetCol(), mkCol("Hotbox Controls", FORGE_PRO_CONTROLS));
  const setRows = [];
  for (const key of Object.keys(FORGE_PRO_SETS)) {
    FORGE_PRO_SET_ROWS(key).forEach((names, i) => {
      const r = mkRow("down", i); r.dataset.set = key; r.dataset.menurow = String(i);
      for (const name of names) if (FORGE_PRO_MENUS[name]) r.append(mkCol(name, FORGE_PRO_MENUS[name]));
      setRows.push(r);
    });
  }
  const labels = proEl("div", "forge-pro-zones");
  for (const [z, t] of [["north", "Layouts"], ["south", "Panels"], ["east", "UI"], ["west", "Selection"]]) labels.append(proEl("span", "z-" + z, t));
  const box = proEl("div", "forge-pro-hbbox");
  box.append(panelRow, mainRow, centre, ...setRows, labels);
  host.append(box);
  forgeProSetApply(host);
  // a press in a zone (not on a menu) opens its marking menu; releasing picks by direction
  host.addEventListener("pointerdown", (ev) => {
    if (ev.target.closest(".forge-pro-col, .forge-pro-fly")) return;
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
    if (host.hidden || !host.dataset.pinned || (ev.target.closest && ev.target.closest("#forge-pro-hotbox .forge-pro-col, #forge-pro-hotbox .forge-pro-fly"))) return;
    ev.preventDefault(); ev.stopPropagation(); forgeProHotboxHide();
  }, true);
  window.addEventListener("pointermove", (ev) => { if (host._zone) forgeProMarkHover(ev.clientX, ev.clientY); });
  window.addEventListener("pointerup", (ev) => {
    if (!host._zone) return;
    host._zone = null;
    const id = forgeProMarkPick(ev.clientX, ev.clientY);
    forgeProHotboxHide();
    if (id && typeof id === "object") { forgeProMarkRun(forge.view, id, ev.clientX, ev.clientY); return; }
    forgeProMarkHide();
    if (id) forgeProRun(forge.view, id);
  });
  document.body.append(host);                     // not inside the sheet: its transform would shift fixed positions
  return host;
}

function forgeProHotboxRefresh(v, host) {        // ticks on the switches, and the Recent Commands list
  for (const b of host.querySelectorAll(".forge-pro-item")) {
    if (!b.dataset.proId) continue;                       // the menu-set items tick for themselves
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
  // submenus drill in: the list shows the submenu with a Back row on top (a stack, so it goes as deep as the menu does)
  const body = proEl("div", "forge-wheel-body");
  sub.append(body);
  const stack = [];
  const fill = (entries, title) => {
    body.textContent = "";
    sub.firstChild.textContent = title;
    if (stack.length) {
      const back = proEl("button", "forge-wheel-item forge-back");
      back.type = "button"; back.dataset.proBack = "1";
      back.append(proEl("span", "forge-pro-tick", "\u25c2"), proEl("span", "", "Back"));
      back.addEventListener("click", (ev) => { ev.stopPropagation(); const prev = stack.pop(); fill(prev[0], prev[1]); });
      body.append(back);
    }
    let n = 0;
    for (const e of entries) {
      if (e === "-" || (typeof e === "string" && e[0] === "#")) continue;
      if (forgeMenuIsSub(e)) {
        if (!forgeMenuSubLive(e)) continue;
        const b = proEl("button", "forge-wheel-item forge-wheel-subitem");
        b.type = "button"; b.dataset.proSub = e[0];
        b.append(proEl("span", "forge-pro-tick", "\u25b8"), proEl("span", "", e[0]));
        b.addEventListener("click", (ev) => { ev.stopPropagation(); stack.push([entries, title]); fill(e[1], e[0]); });
        body.append(b); n++;
        continue;
      }
      const id = Array.isArray(e) ? e[0] : e;
      const c = FORGE_PRO_CMDS[id];
      if (!c || !c[1]) continue;
      const b = proEl("button", "forge-wheel-item");
      b.type = "button"; b.dataset.proId = id;
      let on = false;
      try { on = !!(FORGE_PRO_TOGGLES[id] && FORGE_PRO_TOGGLES[id](v)); } catch (_) { on = false; }
      b.append(proEl("span", "forge-pro-tick", on ? "\u2713" : ""), proEl("span", "", c[0]));
      b.classList.toggle("on", on);
      b.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const view = forge.view;
        host._used = true;
        forgeProWheelClose();
        if (view) forgeProRun(view, id);
      });
      body.append(b); n++;
    }
    if (!n) body.append(proEl("span", "forge-wheel-subtitle", "Nothing yet"));
    if (sub.isConnected) forgeProFit(sub, host.parentElement && host.parentElement.getBoundingClientRect());
  };
  fill(ids, head);
  // the menu opens OUTWARD from its wedge, its nearest edge just past it, so it never covers the ring
  const cx = Math.cos(angle), cy = Math.sin(angle);
  const ex = Math.cos(angle) * (FORGE_PRO_WHEEL_R + 48), ey = Math.sin(angle) * (FORGE_PRO_WHEEL_R * 0.74 + 22);
  sub.style.left = Math.round(ex) + "px";
  sub.style.top = Math.round(ey) + "px";
  sub.style.transform = Math.abs(cx) >= Math.abs(cy)
    ? (cx > 0 ? "translate(0, -50%)" : "translate(-100%, -50%)")
    : (cy > 0 ? "translate(-50%, 0)" : "translate(-50%, -100%)");
  host.append(sub);
  forgeProFit(sub, host.parentElement && host.parentElement.getBoundingClientRect());
  host.dataset.open = head;
}

function forgeProWheelOpen(v, at) {
  const host = forgeProWheelHost();
  if (!host) return;
  host.textContent = "";
  host._used = false;
  const menus = (typeof FORGE_PRO_WHEEL_MENUS === "function" ? FORGE_PRO_WHEEL_MENUS() : FORGE_PRO_ROWS);
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
    if (r.hidden || !r.offsetParent) continue;                 // a hidden set's rows are 0x0: they would skew this
    const b = r.getBoundingClientRect();
    lo = Math.min(lo, b.left); hi = Math.max(hi, b.right); top = Math.min(top, b.top); bot = Math.max(bot, b.bottom);
  }
  if (lo < 6) x += 6 - lo; else if (hi > window.innerWidth - 6) x -= hi - (window.innerWidth - 6);
  if (top < 6) y += 6 - top; else if (bot > window.innerHeight - 6) y -= bot - (window.innerHeight - 6);
  place();
}

function forgeProHotboxHide() {
  const host = document.getElementById("forge-pro-hotbox");
  if (host) { clearTimeout(host._intent); clearTimeout(host._flyT); forgeProFlyClose(host, -1); host._dragFrom = null; host.hidden = true; delete host.dataset.pinned; }
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
  const hit = ray.intersectObjects(t.pickables({ select: true }), false)[0];   // R / T layers: the click goes through
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
    if (t.layerNorm && (!t.layerNorm(n) || t.layersLocked(id))) continue;   // hidden or R / T layers: the box goes through
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
// The camera modifier. Option / Alt is the classic one; the owner (2026-10-21: "maya is hold down command and drag to
// move in the viewport") also navigates with Command, so both do it. One predicate, used by every tool, so none of
// them can disagree about whether the camera or the tool has the drag.
// the camera gesture: Maya / Unreal = Alt (Option) or Cmd + a button; "mmb" (Settings > Navigation) = the middle
// button alone (Shift / Ctrl change what it does), the Blender-style way
const forgeNavStyle = () => (window.ForgeSettings ? ForgeSettings.get("navStyle") : "maya");
const forgeNav = (k) => { const v = window.ForgeSettings ? +ForgeSettings.get(k) : 1; return Number.isFinite(v) && v > 0 ? v : 1; };
function forgeCamMod(e) {
  if (!e) return false;
  if (forgeNavStyle() === "mmb") return e.button === 1 || (e.type !== "pointerdown" && e.type !== "mousedown" && !!(e.buttons & 4));
  return !!(e.altKey || e.metaKey);
}
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
    if (!forgeCamMod(e) || view.quad) return;
    const both = drag && drag.buttons !== e.buttons;
    e.preventDefault(); e.stopImmediatePropagation();
    if (both) { drag.kind = "dolly"; drag.buttons = e.buttons; return; }   // left + middle = dolly
    let kind = e.button === 0 ? "tumble" : e.button === 1 ? "track" : e.button === 2 ? "dolly" : null;
    if (forgeNavStyle() === "mmb") kind = e.button !== 1 ? null : e.shiftKey ? "track" : (e.ctrlKey || e.metaKey) ? "dolly" : "tumble";
    if (!kind) return;
    // box zoom is the camera modifier + Ctrl (Maya's Ctrl + Option + left on macOS), so Command alone is free to
    // tumble - the owner asked for exactly that
    if (kind === "tumble" && e.ctrlKey) kind = "box";
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
    if (drag.kind === "tumble") cam.tumble(dx * forgeNav("tumbleSpeed"), dy * forgeNav("tumbleSpeed"));
    else if (drag.kind === "track") cam.track(dx * forgeNav("trackSpeed"), dy * forgeNav("trackSpeed"));
    else if (drag.kind === "dolly") cam.dolly((dx + dy) * FORGE_CAM_DOLLY * forgeNav("dollySpeed"));
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
    const inv = window.ForgeSettings && ForgeSettings.get("invertWheel") ? -1 : 1;
    cam.dolly(-e.deltaY * unit * FORGE_CAM_WHEEL * forgeNav("wheelSpeed") * inv);
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
    if (e.button !== 0 || forgeCamMod(e)) return;         // every view, the four-view layout included (Ziva)
    const held = ["q", "w", "e", "r"].find((k) => pro.held.has(k));
    if (held && view.mode !== "sculpt") {               // hold q / w / e / r + left button: that tool's marking menu
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
      if (id && typeof id === "object") { forgeProMarkRun(view, id, e.clientX, e.clientY); return; }
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
    if (e.button !== 2 || forgeCamMod(e)) return;         // every view, the four-view layout included
    e.preventDefault();
    if (view.mode === "sculpt" && !e.shiftKey) return;   // sculpting: the right button is the brush wheel (forge_sculpt_ui.js)
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
    if (id && typeof id === "object") { forgeProMarkRun(view, id, e.clientX, e.clientY); return; }
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
    const k = e.key, mod = e.ctrlKey || e.metaKey;
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
    // from the Hotkey Editor). One table, so no key can mean two things (the hard-coded fallback switch is gone).
    const chord = forgeKeyChord(e), act = forgeKeyAction(chord);
    if (!act) return;                                          // unbound: Ctrl/Cmd+S, C, V ... stay the app's
    const hold = forgeHotkeys.hold(act);
    if (hold && !e.repeat) { m.held.add(hold); (m.holdCodes = m.holdCodes || {})[e.code || k] = hold; }
    if (act.startsWith("@") && !e.repeat) (m.holdActs = m.holdActs || {})[e.code || k] = act;
    if (e.repeat && !forgeHotkeys.repeats(act)) { take(e); return; }
    return forgeProKeyAct(v, act, e, take, run);
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
    case "@viewUndo": v.viewUndo(); return;
    case "@viewRedo": v.viewRedo(); return;
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
  const toPairs = (menu) => Object.values(menu.ring).filter((id) => typeof id === "string" && FORGE_PRO_CMDS[id]).map((id) => [FORGE_PRO_CMDS[id][0], () => forgeProRun(v, id)]);
  return { object: toPairs(forgeProMenu(v, { node: v && forgeProTree(v) ? forgeProTree(v).active() : null })),
           shift: toPairs(forgeProMenu(v, { shift: true })), ctrl: toPairs(forgeProMenu(v, { ctrl: true })) };
}
