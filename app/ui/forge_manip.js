// Forge's manipulator - the move / rotate / scale handles drawn the way the pro modelling tools draw them
// (owner 2026-10-21: the gizmo should look like the pro tools' handles, not Blender's; "the hovering over gizmo and
// press shift changes function" the way it does there).
//
// The behaviour is three.js' TransformControls (MIT, app/ui/vendor/three/addons/controls/TransformControls.js,
// unchanged); only the handles are rebuilt here:
//   Move    one arrow per axis (a thin shaft and a cone, pointing one way only), a small filled square for each
//           plane, and a screen-facing square in the middle that moves in the view plane.
//   Rotate  the front half of each axis ring, a light-blue outer ring that turns about the view axis, and a grey
//           trackball ring with a faint disc for free rotation.
//   Scale   a shaft with a cube per axis, plane squares, and a light-blue cube in the middle for uniform scale.
// Colours: X red, Y green, Z blue, the centre handles light blue, the handle under the mouse yellow - and ORANGE
// while Shift is held over a handle: the drag will then duplicate (objects) or extrude (faces), and the help line
// says which. No dashed helper lines and no double-ended arrows (the Blender look the owner did not want).
import { TransformControls } from "/ui/vendor/three/addons/controls/TransformControls.js";
import {
  BoxGeometry, CircleGeometry, ConeGeometry, CylinderGeometry, DoubleSide, MeshBasicMaterial, Mesh, Object3D,
  OctahedronGeometry, RingGeometry, SphereGeometry, TorusGeometry,
} from "/ui/vendor/three/three.module.js";

export const FORGE_MANIP_COLORS = {
  x: 0xe8393a, y: 0x45d64a, z: 0x3a6cff, center: 0x6fd3ff, active: 0xffff3c, shift: 0xff9a1e, track: 0x9a9a9a,
};

const LEN = 0.62;         // shaft + cone, in the handle's units (TransformControls scales them to the screen)

function mat(color, opacity) {
  return new MeshBasicMaterial({ color: color, depthTest: false, depthWrite: false, fog: false, toneMapped: false,
    transparent: true, opacity: opacity == null ? 1 : opacity, side: DoubleSide });
}

// the same layout helper as TransformControls' own (name + geometry baked with its offset)
function build(defs) {
  const g = new Object3D();
  for (const name in defs) {
    for (const [proto, pos, rot, scale, face] of defs[name]) {
      const o = proto.clone();
      o.name = name;
      if (pos) o.position.set(pos[0], pos[1], pos[2]);
      if (rot) o.rotation.set(rot[0], rot[1], rot[2]);
      if (scale) o.scale.set(scale[0], scale[1], scale[2]);
      o.updateMatrix();
      const geo = o.geometry.clone(); geo.applyMatrix4(o.matrix); o.geometry = geo;
      o.renderOrder = Infinity;
      o.position.set(0, 0, 0); o.rotation.set(0, 0, 0); o.scale.set(1, 1, 1);
      if (face) o.userData.faceCamera = true;    // turned to the screen every frame (the centre squares)
      g.add(o);
    }
  }
  return g;
}

function ringGeo(radius, arc, tube) {             // a ring round X (TransformControls' CircleGeometry, thinner)
  const geo = new TorusGeometry(radius, tube || 0.006, 4, 72, arc * Math.PI * 2);
  geo.rotateY(Math.PI / 2); geo.rotateX(Math.PI / 2);
  return geo;
}

