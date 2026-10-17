// Kanban board - columns of cards; drag them (or use the arrows) to move work along.
"use strict";
const { h, mount } = kit;
const root = document.getElementById("app");
const S = { columns: [], cards: [], dragging: null };   // columns: [{id, name}], cards: [{id, col, title, notes, color}]
const COLORS = ["", "accent", "ok", "warn", "bad", "info"];

async function load() {
  S.columns = await loki.store.get("columns", [{ id: "todo", name: "To do" }, { id: "doing", name: "Doing" }, { id: "done", name: "Done" }]);
  S.cards = await loki.store.get("cards", [{ id: kit.uid(), col: "todo", title: "Drag me to Doing", notes: "", color: "accent" }]);
  render();
}
const save = () => Promise.all([loki.store.set("columns", S.columns), loki.store.set("cards", S.cards)]);

async function editCard(card, col) {
  const v = await kit.form(card ? "Edit card" : "New card", [
    { name: "title", label: "Title", value: card ? card.title : "", required: true },
    { name: "notes", label: "Notes", type: "textarea", value: card ? card.notes : "" },
    { name: "color", label: "Label", type: "select", options: COLORS.map((c) => ({ value: c, label: c || "none" })), value: card ? card.color : "" },
  ], card ? "Save" : "Add");
  if (!v) return;
  if (card) Object.assign(card, { title: v.title.trim(), notes: v.notes || "", color: v.color });
  else S.cards.push({ id: kit.uid(), col, title: v.title.trim(), notes: v.notes || "", color: v.color });
  await save();
  render();
}

async function move(card, by) {
  const i = S.columns.findIndex((c) => c.id === card.col);
  const next = S.columns[i + by];
  if (!next) return;
  card.col = next.id;
  await save();
  render();
}

async function addColumn() {
  const name = await kit.ask("Column name", { placeholder: "Review" });
  if (!name || !name.trim()) return;
  S.columns.push({ id: kit.uid(), name: name.trim() });
  await save();
  render();
}

async function removeColumn(col) {
  const n = S.cards.filter((c) => c.col === col.id).length;
  if (!(await kit.confirm("Delete the column “" + col.name + "”" + (n ? " and its " + n + " cards" : "") + "?", { ok: "Delete", danger: true }))) return;
  S.columns = S.columns.filter((c) => c.id !== col.id);
  S.cards = S.cards.filter((c) => c.col !== col.id);
  await save();
  render();
}

function cardView(card, ci) {
  return h("div", { class: "lk-item", draggable: "true", style: { flexDirection: "column", alignItems: "stretch", gap: "6px", cursor: "grab", background: "var(--lk-card2)" },
    on: { dragstart: (e) => { S.dragging = card.id; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", card.id); }, dragend: () => { S.dragging = null; } } },
    h("div", { class: "lk-row nowrap" }, card.color ? h("span", { class: "lk-tag " + card.color }, "●") : null, h("b", { class: "lk-grow" }, card.title)),
    card.notes ? h("div", { class: "lk-small lk-muted", style: { whiteSpace: "pre-wrap" } }, card.notes) : null,
    h("div", { class: "lk-row nowrap", style: { gap: "2px" } },
      Object.assign(kit.button("←", () => move(card, -1), "ghost sm"), { disabled: ci === 0, title: "Move left" }),
      Object.assign(kit.button("→", () => move(card, 1), "ghost sm"), { disabled: ci === S.columns.length - 1, title: "Move right" }),
      h("span", { class: "lk-spacer" }), kit.button("Edit", () => editCard(card), "ghost sm"),
      kit.button("✕", async () => { S.cards = S.cards.filter((x) => x.id !== card.id); await save(); render(); }, "ghost sm")));
}

function render() {
  const board = h("div", { style: { display: "grid", gridTemplateColumns: "repeat(" + S.columns.length + ", minmax(220px, 1fr))", gap: "12px", overflowX: "auto", alignItems: "start" } },
    S.columns.map((col, ci) => {
      const cards = S.cards.filter((c) => c.col === col.id);
      const zone = h("section", { class: "lk-card", style: { minHeight: "200px" },
        on: { dragover: (e) => { e.preventDefault(); zone.style.borderColor = "var(--lk-accent)"; }, dragleave: () => { zone.style.borderColor = ""; },
          drop: async (e) => { e.preventDefault(); zone.style.borderColor = ""; const card = S.cards.find((c) => c.id === (S.dragging || e.dataTransfer.getData("text/plain"))); if (card) { card.col = col.id; await save(); render(); } } } },
        h("div", { class: "lk-card-head" }, h("h3", {}, col.name), h("span", { class: "lk-tag" }, String(cards.length)), kit.button("✕", () => removeColumn(col), "ghost sm")),
        h("div", { class: "lk-list" }, cards.map((c) => cardView(c, ci))),
        kit.button("+ Card", () => editCard(null, col.id), "ghost sm"));
      return zone;
    }));
  mount(root, kit.header("🗂️", "Kanban board", S.cards.length + " cards", kit.button("+ Column", addColumn),
    kit.button("Ask LOKI what to do next", () => kit.askLoki("Look at my board and tell me what to focus on next and why (short).", { columns: S.columns, cards: S.cards }), "primary")), board);
  root.classList.add("wide");
}

loki.ready(load);
