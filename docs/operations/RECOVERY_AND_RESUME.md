# Loki — Recovery and Resume

How to recover work, reconstruct state, and continue after an interruption.

## Where the state lives
- Repo: `C:\Users\macul\Documents\loki`, branch `master`, remote `github.com/m03dev/loki`.
- Bridge log: `.godot/loki_bridge.log` (per-server `[mcp]` lines, traces, errors).
- Docks log: `.godot/loki_dock.log`.
- Conversations / memory: `harness_data/.env`, `harness_data/memory.md`,
  `harness_data/loki_settings.json`, `<workspace>/.godot/loki_conversations.json`.
- Bridge token: `.godot/loki_bridge.token`. Bridge listens on `127.0.0.1:8766`.

## Resume checklist (start of a session)
1. `cd` into the repo; `git status` and `git log --oneline -10`.
2. Read `docs/LOKI_MASTER_BLUEPRINT.md`, `docs/roadmap/IMPLEMENTATION_PLAN.md`,
   `docs/operations/SESSION_LOG.md`, and this file.
3. Run the suite: `harness_data/.venv/Scripts/python.exe tests/test_loki.py`
   (offline). Add `--live` only when a model and the MCP servers are available.
4. Confirm one bridge is LISTENING: `netstat -ano | findstr 8766`. A stale pre-`15f298e`
   bridge holds the port and its `--loki-root` points at `<repo>/harness`; kill that exact
   PID and let the dock relaunch one.
5. Read the tail of `.godot/loki_bridge.log`.

## Recover from a bad edit
- Prefer `git checkout -- <file>` back to the last good commit over hand-repairing.
- Before risky changes, create a branch or a stash checkpoint.
- Patching `loki.py`: locate lines by short single-line predicates, build backslashes as
  `chr(92) + "n"`, and `compile()` the new source in memory — refuse to write on
  `SyntaxError`. A failed match means **nothing** was applied; do not read a later
  "compiles OK" as success.

## Traps that cost real time (do not repeat)
1. Never broad-kill Godot processes. The argless console host runs the user's editor.
   Kill only an exact PID whose command line you read.
2. Do not put backticks inside a double-quoted bash string — they execute.
3. `--check-only` on one `.gd` reports bogus errors for sibling `class_name`s; whole-
   project load is the real test.
4. Godot does not hot-swap a `@tool` dock/plugin script — restart the editor to see UI
   changes.
5. A bridge started before an edit keeps running the old code until the editor restarts.

## If access is blocked
If a directory or operation is denied, identify the exact operation, determine whether it
is the tool, the app sandbox, or an OS permission, and tell the user the precise action to
take. Do not retry a denied operation repeatedly and do not bypass OS permissions.
