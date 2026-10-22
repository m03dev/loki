// Forge's sculpt mode, redone (owner 2026-10-21 13:59: "sculpting needs a complete overhaul ... different functions when
// i right click ... a wheel with all the brushes ... a bar with brush icons that you can slide through horizontally
// just like zbrush for ipad ... modern and minimalist ... intuitive ... i cant even get out of the sculpting mode").
//
// On screen while sculpting (everything else of the old sculpt panels is one click away under "More"):
//   * the header, top centre: the brush's name, Symmetry X / Y / Z, Dynamic detail, the subdivision level stepper
//     (- L1/3 +), Remesh, Reduce, the matcap, More (the full engine settings) and Done (leave sculpt mode);
//   * two slim sliders on the left edge: Size and Strength (drag, or hold b / m and drag on the view as before);
//   * the brush strip along the bottom: every brush as an icon, slid sideways with the wheel, a drag or the arrows;
//     category chips above it (Favourites first) and a search; right-click a brush to add / remove it as a favourite;
//     Ctrl/Cmd+Shift+1-9 pick the first nine favourites.
//   * right button on the view: the sculpt wheel at the mouse - the favourite brushes around it, and Undo, Remesh,
//     Divide, Symmetry, Frame, All brushes and Exit Sculpt; press-drag-release picks like a marking menu, a quick
//     click keeps it open.
//   * leaving: Done, Esc, any other tool (q / w / e / r, F8 - as in the pro tool), the wheel's Exit Sculpt, or Menu Set:
//     Modeling. Every sculpt key is in Forge's one hotkey table (forge_keys.js, the Hotkey Editor's Sculpting group).
// Brushes are the sculpting engine's presets (vendor/sculpt/brushes.json via ForgeSculpt.library), or Forge's seven
// basic brushes when the engine is not loaded.
"use strict";

const FSC_STORE = "loki-forge-sculpt-ui";
const FSC_STICKY = { invert: false, smooth: false, mask: false };
const FSC_FAV_DEFAULT = ["Standard", "Clay", "Clay Strips", "Inflate", "Smooth", "Move", "Pinch", "Dam Standard", "Flatten", "Blob"];
const FSC_BASIC = { Standard: "draw", Clay: "draw", Inflate: "inflate", Smooth: "smooth", Flatten: "flatten", Move: "grab", Grab: "grab", Pinch: "pinch", Crease: "crease", "Dam Standard": "crease" };

// line icons on a ball, one per brush family (24 x 24, stroke = currentColor)
const FSC_ICON = {
  Standard: '<path d="M6 15c3-4 9-4 12 0"/><path d="M9 13.5c1.5-1.5 4.5-1.5 6 0"/>',
  Clay: '<path d="M5 15h14"/><path d="M7 15c1-3 9-3 10 0"/><path d="M8 12h8"/>',
  ClayStrips: '<path d="M5 16l14-6"/><path d="M6 13l12-5"/><path d="M7 19l12-5"/>',
  ClayBuildup: '<path d="M6 16h12M7 13h10M9 10h6"/>',
  Inflate: '<circle cx="12" cy="12" r="4"/><path d="M12 5v2M12 17v2M5 12h2M17 12h2"/>',
  Blob: '<circle cx="12" cy="12.5" r="4.5"/><circle cx="12" cy="12.5" r="1.5"/>',
  Smooth: '<path d="M5 14c2.5-3 4.5-3 7 0s4.5 3 7 0"/>',
  SmoothRelax: '<path d="M5 14c2.5-2 4.5-2 7 0s4.5 2 7 0"/><path d="M5 10h14"/>',
  Polish: '<path d="M5 15h14"/><path d="M8 11l8 0"/><path d="M10 8h4"/>',
  Flatten: '<path d="M5 13h14"/><path d="M7 17c2-2 8-2 10 0"/>',
  Planar: '<path d="M5 12h14"/><path d="M5 16l14-8"/>',
  Scrape: '<path d="M5 15c4-1 10-1 14 0"/><path d="M8 9l8 3"/>',
  MultiplaneScrape: '<path d="M5 16l7-6 7 6"/>',
  TrimDynamic: '<path d="M5 14h14"/><path d="M9 10l6 4"/>',
  TrimAdaptive: '<path d="M5 14h14"/><path d="M9 10l6 4"/>',
  Fill: '<path d="M6 16c2-4 10-4 12 0"/><path d="M8 16h8"/>',
  Layer: '<path d="M6 13h12M6 16h12"/>',
  Move: '<path d="M12 6v12M6 12h12"/><path d="M10 8l2-2 2 2M10 16l2 2 2-2"/>',
  MoveElastic: '<path d="M6 16c3-8 9-8 12 0"/><path d="M12 6v4"/>',
  MoveTopological: '<path d="M6 15c3-6 9-6 12 0"/><circle cx="12" cy="10" r="1.5"/>',
  MoveInfiniteDepth: '<path d="M12 5v14"/><path d="M8 9l4-4 4 4"/>',
  SnakeHook: '<path d="M7 17c0-6 4-10 10-10"/><path d="M14 5l3 2-2 3"/>',
  Pose: '<circle cx="12" cy="8" r="2"/><path d="M12 10v6M8 18l4-2 4 2"/>',
  Rotate: '<path d="M7 12a5 5 0 1 0 2-4"/><path d="M8 5v3h3"/>',
  Thumb: '<path d="M7 15c2-4 8-4 10 0"/><circle cx="12" cy="12" r="2"/>',
  Nudge: '<path d="M6 12h10"/><path d="M13 9l3 3-3 3"/>',
  ElasticScale: '<rect x="8" y="8" width="8" height="8" rx="1"/><path d="M5 5l3 3M19 19l-3-3"/>',
  ElasticTwist: '<path d="M7 9c4-3 10 0 10 3s-6 6-10 3"/>',
  Magnify: '<circle cx="11" cy="11" r="4"/><path d="M14 14l4 4"/>',
  Pinch: '<path d="M5 7l6 5-6 5M19 7l-6 5 6 5"/>',
  Crease: '<path d="M5 9c4 0 5 7 7 7s3-7 7-7"/>',
  DamStandard: '<path d="M5 10c4 0 5 6 7 6s3-6 7-6"/><path d="M12 16v2"/>',
  SurfaceNoise: '<path d="M5 13l2-2 2 2 2-2 2 2 2-2 2 2 2-2"/>',
  Displace: '<path d="M6 15h12"/><path d="M9 15V11M12 15V9M15 15v-3"/>',
  Cloth: '<path d="M6 8c2 2 4 2 6 0s4-2 6 0M6 12c2 2 4 2 6 0s4-2 6 0M6 16c2 2 4 2 6 0s4-2 6 0"/>',
  Tube: '<path d="M6 16c3-8 9-8 12 0"/><path d="M8 17c2-6 6-6 8 0"/>',
  Insert: '<circle cx="12" cy="11" r="3"/><path d="M6 16h12"/>',
  Alpha: '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M9 14l2-3 2 2 2-3"/>',
};
const fscIconOf = (b) => FSC_ICON[b.kernel] || (b.category === "Alpha Textures" ? FSC_ICON.Alpha : b.category === "Insert & Curve" ? FSC_ICON.Insert : FSC_ICON.Standard);
const fscSvg = (body, size) => '<svg viewBox="0 0 24 24" width="' + (size || 22) + '" height="' + (size || 22) + '" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + body + "</svg>";
const fscBall = (body) => '<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10.5" fill="rgba(255,255,255,.06)" stroke="rgba(255,255,255,.14)"/><g stroke="currentColor" stroke-width="1.5">' + body + "</g></svg>";
const FSC_UI_ICON = {
  done: '<path d="M5 12l4 4 10-10"/>', more: '<circle cx="6" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18" cy="12" r="1.2"/>',
  remesh: '<path d="M4 8h16M4 12h16M4 16h16M8 4v16M12 4v16M16 4v16"/>', reduce: '<path d="M12 4l8 15H4z"/><path d="M9 10h6"/>',
  dyn: '<path d="M12 4l8 4-8 4-8-4z"/><path d="M4 12l8 4 8-4M4 16l8 4 8-4"/>', undo: '<path d="M9 7L4 12l5 5"/><path d="M4 12h10a5 5 0 0 1 0 10h-2"/>',
  frame: '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>', prev: '<path d="M14 6l-6 6 6 6"/>', next: '<path d="M10 6l6 6-6 6"/>',
  star: '<path d="M12 4l2.4 5 5.6.6-4.2 3.8 1.2 5.6L12 16.3 7 19l1.2-5.6L4 9.6 9.6 9z"/>', exit: '<path d="M14 5h5v14h-5"/><path d="M10 8l-4 4 4 4M6 12h10"/>',
  search: '<circle cx="11" cy="11" r="5"/><path d="M15 15l4 4"/>',
  mask: '<path d="M5 9c2-3 12-3 14 0v3c0 4-3.5 7-7 7s-7-3-7-7z"/><path d="M8 8l8 8"/>', unmask: '<path d="M5 9c2-3 12-3 14 0v3c0 4-3.5 7-7 7s-7-3-7-7z"/><path d="M9 12h6"/>',
  eye: '<path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z"/><circle cx="12" cy="12" r="2.5"/>', divide: '<path d="M12 4l8 15H4z"/><path d="M8 12h8M12 19l-4-7M12 19l4-7"/>',
};

