// LOKI on your phone, in the phone's own browser - no app to install (owner 2026-10-18: "qr dont show up on my phone
// and links dont go anywhere"). The pairing QR is now a link: http://<this computer>:<phone port>/#loki-phone:<code>.
// The phone camera opens it, this page reads the code from the #fragment (a fragment never reaches any server), keeps
// it in this browser only, and signs every request exactly like the phone app (mobile/src/lib/protocol.ts -> engine/
// phone_link.py: HMAC-SHA256 over method, path, time, nonce and the body's SHA-256). Pure JS: phone browsers give no
// WebCrypto to a plain-http home address. Ask and Plan only; a phone can never approve or build.
"use strict";

(function () {
  const PREFIX = "loki-phone:";
  const K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  const utf8 = (s) => Array.from(new TextEncoder().encode(s));
  function sha256(data) {
    const h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    const bits = data.length * 8, msg = data.slice();
    msg.push(0x80);
    while (msg.length % 64 !== 56) msg.push(0);
    const hi = Math.floor(bits / 0x100000000), lo = bits >>> 0;
    msg.push((hi >>> 24) & 255, (hi >>> 16) & 255, (hi >>> 8) & 255, hi & 255, (lo >>> 24) & 255, (lo >>> 16) & 255, (lo >>> 8) & 255, lo & 255);
    const w = new Array(64);
    for (let off = 0; off < msg.length; off += 64) {
      for (let i = 0; i < 16; i++) { const j = off + i * 4; w[i] = ((msg[j] << 24) | (msg[j + 1] << 16) | (msg[j + 2] << 8) | msg[j + 3]) >>> 0; }
      for (let i = 16; i < 64; i++) {
        const a = w[i - 15], b = w[i - 2];
        const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
        const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
      }
      let [a, b, c, d, e, f, g, hh] = h;
      for (let i = 0; i < 64; i++) {
        const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        const t1 = (hh + S1 + ((e & f) ^ (~e & g)) + K[i] + w[i]) >>> 0;
        const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        const t2 = (S0 + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
        hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      h[0] = (h[0] + a) >>> 0; h[1] = (h[1] + b) >>> 0; h[2] = (h[2] + c) >>> 0; h[3] = (h[3] + d) >>> 0;
      h[4] = (h[4] + e) >>> 0; h[5] = (h[5] + f) >>> 0; h[6] = (h[6] + g) >>> 0; h[7] = (h[7] + hh) >>> 0;
    }
    const out = [];
    for (const x of h) out.push((x >>> 24) & 255, (x >>> 16) & 255, (x >>> 8) & 255, x & 255);
    return out;
  }
  const hex = (b) => b.map((x) => (x < 16 ? "0" : "") + x.toString(16)).join("");
  function hmac(key, message) {
    let k = key.length > 64 ? sha256(key) : key.slice();
    while (k.length < 64) k.push(0);
    return sha256(k.map((x) => x ^ 0x5c).concat(sha256(k.map((x) => x ^ 0x36).concat(message))));
  }
  const signingKey = (token) => hex(hmac(utf8(token), utf8("loki-phone-v1")));
  function sign(key, method, path, stamp, body, nonce) {
    const parts = [method.toUpperCase(), path, stamp, nonce, hex(sha256(utf8(body)))];
    return hex(hmac(utf8(key), utf8(parts.join("\n"))));
  }
  function nonce() {
    const a = new Uint8Array(9);
    if (window.crypto && crypto.getRandomValues) crypto.getRandomValues(a); else for (let i = 0; i < 9; i++) a[i] = Math.random() * 256;
    return hex(Array.from(a)) + Date.now().toString(16);
  }
  function parseCode(text) {
    const s = decodeURIComponent(String(text || "").trim());
    const at = s.indexOf(PREFIX);
    if (at < 0) throw new Error("This page needs the code from LOKI's QR (Settings > Machines > Phone).");
    const b = s.slice(at + PREFIX.length).replace(/[^A-Za-z0-9_-]/g, "");
    const raw = atob(b.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((b.length + 3) % 4));
    const data = JSON.parse(new TextDecoder().decode(Uint8Array.from(raw, (c) => c.charCodeAt(0))));
    if (!data || data.v !== 1 || !data.id || String(data.token || "").length < 32) throw new Error("The code is incomplete - scan it again.");
    return { id: String(data.id), key: signingKey(String(data.token)), machine: String(data.machine || "LOKI"), kind: data.kind === "Mac" ? "Mac" : "PC" };
  }

  const STORE = "loki-phone-web";
  const $ = (id) => document.getElementById(id);
  let me = null;
  try { me = JSON.parse(localStorage.getItem(STORE) || "null"); } catch (_) { me = null; }
  try {
    if (location.hash.includes(PREFIX)) {
      me = parseCode(location.hash.slice(1));
      try { localStorage.setItem(STORE, JSON.stringify(me)); } catch (_) { /* private mode: this tab only */ }
    }
  } catch (exc) { say(exc.message, true); }
  if (location.hash) history.replaceState(null, "", location.pathname);   // the code never stays in the address bar

  function say(text, bad) { const s = $("status"); if (s) { s.textContent = text || ""; s.className = bad ? "bad" : ""; } }

  async function call(method, path, payload) {
    const body = payload ? JSON.stringify(payload) : "", stamp = (Date.now() / 1000).toFixed(3), n = nonce();
    const resp = await fetch(path, { method, body: method === "GET" ? undefined : body, cache: "no-store", headers: {
      "Content-Type": "application/json", "X-Loki-Phone": me.id, "X-Loki-Time": stamp, "X-Loki-Nonce": n,
      "X-Loki-Sig": sign(me.key, method, path, stamp, body, n) } });
    let out = {};
    try { out = await resp.json(); } catch (_) { out = { ok: false, error: "no answer (" + resp.status + ")" }; }
    return out;
  }

  function bubble(who, text) {
    const b = document.createElement("div");
    b.className = "msg " + who; b.textContent = text;
    $("log").append(b); b.scrollIntoView({ block: "end" });
    return b;
  }

  async function hello() {
    if (!me) { $("chat").hidden = true; say("Scan the QR in LOKI on your computer: Settings > Machines > Phone > Pair a phone."); return; }
    $("chat").hidden = false;
    $("who").textContent = me.machine + " (" + me.kind + ")";
    const s = await call("GET", "/phone/status").catch((e) => ({ ok: false, error: e.message }));
    if (s.ok) say(s.busy ? "LOKI is busy on the computer - your message waits." : "Connected. Ask anything (Plan mode reads files too).");
    else { say(s.error || "LOKI did not answer", true); if (/pair|unknown phone|revoked|expired/i.test(s.error || "")) { try { localStorage.removeItem(STORE); } catch (_) { /* */ } } }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = $("text").value.trim();
      if (!text || !me) return;
      $("text").value = ""; $("send").disabled = true;
      bubble("you", text);
      const wait = bubble("loki", "…");
      const r = await call("POST", "/phone/chat", { message: text, mode: $("mode").value }).catch((x) => ({ ok: false, error: x.message }));
      wait.textContent = r.ok ? (r.response || "(no answer)") : "✗ " + (r.error || "failed");
      if (!r.ok) wait.classList.add("bad");
      $("send").disabled = false;
    });
    $("forget").addEventListener("click", async () => {
      if (me) await call("POST", "/phone/unpair", {}).catch(() => null);
      try { localStorage.removeItem(STORE); } catch (_) { /* */ }
      me = null; $("log").textContent = ""; hello();
    });
    hello();
  });
  window.LokiPhoneWeb = { parseCode, sign, signingKey };
})();