function definitions() {
  const C = FORGE_MANIP_COLORS;
  const red = mat(C.x), green = mat(C.y), blue = mat(C.z), center = mat(C.center);
  const redP = mat(C.x, 0.85), greenP = mat(C.y, 0.85), blueP = mat(C.z, 0.85);
  const track = mat(C.track, 0.9), disc = mat(0xffffff, 0.05), hide = mat(0xffffff, 0.15);
  hide.visible = false;
  const shaft = new CylinderGeometry(0.0065, 0.0065, LEN - 0.15, 6); shaft.translate(0, (LEN - 0.15) / 2, 0);
  const cone = new ConeGeometry(0.042, 0.15, 16); cone.translate(0, LEN - 0.075, 0);
  const cube = new BoxGeometry(0.07, 0.07, 0.07); cube.translate(0, LEN - 0.08, 0);
  const sshaft = new CylinderGeometry(0.0065, 0.0065, LEN - 0.12, 6); sshaft.translate(0, (LEN - 0.12) / 2, 0);
  const plane = new BoxGeometry(0.085, 0.085, 0.001);
  const square = new RingGeometry(0.052, 0.068, 4, 1, Math.PI / 4);      // a square outline, facing +Z
  const X = [0, 0, -Math.PI / 2], Z = [Math.PI / 2, 0, 0];
  const at = 0.2;                                                     // where the plane squares sit
  const gizmoTranslate = {
    X: [[new Mesh(shaft, red), null, X], [new Mesh(cone, red), null, X]],
    Y: [[new Mesh(shaft, green)], [new Mesh(cone, green)]],
    Z: [[new Mesh(shaft, blue), null, Z], [new Mesh(cone, blue), null, Z]],
    XY: [[new Mesh(plane, blueP), [at, at, 0]]],
    YZ: [[new Mesh(plane, redP), [0, at, at], [0, Math.PI / 2, 0]]],
    XZ: [[new Mesh(plane, greenP), [at, 0, at], [-Math.PI / 2, 0, 0]]],
    XYZ: [[new Mesh(square, center), null, null, null, true]],
  };
  const pickStick = new CylinderGeometry(0.06, 0.06, LEN, 6); pickStick.translate(0, LEN / 2, 0);
  const pickerTranslate = {
    X: [[new Mesh(pickStick, hide), null, X]],
    Y: [[new Mesh(pickStick, hide)]],
    Z: [[new Mesh(pickStick, hide), null, Z]],
    XY: [[new Mesh(new BoxGeometry(0.13, 0.13, 0.01), hide), [at, at, 0]]],
    YZ: [[new Mesh(new BoxGeometry(0.13, 0.13, 0.01), hide), [0, at, at], [0, Math.PI / 2, 0]]],
    XZ: [[new Mesh(new BoxGeometry(0.13, 0.13, 0.01), hide), [at, 0, at], [-Math.PI / 2, 0, 0]]],
    XYZ: [[new Mesh(new OctahedronGeometry(0.1, 0), hide)]],
  };
  const gizmoRotate = {
    // trackball: a grey ring and a faint disc, both turned to the eye (names with E face the camera)
    XYZE: [[new Mesh(new TorusGeometry(0.5, 0.005, 4, 72), track)], [new Mesh(new CircleGeometry(0.5, 64), disc)]],
    X: [[new Mesh(ringGeo(0.5, 0.5, 0.008), red)]],
    Y: [[new Mesh(ringGeo(0.5, 0.5, 0.008), green), null, [0, 0, -Math.PI / 2]]],
    Z: [[new Mesh(ringGeo(0.5, 0.5, 0.008), blue), null, [0, Math.PI / 2, 0]]],
    E: [[new Mesh(new TorusGeometry(0.62, 0.007, 4, 96), center)]],
  };
  const pickerRotate = {
    XYZE: [[new Mesh(new SphereGeometry(0.45, 12, 8), hide)]],
    X: [[new Mesh(new TorusGeometry(0.5, 0.07, 4, 24), hide), null, [0, -Math.PI / 2, -Math.PI / 2]]],
    Y: [[new Mesh(new TorusGeometry(0.5, 0.07, 4, 24), hide), null, [Math.PI / 2, 0, 0]]],
    Z: [[new Mesh(new TorusGeometry(0.5, 0.07, 4, 24), hide), null, [0, 0, -Math.PI / 2]]],
    E: [[new Mesh(new TorusGeometry(0.62, 0.06, 2, 24), hide)]],
  };
  const gizmoScale = {
    X: [[new Mesh(sshaft, red), null, X], [new Mesh(cube, red), null, X]],
    Y: [[new Mesh(sshaft, green)], [new Mesh(cube, green)]],
    Z: [[new Mesh(sshaft, blue), null, Z], [new Mesh(cube, blue), null, Z]],
    XY: [[new Mesh(plane, blueP), [at, at, 0]]],
    YZ: [[new Mesh(plane, redP), [0, at, at], [0, Math.PI / 2, 0]]],
    XZ: [[new Mesh(plane, greenP), [at, 0, at], [-Math.PI / 2, 0, 0]]],
    XYZ: [[new Mesh(new BoxGeometry(0.085, 0.085, 0.085), center)]],
  };
  const pickerScale = {
    X: [[new Mesh(pickStick, hide), null, X]],
    Y: [[new Mesh(pickStick, hide)]],
    Z: [[new Mesh(pickStick, hide), null, Z]],
    XY: pickerTranslate.XY, YZ: pickerTranslate.YZ, XZ: pickerTranslate.XZ,
    XYZ: [[new Mesh(new BoxGeometry(0.15, 0.15, 0.15), hide)]],
  };
  return { gizmoTranslate, pickerTranslate, gizmoRotate, pickerRotate, gizmoScale, pickerScale };
}

