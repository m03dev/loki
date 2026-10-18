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
import threading
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

T_START = time.monotonic()   # docs/SPEED.md: "window shown after", "engine ready after" in loki_app.log

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


def auto_update() -> dict:
    """Bring this checkout up to GitHub before the engine starts (engine/updater.py).

    Every machine runs the same LOKI this way: the Mac and the PC both follow `master`.
    Fast-forward only; local work is never overwritten. Skipped in packaged builds."""
    if FROZEN:
        return {}
    try:
        sys.path.insert(0, str(HARNESS))
        import updater  # pylint: disable=import-outside-toplevel
        if not updater.enabled():
            return {}
        if RELEASE_MODE and os.environ.get("LOKI_UPDATE_AT_START", "") != "1":
            # An installed LOKI never waits for the network before its window (session 30, docs/SPEED.md):
            # the engine downloads and pre-flights a new release in the background
            # (release_update.prepare); here we only switch to one that is already checked.
            import release_update  # pylint: disable=import-outside-toplevel
            result = release_update.apply_ready()
            if result.get("updated"):
                log("update: " + result.get("note", ""))
            return result
        python = engine_python()
        if python is not None:   # the update's pre-flight runs the new version with the engine's Python
            os.environ["LOKI_ENGINE_PYTHON"] = str(python)
        result = updater.update(REPO, timeout=float(os.environ.get("LOKI_UPDATE_TIMEOUT", "25") or 25))
        log("update: " + (result.get("note") or "") + ((" - " + result["error"]) if result.get("error") else ""))
        return result
    except Exception as exc:  # noqa: BLE001 - an update problem must never stop LOKI from opening
        log("update skipped: %s" % exc)
        return {}


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
    # LOKI_SUPERVISED: the engine exits with RESTART_EXIT_CODE to be restarted on new code.
    # LOKI_APP_PID: this window's process - computer use never clicks or types into it (engine/computer_use.py).
    env = dict(os.environ, LOKI_DATA=str(DATA), PYTHONUNBUFFERED="1", LOKI_PORT=str(PORT),
               LOKI_SUPERVISED="1", LOKI_APP_PID=str(os.getpid()))
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


# --------------------------------------------------------------------- restarts
RESTART_EXIT_CODE = 75          # engine/updater.py: "restart me on the new code"
# An installed LOKI (session 29): packaging/installer/loki_launch.py sets LOKI_RELEASE_ROOT and starts
# <root>/<current>/app/loki_app.py; this exit code asks it to start the (new) current version.
RELEASE_MODE = bool(os.environ.get("LOKI_RELEASE_ROOT", "").strip())
RELAUNCH_EXIT_CODE = 76         # engine/release_update.py
WINDOW: dict = {"window": None, "browser": False}


def rollback_update() -> dict:
    """The updated engine did not start: go back to the version that last worked here."""
    try:
        sys.path.insert(0, str(HARNESS))
        import updater  # pylint: disable=import-outside-toplevel
        result = updater.rollback(REPO)
        log("rollback: " + (("%s -> %s" % (result.get("from"), result.get("to"))) if result.get("ok")
                            else result.get("error", "")))
        return result
    except Exception as exc:  # noqa: BLE001
        log("rollback failed: %s" % exc)
        return {"ok": False, "error": str(exc)}


def show_url(url: str) -> None:
    window = WINDOW.get("window")
    if window is not None:
        try:
            window.load_url(url)
            return
        except Exception:  # noqa: BLE001
            log("could not reload the window:\n" + traceback.format_exc())
    if WINDOW.get("browser"):
        webbrowser.open(url)


def log_tail(path: Path, lines: int = 40) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


def show_problem(title: str, detail: str) -> None:
    """Never leave the window blank (white): say what happened, with the log, in the window."""
    window = WINDOW.get("window")
    if window is not None:
        try:
            window.load_html(problem_page(title, detail))
            return
        except Exception:  # noqa: BLE001
            log("could not show the problem page:\n" + traceback.format_exc())
    log("%s: %s" % (title, detail[:400]))


