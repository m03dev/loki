// Settings > Creations: everything LOKI made - pictures, videos, sketches, sounds and games -
// newest first, big, with a box to ask for the next one. GET /creations lists them; the files
// come from /creations/<kind>/<file> (served only to this machine). "Make it" starts a
// background job, and the wall checks back until the new piece arrives.
"use strict";

let creationsTimer = 0, creationsSeen = 0;

function creationPrompt(kind, what) {
  if (kind === "video") return "Make a short video of: " + what + ". Save it in videos/ and say where it is.";
  if (kind === "game") return "Make a small game with LOKI's Pixel Engine (read game_engine_guide first): " + what +
    ". Save it as games/<short-name>/game.js so it shows in Play.";
  return "Make an image of " + what + ". Save it in images/ and say where it is.";
}

function creationTile(c, open) {
  const tile = el("button", "creation " + c.show);
  tile.type = "button";
  tile.title = c.title;
  const src = "/creations/" + c.path.split("/").map(encodeURIComponent).join("/");
  if (c.show === "image") {
    const img = document.createElement("img");
    img.loading = "lazy"; img.alt = c.title; img.src = src;
    tile.append(img);
  } else {
    tile.append(el("span", "creation-ico", c.show === "video" ? "▶" : c.show === "audio" ? "♪" : "◆"));
  }
  const when = new Date(c.t * 1000);
  tile.append(el("b", "", c.title), el("span", "", c.kind + " · " + when.toLocaleDateString() + " " +
    when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })));
  tile.addEventListener("click", () => open(c, src));
  return tile;
}

function openCreation(c, src) {
  const box = document.getElementById("creations-view");
  if (!box) return;
  box.replaceChildren();
  let media;
  if (c.show === "image") { media = document.createElement("img"); media.alt = c.title; }
  else if (c.show === "video") { media = document.createElement("video"); media.controls = true; media.loop = true; }
  else { media = document.createElement("audio"); media.controls = true; }
  media.src = src;
  const close = el("button", "quiet", "Close");
  close.type = "button";
  close.addEventListener("click", () => { box.hidden = true; box.replaceChildren(); });
  const again = el("button", "quiet", "Make more like this");
  again.type = "button";
  again.addEventListener("click", () => {
    const input = document.getElementById("creations-what");
    if (input) { input.value = "another take on \"" + c.title + "\", same style"; input.focus(); }
    box.hidden = true;
  });
  box.append(media, el("b", "", c.title), el("span", "note", c.path), el("div", "creation-actions"));
  box.lastChild.append(again, close);
  box.hidden = false;
}

async function loadCreations() {
  const box = document.getElementById("creations-panel");
  if (!box) return;
  clearTimeout(creationsTimer);
  const data = await api("/creations").catch(() => null);
  if (!data || !data.ok) { box.replaceChildren(el("p", "note", "Could not read the creations.")); return; }
  const items = data.items || [];
  if (!box.querySelector(".creations-make")) {
    box.replaceChildren();
    const make = el("form", "creations-make");
    const kind = document.createElement("select");
    kind.id = "creations-kind";
    for (const [v, t] of [["image", "Picture"], ["video", "Video"], ["game", "Game"]]) {
      const o = document.createElement("option"); o.value = v; o.textContent = t; kind.append(o);
    }
    const what = document.createElement("input");
    what.id = "creations-what";
    what.placeholder = (data.ideas && data.ideas[Math.floor(Math.random() * data.ideas.length)]) || "a red fox in studio light";
    const go = el("button", "", "Make it");
    go.type = "submit";
    const note = el("span", "note creations-note", "");
    make.append(kind, what, go, note);
    make.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = (what.value || what.placeholder).trim();
      if (!text) return;
      go.disabled = true;
      const r = await api("/jobs", { backend: "local", agent: "loki", prompt: creationPrompt(kind.value, text), isolate: true, timeout_s: 1800 })
        .catch((err) => ({ ok: false, error: String(err) }));
      go.disabled = false;
      note.textContent = r.ok ? "LOKI is making it - it appears here when done." : (r.error || "Could not start it.");
      if (r.ok) { what.value = ""; creationsTimer = setTimeout(loadCreations, 8000); }
    });
    const ideas = el("div", "creations-ideas");
    for (const idea of (data.ideas || []).slice(0, 5)) {
      const chip = el("button", "chip", idea.length > 46 ? idea.slice(0, 44) + "…" : idea);
      chip.type = "button"; chip.title = idea;
      chip.addEventListener("click", () => { what.value = idea; what.focus(); });
      ideas.append(chip);
    }
    const view = el("div", "creation-view");
    view.id = "creations-view"; view.hidden = true;
    box.append(make, ideas, view, el("div", "creations-wall"));
  }
  const wall = box.querySelector(".creations-wall");
  wall.replaceChildren();
  if (!items.length && !(data.games || []).length) wall.append(el("p", "note", "Nothing yet. Ask for a picture above - a fox is a good start."));
  for (const c of items) wall.append(creationTile(c, openCreation));
  for (const g of data.games || []) {
    const tile = el("button", "creation game");
    tile.type = "button";
    tile.append(el("span", "creation-ico", "◆"), el("b", "", g.title), el("span", "", g.src === "workspace" ? "game · made by LOKI" : "game"));
    tile.addEventListener("click", () => { if (typeof showTab === "function") showTab("play"); if (typeof loadPlay === "function") loadPlay(g.name); });
    wall.append(tile);
  }
  // still making something: look again in a while (stops once the panel is closed)
  const newest = items.length ? items[0].t : 0;
  const waiting = box.querySelector(".creations-note") && box.querySelector(".creations-note").textContent.startsWith("LOKI is making");
  if (waiting && newest > creationsSeen && creationsSeen) box.querySelector(".creations-note").textContent = "New: " + items[0].title;
  if (!creationsSeen || newest > creationsSeen) creationsSeen = newest;
  const panel = box.closest("[data-panel]");
  if (waiting && panel && !panel.hidden) creationsTimer = setTimeout(loadCreations, 8000);
}
