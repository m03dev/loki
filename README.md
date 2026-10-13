# Loki

A desktop command center for AI work. Describe what you want and Loki reads your
workspace, edits files, runs checks to verify its own work, and iterates until the job
is done - asking you before anything risky.

## Install

```bash
git clone https://github.com/m03dev/loki
cd loki
bash setup.sh      # macOS / Linux (needs Python 3.11+)
setup.bat          # Windows
```

On macOS, setup builds **Loki.app** in `~/Applications`; open it like any other app.
Elsewhere, start it with `harness_data/.venv/bin/python app/loki_app.py`.
Details: [docs/operations/MACOS.md](docs/operations/MACOS.md).

## Using it

- **The Loki window** has your chats on the left and the conversation on the right.
  Enter sends, Shift+Enter adds a line. Loki streams the tools it uses while it works;
  Stop is always there.
- **Modes.** Pick how much rope to give it:
  - **Ask** answers a question and changes nothing.
  - **Plan** reads, asks up to three clarifying questions, then writes a numbered plan.
    It cannot write, run or delete anything.
  - **Build** is the full agent: it edits, runs and verifies.
- **Approve before it acts.** Risky tools stop and show you exactly what they will do,
  with Allow and Deny.
- **Workspace.** Loki works in `~/Loki` unless you start it with
  `--workspace /path/to/project` (remembered).
- **Settings** has Connections (what Loki can reach - keys are never shown, and you can
  connect a provider key), Tools, Memory and Capabilities.
- **Game projects.** Godot is an optional adapter: point Loki at a folder with a
  `project.godot` and the Godot tools switch on. The original Godot editor dock
  (`addons/loki`) still works for in-editor use.

## Models

Loki works **with no key at all**: the built-in route needs no account and no card, and a
local Ollama model always works. Point it at a free tier (Gemini, Groq, OpenRouter,
SambaNova, Cloudflare Workers AI, Nous), use your own provider key, or use a Claude Code /
Codex subscription as a provider.

Choose `smart` to have Loki pick the best available and fail over automatically when a
quota runs out. One provider going dark degrades a run - it does not end it.

**Decisions, not just generation.** An optional decision layer answers typed
`choice` / `score` / `noul` questions in the loop - to skip a prompt it is confident is
safe, and to notice when it is stuck. **Jev** (hosted, key-gated) and **Laya**
(local-first, no key: `github.com/receptron/laya`) both work; Laya is preferred when
installed (`npm install --prefix harness_data/laya @receptron/laya`).

## What it can do

- Validates scenes, compiles scripts and actually runs scenes before claiming success.
- Runs AND **drives** a scene: inject a timed sequence of inputs, confirm the game
  actually received them, and screenshot the result (`probe_scene`).
- 519 skills from six skill libraries (ECC, GodotPrompter, Superpowers,
  awesome-gamedev, gamedev-plugin, agentic-gamedev), browsable from the dock, plus the
  Ponytail "least code that works" standard.
- Remembers lasting facts about you and your project (Settings -> Memory).
- Live editor tools through a bundled Godot MCP bridge, with more capability domains
  unlockable on demand.

## Requirements

- Godot **4.8** (or newer 4.x).
- Python **3.11+** - `setup.bat` / `setup.sh` creates the virtual environment for you.
- Windows, Linux or macOS.

## Development

```bash
harness_data/.venv/Scripts/python.exe tests/test_loki.py          # structural, offline
harness_data/.venv/Scripts/python.exe tests/test_loki.py --live   # + MCP and a real model turn
```

The agent lives in `addons/loki/harness/` (Python), the editor UI in
`addons/loki/*.gd`, and the local bridge in `addons/loki/loki_bridge.py`. Run the offline
tests before and after touching any of it.

## Contributing

Issues and pull requests are welcome. Please keep the offline test suite green, and add a
test for anything you fix.

## License

MIT - see [LICENSE](LICENSE).
