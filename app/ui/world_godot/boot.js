// Starts LOKI World's Godot web build on /ui/world_godot/index.html, without inline script (the
// page runs under script-src 'self' 'wasm-unsafe-eval'). The export's settings come from the
// <script type="application/json" id="godot-config"> data block the exporter fills in.
// Tells LOKI's window how it went: {lokiWorldGodot: "starting" | "ready" | "missing" | "failed"}.
(function () {
  "use strict";
  const status = document.getElementById("status");
  const tell = (what, detail) => {
    if (window.parent !== window) window.parent.postMessage({ lokiWorldGodot: what, detail: detail || "" }, location.origin);
  };
  const say = (text) => { if (status) status.textContent = text; };
  if (typeof Engine === "undefined") {
    say("LOKI World's Godot build is not exported yet (game/loki-world -> Export -> Web).");
    tell("missing", "index.js not found - export the web build into app/ui/world_godot/");
    return;
  }
  let config = {};
  try {
    config = JSON.parse(document.getElementById("godot-config").textContent || "{}");
  } catch (err) {
    tell("failed", "bad export config");
    return;
  }
  const missing = Engine.getMissingFeatures({ threads: false });
  if (missing.length) {
    say("This window cannot run LOKI World: " + missing.join(", "));
    tell("failed", "missing " + missing.join(", "));
    return;
  }
  config.canvas = document.getElementById("canvas");
  const engine = new Engine(config);
  tell("starting");
  engine.startGame({
    onProgress(current, total) {
      if (total > 0) say("Loading LOKI World... " + Math.round((100 * current) / total) + "%");
    },
  }).then(() => {
    if (status) status.remove();
    tell("ready");
  }, (err) => {
    say("LOKI World could not start: " + (err && err.message ? err.message : err));
    tell("failed", String(err && err.message ? err.message : err));
  });
})();
