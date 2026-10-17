// Settings > Tools, session 28: the tool health map (every tool, MCP server, add-on, connector, computer use
// and the browser, with a live status and a one-click fix) and the connector cards (email, calendar, Google,
// GitHub, notes, files on my machines, computer use, browser). Secrets are password fields: the window only
// ever learns "saved" / "not saved". Uses api(), el(), addNotice() from app.js. Plain DOM (CSP).
"use strict";

const toolsUi = { filter: "problems", signin: null };
const STATUS_TEXT = { ok: "Works", needs_setup: "Needs setup", off: "Off", missing: "Not installed", broken: "Broken",
  failing: "Failing - hidden", stopped: "Stopped", idle: "Idle" };
const KIND_TEXT = { connector: "Connector", computer: "Computer", browser: "Browser", tool: "Tool", mcp: "MCP server", addon: "Add-on" };

function toolsAgo(t) {
  if (!t) return "";
  const s = Math.max(0, Math.round(Date.now() / 1000 - t));
  return s < 60 ? s + "s ago" : s < 3600 ? Math.round(s / 60) + " min ago" : s < 86400 ? Math.round(s / 3600) + " h ago" : Math.round(s / 86400) + " d ago";
}

async function loadToolsPanel() {
  const box = document.getElementById("tools-health");
  if (!box) return;
  const data = await api("/tools/health").catch(() => null);
  box.replaceChildren();
  if (!data || !data.ok) { box.append(el("p", "note", "The tool health map is not available in this engine.")); return; }
  const s = data.summary || {};
  const head = el("div", "th-head");
  head.append(el("b", "", (s.ok || 0) + " work · " + ((s.needs_setup || 0) + (s.missing || 0)) + " need setup · " +
    (s.off || 0) + " off" + ((s.failing || 0) + (s.broken || 0) + (s.stopped || 0) ? " · " + ((s.failing || 0) + (s.broken || 0) + (s.stopped || 0)) + " problems" : "")));
  const filters = el("div", "chips");
  for (const [key, label] of [["problems", "Needs attention"], ["connector", "Connectors"], ["all", "Everything"]]) {
    const b = el("button", "chip" + (toolsUi.filter === key ? " on" : ""), label);
    b.type = "button";
    b.setAttribute("aria-pressed", String(toolsUi.filter === key));
    b.addEventListener("click", () => { toolsUi.filter = key; loadToolsPanel(); });
    filters.append(b);
  }
  const recheck = el("button", "mini", "Check again");
  recheck.type = "button";
  recheck.addEventListener("click", async () => { await api("/tools/health/recheck", {}).catch(() => null); loadToolsPanel(); });
  head.append(filters, recheck);
  box.append(head);
  if ((data.hidden || []).length) box.append(el("p", "note", "Hidden from the model right now (so it does not waste steps): " + data.hidden.join(", ")));
  const rows = el("div", "rows th-rows");
  const items = (data.items || []).filter((it) => {
    if (toolsUi.filter === "all") return true;
    if (toolsUi.filter === "connector") return ["connector", "computer", "browser"].includes(it.kind);
    return it.status !== "ok" && it.status !== "idle" && !(it.kind === "addon" && it.status === "off") && !(it.kind === "mcp" && it.status === "off");
  });
  if (!items.length) rows.append(el("p", "note", toolsUi.filter === "problems" ? "Nothing needs attention." : "Nothing here."));
  for (const it of items) rows.append(toolRow(it, data.installs || {}));
  box.append(rows);
  loadConnectorCards();
}

function toolRow(it, installs) {
  const r = el("div", "row th-row");
  r.dataset.status = it.status;
  const left = el("div", "th-text");
  const title = el("b", "", it.label);
  left.append(title, el("span", "badge subtle", KIND_TEXT[it.kind] || it.kind));
  const bits = [];
  if (it.detail) bits.push(it.detail);
  if (it.calls) bits.push(it.calls + " calls" + (it.fails ? ", " + it.fails + " failed" : ""));
  if (it.last_ok) bits.push("last worked " + toolsAgo(it.last_ok));
  left.append(el("small", "", bits.join(" · ")));
  if (it.last_err && it.status !== "ok") left.append(el("small", "th-err", "Last error " + toolsAgo(it.last_err_t) + ": " + it.last_err));
  const right = el("div", "th-right");
  right.append(el("span", "pill-state " + (it.status === "ok" ? "ok" : (["broken", "failing", "stopped"].includes(it.status) ? "bad" : "")), STATUS_TEXT[it.status] || it.status));
  const inst = installs[(it.fix || {}).arg];
  if (inst && inst.running) right.append(el("span", "note", "installing…"));
  else if (it.fix && it.fix.action) {
    const b = el("button", "mini", it.fix.label || "Fix");
    b.type = "button";
    b.addEventListener("click", () => runToolFix(it, b));
    right.append(b);
  }
  r.append(left, right);
  return r;
}

