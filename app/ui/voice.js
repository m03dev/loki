// Voice (EVOLVE E7): push-to-talk in the message box and optional spoken replies.
//
// Mic button: hold it and talk, let go and the words appear in the message box (Enter sends).
// A short click starts listening and the next click stops (Esc cancels). Speech to text is
// local Whisper when it is installed (engine/voice_input.py: faster-whisper or whisper.cpp; the
// window records 16 kHz mono WAV itself with WebAudio, so WebView2 and WKWebView send the same
// thing), else the webview's own speech recognition when it has one (WebView2 often has the
// object but no speech service; WKWebView may not have it at all) - and when neither works the
// window says how to install Whisper. Speaker button: replies are read aloud (Kokoro on the
// engine when installed, else the window's own speechSynthesis, else the computer's voice).
//
// Microphone permission: WebView2 shows its own "allow microphone" prompt the first time and
// remembers it in LOKI's webview profile; Windows also needs Settings > Privacy & security >
// Microphone > "Let desktop apps access your microphone". WKWebView asks per page load unless
// pywebview answers for it, and macOS asks once for Loki.app (its Info.plist carries
// NSMicrophoneUsageDescription - tools/macos/make_loki_app.sh). Errors say exactly which.
"use strict";

const Voice = (() => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition || null;
  const HOLD_MS = 400, MAX_MS = 5 * 60 * 1000, RATE = 16000;
  let status = null, statusAt = 0;
  let rec = null;          // {kind: "wav"|"sr", stop(cancel), started}
  let downAt = 0, micBtn = null, spkBtn = null, player = null, busy = false;
  let speakOn = false;
  try { speakOn = localStorage.getItem("loki.speakReplies") === "1"; } catch (_) { /* storage blocked */ }

  const isMac = /Mac/i.test(navigator.platform || navigator.userAgent || "");

  function notice(text, isError) {
    if (typeof addNotice === "function") addNotice(text, isError);
  }

  async function loadStatus(force) {
    if (!force && status && Date.now() - statusAt < 60000) return status;
    try {
      const r = await api("/voice");
      if (r && r.ok) { status = r; statusAt = Date.now(); }
    } catch (_) { /* engine not reachable: browser fallbacks only */ }
    return status;
  }

  function hasWhisper() { return !!(status && status.stt && status.stt.engine); }

  function permissionHelp(err) {
    const name = err && err.name || "";
    if (name === "NotAllowedError" || name === "SecurityError" || name === "not-allowed" || name === "service-not-allowed")
      return isMac
        ? "LOKI may not use the microphone. Allow it: System Settings > Privacy & Security > Microphone > Loki (if Loki is missing there, rebuild it with tools/macos/make_loki_app.sh), then press the mic again."
        : "LOKI may not use the microphone. Allow it: Windows Settings > Privacy & security > Microphone > turn on \"Let desktop apps access your microphone\", and say Allow when the window asks.";
    if (name === "NotFoundError" || name === "audio-capture") return "No microphone found on this computer.";
    if (name === "network") return "This window's speech recognition has no speech service here. Install Whisper for local speech to text: Settings > Add-ons > whisper.";
    return "The microphone did not start: " + (err && (err.message || err.error || err.name) || "unknown error");
  }

  function setMicState(on, label) {
    if (!micBtn) return;
    micBtn.classList.toggle("recording", on);
    micBtn.setAttribute("aria-pressed", on ? "true" : "false");
    micBtn.dataset.tipName = on ? "Listening..." : "Talk";
    micBtn.dataset.tipWhat = on ? (label || "Let go (or click again) to stop; Esc cancels.") : tipWhat();
  }

  function tipWhat() {
    const how = hasWhisper() ? "Whisper on this computer" : (SR ? "this window's speech recognition" : "Whisper once installed (Settings > Add-ons > whisper)");
    return "Hold and talk, let go to stop - or click to start and click again. The words appear in the message box. Uses " + how + ".";
  }

  function putText(text) {
    const box = document.getElementById("prompt");
    text = String(text || "").trim();
    if (!box || !text) return;
    const before = box.value && !/\s$/.test(box.value) ? box.value + " " : box.value;
    box.value = before + text;
    box.dispatchEvent(new Event("input", { bubbles: true }));
    box.focus();
  }

  // ------------------------------------------------------------ WAV recording (for Whisper)
  function downsample(samples, from) {
    if (from === RATE) return samples;
    const ratio = from / RATE, out = new Float32Array(Math.floor(samples.length / ratio));
    for (let i = 0; i < out.length; i++) {
      const start = Math.floor(i * ratio), end = Math.min(samples.length, Math.floor((i + 1) * ratio));
      let sum = 0; for (let j = start; j < end; j++) sum += samples[j];
      out[i] = sum / Math.max(1, end - start);
    }
    return out;
  }

  function encodeWav(samples) {
    const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
    const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE"); str(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, RATE, true);
    v.setUint32(28, RATE * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data");
    v.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  function dataUrl(blob) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).replace(/^data:audio\/wav[^,]*,/, "data:audio/wav;base64,"));
      r.onerror = () => reject(r.error);
      r.readAsDataURL(blob);
    });
  }

  async function startWav() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    if (ctx.state === "suspended") { try { await ctx.resume(); } catch (_) { /* resumes on the gesture */ } }
    const src = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const chunks = [];
    let length = 0;
    proc.onaudioprocess = (e) => { const c = new Float32Array(e.inputBuffer.getChannelData(0)); chunks.push(c); length += c.length; };
    src.connect(proc); proc.connect(ctx.destination);   // Chromium only runs a connected processor (it outputs silence)
    const timer = setTimeout(() => finish(false), MAX_MS);
    async function stop(cancel) {
      clearTimeout(timer);
      try { proc.disconnect(); src.disconnect(); } catch (_) { /* already */ }
      stream.getTracks().forEach((t) => t.stop());
      const rate = ctx.sampleRate;
      try { await ctx.close(); } catch (_) { /* closed */ }
      if (cancel || length < rate * 0.3) return null;   // under 0.3 s: nothing said
      const all = new Float32Array(length);
      let at = 0; for (const c of chunks) { all.set(c, at); at += c.length; }
      return encodeWav(downsample(all, rate));
    }
    return { kind: "wav", stop, started: Date.now() };
  }

  // ------------------------------------------------------------ the webview's own recognition
  function startSR() {
    const r = new SR();
    r.lang = navigator.language || "en-US";
    r.interimResults = true;
    r.continuous = true;
    const box = document.getElementById("prompt");
    const base = box ? (box.value && !/\s$/.test(box.value) ? box.value + " " : box.value) : "";
    let finalText = "", failed = null;
    r.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript; else interim += e.results[i][0].transcript;
      }
      if (box) { box.value = base + finalText + interim; box.dispatchEvent(new Event("input", { bubbles: true })); }
    };
    r.onerror = (e) => { failed = e; if (e.error !== "aborted" && e.error !== "no-speech") notice(permissionHelp({ name: e.error, error: e.error }), true); };
    r.onend = () => { if (rec && rec.kind === "sr") { rec = null; setMicState(false); } };
    r.start();
    return {
      kind: "sr", started: Date.now(),
      stop: async (cancel) => { try { cancel ? r.abort() : r.stop(); } catch (_) { /* ended */ } if (cancel && box) box.value = base.trimEnd(); return failed ? null : "sr"; },
    };
  }

  // ------------------------------------------------------------ start / stop
  async function start() {
    if (rec || busy) return;
    stopSpeaking();
    await loadStatus(false);
    const canRecord = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    try {
      if (hasWhisper() && canRecord) rec = await startWav();
      else if (SR) rec = startSR();
      else {
        notice(canRecord
          ? "To talk to LOKI, install Whisper (speech to text on this computer): Settings > Add-ons > whisper. This window has no speech recognition of its own."
          : "This window cannot use a microphone. Install Whisper (Settings > Add-ons > whisper) and use a recent LOKI window.", true);
        return;
      }
      setMicState(true);
    } catch (err) {
      rec = null;
      setMicState(false);
      notice(permissionHelp(err), true);
    }
  }

  async function finish(cancel) {
    const current = rec;
    if (!current) return;
    rec = null;
    setMicState(false);
    const result = await current.stop(cancel);
    if (!result || current.kind !== "wav") return;
    busy = true;
    if (micBtn) micBtn.classList.add("working");
    try {
      const r = await api("/voice/transcribe", { audio: await dataUrl(result) });
      if (r.ok) { if (String(r.text || "").trim()) putText(r.text); else notice("I did not catch any words - try again a little closer to the mic.", false); }
      else notice(r.error || "Whisper could not turn that into text.", true);
    } catch (err) {
      notice("Could not reach the LOKI engine for speech to text.", true);
    } finally {
      busy = false;
      if (micBtn) micBtn.classList.remove("working");
    }
  }

  // ------------------------------------------------------------ spoken replies
  function plain(text) {
    return String(text || "").replace(/```[\s\S]*?```/g, " (code shown on screen) ").replace(/`([^`]*)`/g, "$1")
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/^[#>\-*\s]+/gm, "").replace(/\*\*|__/g, "").replace(/\s+/g, " ").trim().slice(0, 1500);
  }

  function stopSpeaking() {
    if (player) { try { player.pause(); } catch (_) { /* gone */ } player = null; }
    if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (_) { /* none */ } }
  }

  async function speak(text) {
    const words = plain(text);
    if (!words) return;
    stopSpeaking();
    await loadStatus(false);
    const kokoro = status && status.tts && status.tts.kokoro;
    if (!kokoro && window.speechSynthesis && window.SpeechSynthesisUtterance) {
      const u = new SpeechSynthesisUtterance(words);
      u.lang = navigator.language || "en-US";
      window.speechSynthesis.speak(u);
      return;
    }
    const r = await api("/voice/speak", { text: words }).catch(() => null);
    if (!r || !r.ok) { notice((r && r.error) || "LOKI could not read that aloud.", true); return; }
    player = new Audio(r.audio);
    player.play().catch(() => notice("The reply could not be played here.", true));
  }

  function afterReply(text) { if (speakOn) speak(text); }

  function setSpeak(on) {
    speakOn = on;
    try { localStorage.setItem("loki.speakReplies", on ? "1" : "0"); } catch (_) { /* storage blocked */ }
    if (!on) stopSpeaking();
    if (!spkBtn) return;
    spkBtn.dataset.icon = on ? "speaker" : "speakerOff";
    if (typeof iconSvg === "function" && spkBtn.dataset.iconDone) spkBtn.innerHTML = iconSvg(spkBtn.dataset.icon);
    spkBtn.classList.toggle("on", on);
    spkBtn.setAttribute("aria-pressed", on ? "true" : "false");
    spkBtn.dataset.tipName = on ? "Spoken replies: on" : "Spoken replies: off";
    spkBtn.dataset.tipWhat = on ? "LOKI reads its replies aloud. Click to keep them written only." : "Click to have LOKI read its replies aloud.";
  }

  // ------------------------------------------------------------ wiring
  function button(id, icon, name, what) {
    const b = document.createElement("button");
    b.type = "button"; b.id = id; b.className = "quiet voice-btn";
    b.dataset.icon = icon; b.dataset.tipName = name; b.dataset.tipWhat = what;
    b.textContent = name;   // icons.js swaps the words for the icon (aria-label keeps them)
    return b;
  }

  function wire() {
    const row = document.querySelector(".composer-row");
    if (!row || document.getElementById("mic")) return;
    micBtn = button("mic", "mic", "Talk", tipWhat());
    micBtn.setAttribute("aria-pressed", "false");
    spkBtn = button("speak-replies", speakOn ? "speaker" : "speakerOff", "Spoken replies", "");
    const before = document.getElementById("stop") || document.getElementById("send");
    row.insertBefore(micBtn, before);
    row.insertBefore(spkBtn, before);
    setSpeak(speakOn);

    micBtn.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      if (rec) { finish(false); downAt = 0; return; }   // second click of click-to-talk
      downAt = Date.now();
      start();
    });
    const release = () => { if (rec && downAt && Date.now() - downAt >= HOLD_MS) finish(false); downAt = 0; };
    micBtn.addEventListener("pointerup", release);
    micBtn.addEventListener("pointerleave", () => { if (downAt) release(); });
    micBtn.addEventListener("click", (e) => { if (e.detail === 0) { if (rec) finish(false); else start(); } });   // keyboard
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && rec) finish(true); });
    spkBtn.addEventListener("click", () => setSpeak(!speakOn));
    loadStatus(true).then(() => { if (!rec) setMicState(false); });
  }

  document.addEventListener("DOMContentLoaded", wire);
  return { afterReply, speak, start, finish, status: () => status, recording: () => !!rec, setSpeak, hasRecognition: () => !!SR };
})();
window.Voice = Voice;
