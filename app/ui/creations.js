// Settings > Creations: everything LOKI made - pictures, videos, sketches, music, voice and games -
// newest first, big, with a box to ask for the next one. GET /creations lists them; the files
// come from /creations/<kind>/<file> (served only to this machine). "Make it" starts a
// background job, and the wall checks back until the new piece arrives.
//
// Session 28: the Make box has a style picker (Fooocus' 25 styles, pixel art among them), "Enhance"
// (LOKI's model writes a richer prompt), the aspect ratio and x4 variations. Every tile shows its
// prompt on hover and has a star; the viewer adds "Make more like this" (same prompt and style,
// the next seeds), "Animate this" (image-to-video) and Delete (moves it to the trash folder).
// Music and voice play right on their tile.
"use strict";

let creationsTimer = 0, creationsSeen = 0, creationsFilter = "all", creationsData = null;

function creationPrompt(kind, what) {
  if (kind === "video") return "Make a short video of: " + what + ". Save it in videos/ and say where it is.";
  if (kind === "game") return "Make a small game with LOKI's Pixel Engine (read game_engine_guide first): " + what +
    ". Save it as games/<short-name>/game.js so it shows in Play.";
  return "Make an image of " + what + ". Save it in images/ and say where it is.";
}

function creationSrc(c) {
  return "/creations/" + c.path.split("/").map(encodeURIComponent).join("/");
}

function creationMetaLine(c) {
  const bits = [];
  if (c.style) bits.push(c.style);
  if (c.backend) bits.push(c.backend);
  if (c.seed) bits.push("seed " + c.seed);
  if (c.aspect && c.aspect !== "1:1") bits.push(c.aspect);
  if (c.daily) bits.push("daily");
  return bits.join(" · ");
}

async function likeCreation(c, star) {
  const r = await api("/creations/like", { path: c.path, liked: !c.liked }).catch(() => null);
  if (r && r.ok) {
    c.liked = r.liked;
    if (star) { star.classList.toggle("on", c.liked); star.textContent = c.liked ? "★" : "☆"; }
  }
}

function creationStar(c) {
  const star = el("button", "creation-star" + (c.liked ? " on" : ""), c.liked ? "★" : "☆");
  star.type = "button";
  star.title = c.liked ? "A favourite - click to unstar" : "Star it: the daily creation learns from your stars";
  star.setAttribute("aria-label", "favourite");
  star.addEventListener("click", (e) => { e.stopPropagation(); likeCreation(c, star); });
  return star;
}

function creationTile(c, open) {
  const tile = el("div", "creation " + c.show);
  tile.tabIndex = 0;
  tile.setAttribute("role", "button");
  tile.title = c.prompt || c.title;
  const src = creationSrc(c);
  const frame = el("div", "creation-frame");
  if (c.show === "image") {
    const img = document.createElement("img");
    img.alt = c.title; img.src = src;   // never lazy: WebKit (the Mac) skips lazy pictures in scrolling panels
    frame.append(img);
  } else if (c.show === "video") {
    const vid = document.createElement("video");
    vid.muted = true; vid.loop = true; vid.preload = "metadata"; vid.playsInline = true;
    vid.src = src + "#t=0.5";
    tile.addEventListener("mouseenter", () => vid.play().catch(() => {}));
    tile.addEventListener("mouseleave", () => vid.pause());
    frame.append(vid, el("span", "creation-badge", "▶"));
  } else {
    frame.append(el("span", "creation-ico", c.show === "audio" ? (c.kind === "voice" ? "☊" : "♪") : "◆"));
  }
  if (c.prompt) frame.append(el("span", "creation-prompt", c.prompt));   // shown on hover
  if (c.kind !== "games") frame.append(creationStar(c));
  tile.append(frame);
  if (c.show === "audio") {   // music and voice play right here
    const player = document.createElement("audio");
    player.controls = true; player.preload = "none"; player.src = src;
    player.addEventListener("click", (e) => e.stopPropagation());
    tile.append(player);
  }
  const when = new Date(c.t * 1000);
  tile.append(el("b", "", c.title), el("span", "", c.kind + " · " + when.toLocaleDateString() + " " +
    when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })));
  const go = () => open(c, src);
  tile.addEventListener("click", go);
  tile.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  return tile;
}

function creationsSay(text) {
  const note = document.querySelector(".creations-note");
  if (note) note.textContent = text;
}

