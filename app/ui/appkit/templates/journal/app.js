// Journal - one entry a day with a mood, search, and a weekly reflection from LOKI.
"use strict";
const { h, mount } = kit;
const root = document.getElementById("app");
const MOODS = ["😄", "🙂", "😐", "😕", "😢"];
const S = { entries: {}, day: kit.today(), query: "" };   // entries: {"2026-10-17": {text, mood, t}}

async function load() {
  S.entries = await loki.store.get("entries", {});
  render();
}
const persist = kit.debounce(() => loki.store.set("entries", S.entries), 600);

function setEntry(day, patch) {
  const cur = S.entries[day] || { text: "", mood: "" };
  S.entries[day] = Object.assign(cur, patch, { t: Date.now() });
  if (!S.entries[day].text && !S.entries[day].mood) delete S.entries[day];
  persist();
}

function shift(by) {
  const d = new Date(S.day + "T12:00:00");
  d.setDate(d.getDate() + by);
  S.day = d.toISOString().slice(0, 10);
  render();
}

function reflect() {
  const week = Object.entries(S.entries).sort().slice(-7).map(([day, e]) => ({ day, mood: e.mood, text: e.text }));
  if (!week.length) { kit.toast("Write a few entries first"); return; }
  kit.askLoki("Read my last journal entries and give me a short, kind reflection: patterns you notice, and one gentle suggestion.", { entries: week });
}

function render() {
  const entry = S.entries[S.day] || { text: "", mood: "" };
  const area = h("textarea", { class: "lk-textarea", style: { minHeight: "260px" }, placeholder: "How was today? What happened, what are you thinking about?",
    on: { input: (e) => { setEntry(S.day, { text: e.target.value }); counter.textContent = words(e.target.value) + " words"; } } }, entry.text || "");
  const counter = h("span", { class: "lk-muted lk-small" }, words(entry.text || "") + " words");
  const moods = h("div", { class: "lk-row" }, MOODS.map((m) => kit.button(m, () => { setEntry(S.day, { mood: entry.mood === m ? "" : m }); render(); },
    "round" + (entry.mood === m ? " primary" : " ghost"))));
  const q = S.query.trim().toLowerCase();
  const list = Object.entries(S.entries).filter(([, e]) => !q || (e.text || "").toLowerCase().includes(q)).sort().reverse().slice(0, 60);
  mount(root,
    kit.header("📔", "Journal", kit.date(S.day, { weekday: true }),
      kit.button("‹", () => shift(-1), "icon ghost"), kit.button("Today", () => { S.day = kit.today(); render(); }, "sm"),
      kit.button("›", () => shift(1), "icon ghost"), kit.button("Reflect with LOKI", reflect, "primary")),
    h("div", { class: "lk-grid two" },
      kit.card("Entry", moods, area, h("div", { class: "lk-row" }, counter, h("span", { class: "lk-spacer" }), h("span", { class: "lk-muted lk-small" }, "Saved automatically"))),
      kit.card("Past entries",
        kit.input({ type: "search", placeholder: "Search your journal", value: S.query, on: { input: kit.debounce((e) => { S.query = e.target.value; render(); document.querySelector("input[type=search]").focus(); }, 250) } }),
        list.length ? h("div", { class: "lk-list" }, list.map(([day, e]) => h("div", { class: "lk-item clickable", on: { click: () => { S.day = day; render(); } } },
          h("span", {}, e.mood || "·"), h("div", { class: "lk-grow" }, h("b", {}, kit.date(day, { weekday: true })), h("div", { class: "lk-muted lk-small" }, (e.text || "").slice(0, 90))))))
          : kit.empty("✍️", q ? "Nothing matches." : "Your entries will show up here."))));
  area.focus();
}

const words = (t) => (String(t).trim().match(/\S+/g) || []).length;
loki.ready(load);
