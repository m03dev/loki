# Loki — handoff

An AI game-dev agent that lives **inside the Godot 4 editor**. You describe a change in
the dock; Loki plans, edits scenes and scripts, runs Godot to check its work, and iterates.

Repo: https://github.com/m03dev/loki

## Run the tests first

```bash
harness_data/.venv/Scripts/python.exe tests/test_loki.py          # structural, offline
harness_data/.venv/Scripts/python.exe tests/test_loki.py --live   # + MCP and a real model turn
```

125 structural checks pass offline. `--live` adds MCP connection, the capability-domain
unlock path, and a real agent turn.
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
    ecc_sync.py          fetches the agent/skill libraries (see docs/godot-plugins.md)
    jev.py               optional Jev typed decisions (risk gate + loop detection)
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
lost. A provider that cannot run at all - an installed but **unsigned** coding CLI
(CliAgentError) - is now skipped the same way instead of ending the turn, and a spent
*quota* is no longer retried through the whole backoff (only a genuine transient rate
limit is). Verified: gemini -> groq -> openrouter -> vireonix -> claude-code -> codex ->
local, task still completed.

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

**Capability domains are surfaced on demand.** `godot_list_toolsets` lists every domain with a
description and its `min_godot`; `godot_enable_toolset` (argument is `category`, not
`toolset`) switches one on and `godot_disable_toolset` switches it off. The system prompt
tells the agent to do this before hand-rolling Godot work, so animation, tilemap, shader,
resources (.tres), physics, audio, particles, navigation, theme/UI, profiling, export, batch
and the rest are reachable - and none of them cost context until used. Proven live: the suite
enables `scripts` and the very next model turn calls `godot_scripts_list`.

An enable answers with its full JSON (every tool and schema). `call_tool` summarises it to one
line (`_toolset_summary`) because those schemas are already offered - echoing the blob is pure
context cost on every later request.

To make domains **always on** at startup, list them under the godot server's `toolsets` key in
`harness/mcp_servers.json` (default `[]`); their whole surface is then offered, bounded by
`max_tools`. It is empty by default on purpose: every schema is paid for on every request
(free tiers such as Groq at ~7k input tokens/min choke), so the startup allow-list stays at 8
tools. Domains needing the editor bridge (`scene_edit`, `scene_3d`, `tilemap`, `input_map`)
answer `BRIDGE_DISCONNECTED` and add nothing until the editor is connected.

The vendored server ships handlers for animation, audio, particles, physics, navigation,
tilemap, tileset, shaders, visual_shader, theme/UI, resources, export, profiling, debugger,
import_asset, runtime_inspect/session, scene_3d, mesh_library, input_recording, batch and
project_scaffold. The server groups them into **26 capability domains** (toolset names) but
starts with only `core` + `inspection` enabled - 15 Godot tools reach the model out of the
box, out of roughly 150 behind the domains.

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
   `--path <loki> --editor`.
5. `--check-only` on a single `.gd` reports bogus errors for global `class_name`s defined in
   sibling files. Whole-project load is the real test.
6. The `time` MCP server has intermittently failed to start (`Connection closed`). Harmless.

## Known state

- `tests/test_loki.py` - 125 offline + 10 live checks green (`--live`).
- **Setup is seamless and needs no keys.** `setup.bat` / `setup.sh` create
  `harness_data/.venv`, install the deps, fetch the skill libraries and run
  `tools/loki_doctor.py`. `LOKI_MODEL` defaults to `smart`, which with no keys at all
  resolves to `vireonix` (needs no key, account or card), so the agent runs out of the box.
- `tools/loki_doctor.py` lists every provider, whether it is usable, and the link to get a key.
  `VIREONIX_API_KEY` must stay unset/empty-inert: `_load_env_file` treats an empty value as
  "set", which would DISABLE the zero-key provider (`.env.example` keeps it commented out).
- **One bridge looks like FOUR python processes on Windows - that is normal.** The
  `harness_data/.venv` interpreter is a redirector: it starts the base interpreter as a CHILD,
  so a single launch shows as launcher + real for `bootstrap.py`, and again for
  `loki_bridge.py`. Do not "fix" this by killing processes. To count BRIDGES, check the
  listener, not the process list: `netstat -ano | findstr 8766` - exactly one PID is LISTENING.
