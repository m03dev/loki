// LOKI Spaces in the window: your own Discord, on LOKI home and over LOKI World (engine/spaces.py, docs/SPACES.md).
// Owner, 2026-10-19: "an open source discord or voip that's p2p - people make their own and host people - seamless in
// LOKI World, where people can chat and create lobbies ... reimagine the space ... replace discord, improve everything".
//
//   the rail      every space you host or joined, as a coloured stone on the left of the home screen / the World tab;
//                 + makes one or joins one with an invite code; unread dots; your name at the bottom
//   a space       rooms (text, voice) and LOBBIES (a voice + text room anyone opens for a game; they appear on the home
//                 screen over the live world, and "in LOKI World" lobbies take you into the World tab)
//   chat          end-to-end encrypted HERE (WebCrypto AES-GCM, a key derived from the space key): the engines only
//                 carry ciphertext. Replies, edits, deletes, reactions, typing, unread, @mentions
//   voice         WebRTC between the windows (peer to peer, DTLS-SRTP, a mesh); the offers / answers / candidates go
//                 through the host as ENCRYPTED signals. Mute, deafen, push-to-talk, who is speaking. The voice bar
//                 stays at the bottom wherever you go in LOKI.
// Plain DOM, CSP-safe (no inline script, textContent for everything anyone else wrote). Uses api(), el(), state.
"use strict";

const SP = {
  list: [], me: { name: "", color: "#8ccfc4" }, open: "", room: {}, data: {}, keys: {}, timer: 0, bgTimer: 0,
  voice: null, ptt: false, pttDown: false, reply: null, editing: null, built: false, lastTyping: 0,
};
const SP_REACTIONS = ["👍", "❤️", "😂", "🔥", "👀", "🎉"];
const SP_ICE = [{ urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] }, { urls: "stun:stun.cloudflare.com:3478" }];
const SP_STORE = "loki-spaces";

const spSvg = (name) => {
  const p = (typeof ICON_PATHS !== "undefined" && ICON_PATHS[name]) || SP_ICONS[name] || "";
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + p + "</svg>";
};
const SP_ICONS = {
  hash: '<path d="M9 4L7 20M17 4l-2 16M4.5 9h16M3.5 15h16"/>',
  speaker: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  lobby: '<circle cx="8" cy="9" r="2.6"/><circle cx="16" cy="9" r="2.6"/><path d="M3.5 18c.6-2.6 2.4-4 4.5-4s3.9 1.4 4.5 4M11.5 18c.6-2.6 2.4-4 4.5-4s3.9 1.4 4.5 4"/>',
  mic: '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5"/>',
  micoff: '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5M4 4l16 16"/>',
  head: '<path d="M4 15v-3a8 8 0 0 1 16 0v3"/><rect x="3.5" y="14" width="4" height="6" rx="1.5"/><rect x="16.5" y="14" width="4" height="6" rx="1.5"/>',
  headoff: '<path d="M4 15v-3a8 8 0 0 1 16 0v3"/><rect x="3.5" y="14" width="4" height="6" rx="1.5"/><rect x="16.5" y="14" width="4" height="6" rx="1.5"/><path d="M4 4l16 16"/>',
  hangup: '<path d="M3.5 14.5c4.5-4 12.5-4 17 0l-2 2.5-3.5-1.5V13a10 10 0 0 0-6 0v2.5L5.5 17z"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  reply: '<path d="M10 7L5 12l5 5"/><path d="M5 12h9a5 5 0 0 1 5 5v1"/>',
  pen: '<path d="M4 20l4.5-1 10-10-3.5-3.5-10 10z"/>',
  bin: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
  smile: '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 14c1.8 2 5.2 2 7 0M9 9.5h.01M15 9.5h.01"/>',
  out: '<path d="M14 4.5h5.5v15H14M10 8l-4 4 4 4M6 12h10"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.6 2.6 14.4 0 17M12 3.5c-2.6 2.6-2.6 14.4 0 17"/>',
  shrink: '<path d="M4 14h6v6M20 10h-6V4"/>',
  crown: '<path d="M4 17.5l1.5-9 4.5 4 2-6 2 6 4.5-4 1.5 9z"/>',
  dots: '<circle cx="6" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18" cy="12" r="1.2"/>',
};

function spB(icon, label, onClick, cls) {
  const b = el("button", "sp-ib" + (cls ? " " + cls : ""));
  b.type = "button"; b.innerHTML = spSvg(icon); b.title = label; b.setAttribute("aria-label", label);
  b.dataset.tipName = label;
  b.addEventListener("click", onClick);
  return b;
}
const spInitials = (name) => (String(name || "?").trim().split(/\s+/).map((w) => w[0]).join("").slice(0, 2) || "?").toUpperCase();
function spAvatar(name, color, size) {
  const a = el("span", "sp-av", spInitials(name));
  a.style.background = color || "#8ccfc4";
  if (size) a.style.setProperty("--s", size + "px");
  return a;
}
function spSay(text, bad) {
  const s = document.getElementById("sp-toast");
  if (!s) return;
  s.textContent = text || ""; s.classList.toggle("bad", !!bad); s.hidden = !text;
  clearTimeout(spSay.t);
  if (text) spSay.t = setTimeout(() => { s.hidden = true; }, bad ? 7000 : 3500);
}
function spLoad() { try { return JSON.parse(localStorage.getItem(SP_STORE) || "{}") || {}; } catch (_) { return {}; } }
function spSave(patch) { try { localStorage.setItem(SP_STORE, JSON.stringify(Object.assign(spLoad(), patch))); } catch (_) { /* private mode */ } }

// ------------------------------------------------------------------------------------------ end-to-end crypto
const b64u = {
  enc(buf) { let s = ""; const b = new Uint8Array(buf); for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]); return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); },
  dec(t) { t = String(t).replace(/-/g, "+").replace(/_/g, "/"); while (t.length % 4) t += "="; const s = atob(t), b = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) b[i] = s.charCodeAt(i); return b; },
};
async function spKey(sid) {
  if (SP.keys[sid]) return SP.keys[sid];
  const r = await api("/spaces/key?space=" + encodeURIComponent(sid));
  if (!r || !r.ok) throw new Error((r && r.error) || "no key");
  const base = await crypto.subtle.importKey("raw", b64u.dec(r.key), "HKDF", false, ["deriveKey"]);
  SP.keys[sid] = await crypto.subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: new TextEncoder().encode(sid), info: new TextEncoder().encode("loki-spaces enc v1") },
    base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  return SP.keys[sid];
}
async function spSeal(sid, obj, aad) {
  const key = await spKey(sid), iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: new TextEncoder().encode(sid + "|" + aad) }, key, new TextEncoder().encode(JSON.stringify(obj)));
  return { ct: b64u.enc(ct), iv: b64u.enc(iv) };
}
async function spOpen(sid, ev, aad) {
  try {
    const key = await spKey(sid);
    const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64u.dec(ev.iv), additionalData: new TextEncoder().encode(sid + "|" + aad) }, key, b64u.dec(ev.ct));
    return JSON.parse(new TextDecoder().decode(pt));
  } catch (_) { return null; }
}

