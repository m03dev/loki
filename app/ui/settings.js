// Settings, reworked: General, the Connections portal (provider cards, sign-in, QR codes),
// the agent builder, and Machines & updates (one click updates every machine).
// Uses api(), el(), $ and addNotice() from app.js. No inline HTML from the network except
// the engine's own QR SVG (generated locally by engine/qr.py from text we sent).
"use strict";

// ---------------------------------------------------------------- small widgets
function switchEl(checked, label, onChange) {
  const wrap = el("label", "switch");
  const input = el("input");
  input.type = "checkbox";
  input.setAttribute("role", "switch");
  input.checked = !!checked;
  input.setAttribute("aria-label", label);
  const knob = el("span", "knob");
  wrap.append(input, knob);
  input.addEventListener("change", async () => {
    input.disabled = true;
    const ok = await onChange(input.checked);
    input.disabled = false;
    if (ok === false) input.checked = !input.checked;
  });
  return wrap;
}

function segmented(choices, value, onPick) {
  const box = el("div", "segmented");
  box.setAttribute("role", "radiogroup");
  for (const choice of choices) {
    const b = el("button", "", choice);
    b.type = "button";
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(choice === value));
    b.addEventListener("click", async () => {
      if (await onPick(choice) === false) return;
      for (const other of box.children) other.setAttribute("aria-checked", String(other === b));
    });
    box.append(b);
  }
  return box;
}

