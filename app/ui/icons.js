// Icons in favour of words: LOKI's buttons and Settings sections show an icon; hover (or focus)
// one and a tooltip says its name and what it does. The words stay for screen readers
// (aria-label) and for the Settings search. Hand-drawn 24px line icons, no icon font, no CDN.
"use strict";

const ICON_PATHS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
  shield: '<path d="M12 3l7 3v5.5c0 4.4-3 8-7 9.5-4-1.5-7-5.1-7-9.5V6z"/><path d="M8.8 12.2l2.2 2.2 4.3-4.6"/>',
  update: '<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 3.5V8h4.5"/><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 20.5V16h-4.5"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
  ask: '<path d="M4 5.5h16v10H9l-4.5 4v-4H4z"/><path d="M10 9a2 2 0 1 1 2.6 1.9c-.4.2-.6.5-.6.9v.4"/><path d="M12 13.6v.1"/>',
  plan: '<path d="M9 6.5h11M9 12h11M9 17.5h11"/><path d="M4 6.5h1M4 12h1M4 17.5h1"/>',
  build: '<path d="M14.5 4.5l5 5-2 2-5-5z"/><path d="M13.5 8.5L4.5 17.5l2 2 9-9"/>',
  layers: '<path d="M12 3.5l9 4.8-9 4.8-9-4.8z"/><path d="M3 12.5l9 4.8 9-4.8"/><path d="M3 16.5l9 4.8 9-4.8"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  send: '<path d="M12 19.5V5M6 11l6-6 6 6"/>',
  broom: '<path d="M14 3l-3.5 9"/><path d="M6.5 12h8l2 8.5h-12z"/><path d="M9 16l-.5 4.5M12 16v4.5"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  search: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5.5 5.5"/>',
  check: '<circle cx="12" cy="12" r="8.5"/><path d="M8 12.3l2.7 2.7L16.2 9.4"/>',
  sliders: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  plug: '<path d="M9 3v5M15 3v5"/><path d="M6.5 8h11v3a5.5 5.5 0 0 1-11 0z"/><path d="M12 16.5V21"/>',
  people: '<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19.5c.5-3.3 2.6-5 5.5-5s5 1.7 5.5 5"/><circle cx="17" cy="9.5" r="2.4"/><path d="M15.8 14.6c2.4.1 4 1.6 4.4 4.4"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/><path d="M12 3.5c2.4 2.4 3.6 5.2 3.6 8.5s-1.2 6.1-3.6 8.5c-2.4-2.4-3.6-5.2-3.6-8.5s1.2-6.1 3.6-8.5z"/>',
  monitors: '<rect x="2.5" y="4.5" width="12" height="9" rx="1"/><path d="M6.5 17h4M8.5 13.5V17"/><rect x="16" y="7.5" width="5.5" height="12" rx="1"/>',
  chip: '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>',
  puzzle: '<path d="M5 8h3.2a2.3 2.3 0 1 1 4.6 0H16v3.2a2.3 2.3 0 1 1 0 4.6V19H5z"/>',
  image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="9.5" r="1.8"/><path d="M4 17.5l5-5 4 4 2.5-2.5 5 5"/>',
  brain: '<circle cx="6" cy="7" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="12" cy="12" r="2.2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="17.5" r="2"/><path d="M7.6 8.2l2.7 2.4M16.4 7.3l-2.8 3.1M10.3 13.4l-2.8 3.2M13.8 13.2l2.6 3"/>',
  play: '<path d="M7.5 5v14l11-7z"/>',
  flask: '<path d="M9.5 3.5h5M10.5 3.5v5.2L5 18.3c-.6 1 .1 2.2 1.3 2.2h11.4c1.2 0 1.9-1.2 1.3-2.2l-5.5-9.6V3.5"/><path d="M7.5 14.5h9"/>',
  contacts: '<rect x="4.5" y="3.5" width="15" height="17" rx="2"/><circle cx="12" cy="10" r="2.6"/><path d="M8 17c.6-2 2-3 4-3s3.4 1 4 3"/>',
  wrench: '<path d="M14.8 4.2a4.5 4.5 0 0 0-5.6 5.6L3.8 15.2l2.1 2.1 2.9 2.9 5.4-5.4a4.5 4.5 0 0 0 5.6-5.6l-2.9 2.9-2.8-.7-.7-2.8z"/>',
  book: '<path d="M4.5 5.5c2.5-1.3 5-1.3 7.5 0v14c-2.5-1.3-5-1.3-7.5 0z"/><path d="M12 5.5c2.5-1.3 5-1.3 7.5 0v14c-2.5-1.3-5-1.3-7.5 0z"/>',
  pen: '<path d="M15.5 4.5l4 4L8.5 19.5H4.5v-4z"/><path d="M13.5 6.5l4 4"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0"/><path d="M12 17.5V21M8.5 21h7"/>',
  speaker: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  speakerOff: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>',
  studio: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8.5 9l-2.5 2.5L8.5 14M15.5 9l2.5 2.5-2.5 2.5M13 8.5l-2 6M9 20.5h6"/>',
  coin: '<circle cx="12" cy="12" r="8.5"/><path d="M14.8 9.2c-.5-1-1.5-1.5-2.8-1.5-1.6 0-2.7.8-2.7 2 0 2.8 5.6 1.4 5.6 4.3 0 1.2-1.2 2.1-2.9 2.1-1.4 0-2.5-.6-3-1.6M12 6v1.7M12 16.1V18"/>',
};