// ------------------------------------------------------------------------------------------ the dock
function spBuild() {
  if (SP.built || !document.body) return;
  SP.built = true;
  const root = el("div", "sp-dock"); root.id = "spaces";
  const rail = el("nav", "sp-rail"); rail.id = "sp-rail"; rail.setAttribute("aria-label", "Spaces");
  const stones = el("div", "sp-stones"); stones.id = "sp-stones";
  const add = spB("plus", "Make or join a space", () => spDialog("new"), "sp-add");
  const me = el("button", "sp-me"); me.type = "button"; me.id = "sp-me"; me.title = "Your name in Spaces";
  me.addEventListener("click", () => spDialog("me"));
  rail.append(stones, add, me);
  const panel = el("section", "sp-panel"); panel.id = "sp-panel"; panel.hidden = true; panel.setAttribute("aria-label", "Space");
  const lobbies = el("div", "sp-lobbies"); lobbies.id = "sp-lobbies"; lobbies.setAttribute("aria-label", "Open lobbies");
  const toast = el("div", "sp-toast"); toast.id = "sp-toast"; toast.hidden = true; toast.setAttribute("role", "status");
  root.append(rail, panel, lobbies, toast);
  const bar = el("div", "sp-voicebar"); bar.id = "sp-voicebar"; bar.hidden = true;
  const audio = el("div", "sp-audio"); audio.id = "sp-audio"; audio.hidden = true;
  document.body.append(root, bar, audio);
  window.addEventListener("resize", spPlace);
  new MutationObserver(spPlace).observe(document.body, { attributes: true, attributeFilter: ["data-mode"] });
  const main = document.getElementById("main");
  if (main) new MutationObserver(spPlace).observe(main, { attributes: true, attributeFilter: ["class"] });
  document.addEventListener("keydown", spKeys, true);
  document.addEventListener("keyup", spKeys, true);
  spPlace();
}

// the dock sits on the home screen (over the live world) and on the World tab; the voice bar goes everywhere
function spPlace() {
  const root = document.getElementById("spaces");
  if (!root) return;
  const mode = document.body.dataset.mode || "loki", main = document.getElementById("main");
  const home = mode === "loki" && main && main.classList.contains("home") && !main.classList.contains("summoned");
  const world = mode === "world";
  const show = home || world || root.classList.contains("pinned");
  root.hidden = !show;
  root.classList.toggle("in-world", world);
  if (!show) return;
  let r = main ? main.getBoundingClientRect() : { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
  if (world) {   // over the game itself: the World tab's frame (world_godot/host.js lays the game on it)
    const frame = document.querySelector('[data-panel="world"] .world-frame');
    const fr = frame && frame.getBoundingClientRect();
    if (fr && fr.width > 200 && fr.height > 200) r = fr;
    else { const strip = document.getElementById("titlestrip"); r = { left: 0, top: strip ? strip.getBoundingClientRect().bottom : 0, right: innerWidth, bottom: innerHeight }; }
    if (frame && !SP.watched) { SP.watched = true; try { new ResizeObserver(spPlace).observe(frame); } catch (_) { /* old webview */ } }
  } else if (main) { const head = main.querySelector(".topbar, header"); if (head) r = { left: r.left, top: head.getBoundingClientRect().bottom, right: r.right, bottom: r.bottom }; }
  Object.assign(root.style, { left: r.left + "px", top: r.top + "px", width: Math.max(0, r.right - r.left) + "px", height: Math.max(0, r.bottom - r.top) + "px" });
}

function spRail() {
  const box = document.getElementById("sp-stones");
  if (!box) return;
  box.replaceChildren();
  for (const s of SP.list) {
    const b = el("button", "sp-stone" + (s.id === SP.open ? " on" : "") + (s.online ? "" : " off"));
    b.type = "button"; b.dataset.space = s.id;
    b.title = s.name + (s.hosted ? " (you host it)" : s.online ? "" : " (the host is offline)");
    b.style.setProperty("--c", s.color || "#8ccfc4");
    b.append(el("span", "sp-stone-t", s.icon || spInitials(s.name)));
    const d = SP.data[s.id];
    const unread = d ? spUnread(s.id) : 0;
    if (unread) b.append(el("i", "sp-dot" + (d && d.mention ? " at" : ""), unread > 99 ? "99+" : String(unread)));
    if (d && SP.voice && SP.voice.space === s.id) b.classList.add("voice");
    b.addEventListener("click", () => spOpenSpace(s.id === SP.open ? "" : s.id));
    box.append(b);
  }
  const me = document.getElementById("sp-me");
  if (me) { me.replaceChildren(spAvatar(SP.me.name, SP.me.color, 30)); me.title = SP.me.name + " - your name in Spaces"; }
}

async function spRefresh() {
  const r = await api("/spaces").catch(() => null);
  if (!r || !r.ok) return;
  SP.list = r.spaces || []; SP.me = r.me || SP.me; SP.serving = r.serving;
  if (SP.open && !SP.list.some((s) => s.id === SP.open)) spOpenSpace("");
  spRail();
}

// ------------------------------------------------------------------------------------------ syncing a space
function spState(sid) {
  if (!SP.data[sid]) SP.data[sid] = { seq: 0, space: null, members: [], msgs: new Map(), order: [], read: spLoad().read || {}, mention: false, busy: false };
  return SP.data[sid];
}

async function spSync(sid) {
  const d = spState(sid);
  if (d.busy) return;
  d.busy = true;
  try {
    const r = await api("/spaces/sync?space=" + encodeURIComponent(sid) + "&since=" + d.seq);
    if (!r || !r.ok) { d.error = (r && r.error) || "offline"; if (sid === SP.open) spHeader(); return; }
    d.error = "";
    d.space = r.space; d.members = r.members || [];
    for (const ev of r.events || []) await spEvent(sid, d, ev);
    d.seq = Math.max(d.seq, r.seq || 0);
    for (const sg of r.signals || []) spSignal(sid, sg);
    if (SP.voice && SP.voice.space === sid) spVoicePeers(d);
    if (sid === SP.open) spRender();
    spRail();
    spLobbies();
  } finally { d.busy = false; }
}

async function spEvent(sid, d, ev) {
  if (ev.kind === "msg") {
    const body = await spOpen(sid, ev, ev.room);
    const m = { seq: ev.seq, room: ev.room, from: ev.from, ts: ev.ts, text: body ? String(body.t || "") : null, reply: ev.reply || 0,
      reactions: {}, bot: ev.bot || "" };
    d.msgs.set(ev.seq, m); d.order.push(ev.seq);
    if (body && ev.from !== spMe(sid) && SP.me.name && new RegExp("@" + SP.me.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i").test(m.text)
      && (SP.open !== sid || SP.room[sid] !== ev.room || document.hidden)) d.mention = true;
  } else if (ev.kind === "edit") {
    const m = d.msgs.get(ev.target), body = await spOpen(sid, ev, ev.room);
    if (m && body && m.from === ev.from) { m.text = String(body.t || ""); m.edited = true; }
  } else if (ev.kind === "del") {
    const m = d.msgs.get(ev.target);
    if (m) { m.deleted = true; m.text = ""; }
  } else if (ev.kind === "react") {
    const m = d.msgs.get(ev.target);
    if (m) { const set = new Set(m.reactions[ev.emoji] || []); if (ev.on) set.add(ev.from); else set.delete(ev.from); m.reactions[ev.emoji] = [...set]; }
  } else if (ev.kind === "sys") {
    d.msgs.set(ev.seq, { seq: ev.seq, room: ev.room, from: ev.from, ts: ev.ts, sys: ev.text, reactions: {} }); d.order.push(ev.seq);
  }
  if (d.order.length > 3000) { for (const s of d.order.splice(0, d.order.length - 3000)) d.msgs.delete(s); }
}

const spMe = (sid) => { const s = SP.list.find((x) => x.id === sid); return s ? s.me : ""; };
const spMember = (sid, id) => (spState(sid).members.find((m) => m.id === id) || { name: "someone", color: "#777" });
function spUnread(sid) {
  const d = SP.data[sid];
  if (!d) return 0;
  let n = 0;
  for (const seq of d.order) { const m = d.msgs.get(seq); if (m && !m.sys && m.from !== spMe(sid) && seq > (d.read[sid + ":" + m.room] || 0)) n++; }
  return n;
}

function spLoop() {
  clearTimeout(SP.timer);
  const fast = SP.voice ? 700 : 1500;
  const go = async () => {
    const ids = new Set();
    if (SP.open) ids.add(SP.open);
    if (SP.voice) ids.add(SP.voice.space);
    await Promise.all([...ids].map((id) => spSync(id).catch(() => {})));
    SP.timer = setTimeout(go, document.hidden && !SP.voice ? 5000 : fast);
  };
  SP.timer = setTimeout(go, 50);
  clearInterval(SP.bgTimer);
  SP.bgTimer = setInterval(async () => {   // the other spaces: unread dots and lobbies, now and then
    await spRefresh();
    for (const s of SP.list) if (s.id !== SP.open && (!SP.voice || SP.voice.space !== s.id)) spSync(s.id).catch(() => {});
  }, 8000);
}

// ------------------------------------------------------------------------------------------ the open space
function spOpenSpace(sid) {
  SP.open = sid;
  const panel = document.getElementById("sp-panel");
  panel.hidden = !sid;
  document.getElementById("spaces").classList.toggle("open", !!sid);
  spRail();
  if (!sid) return;
  panel.replaceChildren();
  const head = el("header", "sp-head"); head.id = "sp-head";
  const cols = el("div", "sp-cols");
  const rooms = el("aside", "sp-rooms"); rooms.id = "sp-rooms";
  const chat = el("div", "sp-chat");
  const top = el("div", "sp-chat-top"); top.id = "sp-chat-top";
  const log = el("div", "sp-log"); log.id = "sp-log"; log.setAttribute("role", "log"); log.setAttribute("aria-live", "polite");
  const typing = el("div", "sp-typing"); typing.id = "sp-typing";
  const comp = el("div", "sp-compose"); comp.id = "sp-compose";
  const ctx = el("div", "sp-ctx"); ctx.id = "sp-ctx"; ctx.hidden = true;
  const ta = document.createElement("textarea"); ta.id = "sp-input"; ta.rows = 1; ta.maxLength = 4000; ta.setAttribute("aria-label", "Message");
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); spSend(); }
    else if (e.key === "Escape") { SP.reply = null; SP.editing = null; spCtx(); }
    else if (e.key === "ArrowUp" && !ta.value) spEditLast();
  });
  ta.addEventListener("input", () => {
    ta.style.height = "auto"; ta.style.height = Math.min(160, ta.scrollHeight) + "px";
    if (Date.now() - SP.lastTyping > 3000 && ta.value) { SP.lastTyping = Date.now(); api("/spaces/act", { space: sid, action: "typing", room: SP.room[sid] }).catch(() => {}); }
  });
  comp.append(ctx, ta, spB("reply", "Send (Enter)", () => spSend(), "sp-send"));
  chat.append(top, log, typing, comp);
  const people = el("aside", "sp-people"); people.id = "sp-people";
  cols.append(rooms, chat, people);
  panel.append(head, cols);
  spState(sid);
  spRender();
  spSync(sid);
  spLoop();
}