function button(text, cls, onClick) {
  const b = el("button", cls || "", text);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function openLink(url) { return api("/open", { url }); }

function ago(t) {
  if (!t) return "";
  const s = Math.max(0, Math.round(Date.now() / 1000 - t));
  return s < 60 ? s + "s ago" : s < 3600 ? Math.round(s / 60) + " min ago" : Math.round(s / 3600) + " h ago";
}

// ---------------------------------------------------------------- General
async function loadGeneral() {
  const box = $("#general-panel");
  const data = await api("/settings/general").catch(() => null);
  box.replaceChildren();
  if (!data || !data.ok) { box.append(el("p", "note", "Could not load settings.")); return; }
  const save = async (key, value) => {
    const r = await api("/settings/general", { values: { [key]: value } });
    if (!r.ok) addNotice(r.error || "Not saved.", true);
    if (key === "LOKI_WORLD" && typeof setWorldMode === "function") setWorldMode(value);
    return r.ok;
  };
  for (const [key, spec] of Object.entries(data.settings)) {
    const value = data.values[key];
    const card = el("div", "set-card");
    const text = el("div", "set-text");
    text.append(el("b", "", spec.label), el("small", "", key));
    let control;
    if (spec.kind === "bool") control = switchEl(value === "1", spec.label, (on) => save(key, on ? "1" : "0"));
    else if (spec.kind === "choice") control = segmented(spec.choices, value, (c) => save(key, c));
    else if (spec.kind === "int" || spec.kind === "float") {
      control = el("div", "slider");
      const range = el("input");
      range.type = "range";
      range.min = spec.min; range.max = key === "LOKI_DAILY_USD_LIMIT" ? 20 : spec.max;
      range.step = spec.kind === "float" ? "0.5" : (key === "LOKI_UPDATE_EVERY_S" ? "300" : "1");
      range.value = value;
      range.setAttribute("aria-label", spec.label);
      const shown = el("output", "", key === "LOKI_DAILY_USD_LIMIT" ? "$" + value : (key === "LOKI_UPDATE_EVERY_S" ? Math.round(value / 60) + " min" : value));
      range.addEventListener("input", () => {
        shown.textContent = key === "LOKI_DAILY_USD_LIMIT" ? "$" + range.value : (key === "LOKI_UPDATE_EVERY_S" ? Math.round(range.value / 60) + " min" : range.value);
      });
      range.addEventListener("change", () => save(key, range.value));
      control.append(range, shown);
    } else {
      control = el("input", "text-in");
      control.value = value || "";
      control.setAttribute("aria-label", spec.label);
      control.addEventListener("change", () => save(key, control.value));
    }
    card.append(text, control);
    box.append(card);
  }
}

// ---------------------------------------------------------------- Connections portal
const portal = { data: null, open: {} };
const GROUP_BADGE = { local: "Local", free: "Free", keyless: "No account", trial: "Free credits", subscription: "Subscription", paid: "Paid" };

function initials(name) { return name.replace(/\(.*\)/, "").split(/[\s.-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase(); }

function providerState(p) {
  if (!p.enabled) return ["Off", "off"];
  if (p.configured) {
    if (p.group === "local") return ["Running", "ok"];
    if (p.group === "subscription") return ["Installed", "ok"];
    if (p.test && !p.test.ok) return ["Problem", "bad"];
    return [p.test && p.test.ok ? "Connected · works" : "Connected", "ok"];
  }
  if (p.group === "local") return ["Not running", ""];
  if (p.group === "subscription") return ["Not installed", ""];
  return ["Not connected", ""];
}

async function loadPortal() {
  const data = await api("/providers").catch(() => null);
  if (!data || !data.ok) { $("#portal").replaceChildren(el("p", "note", "Could not load providers.")); return; }
  portal.data = data;
  const count = $("#conn-count");
  if (count) count.textContent = data.connected ? String(data.connected) : "";
  renderPortal();
}

function renderPortal() {
  const data = portal.data;
  if (!data) return;
  const box = $("#portal");
  const filter = ($("#portal-filter").value || "").toLowerCase();
  const freeOnly = $("#portal-free").checked;
  const connectedOnly = $("#portal-connected").checked;
  box.replaceChildren();
  for (const group of data.groups) {
    let cards = data.providers.filter((p) => p.group === group.id);
    if (filter) cards = cards.filter((p) => (p.name + " " + p.blurb + " " + p.id).toLowerCase().includes(filter));
    if (freeOnly) cards = cards.filter((p) => ["local", "free", "keyless", "subscription"].includes(p.group));
    if (connectedOnly) cards = cards.filter((p) => p.configured);
    if (!cards.length) continue;
    const section = el("section", "portal-group");
    const ready = cards.filter((p) => p.configured && p.enabled).length;
    section.append(el("h4", "", group.label + (ready ? " · " + ready + " ready" : "")));
    const grid = el("div", "portal-grid");
    for (const p of cards) grid.append(providerCard(p));
    section.append(grid);
    box.append(section);
  }
  if (!box.children.length) box.append(el("p", "note", "Nothing matches."));
}

function providerCard(p) {
  const card = el("article", "pcard" + (p.configured && p.enabled ? " on" : "") + (!p.enabled ? " disabled" : ""));
  card.dataset.id = p.id;
  const head = el("div", "pcard-head");
  const avatar = el("div", "avatar g-" + p.group, initials(p.name));
  avatar.setAttribute("aria-hidden", "true");
  const title = el("div", "pcard-title");
  const [stateText, stateCls] = providerState(p);
  const badges = el("div", "badges");
  badges.append(el("span", "badge g-" + p.group, GROUP_BADGE[p.group] || p.group), el("span", "pill-state " + stateCls, stateText));
  if (p.default) badges.append(el("span", "badge", "Default"));
  if (p.active && !p.default) badges.append(el("span", "badge", "In use"));
  if (p.prompted_tools) badges.append(el("span", "badge subtle", "tools via harness"));
  title.append(el("b", "", p.name), badges);
  const toggle = switchEl(p.enabled, "Use " + p.name, async (on) => {
    const r = await api("/providers/enable", { id: p.id, on });
    if (r.ok) { p.enabled = on; card.classList.toggle("disabled", !on); loadPortal(); }
    return r.ok;
  });
  toggle.title = p.enabled ? "LOKI may route to " + p.name : p.name + " is switched off";
  head.append(avatar, title, toggle);
  card.append(head, el("p", "pcard-blurb", p.blurb));
  if (p.needs) card.append(el("p", "pcard-warn", "Needs " + p.needs));

  const body = el("div", "pcard-body");
  const result = el("div", "pcard-result");
  result.setAttribute("role", "status");
  if (p.test) result.textContent = (p.test.ok ? "✓ " : "✗ ") + p.test.detail + " · " + ago(p.test.at);
  const auth = p.auth || [];

  if (auth.includes("oauth") && !p.has_key) {
    const row = el("div", "pcard-actions");
    row.append(button("Sign in with " + p.name, "primary", () => signInOpenRouter(result)),
               button("Sign in on my phone", "", () => signInOpenRouterPhone()));
    body.append(row);
  }
  if (auth.includes("device") && !p.has_key) {
    body.append(el("div", "pcard-actions"));
    body.lastChild.append(button("Sign in with a code", "", () => signInDevice(p, result)));
  }
  if (auth.includes("key") && !p.has_key) {
    const form = el("form", "key-form");
    const input = el("input");
    input.type = "password";
    input.autocomplete = "off";
    input.placeholder = (p.env || "API key");
    input.setAttribute("aria-label", p.name + " API key");
    form.append(input);
    let account = null;
    if ((p.extra_env || []).includes("CLOUDFLARE_ACCOUNT_ID")) {
      account = el("input");
      account.placeholder = "Account ID";
      account.setAttribute("aria-label", "Cloudflare account ID");
      form.append(account);
    }
    const go = el("button", "primary", "Connect");
    go.type = "submit";
    form.append(go);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!input.value.trim()) { input.focus(); return; }
      go.disabled = true;
      result.textContent = "Checking the key…";
      const r = await api("/providers/connect", { id: p.id, key: input.value, account_id: account ? account.value : "" });
      input.value = "";
      go.disabled = false;
      result.textContent = r.ok ? "✓ " + (r.message || "Connected") : "✗ " + (r.error || "Could not connect");
      if (r.ok) loadPortal();
    });
    body.append(form);
    const links = el("div", "pcard-links");
    if (p.keys) links.append(button("Get a key", "link", () => openLink(p.keys)));
    links.append(button("Use my phone", "link", () => phoneKey(p)));
    if (p.docs) links.append(button("Docs", "link", () => openLink(p.docs)));
    body.append(links);
  }
  if ((auth.includes("cli") || auth.includes("none")) && p.setup && !p.configured) {
    const pre = el("code", "setup-cmd", p.setup);
    body.append(pre);
  }
  if ((auth.includes("cli") || auth.includes("none")) && !p.configured && p.signup) {
    const links = el("div", "pcard-links");
    links.append(button(p.group === "local" ? "Download" : "Get it", "link", () => openLink(p.signup)));
    if (p.docs) links.append(button("Docs", "link", () => openLink(p.docs)));
    body.append(links);
  }

  const foot = el("div", "pcard-foot");
  if (p.available) {
    foot.append(button("Test", "small", async (event) => {
      event.target.disabled = true;
      result.textContent = "Testing…";
      const r = await api("/providers/test", { id: p.id });
      event.target.disabled = false;
      const t = r.test || {};
      result.textContent = (t.ok ? "✓ " : "✗ ") + (t.detail || r.error || "") + (t.ms ? " · " + t.ms + " ms" : "");
      p.test = t;
    }));
  }
  if (p.available && p.base_url && (p.configured || p.has_key)) {
    const pick = el("select", "model-pick");
    pick.setAttribute("aria-label", p.name + " model");
    const current = el("option", "", p.model || "model");
    current.value = p.model;
    pick.append(current);
    let loaded = false;
    pick.addEventListener("focus", async () => {
      if (loaded) return;
      loaded = true;
      const r = await api("/providers/models", { id: p.id });
      if (!r.ok) { result.textContent = "✗ models: " + (r.error || ""); return; }
      for (const m of r.models) {
        if (m === p.model) continue;
        const o = el("option", "", m + (/(:|-)free\b/.test(m) ? "  · free" : ""));
        o.value = m;
        pick.append(o);
      }
    });
    pick.addEventListener("change", async () => {
      const r = await api("/providers/model", { id: p.id, model: pick.value });
      result.textContent = r.ok ? "Uses " + pick.value + " now" : "✗ " + (r.error || "");
    });
    foot.append(pick);
  }
  if (p.available && !p.default && (p.configured || p.has_key)) {
    foot.append(button("Make default", "small quiet", async () => {
      const r = await api("/providers/default", { id: p.id });
      if (r.ok) { loadPortal(); if (typeof loadModels === "function") loadModels(); }
    }));
  }
  if (p.has_key) {
    foot.append(button("Disconnect", "small quiet danger", async () => {
      const r = await api("/providers/disconnect", { id: p.id });
      if (r.ok) loadPortal();
    }));
  }
  body.append(foot, result);
  card.append(body);
  return card;
}

