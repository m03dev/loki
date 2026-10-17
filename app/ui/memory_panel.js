// Settings > Memory: the one memory model (engine/memory_core.py, session 28).
//  - "LOKI learned N things today": what it wrote by itself, each with Keep / Undo
//  - search: exactly what a request would recall for those words (hybrid search, scores, the
//    project's own files with path:line)
//  - every memory by kind, with Edit / Forget; superseded memories with their history and Restore
//  - the machines it is shared with (last sync, Sync now), the project index (Reindex) and how it
//    searches (BM25, or hybrid with a local embedding model)
// GET /memory/core[?q=&kind=]; POST /memory/core {action: learn|edit|forget|undo|keep|keep_all|restore|sync|reindex}.
// Plain DOM (CSP). Icon buttons carry a title (tooltip) and an aria-label.
"use strict";

const MemoryPanel = { kind: "", query: "" };

function memIcon(symbol, label, onClick) {
  const b = el("button", "mini mem-icon", symbol);
  b.type = "button";
  b.title = label;
  b.setAttribute("aria-label", label);
  b.addEventListener("click", onClick);
  return b;
}

function memAgo(t) {
  if (!t) return "never";
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 90) return "just now";
  if (s < 5400) return Math.round(s / 60) + " min ago";
  if (s < 129600) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " days ago";
}

async function memPost(body, ok) {
  const res = await api("/memory/core", body).catch(() => null);
  if (!res || !res.ok) { addNotice((res && res.error) || "Could not change LOKI's memory.", true); return null; }
  if (ok) addNotice(ok);
  return res;
}

function memRow(item, labels, opts) {
  const r = el("div", "row lab-row mem-row" + (item.status === "superseded" ? " done" : ""));
  const text = el("div", "lab-text");
  const tag = el("span", "mem-kind mem-kind-" + (item.kind || "fact"), labels[item.kind] || item.kind || "memory");
  text.append(tag, el("span", "", " " + (item.text || "")));
  const meta = [];
  if (opts.score !== undefined) meta.push("score " + Number(opts.score).toFixed(3));
  if (item.source === "auto") meta.push("learned by LOKI");
  if (item.origin) meta.push("from " + item.origin);
  if (item.uses) meta.push("used " + item.uses + "x");
  if (meta.length) text.append(el("div", "note mem-meta", meta.join(" · ")));
  if ((item.history || []).length) {
    const h = el("details", "mem-history");
    h.append(el("summary", "", "Before (" + item.history.length + ")"));
    for (const old of item.history.slice().reverse()) h.append(el("div", "note", "· " + (old.text || "")));
    text.append(h);
  }
  const right = el("div", "lab-right");
  const id = String(item.id || "");
  if (opts.review) {
    right.append(memIcon("✓", "Keep: LOKI got this right", async () => { if (await memPost({ action: "keep", id })) loadMemoryCore(); }),
      memIcon("↶", "Undo: forget this on every machine", async () => { if (await memPost({ action: "undo", id }, "Forgotten.")) loadMemoryCore(); }));
  } else if (item.status === "superseded") {
    right.append(memIcon("⤺", "Restore: make this current again", async () => { if (await memPost({ action: "restore", id }, "Restored.")) loadMemoryCore(); }));
  } else if (!id.startsWith("skill:") && !id.startsWith("note:")) {
    right.append(memIcon("✎", "Edit this memory", async () => {
      const next = window.prompt("Change this memory:", item.text || "");
      if (next === null) return;
      if (await memPost({ action: "edit", id, text: next })) loadMemoryCore();
    }), memIcon("✕", "Forget this on every machine", async () => {
      if (await memPost({ action: "forget", id }, "Forgotten.")) loadMemoryCore();
    }));
  }
  r.append(text, right);
  return r;
}