function spHeader() {
  const head = document.getElementById("sp-head"), sid = SP.open, d = SP.data[sid], s = SP.list.find((x) => x.id === sid);
  if (!head || !s) return;
  head.replaceChildren();
  const name = el("h3", "sp-title", (d && d.space && d.space.name) || s.name);
  const sub = el("span", "sp-sub", s.hosted ? "you host it · peer to peer" : d && d.error ? d.error : "hosted by " + spOwnerName(sid));
  if (d && d.error) sub.classList.add("bad");
  const tools = el("div", "sp-tools");
  tools.append(spB("link", "Invite people (copy the invite code)", () => spInvite(sid)),
    spB("lobby", "Open a lobby (voice + chat, for a game or a hangout)", () => spDialog("lobby")),
    spB("dots", s.hosted ? "Space settings" : "Leave or tidy", () => spDialog("settings")),
    spB("shrink", "Close (Esc)", () => spOpenSpace("")));
  head.append(el("span", "sp-lock", ""), name, sub, tools);
}
const spOwnerName = (sid) => { const d = SP.data[sid]; if (!d || !d.space) return "…"; return spMember(sid, d.space.owner).name; };

function spRender() {
  const sid = SP.open, d = SP.data[sid];
  if (!sid || !d) return;
  spHeader();
  const rooms = (d.space && d.space.rooms) || [];
  if (!SP.room[sid] || !rooms.some((r) => r.id === SP.room[sid] && r.kind === "text" || r.id === SP.room[sid] && r.kind === "lobby")) {
    const first = rooms.find((r) => r.kind === "text");
    if (first) SP.room[sid] = first.id;
  }
  spRooms(sid, d, rooms);
  spLog(sid, d, rooms.find((r) => r.id === SP.room[sid]));
  spPeople(sid, d);
}

function spRooms(sid, d, rooms) {
  const box = document.getElementById("sp-rooms");
  if (!box) return;
  box.replaceChildren();
  const me = spMe(sid), role = d.space && d.space.me ? d.space.me.role : "member";
  const voiceIn = (rid) => d.members.filter((m) => m.online && m.voice && m.voice.room === rid);
  for (const [kind, title] of [["text", "Text"], ["voice", "Voice"], ["lobby", "Lobbies"]]) {
    const list = rooms.filter((r) => r.kind === kind);
    if (!list.length && kind !== "lobby") continue;
    const h = el("div", "sp-group");
    h.append(el("span", "", title));
    if (kind === "lobby" || role === "owner" || role === "admin") {
      h.append(spB("plus", kind === "lobby" ? "Open a lobby" : "Add a " + kind + " room", () => spDialog(kind === "lobby" ? "lobby" : "room", { kind })));
    }
    box.append(h);
    for (const r of list) {
      const row = el("button", "sp-room" + (SP.room[sid] === r.id ? " on" : "") + (SP.voice && SP.voice.room === r.id ? " live" : ""));
      row.type = "button"; row.dataset.room = r.id; row.dataset.kind = r.kind;
      row.innerHTML = spSvg(kind === "text" ? "hash" : kind === "voice" ? "speaker" : "lobby");
      row.append(el("span", "sp-room-n", r.name));
      const unread = kind === "text" || kind === "lobby" ? d.order.filter((s) => { const m = d.msgs.get(s); return m && m.room === r.id && !m.sys && m.from !== me && s > (d.read[sid + ":" + r.id] || 0); }).length : 0;
      if (unread && SP.room[sid] !== r.id) row.append(el("i", "sp-dot", String(unread)));
      if (r.kind === "lobby") row.append(el("span", "sp-room-a", (r.activity || "") + " · " + voiceIn(r.id).length + "/" + (r.cap || 8)));
      row.addEventListener("click", () => {
        if (r.kind === "voice") { spJoinVoice(sid, r.id); return; }
        SP.room[sid] = r.id; SP.reply = null; SP.editing = null; spRender();
        if (r.kind === "lobby" && (!SP.voice || SP.voice.room !== r.id)) spJoinVoice(sid, r.id);
      });
      box.append(row);
      const inside = voiceIn(r.id);
      if (inside.length) {
        const who = el("div", "sp-room-who");
        for (const m of inside) {
          const p = el("span", "sp-vp" + (m.voice.speaking || spSpeaking(m.id) ? " talk" : "") + (m.voice.muted ? " muted" : ""));
          p.append(spAvatar(m.name, m.color, 20), el("span", "", m.name));
          if (m.voice.muted) { const ic = el("i", "sp-mi"); ic.innerHTML = spSvg("micoff"); p.append(ic); }
          who.append(p);
        }
        box.append(who);
      }
    }
  }
}

