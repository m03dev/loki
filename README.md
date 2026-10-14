# LOKI

A living AI company on your own machines. Describe what you want; LOKI plans the work,
picks the right agents and models, runs them (in the background, on the best machine),
verifies the result, and learns from every verified success.

It is a standalone desktop app for macOS and Windows. It is **not** a Godot project; game
work is one optional capability among many.

## Requirements

- Python **3.11+** (3.13 recommended) and git
- macOS (Apple Silicon or Intel), Windows 10/11, or Linux
- Optional: [Ollama](https://ollama.com) for local models, Node 20+ for Laya, an NVIDIA GPU
  for training, Docker for cua virtual computers

## Set up and run

```bash
git clone https://github.com/m03dev/loki
cd loki
bash setup.sh      # macOS / Linux
setup.bat          # Windows
```

Setup creates a private Python environment in `harness_data/.venv`, installs the
dependencies, copies `engine/.env.example` to `harness_data/.env`, runs a health check and
creates launchers:

| | How to start LOKI |
| --- | --- |
| macOS | **Loki.app** in `~/Applications` |
| Windows | **Loki** in the Start menu or on the Desktop, or `Loki.cmd` |
| Linux | `harness_data/.venv/bin/python app/loki_app.py` |

Every message first goes through **Laya**, a small local decision model that sorts the
request (question, code, research, a job for a team...) in milliseconds and works offline.
Setup downloads it once (about 1.7 GB, needs Node 20+); `python tools/setup_laya.py --check`
shows its state. Without it, built-in rules do the sorting and the chat says so.

LOKI works with no API key (a built-in free route, Claude Code / Codex subscriptions, or a
local Ollama model). Add keys in `harness_data/.env` or in Settings > Connections.

Your projects live in `~/LOKI Projects/` (default `~/LOKI Projects/Home`). Start with
`--workspace <folder>` to use another one; it is remembered.

## One version on every machine

The Mac and the PC always run the same LOKI: GitHub's `master`.

- **Updating is automatic.** Every LOKI updates itself from GitHub when it starts
  (fast-forward only; your own edits and unpushed commits are never overwritten). While it
  runs, the sidebar shows when an update is waiting.
- **Publishing is one command**, for you and for every agent (Ziva, Claude Code, LOKI's own):
  `python tools/ship.py -m "what changed"`. It runs every test suite, commits, catches up
  with GitHub, pushes, and tells your other machines. It pushes nothing if a test fails.
- **Both platforms are tested** on every push (GitHub Actions, macOS and Windows).
- **LOKI can improve itself**: ask it to change something about LOKI and it hands the work to
  a background agent (`improve_loki`) that ships it with `ship_loki` once the tests pass.
  `LOKI_SELF_SHIP=ask` makes it ask you first; `off` turns it off.

Agents: read [AGENTS.md](AGENTS.md) and [HANDOFF.md](HANDOFF.md) before changing anything.
Ziva: your task list and inbox is [ZIVA_TASKS.md](ZIVA_TASKS.md).

## Settings: connections, agents, world, updates

- **Connections**: one card per provider (local servers, free tiers, no-account services, free
  credits, your subscriptions, paid). Each has an on/off switch, **Test** (a real 1-token call),
  a live model picker, **Make default** and **Disconnect**. Connect by **Sign in with
  OpenRouter**, by pasting a key, or with your phone: **Use my phone** shows a QR code for a
  one-time page on your Wi-Fi that sends the key to LOKI.
- **Any model can use tools**: models without native tool calling (MLX, plain llama.cpp,
  keyless endpoints) get the tools as text and their calls come back as real tool calls
  (`engine/tool_harness.py`).
- **Agents**: build agents you want to keep - role, goal, skills (SKILL.md), tools, harness
  (LOKI, Claude Code, Codex, Hermes, OpenCode), model and fallback, the machine they live on.
  "Draft it" makes one from a sentence.
- **LOKI World**: your agents as characters in a small 3D world, behind the home screen and in
  its own panel, driven only by real state (GET /world).
- **Machines & updates**: **Update everything** updates every linked machine and restarts it,
  then this one. A version that does not start is rolled back on that machine.
- **Add-ons**: `media` (yt-dlp), `image-gen` (Z-Image Turbo / Pollinations), `agent-reach`,
  `opencode`, `mlx`, `kyojin`. Install the optional ones with `python tools/setup_extras.py`.

## Agent teams

Ask for something big ("build a landing page for my bakery and test it in a browser") and
LOKI builds a team for it: researcher if needed, architect, builder, tester, reviewer and a
browser tester for web work. They work in stages in your project folder, talk on a shared
team board, and the team only reports "verified" when every check passes (one fix round,
then it asks you). You see the team, its stage and its board above the message box. You
never build agents by hand.

## LOKI World

Your Godot world can show LOKI's real agents as characters: the engine serves `GET /world`
(who is there and what they do) and `GET /events` (everything that happens, in order). The
world is its own Godot project; this repository stays Godot-free. Protocol and a brief for
Ziva: [docs/WORLD.md](docs/WORLD.md).

## Spending

LOKI never switches to a paid provider on its own (`LOKI_ALLOW_PAID=1` allows it), and paid
use stops for the day at `LOKI_DAILY_USD_LIMIT` (default $1).

Where everything stands against the vision: [docs/STATUS.md](docs/STATUS.md).

## Link your machines

Run LOKI on your Mac and your PC and let them work together: the PC takes background jobs,
trains on both machines' verified work, and can share its GPU. On the PC, Settings >
Machines > "Let my other machines link to this one" (or
`harness_data\.venv\Scripts\python.exe tools\peer_link.py pair --name pc`); paste the link
code on the Mac. Full guide: [docs/operations/MACHINES.md](docs/operations/MACHINES.md).

## Self-improvement (PC with an NVIDIA GPU)

```bat
tools\setup_training.bat
harness_data\.venv\Scripts\python.exe tools\self_improve.py schedule
```

LOKI collects verified work, fine-tunes a small local model with QLoRA, evaluates it, and
promotes it only when it beats the current one. See
[docs/agents-and-self-improvement.md](docs/agents-and-self-improvement.md).

## Test

```bash
PY=harness_data/.venv/bin/python          # Windows: harness_data\.venv\Scripts\python.exe
$PY tests/test_loki.py            # agent core, app, layout (offline)
$PY tests/test_hardening.py       # no-shell exec, policy, manifests, skills
$PY tests/test_integrations.py    # conductor, specialists, knowledge
$PY tests/test_workers.py         # background jobs
$PY tests/test_offline_e2e.py     # full offline run against a fake model server
$PY tests/test_peers.py           # Mac <-> PC link
$PY tests/test_first_layer.py     # Laya first layer (needs Node 20+ for the Laya part)
$PY tests/test_updater.py         # same version everywhere: updater, ship.py
$PY tests/test_team.py            # agent teams: roles, stages, board, fix round
$PY tests/test_events.py          # event stream, world view, decision-before-model, spending
$PY tests/test_portal.py          # portal, sign-in, QR, tool harness, update everything, agent builder
$PY tools/ship.py --check         # all of the above
```

## Build the Windows app

```powershell
powershell -ExecutionPolicy Bypass -File tools\windows\build_exe.ps1
```

This produces `dist\Loki-windows.zip` (no Python needed to run it). The **Windows build**
workflow on GitHub builds the same zip on every push.

## Layout

| Folder | What it is |
| --- | --- |
| `engine/` | the Python core: agent loop (`loki.py`), loopback API (`loki_bridge.py`), routing, policy, workers, conductor, Laya, learning loop, peer link |
| `app/` | the desktop window (`loki_app.py`, pywebview) and its UI (`app/ui/`) |
| `capabilities/` | manifests for optional add-ons (Browser Use, cua, Crawl4AI, Laya, Ollama fleet...) |
| `skills/` | LOKI's own skills |
| `tools/` | doctor, peer link, self-improvement, training, packaging helpers |
| `tests/` | offline test suites |
| `docs/` | architecture, operations, decisions, security, session log |
| `harness_data/` | your data at runtime: keys, memory, logs, jobs, learning (never committed) |

## License

MIT - see [LICENSE](LICENSE).
