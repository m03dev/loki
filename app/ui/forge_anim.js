// Forge - the Time Slider (the pro animation frame): keyframes on a node's transform channels, a playhead you
// can scrub, a tick per key, Set Key (S), step to the previous / next key and playback that loops the range.
// The keys live on the scene nodes (forge_scene.js tree.api.setKey / evalKeys / setFrame); this is the UI and
// the clock. Re-implemented from the standard keyframe model - nothing copied.
function forgeTimeAttach(view) {
  const T = view && view.tree;
  if (!T || !T.api) return null;
  const api = T.api;
  const stage = (document.getElementById("forge-view") || {}).parentElement;
  if (!stage || document.getElementById("forge-time")) return null;

  const bar = document.createElement("div");
  bar.className = "forge-float forge-timebar"; bar.id = "forge-time";
  const mk = (label, tip, id, cls) => {
    const b = document.createElement("button"); b.type = "button"; b.className = "mini forge-btn" + (cls ? " " + cls : "");
    b.textContent = label; b.title = tip; if (id) b.id = id; return b;
  };
  const num = (id, tip, val) => {
    const i = document.createElement("input"); i.type = "number"; i.className = "forge-time-num"; i.id = id;
    i.title = tip; i.value = String(val); return i;
  };
  const play = mk("Play", "Play / stop the animation (it loops over the range).", "forge-time-play", "forge-time-play");
  const prev = mk("\u25c0", "Jump to the previous key.", "forge-time-prev");
  const next = mk("\u25b6", "Jump to the next key.", "forge-time-next");
  const setk = mk("Set Key", "Key the selected object's translate / rotate / scale at this frame (S).", "forge-time-setkey", "forge-time-setkey");
  const akey = mk("Auto Key", "Auto Keyframe: while it is on, moving or typing a channel writes a key at the playhead.", "forge-time-autokey", "forge-time-autokey");
  const interp = document.createElement("select");
  interp.className = "forge-time-interp"; interp.id = "forge-time-interp";
  interp.title = "Interpolation of the keys at this frame.";
  for (const [val, label] of [["linear", "Linear"], ["bezier", "Smooth"], ["step", "Step"]]) { const o = document.createElement("option"); o.value = val; o.textContent = label; interp.append(o); }
  interp.addEventListener("change", () => api.undoChunk("key interpolation", () => api.setInterp(null, T.time.frame, null, null, interp.value)));
  const frame = num("forge-time-frame", "The current frame.", 1);
  frame.min = "1";
  const start = num("forge-time-start", "First frame of the played range.", 1);
  const end = num("forge-time-end", "Last frame of the played range.", 24);
  const slider = document.createElement("input");
  slider.type = "range"; slider.className = "forge-time-slider"; slider.id = "forge-time-slider";
  slider.min = "1"; slider.max = "24"; slider.step = "1"; slider.value = "1";
  slider.title = "Scrub the playhead.";
  const ticks = document.createElement("div"); ticks.className = "forge-time-ticks"; ticks.id = "forge-time-ticks";
  const track = document.createElement("div"); track.className = "forge-time-track"; track.append(slider, ticks);

  play.addEventListener("click", () => api.togglePlay());
  prev.addEventListener("click", () => api.stepKey(null, -1));
  next.addEventListener("click", () => api.stepKey(null, 1));
  setk.addEventListener("click", () => { if (typeof forgeProRun === "function") { const r = forgeProRun(view, "setKey"); if (r && typeof forgeSay === "function") forgeSay(r); } });
  akey.addEventListener("click", () => { const on = api.setAutoKey(); if (typeof forgeSay === "function") forgeSay("Auto Keyframe " + (on ? "on" : "off") + "."); });
  slider.addEventListener("input", () => api.setFrame(slider.value));
  frame.addEventListener("input", () => { if (frame.value !== "") api.setFrame(frame.value); });
  frame.addEventListener("keydown", (e) => e.stopPropagation());        // typing a frame is not a hotkey
  start.addEventListener("change", () => api.setRange(start.value, end.value));
  end.addEventListener("change", () => api.setRange(start.value, end.value));
  for (const i of [start, end]) i.addEventListener("keydown", (e) => e.stopPropagation());
  // a click on the tick strip jumps the playhead there
  track.addEventListener("pointerdown", (e) => {
    if (e.target === slider) return;
    const r = track.getBoundingClientRect();
    api.setFrame(T.time.start + Math.round((e.clientX - r.left) / Math.max(1, r.width) * (T.time.end - T.time.start)));
  });

  bar.append(play, prev, next, setk, akey, interp, frame, track, start, end);
  stage.append(bar);

  function sync() {
    const t = T.time;
    play.textContent = t.playing ? "Stop" : "Play";
    play.classList.toggle("on", t.playing);
    if (document.activeElement !== frame) frame.value = String(Math.round(t.frame));
    akey.classList.toggle("on", !!T.autoKey);
    bar.dataset.autokey = T.autoKey ? "1" : "0";
    if (document.activeElement !== start) start.value = String(t.start);
    if (document.activeElement !== end) end.value = String(t.end);
    slider.min = String(t.start); slider.max = String(t.end); slider.value = String(Math.round(t.frame));
    ticks.textContent = "";
    const ts = api.keyTimes ? api.keyTimes() : [];
    const span = Math.max(1, t.end - t.start);
    for (const f of ts) {
      const s = document.createElement("span"); s.className = "forge-tick";
      s.style.left = (((f - t.start) / span) * 100) + "%"; s.title = "Key at frame " + f;
      ticks.append(s);
    }
    bar.dataset.keys = String(ts.length);
    if (document.activeElement !== interp) {
      const key = api.active() && api.active().keys && api.active().keys[`translate0`];
      const at = (n) => { const ks = n && n.keys ? Object.values(n.keys).flat().filter((x) => x.f === Math.round(t.frame)) : []; return ks.length ? ks[0].i : "linear"; };
      interp.value = at(api.active());
    }
    bar.dataset.frame = String(Math.round(t.frame));
  }
  T.syncTime = sync;
  T.syncKeys = sync;   // forge_scene's tree.build calls syncKeys when the selection or the keys change

  let last = performance.now();
  view.tickTime = () => {
    const t = T.time, now = performance.now();
    const dt = Math.min(0.25, (now - last) / 1000);
    last = now;
    if (!t.playing) return;
    let f = t.frame + dt * (t.fps || 24);
    const span = Math.max(1, t.end - t.start);
    if (f > t.end) f = t.start + ((f - t.start) % span);        // loop the range, the pro default
    api.setFrame(f);
  };

  sync();
  return bar;
}
window.forgeTimeAttach = forgeTimeAttach;