function spFmtTime(ts) {
  const t = new Date(ts * 1000), now = new Date();
  const hm = t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return t.toDateString() === now.toDateString() ? hm : t.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + hm;
}

// a message's text: plain text with links and @mentions picked out (never innerHTML)
function spText(node, text) {
  const re = /(https?:\/\/[^\s<>"']+|@[\w.-]{2,40})/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) node.append(document.createTextNode(text.slice(last, m.index)));
    if (m[0][0] === "@") node.append(el("span", "sp-at" + (m[0].slice(1).toLowerCase() === (SP.me.name || "").toLowerCase() ? " me" : ""), m[0]));
    else { const a = el("a", "sp-a", m[0]); a.href = m[0]; a.target = "_blank"; a.rel = "noopener noreferrer"; node.append(a); }
    last = m.index + m[0].length;
  }
  if (last < text.length) node.append(document.createTextNode(text.slice(last)));
}

function spLog(sid, d, room) {
  const log = document.getElementById("sp-log"), top = document.getElementById("sp-chat-top");
  if (!log) return;
  if (top) {
    top.replaceChildren();
    if (room) {
      top.innerHTML = spSvg(room.kind === "lobby" ? "lobby" : "hash");
      const where = room.world && !/loki world/i.test(room.activity || "") ? " · meets in LOKI World" : "";
      top.append(el("b", "", room.name), el("span", "sp-topic", room.kind === "lobby" ? (room.activity || "") + where : room.topic || ""));
      if (room.kind === "lobby" && room.world) top.append(spB("globe", "Go into LOKI World with this lobby", () => { if (window.LokiModeBar) LokiModeBar.go("world"); }));
    }
  }
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
  log.replaceChildren();
  if (!room) return;
  const me = spMe(sid), role = d.space && d.space.me ? d.space.me.role : "member";
  let prev = null;
  const seqs = d.order.filter((s) => { const m = d.msgs.get(s); return m && m.room === room.id; });
  if (!seqs.length) log.append(el("p", "sp-empty", "Nothing here yet. Say hello - only the people in this space can read it (end-to-end encrypted)."));
  for (const seq of seqs) {
    const m = d.msgs.get(seq);
    if (m.sys) { log.append(el("div", "sp-sys", spMember(sid, m.from).name + " " + m.sys)); prev = null; continue; }
    const who = spMember(sid, m.from);
    const grouped = prev && prev.from === m.from && m.ts - prev.ts < 300 && !m.reply;
    const row = el("div", "sp-msg" + (grouped ? " grouped" : "") + (m.from === me ? " mine" : "") + (m.text && SP.me.name && m.text.toLowerCase().includes("@" + SP.me.name.toLowerCase()) ? " mention" : ""));
    row.dataset.seq = String(seq);
    if (!grouped) row.append(spAvatar(m.bot || who.name, who.color, 34));
    else row.append(el("span", "sp-gut", spFmtTime(m.ts).slice(-5)));
    const body = el("div", "sp-body");
    if (m.reply) {
      const r = d.msgs.get(m.reply);
      const q = el("div", "sp-quote");
      q.append(el("b", "", r ? spMember(sid, r.from).name : "a message"), document.createTextNode(" " + (r && r.text ? r.text.slice(0, 90) : "…")));
      body.append(q);
    }
    if (!grouped) {
      const meta = el("div", "sp-meta");
      const n = el("b", "", m.bot ? m.bot : who.name); n.style.color = who.color;
      meta.append(n);
      if (m.bot) meta.append(el("span", "sp-tag", "via " + who.name));
      if (who.role === "owner") { const c = el("i", "sp-crown"); c.innerHTML = spSvg("crown"); c.title = "Owner"; meta.append(c); }
      meta.append(el("span", "sp-time", spFmtTime(m.ts)));
      body.append(meta);
    }
    const text = el("div", "sp-text" + (m.deleted ? " gone" : ""));
    if (m.deleted) text.textContent = "message deleted";
    else if (m.text === null) text.textContent = "🔒 could not be decrypted (a different key)";
    else spText(text, m.text);
    if (m.edited && !m.deleted) text.append(el("span", "sp-edited", " (edited)"));
    body.append(text);
    const reacts = Object.entries(m.reactions || {}).filter(([, who_]) => who_.length);
    if (reacts.length) {
      const rr = el("div", "sp-reacts");
      for (const [emo, who_] of reacts) {
        const b = el("button", "sp-react" + (who_.includes(me) ? " on" : ""), emo + " " + who_.length);
        b.type = "button"; b.title = who_.map((x) => spMember(sid, x).name).join(", ");
        b.addEventListener("click", () => spAct(sid, "react", { target: seq, emoji: emo, on: !who_.includes(me) }));
        rr.append(b);
      }
      body.append(rr);
    }
    row.append(body);
    if (!m.deleted) {
      const hover = el("div", "sp-hover");
      for (const emo of SP_REACTIONS.slice(0, 4)) {
        const b = el("button", "sp-hv", emo); b.type = "button"; b.title = "React " + emo;
        b.addEventListener("click", () => spAct(sid, "react", { target: seq, emoji: emo, on: !(m.reactions[emo] || []).includes(me) }));
        hover.append(b);
      }
      hover.append(spB("reply", "Reply", () => { SP.reply = seq; SP.editing = null; spCtx(); document.getElementById("sp-input").focus(); }));
      if (m.from === me) hover.append(spB("pen", "Edit (↑ in an empty box)", () => spStartEdit(seq)));
      if (m.from === me || role === "owner" || role === "admin") hover.append(spB("bin", "Delete", () => spAct(sid, "delete", { target: seq })));
      row.append(hover);
    }
    log.append(row);
    prev = m;
  }
  if (atBottom || !log.dataset.room || log.dataset.room !== room.id) log.scrollTop = log.scrollHeight;
  log.dataset.room = room.id;
  const last = seqs[seqs.length - 1] || 0;
  if (last && !document.hidden) { d.read[sid + ":" + room.id] = last; d.mention = false; spSave({ read: Object.assign(spLoad().read || {}, d.read) }); }
  const typing = d.members.filter((x) => x.typing === room.id && x.id !== me).map((x) => x.name);
  const tbox = document.getElementById("sp-typing");
  if (tbox) tbox.textContent = typing.length ? typing.join(", ") + (typing.length > 1 ? " are" : " is") + " typing…" : "";
  const input = document.getElementById("sp-input");
  if (input) input.placeholder = "Message " + (room.kind === "lobby" ? "the lobby" : "#" + room.name) + " - Enter sends, Shift+Enter a new line";
}

function spPeople(sid, d) {
  const box = document.getElementById("sp-people");
  if (!box) return;
  box.replaceChildren();
  const me = spMe(sid), myRole = d.space && d.space.me ? d.space.me.role : "member";
  const on = d.members.filter((m) => m.online), off = d.members.filter((m) => !m.online);
  for (const [title, list] of [["Online", on], ["Offline", off]]) {
    if (!list.length) continue;
    box.append(el("div", "sp-group", title + " — " + list.length));
    for (const m of list.sort((a, b) => ({ owner: 0, admin: 1 }[a.role] ?? 2) - ({ owner: 0, admin: 1 }[b.role] ?? 2) || a.name.localeCompare(b.name))) {
      const row = el("div", "sp-person" + (m.online ? "" : " off"));
      row.append(spAvatar(m.name, m.color, 26), el("span", "sp-pn", m.name + (m.id === me ? " (you)" : "")));
      if (m.role !== "member") row.append(el("span", "sp-role", m.role));
      if (m.voice) { const v = el("i", "sp-mi"); v.innerHTML = spSvg("speaker"); v.title = "in voice"; row.append(v); }
      if (m.id !== me && m.role !== "owner" && (myRole === "owner" || (myRole === "admin" && m.role !== "admin"))) {
        const more = spB("dots", "Moderate " + m.name, () => spDialog("mod", { member: m }));
        more.classList.add("sp-more"); row.append(more);
      }
      box.append(row);
    }
  }
}

function spCtx() {
  const box = document.getElementById("sp-ctx"), d = SP.data[SP.open];
  if (!box || !d) return;
  const seq = SP.editing || SP.reply, m = seq && d.msgs.get(seq);
  box.hidden = !m;
  box.replaceChildren();
  if (!m) return;
  box.append(el("span", "", (SP.editing ? "Editing" : "Replying to " + spMember(SP.open, m.from).name) + " · Esc cancels"));
  if (SP.editing) document.getElementById("sp-input").value = m.text || "";
}
function spStartEdit(seq) { SP.editing = seq; SP.reply = null; spCtx(); const i = document.getElementById("sp-input"); i.focus(); }
function spEditLast() {
  const sid = SP.open, d = SP.data[sid], me = spMe(sid);
  for (let i = d.order.length - 1; i >= 0; i--) { const m = d.msgs.get(d.order[i]); if (m && m.from === me && m.room === SP.room[sid] && !m.deleted && !m.sys) { spStartEdit(m.seq); return; } }
}

async function spAct(sid, action, body) {
  const r = await api("/spaces/act", Object.assign({ space: sid, action }, body)).catch(() => null);
  if (!r || !r.ok) { spSay((r && r.error) || "That did not go through.", true); return null; }
  spSync(sid);
  return r;
}

async function spSend() {
  const sid = SP.open, input = document.getElementById("sp-input"), room = SP.room[sid];
  const text = input.value.trim();
  if (!sid || !room || !text) return;
  input.value = ""; input.style.height = "auto";
  const sealed = await spSeal(sid, { t: text }, room);
  if (SP.editing) {
    const seq = SP.editing; SP.editing = null; spCtx();
    await spAct(sid, "edit", Object.assign({ target: seq }, sealed));
    return;
  }
  const body = Object.assign({ room }, sealed);
  if (SP.reply) { body.reply = SP.reply; SP.reply = null; spCtx(); }
  const r = await spAct(sid, "send", body);
  if (!r) input.value = text;
}

async function spInvite(sid) {
  const r = await api("/spaces/invite?space=" + encodeURIComponent(sid)).catch(() => null);
  if (!r || !r.ok) { spSay((r && r.error) || "No invite.", true); return; }
  spDialog("invite", { code: r.code, hosts: r.hosts, relay: r.relay });
}

// ------------------------------------------------------------------------------------------ dialogs
function spDialog(kind, opt) {
  opt = opt || {};
  document.getElementById("sp-dlg")?.remove();
  const wrap = el("div", "sp-dlg"); wrap.id = "sp-dlg"; wrap.setAttribute("role", "dialog"); wrap.setAttribute("aria-modal", "true");
  const card = el("div", "sp-card");
  const close = () => wrap.remove();
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  wrap.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } });
  const field = (label, input) => { const l = el("label", "sp-field"); l.append(el("span", "", label), input); return l; };
  const inp = (val, ph, max) => { const i = document.createElement("input"); i.type = "text"; i.value = val || ""; i.placeholder = ph || ""; i.maxLength = max || 40; return i; };
  const go = (label, fn, cls) => { const b = el("button", "send sp-go" + (cls ? " " + cls : ""), label); b.type = "button"; b.addEventListener("click", fn); return b; };
  const sid = SP.open;
  if (kind === "new") {
    card.append(el("h3", "", "A space of your own"), el("p", "note", "Make one - your LOKI hosts it, peer to peer, no account and no company in the middle - or paste an invite someone gave you."));
    const nm = inp("", "Night Owls"), code = document.createElement("textarea"); code.rows = 3; code.placeholder = "loki-space:…";
    code.className = "sp-code";
    const colors = el("div", "sp-swatches"); let color = "#7fcfc2";
    for (const c of ["#7fcfc2", "#a596c4", "#e0a96d", "#8fb3d9", "#d98ca0", "#9cc98a", "#e6c76a", "#c79be0"]) {
      const b = el("button", "sp-sw" + (c === color ? " on" : "")); b.type = "button"; b.style.background = c; b.setAttribute("aria-label", "Colour " + c);
      b.addEventListener("click", () => { color = c; for (const x of colors.children) x.classList.toggle("on", x === b); });
      colors.append(b);
    }
    const make = go("Make it", async () => {
      const r = await api("/spaces/create", { name: nm.value.trim() || "My space", color }).catch(() => null);
      if (!r || !r.ok) { spSay((r && r.error) || "Could not make it.", true); return; }
      close(); await spRefresh(); spOpenSpace(r.space.id); spInvite(r.space.id);
    });
    const join = go("Join", async () => {
      join.disabled = true; join.textContent = "Joining…";
      const r = await api("/spaces/join", { code: code.value.trim() }).catch(() => null);
      join.disabled = false; join.textContent = "Join";
      if (!r || !r.ok) { spSay((r && r.error) || "Could not join.", true); return; }
      close(); await spRefresh(); spOpenSpace(r.space.id);
    }, "quiet");
    const a = el("div", "sp-half"), b = el("div", "sp-half");
    a.append(el("h4", "", "Make a space"), field("Name", nm), colors, make);
    b.append(el("h4", "", "Join with an invite"), code, join);
    const row = el("div", "sp-two"); row.append(a, b);
    card.append(row);
    setTimeout(() => nm.focus(), 0);
  } else if (kind === "invite") {
    card.append(el("h3", "", "Invite people"), el("p", "note", "Send this code to whoever you want in. Their LOKI joins your LOKI directly - on your network, or through the free public relay when they are elsewhere. Anyone with the code can join, so share it like a key; lock the space in its settings when everyone is in."));
    const code = document.createElement("textarea"); code.readOnly = true; code.rows = 4; code.value = opt.code; code.className = "sp-code";
    const copy = go("Copy the invite", async () => {
      try { await navigator.clipboard.writeText(opt.code); copy.textContent = "Copied"; } catch (_) { code.select(); document.execCommand && document.execCommand("copy"); copy.textContent = "Copied"; }
    });
    const where = el("p", "note sp-where", "Reachable at: " + (opt.hosts || []).filter((h) => !h.startsWith("127.")).join(" · ")
      + (opt.relay && opt.relay.publishing ? " (relay live)" : opt.relay && opt.relay.error ? " (relay: " + opt.relay.error + ")" : ""));
    card.append(code, copy, where);
    setTimeout(() => code.select(), 0);
  } else if (kind === "me") {
    card.append(el("h3", "", "You, in Spaces"), el("p", "note", "The name and colour everyone in your spaces sees."));
    const nm = inp(SP.me.name, "your name");
    const col = document.createElement("input"); col.type = "color"; col.value = SP.me.color || "#8ccfc4";
    const ptt = document.createElement("input"); ptt.type = "checkbox"; ptt.checked = !!spLoad().ptt;
    const turn = inp(spLoad().turn || "", "turn:user:pass@host:3478 (optional)", 200);
    card.append(field("Name", nm), field("Colour", col));
    const l = el("label", "sp-check"); l.append(ptt, el("span", "", "Push to talk (hold the backquote ` key)")); card.append(l);
    card.append(field("Your own TURN server, for voice through strict networks", turn));
    card.append(go("Save", async () => {
      await api("/spaces/profile", { name: nm.value.trim(), color: col.value });
      spSave({ ptt: ptt.checked, turn: turn.value.trim() }); SP.ptt = ptt.checked;
      close(); spRefresh();
    }));
  } else if (kind === "lobby" || kind === "room") {
    const isLobby = kind === "lobby";
    card.append(el("h3", "", isLobby ? "Open a lobby" : "Add a room"), el("p", "note", isLobby
      ? "Voice and chat for a game or a hangout. It shows on everyone's LOKI home and goes away by itself when the last person leaves."
      : "A text room for talking in writing, or a voice room people drop into."));
    const nm = inp("", isLobby ? "Raid night" : "general");
    card.append(field("Name", nm));
    let kindSel = null, act = null, cap = null, world = null;
    if (isLobby) {
      act = inp("LOKI World", "what you are doing");
      cap = document.createElement("input"); cap.type = "number"; cap.min = "2"; cap.max = "25"; cap.value = "8";
      world = document.createElement("input"); world.type = "checkbox"; world.checked = true;
      const l = el("label", "sp-check"); l.append(world, el("span", "", "Meet in LOKI World (everyone in the lobby goes there)"));
      card.append(field("Activity", act), field("How many", cap), l);
    } else {
      kindSel = document.createElement("select");
      for (const [v, t] of [["text", "Text"], ["voice", "Voice"]]) { const o = el("option", "", t); o.value = v; kindSel.append(o); }
      kindSel.value = opt.kind === "voice" ? "voice" : "text";
      card.append(field("Kind", kindSel));
    }
    card.append(go(isLobby ? "Open it" : "Add it", async () => {
      const body = { op: "add", kind: isLobby ? "lobby" : kindSel.value, name: nm.value.trim() };
      if (isLobby) Object.assign(body, { activity: act.value.trim(), cap: +cap.value || 8, world: world.checked });
      const r = await spAct(sid, "room", body);
      if (!r) return;
      close();
      if (isLobby && r.room) { SP.room[sid] = r.room.id; await spSync(sid); spJoinVoice(sid, r.room.id); if (world.checked && window.LokiModeBar) LokiModeBar.go("world"); }
    }));
    setTimeout(() => nm.focus(), 0);
  } else if (kind === "mod") {
    const m = opt.member;
    card.append(el("h3", "", m.name));
    const d = SP.data[sid], mine = d.space.me.role;
    const row = el("div", "sp-acts");
    if (mine === "owner") row.append(go(m.role === "admin" ? "Make a member" : "Make an admin", async () => { await spAct(sid, "mod", { member: m.id, op: m.role === "admin" ? "member" : "admin" }); close(); }, "quiet"));
    row.append(go("Kick", async () => { await spAct(sid, "mod", { member: m.id, op: "kick" }); close(); }, "quiet"),
      go("Ban", async () => { await spAct(sid, "mod", { member: m.id, op: "ban" }); close(); }, "danger"));
    card.append(el("p", "note", "Kick: out, but they can come back with the invite. Ban: out for good."), row);
  } else if (kind === "settings") {
    const s = SP.list.find((x) => x.id === sid), d = SP.data[sid];
    card.append(el("h3", "", (d && d.space && d.space.name) || s.name));
    if (s.hosted) {
      const nm = inp(d.space.name, "name");
      const lock = document.createElement("input"); lock.type = "checkbox"; lock.checked = !!d.space.locked;
      const l = el("label", "sp-check"); l.append(lock, el("span", "", "Locked: no new members, even with the invite"));
      card.append(el("p", "note", "Your LOKI hosts this space: it is only reachable while LOKI runs on this machine. (Host it on the machine that is always on - your PC - so it never sleeps.)"),
        field("Name", nm), l,
        go("Save", async () => {
          await spAct(sid, "space", { name: nm.value.trim() });
          if (!!d.space.locked !== lock.checked) await spAct(sid, "mod", { op: "lock", on: lock.checked });
          close();
        }),
        go("Delete the space", async () => {
          if (!confirm("Delete " + d.space.name + "? Everyone loses it. (It is kept on this disk, renamed.)")) return;
          await api("/spaces/forget", { space: sid }); close(); spOpenSpace(""); spRefresh();
        }, "danger"));
    } else {
      card.append(el("p", "note", "Hosted by " + spOwnerName(sid) + ". Leaving removes it from your rail; the invite brings you back."),
        go("Leave the space", async () => { await api("/spaces/forget", { space: sid }); close(); spOpenSpace(""); spRefresh(); }, "danger"));
    }
  }
  card.append(spB("close", "Close", close, "sp-x"));
  wrap.append(card);
  (document.getElementById("spaces") || document.body).append(wrap);
}

