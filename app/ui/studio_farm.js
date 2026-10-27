// Studio = the render farm manager (owner 2026-10-25: "i want the render to be more like a render farm and management
// software like eclipse using ai ... using gpu, change the name to studio"). The Studio tab (mode id "render") gets
// two views on a sub-bar: Farm - a Deadline / Eclipse-style Monitor over engine/render_farm.py (jobs with priority,
// pool, dependencies, progress, worker and ETA; every GPU worker with its VRAM and status; the farm doctor's reading of
// each failure; the render history) - and Render, the Render Studio as it was (render_studio.js: passes, preview,
// AI Renderer settings). A render made in Render is sent to the farm with Submit.
// Plain DOM, CSP script-src 'self'; api() from app.js; sizes in %; every button an icon or a short word with a tooltip.
"use strict";

const LokiStudioFarm = (() => {
  const S = { root: null, tasks: null, agents: null, farm: null, render: null, view: "tasks", timer: 0, data: null, sel: null, rjobs: [] };
  const STORE = "loki-studio-view";
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.reject(new Error("not ready")));
  const gb = (b) => (b ? (b / 1e9).toFixed(1) + " GB" : "-");
  const dur = (s) => (s == null ? "-" : s < 90 ? Math.round(s) + " s" : s < 5400 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1) + " h");
  const ago = (t) => (t ? dur(Date.now() / 1000 - t) + " ago" : "");
  function btn(label, tip, fn, cls) {
    const b = mk("button", "sf-btn" + (cls ? " " + cls : ""), label); b.type = "button";
    b.title = tip; b.dataset.tipName = label; b.dataset.tipWhat = tip; b.setAttribute("aria-label", label);
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(e); });
    return b;
  }
  const stop = (n) => { n.addEventListener("keydown", (e) => e.stopPropagation()); return n; };

  // ------------------------------------------------------------------ the shell: Farm | Render
  function open(p, opts) {
    if (!S.root) build(p);
    let v = S.view;
    try { v = localStorage.getItem(STORE) || v; } catch (_) { /* private window */ }
    if (opts && (opts.job || opts.fromForge)) v = "render";      // a project card / Forge asked for the Render view
    if (opts && opts.view) v = opts.view;                          // Home's live view asks for Agents
    show(v, opts);
  }
  function build(p) {
    p.classList.add("sf-pane");
    const bar = mk("div", "sf-views"); bar.setAttribute("role", "tablist"); bar.setAttribute("aria-label", "Studio view");
    for (const [id, label, tip] of [["tasks", "Tasks", "What the agents were asked to do on this computer: finished, failed (and why), being tried again, working now."],
      ["agents", "Agents", "Every agent at work on every machine, with Stop and Again - and Make: art, paintings, 3D models, comics, novels, websites, games."],
      ["farm", "Farm", "The render farm: every job and GPU worker, priorities, failures and their fixes, the history."],
      ["render", "Render", "Render Studio: render the passes from a Forge camera, the AI Renderer settings, the preview."]]) {
      const b = mk("button", "sf-view", label); b.type = "button"; b.dataset.view = id; b.setAttribute("role", "tab");
      b.title = tip; b.dataset.tipName = label; b.dataset.tipWhat = tip;
      b.addEventListener("click", () => show(id));
      bar.append(b);
    }
    // the work strip (every background agent and team, Clear finished) moved here from under the Home chat
    // (owner 2026-10-26: "remove the agent working and team from loki home chat move them over to lab")
    S.work = mk("div", "sf-work");
    const strip = document.getElementById("work");
    if (strip) { S.work.append(strip); strip.classList.remove("collapsed"); }
    S.tasks = mk("div", "sf-tasks"); S.tasks.hidden = true;
    S.agents = mk("div", "sf-agents"); S.agents.id = "studio-agents"; S.agents.hidden = true;
    S.farm = mk("div", "sf-farm"); S.farm.id = "studio-farm";
    S.render = mk("div", "sf-render"); S.render.hidden = true;
    p.append(bar, S.tasks, S.work, S.agents, S.farm, S.render);
    S.root = p;
    buildFarm(S.farm);
  }
  function show(v, opts) {
    // Tasks first (owner 2026-10-27: "there should be a clear finished jobs and tasks"), then Agents
    S.view = v === "render" || v === "farm" || v === "agents" ? v : "tasks";
    try { localStorage.setItem(STORE, S.view); } catch (_) { /* private window */ }
    for (const b of S.root.querySelectorAll(".sf-view")) b.setAttribute("aria-selected", String(b.dataset.view === S.view));
    S.agents.hidden = S.view !== "agents"; S.farm.hidden = S.view !== "farm"; S.render.hidden = S.view !== "render";
    S.tasks.hidden = S.view !== "tasks";
    if (S.view !== "tasks" && window.LokiTaskBoard) window.LokiTaskBoard.leave();
    S.work.hidden = S.view !== "agents";
    if (S.view === "agents" && typeof refreshJobs === "function") refreshJobs();
    if (S.view !== "agents" && window.LokiStudioAgents) window.LokiStudioAgents.leave();
    if (S.view === "tasks") {
      clearInterval(S.timer); S.timer = 0;
      if (window.LokiRenderStudio) window.LokiRenderStudio.leave();
      if (window.LokiStudioAgents) window.LokiStudioAgents.leave();
      if (window.LokiTaskBoard) window.LokiTaskBoard.open(S.tasks);
      else S.tasks.textContent = "The task board is not in this window.";
    } else if (S.view === "agents") {
      clearInterval(S.timer); S.timer = 0;
      if (window.LokiRenderStudio) window.LokiRenderStudio.leave();
      if (window.LokiStudioAgents) window.LokiStudioAgents.open(S.agents);
      else S.agents.textContent = "The Agents view is not in this window.";
    } else if (S.view === "render") {
      clearInterval(S.timer); S.timer = 0;
      if (window.LokiRenderStudio) window.LokiRenderStudio.open(S.render, opts || {});
      else S.render.textContent = "Render Studio is not in this window.";
    } else {
      if (window.LokiRenderStudio) window.LokiRenderStudio.leave();
      refresh();
      clearInterval(S.timer);
      S.timer = setInterval(() => { if (S.root && !S.root.hidden && !S.farm.hidden && !document.hidden) refresh(); }, 2000);
    }
  }
  function leave() { clearInterval(S.timer); S.timer = 0; if (window.LokiTaskBoard) window.LokiTaskBoard.leave(); if (window.LokiRenderStudio) window.LokiRenderStudio.leave(); if (window.LokiStudioAgents) window.LokiStudioAgents.leave(); }

  // ------------------------------------------------------------------ the Farm Monitor
  function buildFarm(f) {
    const stats = mk("div", "sf-stats"); stats.id = "sf-stats";
    const grid = mk("div", "sf-grid");
    const jobs = mk("section", "sf-box sf-jobs");
    const jhead = mk("div", "sf-head");
    jhead.append(mk("h3", "", "Jobs"), btn("Submit", "Send a render to the farm: pick one made in Render (its passes are in), its priority, pool and what it waits for.", () => toggleSubmit()));
    const submit = mk("form", "sf-submit"); submit.id = "sf-submit"; submit.hidden = true;
    jobs.append(jhead, submit, mk("div", "sf-table sf-jobtable"));
    const detail = mk("section", "sf-box sf-detail"); detail.id = "sf-detail";
    const workers = mk("section", "sf-box sf-workers");
    const whead = mk("div", "sf-head");
    const addf = mk("form", "sf-addworker");
    const url = stop(mk("input")); url.placeholder = "http://192.168.1.50:8188"; url.setAttribute("aria-label", "ComfyUI address of a new worker");
    const nm = stop(mk("input")); nm.placeholder = "Name"; nm.setAttribute("aria-label", "Worker name");
    const go = mk("button", "sf-btn", "Add"); go.type = "submit"; go.title = "Add a GPU worker: any machine running ComfyUI with --listen.";
    addf.append(url, nm, go);
    addf.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!url.value.trim()) return;
      const r = await call("/farm/worker", { url: url.value.trim(), name: nm.value.trim() });
      say(r.ok ? "Worker added - it shows online once its ComfyUI answers." : r.error, !r.ok);
      if (r.ok) { url.value = ""; nm.value = ""; refresh(); }
    });
    whead.append(mk("h3", "", "Workers"), addf);
    workers.append(whead, mk("div", "sf-table sf-worktable"));
    const hist = mk("section", "sf-box sf-history");
    hist.append(mk("h3", "", "History"), mk("div", "sf-histlist"));
    const note = mk("p", "sf-note"); note.id = "sf-note";
    grid.append(jobs, detail, workers, hist);
    f.append(stats, grid, note);
  }
  function say(t, bad) { const n = document.getElementById("sf-note"); if (n) { n.textContent = t || ""; n.classList.toggle("bad", !!bad); } }

  async function refresh() {
    let d;
    try { d = await call("/farm/status"); } catch (e) { say(e.message, true); return; }
    if (!d || !d.ok) { say((d && d.error) || "LOKI's engine does not answer.", true); return; }
    d.jobs = d.jobs || []; d.workers = d.workers || []; d.history = d.history || []; d.stats = d.stats || {};
    S.data = d;
    drawStats(d); drawJobs(d); drawWorkers(d); drawHistory(d); drawDetail();
  }
  function drawStats(d) {
    const s = d.stats || {}, box = document.getElementById("sf-stats");
    box.replaceChildren();
    for (const [k, v, tip] of [["Workers", (s.online || 0) + " / " + (s.workers || 0), "GPU workers online / known."],
      ["Rendering", s.active || 0, "Jobs rendering now."], ["Queued", s.queued || 0, "Jobs waiting for a worker."],
      ["Failed", s.failed || 0, "Jobs that hit their error limit - the doctor says why."], ["Free VRAM", gb(s.vram_free), "Video memory free across the online workers."]]) {
      const t = mk("div", "sf-stat"); t.title = tip;
      t.append(mk("b", "", String(v)), mk("span", "", k)); box.append(t);
    }
  }
  function row(cells, cls) { const r = mk("div", "sf-row" + (cls ? " " + cls : "")); for (const c of cells) r.append(c instanceof Node ? c : mk("span", "", c == null ? "" : String(c))); return r; }
  function bar(frac) { const b = mk("span", "sf-bar"); const i = mk("i"); i.style.width = Math.round(Math.max(0, Math.min(1, frac || 0)) * 100) + "%"; b.append(i); return b; }

  function drawJobs(d) {
    const t = S.farm.querySelector(".sf-jobtable"); t.replaceChildren();
    t.append(row(["Name", "Status", "Priority", "Pool", "Progress", "Worker", "ETA", ""], "sf-th"));
    if (!d.jobs.length) t.append(mk("p", "sf-empty", "No farm jobs. Render the passes in the Render view, then Submit them here - the farm picks the best free GPU."));
    const names = Object.fromEntries((d.workers || []).map((w) => [w.url, w.name]));
    for (const j of d.jobs) {
      const pr = stop(mk("input", "sf-prio")); pr.type = "number"; pr.min = "0"; pr.max = "100"; pr.value = String(j.priority);
      pr.title = "Priority 0-100: higher renders first."; pr.addEventListener("click", (e) => e.stopPropagation());
      pr.addEventListener("change", () => act(j.id, "priority", +pr.value));
      const acts = mk("span", "sf-acts");
      if (j.status === "queued") acts.append(btn("Suspend", "Hold it in the queue.", () => act(j.id, "suspend")));
      if (j.status === "suspended") acts.append(btn("Resume", "Back into the queue.", () => act(j.id, "resume")));
      if (["failed", "completed", "cancelled", "suspended"].includes(j.status)) acts.append(btn("Requeue", "Render it again (a fresh attempt, errors and blacklist cleared).", () => act(j.id, "requeue")));
      if (!["failed", "completed", "cancelled"].includes(j.status)) acts.append(btn("Cancel", "Stop it (the worker's ComfyUI is told to interrupt).", () => act(j.id, "cancel")));
      if (j.status !== "active") acts.append(btn("Delete", "Take it off the list (the render's files stay in Render).", () => act(j.id, "delete")));
      const r = row([j.name, mk("span", "sf-st sf-st-" + j.status, j.status + (j.errors && j.errors.length ? " (" + j.errors.length + "/" + j.max_errors + ")" : "")),
        pr, j.pool, bar(j.progress), j.worker ? (names[j.worker] || j.worker) : "-", j.eta != null ? dur(j.eta) : "-", acts], "sf-jobrow" + (S.sel === j.id ? " on" : ""));
      r.addEventListener("click", () => { S.sel = j.id; drawJobs(S.data); drawDetail(); });
      t.append(r);
    }
  }
  function drawDetail() {
    const box = document.getElementById("sf-detail"); if (!box) return;
    box.replaceChildren(mk("h3", "", "Job"));
    const j = S.data && S.data.jobs.find((x) => x.id === S.sel);
    if (!j) { box.append(mk("p", "sf-empty", "Pick a job: its log, what it waits for, and the farm doctor's reading of any failure.")); return; }
    box.append(mk("p", "sf-dname", j.name),
      mk("p", "sf-small", "Render job " + j.attempts[j.attempts.length - 1] + " - " + (j.frames || "?") + " frames - " + (j.workflow || "") +
        (j.depends && j.depends.length ? " - waits for " + j.depends.length + " job(s)" : "") + (j.blacklist && j.blacklist.length ? " - not on " + j.blacklist.join(", ") : "")));
    if (j.doctor && j.doctor.length) {
      const doc = mk("div", "sf-doctor");
      doc.append(mk("b", "", "Farm doctor"));
      for (const x of j.doctor) { const it = mk("div", "sf-dx"); it.append(mk("span", "sf-cause", x.cause), mk("span", "sf-fix", x.fix)); doc.append(it); }
      box.append(doc);
    }
    const log = mk("ul", "sf-log");
    for (const [t, m] of (j.log || []).slice().reverse()) log.append(mk("li", "", ago(t) + " - " + m));
    box.append(log);
    const view = btn("Open in Render", "See this render's passes and result in the Render view.", () => show("render", { job: j.attempts[j.attempts.length - 1] }));
    box.append(view);
  }
  function drawWorkers(d) {
    const t = S.farm.querySelector(".sf-worktable"); t.replaceChildren();
    t.append(row(["Worker", "GPU", "VRAM free", "Status", "Pools", "Done / failed", ""], "sf-th"));
    if (!d.workers.length) t.append(mk("p", "sf-empty", "No workers yet. Start ComfyUI with --listen on a GPU machine (the PC's RTX 3070 Ti), then add its address above - linked LOKI machines are tried by themselves."));
    for (const w of d.workers) {
      const st = !w.enabled ? "disabled" : !w.online ? "offline" : w.rendering || w.busy ? "rendering" : "idle";
      const vram = mk("span", "sf-vram");
      if (w.vram_total) { vram.append(bar(w.vram_free / w.vram_total), mk("small", "", gb(w.vram_free) + " / " + gb(w.vram_total))); } else vram.textContent = "-";
      const pools = stop(mk("input", "sf-pools")); pools.value = (w.pools || ["gpu"]).join(", ");
      pools.title = "Pools this worker takes jobs from (comma separated). A job's pool must be here, or 'any'.";
      pools.addEventListener("change", () => setWorker(w.url, { pools: pools.value }));
      const acts = mk("span", "sf-acts");
      acts.append(btn(w.enabled ? "Disable" : "Enable", w.enabled ? "Stop giving this worker jobs." : "Give this worker jobs again.", () => setWorker(w.url, { enabled: !w.enabled })));
      if (w.source === "added") acts.append(btn("Remove", "Forget this worker.", () => setWorker(w.url, { remove: true })));
      const st_ = mk("span", "sf-st sf-st-" + st, st); st_.title = w.online ? (w.os || "") + (w.comfyui ? " - ComfyUI " + w.comfyui : "") : (w.why || "");
      const name = mk("span", "", w.name); name.title = w.url + " (" + w.source + ")";
      t.append(row([name, w.gpu || "-", vram, st_, pools, (w.ok || 0) + " / " + (w.failed || 0), acts], "sf-workrow"));
    }
  }
  function drawHistory(d) {
    const l = S.farm.querySelector(".sf-histlist"); l.replaceChildren();
    if (!d.history.length) { l.append(mk("p", "sf-empty", "Finished jobs land here and stay (the last 500).")); return; }
    for (const h of d.history.slice(0, 30)) l.append(row([h.name, mk("span", "sf-st sf-st-" + h.status, h.status), h.secs != null ? dur(h.secs) : "-", ago(h.finished)], "sf-histrow"));
  }

  async function act(id, action, value) {
    const r = await call("/farm/job", { id, action, value });
    say(r.ok ? "" : r.error, !r.ok);
    refresh();
  }
  async function setWorker(url, data) {
    const r = await call("/farm/worker", Object.assign({ url }, data));
    say(r.ok ? "" : r.error, !r.ok);
    refresh();
  }

  async function toggleSubmit() {
    const f = document.getElementById("sf-submit");
    f.hidden = !f.hidden;
    if (f.hidden) return;
    let r; try { r = await call("/render/status"); } catch (_) { r = null; }
    const jobs = ((r && r.jobs) || []).filter((j) => j.kind === "ai" && j.status === "idle");
    f.replaceChildren();
    if (!jobs.length) {
      f.append(mk("p", "sf-empty", "No render ready to send: in Render, render the passes from a Forge camera (AI Renderer), then come back."),
        btn("Go to Render", "Open the Render view.", () => show("render")));
      return;
    }
    const pick = mk("select"); for (const j of jobs) pick.append(new Option(j.name + " (" + (j.frames || "?") + " frames)", j.job));
    const prio = stop(mk("input")); prio.type = "range"; prio.min = "0"; prio.max = "100"; prio.value = "50";
    const pv = mk("output", "", "50"); prio.addEventListener("input", () => { pv.textContent = prio.value; });
    const pool = stop(mk("input")); pool.value = "gpu"; pool.title = "The pool it renders in (a worker must have it; 'any' = every worker).";
    const errs = stop(mk("input")); errs.type = "number"; errs.min = "1"; errs.max = "20"; errs.value = "3"; errs.title = "Errors before it stops trying.";
    const dep = mk("select"); dep.append(new Option("starts now", ""));
    for (const j of (S.data ? S.data.jobs : []).filter((x) => !["completed", "failed", "cancelled"].includes(x.status))) dep.append(new Option("after " + j.name, j.id));
    const lab = (t, n) => { const l = mk("label", "sf-field"); l.append(mk("span", "", t), n); return l; };
    const go = mk("button", "sf-btn primary", "Submit"); go.type = "submit";
    f.append(lab("Render", pick), lab("Priority", prio), pv, lab("Pool", pool), lab("Max errors", errs), lab("Waits for", dep), go);
    f.onsubmit = async (e) => {
      e.preventDefault();
      const res = await call("/farm/submit", { render_job: pick.value, priority: +prio.value, pool: pool.value.trim() || "gpu",
        max_errors: +errs.value || 3, depends: dep.value ? [dep.value] : [] });
      say(res.ok ? "Submitted - the farm starts it on the best free GPU." : res.error, !res.ok);
      if (res.ok) { f.hidden = true; S.sel = res.job.id; refresh(); }
    };
  }

  return { open, show, leave, refresh, state: S };
})();
window.LokiStudioFarm = LokiStudioFarm;
if (window.LokiModeBar && typeof window.LokiModeBar.register === "function") {
  window.LokiModeBar.register("render", { enter: (p, o) => LokiStudioFarm.open(p, o), leave: () => LokiStudioFarm.leave() });
}
