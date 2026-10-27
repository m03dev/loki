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
//   Thumbs up / down      tell LOKI you like it or not; a thumbs down asks why (chips + a note) - engine/image_feedback.py:
//                         the reasons shape the next prompts, and a pipeline picture's stage is redone with them
//   Delete (Del twice)    "I really don't like it": a thumbs down + the picture moves to trash/ (gone from Home and the
//                         library, recoverable from that folder). Click once, then again within 3 s - no pop-ups
//   Settings (G)          every setting the picture can be made with (engine/image_settings.py draws the panel: size in
//                         pixels or aspect + megapixels, steps, guidance, sampler, seed, count, change amount, start from
//                         this picture, style, avoid, upscale, pixel-art size, palette, model) - Remake makes a new one
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
    up: '<path d="M7 11v9H4v-9z"/><path d="M7 11l4-8c1.5 0 2.5 1 2.5 2.5V9h5a2 2 0 012 2.3l-1.2 7A2 2 0 0117.3 20H7"/>',
    down: '<path d="M17 13V4h3v9z"/><path d="M17 13l-4 8c-1.5 0-2.5-1-2.5-2.5V15h-5a2 2 0 01-2-2.3l1.2-7A2 2 0 016.7 4H17"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
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

  /** Is a setting live for this model? (engine/image_settings.py "honoured"): {on, why}. */
  function fieldState(setting, backend) {
    const b = backend || "auto";
    const on = !setting.honoured || setting.honoured.includes(b);
    return { on, why: on ? "" : "The " + b + " model ignores " + setting.label + "." };
  }
  /** The panel's values -> the settings sent to /image/remake: empty / default numbers left out, exact pixels only
   *  when "exact size" is on (otherwise aspect + megapixels). */
  function collect(values, schema, exact) {
    const out = {};
    for (const s of schema || []) {
      if (!(s.key in values)) continue;
      let v = values[s.key];
      if ((s.key === "width" || s.key === "height") && !exact) continue;
      if ((s.key === "aspect" || s.key === "megapixels") && exact) continue;
      if (s.type === "int" || s.type === "float") { if (v === "" || v == null) continue; v = Number(v); if (!isFinite(v)) continue; }
      if (s.type === "bool") v = !!v;
      if (s.type === "text" || s.type === "enum") { if (v === "" || v == null) continue; }
      out[s.key] = v;
    }
    return out;
  }
  /** Rating state for the two thumbs: [upPressed, downPressed]. */
  function thumbs(rating) { return [rating > 0, rating < 0]; }

  let V = null;   // the open viewer's state

  function btn(icon, name, what, fn, key) {
    const b = mk("button", "lv-btn"); b.type = "button"; b.innerHTML = svg(ICON[icon]);
    b.setAttribute("aria-label", name); b.title = name + (key ? " (" + key + ")" : "") + " - " + what;
    b.dataset.tipName = name; b.dataset.tipWhat = what;
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(b); });
    return b;
  }

  function open(items, index, opts) {
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
    const bUp = btn("up", "Thumbs up", "I like this one - LOKI makes more like it (and stars it).", () => rate(1));
    const bDown = btn("down", "Thumbs down", "I don't like this one - say why, LOKI avoids it next time (a pipeline picture is redone).", () => rate(-1));
    const bSet = btn("settings", "Settings", "Every setting this picture can be made with - change them and Remake.", toggleSettings, "G");
    const bDel = btn("trash", "Delete", "I really don't like it - remove it (click twice). It goes to the trash folder and LOKI learns from it.", askDelete, "Del");
    bUp.classList.add("lv-up"); bDown.classList.add("lv-down"); bDel.classList.add("lv-del");
    tools.append(bUp, bDown, bDel, bSet, bSelect, bFocus, bCrop, bEdit, bCompare, bOpen, bClose);
    bar.append(title, count, tools);
    const editRow = mk("form", "lv-edit"); editRow.hidden = true;
    const prompt = mk("input", "lv-prompt"); prompt.type = "text"; prompt.placeholder = "What should the selected area become?  e.g. a golden helmet";
    const strength = mk("input", "lv-strength"); strength.type = "range"; strength.min = "0.3"; strength.max = "0.95"; strength.step = "0.05"; strength.value = "0.75";
    strength.title = "How much to change it - left keeps more of what is there, right redraws it more freely";
    strength.dataset.tipName = "Change amount"; strength.dataset.tipWhat = strength.title;
    const apply = mk("button", "send small", "Edit"); apply.type = "submit";
    const cancel = mk("button", "quiet small", "Cancel"); cancel.type = "button";
    editRow.append(prompt, strength, apply, cancel);
    const why = mk("form", "lv-why"); why.hidden = true;            // the thumbs-down reasons
    const chips = mk("span", "lv-chips"), note = mk("input", "lv-prompt"); note.type = "text";
    note.placeholder = "Anything else? e.g. the side view is a different creature";
    const sendWhy = mk("button", "send small", "Send"); sendWhy.type = "submit";
    const skipWhy = mk("button", "quiet small", "Skip"); skipWhy.type = "button";
    why.append(chips, note, sendWhy, skipWhy);
    const panel = mk("aside", "lv-settings"); panel.hidden = true; panel.setAttribute("aria-label", "Picture settings");
    const say = mk("div", "lv-say"); say.setAttribute("aria-live", "polite");
    wrap.append(stage, editRow, why, bar, say, panel);
    document.body.append(wrap);

    V = { wrap, stage, img, list, i: Math.max(0, Math.min(list.length - 1, index | 0)), title, count, prev, next, say,
          editRow, prompt, strength, bSelect, bFocus, bCrop, bEdit, bCompare, cropper: null, focus: false, before: "",
          touchX: null, busy: false, bUp, bDown, bSet, bDel, armed: 0, why, chips, note, panel, info: null, schema: null, rating: 0 };
    editRow.addEventListener("submit", (e) => { e.preventDefault(); runEdit(); });
    why.addEventListener("submit", (e) => { e.preventDefault(); sendRating(-1); });
    skipWhy.addEventListener("click", () => sendRating(-1));
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
    if (opts && opts.rate === -1 && V.list[V.i].path) rate(-1);       // Home's thumbs down: straight to "why?"
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
    V.editRow.hidden = true; V.why.hidden = true;
    for (const b of [V.bUp, V.bDown, V.bSet, V.bDel]) b.disabled = !editable;
    disarm();
    V.rating = 0; paintThumbs(); V.info = null;
    if (editable) loadInfo(it);
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

  // ---- thumbs up / down (engine/image_feedback.py through /image/rate)
  const REASONS = { match: "Doesn't match the design", perspective: "Wrong view / perspective", text: "Text or letters",
    anatomy: "Bad anatomy / limbs", detail: "Blurry / low detail", style: "Wrong style", colour: "Wrong colours",
    background: "Background not plain", cropped: "Cut off", pose: "Wrong pose", boring: "Boring" };
  function paintThumbs() {
    if (!V) return;
    const [up, down] = thumbs(V.rating);
    V.bUp.setAttribute("aria-pressed", String(up)); V.bDown.setAttribute("aria-pressed", String(down));
  }
  async function loadInfo(it) {
    const r = await call("/image/info?path=" + encodeURIComponent(it.path)).catch(() => null);
    if (!V || V.list[V.i] !== it || !r || !r.ok) return;
    V.info = r; V.rating = r.rating || 0; paintThumbs();
    if (!V.panel.hidden) fillSettings();
  }
  function rate(n) {
    if (!V || !V.list[V.i].path) return;
    if (V.rating === n) { sendRating(0); return; }          // pressing it again clears it
    if (n > 0) { sendRating(1); return; }
    V.chips.replaceChildren();
    for (const [k, label] of Object.entries(REASONS)) {
      const c = mk("button", "lv-chip", label); c.type = "button"; c.dataset.reason = k;
      c.addEventListener("click", () => c.setAttribute("aria-pressed", String(c.getAttribute("aria-pressed") !== "true")));
      V.chips.append(c);
    }
    V.note.value = ""; V.why.hidden = false;
    tell("What is wrong with it? Pick any that fit - LOKI uses them for the next pictures.");
  }
  async function sendRating(n) {
    const it = V.list[V.i];
    const reasons = n < 0 ? [...V.chips.querySelectorAll('[aria-pressed="true"]')].map((c) => c.dataset.reason) : [];
    V.why.hidden = true;
    const r = await call("/image/rate", { path: it.path, rating: n, reasons, note: n < 0 ? V.note.value.trim() : "" })
      .catch((e) => ({ ok: false, error: e.message }));
    if (!r || !r.ok) { tell("Not saved: " + ((r && r.error) || "no answer"), true); return; }
    V.rating = r.rating; paintThumbs();
    tell(n > 0 ? "Liked - LOKI makes more like this." : n < 0 ? ("Noted" + (reasons.length ? ": " + reasons.map((k) => REASONS[k]).join(", ") : "") +
      (r.retake ? " - its " + r.retake.stage + " stage is being redone." : ".")) : "Cleared.");
  }

  // ---- delete: two clicks (no pop-up dialogs - they block the app), then gone from the list
  function disarm() { if (!V) return; clearTimeout(V.armed); V.armed = 0; V.bDel.classList.remove("lv-armed"); }
  function askDelete() {
    if (!V || !V.list[V.i].path) return;
    if (!V.armed) {
      V.bDel.classList.add("lv-armed");
      V.armed = setTimeout(disarm, 3000);
      tell("Delete this picture? Click the bin again (or Del) within 3 seconds.", true);
      return;
    }
    disarm(); removeIt();
  }
  async function removeIt() {
    const it = V.list[V.i];
    const r = await call("/image/delete", { path: it.path }).catch((e) => ({ ok: false, error: e.message }));
    if (!V) return;
    if (!r || !r.ok) { tell("Not deleted: " + ((r && r.error) || "no answer"), true); return; }
    V.list.splice(V.i, 1);
    if (window.LokiHome && typeof window.LokiHome.refresh === "function") window.LokiHome.refresh();
    if (!V.list.length) { close(); return; }
    V.i = Math.min(V.i, V.list.length - 1); V.before = ""; show();
    tell("Deleted " + (it.name || it.path) + " - moved to " + (r.trash || "the trash folder") + ".");
  }

  // ---- settings (engine/image_settings.py draws the panel; /image/remake makes the new picture)
  async function toggleSettings() {
    if (!V) return;
    if (!V.panel.hidden) { V.panel.hidden = true; V.wrap.classList.remove("lv-with-settings"); V.bSet.removeAttribute("aria-pressed"); return; }
    if (!V.schema) {
      const r = await call("/image/settings").catch(() => null);
      if (!V) return;
      if (!r || !r.ok) { tell("The settings did not load.", true); return; }
      V.schema = r.settings; V.backends = (r.backends && r.backends.order) || [];
    }
    V.panel.hidden = false; V.wrap.classList.add("lv-with-settings"); V.bSet.setAttribute("aria-pressed", "true");
    fillSettings();
  }
  function fillSettings() {
    const it = V.list[V.i], info = V.info || {}, meta = info.meta || {}, prev = meta.settings || {};
    const start = Object.assign({ prompt: meta.idea || meta.prompt || "", seed: meta.seed || 0, style: meta.style || "",
      width: info.size ? info.size[0] : 1024, height: info.size ? info.size[1] : 1024 }, prev);
    const p = V.panel; p.replaceChildren();
    const head = mk("div", "lv-set-head"); head.append(mk("strong", "", "Settings"), mk("span", "lv-set-file", it.name || ""));
    const shut = btn("close", "Close settings", "Close this panel.", toggleSettings); head.append(shut);
    const form = mk("form", "lv-set-form"); const fields = {};
    const promptBox = mk("textarea", "lv-set-prompt"); promptBox.rows = 3; promptBox.value = start.prompt || "";
    promptBox.title = "What the picture shows - the prompt it is remade from"; fields.prompt = promptBox;
    form.append(mk("label", "lv-set-label", "Prompt"), promptBox);
    const exact = mk("input"); exact.type = "checkbox"; exact.checked = !!(prev.width || prev.height);
    const exactRow = mk("label", "lv-set-check"); exactRow.append(exact, mk("span", "", "Exact size in pixels"));
    exactRow.title = "On: width and height in pixels. Off: aspect + megapixels (the sizes models are trained near).";
    let group = "";
    for (const s of V.schema) {
      if (s.group !== group) { group = s.group; form.append(mk("div", "lv-set-group", group)); if (group === "Size") form.append(exactRow); }
      const row = mk("label", "lv-set-row"); row.title = s.what; row.dataset.key = s.key;
      row.append(mk("span", "lv-set-label", s.label));
      let input;
      if (s.type === "enum") { input = mk("select"); for (const o of s.options) { const op = mk("option", "", String(o) === "" ? "(default)" : String(o)); op.value = String(o); input.append(op); } }
      else if (s.type === "bool") { input = mk("input"); input.type = "checkbox"; }
      else if (s.type === "text") { input = mk("input"); input.type = "text"; }
      else { input = mk("input"); input.type = "number"; input.min = s.min; input.max = s.max; input.step = s.step; }
      const v = s.key in start ? start[s.key] : s.default;
      if (s.type === "bool") input.checked = !!v; else input.value = v == null ? "" : String(v);
      fields[s.key] = input; row.append(input); form.append(row);
    }
    const paint = () => {
      const be = fields.backend ? fields.backend.value : "auto";
      for (const s of V.schema) {
        const row = form.querySelector('[data-key="' + s.key + '"]'); const st = fieldState(s, be);
        const sizeOff = ((s.key === "width" || s.key === "height") && !exact.checked) || ((s.key === "aspect" || s.key === "megapixels") && exact.checked);
        row.classList.toggle("lv-set-off", !st.on || sizeOff);
        row.title = st.on ? s.what : st.why;
      }
    };
    form.addEventListener("input", paint); exact.addEventListener("change", paint); paint();
    const go = mk("button", "send small", "Remake"); go.type = "submit";
    go.title = "Make a new picture with these settings - this one is kept";
    const out = mk("div", "lv-set-notes");
    form.append(go, out);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const values = {}; for (const [k, el] of Object.entries(fields)) values[k] = el.type === "checkbox" ? el.checked : el.value;
      const settings = Object.assign(collect(values, V.schema, exact.checked), { prompt: promptBox.value.trim() });
      out.textContent = "Starting...";
      const r = await call("/image/remake", { path: it.path, settings }).catch((er) => ({ ok: false, error: er.message }));
      if (!r || !r.ok) { out.textContent = "Not started: " + ((r && r.error) || "no answer"); return; }
      out.textContent = (r.notes || []).join(" · ") || "Making it...";
      const t0 = Date.now();
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 2000));
        if (!V) return;
        const j = await call("/image/remake?job=" + encodeURIComponent(r.job)).catch(() => null);
        if (j && j.status === "done") { out.textContent = "Made " + (j.files || []).join(", ") + " with " + (j.backend || "?");
          for (const f of (j.files || []).slice().reverse()) insertMade({ file: f.split("/").pop(), path: f }, null); return; }
        if (j && j.status === "failed") { out.textContent = "Not made: " + j.error; return; }
        out.textContent = "Making it... " + Math.round((Date.now() - t0) / 1000) + " s";
      }
    });
    p.append(head, form);
  }

  function tell(text, bad) { if (!V) return; V.say.textContent = text || ""; V.say.classList.toggle("bad", !!bad); }

  function onKey(e) {
    if (!V) return;
    const typing = e.target && /^(INPUT|TEXTAREA)$/.test(e.target.tagName);
    if (e.key === "Escape") {
      e.preventDefault(); e.stopPropagation();
      if (!V.editRow.hidden) V.editRow.hidden = true; else if (!V.why.hidden) V.why.hidden = true;
      else if (!V.panel.hidden) toggleSettings(); else if (V.focus) unfocus(); else if (V.cropper) { stopSelect(); tell(""); } else close();
      return;
    }
    if (typing) return;
    const k = e.key.toLowerCase();
    const handled = { arrowleft: () => go(-1), arrowright: () => go(1), s: toggleSelect, f: toggleFocus, e: showEdit, g: toggleSettings, delete: askDelete, backspace: askDelete,
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

  const api_ = { open, close, step, shareBox, clean, fieldState, collect, thumbs, isOpen: () => !!V };
  if (typeof window !== "undefined") window.LokiViewer = api_;
  return api_;
})();
if (typeof module !== "undefined") module.exports = LokiViewer;
