// Budget - income and spending by month, limits per category, CSV in and out, ask LOKI about it.
"use strict";
const { h, mount } = kit;
const root = document.getElementById("app");
const DEFAULT_CATEGORIES = [
  { name: "Housing", limit: 1200 }, { name: "Food", limit: 450 }, { name: "Transport", limit: 150 },
  { name: "Bills", limit: 200 }, { name: "Fun", limit: 150 }, { name: "Other", limit: 100 },
];
const S = { entries: [], categories: [], currency: "USD", month: kit.today().slice(0, 7), view: "month" };

async function load() {
  S.entries = await loki.store.get("entries", []);
  S.categories = await loki.store.get("categories", DEFAULT_CATEGORIES);
  S.currency = await loki.store.get("currency", "USD");
  render();
}
const save = () => Promise.all([loki.store.set("entries", S.entries), loki.store.set("categories", S.categories)]);
const money = (n) => kit.money(n, S.currency);
const inMonth = () => S.entries.filter((e) => String(e.date).startsWith(S.month));

function shiftMonth(by) {
  const [y, m] = S.month.split("-").map(Number);
  const d = new Date(y, m - 1 + by, 1);
  S.month = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
  render();
}
const monthName = () => new Date(S.month + "-15T12:00:00").toLocaleDateString(undefined, { month: "long", year: "numeric" });

async function addEntry(kind, existing) {
  const v = await kit.form(existing ? "Edit entry" : (kind === "income" ? "Add income" : "Add spending"), [
    { name: "description", label: "What", value: existing ? existing.description : "", placeholder: kind === "income" ? "Salary" : "Groceries", required: true },
    { name: "amount", label: "Amount", type: "number", value: existing ? existing.amount : "", required: true },
    { name: "date", label: "Date", type: "date", value: existing ? existing.date : (kit.today().startsWith(S.month) ? kit.today() : S.month + "-01") },
    kind === "income" ? null : { name: "category", label: "Category", type: "select", options: S.categories.map((c) => c.name), value: existing ? existing.category : S.categories[0] && S.categories[0].name },
  ].filter(Boolean), existing ? "Save" : "Add");
  if (!v) return;
  const entry = Object.assign(existing || { id: kit.uid(), kind }, { description: v.description, amount: Math.abs(Number(v.amount) || 0), date: v.date || kit.today(), category: kind === "income" ? "Income" : v.category });
  if (!existing) S.entries.push(entry);
  await save();
  kit.toast(existing ? "Saved" : "Added", "ok");
  render();
}

async function removeEntry(e) {
  if (!(await kit.confirm("Delete “" + e.description + "”?", { ok: "Delete", danger: true }))) return;
  S.entries = S.entries.filter((x) => x.id !== e.id);
  await save();
  render();
}

async function editCategories() {
  const fields = S.categories.map((c, i) => ({ name: "c" + i, label: c.name + " - monthly limit", type: "number", value: c.limit }));
  fields.push({ name: "newName", label: "New category (optional)", placeholder: "e.g. Pets" }, { name: "newLimit", label: "Its limit", type: "number" });
  const v = await kit.form("Categories and limits", fields, "Save");
  if (!v) return;
  S.categories.forEach((c, i) => { c.limit = Number(v["c" + i]) || 0; });
  if (v.newName && v.newName.trim()) S.categories.push({ name: v.newName.trim(), limit: Number(v.newLimit) || 0 });
  await save();
  render();
}

async function exportCsv() {
  const rows = [["date", "kind", "description", "category", "amount"]].concat(
    kit.sortBy(S.entries, (e) => e.date).map((e) => [e.date, e.kind, e.description, e.category, e.amount]));
  const saved = await loki.files.save("budget-" + kit.today() + ".csv", kit.csv(rows));
  if (saved) kit.toast("Saved " + saved.name, "ok");
}

