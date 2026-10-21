// Forge's hotkeys - one table, every key changeable (owner 2026-10-21: hotkeys like the pro tools', "everything should
// be modular and custimizable").
//
// What used to be a hard-coded switch in forge_pro.js is now data: FORGE_KEY_DEFAULTS is the pro tools' default
// hotkey set (docs/FORGE_PRO_SPEC.md, the keys the reference package ships with), and the owner can make sets of
// his own in the Hotkey Editor (Windows > Settings/Preferences > Hotkey Editor, or the hotbox's Windows menu):
// duplicate the default set, press a new key for any command, clear one, import / export a set as JSON, switch
// sets. The default set itself is locked, so it is always there to go back to - like the pro Hotkey Editor.
//
// A key is written as a chord: [ctrl+][alt+][shift+]<key>. "ctrl" is Ctrl on Windows AND Cmd on the Mac (the pro
// tools treat them alike); letters and digits are read by their place on the keyboard (so Option+D on a Mac is
// still "alt+d", not "∂"); symbols are written as typed (">" not "shift+.").
//
// An action is a command id from FORGE_PRO_CMDS (forge_pro.js: menus, hotbox, marking menus and the command line use
// the same ids) or a special "@" action that needs the key itself (holds, pick-walk, the snap keys) - forge_pro.js
// runs those. Space (the hotbox) and Escape stay where they are: they are what you use to get out of anything.
"use strict";

const FORGE_KEYS_STORE = "loki-forge-hotkeys";
const FORGE_KEYS_DEFAULT_SET = "Default";

// [chord, action] - the pro default set. Order = the order the editor lists them in.
const FORGE_KEY_DEFAULTS = [
  // tools (hold q / w / e + left button = that tool's marking menu)
  ["q", "select"], ["w", "move"], ["e", "rotate"], ["r", "scale"], ["t", "showManip"], ["y", "lastTool"],
  ["enter", "@completeTool"], ["g", "@repeatLast"],
  // edit
  ["z", "undo"], ["ctrl+z", "undo"], ["shift+z", "redo"], ["ctrl+shift+z", "redo"], ["ctrl+y", "redo"],
  ["ctrl+d", "duplicate"], ["shift+d", "duplicateT"], ["ctrl+g", "group"], ["ctrl+shift+g", "ungroup"],
  ["p", "parent"], ["shift+p", "unparent"], ["delete", "delete"], ["backspace", "delete"],
  ["alt+shift+d", "deleteHistory"],
  // display / visibility
  ["h", "hideToggle"], ["ctrl+h", "hide"], ["shift+h", "show"], ["ctrl+shift+h", "showLast"], ["alt+h", "hideOthers"],
  ["ctrl+alt+h", "showAll"], ["ctrl+1", "isolate"], ["alt+x", "xray"],
  ["1", "smooth1"], ["2", "smooth2"], ["3", "smooth3"], ["4", "wire"], ["5", "shaded"], ["6", "textured"], ["7", "lights"],
  ["ctrl+space", "hideUI"],
  // select
  ["ctrl+shift+a", "selectAll"], ["alt+d", "selectNone"], ["ctrl+shift+i", "invert"], [">", "grow"], ["<", "shrink"],
  ["f8", "objComp"], ["f9", "vertex"], ["f10", "edge"], ["f11", "face"],
  ["ctrl+f9", "vertex"], ["ctrl+f10", "edge"], ["ctrl+f11", "face"], ["f12", "uv"],
  ["arrowup", "@pickUp"], ["arrowdown", "@pickDown"], ["arrowleft", "@pickLeft"], ["arrowright", "@pickRight"],
  // view
  ["a", "frameAll"], ["shift+a", "frameAll"], ["f", "frameSel"], ["shift+f", "frameSel"], ["alt+home", "defaultView"],
  ["[", "@viewUndo"], ["]", "@viewRedo"],
  // pivots and snapping (held)
  ["d", "@pivotHold"], ["insert", "@pivotToggle"], ["home", "pivotEdit"],
  ["x", "@snapGrid"], ["c", "@snapEdge"], ["v", "@snapPoint"], ["j", "@snapStep"],
  ["-", "__smaller"], ["=", "__bigger"], ["+", "__bigger"],
  ["alt+arrowup", "@nudgeUp"], ["alt+arrowdown", "@nudgeDown"], ["alt+arrowleft", "@nudgeLeft"], ["alt+arrowright", "@nudgeRight"],
  // windows
  ["ctrl+a", "channelBox"],
  // animation (the Time Slider)
  ["s", "setKey"], ["alt+v", "playPause"], ["alt+shift+v", "playPause"],
  // modelling
  ["ctrl+e", "extrude"], ["ctrl+b", "bevel"], ["ctrl+backspace", "deleteEdgeVert"], ["ctrl+delete", "deleteEdgeVert"],
  // sculpting (held)
  ["b", "@brushSize"], ["m", "@brushStrength"],
];

