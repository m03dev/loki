// Forge, the way Maya works: Maya's hotkeys, its marking menus (by context, released by direction), the
// Space-bar hotbox with its zones, the Space tap between one and four views, Maya's Alt/Option camera, pick-walk,
// pivot editing (d / Insert) and the rest of docs/FORGE_MAYA_SPEC.md - which was read off Maya 2027 itself.
// (owner 2026-10-19: "maya is my love I want it exactly on here ... the hotkeys especially the movement command
// control option shift")
//
// Maya's interaction DESIGN, re-written for a web canvas: no Autodesk code, MEL, art or icons are used.
// Ctrl and Cmd are the same key here (Maya binds both on the Mac); Alt is Option.
// Hotkeys: Maya is the default set; Blender's edit-mode keys (forge_model.js) come back with "Hotkeys: Classic"
// in the hotbox (Edit > Hotkey set), saved per machine.
"use strict";

const FORGE_MAYA_R = 104;          // marking-menu ring radius, px
const FORGE_MAYA_DEAD = 22;        // px from the centre before a direction counts (Maya's dead zone)
const FORGE_MAYA_HOLD = 85;        // ms of hold before the menu opens; a plain click opens it too and leaves it
const FORGE_MAYA_TAP = 230;        // a Space press shorter than this, with nothing chosen, is a tap
const FORGE_KEYMAP_STORE = "loki-forge-keymap";
const FORGE_COMPASS = { N: -90, NE: -45, E: 0, SE: 45, S: 90, SW: 135, W: 180, NW: -135 };

function forgeKeymap() {
  try { return localStorage.getItem(FORGE_KEYMAP_STORE) === "blender" ? "blender" : "maya"; } catch (_) { return "maya"; }
}
function forgeSetKeymap(k) {
  try { localStorage.setItem(FORGE_KEYMAP_STORE, k === "blender" ? "blender" : "maya"); } catch (_) { /* private mode */ }
  const v = typeof forge !== "undefined" && forge.view;
  if (v && v.maya && v.maya.buttons) v.maya.buttons();
  return forgeKeymap();
}

