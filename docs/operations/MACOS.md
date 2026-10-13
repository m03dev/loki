# Loki on macOS

Loki is a standalone desktop app. `Loki.app` opens the Loki window (a native WebKit
window via pywebview) over the Loki engine, which runs locally on `127.0.0.1:8766`.
Godot is not needed; it is only used, if installed, when the workspace is a Godot
project.

## One-time setup

1. Install **Python 3.11+**. With Homebrew: `brew install python@3.13` (answer `y`).
   Apple's `/usr/bin/python3` is 3.9 and cannot run Loki. Prefer 3.13 over a brand-new
   release, whose packages may not have ready-made builds yet.
2. In the checkout:

   ```bash
   bash setup.sh
   ```

   This creates Loki's private Python environment, installs the engine and the window
   (`pywebview`), fetches the skill libraries, and builds `~/Applications/Loki.app`.
3. Open **Loki** from `~/Applications`, or run `open ~/Applications/Loki.app`.

Run the two commands separately: pasting them together feeds the second line to
Homebrew's `[y/n]` question.

## What happens when you open Loki

- `Loki.app` runs `app/loki_app.py` with Loki's private Python (first launch without
  that Python runs `setup.sh` once).
- The app starts the engine with `--ui-dir app/ui` and its own state folder
  (`harness_data/app/`: log, engine token, settings), waits until it answers, then opens
  the window at `http://127.0.0.1:8766/#token=...`. The token stays in the URL
  fragment, which is never sent over the wire.
- Closing or quitting Loki stops the engine it started.
- If another engine already holds the port (the Godot dock's), Loki says so instead of
  fighting it.

## Files

| Path | What |
| --- | --- |
| `harness_data/app/loki_app.log` | app log |
| `harness_data/app/engine.out` | engine output (startup, MCP servers, errors) |
| `harness_data/app/settings.json` | remembered workspace |
| `~/Loki` | default workspace |

## Verified so far

On Linux, with real Chromium: the engine starts without Godot, serves the UI, rejects
a foreign Host (403), a missing token (401) and path traversal (404). The UI loads,
switches modes, lists 39 models, shows settings (10 tool groups, 98 capabilities),
renders and answers a permission request, and has no console errors. The app shell
starts the engine, remembers the workspace, and stops the engine when it quits.

**Not yet verified on the Mac:** the pywebview window itself, and a real model reply
(this workspace could not install the `openai`/`mcp` packages). The first real launch
on the Mac is that check.