// ---------------------------------------------------------------- QR modal
const qrView = { timer: 0 };

function closeQR() {
  clearInterval(qrView.timer);
  $("#qr-modal").hidden = true;
}

async function qrSvg(text) {
  const r = await api("/qr?text=" + encodeURIComponent(text));
  return r.ok ? r.svg : "";
}

function showQR({ title, text, svg, steps = [], actions = [] }) {
  clearInterval(qrView.timer);
  $("#qr-title").textContent = title;
  $("#qr-text").textContent = text || "";
  const img = $("#qr-image");
  img.replaceChildren();
  if (svg) {
    // engine/qr.py output: one <svg> with a rect and a path, built from our own text.
    const holder = el("div");
    holder.innerHTML = svg;
    if (holder.firstElementChild && holder.firstElementChild.tagName.toLowerCase() === "svg") img.append(holder.firstElementChild);
  }
  const list = el("ol");
  for (const s of steps) list.append(el("li", "", s));
  $("#qr-steps").replaceChildren(list);
  $("#qr-actions").replaceChildren(...actions);
  $("#qr-status").textContent = "";
  $("#qr-modal").hidden = false;
}

function qrStatus(text) { $("#qr-status").textContent = text; }

async function phoneKey(p) {
  // Two ways at once: scan to open the provider's key page on the phone, and the one-time
  // page that sends the key from the phone back here.
  const r = await api("/handoff", { id: p.id });
  if (!r.ok) {
    const svg = p.keys ? await qrSvg(p.keys) : "";
    showQR({ title: "Get a " + p.name + " key on your phone", text: p.keys || "", svg,
             steps: ["Scan to open " + p.name + "'s key page.", "Create a key, then paste it into LOKI."] });
    qrStatus(r.error || "");
    return;
  }
  const keyPage = p.keys ? button("Show the key page QR instead", "small", async () => {
    $("#qr-image").replaceChildren();
    const holder = el("div");
    holder.innerHTML = await qrSvg(p.keys);
    if (holder.firstElementChild) $("#qr-image").append(holder.firstElementChild);
    $("#qr-text").textContent = p.keys;
  }) : null;
  showQR({ title: "Send a " + p.name + " key from your phone", text: r.url, svg: r.svg,
           steps: ["Your phone must be on the same Wi-Fi as this computer.",
                   "Scan the code. A LOKI page opens on the phone.",
                   "Paste the key (copy it from " + p.name + "'s site on the phone) and tap Send.",
                   "LOKI checks it and connects " + p.name + ". The page then stops working."],
           actions: keyPage ? [keyPage] : [] });
  qrStatus("Waiting for your phone… (5 minutes)");
  qrView.timer = setInterval(async () => {
    const s = await api("/handoff/status?id=" + encodeURIComponent(r.id)).catch(() => null);
    if (!s || !s.ok) { qrStatus("This code expired. Close and try again."); clearInterval(qrView.timer); return; }
    if (s.result) {
      clearInterval(qrView.timer);
      qrStatus(s.result.ok ? "✓ " + (s.result.message || "Connected") : "✗ " + (s.result.error || "That key did not work"));
      if (s.result.ok) { loadPortal(); setTimeout(closeQR, 1800); }
    } else qrStatus("Waiting for your phone… " + Math.floor(s.expires_in / 60) + ":" + String(s.expires_in % 60).padStart(2, "0"));
  }, 1500);
}

