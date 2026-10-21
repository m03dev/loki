# LOKI Studio vs Ziva

The owner uses Ziva (ziva.sh, a commercial AI agent plugin inside the Godot editor) a lot and loves its workflow:
"i want it to work 1:1 OR BETTER THEN ZIVA ... i want my dev tool thats building loki better then ziva smart".

**Legal line.** Ziva is proprietary ("All rights reserved... No permission is granted to copy, modify..."; its plugin
ships as compiled GDExtension binaries and a few .gd files). LOKI Studio copies, decompiles and ports nothing of it.
Everything here is clean-room: built from Ziva's PUBLIC feature list (ziva.sh/docs) and its observable behaviour,
on Godot's own public APIs (EditorPlugin, EditorInterface, EditorUndoRedoManager, EditorDebuggerPlugin, Logger) and
LOKI's own code. This file describes what Ziva does only from its public docs; the numbers in the benchmark below
must come from real runs (ZIVA_TASKS W37/M28), not from this file.

## Feature by feature

Status: **=** matched, **+** LOKI Studio does more, **~** partly, **-** not yet.

| Ziva (public docs) | LOKI Studio | |
| --- | --- | --- |
| Works inside the Godot editor | the LOKI Studio plugin's dock (docs/STUDIO.md); Studio also stays its own app, and works when Godot is closed | + |
| Reads scenes, nodes, scripts, resources, project settings | live editor (scene_tree, node_info, editor_state, selected_code) + files + `project_index` (scenes/scripts/signals/autoloads/inputs graph) | = |
| Reads editor errors and the running game | `error_logger.gd` (Logger, 4.5+) in the editor AND in the game, pushed to Studio; `editor_errors`, `@errors` | = |
| Creates/changes scenes and GDScript/C# | files (GDScript, C#, shaders, .tscn/.tres) + editor actions through UndoRedo (add/remove node, properties, signals, scripts, new/save scene) | = (C#: files only, no C# build step) |
| Searches the Godot docs | the WHOLE class reference offline, for the owner's exact Godot version (`godot --doctool`), searched locally | + |
| Fixes errors, runs tests, inspects results | `/fix`, `/test`; LOKI sessions run LOKI's suites; a Godot project's own tests via the game | = |
| Every turn undoable (checkpoints) | per-turn checkpoints (git snapshots for code, file snapshots for Godot) + the editor's UndoRedo; Undo turn in the window and the dock; `/undo N` | = |
| Playtests turn by turn | `run_game` + `playtest_step` (input -> wait -> screenshot -> new errors) + `game_get`, `game_tree` | = |
| Image generation | `generate_image` (LOKI's local image model, free, on the machine) | ~ (needs LOKI's local image add-on) |
| Default / Plan / Ask modes | the same three; Plan/Ask get no write tools at all | = |
| Approvals and questions | risky tools always ask; "Ask first" for every edit; `ask_owner` with choices | = |
| Image / video / voice attachments | screenshots in the thread; `@`-mentions of files | - (no video/voice attachments yet) |
| Chat history, fork, share | history kept per session (events.jsonl), Fork (with its own worktree for code) | ~ (no share link) |
| Mermaid diagrams | the window draws them itself; `project_graph` makes them from the project | = (the dock shows text) |
| Todos and queued messages | `todo_write` live list; queued messages run in order, count shown | = |
| Subagents | `subagent` (read-only helpers, up to 3 side by side) | = |
| Find lag (game speed profiling) | `find_lag`: monitors over real frames + busiest scripts + a verdict in plain words | = |
| Web search | `web_search` (no key) | = |
| 3D models | - | - |
| Devlog videos | - (LOKI has video tools in the app, not wired into Studio) | - |
| MCP client and MCP server | Studio's agent drives LOKI through the LOKI MCP API; `studio_mcp.py` makes Studio an MCP server for Claude Code / Codex / Cursor | = |
| Slash commands + custom prompt templates | 28 built-ins + `.md` templates per project / per owner / bundled | = |
| @-mentions of files/folders | `@file`, `@folder/`, `@res://`, plus live `@scene`, `@selection`, `@errors`, `@todos` | + |
| "Add selected code to chat" | right-click in the script editor (4.4+) and "+ Selection" in the dock | = |
| AGENTS.md project instructions | the project's AGENTS.md (or CLAUDE.md) in the system prompt | = |
| Memories | LOKI's memory - one memory for the Mac AND the PC (synced), with kinds, supersession and secret scrubbing | + |
| Skills | SKILL.md from the project, LOKI and learned skills | = |
| Models: Claude Code/Codex subscriptions, OpenRouter, Ollama/LM Studio | all of these + DeepSeek V4.1 Flash free on NVIDIA as the main driver, paced, with automatic failover | + |

## What LOKI Studio does that Ziva cannot

1. **It builds LOKI itself, safely.** A session on LOKI's code works in its own git worktree, runs LOKI's suites,
   and only the owner's **Ship it** publishes - through `tools/ship.py` and the health-gated updater on every machine
   (pre-flight self-test, on trial until the window is ready, automatic rollback). Studio runs from a pinned
   known-good copy, so a bad LOKI commit cannot break the tool that fixes it.
