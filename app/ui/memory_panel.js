// Settings > Memory, below the facts: what LOKI learned itself (engine/memory_core.py) and the
// skills it learned from its own verified work (engine/skill_learning.py) - roadmap E1/E2.
// GET /memory/core[?q=] lists or searches; POST /memory/core {action: edit|forget|learn}.
// Plain DOM (CSP).
"use strict";

async function loadMemoryCore(query) {
  const box = document.getElementById("memory-core");
  if (!box) return;
  const q = String(query || "");
  const data = await api("/memory/core" + (q ? "?q=" + encodeURIComponent(q) : "")).catch(() => null);
  box.replaceChildren();
  if (!data || !data.ok) { box.append(el("p", "note", "LOKI's learned memory is not available in this engine.")); return; }

  const head = el("div", "lab-head");
  const stats = data.stats || {};
  head.append(el("b", "", "What LOKI learned (" + (stats.items || 0) + " memories, " + (data.skills || []).length + " skills)"));
  const form = el("form", "lab-idea");
  const input = el("input");
  input.placeholder = "Search what LOKI remembers…";
  input.value = q;
  input.setAttribute("aria-label", "Search LOKI's memory");
  const go = el("button", "", "Search");
  go.type = "submit";
  form.append(input, go);
  form.addEventListener("submit", (e) => { e.preventDefault(); loadMemoryCore(input.value); });
  box.append(head, form);

  const rows = el("div", "rows");
  for (const item of data.items || []) {
    const r = el("div", "row lab-row");
    const text = el("div", "lab-text");
    text.append(el("b", "", item.tier || "memory"), el("span", "", " " + (item.text || "")));
    const right = el("div", "lab-right");
    const edit = el("button", "mini", "Edit");
    edit.type = "button";
    edit.addEventListener("click", async () => {
      const next = window.prompt("Change this memory:", item.text || "");
      if (next === null) return;
      const res = await api("/memory/core", { action: "edit", id: item.id, text: next }).catch(() => null);
      if (!res || !res.ok) addNotice((res && res.error) || "Could not change it.", true);
      loadMemoryCore(q);
    });
    const forget = el("button", "mini", "Forget");
    forget.type = "button";
    forget.addEventListener("click", async () => {
      const res = await api("/memory/core", { action: "forget", id: item.id }).catch(() => null);
      if (!res || !res.ok) addNotice((res && res.error) || "Could not forget it.", true);
      loadMemoryCore(q);
    });
    if (!String(item.id || "").startsWith("skill:")) right.append(edit, forget);
    r.append(text, right);
    rows.append(r);
  }
  if (!(data.items || []).length) rows.append(el("p", "note", q ? "Nothing matches." : "Nothing learned yet. LOKI learns as it works (the memory tool)."));
  box.append(rows);

  if ((data.skills || []).length) {
    const skills = el("details", "lab-lessons");
    skills.append(el("summary", "", "Skills LOKI learned from its own verified work"));
    const list = el("div", "rows");
    for (const s of data.skills) {
      const r = el("div", "row lab-row");
      r.append(el("div", "lab-text", s.id + " - " + (s.description || "")), el("span", "state", "used " + (s.uses || 0) + "x"));
      list.append(r);
    }
    skills.append(list);
    box.append(skills);
  }
}
