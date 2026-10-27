// LOKI's home screen is the preview hub (owner, 2026-10-21: "maybe we can preview projects we're working on in the home
// screen, combine studio with home"; "it'll be the home ... where we do preview of render and other things").
//
//   a big preview of the latest render (or the card you pick), then one grid of everything you are making - renders,
//   Forge models, Godot games, Studio sessions, the jobs on this machine and the worker farm - newest first, from ONE
//   engine call: GET /home/projects (engine/home_projects.py). A card shows its picture (or its kind's icon), its name
//   and when; a click shows it big, its open button (or a double-click) opens it where it lives: Forge, Render, Godot,
//   Studio, or the job's status. Kinds filter with icons; each kind says how to make one when there is none.
//   Studio (build or change an app with an agent) is a pane inside Home: the header's Studio button, a Studio card,
//   the sidebar's LOKI Studio button or Ctrl/Cmd+Shift+S; Back / Esc closes it. The chat stays one click away (the
//   word "Loki", or just type). Once a conversation runs the hub steps aside; on a new chat it folds to one row.
// Cleaned up 2026-10-21 (owner: "too much stuff happening all at once ... i like the preview but its too much and too
// many"): one header row with its icons on the left (the kind filter, a "working now" chip, chat + Studio), the big preview, then ONE row
// of recent things with "All" to see the rest. Jobs are not cards any more: the chip counts what runs and a click shows
// it live in the preview. No refresh / fold buttons (it refreshes itself). Later: a live view in the preview spot.
// Reworked 2026-10-26 (owner: "when i click on an image it takes me to the top and shows me thats wrong its jarring ...
// look at how other programs are managing it"): like Google Photos / Lightroom / Midjourney - a click on a card opens it
// RIGHT THERE in the viewer (pictures and 3D models; ‹ › through everything), the page never jumps or redraws; every
// card has thumbs up / down / delete on hover; the grid is everything, grouped by day (Today, Yesterday, dates) with
// "Show more" at the end instead of one row + "All"; thumbnail size S / M / L is remembered. Double-click (or the
// card's open icon, or Shift+Enter) still opens it where it lives. Keys: arrows walk, Enter opens, Del deletes (twice).
// Plain DOM, CSP script-src 'self' (no inline script, no eval); sizes in % / fr so it fits any window.
"use strict";

