// LOKI Apps (docs/APPS.md): the Apps area - the owner's mini-apps, the gallery, modes and extensions -
// and the window side of the mini-app bridge. Each app runs in a sandboxed frame (allow-scripts only:
// an opaque origin with no token, cookies, storage or network). It can only postMessage this window;
// THIS file decides which app a message comes from (by the frame it came out of, never by what the
// message says), calls the engine with LOKI's token, and asks the owner before a file is saved.
// Engine side: engine/apps.py, engine/apps_api.py. Needs app.js's api(), el() and send().
"use strict";

const Apps = { sheet: null, body: null, tab: "mine", frames: new Map(), data: null, running: null, busyDialog: false };

function appsEl(tag, cls, text) { return typeof el === "function" ? el(tag, cls, text) : Object.assign(document.createElement(tag), { className: cls || "", textContent: text || "" }); }
function appsBtn(label, onClick, cls) { const b = appsEl("button", cls || "", label); b.type = "button"; if (onClick) b.addEventListener("click", onClick); return b; }

function buildAppsSheet() {
  const sheet = appsEl("div", "sheet apps-sheet");
  sheet.id = "apps-sheet";
  sheet.hidden = true;
  const panel = appsEl("div", "sheet-panel apps-panel");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  panel.setAttribute("aria-label", "Apps");
  const nav = appsEl("nav", "apps-nav");
  nav.setAttribute("aria-label", "Apps sections");
  const title = appsEl("h2", "apps-title", "Apps");
  nav.append(title);
  for (const [id, label, what] of [["mine", "My apps", "Apps LOKI made or you installed"], ["gallery", "Gallery", "Ready-made apps, one click to install"],
    ["modes", "Modes", "Content creator, Outreach, Writer... and your own"], ["extensions", "Extensions", "Plugins anyone can write"]]) {
    const b = appsBtn(label, () => showAppsTab(id), "apps-tab");
    b.dataset.appsTab = id;
    b.title = what;
    nav.append(b);
  }
  const close = appsBtn("Close", closeApps, "quiet apps-close");
  close.setAttribute("aria-label", "Close Apps");
  nav.append(close);
  const body = appsEl("div", "apps-body");
  panel.append(nav, body);
  sheet.append(panel);
  sheet.addEventListener("click", (e) => { if (e.target === sheet) closeApps(); });
  document.body.append(sheet);
  Apps.sheet = sheet;
  Apps.body = body;
}

function openApps(tab) {
  if (!Apps.sheet) buildAppsSheet();
  Apps.sheet.hidden = false;
  showAppsTab(tab || Apps.tab || "mine");
}

function closeApps() {
  if (!Apps.sheet) return;
  stopRunningApp();
  Apps.sheet.hidden = true;
}

function stopRunningApp() {
  if (Apps.running) { Apps.running.frame.src = "about:blank"; Apps.frames.clear(); Apps.running = null; }
}

async function showAppsTab(tab) {
  Apps.tab = tab;
  stopRunningApp();
  for (const b of Apps.sheet.querySelectorAll("[data-apps-tab]")) b.setAttribute("aria-selected", String(b.dataset.appsTab === tab));
  Apps.body.replaceChildren(appsEl("p", "note", "Loading…"));
  if (tab === "modes") return renderModesTab();
  if (tab === "extensions") return renderExtensionsTab();
  const data = await api("/apps/list").catch(() => null);
  Apps.data = data && data.ok ? data : { apps: [], templates: [] };
  if (tab === "gallery") renderGallery(); else renderMine();
}

function appTile(app, onOpen, extra) {
  const tile = appsEl("div", "app-tile");
  const open = appsBtn("", onOpen, "app-tile-open");
  open.setAttribute("aria-label", "Open " + app.title);
  const icon = appsEl("span", "app-icon", app.icon || (app.title || "?").slice(0, 1).toUpperCase());
  icon.setAttribute("aria-hidden", "true");
  const words = appsEl("span", "app-words");
  words.append(appsEl("b", "", app.title), appsEl("span", "", app.description || ""));
  open.append(icon, words);
  tile.append(open);
  if (extra) tile.append(extra);
  return tile;
}

