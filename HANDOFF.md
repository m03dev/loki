# Loki — handoff

An AI game-dev agent that lives **inside the Godot 4 editor**. You describe a change in
the dock; Loki plans, edits scenes and scripts, runs Godot to check its work, and iterates.

Repo: https://github.com/m03dev/loki

## Run the tests first

```bash
harness_data/.venv/Scripts/python.exe tests/test_loki.py          # structural, offline
harness_data/.venv/Scripts/python.exe tests/test_loki.py --live   # + MCP and a real model turn
```

43 structural checks pass offline. `--live` adds MCP connection and a real agent turn.
Run these before and after any change to `addons/loki/harness/loki.py`.

## Layout — the addon is self-contained

A consuming Godot project needs **only `addons/loki`**. Nothing else. This is a hard
requirement and it drives every layout decision below.

```
addons/loki/
  plugin.gd              EditorPlugin: dock + hosts the vendored MCP bridge
  loki_dock.gd           the chat dock (tabs, history, progress, approvals)
  loki_bridge.py         local HTTP bridge (port 8766, Bearer token)
  bootstrap.py           zero-setup launcher: makes the venv, starts the bridge
  harness/               THE AGENT CODE (142 KB, ships inside the addon)
    loki.py              the agent: providers, tool loop, prompts
    godot_tools.py       Godot project tools (build_scene, validate_scene, ...)
    cli_agents.py        Claude Code / Codex as subscription providers
    ecc_sync.py          fetches the ECC agent/skill library
    mcp_servers.json     which MCP servers to start, and which tools to offer
  godot_mcp/             the Godot editor MCP bridge, vendored (MIT, (c) 2026 Johnny D)

<project>/harness_data/  USER DATA - never shipped, never inside the addon
  .env                   API keys
  memory.md  plan.md  loki_settings.json
  workspace/             the folder file tools may touch
  vendor/                downloaded ECC + ponytail libraries
  .venv/                 Python environment (created by bootstrap.py)
```

`loki.py` keeps `ROOT` (its own code dir) for imports, and resolves all user data via
`DATA_DIR` by walking up to `project.godot`. Override with `LOKI_DATA`.
`mcp_servers.json` ships with the code; `memory.md`, `plan.md`, `.env`, `loki_settings.json`
and the venv are user data. **Do not move user data back inside the addon** — it would ship
the user's API keys and chat memory with the addon.

## Modes and providers

- `smart` — best available: free cloud tiers first, then the subscription agents, then a
  local Ollama model as a last resort.
- `online` — **no Ollama and no GPU.** Same order but never a local model. If nothing is
  configured it names a provider to set up instead of silently using a local model.
- Explicit: `gb`, `groq`, `openrouter`, `mistral`, `sambanova`, `cloudflare`, `together`,
  `nous`, `unorouter`, `deepseek`, `cerebras`, `vireonix`, `claude-code`, `codex`, `local*`.

Running out of allowance is **not** a failure. `_is_limit_error()` recognises an
out-of-allowance refusal (429/402/413, quota, rate limit, resource_exhausted, too large,
exceeded, credit, billing) as distinct from a real bug; `failover_target()` marks the
provider used-up and the turn **retries the same turn** on the next provider, so no work is
lost. Verified: gemini -> groq -> openrouter -> vireonix -> local, task still completed.

Provider notes (verified Oct 2026):
- GitHub Models is **retired** — the `github` provider was removed.
- Cerebras needs a **verified payment method**, so it is not free.
- Gemini's free tier **may train on your content**.
- OpenRouter free = 50 requests/day; a **negative balance breaks even `:free` models**.
- DeepSeek is `deepseek-flash` (V4.1-Flash) and is **paid** — $0.15/1M in, $0.60/1M out
  off-peak. Thinking mode is on by default there.
- `vireonix` needs **no key, no account and no card**, but requests go to a third party.

### Claude Code and Codex as providers
`cli-agent://<name>` base URLs mean "run the installed CLI in the project and return its
answer". No API key - they use the subscription allowance you already pay, and they are real
agents with their own file/edit/shell tools. Claude Code also gets Loki's MCP servers.
Install and **sign in** (`claude` then `/login`; `codex login`) or they report "not signed
in". Override the binary with `LOKI_CLAUDE_CODE_EXE` / `LOKI_CODEX_EXE`.

## The Godot MCP bridge