async function signInOpenRouter(result) {
  result.textContent = "Opening OpenRouter in your browser…";
  const r = await api("/signin/openrouter", { mode: "browser" });
  if (!r.ok) { result.textContent = "✗ " + (r.error || ""); return; }
  result.textContent = "Approve LOKI in the browser tab that opened. Waiting…";
  watchFlow(r.state, (s) => { result.textContent = s; });
}

async function signInOpenRouterPhone() {
  const r = await api("/signin/openrouter", { mode: "code" });
  if (!r.ok) return;
  const svg = await qrSvg(r.url);
  const form = el("form", "key-form");
  const input = el("input");
  input.placeholder = "Code from OpenRouter";
  input.setAttribute("aria-label", "OpenRouter code");
  const go = el("button", "primary", "Connect");
  go.type = "submit";
  form.append(input, go);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    go.disabled = true;
    qrStatus("Connecting…");
    const done = await api("/signin/openrouter/code", { state: r.state, code: input.value });
    go.disabled = false;
    qrStatus(done.ok ? "✓ " + (done.message || "Connected") : "✗ " + (done.error || ""));
    if (done.ok) { loadPortal(); setTimeout(closeQR, 1500); }
  });
  showQR({ title: "Sign in to OpenRouter on your phone", text: "", svg,
           steps: ["Scan the code with your phone's camera.", "Sign in to OpenRouter there and tap Authorize.",
                   "OpenRouter shows a code. Type it here."], actions: [form] });
  input.focus();
}

