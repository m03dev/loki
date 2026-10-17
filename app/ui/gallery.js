// "What can LOKI do?" and the help center (session 29).
//
// The gallery: 32 example tasks in 8 categories. One click runs one in a new chat (Ask mode, so
// nothing on the computer changes) and the answer shows up right there. Their words are in the
// i18n tables (task.<id>.title / task.<id>.prompt), so they run in the user's language.
// Health tasks carry a safety note, on the card and in what LOKI is asked.
//
// The help center: searchable articles from docs/help/ (GET /help), opened with the "?" icon
// in the top bar or F1, rendered with app.js's escaping Markdown renderer.
"use strict";

(function () {
  const CATEGORIES = [
    ["everyday", "Everyday life"], ["work", "Work"], ["study", "Study"], ["creative", "Creative"],
    ["home", "Home"], ["money", "Money"], ["health", "Health info"], ["business", "Small business"],
  ];
  // [id, category, English title, English prompt]. The English is the fallback; i18n tables translate.
  const TASKS = [
    ["meal_plan", "everyday", "Weekly meal plan", "Make a simple 7-day dinner plan for two people on a budget, with a shopping list grouped by aisle."],
    ["polite_message", "everyday", "A polite message", "Write a short, friendly message to my neighbour asking them to keep the noise down after 10 pm."],
    ["packing_list", "everyday", "Packing list", "Make a packing list for a 4-day city trip with rainy weather."],
    ["explain_simply", "everyday", "Explain it simply", "Explain how a credit score works in simple words, in under 150 words."],
    ["email_reply", "work", "Professional email", "Write a short professional email asking my manager to move our Friday meeting to Monday morning."],
    ["meeting_agenda", "work", "Meeting agenda", "Make a 30-minute agenda for a team kickoff meeting for a new website project, with times."],
    ["prioritize", "work", "Prioritise my tasks", "Put these tasks in order, with one reason each: answer emails, finish the budget report due tomorrow, book travel, review a colleague's document, plan next quarter."],
    ["cv_lines", "work", "Stronger CV lines", "Rewrite these CV lines so they sound stronger and show results: 'Helped customers.' 'Did social media.' 'Worked on the website.'"],
    ["study_plan", "study", "Study plan", "Make a 2-week study plan to prepare for a beginner Spanish exam, 30 minutes a day."],
    ["quiz_me", "study", "Quiz me", "Give me 5 multiple-choice questions about the solar system, with the answers at the end."],
    ["explain_concept", "study", "Explain a concept", "Explain photosynthesis step by step, with a simple everyday example."],
    ["essay_outline", "study", "Essay outline", "Make an outline for a 1,000-word essay on whether social media is good for teenagers, with arguments for and against."],
    ["bedtime_story", "creative", "Bedtime story", "Write a 200-word bedtime story about a fox who is afraid of the dark."],
    ["card_poem", "creative", "Poem for a card", "Write a warm 8-line poem for my grandmother's 80th birthday card."],
    ["name_ideas", "creative", "Name ideas", "Give me 10 name ideas for a cosy neighbourhood bakery, with one line about each."],
    ["drawing_ideas", "creative", "Drawing ideas", "Suggest 3 things a beginner could draw this weekend, with simple steps for one of them."],
    ["cleaning", "home", "Cleaning schedule", "Make a simple weekly cleaning schedule for a 2-bedroom flat, 20 minutes a day."],
    ["dripping_tap", "home", "Fix a dripping tap", "My kitchen tap is dripping. Explain the usual causes, the safe steps to fix it, and when to call a plumber."],
    ["basil", "home", "Keep a plant alive", "How do I keep a basil plant alive on a windowsill? Short, practical tips."],
    ["moving", "home", "Moving checklist", "Make a checklist for moving house, from 4 weeks before to moving day."],
    ["budget", "money", "Monthly budget", "Help me make a simple monthly budget: income 2,500, rent 900, bills 250, food 400. Suggest how to split the rest, including savings."],
    ["groceries", "money", "Spend less on food", "Give me 10 realistic ways to spend less on groceries each month."],
    ["rent_or_buy", "money", "Compare two choices", "Compare renting and buying a car for someone who drives 8,000 km a year: pros, cons and a simple cost table."],
    ["money_words", "money", "Money words explained", "Explain these in plain words: interest rate, inflation, index fund, emergency fund."],
    ["sleep", "health", "Sleep better", "Give me evidence-based tips for falling asleep more easily."],
    ["stretching", "health", "Gentle stretching", "Make a gentle 15-minute daily stretching routine for someone who sits at a desk all day."],
    ["doctor_questions", "health", "Questions for my doctor", "Help me prepare questions to ask my doctor at a check-up about frequent headaches."],
    ["healthy_lunch", "health", "Healthy lunch ideas", "Give me 7 quick, healthy lunch ideas that take 10 minutes to prepare."],
    ["product_text", "business", "Product description", "Write a short product description for handmade lavender soy candles, for an online shop."],
    ["social_posts", "business", "Social media posts", "Write 5 short social media posts for a small coffee shop announcing its new autumn menu."],
    ["customer_reply", "business", "Reply to a customer", "Write a calm, kind reply to a customer whose order arrived late, offering a 10% discount."],
    ["business_plan", "business", "One-page business plan", "Make a one-page business plan outline for a dog-walking business: customers, prices, costs and first steps."],
  ];
  const SAFETY_EN = "General information only, not medical advice. For symptoms that are severe, sudden or worrying, contact a doctor or your local emergency number.";
  const SAFETY_PROMPT_EN = "This is general health information, not a diagnosis: keep it safe, and end with when to see a doctor.";

  const tr = (key, en, vars) => (window.LokiI18n ? window.LokiI18n.t(key, en, vars) : en);
  function node(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function keyed(n, key, en) { n.dataset.i18n = key; n.textContent = tr(key, en); return n; }

  function task(id) {
    const t = TASKS.find((x) => x[0] === id);
    if (!t) return null;
    const [tid, cat, title, prompt] = t;
    const health = cat === "health";
    let text = tr("task." + tid + ".prompt", prompt);
    if (health) text += " " + tr("gallery.safety_prompt", SAFETY_PROMPT_EN);
    return { id: tid, category: cat, title: tr("task." + tid + ".title", title), prompt: text, health };
  }

  // Run one example: a new chat in Ask mode (answers only, nothing on the computer changes).
  async function run(id) {
    const t = task(id);
    if (!t) return false;
    if (gallery && gallery.isOpen) gallery.hide("run");
    if (typeof api === "function") {
      const m = await api("/mode", { mode: "ask" }).catch(() => null);
      if (m && m.ok && typeof markMode === "function") markMode(m.mode);
    }
    if (typeof showHome === "function") showHome();
    if (typeof send === "function") await send(t.prompt, { direct: true });
    return true;
  }

  // ------------------------------------------------------------ gallery
  let gallery = null;
  let filter = "all";

  function pickFor(interests, n) {
    const out = [];
    const cats = (interests && interests.length ? interests : ["everyday", "work", "creative"]).slice();
    for (const c of ["everyday", "work", "creative", "study"]) if (!cats.includes(c)) cats.push(c);
    for (const c of cats) {
      const t = TASKS.find((x) => x[1] === c && !out.includes(x[0]));
      if (t) out.push(t[0]);
      if (out.length >= n) break;
    }
    return out;
  }

  function card(id) {
    const t = task(id);
    const b = node("button", "u-task" + (t.health ? " u-health" : ""));
    b.type = "button";
    b.dataset.task = id;
    b.append(node("span", "u-task-cat", catName(t.category)), node("b", "u-task-title", t.title),
      node("span", "u-task-prompt", tr("task." + id + ".prompt", TASKS.find((x) => x[0] === id)[3])));
    if (t.health) {
      const note = node("span", "u-safety");
      note.append(node("span", "u-safety-mark", "!"), document.createTextNode(" " + tr("gallery.safety", SAFETY_EN)));
      b.append(note);
    }
    b.append(node("span", "u-run", tr("gallery.run", "Run it")));
    b.setAttribute("aria-label", tr("gallery.run_aria", "Run: {title}", { title: t.title }));
    b.addEventListener("click", () => run(id));
    return b;
  }

  function catName(cat) { const c = CATEGORIES.find((x) => x[0] === cat); return tr("cat." + cat, c ? c[1] : cat); }

  function renderGallery() {
    const body = gallery.body;
    body.replaceChildren();
    body.append(keyed(node("p", "note"), "gallery.intro", "Pick an example and LOKI does it right away, in a new chat. Nothing on your computer is changed. Change the words afterwards to make it yours."));
    const search = node("input", "u-search");
    search.type = "search";
    search.id = "u-gallery-search";
    search.dataset.i18nAttr = "placeholder:gallery.search,aria-label:gallery.search";
    search.placeholder = tr("gallery.search", "Search examples");
    search.setAttribute("aria-label", tr("gallery.search", "Search examples"));
    const chips = node("div", "u-chips u-arrows");
    chips.setAttribute("role", "toolbar");
    chips.setAttribute("aria-label", tr("gallery.categories", "Categories"));
    for (const [cat, en] of [["all", "All"]].concat(CATEGORIES)) {
      const c = node("button", "chip u-arrow-item" + (filter === cat ? " on" : ""), cat === "all" ? tr("cat.all", en) : catName(cat));
      c.type = "button";
      c.setAttribute("aria-pressed", String(filter === cat));
      c.addEventListener("click", () => { filter = cat; renderGallery(); const again = gallery.body.querySelector('.u-chips [aria-pressed="true"]'); if (again) again.focus(); });
      chips.append(c);
    }
    const grid = node("div", "u-grid");
    grid.id = "u-gallery-grid";
    const count = node("p", "u-count");
    count.setAttribute("role", "status");
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      grid.replaceChildren();
      let n = 0;
      for (const [id, cat] of TASKS) {
        if (filter !== "all" && cat !== filter) continue;
        const t = task(id);
        if (q && !(t.title + " " + t.prompt + " " + catName(cat)).toLowerCase().includes(q)) continue;
        grid.append(card(id));
        n++;
      }
      count.textContent = n ? tr("gallery.count", "{n} examples", { n }) : tr("gallery.none", "No example matches. Try another word, or just ask LOKI in your own words.");
    };
    search.addEventListener("input", draw);
    body.append(search, chips, count, grid);
    draw();
  }

  function openGallery(cat) {
    if (!window.LokiDialog) return;
    gallery = window.LokiDialog("u-gallery", "gallery.title", "What can LOKI do?", { wide: true, focus: "#u-gallery-search" });
    if (cat) filter = cat;
    renderGallery();
    gallery.open();
  }

  // ------------------------------------------------------------ help center
  let help = null;
  const helpCache = { lang: "", articles: null };

  async function articles() {
    const lang = window.LokiI18n ? window.LokiI18n.lang : "en";
    if (helpCache.articles && helpCache.lang === lang) return helpCache.articles;
    const r = typeof api === "function" ? await api("/help?lang=" + encodeURIComponent(lang)).catch(() => null) : null;
    if (!r || !r.ok) return null;
    helpCache.lang = lang;
    helpCache.articles = r.articles || [];
    return helpCache.articles;
  }

  function md(text) {
    const box = node("div", "text u-article-text");
    // renderMarkdown (app.js) escapes everything first: an article can never inject markup
    if (typeof renderMarkdown === "function") box.innerHTML = renderMarkdown(text);
    else box.textContent = text;
    return box;
  }

  async function showList(query) {
    const body = help.body;
    body.replaceChildren();
    const search = node("input", "u-search");
    search.type = "search";
    search.id = "u-help-search";
    search.dataset.i18nAttr = "placeholder:help.search,aria-label:help.search";
    search.placeholder = tr("help.search", "Search help");
    search.setAttribute("aria-label", tr("help.search", "Search help"));
    search.value = query || "";
    const list = node("div", "u-help-list");
    const status = node("p", "u-count");
    status.setAttribute("role", "status");
    body.append(search, status, list);
    const all = await articles();
    if (!all) {
      status.textContent = tr("help.offline", "Help could not be loaded: LOKI's engine is not answering. Quit LOKI and open it again; the articles are also in the docs/help folder.");
      return;
    }
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      list.replaceChildren();
      const hits = all.filter((a) => !q || (a.title + " " + a.tags.join(" ") + " " + a.text).toLowerCase().includes(q));
      for (const a of hits) {
        const b = node("button", "u-help-item");
        b.type = "button";
        b.append(node("b", "", a.title), node("span", "", a.summary || ""));
        b.addEventListener("click", () => showArticle(a.slug, search.value));
        list.append(b);
      }
      status.textContent = hits.length ? tr("help.count", "{n} articles", { n: hits.length })
        : tr("help.none", "Nothing found. Try a shorter word, or ask LOKI: it can explain itself.");
    };
    search.addEventListener("input", draw);
    draw();
    search.focus();
  }

  async function showArticle(slug, backQuery) {
    const lang = window.LokiI18n ? window.LokiI18n.lang : "en";
    const r = typeof api === "function" ? await api("/help/" + encodeURIComponent(slug) + "?lang=" + lang).catch(() => null) : null;
    const body = help.body;
    body.replaceChildren();
    const back = node("button", "quiet u-back");
    back.type = "button";
    keyed(back, "help.back", "All help articles");
    back.addEventListener("click", () => showList(backQuery || ""));
    body.append(back);
    if (!r || !r.ok) {
      body.append(node("p", "note", (r && r.error) || tr("help.offline", "Help could not be loaded.")));
      back.focus();
      return;
    }
    if (lang !== "en" && !r.translated) body.append(keyed(node("p", "note u-en-only"), "help.english_only", "This article is only in English for now."));
    body.append(md(r.body || r.text));
    back.focus();
  }

  function openHelp(slug) {
    if (!window.LokiDialog) return;
    help = window.LokiDialog("u-help", "help.title", "Help", { wide: true });
    help.open();
    if (slug) showArticle(slug); else showList("");
  }

  // ------------------------------------------------------------ buttons
  const EXTRA_ICONS = {
    help: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.5"/><path d="M12 16.6v.1"/>',
    grid: '<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>',
  };

  function addButtons() {
    if (typeof ICON_PATHS === "object") Object.assign(ICON_PATHS, EXTRA_ICONS);   // icons.js
    const right = document.querySelector(".topbar-right");
    if (right && !document.getElementById("u-help-btn")) {
      const b = node("button", "quiet u-topbtn", "?");
      b.type = "button";
      b.id = "u-help-btn";
      b.dataset.icon = "help";
      b.dataset.tipName = "Help";
      b.dataset.tipWhat = "Search the help articles: getting started, models, privacy, shortcuts (F1).";
      b.addEventListener("click", () => openHelp());
      right.prepend(b);
    }
    const foot = document.querySelector(".sidebar-foot .foot-row") || document.querySelector(".sidebar-foot");
    if (foot && !document.getElementById("u-gallery-btn")) {
      const g = node("button", "quiet u-sidebtn", "What can LOKI do?");
      g.type = "button";
      g.id = "u-gallery-btn";
      g.dataset.icon = "grid";
      g.dataset.tipName = "What can LOKI do?";
      g.dataset.tipWhat = "32 examples you can run with one click: everyday life, work, study, home, money and more.";
      g.addEventListener("click", () => openGallery());
      foot.prepend(g);
    }
    // the home screen: one more chip opens the gallery
    const chips = document.querySelector(".welcome-chips");
    if (chips && !document.getElementById("u-gallery-chip")) {
      const c = node("button", "chip u-more-chip");
      c.type = "button";
      c.id = "u-gallery-chip";
      keyed(c, "home.more", "More ideas…");
      c.addEventListener("click", (e) => { e.stopPropagation(); openGallery(); });
      chips.append(c);
    }
  }

  window.LokiGallery = { open: openGallery, run, tasks: TASKS, categories: CATEGORIES, pickFor, task };
  window.LokiHelp = { open: openHelp };

  document.addEventListener("DOMContentLoaded", () => {
    addButtons();
    document.addEventListener("keydown", (e) => {
      if (e.key === "F1") { e.preventDefault(); openHelp(); }
    });
    // a language switch re-draws open lists in the new language
    document.addEventListener("loki:language", () => {
      helpCache.articles = null;
      if (gallery && gallery.isOpen) renderGallery();
      if (help && help.isOpen) showList("");
    });
  });
})();
