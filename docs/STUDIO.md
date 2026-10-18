# LOKI Studio

The owner: "i want a tab in loki for loki development that runs on deepseek4.1 ... it works on the
development of loki", then: "this mode might need to exist outside of loki like a game engine".

So LOKI Studio is **its own app** - like a game editor next to the game. You tell it what to build
or fix in LOKI; it works on LOKI's code in its own git worktree with DeepSeek V4.1 Flash, shows you
every step and the diff, and ships only when you press **Ship it**. It keeps working when LOKI is
broken, not running, or in the middle of an update.

## One client: Studio is a tab of LOKI's window (owner, 2026-10-17)

"loki studio should not be another window but the same client, just another tab; utilize the top tab like godot engine
to switch between modes." The mode tabs **LOKI** (chat/home) / **Studio** / **Godot** / **World** / **Forge** sit IN the
window's title bar (`app/ui/modebar.js`, a 38 px title strip), Ctrl+1..5 (Cmd on the Mac). Each mode keeps its state when
you switch away (panes are built once and only hidden).
- **macOS**: the native traffic lights stay; `app/loki_app.py` makes the title bar transparent and title-less over a
  full-size content view (pyobjc, on pywebview's `before_show`; every call guarded - a failure leaves the normal title
  bar) and tells the page (`#...&titlebar=mac`), so the strip starts after the traffic lights (78 px).
- **Windows**: pywebview's frameless window (WinForms, `FormBorderStyle None`) cannot be resized at its edges, so the
  **native frame stays** and LOKI's strip sits flush directly under it - same tabs, no floating pill.
- Empty parts of the strip drag the window (`.pywebview-drag-region`); the tabs are not drag regions; a double-click on the
  strip maximises/restores (`WindowApi.toggle_maximize`, the window's only js_api). `LOKI_TITLEBAR=native` (Settings >
  General) leaves the macOS title bar alone (next start).
- Every menu/popover is placed by `app/ui/place.js` (`LokiPlace.place/at`): flips above/below to the side with room,
  stays inside the window, caps its height and scrolls inside; dialogs are sized with vh/% and clamp() under the strip.
  `tests/test_ui_fit.py` opens them at 900x600, 960x1040 and 1920x1080.

- **Studio**: the first time the tab opens, LOKI asks its engine (`POST /studio/embed`, engine/studio_api.py) to start
  Studio's server in the background (`studio_app.py --headless`, no window; once - a second click while it comes up does
  not start another) and frames Studio's own loopback page with its token. Studio keeps its own process and server, so it
  still works when LOKI is broken, and the Godot plugin still links to it. Studio's CSP allows only a loopback page to
  frame it; LOKI's window allows framing only loopback (`frame-src`). `Loki Studio.cmd` / `loki_studio.sh` still open the
  standalone window for those who want it. The sidebar's LOKI Studio button now switches to the tab.
- **Godot** (`engine/godot_web.py`): the official Godot 4 **web editor** (MIT), downloaded on first use from the
  `4.7.2-stable` release (LOKI World is a 4.7 project) into `<data>/addons/godot-web-editor`, SHA-512 checked against the release's SHA512-SUMS
  (nothing kept on a mismatch; zip members that are folders, absolute, `..` or odd types are refused), never committed.
  Served at `/godot-editor/app/` with `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy:
  require-corp` (SharedArrayBuffer). Projects: `~/LOKI Projects/<name>` and `game/loki-world`. **Which way files flow**
  (said in the tab): the project folder -> "Project to the web editor" (a zip) -> the editor's Import; back: the editor's
  Project > Tools > Download Project Source -> "Bring back from Downloads" (writes only inside the project folder).
  LOKI's own window is not cross-origin isolated, so the tab says so and offers "Web editor in its own window" (the page
  there IS isolated) and **Open in the Godot app** (the installed editor, `--editor --path`, with the LOKI Studio plugin
  installed first).
- **World**: LOKI World's panel (the same one as Settings > LOKI World) shown in the tab. **Forge**: forge.js's sheet.