function fscPrefs() {
  try { return Object.assign({ fav: FSC_FAV_DEFAULT.slice(), cat: "Favourites", recent: [] }, JSON.parse(localStorage.getItem(FSC_STORE) || "{}") || {}); }
  catch (_) { return { fav: FSC_FAV_DEFAULT.slice(), cat: "Favourites", recent: [] }; }
}
function fscSave(p) { try { localStorage.setItem(FSC_STORE, JSON.stringify(p)); } catch (_) { /* private window */ } }
const fscView = () => (typeof forge !== "undefined" ? forge.view : null);
const fscSay = (t, bad) => { if (typeof forgeSay === "function") forgeSay(t, bad); return t; };

// every brush: the engine's presets, else the basic seven
function fscBrushes() {
  const lib = (window.ForgeSculpt && ForgeSculpt.library) || [];
  if (lib.length) return lib;
  return (typeof FORGE_BRUSHES !== "undefined" ? FORGE_BRUSHES : []).map(([id, , name]) => ({ name, kernel: { draw: "Clay", grab: "Move" }[id] || name, category: "Basic", basic: id }));
}
function fscCurrent() {
  const v = fscView(); if (!v || !v.brush) return "";
  if (v.brush.tool === "lib" && v.brush.lib) return v.brush.lib;
  const b = (typeof FORGE_BRUSHES !== "undefined" ? FORGE_BRUSHES : []).find((x) => x[0] === v.brush.tool);
  return b ? (b[0] === "draw" ? "Clay" : b[2]) : "";
}
function fscPick(name) {
  const v = fscView(); if (!v || !v.brush) return "";
  const lib = window.ForgeSculpt && ForgeSculpt.libraryByName && ForgeSculpt.libraryByName[name];
  if (lib) { v.brush.tool = "lib"; v.brush.lib = name; }
  else {
    const all = fscBrushes(), b = all.find((x) => x.name === name);
    const id = (b && b.basic) || FSC_BASIC[name] || "draw";
    if (typeof forgeBrush === "function") forgeBrush(id); else v.brush.tool = id;
    v.brush.lib = "";
  }
  const p = fscPrefs(); p.recent = [name].concat(p.recent.filter((x) => x !== name)).slice(0, 12); fscSave(p);
  fscSync();
  return fscSay("Brush: " + name + ".");
}

