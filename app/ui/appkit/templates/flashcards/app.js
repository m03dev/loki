// Study cards - decks of flashcards with simple spaced repetition (Leitner boxes); LOKI can write cards.
"use strict";
const { h, mount } = kit;
const root = document.getElementById("app");
const GAPS = [0, 1, 3, 7, 14, 30];   // days until a card in box N is due again
const S = { decks: [], deck: null, study: null };   // deck: {id, name, cards: [{id, front, back, box, due}]}

async function load() {
  S.decks = await loki.store.get("decks", [{ id: kit.uid(), name: "Example: capitals", cards: [
    { id: kit.uid(), front: "Capital of France?", back: "Paris", box: 0, due: "" },
    { id: kit.uid(), front: "Capital of Japan?", back: "Tokyo", box: 0, due: "" },
    { id: kit.uid(), front: "Capital of Kenya?", back: "Nairobi", box: 0, due: "" }] }]);
  render();
}
const save = () => loki.store.set("decks", S.decks);
const due = (deck) => deck.cards.filter((c) => !c.due || c.due <= kit.today());
function addDays(n) { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }

async function newDeck() {
  const name = await kit.ask("Deck name", { placeholder: "Biology - cells" });
  if (!name) return;
  S.decks.push({ id: kit.uid(), name: name.trim(), cards: [] });
  await save();
  S.deck = S.decks[S.decks.length - 1];
  render();
}

async function addCard(deck) {
  const v = await kit.form("New card", [{ name: "front", label: "Front (question)", type: "textarea", required: true }, { name: "back", label: "Back (answer)", type: "textarea", required: true }], "Add");
  if (!v) return;
  deck.cards.push({ id: kit.uid(), front: v.front.trim(), back: v.back.trim(), box: 0, due: "" });
  await save();
  render();
}

async function lokiCards(deck) {
  const topic = await kit.ask("What should the cards be about?", { placeholder: deck.name });
  if (!topic) return;
  kit.toast("LOKI is writing cards…");
  try {
    const answer = await loki.ask("Write 10 flashcards about: " + topic + ". One per line, exactly 'question | answer', nothing else.");
    let n = 0;
    for (const line of String(answer).split("\n")) {
      const [front, back] = line.replace(/^\s*[-*\d.)]+\s*/, "").split("|").map((x) => (x || "").trim());
      if (front && back) { deck.cards.push({ id: kit.uid(), front, back, box: 0, due: "" }); n++; }
    }
    await save();
    kit.toast(n ? "Added " + n + " cards" : "LOKI's answer had no cards in it", n ? "ok" : "bad");
    render();
  } catch (e) { kit.toast("LOKI could not answer: " + e.message, "bad"); }
}

function startStudy(deck) {
  const cards = due(deck);
  if (!cards.length) { kit.toast("Nothing due - come back tomorrow"); return; }
  S.study = { deck, queue: cards.sort(() => Math.random() - 0.5), shown: false, right: 0, done: 0 };
  render();
}

async function grade(knew) {
  const st = S.study;
  const card = st.queue.shift();
  card.box = knew ? Math.min(GAPS.length - 1, (card.box || 0) + 1) : 0;
  card.due = addDays(knew ? GAPS[card.box] : 0);
  if (!knew) st.queue.push(card);
  else st.right++;
  st.done++;
  st.shown = false;
  await save();
  render();
}

function studyView() {
  const st = S.study;
  if (!st.queue.length) {
    return [kit.header("🧠", st.deck.name, "Session done"), kit.card(null, kit.empty("🎉", "All due cards done - " + st.right + " remembered.", "Back to decks", () => { S.study = null; render(); }))];
  }
  const card = st.queue[0];
  const face = h("div", { class: "lk-card accent", style: { minHeight: "220px", alignItems: "center", justifyContent: "center", textAlign: "center", fontSize: "20px", cursor: "pointer" },
    on: { click: () => { st.shown = true; render(); } } },
    h("div", { style: { whiteSpace: "pre-wrap" } }, card.front),
    st.shown ? h("hr", { class: "lk-divider", style: { width: "60%" } }) : null,
    st.shown ? h("div", { style: { whiteSpace: "pre-wrap", color: "var(--lk-accent)" } }, card.back) : h("div", { class: "lk-muted lk-small" }, "Click (or press Space) to show the answer"));
  return [kit.header("🧠", st.deck.name, st.queue.length + " left · box " + (card.box || 0), kit.button("Stop", () => { S.study = null; render(); }, "ghost")),
    face, st.shown ? h("div", { class: "lk-row", style: { justifyContent: "center" } }, kit.button("Again", () => grade(false), "danger"), kit.button("I knew it", () => grade(true), "primary")) : null];
}

function deckView(deck) {
  return [kit.header("🧠", deck.name, deck.cards.length + " cards · " + due(deck).length + " due",
    kit.button("‹ Decks", () => { S.deck = null; render(); }, "ghost"), kit.button("LOKI, write cards", () => lokiCards(deck)),
    kit.button("+ Card", () => addCard(deck)), kit.button("Study", () => startStudy(deck), "primary")),
  kit.card(null, deck.cards.length ? h("div", { class: "lk-list" }, deck.cards.map((c) => h("div", { class: "lk-item" },
    h("div", { class: "lk-grow" }, h("b", {}, c.front), h("div", { class: "lk-muted lk-small" }, c.back)),
    h("span", { class: "lk-tag" + (c.box >= 3 ? " ok" : "") }, "box " + (c.box || 0)),
    kit.button("✕", async () => { deck.cards = deck.cards.filter((x) => x.id !== c.id); await save(); render(); }, "ghost sm"))))
    : kit.empty("🃏", "No cards yet.", "Add a card", () => addCard(deck))),
  h("div", { class: "lk-row" }, kit.button("Delete deck", async () => {
    if (!(await kit.confirm("Delete the deck “" + deck.name + "”?", { ok: "Delete", danger: true }))) return;
    S.decks = S.decks.filter((d) => d.id !== deck.id); S.deck = null; await save(); render();
  }, "ghost danger sm"))];
}

function render() {
  if (S.study) return mount(root, studyView());
  if (S.deck) return mount(root, deckView(S.deck));
  const total = kit.sum(S.decks, (d) => due(d).length);
  mount(root, kit.header("🧠", "Study cards", total + " cards due today", kit.button("+ Deck", newDeck, "primary")),
    S.decks.length ? h("div", { class: "lk-grid" }, S.decks.map((d) => h("div", { class: "lk-card", style: { cursor: "pointer" }, on: { click: () => { S.deck = d; render(); } } },
      h("h3", {}, d.name), h("div", { class: "lk-row" }, h("span", { class: "lk-tag accent" }, due(d).length + " due"), h("span", { class: "lk-muted lk-small" }, d.cards.length + " cards")),
      kit.progress(d.cards.length ? d.cards.filter((c) => c.box >= 3).length / d.cards.length : 0))))
      : kit.empty("📚", "Make a deck to start studying.", "New deck", newDeck));
}

document.addEventListener("keydown", (e) => {
  if (!S.study || !S.study.queue.length || e.target.closest("input, textarea, .lk-overlay")) return;
  if (e.key === " " && !S.study.shown) { e.preventDefault(); S.study.shown = true; render(); }
  else if (S.study.shown && (e.key === "1" || e.key === "ArrowLeft")) grade(false);
  else if (S.study.shown && (e.key === "2" || e.key === "ArrowRight" || e.key === " ")) { e.preventDefault(); grade(true); }
});
loki.ready(load);
