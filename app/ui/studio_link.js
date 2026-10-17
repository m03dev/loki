// LOKI Studio lives OUTSIDE this window (its own app, like a game editor next to the game:
// studio/, docs/STUDIO.md). Here there is only the button that opens it.
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
  b.dataset.tipWhat = "Work on LOKI itself with DeepSeek V4.1 - opens LOKI Studio, its own app (works even when LOKI is down).";
  b.textContent = "LOKI Studio";
  b.addEventListener("click", async () => {
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
