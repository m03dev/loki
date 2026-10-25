// Settings > Add-ons > Tool Shelf: open-source game-dev tools LOKI installs when you say so (owner 2026-10-25: "add all
// the tools"). GET /tools/shelf, POST /tools/shelf/install {id} (a job: progress from /forge/status?id=), POST
// /tools/shelf/remove {id}. engine/toolshelf.py, recipes in engine/toolshelf/*.json. Install asks once, in the row.
// The agents use the same tools (toolshelf tool, loki-make shelf).
"use strict";

const LokiToolShelf = (() => {
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const AREA = { audio: "Sound & voice", "2d": "2D art & sprites", "3d": "3D models", animation: "Animation", video: "Video & captions", marketing: "Marketing & stores", godot: "Godot" };
  let box = null;

  function mount() {
    const anchor = document.getElementById("manifests");
    if (!anchor) return null;
    if (box && box.isConnected) return box;
    box = mk("div", "ts-box"); box.id = "toolshelf";
    anchor.before(box);
    return box;
  }
  async function load() {
    if (!mount() || typeof api !== "function") return;
    box.replaceChildren(mk("p", "note", "Loading the Tool Shelf..."));
    const d = await api("/tools/shelf").catch((e) => ({ ok: false, error: e.message }));
    paint(d);
  }
  function paint(d) {
    box.replaceChildren();
    const head = mk("div", "ts-head");
    head.append(mk("h4", "", "Tool Shelf"), mk("span", "note", "Game-dev tools, each in its own folder - installed only when you say so."));
    box.append(head);
    if (!d || !d.ok) { box.append(mk("p", "note bad", "Could not load it: " + ((d && d.error) || "no answer"))); return; }
    const groups = {};
    for (const t of d.tools) (groups[t.area] = groups[t.area] || []).push(t);
    for (const area of Object.keys(groups)) {
      const fold = document.createElement("details"); fold.className = "ts-area";
      const sum = mk("summary", "", AREA[area] || area);
      sum.append(mk("span", "note", " " + groups[area].filter((t) => t.installed).length + " of " + groups[area].length + " installed"));
      fold.append(sum);
      for (const t of groups[area]) fold.append(row(t));
      box.append(fold);
    }
  }
  function row(t) {
    const r = mk("div", "ts-row"); r.dataset.id = t.id;
    const info = mk("div", "ts-info");
    const title = mk("b", "", t.name);
    if (t.installed) title.append(mk("span", "lm-badge", "installed"));
    info.append(title, mk("span", "note", t.what));
    const meta = [t.license && "code " + t.license, t.weights && "weights " + (t.weights.license || t.weights), t.hardware, !t.here && "not for this computer"].filter(Boolean).join(" · ");
    info.append(mk("span", "note ts-meta", meta));
    const acts = mk("div", "lm-acts");
    if (t.kind === "manual") {
      const how = mk("span", "note", t.manual || "Install it by hand"); acts.append(how);
    } else if (t.installed) {
      const rm = mk("button", "quiet small", "Remove"); rm.type = "button";
      rm.addEventListener("click", () => confirmRow(r, "Remove " + t.name + " and everything it downloaded?", "Remove", async () => api("/tools/shelf/remove", { id: t.id })));
      acts.append(rm);
    } else if (t.here) {
      const inst = mk("button", "small", "Install"); inst.type = "button";
      inst.title = "Downloads it from " + (t.repo || "its project") + " into LOKI's tools folder";
      inst.addEventListener("click", () => confirmRow(r, "Install " + t.name + "? It downloads and runs its code (" + (t.repo || "") + ").", "Install", async () => {
        const j = await api("/tools/shelf/install", { id: t.id });
        return j && j.ok ? waitJob(j.id, r) : j;
      }));
      acts.append(inst);
    }
    r.append(info, acts);
    return r;
  }
  async function waitJob(id, r) {
    const q = r.querySelector(".lm-ask");
    for (let i = 0; i < 2400; i++) {
      const s = await api("/forge/status?id=" + encodeURIComponent(id)).catch(() => null);
      if (s && s.ok && !s.done && q) q.textContent = (s.stage || "installing") + "...";
      if (s && s.ok && s.done) return s.result || { ok: false };
      await new Promise((res) => setTimeout(res, 1500));
    }
    return { ok: false, error: "still installing - look again later" };
  }
  function confirmRow(r, text, verb, go) {
    const acts = r.querySelector(".lm-acts");
    const prev = [...acts.childNodes];
    const q = mk("span", "lm-ask", text);
    const yes = mk("button", "small", verb); yes.type = "button";
    const no = mk("button", "quiet small", "Cancel"); no.type = "button";
    no.addEventListener("click", () => acts.replaceChildren(...prev));
    yes.addEventListener("click", async () => {
      yes.disabled = no.disabled = true; q.textContent = verb === "Install" ? "Installing..." : "Removing...";
      const res = await go().catch((e) => ({ ok: false, error: e.message }));
      if (res && res.ok) { q.textContent = "Done."; setTimeout(load, 700); }
      else { q.textContent = "Not done: " + ((res && (res.error || res.check)) || "no answer"); q.classList.add("bad"); no.disabled = false; }
    });
    acts.replaceChildren(q, yes, no);
    no.focus();
  }
  document.addEventListener("DOMContentLoaded", () => {
    const section = document.querySelector('section[data-panel="capabilities"]');
    if (!section) return;
    new MutationObserver(() => { if (!section.hidden) load(); }).observe(section, { attributes: true, attributeFilter: ["hidden"] });
    if (!section.hidden) load();
  });
  return { load, paint };
})();
window.LokiToolShelf = LokiToolShelf;
