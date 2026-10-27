"""One heavy job at a time, only with memory free (owner 2026-10-26: "you crashed my computer ... you used all my
vram" - a local FLUX.2 model, Blender polish and renders ran at once on the 16 GB Mac). Offline, seconds.

    python tests/test_heavy.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-heavy-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
PASS, FAIL = [], []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %r" % (detail,)))


import heavy  # noqa: E402

VM = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               12000.
Pages active:                            400000.
Pages inactive:                           50000.
Pages speculative:                         3000.
Pages purgeable:                           1000."""
check("free memory read from macOS vm_stat (free + inactive + speculative + purgeable)", heavy.available_gb(VM) == round(66000 * 16384 / 2**30, 2), heavy.available_gb(VM))
with heavy.slot("one", free=lambda: 50.0):
    held = heavy.holder()
    with heavy.slot("inner", free=lambda: 50.0):
        check("re-entrant inside one process (a stage that calls a tool)", heavy.holder() == held)
    check("this process's own hold is not 'busy' for itself", heavy.busy() == "")
check("released after", not heavy.lock_path().exists())

# another live process holds it
other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
heavy.lock_path().parent.mkdir(parents=True, exist_ok=True)
heavy.lock_path().write_text(json.dumps({"pid": other.pid, "what": "blender polish", "t": time.time()}))
check("another process's slot shows as busy (schedulers skip)", "blender polish" in heavy.busy(), heavy.busy())
t = {"now": 0.0}
try:
    with heavy.slot("render", wait_s=20, poll_s=5, sleep=lambda s: t.update(now=t["now"] + s), clock=lambda: t["now"], free=lambda: 50.0):
        check("waits while another job runs", False)
except heavy.Busy as exc:
    check("waits while another job runs, then says why it did not start", "busy with blender polish" in str(exc), str(exc))
other.kill()
other.wait()
with heavy.slot("render", free=lambda: 50.0):
    check("a dead holder's lock is taken over", heavy.holder().get("what") == "render")
t["now"] = 0.0
try:
    with heavy.slot("local model", wait_s=10, poll_s=5, sleep=lambda s: t.update(now=t["now"] + s), clock=lambda: t["now"],
                    free=lambda: 2.0, need_gb=5.0):
        check("never starts with too little free memory", False)
except heavy.Busy as exc:
    check("never starts with too little free memory (2 GB free, needs 5)", "only 2.0 GB free" in str(exc) and not heavy.lock_path().exists(), str(exc))
os.environ["LOKI_HEAVY_MIN_FREE_GB"] = "7"
check("the floor can be set (LOKI_HEAVY_MIN_FREE_GB)", heavy.min_free_gb() == 7.0)
os.environ.pop("LOKI_HEAVY_MIN_FREE_GB")

import creative  # noqa: E402
check("a LOCAL FLUX.2 edit is off unless asked for", "off" in creative.mflux_edit_allowed({"ram_gb": 64}, {}))
check("... and never on a 16 GB machine (it crashed the Mac)", "16 GB" in creative.mflux_edit_allowed({"ram_gb": 16}, {"LOKI_MFLUX_EDIT": "on"}))
check("... allowed with LOKI_MFLUX_EDIT=on and more memory", creative.mflux_edit_allowed({"ram_gb": 32}, {"LOKI_MFLUX_EDIT": "on"}) == "")
src = {f: (REPO / "engine" / f).read_text(encoding="utf-8") for f in ("blender_link.py", "creative.py", "region_edit.py",
                                                                     "render_agent.py", "forge3d.py", "asset_pipeline.py", "autopilot.py")}
check("Blender, local image models, area edits, render passes and TripoSR all take the slot",
      all("heavy.slot(" in src[f] for f in ("blender_link.py", "creative.py", "region_edit.py", "render_agent.py", "forge3d.py")))
check("the pipeline and the autopilot do not start a stage while heavy work runs",
      "heavy.busy()" in src["asset_pipeline.py"] and 'r["lane"] == "gpu" for r in self.running_work()' in src["autopilot.py"])
tasks = (REPO / "LOKI_TASKS.md").read_text(encoding="utf-8")
check("the local FLUX.2 request is gone from LOKI's tasks", "Local FLUX.2 klein edits on the Mac" not in tasks)
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