function mayaEl(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
const mayaSay = (t, bad) => { if (t && typeof forgeSay === "function") forgeSay(t, bad); };

// ================================================================== the commands (menus, hotbox, hotkeys share them)
// each returns a short note for the status line, or "" / undefined for silence
function forgeMayaTree(v) { return v && v.tree && v.tree.api; }
function forgeMayaComp(v) { return !!(v && v.mode === "poly"); }

function forgeMayaTool(v, mode) {                 // q / w / e / r
  const t = forgeMayaTree(v);
  if (v.maya) v.maya.tool = mode;
  if (forgeMayaComp(v)) { if (v.setTool) v.setTool(mode); return ""; }
  if (!mode) { if (v.transform && v.transform.object) v.transform.detach(); if (v.gizmo && v.gizmo.object) v.gizmo.detach(); v.dirty = true; return "Select"; }
  if (t && t.attachTool) t.attachTool(mode); else v.toggleTransform(mode);
  for (const b of document.querySelectorAll("#forge .forge-transform")) b.classList.toggle("on", true);
  return "";
}

async function forgeMayaComponents(v, sel) {      // F9 / F10 / F11, or a component wedge on an object
  const t = forgeMayaTree(v);
  const n = t && t.active();
  if (n && !n.root && n.kind === "mesh") t.makeWorking(n.id);
  if (!forgeMayaComp(v) && typeof forgeModelMode === "function") await forgeModelMode(true);
  if (sel && v.setSelMode) v.setSelMode(sel);
  return "";
}
async function forgeMayaObjectMode(v) {
  if (forgeMayaComp(v) && typeof forgeModelMode === "function") await forgeModelMode(false);
  return "Object mode.";
}
async function forgeMayaF8(v) { return forgeMayaComp(v) ? forgeMayaObjectMode(v) : forgeMayaComponents(v, null); }

async function forgeMayaSculpt(v) {
  const t = forgeMayaTree(v), n = t && t.active();
  if (n && !n.root && n.kind === "mesh") t.makeWorking(n.id);
  if (forgeMayaComp(v)) await forgeMayaObjectMode(v);
  if (v.mode !== "sculpt" && typeof forgeMode === "function") forgeMode();
  return "";
}

function forgeMayaFrame(v, all) {
  const t = forgeMayaTree(v);
  if (forgeMayaComp(v) || !t) { v.frame(); return ""; }
  const ids = all || !t.selected().length ? t.allIds() : t.selected();
  if (v.rememberView) v.rememberView();
  v.frameBox(t.worldBox(ids));
  return "";
}

function forgeMayaView(v, name) {
  if (v.quad) v.setLook("quad", false);
  if (v.rememberView) v.rememberView();
  v.setView(name);
  return { persp: "Perspective", top: "Top", front: "Front", side: "Side" }[name] + " view.";
}

function forgeMayaLook(v, what, on) {
  v.setLook(what, !!on);
  return what === "wire" ? (on ? "Wireframe (4)." : "Shaded (5).") : "";
}

function forgeMayaIsolate(v) {                     // Ctrl+1: show only the selection, again to come back
  const t = forgeMayaTree(v);
  if (!t) return "";
  const m = v.maya;
  if (m.isolated) { t.show(m.isolated); m.isolated = null; return "Isolate off."; }
  if (!t.selected().length) return "Select something to isolate.";
  t.hideUnselected(); m.isolated = v.tree.hiddenLast.slice();
  return "Isolate select (Ctrl+1 again to come back).";
}

function forgeMayaNudge(v, dx, dy) {               // Alt + arrows: a small step along the screen
  const t = forgeMayaTree(v);
  if (!t || forgeMayaComp(v) || !t.selected().length) return "";
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
function forgeMayaPivotMode(v, on) {
  const t = forgeMayaTree(v), m = v.maya, tc = v.transform;
  if (!t || !tc || forgeMayaComp(v)) return "";
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

function forgeMayaSpace(v, space) {                // w / e + left button: World / Object
  const tc = v.transform;
  if (tc && tc.setSpace) tc.setSpace(space === "world" ? "world" : "local");
  if (v.gizmo && v.gizmo.setSpace) v.gizmo.setSpace(space === "world" ? "world" : "local");
  return space === "world" ? "Axes: World." : "Axes: Object.";
}

function forgeMayaSnap(v, kind, on) {              // x (grid) and j (step) while held
  const tcs = [v.transform, v.gizmo].filter((x) => x && x.setTranslationSnap);
  const step = Math.pow(10, Math.round(Math.log10(Math.max(v.size || 1, 1e-3) / 10)));
  for (const tc of tcs) {
    if (kind === "grid") tc.setTranslationSnap(on ? step : null);
    if (kind === "step") { tc.setTranslationSnap(on ? step : null); tc.setRotationSnap(on ? Math.PI / 12 : null); tc.setScaleSnap(on ? 0.1 : null); }
  }
  return "";
}

function forgeMayaManipSize(v, bigger) {
  for (const tc of [v.transform, v.gizmo]) if (tc && tc.setSize) tc.setSize(Math.max(0.2, Math.min(4, (tc.size || 1) * (bigger ? 1.25 : 0.8))));
  v.dirty = true;
  return "";
}

const forgeMayaHas = (name) => typeof window[name] === "function";
const forgeMayaCall = (name, ...a) => (forgeMayaHas(name) ? window[name](...a) : undefined);

// the command table: id -> [label, run(v)] ; `null` run = not in Forge yet (shown greyed, with why)
function forgeMayaCommands() {
  const T = (v) => forgeMayaTree(v);
  const comp = forgeMayaComp;
  return {
    select: ["Select", (v) => forgeMayaTool(v, null)],
    move: ["Move", (v) => forgeMayaTool(v, "translate")],
    rotate: ["Rotate", (v) => forgeMayaTool(v, "rotate")],
    scale: ["Scale", (v) => forgeMayaTool(v, "scale")],
    lastTool: ["Last Tool", (v) => forgeMayaTool(v, v.maya.lastTool || "translate")],
    undo: ["Undo", (v) => { v.undo(); if (T(v)) v.tree.build(); }],
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
    isolate: ["Isolate Select", (v) => forgeMayaIsolate(v)],
    selectAll: ["Select All", (v) => { if (comp(v)) v.selectAll(true); else T(v).selectAll(); }],
    selectNone: ["Select None", (v) => { if (comp(v)) v.selectAll(false); else T(v).selectNone(); }],
    invert: ["Invert Selection", (v) => { if (comp(v)) v.selectInvert(); else T(v).invertSelection(); }],
    hierarchy: ["Select Hierarchy", (v) => { T(v).selectHierarchy(); }],
    grow: ["Grow Selection", (v) => { if (comp(v)) v.selectGrow(true); }],
    shrink: ["Shrink Selection", (v) => { if (comp(v)) v.selectGrow(false); }],
    delete: ["Delete", (v) => { if (comp(v)) forgeMayaCall("forgeFaceOp", "delete"); else { const k = T(v).removeSelected(); return k ? "Deleted." : "The object being edited stays - select another, or empty it."; } }],
    frameSel: ["Frame Selection", (v) => forgeMayaFrame(v, false)],
    frameAll: ["Frame All", (v) => forgeMayaFrame(v, true)],
    defaultView: ["Default View", (v) => { forgeMayaView(v, "persp"); forgeMayaFrame(v, true); return ""; }],
    persp: ["Perspective", (v) => forgeMayaView(v, "persp")],
    top: ["Top", (v) => forgeMayaView(v, "top")],
    front: ["Front", (v) => forgeMayaView(v, "front")],
    side: ["Side", (v) => forgeMayaView(v, "side")],
    single: ["Single View", (v) => { v.setLook("quad", false); return "One view."; }],
    four: ["Four View", (v) => { v.setLook("quad", true); return "Four views."; }],
    wire: ["Wireframe", (v) => forgeMayaLook(v, "wire", true)],
    shaded: ["Shaded", (v) => forgeMayaLook(v, "wire", false)],
    textured: ["Textured", (v) => { v.setLook("clay", !v.clay); return v.clay ? "Clay (6 again for colours)." : "Colours and textures."; }],
    lights: ["Next Light", (v) => "Light: " + v.nextLight()],
    centerPivot: ["Center Pivot", (v) => (T(v).centerPivot() ? "Pivot centred." : "")],
    resetPivot: ["Reset Pivot", (v) => (T(v).resetPivot() ? "Pivot back on the object's origin." : "")],
    pivotEdit: ["Edit Pivot", (v) => forgeMayaPivotMode(v, null)],
    freeze: ["Freeze Transformations", (v) => (T(v).freeze() ? "Frozen: reads 0 / 0 / 1, nothing moved." : "")],
    resetXf: ["Reset Transformations", (v) => (T(v).resetTransform() ? "Back to 0 / 0 / 1." : "")],
    channelBox: ["Channel Box", (v) => (T(v).toggleChannelBox() ? "Channel Box on (Ctrl+A)." : "Channel Box off (Ctrl+A).")],
    outliner: ["Outliner", () => { const o = document.getElementById("forge-outliner"); if (o) o.hidden = !o.hidden; return ""; }],
    objComp: ["Object/Component", (v) => forgeMayaF8(v)],
    vertex: ["Vertex", (v) => forgeMayaComponents(v, "vert")],
    edge: ["Edge", (v) => forgeMayaComponents(v, "edge")],
    face: ["Face", (v) => forgeMayaComponents(v, "face")],
    objectMode: ["Object Mode", (v) => forgeMayaObjectMode(v)],
    uv: ["UV", null, "UV editing is not in Forge yet"],
    vertexFace: ["Vertex Face", null, "Vertex faces are not in Forge yet"],
    uvShell: ["UV Shell", null, "UV shells are not in Forge yet"],
    multi: ["Multi", null, "Multi-component selection is not in Forge yet"],
    extrude: ["Extrude", async (v) => { if (!comp(v)) await forgeMayaComponents(v, "face"); forgeMayaCall("forgeFaceOp", "extrude"); }],
    inset: ["Inset", (v) => forgeMayaCall("forgeFaceOp", "inset")],
    reverse: ["Reverse Normals", (v) => forgeMayaCall("forgeFaceOp", "flip")],
    smooth: ["Smooth", (v) => forgeMayaCall("forgeFaceOp", "smooth")],
    dynamesh: ["DynaMesh", () => forgeMayaCall("forgeDynamesh")],
    sculpt: ["Sculpt Tool", (v) => forgeMayaSculpt(v)],
    deleteComp: ["Delete Components", () => forgeMayaCall("forgeFaceOp", "delete")],
    bevel: ["Bevel", null, "Bevel is not in Forge yet."],
    edgeLoop: ["Insert Edge Loop", null, "Insert Edge Loop is not in Forge yet (T8)"],
    multiCut: ["Multi-Cut", null, "Multi-Cut is not in Forge yet (T8)"],
    merge: ["Merge", null, "Merge is not in Forge yet (T8)"],
    fillHole: ["Fill Hole", null, "Fill Hole is not in Forge yet (T8)"],
    softHard: ["Soften/Harden", null, "Soft/hard edges are not in Forge yet"],
    chamfer: ["Chamfer Vertex", null, "Chamfer is not in Forge yet (T8)"],
    poke: ["Poke Face", null, "Poke is not in Forge yet (T8)"],
    wedge: ["Wedge", null, "Wedge is not in Forge yet"],
    toUV: ["To UVs", null, "UVs are not in Forge yet"],
    loopSel: ["To Edge Loop", null, "Alt+click an edge selects a loop"],
    ringSel: ["To Edge Ring", null, "Edge rings are not on a menu yet"],
    cube: ["Cube", () => forgeMayaCall("forgeAddPrimitive", "cube")],
    sphere: ["Sphere", () => forgeMayaCall("forgeAddPrimitive", "sphere")],
    cylinder: ["Cylinder", () => forgeMayaCall("forgeAddPrimitive", "cylinder")],
    cone: ["Cone", () => forgeMayaCall("forgeAddPrimitive", "cone")],
    plane: ["Plane", () => forgeMayaCall("forgeAddPrimitive", "plane")],
    torus: ["Torus", () => forgeMayaCall("forgeAddPrimitive", "torus")],
    quadsphere: ["Quad Sphere", () => forgeMayaCall("forgeAddPrimitive", "quadsphere")],
    draw: ["Draw it", () => forgeMayaCall("forgeWay", "draw")],
    image: ["From an image", () => forgeMayaCall("forgeWay", "image")],
    describe: ["Describe it", () => forgeMayaCall("forgeWay", "describe")],
    creature: ["Creature", () => forgeMayaCall("forgeWay", "creature")],
    save: ["Save .glb", () => { document.querySelector('#forge-exportbar [data-icon="save"]')?.click(); }],
    close: ["Close Forge", () => forgeMayaCall("forgeClose")],
    panelModel: ["Model panel", () => forgeMayaCall("forgeSide", "make")],
    panelMaterials: ["Materials", () => forgeMayaCall("forgeSide", "materials")],
    worldAxes: ["World", (v) => forgeMayaSpace(v, "world")],
    objectAxes: ["Object", (v) => forgeMayaSpace(v, "local")],
    marquee: ["Marquee", () => "Drag a box to select (Shift toggles, Ctrl/Cmd removes)."],
    keysMaya: ["Hotkeys: Forge", () => { forgeSetKeymap("maya"); return "Hotkey set: Forge (the default)."; }],
    keysBlender: ["Hotkeys: Classic", () => { forgeSetKeymap("blender"); return "Hotkey set: Classic (G/R/S, 1/2/3, middle-drag turns)."; }],
    more: ["More...", (v) => { forgeMayaHotboxOpen(v); }],
    sculptModel: ["Sculpt/Model", () => forgeMayaCall("forgeMode")],
    quadToggle: ["Quad view", (v) => { v.setLook("quad", !v.quad); return v.quad ? "Four views." : "One view."; }],
    makeLive: ["Edit this mesh", (v) => { const t = T(v), n = t.active(); return n && t.makeWorking(n.id) ? n.name + " is the one the tools edit now." : ""; }],
  };
}
const FORGE_MAYA_CMDS = forgeMayaCommands();

async function forgeMayaRun(v, id) {
  const c = FORGE_MAYA_CMDS[id];
  if (!c || !v) return;
  if (!c[1]) { mayaSay(c[0] + ": " + (c[2] || "not in Forge yet") + ".", true); return; }
  let note = "";
  try { note = await c[1](v); } catch (exc) { mayaSay(c[0] + " could not run: " + exc.message, true); return; }
  if (v.maya && !/^(undo|redo|select|lastTool)$/.test(id)) v.maya.last = id;     // g repeats this
  if (v.maya && /^(move|rotate|scale)$/.test(id)) v.maya.lastTool = { move: "translate", rotate: "rotate", scale: "scale" }[id];
  if (v.tree) v.tree.build();
  mayaSay(note || "");
}

// ================================================================== marking menus (Maya's compass layout)
// a menu: { title, ring: { N: id, NE: id, ... }, list: [id, ...] }
function forgeMayaMenu(v, ctx) {
  const comp = forgeMayaComp(v), mode = v.edit ? v.edit.mode : "face";
  if (ctx.key === "q") return { title: "Select", ring: { NW: "marquee", SE: "selectNone", E: "selectAll", W: "invert" }, list: [] };
  if (ctx.key === "w" || ctx.key === "e") return { title: ctx.key === "w" ? "Move" : "Rotate", ring: { W: "worldAxes", NW: "objectAxes", N: "pivotEdit", S: "resetPivot" }, list: [] };
  if (ctx.ctrl) {                                   // convert the selection (polyConvertMM)
    return { title: "Convert", ring: { W: "vertex", N: "edge", S: "face", E: "toUV", NE: "grow", NW: "shrink", SE: "loopSel", SW: "ringSel" }, list: [] };
  }
  if (ctx.shift) {
    if (comp && mode === "vert") return { title: "Vertex tools", ring: { S: "extrude", E: "chamfer", SW: "deleteComp", N: "merge", NE: "smooth", W: "multiCut" }, list: ["grow", "shrink"] };
    if (comp && mode === "edge") return { title: "Edge tools", ring: { S: "extrude", E: "bevel", SW: "deleteComp", N: "merge", NE: "edgeLoop", W: "multiCut" }, list: ["grow", "shrink"] };
    if (comp) return { title: "Face tools", ring: { S: "extrude", E: "bevel", SW: "wedge", NE: "poke", SE: "reverse", W: "multiCut", NW: "inset" }, list: ["deleteComp", "smooth", "grow", "shrink"] };
    if (ctx.node) return { title: "Mesh tools", ring: { S: "extrude", SW: "edgeLoop", NE: "fillHole", N: "merge", W: "multiCut", NW: "sculpt", E: "softHard" }, list: ["smooth", "dynamesh", "makeLive"] };
    return { title: "Create", ring: { NE: "quadsphere", E: "sphere", SE: "torus", S: "cube", SW: "cone", W: "cylinder", NW: "plane" }, list: ["draw", "image", "describe", "creature"] };
  }
  if (ctx.node || comp) {                           // dagMenuProc: N Edge, W Vertex, S UV, E Face, SW VF, SE Shell, NW Multi, NE Object
    return { title: ctx.node ? ctx.node.name : "Components",
      ring: { N: "edge", W: "vertex", S: "uv", E: "face", SW: "vertexFace", SE: "uvShell", NW: "multi", NE: "objectMode" },
      list: ["select", "move", "rotate", "scale", "frameSel", "hierarchy", "invert", "duplicate", "group", "centerPivot", "resetPivot",
        "resetXf", "freeze", "makeLive", "delete", "more"] };
  }
  return { title: "View", ring: { N: "persp", W: "top", S: "front", E: "side", NE: "four", NW: "single" },
    list: ["selectAll", "selectNone", "frameAll", "defaultView", "wire", "shaded", "quadToggle", "lights", "undo", "redo", "more"] };
}

function forgeMayaMarkHost() {
  let host = document.getElementById("forge-maya-marking");
  if (host) return host;
  host = mayaEl("div", "forge-maya-marking");
  host.id = "forge-maya-marking"; host.hidden = true;
  host.setAttribute("role", "menu");
  document.body.append(host);
  return host;
}

function forgeMayaMarkShow(v, x, y, menu) {
  const host = forgeMayaMarkHost();
  host.textContent = "";
  host.append(mayaEl("span", "forge-maya-hub", menu.title || ""));
  for (const [pos, id] of Object.entries(menu.ring)) {
    const c = FORGE_MAYA_CMDS[id]; if (!c) continue;
    const a = FORGE_COMPASS[pos] * Math.PI / 180;
    const b = mayaEl("button", "forge-maya-wedge pos-" + pos.toLowerCase() + (c[1] ? "" : " off"), c[0]);
    b.type = "button"; b.dataset.mayaCmd = c[0]; b.dataset.mayaId = id; b.dataset.pos = pos;
    if (!c[1]) b.title = c[2] || "Not in Forge yet";
    b.style.left = Math.round(Math.cos(a) * FORGE_MAYA_R) + "px";
    b.style.top = Math.round(Math.sin(a) * FORGE_MAYA_R * 0.82) + "px";
    b.addEventListener("click", (ev) => { ev.stopPropagation(); forgeMayaMarkHide(); forgeMayaRun(v, id); });
    host.append(b);
  }
  if (menu.list && menu.list.length) {
    const list = mayaEl("div", "forge-maya-mlist");
    list.style.top = Math.round(FORGE_MAYA_R * 0.82 + 30) + "px";
    for (const id of menu.list) {
      const c = FORGE_MAYA_CMDS[id]; if (!c) continue;
      const b = mayaEl("button", "forge-maya-litem" + (c[1] ? "" : " off"), c[0]);
      b.type = "button"; b.dataset.mayaCmd = c[0]; b.dataset.mayaId = id;
      b.addEventListener("click", (ev) => { ev.stopPropagation(); forgeMayaMarkHide(); forgeMayaRun(v, id); });
      list.append(b);
    }
    host.append(list);
  }
  host.style.left = Math.round(x) + "px";
  host.style.top = Math.round(y) + "px";
  host.dataset.set = menu.title || "";
  host.hidden = false;
  host._at = [x, y]; host._menu = menu;
}

function forgeMayaMarkHide() {
  const host = document.getElementById("forge-maya-marking");
  if (host) { host.hidden = true; host.textContent = ""; host._menu = null; }
}

// which wedge does a release at (x, y) mean? Maya picks by DIRECTION once past the dead zone
function forgeMayaMarkPick(x, y) {
  const host = document.getElementById("forge-maya-marking");
  if (!host || host.hidden || !host._at) return null;
  const hit = document.elementFromPoint(x, y);
  if (hit && hit.dataset && hit.dataset.mayaId && host.contains(hit)) return hit.dataset.mayaId;
  const dx = x - host._at[0], dy = y - host._at[1];
  if (Math.hypot(dx, dy) < FORGE_MAYA_DEAD) return null;
  const ang = Math.atan2(dy, dx) * 180 / Math.PI;
  let best = null, bestD = 999;
  for (const pos of Object.keys(host._menu.ring)) {
    let d = Math.abs(((ang - FORGE_COMPASS[pos]) + 540) % 360 - 180);
    if (d < bestD) { bestD = d; best = host._menu.ring[pos]; }
  }
  return bestD <= 30 ? best : null;
}
function forgeMayaMarkHover(x, y) {
  const host = document.getElementById("forge-maya-marking");
  if (!host || host.hidden) return;
  const id = forgeMayaMarkPick(x, y);
  for (const b of host.querySelectorAll("[data-maya-id]")) b.classList.toggle("hot", b.dataset.mayaId === id);
}

// ================================================================== the hotbox (hold Space)
const FORGE_MAYA_ROWS = [
  ["File", ["save", "close"]],
  ["Edit", ["undo", "redo", "sculptModel", "duplicate", "duplicateT", "group", "ungroup", "parent", "unparent", "delete", "keysMaya", "keysBlender"]],
  ["Create", ["cube", "sphere", "cylinder", "cone", "plane", "torus", "quadsphere", "draw", "image", "describe", "creature"]],
  ["Select", ["selectAll", "selectNone", "invert", "hierarchy", "grow", "shrink"]],
  ["Modify", ["select", "move", "rotate", "scale", "centerPivot", "resetPivot", "pivotEdit", "freeze", "resetXf", "frameSel", "makeLive"]],
  ["Display", ["wire", "shaded", "textured", "quadToggle", "lights", "hide", "showLast", "hideOthers", "showAll", "isolate"]],
  ["Mesh", ["smooth", "dynamesh", "sculpt"]],
  ["Edit Mesh", ["extrude", "inset", "reverse", "deleteComp", "bevel", "multiCut"]],
  ["Windows", ["outliner", "channelBox", "panelModel", "panelMaterials"]],
];
// the five zones (HotboxCenter/North/South/East/WestMenu.mel)
const FORGE_MAYA_ZONES = {
  center: { title: "Views", ring: { N: "persp", W: "top", S: "front", E: "side" } },
  north: { title: "Layouts", ring: { N: "single", E: "four", S: "outliner" } },
  south: { title: "Panels", ring: { N: "outliner", E: "panelMaterials", W: "panelModel", S: "channelBox" } },
  east: { title: "UI", ring: { N: "outliner", E: "channelBox", S: "panelModel" } },
  west: { title: "Selection mode", ring: { NW: "objComp", NE: "hierarchy", SW: "face", N: "vertex", W: "edge" } },
};

function forgeMayaHotboxHost() {
  let host = document.getElementById("forge-maya-hotbox");
  if (host) return host;
  const sheet = document.getElementById("forge");
  if (!sheet) return null;
  host = mayaEl("div", "forge-maya-hotbox");
  host.id = "forge-maya-hotbox"; host.hidden = true;
  host.setAttribute("role", "menu");
  const grid = mayaEl("div", "forge-maya-grid");
  for (const [head, ids] of FORGE_MAYA_ROWS) {
    const col = mayaEl("section", "forge-maya-col");
    col.append(mayaEl("h4", "forge-maya-head", head));
    const list = mayaEl("div", "forge-maya-list");
    for (const id of ids) {
      const c = FORGE_MAYA_CMDS[id]; if (!c) continue;
      const b = mayaEl("button", "forge-maya-item" + (c[1] ? "" : " off"), c[0]);
      b.type = "button"; b.dataset.mayaCmd = c[0]; b.dataset.mayaId = id;
      if (!c[1]) b.title = c[2] || "";
      b.addEventListener("pointerdown", (ev) => ev.stopPropagation());
      b.addEventListener("click", (ev) => { ev.stopPropagation(); const v = forge.view; host._used = true; forgeMayaHotboxHide(); if (v) forgeMayaRun(v, id); });
      list.append(b);
    }
    col.append(list); grid.append(col);
  }
  host.append(grid);
  const hub = mayaEl("div", "forge-maya-zonehub", "Views");
  hub.title = "Press here for the views (Perspective / Top / Front / Side); above, below, left and right of it are the other zones.";
  host.append(hub);
  // a press in a zone opens its marking menu; releasing picks by direction
  host.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0 || ev.target.closest(".forge-maya-item")) return;
    ev.preventDefault();
    const c = host._center || [window.innerWidth / 2, window.innerHeight / 2];
    const dx = ev.clientX - c[0], dy = ev.clientY - c[1];
    const zone = Math.abs(dx) < 70 && Math.abs(dy) < 34 ? "center" : Math.abs(dy) > Math.abs(dx) ? (dy < 0 ? "north" : "south") : (dx < 0 ? "west" : "east");
    host._used = true;
    host._zone = zone;
    forgeMayaMarkShow(forge.view, ev.clientX, ev.clientY, FORGE_MAYA_ZONES[zone]);
  });
  window.addEventListener("pointermove", (ev) => { if (host._zone) forgeMayaMarkHover(ev.clientX, ev.clientY); });
  window.addEventListener("pointerup", (ev) => {
    if (!host._zone) return;
    host._zone = null;
    const id = forgeMayaMarkPick(ev.clientX, ev.clientY);
    forgeMayaMarkHide(); forgeMayaHotboxHide();
    if (id) forgeMayaRun(forge.view, id);
  });
  sheet.append(host);
  return host;
}

