// Settings > Automations (session 29): LOKI does things by itself. Triggers -> conditions -> steps, drafted from
// one sentence ("every morning at 8 send me the weather and my calendar on Telegram"), shown as a readable card
// the owner approves; a list with on/off, Run now, history with logs, a simple step editor and templates.
// Engine: engine/automations.py (GET /automations, POST /automations/*). Uses api(), el() from app.js and the
// icon pattern of icons.js (it adds its own icons to ICON_PATHS / TAB_ICONS before the page iconizes). Plain DOM (CSP).
"use strict";

if (typeof ICON_PATHS !== "undefined") {
  ICON_PATHS.bolt = '<path d="M13 2.5L5 13.5h6l-1 8 8-11h-6z"/>';
  ICON_PATHS.history = '<path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.5"/><path d="M4 4v4.5h4.5"/><path d="M12 7.5V12l3 2"/>';
  ICON_PATHS.trash = '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/><path d="M10 11v5M14 11v5"/>';
  ICON_PATHS.text = '<path d="M5 6.5h14M5 11h14M5 15.5h9"/><path d="M17 15v5M14.5 17.5h5"/>';
  ICON_PATHS.up = '<path d="M12 18V6M6.5 11.5L12 6l5.5 5.5"/>';
  ICON_PATHS.down = '<path d="M12 6v12M6.5 12.5L12 18l5.5-5.5"/>';
}
if (typeof TAB_ICONS !== "undefined") {
  TAB_ICONS.automations = ["bolt", "Automations: LOKI does things by itself - on a schedule, when a file arrives, a new email, before a meeting, a webhook, a Telegram word."];
}

const autoUi = { data: null, open: "", editing: null, draft: null, draftCard: null, timer: 0, busy: false };

const TRIGGER_TYPES = { schedule: "On a schedule", folder: "A file appears in a folder", email: "A new email", calendar: "Before a calendar event",
  webhook: "A webhook is called", telegram: "A Telegram keyword", job: "A LOKI job ends", machine: "A machine comes online", manual: "Only by hand" };
const STEP_TYPES = { task: "LOKI does a task", tool: "Use a tool", image: "Make a picture", telegram: "Send me a Telegram message",
  file: "Write a file", notify: "Show a notification", http: "HTTP request (asks)", if: "Ask LOKI yes/no", wait: "Wait", sort_file: "Sort the file (asks)" };
const TRIGGER_FIELDS = {
  schedule: [["when", "text", "When (every morning at 8 · every weekday at 9am · every 2h · 0 9 * * 1-5)"], ["catch_up", "select", "If LOKI was off at that time", ["once", "skip", "all"]]],
  folder: [["path", "text", "Folder"], ["pattern", "text", "Files (*.pdf, *.png · * = any)"], ["events", "select", "When a file", ["created", "modified", "created,modified"]], ["copy", "bool", "Copy it into the workspace for LOKI"]],
  email: [["query", "text", "Filter (from:bob@example.com · unread · a word)"], ["folder", "text", "Folder"], ["every_s", "number", "Check every (seconds)"]],
  calendar: [["minutes_before", "number", "Minutes before"], ["match", "text", "Only events titled like (optional)"]],
  webhook: [],
  telegram: [["keyword", "text", "Keyword (the first word of your message)"]],
  job: [["status", "select", "When a job", ["failed", "done", "any"]], ["match", "text", "Title contains (optional)"]],
  machine: [["machine", "text", "Machine (blank = any linked machine)"]],
  manual: [],
};
const STEP_FIELDS = {
  task: [["prompt", "area", "What LOKI should do ({{trigger.name}}, {{last}}, {{date}} fill in)"], ["wait", "bool", "Wait for it to finish (the next steps get its answer as {{last}})"], ["timeout_min", "number", "Time limit (minutes)"]],
  tool: [["tool", "text", "Tool (read_web, web_search, email, calendar, github, notes ...)"], ["args", "json", "Arguments (JSON)"]],
  image: [["prompt", "area", "A picture of"]],
  telegram: [["text", "area", "Message ({{last}} = the previous step's answer)"]],
  file: [["path", "text", "File in the workspace (notes/log.md)"], ["mode", "select", "", ["append", "write"]], ["text", "area", "Text"]],
  notify: [["title", "text", "Title"], ["text", "area", "Text"]],
  http: [["method", "select", "", ["GET", "POST", "PUT", "PATCH", "DELETE"]], ["url", "text", "URL"], ["body", "area", "Body"]],
  if: [["question", "text", "Yes/no question for LOKI"], ["input", "area", "What it looks at"], ["then", "json", "If yes: steps (JSON list)"], ["else", "json", "If no: steps (JSON list)"]],
  wait: [["minutes", "number", "Minutes"]],
  sort_file: [["into", "text", "Into the subfolder (blank = by kind: Images, Documents, ...)"]],
};
const RUN_TEXT = { queued: "Queued", running: "Running", waiting: "Waiting", retry: "Will retry", approval: "Needs your OK",
  done: "Done", failed: "Failed", cancelled: "Cancelled", skipped: "Skipped" };

