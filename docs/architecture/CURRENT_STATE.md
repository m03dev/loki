# Loki — Current State (audit)

Audit of the confirmed checkout `C:\Users\macul\Documents\loki` (branch `master`, remote
`github.com/m03dev/loki`). This document is an honest picture of what the code **is**, not
what it should become. Verified by reading the source and running the suite.

## 1. Checkout and working tree

- Absolute path: `C:\Users\macul\Documents\loki`.
- Remote: `origin https://github.com/m03dev/loki.git`.
- Branch: `master`, clean working tree at the start of this session.
- Recent history: `8054c9e` (answer a question in one turn, English only) is HEAD.
- License: MIT.
- User data (`harness_data/`) is git-ignored and never shipped in the addon.

## 2. Language, framework, entry points

- **Language / runtime**: Python 3.11+ (agent + bridge) and GDScript (Godot 4 editor UI).
- **Host**: Godot 4.8. Loki is a self-contained editor addon; a consuming project needs
  only `addons/loki`.
- **Entry points**
  - `addons/loki/plugin.gd` — the EditorPlugin: the Loki viewport screen and the bundled
    Godot MCP bridge host.
  - `addons/loki/chat/plugin.gd` — the chat dock plugin (independent of the screen plugin;
    they talk through node groups).
  - `addons/loki/bootstrap.py` — zero-setup launcher (creates the venv, starts the bridge).
  - `addons/loki/loki_bridge.py` — local loopback HTTP bridge (port 8766, Bearer token).
  - `addons/loki/harness/loki.py` — the agent: providers, tool loop, prompts (~3,100 lines).

## 3. Request lifecycle (as implemented)

1. The dock sends the message to the bridge over loopback HTTP with a Bearer token.
2. `loki_bridge.py` authenticates, then routes: normal **Send → `POST /chat`** (one turn,
   `run_agent`); only the explicit **"Run task (no limit)"** item → `POST /task`
   (`pursue_goal`, the bounded autonomous loop). This split fixed the "stuck" symptom.
3. `run_agent` builds context (`composed_memory()` = memory facts + profile → system
   prompt, trimmed history), offers the mode-restricted tool schemas, and runs `agent_turn`.
4. `agent_turn` loops: model request → tool calls → results, with retry/backoff,
   failover, loop detection, and cancellation checks.
5. A streaming progress callback pushes events back to the dock while it works.

Modes (Ask / Plan / Build) are enforced in the bridge via `LOKI_MODE` / `set_mode()`, which
decides which tools are offered. Plan cannot write/run/delete.

## 4. Providers and routing

- One common provider model (`ModelConfig`); `smart` mode orders free cloud tiers, then
  subscription coding agents, then local Ollama, and fails over automatically.
- `_is_limit_error()` distinguishes an out-of-allowance refusal (429/402/413, quota, rate
  limit) from a real bug; `failover_target()` marks a provider used up and retries the
  **same turn** on the next provider, so no work is lost.
- Coding CLIs (Claude Code, Codex) are providers (`cli-agent://…`), using an existing
  subscription rather than an API key.
- Go-to model on the user's account: DeepSeek V4.1-Flash via OpenRouter.

## 5. Decision layer (Jev) — status: implemented, optional

- `addons/loki/harness/jev.py` is a stdlib-only client for TypeSafe System One "typed
  decisions". **It exists** and is consumed in two places:
  - **Risk gate** in `approve()`: Jev may judge a dangerous tool call safe enough to skip
    the prompt; it can never force an action, so the human path stays authoritative.
  - **Loop detection** in `agent_turn`: every N tool calls Jev answers "is the agent
    repeating without progress?" and the agent gets a stop-and-reassess nudge.
- Every Jev call is guarded and non-fatal; with no key, or on any HTTP/network error, Loki
  keeps its own heuristic. It is optionally exposed as an MCP server gated by an env key.

## 6. Decision layer (Laya) — status: implemented, local-first

