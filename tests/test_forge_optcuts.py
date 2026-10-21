"""Forge's UV unwrap engine: OptCuts (Li et al., SIGGRAPH Asia 2018; MIT) built to WebAssembly
(native/optcuts/, app/ui/vendor/optcuts/). Runs native/optcuts/test/test_optcuts.js in node - valid UV layouts on a
closed sphere, an open cylinder and a torus (every corner has a UV, no flipped triangle, distortion within the bound,
seams cut the mesh into disks), determinism, the step API and budget stop, bad input refused, the worker's messages,
timings at ~2k / ~10k triangles - and checks that LOKI serves the worker with the worker CSP. Skips the node part
without node. Under 40 s.

    python tests/test_forge_optcuts.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-optcuts-"))
os.environ["LOKI_DATA"] = str(TMP / "data")   # importing the bridge never touches a real data folder
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


VENDOR = REPO / "app" / "ui" / "vendor" / "optcuts"
for name in ("optcuts.wasm", "optcuts_engine.js", "optcuts_worker.js"):
    check("app/ui/vendor/optcuts/%s is there" % name, (VENDOR / name).is_file())
worker = (VENDOR / "optcuts_worker.js").read_text(encoding="utf-8") if (VENDOR / "optcuts_worker.js").is_file() else ""
imports = [line for line in worker.splitlines() if "importScripts(" in line and not line.lstrip().startswith(("*", "/"))]
check("the worker loads only its own engine script",
      imports == ['importScripts("/ui/vendor/optcuts/optcuts_engine.js");'], imports)
for lic in ("native/optcuts/src/LICENSE.txt", "native/optcuts/third_party/libigl/LICENSE.MPL2",
            "native/optcuts/third_party/eigen/COPYING.MPL2", "native/optcuts/third_party/CDT/LICENSE"):
    check("licence kept next to the code: " + lic, (REPO / lic).is_file())

def served_headers():
    """GET the worker, its engine, the module and a page from a real BridgeHandler: status, CSP, type."""
    import http.client
    from http.server import ThreadingHTTPServer

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def __init__(self):
            super().__init__(("127.0.0.1", 0), loki_bridge.BridgeHandler)
            self.state = type("State", (), {"secret": "s3cret", "agent": None})()

    srv = Server()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    saved = (loki_bridge.UI_DIR, loki_bridge.ALLOWED_HOSTS)
    loki_bridge.UI_DIR = REPO / "app" / "ui"
    loki_bridge.ALLOWED_HOSTS = ("127.0.0.1:%d" % srv.server_address[1],)
    res = {}
    try:
        for path in ("/ui/vendor/optcuts/optcuts_worker.js", "/ui/vendor/optcuts/optcuts_engine.js",
                     "/ui/vendor/optcuts/optcuts.wasm", "/ui/vendor/sculpt/sculpt_worker.js"):
            conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            conn.request("GET", path)
            r = conn.getresponse()
            res[path] = (r.status, r.getheader("Content-Security-Policy", ""), r.getheader("Content-Type", ""))
            r.read()
            conn.close()
    finally:
        loki_bridge.UI_DIR, loki_bridge.ALLOWED_HOSTS = saved
        srv.shutdown()
    return res


try:
    import loki_bridge  # noqa: E402
except ImportError as exc:  # engine dependencies missing on this machine
    loki_bridge = None
    print("SKIP bridge checks: %s" % exc)
if loki_bridge is not None:
    check("WORKER_PAGES holds the sculpt worker and the OptCuts worker; pages keep UI_CSP (no WebAssembly)",
          "/ui/vendor/optcuts/optcuts_worker.js" in loki_bridge.WORKER_PAGES
          and loki_bridge.SCULPT_WORKER in loki_bridge.WORKER_PAGES
          and "'wasm-unsafe-eval'" in loki_bridge.SCULPT_WORKER_CSP
          and "'wasm-unsafe-eval'" not in loki_bridge.UI_CSP)
    res = served_headers()
    w, e, m, s = (res["/ui/vendor/optcuts/optcuts_worker.js"], res["/ui/vendor/optcuts/optcuts_engine.js"],
                  res["/ui/vendor/optcuts/optcuts.wasm"], res["/ui/vendor/sculpt/sculpt_worker.js"])
    check("served: the OptCuts worker gets the worker CSP, its engine script does not, the .wasm is application/wasm, "
          "the sculpt worker keeps its CSP",
          w[0] == 200 and w[1] == loki_bridge.SCULPT_WORKER_CSP and e[0] == 200 and "wasm-unsafe-eval" not in e[1]
          and m[0] == 200 and m[2] == "application/wasm" and s[0] == 200 and s[1] == loki_bridge.SCULPT_WORKER_CSP, res)

node = shutil.which("node")
if node:
    r = subprocess.run([node, str(REPO / "native" / "optcuts" / "test" / "test_optcuts.js")],
                       capture_output=True, text=True, timeout=60)
    print(r.stdout.strip())
    check("OptCuts in WebAssembly: test_optcuts.js", r.returncode == 0, (r.stdout + r.stderr)[-600:])
else:
    print("SKIP node part: no node here")

shutil.rmtree(str(TMP), ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