// ------------------------------------------------------------------------------------------ lobbies over the world
function spLobbies() {
  const box = document.getElementById("sp-lobbies");
  if (!box) return;
  box.replaceChildren();
  const cards = [];
  for (const s of SP.list) {
    const d = SP.data[s.id];
    if (!d || !d.space) continue;
    for (const r of d.space.rooms) {
      if (r.kind !== "lobby") continue;
      const inside = d.members.filter((m) => m.online && m.voice && m.voice.room === r.id);
      cards.push({ s, d, r, inside });
    }
  }
  box.hidden = !cards.length;
  for (const { s, r, inside } of cards.slice(0, 6)) {
    const c = el("div", "sp-lcard" + (SP.voice && SP.voice.room === r.id ? " live" : ""));
    c.style.setProperty("--c", s.color || "#8ccfc4");
    const t = el("div", "sp-lt");
    t.append(el("b", "", r.name), el("span", "", (r.activity || "Hanging out") + " · " + s.name));
    const faces = el("div", "sp-lf");
    for (const m of inside.slice(0, 6)) faces.append(spAvatar(m.name, m.color, 22));
    faces.append(el("span", "sp-lcap", inside.length + "/" + (r.cap || 8)));
    const join = el("button", "send small", SP.voice && SP.voice.room === r.id ? "In it" : "Join");
    join.type = "button"; join.disabled = !!(SP.voice && SP.voice.room === r.id);
    join.addEventListener("click", () => { SP.room[s.id] = r.id; spOpenSpace(s.id); spJoinVoice(s.id, r.id); if (r.world && window.LokiModeBar) LokiModeBar.go("world"); });
    c.append(t, faces, join);
    box.append(c);
  }
}

