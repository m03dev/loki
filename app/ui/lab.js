// Settings > Lab: LOKI growing its own personal-agent core (engine/evolve.py, docs/EVOLVE.md).
// GET /evolve lists the steps (your ideas first), what happened to each, and the lessons the
// next attempt is given; POST /evolve/idea adds your idea, /evolve/start starts the next step
// now, /evolve/approve accepts or declines an idea LOKI proposed. Plain DOM (CSP).
// Session 28: the Lab also shows the speed watch (GET /speed, E6), the job success dashboard
// (GET /jobs/stats: success over time, by model, by kind, failure reasons, retry on a stronger
// model, the daily self-test) and runs the weekly self-review on demand (E8). Settings > Tools
// lists the tools LOKI wrote for itself (GET /user_tools, E9).
"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";

function labChip(item, isNext) {
  const last = item.last || {};
  if (item.done) return el("span", "state ready", item.declined ? "declined" : "done");
  if (item.approved === false) return el("span", "state", "waiting for your OK");
  if (last.outcome === "started") return el("span", "state working", "LOKI is building it");
  if (last.outcome === "failed") return el("span", "state warn", "did not ship - will retry");
  return el("span", "state", isNext ? "next up" : "planned");
}

function svg(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
  return node;
}

// A small line of the last values (oldest left), with the newest point marked.
function sparkline(values, label) {
  const w = 120, h = 26, pad = 2;
  const box = svg("svg", { viewBox: "0 0 " + w + " " + h, width: w, height: h, class: "spark", role: "img" });
  box.setAttribute("aria-label", label + ": " + (values.length ? values.length + " measurements" : "no measurements yet"));
  if (!values.length) { box.append(svg("line", { x1: pad, y1: h / 2, x2: w - pad, y2: h / 2, class: "spark-empty" })); return box; }
  const max = Math.max(...values), min = Math.min(...values);
  const span = max - min || 1;
  const step = values.length > 1 ? (w - 2 * pad) / (values.length - 1) : 0;
  const pts = values.map((v, i) => [pad + i * step, h - pad - ((v - min) / span) * (h - 2 * pad)]);
  box.append(svg("polyline", { points: pts.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" "), class: "spark-line" }));
  const last = pts[pts.length - 1];
  box.append(svg("circle", { cx: last[0].toFixed(1), cy: last[1].toFixed(1), r: 2.2, class: "spark-dot" }));
  return box;
}

function fmtMs(ms) {
  if (!ms) return "—";
  if (ms < 1000) return Math.round(ms) + " ms";
  if (ms < 90000) return (ms / 1000).toFixed(1) + " s";
  return (ms / 60000).toFixed(1) + " min";
}

function pct(rate) { return rate === null || rate === undefined ? "—" : Math.round(rate * 100) + "%"; }

// One bar per day: height = success rate; days with no job are a thin grey tick.
function dayBars(days) {
  const w = 600, h = 90, gap = 2;
  const bw = Math.max(3, (w - gap * (days.length - 1)) / Math.max(days.length, 1));
  const box = svg("svg", { viewBox: "0 0 " + w + " " + (h + 16), class: "daybars", role: "img", preserveAspectRatio: "none" });
  box.setAttribute("aria-label", "Job success rate per day");
  days.forEach((d, i) => {
    const x = i * (bw + gap);
    if (!d.n) { box.append(svg("rect", { x: x.toFixed(1), y: h - 2, width: bw.toFixed(1), height: 2, class: "bar-none" })); return; }
    const bh = Math.max(3, d.rate * h);
    const r = svg("rect", { x: x.toFixed(1), y: (h - bh).toFixed(1), width: bw.toFixed(1), height: bh.toFixed(1),
      class: d.rate >= 0.8 ? "bar-good" : d.rate >= 0.5 ? "bar-mid" : "bar-bad" });
    const t = svg("title");
    t.textContent = d.day + ": " + d.ok + " of " + d.n + " jobs worked (" + pct(d.rate) + ")";
    r.append(t);
    box.append(r);
  });
  [0, Math.floor(days.length / 2), days.length - 1].forEach((i) => {
    if (!days[i]) return;
    const label = svg("text", { x: (i * (bw + gap) + bw / 2).toFixed(1), y: h + 13, class: "bar-label", "text-anchor": i === 0 ? "start" : i === days.length - 1 ? "end" : "middle" });
    label.textContent = days[i].day;
    box.append(label);
  });
  return box;
}

function meter(rate) {
  const m = el("span", "meter");
  const fill = el("span", "meter-fill " + (rate === null ? "" : rate >= 0.8 ? "good" : rate >= 0.5 ? "mid" : "bad"));
  fill.style.width = Math.round((rate || 0) * 100) + "%";
  m.append(fill);
  return m;
}

