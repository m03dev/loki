// Files, session 29: browse the workspace, drop files in (copied into uploads/), preview them (PDF pages,
// pictures, tables, Markdown), "Ask LOKI about this file", recent files, document collections. Also makes
// file paths in LOKI's replies clickable (they open here) and shows charts LOKI made right in the chat.
// Uses api(), el(), renderMarkdown(), state from app.js and the icon pattern of icons.js (data-icon +
// data-tip-name/-what). Plain DOM (CSP script-src 'self').
"use strict";

Object.assign(ICON_PATHS, {
  folder: '<path d="M3.5 6.5a1.5 1.5 0 0 1 1.5-1.5h4.2l2 2.2H19a1.5 1.5 0 0 1 1.5 1.5v9.3A1.5 1.5 0 0 1 19 19.5H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
  file: '<path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4"/>',
  upload: '<path d="M12 15.5V4.5M7.5 9l4.5-4.5L16.5 9"/><path d="M4.5 15.5v4h15v-4"/>',
  external: '<path d="M13.5 4.5h6v6"/><path d="M19.5 4.5l-8 8"/><path d="M17.5 13.5v6h-13v-13h6"/>',
  markdown: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M6.5 15V9l2.5 3 2.5-3v6M15.5 9v5.5M13.5 12.5l2 2 2-2"/>',
  refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4h-4"/>',
  prev: '<path d="M14.5 6l-6 6 6 6"/>',
  next: '<path d="M9.5 6l6 6-6 6"/>',
  up: '<path d="M12 19V6M6.5 11.5L12 6l5.5 5.5"/>',
  stack: '<path d="M4 7.5h16M4 12h16M4 16.5h16"/><path d="M8 4.5v15"/>',
});

const FILE_ICON = { dir: "folder", pdf: "book", docx: "file", xlsx: "stack", csv: "stack", pptx: "layers", image: "image",
  markdown: "markdown", email: "send", epub: "book" };
const filesUi = { root: "", dir: "", sel: null, page: 1, sheet: "", list: null };

function fileSize(n) {
  if (!n) return "";
  return n < 1024 ? n + " B" : n < 1048576 ? Math.round(n / 1024) + " KB" : (n / 1048576).toFixed(1) + " MB";
}

function iconButton(icon, name, what, onClick) {
  const b = el("button", "mini icon-mini");
  b.type = "button";
  b.dataset.icon = icon;
  b.dataset.tipName = name;
  b.dataset.tipWhat = what;
  b.textContent = name;
  b.addEventListener("click", onClick);
  return b;
}

function openFiles(path, root) {
  const sheet = document.getElementById("files");
  if (!sheet) return;
  sheet.hidden = false;
  if (typeof path === "string" && path) {
    filesUi.root = root || "";
    const parts = path.split("/");
    filesUi.dir = parts.slice(0, -1).join("/");
    loadFileList().then(() => selectFile({ path, root: filesUi.root, name: parts[parts.length - 1] }));
  } else {
    loadFileList();
  }
  loadRecent();
  loadCollections();
}

function closeFiles() { const s = document.getElementById("files"); if (s) s.hidden = true; }

async function loadFileList() {
  const box = document.getElementById("files-list");
  if (!box) return;
  const q = "/files/list?dir=" + encodeURIComponent(filesUi.dir) + "&root=" + encodeURIComponent(filesUi.root);
  const data = await api(q).catch(() => null);
  box.replaceChildren();
  const crumbs = document.getElementById("files-crumbs");
  crumbs.replaceChildren();
  if (!data || !data.ok) { box.append(el("p", "note", (data && data.error) || "The Files view is not available in this engine.")); return; }
  for (const [i, c] of data.crumbs.entries()) {
    if (i) crumbs.append(el("span", "crumb-sep", "/"));
    const b = el("button", "crumb", c.name);
    b.type = "button";
    b.addEventListener("click", () => { filesUi.dir = c.path; loadFileList(); });
    crumbs.append(b);
  }
  if (!data.entries.length) box.append(el("p", "note", "Empty. Drop files here to copy them in."));
  for (const it of data.entries) {
    const row = el("button", "file-row" + (filesUi.sel && filesUi.sel.path === it.path ? " on" : ""));
    row.type = "button";
    row.dataset.path = it.path;
    row.innerHTML = iconSvg(FILE_ICON[it.kind] || "file");
    row.append(el("span", "file-name", it.name), el("small", "file-meta", it.dir ? "" : fileSize(it.size)));
    row.title = it.path;
    row.addEventListener("click", () => {
      if (it.dir) { filesUi.dir = it.path; loadFileList(); } else selectFile({ ...it, root: filesUi.root });
    });
    box.append(row);
  }
}

