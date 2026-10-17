// Research round 3 - richer replies in the chat (docs/integrations/research-2026-10-17b.md):
//   code blocks with their language, Copy and (for html/svg) Preview + Save; ```mermaid diagrams drawn in
//   place; ```chart blocks (JSON) drawn as bar/line/pie charts; ```loki-card blocks (weather, news, clock)
//   drawn as cards; tables; links that open in your browser; [1] citations that jump to their source.
// The window's policy forbids inline scripts and styles, so a preview or a diagram runs in a sandboxed frame
// served by the engine (GET /artifact/<id>, its own CSP, no network, no access to LOKI) - see
// engine/artifacts.py. Charts and cards are plain DOM/SVG made here (no library).
// Hooks without touching app.js: renderMarkdown is replaced (it is a global function app.js calls by name).
"use strict";

const Artifacts = (function () {
  const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const SVGNS = "http://www.w3.org/2000/svg";
  const PALETTE = ["#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2", "#b279a2", "#eeca3b", "#9d755d"];

  // ------------------------------------------------------------------ Markdown
  function inline(t) {
    // t is already escaped. Links first (so their text is not re-matched), then code, bold, italics, citations.
    const codes = [];
    t = t.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return "\u0000" + (codes.length - 1) + "\u0000"; });
    t = t.replace(/\[([^\]]{1,200})\]\((https?:\/\/[^\s)]{1,2000})\)/g, (_, txt, url) =>
      '<a href="' + url + '" class="ext-link" data-url="' + url + '">' + txt + "</a>");
    t = t.replace(/(^|[\s(])(https?:\/\/[^\s<)]{4,2000})/g, (_, pre, url) =>
      pre + '<a href="' + url + '" class="ext-link" data-url="' + url + '">' + url.replace(/^https?:\/\//, "").slice(0, 60) + "</a>");
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>");
    t = t.replace(/\[(\d{1,2})\](?!\()/g, '<sup class="cite" data-cite="$1">$1</sup>');
    return t.replace(/\u0000(\d+)\u0000/g, (_, i) => "<code>" + codes[+i] + "</code>");
  }

  function table(lines) {
    const cells = (l) => l.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());
    const head = cells(lines[0]);
    let html = '<div class="md-table"><table><thead><tr>' + head.map((c) => "<th>" + inline(c) + "</th>").join("") + "</tr></thead><tbody>";
    for (const l of lines.slice(2)) html += "<tr>" + cells(l).map((c) => "<td>" + inline(c) + "</td>").join("") + "</tr>";
    return html + "</tbody></table></div>";
  }

  function block(trimmed) {
    const lines = trimmed.split("\n");
    const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed);
    if (heading && lines.length === 1) {
      const level = Math.min(heading[1].length, 4);
      return `<h${level}>${inline(heading[2])}</h${level}>`;
    }
    if (lines.length >= 2 && /^\s*\|.*\|\s*$/.test(lines[0]) && /^\s*\|?\s*:?-{2,}/.test(lines[1])) return table(lines);
    if (lines.every((l) => /^\s*[-*]\s+/.test(l))) {
      return "<ul>" + lines.map((l) => {
        const box = /^\s*[-*]\s+\[([ xX])\]\s+(.*)$/.exec(l);
        if (box) return '<li class="task' + (box[1] !== " " ? " done" : "") + '">' + inline(box[2]) + "</li>";
        return "<li>" + inline(l.replace(/^\s*[-*]\s+/, "")) + "</li>";
      }).join("") + "</ul>";
    }
    if (lines.every((l) => /^\s*\d+[.)]\s+/.test(l))) {
      return "<ol>" + lines.map((l) => "<li>" + inline(l.replace(/^\s*\d+[.)]\s+/, "")) + "</li>").join("") + "</ol>";
    }
    if (lines.every((l) => /^\s*&gt;\s?/.test(l))) return "<blockquote>" + inline(lines.map((l) => l.replace(/^\s*&gt;\s?/, "")).join("<br>")) + "</blockquote>";
    if (/^(-{3,}|\*{3,})$/.test(trimmed)) return "<hr>";
    return "<p>" + inline(lines.join("<br>")) + "</p>";
  }

  // Same contract as app.js's renderMarkdown: everything escaped first, so model output never injects markup.
  function render(source) {
    const parts = String(source).split(/^```/m);
    let html = "";
    parts.forEach((part, index) => {
      if (index % 2 === 1) {
        const nl = part.indexOf("\n");
        const lang = (nl < 0 ? part : part.slice(0, nl)).trim().toLowerCase().replace(/[^a-z0-9_+-]/g, "").slice(0, 20);
        const body = nl < 0 ? "" : part.slice(nl + 1).replace(/\n$/, "");
        html += '<pre class="code" data-lang="' + lang + '"><code>' + esc(body) + "</code></pre>";
        return;
      }
      for (const b of esc(part).split(/\n{2,}/)) { const t = b.trim(); if (t) html += block(t); }
    });
    return html;
  }

  // ------------------------------------------------------------------ helpers
  function button(icon, name, what, onClick, cls) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "art-btn " + (cls || "");
    b.dataset.icon = icon; b.dataset.tipName = name; b.dataset.tipWhat = what;
    b.textContent = name;
    b.addEventListener("click", (e) => { e.stopPropagation(); onClick(b); });
    return b;
  }

  async function copyText(text, b) {
    try { await navigator.clipboard.writeText(text); } catch (_) {
      const t = document.createElement("textarea"); t.value = text; document.body.append(t); t.select();
      try { document.execCommand("copy"); } catch (_e) { /* nothing */ } t.remove();
    }
    if (b) { b.classList.add("done"); setTimeout(() => b.classList.remove("done"), 1200); }
  }

  async function makePage(code, kind) {
    const data = await api("/artifact", { code, kind });
    if (!data || !data.ok) throw new Error((data && data.error) || "the preview could not be made");
    return data;
  }

  function frame(url, cls, title) {
    const f = document.createElement("iframe");
    f.className = cls; f.title = title || "Preview";
    f.setAttribute("sandbox", "allow-scripts");     // no allow-same-origin: it cannot reach LOKI
    f.setAttribute("referrerpolicy", "no-referrer");
    f.src = url;
    return f;
  }

  // Frames tell their height (mermaid pages do); match them by their window.
  window.addEventListener("message", (ev) => {
    if (!ev.data || ev.data.lokiArtifact !== 1) return;
    for (const f of document.querySelectorAll("iframe.art-diagram")) {
      if (f.contentWindow === ev.source) f.style.height = Math.min(Math.max(+ev.data.height || 120, 60), 1400) + "px";
    }
  });

  // ------------------------------------------------------------------ canvas (preview pane)
  let canvas = null;
  function openCanvas(page, code, kind) {
    if (!canvas) {
      canvas = document.createElement("aside");
      canvas.className = "art-canvas"; canvas.setAttribute("aria-label", "Preview");
      const bar = document.createElement("div"); bar.className = "art-canvas-bar";
      const title = document.createElement("span"); title.className = "art-canvas-title";
      const actions = document.createElement("span"); actions.className = "art-canvas-actions";
      bar.append(title, actions);
      canvas.append(bar);
      document.body.append(canvas);
      document.addEventListener("keydown", (e) => { if (e.key === "Escape" && canvas && !canvas.hidden) closeCanvas(); });
    }
    canvas.hidden = false;
    document.body.classList.add("with-canvas");
    const old = canvas.querySelector("iframe"); if (old) old.remove();
    canvas.querySelector(".art-canvas-title").textContent = kind === "svg" ? "SVG preview" : "Page preview";
    const actions = canvas.querySelector(".art-canvas-actions");
    actions.replaceChildren(
      button("copy", "Copy code", "Copy this page's code.", (b) => copyText(code, b)),
      button("save", "Save to workspace", "Save it as artifacts/<name>.html (earlier versions are kept as .v2, .v3...).", async () => {
        const name = (prompt("Save as (a short name):", "page") || "").trim();
        if (!name) return;
        const out = await api("/artifact/save", { id: page.id, name });
        addNotice(out.ok ? "Saved " + out.path + (out.same ? " (no change)" : "") : (out.error || "Not saved"), !out.ok);
      }),
      button("expand", "Full width", "Make the preview wider or narrower.", () => canvas.classList.toggle("wide")),
      button("close", "Close preview", "Close the preview (Esc).", closeCanvas));
    canvas.append(frame(page.url, "art-frame", "Preview of LOKI's page"));
  }
  function closeCanvas() {
    if (!canvas) return;
    canvas.hidden = true; document.body.classList.remove("with-canvas");
    const f = canvas.querySelector("iframe"); if (f) f.remove();
  }

  // ------------------------------------------------------------------ charts (```chart JSON)
  function svg(tag, attrs, parent) {
    const n = document.createElementNS(SVGNS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.append(n);
    return n;
  }

  function chart(spec) {
    const type = String(spec.type || "bar").toLowerCase();
    const labels = (spec.labels || []).map(String).slice(0, 60);
    let series = spec.series || (spec.data ? [{ name: spec.name || "", data: spec.data }] : []);
    series = series.slice(0, 8).map((s) => ({ name: String(s.name || ""), data: (s.data || []).map(Number).slice(0, 60) }));
    if (!series.length || !series[0].data.length) throw new Error("a chart needs labels and data");
    const W = 560, H = 260, L = 44, B = 34, T = spec.title ? 28 : 10, R = 10;
    const box = document.createElement("figure"); box.className = "art-chart";
    const root = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": spec.title || "Chart" });
    box.append(root);
    if (spec.title) { const t = svg("text", { x: W / 2, y: 18, "text-anchor": "middle", class: "c-title" }, root); t.textContent = spec.title; }
    if (type === "pie" || type === "donut") {
      const vals = series[0].data, total = vals.reduce((a, b) => a + Math.max(b, 0), 0) || 1;
      let a0 = -Math.PI / 2; const cx = 150, cy = (H + T) / 2, r = Math.min(100, (H - T) / 2 - 8);
      vals.forEach((v, i) => {
        const a1 = a0 + 2 * Math.PI * Math.max(v, 0) / total, big = a1 - a0 > Math.PI ? 1 : 0;
        const p = vals.length === 1 ? "M" + (cx - r) + "," + cy + "a" + r + "," + r + " 0 1,0 " + 2 * r + ",0a" + r + "," + r + " 0 1,0 " + -2 * r + ",0"
          : "M" + cx + "," + cy + "L" + (cx + r * Math.cos(a0)) + "," + (cy + r * Math.sin(a0)) + "A" + r + "," + r + " 0 " + big + ",1 " + (cx + r * Math.cos(a1)) + "," + (cy + r * Math.sin(a1)) + "Z";
        const s = svg("path", { d: p, fill: PALETTE[i % PALETTE.length], stroke: "#fff", "stroke-width": 1.5 }, root);
        svg("title", {}, s).textContent = (labels[i] || "") + ": " + v;
        const ly = T + 14 + i * 20;
        svg("rect", { x: 290, y: ly - 10, width: 12, height: 12, rx: 2, fill: PALETTE[i % PALETTE.length] }, root);
        svg("text", { x: 308, y: ly, class: "c-label" }, root).textContent = (labels[i] || "") + " - " + v + " (" + Math.round(100 * v / total) + "%)";
        a0 = a1;
      });
      if (type === "donut") svg("circle", { cx, cy, r: r * 0.55, fill: "var(--bg, #fff)" }, root);
      return box;
    }
    const all = series.flatMap((s) => s.data), max = Math.max(...all, 0), min = Math.min(...all, 0);
    const span = (max - min) || 1, n = Math.max(...series.map((s) => s.data.length));
    const x = (i) => L + (W - L - R) * (n === 1 ? 0.5 : (type === "line" ? i / (n - 1) : (i + 0.5) / n));
    const y = (v) => T + (H - T - B) * (1 - (v - min) / span);
    for (let g = 0; g <= 4; g++) {
      const v = min + span * g / 4, yy = y(v);
      svg("line", { x1: L, x2: W - R, y1: yy, y2: yy, class: "c-grid" }, root);
      svg("text", { x: L - 6, y: yy + 4, "text-anchor": "end", class: "c-axis" }, root).textContent = Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + "k" : (Math.round(v * 10) / 10);
    }
    const step = Math.ceil(n / 12);
    for (let i = 0; i < n; i += step) svg("text", { x: x(i), y: H - B + 16, "text-anchor": "middle", class: "c-axis" }, root).textContent = (labels[i] || String(i + 1)).slice(0, 12);
    series.forEach((s, si) => {
      const color = PALETTE[si % PALETTE.length];
      if (type === "line") {
        svg("polyline", { points: s.data.map((v, i) => x(i) + "," + y(v)).join(" "), fill: "none", stroke: color, "stroke-width": 2.2 }, root);
        s.data.forEach((v, i) => { const c = svg("circle", { cx: x(i), cy: y(v), r: 3, fill: color }, root); svg("title", {}, c).textContent = (labels[i] || "") + ": " + v; });
      } else {
        const bw = (W - L - R) / n * 0.8 / series.length;
        s.data.forEach((v, i) => {
          const x0 = x(i) - (bw * series.length) / 2 + si * bw, y0 = y(Math.max(v, 0)), h = Math.abs(y(v) - y(0));
          const r = svg("rect", { x: x0, y: y0, width: Math.max(bw - 2, 1), height: Math.max(h, 1), rx: 2, fill: color }, root);
          svg("title", {}, r).textContent = (s.name ? s.name + " - " : "") + (labels[i] || "") + ": " + v;
        });
      }
    });
    if (series.length > 1 || series[0].name) {
      const legend = document.createElement("figcaption"); legend.className = "c-legend";
      series.forEach((s, si) => { const k = document.createElement("span"); k.className = "c-key c" + (si % PALETTE.length); k.textContent = s.name || "Series " + (si + 1); legend.append(k); });
      box.append(legend);
    }
    return box;
  }

  // ------------------------------------------------------------------ cards (```loki-card)
  const SKY = { sun: "☀", "cloud-sun": "⛅", cloud: "☁", fog: "🌫", rain: "🌧", snow: "❄", storm: "⛈" };
  function card(spec) {
    const c = document.createElement("div"); c.className = "loki-card " + (spec.kind || "");
    const h = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
    if (spec.kind === "weather") {
      const now = spec.now || {};
      const top = h("div", "lc-top");
      top.append(h("span", "lc-sky", SKY[now.icon] || "☁"), h("span", "lc-temp", Math.round(+now.temp) + (spec.unit || "")),
        h("span", "lc-where", spec.place || ""), h("span", "lc-words", (now.words || "") + " · feels " + Math.round(+now.feels) + (spec.unit || "")));
      const days = h("div", "lc-days");
      for (const d of spec.days || []) {
        const cell = h("div", "lc-day");
        cell.append(h("b", "", d.day.split(" ")[0]), h("span", "lc-sky small", SKY[d.icon] || "☁"),
          h("span", "", Math.round(+d.hi) + "° / " + Math.round(+d.lo) + "°"), h("small", "", d.rain != null ? d.rain + "% rain" : ""));
        days.append(cell);
      }
      c.append(top, days, h("small", "lc-src", "Open-Meteo"));
    } else if (spec.kind === "news") {
      c.append(h("b", "lc-head", spec.topic ? "News: " + spec.topic : "Top stories"));
      const list = h("ol", "lc-news");
      for (const it of (spec.items || []).slice(0, 10)) {
        const li = h("li");
        const a = h("a", "ext-link", it.title); a.href = it.link; a.dataset.url = it.link;
        li.append(a, h("small", "", " " + [it.source, it.age].filter(Boolean).join(" · ")));
        list.append(li);
      }
      c.append(list);
    } else if (spec.kind === "clock") {
      c.append(h("span", "lc-temp", spec.time || ""), h("span", "lc-where", spec.place || ""), h("span", "lc-words", (spec.date || "") + " · " + (spec.zone || "")));
    } else {
      throw new Error("unknown card");
    }
    return c;
  }

  // ------------------------------------------------------------------ decorate a rendered reply
  function decorate(root) {
    if (!root) return;
    for (const pre of root.querySelectorAll("pre.code:not([data-done])")) {
      pre.dataset.done = "1";
      const lang = pre.dataset.lang || "", code = pre.textContent;
      try {
        if (lang === "chart") { pre.replaceWith(chart(JSON.parse(code))); continue; }
        if (lang === "loki-card") { pre.replaceWith(card(JSON.parse(code))); continue; }
      } catch (_) { /* not valid: show it as code */ }
      if (lang === "mermaid") {
        const holder = document.createElement("div"); holder.className = "art-diagram-box";
        pre.replaceWith(holder);
        holder.append(pre);
        makePage(code, "mermaid").then((page) => {
          const f = frame(page.url, "art-diagram", "Diagram");
          holder.prepend(f);
          pre.classList.add("art-source");
          const bar = document.createElement("div"); bar.className = "code-bar";
          bar.append(button("code", "Show source", "Show or hide the diagram's text.", () => pre.classList.toggle("art-source")),
            button("copy", "Copy", "Copy the diagram's text.", (b) => copyText(code, b)));
          holder.append(bar);
        }).catch(() => { /* engine without previews: the code stays */ });
        continue;
      }
      const bar = document.createElement("div"); bar.className = "code-bar";
      bar.append(Object.assign(document.createElement("span"), { className: "code-lang", textContent: lang || "text" }));
      bar.append(button("copy", "Copy", "Copy this code.", (b) => copyText(code, b)));
      if (lang === "html" || lang === "svg" || (lang === "xml" && /^\s*<svg/i.test(code))) {
        bar.append(button("eye", "Preview", "Run it in a sandboxed preview beside the chat (it cannot reach LOKI or the internet).", async () => {
          try { openCanvas(await makePage(code, lang === "html" ? "html" : "svg"), code, lang === "html" ? "html" : "svg"); }
          catch (e) { addNotice(String(e.message || e), true); }
        }));
      }
      pre.before(bar);
    }
    // citations: [n] jumps to the n-th link of the reply (research_web / deep_research number their sources)
    const links = [...root.querySelectorAll("a.ext-link")];
    for (const sup of root.querySelectorAll("sup.cite:not([data-done])")) {
      sup.dataset.done = "1";
      const link = links[+sup.dataset.cite - 1];
      if (link) { sup.title = link.dataset.url; sup.classList.add("live"); sup.addEventListener("click", () => openUrl(link.dataset.url)); }
    }
  }

  function openUrl(url) { if (/^https?:\/\//.test(url)) api("/open", { url }).catch(() => {}); }

  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a.ext-link");
    if (!a) return;
    e.preventDefault();                 // never navigate LOKI's own window away
    openUrl(a.dataset.url || a.href);
  });

  return { render, decorate, chart, card, openCanvas, closeCanvas, copyText, button };
})();
window.Artifacts = Artifacts;

// app.js calls renderMarkdown(text) by name; this richer one keeps its escaping contract.
renderMarkdown = Artifacts.render;   // eslint-disable-line no-global-assign