// ------------------------------------------------------------------------------------------ voice (WebRTC mesh)
function spIce() {
  const ice = SP_ICE.slice(), turn = spLoad().turn || "";
  const m = /^turns?:([^:@]+):([^@]+)@(.+)$/.exec(turn);
  if (m) ice.push({ urls: turn.split(":")[0] + ":" + m[3], username: m[1], credential: m[2] });
  return ice;
}

async function spJoinVoice(sid, rid) {
  if (SP.voice && SP.voice.room === rid) return;
  if (SP.voice) await spLeaveVoice();
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
  } catch (exc) {
    spSay("No microphone: " + exc.message + ". Allow LOKI to use the microphone (System Settings > Privacy > Microphone), or listen only.", true);
    stream = null;
  }
  const r = await api("/spaces/act", { space: sid, action: "voice", room: rid, muted: !stream }).catch(() => null);
  if (!r || !r.ok) { if (stream) stream.getTracks().forEach((t) => t.stop()); spSay((r && r.error) || "Could not join voice.", true); return; }
  SP.voice = { space: sid, room: rid, stream, peers: new Map(), muted: !stream, deaf: false, speaking: false, levels: new Map(), started: Date.now() };
  SP.ptt = !!spLoad().ptt;
  if (stream && SP.ptt) stream.getAudioTracks().forEach((t) => { t.enabled = false; });
  spMeter(stream, "me");
  for (const peer of r.peers || []) spCall(peer, true);     // the newcomer calls everyone already there
  spVoiceBar(); spLoop(); spSync(sid);
}

