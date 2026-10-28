// Forge > Manga: LOKI's Manga Studio (engine/manga.py, engine/manga_api.py) - an idea becomes an outline, a cast with
// locked looks and reference sheets, a panel script per page, drawn panels and typeset lettering, a review and a
// PDF / CBZ (owner 2026-10-28: "add it to loki it should be in the forge tab in another tab like the forge is where we
// create none render stuff"). The owner's own clicks draw at once; an agent's drawing steps wait in Home > For you.
"use strict";

const ForgeManga = (() => {
  if (typeof ICON_PATHS === "object") Object.assign(ICON_PATHS, {
    mgNew: '<path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4"/><path d="M12 11v6M9 14h6"/>',
    mgOutline: '<path d="M5 5h3M5 10h3M5 15h3M5 20h3"/><path d="M11 5h8M11 10h6M11 15h8M11 20h5"/>',
    mgCast: '<circle cx="8" cy="8" r="2.6"/><circle cx="16" cy="8" r="2.6"/><path d="M3.5 18c.6-3 2.3-4.5 4.5-4.5s3.9 1.5 4.5 4.5"/><path d="M11.5 18c.6-3 2.3-4.5 4.5-4.5s3.9 1.5 4.5 4.5"/>',
    mgSheet: '<rect x="3" y="5" width="18" height="14" rx="1"/><circle cx="7.5" cy="10" r="1.6"/><circle cx="12" cy="10" r="1.6"/><circle cx="16.5" cy="10" r="1.6"/><path d="M6 16h3M10.5 16h3M15 16h3"/>',
    mgScript: '<path d="M7 3.5h10v17H7z"/><path d="M9.5 7.5h5M9.5 10.5h5M9.5 13.5h3"/><path d="M4 7v12.5h2"/>',
    mgDraw: '<path d="M4 20l1.2-4.4L15.6 5.2l3.2 3.2L8.4 18.8z"/><path d="M13.6 7.2l3.2 3.2"/><rect x="3" y="3" width="6" height="5" rx=".5"/>',
    mgPage: '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M4 11h16M12 3v8M10 11v10"/>',
    mgLetter: '<path d="M4 6.5c0-1.4 1.1-2.5 2.5-2.5h11c1.4 0 2.5 1.1 2.5 2.5v6c0 1.4-1.1 2.5-2.5 2.5H11l-4.5 4v-4h0A2.5 2.5 0 0 1 4 12.5z"/><path d="M8.5 8h7M8.5 11h4.5"/>',
    mgReview: '<rect x="4" y="3" width="13" height="17" rx="1"/><path d="M7 8h7M7 11h5"/><circle cx="16" cy="16" r="3.2"/><path d="M18.4 18.4l2.6 2.6"/>',
    mgPdf: '<path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4"/><path d="M12 10v7M9.2 14.2L12 17l2.8-2.8"/>',
    mgCbz: '<rect x="5" y="3.5" width="14" height="17" rx="1"/><path d="M12 3.5v3h-2v2h2v2h-2v2h2v2"/><rect x="10" y="15" width="4" height="3" rx=".5"/>',
    mgRead: '<path d="M3 5.5c3-1 6-1 9 1 3-2 6-2 9-1v13c-3-1-6-1-9 1-3-2-6-2-9-1z"/><path d="M12 6.5v13"/>',
    mgRedraw: '<path d="M19 11a7 7 0 0 0-12.5-4.3L5 8.5"/><path d="M5 4v4.5h4.5"/><path d="M8 17.5l.6-2.3 5.4-5.4 1.7 1.7-5.4 5.4z"/>',
    mgAddLine: '<path d="M4 6.5c0-1.4 1.1-2.5 2.5-2.5h11c1.4 0 2.5 1.1 2.5 2.5v6c0 1.4-1.1 2.5-2.5 2.5H11l-4.5 4v-4A2.5 2.5 0 0 1 4 12.5z"/><path d="M12 6.5v6M9 9.5h6"/>',
    mgDelLine: '<path d="M4 6.5c0-1.4 1.1-2.5 2.5-2.5h11c1.4 0 2.5 1.1 2.5 2.5v6c0 1.4-1.1 2.5-2.5 2.5H11l-4.5 4v-4A2.5 2.5 0 0 1 4 12.5z"/><path d="M9 9.5h6"/>',
    mgTeam: '<circle cx="12" cy="7" r="2.6"/><circle cx="5.5" cy="10" r="2"/><circle cx="18.5" cy="10" r="2"/><path d="M7.5 20c.4-3.4 2.1-5.5 4.5-5.5s4.1 2.1 4.5 5.5"/><path d="M2.5 18c.3-2 1.3-3.2 3-3.4M21.5 18c-.3-2-1.3-3.2-3-3.4"/>',
    mgRefresh: '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v4.5h-4.5"/><circle cx="12" cy="12" r="1.2"/>',
  });

  const S = { panel: null, projects: [], library: [], meta: null, proj: null, review: null, page: 1, sel: 0, blobs: {},
    busy: "", reading: false };
  const q = (sel) => S.panel && S.panel.querySelector(sel);
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.resolve({ ok: false, error: "no api" }));
  const btn = (icon, name, what, fn, cls) => {
    const b = forgeBtn(icon, name, what, (e) => { e.stopPropagation(); fn(); }, cls);
    return b;
  };
  const sec = (title, cls) => { const d = el("div", "fuv-sec fmg-sec " + (cls || "")); d.append(el("div", "fuv-sec-title", title)); return d; };
  const field = (label, input) => { const r = el("label", "fmg-field"); r.append(el("span", "", label), input); return r; };
  const select = (opts, value) => {
    const s = el("select", "fmg-in");
    for (const o of opts) { const [v, t] = Array.isArray(o) ? o : [o, o]; const op = el("option", "", t); op.value = v; s.append(op); }
    if (value !== undefined) s.value = value;
    return s;
  };
  const input = (value, ph) => { const i = el("input", "fmg-in"); i.value = value || ""; if (ph) i.placeholder = ph; return i; };
  const area = (value, ph, rows) => { const t = el("textarea", "fmg-in"); t.value = value || ""; if (ph) t.placeholder = ph; t.rows = rows || 3; return t; };

  function say(text, bad) {
    const s = q(".fmg-status"); if (s) { s.textContent = text || ""; s.classList.toggle("bad", !!bad); s.title = text || ""; }
    return text;
  }

  async function picture(path, img) {
    if (!path) { img.removeAttribute("src"); return; }
    const key = path + "@" + ((S.proj && S.proj.updated) || 0);
    if (S.blobs[key]) { img.src = S.blobs[key]; return; }
    try {
      const r = await fetch("/manga/file?path=" + encodeURIComponent(path), { headers: { Authorization: "Bearer " + state.token } });
      if (!r.ok) return;
      const url = URL.createObjectURL(await r.blob());
      S.blobs[key] = url; img.src = url;
    } catch (_) { /* the page shows without it */ }
  }

  // ---------------------------------------------------------------- the panel
  function build() {
    const body = document.querySelector("#forge .forge-body");
    if (!body) return null;
    if (S.panel) return S.panel;
    const p = el("section", "forge-mangapanel"); p.id = "forge-mangapanel"; p.hidden = true;
    S.panel = p;
    const head = el("div", "fuv-head fmg-head"); head.append(el("span", "fuv-title", "Manga"));
    const tb = el("div", "fuv-toolbar fmg-toolbar");
    tb.append(
      btn("mgOutline", "Write Outline", "LOKI writes the outline: a logline and one story job per page, the last page lands the ending.", () => step("outline")),
      btn("mgCast", "Write Cast", "LOKI writes the characters with locked looks (face, hair, build, outfit, colours) so they look the same in every panel.", () => step("characters")),
      btn("mgSheet", "Draw Sheets", "Draw a reference sheet (front, side, back, three expressions) for every character without one - two variants to pick from.", () => drawSheets()),
      btn("mgScript", "Write Script", "LOKI writes this page's panels: shot, angle, action, emotion, style and dialogue (kept apart from the drawing).", () => step("script", { page: S.page })),
      btn("mgDraw", "Draw Page", "Draw every panel of this page that has no picture yet (each at its panel's shape, no text), then letter the page.", () => step("draw_page", { page: S.page })),
      btn("mgLetter", "Letter Page", "Put the page together again: panels, borders and every balloon typeset from the script.", () => step("letter", { page: S.page })),
      btn("mgReview", "Review", "Check the book against the script: undrawn panels, long balloons, characters not in the cast, missing sheets.", () => doReview()),
      btn("mgPdf", "Export PDF", "Every composed page in one PDF (manga/<project>/exports).", () => exportAs("pdf")),
      btn("mgCbz", "Export CBZ", "A CBZ for comic readers (manga/<project>/exports).", () => exportAs("cbz")),
      btn("mgRead", "Read", "Read the book page by page, full size (arrow keys turn pages, Esc closes).", () => read(true)));
    head.append(tb);

    const cols = el("div", "fmg-cols");
    // left: projects, a new project, the character library
    const left = el("div", "fmg-left");
    const projSec = sec("Projects", "fmg-projects");
    projSec.append(btn("mgRefresh", "Refresh", "List the manga projects in this workspace again.", () => refresh()), el("div", "fmg-plist"));
    const newSec = sec("New manga", "fmg-new");
    const meta = S.meta || {};
    const f = {
      premise: area("", "The idea: who, where, what goes wrong ...", 3), title: input("", "Title (optional)"),
      format: select([["page", "Story pages (5-8 panels)"], ["4koma", "4-koma strip"], ["webtoon", "Webtoon scroll"]], "page"),
      colour: select([["mono", "Black and white"], ["color", "Colour"]], "mono"),
      style: select(meta.styles || ["normal", "pop", "watercolor", "gekiga", "sketch", "chibi"], "normal"),
      pages: input("4"), language: input("English"), reading: select([["ltr", "Left to right"], ["rtl", "Right to left (manga)"]], "ltr"),
    };
    f.pages.type = "number"; f.pages.min = 1; f.pages.max = 40;
    newSec.append(field("Idea", f.premise), field("Title", f.title), field("Format", f.format), field("Colour", f.colour),
      field("Style", f.style), field("Pages", f.pages), field("Language", f.language), field("Reading", f.reading),
      btn("mgNew", "Create", "Make the project, then LOKI writes its outline.", () => create(f), "fmg-create"),
      btn("mgTeam", "Let an Agent Make It", "The manga team (writer, artist, editor) makes the whole book in the background with the manga playbook - every drawing step waits for your OK in Home > For you.", () => {
        if (!f.premise.value.trim()) return say("Write the idea first.", true);
        const text = "Make a manga with the manga tool, following skills/playbooks/manga/PLAYBOOK.md: " + f.premise.value.trim()
          + "\nFormat: " + f.format.value + ", " + (+f.pages.value || 4) + " pages, " + (f.colour.value === "color" ? "colour" : "black and white")
          + ", style " + f.style.value + ", dialogue in " + (f.language.value || "English") + ", reading " + f.reading.value
          + (f.title.value.trim() ? ", title \"" + f.title.value.trim() + "\"" : "") + ".";
        if (typeof sendToBackground === "function") { sendToBackground(text); say("The manga team is on it - its drawing steps wait in Home > For you."); }
      }, "fmg-create"));
    const libSec = sec("Character library", "fmg-lib"); libSec.append(el("div", "fmg-liblist"));
    left.append(projSec, newSec, libSec);

    // centre: the page
    const mid = el("div", "fmg-mid");
    const tabs = el("div", "fmg-pagetabs");
    const stage = el("div", "fmg-stage");
    const sheet = el("div", "fmg-sheet"); const img = el("img", "fmg-pageimg"); img.alt = "The composed page";
    const hot = el("div", "fmg-hot"); sheet.append(img, hot); stage.append(sheet);
    mid.append(tabs, stage, el("div", "fmg-empty", "Pick a project on the left, or write an idea under New manga."));

    // right: outline, cast, the page's script, the picked panel
    const right = el("div", "fmg-right");
    const outSec = sec("Outline", "fmg-outline"); outSec.append(el("div", "fmg-outbody"));
    const castSec = sec("Cast", "fmg-cast"); castSec.append(el("div", "fmg-castlist"));
    const scrSec = sec("Page script", "fmg-script"); scrSec.append(el("div", "fmg-scrbody"));
    const panSec = sec("Panel", "fmg-panel"); panSec.append(el("div", "fmg-panbody"));
    const revSec = sec("Review", "fmg-review"); revSec.append(el("div", "fmg-revbody"));
    right.append(outSec, castSec, scrSec, panSec, revSec);
    cols.append(left, mid, right);

    const reader = el("div", "fmg-reader"); reader.hidden = true;
    const rimg = el("img", "fmg-readimg"); rimg.alt = "Page";
    reader.append(rimg, btn("close", "Close", "Close the reader (Esc).", () => read(false), "fmg-readclose"));
    reader.addEventListener("click", (e) => { if (e.target === reader || e.target === rimg) turn(e.offsetX < reader.clientWidth / 2 ? -1 : 1); });

    p.append(head, cols, reader, el("div", "fuv-status fmg-status", "Manga workspace."));
    p.addEventListener("keydown", (e) => {
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) { e.stopPropagation(); if (e.key === "Escape") e.target.blur(); return; }
      if (S.reading && (e.key === "ArrowRight" || e.key === "ArrowLeft")) { e.preventDefault(); e.stopPropagation(); turn(e.key === "ArrowRight" ? 1 : -1); }
      if (S.reading && e.key === "Escape") { e.stopPropagation(); read(false); }
    }, true);
    p.tabIndex = -1;
    body.append(p);
    return p;
  }

  // ---------------------------------------------------------------- data
  async function refresh(id) {
    if (!S.meta) { const m = await call("/manga/meta"); if (m && m.ok) S.meta = m; }
    const d = await call("/manga/list");
    if (!d || !d.ok) return say((d && d.error) || "Manga Studio did not answer.", true);
    S.projects = d.projects || []; S.library = d.library || [];
    drawProjects();
    const want = id || (S.proj && S.proj.id) || (S.projects[0] && S.projects[0].id);
    if (want) await open(want); else drawProject();
  }

  async function open(id) {
    const d = await call("/manga/project?id=" + encodeURIComponent(id));
    if (!d || !d.ok) return say((d && d.error) || "That project is gone.", true);
    S.proj = d.project; S.review = d.review;
    const pages = S.proj.pages || [];
    if (!pages.some((pg) => pg.n === S.page)) S.page = pages.length ? pages[0].n : 1;
    drawProjects(); drawProject();
  }

  function page() { return ((S.proj && S.proj.pages) || []).find((pg) => pg.n === S.page) || null; }

  // ---------------------------------------------------------------- drawing the UI
  function drawProjects() {
    const box = q(".fmg-plist"); if (!box) return;
    box.replaceChildren();
    if (!S.projects.length) box.append(el("div", "fmg-hint", "No manga yet."));
    for (const pr of S.projects) {
      const b = el("button", "fmg-pitem" + (S.proj && S.proj.id === pr.id ? " on" : ""));
      b.type = "button"; b.title = pr.title + " - " + pr.format + ", " + pr.pages + " pages, " + pr.drawn + " composed";
      b.append(el("span", "fmg-ptitle", pr.title || pr.id), el("span", "fmg-pmeta", pr.format + " · " + pr.drawn + "/" + pr.pages));
      b.addEventListener("click", () => open(pr.id));
      box.append(b);
    }
    const lib = q(".fmg-liblist"); if (lib) { lib.replaceChildren(); for (const n of S.library) lib.append(el("span", "fmg-chip", n)); if (!S.library.length) lib.append(el("div", "fmg-hint", "Characters with a sheet are kept here and reused when a new manga has the same name.")); }
  }

  function drawProject() {
    const pr = S.proj;
    const empty = q(".fmg-empty"); if (empty) empty.hidden = !!pr;
    const stage = q(".fmg-stage"); if (stage) stage.hidden = !pr;
    const tabs = q(".fmg-pagetabs"); if (tabs) tabs.replaceChildren();
    for (const s of [".fmg-outbody", ".fmg-castlist", ".fmg-scrbody", ".fmg-panbody", ".fmg-revbody"]) { const n = q(s); if (n) n.replaceChildren(); }
    if (!pr) return;
    // page tabs
    for (const pg of pr.pages || []) {
      const t = el("button", "fmg-tab" + (pg.n === S.page ? " on" : "") + (pg.file ? " made" : ""), String(pg.n));
      t.type = "button"; t.title = "Page " + pg.n + (pg.beat ? " - " + pg.beat : "") + (pg.file ? "" : " (not composed yet)");
      t.addEventListener("click", () => { S.page = pg.n; S.sel = 0; drawProject(); });
      tabs.append(t);
    }
    drawPage(); drawOutline(); drawCast(); drawScript(); drawPanel(); drawReview();
  }

  function drawPage() {
    const pg = page(), img = q(".fmg-pageimg"), hot = q(".fmg-hot");
    if (!img || !hot) return;
    hot.replaceChildren();
    if (!pg || !pg.file) { img.removeAttribute("src"); img.hidden = true; hot.append(el("div", "fmg-hint fmg-nopage", pg && pg.panels ? "This page is scripted - Draw Page (or Letter Page for a sketch of the layout)." : "No script for this page yet - Write Script.")); return; }
    img.hidden = false;
    picture(pg.file, img);
    for (const b of pg.boxes || []) {       // the panels as click targets, in % of the page
      const h = el("button", "fmg-hotpanel" + (b.n === S.sel ? " on" : ""));
      h.type = "button"; h.title = "Panel " + b.n + " - click to edit it";
      Object.assign(h.style, { left: b.x + "%", top: b.y + "%", width: b.w + "%", height: b.h + "%" });
      h.addEventListener("click", () => { S.sel = b.n; drawPage(); drawPanel(); });
      hot.append(h);
    }
  }

  function drawOutline() {
    const box = q(".fmg-outbody"), pr = S.proj; if (!box) return;
    const o = pr.outline || {};
    box.append(el("div", "fmg-title", pr.title), el("div", "fmg-sub", [pr.format, pr.colour, pr.style, pr.language, pr.reading].join(" · ")));
    if (!o.pages) { box.append(el("div", "fmg-hint", "No outline yet - Write Outline.")); return; }
    if (o.logline) box.append(el("div", "fmg-logline", o.logline));
    for (const pg of o.pages) {
      const r = el("div", "fmg-beat" + (pg.n === S.page ? " on" : ""));
      r.append(el("b", "", pg.n + ". " + (pg.beat || "")), el("span", "", " " + (pg.summary || "")));
      r.addEventListener("click", () => { S.page = pg.n; S.sel = 0; drawProject(); });
      box.append(r);
    }
  }

  function drawCast() {
    const box = q(".fmg-castlist"); if (!box) return;
    const chars = S.proj.characters || [];
    if (!chars.length) { box.append(el("div", "fmg-hint", "No cast yet - Write Cast.")); return; }
    for (const c of chars) {
      const card = el("div", "fmg-char");
      const th = el("img", "fmg-charimg"); th.alt = c.name + "'s sheet"; picture(c.sheet, th);
      const lk = c.look || {};
      const info = el("div", "fmg-charinfo");
      info.append(el("b", "", c.name + (c.role ? " · " + c.role : "")),
        el("div", "fmg-look", ["hair", "face", "outfit"].map((k) => lk[k]).filter(Boolean).join("; ")));
      const vs = el("div", "fmg-variants");
      for (const v of c.variants || []) {
        const vi = el("img", "fmg-variant" + (v === c.sheet ? " on" : "")); vi.alt = "variant"; vi.title = "Use this sheet for " + c.name;
        picture(v, vi);
        vi.addEventListener("click", async () => { const d = await call("/manga/do", { action: "pick", project: S.proj.id, character: c.id, file: v }); say(d.ok ? c.name + "'s sheet picked." : d.error, !d.ok); open(S.proj.id); });
        vs.append(vi);
      }
      info.append(vs, btn("mgSheet", "Draw Sheet", "Draw " + c.name + "'s reference sheet - two variants to pick from.", () => step("sheet", { character: c.id, variants: 2 }), "fmg-small"));
      card.append(th, info);
      box.append(card);
    }
  }

  function drawScript() {
    const box = q(".fmg-scrbody"), pg = page(); if (!box) return;
    if (!pg || !(pg.panels || []).length) { box.append(el("div", "fmg-hint", "Page " + S.page + " has no script yet - Write Script.")); return; }
    box.append(el("div", "fmg-sub", "Layout: " + (pg.layout || "") + " · " + pg.panels.length + " panels"));
    for (const pn of pg.panels) {
      const r = el("div", "fmg-pline" + (pn.n === S.sel ? " on" : ""));
      r.append(el("b", "", pn.n + ". " + pn.shot + ", " + pn.angle), el("div", "", pn.action));
      for (const d of pn.dialogue || []) r.append(el("div", "fmg-say fmg-" + d.kind, (d.speaker ? d.speaker + ": " : "") + d.text));
      r.addEventListener("click", () => { S.sel = pn.n; drawPage(); drawPanel(); drawScript(); });
      box.append(r);
    }
  }

  function drawPanel() {
    const box = q(".fmg-panbody"), pg = page(); if (!box) return;
    box.replaceChildren();
    const pn = pg && (pg.panels || []).find((x) => x.n === S.sel);
    if (!pn) { box.append(el("div", "fmg-hint", "Click a panel on the page (or in the script) to change it.")); return; }
    const kinds = (S.meta && S.meta.kinds) || ["speech", "thought", "shout", "whisper", "narration", "sfx"];
    const act = area(pn.action, "What we see", 3);
    const style = select((S.meta && S.meta.styles) || ["normal"], pn.style);
    const note = input("", "What to change in the picture");
    box.append(el("b", "", "Panel " + pn.n), field("Action", act), field("Style", style), field("Note", note),
      btn("mgRedraw", "Redraw Panel", "Draw only this panel again with the action, style and note above; the rest of the page stays.", () =>
        step("edit_panel", { page: S.page, panel: pn.n, note: note.value, panel_action: act.value !== pn.action ? act.value : "", style: style.value }), "fmg-small"));
    const lines = el("div", "fmg-lines");
    const rows = [];
    const addRow = (d) => {
      const row = el("div", "fmg-line");
      const who = input(d.speaker, "Who"), kind = select(kinds, d.kind || "speech"), text = input(d.text, "Words"),
        place = select(["", "top-left", "top", "top-right", "middle", "bottom-left", "bottom", "bottom-right"], d.place || "");
      place.title = "Where the balloon goes (empty = LOKI places it)";
      row.append(who, kind, text, place, btn("mgDelLine", "Remove Line", "Take this line out of the panel.", () => { row.remove(); rows.splice(rows.indexOf(rec), 1); }, "fmg-small"));
      const rec = { who, kind, text, place }; rows.push(rec); lines.append(row);
    };
    for (const d of pn.dialogue || []) addRow(d);
    box.append(el("div", "fmg-sub", "Dialogue (re-lettered without redrawing)"), lines,
      btn("mgAddLine", "Add Line", "Add a balloon, a thought, a narration box or a sound effect.", () => addRow({ kind: "speech" }), "fmg-small"),
      btn("mgLetter", "Letter Panel", "Put these words on the page (the picture is not redrawn).", async () => {
        const dialogue = rows.map((r) => ({ speaker: r.who.value, kind: r.kind.value, text: r.text.value, place: r.place.value })).filter((d) => d.text.trim());
        const d = await call("/manga/do", { action: "letter", project: S.proj.id, page: S.page, panel: pn.n, data: { dialogue } });
        say(d.ok ? "Panel " + pn.n + " lettered." : d.error, !d.ok); open(S.proj.id);
      }, "fmg-small"));
  }

  function drawReview() {
    const box = q(".fmg-revbody"), rv = S.review; if (!box || !rv) return;
    box.append(el("div", rv.ok ? "fmg-ok" : "fmg-sub", rv.ok ? "Everything is drawn and lettered." : rv.issues.length + " open:"));
    for (const i of rv.issues || []) box.append(el("div", "fmg-issue", i));
  }

  // ---------------------------------------------------------------- actions
  async function create(f) {
    if (!f.premise.value.trim()) return say("Write the idea first.", true);
    const d = await call("/manga/do", { action: "project", premise: f.premise.value, title: f.title.value, format: f.format.value,
      colour: f.colour.value, style: f.style.value, pages: +f.pages.value || 4, language: f.language.value, reading: f.reading.value });
    if (!d.ok) return say(d.error, true);
    f.premise.value = ""; f.title.value = "";
    await refresh(d.project);
    step("outline");
  }

  async function step(action, extra) {
    if (!S.proj) return say("Pick or create a project first.", true);
    if (S.busy) return say("Still working on: " + S.busy, true);
    const d = await call("/manga/do", Object.assign({ action, project: S.proj.id }, extra || {}));
    if (!d.ok) return say(d.error || "That did not work.", true);
    if (!d.job) { say(action + " done."); return refresh(S.proj.id); }
    S.busy = action; say(label(action) + " ...");
    const t0 = Date.now();
    for (;;) {
      await new Promise((r) => setTimeout(r, 1500));
      const j = await call("/manga/job?id=" + d.job);
      if (!j.ok || j.status !== "running") {
        S.busy = "";
        const res = (j && j.result) || {};
        say(j.status === "done" ? label(action) + " done" + (res.errors && res.errors.length ? " (" + res.errors.length + " panels failed: " + res.errors[0] + ")" : ".") : (res.error || "It failed."), j.status !== "done");
        return refresh(S.proj.id);
      }
      say(label(action) + " ... " + Math.round((Date.now() - t0) / 1000) + " s");
    }
  }
  function label(a) { return { outline: "Writing the outline", characters: "Writing the cast", script: "Writing page " + S.page, sheet: "Drawing the sheet", draw_page: "Drawing page " + S.page, edit_panel: "Redrawing the panel", letter: "Lettering" }[a] || a; }

  async function drawSheets() {
    const todo = ((S.proj && S.proj.characters) || []).filter((c) => !c.sheet);
    if (!todo.length) return say("Every character has a sheet - Draw Sheet on one to draw more variants.");
    for (const c of todo) { await step("sheet", { character: c.id, variants: 2 }); }
  }

  async function doReview() {
    if (!S.proj) return;
    const d = await call("/manga/do", { action: "review", project: S.proj.id });
    S.review = d; drawProject();
    say(d.ok ? "Review: everything is drawn and lettered." : "Review: " + (d.issues || []).length + " open (right column).", !d.ok);
  }

  async function exportAs(fmt) {
    if (!S.proj) return;
    const d = await call("/manga/do", { action: "export", project: S.proj.id, format: fmt });
    say(d.ok ? "Saved " + d.file + " (" + d.pages + " pages)." : d.error, !d.ok);
  }

  function read(on) {
    const r = q(".fmg-reader"); if (!r) return;
    const made = ((S.proj && S.proj.pages) || []).filter((pg) => pg.file);
    if (on && !made.length) return say("No composed pages yet.", true);
    S.reading = !!on; r.hidden = !on;
    if (on) { if (!made.some((pg) => pg.n === S.page)) S.page = made[0].n; picture(page().file, q(".fmg-readimg")); S.panel.focus(); }
  }
  function turn(dir) {
    const made = ((S.proj && S.proj.pages) || []).filter((pg) => pg.file);
    const i = made.findIndex((pg) => pg.n === S.page) + (S.proj.reading === "rtl" ? -dir : dir);
    if (i < 0 || i >= made.length) return;
    S.page = made[i].n; picture(made[i].file, q(".fmg-readimg")); drawProject();
  }

  function show(on) {
    const p = build(); if (!p) return;
    p.hidden = !on;
    document.querySelector("#forge .forge-body")?.classList.toggle("ws-manga", !!on);
    if (on) refresh();
  }

  return { show, refresh, open, state: S };
})();
