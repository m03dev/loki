# HANDOFF - where LOKI stands right now

Read this, AGENTS.md and docs/BUILD_BRIEF.md before working. Update this file when you ship
something significant (tools/ship.py), so the next agent - Ziva, Claude Code, Codex or
LOKI itself - starts from the truth.

Last updated: 2026-10-16 (session 22, Claude in the cloud).

## Session 22 (2026-10-16, Claude in the cloud): three.js world, glass GUI, workbench, Bonsai 2, TimesFM-3, Higgsfield, Mac hangs

Two commits. All 21 suites pass (`tools/ship.py --check`).

- **Mac "not responding".** Its engine still answered over the relay (444 ms, latest version), so the
  hang is the window or the machine, and the Mac's history points at memory: 16 GB, swap at 96-100%
  (M7: image-gen crashed WindowServer). Shipped: `GET /peer/diagnose` (busy locks, progress, failing
  system-check rows, Ollama's loaded models, memory pressure, update status, redacted log tails) and
  `POST /peer/restart`; from the UI side `POST /peers/diagnose|restart {peer}`. And the cause itself:
  `forecast.memory_tick` runs every minute in the bridge, forecasts memory 10 minutes ahead and, when
  LOKI is idle and memory is heading past 92%, unloads idle Ollama models (keep_alive 0) - at most
  once per 2 minutes. Not yet read on the real Mac: ZIVA_TASKS M8.
- **PC updates hung on the Git Credential Manager account picker.** `updater.git_env` now makes GCM,
  ssh and askpass non-interactive and passes `credential.https://github.com.username=<origin owner>`.
- **LOKI World on three.js** (`app/ui/world_three.js`, vendored r186): PBR, shadows, bloom, ACES, the
  water shader ported, instanced agents; linked machines are islands with a live light bridge; HUD
  shows model, today's cost and machines. The classic renderer stays as the fallback
  (`LOKI_WORLD_ENGINE=classic`). Godot/Panda3D were rejected: no Godot in the repo (AGENTS.md) and
  Panda3D would be a second window outside the webview; three.js runs inside the existing UI.
- **Glass GUI** (`app/ui/glass.css`): frosted panels over the full-window world, gradients, rounder;
  `prefers-reduced-transparency` falls back to solid.
- **Workbench, the Claude Code/Ziva habits** (`engine/workbench.py`, `app/ui/workbench.js`):
  checkpoints in a private shadow git store before every Build request, Review (diff), Rewind
  (undoable), `@file` mentions, an `@` picker and a `/` palette (/plan /build /review /rewind /bg
  /team /test /commit /model /image ...).
- **Bonsai 2** (PrismML, Apache-2.0) in `model_setup.CATALOG`: 9B/4B/2B ternary GGUF (Q2_0) pulled
  by Ollama from Hugging Face, plus the 9B MLX build. Q2_0 needs llama.cpp b11555+, so after a pull
  `verify_runs` asks one question and reports gibberish as "update Ollama". An installed model
  within 6 points (`INSTALLED_BONUS`) now beats a download, so nobody is nagged for a small gain.
- **TimesFM-3 in the core** (`engine/forecast.py`): one forecaster (TimesFM-3 when `timesfm3` is
  installed - MLX on Apple Silicon, torch elsewhere - Holt's damped trend otherwise) feeds three
  decisions: routing (`loki.routing_order` moves a provider forecast to be >2.5x slower to the back),
  the memory guard, and the spend outlook (`GET /forecast`). The agent has `forecast_series`.
  `POST /forecast/install` pip-installs it. Kill switch `LOKI_FORECAST=off`. NOTE: TimesFM-3's
  weights are licensed for non-commercial use; LOKI never installs it on its own.
- **Higgsfield** (`engine/higgsfield.py`): images (and video with an application id) via the
  official SDK's protocol, stdlib only. The key is pasted by the owner in Settings > General >
  "Higgsfield key" (KEY:SECRET), stored as `HIGGSFIELD_KEY` in LOKI's .env and never sent back to the
  window (new `secret` setting kind). Tool `generate_media`, route `POST /media/generate`, command
  `/image`. Outputs are downloaded into the workspace's images/ or videos/.
- **Not done:** "framepipe" - no repo by that name is visible to this session; the owner needs to
  give the exact GitHub name. No API keys were searched for or copied anywhere.

## Session 21 (2026-10-15, the PC - Ziva Windows): the agent/computer boundary, and one memory

All 19 suites green on the real PC (`tools/ship.py --check`), including test_systems "the bridge
rebinds the same port immediately" (SO_REUSEADDR off on Windows) - the `[windows]` signal Claude
asked for. `macos-app` and `origin/macos-app` are 0 ahead of master: **master really is the one
branch.** The old gap `backup/pc-merge-c25660f` is REVIEWED below.

- **ACI: bound EVERY tool result, and check a file the moment it is written** (ecc2558).
  `MAX_OUTPUT` bounded only COMMAND output, so a large `read_file` dumped a whole file into a local
  model's context. Now one choke point (`call_tool`, local and MCP): `loki._elide()` keeps the head
  AND the tail (errors and totals live at the end) and inserts a marker naming what was dropped.
  `loki._check_written()` checks a file the instant write/edit/append returns - `.py` (ast), `.json`,
  `.gd` (Godot). To SEE what a model really received, read `GET /progress?after=0` (bearer token):
  it carries `tool_result` events. Proof: a local model wrote a broken file and got "SYNTAX ERROR in
  scripts/check.py: invalid syntax (line 1)" in the same result.
- **`engine/memory.py`: ONE interface over the four tiers LOKI actually has** (272d30d). `working`
  (project_state) / `episodic` (reasoning_bank + experience) / `semantic` (memory.md facts + brain
  vault + knowledge) / `procedural` (agents.skills_catalog), behind `remember` / `recall` / `stats` /
  `describe` / `tier_of`, each DELEGATING to the module that already owns the bytes - no storage moved.
  `save_memory` writes through the semantic tier; the status payload carries `memory.stats()`. A
  read-only tier says so (procedural -> "write a SKILL.md instead").
- **Difficulty-aware routing** (d6c2db6). `LOKI_PREFER` defaults to `local`, so smart mode was
  local-first for EVERYTHING - hard work stayed on the weak offline model. `loki.triage_difficulty()`
  + `LOKI_HARD_DIFFICULTY` (default 2) now drops local-first for a hard request.
- **Local models are chosen by MEASURED tool calling** (0cd6012). `experience.tool_stats`/`tool_score`
  score each model on tool rate + clean rate; `loki._best_local_by_tools` picks the best record. The
  note explaining the pick is surfaced as `local_note`; `/status` carries `tool_stats`.
- **The literal `<tool_call>` tag crashes Qwen3.5's Ollama runner** (eb1919d, found on the PC).
  Ollama dies with `HTTP 500 {"message":"EOF"}` - reproduced on `loki-qwen3.5-9b` and `qwen3.5:9b`;
  `qwen3:8b`/`hermes3:8b` are fine. The harness now teaches a fenced ```json block and `parse()`
  still accepts `<tool_call>`. The old `_FENCE_RE` was non-greedy, truncating at the first `}` - so
  every real file write failed to parse; it now captures to the closing fence.
- **`engine/evals.py` (from Inspect) + `docs/architecture/SYSTEMS_TO_IMPORT.md`** (575e21d): Task =
  dataset + solver + scorer; scorers `wrote_file`/`called_tool`/`answered`; `record()` feeds the
  routing scorecard. The doc is the open-source deep dive (9 systems, verdicts, a "deliberately NOT
  taken" table, a priority list). Items 1-4 of that list are shipped: evals, difficulty routing,
  check-on-edit, memory tiers.
- **Ruflo's plugins are really committed, and image-gen is really on** (68882cc, a260f1a, 73043ee).
  `.gitignore`'s unanchored `plugins/` rule hid `contrib/ruflo/plugins` (0 files tracked), which made
  master red on a fresh clone; anchored to `/plugins/`. A changed image-gen manifest had silently
  flipped it to `changed` (= off); re-enabled and re-saved all 10 capabilities with the new `trust`
  field - live, an agent made an image in 24.8 s.
## Session 20 (2026-10-15, cloud + the PC): real water, and local models' long tool calls

- **Water** (app/ui/world.js `WATER_FS`, app/ui/world_noise.js): its own shader with an exact
  shore distance per body (no depth texture, works on every WebGL 1 driver): Beer-Lambert depth
  colour, wobbling shoreline foam + a breathing second line, cellular caustics, Schlick fresnel
  sky reflection, stepped sun/moon glint, station lamps reflected at night, whitecaps on the
  stream, ripple rings (LOKI's beacon pings the pool on every new board line; a fish jumps in
  the pond), a waterfall sheet with sliding streaks and a white lip. Stone curbs, lily pads, a
  tiled pool floor. Credits: docs/THIRD_PARTY.md (stegu/webgl-noise MIT; paddy-exe stylized
  water MIT). Screens: docs/operations/screens/world-water-*.png.
- **Found on the PC** (harness_data/_engine_ziva6.log, 10:37 today): a local model wrote a whole
  todo page as a TEXT write_file call; LOKI dropped it because the scanner counted the CSS/JS
  braces inside the content and the model left off the final "}". Then a reply was cut off
  mid-call and lost; the task looped to the step limit with no file. Fixed: string-aware
  `tool_guard.json_object_spans`, `close_truncated` (only adds missing closers at the very end),
  and `loki._unfinished_call`: a cut-off call is kept and the model is asked to continue it,
  then the two parts are joined. 7 checks in test_tool_guard built from that run.
- **Why the PC fell behind the Mac all day** (harness_data/app/loki_app.log on the PC): every start
  said "update waiting: local changes to 3 file(s)" - an agent's unfinished edits (a new memory
  interface) blocked EVERY update. engine/updater.py now carries uncommitted edits across an update
  when git merges them cleanly (three-way, CRLF-aware, backup under refs/loki/backup/edits-*); a
  real conflict still blocks as before. The PC's three edits were checked: all merge cleanly.
  test_updater: +12 checks.
- **Mac <-> PC live across networks** (the owner chose the built-in relay over Tailscale):
  engine/relay_link.py speaks bore's protocol in plain Python; each machine publishes its peer
  port on bore.pub at ports derived from the shared secret, and dials the other as name=relay
  through a loopback forwarder. Responses are now signed and bound to the request
  (peers.sign_response) and checked over the relay; a dead or wrong relay port is skipped.
  One link code links both ways (peer_link.link_back). Settings > Machines shows the relay;
  GET /peers/relay-test proves the loop on a machine. tests/test_relay.py (23, fake bore server).
  PROVEN LIVE on the PC against the real bore.pub (2026-10-16): the owner pasted the Mac's own
  link code into the PC's Settings > Machines, so the pair is linked both ways - the PC reaches
  mohameds-mac-mini through the relay in 423-425 ms (relay-test ok 2935 ms), and link_back adds
  the PC on the Mac by itself. ZIVA_TASKS R1 is done; nothing left for the owner.

## Session 19 (2026-10-15, cloud): LOKI World becomes a life sim, and stays smooth

Owner: "go through what's not working, only add, make the LOKI world more like a sim, more
features, improve the graphics, keep everything running smooth". All 16 suites pass.
Rendered and checked in headless Chromium (software WebGL) with a mocked /world - screenshots
docs/operations/screens/world-sim*.png. NOT yet seen on the real Mac/PC GPUs (ZIVA_TASKS W10).

What was not working (fixed, tested):
- **/world re-parsed the whole event log twice per poll** (up to 4 MB, every 2.5 s, per open
  view). `engine/events.py _tail_scan()` now reads only what was appended (rotation and
  half-written lines handled); `latest_seq()` uses it too. test_events proves no lines are
  parsed when nothing is new.
- **Two agents with the same role shared one speech line** (messages were keyed by sender
  only): now by team + sender.
- **A blocked agent's red light was always dropped** (exactly 10 lamps filled the shader's 10
  lights): lights are ranked; alerts first.
- The blocked/selected ground rings z-fought into invisibility (16-bit depth, near 0.1): rings are
  now opaque dashes and the near plane is 0.5.
- A lost WebGL context (sleep / GPU switch) left the world black forever: it is rebuilt.
- Drag could stick (no pointercancel); no pinch zoom; agents stood inside lamps and each other;
  labels piled on top of each other.
- **False DONE in the main task loop** (Ziva's [claude] request): `make_dir` - or a write that
  returned an error - counted as "changed a file", so "create notes/hello.txt" was accepted after
  only `mkdir notes`. engine/loki.py: errors change nothing; a goal naming a file needs a file.

Added (app/ui/world.js, docs/WORLD.md "The life-sim layer"):
- Agents walk round the plaza (not through the pool), act out each station's work (book,
  hammer + sparks, typing + lit screen, bubbling beakers, stamping, drawing), role hats, LOKI's
  horns, state icons (cube / hourglass / red "!" with a hand up / cheer + confetti / grey cloud).
- Done/idle agents leave the desk, sit on benches, wander and "chat" (a wordless ···).
- Team banners in the plaza with one pip per real stage (`teams[].stages` from the engine).
- Settings > LOKI World: click an agent or legend row -> inspector card (all from /world:
  task, station, machine, time on task, team + stage, last line), double-click / Follow ->
  camera follows, Esc, arrows, pinch. A HUD with local time and the real counts (`stats`).
- Scenery: reflecting pool, pond + waterfall + mist, flowers, grass, benches, crystals under the
  island, floating islets, birds, fireflies, twinkling stars, chimney smoke when building.
- /world adds per agent `since`, `finished`, `stage`; per team `stages`; top-level `stats`.

Smooth: the static scene is baked once (3 draws for everything that never moves, +2 for the
turning clouds/islets) - ~200 draws per frame whatever the scenery, ~1 ms of JS per frame.
A frame-time watcher steps world pixels one size coarser when frames run late and keeps it only
if frames really got faster (`World.adaptive = false` pins it). `prefers-reduced-motion` stops
the ambience.

Libraries: none added on purpose. The UI is offline and CSP-clean, and test_portal forbids
loading anything external; three.js/OGL/regl would add weight for things this renderer already
does. If a library is ever wanted, vendor it into app/ui (no CDN).

Next (ZIVA W10): open Settings > LOKI World on both machines, start a team, screenshot, report
frame feel and `World.views.panel.perf` (ema ms, boost, draws).

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
- ~~`backup/pc-merge-c25660f` ... not reviewed.~~ REVIEWED (Ziva Windows, 2026-10-15): the branch is
  local-only and holds exactly ONE commit master lacks - the pre-restructure merge whose content is
  the old `addons/loki/harness/` layout (`jobs.py`, `worker.py`, `workers.py`). That layout was
  deliberately replaced by the top-level `engine/` + `engine/workers.py`; jobs.py and worker.py do not
  exist on master. Nothing master lacks, safe to delete (kept as a backup branch on purpose).
- A running engine does not restart itself after an update; the next start applies it.