// special actions: a name for the editor (the rest come from FORGE_PRO_CMDS)
const FORGE_KEY_SPECIAL = {
  "@completeTool": "Complete Tool", "@repeatLast": "Repeat Last", "@pickUp": "Pick-walk Up", "@pickDown": "Pick-walk Down",
  "@pickLeft": "Pick-walk Left", "@pickRight": "Pick-walk Right", "@viewUndo": "Undo View Change", "@viewRedo": "Redo View Change",
  "@pivotHold": "Edit Pivot (hold)", "@pivotToggle": "Edit Pivot (toggle)", "@snapGrid": "Snap to Grids (hold)",
  "@snapEdge": "Snap to Curves / Edges (hold)", "@snapPoint": "Snap to Points (hold)", "@snapStep": "Step Snap (hold)",
  "@nudgeUp": "Nudge Up", "@nudgeDown": "Nudge Down", "@nudgeLeft": "Nudge Left", "@nudgeRight": "Nudge Right",
  "@brushSize": "Brush Size (hold + drag)", "@brushStrength": "Brush Strength (hold + drag)",
};
// held actions keep the letter the rest of Forge listens for (q/w/e marking menus, b/m brush drags, x/c/v snaps)
const FORGE_KEY_HOLD = { select: "q", move: "w", rotate: "e", "@snapGrid": "x", "@snapEdge": "c", "@snapPoint": "v",
  "@brushSize": "b", "@brushStrength": "m" };
// actions a held-down key repeats (everything else fires once per press)
const FORGE_KEY_REPEATS = new Set(["__smaller", "__bigger", "@viewUndo", "@viewRedo", "undo", "redo", "@pickUp", "@pickDown",
  "@pickLeft", "@pickRight", "@nudgeUp", "@nudgeDown", "@nudgeLeft", "@nudgeRight"]);
// the editor's groups (by command id; anything not listed goes under "Other")
const FORGE_KEY_GROUPS = [
  ["Tools", ["select", "move", "rotate", "scale", "showManip", "lastTool", "@completeTool", "@repeatLast", "softSel", "multiCut", "sculpt"]],
  ["Edit", ["undo", "redo", "duplicate", "duplicateT", "group", "ungroup", "parent", "unparent", "delete", "deleteHistory"]],
  ["Display", ["hideToggle", "hide", "show", "showLast", "hideOthers", "showAll", "isolate", "xray", "smooth1", "smooth2", "smooth3",
    "wire", "shaded", "textured", "lights", "grid", "hideUI", "quadToggle"]],
  ["Select", ["selectAll", "selectNone", "invert", "hierarchy", "grow", "shrink", "objComp", "vertex", "edge", "face", "uv",
    "@pickUp", "@pickDown", "@pickLeft", "@pickRight", "loopSel", "ringSel"]],
  ["View", ["frameAll", "frameSel", "defaultView", "@viewUndo", "@viewRedo", "persp", "top", "front", "side", "single", "four"]],
  ["Pivot / Snap", ["@pivotHold", "@pivotToggle", "pivotEdit", "centerPivot", "resetPivot", "@snapGrid", "@snapEdge", "@snapPoint",
    "@snapStep", "snapGrid", "snapEdge", "snapPoint", "__smaller", "__bigger", "@nudgeUp", "@nudgeDown", "@nudgeLeft", "@nudgeRight"]],
  ["Modelling", ["extrude", "inset", "bevel", "bridge", "edgeLoop", "offsetEdgeLoop", "multiCut", "targetWeld", "slideEdge", "connect",
    "detach", "collapse", "merge", "mergeCenter", "fillHole", "reverse", "deleteComp", "deleteEdgeVert", "smooth", "triangulate",
    "quadrangulate", "averageVerts", "relax", "circularize", "spinEdge", "spinEdgeBack", "duplicateFace", "extractFace",
    "dynamesh", "combine", "separate", "mirror", "mirrorY", "mirrorZ", "chamfer", "poke", "wedge", "cleanup", "meshStats", "insertLoopTool", "mergeThreshold"]],
  ["Sculpting", ["@brushSize", "@brushStrength", "sculptRemesh", "sculptQuadRemesh", "sculptReduce", "sculptDivide", "sculptDynamic", "matcapNext", "matcapPrev"]],
  ["Windows", ["channelBox", "outliner", "winOutliner", "winChannel", "winCreate", "winMaterials", "winShelf", "winToolkit", "winCreature", "wheel", "hotkeyEditor"]],
];