async function selectFile(it, page) {
  filesUi.sel = it;
  filesUi.page = page || 1;
  for (const r of document.querySelectorAll(".file-row")) r.classList.toggle("on", r.dataset.path === it.path);
  const pane = document.getElementById("files-preview");
  pane.replaceChildren(el("p", "note", "Opening " + it.name + "…"));
  const q = "/files/preview?path=" + encodeURIComponent(it.path) + "&root=" + encodeURIComponent(it.root || "") +
    "&page=" + filesUi.page + (filesUi.sheet ? "&sheet=" + encodeURIComponent(filesUi.sheet) : "");
  const d = await api(q).catch(() => null);
  pane.replaceChildren();
  if (!d || !d.ok) { pane.append(el("p", "note error", (d && d.error) || "Could not open it.")); return; }
  const head = el("div", "fp-head");
  head.append(el("b", "fp-name", d.name), el("small", "note", [d.type, fileSize(d.size)].filter(Boolean).join(" · ")));
  const tools = el("div", "fp-tools");
  tools.append(
    iconButton("ask", "Ask LOKI about this file", "Start a message about this file; LOKI reads it with its document tools.", () => askAbout(d)),
    iconButton("external", "Open", "Open it in this computer's own app for this kind of file.", async () => {
      const r = await api("/files/open", { path: d.path, root: d.root || "" });
      if (!r.ok) addNotice(r.error || "Could not open it.", true);
    }),
  );
  if (["pdf", "docx", "pptx", "xlsx", "html", "epub", "email", "image", "office"].includes(d.type)) {
    tools.append(iconButton("markdown", "Save as Markdown", "Convert it to clean Markdown next to the original.", async () => {
      const r = await api("/files/convert", { path: d.path, root: d.root || "" });
      if (r.ok) { loadFileList(); loadRecent(); setFilesNote("Saved " + r.path); } else setFilesNote(r.error || "Could not convert it.", true);
    }));
  }
  head.append(tools);
  pane.append(head);
  for (const w of d.warnings || []) pane.append(el("p", "note warn", w));
  if (d.kind === "image") {
    const img = el("img", "fp-img");
    img.alt = d.name;
    img.src = d.data_url;
    pane.append(img);
  } else if (d.kind === "pdf") {
    const nav = el("div", "fp-pages");
    nav.append(iconButton("prev", "Previous page", "Show the page before.", () => { if (d.page > 1) selectFile(it, d.page - 1); }),
      el("span", "note", "Page " + d.page + " of " + d.pages),
      iconButton("next", "Next page", "Show the next page.", () => { if (d.page < d.pages) selectFile(it, d.page + 1); }));
    pane.append(nav);
    if (d.image) { const img = el("img", "fp-img page"); img.alt = "Page " + d.page; img.src = d.image; pane.append(img); }
    else if (d.note) pane.append(el("p", "note", d.note));
    if (d.text) pane.append(el("pre", "fp-text", d.text));
  } else if (d.kind === "table") {
    if ((d.sheets || []).length > 1) {
      const chips = el("div", "chips");
      for (const s of d.sheets) {
        const b = el("button", "chip" + (s === d.sheet ? " on" : ""), s);
        b.type = "button";
        b.addEventListener("click", () => { filesUi.sheet = s; selectFile(it); });
        chips.append(b);
      }
      pane.append(chips);
    }
    pane.append(tableEl(d.columns, d.rows));
    if (d.total > d.rows.length) pane.append(el("p", "note", d.total + " rows - the first " + d.rows.length + " are shown."));
  } else if (d.kind === "markdown") {
    const body = el("div", "text fp-md");
    body.innerHTML = renderMarkdown(d.markdown || "");
    pane.append(body);
  } else {
    pane.append(el("p", "note", d.error || d.note || "No preview for this kind of file - Open shows it in its own app."));
  }
  filesUi.sheet = "";
}