function openCreation(c, src) {
  const box = document.getElementById("creations-view");
  if (!box) return;
  box.replaceChildren();
  let media;
  if (c.show === "image") { media = document.createElement("img"); media.alt = c.title; }
  else if (c.show === "video") { media = document.createElement("video"); media.controls = true; media.loop = true; media.autoplay = true; }
  else { media = document.createElement("audio"); media.controls = true; }
  media.src = src;
  const button = (label, cls, fn) => {
    const b = el("button", cls, label); b.type = "button"; b.addEventListener("click", fn); return b;
  };
  const close = button("Close", "quiet", () => { box.hidden = true; box.replaceChildren(); });
  const star = button(c.liked ? "★ Favourite" : "☆ Favourite", "quiet", async () => {
    await likeCreation(c, null);
    star.textContent = c.liked ? "★ Favourite" : "☆ Favourite";
    loadCreations();
  });
  const again = button("Make more like this", "", async () => {
    again.disabled = true;
    const r = await api("/creations/more", { path: c.path, count: 4 }).catch((err) => ({ ok: false, error: String(err) }));
    creationsSay(r.ok ? "Making 4 more like \"" + c.title + "\" - same prompt and style, new seeds." : (r.error || "Could not start it."));
    if (r.ok) { box.hidden = true; creationsTimer = setTimeout(loadCreations, 5000); }
    again.disabled = false;
  });
  const actions = el("div", "creation-actions");
  if (c.kind === "images" || c.kind === "sketches") actions.append(again);
  if (c.show === "image") {
    const video = (creationsData && creationsData.creative && creationsData.creative.video) || {};
    const animate = button("Animate this", "quiet", async () => {
      animate.disabled = true;
      const r = await api("/creations/animate", { path: c.path, seconds: 3 }).catch((err) => ({ ok: false, error: String(err) }));
      creationsSay(r.ok ? "Animating \"" + c.title + "\" - a 3 s video appears here when done." : (r.error || "Could not start it."));
      if (r.ok) { box.hidden = true; creationsTimer = setTimeout(loadCreations, 8000); }
      animate.disabled = false;
    });
    if (!video.ready) { animate.disabled = true; animate.title = video.why || "no video maker here yet"; }
    actions.append(animate);
  }
  if (c.kind !== "games") {
    actions.append(star, button("Delete", "quiet danger", async () => {
      if (!confirm("Move \"" + c.title + "\" to the trash folder? (Nothing is deleted for good.)")) return;
      const r = await api("/creations/delete", { path: c.path }).catch(() => null);
      creationsSay(r && r.ok ? "Moved to " + r.trash + "." : ((r && r.error) || "Could not move it."));
      box.hidden = true;
      loadCreations();
    }));
  }
  actions.append(close);
  box.append(media, el("b", "", c.title));
  if (c.prompt) box.append(el("p", "creation-full-prompt", c.prompt));
  const line = creationMetaLine(c);
  box.append(el("span", "note", (line ? line + " · " : "") + c.path), actions);
  box.hidden = false;
  box.scrollIntoView({ block: "nearest" });
}

function creationsBackendLine(info) {
  if (!info || info.error) return "";
  const img = info.image || {}, vid = info.video || {};
  const parts = [];
  parts.push(img.ready ? "Pictures: " + (img.label || img.backend) + " on this computer"
    : "Pictures: online (FLUX on NVIDIA / Hugging Face) - Add-ons > local-image makes them here, free and private");
  parts.push(vid.ready ? "Videos: " + (vid.backend === "wan2gp" ? "Wan2GP on this computer" : "Higgsfield")
    : "Videos: " + (vid.why || "none yet"));
  for (const [name, job] of Object.entries(info.install || {})) {
    if (!job || (job.done && job.ok)) continue;
    const pct = job.total ? " " + Math.round(100 * job.got / job.total) + "%" : "";
    parts.push(job.done ? "Installing " + name + " failed: " + (job.error || "?") : "Installing " + name + ": " + job.step + pct);
  }
  return parts.join(" · ");
}

