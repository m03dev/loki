// Settings > Your data (research round 3): what LOKI keeps and where, which model providers got your
// messages in the last 30 days, a backup you can restore, and clearing one kind of data.
// Engine: engine/your_data.py via engine/assist_api.py (GET /data, POST /data/backup|restore|clear).
// Also registers the extra icons the research-3 buttons use (icons.js reads ICON_PATHS/TAB_ICONS by name).
"use strict";

Object.assign(ICON_PATHS, {
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8"/>',
  branch: '<circle cx="6" cy="5.5" r="2"/><circle cx="6" cy="18.5" r="2"/><circle cx="18" cy="8" r="2"/><path d="M6 7.5v9M18 10c0 4-6 3.5-11 7"/>',
  save: '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
  expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  code: '<path d="M9 7l-5 5 5 5M15 7l5 5-5 5"/>',
  dots: '<circle cx="5.5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="18.5" cy="12" r="1.4"/>',
  library: '<path d="M5 4h3v16H5zM10 4h3v16h-3z"/><path d="M15.5 5.2l2.9-.8 3.4 15-2.9.8z"/>',
  vault: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M12 9v1M12 14v1M9 12h1M14 12h1"/>',
});
TAB_ICONS.data = ["vault", "What LOKI keeps and where, what left this computer, backups and restore."];

function fmtBytes(n) {
  n = +n || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(1) + " GB";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + " MB";
  if (n >= 1e3) return Math.round(n / 1e3) + " KB";
  return n + " B";
}

async function loadDataPanel() {
  const box = document.getElementById("data-panel");
  if (!box) return;
  const data = await api("/data").catch(() => null);
  box.replaceChildren();
  if (!data || !data.ok) { box.append(el("p", "note", (data && data.error) || "This engine cannot show your data.")); return; }
  const s = data.summary || {};
  const top = el("div", "data-summary");
  const tile = (big, small) => { const t = el("div", "data-tile"); t.append(el("b", "", big), el("span", "", small)); return t; };
  top.append(tile(fmtBytes(s.bytes), "kept on this computer"), tile(String(data.chats.count), "chats"),
    tile(String(s.local_calls_30d || 0), "answers from local models (30 days)"),
    tile(String(s.cloud_calls_30d || 0), "messages sent to cloud models (30 days)"));
  box.append(top);
  const facts = el("ul", "data-facts");
  for (const f of data.facts || []) facts.append(el("li", "", f));
  box.append(facts);

  box.append(el("h4", "", "Who got your messages (last 30 days)"));
  if (!(data.providers || []).length) box.append(el("p", "note", "No model calls in the last 30 days."));
  else {
    const rows = el("div", "rows");
    for (const p of data.providers) {
      const r = el("div", "row data-row");
      r.append(el("span", "", p.provider), el("span", "state " + (p.local ? "ready" : "warn"), p.local ? "on this computer" : "cloud"),
        el("span", "", p.calls + " calls · " + Math.round((p.tokens_in + p.tokens_out) / 1000) + "k tokens"));
      rows.append(r);
    }
    box.append(rows);
  }

  box.append(el("h4", "", "Where it is kept"));
  box.append(el("p", "note", data.data_dir + "  ·  chats: " + data.chats.path));
  const places = el("div", "rows");
  for (const p of data.places || []) {
    const r = el("div", "row data-row");
    r.append(el("span", "", p.name), el("span", "note", p.what), el("span", "", fmtBytes(p.bytes) + (p.secret ? " · secret" : p.backed_up ? "" : " · not backed up")));
    places.append(r);
  }
  box.append(places);

  box.append(el("h4", "", "Backups"));
  box.append(el("p", "note", "A backup is one zip in " + data.backup_dir + ": your chats, memory, settings, CRM, prompts, tools LOKI wrote and the rest - not the local models or LOKI's Python (they download again). Copy it to another disk or the other machine to be safe."));
  const brow = el("div", "data-actions");
  const keys = el("label", "check"); const kb = document.createElement("input"); kb.type = "checkbox"; keys.append(kb, document.createTextNode(" include my keys (.env) - keep that zip private"));
  const go = el("button", "send small", "Back up now"); go.type = "button";
  go.dataset.icon = "save"; go.dataset.tipName = "Back up now"; go.dataset.tipWhat = "Make one zip of LOKI's data now.";
  go.addEventListener("click", async () => {
    go.disabled = true;
    const out = await api("/data/backup", { secrets: kb.checked }).catch((e) => ({ ok: false, error: String(e) }));
    go.disabled = false;
    if (!out.ok) { alert(out.error || "The backup failed."); return; }
    loadDataPanel();
  });
  brow.append(go, keys);
  box.append(brow);
  const list = el("div", "rows");
  for (const b of data.backups || []) {
    const r = el("div", "row data-row");
    const when = new Date((b.created || 0) * 1000).toLocaleString();
    r.append(el("span", "", when), el("span", "note", (b.machine || "") + " · " + b.files + " files · " + fmtBytes(b.bytes) + (b.secrets ? " · with keys" : "")));
    const restore = el("button", "quiet small", "Restore"); restore.type = "button";
    restore.disabled = !b.valid;
    restore.addEventListener("click", async () => {
      if (!confirm("Restore LOKI's data from " + when + "?\nFiles in the backup replace today's (a safety backup of now is made first). Restart LOKI afterwards.")) return;
      const out = await api("/data/restore", { name: b.name, confirm: true });
      alert(out.ok ? "Restored " + out.restored + " files. " + out.note : (out.error || "Restore failed."));
      loadDataPanel();
    });
    r.append(restore);
    list.append(r);
  }
  if (!(data.backups || []).length) list.append(el("p", "note", "No backups yet."));
  box.append(list);

  box.append(el("h4", "", "Clear"));
  const crow = el("div", "data-actions");
  for (const [kind, label] of Object.entries(data.clearable || {})) {
    const b = el("button", "quiet small", "Clear " + label); b.type = "button";
    b.addEventListener("click", async () => {
      if (!confirm("Delete " + label + " for good? (Back up first if you may want it.)")) return;
      const out = await api("/data/clear", { kind, confirm: true });
      if (!out.ok) alert(out.error || "Not cleared.");
      if (kind === "chats" && typeof loadConversations === "function") loadConversations();
      loadDataPanel();
    });
    crow.append(b);
  }
  box.append(crow);
}

document.addEventListener("DOMContentLoaded", () => {
  const tab = document.querySelector('.tabs button[data-tab="data"]');
  if (tab) tab.addEventListener("click", () => loadDataPanel());
});
