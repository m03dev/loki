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

const EVENT_LABELS = { triage: "First layer", tool: "Tool", tool_result: "Result", task: "Task", done: "Done", error: "Error", approval: "Permission" };

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

function setView(view) {
  const home = view === "home";
  $("#main").classList.toggle("home", home);
  // Home is just the world and the word "Loki"; the chat box appears when it is clicked.
  if (home) $("#main").classList.remove("summoned");
  const welcome = $("#welcome");
  if (welcome) welcome.hidden = !home;
  if (home) {
    $("#chat-title").textContent = "Loki";
    $("#prompt").placeholder = "Ask Loki anything, or describe what to build";
  } else {
    $("#prompt").placeholder = "Message Loki";
  }
}

function showHome() { setView("home"); }

function summon(open) {
  const main = $("#main");
  main.classList.toggle("summoned", open);
  if (open) setTimeout(() => $("#prompt").focus(), 0);
}
function showChat() { setView("chat"); }

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
  if (state.busy) return;
  applyConversations(await api("/conversations/switch", { id }));
  showChat();
}

async function newChat() {
  if (state.busy) return;
  applyConversations(await api("/conversations", { title: "" }));
  showHome();
  renderMessages([]);
  summon(true);   // they asked for a new chat: open the box straight away
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
  const background = $("#in-background") && $("#in-background").checked;
  if ($("#main").classList.contains("home")) {
    // Reuse the current chat when it is still empty; otherwise start a new one.
    const current = (state.conversations || []).find((c) => c.id === state.active);
    const empty = current && !(current.count || current.messages || current.turns) && /^(new chat)?$/i.test(current.title || "");
    if (!empty) applyConversations(await api("/conversations", { title: "" }));
    showChat();
    $("#transcript").replaceChildren();
  }
  if (background) { $("#in-background").checked = false; return sendToBackground(text); }
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
      if (data.usage && typeof showMeter === "function") showMeter(data.usage);
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

// ---------------------------------------------------------------- model picker
// One button at the top: "Smart · Gemini". It opens a menu with Smart first (and what it
// would use right now), then the models LOKI can use right now, grouped by cost; models
// that still need a key or a download are tucked under "Not set up" with one click to
// Connections. Picking one switches at once.
const modelMenu = { data: null, showAll: false };

async function loadModels() {
  const data = await api("/models").catch(() => null);
  if (!data || !data.ok) return;
  modelMenu.data = data;
  paintModelButton();
  if (!$("#model-menu").hidden) renderModelMenu();
}

function modelLabel(name) {
  const entry = ((modelMenu.data || {}).entries || []).find((e) => e.name === name);
  return entry ? entry.label : name;
}

function paintModelButton() {
  const data = modelMenu.data;
  if (!data) return;
  const auto = data.current === "smart" || data.current === "online";
  const text = auto ? modelLabel(data.current) + (data.resolved_label ? " · " + data.resolved_label : "")
    : modelLabel(data.current);
  $("#model-button-text").textContent = text;
  $("#model-button").title = auto ? "LOKI picks the model. Right now: " + (data.resolved_label || "—") : "Pinned to " + text;
}

function renderModelMenu() {
  const data = modelMenu.data || { entries: [], groups: [] };
  const menu = $("#model-menu");
  menu.replaceChildren();
  const item = (entry) => {
    const b = el("button", "model-item" + (entry.name === data.current ? " current" : "") + (entry.ready ? "" : " not-ready"));
    b.type = "button";
    b.setAttribute("role", "menuitemradio");
    b.setAttribute("aria-checked", String(entry.name === data.current));
    const top = el("span", "model-item-top");
    top.append(el("span", "model-item-name", entry.label));
    if (entry.using) top.append(el("span", "model-item-using", "now: " + entry.using));
    else if (!entry.ready) top.append(el("span", "model-item-using", "set up"));
    else if (entry.model && entry.group !== "auto") top.append(el("span", "model-item-using", entry.model));
    b.append(top);
    if (entry.blurb && (entry.group === "auto" || !entry.ready)) b.append(el("span", "model-item-blurb", entry.blurb));
    b.addEventListener("click", () => (entry.ready ? chooseModel(entry.name) : openConnections()));
    return b;
  };
  const entries = data.entries || [];
  for (const group of data.groups || []) {
    const rows = entries.filter((e) => e.group === group.id && e.ready);
    if (!rows.length) continue;
    menu.append(el("div", "model-group", group.label));
    for (const e of rows) menu.append(item(e));
  }
  const rest = entries.filter((e) => !e.ready);
  if (rest.length) {
    const more = el("button", "model-more", (modelMenu.showAll ? "Hide" : "Show") + " " + rest.length + " not set up");
    more.type = "button";
    more.addEventListener("click", (ev) => { ev.stopPropagation(); modelMenu.showAll = !modelMenu.showAll; renderModelMenu(); });
    menu.append(more);
    if (modelMenu.showAll) for (const e of rest) menu.append(item(e));
  }
  const foot = el("div", "model-foot");
  const connect = el("button", "quiet small", "Connect a provider…");
  connect.type = "button";
  connect.addEventListener("click", openConnections);
  const local = el("button", "quiet small", "Local models…");
  local.type = "button";
  local.addEventListener("click", () => { closeModelMenu(); openSettings(); showTab("models"); });
  foot.append(connect, local);
  menu.append(foot);
}

function openConnections() { closeModelMenu(); openSettings(); showTab("connections"); }

function toggleModelMenu(force) {
  const menu = $("#model-menu");
  const open = force === undefined ? menu.hidden : force;
  menu.hidden = !open;
  $("#model-button").setAttribute("aria-expanded", String(open));
  if (open) { renderModelMenu(); loadModels(); const first = menu.querySelector(".model-item.current, .model-item"); if (first) first.focus(); }
}
function closeModelMenu() { toggleModelMenu(false); }

async function chooseModel(name) {
  closeModelMenu();
  const data = await api("/model", { model: name }).catch(() => null);
  if (!data || !data.ok) { addNotice((data && data.error) || "Could not switch model.", true); return; }
  if (modelMenu.data) { modelMenu.data.current = data.current; modelMenu.data.resolved = data.resolved; modelMenu.data.resolved_label = modelLabel(data.resolved); }
  paintModelButton();
  setStatus("Using " + modelLabel(data.resolved || name), true);
  loadModels();
}

async function loadHealth() {
  const data = await api("/health");
  if (!data.ok) return false;
  $("#workspace").textContent = data.workspace || "";
  $("#workspace").title = "Workspace: " + (data.workspace || "");
  showVersion(data.update || {});
  return true;
}

// Every machine runs the same LOKI (engine/updater.py). Show the version, and say when
// GitHub has a newer one that the next start will apply.
function showVersion(u) {
  const box = $("#version");
  if (!box) return;
  const commit = u.commit ? u.commit.slice(0, 7) : "";
  window.LOKI_VERSION = u.commit || "";
  // "LOKI v0.16 · patch 412" - the version and the patch, side by side, everywhere.
  const label = u.label || (commit ? "LOKI " + commit : "");
  box.textContent = label ? (label.startsWith("v") ? "LOKI " + label : label) : "";
  const summon = $("#summon-version");
  if (summon) summon.textContent = label;
  const problem = u.problem || "";
  box.classList.toggle("attention", !!u.update_available || !!problem);
  box.classList.toggle("problem", !!problem);
  box.title = problem ? "Updates are not working: " + (u.error || problem) + " (click for details)"
    : u.update_available
      ? "A newer LOKI is on GitHub (" + (u.latest || "").slice(0, 7) + "). Quit and reopen LOKI to use it."
      : (u.note || "Up to date with GitHub") + (commit ? " · " + commit : "");
  if (problem) box.textContent += " · update problem";
  else if (u.update_available) box.textContent += " · update waiting";
  if (typeof checkUpdateBanner === "function") checkUpdateBanner(u);
}

// ---------------------------------------------------------------- settings
async function openSettings() {
  $("#settings").hidden = false;
  showTab("system");
  $("#close-settings").focus();
}

function showTab(name) {
  for (const tab of document.querySelectorAll(".tabs button")) tab.setAttribute("aria-selected", String(tab.dataset.tab === name));
  for (const panel of document.querySelectorAll("[data-panel]")) panel.hidden = panel.dataset.panel !== name;
  if (name === "system" && typeof loadSystemCheck === "function") loadSystemCheck();
  if (name === "connections") { loadConnections(); if (typeof loadPortal === "function") loadPortal(); }
  if (name === "general" && typeof loadGeneral === "function") loadGeneral();
  if (name === "agents" && typeof loadAgents === "function") loadAgents();
  if (name === "world" && typeof showWorldPanel === "function") showWorldPanel();
  if (name !== "world" && typeof hideWorldPanel === "function") hideWorldPanel();
  if (name === "machines" && typeof loadUpdatePanel === "function") loadUpdatePanel();
  if (name === "tools") loadCategories();
  if (name === "memory") loadMemory();
  if (name === "capabilities") loadCapabilities();
  if (name === "models" && typeof loadModelsTab === "function") loadModelsTab();
  if (name === "usage" && typeof loadUsageTab === "function") loadUsageTab();
  if (name === "machines" && typeof loadMachines === "function") loadMachines();
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
  // Providers have their own cards in the portal; this list keeps the local tools LOKI sees.
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
      checkChangedCapabilities();
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

// An add-on whose manifest changed after it was turned on is off until the owner OKs it
// again (engine/manifests.py). Say so up front instead of leaving it to be found in
// Settings > Add-ons: a banner names it, and one click shows what it may do and re-approves.
const changedCaps = { list: [], dismissed: false };

async function checkChangedCapabilities() {
  const data = await api("/capabilities/manifests").catch(() => null);
  const banner = $("#changed-banner");
  if (!banner) return;
  changedCaps.list = data && data.ok ? (data.capabilities || []).filter((c) => c.status === "changed") : [];
  if (!changedCaps.list.length || changedCaps.dismissed) { banner.hidden = true; return; }
  const names = changedCaps.list.map((c) => c.name).join(", ");
  $("#changed-banner-text").textContent = names + (changedCaps.list.length > 1 ? " have" : " has")
    + " changed since you turned it on, so it is off until you OK it again.";
  banner.hidden = false;
}

async function reapproveChangedCapabilities() {
  for (const cap of changedCaps.list) {
    const list = (cap.permissions || []).map((p) => "- " + p.text).join("\n") || "- (no special permissions)";
    if (!confirm(cap.name + " changed since you turned it on. Turn it back on? It will be allowed to:\n" + list)) continue;
    const result = await api("/capabilities/enable", { name: cap.name, enabled: true }).catch(() => null);
    if (!result || !result.ok) addNotice((result && result.error) || ("Could not turn " + cap.name + " back on."), true);
  }
  await checkChangedCapabilities();
  if (!$("#settings").hidden) loadManifests();
}

function wireChangedBanner() {
  const go = $("#changed-banner-go");
  if (go) go.addEventListener("click", reapproveChangedCapabilities);
  const later = $("#changed-banner-later");
  if (later) later.addEventListener("click", () => { changedCaps.dismissed = true; $("#changed-banner").hidden = true; });
}

async function loadCapabilities() {
  loadManifests();
  const data = await api("/capabilities");
  const copy = Object.assign({}, data);
  delete copy.ok;
  $("#capabilities").textContent = JSON.stringify(copy, null, 2);
}

// ---------------------------------------------------------------- work in progress
// Background work is part of the conversation, not a separate tab: whatever agents are
// running (started by Loki itself or with "Run in background") shows in a strip above the
// message box, with its status, machine, output and screenshots.
const jobsView = { timer: 0, shots: {}, collapsed: false, live: 0 };
const LIVE = ["queued", "starting", "working", "blocked"];

async function loadShot(job, holder) {
  if (jobsView.shots[job.id]) { holder.src = jobsView.shots[job.id]; return; }
  const data = await api("/jobs/screenshot?id=" + encodeURIComponent(job.id)).catch(() => null);
  if (data && data.ok) { jobsView.shots[job.id] = data.image; holder.src = data.image; }
}

function jobWhere(job) {
  const agent = job.agent && job.agent !== "cua" ? job.agent : "";
  const machine = job.backend === "cua" ? "virtual computer" : job.machine || "this computer";
  return [agent === "loki" ? "Loki agent" : agent, machine].filter(Boolean).join(" · ");
}

function renderJobs(jobs) {
  const list = $("#job-list");
  const openIds = new Set([...list.querySelectorAll("details[open]")].map((d) => d.dataset.id));
  list.replaceChildren();
  renderTeams(list);
  for (const d of list.querySelectorAll("details")) d.open = openIds.has(d.dataset.id);
  for (const job of jobs) {
    const card = el("div", "job");
    const top = el("div", "job-top");
    top.append(el("span", "pill " + job.status, job.status), el("span", "job-title", job.title));
    if (LIVE.includes(job.status)) {
      const stop = el("button", "quiet small", "Stop");
      stop.type = "button";
      stop.addEventListener("click", async () => { renderWork(await api("/jobs/cancel", { id: job.id })); });
      top.append(stop);
    }
    card.append(top, el("div", "job-meta", jobWhere(job) + " · started " + (job.started || "—") + (job.finished ? " · finished " + job.finished : "")));
    if (job.note) card.append(el("div", "job-meta", job.note));
    if (job.error) card.append(el("div", "err", job.error));
    if (job.output || job.screenshot) {
      const details = el("details");
      details.dataset.id = job.id;
      details.open = openIds.has(job.id);
      details.append(el("summary", "", job.screenshot ? "Output and screen" : "Output"));
      if (job.output) details.append(el("pre", "", job.output));
      if (job.screenshot) {
        const img = el("img");
        img.alt = "Screen of " + job.title;
        details.append(img);
        details.addEventListener("toggle", () => { if (details.open) loadShot(job, img); });
        if (details.open) loadShot(job, img);
      }
      card.append(details);
    }
    list.append(card);
  }
}

function renderWork(data) {
  if (!data || !data.ok) return;
  const jobs = data.jobs || [];
  const c = data.counts || {};
  const live = LIVE.reduce((n, k) => n + (c[k] || 0), 0);
  jobsView.live = live;
  const teamsLive = (jobsView.teams || []).filter((t) => t.status === "working").length;
  $("#work").hidden = jobs.length === 0 && !(jobsView.teams || []).length;
  const blocked = c.blocked || 0;
  $("#work-summary").textContent = (live
    ? (live === 1 ? "1 agent working" : live + " agents working") + (blocked ? " · " + blocked + " waiting for you" : "")
    : "Background work finished") + (teamsLive ? " · " + teamsLive + (teamsLive === 1 ? " team" : " teams") : "");
  $("#work").classList.toggle("attention", blocked > 0);
  $("#work").classList.toggle("collapsed", jobsView.collapsed);
  $("#work-toggle").setAttribute("aria-expanded", String(!jobsView.collapsed));
  renderJobs(jobs);
  // Poll fast while something runs, slowly otherwise.
  clearInterval(jobsView.timer);
  jobsView.timer = setInterval(refreshJobs, live ? 3000 : 10000);
}

async function refreshJobs() {
  const [jobs, teams] = await Promise.all([api("/jobs").catch(() => null), api("/teams").catch(() => null)]);
  jobsView.teams = (teams && teams.ok) ? teams.teams || [] : [];
  renderWork(jobs);
}

// A team: its stage, its members and the last notes on its board.
function renderTeams(list) {
  const recent = (jobsView.teams || []).filter((t) => t.status === "working" || (Date.now() / 1000 - (t.finished || 0)) < 3600);
  for (const team of recent) {
    const card = el("div", "job team");
    const top = el("div", "job-top");
    top.append(el("span", "pill " + (team.status === "working" ? "working" : "done"), team.status === "working" ? (team.stage || "starting") : "done"),
               el("span", "job-title", "Team: " + team.goal));
    if (team.status === "working") {
      const stop = el("button", "quiet small", "Stop team");
      stop.type = "button";
      stop.addEventListener("click", async () => { await api("/teams/cancel", { id: team.id }); refreshJobs(); });
      top.append(stop);
    }
    card.append(top);
    const who = (team.members || []).map((m) => m.role + (m.round ? " (" + m.round + ")" : "") + ": " + (m.status || "waiting"));
    card.append(el("div", "job-meta", (team.roles || []).join(" → ") + (who.length ? " · " + who.join(", ") : "")));
    if (team.verdict) card.append(el("div", "job-meta", team.verdict));
    if ((team.board || []).length) {
      const details = el("details");
      details.dataset.id = "team-" + team.id;
      details.append(el("summary", "", "Team board (" + team.board.length + ")"));
      details.append(el("pre", "", team.board.slice(-12).map((m) => m.from + " → " + m.to + ": " + m.text).join("\n\n")));
      card.append(details);
    }
    list.append(card);
  }
  return recent.length;
}

async function sendToBackground(text) {
  addUser(text);
  const data = await api("/jobs", { backend: "local", agent: "loki", prompt: text, isolate: true, timeout_s: 3600 })
    .catch((e) => ({ ok: false, error: String(e) }));
  if (data.ok) {
    addLoki("Started a background agent on this. You can keep chatting; its progress is shown above the message box.");
    jobsView.collapsed = false;
    renderWork(data);
  } else {
    addNotice(data.error || "Could not start the background agent.", true);
  }
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
  for (const chip of document.querySelectorAll(".welcome-chips .chip")) {
    chip.addEventListener("click", () => send(chip.dataset.prompt || chip.textContent));
  }
  for (const button of document.querySelectorAll(".modes button")) {
    button.addEventListener("click", async () => {
      const data = await api("/mode", { mode: button.dataset.mode });
      if (data.ok) markMode(data.mode);
    });
  }
  $("#model-button").addEventListener("click", (ev) => { ev.stopPropagation(); toggleModelMenu(); });
  $("#model-menu").addEventListener("click", (ev) => ev.stopPropagation());
  document.addEventListener("click", () => { if (!$("#model-menu").hidden) closeModelMenu(); });
  $("#summon").addEventListener("click", () => summon(true));
  $("#version").addEventListener("click", () => { openSettings(); showTab("machines"); });
  document.addEventListener("keydown", (ev) => {
    // On the home screen, just start typing: the chat box opens with that key in it.
    const main = $("#main");
    if (ev.key.length === 1 && !ev.metaKey && !ev.ctrlKey && !ev.altKey && main.classList.contains("home")
        && !main.classList.contains("summoned") && !/^(INPUT|TEXTAREA|SELECT)$/.test((ev.target || {}).tagName || "")
        && $("#settings").hidden) {
      ev.preventDefault();
      summon(true);
      const prompt = $("#prompt");
      prompt.value += ev.key;
      prompt.focus();
      return;
    }
    if (ev.key !== "Escape") return;
    if (!$("#model-menu").hidden) { closeModelMenu(); $("#model-button").focus(); return; }
    if (main.classList.contains("home") && main.classList.contains("summoned") && !$("#prompt").value.trim()) summon(false);
  });
  $("#open-settings").addEventListener("click", openSettings);
  $("#work-toggle").addEventListener("click", () => {
    jobsView.collapsed = !jobsView.collapsed;
    $("#work").classList.toggle("collapsed", jobsView.collapsed);
    $("#work-toggle").setAttribute("aria-expanded", String(!jobsView.collapsed));
  });
  $("#clear-jobs").addEventListener("click", async () => renderWork(await api("/jobs/clear", {})));
  $("#close-settings").addEventListener("click", () => {
    $("#settings").hidden = true;
    if (typeof hideWorldPanel === "function") hideWorldPanel();
  });
  $("#settings").addEventListener("click", (event) => { if (event.target === $("#settings")) $("#settings").hidden = true; });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if ($("#qr-modal") && !$("#qr-modal").hidden) { $("#qr-modal").hidden = true; return; }
    $("#settings").hidden = true;
    if (typeof hideWorldPanel === "function") hideWorldPanel();
  });
  for (const tab of document.querySelectorAll(".tabs button")) tab.addEventListener("click", () => showTab(tab.dataset.tab));
  $("#save-memory").addEventListener("click", async () => {
    const data = await api("/memory", { text: $("#memory-text").value });
    $("#save-memory").textContent = data.ok ? "Saved" : "Not saved";
    setTimeout(() => { $("#save-memory").textContent = "Save memory"; }, 1600);
  });
  // Connecting providers lives in the Connections portal now (settings.js).
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
  wireChangedBanner();
  checkChangedCapabilities();
  if (typeof afterStart === "function") afterStart();
  showHome();     // just the world and the word "Loki" until it is clicked
}

document.addEventListener("DOMContentLoaded", start);
