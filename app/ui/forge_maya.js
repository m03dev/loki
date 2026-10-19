// Forge, the way Maya works - marking menus, the space-bar hotbox, Maya's hotkeys and Maya's camera.
// (owner 2026-10-20: "I want my forge to be like maya ... menus depending on where my mouse clicks ... maya
// hot keys ... space bar for selection menu with more menus ... the viewports the camera")
//
// This is Maya's interaction DESIGN, re-written for a web canvas: no Autodesk code, art or icons are used.
//   marking menus  hold the right button on the viewport and a wheel of commands opens AT THE CURSOR. Which
//                  menu it is depends on the context (nothing/object vs component) and on Shift / Ctrl. Let go
//                  over a wedge to run it; let go over the middle to cancel.
//   hotbox         hold Space: the whole menu set opens as a grid over the window. Move onto a heading to open
//                  its column, click a command. (Click a heading to keep it open until Esc / a click away.)
//   hotkeys        q select, w move, e rotate, r scale, 4 wireframe, 5 shaded, F8 component mode, F9/F10/F11
//                  vertex/edge/face, g repeat the last command, f frame, Esc close.
//   navigation     Alt + left tumbles, Alt + middle tracks, Alt + right dollies - Maya's camera exactly. While
//                  Alt is down the right button belongs to the camera, so the marking menu stands aside.
"use strict";

const FORGE_MAYA_R = 98;          // marking-menu ring radius, px
const FORGE_MAYA_HOLD = 170;      // ms of right-button hold before the wheel opens (a quick click just cancels)

