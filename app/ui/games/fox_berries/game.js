// Fox & Berries - the first game made with LOKI's Pixel Engine.
// Run around the floating island as the fox, eat the berries before the time runs out,
// and keep away from the rolling boulders. Arrow keys / WASD to move, Space to dash, R to restart.
"use strict";
(function () {
  const PE = window.PixelEngine;
  const G = PE.create(document.getElementById("game"), { pixel: 3, sky: [[0.36, 0.56, 0.9], [0.86, 0.92, 1.0]] });
  const R = 7.2;                                            // island radius (the edge is the limit)
  const rnd = G.rand(Date.now() % 100000);
  G.add(PE.models.island(8));
  for (let i = 0; i < 9; i++) {                             // a ring of trees near the edge
    const a = i / 9 * Math.PI * 2 + 0.3, r = 6.4 + (i % 3) * 0.3;
    G.add(PE.models.tree(0.8 + (i % 3) * 0.2), { pos: [Math.cos(a) * r, 0, Math.sin(a) * r], ry: i });
  }
  for (let i = 0; i < 5; i++) {
    const a = i * 1.3 + 0.7;
    G.add(PE.models.rock(0.4 + (i % 2) * 0.2), { pos: [Math.cos(a) * 4.8, 0, Math.sin(a) * 4.8], ry: i });
  }
  const fox = G.add(PE.models.fox(), { pos: [0, 0, 0], scale: 1.3 });
  let berries = [], boulders = [], score = 0, best = 0, time = 0, dash = 0, over = false, flash = 0;

  function spot(minR) {
    for (let k = 0; k < 40; k++) {
      const a = rnd() * Math.PI * 2, r = minR + rnd() * (R - 0.8 - minR);
      const p = [Math.cos(a) * r, 0, Math.sin(a) * r];
      if (Math.hypot(p[0] - fox.pos[0], p[2] - fox.pos[2]) > 2) return p;
    }
    return [0, 0, 3];
  }
  function reset() {
    for (const b of berries.concat(boulders)) G.remove(b);
    berries = []; boulders = [];
    fox.pos = [0, 0, 0]; score = 0; time = 45; over = false; dash = 0;
    for (let i = 0; i < 6; i++) berries.push(G.add(PE.models.berry(), { pos: spot(0.5), scale: 1.2 }));
    G.hud("", "big");
  }
  function addBoulder() {
    const a = rnd() * Math.PI * 2;
    const b = G.add(PE.models.rock(0.7), { pos: [Math.cos(a) * (R - 0.5), 0, Math.sin(a) * (R - 0.5)] });
    const to = Math.atan2(-b.pos[2], -b.pos[0]) + (rnd() - 0.5) * 0.8;
    b.data.v = [Math.cos(to) * 2.2, Math.sin(to) * 2.2];
    boulders.push(b);
  }
  reset();

  G.on("update", (dt, t) => {
    if (over) {
      if (G.key("r") || G.key("Enter")) reset();
      G.camera.yaw += dt * 0.2;
      return;
    }
    time -= dt;
    // move: arrows/WASD relative to the camera
    let mx = 0, mz = 0;
    if (G.key("ArrowUp") || G.key("w")) mz -= 1;
    if (G.key("ArrowDown") || G.key("s")) mz += 1;
    if (G.key("ArrowLeft") || G.key("a")) mx -= 1;
    if (G.key("ArrowRight") || G.key("d")) mx += 1;
    if ((G.key(" ") || G.key("Space")) && dash <= -0.6) { dash = 0.25; G.sound(660, 0.08, "triangle"); }
    dash -= dt;
    const yaw = G.camera.yaw, speed = dash > 0 ? 9 : 4;
    if (mx || mz) {
      const l = Math.hypot(mx, mz);
      // camera forward on the ground is toward the target from the eye: (-cos yaw, -sin yaw)
      const fx = -Math.cos(yaw), fz = -Math.sin(yaw), rx = -fz, rz = fx;
      const dx = (rx * mx - fx * mz) / l, dz = (rz * mx - fz * mz) / l;
      fox.pos[0] += dx * speed * dt; fox.pos[2] += dz * speed * dt;
      fox.ry = Math.atan2(dx, dz);
      fox.pos[1] = Math.abs(Math.sin(t * 14)) * 0.06;
    } else fox.pos[1] = 0;
    const d = Math.hypot(fox.pos[0], fox.pos[2]);
    if (d > R) { fox.pos[0] *= R / d; fox.pos[2] *= R / d; }
    // berries bob and get eaten
    for (const b of berries) {
      b.ry += dt * 2; b.pos[1] = 0.1 + Math.sin(t * 3 + b.pos[0]) * 0.08;
      if (G.hit(fox, b, 0.75)) {
        score++; time += 2.5; flash = 0.15;
        G.sound(880 + score * 20, 0.1, "square");
        b.pos = spot(0.5);
        if (score % 4 === 0) addBoulder();
      }
    }
    // boulders roll across and bounce off the edge
    for (const b of boulders) {
      b.pos[0] += b.data.v[0] * dt; b.pos[2] += b.data.v[1] * dt; b.ry += dt * 4;
      const r = Math.hypot(b.pos[0], b.pos[2]);
      if (r > R - 0.3) {
        const nx = b.pos[0] / r, nz = b.pos[2] / r, dotv = b.data.v[0] * nx + b.data.v[1] * nz;
        b.data.v[0] -= 2 * dotv * nx; b.data.v[1] -= 2 * dotv * nz;
        b.pos[0] = nx * (R - 0.35); b.pos[2] = nz * (R - 0.35);
      }
      if (G.hit(fox, b, 0.7) && dash <= 0) { time -= 5; G.sound(140, 0.25, "sawtooth"); b.data.v[0] *= -1; b.data.v[1] *= -1; }
    }
    // camera follows the fox
    const c = G.camera;
    c.target[0] += (fox.pos[0] - c.target[0]) * Math.min(1, dt * 4);
    c.target[2] += (fox.pos[2] - c.target[2]) * Math.min(1, dt * 4);
    c.dist = 11; c.pitch = 0.62;
    flash -= dt;
    G.hud("Berries " + score + "   Time " + Math.max(0, Math.ceil(time)) + "   Best " + best + "\n" +
      "Arrows/WASD move · Space dash");
    if (time <= 0) {
      over = true; best = Math.max(best, score);
      G.sound(220, 0.4, "triangle");
      G.hud("Time! " + score + " berries\nPress R to play again", "big");
    }
  });
  window.LOKI_GAME = G;   // lets LOKI's tests and screenshots look at the running game
  G.start();
})();
