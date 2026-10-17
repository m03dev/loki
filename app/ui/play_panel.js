// Settings > Play: the games made with LOKI's Pixel Engine (app/ui/engine/pixel_engine.js).
// GET /games/list lists the ones that ship with LOKI and the ones LOKI built in the workspace;
// the chosen game runs in a sandboxed frame (allow-scripts only: no access to LOKI's token,
// storage or engine), from /ui/play.html.
"use strict";

let playFrame = null;

function stopPlay() {
  if (playFrame) { playFrame.src = "about:blank"; }
}

async function loadPlay(pick) {
  const box = document.getElementById("play-panel");
  if (!box) return;
  const data = await api("/games/list").catch(() => null);
  box.replaceChildren();
  const games = (data && data.games) || [];
  if (!games.length) { box.append(el("p", "note", "No games yet. Ask LOKI to make one.")); return; }
  const list = el("div", "play-list");
  const stage = el("div", "play-stage");
  playFrame = document.createElement("iframe");
  playFrame.className = "play-frame";
  playFrame.setAttribute("sandbox", "allow-scripts");
  playFrame.setAttribute("title", "Game");
  const open = (g) => {
    list.querySelectorAll(".play-item").forEach((x) => x.classList.toggle("on", x.dataset.name === g.name));
    playFrame.src = "/ui/play.html?game=" + encodeURIComponent(g.name) + (g.src === "workspace" ? "&src=workspace" : "");
    playFrame.focus();
  };
  for (const g of games) {
    const b = el("button", "play-item");
    b.type = "button";
    b.dataset.name = g.name;
    b.append(el("b", "", g.title), el("span", "", g.src === "workspace" ? "made by LOKI" : "comes with LOKI"));
    if (g.about) b.title = g.about;
    b.addEventListener("click", () => open(g));
    list.append(b);
  }
  const full = el("button", "quiet", "Full window");
  full.type = "button";
  full.addEventListener("click", () => { if (stage.requestFullscreen) stage.requestFullscreen(); playFrame.focus(); });
  stage.append(playFrame, full);
  box.append(list, stage);
  open(games.find((g) => g.name === pick) || games[games.length - 1]);
}

// a game never keeps running behind a closed Settings sheet
document.addEventListener("DOMContentLoaded", () => {
  const sheet = document.getElementById("settings");
  if (sheet) new MutationObserver(() => { if (sheet.hidden) stopPlay(); }).observe(sheet, { attributes: true, attributeFilter: ["hidden"] });
});
