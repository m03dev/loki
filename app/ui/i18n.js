// LOKI in your language (session 29). String tables live in app/ui/i18n/<lang>.json.
//
// Translation is OPT-IN per element, so UI other changes add keeps working (in English) until
// someone gives it keys:
//   <b data-i18n="gallery.title">What can LOKI do?</b>            textContent from a key
//   <input data-i18n-attr="placeholder:help.search">              attributes (comma list attr:key)
//   <span data-i18n-src="Settings">Settings</span>                 by its English text ("phrases")
// Icon buttons (icons.js) keep their English name in data-tip-src; their tooltip and
// aria-label are translated from "phrases". Static parts of index.html are annotated here
// (STATIC below) so index.html itself needs no edits.
//
// window.LokiI18n: lang, dir, t(key, fallback, vars), phrase(english), set(lang), apply(root), ready
"use strict";

(function () {
  const LANGS = {
    en: ["English", "ltr"], es: ["Español", "ltr"], fr: ["Français", "ltr"], de: ["Deutsch", "ltr"],
    ar: ["العربية", "rtl"], hi: ["हिन्दी", "ltr"], zh: ["中文", "ltr"], ja: ["日本語", "ltr"],
  };
  const tables = {};          // lang -> parsed table
  let lang = "en";
  let readyResolve;
  const ready = new Promise((r) => { readyResolve = r; });

  // [selector, key, attr?]: index.html's own words. attr "text" = textContent.
  const STATIC = [
    [".welcome-title", "home.title"],
    [".welcome-sub", "home.sub"],
    ['.welcome-chips .chip:nth-child(1)', "home.chip1"],
    ['.welcome-chips .chip:nth-child(2)', "home.chip2"],
    ['.welcome-chips .chip:nth-child(3)', "home.chip3"],
    ["#prompt", "composer.label", "aria-label"],
    ["#settings-title", "settings.title"],
    ["#settings-search", "settings.search", "placeholder"],
    ["#settings-search", "settings.search", "aria-label"],
    ["#setup-title", "setup.title"],
    ["#close-setup", "common.later"],
    ["#qr-title", "qr.title"],
    ["#qr-close", "common.close"],
    [".sidebar", "a11y.region_sidebar", "aria-label"],
    ["#conversations", "a11y.region_chats", "aria-label"],
    ["#transcript", "a11y.region_conversation", "aria-label"],
    ["#work-summary", "work.working"],
    ['[data-panel="system"] .panel-head h3', "panel.system.title"],
    ['[data-panel="general"] .panel-head h3', "panel.general.title"],
    ['[data-panel="connections"] .panel-head h3', "panel.connections.title"],
    ['[data-panel="connections"] .panel-head .note', "panel.connections.note"],
    ['[data-panel="models"] .panel-head h3', "panel.models.title"],
    ['[data-panel="models"] .panel-head .note', "panel.models.note"],
    ['[data-panel="usage"] .panel-head h3', "panel.usage.title"],
    ['[data-panel="memory"] .panel-head h3', "panel.memory.title"],
    ['[data-panel="machines"] .panel-head h3', "panel.machines.title"],
    ['[data-panel="machines"] .panel-head .note', "panel.machines.note"],
    ['[data-panel="tools"] .panel-head h3', "panel.tools.title"],
    ['[data-panel="capabilities"] .panel-head h3', "panel.capabilities.title"],
    ['[data-panel="creations"] .panel-head h3', "panel.creations.title"],
  ];

  function lookup(table, key) {
    if (!table) return undefined;
    const v = table[key];
    return typeof v === "string" && v !== "" ? v : undefined;
  }

  function fill(text, vars) {
    if (!vars) return text;
    return text.replace(/\{(\w+)\}/g, (m, k) => (vars[k] !== undefined ? String(vars[k]) : m));
  }

  function t(key, fallback, vars) {
    const v = lookup(tables[lang], key);
    const en = lookup(tables.en, key);
    return fill(v !== undefined ? v : en !== undefined ? en : (fallback !== undefined ? fallback : key), vars);
  }

  function phrase(english) {
    if (!english) return english;
    const p = (tables[lang] && tables[lang].phrases) || {};
    return typeof p[english] === "string" && p[english] ? p[english] : english;
  }

  function supported(code) { return Object.prototype.hasOwnProperty.call(LANGS, code) ? code : ""; }

  function guess() {
    let saved = "";
    try { saved = localStorage.getItem("loki-lang") || ""; } catch (_) { /* no storage */ }
    if (saved && saved !== "auto" && supported(saved)) return saved;
    const nav = (navigator.languages && navigator.languages[0]) || navigator.language || "en";
    return supported(String(nav).split("-")[0].toLowerCase()) || "en";
  }

  async function load(code) {
    if (tables[code]) return tables[code];
    try {
      const r = await fetch("/ui/i18n/" + code + ".json", { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      tables[code] = await r.json();
    } catch (e) {
      console.warn("LOKI i18n: could not load " + code + " (" + e + "); using English");
      tables[code] = null;
    }
    return tables[code];
  }

  function annotateStatic() {
    for (const [sel, key, attr] of STATIC) {
      for (const node of document.querySelectorAll(sel)) {
        if (!attr || attr === "text") { if (!node.dataset.i18n) node.dataset.i18n = key; continue; }
        const list = (node.dataset.i18nAttr || "").split(",").filter(Boolean);
        if (!list.some((p) => p.startsWith(attr + ":"))) list.push(attr + ":" + key);
        node.dataset.i18nAttr = list.join(",");
      }
    }
    // the chips send their own words: translate the prompt they send too
    document.querySelectorAll(".welcome-chips .chip").forEach((chip, i) => {
      if (!chip.dataset.i18nPromptKey) chip.dataset.i18nPromptKey = "home.chip" + (i + 1) + "_prompt";
    });
  }

  function setText(node, text) { if (node.textContent !== text) node.textContent = text; }
  function setAttr(node, attr, text) { if (node.getAttribute(attr) !== text) node.setAttribute(attr, text); }

  function applyTo(node) {
    const d = node.dataset;
    if (d.i18n) {
      if (d.i18nEn === undefined) d.i18nEn = node.textContent;
      setText(node, t(d.i18n, d.i18nEn));
    }
    if (d.i18nAttr) {
      for (const pair of d.i18nAttr.split(",")) {
        const [attr, key] = pair.split(":");
        if (!attr || !key) continue;
        const keep = "i18nEn_" + attr.replace(/[^a-z]/gi, "");
        if (d[keep] === undefined) d[keep] = node.getAttribute(attr) || "";
        setAttr(node, attr, t(key, d[keep]));
      }
    }
    if (d.i18nSrc) setText(node, phrase(d.i18nSrc));
    if (d.i18nPromptKey && d.prompt !== undefined) {
      if (d.promptEn === undefined) d.promptEn = d.prompt;
      const p = t(d.i18nPromptKey, d.promptEn);
      if (d.prompt !== p) d.prompt = p;
    }
    if (d.tipSrc) {   // an icon button (icons.js)
      const name = phrase(d.tipSrc);
      if (d.tipName !== name) d.tipName = name;
      const what = phrase(d.tipWhatSrc || "");
      if (d.tipWhat !== what) d.tipWhat = what;
      setAttr(node, "aria-label", name);
      const label = node.querySelector(":scope > .tab-label");
      if (label) setText(label, name);
      const box = node.querySelector(":scope > input.icon-check");
      if (box) setAttr(box, "aria-label", name);
    }
  }

  const SEL = "[data-i18n],[data-i18n-attr],[data-i18n-src],[data-tip-src],[data-i18n-prompt-key]";

  function apply(root) {
    root = root || document;
    if (root.nodeType === 1 && root.matches(SEL)) applyTo(root);
    if (root.querySelectorAll) for (const node of root.querySelectorAll(SEL)) applyTo(node);
  }

  function setDocLang() {
    const html = document.documentElement;
    html.lang = lang;
    html.dir = LANGS[lang][1];
    html.classList.toggle("rtl", LANGS[lang][1] === "rtl");
  }

  async function set(code, opts) {
    code = supported(code) || "en";
    await load("en");
    await load(code);
    lang = tables[code] ? code : "en";
    setDocLang();
    apply(document);
    const prompt = document.getElementById("prompt"), main = document.getElementById("main");
    if (prompt && main) {   // app.js setView sets it per view; refresh it for the new language
      prompt.placeholder = main.classList.contains("home")
        ? t("composer.placeholder_home", "Ask Loki anything, or describe what to build") : t("composer.placeholder", "Message Loki");
    }
    if (!(opts && opts.quiet)) {
      try { localStorage.setItem("loki-lang", code); } catch (_) { /* no storage */ }
    }
    document.dispatchEvent(new CustomEvent("loki:language", { detail: { lang } }));
    return lang;
  }

  // what the engine remembers (Settings > General > Language), once the token is there
  async function syncWithEngine() {
    if (typeof api !== "function") return;
    const prefs = await api("/prefs/language").catch(() => null);
    if (!prefs || !prefs.ok) return;
    const nav = (navigator.language || "en").split("-")[0];
    if (prefs.ui === "auto") {
      api("/prefs/language", { browser: nav }).catch(() => {});
      let saved = "";
      try { saved = localStorage.getItem("loki-lang") || ""; } catch (_) { /* no storage */ }
      if (saved && saved !== "auto" && saved !== lang) await set(saved, { quiet: true });
    } else if (supported(prefs.ui) && prefs.ui !== lang) {
      await set(prefs.ui, { quiet: true });
    }
  }

  // Choose a language: the window switches at once and LOKI answers in it (POST /prefs/language).
  async function choose(code) {
    const got = await set(code === "auto" ? guess() : code);
    try { localStorage.setItem("loki-lang", code); } catch (_) { /* no storage */ }
    if (typeof api === "function") {
      await api("/prefs/language", { ui: code, browser: (navigator.language || "en").split("-")[0] }).catch(() => {});
    }
    return got;
  }

  window.LokiI18n = {
    get lang() { return lang; },
    get dir() { return LANGS[lang][1]; },
    languages: LANGS,
    t, phrase, set, choose, apply, ready, syncWithEngine,
    table: (code) => tables[code || lang],
  };

  document.addEventListener("DOMContentLoaded", async () => {
    annotateStatic();
    await set(guess(), { quiet: true });
    readyResolve(lang);
    // only what was added (cheap even when LOKI World's labels change every frame); every write
    // above is skipped when the text is already right, so this never feeds itself
    let pending = [];
    new MutationObserver((records) => {
      for (const r of records) for (const n of r.addedNodes) if (n.nodeType === 1) pending.push(n);
      if (pending.length === 0 || pending.queued) return;
      pending.queued = true;
      requestAnimationFrame(() => {
        const nodes = pending;
        pending = [];
        for (const n of nodes) if (n.isConnected) apply(n);
      });
    }).observe(document.body, { childList: true, subtree: true });
  });
})();
