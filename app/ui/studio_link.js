// LOKI Studio lives inside Home (home.js; owner 2026-10-21: "combine studio with home we dont need them both").
// This sidebar button opens it there; without the home hub it opens Studio's own window as before.
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const row = document.querySelector(".sidebar .foot-row");
  if (!row || document.getElementById("open-studio")) return;
  const b = document.createElement("button");
  b.type = "button";
  b.id = "open-studio";
  b.className = "quiet";
  b.dataset.icon = "studio";
  b.dataset.tipName = "LOKI Studio";
  b.dataset.tipWhat = "Work on LOKI itself with DeepSeek V4.1 - Studio opens inside Home (Ctrl/Cmd+Shift+S); Studio keeps its own server, so it works even when LOKI is down.";
  b.textContent = "LOKI Studio";
  b.addEventListener("click", async () => {
    if (window.LokiHome) { window.LokiHome.openStudio(); return; }
    b.disabled = true;
    try {
      const r = await api("/studio/open", {});   // app.js's api(): resolves with the JSON, never throws on HTTP errors
      if (r && r.ok) {
        if (typeof setStatus === "function") setStatus(r.note || "LOKI Studio is opening.", true);
      } else {
        alert("LOKI Studio did not open: " + ((r && r.error) || "no answer") + (r && r.how ? "\n\n" + r.how : ""));
      }
    } catch (e) {
      alert("LOKI Studio did not open: " + e.message);
    } finally {
      setTimeout(() => { b.disabled = false; }, 2500);
    }
  });
  row.append(b);
});