function autoAgo(t) {
  if (!t) return "";
  const s = Math.max(0, Math.round(Date.now() / 1000 - t));
  return s < 60 ? "just now" : s < 3600 ? Math.round(s / 60) + " min ago" : s < 86400 ? Math.round(s / 3600) + " h ago" : Math.round(s / 86400) + " d ago";
}

function autoBtn(cls, label, icon, what, onClick) {
  const b = el("button", cls, label);
  b.type = "button";
  if (icon) { b.dataset.icon = icon; b.dataset.tipName = label; b.dataset.tipWhat = what || ""; }
  b.addEventListener("click", onClick);
  return b;
}

function autoMachine(m) {
  return ({ pc: "the PC", mac: "the Mac", any: "every machine" })[m] || m || "this computer";
}

async function loadAutomations() {
  const box = document.getElementById("automations-panel");
  if (!box) return;
  const data = await api("/automations").catch(() => null);
  autoUi.data = data;
  if (!autoUi.timer) autoUi.timer = setInterval(autoRefresh, 5000);
  renderAutomations(box);
}

function autoRefresh() {
  const panel = document.querySelector('[data-panel="automations"]');
  if (!panel || panel.hidden || document.hidden) { clearInterval(autoUi.timer); autoUi.timer = 0; return; }
  if (autoUi.editing || autoUi.busy || (document.activeElement && panel.contains(document.activeElement) && /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName))) return;
  loadAutomations();
}