async function spLeaveVoice() {
  const v = SP.voice;
  if (!v) return;
  SP.voice = null;
  for (const [id, p] of v.peers) { try { await spSignalSend(v.space, id, { t: "bye" }); } catch (_) { /* */ } p.pc.close(); p.audio.remove(); }
  if (v.stream) v.stream.getTracks().forEach((t) => t.stop());
  if (v.ctx) v.ctx.close().catch(() => {});
  await api("/spaces/act", { space: v.space, action: "voice", room: null }).catch(() => {});
  spVoiceBar(); spSync(v.space); spLoop();
}

async function spSignalSend(sid, to, obj) {
  const sealed = await spSeal(sid, obj, "signal");
  return api("/spaces/act", Object.assign({ space: sid, action: "signal", to }, sealed));
}

function spPeer(id) {
  const v = SP.voice;
  let p = v.peers.get(id);
  if (p) return p;
  const pc = new RTCPeerConnection({ iceServers: spIce() });
  const audio = document.createElement("audio"); audio.autoplay = true; audio.dataset.peer = id;
  document.getElementById("sp-audio").append(audio);
  p = { pc, audio, pending: [], remoteSet: false };
  v.peers.set(id, p);
  if (v.stream) for (const t of v.stream.getAudioTracks()) pc.addTrack(t, v.stream);
  else pc.addTransceiver("audio", { direction: "recvonly" });
  pc.onicecandidate = (e) => { if (e.candidate) spSignalSend(v.space, id, { t: "ice", c: e.candidate.toJSON() }).catch(() => {}); };
  pc.ontrack = (e) => { audio.srcObject = e.streams[0] || new MediaStream([e.track]); audio.muted = !!(SP.voice && SP.voice.deaf); spMeter(audio.srcObject, id); };
  pc.onconnectionstatechange = () => {
    p.state = pc.connectionState;
    if (pc.connectionState === "failed") spSay("Voice could not reach someone directly (a strict network). A TURN server fixes that: You > TURN.", true);
    spVoiceBar();
  };
  return p;
}

async function spCall(id, initiate) {
  if (!SP.voice) return;
  const p = spPeer(id);
  if (!initiate) return;
  const offer = await p.pc.createOffer();
  await p.pc.setLocalDescription(offer);
  await spSignalSend(SP.voice.space, id, { t: "offer", sdp: p.pc.localDescription.sdp, room: SP.voice.room });
}

async function spSignal(sid, sg) {
  const v = SP.voice;
  const msg = await spOpen(sid, sg, "signal");
  if (!msg || !v || v.space !== sid) return;
  const from = sg.from;
  if (msg.t === "offer") {
    if (msg.room !== v.room) return;
    const p = spPeer(from);
    await p.pc.setRemoteDescription({ type: "offer", sdp: msg.sdp });
    p.remoteSet = true;
    for (const c of p.pending.splice(0)) await p.pc.addIceCandidate(c).catch(() => {});
    const ans = await p.pc.createAnswer();
    await p.pc.setLocalDescription(ans);
    await spSignalSend(sid, from, { t: "answer", sdp: p.pc.localDescription.sdp });
  } else if (msg.t === "answer") {
    const p = v.peers.get(from);
    if (!p) return;
    await p.pc.setRemoteDescription({ type: "answer", sdp: msg.sdp }).catch(() => {});
    p.remoteSet = true;
    for (const c of p.pending.splice(0)) await p.pc.addIceCandidate(c).catch(() => {});
  } else if (msg.t === "ice") {
    const p = v.peers.get(from) || spPeer(from);
    if (p.remoteSet) await p.pc.addIceCandidate(msg.c).catch(() => {}); else p.pending.push(msg.c);
  } else if (msg.t === "bye") {
    spDrop(from);
  }
}

function spDrop(id) {
  const v = SP.voice, p = v && v.peers.get(id);
  if (!p) return;
  p.pc.close(); p.audio.remove(); v.peers.delete(id); v.levels.delete(id);
  spVoiceBar();
}

// keep the mesh in step with who the host says is in the room
function spVoicePeers(d) {
  const v = SP.voice;
  if (!v) return;
  const here = new Set(d.members.filter((m) => m.online && m.voice && m.voice.room === v.room && m.id !== spMe(v.space)).map((m) => m.id));
  for (const id of [...v.peers.keys()]) if (!here.has(id)) spDrop(id);
  spVoiceBar();
}

