// Loki UI: first-run model setup, the credits meter, and your agents.
// Uses helpers from app.js ($, el, api, addNotice, setStatus, renderAfter, refreshJobs).
"use strict";

const setupView = { timer: 0, last: null };

function fmtTokens(n) {
  n = Number(n) || 0;
  return n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n);
}
function fmtCost(c) {
  c = Number(c) || 0;
  return c === 0 ? "free" : c < 0.01 ? "$" + c.toFixed(4) : "$" + c.toFixed(2);
}
function gb(n) { return (Number(n) || 0).toFixed(n >= 10 ? 0 : 1) + " GB"; }

// ---------------------------------------------------------------- credits meter
function showMeter(usage) {
  if (!usage || !usage.line) return;
  const turns = document.querySelectorAll("#transcript .turn.loki");
  const host = turns[turns.length - 1] || $("#transcript");
  host.append(el("div", "meter", usage.line));
  refreshUsagePill();
}

async function refreshUsagePill() {
  const data = await api("/usage").catch(() => null);
  const pill = $("#usage-pill");
  if (!data || !data.ok) { pill.textContent = "—"; return; }
  const today = data.today || {};
  pill.textContent = today.calls ? fmtCost(today.cost) + " today · " + fmtTokens((today.in || 0) + (today.out || 0)) + " tok" : "Usage";
  pill.classList.toggle("paid", (today.cost || 0) > 0);
}

async function loadUsageTab() {
  const data = await api("/usage").catch(() => null);
  const box = $("#usage-panel");
  box.replaceChildren();
  if (!data || !data.ok) { box.append(el("p", "note", "Usage is not available.")); return; }
  const grid = el("div", "usage-grid");
  const card = (value, label) => { const c = el("div", "usage-card"); c.append(el("b", "", value), el("span", "", label)); return c; };
  grid.append(card(fmtCost(data.today.cost), "today"), card(fmtTokens(data.today.in + data.today.out), "tokens today"),
              card(fmtCost(data.month.cost), "last 30 days"), card(String(data.month.calls), "model calls (30 days)"));
  box.append(grid);
  const table = el("table", "usage");
  const head = el("tr");
  for (const h of ["Provider", "Model", "Calls", "Tokens in / out", "Speed", "Cost"]) head.append(el("th", "", h));
  table.append(head);
  for (const [name, row] of Object.entries(data.by_provider || {})) {
    const tr = el("tr");
    tr.append(el("td", "", name), el("td", "", row.model || ""), el("td", "", String(row.calls)),
              el("td", "", fmtTokens(row.in) + " / " + fmtTokens(row.out)),
              el("td", "", row.avg_tps ? row.avg_tps + " tok/s" : "—"), el("td", "", fmtCost(row.cost)));
    table.append(tr);
  }
  if (!Object.keys(data.by_provider || {}).length) box.append(el("p", "note", "No model calls yet."));
  else box.append(table);
}