const LokiHome = (() => {
  const KIND = {
    made: { label: "Made", tip: "Pictures, sprites, sketches and videos LOKI made - the real thing, newest first.",
      empty: "Nothing made yet: ask LOKI for a picture, a sprite or a video and it shows up here.",
      icon: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="M20.5 16l-5-5-8.5 8"/>' },
    content: { label: "Content", tip: "What LOKI's agents make for the brand and marketing: names, logos, posts, ad drafts (the workspace's brand/ folder).",
      empty: "No content yet: LOKI's agents put names, logos, posts and ad drafts here (brand/ in the workspace).",
      icon: '<path d="M4 5h16v11H8l-4 3.5z"/><path d="M8 9h8M8 12h5"/>' },
    render: { label: "Render", tip: "Renders: path-traced and AI renders, from this computer or the worker farm.",
      empty: "No renders yet: open Render (or Forge > Render) and render a scene.",
      icon: '<circle cx="12" cy="12" r="3.2"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>' },
    forge: { label: "Forge", tip: "Forge models and scenes you saved.",
      empty: "No models yet: open Forge, draw, add a picture or describe one, then save it.",
      icon: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>' },
    godot: { label: "Godot", tip: "Your game projects in LOKI Projects.",
      empty: "No game projects yet: make a folder with a Godot project in LOKI Projects, or ask LOKI to start one.",
      icon: '<path d="M4 9.5l2-3.5 3 1.5L12 4l3 3.5 3-1.5 2 3.5-1.5 8.5h-13z"/><circle cx="9" cy="13" r="1.4"/><circle cx="15" cy="13" r="1.4"/>' },
    studio: { label: "Studio", tip: "Studio sessions: an app being built or changed with an agent.",
      empty: "No Studio sessions yet: open Studio and tell it what to build or change.",
      icon: '<path d="M8.5 7L3.5 12l5 5M15.5 7l5 5-5 5M13.5 4.5l-3 15"/>' },
    job: { label: "Agents", tip: "Your agents and teams: what each is making on every machine, newest first - double-click opens it in Lab > Agents.",
      empty: "No agent work yet: tick Run in background on a message, or start something in Lab > Agents > Make.",
      icon: '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>' },
  };
  // Owner 2026-10-26: "whats the point of the home middle collum if it doesnt have a thumbnail preview of whats inside
  // ... i dont wanna see folders or text i wanna see real results". The grid and the big preview show only things you
  // can SEE (a picture, a render, a model's picture, a video); games and Studio sessions live in the Engine tab and the
  // Studio button, jobs in the "working now" chip - and a job in the preview shows the picture it made, never its log.
  // + "job" = Agents (owner 2026-10-26: "remove the agent working and team from loki home chat move them over to lab ...
  // also add them to the tabs in that middle section")
  const ORDER = ["made", "render", "forge", "content", "job"];   // the filter and the grid
  const ICON = {
    all: '<rect x="4" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.6"/>',
    open: '<path d="M14 4.5h5.5V10"/><path d="M19.5 4.5L11 13"/><path d="M18 13.5v5a1 1 0 0 1-1 1H5.5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    chat: '<path d="M5 6.5h14v9H9l-4 3.5z"/>',
    refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4h-4"/>',
    fold: '<path d="M6 9l6 6 6-6"/>',
    size: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.4"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.4"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.4"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.4"/>',
    up: '<path d="M7 11v9H4v-9z"/><path d="M7 11l4-8c1.5 0 2.5 1 2.5 2.5V9h5a2 2 0 012 2.3l-1.2 7A2 2 0 0117.3 20H7"/>',
    down: '<path d="M17 13V4h3v9z"/><path d="M17 13l-4 8c-1.5 0-2.5-1-2.5-2.5V15h-5a2 2 0 01-2-2.3l1.2-7A2 2 0 016.7 4H17"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    back: '<path d="M15 5l-7 7 7 7"/>',
    pc: '<rect x="3" y="4" width="18" height="12" rx="1.6"/><path d="M8 20h8M12 16v4"/>',
  };
  const STORE = "loki-home";
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
  const S = { items: [], errors: {}, filter: "all", pick: "", shown: 60, size: "m", timer: 0, loading: false, loaded: false };
  const PAGE = 60, SIZES = { s: 110, m: 160, l: 240 };
  let pc = null, root = null, hero = null, grid = null, empty = null, more = null, live = null, studioPane = null, studioFrame = null, studioBody = null;
  try { const saved = JSON.parse(localStorage.getItem(STORE) || "{}") || {}; S.filter = saved.filter || "all"; if (!["all", "made", "render", "forge", "content", "job"].includes(S.filter)) S.filter = "all"; if (SIZES[saved.size]) S.size = saved.size; } catch (_) { /* private mode */ }
  const remember = () => { try { localStorage.setItem(STORE, JSON.stringify({ filter: S.filter, size: S.size })); } catch (_) { /* private mode */ } };

  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const svg = (paths) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + paths + "</svg>";
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.reject(new Error("not ready")));
  function iconBtn(cls, icon, name, what, fn) {
    const b = mk("button", "home-ico " + (cls || "")); b.type = "button";
    b.innerHTML = svg(icon); b.dataset.tipName = name; b.dataset.tipWhat = what; b.setAttribute("aria-label", name);
    b.addEventListener("click", fn);
    return b;
  }
  function ago(t) {
    if (!t) return "";
    const s = Math.max(0, Date.now() / 1000 - t);
    if (s < 60) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    if (s < 7 * 86400) return Math.round(s / 86400) + " d ago";
    return new Date(t * 1000).toLocaleDateString();
  }
  const keyOf = (it) => it.kind + ":" + it.path_or_id;
  const seeable = (it) => !!(it.thumb || it.video);
  // a tab shows ONLY its kind (owner 2026-10-26: "those tabs dont work they need to isolate whatever they have selected
  // like a filter"); agents' jobs only under Agents. seeable() keeps folders and text cards out, but an agent job is
  // shown under Agents even before it has a picture (its status is what you look at there)
  const visible = () => S.items.filter((it) => (S.filter === "job" ? it.kind === "job"
    : it.kind !== "job" && seeable(it) && (S.filter === "all" || it.kind === S.filter)));
  const running = () => S.items.filter((it) => it.kind === "job" && /^(working|running|queued|pending|starting)$/i.test(it.status || ""));
  const whatOpens = { made: "opens it in Files", render: "opens it in Studio", forge: "opens it in Forge", godot: "opens it in the Engine tab",
    studio: "opens it in Studio", content: "opens it in Files", job: "opens it in Lab > Agents" };

  // ---------------------------------------------------------------- building the hub (once)
  function build() {
    const main = document.getElementById("main");
    if (!main || root) return;
    root = mk("section", "home-hub"); root.id = "home-hub"; root.setAttribute("aria-label", "Home: your renders and projects");
    const head = mk("div", "home-head");
    const kinds = mk("div", "home-kinds"); kinds.setAttribute("role", "toolbar"); kinds.setAttribute("aria-label", "Show");
    const kindBtn = (id, icon, name, what) => {
      const b = iconBtn("home-kind", icon, name, what, () => { S.filter = id; S.pick = ""; S.shown = PAGE; remember(); render(); });
      b.dataset.kind = id; b.setAttribute("aria-pressed", String(S.filter === id));
      return b;
    };
    kinds.append(kindBtn("all", ICON.all, "Everything", "Everything LOKI made that you can see - pictures, renders, models, videos - newest first."));
    for (const k of ORDER) kinds.append(kindBtn(k, KIND[k].icon, KIND[k].label, KIND[k].tip));
    const acts = mk("div", "home-acts");
    acts.append(
      iconBtn("home-chat", ICON.chat, "Chat with LOKI", "Open the message box (or just start typing).", () => { if (typeof summon === "function") summon(true); }),
      iconBtn("home-studio-btn", KIND.studio.icon, "Studio", "Build or change an app with an agent, review the diff, ship it (" + (isMac ? "⌘" : "Ctrl+") + "Shift+S).", () => openStudio()));
    // what is running now (this computer and the worker farm): a click shows it live in the preview
    live = mk("button", "home-live"); live.type = "button"; live.hidden = true;
    live.dataset.tipName = "Working now"; live.dataset.tipWhat = "Jobs running on this computer and the worker farm - click to watch one in the preview.";
    live.addEventListener("click", () => { const r = running(); if (!r.length) return; const i = r.findIndex((it) => keyOf(it) === S.pick); S.pick = keyOf(r[(i + 1) % r.length]); render(); });
    const sizeBtn = iconBtn("home-size", ICON.size, "Thumbnail size", "Small, medium or large thumbnails (remembered).", () => {
      S.size = { s: "m", m: "l", l: "s" }[S.size] || "m"; remember(); applySize();
    });
    acts.prepend(sizeBtn);
    // where the heavy work goes (engine/offload.py): the Mac gives pictures, area edits, 3D and model clean-ups to the PC
    pc = iconBtn("home-pc", ICON.pc, "Your PC", "Checking whether your PC can take the heavy work ...", () => machines());
    pc.hidden = true;
    acts.prepend(pc);
    head.append(kinds, live, acts);   // all icons on the left; no title (the Home tab already says Home)
    hero = mk("div", "home-hero"); hero.setAttribute("aria-live", "polite");
    const recent = mk("div", "home-recent-head");     // kept for the chat-folded layout's styles
    recent.hidden = true;
    grid = mk("div", "home-grid"); grid.setAttribute("role", "list");
    more = mk("button", "home-more quiet small"); more.type = "button";
    more.addEventListener("click", () => { S.shown += PAGE; render(); });
    empty = mk("div", "home-empty");
    root.append(head, hero, recent, grid, more, empty);
    applySize();
    // left of the chat column (index.html #loki-split); older pages without the split: before the summon word
    const split = document.getElementById("loki-split"), summonBtn = document.getElementById("summon");
    if (split) split.prepend(root);
    else main.insertBefore(root, (summonBtn && summonBtn.parentNode === main) ? summonBtn : main.firstChild);
    grid.addEventListener("keydown", (e) => {   // arrow keys walk the cards
      const cards = [...grid.querySelectorAll(".home-card")]; const i = cards.indexOf(document.activeElement);
      if (i < 0) return;
      const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols(), ArrowUp: -cols() }[e.key];
      if (step) { e.preventDefault(); const n = cards[Math.max(0, Math.min(cards.length - 1, i + step))]; if (n) n.focus(); }
      else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        const it = S.items.find((x) => keyOf(x) === document.activeElement.dataset.key);
        if (e.shiftKey) open(it); else look(it);
      } else if (e.key === "Delete" || e.key === "Backspace") {
        const del = document.activeElement.querySelector(".home-card-del"); if (del) { e.preventDefault(); del.click(); }
      }
    });
    sync();
  }
  const WORK = { image: "pictures", img2img: "area edits", make_3d: "3D models", polish: "model clean-ups" };
  function pcText(st) {
    const m = (st.machines || [])[0];
    const gives = Object.keys(WORK).filter((k) => (st.gives || {})[k]);
    if (gives.length) return { on: true, name: "Your PC (" + st.gives[gives[0]] + ") does the heavy work",
      what: gives.map((k) => WORK[k]).join(", ") + " run on " + st.gives[gives[0]] + "; this computer stays light." };
    if (!m) return { on: false, name: "No PC linked", what: "Link your PC in Settings > Machines (paste its link code) and the heavy work runs there." };
    if (!m.online) return { on: false, name: m.name + " is not answering", what: "Open LOKI on " + m.name + " - until then heavy work waits or runs here. " + (m.error || "") };
    if (!m.work) return { on: false, name: m.name + " needs an update", what: m.name + " runs an older LOKI that cannot take work yet; it was asked to update itself." };
    return { on: false, name: m.name + " cannot take work yet", what: Object.entries(m.work_why || {}).map(([k, v]) => (WORK[k] || k) + ": " + v).join("; ") };
  }
  function machines() {
    if (!pc) return;
    call("/offload/status").then((st) => {
      if (!st || st.role !== "light") { pc.hidden = true; return; }   // the PC itself: nothing to show
      const t = pcText(st);
      pc.hidden = false; pc.classList.toggle("on", t.on); pc.classList.toggle("off", !t.on);
      pc.dataset.tipName = t.name; pc.dataset.tipWhat = t.what; pc.setAttribute("aria-label", t.name);
    }).catch(() => {});
  }
  function cols() { return Math.max(1, getComputedStyle(grid).gridTemplateColumns.split(" ").length); }
  function thumbOf(it, cls) {
    const box = mk("div", cls + " kind-" + it.kind);
    if (it.video && !it.thumb) {   // a video: its own first frames, playing silently
      const v = mk("video"); v.src = it.video; v.muted = true; v.loop = true; v.playsInline = true; v.preload = "metadata";
      v.autoplay = cls === "home-hero-pic";
      if (!v.autoplay) { box.addEventListener("mouseenter", () => v.play().catch(() => {})); box.addEventListener("mouseleave", () => v.pause()); }
      v.addEventListener("error", () => { v.remove(); box.innerHTML = svg((KIND[it.kind] || KIND.job).icon); });
      box.append(v);
      return box;
    }
    if (it.thumb) {
      const img = mk("img"); img.alt = ""; img.src = it.thumb; img.loading = "lazy"; img.decoding = "async";
      img.addEventListener("error", () => { img.remove(); box.innerHTML = svg(KIND[it.kind].icon); });
      box.append(img);
    } else box.innerHTML = svg((KIND[it.kind] || KIND.job).icon);
    return box;
  }

  function card(it) {
    const k = KIND[it.kind] || KIND.job;
    const c = mk("div", "home-card"); c.setAttribute("role", "listitem"); c.tabIndex = 0;
    c.dataset.key = keyOf(it); c.dataset.kind = it.kind;
    c.classList.toggle("on", keyOf(it) === S.pick);
    c.setAttribute("aria-label", k.label + ": " + it.name + (it.updated ? ", " + ago(it.updated) : ""));
    const meta = mk("div", "home-card-meta");
    const kindIco = mk("span", "home-card-kind"); kindIco.innerHTML = svg(k.icon);
    meta.append(kindIco, mk("span", "home-card-when", ago(it.updated)));
    if (it.status) meta.append(mk("span", "pill home-pill " + it.status, it.status));
    const go = iconBtn("home-card-open", ICON.open, "Open " + it.name, k.label + " - " + whatOpens[it.kind] + ".", (e) => { e.stopPropagation(); open(it); });
    const tools = mk("div", "home-card-tools");
    const path = ratePath(it);
    if (path) {   // thumbs + delete on the card itself (engine/image_feedback.py through /image/rate, /image/delete)
      const up = iconBtn("home-card-up", ICON.up, "Thumbs up", "I like this one - LOKI makes more like it.", (e) => { e.stopPropagation(); rateCard(c, path, 1); });
      const down = iconBtn("home-card-down", ICON.down, "Thumbs down", "I don't like this one - opens it and asks why.", (e) => { e.stopPropagation(); look(it, { rate: -1 }); });
      const del = iconBtn("home-card-del", ICON.trash, "Delete", "Really don't like it: remove it (click twice). It goes to the trash folder; LOKI learns from it.", (e) => { e.stopPropagation(); deleteCard(c, it, path, del); });
      tools.append(up, down, del);
    }
    tools.append(go);
    c.append(thumbOf(it, "home-card-thumb"), mk("div", "home-card-name", it.name), meta, tools);
    c.dataset.tipName = it.name; c.dataset.tipWhat = k.label + (it.detail ? " · " + it.detail : "") + (it.updated ? " · " + ago(it.updated) : "") + " - click to see it big, double-click " + whatOpens[it.kind] + ".";
    let t = 0;   // one click: see it big right here; a double click: open it where it lives (Forge, Files ...)
    c.addEventListener("click", () => { clearTimeout(t); t = setTimeout(() => look(it), 230); });
    c.addEventListener("dblclick", () => { clearTimeout(t); open(it); });
    return c;
  }
  /** The workspace path thumbs / delete work on (pictures LOKI made, Forge models), or "". */
  function ratePath(it) {
    if (it.kind === "made") return it.path_or_id;
    if (it.kind === "forge" && /^models\//.test(it.path_or_id || "")) return it.path_or_id;
    return "";
  }
  async function rateCard(c, path, n) {
    const r = await call("/image/rate", { path, rating: n }).catch(() => null);
    if (r && r.ok) { c.classList.toggle("liked", r.rating > 0); c.classList.toggle("disliked", r.rating < 0); }
  }
  async function deleteCard(c, it, path, del) {
    if (!del.dataset.armed) {   // two clicks, no pop-up dialog
      del.dataset.armed = "1"; del.classList.add("armed"); del.dataset.tipName = "Click again to delete";
      setTimeout(() => { delete del.dataset.armed; del.classList.remove("armed"); del.dataset.tipName = "Delete"; }, 3000);
      return;
    }
    const r = await call("/image/delete", { path }).catch(() => null);
    if (r && r.ok) {             // gone at once, in place: no redraw, no jump
      S.items = S.items.filter((x) => keyOf(x) !== keyOf(it));
      const next = c.nextElementSibling; c.remove(); if (next && next.focus) next.focus();
    }
  }
  /** Everything the viewer can show (pictures + 3D models), in the grid's order. */
  function viewables() {
    return visible().filter((x) => (x.thumb && !x.video) || (x.kind === "forge" && x.open && x.open.model))
      .map((x) => ({ key: keyOf(x), src: x.thumb || "", name: x.name, path: ratePath(x),
                     model: x.kind === "forge" && x.open ? x.open.model : "" }));
  }
  /** See it big, right where you are (image_viewer.js). Videos and other kinds open where they live. */
  function look(it, opts) {
    if (!it) return;
    const list = viewables(), at = list.findIndex((p) => p.key === keyOf(it));
    if (at < 0 || !window.LokiViewer) { open(it); return; }
    window.LokiViewer.open(list, at, opts || {});
  }
  function applySize() {
    if (root) root.style.setProperty("--home-card-min", SIZES[S.size] + "px");
    const b = root && root.querySelector(".home-size"); if (b) b.dataset.size = S.size;
  }
  function dayOf(t) {
    if (!t) return "Earlier";
    const d = new Date(t * 1000), now = new Date();
    const start = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const days = Math.round((start(now) - start(d)) / 86400000);
    if (days <= 0) return "Today";
    if (days === 1) return "Yesterday";
    if (days < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
    return d.toLocaleDateString(undefined, { day: "numeric", month: "long", year: days > 300 ? "numeric" : undefined });
  }

  function heroItem() {
    const list = visible();
    // the picked card only while it is in this tab (a picked picture stayed big under every tab, so they looked dead);
    // under All, "working now" may still put a running job in the preview
    const picked = list.find((it) => keyOf(it) === S.pick) || (S.filter === "all" && S.items.find((it) => it.kind === "job" && keyOf(it) === S.pick));
    return picked || list[0] || null;
  }

  function renderHero() {
    if (S.preview) { S.preview.dispose(); S.preview = null; }   // one live 3D preview at a time
    hero.replaceChildren();
    const it = heroItem();
    if (!it) { hero.hidden = true; return; }
    hero.hidden = false;
    const k = KIND[it.kind] || KIND.job;
    const side = mk("div", "home-hero-side");
    const kind = mk("div", "home-hero-kind"); kind.innerHTML = svg(k.icon); kind.append(mk("span", "", k.label));
    side.append(kind, mk("h3", "home-hero-name", it.name));
    const facts = mk("p", "home-hero-facts", [ago(it.updated), it.detail, it.status].filter(Boolean).join(" · "));
    side.append(facts);
    let pic = null;
    if (it.kind === "job") {   // the newest picture the job made, not its log
      pic = mk("div", "home-hero-pic kind-job"); pic.innerHTML = svg(KIND.job.icon);
      jobPicture(it.path_or_id).then((src) => {
        if (!src || !pic.isConnected) return;
        const img = mk("img"); img.alt = it.name; img.src = src; pic.replaceChildren(img);
      });
    }
    const go = mk("button", "send small home-hero-open", it.kind === "job" ? "Open in Lab > Agents" : it.kind === "made" ? "Show in Files" : "Open in " + k.label);
    go.type = "button"; go.addEventListener("click", () => open(it));
    side.append(go);
    pic = pic || thumbOf(it, "home-hero-pic");
    if (it.kind === "forge" && window.LokiModelPreview && it.open && it.open.model) {   // a model: the model itself, live
      pic.classList.add("home-hero-3d");
      pic.title = "Drag to turn it, scroll to zoom - double-click opens it in Forge";
      S.preview = window.LokiModelPreview.mount(pic, it.open.model, { onOpen: () => open(it) });
    }
    const pics = viewables().filter((p) => !p.model), at = pics.findIndex((p) => p.key === keyOf(it));
    if (at >= 0) {   // a picture: click it to see it big and step through everything (image_viewer.js)
      pic.classList.add("home-hero-viewable");
      pic.title = "Click to see it big - then ‹ › (or ← →) through all your pictures, select an area to focus, crop or edit only it";
      pic.addEventListener("click", () => { if (window.LokiViewer) window.LokiViewer.open(pics, at); });
      const stepTo = (d) => { const j = at + d; if (pics[j]) { S.pick = pics[j].key; render(); } };
      const nav = (d, cls, name, icon) => {
        const b = iconBtn("home-hero-nav " + cls, icon, name, d < 0 ? "The picture before this one." : "The next picture.", (e) => { e.stopPropagation(); stepTo(d); });
        b.disabled = !pics[at + d]; return b;
      };
      pic.append(nav(-1, "prev", "Before", '<path d="M15 5l-7 7 7 7"/>'), nav(1, "next", "Next", '<path d="M9 5l7 7-7 7"/>'));
      if (pics[at].path) {   // thumbs up / down right next to the picture (engine/image_feedback.py)
        const row = mk("div", "home-hero-rate"), say = mk("span", "home-hero-rated");
        const up = iconBtn("home-rate-up", '<path d="M7 11v9H4v-9z"/><path d="M7 11l4-8c1.5 0 2.5 1 2.5 2.5V9h5a2 2 0 012 2.3l-1.2 7A2 2 0 0117.3 20H7"/>',
          "Thumbs up", "I like this one - LOKI makes more like it.", async () => {
            const r = await call("/image/rate", { path: pics[at].path, rating: 1 }).catch(() => null);
            say.textContent = r && r.ok ? "Liked" : "Not saved"; up.setAttribute("aria-pressed", String(!!(r && r.ok)));
          });
        const down = iconBtn("home-rate-down", '<path d="M17 13V4h3v9z"/><path d="M17 13l-4 8c-1.5 0-2.5-1-2.5-2.5V15h-5a2 2 0 01-2-2.3l1.2-7A2 2 0 016.7 4H17"/>',
          "Thumbs down", "I don't like this one - say why in the viewer; LOKI avoids it next time.", () => {
            if (window.LokiViewer) window.LokiViewer.open(pics, at, { rate: -1 });
          });
        let armed = 0;
        const del = iconBtn("home-rate-del", '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
          "Delete", "I really don't like it - remove it (click twice). It goes to the trash folder and LOKI learns from it.", async () => {
            if (!armed) { del.classList.add("armed"); say.textContent = "Click the bin again to delete"; armed = setTimeout(() => { armed = 0; del.classList.remove("armed"); say.textContent = ""; }, 3000); return; }
            clearTimeout(armed); armed = 0; del.classList.remove("armed");
            const r = await call("/image/delete", { path: pics[at].path }).catch(() => null);
            if (r && r.ok) { S.pick = (pics[at + 1] || pics[at - 1] || {}).key || null; if (window.LokiHome && LokiHome.refresh) LokiHome.refresh(); }
            else say.textContent = "Not deleted: " + ((r && r.error) || "no answer");
          });
        row.append(up, down, del, say); side.insertBefore(row, go);
        call("/image/info?path=" + encodeURIComponent(pics[at].path)).then((r) => {
          if (!r || !r.ok) return;
          up.setAttribute("aria-pressed", String(r.rating > 0)); down.setAttribute("aria-pressed", String(r.rating < 0));
          if (r.rating) say.textContent = r.rating > 0 ? "Liked" : "Disliked" + (r.reasons && r.reasons.length ? ": " + r.reasons.join(", ") : "");
        }).catch(() => {});
      }
    }
    hero.append(pic, side);
  }
  async function jobDetail(id) {
    const r = await call("/jobs").catch(() => null);
    return ((r && r.jobs) || []).find((j) => j.id === id) || null;
  }
  async function jobPicture(id) {
    const j = await jobDetail(id);
    const paths = (j && window.LokiChatMedia) ? window.LokiChatMedia.pathsIn(j.output || "").filter((p) => !/\.pdf$/i.test(p)) : [];
    for (const p of paths.reverse()) {
      const m = await call("/chat/media?path=" + encodeURIComponent(p)).catch(() => null);
      if (m && m.ok && m.data_url) return m.data_url;
    }
    return "";
  }

  function renderEmpty() {
    empty.replaceChildren();
    if (!S.loaded) { empty.append(mk("p", "mode-note", "Looking for your renders and projects...")); return; }
    if (visible().length) return;
    if (S.filter !== "all") {   // one kind picked and none of it: how to make one
      const k = S.filter, row = mk("p", "home-empty-row"), ico = mk("span", "home-empty-ico"); ico.innerHTML = svg(KIND[k].icon);
      row.append(ico, mk("span", "", S.errors[k] ? KIND[k].label + ": could not look (" + S.errors[k] + ")" : KIND[k].empty));
      empty.append(row);
      return;
    }
    // nothing at all yet: one calm line and the three places to start
    const box = mk("div", "home-start");
    box.append(mk("p", "home-start-line", "Nothing here yet. Make something and it shows up here."));
    const acts = mk("div", "home-start-acts");
    for (const [mode, k, label] of [["forge", "forge", "Model in Forge"], ["render", "render", "Render a scene"], ["godot", "godot", "Open a game"]]) {
      const b = mk("button", "quiet small home-start-btn"); b.type = "button"; b.dataset.kind = k;
      b.innerHTML = svg(KIND[k].icon); b.append(mk("span", "", label));
      b.addEventListener("click", () => { if (window.LokiModeBar) window.LokiModeBar.go(mode); });
      acts.append(b);
    }
    box.append(acts);
    empty.append(box);
  }

  function render() {
    if (!root) return;
    for (const b of root.querySelectorAll(".home-kind")) b.setAttribute("aria-pressed", String(b.dataset.kind === S.filter));
    const list = visible(), shown = list.slice(0, S.shown), nodes = [];
    let day = "";
    for (const it of shown) {   // grouped by day, newest first (Google Photos / Lightroom style)
      const d = dayOf(it.updated);
      if (d !== day) { day = d; nodes.push(mk("h3", "home-day", d)); }
      nodes.push(card(it));
    }
    const top = root.scrollTop;   // a redraw (new things arriving) never moves the page
    grid.replaceChildren(...nodes);
    root.scrollTop = top;
    more.hidden = list.length <= shown.length;
    more.textContent = "Show more (" + (list.length - shown.length) + ")";
    more.title = "Show the next " + Math.min(PAGE, list.length - shown.length) + ".";
    const r = running();
    live.hidden = !r.length;
    live.replaceChildren(mk("span", "home-live-dot"), mk("span", "", r.length + " working"));
    live.classList.toggle("on", r.some((it) => keyOf(it) === S.pick));
    renderHero();
    renderEmpty();
  }

  // ---------------------------------------------------------------- data
  async function refresh() {
    if (S.loading || typeof state === "undefined" || !state.token) return;
    S.loading = true;
    try {
      const r = await call("/home/projects");
      if (r && r.ok) { S.items = r.items || []; S.errors = r.errors || {}; }
    } catch (_) { /* engine restarting: keep what is shown */ }
    S.loading = false; S.loaded = true;
    // nothing changed: keep the cards as they are (re-building them every 5-15 s made Home flicker and feel slow);
    // still redraw once a minute so "3 min ago" stays true
    const sig = S.items.map((it) => keyOf(it) + "|" + (it.updated || 0) + "|" + (it.status || "") + "|" + ((it.thumb || "").length)).join("\n")
      + "#" + Object.keys(S.errors).join(",");
    if (sig === S.sig && Date.now() - (S.drawn || 0) < 60000) return;
    S.sig = sig; S.drawn = Date.now();
    render();
  }

  // ---------------------------------------------------------------- opening a thing where it lives
  function open(it) {
    if (!it) return;
    const o = it.open || {};
    const bar = window.LokiModeBar;
    if (o.mode === "studio") return openStudio(o.session || "");
    if (o.mode === "job" || it.kind === "job") {   // agents live in Lab > Agents now, not under the Home chat
      if (bar && bar.modes().includes("render")) bar.go("render", { view: "agents", job: "" });
      if (typeof refreshJobs === "function") refreshJobs();
      return;
    }
    if (o.mode === "files" && typeof openFiles === "function") return openFiles(o.path || "");
    if (bar && bar.modes().includes(o.mode)) bar.go(o.mode, o);
  }

  // ---------------------------------------------------------------- Studio, inside Home
  function openStudio(session) {
    if (window.LokiModeBar && window.LokiModeBar.active() !== "loki") window.LokiModeBar.go("loki");
    const main = document.getElementById("main");
    if (!main) return;
    if (!studioPane) {
      studioPane = mk("section", "home-studio"); studioPane.id = "home-studio"; studioPane.setAttribute("aria-label", "LOKI Studio");
      const bar = mk("div", "home-studio-bar");
      const back = iconBtn("home-studio-back", ICON.back, "Back to Home", "Close Studio (Esc). Studio keeps working; open it again any time.", closeStudio);
      bar.append(back, mk("span", "home-studio-title", "Studio"),
        mk("span", "home-studio-sub", "build or change an app with an agent, review the diff, ship it"));
      studioBody = mk("div", "home-studio-body");
      studioPane.append(bar, studioBody);
      main.append(studioPane);
      if (window.LokiModeBar && typeof window.LokiModeBar.buildStudio === "function") {
        window.LokiModeBar.buildStudio(studioBody, session || "").then((f) => { studioFrame = f; });
      }
    } else if (session && studioFrame) {
      const base = studioFrame.src.replace(/&session=[^&]*/, "");
      studioFrame.src = "about:blank";
      setTimeout(() => { studioFrame.src = base + "&session=" + encodeURIComponent(session); }, 30);
    }
    studioPane.hidden = false;
    main.classList.add("studio-open");
    const back = studioPane.querySelector(".home-studio-back"); if (back) back.focus();
  }
  function closeStudio() {
    if (!studioPane) return;
    studioPane.hidden = true;
    const main = document.getElementById("main"); if (main) main.classList.remove("studio-open");
  }
  const studioOpen = () => !!(studioPane && !studioPane.hidden);

  // the view changed (app.js setView) or the hub was folded away (chat_view.js "hub-off"). With the split layout the
  // hub stays beside the chat in BOTH views - it is never hidden just because a chat is open (that hid the display).
  function sync() {
    const main = document.getElementById("main");
    if (!main || !root) return;
    const home = main.classList.contains("home");
    const split = !!document.getElementById("loki-split");
    const hidden = split ? main.classList.contains("hub-off") : !home;
    if (root.hidden !== hidden) root.hidden = hidden;
    const chatting = !split && home && main.classList.contains("summoned");
    if (root.classList.contains("chatting") !== chatting) root.classList.toggle("chatting", chatting);
    if (!main.classList.contains("has-hub")) main.classList.add("has-hub");
  }

  function onKey(e) {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.shiftKey && !e.altKey && (e.code === "KeyS" || (e.key || "").toLowerCase() === "s")) {
      if (document.querySelector('.sheet:not([hidden]) [role="dialog"]')) return;
      if (window.LokiModeBar && window.LokiModeBar.active() === "forge") return;   // Forge keeps its own keys
      e.preventDefault(); e.stopPropagation();
      if (studioOpen()) closeStudio(); else openStudio();
      return;
    }
    if (e.key === "Escape" && studioOpen() && !document.querySelector(".sheet:not([hidden])")) { e.preventDefault(); closeStudio(); }
  }

  async function start() {
    build();
    let rz = 0;   // one row of cards: re-count it when the window changes size
    window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (root && !root.hidden) render(); }, 120); });
    document.addEventListener("keydown", onKey, true);
    const main = document.getElementById("main");
    if (main) new MutationObserver(sync).observe(main, { attributes: true, attributeFilter: ["class"] });
    for (let i = 0; i < 400 && !window.LOKI_READY; i++) await new Promise((r) => setTimeout(r, 150));
    if (!window.LOKI_READY) return;
    refresh();
    machines();
    setInterval(() => { if (!document.hidden) machines(); }, 60000);   // once a minute is plenty
    let tick = 0;   // every 15 s; every 5 s while something runs, so the preview stays live
    S.timer = setInterval(() => {
      const m = document.getElementById("main");
      tick++;
      if (!running().length && tick % 3) return;
      if (!document.hidden && m && root && !root.hidden && (!window.LokiModeBar || window.LokiModeBar.active() === "loki")) refresh();
    }, 5000);
    window.addEventListener("focus", () => refresh());
  }

  document.addEventListener("DOMContentLoaded", start);
  return { refresh, open, look, openStudio, closeStudio, studioOpen, sync, items: () => S.items.slice(), dayOf, pcText };
})();
window.LokiHome = LokiHome;