// ------------------------------------------------------------------------------------------ build
function fscBuild() {
  const stage = document.getElementById("forge-stage");
  if (!stage || document.getElementById("fsc-head")) return;
  const el = (tag, cls, html) => { const n = document.createElement(tag); if (cls) n.className = cls; if (html != null) n.innerHTML = html; return n; };
  const btn = (icon, label, what, fn, cls) => {
    const b = el("button", "fsc-btn" + (cls ? " " + cls : ""), fscSvg(FSC_UI_ICON[icon] || icon, 18));
    b.type = "button"; b.title = label + (what ? " - " + what : ""); b.setAttribute("aria-label", label);
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(b); fscSync(); });
    return b;
  };
  const txt = (t, label, what, fn, cls) => { const b = el("button", "fsc-btn fsc-txt" + (cls ? " " + cls : ""), t); b.type = "button"; b.title = label + (what ? " - " + what : ""); b.addEventListener("click", (e) => { e.stopPropagation(); fn(b); fscSync(); }); return b; };
  const sep = () => el("span", "fsc-sep");

  // ---- header
  const head = el("div", "fsc-head"); head.id = "fsc-head";
  const name = el("span", "fsc-name"); name.id = "fsc-brushname";
  const sym = el("span", "fsc-group");
  for (const [ax, bit] of [["X", 1], ["Y", 2], ["Z", 4]]) {
    const sb = txt(ax, "Symmetry " + ax, "mirror strokes across the object's " + ax + " plane", () => {
      const v = fscView(); if (!v) return;
      const bits = ((v.brush.symBits | 0) ^ bit);
      if (typeof forgeProSym === "function") fscSay(forgeProSym(v, bits)); else { v.brush.symBits = bits; v.brush.symmetry = !!bits; }
    }, "fsc-sym");
    sb.dataset.bit = String(bit);
    sym.append(sb);
  }
  const dyn = btn("dyn", "Dynamic detail", "add and remove triangles under the brush as you sculpt", () => { const d = document.getElementById("forge-sculpt-dyn"); if (d) d.click(); }, "fsc-dyn");
  const lvl = el("span", "fsc-group fsc-levels");
  const lvlTxt = el("span", "fsc-level"); lvlTxt.id = "fsc-level";
  lvl.append(btn("prev", "Lower level", "step down a subdivision level (big forms)", () => fscLevel(-1)), lvlTxt,
    btn("next", "Higher level / Divide", "step up a level, or add one (4x the faces)", () => fscLevel(1)));
  const remesh = btn("remesh", "Remesh", "rebuild as one even surface (voxels)", () => fscOp("sculptRemesh"));
  const reduce = btn("reduce", "Reduce", "far fewer triangles, same shape (C++ decimation)", () => fscOp("sculptReduce"));
  const cap = el("button", "fsc-btn fsc-cap"); cap.type = "button"; cap.id = "fsc-matcap"; cap.title = "Matcap - click for the next look, right-click for the previous";
  cap.addEventListener("click", (e) => { e.stopPropagation(); if (typeof forgeCycleMatcap === "function") forgeCycleMatcap(1); fscSync(); });
  cap.addEventListener("contextmenu", (e) => { e.preventDefault(); if (typeof forgeCycleMatcap === "function") forgeCycleMatcap(-1); fscSync(); });
  const more = btn("more", "More", "every sculpting setting: falloff, stroke, detail, resolution, matcaps", () => { document.getElementById("forge")?.classList.toggle("fsc-more"); });
  more.id = "fsc-more";
  const done = el("button", "fsc-done", fscSvg(FSC_UI_ICON.done, 16) + "<span>Done</span>"); done.type = "button"; done.id = "fsc-done";
  done.title = "Done - leave sculpt mode (Esc, or pick another tool: q, w, e, r)";
  done.addEventListener("click", (e) => { e.stopPropagation(); fscExit(); });
  const chip = el("span", "fsc-chip-mode", "<i></i>Sculpt"); chip.title = "You are sculpting - Done, Esc or another tool (q, w, e, r) leaves";
  const undo = btn("undo", "Undo", "Ctrl+Z", () => { const v = fscView(); if (v && v.undo) v.undo(); });
  const redo = btn("undo", "Redo", "Ctrl+Shift+Z", () => { const v = fscView(); if (v && v.redo) v.redo(); }, "fsc-redo");
  head.append(chip, name, sep(), sym, dyn, sep(), lvl, remesh, reduce, sep(), undo, redo, cap, more, done);

  // ---- the two sliders on the left
  const side = el("div", "fsc-side"); side.id = "fsc-side";
  const sliders = el("div", "fsc-sliders");
  sliders.append(fscSlider("size", "Size", "brush radius (or hold b and drag)", 0.02, 0.4), fscSlider("strength", "Strength", "how hard each dab pushes (or hold m and drag)", 0.05, 1));
  side.append(sliders);
  const tools = el("div", "fsc-tools");
  // sticky toggles (Nomad's left bar): tap = stays on, the same as holding Ctrl (invert) or Shift (smooth)
  const sticky = (key, label, what, icon) => {
    const b = btn(icon, label, what, () => { FSC_STICKY[key] = !FSC_STICKY[key]; }, "fsc-sticky");
    b.dataset.sticky = key; return b;
  };
  tools.append(sticky("invert", "Invert", "dig in instead of building up - the same as holding Ctrl / Cmd", '<path d="M6 12h12"/>'),
    sticky("smooth", "Smooth", "every stroke smooths - the same as holding Shift", '<path d="M5 14c2.5-3 4.5-3 7 0s4.5 3 7 0"/>'));
  // masking: paint a mask (frozen, drawn dark), invert / clear it, hide what is masked
  const msep = el("span", "fsc-hsep");
  const mpaint = sticky("mask", "Mask", "paint a mask: masked parts never move (or hold Ctrl+Shift and drag). With Mask on, Ctrl+drag paints the mask away", '<path d="M5 9c2-3 12-3 14 0v3c0 4-3.5 7-7 7s-7-3-7-7z"/><circle cx="9.5" cy="11" r="1.2"/><circle cx="14.5" cy="11" r="1.2"/>');
  const mbtn = (icon, label, what, op) => { const b = btn(icon, label, what, () => fscSay(ForgeMask.op(op)), "fsc-sticky fsc-maskbtn"); b.dataset.op = op; return b; };
  tools.append(mpaint,
    mbtn('<path d="M5 9c2-3 12-3 14 0v3c0 4-3.5 7-7 7s-7-3-7-7z"/><path d="M8 8l8 8"/>', "Invert mask", "masked becomes free and free becomes masked (Ctrl/Cmd+Shift+I while sculpting, as in the pro tool)", "maskInvert"),
    mbtn('<path d="M5 9c2-3 12-3 14 0v3c0 4-3.5 7-7 7s-7-3-7-7z"/><path d="M9 12h6"/>', "Clear mask", "nothing masked (Shift+U)", "maskClear"),
    mbtn('<path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z"/><path d="M4 20L20 4"/>', "Hide masked", "hide the masked parts / show everything again (Alt/Option+Shift+H)", "maskHideToggle"));
  tools.lastChild.dataset.maskState = "hidden";
  side.append(msep, tools);

  // ---- the brush strip
  const strip = el("div", "fsc-strip"); strip.id = "fsc-strip";
  const top = el("div", "fsc-striptop");
  const chips = el("div", "fsc-chips"); chips.id = "fsc-chips";
  const search = el("label", "fsc-search", fscSvg(FSC_UI_ICON.search, 14));
  const q = el("input"); q.type = "search"; q.id = "fsc-q"; q.placeholder = "Search brushes";
  q.addEventListener("keydown", (e) => e.stopPropagation());
  q.addEventListener("input", () => fscFill());
  search.append(q);
  top.append(chips, search);
  const row = el("div", "fsc-rowwrap");
  const left = btn("prev", "Scroll left", "", () => { list.scrollBy({ left: -list.clientWidth * 0.8, behavior: "smooth" }); }, "fsc-arrow");
  const right = btn("next", "Scroll right", "", () => { list.scrollBy({ left: list.clientWidth * 0.8, behavior: "smooth" }); }, "fsc-arrow");
  const list = el("div", "fsc-list"); list.id = "fsc-list";
  // the wheel slides it sideways; a drag on empty space slides it too
  list.addEventListener("wheel", (e) => { if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) { list.scrollLeft += e.deltaY; e.preventDefault(); } }, { passive: false });
  let drag = null;
  list.addEventListener("pointerdown", (e) => { if (e.button !== 0) return; drag = { x: e.clientX, s: list.scrollLeft, moved: false }; });
  list.addEventListener("pointermove", (e) => { if (!drag) return; const dx = e.clientX - drag.x; if (Math.abs(dx) > 4) drag.moved = true; if (drag.moved) list.scrollLeft = drag.s - dx; });
  const end = () => { if (drag && drag.moved) list.dataset.justDragged = "1"; drag = null; setTimeout(() => { delete list.dataset.justDragged; }, 0); };
  list.addEventListener("pointerup", end); list.addEventListener("pointerleave", end);
  row.append(left, list, right);
  strip.append(top, row);

  stage.append(head, side, strip);
  fscChips(); fscFill(); fscSync();
}

