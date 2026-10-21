# ZIVA.md - standing instructions for Ziva (Mac and Windows) on LOKI

Read this at the start of EVERY session, then AGENTS.md, HANDOFF.md (top sections) and ZIVA_TASKS.md.

## What LOKI is
LOKI is the owner's (m03dev) personal AI agent app for Windows and macOS: it chats, runs background
agents and teams, makes pictures/video/music, builds mini-apps, automates things, remembers across
machines and improves itself. It is PUBLIC and AGPL-3.0 now: other people install it from a zip or
installer, so it must "just work" - one click, no terminal, no setup stress, fast.

## Your job, always
1. Keep LOKI working on this machine: pull, run it, look at it, use it like a new user would.
2. Do the open tasks for your machine in ZIVA_TASKS.md, newest first ("Ziva (Windows)" or "Ziva (Mac)").
3. Report results under each task (what you did, what you saw, numbers, screenshots in docs/operations/screens/).
4. Fix real bugs you find (small, focused, with a test); ship with tools/ship.py; note it in HANDOFF.md.
5. If nothing is open: run LOKI's own checks (Settings > System check), try 3 real tasks a normal person
   would ask, and file what broke as a new task for yourself or for LOKI (docs/EVOLVE.md roadmap line).

## Rules (never break these)
- **Don't remove anything, only improve** (owner, 2026-10-19): never delete a feature, menu entry, test check,
  file or doc to make something pass - move it, put it behind a setting, or archive it (docs/operations/archive/).
- Run for hours: follow the loop in ZIVA_TASKS.md "Ziva's long run" - pull, next item, ship, report, repeat.
- Publish ONLY with `tools/ship.py -m "..."` (Windows: `harness_data\.venv\Scripts\python.exe tools\ship.py`,
  Mac: `harness_data/.venv/bin/python tools/ship.py`). Never `git push --force`.
- Tests: at most 1 minute per run (the owner's rule). ship.py's default is a 60 s budget; `--full` only overnight.
- Never commit anything from harness_data/ (keys, memory, logs). Never paste keys or tokens anywhere.
- Never copy proprietary code (Ziva's included) or non-commercial code; only AGPL-3.0-compatible licences.
- Both platforms: every change must work on Windows AND macOS.
- LOKI's own tasks (docs/EVOLVE.md: E12-E15 ...) are for LOKI to build. Watch, unblock and report them;
  don't write those fixes yourself unless the owner says so.
- Core systems and ease of use come first.
- Ask the owner (Needs Mohamed in ZIVA_TASKS.md) before anything irreversible or that spends money.
- Never open visible terminal windows on the owner's screen (2026-10-18: "the terminal keeps popping up" - they were
  Ziva's own "ZIVA_TEST3" cmd windows). Run commands in your own tool, or hidden: Windows
  `Start-Process -WindowStyle Hidden ...` (never `start "TITLE" cmd`), Mac: no `open -a Terminal`. Close any you opened.
- Never open the owner's projects in Godot_v4.8-beta1_mono (it rewrites them); LOKI's Godot tab picks the right Godot.
