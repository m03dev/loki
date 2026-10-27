// First run for anyone (session 29): a friendly 4-step welcome.
//   1. What LOKI is + pick a language (and bigger text / high contrast right there)
//   2. How LOKI thinks (session 30): "Run AI on this computer" (hardware detected, a quick model
//      that fits, Ollama installed silently, downloaded IN THE BACKGROUND with progress that outlives
//      the tour), "Connect an account" (OpenRouter one click; NVIDIA NIM - DeepSeek V4.1 Flash, LOKI's
//      main driver; Groq / Gemini removed 2026-10-27 for their daily caps) or "Both" (chat online while the local model downloads)
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
    // [id, name, how, sign-up page, key page, key hint, note key, note]
    ["openrouter", "OpenRouter", "oauth", "https://openrouter.ai", "https://openrouter.ai/keys", "sk-or-"],
    ["nvidia", "NVIDIA NIM", "key", "https://build.nvidia.com", "https://build.nvidia.com/settings/api-keys", "nvapi-",
      "ob.nvidia_why", "DeepSeek V4.1 Flash, free - LOKI's main driver: fast, smart, calls tools."],
  ];
  const view = { dlg: null, step: 0, data: null, setup: null, interests: [], timer: 0, connected: "", way: "" };

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

  // ------------------------------------------------------------ 2. a model (session 30: three ways)
  // "Run AI on this computer" (free, private: a model that fits, Ollama installed silently, the
  // download in the BACKGROUND - LokiBgSetup below keeps going after the tour closes), "Connect an
  // account" (OpenRouter one click, an NVIDIA NIM key), or "Both" (chat online at once
  // while the local model downloads). Nothing blocks; every step can be skipped.
  function working(setup) {
    const act = (setup && setup.active) || {};
    if (act.local) return act.local;
    if (setup && (setup.cloud_ready || []).length) return setup.cloud_ready[0];
    return view.connected || "";
  }

  function pickFor(setup) {
    // the tour's first model is a QUICK one (model_setup.quick_pick: Bonsai 2 9B/4B or a small qwen);
    // the best-fitting bigger one is offered later as an upgrade
    const q = (setup && setup.quick) || null;
    const a = (setup && setup.auto) || {};
    if (q && q.tag) return { tag: q.tag, size: Number(q.size_gb) || 0, installed: !!q.installed, quick: true, upgrade: q.upgrade || "" };
    if (a.tag) return { tag: a.tag, size: Number(a.size_gb) || 0, installed: !!a.installed, quick: false, upgrade: "" };
    return null;
  }

  function machineLine(setup) {
    const hw = (setup && setup.hardware) || {};
    const bits = [];
    if (hw.ram_gb) bits.push(tr("ob.hw_ram", "{gb} GB memory", { gb: Math.round(hw.ram_gb) }));
    if (hw.gpu) bits.push(hw.gpu);
    else if (hw.chip) bits.push(hw.chip);
    const sc = (setup && setup.scan) || {};
    if (sc.disk_free_gb !== undefined && sc.disk_free_gb !== null) bits.push(tr("ob.hw_disk", "{gb} GB free disk", { gb: Math.round(sc.disk_free_gb) }));
    return bits.length ? tr("ob.hw", "This computer: {what}", { what: bits.join(" · ") }) : "";
  }

  async function stepModel(body) {
    body.append(keyed(node("h3", "u-h"), "ob.model_title2", "How should LOKI think?"));
    body.append(keyed(node("p", "note"), "ob.model_why2", "Pick one - or both. Nothing here makes you wait: downloads run in the background and you can change it any time in Settings."));
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
    else if (window.LokiBgSetup && window.LokiBgSetup.busy()) say(status, tr("ob.bg_running", "A model is downloading in the background - you can go on."));
    else status.textContent = "";

    const pick = pickFor(view.setup);
    const ways = node("div", "u-ways");
    ways.setAttribute("role", "radiogroup");
    ways.setAttribute("aria-label", tr("ob.model_title2", "How should LOKI think?"));
    const panels = node("div", "u-choices");
    const localWhat = !view.setup ? tr("ob.way_local_unknown", "Could not check this computer")
      : pick ? (pick.installed ? tr("ob.way_local_have", "{model} is already downloaded", { model: pick.tag })
        : tr("ob.way_local_dl", "{model} · {size} GB download, in the background", { model: shortName(pick.tag), size: pick.size.toFixed(1) }))
        : tr("ob.way_local_nofit", "No local model fits this computer well");
    const WAYS = [
      ["local", "ob.way_local", "Run AI on this computer", "ob.way_local_sub", "Free and private. Works offline once it is downloaded.", localWhat],
      ["cloud", "ob.way_cloud", "Connect an account", "ob.way_cloud_sub", "Fast on any computer. Free: NVIDIA (DeepSeek V4.1 Flash, Nemotron). Paid: OpenRouter.", ""],
      ["both", "ob.way_both", "Both", "ob.way_both_sub", "Chat online right away while the local model downloads.", ""],
    ];
    const show = (way) => {
      view.way = way;
      for (const b of ways.children) {
        const on = b.dataset.way === way;
        b.setAttribute("aria-checked", String(on));
        b.tabIndex = on || (!way && b.dataset.way === "local") ? 0 : -1;
      }
      panels.replaceChildren();
      if (way === "local" || way === "both") panels.append(localCard(view.setup, status, way));
      if (way === "cloud" || way === "both") panels.append(cloudCard(status));
      panels.classList.toggle("u-one", way !== "both");
    };
    for (const [id, key, en, subKey, subEn, extra] of WAYS) {
      const b = node("button", "u-way");
      b.type = "button";
      b.dataset.way = id;
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", "false");
      b.append(keyed(node("b", "u-way-title"), key, en), keyed(node("span", "u-way-sub"), subKey, subEn));
      if (extra) b.append(node("span", "u-way-extra", extra));
      if (id !== "cloud" && view.setup && !pick) b.classList.add("u-way-dim");
      b.addEventListener("click", () => {
        show(id);
        save({ model_way: id });
        if ((id === "local" || id === "both") && pick && !pick.installed && !(window.LokiBgSetup && window.LokiBgSetup.busy())) {
          startLocal(status);   // the choice IS the one click: the download starts in the background
        } else if ((id === "local" || id === "both") && pick && pick.installed && !working(view.setup)) {
          startLocal(status);   // downloaded already: just switch to it
        }
      });
      ways.append(b);
    }
    body.append(ways, panels);
    if (view.way) show(view.way);
    else ways.firstChild.tabIndex = 0;
    let warned = false;
    const row = nav("common.next", "Next", () => {
      const pending = window.LokiBgSetup && window.LokiBgSetup.busy();
      if (!working(view.setup) && !pending && !warned) {   // say it once, plainly; the next press goes on
        warned = true;
        say(status, tr("ob.no_model_warn", "LOKI cannot answer until a model is connected. You can do it later in Settings > Connections, or from the ? help."), "warn");
        keyed(row.querySelector(".u-next"), "ob.next_anyway", "Continue without a model");
        status.scrollIntoView({ block: "nearest" });
        return;
      }
      go(2);
    }, { skip: () => go(2) });
    body.append(row);
  }

  function shortName(tag) {
    const t = String(tag || "");
    const m = t.match(/Ternary-Bonsai-2-(\d+B)/i);
    if (m) return "Bonsai 2 " + m[1];
    return t.replace(/^hf\.co\/[^:]+:/, "");
  }

  async function startLocal(status, again) {
    const r = await call("/setup/auto", { quick: true });
    if (!r || !r.ok) {
      if (r && /busy|already/i.test(r.error || "") && window.LokiBgSetup) { window.LokiBgSetup.track(); return; }
      say(status, tr("ob.local_failed", "That did not start: {error}. Try again, install Ollama yourself from ollama.com/download, or use a free online model.", { error: (r && r.error) || "?" }), "bad");
      return;
    }
    save({ model_choice: "local" });
    if (window.LokiBgSetup) window.LokiBgSetup.track({ onDone: (pr) => {
      if (pr.status !== "failed") {
        view.connected = pr.target || "local";
        if (view.dlg && view.step === 1) say(status, tr("ob.local_done", "Done - LOKI now runs on this computer."), "ok");
        if (typeof loadModels === "function") loadModels();
      }
    } });
    if (!again && view.dlg && view.step === 1) {
      say(status, tr("ob.bg_started", "Downloading in the background - you can go on (it keeps going after this tour). Want to chat now? Connect an account too."));
    }
  }

  function localCard(setup, status, way) {
    const c = node("section", "u-choice");
    c.setAttribute("aria-labelledby", "u-ob-local");
    const h = keyed(node("h4", "u-sub"), "ob.local_title", "On this computer");
    h.id = "u-ob-local";
    c.append(h);
    if (!setup) {
      c.append(keyed(node("p", "u-say bad"), "ob.local_unknown", "Could not check this computer. Try again, or use a free online model."));
      c.append(button("quiet", "common.retry", "Try again", () => go(1)));
      return c;
    }
    const line = machineLine(setup);
    if (line) c.append(node("p", "u-found", line));
    const sc = setup.scan || setup.hardware || {};
    const ol = setup.ollama || {};
    const found = [];
    if (ol.running) found.push(tr("ob.found_ollama_on", "Ollama is running"));
    else if (ol.installed || sc.ollama_installed) found.push(tr("ob.found_ollama_off", "Ollama is installed (LOKI will start it)"));
    if (sc.mlx && sc.mlx.installed) found.push(tr("ob.found_mlx", "MLX is installed (Apple Silicon)"));
    c.append(node("p", "note", found.length ? found.join(" · ") : tr("ob.found_none2", "LOKI installs Ollama for you (free, open source) - quietly, no setup windows.")));
    if (setup.active && setup.active.local) {
      c.append(node("p", "u-say ok", tr("ob.local_using", "In use: {name}", { name: setup.active.local })));
      return c;
    }
    const pick = pickFor(setup);
    if (!pick) {
      c.append(node("p", "u-say warn", tr("ob.local_no_fit", "No local model fits this computer well ({why}). A free online model is the better choice here.",
        { why: (setup.auto && setup.auto.error) || tr("ob.local_small", "not enough memory or disk") })));
      return c;
    }
    c.append(node("p", "u-say", pick.installed ? tr("ob.local_ready", "Ready: {model} is on this computer.", { model: shortName(pick.tag) })
      : tr("ob.local_reco", "Recommended for this computer: {model} ({size} GB). It downloads in the background - you can keep going.",
        { model: shortName(pick.tag), size: pick.size.toFixed(1) })));
    if (pick.upgrade) c.append(node("p", "note", tr("ob.local_upgrade", "A bigger, smarter model ({model}) also fits: Settings > Local models, later.", { model: shortName(pick.upgrade) })));
    const busy = window.LokiBgSetup && window.LokiBgSetup.busy();
    const b = node("button", "send u-big");
    b.type = "button";
    b.textContent = busy ? tr("ob.local_busy", "Downloading… (see the progress at the bottom right)")
      : pick.installed ? tr("ob.local_use", "Use {model} (already downloaded)", { model: shortName(pick.tag) })
        : tr("ob.local_install", "Set it up for me ({model}, {size} GB download)", { model: shortName(pick.tag), size: pick.size.toFixed(1) });
    b.disabled = !!busy;
    b.addEventListener("click", () => { b.disabled = true; startLocal(status); });
    c.append(b);
    if (way === "local") c.append(keyed(node("p", "note"), "ob.local_meanwhile", "Tip: choose Both to chat online while it downloads."));
    if (!ol.installed && !ol.running) c.append(button("link u-link", "ob.install_ollama_help", "How to install Ollama by hand", () => openLinkSafe("https://ollama.com/download")));
    if (setup.picks && setup.picks.mlx) c.append(node("p", "note", tr("ob.mlx_note", "MLX is installed: {repo} also runs on this Mac (Settings > Local models).", { repo: setup.picks.mlx.repo })));
    c.append(button("link u-link", "ob.more_choices", "More choices (pick a model yourself)", () => {
      view.dlg.hide("more");
      if (typeof openSetup === "function") openSetup(true);
    }));
    return c;
  }

  function cloudCard(status) {
    const c = node("section", "u-choice");
    c.setAttribute("aria-labelledby", "u-ob-cloud");
    const h = keyed(node("h4", "u-sub"), "ob.cloud_title2", "Connect an account");
    h.id = "u-ob-cloud";
    c.append(h, keyed(node("p", "note"), "ob.cloud_why", "Fast on any computer. Needs internet and a free account; what you ask is sent to that service."));
    for (const [id, name, how, signup, keys, hint, extraKey, extraEn] of CLOUD) {
      const row = node("div", "u-cloud");
      const head = node("div", "u-cloud-head");
      head.append(node("b", "", name), node("span", "u-badge", tr("ob.free", "Free")));
      row.append(head);
      if (extraKey) row.append(keyed(node("p", "note"), extraKey, extraEn));
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
    view.way = view.way || view.data.model_way || "";
    view.dlg.open();
    go(force ? 0 : Math.min(view.data.step || 0, STEPS - 1));
    return true;
  }

  // Called once the engine answers (setup.js afterStart). true = the welcome is showing.
  async function start() {
    bgResume();   // a local model still downloading from before: show its progress again
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

  // ------------------------------------------------------------ the background download (session 30)
  // A small progress card at the bottom right while the local model (and Ollama) install: it keeps
  // going after the tour closes, never blocks the window, and when something fails it offers
  // choices (try again / install Ollama by hand / use an online model) instead of a dead end.
  const bg = { el: null, timer: 0, busy: false, hooks: [], hideTimer: 0 };

  function bgEl() {
    if (bg.el && document.body.contains(bg.el)) return bg.el;
    const el = node("div", "u-bgsetup");
    el.id = "u-bgsetup";
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    el.hidden = true;
    const text = node("p", "u-bg-text");
    const bar = node("div", "bar u-bar");
    bar.append(node("i"));
    const acts = node("div", "u-bg-acts");
    el.append(text, bar, acts);
    document.body.append(el);
    bg.el = el;
    return el;
  }

  function bgShow(message, percent, actions, kind) {
    const el = bgEl();
    clearTimeout(bg.hideTimer);
    el.hidden = false;
    el.className = "u-bgsetup" + (kind ? " " + kind : "");
    el.querySelector(".u-bg-text").textContent = message;
    const bar = el.querySelector(".u-bar");
    bar.hidden = percent === null;
    if (percent !== null) bar.firstChild.style.width = Math.max(2, Math.min(100, percent)) + "%";
    const acts = el.querySelector(".u-bg-acts");
    acts.replaceChildren();
    for (const [key, en, fn] of actions || []) acts.append(button("quiet u-bg-btn", key, en, fn));
  }

  function bgTrack(opts) {
    if (opts && opts.onDone) bg.hooks.push(opts.onDone);
    bg.busy = true;
    clearInterval(bg.timer);
    bgShow(tr("ob.bg_starting", "Setting up the local model…"), 0, [["ob.bg_hide", "Hide", () => { bgEl().hidden = true; }]]);
    const tick = async () => {
      const r = await call("/setup/progress");
      if (!r || !r.ok) return;
      const pr = r.progress || {};
      if (!pr.done) {
        const pct = pr.total ? Number(pr.percent) || 0 : null;
        bgShow((pr.message || pr.status || tr("ob.working", "Working…")) + (pct !== null ? " · " + Math.round(pct) + "%" : ""),
          pct === null ? 5 : pct, [["ob.bg_hide", "Hide", () => { bgEl().hidden = true; }]]);
        return;
      }
      clearInterval(bg.timer);
      bg.busy = false;
      const hooks = bg.hooks.splice(0);
      for (const h of hooks) { try { h(pr); } catch (_) { /* a closed tour */ } }
      if (pr.status === "failed" || pr.status === "manual") {
        bgShow(tr("ob.bg_failed", "The local model did not install: {error}", { error: pr.message || pr.error || "?" }), null, [
          ["common.retry", "Try again", async () => { const again = await call("/setup/auto", { quick: true }); if (again && again.ok) bgTrack(); }],
          ["ob.bg_byhand", "Install Ollama by hand", () => openLinkSafe("https://ollama.com/download")],
          ["ob.bg_online", "Use an online model", () => { bgEl().hidden = true; view.way = "cloud"; open(false).then(() => go(1)); }],
          ["ob.bg_close", "Close", () => { bgEl().hidden = true; }],
        ], "bad");
      } else {
        bgShow(tr("ob.bg_done", "LOKI now runs on this computer - private, free, offline."), 100, [["ob.bg_close", "Close", () => { bgEl().hidden = true; }]], "ok");
        if (typeof loadModels === "function") loadModels();
        bg.hideTimer = setTimeout(() => { bgEl().hidden = true; }, 12000);
      }
    };
    bg.timer = setInterval(tick, 1500);
    tick();
  }

  async function bgResume() {   // the window was reopened while a download runs: show it again
    const r = await call("/setup/progress");
    const pr = (r && r.progress) || {};
    if (r && r.ok && pr.op && !pr.done) bgTrack();
  }

  window.LokiBgSetup = { track: bgTrack, busy: () => bg.busy, resume: bgResume };

  window.Onboarding = { start, open, steps: STEPS, interests: INTERESTS };
})();
