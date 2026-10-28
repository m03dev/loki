// Pictures and PDFs in the chat (owner 2026-10-25 11:42: "can you make it so loki gives me jpg or pdf images in the
// chat"). When a reply of LOKI's names a picture (.png .jpg .jpeg .webp .gif) or a PDF it made - `images/fox.png`,
// ![a fox](images/fox.png), a path in LOKI Projects - it shows right under the reply:
//   a picture   the picture itself; a click shows it big; Open (the computer's own viewer), Save as JPG, Save as PDF
//   a PDF       its page as a picture, page by page, and Open
// Files come from GET /chat/media (engine/chat_media.py: only pictures and PDFs, only the workspace and LOKI Projects).
// Plain DOM, CSP script-src 'self'; api() from app.js. A MutationObserver on #transcript catches every new reply.
"use strict";

const LokiChatMedia = (() => {
  const EXT = "png|jpe?g|webp|gif|pdf";
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.reject(new Error("not ready")));
  const MAX = 8;

  /** The picture / PDF paths a reply names, in order, each once. */
  function pathsIn(text) {
    const out = [], seen = new Set();                    // [where it is in the reply, path]: shown in reply order
    let at = 0;
    const add = (p) => { p = String(p || "").trim().replace(/[.,;:!?)\]]+$/, ""); if (p && !seen.has(p) && new RegExp("\\.(" + EXT + ")$", "i").test(p)) { seen.add(p); out.push([at, p]); } };
    const t = String(text || "");
    for (const m of t.matchAll(new RegExp("!\\[[^\\]]*\\]\\(([^)\\s]+\\.(?:" + EXT + "))\\)", "gi"))) { at = m.index; add(m[1]); }   // ![alt](path)
    for (const m of t.matchAll(new RegExp("`([^`\\n]+\\.(?:" + EXT + "))`", "gi"))) { at = m.index; add(m[1]); }   // `a path with spaces.png`
    for (const m of t.matchAll(new RegExp("(?:^|[\\s(\"'])((?:~|[A-Za-z]:)?[^\\s`'\"()<>|*]*\\.(?:" + EXT + "))(?=[\\s,.;:!?)\"']|$)", "gim"))) {
      if (!/^https?:/i.test(m[1])) { at = m.index; add(m[1]); }
    }
    return out.sort((a, b) => a[0] - b[0]).map((x) => x[1]).slice(0, MAX);
  }

  function btn(label, tip, fn) {
    const b = mk("button", "cm-btn quiet small", label); b.type = "button";
    b.title = tip; b.dataset.tipName = label; b.dataset.tipWhat = tip;
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(b); });
    return b;
  }
  function say(tile, text, bad) { const s = tile.querySelector(".cm-say"); if (s) { s.textContent = text; s.classList.toggle("bad", !!bad); } }

  function imageTile(m) {
    const tile = mk("figure", "cm-tile cm-image"); tile.dataset.path = m.path;
    const img = mk("img", "cm-pic"); img.src = m.data_url; img.alt = m.name; img.loading = "lazy";
    img.addEventListener("click", () => bigView(m.data_url, m.name));
    const cap = mk("figcaption", "cm-cap");
    cap.append(mk("span", "cm-name", m.name + (m.width ? "  " + m.width + "×" + m.height : "")));
    const acts = mk("span", "cm-acts");
    acts.append(btn("Open", "Open it in this computer's own viewer.", () => call("/chat/media/open", { path: m.path })));
    if (!/\.jpe?g$/i.test(m.name)) acts.append(btn("Save as JPG", "Save a JPG copy beside it.", () => convert(tile, m.path, "jpg")));
    acts.append(btn("Save as PDF", "Save a PDF of the picture beside it.", () => convert(tile, m.path, "pdf")));
    acts.append(btn("Pixel art", "Make a 64-pixel game sprite of it (real pixel art: outlines kept, clean colours), saved beside it.", () => convert(tile, m.path, "pixel")));
    cap.append(acts, mk("span", "cm-say"));
    tile.append(img, cap);
    return tile;
  }
  function pdfTile(m) {
    const tile = mk("figure", "cm-tile cm-pdf"); tile.dataset.path = m.path;
    const pic = mk("img", "cm-pic"); pic.alt = m.name + " page " + m.page;
    const note = mk("div", "cm-note");
    const cap = mk("figcaption", "cm-cap"), name = mk("span", "cm-name"), acts = mk("span", "cm-acts");
    let page = m.page || 1;
    const show = (d) => {
      page = d.page || page;
      if (d.image) { pic.src = d.image; pic.hidden = false; note.textContent = ""; } else { pic.hidden = true; note.textContent = d.note || ""; }
      name.textContent = d.name + " · PDF" + (d.pages ? " · page " + page + " of " + d.pages : "");
      prev.disabled = page <= 1; next.disabled = !d.pages || page >= d.pages;
    };
    const go = async (n) => { const d = await call("/chat/media?path=" + encodeURIComponent(m.path) + "&page=" + n).catch(() => null); if (d && d.ok) show(d); };
    const prev = btn("‹", "The page before.", () => go(page - 1)), next = btn("›", "The next page.", () => go(page + 1));
    pic.addEventListener("click", () => { if (pic.src) bigView(pic.src, m.name + " page " + page); });
    acts.append(prev, next, btn("Open", "Open the PDF in this computer's PDF reader.", () => call("/chat/media/open", { path: m.path })));
    cap.append(name, acts, mk("span", "cm-say"));
    tile.append(pic, note, cap);
    show(m);
    return tile;
  }
  async function convert(tile, path, to) {
    say(tile, "Saving...");
    const r = await call("/chat/media/convert", { path, to }).catch((e) => ({ ok: false, error: e.message }));
    say(tile, r && r.ok ? "Saved " + r.name : "Not saved: " + ((r && r.error) || "no answer"), !(r && r.ok));
    if (r && r.ok && r.preview) {             // the pixel sprite: show it big right away
      const d = await call("/chat/media?path=" + encodeURIComponent(r.preview)).catch(() => null);
      if (d && d.ok) bigView(d.data_url, r.name);
    }
  }
  function bigView(src, name) {
    if (window.LokiViewer) {   // the viewer: ‹ › through every picture in the chat, area select / crop / edit
      const tiles = [...document.querySelectorAll(".cm-tile.cm-image")];
      const items = tiles.map((t) => { const p = t.querySelector(".cm-pic"); return { src: p && p.src, name: p && p.alt, path: t.dataset.path }; });
      let at = items.findIndex((x) => x.src === src);
      if (at < 0) { items.push({ src, name, path: "" }); at = items.length - 1; }
      window.LokiViewer.open(items, at);
      return;
    }
    const old = document.getElementById("cm-big"); if (old) old.remove();
    const wrap = mk("div", "cm-big"); wrap.id = "cm-big"; wrap.setAttribute("role", "dialog"); wrap.setAttribute("aria-label", name);
    const img = mk("img"); img.src = src; img.alt = name;
    const close = mk("button", "cm-close", "×"); close.type = "button"; close.setAttribute("aria-label", "Close");
    const done = () => { wrap.remove(); document.removeEventListener("keydown", key, true); };
    const key = (e) => { if (e.key === "Escape") { e.stopPropagation(); done(); } };
    close.addEventListener("click", done); wrap.addEventListener("click", (e) => { if (e.target === wrap) done(); });
    document.addEventListener("keydown", key, true);
    wrap.append(img, close);
    document.body.append(wrap);
    close.focus();
  }

  async function decorate(turn) {
    if (!turn || turn.dataset.mediaDone) return;
    turn.dataset.mediaDone = "1";
    const body = turn.querySelector(".text") || turn;
    const plain = body.cloneNode(true);                // links to the web are not LOKI's files: leave their text out
    for (const a of plain.querySelectorAll("a")) a.remove();
    const paths = pathsIn(plain.textContent || "");
    if (!paths.length) return;
    const strip = mk("div", "cm-strip"); strip.setAttribute("aria-label", "Pictures and PDFs in this reply");
    let shown = 0;
    for (const p of paths) {
      const m = await call("/chat/media?path=" + encodeURIComponent(p)).catch(() => null);
      if (!m || !m.ok) continue;
      if (strip.querySelector('[data-path="' + CSS.escape(m.path) + '"]')) continue;
      try { strip.append(m.kind === "pdf" ? pdfTile(m) : imageTile(m)); }
      catch (exc) { console.warn("chat media:", exc); continue; }
      if (!shown++) turn.append(strip);
    }
    if (shown && typeof scrollDown === "function") scrollDown();
  }
  /** Under a job's output in the work strip: the pictures it made, as pictures (owner 2026-10-26: "if its an image it
   *  should show the image"). Once per element; the text stays below for the details. */
  const SEEN = new Map();
  async function attach(el, text) {
    if (!el || el.dataset.mediaDone) return;
    el.dataset.mediaDone = "1";
    const paths = pathsIn(text || "").filter((p) => !/\.pdf$/i.test(p));
    if (!paths.length) return;
    const strip = mk("div", "cm-strip"); strip.setAttribute("aria-label", "Pictures this job made");
    for (const p of paths) {
      if (!SEEN.has(p)) SEEN.set(p, call("/chat/media?path=" + encodeURIComponent(p)).catch(() => null));   // the work strip redraws often: fetch each picture once
      if (SEEN.size > 200) SEEN.delete(SEEN.keys().next().value);
      const m = await SEEN.get(p);
      if (!m || !m.ok) { SEEN.delete(p); el.dataset.mediaDone = ""; continue; }   // not there yet / still being written: ask again on the next redraw
      if (m.kind === "pdf" || strip.querySelector('[data-path="' + CSS.escape(m.path) + '"]')) continue;
      try { strip.append(imageTile(m)); } catch (exc) { console.warn("job media:", exc); }
    }
    if (strip.childElementCount) el.prepend(strip);
  }
  function scan(root) {
    for (const t of (root || document).querySelectorAll("#transcript .turn.loki:not([data-media-done])")) decorate(t);
  }
  document.addEventListener("DOMContentLoaded", () => {
    const tr = document.getElementById("transcript");
    if (!tr) return;
    let queued = false;
    new MutationObserver(() => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; scan(); }); })
      .observe(tr, { childList: true, subtree: true });
    scan();
  });
  return { pathsIn, decorate, scan, attach };
})();
window.LokiChatMedia = LokiChatMedia;