function iconSvg(name) {
  return '<svg class="icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" '
    + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + (ICON_PATHS[name] || ICON_PATHS.plus) + "</svg>";
}

// [selector, icon, name, what it does]
const ICON_BUTTONS = [
  ["#new-chat", "plus", "New chat", "Start a fresh conversation with LOKI."],
  ["#open-settings", "gear", "Settings", "Connections, models, add-ons, machines, creations, the world and more."],
  ["#check-everything", "shield", "Check everything", "Prove every part of LOKI works together on this computer."],
  ["#update-banner-go", "update", "Update everything", "Update LOKI on every linked machine; each one restarts on the new version."],
  ["#update-banner-later", "clock", "Later", "Hide this until the next check."],
  ["#changed-banner-go", "eye", "Review and turn back on", "See what changed and switch it back on."],
  ["#changed-banner-later", "clock", "Later", "Hide this for now."],
  ['.modes [data-mode="ask"]', "ask", "Ask", "Answer questions; change nothing."],
  ['.modes [data-mode="plan"]', "plan", "Plan", "Read, ask, then write a plan; change nothing."],
  ['.modes [data-mode="build"]', "build", "Build", "Edit, run and verify - asks before anything risky."],
  [".bg-toggle", "layers", "Run in background", "Hand this message to a background agent and keep chatting."],
  ["#stop", "stop", "Stop", "Stop what LOKI is doing now."],
  ["#send", "send", "Send", "Send your message (Enter). Shift+Enter makes a new line."],
  [".sketch-open", "pen", "Draw", "Open the drawing pad: sketch something and LOKI looks at it with your next message."],
  ["#clear-jobs", "broom", "Clear finished", "Remove finished background jobs from this list."],
  ["#close-settings", "close", "Close", "Close Settings (Esc)."],
];

const TAB_ICONS = {
  system: ["check", "Check this computer: what works, what is missing and how to fix it."],
  general: ["sliders", "LOKI's options: the world's look, updates, keys you paste in, behaviour."],
  connections: ["plug", "Model providers and accounts: connect, test and pick models."],
  agents: ["people", "LOKI's agents and specialists: who does what, with which model."],
  world: ["globe", "LOKI World: the islands, your machines and the agents at work."],
  machines: ["monitors", "Your computers running LOKI, linked together, and updating them all."],
  models: ["chip", "Models that run on this computer (Ollama, MLX): install and test them."],
  capabilities: ["puzzle", "Add-ons: extra powers LOKI can install and use."],
  creations: ["image", "Everything LOKI made for you - pictures, videos, sketches, games - and make more."],
  brain: ["brain", "Everything LOKI knows as one map; edit or forget what it remembers."],
  play: ["play", "Games made with LOKI's Pixel Engine."],
  lab: ["flask", "LOKI improving itself, one tested change at a time."],
  crm: ["contacts", "People and companies LOKI keeps track of for you."],
  tools: ["wrench", "Every tool LOKI's agents can use, by category."],
  memory: ["book", "What LOKI remembers: search, edit, forget."],
  usage: ["coin", "What your messages cost, per model and per day."],
};

let tipBox = null, tipTimer = 0;

