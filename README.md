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
