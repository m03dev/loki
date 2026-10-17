// Meal planner - the week's meals, and a shopping list made from their ingredients.
"use strict";
const { h, mount } = kit;
const root = document.getElementById("app");
const SLOTS = ["Breakfast", "Lunch", "Dinner"];
const S = { week: "", plan: {}, have: {} };   // plan: {"2026-10-13": {Dinner: {name, ingredients: "pasta, tomatoes"}}}

function monday(offset) {
  const d = new Date();
  d.setHours(12);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7) + (offset || 0) * 7);
  return d.toISOString().slice(0, 10);
}
function weekDays() {
  const out = [];
  for (let i = 0; i < 7; i++) { const d = new Date(S.week + "T12:00:00"); d.setDate(d.getDate() + i); out.push(d.toISOString().slice(0, 10)); }
  return out;
}

async function load() {
  S.week = monday(0);
  S.plan = await loki.store.get("plan", {});
  S.have = await loki.store.get("have", {});
  render();
}
const save = () => Promise.all([loki.store.set("plan", S.plan), loki.store.set("have", S.have)]);

async function editMeal(day, slot) {
  const cur = (S.plan[day] || {})[slot] || {};
  const v = await kit.form(slot + " · " + kit.date(day, { weekday: true }), [
    { name: "name", label: "Meal", value: cur.name || "", placeholder: "Pasta with tomato sauce" },
    { name: "ingredients", label: "Ingredients (comma separated)", type: "textarea", value: cur.ingredients || "", placeholder: "pasta, tomatoes, garlic, basil" },
  ], "Save");
  if (!v) return;
  S.plan[day] = S.plan[day] || {};
  if (v.name.trim()) S.plan[day][slot] = { name: v.name.trim(), ingredients: v.ingredients || "" };
  else delete S.plan[day][slot];
  await save();
  render();
}

function shopping() {
  const counts = {};
  for (const day of weekDays()) for (const slot of SLOTS) {
    const meal = (S.plan[day] || {})[slot];
    if (!meal) continue;
    for (const raw of String(meal.ingredients || "").split(/[,\n]/)) {
      const item = raw.trim().toLowerCase();
      if (item) counts[item] = (counts[item] || 0) + 1;
    }
  }
  return Object.keys(counts).sort().map((item) => ({ item, n: counts[item] }));
}

async function ideas() {
  const planned = weekDays().flatMap((d) => SLOTS.map((s) => (S.plan[d] || {})[s]).filter(Boolean).map((m) => m.name));
  kit.askLoki("Suggest 5 easy dinners for this week that use different ingredients from what I already planned. For each: name and a short ingredient list.", { planned });
}

async function exportList() {
  const list = shopping().filter((x) => !S.have[x.item]);
  const saved = await loki.files.save("shopping-" + S.week + ".txt", "Shopping list - week of " + kit.date(S.week) + "\n\n" + list.map((x) => "[ ] " + x.item + (x.n > 1 ? " (x" + x.n + ")" : "")).join("\n"));
  if (saved) kit.toast("Saved " + saved.name, "ok");
}

function render() {
  const days = weekDays();
  const grid = h("table", { class: "lk-table" },
    h("thead", {}, h("tr", {}, h("th", {}), days.map((d) => h("th", {}, kit.date(d, { weekday: true }))))),
    h("tbody", {}, SLOTS.map((slot) => h("tr", {}, h("th", {}, slot), days.map((d) => {
      const meal = (S.plan[d] || {})[slot];
      return h("td", {}, h("button", { type: "button", class: "lk-btn sm " + (meal ? "" : "ghost"), style: { width: "100%", whiteSpace: "normal", minHeight: "40px" },
        on: { click: () => editMeal(d, slot) } }, meal ? meal.name : "+"));
    })))));
  const list = shopping();
  mount(root,
    kit.header("🥗", "Meal planner", "Week of " + kit.date(S.week),
      kit.button("‹", () => { S.week = new Date(new Date(S.week + "T12:00:00").getTime() - 7 * 864e5).toISOString().slice(0, 10); render(); }, "icon ghost"),
      kit.button("This week", () => { S.week = monday(0); render(); }, "sm"),
      kit.button("›", () => { S.week = new Date(new Date(S.week + "T12:00:00").getTime() + 7 * 864e5).toISOString().slice(0, 10); render(); }, "icon ghost"),
      kit.button("Ideas from LOKI", ideas, "primary")),
    kit.card("The week", h("div", { style: { overflowX: "auto" } }, grid)),
    kit.card("Shopping list",
      list.length ? h("div", { class: "lk-list" }, list.map((x) => h("label", { class: "lk-item lk-check" + (S.have[x.item] ? " done" : "") },
        h("input", { type: "checkbox", checked: !!S.have[x.item], on: { change: async (e) => { if (e.target.checked) S.have[x.item] = true; else delete S.have[x.item]; await save(); render(); } } }),
        h("span", { class: "lk-grow" }, x.item), x.n > 1 ? h("span", { class: "lk-tag" }, "×" + x.n) : null)))
        : kit.empty("🛒", "Add meals with ingredients and the list makes itself."),
      list.length ? h("div", { class: "lk-row" }, kit.button("Save list as a file", exportList, "sm"), kit.button("Clear ticks", async () => { S.have = {}; await save(); render(); }, "ghost sm")) : null));
}

loki.ready(load);
