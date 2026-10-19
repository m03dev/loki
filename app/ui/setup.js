// Loki UI: first-run model setup, the credits meter, and your agents.
// Uses helpers from app.js ($, el, api, addNotice, setStatus, refreshJobs).
"use strict";

const setupView = { timer: 0, last: null };

function fmtTokens(n) {
  n = Number(n) || 0;
  return n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n);
}
function fmtCost(c) {
  c = Number(c) || 0;
  return c === 0 ? "free" : c < 0.01 ? "$" + c.toFixed(4) : "$" + c.toFixed(2);
}
function gb(n) { return (Number(n) || 0).toFixed(n >= 10 ? 0 : 1) + " GB"; }

// ---------------------------------------------------------------- credits meter
function showMeter(usage) {
  if (!usage || !usage.line) return;
  const turns = document.querySelectorAll("#transcript .turn.loki");
  const host = turns[turns.length - 1] || $("#transcript");
  host.append(el("div", "meter", usage.line));
  refreshUsagePill();
}

async function refreshUsagePill() {
  const data = await api("/usage").catch(() => null);
  const pill = $("#usage-pill");
  if (!data || !data.ok) { pill.textContent = "—"; return; }
  const today = data.today || {};
  pill.textContent = today.calls ? fmtCost(today.cost) + " today · " + fmtTokens((today.in || 0) + (today.out || 0)) + " tok" : "Usage";
  pill.classList.toggle("paid", (today.cost || 0) > 0);
}

async function loadUsageTab() {
  const data = await api("/usage").catch(() => null);
  const box = $("#usage-panel");
  box.replaceChildren();
  if (!data || !data.ok) { box.append(el("p", "note", "Usage is not available.")); return; }
  const grid = el("div", "usage-grid");
  const card = (value, label) => { const c = el("div", "usage-card"); c.append(el("b", "", value), el("span", "", label)); return c; };
  grid.append(card(fmtCost(data.today.cost), "today"), card(fmtTokens(data.today.in + data.today.out), "tokens today"),
              card(fmtCost(data.month.cost), "last 30 days"), card(String(data.month.calls), "model calls (30 days)"));
  box.append(grid);
  const table = el("table", "usage");
  const head = el("tr");
  for (const h of ["Provider", "Model", "Calls", "Tokens in / out", "Speed", "Cost"]) head.append(el("th", "", h));
  table.append(head);
  for (const [name, row] of Object.entries(data.by_provider || {})) {
    const tr = el("tr");
    tr.append(el("td", "", name), el("td", "", row.model || ""), el("td", "", String(row.calls)),
              el("td", "", fmtTokens(row.in) + " / " + fmtTokens(row.out)),
              el("td", "", row.avg_tps ? row.avg_tps + " tok/s" : "—"), el("td", "", fmtCost(row.cost)));
    table.append(tr);
  }
  if (!Object.keys(data.by_provider || {}).length) box.append(el("p", "note", "No model calls yet."));
  else box.append(table);
}

