// Home's live view (owner 2026-10-25 11:20: "what happened to my live view in the home page i still want to see stuff"):
// the top of the Home hub shows your agents at work RIGHT NOW on every machine - what each is making, where, the stage,
// its last line and its live screen when it has one - and the machines. A click opens Studio > Agents (Stop, Again,
// Make). Nobody working: one calm line with the machines and a Make button. Reads GET /studio/agents
// (engine/studio_agents.py) every 4 s while Home shows; nothing when the window is hidden.
"use strict";

const LokiHomeLive = (() => {
  const S = { box: null, timer: 0, busy: false, sig: "" };
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const ago = (t) => { if (!t) return ""; const s = Math.max(0, Date.now() / 1000 - t); return s < 90 ? Math.round(s) + " s" : s < 5400 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1) + " h"; };
  const openStudio = () => { if (window.LokiModeBar) window.LokiModeBar.go("render", { view: "agents" }); };

  function mount() {
    const hub = document.getElementById("home-hub");
    if (!hub) return false;
    if (S.box && S.box.isConnected) return true;
    S.box = mk("section", "home-livewall"); S.box.id = "home-livewall"; S.box.setAttribute("aria-label", "Live: your agents at work");
    S.box.setAttribute("aria-live", "polite");
    const head = hub.querySelector(".home-head");
    if (head && head.nextSibling) hub.insertBefore(S.box, head.nextSibling); else hub.prepend(S.box);
    return true;
  }
  async function tick() {
    if (S.busy || document.hidden || typeof api !== "function") return;
    if (!mount() || S.box.offsetParent === null) return;          // Home is not showing
    S.busy = true;
    try {
      const d = await api("/studio/agents");
      if (d && d.ok) paint(d);
    } catch (_) { /* the engine is restarting */ }
    finally { S.busy = false; }
  }
  function paint(d) {
    const agents = (d.agents || []).filter((a) => /working|starting|queued|waiting|blocked/.test(a.status || a.state || ""));
    const machines = d.machines || [];
    const sig = JSON.stringify([agents.map((a) => [a.id, a.machine, a.stage, a.last_message, a.status]), machines.map((m) => [m.name, m.ok, m.working])]);
    if (sig === S.sig) { for (const t of S.box.querySelectorAll("[data-since]")) t.textContent = ago(+t.dataset.since); return; }
    S.sig = sig;
    S.box.replaceChildren();
    const top = mk("div", "hl-top");
    const dot = mk("i", "hl-dot" + (agents.length ? " on" : ""));
    top.append(dot, mk("b", "hl-title", agents.length ? agents.length + " agent" + (agents.length === 1 ? "" : "s") + " working" : "Live"),
      mk("span", "hl-machines", machines.map((m) => (m.ok ? "● " : "○ ") + m.name + (m.working ? " (" + m.working + ")" : "")).join("   ")));
    const go = mk("button", "hl-open quiet small", agents.length ? "Watch in Studio" : "Make something");
    go.type = "button"; go.dataset.tipName = go.textContent; go.dataset.tipWhat = "Studio > Agents: every agent on every machine, Stop and Again, and Make (art, 3D, comics, novels, websites).";
    go.addEventListener("click", openStudio);
    top.append(go);
    S.box.append(top);
    // idle: a slim line inside the header row (no extra height - the cards stay on screen in a short window);
    // agents working: its own panel under the header
    const hub = document.getElementById("home-hub"), head = hub && hub.querySelector(".home-head");
    if (head) {
      if (!agents.length && S.box.parentNode !== head) head.append(S.box);
      else if (agents.length && S.box.parentNode === head) hub.insertBefore(S.box, head.nextSibling);
    }
    if (!agents.length) {
      S.box.classList.add("idle");
      if (d.hint && machines.length < 2) { go.dataset.tipWhat = "Only this computer is linked - Studio > Agents links the other one. " + go.dataset.tipWhat; S.box.append(mk("span", "hl-hint", "1 machine - link the other in Studio > Agents")); }
      return;
    }
    S.box.classList.remove("idle");
    const row = mk("div", "hl-row");
    for (const a of agents.slice(0, 4)) {
      const t = mk("button", "hl-agent"); t.type = "button"; t.dataset.machine = a.machine || ""; t.dataset.agent = a.id;
      t.addEventListener("click", openStudio);
      t.dataset.tipName = a.task || a.name || "Agent"; t.dataset.tipWhat = "Open it in Studio > Agents (Stop, Again, its output).";
      if (a.screenshot && a.job && !a.remote) {
        const img = mk("img", "hl-shot"); img.alt = ""; t.append(img);
        api("/jobs/screenshot?id=" + encodeURIComponent(a.job)).then((r) => { if (r && r.ok) img.src = r.image; }).catch(() => {});
      }
      t.append(mk("b", "hl-task", a.task || a.name || "LOKI"));
      const meta = mk("span", "hl-meta", [a.machine, a.stage, a.status || a.state].filter(Boolean).join(" · ") + (a.since ? " · " : ""));
      if (a.since) { const s = mk("span", "", ago(a.since)); s.dataset.since = a.since; meta.append(s); }
      t.append(meta);
      if (a.last_message || a.note) t.append(mk("span", "hl-line", a.last_message || a.note));
      row.append(t);
    }
    if (agents.length > 4) { const more = mk("button", "hl-more quiet small", "+" + (agents.length - 4) + " more"); more.type = "button"; more.addEventListener("click", openStudio); row.append(more); }
    S.box.append(row);
  }
  function start() {
    clearInterval(S.timer);
    S.timer = setInterval(tick, 4000);
    setTimeout(tick, 600);
  }
  document.addEventListener("DOMContentLoaded", start);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });
  return { tick, paint, mount };
})();
window.LokiHomeLive = LokiHomeLive;
