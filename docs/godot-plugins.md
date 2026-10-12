# The Godot AI ecosystem, and what Loki takes from it

Loki bundles no other editor addon - a consuming project needs only `addons/loki`.
Instead it absorbs the *portable* parts of the ecosystem through the two mechanisms
it already has:

1. **The vendored knowledge library** (`ecc_sync.py` -> `harness_data/vendor/`),
   loaded on demand by `load_ecc_skill` / `load_ecc_agent`. Any repo that ships
   `SKILL.md` folders (the "Agent Skills" format) or `agents/*.md` drops straight
   in - the loader searches **recursively**, so nested layouts work too.
2. **MCP servers** (`harness/mcp_servers.json`), each gated so it costs no tool
   schemas until it can actually run.

## Vendored knowledge (519 skills, 88 agents)

| Library | Repo | Contents |
|---|---|---|
| **ECC** | `affaan-m/ECC` | 76 agents, 311 skills (general engineering) |
| **GodotPrompter** | `jame581/GodotPrompter` | 9 agents, 56 Godot-4 skills (GDScript & C#, 4.3-4.6) |
| **awesome-gamedev** | `gamedev-skills/awesome-gamedev-agent-skills` | 75 game-dev skills (Godot + 8 other engines, genres, design) |
| **gamedev-plugin** | `fcsouza/agent-skills` | 3 agents, 25 skills (design / engineering / narrative) |
| **agentic-gamedev** | `abagames/agentic-gamedev-skills` | 37 skills (agentic gamedev workflows, repair loops) |
| **Superpowers** | `obra/superpowers` | 15 core agentic-workflow skills |
| **ponytail** | `DietrichGebert/ponytail` | the "lazy senior dev" coding standard (prompt block) |

```bash
harness_data/.venv/Scripts/python.exe addons/loki/harness/ecc_sync.py --status
```

`list_ecc_skills()` returns names grouped per library, capped at
`LOKI_SKILL_LIST_CAP` (120) per library with a `(+N more)` tail - pass `query` to
filter by name substring when the library is this large.

## MCP servers, and the gate

Every entry may carry, enforced by `_server_skip_reason()`:

- `"enabled": false` - never start (an opt-in server).
- `"requires_env": "NAME"` - start only when that env var is set (an API key).
- `"requires_cmd": "npx"` - start only when that command is on PATH.

Token discipline is the reason: a Godot MCP server can expose 150+ schemas, and
**every schema is paid for on every request**. A server that cannot work yet
contributes nothing. Loki also exports `GODOT_PATH` from its own `GODOT_EXE` (when
it is a real file) so engine-driving servers find the binary.

| Server | Command | Gate | What it adds |
|---|---|---|---|
| **godot** | `uvx godot-editor-mcp` | on | the vendored editor bridge (8 startup tools + on-demand domains) |
| **godot_run** | `npx @coding-solo/godot-mcp` | `npx` | launch editor, run/stop the game, capture debug output |
| **godot_omni** | `uvx` (Benjiarml wheel) | off | 1,820 operations / 59 domains, reflection, GDScript eval |
| **jev** | `uvx jev-mcp-server` | `TYPESAFE_API_KEY` | typed decision tools (choice/score/noul) |
| **git** | `uvx mcp-server-git` | off | git status/diff/log/show/branches - review & revert changes |
| **sequential** | `uvx mcp-sequential-thinking` | off | structured planning journal |
| **time**, **fetch** | `uvx mcp-server-*` | on | clock and web fetch |

### Turning on an opt-in server

- **`git`**: set `"enabled": true`. It defaults to the working directory; add
  `--repository <path>` to `args` to point it at a specific repo.
- **`godot_omni`**: download `godot-mcp-v5.0.39.zip`, extract `addons/godot_ai` +
  `addons/godot_omni`, enable both plugins, then set `"enabled": true`.
- **`sequential`**: set `"enabled": true`.

## The Godot MCP gateway (addons/godot_ai + addons/godot_omni) - SOLVED

This addon pair is the single richest Godot integration: **100 tools** (1,820 engine
operations, GDScript eval, reflection, UI automation). Getting it working took three
discoveries:

1. **Extract the addon completely.** The release zip ships ~212 files; a partial
   extraction (29 files) leaves `utils/server_lifecycle.gd` and friends missing, so every
   preload fails and the plugin can never start its server. The editor still opens, so the
   breakage is silent.
2. **Never spawn `godot-ai` yourself.** The editor plugin *starts or adopts* the local
   python server and connects over WebSocket. If Loki also spawns one, the two fight over
   ports 8000/9500 and **the editor is killed ~45s after launch** (reproduced).
3. **Connect over HTTP with the capability token.** The editor's server requires
   `Authorization: Bearer <token>` - a per-launch 64-char hex capability it publishes to
   `${GODOT_AI_CAPABILITY_DIR}/http-8000.json` (`%LOCALAPPDATA%\godot-ai\capabilities` on
   Windows). Loki reads that record fresh at connect time:

       "godot_omni": {
         "url": "http://127.0.0.1:8000/mcp",
         "transport": "streamable-http",
         "auth_bearer_json": {"path": "${GODOT_AI_CAPABILITY_DIR}/http-8000.json", "key": "http"}
       }

   SSE is not exposed (404); streamable-http on `/mcp` is. A missing record makes the
   server skip cleanly with "start the Godot editor" rather than crash.

### Other Godot MCP servers (all opt-in: `LOKI_MCP_ENABLE=<name>`)
Probed from the npm registry; only these speak clean stdio JSON-RPC:

| name | tools | what it adds |
| --- | --- | --- |
| `godot_omni` | 100 | the full editor gateway (above) |
| `godot_runtime` | 39 | launch/run/attach a project, read debug output |
| `godot_enhanced` | 26 | runtime, **screenshots**, script/scene validation |
| `godot_scene` | 21 | scene/node/editor read + edit |
| `better_godot` | 17 | project/scene/node/script/editor/config (Node >= 24) |

`@gikit/godot-mcp` and `vberai-godot-mcp` print banners to stdout and cannot be used as
stdio servers. `godot-forge-mcp` and `godot-ai-builder` do not exist on npm or PyPI.

## Making it all interoperate

- **Every server's full tool surface is offered** - no per-server caps. With the
  Godot gateway on that was ~157 MCP tools; with it off (the default, see below)
  it is ~57 MCP tools alongside Loki's ~40 built-in tools.
  `LOKI_DYNAMIC_TOOLS_MAX` (default 400) bounds dynamic additions only.
- **`${ENV}` templating** in `mcp_servers.json` args/env, e.g. the git server is
  started with `--repository ${LOKI_WORKSPACE}`, so it always points at the
  active project.
- **git needs no path from the model**: Loki fills `repo_path` with the workspace
  on any `git_*` call, so `git_status` / `git_diff` / `git_log` just work.
- **`GET /connections`** includes `mcp_servers`: each server as `connected` (with
  its tool count) or `off` (with the reason it was skipped).
- **Turn opt-in servers on locally without editing the shipped JSON**: put
  `LOKI_MCP_ENABLE=godot_omni,git,sequential` in `harness_data/.env`
  (`LOKI_MCP_DISABLE=a,b` forces servers off).

## Considered, not integrated

- **`HubDev-AI/godot-ai-builder`** - repository is gone (404 on HTML and API).
- **`godot-forge-mcp`** (Tann2019) - the README advertises `npx -y godot-forge-mcp`,
  but the package is **404 on both npm and PyPI**, so it cannot be installed.
- **`josephsmithberger/godot_ai_assistant`** - a Godot editor addon (74 tools), not
  a skill library; nothing is portable without installing its plugin. Its ideas
  (offline docs search, runtime probe install/drain, `classdb_query`) already
  overlap Loki's `godot_search`, `godot_api`, `capture_scene` and runtime probe.
- **Other editor MCPs** (`TomasLucasUTN/godot-mcp-bridge` 231 tools,
  `yurineko73/Godot-MCP-Native` 155, `Demiurgic-io/godot-mcp` 149, dlight "Godot
  AI" 120+) - all require their own Godot addon and are largely covered by
  `godot` + `godot_omni`. Listed here so the trade-off is on record.
