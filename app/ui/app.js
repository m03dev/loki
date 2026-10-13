// Loki standalone app UI. Talks to the local Loki engine over its loopback API.
// The engine token arrives in the URL fragment (#token=...), which the browser never
// sends to the server; it is kept in sessionStorage for reloads and then removed from
// the address.
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = {
  token: "",
  busy: false,
  cursor: 0,
  chatId: "",
  startedAt: 0,
  active: "",
  conversations: [],
  approvalId: "",
  connected: false,
};

// ---------------------------------------------------------------- token + API
function readToken() {
  const match = /(?:^|[#&])token=([^&]+)/.exec(location.hash);
  if (match) {
    const token = decodeURIComponent(match[1]);
    try { sessionStorage.setItem("loki-token", token); } catch (_) { /* private mode */ }
    history.replaceState(null, "", location.pathname);
    return token;
  }
  try { return sessionStorage.getItem("loki-token") || ""; } catch (_) { return ""; }
}

async function api(path, body) {
  const init = { headers: { Authorization: "Bearer " + state.token } };
  if (body !== undefined) {
    init.method = "POST";
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init);
  let data = {};
  try { data = await response.json(); } catch (_) { data = { ok: false, error: "Bad response from Loki." }; }
  if (response.status === 401) setStatus("Not authorised: reopen Loki from the app", false);
  return data;
}

// ---------------------------------------------------------------- rendering
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// A small Markdown subset: fenced code, inline code, bold, headings, lists, paragraphs.
// Everything is escaped first, so model output can never inject markup.
function renderMarkdown(source) {
  const parts = String(source).split(/```/);
  let html = "";
  parts.forEach((part, index) => {
    if (index % 2 === 1) {
      const body = part.replace(/^[^\n]*\n/, "");
      html += "<pre><code>" + escapeHtml(body.replace(/\n$/, "")) + "</code></pre>";
      return;
    }
    const blocks = escapeHtml(part).split(/\n{2,}/);
    for (const block of blocks) {
      const trimmed = block.trim();
      if (!trimmed) continue;
      const lines = trimmed.split("\n");
      const inline = (t) => t.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      const heading = /^(#{1,3})\s+(.*)$/.exec(trimmed);
      if (heading && lines.length === 1) {
        const level = heading[1].length;
        html += `<h${level}>${inline(heading[2])}</h${level}>`;
      } else if (lines.every((l) => /^\s*[-*]\s+/.test(l))) {
        html += "<ul>" + lines.map((l) => "<li>" + inline(l.replace(/^\s*[-*]\s+/, "")) + "</li>").join("") + "</ul>";
      } else if (lines.every((l) => /^\s*\d+[.)]\s+/.test(l))) {
        html += "<ol>" + lines.map((l) => "<li>" + inline(l.replace(/^\s*\d+[.)]\s+/, "")) + "</li>").join("") + "</ol>";
      } else {
        html += "<p>" + inline(lines.join("<br>")) + "</p>";
      }
    }
  });
  return html;
}

function scrollDown() {
  const t = $("#transcript");
  t.scrollTop = t.scrollHeight;
}

function addUser(text) {
  const turn = el("div", "turn user");
  turn.append(el("div", "bubble", text));
  $("#transcript").append(turn);
  scrollDown();
}

function addLoki(text) {
  const turn = el("div", "turn loki");
  const body = el("div", "text");
  body.innerHTML = renderMarkdown(text);
  turn.append(body);
  $("#transcript").append(turn);
  scrollDown();
}

function addNotice(text, isError) {
  $("#transcript").append(el("div", "notice" + (isError ? " error" : ""), text));
  scrollDown();
}

const EVENT_LABELS = { tool: "Tool", tool_result: "Result", task: "Task", done: "Done", error: "Error", approval: "Permission" };

function addEvent(kind, text) {
  const details = el("details", "event " + kind);
  const summary = el("summary");
  summary.append(el("span", "kind", EVENT_LABELS[kind] || kind), document.createTextNode(text.split("\n")[0].slice(0, 160)));
  details.append(summary, el("pre", "", text));
  $("#transcript").append(details);
  scrollDown();
}

function showEmpty() {
  const box = el("div", "empty");
  box.append(el("h2", "", "What should Loki work on?"));
  box.append(el("p", "", "Ask a question, plan a change, or switch to Build and let Loki do it. Risky actions always ask you first."));
  $("#transcript").append(box);
}

function renderMessages(messages) {
  $("#transcript").replaceChildren();
  if (!messages || messages.length === 0) { showEmpty(); return; }
  for (const message of messages) {
    const content = String(message.content || "").trim();
    if (!content) continue;
    if (message.role === "user") addUser(content);
    else if (message.role === "assistant") addLoki(content);
  }
}

function setStatus(text, ok) {
  const s = $("#status");
  s.textContent = text;
  s.className = "status" + (ok === true ? " ok" : ok === false ? " bad" : ok === "wait" ? " wait" : "");
}

// ---------------------------------------------------------------- conversations
function renderConversations() {
  const nav = $("#conversations");
  nav.replaceChildren();
  for (const convo of state.conversations) {
    const row = el("div", "convo" + (convo.id === state.active ? " active" : ""));
    const open = el("button", "open", convo.title || "New chat");
    open.type = "button";
    open.title = convo.title || "New chat";
    open.addEventListener("click", () => switchTo(convo.id));
    const del = el("button", "del", "×");
    del.type = "button";
    del.setAttribute("aria-label", "Delete chat " + (convo.title || ""));
    del.addEventListener("click", () => removeChat(convo.id));
    row.append(open, del);
    nav.append(row);
  }
  const current = state.conversations.find((c) => c.id === state.active);
  $("#chat-title").textContent = current ? (current.title || "New chat") : "Loki";
}

function applyConversations(data) {
  if (!data || !data.ok) {
    if (data && data.error) addNotice(data.error, true);
    return;
  }
  if (data.conversations) state.conversations = data.conversations;
  if (data.active !== undefined) state.active = data.active;
  renderConversations();
  if (data.messages) renderMessages(data.messages);
}

async function loadConversations() {
  const data = await api("/conversations");
  applyConversations(data);
  if (state.active) {
    const messages = await api("/conversations/messages?id=" + encodeURIComponent(state.active));
    if (messages.ok) renderMessages(messages.messages);
  } else {
    renderMessages([]);
  }
}

async function switchTo(id) {
  if (state.busy || id === state.active) return;
  applyConversations(await api("/conversations/switch", { id }));
}

async function newChat() {
  if (state.busy) return;
  applyConversations(await api("/conversations", { title: "" }));
  renderMessages([]);
  $("#prompt").focus();
}

async function removeChat(id) {
  if (state.busy) return;
  const data = await api("/conversations/delete", { id });
  applyConversations(data);
  await loadConversations();
}

// ---------------------------------------------------------------- sending
function setBusy(busy) {
  state.busy = busy;
  $("#send").disabled = busy;
  $("#stop").hidden = !busy;
  $("#elapsed").textContent = "";
  if (busy) state.startedAt = Date.now();
}

async function send(text) {
  if (state.busy || !text.trim()) return;
  if (state.active === "" || $("#transcript").querySelector(".empty")) $("#transcript").replaceChildren();
  addUser(text);
  setBusy(true);
  state.cursor = 0;
  state.chatId = "";
  setStatus("Working…");
  const progress = setInterval(pollProgress, 700);
  try {
    const data = await api("/chat", { message: text });
    await pollProgress();
    if (data.ok) {
      const reply = String(data.response || "").trim();
      if (reply) addLoki(reply);
      setStatus("Ready", true);
    } else {
      // The engine usually streamed this error already; do not show it twice.
      const message = String(data.error || "Loki could not answer.");
      const shown = [...document.querySelectorAll(".event.error pre")].some((n) => n.textContent.trim() === message.trim());
      if (!shown) addNotice(message, true);
      setStatus("Ready", true);
    }
  } catch (err) {
    addNotice("Lost the connection to the Loki engine. It may have stopped; reopen Loki.", true);
    setStatus("Disconnected", false);
  } finally {
    clearInterval(progress);
    setBusy(false);
    const data = await api("/conversations").catch(() => null);
    if (data) applyConversations(data);
  }
}

async function pollProgress() {
  if (!state.busy) return;
  $("#elapsed").textContent = Math.round((Date.now() - state.startedAt) / 1000) + "s";
  let data;
  try { data = await api("/progress?after=" + state.cursor); } catch (_) { return; }
  if (!data.ok || !data.chat_id) return;
  if (!state.chatId) state.chatId = data.chat_id;
  else if (state.chatId !== data.chat_id) return;
  for (const event of data.progress || []) {
    state.cursor = Math.max(state.cursor, Number(event.id) || 0);
    const kind = String(event.event || "progress");
    const text = String(event.text || "");
    if (kind === "thinking") setStatus("Thinking…");
    else if (kind === "assistant") addLoki(text);
    else if (kind in EVENT_LABELS && kind !== "approval") {
      if (kind === "tool") setStatus("Using a tool…");
      addEvent(kind, text);
    }
  }
}

// ---------------------------------------------------------------- approvals
async function pollApproval() {
  let data;
  try { data = await api("/approval"); } catch (_) {
    if (state.connected) setStatus("Engine not responding", false);
    state.connected = false;
    return;
  }
  if (!data.ok) return;
  if (!state.connected) { state.connected = true; if (!state.busy) setStatus("Ready", true); }
  const ticket = data.approval;
  if (!ticket || ticket.id === state.approvalId) return;
  state.approvalId = ticket.id;
  setStatus("Waiting for your approval", "wait");
  const card = el("div", "approval");
  card.setAttribute("role", "alertdialog");
  card.append(el("h3", "", "Loki wants to run " + ticket.tool));
  card.append(el("p", "", "Allow only if you understand what this does."));
  card.append(el("pre", "", String(ticket.details || "")));
  const actions = el("div", "actions");
  const allow = el("button", "allow", "Allow");
  const deny = el("button", "", "Deny");
  allow.type = deny.type = "button";
  const decide = async (approved) => {
    allow.disabled = deny.disabled = true;
    await api("/approval", { id: ticket.id, approved });
    card.classList.add("settled");
    actions.replaceChildren(el("span", "", approved ? "Allowed." : "Denied."));
    setStatus("Working…");
  };
  allow.addEventListener("click", () => decide(true));
  deny.addEventListener("click", () => decide(false));
  actions.append(allow, deny);
  card.append(actions);
  $("#transcript").append(card);
  scrollDown();
  allow.focus();
}

// ---------------------------------------------------------------- mode + model
async function loadMode() {
  const data = await api("/mode");
  if (data.ok) markMode(data.mode);
}

function markMode(mode) {
  for (const button of document.querySelectorAll(".modes button")) {
    button.setAttribute("aria-checked", String(button.dataset.mode === mode));
  }
}

async function loadModels() {
  const data = await api("/models");
  if (!data.ok) return;
  const select = $("#model-select");
  select.replaceChildren();
  for (const name of data.models) {
    const option = el("option", "", name);
    option.value = name;
    option.selected = name === data.current;
    select.append(option);
  }
}

async function loadHealth() {
  const data = await api("/health");
  if (!data.ok) return false;
  $("#workspace").textContent = data.workspace || "";
  $("#workspace").title = "Workspace: " + (data.workspace || "");
  return true;
}

// ---------------------------------------------------------------- settings
async function openSettings() {
  $("#settings").hidden = false;
  showTab("connections");
  $("#close-settings").focus();
}

function showTab(name) {
  for (const tab of document.querySelectorAll(".tabs button")) tab.setAttribute("aria-selected", String(tab.dataset.tab === name));
  for (const panel of document.querySelectorAll("[data-panel]")) panel.hidden = panel.dataset.panel !== name;
  if (name === "connections") loadConnections();
  if (name === "tools") loadCategories();
  if (name === "memory") loadMemory();
  if (name === "capabilities") loadCapabilities();
}

function row(label, status, ready) {
  const r = el("div", "row");
  r.append(el("span", "", label), el("span", "state" + (ready ? " ready" : ""), status));
  return r;
}

async function loadConnections() {
  const data = await api("/connections");
  const box = $("#providers");
  box.replaceChildren();
  if (!data.ok) return;
  for (const p of data.providers || []) box.append(row(p.label, p.status, /configured|detected|installed/i.test(p.status) && !/not/i.test(p.status)));
  for (const t of data.tools || []) box.append(row(t.label, t.status, !/not detected/i.test(t.status)));
}

async function loadCategories() {
  const data = await api("/settings");
  const box = $("#categories");
  box.replaceChildren();
  if (!data.ok) return;
  for (const [name, enabled] of Object.entries(data.categories || {})) {
    const r = el("div", "row");
    const label = el("label");
    const box2 = el("input");
    box2.type = "checkbox";
    box2.checked = Boolean(enabled);
    box2.addEventListener("change", async () => {
      const result = await api("/settings", { category: name, enabled: box2.checked });
      if (!result.ok) { box2.checked = !box2.checked; addNotice(result.error || "Could not change that setting.", true); }
    });
    label.append(box2, document.createTextNode((data.labels && data.labels[name]) || name));
    r.append(label);
    box.append(r);
  }
}

async function loadMemory() {
  const data = await api("/memory");
  if (data.ok) $("#memory-text").value = data.memory || "";
}

async function loadManifests() {
  const data = await api("/capabilities/manifests").catch(() => null);
  const box = $("#manifests");
  box.replaceChildren();
  if (!data || !data.ok) return;
  for (const cap of data.capabilities || []) {
    const r = el("div", "row manifest");
    const top = el("div", "row-top");
    const label = el("label");
    const toggle = el("input");
    toggle.type = "checkbox";
    toggle.checked = cap.status === "enabled" || cap.status === "missing";
    toggle.disabled = cap.status === "invalid";
    toggle.addEventListener("change", async () => {
      if (toggle.checked && cap.permissions.some((p) => p.high_risk)) {
        const list = cap.permissions.map((p) => "- " + p.text).join("\n");
        if (!confirm("Turn on " + cap.name + "? It will be allowed to:\n" + list)) { toggle.checked = false; return; }
      }
      const result = await api("/capabilities/enable", { name: cap.name, enabled: toggle.checked });
      if (!result.ok) addNotice(result.error || "Could not change that capability.", true);
      loadManifests();
    });
    label.append(toggle, document.createTextNode(" " + cap.name + (cap.version ? " " + cap.version : "")));
    top.append(label, el("span", "state" + (cap.status === "enabled" ? " ready" : ""), cap.status));
    r.append(top, el("div", "desc", cap.description));
    for (const p of cap.permissions) r.append(el("div", "perm" + (p.high_risk ? " high" : ""), "• " + p.text));
    if (cap.missing && cap.missing.length) r.append(el("div", "why", "Needs " + cap.missing.join(", ")));
    if (cap.status === "changed") r.append(el("div", "why", "Changed since you turned it on - toggle to re-approve."));
    if (cap.errors && cap.errors.length) r.append(el("div", "why", cap.errors.join("; ")));
    box.append(r);
  }
}

async function loadCapabilities() {
  loadManifests();
  const data = await api("/capabilities");
  const copy = Object.assign({}, data);
  delete copy.ok;
  $("#capabilities").textContent = JSON.stringify(copy, null, 2);
}

// ---------------------------------------------------------------- background jobs
const jobsView = { timer: 0, open: false, shots: {} };

function updateBadge(data) {
  const badge = $("#jobs-badge");
  if (!data || !data.ok) { badge.hidden = true; return; }
  const c = data.counts || {};
  const live = (c.queued || 0) + (c.starting || 0) + (c.working || 0) + (c.blocked || 0);
  badge.hidden = live === 0;
  badge.textContent = String(live);
  badge.classList.toggle("attention", (c.blocked || 0) > 0);
  badge.title = (c.blocked || 0) > 0 ? "A job is waiting for you" : live + " running";
}

function renderBackends(backends) {
  const box = $("#backends");
  box.replaceChildren();
  for (const [name, info] of Object.entries(backends || {})) {
    const b = el("div", "backend " + (info.available ? "ready" : "off"));
    b.append(el("b", "", name), document.createTextNode(info.detail || ""));
    box.append(b);
  }
}

async function loadShot(job, holder) {
  if (jobsView.shots[job.id]) { holder.src = jobsView.shots[job.id]; return; }
  const data = await api("/jobs/screenshot?id=" + encodeURIComponent(job.id)).catch(() => null);
  if (data && data.ok) { jobsView.shots[job.id] = data.image; holder.src = data.image; }
}

function renderJobs(jobs) {
  const list = $("#job-list");
  const openIds = new Set([...list.querySelectorAll("details[open]")].map((d) => d.dataset.id));
  list.replaceChildren();
  if (!jobs || !jobs.length) { list.append(el("p", "note", "No jobs yet.")); return; }
  for (const job of jobs) {
    const card = el("div", "job");
    const top = el("div", "job-top");
    top.append(el("span", "pill " + job.status, job.status), el("span", "job-title", job.title));
    if (!["done", "failed", "cancelled"].includes(job.status)) {
      const stop = el("button", "quiet", "Cancel");
      stop.type = "button";
      stop.addEventListener("click", async () => { renderAfter(await api("/jobs/cancel", { id: job.id })); });
      top.append(stop);
    }
    const where = job.backend + (job.agent && job.agent !== "cua" ? " · " + job.agent : "");
    card.append(top, el("div", "job-meta", where + " · started " + (job.started || "—") + (job.finished ? " · finished " + job.finished : "")));
    if (job.note) card.append(el("div", "job-meta", job.note));
    if (job.error) card.append(el("div", "err", job.error));
    if (job.output || job.screenshot) {
      const details = el("details");
      details.dataset.id = job.id;
      details.open = openIds.has(job.id);
      details.append(el("summary", "", "Output"));
      if (job.output) details.append(el("pre", "", job.output));
      if (job.screenshot) {
        const img = el("img");
        img.alt = "Virtual computer screenshot";
        details.append(img);
        loadShot(job, img);
      }
      card.append(details);
    }
    list.append(card);
  }
}

function renderAfter(data) {
  updateBadge(data);
  if (!data || !data.ok) return;
  renderBackends(data.backends);
  renderJobs(data.jobs);
}

async function refreshJobs() {
  const data = await api("/jobs").catch(() => null);
  updateBadge(data);
  if (jobsView.open && data && data.ok) renderAfter(data);
}

function syncJobForm() {
  const backend = $("#job-backend").value;
  const vm = backend === "cua";
  $("#job-agent-label").hidden = vm;
  const hermes = $("#job-agent").querySelector('option[value="hermes"]');
  if (hermes) hermes.disabled = backend !== "herdr";
  if (backend !== "herdr" && $("#job-agent").value === "hermes") $("#job-agent").value = "claude-code";
  $("#job-commands").hidden = !vm;
  $("#job-isolate").parentElement.hidden = vm;
}

function openJobs() {
  jobsView.open = true;
  $("#jobs").hidden = false;
  syncJobForm();
  refreshJobs();
  clearInterval(jobsView.timer);
  jobsView.timer = setInterval(refreshJobs, 3000);
  $("#job-prompt").focus();
}

function closeJobs() {
  jobsView.open = false;
  $("#jobs").hidden = true;
  clearInterval(jobsView.timer);
}

async function submitJob(event) {
  event.preventDefault();
  const backend = $("#job-backend").value;
  const body = {
    backend,
    prompt: $("#job-prompt").value.trim(),
    timeout_s: Number($("#job-timeout").value),
  };
  if (backend === "cua") body.commands = $("#job-commands").value;
  else { body.agent = $("#job-agent").value; body.isolate = $("#job-isolate").checked; }
  $("#job-result").textContent = "Starting…";
  const data = await api("/jobs", body).catch((e) => ({ ok: false, error: String(e) }));
  $("#job-result").textContent = data.ok ? "Started job " + data.id : (data.error || "Could not start the job.");
  if (data.ok) { $("#job-prompt").value = ""; $("#job-commands").value = ""; renderAfter(data); }
}

// ---------------------------------------------------------------- wiring
function autosize() {
  const t = $("#prompt");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 220) + "px";
}

function wire() {
  $("#composer").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = $("#prompt").value;
    $("#prompt").value = "";
    autosize();
    send(text);
  });
  $("#prompt").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("#composer").requestSubmit();
    }
  });
  $("#prompt").addEventListener("input", autosize);
  $("#stop").addEventListener("click", async () => {
    await api("/cancel", {});
    setStatus("Stopping…");
  });
  $("#new-chat").addEventListener("click", newChat);
  for (const button of document.querySelectorAll(".modes button")) {
    button.addEventListener("click", async () => {
      const data = await api("/mode", { mode: button.dataset.mode });
      if (data.ok) markMode(data.mode);
    });
  }
  $("#model-select").addEventListener("change", async (event) => {
    const data = await api("/model", { model: event.target.value });
    if (!data.ok) addNotice(data.error || "Could not switch model.", true);
    else if (data.resolved && data.resolved !== data.current) setStatus("Using " + data.resolved, true);
  });
  $("#open-settings").addEventListener("click", openSettings);
  $("#open-jobs").addEventListener("click", openJobs);
  if (window.LokiBrain) {
    window.LokiBrain.init(api);
    $("#open-brain").addEventListener("click", () => window.LokiBrain.open());
    $("#close-brain").addEventListener("click", () => window.LokiBrain.close());
  }
  $("#close-jobs").addEventListener("click", closeJobs);
  $("#jobs").addEventListener("click", (event) => { if (event.target === $("#jobs")) closeJobs(); });
  $("#job-form").addEventListener("submit", submitJob);
  $("#job-backend").addEventListener("change", syncJobForm);
  $("#clear-jobs").addEventListener("click", async () => renderAfter(await api("/jobs/clear", {})));
  $("#close-settings").addEventListener("click", () => { $("#settings").hidden = true; });
  $("#settings").addEventListener("click", (event) => { if (event.target === $("#settings")) $("#settings").hidden = true; });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") { $("#settings").hidden = true; closeJobs(); if (window.LokiBrain) window.LokiBrain.close(); } });
  for (const tab of document.querySelectorAll(".tabs button")) tab.addEventListener("click", () => showTab(tab.dataset.tab));
  $("#save-memory").addEventListener("click", async () => {
    const data = await api("/memory", { text: $("#memory-text").value });
    $("#save-memory").textContent = data.ok ? "Saved" : "Not saved";
    setTimeout(() => { $("#save-memory").textContent = "Save memory"; }, 1600);
  });
  $("#connect-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const provider = $("#connect-provider").value.trim();
    const key = $("#connect-key").value;
    $("#connect-result").textContent = "Checking the key…";
    const data = await api("/connect", { provider, key });
    $("#connect-key").value = "";
    $("#connect-result").textContent = data.ok ? (data.message || "Connected.") : (data.error || "Could not connect.");
    if (data.ok) loadConnections();
  });
}

async function start() {
  wire();
  state.token = readToken();
  if (!state.token) {
    setStatus("No engine token", false);
    addNotice("Open Loki from the Loki app so it can connect to its engine.", true);
    return;
  }
  // The engine may still be starting (MCP servers, first-run setup): wait for it.
  for (let attempt = 0; attempt < 120; attempt++) {
    try { if (await loadHealth()) break; } catch (_) { /* not up yet */ }
    setStatus("Starting the Loki engine…");
    await new Promise((r) => setTimeout(r, 1000));
  }
  state.connected = true;
  setStatus("Ready", true);
  await Promise.all([loadModels(), loadMode(), loadConversations()]);
  setInterval(pollApproval, 1500);
  refreshJobs();
  setInterval(() => { if (!jobsView.open) refreshJobs(); }, 10000);
  $("#prompt").focus();
}

document.addEventListener("DOMContentLoaded", start);
