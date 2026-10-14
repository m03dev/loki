"""Set up Laya, Loki's offline first layer: install it, download the model, test it.

    python tools/setup_laya.py           install + download (about 1.7 GB, once) + self-test
    python tools/setup_laya.py --check   report what is there, without touching the network

Everything lands in harness_data/laya (the npm package and the cached ONNX weights), so after
this has run once Laya works with no internet. Needs Node.js 20+ (nodejs.org). Setup runs this
for you; set LOKI_SKIP_LAYA=1 to skip it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))

import laya  # noqa: E402


def node_version() -> tuple:
    exe = shutil.which(laya.node_exe())
    if not exe:
        return ()
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ()
    match = re.match(r"v?(\d+)\.(\d+)", out.strip())
    return (int(match.group(1)), int(match.group(2))) if match else ()


def npm_exe() -> str:
    return shutil.which("npm") or shutil.which("npm.cmd") or ""


def report() -> dict:
    version = node_version()
    return {
        "node": ".".join(map(str, version)) if version else "",
        "node_ok": bool(version) and version >= (20, 0),
        "package": laya.package_installed(),
        "weights": laya.weights_cached(),
        "package_dir": laya.package_dir(),
        "cache_dir": laya.cache_dir(),
    }


def install_package() -> bool:
    npm = npm_exe()
    if not npm:
        print("[laya] npm was not found (it comes with Node.js).")
        return False
    target = Path(laya.package_dir())
    target.mkdir(parents=True, exist_ok=True)
    print("[laya] installing @receptron/laya into %s" % target, flush=True)
    proc = subprocess.run([npm, "install", "--prefix", str(target), "--no-audit", "--no-fund",
                           "@receptron/laya"], cwd=str(target))
    return proc.returncode == 0 and laya.package_installed()


def _mb(n) -> str:
    return "%.0f MB" % (float(n) / 1e6) if n else "?"


def prefetch() -> dict:
    """Download the weights (with progress), load them, and answer one test question."""
    env = laya.node_env()
    print("[laya] loading the model (downloads about 1.7 GB the first time)...", flush=True)
    proc = subprocess.Popen([laya.node_exe(), laya.DRIVER, "--prefetch"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, cwd=str(REPO))
    result: dict = {}
    for raw in iter(proc.stdout.readline, b""):
        try:
            msg = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if "progress" in msg:
            p = msg["progress"]
            total = p.get("total")
            pct = (" %3d%%" % (100 * p["received"] / total)) if total else ""
            print("\r[laya] %s %s / %s%s   " % (p.get("file"), _mb(p.get("received")), _mb(total), pct),
                  end="", flush=True)
        elif msg.get("ready"):
            print("\n[laya] model loaded in %.1f s" % (msg.get("ms", 0) / 1000.0), flush=True)
        elif "selftest" in msg:
            result = msg["selftest"]
        elif "fatal" in msg:
            print("\n[laya] %s" % msg["fatal"], flush=True)
    proc.wait()
    if proc.returncode != 0 and not result:
        err = (proc.stderr.read() or b"").decode("utf-8", "replace").strip()[-400:]
        if err:
            print("[laya] " + err)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only; no network")
    args = ap.parse_args(argv)
    state = report()
    if args.check:
        print(json.dumps(state, indent=2))
        return 0 if state["node_ok"] and state["package"] and state["weights"] else 1
    if os.getenv("LOKI_SKIP_LAYA", "").strip() in ("1", "true", "yes"):
        print("[laya] skipped (LOKI_SKIP_LAYA=1); Loki uses its built-in rules instead.")
        return 0
    if not state["node_ok"]:
        print("[laya] Laya needs Node.js 20 or newer%s. Install it from https://nodejs.org, then run:"
              % (" (found %s)" % state["node"] if state["node"] else ""))
        print("       python tools/setup_laya.py")
        print("       Until then Loki's first layer uses its built-in rules.")
        return 1
    if not state["package"] and not install_package():
        print("[laya] could not install @receptron/laya. Loki keeps working with its built-in rules.")
        return 1
    answers = prefetch()
    route = (answers.get("route") or {}).get("choice")
    if route not in ("answer", "plan", "team"):
        print("[laya] self-test FAILED (no answer). Loki keeps working with its built-in rules.")
        return 1
    print("[laya] self-test OK: 'What is the capital of France?' -> %s. Laya now works offline." % route)
    return 0


if __name__ == "__main__":
    sys.exit(main())
