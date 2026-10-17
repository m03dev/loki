"use strict";
// Start the world like app.js does, then open the Settings > LOKI World view.
(async function () {
  const engine = new URLSearchParams(location.search).get("engine") || "babylon";
  World.engine = engine;
  World.hour = 14;
  if (engine === "babylon" && !(await loadBabylon())) World.engine = "classic";
  await fetchWorld();
  showWorldPanel();
  window.previewReady = true;
})();
