// LOKI Studio's window. No framework, no CDN, no inline script (CSP script-src 'self').
"use strict";

const S = { token: "", sid: "", after: 0, working: false, status: "", lastState: null, timer: 0, mode: "default", turn: 0,
  commands: [], models: null, sugg: [], suggAt: -1 };
const $ = (id) => document.getElementById(id);

const ICONS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  send: '<path d="M12 19.5V5M6 11l6-6 6 6"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  diff: '<path d="M7 4v10M2 9h10M14 15h8"/><rect x="13" y="3.5" width="8" height="8" rx="1.5"/><rect x="3" y="15" width="8" height="5.5" rx="1.5"/>',
  check: '<circle cx="12" cy="12" r="8.5"/><path d="M8 12.3l2.7 2.7L16.2 9.4"/>',
  ship: '<path d="M4 15.5l8 4 8-4-1.5-5.5h-13z"/><path d="M12 3v7M8.5 6.5L12 3l3.5 3.5"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
  power: '<path d="M12 3.5v8"/><path d="M7 6.5a7.5 7.5 0 1 0 10 0"/>',
  undo: '<path d="M9 7H4.5V2.5"/><path d="M4.8 7A8 8 0 1 1 4 13"/>',
  log: '<rect x="4.5" y="3.5" width="15" height="17" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  rewind: '<path d="M11 7l-5 5 5 5M18 7l-5 5 5 5"/>',
  fork: '<circle cx="6" cy="5" r="2"/><circle cx="18" cy="5" r="2"/><circle cx="12" cy="19" r="2"/><path d="M6 7v2a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3V7M12 12v5"/>',
  yes: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  no: '<path d="M6 6l12 12M18 6L6 18"/>',
};

function svg(name) {
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + (ICONS[name] || ICONS.plus) + "</svg>";
}

// Buttons with data-icon become icons; data-tip="Name|What it does" is the hover tooltip.
function iconize(root) {
  for (const b of (root || document).querySelectorAll("button[data-icon]:not([data-done])")) {
    b.dataset.done = "1";
    const [name] = (b.dataset.tip || b.textContent).split("|");
    b.setAttribute("aria-label", name.trim());
    const words = b.textContent.trim();
    b.innerHTML = svg(b.dataset.icon) + (b.classList.contains("icon") ? "" : "<span>" + esc(words) + "</span>");
  }
}

