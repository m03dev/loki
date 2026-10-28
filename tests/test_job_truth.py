"""A job's DONE must be true (owner 2026-10-28: "jobs finished but nothing happened why is it fake results? i thought we
fixed this problem"). Built from the Mac's real jobs that day:

  1d23380d  the local 9B model read a few files, looped on a tool it does not have, was stopped as stuck - and the
            job list said "DONE: I'll start by exploring the project structure ..."
  14a65457  NVIDIA, 25 minutes, read and tested, quit mid-investigation, changed nothing - "DONE: I used URL-encoded
            paths (%20) ..."

and from the three causes behind them: LOKI stamped DONE on any job where one tool had run; one long turn benched the
only route that worked ("out" for an hour) so jobs fell to the local model; that local model was not recognised as
local (it is not on Ollama's port) and ran inside OpenCode. Under a minute.

    python tests/test_job_truth.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-truth-"))
os.environ.setdefault("LOKI_DATA", str(TMP / "data"))
PASS: list = []
FAIL: list = []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import loki  # noqa: E402
import provider_speed  # noqa: E402
import dsh_engine  # noqa: E402

# ----------------------------------------------------------------------------- the Mac's two "done" jobs
stuck = ("I'll start by exploring the project structure and reading the authoritative docs to understand what auth "
         "integration is expected, then implement it.\n\nTools run: 10 ok.")
out = loki._job_outcome(stuck, [], "stuck: the same error 3 times: invalid tool codegraph_explore")
check("a job stopped as stuck is BLOCKED, with why - never DONE", loki.reply_outcome(out) == "blocked"
      and "stopped before it finished" in out and "stuck" in out and "Nothing in the folder" in out, out)
quit_ = ("I used URL-encoded paths (`%20`). Let me use the real paths with spaces.\n\n28 passed, 2 failed. Let me "
         "investigate the 2 failures.\n\nTools run: 11 ok, 4 failed.")
out = loki._job_outcome(quit_, [])
check("a job that quit mid-work and changed nothing is BLOCKED", loki.reply_outcome(out) == "blocked"
      and "never said DONE" in out, out)
check("... and no reply first line is ever turned into a DONE line", "DONE: I used" not in out and "DONE: I'll" not in out)

# ----------------------------------------------------------------------------- the evidence decides
out = loki._job_outcome("Wrote the sprite.\nDONE: sprites/fox.png", [("made", "sprites/fox.png")])
check("DONE with the file really made stays DONE, and says what changed", loki.reply_outcome(out) == "done"
      and "sprites/fox.png" in out, out)
out = loki._job_outcome("DONE: made sprites/fox.png", [])
check("DONE but nothing in the folder changed -> BLOCKED", loki.reply_outcome(out) == "blocked" and "did not happen" in out, out)
out = loki._job_outcome("Ran the suite: 28 passed, 0 failed.\nDONE: checked, all tests pass", [])
check("a DONE that is a check or a report needs no new file", loki.reply_outcome(out) == "done", out)
out = loki._job_outcome("Created loki-test-repo and committed it.", [("made", "loki-test-repo/README.md")])
check("no DONE line but the work is really on disk -> DONE, marked as checked by LOKI", loki.reply_outcome(out) == "done"
      and "LOKI checked the folder" in out, out)
out = loki._job_outcome("Indexing ...", [("made", ".codegraph/index.db"), ("changed", ".loki/messages/m.md")])
check("LOKI's own index / message files are not work", loki.reply_outcome(out) == "blocked", out)
out = loki._job_outcome("BLOCKED: the ComfyUI server is down", [])
check("an honest BLOCKED stays BLOCKED", loki.reply_outcome(out) == "blocked" and out.startswith("BLOCKED"), out)
out = loki._job_outcome("NOT DONE - OpenCode stopped: 404", [])
check("NOT DONE is BLOCKED", loki.reply_outcome(out) == "blocked", out)

# ----------------------------------------------------------------------------- the snapshot really sees changes
ws = TMP / "ws"
(ws / "images").mkdir(parents=True)
before = dsh_engine.snapshot(ws)
(ws / "images" / "golem.png").write_bytes(b"\x89PNG")
ch = dsh_engine.changes(before, dsh_engine.snapshot(ws))
check("LOKI's before/after look at the folder finds the new file", ("made", os.path.join("images", "golem.png")) in ch, ch)

# ----------------------------------------------------------------------------- one long turn never benches the only route
d = TMP / "speed"
provider_speed.mark_out(d, "nvidia", "timed out after 1200s")
provider_speed.mark_out(d, "nvidia-pro", 'LOKI proxy: host answered 404: Function x: Not found for account y')
check("a timeout makes a route slow, not out", provider_speed.is_slow(d, "nvidia") and not provider_speed.is_out(d, "nvidia"))
check("so the only working cloud route stays in the line (last), the 404 one is left off",
      provider_speed.order(d, ["nvidia-pro", "nvidia", "local"], keep=("local",)) == ["local", "nvidia"],
      provider_speed.order(d, ["nvidia-pro", "nvidia", "local"], keep=("local",)))
import json  # noqa: E402
(d / "provider_speed.json").write_text(json.dumps({"nvidia": {"t": time.time(), "slow_until": time.time() + 3000,
                                                               "out": "timed out after 1200s"}}))
check("a timeout an older LOKI recorded as 'out' counts as slow only", not provider_speed.is_out(d, "nvidia"))

# ----------------------------------------------------------------------------- the local model is recognised as local
check("a local model on another port (MLX / LM Studio) is local", loki._cfg_is_local(type("C", (), {"base_url": "http://127.0.0.1:8080/v1"})()))
loki.JOB_DEADLINE_AT = time.monotonic() + 7140
check("a job's OpenCode turn gets the job's own time, not a flat 20 minutes", loki._turn_timeout() > 6000, loki._turn_timeout())
loki.JOB_DEADLINE_AT = 0
import art_specialists  # noqa: E402
check("a UI design job ('render a login screen') never goes to the 3D Lighting / Render specialist",
      art_specialists.for_goal("Design (OpenPencil) proof: render a dark login screen for the LOKI phone app") == [])
check("this suite stays under 60 s", time.time() - T0 < 60, time.time() - T0)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
