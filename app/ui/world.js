// LOKI World is ONE thing: the Godot project game/loki-world (owner, 2026-10-18: "i said make it in godot - if it's
// ... in code, delete it, we're moving on"). The hand-drawn WebGL / Babylon.js / three.js islands, the JS MMO and the
// JS character creator are gone. This file only hosts the Godot game's web build (app/ui/world_godot/host.js) in the
// World tab and Settings > LOKI World, and lists the agents GET /world reports beside it. You change the world in the
// Godot editor (Godot tab > Open in Godot); "Rebuild the World tab" exports it here.
"use strict";

const World = {
  game: "godot", panelOpen: false, godotLive: false, data: null, fetching: false, timer: 0,
  reduced: window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
};

const WORLD_STATE_COLOR = { working: "#7fc4a6", blocked: "#e07a6b", done: "#d9c27f", idle: "#8fb3d9" };

function loadScript(src) {
  return new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = src; s.onload = () => resolve(true); s.onerror = () => resolve(false);
    document.head.append(s);
  });
}

// the Godot game's host: resolves true once the web build is starting (the first time the World opens)
let godotStarting = null;
async function loadGodotWorld() {
  if (World.godotLive) return true;
  if (!godotStarting) {
    godotStarting = (async () => {
      if (!window.WorldGodot && !(await loadScript("/ui/world_godot/host.js"))) return false;
      return !!window.WorldGodot && (await window.WorldGodot.start(state.token, () => false));
    })();
  }
  World.godotLive = await godotStarting;
  if (!World.godotLive) godotStarting = null;   // try again next time it opens
  return World.godotLive;
}

function worldNote(text) {
  const box = document.querySelector('[data-panel="world"] .world-frame');
  if (!box) return;
  box.querySelectorAll(".world-missing").forEach((n) => n.remove());
  if (!text) return;
  const note = el("div", "world-missing");
  note.append(el("p", "note", text));
  const go = el("button", "send small", "Open the Godot tab");
  go.type = "button";
  go.addEventListener("click", () => { if (window.LokiModeBar) window.LokiModeBar.go("godot"); });
  note.append(go);
  box.append(note);
}

function showWorldPanel() {
  World.panelOpen = true;
  fetchWorld();
  clearInterval(World.timer);
  World.timer = setInterval(() => { if (World.panelOpen && !document.hidden) fetchWorld(); }, 5000);
  loadGodotWorld().then((ok) => {
    if (!World.panelOpen) return;
    if (ok) { worldNote(""); window.WorldGodot.panel(true); }
    else worldNote("LOKI World's web build is not here yet. Open the Godot tab, then \"Rebuild the World tab\" - " +
                   "or \"Open in Godot\" to play and edit it in the Godot editor.");
  });
}

function hideWorldPanel() {
  World.panelOpen = false;
  clearInterval(World.timer);
  if (World.godotLive && window.WorldGodot) window.WorldGodot.panel(false);
}

function setWorldMode() { /* LOKI World lives in the World tab and the Godot editor - no background copy */ }

async function fetchWorld() {
  if (World.fetching || typeof state === "undefined" || !state.token) return;
  World.fetching = true;
  try {
    const data = await api("/world");
    if (data && data.ok) { World.data = data; renderLegend(); }
  } catch (_) { /* engine restarting */ }
  World.fetching = false;
}

function renderLegend() {
  const box = document.getElementById("world-legend");
  if (!box || !World.data) return;
  box.replaceChildren();
  for (const a of World.data.agents || []) {
    const row = el("div", "legend-row");
    row.dataset.agent = a.id;
    const dot = el("span", "agent-dot");
    dot.style.background = a.color || WORLD_STATE_COLOR[a.state] || "#8fb3d9";
    row.append(dot, el("b", "", a.name),
               el("span", "pill " + (["working", "blocked", "done"].includes(a.state) ? a.state : ""), a.state),
               el("span", "muted", (a.station || "") + (a.task ? " · " + a.task : "")));
    box.append(row);
  }
}
window.World = World;
