# Loki

An AI game-development agent that lives inside the **Godot 4** editor. Describe what you
want and Loki reads your project, edits its scenes and scripts, runs Godot to check its
own work, and iterates until the job is done.

## Install

```bash
git clone https://github.com/m03dev/loki
cd loki
setup.bat          # Windows
./setup.sh         # Linux / macOS
```

Then open the folder as a project in **Godot 4.8** and enable **Loki** and **Loki Chat**
in *Project Settings -> Plugins*.

## Using it

- **The chat dock** sits in the left column beside Scene. Type in the box and press
  `Ctrl+Enter`. Each conversation gets its own tab, and Loki streams what it is doing
  while it works, so you can watch and stop it.
- **Modes.** Pick how much rope to give it:
  - **Ask** answers a question and changes nothing.
  - **Plan** reads your project, asks up to three clarifying questions, then writes a
    numbered plan. It cannot write, run or delete anything.
  - **Build** is the full agent: it edits, runs and verifies.
- **Approve before it acts.** Dangerous tools ask first. Stop is always available.
- **The Loki screen** is the **Loki** tab next to 3D - a quick way back to the chat and
  its settings.
- **Settings** has tabs: Agent (switch tool categories on and off), Account, Memory,
  Profile and Connections (what Loki can reach right now - secrets are never shown).

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

## Background agents and self-improvement

Loki can hand sub-tasks to background agents (coder, tester, reviewer, researcher) that
work in parallel and report back - start, watch and message them from the dock's
**Background agents...** menu. It also logs how every request went, learns which
providers actually deliver, and can fine-tune a small local model on an NVIDIA GPU from
its own verified work, promoting it only when it beats the current one. See
[docs/agents-and-self-improvement.md](docs/agents-and-self-improvement.md).

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