def start_and_wait(python: Path, workspace: Path, godot: str) -> tuple:
    """Start the engine; if a fresh update keeps it from starting, roll back once and retry."""
    process = start_engine(python, workspace, godot)
    token = wait_for_engine(process)
    if token:
        return process, token
    stop_engine(process)
    back = rollback_update()
    if back.get("ok") and RELEASE_MODE:
        log("went back to %s; the launcher starts it" % back.get("to"))
        os._exit(RELAUNCH_EXIT_CODE)   # the previous version is another folder: the launcher starts it
    if back.get("ok"):
        log("starting the previous version again")
        process = start_engine(python, workspace, godot)
        token = wait_for_engine(process)
        if token:
            return process, token
        stop_engine(process)
    return None, ""


def supervise(holder: dict, python: Path, workspace: Path, godot: str, stop) -> None:
    """Restart the engine when it asks to (after Update everything), and reload the window."""
    while not stop.is_set():
        process = holder.get("process")
        if process is None:
            return
        code = process.poll()
        if code is None:
            stop.wait(1.0)
            continue
        if stop.is_set():
            return
        if code == QUIT_EXIT_CODE:
            log("LOKI was asked to quit")
            stop.set()
            close_window()
            return
        if code != RESTART_EXIT_CODE:
            # The engine died on its own (a crash, or killed for memory). Before, the window then
            # sat there dead until LOKI was quit - all night once. Start it again, a few times,
            # with a growing pause, and reload the window; give up only if it keeps dying.
            now = time.time()
            crashes = [c for c in holder.get("crashes", []) if now - c < 600] + [now]
            holder["crashes"] = crashes
            log("the engine stopped (exit %s)%s" % (code, "; starting it again" if len(crashes) <= 5 else ""))
            if len(crashes) > 5:
                log("the engine crashed 5 times in 10 minutes; not restarting it again")
                return
            stop.wait(min(30.0, 2.0 * len(crashes)))
            new_process, token = start_and_wait(python, workspace, godot)
            holder["process"] = new_process
            if not token:
                log("the engine did not come back")
                show_problem("LOKI's engine stopped and did not start again",
                             "Quit LOKI and open it again. The last lines of its log (%s):\n\n%s"
                             % (STATE / "engine.out", log_tail(STATE / "engine.out")))
                return
            show_url(window_url(token))
            continue
        log("the engine is restarting on the updated code")
        if RELEASE_MODE:
            # an installed LOKI: the launcher (packaging/installer/loki_launch.py) starts the version
            # that is current now - the new one, or the last good one after a rollback
            stop.set()
            close_window()
            if os.environ.get("LOKI_APP_TEST", "") != "1":
                threading.Timer(2.0, os._exit, [RELAUNCH_EXIT_CODE]).start()
            return
        if relaunch_app():
            # Update everything restarts the WHOLE client, not only the engine: the window and
            # this app process run the new code too. The new app waits for this one to exit.
            stop.set()
            close_window()
            # Closing a window from this thread can hang on macOS (Cocoa wants the main thread),
            # which would leave this old copy as a blank window next to the new one: leave for sure.
            if os.environ.get("LOKI_APP_TEST", "") != "1":
                threading.Timer(2.0, os._exit, [0]).start()
            return
        new_process, token = start_and_wait(python, workspace, godot)
        holder["process"] = new_process
        if not token:
            log("the engine did not come back after the update")
            show_problem("LOKI's engine did not come back after the update",
                         "It was rolled back if it could be. Quit LOKI and open it again. The last lines of "
                         "its log (%s):\n\n%s" % (STATE / "engine.out", log_tail(STATE / "engine.out")))
            return
        show_url(window_url(token))


# --------------------------------------------------------------------- background + start at login
QUIT_EXIT_CODE = 76   # the engine asks the app to quit for good (Settings > Quit LOKI)