function renderMine() {
  const box = Apps.body;
  box.replaceChildren();
  const head = appsEl("header", "apps-head");
  head.append(appsEl("h3", "", "My apps"), appsEl("p", "note", "Small apps that run inside LOKI, sealed off from your files and keys. Ask LOKI for one (“make me a habit tracker”) or install one from the Gallery. Their data is kept by LOKI and synced to your other machines."));
  const ask = appsEl("form", "apps-make");
  const input = appsEl("input", "apps-make-input");
  input.placeholder = "Describe an app: a tracker for my plants' watering…";
  input.setAttribute("aria-label", "Describe an app for LOKI to build");
  ask.append(input, appsBtn("Build it", null, "send small"));
  ask.lastChild.type = "submit";
  ask.addEventListener("submit", (e) => { e.preventDefault(); const what = input.value.trim(); if (what) askLokiToBuild(what); });
  head.append(ask);
  box.append(head);
  const apps = Apps.data.apps || [];
  if (!apps.length) {
    const empty = appsEl("div", "apps-empty");
    empty.append(appsEl("p", "", "No apps yet."), appsBtn("Browse the gallery", () => showAppsTab("gallery"), "send small"));
    box.append(empty);
    return;
  }
  const grid = appsEl("div", "apps-grid");
  for (const app of apps) grid.append(appTile(app, () => runApp(app)));
  box.append(grid);
}

function renderGallery() {
  const box = Apps.body;
  box.replaceChildren();
  const head = appsEl("header", "apps-head");
  head.append(appsEl("h3", "", "Gallery"), appsEl("p", "note", "Ready-made apps. Install one and it is yours: LOKI can change it for you (“add a savings goal to my budget app”)."));
  box.append(head);
  const installed = new Set((Apps.data.apps || []).map((a) => a.template).filter(Boolean));
  const grid = appsEl("div", "apps-grid");
  for (const t of Apps.data.templates || []) {
    const actions = appsEl("div", "app-tile-actions");
    actions.append(appsBtn("Try", () => runApp(t, true), "quiet small"),
      appsBtn(installed.has(t.name) ? "Install again" : "Install", async (ev) => {
        ev.target.disabled = true;
        const out = await api("/apps/install", { template: t.name });
        if (!out.ok) { ev.target.disabled = false; ev.target.textContent = out.error || "Failed"; return; }
        Apps.data = await api("/apps/list");
        runApp(out.app);
      }, "send small"));
    if (t.category) actions.prepend(appsEl("span", "app-cat", t.category));
    grid.append(appTile(t, () => runApp(t, true), actions));
  }
  box.append(grid);
}

function askLokiToBuild(what, app) {
  closeApps();
  const prompt = app
    ? "Change my LOKI app “" + app.title + "” (apps/" + app.name + "): " + what + ". Read app_builder_guide and make_app(action='read', name='" + app.name + "') first, then save it with make_app."
    : "Build me a LOKI app: " + what + ". Read app_builder_guide first, then make it with make_app.";
  if (typeof send === "function") send(prompt, { direct: true });
}

function runApp(app, preview) {
  const box = Apps.body;
  box.replaceChildren();
  const bar = appsEl("div", "app-run-bar");
  bar.append(appsBtn("‹ Apps", () => showAppsTab(preview ? "gallery" : "mine"), "quiet small"));
  const name = appsEl("b", "app-run-title", (app.icon ? app.icon + "  " : "") + app.title + (preview ? " (preview - nothing is kept)" : ""));
  bar.append(name);
  if (!preview && app.kind === "w") {
    const change = appsEl("form", "app-change");
    const inp = appsEl("input", "apps-make-input");
    inp.placeholder = (app.starters && app.starters[0]) ? "e.g. " + app.starters[0] : "Ask LOKI to change this app…";
    inp.setAttribute("aria-label", "Ask LOKI to change this app");
    change.append(inp, appsBtn("Change it", null, "small"));
    change.lastChild.type = "submit";
    change.addEventListener("submit", (e) => { e.preventDefault(); if (inp.value.trim()) askLokiToBuild(inp.value.trim(), app); });
    bar.append(change);
    bar.append(appsBtn("Remove", async () => {
      if (!(await appsConfirm("Remove " + app.title + "?", "The app goes to LOKI's trash (its data is kept). It is removed on your other machines too.", "Remove"))) return;
      const out = await api("/apps/remove", { name: app.name });
      if (out.ok) showAppsTab("mine");
    }, "quiet small danger-text"));
  }
  const full = appsBtn("Full window", () => { if (stage.requestFullscreen) stage.requestFullscreen(); }, "quiet small");
  bar.append(full);
  const stage = appsEl("div", "app-stage");
  const frame = document.createElement("iframe");
  frame.className = "app-frame";
  frame.setAttribute("sandbox", "allow-scripts");
  frame.setAttribute("title", app.title);
  frame.setAttribute("referrerpolicy", "no-referrer");
  stage.append(frame);
  box.append(bar, stage);
  Apps.running = { frame, app, key: app.key, preview: !!preview };
  Apps.frames.clear();
  if (frame.contentWindow) Apps.frames.set(frame.contentWindow, { key: app.key, app });   // the frame's window stays the same object across its navigation
  frame.addEventListener("load", () => {
    Apps.frames.clear();
    if (frame.contentWindow) Apps.frames.set(frame.contentWindow, { key: app.key, app });
    sayHello(frame.contentWindow, app);
  });
  frame.src = app.url;
}

