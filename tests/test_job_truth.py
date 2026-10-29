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
import task_board  # noqa: E402
check("the board spots the old fake stamp (DONE: <its own first line>) and never an agent's own DONE",
      task_board.stamped("I'll start by exploring the project.\n\nTools run: 10 ok.\n\nDONE: I'll start by exploring the project.")
      and not task_board.stamped("Made the sprite.\nDONE: sprites/fox.png") and not task_board.stamped("DONE: wrote it"))
check("the chat gets the strongest model: an old local pin becomes Smart once (Claude Code / Goose / aider all give the "
      "main conversation the strong model)", loki.chat_model_default("local-reasoning", {}) == "smart"
      and loki.chat_model_default("local-reasoning", {"LOKI_CHAT_ROLE_V2": "1"}) == "local-reasoning"
      and loki.chat_model_default("local", {"LOKI_LOCAL_ONLY": "1"}) == "local" and loki.chat_model_default("nvidia", {}) == "nvidia")
import ratelimit  # noqa: E402
os.environ["LOKI_RATE_FILE_DIR"] = str(TMP / "rl")
os.environ["LOKI_JOB_ID"] = "x"
ratelimit.reset("nvidia")
for _ in range(ratelimit.rpm("nvidia") - ratelimit.chat_reserve()):
    ratelimit.take("nvidia")
job_waits = ratelimit.wait_s("nvidia") > 0
os.environ.pop("LOKI_JOB_ID")
check("a background job leaves NVIDIA's last requests a minute for the chat (it waits; the chat does not)",
      job_waits and ratelimit.wait_s("nvidia") == 0)
import chat_media  # noqa: E402
import io  # noqa: E402
from PIL import Image  # noqa: E402
_buf = io.BytesIO(); Image.new("RGB", (64, 64), "red").save(_buf, "PNG"); _png = _buf.getvalue()
check("a picture a maker is still writing is not shown as a (blank) preview; the whole one is",
      not chat_media.complete_image(_png[: len(_png) // 2]) and chat_media.complete_image(_png))


class _Resp:
    headers = {"Content-Type": "image/png"}

    def __init__(self, b): self.b = b
    def read(self, n=-1): return self.b
    def __enter__(self): return self
    def __exit__(self, *a): return False


_st = type("S", (), {"agent": type("A", (), {"DATA_DIR": str(TMP / "d")})()})()
_ref = chat_media.reference(_st, "https://cms-assets.example.com/a.png", opener=lambda req, timeout=0: _Resp(_png))
check("a web reference picture comes to the window as data (its CSP blocks web pictures), cached",
      _ref["data_url"].startswith("data:image/png;base64,") and any((TMP / "d" / "refcache").glob("*.png")))
try:
    chat_media.reference(_st, "http://127.0.0.1/x.png")
    check("only https web pictures are fetched", False)
except chat_media.MediaError:
    check("only https web pictures are fetched", True)
os.environ["LOKI_JOB_ID"] = "x"
_prov = {"nvidia": {"base_url": "https://integrate.api.nvidia.com/v1"}, "local": {"base_url": "http://127.0.0.1:11434/v1"},
         "groq": {"base_url": "https://api.groq.com/openai/v1"}}
_pid = loki.opencode_engine.provider_id
check("a job never leaves a slow capable route for the local model only",
      not loki._slow_may_move("nvidia", ["%s/q" % _pid("local")], _prov)
      and loki._slow_may_move("nvidia", ["%s/q" % _pid("groq"), "%s/q" % _pid("local")], _prov))
os.environ.pop("LOKI_JOB_ID")
check("the chat may still move off a slow route", loki._slow_may_move("nvidia", ["%s/q" % _pid("local")], _prov))
_ui = REPO / "app" / "ui"
_lazy = [f.name for f in _ui.glob("*.js") if 'loading = "lazy"' in f.read_text(encoding="utf-8")]
check("no lazy pictures in the window (WebKit, the Mac's window, never loads them inside a scrolling panel: blank "
      "For you previews)", not _lazy, _lazy)
_hr = (_ui / "home_review.js").read_text(encoding="utf-8")
check("For you resolves a card's relative files against the card's own folder", "media(f, img, it)" in _hr
      and "it.cwd" in _hr)
import team  # noqa: E402
_old = team.present({"id": "t1", "goal": "a manga", "roles": ["art_manga_writer", "builder"], "status": "done"}, {})
check("a saved team naming a retired role still shows (the PC's status call broke 78 times on art_manga_writer)",
      _old["roles"][0].startswith("Manga Writer") and _old["roles"][1] == "Builder", _old.get("roles"))
_pc, _orig = loki.provider_configured, dict(loki.MODELS)
os.environ.update(LOKI_JOB_ID="x", LOKI_MACHINE_ROLE="light")
loki.MODELS["pc-local"] = loki.ModelConfig(base_url="http://127.0.0.1:9/v1", api_key="peer", model="pc-local")
loki.MODELS["nvidia"] = loki.ModelConfig(base_url="https://integrate.api.nvidia.com/v1", api_key="x", model="m")
loki.provider_configured = lambda n: n in ("pc-local", "local", "nvidia")
_seen = list(loki._oc_providers("nvidia"))
check("a Mac job with the PC's model never loads the Mac's own local model (rule 7)", "pc-local" in _seen
      and not any(n in loki.LOCAL_PROVIDERS for n in _seen), _seen)
loki.provider_configured = _pc; loki.MODELS.clear(); loki.MODELS.update(_orig)
os.environ.pop("LOKI_JOB_ID"); os.environ.pop("LOKI_MACHINE_ROLE")
check("this suite stays under 60 s", time.time() - T0 < 60, time.time() - T0)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
