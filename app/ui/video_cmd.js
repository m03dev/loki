/* Type a line, get a video (owner 2026-10-27: "there needs to be a way where I can just type something and it renders a
   video"). In the chat box:  /video a red fox running through snow at dusk   (add "5s" for five seconds).
   Goes straight to engine/text_video.py (no model in between): on the Mac it is rendered on the PC and comes back into
   Home's library; the chat shows where it runs, the time so far, then plays it. */
const LokiVideo = (() => {
  const RE = /^\s*\/(video|render)\s+([\s\S]+)$/i;
  function handles(text) { return RE.test(String(text || "")); }

  function parse(text) {
    let words = String(text).match(RE)[2].trim(), seconds = 3;
    const m = words.match(/(?:^|\s)(\d{1,2})\s*s(?:ec(?:onds?)?)?\s*$/i);
    if (m) { seconds = Math.max(1, Math.min(8, +m[1])); words = words.slice(0, m.index).trim(); }
    return { prompt: words, seconds };
  }

  function bubble() {
    const turn = document.createElement("div"); turn.className = "turn loki lk-video";
    const body = document.createElement("div"); body.className = "text";
    turn.append(body); document.getElementById("transcript").append(turn);
    return body;
  }

  async function run(text) {
    const { prompt, seconds } = parse(text);
    if (typeof addUser === "function") addUser(text.trim());
    const body = bubble();
    const say = (t) => { body.textContent = t; if (typeof scrollDown === "function") scrollDown(); };
    if (!prompt) { say("Say what the video shows, e.g. /video a red fox running through snow at dusk"); return; }
    say("Starting the video…");
    let r;
    try { r = await api("/video/make", { prompt, seconds }); } catch (e) { say("Could not start: " + e.message); return; }
    if (!r || !r.ok) { say((r && r.error) || "Could not start the video."); return; }
    const id = r.job.id, where = r.where === "here" ? "this machine" : r.where, t0 = Date.now();
    for (;;) {
      await new Promise((ok) => setTimeout(ok, 4000));
      const s = Math.round((Date.now() - t0) / 1000);
      say("Rendering on " + where + " (" + (r.engine || "Wan VACE") + ") - " + (s < 90 ? s + " s" : Math.round(s / 60) + " min") + " so far");
      let jobs;
      try { jobs = (await api("/video/jobs")).jobs || []; } catch (e) { continue; }
      const job = jobs.find((j) => j.id === id);
      if (!job || job.status === "working") continue;
      if (job.status === "failed") { say("The video failed: " + (job.error || "no reason given")); return; }
      body.replaceChildren();
      const v = document.createElement("video");
      v.src = "/creations/" + job.rel; v.controls = true; v.autoplay = true; v.loop = true; v.muted = true; v.playsInline = true;
      v.className = "lk-video-player";
      const cap = document.createElement("div"); cap.className = "lk-video-cap";
      cap.textContent = job.size + ", " + job.frames + " frames, " + job.machine + ", " + Math.round(job.seconds_taken) + " s - saved in Home > videos";
      body.append(v, cap);
      if (window.LokiHome && LokiHome.refresh) LokiHome.refresh();
      if (typeof scrollDown === "function") scrollDown(true);
      return;
    }
  }
  return { handles, run, parse };
})();
window.LokiVideo = LokiVideo;
