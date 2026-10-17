// Settings > Lab: "Do LOKI's agents finish real tasks?" - the latest task-success benchmark
// (tools/task_bench.py; the autopilot runs it nightly on the PC). GET /bench gives, per model,
// how many of the owner's realistic tasks were really finished and which failed and why.
// A separate section under the Lab panel (lab.js is the jobs/evolve dashboard). Plain DOM (CSP).
"use strict";

async function loadBench() {
  const box = document.getElementById("bench-panel");
  if (!box) return;
  const data = await api("/bench").catch(() => null);
  box.replaceChildren();
  box.append(el("h4", "", "Task success - do agents finish real tasks?"));
  if (!data || !data.ok) { box.append(el("p", "note", (data && data.error) || "The benchmark is not available in this engine.")); return; }
  const when = data.running ? "Running now..." : (data.date ? "Latest run: " + data.date : "Not run yet.");
  box.append(el("p", "note", when + " " + (data.enabled
    ? "Runs nightly when LOKI is idle (LOKI_TASK_BENCH)."
    : "Nightly runs are off on this machine (LOKI_TASK_BENCH; auto = the Windows PC). Run: python tools/task_bench.py --model local")));
  const runs = data.runs || [];
  if (!runs.length) return;
  const rows = el("div", "rows bench-rows");
  const head = el("div", "row bench-row bench-head");
  for (const t of ["Model", "Finished", "Score", "Time", "Escalated"]) head.append(el("b", "", t));
  rows.append(head);
  for (const run of runs) {
    const r = el("div", "row bench-row");
    const pct = Math.round(100 * (run.rate || 0));
    r.append(el("span", "", run.model + (run.scripted ? " (scripted)" : "")),
      el("span", "", (run.passed || 0) + " / " + (run.total || 0)),
      el("span", "state " + (pct >= 80 ? "ready" : pct >= 50 ? "working" : "warn"), pct + "%"),
      el("span", "", Math.round(run.seconds || 0) + " s"),
      el("span", "", String(run.escalated || 0)));
    rows.append(r);
    if ((run.failed || []).length) {
      const why = el("details", "lab-lessons");
      why.append(el("summary", "", "What " + run.model + " did not finish (" + run.failed.length + ")"),
        el("pre", "", run.failed.map((f) => f.id + ": " + f.reason).join("\n")));
      rows.append(why);
    }
  }
  box.append(rows);
}
