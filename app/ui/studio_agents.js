// Studio > Agents (owner 2026-10-25 11:20: "the studio should be a place i can see my agents working as well and other
// machines. why do i only see one machine? and i should be able to have some sort of control over what im doing ... i
// want them to make real things like art 3d models or paintings comic books novels real websites").
//   Make      pick what to make (Art, Painting, 3D model, Comic book, Novel, Website, Game), say what, pick the machine:
//             a real job in ~/LOKI Projects/<Kind>/<name> (engine/studio_agents.py POST /studio/make)
//   Machines  this computer and every linked one (online, OS, how many agents working); only one: link the other here
//   Agents    everyone at work on every machine - what, where, the stage, the last thing said, a live screen when there
//             is one - with Stop, Again and the output (POST /studio/agents/stop | again)
// Plain DOM, CSP script-src 'self'; api() from app.js; polls every 2 s while it shows. Home's live view uses LokiStudioAgents.data().
"use strict";

const LokiStudioAgents = (() => {
  const S = { root: null, data: null, timer: 0, kind: "art", busy: false, open: new Set(), shots: {} };
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.reject(new Error("not ready")));
  const ago = (t) => { if (!t) return ""; const s = Math.max(0, Date.now() / 1000 - t); return s < 90 ? Math.round(s) + " s" : s < 5400 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1) + " h"; };
  const KIND_TIP = {
    art: "Finished artwork: the look decided, pictures drawn in rounds, the best kept with captions.",
    painting: "A real painting (oil, acrylic, watercolour, ink): the medium and brushwork in every picture.",
    "3d": "A 3D model: clean reference pictures first, then the model (.glb/.obj) - it opens in Forge.",
    comic: "A comic book: the script, every panel drawn with the same characters, the pages put together and checked.",
    novel: "A novel: the outline, the characters, then real chapters - and a cover.",
    website: "A real website: real pages and copy, pictures made for it, checked in a browser.",
    game: "A small playable game: planned, built, its art made, run and fixed.",
  };
  function btn(label, tip, fn, cls) {
    const b = mk("button", "sa-btn" + (cls ? " " + cls : ""), label); b.type = "button";
    b.title = tip; b.dataset.tipName = label; b.dataset.tipWhat = tip; b.setAttribute("aria-label", label);
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(e); });
    return b;
  }
  const keep = (n) => { n.addEventListener("keydown", (e) => e.stopPropagation()); return n; };   // typing never triggers app keys

  // ------------------------------------------------------------------ build
  function build(p) {
    p.classList.add("sa-pane");
    // --- Make
    const make = mk("section", "sa-make"); make.setAttribute("aria-label", "Make something");
    const kinds = mk("div", "sa-kinds"); kinds.setAttribute("role", "radiogroup"); kinds.setAttribute("aria-label", "What to make");
    const brief = keep(mk("textarea", "sa-brief")); brief.id = "sa-brief"; brief.rows = 2;
    brief.placeholder = "What should it be? e.g. a moody oil painting of a lighthouse in a storm";
    brief.setAttribute("aria-label", "What to make");
    const name = keep(mk("input", "sa-name")); name.id = "sa-name"; name.type = "text"; name.placeholder = "Name (optional)"; name.setAttribute("aria-label", "Name");
    const where = mk("select", "sa-where"); where.id = "sa-where"; where.setAttribute("aria-label", "Which machine");
    const go = btn("Make it", "Start an agent on it now. It works in its own folder in LOKI Projects; you see it below.", () => start(), "primary");
    go.id = "sa-go";
    const say = mk("div", "sa-say"); say.id = "sa-say"; say.setAttribute("aria-live", "polite");
    const row = mk("div", "sa-make-row"); row.append(name, where, go);
    make.append(kinds, brief, row, say);
    // --- Machines + Agents
    const machines = mk("section", "sa-machines"); machines.id = "sa-machines"; machines.setAttribute("aria-label", "Machines");
    const agents = mk("section", "sa-agents"); agents.id = "sa-agents"; agents.setAttribute("aria-label", "Agents at work");
    p.append(make, machines, agents);
    S.root = p; S.els = { kinds, brief, name, where, go, say, machines, agents };
    paintKinds([]);
  }
  function paintKinds(list) {
    const k = S.els.kinds;
    const LABEL = { art: "Art", painting: "Painting", "3d": "3D model", comic: "Comic book", novel: "Novel", website: "Website", game: "Game" };
    const items = list.length ? list : Object.keys(KIND_TIP).map((id) => ({ id, label: LABEL[id] || id }));
    if (k.childElementCount === items.length && items.every((it, i) => k.children[i].textContent === it.label)) return;
    k.replaceChildren();
    for (const it of items) {
      const b = mk("button", "sa-kind", it.label); b.type = "button"; b.dataset.kind = it.id; b.setAttribute("role", "radio");
      b.title = KIND_TIP[it.id] || ""; b.dataset.tipName = it.label; b.dataset.tipWhat = KIND_TIP[it.id] || "";
      b.addEventListener("click", () => { S.kind = it.id; for (const x of k.children) x.setAttribute("aria-checked", String(x === b)); });
      b.setAttribute("aria-checked", String(it.id === S.kind));
      k.append(b);
    }
  }

  // ------------------------------------------------------------------ data
  async function refresh() {
    if (S.busy) return;
    S.busy = true;
    try {
      const d = await call("/studio/agents");
      if (d && d.ok) { S.data = d; paint(); }
    } catch (_) { /* the engine is restarting: try again next tick */ }
    finally { S.busy = false; }
  }
  function paint() {
    const d = S.data; if (!d || !S.root) return;
    paintKinds(d.kinds || []);
    // machine picker
    const w = S.els.where, keepVal = w.value;
    const opts = (d.machines || []).filter((m) => m.self || (m.ok && !m.farm));
    if (w.childElementCount !== opts.length || [...w.options].some((o, i) => o.value !== (opts[i].self ? "" : opts[i].name))) {
      w.replaceChildren(...opts.map((m) => new Option(m.self ? "This computer (" + m.name + ")" : m.name, m.self ? "" : m.name)));
      w.value = [...w.options].some((o) => o.value === keepVal) ? keepVal : "";
    }
    // machines
    const box = S.els.machines; box.replaceChildren();
    const head = mk("div", "sa-head"); head.append(mk("h3", "", "Machines"), mk("span", "sa-count", (d.machines || []).length + ""));
    box.append(head);
    const strip = mk("div", "sa-mstrip");
    for (const m of d.machines || []) {
      const c = mk("div", "sa-machine" + (m.ok ? " on" : " off") + (m.self ? " self" : ""));
      c.dataset.machine = m.name;
      const top = mk("div", "sa-mtop"); top.append(mk("i", "sa-dot"), mk("b", "", m.name));
      if (m.self) top.append(mk("span", "sa-tag", "this computer"));
      else if (m.farm) top.append(mk("span", "sa-tag", "farm"));
      c.append(top);
      const facts = [m.os, m.ok ? (m.working ? m.working + " working" : "idle") : "not reachable", m.queued ? m.queued + " waiting" : "",
        m.ms ? m.ms + " ms" : "", m.gpu || ""].filter(Boolean);
      c.append(mk("div", "sa-mfacts", facts.join(" · ")));
      if (!m.ok && m.error) c.append(mk("div", "sa-err", m.error));
      strip.append(c);
    }
    box.append(strip);
    if (d.hint) box.append(linkBox(d.hint));
    // agents
    const list = S.els.agents; list.replaceChildren();
    const ah = mk("div", "sa-head"); ah.append(mk("h3", "", "Agents at work"), mk("span", "sa-count", (d.agents || []).length + ""));
    list.append(ah);
    if (!(d.agents || []).length) {
      list.append(mk("p", "sa-empty", "Nobody is working right now. Pick what to make above and press Make it - you will see the agent here, on whichever machine it runs."));
      return;
    }
    const grid = mk("div", "sa-grid");
    for (const a of d.agents) grid.append(card(a));
    list.append(grid);
  }
  function linkBox(hint) {
    const b = mk("div", "sa-link"); b.id = "sa-link";
    b.append(mk("p", "", hint));
    const code = keep(mk("input", "sa-code")); code.type = "text"; code.placeholder = "Paste the other machine's link code"; code.setAttribute("aria-label", "Link code");
    const out = mk("span", "sa-say");
    const link = btn("Link", "Link this computer with the other one, using the code it shows in Settings > Machines.", async () => {
      if (!code.value.trim()) { out.textContent = "Paste the code first."; return; }
      out.textContent = "Linking...";
      const r = await call("/peers/link", { code: code.value.trim() }).catch((e) => ({ ok: false, error: e.message }));
      out.textContent = r && r.ok ? "Linked " + (r.name || "") + ". It shows here in a few seconds." : "Not linked: " + ((r && r.error) || "no answer");
      if (r && r.ok) { code.value = ""; refresh(); }
    });
    const r = mk("div", "sa-make-row"); r.append(code, link, out);
    b.append(r);
    return b;
  }
  function card(a) {
    const key = (a.machine || "") + ":" + (a.job || a.id);
    const c = mk("article", "sa-card st-" + (a.status || a.state || "idle"));
    c.dataset.agent = a.id; c.dataset.machine = a.machine || ""; if (a.job) c.dataset.job = a.job;
    const top = mk("div", "sa-ctop");
    top.append(mk("span", "sa-pill", a.status || a.state || ""), mk("b", "sa-title", a.task || a.name || "LOKI"));
    c.append(top);
    const meta = [a.name, a.machine ? "on " + a.machine : "", a.stage ? "stage: " + a.stage : "", a.since ? ago(a.since) : "",
      a.folder ? "folder " + a.folder : (a.workspace ? "folder " + a.workspace.split(/[\\/]/).pop() : "")].filter(Boolean);
    c.append(mk("div", "sa-meta", meta.join(" · ")));
    const line = a.last_message || a.note || "";
    if (line) c.append(mk("div", "sa-line", line));
    if (a.error) c.append(mk("div", "sa-err", a.error));
    if (a.screenshot && a.job && !a.remote) {      // the job's live screen (a browser or a desktop it drives)
      const img = mk("img", "sa-shot"); img.alt = "What the agent sees"; c.append(img);
      call("/jobs/screenshot?id=" + encodeURIComponent(a.job)).then((r) => { if (r && r.ok) img.src = r.image; }).catch(() => {});
    }
    const acts = mk("div", "sa-acts");
    if (a.can_stop && a.job) acts.append(btn("Stop", "Stop this agent now (on " + (a.machine || "this computer") + ").", () => control("stop", a)));
    if (a.job && !a.can_stop) acts.append(btn("Again", "Run the same brief once more, as a fresh job.", () => control("again", a)));
    if (a.job && !a.remote) acts.append(btn(S.open.has(key) ? "Hide output" : "Output", "What it has written so far.", () => { S.open.has(key) ? S.open.delete(key) : S.open.add(key); paint(); }));
    if (acts.childElementCount) c.append(acts);
    if (S.open.has(key)) {
      const pre = mk("pre", "sa-out", "..."); c.append(pre);
      call("/jobs").then((r) => { const j = ((r && r.jobs) || []).find((x) => x.id === a.job); pre.textContent = (j && (j.output || j.note || j.error)) || "Nothing yet."; }).catch(() => {});
    }
    return c;
  }

  // ------------------------------------------------------------------ the controls
  async function control(what, a) {
    const say = S.els.say;
    say.textContent = (what === "stop" ? "Stopping " : "Starting again: ") + (a.task || a.name) + "...";
    const r = await call("/studio/agents/" + what, { machine: a.remote ? a.machine : "", job: a.job }).catch((e) => ({ ok: false, error: e.message }));
    say.textContent = r && r.ok ? (what === "stop" ? "Stopped." : "Started again.") : "Could not: " + ((r && r.error) || "no answer");
    refresh();
  }
  async function start() {
    const { brief, name, where, say } = S.els;
    const text = brief.value.trim();
    if (!text) { say.textContent = "Say what to make first."; brief.focus(); return; }
    say.textContent = "Starting...";
    const r = await call("/studio/make", { kind: S.kind, brief: text, name: name.value.trim(), machine: where.value })
      .catch((e) => ({ ok: false, error: e.message }));
    if (r && r.ok) {
      say.textContent = "Started on " + (r.machine || "this computer") + (r.folder ? " - it works in " + r.folder : "") + ".";
      brief.value = ""; name.value = "";
    } else say.textContent = "Not started: " + ((r && r.error) || "no answer");
    refresh();
  }

  function open(p) {
    if (!S.root) build(p);
    refresh();
    clearInterval(S.timer);
    S.timer = setInterval(() => { if (S.root && S.root.offsetParent !== null && !document.hidden) refresh(); }, 2000);
  }
  function leave() { clearInterval(S.timer); S.timer = 0; }
  return { open, leave, refresh, data: () => S.data, start, control };
})();
window.LokiStudioAgents = LokiStudioAgents;
