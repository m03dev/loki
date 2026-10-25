// Forge's Settings window (owner 2026-10-25: "the preference window in forge needs a hotkey tab and the entire window
// needs rework - it should be an actual settings window with useful things ... i want to be able to change my hotkeys,
// the way i pivot or move, everything should be modular"). Maya's Preferences is the model: categories on the left,
// the settings on the right, every change live and remembered.
//
//   ForgeSettings.get(key) / set(key, value) / on(fn)    the store (localStorage "loki-forge-settings"); the systems
//                                                        read it when they act, so a change applies at once
//   ForgeSettings.open(tab)                              the window (Windows > Settings/Preferences > Preferences)
//
// Tabs: Interface, Navigation (camera buttons, speeds, Maya / middle-mouse styles), Manipulators (handle size, axes,
// pivot placement, step snaps), Selection (soft selection defaults, falloff mode), Create (object / component mode,
// camera), Hotkeys (the Hotkey Editor, inside), Menus (Menu Settings, inside), Tools (the tools' limits and presets).
// Plain DOM, CSP script-src 'self'; sizes in %, it never overlaps the edges of the window.
"use strict";

const ForgeSettings = (() => {
  const STORE = "loki-forge-settings";
  const DEFAULTS = {
    // navigation
    navStyle: "maya",          // maya: Alt/Option (or Cmd) + left / middle / right = tumble / track / dolly
                               // mmb: the middle button alone tumbles, Shift + middle tracks, Ctrl + middle dollies
    tumbleSpeed: 1, trackSpeed: 1, dollySpeed: 1, wheelSpeed: 1, invertWheel: false,
    // manipulators
    handleSize: 1, axes: "object", pivotPlacement: "bbox",   // bbox (Maya) | median | last
    snapMove: 0, snapRotate: 15, snapScale: 0.1,             // the step snap (j): 0 = the grid step
    // selection
    softRadius: 0.25, softFalloff: "smooth", softMode: "volume",
    // create
    createMode: "object", createFrames: false,
    // interface
    accent: "#3d84c8", uiScale: 1,
  };
  let cache = null;
  const subs = new Set();
  function load() {
    if (cache) return cache;
    let s = {};
    try { s = JSON.parse(localStorage.getItem(STORE) || "{}") || {}; } catch (_) { s = {}; }
    // the old create-mode switch (loki-forge-create-mode) still counts
    try { if (localStorage.getItem("loki-forge-create-mode") === "component" && !s.createMode) s.createMode = "component"; } catch (_) { /* private */ }
    cache = Object.assign({}, DEFAULTS, s);
    return cache;
  }
  const get = (k) => load()[k];
  function set(k, v) {
    const s = load();
    s[k] = v;
    try { localStorage.setItem(STORE, JSON.stringify(s)); } catch (_) { /* private window: this session only */ }
    if (k === "createMode") { try { localStorage.setItem("loki-forge-create-mode", v); } catch (_) { /* private */ } }
    apply(k);
    for (const fn of subs) { try { fn(k, v); } catch (_) { /* a listener's own problem */ } }
  }
  function reset() { cache = Object.assign({}, DEFAULTS); try { localStorage.removeItem(STORE); } catch (_) { /* private */ } for (const k of Object.keys(DEFAULTS)) apply(k); }
  const on = (fn) => { subs.add(fn); return () => subs.delete(fn); };

  // settings that change something on screen right away
  function apply(k) {
    const v = typeof forge !== "undefined" && forge.view;
    if (k === "accent" || k == null) document.documentElement.style.setProperty("--fm-accent", get("accent"));
    if ((k === "handleSize" || k == null) && v) for (const tc of [v.transform, v.gizmo]) if (tc && tc.setSize) tc.setSize(0.8 * get("handleSize"));
    if ((k === "axes" || k == null) && v && typeof forgeProSpace === "function") forgeProSpace(v, get("axes") === "world" ? "world" : "object");
    if ((k === "softRadius" || k === "softFalloff" || k === "softMode" || k == null) && v && v.setProportional && v.edit)
      v.setProportional(null, get("softRadius"), get("softFalloff"), get("softMode"));
    if ((k === "uiScale" || k == null)) { const f = document.getElementById("forge"); if (f) f.style.zoom = get("uiScale") !== 1 ? String(get("uiScale")) : ""; }
  }

  // ---------------------------------------------------------------- the window
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  function row(label, help, input) {
    const r = el("label", "fset-row");
    const t = el("span", "fset-label"); t.append(el("b", "", label)); if (help) t.append(el("small", "", help));
    r.append(t, input); return r;
  }
  function choice(key, opts) {
    const s = el("select", "fset-input");
    for (const [v, t] of opts) s.append(new Option(t, v));
    s.value = String(get(key));
    s.addEventListener("change", () => set(key, s.value));
    return s;
  }
  function toggle(key) {
    const c = el("input", "fset-check"); c.type = "checkbox"; c.checked = !!get(key);
    c.addEventListener("change", () => set(key, c.checked));
    return c;
  }
  function slider(key, min, max, step) {
    const w = el("span", "fset-slider");
    const r = el("input"); r.type = "range"; r.min = min; r.max = max; r.step = step; r.value = get(key);
    const n = el("input", "fset-num"); n.type = "number"; n.min = min; n.max = max; n.step = step; n.value = get(key);
    const put = (x) => { const v = Math.max(+min, Math.min(+max, +x)); if (!Number.isFinite(v)) return; r.value = n.value = v; set(key, v); };
    r.addEventListener("input", () => put(r.value)); n.addEventListener("change", () => put(n.value));
    for (const i of [r, n]) i.addEventListener("keydown", (e) => e.stopPropagation());
    w.append(r, n); return w;
  }
  function color(key) {
    const c = el("input", "fset-color"); c.type = "color"; c.value = get(key);
    c.addEventListener("input", () => set(key, c.value)); return c;
  }
  // an existing editor moved into a tab (its own window chrome hidden there)
  function host(pane, id, make) {
    let node = document.getElementById(id);
    if (!node && make) { make(); node = document.getElementById(id); }
    if (!node) { pane.append(el("p", "fset-note", "Not available in this window.")); return; }
    node.hidden = false; node.classList.add("fset-hosted");
    pane.append(node);
  }

  const TABS = [
    ["interface", "Interface", (p) => {
      p.append(el("h3", "", "Interface"),
        row("Accent colour", "Menus, highlights and switches.", color("accent")),
        row("Interface size", "Scale Forge's panels and menus (vertical monitors: a little smaller).", slider("uiScale", 0.75, 1.5, 0.05)));
      // the UI elements (Windows > UI Elements), the chrome's own list
      if (typeof FMY_UI !== "undefined" && typeof fmyUi === "function" && typeof fmyUiSet === "function") {
        p.append(el("h3", "", "Show"));
        for (const [k, label] of Object.entries(FMY_UI)) {
          const c = el("input", "fset-check"); c.type = "checkbox"; c.checked = !!fmyUi()[k];
          c.addEventListener("change", () => fmyUiSet(k, c.checked));
          p.append(row(label, "", c));
        }
      }
    }],
    ["navigation", "Navigation", (p) => {
      p.append(el("h3", "", "Camera"),
        row("Style", "How the mouse moves the view.", choice("navStyle", [["maya", "Maya / Unreal: Alt (Option / Cmd) + left tumble, middle track, right dolly"],
          ["mmb", "Middle mouse: middle tumble, Shift + middle track, Ctrl + middle dolly"]])),
        row("Tumble speed", "", slider("tumbleSpeed", 0.2, 3, 0.05)),
        row("Track speed", "", slider("trackSpeed", 0.2, 3, 0.05)),
        row("Dolly speed", "", slider("dollySpeed", 0.2, 3, 0.05)),
        row("Wheel zoom speed", "", slider("wheelSpeed", 0.2, 3, 0.05)),
        row("Invert wheel zoom", "Wheel up zooms out.", toggle("invertWheel")));
    }],
    ["manipulators", "Manipulators", (p) => {
      p.append(el("h3", "", "Handles"),
        row("Handle size", "The move / rotate / scale handles (- and = change it too).", slider("handleSize", 0.3, 3, 0.05)),
        row("Axes", "Which way the handles point.", choice("axes", [["object", "Object"], ["world", "World"]])),
        el("h3", "", "Pivot"),
        row("Component pivot", "Where the handle sits for picked vertices / edges / faces.", choice("pivotPlacement",
          [["bbox", "Centre of the bounding box (Maya)"], ["median", "Average of the picked points"], ["last", "Last picked vertex"]])),
        el("h3", "", "Step snap (hold j)"),
        row("Move step", "0 = the grid step.", slider("snapMove", 0, 5, 0.05)),
        row("Rotate step (degrees)", "", slider("snapRotate", 1, 90, 1)),
        row("Scale step", "", slider("snapScale", 0.01, 1, 0.01)));
    }],
    ["selection", "Selection", (p) => {
      p.append(el("h3", "", "Soft selection"),
        row("Falloff radius", "A share of the model's size.", slider("softRadius", 0.02, 2, 0.01)),
        row("Falloff curve", "", choice("softFalloff", ["smooth", "sphere", "root", "inverse", "sharp", "linear", "constant"].map((f) => [f, f[0].toUpperCase() + f.slice(1)]))),
        row("Falloff mode", "Volume: through the air. Surface: along the mesh (a lip moves without the other).", choice("softMode", [["volume", "Volume"], ["surface", "Surface"]])));
    }],
    ["create", "Create", (p) => {
      p.append(el("h3", "", "New objects"),
        row("Open in", "What a new cube / sphere ... is in when it appears.", choice("createMode", [["object", "Object mode, selected (Maya)"], ["component", "Component mode"]])),
        row("Frame the new object", "Off: the camera stays where it is (Maya / Unreal).", toggle("createFrames")));
    }],
    ["hotkeys", "Hotkeys", (p) => { host(p, "forge-hotkeys", () => { if (typeof forgeHotkeyEditor === "function") forgeHotkeyEditor(true); }); }],
    ["menus", "Menus", (p) => { host(p, "fmenu-settings", () => { if (typeof forgeMenusSettings === "function") forgeMenusSettings(); }); }],
  ];

  function open(tab) {
    let w = document.getElementById("forge-settings");
    if (!w) {
      w = el("div", "fset"); w.id = "forge-settings"; w.setAttribute("role", "dialog"); w.setAttribute("aria-label", "Settings");
      const head = el("div", "fset-head");
      head.append(el("span", "fset-title", "Settings"));
      const resetB = el("button", "fset-btn", "Reset all"); resetB.type = "button"; resetB.title = "Every setting back to the default (hotkey sets stay).";
      resetB.addEventListener("click", () => { reset(); show(w.dataset.tab); });
      const x = el("button", "fset-x", "×"); x.type = "button"; x.title = "Close (Esc)"; x.setAttribute("aria-label", "Close");
      x.addEventListener("click", close);
      head.append(resetB, x);
      const body = el("div", "fset-body");
      const nav = el("nav", "fset-nav"); nav.setAttribute("role", "tablist");
      for (const [id, label] of TABS) {
        const b = el("button", "fset-tab", label); b.type = "button"; b.dataset.tab = id; b.setAttribute("role", "tab");
        b.addEventListener("click", () => show(id)); nav.append(b);
      }
      const pane = el("section", "fset-pane");
      body.append(nav, pane); w.append(head, body);
      w.addEventListener("keydown", (e) => { if (e.key === "Escape" && !w.querySelector("[data-capturing]")) { e.stopPropagation(); close(); } });
      document.body.append(w);
    }
    w.hidden = false;
    show(tab || w.dataset.tab || "interface");
    return w;
  }
  function show(id) {
    const w = document.getElementById("forge-settings"); if (!w) return;
    const pane = w.querySelector(".fset-pane");
    // hosted editors go back to the body (hidden) before the pane is cleared, so they are never destroyed
    for (const n of pane.querySelectorAll(".fset-hosted")) { n.classList.remove("fset-hosted"); n.hidden = true; document.body.append(n); }
    pane.textContent = "";
    w.dataset.tab = id;
    for (const b of w.querySelectorAll(".fset-tab")) b.setAttribute("aria-selected", String(b.dataset.tab === id));
    const t = TABS.find((x) => x[0] === id) || TABS[0];
    t[2](pane);
  }
  function close() {
    const w = document.getElementById("forge-settings"); if (!w) return;
    for (const n of w.querySelectorAll(".fset-hosted")) { n.classList.remove("fset-hosted"); n.hidden = true; document.body.append(n); }
    w.hidden = true;
  }

  if (typeof FORGE_PRO_CMDS !== "undefined") {
    FORGE_PRO_CMDS.preferences = ["Settings / Preferences...", () => { open(); return "Settings: Interface, Navigation, Manipulators, Selection, Create, Hotkeys, Menus."; }];
    const he = FORGE_PRO_CMDS.hotkeyEditor;
    FORGE_PRO_CMDS.hotkeyEditor = [he ? he[0] : "Hotkey Editor", () => { open("hotkeys"); return "Hotkeys: click a key box, press the new key."; }];
    FORGE_PRO_CMDS.menuSettings = ["Menu Settings...", () => { open("menus"); return ""; }];
  }
  document.addEventListener("DOMContentLoaded", () => apply(null));
  return { get, set, on, reset, open, close, DEFAULTS, apply };
})();
window.ForgeSettings = ForgeSettings;
