// Chat quality of life (session 29) - LOKI's own versions of the comfort features in Ziva's public patch
// notes (ziva.sh/changelog, ziva.sh/docs; list + sources in docs/integrations/ZIVA_QOL.md). Clean-room.
//
//   connection   the engine stops answering -> a banner: retries by itself with a countdown, Reconnect now,
//                Copy my message, What happened; when it is back, a message that was cut off is checked
//                (finished meanwhile? -> shown; not -> Send again). Offline computer -> use a local model.
//   recovery     a failed answer gets a card with choices instead of a dead end: try again, wait and try again
//                (countdown, automatic for dropped connections / rate limits), another model, a model on this
//                computer, let LOKI pick, summarize and retry, fix the key, new chat, what happened.
//   queue/steer  typing while LOKI works never loses the message: Enter queues it (sent when LOKI is free),
//                Ctrl/Cmd+Enter steers (LOKI reads it at its next step). Each waiting one: Steer, Send now,
//                Edit, Remove. Stop puts them back in the box.
//   slow         no news for 90 s -> Keep waiting / Stop and try again / Stop and use another model.
//   restart      a message LOKI was answering when it closed is offered again on the next start.
//   comfort      drafts kept, long pastes become attached files, Up recalls, allow-for-this-session,
//                context bar + Summarize now, notifications + sound when a long answer finishes,
//                search all chats (Ctrl/Cmd+K), find in chat (Ctrl/Cmd+F), pinned + renamed chats,
//                customizable shortcuts, copy chat as Markdown, thinking on/off, model switches noted.
// Engine side: engine/qol.py (GET/POST /qol/*). app.js is not edited: this file wraps its globals.
"use strict";

