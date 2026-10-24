// Forge's Level workspace, the editor side (owner 2026-10-24: "i want forge as an editor or something close to unreal
// engine"). The engine is app/ui/forge_level_core.js (ForgeLevel: actors, scripts, Play sessions, level files); this
// file is the panel and the wiring, built like the Baking workspace (forge_bake.js): one panel beside the viewport,
// commands in FORGE_PRO_CMDS, nothing else in Forge hard-codes it.
//
//   Place Actors      Empty, Point / Directional / Spot Light, Camera, Player Start, Trigger Box -> Outliner nodes
//   Content Browser   the workspace's models/ (.glb) placed as actors; saved levels (.level) to open
//   Details           the selected node's actor settings, tags and scripts (any Forge object can get a script)
//   Play / Simulate   Play possesses the Player Start (W A S D, mouse look, Shift runs, Esc stops); Simulate runs the
//                     scripts with the editor camera. Stop puts the scene back exactly as it was.
"use strict";

if (typeof ICON_PATHS !== "undefined") {
  Object.assign(ICON_PATHS, {
    empty: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" stroke-dasharray="2 2"/>',
    spot: '<path d="M9 3h6l3 9H6z"/><path d="M8 15l-3 6M16 15l3 6M12 15v6"/>',
    trigger: '<rect x="4" y="4" width="16" height="16" rx="1" stroke-dasharray="3 2"/><path d="M9 12l2 2 4-4"/>',
    simulate: '<path d="M7 4v16l12-8z" stroke-dasharray="2.5 1.5"/>',
    script: '<path d="M8 7l-4 5 4 5M16 7l4 5-4 5M13.5 5l-3 14"/>',
    level: '<path d="M3 17l5-6 4 4 3-3 6 5z"/><circle cx="16" cy="7" r="2"/>',
  });
}

