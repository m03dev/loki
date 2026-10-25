// LOKI's chat column beside the Home hub (owner 2026-10-25: "the chat is buggy, the display is sometimes hidden, the
// icons below the chat sometimes get cut off, there's no scroll bar when the chat gets too long so I can get back up
// ... reimagine the entire thing"). index.html puts the hub (home.js) and #chat-col side by side in #loki-split;
// home_layout.css lays them out. This file owns the small live parts:
//   - the "Latest" button: shows when you have scrolled up, brings you back to the newest message;
//   - following new output only while you are at the bottom (app.js chatScroll.pinned, kept true/false here);
//   - the hub panel toggle in the top bar (remembered), so the chat can have the whole window.
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

  document.addEventListener("DOMContentLoaded", start);
  return { update, toLatest, setHub, atBottom };
})();
window.LokiChatView = LokiChatView;