// who is speaking: an analyser on each stream (mine and everyone's), drawn as a ring
function spMeter(stream, id) {
  const v = SP.voice;
  if (!v || !stream) return;
  try {
    v.ctx = v.ctx || new (window.AudioContext || window.webkitAudioContext)();
    const src = v.ctx.createMediaStreamSource(stream), an = v.ctx.createAnalyser();
    an.fftSize = 512; src.connect(an);
    const buf = new Uint8Array(an.fftSize);
    const tick = () => {
      if (SP.voice !== v) return;
      an.getByteTimeDomainData(buf);
      let s = 0; for (let i = 0; i < buf.length; i++) { const x = (buf[i] - 128) / 128; s += x * x; }
      const level = Math.sqrt(s / buf.length);
      const talking = level > 0.035 && !(id === "me" && v.muted);
      if (v.levels.get(id) !== talking) {
        v.levels.set(id, talking);
        if (id === "me" && Date.now() - (v.saidAt || 0) > 800) {
          v.saidAt = Date.now();
          api("/spaces/act", { space: v.space, action: "voice", room: v.room, muted: v.muted, deaf: v.deaf, speaking: talking }).catch(() => {});
        }
        spVoiceBar();
      }
      setTimeout(tick, 120);
    };
    tick();
  } catch (_) { /* no Web Audio: no rings */ }
}
const spSpeaking = (id) => !!(SP.voice && SP.voice.levels.get(id));

function spSetMute(on) {
  const v = SP.voice;
  if (!v || !v.stream) return;
  v.muted = on;
  v.stream.getAudioTracks().forEach((t) => { t.enabled = !on && (!SP.ptt || SP.pttDown); });
  api("/spaces/act", { space: v.space, action: "voice", room: v.room, muted: v.muted, deaf: v.deaf }).catch(() => {});
  spVoiceBar();
}
function spSetDeaf(on) {
  const v = SP.voice;
  if (!v) return;
  v.deaf = on;
  for (const a of document.querySelectorAll("#sp-audio audio")) a.muted = on;
  if (on && !v.muted) spSetMute(true); else api("/spaces/act", { space: v.space, action: "voice", room: v.room, muted: v.muted, deaf: v.deaf }).catch(() => {});
  spVoiceBar();
}

// the voice bar is built once per call and then only updated (rebuilding it every sync made its buttons jump)
function spVoiceBar() {
  const bar = document.getElementById("sp-voicebar"), v = SP.voice;
  if (!bar) return;
  bar.hidden = !v;
  document.body.classList.toggle("sp-voice-on", !!v);
  if (!v) { bar.replaceChildren(); delete bar.dataset.call; return; }
  if (bar.dataset.call !== String(v.started)) {
    bar.replaceChildren();
    bar.dataset.call = String(v.started);
    const info = el("div", "sp-vinfo"); info.id = "sp-vinfo";
    info.append(el("b", "sp-vlive"), el("span", "sp-vwhere"));
    info.addEventListener("click", () => {
      const vv = SP.voice; if (!vv) return;
      const d = SP.data[vv.space], room = d && d.space && d.space.rooms.find((r) => r.id === vv.room);
      if (room && room.kind === "lobby") SP.room[vv.space] = room.id;
      spOpenSpace(vv.space);
    });
    const faces = el("div", "sp-vfaces"); faces.id = "sp-vfaces";
    const mute = spB("mic", "Mute", () => spSetMute(!SP.voice.muted)); mute.id = "sp-vmute";
    const deaf = spB("head", "Deafen (hear nobody)", () => spSetDeaf(!SP.voice.deaf)); deaf.id = "sp-vdeaf";
    bar.append(info, faces, mute, deaf, spB("hangup", "Leave voice", () => spLeaveVoice(), "hang"));
  }
  const d = SP.data[v.space], room = d && d.space && d.space.rooms.find((r) => r.id === v.room);
  const s = SP.list.find((x) => x.id === v.space);
  const states = [...v.peers.values()].map((p) => p.state || "connecting");
  const ok = states.filter((x) => x === "connected").length;
  bar.querySelector(".sp-vlive").textContent = ok || !states.length ? "Voice connected" : "Connecting…";
  bar.querySelector(".sp-vwhere").textContent = (room ? room.name : "voice") + " / " + (s ? s.name : "");
  const faces = document.getElementById("sp-vfaces");
  const want = ["me", ...v.peers.keys()];
  if (faces.dataset.who !== want.join(",")) {
    faces.dataset.who = want.join(",");
    faces.replaceChildren();
    for (const id of want) {
      const m = id === "me" ? SP.me : spMember(v.space, id);
      const a = spAvatar(m.name, m.color, 24); a.dataset.who = id; a.title = m.name; faces.append(a);
    }
  }
  for (const a of faces.children) a.classList.toggle("talk", spSpeaking(a.dataset.who));
  const mute = document.getElementById("sp-vmute"), deaf = document.getElementById("sp-vdeaf");
  mute.innerHTML = spSvg(v.muted ? "micoff" : "mic"); mute.classList.toggle("bad", v.muted);
  mute.title = v.muted ? "Unmute" : SP.ptt ? "Mute (push to talk: hold `)" : "Mute"; mute.setAttribute("aria-label", mute.title);
  deaf.innerHTML = spSvg(v.deaf ? "headoff" : "head"); deaf.classList.toggle("bad", v.deaf);
  deaf.title = v.deaf ? "Undeafen" : "Deafen (hear nobody)"; deaf.setAttribute("aria-label", deaf.title);
  if (SP.open && SP.data[SP.open]) spRooms(SP.open, SP.data[SP.open], (SP.data[SP.open].space || {}).rooms || []);
}

function spKeys(e) {
  // a space is open: start typing anywhere and it goes into its message box (not into LOKI's home prompt)
  if (e.type === "keydown" && SP.open && e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey && e.key !== "`"
      && !/^(INPUT|TEXTAREA|SELECT)$/.test((e.target || {}).tagName || "") && !document.getElementById("sp-dlg")
      && !document.getElementById("spaces").hidden && !document.getElementById("sp-panel").hidden) {
    const box = document.getElementById("sp-input");
    if (box) { e.stopImmediatePropagation(); box.focus(); }
    return;
  }
  if (e.key === "Escape" && e.type === "keydown" && SP.open && !document.getElementById("sp-dlg") && document.getElementById("spaces")?.contains(document.activeElement)) {
    spOpenSpace(""); return;
  }
  if (!SP.voice || !SP.ptt || e.key !== "`" || (e.target && /^(INPUT|TEXTAREA)$/.test(e.target.tagName))) return;
  e.preventDefault();
  SP.pttDown = e.type === "keydown";
  if (SP.voice.stream && !SP.voice.muted) SP.voice.stream.getAudioTracks().forEach((t) => { t.enabled = SP.pttDown; });
}

// ------------------------------------------------------------------------------------------ start
async function spStart() {
  if (typeof state === "undefined" || !state.token) { setTimeout(spStart, 400); return; }
  spBuild();
  await spRefresh();
  spLoop();
  for (const s of SP.list) spSync(s.id).catch(() => {});
}
window.LokiSpaces = { open: spOpenSpace, refresh: spRefresh, join: spJoinVoice, leave: spLeaveVoice, state: SP };
// LOKI World (the Godot game, in a same-origin frame) walks you into a lobby: {lokiSpaces: "join", space, room}
window.addEventListener("message", (e) => {
  const m = e.data;
  if (e.origin !== location.origin || !m || typeof m !== "object" || m.lokiSpaces !== "join") return;
  if (typeof m.space === "string" && typeof m.room === "string" && SP.list.some((x) => x.id === m.space)) {
    SP.room[m.space] = m.room; spOpenSpace(m.space); spJoinVoice(m.space, m.room);
  }
});
window.addEventListener("beforeunload", () => { if (SP.voice) api("/spaces/act", { space: SP.voice.space, action: "voice", room: null }); });
document.addEventListener("DOMContentLoaded", () => setTimeout(spStart, 300));