// ------------------------------------------------------------------ small helpers (no icon art: Maya's marking menus are words)
function mayaEl(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

// the commands the menus run - each returns a short note for the status line (or "" for silence)
function forgeMayaSelect(v) {
  if (v.transform && v.transform.object) v.transform.detach();
  if (v.gizmo && v.gizmo.object) v.gizmo.detach();
  return "Select";
}

function forgeMayaResetPivot(v) {
  v.holder.position.set(0, 0, 0);
  v.holder.rotation.set(0, 0, 0);
  v.holder.scale.set(1, 1, 1);
  v.dirty = true;
  return "Pivot back at the origin (Modify > Reset Pivot).";
}

function forgeMayaComponent(v) {
  if (typeof forgeMode === "function") forgeMode();          // object <-> component (the Model/Sculpt switch)
  return "";
}

function forgeMayaKey(k) {                                 // press a hotkey on the app's behalf (component modes live in forge_edit)
  document.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
}

function forgeMayaLook(v, what, on) {
  v.setLook(what, !!on);
  return what === "wire" ? (on ? "Wireframe (4)." : "Shaded (5).") : "";
}

// ------------------------------------------------------------------ the marking-menu sets
function forgeMayaSets(v) {
  const comp = !!(v && v.mode === "poly");
  const obj = [
    ["Select", () => forgeMayaSelect(v)],
    ["Move", () => v.toggleTransform("translate")],
    ["Rotate", () => v.toggleTransform("rotate")],
    ["Scale", () => v.toggleTransform("scale")],
    ["Frame", () => v.frame()],
    ["Reset Pivot", () => forgeMayaResetPivot(v)],
    ["Component Mode", () => forgeMayaComponent(v)],
    ["More...", () => forgeMayaHotboxOpen(v)],
  ];
  const component = [
    ["Vertex", () => forgeMayaKey("1")],
    ["Edge", () => forgeMayaKey("2")],
    ["Face", () => forgeMayaKey("3")],
    ["Move", () => v.toggleTransform("translate")],
    ["Rotate", () => v.toggleTransform("rotate")],
    ["Scale", () => v.toggleTransform("scale")],
    ["Object Mode", () => forgeMayaComponent(v)],
    ["More...", () => forgeMayaHotboxOpen(v)],
  ];
  const view = [
    ["Wireframe", () => forgeMayaLook(v, "wire", true)],
    ["Shaded", () => forgeMayaLook(v, "wire", false)],
    ["Quad View", () => { v.setLook("quad", !v.quad); return v.quad ? "Four views." : "One view."; }],
    ["Frame", () => v.frame()],
    ["Light", () => "Light: " + v.nextLight()],
    ["Undo", () => v.undo()],
    ["Redo", () => v.redo()],
    ["More...", () => forgeMayaHotboxOpen(v)],
  ];
  const display = [
    ["Reset Pivot", () => forgeMayaResetPivot(v)],
    ["Frame", () => v.frame()],
    ["Wireframe", () => forgeMayaLook(v, "wire", true)],
    ["Shaded", () => forgeMayaLook(v, "wire", false)],
    ["Undo", () => v.undo()],
    ["Redo", () => v.redo()],
    ["Light", () => "Light: " + v.nextLight()],
    ["More...", () => forgeMayaHotboxOpen(v)],
  ];
  return { object: comp ? component : obj, shift: view, ctrl: display };
}

// ------------------------------------------------------------------ the marking menu itself
function forgeMayaHost() {
  let host = document.getElementById("forge-maya-marking");
  if (host) return host;
  const stage = document.getElementById("forge-stage");
  if (!stage) return null;
  host = mayaEl("div", "forge-maya-marking");
  host.id = "forge-maya-marking"; host.hidden = true;
  host.setAttribute("role", "menu");
  stage.append(host);
  return host;
}

function forgeMayaWheelShow(v, x, y, set, title) {
  const host = forgeMayaHost();
  if (!host) return;
  host.textContent = "";
  const n = set.length;
  host.append(mayaEl("span", "forge-maya-hub", title || ""));
  set.forEach(([name, run], i) => {
    const a = (-Math.PI / 2) + (i * 2 * Math.PI) / n;            // first wedge straight up, then clockwise (Maya)
    const b = mayaEl("button", "forge-maya-wedge", name);
    b.type = "button"; b.dataset.mayaCmd = name;
    b.style.left = Math.round(Math.cos(a) * FORGE_MAYA_R) + "px";
    b.style.top = Math.round(Math.sin(a) * FORGE_MAYA_R) + "px";
    b.addEventListener("click", (ev) => { ev.stopPropagation(); forgeMayaRun(v, name, run); forgeMayaWheelHide(); });
    host.append(b);
  });
  const rect = (host.parentElement || document.body).getBoundingClientRect();
  host.style.left = Math.round(x - rect.left) + "px";
  host.style.top = Math.round(y - rect.top) + "px";
  host.hidden = false;
  host.dataset.set = title || "";
}

function forgeMayaWheelHide() {
  const host = document.getElementById("forge-maya-marking");
  if (host) { host.hidden = true; host.textContent = ""; }
}

function forgeMayaRun(v, name, run) {
  let note = "";
  try { note = run() || ""; } catch (exc) { note = name + " could not run: " + exc.message; forgeSay(note, true); return; }
  if (v && v.maya) v.maya.last = [name, run];
  if (note && typeof forgeSay === "function") forgeSay(note);
}

// ------------------------------------------------------------------ the hotbox (hold Space)
const FORGE_MAYA_COLUMNS = [
  ["File", [["Save .glb", () => document.querySelector('#forge-exportbar [data-icon="save"]')?.click()],
            ["Close Forge", () => forgeClose()]]],
  ["Edit", [["Undo", (v) => v.undo()], ["Redo", (v) => v.redo()], ["Sculpt/Model", () => forgeMode()]]],
  ["Create", [["Draw", () => forgeWay("draw")], ["Add an image", () => forgeWay("image")],
              ["Describe it", () => forgeWay("describe")], ["Creature", () => forgeWay("creature")]]],
  ["Modify", [["Select", (v) => forgeMayaSelect(v)], ["Move", (v) => v.toggleTransform("translate")],
              ["Rotate", (v) => v.toggleTransform("rotate")], ["Scale", (v) => v.toggleTransform("scale")],
              ["Reset Pivot", (v) => forgeMayaResetPivot(v)], ["Frame selection", (v) => v.frame()]]],
  ["Display", [["Wireframe", (v) => forgeMayaLook(v, "wire", true)], ["Shaded", (v) => forgeMayaLook(v, "wire", false)],
               ["Quad view", (v) => v.setLook("quad", !v.quad)], ["Next light", (v) => v.nextLight()]]],
  ["Panels", [["Model", () => forgeSide("make")], ["Materials", () => forgeSide("materials")]]],
];

function forgeMayaHotboxHost() {
  let host = document.getElementById("forge-maya-hotbox");
  if (host) return host;
  const sheet = document.getElementById("forge");
  if (!sheet) return null;
  host = mayaEl("div", "forge-maya-hotbox");
  host.id = "forge-maya-hotbox"; host.hidden = true;
  host.setAttribute("role", "menu");
  const grid = mayaEl("div", "forge-maya-grid");
  for (const [head, items] of FORGE_MAYA_COLUMNS) {
    const col = mayaEl("section", "forge-maya-col");
    const h = mayaEl("h4", "forge-maya-head", head);
    const list = mayaEl("div", "forge-maya-list");
    for (const [name, run] of items) {
      const b = mayaEl("button", "forge-maya-item", name);
      b.type = "button"; b.dataset.mayaCmd = name;
      b.addEventListener("click", (ev) => { ev.stopPropagation(); const v = forge.view; if (v) forgeMayaRun(v, name, () => run(v)); forgeMayaHotboxHide(); });
      list.append(b);
    }
    col.append(h, list); grid.append(col);
  }
  host.append(grid);
  host.addEventListener("click", () => { /* a click inside keeps it open (pinned by the handler above) */ });
  sheet.append(host);
  return host;
}

function forgeMayaHotboxOpen(v) {
  const host = forgeMayaHotboxHost();
  if (!host) return;
  host.hidden = false;
}

function forgeMayaHotboxHide() {
  const host = document.getElementById("forge-maya-hotbox");
  if (host) { host.hidden = true; delete host.dataset.pinned; }
}

// ------------------------------------------------------------------ attach to a viewer
function forgeMayaAttach(view, ctx) {
  const { THREE, canvas, controls } = ctx;
  const maya = view.maya = { timer: 0, at: null, down: false, last: null, open: false, saved: null,
    controls: controls };
  if (!canvas || !controls) return;

  // Maya's camera: with Alt down the three buttons are tumble / track / dolly, and the right button is free for
  // the marking menu when Alt is up (Maya pans with Alt+MMB, not with a bare right-drag).
  const mayaAlt = (on) => {
    if (on) {
      if (!maya.saved) maya.saved = Object.assign({}, controls.mouseButtons);
      controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
      controls.mouseButtons.MIDDLE = THREE.MOUSE.PAN;
      controls.mouseButtons.RIGHT = THREE.MOUSE.DOLLY;
    } else {
      if (maya.saved) { Object.assign(controls.mouseButtons, maya.saved); maya.saved = null; }
      controls.mouseButtons.RIGHT = null;                 // the marking menu owns the right button
    }
  };
  maya.alt = mayaAlt;
  mayaAlt(false);

  // --- the right button: hold and a wheel opens, release over a wedge to run it
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 2 || e.altKey || view.quad) return;
    maya.down = true; maya.at = [e.clientX, e.clientY];
    window.clearTimeout(maya.timer);
    maya.timer = window.setTimeout(() => {
      if (!maya.down) return;
      const sets = forgeMayaSets(view);
      const set = e.shiftKey ? sets.shift : (e.ctrlKey || e.metaKey) ? sets.ctrl : sets.object;
      maya.open = true;
      forgeMayaWheelShow(view, maya.at[0], maya.at[1], set, view.mode === "poly" ? "Components" : "Object");
    }, FORGE_MAYA_HOLD);
  });
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  const endRight = (e) => {
    if (e.button !== 2) return;
    maya.down = false; window.clearTimeout(maya.timer);
    if (maya.open) {
      const hit = document.elementFromPoint(e.clientX, e.clientY);
      if (hit && hit.dataset && hit.dataset.mayaCmd) {
        const name = hit.dataset.mayaCmd, sets = forgeMayaSets(view);
        for (const set of [sets.object, sets.shift, sets.ctrl]) {
          const found = set.find(([n]) => n === name);
          if (found) { forgeMayaRun(view, found[0], found[1]); break; }
        }
      }
      forgeMayaWheelHide(); maya.open = false;
    }
  };
  canvas.addEventListener("pointerup", endRight);
  window.addEventListener("pointerup", endRight);
  canvas.addEventListener("pointermove", (e) => { if (maya.open) e.preventDefault(); });

  // leaving Forge takes the camera bindings back to where forge_edit left them
  view.mayaRestore = () => { if (maya.saved) mayaAlt(false); };
  forgeMayaKeys();                       // after forge_edit's own keys, so its modal wins while it runs
  return maya;
}