function sayHello(win, app) {
  if (win) win.postMessage({ lokiApp: 1, op: "hello", app: { name: app.name, title: app.title }, theme: document.documentElement.dataset.theme || "dark" }, "*");
}

// ------------------------------------------------------------------ the bridge (window side)
window.addEventListener("message", async (event) => {
  const msg = event.data;
  if (!msg || msg.lokiApp !== 1 || typeof msg.op !== "string") return;
  const who = Apps.frames.get(event.source);
  if (!who || !Apps.running) return;   // only the app this window is showing, identified by its frame
  const reply = (ok, result, error) => { try { event.source.postMessage({ lokiApp: 1, id: msg.id, ok, result, error }, "*"); } catch (_) { /* gone */ } };
  if (msg.op === "hello") { sayHello(event.source, who.app); return; }
  const args = msg.args && typeof msg.args === "object" ? msg.args : {};
  try {
    if (msg.op.startsWith("store.")) {
      const op = msg.op.slice(6);
      if (!["get", "set", "remove", "keys", "all"].includes(op)) return reply(false, null, "unknown store call");
      const out = await api("/apps/storage", { app: who.key, op, key: args.key, value: args.value });
      if (!out.ok) return reply(false, null, out.error || "storage failed");
      return reply(true, op === "get" ? out.value : op === "keys" ? out.keys : op === "all" ? out.values : true);
    }
    if (msg.op === "ask") {
      const out = await api("/apps/ask", { app: who.key, prompt: String(args.prompt || "").slice(0, 8000), data: args.data });
      return out.ok ? reply(true, out.answer) : reply(false, null, out.error || "LOKI could not answer");
    }
    if (msg.op === "files.save") return reply(true, await approveSave(who, args));
    if (msg.op === "files.open") return reply(true, await pickFile(who, args));
    reply(false, null, "unknown call " + msg.op);
  } catch (e) {
    reply(false, null, String(e && e.message || e));
  }
});

// LOKI's own dialogs, drawn in this window (an app cannot draw over them or click them).
function appsDialog(title, build) {
  return new Promise((resolve) => {
    const wrap = appsEl("div", "sheet modal apps-dialog");
    const panel = appsEl("div", "sheet-panel apps-dialog-panel");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.append(appsEl("h3", "", title));
    const done = (v) => { wrap.remove(); resolve(v); };
    build(panel, done);
    wrap.append(panel);
    wrap.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); done(null); } });
    document.body.append(wrap);
    const first = panel.querySelector("button.send, button");
    if (first) first.focus();
  });
}

function appsConfirm(title, text, okLabel) {
  return appsDialog(title, (panel, done) => {
    panel.append(appsEl("p", "note", text));
    const row = appsEl("div", "apps-dialog-actions");
    row.append(appsBtn("Cancel", () => done(false), "quiet"), appsBtn(okLabel || "OK", () => done(true), "send"));
    panel.append(row);
  }).then((v) => !!v);
}

async function approveSave(who, args) {
  if (Apps.busyDialog) throw new Error("another request is waiting for you");
  const content = String(args.content == null ? "" : args.content);
  const name = String(args.name || "file.txt").replace(/[\\/]/g, "_").slice(0, 120);
  Apps.busyDialog = true;
  try {
    const kb = Math.max(1, Math.round(new Blob([content]).size / 1024));
    const ok = await appsConfirm(who.app.title + " wants to save a file",
      "“" + name + "” (" + kb + " KB) into App files/" + who.app.name + "/ in your workspace. Nothing else is touched.", "Save");
    if (!ok) return null;
    const out = await api("/apps/files/save", { app: who.key, name, content });
    if (!out.ok) throw new Error(out.error || "not saved");
    return { name: out.name, path: out.path };
  } finally { Apps.busyDialog = false; }
}