function renderAutomations(box) {
  const data = autoUi.data;
  box.replaceChildren();
  if (!data || !data.ok) {
    box.append(el("p", "note", (data && data.error) || "Automations are not available in this engine (restart LOKI after the update)."));
    return;
  }
  // the kill switch and where things run
  const head = el("div", "auto-head");
  const me = data.machine || {};
  head.append(el("span", "note", "This computer: " + (me.name || "?") + " (" + (me.kind === "mac" ? "Mac" : "PC") + "). New automations run on "
    + autoMachine(data.default_machine) + ", so your machines never both fire one." + (data.active ? " " + data.active + " running now." : "")));
  const stop = autoBtn("mini" + (data.stopped ? " danger" : ""), data.stopped ? "Turn automations back on" : "Stop all", data.stopped ? "play" : "stop",
    data.stopped ? "Automations are stopped: nothing fires until you turn them back on." : "Kill switch: nothing fires, running ones are cancelled with their jobs.",
    async () => { await api("/automations/stop", { stopped: !data.stopped }); loadAutomations(); });
  head.append(stop);
  box.append(head);
  if (data.stopped) box.append(el("p", "auto-stopped", "Automations are STOPPED. Nothing fires until you turn them back on."));

  // describe it in a sentence
  const make = el("div", "auto-make");
  const ta = el("textarea", "auto-say");
  ta.rows = 2;
  ta.placeholder = "Say what LOKI should do by itself - e.g. \"every morning at 8 send me the weather and my calendar on Telegram\" or \"when a PDF lands in Downloads, summarize it into notes\"";
  ta.setAttribute("aria-label", "Describe an automation");
  const go = autoBtn("send small", "Draft it", "bolt", "LOKI turns your sentence into an automation card; nothing runs until you turn it on.", async () => {
    if (!ta.value.trim()) { ta.focus(); return; }
    go.disabled = true;
    const r = await api("/automations/draft", { text: ta.value }).catch(() => null);
    go.disabled = false;
    if (!r || !r.ok) { showAutoError(make, (r && r.error) || "Could not draft it."); return; }
    autoUi.draft = r.automation; autoUi.draftCard = r.card || null; renderAutomations(box);
  });
  make.append(ta, go);
  box.append(make);
  if (autoUi.draft) box.append(draftCard(autoUi.draft, box));
  if (autoUi.editing) box.append(editor(autoUi.editing, box));

  // runs waiting for the owner's OK
  for (const w of data.waiting || []) {
    const row = el("div", "auto-wait");
    row.append(el("b", "", w.name), el("span", "", " waits for your OK: " + w.approval));
    row.append(autoBtn("mini", "Approve", "check", "Let this step run this time.", async () => { await api("/automations/run/approve", { run: w.id }); loadAutomations(); }),
      autoBtn("mini", "Deny", "close", "Stop this run.", async () => { await api("/automations/run/deny", { run: w.id }); loadAutomations(); }));
    box.append(row);
  }
  const notices = (data.notices || []).filter((n) => n.kind === "failed" || n.kind === "missed").slice(0, 4);
  for (const n of notices) box.append(el("p", "note auto-notice " + n.kind, autoAgo(n.t) + " · " + n.text));

  // the list
  const list = el("div", "rows auto-list");
  const autos = data.automations || [];
  if (!autos.length) list.append(el("p", "note", "No automations yet. Describe one above or start from a template below."));
  for (const a of autos) list.append(autoRow(a, box));
  box.append(el("h4", "th-sub", "Your automations"), list);

  // templates
  const gallery = el("div", "auto-templates");
  for (const t of data.templates || []) {
    const c = el("div", "auto-tpl");
    c.append(el("b", "", t.name), el("small", "", t.about));
    if ((t.needs || []).length) c.append(el("span", "badge subtle", "needs " + t.needs.join(", ")));
    c.append(autoBtn("mini", "Use", "plus", "Start from this template: you see the card and change it before anything runs.", async () => {
      const r = await api("/automations/template", { template: t.id }).catch(() => null);
      if (r && r.ok) { autoUi.draft = r.automation; autoUi.draftCard = r.card || null; renderAutomations(box); box.scrollTop = 0; }
    }));
    gallery.append(c);
  }
  box.append(el("h4", "th-sub", "Templates"), gallery);
}

function showAutoError(where, text) {
  const old = where.querySelector(".auto-error");
  if (old) old.remove();
  where.append(el("p", "auto-error", text));
}

function cardBody(card) {
  const body = el("div", "auto-card-body");
  const sect = (title, lines) => {
    if (!lines || !lines.length) return;
    const s = el("div", "auto-sect");
    s.append(el("span", "auto-sect-title", title));
    const ul = el("ul");
    for (const line of lines) {
      const li = el("li", "", line.trim());
      li.style.marginLeft = (line.length - line.trimStart().length) * 6 + "px";
      ul.append(li);
    }
    s.append(ul);
    body.append(s);
  };
  sect("When", card.when);
  sect("Only if", card.only_if);
  sect("Then", card.then);
  sect("Runs on", [card.runs_on]);
  if ((card.asks || []).length) sect("Asks you first", card.asks);
  return body;
}