- **Laya is integrated** (`harness/laya.py` + `harness/decisions.py`). It is the Jev-compatible
  open-source System-1 decision model (github.com/receptron/laya). Two backends: an HTTP
  `system_one` endpoint, or the local Node driver `laya_driver.mjs`, which delegates to the
  real `@receptron/laya` package (installed under `harness_data/laya`, never inside the addon).
  Routing prefers Laya and falls back to Jev; a disagreement is recorded and the safer answer
  wins. `approve()` and loop detection route through this layer.
- **Not exercised offline**: the model's forward pass needs the 1.7 GB ONNX weights
  (downloaded on first use), so only the plumbing and the error paths are covered.

## 7. Memory and persistence

- Conversations are stored in `<workspace>/.godot/loki_conversations.json`
  (`{active, profile, conversations}`); the old single-history file is migrated on first
  run. Titles derive from the first user message.
- Long-term memory is `harness_data/memory.md` plus a profile, composed into the system
  prompt; `save_memory` triggers a prompt refresh so facts apply immediately.
- No project index / RAG yet; context is file tools + tree listing, not embeddings.

## 8. Tools and MCP

- Local tools: file read/write/edit/search/delete, scene builders, validation, script
  compile check, scene run + screenshot, an injected-input runtime probe (`probe_scene`,
  which drives the running game and reports what it received), Godot API search,
  project-setting/autoload/input helpers, skills browser, memory.
- **Offered-to-model set** (`MODEL_TOOL_NAMES`) deliberately excludes `run_command`,
  `open_godot`, and `run_godot` (dangerous / misused by small models). They remain
  callable behind the approval gate, and the `system` tool category is off by default.
- `run_command` executes via `subprocess.run(..., shell=True, cwd=WORKSPACE)`.
- MCP: an external `uvx godot-editor-mcp` server talks to the vendored Godot MCP bridge
  (`addons/loki/godot_mcp/`, 32 domain handlers, ~167 commands) over `ws://127.0.0.1:9080`.
  `refresh_mcp_tools()` re-reads the tool list once per request; capability domains are
  unlocked on demand via `godot_enable_toolset`. Gating is one pure function
  (`_server_skip_reason`) with `enabled`, `requires_env`, and `requires_cmd` rules.
- Vendored skills: 519 skills across six libraries plus the Ponytail coding standard.

## 9. Security posture (what exists)

- **Filesystem sandbox**: every path goes through `resolve_in_workspace()`, which rejects
  anything escaping `WORKSPACE` (traversal contained; tested).
- **Dangerous tools** (`run_command`, `open_godot`, `move_file`, `delete_file`) route
  through `approve()`; in the editor the bridge replaces it with the dock's approval UI;
  `LOKI_AUTO_APPROVE=1` runs unattended.
- **Command policy** (new this session): `command_policy()` refuses known-destructive
  shapes before `run_command` reaches the shell (see SECURITY_BASELINE.md).
- **Secrets**: keys live in `harness_data/.env` (git-ignored); the Connections view never
  returns credential values.

## 10. Tests and documentation

- `tests/test_loki.py` — structural/offline plus a `--live` mode (MCP + a real model
  turn). At the start of this session: **200 offline checks green**. After the command
  policy work: **218 green**.
- Docs before this session: `README.md`, `HANDOFF.md`, `docs/providers.md`,
  `docs/dependencies.md`, `docs/godot-plugins.md`, `docs/google-signin.md`, plus
  `addons/loki/README.md` and `keys/README.md`. The formal `docs/` tree in section 19 of
  the blueprint did **not** exist and is created now.

## 11. Known gaps / incomplete features

- No Laya implementation (section 6).
- `run_command` still uses a shell string; the command policy is a guard, not structured
  argument execution.
- No project index / semantic retrieval; no resumable project-state file yet.
- No repository browser or API Vault implementation yet.
- No distributed-worker layer yet.
- Scene edits are not yet routed through Godot's undo manager.
- No CI. `godot_omni` MCP backend disabled (port conflict with the `godot_ai`/`godot_omni`
  addons terminates the editor; keep them disabled).