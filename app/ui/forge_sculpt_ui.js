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
//     1-9 pick the first nine favourites.
//   * right button on the view: the sculpt wheel at the mouse - the favourite brushes around it, and Undo, Remesh,
//     Divide, Symmetry, Frame, All brushes and Exit Sculpt; press-drag-release picks like a marking menu, a quick
//     click keeps it open.
//   * leaving: Done, q (the Select tool, as in the pro tool), F8, Esc, the wheel's Exit Sculpt, or Menu Set: Modeling.
// Brushes are the sculpting engine's presets (vendor/sculpt/brushes.json via ForgeSculpt.library), or Forge's seven
// basic brushes when the engine is not loaded.
"use strict";

const FSC_STORE = "loki-forge-sculpt-ui";
const FSC_STICKY = { invert: false, smooth: false };
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
  search: '<circle cx="11" cy="11" r="5"/><path d="M15 15l4 4"/>', divide: '<path d="M12 4l8 15H4z"/><path d="M8 12h8M12 19l-4-7M12 19l4-7"/>',
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
  done.title = "Done - leave sculpt mode (q, F8 or Esc)";
  done.addEventListener("click", (e) => { e.stopPropagation(); fscExit(); });
  const chip = el("span", "fsc-chip-mode", "<i></i>Sculpt"); chip.title = "You are sculpting - Done, q, F8 or Esc leaves";
  const undo = btn("undo", "Undo", "Ctrl+Z", () => { const v = fscView(); if (v && v.undo) v.undo(); });
  const redo = btn("undo", "Redo", "Ctrl+Shift+Z", () => { const v = fscView(); if (v && v.redo) v.redo(); }, "fsc-redo");
  head.append(chip, name, sep(), sym, dyn, sep(), lvl, remesh, reduce, sep(), undo, redo, cap, more, done);

  // ---- the two sliders on the left
  const side = el("div", "fsc-side"); side.id = "fsc-side";
  side.append(fscSlider("size", "Size", "brush radius (or hold b and drag)", 0.02, 0.4), fscSlider("strength", "Strength", "how hard each dab pushes (or hold m and drag)", 0.05, 1));
  // sticky toggles (Nomad's left bar): tap = stays on, the same as holding Ctrl (invert) or Shift (smooth)
  const sticky = (key, label, what, icon) => {
    const b = btn(icon, label, what, () => { FSC_STICKY[key] = !FSC_STICKY[key]; }, "fsc-sticky");
    b.dataset.sticky = key; return b;
  };
  side.append(sticky("invert", "Invert", "dig in instead of building up - the same as holding Ctrl / Cmd", '<path d="M6 12h12"/>'),
    sticky("smooth", "Smooth", "every stroke smooths - the same as holding Shift", '<path d="M5 14c2.5-3 4.5-3 7 0s4.5 3 7 0"/>'));

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
    t.title = b.name + key + " - " + (b.category || "") + " · right-click: " + (p.fav.includes(b.name) ? "take off" : "add to") + " favourites";
    t.innerHTML = fscBall(fscIconOf(b)) + '<span class="fsc-tname">' + b.name + "</span>" + (key ? '<span class="fsc-key">' + (i + 1) + "</span>" : "");
    t.addEventListener("click", (e) => { e.stopPropagation(); if (list.dataset.justDragged) return; fscPick(b.name); });
    t.addEventListener("contextmenu", (e) => { e.preventDefault(); e.stopPropagation(); fscFav(b.name); });
    list.append(t);
  });
  if (!items.length) { const n = document.createElement("span"); n.className = "fsc-empty"; n.textContent = q ? "No brush matches." : p.cat === "Recent" ? "Brushes you use show up here." : "Right-click a brush to make it a favourite."; list.append(n); }
}
function fscFav(name) {
  const p = fscPrefs();
  p.fav = p.fav.includes(name) ? p.fav.filter((x) => x !== name) : p.fav.concat([name]);
  fscSave(p); fscFill();
  return fscSay(name + (p.fav.includes(name) ? " is a favourite (the wheel and 1-9)." : " is no longer a favourite."));
}

