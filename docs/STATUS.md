# LOKI status against the vision

Every item in docs/VISION.md, checked against the code on 2026-10-14 (not against older
docs). Status words from the vision: **Proposed -> Investigating -> Blocked / Implementing ->
Implemented -> Tested -> Verified** (Verified = shown working on the owner's machines).
"Tested" means an automated test in `tests/` proves it; `tools/ship.py --check` runs them all,
on macOS and Windows in CI. Update this file when a status changes.

## 1. Core: decisions, routing, permissions

| Item | Status | Where / evidence |
| --- | --- | --- |
| Every request decided before the model runs | Tested | `first_layer.py`; tests/test_events.py proves `decision.made` before the model call for chat and tasks |
| Laya as the local first layer, warm, offline | Verified on PC, Tested | `laya.py`, `laya_server.mjs`; PC: model downloaded, self-test passed; Mac: not installed yet |
| Jev as the second opinion | Implemented | used when Laya cannot answer and `TYPESAFE_API_KEY` is set; no key on either machine |
| Structured decision (intent, route, capabilities, missing info, risk, approval, rationale, fallback) | Tested | `first_layer._complete`; logged with every outcome |
| Decision accuracy measured | Tested | `experience.triage_stats` (per source, against what the request needed) |
| Decisions cannot grant permissions | Tested | `policy.py` decides; Laya/Jev can only skip a prompt for a confidently safe call |
| Hardware-aware routing | Implementing | `model_setup.hardware()`, GPU in peer hello; routing does not yet weigh VRAM per task |
| Provider routing with failover | Tested | `SMART_ORDER`, `failover_target`, learned order within cost tiers |
| No paid fallback unless allowed; daily dollar cap | Tested | `LOKI_ALLOW_PAID` (default off), `LOKI_DAILY_USD_LIMIT` (default $1/day), per-request paid call cap |
| Usage ledger (calls, tokens, cost) | Tested | `usage.py`, Settings > Usage; provider account balances are shown as unknown, never invented |
| API Vault as a provider registry with quotas and health | Implementing | `api_vault.py` is an API directory (apis.guru); provider health/quota fields not built yet |
| Secrets out of prompts, logs, events, repo | Tested | `redact_secrets`, events payload filter, `.gitignore` covers `harness_data/` |

## 2. Workforce: agents, teams, machines

| Item | Status | Where / evidence |
| --- | --- | --- |
| Background agents in isolated worktrees | Tested | `workers.py` (local, herdr, cua backends) |
| Teams built per goal (roles chosen for you) | Tested | `team.py`: researcher, architect, builder, tester, reviewer, browser tester; one fix round |
| Agents talk to each other | Tested | team board (`team_post`/`team_read`) -> `agent.message` events |
| Common event format (agent.status ... verification.completed) | Tested | `events.py`, `GET /events` (long poll) |
| Machines advertise real capabilities | Tested | `peer_link.machine_capabilities` in hello (git, gpu.cuda, model.local-inference, godot.test, blender.inspect, ...) |
| Mac <-> PC link (signed, LAN) | Implemented, Blocked | `peers.py`; machines are on different networks (192.168.1.x / 192.168.0.x): same network or Tailscale needed |
| Same version on every machine | Tested | `updater.py`, `tools/ship.py`, CI on macOS + Windows |
| Leases, retries, recovery if a peer disappears | Proposed | jobs survive restarts locally; cross-machine leases not built |
| Steam P2P transport | Proposed | not evaluated; the transport is replaceable (peers.py) |
| School PC / laptop as conditional workers | Proposed | any machine running LOKI can be linked; nothing machine-specific built |

## 3. World: agents as characters

| Item | Status | Where / evidence |
| --- | --- | --- |
| Real-state API for the world | Tested | `GET /world`, `GET /events`, docs/WORLD.md |
| 3D world in the app (plain WebGL) | Implemented | `app/ui/world.js`; WebView2/WKWebView check is ZIVA W6/M6 |
| Characters only act on real events | Tested (engine side) | `events.world` builds agents from jobs/teams/events only |
| Nordic LOKI identity (L-geometry logo, navy + cyan/emerald) | Proposed | not in the app yet |

## 4. Bridge: integrations

| Item | Status | Where / evidence |
| --- | --- | --- |
| Godot (optional game capability) | Implemented | `godot_tools.py` (validate, run, probe scenes) when a game project is open |
| Claude Code / Codex subscriptions | Verified on PC | `cli_agents.py`; PC reports both ready |
| MCP servers | Implemented | `mcp_servers.json` (time, fetch, sequential, Godot servers off by default) |
| Browser Use, cua, Crawl4AI, Firecrawl, Scrapling, Perplexity, Vane, Hindsight, Hermes | Implemented | capability manifests, off until enabled; not run for real on either machine |
| Unreal, Blender, Maya, Substance, Unity adapters | Proposed | only detected (`machine_capabilities`), no adapters |
| One common creative-tool interface | Proposed | |
| Obsidian vault | Implemented | `tools/export_obsidian.py`; Settings > Brain maps it (read-only) with LOKI's memory, which you can correct or forget there |

## 5. Evolution: improving safely

| Item | Status | Where / evidence |
| --- | --- | --- |
| Outcome log and verified examples | Tested | `experience.py` |
| Fine-tune on the PC's GPU, promote only if better | Implemented | `tools/self_improve.py`, `train_lora.py`; no training run yet (needs examples) |
| LOKI changes its own code in isolated worktrees, ships only when tests pass | Tested | `improve_loki`, `ship_loki`, `tools/ship.py` (refuses failing tests and conflicts) |
| Protected areas (policy, evaluator, secrets) need stricter review | Proposed | not enforced yet: ship.py gates on tests only |
| Evaluation suite (routing, fallback, injection, approvals, recovery) | Implementing | 10 offline suites (~1000 checks); no live model evaluations yet |
| Dashboard | Implementing | work strip, Settings > Usage / Machines; no single dashboard |

## Session 14 additions (2026-10-14)

| Item | Status | Where / evidence |
| --- | --- | --- |
| Connections portal (switch, Test, model picker, default, disconnect) | Tested | `providers_catalog.py`, `portal_api.py`, `settings.js`; tests/test_portal.py |
| OpenRouter sign-in (PKCE, browser + phone code), device flow, QR, phone hand-off | Tested (offline) | `signin.py`, `qr.py` (decoded by jsQR); not yet on a real phone (ZIVA W3/W4) |
| Prompted tool harness (any model, any tool) | Tested | `tool_harness.py`, `_model_request`; real MLX/llama.cpp run is ZIVA W8/M4 |
| Update everything + rollback of a version that does not start | Tested | `update_all.py`, `updater.py` health, `loki_app.py` supervisor; two-machine run is ZIVA W7 |
| Agent builder (skills, tools, harness, fallback, home machine, draft) | Tested | `agents.py`, `/agents/launch`; peer placement live run pending |
| media (yt-dlp), image (Z-Image Turbo / Pollinations), reach (Agent Reach) | Implemented | runners + manifests; real runs are ZIVA W5 |
| LOKI World 3D in the app (WebGL) | Implemented | `world.js`; rendered in headless Chromium; WebView2/WKWebView check ZIVA W6/M6 |
| Native (non-web) world client | Not planned | the world stays in the app (WebGL) |

## Session 17 additions (2026-10-15, on master)

| Item | Status | Where / evidence |
| --- | --- | --- |
| Local model comes back after a transient failure (not dropped for the session) | Tested | `loki.revive_local`, `_FAILED_AT`; tests/test_tool_guard.py |
| Tool-call guard: repair bad JSON / near-miss names / type slips, precise error otherwise | Tested | `engine/tool_guard.py`, wired in `agent_turn`; tests/test_tool_guard.py (38 checks) |
| Constrained decoding (json_schema) for local servers, with fallback | Tested | `loki._use_constrained`/`_constrained_request`; tests/test_tool_guard.py |
| Agent factory picks the best model per team role (measured), cheaper tier wins ties | Tested | `experience.role_stats`/`best_for_role`, `team.py`; tests/test_role_routing.py |
| Autopilot: when idle, health fixes + [loki] inbox + weekly learned report | Tested | `engine/autopilot.py`, `GET /autopilot`, System check row; tests/test_autopilot.py (19) |
| Cloud suites run for real against the fake Ollama | Tested | `tests/cloud_stubs/openai` speaks HTTP; all 16 suites green in the cloud |
| S2/S3: a real-Ollama run and an idle-autopilot run on the machines | Proposed | ZIVA_TASKS Requests S2/S3 |

## Session 16 additions (2026-10-15)

| Item | Status | Where / evidence |
| --- | --- | --- |
| One-click System check (parts proven together, each red row with its fix) | Tested | `system_check.py`, Settings > System check; tests/test_systems.py; live run is ZIVA S1 |
| End-to-end integration scenarios (goal, job, team, failover, check) | Tested | tests/test_systems.py (real modules, fakes only for model servers / network / hardware) |

## Research the vision asks for (not code)

Repository catalog (DeepSeek Harness, OpenViking, Graphiti, OpenHub, October Bus, AutoHelix,
EvoSkill, AgentArena, OpenScreen, ...), free inference comparison, hosting and publishing
terms, creative-tool bridge options, Steam P2P vs LAN vs Tailscale: **Proposed**. None of it
has been researched with current sources yet; treat the names in VISION.md as candidates.

## Fixed while checking

- The goal loop could spin forever when a model kept answering "DONE" without changing any
  file; it now stops after 3 tries with BLOCKED (tests/test_events.py).
- Automatic routing could pick a paid provider on its own (for example a paid OpenRouter
  model); it no longer does unless `LOKI_ALLOW_PAID=1`.
