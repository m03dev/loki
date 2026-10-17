// The Play page: runs one game in LOKI's own Pixel Engine. It lives in a sandboxed frame inside
// LOKI's window (no access to LOKI's token, files or engine): ?game=<name> loads the game's one
// script - a game that ships with LOKI from /ui/games/<name>/game.js, or one LOKI built in the
// workspace from /games/<name>/game.js (?src=workspace).
"use strict";
(function () {
  const q = new URLSearchParams(location.search);
  const name = (q.get("game") || "fox_berries").replace(/[^a-z0-9_-]/gi, "");
  const base = q.get("src") === "workspace" ? "/games/" : "/ui/games/";
  window.addEventListener("error", (ev) => showError(ev.message || "the game stopped"));
  function showError(text) {
    let box = document.querySelector(".pe-error");
    if (!box) { box = document.createElement("div"); box.className = "pe-error"; document.querySelector(".stage").append(box); }
    box.textContent = "This game hit a problem: " + text;
  }
  if (!window.PixelEngine) { showError("the engine did not load"); return; }
  const s = document.createElement("script");
  s.src = base + name + "/game.js";
  s.onerror = () => showError("no game called " + name);
  document.body.append(s);
  document.getElementById("game").focus();
})();
