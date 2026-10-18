"""LOKI Studio - the app you build LOKI with (docs/STUDIO.md).

Its own process, its own window, its own launcher (Loki Studio.cmd on Windows, LOKI Studio.app /
studio/loki_studio.sh on the Mac). Like a game editor next to the game, it does not need LOKI to
be running - or working: it runs from a pinned known-good copy of LOKI (studio_pin.py), its
development agent runs inside it on DeepSeek V4.1 Flash (NVIDIA NIM), it works on LOKI's code in
its own git worktrees, and it can read LOKI's logs, start or restart LOKI and roll it back to the
last good version when LOKI is down. When LOKI is up, the agent inspects and controls it through
the LOKI MCP API.

    python studio/studio_app.py              the Studio window (pywebview), or the browser
    python studio/studio_app.py --print-url  serve and print the URL (no window)
    python studio/studio_app.py --self-test  check this copy can run (used before pinning it)
    python studio/studio_app.py --no-pin     run this copy even when a pinned copy exists
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import studio_paths  # noqa: E402

WINDOW: dict = {"window": None}


def log(message: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + message
    print("[loki-studio] " + message, file=sys.stderr, flush=True)
    try:
        with (studio_paths.studio_data() / "studio.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def self_test() -> int:
    """Every Studio module and the engine modules it uses import; the window's files exist."""
    import tempfile
    os.environ.setdefault("LOKI_DATA", tempfile.mkdtemp(prefix="loki-studio-selftest-"))
    problems = []
    for name in ("studio_models", "studio_core", "studio_control", "studio_pin", "studio_server",
                 "studio_godot", "studio_tools", "studio_commands", "studio_checkpoints", "studio_index", "godot_docs",
                 "studio_cli", "studio_mcp", "install_godot_plugin", "loki_mcp", "ratelimit", "updater", "policy"):
        try:
            __import__(name)
        except Exception as exc:  # noqa: BLE001
            problems.append("%s: %s: %s" % (name, type(exc).__name__, exc))
    try:
        import loki_mcp  # pylint: disable=import-outside-toplevel
        loki_mcp.build_server(loki_mcp.LokiAPI(worktree=studio_paths.CODE, repo=studio_paths.CODE))
    except Exception as exc:  # noqa: BLE001
        problems.append("the LOKI MCP API does not build: %s" % exc)
    for rel in ("index.html", "studio.js", "studio.css"):
        if not (studio_paths.UI / rel).is_file():
            problems.append("missing studio/ui/" + rel)
    plugin = studio_paths.HERE / "godot_plugin" / "addons" / "loki_studio"
    for rel in ("plugin.cfg", "plugin.gd", "bridge.gd", "dock.gd", "api.gd", "game_bridge.gd", "debugger.gd"):
        if not (plugin / rel).is_file():
            problems.append("missing the Godot plugin's " + rel)
    print("LOKI Studio self-test: " + ("OK" if not problems else "FAILED\n  " + "\n  ".join(problems)), flush=True)
    return 0 if not problems else 1


def hand_over_to_pin(argv: list) -> int | None:
    """Run the pinned known-good copy instead of this one; None = run this one."""
    if os.getenv("LOKI_STUDIO_PINNED") == "1" or os.getenv("LOKI_STUDIO_NO_PIN") == "1" or "--no-pin" in argv:
        return None
    try:
        import studio_pin  # pylint: disable=import-outside-toplevel
        studio_pin.ensure(studio_paths.repo(), studio_paths.data())
        app = studio_pin.usable(studio_paths.data())
    except Exception as exc:  # noqa: BLE001 - a broken pin never stops Studio: run from the checkout
        log("pinned copy unavailable (%s); running from the checkout" % exc)
        return None
    if app is None or app.resolve() == Path(__file__).resolve():
        return None
    env = dict(os.environ, LOKI_STUDIO_PINNED="1", LOKI_STUDIO_REPO=str(studio_paths.repo()),
               LOKI_DATA=str(studio_paths.data()))
    log("running the pinned copy %s" % app.parent.parent)
    started = time.monotonic()
    code = subprocess.call([sys.executable, str(app), *argv], env=env)
    if code != 0 and time.monotonic() - started < 20:
        # The pinned copy would not even start: never leave the owner without Studio.
        log("the pinned copy exited at once (%s); running from the checkout instead" % code)
        return None
    return code


def open_window(url: str) -> bool:
    try:
        import webview  # type: ignore  # pylint: disable=import-outside-toplevel
    except ImportError:
        return False
    if sys.platform == "darwin":
        try:
            from Foundation import NSBundle  # type: ignore  # pylint: disable=import-outside-toplevel
            info = NSBundle.mainBundle().infoDictionary()
            if info is not None:
                info["CFBundleName"] = "LOKI Studio"
        except Exception:  # noqa: BLE001
            pass
    WINDOW["window"] = webview.create_window("LOKI Studio", url, width=1280, height=840, min_size=(820, 560),
                                             background_color="#15161b")
    webview.start(private_mode=False, storage_path=str(studio_paths.studio_data() / "webview"))
    return True


def raise_window() -> None:
    window = WINDOW.get("window")
    if window is None:
        return
    for name in ("restore", "show"):
        try:
            getattr(window, name)()
        except Exception:  # noqa: BLE001
            pass


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--self-test"]:
        return self_test()
    handed = hand_over_to_pin(argv)
    if handed is not None:
        return handed
    ap = argparse.ArgumentParser(description="LOKI Studio")
    ap.add_argument("--print-url", action="store_true", help="serve and print the URL; no window")
    ap.add_argument("--port", type=int, default=int(os.getenv("LOKI_STUDIO_PORT", "8771") or 8771))
    ap.add_argument("--no-pin", action="store_true")
    args = ap.parse_args(argv)
    studio_paths.load_env_file()
    import studio_core  # pylint: disable=import-outside-toplevel
    import studio_pin  # pylint: disable=import-outside-toplevel
    import studio_server  # pylint: disable=import-outside-toplevel
    import studio_godot  # pylint: disable=import-outside-toplevel
    studio = studio_core.Studio()
    connect = studio_godot.connect_path()     # the Godot plugin finds Studio through this file
    try:
        server = studio_server.StudioServer(studio, port=args.port, on_raise=raise_window, connect_file=connect)
    except OSError:
        server = studio_server.StudioServer(studio, port=0, on_raise=raise_window, connect_file=connect)   # the port is taken
    server.start()
    log("LOKI Studio on %s (code from %s, working on %s)" % ("http://127.0.0.1:%d" % server.port, studio_paths.CODE,
                                                              studio.repo))

    def refresh_pin() -> None:
        try:
            log("pin: " + studio_pin.refresh(studio.repo, studio.data, python=sys.executable).get("note", ""))
        except Exception as exc:  # noqa: BLE001
            log("pin refresh failed: %s" % exc)
    if os.getenv("LOKI_STUDIO_PIN_REFRESH", "1") != "0":
        threading.Thread(target=refresh_pin, daemon=True, name="studio-pin").start()
    try:
        if args.print_url:
            print(server.url, flush=True)
            while True:
                time.sleep(3600)
        if not open_window(server.url):
            log("pywebview is not installed; opening LOKI Studio in the browser")
            webbrowser.open(server.url)
            while True:
                time.sleep(3600)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        for sid in [s["id"] for s in studio.list()]:
            try:
                studio.stop(sid)
            except Exception:  # noqa: BLE001
                pass
        server.stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        log("LOKI Studio crashed:\n" + traceback.format_exc())
        raise
