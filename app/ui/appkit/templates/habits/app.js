// Habits - tick off daily habits, keep streaks, see the last 7 days.
"use strict";
const { h, mount } = kit;
const root = document.getElementById("app");
let habits = [];   // [{id, name, emoji, done: {"2026-10-17": true}}]

async function load() {
  habits = await loki.store.get("habits", [
    { id: kit.uid(), name: "Drink water", emoji: "💧", done: {} },
    { id: kit.uid(), name: "Read 10 pages", emoji: "📖", done: {} },
    { id: kit.uid(), name: "Walk", emoji: "🚶", done: {} },
  ]);
  render();
}
const save = () => loki.store.set("habits", habits);

function lastDays(n) {
  const out = [];
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    out.push(d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"));
  }
  return out;
}

function streak(habit) {
  let n = 0;
  const d = new Date();
  if (!habit.done[kit.today()]) d.setDate(d.getDate() - 1);   // today not done yet: count up to yesterday
  for (;;) {
    const key = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    if (!habit.done[key]) return n;
    n++;
    d.setDate(d.getDate() - 1);
  }
}

async function toggle(habit, day) {
  if (habit.done[day]) delete habit.done[day]; else habit.done[day] = true;
  await save();
  render();
}

async function addHabit() {
  const v = await kit.form("New habit", [
    { name: "name", label: "Habit", placeholder: "Stretch for 5 minutes", required: true },
    { name: "emoji", label: "Emoji", value: "⭐" },
  ], "Add");
  if (!v) return;
  habits.push({ id: kit.uid(), name: v.name.trim(), emoji: v.emoji || "⭐", done: {} });
  await save();
  render();
}

async function removeHabit(habit) {
  if (!(await kit.confirm("Remove “" + habit.name + "” and its history?", { ok: "Remove", danger: true }))) return;
  habits = habits.filter((x) => x.id !== habit.id);
  await save();
  render();
}

function render() {
  const days = lastDays(7);
  const today = kit.today();
  const doneToday = habits.filter((x) => x.done[today]).length;
  const head = h("tr", {}, h("th", {}, "Habit"), days.map((d) => h("th", { class: "lk-right", title: d },
    new Date(d + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" }))), h("th", { class: "lk-right" }, "Streak"), h("th", {}));
  const rows = habits.map((habit) => h("tr", {},
    h("td", {}, h("span", { style: { marginRight: "8px" } }, habit.emoji), habit.name),
    days.map((d) => h("td", { class: "lk-right" }, h("input", { type: "checkbox", checked: !!habit.done[d], title: habit.name + " on " + d,
      "aria-label": habit.name + " on " + d, style: { width: "20px", height: "20px", accentColor: "var(--lk-accent)" }, on: { change: () => toggle(habit, d) } }))),
    h("td", { class: "lk-right lk-num" }, h("span", { class: "lk-tag" + (streak(habit) >= 3 ? " ok" : "") }, "🔥 " + streak(habit))),
    h("td", { class: "lk-right" }, kit.button("✕", () => removeHabit(habit), "ghost sm"))));
  mount(root,
    kit.header("✅", "Habits", "Small things, every day", kit.button("+ Habit", addHabit, "primary")),
    h("div", { class: "lk-grid stats" },
      kit.stat("Done today", doneToday + " / " + habits.length, "", doneToday === habits.length && habits.length ? "good" : ""),
      kit.stat("Best streak", String(Math.max(0, ...habits.map(streak))) + " days")),
    kit.card("This week", habits.length ? kit.progress(habits.length ? doneToday / habits.length : 0) : null,
      habits.length ? h("table", { class: "lk-table" }, h("thead", {}, head), h("tbody", {}, rows))
        : kit.empty("🌱", "No habits yet.", "Add your first habit", addHabit)));
}

loki.ready(load);