function showTip(target) {
  const name = target.dataset.tipName, what = target.dataset.tipWhat;
  if (!name) return;
  if (!tipBox) {
    tipBox = document.createElement("div");
    tipBox.className = "icon-tip";
    tipBox.setAttribute("role", "tooltip");
    document.body.append(tipBox);
  }
  tipBox.replaceChildren();
  const b = document.createElement("b"); b.textContent = name;
  tipBox.append(b);
  if (what) { const s = document.createElement("span"); s.textContent = what; tipBox.append(s); }
  tipBox.hidden = false;
  const r = target.getBoundingClientRect(), tw = tipBox.offsetWidth, th = tipBox.offsetHeight;
  const side = target.closest(".settings-nav, .sidebar");   // rails: the tip goes to the right
  let x, y;
  if (side) { x = r.right + 10; y = r.top + r.height / 2 - th / 2; }
  else { x = r.left + r.width / 2 - tw / 2; y = r.top - th - 8; if (y < 6) y = r.bottom + 8; }
  x = Math.max(6, Math.min(window.innerWidth - tw - 6, x));
  y = Math.max(6, Math.min(window.innerHeight - th - 6, y));
  tipBox.style.transform = "translate(" + Math.round(x) + "px," + Math.round(y) + "px)";
}

function hideTip() { clearTimeout(tipTimer); if (tipBox) tipBox.hidden = true; }

function tipTarget(e) { return e.target && e.target.closest ? e.target.closest("[data-tip-name]") : null; }

function makeIcon(node, icon, name, what) {
  if (!node || node.dataset.iconDone) return;
  node.dataset.iconDone = "1";
  node.dataset.tipName = name;
  node.dataset.tipWhat = what || "";
  node.setAttribute("aria-label", name);
  node.removeAttribute("title");   // the tooltip replaces the slow native one
  node.classList.add("icon-btn");
  if (node.matches("label")) {   // a checkbox label: keep the box (hidden), show the icon as a toggle
    const box = node.querySelector("input");
    node.replaceChildren();
    if (box) { node.append(box); box.classList.add("icon-check"); box.setAttribute("aria-label", name); }
    node.insertAdjacentHTML("beforeend", iconSvg(icon));
    return;
  }
  node.innerHTML = iconSvg(icon);
}

function iconizeTabs() {
  for (const tab of document.querySelectorAll(".settings-nav .tabs button[data-tab]")) {
    if (tab.dataset.iconDone) continue;
    const spec = TAB_ICONS[tab.dataset.tab];
    if (!spec) continue;
    const label = [...tab.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim();
    for (const n of [...tab.childNodes]) if (n.nodeType === 3) n.remove();
    const ico = tab.querySelector(".ico") || document.createElement("span");
    ico.className = "ico"; ico.innerHTML = iconSvg(spec[0]);
    if (!ico.parentNode) tab.prepend(ico);
    const words = document.createElement("span");
    words.className = "tab-label"; words.textContent = label;   // kept for search and screen readers
    ico.after(words);
    tab.dataset.iconDone = "1";
    tab.dataset.tipName = label;
    tab.dataset.tipWhat = spec[1];
    tab.setAttribute("aria-label", label);
  }
}

function iconizeAll() {
  for (const [sel, icon, name, what] of ICON_BUTTONS) document.querySelectorAll(sel).forEach((n) => makeIcon(n, icon, name, what));
  iconizeTabs();
  // buttons made later by other scripts opt in with data-icon / data-tip-name
  for (const n of document.querySelectorAll("button[data-icon]:not([data-icon-done])")) {
    makeIcon(n, n.dataset.icon, n.dataset.tipName || n.textContent.trim(), n.dataset.tipWhat || "");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.body.classList.add("icons-first");
  iconizeAll();
  const nav = document.querySelector(".settings-nav");
  const search = document.getElementById("settings-search");
  if (nav && search) {   // the rail's search is an icon that opens the field
    const find = document.createElement("button");
    find.type = "button"; find.className = "rail-search";
    nav.insertBefore(find, search);
    makeIcon(find, "search", "Search settings", "Find a setting by name or by anything shown in it.");
    find.addEventListener("click", () => { nav.classList.toggle("searching"); if (nav.classList.contains("searching")) search.focus(); });
    search.addEventListener("keydown", (e) => { if (e.key === "Escape" && !search.value) nav.classList.remove("searching"); });
  }
  let queued = false;   // new buttons appear as panels render: iconize them once per frame at most
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; iconizeAll(); });
  }).observe(document.body, { childList: true, subtree: true });
  document.addEventListener("mouseover", (e) => {
    const t = tipTarget(e);
    clearTimeout(tipTimer);
    if (t) tipTimer = setTimeout(() => showTip(t), 220); else hideTip();
  });
  document.addEventListener("focusin", (e) => { const t = tipTarget(e); if (t && t.matches(":focus-visible")) showTip(t); });
  document.addEventListener("focusout", hideTip);
  document.addEventListener("mousedown", hideTip);
  window.addEventListener("blur", hideTip);
});