async function loadMemoryCore(query) {
  const box = document.getElementById("memory-core");
  if (!box) return;
  if (query !== undefined) MemoryPanel.query = String(query || "");
  const q = MemoryPanel.query, kind = MemoryPanel.kind;
  const params = [];
  if (q) params.push("q=" + encodeURIComponent(q));
  if (kind) params.push("kind=" + encodeURIComponent(kind));
  const data = await api("/memory/core" + (params.length ? "?" + params.join("&") : "")).catch(() => null);
  box.replaceChildren();
  if (!data || !data.ok) { box.append(el("p", "note", "LOKI's memory is not available in this engine.")); return; }
  const labels = {};
  for (const k of data.kinds || []) labels[k.kind] = k.label;
  const stats = data.stats || {};

  // 1. what LOKI learned by itself today
  const today = data.today || [];
  const review = el("div", "mem-today");
  const head = el("div", "lab-head");
  head.append(el("b", "", today.length ? "LOKI learned " + today.length + " thing" + (today.length === 1 ? "" : "s") + " today"
    : "Nothing new learned today"));
  if (today.length > 1) head.append(memIcon("✓✓", "Keep all of today's", async () => { if (await memPost({ action: "keep_all" }, "Kept.")) loadMemoryCore(); }));
  review.append(head);
  for (const item of today) review.append(memRow(item, labels, { review: true }));
  if (!today.length) review.append(el("p", "note", "When you tell LOKI something lasting (\"I prefer short answers\", \"Mia is my sister\", \"we decided to use Godot\"), it remembers it and lists it here for you to check."));
  box.append(review);

  // 2. status line: machines, search mode, project index
  const status = el("div", "mem-status");
  const sync = data.sync || {};
  const peers = (sync.peers || []).filter((p) => p.linked || p.t);
  const syncText = peers.length
    ? "Shared with " + peers.map((p) => p.peer + " (" + (p.error ? "not reached: " + p.error.slice(0, 60) : "synced " + memAgo(p.t)) + ")").join(", ")
    : "Not shared yet - link your other machine in Settings > Machines";
  status.append(el("span", "note", "This machine: " + (sync.host || stats.host || "?") + ". " + syncText + "."));
  if (peers.length) status.append(memIcon("⟳", "Sync memory with your other machines now", async () => {
    const r = await memPost({ action: "sync" });
    if (r) addNotice((r.results || []).map((x) => x.peer + ": " + (x.ok ? "sent " + x.sent + ", got " + x.received : x.error)).join("; ") || "No linked machine.");
    loadMemoryCore();
  }));
  const search = stats.search || {};
  status.append(el("span", "note", " Search: " + (search.mode === "hybrid" ? "hybrid (BM25 + " + search.model + ")"
    : "BM25" + (search.note ? " - local embeddings " + search.note : " - add a local embedding model to Ollama (e.g. nomic-embed-text) for hybrid search")) + "."));
  const idx = data.index || {};
  if (idx.workspace) {
    status.append(el("span", "note", " Project files indexed: " + (idx.files || 0) + " (" + (idx.chunks || 0) + " passages)" + (idx.indexing ? ", indexing…" : "") + "."));
    status.append(memIcon("⎘", "Re-index the project's docs and code now", async () => {
      const r = await memPost({ action: "reindex" });
      if (r) addNotice("Indexed: " + r.files + " files, " + r.added + " new, " + r.changed + " changed, " + r.removed + " removed.");
      loadMemoryCore();
    }));
  }
  box.append(status);

  // 3. search + kind filter
  const form = el("form", "lab-idea");
  const input = el("input");
  input.placeholder = "What would LOKI recall for… (try a question)";
  input.value = q;
  input.setAttribute("aria-label", "Search LOKI's memory");
  const go = el("button", "", "Search");
  go.type = "submit";
  form.append(input, go);
  form.addEventListener("submit", (e) => { e.preventDefault(); loadMemoryCore(input.value); });
  box.append(form);
  const chips = el("div", "chips mem-kinds");
  const byKind = stats.by_kind || {};
  const mk = (k, label) => {
    const c = el("button", "chip" + (kind === k ? " on" : ""), label + (k && byKind[k] ? " " + byKind[k] : (!k ? " " + (stats.items || 0) : "")));
    c.type = "button";
    c.setAttribute("aria-pressed", kind === k ? "true" : "false");
    c.addEventListener("click", () => { MemoryPanel.kind = k; loadMemoryCore(); });
    return c;
  };
  chips.append(mk("", "All"));
  for (const k of data.kinds || []) if (k.kind !== "skill") chips.append(mk(k.kind, k.label));
  box.append(chips);

  // 4. the memories (or the search result, with scores and the project's passages)
  const rows = el("div", "rows");
  for (const item of data.items || []) rows.append(memRow(item, labels, q ? { score: item.score } : {}));
  if (!(data.items || []).length) rows.append(el("p", "note", q ? "LOKI would recall nothing from memory for that." : "Nothing remembered yet."));
  box.append(rows);
  if (q && (data.knowledge || []).length) {
    const kb = el("div", "rows mem-knowledge");
    kb.append(el("b", "", "From the project's own files"));
    for (const hit of data.knowledge) {
      const r = el("div", "row lab-row");
      r.append(el("div", "lab-text", hit.cite + " - " + String(hit.text || "").replace(/\s+/g, " ").slice(0, 220)));
      kb.append(r);
    }
    box.append(kb);
  }

  // 5. replaced memories (history kept) and learned skills
  if (!q && (data.superseded || []).length) {
    const old = el("details", "lab-lessons");
    old.append(el("summary", "", "Replaced by newer memories (" + data.superseded.length + ")"));
    const list = el("div", "rows");
    for (const item of data.superseded) list.append(memRow(item, labels, {}));
    old.append(list);
    box.append(old);
  }
  if ((data.skills || []).length) {
    const skills = el("details", "lab-lessons");
    skills.append(el("summary", "", "Skills LOKI learned from its own verified work (" + data.skills.length + ")"));
    const list = el("div", "rows");
    for (const s of data.skills) {
      const r = el("div", "row lab-row");
      r.append(el("div", "lab-text", s.id + " - " + (s.description || "")), el("span", "state", "used " + (s.uses || 0) + "x"));
      list.append(r);
    }
    skills.append(list);
    box.append(skills);
  }
}