let tip = null;
function showTip(t) {
  const [name, what] = (t.dataset.tip || "").split("|");
  if (!name) return;
  if (!tip) { tip = document.createElement("div"); tip.className = "tip"; tip.setAttribute("role", "tooltip"); document.body.append(tip); }
  tip.replaceChildren();
  const b = document.createElement("b"); b.textContent = name; tip.append(b);
  if (what) { const s = document.createElement("span"); s.textContent = what; tip.append(s); }
  tip.hidden = false;
  const r = t.getBoundingClientRect();
  const inRail = t.closest(".rail");
  let x = inRail ? r.right + 10 : r.left + r.width / 2 - tip.offsetWidth / 2;
  let y = inRail ? r.top + r.height / 2 - tip.offsetHeight / 2 : r.bottom + 8;
  x = Math.max(6, Math.min(innerWidth - tip.offsetWidth - 6, x));
  y = Math.max(6, Math.min(innerHeight - tip.offsetHeight - 6, y));
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function hideTip() { if (tip) tip.hidden = true; }

function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

async function api(path, body) {
  const init = { headers: { Authorization: "Bearer " + S.token } };
  if (body !== undefined) { init.method = "POST"; init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
  const res = await fetch(path, init);
  const data = await res.json().catch(() => ({ ok: false, error: "HTTP " + res.status }));
  if (!res.ok || data.ok === false) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }

function diffView(text) {
  const box = el("div", "diff");
  for (const line of String(text || "(no changes)").split("\n")) {
    const row = el("div", "", line || " ");
    if (line.startsWith("diff --git")) row.className = "f";
    else if (line.startsWith("@@")) row.className = "h";
    else if (line.startsWith("+") && !line.startsWith("+++")) row.className = "a";
    else if (line.startsWith("-") && !line.startsWith("---")) row.className = "d";
    box.append(row);
  }
  return box;
}

// ------------------------------------------------------------------ mermaid (flowcharts), drawn here: no CDN, CSP 'self'
// graph TD|LR; nodes a[box] a(round) a([stadium]) a{choice} a["quoted"]; edges -->, ---, -.->, ==>, -->|label|, -- label -->.
function parseMermaid(src) {
  const lines = String(src).split(/\n|;/).map((l) => l.trim()).filter(Boolean);
  const head = (lines.shift() || "").match(/^(graph|flowchart)\s+(TD|TB|LR|RL|BT)?/i);
  if (!head) return null;
  const dir = (head[2] || "TD").toUpperCase();
  const nodes = new Map(); const edges = [];
  const node = (tok) => {
    const m = tok.trim().match(/^([\w.-]+)\s*(?:\(\[(.*?)\]\)|\[\((.*?)\)\]|\[(.*?)\]|\((.*?)\)|\{(.*?)\})?$/);
    if (!m) return null;
    const label = (m[2] || m[3] || m[4] || m[5] || m[6] || "").replace(/^"|"$/g, "");
    if (!nodes.has(m[1])) nodes.set(m[1], { id: m[1], label: label || m[1] });
    else if (label) nodes.get(m[1]).label = label;
    return m[1];
  };
  const EDGE = /\s*(-\.->|==>|-->|---|--\s*([^-]+?)\s*-->|--\s*([^-]+?)\s*->)\s*(?:\|([^|]*)\|)?\s*/;
  for (const line of lines) {
    if (/^(classDef|class|style|linkStyle|subgraph|end|%%)/.test(line)) continue;
    let rest = line; let from = null; let pending = { label: "", dash: false };
    while (rest) {
      const m = rest.match(EDGE);
      const tok = m ? rest.slice(0, m.index) : rest;
      const id = node(tok);
      if (from && id) edges.push({ from, to: id, label: pending.label, dash: pending.dash });
      if (!m) break;
      pending = { label: (m[4] || m[2] || m[3] || "").trim(), dash: m[1].startsWith("-.") };
      from = id; rest = rest.slice(m.index + m[0].length);
    }
  }
  return { dir, nodes: [...nodes.values()], edges };
}

function mermaidSvg(src) {
  const g = parseMermaid(src);
  if (!g || !g.nodes.length) return null;
  const level = new Map(g.nodes.map((n) => [n.id, 0]));
  for (let i = 0; i < g.nodes.length; i++) for (const e of g.edges) if (level.get(e.to) <= level.get(e.from) && e.from !== e.to) level.set(e.to, level.get(e.from) + 1);
  const cols = new Map();
  for (const n of g.nodes) { const l = level.get(n.id); if (!cols.has(l)) cols.set(l, []); cols.get(l).push(n); }
  const horiz = g.dir === "LR" || g.dir === "RL";
  const W = 150, H = 36, GX = horiz ? 70 : 24, GY = horiz ? 18 : 50;
  const pos = new Map(); let maxX = 0, maxY = 0;
  for (const [l, list] of cols) list.forEach((n, i) => {
    const x = horiz ? l * (W + GX) : i * (W + GX); const y = horiz ? i * (H + GY) : l * (H + GY);
    pos.set(n.id, { x: x + 8, y: y + 8 }); maxX = Math.max(maxX, x + W + 16); maxY = Math.max(maxY, y + H + 16);
  });
  const NS = "http://www.w3.org/2000/svg";
  const svgEl = document.createElementNS(NS, "svg");
  svgEl.setAttribute("viewBox", "0 0 " + maxX + " " + maxY); svgEl.setAttribute("width", maxX); svgEl.setAttribute("height", maxY);
  svgEl.setAttribute("role", "img"); svgEl.setAttribute("aria-label", "diagram");
  const add = (tag, attrs, text) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (text != null) e.textContent = text; svgEl.append(e); return e; };
  for (const e of g.edges) {
    const a = pos.get(e.from), b = pos.get(e.to); if (!a || !b) continue;
    const x1 = horiz ? a.x + W : a.x + W / 2, y1 = horiz ? a.y + H / 2 : a.y + H, x2 = horiz ? b.x : b.x + W / 2, y2 = horiz ? b.y + H / 2 : b.y;
    add("path", { d: "M" + x1 + " " + y1 + " C" + (horiz ? (x1 + x2) / 2 : x1) + " " + (horiz ? y1 : (y1 + y2) / 2) + " " + (horiz ? (x1 + x2) / 2 : x2) + " " + (horiz ? y2 : (y1 + y2) / 2) + " " + x2 + " " + y2,
      class: e.dash ? "dash" : "" });
    add("path", { d: "M" + x2 + " " + y2 + (horiz ? " l-6 -4 m6 4 l-6 4" : " l-4 -6 m4 6 l4 -6") });
    if (e.label) add("text", { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 3, "text-anchor": "middle" }, e.label.slice(0, 24));
  }
  for (const n of g.nodes) {
    const p = pos.get(n.id);
    add("rect", { x: p.x, y: p.y, width: W, height: H, rx: 8 });
    add("text", { x: p.x + W / 2, y: p.y + H / 2 + 4, "text-anchor": "middle" }, n.label.length > 22 ? n.label.slice(0, 21) + "..." : n.label);
  }
  return svgEl;
}

// Text with ```mermaid blocks drawn as diagrams.
function richText(cls, text) {
  const box = el("div", cls);
  const parts = String(text || "").split(/```mermaid\s*\n([\s\S]*?)```/);
  parts.forEach((part, i) => {
    if (i % 2 === 0) { if (part.trim()) box.append(document.createTextNode(part)); return; }
    const d = el("div", "mermaid"); const svgEl = mermaidSvg(part);
    if (svgEl) d.append(svgEl); else d.append(el("pre", "", part));
    box.append(d);
  });
  return box;
}

function when(t) { if (!t) return ""; const d = new Date(t * 1000); return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }

// ------------------------------------------------------------------ the rail
function renderState(st) {
  S.lastState = st;
  const nav = $("sessions");
  nav.replaceChildren();
  for (const s of st.sessions) {
    const b = el("button", "sess" + (s.id === S.sid ? " active" : ""));
    b.type = "button";
    b.append(el("b", "", s.title || s.id));
    const line = el("span");
    line.append(el("i", "badge " + (s.status || ""), s.status || ""), document.createTextNode(" " + (s.kind === "godot" ? "Godot " + (s.project || "") + " - " : "") + when(s.updated)));
    b.append(line);
    b.addEventListener("click", () => select(s.id));
    nav.append(b);
  }
  const d = st.driver || {};
  const box = $("driver");
  box.className = "driver " + (d.provider === "nvidia" ? "good" : "warn");
  box.replaceChildren(document.createTextNode(d.text || ""));
  if (d.how) {
    const how = el("div", "small", d.how);
    box.append(how);
  }
  const L = st.loki || {};
  $("loki-dot").className = "dot " + (L.running ? "up" : "down");
  $("loki-state").textContent = L.running ? "running" + (L.model ? " - " + L.model : "") : "not running";
  $("loki-version").textContent = (L.version || "") + (L.on_trial ? " (on trial)" : "") + (L.last_good ? " - last good " + String(L.last_good).slice(0, 10) : "");
  $("loki-start").dataset.tip = L.running ? "Restart LOKI|Restart LOKI's engine; the window reloads when it is back." : "Start LOKI|Start the LOKI app from your checkout.";
  $("loki-rollback").disabled = !L.can_roll_back;
  $("pin").textContent = st.pin && st.pin.commit ? "Studio runs from its pinned copy " + st.pin.commit : "Studio runs from " + (st.pin ? st.pin.running_from : "the checkout");
  const target = $("target"); const keep = target.value;
  target.replaceChildren(new Option("LOKI's code", ""));
  for (const e of st.editors || []) target.append(new Option("Godot: " + e.name + " (" + e.godot + ")", e.project));
  target.value = [...target.options].some((o) => o.value === keep) ? keep : "";
  $("editors").textContent = (st.editors || []).length ? (st.editors.length + " Godot editor" + (st.editors.length > 1 ? "s" : "") + " linked") : "no Godot editor linked";
}

async function loadModels() {
  if (S.models) return;
  try {
    S.models = (await api("/api/models")).models;
    const sel = $("model"); sel.replaceChildren();
    for (const m of S.models) sel.append(new Option(m.name + (m.ready === false ? " (not set up)" : ""), m.id));
  } catch (e) { S.models = null; }
}

async function refreshState() {
  try { renderState(await api("/api/state")); } catch (e) { $("driver").textContent = "Studio's server: " + e.message; }
}

// ------------------------------------------------------------------ one session
function select(sid) {
  S.sid = sid; S.after = 0;
  $("thread").replaceChildren();
  if (S.lastState) renderState(S.lastState);
  poll();
}

function approvalRow(e) {
  const row = el("div", "ev approval");
  row.dataset.approval = e.approval;
  row.append(el("div", "what", e.text));
  const yes = el("button", "ship", "Approve"); yes.type = "button";
  const no = el("button", "", "Deny"); no.type = "button";
  const answer = async (ok) => {
    yes.disabled = no.disabled = true;
    try { await api("/api/session/approve", { id: S.sid, approval: e.approval, yes: ok }); } catch (err) { alert(err.message); }
  };
  yes.addEventListener("click", () => answer(true));
  no.addEventListener("click", () => answer(false));
  row.append(yes, no);
  return row;
}

function questionRow(e) {
  const row = el("div", "ev question");
  row.dataset.question = e.question_id;
  row.append(el("div", "what", "LOKI asks: " + e.text));
  const answer = async (text) => {
    row.querySelectorAll("button, input").forEach((b) => { b.disabled = true; });
    try { await api("/api/session/answer", { id: S.sid, question: e.question_id, answer: text }); } catch (err) { alert(err.message); }
  };
  for (const o of e.options || []) { const b = el("button", "", o); b.type = "button"; b.addEventListener("click", () => answer(o)); row.append(b); }
  const free = el("input"); free.placeholder = "or type an answer, Enter";
  free.addEventListener("keydown", (k) => { if (k.key === "Enter" && free.value.trim()) answer(free.value.trim()); });
  row.append(free);
  return row;
}

function showTodos(todos) {
  const box = $("todos");
  box.hidden = !(todos && todos.length);
  box.replaceChildren(el("b", "", "Todos"));
  const ul = el("ul");
  for (const t of todos || []) ul.append(el("li", t.status, (t.status === "done" ? "done  " : t.status === "doing" ? "doing  " : "todo  ") + t.text));
  box.append(ul);
}

async function addShots(node, paths) {
  for (const p of paths || []) {
    try { const img = el("img", "shot"); img.alt = "screenshot"; img.src = (await api("/api/shot?path=" + encodeURIComponent(p))).data; node.append(img); } catch (err) { /* gone */ }
  }
}

function renderEvent(e) {
  const t = $("thread");
  $("empty") && $("empty").remove();
  let n;
  switch (e.type) {
    case "user": n = el("div", "ev user", e.text + (e.attachments ? "\n(" + e.attachments.join(", ") + ")" : "")); break;
    case "assistant": n = richText("ev assistant", e.text); break;
    case "command": n = richText("ev command", e.text); if (e.images) addShots(n, e.images); break;
    case "question": n = questionRow(e); break;
    case "answered": {
      const row = t.querySelector('[data-question="' + e.question_id + '"]');
      if (row) { row.classList.add("closed"); row.querySelectorAll("button, input").forEach((b) => b.remove()); row.append(el("b", "", "answered: " + e.text)); }
      return;
    }
    case "todos": showTodos(e.todos); return;
    case "checkpoint": case "mode": case "undo": n = el("div", "ev " + e.type, e.type === "mode" ? "Mode: " + e.text : e.text); break;
    case "thinking": {
      n = el("details", "ev thinking");
      n.append(el("summary", "", "thinking" + (e.provider ? " (" + e.provider + ")" : "")), el("div", "", e.text));
      break;
    }
    case "tool": n = el("div", "ev tool", "> " + e.text); break;
    case "result": {
      n = el("details", "ev result");
      const first = String(e.text || "").split("\n")[0].slice(0, 140);
      n.append(el("summary", "", first), el("pre", "", e.text));
      if (e.images && e.images.length) { n.open = true; addShots(n, e.images); }
      break;
    }
    case "diff": n = diffView(e.text); break;
    case "approval": n = approvalRow(e); break;
    case "approved": case "denied": {
      const row = t.querySelector('[data-approval="' + e.approval + '"]');
      if (row) { row.classList.add("closed"); row.querySelectorAll("button").forEach((b) => b.remove()); row.append(el("b", "", e.type)); }
      return;
    }
    case "check": case "ship": n = el("div", "ev " + e.type + ((e.passed || e.ok) ? " ok" : ""), e.text); break;
    case "error": n = el("div", "ev error", e.text + (e.how ? "\n\n" + e.how : "")); break;
    default: n = el("div", "ev " + (e.type === "status" ? "status" : "progress"), e.text);
  }
  t.append(n);
}

async function poll() {
  clearTimeout(S.timer);
  if (S.sid) {
    try {
      const data = await api("/api/session?id=" + encodeURIComponent(S.sid) + "&after=" + S.after);
      const t = $("thread");
      const atBottom = t.scrollHeight - t.scrollTop - t.clientHeight < 80;
      for (const e of data.events) { renderEvent(e); S.after = e.id; }
      if (atBottom && data.events.length) t.scrollTop = t.scrollHeight;
      S.working = data.working; S.status = data.session.status;
      $("title").textContent = data.session.title || "Session";
      $("sub").textContent = (data.session.branch || "") + (data.session.model ? " - " + data.session.model : "") + " - " + (data.session.status || "");
      const final = ["shipped", "discarded"].includes(S.status);
      $("act-stop").disabled = !S.working;
      $("act-diff").disabled = S.status === "discarded";
      $("act-check").disabled = S.working || final;
      $("act-ship").disabled = S.working || final;
      $("act-discard").disabled = S.status === "discarded";
      const sess = data.session;
      S.turn = sess.turn || 0; S.kind = sess.kind || "loki";
      $("act-undo").disabled = S.working || final || S.turn < 1;
      $("act-fork").disabled = S.status === "discarded";
      $("act-ship").hidden = $("act-check").hidden = S.kind === "godot";
      setMode(sess.mode || "default");
      $("ask-edits").checked = !!sess.approve_edits;
      if (sess.model_pref && $("model").value !== sess.model_pref) $("model").value = sess.model_pref;
      if (sess.kind === "godot") $("sub").textContent = "Godot: " + (sess.project || "") + " - " + (sess.root || "") + " - turn " + S.turn
        + (sess.queued ? " - " + sess.queued + " queued" : "") + " - " + (sess.status || "");
      showTodos(sess.todos);
      const target = $("target"); const want = sess.kind === "godot" ? sess.root : "";
      if (![...target.options].some((o) => o.value === want)) target.append(new Option("Godot: " + (sess.project || want), want));
      target.value = want; target.disabled = true;     // a session keeps what it works on; New session picks again
    } catch (e) { /* the server restarts: try again */ }
  }
  S.timer = setTimeout(poll, S.working ? 900 : 2500);
}

async function send(text) {
  text = String(text || "").trim();
  if (!text) return;
  $("prompt").value = "";
  try {
    if (S.sid && !["shipped", "discarded"].includes(S.status)) await api("/api/session/send", { id: S.sid, text });
    else {
      const r = await api("/api/session/new", { text, mode: S.mode, model: $("model").value || "auto", project: $("target").value,
        approve_edits: $("ask-edits").checked });
      select(r.session.id);
    }
  } catch (e) { alert(e.message); }
  hideSuggest(); refreshState(); poll();
}

function setMode(mode) {
  S.mode = mode;
  for (const b of document.querySelectorAll("#modes button")) b.classList.toggle("on", b.dataset.mode === mode);
}

// ------------------------------------------------------------------ /commands and @mentions
function hideSuggest() { $("suggest").hidden = true; S.sugg = []; S.suggAt = -1; }

function showSuggest(items, apply) {
  const box = $("suggest");
  box.replaceChildren();
  S.sugg = items.slice(0, 12).map((it) => ({ ...it, apply }));
  S.suggAt = S.sugg.length ? 0 : -1;
  S.sugg.forEach((it, i) => {
    const li = el("li", i === 0 ? "on" : "", it.label); li.setAttribute("role", "option");
    li.addEventListener("mousedown", (ev) => { ev.preventDefault(); it.apply(it.value); });
    box.append(li);
  });
  box.hidden = !S.sugg.length;
}

async function onPromptInput() {
  const ta = $("prompt"); const before = ta.value.slice(0, ta.selectionStart);
  const word = (before.match(/(\S*)$/) || ["", ""])[1];
  if (/^\/[\w-]*$/.test(ta.value.trim()) && before === ta.value) {
    if (!S.commands.length || S.commandsFor !== S.sid) {
      try { S.commands = (await api("/api/commands" + (S.sid ? "?id=" + encodeURIComponent(S.sid) : ""))).commands; S.commandsFor = S.sid; } catch (e) { return; }
    }
    const q = word.slice(1);
    showSuggest(S.commands.filter((c) => c.name.startsWith(q)).map((c) => ({ label: "/" + c.name + " - " + c.description, value: "/" + c.name + " " })),
      (v) => { ta.value = v; hideSuggest(); ta.focus(); });
  } else if (word.startsWith("@") && word.length > 1) {
    const q = word.slice(1);
    const where = S.sid ? "id=" + encodeURIComponent(S.sid) : "project=" + encodeURIComponent($("target").value || "");
    try {
      const items = (await api("/api/mentions?q=" + encodeURIComponent(q) + "&" + where)).items;
      showSuggest(items.map((p) => ({ label: "@" + p, value: p })), (v) => {
        const start = ta.selectionStart - word.length;
        ta.value = ta.value.slice(0, start) + "@" + v + " " + ta.value.slice(ta.selectionStart);
        hideSuggest(); ta.focus();
      });
    } catch (e) { hideSuggest(); }
  } else hideSuggest();
}

function side(title, node) {
  $("side-title").textContent = title;
  const body = $("side-body");
  body.replaceChildren(node);
  $("side").hidden = false;
}

// ------------------------------------------------------------------ wiring
document.addEventListener("DOMContentLoaded", () => {
  S.token = (location.hash.match(/token=([^&]+)/) || [])[1] || "";
  iconize();
  $("composer").addEventListener("submit", (e) => { e.preventDefault(); send($("prompt").value); });
  $("prompt").addEventListener("keydown", (e) => {
    if (!$("suggest").hidden && ["ArrowDown", "ArrowUp", "Tab", "Escape"].includes(e.key)) {
      e.preventDefault();
      if (e.key === "Escape") return hideSuggest();
      if (e.key === "Tab") return S.sugg[S.suggAt] && S.sugg[S.suggAt].apply(S.sugg[S.suggAt].value);
      S.suggAt = (S.suggAt + (e.key === "ArrowDown" ? 1 : S.sugg.length - 1)) % S.sugg.length;
      [...$("suggest").children].forEach((li, i) => li.classList.toggle("on", i === S.suggAt));
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!$("suggest").hidden && S.sugg[S.suggAt] && !$("prompt").value.trim().includes(" ")) return S.sugg[S.suggAt].apply(S.sugg[S.suggAt].value);
      send($("prompt").value);
    }
  });
  $("prompt").addEventListener("input", onPromptInput);
  $("prompt").addEventListener("blur", () => setTimeout(hideSuggest, 150));
  for (const b of document.querySelectorAll("#modes button")) b.addEventListener("click", async () => {
    setMode(b.dataset.mode);
    if (S.sid) { try { await api("/api/session/mode", { id: S.sid, mode: b.dataset.mode }); poll(); } catch (err) { alert(err.message); } }
  });
  $("model").addEventListener("change", () => { if (S.sid) api("/api/session/model", { id: S.sid, model: $("model").value }).then(poll).catch((e) => alert(e.message)); });
  $("ask-edits").addEventListener("change", () => { if (S.sid) api("/api/session/approve_edits", { id: S.sid, on: $("ask-edits").checked }).catch((e) => alert(e.message)); });
  $("act-undo").addEventListener("click", async () => {
    if (!confirm("Undo turn " + S.turn + "? The files go back to how they were before it (and its Godot editor changes are undone).")) return;
    try { await api("/api/session/undo", { id: S.sid, turn: S.turn }); } catch (e) { alert(e.message); }
    poll();
  });
  $("act-fork").addEventListener("click", async () => {
    try { const r = await api("/api/session/fork", { id: S.sid }); select(r.session.id); refreshState(); } catch (e) { alert(e.message); }
  });
  loadModels();
  for (const c of document.querySelectorAll(".chip")) c.addEventListener("click", () => { $("prompt").value = c.dataset.prompt; $("prompt").focus(); });
  $("new-session").addEventListener("click", () => { S.sid = ""; S.status = ""; $("thread").replaceChildren(); $("title").textContent = "New session"; $("sub").textContent = "Type what to build or fix. On LOKI's code it gets its own worktree; on a Godot project it works live in the editor."; $("target").disabled = false; showTodos([]); $("prompt").focus(); });
  $("act-stop").addEventListener("click", () => api("/api/session/stop", { id: S.sid }).catch((e) => alert(e.message)));
  $("act-diff").addEventListener("click", async () => { try { side("Diff", diffView((await api("/api/session/diff?id=" + encodeURIComponent(S.sid))).diff)); } catch (e) { alert(e.message); } });
  $("act-check").addEventListener("click", () => api("/api/session/check", { id: S.sid }).then(poll).catch((e) => alert(e.message)));
  $("act-ship").addEventListener("click", () => { $("ship-message").value = "LOKI Studio: " + ($("title").textContent || ""); $("ship-dialog").showModal(); });
  $("ship-cancel").addEventListener("click", () => $("ship-dialog").close());
  $("ship-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("ship-dialog").close();
    try { await api("/api/session/ship", { id: S.sid, message: $("ship-message").value, confirm: true }); poll(); } catch (err) { alert(err.message); }
  });
  $("act-discard").addEventListener("click", async () => {
    if (!confirm("Discard this session's worktree and branch? The conversation stays in the list.")) return;
    try { await api("/api/session/discard", { id: S.sid, confirm: true }); refreshState(); poll(); } catch (e) { alert(e.message); }
  });
  $("loki-start").addEventListener("click", async () => {
    const running = S.lastState && S.lastState.loki && S.lastState.loki.running;
    if (!confirm(running ? "Restart LOKI's engine now?" : "Start LOKI now?")) return;
    try { const r = await api(running ? "/api/loki/restart" : "/api/loki/start", { confirm: true }); alert(r.note || r.error || "ok"); } catch (e) { alert(e.message); }
    setTimeout(refreshState, 1500);
  });
  $("loki-rollback").addEventListener("click", async () => {
    if (!confirm("Roll LOKI back to the last version that worked on this computer? Nothing is pushed; your local edits are kept.")) return;
    try { const r = await api("/api/loki/rollback", { confirm: true }); alert(r.note || r.error || "done"); } catch (e) { alert(e.message); }
    refreshState();
  });
  $("loki-logs").addEventListener("click", async () => {
    try {
      const parts = [];
      for (const which of ["engine", "app", "bridge"]) parts.push("==== " + which + " ====\n" + (await api("/api/loki/logs?which=" + which + "&lines=120")).text);
      side("LOKI's logs", document.createTextNode(parts.join("\n\n")));
    } catch (e) { alert(e.message); }
  });
  $("side-close").addEventListener("click", () => { $("side").hidden = true; });
  document.addEventListener("mouseover", (e) => { const t = e.target.closest && e.target.closest("[data-tip]"); if (t) showTip(t); else hideTip(); });
  document.addEventListener("focusin", (e) => { const t = e.target.closest && e.target.closest("[data-tip]"); if (t) showTip(t); });
  document.addEventListener("focusout", hideTip);
  refreshState();
  setInterval(refreshState, 4000);
  const first = new URLSearchParams(location.hash.slice(1)).get("session");
  if (first) select(first); else poll();
});
