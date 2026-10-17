// Workbench - Claude Code / Ziva habits in LOKI's window (engine/workbench.py on the engine side).
//
//   /commands   type "/" in the message box: a palette of commands (modes, review, rewind,
//               background agents, teams, model switch, the world, the system check...)
//   @files      type "@" and part of a name: pick a workspace file; the engine attaches its
//               contents to the message
//   checkpoints every Build request is checkpointed first; after the reply a bar shows the
//               files it changed with Review (a diff) and Rewind (put them back)
"use strict";

const Workbench = (function () {
  const box = () => document.getElementById("prompt");
  let menu = null, items = [], index = 0, kind = "", token = { start: 0, end: 0 }, timer = 0;

  const COMMANDS = [
    { name: "help", hint: "list the commands", run: () => help() },
    { name: "ask", hint: "Ask mode: answer, change nothing", run: (a) => mode("ask", a) },
    { name: "plan", hint: "Plan mode: read, then write a plan", run: (a) => mode("plan", a) },
    { name: "build", hint: "Build mode: edit, run and verify", run: (a) => mode("build", a) },
    { name: "review", hint: "what the last request changed (a diff)", run: () => review("") },
    { name: "diff", hint: "same as /review", run: () => review("") },
    { name: "rewind", hint: "put files back to a checkpoint", run: () => rewindList() },
    { name: "checkpoint", hint: "save a checkpoint now [label]", run: (a) => checkpoint(a) },
    { name: "bg", hint: "hand a task to a background agent", arg: "task", run: (a) => background(a) },
    { name: "team", hint: "start an agent team on a goal", arg: "goal", run: (a) => team(a) },
    { name: "test", hint: "run the project's tests and fix what fails", run: (a) => buildSend("Run this project's tests. Fix what fails, then run them again and report." + (a ? " Focus: " + a : "")) },
    { name: "commit", hint: "commit the current changes with a good message", run: () => buildSend("Review the uncommitted changes in this project, then commit them with a short, accurate message. Do not push.") },
    { name: "model", hint: "switch model (name)", arg: "name", run: (a) => model(a) },
    { name: "clear", hint: "start a new chat", run: () => { if (typeof newChat === "function") newChat(); } },
    { name: "world", hint: "open LOKI World", run: () => settings("world") },
    { name: "machines", hint: "your linked machines", run: () => settings("machines") },
    { name: "check", hint: "prove every part of LOKI works", run: () => settings("system") },
    { name: "usage", hint: "what your requests cost", run: () => settings("usage") },
    { name: "memory", hint: "what LOKI remembers", run: () => settings("memory") },
    { name: "options", hint: "show 3-4 readings of a request, then pick one", arg: "request", run: (a) => offerOptions(a, true) },
    { name: "image", hint: "make an image with Higgsfield (uses your credits)", arg: "prompt", run: (a) => media(a) },
  ];

  // ---------------------------------------------------------------- commands
  function handleSlash(text) {
    const m = /^\/([a-z]+)\b\s*([\s\S]*)$/i.exec((text || "").trim());
    if (!m) return false;
    const cmd = COMMANDS.find((c) => c.name === m[1].toLowerCase());
    if (!cmd) { addNotice("Unknown command /" + m[1] + " - type / to see them all.", true); return true; }
    if (cmd.arg && !m[2].trim()) { addNotice("/" + cmd.name + " needs a " + cmd.arg + ".", true); return true; }
    Promise.resolve(cmd.run(m[2].trim())).catch((err) => addNotice(String(err), true));
    return true;
  }

  function help() {
    if (typeof showChat === "function") showChat();
    addLoki("**Commands**\n\n" + COMMANDS.map((c) => "- `/" + c.name + (c.arg ? " <" + c.arg + ">" : "") + "` - " + c.hint).join("\n") +
      "\n\nType `@` and part of a file name to attach a file from your workspace.");
  }

  async function mode(m, rest) {
    const data = await api("/mode", { mode: m });
    if (data.ok && typeof markMode === "function") markMode(data.mode);
    if (rest) send(rest);
    else addNotice("Mode: " + ((data && data.label) || m), false);
  }

  async function buildSend(text) {
    const data = await api("/mode", { mode: "build" });
    if (data.ok && typeof markMode === "function") markMode(data.mode);
    send(text);
  }

  function background(task) { if (typeof showChat === "function") showChat(); sendToBackground(task); }

  async function team(goal) {
    const data = await api("/teams", { goal }).catch((e) => ({ ok: false, error: String(e) }));
    if (typeof showChat === "function") showChat();
    if (data.ok) addLoki("Started a team on: **" + goal + "**. Watch it in the work strip and in LOKI World.");
    else addNotice(data.error || "Could not start the team.", true);
  }

  // ---------------------------------------------------------------- "which do you mean?"
  // An open request gets 3-4 readings first (engine/options.py; LOKI_OPTIONS auto|always|off).
  // Returns true when it showed them (the caller then waits for a pick instead of sending).
  async function offerOptions(text, force) {
    if (typeof showChat === "function" && force) showChat();
    if (typeof setStatus === "function") setStatus("Thinking about what you might mean…");
    const data = await api("/options", { text, force: !!force }).catch(() => null);
    if (typeof setStatus === "function") setStatus("Ready", true);
    if (!data || !data.offer || !(data.options || []).length) {
      if (force) addNotice((data && data.error) || "No different readings came up - send it as it is.", !data);
      return false;
    }
    addUser(text);
    const card = el("div", "options-card");
    card.append(el("div", "options-head", "A few ways to read this - pick one:"));
    const grid = el("div", "options-grid");
    const done = () => card.classList.add("picked");
    data.options.forEach((o, i) => {
      const b = el("button", "option");
      b.type = "button";
      b.append(el("span", "option-n", String(i + 1)), el("b", "", o.title));
      if (o.meaning) b.append(el("span", "option-meaning", o.meaning));
      if (o.plan) b.append(el("span", "option-plan", o.plan));
      b.addEventListener("click", () => { if (card.classList.contains("picked")) return; done(); b.classList.add("chosen"); send(o.prompt, { direct: true }); });
      grid.append(b);
    });
    const asis = el("button", "option-asis", "Just do it as I wrote it");
    asis.type = "button";
    asis.addEventListener("click", () => { if (card.classList.contains("picked")) return; done(); send(text, { direct: true, quiet: true }); });
    card.append(grid, asis);
    document.getElementById("transcript").append(card);
    card.scrollIntoView({ block: "end", behavior: "smooth" });
    return true;
  }

  async function media(prompt) {
    if (typeof showChat === "function") showChat();
    addNotice("Asking Higgsfield for: " + prompt + " (this can take a minute)");
    const data = await api("/media/generate", { prompt, kind: "image" }).catch((e) => ({ ok: false, error: String(e) }));
    if (data.ok) addLoki("Made with Higgsfield: " + ((data.files || []).map((f) => "`" + f + "`").join(", ") || (data.urls || []).join(", ")));
    else addNotice(data.error || "Higgsfield did not make it.", true);
  }

  async function model(name) {
    if (typeof chooseModel === "function") return chooseModel(name);
    return api("/model", { model: name });
  }

  function settings(tab) {
    if (typeof openSettings === "function") openSettings();
    if (typeof showTab === "function") showTab(tab);
    if (tab === "world" && typeof showWorldPanel === "function") showWorldPanel();
  }

  async function checkpoint(label) {
    const data = await api("/checkpoints/take", { label: label || "saved by you" });
    addNotice(data.ok ? "Checkpoint " + data.id + " saved." : (data.error || "Could not save a checkpoint."), !data.ok);
  }

  // ---------------------------------------------------------------- after a reply: what changed
  function afterReply(data) {
    if (!data || !data.checkpoint) return;
    const files = data.changed_files || [];
    if (!files.length) return;
    const bar = el("div", "changes-bar");
    const added = files.reduce((n, f) => n + (f.added || 0), 0), removed = files.reduce((n, f) => n + (f.removed || 0), 0);
    bar.append(el("span", "changes-sum", files.length + " file" + (files.length === 1 ? "" : "s") + " changed"),
      el("span", "changes-add", "+" + added), el("span", "changes-rem", "−" + removed));
    const names = el("span", "changes-names", files.slice(0, 4).map((f) => f.path.split("/").pop()).join(", ") + (files.length > 4 ? " …" : ""));
    const rv = el("button", "quiet small", "Review");
    rv.type = "button";
    rv.addEventListener("click", () => review(data.checkpoint));
    const rw = el("button", "quiet small", "Rewind");
    rw.type = "button";
    rw.addEventListener("click", () => rewind(data.checkpoint, bar));
    bar.append(names, rv, rw);
    const t = document.getElementById("transcript");
    t.append(bar);
    t.scrollTop = t.scrollHeight;
  }

  async function rewind(id, bar) {
    if (!confirm("Put the files back as they were before this request? (You can undo this: a checkpoint of now is saved first.)")) return;
    const data = await api("/checkpoints/rewind", { id });
    if (data.ok) {
      addNotice("Rewound to " + data.rewound_to + (data.removed && data.removed.length ? " (removed " + data.removed.length + " new file(s))" : "") +
        ". Undo with /rewind → " + data.undo + ".", false);
      if (bar) bar.classList.add("rewound");
    } else addNotice(data.error || "Could not rewind.", true);
  }

  // ---------------------------------------------------------------- the diff / checkpoint viewer
  function modal(title) {
    const back = el("div", "wb-modal");
    const panel = el("div", "wb-panel");
    const head = el("div", "wb-head");
    const close = el("button", "quiet", "Close");
    close.type = "button";
    close.addEventListener("click", () => back.remove());
    head.append(el("h3", "", title), close);
    panel.append(head);
    back.append(panel);
    back.addEventListener("click", (e) => { if (e.target === back) back.remove(); });
    document.addEventListener("keydown", function esc(e) { if (e.key === "Escape") { back.remove(); document.removeEventListener("keydown", esc); } });
    document.body.append(back);
    return panel;
  }

  async function review(id) {
    const data = await api("/checkpoints/changes" + (id ? "?id=" + encodeURIComponent(id) : ""));
    if (!data.ok) { addNotice(data.error || "Nothing to review yet - checkpoints start with your first Build request.", true); return; }
    const panel = modal("Changes since " + data.since + (data.label ? " · " + data.label.slice(0, 60) : ""));
    if (!data.files.length) { panel.append(el("p", "note", "No files changed since that checkpoint.")); return; }
    const list = el("div", "wb-files");
    for (const f of data.files) {
      const row = el("div", "wb-file");
      row.append(el("span", "wb-path", f.path), el("span", "changes-add", f.binary ? "binary" : "+" + f.added), el("span", "changes-rem", f.binary ? "" : "−" + f.removed));
      list.append(row);
    }
    const pre = el("pre", "wb-diff");
    for (const line of String(data.diff || "").split("\n")) {
      const cls = line.startsWith("+++") || line.startsWith("---") ? "h" : line.startsWith("+") ? "a" : line.startsWith("-") ? "r" : line.startsWith("@@") ? "c" : "";
      pre.append(el("span", cls, line + "\n"));
    }
    const actions = el("div", "wb-actions");
    const rw = el("button", "send small", "Rewind these changes");
    rw.type = "button";
    rw.addEventListener("click", () => rewind(data.since));
    actions.append(rw);
    panel.append(list, pre, actions);
  }

  async function rewindList() {
    const data = await api("/checkpoints");
    const panel = modal("Checkpoints");
    if (!data.ok || !data.checkpoints.length) { panel.append(el("p", "note", "No checkpoints yet. Every Build request saves one first.")); return; }
    for (const c of data.checkpoints.slice(0, 40)) {
      const row = el("div", "wb-file");
      const when = new Date((c.t || 0) * 1000).toLocaleString();
      row.append(el("span", "wb-path", c.id + " · " + (c.label || c.kind)), el("span", "muted", when));
      const see = el("button", "quiet small", "Changes since");
      see.type = "button";
      see.addEventListener("click", () => review(c.id));
      const go = el("button", "quiet small", "Rewind");
      go.type = "button";
      go.addEventListener("click", () => rewind(c.id));
      row.append(see, go);
      panel.append(row);
    }
  }

  // ---------------------------------------------------------------- the palette (/ and @)
  function ensureMenu() {
    if (menu) return menu;
    menu = el("div", "wb-menu");
    menu.setAttribute("role", "listbox");
    menu.hidden = true;
    (document.querySelector(".composer-box") || document.getElementById("composer")).append(menu);
    return menu;
  }

  function show(list, k) {
    ensureMenu();
    items = list; kind = k; index = 0;
    menu.replaceChildren();
    if (!list.length) { menu.hidden = true; return; }
    list.forEach((it, i) => {
      const row = el("div", "wb-item" + (i === 0 ? " on" : ""));
      row.setAttribute("role", "option");
      row.append(el("b", "", it.label), el("span", "", it.hint || ""));
      row.addEventListener("mousedown", (e) => { e.preventDefault(); index = i; pick(); });
      menu.append(row);
    });
    menu.hidden = false;
  }

  function hide() { if (menu) menu.hidden = true; items = []; kind = ""; }

  function move(d) {
    if (!items.length) return;
    index = (index + d + items.length) % items.length;
    [...menu.children].forEach((n, i) => n.classList.toggle("on", i === index));
    menu.children[index].scrollIntoView({ block: "nearest" });
  }

  function pick() {
    const it = items[index], t = box();
    if (!it) return;
    const before = t.value.slice(0, token.start), after = t.value.slice(token.end);
    const insert = kind === "/" ? "/" + it.value + " " : "@" + it.value + (it.value.endsWith("/") ? "" : " ");
    t.value = before + insert + after;
    const caret = (before + insert).length;
    t.setSelectionRange(caret, caret);
    t.focus();
    hide();
    if (typeof autosize === "function") autosize();
  }

  function onInput() {
    const t = box(), caret = t.selectionStart, upto = t.value.slice(0, caret);
    const slash = /^\/([a-z]*)$/i.exec(upto);
    if (slash) {
      token = { start: 0, end: caret };
      const q = slash[1].toLowerCase();
      show(COMMANDS.filter((c) => c.name.startsWith(q)).map((c) => ({ label: "/" + c.name + (c.arg ? " <" + c.arg + ">" : ""), hint: c.hint, value: c.name })), "/");
      return;
    }
    const at = /(^|\s)@([\w./\\-]*)$/.exec(upto);
    if (at) {
      token = { start: caret - at[2].length - 1, end: caret };
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const data = await api("/workbench/files?q=" + encodeURIComponent(at[2])).catch(() => null);
        if (box().selectionStart !== caret) return;
        show(((data && data.files) || []).slice(0, 12).map((f) => ({ label: "@" + f, hint: "", value: f })), "@");
      }, 120);
      return;
    }
    hide();
  }

  function onKey(e) {
    if (!menu || menu.hidden || !items.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); e.stopImmediatePropagation(); move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); e.stopImmediatePropagation(); move(-1); }
    else if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey && (kind === "@" || box().value.trim().indexOf(" ") < 0))) {
      e.preventDefault(); e.stopImmediatePropagation(); pick();
    } else if (e.key === "Escape") { e.stopImmediatePropagation(); hide(); }
  }

  function wire() {
    const t = box();
    if (!t) return;
    t.addEventListener("input", onInput);
    t.addEventListener("keydown", onKey, true);   // before app.js's Enter-to-send
    t.addEventListener("blur", () => setTimeout(hide, 150));
    t.placeholder = "Message Loki  ·  / for commands  ·  @ to attach a file";
  }

  document.addEventListener("DOMContentLoaded", wire);
  return { handleSlash, afterReply, review, rewindList, offerOptions, COMMANDS };
})();
window.Workbench = Workbench;