function draftCard(auto, box) {
  const wrap = el("div", "auto-card draft");
  const name = el("input", "auto-name");
  name.value = auto.name || "";
  name.setAttribute("aria-label", "Name");
  name.addEventListener("input", () => { auto.name = name.value; });
  wrap.append(el("span", "badge", "Draft - nothing runs yet"), name);
  const cardData = autoUi.draftCard;
  wrap.append(cardBody(cardData || localCard(auto)));
  const asks = (cardData || localCard(auto)).asks || [];
  let pre = null;
  if (asks.length) {
    const lab = el("label", "check auto-pre");
    pre = el("input");
    pre.type = "checkbox";
    lab.append(pre, document.createTextNode(" Pre-approve exactly these steps (they will not ask each time; any edit asks again)"));
    wrap.append(lab);
  }
  const machine = el("select", "auto-machine");
  for (const m of ["pc", "mac", "any", (autoUi.data.machine || {}).name].filter((v, i, a) => v && a.indexOf(v) === i)) {
    const o = el("option", "", "Runs on " + autoMachine(m)); o.value = m; machine.append(o);
  }
  machine.value = auto.machine || "pc";
  machine.addEventListener("change", () => { auto.machine = machine.value; });
  const row = el("div", "auto-actions");
  const save = async (enabled) => {
    auto.enabled = enabled;
    const r = await api("/automations/save", { automation: auto, approve: !!(pre && pre.checked) }).catch(() => null);
    if (!r || !r.ok) { showAutoError(wrap, (r && r.error) || "Could not save it."); return; }
    autoUi.draft = null; loadAutomations();
  };
  row.append(machine,
    autoBtn("send small", "Turn it on", "check", "Save it and let it run on its trigger.", () => save(true)),
    autoBtn("mini", "Save it off", "", "", () => save(false)),
    autoBtn("mini", "Edit steps", "pen", "Change the trigger, conditions and steps first.", () => { autoUi.editing = JSON.parse(JSON.stringify(auto)); autoUi.draft = null; renderAutomations(box); }),
    autoBtn("mini", "Discard", "close", "Throw this draft away.", () => { autoUi.draft = null; renderAutomations(box); }));
  wrap.append(row);
  return wrap;
}

function localCard(auto) {
  // a saved automation carries its card from the engine; a draft gets the one the draft call returned
  if (auto.card) return auto.card;
  const lines = (steps, d) => (steps || []).flatMap((s) => [" ".repeat(d * 2) + (STEP_TYPES[s.type] || s.type) + ": " + (s.prompt || s.text || s.tool || s.url || s.question || s.path || s.minutes || "")]
    .concat(s.type === "if" ? lines(s.then, d + 1).concat(s.else && s.else.length ? [" ".repeat(d * 2 + 2) + "otherwise:"].concat(lines(s.else, d + 2)) : []) : []));
  const asks = [];
  const walk = (steps) => (steps || []).forEach((s) => {
    if (s.type === "http") asks.push("an HTTP request to " + (s.url || ""));
    if (s.type === "sort_file") asks.push("moves the file that arrived into a subfolder");
    if (s.type === "tool" && /^(send|create|create_issue|comment|close_issue|create_pr|write|append)$/.test(String((s.args || {}).action || ""))) asks.push(s.tool + " " + s.args.action + " writes to your account");
    if (s.type === "if") { walk(s.then); walk(s.else); }
  });
  walk(auto.steps);
  return { when: (auto.triggers || []).map((t) => TRIGGER_TYPES[t.type] + (t.when ? ": " + t.when : t.path ? ": " + t.path : t.query ? ": " + t.query : t.keyword ? ": " + t.keyword : "")),
    only_if: (auto.conditions || []).map((c) => c.type === "time" ? "between " + c.after + " and " + c.before : c.type === "weekday" ? "on " + (c.days || []).join(", ") : c.field + " " + c.op + " " + c.value),
    then: lines(auto.steps, 0), asks, runs_on: autoMachine(auto.machine) };
}

