// Home tidied up (owner 2026-10-21 22:13: "clean up home as well those icons are redundant we dont need the same ones over
// and over and they should all be organized better and more intuitive; get rid of what i coloured green [the LOKI logo in
// the sidebar and the "Loki" title in the top bar]; everything should be adjustable").
//
// Several scripts add their own button to the sidebar (gallery.js, studio_link.js, qol.js ...). This layer runs after all
// of them and gives every button ONE place, without taking any feature away:
//   sidebar top    [ + New chat ] [ search ]                      - nothing above it (the logo is gone)
//   sidebar list   the chats
//   sidebar foot   Files · Apps · Settings · More                  - four different icons, nothing twice
//   More (menu)    What can LOKI do?, LOKI Studio, Check everything, the workspace folder, the version, Quit LOKI
//   gone           the sidebar's Forge button (the Forge tab in the title bar is the way in), the "Loki" title on Home,
//                  Home's own Chat and Studio buttons (New chat / typing, and Studio in More or Ctrl/Cmd+Shift+S)
//   Home filters   text chips - All, Renders, Models, Games, Sessions - instead of the same icons the title-bar tabs use
// Adjustable: drag the sidebar's edge (its width is a % of the window, double-click resets), Ctrl/Cmd+B folds it away;
// drag the line under Home's big preview to make it taller or shorter. Kept per viewer.
"use strict";

