// LOKI's agent system in the window (engine/agentsys/, docs/AGENT_SYSTEM.md; owner 2026-10-28).
//
//   Interview      before work starts, 1-4 questions with options under the owner's message ("is this what you
//                  want?"): pick, add a note, Go - or "As written" / "Not now". Templates answer in milliseconds; a
//                  model may sharpen them inside 4 s, never longer (POST /agentsys/interview). Big work asks "team or
//                  one agent": Specialist team runs the delegation loop (POST /agentsys/orchestrate).
//   Send back      on LOKI's latest answer: a note box - the note becomes the revision request (POST /agentsys/sendback);
//   Not now        parks the request (it waits in For you > Parked, one click to resume).
//   Lab > System   every layer at a glance: runs (traces), delegation runs, playbooks (add your own line, retire one),
//                  upstream sources (Check now), parked work.
//
// Its own module; app.js calls LokiAgentSys.offer(text, opts) from send() and LokiAgentSys.label(text) from addUser().
// Plain DOM, CSP script-src 'self'; icons with hover tooltips; sizes in % / fr.
"use strict";

const LokiAgentSys = (() => {
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.reject(new Error("not ready")));
  const svg = (paths) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + paths + "</svg>";
  const ICON = {
    go: '<path d="M5 12h12"/><path d="M13 6l6 6-6 6"/>',
    asis: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    later: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    back: '<path d="M9 7L4 12l5 5"/><path d="M4 12h10a6 6 0 0 1 0 12h-1" transform="translate(0 -6)"/>',
    ask: '<circle cx="12" cy="12" r="8.5"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.5V14"/><path d="M12 17h.01"/>',
    team: '<circle cx="8" cy="9" r="2.6"/><circle cx="16" cy="9" r="2.6"/><path d="M3.5 18c.8-2.6 2.6-4 4.5-4s3.7 1.4 4.5 4"/><path d="M11.5 18c.8-2.6 2.6-4 4.5-4s3.7 1.4 4.5 4"/>',
    resume: '<path d="M8 5v14l11-7z"/>',
    drop: '<path d="M6 6l12 12M18 6L6 18"/>',
    check: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v4h4"/>',
    add: '<path d="M12 5v14M5 12h14"/>',
  };
  const ANSWERS_MARK = "Owner's choices (from the interview):";
  const cid = () => (typeof state !== "undefined" && state && state.active) || "";   // app.js's chat on screen

  function iconBtn(cls, icon, name, what, fn, label) {
    const b = mk("button", "as-btn " + (cls || "")); b.type = "button";
    b.innerHTML = svg(icon); if (label) b.append(mk("span", "", label));
    b.dataset.tipName = name; b.dataset.tipWhat = what; b.setAttribute("aria-label", name);
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(b); });
    return b;
  }
  const transcript = () => document.getElementById("transcript");
  const scroll = (n) => { try { n.scrollIntoView({ block: "end", behavior: "smooth" }); } catch (_) { /* old webview */ } };
  const say = (text, bad) => { if (typeof addNotice === "function") addNotice(text, bad); };

  // ------------------------------------------------------------------ what a user turn shows
  /** The owner's words, not the machinery: a revision shows his note, an interviewed request his choices. */
  function label(text) {
    const t = String(text || "");
    if (/^REVISION \d+ - the owner sent the last result back\./.test(t)) {
      const m = /changed \(this is the instruction[^)]*\): ([\s\S]*?)(\n\n|$)/.exec(t);
      return "↩ Sent back: " + (m ? m[1].trim() : "");
    }
    const i = t.indexOf(ANSWERS_MARK);
    if (i >= 0) {
      const choices = t.slice(i + ANSWERS_MARK.length).trim().split("\n").map((l) => l.replace(/^- /, "")).filter(Boolean);
      return t.slice(0, i).trim() + "\n\n" + choices.map((c) => "· " + c).join("\n");
    }
    return t;
  }

  // ------------------------------------------------------------------ the interview
  /** Called by send() before a message goes out. Shows the owner's message + the questions and returns true (the
      card sends the brief when he picks), or false when nothing needs asking (send() goes on as usual). */
  async function offer(text, opts) {
    opts = opts || {};
    const t = String(text || "").trim();
    if (!t || t.startsWith("/") || t.includes(ANSWERS_MARK) || /^REVISION \d+/.test(t)) return false;
    const box = transcript();
    if (!box) return false;
    if (typeof addUser === "function") addUser(t);            // his message shows at once, the card follows
    const wait = mk("div", "as-iv as-iv-wait", "Checking what you want…");
    box.append(wait); scroll(wait);
    const iv = await Promise.race([call("/agentsys/interview", { text: t }).catch(() => null),
      new Promise((res) => setTimeout(() => res(null), 9000))]);
    wait.remove();
    if (!iv || !iv.ok || !iv.ask || !(iv.questions || []).length) { opts.go(t, { quiet: true }); return true; }
    box.append(card(t, iv, opts)); scroll(box.lastChild);
    return true;
  }

  function card(text, iv, opts) {
    const c = mk("section", "as-iv"); c.setAttribute("aria-label", "Before LOKI starts: is this what you want?");
    const head = mk("div", "as-iv-head"); head.innerHTML = svg(ICON.ask);
    head.append(mk("span", "", "Before I start - is this what you want?"));
    c.append(head);
    if (iv.plan) c.append(mk("p", "as-iv-plan", iv.plan));
    const picks = {};
    for (const q of iv.questions) {
      const row = mk("div", "as-q"); row.setAttribute("role", "group"); row.setAttribute("aria-label", q.question);
      const h = mk("div", "as-q-h"); h.append(mk("b", "as-q-tag", q.header), mk("span", "", q.question + (q.multi ? " (pick any)" : "")));
      const opts_ = mk("div", "as-opts");
      picks[q.header] = q.multi ? [] : (q.options[0] ? q.options[0].label : "");     // the first is the suggestion
      const mark = () => { for (const b of opts_.querySelectorAll(".as-opt")) {
        const on = q.multi ? picks[q.header].includes(b.dataset.label) : picks[q.header] === b.dataset.label;
        b.setAttribute("aria-pressed", String(on)); } };
      for (const o of q.options) {
        const b = mk("button", "as-opt"); b.type = "button"; b.dataset.label = o.label;
        b.append(mk("span", "as-opt-l", o.label)); if (o.description) b.append(mk("span", "as-opt-d", o.description));
        b.dataset.tipName = o.label; b.dataset.tipWhat = o.description || o.label;
        b.addEventListener("click", () => {
          if (q.multi) { const a = picks[q.header]; const i = a.indexOf(o.label); if (i >= 0) a.splice(i, 1); else a.push(o.label); }
          else picks[q.header] = o.label;
          other.value = ""; mark();
        });
        opts_.append(b);
      }
      const other = mk("input", "as-other"); other.type = "text"; other.placeholder = "Other…";
      other.setAttribute("aria-label", q.header + ": something else");
      other.addEventListener("input", () => { if (other.value.trim()) { picks[q.header] = q.multi ? [other.value.trim()] : other.value.trim(); mark(); } });
      other.addEventListener("keydown", (e) => e.stopPropagation());
      opts_.append(other);
      row.append(h, opts_);
      c.append(row);
      mark();
    }
    const note = mk("input", "as-note"); note.type = "text"; note.placeholder = "Anything else? (optional)";
    note.setAttribute("aria-label", "A note for LOKI");
    note.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") go.click(); });
    const acts = mk("div", "as-acts");
    const done = (how) => { c.classList.add("as-done"); c.dataset.how = how; for (const n of c.querySelectorAll("button, input")) n.disabled = true; };
    const go = iconBtn("as-go", ICON.go, "Go", "Start with these choices.", async () => {
      done("go");
      const answers = {};
      for (const [k, v] of Object.entries(picks)) if ((Array.isArray(v) && v.length) || (!Array.isArray(v) && v)) answers[k] = v;
      const b = await call("/agentsys/brief", { text, answers, questions: iv.questions, note: note.value }).catch(() => null);
      const request = (b && b.ok && b.request) || text;
      if (b && b.team) return orchestrate(request);
      opts.go(request, { quiet: true });
    }, "Go");
    acts.append(go,
      iconBtn("as-asis", ICON.asis, "As written", "Skip the questions - do exactly what I wrote.", () => { done("asis"); opts.go(text, { quiet: true }); }),
      iconBtn("as-later", ICON.later, "Not now", "Park it: nothing is made now. It waits in For you > Parked, one click to start it later.",
        async () => {
          done("later");
          const r = await call("/agentsys/sendback", { kind: "text", action: "park", text, note: note.value }).catch(() => null);
          say(r && r.ok ? "Parked - nothing is made now. It waits in Home > For you > Parked." : "Could not park it.", !(r && r.ok));
        }));
    const foot = mk("div", "as-row"); foot.append(note, acts);
    c.append(foot);
    if (iv.by === "model") c.append(mk("p", "as-by", "Questions sharpened by the model for this request."));
    return c;
  }

  async function orchestrate(goal) {
    const r = await call("/agentsys/orchestrate", { goal, conversation_id: cid() })
      .catch((e) => ({ ok: false, error: String(e) }));
    if (r && r.ok) {
      if (typeof addLoki === "function") addLoki("**Specialist team on it.** I plan the steps, hand each to the specialist for it, check every result and send back what fails. You see each hand-off in **For you**; the report lands here. Follow it in **Lab > System**.");
    } else say((r && r.error) || "Could not start the specialist team.", true);
  }

  // ------------------------------------------------------------------ send back / not now on LOKI's answer
  function bar() {
    const b = mk("div", "as-sb"); b.setAttribute("aria-label", "Not what you wanted?");
    const note = mk("input", "as-sb-note"); note.type = "text"; note.placeholder = "What should change?"; note.hidden = true;
    note.setAttribute("aria-label", "What should change");
    const back = iconBtn("as-sb-back", ICON.back, "Send back", "Not right? Say what to change - LOKI redoes it with your note (and remembers it for next time).", () => {
      if (note.hidden) { note.hidden = false; note.focus(); return; }
      sendBack(note, b);
    });
    note.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") sendBack(note, b); if (e.key === "Escape") note.hidden = true; });
    const later = iconBtn("as-sb-later", ICON.later, "Not now", "Park this request: stop here, keep it in For you > Parked to start later.", async () => {
      const r = await call("/agentsys/sendback", { kind: "chat", action: "park", note: note.value, conversation_id: cid() }).catch(() => null);
      say(r && r.ok ? "Parked - it waits in Home > For you > Parked." : "Could not park it.", !(r && r.ok));
      b.remove();
    });
    b.append(note, back, later);
    return b;
  }

  async function sendBack(note, b) {
    const words = note.value.trim();
    if (!words) { note.hidden = false; note.focus(); note.classList.add("want"); return; }
    b.classList.add("busy");
    const r = await call("/agentsys/sendback", { kind: "chat", note: words, conversation_id: cid() })
      .catch((e) => ({ ok: false, error: String(e) }));
    b.classList.remove("busy");
    if (!r || !r.ok) { say((r && r.error) || "Could not send it back.", true); return; }
    b.remove();
    if (typeof addUser === "function") addUser("↩ Sent back: " + words);
    if (typeof send === "function") send(r.request, { direct: true, quiet: true });
  }

  /** The send-back bar lives on LOKI's newest answer only (it redoes the latest result). */
  function keepBar() {
    const box = transcript();
    if (!box) return;
    const turns = box.querySelectorAll(".turn.loki");
    const last = turns[turns.length - 1];
    for (const n of box.querySelectorAll(".as-sb")) if (!last || n.parentNode !== last) n.remove();
    if (last && !last.querySelector(".as-sb") && !(typeof state !== "undefined" && state.busy)) last.append(bar());
  }

  // ------------------------------------------------------------------ Lab > System
  const P = { root: null, timer: 0 };
  const ago = (t) => { if (!t) return "never"; const s = Date.now() / 1000 - t; return s < 90 ? "just now" : s < 5400 ? Math.round(s / 60) + " min ago" : s < 172800 ? Math.round(s / 3600) + " h ago" : Math.round(s / 86400) + " d ago"; };
  function box(title, tip) {
    const s = mk("section", "as-box"); const h = mk("div", "as-box-h"); const t = mk("h3", "", title);
    t.dataset.tipName = title; t.dataset.tipWhat = tip; h.append(t); s.append(h); return s;
  }
  async function panel(container) {
    if (!P.root || P.root.parentNode !== container) {
      P.root = mk("div", "as-panel"); P.root.setAttribute("aria-label", "LOKI's agent system");
      container.replaceChildren(P.root);
    }
    const [st, runs, pb, up, pk, orch] = await Promise.all(["/agentsys/status", "/agentsys/traces?days=2", "/agentsys/playbooks",
      "/agentsys/upstream", "/agentsys/parked", "/agentsys/orchestrations"].map((p) => call(p).catch(() => null)));
    const kids = [];
    const t = (st && st.traces) || {};
    const head = box("This week", "Every request LOKI ran, from the traces (engine/agentsys/trace.py).");
    const facts = mk("div", "as-stats");
    for (const [k, v, tip] of [["Runs", t.runs, "Requests and jobs run"], ["Model calls", t.model_calls, "Calls to a model"],
      ["Tools", t.tool_calls, "Tool calls"], ["Tool errors", t.tool_errors, "Tool calls that failed"],
      ["Checks tripped", t.guardrails_tripped, "Guardrails that stopped or flagged something"],
      ["Tokens", ((t.tokens || {}).input || 0) + ((t.tokens || {}).output || 0), "Tokens in + out"],
      ["Interview", (st && st.interview) || "?", "LOKI_INTERVIEW: always / big / off"], ["Parked", (st && st.parked) || 0, "Waiting for you to start"]]) {
      const c = mk("div", "as-stat"); c.dataset.tipName = k; c.dataset.tipWhat = tip;
      c.append(mk("b", "", v == null ? "-" : String(v)), mk("span", "", k)); facts.append(c);
    }
    head.append(facts);
    if ((t.failing_tools || []).length) head.append(mk("p", "as-muted", "Failing most: " + t.failing_tools.slice(0, 5).map((x) => x[0] + " (" + x[2] + "/" + x[1] + ")").join(", ")));
    kids.push(head);

    const rb = box("Runs", "The latest runs: what ran, how long, tools, errors, the outcome.");
    const rl = mk("div", "as-list");
    for (const r of ((runs && runs.runs) || []).slice(0, 12)) {
      const row = mk("div", "as-item as-" + (r.status === "error" ? "bad" : r.outcome === "done" || r.outcome === "verified" ? "ok" : "mid"));
      row.append(mk("span", "as-item-t", (r.name || "").replace(/^invoke_agent /, "")), mk("span", "as-muted",
        [r.outcome || r.status, (r.ms / 1000).toFixed(1) + " s", r.llm + " model", r.tools + " tools", r.errors ? r.errors + " errors" : "", ago(r.start)].filter(Boolean).join(" · ")));
      if ((r.tripped || []).length) row.append(mk("span", "as-warn", r.tripped.join(", ")));
      rl.append(row);
    }
    if (!rl.children.length) rl.append(mk("p", "as-muted", "No runs yet."));
    rb.append(rl); kids.push(rb);

    const ob = box("Specialist teams", "Delegation runs: the plan, each specialist's step, what was checked.");
    const ol = mk("div", "as-list");
    for (const r of ((orch && orch.runs) || []).slice(0, 8)) {
      const row = mk("div", "as-item as-" + (r.outcome === "verified" ? "ok" : r.outcome === "failed" ? "bad" : "mid"));
      row.append(mk("span", "as-item-t", r.goal), mk("span", "as-muted", (r.outcome || r.status) + " · " + ago(r.updated)));
      const steps = mk("div", "as-steps");
      for (const s of r.steps || []) { const chip = mk("span", "as-chip as-" + s.status, s.specialist); chip.title = s.id + ": " + s.status; steps.append(chip); }
      row.append(steps); ol.append(row);
    }
    if (!ol.children.length) ol.append(mk("p", "as-muted", "None yet - pick \"Specialist team\" when LOKI asks who should do big work."));
    ob.append(ol); kids.push(ob);

    const pbb = box("Playbooks", "What LOKI learned works, per kind of work. Your own lines (from send-backs and here) always come first.");
    const pgrid = mk("div", "as-pb");
    const books = (pb && pb.playbooks) || {};
    for (const [kind, v] of Object.entries(books)) {
      const card = mk("div", "as-pb-card");
      card.append(mk("b", "", kind + " · " + v.active + " lines" + (v.owner ? " · " + v.owner + " yours" : "")));
      for (const b of v.top || []) {
        const line = mk("div", "as-pb-line as-" + b.section);
        line.append(mk("span", "", b.text), mk("span", "as-muted", "+" + b.helpful + " / -" + b.harmful));
        line.append(iconBtn("as-mini", ICON.drop, "Retire", "Take this line out of the playbook.", async () => {
          await call("/agentsys/playbook", { kind, op: "retire", id: b.id }).catch(() => null); panel(container);
        }));
        card.append(line);
      }
      const add = mk("input", "as-pb-add"); add.type = "text"; add.placeholder = "Add your own line for " + kind + "…";
      add.setAttribute("aria-label", "Add a playbook line for " + kind);
      add.addEventListener("keydown", async (e) => {
        e.stopPropagation();
        if (e.key === "Enter" && add.value.trim()) { await call("/agentsys/playbook", { kind, op: "add", text: add.value.trim() }).catch(() => null); panel(container); }
      });
      card.append(add); pgrid.append(card);
    }
    pbb.append(pgrid); kids.push(pbb);

    const ub = box("Upstream", "Every open-source project LOKI is built from, the version LOKI has, and what changed there since. Changes come to For you: Adopt, Skip or Not now.");
    const uh = ub.querySelector(".as-box-h");
    uh.append(iconBtn("as-mini", ICON.check, "Check now", "Ask GitHub now what changed in the projects LOKI uses.", async (btn) => {
      btn.disabled = true;
      const r = await call("/agentsys/upstream/check", {}).catch((e) => ({ ok: false, error: String(e) }));
      btn.disabled = false;
      say(r && r.ok ? "Checked " + r.checked + " of " + r.total + " sources - " + r.new + " with something new (in For you)." + (r.token ? "" : " No GitHub token: a batch at a time.") : (r && r.error) || "The check failed.", !(r && r.ok));
      panel(container);
    }));
    const srcs = (up && up.sources) || [];
    const order = { behind: 0, "new release": 1, archived: 2, moved: 3, unreachable: 4 };
    const ul = mk("div", "as-list as-up");
    ub.append(mk("p", "as-muted", srcs.length + " sources · last check " + ago(up && up.last_run)));
    for (const e of srcs.slice().sort((a, b) => (order[(a.seen || {}).status] ?? 9) - (order[(b.seen || {}).status] ?? 9)).slice(0, 40)) {
      const s = e.seen || {};
      const row = mk("div", "as-item as-" + (s.status === "behind" || s.status === "new release" ? "mid" : s.status === "archived" || s.status === "unreachable" ? "bad" : "ok"));
      const a = mk("a", "as-item-t", e.repo); a.href = "https://github.com/" + e.repo; a.target = "_blank"; a.rel = "noopener";
      row.append(a, mk("span", "as-muted", [(e.pin || "").slice(0, 8) || e.version || e.follows || "not pinned",
        s.status ? (s.status === "behind" ? "behind by " + s.behind : s.status) : "not checked", (e.used_in || []).slice(0, 2).join("; ")].join(" · ")));
      ul.append(row);
    }
    ub.append(ul); kids.push(ub);

    const kb = box("Parked", "What you said Not now to. Start it again with one click (add a note if you like), or drop it.");
    const kl = mk("div", "as-list");
    for (const it of ((pk && pk.parked) || []).slice(0, 20)) kl.append(parkedRow(it, () => panel(container)));
    if (!kl.children.length) kl.append(mk("p", "as-muted", "Nothing parked."));
    kb.append(kl); kids.push(kb);
    P.root.replaceChildren(...kids);
    clearInterval(P.timer);
    P.timer = setInterval(() => { if (P.root && P.root.offsetParent !== null && !document.hidden) panel(container); }, 15000);
  }
  function leave() { clearInterval(P.timer); P.timer = 0; }

  function parkedRow(it, after) {
    const row = mk("div", "as-item as-parked");
    row.append(mk("span", "as-item-t", label(it.request).split("\n")[0].slice(0, 180)), mk("span", "as-muted", (it.note ? "\"" + it.note + "\" · " : "") + ago(it.t)));
    const note = mk("input", "as-sb-note"); note.type = "text"; note.placeholder = "Note for when it starts (optional)";
    note.addEventListener("keydown", (e) => e.stopPropagation());
    const acts = mk("div", "as-acts");
    acts.append(iconBtn("as-mini", ICON.resume, "Start it", "Start this now (with your note, if you wrote one).", async () => {
      const r = await call("/agentsys/parked/resume", { id: it.id, note: note.value }).catch(() => null);
      if (r && r.ok) {
        if (typeof showChat === "function") showChat();
        if (typeof send === "function") send(r.request, { direct: true });
      }
      if (after) after();
    }), iconBtn("as-mini", ICON.drop, "Drop", "Forget this parked request.", async () => {
      await call("/agentsys/parked/drop", { id: it.id }).catch(() => null); if (after) after();
    }));
    const r2 = mk("div", "as-row"); r2.append(note, acts); row.append(r2);
    return row;
  }

  function start() {
    const box_ = transcript();
    if (box_ && window.MutationObserver) new MutationObserver(() => keepBar()).observe(box_, { childList: true });
    setInterval(keepBar, 1500);   // also once a busy reply has finished
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
  return { offer, label, panel, leave, parkedRow, keepBar, orchestrate };
})();
window.LokiAgentSys = LokiAgentSys;
