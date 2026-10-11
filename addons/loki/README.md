# Loki Godot addon

An AI game-dev agent dock for the Godot 4 editor.

- `plugin.gd` — registers the center-screen placeholder.
- `chat/plugin.gd` — adds the **Loki Chat** dock (left, beside Scene).
- `loki_dock.gd` — the dock UI: chat, tasks, progress, approvals, Stop.
- `loki_settings.gd` — the settings dialog.
- `loki_bridge.py` — loopback HTTP bridge to the Python agent.
- `run_bridge.bat` — launches the bridge using `harness/` from the repo root.

The agent itself lives in `../../harness/loki.py`. See the repo README and
`docs/` for setup and providers.
