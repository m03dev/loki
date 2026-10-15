# HANDOFF - where LOKI stands right now

Read this, AGENTS.md and docs/BUILD_BRIEF.md before working. Update this file when you ship
something significant (tools/ship.py), so the next agent - Ziva, Claude Code, Codex or
LOKI itself - starts from the truth.

Last updated: 2026-10-15 (session 17).

## Session 17 (2026-10-15, cloud): local models that work, and an app that works by itself

Shipped to master at the owner's direction once both machines were online. All 16 suites
pass (cloud + CI on macOS and Windows). The two real-hardware checks (S2 local-model tool
calling, S3 idle autopilot) are open in ZIVA_TASKS - they confirm behaviour on a real
Ollama, they do not gate the code. Kill switches: `LOKI_AUTOPILOT=off`,
`LOKI_CONSTRAINED_TOOLS=off`.

- **Found why local felt useless** (`engine/loki.py`): a local provider that failed ONE
  request (a cold model load timing out, a brief restart) was marked used-up for the whole
  session, so every later request silently went to cloud or Claude Code until a restart.
  Now `revive_local()` brings a local provider back at the start of the next request once
  its server answers again (`LOKI_LOCAL_REVIVE_S`, default 20s). test_tool_guard proves it.
- **Tool-call guard** (`engine/tool_guard.py`, wired into `agent_turn`, text recovery and
  `call_tool`): repairs the calls small models get wrong - bad JSON (single quotes,
  trailing commas, fences), near-miss tool names (create_file->write_file, ls, cat, bash),
  numbers sent as strings, calls written as code - and when it cannot, returns ONE precise
  sentence naming the missing argument and the signature. GUARD_STATS counts repairs/rejects.
- **Constrained decoding for local servers** (`_use_constrained`/`_constrained_request`):
  sends a json_schema response_format so Ollama/llama.cpp can only produce a real tool call
  or an answer; falls back automatically if a server refuses it. `LOKI_CONSTRAINED_TOOLS=
  auto|on|off` (auto = on for local servers already in prompted-tool mode).
- **Agent factory picks a model per role** (`experience.role_stats`/`best_for_role`,
  `team.py`, `loki.model_for_role`): each team role (builder, tester, reviewer...) gets the
  model that has measurably done THAT job best, within the spending policy; a cheaper tier
  wins a near-tie; a pinned team model always wins. Jobs now record their role so outcomes
  can be scored. This is BUILD_BRIEF 5.3 "best spec per role", first real version.
- **Autopilot** (`engine/autopilot.py`, started by the bridge, `GET /autopilot`, a System
  check row): when LOKI is idle (no request in flight, no job, quiet for
  `LOKI_AUTOPILOT_IDLE_S`=600s) it does ONE duty per pass - **health** (run the System
  check, apply only the always-safe fixes, never approve/spend/update), **inbox** (start the
  oldest open `[loki]` request in ZIVA_TASKS.md as a team, one at a time), **report** (weekly
  "what LOKI learned": verified work, best model per role, routing changes, tool repairs,
  training readiness, in harness_data/reports/). `LOKI_AUTOPILOT=off` turns it all off. This
  is the first piece of BUILD_BRIEF 5.4/5.6 "alive and improving on its own".
- **Cloud testing is real now**: `tests/cloud_stubs/openai` used to fail every call, so the
  offline e2e and HTTP-400 checks were skipped in the cloud. It now speaks the
  chat-completions wire format over urllib, so every suite runs against the fake Ollama for
  real. Register it once per sandbox (see tests/cloud_stubs/README.md). The Mac/PC use the
  real openai package, unchanged.

Next (ZIVA): S2 - on the Mac and PC with real Ollama, run "create notes/hello.txt with hi,
then list the folder" with LOKI_CONSTRAINED_TOOLS=off/auto/on on your installed models,
record valid-call rate + GUARD_STATS. S3 - leave LOKI idle and confirm the autopilot's
health row and a weekly report appear (GET /autopilot).

## Session 16 (2026-10-15): System check + positive integration tests

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

## Phone app (2026-10-15, branch claude/phone, not shipped yet)