function tableEl(columns, rows) {
  const wrap = el("div", "fp-table");
  const t = el("table");
  const tr = el("tr");
  for (const c of columns) tr.append(el("th", "", c));
  const thead = el("thead"); thead.append(tr);
  const tbody = el("tbody");
  for (const r of rows) { const row = el("tr"); for (const c of r) row.append(el("td", "", c)); tbody.append(row); }
  t.append(thead, tbody);
  wrap.append(t);
  return wrap;
}

function askAbout(d) {
  const where = d.root ? d.root + "/" + d.path : d.path;
  const prompt = document.getElementById("prompt");
  closeFiles();
  if (!prompt) return;
  prompt.value = "About the file `" + where + "`: ";
  prompt.focus();
  prompt.dispatchEvent(new Event("input"));
}

function setFilesNote(text, bad) {
  const n = document.getElementById("files-note");
  if (n) { n.textContent = text; n.classList.toggle("error", !!bad); }
}

async function loadRecent() {
  const box = document.getElementById("files-recent");
  if (!box) return;
  const d = await api("/files/recent").catch(() => null);
  box.replaceChildren();
  const files = (d && d.files) || [];
  if (!files.length) { box.append(el("p", "note", "Nothing yet.")); return; }
  for (const it of files.slice(0, 8)) {
    const b = el("button", "chip recent");
    b.type = "button";
    b.innerHTML = iconSvg(FILE_ICON[it.kind] || "file");
    b.append(el("span", "", it.name));
    b.title = (it.root ? it.root + "/" : "") + it.path + (it.how ? " - " + it.how : "");
    b.addEventListener("click", () => openFiles(it.path, it.root || ""));
    box.append(b);
  }
}

async function loadCollections() {
  const box = document.getElementById("files-collections");
  if (!box) return;
  const d = await api("/files/collections").catch(() => null);
  box.replaceChildren();
  const list = (d && d.collections) || [];
  const ws = el("button", "chip" + (filesUi.root === "" ? " on" : ""), "Workspace");
  ws.type = "button";
  ws.addEventListener("click", () => { filesUi.root = ""; filesUi.dir = ""; loadFileList(); loadCollections(); });
  box.append(ws);
  for (const c of list) {
    const b = el("button", "chip" + (filesUi.root === c.name ? " on" : ""), c.name);
    b.type = "button";
    b.title = c.folder + " - " + c.documents + " documents, " + c.chunks + " passages indexed" + (c.indexing ? " (indexing…)" : "");
    b.addEventListener("click", () => { filesUi.root = c.name; filesUi.dir = ""; loadFileList(); loadCollections(); });
    box.append(b);
  }
  const add = iconButton("book", "Chat with this folder", "Add the folder you are in as a document collection: LOKI indexes it and answers questions with page citations.", async () => {
    if (filesUi.root) { setFilesNote("This is already a collection."); return; }
    const r = await api("/files/collections", { action: "add", folder: filesUi.dir || "." });
    setFilesNote(r.ok ? "Added " + r.collection.name + " - indexing in the background." : (r.error || "Could not add it."), !r.ok);
    loadCollections();
  });
  box.append(add);
}

async function uploadFiles(fileList, folder) {
  const dir = folder !== undefined ? folder : (filesUi.root ? "uploads" : (filesUi.dir || "uploads"));
  const done = [];
  for (const f of fileList) {
    setFilesNote("Copying " + f.name + "…");
    try {
      const r = await fetch("/files/upload?name=" + encodeURIComponent(f.name) + "&dir=" + encodeURIComponent(dir), {
        method: "POST", headers: { Authorization: "Bearer " + state.token, "Content-Type": "application/octet-stream" }, body: f });
      const d = await r.json();
      if (d.ok) done.push(d.path); else setFilesNote(f.name + ": " + (d.error || "failed"), true);
    } catch (_) { setFilesNote(f.name + ": could not reach LOKI", true); }
  }
  if (done.length) setFilesNote("Copied in: " + done.join(", "));
  loadFileList();
  loadRecent();
  return done;
}

// ------------------------------------------------------------------ chat: file paths open here, charts show
const FILE_PATH_RE = /^[\w .()\/-]+\.(pdf|docx|xlsx|pptx|csv|tsv|png|jpe?g|gif|webp|md|txt|epub|eml|html?|json)$/i;

