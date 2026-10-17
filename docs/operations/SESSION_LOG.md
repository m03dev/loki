# Loki — Session Log

Concise dated records of meaningful work. Newest at the top.

---

## 2026-10-17 - Session 29 (Claude, worktree): automations - LOKI does things by itself

- engine/automations.py: triggers (schedule, folder, email, calendar, webhook, Telegram keyword, job ended, machine
  online, manual) -> conditions -> steps (task job, tool, image, Telegram, file, notify, http, if = LLM yes/no,
  wait, sort_file); one runner thread, JSON store, resumable runs, catch-up, retries with backoff, modes, rate
  limits, kill switch, one owning machine + sync over `POST /peer/automations`; account-touching steps ask unless
  that exact automation is pre-approved (fingerprint).
- Drafting from a sentence (rules offline, model fallback), 8 templates, the agent's `automation` tool (drafts OFF).
- Settings > Automations (app/ui/automations.js/.css): list + switches, Run now / with text, history with logs,
  approvals, step editor, templates. docs/AUTOMATIONS.md.
- tests/test_automations.py (190, in SUITES) incl. the real bridge + webhook and the view in headless Chromium.
  Real machines: ZIVA W35 (PC: morning briefing to Telegram + folder watcher), M26 (Mac).
## 2026-10-17 - Session 29 (Claude, worktree): DeepSeek V4.1 Flash as the main driver, the LOKI MCP API, LOKI Studio

- NVIDIA NIM's free DeepSeek V4.1 Flash leads smart/online routing whenever its key is set (chat, jobs, teams,
  self-improvement), paced under ~40/min (engine/ratelimit.py, shared across processes), 429 -> failover, reasoning shown
  as thinking and never re-sent; /models doctor + the Connections card say so.
- engine/loki_mcp.py: an MCP server over LOKI (status, doctor, settings, jobs, logs, memory, tools, creations, restart)
  and its code (jailed to a dev worktree; tests; ship), risky tools need the owner's approval code. docs/LOKI_MCP.md.
- studio/: LOKI Studio, a separate app (the owner: "like a game engine") that runs from a pinned known-good copy, works
  when LOKI is down (logs, start, rollback), develops LOKI in per-session worktrees on DeepSeek with the MCP API,
  owner-only Ship it. LOKI keeps an icon that opens it. docs/STUDIO.md.
- tests/test_studio.py (182) in SUITES. Real machines: ZIVA W35 (PC), M26 (Mac); Needs Mohamed: the NVIDIA key.

## 2026-10-17 - Session 29 (Claude, worktree): research round 3 - what the best personal-AI apps have

- Research: docs/integrations/research-2026-10-17b.md (35 projects/features ranked, sources).
- Built: message actions (copy/edit/regenerate/branch), rich replies + sandboxed artifacts canvas (HTML/SVG
  preview, Mermaid vendored, charts, cards, citations), chat export/import (ChatGPT, Claude, Open WebUI,
  LibreChat, Markdown), prompt library, compare models + Elo, Home Assistant connector (writes ask), weather/
  news/clock/translate with no key, picture edits (Pillow, rembg add-on, Real-ESRGAN), Settings > Your data
  (inventory, backup/restore, clear). tests/test_research3.py (154) in SUITES. Real machines: ZIVA W35, M26.
## 2026-10-17 - Session 29 (Claude, worktree): LOKI usable by anyone

- Welcome tour (app/ui/onboarding.js): language, a free model (local one-click or OpenRouter/Groq/Gemini), interests,
  3 examples; no dead ends; replaces the auto setup sheet for new people only. engine/usability_api.py (/onboarding,
  /prefs/language, /help).
- "What can LOKI do?" (32 one-click examples, 8 categories, health safety notes) + help center (docs/help/, "?", F1).
- Accessibility (app/ui/a11y.js): text size, high contrast, reduced motion, colour-blind-safe colours, skip link,
  arrow keys, focus kept in dialogs. i18n (app/ui/i18n.js + 8 tables incl. Arabic RTL, opt-in data-i18n); LOKI
  answers in the user's language (LOKI_REPLY_LANGUAGE).
- Installers: tools/make_release.py, packaging/windows/loki.iss, tools/macos/make_dmg.sh, packaging/installer/
  (bootstrap + launcher), .github/workflows/installers.yml (manual); engine/release_update.py = signed release-zip
  updates with the same pre-flight/trial/rollback. docs/INSTALL.md.
- tests/test_usability.py (137 quick, 166 with LOKI_SUITE_SLOW=1) in SUITES. Real machines: ZIVA W35 (PC), M26 (Mac). Needs Mohamed: licence, feed, key.
## 2026-10-17 - Session 29 (Claude, worktree): documents, files and data

- engine/doc_read.py: any file -> Markdown with anchors (PDF pages incl. OCR of scans, DOCX, XLSX, PPTX, CSV, HTML,
  EPUB, EML + attachments, pictures with OCR / vision description, notebooks; LibreOffice/MarkItDown for the rest),
  standard-library OOXML readers, MarkItDown (MIT) logic ported, conversion cache.
- engine/doc_write.py: Word, Excel (formulas + charts), PowerPoint, PDF fill/merge/split/sign-ready, Markdown -> PDF
  (Chromium > reportlab > own writer). python-docx/openpyxl/python-pptx/pypdf in requirements.txt.
- engine/data_sandbox.py: pandas in an audited child process (no network/subprocess/outside writes, time + memory
  limits), auto profile + charts, SQL via DuckDB or SQLite (read-only).
