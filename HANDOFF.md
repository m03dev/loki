# Loki — handoff notes

A **local-first coding agent for Godot**, presented Ziva-style: a chat dock beside
the Scene dock with conversation tabs, saved history, memory, and a library of
specialist agents/skills (ECC).

## Layout

| Path | What it is |
| --- | --- |
| `addons/loki/chat/plugin.gd` | Adds the dock (`EditorDock`, left-upper slot) |
| `addons/loki/loki_dock.gd` | The dock UI: tabs, chat, ECC picker, approvals, settings entry |
| `addons/loki/loki_settings.gd` | Settings dialog: Agent / Account / Profile / Memory tabs |
| `addons/loki/loki_bridge.py` | Loopback HTTP bridge (`127.0.0.1:8766`) between dock and agent |
| `addons/loki/bootstrap.py` | **Zero-setup launcher** — creates the venv, installs deps, runs the bridge |
| `addons/loki/run_bridge.bat` | Manual bridge launcher (optional; the dock does this itself) |
| `harness/loki.py` | The agent: tool loop, model providers, conversations, memory |
| `harness/ecc_sync.py` | Fetches the ECC library + Ponytail from GitHub (stdlib only) |
| `harness/vendor/` | Fetched library (gitignored, ~7 MB) |
| `cloud/` | Optional hosted mode (`auth_server.py`) |

## First run (nothing to install)

1. Open the project in **Godot 4.3+** (developed against 4.8-dev7).
2. Make sure both plugins are enabled (`addons/loki/plugin.cfg`, `addons/loki/chat/plugin.cfg`).
3. That is it. The dock runs `bootstrap.py`, which creates `harness/.venv`,
   installs `harness/requirements.txt`, then starts the bridge. The ECC library
   is fetched from GitHub on the first bridge start.
   - Only prerequisite: **Python 3.11+**. Internet is needed the first time.
   - Watch `project/.godot/loki_bridge.log` if something looks stuck.

## Configuration (never committed)

- `harness/.env` — `LOKI_MODEL` and provider keys (see `harness/.env.example`).
- `cloud/.env` — hosted-mode secrets.
- `user://loki_profile.cfg`, `harness/memory.md` — profile and lasting facts.
- `<project>/.godot/loki_conversations.json` — chats; `.godot/loki_session.json` — cloud session.

## Providers / models

`openrouter` (default) — `poolside/laguna-s-2.1:free` is the tested free
tool-calling model; occasional 429s on the shared pool are expected.
Also wired: `local-reasoning` (Ollama), `omniroute` (local gateway), `cloud`
(sign in through the bridge; the key stays server-side).

## ECC

71 agents and 311 skills from <https://github.com/affaan-m/ECC>. The model reaches
them through `list_ecc_agents` / `load_ecc_agent` / `list_ecc_skills` /
`load_ecc_skill` / `sync_ecc`. The dock exposes a searchable picker
(**⋮ → Agents and skills (ECC)**) and **Sync ECC library from GitHub**. Only the
selected document is loaded (capped at ~12k chars), so the context stays small.

## Which models actually work (tested 2026-10-11)

Every run below drove the same task through the real `/task` path.

| Model | Endpoint | Result |
| --- | --- | --- |
| `local` = **qwen3:8b** | Ollama | **PASS, 36s, 6 tool calls, and it self-corrects a failed tool call** |
| `openrouter` = poolside/laguna-s-2.1:free | OpenRouter | PASS, 20s, 5 tool calls - but rate-limited (429) and returns empty replies under load |
| `local-reasoning` = qwen3.5:9b | Ollama | BROKEN for agents: replies "DONE" without calling any tool |
| `local-coder` = qwen2.5-coder:7b | Ollama | BROKEN for agents: prints the tool call as JSON *text*; no `tool_calls` |
| `omniroute` | OmniRoute | BROKEN: HTTP 503, model in cooldown |

- **Use `qwen3:8b` offline.** `ollama pull qwen3:8b`. It is the only local model
  verified to emit real structured `tool_calls` through Ollama.
- `qwen2.5-coder:7b` does **not** support tools in Ollama's template - never wire it
  to the agent loop. It answers in prose and the run stalls.
- The free OpenRouter pool works but is not reliable for long tasks; a paid key or a
  bigger local model is needed for sustained work.
- Loki's guard is doing its job: a model that claims completion without writing files
  is rejected ("nothing was written yet - not accepting DONE").

## Reliability behaviour (harness)

- **Transient model failures are retried, not fatal.** HTTP 408/409/425/429/5xx and dropped
  connections retry with exponential backoff (1.5s, 3, 6, 12 - capped at 20s). Tunable with
  `LOKI_MODEL_RETRIES`, `LOKI_RETRY_BASE_S`, `LOKI_RETRY_MAX_S`. Verified live: 4 attempts,
  then a clear error instead of an instant failure.