async function pickFile(who, args) {
  if (Apps.busyDialog) throw new Error("another request is waiting for you");
  Apps.busyDialog = true;
  try {
    const saved = await api("/apps/files/list", { app: who.key }).catch(() => ({}));
    return await appsDialog(who.app.title + " wants to open a file", (panel, done) => {
      panel.append(appsEl("p", "note", "Pick a file for this app to read. It sees only the file you choose."));
      const input = document.createElement("input");
      input.type = "file";
      if (args.accept) input.accept = String(args.accept).slice(0, 200);
      input.hidden = true;
      input.addEventListener("change", () => {
        const f = input.files && input.files[0];
        if (!f) return;
        if (f.size > 5000000) { done(null); return; }
        const reader = new FileReader();
        reader.onload = () => done({ name: f.name, text: String(reader.result || "") });
        reader.onerror = () => done(null);
        reader.readAsText(f);
      });
      panel.append(input, appsBtn("Choose from this computer…", () => input.click(), "send"));
      const files = (saved && saved.files) || [];
      if (files.length) {
        panel.append(appsEl("p", "note", "Or one this app saved before:"));
        const list = appsEl("div", "apps-file-list");
        for (const f of files.slice(0, 20)) {
          list.append(appsBtn(f.name, async () => {
            const out = await api("/apps/files/read", { app: who.key, name: f.name });
            done(out.ok && out.text !== undefined ? { name: out.name, text: out.text } : null);
          }, "quiet small"));
        }
        panel.append(list);
      }
      const row = appsEl("div", "apps-dialog-actions");
      row.append(appsBtn("Cancel", () => done(null), "quiet"));
      panel.append(row);
    });
  } finally { Apps.busyDialog = false; }
}

