# Loki on Windows

The same standalone app as on macOS: `app/loki_app.py` starts the Loki engine (on its
own port, 8767) and opens the Loki window. On Windows the window uses Microsoft Edge
WebView2, which Windows 10/11 already ship with.

## One-time setup

1. Install **Python 3.13** from python.org (tick "Add python.exe to PATH"). The `py`
   launcher it installs is what `setup.bat` looks for first.
2. Install **git** (for the optional skill libraries).
3. In the checkout, run `setup.bat`. It creates Loki's private Python, installs the engine
   and the window (`pywebview`), fetches the skill libraries, and adds **Loki** to the
   Start menu and the Desktop.
4. Open **Loki** from the Start menu, or run `Loki.cmd`.

## Notes

- The shortcuts run `harness_data\.venv\Scripts\pythonw.exe app\loki_app.py`, so no
  console window appears; the engine is also started without a console.
- Logs: `harness_data\app\loki_app.log` (app) and `harness_data\app\engine.out` (engine).
- The Godot dock keeps port 8766, so the app and the dock can run at the same time.

## Verified so far

The Windows pieces (`setup.bat`, `make_shortcuts.ps1`, `Loki.cmd`, the no-console
engine start) are covered by offline checks only. They have **not** been run on a
Windows machine yet; the first `setup.bat` run there is that check.
