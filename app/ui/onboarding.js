// First run for anyone (session 29): a friendly 4-step welcome.
//   1. What LOKI is + pick a language (and bigger text / high contrast right there)
//   2. Connect a free model in one click: on this computer (Ollama / MLX, detected, with install
//      help) or a free online one (OpenRouter sign-in, Groq or Gemini key)
//   3. What should LOKI help with (saved; the gallery and the examples follow it)
//   4. Try 3 examples, each one click
// Every error says what to do next and every step can be skipped: no dead ends.
//
// It replaces the old first-run sheet (setup.js) for new people; that sheet stays as
// "More choices" here and in Settings > Local models. Someone who already uses LOKI (a model
// works and there are chats) is never shown this: it marks itself done.
"use strict";

(function () {
  const STEPS = 4;
  const INTERESTS = [
    ["everyday", "Everyday life", "☀"], ["work", "Work", "✉"], ["study", "Study", "✎"], ["creative", "Creative", "✿"],
    ["home", "Home", "⌂"], ["money", "Money", "¤"], ["health", "Health info", "♥"], ["business", "Small business", "◆"],
  ];
  const CLOUD = [
    // [id, name, how, sign-up page, key page, key hint]
    ["openrouter", "OpenRouter", "oauth", "https://openrouter.ai", "https://openrouter.ai/keys", "sk-or-"],
    ["groq", "Groq", "key", "https://console.groq.com", "https://console.groq.com/keys", "gsk_"],
    ["gemini", "Google Gemini", "key", "https://aistudio.google.com", "https://aistudio.google.com/apikey", "AIza"],
  ];
  const view = { dlg: null, step: 0, data: null, setup: null, interests: [], timer: 0, connected: "" };

  const tr = (key, en, vars) => (window.LokiI18n ? window.LokiI18n.t(key, en, vars) : en);
  function node(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function keyed(n, key, en, vars) { n.dataset.i18n = key; n.textContent = tr(key, en, vars); return n; }
  function button(cls, key, en, onClick) {
    const b = keyed(node("button", cls), key, en);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }
  function say(box, text, kind) {
    box.textContent = text;
    box.className = "u-say" + (kind ? " " + kind : "");
  }
  async function call(path, body) {
    if (typeof api !== "function") return { ok: false, error: tr("ob.err_engine", "LOKI's engine is not answering.") };
    try { return await api(path, body); } catch (e) { return { ok: false, error: String(e) }; }
  }
  function openLinkSafe(url) {
    call("/open", { url }).then((r) => { if (!r || !r.ok) window.open(url, "_blank", "noopener"); });
  }

  async function save(change) { return call("/onboarding", change); }

  // ------------------------------------------------------------ frame
  function frame() {
    view.dlg = window.LokiDialog("u-onboarding", "ob.title", "Welcome to LOKI", {
      wide: true, modal: true, cls: "u-ob", focus: "h3.u-h",   // a screen reader starts at the step's title
      onClose: (why) => {
        clearInterval(view.timer);
        if (why !== "done") { try { localStorage.setItem("loki-onboarding-later", String(Date.now())); } catch (_) { /* no storage */ } }
      },
    });
    keyed(view.dlg.close, "ob.skip_all", "Skip the tour");
    return view.dlg;
  }

  function progress() {
    const p = node("div", "u-steps");
    p.setAttribute("role", "status");
    p.append(node("span", "u-steps-text", tr("ob.step_of", "Step {n} of {total}", { n: view.step + 1, total: STEPS })));
    const dots = node("span", "u-dots");
    dots.setAttribute("aria-hidden", "true");
    for (let i = 0; i < STEPS; i++) dots.append(node("i", i === view.step ? "on" : i < view.step ? "done" : ""));
    p.append(dots);
    return p;
  }

  function nav(nextKey, nextEn, onNext, opts) {
    opts = opts || {};
    const row = node("div", "u-nav");
    if (view.step > 0) row.append(button("quiet", "common.back", "Back", () => go(view.step - 1)));
    row.append(node("span", "u-grow"));
    if (opts.skip) row.append(button("quiet", opts.skipKey || "ob.skip_step", opts.skipEn || "Skip this step", opts.skip));
    const next = button("send u-next", nextKey, nextEn, onNext);
    row.append(next);
    return row;
  }

  function go(step) {
    clearInterval(view.timer);
    view.step = Math.max(0, Math.min(STEPS - 1, step));
    save({ step: view.step });
    const body = view.dlg.body;
    body.replaceChildren(progress());
    [stepWelcome, stepModel, stepInterests, stepTry][view.step](body);
    const h = body.querySelector("h3");
    if (h) { h.tabIndex = -1; h.focus(); }   // a screen reader hears the new step's title
  }

  // ------------------------------------------------------------ 1. welcome + language
  function stepWelcome(body) {
    body.append(keyed(node("h3", "u-h"), "ob.hello", "Hi, I'm LOKI - your helper on this computer"));
    const list = node("ul", "u-points");
    for (const [k, en] of [["ob.point1", "Ask me anything, in your own words: write a letter, plan a week, explain a bill, learn something new."],
      ["ob.point2", "I can also work on files on this computer - but I always ask before doing anything risky."],
      ["ob.point3", "I can run completely on this computer, private and free, or use a free online model."]]) list.append(keyed(node("li"), k, en));
    body.append(list);
    const h = keyed(node("h4", "u-sub"), "ob.pick_lang", "Choose your language");
    h.id = "u-ob-lang";
    body.append(h);
    const langs = node("div", "u-langs");
    langs.setAttribute("role", "radiogroup");
    langs.setAttribute("aria-labelledby", "u-ob-lang");
    const cur = window.LokiI18n ? window.LokiI18n.lang : "en";
    for (const [code, [name]] of Object.entries((window.LokiI18n && window.LokiI18n.languages) || { en: ["English"] })) {
      const b = node("button", "chip u-lang", name);
      b.type = "button";
      b.lang = code;
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(code === cur));
      b.tabIndex = code === cur ? 0 : -1;
      b.addEventListener("click", async () => {
        if (window.LokiI18n) await window.LokiI18n.choose(code);
        go(0);
        const again = view.dlg.body.querySelector('.u-lang[aria-checked="true"]');
        if (again) again.focus();
      });
      langs.append(b);
    }
    body.append(langs);
    if (cur !== "en") body.append(keyed(node("p", "note u-review"), "ob.machine_drafted", "This translation was drafted by a machine and is waiting for review by a native speaker."));
    // easier to see, right away
    const easy = node("div", "u-row");
    const a = window.LokiA11y ? window.LokiA11y.prefs : { font: "100", contrast: false };
    const bigger = button("quiet u-toggle", "ob.bigger", "Bigger text", () => {
      const steps = window.LokiA11y.FONT_STEPS;
      const next = steps[(steps.indexOf(String(window.LokiA11y.prefs.font)) + 1) % steps.length];
      window.LokiA11y.save({ font: next });
      bigger.setAttribute("aria-pressed", String(next !== "100"));
    });
    bigger.setAttribute("aria-pressed", String(String(a.font) !== "100"));
    const hc = button("quiet u-toggle", "ob.contrast", "High contrast", () => {
      const on = !window.LokiA11y.prefs.contrast;
      window.LokiA11y.save({ contrast: on });
      hc.setAttribute("aria-pressed", String(on));
    });
    hc.setAttribute("aria-pressed", String(!!a.contrast));
    easy.append(bigger, hc);
    body.append(easy, nav("ob.start", "Let's start", () => go(1)));
  }

  // ------------------------------------------------------------ 2. a model
  function working(setup) {
    const act = (setup && setup.active) || {};
    if (act.local) return act.local;
    if (setup && (setup.cloud_ready || []).length) return setup.cloud_ready[0];
    return view.connected || "";
  }

  async function stepModel(body) {
    body.append(keyed(node("h3", "u-h"), "ob.model_title", "Connect a free AI model"));
    body.append(keyed(node("p", "note"), "ob.model_why", "LOKI needs an AI model to think with. Both choices below are free. You can change it any time in Settings."));
    const status = node("p", "u-say");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    body.append(status);
    say(status, tr("ob.checking", "Looking at this computer…"));
    const setup = await call("/setup");
    if (view.step !== 1) return;
    view.setup = setup && setup.ok ? setup : null;
    const now = working(view.setup);
    if (now) say(status, tr("ob.connected", "Connected: LOKI is using {name}. You can go on, or pick another below.", { name: now }), "ok");
    else if (!view.setup) say(status, tr("ob.err_setup", "LOKI could not look at this computer's models (its engine did not answer). You can still connect a free online model below."), "bad");
    else say(status, tr("ob.none_yet", "No model is connected yet. Pick one:"));

    const choices = node("div", "u-choices");
    choices.append(localCard(view.setup, status), cloudCard(status));
    body.append(choices);
    let warned = false;
    const row = nav("common.next", "Next", () => {
      if (!working(view.setup) && !warned) {   // say it once, plainly; the next press goes on
        warned = true;
        say(status, tr("ob.no_model_warn", "LOKI cannot answer until a model is connected. You can do it later in Settings > Connections, or from the ? help."), "warn");
        keyed(row.querySelector(".u-next"), "ob.next_anyway", "Continue without a model");
        status.scrollIntoView({ block: "nearest" });
        return;
      }
      go(2);
    });
    body.append(row);
  }

  function localCard(setup, status) {
    const c = node("section", "u-choice");
    c.setAttribute("aria-labelledby", "u-ob-local");
    const h = keyed(node("h4", "u-sub"), "ob.local_title", "On this computer");
    h.id = "u-ob-local";
    c.append(h, keyed(node("p", "note"), "ob.local_why", "Private and free, works without internet. Needs a few GB of disk and a one-time download."));
    if (!setup) {
      c.append(keyed(node("p", "u-say bad"), "ob.local_unknown", "Could not check this computer. Try again, or use a free online model."));
      c.append(button("quiet", "common.retry", "Try again", () => go(1)));
      return c;
    }
    const sc = setup.scan || setup.hardware || {};
    const ol = setup.ollama || {};
    const found = [];
    if (ol.running) found.push(tr("ob.found_ollama_on", "Ollama is running"));
    else if (ol.installed || sc.ollama_installed) found.push(tr("ob.found_ollama_off", "Ollama is installed (LOKI will start it)"));
    if (sc.mlx && sc.mlx.installed) found.push(tr("ob.found_mlx", "MLX is installed (Apple Silicon)"));
    if (sc.llamacpp && sc.llamacpp.installed) found.push("llama.cpp");
    c.append(node("p", "u-found", found.length ? found.join(" · ") : tr("ob.found_none", "No local model app yet - LOKI installs Ollama for you (free, open source).")));
    const auto = setup.auto || {};
    const p = node("p", "u-say");
    p.setAttribute("aria-live", "polite");
    if (setup.active && setup.active.local) {
      c.append(node("p", "u-say ok", tr("ob.local_using", "In use: {name}", { name: setup.active.local })));
      return c;
    }
    if (!auto.tag) {
      c.append(node("p", "u-say warn", tr("ob.local_no_fit", "No local model fits this computer well ({why}). A free online model is the better choice here.",
        { why: auto.error || tr("ob.local_small", "not enough memory or disk") })));
      return c;
    }
    const size = (Number(auto.size_gb) || 0).toFixed(1);
    const go1 = node("button", "send u-big");
    go1.type = "button";
    go1.textContent = auto.installed ? tr("ob.local_use", "Use {model} (already downloaded)", { model: auto.tag })
      : tr("ob.local_install", "Set it up for me ({model}, {size} GB download)", { model: auto.tag, size });
    go1.addEventListener("click", async () => {
      go1.disabled = true;
      say(p, tr("ob.local_starting", "Starting… you can keep reading; this runs in the background."));
      const r = await call("/setup/auto", {});
      if (!r.ok) {
        go1.disabled = false;
        say(p, tr("ob.local_failed", "That did not start: {error}. Try again, install Ollama yourself from ollama.com/download, or use a free online model.", { error: r.error || "?" }), "bad");
        return;
      }
      save({ model_choice: "local" });
      watch(p, go1, status);
    });
    const bar = node("div", "bar u-bar");
    bar.hidden = true;
    bar.append(node("i"));
    c.append(go1, bar, p);
    if (!ol.installed && !ol.running) {
      const help = button("link u-link", "ob.install_ollama_help", "How to install Ollama by hand", () => openLinkSafe("https://ollama.com/download"));
      c.append(help);
    }
    c.append(button("link u-link", "ob.more_choices", "More choices (pick a model yourself)", () => {
      view.dlg.hide("more");
      if (typeof openSetup === "function") openSetup(true);
    }));
    return c;
  }

  function watch(p, btn, status) {
    const bar = btn.parentNode.querySelector(".u-bar");
    if (bar) bar.hidden = false;
    clearInterval(view.timer);
    view.timer = setInterval(async () => {
      const r = await call("/setup/progress");
      if (!r || !r.ok) return;
      const pr = r.progress || {};
      if (bar) bar.firstChild.style.width = (pr.done ? 100 : pr.percent || 0) + "%";
      say(p, (pr.message || pr.status || tr("ob.working", "Working…")) + (pr.total && !pr.done ? " · " + pr.percent + "%" : ""));
      if (pr.done) {
        clearInterval(view.timer);
        if (pr.status === "failed") {
          btn.disabled = false;
          say(p, tr("ob.local_failed", "That did not work: {error}. Try again, install Ollama yourself from ollama.com/download, or use a free online model.",
            { error: pr.message || "?" }), "bad");
        } else {
          say(p, tr("ob.local_done", "Done - LOKI now runs on this computer."), "ok");
          view.connected = pr.target || "local";
          say(status, tr("ob.connected", "Connected: LOKI is using {name}. You can go on, or pick another below.", { name: view.connected }), "ok");
          if (typeof loadModels === "function") loadModels();
        }
      }
    }, 1000);
  }

  function cloudCard(status) {
    const c = node("section", "u-choice");
    c.setAttribute("aria-labelledby", "u-ob-cloud");
    const h = keyed(node("h4", "u-sub"), "ob.cloud_title", "A free online model");
    h.id = "u-ob-cloud";
    c.append(h, keyed(node("p", "note"), "ob.cloud_why", "Fast on any computer. Needs internet and a free account; what you ask is sent to that service."));
    for (const [id, name, how, signup, keys, hint] of CLOUD) {
      const row = node("div", "u-cloud");
      const head = node("div", "u-cloud-head");
      head.append(node("b", "", name), node("span", "u-badge", tr("ob.free", "Free")));
      row.append(head);
      const out = node("p", "u-say");
      out.setAttribute("aria-live", "polite");
      if (how === "oauth") {
        row.append(keyed(node("p", "note"), "ob.or_how", "Sign in (or make a free account) in your browser and approve LOKI - no key to copy."));
        const b = node("button", "send");
        b.type = "button";
        b.textContent = tr("ob.signin", "Sign in with {name}", { name });
        b.addEventListener("click", async () => {
          b.disabled = true;
          say(out, tr("ob.opening", "Opening {name} in your browser…", { name }));
          const r = await call("/signin/openrouter", { mode: "browser" });
          if (!r.ok) { b.disabled = false; say(out, tr("ob.signin_failed", "Could not start the sign-in: {error}. Check the internet connection and try again, or use another option.", { error: r.error || "?" }), "bad"); return; }
          say(out, tr("ob.approve", "Approve LOKI in the browser tab that opened. Waiting…"));
          const started = Date.now();
          const timer = setInterval(async () => {
            const s = await call("/signin/status?state=" + encodeURIComponent(r.state));
            const late = Date.now() - started > 600000;
            if (!s || !s.ok || late) { clearInterval(timer); b.disabled = false; say(out, tr("ob.expired", "This sign-in expired. Press the button to try again."), "bad"); return; }
            if (s.done) {
              clearInterval(timer);
              b.disabled = false;
              const res = s.result || {};
              if (res.ok) connected(out, status, name, id);
              else say(out, tr("ob.signin_failed", "Could not sign in: {error}. Try again, or use another option.", { error: res.error || "?" }), "bad");
            }
          }, 2000);
        });
        row.append(b);
      } else {
        const steps = node("ol", "u-howto");
        const s1 = node("li");
        const link = node("button", "link u-link", tr("ob.open_signup", "Open {name} (free sign-up)", { name }));
        link.type = "button";
        link.addEventListener("click", () => openLinkSafe(keys || signup));
        s1.append(link);
        steps.append(s1, node("li", "", tr("ob.make_key", "Create an API key there and copy it.")),
          node("li", "", tr("ob.paste_key", "Paste it here - it stays on this computer.")));
        row.append(steps);
        const form = node("form", "u-keyform");
        const input = node("input", "u-input");
        input.type = "password";
        input.autocomplete = "off";
        input.placeholder = hint + "…";
        input.setAttribute("aria-label", tr("ob.key_for", "{name} key", { name }));
        const go2 = node("button", "send", tr("ob.connect", "Connect"));
        go2.type = "submit";
        form.append(input, go2);
        form.addEventListener("submit", async (e) => {
          e.preventDefault();
          const key = input.value.trim();
          if (!key) { say(out, tr("ob.key_empty", "Paste the key first (copy it from the {name} page).", { name }), "warn"); input.focus(); return; }
          go2.disabled = true;
          say(out, tr("ob.checking_key", "Checking the key…"));
          const r = await call("/providers/connect", { id, key });
          go2.disabled = false;
          if (r.ok) { input.value = ""; connected(out, status, name, id); return; }
          const wrong = hint && !key.startsWith(hint);
          say(out, tr("ob.key_failed", "That key did not work: {error}.", { error: r.error || "?" }) + " "
            + (wrong ? tr("ob.key_hint", "{name} keys start with {hint} - check you copied all of it.", { name, hint }) : tr("ob.key_retry", "Copy it again (all of it) and paste it, or make a new key.")), "bad");
        });
        row.append(form);
      }
      row.append(out);
      c.append(row);
    }
    return c;
  }

  function connected(out, status, name, id) {
    view.connected = name;
    save({ model_choice: id });
    say(out, tr("ob.cloud_ok", "Connected to {name}.", { name }), "ok");
    say(status, tr("ob.connected", "Connected: LOKI is using {name}. You can go on, or pick another below.", { name }), "ok");
    if (typeof loadModels === "function") loadModels();
  }

  // ------------------------------------------------------------ 3. interests
  function stepInterests(body) {
    body.append(keyed(node("h3", "u-h"), "ob.help_title", "What would you like help with?"));
    body.append(keyed(node("p", "note"), "ob.help_why", "Pick as many as you like. LOKI shows you matching examples first; it can still help with anything."));
    const grid = node("div", "u-interests");
    grid.setAttribute("role", "group");
    grid.setAttribute("aria-label", tr("ob.help_title", "What would you like help with?"));
    for (const [id, en, mark] of INTERESTS) {
      const b = node("button", "u-interest");
      b.type = "button";
      b.setAttribute("aria-pressed", String(view.interests.includes(id)));
      b.append(node("span", "u-mark", mark), node("span", "", tr("cat." + id, en)));
      b.querySelector(".u-mark").setAttribute("aria-hidden", "true");
      b.addEventListener("click", () => {
        const on = !view.interests.includes(id);
        view.interests = on ? view.interests.concat(id) : view.interests.filter((x) => x !== id);
        b.setAttribute("aria-pressed", String(on));
      });
      grid.append(b);
    }
    body.append(grid, nav("common.next", "Next", async () => {
      const r = await save({ interests: view.interests });
      if (r && r.ok === false) { body.append(node("p", "u-say warn", r.error)); }
      go(3);
    }, { skip: () => go(3) }));
  }

  // ------------------------------------------------------------ 4. try it
  function stepTry(body) {
    body.append(keyed(node("h3", "u-h"), "ob.try_title", "Try it: pick one"));
    body.append(keyed(node("p", "note"), "ob.try_why", "Each one runs in a new chat and changes nothing on your computer."));
    if (!working(view.setup)) body.append(node("p", "u-say warn", tr("ob.try_no_model", "No model is connected yet, so LOKI cannot answer. Go Back one step to connect a free one.")));
    const grid = node("div", "u-try");
    const G = window.LokiGallery;
    for (const id of (G ? G.pickFor(view.interests, 3) : [])) {
      const t = G.task(id);
      const b = node("button", "u-task");
      b.type = "button";
      b.append(node("span", "u-task-cat", tr("cat." + t.category, t.category)), node("b", "u-task-title", t.title),
        node("span", "u-task-prompt", tr("task." + id + ".prompt", "")), node("span", "u-run", tr("gallery.run", "Run it")));
      b.addEventListener("click", async () => { await finish(); G.run(id); });
      grid.append(b);
    }
    body.append(grid);
    const row = node("div", "u-nav");
    row.append(button("quiet", "common.back", "Back", () => go(2)), node("span", "u-grow"),
      button("quiet", "ob.open_gallery", "See all 32 examples", async () => { await finish(); if (G) G.open(); }),
      button("send u-next", "ob.finish", "Start chatting", async () => { await finish(); if (typeof summon === "function") summon(true); }));
    body.append(row);
  }

  async function finish() {
    clearInterval(view.timer);
    await save({ done: true });
    try { localStorage.setItem("loki-onboarded", "1"); } catch (_) { /* no storage */ }
    view.dlg.hide("done");
  }

  // ------------------------------------------------------------ start
  async function open(force) {
    if (!window.LokiDialog) return false;
    if (window.LokiI18n) await window.LokiI18n.ready;   // the tour opens in the user's language
    frame();
    const st = await call("/onboarding");
    view.data = st && st.ok ? st : {};
    view.interests = (view.data.interests || []).slice();
    view.dlg.open();
    go(force ? 0 : Math.min(view.data.step || 0, STEPS - 1));
    return true;
  }

  // Called once the engine answers (setup.js afterStart). true = the welcome is showing.
  async function start() {
    const st = await call("/onboarding");
    if (!st || !st.ok || st.done !== false) return false;   // only an engine that knows the tour says done:false
    let later = "";
    try { later = localStorage.getItem("loki-onboarding-later") || ""; } catch (_) { /* no storage */ }
    if (later && Date.now() - Number(later) < 3 * 86400000) return false;   // "skip": ask again in 3 days
    // someone who already uses LOKI: a model works and there are chats -> never shown
    const setup = await call("/setup");
    const hasChats = typeof state === "object" && state && (state.conversations || []).some((c) => (c.title || "") && !/^new chat$/i.test(c.title));
    if (setup && setup.ok && working(setup) && hasChats) { await save({ done: true }); return false; }
    view.setup = setup && setup.ok ? setup : null;
    return open(false);
  }

  window.Onboarding = { start, open, steps: STEPS, interests: INTERESTS };
})();
