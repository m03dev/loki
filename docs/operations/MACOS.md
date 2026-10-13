# Loki on macOS

Loki is a Godot editor addon, so "the Mac app" is a small `Loki.app` launcher that
opens this checkout in Godot with Loki enabled. It is not a separate copy of Loki:
`git pull` in the checkout updates what the app opens.

## One-time setup

1. Install **Godot 4.8+** (godotengine.org) into `/Applications` or `~/Applications`.
2. Install **Python 3.11+** (python.org or `brew install python`). Apple's
   `/usr/bin/python3` is 3.9 and cannot run the harness.
3. In the checkout:

   ```bash
   ./setup.sh                        # venv, deps, skill libraries, harness_data/.env
   tools/macos/make_loki_app.sh      # builds ~/Applications/Loki.app
   ```

4. Double-click **Loki** in `~/Applications` (drag it to the Dock if you like).

## What the launcher does

- Finds Godot: `LOKI_GODOT`, then `Godot*.app` in `/Applications` and
  `~/Applications` (newest first), then Spotlight, then `godot` on `PATH`.
- Refuses Godot older than 4.8 with a dialog; never downloads or installs Godot.
- Runs `setup.sh` once if `harness_data/.venv` is missing (log:
  `harness_data/loki_app.log`).
- Adds `/opt/homebrew/bin`, `/usr/local/bin` and `~/.local/bin` to `PATH`. Apps opened
  from Finder get a bare `PATH`, and the bridge needs `python3`, `git`, `node` and `uvx`.
- Opens the editor: `Godot --path <checkout> -e`.

If you move the checkout, rebuild the app. The builder only replaces a `Loki.app` that
it made itself.

## Fixed for macOS in this change

- The chat dock only looked for the Windows venv (`.venv/Scripts/python.exe`). On a Mac
  it fell back to bare `pythonw`/`python`/`py`, which do not exist there. Godot's
  `create_process` forks before it execs, so it still returned a PID and the bridge
  silently never started. The dock now tries `harness_data/.venv/bin/python3` and the
  Homebrew, python.org and system Python locations, and uses bare names only on Windows.
- `bootstrap.py` and `setup.sh` refuse to build the venv from a Python older than 3.11,
  instead of leaving a broken venv that every later launch would prefer.

## Not verified yet

Everything above was tested on Linux: the bundle structure, the plist, and the launcher
against fake Godot binaries. It has **not** yet been run on a real Mac with a real Godot
4.8. The first real launch is the check:

1. `tests/test_loki.py` passes with `harness_data/.venv/bin/python`.
2. Double-clicking Loki opens the editor, and the dock status reaches "connected".
3. One Ask-mode message gets a reply.