The owner asked for iOS + Android and a phone-local model. Built: `mobile/` (one Expo app:
Chat, Connect, Models) that chats with LOKI on the Mac/PC when reachable, else with a small
on-phone model (Cactus: Needle for quick actions + Qwen3 0.6B etc.; llama.rn as the swap-in).
Engine side `engine/phone_link.py` (opt-in, port 8769, per-phone signed keys, Ask/Plan only,
a phone message can never approve), the Phone card in Settings > Machines, docs/PHONE.md,
tests/test_phone_link.py. NOT yet: npm install / prebuild / a run on a real phone (the npm
registry was unreachable where it was built); see docs/PHONE.md "Not done yet".

## Session 17 (2026-10-15): Mac updates really work; bridge port fix; S1/S2 live; phone typecheck

Ziva (Mac). Shipped as v0.16 · patch 165/166.
- **The Mac updater worked, but a GOOD version was being rolled back.** On restart the Mac pulled
  origin/master `fb6f66806db6` and the engine could not bind 127.0.0.1:8767 - `OSError: [Errno 48]
  Address already in use` - so the app rolled back and recorded the commit in
  `.git/loki_update_health.json` `skip[]`, leaving the Mac one version behind. Cause:
  `BridgeHTTPServer.allow_reuse_address = False`, so a just-exited engine leaves the port in TIME_WAIT
  and macOS refuses the rebind for ~30 s. Fix: `allow_reuse_address = True` + a `port_is_answering()`
  guard (a live engine is still never overwritten - that matters on Windows). Regression check in
  `tests/test_systems.py` (fails without the fix).
- **Two tests were red on the Mac** (CI is off, so nobody saw it): `test_loki`'s status/upgrade check
  depended on the real models disk, and `test_updater`'s "a missing disk is named" hard-coded
  `/Volumes/LokiSSD/loki` (which exists here). Both made machine-independent; all 13 suites green.
- S1 System check (Mac): "All 12 systems work together. 3 worth a look" - no red rows. S2 (Mac):
  version label / model button / Settings > Local models verified; `world-mac.png` re-captured.
  P1 phone app: `npm install`, `expo install --fix`, `typecheck` (after fixing
  `mobile/src/brains/cactus.ts` to the installed Cactus types) and `prebuild`; `run:ios` blocked on
  Xcode + CocoaPods + an iPhone (Needs Mohamed).

## Session 16 (2026-10-15): System check + positive integration tests

The owner saw only red ("systems aren't integrated and working together yet"). Now:
- **System check** (`engine/system_check.py`, Settings > System check = first tab, and "Check
  everything" in the sidebar): 14 ordered checks in a background thread, each
  `{id, title, status ok|warn|fail|skip, detail, fix}` - engine/version/update problem; a model
  answers through the real smart route (latency, dead providers and why); that model calls
  `list_tree` through `_model_request` (prompted harness included); first layer; a real
  background job (built-in agent, `selfcheck` mode: no model, no tools) watched through the jobs
  API, the event stream and /world; a team dry run (board, events, world, then cleaned up);
  policy rules; add-ons changed/invalid; image backend (no image unless "Run a real image test");
  local models; usage + ReasoningBank; peers; phone link; disk + memory. Routes: GET/POST
  `/system/check`, POST `/system/fix` (safe actions only: provider_off, revive_providers,
  laya_warm, start_ollama, jobs_start, zimage_retry; never approves add-ons, updates or spends).
- **tests/test_systems.py** (in ship.py): five scenarios wiring real modules with fakes only at
  the edges - goal -> first layer -> model -> conductor -> policy -> usage -> ReasoningBank recall;
  jobs API -> real child process -> events -> world; team plan/build/check/fix -> verified;
  providers dying mid-run (402/401) -> failover -> the check names them and switches them off;
  the check all-green / red rows with the right fixes / over the engine's HTTP routes.
- Bugs found by wiring things together (fixed, tested): ReasoningBank stored every finished chat
  as a failure; the conductor's prompt section vanished when no specialist was ready; /fleet sent
  a second 404 response; a check job could wait behind the one local-model slot.
- Next: ZIVA_TASKS S1 - run it on the PC and the Mac and report the rows.

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