// the parts that follow state: the brush, the sliders, symmetry, dynamic detail, the level, the matcap
function fscSync() {
  const v = fscView(); if (!v || !v.brush) return;
  // the header sits under whatever the viewport shows at its top (its toolbar wraps onto more rows on a small window)
  const head = document.getElementById("fsc-head"), stage = document.getElementById("forge-stage");
  if (head && stage) {
    const st = stage.getBoundingClientRect();
    let low = st.top + 46;
    for (const sel of [".forge-viewbar", "#fmy-panelbar", ".fmy-panelbar", "#forge-exportbar"]) {
      const e = stage.querySelector(sel);
      if (e && e.offsetParent && getComputedStyle(e).display !== "none") { const r = e.getBoundingClientRect(); if (r.height && r.top < st.top + 120) low = Math.max(low, r.bottom); }
    }
    head.style.top = Math.round(low - st.top + 8) + "px";
    head.classList.toggle("fsc-narrow", st.width < 760);
    // ... and the brush strip above whatever sits along the bottom (the export bar)
    const strip = document.getElementById("fsc-strip");
    if (strip) {
      let high = st.bottom - 12;
      for (const sel of ["#forge-exportbar", ".forge-viewbar"]) {
        const e = stage.querySelector(sel);
        if (e && e.offsetParent && getComputedStyle(e).display !== "none") { const r = e.getBoundingClientRect(); if (r.height && r.top > st.top + st.height / 2) high = Math.min(high, r.top - 8); }
      }
      strip.style.bottom = Math.round(st.bottom - high) + "px";
    }
  }
  const name = document.getElementById("fsc-brushname"); if (name) name.textContent = fscCurrent() || "Brush";
  for (const t of document.querySelectorAll("#fsc-list .fsc-tile")) t.classList.toggle("on", t.dataset.brush === fscCurrent());
  for (const s of document.querySelectorAll("#fsc-side .fsc-slider")) {
    const lo = +s.dataset.lo, hi = +s.dataset.hi, val = s.dataset.key === "size" ? v.brush.radius : v.brush.strength;
    const f = Math.max(0, Math.min(1, ((val || lo) - lo) / (hi - lo)));
    s.querySelector(".fsc-fill").style.height = (f * 100).toFixed(1) + "%";
    s.querySelector(".fsc-sval").textContent = s.dataset.key === "size" ? Math.round((val || 0) * 250) : Math.round((val || 0) * 100);
  }
  for (const b of document.querySelectorAll("#fsc-head .fsc-sym")) b.classList.toggle("on", !!((v.brush.symBits | 0) & +b.dataset.bit));
  for (const b of document.querySelectorAll("#fsc-side .fsc-sticky")) b.classList.toggle("on", !!FSC_STICKY[b.dataset.sticky]);
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
function fscExit() {
  const v = fscView();
  if (!v) return "";
  fscWheelClose();
  FSC_STICKY.invert = false; FSC_STICKY.smooth = false;
  if (v.mode === "sculpt" && typeof forgeMode === "function") forgeMode();
  const set = document.getElementById("fmy-menuset"); if (set) set.value = "Modeling";
  if (typeof fmySync === "function") fmySync();
  fscShow();
  return fscSay("Left sculpt mode.");
}
function fscShow() {
  const v = fscView(), on = !!(v && v.mode === "sculpt");
  const f = document.getElementById("forge");
  if (f) { f.classList.toggle("fsc-on", on); if (!on) f.classList.remove("fsc-more"); }
  if (on) { fscBuild(); fscFill(); fscSync(); }
  else fscWheelClose();
}
// the mode can change from anywhere (menu set, the command, a tool): follow it
setInterval(() => { const v = fscView(), on = !!(v && v.mode === "sculpt"), f = document.getElementById("forge"); if (f && f.classList.contains("fsc-on") !== on) fscShow(); else if (on) fscSync(); }, 300);

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
    if (!v || v.mode !== "sculpt" || e.button !== 2 || e.altKey || !e.target || e.target.id !== "forge-view") return;
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
    const moved = Math.hypot(e.clientX - press.x, e.clientY - press.y) > 12, quick = performance.now() - press.t < 260;
    press = null;
    if (!moved && quick) return;                          // a click: the wheel stays open for clicking
    const el = fscWheelPick(e.clientX, e.clientY);
    if (el) el.click(); else fscWheelClose();
  }, true);
  document.addEventListener("contextmenu", (e) => { const v = fscView(); if (v && v.mode === "sculpt" && e.target && (e.target.id === "forge-view" || e.target.closest("#fsc-wheel"))) e.preventDefault(); }, true);
  // keys in sculpt mode: q / F8 / Esc leave, 1-9 the favourites
  window.addEventListener("keydown", (e) => {
    const v = fscView();
    if (!v || v.mode !== "sculpt" || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    if (e.key === "Escape" && document.getElementById("fsc-wheel")) { e.preventDefault(); e.stopImmediatePropagation(); fscWheelClose(); return; }
    if (e.key === "Escape" && document.querySelector(".fmy-drop, #forge-pro-hotbox:not([hidden]), #forge-pro-marking:not([hidden])")) return;
    if ((e.key === "q" || e.key === "Q") && !e.shiftKey || e.key === "F8" || e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); fscExit(); return; }
    const k = e.key.toLowerCase();
    if (k === "d") { e.preventDefault(); e.stopImmediatePropagation(); fscLevel(e.shiftKey ? -1 : 1); return; }   // ZBrush: D up / Shift+D down
    if (k === "x" && !e.repeat) {                                         // X: symmetry across X on / off
      e.preventDefault(); e.stopImmediatePropagation();
      const bits = (v.brush.symBits | 0) ^ 1;
      if (typeof forgeProSym === "function") fscSay(forgeProSym(v, bits)); fscSync(); return;
    }
    if (k === "l" && window.ForgeSculpt) {                                 // L: lazy mouse on / off
      e.preventDefault(); e.stopImmediatePropagation();
      const o = ForgeSculpt.strokeOpts; o.lazyWas = o.lazy || o.lazyWas || 10; o.lazy = o.lazy ? 0 : o.lazyWas;
      fscSay("Lazy mouse " + (o.lazy ? "on (" + o.lazy + " px)" : "off") + "."); return;
    }
    if (/^[1-9]$/.test(e.key) && !e.shiftKey) {
      const p = fscPrefs(), name = p.fav[+e.key - 1];
      if (name) { e.preventDefault(); e.stopImmediatePropagation(); fscPick(name); }
    }
  }, true);
})();

if (typeof FORGE_PRO_CMDS !== "undefined") {
  FORGE_PRO_CMDS.sculptExit = ["Exit Sculpt", () => fscExit()];
  FORGE_PRO_CMDS.sculptWheel = ["Sculpt Brush Wheel", (v) => { const m = (v && v.pro && v.pro.mouse) || [innerWidth / 2, innerHeight / 2]; fscWheelOpen(m[0], m[1]); return ""; }];
}
window.forgeSculptUI = { sticky: FSC_STICKY, show: fscShow, exit: fscExit, pick: fscPick, fav: fscFav, wheel: fscWheelOpen, close: fscWheelClose, brushes: fscBrushes, prefs: fscPrefs };
