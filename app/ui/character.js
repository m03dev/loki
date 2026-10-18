// LOKI World - the character creator. Shown before you first "Join world" (and from "Edit
// character" later): a name, a role, and a look - body, skin, hair, eyes, outfit, an accessory -
// with a live preview drawn the way LOKI World draws people (world.js's own cel shader, ink
// outlines and low-res pixel blit; the body itself is mmo_core.js's person()).
//
// The character is kept per machine by the engine: GET/POST /character (engine/character.py,
// <data>/world/character.json). Once saved, MMO.setLook() dresses your avatar in the world - in
// every renderer, since they all draw the scene description mmo_core.js fills - and the Godot
// client reads the same look as profile.look from GET /mmo/state (docs/MMO_API.md).
//
// window.LokiCharacter: ready (a promise), current, load(), open({edit, onJoin}), label(btn, kind)
"use strict";

(function () {
  // The same lists as engine/character.py OPTIONS (tests/test_character.py keeps them equal).
  const OPTIONS = {
    role: ["builder", "explorer", "artist", "scholar"],
    body: ["slim", "regular", "broad"],
    skin: ["#f6d7bf", "#e9bf9c", "#d29e76", "#a8754f", "#7d5234", "#55361f"],
    hair: ["short", "long", "spiky", "bun", "curly", "bald"],
    hair_color: ["#1d1a1f", "#4a2f22", "#8a5a33", "#d9b26a", "#c4512e", "#e8e4dc", "#5b7bd6", "#d26aa8"],
    eyes: ["round", "visor", "sleepy", "wide"],
    eye_color: ["#2b2b33", "#5a3a22", "#3f78c9", "#3f9a5a", "#2ee6d6", "#9b6ad6"],
    top: ["tunic", "jacket", "hoodie"],
    top_color: ["#3b82c4", "#2ec4b6", "#55b85c", "#e0a73a", "#d9604f", "#8b7bff", "#d26aa8", "#e8e4dc", "#3a3f4b", "#8a5a33"],
    bottom: ["trousers", "shorts", "skirt"],
    bottom_color: ["#2e3440", "#3b4a6b", "#5a4632", "#4f6b3a", "#7a2f3a", "#8a8f99", "#c9b28a"],
    accessory: ["none", "hat", "scarf"],
    accessory_color: ["#d9604f", "#e0a73a", "#2ec4b6", "#8b7bff", "#e8e4dc", "#3a3f4b"],
  };
  const NAME_MAX = 24;
  const DEFAULT = {
    role: "builder", body: "regular", skin: "#e9bf9c", hair: "short", hair_color: "#4a2f22", eyes: "round",
    eye_color: "#2b2b33", top: "tunic", top_color: "#3b82c4", bottom: "trousers", bottom_color: "#2e3440",
    accessory: "none", accessory_color: "#d9604f",
  };
  // The form, top to bottom: [field, label key, English, kind]
  const FIELDS = [
    ["body", "char.body", "Body", "choice"],
    ["skin", "char.skin", "Skin tone", "colour"],
    ["hair", "char.hair", "Hair", "choice"],
    ["hair_color", "char.hair_color", "Hair colour", "colour"],
    ["eyes", "char.eyes", "Eyes", "choice"],
    ["eye_color", "char.eye_color", "Eye colour", "colour"],
    ["top", "char.top", "Top", "choice"],
    ["top_color", "char.top_color", "Top colour", "colour"],
    ["bottom", "char.bottom", "Bottom", "choice"],
    ["bottom_color", "char.bottom_color", "Bottom colour", "colour"],
    ["accessory", "char.accessory", "Accessory", "choice"],
    ["accessory_color", "char.accessory_color", "Accessory colour", "colour"],
  ];
  // option words, and what each role means in LOKI ([key, English] pairs: tools/i18n_tables.py finds them)
  const WORDS = new Map([
    ["char.role.builder", "Builder"], ["char.role.builder_about", "Makes things real: code, apps and games, tested and shipped."],
    ["char.role.explorer", "Explorer"], ["char.role.explorer_about", "Goes out and finds things: the web, new tools, other machines' islands."],
    ["char.role.artist", "Artist"], ["char.role.artist_about", "Pictures, video, music and sketches - what LOKI makes for you to keep."],
    ["char.role.scholar", "Scholar"], ["char.role.scholar_about", "Reads, researches and remembers, so every answer has its sources."],
    ["char.body.slim", "Slim"], ["char.body.regular", "Regular"], ["char.body.broad", "Broad"],
    ["char.hair.short", "Short"], ["char.hair.long", "Long"], ["char.hair.spiky", "Spiky"], ["char.hair.bun", "Bun"],
    ["char.hair.curly", "Curly"], ["char.hair.bald", "Bald"],
    ["char.eyes.round", "Round"], ["char.eyes.visor", "Visor"], ["char.eyes.sleepy", "Sleepy"], ["char.eyes.wide", "Wide"],
    ["char.top.tunic", "Tunic"], ["char.top.jacket", "Jacket"], ["char.top.hoodie", "Hoodie"],
    ["char.bottom.trousers", "Trousers"], ["char.bottom.shorts", "Shorts"], ["char.bottom.skirt", "Skirt"],
    ["char.accessory.none", "None"], ["char.accessory.hat", "Hat"], ["char.accessory.scarf", "Scarf"],
  ]);
  const ROLE_GLYPH = { builder: "build", explorer: "globe", artist: "pen", scholar: "book" };
  const NAMES = ["Wren", "Juno", "Rook", "Nova", "Fen", "Sol", "Kit", "Ash", "Ivy", "Orin", "Pip", "Sage"];

  const tr = (key, en, vars) => (typeof uiText === "function" ? uiText(key, en, vars) : en);
  const word = (key) => tr(key, WORDS.get(key) || key);
  const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const icon = (n, name) => { if (typeof iconSvg === "function") n.insertAdjacentHTML("afterbegin", iconSvg(name)); return n; };

  let readyResolve;
  const C = window.LokiCharacter = {
    current: null, loaded: false, options: OPTIONS, NAME_MAX, DEFAULT,
    ready: new Promise((r) => { readyResolve = r; }),
  };

  // ------------------------------------------------------------------ the engine
  C.load = async function () {
    try {
      const data = await api("/character");
      if (data && data.ok) C.current = data.character || null;
    } catch (_) { /* engine not there: no character yet */ }
    C.loaded = true;
    if (window.MMO) {
      window.MMO.setLook(C.current);
      // the world view opened before we knew: join now if you were walking last time
      const M = window.MMO;
      if (C.current && M.view && !M.active && !M.save.settings.spectate) M.enter();
      if (M.refreshButtons) M.refreshButtons();
    }
    readyResolve(C.current);
    return C.current;
  };

  // the same rules as engine/character.py validate(): a plain sentence when something is wrong
  C.validate = function (c) {
    const name = String((c && c.name) || "").replace(/[\u0000-\u001f\u007f​-‏‪-‮⁦-⁩﻿]/g, "").replace(/\s+/g, " ").trim();
    if (!name) return { error: tr("char.name_empty", "Give your character a name.") };
    if (name.length > NAME_MAX) return { error: tr("char.name_long", "A name is at most {n} characters.", { n: NAME_MAX }) };
    const out = { name };
    for (const k of Object.keys(OPTIONS)) out[k] = OPTIONS[k].includes(c[k]) ? c[k] : DEFAULT[k];
    return { character: out };
  };

  async function persist(c) {
    const data = await api("/character", c);
    if (!data || !data.ok) throw new Error((data && data.error) || "no answer");
    C.current = data.character;
    const M = window.MMO;
    if (M) {
      M.setLook(C.current);
      // the role is your class in the world (the character sheet can still change it)
      const cls = M.roleClass(C.current.role);
      if (cls) { M.save.cls = cls; M.persist(); }
      api("/mmo/profile", { name: C.current.name, cls: cls || undefined }).catch(() => {});   // the Godot client's name too
    }
    return C.current;
  }

  // ------------------------------------------------------------------ the buttons on the world view
  // kind: "join" | "spectate" | "edit" - an icon, the words, and a tooltip (icons.js), translated
  C.label = function (btn, kind) {
    const spec = {
      join: ["enter", tr("world.join", "Join world"), tr("world.join_tip", "Walk your own character in LOKI World: WASD to move, drag to turn the camera, Space to jump.")],
      spectate: ["eye", tr("world.spectate", "Spectate"), tr("world.spectate_tip", "Back to the orbiting view of the island.")],
      edit: ["person", tr("world.edit", "Edit character"), tr("world.edit_tip", "Change your character's name and look.")],
    }[kind];
    if (btn.dataset.kind === kind && btn.dataset.lang === String(window.LokiI18n && window.LokiI18n.lang)) return;
    btn.dataset.kind = kind;
    btn.dataset.lang = String(window.LokiI18n && window.LokiI18n.lang);
    btn.replaceChildren(node("span", "mmo-btn-label", spec[1]));
    icon(btn, spec[0]);
    btn.dataset.tipName = spec[1];
    btn.dataset.tipWhat = spec[2];
    btn.setAttribute("aria-label", spec[1]);
    btn.removeAttribute("title");
  };

  // ------------------------------------------------------------------ the preview: LOKI World's renderer
  // world.js's own programs (cel-shaded solids, ink outlines, the dithered NEAREST blit) and meshes;
  // mmo_core.js's person() fills the scene. One small low-res target, redrawn while the creator is open.
  const Preview = {
    gl: null, canvas: null, raf: 0, yaw: 0.35, drag: null, look: null, cls: "Warrior", fb: null, failed: false, t0: 0,
    start(canvas) {
      this.canvas = canvas;
      if (!this.gl) {
        let gl = null;
        try { gl = canvas.getContext("webgl", { antialias: false, alpha: false, premultipliedAlpha: false }); } catch (_) { gl = null; }
        if (!gl || typeof makeProgram !== "function" || !window.MMO || !window.MMO.person) { this.failed = true; return false; }
        this.gl = gl;
        this.solid = makeProgram(gl, VS, FS, ["IS", "C", "E", "G", "S"].concat(LIGHT_UNIFORMS));
        this.outline = makeProgram(gl, OUTLINE_VS, OUTLINE_FS, ["M", "VP", "oeye", "OL", "OC", "ofog", "ofogr"]);
        this.blit = makeProgram(gl, BLIT_VS, BLIT_FS, ["T", "R", "VPX", "Q"]);
        if (!this.solid || !this.outline || !this.blit) { this.failed = true; return false; }
        this.meshes = {};
        for (const k of ["box", "cyl", "cyl6", "cone", "pyr", "sph", "sph4", "quad"]) this.meshes[k] = uploadMesh(gl, MESH_SRC[k]);
        this.lp = new Float32Array(30);
        this.lc = new Float32Array(40);
        for (let i = 0; i < 10; i++) this.lc[i * 4 + 3] = 1;
        this.lp.set([1.6, 2.4, 2.2], 0); this.lc.set([0.35, 0.3, 0.22, 4.5], 0);   // a warm key lamp, front left
        this.lp.set([-1.8, 1.8, -1.6], 3); this.lc.set([0.12, 0.3, 0.32, 4.0], 4);   // a teal back light, like the pool
      }
      if (!this.raf) { this.t0 = performance.now(); this.loop(); }
      return true;
    },
    stop() { if (this.raf) cancelAnimationFrame(this.raf); this.raf = 0; },
    loop() {
      this.raf = requestAnimationFrame((now) => { this.raf = 0; if (!this.canvas || !this.canvas.isConnected || this.canvas.offsetParent === null) return; this.draw(now); this.loop(); });
    },
    target(lw, lh) {
      const gl = this.gl;
      if (this.fb && this.fb.w === lw && this.fb.h === lh) return this.fb;
      if (this.fb) { gl.deleteFramebuffer(this.fb.fbo); gl.deleteTexture(this.fb.tex); gl.deleteRenderbuffer(this.fb.depth); }
      const tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, lw, lh, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      for (const [p, v] of [[gl.TEXTURE_MIN_FILTER, gl.NEAREST], [gl.TEXTURE_MAG_FILTER, gl.NEAREST], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, p, v);
      const depth = gl.createRenderbuffer();
      gl.bindRenderbuffer(gl.RENDERBUFFER, depth);
      gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT16, lw, lh);
      const fbo = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, depth);
      const ok = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      this.fb = ok ? { fbo, tex, depth, w: lw, h: lh } : null;
      return this.fb;
    },
    draw(now) {
      const gl = this.gl, canvas = this.canvas, M = window.MMO;
      if (!gl || !this.look || gl.isContextLost()) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(1, Math.round(canvas.clientWidth * dpr)), h = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      const scale = Math.max(1, Math.round(3 * dpr)), lw = Math.ceil(w / scale), lh = Math.ceil(h / scale);
      const fb = this.target(lw, lh), rw = fb ? lw : w, rh = fb ? lh : h;
      const t = (now - this.t0) / 1000, reduced = typeof World !== "undefined" && World.reduced;
      if (!this.drag && !reduced) this.yaw += 0.006;
      // the scene: a grass tuft to stand on (the island's), and you
      M.resetPools();
      const L = { solids: [], clear: [], shadows: [], glows: [], puffs: [], lights: [] };
      M.draw.put(L, "cyl", 0, -0.06, 0, 0, 1.7, 0.14, 1.7, GRASS, 0, true);
      M.draw.put(L, "cyl", 0, -0.24, 0, 0, 1.5, 0.22, 1.5, EARTH, 0, true);
      M.person(L, 0, 0.02, 0, 0, this.look, this.cls, reduced ? 0 : t * 2, false, "", 0, 1, 1, false);
      const target = [0, 0.78, 0], dist = 3.4, pitch = 0.16;
      const eye = [Math.sin(this.yaw) * Math.cos(pitch) * dist, target[1] + Math.sin(pitch) * dist, Math.cos(this.yaw) * Math.cos(pitch) * dist];
      const fov = 0.62, vp = M4.mul(M4.persp(fov, w / h, 0.3, 30), M4.lookAt(eye, target, [0, 1, 0]));
      const F = { vp, eye, sunDir: SUN, P: PAL, fogr: [40, 80], lp: this.lp, lc: this.lc, t };
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb ? fb.fbo : null);
      gl.viewport(0, 0, rw, rh);
      gl.disable(gl.BLEND); gl.depthMask(true);
      gl.clearColor(BG[0], BG[1], BG[2], 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE);
      // ink outlines: inflated back faces, as world.js draws them
      gl.cullFace(gl.FRONT);
      let { prog, loc } = this.outline;
      gl.useProgram(prog);
      gl.uniformMatrix4fv(loc.VP, false, vp); gl.uniform3fv(loc.oeye, eye);
      gl.uniform1f(loc.OL, 1.15 * 2 * Math.tan(fov / 2) / rh);
      gl.uniform3fv(loc.ofog, PAL.fog); gl.uniform2fv(loc.ofogr, F.fogr);
      for (const o of L.solids) {
        if (o.line === false) continue;
        const m = this.meshes[o.mesh];
        bindMesh(gl, loc, m);
        gl.uniformMatrix4fv(loc.M, false, M4.trs(o.pos, o.ry, o.s));
        gl.uniform3fv(loc.OC, mix3(INK, o.color, 0.22));
        gl.drawArrays(gl.TRIANGLES, 0, m.count);
      }
      // cel-shaded solids
      gl.cullFace(gl.BACK);
      ({ prog, loc } = this.solid);
      gl.useProgram(prog);
      setLighting(gl, loc, F);
      for (const o of L.solids) {
        const m = this.meshes[o.mesh];
        bindMesh(gl, loc, m);
        gl.uniformMatrix4fv(loc.M, false, M4.trs(o.pos, o.ry, o.s));
        gl.uniform3f(loc.IS, 1 / (o.s[0] * o.s[0]), 1 / (o.s[1] * o.s[1]), 1 / (o.s[2] * o.s[2]));
        gl.uniform3fv(loc.C, o.color); gl.uniform1f(loc.A, 1); gl.uniform1f(loc.E, o.e || 0);
        gl.uniform1f(loc.G, o.g || 0); gl.uniform1f(loc.S, o.s2 || 0.3);
        gl.drawArrays(gl.TRIANGLES, 0, m.count);
      }
      // the low-res picture blown up: NEAREST, whole-number scale, dithered (world.js's blit)
      if (fb) {
        ({ prog, loc } = this.blit);
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        gl.viewport(0, 0, lw * scale, lh * scale);
        gl.disable(gl.DEPTH_TEST);
        gl.useProgram(prog);
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, fb.tex);
        gl.uniform1i(loc.T, 0);
        gl.uniform2f(loc.R, lw, lh); gl.uniform2f(loc.VPX, lw * scale, lh * scale); gl.uniform1f(loc.Q, 32);
        bindMesh(gl, loc, this.meshes.quad);
        gl.drawArrays(gl.TRIANGLES, 0, this.meshes.quad.count);
      }
    },
  };
  const GRASS = [0.36, 0.62, 0.36], EARTH = [0.42, 0.3, 0.22], INK = [0.03, 0.03, 0.1], BG = [0.16, 0.18, 0.23];
  const SUN = [0.42, 0.78, 0.46];
  // a late-afternoon palette between world.js's NIGHT and DAY, so the colours read true
  const PAL = typeof DAY !== "undefined" ? (() => { const p = {}; for (const k of Object.keys(DAY)) p[k] = Array.isArray(DAY[k]) ? mix3(NIGHT[k], DAY[k], 0.8) : DAY[k]; return p; })() : null;

  // ------------------------------------------------------------------ the dialog
  let dlg = null, draft = null, opts = {}, ui = {};

  function pickRandom(list) { return list[Math.floor(Math.random() * list.length)]; }
  function randomize() {
    for (const k of Object.keys(OPTIONS)) draft[k] = pickRandom(OPTIONS[k]);
    if (Math.random() < 0.5) draft.accessory = "none";
    if (!String(draft.name || "").trim()) draft.name = pickRandom(NAMES);
    sync();
  }

  function radioGroup(field, values, labelOf, render) {
    const g = node("div", "char-choices u-arrows");
    g.setAttribute("role", "radiogroup");
    g.dataset.field = field;
    for (const v of values) {
      const b = node("button", "char-choice u-arrow-item");
      b.type = "button";
      b.setAttribute("role", "radio");
      b.dataset.value = v;
      render(b, v);
      const name = labelOf(v);
      b.setAttribute("aria-label", name);
      b.dataset.tipName = name;
      b.addEventListener("click", () => { draft[field] = v; sync(); });
      g.append(b);
    }
    return g;
  }

  function build() {
    const A = window.LokiA11y;
    if (!A || !A.LokiDialog) return null;
    const d = A.LokiDialog("character-dialog", "char.title_new", "Create your character", {
      cls: "char-dialog", wide: true, focus: "#char-name",
      onClose() { Preview.stop(); },
    });
    const body = d.body;
    body.replaceChildren();
    const grid = node("div", "char-grid");
    // left: the preview, turn buttons, randomize
    const left = node("div", "char-left");
    const stage = node("div", "char-stage");
    const canvas = node("canvas", "char-canvas");
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "img");
    ui.canvas = canvas;
    const nope = node("p", "note char-nope");
    nope.hidden = true;
    ui.nope = nope;
    canvas.addEventListener("pointerdown", (e) => { Preview.drag = { x: e.clientX, yaw: Preview.yaw }; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener("pointermove", (e) => { if (Preview.drag) Preview.yaw = Preview.drag.yaw - (e.clientX - Preview.drag.x) * 0.012; });
    const end = () => { Preview.drag = null; };
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);
    canvas.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { Preview.yaw -= 0.3; e.preventDefault(); }
      else if (e.key === "ArrowRight") { Preview.yaw += 0.3; e.preventDefault(); }
    });
    const nameplate = node("div", "char-plate");
    ui.plateName = node("b");
    ui.plateRole = node("span");
    nameplate.append(ui.plateName, ui.plateRole);
    stage.append(canvas, nameplate, nope);
    const turns = node("div", "char-turns");
    ui.turnL = node("button", "char-icon");
    ui.turnL.type = "button";
    ui.turnL.textContent = "↺";
    ui.turnL.addEventListener("click", () => { Preview.yaw -= 0.6; });
    ui.turnR = node("button", "char-icon");
    ui.turnR.type = "button";
    ui.turnR.textContent = "↻";
    ui.turnR.addEventListener("click", () => { Preview.yaw += 0.6; });
    ui.random = node("button", "char-random");
    ui.random.type = "button";
    ui.random.id = "char-randomize";
    ui.random.addEventListener("click", randomize);
    turns.append(ui.turnL, ui.random, ui.turnR);
    ui.hint = node("p", "note char-hint");
    left.append(stage, turns, ui.hint);
    // right: name, role, the look
    const right = node("div", "char-form");
    ui.nameLabel = node("label", "char-label");
    ui.nameLabel.htmlFor = "char-name";
    ui.name = node("input", "char-name");
    ui.name.id = "char-name";
    ui.name.type = "text";
    ui.name.maxLength = NAME_MAX;
    ui.name.autocomplete = "off";
    ui.name.spellcheck = false;
    ui.name.addEventListener("input", () => { draft.name = ui.name.value; ui.err.textContent = ""; sync(true); });
    ui.name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } });
    ui.roleLabel = node("div", "char-label");
    ui.roleLabel.id = "char-role-label";
    const roles = radioGroup("role", OPTIONS.role, (v) => word("char.role." + v), (b, v) => {
      b.classList.add("char-role");
      const head = node("span", "char-role-head");
      icon(head, ROLE_GLYPH[v]);
      head.append(node("b", "", word("char.role." + v)));
      b.append(head, node("span", "char-role-about", word("char.role." + v + "_about")));
    });
    roles.setAttribute("aria-labelledby", "char-role-label");
    ui.groups = { role: roles };
    right.append(ui.nameLabel, ui.name, ui.roleLabel, roles);
    ui.rowLabels = {};
    const rows = node("div", "char-rows");
    for (const [field, key, en, kind] of FIELDS) {
      const row = node("div", "char-row");
      const lab = node("div", "char-label");
      lab.id = "char-" + field + "-label";
      ui.rowLabels[field] = [lab, key, en];
      const g = kind === "colour"
        ? radioGroup(field, OPTIONS[field], (v) => tr("char.swatch", "Colour {n}", { n: OPTIONS[field].indexOf(v) + 1 }), (b, v) => {
          b.classList.add("char-swatch");
          b.style.setProperty("--sw", v);
        })
        : radioGroup(field, OPTIONS[field], (v) => word("char." + field + "." + v), (b, v) => { b.textContent = word("char." + field + "." + v); });
      g.setAttribute("aria-labelledby", lab.id);
      ui.groups[field] = g;
      row.append(lab, g);
      rows.append(row);
    }
    right.append(rows);
    grid.append(left, right);
    // the foot: what went wrong, and Join world
    const foot = node("div", "char-foot");
    ui.err = node("p", "char-err");
    ui.err.setAttribute("role", "alert");
    ui.join = node("button", "primary char-join");
    ui.join.type = "button";
    ui.join.id = "char-join";
    ui.join.addEventListener("click", submit);
    foot.append(ui.err, ui.join);
    body.append(grid, foot);
    document.addEventListener("loki:language", () => { if (d.isOpen) texts(); });
    return d;
  }

  // every word in the dialog, in the current language
  function texts() {
    const editing = !!opts.edit;
    dlg.title.dataset.i18n = editing ? "char.title_edit" : "char.title_new";
    dlg.title.textContent = editing ? tr("char.title_edit", "Edit your character") : tr("char.title_new", "Create your character");
    ui.canvas.setAttribute("aria-label", tr("char.preview", "Your character, as LOKI World draws it"));
    ui.nope.textContent = tr("char.no_preview", "This window cannot draw 3D, so there is no preview - your choices still apply.");
    ui.hint.textContent = tr("char.turn_hint", "Drag the picture, or focus it and use the arrow keys, to turn your character.");
    for (const [b, key, en] of [[ui.turnL, "char.turn_left", "Turn left"], [ui.turnR, "char.turn_right", "Turn right"]]) {
      const s = tr(key, en); b.setAttribute("aria-label", s); b.dataset.tipName = s;
    }
    const rnd = tr("char.randomize", "Randomize");
    ui.random.replaceChildren(node("span", "", rnd));
    icon(ui.random, "dice");
    ui.random.dataset.tipName = rnd;
    ui.random.dataset.tipWhat = tr("char.randomize_tip", "A random look. Your name stays.");
    ui.nameLabel.textContent = tr("char.name", "Name");
    ui.roleLabel.textContent = tr("char.role", "Role");
    for (const [lab, key, en] of Object.values(ui.rowLabels)) lab.textContent = tr(key, en);
    const live = window.MMO && window.MMO.active;
    const words = live ? tr("char.save", "Save") : tr("world.join", "Join world");
    ui.join.replaceChildren(node("span", "", words));
    icon(ui.join, live ? "check" : "enter");
    ui.join.dataset.tipName = words;
    ui.join.dataset.tipWhat = live ? tr("world.edit_tip", "Change your character's name and look.")
      : tr("world.join_tip", "Walk your own character in LOKI World: WASD to move, drag to turn the camera, Space to jump.");
  }

  // the form shows the draft; the preview draws it
  function sync(fromName) {
    if (!fromName && ui.name.value !== draft.name) ui.name.value = draft.name || "";
    for (const [field, g] of Object.entries(ui.groups)) {
      for (const b of g.children) {
        const on = b.dataset.value === draft[field];
        b.setAttribute("aria-checked", on ? "true" : "false");
        b.tabIndex = on ? 0 : -1;
      }
    }
    const acc = draft.accessory !== "none";
    ui.groups.accessory_color.closest(".char-row").classList.toggle("off", !acc);
    ui.plateName.textContent = String(draft.name || "").trim() || "…";
    ui.plateRole.textContent = "<" + word("char.role." + draft.role) + ">";
    if (window.MMO && window.MMO.lookOf) {
      Preview.look = window.MMO.lookOf(Object.assign({}, draft, { name: draft.name || "?" }));
      Preview.cls = window.MMO.roleClass(draft.role) || "Warrior";
    }
  }

  async function submit() {
    const v = C.validate(draft);
    if (v.error) { ui.err.textContent = v.error; ui.name.focus(); return; }
    ui.join.disabled = true;
    ui.err.textContent = tr("char.saving", "Saving...");
    try {
      await persist(v.character);
      ui.err.textContent = "";
      const done = opts.onJoin;
      dlg.hide("saved");
      if (typeof done === "function") done(C.current);
    } catch (err) {
      ui.err.textContent = tr("char.failed", "Could not save: {error}", { error: String((err && err.message) || err) });
    } finally {
      ui.join.disabled = false;
    }
  }

  C.open = function (o) {
    opts = o || {};
    if (!dlg) dlg = build();
    if (!dlg) return false;
    const base = C.current || Object.assign({}, DEFAULT, { name: (window.MMO && window.MMO.save && window.MMO.save.name) || "" });
    draft = Object.assign({}, DEFAULT, base);
    ui.err.textContent = "";
    texts();
    sync();
    dlg.open();
    const ok = Preview.start(ui.canvas);
    ui.nope.hidden = ok;
    ui.canvas.hidden = !ok;
    return true;
  };
  C.isOpen = function () { return !!(dlg && dlg.isOpen); };

  // LOKI World as the Godot client (Settings > General > LOKI World look = godot): it has no
  // in-app Join button, so opening the LOKI World tab with no character opens the creator first
  document.addEventListener("click", (e) => {
    const tab = e.target && e.target.closest && e.target.closest('button[data-tab="world"], #mode-world');
    if (!tab || C.current || !C.loaded || C.isOpen()) return;
    // one character for LOKI everywhere: the creator saves it to /mmo/profile, which the Godot game reads
    if (typeof World !== "undefined" && World.game === "godot") C.open({ edit: false });
  });

  // load once the engine answers (app.js calls afterStart; chain onto it, as world.js does)
  const previous = window.afterStart;
  window.afterStart = function () {
    if (typeof previous === "function") previous();
    C.load();
  };
})();
