// LOKI World as the Godot MMO, inside LOKI's window (Settings > General > LOKI World look = godot).
// One frame shows the web build (/ui/world_godot/index.html, exported from game/loki-world): behind
// the home screen it is a quiet backdrop (mode=background), in Settings > LOKI World you play it
// (mode=play). One frame for both, laid over whichever box is showing - moving an iframe in the
// DOM would reload the game. The token goes in the frame's URL fragment, as LOKI's own page gets it.
// Not exported yet, or the browser cannot run it -> start() resolves false and world.js falls
// back to a note in the World tab (app/ui/world.js).
(function () {
  "use strict";
  let frame = null;
  let mode = "";
  let inPanel = false;
  let wantBackground = () => false;
  let raf = 0;

  function target() {
    if (inPanel) return document.querySelector('[data-panel="world"] .world-frame');
    return wantBackground() ? document.querySelector(".world-bg") : null;
  }

  function place() {
    raf = 0;
    if (!frame) return;
    const box = target();
    const r = box ? box.getBoundingClientRect() : null;
    // the character creator (character.js) opens over the World tab: the game steps aside while it is open, else its
    // frame (z-index 1000) covered the dialog (seen 2026-10-18)
    const creator = window.LokiCharacter && typeof window.LokiCharacter.isOpen === "function" && window.LokiCharacter.isOpen();
    const visible = !!r && r.width > 0 && r.height > 0 && !document.hidden && !creator;
    // styles set from script (allowed under style-src 'self'; no stylesheet edit needed):
    // behind the home screen it is a half-faded backdrop that never takes the mouse
    frame.style.display = visible ? "block" : "none";
    frame.style.opacity = inPanel ? "1" : "0.5";
    frame.style.pointerEvents = inPanel ? "auto" : "none";
    frame.style.zIndex = inPanel ? "1000" : "0";
    if (visible) {
      frame.style.left = r.left + "px";
      frame.style.top = r.top + "px";
      frame.style.width = r.width + "px";
      frame.style.height = r.height + "px";
    }
    const want = inPanel ? "play" : "background";
    if (want !== mode && frame.contentWindow) {
      mode = want;
      frame.contentWindow.postMessage({ lokiWorld: "mode", mode: want }, location.origin);
      if (inPanel) frame.focus();   // keys go to the game once, when you open the panel
    }
  }

  function schedule() { if (!raf) raf = requestAnimationFrame(place); }

  function start(token, backgroundWanted) {
    wantBackground = typeof backgroundWanted === "function" ? backgroundWanted : wantBackground;
    return new Promise((resolve) => {
      let settled = false;
      // the 12 s "nothing said at all" timer fires after a good start too: once the game said it is starting it
      // stays; only the game's own "failed"/"missing" removes it later (before 2026-10-18 the timer removed a
      // running LOKI World 12 s after every start, so the World tab fell back to nothing)
      let good = false;
      const done = (ok, fromGame) => {
        if (!settled) { settled = true; good = !!ok; resolve(!!ok); }
        if (!ok && (!good || fromGame)) stop();
      };
      frame = document.createElement("iframe");
      frame.className = "world-godot";
      frame.title = "LOKI World";
      frame.setAttribute("allow", "fullscreen");
      frame.style.position = "fixed";
      frame.style.border = "0";
      frame.style.display = "none";
      frame.src = "/ui/world_godot/index.html#token=" + encodeURIComponent(token || "") + "&mode=background";
      // LOKI's mode-bar shortcuts are Ctrl+1..5, but place() focuses the game once the panel opens, and a focused
      // frame swallows every key: while the game has focus, re-raise a Ctrl+<number> press on LOKI's own document so
      // the mode bar still switches (regression 2026-10-18: opening the World tab made Ctrl+1..5 do nothing).
      frame.addEventListener("load", () => {
        try {
          frame.contentWindow.addEventListener("keydown", (ev) => {
            if (!(ev.ctrlKey || ev.metaKey) || ev.altKey || ev.shiftKey) return;
            if (!(/^Digit[1-9]$/.test(ev.code || "") || /^[1-9]$/.test(ev.key || ""))) return;
            ev.preventDefault();
            window.parent.document.dispatchEvent(new KeyboardEvent("keydown",
              { key: ev.key, code: ev.code, ctrlKey: ev.ctrlKey, metaKey: ev.metaKey, bubbles: true, cancelable: true }));
          }, true);
        } catch (_) { /* not same-origin: the game keeps its keys */ }
      });
      window.addEventListener("message", (ev) => {
        if (ev.origin !== location.origin || !frame || ev.source !== frame.contentWindow) return;
        const msg = ev.data || {};
        if (msg.lokiWorldGodot === "ready") mode = "";   // the game listens now: tell it the mode again
        if (msg.lokiWorldGodot === "starting" || msg.lokiWorldGodot === "ready") { done(true); schedule(); }
        else if (msg.lokiWorldGodot === "missing" || msg.lokiWorldGodot === "failed") {
          console.warn("LOKI World (Godot): " + (msg.detail || msg.lokiWorldGodot) + " - the World tab shows how to build it");
          done(false, true);
        }
      });
      document.body.append(frame);
      setTimeout(() => done(false), 12000);   // nothing said at all: not there
      const watch = new MutationObserver(schedule);
      for (const id of ["main", "settings"]) {
        const node = document.getElementById(id);
        if (node) watch.observe(node, { attributes: true, attributeFilter: ["class", "hidden"] });
      }
      window.addEventListener("resize", schedule);
      document.addEventListener("visibilitychange", schedule);
      setInterval(schedule, 1000);   // panels that move without a class change (scrolling)
    });
  }

  function stop() {
    if (frame) frame.remove();
    frame = null;
  }

  window.WorldGodot = {
    start,
    panel(on) { inPanel = !!on; schedule(); },
    get active() { return !!frame; },
  };
})();