// ================================================================== the Space wheel (floats at the mouse)
// Owner, 2026-10-20: "i want the space bar menue to float where my mouse is just like maya not a newhud its
// like a wheel and when you hover over it brings down a new menue". So Space opens a wheel AT THE POINTER, and
// hovering a wedge brings that menu down beside it. The wedges are the same nine menus the hotbox uses and the
// commands come from FORGE_MAYA_CMDS, so the two surfaces can never drift apart; the last wedge opens the full
// hotbox for anyone who wants Maya's whole five-zone layout, so nothing was taken away.
const FORGE_MAYA_WHEEL_R = 106;

function forgeMayaWheelHost() {
  let host = document.getElementById("forge-maya-wheel");
  if (host) return host;
  const stage = document.getElementById("forge-stage");
  if (!stage) return null;
  host = mayaEl("div", "forge-maya-wheel");
  host.id = "forge-maya-wheel"; host.hidden = true;
  host.setAttribute("role", "menu");
  stage.append(host);
  return host;
}

function forgeMayaWheelSub(v, head, ids, angle) {
  const host = document.getElementById("forge-maya-wheel");
  if (!host) return;
  const old = host.querySelector(".forge-wheel-sub");
  if (old) old.remove();
  const sub = mayaEl("div", "forge-wheel-sub");
  sub.dataset.head = head;
  sub.append(mayaEl("span", "forge-wheel-subtitle", head));
  for (const id of ids) {
    const c = FORGE_MAYA_CMDS[id];
    if (!c) continue;
    const b = mayaEl("button", "forge-wheel-item" + (c[1] ? "" : " off"), c[0]);
    b.type = "button"; b.dataset.mayaId = id;
    if (!c[1]) b.title = c[2] || "";
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (!c[1]) return;
      const view = forge.view;
      host._used = true;
      forgeMayaWheelClose();
      if (view) forgeMayaRun(view, id);
    });
    sub.append(b);
  }
  const b2 = mayaEl("button", "forge-wheel-item forge-wheel-more", "All menus (the full menu grid)");
  b2.type = "button";
  b2.addEventListener("click", (ev) => { ev.stopPropagation(); host._used = true; forgeMayaWheelClose(); forgeMayaHotboxOpen(v, host._at); });
  sub.append(b2);
  const r2 = FORGE_MAYA_WHEEL_R + 58;
  sub.style.left = Math.round(Math.cos(angle) * r2) + "px";
  sub.style.top = Math.round(Math.sin(angle) * r2) + "px";
  host.append(sub);
  host.dataset.open = head;
}

