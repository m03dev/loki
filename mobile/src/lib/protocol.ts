// The phone link protocol (engine/phone_link.py), with no imports and no native code:
// SHA-256, HMAC-SHA256, request signing and the pairing code. Plain TypeScript so it runs
// the same on iOS and Android (Hermes) and in Node for tests/test_phone_link.py.

export const PAIR_PREFIX = "loki-phone:";

export type Pairing = {
  v: number;
  machine: string;
  kind: string; // "Mac" or "PC"
  hosts: string[];
  port: number;
  id: string;
  token: string;
};

export function utf8(text: string): number[] {
  const out: number[] = [];
  for (let i = 0; i < text.length; i += 1) {
    let code = text.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff && i + 1 < text.length) {
      const next = text.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        code = 0x10000 + ((code - 0xd800) << 10) + (next - 0xdc00);
        i += 1;
      }
    }
    if (code < 0x80) out.push(code);
    else if (code < 0x800) out.push(0xc0 | (code >> 6), 0x80 | (code & 63));
    else if (code < 0x10000) out.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 63), 0x80 | (code & 63));
    else out.push(0xf0 | (code >> 18), 0x80 | ((code >> 12) & 63), 0x80 | ((code >> 6) & 63), 0x80 | (code & 63));
  }
  return out;
}

export function fromUtf8(bytes: number[]): string {
  let out = "";
  for (let i = 0; i < bytes.length; ) {
    const b = bytes[i];
    let code: number;
    if (b < 0x80) { code = b; i += 1; }
    else if (b < 0xe0) { code = ((b & 31) << 6) | (bytes[i + 1] & 63); i += 2; }
    else if (b < 0xf0) { code = ((b & 15) << 12) | ((bytes[i + 1] & 63) << 6) | (bytes[i + 2] & 63); i += 3; }
    else {
      code = ((b & 7) << 18) | ((bytes[i + 1] & 63) << 12) | ((bytes[i + 2] & 63) << 6) | (bytes[i + 3] & 63);
      i += 4;
    }
    out += String.fromCodePoint(code);
  }
  return out;
}

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

export function sha256(data: number[]): number[] {
  const h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
  const bitLength = data.length * 8;
  const msg = data.slice();
  msg.push(0x80);
  while (msg.length % 64 !== 56) msg.push(0);
  const hi = Math.floor(bitLength / 0x100000000);
  const lo = bitLength >>> 0;
  msg.push((hi >>> 24) & 255, (hi >>> 16) & 255, (hi >>> 8) & 255, hi & 255);
  msg.push((lo >>> 24) & 255, (lo >>> 16) & 255, (lo >>> 8) & 255, lo & 255);
  const w = new Array<number>(64);
  for (let off = 0; off < msg.length; off += 64) {
    for (let i = 0; i < 16; i += 1) {
      const j = off + i * 4;
      w[i] = ((msg[j] << 24) | (msg[j + 1] << 16) | (msg[j + 2] << 8) | msg[j + 3]) >>> 0;
    }
    for (let i = 16; i < 64; i += 1) {
      const a = w[i - 15], b = w[i - 2];
      const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
      const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, hh] = h;
    for (let i = 0; i < 64; i += 1) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      const ch = (e & f) ^ (~e & g);
      const t1 = (hh + S1 + ch + K[i] + w[i]) >>> 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    h[0] = (h[0] + a) >>> 0; h[1] = (h[1] + b) >>> 0; h[2] = (h[2] + c) >>> 0; h[3] = (h[3] + d) >>> 0;
    h[4] = (h[4] + e) >>> 0; h[5] = (h[5] + f) >>> 0; h[6] = (h[6] + g) >>> 0; h[7] = (h[7] + hh) >>> 0;
  }
  const out: number[] = [];
  for (const word of h) out.push((word >>> 24) & 255, (word >>> 16) & 255, (word >>> 8) & 255, word & 255);
  return out;
}

export function hex(bytes: number[]): string {
  return bytes.map((b) => (b < 16 ? "0" : "") + b.toString(16)).join("");
}

export function hmacSha256(key: number[], message: number[]): number[] {
  let k = key.length > 64 ? sha256(key) : key.slice();
  while (k.length < 64) k.push(0);
  const inner = k.map((b) => b ^ 0x36).concat(message);
  const outer = k.map((b) => b ^ 0x5c).concat(sha256(inner));
  return sha256(outer);
}