function creationsMakeBox(data) {
  const make = el("form", "creations-make");
  const field = (cls) => { const s = document.createElement("select"); s.className = cls; return s; };
  const kind = field("creations-kind");
  kind.id = "creations-kind";
  kind.title = "What to make";
  for (const [v, t] of [["image", "Picture"], ["video", "Video"], ["game", "Game"]]) {
    const o = document.createElement("option"); o.value = v; o.textContent = t; kind.append(o);
  }
  const what = document.createElement("input");
  what.id = "creations-what";
  what.placeholder = (data.ideas && data.ideas[Math.floor(Math.random() * data.ideas.length)]) || "a red fox in studio light";
  const style = field("creations-style");
  style.id = "creations-style";
  style.title = "Style (Fooocus' presets)";
  const none = document.createElement("option"); none.value = ""; none.textContent = "No style"; style.append(none);
  const order = (data.styles || []).slice().sort((a, b) => (a === "pixel art" ? -1 : b === "pixel art" ? 1 : a.localeCompare(b)));
  for (const s of order) {
    if (s === "negative") continue;
    const o = document.createElement("option"); o.value = s; o.textContent = s.replace(/\b\w/g, (m) => m.toUpperCase()); style.append(o);
  }
  const aspect = field("creations-aspect");
  aspect.id = "creations-aspect";
  aspect.title = "Aspect ratio";
  for (const a of data.aspects || ["1:1"]) {
    const o = document.createElement("option"); o.value = a; o.textContent = a; aspect.append(o);
  }
  const toggle = (id, label, tip) => {
    const wrap = el("label", "creations-toggle");
    const box = document.createElement("input");
    box.type = "checkbox"; box.id = id;
    wrap.title = tip;
    wrap.append(box, document.createTextNode(" " + label));
    return [wrap, box];
  };
  const [enhanceWrap, enhance] = toggle("creations-enhance", "Enhance", "LOKI's model turns your idea into a richer prompt first");
  const [fourWrap, four] = toggle("creations-four", "×4", "Four variations (seeds next to each other)");
  try { enhance.checked = localStorage.getItem("loki.creations.enhance") === "1"; } catch (_) { /* private mode */ }
  enhance.addEventListener("change", () => { try { localStorage.setItem("loki.creations.enhance", enhance.checked ? "1" : "0"); } catch (_) { /* ignore */ } });
  const go = el("button", "", "Make it");
  go.type = "submit";
  const pictureOnly = [style, aspect, enhanceWrap, fourWrap];
  kind.addEventListener("change", () => { for (const n of pictureOnly) n.hidden = kind.value !== "image"; });
  const note = el("span", "note creations-note", "");
  const backend = el("div", "note creations-backend", creationsBackendLine(data.creative));
  make.append(kind, what, style, aspect, enhanceWrap, fourWrap, go);
  make.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = (what.value || what.placeholder).trim();
    if (!text) return;
    go.disabled = true;
    const video = (creationsData && creationsData.creative && creationsData.creative.video) || {};
    // a picture goes straight to the image maker, a video to the local video maker when there is one;
    // otherwise (and for a game) an agent does it as a background job
    let r;
    if (kind.value === "image") {
      r = await api("/creations/make", { kind: "image", prompt: text, style: style.value, aspect: aspect.value,
        enhance: enhance.checked, count: four.checked ? 4 : 1 }).catch((err) => ({ ok: false, error: String(err) }));
    } else if (kind.value === "video" && video.ready) {
      r = await api("/creations/make", { kind: "video", prompt: text, seconds: 3 }).catch((err) => ({ ok: false, error: String(err) }));
    } else {
      r = await api("/jobs", { backend: "local", agent: "loki", prompt: creationPrompt(kind.value, text), isolate: true, timeout_s: 1800 })
        .catch((err) => ({ ok: false, error: String(err) }));
    }
    go.disabled = false;
    note.textContent = r.ok ? "LOKI is making it - it appears here when done." : (r.error || "Could not start it.");
    if (r.ok) { what.value = ""; creationsTimer = setTimeout(loadCreations, 8000); }
  });
  return [make, note, backend];
}

function creationsFilters(box) {
  const bar = el("div", "creations-filter");
  for (const [v, t] of [["all", "All"], ["images", "Pictures"], ["videos", "Videos"], ["audio", "Music & voice"], ["liked", "★ Starred"]]) {
    const chip = el("button", "chip" + (creationsFilter === v ? " on" : ""), t);
    chip.type = "button";
    chip.addEventListener("click", () => {
      creationsFilter = v;
      for (const c of bar.children) c.classList.toggle("on", c === chip);
      renderCreationsWall(box);
    });
    bar.append(chip);
  }
  return bar;
}

