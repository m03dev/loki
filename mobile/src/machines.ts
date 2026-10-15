// Talking to LOKI on the Mac/PC (engine/phone_link.py): signed requests over the LAN.
import { parsePairingCode, signedHeaders, signingKey } from "./lib/protocol";
import { Machine, store } from "./storage";

export const PROBE_TIMEOUT_MS = 2500;
export const CHAT_TIMEOUT_MS = 10 * 60 * 1000;

export class LinkError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.status = status; // 0 = could not reach it at all
  }
}

async function request(m: Machine, host: string, method: "GET" | "POST", path: string,
                       payload: unknown, timeoutMs: number): Promise<any> {
  const key = await store.key(m.id);
  if (!key) throw new LinkError("This phone has no key for " + m.machine + " - pair again.", 401);
  const body = payload === undefined ? "" : JSON.stringify(payload);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch("http://" + host + ":" + m.port + path, {
      method,
      headers: signedHeaders(m.id, key, method, path, body, Date.now()),
      body: method === "POST" ? body : undefined,
      signal: controller.signal,
    });
    let data: any = {};
    try {
      data = await response.json();
    } catch {
      data = {};
    }
    if (!response.ok) throw new LinkError(data.error || "HTTP " + response.status, response.status);
    return data;
  } catch (err) {
    if (err instanceof LinkError) throw err;
    throw new LinkError("Cannot reach " + m.machine + " at " + host, 0);
  } finally {
    clearTimeout(timer);
  }
}

/** The first of this machine's addresses that answers /phone/status, or null. */
export async function probe(m: Machine): Promise<{ host: string; status: any } | null> {
  const hosts = m.lastHost ? [m.lastHost, ...m.hosts.filter((h) => h !== m.lastHost)] : m.hosts;
  // All addresses at once; the first to answer wins (no Promise.any: not on every engine).
  return new Promise((resolve, reject) => {
    let left = hosts.length;
    let refused: LinkError | null = null;
    if (!left) resolve(null);
    for (const host of hosts) {
      request(m, host, "GET", "/phone/status", undefined, PROBE_TIMEOUT_MS)
        .then((status) => resolve({ host, status }))
        .catch((err) => {
          if (err instanceof LinkError && err.status === 401) refused = err;
          left -= 1;
          if (left === 0) {
            if (refused) reject(refused); // reachable, but this phone is no longer allowed: say so
            else resolve(null);
          }
        });
    }
  });
}

export async function chat(m: Machine, host: string, message: string, mode: "ask" | "plan"): Promise<string> {
  const data = await request(m, host, "POST", "/phone/chat", { message, mode }, CHAT_TIMEOUT_MS);
  return String(data.response || "");
}

/** Save a machine from a scanned or pasted "loki-phone:" code. Returns it. */
export async function pairFromCode(code: string): Promise<Machine> {
  const p = parsePairingCode(code);
  const machine: Machine = { id: p.id, machine: p.machine, kind: p.kind, hosts: p.hosts, port: p.port };
  await store.saveKey(p.id, signingKey(p.token)); // the raw token is not kept
  const list = (await store.machines()).filter((m) => m.id !== p.id && !(m.machine === p.machine && m.kind === p.kind));
  await store.saveMachines([...list, machine]);
  // First contact claims the pairing on the computer (it expires 15 minutes after it was shown).
  const found = await probe(machine);
  if (found) {
    machine.lastHost = found.host;
    machine.lastSeen = Date.now();
    await store.saveMachines([...list, machine]);
  }
  return machine;
}

export async function forget(m: Machine): Promise<void> {
  if (m.lastHost) {
    await request(m, m.lastHost, "POST", "/phone/unpair", {}, PROBE_TIMEOUT_MS).catch(() => undefined);
  }
  await store.forgetKey(m.id);
  await store.saveMachines((await store.machines()).filter((x) => x.id !== m.id));
}
