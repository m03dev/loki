"""Loki - the standalone desktop app.

Starts the Loki engine (engine/loki_bridge.py) on 127.0.0.1:8767 and opens the Loki
window on it. Godot is an optional capability for game projects: it is handed to the
engine only when one is found, so the game tools can light up.

    python app/loki_app.py                 # the window (pywebview), or a browser fallback
    python app/loki_app.py --workspace DIR # work in DIR instead of ~/LOKI Projects/Home
    python app/loki_app.py --print-url     # start the engine and print the window URL

Standard library only, apart from the optional `pywebview` window.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# Packaged builds (PyInstaller, see packaging/loki.spec) carry the repo tree inside the
# bundle and keep user data in a per-user folder, because the install folder may be
# read-only. FROZEN is True there.
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    REPO = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    APP_DIR = REPO / "app"
else:
    APP_DIR = Path(__file__).resolve().parent
    REPO = APP_DIR.parent
HARNESS = REPO / "engine"
ENGINE = REPO / "engine" / "loki_bridge.py"
UI_DIR = APP_DIR / "ui"


def default_data_dir() -> Path:
    if not FROZEN:
        return REPO / "harness_data"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "Loki"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Loki"
    return Path.home() / ".local" / "share" / "loki"


DATA = Path(os.environ.get("LOKI_DATA") or default_data_dir())
STATE = DATA / "app"
TOKEN_FILE = STATE / "engine.token"
SETTINGS_FILE = STATE / "settings.json"
LOG_FILE = STATE / "loki_app.log"
# The app's engine port (the engine's own default, 8766, is left free for a CLI run).
HOST, PORT = "127.0.0.1", int(os.environ.get("LOKI_APP_PORT", "8767") or 8767)
BASE = f"http://{HOST}:{PORT}"
ENGINE_START_TIMEOUT_S = 180


def log(message: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + message
    print("[loki-app] " + message, file=sys.stderr, flush=True)
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------- settings
def load_settings() -> dict:
    try:
        value = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict) -> None:
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError:
        pass


def choose_workspace(cli_value: str = "", settings: dict | None = None, env: dict | None = None) -> Path:
    """--workspace, else the remembered one, else $LOKI_WORKSPACE, else ~/LOKI Projects/Home.

    Never ~/Loki: a folder named after the app is easily mistaken for the app itself
    (that is how a game project ended up looking like Loki)."""
    settings = settings if settings is not None else {}
    env = env if env is not None else os.environ
    for candidate in (cli_value, settings.get("workspace", ""), env.get("LOKI_WORKSPACE", "")):
        if str(candidate or "").strip():
            return Path(str(candidate)).expanduser().resolve()
    return (Path.home() / "LOKI Projects" / "Home").resolve()


def adopt_old_chats(workspace: Path, home: Path | None = None) -> list[str]:
    """Bring chats from the old default workspace (~/Loki/.godot) into <workspace>/.loki.

    Copies only when the new place has none yet; the old files are never touched."""
    old_dir = (home or Path.home()) / "Loki" / ".godot"
    copied = []
    for name in ("loki_conversations.json", "loki_history.json"):
        old, new = old_dir / name, workspace / ".loki" / name
        if old.is_file() and not new.exists():
            try:
                new.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old, new)
                copied.append(name)
            except OSError:
                pass
    return copied


# --------------------------------------------------------------------- discovery
def engine_python() -> Path | None:
    """The interpreter of Loki's private environment (setup.sh / setup.bat make it).
    A packaged build is its own interpreter: it runs the engine as `Loki --engine`."""
    if FROZEN:
        return Path(sys.executable)
    for candidate in (DATA / ".venv" / "bin" / "python3", DATA / ".venv" / "bin" / "python",
                      DATA / ".venv" / "Scripts" / "python.exe"):
        if candidate.is_file():
            return candidate
    return None


def find_godot(env: dict | None = None) -> str:
    """Optional. A Godot binary for the game tools, or "" when there is none."""
    env = env if env is not None else os.environ
    explicit = env.get("LOKI_GODOT", "") or env.get("GODOT_EXE", "")
    if explicit:
        return explicit if Path(explicit).is_file() else ""
    if sys.platform == "darwin":
        for root in (Path("/Applications"), Path.home() / "Applications"):
            for app in sorted(root.glob("Godot*.app"), reverse=True):
                binary = app / "Contents" / "MacOS" / "Godot"
                if binary.is_file():
                    return str(binary)
    return shutil.which("godot") or shutil.which("godot4") or ""


# --------------------------------------------------------------------- engine
def read_token() -> str:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def probe(token: str, timeout: float = 1.5) -> int:
    """HTTP status of GET /health with `token`; 0 when nothing answers."""
    request = urllib.request.Request(BASE + "/health", headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return 0


def engine_command(python: Path, workspace: Path, godot: str) -> list[str]:
    command = [str(python), "--engine"] if FROZEN else [str(python), str(ENGINE)]
    command += [
               "--loki-root", str(HARNESS),
               "--project-dir", str(workspace),
               "--secret-file", str(TOKEN_FILE),
               "--state-dir", str(STATE),
               "--ui-dir", str(UI_DIR)]
    if godot:
        command += ["--godot-exe", godot]
    return command


def popen_options(platform: str | None = None) -> dict:
    """How to detach the engine: its own session on macOS/Linux, no console on Windows."""
    platform = platform or sys.platform
    if platform == "win32":
        # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP: no black console window, and the
        # engine can be stopped on its own.
        return {"creationflags": 0x08000000 | 0x00000200}
    return {"start_new_session": True}


def start_engine(python: Path, workspace: Path, godot: str) -> subprocess.Popen:
    STATE.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        TOKEN_FILE.unlink()
    except OSError:
        pass
    env = dict(os.environ, LOKI_DATA=str(DATA), PYTHONUNBUFFERED="1", LOKI_PORT=str(PORT))
    output = open(STATE / "engine.out", "a", encoding="utf-8")
    log(f"starting the engine for {workspace}" + (f" (Godot: {godot})" if godot else " (no Godot)"))
    return subprocess.Popen(engine_command(python, workspace, godot), cwd=str(REPO), env=env,
                            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                            **popen_options())


def wait_for_engine(process: subprocess.Popen | None, timeout: float = ENGINE_START_TIMEOUT_S) -> str:
    """The engine's token once it answers, or "" if it died or timed out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return ""
        token = read_token()
        if token and probe(token) == 200:
            return token
        time.sleep(0.5)
    return ""