// Shift, read from the keyboard (TransformControls' own events do not carry it)
const live = new Set();
let shiftHeld = false;
function setShift(on) {
  if (shiftHeld === on) return;
  shiftHeld = on;
  for (const tc of live) tc.dispatchEvent({ type: "change" });
}
if (typeof document !== "undefined") {
  document.addEventListener("keydown", (e) => { if (e.key === "Shift") setShift(true); }, true);
  document.addEventListener("keyup", (e) => { if (e.key === "Shift") setShift(false); }, true);
  window.addEventListener("blur", () => setShift(false));
}

export class ForgeManip extends TransformControls {
  constructor(camera, domElement) {
    super(camera, domElement);
    this.isForgeManip = true;
    this.showHelpers = false;              // the dashed lines / start-end markers (kept, off by default)
    this.shiftHint = null;                 // (tc) => text for the help line while Shift is held over a handle
    forgeManipRestyle(this);
    live.add(this);
    // the pro middle-button drag: anywhere in the view, the manipulator moves along the handle you used last (or the
    // view plane / view axis before any), without having to grab the handle itself
    this.middleDrag = true;
    this.addEventListener("mouseDown", () => { if (this.axis) this.lastAxis = this.axis; });
    if (domElement) {
      domElement.addEventListener("pointerdown", (e) => {
        if (!this.middleDrag || e.button !== 1 || forgeCamMod(e) || !this.enabled || !this.object || this.dragging) return;
        const ax = this.lastAxis && (this.mode !== "rotate" ? /^(X|Y|Z|XY|YZ|XZ|XYZ)$/ : /^(X|Y|Z|E|XYZE)$/).test(this.lastAxis)
          ? this.lastAxis : (this.mode === "rotate" ? "E" : "XYZ");
        e.preventDefault(); e.stopImmediatePropagation();
        const ptr = (ev, b) => { const p = this._getPointer(ev); p.button = b; return p; };   // TransformControls: down/up 0, move -1
        this.axis = ax;
        this.getHelper().updateMatrixWorld(true);         // the drag plane follows the axis just set
        this.pointerDown(ptr(e, 0));
        const mv = (ev) => { this.axis = ax; this.pointerMove(ptr(ev, -1)); };
        const up = (ev) => { document.removeEventListener("pointermove", mv, true); document.removeEventListener("pointerup", up, true); this.pointerUp(ptr(ev, 0)); };
        document.addEventListener("pointermove", mv, true); document.addEventListener("pointerup", up, true);
      }, true);
    }
  }
  get shiftHeld() { return shiftHeld; }
  dispose() { live.delete(this); super.dispose(); }
}

export function forgeManipRestyle(tc) {
  const g = tc._gizmo;
  if (!g || g.forgeStyled) return tc;
  const d = definitions();
  const swap = (kind, mode, defs, visible) => {
    const old = g[kind][mode];
    if (old) { g.remove(old); }
    const next = build(defs);
    next.visible = visible;
    g[kind][mode] = next;
    g.add(next);
  };
  swap("gizmo", "translate", d.gizmoTranslate, true);
  swap("gizmo", "rotate", d.gizmoRotate, true);
  swap("gizmo", "scale", d.gizmoScale, true);
  swap("picker", "translate", d.pickerTranslate, false);
  swap("picker", "rotate", d.pickerRotate, false);
  swap("picker", "scale", d.pickerScale, false);
  const C = FORGE_MANIP_COLORS;
  g.materialLib.active.color.setHex(C.active);
  const update = g.updateMatrixWorld;
  let lastHint = "";
  g.updateMatrixWorld = function (force) {
    const shift = shiftHeld && !!tc.axis && tc.enabled;
    this.materialLib.active.color.setHex(shift ? C.shift : C.active);
    update.call(this, force);
    let again = false;
    const kids = this.gizmo[this.mode] ? this.gizmo[this.mode].children.concat(this.picker[this.mode].children) : [];
    for (const h of kids) if (h.userData.faceCamera && this.cameraQuaternion) { h.quaternion.copy(this.cameraQuaternion); again = true; }
    if (!tc.showHelpers && this.helper[this.mode]) { for (const h of this.helper[this.mode].children) h.visible = false; }
    if (again) Object3D.prototype.updateMatrixWorld.call(this, true);
    // the help line says what Shift will do (only while hovering, not mid-drag)
    const hint = shift && !tc.dragging && tc.shiftHint ? tc.shiftHint(tc) || "" : "";
    if (hint !== lastHint) {
      lastHint = hint;
      const help = typeof document !== "undefined" && document.getElementById("fmy-help");
      if (help && hint) help.textContent = hint;
      const el = tc.domElement;
      if (el && el.style) el.style.cursor = hint ? "copy" : "";
    }
  };
  g.forgeStyled = true;
  return tc;
}

if (typeof window !== "undefined") window.ForgeManipColors = FORGE_MANIP_COLORS;