/** The HMAC key both sides derive from the QR token (phone_link.signing_key). */
export function signingKey(token: string): string {
  return hex(hmacSha256(utf8(token), utf8("loki-phone-v1")));
}

/** phone_link.sign: HMAC over method, path, timestamp, an optional nonce and the body's SHA-256. */
export function sign(key: string, method: string, path: string, stamp: string, body: string,
                     nonce: string = ""): string {
  const parts = [method.toUpperCase(), path, stamp];
  if (nonce) parts.push(nonce);
  parts.push(hex(sha256(utf8(body))));
  return hex(hmacSha256(utf8(key), utf8(parts.join("\n"))));
}

let nonceCounter = 0;

/** A fresh value per request so two identical requests in one millisecond never share a
 *  signature (the engine would refuse the second as a replay). It only has to be unique. */
export function makeNonce(): string {
  const bytes = new Array<number>(9).fill(0);
  const c = (globalThis as { crypto?: { getRandomValues?: (a: Uint8Array) => Uint8Array } }).crypto;
  if (c && typeof c.getRandomValues === "function") {
    const arr = new Uint8Array(9);
    c.getRandomValues(arr);
    for (let i = 0; i < 9; i++) bytes[i] = arr[i];
  } else {
    for (let i = 0; i < 9; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  nonceCounter = (nonceCounter + 1) % 65536;
  return hex(bytes) + nonceCounter.toString(16);
}

export function signedHeaders(phoneId: string, key: string, method: string, path: string, body: string,
                              nowMs: number, nonce: string = makeNonce()): Record<string, string> {
  const stamp = (nowMs / 1000).toFixed(3);
  return {
    "Content-Type": "application/json",
    "X-Loki-Phone": phoneId,
    "X-Loki-Time": stamp,
    "X-Loki-Nonce": nonce,
    "X-Loki-Sig": sign(key, method, path, stamp, body, nonce),
  };
}

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

export function base64UrlDecode(text: string): number[] {
  const clean = text.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const out: number[] = [];
  let buffer = 0, bits = 0;
  for (const ch of clean) {
    const value = B64.indexOf(ch);
    if (value < 0) throw new Error("the phone code is damaged");
    buffer = (buffer << 6) | value;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push((buffer >> bits) & 255);
    }
  }
  return out;
}

function privateHost(host: string): boolean {
  const parts = host.split(".").map((p) => Number(p));
  if (parts.length === 4 && parts.every((p) => Number.isInteger(p) && p >= 0 && p <= 255)) {
    const [a, b] = parts;
    return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) ||
      (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254);
  }
  return !host.includes(".") || /\.(local|lan|home|internal)$/.test(host);
}

/** The payload of a "loki-phone:" code (from the QR or pasted), or an Error saying why not. */
export function parsePairingCode(code: string): Pairing {
  let text = String(code || "").trim();
  // the QR is a link now (http://<computer>:<port>/#loki-phone:...) so a phone camera opens LOKI's web page; the
  // app takes the same code from the #fragment
  if (!text.startsWith(PAIR_PREFIX) && text.includes("#" + PAIR_PREFIX)) text = decodeURIComponent(text.slice(text.indexOf("#") + 1));
  if (!text.startsWith(PAIR_PREFIX)) throw new Error("That is not a LOKI phone code (it starts with " + PAIR_PREFIX + ").");
  let data: Partial<Pairing>;
  try {
    data = JSON.parse(fromUtf8(base64UrlDecode(text.slice(PAIR_PREFIX.length))));
  } catch {
    throw new Error("The phone code is damaged - scan it again.");
  }
  if (!data || data.v !== 1 || !data.id || !data.token || String(data.token).length < 32 ||
      !Array.isArray(data.hosts) || !data.hosts.length || !data.port) {
    throw new Error("The phone code is incomplete.");
  }
  if (!data.hosts.every((h) => privateHost(String(h)))) throw new Error("LOKI only pairs on your own network.");
  return {
    v: 1, machine: String(data.machine || "LOKI"), kind: data.kind === "Mac" ? "Mac" : "PC",
    hosts: data.hosts.map(String).slice(0, 4), port: Number(data.port), id: String(data.id), token: String(data.token),
  };
}