function forgeMayaWheelOpen(v, at) {
  const host = forgeMayaWheelHost();
  if (!host) return;
  host.textContent = "";
  const menus = FORGE_MAYA_ROWS.concat([["Panels", ["outliner", "channelBox", "panelModel", "panelMaterials"]]]);
  const n = menus.length;
  host.append(mayaEl("span", "forge-wheel-hub", "Space"));
  menus.forEach(([head, ids], i) => {
    const a = (-Math.PI / 2) + (i * 2 * Math.PI) / n;
    const b = mayaEl("button", "forge-wheel-wedge", head);
    b.type = "button"; b.dataset.mayaHead = head;
    b.style.left = Math.round(Math.cos(a) * FORGE_MAYA_WHEEL_R) + "px";
    b.style.top = Math.round(Math.sin(a) * FORGE_MAYA_WHEEL_R) + "px";
    b.addEventListener("mouseenter", () => forgeMayaWheelSub(v, head, ids, a));
    b.addEventListener("click", (ev) => { ev.stopPropagation(); forgeMayaWheelSub(v, head, ids, a); });
    host.append(b);
  });
  host.addEventListener("click", (ev) => { if (ev.target === host) forgeMayaWheelClose(); });
  const c = at || (v && v.maya && v.maya.mouse) || [window.innerWidth / 2, window.innerHeight / 2];
  const rect = (host.parentElement || document.body).getBoundingClientRect();
  host._at = c;
  host.style.left = Math.round(c[0] - rect.left) + "px";     // where the mouse is
  host.style.top = Math.round(c[1] - rect.top) + "px";
  host.hidden = false;
}