(() => {
  const STORE = "loki-ui-tidy";
  const load = () => { try { return Object.assign({ side: 19, folded: false, hero: 46 }, JSON.parse(localStorage.getItem(STORE) || "{}") || {}); } catch (_) { return { side: 19, folded: false, hero: 46 }; } };
  const save = (p) => { try { localStorage.setItem(STORE, JSON.stringify(p)); } catch (_) { /* private window */ } };
  const $ = (s) => document.querySelector(s);
  const ico = (name) => (typeof iconSvg === "function" ? iconSvg(name) : "");
  const tip = (b, name, what) => { b.dataset.tipName = name; b.dataset.tipWhat = what || ""; b.setAttribute("aria-label", name); b.removeAttribute("title"); };

  function sidebar() {
    const side = $(".sidebar");
    if (!side) return;
    side.classList.add("tidy");
    // the top row: New chat + search side by side
    const nc = $("#new-chat"), srch = $("#qol-search-btn");
    let top = $("#tidy-top");
    if (!top && nc) { top = document.createElement("div"); top.id = "tidy-top"; top.className = "tidy-top"; nc.before(top); }
    if (top && nc && nc.parentElement !== top) top.append(nc);
    if (top && srch && srch.parentElement !== top) top.append(srch);
    // the foot: Files, Apps, Settings, More
    const foot = $(".sidebar-foot .foot-row");
    if (!foot) return;
    let more = $("#tidy-more");
    if (!more) {
      more = document.createElement("button");
      more.type = "button"; more.id = "tidy-more"; more.className = "quiet icon-btn";
      more.innerHTML = ico("dots") || "⋯";
      tip(more, "More", "What can LOKI do?, LOKI Studio, Check everything, the workspace folder, the version, Quit");
      more.addEventListener("click", (e) => { e.stopPropagation(); menuToggle(); });
    }
    const apps = $("#open-apps");
    for (const b of [$("#open-files"), apps, $("#open-settings"), more]) if (b && b.parentElement !== foot) foot.append(b);
    if (apps) apps.classList.add("tidy-foot");
    // into the More menu
    let menu = $("#tidy-menu");
    if (!menu) {
      menu = document.createElement("div"); menu.id = "tidy-menu"; menu.className = "tidy-menu"; menu.hidden = true; menu.setAttribute("role", "menu");
      side.append(menu);
      document.addEventListener("pointerdown", (e) => { if (!menu.hidden && !menu.contains(e.target) && e.target !== more && !more.contains(e.target)) menu.hidden = true; }, true);
      document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) menu.hidden = true; });
    }
    for (const id of ["u-gallery-btn", "open-studio", "check-everything", "quit-loki"]) {
      const b = document.getElementById(id);
      if (!b || b.parentElement === menu) continue;
      b.classList.add("tidy-item");
      const label = b.dataset.tipName || b.getAttribute("aria-label") || b.textContent.trim();
      b.dataset.tidyLabel = label;
      if (id === "u-gallery-btn" && typeof iconSvg === "function") { b.dataset.icon = "bulb"; b.dataset.iconDone = "1"; b.innerHTML = iconSvg("bulb"); }
      b.addEventListener("click", () => { menu.hidden = true; });
      menu.append(b);
    }
    // an icon script may redraw a button's insides later: its words come back every pass
    for (const b of menu.querySelectorAll(".tidy-item")) if (!b.querySelector(".tidy-lbl")) { const l = document.createElement("span"); l.className = "tidy-lbl"; l.textContent = b.dataset.tidyLabel || ""; b.append(l); }
    const ws = $("#workspace"), ver = $("#version");
    let info = $("#tidy-info");
    if (!info) { info = document.createElement("div"); info.id = "tidy-info"; info.className = "tidy-info"; menu.prepend(info); }
    for (const n of [ws, ver]) if (n && n.parentElement !== info) info.append(n);
    // the Forge button: the title bar's Forge tab does this (kept in the page, hidden, for scripts that click it)
    const forgeBtn = $("#open-forge"); if (forgeBtn) forgeBtn.classList.add("tidy-hidden");
    $(".sidebar .brand")?.classList.add("tidy-hidden");
  }
  function menuToggle() {
    const m = $("#tidy-menu"), b = $("#tidy-more");
    if (!m || !b) return;
    m.hidden = !m.hidden;
    if (!m.hidden) {
      const r = b.getBoundingClientRect(), sr = ($(".sidebar") || b).getBoundingClientRect();
      m.style.left = Math.max(8, Math.round(sr.left + 8)) + "px";
      m.style.width = Math.max(200, Math.round(sr.width - 16)) + "px";
      m.style.bottom = Math.round(window.innerHeight - r.top + 8) + "px";
    }
  }

  // the top bar: no "Loki" title on Home (a chat still shows its own name)
  function topbar() {
    const t = $("#chat-title");
    if (!t) return;
    const plain = !t.textContent.trim() || /^loki$/i.test(t.textContent.trim());
    t.classList.toggle("tidy-hidden", plain);
  }

  // Home: words for the filters, and no second Chat / Studio button
  const KIND_WORDS = { all: "All", render: "Renders", forge: "Models", godot: "Games", studio: "Sessions" };
  function home() {
    for (const b of document.querySelectorAll(".home-kinds .home-kind")) {
      const k = b.dataset.kind;
      if (!KIND_WORDS[k] || b.dataset.tidy) continue;
      b.dataset.tidy = "1";
      b.classList.add("tidy-chip");
      const what = b.dataset.tipWhat || "";
      b.textContent = KIND_WORDS[k];
      tip(b, KIND_WORDS[k], what);
    }
    for (const id of ["home-chat", "home-studio-btn"]) for (const b of document.querySelectorAll("." + id + ", #" + id)) b.classList.add("tidy-hidden");
    heroHandle();
  }
  function heroHandle() {
    const pic = $(".home-hero-pic"), hero = $(".home-hero");
    if (!pic || !hero) return;
    const p = load();
    if (p.heroSet) document.documentElement.style.setProperty("--tidy-hero", p.hero + "vh");
    else {
      // not set by hand: the preview takes the room the cards leave, so Home fits the window without scrolling
      const hub = $(".home-hub");
      if (hub && hub.clientHeight) {
        const gap = parseFloat(getComputedStyle(hub).rowGap) || 12;
        let other = 0, n = 0;
        for (const k of hub.children) { if (k === hero || k.hidden || getComputedStyle(k).display === "none") continue; other += k.getBoundingClientRect().height; n++; }
        const pad = parseFloat(getComputedStyle(hub).paddingTop) + parseFloat(getComputedStyle(hub).paddingBottom);
        const room = hub.clientHeight - other - gap * n - pad - 4;
        const px = Math.max(140, Math.min(window.innerHeight * 0.62, room));
        document.documentElement.style.setProperty("--tidy-hero", Math.round(px) + "px");
      }
    }
    if ($("#tidy-hero-edge")) return;
    const h = document.createElement("div");
    h.id = "tidy-hero-edge"; h.className = "tidy-hero-edge"; h.setAttribute("role", "separator");
    tip(h, "Preview size", "Drag up or down to make the preview smaller or bigger; double-click resets.");
    hero.after(h);
    drag(h, (ev, start) => {
      const v = Math.max(18, Math.min(80, start.v + (ev.clientY - start.y) / window.innerHeight * 100));
      document.documentElement.style.setProperty("--tidy-hero", v.toFixed(1) + "vh"); h.dataset.v = v.toFixed(1);
    }, () => ({ y: 0, v: ($(".home-hero-pic") ? $(".home-hero-pic").getBoundingClientRect().height / window.innerHeight * 100 : load().hero) }),
    () => { const pp = load(); if (h.dataset.v) { pp.hero = +h.dataset.v; pp.heroSet = true; } save(pp); });
    h.addEventListener("dblclick", () => { const pp = load(); pp.heroSet = false; save(pp); heroHandle(); });
  }

  // ---- the sidebar's width and fold
  function sideWidth() {
    const p = load(), shell = $(".shell");
    if (!shell) return;
    document.documentElement.style.setProperty("--tidy-side", p.side + "vw");
    shell.classList.toggle("tidy-folded", !!p.folded);
    let edge = $("#tidy-side-edge");
    if (!edge) {
      edge = document.createElement("div"); edge.id = "tidy-side-edge"; edge.className = "tidy-side-edge"; edge.setAttribute("role", "separator");
      tip(edge, "Sidebar width", "Drag to make the sidebar wider or narrower; double-click resets; Ctrl/Cmd+B folds it away.");
      $(".sidebar")?.append(edge);
      drag(edge, (ev) => {
        const v = Math.max(12, Math.min(40, ev.clientX / window.innerWidth * 100));
        document.documentElement.style.setProperty("--tidy-side", v.toFixed(2) + "vw"); edge.dataset.v = v.toFixed(2);
      }, () => ({}), () => { const pp = load(); if (edge.dataset.v) pp.side = +edge.dataset.v; save(pp); });
      edge.addEventListener("dblclick", () => { const pp = load(); pp.side = 19; save(pp); sideWidth(); });
    }
  }
  function fold() { const p = load(); p.folded = !p.folded; save(p); sideWidth(); }
  window.addEventListener("resize", () => { clearTimeout(window.__tidyR); window.__tidyR = setTimeout(apply, 80); });
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "b") {
      const f = $("#forge"); if (f && !f.hidden) return;              // Forge has its own Ctrl+B (bevel)
      if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName)) return;
      e.preventDefault(); fold();
    }
  });

  function drag(h, move, begin, end) {
    h.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const start = Object.assign({ y: e.clientY }, begin());
      try { h.setPointerCapture(e.pointerId); } catch (_) { /* gone */ }
      document.body.classList.add("tidy-dragging");
      const mv = (ev) => move(ev, start);
      const up = () => { document.body.classList.remove("tidy-dragging"); h.removeEventListener("pointermove", mv); h.removeEventListener("pointerup", up); end(); };
      h.addEventListener("pointermove", mv); h.addEventListener("pointerup", up);
    });
  }

  function apply() { try { sidebar(); topbar(); home(); sideWidth(); } catch (_) { /* the next pass tries again */ } }
  document.addEventListener("DOMContentLoaded", () => {
    apply();
    setTimeout(apply, 300); setTimeout(apply, 1200);
    // other scripts keep adding / renaming things in the sidebar, the top bar and Home: follow them (only there -
    // watching the whole page made every Forge frame run this)
    let t = 0;
    const mo = new MutationObserver(() => { clearTimeout(t); t = setTimeout(apply, 80); });
    const watch = () => {
      for (const sel of [".sidebar", ".topbar", "#chat-title"]) { const n = $(sel); if (n && !n.dataset.tidyWatched) { n.dataset.tidyWatched = "1"; mo.observe(n, { childList: true, subtree: true, characterData: sel === "#chat-title" }); } }
      const hub = $("#home-hub"); if (hub && !hub.dataset.tidyWatched) { hub.dataset.tidyWatched = "1"; mo.observe(hub, { childList: true, subtree: false }); const k = hub.querySelector(".home-head"); if (k) mo.observe(k, { childList: true, subtree: true }); }
    };
    watch(); setTimeout(watch, 1500); setTimeout(watch, 4000);
  });
  window.LokiTidy = { apply, fold, menu: menuToggle };
})();
