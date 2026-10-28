// Lab > Tasks: what LOKI's agents were asked to do on this computer, what they finished, what failed and why (owner
// 2026-10-27: "there should be a clear finished jobs and tasks i dont understand what theyve been doing").
// GET /tasks/board (engine/task_board.py through the autopilot); POST /tasks/retry {id} tries one again now,
// POST /tasks/dismiss {id} takes a row off. Filters: Needs you / Trying again / Working / Finished / All; requests and
// standing goals apart. A finished row shows its answer and what it made (pictures as pictures, other files as paths).
// Plain DOM, CSP script-src 'self'; api() from app.js; polls every 10 s while it shows.
"use strict";

const LokiTaskBoard = (() => {
  const S = { root: null, list: null, head: null, data: null, filter: "attention", kind: "request", timer: 0, open: new Set() };
  const STORE = "loki-task-board";
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.reject(new Error("not ready")));
  const STATUS = {
    failed: ["Needs you", "It failed on every try - the reason is below. Try again, or change the request in LOKI_TASKS.md."],
    retrying: ["Trying again", "It failed; LOKI tries again on its own, told why the last try failed."],
    running: ["Working", "A team is on it right now."],
    done: ["Finished", "Done - its answer and what it made are below."],
    unknown: ["Unknown", "Its record is gone."],
  };
  const FILTERS = [["attention", "Needs you", (r) => r.status === "failed" || r.status === "retrying"],
    ["running", "Working", (r) => r.status === "running"], ["done", "Finished", (r) => r.status === "done"], ["all", "All", () => true]];
  const IMG = /\.(png|jpe?g|webp|gif)$/i;
  try { const s = JSON.parse(localStorage.getItem(STORE) || "{}"); if (s.filter) S.filter = s.filter; if (s.kind) S.kind = s.kind; } catch (_) { /* private window */ }
  const remember = () => { try { localStorage.setItem(STORE, JSON.stringify({ filter: S.filter, kind: S.kind })); } catch (_) { /* private window */ } };

  function when(t) {
    if (!t) return "";
    const s = Date.now() / 1000 - t;
    if (s < 90) return "just now";
    if (s < 5400) return Math.round(s / 60) + " min ago";
    if (s < 86400 * 2) return Math.round(s / 3600) + " h ago";
    return new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }
  function btn(label, tip, fn, cls) {
    const b = mk("button", "tb-btn" + (cls ? " " + cls : ""), label); b.type = "button";
    b.title = tip; b.dataset.tipName = label; b.dataset.tipWhat = tip;
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(b); });
    return b;
  }
  function title(text) {   // the request's first sentence, without the "[windows] DO FIRST -" prefix
    return String(text || "").replace(/^\s*(\[(windows|mac|linux|loki)\]\s*)+/i, "").replace(/^DO FIRST\s*-\s*/i, "")
      .split(/\n|(?<=[.!?])\s|\(owner/)[0].slice(0, 160);
  }
  function thumb(rel) {
    const parts = rel.split("/");
    if (!IMG.test(rel) || parts.length !== 2) return null;
    const img = mk("img", "tb-pic"); img.alt = rel;
    img.src = "/creations/" + parts.map(encodeURIComponent).join("/");
    img.addEventListener("error", () => img.remove());
    img.addEventListener("click", (e) => {
      e.stopPropagation();
      if (window.LokiViewer) window.LokiViewer.open([{ src: img.src, name: rel, path: rel }], 0);
    });
    return img;
  }

  function row(r) {
    const card = mk("article", "tb-row tb-" + r.status); card.dataset.id = r.id;
    const [label, what] = STATUS[r.status] || [r.status, ""];
    const top = mk("div", "tb-top");
    const pill = mk("span", "tb-pill", label); pill.title = what;
    const name = mk("span", "tb-name", title(r.text)); name.title = r.text;
    const meta = mk("span", "tb-meta", [r.kind === "goal" ? "standing goal" : "request",
      r.max_tries > 1 ? "try " + r.tries + " of " + r.max_tries : "", when(r.finished || r.started)].filter(Boolean).join(" · "));
    top.append(pill, name, meta);
    card.append(top);
    const sum = mk("p", "tb-sum", r.summary + (r.status === "retrying" && r.next_try
      ? " Next try " + (r.next_try * 1000 <= Date.now() ? "as soon as a slot is free." : "in " + Math.max(1, Math.round((r.next_try - Date.now() / 1000) / 60)) + " min.") : ""));
    card.append(sum);
    if (r.why) card.append(mk("p", "tb-why", "Why: " + r.why));
    if ((r.files || []).length) {
      const made = mk("div", "tb-made");
      const pics = mk("div", "tb-pics"), names = [];
      for (const f of r.files) { const t = thumb(f); if (t) pics.append(t); else names.push(f); }
      if (pics.childElementCount) made.append(pics);
      if (names.length) {
        const l = mk("p", "tb-files", "Made: " + names.slice(0, 6).join(", ") + (names.length > 6 ? " +" + (names.length - 6) : ""));
        if (typeof openFiles === "function") { l.classList.add("tb-link"); l.title = "Show in Files"; l.addEventListener("click", (e) => { e.stopPropagation(); openFiles(names[0]); }); }
        made.append(l);
      }
      card.append(made);
    }
    const acts = mk("div", "tb-acts");
    if (r.answer) {
      const more = btn(S.open.has(r.id) ? "Hide answer" : "Answer", "What the agent said when it stopped.", () => {
        if (S.open.has(r.id)) S.open.delete(r.id); else S.open.add(r.id); render();
      }, "quiet");
      acts.append(more);
    }
    if (r.kind === "request" && (r.status === "failed" || r.status === "retrying"))
      acts.append(btn("Try again now", "Start the next try now (a request that gave up gets one more).", async (b) => {
        b.disabled = true; const d = await call("/tasks/retry", { id: r.id }).catch(() => null); if (d && d.ok) { S.data = d; render(); } else b.disabled = false;
      }));
    if (r.status !== "running")
      acts.append(btn("Dismiss", "Take this off the board (the work itself stays).", async () => {
        const d = await call("/tasks/dismiss", { id: r.id }).catch(() => null); if (d && d.ok) { S.data = d; render(); }
      }, "quiet"));
    if (acts.childElementCount) card.append(acts);
    if (r.answer && S.open.has(r.id)) card.append(mk("pre", "tb-answer", r.answer));
    return card;
  }

  function render() {
    if (!S.root) return;
    const d = S.data;
    S.head.replaceChildren();
    if (!d || !d.ok) {
      S.list.replaceChildren(mk("p", "tb-empty", d && d.error ? d.error : "Loading the task board…"));
      return;
    }
    const rows = (d.rows || []).filter((r) => S.kind === "all" || r.kind === S.kind);
    const count = (fn) => rows.filter(fn).length;
    const bar = mk("div", "tb-filters"); bar.setAttribute("role", "tablist");
    for (const [id, label, fn] of FILTERS) {
      const b = mk("button", "tb-filter", label + " " + count(fn)); b.type = "button"; b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(S.filter === id));
      b.addEventListener("click", () => { S.filter = id; remember(); render(); });
      bar.append(b);
    }
    const kinds = mk("div", "tb-kinds");
    for (const [id, label, tip] of [["request", "Requests", "What you (or Claude) asked for in LOKI_TASKS.md."],
      ["goal", "Standing goals", "What the agents keep making on their own when nothing is asked."], ["all", "Both", "Requests and standing goals."]]) {
      const b = mk("button", "tb-kind", label); b.type = "button"; b.title = tip; b.setAttribute("aria-pressed", String(S.kind === id));
      b.addEventListener("click", () => { S.kind = id; remember(); render(); });
      kinds.append(b);
    }
    const c = d.counts || {};
    const line = mk("p", "tb-line", "On " + (d.machine || "this computer") + ": " + [["done", "finished"], ["failed", "need you"],
      ["retrying", "trying again"], ["running", "working"]].filter(([k]) => c[k]).map(([k, w]) => c[k] + " " + w).join(" · ")
      + " · report: harness_data/reports/tasks.md");
    S.head.append(bar, kinds, line);
    const fn = (FILTERS.find((f) => f[0] === S.filter) || FILTERS[3])[2];
    const shown = rows.filter(fn);
    S.list.replaceChildren(...(shown.length ? shown.slice(0, 120).map(row)
      : [mk("p", "tb-empty", S.filter === "attention" ? "Nothing needs you - everything either finished or is being tried again." : "Nothing here.")]));
  }

  async function refresh() {
    const d = await call("/tasks/board").catch((e) => ({ ok: false, error: String(e) }));
    S.data = d; render();
  }

  function open(container) {
    if (!S.root || S.root.parentNode !== container) {
      S.root = mk("section", "tb"); S.root.setAttribute("aria-label", "Task board");
      S.head = mk("div", "tb-head"); S.list = mk("div", "tb-list");
      S.root.append(S.head, S.list);
      container.replaceChildren(S.root);
    }
    render(); refresh();
    clearInterval(S.timer);
    S.timer = setInterval(() => { if (S.root && S.root.offsetParent !== null && !document.hidden) refresh(); }, 10000);
  }
  function leave() { clearInterval(S.timer); S.timer = 0; }

  return { open, leave, refresh, title, data: () => S.data };
})();
window.LokiTaskBoard = LokiTaskBoard;