function autoRow(a, box) {
  const r = el("div", "row auto-row" + (a.enabled ? "" : " off"));
  r.dataset.id = a.id;
  const sw = el("input", "auto-switch");
  sw.type = "checkbox";
  sw.checked = !!a.enabled;
  sw.setAttribute("role", "switch");
  sw.setAttribute("aria-label", (a.enabled ? "Turn off " : "Turn on ") + a.name);
  sw.title = a.enabled ? "On - click to turn it off" : "Off - click to turn it on";
  sw.addEventListener("change", async () => { await api("/automations/toggle", { id: a.id, enabled: sw.checked }); loadAutomations(); });
  const text = el("div", "auto-text");
  text.append(el("b", "", a.name));
  const card = a.card || {};
  const sched = (a.triggers || []).find((t) => t.type === "schedule" && t.next);
  text.append(el("small", "", (card.when || []).join(" · ") + (sched && a.enabled ? " · next " + sched.next : "")));
  const st = a.stats || {};
  const bits = ["on " + (card.runs_on || autoMachine(a.machine))];
  if (!a.here) bits.push("not this computer");
  if (st.last_status) bits.push("last: " + (RUN_TEXT[st.last_status] || st.last_status) + " " + autoAgo(st.at));
  if (st.runs) bits.push(st.runs + " runs" + (st.failures ? ", " + st.failures + " failed" : ""));
  if (card.asks && card.asks.length) bits.push(card.preapproved ? "pre-approved" : "asks before: " + card.asks.join("; "));
  text.append(el("small", "auto-meta", bits.join(" · ")));
  for (const err of a.errors || []) text.append(el("small", "th-err", err));
  const hook = (a.triggers || []).find((t) => t.type === "webhook" && t.url);
  if (hook) {
    const code = el("code", "auto-hook", hook.url);
    text.append(code);
  }
  const right = el("div", "auto-buttons");
  right.append(
    autoBtn("mini", "Run now", "play", "Run it once now (a test - conditions are not checked).", async () => {
      const res = await api("/automations/run", { id: a.id }).catch(() => null);
      if (!res || !res.ok) showAutoError(r, (res && (res.error || res.skipped)) || "Could not start it.");
      autoUi.open = a.id; loadAutomations();
    }),
    autoBtn("mini", "Run with text", "text", "Run it with some text (from the clipboard when it can) as {{trigger.text}}.", async () => {
      let clip = "";
      try { clip = navigator.clipboard && navigator.clipboard.readText ? await navigator.clipboard.readText() : ""; } catch (_) { clip = ""; }
      const given = window.prompt("Text for this run ({{trigger.text}}):", clip || "");
      if (given === null) return;
      await api("/automations/run", { id: a.id, text: given });
      autoUi.open = a.id; loadAutomations();
    }),
    autoBtn("mini", "History", "history", "Its runs, with every step's log.", () => { autoUi.open = autoUi.open === a.id ? "" : a.id; renderAutomations(box); }),
    autoBtn("mini", "Edit", "pen", "Change its trigger, conditions and steps.", () => { autoUi.editing = JSON.parse(JSON.stringify(a)); renderAutomations(box); box.scrollTop = 0; }),
    autoBtn("mini", "Delete", "trash", "Delete this automation (on every machine).", async () => {
      if (!window.confirm("Delete \"" + a.name + "\" on every machine?")) return;
      await api("/automations/delete", { id: a.id }); loadAutomations();
    }));
  if (card.asks && card.asks.length) {
    right.append(autoBtn("mini", card.preapproved ? "Take back approval" : "Pre-approve", "shield",
      card.preapproved ? "Its account-touching steps will ask you again." : "Let exactly this version run its account-touching steps without asking.",
      async () => { await api("/automations/approve", { id: a.id, on: !card.preapproved }); loadAutomations(); }));
  }
  r.append(sw, text, right);
  if (autoUi.open === a.id) {
    const hist = el("div", "auto-history");
    hist.append(el("p", "note", "Loading history..."));
    r.append(hist);
    loadHistory(a.id, hist);
  }
  return r;
}