const ForgeLevelUI = (() => {
  const S = { view: null, panel: null, session: null, selId: null, keyCap: null, saved: null, levelName: "level1",
    brush: { mode: null, radius: 6, strength: 0.4, color: "dirt" }, brushCap: null, cursor: null };
  const L = () => (typeof ForgeLevel !== "undefined" ? ForgeLevel : null);
  const api = () => S.view && S.view.tree && S.view.tree.api;
  const q = (sel) => S.panel && S.panel.querySelector(sel);
  const stopKeys = (e) => { e.stopPropagation(); if (e.key === "Escape") e.target.blur(); };

  function say(text, bad) {
    const s = q(".flv-status"); if (s) { s.textContent = text; s.classList.toggle("bad", !!bad); }
    return text;
  }
  function log(text, bad) {
    const box = q(".flv-log"); if (!box) return;
    const line = el("div", "flv-logline" + (bad ? " bad" : ""), text);
    box.append(line);
    while (box.children.length > 200) box.firstChild.remove();
    box.scrollTop = box.scrollHeight;
  }
  const btn = (icon, name, what, fn, id) => {
    const b = forgeBtn(icon, name, what, (e) => { e.stopPropagation(); fn(); });
    if (id) b.dataset.lv = id;
    return b;
  };
  const sec = (title, cls) => { const d = el("div", "fuv-sec flv-sec " + (cls || "")); d.append(el("div", "fuv-sec-title", title)); return d; };

  // ---------------------------------------------------------------- the panel
  function build() {
    const body = document.querySelector("#forge .forge-body");
    if (!body || !L()) return null;
    if (S.panel) return S.panel;
    const p = el("aside", "forge-uvpanel forge-levelpanel"); p.id = "forge-levelpanel"; p.hidden = true;
    S.panel = p;
    const head = el("div", "fuv-head"); head.append(el("span", "fuv-title", "Level"));
    const tb = el("div", "fuv-toolbar");
    tb.append(
      btn("play", "Play", "Play in Editor from the Player Start (third person, WoW controls): W / S move, A / D turn, Q / E strafe, Space jumps, right-drag turns, left-drag looks, wheel zooms, Shift runs, Esc stops.", () => play(true), "play"),
      btn("simulate", "Simulate", "Run the level's scripts with the editor camera - nobody is possessed.", () => play(false), "simulate"),
      btn("stop", "Stop", "Stop playing: every object goes back exactly as it was.", () => stop(), "stop"),
      btn("save", "Save Level", "Save the level's actors, settings and scripts to models/ as a .level file.", () => save(), "save"),
      btn("check", "Check Scripts", "Compile every script in the level and list the errors, without playing.", () => check(), "check"));
    head.append(tb);
    const scroll = el("div", "flv-body");
    const place = sec("Place Actors", "flv-place");
    const grid = el("div", "flv-grid");
    for (const [type, def] of Object.entries(L().ACTORS)) grid.append(btn(def.icon, def.label, def.what, () => placeActor(type), "place-" + type));
    place.append(grid);
    const terr = sec("Terrain", "flv-terrain");
    const tools = el("div", "flv-grid");
    for (const [m, icon, label, what] of [["raise", "grow", "Raise", "Drag on the terrain to raise hills."], ["lower", "shrink", "Lower", "Drag to dig valleys."],
      ["smooth", "smooth", "Smooth", "Drag to soften bumps and edges."], ["flatten", "flatten", "Flatten", "Drag to level the ground to where you started."],
      ["paint", "brush", "Paint", "Drag to paint the ground with the colour below."]]) tools.append(btn(icon, label, what, () => brushMode(m), "tb-" + m));
    const trow = (label, key, min, max, step) => {
      const r = el("label", "fuv-set-row"), i = el("input"); i.type = "range"; i.min = min; i.max = max; i.step = step; i.value = S.brush[key];
      i.addEventListener("input", () => { S.brush[key] = +i.value; }); r.append(el("span", "", label), i); return r;
    };
    const paints = el("div", "flv-grid");
    for (const name of Object.keys(L().PAINT)) {
      const b = el("button", "flv-paint", name); b.type = "button"; b.dataset.paint = name; b.style.borderLeft = "10px solid " + L().PAINT[name];
      b.title = "Paint with " + name; b.addEventListener("click", () => { S.brush.color = name; brushMode("paint"); }); paints.append(b);
    }
    terr.append(tools, trow("Radius", "radius", 1, 30, 0.5), trow("Strength", "strength", 0.05, 1.5, 0.05), paints);
    const content = sec("Content Browser", "flv-content");
    content.append(btn("update", "Refresh", "List the models and levels in the workspace's models/ folder again.", () => refresh(), "refresh"),
      el("div", "flv-assets"), el("div", "flv-levels"));
    const details = sec("Details", "flv-detailsec"); details.append(el("div", "flv-details"));
    const out = sec("Output", "flv-out"); out.append(el("div", "flv-log"));
    scroll.append(place, terr, content, details, out);
    p.append(head, scroll, el("div", "fuv-status flv-status", "Level workspace."));
    p.addEventListener("keydown", (e) => { if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) stopKeys(e); });
    const chan = document.getElementById("forge-chancol");
    if (chan && chan.parentElement === body) body.insertBefore(p, chan); else body.append(p);
    if (typeof FORGE_SPLIT_PANELS !== "undefined" && !FORGE_SPLIT_PANELS.some((x) => x[0] === "forge-levelpanel")) FORGE_SPLIT_PANELS.push(["forge-levelpanel", "right", 30, 18, 60]);
    if (typeof forgeSplitAttach === "function") forgeSplitAttach();
    return p;
  }

  function show(on) {
    const p = build(); if (!p) return;
    p.hidden = !on;
    if (!on && S.session) stop();
    if (!on) brushMode(null);
    if (on) { refresh(); details(); }
    if (typeof forgeSplitAttach === "function") forgeSplitAttach();
  }

  // ---------------------------------------------------------------- placing
  function undoable(label, fn) {
    const a = api();
    return a && typeof a.undoChunk === "function" ? a.undoChunk(label, fn) : fn();
  }
  const SPAWN = { pointLight: [0, 3, 0], dirLight: [4, 8, 4], spotLight: [0, 4, 2], camera: [0, 1.7, 6], npcSpawn: [8, 0, -8] };

  // ---------------------------------------------------------------- terrain brush
  function terrainHit(e) {
    const v = S.view, T = v.THREE, r = v.canvas.getBoundingClientRect();
    const ray = new T.Raycaster();
    ray.setFromCamera(new T.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), v.camera);
    const meshes = L().terrains(v.scene).map((t) => t.vis.getObjectByName("terrain"));
    const hit = ray.intersectObjects(meshes, false)[0];
    if (!hit) return null;
    const item = L().terrains(v.scene).find((t) => t.vis.getObjectByName("terrain") === hit.object);
    return { point: hit.point, obj: item.obj };
  }
  function brushMode(mode) {
    const v = S.view; if (!v) return "";
    S.brush.mode = S.brush.mode === mode ? null : mode;
    S.panel && S.panel.querySelectorAll("[data-lv^=tb-]").forEach((b) => b.classList.toggle("on", b.dataset.lv === "tb-" + S.brush.mode));
    if (S.brushCap) { window.removeEventListener("pointerdown", S.brushCap.down, true); window.removeEventListener("pointermove", S.brushCap.move, true); window.removeEventListener("pointerup", S.brushCap.up, true); S.brushCap = null; }
    if (S.cursor) { S.cursor.parent && S.cursor.parent.remove(S.cursor); S.cursor = null; v.dirty = true; }
    if (!S.brush.mode) return say("Terrain brush off.");
    if (!L().terrains(v.scene).length) placeActor("terrain");
    const T = v.THREE;
    S.cursor = new T.Mesh(new T.RingGeometry(0.95, 1, 40), new T.MeshBasicMaterial({ color: 0xffd34d, side: T.DoubleSide, depthTest: false, transparent: true }));
    S.cursor.rotation.x = -Math.PI / 2; S.cursor.renderOrder = 999; S.cursor.visible = false; S.cursor.raycast = () => {};
    v.scene.add(S.cursor);
    let drag = null;
    const dab = (hit) => { if (L().sculpt(T, hit.obj, hit.point, S.brush)) v.dirty = true; };
    S.brushCap = {
      down: (e) => {
        if (e.target !== v.canvas || e.button !== 0 || e.altKey || S.session) return;
        const hit = terrainHit(e); if (!hit) return;
        e.preventDefault(); e.stopImmediatePropagation();    // the brush owns this drag, not Forge's selection
        if (v.controls) v.controls.enabled = false;
        drag = { obj: hit.obj };
        if (S.brush.mode === "flatten") S.brush.height = hit.point.y;
        dab(hit);
      },
      move: (e) => {
        if (S.session) return;
        const hit = terrainHit(e);
        if (S.cursor) { S.cursor.visible = !!hit; if (hit) { S.cursor.position.copy(hit.point); S.cursor.position.y += 0.08; S.cursor.scale.setScalar(S.brush.radius); } v.dirty = true; }
        if (drag && hit && hit.obj === drag.obj) dab(hit);
      },
      up: () => { if (!drag) return; drag = null; S.brush.height = null; if (v.controls) v.controls.enabled = true; },
    };
    window.addEventListener("pointerdown", S.brushCap.down, true);   // window capture: before Forge's own canvas handlers
    window.addEventListener("pointermove", S.brushCap.move, true);
    window.addEventListener("pointerup", S.brushCap.up, true);
    return say({ raise: "Raise: drag on the terrain. Alt-drag still orbits the camera.", lower: "Lower: drag to dig.", smooth: "Smooth: drag over bumps.",
      flatten: "Flatten: drag - the ground levels to where you started.", paint: "Paint (" + S.brush.color + "): drag on the terrain." }[S.brush.mode]);
  }
  function placeActor(type, opts) {
    const a = api(), def = L() && L().ACTORS[type];
    if (!a || !def || typeof a.addActor !== "function") return say("Open Forge first.", true);
    const o = Object.assign({ position: SPAWN[type] || [0, 0, 0] }, opts || {});
    const n = undoable("Place " + def.label, () => {
      const made = a.addActor(def.label.replace(/\s+/g, ""), type, o);
      if (made && o.position) made.grp.position.set(o.position[0], o.position[1], o.position[2]);
      return made;
    });
    if (n) { details(); S.view.dirty = true; }
    return say(n ? "Placed " + def.label + " (" + n.name + ")." : "Could not place " + def.label + ".", !n);
  }

  async function fetchFile(name) {
    const r = await fetch("/forge/file/" + encodeURIComponent(name), { headers: { Authorization: "Bearer " + state.token } });
    if (!r.ok) throw new Error("could not load " + name);
    return r;
  }
  async function placeAsset(name) {
    const a = api(); if (!a) return say("Open Forge first.", true);
    try {
      const { GLTFLoader } = await import("/ui/vendor/three/addons/loaders/GLTFLoader.js");
      const gltf = await new GLTFLoader().parseAsync(await (await fetchFile(name)).arrayBuffer(), "");
      const stem = name.replace(/^\d{8}-\d{6}-/, "").replace(/\.glb$/i, "").replace(/[^A-Za-z0-9_]+/g, "_") || "mesh";
      const n = undoable("Place " + stem, () => a.addActor(stem, "mesh", { asset: name }, gltf.scene));
      details(); S.view.dirty = true;
      return say(n ? "Placed " + name + " as " + n.name + "." : "Could not place " + name + ".", !n);
    } catch (e) { return say("Could not place " + name + ": " + e.message, true); }
  }

  async function refresh() {
    const box = q(".flv-assets"), lv = q(".flv-levels"); if (!box) return;
    const [models, levels] = await Promise.all([fetchJson("/forge/list"), fetchJson("/forge/levels")]);
    box.replaceChildren(); lv.replaceChildren();
    const items = (models && models.items) || [];
    if (!items.length) box.append(el("p", "note", "No models yet - make or save one in Forge."));
    for (const it of items.slice(0, 60)) {
      const b = el("button", "flv-asset", it.name.replace(/^\d{8}-\d{6}-/, "").replace(/\.glb$/, ""));
      b.type = "button"; b.title = "Place " + it.name + " in the level"; b.dataset.asset = it.name;
      b.addEventListener("click", () => placeAsset(it.name));
      box.append(b);
    }
    for (const it of ((levels && levels.items) || []).slice(0, 30)) {
      const b = el("button", "flv-asset flv-level", it.name.replace(/\.level$/, "") + " · " + it.actors + " actors");
      b.type = "button"; b.title = "Open " + it.name + " (adds its actors to the scene)"; b.dataset.level = it.name;
      b.addEventListener("click", () => openLevel(it.name));
      lv.append(b);
    }
  }
  async function fetchJson(path) {
    try {
      const r = await fetch(path, { headers: { Authorization: "Bearer " + state.token } });
      return r.ok ? await r.json() : null;
    } catch (_) { return null; }
  }

  // ---------------------------------------------------------------- details
  function selectedNode() {
    const a = api(); if (!a) return null;
    const sel = S.view.tree.sel || [];
    return sel.length ? a.node(sel[sel.length - 1]) : null;
  }

  function details() {
    const box = q(".flv-details"); if (!box) return;
    const n = selectedNode();
    S.selId = n ? n.id : null;
    box.replaceChildren();
    if (!n) { box.append(el("p", "note", "Select an actor - or any Forge object - to see its details.")); return; }
    const Lv = L(), data = Lv.actorOf(n.grp);
    box.append(el("div", "flv-name", n.name + (data ? " · " + ((Lv.ACTORS[data.actor] || {}).label || "Static Mesh") : " · Forge object")));
    if (!data) {
      box.append(el("p", "note", "Give it a script to make it an actor: it then moves, reacts and saves with the level."),
        btn("script", "Add Script", "Make this object an actor with a starter script (spins it while playing).", () => addScript(n), "addscript"));
      return;
    }
    const def = Lv.ACTORS[data.actor];
    for (const [key, val] of Object.entries(data.props || {})) box.append(propRow(n, data, key, val));
    const tags = el("label", "fuv-set-row"), ti = el("input");
    ti.value = (data.tags || []).join(", "); ti.placeholder = "e.g. overlap";
    ti.title = "Tags, comma separated. \"overlap\" makes Trigger Boxes notice this actor.";
    ti.addEventListener("change", () => { data.tags = ti.value.split(",").map((t) => t.trim()).filter(Boolean); });
    tags.append(el("span", "", "Tags"), ti); box.append(tags);
    if (def && data.actor === "playerStart") box.append(el("p", "note", "Play starts here, facing the cone."));
    for (const s of data.scripts) box.append(scriptBox(n, data, s));
    box.append(btn("script", "Add Script", "Add another script to this actor.", () => addScript(n), "addscript"));
  }

  function propRow(n, data, key, val) {
    const r = el("label", "fuv-set-row"); r.append(el("span", "", key));
    const commit = () => { L().applyProps(n.grp); S.view.dirty = true; };
    if (Array.isArray(val)) {
      const wrap = el("span", "flv-vec");
      val.forEach((x, i) => {
        const inp = el("input"); inp.type = "number"; inp.step = "0.1"; inp.value = String(x);
        inp.addEventListener("change", () => { if (isFinite(+inp.value)) { data.props[key][i] = +inp.value; commit(); } });
        wrap.append(inp);
      });
      r.append(wrap);
    } else if (typeof val === "number") {
      const inp = el("input"); inp.type = "number"; inp.step = "0.1"; inp.value = String(val);
      inp.addEventListener("change", () => { if (isFinite(+inp.value)) { data.props[key] = +inp.value; commit(); } });
      r.append(inp);
    } else if (key === "mode") {
      const s = el("select"); for (const m of ["walk", "fly"]) { const o = el("option", "", m); o.value = m; s.append(o); }
      s.value = val; s.addEventListener("change", () => { data.props[key] = s.value; commit(); });
      r.append(s);
    } else if (/^#[0-9a-f]{6}$/i.test(String(val))) {
      const c = el("input"); c.type = "color"; c.value = val;
      c.addEventListener("input", () => { data.props[key] = c.value; commit(); });
      r.append(c);
    } else {
      const t = el("input"); t.value = String(val); t.addEventListener("change", () => { data.props[key] = t.value; commit(); });
      r.append(t);
    }
    return r;
  }

  function scriptBox(n, data, s) {
    const box = el("div", "flv-script");
    const top = el("div", "flv-script-top");
    const name = el("input", "flv-script-name"); name.value = s.name || "script";
    name.addEventListener("change", () => { s.name = name.value.trim() || "script"; });
    const on = el("input"); on.type = "checkbox"; on.checked = s.enabled !== false; on.title = "Run this script when playing";
    on.addEventListener("change", () => { s.enabled = on.checked; });
    top.append(name, on, btn("trash", "Remove Script", "Delete this script from the actor.", () => {
      data.scripts.splice(data.scripts.indexOf(s), 1); details();
    }, "rmscript"));
    const ta = el("textarea", "flv-code"); ta.spellcheck = false; ta.value = s.source || ""; ta.rows = 9;
    ta.title = "start(), update(dt), stop(), keydown(e), keyup(e), pointerdown(e), beginOverlap(other), endOverlap(other). this = the actor; level.find / spawn / destroy / log / viewFrom, input.down(key), THREE, scene.";
    ta.addEventListener("input", () => { s.source = ta.value; });
    ta.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Tab") { e.preventDefault(); const i = ta.selectionStart; ta.setRangeText("  ", i, ta.selectionEnd, "end"); s.source = ta.value; }
    });
    box.append(top, ta);
    return box;
  }

  function addScript(n) {
    const Lv = L(), data = Lv.makeActor(n.grp, Lv.actorOf(n.grp) ? undefined : "mesh");
    data.scripts.push({ name: "script" + (data.scripts.length + 1), source: Lv.TEMPLATE, enabled: true });
    details();
    return say("Script added to " + n.name + ". It runs when you press Play.");
  }

  // ---------------------------------------------------------------- play
  function play(possess) {
    const v = S.view, Lv = L();
    if (!v || !Lv) return say("Open Forge first.", true);
    if (S.session) return say("Already playing - Esc or Stop first.");
    for (const p of Lv.checkScripts(v.scene)) log(p.actor + " / " + p.script + ": " + p.error, true);
    const s = new Lv.Session(v.THREE, v.scene, {
      possess, editorCamera: v.camera,
      aspect: (v.canvas.clientWidth || 16) / (v.canvas.clientHeight || 9),
      onLog: (m) => log(m), onError: (e) => log(e.actor + " / " + e.script + " (" + e.where + "): " + e.error, true),
    });
    S.saved = { target: v.transform && v.transform.object, controls: v.controls ? v.controls.enabled : true };
    if (v.transform && v.transform.object) v.transform.detach();
    if (possess && v.controls) v.controls.enabled = false;
    try { s.start(); } catch (e) { log("Play failed to start: " + e.message, true); return say("Play failed: " + e.message, true); }
    S.session = s;
    let last = performance.now();
    v.playing = {
      frame() {
        const now = performance.now(); s.tick((now - last) / 1000); last = now;
        const cam = s.camera;
        if (cam && cam !== v.camera) { const asp = (v.canvas.clientWidth || 16) / (v.canvas.clientHeight || 9); if (Math.abs(cam.aspect - asp) > 1e-3) { cam.aspect = asp; cam.updateProjectionMatrix(); } }
        if (!s.running) setTimeout(stop, 0);
        return cam;
      },
    };
    brushMode(null);
    let dragBtn = -1, lastX = 0, lastY = 0;
    const third = () => s.mode === "third";
    S.keyCap = {
      down: (e) => { if (e.key === "Escape") { e.preventDefault(); stop(); } else s.keydown(e); e.stopPropagation(); if (e.key === " ") e.preventDefault(); },
      up: (e) => { s.keyup(e); e.stopPropagation(); },
      move: (e) => {
        if (third()) { if (dragBtn >= 0) { s.look(e.clientX - lastX, e.clientY - lastY, dragBtn === 2 ? "turn" : "orbit"); lastX = e.clientX; lastY = e.clientY; } }
        else if (document.pointerLockElement === v.canvas) s.look(e.movementX || 0, e.movementY || 0);
      },
      press: (e) => {
        if (e.target !== v.canvas) return;
        s.pointerdown(e);
        if (third()) { e.preventDefault(); e.stopImmediatePropagation(); dragBtn = e.button; lastX = e.clientX; lastY = e.clientY; if (e.button === 2) s.setTurning(true); }
        else if (possess && v.canvas.requestPointerLock && document.pointerLockElement !== v.canvas) { try { v.canvas.requestPointerLock(); } catch (_) { /* not allowed here */ } }
      },
      release: (e) => { if (e.button === 2) s.setTurning(false); if (e.button === dragBtn) dragBtn = -1; },
      wheel: (e) => { if (third()) { e.preventDefault(); e.stopPropagation(); s.zoom(e.deltaY); } },
      menu: (e) => { e.preventDefault(); e.stopPropagation(); },
    };
    window.addEventListener("pointerup", S.keyCap.release, true);
    v.canvas.addEventListener("wheel", S.keyCap.wheel, { capture: true, passive: false });
    v.canvas.addEventListener("contextmenu", S.keyCap.menu, true);
    window.addEventListener("keydown", S.keyCap.down, true);
    window.addEventListener("keyup", S.keyCap.up, true);
    window.addEventListener("pointermove", S.keyCap.move, true);
    window.addEventListener("pointerdown", S.keyCap.press, true);     // before Forge's own canvas handlers
    document.getElementById("forge")?.classList.add("flv-playing");
    v.canvas.classList.add("flv-playcanvas");                       // a green frame while playing
    v.dirty = true;
    return say(possess ? (s.mode === "third" ? "Playing - W / S move, A / D turn, Q / E strafe, Space jumps, right-drag turns, left-drag looks, wheel zooms, Esc stops." : "Playing - click the view to look around, W A S D to move, Esc to stop.") : "Simulating - scripts are running. Esc or Stop to end.");
  }

  function stop() {
    const v = S.view, s = S.session;
    if (!s) return say("Not playing.");
    S.session = null;
    if (v) v.playing = null;
    try { s.stop(); } catch (e) { log("Stop: " + e.message, true); }
    if (S.keyCap) {
      window.removeEventListener("keydown", S.keyCap.down, true);
      window.removeEventListener("keyup", S.keyCap.up, true);
      window.removeEventListener("pointermove", S.keyCap.move, true);
      window.removeEventListener("pointerup", S.keyCap.release, true);
      window.removeEventListener("pointerdown", S.keyCap.press, true);
      if (v) { v.canvas.removeEventListener("wheel", S.keyCap.wheel, { capture: true }); v.canvas.removeEventListener("contextmenu", S.keyCap.menu, true); }
      S.keyCap = null;
    }
    if (document.pointerLockElement && document.exitPointerLock) document.exitPointerLock();
    if (v) {
      if (v.controls) v.controls.enabled = S.saved ? S.saved.controls : true;
      if (S.saved && S.saved.target && v.transform && S.saved.target.parent) v.transform.attach(S.saved.target);
      if (v.tree) v.tree.build();
      v.dirty = true;
    }
    document.getElementById("forge")?.classList.remove("flv-playing");
    if (v) v.canvas.classList.remove("flv-playcanvas");
    details();
    const errs = s.errors.length;
    return say("Stopped after " + s.time.toFixed(1) + " s" + (errs ? " - " + errs + " script error" + (errs > 1 ? "s" : "") + " (see Output)." : ".") , errs > 0);
  }

  // ---------------------------------------------------------------- level files
  async function save(name) {
    const v = S.view, Lv = L(); if (!v || !Lv) return say("Open Forge first.", true);
    const doc = Lv.serialize(v.scene, { name: name || S.levelName, app: "LOKI Forge" });
    const loose = doc.actors.filter((a) => (a.type === "mesh" || !Lv.ACTORS[a.type]) && !a.asset).length;
    const file = (name || S.levelName).replace(/[^A-Za-z0-9_-]+/g, "_") + ".level";
    try {
      const r = await fetch("/forge/save?name=" + encodeURIComponent(file), {
        method: "POST", headers: { Authorization: "Bearer " + state.token }, body: JSON.stringify(doc) });
      const out = await r.json().catch(() => ({}));
      if (!r.ok || out.ok === false) return say("Could not save the level: " + (out.error || r.status), true);
      refresh();
      return say("Saved " + (out.name || file) + " (" + doc.actors.length + " actors)." +
        (loose ? " " + loose + " scripted Forge object" + (loose > 1 ? "s have" : " has") + " no model file: export it to models/ to keep its mesh in the level." : ""));
    } catch (e) { return say("Could not save the level: " + e.message, true); }
  }

  async function openLevel(name) {
    const v = S.view, a = api(), Lv = L(); if (!v || !a || !Lv) return say("Open Forge first.", true);
    try {
      const doc = await (await fetchFile(name)).json();
      if (doc.format !== Lv.FORMAT) throw new Error("not a LOKI level");
      const { GLTFLoader } = await import("/ui/vendor/three/addons/loaders/GLTFLoader.js");
      const byId = new Map();
      for (const rec of doc.actors) {
        let n;
        if (Lv.ACTORS[rec.type]) n = a.addActor(rec.name, rec.type, { props: rec.props });
        else if (rec.asset) {
          const gltf = await new GLTFLoader().parseAsync(await (await fetchFile(rec.asset)).arrayBuffer(), "");
          n = a.addActor(rec.name, rec.type || "mesh", { asset: rec.asset }, gltf.scene);
        } else continue; // a scripted Forge object without a model file: its mesh isn't in the level
        const data = Lv.actorOf(n.grp);
        data.props = rec.props || {}; data.scripts = rec.scripts || []; data.tags = rec.tags || [];
        if (rec.asset) data.asset = rec.asset;
        n.grp.position.fromArray(rec.position); n.grp.quaternion.fromArray(rec.quaternion); n.grp.scale.fromArray(rec.scale);
        n.grp.visible = rec.visible !== false;
        Lv.applyProps(n.grp);
        byId.set(rec.id, n);
      }
      for (const rec of doc.actors) {
        const n = byId.get(rec.id), p = byId.get(rec.parent);
        if (n && p && typeof a.reparent === "function") a.reparent(n.id, p.id);
      }
      S.levelName = name.replace(/\.level$/, "");
      v.tree.build(); details(); v.dirty = true;
      return say("Opened " + name + ": " + byId.size + " actors.");
    } catch (e) { return say("Could not open " + name + ": " + e.message, true); }
  }

  function check() {
    const v = S.view, Lv = L(); if (!v || !Lv) return say("Open Forge first.", true);
    const probs = Lv.checkScripts(v.scene);
    for (const p of probs) log(p.actor + " / " + p.script + ": " + p.error, true);
    const n = Lv.actors(v.scene).reduce((k, o) => k + (Lv.actorOf(o).scripts || []).length, 0);
    return say(probs.length ? probs.length + " of " + n + " scripts have errors (see Output)." : "All " + n + " scripts compile.", probs.length > 0);
  }

  // ---------------------------------------------------------------- attach
  function attach(v) {
    S.view = v;
    build();
    const a = api();
    if (a && !a.__lokiLevel) {
      const prev = a.onSelect;
      a.onSelect = function () { if (prev) prev.apply(this, arguments); if (S.panel && !S.panel.hidden) details(); };
      a.__lokiLevel = true;
    }
  }
  setInterval(() => {
    const v = typeof forge !== "undefined" && forge.view;
    if (v && v.tree && v !== S.view && document.querySelector("#forge .forge-body")) attach(v);
    if (S.panel && !S.panel.hidden && S.view && S.view.tree) {      // a click in the Outliner doesn't always go through onSelect
      const n = selectedNode(); if ((n ? n.id : null) !== S.selId && !S.panel.contains(document.activeElement)) details();
    }
  }, 400);

  return { show, play, stop, save, openLevel, placeActor, placeAsset, check, refresh, details, brushMode, state: S };
})();

