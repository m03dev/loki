# HANDOFF - where LOKI stands right now

Read this, AGENTS.md and docs/BUILD_BRIEF.md before working (machine agents: LOKI_TASKS.md too). The rules and the
brief were rewritten on 2026-10-24 for the current scope (3D creation engine: Forge, Render Studio, farm, local AI).

**How to use this file.** It is the CURRENT picture, not a diary. When you ship something significant
(tools/ship.py), edit the area it changed under "Current state", tick or remove what you fixed under "Open
problems", and move "Next" along - in place, in a few lines. Long write-ups go in the commit message,
docs/operations/SESSION_LOG.md or a doc of their own. Every session entry up to 2026-10-19 04:10 (sessions 13-30
and all dated entries, with their full test lists) is kept verbatim in
**docs/operations/archive/HANDOFF_until_2026-10-19.md** - search it for the history of anything below.
"Verified" below means seen on a real machine (the Mac mini or the PC); "cloud" means checked only on Claude's
Linux box (headless Chromium, stubs, headless Godot).

Last updated: 2026-10-24 14:05 (owner idea I5: Forge hotbox menus stay clear of the title strip - Windows > OpenChannelsLayers is clickable again; app/ui/forge_pro.js forgeTopInset, tests/test_forge_pro_ui.py).

## The machines

| | Mac mini (M4, 16 GB) | Windows PC (RTX 3070 Ti, on 24/7) |
| --- | --- | --- |
| Checkout | `~/Documents/loki` -> `/Volumes/LokiSSD/loki` (APFS sparse image on the 2 TB SSD; login item `sh.loki.attach-image` reattaches it) | `C:\Users\macul\Documents\loki` |
| Python | `harness_data/.venv/bin/python` | `harness_data\.venv\Scripts\python.exe` |
| Godot | LOKI's own 4.7.2 when no other Godot; Godot_mono 4.8 dev is not LOKI's - never open the owner's projects in it | LOKI's own 4.7.2 (`harness_data\addons\godot-export\editor\Godot_v4.7.2-stable_win64.exe`); never `Godot_v4.8-beta1_mono` / ai_testin |

The repo is PUBLIC and AGPL-3.0 since 2026-10-17 (W43, 910dab2). Branch `master` only; `macos-app` is a mirror
ship.py keeps in step. The CI tests workflow was removed (2026-10-25, it only emailed failures); the suites run locally and the Windows build workflow stays.

## Now (2026-10-25)

