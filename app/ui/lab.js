// Settings > Lab: LOKI growing its own personal-agent core (engine/evolve.py, docs/EVOLVE.md).
// GET /evolve lists the steps (your ideas first), what happened to each, and the lessons the
// next attempt is given; POST /evolve/idea adds your idea, /evolve/start starts the next step
// now, /evolve/approve accepts or declines an idea LOKI proposed. Plain DOM (CSP).
"use strict";

function labChip(item, isNext) {
  const last = item.last || {};
  if (item.done) return el("span", "state ready", item.declined ? "declined" : "done");
  if (item.approved === false) return el("span", "state", "waiting for your OK");
  if (last.outcome === "started") return el("span", "state working", "LOKI is building it");
  if (last.outcome === "failed") return el("span", "state warn", "did not ship - will retry");
  return el("span", "state", isNext ? "next up" : "planned");
}

async function loadLab() {
  const box = document.getElementById("lab-panel");
  if (!box) return;
  const data = await api("/evolve").catch(() => null);
  box.replaceChildren();
  if (!data || !data.ok) { box.append(el("p", "note", (data && data.error) || "The Lab is not running in this engine.")); return; }

  const head = el("div", "lab-head");
  head.append(el("b", "", data.enabled ? "On: LOKI works on the next step when it is idle." : "Off on this machine (LOKI_EVOLVE in Settings > General; auto = the Windows PC only)."));
  const go = el("button", "send", "Start the next step now");
  go.type = "button";
  go.addEventListener("click", async () => {
    go.disabled = true;
    const r = await api("/evolve/start", {}).catch(() => null);
    addNotice((r && (r.line || r.error)) || "Could not start it.", !(r && r.ok));
    loadLab();
  });
  head.append(go);
  box.append(head);

  const form = el("form", "lab-idea");
  const input = el("input");
  input.placeholder = "An idea for LOKI to build into itself…";
  input.setAttribute("aria-label", "Your idea");
  const add = el("button", "", "Add idea");
  add.type = "submit";
  form.append(input, add);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const r = await api("/evolve/idea", { text: input.value }).catch(() => null);
    if (!r || !r.ok) addNotice((r && r.error) || "Could not add it.", true);
    loadLab();
  });
  box.append(form);

  const rows = el("div", "rows");
  for (const item of data.items || []) {
    const r = el("div", "row lab-row" + (item.done ? " done" : "") + (item.id === data.next ? " next" : ""));
    const text = el("div", "lab-text");
    text.append(el("b", "", item.id + (item.source === "owner" ? " · your idea" : item.source === "loki" ? " · LOKI's idea" : "")),
      el("span", "", " " + item.title));
    const right = el("div", "lab-right");
    right.append(labChip(item, item.id === data.next));
    if (item.approved === false && !item.done) {
      for (const [label, yes] of [["Build it", true], ["No", false]]) {
        const b = el("button", "mini", label);
        b.type = "button";
        b.addEventListener("click", async () => { await api("/evolve/approve", { id: item.id, yes }).catch(() => null); loadLab(); });
        right.append(b);
      }
    }
    r.append(text, right);
    rows.append(r);
  }
  box.append(rows);

  const learned = el("details", "lab-lessons");
  learned.append(el("summary", "", "What LOKI learned from earlier attempts"), el("pre", "", data.lessons || ""));
  box.append(learned);
  if ((data.log || []).length) {
    const log = el("details", "lab-lessons");
    log.append(el("summary", "", "Recent activity"), el("pre", "", data.log.map((e) => new Date(e.t * 1000).toLocaleString() + "  " + e.text).join("\n")));
    box.append(log);
  }
}
