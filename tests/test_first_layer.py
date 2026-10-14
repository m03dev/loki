"""First-layer tests: every request is triaged by Laya, or by the built-in rules without it.

    python tests/test_first_layer.py

The real @receptron/laya model is 1.7 GB, so these tests run the REAL laya_server.mjs
against a small stand-in package with the same API (Laya.load / systemOne / close). The
stand-in records how many times the model was loaded, which proves it stays warm.
Needs Node.js 20+; the Node parts are skipped without it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
os.environ["LOKI_DATA"] = str(TMP / "data")
(TMP / "data").mkdir()
for key in ("LAYA_BASE_URL", "LOKI_LAYA_LOCAL", "LOKI_LAYA_PACKAGE_DIR", "LAYA_CACHE", "LOKI_LAYA_MODEL_DIR"):
    os.environ.pop(key, None)
sys.path.insert(0, str(REPO / "engine"))

import experience  # noqa: E402
import first_layer  # noqa: E402
import laya  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:300]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


section("built-in rules (no Laya)")
check("no Laya package means no backend", laya.backend() == "", laya.status())
cases = {
    "hi": ("chat", "answer"),
    "What does this project do?": ("question", "answer"),
    "Build a landing page for my bakery and test it in a browser": ("build", "team"),
    "fix the bug in parser.py where empty lines crash": ("code", "one_step"),
    "research the cheapest GPU cloud providers and compare their prices for a week of training": ("research", "plan"),
}
for text, (kind, route) in cases.items():
    t = first_layer.triage(text)
    check("rules: %r -> %s / %s" % (text[:40], kind, route),
          t["kind"] == kind and t["route"] == route and t["source"] == "rules", t)
t = first_layer.triage("hello")
check("without Laya the triage says so", "not set up" in t.get("note", ""), t)
check("risky words raise the risk", first_layer.triage("delete all my old emails")["risk"] >= 0.5)
check("Ask and Plan never start a team", first_layer.triage("Build a whole game", mode="plan")["route"] == "plan")
check("the trace line names who answered", first_layer.describe(first_layer.triage("hi")).startswith("Rules:"))
check("a question tells the agent to answer directly", "Answer it" in first_layer.guidance({"route": "answer"}))
check("a large job tells the agent to use background agents",
      "start_team" in first_layer.guidance({"route": "team"}))
check("a one-step job adds nothing to the prompt", first_layer.guidance({"route": "one_step"}) == "")
check("actual route: no tools = answer", first_layer.actual_route(0, False) == "answer")
check("actual route: delegated = team", first_layer.actual_route(9, True) == "team")
check("actual route: many tools = plan", first_layer.actual_route(7, False) == "plan")

section("triage accuracy is measured from the experience log")
root = TMP / "exp"
for predicted, actual, src, outcome in (("answer", "answer", "laya", "answered"),
                                        ("plan", "plan", "laya", "verified"),
                                        ("plan", "one_step", "laya", "verified"),
                                        ("team", "answer", "rules", "answered")):
    experience.record({"id": experience.uuid_hex()[:12], "kind": "chat", "goal": "g", "status": "done",
                       "outcome": outcome, "triage": {"source": src, "route": predicted,
                                                      "actual_route": actual, "ms": 10}}, root=root)
stats = experience.triage_stats(root)
check("per source: requests and accuracy", stats["laya"]["requests"] == 3 and stats["laya"]["accuracy"] == round(2 / 3, 3), stats)
check("off-by-one counts as close", stats["laya"]["within_one"] == 1.0, stats)
check("a far miss is neither right nor close", stats["rules"]["accuracy"] == 0.0 and stats["rules"]["within_one"] == 0.0, stats)
check("the summary carries triage stats", "triage" in experience.summary(root))

section("Laya over the real laya_server.mjs (stand-in model)")
node = shutil.which("node")
version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip() if node else ""
if not node or int(version.lstrip("v").split(".")[0] or 0) < 20:
    print("  SKIP no Node.js 20+ (%s)" % (version or "not found"))
else:
    pkg = TMP / "data" / "laya" / "node_modules" / "@receptron" / "laya"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text(json.dumps({"name": "@receptron/laya", "version": "0.0.0-test",
                                                  "type": "module", "main": "index.js"}), encoding="utf-8")
    loads = TMP / "loads.txt"
    (pkg / "index.js").write_text("""