function forgeMayaWheelClose() {
  const host = document.getElementById("forge-maya-wheel");
  if (host) { host.hidden = true; host.textContent = ""; delete host.dataset.open; }
}

function forgeMayaWheelOpenNow() {
  const wh = document.getElementById("forge-maya-wheel");
  return !!(wh && !wh.hidden);
}

function forgeMayaHotboxOpen(v, at) {
  const host = forgeMayaHotboxHost();
  if (!host) return;
  const c = at || (v && v.maya && v.maya.mouse) || [window.innerWidth / 2, window.innerHeight / 2];
  host._center = c; host._used = false;
  const hub = host.querySelector(".forge-maya-zonehub");
  if (hub) { hub.style.left = Math.round(c[0]) + "px"; hub.style.top = Math.round(c[1]) + "px"; }
  host.hidden = false;
}

function forgeMayaHotboxHide() {
  const host = document.getElementById("forge-maya-hotbox");
  if (host) { host.hidden = true; delete host.dataset.pinned; }
}

// a Space tap: one view <-> four views; a tap over a pane of the four maximises that pane
function forgeMayaTap(v) {
  const m = v.maya;
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
function forgeMayaPickAt(v, x, y) {               // the node under the screen point (x, y), or null
  const t = forgeMayaTree(v);
  if (!t || !v.canvas || !v.camera) return null;
  const THREE = v.THREE, r = v.canvas.getBoundingClientRect();
  v.camera.updateMatrixWorld();
  const ray = new THREE.Raycaster();
  ray.setFromCamera(new THREE.Vector2(((x - r.left) / r.width) * 2 - 1, -((y - r.top) / r.height) * 2 + 1), v.camera);
  const hit = ray.intersectObjects(t.pickables(), false)[0];
  return hit ? t.nodeOfObject(hit.object) : null;
}

function forgeMayaBoxPick(v, x0, y0, x1, y1) {     // nodes whose middle is inside a screen box
  const t = forgeMayaTree(v);
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
// Maya's modifiers: Shift toggles, Ctrl/Cmd removes, Ctrl/Cmd+Shift adds
const forgeMayaHow = (e) => ((e.ctrlKey || e.metaKey) && e.shiftKey ? "add" : (e.ctrlKey || e.metaKey) ? "remove" : e.shiftKey ? "toggle" : "set");

// ================================================================== attach to a viewer
function forgeMayaAttach(view, ctx) {
  const { THREE, canvas, controls } = ctx;
  const maya = view.maya = { timer: 0, at: null, down: false, last: null, open: false, saved: null, controls: controls,
    held: new Set(), mouse: null, spaceAt: 0, tool: null, lastTool: "translate", isolated: null };
  if (!canvas || !controls) return maya;
  const defaults = Object.assign({}, controls.mouseButtons);

  // the buttons: Maya - Alt/Option + left / middle / right = tumble / track / dolly; without Alt the left button
  // selects and the right button is the marking menu. Blender keeps the viewer's own orbit buttons.
  const buttons = maya.buttons = () => {
    const mb = controls.mouseButtons;
    if (forgeKeymap() !== "maya") {
      if (maya.altOn) return;
      Object.assign(mb, defaults);
      if (view.mode === "poly") mb.MIDDLE = THREE.MOUSE.ROTATE;
      mb.RIGHT = null;                                   // the marking menu still owns the right button
      return;
    }
    if (maya.altOn) {
      mb.LEFT = view.cam && view.cam !== "persp" ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
      mb.MIDDLE = THREE.MOUSE.PAN;
      mb.RIGHT = THREE.MOUSE.DOLLY;
    } else { mb.LEFT = null; mb.MIDDLE = null; mb.RIGHT = null; }
  };
  const mayaAlt = maya.alt = (on) => {
    on = !!on;
    if (on === !!maya.altOn) return;
    maya.altOn = on;
    if (on) { maya.saved = Object.assign({}, controls.mouseButtons); Object.assign(controls.mouseButtons, { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.DOLLY }); if (view.cam && view.cam !== "persp") controls.mouseButtons.LEFT = THREE.MOUSE.PAN; }
    else { maya.saved = null; buttons(); }
  };
  buttons();
  const setMode = view.setMode;
  view.setMode = (m) => { setMode(m); buttons(); };   // forge_edit puts orbit on the middle button in poly mode

  // ------------------------------------------------ left button: select (click / Shift / Ctrl / box), q/w/e + left = menu
  const box = mayaEl("div", "forge-marquee"); box.hidden = true;
  canvas.parentElement.append(box);
  let gest = null;
  canvas.addEventListener("pointerdown", (e) => {
    maya.mouse = [e.clientX, e.clientY];
    if (e.button !== 0 || e.altKey || forgeKeymap() !== "maya") return;
    const held = ["q", "w", "e"].find((k) => maya.held.has(k));
    if (held && view.mode !== "sculpt") {               // hold q / w / e + left button: that tool's marking menu
      e.preventDefault(); e.stopImmediatePropagation();
      maya.open = "key";
      forgeMayaMarkShow(view, e.clientX, e.clientY, forgeMayaMenu(view, { key: held }));
      return;
    }
    if (view.mode !== "view") return;                    // sculpt strokes and component picking own the button there
    const tc = view.transform;
    if (tc && tc.object && tc.axis) return;            // the handle
    gest = { at: [e.clientX, e.clientY], how: forgeMayaHow(e), box: false, id: e.pointerId };
  }, { capture: true });
  canvas.addEventListener("pointermove", (e) => {
    maya.mouse = [e.clientX, e.clientY];
    if (maya.open) { forgeMayaMarkHover(e.clientX, e.clientY); return; }
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
    if (maya.open === "key") {
      maya.open = false;
      const id = forgeMayaMarkPick(e.clientX, e.clientY);
      forgeMayaMarkHide();
      if (id) forgeMayaRun(view, id);
      return;
    }
    if (!gest) return;
    const g = gest; gest = null; box.hidden = true;
    const t = forgeMayaTree(view);
    if (!t) return;
    if (g.box) { t.selectMany(forgeMayaBoxPick(view, g.at[0], g.at[1], e.clientX, e.clientY), g.how === "set" ? "set" : g.how); return; }
    const n = forgeMayaPickAt(view, e.clientX, e.clientY);
    if (n) t.select(n.id, g.how);
    else if (g.how === "set") t.selectNone();
  };
  canvas.addEventListener("pointerup", endLeft);
  window.addEventListener("pointerup", (e) => { if (maya.open === "key") endLeft(e); });

  // ------------------------------------------------ right button: hold and a marking menu opens, picked by direction
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 2 || e.altKey) return;              // every view, the four-view layout included
    maya.down = true; maya.at = [e.clientX, e.clientY];
    const how = { shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey };
    window.clearTimeout(maya.timer);
    maya.timer = window.setTimeout(() => {
      if (!maya.down) return;
      const node = view.mode === "view" ? forgeMayaPickAt(view, maya.at[0], maya.at[1]) : null;
      const t = forgeMayaTree(view);
      if (node && t && !how.shift && !how.ctrl && !t.selected().includes(node.id)) t.select(node.id);
      maya.open = "right";
      forgeMayaMarkShow(view, maya.at[0], maya.at[1], forgeMayaMenu(view, Object.assign({ node: node }, how)));
    }, FORGE_MAYA_HOLD);
  });
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  const endRight = (e) => {
    if (e.button !== 2) return;
    maya.down = false; window.clearTimeout(maya.timer);
    if (maya.open === "pinned") return;                   // already open from an earlier click: leave it
    if (maya.open === "right") {                          // it was showing: a flick picks by direction
      maya.open = false;
      const id = forgeMayaMarkPick(e.clientX, e.clientY);
      forgeMayaMarkHide();
      if (id) forgeMayaRun(view, id);
      return;
    }
    // a quick click opens the menu and leaves it open (a click is enough; you do not have to hold)
    const at = maya.at || [e.clientX, e.clientY];
    const how = { shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey };
    const node = view.mode === "view" ? forgeMayaPickAt(view, at[0], at[1]) : null;
    const t = forgeMayaTree(view);
    if (node && t && !how.shift && !how.ctrl && !t.selected().includes(node.id)) t.select(node.id);
    forgeMayaMarkShow(view, at[0], at[1], forgeMayaMenu(view, Object.assign({ node: node }, how)));
    maya.open = "pinned";
  };
  // a click away, or Escape, closes one that was opened by a click
  document.addEventListener("pointerdown", (e) => {
    if (maya.open !== "pinned") return;
    const host = document.getElementById("forge-maya-marking");
    if (host && !host.hidden && !host.contains(e.target)) { maya.open = false; forgeMayaMarkHide(); }
  }, true);
  canvas.addEventListener("pointerup", endRight);
  window.addEventListener("pointerup", endRight);
  window.addEventListener("pointermove", (e) => { if (maya.open === "right") forgeMayaMarkHover(e.clientX, e.clientY); });

  view.mayaRestore = () => { mayaAlt(false); forgeMayaPivotMode(view, false); };
  forgeMayaKeys();                       // after forge_edit's own keys, so its modal wins while it runs
  return maya;
}

