// LOKI Studio's window. No framework, no CDN, no inline script (CSP script-src 'self').
"use strict";

const S = { token: "", sid: "", after: 0, working: false, status: "", lastState: null, timer: 0 };
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
    line.append(el("i", "badge " + (s.status || ""), s.status || ""), document.createTextNode(" " + when(s.updated)));
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

function renderEvent(e) {
  const t = $("thread");
  $("empty") && $("empty").remove();
  let n;
  switch (e.type) {
    case "user": n = el("div", "ev user", e.text); break;
    case "assistant": n = el("div", "ev assistant", e.text); break;
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
    else { const r = await api("/api/session/new", { text }); select(r.session.id); }
  } catch (e) { alert(e.message); }
  refreshState(); poll();
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
  $("prompt").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send($("prompt").value); } });
  for (const c of document.querySelectorAll(".chip")) c.addEventListener("click", () => { $("prompt").value = c.dataset.prompt; $("prompt").focus(); });
  $("new-session").addEventListener("click", () => { S.sid = ""; S.status = ""; $("thread").replaceChildren(); $("title").textContent = "New session"; $("sub").textContent = "Type what to build or fix; it gets its own worktree."; $("prompt").focus(); });
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