- A stale bridge from a pre-`15f298e` build can linger and hold 8766. Tell: its `--loki-root`
  points at `<repo>/harness` instead of `<repo>/addons/loki/harness`. Kill those exact PIDs and
  let the dock relaunch one.
- Kept as hardening against a genuine simultaneous launch (two docks after a plugin re-entry, or
  a dock-vs-manual race): `bootstrap.py` takes an atomic `O_CREAT|O_EXCL` lock at
  `.godot/loki_bridge.launch` (60s TTL) and stands down if another launch holds it, and the dock
  has a 5s spawn cooldown.
- The bridge starts via `bootstrap.py` and answers `/health` with
  `{"ok": true, "service": "loki", ...}`. Auth is `Authorization: Bearer <token>`.
- Play-session/runtime inspection additionally needs `mcp_runtime_probe.gd` registered as an
  autoload **in the game project**. That is a project modification, so it is opt-in and not
  done by default.

## Jev — typed decisions in the loop (optional)

Loki makes hundreds of small judgements between edits: is this tool call safe, are we
stuck. Jev (TypeSafe System One, https://thejevai.com) answers those as typed
`choice` / `score` / `noul` decisions in a few hundred ms, so the loop thresholds a
number instead of parsing prose. It is **optional**: with no key every call is inert
and Loki behaves exactly as before.

Two routes, matching how Jev is meant to be adopted:

- **Direct (hard-wired) — `addons/loki/harness/jev.py`.** A stdlib-only client used
  where a decision is non-negotiable:
  - **Risk gate** in `approve()`: before the y/N prompt, Jev judges a dangerous tool
    call. `destructive < LOKI_JEV_RISK` (default 0.15) *and* the action choice is
    `allow` => run it silently; otherwise it still asks. The human path stays
    **authoritative** — Jev can only skip a prompt, never force an action. The bridge
    overrides `approve()` with the dock's approval UI, so this covers both modes.
  - **Loop detection** in `agent_turn`: a rolling window of recent actions; every
    `LOKI_JEV_LOOP_EVERY` (6) tool calls Jev answers "is the agent repeating without
    progress?" (p >= 0.7) and the agent gets a stop-and-reassess nudge. This catches
    the same *approach* retried with different args, which the exact-signature check
    already in the loop cannot see.
  - Every call is guarded and non-fatal: no key, a 401/422/429/529, or a dropped
    connection all return None/{} and the caller keeps its heuristic.
- **MCP (`mcp_servers.json` -> `"jev"`).** The `jev-mcp-server` (uvx) exposes Jev's
  decision primitives as tools the agent can call on its own initiative. Gated by a
  new `requires_env` key so it only starts (and only costs tool-schema tokens) once
  `TYPESAFE_API_KEY` is set.

Turn it on: put `TYPESAFE_API_KEY=` (a hosted `jv_live_` key or an official
`console.typesafe.ai` key; the endpoint follows the key) in `harness_data/.env`.
`LOKI_JEV=0` force-disables it. `GET /jev` on the bridge reports status and
`tools/loki_doctor.py` shows a Jev line.

## Vendored Godot knowledge + optional MCP servers

`ecc_sync.py` fetches several libraries into `harness_data/vendor/` and `loki.py`
loads them all through one loader (`LIBRARIES`). The loader searches **recursively**
for `SKILL.md` and `agents/*.md`, so every repo layout works (root `skills/`,
`plugins/<x>/skills`, `.agents/skills`). Total: **482 skills, 88 agents**.

- **ECC** (general): 76 agents, 311 skills.
- **GodotPrompter** (`jame581/GodotPrompter`): 9 agents, 56 Godot-4 skills.
- **awesome-gamedev** (`gamedev-skills/awesome-gamedev-agent-skills`): 75 game-dev skills.
- **gamedev-plugin** (`fcsouza/agent-skills`): 3 agents, 25 design/eng/narrative skills.
- **agentic-gamedev** (`abagames/agentic-gamedev-skills`): 37 skills.
- **Superpowers** (`obra/superpowers`): 15 core workflow skills.
- **ponytail**: the coding standard (rendered as a prompt block).

`list_ecc_skills(query)` groups names per library and caps the dump at
`LOKI_SKILL_LIST_CAP` (120) with a `(+N more)` tail.

`load_ecc_skill` / `load_ecc_agent` search every library; `list_ecc_*` name each
library it found; `/ecc` returns flat lists plus a per-library `libraries` map.
`docs/godot-plugins.md` has the full ecosystem survey and what was/wasn't taken.

MCP servers now offer their FULL tool surface (no allow-lists or caps; ~157
MCP tools reach the model). Gating is three generic rules, enforced by the pure
function
`_server_skip_reason()`: `enabled:false`, `requires_env` (an API key), and
`requires_cmd` (e.g. `npx`/`uvx` on PATH). `LOKI_MCP_ENABLE=a,b` turns opt-in
servers on locally without editing the shipped JSON (`LOKI_MCP_DISABLE` forces
off); args/env support `${ENV}` templating (git uses `--repository
${LOKI_WORKSPACE}`, and Loki auto-fills git's `repo_path` from the workspace);
`GET /connections` reports each server's state. Registered additions: **`godot_run`**
(Coding-Solo `@coding-solo/godot-mcp` - run/stop/debug the game, gated by `npx`),
**`godot_omni`** (the 1,820-op bebabinlarsson gateway - registered but OFF until
its own addons are installed), **`jev`** (gated by `TYPESAFE_API_KEY`), and two
opt-in servers **`git`** (`uvx mcp-server-git`) and **`sequential`**
(`uvx mcp-sequential-thinking`). Loki exports `GODOT_PATH` from a real `GODOT_EXE`
so engine-driving servers find the binary. The full survey is in
`docs/godot-plugins.md`.

**A real bug this caught:** an earlier patch inserted the `requires_env` block
BETWEEN the `enabled` print and its `continue`, so a disabled server still started
and added 20 tool schemas to every request. Gating is now one pure function with
unit tests. After editing `mcp_servers.json`, read the `[mcp]` lines in
`.godot/loki_bridge.log` - every server should say `connected` or `skipped: <why>`.

## Release signing

`keys/loki_public.pem` is the trusted RSA-2048 public key (fingerprint
`SHA256:k7mnIAntVdK6HNIKTPLtOuN6Ps5kfLTzSPkmJ5oqCNs`). The matching **private** key
is never in the repo - point `LOKI_SIGNING_KEY` at it to sign. `tools/loki_sign.py`
signs (`sign`), verifies against the bundled key (`verify` / `verify-all`, or
`--pubkey` for another key) and prints the pinnable fingerprint. See `keys/README.md`.

**WARNING - do not enable `addons/godot_ai` + `addons/godot_omni` alongside the
`godot_omni` MCP backend.** They fight over ports 8000/9500 and the Loki editor is
terminated ~45s after launch (reproduced). Both addons are on disk but disabled,
and `godot_omni` is off; the editor is stable without them.

## Next steps, in value order

1. ~~**Surface the vendored Godot domains as real tools**~~ - **done.** The domains were
   already reachable (`godot_list_toolsets` / `godot_enable_toolset`); what was missing was
   the agent knowing to use them. The prompt now says so, `call_tool` compacts the enable
   response, `mcp_servers.json` gained a `toolsets` knob, and the live suite proves the unlock
   path. Next in this area: promote the most-used domains into the *startup* surface for users
   with allowance to spare, and give `godot_list_toolsets` a compact one-line-per-domain
   rendering so the model can choose a domain without a large call.
2. **Adopt the safety patterns** comparable agents use: route scene edits through Godot's
   **undo manager**, lock file operations to `res://`, and never eval raw source — restrict
   script execution to calling a method on an existing `@tool` script or runtime node.
3. **Composite tools** (one `nodes` tool with add/remove/set_property) to cut schema tokens;
   every schema is paid for on every request.
4. A **`help` tool** for tiered tool descriptions instead of full schemas.
5. **Runtime inspection** while the game runs.
