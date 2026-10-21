# HANDOFF - where LOKI stands right now

Read this, AGENTS.md and docs/BUILD_BRIEF.md before working (Ziva: ZIVA.md and ZIVA_TASKS.md too).

**How to use this file.** It is the CURRENT picture, not a diary. When you ship something significant
(tools/ship.py), edit the area it changed under "Current state", tick or remove what you fixed under "Open
problems", and move "Next" along - in place, in a few lines. Long write-ups go in the commit message,
docs/operations/SESSION_LOG.md or a doc of their own. Every session entry up to 2026-10-19 04:10 (sessions 13-30
and all dated entries, with their full test lists) is kept verbatim in
**docs/operations/archive/HANDOFF_until_2026-10-19.md** - search it for the history of anything below.
"Verified" below means seen on a real machine (the Mac mini or the PC); "cloud" means checked only on Claude's
Linux box (headless Chromium, stubs, headless Godot).

Last updated: 2026-10-21 (Forge: undo for the scene, hotkey table, pro manipulator, Creature Editor, smoother sculpting).

## The machines

| | Mac mini (M4, 16 GB) | Windows PC (RTX 3070 Ti, on 24/7) |
| --- | --- | --- |
| Checkout | `~/Documents/loki` -> `/Volumes/LokiSSD/loki` (APFS sparse image on the 2 TB SSD; login item `sh.loki.attach-image` reattaches it) | `C:\Users\macul\Documents\loki` |
| Python | `harness_data/.venv/bin/python` | `harness_data\.venv\Scripts\python.exe` |
| Ziva | works on Forge (pro roadmap) since 2026-10-19 | did W50-W52 on 2026-10-18 |
| Godot | LOKI's own 4.7.2 for LOKI World; Godot_mono 4.8 dev is Ziva's - never open game/loki-world in it | LOKI's own 4.7.2 (`harness_data\addons\godot-export\editor\Godot_v4.7.2-stable_win64.exe`); never `Godot_v4.8-beta1_mono` / ai_testin |

The repo is PUBLIC and AGPL-3.0 since 2026-10-17 (W43, 910dab2). Branch `master` only; `macos-app` is a mirror
ship.py keeps in step. CI (`.github/workflows/tests.yml`, macOS + Windows) runs again since the repo went public.

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

### App window and tabs (incl. Spaces)
- Six title-bar tabs (app/ui/modebar.js MODES): LOKI / Studio / Godot / World / Forge / Spaces, Ctrl/Cmd+1..6
  (Ctrl works on macOS too). Ctrl+<n> is re-raised from inside the World game frame (world_godot/host.js).
