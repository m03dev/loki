"""Two LOKI windows on one machine (the PC, 2026-10-28 00:18): the second window updated the folder with the old
updater (patch 610 = master + a stray commit), started a second engine, which crashed 5 times into the first (port
busy) and the app gave up - the first engine kept running old code with nothing to apply.

  1. a second engine on a busy port exits with ALREADY_RUNNING (73), not a crash
  2. the app waits for a BUSY engine (port open, slow /health) instead of starting a second one
  3. the app's supervisor attaches on exit 73 instead of counting crashes
  4. an engine whose folder changed under it (or that carries a local commit, mirror mode) heals itself:
     heal_reason() says why, so the loop updates + restarts
"""
import os
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "app"))

FAILS = []
PASSES = 0


def check(name, ok, detail=""):
    global PASSES
    if ok:
        PASSES += 1
        print("  PASS", name)
    else:
        FAILS.append(name)
        print("  FAIL", name, " <-", str(detail)[:200])


src = (ROOT / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("a second engine on a busy port exits with its own code (73), not RuntimeError -> 'crash'",
      "raise SystemExit(ALREADY_RUNNING_EXIT_CODE)" in src and "ALREADY_RUNNING_EXIT_CODE = 73" in src)

import loki_app  # noqa: E402

check("the app and the engine agree on the code", loki_app.ALREADY_RUNNING_EXIT_CODE == 73)

# 2. a busy engine: the port is open, /health answers late
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5)
port = srv.getsockname()[1]
loki_app.HOST, loki_app.PORT = "127.0.0.1", port
check("port_open() sees a listening engine even when it does not answer HTTP", loki_app.port_open())
calls = []
real_probe = loki_app.probe
loki_app.probe = lambda token, timeout=1.5: (calls.append(timeout), 200 if len(calls) >= 3 else 0)[1]
t0 = time.monotonic()
got = loki_app.answer_slowly("tok", wait_s=10)
check("a busy engine is waited for (several longer asks) instead of being taken for 'nothing runs'",
      got == 200 and len(calls) >= 3 and max(calls) >= 5.0, (got, calls))
srv.close()
loki_app.probe = real_probe
check("a closed port is not waited for", loki_app.answer_slowly("tok", wait_s=5) == 0 and time.monotonic() - t0 < 12)

# bring_up_engine never starts a second engine while one listens
srv = socket.socket(); srv.bind(("127.0.0.1", port)); srv.listen(5)
started = []
loki_app.read_token = lambda: "tok"
seq = iter([0, 200, 200, 200, 200])
loki_app.probe = lambda token, timeout=1.5: next(seq, 200)
loki_app.stale_engine = lambda token: False
loki_app.start_and_wait = lambda *a: (started.append(1), (None, ""))[1]
loki_app.log = lambda *a: None
tok, title, _ = loki_app.bring_up_engine(Path("."), {}, threading.Event())
check("first /health too slow, port open -> attaches, starts no second engine", tok == "tok" and not started, (tok, title, started))
srv.close()

# 3. supervisor on exit 73
class P:
    def __init__(self, code): self.code = code
    def poll(self): return self.code
shown = []
loki_app.show_url = lambda url: shown.append(url)
loki_app.window_url = lambda token: "loki://" + token
loki_app.answer_slowly = lambda token, wait_s=25.0: 200
loki_app.take_over = lambda token: "attach"
holder = {"process": P(73)}
loki_app.supervise(holder, Path("py"), Path("."), "", threading.Event())
check("exit 73 -> the window attaches to the running engine; no crash counted, no restart loop",
      shown == ["loki://tok"] and not holder.get("crashes") and holder.get("process") is None, (shown, holder))

# 4. self-heal
import updater  # noqa: E402

updater.RUNNING_COMMIT = "caf1fc88ae41aaaaaaaaaaaaaaaaaaaaaaaaaaaa"
real_version = updater.version
updater.version = lambda repo=None: {"commit": "c5ffff296a0e4ae289776eb400e8a2e5b4788428"}
check("the folder was updated under the running engine -> it restarts on the new code (the PC's stuck engine)",
      "newer code" in updater.heal_reason({"ahead": 0}))
updater.RUNNING_COMMIT = "c5ffff296a0e4ae289776eb400e8a2e5b4788428"
check("a local commit on top of master -> back to exactly master (the PC's patch 610)",
      "exactly master" in updater.heal_reason({"ahead": 1}))
os.environ["LOKI_UPDATE_EXACT"] = "0"
check("... not in developer mode (LOKI_UPDATE_EXACT=0)", updater.heal_reason({"ahead": 1}) == "")
os.environ.pop("LOKI_UPDATE_EXACT")
check("nothing to heal -> nothing happens", updater.heal_reason({"ahead": 0}) == "")
updater.version = real_version

print("\n%d passed, %d failed" % (PASSES, len(FAILS)))
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    sys.exit(1)