- Tools read_document/write_document/edit_document/pdf_tools/analyze_data/data_sql/documents; read_file reads
  documents. Files view (app/ui/files.js, engine/files_api.py, /files/* routes, drag & drop), tables + charts in the
  chat. Document collections are a source of the one knowledge index; memory.pack cites file#page.
- Add-ons documents, ocr, data-analysis, docling. tests/test_documents.py + tests/test_files_ui.py (Files view screenshot) in SUITES.
  Real machines: ZIVA W35 (PC), M26 (Mac).

## 2026-10-17 - Session 28 (Claude, worktree): LOKI improving itself - own tools, speed watch, self-review, jobs view

- E9 engine/user_tools.py + make_tool: tool.json + tool.py in harness_data/tools, checked (scan + own tests) before
  enabled, loaded without restart, sandboxed process, asks before every call, denied in jobs unless allowed; Settings > Tools.
- E6 engine/speed_watch.py: startup, first paint (boot.js), triage, model calls, tools, verification, requests, jobs;
  Lab sparklines; weekly slowest-step idea. Queued jobs get duration + failure-risk forecasts (job_stats + forecast.py).
- E8 engine/self_review.py: weekly up to 3 "LOKI's idea" proposals waiting for the owner's OK.
- Jobs dashboard (success over time / model / kind, failure reasons, retry on a stronger model) and a daily
  3-job self-test on the PC (engine/selftest.py), checked from files, regressions flagged.
- tests/test_self_systems.py (120) incl. autopilot -> evolve -> improve_loki -> run_job -> check_loki -> ship proof.
  Screenshots via tests/lab_preview/shot.py. Real machines: ZIVA W27 (PC), M19 (Mac).
## 2026-10-17 - Session 28 (Claude, worktree): talk to LOKI from anywhere - Telegram + voice

- EVOLVE E10: engine/channels.py (pairing with a one-time code, owner-only private chat, Ask/Plan via
  phone_link.chat_once with approvals denied, /jobs /make /stop /help, splitting, photos, rate limits, token
  redaction, one machine polls: LOKI_TELEGRAM_POLL auto = the PC) + engine/channel_telegram.py (stdlib Bot API,
  long poll, multipart photos, voice notes). Settings > General: token (secret), poll, mode + pairing card.
- EVOLVE E7: engine/voice_input.py (faster-whisper / whisper.cpp, WAV upload, spoken replies via voice.speak),
  app/ui/voice.js (mic push-to-talk + speaker toggle, data-icon tooltips; webview speech recognition fallback),
  whisper add-on, CSP media-src, Loki.app NSMicrophoneUsageDescription. Discord not built (needs a gateway).
- tests/test_channels.py (fake Telegram on loopback) in SUITES; tests/voice_preview/shot.py (headless Chromium,
  fake mic -> WAV -> text). Real machines: ZIVA W27 (PC), M19 (Mac); Needs Mohamed: a bot from @BotFather.
## 2026-10-17 - Session 28 (Claude, worktree): creative pipelines - local pictures, video, a better Creations

- engine/creative.py: stable-diffusion.cpp + Z-Image Turbo GGUF (PC, 8 GB) and mflux 4-bit (Mac) as the image
  runner's first backend, chosen per machine; installers for local-image / local-video (Wan2GP) from Settings >
  Add-ons or setup_extras.py; Wan2GP headless video (LTX distilled) with Higgsfield fallback; the daily creation.
- Creations: styles, Enhance, aspect, x4, metadata sidecars, prompt on hover, star, filters, make more like this,
  animate this, delete to trash, music/voice tiles. Autopilot duty `creation`; tool make_local_video.
- tests/test_creative.py (93, fakes) in SUITES; all 31 suites pass. Real machines: ZIVA W27 (PC), M19 (Mac).
## 2026-10-17 - Session 28 (Claude, worktree): do agents finish real tasks? A benchmark, and the loop fixed

- tests/tasks/ (31 realistic owner tasks with checkers) + tools/task_bench.py (real loki.run_job per task in a
  throwaway folder, any model, scripted small-model fakes; JSON + markdown table in harness_data/bench/).
- Scripted, same catalog: 15/31 before -> 31/31 after. Found: a team "verified" buggy code (halted tester =
  exit 0 = pass), run_command never offered to any model, team board tools missing on local models, DONE in the
  last line ignored, premature DONE without "create" words, DONE after refused actions, DONE naming missing
  files, BLOCKED guesses, questions in jobs, .py not syntax-checked, "image" calls rejected by the guard, huge
  replies filling context, no job deadline / empty result files. All fixed in the goal loop (HANDOFF).
- Autopilot duty task_bench (nightly, PC on, Mac off), GET /bench, Settings > Lab "Task success" (bench.js).
- tests/test_task_success.py (94) in SUITES; all 33 suites pass. Real models: ZIVA W28.
## 2026-10-17 - Session 28 (Claude, worktree): models & routing - the core system

- engine/provider_health.py: each provider's live state (key rejected, no credit, quota until, rate limited,
  size/context limits, unreachable, model missing), persisted across processes, free background probes.
- engine/routing.py: task-aware order (needs x abilities x health x learned success per task kind) and
  `/models doctor`; loki.active_model_name uses it; background jobs get the best free capable model.
- Local: Ollama version + Bonsai gate + winget/brew guidance, num_ctx made and verified, condenser sized to
  the real window, MLX fallback. Failover: empty choices, timeouts, 429s without long back-off, SDK retries off.
- Settings > Connections: health + fix per card, Explain routing, Re-check; General > Private (local only).
- tests/test_routing_core.py (142) in SUITES. Real machines: ZIVA W28 / M20.
## 2026-10-17 - Session 28 (Claude, worktree): memory & knowledge as one system

- One model (memory_core + memory_kinds): kinds profile/preference/person/project/decision/fact/episode/lesson/skill,
  importance, supersede-with-history on contradiction, dedupe/merge, secrets never stored.
- memory_store: append-only op log, last-writer-wins per id, tombstones + redaction, vectors, compaction, migration.
- memory_search: BM25 + synonyms + optional local Ollama embeddings (hybrid), recency by kind, token budget.
- memory.pack = the ONE path (profile always on, lessons + memories + project passages per request); loki._triage
  calls it once; memory_extract learns what the owner says (review in Settings > Memory: keep/undo).
- memory_sync over the signed peer link (POST /peer/memory), notes file synced; knowledge.ProjectIndex (incremental,
  path:line). Settings > Memory rebuilt. tests/test_memory_core2.py (112, eval 30/30) in SUITES. ZIVA W28 / M20.
## 2026-10-17 - Session 28 (Claude, worktree): tools, connectors, computer use

- Tool health map (tool_health.py, GET /tools/health, Settings > Tools): status + last success/error + one-click
  fix for every tool, MCP server, add-on, connector; dead tools hidden from the model.
- Connectors, read-only by default, writes always ask (policy.ACTION_ALWAYS_ASK): email (IMAP/SMTP, Google
  XOAUTH2), Google loopback sign-in, calendar (Google/CalDAV/iCal), GitHub (gh or token), notes (Obsidian/Notion),
  files on the other machine (POST /peer/files).
- `computer` tool: accessibility tree first (UIA / AXUIElement, ctypes), vision fallback, per-app approval,
  kill switch, log; the computer-use add-on. Chromium (Playwright) behind browse_page with numbered elements.
- tool_teach.py: examples, action synonyms, teaching errors. tests/test_tools_core.py. Real machines: ZIVA W28, M20.

## 2026-10-17 - Session 27 (Claude, worktree): LOKI World as a Godot 4 MMO (game/loki-world)

- game/loki-world: you, islands per device, bridges, flying; cel/ink/pixel look; full MMO HUD; agents as NPCs,
  jobs as quests, failures as monsters (retry on a stronger model), creations as loot; presence multiplayer;
  LokiApi net layer on docs/MMO_API.md with derived and offline fallbacks; export presets (single-threaded Web,
  Windows, macOS, Linux). Godot 4.7.2 built from source here: imports, 107 Godot tests, headless E2E vs the bridge.
- LOKI hooks: world.js "godot" look (falls back to Babylon), app/ui/world_godot/ (no inline script), bridge
  .wasm/.pck + 'wasm-unsafe-eval' for that page only, portal choice. tests/test_godot_world.py (84) in SUITES.
- Real machines: ZIVA W26 (PC: Web + Windows export) and M17 (Mac).

## 2026-10-17 - Session 27 (Claude): every job failed - fixed

- loki.py: qwen3 /no_think, text tool calls salvaged, role-name tools -> conductor, write_file refuses media,
  media verification, specialist output counts, generic DONE nudge, escalation to a free online model.
- cli_agents.py: no NUL bytes, long prompts on stdin. creations: /creations/make (image maker direct).
- forecast.py: TimesFM approved by the owner, installed at start-up. tests/test_job_fixes.py.

## 2026-10-17 - Session 27 (Claude, worktree): LOKI World MMO - engine API, presence, in-app stage 1

- docs/MMO_API.md: the contract for clients (the Godot 4 client the owner chose; the in-app fallback).
- engine/mmo_state.py + /mmo/* routes: quests = jobs, monsters = failed jobs, loot = creations, NPC
  classes/levels, hotbar LOKI actions -> real jobs, retry on a stronger model.
- engine/presence.py + /world/presence, /peer/presence: the owner's avatars and chat between machines.
- app/ui/mmo/mmo_core.js: Play in Settings > LOKI World (WASD, camera, jump, zones over the bridges).
- tests/test_mmo.py (77) in SUITES; tests/mmo_preview/ screenshot harness.
## 2026-10-17 - Session 27 (Claude, worktree): research ports - aider, bigtool, instructor, ReWOO, Reflexion, STORM, Fooocus, ACE-Step, Kokoro

- docs/integrations/research-2026-10-17.md: 36 new open-source projects ranked (licence, stars, what to take,
  decision, sources), incl. MMO notes (Colyseus, snapshot interpolation, bitECS/miniplex).
- New engine modules: repo_map, edit_blocks, tool_select, structured, rewoo, reflexion, deep_research,
  image_prompt (+ data/image_styles.json), music, voice; licences in engine/licenses/.
- New tools: repo_map, apply_edits, find_tools, extract_structured, plan_and_solve, reflect, web_search,
  deep_research, enhance_image_prompt, make_music, speak (one registration block in loki.py).
- tests/test_research_ports.py (141, offline); all 26 suites pass. Live checks: ZIVA W22 / M14.

---
## 2026-10-17 - Session 27 (Claude, worktree): the harvest - code from every documented repo built into LOKI

- docs/integrations/HARVEST.md: one row per documented repo (91 rows; 12 placeholder links left out) with
  licence, what LOKI already had, what was worth taking, and the decision.
- Ported (13): Hermes Agent fuzzy edits + escape drift + arg coercion + cron parser; SWE-agent
  lint-on-edit revert + filemap/search_dir; crawl4ai BM25 focus/citations; Vane search + cited
  research; Firecrawl map; browser-use + page-agent text browser; Agent Reach channels + strict
  public-URL check; Headroom JSON/log compression; SkillSpector agent-skill rules; six
  Apache-2.0 Anthropic skills. New tools: web_search, research_web, browse_page, map_site, reach,
  code_map, search_docs, schedule_task; read_web(query=); autopilot duty `schedules`.
- Licences in engine/licenses/ (one AGPL-3.0 port: engine/site_map.py); THIRD_PARTY.md rows.
- tests/test_harvest.py (offline fakes) in SUITES; all 26 suites pass. Real-internet checks: W22, M14.

## 2026-10-17 - Session 26 (Claude): Babylon.js world, an island per device, Creations

- app/ui/vendor/babylon (Babylon 8.9.1 from source, Apache-2.0), app/ui/world_babylon.js, tools/babylon/.
  World engine default "babylon"; classic/three kept.
- world.js: self island + one island per linked machine (stable slots, fly-to, back home); creations hall.
- engine/creations.py, GET /creations, /creations/<kind>/<file>; app/ui/creations.js, Settings > Creations.
- tests: test_portal (Babylon, islands, self), test_play (Creations).
## 2026-10-17 - Session 26 (Claude, worktree): core upgrade from OpenHuman, OpenHands, Scrapling, MuMuAINovel

- Self-improvement blockers fixed: improve model falls back to smart, check_loki/ship_loki kept for
  local models in a worktree, ship proof + honest evolve settle, hermetic test env, worktree's own
  ship.py, condensed model view, outcomes as memories, nudges after the tool batch.
- New engine modules: memory_core, skill_learning, subagent, condenser, stuck, file_editor,
  web_reader, command_risk, task_tracker; tools memory, run_subagent, read_web, task_tracker,
  insert_lines, undo_edit, sketch_reply. Settings > Memory lists learned memories/skills.
- Novel Writer: MuMuAINovel pipeline prompts in English (skills/novel-writer). GPL code -> LOKI stays private.
- tests/test_core_upgrade.py; all 25 suites pass.

---

## 2026-10-17 - Session 25 (Claude): Pixel Engine + Play + Fox & Berries, Brain map (editable memory), audit

- app/ui/engine/pixel_engine.js, play.html/play.js, games/fox_berries, Settings > Play (sandboxed),
  /games/<name>/<file>, /games/list, tool game_engine_guide. tests/test_play.py (20).
- app/ui/brain.js, Settings > Brain: map + search + read + edit/forget memory facts.
- Ziva on the PC: "Use Main Screen Tab" off (the tab was off-screen on the portrait monitor).

---

## 2026-10-17 - Session 24 (Claude): pixel look back, lag removed, fox, crash restart, LOKI grows itself

- world.js: classic pixel cel-shaded renderer is the default again, denser (2/3 px) with 32 colour
  levels and 4 cel bands; three.js optional and lazy-loaded. Fox + rabbits.
- glass.css: no live backdrop blur over the moving world (the lag); no per-label blur.
- loki_app.py: a crashed engine restarts (5 per 10 min max).
- engine/evolve.py + docs/EVOLVE.md + Settings > Lab + autopilot evolve duty. tests/test_evolve.py.

---

## 2026-10-16 - Session 23 (Claude): options, drawing pad, world fixes, softer GUI, add-ons

- engine/options.py + /options + offerOptions: 3-4 readings of an open request, pick one.
- app/ui/sketch.js + /sketch: draw for LOKI (pressure pen), saved to sketches/, read with view_image.
- world.js: benches, banners and books rebuilt in the right frame; people-sized agents that really
  sit; taller doors; calmer bloom. glass.css: graphite glass, low-saturation accent.
- Add-ons (worktree): CRM, Scrapling, marketing skills, OpenHands, PenEcho/OpenHuman MCP,
  Remotion, PersonaLive card, Novel Writer. tests: test_addons (120), test_workbench (+18).

---

## 2026-10-16 - Session 22 (Claude): three.js world, glass GUI, workbench, Bonsai 2, TimesFM-3, Higgsfield

- Mac hangs: /peer/diagnose + /peer/restart; forecast.memory_tick unloads idle Ollama models
  before the 16 GB Mac swaps. PC updater: GCM non-interactive + credential username.
- app/ui/world_three.js (three.js r186) with the classic renderer as fallback; glass.css.
- engine/workbench.py + app/ui/workbench.js: checkpoints, review/rewind, @file, / palette.
- Bonsai 2 in the model catalog (+ verify_runs); engine/forecast.py (TimesFM-3 or Holt) in
  routing, memory guard, spend outlook and the forecast_series tool; engine/higgsfield.py.
- tests: test_workbench (24), test_models_media (39), test_relay/test_portal/test_updater additions.

---

## 2026-10-15 - LOKI World: a life sim, and cheaper to run

- engine/events.py: /world reads only the new end of the event log (was a full re-parse twice
  per poll); last lines keyed by team + sender; adds since/finished/stage, team stages, stats.
- app/ui/world.js: static scene baked into one buffer, adaptive pixel size, context restore,
  ranked lights; walking routes, station work animations, benches, chat, team banners, inspector
  card, follow camera, HUD; waterfall, pool, flowers, crystals, islets, birds, fireflies.
- tests: test_events (+9), test_portal (+8). Headless Chromium screenshots in
  docs/operations/screens/world-sim*.png. Real-GPU check is ZIVA_TASKS W10.

---

## 2026-10-15 - Session 18 (Ziva Mac): off-network link, S2/S3, a real-model team, one crashed ship

- M3 off-network link: the peer link only dials private addresses, so a public relay is used
  behind a loopback forwarder - new `tools/peer_forward.py` and `docs/operations/OFF_NETWORK.md`,
  tests in `tests/test_peers.py`. Proven live (a signed peer /hello through bore.pub). The
  Tailscale route is blocked on the owner's admin password (its macOS cask installs with sudo).
- S2 local tool calling on Ollama (loki-qwen3.5-9b-agent): `=off` 3/3 first-try calls + file,
  `=auto` 4/4 + file, `=on` failed once with a false DONE (only make_dir, no file) then passed on
  re-run - not reproducible. 0 repaired / 0 rejected in every run. New [claude] request: the task
  loop accepted a false DONE the team/background guard had blocked.
- S3 autopilot: verified while idle - it ran the health duty and the inbox duty (started a team),
  and the System-check "Autopilot (works when idle)" row is green.
- A real-model team (the autopilot's 33f463b9) ran the whole cycle: Architect -> Builder ->
  Tester(failed) -> Builder fix -> recheck; the guard BLOCKED the Tester's repeated DONE with no
  file change, and policy refused a delete_file inside a background job.
- Tests / offline symbiosis: every suite passes under `PYTHONPATH=tests/cloud_stubs` with the
  SAME numbers as the real run, and a new `tests/test_stubs.py` runs one contract against both
  the stubs and the real `openai`/`pydantic`/`mcp`, failing on drift (contract testing is how you
  keep test doubles honest). Added to `tools/ship.py`.
- **CRASH:** the ship of the team report was interrupted by a Ziva / sidecar restart mid-run. It
  left a modified ZIVA_TASKS.md and several suites' temp dirs (`loki-auto-*`, `loki-role-*`,
  `loki-systems-*`, `tmp*`) in the repo root. The temp dirs were removed (they were never
  committed) and the work was re-shipped. No code was lost and no partial commit was made - the
  run died before it reached the commit step.

---

## 2026-10-15 - System check and positive integration tests

- `engine/system_check.py`: 14 checks that prove LOKI's parts work together on this machine,
  each with a plain-English detail and one fix (a Settings tab, or a safe engine action).
  Background thread, short timeouts, nothing paid unless allowed. `/system/check`,
  `/system/fix` in loki_bridge.py. UI: first Settings tab + "Check everything" in the sidebar
  (screenshot docs/operations/screens/system-check.png, headless Chromium with a mocked API).
- Background jobs can run a `selfcheck` job (the built-in agent proves spawn/log/poll/events/
  world with no model); teams have a dry run and `forget`; the image runner has `--plan`.
- tests/test_systems.py: 91 checks across five end-to-end scenarios (goal, job, team, dying
  providers, the check itself), added to tools/ship.py.
- Fixed: ReasoningBank called every finished chat a failure; no specialist reason in the prompt
  when none was ready; /fleet double response; check job blocked by the local-model slot.
- Not run on a real machine yet (ZIVA_TASKS S1).

## 2026-10-15 - Phone app (iOS + Android) and the phone link

- `mobile/`: Expo / React Native app, one codebase for iPhone and Android: Chat (badge says
  Mac / PC / On phone (model)), Connect (scan or paste the pairing code, saved machines),
  Models (download/delete with progress, RAM-based suggestion). Router: paired machines
  first (2.5 s, last good first), else the on-phone model; manual switch.
- On-phone brains behind `LocalBrain`: Cactus (cactus-react-native; Needle for quick
  actions, Qwen3/LFM2/Gemma 3 for chat) and llama.rn (GGUF).
- `engine/phone_link.py`: opt-in phone server (LOKI_PHONE_LINK=1, port 8769), random key per
  phone shown as a QR, stored derived, HMAC-signed requests, replay/age checks, expiry,
  revocation, rate limits, Ask/Plan only, approvals always denied during a phone message.
  Wired into loki_bridge.py (/phones routes, start/stop) and Settings > Machines (Phone card).
- tests/test_phone_link.py (incl. the app's TypeScript protocol run in Node vs Python).
  Not run on a real phone yet (no npm registry access when built).

## 2026-10-14 (session 15) - Repo private, Godot story gone, hermetic suites

- master fast-forwarded onto the session-14 branch (portal, sign-in/QR, agent builder, 3D
  world, Update everything, specialists) - linear history, no merge commit.
- m03dev/loki is **private** now; the Mac needs `gh auth login` (ZIVA M2).
- Removed every "the world is a Godot project" reference (README, docs/WORLD.md,
  docs/STATUS.md, HANDOFF, docs/ARCHITECTURE.md); cancelled ZIVA_TASKS W9 (Godot world
  client); deleted the leftover Godot `addons/`.
- test_loki and test_hardening were failing on the PC only (Ollama + llama-server running,
  and `.env` OPENROUTER_MODEL = deepseek/deepseek-v4.1-flash, a paid model, which makes
  `openrouter` metered and changes smart routing); made hermetic. All 11 suites green.
- `docs/LOKI_BLUEPRINT.pdf` added: improved prompt, research (free hosts, Hermes tool
  harness, Qwen image, OBLITERATUS excluded), plan, and the Ziva Windows/Mac task lists.

## 2026-10-14 (session 14) - Portal, sign-in, Update everything, agent builder, 3D world

- Connections portal (providers_catalog.py, portal_api.py, settings.js): 43 providers with
  switches, Test, model picker; OpenRouter OAuth PKCE (browser + phone code), device flow,
  QR codes (qr.py, no dependencies) and a one-time phone hand-off page (signin.py).
- More hosts: OpenCode Zen, Codestral, Vercel AI Gateway, Pollinations, Nebius, Scaleway,
  Hyperbolic, Novita, Fireworks, Alibaba; local LM Studio, llama.cpp, MLX, vLLM, Jan, Kyojin;
  OpenCode as a CLI agent. GitHub Models is retired (2026-07-30) and left out.
- tool_harness.py: prompted tool calling for any model (Hermes format), learned per provider.
- Update everything (update_all.py, peer /peer/update/apply, app supervisor restarts the
  engine on exit 75, updater health: last_good / pending / skip, rollback).
- Agent builder (agents.py): skills, tools, harness, fallback, home machine, memory, colour,
  draft from a sentence, templates; /agents/launch places agents on a peer.
- Specialists media (yt-dlp), image (Z-Image Turbo / Pollinations), reach (Agent Reach).
- LOKI World in 3D (world.js, plain WebGL) behind the home screen and in Settings.
- ZIVA_TASKS.md: tasks for Ziva Mac / Ziva Windows and an inbox for requests.
- Verified (cloud): tests/test_portal.py 122 checks without the engine packages; QR codes
  decoded by jsQR; UI rendered in headless Chromium with a stub engine, no console errors.
  Not verified here: the other suites (no PyPI access in the workspace) - CI and Ziva W1/M1.

---

## 2026-10-14 (session 13) - The five-layer vision, checked and started

- Saved the owner's vision (docs/VISION.md) and checked every item against the code
  (docs/STATUS.md).
- Event stream + world API for the Godot LOKI World (events.py, /events, /world,
  docs/WORLD.md); structured decisions + Jev fallback; machine capabilities; spending policy.
- Fixed an endless loop in the goal loop (premature DONE).
- Verified: tests/test_events.py (33) incl. decision-before-model; all suites via ship.py.

---

## 2026-10-13 (session 12, part 3) - Agent teams

- `engine/team.py`: roles per goal, staged background jobs on one folder, shared board,
  fix round, stop on a failed stage; tools start_team/team_post/team_read; /teams; UI.
- CI fixed for macOS (launcher dialogs) and machines without the skill libraries; tests
  green on macOS and Windows on GitHub.
- Verified: tests/test_team.py (35); live: POST /teams on a real engine started a real
  architect job, the board recorded it, the team stopped with "needs you" (no model here).

---

## 2026-10-13 (session 12, part 2) - One version on both machines; LOKI ships itself

- Mac: copied the current code into `~/Documents/loki` (it had no git history) and restarted
  LOKI on it; the engine reported the new layout and the first layer. The Mac refused remote
  writes to `.env` and clicks in the LOKI window, so linking and keys need the owner.
- Found: the Mac was set to *listen* instead of linking, and the machines are on different
  networks (192.168.1.71 vs 192.168.0.101).
- `engine/updater.py` (update on start, plain copy -> checkout, never overwrites local work,
  macos-app -> master), `tools/ship.py`, CI on macOS + Windows, peers compare versions and
  `/peer/update`, version shown in the sidebar and in Machines, `improve_loki`/`ship_loki`,
  AGENTS.md, CLAUDE.md, HANDOFF.md (now tracked).
- Verified: 8 suites, 933 checks (new tests/test_updater.py, 42, against real git and a
  stand-in GitHub). Not verified: the first real update on the Mac and the PC.

---

## 2026-10-13 (session 12) - LOKI is its own app; Laya first; work in the chat

**PC linked for real:** the PC (`mo`, RTX 3070 Ti, 192.168.0.101) was moved onto GitHub's
history (its unpushed merge `c25660f` is kept on its local branch
`backup/pc-merge-c25660f`; it uniquely held `jobs.py`, `worker.py` and a Godot workers
dialog, apparently superseded by `workers.py` - not yet reviewed), set up, paired, and
listens on 8768. The Mac still has to pull and paste the link code.

**Done (BUILD_BRIEF 5.1, 5.7, 5.2, section 9):**
- `f4a68c1` engine/ layout; every Godot file removed (project.godot, dock, plugins, .uid,
  vendored MCP addon); data dir no longer found via project.godot; workspace default
  `~/LOKI Projects/Home`; chats in `.loki/` with a one-time copy from `.godot/`.
- `3663edd` Background and Brain tabs removed; running agents show above the message box;
  "Run in background" in the composer.
- `8f77003` Laya as the first layer: warm `laya_server.mjs`, `first_layer.py` triage on every
  request with rules fallback, logged and measured; `tools/setup_laya.py` in setup.
- Docs: new ARCHITECTURE.md; removed the stale blueprint, current-state audit, target
  architecture, implementation plan, dependencies and google-signin docs; fixed paths.

**Verified:** 7 suites, 891 checks; the app UI in headless Chromium (work strip, First layer
line, no console errors); the engine from the new layout over HTTP.
**Not verified:** the real Laya model (no registry access here), the Windows build (CI), the
Mac app after the move.

---

## 2026-10-13 (session 11) - One line of history, and the Mac and PC talking

**Found:** two sessions had worked in parallel. `macos-app` built the standalone app
(conductor, offline-first, credits meter, background jobs, Brain, Windows build,
hardening). `master` fixed routing and verification and added learning. Neither had the
other's work, and the app (`~/Documents/loki` on the Mac) ran without master's fixes.

**Work completed**
- Merged master into the app (`49b996b`): master's routing, verification, paid budget,
  Plan-mode, Godot-path and learning work; the app's job system, launch fix and CRLF
  rules. master's duplicate worker system was dropped.
- Peer link (`peers.py`, `peer_link.py`, `app/ui/machines.js`, `tools/peer_link.py`):
  signed (HMAC) LAN-only link between your Lokis; remote jobs (built-in agent only,
  isolated); verified work flows to the trainer; the Mac adopts the PC's promoted model.
  Settings > Machines; docs/operations/MACHINES.md.
- Windows build lists the new modules; CI runs tests/test_peers.py.

**Tests:** test_loki 486, test_hardening 127, test_integrations 71, test_workers 68,
test_offline_e2e 39, test_peers 58 - all passed. Smoke: a real engine listening, with a
second process linking and sending a real background job.

**Not verified:** the link between the real Mac and PC; GPU training; the Machines tab
in the pywebview window.

**Mac incident (owner's machine):** this session wrongly moved `~/Documents/loki` (the
app's checkout) to the Trash, because a file-listing tool showed it as empty. It was
restored with Put Back. Lesson: never trust one listing tool before moving a folder;
check it in Finder first.

---

## 2026-10-12 (session 10) - Loki becomes a standalone desktop app

**Scope change (owner):** Loki is not a Godot product any more. It ships as its own app;
Godot is an optional adapter. Recorded in the blueprint scope log and AD-10 (supersedes
AD-1).

**Work completed**
- Engine (`loki_bridge.py`): `--godot-exe` and `--project-dir` are optional (workspace
  defaults to `~/Loki`), `--state-dir` moves log/session out of `.godot`, `--ui-dir`
  serves the app UI at `/` with a Host check and a strict CSP; the app's origin may call
  the API; `/health` reports the workspace.
- Harness: a general Build prompt when the workspace is not a Godot project; the Godot
  MCP servers (`godot`, `godot_run`) need `GAME_PROJECT`.
- `app/ui/`: the Loki window - chats, Ask/Plan/Build, model picker, live tool
  activity, permission cards (Allow/Deny), Stop, Settings (Connections + connect a key,
  Tools, Memory, Capabilities). Markdown is escaped before rendering.
- `app/loki_app.py`: starts or attaches to the engine, opens a pywebview window (browser
  fallback), stops the engine on quit, explains setup/port problems in a window.
- `Loki.app` now runs the app (no Godot); `setup.sh` installs pywebview and builds the
  bundle on macOS.

**Tests:** 378 passed, 0 failed offline. Real Chromium run against the real engine: UI
loads, no console errors, modes/models/settings/approval work; engine guards return
403/401/404; the shell starts the engine and stops it on quit.

**Not verified:** pywebview window and a real model reply on the Mac.

---

## 2026-10-12 (session 9) - macOS: the bridge launch fix and Loki.app

**Context.** This was the first session from the cloud workspace, not the Windows checkout.
It worked on the fresh clone `github.com/m03dev/loki`, `master` at `b0c805d` (clean),
on branch `macos-app`. PyPI and GitHub zip downloads are blocked from this workspace, so
the baseline was run with throwaway import stubs for `mcp`/`openai`/`pydantic`. The skill
libraries were fetched with `git clone` into the same vendor folders. Baseline:
**331 passed, 0 failed**.

**Work completed**
- `loki_dock.gd`: `_bridge_interpreters()` now gives macOS/Linux venv paths
  (`bin/python3`) and the Homebrew, python.org and system Python 3 locations. The
  bare-name `pythonw`/`python`/`py` fallback is Windows-only. Before this, the bridge
  never started on a Mac: `create_process` forks before it execs, so a missing name
  still returned a PID.
- `bootstrap.py` / `setup.sh`: there is now a Python 3.11 floor. A too-old interpreter
  (Apple's 3.9) gets a clear message and no venv, instead of a broken venv that later
  launches would prefer.
- `tools/macos/make_loki_app.sh` + `launcher.sh`: build `Loki.app`, which finds Godot
  4.8+, runs setup once, fixes the Finder `PATH`, and opens this checkout in the editor.
  It never installs Godot, and it only replaces its own bundle.
- `docs/operations/MACOS.md`, README pointer.

**Tests:** 351 passed, 0 failed (+20: dock interpreter order, bootstrap floor (behavioural),
bundle build/plist/rebuild/refuse-foreign, launcher allowed/old-version/invalid-path/
bad-version/missing-Godot against fake Godot binaries).

**Not verified:** no run on a real Mac with real Godot 4.8 yet (see MACOS.md, "Not
verified yet").
## 2026-10-13 (master, parallel session B) - Background agents, self-improvement, MCP verification, paid budget

Cloud clone again; the linked computer was the Mac mini, so nothing ran on the 3070 Ti.

**Work completed**
- MCP edits (write_script, create_scene, settings tools...) join the verification set.
- Per-request usage and a budget for metered providers only (`LOKI_PAID_MAX_CALLS`).
- Background agents (`workers.py`, `worker.py`): one process per goal, roles, delegation
  tools, inbox messages, cancel, bridge `/workers*`, a supervisor thread, and a dock
  dialog ("Background agents..."). A worker can never approve a dangerous tool.
- Self-improvement (`experience.py`, `tools/self_improve.py`, `tools/train_lora.py`,
  `tools/setup_training.*`): outcome log, tier-bound learned routing, verified-only
  training data, QLoRA on Qwen3-4B, promote-only-if-better gate, nightly schedule.
- Repo evaluation recorded in INTEGRATION_REGISTRY (Unsloth first, Cua Driver second;
  OpenViking/Paperclip pattern-only; Graphiti rejected for now).

**Tests:** 465 passed, 0 failed (+89). Includes a REAL worker subprocess with a scripted
model, the bridge over real HTTP on a throwaway port, and the evaluator against a fake
Ollama. The suite disables experience recording globally so it never touches a real log.

**Not verified here:** GPU training (no GPU), the GDScript dialog in a running editor
(parses with gdtoolkit only), `--live`.

**Next concrete actions**
1. On the PC: `git pull`, `tools\setup_training.bat`, `self_improve.py status`, `schedule`.
2. Open the dock, start a background agent, confirm the dialog in Godot.
3. Cua Driver as an opt-in MCP server (the brief's computer-use adapter).

---

## 2026-10-13 (master, parallel session A) - Routing and verification: confirmed defects, fixed

Worked from a fresh cloud clone of `master` (`b0c805d`), not the Windows checkout, so
local uncommitted work there was neither seen nor touched. Godot was not available, so
`--live`, real compile checks and scene runs were NOT exercised.

**Baseline before editing:** 331 passed, 0 failed (after fetching the vendored skill
libraries; without them the suite crashes at the GodotPrompter check).

**Confirmed defects (each reproduced before the fix)**
1. **Failover skipped a ready provider.** `_model_request` marked the failing provider
   used-up, then `agent_turn` re-resolved "the spent provider" - by then the NEXT one -
   and marked it too. Repro: openrouter+gemini+groq ready, openrouter quota spent ->
   tried `[openrouter, groq]`, gemini marked used-up unseen. With only two keys the turn
   fell to `local` and reported "Ollama is not running".
2. **Online mode became smart on failover**, so it could reach a local model.
3. **A rejected key / unreachable endpoint ended the turn** in smart mode while other
   providers were ready (401 repro).
4. **Without Godot, `validate_scene` said "INVALID - fix these errors"** (the launch
   error contains `error:`), inviting the model to "fix" valid files. `GODOT_EXE`
   defaulted to one developer's `G:` drive.
5. **`build_scene` and the project.godot editors were not in `MODIFYING`**: a task
   finished with `build_scene` had DONE rejected as "premature", and Plan mode (documented
   "write nothing") offered all four, plus five tools that run the game.
6. **False completion:** DONE was accepted once any file was written; `/chat` never
   checked anything.

**Work completed** (`c665857`, and the verification commit after it)
- Failover marks the provider that actually failed; online stays online; auto-routing
  modes skip a rejected key / unreachable endpoint; a pinned provider still surfaces
  its error; with nothing else configured the ORIGINAL error is shown.
- `ROUTE_TRACE` records every switch (provider, reason, next), key-shaped strings
  masked, served on `/health` as `route`.
- Verification gate: files written per request are recorded; on DONE (task) or at the
  end of a chat turn they are checked (.gd compile, .tscn headless load, .json parse);
  real errors go back to the model (2 rounds task / 1 round chat); the answer ends
  with `Verification: ...` naming what passed, FAILED, was not verified, or has no check.
- `resolve_godot_exe()`: env, PATH, known paths (incl. macOS), else "".

**Tests:** 376 passed, 0 failed (+45). The routing tests drive `agent_turn` with a fake
client; 10 of them fail on the previous code. The verification tests use a temp
WORKSPACE and stub `save_history`/`todo_clear`, so they never touch a real project.

**Not done / known gaps**
- Verification is only as good as the checkers: nothing checks behaviour (that the
  player actually moves); MCP-driven edits (godot-editor-mcp) are not recorded yet.
- `setup.sh`/`setup.bat` clone 2 of the 7 skill sources (the bridge's `ecc_sync` fetches
  the rest on start, so this is cosmetic); `ecc_sync` hides WHY a download failed.
- `tests/test_loki.py` has every line followed by blank lines (an editor/line-ending
  artifact); harmless to Python, worth normalising in a dedicated commit.
- No per-task model budget by default (`LOKI_MAX_TURNS=0`, `GOAL_STEPS=0`).

**Next concrete actions**
1. Record MCP edits in the verification set (map godot-editor-mcp write tools to paths).
2. A default per-task budget for PAID providers only, reported in the answer.
3. Run `--live` on the Windows checkout to confirm the gate with a real Godot.

---

## 2026-10-12 (session 8) - The API Vault (the real catalog)

**Work completed** (`87a4770`)
- `harness/api_vault.py`: a searchable index of APIs (id, name, url, provider,
  categories, auth, docs, source) with `import_apis_guru()`, which normalizes the
  apis.guru catalog - the preferred version's title, `x-origin` url, `x-providerName`,
  `x-apisguru-categories` and its security scheme into a key/oauth hint.
- `tools/build_api_vault.py`: fetches the catalog and folds in Loki's 38 model providers
  (name + base_url only - never a key). Seed committed: **2,097 entries, 363 KiB**,
  searchable offline.
- `api_vault_lookup` tool + `GET /vault` / `POST /vault`. The shipped seed is read-only;
  'add' writes to harness_data/api_vault_extra.json, which search merges over the seed.
- Traps hit and fixed: apis.guru answers **403 to urllib's default User-Agent** (set one),
  and embedded `
` escapes get mangled when a patch is written through a heredoc - use
  `chr(10)` in generated code.
- public-apis / public-api-lists / davemachado are now marked **Superseded**: apis.guru is
  the larger, machine-readable superset and is already in the vault.

**Tests:** 331 passed, 0 failed.

---

## 2026-10-12 (session 7) - Vercel design, and the Herdr session registry

**Work completed**
- **Vercel design** in the dock (`ab3fc7e`): a pure-black canvas, #EDEDED text at full
  contrast, hairline #333 borders, small radii and one #0070F3 focus accent, applied as a
  Theme so every child and dialog inherits it. Verified headlessly (composer #0a0a0a r8,
  hover #1a1a1a, focus border #0070f3, menu #0a0a0a).
- **Agent-session registry** (`67a1b30`): `harness/sessions.py` + the `agent_sessions` tool
  + `/sessions` on the bridge. Adopts Herdr's (herdr.dev) core idea - a shared list of
  agent sessions each working / blocked / idle / done, with a summary that names who is
  stuck - as the blueprint's multi-agent runtime (9) and worker registry (7.1).

**Tests:** 313 passed, 0 failed.

---

## 2026-10-12 (session 6) - The document's systems: providers, project state, repo browser

**Work completed**
- Imported **awesome-free-llm-apis** (github.com/mnfst/awesome-free-llm-apis): 11 new
  OpenAI-compatible providers (aion, cohere, zai, huggingface, kilocode, llm7, modelscope,
  nvidia, ollama-cloud, ovh, siliconflow), documented and tested. Kept out of SMART_ORDER.
- **Resumable project state** (blueprint 7.3): `harness/project_state.py` + the
  `project_state` tool + `/state` on the bridge, over harness_data/project_state.json.
- **Capability registry** (blueprint 3.3, the API Vault seed): `harness/capabilities.py`
  with one shape for every provider/tool/MCP server/skill library, `list_capabilities` and
  `/capabilities`. (Added by a second agent committing to this repo - see below.)
- **Repository browser** (blueprint 5.1): `harness/repo_review.py` + the `review_repository`
  tool - read-only, never executes or installs anything.

**CONCURRENCY NOTE (important)**
- A SECOND writer is committing and pushing to this same repo: commit `8808db7`
  ('Add the capability registry') was made at 18:43 by m03dev and was not made by this
  session. It briefly clobbered a duplicate `capability_registry` this session had added;
  that duplicate was reverted and the other writer's implementation kept. Both landed
  coherently. If two agents are meant to be working this repo, they must pull --rebase
  before every commit and keep to separate files.

**Tests:** 301 passed, 0 failed.

---

## 2026-10-12 (session 5) - Rounded controls and a bubble for the typing box

**Feedback.** "where is the chat bubble when you're typing - everything is beveled and nice
and rounded ... do that". Session 4 only rounded the SENT message; the composer was still a
plain box and nothing else was rounded.

**Work completed**
- `_rounded_copy` / `_round` / `_apply_rounding`: each control's CURRENT stylebox is
  duplicated and only its corners and padding change, so the editor's own colours are kept.
  Deliberately NOT a replacement theme - that is what read as "just darker".
- The typing box (`_input_edit`) is now the bubble: StyleBoxFlat corner radius 12, padding
  12x9, across normal/focus/read_only.
- Every composer and header button, the chat tabs and the three dropdown panels are rounded.
- The overflow menu was reordered chat-first (New chat, Rename, Copy, Memory | Settings,
  ECC, Sync | Inspect, Validate, Run task, Clear attachments); ids are unchanged.

**Tests:** 248 passed, 0 failed. Rounding confirmed headlessly: composer box is StyleBoxFlat
corner=12 pad=12; button hover corner=6; tab corner=6.
**Not visually confirmed** (`view_image` only reads the `ai` project).

---

## 2026-10-12 (session 4) - Keep Ziva's look: bubble + Enter to send (theme reverted)

**Feedback.** The session-3 dark theme read as "just darker" and looked LESS like Ziva; the
dock before it was better. Reverted.

**Work completed**
- Reverted the Ziva-style Theme and the `_draw` canvas from `loki_dock.gd`.
- Your messages now render as a right-aligned BUBBLE (a `[bgcolor]` block with padding);
  Loki's replies stay plain text. A truly rounded bubble needs a message-list container,
  which conflicts with the deliberate single self-scrolling RichTextLabel transcript, so this
  is the closest the transcript can do.
- The composer sends on ENTER and inserts a line on Shift+Enter (was Ctrl+Enter only), the
  way Ziva's composer works. Enter is ignored while the box is empty.
- Placeholder updated to say so.

**Tests:** 248 passed, 0 failed; dock compiles; headless probe builds.
**Not visually confirmed** (`view_image` reads only the `ai` project, which must not be written to).

---

## 2026-10-12 (session 3) - Ziva-style dock theme

**Work completed**
- Restyled the Loki dock toward Ziva's visual language: a near-black canvas drawn in
  `_draw()`, quietly rounded fields, one muted secondary colour and one accent, applied
  through a single `Theme` on the dock root so the tabs, transcript, composer, icon row
  and every dialog inherit it. Palette: bg #0d0d0f, surface #17171a, field #1c1c20,
  hover #26262b, border #2e2e34, text #ececed, muted #8b8b92, accent #6ba1ff.

**Finding (important)**
- Ziva's own GUI is a **compiled CEF web app** (`addons/ziva_agent/bin/*/chrome_*.pak`,
  a 7.8 MB GDExtension DLL, a 122 MB `zivacode.exe`). There is **no readable HTML/CSS/JS**
  - the only loose UI file is `icon.svg`. Loki's dock therefore matches Ziva's LOOK, not
  its markup; a pixel-exact copy is not possible from a compiled application.

**Tests / verification**
- `loki_dock.gd` compiles; `tests/test_loki.py` -> 248 passed, 0 failed; the headless dock
  probe builds (`ready=true tabs=1`); the theme values are read back and confirmed
  (label #ececed, field #1c1c20, accent focus border, hover #26262b, tab #17171a).
- **Not visually confirmed**: `view_image` reads only the `ai` project, which must not be
  written to, so the PrintWindow screenshot could not be inspected. The Loki editor is
  open for a human look.

**Residual gap vs Ziva**
- Ziva's right-aligned rounded user BUBBLES need a message-list container; Loki's
  transcript is one self-scrolling RichTextLabel (a deliberate anti-min-size-blowup
  choice) that cannot render a true padded bubble. Staged, not done.

---

## 2026-10-12 (session 2) - Laya, an upstream contribution, and the input probe

**Work completed**
- Integrated **Laya** (github.com/receptron/laya) as Loki's local-first decision provider:
  `laya.py` (HTTP + a local Node backend via `laya_driver.mjs`, delegating to the real
  `@receptron/laya` package), `decisions.py` (Laya-first routing with Jev fallback and
  recorded disagreements), wired into `approve()` and loop detection; the bridge `/jev`
  and the doctor report it. Installed `@receptron/laya` into `harness_data/laya` (gitignored).
- Prepared an upstream contribution to `receptron/laya` in `contrib/laya/`
  (`0001-systemone-offline-tests.patch` + README): a `Laya.fromParts()` test seam and
  offline tests for `systemOne`'s answer shaping. Verified in the clone: `yarn test`
  13 pass / 1 skip, `yarn typecheck` clean, `yarn lint` no errors.
- Ported the injected-input discipline into Loki: `engine/loki_probe.gd` +
  the `probe_scene` tool run a scene in a real window, feed it timed inputs (action/key/
  mouse/motion), hold each press for at least two PHYSICS frames, and report what the game
  actually received, plus a screenshot.

**Files changed**
- `engine/`: `laya.py`, `laya_driver.mjs`, `decisions.py`, `loki_probe.gd`,
  `loki.py`, `.env.example`; plus `loki_bridge.py`, `tools/loki_doctor.py`,
  `tests/test_loki.py`, `.gitignore`.
- `contrib/laya/0001-systemone-offline-tests.patch`, `contrib/laya/README.md` (new).
- docs: this log, CURRENT_STATE, IMPLEMENTATION_PLAN, INTEGRATION_REGISTRY.

**Tests executed and results**
- `tests/test_loki.py` -> **248 passed, 0 failed** (was 200 at session start).
- Laya driver error paths exercised through Node (missing package, empty stdin).
- `probe_scene` run end-to-end against a throwaway Godot project: 2/2 inputs delivered,
  the game printed `INPUT_SEEN: ui_right`, and the 0 ms key was clamped to 2 physics frames.

**Known issues**
- Laya's model forward pass is not exercised (needs the 1.7 GB ONNX weights on first use).
- The input probe reports delivery and a screenshot; it does not yet assert game-state
  changes (a value probe / servo is the next step).

**Next concrete actions**
1. Assert game state after input (a value probe / servo), not only delivery.
2. Fork and open a PR for the Laya patch if it should be submitted.
3. Resumable `PROJECT_STATE` file.

---

## 2026-10-12 — Audit, command policy, and the durable documentation

**Work completed**
- Located and confirmed the checkout (`C:\Users\macul\Documents\loki`, `master`,
  `github.com/m03dev/loki`), clean tree.
- Audited the request lifecycle, providers, Jev (present), Laya (absent), memory, tools
  and MCP gating, security posture, tests, and docs.
- Ran the baseline suite: **200 offline checks green**.
- **Phase 1 implementation:** added `command_policy()` to `engine/loki.py`
  and wired it into `run_command` so destructive/remote-exec command strings are refused
  before the shell is reached. Pure, testable, overridable via `LOKI_COMMAND_POLICY=0`.
- Added 18 tests (section "command policy (the run_command guard)"). Suite now
  **218 passed, 0 failed**.
- Created the permanent documentation tree under `docs/`: master blueprint, current
  state, target architecture, implementation plan, architecture decisions, security
  baseline, recovery and resume, session log, integration registry.

**Files changed**
- `engine/loki.py` (+ `command_policy`, `_DESTRUCTIVE_SNIPPETS`,
  `_REMOTE_EXEC_TOKENS`; `run_command` guarded).
- `tests/test_loki.py` (+18 checks).
- `docs/LOKI_MASTER_BLUEPRINT.md`, `docs/architecture/CURRENT_STATE.md`,
  `docs/architecture/TARGET_ARCHITECTURE.md`, `docs/roadmap/IMPLEMENTATION_PLAN.md`,
  `docs/integrations/INTEGRATION_REGISTRY.md`,
  `docs/decisions/ARCHITECTURE_DECISIONS.md`, `docs/operations/RECOVERY_AND_RESUME.md`,
  `docs/operations/SESSION_LOG.md`, `docs/security/SECURITY_BASELINE.md`.

**Tests executed and results**
- `harness_data/.venv/Scripts/python.exe tests/test_loki.py` -> 218 passed, 0 failed.
- (Not run this session) `--live` (needs a model + MCP servers).

**Known issues**
- Laya not implemented; symlink-escape path untested; no outbound destination policy;
  `run_command` still a shell string (guard only).

**Blockers**
- None for the work above.

**Next concrete actions**
1. Resumable `PROJECT_STATE` file loaded at session start.
2. DecisionProvider contract + Laya mock.
3. Capability registry prototype over existing tool/MCP schemas.

## 2026-10-17 - Ziva (Windows): PC checks, and a duplicate fix dropped

Ran the [windows] inbox item and W21/W20/W19/W18/W10/W23 on the PC (28 suites green). Verified
Session 27's job fix on the PC: POST /creations/make made a real ~1 MB picture with zimage in
~7 min; /peers/diagnose works over the relay and is redacted. Dropped a duplicate weak-model
"Make it" fix after finding a5deaad already fixed it better; no code shipped. See ZIVA_TASKS.md.

## 2026-10-17 (later) - Ziva (Windows): everything installed, two bugs fixed

Ollama 0.40.5->0.40.6 + Bonsai 2 (correct -Q2_0 tag) loads; kokoro 0.2.2 + soundfile installed and
fixed (ASCII-safe config - Kokoro opened its UTF-8 config with the Windows cp1252 locale and fell
back); TimesFM 3.0.2 installed; ACE-Step 1.5 cloned, uv synced and running with
ACESTEP_OFFLOAD_TO_CPU=true, a fox song made a real 30 s mp3, and engine/music.py fixed (a ready
/v1/audio?path= file was wrapped again -> 403). 32 suites green; tests/test_research_ports 146.

## 2026-10-17 (later) - Ziva (Windows): the new PC-only duties left six suites red on Windows

The new autopilot duties (selftest, task_bench; auto = on for the PC) broke six suites on Windows
while they stayed green on the Mac: test_autopilot, test_core_upgrade, test_self_systems and
test_creative (their idle-pass helpers did not mark the PC duties as run, so a PC duty fired first);
test_task_success (its scripted team task takes about 83 s on this PC, over the 60 s ceiling); and
tests/tasks/base.py pycmd() passed a Windows path as a regex replacement (a C:/Users path has an
invalid backslash escape). Fixed all six - Windows can ship again.
