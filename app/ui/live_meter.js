// The live meter (owner 2026-10-25: "real time token tracking underneath the thinking or its steps as its working just
// like ziva ... i want to know what model is being used and when - keep the ui clean and minimal").
// One quiet line under the steps while LOKI works: the model and where it runs, the step, tokens in / out so far, the
// speed, the time. It stays under the reply when done. A model switch (a provider ran out) leaves a one-line note.
// Fed by "usage" progress events (engine/local_agent.py, loki.run_opencode).
"use strict";

const LiveMeter = (() => {
  let line = null, last = null, timer = 0, t0 = 0, base = 0;
  const k = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n || 0));
  const nice = (m) => String(m || "").replace(/^registry\.ollama\.ai\/library\//, "").replace(/^loki-/, "")
    .replace(/:latest$/, "").replace(/^[\w.-]+\//, "");
  function el() {
    const tr = document.getElementById("transcript");
    if (!tr) return null;
    if (!line || !line.isConnected) { line = document.createElement("div"); line.className = "live-meter"; line.setAttribute("aria-live", "off"); }
    tr.append(line);                                   // always the last thing: under the newest step
    return line;
  }
  function paint() {
    if (!line || !last) return;
    const secs = Math.round(base + (t0 ? (Date.now() - t0) / 1000 : 0));
    const parts = [nice(last.model) + (last.where ? " · " + last.where : "")];
    if (last.step) parts.push("step " + last.step);
    parts.push(k(last.input) + " in · " + k(last.output) + " out");
    if (last.tps) parts.push(last.tps + " tok/s");
    if (last.cost) parts.push("$" + Number(last.cost).toFixed(4));
    parts.push(secs + " s");
    line.textContent = parts.join("  ·  ");
    line.title = "Model: " + (last.model || "?") + "\nRuns on: " + (last.where || "?");
  }
  function update(text) {
    let d;
    try { d = JSON.parse(text); } catch (_) { return; }
    if (!el()) return;
    if (last && d.model && nice(d.model) !== nice(last.model)) {
      const note = document.createElement("div"); note.className = "live-switch";
      note.textContent = "switched to " + nice(d.model) + (d.where ? " (" + d.where + ")" : "");
      line.before(note);
    }
    last = d; base = Number(d.seconds) || 0; t0 = Date.now();
    line.classList.remove("done");
    if (!timer) timer = setInterval(paint, 1000);
    paint();
  }
  function finish() {
    clearInterval(timer); timer = 0;
    if (line && last) { t0 = 0; base = Number(last.seconds) || base; paint(); line.classList.add("done"); el(); }
    line = null; last = null;
  }
  // new steps land below it: keep it the last line while working
  document.addEventListener("DOMContentLoaded", () => {
    const tr = document.getElementById("transcript");
    if (!tr) return;
    new MutationObserver(() => { if (timer && line && line.isConnected && tr.lastElementChild !== line) tr.append(line); })
      .observe(tr, { childList: true });
  });
  return { update, finish };
})();
window.LiveMeter = LiveMeter;