- **Windows:** frameless, LOKI's strip is the title bar with its own min/max/close, Aero snap via WM_NCLBUTTONDOWN
  (app/loki_app.py win_hit) - **verified on the PC** (W50, docs/operations/screens/w50-titlebar.png).
  **macOS:** pywebview frameless full-size transparent title bar with the traffic lights (68b9469) - cloud
  (test_ui_fit runs pywebview's real customize.js); no report from the real Mac since.
- **Home** = the live LOKI World (the Godot web build, same frame as the World tab), only in LOKI's own window
  (`worldbg=1`) - **verified on the PC** (W52, w52-home-world.png).
- **Cross-origin isolation:** the UI is COOP same-origin + COEP require-corp (04def98, for the in-window Godot web
  editor); every bridge answer adds COEP + CORP cross-origin (loki_bridge.py COI_HEADERS, ecf9b40) so Mermaid,
  Preview, LOKI Apps, Play and the Studio tab frame again. Cloud only (test_research3 154, test_apps 131) -
  **not checked in WebView2 / WKWebView**.
- **Spaces** (engine/spaces.py, spaces_api.py, app/ui/spaces.js/.css, docs/SPACES.md): your own peer-to-peer
  Discord. The machine that makes a space hosts it (harness_data/spaces/, port 8795 + the bore relay); HMAC-signed
  requests, AES-GCM-sealed messages and WebRTC signals; text/voice rooms, lobbies, roles. Full-window tab since
  d04c132 (rail | rooms | room | members; a call keeps a pill on other tabs). Cloud: test_spaces 33,
  test_spaces_ui 16 (a real WebRTC call with Chromium's fake mic). **Not verified:** the mic inside
  WKWebView/WebView2, two real machines over the relay, the Godot side.
- Background mode: closing the window keeps LOKI running; it starts hidden at login (Startup LOKI.vbs /
  LaunchAgent). The stray Startup `Loki.lnk` -> Loki.cmd that opened a console at every logon is removed by
  `retire_console_launchers()` (847a78b).
- Health-gated updates: a version must pass `app/loki_app.py --self-test`, have every window file and post
  `/ui/ready`, else it is rolled back and skipped (`.git/loki_update_health.json`).

### Studio
- A tab (Studio's own server started headless, `POST /studio/embed`), runs a pinned known-good copy
  (harness_data/studio/pin.json). Kill loop fixed (`studio_api.good_codes()` = pin + HEAD, restart at most once per
  10 min); the flaky pacing check that froze the pin is fixed (tests/test_studio.py window 3 s, a3e1b64); the stale
  pinned copy on the PC was removed (W52). Local driver uses an installed model (`studio_models.local_model()`).
- LOKI Studio Godot plugin 1.2 (studio/godot_plugin/addons/loki_studio/) links to both Studio and the engine; dock
  shows "LOKI: linked / not linked". **Verified on the PC** (W51: "LOKI Studio plugin 1.2 ready").
- Not verified: a real model driving a Studio session on NVIDIA; the 15-task parity benchmark vs Ziva
  (docs/STUDIO_VS_ZIVA.md); `gh repo fork/create` destinations.

### Godot / LOKI World live link
- LOKI World is ONLY the Godot 4 project `game/loki-world/` (all JS/Babylon/three.js worlds and the JS MMO were
  deleted in 0e2af40). scenes/main.tscn + scenes/home_island.tscn are real editable scenes (9b160a0).
- The web build is committed in app/ui/world_godot/ (index.wasm.gz, served gzip) and plays in the World tab and on
  home; "Rebuild the World tab" exports with LOKI's own Godot 4.7.2 (engine/world_build.py).
- engine/godot_live.py hosts the editor link (`/api/godot/*`, `~/.loki/engine_connect.json`); every agent has
  `godot_editor`; Asset Library plugins via install_plugin recorded in game/loki-world/plugins.json (docs/LIVE_GODOT.md).
- **Verified on the PC:** Open in Godot downloads + opens LOKI's 4.7.2 on "main.tscn - LOKI World" (W50); the
  live link shows the editor and agent actions (W51). Godot tab no longer says "not installed" (godot_web.status()
  falls back to loki_godot()). Game tests 118/0, test_godot_world 97/0 on the PC (d65ecfc).
- Ziva added an Auto Chess prototype to the MMO HUD (79a1318, d5223d8 - game/loki-world/scripts/autochess/). The MMO
  is parked per ZIVA.md ("core systems first").
- **Not verified on the Mac:** downloading the macOS 4.7.2 editor, Open in Godot, the live link, Rebuild World.

### Forge
- app/ui/forge*.js: draw / picture / describe -> 3D (engine/forge3d.py: TripoSR -> TRELLIS Space -> offline lift),
  SculptGL-ported sculpting, Material Maker nodes, primitives + poly ops + DynaMesh (GoBuild port, GPL-3.0),
  Blender-style component editing (forge_edit.js: vert/edge/face, box select, G/R/S, proportional), Quad view.
- **pro layer** (forge_pro.js, forge_scene.js; docs/FORGE_PRO.md): marking menus, hotbox, hotkeys, Alt camera;
  T1 scene, T2 Outliner, T3 Group/Ungroup, T4 Channel Box, T4b Freeze/Center Pivot, T5 Shift+drag duplicate,
  T6 construction history for poly ops + DynaMesh (c132c1f, test_forge_ui 62/62). Ziva (Mac) owns this.
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
  Not verified on a real machine yet (ZIVA_TASKS M-F1 / W-2). Next: FORGE_PRO.md T7-T12.
- **2026-10-19 evening (Claude), owner 17:06:** no product/vendor names anywhere (files renamed: forge_pro.js,
  forge_chrome.js, test_forge_pro_ui.py, docs/FORGE_PRO*.md; identifiers forgePro*/view.pro). Forge's own camera
  controller (`forgeProCamera`: Alt tumble / track / dolly, Shift lock, Ctrl box dolly, wheel; OrbitControls keeps
  only the target). Right button = hold-only marking menu, opens on press, quick click does nothing; empty space =
  Complete Tool / Select All / Undo ... list. Space = hotbox centred on the mouse (Ziva's wheel: Windows > Radial
  Menus). Modern high-contrast theme + one 20 px menu style (end of forge.css), picture at 1.5-3x pixel ratio, shelf
  hidden by default. Component display light-blue / orange / purple; the object wire follows edits via
  `view.frameHooks` (the "weird wireframes after moving an edge" were the stale wire of the old shape). Insert Edge
  Loop restored (Ziva's 8086bf2 had removed it). Checked: test_forge_pro_ui 99 (44 s), test_forge_ui 37,
  test_forge_edit_ui 21, test_forge_model_ui 14, creature 8, poly 32, ui_fit 81, ui_smoke 10, studio_destination 81.
  Next: ZIVA_TASKS "From Claude (2026-10-19 evening)" - real-screen check, then Combine/Separate/Mirror/Merge.

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
  Cloud-checked (see SESSION_LOG); **not verified** in WKWebView / WebView2 - ZIVA_TASKS "From Claude (2026-10-21)".
  The owner's Maya sculpting plug-in source was not reachable from this session (not in ~/Documents, ~/Downloads or
  GitHub); ByHand is Windows-only and was not on the Mac.

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
- Shared over the link: memory (engine/memory_sync.py), automations, apps, MMO profile, Spaces (own port 8795).
  None of the two-machine flows (memory, automations, apps sync, Update everything) has been checked live.

## Open problems (still open as of c132c1f)

1. **The PC's engine was not answering** at 2026-10-19 04:04 ("LOKI's engine is not answering", attempt 6, v0.16
   patch 324, "update waiting", Godot tab "No Godot editor is linked"). Not looked at on the PC yet (ZIVA_TASKS).
2. **No release signing key** - Needs Mohamed (docs/INSTALL.md "Signing"); blocks the first v* release.
3. **COEP in the real webviews**: whether Mermaid/Preview/Apps/Play/Studio tab frames show in WebView2 and
   WKWebView (Safari's COEP is stricter) after ecf9b40 is unknown.
4. **Spaces mic** inside pywebview (may need the OS microphone permission; macOS Loki.app needs
   NSMicrophoneUsageDescription - tools/macos/make_loki_app.sh) and Spaces across two real machines.
5. **Mac computer use**: Accessibility + Screen Recording are not granted ("screencapture failed - give the app
   running LOKI Screen Recording permission"); the open_app-activate / never-type-into-LOKI fix (0d544bf) is
   tested only with the fake desktop.
6. **Forge**: bevel / loop cut / knife not done (the GoBuild bevel port left the mesh non-closed where three
   selected edges meet - removed, not shipped); extrude of loose verts/edges; commit after a move on 50k+ faces
   takes ~0.7 s (software GL); a sculpt stroke is not in the construction history (FORGE_PRO.md T6c).
7. **Small local models pick the wrong tool** (the Mac's qwen3.5-9b answered "draw an arrow on my pad" with
   computer use; a cloud model drew it first try). Model choice, not a missing tool.
8. **Mac recall is keyword-only** - no embedding model in Ollama ("no embedding model installed in Ollama").
9. Unexplained (2026-10-17, Mac): the second turn of a chat reported provider vireonix with prefer=local.
10. Not real failures but noise: test_studio / test_studio_godot fail ONLY on the cloud stubs (no mcp>=2
    MCPServer/Client there); the Mac has a stale legacy `harness_data/app/update_health.json`, a re-saved
    game/loki-world/project.godot and 5 `app/ui/world_godot/*.before-update` (now gitignored) - harmless.
11. Accounts not connected (Needs Mohamed in ZIVA_TASKS.md): Telegram, email/calendar, Mistral/Together/Cerebras
    keys rejected, DeepSeek out of credit, ModelScope, Higgsfield, Home Assistant.

## Next, in order

1. PC: restart LOKI so it takes the waiting update; if the engine still does not answer, read the last 40 lines of
   harness_data/app/loki_bridge.log. Then Godot tab > Open LOKI World in Godot so the agents are linked again.
2. Mac: the same LOKI World loop (Open in Godot with LOKI's macOS 4.7.2, live link, World tab, Rebuild World).
3. Check the COEP frames and the Spaces tab (two machines, voice) in the real windows on both machines.
4. Mohamed: the release signing key; then run the Installers workflow and install on a clean account per OS.
5. Real models through the task bench on the PC (`tools/task_bench.py --model local|bonsai|smart`) - the owner's
   #1 core system; the failures it finds are the next engine fixes.
6. Spaces in LOKI World (Godot side): poll `GET /spaces/world`, draw lobbies/voice rooms as campfires, join via
   `postMessage({lokiSpaces: "join", space, room})` (docs/SPACES.md "LOKI World").
7. Forge: loop cut + bevel on `P.topology` / `P.edgeRing` (app/ui/forge_poly.js), then T6c.
8. Let LOKI's own evolve loop do E15, E14, E12 (docs/EVOLVE.md; E13 done in 2ddc73d) - watch, do not write them.
9. After Mohamed's macOS grants: re-run computer use on the Mac (TextEdit) and the PC (Notepad).

## Where to look

- Owner's direction: docs/BUILD_BRIEF.md. Architecture: docs/ARCHITECTURE.md. Roadmap LOKI builds itself: docs/EVOLVE.md.
- Live Godot: docs/LIVE_GODOT.md. Spaces: docs/SPACES.md. Forge pro: docs/FORGE_PRO.md. Studio: docs/STUDIO.md.
- Installers: docs/INSTALL.md, docs/TESTERS.md, docs/SPEED.md. Phone: docs/PHONE.md, mobile/INSTALL_PHONE.md.
- Off-network link: docs/operations/OFF_NETWORK.md. Session log: docs/operations/SESSION_LOG.md.
- Full history: docs/operations/archive/HANDOFF_until_2026-10-19.md.