async function importCsv() {
  const file = await loki.files.open({ accept: ".csv,text/csv" });
  if (!file || !file.text) return;
  const lines = file.text.split(/\r?\n/).filter((l) => l.trim());
  let added = 0;
  for (const line of lines.slice(1)) {
    const cells = line.match(/("([^"]|"")*"|[^,]*)(,|$)/g).map((c) => c.replace(/,$/, "").replace(/^"|"$/g, "").replace(/""/g, '"'));
    const [date, kind, description, category, amount] = cells;
    if (!date || isNaN(Number(amount))) continue;
    S.entries.push({ id: kit.uid(), date, kind: kind === "income" ? "income" : "expense", description: description || "", category: category || "Other", amount: Math.abs(Number(amount)) });
    added++;
  }
  await save();
  kit.toast("Imported " + added + " entries", "ok");
  render();
}

function render() {
  const month = inMonth();
  const income = kit.sum(month.filter((e) => e.kind === "income"), (e) => e.amount);
  const spent = kit.sum(month.filter((e) => e.kind !== "income"), (e) => e.amount);
  const left = income - spent;
  const byCat = kit.groupBy(month.filter((e) => e.kind !== "income"), (e) => e.category);
  const catCards = S.categories.map((c) => {
    const used = kit.sum(byCat[c.name], (e) => e.amount);
    const frac = c.limit ? used / c.limit : 0;
    return h("div", { class: "lk-item" },
      h("div", { class: "lk-grow lk-col", style: { gap: "5px" } },
        h("div", { class: "lk-row" }, h("b", {}, c.name), h("span", { class: "lk-spacer" }),
          h("span", { class: "lk-num lk-small" + (frac > 1 ? "" : " lk-muted"), style: frac > 1 ? { color: "var(--lk-bad)" } : null }, money(used) + " of " + money(c.limit))),
        kit.progress(frac)));
  });
  const rows = kit.sortBy(month, (e) => e.date, true).map((e) => h("tr", {},
    h("td", { class: "lk-muted" }, kit.date(e.date)), h("td", {}, e.description),
    h("td", {}, h("span", { class: "lk-tag" + (e.kind === "income" ? " ok" : "") }, e.category)),
    h("td", { class: "lk-num", style: { color: e.kind === "income" ? "var(--lk-ok)" : "" } }, (e.kind === "income" ? "+" : "−") + money(e.amount)),
    h("td", { class: "lk-right" }, kit.button("Edit", () => addEntry(e.kind, e), "ghost sm"), kit.button("✕", () => removeEntry(e), "ghost sm"))));
  mount(root,
    kit.header("💰", "Budget", monthName(),
      kit.button("‹", () => shiftMonth(-1), "icon ghost"), kit.button("›", () => shiftMonth(1), "icon ghost"),
      kit.button("+ Income", () => addEntry("income")), kit.button("+ Spending", () => addEntry("expense"), "primary")),
    h("div", { class: "lk-grid stats" },
      kit.stat("Income", money(income)), kit.stat("Spent", money(spent)),
      kit.stat("Left", money(left), income ? Math.round(left / income * 100) + "% of income" : "", left < 0 ? "bad" : "good"),
      kit.stat("Entries", String(month.length))),
    h("div", { class: "lk-grid two" },
      kit.card("Categories", h("div", { class: "lk-list" }, catCards), h("div", { class: "lk-row" }, kit.button("Edit limits", editCategories, "sm"))),
      kit.card("Where it went", spent ? kit.bars(S.categories.map((c) => ({ label: c.name, value: Math.round(kit.sum(byCat[c.name], (e) => e.amount)) })), money) : kit.empty("📊", "Nothing spent this month yet."),
        h("div", { class: "lk-row" }, kit.button("Ask LOKI about my spending", () => kit.askLoki("Look at my budget for " + monthName() + ". Where can I save, and is anything unusual?", { month: S.month, income, spent, entries: month }), "sm")))),
    kit.card("This month",
      month.length ? h("table", { class: "lk-table" }, h("thead", {}, h("tr", {}, h("th", {}, "Date"), h("th", {}, "What"), h("th", {}, "Category"), h("th", { class: "lk-num" }, "Amount"), h("th", {}))), h("tbody", {}, rows))
        : kit.empty("🧾", "No entries for " + monthName() + ".", "Add spending", () => addEntry("expense")),
      h("div", { class: "lk-row" }, kit.button("Export CSV", exportCsv, "sm"), kit.button("Import CSV", importCsv, "sm"))));
}

loki.ready(load);
