# PyInstaller spec for the packaged Loki app (Windows build; works on macOS/Linux too).
#
#   pip install pyinstaller -r addons/loki/harness/requirements.txt -r app/requirements.txt
#   pyinstaller packaging/loki.spec --noconfirm
#
# Result: dist/Loki/Loki.exe (onedir). The repo tree Loki reads at runtime (the agent's
# Python sources, the UI, capabilities/, skills/) ships as data next to it; user data lives
# in %LOCALAPPDATA%\Loki. The same executable runs the engine (`Loki.exe --engine`) and the
# conductor's runners (`Loki.exe --run-script`), so no separate Python is needed.
# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller

datas, binaries, hidden = [], [], []
for package in ("mcp", "openai", "pydantic", "pydantic_core", "httpx", "anyio", "webview"):
    try:
        d, b, h = collect_all(package)
        datas += d; binaries += b; hidden += h
    except Exception:
        pass

# Loki's own tree, as files on disk (the engine imports the harness from source).
for folder in ("addons/loki", "app/ui", "capabilities", "skills"):
    datas.append((str(ROOT / folder), folder))
datas.append((str(ROOT / "LICENSE"), "."))

a = Analysis(  # noqa: F821
    [str(ROOT / "app" / "loki_app.py")],
    pathex=[str(ROOT / "addons" / "loki" / "harness"), str(ROOT / "addons" / "loki")],
    binaries=binaries,
    datas=datas,
    # Modules the harness imports at runtime; listing them pulls in their stdlib needs.
    hiddenimports=hidden + ["asyncio", "sqlite3", "urllib.request", "http.server", "runpy",
                            "loki_bridge", "loki", "workers", "policy", "manifests", "conductor",
                            "brain", "safe_exec", "knowledge", "federation", "skill_scan",
                            "interfaces", "decisions", "jev", "laya", "cli_agents", "capabilities",
                            "sessions", "api_vault", "project_state", "repo_review", "godot_tools",
                            "ecc_sync"],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="Loki",
    console=False,          # no console window; the engine logs to %LOCALAPPDATA%\Loki\app
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Loki")  # noqa: F821
