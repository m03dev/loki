// Accessibility for everyone (session 29): text size, high contrast, reduced motion and
// colour-blind-safe status colours (saved per computer), keyboard navigation (a skip link,
// arrow keys in tab lists and radio groups, focus kept inside open dialogs) and LokiDialog,
// the accessible dialog the onboarding, gallery and help center use.
//
// Loaded early (not deferred) so the chosen look applies before the first paint.
"use strict";

(function () {
  const KEY = "loki-a11y";
  const DEFAULTS = { font: "100", contrast: false, motion: "auto", cbsafe: false };
  const FONT_STEPS = ["100", "115", "130", "150"];

  function read() {
    try { return Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(KEY) || "{}")); }
    catch (_) { return Object.assign({}, DEFAULTS); }
  }

  let prefs = read();

  function applyPrefs() {
    const root = document.documentElement;
    const font = FONT_STEPS.includes(String(prefs.font)) ? String(prefs.font) : "100";
    root.style.setProperty("--u-zoom", String(Number(font) / 100));
    root.classList.toggle("u-zoomed", font !== "100");
    root.dataset.fontSize = font;
    root.classList.toggle("u-hc", !!prefs.contrast);
    const sysReduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    root.classList.toggle("u-rm", prefs.motion === "reduce" || (prefs.motion === "auto" && sysReduce));
    root.classList.toggle("u-cb", !!prefs.cbsafe);
  }

  function save(change) {
    prefs = Object.assign({}, prefs, change);
    try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (_) { /* no storage: this session only */ }
    applyPrefs();
    document.dispatchEvent(new CustomEvent("loki:a11y", { detail: prefs }));
  }

  applyPrefs();

  const tr = (key, en, vars) => (window.LokiI18n ? window.LokiI18n.t(key, en, vars) : en);
  function node(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function keyed(n, key, en) { n.dataset.i18n = key; n.textContent = tr(key, en); return n; }

  // ------------------------------------------------------------ dialogs
  const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), ' +
    'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function focusables(root) {
    return [...root.querySelectorAll(FOCUSABLE)].filter((n) => n.offsetParent !== null || n === document.activeElement);
  }

  // Tab and Shift+Tab stay inside the topmost open dialog.
  function trap(ev) {
    if (ev.key !== "Tab") return;
    const open = [...document.querySelectorAll('.sheet:not([hidden]) [role="dialog"], .u-dialog:not([hidden]) [role="dialog"]')];
    const dialog = open[open.length - 1];
    if (!dialog) return;
    const items = focusables(dialog);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (!dialog.contains(document.activeElement)) { ev.preventDefault(); first.focus(); return; }
    if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
    else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
  }

  // An accessible dialog: role=dialog, aria-modal, labelled by its title, Esc closes, focus is
  // kept inside and goes back to what opened it.
  function LokiDialog(id, titleKey, titleEn, opts) {
    opts = opts || {};
    let wrap = document.getElementById(id);
    if (wrap) return wrap.lokiDialog;
    wrap = node("div", "sheet u-dialog" + (opts.cls ? " " + opts.cls : ""));
    wrap.id = id;
    wrap.hidden = true;
    const panel = node("div", "sheet-panel u-panel" + (opts.wide ? " wide" : ""));
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    const head = node("header", "sheet-head u-head");
    const title = keyed(node("h2", "u-title"), titleKey, titleEn);
    title.id = id + "-title";
    panel.setAttribute("aria-labelledby", title.id);
    const close = node("button", "quiet u-close");
    close.type = "button";
    close.dataset.i18n = "common.close";
    close.textContent = tr("common.close", "Close");
    head.append(title, close);
    const body = node("div", "u-body");
    panel.append(head, body);
    wrap.append(panel);
    document.body.append(wrap);
    let opener = null;
    const api = {
      wrap, panel, body, title, close,
      open() {
        opener = document.activeElement;
        wrap.hidden = false;
        setTimeout(() => { const f = opts.focus ? panel.querySelector(opts.focus) : null; (f || focusables(panel)[0] || close).focus(); }, 0);
        if (opts.onOpen) opts.onOpen(api);
      },
      hide(why) {
        if (wrap.hidden) return;
        wrap.hidden = true;
        if (opts.onClose) opts.onClose(why || "close");
        if (opener && opener.focus && document.contains(opener)) opener.focus();
      },
      get isOpen() { return !wrap.hidden; },
    };
    close.addEventListener("click", () => api.hide("close"));
    wrap.addEventListener("click", (e) => { if (e.target === wrap && !opts.modal) api.hide("outside"); });
    // keys typed in a dialog stay in it (app.js's "type to open the chat" and Esc for Settings)
    wrap.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Escape") api.hide("escape"); });
    wrap.lokiDialog = api;
    return api;
  }

  // ------------------------------------------------------------ keyboard
  function arrowNav(ev) {
    const t = ev.target;
    if (!t || !t.closest) return;
    const group = t.closest('[role="tablist"], [role="radiogroup"], .u-arrows');
    if (!group) return;
    const vertical = group.getAttribute("aria-orientation") === "vertical";
    const rtl = document.documentElement.dir === "rtl";
    const next = vertical ? "ArrowDown" : rtl ? "ArrowLeft" : "ArrowRight";
    const prev = vertical ? "ArrowUp" : rtl ? "ArrowRight" : "ArrowLeft";
    if (![next, prev, "Home", "End"].includes(ev.key)) return;
    const items = [...group.querySelectorAll('[role="tab"], [role="radio"], .u-arrow-item')].filter((n) => n.offsetParent !== null && !n.disabled);
    const i = items.indexOf(t.closest('[role="tab"], [role="radio"], .u-arrow-item'));
    if (i < 0) return;
    ev.preventDefault();
    const j = ev.key === "Home" ? 0 : ev.key === "End" ? items.length - 1 : (i + (ev.key === next ? 1 : -1) + items.length) % items.length;
    items[j].focus();
    // a tab shows its panel and a radio is chosen as it gets focus (WAI-ARIA tabs / radio group)
    if (["tablist", "radiogroup"].includes(group.getAttribute("role"))) items[j].click();
  }

  function roving() {
    // only the selected tab is in the Tab order; arrows move between them (WAI-ARIA tabs pattern)
    for (const list of document.querySelectorAll('[role="tablist"]')) {
      const tabs = [...list.querySelectorAll('[role="tab"]')];
      const sel = tabs.find((x) => x.getAttribute("aria-selected") === "true") || tabs[0];
      for (const tab of tabs) tab.tabIndex = tab === sel ? 0 : -1;
    }
  }

  function skipLink() {
    if (document.getElementById("u-skip")) return;
    const a = node("a", "u-skip");
    a.id = "u-skip";
    a.href = "#prompt";
    keyed(a, "a11y.skip", "Skip to the message box");
    a.addEventListener("click", (e) => {
      e.preventDefault();
      if (typeof summon === "function") summon(true);
      const p = document.getElementById("prompt");
      if (p) setTimeout(() => p.focus(), 0);
    });
    document.body.prepend(a);
  }

  // ------------------------------------------------------------ Settings > General: language + accessibility
  function choiceRow(labelKey, labelEn, hintKey, hintEn, control) {
    const card = node("div", "set-card u-pref");
    const text = node("div", "set-text");
    const b = keyed(node("b"), labelKey, labelEn);
    const id = "u-" + labelKey.replace(/[^a-z0-9]/gi, "-");
    b.id = id;
    text.append(b);
    if (hintKey) text.append(keyed(node("small"), hintKey, hintEn));
    if (control.setAttribute && !control.getAttribute("aria-label")) control.setAttribute("aria-labelledby", id);
    card.append(text, control);
    return card;
  }

  function select(options, value, onChange) {
    const s = node("select", "u-select");
    for (const [v, key, en] of options) {
      const o = node("option");
      o.value = v;
      if (key) { o.dataset.i18n = key; o.textContent = tr(key, en); } else o.textContent = en;
      s.append(o);
    }
    s.value = value;
    s.addEventListener("change", () => onChange(s.value));
    return s;
  }

  function checkbox(on, onChange) {
    const label = node("label", "u-switch");
    const box = node("input");
    box.type = "checkbox";
    box.checked = !!on;
    box.addEventListener("change", () => onChange(box.checked));
    label.append(box, node("span", "u-switch-track"));
    return { label, box };
  }

  async function render(box) {
    if (!box || box.querySelector(".u-prefs")) return;
    const wrap = node("section", "u-prefs");
    wrap.setAttribute("aria-labelledby", "u-prefs-title");
    const h = keyed(node("h4", "th-sub"), "prefs.title", "Language and accessibility");
    h.id = "u-prefs-title";
    wrap.append(h);
    const langs = (window.LokiI18n && window.LokiI18n.languages) || { en: ["English", "ltr"] };
    let saved = "auto";
    try { saved = localStorage.getItem("loki-lang") || "auto"; } catch (_) { /* no storage */ }
    let reply = "match";
    if (typeof api === "function") {
      const p = await api("/prefs/language").catch(() => null);
      if (p && p.ok) { saved = p.ui || saved; reply = p.reply || reply; }
    }
    const langSel = select([["auto", "prefs.lang_auto", "Same as this computer"]].concat(
      Object.entries(langs).map(([code, [name]]) => [code, "", name])), saved, (v) => window.LokiI18n && window.LokiI18n.choose(v));
    wrap.append(choiceRow("prefs.lang", "Language", "prefs.lang_hint", "The words in LOKI's window. Translations other than English are machine-drafted and waiting for review.", langSel));
    const replySel = select([["match", "prefs.reply_match", "The language I write in"], ["ui", "prefs.reply_ui", "Always the window's language"],
      ["en", "prefs.reply_en", "Always English"]], reply, (v) => { if (typeof api === "function") api("/prefs/language", { reply: v }); });
    wrap.append(choiceRow("prefs.reply", "LOKI answers in", "", "", replySel));
    const size = select(FONT_STEPS.map((f) => [f, "prefs.font_" + f, f + "%"]), String(prefs.font), (v) => save({ font: v }));
    wrap.append(choiceRow("prefs.font", "Text size", "prefs.font_hint", "Makes everything in the window bigger.", size));
    const hc = checkbox(prefs.contrast, (on) => save({ contrast: on }));
    wrap.append(choiceRow("prefs.contrast", "High contrast", "prefs.contrast_hint", "Black and white with strong outlines; easier to read.", hc.label));
    hc.box.setAttribute("aria-labelledby", "u-prefs-contrast");
    const rm = select([["auto", "prefs.motion_auto", "Follow this computer's setting"], ["reduce", "prefs.motion_reduce", "Reduce motion"],
      ["full", "prefs.motion_full", "Full motion"]], prefs.motion, (v) => save({ motion: v }));
    wrap.append(choiceRow("prefs.motion", "Motion", "prefs.motion_hint", "Reduce motion stops animations and hides the moving 3D world.", rm));
    const cb = checkbox(prefs.cbsafe, (on) => save({ cbsafe: on }));
    wrap.append(choiceRow("prefs.cbsafe", "Colour-blind-safe colours", "prefs.cbsafe_hint", "Blue, orange and yellow status colours, always with a symbol.", cb.label));
    cb.box.setAttribute("aria-labelledby", "u-prefs-cbsafe");
    const tour = node("button", "quiet");
    tour.type = "button";
    keyed(tour, "prefs.tour", "Show the welcome tour again");
    tour.addEventListener("click", () => { if (window.Onboarding) window.Onboarding.open(true); });
    const keys = node("button", "quiet");
    keys.type = "button";
    keyed(keys, "prefs.shortcuts", "Keyboard shortcuts");
    keys.addEventListener("click", () => { if (window.LokiHelp) window.LokiHelp.open("keyboard-shortcuts"); });
    const row = node("div", "u-row");
    row.append(tour, keys);
    wrap.append(row);
    box.prepend(wrap);
  }

  window.LokiA11y = { get prefs() { return Object.assign({}, prefs); }, save, applyPrefs, render, LokiDialog, focusables, FONT_STEPS };
  window.LokiDialog = LokiDialog;

  document.addEventListener("keydown", trap, true);
  document.addEventListener("keydown", arrowNav, true);
  if (window.matchMedia) {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mq.addEventListener) mq.addEventListener("change", applyPrefs);
  }
  // A 3D engine (Babylon) gives its canvas tabindex="1", which jumps it ahead of everything in the
  // Tab order; the world behind the home screen is decorative (aria-hidden) and must not take focus.
  function fixTabindex(n) {
    if (!n || n.nodeType !== 1 || !n.hasAttribute("tabindex")) return;
    const v = Number(n.getAttribute("tabindex"));
    if (n.closest('[aria-hidden="true"]') && v >= 0) n.setAttribute("tabindex", "-1");
    else if (v > 0) n.setAttribute("tabindex", "0");
  }

  document.addEventListener("DOMContentLoaded", () => {
    skipLink();
    roving();
    document.querySelectorAll("[tabindex]").forEach(fixTabindex);
    new MutationObserver((recs) => { for (const r of recs) fixTabindex(r.target); })
      .observe(document.body, { subtree: true, attributes: true, attributeFilter: ["tabindex"] });
    // tab selection changes (app.js showTab): keep the roving tabindex right
    new MutationObserver(roving).observe(document.body, { subtree: true, attributes: true, attributeFilter: ["aria-selected"] });
    // Settings opened with the mouse or keyboard: focus returns to the button that opened it on close
    const settings = document.getElementById("settings");
    if (settings) {
      let opener = null;
      new MutationObserver(() => {
        if (!settings.hidden) opener = opener || document.activeElement;
        else if (opener) { const o = opener; opener = null; if (document.contains(o) && o.focus) o.focus(); }
      }).observe(settings, { attributes: true, attributeFilter: ["hidden"] });
    }
  });
})();
