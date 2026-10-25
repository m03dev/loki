// Settings > Local models: every model downloaded on this computer, and Remove (owner 2026-10-25: "i should be able to
// see what models i have downloaded and i can uninstall them from my system from loki in that local tab").
// GET /local/models, POST /local/models/remove (engine/local_models.py). LOKI's own "loki-<model>" long-context copy is
// shown on its model's row and removed with it (it shares the same files). Remove asks once, in the row (no pop-up).
"use strict";

const LokiLocalModels = (() => {
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const gb = (x) => (x >= 1 ? x.toFixed(1) + " GB" : Math.round(x * 1024) + " MB");
  const KIND = { ollama: "Chat model (Ollama)", image: "Image model", hf: "Downloaded model files" };
  let box = null;

  function mount() {
    const panel = document.getElementById("models-panel");
    if (!panel) return null;
    if (box && box.isConnected) return box;
    box = mk("div", "lm-box"); box.id = "lm-downloaded";
    panel.before(box);
    return box;
  }
  async function load() {
    if (!mount() || typeof api !== "function") return;
    box.replaceChildren(mk("p", "note", "Looking at what is downloaded..."));
    const d = await api("/local/models").catch((e) => ({ ok: false, error: e.message }));
    paint(d);
  }
  function paint(d) {
    box.replaceChildren();
    const head = mk("div", "lm-head");
    head.append(mk("h4", "", "Downloaded on this computer"));
    if (d && d.ok) head.append(mk("span", "note", gb(d.total_gb || 0) + " of models" + (d.free_gb != null ? " · " + gb(d.free_gb) + " free on the disk" : "")));
    const again = mk("button", "quiet small", "Refresh"); again.type = "button"; again.addEventListener("click", load);
    head.append(again);
    box.append(head);
    if (!d || !d.ok) { box.append(mk("p", "note bad", "Could not list them: " + ((d && d.error) || "no answer"))); return; }
    if (d.ollama_note) box.append(mk("p", "note", d.ollama_note));
    const copies = {};
    for (const m of d.models) if (m.copy_of) (copies[m.copy_of] = copies[m.copy_of] || []).push(m);
    const rows = d.models.filter((m) => !m.copy_of);
    if (!rows.length) { box.append(mk("p", "note", "No models downloaded yet.")); return; }
    const list = mk("div", "lm-list"); list.setAttribute("role", "list");
    for (const m of rows) {
      const extra = copies[m.name] || [];
      const row = mk("div", "lm-row"); row.setAttribute("role", "listitem"); row.dataset.id = m.id;
      const info = mk("div", "lm-info");
      const title = mk("b", "lm-name", m.name);
      if (m.loaded || extra.some((c) => c.loaded)) title.append(mk("span", "lm-badge", "in use"));
      info.append(title);
      const meta = [KIND[m.kind] || m.kind, gb(m.size_gb), m.params, m.quant].filter(Boolean).join(" · ");
      info.append(mk("span", "note", meta + (extra.length ? " · with LOKI's long-context copy" : "")));
      const acts = mk("div", "lm-acts");
      const rm = mk("button", "quiet small lm-remove", "Remove"); rm.type = "button";
      rm.dataset.tipName = "Remove"; rm.dataset.tipWhat = "Delete this model from this computer and get the space back.";
      rm.addEventListener("click", () => ask(row, m, extra));
      acts.append(rm);
      row.append(info, acts);
      list.append(row);
    }
    box.append(list);
  }
  function ask(row, m, extra) {
    const acts = row.querySelector(".lm-acts");
    const prev = [...acts.childNodes];
    const q = mk("span", "lm-ask", "Remove " + m.name + " (" + gb(m.size_gb) + ")" + (extra.length ? " and LOKI's copy of it" : "") + "?");
    const yes = mk("button", "small danger", "Remove"); yes.type = "button";
    const no = mk("button", "quiet small", "Cancel"); no.type = "button";
    no.addEventListener("click", () => acts.replaceChildren(...prev));
    yes.addEventListener("click", async () => {
      yes.disabled = no.disabled = true; q.textContent = "Removing...";
      const r = await api("/local/models/remove", { id: m.id }).catch((e) => ({ ok: false, error: e.message }));
      if (r && r.ok) { row.classList.add("gone"); q.textContent = "Removed."; setTimeout(load, 600); }
      else { q.textContent = "Not removed: " + ((r && r.error) || "no answer"); q.classList.add("bad"); no.disabled = false; }
    });
    acts.replaceChildren(q, yes, no);
    no.focus();
  }
  document.addEventListener("DOMContentLoaded", () => {
    const section = document.querySelector('section[data-panel="models"]');
    if (!section) return;
    new MutationObserver(() => { if (!section.hidden) load(); }).observe(section, { attributes: true, attributeFilter: ["hidden"] });
    if (!section.hidden) load();
  });
  return { load, paint };
})();
window.LokiLocalModels = LokiLocalModels;
