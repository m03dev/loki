// LOKI's chat column beside the Home hub (owner 2026-10-25: "the chat is buggy, the display is sometimes hidden, the
// icons below the chat sometimes get cut off, there's no scroll bar when the chat gets too long so I can get back up
// ... reimagine the entire thing"). index.html puts the hub (home.js) and #chat-col side by side in #loki-split;
// home_layout.css lays them out. This file owns the small live parts:
//   - the "Latest" button: shows when you have scrolled up, brings you back to the newest message;
//   - following new output only while you are at the bottom (app.js chatScroll.pinned, kept true/false here);
//   - the hub panel toggle in the top bar (remembered), so the chat can have the whole window;
//   - the panes swap slots (owner 2026-10-25: "I should be able to move that chat window to the middle and vice versa,
//     kind of like the Godot preset windows, you swap slots"): the sidebar, the hub and the chat in three slots, by a
//     preset (the top bar's Layout button) or by dragging a pane's grip onto a slot; the chat column's inner edge
//     resizes it. Same code, same look on the Mac and on Windows; remembered in localStorage "loki-home-layout".
"use strict";

const LokiChatView = (() => {
  const KEY = "loki-hub-off";
  const NEAR = 80;   // px from the bottom that still counts as "at the latest message"
  let t = null, jump = null, toggle = null;

  const store = {
    get() { try { return localStorage.getItem(KEY) === "1"; } catch (_) { return false; } },
    set(v) { try { localStorage.setItem(KEY, v ? "1" : "0"); } catch (_) { /* private window: just this session */ } },
  };

  function atBottom() { return !t || t.scrollHeight - t.scrollTop - t.clientHeight < NEAR; }

  /** Show / hide "Latest" for where the chat is scrolled to (app.js scrollDown calls this too). */
  function update() {
    if (!t || !jump) return;
    const pinned = atBottom();
    if (typeof chatScroll !== "undefined") chatScroll.pinned = pinned;
    const show = !pinned && t.offsetParent !== null && t.childElementCount > 0;
    if (jump.hidden === show) jump.hidden = !show;
  }

  function toLatest(smooth) {
    if (!t) return;
    t.scrollTo({ top: t.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    if (typeof chatScroll !== "undefined") chatScroll.pinned = true;
    if (jump) jump.hidden = true;
  }

  function setHub(off) {
    const main = document.getElementById("main");
    if (!main) return;
    main.classList.toggle("hub-off", !!off);
    store.set(!!off);
    if (toggle) {
      toggle.setAttribute("aria-pressed", String(!off));
      toggle.title = off ? "Show the Home panel (your renders and projects) beside the chat" : "Hide the Home panel - the chat gets the whole window";
    }
    if (window.LokiHome && window.LokiHome.sync) window.LokiHome.sync();
    if (!off && window.LokiHome && window.LokiHome.refresh) window.LokiHome.refresh();
  }

  function start() {
    t = document.getElementById("transcript");
    jump = document.getElementById("jump-latest");
    if (!t) return;
    let raf = 0;
    t.addEventListener("scroll", () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; update(); }); }, { passive: true });
    if (jump) jump.addEventListener("click", () => toLatest(false));   // instant: a long smooth scroll felt slow
    // the chat's own content changes size (images load, a code block opens): keep following when pinned
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => {
        if (typeof chatScroll !== "undefined" && chatScroll.pinned && !chatScroll.hold) t.scrollTop = t.scrollHeight;
        update();
      });
      ro.observe(t);
    }
    new MutationObserver(() => update()).observe(t, { childList: true });

    const right = document.querySelector(".topbar .topbar-right");
    if (right && !document.getElementById("hub-toggle")) {
      toggle = document.createElement("button");
      toggle.type = "button"; toggle.id = "hub-toggle"; toggle.className = "hub-toggle";
      toggle.setAttribute("aria-label", "Home panel");
      toggle.innerHTML = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M14 4v16"/></svg>';
      toggle.addEventListener("click", () => setHub(!document.getElementById("main").classList.contains("hub-off")));
      right.prepend(toggle);
    }
    setHub(store.get());
    update();
  }

  // ---------------------------------------------------------------- the slots
  const LKEY = "loki-home-layout";
  const PANES = { sidebar: "Chats", hub: "Home", chat: "Chat" };
  const GRIP_NAME = { sidebar: "Move the chats list", hub: "Move Home", chat: "Move the chat" };   // whole phrases (i18n tables)
  const PRESETS = [
    [["sidebar", "hub", "chat"], "Home, then chat"],
    [["sidebar", "chat", "hub"], "Chat in the middle"],
    [["chat", "hub", "sidebar"], "Home in the middle"],
    [["hub", "chat", "sidebar"], "Chats on the right"],
  ];
  const valid = (o) => Array.isArray(o) && o.length === 3 && ["sidebar", "hub", "chat"].every((k) => o.includes(k)) && o[1] !== "sidebar";
  function lload() {
    let L = null;
    try { L = JSON.parse(localStorage.getItem(LKEY) || "null"); } catch (_) { L = null; }
    L = L && typeof L === "object" ? L : {};
    if (!valid(L.order)) L.order = PRESETS[0][0].slice();
    if (!(L.chatW >= 22 && L.chatW <= 72)) L.chatW = null;
    return L;
  }
  function lsave(L) { try { localStorage.setItem(LKEY, JSON.stringify(L)); } catch (_) { /* private window: this session only */ } }

  /** Put the panes where the layout says (sidebar end, hub / chat order, chat width). */
  function applyLayout(L) {
    L = L || lload();
    const split = document.getElementById("loki-split");
    document.documentElement.classList.toggle("side-right", L.order[2] === "sidebar");
    if (split) {
      split.classList.toggle("chat-first", L.order.indexOf("chat") < L.order.indexOf("hub"));
      if (L.chatW) split.style.setProperty("--chat-w", L.chatW + "%"); else split.style.removeProperty("--chat-w");
    }
    for (const b of document.querySelectorAll(".layout-opt[data-order]")) b.setAttribute("aria-checked", String(b.dataset.order === L.order.join(",")));
    return L;
  }
  function setLayout(order) {
    if (!valid(order)) return false;
    const L = lload(); L.order = order.slice(); lsave(L); applyLayout(L);
    return true;
  }
  /** Drop a pane on a slot (0 left, 1 middle, 2 right): it takes the slot; the sidebar never ends up in the middle. */
  function dropOn(pane, slot) {
    const L = lload(), o = L.order.filter((k) => k !== pane);
    if (pane === "sidebar" && slot === 1) return false;
    o.splice(slot, 0, pane);
    if (o[1] === "sidebar") { o.splice(1, 1); if (slot === 0) o.push("sidebar"); else o.unshift("sidebar"); }
    return setLayout(o);
  }

  const GRIP = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>';
  function grip(pane) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "pane-grip"; b.dataset.pane = pane; b.innerHTML = GRIP;
    b.setAttribute("aria-label", "Move the " + PANES[pane] + " pane");
    b.title = "Drag the " + PANES[pane] + " pane to another place (or pick a layout with the Layout button)";
    b.dataset.tipName = GRIP_NAME[pane]; b.dataset.tipWhat = "Drag onto a slot: left, middle or right.";
    b.addEventListener("pointerdown", (e) => startDrag(e, pane));
    return b;
  }
  function ensureGrips() {
    const head = document.querySelector("#home-hub .home-head"), col = document.getElementById("chat-col"), side = document.querySelector(".sidebar");
    if (head && !head.querySelector(".pane-grip")) head.prepend(grip("hub"));
    if (col && !col.querySelector(":scope > .pane-grip")) col.prepend(grip("chat"));
    if (side && !side.querySelector(":scope > .pane-grip")) side.append(grip("sidebar"));
  }

  function startDrag(e, pane) {
    if (e.button !== 0) return;
    e.preventDefault();
    const over = document.createElement("div"); over.className = "lk-slots"; over.setAttribute("aria-hidden", "true");
    const L = lload(), slots = [0, 1, 2].map((i) => {
      const d = document.createElement("div"); d.className = "lk-slot" + (pane === "sidebar" && i === 1 ? " off" : "");
      d.textContent = (["Left", "Middle", "Right"][i]) + (L.order[i] === pane ? " (here now)" : " - " + PANES[L.order[i]]);
      over.append(d); return d;
    });
    document.body.append(over); document.body.classList.add("lk-dragging");
    let hot = -1;
    const at = (x) => { for (let i = 0; i < 3; i++) { const r = slots[i].getBoundingClientRect(); if (x >= r.left - 5 && x <= r.right + 5) return i; } return -1; };
    const move = (ev) => { const i = at(ev.clientX); if (i === hot) return; hot = i; slots.forEach((d, k) => d.classList.toggle("hot", k === i && !d.classList.contains("off"))); };
    const end = (ev) => {
      window.removeEventListener("pointermove", move, true); window.removeEventListener("pointerup", end, true); window.removeEventListener("keydown", esc, true);
      const i = ev && ev.type === "pointerup" ? at(ev.clientX) : -1;   // measured before the slots go away
      over.remove(); document.body.classList.remove("lk-dragging");
      if (i >= 0) dropOn(pane, i);
    };
    const esc = (ev) => { if (ev.key === "Escape") { ev.preventDefault(); end(null); } };
    window.addEventListener("pointermove", move, true); window.addEventListener("pointerup", end, true); window.addEventListener("keydown", esc, true);
    move(e);
  }

  // the chat column's inner edge: its width, as a share of the split
  function ensureEdge() {
    const col = document.getElementById("chat-col"), split = document.getElementById("loki-split");
    if (!col || !split || col.querySelector(":scope > .chat-edge")) return;
    const edge = document.createElement("div"); edge.className = "chat-edge"; edge.setAttribute("role", "separator");
    edge.setAttribute("aria-label", "Chat width"); edge.title = "Drag to make the chat wider or narrower; double-click resets";
    col.append(edge);
    edge.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault(); edge.setPointerCapture(e.pointerId); document.body.classList.add("lk-dragging");
      const mv = (ev) => {
        const r = split.getBoundingClientRect(), first = split.classList.contains("chat-first");
        const w = first ? ev.clientX - r.left : r.right - ev.clientX;
        const pct = Math.max(22, Math.min(72, w / r.width * 100));
        split.style.setProperty("--chat-w", pct.toFixed(1) + "%"); edge.dataset.v = pct.toFixed(1);
      };
      const up = () => {
        edge.removeEventListener("pointermove", mv); edge.removeEventListener("pointerup", up); document.body.classList.remove("lk-dragging");
        if (edge.dataset.v) { const L = lload(); L.chatW = +edge.dataset.v; lsave(L); }
      };
      edge.addEventListener("pointermove", mv); edge.addEventListener("pointerup", up);
    });
    edge.addEventListener("dblclick", () => { const L = lload(); L.chatW = null; lsave(L); applyLayout(L); });
  }

  // the top bar's Layout button: the presets as little pictures
  function pic(order) {
    const p = document.createElement("span"); p.className = "layout-pic";
    p.style.gridTemplateColumns = order.map((k) => (k === "sidebar" ? "0.7fr" : k === "hub" ? "1.6fr" : "1fr")).join(" ");
    for (const k of order) { const i = document.createElement("i"); i.className = k === "sidebar" ? "s" : k === "chat" ? "c" : ""; p.append(i); }
    return p;
  }
  function ensureMenu() {
    const right = document.querySelector(".topbar .topbar-right");
    if (!right || document.getElementById("layout-btn")) return;
    const btn = document.createElement("button");
    btn.type = "button"; btn.id = "layout-btn"; btn.className = "layout-btn"; btn.setAttribute("aria-haspopup", "menu"); btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-label", "Layout"); btn.title = "Layout: where the chats, Home and the chat go";
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M8 4v16M15 4v16"/></svg>';
    const menu = document.createElement("div"); menu.id = "layout-menu"; menu.className = "layout-menu"; menu.setAttribute("role", "menu"); menu.hidden = true;
    const h = document.createElement("h4"); h.textContent = "Layout"; menu.append(h);
    for (const [order, name] of PRESETS) {
      const o = document.createElement("button"); o.type = "button"; o.className = "layout-opt"; o.setAttribute("role", "menuitemradio");
      o.dataset.order = order.join(","); o.append(pic(order), document.createTextNode(name));
      o.addEventListener("click", () => { setLayout(order); close(); });
      menu.append(o);
    }
    const only = document.createElement("button"); only.type = "button"; only.className = "layout-opt layout-wide"; only.setAttribute("role", "menuitem");
    only.textContent = "Chat only (hide Home)";
    only.addEventListener("click", () => { setHub(!document.getElementById("main").classList.contains("hub-off")); close(); });
    const reset = document.createElement("button"); reset.type = "button"; reset.className = "layout-opt layout-wide"; reset.setAttribute("role", "menuitem");
    reset.textContent = "Reset the layout";
    reset.addEventListener("click", () => { lsave({}); applyLayout(); setHub(false); close(); });
    menu.append(only, reset);
    document.body.append(menu);
    function close() { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); }
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (!menu.hidden) return close();
      only.textContent = document.getElementById("main").classList.contains("hub-off") ? "Show Home beside the chat" : "Chat only (hide Home)";
      menu.hidden = false; btn.setAttribute("aria-expanded", "true");
      const r = btn.getBoundingClientRect(), w = menu.offsetWidth || 300;
      menu.style.top = Math.round(r.bottom + 6) + "px";
      menu.style.left = Math.round(Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w))) + "px";
      const cur = menu.querySelector('[aria-checked="true"]') || menu.querySelector(".layout-opt"); if (cur) cur.focus();
    });
    menu.addEventListener("click", (e) => e.stopPropagation());
    menu.addEventListener("keydown", (e) => {
      const items = [...menu.querySelectorAll(".layout-opt")], i = items.indexOf(document.activeElement);
      if (e.key === "Escape") { e.preventDefault(); close(); btn.focus(); }
      else if (e.key === "ArrowDown" || e.key === "ArrowRight") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
    });
    document.addEventListener("click", close);
    right.prepend(btn);
    applyLayout();
  }

  function startLayout() {
    applyLayout();
    ensureMenu(); ensureEdge(); ensureGrips();
    setTimeout(ensureGrips, 0); setTimeout(ensureGrips, 600);   // the hub (home.js) may build a moment later
  }

  document.addEventListener("DOMContentLoaded", startLayout);
  document.addEventListener("DOMContentLoaded", start);
  return { update, toLatest, setHub, atBottom, setLayout, dropOn, layout: () => lload().order.slice(), PRESETS };
})();
window.LokiChatView = LokiChatView;