const forgeIsMac = () => /Mac|iPhone|iPad/.test((typeof navigator !== "undefined" && (navigator.platform || navigator.userAgent)) || "");

/** The chord a key event is: "ctrl+shift+z", "alt+d", ">", "f8", "arrowup" ... or "" for a lone modifier. */
function forgeKeyChord(e) {
  let k = e.key || "";
  if (k === "Shift" || k === "Control" || k === "Alt" || k === "Meta" || k === "OS" || k === "AltGraph") return "";
  const code = e.code || "";
  let shiftCounts = true;
  if (k === " " || code === "Space") k = "space";
  else if (/^Key[A-Z]$/.test(code) && (k.length !== 1 || !/[a-z]/i.test(k) || e.altKey)) k = code.slice(3).toLowerCase();   // Option+D = "∂"
  else if (/^Digit[0-9]$/.test(code) && (e.altKey || e.ctrlKey || e.metaKey || !/[0-9]/.test(k))) {
    if (e.shiftKey && !(e.altKey || e.ctrlKey || e.metaKey) && k.length === 1) { shiftCounts = false; }   // "!" stays "!"
    else k = code.slice(5);
  } else if (k.length === 1) {
    if (/[a-z]/i.test(k)) k = k.toLowerCase();
    else if (!/[0-9]/.test(k)) shiftCounts = false;   // symbols: ">" already says Shift
  } else k = k.toLowerCase();
  if (k === "+" && !e.shiftKey) shiftCounts = false;
  const parts = [];
  if (e.ctrlKey || e.metaKey) parts.push("ctrl");
  if (e.altKey) parts.push("alt");
  if (e.shiftKey && shiftCounts) parts.push("shift");
  parts.push(k);
  return parts.join("+");
}

/** "ctrl+shift+z" -> "Cmd+Shift+Z" on a Mac, "Ctrl+Shift+Z" elsewhere. */
function forgeKeyLabel(chord) {
  if (!chord) return "";
  const mac = forgeIsMac();
  const names = { ctrl: mac ? "Cmd" : "Ctrl", alt: mac ? "Option" : "Alt", shift: "Shift", space: "Space", enter: "Enter",
    delete: "Delete", backspace: "Backspace", insert: "Insert", home: "Home", end: "End", arrowup: "Up", arrowdown: "Down",
    arrowleft: "Left", arrowright: "Right", escape: "Esc", tab: "Tab", pageup: "PageUp", pagedown: "PageDown" };
  return chord.split("+").filter((x, i, a) => x || i === a.length - 1).map((p) => names[p] || (p.length === 1 ? p.toUpperCase() : p.replace(/^f(\d+)$/, "F$1")))
    .join("+").replace(/\+\+$/, "++");
}