def stop_engine(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    log("stopping the engine")
    try:
        if hasattr(os, "killpg"):
            os.killpg(process.pid, signal.SIGTERM)
        else:  # Windows
            process.terminate()
        process.wait(timeout=8)
    except Exception:
        process.kill()


# --------------------------------------------------------------------- window
def problem_page(title: str, detail: str) -> str:
    """A self-contained page for when the engine cannot start."""
    def esc(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return ("<!doctype html><meta charset=utf-8><title>Loki</title>"
            "<body style=\"background:#1f1f24;color:#e6e9ee;font:15px -apple-system,system-ui,sans-serif;"
            "padding:48px;max-width:640px\"><h2 style=\"font-weight:600\">" + esc(title) + "</h2>"
            "<p style=\"color:#9aa0aa;white-space:pre-wrap\">" + esc(detail) + "</p></body>")


def name_the_app() -> None:
    """On macOS the window belongs to the Python process; call it Loki in the menu bar."""
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle  # type: ignore  # pyobjc, installed with pywebview
        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "Loki"
    except Exception:
        pass


def open_window(url: str = "", html: str = "") -> bool:
    """Show Loki in a native window. False when pywebview is not installed."""
    try:
        import webview  # type: ignore
    except ImportError:
        return False
    name_the_app()
    if html:
        webview.create_window("Loki", html=html, width=720, height=360)
    else:
        webview.create_window("Loki", url, width=1240, height=820, min_size=(760, 520),
                              background_color="#1f1f24")
    log("opening the Loki window")
    try:
        webview.start(debug=os.environ.get("LOKI_APP_DEBUG", "") == "1",
                      private_mode=False, storage_path=str(STATE / "webview"))
    except Exception:
        log("the window backend raised:")
        log(traceback.format_exc())
        raise
    log("the Loki window closed")
    return True


def tell(title: str, detail: str) -> int:
    log(f"{title}: {detail}")
    if not open_window(html=problem_page(title, detail)):
        print(f"{title}\n{detail}", file=sys.stderr)
    return 1


# --------------------------------------------------------------------- main
def run_engine(args: list[str]) -> int:
    """`Loki --engine ...`: run the engine (loki_bridge.py) inside this interpreter."""
    import runpy
    sys.path[:0] = [str(HARNESS), str(ENGINE.parent)]
    sys.argv = [str(ENGINE), *args]
    runpy.run_path(str(ENGINE), run_name="__main__")
    return 0


def run_agent_job(args: list[str]) -> int:
    """`Loki --agent-job JOB.json`: a packaged build runs a built-in background agent."""
    import asyncio
    if not args:
        return 2
    sys.path[:0] = [str(HARNESS), str(ENGINE.parent)]
    import loki  # type: ignore
    return int(asyncio.run(loki.run_job(args[0])) or 0)


def run_script(args: list[str]) -> int:
    """`Loki --run-script SCRIPT`: a packaged build's stand-in for `python -I SCRIPT` (the
    conductor's runners). Only scripts that ship inside the bundle may run."""
    import runpy
    if not args:
        return 2
    script = Path(args[0]).resolve()
    runners = (HARNESS / "runners").resolve()
    if script.parent != runners or script.suffix != ".py":
        print("refused: only Loki's bundled runners can be run", file=sys.stderr)
        return 2
    sys.argv = [str(script), *args[1:]]
    runpy.run_path(str(script), run_name="__main__")
    return 0


def self_test() -> int:
    """`Loki --self-test`: import the engine and its modules and report. Used by CI."""
    import tempfile
    os.environ.setdefault("LOKI_DATA", tempfile.mkdtemp(prefix="loki-selftest-"))
    sys.path[:0] = [str(HARNESS), str(ENGINE.parent)]
    problems = []
    for name in ("loki_bridge", "workers", "policy", "manifests", "conductor", "brain", "safe_exec",
                 "model_setup", "usage", "agents",
                 "knowledge", "federation", "skill_scan", "loki"):
        try:
            __import__(name)
        except Exception as exc:  # noqa: BLE001
            problems.append("%s: %s: %s" % (name, type(exc).__name__, exc))
    for path in (UI_DIR / "index.html", UI_DIR / "app.js", REPO / "capabilities", REPO / "skills"):
        if not path.exists():
            problems.append("missing " + str(path))
    print("Loki self-test: " + ("OK" if not problems else "FAILED\n  " + "\n  ".join(problems)), flush=True)
    return 0 if not problems else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--engine"]:
        return run_engine(argv[1:])
    if argv[:1] == ["--agent-job"]:
        return run_agent_job(argv[1:])
    if argv[:1] == ["--run-script"]:
        return run_script(argv[1:])
    if argv[:1] == ["--self-test"]:
        return self_test()
    parser = argparse.ArgumentParser(description="Loki desktop app")
    parser.add_argument("--workspace", default="", help="folder Loki works in (remembered)")
    parser.add_argument("--print-url", action="store_true", help="start the engine, print the URL, keep running")
    args = parser.parse_args(argv)
    # Quitting (Cmd+Q, logout, kill) must take the engine down with the app.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    settings = load_settings()
    workspace = choose_workspace(args.workspace, settings)
    if adopt_old_chats(workspace):
        log("brought your chats over from ~/Loki")
    if args.workspace:
        settings["workspace"] = str(workspace)
        save_settings(settings)

    process: subprocess.Popen | None = None
    token = read_token()
    status = probe(token) if token else probe("")
    if token and status == 200:
        log("attaching to the running engine")
    elif status != 0:
        return tell("Port %d is taken" % PORT,
                    f"Something else answers on {BASE}. Quit it, or start Loki with "
                    "LOKI_APP_PORT set to a free port.")
    else:
        python = engine_python()
        if python is None:
            fix = (f"cd /d {REPO} && setup.bat" if sys.platform == "win32"
                   else f"cd {REPO} && bash setup.sh")
            return tell("Loki is not set up yet",
                        f"Run this once in a terminal, then open Loki again:\n\n{fix}")
        process = start_engine(python, workspace, find_godot())
        token = wait_for_engine(process)
        if not token:
            stop_engine(process)
            return tell("The Loki engine did not start",
                        f"Details are in {STATE / 'engine.out'}")

    url = f"{BASE}/#token={token}"
    try:
        if args.print_url:
            print(url, flush=True)
            while process is None or process.poll() is None:
                time.sleep(1)
            return 0
        if not open_window(url):
            log("pywebview is not installed; opening Loki in the browser instead")
            webbrowser.open(url)
            while process is not None and process.poll() is None:
                time.sleep(1)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        log("the Loki app is shutting down")
        stop_engine(process)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        log("Loki crashed:")
        log(traceback.format_exc())
        raise