const LokiQol = (function () {
  const $q = (s, r) => (r || document).querySelector(s);
  const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  // English for now (like app.js's dynamic strings); tooltips go through icons.js' phrase tables
  const say = (en, vars) => String(en).replace(/\{(\w+)\}/g, (_, k) => (vars && k in vars ? vars[k] : ""));
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");

  Object.assign(ICON_PATHS, {
    keyboard: '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 9.5h1M9.5 9.5h1M13 9.5h1M16.5 9.5h1M6 12.5h1M17 12.5h1M9.5 12.5h4.5M7.5 15.5h9"/>',
    pin: '<path d="M9 3.5h6l-1 5 3.5 3.5h-11L10 8.5z"/><path d="M12 12v8.5"/>',
    steer: '<path d="M5 19c0-7 4-11 11-11"/><path d="M13 4.5l3.5 3.5L13 11.5"/>',
    queue: '<path d="M4 7h11M4 12h11M4 17h7"/><path d="M18 14.5v5M15.5 17h5"/>',
    wifiOff: '<path d="M3 3l18 18"/><path d="M8.5 16.2a5 5 0 0 1 7 0M5.3 12.9a9.5 9.5 0 0 1 6-2.8M15.9 10.6a9.5 9.5 0 0 1 2.8 2.3M2.3 9.6A14 14 0 0 1 8 6.3M12 5.5a14 14 0 0 1 9.7 4.1"/><circle cx="12" cy="19.2" r=".6"/>',
    bell: '<path d="M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 2h-14z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    sendNow: '<path d="M4 12h12M11 6l6 6-6 6"/><path d="M20 5v14"/>',
  });

  // ------------------------------------------------------------------ preferences (this computer)
  const PREFS_KEY = "loki-qol-prefs", DRAFT_KEY = "loki-qol-draft";
  const DEFAULTS = { notify: true, notifyAfter: 20, sound: false, autoRetry: true, thinking: false, slowAfter: 90,
    pasteLimit: 8000, shortcuts: {} };
  let prefs = loadPrefs();
  function loadPrefs() {
    try { return Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(PREFS_KEY) || "{}")); } catch (_) { return Object.assign({}, DEFAULTS); }
  }
  function savePrefs() { try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch (_) { /* this session only */ } }

  // ------------------------------------------------------------------ shared state
  const conn = { up: true, fails: 0, attempt: 0, timer: 0, tick: 0, next: 0, log: [], offline: false };
  const turn = { text: "", data: null, error: null, started: 0, news: 0, slowCard: null, extended: 0, retryAfterStop: "",
    switchAfterStop: "", stopped: false, sendNow: false, autoTries: {} };
  const queue = [];   // {id, text, mode: "queued" | "steering", steerId}
  queue.paused = false;
  let seq = 0, info = { never_session: [], pins: [] }, lastTicket = null;
  const log = (what) => { conn.log.push({ t: new Date().toLocaleTimeString(), what }); conn.log.splice(0, conn.log.length - 30); };

  // ------------------------------------------------------------------ api: watch every call
  const _api = api;
  api = async function (path, body) {   // eslint-disable-line no-global-assign
    let data;
    try { data = await _api(path, body); } catch (err) {
      if (path === "/chat") turn.error = err;
      lostEngine(path, err);
      throw err;
    }
    reachedEngine();
    if (path === "/chat") turn.data = data;
    else if (String(path).startsWith("/progress")) watchProgress(data);
    else if (path === "/approval" && body === undefined) noteTicket(data && data.approval);
    return data;
  };

  // ------------------------------------------------------------------ connection to the engine
  function lostEngine(path, err) {
    conn.fails += 1;
    if (!conn.up || (conn.fails < 2 && path !== "/chat")) return;
    conn.up = false;
    conn.attempt = 0;
    log("lost the engine (" + (path || "") + ": " + String((err && err.message) || err).slice(0, 80) + ")");
    showConnBanner();
    scheduleReconnect();
  }

  function reachedEngine() {
    conn.fails = 0;
    if (conn.up) return;
    conn.up = true;
    clearTimeout(conn.timer); clearInterval(conn.tick);
    log("the engine answers again");
    const b = $q("#qol-conn");
    if (b) {
      b.classList.add("good");
      $q(".qol-conn-text", b).textContent = say("Connected to LOKI's engine again.");
      $q(".qol-conn-sub", b).textContent = "";
      for (const x of b.querySelectorAll("button")) x.hidden = !x.classList.contains("qol-dismiss");
      setTimeout(() => { if (conn.up) b.hidden = true; }, 3500);
    }
    if (!state.busy) setStatus("Ready", true);
    if (turn.error && turn.text) checkCutOff(turn.text);
  }

  function scheduleReconnect() {
    clearTimeout(conn.timer); clearInterval(conn.tick);
    if (conn.up) return;
    conn.attempt += 1;
    const wait = Math.min(30, [2, 3, 5, 8, 13, 20][conn.attempt - 1] || 30);
    conn.next = Date.now() + wait * 1000;
    const paint = () => {
      const b = $q("#qol-conn");
      if (!b || conn.up) return;
      const s = Math.max(0, Math.ceil((conn.next - Date.now()) / 1000));
      $q(".qol-conn-sub", b).textContent = prefs.autoRetry
        ? say("Trying again in {s} s (attempt {n}). Your chats and your draft are kept.", { s, n: conn.attempt })
        : say("Automatic retry is off. Your chats and your draft are kept.");
    };
    paint();
    if (!prefs.autoRetry) return;
    conn.tick = setInterval(paint, 1000);
    conn.timer = setTimeout(reconnectNow, wait * 1000);
  }

  async function reconnectNow() {
    clearTimeout(conn.timer); clearInterval(conn.tick);
    const b = $q("#qol-conn");
    if (b) $q(".qol-conn-sub", b).textContent = say("Checking...");
    let ok = false;
    try { const d = await _api("/health"); ok = !!(d && d.ok); } catch (_) { ok = false; }
    if (ok) reachedEngine(); else scheduleReconnect();
    return ok;
  }

  function showConnBanner() {
    let b = $q("#qol-conn");
    if (!b) {
      b = node("div", "qol-banner qol-conn"); b.id = "qol-conn"; b.setAttribute("role", "alert");
      const words = node("div", "qol-words");
      words.append(node("b", "qol-conn-text"), node("span", "qol-conn-sub"));
      b.append(iconSpan("wifiOff"), words,
        textBtn("send small", say("Reconnect now"), "Reconnect now", "Ask LOKI's engine again right away.", reconnectNow),
        textBtn("quiet small qol-copy", say("Copy my message"), "Copy my message", "Copy the message that was being answered, so nothing is lost.", () => copy(turn.text)),
        textBtn("quiet small", say("What happened?"), "What happened?", "What LOKI knows about the problem, and what to try.", whatHappened),
        textBtn("quiet small qol-dismiss", "×", "Hide", "Hide this banner (LOKI keeps trying).", () => { b.hidden = true; }));
      placeBanner(b);
    }
    b.classList.remove("good");
    for (const x of b.querySelectorAll("button")) x.hidden = false;
    $q(".qol-copy", b).hidden = !turn.text || !state.busy && !turn.error;
    $q(".qol-conn-text", b).textContent = say("LOKI's engine is not answering.");
    b.hidden = false;
    setStatus("Disconnected - reconnecting", false);
  }

  // A message whose answer was cut off by the drop: did the engine finish it meanwhile?
  async function checkCutOff(text) {
    turn.error = null;
    const out = await api("/conversations/messages?id=" + encodeURIComponent(state.active || "")).catch(() => null);
    const msgs = (out && out.messages) || [];
    const last = msgs[msgs.length - 1], prev = msgs[msgs.length - 2];
    removeCard("engine");
    if (last && last.role === "assistant" && prev && prev.role === "user" && String(prev.content || "").trim() === text.trim()) {
      renderMessages(msgs);
      addNotice(say("LOKI finished that answer while the connection was down - here it is."));
      return;
    }
    const st = await api("/qol/state").catch(() => null);
    if (st && st.busy) { addNotice(say("LOKI is still working on it - the answer appears when it is done."), false); waitForIdle(text); return; }
    recoveryCard({ kind: "engine", title: say("The answer was cut off"),
      advice: say("The connection dropped before the answer arrived, and LOKI did not finish it. Send it again?"),
      actions: ["retry", "draft", "details"], labels: {} }, text);
  }

  async function waitForIdle(text) {
    for (let i = 0; i < 400; i++) {
      await sleep(3000);
      const st = await api("/qol/state").catch(() => null);
      if (st && !st.busy) { await loadConversations(); showChat(); return; }
    }
    recoveryCard({ kind: "engine", title: say("The answer was cut off"), advice: "", actions: ["retry", "draft"], labels: {} }, text);
  }

  // This computer lost the internet: online models cannot answer; a local one can.
  async function offlineBanner(off) {
    conn.offline = off;
    let b = $q("#qol-offline");
    if (!off) { if (b) b.hidden = true; return; }
    const alts = await api("/qol/alternatives").catch(() => null);
    const local = ((alts && alts.alternatives) || []).find((a) => a.local);
    if (!b) {
      b = node("div", "qol-banner qol-offline"); b.id = "qol-offline"; b.setAttribute("role", "status");
      placeBanner(b);
    }
    b.replaceChildren(iconSpan("wifiOff"), node("span", "qol-words", say("This computer is offline - online models cannot answer until it is back.")));
    if (local) b.append(textBtn("send small", say("Use {name}", { name: local.label }), "Use a model on this computer", "Switch to a model that runs here, without the internet.", async () => { await chooseModel(local.name); b.hidden = true; }));
    b.append(textBtn("quiet small", "×", "Hide", "Hide this.", () => { b.hidden = true; }));
    b.hidden = false;
  }

  // ------------------------------------------------------------------ sending: queue, steer, recovery
  const _send = send;
  send = async function (text, opts) {   // eslint-disable-line no-global-assign
    opts = opts || {};
    if (!String(text || "").trim()) return;
    if (state.busy && !opts.qolInternal) { enqueue(text); return; }
    Object.assign(turn, { text, data: null, error: null, started: Date.now(), news: Date.now(), extended: 0, stopped: false,
      sendNow: false, retryAfterStop: "", switchAfterStop: "" });
    clearDraft();
    const watch = setInterval(slowCheck, 2000);
    try { await _send(text, opts); } finally { clearInterval(watch); dropCard(turn.slowCard); turn.slowCard = null; }
    await afterTurn(text);
  };

  async function afterTurn(text) {
    const data = turn.data, err = turn.error, took = Date.now() - turn.started;
    if (!data && !err) return;   // options card / background job: no answer to look at
    if (err) {
      dropNotice("Lost the connection to the Loki engine");
      if (!$q("#prompt").value.trim()) $q("#prompt").value = text;
      if (conn.up) { lostEngine("/chat", err); }
      recoveryCard({ kind: "engine", title: say("The answer was cut off"),
        advice: say("LOKI's engine stopped answering in the middle of this message. It may be restarting after an update. LOKI reconnects by itself; your message is back in the box."),
        actions: ["reconnect", "retry", "details"], labels: {} }, text);
      pauseQueue();
      return;
    }
    const leftover = (data.steers_left || []);
    for (let i = queue.length - 1; i >= 0; i--) if (queue[i].mode === "steering") queue.splice(i, 1);
    leftover.slice().reverse().forEach((t) => queue.unshift({ id: ++seq, text: t, mode: "queued" }));
    if (data.ok) {
      finishedNote(took, String(data.response || "").split("\n")[0], true);
      const stoppedText = turn.retryAfterStop, switchText = turn.switchAfterStop;
      if (stoppedText) { renderQueue(); return send(stoppedText, { direct: true, quiet: true }); }
      if (switchText) { renderQueue(); return switchCard(switchText); }
      if (turn.stopped && !turn.sendNow) { returnQueueToBox(); return; }
      contextCheck();
      renderQueue();
      return nextInQueue();
    }
    finishedNote(took, String(data.error || ""), false);
    const message = String(data.error || "");
    dropNotice(message);
    if (!$q("#prompt").value.trim()) { $q("#prompt").value = text; autosize(); }
    let rec = data.recovery;
    if (!rec) rec = await api("/qol/classify", { error: message }).catch(() => null);
    recoveryCard(rec || { kind: "unknown", title: "LOKI could not answer", advice: "", actions: ["retry", "details"], labels: {} }, text, message);
    pauseQueue();
  }

  function enqueue(text) {
    queue.push({ id: ++seq, text, mode: "queued" });
    queue.paused = false;
    renderQueue();
    setStatus(say("Queued - LOKI sends it when it is free"), "wait");
  }

  async function steer(item) {
    const out = await api("/qol/steer", { text: item.text }).catch(() => null);
    if (out && out.ok) { item.mode = "steering"; item.steerId = out.id; renderQueue(); return; }
    if (out && out.idle) { removeItem(item); send(item.text); return; }
    addNotice((out && out.error) || say("Could not steer - it stays in the queue."), true);
  }

  function steerText(text) { const item = { id: ++seq, text, mode: "queued" }; queue.push(item); renderQueue(); steer(item); }

  async function sendNow(item) {
    const i = queue.indexOf(item);
    if (i > 0) { queue.splice(i, 1); queue.unshift(item); }
    if (item.mode === "steering") { await api("/qol/steer/cancel", { id: item.steerId }).catch(() => null); item.mode = "queued"; }
    turn.sendNow = true;
    queue.paused = false;
    renderQueue();
    if (state.busy) { await api("/cancel", {}).catch(() => null); setStatus("Stopping, then sending yours…"); } else nextInQueue();
  }

  function removeItem(item) {
    const i = queue.indexOf(item);
    if (i >= 0) queue.splice(i, 1);
    if (item.mode === "steering") api("/qol/steer/cancel", { id: item.steerId }).catch(() => null);
    renderQueue();
  }

  function editItem(item) {
    removeItem(item);
    const p = $q("#prompt");
    p.value = item.text + (p.value.trim() ? "\n\n" + p.value : "");
    autosize(); p.focus();
  }

  function nextInQueue() {
    if (state.busy || queue.paused) return;
    const item = queue.find((q) => q.mode === "queued");
    if (!item) { renderQueue(); return; }
    removeItem(item);
    setTimeout(() => send(item.text, { direct: true }), 250);
  }

  function pauseQueue() { if (queue.length) { queue.paused = true; renderQueue(); } }

  function returnQueueToBox() {
    if (!queue.length) { renderQueue(); return; }
    const p = $q("#prompt");
    const texts = queue.map((q) => q.text);
    queue.length = 0;
    p.value = [p.value.trim(), ...texts].filter(Boolean).join("\n\n");
    autosize();
    renderQueue();
    addNotice(say("Stopped. Your waiting messages are back in the box."));
  }

  function renderQueue() {
    let box = $q("#qol-queue");
    if (!box) {
      box = node("section", "qol-queue"); box.id = "qol-queue"; box.setAttribute("aria-label", "Waiting messages");
      $q("#composer").before(box);
    }
    box.replaceChildren();
    box.hidden = !queue.length;
    if (!queue.length) return;
    if (queue.paused) {
      const head = node("div", "qol-queue-head");
      head.append(node("span", "", say("Paused after a problem - {n} waiting.", { n: queue.length })),
        textBtn("quiet small", say("Send them"), "Send them", "Carry on sending the waiting messages.", () => { queue.paused = false; nextInQueue(); }),
        textBtn("quiet small", say("Put them in the box"), "Put them in the box", "Move them back into the message box.", returnQueueToBox));
      box.append(head);
    }
    for (const item of queue) {
      const row = node("div", "qol-q " + item.mode);
      row.append(node("span", "qol-q-tag", item.mode === "steering" ? say("Steering") : say("Queued")),
        node("span", "qol-q-text", item.text.length > 160 ? item.text.slice(0, 157) + "..." : item.text));
      if (item.mode === "queued" && state.busy) row.append(iconBtn("steer", "Steer", "LOKI reads this at its next step instead of waiting for the end (Ctrl/Cmd+Enter).", () => steer(item)));
      if (state.busy) row.append(iconBtn("sendNow", "Send now", "Stop the current step and send this right away (what LOKI already changed is kept).", () => sendNow(item)));
      row.append(iconBtn("pen", "Edit", "Move it back into the message box to change it.", () => editItem(item)),
        iconBtn("close", "Remove", "Throw this waiting message away.", () => removeItem(item)));
      box.append(row);
    }
  }

  // ------------------------------------------------------------------ progress: steers read, news, thinking
  function watchProgress(data) {
    if (!data || !data.ok) return;
    for (const ev of data.progress || []) {
      if (Number(ev.id) <= state.cursor) continue;
      const text = String(ev.text || "");
      if (!/^(Still working|Loki is thinking)/.test(text)) turn.news = Date.now();
      if (ev.event === "steer") {
        let s = {};
        try { s = JSON.parse(text); } catch (_) { s = { text }; }
        const item = queue.find((q) => q.mode === "steering" && q.steerId === s.id);
        if (item) { const i = queue.indexOf(item); queue.splice(i, 1); renderQueue(); }
        addUser(s.text || "");
        const last = [...document.querySelectorAll("#transcript .turn.user")].pop();
        if (last) { last.classList.add("steered"); last.prepend(node("span", "qol-steered", say("Steered"))); }
      } else if (ev.event === "thinking" && prefs.thinking && / thought: /.test(text)) {
        addEvent("thinking", text);
      }
    }
  }

  function slowCheck() {
    if (!state.busy || turn.slowCard || !prefs.slowAfter) return;
    if (Date.now() < turn.extended) return;
    if (Date.now() - turn.news < prefs.slowAfter * 1000) return;
    const card = node("div", "qol-card slow");
    card.append(node("h3", "", say("No news from the model for {s} seconds", { s: Math.round((Date.now() - turn.news) / 1000) })),
      node("p", "", say("It may be a busy server or a long step. Keep waiting, or stop and try again - with this model or another one.")));
    const row = node("div", "qol-actions");
    row.append(textBtn("send small", say("Keep waiting"), "Keep waiting", "Wait 3 more minutes before asking again.", () => { turn.extended = Date.now() + 180000; dropCard(card); turn.slowCard = null; }),
      textBtn("quiet small", say("Stop and try again"), "Stop and try again", "Stop this answer and send the same message again.", () => { turn.retryAfterStop = turn.text; api("/cancel", {}); dropCard(card); }),
      textBtn("quiet small", say("Stop and use another model"), "Stop and use another model", "Stop, then pick a different model for the same message.", () => { turn.switchAfterStop = turn.text; api("/cancel", {}); dropCard(card); }));
    card.append(row);
    turn.slowCard = card;
    $q("#transcript").append(card);
    scrollDown();
  }

  // ------------------------------------------------------------------ recovery cards
  const ACTION_WORDS = {
    retry: ["Try again", "Send the same message again."],
    wait: ["Wait, then try again", "Count down, then send it again by itself."],
    switch: ["Use another model", "Pick a model that is ready right now and send it there."],
    local: ["Use a model on this computer", "Answer without the internet, on this computer."],
    smart: ["Let LOKI pick", "Smart mode: LOKI uses a model that works now and switches when one runs out."],
    compact: ["Summarize and try again", "Shorten the chat to a summary (the history is kept), then send it again."],
    new_chat: ["Start a new chat", "A fresh chat with your message in the box."],
    connections: ["Fix the key", "Open Settings > Connections to paste a new key or connect a provider."],
    models: ["Local models", "Open Settings > Local models to start or download a model on this computer."],
    details: ["What happened?", "The steps and errors LOKI saw, and what to try."],
    draft: ["Put it back in the box", "Your message goes back into the message box to change or send later."],
    reconnect: ["Reconnect now", "Ask LOKI's engine again right away."],
  };

  function recoveryCard(rec, text, error) {
    removeCard(rec.kind === "engine" ? "engine" : "");
    const card = node("div", "qol-card recovery kind-" + (rec.kind || "unknown"));
    card.dataset.kind = rec.kind || "unknown";
    card.setAttribute("role", "group");
    card.setAttribute("aria-label", rec.title || "LOKI could not answer");
    card.append(node("h3", "", rec.title || "LOKI could not answer"));
    if (rec.advice) card.append(node("p", "", rec.advice));
    const err = error || rec.error;
    if (err) { const d = node("details", "qol-err"); d.append(node("summary", "", say("The error")), node("pre", "", err)); card.append(d); }
    const row = node("div", "qol-actions");
    const alts = rec.alternatives || [];
    for (const a of rec.actions || []) {
      const words = ACTION_WORDS[a];
      if (!words) continue;
      const label = (rec.labels && rec.labels[a]) || words[0];
      const b = textBtn(a === (rec.actions || [])[0] ? "send small" : "quiet small", label, label, words[1], () => act(a, rec, text, card, b));
      b.dataset.action = a;
      row.append(b);
    }
    card.append(row);
    if (alts.length && (rec.actions || []).includes("switch")) {
      const pick = node("div", "qol-alts"); pick.hidden = true;
      for (const m of alts) pick.append(textBtn("quiet small", m.label + (m.local ? " · " + say("on this computer") : ""), m.label, "Use " + m.label + " and send it again.", async () => { await chooseModel(m.name); settle(card); resend(text); }));
      card.append(pick);
    }
    $q("#transcript").append(card);
    scrollDown();
    const auto = rec.wait_s && prefs.autoRetry && ["network", "rate_limit"].includes(rec.kind);
    const tries = (turn.autoTries[text] = (turn.autoTries[text] || 0) + (auto ? 1 : 0));
    if (auto && tries <= 5) { const w = row.querySelector('[data-action="wait"]'); if (w) act("wait", rec, text, card, w); }
    return card;
  }

  async function act(a, rec, text, card, b) {
    if (a === "retry") { settle(card); return resend(text); }
    if (a === "wait") return countdown(b, rec.wait_s || 15, () => { settle(card); resend(text); });
    if (a === "switch") { const p = $q(".qol-alts", card); if (p) { p.hidden = !p.hidden; return; } toggleModelMenu(true); return; }
    if (a === "local") {
      const m = (rec.alternatives || []).find((x) => x.local);
      if (!m) { openSettings(); showTab("models"); return; }
      await chooseModel(m.name); settle(card); return resend(text);
    }
    if (a === "smart") { await chooseModel("smart"); settle(card); return resend(text); }
    if (a === "compact") {
      b.disabled = true;
      const out = await api("/qol/compact", {}).catch(() => null);
      addNotice((out && (out.note || out.error)) || "Could not summarize.", !(out && out.ok));
      settle(card); return resend(text);
    }
    if (a === "new_chat") { settle(card); await newChat(); $q("#prompt").value = text; autosize(); return; }
    if (a === "connections") { openSettings(); showTab("connections"); return; }
    if (a === "models") { openSettings(); showTab("models"); return; }
    if (a === "details") return whatHappened();
    if (a === "draft") { const p = $q("#prompt"); p.value = text; autosize(); p.focus(); return; }
    if (a === "reconnect") { if (await reconnectNow()) settle(card); }
  }

  function resend(text) { $q("#prompt").value = $q("#prompt").value.trim() === text.trim() ? "" : $q("#prompt").value; return send(text, { direct: true, quiet: true }); }

  function countdown(b, seconds, done) {
    if (b.dataset.counting) { clearInterval(Number(b.dataset.counting)); delete b.dataset.counting; b.textContent = b.dataset.tipName; return; }
    let left = Math.max(1, Math.round(seconds));
    const paint = () => { b.textContent = say("Trying again in {s} s (click to cancel)", { s: left }); };
    paint();
    const id = setInterval(() => {
      left -= 1;
      if (left <= 0) { clearInterval(id); delete b.dataset.counting; done(); return; }
      paint();
    }, 1000);
    b.dataset.counting = String(id);
  }

  async function switchCard(text) {
    const alts = await api("/qol/alternatives").catch(() => null);
    recoveryCard({ kind: "switch", title: say("Pick another model for this message"), advice: "",
      actions: ["switch", "smart", "draft"], labels: {}, alternatives: (alts && alts.alternatives) || [] }, text);
    const pick = $q("#transcript .qol-card:last-of-type .qol-alts");
    if (pick) pick.hidden = false;
  }

  function settle(card) { if (!card) return; card.classList.add("settled"); for (const x of card.querySelectorAll("button")) x.disabled = true; }
  function removeCard(kind) { for (const c of document.querySelectorAll("#transcript .qol-card.recovery" + (kind ? ".kind-" + kind : "") + ":not(.settled)")) if (kind) c.remove(); }
  function dropCard(c) { if (c && c.parentNode) c.remove(); }
  function dropNotice(text) {
    const t = String(text || "").trim();
    for (const n of [...document.querySelectorAll("#transcript .notice.error")].slice(-3)) if (t && n.textContent.trim().startsWith(t.slice(0, 60))) n.remove();
  }

  // ------------------------------------------------------------------ what happened
  async function whatHappened() {
    const dlg = LokiDialog("qol-why", "qol.why", "What happened?", { wide: true });
    dlg.body.replaceChildren(node("p", "note", say("Looking...")));
    dlg.open();
    const d = await _api("/qol/diagnose").catch(() => null);
    dlg.body.replaceChildren();
    const lines = [];
    if (!d || !d.ok) {
      dlg.body.append(node("p", "", say("LOKI's engine is not answering. It may be restarting after an update (that takes up to a minute), or it stopped. Your chats are saved on disk. If it does not come back, quit LOKI and open it again; LOKI Studio's Logs show why it stopped.")));
      lines.push("engine: not answering");
    } else {
      const top = node("div", "qol-why-top");
      top.append(node("div", "", say("Model: {m} (using {u} now)", { m: d.model, u: d.using })),
        node("div", "", say("Engine up for {s} s{busy}", { s: d.engine_up_s, busy: d.busy ? " - working now" : "" })));
      dlg.body.append(top);
      if (d.recovery) dlg.body.append(node("p", "qol-why-advice", d.recovery.title + ": " + d.recovery.advice));
      if ((d.errors || []).length) { dlg.body.append(node("h3", "", say("Errors"))); dlg.body.append(node("pre", "qol-why-pre", d.errors.join("\n"))); }
      if ((d.steps || []).length) { dlg.body.append(node("h3", "", say("Last steps"))); dlg.body.append(node("pre", "qol-why-pre", d.steps.map((s) => s.event + ": " + s.text).join("\n"))); }
      if ((d.route || []).length) { dlg.body.append(node("h3", "", say("How LOKI picked the model"))); dlg.body.append(node("pre", "qol-why-pre", d.route.join("\n"))); }
      if (d.providers) { const det = node("details"); det.append(node("summary", "", say("Providers")), node("pre", "qol-why-pre", d.providers)); dlg.body.append(det); }
      lines.push("model: " + d.model + " / " + d.using, ...(d.errors || []), ...(d.steps || []).map((s) => s.event + ": " + s.text));
    }
    if (conn.log.length) { dlg.body.append(node("h3", "", say("Connection"))); dlg.body.append(node("pre", "qol-why-pre", conn.log.map((l) => l.t + "  " + l.what).join("\n"))); lines.push(...conn.log.map((l) => l.t + " " + l.what)); }
    dlg.body.append(textBtn("quiet small", say("Copy this report"), "Copy this report", "Copy it to paste into a bug report or a chat with Claude.", () => copy(lines.join("\n"))));
  }

  // ------------------------------------------------------------------ after a turn: notify, context
  let audio = null;
  function finishedNote(took, line, ok) {
    if (!prefs.notify || took < prefs.notifyAfter * 1000) return;
    if (!document.hidden && document.hasFocus()) return;
    api("/qol/notify", { title: ok ? say("LOKI finished") : say("LOKI needs you"), text: String(line || "").slice(0, 200) }).catch(() => null);
    if (prefs.sound) chime();
  }

  function chime() {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      [660, 880].forEach((f, i) => {
        const o = audio.createOscillator(), g = audio.createGain();
        o.frequency.value = f; o.connect(g); g.connect(audio.destination);
        const t = audio.currentTime + i * 0.14;
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.15, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
        o.start(t); o.stop(t + 0.3);
      });
    } catch (_) { /* no audio here */ }
  }

  async function contextCheck() {
    const c = await api("/qol/context").catch(() => null);
    let bar = $q("#qol-context");
    if (!c || !c.ok || c.level === "ok" || !c.enabled) { if (bar) bar.hidden = true; return; }
    if (!bar) { bar = node("div", "qol-context"); bar.id = "qol-context"; bar.setAttribute("role", "status"); $q("#composer").before(bar); }
    bar.replaceChildren(node("span", "qol-words", c.level === "full"
      ? say("This chat is full ({p}%): LOKI summarizes older messages before each answer. Summarize now, or start a new chat for a new topic.", { p: c.percent })
      : say("This chat is getting long ({p}% of what LOKI sends before it summarizes).", { p: c.percent })),
      textBtn("quiet small", say("Summarize now"), "Summarize now", "Shorten the older part of this chat to a summary for the model; the full history stays.", async (b) => {
        b.disabled = true; const out = await api("/qol/compact", {}).catch(() => null);
        addNotice((out && (out.note || out.error)) || "Could not summarize.", !(out && out.ok)); contextCheck();
      }),
      textBtn("quiet small", say("New chat"), "New chat", "Start a fresh chat for a new topic.", () => newChat()),
      textBtn("quiet small", "×", "Hide", "Hide this until the next answer.", () => { bar.hidden = true; }));
    bar.hidden = false;
  }

  // ------------------------------------------------------------------ approvals: allow for this session
  function noteTicket(ticket) {
    if (!ticket || (lastTicket && lastTicket.id === ticket.id)) return;
    lastTicket = ticket;
    if (prefs.notify && (document.hidden || !document.hasFocus())) {
      api("/qol/notify", { title: say("LOKI needs your OK"), text: "LOKI wants to run " + ticket.tool }).catch(() => null);
      if (prefs.sound) chime();
    }
  }

  function decorateApprovals() {
    for (const card of document.querySelectorAll("#transcript .approval:not(.settled):not([data-qol])")) {
      card.dataset.qol = "1";
      const actions = $q(".actions", card), deny = actions && [...actions.querySelectorAll("button")].find((b) => !b.classList.contains("allow"));
      const ticket = lastTicket;
      if (!actions || !deny || !ticket || (info.never_session || []).includes(ticket.tool)) continue;
      const b = textBtn("qol-allow-session", say("Allow for this session"), "Allow for this session",
        "Allow it now, and do not ask again for this exact action until LOKI restarts.", async () => {
          for (const x of actions.querySelectorAll("button")) x.disabled = true;
          const out = await api("/qol/approval", { id: ticket.id }).catch(() => null);
          if (out && out.ok) {
            card.classList.add("settled");
            actions.replaceChildren(node("span", "", say("Allowed - LOKI will not ask again for this exact action until it restarts.")));
            setStatus("Working…");
          } else {
            for (const x of actions.querySelectorAll("button")) x.disabled = false;
            b.remove();
            addNotice((out && out.error) || "Could not do that - choose Allow or Deny.", true);
          }
        });
      deny.before(b);
    }
  }

  // ------------------------------------------------------------------ drafts, long pastes, recall
  let draftTimer = 0;
  function saveDraft() { clearTimeout(draftTimer); draftTimer = setTimeout(() => { try { localStorage.setItem(DRAFT_KEY, $q("#prompt").value); } catch (_) { /* no storage */ } }, 300); }
  function clearDraft() { clearTimeout(draftTimer); try { localStorage.removeItem(DRAFT_KEY); } catch (_) { /* no storage */ } }
  function restoreDraft() {
    let d = "";
    try { d = localStorage.getItem(DRAFT_KEY) || ""; } catch (_) { d = ""; }
    const p = $q("#prompt");
    if (d && p && !p.value.trim()) { p.value = d; autosize(); markRestored(); }
  }
  function markRestored() {
    const p = $q("#prompt");
    p.classList.add("qol-restored");
    p.title = say("Your unsent message from last time is back.");
    setTimeout(() => p.classList.remove("qol-restored"), 4000);
  }

  async function longPaste(ev) {
    const text = ev.clipboardData && ev.clipboardData.getData("text/plain");
    if (!text || text.length < prefs.pasteLimit) return;
    ev.preventDefault();
    const p = $q("#prompt"), at = p.selectionStart, end = p.selectionEnd;
    const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..*/, "").replace("T", "-");
    const name = "paste-" + stamp + ".txt";
    let path = "";
    try {
      const r = await fetch("/files/upload?name=" + encodeURIComponent(name) + "&dir=uploads", {
        method: "POST", headers: { Authorization: "Bearer " + state.token, "Content-Type": "application/octet-stream" }, body: new Blob([text], { type: "text/plain" }) });
      const d = await r.json();
      if (d.ok) path = d.path;
    } catch (_) { path = ""; }
    const insert = path ? "@" + path + " " : text;
    p.value = p.value.slice(0, at) + insert + p.value.slice(end);
    p.selectionStart = p.selectionEnd = at + insert.length;
    autosize(); saveDraft();
    if (path) addNotice(say("Your long paste ({n} characters) was saved as {path} and goes with your message as an attached file.", { n: text.length, path }));
  }

  function recall() {
    const p = $q("#prompt");
    const last = queue.length ? queue[queue.length - 1] : null;
    if (last) { editItem(last); return true; }
    const turnEl = [...document.querySelectorAll("#transcript .turn.user")].pop();
    if (!turnEl) return false;
    p.value = turnEl.dataset.raw || ($q(".bubble", turnEl) || turnEl).textContent;
    autosize();
    p.selectionStart = p.selectionEnd = p.value.length;
    return true;
  }

  // ------------------------------------------------------------------ chats: pins, rename, search, find
  const _render = renderConversations;
  renderConversations = function () {   // eslint-disable-line no-global-assign
    const pins = info.pins || [];
    if (pins.length) {
      const rank = (c) => { const i = pins.indexOf(c.id); return i < 0 ? 1e6 : i; };
      state.conversations = state.conversations.map((c, i) => [c, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map((x) => x[0]);
    }
    _render();
    const rows = [...document.querySelectorAll("#conversations .convo")];
    rows.forEach((row, i) => {
      const c = state.conversations[i];
      if (!c) return;
      const pinned = pins.includes(c.id);
      row.classList.toggle("pinned", pinned);
      const pin = iconBtn("pin", pinned ? "Unpin" : "Pin", pinned ? "Take this chat off the top of the list." : "Keep this chat at the top of the list.", () => togglePin(c.id, !pinned));
      pin.classList.add("qol-pin");
      row.insertBefore(pin, row.querySelector(".del"));
      row.dataset.qolId = c.id;
    });
  };

  // double-click (or F2) a chat to rename it. One listener on the list: the first click of a double-click
  // switches to the chat and redraws the rows, so a listener on the old row would miss the second click.
  function wireRename() {
    const nav = $q("#conversations");
    if (!nav) return;
    const start = (e) => {
      const row = e.target.closest && e.target.closest(".convo");
      if (!row || !row.dataset.qolId || e.target.closest(".qol-rename")) return;
      const id = row.dataset.qolId;
      e.preventDefault();
      setTimeout(() => { const c = (state.conversations || []).find((x) => x.id === id), r = rowFor(id); if (c && r) renameInline(r, c); }, 300);
    };
    nav.addEventListener("dblclick", start);
    nav.addEventListener("keydown", (e) => { if (e.key === "F2") start(e); });
  }

  function rowFor(id) {
    const i = (state.conversations || []).findIndex((c) => c.id === id);
    return i < 0 ? null : document.querySelectorAll("#conversations .convo")[i] || null;
  }

  async function togglePin(id, pinned) {
    const out = await api("/qol/pin", { id, pinned }).catch(() => null);
    if (out && out.ok) { info.pins = out.pins; renderConversations(); }
  }

  function renameInline(row, c) {
    if (state.busy || row.querySelector("input")) return;
    const open = row.querySelector(".open");
    const input = node("input", "qol-rename"); input.value = c.title || ""; input.setAttribute("aria-label", "Chat name");
    open.hidden = true; row.prepend(input); input.focus(); input.select();
    let done = false;
    const finish = async (save) => {
      if (done) return; done = true;
      const title = input.value.trim();
      input.remove(); open.hidden = false;
      if (!save || !title || title === c.title) return;
      const out = await api("/conversations/rename", { id: c.id, title }).catch(() => null);
      if (out && out.ok) applyConversations(out); else addNotice((out && out.error) || "Could not rename it.", true);
    };
    input.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); });
    const born = Date.now();   // the chat switch focuses the message box right after: keep the rename field
    input.addEventListener("blur", () => { if (Date.now() - born < 800) { setTimeout(() => { if (input.isConnected) input.focus(); }, 0); return; } finish(true); });
  }

  function openSearch() {
    const dlg = LokiDialog("qol-search", "qol.search", "Search all chats", { wide: true, focus: "input" });
    if (!dlg.body.firstChild) {
      const input = node("input", "qol-search-input"); input.type = "search"; input.placeholder = say("Words in a chat's name or messages"); input.setAttribute("aria-label", "Search all chats");
      const list = node("div", "qol-results"); list.setAttribute("role", "listbox");
      dlg.body.append(input, list);
      let timer = 0, pick = 0;
      const paint = (results, q) => {
        list.replaceChildren();
        if (!q) return;
        if (!results.length) { list.append(node("p", "note", say("Nothing found."))); return; }
        results.forEach((r, i) => {
          const b = node("button", "qol-hit-row" + (i === pick ? " on" : "")); b.type = "button"; b.setAttribute("role", "option");
          b.append(node("b", "", r.title), node("span", "", r.where === "title" ? say("in the name") : (r.role === "user" ? "You: " : "LOKI: ") + r.snippet));
          b.addEventListener("click", () => openHit(r, q, dlg));
          list.append(b);
        });
      };
      input.addEventListener("input", () => {
        clearTimeout(timer); pick = 0;
        timer = setTimeout(async () => {
          const q = input.value.trim();
          const out = q ? await api("/qol/search?q=" + encodeURIComponent(q)).catch(() => null) : null;
          input._results = (out && out.results) || [];
          paint(input._results, q);
        }, 180);
      });
      input.addEventListener("keydown", (e) => {
        const rs = input._results || [];
        if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); pick = (pick + (e.key === "ArrowDown" ? 1 : -1) + rs.length) % Math.max(1, rs.length); paint(rs, input.value.trim()); }
        if (e.key === "Enter" && rs[pick]) { e.preventDefault(); openHit(rs[pick], input.value.trim(), dlg); }
      });
    }
    dlg.open();
  }

  async function openHit(r, q, dlg) {
    dlg.hide("picked");
    if (r.id !== state.active) await switchTo(r.id); else showChat();
    if (r.where === "message") setTimeout(() => openFind(q), 150);
  }

  const find = { bar: null, hits: [], at: -1 };
  function openFind(q) {
    if (!find.bar) {
      const bar = node("div", "qol-find"); bar.setAttribute("role", "search");
      const input = node("input"); input.type = "search"; input.placeholder = say("Find in this chat"); input.setAttribute("aria-label", "Find in this chat");
      const count = node("span", "qol-find-count");
      bar.append(input, count,
        textBtn("quiet small", "↑", "Previous match", "Go to the previous match (Shift+Enter).", () => step(-1)),
        textBtn("quiet small", "↓", "Next match", "Go to the next match (Enter).", () => step(1)),
        textBtn("quiet small", "×", "Close", "Close the find bar (Esc).", closeFind));
      input.addEventListener("input", () => run(input.value));
      input.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") { e.preventDefault(); step(e.shiftKey ? -1 : 1); } if (e.key === "Escape") closeFind(); });
      $q("#transcript").before(bar);
      find.bar = bar; find.input = input; find.count = count;
    }
    find.bar.hidden = false;
    if (typeof q === "string") { find.input.value = q; run(q); }
    find.input.focus(); find.input.select();
    function run(text) {
      for (const h of find.hits) h.classList.remove("qol-hit", "qol-hit-now");
      const words = String(text || "").toLowerCase().split(/\s+/).filter(Boolean);
      find.hits = words.length ? [...document.querySelectorAll("#transcript .turn")].filter((t) => { const s = (t.dataset.raw || t.textContent).toLowerCase(); return words.every((w) => s.includes(w)); }) : [];
      for (const h of find.hits) h.classList.add("qol-hit");
      find.at = -1;
      step(1);
    }
    function step(d) {
      if (!find.hits.length) { find.count.textContent = find.input.value ? say("none") : ""; return; }
      if (find.hits[find.at]) find.hits[find.at].classList.remove("qol-hit-now");
      find.at = (find.at + d + find.hits.length) % find.hits.length;
      const h = find.hits[find.at];
      h.classList.add("qol-hit-now");
      h.scrollIntoView({ block: "center" });
      find.count.textContent = (find.at + 1) + " / " + find.hits.length;
    }
  }
  function closeFind() { if (!find.bar) return; for (const h of find.hits) h.classList.remove("qol-hit", "qol-hit-now"); find.hits = []; find.bar.hidden = true; $q("#prompt").focus(); }

  function jump(d) {
    const turns = [...document.querySelectorAll("#transcript .turn")];
    if (!turns.length) return;
    const box = $q("#transcript").getBoundingClientRect();
    let i = turns.findIndex((t) => t.getBoundingClientRect().top >= box.top + 4);
    if (i < 0) i = turns.length - 1;
    const target = turns[Math.max(0, Math.min(turns.length - 1, i + (d > 0 ? 1 : -1)))];
    target.scrollIntoView({ block: "start" });
    target.classList.add("qol-hit-now"); setTimeout(() => target.classList.remove("qol-hit-now"), 900);
  }

  function chatMarkdown() {
    const title = ($q("#chat-title") || {}).textContent || "LOKI chat";
    const parts = ["# " + title, ""];
    for (const t of document.querySelectorAll("#transcript .turn")) {
      const raw = t.dataset.raw || ($q(".bubble, .text", t) || t).textContent;
      parts.push((t.classList.contains("user") ? "**You:**" : "**LOKI:**") + "\n\n" + String(raw).trim(), "");
    }
    return parts.join("\n");
  }
  function copyChat() { copy(chatMarkdown()); addNotice(say("This chat is on the clipboard as Markdown.")); }

  // ------------------------------------------------------------------ keyboard shortcuts
  const ACTIONS = [
    { id: "newChat", name: "New chat", def: "Mod+N", run: () => newChat() },
    { id: "search", name: "Search all chats", def: "Mod+K", run: openSearch },
    { id: "find", name: "Find in this chat", def: "Mod+F", run: () => { showChat(); openFind(); } },
    { id: "model", name: "Open the model picker", def: "Mod+Shift+M", run: () => toggleModelMenu(true) },
    { id: "settings", name: "Open Settings", def: "Mod+,", run: () => openSettings() },
    { id: "sidebar", name: "Show or hide the chat list", def: "Mod+B", run: () => document.body.classList.toggle("qol-no-sidebar") },
    { id: "stop", name: "Stop LOKI", def: "Mod+.", run: () => { if (state.busy) $q("#stop").click(); } },
    { id: "copyChat", name: "Copy this chat as Markdown", def: "Mod+Shift+C", run: copyChat },
    { id: "prev", name: "Previous message", def: "Alt+ArrowUp", run: () => jump(-1) },
    { id: "next", name: "Next message", def: "Alt+ArrowDown", run: () => jump(1) },
    { id: "why", name: "What happened?", def: "Mod+Shift+H", run: whatHappened },
    { id: "prefs", name: "Shortcuts and chat comfort", def: "Mod+/", run: openPrefs },
  ];
  const KEYS = { Comma: ",", Period: ".", Slash: "/", Semicolon: ";", Quote: "'", BracketLeft: "[", BracketRight: "]", Backslash: "\\", Minus: "-", Equal: "=", Backquote: "`", Space: "Space", Enter: "Enter" };
  function comboOf(e) {
    let key = e.code && /^Key[A-Z]$/.test(e.code) ? e.code.slice(3) : e.code && /^Digit\d$/.test(e.code) ? e.code.slice(5) : KEYS[e.code] || e.key;
    if (!key || ["Control", "Meta", "Shift", "Alt", "OS"].includes(key)) return "";
    if (key.length === 1) key = key.toUpperCase();
    const mod = e.ctrlKey || e.metaKey;   // Ctrl and Cmd (macOS) are both "Mod": the labels say Ctrl/Cmd
    return [mod ? "Mod" : "", e.altKey ? "Alt" : "", e.shiftKey ? "Shift" : "", key].filter(Boolean).join("+");
  }
  function comboOfAction(a) { return a.id in prefs.shortcuts ? prefs.shortcuts[a.id] : a.def; }
  function showCombo(c) { return !c ? say("(none)") : c.replace("Mod", isMac ? "⌘" : "Ctrl").replace("Alt", isMac ? "⌥" : "Alt").replace("ArrowUp", "↑").replace("ArrowDown", "↓"); }
  let recording = null;

  function onKey(e) {
    if (recording || e.defaultPrevented) return;
    const t = e.target;
    // queue / steer from the message box while LOKI works
    if (t && t.id === "prompt" && e.key === "Enter" && !e.shiftKey && !e.isComposing && !($q(".wb-menu") && !$q(".wb-menu").hidden)) {
      const mod = e.ctrlKey || e.metaKey;
      if (state.busy) {
        const text = t.value;
        if (!text.trim()) return;
        e.preventDefault(); e.stopImmediatePropagation();
        t.value = ""; autosize(); clearDraft();
        if (mod) steerText(text); else enqueue(text);
        return;
      }
    }
    if (t && t.id === "prompt" && e.key === "ArrowUp" && !e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey && !t.value && !($q(".wb-menu") && !$q(".wb-menu").hidden)) {
      if (recall()) e.preventDefault();
      return;
    }
    const combo = comboOf(e);
    if (!combo || (!/Mod|Ctrl|Alt/.test(combo))) return;
    if (typeof window.forgeOwnsKey === "function" && window.forgeOwnsKey(e)) return;   // Forge's Maya keys win in Forge (Ctrl+B bevel, Alt+Up nudge ...)
    if (document.querySelector('.sheet:not([hidden]) [role="dialog"]')) return;   // shortcuts pause while a dialog is open
    const a = ACTIONS.find((x) => comboOfAction(x) === combo);
    if (!a) return;
    e.preventDefault(); e.stopPropagation();
    a.run();
  }

  // ------------------------------------------------------------------ the comfort dialog
  function openPrefs() {
    const dlg = LokiDialog("qol-prefs", "qol.prefs", "Shortcuts and chat comfort", { wide: true });
    paintPrefs(dlg.body);
    dlg.open();
  }

  function paintPrefs(body) {
    body.replaceChildren();
    body.append(node("h3", "", say("Keyboard shortcuts")),
      node("p", "note", say("Click a shortcut, then press the new keys (with Ctrl, Cmd or Alt). Esc cancels. In the message box: Enter while LOKI works queues your message, Ctrl/Cmd+Enter steers, Up brings back your last message.")));
    const table = node("div", "qol-keys");
    for (const a of ACTIONS) {
      const row = node("div", "qol-key-row");
      const b = node("button", "qol-combo", showCombo(comboOfAction(a))); b.type = "button"; b.dataset.action = a.id;
      b.setAttribute("aria-label", a.name + ": " + showCombo(comboOfAction(a)) + ". Press to change.");
      b.addEventListener("click", () => record(a, b, body));
      row.append(node("span", "", a.name), b,
        textBtn("quiet small", say("Clear"), "Clear", "Turn this shortcut off.", () => { prefs.shortcuts[a.id] = ""; savePrefs(); paintPrefs(body); }));
      table.append(row);
    }
    body.append(table, textBtn("quiet small", say("Reset all shortcuts"), "Reset all shortcuts", "Back to the shortcuts LOKI started with.", () => { prefs.shortcuts = {}; savePrefs(); paintPrefs(body); }));
    body.append(node("h3", "", say("Chat comfort")));
    const check = (key, label) => {
      const l = node("label", "qol-pref"); const c = node("input"); c.type = "checkbox"; c.checked = !!prefs[key];
      c.addEventListener("change", () => { prefs[key] = c.checked; savePrefs(); if (key === "sound" && c.checked) chime(); });
      l.append(c, document.createTextNode(" " + label)); return l;
    };
    const num = (key, label, min, max) => {
      const l = node("label", "qol-pref"); const c = node("input"); c.type = "number"; c.min = min; c.max = max; c.value = prefs[key];
      c.addEventListener("change", () => { prefs[key] = Math.max(min, Math.min(max, Number(c.value) || DEFAULTS[key])); savePrefs(); });
      l.append(document.createTextNode(label + " "), c); return l;
    };
    body.append(check("notify", say("Tell me (desktop notification) when a long answer finishes or LOKI needs my OK, if I am in another window")),
      num("notifyAfter", say("Long means more than (seconds)"), 5, 3600),
      check("sound", say("Play a sound then too")),
      check("autoRetry", say("Try again by itself when the connection drops or a model asks to slow down")),
      num("slowAfter", say("Offer choices when there is no news for (seconds, 0 = never)"), 0, 3600),
      check("thinking", say("Show the model's thinking in the chat")),
      num("pasteLimit", say("Pastes longer than this many characters become an attached file"), 1000, 1000000));
    const rules = node("div", "qol-rules");
    body.append(node("h3", "", say("Allowed for this session")), rules);
    _api("/qol/state").then((st) => {
      const list = (st && st.session_rules) || [];
      rules.replaceChildren(list.length ? node("pre", "qol-why-pre", list.map((r) => r.tool + ": " + r.preview).join("\n")) : node("p", "note", say("Nothing - LOKI asks every time.")));
      if (list.length) rules.append(textBtn("quiet small", say("Ask me every time again"), "Ask me every time again", "Forget the actions you allowed for this session.", async () => { await _api("/qol/approvals/clear", {}); paintPrefs(body); }));
    }).catch(() => null);
  }

  function record(a, b, body) {
    recording = a;
    b.textContent = say("Press the keys… (Esc cancels)");
    b.classList.add("recording");
    let stopped = false;
    // the list is drawn again: focus goes back to this shortcut's new button, so a second Esc reaches the sheet and
    // closes it (it used to land on the page body and the sheet stayed open)
    const stop = () => { if (stopped) return; stopped = true; recording = null; b.removeEventListener("keydown", onRec, true); b.removeEventListener("blur", stop); paintPrefs(body);
      const again = body.querySelector('.qol-combo[data-action="' + a.id + '"]'); if (again) again.focus(); };
    const onRec = (e) => {
      e.preventDefault(); e.stopPropagation();
      if (e.key === "Escape" || e.key === "Tab") { stop(); return; }
      const combo = comboOf(e);
      if (!combo) return;
      if (!/Mod|Ctrl|Alt/.test(combo)) { b.textContent = say("Use Ctrl, Cmd or Alt with it - try again"); return; }
      const clash = ACTIONS.find((x) => x !== a && comboOfAction(x) === combo);
      if (clash) { b.textContent = say("{c} is already {name} - clear that one first", { c: showCombo(combo), name: clash.name }); return; }
      prefs.shortcuts[a.id] = combo; savePrefs(); stop();
    };
    b.addEventListener("keydown", onRec, true);
    b.addEventListener("blur", stop);
    b.focus();
  }

  // ------------------------------------------------------------------ small helpers
  function textBtn(cls, label, name, what, fn) {
    const b = node("button", cls, label); b.type = "button";
    b.dataset.tipName = name; b.dataset.tipWhat = what;
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(b); });
    return b;
  }
  function iconBtn(icon, name, what, fn) {
    const b = node("button", "qol-icon"); b.type = "button";
    b.dataset.icon = icon; b.dataset.tipName = name; b.dataset.tipWhat = what; b.textContent = name;
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(b); });
    return b;
  }
  function iconSpan(icon) { const s = node("span", "qol-ico"); s.innerHTML = iconSvg(icon); return s; }
  function placeBanner(b) { const after = $q("#changed-banner") || $q("#update-banner"); if (after) after.after(b); else $q("#main").prepend(b); }
  function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
  async function copy(text) {
    if (window.Artifacts && Artifacts.copyText) return Artifacts.copyText(String(text || ""));
    try { await navigator.clipboard.writeText(String(text || "")); } catch (_) { /* no clipboard */ }
  }

  // ------------------------------------------------------------------ start
  async function afterReady() {
    for (let i = 0; i < 200 && !window.LOKI_READY; i++) await sleep(150);
    if (!window.LOKI_READY) return;
    const st = await api("/qol/state").catch(() => null);
    if (st && st.ok) {
      info = st;
      if ((st.pins || []).length) renderConversations();
      if (st.interrupted) interruptedBanner(st.interrupted);
    }
    restoreDraft();
    if (navigator.onLine === false) offlineBanner(true);
  }

  function interruptedBanner(it) {
    const b = node("div", "qol-banner qol-interrupted"); b.id = "qol-interrupted"; b.setAttribute("role", "status");
    const when = it.t ? new Date(it.t * 1000).toLocaleString() : "";
    const short = it.prompt.length > 120 ? it.prompt.slice(0, 117) + "..." : it.prompt;
    const words = node("div", "qol-words");
    words.append(node("b", "", say("LOKI was closed while it was answering you{when}.", { when: when ? " (" + when + ")" : "" })), node("span", "", "“" + short + "”"));
    const done = () => { b.remove(); api("/qol/interrupted/dismiss", {}).catch(() => null); };
    b.append(iconSpan("update"), words,
      textBtn("send small", say("Send it again"), "Send it again", "Open that chat and send the message again.", async () => {
        done();
        if (it.convo && it.convo !== state.active && (state.conversations || []).some((c) => c.id === it.convo)) await switchTo(it.convo); else showChat();
        send(it.prompt, { direct: true, quiet: true });
      }),
      textBtn("quiet small", say("Put it in the box"), "Put it in the box", "Put the message in the message box to change it first.", () => { done(); summon(true); $q("#prompt").value = it.prompt; autosize(); }),
      textBtn("quiet small", say("Dismiss"), "Dismiss", "Forget it.", done));
    placeBanner(b);
  }

  function wire() {
    document.addEventListener("keydown", onKey, true);
    wireRename();
    const p = $q("#prompt");
    if (p) { p.addEventListener("input", saveDraft); p.addEventListener("paste", longPaste); }
    const stop = $q("#stop");
    if (stop) stop.addEventListener("click", () => { turn.stopped = true; }, true);
    window.addEventListener("offline", () => offlineBanner(true));
    window.addEventListener("online", () => offlineBanner(false));
    // icons with tooltips: search chats (sidebar), shortcuts + comfort (top bar)
    const nc = $q("#new-chat");
    if (nc && !$q("#qol-search-btn")) {
      const s = node("button", "quiet qol-side-search"); s.type = "button"; s.id = "qol-search-btn";
      s.dataset.icon = "search"; s.dataset.tipName = "Search chats"; s.dataset.tipWhat = "Find any chat by its name or by words in it (Ctrl/Cmd+K).";
      s.textContent = "Search chats";
      s.addEventListener("click", openSearch);
      nc.after(s);
    }
    const right = $q(".topbar-right");
    if (right && !$q("#qol-prefs-btn")) {
      const k = node("button", "quiet qol-top"); k.type = "button"; k.id = "qol-prefs-btn";
      k.dataset.icon = "keyboard"; k.dataset.tipName = "Shortcuts and chat comfort"; k.dataset.tipWhat = "Keyboard shortcuts (change them), notifications when a long answer finishes, automatic retry, thinking on/off.";
      k.textContent = "Shortcuts";
      k.addEventListener("click", openPrefs);
      right.insertBefore(k, $q("#status"));
    }
    new MutationObserver(decorateApprovals).observe($q("#transcript"), { childList: true });
    if (window.Workbench && Workbench.COMMANDS) {
      Workbench.COMMANDS.push(
        { name: "compact", hint: "summarize the older part of this chat now", run: async () => { const o = await api("/qol/compact", {}); addNotice((o && (o.note || o.error)) || "", !(o && o.ok)); } },
        { name: "search", hint: "search all chats", run: () => openSearch() },
        { name: "find", hint: "find in this chat", run: (a) => { showChat(); openFind(a); } },
        { name: "copy", hint: "copy this chat as Markdown", run: () => copyChat() },
        { name: "why", hint: "what happened with the last message", run: () => whatHappened() },
        { name: "shortcuts", hint: "keyboard shortcuts and chat comfort", run: () => openPrefs() },
        { name: "queue", hint: "show the waiting messages", run: () => { renderQueue(); addNotice(queue.length ? queue.length + " waiting." : "Nothing is waiting."); } });
    }
  }

  // a switch of model is noted in the chat 
  const _choose = chooseModel;
  chooseModel = async function (name) {   // eslint-disable-line no-global-assign
    const before = modelMenu.data && modelMenu.data.current;
    await _choose(name);
    const now = modelMenu.data && modelMenu.data.current;
    if (now === name && before !== name && !$q("#main").classList.contains("home")) addNotice(say("Switched to {m}. The next message uses it.", { m: modelLabel(name) }));
  };

  document.addEventListener("DOMContentLoaded", () => { wire(); afterReady(); });
  return { prefs: () => Object.assign({}, prefs), queue, turn, conn, classifyAction: act, openSearch, openFind, openPrefs, whatHappened,
    recoveryCard, chatMarkdown, comboOf, ACTIONS, reconnectNow, enqueue, steerText };
})();