function fscSlider(key, label, what, lo, hi) {
  const w = document.createElement("div");
  w.className = "fsc-slider"; w.dataset.key = key; w.title = label + " - " + what; w.setAttribute("role", "slider"); w.setAttribute("aria-label", label);
  w.innerHTML = '<div class="fsc-track"><div class="fsc-fill"></div></div><span class="fsc-slabel">' + label + '</span><span class="fsc-sval"></span>';
  const set = (ev) => {
    const r = w.querySelector(".fsc-track").getBoundingClientRect();
    const f = Math.max(0, Math.min(1, (r.bottom - ev.clientY) / (r.height || 1)));
    const v = fscView(); if (!v || !v.brush) return;
    const val = lo + (hi - lo) * f;
    if (key === "size") { v.brush.radius = val; const s = document.getElementById("forge-radius"); if (s) s.value = String(val); }
    else { v.brush.strength = val; const s = document.getElementById("forge-strength"); if (s) s.value = String(val); }
    v.dirty = true; fscSync();
  };
  w.addEventListener("pointerdown", (e) => { e.preventDefault(); e.stopPropagation(); try { w.setPointerCapture(e.pointerId); } catch (_) { /* gone */ } w.classList.add("drag"); set(e);
    const mv = (ev) => set(ev), up = () => { w.classList.remove("drag"); w.removeEventListener("pointermove", mv); w.removeEventListener("pointerup", up); };
    w.addEventListener("pointermove", mv); w.addEventListener("pointerup", up); });
  w.dataset.lo = lo; w.dataset.hi = hi;
  return w;
}