function tableOf(rows, cols) {
  const t = el("table", "lab-table");
  const head = el("tr");
  for (const c of cols) head.append(el("th", c.cls || "", c.label));
  t.append(head);
  for (const r of rows) {
    const tr = el("tr");
    for (const c of cols) {
      const td = el("td", c.cls || "");
      const v = c.cell(r);
      if (v instanceof Node) td.append(v); else td.textContent = v;
      tr.append(td);
    }
    t.append(tr);
  }
  return t;
}

function labCard(title, note) {
  const card = el("section", "lab-card");
  card.append(el("h4", "", title));
  if (note) card.append(el("p", "note", note));
  return card;
}

async function loadLab() {
  const box = document.getElementById("lab-panel");
  if (!box) return;
  const [data, speed, stats] = await Promise.all([
    api("/evolve").catch(() => null), api("/speed").catch(() => null), api("/jobs/stats").catch(() => null)]);
  box.replaceChildren();
  if (!data || !data.ok) { box.append(el("p", "note", (data && data.error) || "The Lab is not running in this engine.")); }
  else renderEvolve(box, data);
  if (stats && stats.ok) box.append(renderJobsView(stats));
  if (speed && speed.ok) box.append(renderSpeed(speed));
}

function renderEvolve(box, data) {
  const head = el("div", "lab-head");
  head.append(el("b", "", data.enabled ? "On: LOKI works on the next step when it is idle." : "Off on this machine (LOKI_EVOLVE in Settings > General; auto = the Windows PC only)."));
  const buttons = el("div", "lab-right");
  const review = el("button", "quiet", "Review now");
  review.type = "button";
  review.title = "LOKI reads what it learned and proposes up to 3 changes (they wait for your OK)";
  review.addEventListener("click", async () => {
    review.disabled = true;
    const r = await api("/self_review/run", {}).catch(() => null);
    const n = r && r.ok ? (r.added || []).length : 0;
    addNotice(r && r.ok ? (n ? "LOKI proposed " + n + " idea" + (n === 1 ? "" : "s") + " below." : "Nothing new to propose.") : ((r && r.error) || "Could not run the review."), !(r && r.ok));
    loadLab();
  });
  const go = el("button", "send", "Start the next step now");
  go.type = "button";
  go.addEventListener("click", async () => {
    go.disabled = true;
    const r = await api("/evolve/start", {}).catch(() => null);
    addNotice((r && (r.line || r.error)) || "Could not start it.", !(r && r.ok));
    loadLab();
  });
  buttons.append(review, go);
  head.append(buttons);
  box.append(head);

  const form = el("form", "lab-idea");
  const input = el("input");
  input.placeholder = "An idea for LOKI to build into itself…";
  input.setAttribute("aria-label", "Your idea");
  const add = el("button", "", "Add idea");
  add.type = "submit";
  form.append(input, add);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const r = await api("/evolve/idea", { text: input.value }).catch(() => null);
    if (!r || !r.ok) addNotice((r && r.error) || "Could not add it.", true);
    loadLab();
  });
  box.append(form);

  const rows = el("div", "rows");
  for (const item of data.items || []) {
    const r = el("div", "row lab-row" + (item.done ? " done" : "") + (item.id === data.next ? " next" : "") + (item.source === "loki" ? " loki-idea" : ""));
    const text = el("div", "lab-text");
    const tag = item.source === "owner" ? " · your idea" : item.source === "loki" ? (item.kind === "speed" ? " · LOKI's idea · speed watch" : " · LOKI's idea") : "";
    text.append(el("b", "", item.id + tag), el("span", "", " " + item.title.replace(/^LOKI's idea \([^)]*\):\s*/, "")));
    const right = el("div", "lab-right");
    right.append(labChip(item, item.id === data.next));
    if (item.approved === false && !item.done) {
      for (const [label, yes] of [["Build it", true], ["No", false]]) {
        const b = el("button", "mini", label);
        b.type = "button";
        b.addEventListener("click", async () => { await api("/evolve/approve", { id: item.id, yes }).catch(() => null); loadLab(); });
        right.append(b);
      }
    }
    r.append(text, right);
    rows.append(r);
  }
  box.append(rows);

  const learned = el("details", "lab-lessons");
  learned.append(el("summary", "", "What LOKI learned from earlier attempts"), el("pre", "", data.lessons || ""));
  box.append(learned);
  if ((data.log || []).length) {
    const log = el("details", "lab-lessons");
    log.append(el("summary", "", "Recent activity"), el("pre", "", data.log.map((e) => new Date(e.t * 1000).toLocaleString() + "  " + e.text).join("\n")));
    box.append(log);
  }
}

function renderJobsView(stats) {
  const card = labCard("Jobs", "Did LOKI's background jobs work? Over the last " + stats.days + " days, from the job logs. A job counts as working when it ended DONE.");
  card.id = "lab-jobs";
  const o = stats.overall || {};
  const top = el("div", "lab-kpis");
  const kpi = (big, small) => { const k = el("div", "kpi"); k.append(el("b", "", big), el("span", "", small)); return k; };
  top.append(kpi(pct(o.rate), o.n ? o.ok + " of " + o.n + " jobs worked" : "no finished jobs yet"));
  const st = stats.selftest || {};
  const lastSt = st.last;
  top.append(kpi(lastSt ? pct(lastSt.rate) : "—", lastSt ? "daily self-test " + lastSt.day.slice(0, 10) + (lastSt.regression ? " · REGRESSION" : "") : (st.running ? "self-test running…" : "self-test not run yet")));
  card.append(top);
  card.append(dayBars(stats.per_day || []));

  const grid = el("div", "lab-grid");
  const byKind = el("div");
  byKind.append(el("h5", "", "By kind"));
  byKind.append(tableOf(stats.by_kind || [], [
    { label: "Kind", cell: (r) => r.kind }, { label: "Worked", cls: "num", cell: (r) => r.ok + "/" + r.n },
    { label: "", cell: (r) => meter(r.rate) }]));
  const byModel = el("div");
  byModel.append(el("h5", "", "By model"));
  byModel.append(tableOf((stats.by_model || []).slice(0, 8), [
    { label: "Model", cell: (r) => r.model }, { label: "Worked", cls: "num", cell: (r) => r.ok + "/" + r.n },
    { label: "", cell: (r) => meter(r.rate) }]));
  grid.append(byKind, byModel);
  card.append(grid);

  const reasons = el("div");
  reasons.append(el("h5", "", "Top failure reasons"));
  if ((stats.reasons || []).length) {
    const list = el("ol", "lab-reasons");
    for (const r of stats.reasons) { const li = el("li"); li.append(el("span", "", r.reason), el("b", "", " ×" + r.n)); list.append(li); }
    reasons.append(list);
  } else reasons.append(el("p", "note", "No failures recorded."));
  card.append(reasons);

  if ((stats.failures || []).length) {
    const fails = el("details", "lab-lessons");
    fails.open = true;
    fails.append(el("summary", "", "Recent failed jobs"));
    const rows = el("div", "rows");
    for (const f of stats.failures.slice(0, 8)) {
      const r = el("div", "row lab-row");
      const t = el("div", "lab-text");
      t.append(el("b", "", f.title || f.id), el("span", "note", " " + f.kind + " · " + f.model + " · " + (f.reason || f.status)));
      const right = el("div", "lab-right");
      const retry = el("button", "mini", "Retry on a stronger model");
      retry.type = "button";
      retry.addEventListener("click", async () => {
        retry.disabled = true;
        const out = await api("/jobs/retry_stronger", { id: f.id }).catch(() => null);
        addNotice(out && out.ok ? "Started it again on " + out.model + "." : ((out && out.error) || "Could not retry it."), !(out && out.ok));
        if (typeof refreshJobs === "function") refreshJobs();
      });
      right.append(retry);
      r.append(t, right);
      rows.append(r);
    }
    fails.append(rows);
    card.append(fails);
  }

  if ((stats.waiting || []).length) {
    const wait = el("div");
    wait.append(el("h5", "", "Waiting and running - forecast"));
    const rows = el("div", "rows");
    for (const w of stats.waiting) rows.append(row(w.title, (w.forecast && w.forecast.line) || w.status, false));
    wait.append(rows);
    card.append(wait);
  }

  const stRow = el("div", "lab-head");
  stRow.append(el("span", "note", "Self-test: 3 cheap jobs (write a file, add numbers, follow a list) on the usual job model, once a day on " + (st.enabled ? "this machine" : "the PC (LOKI_SELFTEST)") + "." +
    ((st.history || []).length ? " Last runs: " + st.history.slice(-7).map((h) => pct(h.rate) + (h.regression ? "!" : "")).join(" ") : "")));
  const run = el("button", "quiet", st.running ? "Self-test running…" : "Run the self-test now");
  run.type = "button";
  run.disabled = Boolean(st.running);
  run.addEventListener("click", async () => {
    run.disabled = true;
    const out = await api("/selftest/start", {}).catch(() => null);
    addNotice((out && (out.line || out.error)) || "Could not start it.", !(out && out.ok));
    if (typeof refreshJobs === "function") refreshJobs();
  });
  stRow.append(run);
  card.append(stRow);
  return card;
}

function renderSpeed(speed) {
  const card = labCard("Speed watch", "How long each step takes on this machine (last " + speed.window_days + " days; the line shows the latest " + 30 + "). Once a week the slowest step becomes an idea above.");
  card.id = "lab-speed";
  if (speed.slowest) {
    const s = el("p", "lab-slowest");
    s.append(el("b", "", "Slowest step: " + speed.slowest.label), document.createTextNode(" - median " + fmtMs(speed.slowest.p50) + ", 90% within " + fmtMs(speed.slowest.p90)));
    card.append(s);
  }
  const shown = (speed.phases || []).filter((p) => p.n || ["startup", "first_paint", "triage", "model_call", "tools", "verification", "request", "job"].includes(p.phase));
  card.append(tableOf(shown, [
    { label: "Step", cell: (p) => p.label },
    { label: "Median", cls: "num", cell: (p) => fmtMs(p.p50) },
    { label: "90%", cls: "num", cell: (p) => fmtMs(p.p90) },
    { label: "Last", cls: "num", cell: (p) => fmtMs(p.last) },
    { label: "n", cls: "num", cell: (p) => String(p.n) },
    { label: "Trend", cell: (p) => sparkline(p.spark || [], p.label) }]));
  if ((speed.tools || []).length) {
    const t = el("p", "note");
    t.textContent = "Slowest tools: " + speed.tools.map((x) => x.tool + " " + fmtMs(x.p50)).join(", ");
    card.append(t);
  }
  return card;
}

// ---------------------------------------------------------------- Settings > Tools: LOKI's own tools (E9)
async function loadUserTools() {
  const box = document.getElementById("user-tools");
  if (!box) return;
  const data = await api("/user_tools").catch(() => null);
  box.replaceChildren();
  const card = labCard("Tools LOKI wrote for itself", "LOKI writes these with make_tool when it needs the same work again. Each one is checked (scanned, its tests run in a sandbox) before it can be switched on, and every call asks you first, like a command.");
  if (!data || !data.ok) { card.append(el("p", "note", (data && data.error) || "Not available in this engine.")); box.append(card); return; }
  if (!(data.tools || []).length) { card.append(el("p", "note", "None yet. They live in " + data.folder + ".")); box.append(card); return; }
  const rows = el("div", "rows");
  for (const t of data.tools) {
    const r = el("div", "row lab-row" + (t.enabled ? "" : " done"));
    const text = el("div", "lab-text");
    text.append(el("b", "", t.name), el("span", "", " " + t.description));
    const params = Object.keys(t.parameters || {});
    const meta = (params.length ? "inputs: " + params.join(", ") : "no inputs") + " · " + t.tests + " test" + (t.tests === 1 ? "" : "s") +
      (t.network ? " · uses the network" : "") + (t.stale ? " · changed since its check" : "") +
      (t.checked ? (t.check_ok ? " · check passed" : " · check FAILED: " + (t.problems || []).join("; ")) : " · not checked");
    text.append(el("div", "note", meta));
    const right = el("div", "lab-right");
    right.append(el("span", "state" + (t.enabled ? " ready" : ""), t.enabled ? "on" : "off"));
    const toggle = el("button", "mini", t.enabled ? "Disable" : "Enable");
    toggle.type = "button";
    toggle.addEventListener("click", async () => {
      const out = await api("/user_tools/toggle", { name: t.name, enabled: !t.enabled }).catch(() => null);
      if (!out || !out.ok) addNotice((out && out.error) || "Could not change it.", true);
      loadUserTools();
    });
    const check = el("button", "mini", "Check");
    check.type = "button";
    check.addEventListener("click", async () => {
      check.disabled = true;
      const out = await api("/user_tools/check", { name: t.name }).catch(() => null);
      addNotice(out && out.ok ? t.name + ": check passed." : t.name + ": " + ((out && out.error) || "check failed"), !(out && out.ok));
      loadUserTools();
    });
    const del = el("button", "mini", "Delete");
    del.type = "button";
    del.addEventListener("click", async () => {
      if (!window.confirm("Delete the tool " + t.name + "?")) return;
      const out = await api("/user_tools/delete", { name: t.name }).catch(() => null);
      if (!out || !out.ok) addNotice((out && out.error) || "Could not delete it.", true);
      loadUserTools();
    });
    right.append(toggle, check, del);
    r.append(text, right);
    rows.append(r);
  }
  card.append(rows);
  box.append(card);
}
