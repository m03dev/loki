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

// the Godot game's host: resolves true once the web build is starting (the home screen or the World tab)
let godotStarting = null;
function loadGodotWorld() {
  if (World.godotLive) return Promise.resolve(true);
  if (!godotStarting) {
    godotStarting = (async () => {
      if (!window.WorldGodot && !(await loadScript("/ui/world_godot/host.js"))) return false;
      return !!window.WorldGodot && (await window.WorldGodot.start(state.token, homeWorldWanted));
    })();
  }
  return godotStarting.then((ok) => {
    World.godotLive = ok;
    if (!ok) godotStarting = null;   // try again next time it opens
    return ok;
  });
}

// The home screen shows the LIVE LOKI World behind the word "Loki" (owner, 2026-10-18: "i want to see it live when i
// home like before" - before it was the WRONG project, the hand-drawn JS island, deleted). It is the same Godot game
// and the same frame host.js lays down: here it is the quiet backdrop and never takes the mouse, and opening the
// World tab just moves that one frame into the panel.
function homeWorldEnabled() {
  // LOKI's own window asked for it (place.js reads `worldbg=1`); the web build and the test harnesses did not.
  return document.documentElement.classList.contains("world-home-on");
}

function homeWorldWanted() {
  const main = document.getElementById("main");
  return !!(homeWorldEnabled() && main && main.classList.contains("home") && !World.reduced);
}

// Show or hide the home backdrop (the World tab, when open, shows the game in its own box instead - host.js picks).
function syncHomeWorld() {
  const box = document.getElementById("world-home");
  if (box) box.classList.toggle("on", homeWorldWanted());
}

// Start the world for the home screen. No web build yet -> the home stays plain; the World tab says how to make it.
function startHomeWorld() {
  if (!homeWorldEnabled() || typeof state === "undefined" || !state.token) return;
  loadGodotWorld().then((ok) => {
    if (!ok) return;
    if (window.WorldGodot) window.WorldGodot.panel(false);
    syncHomeWorld();
  });
}
window.startHomeWorld = startHomeWorld;
window.syncHomeWorld = syncHomeWorld;

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