function fscCategories() {
  const cats = (window.ForgeSculpt && ForgeSculpt.categories && ForgeSculpt.categories.length) ? ForgeSculpt.categories.slice() : ["Basic"];
  return ["Favourites", "Recent"].concat(cats, ["All"]);
}
function fscChips() {
  const host = document.getElementById("fsc-chips"); if (!host) return;
  const p = fscPrefs();
  host.textContent = "";
  for (const c of fscCategories()) {
    const b = document.createElement("button"); b.type = "button"; b.className = "fsc-chip" + (c === p.cat ? " on" : ""); b.textContent = c === "Alpha Textures" ? "Alphas" : c;
    b.dataset.cat = c;
    b.addEventListener("click", (e) => { e.stopPropagation(); const pp = fscPrefs(); pp.cat = c; fscSave(pp); fscChips(); fscFill(); });
    host.append(b);
  }
  host.dataset.n = String(fscCategories().length);
}
function fscFill() {
  const list = document.getElementById("fsc-list"); if (!list) return;
  const p = fscPrefs(), all = fscBrushes(), q = ((document.getElementById("fsc-q") || {}).value || "").trim().toLowerCase();
  let items;
  if (q) items = all.filter((b) => (b.name + " " + b.kernel + " " + b.category).toLowerCase().includes(q));
  else if (p.cat === "Favourites") items = p.fav.map((n) => all.find((b) => b.name === n)).filter(Boolean);
  else if (p.cat === "Recent") items = p.recent.map((n) => all.find((b) => b.name === n)).filter(Boolean);
  else if (p.cat === "All") items = all;
  else items = all.filter((b) => b.category === p.cat);
  list.textContent = "";
  const cur = fscCurrent();
  items.forEach((b, i) => {
    const t = document.createElement("button");
    t.type = "button"; t.className = "fsc-tile" + (b.name === cur ? " on" : "") + (p.fav.includes(b.name) ? " fav" : "");
    t.dataset.brush = b.name;
    const key = p.cat === "Favourites" && !q && i < 9 ? " (" + (i + 1) + ")" : "";
    t.title = b.name + key + " - " + (b.category || "") + " · right-click: favourite, hotkey" + (p.cat === "Favourites" ? " · drag to reorder" : "");
    t.innerHTML = fscBall(fscIconOf(b)) + '<span class="fsc-tname">' + b.name + "</span>" + (key ? '<span class="fsc-key">' + (i + 1) + "</span>" : "");
    t.addEventListener("click", (e) => { e.stopPropagation(); if (list.dataset.justDragged) return; fscPick(b.name); });
    t.addEventListener("contextmenu", (e) => { e.preventDefault(); e.stopPropagation(); fscTileMenu(b.name, e.clientX, e.clientY); });
    const hk = Object.keys(p.keys || {}).find((k) => p.keys[k] === b.name);
    if (hk) { const kb = document.createElement("span"); kb.className = "fsc-hk"; kb.textContent = fscKeyLabel(hk); t.append(kb); }
    // favourites reorder by dragging a tile onto another
    if (p.cat === "Favourites" && !q) {
      t.draggable = true;
      t.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/fsc-brush", b.name); e.dataTransfer.effectAllowed = "move"; t.classList.add("dragging"); });
      t.addEventListener("dragend", () => t.classList.remove("dragging"));
      t.addEventListener("dragover", (e) => { e.preventDefault(); t.classList.add("dropto"); });
      t.addEventListener("dragleave", () => t.classList.remove("dropto"));
      t.addEventListener("drop", (e) => { e.preventDefault(); t.classList.remove("dropto"); const from = e.dataTransfer.getData("text/fsc-brush"); if (from) fscMoveFav(from, b.name); });
    }
    list.append(t);
  });
  if (!items.length) { const n = document.createElement("span"); n.className = "fsc-empty"; n.textContent = q ? "No brush matches." : p.cat === "Recent" ? "Brushes you use show up here." : "Right-click a brush to make it a favourite."; list.append(n); }
}
// favourites order (drag a tile onto another, or Move left / right in its menu)
function fscMoveFav(name, before) {
  const p = fscPrefs(), from = p.fav.indexOf(name);
  if (from < 0 || name === before) return;
  p.fav.splice(from, 1);
  const to = typeof before === "number" ? Math.max(0, Math.min(p.fav.length, before)) : Math.max(0, p.fav.indexOf(before));
  p.fav.splice(to < 0 ? p.fav.length : to, 0, name);
  fscSave(p); fscFill();
  return fscSay(name + " moved to place " + (p.fav.indexOf(name) + 1) + ".");
}
// a brush's own hotkey: a chord like "f5", "alt+2" - never one Forge's hotkey table already has (or Space / Esc), so a
// brush key can't steal a Maya key; keys saved before that rule are ignored when the table has them
function fscTaken(c) {
  if (!c || c === "escape" || c === "space" || c === " ") return true;
  if (/^ctrl\+(s|c|v|x|shift\+s)$/.test(c)) return true;                 // save / copy / paste stay the app's
  return typeof forgeKeyAction === "function" && !!forgeKeyAction(c);
}
function fscChord(e) {
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase();
  if (["shift", "control", "alt", "meta"].includes(k)) return "";
  return (e.ctrlKey || e.metaKey ? "ctrl+" : "") + (e.altKey ? "alt+" : "") + (e.shiftKey ? "shift+" : "") + (e.code && /^Key[A-Z]$/.test(e.code) ? e.code.slice(3).toLowerCase() : e.code && /^Digit\d$/.test(e.code) ? e.code.slice(5) : k);
}
const fscKeyLabel = (c) => c.split("+").map((x) => (x.length === 1 ? x.toUpperCase() : x === "ctrl" ? (/Mac/.test(navigator.platform) ? "⌘" : "Ctrl") : x[0].toUpperCase() + x.slice(1))).join("+");
function fscAssignKey(name) {
  fscSay("Press the key for " + name + " (Esc cancels, Backspace removes its key).");
  const tag = document.createElement("div"); tag.className = "fsc-keywait"; tag.textContent = "Press a key for " + name; document.body.append(tag);
  const done = () => { window.removeEventListener("keydown", on, true); tag.remove(); };
  const on = (e) => {
    e.preventDefault(); e.stopImmediatePropagation();
    if (e.key === "Escape") { done(); fscSay("No key set."); return; }
    const p = fscPrefs(); p.keys = p.keys || {};
    if (e.key === "Backspace" || e.key === "Delete") { for (const k of Object.keys(p.keys)) if (p.keys[k] === name) delete p.keys[k]; fscSave(p); done(); fscFill(); fscSay(name + " has no key now."); return; }
    const c = fscChord(e); if (!c) return;
    if (fscTaken(c)) { fscSay(fscKeyLabel(c) + " is already " + (typeof forgeKeyAction === "function" && forgeKeyAction(c) ? forgeKeyActionName(forgeKeyAction(c)) : "taken") + " - try another (an F-key, Alt+letter ...).", true); return; }
    for (const k of Object.keys(p.keys)) if (p.keys[k] === name) delete p.keys[k];
    const was = p.keys[c]; p.keys[c] = name; fscSave(p); done(); fscFill();
    fscSay(fscKeyLabel(c) + " now picks " + name + (was && was !== name ? " (it was " + was + ")" : "") + ".");
  };
  window.addEventListener("keydown", on, true);
}
function fscTileMenu(name, x, y) {
  document.getElementById("fsc-tmenu")?.remove();
  const p = fscPrefs(), fav = p.fav.includes(name), i = p.fav.indexOf(name);
  const m = document.createElement("div"); m.id = "fsc-tmenu"; m.className = "fsc-tmenu"; m.setAttribute("role", "menu");
  const item = (label, fn, off) => { const b = document.createElement("button"); b.type = "button"; b.textContent = label; b.disabled = !!off; b.addEventListener("click", (e) => { e.stopPropagation(); m.remove(); fn(); }); m.append(b); };
  const hk = Object.keys(p.keys || {}).find((k) => p.keys[k] === name);
  item(fav ? "Remove from favourites" : "Add to favourites", () => fscFav(name));
  item(hk ? "Hotkey: " + fscKeyLabel(hk) + " (change...)" : "Set a hotkey...", () => fscAssignKey(name));
  if (fav) { item("Move left", () => fscMoveFav(name, i - 1), i <= 0); item("Move right", () => fscMoveFav(name, i + 1), i >= p.fav.length - 1); }
  document.body.append(m);
  const r = m.getBoundingClientRect();
  m.style.left = Math.round(Math.min(x, innerWidth - r.width - 8)) + "px";
  m.style.top = Math.round(Math.max(8, y - r.height - 8)) + "px";
  const off = (e) => { if (!m.contains(e.target)) { m.remove(); document.removeEventListener("pointerdown", off, true); } };
  setTimeout(() => document.addEventListener("pointerdown", off, true), 0);
}
function fscFav(name) {
  const p = fscPrefs();
  p.fav = p.fav.includes(name) ? p.fav.filter((x) => x !== name) : p.fav.concat([name]);
  fscSave(p); fscFill();
  return fscSay(name + (p.fav.includes(name) ? " is a favourite (the wheel and Ctrl/Cmd+Shift+1-9)." : " is no longer a favourite."));
}