**2026-10-26 (Claude, cloud):** output names are one rule now - `engine/out_names.py`: `<subject>_<YYYYMMDD-HHMM>[_tag][_n].ext`
(e.g. `knight-sword-shield_20261026-1021.png`; filler/style words dropped, never cut mid-word), used by images, video,
3D, turnarounds, voice and sprites; old names still display. Blender MCP built in: `engine/blender_link.py`
(setup/open/status) + vendored add-on `contrib/blender_mcp/` + the "blender" server in mcp_servers.json (starts only
where Blender is installed). Home's scroll bar on the Mac: WebKit scroll bar + a fixed grid row in home_layout.css
(checked only in cloud Chromium - the Mac must confirm). Maya MCP: not found on the PC; LOKI_TASKS has the Mac search.
Blender on the PC (5.2.3 LTS, C:\Program Files\Blender Foundation\Blender 5.2): Script Directory set by the owner to
~/LOKI Projects/Home/blender/scripts (startup/loki_blender.py + addons/blender_mcp.py) - NOT %APPDATA%: the Claude
desktop app on the PC is an MSIX package, so files it writes into AppData land in its virtualized LocalCache and
Blender never sees them. Design (engine/blender_link.py docstring): a permanent loader (startup/) hot-reloads the core (loki/) when its file
changes - fixes are a file write, never a restart; the core runs jobs in their own scene in a window + 3D-view
context, a watchdog keeps the MCP add-on + socket on; with no window, run() uses a background Blender. Proven on
the PC 2026-10-26: switched over live, core hot-reloaded .2 -> .3, campfire rendered (EEVEE, 3 s) + .glb + .blend.
3D afternoon (2026-10-26): Blender toolkit in the core (import/cleanup/normalize/decimate/remesh/uv/shade/stage/render/
export/lods/turntable) + blender_link.polish() - verified on the PC (Forge character 32.8k->20k tris textures kept;
Poly Haven cannon 41k->15k). free_assets.py (Poly Haven + ambientCG, CC0) verified against the real APIs from the PC.
Hunyuan3D 2.1 = owner-installed Forge backend (forge_hunyuan.py; ComfyUI native nodes on 8 GB), not accepted yet.
Picture viewer (app/ui/image_viewer.js, Cropper.js vendored): click a Home preview or a chat picture -> big, ‹ › / ← →
through all pictures; S select area, F focus, Save crop, E edit area -> engine/region_edit.py redraws only the box
(local img2img: sd.cpp -i/--mask on the PC, mflux --image-path on the Mac) and saves <name>_edit.png beside the
original; pixels outside the box are copied untouched (tests/test_image_area.py). Real-model run: LOKI_TASKS.
**Home + turnarounds v3 (2026-10-26 20:00, owner: "when i click on an image it takes me to the top ... jarring ...
it needs to match in every perspective, environment pieces dont need 4 views"):** Home works like a photo app now - a
click opens the picture (or a 3D model) in the viewer right there, no jump or redraw; double-click / Shift+Enter opens it
where it lives; thumbs up / down / delete on every card; the grid is everything grouped by day with "Show more" (60 at a
time) instead of one row + "All"; thumbnail size S/M/L; the hero shows the whole picture (it cropped tall ones).
Turnarounds: front / side / back drawn on ONE canvas (1568x672) from the concept and split at the gaps; characters and
creatures get no top view, props / vehicles do; scenes are concept only. NVIDIA reference pictures: every known input
form is tried (inline PNG list / string / JPEG / smaller / NVCF asset) and the one that works is remembered
(harness_data/nvidia_reference_format.json) - the Mac's v2 run got HTTP 422 on the first form.
**Pictures (2026-10-26 evening, owner: "thumbs down ... lots of settings ... the perspective technical images are
awful"):** thumbs up / down beside every picture (Home + viewer; down asks why with reason chips) -> engine/image_feedback.py
(ratings.jsonl + sidecar; the reasons become words in the next prompts for that folder; a pipeline picture's stage is
retaken; a lesson for its stage). Settings panel in the viewer (G) drawn from engine/image_settings.py (size by aspect +
megapixels or exact pixels, steps, guidance, sampler, seed, count, change amount, start from this picture, style, avoid,
upscale, pixel size, palette, model; what a model ignores is greyed) -> Remake (engine/image_api.py). Steps / guidance /
sampler / image-to-image now reach sd.cpp, mflux and NVIDIA. Turnaround v2 (engine/turnaround.py): views are edits of
the concept (FLUX.2 klein reference images), no "sheet" wording, scenes refused, colour + silhouette checks. Viewer
fix: tall pictures were cut off at the bottom. Cloud: test_image_settings_feedback 32/32, test_image_rate_ui 14/14
(real window + real routes), test_turnaround 18/18, test_viewer_e2e_ui 19/19. NVIDIA's reference-image format is
unverified until the Mac runs it (LOKI_TASKS DO FIRST).
**Blob fix (2026-10-26 late, owner: "that golem looks so bad its just a blob ... looks nothing like images"):** every
model on the Mac had been the silhouette 'lift' (models/.meta backend lift) - the online TRELLIS Space failed and
forge3d fell through to lift without a word. Now: a failed real backend is an error (lift only when asked for or
allow_draft); online tries each Space in LOKI_FORGE_SPACES (TRELLIS, then TRELLIS.2); polish refuses lift drafts; the
pipeline's model stage asks the vision judge (forge_judge) and fails a model under 60 % likeness; on the Mac a failed
model retries online first. tools/check_online_3d.py shows what each Space offers and makes a test model. The golem
remake is the Mac's DO FIRST request. Cloud: test_forge3d 80/80, test_asset_pipeline 39/39, test_retopo 25/25.
**Asset pipeline (2026-10-26 night, owner: "like an industry pipeline where they pass on work to each other and can
improve"):** engine/asset_pipeline.py + docs/ASSET_PIPELINE.md. concept -> turnaround -> model -> finish (Blender
retopo) -> render; each stage's output is checked before the next stage gets its APPROVED hand-off record
(pipeline/<asset>/<stage>/v00N/record.json + handoff.md); retries change what failed (seed / backend / quad count), 3
fails -> retake; review notes (retake=true) reopen a stage and send everything after it back; lessons per stage voted
by results, promoted into skills/learned/pipeline-<stage>; settings that worked reused. Driven by the autopilot
`pipeline` duty, the `asset_pipeline` tool, and the PRODUCER / ART DIRECTOR standing goals (they replace the three
"newest file without X" goals). Cloud: tests/test_asset_pipeline.py 35/35. On the Mac (2026-10-26 18:00, merged into
~/Documents/loki by Claude from a git bundle - origin/master not pushed yet, ship.py must): LOKI's own team ran the
retopo request with a background Blender 4.5.9 LTS (/Applications): moss golem 17,216 tris -> 8,127 quads, 100% quads,
0.7% poles, colour + normal map baked, .glb/.gltf/.fbx/.blend + LODs (qa/retopo-mac.md, renders/moss-golem-polished_
20261026-1801.png; triangle counts re-read from the .glb files). The window loader + MCP add-on on the Mac is the open
DO FIRST request (blender_link.py setup); the engine picks up the pipeline duty and tool on its next restart.
**Workable topology (2026-10-26 evening, owner: "the entire point of blender is so it can edit the mesh and make em
workable"):** core command `retopo` (engine/blender_scripts/loki_blender_core.py, core 2026-10-26.14): original kept as
`<name>__high`, scale applied, voxel surface, tiny edges merged until Blender's own QuadriFlow pre-check passes
(`qf_problems` - QuadriFlow refuses any edge < 1e-4 in local units, which is why every AI mesh "failed as non-manifold"),
QuadriFlow (3 seeds) -> Instant Meshes (BSD, when LOKI_INSTANT_MESHES points at its binary) -> clean voxel surface,
projected back; `bake` normal=true adds a tangent normal map; colour is baked as EMISSION of Base Color (a DIFFUSE bake
was pure black on glTF's metallic=1 - never noticed before because no earlier run had a textured high mesh). polish()
retopo=<quads> skips decimate; Forge Clean up and every new Forge model use retopo=8000 (`retopo: 0` = old behaviour).
Verified on the PC (Blender 5.2.3): fantasy character 32,834 tris / 0% quads / 92.6% poles -> 7,260 quads, 100% quads,
4.2% poles, 0 non-manifold, texture + normal map baked (renders/retopo/before_*.png vs after_*.png); robot 9,934 tris ->
8,196 quads, 1.0% poles (its source is an old silhouette-lift blob: clean quads, still a blob). Also fixed on the PC
(core .14/.15): LODs crashed in a fresh scene (no depsgraph); every .glb/.fbx/LOD carried the studio's ground plane
(exports now hold only the model); every FBX was written with Blender defaults (no embedded textures) because
export_scene.fbx has no use_active_scene - `_op()` now drops unknown options and keeps the rest (FBX 0.5 MB -> 8 MB). Skill pack for agents:
skills/blender-gameready (router + 4 stages), template agent "3D Finisher" (engine/agents.py). tests/test_retopo.py.
Limit: even quads, not artist loops at eyes/mouth/joints; thin cloth can get holes at voxel 160.

Tabs are Home / Forge / **Studio** (the render farm manager + Render Studio, docs/STUDIO_FARM.md) / **Engine** (Godot
or the Carbon Editor). Forge: Flatten = scale to 0 (Maya / Unreal), tools act on the whole mesh when only the object
is picked, one key per command, sculpt right button = wheel only. Branch `agent/studio-farm-forge-scale`; next steps
in LOKI_TASKS.md (incl. the ChatGPT-web provider and the token blow-up diagnosis).

**Home, reimagined (later 2026-10-25):** one split, two panes, both always there - the hub left (home.js), the chat
column right (#chat-col in index.html, home_layout.css, chat_view.js). The chat is never hidden behind a "Loki" click
any more; the conversation has a visible scroll bar, follows new output only while you are at the bottom, and shows a
"Latest" button when you scroll up; the message-box buttons wrap instead of being cut off; the top-bar panel button
folds the hub away (remembered, `loki-hub-off`); under 900 px the panes stack. Speed: /home/projects caches every
thumbnail by path+mtime+size and only encodes the newest content files; the hub skips redraws when nothing changed;
opening a long chat lays out once. Tests: tests/test_home_projects.py.

## Earlier (2026-10-24)

- **Rules rewritten** (owner: "delete all loki rules ... rewrite them better"): AGENTS.md is the one rulebook,
  ZIVA.md is gone, docs/BUILD_BRIEF.md is the new direction (3D creation engine). Cloud sessions hand work over on
  `agent/*` branches; machine agents merge them at session start (AGENTS.md > Git and shipping).
- **Forge Level workspace** (owner: "forge as an editor ... close to unreal engine"): docs/FORGE_LEVEL.md. Place
  Actors, Content Browser, Details + scripts, Play in Editor (Alt+P) / Simulate / Stop, Save / Open Level. Cloud:
  tests/test_forge_level_ui.py 21/21 + its node suite 24/24 in headless Chromium. **Not verified on the Mac/PC yet**
  (pointer-lock mouse look and the feel of walking need a real window).
- **WoW-style world in the Level editor** (owner: "its gonna be an rpg like world of warcraft"): Terrain (sculpt + paint,
  saved in the level), Creature Spawns (wander / aggro / leash), third-person Play with WoW controls. Cloud verified.
- **Carbon MMO engine editor** (owner chose a native C++ editor, 2026-10-24; overhauled the same day: "more like a
  game engine ... modern, bevelled, high pixel density"): `native/carbon_mmo` `cmmo_editor` - Dear ImGui docking +
  ImGuizmo + its own GL 3.3 renderer over the engine's C++ world module, all on Carbon math. Theme: IBM Plex + Font
  Awesome at the screen's density, bevelled icon buttons with tooltips. Unreal toolbar (Play/Simulate/Pause/Stop),
  Godot scene tree (parenting, prefabs), Terrain3D-style terrain tools (create/generate, 9 brushes, layers +
  auto-shader, foliage), Content Browser (levels, glTF models, prefabs), World Settings, and the MMO layer in Play
  (Tab target, abilities, quests, zones, XP, HUD + minimap). File > New Starter Zone is a playable example. Cloud
  verified headless (self-test 32/32 with screenshots, world 43/43); never run on the Mac yet. Forge's Level
  workspace stays (LOKI's editor); the game engine editor is this.
- **Carbon MMO Foundation** builds and runs on the Mac (verified 2026-10-24: window + all 5 tests) from
  `~/Loki/native/carbon_mmo`, build in `/Volumes/Xero/carbon_mmo/build`; needs pybind11 3.1.0 (2.13.6 fails on the
  macOS 27 SDK). Not in git yet. NOTE: the LOKI repo on the Mac is `~/Documents/loki`, not `~/Loki`.

## Current state

### Engine, agents, models
- **Main driver:** DeepSeek V4.1 Flash on NVIDIA NIM (`deepseek-ai/deepseek-v4.1-flash`, engine/nim_models.py),
  paced by engine/ratelimit.py (LOKI_NVIDIA_RPM 36, shared via harness_data/ratelimit/nvidia.json). Replies stream
  (engine/loki.py `_streamed_request`, LOKI_STREAM_MODELS) since 4c34824 because unstreamed 8192-token answers timed
  out. The owner's NVIDIA key is on the Mac (`~/.loki/keys.env`). **Not verified:** a real NVIDIA turn after the
  streaming fix (test_engine_stream 12, test_studio_stream 10 are cloud only).
- **Keys** live per user in `~/.loki/keys.env` (`%USERPROFILE%\.loki\keys.env`, mode 600, engine/user_keys.py) as
  well as the checkout's .env; suites get an empty LOKI_USER_KEYS.
- **Local models:** resolve_local_model() asks for a tag that is really installed (32cb1b4, verified on the Mac);
  a stuck local job tries the next installed local model before the cloud (model_setup.next_installed, 4ad7229);
  opt-in UNCENSORED catalog of 22 registry-checked tags + the owner's own `harness_data/models_custom.json`
  (0ac6d35, 9f928fe; Settings > Models shows add-by-name, the uncensored list, "Ollama is out of date").
  Bonsai 2 loads on both machines (Ollama 0.40.6). Prompted tool harness reads [TOOL_CALLS], <|tool_call|>,
  <function_call> and {tool_calls:[...]} shapes (a3fc893). A 400/413/422 on a >= 24k-token request condenses and
  retries (`loki._maybe_size_error`).
- **Agents finishing tasks:** tools/task_bench.py, 31 tasks through the real `loki.run_job`; scripted fakes 31/31
  (test_task_success 94/94 after 41ff9b9). **No real model has run the bench yet** (W31).
- **9Router** provider (decolua/9router 0.5.104, 127.0.0.1 only) - written, never run (npm unreachable in the cloud).
- **anyCreature** vendored under contrib/anycreature/ (MIT); `make_creature` agent tool (engine/anycreature.py).
- Subprocesses never open a console on Windows: engine/no_console.py makes CREATE_NO_WINDOW the default
  (LOKI_SHOW_CONSOLES=1 turns it off); verified on the PC with an 8-minute visible-window poll (W51).

### App window and tabs
- Four title-bar tabs (app/ui/modebar.js MODES): **Home / Forge / Render / Godot**, Ctrl/Cmd+1..4 (Ctrl works on macOS
  too). Render shows the Render Studio once its script registers (`LokiModeBar.register("render", ...)` or
- **First layer (2026-10-21, patch 397):** `_triage` calls `first_layer.triage(text, mode, wait=False)` so a cold Laya
  (it loads in ~8 s and unloads after 30 min idle) never stalls a request; warm decisions are ~2-3 ms. Home's header lost
  its redundant 'Home' title and its icons sit on the left.
- **Render Studio Nodes workspace (PC, 2026-10-21, patch 396):** the Nodes button opens an interactive graph like Maya's
  Hypershade - a **Create** list (blocks grouped Guide/Sample/Output/Load with plain names + blurbs; a LOKI group for the
  Forge passes, start image, Test / Preflight / Render), a drag/pan/zoom work area, and an **Attributes** panel whose
  fields are the same settings as the form. **All 7 named model files** are installed on the PC now (the --zimage list
  gained the depth graph's ControlNet).
- **Render Studio Nodes view (PC, 2026-10-21):** the Render View bar has a **Nodes** button that draws the workflow as a
  node canvas (`/render/graph` derives nodes/links/models from the graph's own JSON; nodes colour green/red from the last
  Preflight). **ComfyUI runs on the PC** at D:\loki\harness_data\comfyui (0.42.0, PyTorch 2.14.1+cu130,
  RTX 3070 Ti) with the 3 VACE model files (18.6 GB) installed. **The PC's LOKI now lives at D:\loki** (junction at the
  old path) - the C: drive was full. See LOKI_TASKS 2026-10-21 for the numbers.
  `window.LokiRenderStudio`); until then it offers Forge's Render window.
- **Home = the preview hub** (app/ui/home.js, home.css; owner 2026-10-21): the latest render big, then cards for renders
  (`harness_data/renders/<job>/manifest.json`), Forge models, Godot projects (~/LOKI Projects), Studio sessions and jobs
  (this machine + the farm) from one call, `GET /home/projects` (engine/home_projects.py; a failing source is reported,
  never fatal). A card opens where it lives (Forge + its model, the Godot tab on its project, Studio on its session,
  Render, a job's status). Kind icons filter; tooltips everywhere; the chat is the word "Loki" or just typing; the hub
  folds to one row while a new chat is open and hides once a conversation runs. Cloud only (test_home_projects 58).
- **Windows:** frameless, LOKI's strip is the title bar with its own min/max/close, Aero snap via WM_NCLBUTTONDOWN
  (app/loki_app.py win_hit) - **verified on the PC** (W50, docs/operations/screens/w50-titlebar.png).
  **macOS:** pywebview frameless full-size transparent title bar with the traffic lights (68b9469) - cloud
  (test_ui_fit runs pywebview's real customize.js); no report from the real Mac since.
- **Cross-origin isolation:** the UI is COOP same-origin + COEP require-corp (04def98, for the in-window Godot web
  editor); every bridge answer adds COEP + CORP cross-origin (loki_bridge.py COI_HEADERS, ecf9b40) so Mermaid,
  Preview, LOKI Apps, Play and the Studio frame work. Cloud only (test_research3 154, test_apps 131) -
  **not checked in WebView2 / WKWebView**.
- Background mode: closing the window keeps LOKI running; it starts hidden at login (Startup LOKI.vbs /
  LaunchAgent). The stray Startup `Loki.lnk` -> Loki.cmd that opened a console at every logon is removed by
  `retire_console_launchers()` (847a78b).
- Health-gated updates: a version must pass `app/loki_app.py --self-test`, have every window file and post
  `/ui/ready`, else it is rolled back and skipped (`.git/loki_update_health.json`).

### Studio
- Inside Home (2026-10-21, owner: "combine studio with home"): a full-height pane over the home screen - the Studio icon
  in Home's header, a Studio card (opens that session), the sidebar's LOKI Studio button, Ctrl/Cmd+Shift+S; Esc / back
  closes it. Same backend as before: Studio's own server started headless (`POST /studio/embed`), a pinned known-good
  copy (harness_data/studio/pin.json). Kill loop fixed (`studio_api.good_codes()` = pin + HEAD, restart at most once per
  10 min); the pacing check is fixed (tests/test_studio.py window 3 s, a3e1b64). Local driver uses an installed model.
- LOKI Studio Godot plugin 1.2 (studio/godot_plugin/addons/loki_studio/) links to both Studio and the engine; dock
  shows "LOKI: linked / not linked". **Verified on the PC** (W51: "LOKI Studio plugin 1.2 ready").
- Not verified: a real model driving a Studio session on NVIDIA; the 15-task parity benchmark
  (docs/STUDIO_VS_ZIVA.md); `gh repo fork/create` destinations.

### Godot (the owner's game projects)
- The Godot tab lists ~/LOKI Projects/<name> (LOKI_PROJECTS_DIR) and opens one in the computer's own Godot, or LOKI's own
  standard 4.7.2 when there is none (engine/godot_editor.py, downloaded once, SHA-512 checked; LOKI_GODOT_EDITOR=system
  never uses it). Opening copies the LOKI Studio plugin in and installs the project's plugins.json (godot_live.ensure_plugin).
- engine/godot_live.py hosts the editor link (`/api/godot/*`, `~/.loki/engine_connect.json`); every agent has
  `godot_editor`; Asset Library plugins via install_plugin are recorded in the project's plugins.json (docs/LIVE_GODOT.md).
- GET /world is the live view of agents / jobs / machines (engine/events.py); the home screen and MCP world_summary read it.
- **Verified on the PC (W50/W51):** Open in Godot downloads + opens LOKI's 4.7.2 and the live link shows the editor and
  agent actions. **Not verified:** the Godot tab on a project in ~/LOKI Projects on either machine.

### Forge
- **Forge = Maya 2027 (2026-10-22, docs/FORGE_MAYA_PARITY.md - the plan and the record)**: Maya's own layout is read
  from a Maya install by `tools/forge_maya/extract_maya.py` into `docs/forge/maya2027_layout.json` (names, order,
  compass positions, 510 default hotkeys - no Autodesk code); `tools/forge_maya/gen_layout.py` (the Maya->Forge MAP)
  writes `app/ui/forge_maya_layout.js` (FORGE_MAYA) and the parity doc. forge_pro.js builds the menu bar (File .. Windows,
  then the set: Modeling = Mesh, Edit Mesh, Mesh Tools, Mesh Display, UV; Animation = Key, Playback; Rendering = Render;
  Sculpting = Forge's own), every menu in Maya's order with Maya's labels and section headings (Forge's extras under
  "LOKI" at the end), the hotbox zones and the Shift+right-click marking menus (object / vertex / edge / face / empty, sub-
  menu wedges open their own ring) from it. Snap and Symmetry left the bar (status line, as in Maya). Hotkeys = Maya's
  where Forge has the command (F2/F4/F6 sets, Ctrl+S, Ctrl+Shift+X Multi-Cut, Ctrl+Shift+Q Quad Draw, Shift+X/C/V snaps,
  Ctrl+Alt+Left/Right spin edge, Alt+F12 UV shell); Ctrl+Shift+I = Invert Mask while sculpting (Maya's sculpt context).
  234 of 1113 Maya rows are in Forge (20%): the "-" rows of the parity doc are the build list. To change the layout:
  edit MAP / EXTRAS in gen_layout.py and run it (tests/test_forge_maya_layout.py checks it's up to date).
- **Menus are trees + LOKI tests Forge (2026-10-22, docs/FORGE_QA.md)**: FORGE_PRO_MENUS entries may be
  `["Label", [entries]]` to any depth (menu bar cascades: fmyRow/fmySubDrop; hotbox flyouts: forgeProFillList; wheel and
  marking lists drill in with Back); dead commands are left out of every menu; every floating list fits the window
  (fmyFit / forgeProFit). `forgeMenuFlat(list)` = a tree's ids. `tools/forge_qa.py` sweeps every menu row, button,
  hotbox/wheel entry and command (first run: 70+ unclickable rows, now 0); the autopilot's `qa` duty
  (engine/forge_qa_duty.py) runs it every 6 h when idle and files new problems as Lab ideas (kind "qa") for evolve.
- app/ui/forge*.js: draw / picture / describe -> 3D (engine/forge3d.py: TripoSR -> TRELLIS Space -> offline lift),
  SculptGL-ported sculpting, Material Maker nodes, primitives + poly ops + DynaMesh (GoBuild port, GPL-3.0),
  Blender-style component editing (forge_edit.js: vert/edge/face, box select, G/R/S, proportional), Quad view.
- **pro layer** (forge_pro.js, forge_scene.js; docs/FORGE_PRO.md): marking menus, hotbox, hotkeys, Alt camera;
  T1 scene, T2 Outliner, T3 Group/Ungroup, T4 Channel Box, T4b Freeze/Center Pivot, T5 Shift+drag duplicate,
  T6 construction history for poly ops + DynaMesh (c132c1f, test_forge_ui 62/62). 
- **Creature creator** (engine/anycreature.py): 6 starters, 9 body-plan sliders, coats, Walk/Idle preview
  (test_anycreature 33, test_forge_creature_ui 8).
- Not verified: TripoSR on the PC's CUDA / the Mac's MPS (`tools/setup_forge3d.py`), poly editing with a real GPU.
- **2026-10-19 (Claude): the reference package read off the Mac's own install** -> docs/FORGE_PRO_SPEC.md (facts only, no
  the vendor code). Built on it (forge_scene.js, forge_pro.js; tests/test_forge_pro_ui.py 55 checks, ~23 s): real
  pivots (the pro matrix - pivot moves never move the object or change translate), every object editable
  (`makeWorking`), Create = new pCube1/pSphere1 objects, Duplicate / Shift+D / Group / Parent / hide / isolate /
  pick-walk, viewport click + box selection with the pro modifiers, context marking menus picked by direction,
  hotbox zones, Space tap one/four views, Top/Front/Side, pivot edit (d), view undo ([), the pro Outliner. pro is
  pro-only keys (the owner had the Blender set removed). Later the same morning: the pro workspace (Outliner left,
  Channel Box right, the rest from Space > Windows, Ctrl+Space), the pro hotbox layout, x / c / v snapping and a grid.
- **2026-10-19 afternoon (Claude): Forge LOOKS like the pro tools** - the reference package screenshotted on the Mac, colours sampled
  (docs/FORGE_PRO_SPEC.md "The look"); new app/ui/forge_chrome.js: menu bar, status line, shelf, tool box, time
  slider, help + MEL command line, the viewport's menus, HUD, view cube, grid, lambert grey, teal selection wire.
  Not verified on a real machine yet (LOKI_TASKS M-F1 / W-2). Next: FORGE_PRO.md T7-T12.
- **2026-10-19 evening (Claude), owner 17:06:** no product/vendor names anywhere (files renamed: forge_pro.js,
  forge_chrome.js, test_forge_pro_ui.py, docs/FORGE_PRO*.md; identifiers forgePro*/view.pro). Forge's own camera
  controller (`forgeProCamera`: Alt tumble / track / dolly, Shift lock, Ctrl box dolly, wheel; OrbitControls keeps
  only the target). Right button = hold-only marking menu, opens on press, quick click does nothing; empty space =
  Complete Tool / Select All / Undo ... list. Space = hotbox centred on the mouse (the wheel: Windows > Radial
  Menus). Modern high-contrast theme + one 20 px menu style (end of forge.css), picture at 1.5-3x pixel ratio, shelf
  hidden by default. Component display light-blue / orange / purple; the object wire follows edits via
  `view.frameHooks` (the "weird wireframes after moving an edge" were the stale wire of the old shape). Insert Edge
  Loop restored (8086bf2 had removed it). Checked: test_forge_pro_ui 99 (44 s), test_forge_ui 37,
  test_forge_edit_ui 21, test_forge_model_ui 14, creature 8, poly 32, ui_fit 81, ui_smoke 10, studio_destination 81.
  Next: LOKI_TASKS "From Claude (2026-10-19 evening)" - real-screen check, then Combine/Separate/Mirror/Merge.

- **2026-10-20 (Claude): the native sculpting engine** - LOKI's own C++ sculpting core (`native/sculpt/`, AGPL-3.0;
  from the owner's sculpting plug-in, brought in on his decision) built to WebAssembly (`app/ui/vendor/sculpt/`,
  371 KB) and run in a Web Worker by `app/ui/forge_sculpt.js`. Forge's strokes go to it when it is loaded (the
  SculptGL brushes stay the fallback, `view.dab` unchanged): 40 kernels + the 204-preset library ("More brushes"),
  dynamic detail, Remesh (voxel, even surface), Quad remesh (field-aligned), subdivision levels (Divide / Lower /
  Higher), six matcaps + Lit, and a wire overlay that fades as edges crowd on screen (never solid). Hover picking
  uses the engine's BVH and the brush ring its hit normal (no per-move scan of every vertex). Only moved vertices
  come back (+ one-ring), into the GPU buffers' update range. ~1 ms per dab at 2.1M vertices (node). The worker has
  its own CSP with 'wasm-unsafe-eval' (`SCULPT_WORKER_CSP`); pages keep UI_CSP. Forge's undo/history: a stroke is
  one history step, recorded when the worker has sent its last vertices. Commands: sculptRemesh, sculptQuadRemesh,
  sculptDivide, sculptDynamic, matcapNext/Prev (FORGE_PRO_CMDS). Rebuild: native/sculpt/README.md. Cloud-checked:
  test_forge_sculpt_engine 19 (26 s, real mouse strokes in headless Chromium), test_forge_ui 37, test_forge_pro_ui
  100, test_forge_edit_ui 21, test_forge_model_ui 18, creature 8, poly 36, ui_fit 81, ui_smoke 10. Not verified on
  the Mac's WebKit window or the PC's WebView2 yet (worker CSP + WebAssembly there). Not wired yet: the Mask and
  Paint brushes (engine has them; Forge needs a mask/colour display), alphas, the threaded build (the window is
  cross-origin isolated, so SharedArrayBuffer threads are possible).

- **2026-10-21 (Claude): undo, hotkeys, manipulator, Creature Editor, sculpt quality** - docs/FORGE_PRO.md "DONE (Claude,
  2026-10-21)". Undo/redo now hold the whole scene (Create/Delete/Group/drags/channels/editing another object, one
  labelled step each; the queue is no longer wiped by makeWorking). Moves land in the history (polyTweak). Hotkeys are a
  table (app/ui/forge_keys.js) with a Hotkey Editor (Windows > Settings/Preferences). New manipulator look
  (app/ui/forge_manip.js); Shift over a handle = duplicate (objects) / extrude (faces); middle-drag from anywhere.
  Creature Editor: fold / float / dock / close. Sculpt engine: HC smooth that keeps volume, falloff-aware auto-smooth,
  stabiliser + spacing + pressure, changed-range uploads, screen detail, Tube / Insert Mesh (native/sculpt/README.md).
  Cloud-checked (see SESSION_LOG); **not verified** in WKWebView / WebView2 - LOKI_TASKS "From Claude (2026-10-21)".
  The owner's Maya sculpting plug-in source was not reachable from this session (not in ~/Documents, ~/Downloads or
  GitHub); ByHand is Windows-only and was not on the Mac.

- **2026-10-21 later (Claude): the pro polygon tools + Modeling Toolkit + rules** - docs/FORGE_PRO.md "DONE (Claude,
  2026-10-21 later)": app/ui/forge_polyops.js (32 ops), app/ui/forge_toolkit.js (runner, live Tool Settings, INPUTS
  nodes, interactive Multi-Cut / Target Weld / Offset Edge Loop, the toolkit tab); Delete dissolves edges / vertices;
  calm hotbox; 4 wireframe-only; f on components; manipulator fix for Shift-extrude; the Generate panel. Cloud only.

- **2026-10-21 early morning (Claude)**: a new scene is empty (only the four cameras in the Outliner, empty Channel
  Box, the 3/4 persp view); Display Layers get R (reference: clicks go through, snapping still works) and T draws as a
  grey wire; Free Image Plane (forge_imageplane.js: PNG / JPEG / WebP, menu, hotbox, drop on the viewport, Alpha
  Gain); every side panel resizes by its edge in % (forge_split.js); no scroll bars; channel fields give the keys back on
  Enter; hidden objects grey in the Outliner. C++: native/sculpt/core/src/cage_subdiv.cpp (Catmull-Clark, the JS
  result exactly, ~6x faster) runs the 2 / 3 smooth preview of 400+ face cages in a worker (forge_geom.js);
  sculpt.wasm rebuilt (WASI SDK 25, test_engine ALL OK). docs/FORGE_PRO.md "DONE (Claude, 2026-10-21 early morning)",
  research: docs/FORGE_QOL.md. Cloud only - Mac check in LOKI_TASKS.
- **2026-10-21 night (Claude)**: In-View Editor + t, the full tool options, Mesh > Cleanup, the pro wireframe, camera based
  selection / backface culling / preselection highlight - docs/FORGE_PRO.md "DONE (Claude, 2026-10-21 night)". Cloud only.

- **2026-10-21 morning (Claude): UV Editing / Retopology / Baking workspaces** (docs/FORGE_UV.md): forge_uv.js (map UVs),
  forge_uv_editor.js, forge_retopo.js (Quad Draw), forge_bake.js; then the C++ UV core in native/sculpt (uv_unwrap.cpp:
  LSCM + ARAP unfold, shell packing; xatlas f700c77 vendored, MIT, its polygon input fixed - `ks_uv_unfold / ks_uv_layout /
  ks_uv_auto`, worker uvUnfold / uvLayout / uvAuto, ready.ops), and UVgami's seam logic ported (app/ui/forge_uvgami.js,
  GPL-3.0, docs/FORGE_UVGAMI.md): UV Editor > Smart (seams + unfold + straighten + layout), Atlas (xatlas), Seams.
  sculpt.wasm 924 KB (build ~1.5 min). Cloud only.

- **2026-10-21 10:20 (Claude): the layout system + menus your way** - forge_dock.js (dock / float / close every panel,
  top-bottom docks for vertical monitors, per-workspace + per-screen-shape layouts, named layouts, interface size, bar
  grips, Channel Box column folds), forge_menus.js (tear-offs, Quick Menu Alt+Q, Menu Settings + marking menu editor),
  Workspace: Materials, C++ Reduce (ks_decimate), no page scroll bar (glass.css margin collapse). Cloud only
  (test_forge_dock_ui 22, test_forge_menus_ui 16). Research: docs/FORGE_QOL.md "Second pass".

- **2026-10-21 13:40 (Claude): the owner's bug batch** - Multi-Cut the pro way (forge_multicut.js), soft / hard edges +
  normal display (forge_normals.js), smooth preview never stale, Workspace: Animation (time / range sliders, keys, Graph
  Editor; Modeling is clean), Preferences in Windows > Settings/Preferences (no cog), marking-menu list above the ring near
  the bottom (fixed test_forge_pro_ui's 3 failures). Cloud only: test_forge_mcut_ui 22, test_forge_pro_ui 100.

- **2026-10-21 14:40 (Claude): sculpt mode redone** (docs/FORGE_SCULPT_UI.md, forge_sculpt_ui.js): header with Done,
  sliders, brush strip, right-button brush wheel, every way out of sculpt mode. Cloud only (test_forge_sculpt_ui 25).

- **2026-10-21 22:40 (Claude): Home tidied + sculpt masking** - ui_tidy.js (one place per button, no logo / "Loki" title,
  word filters, resizable sidebar and preview), forge_sculpt_mask.js (mask paint / invert / clear / hide, C++ host-dirty fix),
  brush hotkeys + reorder, a layout pass so nothing overlaps (test_ui_spacing). Cloud only.

- **2026-10-22 00:30 (Claude)**: start-up (stale background engine restarted before attaching; pre-flight cached + done
  ahead), C++ soft/hard normals in the worker, topology cache + typed one-ring (edits ~2x faster on big cages), Workspace:
  Sculpting, Home > Content (brand/), 4 [loki] brand / marketing jobs queued, BUILD_BRIEF 5.11 (LOKI markets what it
  makes). Cloud only.

### Phone
- The pairing QR is a link `http://<computer>:<phone port>/#loki-phone:...`; the phone link serves LOKI's own chat
  page (app/ui/phone_web.html/.js, pure-JS HMAC) plus an internet link through the relay (LOKI_PHONE_RELAY=off).
  Ask/Plan only. Phone requests carry a signed nonce. Cloud: test_phone_web 18, test_phone_link 81.
- The native app (mobile/, Expo) typechecks and prebuilds on the Mac; never run on a phone (needs Xcode +
  CocoaPods + an iPhone). mobile/INSTALL_PHONE.md has Android (Expo cloud build) and iPhone steps.
- **Not verified:** any real phone on the owner's Wi-Fi or mobile data.

### Packaging, installers, updates
- Git installs update themselves from `master` at start (engine/updater.py), health-gated, pre-flight in a
  throwaway worktree; edits to tracked files are carried across (refs/loki/backup/*).
- Installers (session 30): bundled python-build-standalone runtime (tools/bundle_runtime.py), Rust launcher
  (packaging/launcher/), Inno Setup (packaging/windows/loki.iss), dmg (tools/macos/make_dmg.sh), portable/friends zips
  (tools/make_release.py), secret scan on every build, `.github/workflows/installers.yml`. Release updates need a
  SIGNED feed (engine/release_update.py, DEFAULT_FEED = GitHub Releases latest). uninstall.bat / uninstall.sh (8a2e1f4).
- Packaged Windows Loki.exe self-test fixed (packaging/loki.spec ships studio/, 95f5d5e - was
  "ModuleNotFoundError: No module named 'studio_godot'").
- **Not verified:** the Installers workflow has never been run; no installer has been installed on a clean account.
  No release signing key exists yet, so a release would be unsigned and installed copies would refuse to update.

### Cross-machine link
- Linked through LOKI's built-in relay (bore.pub) since 2026-10-16; one link code links both ways. Peer and phone
  requests carry `X-Loki-Nonce` (the "replayed request" HTTP 401 flapping is fixed). `/peers/diagnose` and
  `/peers/restart` work (diagnose verified PC -> Mac, redacted).
- It still drops at times: 2026-10-18 the Mac saw "cannot reach pc at http://127.0.0.1:49952 ([Errno 54] Connection
  reset by peer)" while the PC was down; later the same day M53 saw it live (3.3 s, both on d65ecfc).
- Shared over the link: memory (engine/memory_sync.py), automations, apps, background jobs (the worker farm).
  None of the two-machine flows (memory, automations, apps sync, Update everything) has been checked live.

## Open problems (still open as of c132c1f)

1. **The PC's engine was not answering** at 2026-10-19 04:04 ("LOKI's engine is not answering", attempt 6, v0.16
   patch 324, "update waiting", Godot tab "No Godot editor is linked"). Not looked at on the PC yet (LOKI_TASKS).
2. **No release signing key** - Needs Mohamed (docs/INSTALL.md "Signing"); blocks the first v* release.
3. **COEP in the real webviews**: whether Mermaid/Preview/Apps/Play/Studio frames show in WebView2 and
   WKWebView (Safari's COEP is stricter) after ecf9b40 is unknown.
4. **Mac computer use**: Accessibility + Screen Recording are not granted ("screencapture failed - give the app
   running LOKI Screen Recording permission"); the open_app-activate / never-type-into-LOKI fix (0d544bf) is
   tested only with the fake desktop.
5. **Forge**: bevel / loop cut / knife not done (the GoBuild bevel port left the mesh non-closed where three
   selected edges meet - removed, not shipped); extrude of loose verts/edges; commit after a move on 50k+ faces
   takes ~0.7 s (software GL); a sculpt stroke is not in the construction history (FORGE_PRO.md T6c).
6. **Small local models pick the wrong tool** (the Mac's qwen3.5-9b answered "draw an arrow on my pad" with
   computer use; a cloud model drew it first try). Model choice, not a missing tool.
7. **Mac recall is keyword-only** - no embedding model in Ollama ("no embedding model installed in Ollama").
8. Unexplained (2026-10-17, Mac): the second turn of a chat reported provider vireonix with prefer=local.
9. Not real failures but noise: test_studio / test_studio_godot fail ONLY on the cloud stubs (no mcp>=2
    MCPServer/Client there); the Mac has a stale legacy `harness_data/app/update_health.json`, a re-saved
    and a few `*.before-update` files (gitignored) - harmless.
10. Accounts not connected (Needs Mohamed in LOKI_TASKS.md): Telegram, email/calendar, Mistral/Together/Cerebras
    keys rejected, DeepSeek out of credit, ModelScope, Higgsfield, Home Assistant.

## Next, in order

1. PC: restart LOKI so it takes the waiting update (it was blocked by 4 edited game/loki-world files - set aside
   2026-10-21 10:10, the updater now handles that case); if the engine still does not answer, read the last 40 lines of
   harness_data/app/loki_bridge.log. Then Godot tab > a project in LOKI Projects > Open in Godot (agents linked again).
2. Both machines: the new Home in the real window (cards, open from a card, Studio inside Home) - LOKI_TASKS.
3. Check the COEP frames in the real windows on both machines.
4. Mohamed: the release signing key; then run the Installers workflow and install on a clean account per OS.
5. Real models through the task bench on the PC (`tools/task_bench.py --model local|bonsai|smart`) - the owner's
   #1 core system; the failures it finds are the next engine fixes.
6. The Render Studio writes harness_data/renders/<job>/manifest.json so its renders show on Home.
7. Forge: loop cut + bevel on `P.topology` / `P.edgeRing` (app/ui/forge_poly.js), then T6c.
8. Let LOKI's own evolve loop do E15, E14, E12 (docs/EVOLVE.md; E13 done in 2ddc73d) - watch, do not write them.
9. After Mohamed's macOS grants: re-run computer use on the Mac (TextEdit) and the PC (Notepad).

## Where to look

- Owner's direction: docs/BUILD_BRIEF.md. Architecture: docs/ARCHITECTURE.md. Roadmap LOKI builds itself: docs/EVOLVE.md.
- Live Godot: docs/LIVE_GODOT.md. Forge pro: docs/FORGE_PRO.md. Studio: docs/STUDIO.md. Home: app/ui/home.js, engine/home_projects.py.
- Installers: docs/INSTALL.md, docs/TESTERS.md, docs/SPEED.md. Phone: docs/PHONE.md, mobile/INSTALL_PHONE.md.
- Off-network link: docs/operations/OFF_NETWORK.md. Session log: docs/operations/SESSION_LOG.md.
- Full history: docs/operations/archive/HANDOFF_until_2026-10-19.md.

## Session 28 tools, connectors, computer use (worktree)

- **Connectors:** email, calendar, GitHub, notes and peer files (`engine/connectors.py`, `engine/conn_*.py`).
  Writes always ask the owner (`policy.ACTION_ALWAYS_ASK`).
- **Computer use:** `engine/computer_use.py` and `engine/computer_backends.py`. It never acts on LOKI itself. See
  docs/integrations/COMPUTER_USE.md.
- **Tool health map:** `engine/tool_health.py` and Settings > Tools (`app/ui/tools_panel.js`). Dead tools are hidden
  from the model and come with a one-click fix.
- **Driving LOKI from outside (2026-10-25):** `engine/loki_mcp.py` has `chat` / `task` / `agent_status` /
  `workspace_files` / `workspace_read`. Start it with `tools/loki_mcp_launch.sh` (Windows: `.cmd`). See
  docs/LOKI_MCP.md "Drive LOKI from Claude".
