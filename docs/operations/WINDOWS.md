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

## Verified so far

The Windows pieces (`setup.bat`, `make_shortcuts.ps1`, `Loki.cmd`, the no-console
engine start) are covered by offline checks only. They have **not** been run on a
Windows machine yet; the first `setup.bat` run there is that check.

## Packaged build (Loki.exe)

A self-contained build needs no Python on the target machine.

- **CI:** every push to `master` / `macos-app` runs `.github/workflows/windows-build.yml` on
  Windows: offline tests, PyInstaller build, `Loki.exe --self-test`, and uploads
  `Loki-windows.zip` as a workflow artifact (Actions tab > the run > Artifacts).
- **Locally:** `powershell -ExecutionPolicy Bypass -File tools\windows\build_exe.ps1`
  produces `dist\Loki\Loki.exe` and `dist\Loki-windows.zip`.

The build carries Loki's tree inside it and keeps your data in `%LOCALAPPDATA%\Loki`. The
same `Loki.exe` runs the engine (`--engine`) and the conductor's runners (`--run-script`,
bundled runners only). Optional extras (crawl4ai, browser-use, Hindsight client, Headroom)
are not bundled; use the source install (`setup.bat`) when you want those.
