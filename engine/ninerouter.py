"""9Router (github.com/decolua/9router, MIT) as one of LOKI's model providers - the owner, 2026-10-18: "get 9router".

9Router is a local router in front of 40+ providers (your Claude Code / Codex / Copilot / Cursor subscriptions, free
tiers like Kiro and OpenCode Free, and API keys) with its own fallback chains ("combos") and tool-output compression.
It speaks the OpenAI API, so LOKI talks to it like any provider: MODELS["9router"] (engine/loki.py), base
http://127.0.0.1:20128/v1, the key from 9Router's dashboard (NINEROUTER_API_KEY), model NINEROUTER_MODEL (default
"loki": make a combo with that name in 9Router; when there is none LOKI uses the first model 9Router lists).

It is a separate Node program, installed by `python tools/setup_extras.py 9router` into harness_data/addons/9router
(never global, never the repo) at a pinned version. Its own code is not copied into LOKI.

Safety, because 9Router <= 0.4.41 let anyone who could reach its port read every key (CVE-2026-62328):
  * LOKI pins a version past that (PACKAGE) and starts it bound to 127.0.0.1 only (9Router's default is 0.0.0.0,
    which puts its dashboard on your Wi-Fi) with --skip-update, so it never replaces itself with an unchecked build.
  * LOKI never publishes its port on the relay or the peer link.
Routing your own subscriptions through a third-party router can break those services' terms; that is the owner's
call per account, made inside 9Router's dashboard.

LOKI_9ROUTER: auto (default: start it when it is installed and not running) | on | off.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

PACKAGE = "9router@0.5.104"
PORT = 20128
HOST = "127.0.0.1"


def _data() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


def prefix() -> Path:
    return _data() / "addons" / "9router"


def binary() -> Path | None:
    """The installed 9router command, or None."""
    names = ["9router.cmd", "9router"] if sys.platform == "win32" else ["9router"]
    for name in names:
        path = prefix() / "node_modules" / ".bin" / name
        if path.is_file():
            return path
    return None


def port() -> int:
    try:
        return int(os.getenv("NINEROUTER_PORT", "") or PORT)
    except ValueError:
        return PORT


def base_url() -> str:
    return os.getenv("NINEROUTER_BASE_URL", "").strip() or "http://%s:%d/v1" % (HOST, port())


def dashboard_url() -> str:
    return "http://%s:%d/dashboard" % (HOST, port())


def argv(command: Path | str) -> list:
    """How LOKI starts it: loopback only, no browser, no self-update (the version is LOKI's pin)."""
    return [str(command), "--host", HOST, "--port", str(port()), "--no-browser", "--skip-update"]


def running(timeout: float = 1.0) -> bool:
    """Something answers on 9Router's port (any HTTP status counts: /v1/models may want the key)."""
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                urllib.request.Request(base_url().rstrip("/") + "/models", headers={"User-Agent": "Loki/1.0"}),
                timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except (OSError, ValueError):
        return False


def mode() -> str:
    value = os.getenv("LOKI_9ROUTER", "auto").strip().lower()
    return value if value in ("auto", "on", "off") else "auto"


def start(popen=None) -> dict:
    """Start 9Router in the background when it is installed and not running. Never raises."""
    if mode() == "off":
        return {"ok": False, "started": False, "why": "LOKI_9ROUTER=off"}
    if running():
        return {"ok": True, "started": False, "why": "already running", "url": base_url()}
    command = binary()
    if command is None:
        return {"ok": False, "started": False, "why": "not installed (python tools/setup_extras.py 9router)"}
    log = _data() / "addons" / "9router.log"
    kwargs: dict = {"stdin": subprocess.DEVNULL, "close_fds": True, "cwd": str(prefix())}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        out = open(log, "ab")  # noqa: SIM115 - handed to the child
        (popen or subprocess.Popen)(argv(command), stdout=out, stderr=subprocess.STDOUT, **kwargs)  # noqa: S603
    except OSError as exc:
        return {"ok": False, "started": False, "why": "could not start it: %s" % exc}
    return {"ok": True, "started": True, "url": base_url(), "dashboard": dashboard_url(), "log": str(log)}


def start_background() -> None:
    """The engine calls this once at start; a missing or broken 9Router never delays LOKI."""
    def go() -> None:
        result = start()
        if result.get("started"):
            print("[loki-bridge] 9router started on %s (dashboard %s)" % (base_url(), dashboard_url()), flush=True)
    threading.Thread(target=go, daemon=True, name="loki-9router").start()