import { appendFileSync } from "node:fs";
export class Laya {
  static async load(opts) {
    appendFileSync(%s, "load cache=" + (process.env.LAYA_CACHE || "") + "\\n");
    if (opts.onProgress) opts.onProgress({ file: "laya.onnx.data", received: 10, total: 10 });
    await new Promise((r) => setTimeout(r, 300));
    return new Laya();
  }
  async systemOne(state, questions) {
    const text = JSON.stringify(state).toLowerCase();
    const answers = {};
    for (const [id, q] of Object.entries(questions)) {
      if (q.type === "choice") {
        const keys = Object.keys(q.criteria);
        let pick = keys[0];
        if (id === "kind") pick = text.includes("website") ? "build" : (text.includes("?") ? "question" : "code");
        if (id === "route") pick = text.includes("website") ? "team" : (text.includes("?") ? "answer" : "one_step");
        const probabilities = Object.fromEntries(keys.map((k) => [k, k === pick ? 0.9 : 0.1 / (keys.length - 1)]));
        answers[id] = { choice: pick, probabilities };
      } else if (q.type === "score") {
        answers[id] = { score: text.includes("website") ? 2.6 : 0.4 };
      } else {
        answers[id] = { noul: text.includes("delete") ? 0.8 : 0.03 };
      }
    }
    if (text.includes("explode")) throw new Error("model exploded");
    return { answers, usage: { input_tokens: 42 } };
  }
  async close() {}
}
""" % json.dumps(str(loads)), encoding="utf-8")
    check("the package is found in harness_data/laya", laya.package_installed())
    check("node backend selected", laya.backend() == "node", laya.status())
    check("weights are reported missing until downloaded", laya.weights_cached() is False)

    # tools/setup_laya.py --prefetch path: download, load, answer the self-test
    out = subprocess.run([node, laya.DRIVER, "--prefetch"], capture_output=True, text=True,
                         env=laya.node_env(), timeout=60).stdout
    lines = [json.loads(x) for x in out.splitlines() if x.strip()]
    check("prefetch reports download progress", any("progress" in x for x in lines), lines)
    check("prefetch answers the self-test", any("selftest" in x for x in lines), lines)
    check("the weights cache lives in Loki's data folder",
          str(TMP / "data" / "laya" / "cache") in loads.read_text(), loads.read_text())

    laya._cache.clear()
    loads.write_text("")
    first_layer.TIMEOUT_S = 20
    t1 = first_layer.triage("Build me a website for my bakery")
    check("Laya triages a request", t1["source"] == "laya" and t1["kind"] == "build" and t1["route"] == "team", t1)
    check("difficulty comes from the score", t1["difficulty"] == 3, t1)
    check("confidence is the route probability", t1["confidence"] == 0.9, t1)
    t2 = first_layer.triage("What is in this folder?")
    check("a second request is answered too", t2["source"] == "laya" and t2["route"] == "answer", t2)
    check("the model stayed warm (loaded once for many requests)", loads.read_text().count("load") == 1, loads.read_text())
    check("a warm decision is fast", t2["ms"] < 2000, t2)
    check("the trace line names Laya", first_layer.describe(t2).startswith("Laya:"))
    check("risky requests are flagged", first_layer.triage("delete the logs folder please")["risk"] >= 0.5)
    t3 = first_layer.triage("make it explode")
    check("a model error falls back to the rules", t3["source"] == "rules" and "Laya" in t3.get("note", ""), t3)
    check("errors are counted", laya.STATS["errors"] >= 1, laya.STATS)
    check("the server survived the error", first_layer.triage("What now?")["source"] == "laya")
    check("status shows the warm server", laya.status()["server"]["state"] == "ready", laya.status())

    # The process dies: the next request restarts it.
    laya.SERVER.proc.kill()
    time.sleep(0.5)
    t4 = first_layer.triage("What happened?")
    check("a crashed Laya is restarted on the next request", t4["source"] == "laya", t4)

    # Not ready yet: the rules answer at once and Laya keeps loading for later.
    laya.SERVER.stop()
    laya._cache.clear()
    t5 = first_layer.triage("What is this?", wait=False)
    check("while the model loads, the rules answer without waiting", t5["source"] == "rules" and "loading" in t5.get("note", ""), t5)
    laya.SERVER.wait_ready(20)
    check("...and the model finishes loading in the background", laya.ready())
    laya.SERVER.stop()

    # A broken package fails once and is not retried on every request.
    (pkg / "index.js").write_text("export const Laya = { load: async () => { throw new Error('no weights'); } };", encoding="utf-8")
    laya.SERVER = laya.Server()
    t6 = first_layer.triage("hello there friend")
    check("a model that cannot load falls back to the rules", t6["source"] == "rules", t6)
    check("the load error is reported", "no weights" in laya.SERVER.error, laya.SERVER.snapshot())
    started = time.monotonic()
    first_layer.triage("hello again")
    check("a failed load is not retried on every request", time.monotonic() - started < 1.0)

    # tools/setup_laya.py --check reports without touching the network
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "setup_laya.py"), "--check"],
                          capture_output=True, text=True, env=dict(os.environ), timeout=60)
    report = json.loads(proc.stdout)
    check("setup_laya --check reports node, package and weights",
          report["node_ok"] and report["package"] and report["weights"] is False, report)

section("the engine runs the first layer on every request")
src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("chat requests are triaged first", "await asyncio.to_thread(_triage, user_message)" in src)
check("tasks are triaged first", "await asyncio.to_thread(_triage, goal)" in src)
check("the verdict is logged with the outcome", '"triage": _triage_record(start_index)' in src)
check("the request note is removed afterwards", src.count("_end_triage()") >= 2)
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the engine warms Laya at startup", "laya.warm()" in bridge)
check("/health reports who answers the first layer", '"first_layer": first_layer_status(agent)' in bridge)
ui = (REPO / "app" / "ui" / "app.js").read_text(encoding="utf-8")
check("the conversation shows the first layer's verdict", 'triage: "First layer"' in ui)
for name in ("setup.bat", "setup.sh"):
    check("%s sets up Laya" % name, "setup_laya.py" in (REPO / name).read_text(encoding="utf-8"))

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
