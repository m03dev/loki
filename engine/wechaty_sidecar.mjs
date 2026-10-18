// Wechaty sidecar: LOKI's "wechaty" channel (engine/channel_wechaty.py) talks to chat networks
// through Wechaty (github.com/wechaty/wechaty, Apache-2.0), which is TypeScript, so this small
// Node process runs the bot and speaks JSON lines with LOKI. LOKI starts it only when the
// wechaty add-on is on; it is never vendored (tools/setup_extras.py wechaty installs the npm
// packages into LOKI's data folder, harness_data/addons/wechaty).
//
// out (stdout, one JSON object per line):
//   {"event": "ready"}                                       the bot started
//   {"event": "scan", "qrcode": "<url>", "status": <n>}      log in: show this QR to the owner
//   {"event": "login", "user": {"id", "name"}} / {"event": "logout"}
//   {"event": "message", "user_id", "chat_id", "room": bool, "self": bool, "name", "text"}
//   {"reply": "<id>", "ok": true} / {"reply": "<id>", "ok": false, "error": "..."}
//   {"event": "error", "error": "..."};  {"fatal": "..."} then exit 1
// in (stdin):
//   {"id": "1", "op": "say", "to": "<chat_id>", "text": "..."}
//   {"id": "2", "op": "file", "to": "<chat_id>", "path": "<local file>"}
//   {"op": "stop"}
//
// Only TEXT messages go to LOKI, and LOKI can only answer chats that wrote to it in this run
// (the ids it was given): nothing else of the account is exposed. Environment:
// LOKI_WECHATY_PACKAGE_DIR (folder whose node_modules holds wechaty), WECHATY_PUPPET (default
// wechaty-puppet-wechat4u), WECHATY_PUPPET_SERVICE_TOKEN (puppet-service only, a secret: env,
// never argv), LOKI_WECHATY_NAME (session name; its memory-card file is written in the cwd).

import { createInterface } from "node:readline";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

async function load(name) {
  const dir = process.env.LOKI_WECHATY_PACKAGE_DIR || "";
  if (dir) {
    const require = createRequire(import.meta.url);
    return import(pathToFileURL(require.resolve(name, { paths: [dir] })).href);
  }
  return import(name);
}

const known = new Map();   // chat id -> Contact or Room that wrote to LOKI in this run

async function main() {
  let wechaty, filebox;
  try {
    wechaty = await load("wechaty");
    filebox = await load("file-box");
  } catch (e) {
    emit({ fatal: "wechaty is not installed (python tools/setup_extras.py wechaty): " + String((e && e.message) || e) });
    process.exit(1);
  }
  const options = { name: process.env.LOKI_WECHATY_NAME || "loki" };
  options.puppet = process.env.WECHATY_PUPPET || "wechaty-puppet-wechat4u";
  if (process.env.WECHATY_PUPPET_SERVICE_TOKEN) options.puppetOptions = { token: process.env.WECHATY_PUPPET_SERVICE_TOKEN };
  const bot = wechaty.WechatyBuilder.build(options);
  const TEXT = wechaty.types && wechaty.types.Message ? wechaty.types.Message.Text : 7;

  bot.on("scan", (qrcode, status) => emit({ event: "scan", qrcode: String(qrcode || ""), status }));
  bot.on("login", (user) => emit({ event: "login", user: { id: user.id, name: user.name() } }));
  bot.on("logout", () => emit({ event: "logout" }));
  bot.on("error", (e) => emit({ event: "error", error: String((e && e.message) || e).slice(0, 300) }));
  bot.on("message", async (msg) => {
    try {
      if (msg.type() !== TEXT) return;
      const talker = msg.talker();
      const room = msg.room();
      const chat = room || talker;
      known.set(chat.id, chat);
      emit({ event: "message", user_id: talker.id, chat_id: chat.id, room: Boolean(room), self: msg.self(),
             name: talker.name(), text: msg.text() });
    } catch (e) {
      emit({ event: "error", error: "message: " + String((e && e.message) || e).slice(0, 300) });
    }
  });

  const lines = createInterface({ input: process.stdin });
  lines.on("line", async (line) => {
    let req;
    try { req = JSON.parse(line); } catch { return; }
    if (req.op === "stop") { await bot.stop().catch(() => {}); process.exit(0); }
    const target = known.get(String(req.to || ""));
    if (!target) { emit({ reply: req.id, ok: false, error: "unknown chat" }); return; }
    try {
      if (req.op === "say") await target.say(String(req.text || ""));
      else if (req.op === "file") await target.say(filebox.FileBox.fromFile(String(req.path || "")));
      else throw new Error("unknown op");
      emit({ reply: req.id, ok: true });
    } catch (e) {
      emit({ reply: req.id, ok: false, error: String((e && e.message) || e).slice(0, 300) });
    }
  });
  lines.on("close", async () => { await bot.stop().catch(() => {}); process.exit(0); });

  try {
    await bot.start();
    emit({ event: "ready" });
  } catch (e) {
    emit({ fatal: "the bot did not start: " + String((e && e.message) || e).slice(0, 300) });
    process.exit(1);
  }
}

main();