Vendored at `addons/loki/godot_mcp/` and hosted by Loki's own `EditorPlugin`
(`_start_mcp_bridge()` in `plugin.gd`): it registers the `EditorDebuggerPlugin` via
`add_debugger_plugin`, creates the `MCPBridge` node and calls `start()` on
`ws://127.0.0.1:9080` (`GODOT_MCP_BRIDGE_URL` overrides). Upstream's own entry point and
status dock are deliberately **not** used - their purpose is to be enabled as a separate
plugin, which is what we are avoiding.

The MCP **server** runs via `uvx godot-editor-mcp` (see `harness/mcp_servers.json`). The
editor dials out to it, so launch order does not matter, but the server must be running for
`bridge_connected: true`.

**Tool exposure.** A Godot MCP server grows its tool list at runtime - the editor bridge
connecting and any toolset the model enables both add tools. `connect_mcp` snapshots the list
once, so `refresh_mcp_tools()` re-reads it and offers anything new. Measured: 40 -> 55 tools.
It runs **once per request**, never between turns, because a tool list that changes
mid-conversation invalidates prompt caching and can push a request past a provider's limit.
Both call sites are guarded - the refresh is an optimisation and a dead server must never
take a turn down. The total is capped by `LOKI_DYNAMIC_TOOLS_MAX` (60).

Toolsets are gated for token cost: only an allow-list is offered at startup. Enable more with
`godot_enable_toolset` (argument is `category`, not `toolset`); the newly unlocked tools are
then offered on the next request. `scene_edit` and others require **Godot 4.4+ and a
connected bridge**.

The vendored server ships handlers for animation, audio, particles, physics, navigation,
tilemap, tileset, shaders, visual_shader, theme/UI, resources, export, profiling, debugger,
import_asset, runtime_inspect/session, scene_3d, mesh_library, input_recording, batch and
project_scaffold. **Most of these are not yet surfaced as first-class Loki tools.**

## Traps that have cost real time — read before patching

1. **Never patch `loki.py` with a long multi-line find/replace.** Multi-line anchors get
   corrupted in transit, and `\n` inside a patch script can arrive as a real newline (it once
   wrote a literal line break into `"\n".join(...)` and broke the file). Instead:
   - locate lines by **short single-line predicates** (`l.strip() == "..."`, `"foo(" in l`);
   - build a backslash-n as `chr(92) + "n"`, and avoid literal backslashes in patch text;
   - **compile in memory before writing** — `compile(new, path, "exec")` and refuse to write
     on SyntaxError, so a broken edit can never reach disk.
   - On failure, `git checkout -- <file>` back to the last good commit rather than repairing
     by hand.
2. **A failed assert in a patch script means NOTHING was applied** if the write happens at
   the end. Do not read a later "compiles OK" as success.
3. **Never put backticks in a double-quoted bash string** - they execute. A commit message
   containing a CLI command actually ran it and started an OAuth server on port 1455. Write
   commit messages to a file and use `git commit -F file`.
4. **Never broad-kill Godot processes.** The argless `Godot_..._console.exe` hosts the running
   editor; killing it closes the user's editor. Kill only by an exact PID whose command line
   you have read. Loki's own editor runs as
   `--path C:/Users/macul/Documents/loki --editor`.
5. `--check-only` on a single `.gd` reports bogus errors for global `class_name`s defined in
   sibling files. Whole-project load is the real test.
6. The `time` MCP server has intermittently failed to start (`Connection closed`). Harmless.

## Known state

- `tests/test_loki.py` — 43 offline checks green; `--live` adds MCP + a real agent turn.
- The bridge starts via `bootstrap.py` and answers `/health` with
  `{"ok": true, "service": "loki", ...}`. Auth is `Authorization: Bearer <token>`.
- Play-session/runtime inspection additionally needs `mcp_runtime_probe.gd` registered as an
  autoload **in the game project**. That is a project modification, so it is opt-in and not
  done by default.

## Next steps, in value order

1. **Surface the vendored Godot domains as real tools** — signals, resources (.tres),
   animation, tilemap, shader, theme, export, profiling. The capability is already inside the
   addon; only exposure is missing. This is the single biggest gap.
2. **Adopt the safety patterns** comparable agents use: route scene edits through Godot's
   **undo manager**, lock file operations to `res://`, and never eval raw source — restrict
   script execution to calling a method on an existing `@tool` script or runtime node.
3. **Composite tools** (one `nodes` tool with add/remove/set_property) to cut schema tokens;
   every schema is paid for on every request.
4. A **`help` tool** for tiered tool descriptions instead of full schemas.
5. **Runtime inspection** while the game runs.
