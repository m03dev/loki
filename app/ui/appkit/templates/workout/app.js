// Workout log - sets, reps and weights; personal bests; weekly volume.
"use strict";
const { h, mount } = kit;
const root = document.getElementById("app");
const S = { sets: [], unit: "kg", filter: "" };   // sets: [{id, date, exercise, reps, weight}]

async function load() {
  S.sets = await loki.store.get("sets", []);
  S.unit = await loki.store.get("unit", "kg");
  render();
}
const save = () => loki.store.set("sets", S.sets);
const exercises = () => [...new Set(S.sets.map((s) => s.exercise))].sort();

async function logSet(prefill) {
  const last = S.sets[S.sets.length - 1] || {};
  const v = await kit.form("Log a set", [
    { name: "exercise", label: "Exercise", value: (prefill && prefill.exercise) || last.exercise || "", placeholder: "Squat", required: true },
    { name: "reps", label: "Reps", type: "number", value: (prefill && prefill.reps) || last.reps || 8, required: true },
    { name: "weight", label: "Weight (" + S.unit + ")", type: "number", value: (prefill && prefill.weight) || last.weight || 0 },
    { name: "date", label: "Date", type: "date", value: kit.today() },
  ], "Log");
  if (!v) return;
  S.sets.push({ id: kit.uid(), date: v.date || kit.today(), exercise: v.exercise.trim(), reps: Number(v.reps) || 0, weight: Number(v.weight) || 0 });
  await save();
  kit.toast("Logged", "ok");
  render();
}

function weeks(n) {
  const out = [];
  const start = new Date(); start.setHours(12); start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  for (let i = n - 1; i >= 0; i--) {
    const a = new Date(start); a.setDate(a.getDate() - i * 7);
    const b = new Date(a); b.setDate(b.getDate() + 7);
    out.push({ from: a.toISOString().slice(0, 10), to: b.toISOString().slice(0, 10), label: a.toLocaleDateString(undefined, { month: "short", day: "numeric" }) });
  }
  return out;
}

function render() {
  const shown = S.filter ? S.sets.filter((s) => s.exercise === S.filter) : S.sets;
  const best = exercises().map((ex) => {
    const sets = S.sets.filter((s) => s.exercise === ex);
    const top = sets.reduce((a, s) => (s.weight > a.weight || (s.weight === a.weight && s.reps > a.reps)) ? s : a, sets[0]);
    const e1rm = Math.max(...sets.map((s) => s.weight * (1 + s.reps / 30)));
    return { ex, top, e1rm, count: sets.length };
  });
  const volume = weeks(8).map((w) => ({ label: w.label, value: Math.round(kit.sum(shown.filter((s) => s.date >= w.from && s.date < w.to), (s) => s.reps * s.weight)) }));
  const byDay = kit.groupBy(kit.sortBy(shown, (s) => s.date, true).slice(0, 80), (s) => s.date);
  mount(root,
    kit.header("🏋️", "Workout log", S.sets.length + " sets logged",
      kit.select([{ value: "", label: "All exercises" }].concat(exercises()), S.filter, { on: { change: (e) => { S.filter = e.target.value; render(); } }, style: { width: "auto" } }),
      kit.button("+ Log set", () => logSet(S.filter ? { exercise: S.filter } : null), "primary")),
    h("div", { class: "lk-grid two" },
      kit.card("Weekly volume (" + S.unit + " × reps)", kit.bars(volume, (v) => v >= 1000 ? (v / 1000).toFixed(1) + "k" : String(v))),
      kit.card("Personal bests", best.length ? h("div", { class: "lk-list" }, best.map((b) => h("div", { class: "lk-item clickable", on: { click: () => { S.filter = b.ex; render(); } } },
        h("b", { class: "lk-grow" }, b.ex), h("span", { class: "lk-num" }, b.top.weight + " " + S.unit + " × " + b.top.reps),
        h("span", { class: "lk-tag accent", title: "estimated one-rep max" }, "1RM ~" + Math.round(b.e1rm)))))
        : kit.empty("💪", "Log your first set to see bests here."))),
    kit.card("History", Object.keys(byDay).length ? h("div", { class: "lk-col" }, Object.entries(byDay).map(([day, sets]) => h("div", { class: "lk-col", style: { gap: "4px" } },
      h("b", {}, kit.date(day, { weekday: true })),
      h("div", { class: "lk-list" }, sets.map((s) => h("div", { class: "lk-item" }, h("span", { class: "lk-grow" }, s.exercise),
        h("span", { class: "lk-num" }, s.reps + " × " + s.weight + " " + S.unit),
        kit.button("Again", () => logSet(s), "ghost sm"),
        kit.button("✕", async () => { S.sets = S.sets.filter((x) => x.id !== s.id); await save(); render(); }, "ghost sm")))))))
      : kit.empty("📒", "No sets yet.", "Log a set", () => logSet())),
    h("div", { class: "lk-row" }, h("span", { class: "lk-muted lk-small" }, "Units:"), kit.tabs(["kg", "lb"], S.unit, async (u) => { S.unit = u; await loki.store.set("unit", u); render(); }),
      h("span", { class: "lk-spacer" }), kit.button("Ask LOKI for my next workout", () => kit.askLoki("Based on my recent sets, suggest my next workout (exercises, sets, reps, weights) and why.", { recent: S.sets.slice(-60), unit: S.unit }), "sm")));
}

loki.ready(load);