// the parts that follow state: the brush, the sliders, symmetry, dynamic detail, the level, the matcap
// where everything goes: worked out from the room that is really free, with GAP px between any two things - the header
// under the viewport's own toolbar and clear of the view cube, the sliders on the left between header and strip (their
// tracks shrink to fit), the strip from the sliders' right edge to the viewport's right edge, above any bottom bar
const FSC_GAP = 12;
function fscLayout() {
  const stage = document.getElementById("forge-stage"), head = document.getElementById("fsc-head"),
    side = document.getElementById("fsc-side"), strip = document.getElementById("fsc-strip");
  if (!stage || !head || !side || !strip || !head.offsetParent) return;
  const st = stage.getBoundingClientRect(), G = FSC_GAP;
  const shown = (e) => e && e.offsetParent && getComputedStyle(e).display !== "none" && e.getBoundingClientRect().height > 0;
  let top = st.top + 8, bottom = st.bottom - G, right = st.right - G;
  for (const sel of [".forge-viewbar", "#fmy-panelbar", ".fmy-panelbar", "#forge-exportbar"]) {
    const e = stage.querySelector(sel); if (!shown(e)) continue;
    const r = e.getBoundingClientRect();
    if (r.top < st.top + 120) top = Math.max(top, r.bottom); else if (r.top > st.top + st.height / 2) bottom = Math.min(bottom, r.top - G);
  }
  // the header: centred in the room left of the view cube
  const cube = document.getElementById("fmy-cube");
  let headRight = st.right - G;
  if (shown(cube)) { const c = cube.getBoundingClientRect(); if (c.top < st.top + st.height / 3) headRight = Math.min(headRight, c.left - G); }
  const headLeft = st.left + G;
  head.style.transform = "none";
  head.style.maxWidth = Math.max(160, headRight - headLeft) + "px";
  head.classList.toggle("fsc-narrow", headRight - headLeft < 640);
  const hw = head.getBoundingClientRect().width;
  const hx = Math.max(headLeft, Math.min(headRight - hw, (headLeft + headRight) / 2 - hw / 2));
  head.style.left = Math.round(hx - st.left) + "px";
  head.style.top = Math.round(top + G - st.top) + "px";
  const headBottom = head.getBoundingClientRect().bottom;
  // the strip: its height first (it never shrinks below its tiles)
  strip.style.transform = "none";
  const sh = strip.getBoundingClientRect().height;
  // the sliders: between the header and the strip, their tracks as tall as the room allows
  const sideTop = headBottom + G, sideRoomBottom = bottom - sh - G;
  // A short stage (900x600 leaves the stage 328x473): the sticky-tool grid gets a third column so the column is
  // shorter and stays inside the stage instead of running off the bottom by a few pixels.
  const tight = (sideRoomBottom - sideTop) < 230;
  if (side.classList.contains("fsc-tight") !== tight) side.classList.toggle("fsc-tight", tight);
  const tracks = side.querySelectorAll(".fsc-track");
  const sideBy = !!side.querySelector(".fsc-sliders");
  const fixed = side.getBoundingClientRect().height - (sideBy ? (tracks[0] ? tracks[0].getBoundingClientRect().height : 0) : [...tracks].reduce((a, t) => a + t.getBoundingClientRect().height, 0));
  const rows = sideBy ? 1 : Math.max(1, tracks.length);   // side by side: one row of tracks
  // The tracks are as tall as the room allows. On a short stage (900x600 leaves the stage 328x473 once the columns
  // are up) a 48 px floor made the whole column taller than the room and it ran off the bottom of the stage - so when
  // the room is tight the floor drops to 22 px, which still leaves a usable track and keeps every tool on screen.
  const sideAvail = Math.max(24, sideRoomBottom - sideTop - fixed);
  const per = sideAvail / rows;
  const each = Math.max(per < 48 ? 22 : 48, Math.min(200, per));
  for (const t of tracks) t.style.height = Math.round(each) + "px";
  side.style.transform = "none";
  const sideH = side.getBoundingClientRect().height;
  const sy = Math.max(sideTop, Math.min(sideRoomBottom - sideH, (sideTop + sideRoomBottom) / 2 - sideH / 2));
  side.style.top = Math.round(sy - st.top) + "px";
  side.style.left = G + "px";
  const sideRight = side.getBoundingClientRect().right;
  // if the sliders still reach down to the strip's row, the strip starts right of them
  const sideBottom = side.getBoundingClientRect().bottom;
  const stripLeft = sideBottom > bottom - sh - G / 2 ? sideRight + G : st.left + G;
  const room = right - stripLeft;
  const sw = Math.min(920, room);
  strip.style.width = Math.round(sw) + "px";
  strip.style.left = Math.round(stripLeft + (room - sw) / 2 - st.left) + "px";
  strip.style.bottom = Math.round(st.bottom - bottom) + "px";
}
function fscSync() {
  const v = fscView(); if (!v || !v.brush) return;
  fscLayout();
  const name = document.getElementById("fsc-brushname"); if (name) name.textContent = fscCurrent() || "Brush";
  for (const t of document.querySelectorAll("#fsc-list .fsc-tile")) t.classList.toggle("on", t.dataset.brush === fscCurrent());
  for (const s of document.querySelectorAll("#fsc-side .fsc-slider")) {
    const lo = +s.dataset.lo, hi = +s.dataset.hi, val = s.dataset.key === "size" ? v.brush.radius : v.brush.strength;
    const f = Math.max(0, Math.min(1, ((val || lo) - lo) / (hi - lo)));
    s.querySelector(".fsc-fill").style.height = (f * 100).toFixed(1) + "%";
    s.querySelector(".fsc-sval").textContent = s.dataset.key === "size" ? Math.round((val || 0) * 250) : Math.round((val || 0) * 100);
  }
  for (const b of document.querySelectorAll("#fsc-head .fsc-sym")) b.classList.toggle("on", !!((v.brush.symBits | 0) & +b.dataset.bit));
  for (const b of document.querySelectorAll("#fsc-side .fsc-sticky[data-sticky]")) b.classList.toggle("on", !!FSC_STICKY[b.dataset.sticky]);
  if (window.ForgeMask) ForgeMask.sync();
  const d = document.getElementById("forge-sculpt-dyn"), fd = document.querySelector("#fsc-head .fsc-dyn");
  if (fd) fd.classList.toggle("on", !!(d ? d.classList.contains("on") : window.ForgeSculpt && ForgeSculpt.dyn && ForgeSculpt.dyn.on));
  const lv = document.getElementById("forge-sculpt-level"), lt = document.getElementById("fsc-level");
  if (lt) { const m = /Level (\d+) \/ (\d+)/.exec((lv && lv.textContent) || ""); lt.textContent = m ? "L" + m[1] + "/" + m[2] : "L0"; }
  const cap = document.getElementById("fsc-matcap");
  if (cap) {
    let id = ""; try { id = localStorage.getItem("loki-forge-matcap") || ""; } catch (_) { /* private window */ }
    cap.style.backgroundImage = id && typeof FORGE_SCULPT_BASE !== "undefined" ? "url(" + FORGE_SCULPT_BASE + "matcaps/" + id + "_thumb.png)" : "";
  }
}
function fscLevel(dir) {
  const t = (document.getElementById("forge-sculpt-level") || {}).textContent || "";
  const m = /Level (\d+) \/ (\d+)/.exec(t);
  if (!window.ForgeSculpt) return "";
  if (dir < 0) { if (m && +m[1] > 0) ForgeSculpt.op("setLevel", +m[1] - 1); return ""; }
  if (m && +m[1] < +m[2]) ForgeSculpt.op("setLevel", +m[1] + 1); else ForgeSculpt.op("divide");
  return "";
}
function fscOp(id) { const v = fscView(); if (v && typeof forgeProRun === "function") forgeProRun(v, id); return ""; }