// ------------------------------------------------------------------ the hotkeys (Maya's), installed with the viewer
// Installed from forgeMayaAttach and NOT at page load, on purpose: forge_edit.js registers its own capture
// listener while the viewer is built, and its modal move/rotate/scale owns every key while it runs (so typing
// 0.25 for an exact distance is not eaten by Maya's 4/5 display hotkeys). Registering later puts it first.
function forgeMayaKeys() {
  if (forgeMayaKeys.done) return;
  forgeMayaKeys.done = true;
  const inField = (el) => el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName);
  const sheetOpen = () => { const s = document.getElementById("forge"); return !!(s && !s.hidden && forge.view); };

  document.addEventListener("keydown", (e) => {
    if (e.altKey && !e.repeat && sheetOpen() && !inField(e.target)) {
      const m = forge.view.maya; if (m && m.alt) m.alt(true);
    }
  }, true);
  document.addEventListener("keyup", (e) => {
    if (!e.altKey && sheetOpen()) { const m = forge.view.maya; if (m && m.alt) m.alt(false); }
  }, true);

  // Forge is a modal sheet: while it is open the keys belong to it, so this runs in the CAPTURE phase and
  // stops the event. app/ui/app.js otherwise treats a bare letter as "start typing in the chat box", and a
  // Space would re-click whatever button still had focus (Make).
  const take = (e) => { e.preventDefault(); e.stopImmediatePropagation(); };
  document.addEventListener("keydown", (e) => {
    if (!sheetOpen() || inField(e.target)) return;
    const v = forge.view, m = v.maya || {};
    const k = e.key;
    if (k === " " || e.code === "Space") {                       // Space = the hotbox, held down (Maya)
      const hb = document.getElementById("forge-maya-hotbox");
      if (hb && !hb.hidden) return;
      take(e); forgeMayaHotboxOpen(v); return;
    }
    if (k === "Escape") {
      const hb = document.getElementById("forge-maya-hotbox");
      if (hb && !hb.hidden) { take(e); forgeMayaHotboxHide(); }
      return;                                                    // everything else is Forge's own Esc
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;              // Ctrl+Z&c, and Alt is the camera
    switch (k) {
      case "q": case "Q": take(e); forgeMayaRun(v, "Select", () => forgeMayaSelect(v)); break;
      case "4": take(e); forgeMayaRun(v, "Wireframe", () => forgeMayaLook(v, "wire", true)); break;
      case "5": take(e); forgeMayaRun(v, "Shaded", () => forgeMayaLook(v, "wire", false)); break;
      case "F8": take(e); forgeMayaRun(v, "Component Mode", () => forgeMayaComponent(v)); break;
      case "F9": take(e); forgeMayaKey("1"); break;
      case "F10": take(e); forgeMayaKey("2"); break;
      case "F11": take(e); forgeMayaKey("3"); break;
      case "g": case "G":
        if (m.last) { take(e); forgeMayaRun(v, m.last[0], m.last[1]); }
        break;
      default: break;
    }
  }, true);

  document.addEventListener("keyup", (e) => {
    if (e.key !== " " && e.code !== "Space") return;
    const hb = document.getElementById("forge-maya-hotbox");
    if (hb && !hb.hidden && !hb.dataset.pinned) forgeMayaHotboxHide();
  });
}