async function runToolFix(it, button) {
  const fix = it.fix || {};
  if (fix.action === "hint") { addNotice(fix.arg || it.detail || "See the engine log."); return; }
  if (fix.action === "configure") {
    const card = document.querySelector('[data-connector="' + (fix.arg || "") + '"]') ||
      document.querySelector('[data-connector-tool="' + (fix.arg || "") + '"]');
    if (card) { card.open = true; card.scrollIntoView({ behavior: "smooth", block: "start" }); }
    return;
  }
  button.disabled = true;
  let res = await api("/tools/health/fix", { id: it.id, action: fix.action, arg: fix.arg || "" }).catch(() => null);
  if (res && res.confirm) {
    if (!window.confirm(res.confirm)) { button.disabled = false; return; }
    res = await api("/tools/health/fix", { id: it.id, action: fix.action, arg: fix.arg || "", confirm: true }).catch(() => null);
  }
  if (!res || !res.ok) addNotice((res && res.error) || "That did not work.", true);
  else if (res.note) addNotice(res.note);
  if (fix.action === "install") setTimeout(loadToolsPanel, 4000);
  loadToolsPanel();
}

// ---------------------------------------------------------------- connector cards
async function loadConnectorCards() {
  const box = document.getElementById("connector-cards");
  if (!box) return;
  const data = await api("/connectors").catch(() => null);
  const open = new Set(Array.from(box.querySelectorAll("details[open]")).map((d) => d.dataset.connector));
  box.replaceChildren();
  if (!data || !data.ok) return;
  for (const c of data.connectors || []) box.append(connectorCard(c, open.has(c.id)));
  if (open.has("computer")) loadComputerState();
}

function connectorCard(c, isOpen) {
  const card = el("details", "conn-card");
  card.dataset.connector = c.id;
  if (c.tool) card.dataset.connectorTool = c.tool;
  card.open = isOpen;
  const sum = el("summary");
  sum.append(el("b", "", c.label), el("span", "pill-state " + (c.configured ? "ok" : ""), c.configured ? "Connected" : "Not set up"));
  card.append(sum);
  if (c.about) card.append(el("p", "note", c.about));
  if (c.writes && c.writes.length) card.append(el("p", "note", "Always asks you before: " + c.writes.join(", ") + "."));
  if (c.detail) card.append(el("p", "note conn-detail", c.detail));
  const form = el("form", "conn-form");
  const inputs = {};
  for (const f of c.fields || []) {
    const row = el("label", "conn-field");
    row.append(el("span", "", f.label));
    let input;
    if (f.kind === "choice") {
      input = el("select", "text-in");
      for (const ch of f.choices || []) { const o = el("option", "", ch); o.value = ch; if (ch === (f.value || "")) o.selected = true; input.append(o); }
    } else if (f.kind === "bool") {
      input = el("input");
      input.type = "checkbox";
      input.checked = f.value === "1";
    } else {
      input = el("input", "text-in");
      input.type = f.kind === "secret" ? "password" : "text";
      input.autocomplete = "off";
      input.spellcheck = false;
      if (f.kind === "secret") input.placeholder = f.saved ? "saved - paste a new one to replace" : "paste it here";
      else input.value = f.value || "";
    }
    input.setAttribute("aria-label", f.label);
    inputs[f.key] = { input, field: f };
    row.append(input);
    form.append(row);
  }
  const bar = el("div", "conn-bar");
  const save = el("button", "", "Save");
  save.type = "submit";
  bar.append(save);
  if (c.id !== "computer" && c.id !== "browser") {
    const test = el("button", "mini", "Test");
    test.type = "button";
    test.addEventListener("click", async () => {
      test.disabled = true;
      const res = await api("/connectors/test", { id: c.id }).catch(() => null);
      test.disabled = false;
      const r = res && res.result;
      addNotice(r ? (r.ok ? "Works: " : "Problem: ") + (r.detail || "") : "Could not test.", !(r && r.ok));
      loadToolsPanel();
    });
    bar.append(test);
  }
  if ((c.fields || []).some((f) => f.kind === "secret" && f.saved)) {
    const forget = el("button", "mini", "Disconnect");
    forget.type = "button";
    forget.addEventListener("click", async () => {
      if (!window.confirm("Forget the saved secrets of " + c.label + "?")) return;
      await api("/connectors/forget", { id: c.id }).catch(() => null);
      loadToolsPanel();
    });
    bar.append(forget);
  }
  if (c.signin === "google") {
    const go = el("button", "mini", "Sign in with Google");
    go.type = "button";
    go.addEventListener("click", () => googleSignin(card));
    bar.append(go);
  }
  form.append(bar);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const values = {};
    for (const [key, { input, field }] of Object.entries(inputs)) {
      if (field.kind === "bool") values[key] = input.checked ? "1" : "0";
      else if (field.kind === "secret") { if (input.value) values[key] = input.value; }
      else values[key] = input.value;
    }
    const res = await api("/connectors/save", { id: c.id, values }).catch(() => null);
    for (const { input, field } of Object.values(inputs)) if (field.kind === "secret") input.value = "";
    if (!res || !res.ok) addNotice((res && res.error) || "Not saved.", true);
    else addNotice("Saved.");
    loadToolsPanel();
  });
  card.append(form);
  if (c.help) card.append(el("p", "note conn-help", c.help));
  if (c.id === "computer") {
    const state = el("div", "conn-computer");
    state.id = "computer-state";
    card.append(state);
    card.addEventListener("toggle", () => { if (card.open) loadComputerState(); });
  }
  return card;
}

