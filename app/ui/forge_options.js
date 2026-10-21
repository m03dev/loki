// Forge - the Options panel (the cog): one place for the quick options.
//   - Interface: which of the on-screen elements show (the chrome's own UI-element list, remembered).
//   - Options: the limits of the tools - grid / snap step, brush size and strength, symmetry, auto key, display -
//     each with its own min / max / step, so every value is adjustable and stays inside its limits.
//   - Presets: save the whole set under a name, apply it, delete it (localStorage, per machine).
//   - Any row can be hidden from the panel (Show hidden brings them back), so the cog shows only what you use.
// Re-implemented from the standard "quick settings / cog" model.
const FORGE_OPT = [
  { key: "gridStep", label: "Grid step", min: 0.05, max: 2, step: 0.05, get: (v) => v.pro.gridStep, set: (v, x) => { v.pro.gridStep = x; if (v.pro.grid) v.pro.grid.scale.setScalar(1); } },
  { key: "snapGrid", label: "Snap: grid", kind: "bool", get: (v) => !!v.pro.snap.grid, set: (v, x) => { v.pro.snap.grid = !!x; } },
  { key: "snapPoint", label: "Snap: point", kind: "bool", get: (v) => !!v.pro.snap.point, set: (v, x) => { v.pro.snap.point = !!x; } },
  { key: "snapEdge", label: "Snap: edge", kind: "bool", get: (v) => !!v.pro.snap.edge, set: (v, x) => { v.pro.snap.edge = !!x; } },
  { key: "brushSize", label: "Brush size", min: 0.02, max: 1, step: 0.01, get: (v) => v.brush.radius, set: (v, x) => { v.brush.radius = x; } },
  { key: "brushStrength", label: "Brush strength", min: 0.05, max: 1, step: 0.05, get: (v) => v.brush.strength, set: (v, x) => { v.brush.strength = x; } },
  { key: "symX", label: "Symmetry X", kind: "bool", get: (v) => !!(v.brush.symBits & 1), set: (v, x) => { v.brush.symBits = (v.brush.symBits & ~1) | (x ? 1 : 0); v.brush.symmetry = !!v.brush.symBits; } },
  { key: "symY", label: "Symmetry Y", kind: "bool", get: (v) => !!(v.brush.symBits & 2), set: (v, x) => { v.brush.symBits = (v.brush.symBits & ~2) | (x ? 2 : 0); v.brush.symmetry = !!v.brush.symBits; } },
  { key: "symZ", label: "Symmetry Z", kind: "bool", get: (v) => !!(v.brush.symBits & 4), set: (v, x) => { v.brush.symBits = (v.brush.symBits & ~4) | (x ? 4 : 0); v.brush.symmetry = !!v.brush.symBits; } },
  { key: "radial", label: "Radial symmetry", min: 0, max: 8, step: 1, get: (v) => v.brush.radial | 0, set: (v, x) => { v.brush.radial = x | 0; } },
  { key: "symModel", label: "Modelling symmetry", kind: "bool", get: (v) => !!v.brush.symModel, set: (v, x) => { v.brush.symModel = !!x; } },
  { key: "autoKey", label: "Auto Keyframe", kind: "bool", get: (v) => !!(v.tree && v.tree.autoKey), set: (v, x) => { if (v.tree && v.tree.api) v.tree.api.setAutoKey(!!x); } },
  { key: "prop", label: "Soft selection", kind: "bool", get: (v) => !!(v.edit && v.edit.prop), set: (v, x) => { if (v.edit) v.edit.prop = !!x; } },
  { key: "propRadius", label: "Falloff radius", min: 0.02, max: 1, step: 0.01, get: (v) => (v.edit && v.edit.propRadius) || 0.25, set: (v, x) => { if (v.edit) v.edit.propRadius = x; } },
  { key: "xray", label: "X-ray", kind: "bool", get: (v) => !!(v.edit && v.edit.xray), set: (v, x) => { if (v.edit) v.edit.xray = !!x; } },
  { key: "wire", label: "Wireframe", kind: "bool", get: (v) => !!v.wire, set: (v, x) => { v.wire = !!x; } },
];
const FORGE_OPT_STORE = "loki-forge-quickoptions";