// ---------------------------------------------------------------- the sets (stored per user, in this browser)
function forgeKeysDefaultMap() {
  const map = {};
  for (const [chord, act] of FORGE_KEY_DEFAULTS) map[chord] = act;
  return map;
}
function forgeKeysLoad() {
  let st = null;
  try { st = JSON.parse(localStorage.getItem(FORGE_KEYS_STORE) || "null"); } catch (_) { st = null; }
  if (!st || typeof st !== "object" || !st.sets || typeof st.sets !== "object") st = { active: FORGE_KEYS_DEFAULT_SET, sets: {} };
  delete st.sets[FORGE_KEYS_DEFAULT_SET];            // the default set is never stored: it is the code's
  if (st.active !== FORGE_KEYS_DEFAULT_SET && !st.sets[st.active]) st.active = FORGE_KEYS_DEFAULT_SET;
  return st;
}
function forgeKeysSave(st) {
  try { localStorage.setItem(FORGE_KEYS_STORE, JSON.stringify(st)); } catch (_) { /* private mode: this session only */ }
  forgeKeysCache = null;
}
let forgeKeysCache = null;
/** The active set as { chord: action }. */
function forgeKeyMap() {
  if (forgeKeysCache) return forgeKeysCache;
  const st = forgeKeysLoad();
  forgeKeysCache = st.active === FORGE_KEYS_DEFAULT_SET ? forgeKeysDefaultMap() : Object.assign({}, st.sets[st.active]);
  return forgeKeysCache;
}
function forgeKeyAction(chord) { return chord ? forgeKeyMap()[chord] || null : null; }
/** Every chord bound to an action in the active set. */
function forgeKeysFor(action) {
  const map = forgeKeyMap();
  return Object.keys(map).filter((c) => map[c] === action);
}
function forgeKeyActionName(action) {
  if (FORGE_KEY_SPECIAL[action]) return FORGE_KEY_SPECIAL[action];
  const c = typeof FORGE_PRO_CMDS !== "undefined" && FORGE_PRO_CMDS[action];
  return c ? c[0] : action;
}

// the API scripts, tests and LOKI's agents use (window.forgeHotkeys)
const forgeHotkeys = {
  chord: forgeKeyChord, label: forgeKeyLabel, action: forgeKeyAction, keysFor: forgeKeysFor, map: () => Object.assign({}, forgeKeyMap()),
  defaults: () => forgeKeysDefaultMap(), name: forgeKeyActionName,
  sets: () => [FORGE_KEYS_DEFAULT_SET].concat(Object.keys(forgeKeysLoad().sets)),
  active: () => forgeKeysLoad().active,
  use(name) { const st = forgeKeysLoad(); if (name !== FORGE_KEYS_DEFAULT_SET && !st.sets[name]) return false; st.active = name; forgeKeysSave(st); return true; },
  /** A new set copied from another (the default set when none is given); it becomes the active one. */
  duplicate(name, from) {
    const st = forgeKeysLoad();
    let n = String(name || "").trim() || "My_Hotkeys";
    if (n === FORGE_KEYS_DEFAULT_SET) n = "My_Hotkeys";
    let base = n, i = 1;
    while (st.sets[n]) n = base + "_" + (++i);
    const src = from || st.active;
    st.sets[n] = src === FORGE_KEYS_DEFAULT_SET || !st.sets[src] ? forgeKeysDefaultMap() : Object.assign({}, st.sets[src]);
    st.active = n; forgeKeysSave(st); return n;
  },
  remove(name) { const st = forgeKeysLoad(); if (!st.sets[name]) return false; delete st.sets[name]; if (st.active === name) st.active = FORGE_KEYS_DEFAULT_SET; forgeKeysSave(st); return true; },
  /** Bind chord -> action in the active set (the default set is locked: a copy is made first). Returns the set's name. */
  bind(chord, action) {
    if (!chord) return null;
    let st = forgeKeysLoad();
    if (st.active === FORGE_KEYS_DEFAULT_SET) { forgeHotkeys.duplicate("My_Hotkeys"); st = forgeKeysLoad(); }
    const set = st.sets[st.active];
    if (action) set[chord] = action; else delete set[chord];
    forgeKeysSave(st);
    return st.active;
  },
  /** Take a key off an action (or every key, when no chord is given). */
  unbind(action, chord) {
    let st = forgeKeysLoad();
    if (st.active === FORGE_KEYS_DEFAULT_SET) { forgeHotkeys.duplicate("My_Hotkeys"); st = forgeKeysLoad(); }
    const set = st.sets[st.active];
    for (const c of Object.keys(set)) if (set[c] === action && (!chord || c === chord)) delete set[c];
    forgeKeysSave(st); return st.active;
  },
  resetActive() { const st = forgeKeysLoad(); if (st.sets[st.active]) { st.sets[st.active] = forgeKeysDefaultMap(); forgeKeysSave(st); } return st.active; },
  export(name) {
    const st = forgeKeysLoad(), n = name || st.active;
    return JSON.stringify({ forgeHotkeys: 1, name: n, keys: n === FORGE_KEYS_DEFAULT_SET ? forgeKeysDefaultMap() : st.sets[n] || {} }, null, 1);
  },
  import(text) {
    const data = typeof text === "string" ? JSON.parse(text) : text;
    if (!data || typeof data.keys !== "object") throw new Error("not a Forge hotkey set");
    const st = forgeKeysLoad();
    let n = String(data.name || "Imported").replace(/[^\w .-]/g, "").trim() || "Imported";
    if (n === FORGE_KEYS_DEFAULT_SET) n = "Imported";
    const base = n; let i = 1; while (st.sets[n]) n = base + "_" + (++i);
    const keys = {};
    for (const [c, a] of Object.entries(data.keys)) if (typeof c === "string" && typeof a === "string" && c.length < 40 && a.length < 60) keys[c] = a;
    st.sets[n] = keys; st.active = n; forgeKeysSave(st); return n;
  },
  /** Every action the editor can bind: the commands and the special ones. */
  actions() {
    const ids = new Set(Object.keys(FORGE_KEY_SPECIAL));
    if (typeof FORGE_PRO_CMDS !== "undefined") for (const id of Object.keys(FORGE_PRO_CMDS)) if (FORGE_PRO_CMDS[id][1]) ids.add(id);
    return [...ids];
  },
  hold: (action) => FORGE_KEY_HOLD[action] || null,
  repeats: (action) => FORGE_KEY_REPEATS.has(action),
  open: () => forgeHotkeyEditor(true),
};
window.forgeHotkeys = forgeHotkeys;