// ---------------------------------------------------------------- model setup
function setupButton(cls, text, onClick) {
  const b = el("button", cls, text);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

// A warning line (styled from here: app.css belongs to another change).
function warnNote(text) {
  const n = el("p", "note warn", text);
  n.style.color = "var(--warn)";
  return n;
}

// "This computer": chip/GPU, memory, free disk and what is running, in plain words.
function machineCard(data) {
  const sc = data.scan || data.hardware || {};
  const card = el("div", "setup-step machine-card");
  card.append(el("h3", "", "This computer"));
  let chip;
  if (sc.accel === "nvidia" || sc.vram_gb) {
    chip = (sc.gpu || "NVIDIA GPU") + " with " + gb(sc.vram_gb) + " of graphics memory" +
      (sc.vram_free_gb ? " (" + gb(sc.vram_free_gb) + " free right now)" : "");
  } else if (sc.unified) {
    chip = (sc.chip || "Apple Silicon") + " with " + gb(sc.ram_gb) + " of unified memory (shared by the chip and the AI)";
  } else {
    chip = (sc.chip || "Processor") + " - no graphics card for AI, so models run on the processor";
  }
  card.append(el("p", "note", chip));
  const facts = [gb(sc.ram_gb) + " memory"];
  if (sc.cpu_cores) facts.push(sc.cpu_cores + " CPU cores");
  if (sc.os_name) facts.push(sc.os_name);
  card.append(el("p", "note", facts.join(" · ")));
  const disk = sc.disk || {};
  if (disk.free_gb !== null && disk.free_gb !== undefined) {
    const low = disk.free_gb < 10;
    const line = "Free disk space for models: " + gb(disk.free_gb);
    card.append(low ? warnNote(line + " - that is tight. Models need several GB, and a full disk can break things.")
      : el("p", "note", line));
  }
  const running = sc.running || [];
  const lines = running.map((r) => r.label + (r.models && r.models.length ? " (" + r.models.slice(0, 3).join(", ") + (r.models.length > 3 ? ", …" : "") + ")" : ""));
  card.append(el("p", "note", lines.length ? "Running now: " + lines.join(" · ") : "No local model app is running yet."));
  const extras = [];
  if (sc.mlx && sc.mlx.installed && !sc.mlx.running) extras.push("MLX is installed");
  if (sc.llamacpp && sc.llamacpp.installed && !sc.llamacpp.running) extras.push("llama.cpp is installed");
  if (sc.ollama_installed && !running.some((r) => r.label === "Ollama")) extras.push("Ollama is installed but not open");
  if (extras.length) card.append(el("p", "note", extras.join(" · ") + "."));
  return card;
}

// Download (if needed) and switch to one model, in one click.
async function downloadAndUse(tag, box, compact) {
  const r = await api("/setup/upgrade", { tag });
  if (!r.ok) { addNotice(r.error || "Could not start the download.", true); return false; }
  if (box) watchProgress(box, compact);
  return true;
}

function renderSetup(box, data, compact) {
  box.replaceChildren();
  box.append(machineCard(data));
  const busy = (data.progress || {}).op && !(data.progress || {}).done;

  const active = data.active || {};
  if (active.local) {
    const ok = el("div", "setup-step ok");
    ok.append(el("h3", "", "Running offline on " + active.local),
              el("p", "note", (active.local_note || "") + (active.online ? "" : " · no internet right now - Loki is staying local.")));
    const prefer = el("label", "check");
    const box2 = el("input");
    box2.type = "checkbox";
    box2.checked = active.prefer !== "cloud";
    box2.addEventListener("change", async () => {
      const r = await api("/setup/prefer", { prefer: box2.checked ? "local" : "cloud" });
      if (r.ok) setStatus("Using " + r.using, true);
    });
    prefer.append(box2, document.createTextNode(" Prefer this local model (fast, free, private). Untick to prefer cloud models when online."));
    ok.append(prefer);
    box.append(ok);
  }

  // The one big button: everything (Ollama, download, long context, switch, warm) in one click.
  const auto = data.auto || {};
  const picks = data.picks || {};
  const local = active.local || "";
  const usingBest = auto.tag && auto.installed && (local === auto.tag || local.includes(auto.tag.replace(/[:]/g, "-")));
  const hero = el("div", "setup-step" + (usingBest ? " ok" : ""));
  if (usingBest) {
    hero.append(el("h3", "", "You are using the best model for this computer: " + auto.tag));
  } else if (auto.tag) {
    const label = auto.installed ? "Use the best model for this computer (" + auto.tag + ", already downloaded)"
      : "Set up the best model for this computer (" + auto.tag + ", " + gb(auto.size_gb) + ")";
    const go = setupButton("send big", label, async () => {
      go.disabled = true;
      const r = await api("/setup/auto", {});
      if (!r.ok) { go.disabled = false; addNotice(r.error || "Could not start the setup.", true); return; }
      watchProgress(box, compact);
    });
    go.disabled = busy;
    go.style.width = "100%";
    go.style.padding = "12px 16px";
    go.style.fontSize = "15px";
    go.style.margin = "4px 0 10px";
    hero.append(el("h3", "", "One click setup"), go);
    if (picks.agent && picks.agent.why) hero.append(el("p", "note", picks.agent.why));
    hero.append(el("p", "note", "Loki installs Ollama if needed, downloads the model, gives it a long memory and switches to it. You can keep chatting meanwhile."));
  } else {
    hero.append(el("h3", "", "No local model fits right now"), el("p", "note", auto.error || "Use a cloud provider in Settings > Connections."));
  }
  if (data.blocked) hero.append(warnNote(data.blocked.message));
  box.append(hero);

  // Install or open Ollama (the big button does this too).
  const ol = data.ollama || {};
  const servers = data.servers || [];
  if (!ol.running && !servers.length && !compact) {
    const s1 = el("div", "setup-step");
    s1.append(el("h3", "", ol.installed ? "Ollama is installed but not running" : "Ollama runs the models"),
              el("p", "note", ol.installed ? "Open the Ollama app, or use the button above - Loki starts it for you." :
                "Ollama is free and open source. The button above installs it from ollama.com, or do just that step here."));
    if (!ol.installed) {
      const install = setupButton("quiet", "Only install Ollama", async () => {
        install.disabled = true;
        const r = await api("/setup/install-ollama", {});
        if (!r.ok) addNotice(r.error || "Could not start the install.", true);
        watchProgress(box, compact);
      });
      s1.append(install);
    }
    box.append(s1);
  }

  // An out-of-date Ollama: the one thing that makes "it will not download" look like Loki's fault.
  const advice = data.ollama_advice || {};
  if (advice.needs_update && !compact) {
    const s0 = el("div", "setup-step");
    s0.append(el("h3", "", "Ollama " + (advice.version || "") + " is out of date"),
      el("p", "note", "Newer models need Ollama " + advice.recommended + " or newer, and an old Ollama " +
        "can refuse to download or fail to load them. Update it, then come back here: " + ((advice.upgrade || {}).how || "")));
    const cmd = (advice.upgrade || {}).command;
    if (cmd) {
      const copy = setupButton("quiet", "Copy update command", async () => {
        try { await navigator.clipboard.writeText(cmd); setStatus("Command copied", true); }
        catch (_) { addNotice(cmd); }
      });
      s0.append(copy);
    }
    box.append(s0);
  }

  // Suggestions for this computer, by role, each one click.
  const roles = el("div", "setup-step");
  roles.append(el("h3", "", "Suggested for this computer"));
  const shown = new Set();
  for (const key of ["agent", "fast", "code"]) {
    const p = picks[key];
    if (!p) continue;
    const row = el("div", "model-row");
    const info = el("div", "grow");
    info.append(document.createTextNode(p.title + ": " + p.tag),
                el("small", "", p.why + " · " + gb(p.size_gb) + (p.installed ? " · downloaded" : " download")));
    const inUse = local === p.tag || local.includes(p.tag.replace(/[:]/g, "-"));
    const act = setupButton(inUse ? "quiet" : "send", inUse ? "In use" : p.installed ? "Use" : "Download & use",
      async () => { act.disabled = true; if (!(await downloadAndUse(p.tag, box, compact))) act.disabled = false; });
    act.disabled = inUse || busy;
    row.append(info, act);
    roles.append(row);
    shown.add(p.tag);
  }
  if (picks.mlx) {
    const row = el("div", "model-row");
    const info = el("div", "grow");
    info.append(document.createTextNode(picks.mlx.title + ": " + picks.mlx.repo),
                el("small", "", picks.mlx.why + " Run: " + picks.mlx.command));
    const copy = setupButton("quiet", "Copy command", async () => {
      try { await navigator.clipboard.writeText(picks.mlx.command); setStatus("Command copied", true); }
      catch (_) { addNotice(picks.mlx.command); }
    });
    row.append(info, copy);
    roles.append(row);
  }
  if (roles.querySelector(".model-row")) box.append(roles);

  // Installed models (loki-* are Loki's own long-context copies: not listed).
  const installed = (ol.models || []).filter((m) => !/embed/i.test(m.name) && !/^loki-/.test(m.name));
  if (installed.length) {
    const s2 = el("div", "setup-step" + (data.best && data.best.tools ? " ok" : ""));
    s2.append(el("h3", "", "On this computer"));
    for (const m of installed) {
      const row = el("div", "model-row");
      const info = el("div", "grow");
      info.append(document.createTextNode(m.name), el("small", "", (m.params || "") + " · " + gb(m.size_gb) + " · downloaded"));
      const inUse = local === m.name || local.includes(m.name.replace(/[:]/g, "-"));
      const use = setupButton("quiet", inUse ? "In use" : "Use", async () => {
        const r = await api("/setup/use", { model: m.name });
        if (r.ok) { setStatus("Local model: " + r.local, true); compact ? loadModelsTab() : openSetup(true); }
      });
      use.disabled = inUse;
      row.append(info, use);
      s2.append(row);
    }
    box.append(s2);
  }

  // More models that fit, for people who want to choose.
  const more = (data.recommend || []).filter((r) => !r.installed && !shown.has(r.tag));
  if (more.length && !compact) {
    const s3 = el("div", "setup-step");
    s3.append(el("h3", "", "Other models that fit"));
    for (const rec of more.slice(0, 5)) {
      const row = el("div", "model-row");
      const info = el("div", "grow");
      info.append(document.createTextNode(rec.tag), el("small", "", rec.why + " · " + gb(rec.size) + " download · needs ~" + gb(rec.need) + " memory"));
      const get = setupButton("quiet", rec.fits_disk === false ? "Free up " + gb(rec.free_up_gb) + " first" : "Download & use",
        async () => { get.disabled = true; if (!(await downloadAndUse(rec.tag, box, compact))) get.disabled = false; });
      get.disabled = rec.fits_disk === false || busy;
      row.append(info, get);
      s3.append(row);
    }
    box.append(s3);
  }

  // Your own model: any Ollama tag or Hugging Face GGUF, pulled by name (find more / retry).
  if (!compact) {
    const s4 = el("div", "setup-step");
    s4.append(el("h3", "", "Add a model by name"));
    const input = el("input", "add-model-input");
    input.type = "text";
    input.setAttribute("placeholder", "e.g. huihui_ai/qwen3-abliterated:8b  or  hf.co/user/repo:file");
    const add = setupButton("send", "Download & use", async () => {
      const tag = (input.value || "").trim();
      if (!tag) { input.focus(); return; }
      add.disabled = true;
      const r = await api("/setup/pull", { tag });
      if (!r.ok) { add.disabled = false; addNotice(r.error || "Could not start the download.", true); return; }
      watchProgress(box, compact);
    });
    const line = el("div", "model-row");
    line.append(input, add);
    s4.append(line, el("p", "note", "Any model Ollama can pull - a tag off ollama.com, or your own GGUF. If a download fails, this is where you retry it by name."));
    box.append(s4);
  }

  // Uncensored / abliterated builds: opt-in, never picked automatically (Settings > Models).
  const unc = (data.uncensored || []).filter((r) => !r.installed && !shown.has(r.tag));
  if (unc.length && !compact) {
    const s5 = el("div", "setup-step");
    s5.append(el("h3", "", "Uncensored models"),
      el("p", "note", "Community abliterated builds that keep tool calling but do not refuse work. Opt-in: Loki never picks one for you."));
    for (const rec of unc.slice(0, 5)) {
      const row = el("div", "model-row");
      const info = el("div", "grow");
      info.append(document.createTextNode(rec.tag),
        el("small", "", rec.why + " · " + gb(rec.size) + " download · needs ~" + gb(rec.need) + " memory"));
      const get = setupButton("quiet", "Download & use", async () => {
        get.disabled = true;
        if (!(await downloadAndUse(rec.tag, box, compact))) get.disabled = false;
      });
      get.disabled = busy;
      row.append(info, get);
      s5.append(row);
    }
    box.append(s5);
  }

  const p = data.progress || {};
  if (p.op && !p.done) appendProgress(box, p);
  if (!compact) {
    const cloud = el("p", "note", (data.cloud_ready || []).length ? "Until then Loki can answer through " + data.cloud_ready.slice(0, 3).join(", ") + " (online only)." : (data.cloud_keys || []).length ? "Cloud keys found: " + data.cloud_keys.join(", ") + "." :
      "Prefer the cloud too? Add a provider key in Settings > Connections - Loki will use local when offline and cloud when it helps.");
    box.append(cloud);
  }
}

function progressTitle(p) {
  return p.op === "install" ? "Installing " + (p.target || "") : p.op === "auto" ? "Setting up " + (p.target || "your model")
    : "Downloading " + (p.target || "");
}

function appendProgress(box, p) {
  const wrap = el("div", "setup-step");
  wrap.id = "setup-progress";
  wrap.append(el("h3", "", progressTitle(p)),
              el("p", "note", (p.message || p.status || "") + (p.total ? " · " + p.percent + "%" : "")));
  const bar = el("div", "bar");
  const fill = el("i");
  fill.style.width = (p.done ? 100 : p.percent || 0) + "%";
  bar.append(fill);
  wrap.append(bar);
  const old = box.querySelector("#setup-progress");
  if (old) old.replaceWith(wrap); else box.prepend(wrap);
}

function watchProgress(box, compact) {
  clearInterval(setupView.timer);
  setupView.timer = setInterval(async () => {
    const r = await api("/setup/progress").catch(() => null);
    if (!r || !r.ok) return;
    appendProgress(box, r.progress);
    if (r.progress.done) {
      clearInterval(setupView.timer);
      if (r.progress.status === "failed") addNotice(r.progress.message, true);
      else if (r.progress.op === "auto" && r.progress.status === "success") setStatus(r.progress.message, true);
      setTimeout(() => (compact ? loadModelsTab() : openSetup(true)), 800);
      if (typeof loadModels === "function") loadModels();
    }
  }, 1000);
}

// ---------------------------------------------------------------- better-model prompt
function upgradeLaterKey(tag) { return "loki-upgrade-later-" + tag; }

function showUpgradeBanner(data) {
  const up = data && data.upgrade;
  const old = document.getElementById("model-upgrade-banner");
  if (!up || !up.tag) { if (old) old.remove(); return; }
  try { if (localStorage.getItem(upgradeLaterKey(up.tag))) return; } catch (_) { /* no storage */ }
  const main = document.getElementById("main");
  const top = main && main.querySelector(".topbar");
  if (!top) return;
  const bar = el("div", "update-banner");
  bar.id = "model-upgrade-banner";
  bar.setAttribute("role", "status");
  const text = el("span", "", "A better model fits this computer: " + up.tag + " (you use " + up.current + "). " +
    gb(up.size_gb) + " download.");
  text.title = up.why || "";
  const go = setupButton("send small", "Download & switch", async () => {
    go.disabled = true;
    later.hidden = true;
    const r = await api("/setup/upgrade", { tag: up.tag });
    if (!r.ok) { addNotice(r.error || "Could not start the download.", true); bar.remove(); return; }
    const timer = setInterval(async () => {
      const s = await api("/setup/progress").catch(() => null);
      if (!s || !s.ok) return;
      const p = s.progress;
      text.textContent = (p.message || p.status || "Working") + (p.total && !p.done ? " · " + p.percent + "%" : "");
      if (p.done) {
        clearInterval(timer);
        if (p.status === "failed") addNotice(p.message, true);
        if (typeof loadModels === "function") loadModels();
        setTimeout(() => bar.remove(), 5000);
      }
    }, 1000);
  });
  const later = setupButton("quiet small", "Not now", () => {
    try { localStorage.setItem(upgradeLaterKey(up.tag), String(Date.now())); } catch (_) { /* no storage */ }
    bar.remove();
  });
  bar.append(text, go, later);
  if (old) old.replaceWith(bar); else main.insertBefore(bar, top);
}

async function openSetup(force) {
  const data = await api("/setup").catch(() => null);
  if (!data || !data.ok) return;
  setupView.last = data;
  showUpgradeBanner(data);
  if (!force) {
    if (!data.needs_setup) return;
    let later = "";
    try { later = localStorage.getItem("loki-setup-later") || ""; } catch (_) { /* no storage */ }
    if (later && Date.now() - Number(later) < 7 * 86400000) return;  // asked within the week
  }
  $("#setup").hidden = false;
  renderSetup($("#setup-body"), data, false);
}

async function loadModelsTab() {
  const data = await api("/setup").catch(() => null);
  const box = $("#models-panel");
  if (!data || !data.ok) { box.replaceChildren(el("p", "note", "Model setup is not available.")); return; }
  showUpgradeBanner(data);
  renderSetup(box, data, true);
}

// ---------------------------------------------------------------- wiring
function afterStart() {
  $("#usage-pill").addEventListener("click", () => { openSettings(); showTab("usage"); });
  $("#usage-reset").addEventListener("click", async () => { await api("/usage/reset", {}); loadUsageTab(); refreshUsagePill(); });
  $("#close-setup").addEventListener("click", () => {
    $("#setup").hidden = true;
    clearInterval(setupView.timer);
    try { localStorage.setItem("loki-setup-later", String(Date.now())); } catch (_) { /* no storage */ }
  });
  refreshUsagePill();
  // New people get the welcome tour (onboarding.js) instead of this sheet; the sheet stays for
  // "More choices" and Settings > Local models. Either way the better-model banner still shows.
  if (window.LokiI18n) LokiI18n.syncWithEngine();
  if (window.Onboarding) Onboarding.start().then((shown) => { if (!shown) openSetup(false); }).catch(() => openSetup(false));
  else openSetup(false);
}