async function signInDevice(p, result) {
  const r = await api("/signin/device", { id: p.id });
  if (!r.ok) { result.textContent = "✗ " + (r.error || ""); return; }
  const svg = await qrSvg(r.url);
  const code = el("div", "user-code", r.user_code);
  showQR({ title: "Sign in to " + p.name, text: r.verification_uri, svg,
           steps: ["Scan the code, or open the address on any device.", "Enter this code and approve LOKI:"], actions: [code] });
  watchFlow(r.state, qrStatus);
}

function watchFlow(state, say) {
  const started = Date.now();
  const timer = setInterval(async () => {
    const s = await api("/signin/status?state=" + encodeURIComponent(state)).catch(() => null);
    if (!s || !s.ok) { clearInterval(timer); say("This sign-in expired. Try again."); return; }
    if (s.done) {
      clearInterval(timer);
      const res = s.result || {};
      say(res.ok ? "✓ " + (res.message || "Connected") : "✗ " + (res.error || "Sign-in failed"));
      if (res.ok) { loadPortal(); setTimeout(closeQR, 1500); }
    } else if (Date.now() - started > 600000) { clearInterval(timer); say("This sign-in expired. Try again."); }
  }, 2000);
}

// ---------------------------------------------------------------- Machines & updates
const updates = { timer: 0, banner: { dismissed: false } };

function versionLine(m, latest) {
  if (!m.online) return "offline" + (m.error ? " · " + m.error : "");
  const c = (m.commit || "").slice(0, 7) || "unknown";
  if (m.dirty) return c + " · has local edits (ship them first)";
  return c + (m.behind ? " · behind " + (latest || "").slice(0, 7) : " · up to date");
}

async function loadUpdatePanel() {
  const box = $("#update-panel");
  if (!box) return;
  const data = await api("/update/everywhere").catch(() => null);
  box.replaceChildren();
  if (!data || !data.ok) { box.append(el("p", "note", "Could not read versions.")); return; }
  const behind = data.machines.filter((m) => m.behind);
  const head = el("div", "update-head");
  const summary = el("div");
  summary.append(el("b", "", behind.length ? behind.length + (behind.length === 1 ? " machine needs" : " machines need") + " an update"
                                             : (data.in_step ? "Every machine runs the same LOKI" : "Versions differ")),
                 el("small", "", "Newest on GitHub: " + ((data.latest || "").slice(0, 7) || "not checked yet")));
  const go = button("Update everything", "primary", startUpdateEverywhere);
  const check = button("Check now", "small quiet", async () => { await api("/update/check", {}); loadUpdatePanel(); });
  head.append(summary, check, go);
  box.append(head);
  const list = el("div", "update-list");
  const progress = data.progress || {};
  const steps = {};
  for (const s of progress.steps || []) steps[s.machine] = s;
  for (const m of data.machines) {
    const row = el("div", "update-row" + (m.behind ? " behind" : ""));
    const step = steps[m.machine];
    row.append(el("span", "dot-state " + (m.online ? (m.behind ? "warn" : "ok") : "off")), el("b", "", m.self ? "This computer" : m.machine),
               el("span", "muted", versionLine(m, data.latest)));
    if (step) row.append(el("span", "pill " + (step.status === "done" ? "done" : step.status === "failed" ? "failed" : "working"),
                            step.status + (step.note ? " · " + step.note : "")));
    list.append(row);
  }
  box.append(list);
  const health = data.health || {};
  if (health.rolled_back_from) box.append(el("p", "why", "Rolled back from " + health.rolled_back_from + " here: it did not start. LOKI waits for a newer version."));
  if (progress.running) {
    clearTimeout(updates.timer);
    updates.timer = setTimeout(loadUpdatePanel, 2000);
  }
  const dot = $("#update-dot");
  if (dot) dot.hidden = !behind.length;
  return data;
}