def env_setting(name: str, default: str = "") -> str:
    """A setting from the process environment or LOKI's .env (read here, never logged)."""
    if os.environ.get(name):
        return os.environ[name].strip()
    try:
        for raw in (DATA / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return default


def background_on() -> bool:
    """LOKI_BACKGROUND auto|on|off: when the window closes, LOKI keeps working (its jobs, automations,
    self-improvement) and opening LOKI again brings the window back. auto = on on Windows."""
    value = env_setting("LOKI_BACKGROUND", "auto").lower()
    if value in ("1", "on", "true", "yes"):
        return True
    if value in ("0", "off", "false", "no"):
        return False
    return sys.platform == "win32"


def start_at_login_on() -> bool:
    """LOKI_START_AT_LOGIN auto|on|off. auto = on on Windows (the PC that works for you 24/7)."""
    value = env_setting("LOKI_START_AT_LOGIN", "auto").lower()
    if value in ("1", "on", "true", "yes"):
        return True
    if value in ("0", "off", "false", "no"):
        return False
    return sys.platform == "win32"


def login_item_path() -> Path:
    if sys.platform == "win32":
        return (Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
                / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "LOKI.vbs")
    return Path.home() / "Library" / "LaunchAgents" / "com.m03dev.loki.plist"


def login_item_text() -> str:
    """Starts LOKI in the background at login: no window, no console."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--background"]
    else:
        python = Path(sys.executable)
        if sys.platform == "win32" and (python.parent / "pythonw.exe").is_file():
            python = python.parent / "pythonw.exe"
        cmd = [str(python), str(Path(__file__).resolve()), "--background"]
    if sys.platform == "win32":
        quoted = " ".join('""%s""' % c for c in cmd)
        return ('\' LOKI: start in the background at login (Settings > General > Start LOKI when I log in)\r\n'
                'CreateObject("WScript.Shell").Run "%s", 0, False\r\n' % quoted)
    args = "".join("    <string>%s</string>\n" % c.replace("&", "&amp;").replace("<", "&lt;") for c in cmd)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>\n'
            '  <key>Label</key><string>com.m03dev.loki</string>\n  <key>ProgramArguments</key><array>\n' + args +
            '  </array>\n  <key>RunAtLoad</key><true/>\n</dict></plist>\n')


def sync_login_item() -> str:
    """Make the login item match the setting (written or removed; never anything else)."""
    if sys.platform not in ("win32", "darwin"):
        return ""
    path = login_item_path()
    try:
        if start_at_login_on():
            text = login_item_text()
            if not path.is_file() or path.read_text(encoding="utf-8", errors="replace") != text:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                return "LOKI now starts in the background when you log in"
        elif path.is_file():
            path.unlink()
            return "LOKI no longer starts at login"
    except OSError as exc:
        return "could not update the login item: %s" % exc
    return ""


# --------------------------------------------------------------------- full restart
def relaunch_command() -> list:
    """How this app was started, to start it again (a packaged build is its own executable). With
    no window open (LOKI working in the background) the new copy starts in the background too."""
    cmd = [sys.executable, *sys.argv[1:]] if getattr(sys, "frozen", False) else [sys.executable, *sys.argv]
    if WINDOW.get("window") is None and "--background" not in cmd:
        cmd.append("--background")
    elif WINDOW.get("window") is not None and "--background" in cmd:
        cmd.remove("--background")
    return cmd


def relaunch_app() -> bool:
    """Start a fresh copy of the app (it waits until this one has exited). LOKI_APP_NO_RELAUNCH=1
    keeps the old engine-only restart."""
    if os.environ.get("LOKI_APP_NO_RELAUNCH", "") == "1":
        return False
    env = dict(os.environ, LOKI_APP_WAIT_PID=str(os.getpid()))
    kwargs: dict = {"env": env, "cwd": str(REPO), "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(relaunch_command(), **kwargs)  # noqa: S603 - our own command line
    except Exception:  # noqa: BLE001
        log("could not start a fresh copy of the app:\n" + traceback.format_exc())
        return False
    log("restarting the whole app on the updated code")
    return True


def wait_for_old_app(timeout: float = 30.0) -> None:
    """A relaunched app: wait for the copy that started it to be gone (it frees the port)."""
    pid = os.environ.pop("LOKI_APP_WAIT_PID", "")
    if not pid.isdigit():
        return
    end = time.time() + timeout
    while time.time() < end and pid_alive(int(pid)):
        time.sleep(0.25)


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes  # pylint: disable=import-outside-toplevel
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259   # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def close_window() -> None:
    window = WINDOW.get("window")
    if window is not None:
        try:
            window.destroy()
        except Exception:  # noqa: BLE001
            log("could not close the window:\n" + traceback.format_exc())


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


# The title bar (owner, 2026-10-17: the mode tabs belong IN the window's title bar, not in a floating pill).
# macOS: the native traffic lights stay, the page draws under a transparent title bar (full-size content view) and
#   LOKI's 38 px strip (app/ui/titlebar.js) holds the tabs, starting after the traffic lights; the rest of the strip
#   drags the window (pywebview's .pywebview-drag-region).
# Windows (owner, 2026-10-18: "the tabs are floating here" - the strip sat UNDER the native frame): the window is
#   frameless too and LOKI's strip IS the title bar - tabs centred, LOKI's own minimise / maximise / close on the
#   right. A frameless WinForms window has no native edges, so the strip's empty parts and thin edge handles hand the
#   press to Windows itself (WM_NCLBUTTONDOWN with HTCAPTION / HTLEFT...): real dragging, Aero snap, real resizing.
# LOKI_TITLEBAR=native (Settings > General) leaves the macOS title bar alone too.
TITLEBAR = {"mac": False, "win": False}


def titlebar_mode() -> str:
    return "native" if env_setting("LOKI_TITLEBAR", "custom").lower() == "native" else "custom"


def window_url(token: str) -> str:
    """LOKI's page in the window; `titlebar=mac` tells it the page is drawn under the macOS title bar."""
    if TITLEBAR["mac"] or mac_custom_titlebar():
        return f"{BASE}/#token={token}&titlebar=mac"
    if TITLEBAR["win"] or win_custom_titlebar():
        return f"{BASE}/#token={token}&titlebar=win"
    return f"{BASE}/#token={token}"


def mac_custom_titlebar() -> bool:
    """macOS with LOKI's own title strip: the window is created FRAMELESS (pywebview then makes the content full
    size and the title bar transparent at creation - patching a live window afterwards left the old bar on the
    owner's Mac), and mac_buttons() puts the three traffic lights back before it is shown."""
    return sys.platform == "darwin" and titlebar_mode() == "custom"


def win_custom_titlebar() -> bool:
    """Windows with LOKI's own title strip: a frameless window whose strip is the title bar (WindowApi moves,
    resizes, minimises, maximises and closes it)."""
    return sys.platform == "win32" and titlebar_mode() == "custom"


# Win32 hit-test codes for WM_NCLBUTTONDOWN: the strip / an edge handle hands the press to Windows' own move/size loop
HIT = {"move": 2, "w": 10, "e": 11, "n": 12, "nw": 13, "ne": 14, "s": 15, "sw": 16, "se": 17}


def win_hit(window, edge: str, user32=None) -> bool:
    """Windows: let Windows move ('move') or resize (n/s/e/w/ne/nw/se/sw) the frameless window, exactly like a
    native title bar or border - on the window's own UI thread (the mouse capture lives there)."""
    code = HIT.get(edge)
    if code is None or window is None:
        return False
    form = getattr(window, "native", None)
    if form is None:
        return False
    if user32 is None:
        import ctypes  # pylint: disable=import-outside-toplevel
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    def go() -> None:
        hwnd = int(form.Handle.ToInt64()) if hasattr(form.Handle, "ToInt64") else int(form.Handle)
        user32.ReleaseCapture()
        user32.SendMessageW(hwnd, 0x00A1, code, 0)   # WM_NCLBUTTONDOWN

    try:
        if getattr(form, "InvokeRequired", False):
            from System import Action  # type: ignore  # pythonnet, there with pywebview's WinForms backend
            form.Invoke(Action(go))
        else:
            go()
        return True
    except Exception:  # noqa: BLE001
        log("could not hand the title strip press to Windows:\n" + traceback.format_exc())
        return False


def win_fit_maximized(window) -> None:
    """A frameless WinForms window maximises over the taskbar unless told the working area first."""
    try:
        form = window.native
        from System.Windows.Forms import Screen  # type: ignore  # pylint: disable=import-outside-toplevel
        form.MaximizedBounds = Screen.FromHandle(form.Handle).WorkingArea
    except Exception:  # noqa: BLE001 - not WinForms: nothing to fit
        pass


def mac_buttons(window) -> None:
    """before_show (pywebview runs it on the main thread, before the window appears): the traffic lights back,
    the title hidden. Any failure: logged, and the window still opens."""
    try:
        import AppKit  # type: ignore  # pyobjc, installed with pywebview on macOS
        ns = window.native
        for button in (AppKit.NSWindowCloseButton, AppKit.NSWindowMiniaturizeButton, AppKit.NSWindowZoomButton):
            ns.standardWindowButton_(button).setHidden_(False)
        ns.setTitlebarAppearsTransparent_(True)
        ns.setTitleVisibility_(getattr(AppKit, "NSWindowTitleHidden", 1))
    except Exception:  # noqa: BLE001
        log("could not show the macOS window buttons:\n" + traceback.format_exc())


class WindowApi:
    """The only Python the page may call (pywebview js_api): the title strip's window controls - double-click =
    zoom everywhere; on Windows (frameless) also drag, edge resize, minimise and close."""

    def __init__(self) -> None:
        self._max = False

    def toggle_maximize(self) -> bool:
        window = WINDOW.get("window")
        if window is None:
            return False
        try:
            if not self._max and sys.platform == "win32":
                win_fit_maximized(window)
            (window.restore if self._max else window.maximize)()
            self._max = not self._max
        except Exception:  # noqa: BLE001
            return False
        return self._max

    def minimize(self) -> bool:
        window = WINDOW.get("window")
        try:
            window.minimize()
            return True
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> bool:
        window = WINDOW.get("window")
        try:
            window.destroy()     # same as the frame's X: LOKI keeps working in the background when that is on
            return True
        except Exception:  # noqa: BLE001
            return False

    def grab(self, edge: str = "move") -> bool:
        """Windows: a press on the strip's empty part ('move') or an edge handle - Windows does the rest."""
        if sys.platform != "win32":
            return False
        if edge == "move" and self._max:
            self._max = False      # dragging a maximised window restores it (Windows does that itself)
        return win_hit(WINDOW.get("window"), str(edge))


def open_window(url: str = "", html: str = "", main: bool = False, then=None) -> bool:
    """Show Loki in a native window. False when pywebview is not installed.
    main=True with html: LOKI's own window showing `html` first (the start screen); `then` runs in a
    thread once the window is up (pywebview's start(func)) and later loads LOKI into it (show_url)."""
    try:
        import webview  # type: ignore
    except ImportError:
        return False
    name_the_app()
    try:   # only the bare strip drags the window - a tab inside it never does (the tabs "ran away" on the Mac)
        webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
    except Exception:  # noqa: BLE001 - an older pywebview
        pass
    mac_strip = bool(main or not html) and mac_custom_titlebar()
    win_strip = bool(main or not html) and win_custom_titlebar()
    TITLEBAR["mac"], TITLEBAR["win"] = mac_strip, win_strip
    # frameless on macOS = full-size content + transparent title bar; on Windows LOKI's strip is the whole title
    # bar. easy_drag off, or ANY drag moves the window.
    frame = {"frameless": True, "easy_drag": False} if (mac_strip or win_strip) else {}
    if html and not main:
        webview.create_window("Loki", html=html, width=720, height=360)
    elif html:
        WINDOW["window"] = webview.create_window("Loki", html=html, width=1240, height=820, min_size=(760, 520),
                                                 background_color="#1f1f24", js_api=WindowApi(), **frame)
    else:
        WINDOW["window"] = webview.create_window("Loki", url, width=1240, height=820, min_size=(760, 520), text_select=True,
                                                 background_color="#1f1f24", js_api=WindowApi(), **frame)
    if WINDOW.get("window") is not None and mac_strip:
        win = WINDOW["window"]
        try:
            win.events.before_show += lambda: mac_buttons(win)
        except Exception:  # noqa: BLE001 - an older pywebview: no traffic lights event; still frameless
            log("this pywebview has no before_show event; the window buttons may be hidden")
    log("opening the Loki window")
    try:
        webview.start(then, debug=os.environ.get("LOKI_APP_DEBUG", "") == "1",
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
                 "knowledge", "federation", "skill_scan", "loki", "providers_catalog", "portal_api",
                 "signin", "qr", "tool_harness", "update_all", "system_check",
                 "ratelimit", "loki_mcp", "studio_api", "qol"):   # session 29: the main driver's pacing, the MCP API, Studio's door
        try:
            __import__(name)
        except Exception as exc:  # noqa: BLE001
            problems.append("%s: %s: %s" % (name, type(exc).__name__, exc))
    for path in (UI_DIR / "index.html", UI_DIR / "app.js", REPO / "capabilities", REPO / "skills"):
        if not path.exists():
            problems.append("missing " + str(path))
    print("Loki self-test: " + ("OK" if not problems else "FAILED\n  " + "\n  ".join(problems)), flush=True)
    return 0 if not problems else 1


def bring_up_engine(workspace: Path, holder: dict, stopping) -> tuple:
    """Attach to a running engine or start one. (token, "", "") or ("", title, what to do)."""
    token = read_token()
    status = probe(token) if token else probe("")
    if token and status == 200:
        log("attaching to the running engine")
        return token, "", ""
    if status != 0:
        return "", "Port %d is taken" % PORT, (f"Something else answers on {BASE}. Quit it, or start Loki with "
                                               "LOKI_APP_PORT set to a free port.")
    python = engine_python()
    if python is None:
        fix = (f"cd /d {REPO} && setup.bat" if sys.platform == "win32"
               else f"cd {REPO} && bash setup.sh")
        if RELEASE_MODE:   # installed with the installer: its launcher makes the environment
            fix = ("Quit LOKI and open it again from the Start menu or Applications: it finishes setting "
                   "itself up. If it keeps failing, see docs/INSTALL.md.")
        return "", "Loki is not set up yet", f"Run this once in a terminal, then open Loki again:\n\n{fix}"
    godot = find_godot()
    process, token = start_and_wait(python, workspace, godot)
    if not token:
        return "", "The Loki engine did not start", f"Details are in {STATE / 'engine.out'}"
    holder["process"] = process
    threading.Thread(target=supervise, args=(holder, python, workspace, godot, stopping),
                     daemon=True, name="loki-supervisor").start()
    return token, "", ""


# --------------------------------------------------------------------- the start screen
# The window opens at once and shows a start screen while the engine starts (session 30). LOKI's own
# evolve step E12 designs that screen (a Maya-like splash): it only has to add app/ui/splash.html, a
# SELF-CONTAINED page (inline CSS/JS, images as data: URIs - it is shown before the engine serves
# anything). It may call window.lokiSplash?.() hooks of its own; the app replaces the page with
# LOKI's window as soon as the engine answers, and writes progress lines into it via
# `window.lokiSplashStatus(text)` when the page defines that function. LOKI_SPLASH=off: no start
# screen (the window opens once the engine answers, as before).
SPLASH_FILE = UI_DIR / "splash.html"


def splash_wanted() -> bool:
    if os.environ.get("LOKI_SPLASH", "").strip().lower() in ("0", "off", "no", "false"):
        return False
    import importlib.util  # pylint: disable=import-outside-toplevel
    return importlib.util.find_spec("webview") is not None


def splash_html() -> str:
    try:
        text = SPLASH_FILE.read_text(encoding="utf-8")
        if text.strip():
            return text
    except OSError:
        pass
    return ("<!doctype html><meta charset=utf-8><title>LOKI</title>"
            "<body style=\"margin:0;height:100vh;display:flex;align-items:center;justify-content:center;"
            "background:#1f1f24;color:#9aa0aa;font:15px -apple-system,system-ui,sans-serif\">"
            "<p id=s>Starting LOKI…</p><script>window.lokiSplashStatus=function(t){"
            "document.getElementById('s').textContent=t}</script></body>")


def splash_status(text: str) -> None:
    window = WINDOW.get("window")
    if window is None:
        return
    try:
        window.evaluate_js("window.lokiSplashStatus && window.lokiSplashStatus(%s)" % json.dumps(text))
    except Exception:  # noqa: BLE001 - the start screen is decoration; never let it stop the start
        pass


def run_with_splash(workspace: Path, holder: dict, stopping) -> int:
    t0 = time.monotonic()
    result = {"code": 0}

    def behind_the_window() -> None:
        log("window shown after %.2fs" % (time.monotonic() - T_START))
        if auto_update().get("relaunch"):
            log("a new release is installed; the launcher starts it")
            result["code"] = RELAUNCH_EXIT_CODE
            stopping.set()
            close_window()
            if os.environ.get("LOKI_APP_TEST", "") != "1":
                threading.Timer(2.0, os._exit, [RELAUNCH_EXIT_CODE]).start()
            return
        splash_status("Starting LOKI's engine…")
        token, title, detail = bring_up_engine(workspace, holder, stopping)
        if not token:
            show_problem(title, detail)
            return
        click = os.environ.get("LOKI_LAUNCH_T0", "")   # set by the native launcher at the double click
        since = (" (%.2fs since the double-click)" % (time.time() - int(click) / 1000.0)) if click.isdigit() and int(click) else ""
        log("engine ready after %.2fs (%.2fs since the app started)%s" % (time.monotonic() - t0, time.monotonic() - T_START, since))
        show_url(window_url(token))

    if not open_window(html=splash_html(), main=True, then=behind_the_window):
        return 1
    return result["code"]


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
    parser.add_argument("--background", action="store_true", help="start LOKI with no window (at login)")
    args = parser.parse_args(argv)
    wait_for_old_app()
    # Quitting (Cmd+Q, logout, kill) must take the engine down with the app.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    settings = load_settings()
    workspace = choose_workspace(args.workspace, settings)
    if adopt_old_chats(workspace):
        log("brought your chats over from ~/Loki")
    if args.workspace:
        settings["workspace"] = str(workspace)
        save_settings(settings)

    import threading  # pylint: disable=import-outside-toplevel
    process: subprocess.Popen | None = None
    holder: dict = {"process": None}
    stopping = threading.Event()
    if not args.print_url and splash_wanted():
        # session 30 (docs/SPEED.md): the window opens at once with the start screen; the start-up
        # update and the engine run behind it, and the window switches to LOKI when the engine answers
        try:
            return run_with_splash(workspace, holder, stopping)
        except KeyboardInterrupt:
            return 0
        finally:
            log("the Loki app is shutting down")
            stopping.set()
            stop_engine(holder.get("process"))
    if auto_update().get("relaunch"):
        log("a new release was checked and installed; the launcher starts it")
        return RELAUNCH_EXIT_CODE
    token, title, detail = bring_up_engine(workspace, holder, stopping)
    if not token:
        return tell(title, detail)
    process = holder.get("process")

    url = window_url(token)
    try:
        def alive() -> bool:
            current = holder.get("process")
            if stopping.is_set():
                return False   # relaunched: a fresh copy of the app has taken over
            return current is not None and (current.poll() is None or current.poll() == RESTART_EXIT_CODE)

        if args.print_url:
            print(url, flush=True)
            while process is None or alive():
                time.sleep(1)
            return 0
        note = sync_login_item()
        if note:
            log(note)
        if args.background:
            log("LOKI is working in the background (open LOKI to see it)")
            while process is not None and alive():
                time.sleep(1)
            return 0
        if not open_window(url):
            log("pywebview is not installed; opening Loki in the browser instead")
            WINDOW["browser"] = True
            webbrowser.open(url)
            while process is not None and alive():
                time.sleep(1)
        elif process is not None and background_on() and alive() and not stopping.is_set():
            # The window closed but LOKI keeps working (jobs, automations, self-improvement); opening
            # LOKI again attaches a new window to this engine. Settings > Quit LOKI stops it for good.
            WINDOW["window"] = None
            log("the window closed; LOKI keeps working in the background")
            while alive():
                time.sleep(1)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        log("the Loki app is shutting down")
        stopping.set()
        stop_engine(holder.get("process") or process)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        log("Loki crashed:")
        log(traceback.format_exc())
        raise
