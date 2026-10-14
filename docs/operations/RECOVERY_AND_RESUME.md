# Recovery and resume

How to find LOKI's state, recover from a bad change, and pick work up again.

## Where the state lives

| What | Where |
| --- | --- |
| Repo | `~/Documents/loki` (Mac), `C:\Users\macul\Documents\loki` (PC); GitHub `m03dev/loki`, branch `master` |
| Keys and settings | `harness_data/.env` |
| Engine log, token, app settings | `harness_data/app/` (`loki_app.log`, `engine.out`, `engine.token`, `settings.json`) |
| Chats | `<workspace>/.loki/loki_conversations.json` (older builds: `<workspace>/.godot/`, copied over once) |
| Memory | `harness_data/memory.md` |
| Background jobs | `harness_data/workers/`, worktrees in `harness_data/worktrees/` |
| Learning | `harness_data/experience/` (log, trajectories, training state) |
| Laya | `harness_data/laya/` (package and cached weights) |

The app's engine listens on `127.0.0.1:8767`; a command-line engine uses `8766`; the peer
link uses `8768` on a machine that listens.

## Start of a session

1. `git status`, `git log --oneline -10`, `git fetch` and compare with `origin/master`.
2. Read [../BUILD_BRIEF.md](../BUILD_BRIEF.md), [SESSION_LOG.md](SESSION_LOG.md) and
   [../ARCHITECTURE.md](../ARCHITECTURE.md).
3. Run the offline suites (README > Test). All must pass before and after a change.
4. If the app misbehaves, read the tail of `harness_data/app/engine.out`.

## Recover from a bad change

- Prefer `git checkout -- <file>` or `git revert <commit>` over hand-repairing.
- Before anything risky, push a safety branch (`git push origin HEAD:refs/heads/safety/<name>`).
  `safety/pre-hardening` and `safety/pre-restructure` already exist.
- Never `reset --hard`, force-push or delete a branch without a safety branch first.

## Traps that cost real time

1. Never broad-kill processes. Kill only an exact PID whose command line you have read.
2. Never move or delete folders on the user's machines on the strength of one listing.
   Check a second way first (a past session trashed the live app folder because one
   listing tool showed it empty).
3. A running engine keeps its old code until LOKI is restarted.
4. `.bat` files must be CRLF (`.gitattributes` enforces it); `call :label` cannot be piped.
