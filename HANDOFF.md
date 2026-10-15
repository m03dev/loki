# HANDOFF - where LOKI stands right now

Read this, AGENTS.md and docs/BUILD_BRIEF.md before working. Update this file when you ship
something significant (tools/ship.py), so the next agent - Ziva, Claude Code, Codex or
LOKI itself - starts from the truth.

Last updated: 2026-10-14 (session 15).

## The machines

| | Mac mini | Windows PC |
| --- | --- | --- |
| Name / address | `mohameds-mac-mini`, 192.168.1.71 | `pc` (`mo`), 192.168.0.101, RTX 3070 Ti |
| Checkout | `~/Documents/loki` (becomes a git checkout on the next LOKI start) | `C:\Users\macul\Documents\loki` (on `macos-app`; moves to `master` on the next start) |
| Laya (first layer) | not installed yet: run `bash setup.sh` once | installed, model downloaded, self-test passed |
| Keys | none yet (Settings > Connections) | OpenRouter, DeepSeek, Groq, Gemini, Claude Code, Codex |
| Peer link | set to **listen**, not linked to the PC | listening on 8768 as `pc` |

**The link does not work yet.** The two machines are on different networks (192.168.1.x and
192.168.0.x), so they probably cannot reach each other directly. Fix: put both on the same
network, or install Tailscale on both (the link accepts Tailscale addresses), then on the Mac
use Settings > Machines > *Link another machine* with the PC's code (not "Let other
machines link to this one").

## Same version everywhere (done, session 12)

- `engine/updater.py`: every LOKI fast-forwards to GitHub `master` when it starts; a plain
  folder copy is turned into a checkout in place; local edits and unpushed commits are never
  overwritten; while running it only checks and shows "update waiting".
  2026-10-15 (Mac updates not working): git now runs with Homebrew/~/.local/bin on PATH (the
  `gh auth git-credential` helper was invisible from Finder/launchd) and `-c safe.directory=*`;
  stuck states fixed instead of blocking forever (already-published local commits dropped,
  real ones rebased and kept unpushed, backup in refs/loki/backup/*; stale/deleted files
  restored; real edits block and are named); failures are mapped to an actionable message and
  persisted in `.git/loki_update_last.json`, so `/health` `update.error`/`update.problem` show
  the start-up result. Version label: `VERSION` file + commit count -> `update.label`
  "v0.16 · patch N" (UI still has to display it: app/ui/app.js showVersion).
- `tools/ship.py`: the one way to publish (tests, commit, rebase, re-test, push, tell peers).
- `.github/workflows/tests.yml`: every push is tested on macOS and Windows.
- LOKI can change and ship its own code: tools `improve_loki` (a background agent in a git
  worktree of LOKI) and `ship_loki` (runs ship.py). `LOKI_SELF_SHIP=auto|ask|off`, default
  auto; ship.py refuses to push unless every suite passes.

## Agent teams (done, session 12) - BUILD_BRIEF 5.3, first version

`engine/team.py` + tools `start_team`, `team_post`, `team_read`; `/teams` API; teams in the
work strip with their board. Roles per goal (Laya or rules), stages plan -> build -> check,
one fix round, stops when a stage cannot finish. Verified offline (tests/test_team.py) and
live on the engine API without a model (the team stopped correctly at the architect).
Not yet: placing team stages on the PC over the peer link; a real model run end to end.

## Session 15 (2026-10-14): repo private, Godot story removed, suites hermetic

Ziva (Windows), after pulling the session-14 branch into master:
- master fast-forwarded onto `claude/portal-world-updates` (portal, sign-in/QR, agent builder,
  3D world, Update everything, specialists).
- `m03dev/loki` made **private** (owner's request). The Mac must run `gh auth login` (ZIVA M2)
  or it stops getting updates; the PC is already authenticated.
- The "project is still in Godot" confusion removed: README, docs/WORLD.md, docs/STATUS.md,
  HANDOFF and docs/ARCHITECTURE.md now say the world is in the app (plain WebGL); the Godot
  task ZIVA_TASKS W9 is cancelled; the leftover Godot `addons/` deleted.
- test_loki + test_hardening made hermetic: they failed only on a machine that runs Ollama /
  llama-server and whose `.env` sets OPENROUTER_MODEL to a paid model. All 11 suites pass; no
  assertion was changed.
- `docs/LOKI_BLUEPRINT.pdf`: the improved master prompt + research + plan + both task lists.

## Session 14 (2026-10-14): portal, sign-in, Update everything, agent builder, 3D world

Built in the cloud by Claude; see ZIVA_TASKS.md for the full list and the machine checks.
- Settings reworked: General, Connections portal (43 providers, switches, Test, model picker,
  OpenRouter sign-in, QR codes, phone hand-off), Agents (builder), LOKI World (3D),
  Machines & updates (Update everything), Add-ons.
- Any model can use tools (engine/tool_harness.py); new providers and OpenCode.
- Update everything: peers first, then this machine; app restarts the engine (exit 75);
  a version that fails to start is rolled back and skipped (updater health file in
  harness_data/app/update_health.json).
- New specialists: media (yt-dlp, now in requirements), image (Z-Image Turbo / Pollinations),
  reach (Agent Reach). Optional installs: tools/setup_extras.py.
- Not run on a real machine yet: everything above. Ziva W1-W10 / M1-M7 are the checks.
- Not integrated: OBLITERATUS (removes model safety refusals). Kyojin is wired in but needs a
  Strix Halo machine.

## Session 13 (2026-10-14): the owner's five-layer vision

- docs/VISION.md (the owner's vision, kept), docs/STATUS.md (every item checked against the
  code - read it before planning), docs/WORLD.md (world protocol + Ziva brief).
- `events.py`: one event stream (task.*, agent.*, approval, artifact, verification, decision)
  emitted by jobs, teams, the first layer, approvals; `/events` long poll, `/world`.
- First layer returns the full structured decision; Jev answers when Laya cannot.
- Machines advertise real capabilities in hello.
- Spending policy: no automatic paid routing unless LOKI_ALLOW_PAID=1; daily dollar cap.
- Fixed: the goal loop's endless "premature DONE" path.
- The world is in the app (WebGL 3D); there is no Godot project. Checks: ZIVA_TASKS.md W6/M6.

## Done earlier (see docs/operations/SESSION_LOG.md)

engine/ layout and no Godot files (5.1); Background and Brain tabs replaced by work in the
conversation (5.7); Laya as the first layer, warm and measured (5.2); docs cleaned (9).

## Next, in order (docs/BUILD_BRIEF.md section 5; Ziva's list is ZIVA_TASKS.md)

1. Get the link working (network or Tailscale), then verify a job from the Mac runs on the PC.
2. 5.3 next steps: run a team end to end with a real model; place heavy stages on the PC
   (peer link) and stream their board notes back.
3. 5.4 the PC alive 24/7 as a service (start at boot, watchdog, apply updates on restart).
4. 5.5 cua VMs + Browser Use on the PC; 5.6 self-improvement loop running on its own.
5. 5.8 more model sources; 5.9 Ziva (no public API found as of 2026-10).
6. The owner asked for agents "talking and in game": agents talking is the peer link + team
   board (5.3); "in game" needs a decision from the owner (agents shown inside a game, or
   agents that build and play-test game projects).

## Known gaps

- The real Laya model is verified on the PC only.
- `backup/pc-merge-c25660f` on the PC holds an old merge with `jobs.py`/`worker.py` that
  look superseded by `engine/workers.py`; not reviewed.
- A running engine does not restart itself after an update; the next start applies it.
