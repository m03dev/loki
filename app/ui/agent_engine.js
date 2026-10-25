// The agent card (Settings > Agents, and a one-line notice over the chat when it is missing): LOKI's agent is OpenCode
// with CodeGraph as its code map (engine/opencode_engine.py). Shows where each is, installs the missing ones with one
// click (npm i -g), and switches back to LOKI's old built-in loop only if you ask for it.
"use strict";

const AgentEngine = (() => {
  const mk = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  let card = null, notice = null, last = null;

  function row(label, value, ok) {
    const r = mk("div", "ae-row");
    r.append(mk("span", "ae-label", label), mk("span", "ae-val " + (ok ? "ok" : "bad"), value));
    return r;
  }

  function paint(st) {
    last = st;
    if (card) {
      card.replaceChildren();
      card.append(mk("h4", "ae-title", "The agent: OpenCode + CodeGraph"),
        mk("p", "note", "Your chat and Build tasks are done by OpenCode (an open-source coding agent: files, edits, bash, git) "
          + "using your connected providers, with CodeGraph as its map of the code. LOKI shows every tool it runs and says NOT DONE when nothing ran."),
        row("OpenCode", st.opencode || "not installed", !!st.opencode),
        row("CodeGraph", st.codegraph ? st.codegraph + (st.indexed ? " (workspace indexed)" : " (indexes on first use)") : "not installed", !!st.codegraph),
        row("Workspace", st.workspace || "", true));
      const acts = mk("div", "ae-acts");
      if (!st.opencode || !st.codegraph) {
        const b = mk("button", "send small", "Install " + [!st.opencode && "OpenCode", !st.codegraph && "CodeGraph"].filter(Boolean).join(" + "));
        b.type = "button"; b.id = "ae-install";
        b.addEventListener("click", install);
        acts.append(b);
      }
      const sel = mk("select", "ae-engine"); sel.id = "ae-engine";
      for (const [v, t] of [["opencode", "Agent: OpenCode (recommended)"], ["loki", "Agent: LOKI's old built-in loop"]]) {
        const o = mk("option", "", t); o.value = v; o.selected = st.engine === v; sel.append(o);
      }
      sel.addEventListener("change", async () => paint(await api("/agent/engine/set", { engine: sel.value })));
      acts.append(sel);
      card.append(acts);
    }
    const missing = st.engine === "opencode" && !st.opencode;
    if (notice) notice.hidden = !missing;
  }

  async function install() {
    const b = document.getElementById("ae-install");
    if (b) { b.disabled = true; b.textContent = "Installing (npm i -g) ..."; }
    const r = await api("/agent/engine/install", {});
    paint(r);
    if (card && r.result) {
      const bad = Object.entries(r.result).filter(([, v]) => v !== "ok" && v !== "already");
      card.append(mk("p", bad.length ? "note bad" : "note", bad.length ? bad.map(([k, v]) => k + ": " + v).join(" · ") : "Installed."));
    }
  }

  async function load() {
    try { paint(await api("/agent/engine")); } catch (_) { /* engine restarting */ }
  }

  function start() {
    const host = document.getElementById("agents-panel");
    if (host && !document.getElementById("ae-card")) {
      card = mk("div", "ae-card"); card.id = "ae-card";
      host.parentNode.insertBefore(card, host);
    }
    const col = document.getElementById("chat-col"), comp = document.getElementById("composer");
    if (col && comp && !document.getElementById("ae-notice")) {
      notice = mk("div", "ae-notice"); notice.id = "ae-notice"; notice.hidden = true; notice.setAttribute("role", "status");
      notice.append(mk("span", "", "LOKI's agent (OpenCode) is not installed on this computer, so it cannot do tasks yet. "));
      const b = mk("button", "send small", "Install it"); b.type = "button";
      b.addEventListener("click", async () => { b.disabled = true; b.textContent = "Installing ..."; await install(); b.disabled = false; b.textContent = "Install it"; });
      notice.append(b);
      col.insertBefore(notice, comp);
    }
    const wait = setInterval(() => { if (window.LOKI_READY) { clearInterval(wait); load(); } }, 300);
    document.addEventListener("click", (e) => { const t = e.target.closest && e.target.closest('[data-tab="agents"]'); if (t) setTimeout(load, 50); });
  }

  document.addEventListener("DOMContentLoaded", start);
  return { load, install, status: () => last };
})();
window.AgentEngine = AgentEngine;
