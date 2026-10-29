"""A tool an agent needs is not installed: LOKI checks it is real, asks the owner in Home > For you, and installs it
itself when he says yes (owner 2026-10-28: "if an agent needs a tool thats not installed they should install it or
prompt to install ive never been asked anything why is this broken"; his rule 8: agents may do everything, but ask
first and say what they're going to do).

What went wrong (the PC, 2026-10-28): a job ran `pip install manga` four times (no such package - `manga` is LOKI's
own command) and the 8B model blamed "pymongo"; the phone-test job wrote "Ask the owner: install the Android SDK"
into qa/mobile-test.md and stopped - nobody was asked; a background job's "ask" was a refusal ("nobody is there to
ask"). What the established agents do: OpenHands / Cline / Goose put an install behind an approval (risk MEDIUM ->
confirm), LangGraph's interrupt() parks the run on a human question, OpenCode's doom-loop asks after 3 repeats.

  parse(command)          `pip install x`, `python -m pip install x`, `npm i -g x`, `winget install x`, `brew install x`,
                          `uv tool install x` -> {manager, names}; None for anything else
  known(manager, name)    LOKI's own commands are never installed (manga, design, playbook, loki-make ...); PyPI / npm
                          are asked whether the package exists (no network: "unknown", the owner decides)
  ask(manager, names, why, cwd)
                          one For you card per package (kind "install"): what, why, the exact command, who asked;
                          the agent gets WAITING FOR THE OWNER and stops (its task waits, it is not retried)
  decide -> approve       LOKI runs the install itself (LOKI's own Python for pip; big things go to the external
                          drive on the Mac via the managers' own settings), the result goes on the card and the task
                          that asked is tried again
Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

OWN_COMMANDS = {"manga", "design", "playbook", "loki", "loki-make", "loki-tools", "make_image", "make_3d", "blender",
                "library", "toolshelf", "asset_pipeline", "render_scene"}
_PIP = re.compile(r"^\s*(?:[\w.:\\/-]*python(?:3(?:\.\d+)?)?(?:\.exe)?\s+-m\s+)?(?:uv\s+)?pip3?\s+install\s+(.+)$", re.I)
_NPM = re.compile(r"^\s*npm\s+(?:i|install)\s+(?:-g|--global)\s+(.+)$", re.I)
_WINGET = re.compile(r"^\s*winget\s+install\s+(.+)$", re.I)
_BREW = re.compile(r"^\s*brew\s+install\s+(.+)$", re.I)
_UVT = re.compile(r"^\s*uv\s+tool\s+install\s+(.+)$", re.I)
MARK = "WAITING FOR THE OWNER"


def parse(command: str) -> dict | None:
    """An install command -> {"manager", "names"}; None when it is not one."""
    cmd = str(command or "").strip()
    cmd = re.split(r"\s*(?:&&|;|\|\|)\s*", cmd)[-1] if re.search(r"install", cmd, re.I) else cmd
    for manager, rx in (("pip", _PIP), ("npm", _NPM), ("winget", _WINGET), ("brew", _BREW), ("uv-tool", _UVT)):
        m = rx.match(cmd)
        if not m:
            continue
        try:
            words = shlex.split(m.group(1), posix=os.name != "nt")
        except ValueError:
            words = m.group(1).split()
        names = [w.strip("'\"") for w in words if w and not w.startswith("-") and w.strip("'\"")]
        if names:
            return {"manager": manager, "names": names[:6]}
    return None


def _http_ok(url: str, timeout: float = 8.0, opener=None) -> bool | None:
    try:
        op = opener or urllib.request.urlopen
        with op(urllib.request.Request(url, headers={"User-Agent": "LOKI"}), timeout=timeout) as r:
            return 200 <= getattr(r, "status", 200) < 300
    except urllib.error.HTTPError as exc:
        return False if exc.code == 404 else None
    except Exception:  # noqa: BLE001 - offline: unknown
        return None


def known(manager: str, name: str, opener=None) -> str:
    """"own" (LOKI's own command - never install), "yes", "no" (does not exist), "unknown" (could not check)."""
    base = re.split(r"[=<>!~\[@ ]", str(name or "").strip(), maxsplit=1)[0].lower()
    if base in OWN_COMMANDS:
        return "own"
    if manager == "pip":
        ok = _http_ok("https://pypi.org/pypi/%s/json" % base, opener=opener)
    elif manager in ("npm",):
        ok = _http_ok("https://registry.npmjs.org/%s" % base.replace("/", "%2f"), opener=opener)
    else:
        return "unknown"
    return "yes" if ok else ("no" if ok is False else "unknown")


def command_for(manager: str, names: list, python: str = "") -> list:
    py = python or os.getenv("LOKI_ENGINE_PYTHON") or sys.executable
    if manager == "pip":
        return [py, "-m", "pip", "install", "--disable-pip-version-check", *names]
    if manager == "npm":
        return [shutil.which("npm") or "npm", "install", "-g", *names]
    if manager == "winget":
        return ["winget", "install", "--accept-package-agreements", "--accept-source-agreements", "-e", "--id", *names]
    if manager == "brew":
        return [shutil.which("brew") or "brew", "install", *names]
    if manager == "uv-tool":
        return [shutil.which("uv") or "uv", "tool", "install", *names]
    raise ValueError("unknown manager %s" % manager)


def ask(manager: str, names: list, why: str = "", cwd: str = "", opener=None) -> dict:
    """What the agent gets back instead of running the install itself."""
    own = [n for n in names if known(manager, n, opener) == "own"]
    if own:
        return {"ok": False, "own": own,
                "error": "`%s` is LOKI's own command - it is already on your PATH, never install it. Run `loki-make help "
                         "%s` to see how to use it." % (own[0], own[0])}
    missing = [n for n in names if known(manager, n, opener) == "no"]
    if missing:
        return {"ok": False, "missing": missing,
                "error": "%s has no package called %s - do not try again. Find the right name (search the web) or use "
                         "another way." % ({"pip": "PyPI", "npm": "npm"}.get(manager, manager), ", ".join(missing))}
    import owner_review  # pylint: disable=import-outside-toplevel
    cmd = command_for(manager, names)
    for it in owner_review.items(owner_review.OPEN):     # one open card per install
        if it["kind"] == "install" and it["args"].get("manager") == manager and it["args"].get("names") == names:
            card = it
            break
    else:
        card = owner_review.queue("install", "install", {"manager": manager, "names": names, "command": cmd,
                                                         "why": str(why or "")[:600]}, str(cwd or "."))
    return {"ok": False, "waiting_for_owner": True, "review": card["id"],
            "error": "%s: installing %s (%s) is in Home > For you with why you need it. The owner says yes or no; on "
                     "yes LOKI installs it itself and tries this task again. Do NOT install it another way and do not "
                     "ask again - stop here and say BLOCKED: waiting for the owner to approve installing %s."
                     % (MARK, ", ".join(names), manager, ", ".join(names))}


def run_install(it: dict, runner=subprocess.run, timeout: float = 1800.0) -> dict:
    """The owner said yes: install it. Returns {ok, output}."""
    args = it.get("args") or {}
    cmd = list(args.get("command") or command_for(args.get("manager", "pip"), list(args.get("names") or [])))
    try:
        done = runner(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        out = ((done.stdout or "") + "\n" + (done.stderr or "")).strip()
        return {"ok": done.returncode == 0, "output": out[-3000:], "exit": done.returncode}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "output": "%s: %s" % (type(exc).__name__, exc), "exit": 127}


def _finish(it: dict, res: dict, on_done=None) -> None:
    import owner_review  # pylint: disable=import-outside-toplevel
    fresh = owner_review.get(it["id"]) or it
    fresh.update(status="done" if res["ok"] else "failed", finished=time.time(),
                 answer=("installed: " if res["ok"] else "the install failed: ") + res["output"][-600:])
    owner_review._save(fresh)   # pylint: disable=protected-access
    if on_done is not None:
        try:
            on_done(fresh, res)
        except Exception:  # noqa: BLE001
            pass


def handle(it: dict, action: str, data: dict, runner=subprocess.run, on_done=None, background: bool = False) -> dict:
    """owner_review's handler for "install" cards: approve -> install (in the background in the engine: the card says
    "installing" until it is done); reject / park -> nothing is installed and the agent's task is told."""
    action = str(action or "").lower()
    if action in ("reject", "park"):
        return {"ok": True, "status": "rejected" if action == "reject" else "parked",
                "answer": "the owner said no%s" % ((": " + data.get("note")) if data.get("note") else "")}
    if action != "approve":
        return {"ok": False, "error": "an install is approved, rejected or parked"}
    if background:
        threading.Thread(target=lambda: _finish(it, run_install(it, runner=runner), on_done), daemon=True,
                         name="loki-install").start()
        return {"ok": True, "status": "working", "answer": "installing..."}
    res = run_install(it, runner=runner)
    _finish(it, res, on_done)
    return {"ok": True, "status": "done" if res["ok"] else "failed",
            "answer": ("installed: " if res["ok"] else "the install failed: ") + res["output"][-600:]}


def register(on_done=None) -> None:
    """Install cards work in this process (the engine calls this at start)."""
    import owner_review  # pylint: disable=import-outside-toplevel
    owner_review.HANDLERS["install"] = lambda it, action, data: handle(it, action, data, on_done=on_done,
                                                                       background=True)


