// Paste and copy that always work in LOKI's window.
// The app window (pywebview: WebView2 on Windows, WKWebView on the Mac) has no right-click menu, and on
// some machines Ctrl/Cmd+V does nothing in a field - so pasting an API key "wouldn't work anywhere".
// This adds: a right-click menu on every text field (Cut, Copy, Paste, Select all), a Ctrl/Cmd+V that
// falls back to the engine reading the clipboard when the browser's paste does not arrive, and a Paste
// button next to key fields. The engine reads the computer's clipboard only on these explicit actions.
"use strict";
(function () {
  function isField(n) {
    return n && ((n.tagName === "TEXTAREA") || (n.tagName === "INPUT" && /^(text|password|search|url|email|number|tel|)$/i.test(n.type || "")))
      && !n.readOnly && !n.disabled;
  }

  async function readClipboard() {
    try {
      if (navigator.clipboard && navigator.clipboard.readText) {
        // a permission prompt can leave this hanging forever in an app window: give it a moment only
        const t = await Promise.race([navigator.clipboard.readText(), new Promise((r) => setTimeout(() => r(""), 400))]);
        if (typeof t === "string" && t) return t;
      }
    } catch (_) { /* the window may not allow it: ask the engine */ }
    try {
      const r = await api("/clipboard/paste", {});
      return (r && r.ok && r.text) || "";
    } catch (_) { return ""; }
  }

  async function writeClipboard(text) {
    try { if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(text); return true; } } catch (_) { /* fall back */ }
    try { const r = await api("/clipboard/copy", { text }); return !!(r && r.ok); } catch (_) { return false; }
  }

  function insert(field, text) {
    if (!text) return;
    field.focus();
    const start = field.selectionStart != null ? field.selectionStart : field.value.length;
    const end = field.selectionEnd != null ? field.selectionEnd : field.value.length;
    // a key or a single line: keys are pasted without stray line breaks or spaces around them
    const clean = field.tagName === "INPUT" ? text.replace(/[\r\n]+/g, " ").trim() : text;
    if (typeof field.setRangeText === "function" && field.type !== "number" && field.type !== "email") {
      field.setRangeText(clean, start, end, "end");
    } else {
      field.value = field.value.slice(0, start) + clean + field.value.slice(end);
    }
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }

  async function paste(field) { insert(field, await readClipboard()); }

  // ------------------------------------------------------------ Ctrl/Cmd+V that always arrives
  let pending = null;
  document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (!mod || e.altKey || (e.key || "").toLowerCase() !== "v" || !isField(e.target)) return;
    const field = e.target;
    const before = field.value;
    clearTimeout(pending);
    // let the browser paste normally; if nothing arrived, paste through the engine
    pending = setTimeout(() => { if (field.value === before) paste(field); }, 180);
  }, true);
  // (a paste event alone proves nothing: an app window can fire it with an empty clipboard - only a changed
  // field does, which the check above looks at)

  // ------------------------------------------------------------ right-click menu on text fields
  let menu = null;
  function closeMenu() { if (menu) { menu.remove(); menu = null; } }
  document.addEventListener("contextmenu", (e) => {
    const field = e.target;
    if (!isField(field)) return;
    e.preventDefault();
    closeMenu();
    menu = document.createElement("div");
    menu.className = "clip-menu";
    menu.setAttribute("role", "menu");
    const sel = () => field.value.slice(field.selectionStart || 0, field.selectionEnd || 0);
    const items = [
      ["Cut", async () => { const t = sel(); if (t && await writeClipboard(t)) insertDelete(field); }, !sel()],
      ["Copy", async () => { const t = sel(); if (t) await writeClipboard(t); }, !sel() || field.type === "password"],
      ["Paste", () => paste(field), false],
      ["Select all", () => { field.focus(); field.select(); }, !field.value],
    ];
    for (const [label, run, off] of items) {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label; b.disabled = !!off; b.setAttribute("role", "menuitem");
      b.addEventListener("mousedown", (ev) => ev.preventDefault());   // keep the field's selection
      b.addEventListener("click", () => { closeMenu(); run(); });
      menu.append(b);
    }
    document.body.append(menu);
    if (window.LokiPlace) LokiPlace.at(e.clientX, e.clientY, menu);
    else {
      const w = menu.offsetWidth, h = menu.offsetHeight;
      menu.style.left = Math.max(6, Math.min(e.clientX, window.innerWidth - w - 6)) + "px";
      menu.style.top = Math.max(6, Math.min(e.clientY, window.innerHeight - h - 6)) + "px";
    }
  });
  function insertDelete(field) {
    const s0 = field.selectionStart, e0 = field.selectionEnd;
    if (s0 !== e0) { field.setRangeText("", s0, e0, "end"); field.dispatchEvent(new Event("input", { bubbles: true })); }
  }
  document.addEventListener("mousedown", (e) => { if (menu && !menu.contains(e.target)) closeMenu(); }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  window.addEventListener("blur", closeMenu);

  // ------------------------------------------------------------ a Paste button on key fields
  function addPasteButtons() {
    for (const field of document.querySelectorAll('input[type="password"]:not([data-clip])')) {
      field.dataset.clip = "1";
      const b = document.createElement("button");
      b.type = "button";
      b.className = "clip-paste";
      b.textContent = "Paste";
      b.dataset.icon = "paste";
      b.dataset.tipName = "Paste";
      b.dataset.tipWhat = "Paste from the clipboard (works even when Ctrl+V does not).";
      b.addEventListener("click", () => paste(field));
      field.insertAdjacentElement("afterend", b);
    }
  }
  let queued = false;
  document.addEventListener("DOMContentLoaded", () => {
    addPasteButtons();
    new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; addPasteButtons(); });
    }).observe(document.body, { childList: true, subtree: true });
  });
  window.LokiClipboard = { read: readClipboard, write: writeClipboard, paste };
})();