// ------------------------------------------------------------------ Modes tab
async function renderModesTab() {
  const box = Apps.body;
  const data = await api("/personas").catch(() => null);
  box.replaceChildren();
  const head = appsEl("header", "apps-head");
  head.append(appsEl("h3", "", "Modes"), appsEl("p", "note", "A mode turns LOKI into a Content creator, Outreach, a Writer... - its own instructions, tools, skills and starter prompts. Pick one in the message box. Make your own, or share one as a .lokimode file. A mode never changes the safety rules."));
  const tools = appsEl("div", "apps-row");
  tools.append(appsBtn("New mode", () => editMode(null), "send small"));
  const file = document.createElement("input");
  file.type = "file";
  file.accept = ".lokimode,.json";
  file.hidden = true;
  file.addEventListener("change", () => {
    const f = file.files && file.files[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = async () => {
      const out = await api("/personas/import", { text: String(r.result || "") });
      if (!out.ok) await appsConfirm("Not imported", out.error || "That file is not a LOKI mode.", "OK");
      renderModesTab();
    };
    r.readAsText(f);
  });
  tools.append(file, appsBtn("Import a mode file…", () => file.click(), "small"));
  head.append(tools);
  box.append(head);
  if (!data || !data.ok) { box.append(appsEl("p", "note", "Modes are not available.")); return; }
  const grid = appsEl("div", "apps-grid");
  for (const m of data.modes) {
    const actions = appsEl("div", "app-tile-actions");
    const on = data.active === m.id;
    actions.append(appsBtn(on ? "In use" : "Use", async () => { await setMode(on ? "" : m.id); renderModesTab(); }, on ? "small" : "send small"));
    actions.append(appsBtn("Export", () => exportMode(m), "quiet small"));
    actions.append(appsBtn(m.builtin ? "Copy" : "Edit", () => editMode(m), "quiet small"));
    if (!m.builtin) actions.append(appsBtn("Delete", async () => { if (await appsConfirm("Delete the mode " + m.name + "?", "Its file is removed from this computer.", "Delete")) { await api("/personas/delete", { id: m.id }); renderModesTab(); } }, "quiet small danger-text"));
    const tile = appTile({ title: m.name + (on ? " ✓" : ""), icon: m.icon, description: m.description }, () => editMode(m), actions);
    if (on) tile.classList.add("on");
    grid.append(tile);
  }
  box.append(grid);
}

async function setMode(id) {
  const out = await api("/personas/active", { id });
  if (window.LokiModes) LokiModes.refresh();
  return out;
}

async function exportMode(m) {
  const out = await api("/personas/export", { id: m.id });
  if (!out.ok) return;
  await appsDialog("Share the mode " + m.name, (panel, done) => {
    panel.append(appsEl("p", "note", out.path ? "Saved as " + out.path + " - send that file to anyone with LOKI; they import it in Apps > Modes." : "Copy this and save it as " + out.filename + "."));
    const area = appsEl("textarea", "apps-code");
    area.value = out.text;
    area.readOnly = true;
    area.rows = 10;
    panel.append(area);
    const row = appsEl("div", "apps-dialog-actions");
    row.append(appsBtn("Copy", () => { area.select(); try { navigator.clipboard.writeText(out.text); } catch (_) { document.execCommand("copy"); } }, "quiet"), appsBtn("Done", () => done(true), "send"));
    panel.append(row);
  });
}

async function editMode(m) {
  const v = await appsDialog(m ? (m.builtin ? "Copy of " + m.name : "Edit " + m.name) : "New mode", (panel, done) => {
    const fields = {};
    const add = (key, label, value, kind) => {
      const lab = appsEl("label", "apps-field");
      lab.append(appsEl("span", "", label));
      const c = kind === "area" ? appsEl("textarea", "") : appsEl("input", "");
      if (kind === "area") c.rows = 5;
      if (kind === "check") { c.type = "checkbox"; c.checked = !!value; lab.classList.add("check"); } else c.value = value || "";
      fields[key] = c;
      lab.append(c);
      panel.append(lab);
    };
    add("name", "Name", m ? m.name + (m.builtin ? " (mine)" : "") : "");
    add("icon", "Emoji", m ? m.icon : "✨");
    add("description", "One line about it", m ? m.description : "");
    add("instructions", "How LOKI behaves in this mode", m ? m.instructions : "", "area");
    add("tools", "Tools to put first (comma separated, e.g. web_search, write_file)", m ? (m.tools || []).join(", ") : "");
    add("only_tools", "Offer only these tools", m ? m.only_tools : false, "check");
    add("skills", "Skill packs (comma separated)", m ? (m.skills || []).join(", ") : "");
    add("starters", "Starter prompts (one per line)", m ? (m.starters || []).join("\n") : "", "area");
    const err = appsEl("p", "note error");
    const row = appsEl("div", "apps-dialog-actions");
    row.append(appsBtn("Cancel", () => done(null), "quiet"), appsBtn("Save", async () => {
      const list = (s) => String(s || "").split(",").map((x) => x.trim()).filter(Boolean);
      const mode = { name: fields.name.value, icon: fields.icon.value, description: fields.description.value, instructions: fields.instructions.value,
        tools: list(fields.tools.value), only_tools: fields.only_tools.checked, skills: list(fields.skills.value),
        starters: fields.starters.value.split("\n").map((x) => x.trim()).filter(Boolean) };
      if (m && !m.builtin) mode.id = m.id;
      const out = await api("/personas/save", { mode });
      if (!out.ok) { err.textContent = out.error || "Not saved"; return; }
      done(out.mode);
    }, "send"));
    panel.append(err, row);
  });
  if (v) renderModesTab();
}

// ------------------------------------------------------------------ Extensions tab
async function renderExtensionsTab() {
  const box = Apps.body;
  const data = await api("/extensions").catch(() => null);
  box.replaceChildren();
  const head = appsEl("header", "apps-head");
  head.append(appsEl("h3", "", "Extensions"), appsEl("p", "note", "Add tools, an app or a panel that someone wrote (the format is in docs/APPS.md). LOKI scans it first and shows you what it would get; its tools run sealed off (no keys, no settings) and ask you before each use unless you trust it."));
  const form = appsEl("form", "apps-make");
  const src = appsEl("input", "apps-make-input");
  src.placeholder = "A folder on this computer, or https://github.com/someone/loki-extension";
  src.setAttribute("aria-label", "Extension folder or git URL");
  form.append(src, appsBtn("Scan", null, "send small"));
  form.lastChild.type = "submit";
  const report = appsEl("div", "ext-report");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!src.value.trim()) return;
    report.replaceChildren(appsEl("p", "note", "Fetching and scanning…"));
    const out = await api("/extensions/scan", { source: src.value.trim() });
    showScan(report, out);
  });
  head.append(form, report);
  box.append(head);
  const items = (data && data.extensions) || [];
  if (!items.length) { box.append(appsEl("p", "note", "No extensions installed.")); return; }
  const list = appsEl("div", "ext-list");
  for (const x of items) {
    const card = appsEl("div", "ext-card");
    const top = appsEl("div", "ext-top");
    top.append(appsEl("b", "", x.name + (x.version ? " " + x.version : "")), appsEl("span", "note", x.description));
    card.append(top);
    if (x.tools.length) card.append(appsEl("p", "note", "Tools: " + x.tools.join(", ")));
    const failed = (x.checks || []).filter((c) => !c.ok);
    if (failed.length) card.append(appsEl("p", "note error", "Tests failed: " + failed.map((c) => c.tool + " (" + c.detail + ")").join("; ")));
    const row = appsEl("div", "apps-row");
    row.append(appsBtn(x.enabled ? "Turn off" : "Turn on", async () => { const o = await api("/extensions/toggle", { id: x.id, on: !x.enabled }); if (!o.ok) await appsConfirm("Not turned on", o.error || "", "OK"); renderExtensionsTab(); }, x.enabled ? "small" : "send small"));
    row.append(appsBtn(x.trusted ? "Trusted - ask again" : "Trust (don't ask each time)", async () => {
      if (!x.trusted && !(await appsConfirm("Trust " + x.name + "?", "Its tools will run without asking you first (still sealed off: no keys, no settings, a time limit).", "Trust"))) return;
      await api("/extensions/trust", { id: x.id, on: !x.trusted }); renderExtensionsTab();
    }, "quiet small"));
    if (x.enabled && x.app) row.append(appsBtn("Open app", () => runApp({ key: "x:" + x.id, name: x.id, kind: "x", title: x.name, icon: "🧩", url: x.app_url }), "quiet small"));
    if (x.enabled && x.panel) row.append(appsBtn("Open panel", () => runApp({ key: "p:" + x.id, name: x.id, kind: "p", title: x.name + " panel", icon: "🧩", url: x.panel_url }), "quiet small"));
    row.append(appsBtn("Remove", async () => { if (await appsConfirm("Remove " + x.name + "?", "It is moved to LOKI's trash and its tools go away.", "Remove")) { await api("/extensions/remove", { id: x.id }); renderExtensionsTab(); } }, "quiet small danger-text"));
    card.append(row);
    list.append(card);
  }
  box.append(list);
}

