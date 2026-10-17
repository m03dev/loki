# HANDOFF - where LOKI stands right now

Read this, AGENTS.md and docs/BUILD_BRIEF.md before working. Update this file when you ship
something significant (tools/ship.py), so the next agent - Ziva, Claude Code, Codex or
LOKI itself - starts from the truth.

Last updated: 2026-10-17 (session 27 research ports, Claude worktree).

## Session 27 (cont.): the Mac's white window

The owner reported the Mac shows only a white window (Ziva Mac was looking into it; this session has no access to
the Mac). Whatever the cause, a blank window is now impossible to miss and easy to diagnose: `app/ui/boot.js`
loads first and catches script/load errors, sends them to the engine (`POST /ui/error` -> engine.out "window
error" lines, `/health` `ui_errors`), and shows a rescue screen with the errors, Reload, and "Reload without the
3D world" (localStorage loki.safeMode; cleared when Settings > LOKI World is opened). loki_app.py never shows
about:blank any more when the engine fails - it shows the log tail. An update relaunch now hard-exits the old copy
after 2 s (closing a window off the main thread can hang on macOS, leaving a blank old window). Bonsai 2 gets
/no_think like qwen3. ZIVA M18.

## Ziva (Windows), 2026-10-17: the PC session-26/27 checks, and a duplicate fix dropped

Ran the [windows] inbox item and W21/W20/W19/W18/W10/W23 on the real PC. All 28 suites green. Highlights:
`POST /peers/diagnose {peer: mohameds-mac-mini}` works over the live relay and is REDACTED (no stuck
request, empty log tails); the Babylon pixel world is the default and holds ~60 fps (panel ema 16.7 ms,
boost 0); the Mac linked and /world.machines shows it ("1/1 machines linked"); Settings > Creations makes
a real ~1 MB picture with zimage in ~7 min; three/classic/babylon all switch; the option cards and CRM
work. Not done: Ollama upgrade (0.40.5, needs the owner), the fox close-up, W22 (MMO) and W24 (research
ports).

I started fixing the weak-model "Make it" bug (the model invented a tool `image`, wrote the prompt text
into the PNG and called it DONE) and then found Claude's session-27 commit (a5deaad) had already fixed it
the same day and better - call_tool now routes a role name like `image` to conductor, `_salvage_reply`
keeps text tool calls, `_specialist_made` counts a specialist-written file, and Creations makes pictures
DIRECTLY (POST /creations/make, no model). So I dropped my duplicate patch (no code shipped from this
session) and VERIFIED the upstream fix on the PC instead: /creations/make made a real 1,056,903-byte PNG
via zimage. Details, fps and screenshots are in ZIVA_TASKS.md (W21/W23).
## Session 27 Godot MMO (worktree)

The owner: LOKI World becomes a real MMO "like hordes.io ... mmo everything we can", in **Godot 4**. Built in a
Claude worktree as **`game/loki-world/`** (AGENTS.md: the one Godot project), GL Compatibility so the desktop and
web builds look the same. docs/WORLD.md "LOKI World in Godot 4" has the controls, options and export steps.

- **Play:** your own character (class hat + weapon), WASD + mouse orbit camera, jump, click/Tab to target,
  hotbar 1-9 (Strike, Bolt, Mend, then LOKI actions that start REAL jobs: picture, research, build, video, game,
  then Hearth), cast bars, cooldowns, damage numbers, XP and level-ups, emotes, day/night from the clock.
- **World:** this machine's island at home, every linked machine its own island out in the sky, walkable bridges
  of light, fly via the map (M). LOKI's agents are NPCs at their stations (classes, levels from finished jobs);
  quests = jobs (turn in at LOKI); failed jobs = monsters (beat one: XP + lesson scroll + "retry on a stronger
  model"); loot = creations (hung in the creations hall, in the bags); the fox and two rabbits.
- **HUD:** nameplates with bars, player/target/party frames, minimap + big map, chat (Say via presence, `/l` to
  LOKI via POST /chat), quest tracker + log, bags, character sheet (name/class), loot window, help, pair window.
- **Look:** 4-band cel shading with faceted normals, ink outlines (inverted hull; islands bake theirs - 2 draws
  per island), 1/3 resolution upscaled nearest + posterize/Bayer dither, banded sky, crystals, waterfall.
- **Net:** `autoload/loki_api.gd` follows docs/MMO_API.md (GET /mmo/state 3 s, /mmo/* actions, /world/presence
  150 ms/1 s); falls back to deriving the game from /world+/jobs+/creations on an older engine; offline demo
  world without LOKI. Token: page fragment (web) or LOKI's state folder / --token / Pair (desktop).
- **Web hook:** Settings > General > LOKI World look = **godot** loads `/ui/world_godot/` in one frame laid over
  the home background or the LOKI World panel (app/ui/world_godot/host.js; world.js: 4 small hooks); falls back
  to Babylon when the export is missing. engine/loki_bridge.py serves `.wasm`/`.pck` and gives
  `'wasm-unsafe-eval'` + same-origin framing ONLY to /ui/world_godot/index.html; portal_api lists "godot".
- **Verified here:** Godot 4.7.2 built from source (release downloads are blocked here) - the project imports, its
  own headless tests pass (107), and it plays headless against the REAL bridge (source=engine, quests/monster/loot
  from fake jobs, presence and chat both ways); screenshots rendered with Mesa llvmpipe under Xvfb (software, ~13
  fps - not a GPU number). A Linux release export (template built from source too) starts and runs the game.
  tests/test_godot_world.py (84) is in SUITES; it runs Godot only when one is on PATH
  (`LOKI_SUITE_GODOT`). tests/test_loki.py's "no Godot files" check now exempts game/loki-world/ only.
- **Not done here:** the Web export (needs Emscripten-built templates; their download host is blocked) and the
  Windows/macOS exports - ZIVA W26 (PC, Godot 4.8) and M17 (Mac). No real GPU, WebView2 or WKWebView run yet;
  sound; Steam (notes in WORLD.md). The web export, once made, must be committed (index.js/.wasm/.pck).

## Session 27 (2026-10-17, Claude in the cloud): why every LOKI job failed, and the fixes

From the PC's job logs (harness_data/jobs): background jobs run on qwen3:8b (PREFER=local, easy triage) and
1. it returned EMPTY replies - qwen3's thinking ate the answer (`think: false` is not honoured on Ollama's
   OpenAI-compatible endpoint) -> `_small_model_kwargs` adds Qwen3's `/no_think` switch to the system message;
2. it wrote tool calls as text (```json blocks) and called the image maker as a tool named "image" ->
   `_salvage_reply` turns text calls into real calls on every provider and drops <think> tags; an unknown
   tool named like a conductor role (image, research, generate_image...) runs conductor(role=...);
3. a real image it made did not count as work, so "DONE is premature" told it to write_file (a Godot-era
   nudge) and it wrote "a fox asleep in the snow" into images/fox_asleep_in_snow.png, which the checker
   passed -> a specialist's "made <file>" counts as written work; write_file refuses .png/.jpg/.mp4/...;
   verification checks a media file's magic bytes (a text "png" FAILS); the nudge is generic;
4. a stuck small model ended the job (empty replies, DONE without work, "BLOCKED: Builder's role
   unavailable", no tool calls) -> `_escalate_model`: once per background job, carry on with the first
   free, set-up online model (never paid on its own); LOKI_NO_ESCALATE=1 turns it off;
5. the self-improvement job crashed: Claude Code's argv held a NUL byte (from a binary read) and ~21k
   tokens (Windows caps a command line at 32,767 chars) -> cli_agents cleans control bytes and sends long
   prompts on stdin; a ValueError is a CliAgentError, not a traceback.
Creations' "Make it" for a picture now calls the image specialist directly (POST /creations/make, a
thread; the wall shows "Making..." and failures) - no chat model in between.
- **Update everything** now restarts the WHOLE app on every machine (app/loki_app.py relaunches itself and
  the new copy waits for the old one), and a waiting update is applied by itself when LOKI is idle (no chat,
  no running job) - checked every 10 min (LOKI_FORCE_UPDATE=0 / LOKI_UPDATE_EVERY_S to change).
- **Icons in favour of words** (`app/ui/icons.js`): the main buttons and Settings sections are icons; hover
  or focus one for its name and what it does. Settings is an icon rail (search is an icon that opens the
  field). Words stay in aria-labels and for the search.
- **Owner decision: the MMO is Godot.** LOKI World becomes an MMO built in Godot 4 (`game/loki-world/`),
  exported as its own app for Steam AND as a web build inside LOKI's window (replacing the Babylon world
  there when it lands). The Godot tools in LOKI stay. AGENTS.md updated.

TimesFM-3: the owner said yes (engine/data/owner_approvals.json); each engine installs it once at start-up
where missing (LOKI_TIMESFM_APPROVED=0 says no; suites never install). It forecasts numbers (usage, cost,
trends) for the forecast_series tool - it does not make jobs succeed; the fixes above do.
tests/test_job_fixes.py (33).

## Session 27 MMO world (worktree)

The owner: make LOKI World "more like hordes.io ... an actual mmo" (own character, MMO HUD, agents as
NPCs with levels/classes, jobs as quests, failures as monsters, loot = creations, combat, and the Mac and
PC seeing each other). Mid-session the owner changed plan: **the MMO client will be a Godot 4 game**
(own repo; Steam desktop build + a web build inside LOKI's window replacing the Babylon world there).
So this worktree built the **engine side every client uses** plus the first in-app stage as a fallback.

- **Contract: docs/MMO_API.md** (auth = the bridge's bearer token, loopback Host/Origin rules, polling
  rates, payloads, coordinates/zones, combat numbers, presence interpolation).
- **engine/mmo_state.py** + bridge routes `GET /mmo/state`, `POST /mmo/profile|skill|quest/accept|
  quest/turnin|monster/defeat|monster/retry|note`: quests = jobs, monsters = failed jobs (named from the
  error, stable spawn), loot = creations (+ lesson scrolls), NPC classes/levels from roles and finished
  jobs, a 9-slot hotbar whose LOKI actions start real jobs through the bridge's own `job_action` (policy
  included; same prompts as Settings > Creations). First run turns the owner's past work into XP.
  Progress: `<DATA_DIR>/mmo/profile.json`.
- **engine/presence.py** + `POST/GET /world/presence`, `presence` in GET /world, signed
  `POST /peer/presence` (peers.py route, peer_link callback): one exchange carries both machines'
  avatars and chat (works over a one-way relay link), pushes only while a world is open (~350 ms moving,
  2 s idle), back-off for a dead peer, everything sanitised. `/world/retry` = retry without the game.
- **In-app stage 1** (`app/ui/mmo/mmo_core.js`, `mmo.css`, small guarded hooks in world.js): Settings >
  LOKI World > Play: WASD/mouse/QE camera, jump, collisions, island edges, bridges of light to the other
  machines' islands (zones), class avatars, WebAudio beeps; Spectate = the old view. No HUD/combat/
  presence client in the browser (stopped per the new plan). Pooled drawing, no per-frame allocation.
- Tests: `tests/test_mmo.py` (77, in SUITES): files/hooks/no-CDN/perf guards, presence over a real
  signed peer link on loopback (both directions in one call, dedupe, expiry, back-off, wrong secret,
  old peer 404), game rules, routes with a fake engine and over the real BridgeHTTPServer.
  Screenshots: `tests/mmo_preview/shot.py` (headless Chromium + SwiftShader; checked babylon + classic).
- **Not done / needs a machine**: fps of Play on the real Mac/PC; presence between the real Mac and PC
  has only run on loopback (ZIVA W22/M14 ask for a two-machine `/world/presence` check); the Godot web
  build needs `.wasm`/`.pck` in UI_TYPES and `'wasm-unsafe-eval'` for its page (see MMO_API.md section 1).
Last updated: 2026-10-17 (session 27 harvest, Claude worktree; session 26 before it).

## Session 26 (2026-10-17, Claude in the cloud): Babylon.js world, one island per device, Creations

- **Babylon.js is LOKI World's engine** (owner's choice, over Godot/Panda3D: it runs inside the app's
  webview on both machines with no extra install). `app/ui/vendor/babylon/babylon.loki.js` is Babylon 8.9.1
  built from source (Apache-2.0; rebuild steps in `tools/babylon/README.md`, CellMaterial patched by
  `tools/babylon/patch_cell.py`). `app/ui/world_babylon.js` draws the same scene description world.js makes
  every frame, in the SAME pixel cel-shaded look the owner likes: CellMaterial bands, ink outlines (an
  inverted hull), a hardware pixel grid (setHardwareScalingLevel + `image-rendering: pixelated`), the Bayer
  posterize as a post-process, blob shadows, halos, the water shader. Thin instances: ~14 draw calls a frame.
  Lazy-loaded; if it cannot load, the world falls back to LOKI's own renderer ("classic"). Settings > General
  > LOKI World look: babylon (default) / classic / three. Nothing was taken off.
- **Every device has its own island.** `/world` now says which machine it is (`self`: name + OS). The island
  you stand on is THIS machine ("<name> - you are here" over the spire); each linked machine is a full island
  of its own out in the space around it (its house in its colours - a Mac silver, a PC blue - trees, a beacon
  lit while it answers, a figure per job, a bridge of light with packets). Slots come from the machine's name
  so islands never jump or overlap. Click a machine's name to fly there; "back to <name>" brings you home.
  So on the Mac you stand on the Mac island and see the PC's island out there, and the other way round.
- **Creations - more of the fox.** The fox picture the owner loved was made by LOKI's image specialist
  (conductor `image`, free Pollinations backend) on 2026-10-14 20:17 when Ziva Windows ran W13
  ("make an image of a red fox in studio light"); it is `images/20261014-201742-red-fox-in-studio-light.jpg`
  in the PC's workspace. New: Settings > **Creations** (`creations.js`, `engine/creations.py`, GET
  /creations, files at /creations/<kind>/<file> - this machine only, sandboxed) shows everything LOKI made,
  newest first and big, with a "Make it" box (picture / video / game, starts a background job) and "Make
  more like this". On the island a **creations hall** hangs the newest five pieces; its name opens Creations.
- Still open (owner to answer): remove the Godot code (AGENTS.md says nothing Godot; the owner also said
  "don't take anything off").

## Session 27 research ports (worktree)

The owner: "take code from open-source repos to improve LOKI natively - not the ones we have, but also
research for me". Researched ~36 NEW projects (none already in LOKI) and ported the best nine as native
engine modules + 11 tools. Full ranked table with sources: `docs/integrations/research-2026-10-17.md`.
Built in a Claude worktree, committed there, not pushed; the parent session merges and ships.
**26 suites pass** (`tests/test_research_ports.py` is new: 141 offline checks, fakes only).

Licences sit in `engine/licenses/` (Aider Apache-2.0, ReWOO/Reflexion/STORM/bigtool/instructor/ACE-Step MIT,
Kokoro Apache-2.0, Fooocus GPL-3.0); rows in docs/THIRD_PARTY.md. **Fooocus is GPL-3.0**: like OpenHuman and
MuMuAINovel, `engine/image_prompt.py` + `engine/data/image_styles.json` must go before LOKI is ever published.

**New tools (loki.py: one registration block after SELF_IMPROVE_PRIORITY; nothing in agent_turn, the goal loop,
_model_request, the parser or the DONE gate was changed):**
- `repo_map(focus, subdir, max_chars, files)` - aider's repo map (`engine/repo_map.py`): ast/regex tags,
  def/ref graph with aider's weights, personalized PageRank, budget fit. LOKI additions: `module.name` refs go to
  module.py only; a file's own copy of a common name is no cross-file edge; symbols named in `focus` come first.
- `apply_edits(blocks)` - aider's SEARCH/REPLACE blocks (`engine/edit_blocks.py`): several files per call,
  whitespace-forgiving + `...` matching, did-you-mean on failure, partial success, CRLF kept, `undo_edit` works.
- `find_tools(query)` - langgraph-bigtool (`engine/tool_select.py`): BM25 over all offered tools; the matches are
  inserted after `find_tools` in LOCAL_TOOL_PRIORITY (at most 6, oldest drops), so a local model sees them next
  step. `find_tools` and `repo_map` were added to LOCAL_TOOL_PRIORITY (index 5-6).
- `extract_structured(text, schema, instruction)` - instructor (`engine/structured.py`): JSON Schema validation,
  re-ask with the errors, constrained `response_format` on local servers (falls back once if refused).
- `plan_and_solve(task)` - ReWOO (`engine/rewoo.py`): one plan with `#E` variables, read-only tools run through
  `call_tool` (policy applies - a path outside the workspace is DENIED, tested), one solve call.
- `reflect(task, attempt, feedback)` - Reflexion (`engine/reflexion.py`): diagnosis + new plan stored as an
  episodic memory tagged `reflexion`, so the memory pack offers it on similar later tasks. `trial_loop` is there
  for callers with an evaluator (not wired into evolve yet - see Next).
- `web_search(query)` - keyless: DuckDuckGo HTML, or SearXNG when `LOKI_SEARXNG_URL` is set.
- `deep_research(question, depth 1-3)` - STORM (`engine/deep_research.py`): editors -> questions -> queries ->
  read_web -> cited answers -> outline -> sections -> `research/<date>-<slug>.md` with references.
- `enhance_image_prompt(prompt, style)` - Fooocus styles (25: pixel art, cinematic, anime, ...) + expansion by the
  model or a seeded offline fallback. The image path (conductor/generate_media) is unchanged; the model passes
  the enhanced prompt on.
- `make_music(prompt, lyrics, duration, bpm, key)` - ACE-Step 1.5 REST client (`engine/music.py`), to
  `music/`. Needs `uv run acestep-api` on the machine (or `LOKI_ACESTEP_URL`).
- `speak(text, voice_name)` - Kokoro when `pip install kokoro soundfile` was run, else macOS `say`, Windows SAPI
  (text via env vars, never in the script), espeak-ng (`engine/voice.py`), to `voice/`.
- New settings category "research" (web_search, deep_research); the others joined files/planning/memory/creative.
  `apply_edits`, `deep_research`, `make_music`, `speak` are MODIFYING (not offered in Plan mode).
- Shared model call `_port_ask` (active model, `think: false` on Ollama, usage recorded, `<think>` stripped).

**Not verified (no machine, no network here):** no live model has driven any of these tools; DuckDuckGo was
blocked by the sandbox proxy (the parser is tested on a saved page); ACE-Step and Kokoro never ran; `say` / SAPI /
espeak argv shapes are tested with fake runners only. ZIVA_TASKS W22 (PC) and M14 (Mac) ask for all of it.

**Next (from the research):** a "fix this bug" pipeline (Agentless: repo_map localize -> apply_edits candidates ->
check) and Reflexion's `trial_loop` around it; stable-diffusion.cpp (PC) / mflux (Mac) as local image backends fed
by enhance_image_prompt; Wan2GP as the PC's video add-on; Playwright MCP (accessibility snapshot) for text-only
browser control; arXiv/Wikipedia/GitHub sources in deep_research; MMO notes for the world agent are in the
research doc (Colyseus + snapshot interpolation + bitECS/miniplex).
## Session 27 harvest (worktree)

The owner: "go through all the connectors and add-ons we talked about, every single repo we have
documented - take the code and improve LOKI, not the ones we have." Licence: "LOKI stays private,
copy anything". Built in a Claude worktree, committed there; the parent session merges and ships.
**26 suites pass** (`tests/test_harvest.py` is new: offline, fake openers, 149 checks).

**docs/integrations/HARVEST.md** is the inventory: every `github.com/...` in docs/, engine/,
contrib/, capabilities/, tools/, app/ui, HANDOFF and ZIVA_TASKS (91 rows; 12 placeholder links left out),
each with licence, what LOKI already had, what was worth taking, and the decision. Session 26's
ports (OpenHuman, OpenHands, Scrapling, MuMuAINovel, PenEcho) were not redone.

**Ported into LOKI's own code (13) - priority: agents that succeed on qwen3:8b and free models:**
- **Edits that land** (Hermes Agent `fuzzy_match.py` + `escape_drift_autocorrect.py`, copied; the
  opencode/cline replacer chain): `edit_file` falls back to line-trimmed, whitespace/indent-flexible,
  escape-, unicode- (smart quotes/dashes), boundary-, block-anchor and context-aware matching, says which
  one matched, and a miss shows the closest lines. A one-line "similar" match is NOT accepted (a guess).
- **Edits that cannot break a file** (SWE-agent lint-on-edit, `engine/lint_guard.py`): an `edit_file` /
  `insert_lines` that introduces a syntax error (Python, JSON, TOML, XML, brace balance for JS/TS/CSS/
  Go/Rust/Java/C...) is not written; the model gets SWE-agent's "your edit would have looked like / the
  original" report. Errors already in the file are not blamed. LOKI_EDIT_LINT=0 turns it off.
- **Web search with no add-on** (Vane, `engine/web_search.py`): tools `web_search` (modes web, academic
  = arXiv, discussion = Reddit, news) and `research_web` (search -> read the best pages -> crawl4ai BM25
  keeps the relevant parts -> numbered sources + Vane's citation rules, one call). SearxNG when
  `LOKI_SEARXNG_URL` is set, else DuckDuckGo HTML, arXiv Atom, Wikipedia API.
- **Focused reading + local RAG** (crawl4ai, `engine/content_filter.py`): `read_web(url, query=...)`
  returns only the parts about the query; `search_docs(query)` = BM25 over workspace files (pdf with pypdf).
- **Text browser** (browser-use + page-agent, `engine/text_browser.py`): `browse_page` open/click/type/
  select/submit/scroll/back/find with numbered `[i]<tag ...>` elements; GET forms only unless
  LOKI_BROWSE_POST=1 (a POST changes something on a site - Browser Use add-on asks first).
- **Site maps** (Firecrawl map, `engine/site_map.py` - AGPL port): `map_site(url, search)`.
- **Reach** (Agent Reach, `engine/reach_native.py`): `reach(url)` - GitHub API (repo + README, issue + comments,
  file), RSS/Atom, YouTube oEmbed, Reddit/JS pages through Jina Reader (LOKI_JINA=0 = never). Its URL
  rules now also guard `loki._private_host`: `127.1`, `2130706433`, `0x7f000001`, `*.internal`,
  `metadata.google.internal` are refused everywhere LOKI fetches.
- **Code maps** (SWE-agent filemap/search_dir, `engine/code_map.py`): `code_map(path)` - a file's outline
  (Python bodies elided) or a folder's map of symbols with line numbers.
- **Compression** (Headroom SmartCrusher + LogCompressor, `engine/compress.py`): `_elide` (the one tool-result
  choke point) now keeps a big JSON array's first/last/error rows and a long log's errors, traces and
  summary before falling back to head + tail.
- **Skill abuse rules** (SkillSpector `agent_skills.yar`, `engine/skill_rules.py`): always-on
  `skill_scan.NATIVE_SCANNERS` (the add-on's EXTERNAL_SCANNERS stay separate). 0 of LOKI's 260 skills trip it.
- **Scheduled tasks** (Hermes cron, `engine/schedules.py`): `schedule_task add|list|remove|pause|resume`
  ("every weekday at 9am", "in 30m", "every 2h", cron lines, ISO times; cron matcher built in). The
  autopilot's new `schedules` duty starts a due one as a background LOKI job at its time (idle or not;
  never two runs of one schedule at once). A background job cannot schedule jobs. Store: harness_data/schedules.json.
- **Tool-argument coercion** (Hermes arg_coercion) in `tool_guard`: JSON-string objects, JSON-string
  array items, "null".
- **Skills**: six Apache-2.0 skills from anthropics/skills in `skills/anthropic/` (catalog source
  "anthropic"); the proprietary docx/pdf/pptx/xlsx skills were not copied.

Where it is wired (small blocks only): `engine/loki.py` tool block after the session-26 tools,
schemas after `read_web`, MODEL_TOOL_NAMES, TOOL_CATEGORIES (files: code_map/search_docs; web: the
web tools; planning: schedule_task), LOCAL_TOOL_PRIORITY (research_web, web_search, read_web, code_map
right after the file tools), `NETWORK_WRITES` += schedule_task (Plan mode), `_elide`, `_private_host`,
`read_web(query=)`. Not touched: agent_turn, _pursue_goal, _model_request, the prompted-tools parser,
DONE verification, cli_agents.py, creations.py, conductor.py, app/ui.

**Licence:** ports keep their upstream licence in `engine/licenses/` (Hermes, SWE-agent, crawl4ai, Vane,
Firecrawl AGPL, browser-use, page-agent, Agent Reach, Headroom + NOTICE, SkillSpector); docs/THIRD_PARTY.md
has a row each. `engine/site_map.py` is an AGPL-3.0 port - one more file to remove if LOKI is ever published.

**Not done / check on a machine (ZIVA W22 PC, M14 Mac):** none of the web tools has met the real internet
(the cloud sandbox blocks DuckDuckGo/arXiv/Wikipedia) - whether DuckDuckGo's HTML page answers LOKI's
requests from the owner's IPs is the open question; a SearxNG (LOKI_SEARXNG_URL) is the robust fix if not.
No live model has used the new tools yet; scheduled jobs have not fired on a real engine. Skipped with
reasons in HARVEST.md: memory/graph servers (Hindsight, OpenViking, Graphiti), runtimes (ruflo family,
Paperclip, cua, herdr), phone/hardware projects, API-catalog entries, deepseek-harness (TS preview),
artemis (no longer public). aider is not documented in the project, so it was left to the new-repo research.

## Session 26 core upgrade (worktree)

The owner: "take all these plugins and take their code and parts of it and make LOKI better - not
so it calls out to them. It's not improving itself right now because it doesn't have those." Built
in a Claude worktree (branch `worktree-agent-a503d5a5908a26e4b`), committed there; the parent
session merges and ships. **25 suites pass** (`tests/test_core_upgrade.py` is new, 150+ checks).

**LICENCE: LOKI MUST STAY PRIVATE.** Code ported from GPL-3.0 projects is now in LOKI:
OpenHuman (`engine/memory_core.py`, `engine/subagent.py`) and MuMuAINovel (`skills/novel-writer/`).
The owner allowed any licence because the repo is private and LOKI is not distributed. The root
LICENSE (MIT) does not cover those parts; publishing LOKI would require removing/rewriting them or
releasing all of LOKI as GPL-3.0. Licences sit next to the code (`engine/licenses/`,
`skills/novel-writer/`); docs/THIRD_PARTY.md lists every port.

**Why LOKI was not improving itself (found and fixed):**
1. An improve job ran on `LOKI_IMPROVE_MODEL=online`; with no online key on the machine that name
   resolves to an unconfigured provider, so the job could only answer BLOCKED. Now
   `improve_model()`: online when a free online provider is set up, else `smart` (local).
2. On a local model the tool list is trimmed to 22 by `LOCAL_TOOL_PRIORITY` - `check_loki` and
   `ship_loki` were not on it, so a local improve job could neither test nor ship. Inside a LOKI
   worktree `SELF_IMPROVE_PRIORITY` now puts them first.
3. A job that ended "done" counted as **shipped** even when the model said DONE without calling
   ship_loki (or ship_loki refused). `ship_loki` now leaves proof (`harness_data/jobs/<job>.shipped.json`)
   and `Evolve.settle(..., shipped=, detail=)` records "finished without shipping: <its last line>"
   as a failure (retried in 3 days with that reason in the prompt).
4. A shipped roadmap step was offered again until this checkout updated (the tick lives in the
   pushed commit). `next_item` now skips a step whose last outcome is shipped.
5. Test runs inherited the engine/job environment (`LOKI_DATA` = the live data folder,
   `LOKI_WORKSPACE`, `LOKI_JOB_ID`, keys): the suites behaved unlike CI and could write into the
   owner's real data. `check_loki`/`ship_loki` now use `check_env()` and `tools/ship.py` strips
   `LOKI_*`/`HARNESS_*` from the suites' environment (`LOKI_SUITE_*` stays).
6. `check_loki` ran the MAIN checkout's ship.py, so a suite the change added never ran: it now runs
   the worktree's own `tools/ship.py`.
7. Long jobs had no context management (`LOKI_MAX_CONTEXT=0` = keep everything) and overflowed:
   the OpenHands condenser now sends the model a condensed view (see below).
8. Nothing fed outcomes back except one line in evolve.json: every settled attempt is now also an
   episodic memory (`memory_core`), recalled into the next improve job's memory pack.
9. Loop nudges were appended between an assistant's tool calls and their results (providers reject
   that); they now wait until the whole tool batch is answered.
The whole loop is tested with fakes: autopilot -> evolve -> improve job -> (no ship) failure with
reason + lesson -> next step -> (ship proof) shipped -> not rebuilt; and a scripted improve job
through the real goal loop (task_tracker, ranged read, edit, check_loki, ship_loki, DONE).
Still true: `LOKI_EVOLVE` auto = on only on the Windows PC; `LOKI_SELF_SHIP=ask` blocks shipping
from a background job (nobody can approve there).

**Built in (engine/, tools in loki.py LOCAL_TOOLS / schema / MODEL_TOOL_NAMES / TOOL_CATEGORIES):**
- `memory_core.py` (OpenHuman): `memory` tool learn | recall | fetch | forget; secrets scrubbed
  before storing; host-stamped metadata; IDF + recency + usefulness relevance; evidence capped
  OpenHuman-style; 8 calls per request. Every request gets a bounded **memory pack** (1800 chars,
  `LOKI_MEMORY_PACK_CHARS`) in its "This request" note - never in the transcript - and the reply
  metadata says which were used (`memories_used`, `skills_used`, `learned_skill` on /chat).
  `memory.py` keeps its API and adds learn/forget/pack; recall/stats include the core.
  Settings > Memory lists, searches, edits and forgets learned memories and skills
  (`app/ui/memory_panel.js`, `GET/POST /memory/core`).
- `skill_learning.py` (E2): a verified request with more than 5 tool calls writes
  `harness_data/skills/learned/<slug>/SKILL.md` (steps in order with the file that mattered,
  files changed, pitfalls, result); similar requests refresh it; the pack offers it next time and
  the reply says "used learned skill ...". Listed by the skills catalog as "learned".
- `subagent.py` (E3, OpenHuman): `run_subagent(task | tasks[], tools, max_turns)` - own small
  context, narrowed tools (never run_subagent/delegate/improve_loki/ship_loki/start_team), same
  model routing, one collapsed result, up to 4 side by side, stuck-stopped, turn cap 12 (40 in a job).
- `condenser.py` (OpenHands LLMSummarizingCondenser + its prompt): over 160 messages or 280k chars
  (60k on a local model; `LOKI_CONDENSE_*`) the MODEL gets head + one rolling summary + recent tail;
  the chat history the window shows is never cut. A "context too long" error condenses and retries
  once. Model down -> a summary built from the events.
- `stuck.py` (OpenHands StuckDetector): same call+result x4, same failing call, alternating pair,
  monologue -> one nudge, then the request stops with "BLOCKED: I was stuck in a loop".
- `file_editor.py` (OpenHands file_editor): `read_file(filename, start_line, end_line)` numbered
  ranges (a big file read whole shows its first lines numbered + the line count), `edit_file` needs a
  UNIQUE match unless `replace_all` (it used to replace every copy silently), `insert_lines`,
  `undo_edit`; CRLF files stay CRLF.
- `web_reader.py` (Scrapling core on the standard library): `read_web(url)` - main content as
  markdown, hidden/aria-hidden/template text and zero-width characters removed (prompt-injection
  sanitizer), browser-like headers. Used when no reader add-on is on; `scrape` and
  `conductor read_web` fall back to it. Local/private hosts refused (LOKI_NET_ALLOW to allow).
- `command_risk.py` (OpenHands PatternSecurityAnalyzer + normalizer): HIGH-risk run_command is
  refused in a background job and always asks a human in the window.
- `task_tracker.py` (OpenHands): `task_tracker` view/plan with todo/in_progress/done, mirrored to plan.md.
- Novel Writer (MuMuAINovel): the pipeline prompts translated to English as skills
  (`skills/novel-writer/` + `stages/novel-world|characters|outline|chapter|analysis`), with the
  foreshadowing ledger and chapter analysis; the template loads all six.
- Drawing pad (PenEcho's idea, no code): `sketch_reply(shapes)` - LOKI draws back on the pad
  (sketches/loki-*.json, `GET /sketch/reply`, drawn under the user's strokes, toggle "LOKI's drawing").
- docs/EVOLVE.md: E1, E2, E3 ticked.

**Not done / check on a machine:** OpenHuman channels (that is roadmap E10, Telegram); no live
model has run these paths yet (all fakes) - watch the PC's next evolve step in Settings > Lab and the
Memory tab in WebKit (window.prompt for Edit); the pad's "LOKI's drawing" on a tablet.

## Session 25 (2026-10-17, Claude in the cloud): LOKI's own game engine + Play, the Brain map back, an audit

- **LOKI Pixel Engine** (`app/ui/engine/pixel_engine.js`): LOKI's own small WebGL 1 game engine in LOKI
  World's look - low-res framebuffer, Bayer posterize, 4 cel bands, ink outlines, flat-normal box/sphere/
  cylinder/cone/pyramid meshes, entities made of parts, camera, keys/pointer, HUD, beeps, collisions; the
  world's critters and props as models (fox, rabbit, tree, rock, berry, person, island). No libraries.
- **Play** (Settings > Play, `play_panel.js`, `/ui/play.html`): games run in a sandboxed frame
  (`allow-scripts` only - no token, storage or engine access). Built-in game: **Fox & Berries**. Games LOKI
  makes live in `<workspace>/games/<name>/game.js`, served by `GET /games/<name>/<file>` (only that folder,
  only .js/.json/.png/.svg) and listed by `GET /games/list`. Agent tool `game_engine_guide` gives the model
  the API + workflow + a full example. Only `/ui/play.html` may be framed, and only by LOKI itself.
  CHECK ON THE MAC: WebKit and a sandboxed frame's `'self'` scripts (ZIVA M12).
- **Brain map back** (Settings > Brain, `brain.js`): BUILD_BRIEF 5.7 said remove it "unless it becomes
  genuinely useful (browsing and correcting what LOKI knows)" - it now is: force-directed map of /brain
  (settles, then stops - no idle CPU), search, read any note, and **edit or forget a remembered fact** in
  place (memory.md via /memory). The Obsidian vault can be added there.
- Shading: no rim highlight on flat ground (it lit distant grass cyan at low camera angles) - world and engine.
- **Ziva on the PC** (the owner's Godot, not LOKI): its panel had vanished because Ziva was set to "Use Main
  Screen Tab" and the PC's portrait screen at 125% fits only two main-screen tabs. Switched it to a dock in
  Editor Settings > Ziva > UI; it shows on the left again.
- **Audit (all owner goals)**: none fully finished. Biggest gaps after this session: Godot code still in the
  repo (godot_tools.py, godot_assets.py, ~150 refs in loki.py, Godot MCP servers, the first-run Godot API
  step) although the owner wants nothing Godot; the PC as a real 24/7 worker (start at boot, cua VMs, Browser
  Use, a first LoRA run); evolve has not finished a step yet; the phone app never ran on a phone and cannot
  reach the computer through the relay; most add-ons only tested with fakes. Next session: remove Godot.

## Session 24 (2026-10-17, Claude in the cloud): the pixel look is back, the lag is gone, LOKI grows itself

The owner was right: session 22 made three.js (PBR, bloom) the default world and put the world
full-window behind live-blurred glass. That replaced the pixel cel-shaded look they liked and
made the window lag. Nothing was taken off; it was put back and the cost removed:

- **World: LOKI's own pixel cel-shaded engine is the default again** (`World.engine = "classic"`,
  `LOKI_WORLD_ENGINE` classic|three, default classic). Improved, not replaced: denser pixels (panel
  2 px, background 3 px - was 3 / 4), more colour bits (32 levels, was 20) and 4 cel bands (was 3).
  three.js stays as an option and is now loaded ONLY when chosen (no 2 MB module parsed at start).
  The session-23 asset fixes (benches, flags, books, seated people-sized agents) apply to both.
- **The lag**: every glass panel had `backdrop-filter: blur(22px)` over a 3D canvas that redraws
  30-60 times a second, and each world label had its own blur - the browser re-blurred all of it
  every frame. `--blur: none`; panels are tinted (more opaque) glass; the transcript's scroll mask
  is gone too.
- **The fox** (the owner loves the fox an agent made): a fox now lives on the island - trots between
  the flower patches, sits and looks around, goes to see LOKI now and then, and curls up asleep at
  night (little z's) - plus two rabbits. Same boxes, cel shading and ink lines as everything else.
- **A crashed engine is restarted** (`app/loki_app.py supervise`): on the PC the engine exited 1 at
  22:53 and the window sat dead until morning. Now it restarts with a growing pause and reloads the
  window; after 5 crashes in 10 minutes it stops trying. (Cause of that exit: not in the logs.)
- **LOKI grows its own "OpenHuman", by itself** (`engine/evolve.py`, `docs/EVOLVE.md`, Settings >
  Lab): a roadmap of steps (memory you can see, its own game engine with a Play panel, learning
  skills from its own work, subagents, more island life, a creations hall, speed watch, voice,
  self-review, tools it writes itself, a phone channel). When idle, the autopilot's `evolve` duty
  hands the next step to `improve_loki` (own worktree, all suites, ship), one at a time; outcomes are
  kept and fed into the next attempt; failures retry after 3 days. The owner's ideas (Lab > Add
  idea) go first; LOKI's own ideas wait for the owner's OK. `LOKI_EVOLVE` auto = on only on the
  Windows PC (on 24/7). Tests: tests/test_evolve.py (29).
- **"Moved to the web"**: nothing moved - LOKI is still the same desktop window (pywebview; the PC's
  log says "opening the Loki window" every start) talking to its own engine on this computer. Only
  the Mac-PC link goes over the internet (the bore.pub relay), and that is signed.

## Session 23 (2026-10-16, Claude in the cloud): options, drawing pad, world fixes, softer GUI, add-ons

All 22 suites pass. The owner asked: fix world assets that made no sense, 3-4 suggestions for an open
request, a way to draw for LOKI, OpenHuman/Remotion/OpenHands/PersonaLive/MuMuAINovel/marketing
skills/scraper/CRM, a less blue GUI, and Ziva's instructions in git only (not in chat).

- **"Which do you mean?"** (`engine/options.py`, `POST /options`, `Workbench.offerOptions`): an open
  request ("make me a game") gets 3-4 different readings as cards - title, meaning, what LOKI would
  do - and the pick is sent as a precise request ("Just do it as I wrote it" too). The decision is a
  local heuristic (`looks_open`), so specific requests cost nothing; only open ones make one model
  call. `LOKI_OPTIONS` auto|always|off in Settings > General; `/options <text>` forces it.
- **Drawing pad** (`app/ui/sketch.js`, `POST /sketch`): "✎ Draw" in the composer - pen with
  pressure (tablet/Apple Pencil), marker, eraser, colours, undo/redo. The PNG is saved to
  `sketches/` in the workspace and the next message tells LOKI to read it with `view_image`
  (whose default prompt now describes a drawing, not a Godot screenshot). PenEcho (a full AI canvas,
  AGPL) is the optional add-on for more.
- **World assets fixed** (`app/ui/world.js`): benches were built rotated 90 degrees (seat pointing
  at the pool, back sideways, legs along the wrong axis) - now `benchFrame()` builds slats, back
  rails, posts, legs and arm rests along the ring, facing the pool. Team banners had the same bug
  (flag edge-on): now a crossbar, a flag along the ring with its stage pips sewn on, and a hem.
  Library books stuck out of the shelf sideways: now they stand in it. Agents were 1.5x too big and
  sank into the ground when sitting: people-sized now (about 1 unit; LOKI a head taller), seated on
  the bench seat with feet on the ground; doors are taller than people. Bloom and glow sprites
  toned down (threshold 0.9, strength 0.38) so lamps and visors stop blowing out.
- **Softer GUI** (`app/ui/glass.css`): navy glass -> neutral graphite, cyan/blue/violet accent ->
  low-saturation sage/slate/lilac, lower text contrast (#e4e4e7 on graphite), body glow cut to a hint.
- **Add-ons** (see the section below, built in a worktree and merged): built-in CRM, Scrapling
  scraper, 50 marketing skills (MIT), OpenHands harness, PenEcho / OpenHuman MCP, Remotion videos,
  PersonaLive card, Novel Writer template. MuMuAINovel (GPL) and OpenHuman (GPL) are NOT vendored:
  the novel workflow was written from scratch; OpenHuman runs as a separate program over MCP.
- **OpenHuman vs LOKI:** OpenHuman (tinyhumansai/openhuman) is a Rust desktop agent harness in early
  beta - a peer, not a replacement: LOKI has the Mac+PC link, the world, teams, the workbench and
  self-shipping. It can be used as a tool server.

## Ziva (Mac), 2026-10-16: Bonsai 2 fixed, add-on packages installed, one-click add-on install

- **Bonsai 2 was broken by the tag.** `hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Q2_0` also matches the
  repo's `-PQ2_0.gguf` (Prism ternary, ggml type 142), which no Ollama can load ("unsupported tensor
  output.weight size overflows"); the runnable file is `-Q2_0.gguf` (ggml type 42), and Ollama only
  gained type 42 in **0.40.6** (PR #18967). model_setup now names the file in the tag
  (`:Ternary-Bonsai-2-9B-Q2_0`), the failure message says 0.40.6+, and test_models_media guards it.
  Verified on the Mac: Ollama 0.40.6, smoke test answers "Blue".
- **Add-on packages installed on the Mac**: browser-use, crawl4ai, headroom-ai, scrapling,
  hindsight-client, vision (trackers/supervision/rfdetr), agent-reach, ffmpeg.
- **New: install an add-on from the app.** `engine/addons_install.py` holds the pip plan per add-on;
  `POST /capabilities/install {name}` runs pip in LOKI's venv (no shell string); Settings > Add-ons
  shows **Install** on any add-on that is on but missing its packages, and a manual hint for the few
  pip cannot install (herdr, hermes, SkillSpector). test_integrations' "missing library" checks are
  now hermetic (skipped when the library is present).

## Ziva (Mac), 2026-10-16: the three.js world was dead in every checkout - fixed

- `.gitignore`'s unanchored `addons/` rule (a leftover from the Godot era) git-ignored
  `app/ui/vendor/three/addons/`, so the three.js post-processing add-ons were never committed.
  `world_three.js` failed to import, `window.WorldThree` was undefined, and the world silently fell
  back to the classic renderer on every clean checkout (the PC, CI, a fresh clone) - it worked only
  where those files were still on disk. test_portal's three.js checks only grep the source TEXT, so
  the suite stayed green while the feature was broken.
- Fixed: vendored the three.js r186 add-ons (MIT; `'three'` imports rewritten to local paths),
  anchored `addons/`/`scenes/`/`scripts/` in `.gitignore` to the repo root, wired `LOKI_WORLD_ENGINE`
  into Settings > General (it could not be set before), corrected `docs/THIRD_PARTY.md`, and added two
  regression checks (every `world_three.js` import exists on disk; the ignore rules stay anchored).
- On the Mac the world now runs three.js at quality "high": panel ema 6.97 ms (~143 fps, 80 draws),
  home 34.7 ms - higher quality and faster than the classic fallback (14.6 / 48 ms). Glass text
  contrast 9.7:1 (home) / 11.5:1 (World panel) over the lit world = WCAG AAA. Screens:
  `docs/operations/screens/glass-home-mac.png`, `world-three-mac.png`. Tasks M8/M9 answered in ZIVA_TASKS.

## Ziva (Windows), 2026-10-16: the PC's update bug fixed, and W17 verified

- The PC had NO git credential helper at all, so Git Credential Manager opened its interactive
  account picker (cancelled -> 403) and the fetch failed - `harness_data/app/loki_app.log` showed
  repeated "GitHub sign-in needed on this PC", and LOKI could not update. Fixed on the machine
  with `gh auth setup-git` (wires the gh token as the credential helper); `git fetch` now works
  with no prompt and LOKI updated itself. (Claude's Mac-side updater fix bdfba9b was already on
  master; this was the PC's own missing piece.)
- Pulled master and ran W17 end to end: 21 suites green; LOKI World is three.js once M8's fix is
  on the PC (60 fps at high quality on the RTX 3070 Ti, WebGL 2 via ANGLE/D3D11, so the earlier
  silent classic fallback is gone); the "/" command palette, /review (a real unified diff) and
  /rewind (removed the file) were verified in a real Chromium over CDP;
  hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Q2_0 pulls (3.0 GB) but Ollama 0.40.5 cannot load it
  ("unsupported tensor 'output.weight' size overflows"); GET /forecast backend = statistical
  (TimesFM deliberately not installed). Screenshot docs/operations/screens/world-three-windows.png.
  Details and the Mac's diagnosis JSON are in ZIVA_TASKS.md (W17 + Reports).

## Session 23 add-ons (worktree)

Built in a worktree by a Claude subagent; the parent merges and ships. New suite
`tests/test_addons.py` (in ship.py SUITES). Nothing below has run against the real programs
(no Scrapling, OpenHands, PenEcho, OpenHuman or Remotion was installed): command lines and
fallbacks are tested with fakes.

- **Built-in CRM** (`engine/crm.py`, SQLite at `harness_data/crm.sqlite3`): companies, contacts,
  deals (stage lead..won/lost, value, currency), interactions (note/call/email/meeting), tasks (due,
  done), find, history and a pipeline summary (per stage, open/won value, win rate, overdue tasks).
  Agent tools `crm_add/crm_update/crm_find/crm_log/crm_pipeline` (category "business"; writes are
  hidden in Plan mode). Bridge `GET /crm`, `POST /crm/<add|update|delete|find|log|list|pipeline|history>`.
  Settings > CRM tab (`app/ui/crm.js`): pipeline line, deals (stage picker), contacts, companies,
  tasks, add forms.
- **Scrape** (`engine/runners/scrape.py`, conductor role `scrape` + agent tool `scrape(url, crawl,
  max_pages, dynamic)`): Scrapling Fetcher/DynamicFetcher markdown, or a SiteToMarkdownSpider crawl
  into `scraped/<domain>/` (+ pages.jsonl), max 200 pages. No StealthyFetcher / Cloudflare solving.
  Without Scrapling it reads the one page via read_web (crawl4ai / Firecrawl) and says
  `python tools/setup_extras.py scrapling`.
- **Marketing skills**: 50 skills from coreyhaines31/marketingskills (MIT, commit 365b412) in
  `skills/marketing/` (SKILL.md + references/, no evals; 2.8 MB) with its LICENSE;
  `agents.skill_roots` has a "marketing" root, and `list_ecc_skills` sees them too.
- **OpenHands** harness: worker agent + agent-builder engine + CLI agent (`openhands --headless
  --json --override-with-envs -t <task>` in the workspace). `workers.openhands_env` sets
  LLM_MODEL=openai/<LOKI's local model> (LOKI_LOCAL_MODEL, else the resolved LOCAL_STATE),
  LLM_BASE_URL=http://localhost:11434/v1, LLM_API_KEY=ollama; `LOKI_OPENHANDS_MODEL/_BASE_URL/_API_KEY`
  override. Needs the `openhands` add-on (process:agent). Template "OpenHands Coder".
- **Add-ons** (all off, never auto-installed; `setup_extras.py <name>` only when named, not in `all`):
  `penecho` (AGPL, MCP `penecho mcp`, card button "Open drawing canvas" -> http://localhost:3888),
  `openhuman` (GPL, MCP `openhuman-core mcp`), `remotion` (custom licence; tools `video_project` /
  `render_video`, ask first, `engine/runners/video.py`), `personalive` (card only: Windows/NVIDIA,
  academic licence, cannot be turned on), `openhands`, and `scrapling` got an install hint. Manifests
  gained optional card fields (`install`, `setup_extras`, `notice`, `actions`, `platforms`,
  `card_only`; the first four are cosmetic for trust). An MCP entry with `"capability": NAME` starts
  while that add-on is on. `/open` also allows add-on homepages and card buttons.
- **Novel Writer** template (`agents.TEMPLATES`, written from scratch): idea -> world -> characters ->
  outline -> chapters -> continuity check -> rewrite, all in `novel/`.
- Not done: the Twenty CRM connector (not needed now); no real install/run of any add-on.

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
