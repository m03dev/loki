// Lab > Storage: how much LOKI uses, what may go and why, one click to clean, a trash you can restore (owner
// 2026-10-27: "what are we doing about data management i dont have that much space"). GET /storage (engine/storage.py:
// usage + the plan + the trash); POST /storage/clean {plan, ids} runs exactly what is ticked; /storage/restore {batch};
// /storage/empty-trash. Your outputs go to the trash first (emptied after 7 days); caches and code copies are deleted.
// Plain DOM, CSP script-src 'self'; api() from app.js.
"use strict";

const LokiStorage = (() => {
  const S = { root: null, data: null, pick: new Set(), busy: false, say: "" };
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.reject(new Error("not ready")));
  const fmt = (b) => (b >= 1e9 ? (b / 1e9).toFixed(1) + " GB" : b >= 1e6 ? (b / 1e6).toFixed(0) + " MB" : Math.max(1, Math.round(b / 1e3)) + " KB");
  const WHEN = { safe: "cleaned on its own", budget: "cleaned on its own when LOKI is over its budget" };

  function bar(used, total, cls) {
    const b = mk("div", "st-bar " + (cls || ""));
    const f = mk("i"); f.style.width = Math.min(100, total ? used / total * 100 : 0).toFixed(1) + "%";
    b.append(f);
    return b;
  }

  function render() {
    if (!S.root) return;
    S.root.replaceChildren();
    const d = S.data;
    if (!d || !d.ok) { S.root.append(mk("p", "tb-empty", d && d.error ? d.error : "Measuring…")); return; }
    const u = d.usage, p = d.plan;
    const head = mk("div", "st-head");
    head.append(mk("h3", "st-title", "LOKI uses " + fmt(u.total) + (u.budget ? " of its " + fmt(u.budget) + " budget" : "")),
      bar(u.total, u.budget, u.total > u.budget ? "over" : ""),
      mk("p", "st-line", "Free on this drive: " + fmt(u.free) + " of " + fmt(u.disk) + (u.ws_free != null ? " · workspace drive: " + fmt(u.ws_free) + " free" : "")
        + " · automatic clean-up: " + ({ off: "off", safe: "safe things only", budget: "on (drafts and caches too when over budget)" }[u.auto] || u.auto)));
    S.root.append(head);
    const areas = mk("div", "st-areas");
    const top = (u.areas || []).slice(0, 10), max = Math.max(1, ...top.map((a) => a.size));
    for (const a of top) {
      const r = mk("div", "st-area"); r.title = a.path;
      r.append(mk("span", "st-a-name", a.label), bar(a.size, max), mk("span", "st-a-size", fmt(a.size)));
      areas.append(r);
    }
    S.root.append(mk("h4", "st-h", "Where the space goes"), areas);
    S.root.append(mk("h4", "st-h", "What can go (" + fmt(p.frees) + ")"));
    const cats = Object.entries(p.categories || {});
    if (!cats.length) S.root.append(mk("p", "tb-empty", "Nothing to clean - LOKI only keeps what is worth keeping right now."));
    for (const [cat, c] of cats) {
      const items = p.items.filter((i) => i.category === cat);
      const box = mk("details", "st-cat"); box.open = cat !== "duplicates" && items.length < 8;
      const sum = mk("summary", "st-cat-sum");
      const tick = mk("input"); tick.type = "checkbox"; tick.checked = items.every((i) => S.pick.has(i.id));
      tick.addEventListener("click", (e) => { e.stopPropagation(); for (const i of items) (tick.checked ? S.pick.add(i.id) : S.pick.delete(i.id)); render(); });
      sum.append(tick, mk("span", "st-cat-name", c.label), mk("span", "st-cat-meta", c.count + " · " + fmt(c.size) + " · "
        + (c.kind === "regenerable" ? "deleted (comes back on its own)" : "to the trash first") + " · " + (WHEN[c.when] || "")));
      box.append(sum);
      for (const i of items.slice(0, 60)) {
        const row = mk("label", "st-item");
        const t = mk("input"); t.type = "checkbox"; t.checked = S.pick.has(i.id);
        t.addEventListener("change", () => { t.checked ? S.pick.add(i.id) : S.pick.delete(i.id); paintGo(); });
        row.append(t, mk("span", "st-i-path", i.rel || i.path.split(/[\\/]/).slice(-2).join("/")), mk("span", "st-i-why", i.why), mk("span", "st-a-size", fmt(i.size)));
        row.title = i.path;
        box.append(row);
      }
      if (items.length > 60) box.append(mk("p", "st-line", "… and " + (items.length - 60) + " more"));
      S.root.append(box);
    }
    const acts = mk("div", "st-acts");
    const go = mk("button", "send small st-go"); go.type = "button"; go.id = "st-go";
    go.addEventListener("click", clean);
    const all = mk("button", "quiet small", "Tick everything that cleans on its own"); all.type = "button";
    all.title = "Ticks the safe things and, when LOKI is over budget, its drafts and caches - what the automatic clean-up would take.";
    all.addEventListener("click", () => {
      const over = u.total > u.budget || u.free < u.min_free;
      for (const i of p.items) if (p.categories[i.category].when === "safe" || (over && i.category !== "duplicates")) S.pick.add(i.id);
      render();
    });
    acts.append(go, all);
    if (S.say) acts.append(mk("span", "st-say", S.say));
    S.root.append(acts);
    paintGo();
    if ((d.trash || []).length) {
      S.root.append(mk("h4", "st-h", "Trash (emptied after 7 days)"));
      for (const b of d.trash) {
        const r = mk("div", "st-area");
        const rest = mk("button", "quiet small", "Restore"); rest.type = "button";
        rest.title = "Put these " + b.items + " things back where they were.";
        rest.addEventListener("click", async () => { rest.disabled = true; const res = await call("/storage/restore", { batch: b.batch }).catch(() => null); S.say = res && res.ok ? "Restored " + res.restored + "." : "Could not restore: " + ((res && res.errors) || []).join("; "); refresh(); });
        r.append(mk("span", "st-a-name", b.batch.replace(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2}).*/, "$1-$2-$3 $4:$5") + " · " + b.items + " things"), mk("span", "st-a-size", fmt(b.size)), rest);
        S.root.append(r);
      }
      const empty = mk("button", "quiet small danger", "Empty the trash now"); empty.type = "button";
      empty.title = "Deletes everything in LOKI's trash for good.";
      let armed = false;
      empty.addEventListener("click", async () => {
        if (!armed) { armed = true; empty.textContent = "Click again to delete for good"; setTimeout(() => { armed = false; empty.textContent = "Empty the trash now"; }, 4000); return; }
        await call("/storage/empty-trash", {}).catch(() => null); S.say = "The trash is empty."; refresh();
      });
      S.root.append(empty);
    }
  }

  function paintGo() {
    const go = document.getElementById("st-go");
    if (!go || !S.data || !S.data.plan) return;
    const items = S.data.plan.items.filter((i) => S.pick.has(i.id));
    go.disabled = S.busy || !items.length;
    go.textContent = S.busy ? "Cleaning…" : items.length ? "Clean up " + items.length + " (frees " + fmt(items.reduce((n, i) => n + i.size, 0)) + ")" : "Tick what may go";
  }

  async function clean() {
    if (!S.data || S.busy) return;
    S.busy = true; paintGo();
    const res = await call("/storage/clean", { plan: S.data.plan.id, ids: [...S.pick] }).catch((e) => ({ ok: false, errors: [String(e)] }));
    S.busy = false; S.pick.clear();
    S.say = res && res.removed != null ? "Freed " + fmt(res.freed || 0) + " (" + res.removed + " things" + (res.batch ? "; yours are in the trash - Restore below" : "") + ")."
      + ((res.errors || []).length ? " Not touched: " + res.errors.slice(0, 2).join("; ") : "") : "Could not clean: " + ((res && (res.error || (res.errors || []).join("; "))) || "?");
    refresh();
  }

  async function refresh() {
    S.data = await call("/storage").catch((e) => ({ ok: false, error: String(e) }));
    render();
  }

  function open(container) {
    if (!S.root || S.root.parentNode !== container) { S.root = mk("section", "st"); S.root.setAttribute("aria-label", "Storage"); container.replaceChildren(S.root); }
    render(); refresh();
  }
  function leave() { /* nothing polls */ }
  return { open, leave, refresh, data: () => S.data };
})();
window.LokiStorage = LokiStorage;
