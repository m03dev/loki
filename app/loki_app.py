"""Loki - the standalone desktop app.

Starts the Loki engine (addons/loki/loki_bridge.py, the same agent the Godot dock
uses) on 127.0.0.1:8766 and opens the Loki window on it. Godot is optional: it is
only handed to the engine when one is found, so the game tools can light up.

    python app/loki_app.py                 # the window (pywebview), or a browser fallback
    python app/loki_app.py --workspace DIR # work in DIR instead of ~/Loki
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
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
REPO = APP_DIR.parent
HARNESS = REPO / "addons" / "loki" / "harness"
ENGINE = REPO / "addons" / "loki" / "loki_bridge.py"
UI_DIR = APP_DIR / "ui"
DATA = Path(os.environ.get("LOKI_DATA") or (REPO / "harness_data"))
STATE = DATA / "app"
TOKEN_FILE = STATE / "engine.token"
SETTINGS_FILE = STATE / "settings.json"
LOG_FILE = STATE / "loki_app.log"
# The Godot dock's engine owns 8766; the app keeps its own engine on 8767 so both
# can run at once.
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
    """--workspace, else the remembered one, else $LOKI_WORKSPACE, else ~/Loki."""
    settings = settings if settings is not None else {}
    env = env if env is not None else os.environ
    for candidate in (cli_value, settings.get("workspace", ""), env.get("LOKI_WORKSPACE", "")):
        if str(candidate or "").strip():
            return Path(str(candidate)).expanduser().resolve()
    return (Path.home() / "Loki").resolve()


# --------------------------------------------------------------------- discovery
def engine_python() -> Path | None:
    """The interpreter of Loki's private environment (setup.sh / setup.bat make it)."""
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
    return shutil.which("godot") or ""


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
    command = [str(python), str(ENGINE),
               "--loki-root", str(HARNESS),
               "--project-dir", str(workspace),
               "--secret-file", str(TOKEN_FILE),
               "--state-dir", str(STATE),
               "--ui-dir", str(UI_DIR)]
    if godot:
        command += ["--godot-exe", godot]
    return command


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
                            start_new_session=True)


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
        os.killpg(process.pid, signal.SIGTERM) if hasattr(os, "killpg") else process.terminate()
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
    webview.start()
    return True


def tell(title: str, detail: str) -> int:
    log(f"{title}: {detail}")
    if not open_window(html=problem_page(title, detail)):
        print(f"{title}\n{detail}", file=sys.stderr)
    return 1


# --------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loki desktop app")
    parser.add_argument("--workspace", default="", help="folder Loki works in (remembered)")
    parser.add_argument("--print-url", action="store_true", help="start the engine, print the URL, keep running")
    args = parser.parse_args(argv)
    # Quitting (Cmd+Q, logout, kill) must take the engine down with the app.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    settings = load_settings()
    workspace = choose_workspace(args.workspace, settings)
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
            return tell("Loki is not set up yet",
                        f"Run this once in Terminal, then open Loki again:\n\n"
                        f"cd {REPO} && bash setup.sh")
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
        stop_engine(process)


if __name__ == "__main__":
    raise SystemExit(main())
