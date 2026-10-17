// Reading list - want to read, reading, finished; page progress, ratings and notes.
"use strict";
const { h, mount } = kit;
const root = document.getElementById("app");
const SHELVES = [{ value: "reading", label: "Reading" }, { value: "want", label: "Want to read" }, { value: "done", label: "Finished" }];
const S = { books: [], shelf: "reading" };   // books: [{id, title, author, status, pages, page, rating, notes, finished}]

async function load() {
  S.books = await loki.store.get("books", []);
  render();
}
const save = () => loki.store.set("books", S.books);

async function editBook(book) {
  const v = await kit.form(book ? "Edit book" : "Add a book", [
    { name: "title", label: "Title", value: book ? book.title : "", required: true },
    { name: "author", label: "Author", value: book ? book.author : "" },
    { name: "status", label: "Shelf", type: "select", options: SHELVES, value: book ? book.status : S.shelf },
    { name: "pages", label: "Pages", type: "number", value: book ? book.pages : "" },
    { name: "page", label: "I am on page", type: "number", value: book ? book.page : "" },
    { name: "rating", label: "Rating (1-5)", type: "number", value: book ? book.rating : "" },
    { name: "notes", label: "Notes", type: "textarea", value: book ? book.notes : "" },
  ], book ? "Save" : "Add");
  if (!v) return;
  const b = book || { id: kit.uid(), added: kit.today() };
  Object.assign(b, { title: v.title.trim(), author: (v.author || "").trim(), status: v.status, pages: v.pages || 0, page: v.page || 0,
    rating: Math.max(0, Math.min(5, Math.round(v.rating || 0))), notes: v.notes || "" });
  if (b.status === "done" && !b.finished) { b.finished = kit.today(); b.page = b.pages || b.page; }
  if (!book) S.books.push(b);
  await save();
  render();
}

async function suggest() {
  const liked = S.books.filter((b) => b.rating >= 4).map((b) => b.title + (b.author ? " by " + b.author : ""));
  kit.askLoki("Suggest 5 books I might like next, with one line each on why.", { liked, read: S.books.filter((b) => b.status === "done").map((b) => b.title) });
}

function render() {
  const year = String(new Date().getFullYear());
  const doneThisYear = S.books.filter((b) => b.status === "done" && String(b.finished || "").startsWith(year)).length;
  const list = S.books.filter((b) => b.status === S.shelf);
  mount(root,
    kit.header("📚", "Reading list", doneThisYear + " finished in " + year, kit.button("Suggest my next book", suggest), kit.button("+ Book", () => editBook(null), "primary")),
    h("div", { class: "lk-grid stats" },
      kit.stat("Reading", String(S.books.filter((b) => b.status === "reading").length)),
      kit.stat("Want to read", String(S.books.filter((b) => b.status === "want").length)),
      kit.stat("Finished", String(S.books.filter((b) => b.status === "done").length))),
    kit.tabs(SHELVES, S.shelf, (v) => { S.shelf = v; render(); }),
    list.length ? h("div", { class: "lk-grid two" }, list.map((b) => h("div", { class: "lk-card" },
      h("div", { class: "lk-card-head" }, h("h3", {}, b.title), kit.button("Edit", () => editBook(b), "ghost sm")),
      b.author ? h("div", { class: "lk-muted" }, b.author) : null,
      b.status === "reading" && b.pages ? h("div", { class: "lk-col", style: { gap: "4px" } }, kit.progress(b.page / b.pages), h("span", { class: "lk-small lk-muted" }, "page " + (b.page || 0) + " of " + b.pages)) : null,
      b.rating ? h("div", { "aria-label": b.rating + " of 5" }, "★".repeat(b.rating) + "☆".repeat(5 - b.rating)) : null,
      b.notes ? h("p", { class: "lk-small" }, b.notes) : null,
      h("div", { class: "lk-row" },
        b.status !== "reading" ? kit.button("Start reading", async () => { b.status = "reading"; await save(); render(); }, "sm") : null,
        b.status === "reading" ? kit.button("Update page", async () => { const p = await kit.ask("Which page are you on?", { type: "number", value: b.page }); if (p !== null) { b.page = Number(p) || 0; await save(); render(); } }, "sm") : null,
        b.status !== "done" ? kit.button("Finished", async () => { b.status = "done"; b.finished = kit.today(); b.page = b.pages || b.page; await save(); render(); }, "sm") : null,
        h("span", { class: "lk-spacer" }),
        kit.button("✕", async () => { if (await kit.confirm("Remove “" + b.title + "”?", { ok: "Remove", danger: true })) { S.books = S.books.filter((x) => x.id !== b.id); await save(); render(); } }, "ghost sm")))))
      : kit.card(null, kit.empty("📖", "No books on this shelf.", "Add a book", () => editBook(null))));
}

loki.ready(load);
