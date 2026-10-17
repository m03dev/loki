// LOKI's own accessibility rules (session 29), run in the page by tests/test_usability.py.
// axe-core could not be vendored (no package registry from the build sandbox), so these are the
// WCAG 2.1 A/AA checks that matter most for LOKI, written out plainly:
//   name        every visible button, link, tab, input, select and textarea has an accessible name
//   img-alt     every <img> has alt; decorative <svg> is aria-hidden
//   dup-id      no two elements share an id
//   tabindex    no positive tabindex
//   lang        <html lang> is set, and dir="rtl" for Arabic
//   dialog      every open role=dialog has a name and aria-modal
//   role        only known ARIA roles
//   contrast    visible text has 4.5:1 contrast (3:1 for 18.66px bold / 24px), 7:1 with high contrast
//   aria-ref    aria-labelledby / aria-describedby point at existing ids
// (scope) => [{rule, where, detail}]; scope is a CSS selector to check inside (default: the document).
(scope) => {
  const root = scope ? document.querySelector(scope) : document.body;
  if (!root) return [{ rule: "scope", where: scope, detail: "not found" }];
  const out = [];
  const where = (n) => {
    let s = n.tagName.toLowerCase();
    if (n.id) s += "#" + n.id;
    else if (n.className && typeof n.className === "string") s += "." + n.className.trim().split(/\s+/).slice(0, 2).join(".");
    const t = (n.textContent || "").trim().slice(0, 30);
    return s + (t ? " \"" + t + "\"" : "");
  };
  const visible = (n) => {
    if (!n.isConnected) return false;
    const r = n.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;
    const cs = getComputedStyle(n);
    if (cs.visibility === "hidden" || cs.display === "none" || Number(cs.opacity) === 0) return false;
    return !n.closest("[hidden], [aria-hidden='true'], .world-bg");
  };
  const byId = (id) => document.getElementById(id);
  function accName(n) {
    const lb = n.getAttribute("aria-labelledby");
    if (lb) return lb.split(/\s+/).map((id) => (byId(id) ? byId(id).textContent : "")).join(" ").trim();
    if ((n.getAttribute("aria-label") || "").trim()) return n.getAttribute("aria-label").trim();
    if (n.labels && n.labels.length) return [...n.labels].map((l) => l.textContent).join(" ").trim();
    if (n.closest("label") && /^(INPUT|SELECT|TEXTAREA)$/.test(n.tagName)) return n.closest("label").textContent.trim();
    if (/^(BUTTON|A|SUMMARY)$/.test(n.tagName) || /^(tab|button|radio|link|menuitem|option)$/.test(n.getAttribute("role") || "")) {
      const t = (n.innerText || n.textContent || "").trim();
      if (t) return t;
      const img = n.querySelector("img[alt]");
      if (img && img.alt.trim()) return img.alt.trim();
    }
    if ((n.getAttribute("title") || "").trim()) return n.getAttribute("title").trim();
    if (n.tagName === "INPUT" && /^(submit|button|reset)$/.test(n.type) && n.value) return n.value;
    return "";
  }
  const controls = root.querySelectorAll('button, a[href], input:not([type="hidden"]), select, textarea, summary, [role="tab"], [role="button"], [role="radio"], [role="link"]');
  for (const n of controls) {
    if (!visible(n) && !(n.tagName === "INPUT" && n.type === "checkbox" && visible(n.parentElement))) continue;
    if (!accName(n)) out.push({ rule: "name", where: where(n), detail: "no accessible name" });
  }
  for (const n of root.querySelectorAll("img")) if (!n.hasAttribute("alt")) out.push({ rule: "img-alt", where: where(n), detail: "img without alt" });
  for (const n of root.querySelectorAll("svg")) {
    if (n.getAttribute("aria-hidden") !== "true" && !n.getAttribute("aria-label") && !n.getAttribute("role") && !n.querySelector("title") && visible(n)) {
      out.push({ rule: "img-alt", where: where(n.parentElement || n), detail: "svg is neither aria-hidden nor labelled" });
    }
  }
  const seen = {};
  for (const n of document.querySelectorAll("[id]")) {
    if (seen[n.id]) out.push({ rule: "dup-id", where: "#" + n.id, detail: "id used twice" });
    seen[n.id] = true;
  }
  for (const n of root.querySelectorAll("[tabindex]")) if (Number(n.getAttribute("tabindex")) > 0) out.push({ rule: "tabindex", where: where(n), detail: "positive tabindex" });
  const html = document.documentElement;
  if (!html.lang) out.push({ rule: "lang", where: "html", detail: "no lang" });
  if (html.lang === "ar" && html.dir !== "rtl") out.push({ rule: "lang", where: "html", detail: "Arabic without dir=rtl" });
  for (const d of document.querySelectorAll('[role="dialog"]')) {
    if (!visible(d)) continue;
    if (!accName(d)) out.push({ rule: "dialog", where: where(d), detail: "dialog has no name" });
    if (d.getAttribute("aria-modal") !== "true") out.push({ rule: "dialog", where: where(d), detail: "dialog is not aria-modal" });
  }
  const ROLES = new Set(["alert", "alertdialog", "button", "checkbox", "dialog", "group", "link", "list", "listitem", "menu", "menuitem",
    "menuitemradio", "menuitemcheckbox", "navigation", "option", "progressbar", "radio", "radiogroup", "region", "search", "status",
    "switch", "tab", "tablist", "tabpanel", "textbox", "toolbar", "tooltip", "img", "presentation", "none", "log", "main", "banner",
    "complementary", "contentinfo", "form", "heading", "listbox", "separator", "grid", "row", "cell", "table", "application", "note", "marquee", "timer", "feed", "article", "document"]);
  for (const n of root.querySelectorAll("[role]")) {
    for (const r of n.getAttribute("role").split(/\s+/)) if (r && !ROLES.has(r)) out.push({ rule: "role", where: where(n), detail: "unknown role " + r });
  }
  for (const n of root.querySelectorAll("[aria-labelledby], [aria-describedby]")) {
    for (const attr of ["aria-labelledby", "aria-describedby"]) {
      for (const id of (n.getAttribute(attr) || "").split(/\s+/).filter(Boolean)) if (!byId(id)) out.push({ rule: "aria-ref", where: where(n), detail: attr + " -> missing #" + id });
    }
  }
  // contrast
  const parse = (c) => {
    const m = /rgba?\(([^)]+)\)/.exec(c || "");
    if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const blend = (top, under) => {
    const a = top[3];
    return [top[0] * a + under[0] * (1 - a), top[1] * a + under[1] * (1 - a), top[2] * a + under[2] * (1 - a), 1];
  };
  function background(n) {
    const layers = [];
    for (let e = n; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage && cs.backgroundImage !== "none" && !/gradient/.test(cs.backgroundImage)) return null;   // a picture: unknown
      if (/gradient/.test(cs.backgroundImage || "")) {   // a gradient: judge by its darkest/lightest stop below
        const stops = (cs.backgroundImage.match(/rgba?\([^)]+\)/g) || []).map(parse).filter((s) => s && s[3] >= 1);
        if (stops.length) { layers.push(stops.reduce((a, b) => (Math.abs(lum(a) - 0.5) < Math.abs(lum(b) - 0.5) ? a : b))); break; }
      }
      const c = parse(cs.backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
    }
    let bg = [255, 255, 255, 1];
    const base = parse(getComputedStyle(document.body).backgroundColor);
    if (base && base[3] >= 1) bg = base;
    for (let i = layers.length - 1; i >= 0; i--) bg = blend(layers[i], bg);
    return bg;
  }
  const strict = html.classList.contains("u-hc");
  const texts = new Set();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const t = walker.currentNode;
    if (t.textContent.trim().length < 2) continue;
    const el = t.parentElement;
    if (!el || texts.has(el) || !visible(el)) continue;
    texts.add(el);
    if (el.closest("button:disabled, [aria-disabled='true'], .world-labels, .wlabel, .icon-tip, canvas, svg")) continue;
    const cs = getComputedStyle(el);
    const fg = parse(cs.color);
    const bg = background(el);
    if (!fg || !bg) continue;
    if (cs.webkitTextFillColor && /rgba?\(0, 0, 0, 0\)/.test(cs.webkitTextFillColor)) continue;   // gradient text (brand)
    const col = blend(fg, bg);
    const L1 = lum(col), L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(cs.fontSize), bold = Number(cs.fontWeight) >= 700;
    const large = size >= 24 || (bold && size >= 18.66);
    const need = strict ? (large ? 4.5 : 7) : (large ? 3 : 4.5);
    if (ratio + 0.01 < need) out.push({ rule: "contrast", where: where(el), detail: ratio.toFixed(2) + ":1 < " + need + ":1 (" + cs.color + " on rgb(" + bg.slice(0, 3).map(Math.round).join(",") + "))" });
  }
  return out;
}
