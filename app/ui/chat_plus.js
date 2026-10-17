// Research round 3 - what every good chat app has (Open WebUI, LibreChat, Lobe Chat, Msty, Cherry Studio):
//   on each message: Copy; Edit and send again (yours); Regenerate and Branch from here (LOKI's);
//   a chat menu (top bar): export this chat (Markdown / page / JSON), export all, import chats from
//   ChatGPT / Claude / Open WebUI / LibreChat / Markdown, compare models side by side;
//   a prompt library (the book button in the message box; /p <name>, /prompts);
//   /compare, /weather, /news, /time, /translate, /export, /import.
// Engine side: engine/assist_api.py. Hooks only by wrapping app.js's global addUser/addLoki - app.js is not edited.
"use strict";

const ChatPlus = (function () {
  const $q = (s, r) => (r || document).querySelector(s);
  const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const norm = (t) => String(t || "").split(/\s+/).join(" ").trim();
  const btn = (icon, name, what, fn, cls) => Artifacts.button(icon, name, what, fn, cls);

  function occurrence(turn, role) {
    const raw = norm(turn.dataset.raw);
    let n = 0;
    for (const t of document.querySelectorAll("#transcript .turn." + role)) {
      if (t === turn) return n;
      if (norm(t.dataset.raw) === raw) n++;
    }
    return n;
  }

  function busyNote() {
    if (state.busy) { addNotice("LOKI is still answering - wait for it, or press Stop.", true); return true; }
    return false;
  }

  // ------------------------------------------------------------------ message actions
  function actionsFor(turn, role) {
    if (turn.querySelector(".msg-actions")) return;
    const bar = node("div", "msg-actions");
    bar.append(btn("copy", "Copy", "Copy this message.", (b) => Artifacts.copyText(turn.dataset.raw || "", b)));
    if (role === "user") {
      bar.append(btn("pen", "Edit", "Change this message and send it again (LOKI forgets what came after it).", () => edit(turn)));
    } else {
      bar.append(btn("update", "Regenerate", "Ask again for a new answer to the message before this one.", () => regenerate(turn)),
        btn("branch", "Branch from here", "Start a new chat that keeps everything up to here; this chat stays as it is.", () => branch(turn)));
    }
    turn.append(bar);
  }

  async function cutAndSend(userTurn, text) {
    const out = await api("/convo/cut", { id: state.active, text: userTurn.dataset.raw, occurrence: occurrence(userTurn, "user") });
    if (!out.ok) { addNotice(out.error || "Could not change the chat.", true); return; }
    renderMessages(out.messages);
    send(text, { direct: true });
  }

  function edit(turn) {
    if (busyNote() || turn.querySelector(".edit-box")) return;
    const bubble = $q(".bubble", turn);
    const box = node("div", "edit-box");
    const area = node("textarea"); area.value = turn.dataset.raw || ""; area.rows = Math.min(10, area.value.split("\n").length + 1);
    const row = node("div", "edit-row");
    const go = node("button", "send small", "Send"); go.type = "button";
    const cancel = node("button", "quiet small", "Cancel"); cancel.type = "button";
    row.append(cancel, go);
    box.append(area, row);
    bubble.hidden = true;
    turn.append(box);
    area.focus();
    cancel.addEventListener("click", () => { box.remove(); bubble.hidden = false; });
    const submit = () => { const t = area.value.trim(); if (t) cutAndSend(turn, t); };
    go.addEventListener("click", submit);
    area.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } if (e.key === "Escape") cancel.click(); });
  }

  function previousUser(turn) {
    let t = turn.previousElementSibling;
    while (t && !(t.classList.contains("turn") && t.classList.contains("user"))) t = t.previousElementSibling;
    return t;
  }

  function regenerate(turn) {
    if (busyNote()) return;
    const user = previousUser(turn);
    if (!user) { addNotice("There is no message before this answer to ask again.", true); return; }
    cutAndSend(user, user.dataset.raw);
  }

  async function branch(turn) {
    if (busyNote()) return;
    const out = await api("/convo/branch", { id: state.active, role: "assistant", text: turn.dataset.raw, occurrence: occurrence(turn, "loki") });
    if (!out.ok) { addNotice(out.error || "Could not branch.", true); return; }
    applyConversations({ ok: true, conversations: out.conversations, active: out.active, messages: out.messages });
    addNotice("New branch - this is a copy of the chat up to that answer. The original is still in the list.");
  }

  // ------------------------------------------------------------------ chat menu: export / import / compare
  async function exportChat(format, all) {
    const out = await api("/convo/export", { id: state.active, format, all: !!all });
    if (!out.ok) { addNotice(out.error || "Export failed.", true); return; }
    showChat();
    addNotice("Saved " + out.path + " in your workspace" + (all ? " (" + out.count + " chats)" : "") + ".");
  }

  let fileInput = null;
  function importChats() {
    if (!fileInput) {
      fileInput = node("input"); fileInput.type = "file"; fileInput.accept = ".json,.md,.markdown,.txt"; fileInput.hidden = true;
      document.body.append(fileInput);
      fileInput.addEventListener("change", async () => {
        const f = fileInput.files && fileInput.files[0];
        fileInput.value = "";
        if (!f) return;
        showChat();
        addNotice("Reading " + f.name + "...");
        const text = await f.text();
        const out = await api("/convo/import", { name: f.name, text });
        if (!out.ok) { addNotice(out.error || "Import failed.", true); return; }
        applyConversations({ ok: true, conversations: out.conversations });
        addNotice("Imported " + out.imported + " chat" + (out.imported === 1 ? "" : "s") + " from " + out.source + (out.skipped ? " (" + out.skipped + " empty ones skipped)" : "") + ". They are in the list on the left.");
      });
    }
    fileInput.click();
  }

  let menu = null;
  function chatMenu(anchor) {
    if (menu) { menu.remove(); menu = null; return; }
    menu = node("div", "chat-menu"); menu.setAttribute("role", "menu");
    const item = (label, fn) => { const b = node("button", "", label); b.type = "button"; b.setAttribute("role", "menuitem"); b.addEventListener("click", () => { menu.remove(); menu = null; fn(); }); menu.append(b); };
    item("Export this chat as Markdown", () => exportChat("md"));
    item("Export this chat as a web page", () => exportChat("html"));
    item("Export this chat as JSON", () => exportChat("json"));
    item("Export all chats (JSON backup)", () => exportChat("json", true));
    item("Import chats (ChatGPT, Claude, Open WebUI, LibreChat, Markdown)...", importChats);
    item("Compare models side by side...", () => comparePanel(""));
    item("Prompt library...", () => promptPicker());
    const r = anchor.getBoundingClientRect();
    menu.style.top = Math.round(r.bottom + 6) + "px";
    menu.style.right = Math.round(window.innerWidth - r.right) + "px";
    document.body.append(menu);
    setTimeout(() => document.addEventListener("click", function off(e) { if (menu && !menu.contains(e.target)) { menu.remove(); menu = null; } document.removeEventListener("click", off); }), 0);
  }

  // ------------------------------------------------------------------ compare models
  async function comparePanel(text) {
    showChat();
    const box = node("div", "compare-box");
    const head = node("div", "compare-head");
    head.append(node("b", "", "Compare models"), node("span", "note", "Pick 2-4 models; each answers the same message, side by side (no tools). Vote for the better one - LOKI keeps a leaderboard."));
    const area = node("textarea", "compare-prompt"); area.rows = 2; area.placeholder = "What should they answer?"; area.value = text || "";
    const picks = node("div", "compare-picks");
    const data = await api("/models").catch(() => null);
    const ready = ((data && data.entries) || []).filter((e) => e.ready && !/^(smart|online|auto)$/.test(e.name)).slice(0, 14);
    if (!ready.length) picks.append(node("span", "note", "No model is ready - connect one in Settings > Connections."));
    ready.forEach((e, i) => {
      const lab = node("label", "check");
      const c = node("input"); c.type = "checkbox"; c.value = e.name; c.checked = i < 2;
      lab.append(c, document.createTextNode(" " + (e.label || e.name)));
      picks.append(lab);
    });
    const go = node("button", "send small", "Compare"); go.type = "button";
    const board = node("button", "quiet small", "Leaderboard"); board.type = "button";
    const row = node("div", "edit-row"); row.append(board, go);
    const out = node("div", "compare-grid");
    box.append(head, area, picks, row, out);
    $q("#transcript").append(box);
    scrollDown();
    area.focus();
    board.addEventListener("click", async () => {
      const b = await api("/compare/board");
      const rows = (b.board || []);
      addLoki(rows.length ? "**Model leaderboard** (your votes)\n\n| Model | Rating | Wins | Losses |\n|---|---|---|---|\n" +
        rows.map((r) => "| " + r.model + " | " + Math.round(r.rating) + " | " + r.wins + " | " + r.losses + " |").join("\n") : "No votes yet - compare two models and pick the better answer.");
    });
    go.addEventListener("click", async () => {
      const models = [...picks.querySelectorAll("input:checked")].map((c) => c.value);
      const prompt = area.value.trim();
      if (!prompt || models.length < 2) { addNotice("Write a message and pick at least two models.", true); return; }
      go.disabled = true; go.textContent = "Asking " + models.length + " models...";
      out.replaceChildren();
      const res = await api("/compare", { prompt, models }).catch((e) => ({ ok: false, error: String(e) }));
      go.disabled = false; go.textContent = "Compare again";
      if (!res.answers) { addNotice(res.error || "Nothing came back.", true); return; }
      out.style.setProperty("--cols", String(Math.min(res.answers.length, 4)));
      for (const a of res.answers) {
        const col = node("div", "compare-col" + (a.ok ? "" : " failed"));
        const top = node("div", "compare-col-head");
        top.append(node("b", "", a.model), node("small", "", a.seconds + " s"));
        const body = node("div", "text");
        if (a.ok) { body.innerHTML = renderMarkdown(a.text); Artifacts.decorate(body); } else body.textContent = a.error;
        col.append(top, body);
        if (a.ok) {
          col.append(btn("check", "This one is better", "Vote: this answer wins against the others (the leaderboard keeps the score).", async (b) => {
            const losers = res.answers.filter((x) => x.ok && x.model !== a.model).map((x) => x.model);
            const v = await api("/compare/vote", { winner: a.model, losers, prompt });
            if (v.ok) { for (const c of out.querySelectorAll(".compare-col")) c.classList.remove("winner"); col.classList.add("winner"); b.classList.add("done"); }
            else addNotice(v.error || "Vote not saved.", true);
          }, "vote"));
        }
        out.append(col);
      }
      scrollDown();
    });
  }

  // ------------------------------------------------------------------ prompt library
  let picker = null;
  async function promptPicker() {
    if (picker) { picker.remove(); picker = null; return; }
    picker = node("div", "prompt-picker"); picker.setAttribute("role", "dialog"); picker.setAttribute("aria-label", "Prompt library");
    const search = node("input", "prompt-search"); search.type = "search"; search.placeholder = "Find a prompt (or type a new one in the box and Save)";
    const list = node("div", "prompt-list");
    const foot = node("div", "edit-row");
    const save = node("button", "quiet small", "Save the message box as a prompt"); save.type = "button";
    const close = node("button", "quiet small", "Close"); close.type = "button";
    foot.append(save, close);
    picker.append(search, list, foot);
    document.body.append(picker);
    const draw = async () => {
      const data = await api("/prompts" + (search.value.trim() ? "?q=" + encodeURIComponent(search.value.trim()) : "")).catch(() => null);
      list.replaceChildren();
      for (const p of (data && data.prompts) || []) {
        const row = node("div", "prompt-row");
        const pick = node("button", "prompt-pick"); pick.type = "button";
        pick.append(node("b", "", p.title), node("small", "", "/p " + p.name + (p.variables.length ? " · asks for " + p.variables.map((v) => v.name).join(", ") : "")));
        pick.addEventListener("click", () => usePrompt(p));
        row.append(pick);
        row.append(btn("close", "Remove", p.builtin ? "Hide this starter prompt." : "Delete this prompt.", async () => {
          if (!confirm("Remove the prompt \"" + p.title + "\"?")) return;
          await api("/prompts/delete", { name: p.name }); draw();
        }, "small-icon"));
        list.append(row);
      }
      if (!list.children.length) list.append(node("p", "note", "No prompt matches."));
    };
    search.addEventListener("input", () => { clearTimeout(search._t); search._t = setTimeout(draw, 180); });
    close.addEventListener("click", () => { picker.remove(); picker = null; });
    save.addEventListener("click", async () => {
      const text = $q("#prompt").value.trim();
      if (!text) { addNotice("Write the prompt in the message box first. {{like this}} makes a blank to fill in.", true); return; }
      const name = (window.prompt("A short name for it (you can then type /p name):", "") || "").trim();
      if (!name) return;
      const out = await api("/prompts/save", { name, title: name, text });
      if (!out.ok) addNotice(out.error, true); else draw();
    });
    search.focus();
    draw();
  }

  async function usePrompt(p, given) {
    if (picker) { picker.remove(); picker = null; }
    const values = Object.assign({}, given || {});
    for (const v of p.variables || []) {
      if (values[v.name]) continue;
      const answer = window.prompt(p.title + " - " + v.name + (v.default ? " (blank = " + v.default + ")" : "") + ":", "");
      if (answer === null) return;
      values[v.name] = answer;
    }
    let clip = "";
    if (/\{\{\s*clipboard\s*\}\}/i.test(p.text)) { try { clip = await navigator.clipboard.readText(); } catch (_) { clip = ""; } }
    const out = await api("/prompts/fill", { name: p.name, values, clipboard: clip });
    if (!out.ok) { addNotice(out.error || "Could not fill the prompt.", true); return; }
    summon(true);
    const box = $q("#prompt");
    box.value = out.text; box.dispatchEvent(new Event("input")); box.focus();
  }

  // ------------------------------------------------------------------ everyday commands
  async function everyday(kind, q, extra) {
    showChat();
    const out = await api(kind === "translate" ? "/everyday" : "/everyday?kind=" + kind + "&q=" + encodeURIComponent(q || ""),
      kind === "translate" ? Object.assign({ kind }, extra) : undefined).catch((e) => ({ ok: false, text: String(e) }));
    if (out.ok) addLoki(out.text); else addNotice(String(out.text || out.error || "No answer").replace(/^error:\s*/, ""), true);
  }

  // ------------------------------------------------------------------ wiring
  function wrapTurns() {
    const _addUser = addUser, _addLoki = addLoki;
    addUser = function (text) {   // eslint-disable-line no-global-assign
      _addUser(text);
      const turn = [...document.querySelectorAll("#transcript .turn.user")].pop();
      if (turn) { turn.dataset.raw = String(text); actionsFor(turn, "user"); }
    };
    addLoki = function (text) {   // eslint-disable-line no-global-assign
      _addLoki(text);
      const turn = [...document.querySelectorAll("#transcript .turn.loki")].pop();
      if (turn) { turn.dataset.raw = String(text); Artifacts.decorate(turn); actionsFor(turn, "loki"); }
    };
  }

  function addCommands() {
    if (!window.Workbench || !Workbench.COMMANDS) return;
    const C = Workbench.COMMANDS;
    const more = [
      { name: "p", hint: "use a saved prompt: /p <name>", arg: "name", run: async (a) => {
        const data = await api("/prompts?q=" + encodeURIComponent(a));
        const p = ((data && data.prompts) || []).find((x) => x.name === a.toLowerCase()) || ((data && data.prompts) || [])[0];
        if (!p) { addNotice("No prompt called " + a + " - /prompts lists them.", true); return; }
        usePrompt(p);
      } },
      { name: "prompts", hint: "the prompt library", run: () => promptPicker() },
      { name: "compare", hint: "ask 2-4 models the same thing, side by side [message]", run: (a) => comparePanel(a) },
      { name: "export", hint: "save this chat in exports/ (md | html | json | all)", run: (a) => { const f = (a || "md").toLowerCase(); exportChat(f === "all" ? "json" : f, f === "all"); } },
      { name: "import", hint: "import chats from ChatGPT, Claude, Open WebUI, LibreChat or Markdown", run: () => importChats() },
      { name: "weather", hint: "the weather (place)", run: (a) => everyday("weather", a) },
      { name: "news", hint: "headlines [topic]", run: (a) => everyday("news", a) },
      { name: "time", hint: "the time in a city", arg: "city", run: (a) => everyday("time", a) },
      { name: "translate", hint: "translate: /translate <language>: <text>", arg: "language: text", run: (a) => {
        const m = /^([^:]{2,30}):\s*([\s\S]+)$/.exec(a);
        if (!m) { addNotice("Write it as /translate Spanish: your text", true); return; }
        everyday("translate", "", { to: m[1].trim(), text: m[2] });
      } },
    ];
    for (const c of more) if (!C.some((x) => x.name === c.name)) C.push(c);
  }

  function addButtons() {
    const right = $q(".topbar-right");
    if (right && !$q("#chat-menu-btn")) {
      const b = node("button", "chat-menu-btn"); b.type = "button"; b.id = "chat-menu-btn";
      b.dataset.icon = "dots"; b.dataset.tipName = "Chat menu"; b.dataset.tipWhat = "Export or import chats, compare models side by side, the prompt library.";
      b.textContent = "Chat menu";
      b.addEventListener("click", (e) => { e.stopPropagation(); chatMenu(b); });
      right.prepend(b);
    }
    const row = $q(".composer-row");
    if (row && !$q("#prompt-lib-btn")) {
      const b = node("button", "prompt-lib-btn"); b.type = "button"; b.id = "prompt-lib-btn";
      b.dataset.icon = "library"; b.dataset.tipName = "Prompt library"; b.dataset.tipWhat = "Ready-made prompts with blanks to fill in; save your own (/p <name>).";
      b.textContent = "Prompts";
      b.addEventListener("click", (e) => { e.stopPropagation(); promptPicker(); });
      const modes = $q(".modes", row);
      if (modes) modes.after(b); else row.prepend(b);
    }
  }

  // decorate turns that renderMessages draws (it calls addUser/addLoki, so the wrappers already did it)
  wrapTurns();
  document.addEventListener("DOMContentLoaded", () => { addCommands(); addButtons(); });
  return { comparePanel, promptPicker, importChats, exportChat, usePrompt, everyday };
})();
window.ChatPlus = ChatPlus;
