// LOKI World as an MMO - the core (hordes.io-style, in LOKI World's own pixel cel-shaded look).
//
// world.js keeps the island, the agents and the renderers. This adds YOU: your own character,
// walked with WASD while the mouse turns the camera, standing on the island of the machine you
// are on (each device's island is a zone, joined by the bridges of light). The other files:
//   mmo_game.js  agents as NPCs with levels and classes, jobs as quests, failed jobs as monsters,
//                combat with skills / cooldowns / damage numbers, loot = what LOKI made
//   mmo_hud.js   the MMO screen: unit frames, party, target, minimap, chat, hotbar, cast bar,
//                bags, character sheet, quest log, loot window, banners
//   mmo_net.js   the other machines' avatars, live (POST /world/presence, engine/presence.py)
//
// Hooks world.js calls on the Settings > LOKI World view: tick(view, dt, now) before the camera,
// scene(L, ...) to add what the MMO draws to the frame's scene description, decorate()/labels()
// for nameplates, click()/interact() for the mouse, onWorld(data) after each GET /world.
//
// Smooth: everything the MMO draws each frame comes from pools of objects made once (put(),
// glowAt(), ...), so a frame allocates nothing here; the DOM HUD updates a few times a second.
"use strict";

(function () {
  const STORE_KEY = "loki.mmo.v1";
  const SPEED = 3.4, JUMP = 4.4, GRAVITY = 13, R_PLAYER = 0.28;

  // ------------------------------------------------------------------ classes
  const CLASSES = {
    Warrior: { color: "#d9604f", glyph: "⚔", hat: "helm", weapon: "sword", about: "Front line. Strikes hard, shrugs off hits." },
    Mage: { color: "#8b7bff", glyph: "✦", hat: "wizard", weapon: "staff", about: "Bolts from afar; the arcane does the work." },
    Archer: { color: "#55b85c", glyph: "➶", hat: "hood", weapon: "bow", about: "Quick and precise at range." },
    Shaman: { color: "#2ec4b6", glyph: "✺", hat: "feathers", weapon: "totem", about: "Mends wounds; spirits answer." },
  };
  // agents' classes come from their role (what they really do)
  const NPC_CLASSES = [
    [/^loki$|conductor/, "Trickster", "#2ee6d6"], [/research|hermes/, "Sage", "#3fa9ff"], [/architect/, "Arcanist", "#b46cff"],
    [/browser/, "Scout", "#4d7cff"], [/test/, "Alchemist", "#ffc23d"], [/review/, "Paladin", "#ff7a45"],
    [/build|loki agent|claude|codex|opencode|openhands|agent/, "Smith", "#36e07a"],
  ];
  function npcClass(role) {
    const r = String(role || "").toLowerCase();
    for (const [re, name, color] of NPC_CLASSES) if (re.test(r)) return { name, color };
    return { name: "Adventurer", color: "#9aa0aa" };
  }

  // ------------------------------------------------------------------ levels
  function xpToNext(level) { return Math.round(80 * Math.pow(level, 1.55)); }
  function levelOf(xp) {
    let lvl = 1, left = Math.max(0, xp || 0);
    while (lvl < 99 && left >= xpToNext(lvl)) { left -= xpToNext(lvl); lvl++; }
    return { level: lvl, into: left, need: xpToNext(lvl) };
  }

  // ------------------------------------------------------------------ saved progress (this machine)
  function loadSave() {
    let s = null;
    try { const raw = window.localStorage && localStorage.getItem(STORE_KEY); s = raw ? JSON.parse(raw) : null; } catch (_) { s = null; }
    s = s && typeof s === "object" ? s : {};
    s.name = typeof s.name === "string" && s.name.trim() ? s.name.slice(0, 24) : "Mohamed";
    s.cls = CLASSES[s.cls] ? s.cls : "";
    s.xp = Number(s.xp) || 0;
    for (const k of ["turnedIn", "slain", "seenCreations", "doneSeen", "roleXp", "quests"]) if (!s[k] || typeof s[k] !== "object") s[k] = {};
    if (!Array.isArray(s.scrolls)) s.scrolls = [];
    s.stats = Object.assign({ quests: 0, kills: 0, deaths: 0, casts: 0, loot: 0, jobs: 0, played: 0 }, s.stats || {});
    s.settings = Object.assign({ sound: true, fastDay: false, spectate: false, nameplates: true }, s.settings || {});
    return s;
  }

  const MMO = window.MMO = {
    active: false, view: null, save: loadSave(), CLASSES, npcClass, xpToNext, levelOf,
    player: { x: 0.6, z: 3.6, y: 0, vy: 0, ry: Math.PI, zone: "", hp: 100, en: 100, walking: false, phase: 0,
      emote: "", emoteAt: 0, dead: false, deadAt: 0, combatAt: 0, travel: null, bridgeCool: "", baseY: 0 },
    camTarget: [0.6, 1.1, 3.6], target: null, keys: {}, systems: [], dirtySave: false, savedAt: 0,
    zones: { list: [] },
  };

  MMO.persist = function () { MMO.dirtySave = true; };
  function flushSave(now) {
    if (!MMO.dirtySave || now - MMO.savedAt < 2500) return;
    MMO.dirtySave = false; MMO.savedAt = now;
    try { localStorage.setItem(STORE_KEY, JSON.stringify(MMO.save)); } catch (_) { /* private mode: progress lives this session */ }
  }

  MMO.myClass = function () {
    if (!MMO.save.cls && MMO.look && ROLE_CLASS[MMO.look.role]) return ROLE_CLASS[MMO.look.role];
    if (!MMO.save.cls) {   // first time: the Mac is a Mage, the PC a Warrior (change it on the character sheet)
      const self = (hasWorld() && World.data && World.data.self) || {};
      if (!self.name) return "Warrior";   // not known yet: do not save a guess
      MMO.save.cls = /darwin|mac/i.test((self.os || "") + (self.name || "")) ? "Mage" : /win/i.test(self.os || "") ? "Warrior" : "Shaman";
    }
    return MMO.save.cls;
  };
  const STATS = { level: 1, into: 0, need: 80, hpMax: 102, enMax: 100, xp: -1 };
  MMO.stats = function () {   // called every frame: recomputed only when the XP changed
    if (STATS.xp !== MMO.save.xp) {
      const L = levelOf(MMO.save.xp);
      STATS.xp = MMO.save.xp; STATS.level = L.level; STATS.into = L.into; STATS.need = L.need; STATS.hpMax = 90 + L.level * 12;
    }
    return STATS;
  };
  // world.js's World is a top-level const: shared between scripts, but not a property of window
  function hasWorld() { return typeof World !== "undefined"; }
  MMO.selfName = function () { const s = hasWorld() && World.data && World.data.self; return (s && s.name) || "this computer"; };

  // ------------------------------------------------------------------ sound: WebAudio beeps, no files
  const Sound = MMO.sound = {
    ctx: null,
    init() {
      if (this.ctx) return this.ctx;
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      try { this.ctx = new AC(); } catch (_) { this.ctx = null; }
      return this.ctx;
    },
    tone(freq, start, dur, type, vol, slide) {
      const ctx = this.ctx;
      const o = ctx.createOscillator(), g = ctx.createGain(), t0 = ctx.currentTime + start;
      o.type = type || "square"; o.frequency.setValueAtTime(freq, t0);
      if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(20, slide), t0 + dur);
      g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(vol || 0.05, t0 + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      o.connect(g); g.connect(ctx.destination); o.start(t0); o.stop(t0 + dur + 0.02);
    },
    play(name) {
      if (!MMO.save.settings.sound || !this.init()) return;
      if (this.ctx.state === "suspended") { try { this.ctx.resume(); } catch (_) { /* needs a click first */ } }
      const T = (f, s, d, ty, v, sl) => this.tone(f, s, d, ty, v, sl);
      switch (name) {
        case "hit": T(180, 0, 0.09, "square", 0.05, 90); break;
        case "crit": T(260, 0, 0.07, "square", 0.06, 120); T(520, 0.05, 0.1, "square", 0.04, 200); break;
        case "hurt": T(120, 0, 0.14, "sawtooth", 0.05, 60); break;
        case "cast": T(440, 0, 0.18, "triangle", 0.035, 880); break;
        case "bolt": T(900, 0, 0.16, "sawtooth", 0.03, 300); break;
        case "heal": [523, 659, 784].forEach((f, i) => T(f, i * 0.06, 0.16, "triangle", 0.04)); break;
        case "quest": [392, 523, 659].forEach((f, i) => T(f, i * 0.09, 0.2, "triangle", 0.05)); break;
        case "complete": [523, 659, 784, 1046].forEach((f, i) => T(f, i * 0.08, 0.22, "square", 0.035)); break;
        case "level": [392, 494, 587, 784, 988, 1175].forEach((f, i) => T(f, i * 0.085, 0.3, "square", 0.04)); T(1568, 0.55, 0.6, "triangle", 0.04); break;
        case "loot": T(1318, 0, 0.08, "triangle", 0.04); T(1760, 0.07, 0.14, "triangle", 0.04); break;
        case "chat": T(880, 0, 0.05, "sine", 0.03); break;
        case "error": T(150, 0, 0.12, "square", 0.04); T(110, 0.1, 0.16, "square", 0.04); break;
        case "death": [392, 330, 262, 196].forEach((f, i) => T(f, i * 0.16, 0.3, "triangle", 0.05)); break;
        case "aggro": T(220, 0, 0.12, "sawtooth", 0.04, 330); break;
        case "jump": T(330, 0, 0.1, "sine", 0.03, 520); break;
        case "zone": [262, 392, 523].forEach((f, i) => T(f, i * 0.14, 0.4, "triangle", 0.035)); break;
        case "click": T(660, 0, 0.03, "square", 0.02); break;
        default: break;
      }
    },
  };

  // ------------------------------------------------------------------ zones: each device's island
  // The same maths as world.js sceneList, so you walk exactly where the islands are drawn.
  MMO.refreshZones = function () {
    const d = World.data || {}, self = d.self || {};
    const machines = (d.machines || []).filter((m) => m.name !== self.name).slice(0, 6);
    const slots = machineSlots(machines.map((m) => m.name));
    MMO.zones.list = machines.map((m, i) => {
      const isl = machineIsland(m.name, slots[m.name]);
      const dir = norm([isl.cx, 0, isl.cz]);
      const hx = isl.cx + Math.cos(isl.ang + 0.6) * isl.R * 0.35, hz = isl.cz + Math.sin(isl.ang + 0.6) * isl.R * 0.35;
      const bx = isl.cx - Math.cos(isl.ang + 0.6) * isl.R * 0.3, bz = isl.cz - Math.sin(isl.ang + 0.6) * isl.R * 0.3;
      return { name: m.name, ok: !!m.ok, i, cx: isl.cx, cz: isl.cz, y0: isl.y, R: isl.R, dir, lift: 1.6 + Math.abs(isl.y) * 0.3,
        a0: [dir[0] * (ISLAND - 0.3), 0.3, dir[2] * (ISLAND - 0.3)], colliders: [{ x: hx, z: hz, r: 0.95 }, { x: bx, z: bz, r: 0.3 }] };
    });
  };
  MMO.zone = function (name) {
    if (!name) return null;
    for (const z of MMO.zones.list) if (z.name === name) return z;
    return null;
  };
  MMO.zoneY = function (z, t) { return z.y0 + (World.reduced ? 0 : Math.sin(t * 0.5 + z.i) * 0.15); };
  // a machine-neutral place: which island, and where on it as a fraction of its radius
  MMO.toZoneUV = function (out) {
    const p = MMO.player, z = MMO.zone(p.zone);
    if (z) { out.zone = z.name; out.u = (p.x - z.cx) / z.R; out.v = (p.z - z.cz) / z.R; }
    else { out.zone = MMO.selfName(); out.u = p.x / ISLAND; out.v = p.z / ISLAND; }
    return out;
  };
  // ...and back to this machine's sky (null when that island is not in it)
  MMO.fromZoneUV = function (zone, u, v, t, out) {
    if (!zone || zone === MMO.selfName()) { out[0] = u * ISLAND; out[1] = 0; out[2] = v * ISLAND; return out; }
    const z = MMO.zone(zone);
    if (!z) return null;
    out[0] = z.cx + u * z.R; out[1] = MMO.zoneY(z, t); out[2] = z.cz + v * z.R;
    return out;
  };

  // ------------------------------------------------------------------ the island's solid things
  let HOME_COLLIDERS = null;
  function homeColliders() {
    if (HOME_COLLIDERS) return HOME_COLLIDERS;
    const c = [{ x: 0, z: 0, r: 1.85 }];   // the pool and LOKI's spire
    for (const [name] of Object.entries(STATION_LAYOUT)) {
      if (name === "hall") continue;
      const f = stationFrame(name);
      c.push({ x: f.x + f.u[0] * 2.1, z: f.z + f.u[1] * 2.1, r: 1.05 });   // the little building
      c.push({ x: f.x, z: f.z, r: 0.62 });                                    // the desk
      c.push({ x: f.x - f.u[1] * 1.0 + f.u[0] * 0.6, z: f.z + f.u[0] * 1.0 + f.u[1] * 0.6, r: 0.14 });   // lamp post
      if (name === "library") c.push({ x: f.x + f.tg[0] * 1.35 + f.u[0] * 0.4, z: f.z + f.tg[1] * 1.35 + f.u[1] * 0.4, r: 0.5 });
    }
    for (const t of SCENERY.trees) c.push({ x: t.x, z: t.z, r: 0.22 });
    for (const r of SCENERY.rocks) c.push({ x: r.x, z: r.z, r: r.s * 0.5 });
    for (const l of SCENERY.lamps) c.push({ x: l.x, z: l.z, r: 0.12 });
    for (const b of SCENERY.benches) c.push({ x: b.x, z: b.z, r: 0.42 });
    if (SCENERY.fall) c.push({ x: SCENERY.fall.x, z: SCENERY.fall.z, r: 0.92 });
    const g = SCENERY.gallery;
    if (g) {
      const face = Math.atan2(-g.x, -g.z), fx = Math.sin(face), fz = Math.cos(face), sx = Math.cos(face), sz = -Math.sin(face);
      for (const u of [-1.3, -0.45, 0.45, 1.3]) c.push({ x: g.x + sx * u - fx * 0.85, z: g.z + sz * u - fz * 0.85, r: 0.45 });
      for (const u of [-1.6, 1.6]) c.push({ x: g.x + sx * u + fx * 0.2, z: g.z + sz * u + fz * 0.2, r: 0.16 });
    }
    HOME_COLLIDERS = c;
    return c;
  }
  function pushOut(p, list) {
    for (let i = 0; i < list.length; i++) {
      const c = list[i], dx = p.x - c.x, dz = p.z - c.z, d = Math.hypot(dx, dz), min = c.r + R_PLAYER;
      if (d < min) {
        if (d < 0.0001) { p.x += min; continue; }
        p.x = c.x + dx / d * min; p.z = c.z + dz / d * min;
      }
    }
  }
  MMO.homeColliders = homeColliders;
  MMO.pushOut = pushOut;

  // ------------------------------------------------------------------ pools (no garbage per frame)
  const SOL = [], SHD = [], GLW = [], LIT = [];
  let nS = 0, nH = 0, nG = 0, nL = 0;
  function resetPools() { nS = 0; nH = 0; nG = 0; nL = 0; }
  function put(L, mesh, x, y, z, ry, sx, sy, sz, c, e, line) {
    let o = SOL[nS];
    if (!o) o = SOL[nS] = { mesh: "box", pos: [0, 0, 0], ry: 0, s: [1, 1, 1], color: [1, 1, 1], e: 0, line: true, s2: 0.3, g: 0, a: 1 };
    nS++;
    o.mesh = mesh; o.pos[0] = x; o.pos[1] = y; o.pos[2] = z; o.ry = ry;
    o.s[0] = sx; o.s[1] = sy; o.s[2] = sz; o.color[0] = c[0]; o.color[1] = c[1]; o.color[2] = c[2];
    o.e = e || 0; o.line = line !== false;
    L.solids.push(o);
    return o;
  }
  function shadowAt(L, x, z, r, a) {
    let o = SHD[nH];
    if (!o) o = SHD[nH] = { x: 0, z: 0, r: 1, a: 0.5 };
    nH++;
    o.x = x; o.z = z; o.r = r; o.a = Math.min(1, a * 1.3);
    L.shadows.push(o);
  }
  function glowAt(L, x, y, z, r, c, a) {
    let o = GLW[nG];
    if (!o) o = GLW[nG] = { pos: [0, 0, 0], r: 1, color: [1, 1, 1], a: 1 };
    nG++;
    o.pos[0] = x; o.pos[1] = y; o.pos[2] = z; o.r = r; o.color[0] = c[0]; o.color[1] = c[1]; o.color[2] = c[2]; o.a = a;
    L.glows.push(o);
  }
  function lightAt(L, x, y, z, c, radius, pri) {
    let o = LIT[nL];
    if (!o) o = LIT[nL] = { pos: [0, 0, 0], color: [1, 1, 1], radius: 2, pri: 1 };
    nL++;
    o.pos[0] = x; o.pos[1] = y; o.pos[2] = z; o.color[0] = c[0]; o.color[1] = c[1]; o.color[2] = c[2]; o.radius = radius; o.pri = pri || 1;
    L.lights.push(o);
  }
  function ring(L, x, y, z, r, c, spin, e) {   // a dashed ring on the ground, like the selected agent's
    for (let k = 0; k < 10; k++) {
      const an = spin + k * Math.PI / 5;
      put(L, "box", x + Math.cos(an) * r, y + 0.1, z + Math.sin(an) * r, -an, 0.2, 0.05, 0.08, c, e, false);
    }
  }
  MMO.draw = { put, shadowAt, glowAt, lightAt, ring };

  // scratch colours, written in place
  const CA = [0, 0, 0], CB = [0, 0, 0], CC = [0, 0, 0], CD = [0, 0, 0], CE = [0, 0, 0];
  function shade(out, c, k, add) { out[0] = Math.min(1, c[0] * k + add); out[1] = Math.min(1, c[1] * k + add); out[2] = Math.min(1, c[2] * k + add); return out; }
  const STEEL = [0.72, 0.74, 0.82], WOOD = [0.5, 0.32, 0.2], DARK = [0.06, 0.06, 0.1], PLUME = [0.95, 0.25, 0.25], GOLD = [1, 0.84, 0.3];
  const ORB = [0.75, 0.6, 1], TEAL = [0.25, 0.95, 0.85], LEAF = [0.3, 0.75, 0.35], VISOR = [0.6, 0.98, 1.0];
  const FEATHERS = [[1, 0.5, 0.3], [0.3, 0.9, 1], [1, 0.9, 0.3]];

  // the class weapon in the right hand (avatar() and person() share it)
  function weapon(L, k, ax, ay, az, fx, fz, ry, big, alpha) {
    if (k.weapon === "sword") {
      put(L, "box", ax + fx * 0.05, ay + 0.3 * big, az + fz * 0.05, ry, 0.05 * big, 0.5 * big, 0.09 * big, STEEL, 0.15, true);
      put(L, "box", ax + fx * 0.05, ay + 0.06 * big, az + fz * 0.05, ry, 0.08 * big, 0.04 * big, 0.22 * big, GOLD, 0.2, false);
    } else if (k.weapon === "staff") {
      put(L, "cyl6", ax + fx * 0.04, ay + 0.2 * big, az + fz * 0.04, 0, 0.05 * big, 1.05 * big, 0.05 * big, WOOD, 0, true);
      put(L, "sph4", ax + fx * 0.04, ay + 0.76 * big, az + fz * 0.04, 0, 0.14 * big, 0.14 * big, 0.14 * big, ORB, 1.0, false);
      glowAt(L, ax + fx * 0.04, ay + 0.76 * big, az + fz * 0.04, 0.38 * big, ORB, 0.7 * alpha);
    } else if (k.weapon === "bow") {
      put(L, "box", ax + fx * 0.08, ay + 0.12 * big, az + fz * 0.08, ry, 0.04 * big, 0.72 * big, 0.06 * big, WOOD, 0, true);
      put(L, "box", ax + fx * 0.02, ay + 0.12 * big, az + fz * 0.02, ry, 0.01, 0.64 * big, 0.01, STEEL, 0.6, false);
    } else {
      put(L, "cyl6", ax + fx * 0.04, ay + 0.12 * big, az + fz * 0.04, 0, 0.08 * big, 0.62 * big, 0.08 * big, WOOD, 0, true);
      put(L, "box", ax + fx * 0.04, ay + 0.5 * big, az + fz * 0.04, ry, 0.16 * big, 0.14 * big, 0.16 * big, TEAL, 0.6, true);
    }
  }

  // A character in the island's style (the agents' body, head and visor) with a class hat, a cape
  // and a weapon. Emotes: wave, dance, sit, cheer, bow. Feeds the pools, allocates nothing.
  function avatar(L, x, y, z, ry, col, cls, phase, walking, emote, et, big, alpha, shadowed) {
    const k = CLASSES[cls] || CLASSES.Warrior;
    let bob = walking ? Math.abs(Math.sin(phase)) * 0.12 : Math.sin(phase) * 0.02;
    let sit = 0, armL = 0, armR = 0, fwdArm = 0, lean = 0;
    if (emote === "dance") { bob = Math.abs(Math.sin(et * 7)) * 0.16; ry += Math.sin(et * 3.5) * 1.2; armL = 0.25 + Math.sin(et * 7) * 0.12; armR = 0.25 - Math.sin(et * 7) * 0.12; }
    else if (emote === "sit") sit = -0.26;
    else if (emote === "cheer") { bob = Math.abs(Math.sin(et * 9)) * 0.3; armL = armR = 0.34; }
    else if (emote === "wave") armR = 0.34 + Math.sin(et * 12) * 0.08;
    else if (emote === "bow") lean = 0.18;
    else if (emote === "attack") { fwdArm = 0.22 * Math.max(0, 1 - et * 3); armR = 0.12 * Math.max(0, 1 - et * 3); }
    else if (emote === "cast") { armL = armR = 0.22 + Math.sin(et * 16) * 0.03; fwdArm = 0.1; }
    const fx = Math.sin(ry), fz = Math.cos(ry), sx = Math.cos(ry), sz = -Math.sin(ry);
    const y0 = y + bob + sit, hy = y0 + 0.98 * big - lean * 0.5;
    if (shadowed) shadowAt(L, x + 0.06, z - 0.05, 0.42 * big, 0.7 * alpha);
    put(L, "cyl", x, y0 + 0.42 * big, z, ry, 0.42 * big, 0.62 * big, 0.42 * big, col, 0, true).s2 = 0.25;
    const hx = x + fx * lean, hz = z + fz * lean;
    put(L, "sph", hx, hy, hz, ry, 0.44 * big, 0.44 * big, 0.44 * big, shade(CA, col, 1.12, 0.05), 0, true).s2 = 0.4;
    put(L, "box", hx + fx * 0.18 * big, hy + 0.04 * big, hz + fz * 0.18 * big, ry, 0.28 * big, 0.09 * big, 0.08, VISOR, 0.45, false);
    // the cape: the class colour, swaying when you run
    const cape = k.rgb || (k.rgb = hexRgb(k.color, TEAL)), sway = walking ? Math.sin(phase * 0.5) * 0.05 : 0;
    put(L, "box", x - fx * (0.22 + sway) * big, y0 + 0.5 * big, z - fz * (0.22 + sway) * big, ry, 0.36 * big, 0.6 * big, 0.04, shade(CB, cape, 0.8, 0), 0, true);
    // feet
    for (let s = -1; s <= 1; s += 2) {
      const stride = walking ? Math.sin(phase) * s * 0.11 * big : 0, out = sit ? 0.28 * big : 0;
      put(L, "box", x + sx * s * 0.11 * big + fx * (stride + out), y + 0.05 + Math.max(0, -stride) * 0.4 + (sit ? 0.02 : 0),
        z + sz * s * 0.11 * big + fz * (stride + out), ry, 0.11 * big, 0.08 * big, 0.17 * big, shade(CC, col, 0.5, 0.025), 0, false);
    }
    // arms (+1 is the weapon hand)
    for (let s = -1; s <= 1; s += 2) {
      const swing = walking ? -Math.sin(phase) * s * 0.09 * big : 0;
      const ay = y0 + 0.55 * big + (s > 0 ? armR : armL) * big, fo = swing + (s > 0 ? fwdArm : fwdArm * 0.5) * big, so = 0.27 * big;
      const ax = x + sx * s * so + fx * fo, az = z + sz * s * so + fz * fo;
      put(L, "box", ax, ay, az, ry, 0.1 * big, 0.3 * big, 0.1 * big, shade(CD, col, 0.85, 0), 0, false);
      if (s > 0) weapon(L, k, ax, ay, az, fx, fz, ry, big, alpha);   // the weapon
    }
    // the class hat
    const hat = hy + 0.22 * big;
    if (k.hat === "helm") {
      put(L, "sph4", hx, hat - 0.08 * big, hz, ry, 0.5 * big, 0.24 * big, 0.5 * big, STEEL, 0.05, true);
      put(L, "box", hx - fx * 0.03, hat + 0.08 * big, hz - fz * 0.03, ry, 0.06 * big, 0.16 * big, 0.26 * big, PLUME, 0.15, true);
    } else if (k.hat === "wizard") {
      put(L, "cyl", hx, hat - 0.06 * big, hz, ry, 0.6 * big, 0.04 * big, 0.6 * big, shade(CE, cape, 0.7, 0), 0, true);
      put(L, "cone", hx - fx * 0.02, hat + 0.2 * big, hz - fz * 0.02, ry, 0.36 * big, 0.5 * big, 0.36 * big, shade(CE, cape, 0.7, 0), 0, true);
    } else if (k.hat === "hood") {
      put(L, "pyr", hx - fx * 0.02, hat + 0.0 * big, hz - fz * 0.02, ry + Math.PI / 4, 0.52 * big, 0.36 * big, 0.52 * big, LEAF, 0, true);
      put(L, "box", hx - fx * 0.12 + sx * 0.12, hat + 0.12 * big, hz - fz * 0.12 + sz * 0.12, ry + 0.5, 0.03, 0.26 * big, 0.06, PLUME, 0.2, false);
    } else {
      put(L, "cyl", hx, hat - 0.06 * big, hz, ry, 0.46 * big, 0.07 * big, 0.46 * big, TEAL, 0.2, true);
      for (let f = 0; f < 3; f++) {
        const off = (f - 1) * 0.12 * big;
        put(L, "box", hx + sx * off - fx * 0.1, hat + 0.14 * big + (f === 1 ? 0.06 : 0), hz + sz * off - fz * 0.1, ry, 0.05, 0.28 * big, 0.04, FEATHERS[f], 0.3, false);
      }
    }
    return hy;
  }
  MMO.avatar = avatar;
  MMO.shade = shade;

  // ------------------------------------------------------------------ your character (app/ui/character.js)
  // The look made in the character creator, kept by the engine (GET /character, engine/character.py).
  // setLook() turns it into ready colours once, so person() below allocates nothing per frame.
  const BUILD = { slim: 0.86, regular: 1, broad: 1.16 };
  const ROLE_CLASS = { builder: "Warrior", explorer: "Archer", artist: "Shaman", scholar: "Mage" };
  const ROLE_NAME = { builder: "Builder", explorer: "Explorer", artist: "Artist", scholar: "Scholar" };
  const SHOE = [0.12, 0.11, 0.14], EYE_WHITE = [0.95, 0.95, 0.97];
  MMO.look = null;
  MMO.lookOf = function (c) {   // ready colours for person(); null for no character
    if (!c || typeof c !== "object" || !c.name) return null;
    const rgb = (h, f) => hexRgb(h, f);
    return {
      name: String(c.name).slice(0, 24), role: c.role, roleName: ROLE_NAME[c.role] || "", body: c.body, bw: BUILD[c.body] || 1,
      hair: c.hair, eyes: c.eyes, top: c.top, bottom: c.bottom, accessory: c.accessory,
      skin: rgb(c.skin, [0.91, 0.75, 0.61]), hairC: rgb(c.hair_color, [0.29, 0.18, 0.13]), eyeC: rgb(c.eye_color, [0.17, 0.17, 0.2]),
      topC: rgb(c.top_color, [0.23, 0.51, 0.77]), botC: rgb(c.bottom_color, [0.18, 0.2, 0.25]), accC: rgb(c.accessory_color, [0.85, 0.38, 0.31]),
      raw: Object.assign({}, c),
    };
  };
  MMO.setLook = function (c) {
    MMO.look = MMO.lookOf(c);
    if (!MMO.look) return null;
    MMO.save.name = MMO.look.name;
    MMO.persist();
    return MMO.look;
  };
  MMO.roleClass = function (role) { return ROLE_CLASS[role] || ""; };

  // A person in the island's style (the agents' round body and head, ink outlines, cel shading),
  // dressed as the character creator says: build, skin, hair, eyes, top, bottom, an accessory.
  // The class weapon stays in the right hand (combat is the same). Feeds the pools, allocates nothing.
  function person(L, x, y, z, ry, lk, cls, phase, walking, emote, et, big, alpha, shadowed) {
    const k = CLASSES[cls] || CLASSES.Warrior, bw = lk.bw;
    let bob = walking ? Math.abs(Math.sin(phase)) * 0.12 : Math.sin(phase) * 0.02;
    let sit = 0, armL = 0, armR = 0, fwdArm = 0, lean = 0;
    if (emote === "dance") { bob = Math.abs(Math.sin(et * 7)) * 0.16; ry += Math.sin(et * 3.5) * 1.2; armL = 0.25 + Math.sin(et * 7) * 0.12; armR = 0.25 - Math.sin(et * 7) * 0.12; }
    else if (emote === "sit") sit = -0.26;
    else if (emote === "cheer") { bob = Math.abs(Math.sin(et * 9)) * 0.3; armL = armR = 0.34; }
    else if (emote === "wave") armR = 0.34 + Math.sin(et * 12) * 0.08;
    else if (emote === "bow") lean = 0.18;
    else if (emote === "attack") { fwdArm = 0.22 * Math.max(0, 1 - et * 3); armR = 0.12 * Math.max(0, 1 - et * 3); }
    else if (emote === "cast") { armL = armR = 0.22 + Math.sin(et * 16) * 0.03; fwdArm = 0.1; }
    const fx = Math.sin(ry), fz = Math.cos(ry), sx = Math.cos(ry), sz = -Math.sin(ry);
    const y0 = y + bob + sit, hy = y0 + 0.98 * big - lean * 0.5;
    const hx = x + fx * lean, hz = z + fz * lean;
    if (shadowed) shadowAt(L, x + 0.06, z - 0.05, 0.42 * big * bw, 0.7 * alpha);
    // legs and feet (trousers, or bare legs under shorts and a skirt)
    for (let s = -1; s <= 1; s += 2) {
      const stride = walking ? Math.sin(phase) * s * 0.11 * big : 0, out = sit ? 0.28 * big : 0;
      const lx = x + sx * s * 0.1 * big * bw + fx * (stride + out) * 0.5, lz = z + sz * s * 0.1 * big * bw + fz * (stride + out) * 0.5;
      put(L, "box", lx, y0 + 0.2 * big, lz, ry, 0.12 * big * bw, 0.26 * big, 0.13 * big, lk.bottom === "trousers" ? lk.botC : lk.skin, 0, false);
      put(L, "box", x + sx * s * 0.1 * big * bw + fx * (stride + out), y + 0.05 + Math.max(0, -stride) * 0.4 + (sit ? 0.02 : 0),
        z + sz * s * 0.1 * big * bw + fz * (stride + out), ry, 0.12 * big, 0.08 * big, 0.18 * big, SHOE, 0, false);
    }
    // the bottom: hips (trousers, shorts) or a flared skirt
    if (lk.bottom === "skirt") put(L, "cone", x, y0 + 0.36 * big, z, ry, 0.6 * big * bw, 0.5 * big, 0.6 * big * bw, lk.botC, 0, true);
    else put(L, "cyl", x, y0 + 0.33 * big, z, ry, 0.42 * big * bw, 0.16 * big, 0.4 * big * bw, lk.botC, 0, true);
    if (lk.bottom === "shorts") for (let s = -1; s <= 1; s += 2) {
      put(L, "box", x + sx * s * 0.1 * big * bw, y0 + 0.26 * big, z + sz * s * 0.1 * big * bw, ry, 0.14 * big * bw, 0.1 * big, 0.15 * big, lk.botC, 0, false);
    }
    // the top
    put(L, "cyl", x, y0 + 0.56 * big, z, ry, 0.44 * big * bw, 0.4 * big, 0.42 * big * bw, lk.topC, 0, true).s2 = 0.25;
    if (lk.top === "jacket") {   // open front, a lighter shirt and a collar
      put(L, "box", x + fx * 0.2 * big * bw, y0 + 0.56 * big, z + fz * 0.2 * big * bw, ry, 0.12 * big, 0.36 * big, 0.04, shade(CA, lk.topC, 0.5, 0.45), 0, false);
      put(L, "box", x, y0 + 0.75 * big, z, ry, 0.34 * big * bw, 0.06 * big, 0.36 * big * bw, shade(CB, lk.topC, 0.7, 0), 0, false);
    } else if (lk.top === "hoodie") {   // the hood down at the back, a front pocket
      put(L, "sph4", x - fx * 0.17 * big, y0 + 0.76 * big, z - fz * 0.17 * big, ry, 0.34 * big * bw, 0.16 * big, 0.2 * big, shade(CA, lk.topC, 0.85, 0), 0, true);
      put(L, "box", x + fx * 0.2 * big * bw, y0 + 0.46 * big, z + fz * 0.2 * big * bw, ry, 0.24 * big * bw, 0.1 * big, 0.04, shade(CB, lk.topC, 0.8, 0), 0, false);
    } else {   // tunic: a belt
      put(L, "cyl", x, y0 + 0.4 * big, z, ry, 0.46 * big * bw, 0.05 * big, 0.44 * big * bw, shade(CA, lk.topC, 0.45, 0.02), 0, false);
    }
    // arms: sleeves in the top's colour, hands in skin (+1 is the weapon hand)
    for (let s = -1; s <= 1; s += 2) {
      const swing = walking ? -Math.sin(phase) * s * 0.09 * big : 0;
      const ay = y0 + 0.58 * big + (s > 0 ? armR : armL) * big, fo = swing + (s > 0 ? fwdArm : fwdArm * 0.5) * big, so = (0.25 * bw + 0.03) * big;
      const ax = x + sx * s * so + fx * fo, az = z + sz * s * so + fz * fo;
      put(L, "box", ax, ay, az, ry, 0.1 * big, 0.26 * big, 0.1 * big, shade(CD, lk.topC, 0.9, 0), 0, false);
      put(L, "sph4", ax, ay - 0.15 * big, az, ry, 0.09 * big, 0.09 * big, 0.09 * big, lk.skin, 0, false);
      if (s > 0) weapon(L, k, ax, ay - 0.04 * big, az, fx, fz, ry, big, alpha);
    }
    // the scarf: round the neck, one end hanging in front
    if (lk.accessory === "scarf") {
      put(L, "cyl", x, y0 + 0.78 * big, z, ry, 0.38 * big * bw, 0.08 * big, 0.38 * big * bw, lk.accC, 0, true);
      put(L, "box", x + fx * 0.17 * big + sx * 0.08 * big, y0 + 0.66 * big, z + fz * 0.17 * big + sz * 0.08 * big, ry, 0.08 * big, 0.22 * big, 0.04, lk.accC, 0, false);
    }
    // the head and the eyes
    put(L, "sph", hx, hy, hz, ry, 0.44 * big, 0.44 * big, 0.44 * big, lk.skin, 0, true).s2 = 0.4;
    const ex = hx + fx * 0.205 * big, ez = hz + fz * 0.205 * big, eyY = hy + 0.03 * big;
    if (lk.eyes === "visor") put(L, "box", ex, eyY + 0.01 * big, ez, ry, 0.28 * big, 0.09 * big, 0.06, lk.eyeC, 0.5, false);
    else for (let s = -1; s <= 1; s += 2) {
      const px = ex + sx * s * 0.08 * big, pz = ez + sz * s * 0.08 * big;
      if (lk.eyes === "wide") {
        put(L, "box", px, eyY, pz, ry, 0.08 * big, 0.09 * big, 0.03, EYE_WHITE, 0.1, false);
        put(L, "box", px + fx * 0.012, eyY - 0.01 * big, pz + fz * 0.012, ry, 0.045 * big, 0.06 * big, 0.03, lk.eyeC, 0, false);
      } else if (lk.eyes === "sleepy") put(L, "box", px, eyY - 0.01 * big, pz, ry, 0.07 * big, 0.022 * big, 0.03, lk.eyeC, 0, false);
      else put(L, "box", px, eyY, pz, ry, 0.05 * big, 0.065 * big, 0.03, lk.eyeC, 0, false);
    }
    // hair
    const hb = hx - fx * 0.03 * big, hbz = hz - fz * 0.03 * big;
    if (lk.hair !== "bald") put(L, "sph4", hb, hy + 0.07 * big, hbz, ry, 0.47 * big, 0.34 * big, 0.47 * big, lk.hairC, 0, true);
    if (lk.hair === "long") put(L, "box", hx - fx * 0.15 * big, hy - 0.12 * big, hz - fz * 0.15 * big, ry, 0.42 * big, 0.42 * big, 0.14 * big, lk.hairC, 0, true);
    else if (lk.hair === "spiky") for (let f = -1; f <= 1; f++) {
      put(L, "cone", hb + sx * f * 0.12 * big, hy + 0.26 * big - (f ? 0.03 : 0), hbz + sz * f * 0.12 * big, ry, 0.12 * big, 0.2 * big, 0.12 * big, lk.hairC, 0, true);
    } else if (lk.hair === "bun") put(L, "sph4", hx - fx * 0.12 * big, hy + 0.24 * big, hz - fz * 0.12 * big, ry, 0.18 * big, 0.18 * big, 0.18 * big, lk.hairC, 0, true);
    else if (lk.hair === "curly") for (let f = 0; f < 5; f++) {
      const an = ry + Math.PI + (f - 2) * 0.62;
      put(L, "sph4", hx + Math.sin(an) * 0.2 * big, hy + 0.1 * big - Math.abs(f - 2) * 0.05 * big, hz + Math.cos(an) * 0.2 * big, ry, 0.17 * big, 0.17 * big, 0.17 * big, lk.hairC, 0, true);
    }
    // the hat: a brim and a crown in its colour
    if (lk.accessory === "hat") {
      put(L, "cyl", hb, hy + 0.2 * big, hbz, ry, 0.62 * big, 0.04 * big, 0.62 * big, lk.accC, 0, true);
      put(L, "cyl", hb, hy + 0.3 * big, hbz, ry, 0.4 * big, 0.18 * big, 0.4 * big, lk.accC, 0, true);
      put(L, "cyl", hb, hy + 0.24 * big, hbz, ry, 0.41 * big, 0.05 * big, 0.41 * big, shade(CE, lk.accC, 0.45, 0.02), 0, false);
    }
    return hy;
  }
  MMO.person = person;
  MMO.resetPools = resetPools;

  // ------------------------------------------------------------------ input
  const isTyping = (t) => t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
  function live() { return MMO.active && MMO.view && MMO.view.visible; }
  MMO.live = live;
  const MOVE_KEYS = { w: 1, a: 1, s: 1, d: 1, q: 1, e: 1, arrowup: 1, arrowdown: 1, arrowleft: 1, arrowright: 1, " ": 1 };
  function onKey(e) {
    if (!live()) return;
    if (MMO.sound) MMO.sound.init();
    const k = (e.key || "").toLowerCase();
    if (isTyping(e.target)) {
      if (MMO.hud && MMO.hud.typingKey(e)) { e.preventDefault(); e.stopImmediatePropagation(); }
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (MOVE_KEYS[k]) {
      MMO.keys[k] = true;
      if (k === " " && !e.repeat) jump();
      if (MMO.player.emote && k !== " ") MMO.player.emote = "";
      e.preventDefault(); e.stopImmediatePropagation();
      return;
    }
    const handled = MMO.hud && MMO.hud.hotkey(e, k);
    if (handled) { e.preventDefault(); e.stopImmediatePropagation(); }
  }
  function onKeyUp(e) {
    const k = (e.key || "").toLowerCase();
    if (MMO.keys[k]) { MMO.keys[k] = false; if (live()) e.stopImmediatePropagation(); }
  }
  function jump() {
    const p = MMO.player;
    if (p.dead || p.travel || p.y > 0.01) return;
    p.vy = JUMP; Sound.play("jump");
  }
  MMO.clearKeys = function () { for (const k of Object.keys(MMO.keys)) MMO.keys[k] = false; };

  // ------------------------------------------------------------------ movement, zones and bridges
  MMO.startTravel = function (to) {
    const p = MMO.player;
    if (p.travel || p.dead) return false;
    const from = p.zone;
    const zone = MMO.zone(to || from);
    if (!zone) return false;
    p.travel = { to: to || "", zone, u: to ? 0 : 1, dir: to ? 1 : -1 };
    p.emote = "";
    if (MMO.game) MMO.game.cancelCast("You set off over the bridge.");
    return true;
  };
  MMO.teleportHome = function () {
    const p = MMO.player, was = p.zone;
    p.zone = ""; p.travel = null; p.x = 0.6; p.z = 3.4; p.y = 0; p.vy = 0; p.ry = Math.PI;
    if (was && MMO.hud) MMO.hud.zoneBanner(MMO.selfName(), "home");
  };
  function bridgePoint(z, u, t, out) {
    const yb = MMO.zoneY(z, t) + 0.2;
    const ax = z.a0[0], ay = z.a0[1], az = z.a0[2];
    const bx = z.cx - z.dir[0] * (z.R - 0.3), bz = z.cz - z.dir[2] * (z.R - 0.3);
    out[0] = ax + (bx - ax) * u; out[1] = ay + (yb - ay) * u + Math.sin(u * Math.PI) * z.lift; out[2] = az + (bz - az) * u;
    return out;
  }
  const BP = [0, 0, 0];

  function move(dt, t) {
    const p = MMO.player, view = MMO.view, K = MMO.keys;
    // travelling a bridge of light: carried along it (S turns you back)
    if (p.travel) {
      const tr = p.travel, z = tr.zone;
      if (K.s || K.arrowdown) { tr.dir = tr.to ? -1 : 1; }
      const len = Math.hypot(z.cx - z.a0[0], z.cz - z.a0[2]) || 1;
      tr.u += tr.dir * dt * (SPEED * 1.6) / len;
      bridgePoint(z, Math.max(0, Math.min(1, tr.u)), t, BP);
      const ahead = Math.max(0, Math.min(1, tr.u + tr.dir * 0.02));
      const px = p.x, pz = p.z;
      p.x = BP[0]; p.z = BP[2]; p.baseY = BP[1] - 0.25;
      if (Math.hypot(p.x - px, p.z - pz) > 0.0001) p.ry = Math.atan2(p.x - px, p.z - pz);
      p.walking = true; p.phase += dt * 9;
      if (tr.u >= 1) {   // arrived on that machine's island
        p.travel = null; p.zone = z.name; p.bridgeCool = z.name;
        p.x = z.cx - z.dir[0] * (z.R - 1.0); p.z = z.cz - z.dir[2] * (z.R - 1.0); p.y = 0; p.vy = 0;
        if (MMO.hud) MMO.hud.zoneBanner(z.name, z.ok ? "online" : "offline");
        Sound.play("zone");
      } else if (tr.u <= 0) {   // back home
        p.travel = null; p.zone = ""; p.bridgeCool = z.name;
        p.x = z.a0[0] * 0.88; p.z = z.a0[2] * 0.88; p.y = 0; p.vy = 0;
        if (MMO.hud) MMO.hud.zoneBanner(MMO.selfName(), "home");
        Sound.play("zone");
      }
      void ahead;
      return;
    }
    let mx = 0, mz = 0;
    if (!p.dead) {
      const yaw = view.yaw, fx = -Math.cos(yaw), fz = -Math.sin(yaw), rx = Math.sin(yaw), rz = -Math.cos(yaw);
      if (K.w || K.arrowup) { mx += fx; mz += fz; }
      if (K.s || K.arrowdown) { mx -= fx; mz -= fz; }
      if (K.d) { mx += rx; mz += rz; }
      if (K.a) { mx -= rx; mz -= rz; }
      if (K.q || K.arrowleft) view.yaw -= dt * 2.2;
      if (K.e || K.arrowright) view.yaw += dt * 2.2;
    }
    const m = Math.hypot(mx, mz);
    p.walking = m > 0.01;
    if (p.walking) {
      mx /= m; mz /= m;
      const sp = SPEED * (p.slowUntil > performance.now() ? 0.5 : 1);
      p.x += mx * sp * dt; p.z += mz * sp * dt;
      p.ry = angLerp(p.ry, Math.atan2(mx, mz), Math.min(1, dt * 14));
      p.phase += dt * 10;
      if (MMO.game) MMO.game.cancelCast("Moving interrupted the cast.", true);
    } else p.phase += dt * 2;
    // jump
    if (p.y > 0 || p.vy > 0) { p.vy -= GRAVITY * dt; p.y = Math.max(0, p.y + p.vy * dt); if (p.y === 0) p.vy = 0; }
    // stay on the island, round its solid things
    const z = MMO.zone(p.zone);
    if (z) {
      p.baseY = MMO.zoneY(z, t);
      pushOut(p, z.colliders);
      const dx = p.x - z.cx, dz = p.z - z.cz, d = Math.hypot(dx, dz), lim = z.R - 0.35;
      if (d > lim) { p.x = z.cx + dx / d * lim; p.z = z.cz + dz / d * lim; }
      // the bridge home starts at this island's edge, facing your island
      const ex = z.cx - z.dir[0] * (z.R - 0.3), ez = z.cz - z.dir[2] * (z.R - 0.3), de = Math.hypot(p.x - ex, p.z - ez);
      if (p.bridgeCool === z.name && de > 1.4) p.bridgeCool = "";
      if (!p.bridgeCool && de < 0.85 && p.walking && (mx * -z.dir[0] + mz * -z.dir[2]) > 0.4) MMO.startTravel("");
    } else {
      p.zone = ""; p.baseY = 0;
      pushOut(p, homeColliders());
      const d = Math.hypot(p.x, p.z), lim = ISLAND - 0.35;
      if (d > lim) { p.x = p.x / d * lim; p.z = p.z / d * lim; }
      for (const zz of MMO.zones.list) {   // a bridge of light starts here: walk onto it
        const de = Math.hypot(p.x - zz.a0[0], p.z - zz.a0[2]);
        if (p.bridgeCool === zz.name && de > 1.4) p.bridgeCool = "";
        if (!p.bridgeCool && de < 0.9 && p.walking && (mx * zz.dir[0] + mz * zz.dir[2]) > 0.4) { MMO.startTravel(zz.name); break; }
      }
    }
  }

  // ------------------------------------------------------------------ hooks for world.js
  MMO.attach = function (view) {
    if (MMO.view === view) return;
    MMO.view = view;
    view.mmo = MMO;
    // you walk the world only with a character: none made yet -> the orbiting view until "Join world"
    MMO.active = !MMO.save.settings.spectate && MMO.hasCharacter();
    if (MMO.active) MMO.enter(); else MMO.leave(true);
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("keyup", onKeyUp, true);
    window.addEventListener("blur", MMO.clearKeys);
    view.canvas.addEventListener("contextmenu", (e) => { if (MMO.active) e.preventDefault(); });
    view.canvas.addEventListener("pointerdown", () => { Sound.init(); if (MMO.active) view.canvas.focus({ preventScroll: true }); });
    for (const s of MMO.systems) if (s.attach) s.attach(view);
    // Join world / Spectate: walk your character, or the old orbiting view (nothing is taken off).
    // Joining with no character yet opens the character creator first (app/ui/character.js).
    const frame = view.canvas.parentElement;
    if (frame && !frame.querySelector(".mmo-toggle")) {
      const bar = el("div", "mmo-bar");
      const btn = el("button", "mmo-toggle");
      btn.type = "button";
      btn.id = "world-join";
      const edit = el("button", "mmo-edit");
      edit.type = "button";
      edit.id = "world-edit-character";
      MMO.refreshButtons = function () {
        const C = window.LokiCharacter;
        if (C) { C.label(btn, MMO.active ? "spectate" : "join"); C.label(edit, "edit"); }
        else { btn.textContent = MMO.active ? "\u25CE Spectate" : "\u25B6 Join world"; }
        edit.hidden = !C;
      };
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (MMO.active) { MMO.leave(); MMO.refreshButtons(); } else MMO.join();
      });
      edit.addEventListener("click", (e) => {
        e.stopPropagation();
        if (window.LokiCharacter) window.LokiCharacter.open({ edit: true, onJoin: () => MMO.join() });
      });
      document.addEventListener("loki:language", MMO.refreshButtons);
      MMO.refreshButtons();
      bar.append(edit, btn);
      frame.append(bar);
    }
    if (hasWorld() && World.data) MMO.onWorld(World.data);
  };
  MMO.enter = function () {   // play: the camera comes down behind you
    const v = MMO.view;
    MMO.active = true; MMO.save.settings.spectate = false; MMO.persist();
    if (!v) return;
    v.follow = ""; v.focus = null;
    v.dist = 8; v.pitch = 0.42;
    const p = MMO.player;
    // world.js puts the eye at target + (cos yaw, sin yaw) * dist: behind you is -(sin ry, cos ry)
    v.yaw = Math.atan2(-Math.cos(p.ry), -Math.sin(p.ry));
    MMO.camTarget[0] = p.x; MMO.camTarget[1] = p.baseY + p.y + 1.1; MMO.camTarget[2] = p.z;
    const frame = v.canvas.parentElement;
    if (frame) frame.classList.add("mmo-on");
    for (const s of MMO.systems) if (s.enter) s.enter();
  };
  MMO.hasCharacter = function () { return !!MMO.look || !window.LokiCharacter; };
  // "Join world": with a character, in you go; without one, the creator first (and in after it)
  MMO.join = function () {
    const C = window.LokiCharacter;
    const go = () => {
      MMO.enter();
      if (MMO.refreshButtons) MMO.refreshButtons();
      if (MMO.view) MMO.view.canvas.focus({ preventScroll: true });
    };
    if (MMO.hasCharacter()) { go(); return true; }
    if (!C.loaded) { C.ready.then(() => MMO.join()); return false; }   // still asking the engine
    C.open({ edit: false, onJoin: go });
    return false;
  };
  MMO.leave = function (quiet) {   // spectate: the old orbiting camera, nothing taken off
    const v = MMO.view;
    MMO.active = false;
    if (!quiet) { MMO.save.settings.spectate = true; MMO.persist(); }   // quiet: no character yet, not a choice
    MMO.clearKeys();
    if (v) {
      v.dist = 17; v.pitch = 0.5; v.focus = null;
      const frame = v.canvas.parentElement;
      if (frame) frame.classList.remove("mmo-on", "mmo-full");
    }
    if (World.hour != null && MMO.setHour) { World.hour = null; MMO.setHour = false; }
    for (const s of MMO.systems) if (s.leave) s.leave();
  };
  MMO.onWorld = function (data) {
    MMO.refreshZones();
    for (const s of MMO.systems) if (s.onWorld) s.onWorld(data);
  };

  MMO.tick = function (view, dt, now) {
    const t = now / 1000, p = MMO.player, st = MMO.stats();
    // a clicked machine label sets view.focus: in the MMO that means "travel there"
    if (view.focus) {
      for (const z of MMO.zones.list) {
        if (Math.abs(view.focus[0] - z.cx) < 0.5 && Math.abs(view.focus[2] - z.cz) < 0.5 && p.zone !== z.name) {
          if (p.zone) MMO.teleportHome();
          MMO.startTravel(z.name);
        }
      }
      view.focus = null;
    }
    if (MMO.save.settings.fastDay) { World.hour = (now / 60000) % 24; MMO.setHour = true; }   // a 24-minute day
    else if (MMO.setHour) { World.hour = null; MMO.setHour = false; }
    move(dt, t);
    // out of combat for 5 s: health and energy come back
    const calm = now - p.combatAt > 5000;
    if (!p.dead) {
      p.hp = Math.min(st.hpMax, p.hp + dt * (calm ? st.hpMax * 0.06 : 0.6));
      p.en = Math.min(st.enMax, p.en + dt * (calm ? 14 : 6));
    }
    if (p.emote && now - p.emoteAt > (p.emote === "sit" || p.emote === "dance" ? 60000 : 2600)) p.emote = "";
    for (const s of MMO.systems) if (s.tick) s.tick(dt, now, t);
    // the camera: just behind and above you, eased
    const k = Math.min(1, dt * 12), ty = p.baseY + p.y * 0.6 + 1.1;
    MMO.camTarget[0] += (p.x - MMO.camTarget[0]) * k;
    MMO.camTarget[1] += (ty - MMO.camTarget[1]) * k;
    MMO.camTarget[2] += (p.z - MMO.camTarget[2]) * k;
    MMO.save.stats.played += dt;
    MMO.persist();
    flushSave(now);
  };

  // avatar()'s signature with the look in place of the tunic colour (scene() picks one of the two)
  function personAt(L, x, y, z, ry, col, cls, phase, walking, emote, et, big, alpha, shadowed) {
    return person(L, x, y, z, ry, MMO.look, cls, phase, walking, emote, et, big, alpha, shadowed);
  }
  const RING_SELF = [0.4, 1, 0.55], RING_FOE = [1, 0.3, 0.28], RING_FRIEND = [0.3, 1, 0.9], GHOST = [0.6, 0.6, 0.7];
  const TUNIC = [0, 0, 0];
  // HOT:BEGIN - runs every frame: pooled objects and scratch arrays only
  MMO.scene = function (L, t, dt, P, now) {
    resetPools();
    const p = MMO.player, k = CLASSES[MMO.myClass()];
    const col = k.rgb || (k.rgb = hexRgb(k.color, TEAL));
    const myCol = shade(TUNIC, col, 0.55, 0.32);   // a lighter tunic than the cape
    const emote = p.dead ? "sit" : p.casting ? "cast" : p.emote, et = (now - (p.casting ? p.castAt : p.emoteAt)) / 1000;
    (MMO.look ? personAt : avatar)(L, p.x, p.baseY + p.y, p.z, p.ry, myCol, MMO.myClass(), p.phase, p.walking && !p.travel ? true : !!p.travel,
      p.attackAt && now - p.attackAt < 400 ? "attack" : emote, p.attackAt && now - p.attackAt < 400 ? (now - p.attackAt) / 1000 : et,
      1.0, 1, p.baseY === 0 && !p.travel);
    if (p.dead) glowAt(L, p.x, p.baseY + 1.2, p.z, 1.0, GHOST, 0.5);
    // the target ring
    const tg = MMO.game && MMO.game.targetPos(now);
    if (tg) ring(L, tg.x, tg.y, tg.z, tg.r, tg.foe ? RING_FOE : tg.self ? RING_SELF : RING_FRIEND, World.reduced ? 0 : t * 0.8, 0.8);
    for (const s of MMO.systems) if (s.scene) s.scene(L, t, dt, P, now);
  };
  // HOT:END

  // nameplates: agents get level, class and bars on their label (world.js makes the label)
  MMO.decorate = function (node, id, a, now) {
    if (MMO.game) MMO.game.decorateAgent(node, id, a, now);
  };
  const PLATE = [0, 0, 0];
  MMO.labels = function (view, now, nodeFor, setText, items, seen) {
    if (MMO.look) {   // you: the name and role from the character creator
      const p = MMO.player, node = nodeFor("mmo:self", "wlabel mmo-self");
      seen.add("mmo:self");
      const at = MMO.projectInto(view, p.x, p.baseY + p.y + 1.75 + (MMO.look.accessory === "hat" ? 0.15 : 0), p.z, PLATE);
      node.hidden = !at;
      if (at) {
        setText(node, 0, MMO.look.name);
        setText(node, 1, MMO.look.roleName ? "<" + MMO.look.roleName + ">" : "");
        items.push({ node, x: PLATE[0], y: PLATE[1], depth: PLATE[2] });
      }
    }
    for (const s of MMO.systems) if (s.labels) s.labels(view, now, nodeFor, setText, items, seen);
  };
  MMO.click = function (view, x, y) { return MMO.game ? MMO.game.click(view, x, y) : false; };
  MMO.interact = function () { if (MMO.game) MMO.game.interact(); };

  // projection without allocating (world.js's project() makes arrays)
  MMO.projectInto = function (view, x, y, z, out) {
    const vp = view.lastVP, c = view.canvas;
    if (!vp) return false;
    const X = vp[0] * x + vp[4] * y + vp[8] * z + vp[12], Y = vp[1] * x + vp[5] * y + vp[9] * z + vp[13], W = vp[3] * x + vp[7] * y + vp[11] * z + vp[15];
    if (W <= 0) return false;
    out[0] = (X / W * 0.5 + 0.5) * c.clientWidth; out[1] = (1 - (Y / W * 0.5 + 0.5)) * c.clientHeight; out[2] = W;
    return true;
  };
})();
