# HANDOFF - where LOKI stands right now

Read this, AGENTS.md and docs/BUILD_BRIEF.md before working. Update this file when you ship
something significant (tools/ship.py), so the next agent - Ziva, Claude Code, Codex or
LOKI itself - starts from the truth.

Last updated: 2026-10-13 (session 12).

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

## Done earlier (see docs/operations/SESSION_LOG.md)

engine/ layout and no Godot files (5.1); Background and Brain tabs replaced by work in the
conversation (5.7); Laya as the first layer, warm and measured (5.2); docs cleaned (9).

## Next, in order (docs/BUILD_BRIEF.md section 5)

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
