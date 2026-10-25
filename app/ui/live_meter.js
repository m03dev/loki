// The live meter (owner 2026-10-25: "real time token tracking underneath the thinking or its steps as its working just
// ... i want to know what model is being used and when - keep the ui clean and minimal").
// One quiet line under the steps while LOKI works: the model and where it runs, the step, tokens in / out so far, the
// speed, the time. It stays under the reply when done. A model switch (a provider ran out) leaves a one-line note.
// Fed by "usage" progress events (engine/local_agent.py, loki.run_opencode).
"use strict";

const LiveMeter = (() => {
  let line = null, last = null, timer = 0, t0 = 0, base = 0;
  const k = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n || 0));
  // "loki-huihui_ai-qwen3.5-abliterated-9b:latest" -> "qwen3.5-abliterated-9b"; "nvidia/deepseek-v4.1-flash" -> "deepseek-v4.1-flash"
  const nice = (m) => String(m || "").replace(/^registry\.ollama\.ai\/library\//, "").replace(/^loki-/, "")
    .replace(/:latest$/, "").replace(/^.*\//, "").replace(/^[a-z0-9]+_[a-z0-9]+-/i, "");
  const local = (w) => /this computer/i.test(w || "");
  function span(cls, text) { const n = document.createElement("span"); n.className = cls; n.textContent = text; return n; }
  function el() {
    const tr = document.getElementById("transcript");
    if (!tr) return null;
    if (!line || !line.isConnected) { line = document.createElement("div"); line.className = "live-meter"; line.setAttribute("aria-live", "off"); }
    tr.append(line);                                   // always the last thing: under the newest step / the reply
    return line;
  }
  function paint() {
    if (!line || !last) return;
    const secs = Math.round(base + (t0 ? (Date.now() - t0) / 1000 : 0));
    const tok = (last.input || 0) + (last.output || 0);
    const bits = [span("lm-model" + (local(last.where) ? " local" : ""), nice(last.model))];
    if (tok) bits.push(span("lm-bit", k(tok) + " tok"));      // Codex / Claude Code / dsh do not report tokens
    if (last.tps) bits.push(span("lm-bit", Math.round(last.tps) + " tok/s"));
    if (last.cost) bits.push(span("lm-bit", "$" + Number(last.cost).toFixed(3)));
    bits.push(span("lm-bit", secs + "s"));
    line.replaceChildren(...bits);
    line.title = (last.model || "?") + "  (" + (last.where || "?") + ")\n" + (last.input || 0).toLocaleString() + " tokens in, "
      + (last.output || 0).toLocaleString() + " out" + (last.step ? " - " + last.step + " steps" : "") + (last.cost ? " - $" + last.cost : "");
  }
  function update(text) {
    let d;
    try { d = JSON.parse(text); } catch (_) { return; }
    if (!el()) return;
    if (last && d.model && nice(d.model) !== nice(last.model)) {
      const note = document.createElement("div"); note.className = "live-switch";
      note.textContent = "→ " + nice(d.model);
      note.title = "Switched to " + (d.model || "") + (d.where ? " (" + d.where + ")" : "");
      line.before(note);
    }
    last = d; base = Number(d.seconds) || 0; t0 = Date.now();
    line.classList.remove("done");
    if (!timer) timer = setInterval(paint, 1000);
    paint();
    if (typeof scrollDown === "function") scrollDown();
  }
  function finish() {
    clearInterval(timer); timer = 0;
    if (line && last) {
      t0 = 0; base = Number(last.seconds) || base; line.classList.add("done"); paint(); el();
      if (typeof scrollDown === "function") scrollDown();
    }
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
