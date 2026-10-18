// The mode bar across the top of LOKI's window, like Godot's 2D / 3D / Script / AssetLib bar (owner, 2026-10-17:
// "loki studio should not be another window but the same client, just another tab; utilize the top tab like godot
// engine to switch between modes"). Modes: LOKI (chat/home), Studio (LOKI Studio in this window), Godot (the Godot
// web editor + the native editor), World (LOKI World), Forge (3D making, forge.js). Ctrl/Cmd+1..5 switch.
// Each mode keeps its state: panes are built once and only hidden, never rebuilt.
// Uses app.js's api() and state.token; plain DOM, CSP script-src 'self'.
"use strict";

const LokiModeBar = (() => {
  const MODES = [
    { id: "loki", name: "LOKI", tip: "Chat with LOKI - home, conversations, settings.", icon: '<path d="M5 6.5h14v9H9l-4 3.5z"/>' },
    { id: "studio", name: "Studio", tip: "LOKI Studio: build or change LOKI (or your own app) with an agent, review the diff, ship it.", icon: '<path d="M8.5 7L3.5 12l5 5M15.5 7l5 5-5 5M13.5 4.5l-3 15"/>' },
    { id: "godot", name: "Godot", tip: "The Godot editor: the web editor inside LOKI, or the Godot app with the LOKI Studio plugin.", icon: '<path d="M4 9.5l2-3.5 3 1.5L12 4l3 3.5 3-1.5 2 3.5-1.5 8.5h-13z"/><circle cx="9" cy="13" r="1.4"/><circle cx="15" cy="13" r="1.4"/>' },
    { id: "world", name: "World", tip: "LOKI World: your agents and machines as a living island.", icon: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.6 2.6 14.4 0 17M12 3.5c-2.6 2.6-2.6 14.4 0 17"/>' },
    { id: "forge", name: "Forge", tip: "Forge: draw, add a picture or describe it - LOKI makes a 3D model you can sculpt and export.", icon: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>' },
  ];
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
  let active = "loki";
  const panes = {};
  const built = {};
  let worldHome = null;

  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const svg = (paths) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + "</svg>";
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.reject(new Error("not ready")));

  // The title strip: a 38 px band across the top of the window holding the tabs (owner: "in the window's title bar").
  // macOS (titlebar-mac): the page is drawn under a transparent title bar, so the strip starts after the traffic
  // lights. Windows / native: the strip sits flush under the system frame. Empty parts of the strip drag the window
  // (pywebview's .pywebview-drag-region); the tabs are buttons, never drag regions. Double-click = zoom (js_api).
  function strip() {
    const top = mk("header", "titlestrip pywebview-drag-region"); top.id = "titlestrip";
    const left = mk("div", "titlestrip-side pywebview-drag-region");
    const right = mk("div", "titlestrip-side pywebview-drag-region");
    top.append(left, bar(), right);
    top.addEventListener("dblclick", (e) => {
      if (e.target.closest("button")) return;
      const host = window.pywebview && window.pywebview.api;
      if (host && typeof host.toggle_maximize === "function") host.toggle_maximize();
    });
    return top;
  }

  function bar() {
    const nav = mk("nav", "modebar"); nav.id = "modebar"; nav.setAttribute("role", "tablist"); nav.setAttribute("aria-label", "Mode");
    MODES.forEach((m, i) => {
      const b = mk("button", "modebar-tab"); b.type = "button"; b.id = "mode-" + m.id; b.dataset.mode = m.id;
      b.setAttribute("role", "tab"); b.setAttribute("aria-selected", String(m.id === active));
      const key = (isMac ? "⌘" : "Ctrl+") + (i + 1);
      b.dataset.tipName = m.name + "  (" + key + ")"; b.dataset.tipWhat = m.tip; b.title = m.name + " (" + key + ") - " + m.tip;
      b.setAttribute("aria-keyshortcuts", (isMac ? "Meta+" : "Control+") + (i + 1));
      b.innerHTML = svg(m.icon); b.append(mk("span", "", m.name));
      b.addEventListener("click", () => go(m.id));
      nav.append(b);
    });
    return nav;
  }

  function pane(id) {
    if (panes[id]) return panes[id];
    const p = mk("section", "mode-pane"); p.dataset.modePane = id; p.hidden = true; p.setAttribute("aria-label", id);
    document.body.append(p);
    return (panes[id] = p);
  }

  // ---------------------------------------------------------------- Studio: Studio's own server, framed here
  async function buildStudio(p) {
    const say = mk("p", "mode-note", "Starting LOKI Studio..."); p.append(say);
    const frame = mk("iframe", "mode-frame"); frame.title = "LOKI Studio"; frame.hidden = true;
    frame.setAttribute("referrerpolicy", "no-referrer"); p.append(frame);
    for (let i = 0; i < 40; i++) {
      let r = null;
      try { r = await call("/studio/embed", {}); } catch (e) { r = { ok: false, error: e.message }; }
      if (r && r.ok && r.url) { frame.src = r.url; frame.hidden = false; say.remove(); return; }
      if (!r || !r.ok) { say.textContent = "LOKI Studio did not start: " + ((r && r.error) || "no answer") + (r && r.how ? " " + r.how : ""); built.studio = false; return; }
      say.textContent = (r.note || "LOKI Studio is starting...") + " (" + (i + 1) + ")";
      await new Promise((res) => setTimeout(res, 1500));
    }
    say.textContent = "LOKI Studio is taking long to start. Look at its log (harness_data/studio/studio.log), or open it by hand.";
    built.studio = false;
  }

  // ---------------------------------------------------------------- Godot: the web editor, and the Godot app
  async function buildGodot(p) {
    const head = mk("div", "mode-tools");
    const pick = mk("select"); pick.setAttribute("aria-label", "Godot project");
    const status = mk("span", "mode-note");
    const btn = (label, tip, fn) => { const b = mk("button", "quiet small", label); b.type = "button"; b.title = tip; b.addEventListener("click", fn); return b; };
    const install = btn("Install the web editor", "Downloads Godot's official web editor (MIT, about 40 MB) from godotengine.org's GitHub, checks its SHA-512, keeps it in LOKI's data folder.", async () => {
      install.disabled = true; await call("/godot-editor/install", {}); poll();
    });
    const zip = btn("Project to the web editor", "Downloads the project folder as a zip: import it in the web editor's Project Manager.", async () => {
      if (!pick.value) return;
      const res = await fetch("/godot-editor/project.zip?name=" + encodeURIComponent(pick.value), { headers: { Authorization: "Bearer " + state.token } });
      if (!res.ok) { status.textContent = "Could not pack the project (HTTP " + res.status + ")."; return; }
      const a = mk("a"); a.href = URL.createObjectURL(await res.blob()); a.download = pick.value + ".zip"; document.body.append(a); a.click(); a.remove();
      status.textContent = "Saved " + pick.value + ".zip - in the editor: Import > pick the zip.";
    });
    const back = btn("Bring back from Downloads", "After Project > Tools > Download Project Source in the web editor: copies that zip's files into the project folder.", async () => {
      if (!pick.value || !confirm("Copy the newest " + pick.value + "*.zip from Downloads into the project folder? Files with the same name are replaced.")) return;
      const r = await call("/godot-editor/import", { name: pick.value, confirm: true });
      status.textContent = r.ok ? r.note : (r.error || "failed");
    });
    const native = btn("Open in the Godot app", "Opens the project in the Godot editor installed on this computer, with the LOKI Studio plugin - for heavy work.", async () => {
      if (!pick.value) return;
      const r = await call("/godot-editor/native", { name: pick.value });
      status.textContent = r.ok ? r.note : (r.error || "failed");
    });
    const own = btn("Web editor in its own window", "Opens the web editor as its own page (it needs cross-origin isolation, which a framed page here does not get).", () => {
      window.open("/godot-editor/app/godot.editor.html", "_blank", "noopener");
    });
    head.append(pick, install, zip, back, native, own, status);
    const flow = mk("p", "mode-note small");
    const frame = mk("iframe", "mode-frame"); frame.title = "Godot web editor"; frame.hidden = true;
    p.append(head, flow, frame);

    async function poll() {
      let s;
      try { s = await call("/godot-editor/status"); } catch (e) { status.textContent = e.message; return; }
      if (!s || !s.ok) { status.textContent = (s && s.error) || "LOKI's engine does not answer."; return; }
      const keep = pick.value; pick.replaceChildren();
      for (const pr of s.projects || []) pick.append(new Option(pr.label, pr.name));
      if (!pick.options.length) pick.append(new Option("no Godot project in " + s.projects_dir, ""));
      if ([...pick.options].some((o) => o.value === keep)) pick.value = keep;
      flow.textContent = "Files: " + s.flow;
      native.disabled = !s.native; native.title = s.native ? native.title : "Godot is not installed on this computer (or set GODOT_BIN).";
      install.hidden = s.installed; zip.disabled = back.disabled = !s.installed;
      own.hidden = !s.installed;
      if (s.job && s.job.state === "downloading") { status.textContent = s.job.note; setTimeout(poll, 2000); return; }
      if (s.job && s.job.state === "failed") status.textContent = "Download failed: " + s.job.note;
      if (!s.installed) { install.disabled = false; frame.hidden = true; return; }
      // SharedArrayBuffer: the editor needs a cross-origin-isolated page; a frame is isolated only if LOKI's window is.
      if (window.crossOriginIsolated) {
        if (!frame.src) frame.src = s.page;
        frame.hidden = false;
        status.textContent = "Godot " + s.version + " web editor.";
      } else {
        frame.hidden = true;
        status.textContent = "This window cannot run the web editor inside it (no SharedArrayBuffer here). Use \"Web editor in its own window\" or \"Open in the Godot app\".";
      }
    }
    poll();
  }

  // ---------------------------------------------------------------- World: the same LOKI World panel as Settings > LOKI World
  function enterWorld(p) {
    const sec = document.querySelector('[data-panel="world"]');
    if (!sec) { if (!p.childElementCount) p.append(mk("p", "mode-note", "LOKI World is not in this window.")); return; }
    if (!worldHome) worldHome = { parent: sec.parentNode, next: sec.nextSibling };
    p.append(sec); sec.hidden = false;
    if (typeof showWorldPanel === "function") showWorldPanel();
  }
  function leaveWorld() {
    const sec = document.querySelector('[data-panel="world"]');
    if (typeof hideWorldPanel === "function") hideWorldPanel();
    if (sec && worldHome) { sec.hidden = true; worldHome.parent.insertBefore(sec, worldHome.next); }
  }

  // ---------------------------------------------------------------- Forge: forge.js's own sheet
  function enterForge(p) {
    if (typeof window.forgeOpen === "function" || typeof forgeOpen === "function") {
      p.replaceChildren();
      (window.forgeOpen || forgeOpen)();
      const s = document.getElementById("forge"); if (s) s.classList.add("in-mode");
    } else if (!p.childElementCount) p.append(mk("p", "mode-note", "Forge is coming."));
  }
  function leaveForge() {
    const s = document.getElementById("forge");
    if (s && !s.hidden) { if (typeof forgeClose === "function") forgeClose(); else s.hidden = true; }
  }

  function go(id) {
    if (!MODES.some((m) => m.id === id) || id === active) return;
    const was = active;
    if (was === "world") leaveWorld();
    if (was === "forge") leaveForge();
    if (panes[was]) panes[was].hidden = true;
    active = id;
    document.body.dataset.mode = id;
    for (const b of document.querySelectorAll(".modebar-tab")) b.setAttribute("aria-selected", String(b.dataset.mode === id));
    if (id === "loki") return;
    const p = pane(id); p.hidden = false;
    if (id === "world") return enterWorld(p);
    if (id === "forge") return enterForge(p);
    if (!built[id]) { built[id] = true; (id === "studio" ? buildStudio : buildGodot)(p); }
  }

  function onKey(e) {
    const mod = isMac ? e.metaKey : e.ctrlKey;
    if (!mod || e.altKey || e.shiftKey) return;
    const n = /^Digit([1-9])$/.exec(e.code || "") || /^([1-9])$/.exec(e.key || "");
    if (!n) return;
    const m = MODES[Number(n[1]) - 1];
    if (!m) return;
    e.preventDefault();
    go(m.id);
  }

  function init() {
    if (document.getElementById("modebar")) return;
    document.body.prepend(strip());
    document.body.dataset.mode = active;
    document.body.classList.add("has-modebar");
    document.addEventListener("keydown", onKey, true);
  }

  return { init, go, modes: () => MODES.map((m) => m.id), active: () => active };
})();
window.LokiModeBar = LokiModeBar;
document.addEventListener("DOMContentLoaded", LokiModeBar.init);