async function startUpdateEverywhere() {
  const r = await api("/update/everywhere", {});
  if (!r.ok) { addNotice(r.error || "Could not start the update.", true); return; }
  $("#update-banner").hidden = true;
  setStatus("Updating every machine…", "wait");
  addNotice("Updating every machine. Linked machines go first; this window reloads when this computer restarts on the new version.");
  loadUpdatePanel();
}

async function checkUpdateBanner(u) {
  if (updates.banner.dismissed) return;
  let behindNames = [];
  if (u && u.update_available) behindNames.push("this computer");
  try {
    const data = await api("/update/everywhere");
    if (data && data.ok) behindNames = data.machines.filter((m) => m.behind).map((m) => (m.self ? "this computer" : m.machine));
  } catch (_) { /* engine busy */ }
  const banner = $("#update-banner");
  if (!banner) return;
  if (!behindNames.length) { banner.hidden = true; return; }
  $("#update-banner-text").textContent = "A newer LOKI is ready for " + behindNames.join(" and ") + ".";
  banner.hidden = false;
}

// ---------------------------------------------------------------- Agents (builder)
const builder = { meta: null, skills: [], peers: [], editing: null };

async function loadAgents() {
  const box = $("#agents-panel");
  const [list, meta, skills, peerData] = await Promise.all([
    api("/agents").catch(() => null), api("/agents/templates").catch(() => null),
    api("/skills").catch(() => null), api("/peers").catch(() => null)]);
  builder.meta = meta && meta.ok ? meta : { templates: [], engines: {}, tools: {}, memory: ["none"], models: [] };
  builder.skills = skills && skills.ok ? skills.skills : [];
  builder.peers = peerData && peerData.ok ? (peerData.peers || []).map((p) => p.name) : [];
  box.replaceChildren();

  const create = el("div", "builder-create");
  const ask = el("textarea");
  ask.rows = 2;
  ask.placeholder = "Describe an agent in one sentence, e.g. “watch YouTube videos about Godot and write summaries”";
  ask.setAttribute("aria-label", "Describe a new agent");
  const draft = button("Draft it", "primary", async () => {
    const r = await api("/agents/draft", { description: ask.value });
    if (!r.ok) { addNotice(r.error || "Could not draft that.", true); return; }
    editAgent(r.agent, true);
  });
  const chips = el("div", "chips");
  for (const t of builder.meta.templates) chips.append(button(t.name, "chip", () => editAgent(Object.assign({}, t, { id: "" }), true)));
  create.append(el("b", "", "New agent"), ask, el("div", "right"), chips);
  create.querySelector(".right").append(button("Blank", "quiet", () => editAgent({ name: "", engine: "loki", tools: ["files"] }, true)), draft);
  box.append(create);

  // Ruflo's agent library (github.com/ruvnet/ruflo), built in: search, pick, adjust, save.
  const library = builder.meta.library || [];
  if (library.length) {
    const lib = el("div", "builder-create library");
    const head = el("div", "lib-head");
    head.append(el("b", "", "Ruflo library"), el("small", "muted", library.length + " ready-made agents, checked by LOKI's skill scan"));
    const search = el("input");
    search.type = "search";
    search.placeholder = "Search: security, api, pr, swarm, sparc, docs…";
    search.setAttribute("aria-label", "Search the Ruflo agent library");
    const results = el("div", "chips");
    const show = () => {
      const q = search.value.toLowerCase().trim();
      const hits = library.filter((t) => !q || (t.name + " " + t.goal + " " + t.family).toLowerCase().includes(q)).slice(0, 24);
      results.replaceChildren(...hits.map((t) => {
        const b = button(t.name, "chip", () => editAgent(Object.assign({}, t, { id: "" }), true));
        b.title = t.family + ": " + t.goal;
        return b;
      }));
      if (!hits.length) results.append(el("small", "muted", "No match."));
    };
    search.addEventListener("input", show);
    lib.append(head, search, results);
    box.append(lib);
    show();
  }

  const grid = el("div", "agent-grid");
  for (const a of (list && list.ok ? list.agents : [])) grid.append(agentCard(a));
  box.append(grid, el("div", "", ""));
  const editor = el("div", "agent-editor");
  editor.id = "agent-editor";
  editor.hidden = true;
  box.append(editor);
}

