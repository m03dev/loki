# Loki Godot addon

An AI game-dev agent dock for the Godot 4 editor.

- `plugin.gd` — registers the center-screen placeholder.
- `chat/plugin.gd` — adds the **Loki Chat** dock (left, beside Scene).
- `loki_dock.gd` — the dock UI: conversation tabs, saved history, chat, tasks,
  progress, approvals, Stop.
- `loki_settings.gd` — the settings dialog (Agent / Account / Profile / Memory).
- `loki_settings.gd` — the settings dialog.
- `loki_bridge.py` — loopback HTTP bridge to the Python agent.
- `run_bridge.bat` — launches the bridge using `addons/loki/harness/` from the repo root.

The agent itself lives in `../../addons/loki/harness/loki.py`. See the repo README and
`docs/` for setup and providers.

### First run / dependencies

The dock launches `bootstrap.py`, which creates `harness_data/.venv` and installs
`addons/loki/harness/requirements.txt` automatically, then starts `loki_bridge.py`. The only
prerequisite is Python 3 - nothing else to install or configure.

### ECC agents and skills

`addons/loki/harness/ecc_sync.py` fetches [affaan-m/ECC](https://github.com/affaan-m/ECC)
(agents + skills) and DietrichGebert/ponytail into `harness_data/vendor/` over HTTPS,
using only the standard library. The bridge runs it on first start and the dock
exposes it via **Sync ECC library from GitHub**; the model reaches it through the
`list_ecc_agents` / `load_ecc_agent` / `list_ecc_skills` / `load_ecc_skill` /
`sync_ecc` tools.

### Runtime files (all under the target project)

- `.godot/loki_conversations.json` — every chat and its messages (the tabs).
- `harness_data/memory.md` — the Memory tab's lasting facts (gitignored).
- `.godot/loki_bridge.token` / `.godot/loki_session.json` — bridge token and
  optional Google sign-in session.