// ------------------------------------------------------------------------------------------ in and out of sculpt mode
// Workspace: Sculpting (forge_uv_editor.js setWorkspace calls this) - in and out of sculpt mode with the workspace
let fscWsGuard = false;
function forgeSculptWorkspace(on) {
  if (fscWsGuard) return;
  const v = fscView();
  if (!v) return;
  fscWsGuard = true;
  try {
    if (on) {
      if (typeof forgeProPanels === "function" && typeof forgeProPanel === "function") {
        const p = forgeProPanels();
        if (!window.__fscPanelsBefore) window.__fscPanelsBefore = { outliner: p.outliner, channel: p.channel };
        if (p.outliner) forgeProPanel("outliner", false);
        if (p.channel) forgeProPanel("channel", false);
      }
      if (v.mode !== "sculpt") { if (typeof forgeProSculpt === "function") forgeProSculpt(v); else if (typeof forgeMode === "function") forgeMode(); }
      if (typeof forgeMenuSet === "function" && forgeMenuSet() !== "sculpting") forgeMenuSet("sculpting");
    } else {
      if (v.mode === "sculpt" && typeof forgeMode === "function") forgeMode();
      const before = window.__fscPanelsBefore; window.__fscPanelsBefore = null;
      if (before && typeof forgeProPanel === "function") { forgeProPanel("outliner", !!before.outliner); forgeProPanel("channel", !!before.channel); }
      if (typeof forgeMenuSet === "function" && forgeMenuSet() === "sculpting") forgeMenuSet("modeling");
    }
  } finally { fscWsGuard = false; }
  fscShow();
}
window.forgeSculptWorkspace = forgeSculptWorkspace;
function fscWorkspace() { return typeof ForgeUVEditor !== "undefined" ? ForgeUVEditor.workspace() : ""; }
function fscSetWorkspace(ws) { if (typeof ForgeUVEditor !== "undefined" && ForgeUVEditor.workspace() !== ws) ForgeUVEditor.setWorkspace(ws); }
function fscExit() {
  const v = fscView();
  if (!v) return "";
  fscWheelClose();
  FSC_STICKY.invert = false; FSC_STICKY.smooth = false; FSC_STICKY.mask = false;
  if (fscWorkspace() === "sculpt") fscSetWorkspace("model");
  if (v.mode === "sculpt" && typeof forgeMode === "function") forgeMode();
  if (typeof forgeMenuSet === "function" && forgeMenuSet() === "sculpting") forgeMenuSet("modeling");
  if (typeof fmySync === "function") fmySync();
  fscShow();
  return fscSay("Left sculpt mode.");
}
function fscShow() {
  const v = fscView(), on = !!(v && v.mode === "sculpt");
  if (!fscWsGuard && v) {
    if (on && fscWorkspace() !== "sculpt") fscSetWorkspace("sculpt");
    else if (!on && fscWorkspace() === "sculpt") fscSetWorkspace("model");
  }
  const f = document.getElementById("forge");
  if (f) { f.classList.toggle("fsc-on", on); if (!on) f.classList.remove("fsc-more"); }
  if (on) { fscBuild(); fscFill(); fscSync(); }
  else fscWheelClose();
}
// the mode can change from anywhere (menu set, the command, a tool): follow it at once - the view's setMode is hooked
// (a layout saved straight after leaving sculpt mode used to land on the Sculpting workspace); the poll is the fallback
function fscHookMode(v) {
  if (!v || v._fscHooked || typeof v.setMode !== "function") return;
  const orig = v.setMode;
  v.setMode = function () { const r = orig.apply(this, arguments); fscShow(); return r; };
  v._fscHooked = true;
}
setInterval(() => {
  const v = fscView(), on = !!(v && v.mode === "sculpt"), f = document.getElementById("forge");
  fscHookMode(v);
  if (f && f.classList.contains("fsc-on") !== on) fscShow(); else if (on) fscSync();
}, 300);