## Where is this going? (studio/studio_destination.py)

The owner: "when loki is in someone else's hands the studio creates a new repo and a new app starts getting developed ...
you should have the option to choose where it's going." The card at the top of Studio's rail shows the choice; a click
changes it. The first time, a non-owner is asked before the first session.

| Choice | What Studio does | Ship it |
| --- | --- | --- |
| **Improve LOKI itself** | works on `m03dev/loki` master, as before | `tools/ship.py` |
| **My own LOKI** | `gh repo fork m03dev/loki`; origin = `<you>/loki`, upstream = `m03dev/loki` (without gh: says how by hand) | `tools/ship.py` (pushes origin = the fork) |
| **A new app from LOKI** | `~/LOKI Projects/<name>`: a small skeleton (`app/main.py`, `tests/`, `tools/ship.py --check`, README, AGENTS.md, NOTICE.md, LOKI's AGPL LICENSE) + a **copy** of LOKI's `engine/` used as a library from `app/` (a copy, not a package: LOKI's engine is not packaged, and a copy keeps the app working when LOKI changes; NOTICE.md says where it came from); first commit on `main`; `gh repo create <name> --private\|--public --source ... --push` when gh is signed in | the tests (`--check`), commit, merge into the app's main, push its origin |
| **Just this computer** | `git clone` of LOKI into `~/LOKI Projects/<name>`, origin removed | the tests, commit, merge; nothing leaves the computer |

Who is asking = the account signed in to `gh`. Not `m03dev`: the default is "My own LOKI", "Improve LOKI itself" is
refused, and `guard()` refuses every Ship it whose target is `m03dev/loki` unless the owner ships LOKI itself. Every
git/gh call is an argv list through one runner (no shell strings; `gh.exe`/`git.exe` on Windows via `shutil.which`).
Stored in `harness_data/studio/destination.json`; each session records its own in `session.json` (`destination`,
`base_repo` - its worktree is made from the app's repo for an app). Sessions from before keep "Improve LOKI itself".
API: `GET /api/destination`, `POST /api/destination {kind, name?, visibility?, confirm: true}`.

## LOKI's settings, from Studio

The gear on the LOKI card opens **LOKI's settings** in Studio's side panel (`studio_control.settings_overview/change`,
`GET|POST /api/loki/settings`), through LOKI's own bridge routes - list + toggle + edit, each change after a confirm:
models/providers (on/off `/providers/enable`, model `/providers/model`), General settings (`/settings/general`; secrets
and keys are never shown or changed - Settings > Connections does that), capabilities on/off (`/capabilities/enable`),
and the evolve list: add a task line to `docs/EVOLVE.md`'s Roadmap (`- [ ] E<n> ...`, an uncommitted edit in the LOKI
folder until the next ship) or an idea on this machine (`/evolve/idea`). When LOKI is down it says so; the roadmap is
still read from the file.

404 check (2026-10-17): every `/api/...` path in studio.js, the Godot plugin and studio_mcp.py is a route of
studio_server.py, and every bridge path loki_mcp.py / studio_control.py calls exists in engine/loki_bridge.py or
portal_api.py (`tests/test_studio_destination.py` checks studio.js's). The owner's "error 404 http not found" came from
the model call (a wrong NVIDIA model name -> engine/nim_models.py), not from Studio's routes.

## Start it

| Machine | How |
| --- | --- |
| Windows | double-click **`Loki Studio.cmd`** in the LOKI folder |
| Mac | `bash studio/make_studio_app.sh` once -> **LOKI Studio.app** in ~/Applications; or `bash studio/loki_studio.sh` |
| from LOKI | the **LOKI Studio** icon at the bottom of LOKI's sidebar (tooltip "LOKI Studio - work on LOKI itself with DeepSeek V4.1") starts it, or brings it to the front |

`python studio/studio_app.py --print-url` serves it without a window (any browser works).
Port `LOKI_STUDIO_PORT` (8771; any free port if taken).

## What it is made of

```
studio/studio_app.py      the launcher: hands over to the pinned copy, then server + window (pywebview, else the browser)
studio/studio_pin.py      the pinned known-good copy of LOKI that Studio runs from
studio/studio_core.py     sessions: worktree per session, the agent loop, approvals, ship, discard, history
studio/studio_models.py   DeepSeek V4.1 Flash on NVIDIA first, then free fallbacks; pacing, 429s, reasoning
studio/studio_control.py  LOKI's status, logs on disk, start / restart, roll back to the last good version
studio/studio_server.py   127.0.0.1 API + the window (token, Host check, CSP script-src 'self')
studio/ui/                index.html, studio.css, studio.js
engine/loki_mcp.py        the LOKI MCP API (docs/LOKI_MCP.md) - the agent's only hands
engine/studio_api.py      LOKI's side: GET /studio, POST /studio/open, POST /engine/restart
```

## Why it survives a broken LOKI

- **Its own process and window.** Nothing in Studio needs the LOKI engine to be up.
- **A pinned copy.** Studio runs its own code and the engine modules it uses (loki_mcp, ratelimit,
  updater, policy) from `harness_data/studio/pinned`: a git worktree detached at the updater's
  **last good** commit on this machine (the one whose engine AND window came up; HEAD the very first
  time). The pin moves forward only after the candidate passes Studio's checks in a throwaway worktree
  (`studio_app.py --self-test` and `tests/test_studio.py`), and only at Studio's next start - never
  under a running Studio. A refused candidate is remembered (`harness_data/studio/pin.json`). If the
  pinned copy will not even start, the launcher runs Studio from the checkout instead.
- **No loki.py.** Studio's agent loop is its own (studio_core + studio_models), so a bad commit in
  the agent loop of LOKI cannot stop the tool that fixes it.

## A session

1. You type what to build or fix. The session gets `harness_data/studio/worktrees/<id>` on branch
   `studio/<id>`, made from the checkout's HEAD (the same isolation as improve_loki).
2. The agent runs **inside Studio** on DeepSeek V4.1 Flash (NVIDIA NIM). No key yet? Studio says
   exactly how to get one (build.nvidia.com/settings/api-keys, paste it in LOKI's Settings >
   Connections > NVIDIA NIM) and uses the next best free model meanwhile (OpenRouter's DeepSeek V4.1
   Flash, OpenCode Zen's DeepSeek V4 Flash, Gemini, Groq, then the local model). Requests are paced
   under NVIDIA's ~40/min (shared with LOKI's own jobs), a short 429 is waited out, anything else fails
   over; DeepSeek's reasoning shows as "thinking" and is never re-sent.
3. Its only tools are the LOKI MCP API, started as a stdio server bound to this worktree: read /
   search / edit LOKI's code there, run the test suites, read HANDOFF and ZIVA_TASKS, and look at and
   control the running LOKI (status, logs, models doctor, settings, jobs, memory, tools health,
   restart). Everything streams into the thread: steps, thinking, tool calls, results, diffs.
4. **Risky calls wait for you** (settings_set, job_start, job_stop, restart_engine): an Approve / Deny
   row in the thread; Studio adds the approval code only after Approve. Stop ends a wait as "no".
5. **Follow-ups** go to the SAME session: same worktree, same branch, the conversation continues.
   A message typed while it works is queued for when the current turn ends.
6. **Diff** shows every change (new files too). **Tests** runs `tools/ship.py --check` there.
7. **Ship it** (only you; the agent's `ship` tool is not even offered to it): a dialog for the message,
   then `tools/ship.py -m ... --repo <worktree>` - every suite must pass, then commit, rebase onto
   GitHub, push master, tell the other machines. Each machine then takes it through the health-gated
   updater (pre-flight self-test, on trial until its window is ready, automatic rollback). Failing
   tests: nothing is pushed and the session stays open.
8. **Discard** removes the worktree and the branch; the conversation stays in the list.

History: `harness_data/studio/sessions/<id>/session.json` (meta + the conversation) and
`events.jsonl` (everything shown), so a restarted Studio shows every session.

## LOKI itself, from Studio

The LOKI card at the bottom of the rail: running or not, the version, last good, on trial.
- **Start / Restart**: down -> starts the LOKI app from the checkout (`app/loki_app.py` with LOKI's
  Python, detached); up -> asks its engine to restart.
- **Roll back**: the updater's rollback for a version on trial; otherwise the same move by hand
  (`git reset --keep <last good>`, which refuses to touch local edits) and the bad commit goes on the
  skip list with the reason, so the updater does not take it again. Nothing is pushed.
- **Logs**: engine.out, loki_app.log, loki_bridge.log straight from disk.
Each asks you to confirm.

## Safety

- 127.0.0.1 only, a fresh token per start (in the URL fragment; `harness_data/studio/studio.token`
  for LOKI's button), a Host check, CSP `script-src 'self'`.
- The agent never sees or writes `harness_data/`, `.env` files, tokens, keys or `.git`, never works
  in the owner's checkout, cannot run commands other than the test suites, and cannot ship or push.
- Keys: Studio reads LOKI's `harness_data/.env` into its own process to call the models; it never
  shows, logs or sends them anywhere else, and the MCP server process gets none of them.

## LOKI Studio inside Godot (the plugin)

The owner: "maybe its better when loki was a godot plugin it was very effective. i want it to work 1:1 OR BETTER
THEN ZIVA". So Studio has a **second front end that lives in the Godot editor**, like Ziva does - while Studio
itself stays its own app (it still works when Godot, or LOKI, is closed). The plugin is clean-room: built from
Ziva's public feature list and Godot's own APIs; no Ziva code or files were copied, decompiled or ported.

### Install it into any Godot 4 project

1. Start LOKI Studio (it writes `~/.loki/studio_connect.json` - its address and a fresh token - on every start).
2. Put the plugin into the project, either way:
   - `python studio/install_godot_plugin.py "<path to the project>"` (Windows: `harness_data\.venv\Scripts\python.exe
     studio\install_godot_plugin.py "C:\Users\...\MyGame"`), or in Studio's chat: the API `POST /api/godot/install`;
   - or copy `studio/godot_plugin/addons/loki_studio/` to `<project>/addons/loki_studio/` and enable **LOKI Studio**
     in Project > Project Settings > Plugins.
   The installer also turns it on in `project.godot` (`[editor_plugins]`) and adds the game autoload
   `LokiStudioGame`; `--remove` takes all of it out again. Works for LOKI World (`game/loki-world`) and the owner's
   own games (`~/LOKI Projects/<name>`).
3. Open the project in Godot (4.4+; 4.5+ for error capture, 4.6+ docks natively). The **LOKI Studio** dock appears
   on the right and links to Studio by itself (status "linked"). Studio's window shows "1 Godot editor linked" and
   offers the project as a target ("On: Godot: <name>").

### What is in the plugin

```
studio/godot_plugin/addons/loki_studio/
  plugin.cfg, plugin.gd   the EditorPlugin: dock, bridge, debugger plugin, logger, context menus, the game autoload
  dock.gd                 the chat dock: sessions of this project, New, Fork, Studio; Default/Plan/Ask; model; Ask first;
                          the thread (answers, thinking, tool calls, results, diffs, checkpoints, screenshots);
                          Approve/Deny and the agent's questions as buttons; todos; Undo turn, Diff, Stop, queued count;
                          the input with /command and @mention autocomplete (Enter sends); "+ Selection"
  bridge.gd               the editor bridge: hello, long-poll /api/godot/poll, answer every studio_godot.ACTIONS action
                          (scene tree, node properties, selection, open scripts, selected code, set_property, add_node,
                          remove_node, connect_signal, attach_script, new/open/save scene, open script, select, rescan,
                          run/stop the game, screenshots of the editor or the game, game input/tree/monitors/values,
                          undo_turn). Scene changes go through EditorUndoRedoManager: Ctrl+Z works on them, and
                          Studio's "Undo turn" undoes a whole turn (only while they are still the newest actions)
  debugger.gd             EditorDebuggerPlugin: the line to the RUNNING game over Godot's own debugger link
  game_bridge.gd          the autoload in the game: injected input (held >= 2 physics frames), screenshots, the live
                          tree, values, performance monitors; idle in exported games (no debugger)
  error_logger.gd         a Logger (Godot 4.5+): editor and game errors/warnings with file, line and backtrace
  context_menu.gd         right-click "Add to LOKI Studio chat" in the script editor, scene tree and FileSystem (4.4+)
```

AGENTS.md: this folder is the third allowed place for Godot files (owner decision 2026-10-17); it has no
`project.godot`. `tests/test_loki.py` and `tests/test_godot_world.py` allow its `.gd` files.

## The Ziva-style workflow (in the window AND the dock)

A session works on **LOKI's code** (a git worktree, as above) or on **a Godot project** (live in its editor; no
worktree - every change is checkpointed instead). Everything below works in both front ends.

| | How |
| --- | --- |
| Project awareness | Godot: `project_index` (project.godot, scenes with nodes/scripts/instances/signal connections, scripts with class_name/extends/signals/exports/funcs/preloads) and `project_graph` (mermaid); the overview is in the system prompt. Code: `repo_map` (per file its classes and functions). `studio/studio_index.py` |
| Modes | Default / Plan (reads, writes a todo plan, changes nothing) / Ask (read-only answers); `/plan <task>`, `/ask <q>`. Write tools are not even offered in Plan/Ask and are refused if called |
| Checkpoints + undo | every turn starts with a checkpoint. LOKI code: a git snapshot commit made with a throwaway index (branch, index and working tree untouched; `refs/studio-checkpoints/<session>/<turn>`). Godot: the original bytes of each file before the turn's first write. **Undo turn N** restores the files as they were before N (later turns too), undoes those turns' editor actions and trims the conversation. Discard in a Godot session = undo everything. `studio/studio_checkpoints.py` |
| Approvals and questions | risky tools wait for Approve (as before) + `pc_worker`; "Ask first" makes every file/scene change wait; `ask_owner(question, options)` shows buttons + a free answer and waits |
| Todos, queue | `todo_write` - live list in the window and the dock; messages typed while it works are queued and run in order |
| @-mentions | `@path/file`, `@folder/`, `@res://...` attach content; `@scene`, `@selection` (selected nodes + code), `@errors`, `@todos` attach live editor state. Autocomplete via `/api/mentions` |
| Slash commands, templates | `/help /plan /ask /default /undo [N] /checkpoints /todos /fork /model <id> /approve edits\|auto /docs /web /remember /memory /skills /index /graph /errors /run /stop /screenshot /lag /playtest /fix /review /test /skill`; templates are `.md` files in `<project>/.loki/prompts/`, `harness_data/studio/prompts/`, `studio/prompts/` (bundled: explain, mechanic, optimize) with `{{args}}`, `{{selection}}`, `{{scene}}` |
| Project instructions | the project's `AGENTS.md` (or `CLAUDE.md`) goes into the system prompt |
| Memory, skills | `remember`/`recall` are LOKI's memory (memory_core: the one the Mac and the PC share); `list_skills`/`use_skill` read SKILL.md from the project's `.loki/skills`/`skills`, LOKI's `skills/` and learned ones |
| Subagents | `subagent(task or tasks[<=3])`: read-only helpers with their own small context, side by side |
| Docs, web | `godot_docs`: the whole class reference offline (`studio/godot_docs.py build` - from a Godot source checkout, `godot --doctool` of the owner's own Godot, or a sparse git clone), cached in `harness_data/studio/godot_docs/`; `web_search` (engine/web_search.py, no key) |
| Playtest, lag | `run_game` -> `playtest_step(events)` = input -> wait -> screenshot -> the NEW errors, one turn at a time; `game_get` reads a value; `find_lag` samples fps/frame/physics times/draw calls/nodes/orphans/memory + the busiest scripts and says where to look |
| Pictures | screenshots (editor 2D/3D/whole, game) saved under `harness_data/studio/shots/` and shown in the thread; `generate_image` (LOKI's local image maker) into the project |
| Mermaid | the window draws ```mermaid flowcharts itself (no CDN); the dock shows the text and a pointer to the window |
| Fork | a new session with the same conversation; for LOKI code its own worktree with the same uncommitted changes |
| Models | `/model` or the picker: auto (DeepSeek V4.1 Flash on NVIDIA first, then the free fallbacks), nvidia, openrouter, opencode-zen, gemini, groq, local (Ollama), lmstudio, **claude-code** and **codex** (the owner's subscriptions: the CLI does the turn with its own tools + Studio's MCP server; `studio/studio_cli.py`) |

### Studio as an MCP server

`studio/studio_mcp.py` gives Claude Code, Codex, Cursor (or Ziva) Studio's Godot hands through the running Studio:
`godot(action, args)` on the live editor, `godot_errors`, `godot_screenshot`, `godot_playtest_step`, `godot_find_lag`,
`godot_docs` and `project_index` (these two work without Studio), and Studio's sessions (`studio_sessions`,
`studio_new_session`, `studio_send`, `studio_events`).

    claude mcp add loki-studio -- python <loki>/studio/studio_mcp.py --project <godot project>

### The API the dock uses (studio_server.py)

`/api/godot/hello|poll|result|event|editors|call|tool|install|docs`, `/api/session/new` (+ `project`, `mode`, `model`,
`approve_edits`), `/api/session/mode|model|approve_edits|answer|undo|fork|queue/clear|checkpoints`, `/api/commands`,
`/api/mentions`, `/api/models`, `/api/shot`. Same token, Host check and loopback as the rest; editor results may be up
to 16 MB (screenshots). The comparison with Ziva, task by task: docs/STUDIO_VS_ZIVA.md.

## Tests

`tests/test_studio_destination.py` (in SUITES, ~7 s, offline - no `openai` needed): destinations with fake gh/git runners
(owner vs non-owner defaults, the guard, argv-only command lines, fork/app/local set-up, the stored choice, sessions and
Ship it), the LOKI settings panel against a fake bridge, studio.js's routes, the Studio tab's single background start, the
Godot tab (checksum, traversal, COOP/COEP, project zip both ways) and the mode bar in headless Chromium.

`tests/test_studio_godot.py` (in SUITES, ~20 s): the plugin's files and GDScript sanity, the installer (CRLF kept,
idempotent, remove), the contract (bridge.gd's actions == Studio's; every /api path the dock calls is served), the
editor link with a fake editor over real HTTP, a Godot session on a scripted model (index, docs, edits + checkpoints,
live editor actions, playtest, lag, todos, questions, subagent, Ask first, Plan mode, queue, undo, discard), a LOKI
session with git checkpoints + fork through the real LOKI MCP API, mentions/commands/templates/memory/skills, the docs
cache and the index, Studio as an MCP server, the Claude Code/Codex stream parsing, the window in headless Chromium,
and - with a Godot binary (GODOT_BIN, `godot` on PATH) - the plugin in a REAL headless Godot editor connected to a real
Studio server (state, open scene, add/set/connect with UndoRedo, real parse errors captured, undo_turn) and the game
bridge in a REAL running game (input -> the game's own polling sees it, tree, monitors, errors).

`tests/test_studio.py` (in SUITES): the rate limiter, the main driver, the real agent loop against a
fake NVIDIA (tool calls, reasoning_content, 429s, pacing), the MCP API, a full Studio session with the
engine stopped (a scripted model makes a real edit in a temp worktree, runs a fake check, waits for an
approval, cannot ship; follow-up, ship with approval, stop, discard, history), rollback, the pin,
Studio's server, and its window in headless Chromium (screenshot `docs/operations/screens/studio.png`
with `LOKI_SUITE_SCREENS=docs/operations/screens`).