// ---------------------------------------------------------------- model setup
function renderSetup(box, data, compact) {
  box.replaceChildren();
  const hw = data.hardware || {};
  const mem = hw.vram_gb ? gb(hw.vram_gb) + " GPU memory (" + (hw.gpu || "GPU") + ")" : gb(hw.ram_gb) + " memory" + (hw.unified ? " (Apple Silicon)" : "");
  box.append(el("p", "setup-hw", "This computer: " + mem + " · room for a model up to about " + gb(hw.budget_gb) + "."));

  const active = data.active || {};
  if (active.local) {
    const ok = el("div", "setup-step ok");
    ok.append(el("h3", "", "Running offline on " + active.local),
              el("p", "note", (active.local_note || "") + (active.online ? "" : " · no internet right now - Loki is staying local.")));
    const prefer = el("label", "check");
    const box2 = el("input");
    box2.type = "checkbox";
    box2.checked = active.prefer !== "cloud";
    box2.addEventListener("change", async () => {
      const r = await api("/setup/prefer", { prefer: box2.checked ? "local" : "cloud" });
      if (r.ok) setStatus("Using " + r.using, true);
    });
    prefer.append(box2, document.createTextNode(" Prefer this local model (fast, free, private). Untick to prefer cloud models when online."));
    ok.append(prefer);
    box.append(ok);
  }

  // Step 1: a local model server
  const ol = data.ollama || {};
  const servers = data.servers || [];
  const s1 = el("div", "setup-step" + (ol.running || servers.length ? " ok" : ""));
  s1.append(el("h3", "", ol.running ? "Ollama is running" : servers.length ? "Found " + servers.map((s) => s.label).join(", ") : "Install a local model runner"));
  if (!ol.running && !servers.length) {
    s1.append(el("p", "note", ol.installed ? "Ollama is installed but not running. Open the Ollama app, then come back." :
      "Loki runs models through Ollama (free, open source). It downloads from ollama.com and installs like any app."));
    if (!ol.installed) {
      const install = el("button", "send", "Install Ollama for me");
      install.type = "button";
      install.addEventListener("click", async () => {
        install.disabled = true;
        const r = await api("/setup/install-ollama", {});
        if (!r.ok) addNotice(r.error || "Could not start the install.", true);
        watchProgress(box, compact);
      });
      s1.append(install);
    }
  }
  box.append(s1);

  // Step 2: installed models / recommendations
  const s2 = el("div", "setup-step" + (data.best && data.best.tools ? " ok" : ""));
  s2.append(el("h3", "", data.best && data.best.tools ? "Model ready: " + data.best.name : "Download a model that fits"));
  // loki-* are Loki's own long-context copies of a model (no extra download): not listed.
  const installed = (ol.models || []).filter((m) => !/embed/i.test(m.name) && !/^loki-/.test(m.name));
  for (const m of installed) {
    const row = el("div", "model-row");
    const info = el("div", "grow");
    info.append(document.createTextNode(m.name), el("small", "", (m.params || "") + " · " + gb(m.size_gb) + " · installed"));
    const use = el("button", "quiet", active.local === m.name || (active.local || "").includes(m.name.replace(/[:]/g, "-")) ? "In use" : "Use");
    use.type = "button";
    use.addEventListener("click", async () => {
      const r = await api("/setup/use", { model: m.name });
      if (r.ok) { setStatus("Local model: " + r.local, true); openSetup(true); }
    });
    row.append(info, use);
    s2.append(row);
  }
  if (ol.running || !servers.length) {
    for (const rec of data.recommend || []) {
      if (rec.installed) continue;
      const row = el("div", "model-row");
      const info = el("div", "grow");
      info.append(document.createTextNode(rec.tag), el("small", "", rec.why + " · " + gb(rec.size) + " download · needs ~" + gb(rec.need)));
      const get = el("button", "send", "Download");
      get.type = "button";
      get.disabled = !ol.running;
      get.title = ol.running ? "" : "Install or open Ollama first";
      get.addEventListener("click", async () => {
        const rest = (data.recommend || []).filter((r) => !r.installed).map((r) => r.tag);
        const tags = [rec.tag, ...rest.filter((t) => t !== rec.tag)].slice(0, 3);
        const r = await api("/setup/pull", { tags });
        if (!r.ok) addNotice(r.error || "Could not start the download.", true);
        watchProgress(box, compact);
      });
      row.append(info, get);
      s2.append(row);
      if (compact && s2.querySelectorAll(".model-row").length >= 4) break;
    }
  }
  box.append(s2);

  const p = data.progress || {};
  if (p.op && !p.done) appendProgress(box, p);
  if (!compact) {
    const cloud = el("p", "note", (data.cloud_ready || []).length ? "Until then Loki can answer through " + data.cloud_ready.slice(0, 3).join(", ") + " (online only)." : (data.cloud_keys || []).length ? "Cloud keys found: " + data.cloud_keys.join(", ") + "." :
      "Prefer the cloud too? Add a provider key in Settings > Connections - Loki will use local when offline and cloud when it helps.");
    box.append(cloud);
  }
}

function appendProgress(box, p) {
  const wrap = el("div", "setup-step");
  wrap.id = "setup-progress";
  wrap.append(el("h3", "", (p.op === "install" ? "Installing " : "Downloading ") + (p.target || "")),
              el("p", "note", (p.message || p.status || "") + (p.total ? " · " + p.percent + "%" : "")));
  const bar = el("div", "bar");
  const fill = el("i");
  fill.style.width = (p.percent || 0) + "%";
  bar.append(fill);
  wrap.append(bar);
  const old = box.querySelector("#setup-progress");
  if (old) old.replaceWith(wrap); else box.append(wrap);
}

function watchProgress(box, compact) {
  clearInterval(setupView.timer);
  setupView.timer = setInterval(async () => {
    const r = await api("/setup/progress").catch(() => null);
    if (!r || !r.ok) return;
    appendProgress(box, r.progress);
    if (r.progress.done) {
      clearInterval(setupView.timer);
      if (r.progress.error && r.progress.status === "failed") addNotice(r.progress.message, true);
      setTimeout(() => (compact ? loadModelsTab() : openSetup(true)), 800);
      if (typeof loadModels === "function") loadModels();
    }
  }, 1000);
}

async function openSetup(force) {
  const data = await api("/setup").catch(() => null);
  if (!data || !data.ok) return;
  setupView.last = data;
  if (!force) {
    if (!data.needs_setup) return;
    let later = "";
    try { later = localStorage.getItem("loki-setup-later") || ""; } catch (_) { /* no storage */ }
    if (later && Date.now() - Number(later) < 7 * 86400000) return;  // asked within the week
  }
  $("#setup").hidden = false;
  renderSetup($("#setup-body"), data, false);
}