function creationShown(c) {
  if (creationsFilter === "all") return true;
  if (creationsFilter === "liked") return !!c.liked;
  if (creationsFilter === "audio") return c.show === "audio";
  if (creationsFilter === "images") return c.show === "image";
  if (creationsFilter === "videos") return c.show === "video";
  return true;
}

function renderCreationsWall(box) {
  const data = creationsData || {};
  const items = data.items || [];
  const wall = box.querySelector(".creations-wall");
  wall.replaceChildren();
  const shown = items.filter(creationShown);
  if (!items.length && !(data.games || []).length) wall.append(el("p", "note", "Nothing yet. Ask for a picture above - a fox is a good start."));
  else if (!shown.length && creationsFilter !== "all") wall.append(el("p", "note", creationsFilter === "liked" ? "No stars yet - star the ones you love." : "None of these yet."));
  for (const c of shown) wall.append(creationTile(c, openCreation));
  if (creationsFilter === "all") {
    for (const g of data.games || []) {
      const tile = el("div", "creation game");
      tile.tabIndex = 0; tile.setAttribute("role", "button");
      const frame = el("div", "creation-frame");
      frame.append(el("span", "creation-ico", "◆"));
      tile.append(frame, el("b", "", g.title), el("span", "", g.src === "workspace" ? "game · made by LOKI" : "game"));
      tile.addEventListener("click", () => { if (typeof showTab === "function") showTab("play"); if (typeof loadPlay === "function") loadPlay(g.name); });
      wall.append(tile);
    }
  }
}

async function loadCreations() {
  const box = document.getElementById("creations-panel");
  if (!box) return;
  clearTimeout(creationsTimer);
  const data = await api("/creations").catch(() => null);
  if (!data || !data.ok) { box.replaceChildren(el("p", "note", "Could not read the creations.")); return; }
  creationsData = data;
  const items = data.items || [];
  if (!box.querySelector(".creations-make")) {
    box.replaceChildren();
    const [make, note, backend] = creationsMakeBox(data);
    const ideas = el("div", "creations-ideas");
    for (const idea of (data.ideas || []).slice(0, 5)) {
      const chip = el("button", "chip", idea.length > 46 ? idea.slice(0, 44) + "…" : idea);
      chip.type = "button"; chip.title = idea;
      chip.addEventListener("click", () => { const what = document.getElementById("creations-what"); what.value = idea; what.focus(); });
      ideas.append(chip);
    }
    const view = el("div", "creation-view");
    view.id = "creations-view"; view.hidden = true;
    box.append(make, note, backend, ideas, view, creationsFilters(box), el("div", "creations-wall"));
  } else {
    const backend = box.querySelector(".creations-backend");
    if (backend) backend.textContent = creationsBackendLine(data.creative);
  }
  renderCreationsWall(box);
  // pieces being made right now (and how the last ones went)
  const note = box.querySelector(".creations-note");
  const making = data.making || [];
  const busy = making.filter((m) => !m.end);
  const failed = making.filter((m) => m.end && !m.ok).pop();
  if (note && busy.length) {
    const n = busy.reduce((sum, m) => sum + (m.count || 1), 0);
    const what = busy.some((m) => m.kind === "video") ? "piece" : "picture";
    note.textContent = "Making " + n + " " + what + (n > 1 ? "s" : "") + ": " + busy[0].prompt.slice(0, 50) + "…";
  } else if (note && failed && note.textContent.startsWith("Making")) note.textContent = "That one failed: " + failed.result.replace(/^error:\s*/, "").slice(0, 160);
  // still making something: look again in a while (stops once the panel is closed)
  const newest = items.length ? items[0].t : 0;
  const installing = Object.values((data.creative && data.creative.install) || {}).some((j) => j && !j.done);
  const waiting = busy.length > 0 || installing || (note && note.textContent.startsWith("LOKI is making"));
  if (newest > creationsSeen && creationsSeen && note) note.textContent = "New: " + items[0].title;
  if (!creationsSeen || newest > creationsSeen) creationsSeen = newest;
  const panel = box.closest("[data-panel]");
  if (waiting && panel && !panel.hidden) creationsTimer = setTimeout(loadCreations, 8000);
}
