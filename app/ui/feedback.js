// Settings > General > Send feedback (session 30, the friends test - docs/TESTERS.md).
// Saves a zip of LOKI's logs with keys, tokens and chats removed (engine/feedback.py), shows it in
// the file manager, and opens a prefilled GitHub issue or an email draft to attach it to. LOKI uploads
// nothing itself. The card adds itself to the General panel whenever settings.js (re)draws it.
"use strict";

(function () {
  const tr = (key, en, vars) => (window.LokiI18n ? window.LokiI18n.t(key, en, vars) : en);
  function node(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function card() {
    const c = node("section", "set-card fb-card");
    c.id = "fb-card";
    c.setAttribute("aria-labelledby", "fb-title");
    const h = node("b", "", tr("fb.title", "Send feedback"));
    h.id = "fb-title";
    c.append(h, node("p", "note", tr("fb.why", "Something broke, felt slow or confusing? Tell us. LOKI saves a small file with its logs for you to attach - you see it before anything is sent.")));
    const text = node("textarea");
    text.id = "fb-note";
    text.placeholder = tr("fb.placeholder", "What happened? What did you expect?");
    text.setAttribute("aria-label", tr("fb.note", "What happened"));
    const logsLabel = node("label", "check");
    const logs = node("input");
    logs.type = "checkbox";
    logs.checked = true;
    logs.id = "fb-logs";
    logsLabel.append(logs, document.createTextNode(" " + tr("fb.logs", "Include LOKI's logs (no keys, no chats)")));
    const row = node("div", "fb-row");
    const out = node("p", "u-say");
    out.setAttribute("role", "status");
    out.setAttribute("aria-live", "polite");
    const send = async (how) => {
      for (const b of row.querySelectorAll("button")) b.disabled = true;
      out.textContent = tr("fb.saving", "Saving the feedback file…");
      out.className = "u-say";
      let r = null;
      try { r = await api("/feedback/send", { how, note: text.value, logs: logs.checked }); } catch (e) { r = { ok: false, error: String(e) }; }
      for (const b of row.querySelectorAll("button")) b.disabled = false;
      if (!r || !r.ok) {
        out.textContent = tr("fb.failed", "Could not save it: {error}. You can still write to us on GitHub (m03dev/loki, Issues).", { error: (r && r.error) || "?" });
        out.className = "u-say bad";
        return;
      }
      const where = r.zip || "";
      out.textContent = how === "github" ? tr("fb.github_done", "Saved {file}. A new GitHub issue opened in your browser - drag the file into it and press Submit.", { file: where })
        : how === "email" ? tr("fb.email_done", "Saved {file}. An email draft opened - attach the file and send it.", { file: where })
          : tr("fb.folder_done", "Saved {file}.", { file: where });
      out.className = "u-say ok";
    };
    for (const [how, key, en, cls] of [["github", "fb.github", "Open a GitHub issue", "send"], ["email", "fb.email", "Write an email", "quiet"],
      ["folder", "fb.folder", "Only save the file", "quiet"]]) {
      const b = node("button", cls, tr(key, en));
      b.type = "button";
      b.addEventListener("click", () => send(how));
      row.append(b);
    }
    c.append(text, logsLabel, row, out,
      node("p", "fb-never", tr("fb.never", "Never included: keys and tokens, your chats, LOKI's memory, your files, the settings file.")));
    return c;
  }

  function attach() {
    const box = document.getElementById("general-panel");
    if (!box || box.querySelector("#fb-card") || !box.children.length) return;
    box.append(card());
  }

  document.addEventListener("DOMContentLoaded", () => {
    const box = document.getElementById("general-panel");
    if (!box) return;
    new MutationObserver(attach).observe(box, { childList: true });
    attach();
  });
  window.LokiFeedback = { attach };
})();