async function loadModelsTab() {
  const data = await api("/setup").catch(() => null);
  const box = $("#models-panel");
  if (!data || !data.ok) { box.replaceChildren(el("p", "note", "Model setup is not available.")); return; }
  renderSetup(box, data, true);
}

// ---------------------------------------------------------------- agents
const agentsView = { list: [], editing: null };

function renderAgents() {
  const list = $("#agent-list");
  list.replaceChildren();
  for (const a of agentsView.list) {
    const card = el("div", "agent-card");
    card.append(el("b", "", a.name + (a.engine !== "loki" ? " · " + a.engine : "")),
                el("p", "", a.instructions || "No instructions yet."));
    const task = el("input");
    task.placeholder = "Give " + a.name + " a task…";
    task.setAttribute("aria-label", "Task for " + a.name);
    const run = el("button", "send", "Run");
    run.type = "button";
    const go = async () => {
      if (!task.value.trim()) { task.focus(); return; }
      run.disabled = true;
      const r = await api("/agents/run", { id: a.id, task: task.value.trim() });
      run.disabled = false;
      if (r.ok) { task.value = ""; renderAfter(r); setStatus(a.name + " is working in the background", true); }
      else addNotice(r.error || "Could not start the agent.", true);
    };
    run.addEventListener("click", go);
    task.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
    const edit = el("button", "quiet", "Edit");
    edit.type = "button";
    edit.addEventListener("click", () => editAgent(a));
    const row = el("div", "row-actions");
    row.append(task, run, edit);
    card.append(row);
    list.append(card);
  }
}

async function loadAgents() {
  const data = await api("/agents").catch(() => null);
  if (!data || !data.ok) return;
  agentsView.list = data.agents || [];
  renderAgents();
}

function editAgent(agent) {
  agentsView.editing = agent || null;
  $("#agent-form").hidden = false;
  $("#agent-name").value = agent ? agent.name : "";
  $("#agent-engine").value = agent ? agent.engine : "loki";
  $("#agent-commands").checked = agent ? !!agent.allow_commands : false;
  $("#agent-instructions").value = agent ? agent.instructions || "" : "";
  $("#agent-result").textContent = "";
  let del = $("#agent-delete");
  if (agent && !del) {
    del = el("button", "quiet", "Delete");
    del.type = "button";
    del.id = "agent-delete";
    $("#agent-cancel").before(del);
  }
  if (del) {
    del.hidden = !agent;
    del.onclick = async () => {
      const r = await api("/agents/delete", { id: agentsView.editing.id });
      if (r.ok) { agentsView.list = r.agents; renderAgents(); $("#agent-form").hidden = true; }
    };
  }
  $("#agent-name").focus();
}

async function saveAgent(event) {
  event.preventDefault();
  const body = {
    name: $("#agent-name").value.trim(), engine: $("#agent-engine").value,
    allow_commands: $("#agent-commands").checked, instructions: $("#agent-instructions").value.trim(),
  };
  if (agentsView.editing) body.id = agentsView.editing.id;
  const r = await api("/agents", body);
  if (!r.ok) { $("#agent-result").textContent = r.error || "Could not save."; return; }
  agentsView.list = r.agents;
  renderAgents();
  $("#agent-form").hidden = true;
}

// ---------------------------------------------------------------- wiring
function afterStart() {
  $("#usage-pill").addEventListener("click", () => { openSettings(); showTab("usage"); });
  $("#usage-reset").addEventListener("click", async () => { await api("/usage/reset", {}); loadUsageTab(); refreshUsagePill(); });
  $("#close-setup").addEventListener("click", () => {
    $("#setup").hidden = true;
    clearInterval(setupView.timer);
    try { localStorage.setItem("loki-setup-later", String(Date.now())); } catch (_) { /* no storage */ }
  });
  $("#new-agent").addEventListener("click", () => editAgent(null));
  $("#agent-cancel").addEventListener("click", () => { $("#agent-form").hidden = true; });
  $("#agent-form").addEventListener("submit", saveAgent);
  $("#open-jobs").addEventListener("click", loadAgents);
  $("#job-backend").addEventListener("change", () => {
    const loki = $("#job-agent").querySelector('option[value="loki"]');
    const herdr = $("#job-backend").value === "herdr";
    if (loki) loki.disabled = herdr;
    if (herdr && $("#job-agent").value === "loki") $("#job-agent").value = "claude-code";
  });
  // Default the backend to "This computer" so the built-in agent works out of the box.
  const local = $("#job-backend").querySelector('option[value="local"]');
  if (local) $("#job-backend").value = "local";
  refreshUsagePill();
  openSetup(false);
}