function showScan(box, out) {
  box.replaceChildren();
  if (!out || !out.ok) { box.append(appsEl("p", "note error", (out && out.error) || "Could not scan it.")); return; }
  const r = out.report;
  const card = appsEl("div", "ext-card scan-" + r.verdict);
  card.append(appsEl("b", "", (r.name || "?") + (r.version ? " " + r.version : "") + " - " + ({ ok: "looks safe", review: "look before you install", blocked: "blocked" }[r.verdict] || r.verdict)));
  if (r.description) card.append(appsEl("p", "note", r.description));
  const what = [];
  if (r.tools.length) what.push(r.tools.length + " tool(s): " + r.tools.map((t) => t.name + (t.network ? " (internet)" : "")).join(", "));
  if (r.app) what.push("an app");
  if (r.panel) what.push("a panel");
  if (r.mode) what.push("a mode: " + r.mode);
  card.append(appsEl("p", "note", "It brings " + (what.join("; ") || "nothing LOKI can use") + ". " + r.files + " files."));
  for (const p of r.problems) card.append(appsEl("p", "note error", "✖ " + p));
  for (const n of r.notes) card.append(appsEl("p", "note warn", "⚠ " + n));
  const row = appsEl("div", "apps-row");
  const install = appsBtn("Install", async () => {
    install.disabled = true;
    const res = await api("/extensions/install", { token: out.token });
    if (!res.ok) { box.append(appsEl("p", "note error", res.error || "Not installed")); install.disabled = false; return; }
    renderExtensionsTab();
  }, "send small");
  install.disabled = r.verdict === "blocked";
  row.append(install, appsBtn("Cancel", () => box.replaceChildren(), "quiet small"));
  card.append(row);
  box.append(card);
}

window.LokiApps = { open: openApps, close: closeApps, setMode };

document.addEventListener("DOMContentLoaded", () => {
  const button = document.getElementById("open-apps");
  if (button) button.addEventListener("click", () => openApps());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && Apps.sheet && !Apps.sheet.hidden && !document.querySelector(".apps-dialog")) closeApps();
  });
});
