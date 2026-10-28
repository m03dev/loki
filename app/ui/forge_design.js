// Forge > Design: real layered design files with OpenPencil (engine/design.py, engine/design_api.py; owner 2026-10-28:
// "as well as open-pencil somewhere"). App screens, web pages, cards and posters as .fig files in designs/ - made from
// HTML + CSS or JSX here, or by an agent (Ask an agent), exported as PNG / SVG / JSX / Tailwind / HTML, checked by
// OpenPencil's lint, opened in the OpenPencil app when it is installed. Phone testing (mobile-mcp) shows its devices.
"use strict";

const ForgeDesign = (() => {
  if (typeof ICON_PATHS === "object") Object.assign(ICON_PATHS, {
    dsNew: '<rect x="3.5" y="3.5" width="17" height="17" rx="2"/><path d="M3.5 8.5h17"/><path d="M12 12v6M9 15h6"/>',
    dsRender: '<rect x="3.5" y="5" width="17" height="14" rx="1.5"/><path d="M8 10l-2.5 2.5L8 15M16 10l2.5 2.5L16 15M13.2 9l-2.4 7"/>',
    dsAgent: '<rect x="5" y="7" width="14" height="11" rx="3"/><path d="M12 3.5V7"/><circle cx="9.5" cy="12" r="1.2"/><circle cx="14.5" cy="12" r="1.2"/><path d="M9.5 15.5h5"/>',
    dsExport: '<rect x="4" y="4" width="11" height="14" rx="1"/><path d="M13 13h7.5M17.5 10l3 3-3 3"/>',
    dsLint: '<path d="M4 6h10M4 11h7M4 16h5"/><path d="M13.5 16.5l2.5 2.5 4.5-5"/>',
    dsTree: '<rect x="3.5" y="3.5" width="6" height="4" rx="1"/><rect x="14.5" y="10" width="6" height="4" rx="1"/><rect x="14.5" y="16.5" width="6" height="4" rx="1"/><path d="M6.5 7.5v11h8M6.5 12h8"/>',
    dsApp: '<path d="M14 4h6v6"/><path d="M20 4l-8.5 8.5"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    dsReload: '<path d="M4.5 12a7.5 7.5 0 0 1 13-5.1L19.5 9"/><path d="M19.5 4.5V9H15"/><path d="M19.5 12a7.5 7.5 0 0 1-13 5.1L4.5 15"/>',
    dsPhone: '<rect x="7" y="2.5" width="10" height="19" rx="2"/><path d="M11 18.5h2"/>',
  });

  const S = { panel: null, list: [], sel: "", blobs: {}, busy: false, mobile: {} };
  const q = (s) => S.panel && S.panel.querySelector(s);
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.resolve({ ok: false }));
  const btn = (icon, name, what, fn, cls) => forgeBtn(icon, name, what, (e) => { e.stopPropagation(); fn(); }, cls);
  const sec = (title, cls) => { const d = el("div", "fuv-sec fmg-sec " + (cls || "")); d.append(el("div", "fuv-sec-title", title)); return d; };
  const field = (label, node) => { const r = el("label", "fmg-field"); r.append(el("span", "", label), node); return r; };

  function say(text, bad) { const s = q(".fds-status"); if (s) { s.textContent = text || ""; s.classList.toggle("bad", !!bad); s.title = text || ""; } return text; }

  async function picture(path, img, stamp) {
    if (!path) { img.removeAttribute("src"); return; }
    const key = path + "@" + (stamp || 0);
    if (S.blobs[key]) { img.src = S.blobs[key]; return; }
    try {
      const r = await fetch("/design/file?path=" + encodeURIComponent(path), { headers: { Authorization: "Bearer " + state.token } });
      if (!r.ok) return;
      S.blobs[key] = URL.createObjectURL(await r.blob()); img.src = S.blobs[key];
    } catch (_) { /* shown without it */ }
  }

  function build() {
    const body = document.querySelector("#forge .forge-body");
    if (!body) return null;
    if (S.panel) return S.panel;
    const p = el("section", "forge-mangapanel forge-designpanel"); p.id = "forge-designpanel"; p.hidden = true;
    S.panel = p;
    const head = el("div", "fuv-head fmg-head"); head.append(el("span", "fuv-title", "Design"));
    const fmt = el("select", "fmg-in fds-format"); fmt.title = "What Export makes";
    for (const f of ["png", "svg", "tailwind-jsx", "jsx", "html", "pptx", "webp"]) { const o = el("option", "", f); o.value = f; fmt.append(o); }
    const tb = el("div", "fuv-toolbar fmg-toolbar");
    tb.append(
      btn("dsExport", "Export", "Export the picked design in the format beside this button (into designs/exports).", () => doExport()),
      fmt,
      btn("dsLint", "Check Design", "OpenPencil's lint: contrast (WCAG), spacing, naming - the problems are listed on the right.", () => doLint()),
      btn("dsTree", "Layers", "Show the picked design's layer tree.", () => doTree()),
      btn("dsApp", "Open in OpenPencil", "Open the picked design in the OpenPencil desktop app (when it is installed).", () => run({ action: "open", name: S.sel }, "Opening")),
      btn("dsReload", "Refresh", "List the designs again.", () => refresh()));
    head.append(tb);

    const cols = el("div", "fmg-cols");
    const left = el("div", "fmg-left");
    const listSec = sec("Designs", "fds-designs"); listSec.append(el("div", "fds-list"));
    const phone = sec("Phone testing", "fds-phone"); phone.append(el("div", "fds-mobile"));
    left.append(listSec, phone);

    const mid = el("div", "fmg-mid");
    const stage = el("div", "fmg-stage fds-stage"); const img = el("img", "fds-img"); img.alt = "The picked design";
    stage.append(img, el("div", "fmg-empty fds-empty", "No design picked - make one on the right, or ask an agent."));
    mid.append(stage);

    const right = el("div", "fmg-right");
    const make = sec("Make", "fds-make");
    const name = el("input", "fmg-in fds-name"); name.placeholder = "Name, e.g. home-screen";
    const mode = el("select", "fmg-in fds-mode");
    for (const [v, t] of [["jsx", "JSX (Frame, Text, Rectangle ...)"], ["html", "HTML + CSS (imported as layers)"]]) { const o = el("option", "", t); o.value = v; mode.append(o); }
    const code = el("textarea", "fmg-in fds-code"); code.rows = 9; code.spellcheck = false;
    code.value = '<Frame name="Card" w={360} h={200} bg="#1e1f24" rounded={16} p={24} flex="col" gap={12}>\n  <Text size={28} weight="bold" color="#ffffff">LOKI</Text>\n  <Text size={16} color="#c9cdd3">Made in Forge > Design</Text>\n</Frame>';
    const css = el("textarea", "fmg-in fds-css"); css.rows = 4; css.placeholder = "CSS (for HTML)"; css.hidden = true; css.spellcheck = false;
    mode.addEventListener("change", () => { css.hidden = mode.value !== "html"; });
    make.append(field("Name", name), field("Made from", mode), field("Code", code), css,
      btn("dsRender", "Draw It", "Make the design from the code above (JSX is drawn into the design; HTML + CSS becomes a new design).", () => {
        const n = name.value.trim() || S.sel; if (!n) return say("Give it a name first.", true);
        return mode.value === "jsx" ? run({ action: "render", name: n, jsx: code.value }, "Drawing", n)
          : run({ action: "new", name: n, html: code.value, css: css.value }, "Importing", n);
      }, "fmg-small"));
    const ask = sec("Ask an agent", "fds-ask");
    const brief = el("textarea", "fmg-in fds-brief"); brief.rows = 3; brief.placeholder = "What should it look like? e.g. a dark login screen for the LOKI phone app";
    ask.append(brief, btn("dsAgent", "Ask an Agent", "A LOKI agent designs it with OpenPencil (the design playbook), in the background - the result shows up here.", () => {
      if (!brief.value.trim()) return say("Say what to design first.", true);
      const n = name.value.trim() || "";
      const text = "Design this with the design tool (OpenPencil), following my design playbook if I have one (playbook tool): " + brief.value.trim()
        + (n ? "\nSave it as designs/" + n + ".fig." : "") + "\nLook at the PNG preview, run lint, and export PNG + tailwind-jsx when done.";
      if (typeof sendToBackground === "function") { sendToBackground(text); say("An agent is on it (Home shows its progress)."); brief.value = ""; }
    }, "fmg-small"));
    const out = sec("Result", "fds-out"); out.append(el("div", "fds-result"));
    right.append(make, ask, out);
    cols.append(left, mid, right);
    p.append(head, cols, el("div", "fuv-status fds-status", "Design workspace."));
    p.addEventListener("keydown", (e) => { if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) e.stopPropagation(); }, true);
    body.append(p);
    return p;
  }

  async function refresh(pick) {
    const d = await call("/design/list");
    if (!d || !d.ok) return say((d && d.error) || "Design did not answer.", true);
    S.list = d.designs || []; S.mobile = d.mobile || {};
    if (pick) S.sel = pick;
    if (!S.list.some((x) => x.name === S.sel)) S.sel = S.list.length ? S.list[0].name : "";
    draw();
    if (!d.cli) say("OpenPencil needs Node.js on this computer (or Settings > Tool Shelf > OpenPencil).", true);
  }

  function draw() {
    const box = q(".fds-list"); if (!box) return;
    box.replaceChildren();
    if (!S.list.length) box.append(el("div", "fmg-hint", "No designs yet."));
    for (const x of S.list) {
      const b = el("button", "fds-item" + (x.name === S.sel ? " on" : "")); b.type = "button"; b.title = x.file;
      const th = el("img", "fds-thumb"); th.alt = ""; picture(x.preview, th, x.updated);
      b.append(th, el("span", "fmg-ptitle", x.name));
      b.addEventListener("click", () => { S.sel = x.name; draw(); });
      box.append(b);
    }
    const cur = S.list.find((x) => x.name === S.sel);
    const img = q(".fds-img"), empty = q(".fds-empty");
    if (img) { img.hidden = !cur; if (cur) picture(cur.preview, img, cur.updated); }
    if (empty) empty.hidden = !!cur;
    const nm = q(".fds-name"); if (nm && cur && !nm.value) nm.value = cur.name;
    const mob = q(".fds-mobile");
    if (mob) {
      mob.replaceChildren();
      const devs = S.mobile.devices || [];
      mob.append(el("div", "fmg-sub", devs.length ? devs.length + " device(s) ready - agents test with mobile-mcp:" : "No simulator, emulator or phone found. Mac: boot an iOS simulator (Xcode). PC: adb + an emulator or a phone with USB debugging."));
      for (const dv of devs) mob.append(el("span", "fmg-chip", dv.platform + " " + dv.kind + ": " + dv.name));
      mob.append(btn("dsPhone", "Test the Phone App", "An agent installs and checks LOKI's phone app (" + (S.mobile.app_id || "dev.m03.loki") + ") on a device with mobile-mcp, following the mobile-test playbook.", () => {
        if (typeof sendToBackground === "function") sendToBackground("Test LOKI's phone app (" + (S.mobile.app_id || "dev.m03.loki") + ") with the mobile tools (mobile-mcp), following my phone-test playbook if I have one (playbook tool): list devices, launch it, go through its main screens, save screenshots of the phone and report what works and what is broken.");
        say("An agent is testing the phone app (Home shows its progress).");
      }, "fmg-small"));
    }
  }

  async function run(body, label, pick) {
    if (!body.name) return say("Pick or name a design first.", true);
    if (S.busy) return say("Still working ...", true);
    S.busy = true; say(label + " ...");
    const d = await call("/design/do", body);
    if (!d.ok) { S.busy = false; return say(d.error || "That did not work.", true); }
    for (;;) {
      await new Promise((r) => setTimeout(r, 900));
      const j = await call("/design/job?id=" + d.job);
      if (j && j.status === "running") continue;
      S.busy = false;
      const res = (j && j.result) || {};
      show(res);
      say(res.ok ? label + " done." : (res.error || "It failed."), !res.ok);
      await refresh(pick || S.sel);
      return res;
    }
  }

  function show(res) {
    const box = q(".fds-result"); if (!box) return;
    box.replaceChildren();
    if (res.file) box.append(el("div", "fmg-sub", "File: " + res.file));
    const rep = res.report || res.tree || res.result;
    if (rep && rep.messages) {
      box.append(el("div", rep.messages.length ? "fmg-sub" : "fmg-ok", rep.messages.length ? rep.messages.length + " problems:" : "No problems."));
      for (const m of rep.messages.slice(0, 40)) box.append(el("div", "fmg-issue", (m.nodeName ? m.nodeName + ": " : "") + m.message));
    } else if (rep) {
      const pre = el("pre", "fds-pre"); pre.textContent = typeof rep === "string" ? rep : JSON.stringify(rep, null, 1).slice(0, 6000); box.append(pre);
    }
    if (res.error) box.append(el("div", "fmg-issue", res.error));
  }

  function doExport() { const f = q(".fds-format"); return run({ action: "export", name: S.sel, format: f ? f.value : "png", scale: 2 }, "Exporting"); }
  function doLint() { return run({ action: "lint", name: S.sel, preset: "recommended" }, "Checking"); }
  function doTree() { return run({ action: "tree", name: S.sel, depth: 3 }, "Reading the layers"); }

  function show_(on) {
    const p = build(); if (!p) return;
    p.hidden = !on;
    document.querySelector("#forge .forge-body")?.classList.toggle("ws-design", !!on);
    if (on) refresh();
  }

  return { show: show_, refresh, state: S };
})();
