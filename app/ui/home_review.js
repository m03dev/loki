// Home > For you: what waits for the owner's OK (engine/owner_review.py; owner 2026-10-27: "i never get prompted
// before they make an image i should be overseeing the prompt and the images gen like check off should come through my
// eyes once i should see the hands offs").
//
//   a prompt card   who asks (Concept Artist, Technical Artist, an agent's job), for what, and its prompt in a box the
//                   owner can edit - Approve draws it (with the owner's words), No drops it. Nothing is drawn before.
//   a result card   the pictures (or the model's render) with the hand-off notes (what was checked) - Approve hands it
//                   on to the next agent, Retake sends it back with a note (its prompt comes back here first).
//   drawing...      what the owner approved and LOKI is making right now.
//
// Its own module (AGENTS.md rule 1): it mounts itself under Home's header (#home-hub .home-head) and asks GET /review
// every 10 s (only while Home is on screen); POST /review/decide answers. Icons with hover tooltips, sizes in % / fr.
// Plain DOM, CSP script-src 'self'.
"use strict";

const LokiHomeReview = (() => {
  const EVERY_MS = 10000;
  const ICON = {
    ok: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    no: '<path d="M6 6l12 12M18 6L6 18"/>',
    retake: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v4h4"/>',
    brief: '<path d="M6 4h9l3 3v13H6z"/><path d="M9 11h6M9 14h6M9 17h4"/>',
    you: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c1.2-3.8 4-5.5 7-5.5s5.8 1.7 7 5.5"/>',
    later: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    adopt: '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/>',
    skip: '<path d="M6 5l8 7-8 7z"/><path d="M17 5v14"/>',
    go: '<path d="M5 12h12"/><path d="M13 6l6 6-6 6"/>',
  };
  const S = { items: [], timer: 0, busy: {}, open: {} };
  let panel = null, list = null, count = null;
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const svg = (paths) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + paths + "</svg>";
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.reject(new Error("not ready")));

  function iconBtn(cls, icon, name, what, fn) {
    const b = mk("button", "rv-btn " + (cls || "")); b.type = "button";
    b.innerHTML = svg(icon); b.dataset.tipName = name; b.dataset.tipWhat = what; b.setAttribute("aria-label", name);
    b.addEventListener("click", fn);
    return b;
  }
  function ago(t) {
    const s = Math.max(0, Date.now() / 1000 - (t || 0));
    return s < 90 ? "just now" : s < 5400 ? Math.round(s / 60) + " min ago" : s < 129600 ? Math.round(s / 3600) + " h ago" : Math.round(s / 86400) + " d ago";
  }
  const isPic = (p) => /\.(png|jpe?g|webp|gif)$/i.test(p || "");
  const words = (it) => String((it.args && (it.args.prompt || it.args.subject)) || "");

  /** The panel lives right under Home's header row; it builds itself once Home is there. */
  function mount() {
    const hub = document.getElementById("home-hub");
    const head = hub && hub.querySelector(".home-head");
    if (panel) {
      // Home rebuilds its header (pages, tabs): the panel fell out of the page and For you was gone until a restart
      // (owner 2026-10-28: "for u just bugs out sometimes") - put it back under the header it has now
      if (!panel.isConnected && head) head.after(panel);
      return panel.isConnected;
    }
    if (!hub || !head) return false;
    panel = mk("section", "rv-panel"); panel.id = "home-review"; panel.hidden = true;
    panel.setAttribute("aria-label", "For you: prompts and hand-offs waiting for your OK");
    const top = mk("div", "rv-top");
    const title = mk("div", "rv-title"); title.innerHTML = svg(ICON.you);
    title.append(mk("span", "", "For you"));
    title.dataset.tipName = "For you";
    title.dataset.tipWhat = "Nothing is drawn until you OK its prompt, and nothing is handed on until you check it off.";
    count = mk("span", "rv-count");
    top.append(title, count);
    list = mk("div", "rv-list"); list.setAttribute("role", "list");
    panel.append(top, list);
    head.after(panel);
    return true;
  }

  /** A card's picture, as data (the window shows only its own pictures). A relative path is the card's own project
   *  folder's (2026-10-28, the Mac: images/... of a job in Home/myth_might_mayhem was looked for in Home - blank). */
  const full = (it, f) => (/^([a-zA-Z]:[\\/]|\/)/.test(f) || !it || !it.cwd) ? f : it.cwd.replace(/[\\/]+$/, "") + "/" + f;
  async function media(path, img, it) {
    const m = await call("/chat/media?path=" + encodeURIComponent(full(it, path))).catch(() => null);
    if (m && m.ok && m.data_url) { img.src = m.data_url; return; }
    const why = (m && m.error) || "could not load";
    if (/still being written/.test(why) && img.isConnected) { setTimeout(() => media(path, img, it), 3000); return; }
    const d = mk("div", "rv-file", path.split(/[\\/]/).pop() + " - " + why);
    d.title = full(it, path);
    img.replaceWith(d);
  }

  async function decide(it, action, extra, card) {
    if (S.busy[it.id]) return;
    S.busy[it.id] = true; card.classList.add("busy");
    const r = await call("/review/decide", Object.assign({ id: it.id, action }, extra || {})).catch((e) => ({ ok: false, error: String(e) }));
    S.busy[it.id] = false; card.classList.remove("busy");
    if (!r || !r.ok) { const e = card.querySelector(".rv-err"); if (e) e.textContent = (r && r.error) || "That did not go through."; return; }
    refresh(true);
  }

  function head(it) {
    const h = mk("div", "rv-head");
    h.append(mk("span", "rv-who", it.who || "An agent"));
    const what = it.status === "working" ? "is drawing what you approved" : it.kind === "prompt" ? "wants to draw" : "hands this on";
    h.append(mk("span", "rv-what", what));
    if (it.asset) h.append(mk("span", "rv-asset", it.asset + (it.stage ? " / " + it.stage : "")));
    h.append(mk("span", "rv-ago", ago(it.t)));
    return h;
  }

  function brief(it) {
    if (!it.handoff) return null;
    const d = mk("details", "rv-brief"); if (S.open[it.id]) d.open = true;
    d.addEventListener("toggle", () => { S.open[it.id] = d.open; });
    const s = mk("summary"); s.innerHTML = svg(ICON.brief); s.append(mk("span", "", it.kind === "prompt" ? "What it is for" : "Hand-off notes"));
    d.append(s, mk("pre", "rv-notes", it.handoff));
    return d;
  }

  /** Exactly what will run, in a few short lines (owner 2026-10-27: "what the prompt was ... what images they're using,
      what prompts and what engine, what their plan is ... very minimal, to the point"). From engine/review_plan.py. */
  function facts(it) {
    const p = it.plan || {};
    if (!p.plan && !p.engine && !(p.inputs || []).length) return null;
    const box = mk("div", "rv-facts");
    const row = (label, value) => { if (!value) return; const r = mk("div", "rv-fact"); r.append(mk("span", "rv-k", label));
      if (value instanceof Node) r.append(value); else r.append(mk("span", "rv-v", value)); box.append(r); };
    if ((p.inputs || []).length) {
      const strip = mk("span", "rv-uses");
      for (const f of p.inputs.slice(0, 4)) {
        if (isPic(f)) { const img = mk("img"); img.alt = f.split(/[\\/]/).pop(); img.title = f; strip.append(img); media(f, img, it); }
        else strip.append(mk("span", "rv-v", f.split(/[\\/]/).pop()));
      }
      row("Uses", strip);
    }
    row("Engine", p.engine);
    row("Makes", p.output);
    row("Plan", p.plan);
    if (p.prompt && p.prompt.trim() !== words(it).trim()) {
      const d = mk("details", "rv-brief rv-full"); if (S.open["full" + it.id]) d.open = true;
      d.addEventListener("toggle", () => { S.open["full" + it.id] = d.open; });
      const sm = mk("summary"); sm.innerHTML = svg(ICON.brief); sm.append(mk("span", "", "Full prompt sent"));
      d.append(sm, mk("pre", "rv-notes", p.prompt + (p.negative ? "\n\nKept out: " + p.negative : "")));
      box.append(d);
    }
    return box;
  }

  function promptCard(it) {
    const c = mk("div", "rv-card rv-prompt"); c.setAttribute("role", "listitem"); c.dataset.id = it.id;
    c.append(head(it));
    if (it.note) c.append(mk("div", "rv-note", "Your note: " + it.note));
    const ex = it.expert || {};   // the Prompt Expert (engine/prompt_expert.py) rewrites the agent's words first
    if (ex.status === "working") c.append(mk("div", "rv-expert working", "Prompt Expert is improving this prompt…"));
    else if (ex.status === "done") {
      const e = mk("div", "rv-expert done", "Improved by the Prompt Expert" + (ex.why ? ": " + ex.why : ""));
      e.dataset.tipName = "Prompt Expert"; e.dataset.tipWhat = "An art director rewrote the agent's prompt" + (ex.by ? " (" + ex.by + ")" : "") + ". Edit it freely before you approve.";
      c.append(e);
      const refs = (ex.refs || []).filter(r => r && r.image).slice(0, 3);
      if (refs.length) {   // the real reference prompts the expert matched (engine/specialist_library.py), with their pictures
        const rr = mk("div", "rv-refs"); rr.setAttribute("aria-label", "Reference pictures the expert used");
        for (const r of refs) {
          const img = mk("img"); img.alt = r.title || "reference";
          // the window shows only its own pictures (CSP img-src 'self' data:): the engine fetches the web picture
          call("/chat/media/ref?url=" + encodeURIComponent(r.image)).then((d) => { if (d && d.ok) img.src = d.data_url; else img.remove(); }).catch(() => img.remove());
          img.dataset.tipName = "Reference: " + (r.title || "");
          img.dataset.tipWhat = "A real prompt that made this picture" + (r.author ? " (by " + r.author + ")" : "") + ". The expert matched its detail, not its subject.";
          img.addEventListener("error", () => img.remove());
          rr.append(img);
        }
        c.append(rr);
      }
    } else if (ex.status === "failed") c.append(mk("div", "rv-expert failed", "The Prompt Expert could not run (" + (ex.error || "?") + ") - these are the agent's own words."));
    const box = mk("textarea", "rv-words"); box.value = words(it); box.rows = 3; box.dataset.orig = box.value;
    box.setAttribute("aria-label", "The prompt - edit it before you approve");
    box.dataset.tipName = "The prompt"; box.dataset.tipWhat = "Edit the words if you want - Approve uses what is in this box.";
    const b = null;   // the long "What it is for" text is replaced by the short facts (Uses / Engine / Makes / Plan)
    let agentWords = null;
    if (it.agent_prompt) {
      agentWords = mk("details", "rv-brief rv-agent");
      const sm = mk("summary"); sm.innerHTML = svg(ICON.brief); sm.append(mk("span", "", "What the agent wrote"));
      agentWords.append(sm, mk("pre", "rv-notes", it.agent_prompt));
    }
    const acts = mk("div", "rv-acts");
    acts.append(
      iconBtn("rv-ok", ICON.ok, "Approve and draw", "Draw it with the words in the box (your edits included).", () => decide(it, "approve", { prompt: box.value }, c)),
      iconBtn("rv-no", ICON.no, "No", "Do not draw this. The note box below says why (optional).", () => decide(it, "reject", { note: note.value }, c)),
      iconBtn("rv-later", ICON.later, "Not now", "Park it: nothing is drawn now. It waits in Parked below, one click to start it later.", () => decide(it, "park", { note: note.value }, c)));
    const note = mk("input", "rv-note-in"); note.type = "text"; note.placeholder = "Note (optional)";
    note.setAttribute("aria-label", "A note for the agent");
    c.append(box); const fx = facts(it); if (fx) c.append(fx); if (agentWords) c.append(agentWords); if (b) c.append(b);
    c.append(mk("div", "rv-row", null)); c.lastChild.append(note, acts);
    c.append(mk("div", "rv-err"));
    if (it.status === "working") { box.disabled = true; acts.hidden = true; note.hidden = true; c.classList.add("working"); }
    return c;
  }

  function resultCard(it) {
    const c = mk("div", "rv-card rv-result"); c.setAttribute("role", "listitem"); c.dataset.id = it.id;
    c.append(head(it));
    const pics = mk("div", "rv-pics");
    const files = (it.files || []).slice(0, 6);
    for (const f of files) {
      if (isPic(f)) { const img = mk("img"); img.alt = f.split(/[\\/]/).pop(); pics.append(img); media(f, img, it); }   // never lazy: WebKit (the Mac's window) does not load lazy pictures inside a scrolling panel
      else pics.append(mk("div", "rv-file", f.split(/[\\/]/).pop()));
    }
    if (!files.length) pics.append(mk("div", "rv-file", "no files"));
    c.append(pics);
    if (words(it)) c.append(mk("div", "rv-asked", words(it)));
    const b = brief(it); if (b) c.append(b);
    const note = mk("input", "rv-note-in"); note.type = "text"; note.placeholder = "What to change (for a retake)";
    note.setAttribute("aria-label", "What to change");
    const acts = mk("div", "rv-acts");
    acts.append(
      iconBtn("rv-ok", ICON.ok, "Approve", it.asset ? "Check it off: it is handed on to the next agent." : "Keep it.", () => decide(it, "approve", {}, c)),
      iconBtn("rv-retake", ICON.retake, "Retake", "Send it back with the note - its prompt comes back here first, nothing is redrawn on its own.",
        () => { if (!note.value.trim()) { note.focus(); note.classList.add("want"); return; } decide(it, "retake", { note: note.value }, c); }),
      iconBtn("rv-later", ICON.later, "Not now", "Park it: nothing goes on now. It waits in Parked below.", () => decide(it, "park", { note: note.value }, c)));
    c.append(mk("div", "rv-row", null)); c.lastChild.append(note, acts);
    c.append(mk("div", "rv-err"));
    return c;
  }

  /** The interview for work nobody watched start (engine/agentsys/interview.py): pick, Go; or As written / Not now. */
  function questionCard(it) {
    const a = it.args || {};
    const c = mk("div", "rv-card rv-question"); c.setAttribute("role", "listitem"); c.dataset.id = it.id;
    const h = mk("div", "rv-head"); h.append(mk("span", "rv-who", it.who || "LOKI"), mk("span", "rv-what", "asks before it starts"), mk("span", "rv-ago", ago(it.t)));
    c.append(h, mk("div", "rv-asked", String(a.text || "").slice(0, 400)));
    if (a.plan) c.append(mk("div", "rv-note", a.plan));
    const picks = {};
    for (const q of a.questions || []) {
      const row = mk("div", "rv-q"); row.append(mk("span", "rv-k", q.header));
      const opts = mk("div", "rv-qopts");
      picks[q.header] = q.multi ? [] : ((q.options[0] || {}).label || "");
      for (const o of q.options || []) {
        const b = mk("button", "rv-qopt", o.label); b.type = "button"; b.dataset.tipName = o.label; b.dataset.tipWhat = o.description || o.label;
        const mark = () => { for (const x of opts.children) { const on = q.multi ? picks[q.header].includes(x.textContent) : picks[q.header] === x.textContent; x.setAttribute("aria-pressed", String(on)); } };
        b.addEventListener("click", () => { if (q.multi) { const l = picks[q.header]; const i = l.indexOf(o.label); if (i >= 0) l.splice(i, 1); else l.push(o.label); } else picks[q.header] = o.label; mark(); });
        opts.append(b); setTimeout(mark, 0);
      }
      row.append(opts); c.append(row);
    }
    const note = mk("input", "rv-note-in"); note.type = "text"; note.placeholder = "Anything else? (optional)";
    const acts = mk("div", "rv-acts");
    acts.append(
      iconBtn("rv-ok", ICON.go, "Go", "Start it with these choices.", () => decide(it, "answer", { answers: picks, note: note.value }, c)),
      iconBtn("rv-retake", ICON.ok, "As written", "Skip the questions - do what it says.", () => decide(it, "go", { note: note.value }, c)),
      iconBtn("rv-later", ICON.later, "Not now", "Park it - nothing is made now.", () => decide(it, "park", { note: note.value }, c)));
    c.append(mk("div", "rv-row", null)); c.lastChild.append(note, acts);
    c.append(mk("div", "rv-err"));
    return c;
  }

  /** An open-source project LOKI uses changed (engine/agentsys/upstream.py): Adopt / Skip / Not now. */
  function upstreamCard(it) {
    const a = it.args || {};
    const c = mk("div", "rv-card rv-upstream"); c.setAttribute("role", "listitem"); c.dataset.id = it.id;
    const h = mk("div", "rv-head"); h.append(mk("span", "rv-who", a.repo || "a project"),
      mk("span", "rv-what", a.status === "behind" ? a.behind + " new commits upstream" : a.status === "new release" ? "new release " + a.release : a.status),
      mk("span", "rv-ago", ago(it.t)));
    c.append(h);
    const facts = mk("div", "rv-facts");
    const row = (k, v) => { if (!v) return; const r = mk("div", "rv-fact"); r.append(mk("span", "rv-k", k), mk("span", "rv-v", v)); facts.append(r); };
    row("LOKI has", a.pin || "not pinned");
    row("Used in", (a.used_in || []).slice(0, 3).join("; "));
    row("Changes", (a.changes || []).slice(-4).join(" · "));
    c.append(facts);
    if (a.compare_url) { const l = mk("a", "rv-link", "See what changed"); l.href = a.compare_url; l.target = "_blank"; l.rel = "noopener"; c.append(l); }
    const note = mk("input", "rv-note-in"); note.type = "text"; note.placeholder = "Note for the agent (optional)";
    const acts = mk("div", "rv-acts");
    acts.append(
      iconBtn("rv-ok", ICON.adopt, "Adopt", "A LOKI agent reads the changes, ports what improves LOKI, updates the pin, runs the tests and ships.", () => decide(it, "adopt", { note: note.value }, c)),
      iconBtn("rv-retake", ICON.skip, "Skip", "Not this version - you hear about the next change.", () => decide(it, "skip", {}, c)),
      iconBtn("rv-later", ICON.later, "Not now", "Park it for later.", () => decide(it, "park", { note: note.value }, c)));
    c.append(mk("div", "rv-row", null)); c.lastChild.append(note, acts);
    c.append(mk("div", "rv-err"));
    return c;
  }

  /** An agent needs a tool that is not installed (engine/installs.py; owner 2026-10-28: "they should install it or
   *  prompt to install ive never been asked anything"): what, why, the exact command. Install / No / Not now. */
  function installCard(it) {
    const a = it.args || {};
    const c = mk("div", "rv-card rv-install"); c.setAttribute("role", "listitem"); c.dataset.id = it.id;
    const h = mk("div", "rv-head");
    h.append(mk("span", "rv-who", it.who || "An agent"),
      mk("span", "rv-what", it.status === "working" ? "is installing what you approved" : "needs a tool installed"),
      mk("span", "rv-ago", ago(it.t)));
    c.append(h);
    const facts = mk("div", "rv-facts");
    const row = (k, v) => { if (!v) return; const r = mk("div", "rv-fact"); r.append(mk("span", "rv-k", k), mk("span", "rv-v", v)); facts.append(r); };
    row("Install", (a.names || []).join(", ") + (a.manager ? " (" + a.manager + ")" : ""));
    row("Why", a.why);
    row("Runs", (a.command || []).map((x) => String(x).split(/[\\/]/).pop()).join(" "));
    if (it.answer) row("Result", it.answer);
    c.append(facts);
    const note = mk("input", "rv-note-in"); note.type = "text"; note.placeholder = "Note (optional)";
    note.setAttribute("aria-label", "A note for the agent");
    const acts = mk("div", "rv-acts");
    acts.append(
      iconBtn("rv-ok", ICON.adopt, "Install", "LOKI installs it now and tries the task that asked again.", () => decide(it, "approve", { note: note.value }, c)),
      iconBtn("rv-no", ICON.no, "No", "Do not install it - the agent finds another way.", () => decide(it, "reject", { note: note.value }, c)),
      iconBtn("rv-later", ICON.later, "Not now", "Park it for later.", () => decide(it, "park", { note: note.value }, c)));
    c.append(mk("div", "rv-row", null)); c.lastChild.append(note, acts);
    c.append(mk("div", "rv-err"));
    if (it.status === "working") { acts.hidden = true; note.hidden = true; c.classList.add("working"); }
    return c;
  }

  /** What the owner said Not now to (engine/agentsys/sendback.py), under the cards. */
  async function parked() {
    if (!panel) return;
    let box = panel.querySelector(".rv-parked");
    const r = await call("/agentsys/parked").catch(() => null);
    const items = (r && r.ok && r.parked) || [];
    S.parkedCount = items.length;
    if (!items.length) { if (box) box.remove(); panel.hidden = !S.items.length; return; }
    if (!box) { box = mk("details", "rv-brief rv-parked"); panel.append(box); }
    // never rebuilt under the owner's fingers: a note being typed in a parked row stays
    if (box.contains(document.activeElement) || [...box.querySelectorAll("input")].some((i) => i.value)) return;
    const open = box.open;
    const sm = mk("summary"); sm.innerHTML = svg(ICON.later); sm.append(mk("span", "", "Parked (" + items.length + ")"));
    const list = mk("div", "rv-parked-list");
    for (const it of items.slice(0, 20)) list.append(window.LokiAgentSys ? LokiAgentSys.parkedRow(it, () => parked()) : mk("div", "", it.request));
    box.replaceChildren(sm, list); box.open = open;
    panel.hidden = false;
  }

  function render() {
    if (!mount()) return;
    const items = S.items;
    panel.hidden = !items.length && !S.parkedCount;   // parked cards keep it up (it blinked every 10 s before)
    const waiting = items.filter((x) => x.status === "waiting").length;
    count.textContent = waiting ? String(waiting) : "";
    count.dataset.tipName = "Waiting for you"; count.dataset.tipWhat = waiting + " card(s) need your OK";
    // keep what the owner is typing: only cards that changed are rebuilt
    const have = new Map([...list.children].map((n) => [n.dataset.id, n]));
    const order = [];
    for (const it of items) {
      const key = it.id + "|" + it.status + "|" + ((it.expert && it.expert.status) || "");
      let n = have.get(it.id);
      const box = n && n.querySelector(".rv-words"), note = n && n.querySelector(".rv-note-in");
      const typing = n && ((box && (document.activeElement === box || box.value !== box.dataset.orig))
                           || (note && (document.activeElement === note || note.value)));
      const build = { prompt: promptCard, question: questionCard, upstream: upstreamCard, install: installCard }[it.kind] || resultCard;
      if (!n || (n.dataset.key !== key && !typing)) { n = build(it); n.dataset.key = key; }
      order.push(n);
    }
    list.replaceChildren(...order);
  }

  async function refresh(now) {
    const hub = document.getElementById("home-hub");
    if (!now && (!hub || hub.hidden || document.hidden)) return;   // only while Home is on screen
    const r = await call("/review").catch(() => null);
    if (!r || !r.ok) return;
    // the owner's turn first (results before prompts - a hand-off holds up an agent), then what is being drawn
    const rank = (x) => (x.status === "working" ? 2 : x.kind === "result" ? 0 : 1);
    S.items = (r.waiting || []).slice().sort((a, b) => rank(a) - rank(b) || a.t - b.t);
    render();
    parked();
  }

  function start() {
    let tries = 0;
    const wait = setInterval(() => {   // Home builds itself after the app is up
      if (mount() || ++tries > 120) { clearInterval(wait); refresh(true); }
    }, 500);
    S.timer = setInterval(() => refresh(false), EVERY_MS);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(false); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
  return { refresh, render, state: S };
})();
window.LokiHomeReview = LokiHomeReview;