// ================================================================== the hotkeys (Maya's default set)
// Installed from forgeMayaAttach and NOT at page load: forge_edit.js registers its capture listener while the
// viewer is built and its modal move owns every key while it runs; registering later keeps that order.
function forgeMayaKeys() {
  if (forgeMayaKeys.done) return;
  forgeMayaKeys.done = true;
  const inField = (el) => el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
  const sheetOpen = () => { const s = document.getElementById("forge"); return !!(s && !s.hidden && forge.view); };
  const take = (e) => { e.preventDefault(); e.stopImmediatePropagation(); };

  document.addEventListener("keydown", (e) => { if (e.key === "Alt" && sheetOpen() && !inField(e.target)) { const m = forge.view.maya; if (m && m.alt) m.alt(true); } }, true);
  document.addEventListener("keyup", (e) => { if (e.key === "Alt" && sheetOpen()) { const m = forge.view.maya; if (m && m.alt) m.alt(false); } }, true);
  window.addEventListener("blur", () => {
    const v = typeof forge !== "undefined" && forge.view;
    if (v && v.maya) { v.maya.held.clear(); if (v.maya.alt) v.maya.alt(false); forgeMayaSnap(v, "grid", false); }
  });

  document.addEventListener("keydown", (e) => {
    if (!sheetOpen() || inField(e.target)) return;
    const v = forge.view, m = v.maya || {};
    if (v.modalActive && v.modalActive()) return;            // Blender's G/R/S modal is running: its keys
    const k = e.key, mod = e.ctrlKey || e.metaKey, sh = e.shiftKey, alt = e.altKey;
    const run = (id) => { take(e); forgeMayaRun(v, id); };
    if (k === " " || e.code === "Space") {                   // Space: hold = hotbox, tap = one/four views
      take(e);
      if (e.repeat) return;
      const hb = document.getElementById("forge-maya-hotbox");
      if (hb && !hb.hidden) return;
      if (forgeMayaWheelOpenNow()) { forgeMayaWheelClose(); return; }   // Space again puts the wheel away
      m.spaceAt = performance.now();
      forgeMayaWheelOpen(v, m.mouse);                                   // at the mouse, like Maya's menus
      return;
    }
    if (k === "Escape") {
      const hb = document.getElementById("forge-maya-hotbox"), mk = document.getElementById("forge-maya-marking");
      if (hb && !hb.hidden) { take(e); forgeMayaHotboxHide(); return; }
      if (forgeMayaWheelOpenNow()) { take(e); forgeMayaWheelClose(); return; }
      if (mk && !mk.hidden) { take(e); forgeMayaMarkHide(); m.open = false; return; }
      const t = forgeMayaTree(v);
      if (t && t.pivotMode) { take(e); forgeMayaPivotMode(v, false); return; }
      if ((v.transform && v.transform.object) || (v.gizmo && v.gizmo.object)) { take(e); forgeMayaTool(v, null); return; }
      return;                                                  // nothing to cancel: Forge's own Esc (close)
    }
    if (forgeKeymap() !== "maya") {                            // Blender set: the Maya keys Forge always had stay on
      if (mod && (k === "g" || k === "G")) return run(sh ? "ungroup" : "group");
      if (mod || alt) return;
      const keep = { q: "select", Q: "select", "4": "wire", "5": "shaded", F8: "objComp", F9: "vertex", F10: "edge", F11: "face" };
      if (keep[k] && !e.repeat) return run(keep[k]);
      if ((k === "g" || k === "G") && !forgeMayaComp(v) && m.last) { take(e); forgeMayaRun(v, m.last); }
      return;
    }
    if (!e.repeat && /^[qwe]$/i.test(k) && !mod && !alt) m.held.add(k.toLowerCase());
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
      return;                                                  // Ctrl/Cmd+S, C, V ... stay the app's
    }
    // ---- Alt / Option
    if (alt) {
      if (lower === "d") return run("selectNone");
      if (lower === "h") return run("hideOthers");
      if (k === "Home") return run("defaultView");
      if (k.startsWith("Arrow")) { take(e); forgeMayaNudge(v, k === "ArrowRight" ? 1 : k === "ArrowLeft" ? -1 : 0, k === "ArrowUp" ? 1 : k === "ArrowDown" ? -1 : 0); return; }
      return;
    }
    // ---- bare keys (Shift for the capitals)
    if (k.startsWith("Arrow")) {                               // pick-walk the hierarchy
      const t = forgeMayaTree(v);
      if (!t || forgeMayaComp(v)) return;
      take(e); t.pickWalk({ ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" }[k]); return;
    }
    if (e.repeat && !/^[\[\]\-=+]$/.test(k)) { if (/^[qwedxj]$/i.test(k)) take(e); return; }
    switch (k) {
      case "q": return run("select");
      case "w": return run("move");
      case "e": return run("rotate");
      case "r": return run("scale");
      case "y": return run("lastTool");
      case "t": return run("move");
      case "g": take(e); if (m.last) forgeMayaRun(v, m.last); return;
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
      case "4": return run("wire");
      case "5": return run("shaded");
      case "6": return run("textured");
      case "7": return run("lights");
      case "d": take(e); mayaSay(forgeMayaPivotMode(v, true)); return;
      case "Insert": take(e); mayaSay(forgeMayaPivotMode(v, null)); return;
      case "Home": return run("pivotEdit");
      case "x": case "X": take(e); forgeMayaSnap(v, "grid", true); mayaSay("Snap to grid (while x is held)."); return;
      case "j": case "J": take(e); forgeMayaSnap(v, "step", true); return;
      case "-": return run("__smaller");
      case "=": case "+": return run("__bigger");
      case "Delete": case "Backspace": return run("delete");
      case ">": return run("grow");
      case "<": return run("shrink");
      case "F8": return run("objComp");
      case "F9": return run("vertex");
      case "F10": return run("edge");
      case "F11": return run("face");
      case "Enter": take(e); forgeMayaTool(v, null); return;
      case "[": case "]":
        if (v.mode === "sculpt") return;                       // the brush size there (forge.js)
        take(e); if (k === "[") v.viewUndo(); else v.viewRedo(); return;
      default: return;
    }
  }, true);

  document.addEventListener("keyup", (e) => {
    const v = typeof forge !== "undefined" && forge.view;
    if (!v || !v.maya) return;
    const m = v.maya, k = e.key;
    if (k.length === 1) m.held.delete(k.toLowerCase());
    if (k === " " || e.code === "Space") {
      const wh = document.getElementById("forge-maya-wheel");
      if (wh && !wh.hidden) {                                  // the wheel (the owner's Space menus)
        if (wh.dataset.open) return;                           // a menu is down: it stays so it can be clicked
        const quickW = performance.now() - (m.spaceAt || 0) < FORGE_MAYA_TAP;
        const usedW = !!wh._used;
        forgeMayaWheelClose();
        if (quickW && !usedW && sheetOpen()) mayaSay(forgeMayaTap(v));
        return;
      }
      const hb = document.getElementById("forge-maya-hotbox");
      if (!hb || hb.hidden || hb.dataset.pinned) return;
      const quick = performance.now() - (m.spaceAt || 0) < FORGE_MAYA_TAP;
      const used = !!hb._used;
      if (hb._zone) return;                                    // a zone menu is open: the mouse release decides
      forgeMayaHotboxHide();
      if (quick && !used && sheetOpen()) mayaSay(forgeMayaTap(v));
      return;
    }
    if (k === "d" || k === "D") { const t = forgeMayaTree(v); if (t && t.pivotMode) forgeMayaPivotMode(v, false); }
    if (k === "x" || k === "X") forgeMayaSnap(v, "grid", false);
    if (k === "j" || k === "J") forgeMayaSnap(v, "step", false);
  });
}

// manipulator size has no menu entry; give the two keys commands of their own
FORGE_MAYA_CMDS.__smaller = ["Smaller manipulator", (v) => forgeMayaManipSize(v, false)];
FORGE_MAYA_CMDS.__bigger = ["Bigger manipulator", (v) => forgeMayaManipSize(v, true)];

// older callers (forge.js's buttons, tests) - the marking menu's 8 wedges and the hotbox, by name
function forgeMayaSets(v) {
  const toPairs = (menu) => Object.values(menu.ring).map((id) => [FORGE_MAYA_CMDS[id][0], () => forgeMayaRun(v, id)]);
  return { object: toPairs(forgeMayaMenu(v, { node: v && forgeMayaTree(v) ? forgeMayaTree(v).active() : null })),
           shift: toPairs(forgeMayaMenu(v, { shift: true })), ctrl: toPairs(forgeMayaMenu(v, { ctrl: true })) };
}
