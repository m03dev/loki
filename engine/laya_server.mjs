// Laya, kept warm: loads the @receptron/laya model ONCE and answers many decisions.
//
// Loki's first layer asks Laya about every request, so loading the ~1.7 GB model per call
// (seconds each time) is not an option. This process loads it once and then answers JSON
// lines on stdin:
//
//   in:  {"id": "1", "state": <any>, "questions": {<id>: <question>}}
//   out: {"id": "1", "answers": {...}, "usage": {...}}      or {"id": "1", "error": "..."}
//
// Startup lines on stdout: {"progress": {"file", "received", "total"}} while downloading,
// then {"ready": true, "ms": <load time>}; a load failure prints {"fatal": "..."} and exits 1.
//
//   node laya_server.mjs              serve (Loki starts this itself)
//   node laya_server.mjs --prefetch   download the weights, answer one test question, exit
//
// Environment: LOKI_LAYA_PACKAGE_DIR (folder whose node_modules holds @receptron/laya),
// LOKI_LAYA_MODEL_DIR (a local ONNX export instead of the download), LAYA_CACHE (where the
// weights are cached; Loki points it into its data folder so it works offline afterwards).
// The model head is never reimplemented here; this is a thin shim over the real package.

import { createInterface } from "node:readline";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

async function loadModule() {
  const packageDir = process.env.LOKI_LAYA_PACKAGE_DIR || "";
  const require = createRequire(import.meta.url);
  if (packageDir) {
    const resolved = require.resolve("@receptron/laya", { paths: [packageDir] });
    return import(pathToFileURL(resolved).href);
  }
  return import("@receptron/laya");
}

export const SELF_TEST = {
  state: { request: "What is the capital of France?" },
  questions: {
    route: {
      type: "choice",
      instructions: "How should an assistant handle this request?",
      criteria: { answer: "answer directly", plan: "plan several steps", team: "a large job for several agents" },
    },
  },
};

async function main() {
  const prefetch = process.argv.includes("--prefetch");
  let mod;
  try {
    mod = await loadModule();
  } catch (e) {
    emit({ fatal: "@receptron/laya is not installed: " + String((e && e.message) || e) });
    process.exit(1);
  }
  const started = Date.now();
  const opts = {};
  if (process.env.LOKI_LAYA_MODEL_DIR) opts.modelDir = process.env.LOKI_LAYA_MODEL_DIR;
  let last = 0;
  opts.onProgress = ({ file, received, total }) => {
    const now = Date.now();
    if (now - last < 500 && received !== total) return;
    last = now;
    emit({ progress: { file, received, total } });
  };
  let laya;
  try {
    laya = await mod.Laya.load(opts);
  } catch (e) {
    emit({ fatal: "could not load the Laya model: " + String((e && e.message) || e) });
    process.exit(1);
  }
  emit({ ready: true, ms: Date.now() - started });

  if (prefetch) {
    const result = await laya.systemOne(SELF_TEST.state, SELF_TEST.questions);
    emit({ selftest: result.answers });
    await laya.close();
    return;
  }

  // One request at a time, in order: the model batches the questions of one call itself.
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
  let queue = Promise.resolve();
  rl.on("line", (line) => {
    const text = line.trim();
    if (!text) return;
    queue = queue.then(async () => {
      let req;
      try {
        req = JSON.parse(text);
      } catch (e) {
        emit({ id: null, error: "bad JSON request: " + e.message });
        return;
      }
      try {
        const result = await laya.systemOne(req.state, req.questions || {});
        emit({ id: req.id, answers: result.answers, usage: result.usage });
      } catch (e) {
        emit({ id: req.id, error: String((e && e.message) || e) });
      }
    });
  });
  rl.on("close", async () => {
    await queue;
    try {
      await laya.close();
    } catch {
      /* already closed */
    }
    process.exit(0);
  });
}

main().catch((e) => {
  emit({ fatal: String((e && e.message) || e) });
  process.exit(1);
});
