// Modes (personas) in the message box: a picker next to Ask/Plan/Build that turns LOKI into a Tutor,
// Writer, Coder... (engine/personas.py). The chosen mode's starter prompts replace the welcome chips.
// Managing modes (new, edit, import, export) lives in Apps > Modes (apps.js).
"use strict";

const LokiModes = (() => {
  let modes = [], active = "", menu = null, button = null, defaultChips = null;

  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };

  function current() { return modes.find((m) => m.id === active) || null; }

  function paint() {
    if (!button) return;
    const m = current();
    button.replaceChildren(mk("span", "mode-pick-icon", m ? (m.icon || "✨") : "✨"), mk("span", "mode-pick-name", m ? m.name : "General"));
    button.dataset.tipName = "Mode: " + (m ? m.name : "General");
    button.dataset.tipWhat = m ? m.description : "Pick a mode - Tutor, Writer, Coder, Researcher... - to change how LOKI works.";
    button.setAttribute("aria-label", "Mode: " + (m ? m.name : "General"));
    button.classList.toggle("on", !!m);
    paintChips(m);
  }

  function paintChips(m) {
    const box = document.querySelector(".welcome-chips");
    if (!box) return;
    if (defaultChips === null) defaultChips = [...box.children];
    if (!m || !(m.starters || []).length) { box.replaceChildren(...defaultChips); return; }
    box.replaceChildren(...m.starters.slice(0, 4).map((s) => {
      const chip = mk("button", "chip", s.length > 48 ? s.slice(0, 46) + "…" : s);
      chip.type = "button";
      chip.title = s;
      chip.addEventListener("click", () => { if (typeof send === "function") send(s); });
      return chip;
    }));
  }

  async function refresh() {
    const data = await api("/personas").catch(() => null);
    if (!data || !data.ok) return;
    modes = data.modes || [];
    active = data.active || "";
    paint();
  }

  async function choose(id) {
    closeMenu();
    const out = await api("/personas/active", { id });
    if (out && out.ok) { active = out.active || ""; paint(); }
  }

  function closeMenu() { if (menu) { menu.hidden = true; button.setAttribute("aria-expanded", "false"); } }

  function openMenu() {
    if (!menu) {
      menu = mk("div", "mode-menu");
      menu.setAttribute("role", "menu");
      button.parentNode.append(menu);
      document.addEventListener("click", (e) => { if (menu && !menu.hidden && !menu.contains(e.target) && e.target !== button && !button.contains(e.target)) closeMenu(); });
      document.addEventListener("keydown", (e) => { if (e.key === "Escape" && menu && !menu.hidden) { closeMenu(); button.focus(); } });
    }
    menu.replaceChildren();
    const item = (m) => {
      const b = mk("button", "mode-item" + ((m ? m.id : "") === active ? " on" : ""));
      b.type = "button";
      b.setAttribute("role", "menuitemradio");
      b.setAttribute("aria-checked", String((m ? m.id : "") === active));
      b.append(mk("span", "mode-item-icon", m ? (m.icon || "✨") : "✨"), mk("b", "", m ? m.name : "General"), mk("span", "mode-item-what", m ? m.description : "LOKI as it is."));
      b.addEventListener("click", () => choose(m ? m.id : ""));
      return b;
    };
    menu.append(item(null));
    for (const m of modes) menu.append(item(m));
    const manage = mk("button", "mode-item manage", "Make your own, import or share a mode…");
    manage.type = "button";
    manage.addEventListener("click", () => { closeMenu(); if (window.LokiApps) LokiApps.open("modes"); });
    menu.append(manage);
    menu.hidden = false;
    button.setAttribute("aria-expanded", "true");
    const first = menu.querySelector(".mode-item.on") || menu.querySelector(".mode-item");
    if (first) first.focus();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const row = document.querySelector(".composer-row");
    const modesGroup = row && row.querySelector(".modes");
    if (!row) return;
    const wrap = mk("div", "mode-pick-wrap");
    button = mk("button", "mode-pick");
    button.type = "button";
    button.id = "mode-pick";
    button.setAttribute("aria-haspopup", "menu");
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("click", (e) => { e.stopPropagation(); if (menu && !menu.hidden) closeMenu(); else openMenu(); });
    wrap.append(button);
    row.insertBefore(wrap, modesGroup ? modesGroup : row.firstChild);
    paint();
    // the engine may still be starting: try a few times
    let tries = 0;
    const load = async () => { await refresh(); if (!modes.length && ++tries < 20) setTimeout(load, 2000); };
    setTimeout(load, 800);
  });

  return { refresh, choose };
})();
window.LokiModes = LokiModes;