async function loadHistory(id, box) {
  const data = await api("/automations/runs?id=" + encodeURIComponent(id)).catch(() => null);
  box.replaceChildren();
  const runs = (data && data.runs) || [];
  if (!runs.length) { box.append(el("p", "note", "It has not run yet.")); return; }
  for (const run of runs.slice(0, 12)) {
    const d = el("details", "auto-run " + run.status);
    const s = el("summary");
    s.append(el("span", "pill-state " + (run.status === "done" ? "ok" : run.status === "failed" ? "bad" : ""), RUN_TEXT[run.status] || run.status),
      el("span", "", " " + new Date(run.created * 1000).toLocaleString() + " · " + run.source + (run.error ? " · " + run.error : "")));
    d.append(s);
    const log = el("ol", "auto-log");
    for (const line of run.log || []) {
      const li = el("li", line.level || "info");
      li.append(el("time", "", new Date(line.t * 1000).toLocaleTimeString()), document.createTextNode(" " + line.text));
      log.append(li);
    }
    d.append(log);
    if (!["done", "failed", "cancelled", "skipped"].includes(run.status)) {
      d.append(autoBtn("mini", "Cancel this run", "stop", "Stop it (and its background job).", async () => { await api("/automations/run/cancel", { run: run.id }); loadAutomations(); }));
    }
    if (run.status === "failed" && box.childNodes.length === 0) d.open = true;
    box.append(d);
  }
}

// ---------------------------------------------------------------- the simple step editor
function fieldInput(obj, spec, onChange) {
  const [key, kind, label, choices] = spec;
  const wrap = el("label", "auto-field" + (kind === "area" || kind === "json" ? " wide" : ""));
  if (label) wrap.append(el("span", "", label));
  let input;
  if (kind === "area" || kind === "json") {
    input = el("textarea");
    input.rows = kind === "json" ? 4 : 3;
    input.value = kind === "json" ? JSON.stringify(obj[key] === undefined ? (key === "args" ? {} : []) : obj[key], null, 1) : (obj[key] || "");
    input.addEventListener("input", () => {
      if (kind === "json") {
        try { obj[key] = JSON.parse(input.value || (key === "args" ? "{}" : "[]")); input.classList.remove("bad"); } catch (_) { input.classList.add("bad"); }
      } else obj[key] = input.value;
      onChange && onChange();
    });
  } else if (kind === "select") {
    input = el("select");
    for (const c of choices) { const o = el("option", "", c); o.value = c; input.append(o); }
    input.value = Array.isArray(obj[key]) ? obj[key].join(",") : (obj[key] || choices[0]);
    input.addEventListener("change", () => { obj[key] = key === "events" ? input.value.split(",") : input.value; });
  } else if (kind === "bool") {
    input = el("input");
    input.type = "checkbox";
    input.checked = obj[key] !== false;
    input.addEventListener("change", () => { obj[key] = input.checked; });
    wrap.classList.add("bool");
  } else {
    input = el("input");
    input.type = kind === "number" ? "number" : "text";
    input.value = obj[key] === undefined ? "" : obj[key];
    input.addEventListener("input", () => { obj[key] = kind === "number" ? Number(input.value) : input.value; });
  }
  input.dataset.key = key;
  wrap.append(input);
  return wrap;
}