2. **Two machines.** The same Studio runs on the Mac and the PC from one version; `pc_worker` hands a long or GPU task
   to the PC as a LOKI job over the signed peer link (asks first) and `pc_job` reads its result.
3. **One memory across machines.** What Studio learns (`remember`) is LOKI's memory, synced Mac <-> PC.
4. **Measured, not claimed.** The task-success benchmark (`tools/task_bench.py`) and the parity benchmark below.
5. **Self-improvement.** Studio is LOKI's own dev environment: LOKI's improve/evolve loops and Studio's sessions
   ship through the same gate.
6. **Free main driver.** DeepSeek V4.1 Flash on NVIDIA NIM (free) by default; the owner's Claude Code / Codex
   subscriptions are one `/model` away.
7. **Offline Godot reference for the exact engine version** - no wrong-version answers, no network.

## The parity benchmark (15 tasks)

Ziva Windows runs each task twice - once in Ziva, once in LOKI Studio (the plugin dock, on the default model) - on
fresh copies of the same project, and fills in the result columns honestly. Projects: **LW** = one of the owner's own games
in `~/LOKI Projects/<name>` with a player and a main scene (copied to a temp folder first), **NEW** = a new empty Godot 4 project, **LOKI** = LOKI's own code (Studio only;
Ziva works on it as a plain folder of files).

| # | Task (say exactly this) | Proj | Ziva: how (public docs) | LOKI Studio: how | Ziva: time / ok / quality | Studio: time / ok / quality |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | "Make a 2D player that moves with WASD and jumps with Space; add the input actions." | NEW | writes the script + scene in the editor | write_file + new_scene + add_node + attach_script + input actions in project.godot, playtest_step | | |
| 2 | "Explain how the player's movement works here, with a diagram." | LW | reads scripts, answers (mermaid) | /ask + project_index + a ```mermaid diagram | | |
| 3 | "Add a coin that adds 10 to the score when the player touches it; connect the signal." | NEW (after 1) | scene + script + signal | add_node(Area2D) + connect_signal through UndoRedo + script | | |
| 4 | "There is an error in the Output - fix it." (break one line in a script first) | LW | reads editor errors, fixes | editor_errors -> fix -> rescan -> errors gone | | |
| 5 | "Plan a pause menu; do not change anything yet." | LW | Plan mode | /plan -> todo_write plan, no writes | | |
| 6 | Then: "Do it." | LW | Default mode | Default -> builds it, checkpoints | | |
| 7 | "Undo that last change." | LW | per-turn undo | Undo turn: files + editor actions back | | |
| 8 | "Playtest: walk right for 2 seconds and jump; tell me what happens." | NEW (after 1) | playtest turn by turn | run_game + playtest_step + screenshot + game_get | | |
| 9 | "The game stutters - find out why." (spawn 3000 sprites in _process first) | NEW | find lag | find_lag verdict -> fix -> find_lag again | | |
| 10 | "What does CharacterBody3D.move_and_slide return, and when is is_on_floor valid?" | any | searches Godot docs | godot_docs (offline, exact version) | | |
| 11 | "Make a pixel-art tree sprite and put it in the scene." | NEW | image generation | generate_image + add_node(Sprite2D) | | |
| 12 | "@scenes/main.tscn - list every node without a script." | LW | @-mention | @-mention + scene parse | | |
| 13 | "Remember: in this project coins are worth 10." then, in a NEW chat: "What are coins worth?" | NEW | memories | remember -> recall (also on the other machine) | | |
| 14 | "Add a tooltip to LOKI's Clear finished button in the jobs list; run its test." | LOKI | edits files in a folder | LOKI session: worktree, edit, run_tests, diff, Ship it (owner) | | |
| 15 | "Fix the most frequent error in LOKI's engine log today." | LOKI | reads files | engine_logs + loki_status via the LOKI MCP API, fix, tests | | |

How to score: **time** from pressing Enter to the agent's last word (minutes); **ok** = the result really works (run
it; for 7 the files and the scene are exactly as before; for 13 the answer is "10"); **quality** 1-5 (right approach,
clean GDScript 2, no needless changes, says what it did). Note the model each tool used. Paste the filled table
under ZIVA_TASKS Reports; anything Studio lost or could not do becomes a `[claude]` request.

## Known gaps (honest)

- Video and voice attachments, 3D model generation, devlog videos and share links are not in Studio yet.
- The dock is plain Godot UI; the window draws diagrams, the dock shows their text.
- The game bridge needs the game to be started from the editor (it uses the debugger link); screenshots need a
  window (a headless Godot has no picture, and says so). Error capture needs Godot 4.5+, the right-click entries 4.4+.
- Undo turn undoes the agent's editor actions only while they are still the newest in that scene's history; if the
  owner edited the scene after, it says so and leaves the rest to Ctrl+Z. Files are always restored.
- Claude Code / Codex as drivers were tested here with a fake CLI stream only (W37 checks the real CLIs).
- Verified here on Linux with a real headless Godot 4.7.2; the dock UI in a real windowed editor, playtesting a real
  window, screenshots and the Windows/macOS Godot builds are for W37 / M28.