- **Text-form tool calls are recovered.** Some models print
  `{"name": "tool", "arguments": {...}}` into the message body instead of emitting structured
  `tool_calls`. Those calls are now parsed and executed, so such a model can still drive the
  agent. Only names matching a real tool are accepted, so ordinary JSON in a reply is ignored.
- **Model limits that are NOT fixable in the harness:**
  - `qwen2.5-coder:7b` - Ollama's template gives it no tools at all; it invents a "DONE" it never did.
  - `qwen3.5:9b` - replies "DONE" without calling any tool.
  - Both were re-tested after the recovery fix and still fail. Use `qwen3:8b`.

## What is still missing (found by testing, 2026-10-11)

Driving a real "build a third-person shooter template" task exposed the two things that
stop Loki from being a useful game-dev product yet. Both are TOOL problems, not model problems:

1. **No Godot API reference.** The agent invents APIs that do not exist - e.g. it wrote
   `InputMap.map_action(...)` (real Godot 4 is `InputMap.add_action(name)` then
   `InputMap.action_add_event(name, event)`). It then loops editing the same line because it
   cannot know the correct call. **Needed: a docs/reference lookup tool** (search Godot
   class docs and return the real signature) so the agent checks instead of guessing.
2. **No scene-graph builder** - FIXED, see `build_scene` below.

### build_scene (new tool)
`build_scene(filename, nodes, light, camera)` writes AND verifies a Godot 4 `.tscn` from a
node tree: any node type, attached scripts, collision shapes, primitive meshes, positions,
and `instance` for instancing another scene. Verified: it generated a valid player scene
(CharacterBody3D + CollisionShape3D + MeshInstance3D + SpringArm3D + Camera3D + script) and
a main scene that instances it - both reported "valid - Godot loaded it cleanly".
`build_3d_scene` stays for quick primitive-only scenes.

### Other harness fixes from the same testing pass
- **Argument aliases**: models say `path` when the schema says `filename`; calls were rejected
  outright ("unexpected keyword argument 'path'"). Synonyms are now mapped before dispatch.
- **Lenient JSON**: models emit Python literals (`[{'type':'box'}]`). `json.loads` rejected
  them; `ast.literal_eval` fallback accepts single quotes / trailing commas.
- **Repeat breaker**: after 3 identical failing calls the agent is told to change approach, so
  it stops thrashing on a call that cannot succeed.
- **Retry/backoff** on 429/5xx/timeout (already documented above).

## The toolset (27 tools)

Everything the agent needs for real Godot work, all reachable by the model:

- **Knowledge** - `godot_api` (real class/method/property/enum signatures from the engine's
  own `--dump-extension-api`), `godot_search`. This exists so the model **stops inventing APIs**
  (it previously wrote `InputMap.map_action()`, which does not exist). The dump is generated
  automatically on first bridge start; it is gitignored.
- **Scenes** - `build_scene` (any node type, scripts, collision shapes, meshes, instancing,
  verified), `build_3d_scene` (primitive scenes), `read_scene` (show the node tree),
  `validate_scene`, `open_in_editor`, `play_scene`.
- **Scripts** - `write_file`, `append_file`, `edit_file`, `read_file`, `check_script`.
- **Project** - `add_input_action` (writes a real input action into project.godot, so scripts
  can use `Input.is_action_pressed` with no runtime InputMap hack), `set_project_setting`,
  `add_autoload`.
- **Workspace** - `list_files`, `list_tree`, `search_files`, `make_dir`, `move_file`, `delete_file`.
- **Plan/memory** - `todo_add`, `todo_list`, `todo_done`, `save_memory`.
- **Skills** - `list_ecc_agents`, `load_ecc_agent`, `list_ecc_skills`, `load_ecc_skill`, `sync_ecc`.

## Gotchas worth knowing

- **Never launch the bridge through a shell chain.** `cmd /c start "Title" /min x.bat`
  is mangled by cmd on Windows (`The system cannot find the file Bridge\.`) and
  silently does nothing. The dock spawns the interpreter directly — keep it that way.
- The bridge is **single-instance**: it refuses to start if `8766` is busy and prints
  a clear message. Kill the stale listener before testing.
- A leftover `.godot/loki_bridge.token` is handled: repeated connection failures
  force a relaunch (see `_start_bridge(force)`), so a stale token cannot wedge the dock.
- Headless UI check without opening the editor: `godot --headless --script res://tools/loki_probe.gd`.
- Icons come from Godot's built-in **`EditorIcons`** set via `_editor_icon()`; it
  returns null outside a real editor session so headless runs never break.

## Known gaps / next steps

- The ECC picker inserts a directive; the agent then calls the load tool. A direct
  "run as this agent" sub-loop is not implemented yet.
- Long-running game-dev tasks have not been soaked/monitored end-to-end.
- `harness/loki.py` is CRLF; the `.gd` files are LF. Keep that in mind when patching.

## Secrets / personal data

- No credentials are tracked: `.env`, session files and `harness/loki_settings.json`
  are all gitignored; `harness/vendor/` is gitignored too.
- The repository commit identity is set to a GitHub noreply address.
