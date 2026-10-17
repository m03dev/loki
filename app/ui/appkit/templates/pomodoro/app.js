// Focus timer - Pomodoro: focus, short break, long break; what you focused on today.
"use strict";
const { h, mount } = kit;
const root = document.getElementById("app");
const S = { settings: { focus: 25, short: 5, long: 15, every: 4 }, log: [], phase: "focus", left: 25 * 60, running: false, task: "", count: 0 };
let timer = 0, endsAt = 0;
const LABELS = { focus: "Focus", short: "Short break", long: "Long break" };

async function load() {
  S.settings = await loki.store.get("settings", S.settings);
  S.log = await loki.store.get("log", []);   // [{date, minutes, task, t}]
  S.left = S.settings.focus * 60;
  render();
}

function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [0, 0.25, 0.5].forEach((at) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 880; g.gain.value = 0.08;
      o.connect(g); g.connect(ctx.destination);
      o.start(ctx.currentTime + at); o.stop(ctx.currentTime + at + 0.15);
    });
  } catch (_) { /* no sound here */ }
}

function setPhase(phase) {
  S.phase = phase;
  S.left = S.settings[phase] * 60;
  stop();
  render();
}

function start() {
  if (S.running) return;
  S.running = true;
  endsAt = Date.now() + S.left * 1000;
  timer = setInterval(tick, 250);
  render();
}
function stop() { S.running = false; clearInterval(timer); }

async function tick() {
  S.left = Math.max(0, Math.round((endsAt - Date.now()) / 1000));
  if (S.left > 0) { paint(); return; }
  stop();
  beep();
  if (S.phase === "focus") {
    S.count++;
    S.log.push({ date: kit.today(), minutes: S.settings.focus, task: S.task.trim(), t: Date.now() });
    await loki.store.set("log", S.log.slice(-2000));
    kit.toast("Focus done - take a break", "ok");
    setPhase(S.count % S.settings.every === 0 ? "long" : "short");
  } else {
    kit.toast("Break over - ready?");
    setPhase("focus");
  }
}

const fmt = (s) => String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
let clock = null, ring = null;
function paint() {
  if (clock) clock.textContent = fmt(S.left);
  if (ring) ring.style.background = "conic-gradient(var(--lk-accent) " + (360 * (1 - S.left / (S.settings[S.phase] * 60))) + "deg, var(--lk-bg2) 0)";
  document.title = fmt(S.left) + " · " + LABELS[S.phase];
}

async function settings() {
  const v = await kit.form("Timer settings", [
    { name: "focus", label: "Focus minutes", type: "number", value: S.settings.focus },
    { name: "short", label: "Short break minutes", type: "number", value: S.settings.short },
    { name: "long", label: "Long break minutes", type: "number", value: S.settings.long },
    { name: "every", label: "Long break after this many focus rounds", type: "number", value: S.settings.every },
  ], "Save");
  if (!v) return;
  for (const k of Object.keys(S.settings)) S.settings[k] = Math.max(1, Math.min(180, Math.round(v[k] || S.settings[k])));
  await loki.store.set("settings", S.settings);
  setPhase(S.phase);
}

function render() {
  const today = S.log.filter((l) => l.date === kit.today());
  const days = [];
  for (let i = 6; i >= 0; i--) { const d = new Date(); d.setDate(d.getDate() - i); const key = d.toISOString().slice(0, 10);
    days.push({ label: d.toLocaleDateString(undefined, { weekday: "short" }), value: kit.sum(S.log.filter((l) => l.date === key), (l) => l.minutes) }); }
  clock = h("div", { style: { fontSize: "64px", fontWeight: "700", fontVariantNumeric: "tabular-nums", letterSpacing: "-.02em" } }, fmt(S.left));
  ring = h("div", { style: { width: "260px", height: "260px", borderRadius: "50%", display: "grid", placeItems: "center", margin: "6px auto" } },
    h("div", { style: { width: "228px", height: "228px", borderRadius: "50%", background: "var(--lk-card)", display: "grid", placeItems: "center", alignContent: "center" } },
      clock, h("div", { class: "lk-muted" }, LABELS[S.phase])));
  mount(root,
    kit.header("⏱️", "Focus timer", today.length + " focus rounds today · " + kit.sum(today, (l) => l.minutes) + " min", kit.button("Settings", settings, "ghost")),
    kit.card(null,
      h("div", { class: "lk-row", style: { justifyContent: "center" } }, kit.tabs(["focus", "short", "long"].map((p) => ({ value: p, label: LABELS[p] })), S.phase, setPhase)),
      ring,
      kit.input({ placeholder: "What are you focusing on?", value: S.task, style: { textAlign: "center", maxWidth: "420px", margin: "0 auto" }, on: { input: (e) => { S.task = e.target.value; } } }),
      h("div", { class: "lk-row", style: { justifyContent: "center" } },
        S.running ? kit.button("Pause", () => { stop(); render(); }) : kit.button(S.left < S.settings[S.phase] * 60 ? "Resume" : "Start", start, "primary"),
        kit.button("Reset", () => setPhase(S.phase), "ghost"))),
    h("div", { class: "lk-grid two" },
      kit.card("This week (minutes)", kit.bars(days)),
      kit.card("Today", today.length ? h("div", { class: "lk-list" }, today.slice().reverse().map((l) => h("div", { class: "lk-item" },
        h("span", { class: "lk-grow" }, l.task || "Focus"), h("span", { class: "lk-muted lk-small" }, new Date(l.t).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })), h("span", { class: "lk-tag accent" }, l.minutes + " min"))))
        : kit.empty("🎯", "Start a focus round."))));
  paint();
}

document.addEventListener("keydown", (e) => {
  if (e.key === " " && !e.target.closest("input, textarea, .lk-overlay")) { e.preventDefault(); if (S.running) { stop(); render(); } else start(); }
});
loki.ready(load);