async function googleSignin(card) {
  const res = await api("/connectors/signin", { id: "google" }).catch(() => null);
  if (!res || !res.ok) { addNotice((res && res.error) || "Could not start the sign-in.", true); return; }
  const note = el("p", "note", "Your browser opened Google's sign-in. If it did not, open this link: ");
  const link = el("code", "", res.url);
  note.append(link);
  card.append(note);
  toolsUi.signin = res.state;
  for (let i = 0; i < 300 && toolsUi.signin === res.state; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const st = await api("/connectors/signin/status?state=" + encodeURIComponent(res.state)).catch(() => null);
    if (st && st.done) {
      addNotice(st.signed_in ? "Signed in to Google." : "Google sign-in failed: " + (st.error || ""), !st.signed_in);
      loadToolsPanel();
      return;
    }
  }
}

async function loadComputerState() {
  const box = document.getElementById("computer-state");
  if (!box) return;
  const st = await api("/computer").catch(() => null);
  box.replaceChildren();
  if (!st || !st.ok) { box.append(el("p", "note", "Computer use is not loaded in this engine.")); return; }
  box.append(el("p", "note", (st.available ? st.detail : "Not available here: " + st.detail) + " · kill switch: " + st.kill_hotkey));
  box.append(el("p", "note", st.armed ? "Armed." : "STOPPED (" + (st.tripped || "kill switch") + ") - nothing will be clicked or typed until you re-arm."));
  if ((st.approved_apps || []).length) box.append(el("p", "note", "Approved until LOKI restarts: " + st.approved_apps.join(", ")));
  const bar = el("div", "conn-bar");
  const act = (label, route) => {
    const b = el("button", "mini", label);
    b.type = "button";
    b.addEventListener("click", async () => { await api(route, {}).catch(() => null); loadComputerState(); loadToolsPanel(); });
    bar.append(b);
  };
  if (st.armed) act("Stop now", "/computer/stop"); else act("Re-arm", "/computer/arm");
  if ((st.approved_apps || []).length) act("Forget app approvals", "/computer/forget");
  box.append(bar);
  if ((st.log || []).length) {
    const log = el("div", "conn-log");
    log.append(el("b", "", "Recent actions"));
    for (const e of st.log.slice().reverse()) {
      log.append(el("div", e.ok ? "" : "th-err", new Date(e.t * 1000).toLocaleTimeString() + "  " + (e.app || "") + "  " + e.action + "  " + (e.target || "") + (e.note ? "  (" + e.note + ")" : "")));
    }
    box.append(log);
  }
}
