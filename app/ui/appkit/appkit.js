// LOKI app kit - the bridge and the components every LOKI mini-app uses (docs/APPS.md).
// Load it in index.html: <link rel="stylesheet" href="/ui/appkit/appkit.css"> <script src="/ui/appkit/appkit.js"></script>
// then your own <script src="app.js" defer></script>. The app runs sealed off from LOKI; these are its only doors.
//
// THE BRIDGE (window.loki; every call returns a Promise)
//   loki.ready(fn)                       run fn once LOKI has said hello (at once when the page is opened on its own)
//   loki.app                             {name, title} of this app
//   await loki.store.get(key, fallback)  a saved JSON value (fallback when there is none)
//   await loki.store.set(key, value)     save it (kept by LOKI, synced to the owner's other machines)
//   await loki.store.remove(key)   await loki.store.keys()   await loki.store.all() -> {key: value}
//   await loki.ask(question, {data})     LOKI answers in text, seeing the app's saved data (+ data)
//   await loki.files.save(name, text)    the owner approves; saved in App files/<app>/ -> {name, path} or null
//   await loki.files.open({accept})      the owner picks a file -> {name, text} or null
//
// COMPONENTS (window.kit)
//   kit.h(tag, props, ...children)  make an element. props: {class, text, html: never - use text,
//        on: {click: fn}, value, type, placeholder, title, checked, disabled, style: {..}, data: {..}, attrs: {..}}
//        children: nodes, strings, numbers, arrays, null (skipped). e.g. kit.h("button", {class: "lk-btn primary",
//        on: {click: add}}, "Add")
//   kit.mount(parent, ...children)  replace parent's content     kit.$(selector)   kit.$$(selector)
//   kit.header(emoji, title, subtitle, ...actions)   the app's top bar (lk-head)
//   kit.card(title, ...children)     kit.stat(label, value, hint, tone?)   tone: "good" | "bad"
//   kit.field(label, input)          kit.input({...props})   kit.select(options, value, props)  options: ["a", {value, label}]
//   kit.button(label, onClick, cls)  cls: "primary" | "ghost" | "danger" | "sm" (combine with spaces)
//   kit.tabs(items, active, onChange)  items: ["Week", "Month"] or [{value, label}]
//   kit.progress(fraction)   kit.bars([{label, value}], format?)   kit.empty(emoji, text, buttonLabel?, onClick?)
//   kit.toast(text, tone?)   await kit.confirm(text, {ok, danger})   await kit.ask(label, {value, placeholder, type})
//   await kit.form(title, fields, submitLabel)  fields: [{name, label, type: text|number|date|select|textarea|checkbox,
//        value, options, placeholder, required}] -> {name: value} or null
//   await kit.askLoki(question, data)  a dialog that shows LOKI's answer (uses loki.ask)
//   kit.uid()  kit.today() -> "2026-10-17"  kit.date(iso, {weekday})  kit.money(n, currency="USD")  kit.number(n)
//   kit.sum(list, fn)  kit.groupBy(list, fn)  kit.sortBy(list, fn, desc)  kit.debounce(fn, ms)  kit.csv(rows)
// CSS: lk-app (page), lk-head, lk-card, lk-grid (.two .stats), lk-row, lk-col, lk-list + lk-item (.done .clickable),
//   lk-grow, lk-btn (.primary .ghost .danger .sm .icon), lk-input, lk-select, lk-textarea, lk-field, lk-form,
//   lk-check, lk-tag (.accent .ok .warn .bad .info), lk-stat, lk-progress, lk-table (+ td.lk-num), lk-tabs,
//   lk-empty, lk-muted, lk-small, lk-spacer, lk-answer. Colours: var(--lk-accent), --lk-ok, --lk-warn, --lk-bad.
"use strict";