// the commands (menus, the hotbox, the command line): wsLevel lives with the other workspaces in forge_uv_editor.js
if (typeof FORGE_PRO_CMDS !== "undefined") {
  const add = (id, label, fn) => { if (!FORGE_PRO_CMDS[id] || !FORGE_PRO_CMDS[id][1]) FORGE_PRO_CMDS[id] = [label, fn]; };
  add("levelPlay", "Play in Editor", () => ForgeLevelUI.play(true));
  add("levelSimulate", "Simulate", () => ForgeLevelUI.play(false));
  add("levelStop", "Stop Playing", () => ForgeLevelUI.stop());
  add("levelSave", "Save Level", () => ForgeLevelUI.save());
  add("levelCheckScripts", "Check Scripts", () => ForgeLevelUI.check());
  add("levelWorkspace", "Level Editor", () => ForgeUVEditor.setWorkspace("level"));
  add("placeEmpty", "Empty Actor", () => ForgeLevelUI.placeActor("empty"));
  add("placePointLight", "Point Light", () => ForgeLevelUI.placeActor("pointLight"));
  add("placeDirLight", "Directional Light", () => ForgeLevelUI.placeActor("dirLight"));
  add("placeSpotLight", "Spot Light", () => ForgeLevelUI.placeActor("spotLight"));
  add("placeCamera", "Camera Actor", () => ForgeLevelUI.placeActor("camera"));
  add("placePlayerStart", "Player Start", () => ForgeLevelUI.placeActor("playerStart"));
  add("placeTriggerBox", "Trigger Box", () => ForgeLevelUI.placeActor("triggerBox"));
  add("placeTerrain", "Terrain", () => ForgeLevelUI.placeActor("terrain"));
  add("placeNpcSpawn", "Creature Spawn", () => ForgeLevelUI.placeActor("npcSpawn"));
}
