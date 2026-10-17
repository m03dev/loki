// Notes - quick notes with search, pins and tags; saved as you type.
"use strict";
const { h, mount } = kit;
const root = document.getElementById("app");
const S = { notes: [], open: null, query: "", tag: "" };   // notes: [{id, title, body, tags: [], pinned, t}]

async function load() {
  S.notes = await loki.store.get("notes", []);
  if (S.notes.length) S.open = kit.sortBy(S.notes, (n) => n.t, true)[0].id;
  render();
}
const persist = kit.debounce(() => loki.store.set("notes", S.notes), 500);
const saveNow = () => loki.store.set("notes", S.notes);

async function newNote() {
  const note = { id: kit.uid(), title: "", body: "", tags: [], pinned: false, t: Date.now() };
  S.notes.push(note);
  S.open = note.id;
  await saveNow();
  render();
  const t = document.querySelector("#note-title");
  if (t) t.focus();
}

function editorView(note) {
  const touch = (patch) => { Object.assign(note, patch, { t: Date.now() }); persist(); };
  return kit.card(null,
    h("div", { class: "lk-row nowrap" },
      kit.input({ id: "note-title", value: note.title, placeholder: "Title", style: { fontSize: "18px", fontWeight: "600", border: "0", background: "transparent", padding: "4px 0" },
        on: { input: (e) => touch({ title: e.target.value }), change: () => render() } }),
      kit.button(note.pinned ? "★ Pinned" : "☆ Pin", async () => { note.pinned = !note.pinned; await saveNow(); render(); }, "ghost sm"),
      kit.button("✕", async () => { if (await kit.confirm("Delete this note?", { ok: "Delete", danger: true })) { S.notes = S.notes.filter((x) => x.id !== note.id); S.open = null; await saveNow(); render(); } }, "ghost sm")),
    h("textarea", { class: "lk-textarea", style: { minHeight: "340px" }, placeholder: "Write anything…", on: { input: (e) => touch({ body: e.target.value }) } }, note.body),
    h("div", { class: "lk-row" },
      kit.input({ value: (note.tags || []).join(", "), placeholder: "tags, comma separated", style: { maxWidth: "320px" },
        on: { change: (e) => { touch({ tags: e.target.value.split(",").map((x) => x.trim().toLowerCase()).filter(Boolean) }); render(); } } }),
      h("span", { class: "lk-spacer" }),
      kit.button("Summarise with LOKI", () => kit.askLoki("Summarise this note in a few bullet points and list any to-dos in it.", { note: { title: note.title, body: note.body } }), "sm"),
      kit.button("Save as file", async () => { const s = await loki.files.save((note.title || "note").replace(/[^\w -]/g, "") + ".md", "# " + (note.title || "Note") + "\n\n" + note.body); if (s) kit.toast("Saved " + s.name, "ok"); }, "sm")));
}

function render() {
  const q = S.query.trim().toLowerCase();
  const tags = [...new Set(S.notes.flatMap((n) => n.tags || []))].sort();
  const list = kit.sortBy(S.notes.filter((n) => (!q || (n.title + " " + n.body).toLowerCase().includes(q)) && (!S.tag || (n.tags || []).includes(S.tag))),
    (n) => (n.pinned ? 1e15 : 0) + n.t, true);
  const open = S.notes.find((n) => n.id === S.open);
  mount(root,
    kit.header("📝", "Notes", S.notes.length + " notes", kit.button("+ Note", newNote, "primary")),
    h("div", { style: { display: "grid", gridTemplateColumns: "minmax(220px, 300px) 1fr", gap: "12px", alignItems: "start" } },
      kit.card(null,
        kit.input({ type: "search", placeholder: "Search notes", value: S.query, on: { input: kit.debounce((e) => { S.query = e.target.value; render(); const s = document.querySelector("input[type=search]"); s.focus(); s.setSelectionRange(s.value.length, s.value.length); }, 200) } }),
        tags.length ? h("div", { class: "lk-row", style: { gap: "4px" } }, tags.map((t) => h("button", { type: "button", class: "lk-tag" + (S.tag === t ? " accent" : ""), style: { border: "0", cursor: "pointer" },
          on: { click: () => { S.tag = S.tag === t ? "" : t; render(); } } }, "#" + t))) : null,
        list.length ? h("div", { class: "lk-list" }, list.map((n) => h("div", { class: "lk-item clickable", style: n.id === S.open ? { borderColor: "var(--lk-accent)" } : null, on: { click: () => { S.open = n.id; render(); } } },
          h("div", { class: "lk-grow" }, h("b", {}, (n.pinned ? "★ " : "") + (n.title || "Untitled")), h("div", { class: "lk-muted lk-small" }, (n.body || "").slice(0, 60) || "—")))))
          : kit.empty("🗒️", q || S.tag ? "Nothing matches." : "No notes yet.")),
      open ? editorView(open) : kit.card(null, kit.empty("📝", "Pick a note or make a new one.", "New note", newNote))));
}

loki.ready(load);