function enhanceTranscript(root) {
  for (const code of root.querySelectorAll(".turn.loki code:not([data-file-done])")) {
    code.dataset.fileDone = "1";
    const text = code.textContent.trim();
    if (!FILE_PATH_RE.test(text) || text.startsWith("/") || text.includes("..")) continue;
    code.classList.add("file-link");
    code.tabIndex = 0;
    code.title = "Open " + text + " in Files";
    code.addEventListener("click", () => openFiles(text, ""));
    if (/\.(png|jpe?g|gif|webp)$/i.test(text) && !code.closest("pre")) showInlineImage(code, text);
  }
  // ![chart](analysis/…/x.png) arrives escaped as text: show the picture after the paragraph
  for (const p of root.querySelectorAll(".turn.loki .text p:not([data-img-done]), .turn.loki .text li:not([data-img-done])")) {
    p.dataset.imgDone = "1";
    for (const m of p.textContent.matchAll(/!\[([^\]]*)\]\(([\w .()\/-]+\.(?:png|jpe?g|gif|webp))\)/gi)) {
      if (m[2].startsWith("/") || m[2].includes("..")) continue;
      showInlineImage(p, m[2], m[1]);
    }
  }
}

async function showInlineImage(after, path, alt) {
  const d = await api("/files/preview?path=" + encodeURIComponent(path)).catch(() => null);
  if (!d || d.kind !== "image") return;
  const img = el("img", "chat-img");
  img.src = d.data_url;
  img.alt = alt || path;
  img.title = "Open " + path + " in Files";
  img.addEventListener("click", () => openFiles(path, ""));
  after.after(img);
}

document.addEventListener("DOMContentLoaded", () => {
  const sheet = document.getElementById("files");
  document.getElementById("open-files")?.addEventListener("click", () => openFiles());
  document.getElementById("close-files")?.addEventListener("click", closeFiles);
  document.getElementById("files-refresh")?.addEventListener("click", () => { loadFileList(); loadRecent(); loadCollections(); });
  document.getElementById("files-up")?.addEventListener("click", () => {
    filesUi.dir = filesUi.dir.split("/").slice(0, -1).join("/"); loadFileList();
  });
  const picker = document.getElementById("files-pick");
  document.getElementById("files-upload")?.addEventListener("click", () => picker && picker.click());
  picker?.addEventListener("change", async () => { await uploadFiles([...picker.files]); picker.value = ""; });
  sheet?.addEventListener("click", (e) => { if (e.target === sheet) closeFiles(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && sheet && !sheet.hidden) closeFiles(); });
  // drag & drop: on the Files view it copies into the folder shown; on the chat into uploads/ and the
  // message box asks about it
  const zone = document.getElementById("files-drop");
  for (const target of [sheet, document.getElementById("main")]) {
    if (!target) continue;
    target.addEventListener("dragover", (e) => {
      if (![...(e.dataTransfer?.types || [])].includes("Files")) return;
      e.preventDefault();
      if (target === sheet && zone) zone.classList.add("over");
      else document.body.classList.add("file-drag");
    });
    target.addEventListener("dragleave", (e) => {
      if (e.relatedTarget && target.contains(e.relatedTarget)) return;
      zone?.classList.remove("over"); document.body.classList.remove("file-drag");
    });
    target.addEventListener("drop", async (e) => {
      if (!e.dataTransfer || !e.dataTransfer.files.length) return;
      e.preventDefault();
      e.stopPropagation();
      zone?.classList.remove("over"); document.body.classList.remove("file-drag");
      if (target === sheet) { await uploadFiles([...e.dataTransfer.files]); return; }
      const done = await uploadFiles([...e.dataTransfer.files], "uploads");
      const prompt = document.getElementById("prompt");
      if (done.length && prompt) {
        prompt.value = (prompt.value ? prompt.value + " " : "") + done.map((p) => "`" + p + "`").join(", ") + " ";
        prompt.focus();
        prompt.dispatchEvent(new Event("input"));
        addNotice("Copied into the workspace: " + done.join(", "));
      }
    });
  }
  const transcript = document.getElementById("transcript");
  if (transcript) {
    let queued = false;
    new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; enhanceTranscript(transcript); });
    }).observe(transcript, { childList: true, subtree: true });
  }
});