(function () {
  const pending = new Map();
  let seq = 0;
  let hello = null;
  let connected = false;
  const readyFns = [];
  const memory = {};   // outside LOKI (opened on its own): a store that lasts until the page closes

  function call(op, args) {
    if (!connected) return Promise.resolve(offline(op, args || {}));
    return new Promise((resolve, reject) => {
      const id = "m" + (++seq);
      pending.set(id, { resolve, reject });
      window.parent.postMessage({ lokiApp: 1, id, op, args: args || {} }, "*");
      setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error("LOKI did not answer")); } }, op === "ask" ? 260000 : (op.startsWith("files.") ? 600000 : 20000));
    });
  }

  function offline(op, args) {
    if (op === "store.get") return Object.prototype.hasOwnProperty.call(memory, args.key) ? memory[args.key] : null;
    if (op === "store.set") { memory[args.key] = JSON.parse(JSON.stringify(args.value === undefined ? null : args.value)); return true; }
    if (op === "store.remove") { delete memory[args.key]; return true; }
    if (op === "store.keys") return Object.keys(memory);
    if (op === "store.all") return Object.assign({}, memory);
    if (op === "ask") return "(LOKI is not connected - open this app from LOKI's Apps area.)";
    return null;
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const msg = event.data;
    if (!msg || msg.lokiApp !== 1) return;
    if (msg.op === "hello") {
      hello = msg.app || {};
      connected = true;
      if (msg.theme) document.documentElement.dataset.theme = msg.theme;
      api.app.name = hello.name || ""; api.app.title = hello.title || "";
      flushReady();
      return;
    }
    const waiting = pending.get(msg.id);
    if (!waiting) return;
    pending.delete(msg.id);
    if (msg.ok) waiting.resolve(msg.result); else waiting.reject(new Error(msg.error || "failed"));
  });

  let flushed = false;
  function flushReady() {
    if (flushed) return;
    flushed = true;
    for (const fn of readyFns.splice(0)) { try { fn(); } catch (e) { console.error(e); } }
  }
  if (window.parent === window) setTimeout(flushReady, 0); else setTimeout(flushReady, 4000);
  if (window.parent !== window) window.parent.postMessage({ lokiApp: 1, id: "hello", op: "hello", args: {} }, "*");

  const api = {
    app: { name: "", title: "" },
    ready(fn) { if (flushed) setTimeout(fn, 0); else readyFns.push(fn); },
    get connected() { return connected; },
    store: {
      async get(key, fallback) { const v = await call("store.get", { key: String(key) }); return v === null || v === undefined ? (fallback === undefined ? null : fallback) : v; },
      set(key, value) { return call("store.set", { key: String(key), value: value === undefined ? null : value }); },
      remove(key) { return call("store.remove", { key: String(key) }); },
      keys() { return call("store.keys", {}); },
      all() { return call("store.all", {}); },
    },
    ask(question, opts) { return call("ask", { prompt: String(question || ""), data: (opts && opts.data !== undefined) ? opts.data : null }); },
    files: {
      save(name, text, opts) { return call("files.save", { name: String(name || "file.txt"), content: String(text == null ? "" : text), type: (opts && opts.type) || "" }); },
      open(opts) { return call("files.open", { accept: (opts && opts.accept) || "" }); },
    },
  };
  window.loki = api;

  // ------------------------------------------------------------ components
  function h(tag, props, ...children) {
    const node = document.createElement(tag);
    props = props || {};
    if (typeof props === "string" || props instanceof Node || Array.isArray(props)) { children.unshift(props); props = {}; }
    for (const [k, v] of Object.entries(props)) {
      if (v === undefined || v === null || v === false && k !== "value" && k !== "checked") continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = String(v);
      else if (k === "on") for (const [ev, fn] of Object.entries(v)) node.addEventListener(ev, fn);
      else if (k === "style") Object.assign(node.style, v);
      else if (k === "data") for (const [dk, dv] of Object.entries(v)) node.dataset[dk] = dv;
      else if (k === "attrs") for (const [ak, av] of Object.entries(v)) node.setAttribute(ak, av);
      else if (k === "value" || k === "checked" || k === "disabled" || k === "selected") node[k] = v;
      else node.setAttribute(k, v === true ? "" : v);
    }
    append(node, children);
    return node;
  }
  function append(node, children) {
    for (const c of children) {
      if (c === null || c === undefined || c === false) continue;
      if (Array.isArray(c)) append(node, c);
      else node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
  }
  function mount(parent, ...children) {
    if (typeof parent === "string") parent = document.querySelector(parent);
    parent.replaceChildren();
    append(parent, children);
    return parent;
  }
  const button = (label, onClick, cls) => h("button", { type: "button", class: "lk-btn" + (cls ? " " + cls : ""), on: onClick ? { click: onClick } : null }, label);
  const input = (props) => h("input", Object.assign({ class: "lk-input" }, props || {}));
  function select(options, value, props) {
    const s = h("select", Object.assign({ class: "lk-select" }, props || {}));
    for (const o of options || []) {
      const opt = typeof o === "object" ? o : { value: o, label: o };
      s.append(h("option", { value: String(opt.value) }, opt.label === undefined ? String(opt.value) : opt.label));
    }
    if (value !== undefined && value !== null) s.value = String(value);
    return s;
  }
  const field = (label, control) => h("label", { class: "lk-field" }, h("span", {}, label), control);
  const card = (title, ...children) => h("section", { class: "lk-card" }, title ? h("div", { class: "lk-card-head" }, h("h3", {}, title)) : null, ...children);
  function stat(label, value, hint, tone) {
    return h("div", { class: "lk-stat" + (tone ? " " + tone : "") }, h("span", { class: "lk-stat-label" }, label),
      h("span", { class: "lk-stat-value" }, value), hint ? h("span", { class: "lk-stat-hint" }, hint) : null);
  }
  function header(emoji, title, subtitle, ...actions) {
    return h("header", { class: "lk-head" },
      h("div", { class: "lk-title" }, emoji ? h("span", { class: "lk-emoji", "aria-hidden": "true" }, emoji) : null,
        h("div", {}, h("h1", {}, title), subtitle ? h("p", { class: "lk-sub" }, subtitle) : null)),
      h("div", { class: "lk-spacer" }), ...actions);
  }
  function tabs(items, active, onChange) {
    const box = h("div", { class: "lk-tabs", role: "tablist" });
    for (const it of items) {
      const o = typeof it === "object" ? it : { value: it, label: it };
      box.append(h("button", { type: "button", role: "tab", class: "lk-tab" + (o.value === active ? " on" : ""), "aria-selected": String(o.value === active),
        on: { click: () => onChange(o.value) } }, o.label));
    }
    return box;
  }
  function progress(fraction) {
    const f = Math.max(0, Number(fraction) || 0);
    return h("div", { class: "lk-progress" + (f > 1 ? " over" : ""), role: "progressbar", "aria-valuenow": String(Math.round(f * 100)) },
      h("i", { style: { width: Math.min(100, f * 100) + "%" } }));
  }
  function bars(data, format) {
    const max = Math.max(1, ...data.map((d) => Number(d.value) || 0));
    return h("div", { class: "lk-bars" }, data.map((d) => h("div", { class: "lk-bar", title: d.label + ": " + (format ? format(d.value) : d.value) },
      h("b", {}, format ? format(d.value) : String(d.value)), h("i", { style: { height: Math.max(1, (Number(d.value) || 0) / max * 100) + "%" } }), h("span", {}, d.label))));
  }
  const empty = (emoji, text, label, onClick) => h("div", { class: "lk-empty" }, h("div", { class: "lk-empty-icon" }, emoji || "✨"), h("p", {}, text), label ? button(label, onClick, "primary") : null);

  let toastBox = null;
  function toast(text, tone) {
    if (!toastBox) { toastBox = h("div", { class: "lk-toasts", role: "status", "aria-live": "polite" }); document.body.append(toastBox); }
    const t = h("div", { class: "lk-toast" + (tone ? " " + tone : "") }, text);
    toastBox.append(t);
    setTimeout(() => t.remove(), 2600);
  }
  function dialog(build) {
    return new Promise((resolve) => {
      const prev = document.activeElement;
      const close = (value) => { overlay.remove(); if (prev && prev.focus) prev.focus(); resolve(value); };
      const box = h("div", { class: "lk-dialog", role: "dialog", "aria-modal": "true" });
      const overlay = h("div", { class: "lk-overlay", on: { click: (e) => { if (e.target === overlay) close(null); } } }, box);
      overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(null); } });
      build(box, close);
      document.body.append(overlay);
      const first = box.querySelector("input, select, textarea, .lk-btn.primary, button");
      if (first) first.focus();
    });
  }
  const confirmBox = (text, opts) => dialog((box, close) => {
    opts = opts || {};
    box.append(h("p", {}, text), h("div", { class: "lk-actions" }, button(opts.cancel || "Cancel", () => close(false), "ghost"),
      button(opts.ok || "OK", () => close(true), opts.danger ? "danger" : "primary")));
  }).then((v) => !!v);
  const askBox = (label, opts) => dialog((box, close) => {
    opts = opts || {};
    const inp = input({ type: opts.type || "text", value: opts.value == null ? "" : String(opts.value), placeholder: opts.placeholder || "" });
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") close(inp.value); });
    box.append(h("h3", {}, label), inp, h("div", { class: "lk-actions" }, button("Cancel", () => close(null), "ghost"), button(opts.ok || "OK", () => close(inp.value), "primary")));
  });
  function form(title, fields, submitLabel) {
    return dialog((box, close) => {
      const controls = {};
      const grid = h("div", { class: "lk-col" });
      for (const f of fields) {
        let c;
        if (f.type === "select") c = select(f.options || [], f.value);
        else if (f.type === "textarea") c = h("textarea", { class: "lk-textarea", placeholder: f.placeholder || "" }, f.value == null ? "" : String(f.value));
        else if (f.type === "checkbox") c = h("input", { type: "checkbox", checked: !!f.value });
        else c = input({ type: f.type || "text", value: f.value == null ? "" : String(f.value), placeholder: f.placeholder || "", step: f.type === "number" ? (f.step || "any") : null });
        controls[f.name] = c;
        grid.append(f.type === "checkbox" ? h("label", { class: "lk-check" }, c, f.label) : field(f.label || f.name, c));
      }
      const submit = () => {
        const out = {};
        for (const f of fields) {
          const c = controls[f.name];
          let v = f.type === "checkbox" ? c.checked : c.value;
          if (f.type === "number") v = v === "" ? null : Number(v);
          if (f.required && (v === "" || v === null)) { c.focus(); toast((f.label || f.name) + " is needed", "bad"); return; }
          out[f.name] = v;
        }
        close(out);
      };
      grid.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); submit(); } });
      box.append(h("h3", {}, title), grid, h("div", { class: "lk-actions" }, button("Cancel", () => close(null), "ghost"), button(submitLabel || "Save", submit, "primary")));
    });
  }
  function askLoki(question, data) {
    return dialog((box, close) => {
      const out = h("div", { class: "lk-thinking" }, "LOKI is thinking…");
      box.append(h("h3", {}, "Ask LOKI"), h("p", { class: "lk-muted lk-small" }, question), out,
        h("div", { class: "lk-actions" }, button("Close", () => close(null), "primary")));
      api.ask(question, { data }).then((answer) => { out.className = "lk-answer"; out.textContent = answer; })
        .catch((e) => { out.className = "lk-answer"; out.textContent = "LOKI could not answer: " + e.message; });
    });
  }

  const pad = (n) => String(n).padStart(2, "0");
  const today = () => { const d = new Date(); return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); };
  function date(iso, opts) {
    if (!iso) return "";
    const d = new Date(String(iso).length <= 10 ? iso + "T12:00:00" : iso);
    if (isNaN(d)) return String(iso);
    return d.toLocaleDateString(undefined, Object.assign({ month: "short", day: "numeric" }, (opts && opts.weekday) ? { weekday: "short" } : {},
      (d.getFullYear() !== new Date().getFullYear()) ? { year: "numeric" } : {}));
  }
  function money(n, currency) {
    try { return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "USD" }).format(Number(n) || 0); }
    catch (_) { return (Number(n) || 0).toFixed(2); }
  }
  const number = (n, digits) => new Intl.NumberFormat(undefined, { maximumFractionDigits: digits === undefined ? 1 : digits }).format(Number(n) || 0);
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  const sum = (list, fn) => (list || []).reduce((a, x) => a + (Number(fn ? fn(x) : x) || 0), 0);
  const groupBy = (list, fn) => (list || []).reduce((m, x) => { const k = fn(x); (m[k] = m[k] || []).push(x); return m; }, {});
  const sortBy = (list, fn, desc) => [...(list || [])].sort((a, b) => { const x = fn(a), y = fn(b); return (x < y ? -1 : x > y ? 1 : 0) * (desc ? -1 : 1); });
  const debounce = (fn, ms) => { let t = 0; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms || 300); }; };
  const csv = (rows) => rows.map((r) => r.map((c) => { const s = c == null ? "" : String(c); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }).join(",")).join("\n");

  window.kit = { h, mount, $: (s) => document.querySelector(s), $$: (s) => [...document.querySelectorAll(s)], header, card, stat, field,
    input, select, button, tabs, progress, bars, empty, toast, confirm: confirmBox, ask: askBox, form, askLoki, dialog,
    uid, today, date, money, number, sum, groupBy, sortBy, debounce, csv };
})();
