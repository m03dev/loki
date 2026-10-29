"""A missing tool: LOKI checks it is real, asks the owner in Home > For you, installs it itself on yes and runs the task
again (owner 2026-10-28: "if an agent needs a tool thats not installed they should install it or prompt to install
ive never been asked anything"). Uses the PC's real failure (job 301722c1: `pip install manga` four times). No network:
PyPI is a stand-in. Under a minute.

    python tests/test_installs.py
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import time
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-installs-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_JOB_ID"] = "job301"
PASS: list = []
FAIL: list = []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import owner_review  # noqa: E402
import installs  # noqa: E402

check("install commands are recognised (pip, python -m pip, npm -g, winget)",
      installs.parse("pip install manga") == {"manager": "pip", "names": ["manga"]}
      and installs.parse(r"D:\loki\harness_data\.venv\Scripts\python.exe -m pip install rembg==2.0")["names"] == ["rembg==2.0"]
      and installs.parse("npm install -g @mobilenext/mobile-mcp")["manager"] == "npm"
      and installs.parse("winget install Google.PlatformTools")["manager"] == "winget"
      and installs.parse("cd x && pip install rich")["names"] == ["rich"])
check("... and other commands are not", installs.parse("python tests/test_manga.py") is None
      and installs.parse("git status") is None)


class _R:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


def pypi(req, timeout=0):
    url = req.full_url
    if url.endswith("/rich/json") or "registry.npmjs.org" in url:
        return _R()
    raise urllib.error.HTTPError(url, 404, "nf", {}, io.BytesIO(b""))


r = installs.ask("pip", ["manga"], "make the manga", str(TMP), opener=pypi)
check("`pip install manga` (the PC's loop): manga is LOKI's own command - never installed, the agent is told how to "
      "use it", not r["ok"] and r.get("own") == ["manga"] and "loki-make help manga" in r["error"], r)
r = installs.ask("pip", ["pymangaxyz"], "x", str(TMP), opener=pypi)
check("a package PyPI does not have: no card, the agent is told not to try again", r.get("missing") == ["pymangaxyz"]
      and not owner_review.items(owner_review.OPEN), r)
r = installs.ask("pip", ["rich"], "pretty tables for the report", str(TMP), opener=pypi)
cards = [it for it in owner_review.items(owner_review.OPEN) if it["kind"] == "install"]
check("a real package: ONE install card in For you with what, why and the exact command; the agent waits",
      r.get("waiting_for_owner") and len(cards) == 1 and cards[0]["args"]["names"] == ["rich"]
      and "pretty tables" in cards[0]["args"]["why"] and "pip" in " ".join(cards[0]["args"]["command"])
      and installs.MARK in r["error"], (r, cards))
installs.ask("pip", ["rich"], "again", str(TMP), opener=pypi)
check("... asking again is the same card", len([it for it in owner_review.items(owner_review.OPEN)
                                                if it["kind"] == "install"]) == 1)
check("... and the job's task counts as waiting for the owner (not failed, not retried)",
      owner_review.waiting_for_jobs(["job301"]) != [])

ran, done = [], []


class _Done:
    returncode, stdout, stderr = 0, "Successfully installed rich-14.0", ""


installs.register(on_done=lambda it, res: done.append((it["id"], res["ok"])))
owner_review.HANDLERS["install"] = lambda it, action, data: installs.handle(
    it, action, data, runner=lambda cmd, **kw: (ran.append(cmd), _Done())[1],
    on_done=lambda it2, res: done.append((it2["id"], res["ok"])))
out = owner_review.decide(cards[0]["id"], "approve")
check("the owner says Install: LOKI runs the install itself and the card says what happened",
      out.get("ok") and ran and ran[0][-1] == "rich" and out["item"]["status"] == "done"
      and "installed" in out["item"].get("answer", ""), out)
check("... and the task that asked is told to run again", done == [(cards[0]["id"], True)], done)
r = installs.ask("pip", ["rich"], "x", str(TMP), opener=pypi)
c2 = r.get("review")
out = owner_review.decide(c2, "reject", note="use the stdlib")
check("the owner says No: nothing is installed", out.get("ok") and out["item"]["status"] == "rejected" and len(ran) == 1, out)

import opencode_engine  # noqa: E402
cfg = opencode_engine.build_config({}, "", False, [], workspace=str(TMP))
check("OpenCode agents cannot run a raw pip / npm -g / winget install (they use the install tool)",
      cfg["permission"]["bash"].get("*pip install *") == "deny" and cfg["permission"]["bash"].get("*winget install*") == "deny")
import make_mcp  # noqa: E402
check("the install tool is offered to every agent", any(t["name"] == "install" for t in make_mcp.TOOLS))
check("this suite stays under 60 s", time.time() - T0 < 60, time.time() - T0)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