function editor(auto, box) {
  const wrap = el("div", "auto-card editor");
  auto.triggers = auto.triggers || [];
  auto.steps = auto.steps || [];
  auto.conditions = auto.conditions || [];
  wrap.append(el("span", "badge", auto.id ? "Editing" : "New automation"));
  wrap.append(fieldInput(auto, ["name", "text", "Name"]));
  const top = el("div", "auto-grid");
  const machines = ["pc", "mac", "any", ((autoUi.data || {}).machine || {}).name].filter((v, i, a) => v && a.indexOf(v) === i);
  top.append(fieldInput(auto, ["machine", "select", "Runs on (one machine fires it)", machines]),
    fieldInput(auto, ["mode", "select", "If it is still running", ["single", "queued", "parallel"]]),
    fieldInput(auto, ["retries", "number", "Retries when a step fails"]),
    fieldInput(auto, ["max_per_hour", "number", "At most runs an hour"]));
  wrap.append(top);
  const redraw = () => { const n = editor(auto, box); wrap.replaceWith(n); };
  const list = (title, items, types, fields, addLabel) => {
    const sect = el("div", "auto-sect");
    sect.append(el("span", "auto-sect-title", title));
    items.forEach((item, i) => {
      const it = el("div", "auto-item");
      const head = el("div", "auto-item-head");
      const sel = el("select");
      for (const [k, v] of Object.entries(types)) { const o = el("option", "", v); o.value = k; sel.append(o); }
      sel.value = item.type || Object.keys(types)[0];
      sel.setAttribute("aria-label", title + " type");
      sel.addEventListener("change", () => { items[i] = { type: sel.value }; redraw(); });
      head.append(el("b", "", (i + 1) + "."), sel);
      if (i > 0) head.append(autoBtn("mini", "Move up", "up", "", () => { items.splice(i - 1, 0, items.splice(i, 1)[0]); redraw(); }));
      if (i < items.length - 1) head.append(autoBtn("mini", "Move down", "down", "", () => { items.splice(i + 1, 0, items.splice(i, 1)[0]); redraw(); }));
      head.append(autoBtn("mini", "Remove", "trash", "", () => { items.splice(i, 1); redraw(); }));
      it.append(head);
      const grid = el("div", "auto-grid");
      for (const spec of fields[sel.value] || []) grid.append(fieldInput(item, spec));
      if (item.type === "webhook" && item.url) grid.append(el("code", "auto-hook", item.url));
      it.append(grid);
      sect.append(it);
    });
    sect.append(autoBtn("mini", addLabel, "plus", "", () => { items.push({ type: Object.keys(types)[0] }); redraw(); }));
    return sect;
  };
  wrap.append(list("When", auto.triggers, TRIGGER_TYPES, TRIGGER_FIELDS, "Add a trigger"));
  const condTypes = { field: "A field of the trigger", time: "A time of day", weekday: "Weekdays" };
  const condFields = { field: [["field", "text", "Field (trigger.subject, trigger.name ...)"], ["op", "select", "", ["contains", "not_contains", "equals", "not_equals", "starts_with", "ends_with", "matches", "gt", "lt", "exists", "missing"]], ["value", "text", "Value"]],
    time: [["after", "text", "After (HH:MM)"], ["before", "text", "Before (HH:MM)"]], weekday: [["days", "text", "Days (mon,tue,...)"]] };
  wrap.append(list("Only if (all must hold)", auto.conditions, condTypes, condFields, "Add a condition"));
  wrap.append(list("Then", auto.steps, STEP_TYPES, STEP_FIELDS, "Add a step"));
  const row = el("div", "auto-actions");
  row.append(autoBtn("send small", "Save", "check", "Save it (an edit takes a pre-approval away).", async () => {
    const r = await api("/automations/save", { automation: auto }).catch(() => null);
    if (!r || !r.ok) { showAutoError(wrap, (r && r.error) || "Could not save it."); return; }
    autoUi.editing = null; loadAutomations();
  }), autoBtn("mini", "Cancel", "close", "Leave without saving.", () => { autoUi.editing = null; renderAutomations(box); }));
  wrap.append(row);
  return wrap;
}

window.Automations = { load: loadAutomations };
