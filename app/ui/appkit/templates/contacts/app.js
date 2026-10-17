// Contacts - a light CRM: people, companies, notes, and who is due a follow-up.
"use strict";
const { h, mount } = kit;
const root = document.getElementById("app");
const FOLLOW_UP_DAYS = 30;
const S = { people: [], query: "", open: null };   // people: [{id, name, company, email, phone, tags, notes, last, log: [{date, text}]}]

async function load() {
  S.people = await loki.store.get("people", []);
  render();
}
const save = () => loki.store.set("people", S.people);
const daysSince = (iso) => iso ? Math.floor((Date.now() - new Date(iso + "T12:00:00").getTime()) / 864e5) : Infinity;
const due = (p) => daysSince(p.last) >= FOLLOW_UP_DAYS;

async function editPerson(p) {
  const v = await kit.form(p ? "Edit contact" : "New contact", [
    { name: "name", label: "Name", value: p ? p.name : "", required: true },
    { name: "company", label: "Company", value: p ? p.company : "" },
    { name: "email", label: "Email", type: "email", value: p ? p.email : "" },
    { name: "phone", label: "Phone", value: p ? p.phone : "" },
    { name: "tags", label: "Tags (comma separated)", value: p ? (p.tags || []).join(", ") : "", placeholder: "client, supplier" },
    { name: "notes", label: "Notes", type: "textarea", value: p ? p.notes : "" },
  ], p ? "Save" : "Add");
  if (!v) return;
  const person = p || { id: kit.uid(), log: [], last: "" };
  Object.assign(person, { name: v.name.trim(), company: (v.company || "").trim(), email: (v.email || "").trim(), phone: (v.phone || "").trim(),
    tags: String(v.tags || "").split(",").map((t) => t.trim()).filter(Boolean), notes: v.notes || "" });
  if (!p) S.people.push(person);
  await save();
  S.open = person.id;
  render();
}

async function logTouch(p) {
  const text = await kit.ask("What happened? (call, email, meeting...)", { placeholder: "Called about the new order" });
  if (text === null) return;
  p.log = p.log || [];
  p.log.unshift({ date: kit.today(), text: text.trim() || "Contacted" });
  p.last = kit.today();
  await save();
  kit.toast("Logged", "ok");
  render();
}

async function exportCsv() {
  const rows = [["name", "company", "email", "phone", "tags", "last contacted", "notes"]].concat(S.people.map((p) => [p.name, p.company, p.email, p.phone, (p.tags || []).join("; "), p.last, p.notes]));
  const saved = await loki.files.save("contacts-" + kit.today() + ".csv", kit.csv(rows));
  if (saved) kit.toast("Saved " + saved.name, "ok");
}

function detail(p) {
  return kit.card(null,
    h("div", { class: "lk-card-head" }, h("h3", {}, p.name), kit.button("Edit", () => editPerson(p), "ghost sm"),
      kit.button("Delete", async () => { if (await kit.confirm("Delete " + p.name + "?", { ok: "Delete", danger: true })) { S.people = S.people.filter((x) => x.id !== p.id); S.open = null; await save(); render(); } }, "ghost danger sm")),
    p.company ? h("div", { class: "lk-muted" }, p.company) : null,
    h("div", { class: "lk-row" }, (p.tags || []).map((t) => h("span", { class: "lk-tag accent" }, t))),
    h("div", { class: "lk-col", style: { gap: "2px" } }, p.email ? h("span", {}, "✉ " + p.email) : null, p.phone ? h("span", {}, "☎ " + p.phone) : null),
    p.notes ? h("p", { class: "lk-small", style: { whiteSpace: "pre-wrap" } }, p.notes) : null,
    h("div", { class: "lk-row" }, kit.button("Log contact", () => logTouch(p), "primary sm"),
      kit.button("Draft a follow-up with LOKI", () => kit.askLoki("Draft a short, friendly follow-up message to " + p.name + (p.company ? " at " + p.company : "") + ", based on our history.", { contact: p }), "sm")),
    h("b", {}, "History"),
    (p.log || []).length ? h("div", { class: "lk-list" }, p.log.slice(0, 30).map((l) => h("div", { class: "lk-item" }, h("span", { class: "lk-muted lk-small" }, kit.date(l.date)), h("span", { class: "lk-grow" }, l.text))))
      : h("p", { class: "lk-muted lk-small" }, "Nothing logged yet."));
}

function render() {
  const q = S.query.trim().toLowerCase();
  const list = kit.sortBy(S.people.filter((p) => !q || [p.name, p.company, p.email, (p.tags || []).join(" ")].join(" ").toLowerCase().includes(q)), (p) => p.name.toLowerCase());
  const open = S.people.find((p) => p.id === S.open);
  const dueList = S.people.filter(due);
  mount(root,
    kit.header("👥", "Contacts", S.people.length + " people · " + dueList.length + " due a follow-up", kit.button("Export CSV", exportCsv, "sm"), kit.button("+ Contact", () => editPerson(null), "primary")),
    h("div", { class: "lk-grid two" },
      kit.card(null,
        kit.input({ type: "search", placeholder: "Search people, companies, tags", value: S.query, on: { input: kit.debounce((e) => { S.query = e.target.value; render(); const s = document.querySelector("input[type=search]"); s.focus(); s.setSelectionRange(s.value.length, s.value.length); }, 200) } }),
        list.length ? h("div", { class: "lk-list" }, list.map((p) => h("div", { class: "lk-item clickable", style: p.id === S.open ? { borderColor: "var(--lk-accent)" } : null, on: { click: () => { S.open = p.id; render(); } } },
          h("div", { class: "lk-grow" }, h("b", {}, p.name), h("div", { class: "lk-muted lk-small" }, [p.company, p.email].filter(Boolean).join(" · "))),
          due(p) ? h("span", { class: "lk-tag warn" }, p.last ? daysSince(p.last) + "d" : "new") : h("span", { class: "lk-tag ok" }, daysSince(p.last) + "d"))))
          : kit.empty("📇", q ? "Nobody matches." : "Add the people you work with.", q ? null : "Add a contact", () => editPerson(null))),
      open ? detail(open) : kit.card("Due a follow-up", dueList.length ? h("div", { class: "lk-list" }, dueList.slice(0, 12).map((p) => h("div", { class: "lk-item clickable", on: { click: () => { S.open = p.id; render(); } } },
        h("span", { class: "lk-grow" }, p.name), h("span", { class: "lk-muted lk-small" }, p.last ? "last " + kit.date(p.last) : "never contacted"))))
        : kit.empty("🎯", "Everyone is up to date."))));
}

loki.ready(load);