function agentCard(a) {
  const card = el("article", "acard");
  const head = el("div", "acard-head");
  const dot = el("span", "agent-dot");
  dot.style.background = a.color || "#8fb3d9";
  head.append(dot, el("b", "", a.name), el("span", "badge", (a.engine || "loki")));
  if (a.starter) head.append(el("span", "badge subtle", "starter"));
  card.append(head, el("p", "pcard-blurb", a.goal || (a.instructions || "").slice(0, 140)));
  const facts = [];
  if (a.model) facts.push("model " + a.model);
  if ((a.skills || []).length) facts.push(a.skills.length + " skill" + (a.skills.length === 1 ? "" : "s"));
  if ((a.tools || []).length) facts.push(a.tools.join(", "));
  facts.push(a.machine && a.machine !== "here" ? "lives on " + a.machine : "runs here");
  card.append(el("small", "muted", facts.join(" · ")));
  const run = el("form", "key-form");
  const task = el("input");
  task.placeholder = "Give " + a.name + " a task";
  task.setAttribute("aria-label", "Task for " + a.name);
  const go = el("button", "primary", "Run");
  go.type = "submit";
  run.append(task, go);
  const out = el("div", "pcard-result");
  run.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!task.value.trim()) return;
    go.disabled = true;
    const r = await api("/agents/launch", { id: a.id, task: task.value });
    go.disabled = false;
    out.textContent = r.ok ? (r.remote ? "Started on " + r.remote : "Started — see the work strip") : "✗ " + (r.error || "");
    if (r.ok) { task.value = ""; if (typeof refreshJobs === "function") refreshJobs(); }
  });
  const actions = el("div", "pcard-foot");
  actions.append(button("Edit", "small", () => editAgent(a, false)));
  if (!a.starter) actions.append(button("Delete", "small quiet danger", async () => {
    const r = await api("/agents/delete", { id: a.id });
    if (r.ok) loadAgents();
  }));
  card.append(run, actions, out);
  return card;
}

function field(label, control, hint) {
  const row = el("label", "field");
  row.append(el("span", "", label), control);
  if (hint) row.append(el("small", "muted", hint));
  return row;
}

function selectEl(options, value, labels) {
  const s = el("select");
  for (const o of options) {
    const opt = el("option", "", (labels && labels[o]) || o || "(LOKI decides)");
    opt.value = o;
    opt.selected = o === (value || "");
    s.append(opt);
  }
  return s;
}