/** True when Forge is the open mode and this key is one of its hotkeys (or Space / Esc): the app-wide shortcuts
 *  (the mode bar's Ctrl/Cmd+1..4, the chat's Mod+B / Alt+Up ...) listen in the capture phase, so without this
 *  check they took Forge's keys first - Ctrl/Cmd+1 (Isolate Select) went Home (owner 2026-10-21). */
function forgeOwnsKey(e) {
  const s = typeof document !== "undefined" && document.getElementById("forge");
  if (!s || s.hidden) return false;
  if (window.LokiModeBar && window.LokiModeBar.active && window.LokiModeBar.active() !== "forge") return false;
  const t = e.target;
  if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || "") || t.isContentEditable)) return false;
  if (e.key === "Escape" || e.key === " " || e.code === "Space") return true;
  return !!forgeKeyAction(forgeKeyChord(e));
}
window.forgeOwnsKey = forgeOwnsKey;

// ---------------------------------------------------------------- the Hotkey Editor
function forgeHotkeyEditor(show) {
  let box = document.getElementById("forge-hotkeys");
  if (box && show === false) { box.hidden = true; return box; }
  if (!box) {
    box = document.createElement("div");
    box.id = "forge-hotkeys"; box.className = "forge-hk"; box.hidden = true;
    box.setAttribute("role", "dialog"); box.setAttribute("aria-label", "Hotkey Editor");
    box.innerHTML = '<div class="forge-hk-title"><span>Hotkey Editor</span><button type="button" class="forge-hk-x" title="Close (Esc)">×</button></div>'
      + '<div class="forge-hk-bar"><label>Keyboard Shortcut Set <select class="forge-hk-set"></select></label>'
      + '<button type="button" data-hk="dup" title="Copy this set into a new one you can change">Duplicate</button>'
      + '<button type="button" data-hk="del" title="Delete this set (the Default set stays)">Delete</button>'
      + '<button type="button" data-hk="reset" title="Put this set back to the default keys">Reset</button>'
      + '<button type="button" data-hk="export" title="Copy this set as text (JSON) to keep or share">Export</button>'
      + '<button type="button" data-hk="import" title="Paste a set someone exported">Import</button></div>'
      + '<div class="forge-hk-bar"><input class="forge-hk-search" type="search" placeholder="Search commands or keys"><span class="forge-hk-note"></span></div>'
      + '<div class="forge-hk-list"></div>'
      + '<div class="forge-hk-foot">Click a key box, then press the new key (Esc cancels, Backspace clears). The Default set is locked - changing a key copies it to a set of your own.</div>';
    document.body.append(box);
    box.querySelector(".forge-hk-x").addEventListener("click", () => { box.hidden = true; });
    box.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Escape" && !box.dataset.capturing) { box.hidden = true; } });
    box.querySelector(".forge-hk-set").addEventListener("change", (e) => { forgeHotkeys.use(e.target.value); render(); });
    box.querySelector(".forge-hk-search").addEventListener("input", () => render());
    box.querySelector('[data-hk="dup"]').addEventListener("click", () => {
      // no browser dialogs inside LOKI's window: the copy gets a name (rename by exporting / importing)
      forgeHotkeys.duplicate(forgeHotkeys.active() === FORGE_KEYS_DEFAULT_SET ? "My_Hotkeys" : forgeHotkeys.active() + "_copy");
      render();
    });
    box.querySelector('[data-hk="del"]').addEventListener("click", () => { forgeHotkeys.remove(forgeHotkeys.active()); render(); });
    box.querySelector('[data-hk="reset"]').addEventListener("click", () => { forgeHotkeys.resetActive(); render(); });
    box.querySelector('[data-hk="export"]').addEventListener("click", async () => {
      const text = forgeHotkeys.export();
      let ok = false;
      try { await navigator.clipboard.writeText(text); ok = true; } catch (_) { ok = false; }
      note(ok ? "Copied " + forgeHotkeys.active() + " to the clipboard." : "Copy the text below.");
      if (!ok) showText(text);
    });
    box.querySelector('[data-hk="import"]').addEventListener("click", () => showText("", true));
    // drag by the title, like a pro tool window
    const title = box.querySelector(".forge-hk-title");
    title.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button")) return;
      const r = box.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      title.setPointerCapture(e.pointerId);
      const mv = (ev) => { box.style.left = Math.max(0, ev.clientX - dx) + "px"; box.style.top = Math.max(0, ev.clientY - dy) + "px"; box.style.right = "auto"; };
      const up = () => { title.removeEventListener("pointermove", mv); title.removeEventListener("pointerup", up); };
      title.addEventListener("pointermove", mv); title.addEventListener("pointerup", up);
    });
  }
  function note(text, bad) { const n = box.querySelector(".forge-hk-note"); n.textContent = text || ""; n.classList.toggle("bad", !!bad); }
  function showText(text, importing) {
    let ta = box.querySelector(".forge-hk-text");
    if (!ta) {
      ta = document.createElement("div"); ta.className = "forge-hk-text";
      ta.innerHTML = '<textarea rows="5" spellcheck="false"></textarea><div><button type="button" data-hk="go">Import this set</button><button type="button" data-hk="cancel">Close</button></div>';
      box.querySelector(".forge-hk-list").before(ta);
      ta.querySelector('[data-hk="cancel"]').addEventListener("click", () => ta.remove());
      ta.querySelector('[data-hk="go"]').addEventListener("click", () => {
        try { const n = forgeHotkeys.import(ta.querySelector("textarea").value); ta.remove(); render(); note("Imported " + n + "."); }
        catch (exc) { note("Could not import: " + exc.message, true); }
      });
    }
    ta.querySelector("textarea").value = text;
    ta.querySelector('[data-hk="go"]').hidden = !importing;
  }
  function render() {
    const sets = forgeHotkeys.sets(), active = forgeHotkeys.active();
    const sel = box.querySelector(".forge-hk-set");
    sel.textContent = "";
    for (const s of sets) { const o = document.createElement("option"); o.value = s; o.textContent = s + (s === FORGE_KEYS_DEFAULT_SET ? " (locked)" : ""); o.selected = s === active; sel.append(o); }
    box.querySelector('[data-hk="del"]').disabled = active === FORGE_KEYS_DEFAULT_SET;
    box.querySelector('[data-hk="reset"]').disabled = active === FORGE_KEYS_DEFAULT_SET;
    const q = (box.querySelector(".forge-hk-search").value || "").trim().toLowerCase();
    const list = box.querySelector(".forge-hk-list");
    list.textContent = "";
    const map = forgeKeyMap(), used = {};
    for (const [c, a] of Object.entries(map)) (used[a] = used[a] || []).push(c);
    const all = forgeHotkeys.actions(), placed = new Set();
    const groups = FORGE_KEY_GROUPS.map(([g, ids]) => [g, ids.filter((id) => all.includes(id))]);
    for (const [, ids] of groups) ids.forEach((id) => placed.add(id));
    groups.push(["Other", all.filter((id) => !placed.has(id)).sort((a, b) => forgeKeyActionName(a).localeCompare(forgeKeyActionName(b)))]);
    for (const [g, ids] of groups) {
      const rows = ids.filter((id) => !q || forgeKeyActionName(id).toLowerCase().includes(q) || id.toLowerCase().includes(q)
        || (used[id] || []).some((c) => c.includes(q) || forgeKeyLabel(c).toLowerCase().includes(q)));
      if (!rows.length) continue;
      const head = document.createElement("div"); head.className = "forge-hk-group"; head.textContent = g;
      list.append(head);
      for (const id of rows) list.append(row(id, used[id] || []));
    }
  }
  function row(id, chords) {
    const r = document.createElement("div"); r.className = "forge-hk-row"; r.dataset.action = id;
    const nm = document.createElement("span"); nm.className = "forge-hk-name"; nm.textContent = forgeKeyActionName(id);
    nm.title = id;
    r.append(nm);
    const keys = document.createElement("span"); keys.className = "forge-hk-keys";
    for (const c of chords) {
      const k = document.createElement("button"); k.type = "button"; k.className = "forge-hk-key"; k.textContent = forgeKeyLabel(c);
      k.title = "Click, then press a new key for " + forgeKeyActionName(id) + " (Backspace clears this one).";
      k.addEventListener("click", () => capture(k, id, c));
      keys.append(k);
    }
    const add = document.createElement("button"); add.type = "button"; add.className = "forge-hk-key add"; add.textContent = chords.length ? "+" : "set key";
    add.title = "Add a key for " + forgeKeyActionName(id) + ".";
    add.addEventListener("click", () => capture(add, id, null));
    keys.append(add);
    r.append(keys);
    return r;
  }
  function capture(btn, action, old) {
    btn.textContent = "press a key…"; btn.classList.add("capturing"); box.dataset.capturing = "1";
    const done = () => { btn.classList.remove("capturing"); delete box.dataset.capturing; document.removeEventListener("keydown", onKey, true); };
    function onKey(e) {
      e.preventDefault(); e.stopImmediatePropagation();
      const chord = forgeKeyChord(e);
      if (!chord) return;                               // a lone modifier: wait for the key
      done();
      if (chord === "escape") { render(); return; }
      if ((chord === "backspace" || chord === "delete") && old) { forgeHotkeys.unbind(action, old); render(); note(forgeKeyLabel(old) + " cleared."); return; }
      if (chord === "space" || chord === "escape") { render(); note("Space and Esc stay the hotbox and cancel.", true); return; }
      const was = forgeKeyAction(chord);
      if (old) forgeHotkeys.unbind(action, old);
      const set = forgeHotkeys.bind(chord, action);
      render();
      note(forgeKeyLabel(chord) + " = " + forgeKeyActionName(action) + (was && was !== action ? " (was " + forgeKeyActionName(was) + ")" : "") + " in " + set + ".");
    }
    document.addEventListener("keydown", onKey, true);
  }
  if (show !== false) { render(); box.hidden = false; }
  return box;
}
