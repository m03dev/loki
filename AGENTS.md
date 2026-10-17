# AGENTS.md - rules for every agent working on LOKI

You may be Ziva, Claude Code, Codex, or one of LOKI's own agents (`improve_loki`). The
owner works on LOKI with several of you, on two machines. These rules keep it one project.

## The one rule: one version, both machines

LOKI runs on the owner's **Mac** (`~/Documents/loki`) and **Windows PC**
(`C:\Users\macul\Documents\loki`) from the **same code**, branch **`master`** on GitHub
(`m03dev/loki`). They must never drift apart.

- Publish every change with **`python tools/ship.py -m "what changed"`**. Nothing else.
  It runs all test suites, commits, rebases onto GitHub, re-tests, pushes `master`, and
  tells the other machine. It pushes nothing if a test fails or a rebase conflicts.
  (On Windows: `harness_data\.venv\Scripts\python.exe tools\ship.py -m "..."`.)
- Never `push --force`, `reset --hard` a shared branch, or push to a branch other than
  `master`. Old `macos-app` is only a mirror that ship.py keeps in step.
- Every machine updates itself from GitHub when LOKI starts (`engine/updater.py`), so a
  shipped change reaches the other machine on its next start; while running it shows that
  an update is waiting.
- Every push is tested on **macOS and Windows** in CI (`.github/workflows/tests.yml`).

## Both platforms, always

- No code for one OS without the other. Use `pathlib`, `sys.platform` branches with both
  sides, and no shell strings (`engine/safe_exec.py`).
- `.bat`/`.cmd`/`.ps1` are CRLF (`.gitattributes`); `.sh` is LF and must parse with `bash -n`.
- Setup is `setup.sh` (macOS/Linux) and `setup.bat` (Windows); change both together.
- If you add a dependency, add it to `engine/requirements.txt` (the updater installs it on
  every machine after an update).

## Before you change anything

1. Read `README.md`, `docs/ARCHITECTURE.md`, the top of `docs/operations/SESSION_LOG.md`,
   and `HANDOFF.md` (where the work stands right now). Ziva: also `ZIVA_TASKS.md`, your inbox
   and task list (anyone who needs something from the Mac or the PC adds it there).
2. `git status` and `git log --oneline -5`. If GitHub is ahead, update first.
3. Run `python tools/ship.py --check` so you know the suites pass before you start.

## While you work

- Small steps. Add or update a test in `tests/` for what you change.
- LOKI is its own app, not a Godot addon. Godot belongs in exactly two places (owner's decision,
  2026-10-17: "you can use godot we love godot"): the game capability (`engine/godot_tools.py`,
  `engine/godot_assets.py`, kept) and **LOKI World, the MMO**: one Godot 4 project in
  `game/loki-world/`, exported as its own app (Steam) and as a web build that LOKI's window shows.
  Never put `project.godot`, `.gd`, `.tscn`, `.uid` or an `addons/` folder anywhere else in the repo.
  The owner's own game projects live in `~/LOKI Projects/<name>`.
- Never commit anything from `harness_data/` (keys, memory, logs, venvs, models).
- Updates are health-gated (HANDOFF session 28): a machine only takes a version that passes
  `python app/loki_app.py --self-test` and whose window files all exist, and keeps it only once
  its window reports ready. So: every script index.html loads must be committed, `--self-test`
  must stay green, and app.js must keep posting `/ui/ready`. Never bypass this to "just ship".
- Safety stays: `engine/policy.py`, approvals for risky actions, the signed peer link.

## When you are done

1. `python tools/ship.py -m "<what changed and how it was checked>"`.
2. Update `HANDOFF.md` (what is done, what is next) and add a short entry to
   `docs/operations/SESSION_LOG.md` when the change is significant. Ship those too.
3. Say plainly what you verified and what you did not.

## Where things are

| Folder | What |
| --- | --- |
| `engine/` | the Python core (agent loop `loki.py`, API `loki_bridge.py`, first layer, workers, peers, updater) |
| `app/` | the desktop window and its UI |
| `studio/` | LOKI Studio, the separate app LOKI is developed with (docs/STUDIO.md; the LOKI MCP API is docs/LOKI_MCP.md) |
| `tools/` | `ship.py`, `peer_link.py`, `setup_laya.py`, `self_improve.py`, training, packaging |
| `tests/` | offline suites; `tools/ship.py --check` runs all of them |
| `docs/` | architecture, operations, decisions, security, session log, `BUILD_BRIEF.md` (the owner's direction) |