function forgeOptionsAttach(view) {
  const stage = (document.getElementById("forge-view") || {}).parentElement;
  if (!stage || document.getElementById("forge-options")) return null;

  let state = { hidden: [], presets: {}, opts: {} };
  try { state = Object.assign(state, JSON.parse(localStorage.getItem(FORGE_OPT_STORE) || "{}") || {}); } catch (exc) { /* private mode */ }
  if (!Array.isArray(state.hidden)) state.hidden = [];
  if (!state.presets) state.presets = {};
  if (!state.opts) state.opts = {};
  const save = () => { try { localStorage.setItem(FORGE_OPT_STORE, JSON.stringify(state)); } catch (exc) { /* private mode */ } };

  const btn = document.createElement("button");
  btn.type = "button"; btn.id = "forge-options-btn"; btn.className = "forge-float forge-opt-btn";
  btn.title = "Options: which interface elements show, the limits of the tools, and presets of the lot.";
  btn.textContent = "\u2699";                       // the cog
  stage.append(btn);

  const panel = document.createElement("div");
  panel.className = "forge-float forge-optpnl"; panel.id = "forge-options"; panel.hidden = true;
  const head = document.createElement("div"); head.className = "fx-head";
  const title = document.createElement("b"); title.textContent = "Options";
  const reset = document.createElement("button"); reset.type = "button"; reset.className = "mini forge-btn"; reset.id = "forge-opt-reset"; reset.textContent = "Reset";
  const close = document.createElement("button"); close.type = "button"; close.className = "mini forge-btn"; close.textContent = "\u00d7";
  head.append(title, reset, close);
  const uiSec = document.createElement("div"); uiSec.className = "fx-sec"; uiSec.id = "forge-opt-ui";
  const optSec = document.createElement("div"); optSec.className = "fx-sec"; optSec.id = "forge-opt-opts";
  const presetRow = document.createElement("div"); presetRow.className = "fx-row"; presetRow.id = "forge-opt-presetrow";
  const sel = document.createElement("select"); sel.id = "forge-opt-presets"; sel.className = "forge-opt-sel";
  const nameIn = document.createElement("input"); nameIn.type = "text"; nameIn.id = "forge-opt-name"; nameIn.className = "forge-opt-name"; nameIn.placeholder = "preset name";
  const saveBtn = document.createElement("button"); saveBtn.type = "button"; saveBtn.id = "forge-opt-save"; saveBtn.className = "mini forge-btn"; saveBtn.textContent = "Save";
  const delBtn = document.createElement("button"); delBtn.type = "button"; delBtn.id = "forge-opt-del"; delBtn.className = "mini forge-btn"; delBtn.textContent = "Delete";
  presetRow.append(sel, nameIn, saveBtn, delBtn);
  const showHidden = document.createElement("div"); showHidden.className = "fx-sec"; showHidden.id = "forge-opt-hidden";
  panel.append(head, uiSec, optSec, presetRow, showHidden);
  stage.append(panel);

  const live = () => (typeof forge !== "undefined" && forge.view ? forge.view : view);

  function uiRows() {
    uiSec.textContent = "";
    uiSec.append(mkHead("Interface"));
    const U = (typeof FMY_UI !== "undefined") ? FMY_UI : {};
    const cur = (typeof fmyUi === "function") ? fmyUi() : {};
    for (const k of Object.keys(U)) {
      const row = document.createElement("label"); row.className = "forge-optrow"; row.dataset.ui = k;
      const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !!cur[k]; cb.id = "forge-opt-ui-" + k;
      cb.addEventListener("change", () => { if (typeof fmyUiSet === "function") fmyUiSet(k, cb.checked); });
      const s = document.createElement("span"); s.textContent = U[k];
      row.append(cb, s); uiSec.append(row);
    }
  }
  function mkHead(text) {
    const h = document.createElement("div"); h.className = "fx-head2"; h.textContent = text; return h;
  }
  function optRows() {
    const v = live();
    optSec.textContent = "";
    optSec.append(mkHead("Options"));
    for (const o of FORGE_OPT) {
      if (!o || state.hidden.includes(o.key) || !v) continue;
      const row = document.createElement("div"); row.className = "forge-optrow"; row.dataset.opt = o.key;
      const val = o.get(v);
      if (o.kind === "bool") {
        const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !!val; cb.id = "forge-opt-" + o.key;
        cb.addEventListener("change", () => { o.set(v, cb.checked); state.opts[o.key] = cb.checked; save(); });
        const s = document.createElement("span"); s.textContent = o.label;
        row.append(cb, s);
      } else {
        const s = document.createElement("span"); s.className = "forge-opt-label";
        s.textContent = o.label + " (" + o.min + "-" + o.max + ")";
        const num = document.createElement("input"); num.type = "number"; num.className = "forge-opt-num";
        num.id = "forge-opt-" + o.key; num.min = String(o.min); num.max = String(o.max); num.step = String(o.step);
        num.value = String(val);
        const clamp = (x) => Math.min(o.max, Math.max(o.min, x));
        const rng = document.createElement("input"); rng.type = "range"; rng.className = "forge-opt-range";
        rng.min = String(o.min); rng.max = String(o.max); rng.step = String(o.step); rng.value = String(clamp(val));
        const keep = (x) => { state.opts[o.key] = x; save(); };
        rng.addEventListener("input", () => { const x = clamp(Number(rng.value)); num.value = String(x); o.set(v, x); keep(x); });
        num.addEventListener("change", () => { const x = clamp(Number(num.value)); num.value = String(x); rng.value = String(x); o.set(v, x); keep(x); });
        const hideBtn = document.createElement("button"); hideBtn.type = "button"; hideBtn.className = "forge-opt-x"; hideBtn.textContent = "\u00d7";
        hideBtn.title = "Hide this option from the panel (Show hidden brings it back).";
        hideBtn.addEventListener("click", () => { state.hidden.push(o.key); save(); render(); });
        row.append(s, rng, num, hideBtn);
      }
      optSec.append(row);
    }
  }
  function hiddenRows() {
    showHidden.textContent = "";
    if (!state.hidden.length) return;
    const b = document.createElement("button"); b.type = "button"; b.id = "forge-opt-showhidden";
    b.className = "mini forge-btn"; b.textContent = "Show hidden (" + state.hidden.length + ")";
    b.addEventListener("click", () => { state.hidden = []; save(); render(); });
    showHidden.append(b);
  }
  function presetRows() {
    sel.textContent = "";
    const none = document.createElement("option"); none.value = ""; none.textContent = "- preset -"; sel.append(none);
    for (const n of Object.keys(state.presets).sort()) { const o = document.createElement("option"); o.value = n; o.textContent = n; sel.append(o); }
    sel.addEventListener("change", () => { if (sel.value) apply(sel.value); });
  }
  function capture() {
    const v = live();
    const out = { ui: {}, opts: {} };
    const U = (typeof FMY_UI !== "undefined") ? FMY_UI : {};
    const cur = (typeof fmyUi === "function") ? fmyUi() : {};
    for (const k of Object.keys(U)) out.ui[k] = !!cur[k];
    for (const o of FORGE_OPT) if (v) out.opts[o.key] = o.get(v);
    return out;
  }
  function apply(name) {
    const p = state.presets[name];
    const v = live();
    if (!p || !v) return false;
    if (typeof fmyUiSet === "function") for (const k of Object.keys(p.ui || {})) fmyUiSet(k, p.ui[k]);
    for (const o of FORGE_OPT) if (o.key in (p.opts || {})) o.set(v, p.opts[o.key]);
    state.opts = Object.assign({}, p.opts || {}); save();
    render();
    if (typeof forgeSay === "function") forgeSay("Options preset: " + name + ".");
    return true;
  }
  function applyStored() {                    // the values the panel was last left on
    const v = live(); if (!v) return;
    for (const o of FORGE_OPT) if (o.key in state.opts) { try { o.set(v, state.opts[o.key]); } catch (exc) { /* a value the build no longer takes */ } }
  }
  function render() { uiRows(); optRows(); hiddenRows(); presetRows(); }

  btn.addEventListener("click", () => { panel.hidden = !panel.hidden; if (!panel.hidden) { applyStored(); render(); } if (view && view.resize) view.resize(); });
  close.addEventListener("click", () => { panel.hidden = true; });
  sel.addEventListener("pointerdown", presetRows);
  saveBtn.addEventListener("click", () => {
    const n = (nameIn.value || "").trim() || sel.value;
    if (!n) { if (typeof forgeSay === "function") forgeSay("Name the preset first.", true); return; }
    state.presets[n] = capture(); save(); nameIn.value = ""; render();
    if (typeof forgeSay === "function") forgeSay("Saved options preset \"" + n + "\".");
  });
  delBtn.addEventListener("click", () => {
    const n = sel.value; if (!n) return;
    delete state.presets[n]; save(); render();
    if (typeof forgeSay === "function") forgeSay("Deleted options preset \"" + n + "\".");
  });
  reset.addEventListener("click", () => {
    const v = live(); if (!v) return;
    for (const o of FORGE_OPT) {
      const d = ({ gridStep: 0.25, brushSize: 0.12, brushStrength: 0.5, radial: 0, propRadius: 0.25 })[o.key];
      if (d != null) o.set(v, d);
      else if (o.kind === "bool") o.set(v, ["snapGrid", "symX", "wire", "xray"].includes(o.key) ? false : false);
    }
    v.brush.symBits = 1; v.brush.symmetry = true;
    state.opts = {}; save();
    render();
    if (typeof forgeSay === "function") forgeSay("Options reset to their defaults.");
  });
  applyStored();
  view.forgeOptions = { open: (on) => { panel.hidden = on == null ? !panel.hidden : !on; if (!panel.hidden) render(); return !panel.hidden; },
    shown: () => !panel.hidden, preset: (n) => apply(n), savePreset: save, state: () => state };
  return panel;
}
window.forgeOptionsAttach = forgeOptionsAttach;