// ------------------------------------------------------------------------------------------ the sculpt wheel (right button)
function fscWheelOpen(x, y) {
  fscWheelClose();
  const p = fscPrefs(), all = fscBrushes();
  const ring = p.fav.map((n) => all.find((b) => b.name === n)).filter(Boolean).slice(0, 10);
  const w = document.createElement("div"); w.id = "fsc-wheel"; w.className = "fsc-wheel"; w.setAttribute("role", "menu");
  w.style.left = Math.round(x) + "px"; w.style.top = Math.round(y) + "px";
  const R = 92, n = Math.max(1, ring.length);
  const hub = document.createElement("div"); hub.className = "fsc-hub"; hub.textContent = fscCurrent() || "Brush"; w.append(hub);
  ring.forEach((b, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    const t = document.createElement("button");
    t.type = "button"; t.className = "fsc-wtile" + (b.name === fscCurrent() ? " on" : ""); t.dataset.brush = b.name; t.dataset.angle = String(a);
    t.style.left = Math.round(Math.cos(a) * R) + "px"; t.style.top = Math.round(Math.sin(a) * R) + "px";
    t.innerHTML = fscBall(fscIconOf(b)) + '<span class="fsc-tname">' + b.name + "</span>";
    t.addEventListener("click", (e) => { e.stopPropagation(); fscWheelClose(); fscPick(b.name); });
    w.append(t);
  });
  const acts = document.createElement("div"); acts.className = "fsc-wacts";
  const act = (icon, label, fn) => {
    const b = document.createElement("button"); b.type = "button"; b.className = "fsc-wact"; b.dataset.act = label;
    b.innerHTML = fscSvg(FSC_UI_ICON[icon], 15) + "<span>" + label + "</span>";
    b.addEventListener("click", (e) => { e.stopPropagation(); fscWheelClose(); fn(); });
    acts.append(b);
  };
  act("undo", "Undo", () => { const v = fscView(); if (v && v.undo) v.undo(); });
  act("divide", "Divide", () => fscLevel(1));
  act("remesh", "Remesh", () => fscOp("sculptRemesh"));
  act("frame", "Frame", () => fscOp("frameAll"));
  act("mask", "Invert mask", () => fscSay(ForgeMask.op("maskInvert")));
  act("unmask", "Clear mask", () => fscSay(ForgeMask.op("maskClear")));
  act("eye", ForgeMask.hidden ? "Show all" : "Hide masked", () => { fscSay(ForgeMask.op("maskHideToggle")); fscSync(); });
  act("star", "All brushes", () => { const pp = fscPrefs(); pp.cat = "All"; fscSave(pp); fscChips(); fscFill(); const q = document.getElementById("fsc-q"); if (q) q.focus(); });
  act("exit", "Exit Sculpt", () => fscExit());
  acts.style.top = Math.round(R + 44) + "px";
  w.append(acts);
  document.body.append(w);
  // keep it on screen
  const r = w.getBoundingClientRect();
  const dx = Math.max(0, R + 70 - x) - Math.max(0, x + R + 70 - innerWidth), dy = Math.max(0, R + 50 - y) - Math.max(0, y + R + 130 - innerHeight);
  if (dx || dy) { w.style.left = Math.round(x + dx) + "px"; w.style.top = Math.round(y + dy) + "px"; }
  w._at = [x + dx, y + dy]; w._r = r;
  return w;
}
function fscWheelClose() { document.getElementById("fsc-wheel")?.remove(); }
// a release over the wheel: what is under the mouse, else the brush in that direction past the dead zone
function fscWheelPick(x, y) {
  const w = document.getElementById("fsc-wheel"); if (!w) return null;
  const hit = document.elementFromPoint(x, y);
  const el = hit && hit.closest && hit.closest("#fsc-wheel button");
  if (el) return el;
  const dx = x - w._at[0], dy = y - w._at[1];
  if (Math.hypot(dx, dy) < 30 || dy > 70) return null;
  const ang = Math.atan2(dy, dx);
  let best = null, bd = 9;
  for (const t of w.querySelectorAll(".fsc-wtile")) { const d = Math.abs(Math.atan2(Math.sin(ang - +t.dataset.angle), Math.cos(ang - +t.dataset.angle))); if (d < bd) { bd = d; best = t; } }
  return bd < 0.5 ? best : null;
}
(function fscWheelEvents() {
  let press = null;
  document.addEventListener("pointerdown", (e) => {
    const v = fscView();
    const w = document.getElementById("fsc-wheel");
    if (w && !w.contains(e.target)) fscWheelClose();
    if (!v || v.mode !== "sculpt" || e.button !== 2 || forgeCamMod(e) || !e.target || e.target.id !== "forge-view") return;
    e.preventDefault(); e.stopImmediatePropagation();
    fscWheelOpen(e.clientX, e.clientY);
    press = { x: e.clientX, y: e.clientY, t: performance.now() };
  }, true);
  document.addEventListener("pointermove", (e) => {
    const w = document.getElementById("fsc-wheel"); if (!w || !press) return;
    const el = fscWheelPick(e.clientX, e.clientY);
    for (const b of w.querySelectorAll("button")) b.classList.toggle("hot", b === el);
  }, true);
  document.addEventListener("pointerup", (e) => {
    if (!press || e.button !== 2) return;
    const moved = Math.hypot(e.clientX - press.x, e.clientY - press.y) > 12;
    press = null;
    if (!moved) return;                                   // no flick: the wheel stays open for clicking
    const el = fscWheelPick(e.clientX, e.clientY);
    if (el) el.click(); else fscWheelClose();
  }, true);
  document.addEventListener("contextmenu", (e) => { const v = fscView(); if (v && v.mode === "sculpt" && e.target && (e.target.id === "forge-view" || e.target.closest("#fsc-wheel"))) e.preventDefault(); }, true);
  // keys in sculpt mode: a brush's own hotkey, and Esc (closes the wheel, else leaves sculpt mode). Everything else -
  // levels, symmetry, lazy mouse, masking, the favourites - is in Forge's one hotkey table (forge_keys.js), so no key
  // means one thing here and another in Modeling (owner 2026-10-22: "make sure nothing is used twice")
  window.addEventListener("keydown", (e) => {
    const v = fscView();
    if (!v || v.mode !== "sculpt") return;
    if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    const p0 = fscPrefs(), chord = fscChord(e);
    if (chord && p0.keys && p0.keys[chord] && !fscTaken(chord)) { e.preventDefault(); e.stopImmediatePropagation(); fscPick(p0.keys[chord]); return; }
    if (e.key !== "Escape") return;
    if (document.getElementById("fsc-wheel")) { e.preventDefault(); e.stopImmediatePropagation(); fscWheelClose(); return; }
    if (document.querySelector(".fmy-drop, #forge-pro-hotbox:not([hidden]), #forge-pro-marking:not([hidden]), #forge-hotkeys:not([hidden])")) return;
    e.preventDefault(); e.stopImmediatePropagation(); fscExit();
  }, true);
})();

// the sculpt commands the hotkey table binds (forge_keys.js); outside sculpt mode they say where they work
function fscOnly(fn) { return (v) => (v && v.mode === "sculpt" ? fn(v) : "That works in sculpt mode (Sculpting workspace)."); }
function fscSymX(v) { const bits = (v.brush.symBits | 0) ^ 1; const say = typeof forgeProSym === "function" ? forgeProSym(v, bits) : ""; fscSync(); return say; }
function fscLazy() {
  if (!window.ForgeSculpt) return "";
  const o = ForgeSculpt.strokeOpts; o.lazyWas = o.lazy || o.lazyWas || 10; o.lazy = o.lazy ? 0 : o.lazyWas;
  return "Lazy mouse " + (o.lazy ? "on (" + o.lazy + " px)" : "off") + ".";
}
function fscFavKey(i) { const name = fscPrefs().fav[i]; if (!name) return "No favourite brush " + (i + 1) + " yet - right-click a brush > Add to favourites."; fscPick(name); return ""; }
if (typeof FORGE_PRO_CMDS !== "undefined") {
  const C = FORGE_PRO_CMDS;
  C.sculptLevelUp = ["Sculpt Level Up / Divide", fscOnly(() => fscLevel(1))];
  C.sculptLevelDown = ["Sculpt Level Down", fscOnly(() => fscLevel(-1))];
  C.sculptSymX = ["Sculpt Symmetry X", fscOnly(fscSymX)];
  C.sculptLazy = ["Lazy Mouse", fscOnly(fscLazy)];
  for (let i = 0; i < 9; i++) C["sculptFav" + (i + 1)] = ["Favourite Brush " + (i + 1), fscOnly(() => fscFavKey(i))];
  FORGE_PRO_CMDS.sculptExit = ["Exit Sculpt", () => fscExit()];
  FORGE_PRO_CMDS.sculptWheel = ["Sculpt Brush Wheel", (v) => { const m = (v && v.pro && v.pro.mouse) || [innerWidth / 2, innerHeight / 2]; fscWheelOpen(m[0], m[1]); return ""; }];
}
window.forgeSculptUI = { sticky: FSC_STICKY, show: fscShow, exit: fscExit, pick: fscPick, fav: fscFav, wheel: fscWheelOpen, close: fscWheelClose, brushes: fscBrushes, prefs: fscPrefs };