function editAgent(a, isNew) {
  const box = $("#agent-editor");
  box.replaceChildren();
  box.hidden = false;
  const meta = builder.meta;
  const name = el("input"); name.value = a.name || ""; name.maxLength = 40;
  const role = el("input"); role.value = a.role || "";
  const goal = el("input"); goal.value = a.goal || "";
  const instructions = el("textarea"); instructions.rows = 6; instructions.value = a.instructions || "";
  const engine = selectEl(Object.keys(meta.engines), a.engine || "loki", meta.engines);
  const models = ["", ...meta.models];
  const model = selectEl(models, a.model || "");
  const fallback = selectEl(models, a.fallback || "");
  const machine = selectEl(["here", "auto", ...builder.peers], a.machine || "here",
                           { here: "This computer", auto: "Best machine (GPU first)" });
  const minutes = el("input"); minutes.type = "range"; minutes.min = 5; minutes.max = 480; minutes.step = 5;
  minutes.value = a.max_minutes || 60;
  const minutesOut = el("output", "", minutes.value + " min");
  minutes.addEventListener("input", () => { minutesOut.textContent = minutes.value + " min"; });
  const minutesBox = el("div", "slider"); minutesBox.append(minutes, minutesOut);
  const color = el("input"); color.type = "color"; color.value = a.color || "#8fb3d9";
  let memory = a.memory || "none";
  const memoryCtl = segmented(meta.memory, memory, (m) => { memory = m; return true; });
  let allow = !!a.allow_commands;
  const allowCtl = switchEl(allow, "May run commands", (on) => { allow = on; return true; });

  const tools = el("div", "checks");
  for (const [t, why] of Object.entries(meta.tools)) {
    const l = el("label", "check");
    const c = el("input"); c.type = "checkbox"; c.value = t; c.checked = (a.tools || []).includes(t);
    l.title = why;
    l.append(c, document.createTextNode(" " + t));
    tools.append(l);
  }
  const skills = el("div", "checks");
  if (!builder.skills.length) skills.append(el("small", "muted", "No skills yet. Add folders with a SKILL.md to harness_data/skills."));
  for (const s of builder.skills) {
    const l = el("label", "check");
    const c = el("input"); c.type = "checkbox"; c.value = s.id; c.checked = (a.skills || []).includes(s.id);
    l.title = s.description;
    l.append(c, document.createTextNode(" " + s.name));
    skills.append(l);
  }
  const grid = el("div", "editor-grid");
  grid.append(field("Name", name), field("Role", role, "build, research, test, review, create…"),
              field("Goal", goal, "One line. Also how LOKI decides to hand work to it."),
              field("Harness", engine, "LOKI's own loop works offline with any model (prompted tools)."),
              field("Model", model, "Empty: LOKI's smart routing."), field("Fallback model", fallback),
              field("Lives on", machine), field("Time per run", minutesBox), field("Colour in LOKI World", color));
  const wide = el("div", "editor-wide");
  wide.append(field("Instructions", instructions), field("Tools", tools), field("Skills", skills),
              field("Memory", memoryCtl), field("May run commands (tests, builds) in its workspace", allowCtl));
  const result = el("div", "pcard-result");
  const save = button(isNew ? "Save agent" : "Save changes", "primary", async () => {
    const spec = {
      id: isNew ? "" : a.id, name: name.value, role: role.value, goal: goal.value, instructions: instructions.value,
      engine: engine.value, model: model.value, fallback: fallback.value, machine: machine.value,
      max_minutes: Number(minutes.value), color: color.value, memory, allow_commands: allow,
      tools: [...tools.querySelectorAll("input:checked")].map((c) => c.value),
      skills: [...skills.querySelectorAll("input:checked")].map((c) => c.value),
    };
    const r = await api("/agents", spec);
    result.textContent = r.ok ? "✓ Saved" : "✗ " + (r.error || "");
    if (r.ok) setTimeout(loadAgents, 500);
  });
  const cancel = button("Cancel", "quiet", () => { box.hidden = true; });
  const actions = el("div", "right");
  actions.append(cancel, save);
  box.append(el("h4", "", isNew ? "New agent" : "Edit " + a.name), grid, wide, actions, result);
  box.scrollIntoView({ behavior: "smooth", block: "start" });
  name.focus();
}

// ---------------------------------------------------------------- wiring
function wireSettings() {
  for (const id of ["#portal-filter", "#portal-free", "#portal-connected"]) {
    const node = $(id);
    if (node) node.addEventListener("input", renderPortal);
  }
  const close = $("#qr-close");
  if (close) close.addEventListener("click", closeQR);
  const modal = $("#qr-modal");
  if (modal) modal.addEventListener("click", (e) => { if (e.target === modal) closeQR(); });
  const go = $("#update-banner-go");
  if (go) go.addEventListener("click", startUpdateEverywhere);
  const later = $("#update-banner-later");
  if (later) later.addEventListener("click", () => { updates.banner.dismissed = true; $("#update-banner").hidden = true; });
  const search = $("#settings-search");
  if (search) search.addEventListener("input", () => {
    const q = search.value.toLowerCase().trim();
    for (const tab of document.querySelectorAll(".settings-nav .tabs button")) {
      const panel = document.querySelector('[data-panel="' + tab.dataset.tab + '"]');
      const hay = (tab.textContent + " " + (panel ? panel.textContent : "")).toLowerCase();
      tab.hidden = !!q && !hay.includes(q);
    }
  });
  // Keep the banner honest: look again every ten minutes.
  setInterval(() => checkUpdateBanner(null), 600000);
}

document.addEventListener("DOMContentLoaded", wireSettings);
