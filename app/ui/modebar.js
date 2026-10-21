// The mode bar across the top of LOKI's window, like Godot's 2D / 3D / Script / AssetLib bar (owner, 2026-10-17:
// "utilize the top tab like godot engine to switch between modes"). LOKI is a game engine, render studio and AI farm
// hive (owner, 2026-10-21), so the modes are: Home (the preview hub + chat, app/ui/home.js - LOKI Studio lives inside
// it), Forge (3D making, forge.js), Render (the Render Studio, when it is in this window) and Godot (the owner's game
// projects in the real Godot editor). The keys are Godot's own (owner 2026-10-21: "clean up the hot keys"): Option+1..4
// on a Mac, Ctrl+F1..F4 on Windows - they switch from anywhere, Forge too. Ctrl/Cmd+1..4 still switch outside Forge, but
// in Forge those are its own (Ctrl/Cmd+1 = Isolate Select), so Forge keeps them.
// Each mode keeps its state: panes are built once and only hidden, never rebuilt.
// Uses app.js's api() and state.token; plain DOM, CSP script-src 'self'.
"use strict";

const LokiModeBar = (() => {
  const MODES = [
    { id: "loki", name: "Home", tip: "Home: your latest renders and projects, the chat with LOKI, and Studio.", icon: '<path d="M4 11l8-6.5 8 6.5"/><path d="M6 9.5V19h12V9.5"/><path d="M10 19v-5h4v5"/>' },
    { id: "forge", name: "Forge", tip: "Forge: draw, add a picture or describe it - LOKI makes a 3D model you can sculpt and export.", icon: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>' },
    { id: "render", name: "Render", tip: "Render: path-traced and AI renders of your scenes, on this computer or the worker farm.", icon: '<circle cx="12" cy="12" r="3.2"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>' },
    { id: "godot", name: "Godot", tip: "Godot: open one of your game projects in the Godot app; LOKI's agents work in it live, plugins from the Asset Library.", icon: '<path d="M4 9.5l2-3.5 3 1.5L12 4l3 3.5 3-1.5 2 3.5-1.5 8.5h-13z"/><circle cx="9" cy="13" r="1.4"/><circle cx="15" cy="13" r="1.4"/>' },
  ];
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
  let active = "loki";
  const panes = {};
  const built = {};
  const hooks = {};      // per-mode {enter(pane), leave()} other scripts register (the Render Studio)
  let godotPick = null;  // the Godot tab's select(project), once it is built
  let wantProject = "";

  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const svg = (paths) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + "</svg>";
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.reject(new Error("not ready")));

  // The title strip: a 38 px band across the top of the window holding the tabs (owner: "in the window's title bar").
  // macOS (titlebar-mac): the page is drawn under a transparent title bar, so the strip starts after the traffic
  // lights. Windows (titlebar-win): the window is frameless and the strip is its title bar, with LOKI's own
  // minimise / maximise / close. LOKI_TITLEBAR=native: the strip sits under the system frame. Empty parts of the strip drag the window
  // (pywebview's .pywebview-drag-region); the tabs are buttons, never drag regions. Double-click = zoom (js_api).
  // pywebview's js_api: LOKI's CSP has no 'unsafe-eval', so pywebview's api.js cannot build pywebview.api.* with
  // new Function() (engine.out: "EvalError ... script-src 'self'") - call its bridge directly when needed.
  function host(name, ...args) {
    const pw = window.pywebview;
    if (pw && pw.api && typeof pw.api[name] === "function") { try { pw.api[name](...args); } catch (_) { /* no bridge */ } return; }
    if (pw && typeof pw._jsApiCallback === "function") {
      try { pw._jsApiCallback(name, args, String(Math.random()).slice(2)); } catch (_) { /* no bridge */ }
    }
  }
  const isWinStrip = () => document.documentElement.classList.contains("titlebar-win");

  function strip() {
    // only the two empty sides drag the window; the tabs' bar never does (clicking a tab made the window run away)
    const win = isWinStrip();
    const top = mk("header", "titlestrip"); top.id = "titlestrip";
    // macOS: pywebview's drag regions. Windows (frameless): a press on an empty side is handed to Windows' own
    // title-bar move (WindowApi.grab) - real dragging and Aero snap.
    const left = mk("div", "titlestrip-side" + (win ? "" : " pywebview-drag-region"));
    const right = mk("div", "titlestrip-side" + (win ? "" : " pywebview-drag-region"));
    const tabs = bar();
    tabs.addEventListener("mousedown", (e) => e.stopPropagation());   // a press on a tab is a click, never a drag
    if (win) {
      const grab = (e) => { if (e.button === 0 && e.detail < 2 && !e.target.closest("button")) host("grab", "move"); };
      left.addEventListener("mousedown", grab);
      right.addEventListener("mousedown", grab);
      const ctl = mk("div", "wincontrols");
      const wbtn = (cls, label, paths, fn) => {
        const b = mk("button", "winctl " + cls); b.type = "button"; b.title = label; b.setAttribute("aria-label", label);
        b.innerHTML = '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.1" aria-hidden="true">' + paths + "</svg>";
        b.addEventListener("mousedown", (e) => e.stopPropagation());
        b.addEventListener("click", fn);
        return b;
      };
      ctl.append(
        wbtn("min", "Minimise", '<path d="M1.5 6h9"/>', () => host("minimize")),
        wbtn("max", "Maximise", '<rect x="1.5" y="1.5" width="9" height="9"/>', () => host("toggle_maximize")),
        wbtn("close", "Close", '<path d="M1.5 1.5l9 9M10.5 1.5l-9 9"/>', () => host("close")));
      right.append(ctl);
      // the frameless window's edges: thin handles that hand the press to Windows' own resize
      for (const edge of ["n", "s", "e", "w", "ne", "nw", "se", "sw"]) {
        const h = mk("div", "winedge winedge-" + edge);
        h.addEventListener("mousedown", (e) => { if (e.button === 0) { e.preventDefault(); host("grab", edge); } });
        document.body.append(h);
      }
    }
    top.append(left, tabs, right);
    top.addEventListener("dblclick", (e) => {
      if (e.target.closest("button")) return;
      host("toggle_maximize");
    });
    return top;
  }

  function bar() {
    const nav = mk("nav", "modebar"); nav.id = "modebar"; nav.setAttribute("role", "tablist"); nav.setAttribute("aria-label", "Mode");
    MODES.forEach((m, i) => {
      const b = mk("button", "modebar-tab"); b.type = "button"; b.id = "mode-" + m.id; b.dataset.mode = m.id;
      b.setAttribute("role", "tab"); b.setAttribute("aria-selected", String(m.id === active));
      const key = isMac ? "⌥" + (i + 1) : "Ctrl+F" + (i + 1);
      b.dataset.tipName = m.name + "  (" + key + ")"; b.dataset.tipWhat = m.tip; b.title = m.name + " (" + key + ") - " + m.tip;
      b.setAttribute("aria-keyshortcuts", isMac ? "Alt+" + (i + 1) : "Control+F" + (i + 1));
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

  // ---------------------------------------------------------------- Studio: Studio's own server, framed in a box
  // LOKI Studio (build or change an app with an agent) lives inside Home since 2026-10-21 (owner: "combine studio
  // with home we dont need them both"): home.js opens a pane over the home screen and calls this to fill it.
  async function buildStudio(p, session) {
    const say = mk("p", "mode-note", "Starting LOKI Studio..."); p.append(say);
    const frame = mk("iframe", "mode-frame"); frame.title = "LOKI Studio"; frame.hidden = true;
    frame.setAttribute("referrerpolicy", "no-referrer"); p.append(frame);
    for (let i = 0; i < 40; i++) {
      let r = null;
      try { r = await call("/studio/embed", {}); } catch (e) { r = { ok: false, error: e.message }; }
      if (r && r.ok && r.url) {
        frame.src = r.url + (session ? "&session=" + encodeURIComponent(session) : "");
        frame.hidden = false; say.remove(); return frame;
      }
      if (!r || !r.ok) { say.textContent = "LOKI Studio did not start: " + ((r && r.error) || "no answer") + (r && r.how ? " " + r.how : ""); return null; }
      say.textContent = (r.note || "LOKI Studio is starting...") + " (" + (i + 1) + ")";
      await new Promise((res) => setTimeout(res, 1500));
    }
    say.textContent = "LOKI Studio is taking long to start. Look at its log (harness_data/studio/studio.log), or open it by hand.";
    return null;
  }

  // ---------------------------------------------------------------- Godot: the REAL Godot editor, live with LOKI's agents
  // Owner 2026-10-18: "the agents should be able to roam around in a live project state, change everything ... we want
  // the godot and the assetstore and all the plugins". So this tab drives the Godot app on this computer: open one of
  // the owner's projects (~/LOKI Projects/<name>) with the LOKI plugin, see the live link (engine/godot_live.py), what
  // each agent is doing in the editor, tell the agents what to change, and add plugins from the Asset Library
  // (recorded in the project's plugins.json, so every machine gets them).
  async function buildGodot(p) {
    const head = mk("div", "mode-tools");
    const pick = mk("select"); pick.setAttribute("aria-label", "Godot project");
    const status = mk("span", "mode-note");
    const btn = (label, tip, fn, cls) => { const b = mk("button", cls || "quiet small", label); b.type = "button"; b.title = tip; b.addEventListener("click", fn); return b; };
    const open = btn("Open in Godot", "Open the project in the Godot app on this computer, with the LOKI plugin and its Asset Library plugins - your agents work in it live.", async () => {
      if (!pick.value) return;
      open.disabled = true;
      const r = await call("/godot-editor/native", { name: pick.value });
      status.textContent = r.ok ? r.note : (r.error || "failed");
      // no Godot on this computer: LOKI's Godot 4.7.2 is downloading - show how it goes until it opens (or says why not)
      for (let i = 0; r.ok && r.downloading && i < 400; i++) {
        await new Promise((res) => setTimeout(res, 3000));
        let s = null;
        try { s = await call("/godot-editor/status"); } catch (_) { continue; }
        const g = (s && s.loki_godot) || {};
        if (g.state === "done") { status.textContent = g.note || "The project is opening in Godot 4.7.2."; break; }
        if (g.state === "failed") { status.textContent = g.note || "could not get Godot 4.7.2"; break; }
        status.textContent = "Getting Godot 4.7.2 (one time)... " + Math.round((i + 1) * 3) + " s";
      }
      open.disabled = false;
      setTimeout(refresh, 4000);
    }, "send small");
    // never a dead end: make a new project, or add one that lives in another folder (~/new-game-project ...)
    const addBox = mk("form", "godot-add"); addBox.hidden = true;
    const addIn = mk("input"); addIn.setAttribute("aria-label", "Project name or folder");
    const addGo = mk("button", "send small", "Add"); addGo.type = "submit";
    const addX = btn("Cancel", "Close this without adding anything.", () => { addBox.hidden = true; });
    addBox.append(addIn, addGo, addX);
    let addKind = "new";
    const showAdd = (kind) => {
      addKind = kind; addBox.hidden = false; addIn.value = "";
      addIn.placeholder = kind === "new" ? "Name of the new project, e.g. Racer" : "The project's folder, e.g. ~/new-game-project";
      addGo.textContent = kind === "new" ? "Make it" : "Add it";
      addIn.focus();
    };
    addIn.addEventListener("keydown", (e) => e.stopPropagation());
    addBox.addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = addIn.value.trim();
      if (!v) return;
      addGo.disabled = true;
      let r;
      try { r = await call(addKind === "new" ? "/godot-editor/new" : "/godot-editor/link", addKind === "new" ? { name: v } : { path: v }); }
      catch (err) { r = { ok: false, error: err.message }; }
      addGo.disabled = false;
      status.textContent = r && r.ok ? r.note : ((r && r.error) || "failed");
      if (r && r.ok) { addBox.hidden = true; wantProject = r.name; await projects(); refresh(); }
    });
    const newBtn = btn("New project", "Make a new, empty Godot project in ~/LOKI Projects.", () => showAdd("new"));
    const linkBtn = btn("Add from folder", "Add a Godot project you already have somewhere else - it stays where it is.", () => showAdd("link"));
    head.append(pick, open, newBtn, linkBtn, status, addBox);

    const link = mk("section", "godot-live");
    const linkHead = mk("h3", "", "Live link");
    const linkBody = mk("div", "godot-live-body");
    link.append(linkHead, linkBody);

    const ask = mk("form", "godot-ask");
    const askText = mk("textarea"); askText.rows = 2;
    askText.placeholder = "Tell LOKI's agents what to change in the open project - e.g. \"add a lighthouse on the east cliff\"";
    askText.setAttribute("aria-label", "What should LOKI's agents change in Godot?");
    const askGo = mk("button", "send small", "Send to the agents"); askGo.type = "submit";
    ask.append(askText, askGo);
    ask.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = askText.value.trim();
      if (!text) return;
      askGo.disabled = true;
      const prompt = "Work in the LIVE Godot editor with the godot_editor tool (the owner's real Godot, " +
        (pick.selectedOptions[0] ? pick.selectedOptions[0].textContent : "the open project") + "). Start with editor_state; " +
        "change scenes and scripts through godot_editor (undoable), save what you change, then run_game and look " +
        "(screenshot / game_tree) to check it works. The task: " + text;
      const r = await call("/jobs", { backend: "local", agent: "loki", prompt, isolate: false, timeout_s: 3600 });
      askGo.disabled = false;
      if (r && (r.ok || r.id || (r.job && r.job.id))) { askText.value = ""; status.textContent = "An agent took it - watch it below and on the home screen."; }
      else status.textContent = (r && r.error) || "could not start the agent";
      refresh();
    });

    const plug = mk("section", "godot-plugins");
    const plugHead = mk("h3", "", "Plugins");
    const plugList = mk("div", "godot-plugin-list");
    const plugForm = mk("form", "godot-plugin-add");
    const assetId = mk("input"); assetId.placeholder = "Asset Library number"; assetId.inputMode = "numeric";
    assetId.setAttribute("aria-label", "Asset Library asset number");
    const assetGo = mk("button", "quiet small", "Add plugin"); assetGo.type = "submit";
    const browse = btn("Browse the Asset Library", "godotengine.org/asset-library: the number is in the asset's address (asset/1234). In Godot itself the AssetLib tab works too.", () => {
      window.open("https://godotengine.org/asset-library/asset?godot_version=4.7", "_blank", "noopener");
    });
    plugForm.append(assetId, assetGo, browse);
    plugForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!assetId.value.trim()) return;
      assetGo.disabled = true;
      const r = await call("/api/godot/call", { action: "install_plugin", args: { asset_id: assetId.value.trim() }, timeout: 120 });
      assetGo.disabled = false;
      status.textContent = r.ok ? "Installed " + r.installed.name + " " + r.installed.version + " - " + r.next : (r.error || "failed");
      if (r.ok) assetId.value = "";
      refreshPlugins();
    });
    plug.append(plugHead, plugList, plugForm);
    p.append(head, link, ask, plug);

    function ago(t) { const s = Math.max(0, Math.round(Date.now() / 1000 - t)); return s < 60 ? s + " s ago" : Math.round(s / 60) + " min ago"; }
    async function refresh() {
      let ed;
      try { ed = await call("/api/godot/editors"); } catch (_) { ed = null; }
      linkBody.replaceChildren();
      const eds = (ed && ed.editors) || [];
      if (!eds.length) {
        linkBody.append(mk("p", "mode-note", "No Godot editor is linked right now. Open a project in Godot: the LOKI plugin links it to LOKI by itself within seconds, and every LOKI agent can then see and change it live."));
        if (pick.value) linkBody.append(btn("Open in Godot", "Opens the picked project in Godot, linked live.", () => open.click(), "send small"));
        else linkBody.append(btn("New project", "Make a new, empty Godot project.", () => showAdd("new"), "send small"),
          btn("Add from folder", "Add a Godot project you already have.", () => showAdd("link")));
      }
      for (const e of eds) {   // studio_godot.Editor.summary()
        linkBody.append(mk("p", "godot-editor-row", "Godot " + (e.godot || "") + " - " + (e.name || e.project) +
          (e.edited_scene ? " - editing " + e.edited_scene : "") + (e.playing ? " - the game is running" : "")));
      }
      const act = (ed && ed.activity) || {};
      const rows = Object.entries(act).sort((a, b) => b[1].t - a[1].t);
      if (rows.length) {
        const ul = mk("ul", "godot-activity");
        for (const [who, a] of rows) ul.append(mk("li", "", (who === "loki" ? "LOKI" : "Agent " + who.replace(/^job-/, "")) + ": " + a.detail + " (" + ago(a.t) + ")"));
        linkBody.append(mk("p", "mode-note small", "Working in the editor now:"), ul);
      }
    }
    async function refreshPlugins() {
      let r;
      try { r = await call("/api/godot/call", { action: "plugins" }); } catch (_) { r = null; }
      plugList.replaceChildren();
      if (!r || !r.ok) { plugList.append(mk("p", "mode-note", (r && r.error) || "")); return; }
      const man = r.manifest || [];
      if (!man.length && !(r.installed || []).length) plugList.append(mk("p", "mode-note", "No plugins yet besides LOKI's own."));
      for (const m of man) plugList.append(mk("p", "godot-plugin", m.name + " " + (m.version || "") + " (" + (m.license || "?") + ") - " + (m.addons || []).join(", ")));
      const extra = (r.installed || []).filter((n) => n !== "loki_studio" && !man.some((m) => (m.addons || []).includes(n)));
      if (extra.length) plugList.append(mk("p", "mode-note small", "Also in addons/ (not in plugins.json, so only on this machine): " + extra.join(", ")));
    }
    async function projects() {
      let s;
      try { s = await call("/godot-editor/status"); } catch (e) { status.textContent = e.message; return; }
      if (!s || !s.ok) { status.textContent = (s && s.error) || "LOKI's engine does not answer."; return; }
      const keep = wantProject || pick.value; pick.replaceChildren();
      for (const pr of s.projects || []) pick.append(new Option(pr.label, pr.name));
      if (!pick.options.length) {
        pick.append(new Option("no Godot project yet", ""));
        status.textContent = "No Godot project in " + s.projects_dir + " yet - make a New project, or Add from folder one you already have.";
      }
      if ([...pick.options].some((o) => o.value === keep)) pick.value = keep;
      wantProject = "";
      // no Godot on this computer: LOKI gets its own Godot 4.7.2 on the first Open (engine/godot_web.py)
      open.disabled = !pick.value;
      const g = s.loki_godot || {};
      if (g.state === "downloading" && !s.native) status.textContent = "Getting LOKI's Godot 4.7.2 (one time)...";
    }
    godotPick = (name) => { if ([...pick.options].some((o) => o.value === name)) pick.value = name; else { wantProject = name; projects(); } };
    pick.addEventListener("change", projects);
    await projects();
    refresh(); refreshPlugins();
    const timer = setInterval(() => { if (!p.hidden && !document.hidden) refresh(); }, 3000);
    p.addEventListener("remove", () => clearInterval(timer));
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

  // ---------------------------------------------------------------- Render: the Render Studio, when it is in this window
  // The Render Studio script registers itself (LokiModeBar.register("render", {enter, leave}) or window.LokiRenderStudio
  // with open(pane, opts)). Until it does, the tab offers Forge's own Render window (forge_render.js).
  function enterRender(p, opts) {
    const rs = window.LokiRenderStudio;
    if (rs && typeof rs.open === "function") { rs.open(p, opts || {}); return; }
    if (p.childElementCount) return;
    const box = mk("div", "render-empty");
    box.append(mk("h3", "", "Render"),
      mk("p", "mode-note", "Render Studio is not in this window yet. Forge can already make a path-traced render of its scene."));
    const b = mk("button", "send small", "Open Forge's Render window"); b.type = "button";
    b.addEventListener("click", () => {
      go("forge");
      setTimeout(() => { if (window.ForgeRender && typeof window.ForgeRender.openDialog === "function") window.ForgeRender.openDialog(true); }, 300);
    });
    box.append(b);
    p.append(box);
  }

  function go(id, opts) {
    if (!MODES.some((m) => m.id === id)) return;
    if (id === active) { deliver(id, opts); return; }
    const was = active;
    if (hooks[was] && typeof hooks[was].leave === "function") { try { hooks[was].leave(); } catch (_) { /* its own problem */ } }
    if (was === "forge") leaveForge();
    if (panes[was]) panes[was].hidden = true;
    active = id;
    document.body.dataset.mode = id;
    for (const b of document.querySelectorAll(".modebar-tab")) b.setAttribute("aria-selected", String(b.dataset.mode === id));
    if (id === "loki") { deliver(id, opts); return; }
    const p = pane(id); p.hidden = false;
    if (hooks[id] && typeof hooks[id].enter === "function") { hooks[id].enter(p, opts || {}); return; }
    if (id === "forge") { enterForge(p); deliver(id, opts); return; }
    if (id === "render") { enterRender(p, opts); return; }
    if (!built[id]) { built[id] = true; buildGodot(p).then(() => deliver(id, opts)); return; }
    deliver(id, opts);
  }

  // what a project card asked for once the mode is up: a Forge model, a Godot project
  function deliver(id, opts) {
    if (!opts) return;
    if (id === "forge" && opts.model && typeof window.forgeLoad === "function") window.forgeLoad(opts.model);
    else if (id === "forge" && opts.model && typeof forgeLoad === "function") forgeLoad(opts.model);   // eslint-disable-line no-undef
    if (id === "godot" && opts.project) { if (godotPick) godotPick(opts.project); else wantProject = opts.project; }
    if (id === "render" && window.LokiRenderStudio && typeof window.LokiRenderStudio.show === "function") window.LokiRenderStudio.show(opts);
  }

  function register(id, hook) { hooks[id] = hook || {}; }

  // which mode a key asks for: Godot's keys (Option+1..4 Mac, Ctrl+F1..F4 Windows - Cmd+F1..F4 works on a Mac too),
  // or Ctrl/Cmd+1..4 when Forge does not have that key (in Forge they are its own: Ctrl/Cmd+1 = Isolate Select)
  function keyMode(e) {
    if (e.shiftKey) return -1;
    const code = e.code || "";
    let f = /^F([1-9])$/.exec(code) || /^F([1-9])$/.exec(e.key || "");
    if (f && (e.ctrlKey || e.metaKey) && !e.altKey) return Number(f[1]) - 1;
    const d = /^Digit([1-9])$/.exec(code) || (!code && /^([1-9])$/.exec(e.key || ""));
    if (!d) return -1;
    if (e.altKey && !e.ctrlKey && !e.metaKey && isMac) return Number(d[1]) - 1;
    if ((e.ctrlKey || e.metaKey) && !e.altKey) {
      if (typeof window.forgeOwnsKey === "function" && window.forgeOwnsKey(e)) return -1;   // Forge's own key
      return Number(d[1]) - 1;
    }
    return -1;
  }

  function onKey(e) {
    const i = keyMode(e);
    const m = i >= 0 ? MODES[i] : null;
    if (!m) return;
    e.preventDefault();
    e.stopPropagation();
    go(m.id);
  }

  function init() {
    if (document.getElementById("modebar")) return;
    document.body.prepend(strip());
    document.body.dataset.mode = active;
    document.body.classList.add("has-modebar");
    document.addEventListener("keydown", onKey, true);
  }

  return { init, go, register, buildStudio, keyMode, modes: () => MODES.map((m) => m.id), active: () => active };
})();
window.LokiModeBar = LokiModeBar;
document.addEventListener("DOMContentLoaded", LokiModeBar.init);
