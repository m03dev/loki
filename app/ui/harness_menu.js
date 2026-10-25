// The Harness menu, beside the model menu (owner 2026-10-25: "i should be able to swap out different harnesses,
// everything should be modular"). The model is WHO answers; the harness is HOW the work gets done: Auto, OpenCode,
// DeepSeek Harness, the Shell agent (mini-swe-agent's recipe, best for local models) or LOKI classic. GET /agent/engine
// lists them, POST /agent/engine/set picks one (remembered). Plain DOM, the model menu's look.
"use strict";

const LokiHarness = (() => {
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  let btn = null, menu = null, label = null, st = null;

  function mount() {
    const picker = document.querySelector(".topbar .model-picker");
    if (!picker || document.getElementById("harness-button")) return !!btn;
    const wrap = mk("div", "model-picker harness-picker");
    btn = mk("button", "model-button harness-button"); btn.type = "button"; btn.id = "harness-button";
    btn.setAttribute("aria-haspopup", "menu"); btn.setAttribute("aria-expanded", "false");
    btn.dataset.tipName = "Harness"; btn.dataset.tipWhat = "How the work gets done: OpenCode, DeepSeek Harness, the Shell agent or LOKI classic. Auto picks for the model.";
    label = mk("span", "", "Auto");
    btn.append(label, mk("span", "caret", "▾"));
    btn.querySelector(".caret").setAttribute("aria-hidden", "true");
    menu = mk("div", "model-menu harness-menu"); menu.id = "harness-menu"; menu.setAttribute("role", "menu"); menu.hidden = true;
    menu.addEventListener("click", (e) => e.stopPropagation());
    btn.addEventListener("click", (e) => { e.stopPropagation(); toggle(menu.hidden); });
    document.addEventListener("click", () => toggle(false));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { toggle(false); btn.focus(); } });
    wrap.append(btn, menu);
    picker.after(wrap);
    return true;
  }
  function toggle(open) {
    if (!menu) return;
    menu.hidden = !open; btn.setAttribute("aria-expanded", String(!!open));
    if (open) { paintMenu(); const cur = menu.querySelector(".model-item.current, .model-item"); if (cur) cur.focus(); }
  }
  function paintMenu() {
    menu.replaceChildren(mk("div", "model-group", "Harness - how the work gets done"));
    for (const h of (st && st.harnesses) || []) {
      const b = mk("button", "model-item" + (st.engine === h.id ? " current" : "")); b.type = "button";
      b.setAttribute("role", "menuitemradio"); b.setAttribute("aria-checked", String(st.engine === h.id)); b.dataset.harness = h.id;
      const top = mk("span", "model-item-top"); top.append(mk("span", "model-item-name", h.name));
      const missing = (h.id === "opencode" && !st.opencode) || (h.id === "dsh" && !st.dsh);
      if (missing) top.append(mk("span", "model-item-using", "not installed"));
      b.append(top, mk("span", "model-item-blurb", h.what));
      b.addEventListener("click", () => pick(h.id));
      menu.append(b);
    }
  }
  async function pick(id) {
    const r = await api("/agent/engine/set", { engine: id }).catch(() => null);
    if (r && r.ok) { paint(r); if (window.AgentEngine && AgentEngine.load) AgentEngine.load(); }
    toggle(false);
  }
  function paint(s) {
    st = s;
    const h = ((s && s.harnesses) || []).find((x) => x.id === s.engine);
    if (label) label.textContent = h ? h.name : "Auto";
    if (menu && !menu.hidden) paintMenu();
  }
  async function load() {
    if (!mount() || typeof api !== "function") return;
    try { paint(await api("/agent/engine")); } catch (_) { /* engine restarting */ }
  }
  document.addEventListener("DOMContentLoaded", () => setTimeout(load, 300));
  return { load, paint };
})();
window.LokiHarness = LokiHarness;
