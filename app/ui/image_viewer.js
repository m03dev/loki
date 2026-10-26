// LOKI's picture viewer (owner 2026-10-26: "i want to be able to click next on the images so i can see through them,
// also can i crop an area in the images to focus on it and we can edit the area thats croped or focused not deleting
// or touching the rest of it ... there's probably a repo for that").
//   ‹ ›, ← →, swipe        the picture before / after (Home: everything you made; the chat: every picture in it)
//   Select area (S)       draw a box on the picture - Cropper.js (MIT, app/ui/vendor/cropper/)
//   Focus (F)             look at just that area, big; F again / Esc goes back
//   Save crop             the area as its own picture, beside the original
//   Edit area (E)         say what the area should become; LOKI redraws ONLY that box (engine/region_edit.py) and
//                         saves a new picture beside the original - the original and everything outside the box stay
//   Before / after (B)    hold to see the original again after an edit
// Plain DOM, CSP script-src 'self'; api() from app.js. One global: window.LokiViewer.open(items, index).
"use strict";

const LokiViewer = (() => {
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.reject(new Error("not ready")));
  const ICON = {
    prev: '<path d="M15 5l-7 7 7 7"/>', next: '<path d="M9 5l7 7-7 7"/>',
    select: '<path d="M6 2v16h16"/><path d="M2 6h16v16"/>', focus: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5M11 8v6M8 11h6"/>',
    crop: '<path d="M6 2v16h16"/><path d="M2 6h16v16"/><path d="M14 10l4-4"/>', edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/>',
    compare: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>', open: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v6H4V6h6"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
  };
  const svg = (p) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + p + "</svg>";

  // ---- pure helpers (tests/js/test_image_viewer.js)
  /** The next index, stopping at the ends (no wrap: the end is the end). */
  function step(i, d, n) { return n ? Math.max(0, Math.min(n - 1, i + d)) : 0; }
  /** Cropper's natural-pixel box -> [x, y, w, h] as shares (0-1) of the picture, clamped. */
  function shareBox(d, w, h) {
    if (!d || !w || !h) return null;
    const x = Math.max(0, d.x) / w, y = Math.max(0, d.y) / h;
    const bw = Math.min(d.width, w - Math.max(0, d.x)) / w, bh = Math.min(d.height, h - Math.max(0, d.y)) / h;
    const r = (v) => Math.round(v * 10000) / 10000;
    return bw > 0 && bh > 0 ? [r(x), r(y), r(bw), r(bh)] : null;
  }
  /** Pictures only, each once, in order. */
  function clean(items) {
    const seen = new Set(), out = [];
    for (const it of items || []) {
      if (!it || !it.src || seen.has(it.src)) continue;
      seen.add(it.src); out.push({ src: it.src, name: it.name || "", path: it.path || "" });
    }
    return out;
  }

  let V = null;   // the open viewer's state

  function btn(icon, name, what, fn, key) {
    const b = mk("button", "lv-btn"); b.type = "button"; b.innerHTML = svg(ICON[icon]);
    b.setAttribute("aria-label", name); b.title = name + (key ? " (" + key + ")" : "") + " - " + what;
    b.dataset.tipName = name; b.dataset.tipWhat = what;
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(b); });
    return b;
  }

  function open(items, index) {
    const list = clean(items);
    if (!list.length) return;
    close();
    const wrap = mk("div", "lv"); wrap.setAttribute("role", "dialog"); wrap.setAttribute("aria-modal", "true");
    const stage = mk("div", "lv-stage");
    const img = mk("img", "lv-img"); img.alt = "";
    const prev = btn("prev", "Before", "The picture before this one.", () => go(-1), "←");
    const next = btn("next", "Next", "The next picture.", () => go(1), "→");
    prev.classList.add("lv-nav", "lv-prev"); next.classList.add("lv-nav", "lv-next");
    const frame = mk("div", "lv-frame"); frame.append(img);
    stage.append(frame, prev, next);
    const bar = mk("div", "lv-bar");
    const title = mk("span", "lv-name"), count = mk("span", "lv-count");
    const tools = mk("span", "lv-tools");
    const bSelect = btn("select", "Select area", "Draw a box on the picture to focus on it, crop it or edit only it.", toggleSelect, "S");
    const bFocus = btn("focus", "Focus", "Show just the selected area, big.", toggleFocus, "F");
    const bCrop = btn("crop", "Save crop", "Save the selected area as its own picture beside the original.", saveCrop);
    const bEdit = btn("edit", "Edit area", "Say what the selected area should become - only that box is redrawn, the rest stays exactly as it is.", showEdit, "E");
    const bCompare = btn("compare", "Before / after", "Hold to see the picture before the edit.", () => {}, "B");
    const bOpen = btn("open", "Open", "Open it in this computer's own viewer.", () => { const it = V.list[V.i]; if (it.path) call("/chat/media/open", { path: it.path }); });
    const bClose = btn("close", "Close", "Close the viewer.", close, "Esc");
    tools.append(bSelect, bFocus, bCrop, bEdit, bCompare, bOpen, bClose);
    bar.append(title, count, tools);
    const editRow = mk("form", "lv-edit"); editRow.hidden = true;
    const prompt = mk("input", "lv-prompt"); prompt.type = "text"; prompt.placeholder = "What should the selected area become?  e.g. a golden helmet";
    const strength = mk("input", "lv-strength"); strength.type = "range"; strength.min = "0.3"; strength.max = "0.95"; strength.step = "0.05"; strength.value = "0.75";
    strength.title = "How much to change it - left keeps more of what is there, right redraws it more freely";
    strength.dataset.tipName = "Change amount"; strength.dataset.tipWhat = strength.title;
    const apply = mk("button", "send small", "Edit"); apply.type = "submit";
    const cancel = mk("button", "quiet small", "Cancel"); cancel.type = "button";
    editRow.append(prompt, strength, apply, cancel);
    const say = mk("div", "lv-say"); say.setAttribute("aria-live", "polite");
    wrap.append(stage, editRow, bar, say);
    document.body.append(wrap);

    V = { wrap, stage, img, list, i: Math.max(0, Math.min(list.length - 1, index | 0)), title, count, prev, next, say,
          editRow, prompt, strength, bSelect, bFocus, bCrop, bEdit, bCompare, cropper: null, focus: false, before: "",
          touchX: null, busy: false };
    editRow.addEventListener("submit", (e) => { e.preventDefault(); runEdit(); });
    cancel.addEventListener("click", () => { editRow.hidden = true; });
    wrap.addEventListener("click", (e) => { if (e.target === wrap || e.target === stage || e.target === frame) { if (!V.cropper) close(); } });
    const hold = (on) => { if (!V || !V.before) return; V.img.src = on ? V.before : V.list[V.i].src; V.wrap.classList.toggle("lv-showing-before", on); };
    bCompare.addEventListener("pointerdown", () => hold(true));
    for (const ev of ["pointerup", "pointerleave"]) bCompare.addEventListener(ev, () => hold(false));
    stage.addEventListener("touchstart", (e) => { V.touchX = e.touches[0].clientX; }, { passive: true });
    stage.addEventListener("touchend", (e) => {
      if (V.touchX == null || V.cropper) return;
      const dx = e.changedTouches[0].clientX - V.touchX; V.touchX = null;
      if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1);
    }, { passive: true });
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("keyup", onKeyUp, true);
    show();
    bClose.focus();
  }

  function show() {
    if (!V) return;
    stopSelect();
    const it = V.list[V.i];
    V.img.src = it.src; V.img.alt = it.name;
    V.title.textContent = it.name || "";
    V.count.textContent = (V.i + 1) + " / " + V.list.length;
    V.prev.disabled = V.i <= 0; V.next.disabled = V.i >= V.list.length - 1;
    const editable = !!it.path;
    for (const b of [V.bSelect, V.bFocus, V.bCrop, V.bEdit]) b.disabled = false;
    V.bCrop.disabled = V.bEdit.disabled = !editable;
    if (!editable) { V.bCrop.title = V.bEdit.title = "Only pictures LOKI saved in its folders can be cropped or edited."; }
    V.bCompare.hidden = !V.before || V.list[V.i].before !== V.before;
    V.editRow.hidden = true;
    for (const d of [-1, 1]) { const n = V.list[V.i + d]; if (n) { const pre = new Image(); pre.src = n.src; } }   // next one is instant
  }

  function go(d) {
    if (!V || V.busy) return;
    const j = step(V.i, d, V.list.length);
    if (j !== V.i) { V.i = j; V.before = V.list[j].before || ""; show(); }
  }

  // ---- area selection (Cropper.js)
  function startSelect() {
    if (!V || V.cropper) return;
    if (typeof Cropper !== "function") { tell("The area tool did not load (vendor/cropper).", true); return; }
    V.wrap.classList.add("lv-selecting");
    V.cropper = new Cropper(V.img, { viewMode: 1, dragMode: "crop", autoCropArea: 0.4, background: false, zoomable: false,
                                     rotatable: false, scalable: false, movable: false, guides: true, center: true, toggleDragModeOnDblclick: false });
    V.bSelect.setAttribute("aria-pressed", "true");
    tell("Drag a box over the part you want. Then Focus, Save crop or Edit area.");
  }
  function stopSelect() {
    if (!V) return;
    if (V.cropper) { V.cropper.destroy(); V.cropper = null; }
    if (V.focus) unfocus();
    V.wrap.classList.remove("lv-selecting");
    V.bSelect.removeAttribute("aria-pressed");
  }
  function toggleSelect() { if (V.cropper) { stopSelect(); tell(""); } else startSelect(); }
  function box() {
    if (!V || !V.cropper) return null;
    return shareBox(V.cropper.getData(true), V.img.naturalWidth, V.img.naturalHeight);
  }
  function needBox() {
    const b = box();
    if (!b) { if (!V.cropper) startSelect(); tell("Select the area first: drag a box on the picture.", true); }
    return b;
  }

  // ---- focus: just the area, big (nothing is saved)
  function toggleFocus() { if (V.focus) unfocus(); else focusOn(); }
  function focusOn() {
    const b = needBox(); if (!b) return;
    const canvas = V.cropper.getCroppedCanvas({ maxWidth: 4096, maxHeight: 4096, imageSmoothingQuality: "high" });
    if (!canvas) return;
    const view = mk("div", "lv-focus"); const pic = mk("img"); pic.src = canvas.toDataURL("image/png"); pic.alt = "the selected area";
    view.append(pic); view.addEventListener("click", unfocus);
    V.stage.append(view); V.focus = view; V.bFocus.setAttribute("aria-pressed", "true");
    tell("Focused on the selected area. F or a click goes back.");
  }
  function unfocus() { if (V.focus) { V.focus.remove(); V.focus = false; V.bFocus.removeAttribute("aria-pressed"); tell(""); } }

  // ---- save crop / edit area (engine/region_edit.py)
  async function saveCrop() {
    const b = needBox(); if (!b) return;
    const it = V.list[V.i];
    tell("Saving the crop...");
    const r = await call("/image/crop", { path: it.path, box: b }).catch((e) => ({ ok: false, error: e.message }));
    if (!r || !r.ok) { tell("Not saved: " + ((r && r.error) || "no answer"), true); return; }
    insertMade(r, null);
    tell("Saved " + r.file + " beside the original.");
  }
  function showEdit() {
    if (!needBox()) return;
    V.editRow.hidden = false; V.prompt.focus();
  }
  async function runEdit() {
    const b = box(); const text = V.prompt.value.trim();
    if (!b) { needBox(); return; }
    if (!text) { tell("Say what the selected area should become.", true); V.prompt.focus(); return; }
    const it = V.list[V.i];
    V.busy = true; V.wrap.classList.add("lv-busy");
    tell("Editing only the selected area... (the rest of the picture is not touched)");
    const r = await call("/image/edit-area", { path: it.path, box: b, prompt: text, strength: Number(V.strength.value) }).catch((e) => ({ ok: false, error: e.message }));
    if (!r || !r.ok) { done(); tell("Not edited: " + ((r && r.error) || "no answer"), true); return; }
    const t0 = Date.now();
    for (;;) {
      await new Promise((ok) => setTimeout(ok, 1500));
      if (!V) return;
      const s = await call("/image/edit-area?job=" + encodeURIComponent(r.job)).catch(() => null);
      if (s && s.status === "done") { done(); insertMade(s, it.src); tell("Edited: " + s.file + " (saved as a new picture; the original is kept). Hold B to compare."); return; }
      if (s && s.status === "failed") { done(); tell("Not edited: " + (s.error || "the model failed"), true); return; }
      tell("Editing only the selected area... " + Math.round((Date.now() - t0) / 1000) + " s");
    }
    function done() { if (V) { V.busy = false; V.wrap.classList.remove("lv-busy"); } }
  }
  /** A picture the engine just made: right after the current one, shown. */
  function insertMade(r, beforeSrc) {
    const folder = String(V.list[V.i].src).replace(/[^/]*$/, "");
    const src = /^\/creations\//.test(folder) ? folder + encodeURIComponent(r.file) : null;
    const add = (url) => {
      const item = { src: url, name: r.file, path: r.path, before: beforeSrc || "" };
      V.list.splice(V.i + 1, 0, item); V.i += 1; V.before = item.before; show();
      if (window.LokiHome && typeof window.LokiHome.refresh === "function") window.LokiHome.refresh();
    };
    if (src) add(src + "?t=" + Date.now());
    else call("/chat/media?path=" + encodeURIComponent(r.path)).then((m) => { if (m && m.ok && V) add(m.data_url); }).catch(() => {});
  }

  function tell(text, bad) { if (!V) return; V.say.textContent = text || ""; V.say.classList.toggle("bad", !!bad); }

  function onKey(e) {
    if (!V) return;
    const typing = e.target && /^(INPUT|TEXTAREA)$/.test(e.target.tagName);
    if (e.key === "Escape") {
      e.preventDefault(); e.stopPropagation();
      if (!V.editRow.hidden) V.editRow.hidden = true; else if (V.focus) unfocus(); else if (V.cropper) { stopSelect(); tell(""); } else close();
      return;
    }
    if (typing) return;
    const k = e.key.toLowerCase();
    const handled = { arrowleft: () => go(-1), arrowright: () => go(1), s: toggleSelect, f: toggleFocus, e: showEdit,
                      b: () => { if (V.before && !V.wrap.classList.contains("lv-showing-before")) { V.img.src = V.before; V.wrap.classList.add("lv-showing-before"); } } }[k];
    if (handled && !(V.cropper && k.startsWith("arrow"))) { e.preventDefault(); e.stopPropagation(); handled(); }
    else if (V) e.stopPropagation();   // the viewer is modal: keys don't reach Forge or the chat
  }
  function onKeyUp(e) {
    if (V && e.key.toLowerCase() === "b" && V.wrap.classList.contains("lv-showing-before")) { V.img.src = V.list[V.i].src; V.wrap.classList.remove("lv-showing-before"); }
  }

  function close() {
    if (!V) return;
    stopSelect();
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("keyup", onKeyUp, true);
    V.wrap.remove(); V = null;
  }

  const api_ = { open, close, step, shareBox, clean, isOpen: () => !!V };
  if (typeof window !== "undefined") window.LokiViewer = api_;
  return api_;
})();
if (typeof module !== "undefined") module.exports = LokiViewer;
