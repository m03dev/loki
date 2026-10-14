// Thin shim so Loki can use the real @receptron/laya package without reimplementing the ONNX
// post-processing. Reads ONE JSON request on stdin and writes ONE JSON response on stdout:
//
//   { "state": <any>, "questions": { <id>: <question> }, "modelDir": "<optional>",
//     "packageDir": "<optional dir whose node_modules holds @receptron/laya>" }
//     -> { "answers": {...}, "usage": {...} }   or   { "error": "<message>" }
//
// The package is resolved in this order:
//   1. packageDir/node_modules/@receptron/laya (what Loki passes from harness_data/laya)
//   2. installed next to this file or above it (plain "@receptron/laya" specifier)
// Install it once (Node 20+):
//   npm install --prefix <packageDir> @receptron/laya
// The ONNX weights download on first use and are cached by the package (~/.cache/receptron-laya).

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

function readStdin() {
  try {
    return readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

async function loadLaya(packageDir) {
  const require = createRequire(import.meta.url);
  if (packageDir) {
    const resolved = require.resolve("@receptron/laya", { paths: [packageDir] });
    return import(pathToFileURL(resolved).href);
  }
  return import("@receptron/laya");
}

async function main() {
  const raw = readStdin().trim();
  if (!raw) return { error: "laya_driver: no request on stdin" };
  let req;
  try {
    req = JSON.parse(raw);
  } catch (e) {
    return { error: "laya_driver: bad JSON request: " + e.message };
  }
  let mod;
  try {
    mod = await loadLaya(req.packageDir);
  } catch (e) {
    return {
      error:
        "laya_driver: @receptron/laya is not installed (npm install --prefix <dir> @receptron/laya): " +
        String((e && e.message) || e),
    };
  }
  const opts = {};
  if (req.modelDir) opts.modelDir = req.modelDir;
  const laya = await mod.Laya.load(opts);
  try {
    const result = await laya.systemOne(req.state, req.questions || {});
    return { answers: result.answers, usage: result.usage };
  } finally {
    try {
      await laya.close();
    } catch {
      /* releasing a session that never opened is not an error worth reporting */
    }
  }
}

main()
  .then((body) => {
    process.stdout.write(JSON.stringify(body));
  })
  .catch((e) => {
    process.stdout.write(JSON.stringify({ error: String((e && e.message) || e) }));
  });
