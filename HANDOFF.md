# HANDOFF - where LOKI stands right now

Read this, AGENTS.md and docs/BUILD_BRIEF.md before working. Update this file when you ship
something significant (tools/ship.py), so the next agent - Ziva, Claude Code, Codex or
LOKI itself - starts from the truth.

Last updated: 2026-10-18 (later) (W50 verified on the PC, Claude's changes checked, one fix, Ziva).

## 2026-10-18 20:20: no console windows on Windows, godot_editor reaches local models (Claude, cloud)

Owner on the PC: "the terminal keeps popping up on my screen". LOKI runs as pythonw, so every console program it
starts without CREATE_NO_WINDOW (git, nvidia-smi, ollama, python, Godot command-line runs, job tests) flashed a new
console. engine/no_console.py patches subprocess.Popen once per process so CREATE_NO_WINDOW is the default (a
detached process or an asked-for console is left alone; LOKI_SHOW_CONSOLES=1 turns it off); the engine (loki.py,
loki_bridge.py), every job, Studio (studio_server/studio_app) and the app (loki_app.py) load it first.
tests/test_no_console.py. Also from W50 (Ziva saw godot_editor fall off a local model's 22-tool list and relaxed the
test): a Godot-tab job (prompt names godot_editor -> LOKI_GODOT_LIVE=1) or a linked editor now ranks godot_editor
first for local models (loki._local_rank); test_godot_live 27.

## 2026-10-18 (later): W50 verified on the PC - title bar, Godot download, Open in Godot (Ziva, the PC)

W50 was the owner's check on the PC after 0e2af40, and "check everything we changed". Everything Claude changed
holds up on Windows. On a fresh start engine.out shows "getting LOKI's Godot 4.7.2 for LOKI World (one time,
~80-170 MB)" then "LOKI's Godot 4.7.2 is ready: ...\editor\Godot_v4.7.2-stable_win64.exe" (4.7.2.stable, 180 MB).
The window is frameless with the tabs centred and LOKI's own minimise / maximise / close in the corner: minimise
works, maximise settles to the work area so the taskbar stays (720x1232 on a 720x1280 screen), close quits the app
and the engine with it. Godot tab > LOKI World > Open in Godot opened Godot_v4.7.2-stable_win64 on "main.tscn -
LOKI World - Godot Engine" with the home island and the LOKI Studio dock; ai_testin (the 4.8 mono editor) was not
touched and project.godot kept "4.7" in config/features (opening only reformats it - that noise was reverted).
Walking all five modes (loki, studio, godot, world, forge) in the running app gave no console errors. Screenshots:
docs/operations/screens/w50-titlebar.png, w50-open-in-godot.png.

FIX SHIPPED: the Godot tab showed "Godot is not installed on this computer: get Godot 4.7 from godotengine.org (or
set GODOT_BIN)" while its own live link said "Godot 4.7.2 - LOKI World - editing res://scenes/main.tscn" - a
contradiction the owner would read as "broken". /godot-editor/status returned native:"" because native_godot()
only looks at GODOT_BIN/GODOT_EXE, PATH and the usual install places, never LOKI's own download. engine/godot_web.py
status() now uses native_godot() or loki_godot(); regression test in tests/test_godot_world.py (85 passed).

FIX 2 (regression from 0e2af40): opening the World tab killed LOKI's own keyboard shortcuts. The World panel
is the Godot web build in an iframe now, and host.js focuses that frame when the panel opens ("keys go to the
game") - a focused frame swallows every key, so Ctrl+1..5 did nothing until you clicked LOKI's chrome again
(tests/test_studio_destination.py caught it: after Ctrl+4 World, Ctrl+5 never switched to Forge). host.js now
re-raises Ctrl+<number> from inside the frame onto LOKI's own document (same-origin, capture, preventDefault in the
game) so the mode bar still switches while the game has focus. Also: that suite's "no script errors" was flaky
because the stubbed server makes the Godot shell's audio worklets fail to load (the real app logs no such error) -
that one message is ignored now.

FIX 3 (Windows-only): extensions.install's git-clone path left a .git behind on Windows - git writes its
object files read-only and rmtree(ignore_errors=True) silently kept them (tests/test_apps.py "git clone path:
shallow, no .git left behind" failed). engine/extensions.py now clears the read-only bit and retries (_rmtree);
test_apps 114 passed.

(test_godot_live's "every agent has the godot_editor tool" was flaky under ship: it asserted the tool
was OFFERED right now, but a local model trims the offered list to 22 tools. It asserts the wiring now
(LOCAL_TOOLS + MODEL_TOOL_NAMES + a schema) and reports whether it is offered, instead of failing on which model
is active.)

Suites: test_godot_live 26, test_godot_tab 9, test_world_godot_tab 7, test_channels 145, test_godot_world 85; full
`ship.py --check` was green on the real install.


## 2026-10-18 19:40: Windows title bar, Open in Godot on the PC, LOKI World = the Godot game only (Claude, cloud + PC)

Owner (on the PC): "the tabs are floating here ... opening the godot project takes me to a completely different
project ... where is loki world, i said make it in godot, if it's in code delete it".
- Windows title bar: the window is frameless (like the Mac) and LOKI's strip IS the title bar - tabs centred, LOKI's
  own minimise / maximise / close in the corner, thin edge handles. Presses on the empty strip / edges go to Windows'
  own move/resize (WM_NCLBUTTONDOWN, app/loki_app.py win_hit, on the form's UI thread) - Aero snap works; maximise
  respects the taskbar. LOKI_TITLEBAR=native keeps the system frame. place.js reads titlebar=win.
- The PC never had LOKI's Godot 4.7.2 (no harness_data/addons/godot-export), Godot is not on PATH there, and the only
  Godot on screen was Ziva's Godot_v4.8-beta1_mono on Documents/ai-testin - that was the "different project".
  Now: the engine fetches LOKI's Godot 4.7.2 (editor only) in the background at start (godot_web.prefetch, logged;
  LOKI_GODOT_PREFETCH=off), Open in Godot shows the download and opens LOKI World when ready, and LOKI World NEVER
  opens in another Godot (a failed download is an error, not a fallback). GODOT_EXE defaults to LOKI's Godot.
  Godot's project list on the PC (AppData/Roaming/Godot/projects.cfg) now lists LOKI World instead of ai-testin.
- Deleted the code-drawn worlds: world.js's WebGL island, world_babylon.js + vendor/babylon (2.9 MB), world_three.js,
  world_noise.js, the JS MMO (app/ui/mmo), the JS character creator (character.js), the home-screen background world
  and the LOKI_WORLD / LOKI_WORLD_ENGINE settings. world.js only hosts the Godot game's web build (World tab, Settings >
  LOKI World) with the agent list; without a build it points at the Godot tab. vendor/three stays (Forge uses it).
Checked: test_ui_fit 81 (a Windows strip run), test_godot_live 26, test_world_godot_tab 7, test_portal 203,
test_godot_world 84, test_character 30, test_mmo 66, test_play 27, test_loki 533, other UI suites, --self-test OK.
Not checked yet: the frameless window on the real PC (WinForms + WebView2).

## 2026-10-18 16:30: frames show again in the cross-origin isolated window (Claude, cloud)

04def98 (Ziva) made the window COEP require-corp so the Godot editor runs in-window; every framed page without COEP
went blank (chat Mermaid diagrams, Preview, LOKI Apps, Play, the Studio tab) and opaque-origin frames could not load
/ui/vendor (CORP same-origin). Now engine/loki_bridge.py BridgeHandler.end_headers adds COEP require-corp + CORP
cross-origin to every answer that sets none (COI_HEADERS), UI files send CORP cross-origin, studio/studio_server.py
sends both. The preview pane starts under the title strip (its Close button was covered). Checked: test_research3 154,
test_apps 131, test_godot_world 83, all other suites on stubs. Not run: WebView2 / WKWebView (ZIVA_TASKS requests).

## 2026-10-18 13:30: LOKI World is a real, editable scene in Godot (Claude, cloud + Mac files)

Owner: "it takes me to a different godot project entirely nothing works". On the Mac, Godot DID open game/loki-world
(recent files: main.tscn; the plugin set the live-sync flags) - but main.tscn was one empty Node and the island was
built by code at runtime, so the editor showed nothing. And Godot_mono 4.8 dev rewrote project.godot as 4.8 + [dotnet].
- scenes/main.tscn now holds WorldView > World3D > World (world.gd) > HomeIsland; scenes/home_island.tscn is the island
  as named pieces (scripts/world/home_builder.gd, baked by tools/bake_world.gd, 240 nodes, ~930 KB, 5 shared materials).
  world.gd uses the scene's island (paintings, shelf spots and stations found by group, so moving them in the editor
  works), building from code only when the scene is missing. main.gd sets the mode in _enter_tree (the World readies
  first now).
- Open in Godot uses LOKI's own standard Godot 4.7.2 (world_build's, downloaded in the background on first Open, then
  opened) - LOKI_GODOT_EDITOR=system for the computer's Godot. The engine logs "Godot x linked: <project>".
- The character creator no longer opens behind the World tab's game frame.
- Checked: a REAL Godot 4.7.2 editor in a window (Xvfb) shows the island in its 3D view; game tests 118/118 (scene's
  island, move a station -> agents follow); test_godot_live 34 (the live editor's tree has World/HomeIsland; first Open
  downloads then opens), test_godot_world 94, test_world_godot_tab 7, test_godot_tab 9, test_world_build 17,
  test_ui_smoke, test_character 54, test_mmo 77, test_loki 533, --self-test OK. Not on the Mac yet: the download of
  the macOS 4.7.2 editor and opening it there.

## 2026-10-18 12:30: LOKI World live in the real Godot editor - every LOKI agent works in it (Claude, cloud)

Owner: "the loki world [should] be an editable project in godot ... agents ... roam around in a live project state,
change everything ... the web godot is of no help to us, we want the godot and the assetstore and all the plugins".
docs/LIVE_GODOT.md has the design. Done:
- engine/godot_live.py: LOKI's engine hosts the editor link (Studio's GodotHub, same routes /api/godot/*), writes
  ~/.loki/engine_connect.json at start; tool **godot_editor** for every agent (chat, jobs over loopback, teams) with all
  plugin actions + plugins/install_plugin; Plan mode reads only; each action -> ACTIVITY -> /world puts the agent at the
  new **godot forge** station (LOKI World, 160°) saying what it did.
- The LOKI Studio plugin (1.1) links to BOTH Studio and the engine (two bridges, one debugger with per-link reply ids,
  per-link error cursor) and turns on Synchronize Scene/Script Changes so the game run from the editor changes live.
- LOKI World's project.godot enables the plugin + its game helper (committed); ensure_world copies the plugin in at
  engine start / open / export (only when it changed); addons/ untracked; Asset Library plugins via install_plugin
  (pinned commit, only addons/<name>/, hash checked when given) recorded in game/loki-world/plugins.json and synced on
  every machine.
- Godot tab rebuilt for the Godot app: LOKI World first, Open in Godot, live link (editor, scene, playing), what each
  agent does in the editor, "Send to the agents", plugins + Add plugin by Asset Library number. Web editor removed from
  the tab. The World tab's web copy keeps "Rebuild the World tab" (deterministic gzip now - no 10 MB churn).
- Checked with the REAL Godot 4.7.2 editor (headless): test_godot_live 29/29 - the editor links to the engine AND to a
  Studio hub at once; an agent reads it, opens main.tscn, adds a node, sets a property, saves (on disk), stands at the
  forge; live-sync flags set. test_godot_tab 9/9 (Chromium), test_godot_world 93, test_world_build 17, test_loki 533,
  test_tools_core 218, test_ui_fit 76, test_systems 101, --self-test OK. Not run on the Mac: the plugin in Godot 4.8 mono
  with a window, run_game live sync with a real window, an Asset Library install over the network.

## 2026-10-18 04:20: LOKI World IS the Godot game, and one loop from the Godot editor to the World tab (Claude, cloud)

Owner: "loki world wasnt build in godot where is it ... how are we going to incorporate into godot editor ... they feel like
separate pieces". The Godot MMO (game/loki-world, 26 scripts, 107 tests) existed but was never exported, so the World tab
silently ran the Babylon.js world (and a second, JavaScript MMO behind its "Join world").
- **Exported and committed**: app/ui/world_godot/ (Godot 4.7.2 web, no threads; index.wasm kept gzipped - 39 MB -> 10 MB in
  git - and served with Content-Encoding: gzip by engine/loki_bridge.py). The World tab plays it (World.game="godot",
  default LOKI_WORLD_ENGINE=godot), loaded only when the tab / Settings > LOKI World opens; behind the home screen the light
  Babylon island stays (startup unchanged). No build -> the light world plays.
- **Bugs fixed on the way**: host.js removed the running game 12 s after EVERY start (its "nothing said" timer ignored a good
  start); LokiApi's 3 s first /health timed out while the 39 MB engine started -> the made-up demo world although LOKI was
  there (now 12 s + one retry on the page's own origin; one connect at a time); app.js started the World only if models,
  mode AND chats all loaded (Promise.all -> allSettled); the game's tests read the player's saved profile (now isolated).
- **Godot editor -> World tab**: engine/world_build.py + GET/POST /world/build + "Rebuild World" in the Godot tab (LOKI World
  is picked first there). LOKI keeps its own standard Godot 4.7.2 (a C#/mono Godot - the Mac's 4.8 dev mono - cannot export
  to the web) in <data>/addons/godot-export: the editor SHA-512 checked, only the 10 MB web template range-read out of the
  1.3 GB template pack (SHA-512 pinned), a private Godot data folder (the owner's is never touched). 15 s from nothing on Linux.
- The Godot web editor in the Godot tab is now 4.7.2 too (4.4.1 could not open a 4.7 project); installed + checked here.
- **Forge -> LOKI World**: the Forge shelf - three pedestals in front of the creations hall show the newest Forge models
  (GET /forge/list, the .glb loaded at runtime with GLTFDocument, ~1 m, turning, named). Character: the creator opens the
  first time the World tab is clicked and saves to /mmo/profile, which the game uses - one character.
- Checked: game tests 113/113 (Godot 4.7.2 headless), test_godot_world 86 (incl. the real Godot run), test_world_build 16,
  test_world_godot_tab 6 (the real build in Chromium in the World tab), test_ui_smoke 10, test_ui_fit 76, test_portal 239,
  test_forge_ui 20, test_forge_model_ui 13, test_character 54, test_mmo 77, test_mmo_systems 125, test_studio_destination 81,
  test_files_ui 15, test_loki 533, --self-test OK. In a browser through the real engine: connected, live machine name and
  profile, /forge/file/<model>.glb fetched. The engine serves the NEWER of index.wasm / index.wasm.gz (the Mac had
  an older local export from Ziva; the update sets its clashing files aside as *.before-update). Not run on the Mac: the
  World tab there, Rebuild World with the macOS editor.

## 2026-10-18 03:25: NVIDIA answers instead of timing out - streamed replies (Claude, Mac logs + cloud)

After the 02:40 fix Studio DID reach NVIDIA with the owner's key (session 1018-025513: "nvidia did not answer (The read
operation timed out)"), but every turn waited 180 s, retried another 180 s, fell back - and the next turn started on
NVIDIA again. Cause: Studio and the engine asked for up to 8192 tokens UNSTREAMED, so the server sends nothing until
the whole answer is written, which on the free tier takes longer than the timeout.
- Studio (studio/studio_models.py): remote providers stream (SSE); the timeout is the first byte (FIRST_BYTE_S 90) then
  the silence between chunks (STREAM_IDLE_S 75), wall cap 900 s; tool calls are rebuilt from deltas; a provider that
  times out is not retried on that turn and is asked LAST for 10 min (SLOW_FOR_S). Local servers stay unstreamed.
- Engine (engine/loki.py `_streamed_request`): DeepSeek on NIM streams (LOKI_STREAM_MODELS=auto|remote|off) and is
  rebuilt into the shape the loop reads (content, tool_calls, reasoning, usage, model_dump).
- A Studio on the cleared pin move but not the pin is a checkout run on old code, so it counts as stale and an update
  reaches it (good_codes = the pin + HEAD).
- Two Studios ran at once (8771 + 64148): a pinned copy LOKI stops on purpose (exit 15) no longer makes its launcher
  start the checkout too.
- Checked: test_studio_stream 10/10 (incl. a real chunked socket slower than the timeout overall), test_engine_stream
  12/12, test_loki 533, test_job_fixes 43, test_routing_core 142, test_hardening 135, test_keys_studio 30,
  test_studio_destination 81, --self-test OK. Not verified: a real NVIDIA turn (the key stays on the Mac).

## 2026-10-18 03:10: phone linking that opens on a phone, and 9Router (Claude, cloud + Mac logs)

Owner: "account linking needs rework qr dont show up on my phone and links dont go anywhere ... get 9router repo".
- **The phone-pairing QR was a bare `loki-phone:` code** that only the (unbuilt) phone app reads - a phone camera shows
  nothing for it. Now it is a link, http://<computer>:<phone port>/#loki-phone:..., and the phone link serves LOKI's chat
  page itself (app/ui/phone_web.html + .js, strict CSP, no secret in them; the code stays in the #fragment, which is
  never sent, and in that browser's storage as the derived signing key). Pure-JS SHA-256/HMAC because phone browsers give
  no WebCrypto to plain-http home addresses; requests are signed exactly like the app's. Ask/Plan only, as before. The
  pair response also carries an internet link via LOKI's relay (LOKI_PHONE_RELAY=off turns it off), kept while LOKI
  runs; "Pair a phone" no longer opens a prompt() and the QR window cycles home/internet links and copies the link.
- **Key hand-off page ("links don't go anywhere")**: it records a visit; when no phone reached the home link after 25 s
  and the relay link exists, the window switches the QR to the internet link itself. On a Mac the hint now reads the
  Application Firewall (socketfilterfw, read-only) and names "block all incoming" or a blocked Python.
- **9Router** (decolua/9router, MIT, 0.5.104 - past CVE-2026-62328, which hit <= 0.4.41): provider "9router" in
  MODELS/SMART_ORDER/Connections (key from its dashboard, model "loki" = a combo you name so, else the first it lists);
  `python tools/setup_extras.py 9router` installs it into harness_data/addons/9router; the engine starts it on 127.0.0.1
  only (its default is 0.0.0.0), --no-browser --skip-update. LOKI_9ROUTER=auto|on|off. Not run here (npm registry
  unreachable from the cloud) - first real run is on the Mac.
- Checked (cloud, stubs): test_phone_web 18/18 (headless Chromium chats through the real PhoneServer), test_ninerouter
  13/13, test_phone_link 81/81, test_qr_links 23/23, test_portal 239/239, test_routing_core 142/142, test_loki 533/533,
  --self-test OK. Not verified: a real phone on the owner's Wi-Fi, the relay link from mobile data, 9Router itself.

## 2026-10-18 02:40: Studio stops killing itself; Forge gets primitives, poly modelling and DynaMesh (Claude, Mac logs + cloud)

Owner: "nvidia key is set now but nothing is working ... the loki studio button is past the border ... i want to create
primitives dynamesh ... poly modeling, their godot plugin, take it".
- **Studio kill loop** (Mac studio.log 02:13-02:16: "the pinned copy exited at once (-15)" every ~25 s). The 01:45 fix
  restarted a stale Studio, but the fresh one came up in the old pinned copy (bb52bd6), which predates the "code" note in
  running.json -> stale at once -> killed; its fallback ran the checkout (6d68038 != pin) -> stale -> killed. Studio never
  lived the ~11 s it needs to move its pin, so it stayed on bb52bd6: qwen3:8b hard-wired and keys per checkout - your
  NVIDIA key (in ~/.loki/keys.env, present) was invisible to it. Now `studio_api.good_codes()` accepts the pin's move (or
  pin) AND the checkout's HEAD; a replaced Studio starts with `--no-pin` (current code, reports its commit, moves the pin
  itself); and a stale Studio is replaced at most once per 10 min (RESTART_EVERY_S). tests/test_keys_studio.py 29/29.
- **Sidebar icon row** fit: 6 icons x 36 px + gaps overflowed the 227 px sidebar; they now shrink (flex 0 1 36px, min 26).
- **Forge Model bar** (app/ui/forge_model.js, geometry in app/ui/forge_poly.js, pure JS): 7 primitives (cube, plane, UV
  sphere, quad sphere, cylinder, cone, torus) with live sliders; click picks faces (Shift adds); region Extrude, Inset,
  Catmull-Clark Smooth, Flip, Delete, all/none; the last Extrude/Inset keeps a live redo slider; DynaMesh (voxel parity on
  3 axes + Surface Nets -> all quads, closes holes) with Resolution/Relax sliders; undo covers all of it; Sculpt and Model
  take turns (sculpting drops the poly cage; DynaMesh gives quads back). Ops ported from GoBuild (GPL-3.0, licence at
  app/ui/forge_poly.GoBuild-LICENSE.txt, row in docs/THIRD_PARTY.md). Gator Model Studio is MIT but has no public source.
- Queued for LOKI's own self-improvement (docs/EVOLVE.md): E23 the rest of GoBuild (vertex/edge modes, bevel, loop cut,
  bridge, knife, UVs), E24 Dify (connector + LOKI's own workflow canvas - Dify's extra licence terms rule out copying
  its code into AGPL LOKI), E25 more of OpenHands (sandboxed runtime, microagents, eval harness).
- Checked (cloud, stubs): test_forge_poly 16/16, test_forge_model_ui 13/13 (headless Chromium, real click picks a face),
  test_forge_ui 20/20, test_ui_fit 76/76, test_ui_smoke 10/10, test_studio_destination 81/81, --self-test OK.
  Not verified on the real Mac: a Studio turn answering on NVIDIA after this lands (should, once the pin moves).

## 2026-10-18 01:45: keys that stay saved, a Studio that answers (Claude, on the Mac by computer use + cloud)

Owner: "none of the stuff is working its not calling any tools or responding ... why arnt my api keys saving i did the
nvidia key ... it needs to save per user". Found on the Mac:
- **Studio ran 9d1f8db for hours** (pid from 22:21): LOKI's Studio tab reuses a running Studio server forever, so no
  update ever reached it (its pin had already been cleared to move). Now Studio writes the commit it runs into
  running.json and `studio_api.embed` stops a Studio whose code is not `wanted_code()` (pin.next/pin, else HEAD) and
  starts a fresh one - never while a session is working (`busy()`).
- **Studio's local model was hard-wired to qwen3:8b**, never installed on the Mac -> every turn "model 'qwen3:8b' not
  found". `studio_models.local_model()` (shipped 3bdeef0) takes the engine's pick if installed, else an installed one.
- **The NVIDIA key was never on this Mac** (not in harness_data/.env or anywhere; Connections says Not connected).
  Keys were per-checkout files, so a key typed in another checkout/drive/machine looked "not saved". New
  `engine/user_keys.py`: every key also lives in ONE per-user file, ~/.loki/keys.env (%USERPROFILE%\.loki\keys.env,
  mode 600), loaded by the engine and Studio; Connect saves there, Disconnect (write_env with None) forgets there;
  existing .env keys are adopted once. Keys never leave the computer (no peer sync - the relay is not encrypted).
- **Connect threw a key away when the provider could not be reached** for the check; now it is saved ("could not check
  it just now"). Studio re-reads keys per request (`studio_paths.refresh_keys`), so no restart is needed.
- Suites get their own empty LOKI_USER_KEYS (tools/ship.py), so they never see the owner's keys.
- Checked: tests/test_keys_studio.py 25/25, test_portal 239/239, test_relay 33/33 (cloud, openai stub). test_studio's
  4 model-call checks fail identically before/after under the stub (no real openai in the cloud). Shipped with
  --no-tests for that reason; CI runs everything on macOS + Windows.
- Not verified on the real machines yet: a fresh Studio replacing the stale one, the owner's NVIDIA key connect.

## 2026-10-18 early: four fixes from the Mac's own logs (Claude, on the Mac + cloud)

Read from the Mac's harness_data/app/engine.out and jobs.json, not guessed:
- **Self-improvement job 57c9b2ad died** at ~57k tokens: NVIDIA's free route answered a bare "HTTP 400: The
  request could not be completed"; LOKI only halved the tool list (42 -> 21 -> 10) and gave up. Now
  `loki._maybe_size_error`: a 400/413/422 on a request >= 24k tokens (LOKI_SIZE_400_TOKENS) is treated like a
  context error - condense and resend, then fail over in auto/smart mode. `_model_request` copies kwargs, so a
  halved tool list no longer sticks to the caller's retry.
- **Window CSP**: `style-src` now allows inline `<style>` (pywebview's drag-region style for the Mac title bar and
  Mermaid's diagram styles were blocked: "could not load (no address) - <style>"). Scripts stay 'self', no eval.
- **Title-strip double-click = zoom** never worked: pywebview's api.js builds `pywebview.api.*` with
  `new Function` (EvalError under the CSP). modebar.js now calls `pywebview._jsApiCallback("toggle_maximize")`.
- **engine.out noise**: BridgeHTTPServer.handle_error drops BrokenPipe/ConnectionReset tracebacks.
- **Studio never answered on the Mac**: its "local" driver was hard-wired to `qwen3:8b`, which the Mac never pulled
  (every turn: "model 'qwen3:8b' not found"). `studio_models.local_model()` now uses the engine's pick
  (status.json) when Ollama has it, else the first installed model (loki-* first); LOKI_STUDIO_LOCAL_MODEL still pins.
- Checked in the cloud with an openai stub (no PyPI there); not yet run on the real Mac/PC: the title strip drag +
  double-click, and job 57c9b2ad re-queued.

## 2026-10-17 midnight: title bar fixed for real (Claude, cloud)

Owner (Mac): the tabs were not in the top bar and clicking them made the window "run away". Causes, from pywebview's
source (r0x0r/pywebview, customize.js + cocoa.py): (1) any element INSIDE a .pywebview-drag-region dragged the window
(DRAG_REGION_DIRECT_TARGET_ONLY was False) and the tabs sat inside one; (2) the live-window NSWindow patch did not move
the content under the bar. Now: macOS window created frameless=True, easy_drag=False (pywebview makes it full-size +
transparent at creation), traffic lights un-hidden in before_show (main thread); DIRECT_TARGET_ONLY=True; only the two
empty sides of the strip drag; tabs centred on the whole bar. tests/test_ui_fit.py runs pywebview's real customize.js:
a press on a tab never moves the window. Not run on the real Mac yet.

## 2026-10-17 late: mode tabs in the title bar, menus that stay on screen (Claude, cloud)

- Tabs in a 38 px title strip (`app/ui/modebar.js`). macOS: transparent title bar over full-size content (pyobjc,
  guarded) and the strip starts after the traffic lights. Windows: the native frame stays (pywebview frameless loses
  edge resizing) and the strip is flush under it. `LOKI_TITLEBAR=custom|native` in Settings > General.
- `app/ui/place.js` (LokiPlace) places the chat model menu, the Settings model picker, the chat menu, the mode picker,
  the / palette and right-click menus; dialogs use vh/clamp() under the strip. Suite `tests/test_ui_fit.py` (~42 s).
- Not verified: the real Mac title bar (pyobjc in pywebview's window), dragging/double-click in pywebview on either OS.

## 2026-10-17 night: one client - mode bar, Studio tab, Godot tab; Studio's "Where is this going?" (Claude, cloud)

- LOKI's window: mode bar at the top (`app/ui/modebar.js`): LOKI / Studio / Godot / World / Forge, Ctrl/Cmd+1..5, state
  kept. Studio tab = Studio's own server started headless once (`POST /studio/embed`, `studio_app.py --headless`) and
  framed. Godot tab = `engine/godot_web.py` (`/godot-editor/*`): Godot 4.4.1 web editor downloaded + SHA-512 checked,
  COOP/COEP, project zip in/out, "Open in the Godot app". docs/STUDIO.md has it all.
- Studio: `studio/studio_destination.py` - Improve LOKI itself / My own LOKI (fork) / A new app from LOKI / Just this
  computer; non-owners (gh user != m03dev) can never ship to m03dev/loki. LOKI settings panel in Studio (providers,
  General, capabilities, EVOLVE.md tasks). Suite `tests/test_studio_destination.py` (~7 s).
- Not verified: real `gh repo fork/create` (gh is not signed in here), the real Godot web editor download and whether it
  runs in "its own window" in pywebview on the Mac/PC (LOKI's window is not cross-origin isolated, so it is never framed
  inline), Studio framed inside pywebview (WKWebView/WebView2 loopback iframe), tests/test_studio.py (needs `openai`).

## 2026-10-17 night: Forge, LOKI's 3D maker (Claude, cloud)

- Sidebar cube -> Forge (`app/ui/forge.js/.css`): Draw / Add an image / Describe it (picture first, redo) ->
  Make 3D -> viewer (orbit, zoom, wireframe, clay, lights) + Sculpt (Draw, Inflate, Smooth, Flatten, Grab,
  Pinch, radius/strength, X symmetry, undo/redo, curved Subdivide) -> Save .glb/.obj into `models/`.
- Engine `engine/forge3d.py` (`make_3d`): TripoSR (own process, `engine/runners/triposr.py`) -> HF Space
  TRELLIS via gradio_client -> offline "lift" (always works; closed mesh, vertex colours, own glb writer).
  API `engine/forge_api.py` (`/forge/*`, token required, file route only models/). Agent tool `make_3d`.
  Manifest `capabilities/forge-3d`. Suite `tests/test_forge3d.py` (~18 s, includes a headless window check).
- Round 2 (owner feedback): real open source instead of hand-rolled - three.js' own GLTFLoader/GLTFExporter/
  OBJExporter/OrbitControls/TransformControls vendored (app/ui/vendor/three/addons, from the three.js repo);
  sculpting ported from SculptGL (MIT; clay, inflate, smooth, flatten, move, pinch, crease); a Materials side
  that runs Material Maker's own .mmg nodes (27 bundled by tools/import_mm_nodes.py, compiler forge_mm.js =
  port of gen_shader.gd) -> live PBR maps on the model, PNG/.ptex export, "Open in Material Maker"
  (engine/forge_mm.py finds the app). Output panel = forge3d.OPTIONS modules (resolution, keep %, thickness,
  smoothing, texture/picture size, subject fill, cut-out, mirror, seed) passed to every backend, greyed out
  when ignored. Pollinations: one request builder, nologo+private, Bearer POLLINATIONS_API_KEY (needed for no
  mark per their docs). Layout fits 900x600. Suites: test_forge3d (~5 s), test_forge_ui (~30 s, Chromium).
- Not tested here: `python tools/setup_forge3d.py` (torch + TripoSR) on the PC (CUDA) and the Mac (MPS),
  the TRELLIS Space (its API names may change), TripoSR decimation (needs a trimesh simplifier), and
  Material Maker on a real machine. Next: "Send to LOKI World", more MM nodes (buffers/function inputs).

## 2026-10-17 night: LOKI installs what it needs by itself (Claude, cloud)

Owner: "get loki to start downloading and installing packages it needs". `engine/auto_setup.py`: 45 s after the engine
is ready, one add-on at a time, waiting while a request runs (BridgeState.try_busy). LOKI_AUTO_SETUP (Settings >
General): recommended (default: documents, data-analysis, ocr, media, rembg, chromium, whisper, cadcraft, mlx on Apple
silicon) | everything (+ local-image, + local-video on NVIDIA) | off. Failures are remembered in <data>/auto_setup.json
and retried after 6 h, not in a loop. Installing never turns an add-on on (permissions stay the owner's OK). Settings >
Add-ons shows progress + "Install what LOKI needs now" / "Everything". Routes: GET /autosetup/status, POST
/autosetup/start {level}. Tested with fakes (tests/test_auto_setup.py); not run on the real Mac/PC yet.

## 2026-10-17: LOKI World character creator, "Join world" (Claude, cloud)

Owner: "i want a character creation screen and then play button should be join world". Settings > LOKI World's
"Play" is now **Join world** (icon + tooltip, translated in all 8 tables) next to **Edit character**. With no character
yet, Join world opens the creator (app/ui/character.js): name, role (Builder/Explorer/Artist/Scholar, one line each),
body, skin, hair + colour, eyes + colour, top/bottom + colours, hat/scarf/none, Randomize; live preview drawn with
world.js's own cel shader, ink and pixel blit; keyboard radios. Kept per machine: `GET/POST /character`
(engine/character.py, <data>/world/character.json, fixed option lists). The avatar wears it (mmo_core.js `person()`,
pooled; every renderer draws that scene list) with a name/role plate; role -> class. `GET /mmo/state` adds
`profile.look` (docs/MMO_API.md); Godot player.gd uses its top colour, skin and hat (NOT compiled here - Ziva: run
test_godot_world with Godot). tests/test_character.py (54, ~20 s, in SUITES). The "Play" games tab is unchanged.

## 2026-10-17 evening: provider Test, phone QR black page, model picker (Claude, cloud)

Owner: added the NVIDIA key, Test said "could not reach integrate.api.nvidia.com (TimeoutError)"; the phone QR opens
"no link, just a black page"; the model list is far too bright.
1. **Test** (`providers_catalog.test`): sends DeepSeek on NIM `chat_template_kwargs: {thinking: false}` like the chat does
   (it was reasoning first and timing out), 8 tokens, 45 s. A timeout is now diagnosed (`_diagnose_timeout`): cannot
   reach the host at all / key refused / the model id is not in NVIDIA's list (names the ones it offers) / reachable
   but the free queue was slow. NOT verified against the real NVIDIA API (no access from the cloud box): if it says
   `deepseek-ai/deepseek-v4.1-flash` is not in the list, the default in `engine/loki.py` must change.
2. **Black page** = the phone got no answer (QR images decode fine, checked with OpenCV; the page itself renders).
   The hand-off page is now also published through the relay on a relay-picked port (`relay_link.publish_page`,
   own status, closed with the page; `LOKI_HANDOFF_RELAY=off` / `LOKI_RELAY=off` turn it off) and offered as "Use the
   internet link", labelled not encrypted. On Windows "Let phones in" asks once (UAC) for a firewall rule on TCP 8770,
   private/domain only (`signin.allow_phone_port`, POST /handoff/firewall).
3. **Model picker**: provider cards use LOKI's own list (`modelPicker` in settings.js: search, keyboard, fixed popover),
   soft translucent grey-blue glass; the chat's model menu matches; native `<option>`s get a solid grey everywhere.
Checked here: test_qr_links, test_relay, test_portal, test_ui_smoke, `--self-test` (with an openai stub; PyPI was
blocked in this sandbox so the openai-dependent suites ran only in CI). Not checked on the real PC/phone.

## Session 30 one-click install (worktree)

The owner: "it should prompt users after they install the client to download a local model or go online and connect to
an account ... there shouldn't be any dependencies ... everything should be ready for them a click away ... it should
be quick ... if we need to move to rust to be fast we do". He shares LOKI with friends now; the repo is public.
Built in a Claude worktree, committed there, not pushed. Guides: **docs/INSTALL.md** (rewritten), **docs/TESTERS.md**
(friends: install in 3 steps per OS, what to try, feedback), **docs/SPEED.md** (numbers + the Rust decision).

1. **Zero-dependency installers.** `tools/bundle_runtime.py` makes `dist/runtime/`: python-build-standalone 3.12 (via
   uv, on the BUILD machine only) with every package of engine/ + app/requirements.txt installed, CPython's tests/IDLE
   stripped, everything byte-compiled with that Python (unchecked-hash .pyc, the seed too), plus
   `loki-requirements.sha256`. `packaging/installer/loki_launch.py` (LAUNCHER_VERSION 2) makes `<data>/.venv` from it
   (`--system-site-packages --without-pip`, offline, 0.3 s incl. the seed copy; remade if the app moved), pip-installs
   only what an update ADDED, gives every child CREATE_NO_WINDOW, shows a dialog when it fails (no console to read),
   hands over to a newer launcher a release left in `<data>/launcher` (LOKI_INSTALL_DIR). The slim path (bootstrap
   downloads uv + Python) stays for builds without a runtime; both bootstraps hand over to a bundled runtime at once.
   **`packaging/launcher/`**: a 340 KB native `Loki.exe` / `Loki.app/Contents/MacOS/Loki` (Rust, std only, no crates):
   windows subsystem + CREATE_NO_WINDOW, `exec` on macOS (Dock icon = Loki.app), LOKI_LAUNCH_T0 for timing, falls back
   to the bootstrap. `loki.iss`: bundled runtime + Loki.exe when built (`#if FileExists`), shortcuts on Loki.exe, no
   Python step at install time, x64 (ARM64 Windows runs it emulated). `make_dmg.sh`: runtime + launcher in the app,
   ad-hoc codesign, `Loki-<v>-macos.zip` via ditto, ULFO dmg; the script fallback never calls `python3` (it would ask
   a clean Mac to install Xcode tools). `make_release.py`: `--asset-base` (absolute GitHub asset URL in the manifest),
   default feed = GitHub Releases, `--portable` / `--from-seed` (portable zip: LOKI/ with Loki.exe or `Start LOKI.cmd`,
   runtime, seed, README), **`--friends`** (from `git archive HEAD` = committed tracked files only, scanned,
   `dist/Loki-<v>-<os>-portable.zip` + FRIENDS.txt; on a Mac it zips a real LOKI.app; `--bundle-runtime`).
   **`tools/secret_scan.py`** runs on EVERY build: refuses .env, harness_data/, private keys, cert stores, token/chat
   files and real-looking OpenRouter/OpenAI/Anthropic/Groq/Google/NVIDIA/GitHub/HF/Slack/Telegram/AWS/Stripe keys
   (placeholders pass; tests/ is never shipped, so its fake keys never are). `.github/workflows/installers.yml`: release
   (signed when LOKI_SIGNING_KEY_PEM exists) -> windows (cargo, bundle, iscc, portable, SILENT INSTALL + the installed
   launcher's --check + self-test) -> macos arm64 (+ Intel, optional) (cargo, bundle, dmg+zip, --check + self-test,
   codesign --verify) -> **publish** on v* tags: draft GitHub Release with every file, then public + latest.
   `engine/release_update.py`: `DEFAULT_FEED` = `https://github.com/m03dev/loki/releases/latest/download/manifest.json`,
   `LOKI_RELEASE_FEED=off`, https-only redirects. Key handling (generate, `gh secret set`, rotate): docs/INSTALL.md
   "Signing".
2. **First run** (`app/ui/onboarding.js` step 2, `app/ui/firstrun.css`): "How should LOKI think?" - **Run AI on this
   computer** (shows memory/GPU/disk, the QUICK pick `model_setup.quick_pick`: Bonsai 2 9B, else 4B, else the best
   agent model <= 7 GB; something downloaded wins; the bigger `auto` pick offered for later), **Connect an account**
   (OpenRouter one click, **NVIDIA NIM** first among the keys - DeepSeek V4.1 Flash, LOKI's main driver -, Groq,
   Gemini), **Both**. The choice is the one click: `/setup/auto {quick:true}` starts; **LokiBgSetup** (a card at the
   bottom right, outlives the tour, resumes after a restart) shows progress; failures offer try again / install Ollama
   by hand / use an online model. Ollama installs silently: Windows `OllamaSetup.exe /VERYSILENT /SUPPRESSMSGBOXES`
   (per-user, CREATE_NO_WINDOW), macOS the app copied + its `Contents/Resources/ollama serve` headless
   (`model_setup.serve_headless`); start_ollama opens the app with `open -g` (background). MLX: shown when installed
   (picks.mlx); LOKI does not install MLX itself. 47 new strings in all 8 tables (machine-drafted, marked for review);
   the 11 phrases other sessions had left untranslated are filled too (`i18n_tables.py --check`: 0 problems).
3. **Speed** (docs/SPEED.md, `tools/measure_start.py`): `import loki` 1.25 s -> 0.59 s (the MCP client is imported in
   `connect_mcp`, which already ran in the background); engine to /health 1.21 -> 0.88 s warm, 3.32 -> 2.38 s cold, and
   installed copies get the warm number on their first start (shipped .pyc). **The window opens first** (`app/loki_app.py
   run_with_splash`): the start screen shows while the start-up update and the engine start behind it; the window
   loads LOKI when the engine answers. **E12's hook**: LOKI's own `app/ui/splash.html` (self-contained) is shown when it
   exists, with `window.lokiSplashStatus(text)` progress; else a plain "Starting LOKI…". `LOKI_SPLASH=off` = old order.
   An installed LOKI no longer downloads/pre-flights before its window: `release_update.prepare()` runs in the engine's
   background check (`updater._release_check_now`), `apply_ready()` switches at start (no network);
   `LOKI_UPDATE_AT_START=1` restores the old order. loki_app.log: "window shown after", "engine ready after ... since the
   double-click". Rust: the launcher is 42 ms of Python - Rust would save ~40 ms; only a native splash before Python
   could win visible time, and only if the real machines show a slow window (decision in SPEED.md).
4. **Friends kit**: docs/TESTERS.md; **Settings > General > Send feedback** (`app/ui/feedback.js`, `engine/feedback.py`,
   routes in usability_api.py): a zip of LOKI's own logs (newest 256 KB each, every line redacted: key patterns, Bearer,
   #token=, KEY=value, e-mails, the home folder) + system.json, never .env/chats/memory/files, saved to the Desktop and
   shown; opens a prefilled new GitHub issue (label tester-feedback) or a mailto draft (`LOKI_FEEDBACK_EMAIL`). LOKI
   uploads nothing.
5. **Tests**: **tests/test_install.py** (71 checks, ~32 s, in SUITES): the friends build from git archive (no
   harness_data/.env/tests/tokens/chats, only the public key, feed, sha256), the secret scan (keys made at run time),
   --asset-base, https-only redirects, prepare/apply_ready, the launcher with a bundled runtime (venv, no pip, kept,
   remade after a move), the Rust launcher built with cargo (skipped without cargo), iss/dmg/workflow, bundle_runtime's
   strip + digest, the feedback bundle's redaction + links, lazy mcp, the splash hook, quick_pick, and headless Chromium:
   the tour's ways (account = no download; local = quick download + progress card that survives closing the tour) +
   Send feedback. test_usability updated for the 3-way step (139 passed), test_loki's MCP-transport check reads
   connect_mcp (533 passed); test_updater 102, test_update_overhaul 23, test_ui_smoke 7, `--self-test` OK.
   Also verified by hand here: a portable Linux zip with the Rust launcher -> `--print-url` started the engine in
   release mode end to end.
- **Not verified here (needs the real machines - ZIVA W44 PC, M33 Mac)**: python-build-standalone + the wheels for real
  (no GitHub release downloads from this sandbox, so `bundle_runtime.py` never ran end to end), iscc, hdiutil/codesign/
  ditto, the Windows/macOS Rust builds, the silent Ollama installer flags on a real Windows, `ollama serve` from the app
  bundle, pywebview showing the start screen then LOKI (load_url from the worker thread), WebView2/WKWebView timings,
  Gatekeeper with an ad-hoc signed app, the GitHub Release publish job (needs a v* tag). **Needs Mohamed**: the release
  signing key (generate + `gh secret set LOKI_SIGNING_KEY_PEM`, docs/INSTALL.md "Signing") - without it every release
  is unsigned and installed copies will not update; then push the first v* tag.

## Session 29 Studio in Godot (worktree)

The owner: "maybe its better when loki was a godot plugin it was very effective. i want it to work 1:1 OR BETTER THEN
ZIVA ... i want my dev tool thats building loki better then ziva smart". Built in a Claude worktree, committed there,
not pushed. Clean-room from Ziva's public feature list - no Ziva code/files copied or decompiled. Guides:
**docs/STUDIO.md** ("LOKI Studio inside Godot", "The Ziva-style workflow"), **docs/STUDIO_VS_ZIVA.md** (feature table,
better-than-Ziva, the 15-task parity benchmark, honest gaps).

- **The Godot plugin** `studio/godot_plugin/addons/loki_studio/` (AGENTS.md: the THIRD allowed Godot place, owner decision
  2026-10-17; test_loki/test_godot_world allow its .gd files): plugin.gd (dock via EditorDock/add_dock on 4.6+, else
  add_control_to_dock), dock.gd (chat, sessions of this project, New/Fork/Studio, Default/Plan/Ask, model, Ask first,
  approvals + questions as buttons, todos, Undo turn/Diff/Stop, queue, /command + @mention autocomplete, + Selection),
  bridge.gd (hello + long-poll; every studio_godot.ACTIONS action; scene edits via EditorUndoRedoManager, recorded per
  turn for undo_turn), debugger.gd + game_bridge.gd (autoload LokiStudioGame: input held >= 2 physics frames,
  screenshots, live tree, values, monitors; only active when run from the editor or --loki-selftest), error_logger.gd
  (Logger 4.5+: editor + game errors with file/line/backtrace), context_menu.gd (4.4+). Finds Studio through
  `~/.loki/studio_connect.json` (url + token, 0600, written by Studio at start; LOKI_STUDIO_CONNECT overrides).
  `studio/install_godot_plugin.py <project> [--remove]` copies it into ANY project and enables it (+ autoload, CRLF kept).
- **Studio** (studio/): `studio_godot.py` (the editor hub: hello/poll/result/event, call with timeout, screenshots
  saved to harness_data/studio/shots), `studio_tools.py` (the agent's own tools: Godot project files with checkpoints,
  project_index/graph, repo_map, godot_docs, every editor action, editor_errors, screenshot, playtest_step, find_lag,
  game_get, todo_write, remember/recall (memory_core), list/use_skill, web_search, generate_image, pc_worker/pc_job,
  ask_owner, subagent), `studio_checkpoints.py` (git snapshot commits via a throwaway index for code; file snapshots
  for Godot), `studio_commands.py` (28 slash commands, .md templates, @-mentions incl. @scene/@selection/@errors/@todos),
  `studio_index.py`, `godot_docs.py` (offline class reference: source checkout / `godot --doctool` / sparse git clone),
  `studio_mcp.py` (Studio as an MCP server), `studio_cli.py` (Claude Code / Codex as a session's driver),
  studio_models.py (+ LM Studio, `choices()`), studio_core.py (sessions of kind loki|godot, modes enforced, per-turn
  checkpoints + undo + conversation trim, questions, Ask first, subagents, fork, discard = undo all for Godot),
  studio_server.py (the new /api routes; 16 MB editor bodies), the window (modes bar, target = LOKI code or a linked
  Godot project, model picker, Ask first, todos, questions, Undo/Fork, screenshots inline, its own mermaid renderer,
  /@ autocomplete). studio/prompts/: explain, mechanic, optimize.
- **Verified here (Linux cloud box, Godot 4.7.2 built from source at /usr/local/bin/godot)**: `tests/test_studio_godot.py`
  (135 checks, ~20 s, in SUITES) incl. the plugin loading in a REAL headless Godot editor, its bridge linking to a real
  Studio server, real editor actions with UndoRedo, a real parse error captured, undo_turn; the game bridge in a REAL
  running game (injected input seen by the game's own polling, tree, monitors, errors); the window in headless Chromium
  (docs/operations/screens/studio-godot.png with LOKI_SUITE_SCREENS). test_studio (182), test_loki (533),
  test_godot_world (84), `app/loki_app.py --self-test`, `studio_app.py --self-test` green. The Godot docs cache built
  from the source tree (1071 classes) and from `godot --doctool` (995 classes, 4.7.2-stable).
- **Not verified (needs a real machine - ZIVA W37 PC, M28 Mac)**: the dock in a WINDOWED editor (layout, autocomplete
  popup, image popup, right-click entries), playtesting a real game window + real screenshots, the Windows/macOS Godot
  builds (connect-file path, USERPROFILE), a real model driving a Godot session, Claude Code / Codex CLIs as drivers
  (only a fake stream here), the git-clone docs path (no network check here), and the 15-task parity benchmark vs Ziva.
Last updated: 2026-10-17 (session 29 QoL from Ziva's patch notes, Claude worktree).

## Session 29 QoL from Ziva's patch notes (worktree)

The owner: "go through all ziva updates and patchnotes i want those quality of life features like when you disconnect
it gives you options and stuff". Ziva's public changelog (3.3.0 back to January 2026) and docs (queue-and-steer,
keyboard-shortcuts, approvals, chat-history, troubleshooting) were read; every chat QoL item, LOKI's status and what
was built is in **docs/integrations/ZIVA_QOL.md** (with source links). Clean-room: no Ziva code or files. Built in a
Claude worktree, committed there, not pushed.

- **Disconnect with options** (app/ui/qol.js): engine not answering -> banner, automatic reconnect with a countdown
  (2-30 s backoff), Reconnect now, Copy my message, What happened?; a cut-off answer gets a card and the text goes
  back in the box; after reconnecting the window checks whether the engine finished it meanwhile. Offline computer ->
  "use <local model>".
- **Recovery cards** (engine/qol.py `classify`/`recovery`): 14 error kinds from LOKI's real error texts -> Try again,
  Wait then try again (provider's Retry-After counted down; automatic for drops and rate limits, max 5), another
  ready model, a model on this computer, Let LOKI pick, Summarize and try again, Fix the key, Local models, New chat,
  What happened? (`GET /qol/diagnose` + Copy this report). Slow answer (90 s no news) -> Keep waiting / Stop and try
  again / Stop and use another model.
- **Queue + steer**: typing while LOKI worked used to LOSE the message. Enter now queues (sent when free), Ctrl/Cmd+
  Enter steers: `POST /qol/steer`; `qol.install` wraps the agent loop's `_trim_context` so the steer joins the
  conversation at the next step (never between a tool call and its results); the window marks it "Steered"; unread
  steers come back (`steers_left`). Steer / Send now / Edit / Remove per message; Stop returns them to the box.
- **Interrupted turns**: `<data>/qol/inflight.json` while a turn runs; the next start offers Send it again / Put it
  in the box / Dismiss.
- **Allow for this session** on approval cards: the same exact action (tool + details hash) is not asked again until
  the engine restarts; refused for policy.ALWAYS_ASK, ACTION_ALWAYS_ASK (connector writes) and extensions; not saved.
- **Comfort**: drafts kept (reload/crash/update), long pastes (> 8,000 chars) saved to uploads/ and @-attached, Up
  recalls, context bar + Summarize now (`POST /qol/compact` = the condenser) and `/compact`, desktop notification +
  optional sound when a long answer finishes or an approval waits (automations.notify_argv), search all chats by
  name AND message (Ctrl/Cmd+K, icon under New chat), find in chat (Ctrl/Cmd+F), pinned chats (`POST /qol/pin`),
  rename by double-click/F2, 12 customizable shortcuts (keyboard icon in the top bar / Ctrl/Cmd+/), copy chat as
  Markdown, thinking on/off, "Switched to X" notes; slash commands /compact /search /find /copy /why /shortcuts /queue.
- **Studio** (small; another agent owns studio/godot_plugin): failed send keeps the text, draft kept, red status when
  its server is down.
- **Wiring**: loki_bridge.py one GET block + one POST block + one `qol.install` start-up line; app/loki_app.py
  self-test imports qol; index.html 1 stylesheet + 1 script; app.js and loki.py untouched; icons via data-icon with
  tooltips. i18n: qol strings are English for now; the new tooltip phrases + 3 dialog titles are in all 8 tables,
  and the phrases chat_plus/data_panel/modes/studio_link had left out of the tables (test_usability was red on them)
  were added too (machine-drafted, review flag unchanged).
- **Verified here (Linux)**: tests/test_qol.py 82 checks ~20 s (in SUITES), incl. the real BridgeHTTPServer + the real
  loki module (a steer sent during a real /chat reaches `loki.messages`) and the window in headless Chromium
  (screens docs/operations/screens/qol-*.png). Also green: --self-test, test_ui_smoke 7/7, test_research3 154/154,
  test_usability 137/137, test_studio 182/182. Full `ship.py --check` NOT run (the one-minute rule).
- **Not verified (real machines: ZIVA W42 PC, M32 Mac)**: WebView2/WKWebView (Ctrl/Cmd shortcuts reaching the page -
  Cmd+N/Cmd+, may be taken by the app menu on macOS; clipboard; notifications from the engine), a real engine crash /
  update mid-answer, real provider 429/quota texts, a steer with a real model, the desktop notification and sound.

## Session 29 automations (worktree)

The owner: "a useful app that can help people and can turn into anything" - this one is AUTOMATIONS: LOKI does
things without being asked each time. Built in a Claude worktree, committed there, not pushed. Full guide:
**docs/AUTOMATIONS.md**.

- **Model** (`engine/automations.py`): triggers -> conditions -> steps. Triggers: schedule (engine/schedules.py +
  a phrase normalizer: "every morning at 8", "every weekday morning", "daily at 7", cron, "in 30m" pinned to a
  time), folder (settle check, partial downloads ignored, a copy into `<workspace>/automations/inbox/<id>/`),
  email (connector, last-UID dedupe), calendar (N min before, once per event), webhook (`POST /hook/<id>?key=`,
  no bridge token, 30/min, 64 KB), Telegram keyword (owner only; wraps the channel's handle at start-up, no edit to
  channels.py), job done/failed (ignores automations' own jobs), machine online, manual / Run with text.
  Conditions: trigger fields (contains ... regex, gt/lt, exists), time window, weekdays. Steps: task (a
  background job, waits, `{{last}}` = its answer), tool, image, telegram (paired owner chat only), file (workspace
  only), notify (osascript / PowerShell toast / notify-send + in-app notice), http (always asks), if (LLM YES/NO,
  data framed as data), wait, sort_file (asks). Templates `{{trigger.x}}`, `{{last}}`, `{{steps.N}}`, `{{date}}`.
- **Safety**: account-touching steps (http, sort_file, any tool the policy engine ASKs about - email send,
  calendar create, GitHub/notes/peer-file writes) wait for the owner's OK in the view unless THAT EXACT automation
  is pre-approved (sha256 fingerprint of triggers + conditions + steps + machine; any edit removes it, a rename
  does not). Forbidden tools: run_command, computer, make_tool, schedule_task, automation, improve/ship. Cloud
  metadata addresses refused. Drafts (from the view, the chat tool or the model) are always saved OFF.
- **Natural language**: rules first (offline; the two owner examples and email/calendar/job/machine/Telegram/
  webhook shapes), the model only for what the rules do not understand, its JSON checked like any automation.
  8 templates: daily briefing, inbox triage, folder auto-organizer, meeting prep, weekly report, backup reminder,
  price watch, GitHub issue digest.
- **Runtime**: one thread (`automations.start` - ONE start-up hook in loki_bridge.serve), tick 5 s; JSON store in
  `harness_data/automations/`; a run = a compiled program + pc saved after every step, resumed after a restart
  (a waited-on job keeps its id); missed schedules: catch_up once (default) / skip / all (<= 5); retries with
  backoff 30 s x2^n (<= 30 min); modes single/queued/parallel; per-automation and overall runs/hour; at most 3
  runs start at once; kill switch (Stop all cancels runs and their jobs); `LOKI_AUTOMATIONS=off`.
- **Two machines**: each automation has `machine` (default `pc`; on a lone Mac, the Mac). Only that machine
  fires it. Shared over the signed peer link: new route `POST /peer/automations` (peers.py one block,
  peer_link.py one callback), every 2 min + after a change, last writer wins, tombstones, run stats travel back.
  No failover by design (a double briefing is worse than a late one).
- **Where it is wired**: loki.py one tool block (`automation`: list/draft/show/run; planning category; not in Plan
  mode; refused in background jobs). loki_bridge.py: GET/POST `/automations*` route blocks, the `/hook/` block
  before the token check, one start-up hook. app/ui: `automations.js` + `automations.css` (new), index.html (tab,
  panel, script, stylesheet), app.js one line in showTab. The rail icon + tooltip are added from automations.js to
  icons.js' ICON_PATHS/TAB_ICONS (icons.js untouched).
- **Verified here (Linux cloud box)**: `tests/test_automations.py` (190 checks, in SUITES; fake clock, fake
  connectors, fake Telegram, fake jobs/peers/model; the real BridgeHTTPServer for the routes and the webhook; the
  view in headless Chromium: list, rail tooltip, draft card, history log, editor). Screens:
  `docs/operations/screens/automations-{list,draft,history,editor}.png` (`python tests/automations_preview/shot.py`).
  `python tools/ship.py --check` green with the new suite.
- **Not verified (needs the real machines - ZIVA W35 PC, M26 Mac)**: real Telegram delivery of the morning
  briefing, real IMAP/calendar triggers, a real model's YES/NO, the Windows toast and macOS notification, the
  folder watcher with a real browser download, peer sync between the real Mac and PC, the view in WebView2/WKWebView.
  Not built: an OS-wide hotkey (Run with text reads the clipboard instead), failover to the other machine.

## Session 29 DeepSeek V4.1 + LOKI Studio (worktree)

The owner: "i heard deepseek4.1 flash is free now through nvida ... i want it as the main driver ... i want a tab in
loki for loki development that runs on deepseek4.1 and has the loki mcp api and controls it", then: "this mode might
need to exist outside of loki like a game engine". So: DeepSeek is the main driver, LOKI has an MCP API, and the
development environment is its OWN app, **LOKI Studio** (docs/STUDIO.md); inside LOKI there is only an icon that opens it.

1. **Main driver** (engine/loki.py provider block + routing helpers, engine/routing.py, docs/providers.md): `nvidia`
   defaults to `deepseek-ai/deepseek-v4.1-flash` (NIM, free, ~40 req/min, 1M context, tools) and leads SMART_ORDER and
   ONLINE_ORDER. `main_driver_ready(needs)` puts it first - ahead of local-first and the learned order - for chat,
   code, background jobs, teams and self-improvement (improve_loki/evolve run "online") whenever its key is set and it
   is healthy; pictures, Local only, a rejected key, a remembered rate limit/quota or a failure this session fall back
   to the usual order. `LOKI_MAIN_DRIVER=off` / `LOKI_NVIDIA_THINKING=off|high|max` in Settings > General. `/models
   doctor` opens with a "Main driver: ..." line (+ a Needs-you line with the key URL when missing). The Connections
   card says "LOKI's main driver ... Get a free key at build.nvidia.com".
2. **Pacing** (engine/ratelimit.py, stdlib): a per-provider sliding minute (LOKI_NVIDIA_RPM, default 36) shared by the
   engine, every job and Studio via harness_data/ratelimit/nvidia.json; `_model_request` waits for a slot (up to 75 s,
   says so). A 429 anyway penalises the window and, with another provider ready, fails over at once (provider_health
   marks rate_limited); with none ready the retry waits in the pacer.
3. **Reasoning**: NIM's `chat_template_kwargs: {"thinking": false}` for agent work; `reasoning_content` / `reasoning` /
   `<think>` are shown as a "<provider> thought: ..." progress line and removed from the message (`_take_reasoning`,
   `split_reasoning`) - never in the history, never re-sent. Local models keep the old empty-answer recovery.
4. **The LOKI MCP API** (engine/loki_mcp.py, docs/LOKI_MCP.md): an `mcp` 2.x MCPServer (stdio; `--http` = streamable
   HTTP on 127.0.0.1 behind the bridge token). 25 tools: loki_status, models_doctor, settings_get/set (no secrets),
   jobs_list/job_start/job_stop/job_logs, engine_logs (disk: works when LOKI is down), world_summary, memory_search,
   tools_health, creations_list, restart_engine, read/list/search/edit/write files, git_status/diff/log, read_doc
   (HANDOFF/ZIVA_TASKS/AGENTS/BUILD_BRIEF), run_tests (ship.py --check, hermetic), ship (ship.py). Code tools are jailed
   to the dev worktree (never the checkout, harness_data, .env, tokens, keys, .git). Risky tools go through policy.py
   and need an HMAC approval code that only the asking program (Studio, after the owner's Approve) can make, or
   `--allow-risky` (the client's own prompt is the gate). Engine side: engine/studio_api.py (`POST /engine/restart`,
   `GET /studio`, `POST /studio/open`; 2 small hooks in loki_bridge.py).
5. **LOKI Studio** (studio/): its own process, window (pywebview, else the browser) and launchers (`Loki Studio.cmd`;
   `studio/loki_studio.sh` + `studio/make_studio_app.sh` -> LOKI Studio.app). Runs from a **pinned known-good copy**
   (harness_data/studio/pinned, a detached worktree at the updater's last_good; moved only after the candidate passes
   `studio_app.py --self-test` + test_studio in a throwaway worktree, and only at the next start; falls back to the
   checkout if the pin will not start). Its agent loop is its own (studio_core + studio_models, no loki.py): DeepSeek on
   NVIDIA first, then OpenRouter's DeepSeek V4.1, OpenCode Zen, Gemini, Groq, local; paced; no key -> it says exactly
   how to get one and uses the next best free model. A session = a worktree on `studio/<id>`; the agent's only hands are
   the MCP API (stdio, bound to that worktree); everything streams (thinking, tool calls, results, diffs); risky calls
   wait for Approve; follow-ups continue the same session; Diff, Tests, **Ship it** (owner only: ship.py), Discard;
   history in harness_data/studio/sessions/. The LOKI card: status, logs from disk, Start/Restart, **Roll back** (the
   updater's rollback, or by hand `git reset --keep <last_good>` + skip list). LOKI's sidebar has only the Studio icon
   (app/ui/studio_link.js, 1 line in index.html, 1 icon in icons.js).
6. Tests: **tests/test_studio.py** (182 checks, in SUITES): ratelimit, main-driver routing, the real agent loop vs a
   fake NVIDIA (tool calls + reasoning_content + <think> + 429s + pacing against a server-side cap), every MCP tool via
   the mcp client in-process + the stdio process + the HTTP token check, a fake running engine, a full Studio session
   with the engine stopped (scripted model edits a temp worktree, fake check, approval, cannot ship, follow-up, ship
   with approval, failing tests not shipped, stop, discard, history), start/restart/rollback (both kinds), the pin,
   Studio's server (token, Host, CSP), its window and LOKI's Studio icon in headless Chromium
   (docs/operations/screens/studio.png, studio-button.png).
   test_loki: 2 checks updated for the new order. app self-test imports ratelimit, loki_mcp, studio_api.

**Not verified here (no key, no network, no real window):** a real NIM request (model id, `chat_template_kwargs`, the
exact reasoning field and 429 body/headers are from build.nvidia.com's docs and catalog pages, not a live call); the
40/min figure per account; pywebview windows on Windows/macOS (Studio's window only ran in headless Chromium); the
Studio icon in LOKI's real window; Loki Studio.cmd / LOKI Studio.app; a pin refresh with the real test_studio in a
real checkout; the stdio MCP server inside Claude Code/Codex. -> ZIVA W35 (PC), M26 (Mac). Needs Mohamed: the NVIDIA key.
Last updated: 2026-10-17 (session 29, Claude in the cloud; research round 3 worktree).

## Session 29 research round 3 (worktree)

The owner: "keep researching, downloading and installing new features ... a useful app that can help people and can
turn into anything". Research: what the best personal-AI apps of October 2026 (Open WebUI, LibreChat, Msty, Cherry
Studio, Lobe Chat, Khoj, Jan, OpenClaw, Leon, Goose ...) give ordinary people that LOKI lacked - ranked table of 35
with sources in **docs/integrations/research-2026-10-17b.md**. Built in a Claude worktree, committed there, not
pushed. **tests/test_research3.py (154 offline checks, in SUITES)**; screens `docs/operations/screens/research3-*.png`.

- **Message actions** (`engine/chat_plus.py`, `app/ui/chat_plus.js`): Copy on every message; Edit & send again
  (yours); Regenerate and Branch from here (LOKI's). Edit/regenerate cut the stored chat before that message and
  resend through /chat; branch = a new chat up to there (original kept). Found by text + occurrence; 409 while busy.
- **Rich replies + artifacts** (`app/ui/artifacts.js` replaces app.js's global `renderMarkdown`, same escaping
  contract; `engine/artifacts.py`): tables, task lists, quotes, links (open in the browser via /open), [n]
  citations that jump to the reply's n-th link, code blocks with language + Copy; ```html/```svg get **Preview**
  in a canvas beside the chat (Save -> workspace artifacts/<name>.html, later versions .v2 ...); ```mermaid is
  drawn in place; ```chart (JSON: type bar|line|pie|donut, labels, data/series) drawn as SVG; ```loki-card
  (weather/news/clock) drawn as cards. Pages run at `GET /artifact/<id>` (no token; host-checked) in
  `sandbox="allow-scripts"` frames with their own CSP (`sandbox allow-scripts`, `connect-src 'none'`); the window's
  UI_CSP is unchanged. Mermaid 11.16.1 vendored in `app/ui/vendor/mermaid/` (MIT, loaded only inside the frame).
- **Export / import chats** (`engine/chat_io.py`): Markdown, standalone page, JSON (exports/ in the workspace);
  import ChatGPT (mapping graph, current_node branch), Claude, Open WebUI, LibreChat, LOKI, Markdown/`User:`.
  `/convo/import` and `/artifact` read bodies up to 150 MB / 4 MB (the bridge's 32 KB limit stays for the rest).
- **Prompt library** (`engine/prompt_library.py`; book button in the message box; `/p name`, `/prompts`): 12
  starters, `{{blank|default}}`, `{{date}} {{time}} {{weekday}} {{clipboard}}`; own prompts in DATA_DIR/prompts.json.
- **Compare models** (`engine/compare.py`; chat menu or `/compare`): 2-4 ready models answer the same message side
  by side (no tools, `loki._r3_model_ask`), vote -> Elo leaderboard in DATA_DIR/arena.json.
- **Home Assistant** (`engine/conn_home.py`, connector `home`, registered in connectors.py, tool category `home`): status/list/find/state/
  history; turn_on/off/toggle (brightness, colour, temperature), call, assist - by friendly name. Writes are in
  `policy.ACTION_ALWAYS_ASK["home"]` (always ask, never in jobs); hidden from the model until HA_URL + HA_TOKEN.
- **Everyday** (`engine/everyday.py`, category `everyday`): `weather` (Open-Meteo, no key, °F in the US),
  `news` (Google News RSS / BBC), `world_clock`, `translate` (model or LOKI_LIBRETRANSLATE_URL); `/weather`,
  `/news`, `/time`, `/translate Spanish: text` render cards without a model.
- **Picture edits** (`engine/image_tools.py`, tool `edit_image`): info, resize, crop, rotate, flip, convert,
  compress, grayscale, thumbnail, upscale (Real-ESRGAN ncnn if on PATH / LOKI_REALESRGAN, else Lanczos),
  remove_background (new add-on `rembg`, pip `rembg[cpu]`). Always a NEW file. **Pillow added to requirements.txt.**
- **Settings > Your data** (`engine/your_data.py`, `app/ui/data_panel.js`): sizes of everything LOKI keeps,
  which providers got messages in 30 days (from usage.jsonl), backup zip (no .env unless ticked; no venv/models/
  installed programs; LOKI's own tools kept) to ~/LOKI Backups (LOKI_BACKUP_DIR), restore (manifest, no escaping
  paths/links, safety backup first), clear logs/previews/computer log/usage/chats.
- **Where it is wired:** loki.py one registration block before the agent loop; loki_bridge.py three route blocks
  (`/artifact/<id>` page, big-body POSTs, GET/POST to `engine/assist_api.py`); policy.py one dict entry;
  connectors.py one import; addons_install.py one PIP entry; index.html 1 stylesheet + 3 scripts + the Your data
  tab; app.js untouched (chat_plus.js wraps the global addUser/addLoki; data_panel.js adds icons to ICON_PATHS).
- **Verified here (Linux cloud box):** every engine module with fakes; real Pillow; every route on the real
  BridgeHTTPServer; the window in headless Chromium against the real bridge - Mermaid really draws in its frame,
  the preview's own script runs, the frames cannot read the window, prompt blanks fill, compare + vote, Your data.
- **NOT verified (ZIVA W35 PC, M26 Mac; Needs Mohamed for HA):** real Open-Meteo / Google News / LibreTranslate /
  Home Assistant / models (the sandbox cannot reach them), rembg and Real-ESRGAN for real, WebView2/WKWebView:
  sandboxed iframes, the Import file picker, confirm()/prompt() dialogs, clipboard.
- **Next (from the table):** a global quick-launch hotkey ("Spotlight for LOKI", Khoj Mini), clipboard history
  (opt-in), job-finished notifications, a hands-free voice mode with Pipecat's Smart Turn, a screenshot button.
Last updated: 2026-10-17 (session 29, Claude in the cloud; usable-by-anyone worktree).

## Session 29 usable by anyone (worktree)

The owner wants "a useful app that can help people" - other people, not only him. LOKI was a power-user tool
with an English-only window, a model-setup sheet as the first thing anyone saw, and installs that needed git.

**1. A first run for anyone** (`app/ui/onboarding.js`, engine `engine/usability_api.py`): a 4-step welcome tour -
what LOKI is + pick one of 8 languages (with Bigger text / High contrast right there), connect a FREE model (on this
computer: the detected Ollama/MLX state + the existing one-click `/setup/auto` with its size, "install Ollama by hand"
and "More choices" = the old setup sheet; or online: OpenRouter one-click sign-in via the existing `/signin/openrouter`,
Groq/Gemini sign-up link + paste key via `/providers/connect`), choose what to help with (8 interests, saved as
`LOKI_INTERESTS`), and try 3 matching examples. Every error says what to do (wrong key -> the prefix it should
have; setup failed -> retry / install by hand / go online), every step can be skipped, "Next" without a model
warns once then goes on. It REPLACES the old auto-opening setup sheet for new people only (setup.js `afterStart`):
the tour shows only when the engine says `done:false`, and marks itself done for anyone who already has a working
model and real chats (the owner never sees it). Esc = "ask again in 3 days"; Settings > General re-opens it.

**2. "What can LOKI do?" + help** (`app/ui/gallery.js`): 32 examples in 8 categories (everyday, work, study,
creative, home, money, health info, small business); one click runs it in a new chat in Ask mode (nothing on the
computer changes) and the answer shows in the chat. The 4 health examples show a safety note on the card and add
"general information, not a diagnosis, say when to see a doctor" to the prompt. Opened from a grid icon in the
sidebar and "More ideas..." on the home screen. Help center: the "?" icon in the top bar (tooltip like every icon)
or F1, searchable articles from `docs/help/*.md` (10 articles: getting started, connect a model, examples,
privacy, health safety, languages, accessibility, keyboard, updates, troubleshooting; `docs/help/index.json` orders
them; `docs/help/<lang>/<slug>.md` overrides per language) via `GET /help`, `GET /help/<slug>`, rendered with
app.js's escaping Markdown renderer.

**3. Accessibility** (`app/ui/a11y.js`, `app/ui/usability.css`): Settings > General > "Language and accessibility"
(text size 100/115/130/150% via zoom, high contrast (black/white/yellow focus), motion (follow the system / reduce /
full - reduce hides the 3D world), colour-blind-safe status colours (Okabe-Ito + a symbol)), saved per computer
in localStorage. Keyboard: a skip link, arrow keys + roving tabindex in tab lists and radio groups (Settings
sections), focus kept inside open dialogs and returned to the opener, Esc closes; Space on a focused button no
longer opens the chat box on the home screen (app.js `keyForControl`), Babylon's `tabindex=1` on the decorative
world canvas is neutralised. `LokiDialog` is the accessible dialog all new UI uses.

**4. Languages** (`app/ui/i18n.js`, `app/ui/i18n/<lang>.json`): en, es, fr, de, ar (RTL), hi, zh, ja - 217 keys +
63 icon phrases each, all machine-drafted by Claude and marked `_meta.review: true`. OPT-IN per element so other
agents' new UI keeps working in English: `data-i18n="key"`, `data-i18n-attr="placeholder:key"`, `data-i18n-src`
(by English text); icons.js keeps the English name in `data-tip-src` and translates tooltips/aria-labels from
"phrases"; index.html's static words are annotated from i18n.js (STATIC) - index.html itself only got 6 new lines.
`tools/i18n_tables.py --write-en` regenerates en.json from the code (tr("key","English") etc.), `--check` finds
missing keys/placeholders, `--missing es` lists what a table lacks. Arabic sets `dir=rtl` and usability.css flips
the sidebar, menus and text alignment. **LOKI answers in the user's language**: `LOKI_REPLY_LANGUAGE` match
(default: the language the user writes in, the window's language as the fallback, never drifting) / ui / en (the
old `_ENGLISH_RULE`, unchanged); `engine/loki.py _language_rule()`. Not translated yet: app.js's dynamic strings
(status line, "New chat", notices), the Settings panels' own contents, and LOKI's replies to errors.

**5. Installers for other people** (docs/INSTALL.md): `tools/make_release.py` (seed tree of git-tracked files minus
tests/mobile/cloud/CI/big docs + RELEASE.json, zip, manifest with sha256, signed with tools/loki_sign.py when
LOKI_SIGNING_KEY is set), `packaging/windows/loki.iss` (Inno Setup, per-user, no admin), `tools/macos/make_dmg.sh`
(self-contained Loki.app + .dmg; optional Developer ID signing + notarization), `packaging/installer/bootstrap.ps1
/.sh` (first run: pinned uv + checksum -> standalone Python 3.12 -> `<data>/.venv`), `packaging/installer/
loki_launch.py` (stdlib: installs the seed into `<data>/versions/<v>`, pip installs changed requirements, runs the
current version with `LOKI_RELEASE_ROOT`, starts again on exit 76), `.github/workflows/installers.yml` (manual or
v* tag only; builds release + Windows setup + dmg + bootstrap smoke tests; NOT run here). **Packaged updates are
safe**: `engine/release_update.py` - signed feed (pure-Python RSA verify against keys/loki_public.pem; unsigned is
refused by default; https only), sha256, safe unzip, pre-flight (the new tree's own `--self-test` + `ui_missing`),
switch with trial (`pending` until /ui/ready), rollback to last_good + skip with reason, history, keep 3 versions.
`engine/updater.py` dispatches to it when `LOKI_RELEASE_ROOT` is set (update/check/status/health/mark_good/
on_trial/rollback/check_now/run_forever) so Update everything, the banner and Settings > Machines work unchanged;
`app/loki_app.py` exits 76 to the launcher after a release switch or rollback (`RELEASE_MODE`). The git path and
FROZEN (PyInstaller, which still does not self-update - documented) are untouched.

**Tests**: tests/test_usability.py (in SUITES; 137 checks in ~30 s by default - the owner's one-minute rule - with a quick pre-flight stand-in and one headless page after the tour; `LOKI_SUITE_SLOW=1` runs all 166 incl. the real pre-flights, ~3 min): tables complete, gallery/help content, the
engine routes, the language rule, the release updater end to end with this repo as the release (good update ->
trial -> good; broken engine -> refused + skipped; missing window file; bad checksum; `../` zip; rollback; openssl
signature verified in pure Python; unsigned refused), the launcher's relaunch loop, the installer files; headless
Chromium: the whole tour by keyboard (wrong + good key), the tour hidden for existing users, skip link, gallery,
help, Settings arrows, 130% zoom without sideways scroll, Arabic RTL, high contrast + colour-blind + reduced motion,
and LOKI's own accessibility rules (`tests/a11y_rules.js`: names, alt, ids, tabindex, lang/dir, dialogs, roles,
aria refs, 4.5:1 / 7:1 contrast - axe-core could not be vendored: no npm registry from the sandbox). Screenshots:
docs/operations/screens/usability_*.png (onboarding 1-4, gallery, settings, Arabic home/gallery/onboarding, high
contrast). tests/test_ui_smoke.py stays green (the tour shows only for an engine that says `done:false`).

**Not verified here (needs a real machine):** the real pywebview window (WebView2 / WKWebView) with any of this;
iscc on the .iss (written without Inno Setup); make_dmg.sh / hdiutil / codesign (Linux sandbox); the bootstrap's
real downloads (uv 0.8.0's URL and Python via uv - no GitHub release downloads from the sandbox); a real install on
a clean account; VoiceOver/NVDA; the translations' quality (machine-drafted). ZIVA W35 (PC) and M26 (Mac). **Needs
Mohamed**: the GPL/AGPL ports must go before anyone else gets an installer; a public release feed; who holds the
release signing key.

## Session 29 documents & data (worktree)

The owner: "a useful app that can help people and can turn into anything". This is what most people need help
with: DOCUMENTS, FILES AND DATA. Built in a Claude worktree, committed there, not pushed; the parent merges and
ships. **tests/test_documents.py (143 offline checks, ~20 s; every sample file is generated in the test) and tests/test_files_ui.py (15 checks, ~13 s: the Files view in headless
Chromium against the real files_api, with a screenshot) are in SUITES.**

- **Read anything** (`engine/doc_read.py`, `convert(path)` -> Markdown + sections with ANCHORS: `p3` PDF page,
  `slide-4`, `sheet-sales`, `s2-introduction` heading, `ch-5` e-book chapter, `msg`/`att-1` e-mail, `img`; the
  Markdown carries them as `## Page 3 {#p3}`; a citation is `report.pdf#p3`). Built-in standard-library readers
  for DOCX (headings, lists, bold/italic, links, tables, alt text, page breaks -> page numbers), XLSX (shared/rich
  strings, dates, cached formula values + the formulas), PPTX (presentation order, shapes top-left first, tables,
  charts as tables, alt text, notes - MarkItDown's logic, ported), CSV/TSV, HTML (web_reader), EPUB, EML (body +
  attachments read too), notebooks, text. PDF: docling (opt-in) > pdfplumber (text + tables) > pypdf > pypdfium2 >
  a small built-in reader. A page with no text is a scan: rendered (pypdfium2/PyMuPDF) and OCR'd (RapidOCR >
  the tesseract program). Pictures: OCR + `describe=true` asks the vision model (LOKI_VISION_MODEL). .doc/.xls/
  .ppt/.rtf/.odt via LibreOffice when installed; anything else via MarkItDown when the documents add-on is on.
  Zip-bomb and XML-entity guards. Conversions cached in harness_data/documents/cache/ (size + mtime).
- **Write anything** (`engine/doc_write.py`): Word (python-docx, from Markdown; edit = replace keeping run
  formatting + append), Excel (openpyxl: `=SUM()` cells are formulas, numbers/dates typed, header styled, frozen,
  auto widths, bar/column/line/pie/scatter/area charts; edit cells/rows/charts), PowerPoint (python-pptx: title
  slide, bullets with levels, table or picture beside them, notes; edit = replace text + add slides), PDF (pypdf:
  info, fields, fill text + checkboxes, merge, split by ranges, **sign_ready** = a signature page with one empty
  `/Sig` field per signer), Markdown -> PDF: Chromium (chromium add-on) > reportlab > LOKI's own small PDF writer
  (standard library: headings, wrapped text, lists, code, tables, JPEG pictures, page numbers; WinAnsi only).
  python-docx, openpyxl, python-pptx, pypdf added to engine/requirements.txt (small, pure Python).
- **Data** (`engine/data_sandbox.py`): `analyze` runs pandas in a CHILD process - an audit hook refuses sockets/DNS,
  subprocess, os.system/exec/spawn/fork, ctypes, and any write/remove outside its run folder (workspace/analysis/
  <time>/, also its TMPDIR); time limit kills the process group; memory limit = RLIMIT_AS on Linux + an RSS
  watchdog on every OS (Windows via K32GetProcessMemoryInfo); only a few env vars. No code -> a profile (missing
  values, totals, top group, trend over the date column, strongest correlation) + up to 4 charts; with code -> `df`,
  `dfs`, `show()`, `chart()`, `finding`. Without pandas a standard-library profile still answers. `sql`: DuckDB
  (tables loaded, then external access off + configuration locked) else SQLite in memory (query_only, progress
  handler deadline); one SELECT/WITH only.
- **Agent tools** (loki.py, ONE block before the agent loop): `read_document` (pages=/section=, parts with "read
  on with..."), `write_document` (.docx/.xlsx/.pptx/.pdf/.md/.html; no silent overwrite), `edit_document`,
  `pdf_tools`, `analyze_data` (answers with `![chart](analysis/...png)` lines), `data_sql` (errors list tables +
  columns), `documents` (collections: search/add/remove/index/collections). Category "documents"; the writers are
  MODIFYING. `read_file` on a PDF/Office/picture/e-mail now goes through read_document (it used to crash on decode).
  Local-model priority: read_document, write_document, analyze_data after read_web.
- **Files view** (`app/ui/files.js` + `files.css`, a folder icon above Settings, `engine/files_api.py`, bridge routes
  `/files/*` + a raw-body `POST /files/upload`): browse the workspace (no dot folders, no harness_data, nothing
  outside), drag & drop onto Files (into the folder shown) or onto the chat (into uploads/, the message box names
  it), "Add files" picker, preview: PDF page picture + text with ◀ ▶ (picture needs pypdfium2), pictures, tables
  (CSV/XLSX with sheet chips), Markdown for the rest; Ask LOKI about this file, Open (default app, documents/
  pictures/data only - never programs), Save as Markdown; recent files; places = Workspace + collections; "Chat
  with this folder". Icons with tooltips (data-icon). In the chat: pipe tables render as tables (app.js
  renderMarkdown, 6 lines), file paths in replies open in Files, picture paths and `![..](analysis/..png)` show
  the picture inline.
- **Chat with your documents** (knowledge.py, no second index): documents are a SOURCE of the same ProjectIndex -
  the workspace index now converts PDFs/Office/EPUB/EML/CSV too (cached, budgeted, OCR off), chunks per page/
  section, and cites `file#anchor`. A collection = a folder (harness_data/documents/collections.json) indexed by
  the same class (OCR when asked); `knowledge.search_documents`; `memory.knowledge_hits` adds collection hits, so
  memory.pack() (chat, jobs, teams) carries them as `[Contracts/lease.pdf#p3] ...`.
- **Add-ons** (capabilities/ + addons_install.PIP): documents (pypdfium2, pdfplumber, markitdown), ocr (rapidocr,
  onnxruntime), data-analysis (pandas, matplotlib, duckdb, pyarrow), docling (~2 GB, opt-in).
- **Research**: MarkItDown 0.1.8 (MIT, cloned) - ported its table, numbering-merge and PPTX logic; Docling (MIT)
  is the best PDF layout/table engine but needs PyTorch (~2 GB) - an add-on card only; RapidOCR (Apache-2.0) is the
  pip-installable OCR that works on Windows + macOS without a system program; Tesseract used when on PATH. PyMuPDF
  (AGPL) is used when present but not installed by LOKI (pypdfium2 does the rendering).
- **Verified here (Linux cloud box, Python 3.13):** test_documents with python-docx/openpyxl/python-pptx/pypdf/
  pdfplumber/pypdfium2/pandas/matplotlib/reportlab/Playwright + tesseract present: the scanned PDF and picture really
  OCR'd with tesseract, Markdown -> PDF really through Chromium, the sandbox really refusing network/writes/
  subprocess/os.remove and stopping a runaway loop and a 3 GB allocation; the Files view in headless Chromium
  (open, PDF preview, CSV table, a real DataTransfer drop, Ask LOKI, chat table/inline picture/file link,
  screenshot). One full `ship.py --check` with this work: every suite green except test_harvest (my tool-priority insert pushed web_search out of the first ten - fixed, test_harvest 149/149); the confirming full run was stopped by the new 1-minute rule; after the split: --self-test OK, test_documents 143/143 (19 s), test_files_ui 15/15 (13 s), test_ui_smoke 7/7, test_harvest 149/149.
- **NOT verified (needs the real machines - ZIVA W35 PC, M26 Mac):** pip installs (pypi is blocked here) - RapidOCR
  and DuckDB were NOT available, so the rapidocr path and the DuckDB SQL path are untested (written to their
  docs); WebView2/WKWebView drag & drop (pywebview may swallow file drops on macOS - the Add files picker is the
  fallback); the Windows memory watchdog and `os.startfile`; Docling; LibreOffice conversion of .doc/.xls; real
  user PDFs/spreadsheets; a live model using the tools and citing pages.
Last updated: 2026-10-17 (session 29, Claude in the cloud; LOKI Apps worktree).

## Session 29 LOKI Apps (worktree)

The owner: "i want a useful app that can help people and can turn into anything" - not the game. LOKI now builds
small apps for people, changes into the helper they need, and can be extended by anyone. Users and authors:
**docs/APPS.md**. Built in a Claude worktree, committed there, not pushed; the parent session merges and ships.

- **Mini-apps** (`engine/apps.py`, `engine/apps_api.py`, `app/ui/apps.js` + `apps.css`): an Apps area (grid icon
  under New chat, data-icon tooltip) with My apps / Gallery / Modes / Extensions. Each app runs in an iframe
  `sandbox="allow-scripts"`; its files come from `GET /apps/<w|t|x|p>/<name>/<file>` (no token - a sandboxed frame
  has none - Host-checked, app folder only, safe types) with `apps.APP_CSP` (no network, scripts from files only,
  CSP `sandbox allow-scripts` even when opened directly). The window side of the bridge identifies the app by
  the frame a message comes out of (never by the message) and calls `/apps/storage`, `/apps/ask`, `/apps/files/*`
  with the token. File saves and opens go through LOKI's own dialogs in the main window.
  Store: `harness_data/app_data/<app>.json`, per key `{v, t, h, d}` (last writer wins, ties by machine name,
  tombstones). Saved files: `<workspace>/App files/<app>/`, never overwritten.
- **Sync**: `POST /peer/apps` (peers.py block + peer_link callback): summaries first, then only the apps/data the
  other side lacks; removals are tombstones (`_removed.json`), removed apps go to `app_data/.removed/`. Loop:
  started lazily by the first /apps or /personas call (`apps.ensure_sync_thread`), 5 s after a change and every
  `LOKI_APPS_SYNC_S` (300); `LOKI_APPS_SYNC=0` turns it off.
- **Kit + gallery** (`app/ui/appkit/`): appkit.css (midnight navy, cyan->emerald, light mode), appkit.js (`loki.*`
  bridge, `kit.*` components - its header comment is the reference the guide shows the model) and 12 templates.
- **Agent tools** (loki.py session-29 block, registration only): `app_builder_guide`, `make_app`
  (create/update/install/read/list/data; refuses inline scripts, onclick=, CDN, fetch, localStorage, alert, eval,
  JS syntax errors via node --check), `app_ask` for the bridge (one `_port_ask` with the app's data). make_app is in
  MODIFYING (never in Plan mode).
- **Modes** (`engine/personas.py`, `app/ui/modes.js`): Tutor, Writer, Coder, Researcher, Life admin, Small
  business, Student, Creator + own (`harness_data/modes/`), export `<workspace>/LOKI modes/<id>.lokimode`, import
  scanned with skill_scan.BLOCK_PATTERNS. Applied by wrappers AROUND `system_prompt` (adds "# Mode: ...") and
  `_tool_enabled` (only when a mode sets only_tools); `apply_persona()` puts the mode's tools first for small
  models. The picker sits left of Ask/Plan/Build; starter prompts replace the welcome chips.
- **Extensions** (`engine/extensions.py`): `extension.json` (`loki-extension/1`: python tools, app, panel, mode).
  `POST /extensions/scan` stages (folder copy, or `git clone --depth 1` https only, no prompts, `.git` removed) and
  scans (user_tools.scan per tool, skill_scan patterns on every text file, skill_rules, undeclared programs noted,
  name clashes with LOKI's tools blocked); `POST /extensions/install` after the owner's click (re-scanned, tool
  tests run). Tools run via `extensions.execute` (the user_tools sandbox) and ask every call
  (`approve("extension_tool", ..., decidable=False)`) unless trusted.
- **Bridge**: one file-serving method `_serve_app` + one GET block + one POST block (read before `_read_json`,
  6 MB bodies for app data). index.html: 1 stylesheet, 2 scripts, 1 button; icons.js: the `grid` icon; app.js
  untouched.
- **Tests**: tests/test_apps.py (131 checks, ~35 s) in SUITES - templates, make_app rules, storage merge, files,
  personas, extensions (stage/scan/block/install/git clone/sandboxed run), two-machine sync with a fake peer, the
  loki.py tools + wrappers + approval, the real bridge over HTTP, and headless Chromium: the window starts, every
  template runs under the real CSP, Budget in its sandboxed frame stores through the bridge, cannot reach the
  parent/storage/network, gets an "ask LOKI" answer, a file save asks in LOKI's window (approve + decline), the mode
  picker sets Tutor. `LOKI_SUITE_SHOTS=<dir>` keeps screenshots (looked at: gallery, Budget + ask, save approval,
  mode picker). Also green here: --self-test, test_ui_smoke, test_loki, test_peers, test_play.
- **Not verified here**: WebView2/WKWebView (file dialogs from `<input type=file>`, WebKit and the sandboxed frame's
  `'self'` scripts, color-mix), a real model answering "ask LOKI" or building an app with make_app, real sync
  between the Mac and the PC, a real git extension from GitHub (the clone path was tested with a local repo).
  ZIVA W35 (PC), M26 (Mac). In headless Chromium a synthetic click right after an app's first render sometimes
  did not reach the frame; the suite drives the bridge with calls instead - watch for "first click ignored" on
  the real machines.

## Session 28 task success (worktree)

The owner: "do not focus on the game, the core systems aren't fleshed out yet" - #1: **agents finish real
tasks.** Session 27 fixed what the PC's job logs showed; nobody had proven the loop works across realistic
tasks. Now there is a benchmark, and the loop was fixed until it passes.

- **tests/tasks/** (`base.py` checks + scripted-step helpers, `catalog.py`): 31 owner tasks - write a doc
  (README, meeting notes, changelog, an email), edit code and run its test (fix a bug, add a function, rename
  across files, JSON config, a CLI script), research with sources (a file with links, a question answered with
  a link, a comparison table), pictures (incl. "the image maker is not set up" -> must end BLOCKED), summarize
  a file (report, a 3,000-line log, a CSV total), plan a project, multi-step builds (website, package + tests,
  todo CLI), two team jobs (one where the tester finds a bug and the fix round fixes it), tasks that need an
  assumption, and tasks that must end BLOCKED honestly (deploy without credentials, a missing file, a purchase,
  a job that never ends). Checkers look at the real result: files + content, tests that run, real picture
  bytes, sources that came from a tool (no invented links), a DONE line that names only files that exist, no
  fake media, team agents that really finished.
- **tools/task_bench.py**: runs them through the REAL `loki.run_job` (a child process per job, LOKI_WORKSPACE =
  a throwaway folder, LOKI_JOB_ID set - exactly like a job from the app), team tasks through `team.TeamRunner`
  with a synchronous jobs adapter. `--model local|bonsai|smart|groq|openrouter|claude-code|...` (comma list),
  `--tasks`, `--kind`, `--jobs`, `--timeout`, `--no-escalate`, `--keep`, `--list`. Records success, status,
  steps (model calls), tool calls, tokens, time, escalation, the longest request, and the failure reason;
  writes `harness_data/bench/<date>.json` (all models that day), `latest.json`, `<date>.md` (the table) and a log
  per task in `harness_data/bench/logs/`. Experience logging is off for bench jobs (synthetic tasks must not
  skew routing). `--scripted` swaps the model for scripted fakes that replay small-model behaviour seen in the
  PC's logs, and the web/image specialists for fixtures; `--scenario cheat` plays models that never do the work.
  The scripted model also flags a call to a real tool the loop did not OFFER (that is how the run_command gap
  below was found).
- **Scripted, the same catalog: 15/31 on the engine before this session, 31/31 after.** The 4 cheat scenarios
  fail both times (0/4), but before 3 of them ended "DONE" in the loop (fake email/summary/picture accepted);
  now those end BLOCKED and only the invented-link one ends DONE (the bench's source check catches it - the
  loop cannot know a link is made up). tests/test_task_success.py (94 checks, ~3 min, in SUITES).

**What the scenarios exposed, and the fixes (engine/loki.py goal loop unless noted):**
1. *A team "verified" buggy code.* The tester's `DONE: PASS` was rejected as premature (it writes nothing by
   design), it stalled, the job ended with a plain "task halted" and exit 0, and team.py counted that as a pass -
   in team-primes this hid the tester's real FAIL. Read-only team roles (tester, reviewer, researcher, browser)
   are exempt from "nothing was written"; a halted job now ends **BLOCKED** (exit 2) with its partial work, so a
   team says "needs you". Same for "stopped calling tools" and the step limit.
2. *No model could ever run a command.* `run_command` was not in MODEL_TOOL_NAMES and the "system" category is
   off by default, so a job started with allow_commands (and every team Tester/Builder) could not run a test.
   run_job now offers it in that process only (policy + risk checks unchanged; the owner's setting not saved).
3. *Team agents on a local model could not reach their board* (team_post/team_read fell off the 22-tool list):
   they lead the list when LOKI_TEAM_ID is set.
4. *DONE in the last line of a prose reply* was not seen (head-only check) and the job looped into "halted":
   `reply_outcome()` reads a DONE:/BLOCKED: line anywhere (first line as before, else the last upper-case one);
   run_job's exit code and the request status use it.
5. *Premature DONE on goals without a "create/write..." word* ("Draft an email ... save it as email_draft.txt",
   "Summarize report.txt into summary.md" with the summary in the reply): a file the goal asks to PRODUCE
   (`_goal_outputs`: a name right after write/create/save as/into/to..., not yet there) must exist before DONE.
   A picture request needs a real picture file (a .txt next to it is not one).
6. *Final self-checks before DONE*: nothing in the task succeeded (every call refused/failed, or none) -> pushed
   back once ("deployed to S3" after the deploy was refused now ends BLOCKED: needs credentials + permission);
   the DONE line names a file that does not exist -> pushed back once.
7. *BLOCKED guesses*: BLOCKED before trying any tool is pushed back once ("look first"); an honest BLOCKED after
   that stays BLOCKED (blocked-purchase), then escalation as before.
8. *Questions nobody can answer*: a question in a background job gets "assume, do it, say the assumption in
   DONE" (twice at most); it used to loop to "halted".
9. *Python with a syntax error passed as "no automatic check"*: verification now syntax-checks .py, .toml, .xml
   and JS/TS/CSS (lint_guard.check); errors go back to the model like a broken JSON.
10. *A native call to the role name "image"* was rejected by the tool guard before call_tool could route it to
   the conductor: `_guard_call` now maps role names (image, generate_image, research...) to conductor(role=...).
11. *A 120,000-character reply filled the context*: prose replies over LOKI_MAX_REPLY_CHARS (24,000) are kept
   head + tail in the history (the DONE line is read from the full reply).
12. *Job timeouts*: a job now has a deadline (`deadline_s` in the job file - workers.py passes timeout - 60 s -
   or LOKI_JOB_DEADLINE); at it the job stops with "BLOCKED: hit the job's time limit. Partial work is kept: ..."
   and the result file is ALWAYS written (it was empty when a job was stopped by a budget or a missing model).

**Nightly on the PC**: autopilot duty `task_bench` (LOKI_TASK_BENCH auto = on on Windows, off on the Mac; window
LOKI_TASK_BENCH_HOURS=1-6 local; LOKI_TASK_BENCH_S=72000; models LOKI_TASK_BENCH_MODELS=local,smart) starts
`tools/task_bench.py` in the background right after the health check, once a night, when idle; while it runs
nothing else starts. **Settings > Lab** has a separate "Task success" section (app/ui/bench.js, GET /bench, 2
lines in index.html, 1 in app.js, 4 CSS lines; lab.js untouched).

**Not verified here (no model, no GPU, no network):** no real model has run the bench - only the scripted fakes.
The real numbers for qwen3:8b, Bonsai 2 and smart are ZIVA W28. The nightly duty is tested with a fake process
only; the Lab section was not seen in a real window (UI smoke test covers that index.html loads).

## Ziva (Mac), 2026-10-18 (2): the Session-26 UI check - Memory panel and the Draw pad

Both halves of the `[mac] Session 26 UI check` are done, driven in Chrome over CDP against the live engine
(the app's WKWebView is not scriptable). **Settings > Memory works**: the list groups every memory by kind
with its origin and per-row ✎/✕, Search returns the recall path with BM25 scores (a query of "scratch"
scored 1.000 for the exact memories), Edit raises a real `window.prompt` and saving keeps a "Before (1)"
history row, and Forget removes the row at once - with no confirmation dialog, which is worth knowing before
scripting it. Only scratch entries of mine were created and forgotten; the Mac's real memories were not
touched. Two Mac notes: the panel reports "local embeddings - no embedding model installed in Ollama", so
recall here is keyword-only until one is pulled, and the shared-memory line shows the PC link down.

**✎ Draw works, but the LOCAL model does not draw.** The local qwen3.5-9b agent answered "draw an arrow from
the top-left to the middle on my pad" with computer-use calls (open_app "Draw"/"NotePad") and then claimed in
Chinese that `sketch_reply` is missing - it is not missing, it is a small-model tool-choice failure. With
`POST /setup/prefer {"prefer":"cloud"}` the same sentence drew it first try (one #ff2d55 arrow 80,80 ->
500,450 in sketches/loki-<time>.json), so if a Mac user says "it never draws on the pad", try a stronger
model before touching the tool. The pad itself is correct: separate layers (my stroke above LOKI's arrow),
the "LOKI's drawing" toggle hides only LOKI's layer, Pen/Marker/Eraser, colours, undo/redo/clear, attach to
message. One nit to check with a human click: in a headless browser the composer's ✎ Draw button computes to
0x0 px.

## Ziva (Mac), 2026-10-18: computer use on macOS - works, but both TCC grants are missing

The computer-use add-on works on the Mac (Quartz mouse/keyboard, `open_app`, the approval prompt, the kill
switch, the action log) - what is missing is the two macOS permissions, which only Mohamed can grant:
**System Settings > Privacy & Security > Accessibility** (no accessibility tree until then, proved by
`computer(action=elements)` answering "(no accessibility tree for this window...)") and **Screen Recording**
(`computer(action=screenshot)` -> "screencapture failed - give the app running LOKI Screen Recording
permission"). Grant them to `/Users/mohamed/Applications/Loki.app` and to the Python that Loki.app launches
(`/opt/homebrew/Cellar/python@3.13/13.3.16/.../Resources/Python.app/Contents/MacOS/Python`), then restart.

Two things to fix in the code once the tree works, both seen live: (1) **after `open_app` the app is not
brought to the front** - TextEdit opened with no window and the next action targeted `python`, i.e. LOKI's
own window, where typing would have gone; activate and verify the frontmost app before typing. (2) LOKI
should refuse to drive its own process - typing into its own chat box is never right.

The approval flow itself is fully scriptable: `GET /approval` returns the pending ticket and
`POST /approval {"id":..., "approved":bool}` answers it, which is how these tests said Yes and No. The kill
switch works exactly as documented: Ctrl+Option+Esc (a real Quartz key event) tripped it
(`armed: false`, `tripped: "kill hotkey pressed"`), every later action was refused in the same chat, the
recent-actions log showed the whole run, and `POST /computer/arm {}` re-armed it (a body is required - a
bare POST gets "Request body is empty or too large.").

Also on the Mac, all in this session: Settings > Tools health map "86 work · 17 need setup · 28 off" with
no Broken/Failing row (docs/operations/screens/tools-health-mac.png); GitHub connector -> "signed in as
m03dev", a real issues call, and the create-issue approval appeared and was declined (nothing created);
Chromium add-on on and verified directly (Hacker News 228 numbered elements in 1.7s, react.dev 105 in
2.8s); email/calendar/Google still unset (Needs Mohamed); peer_files not run because the PC link is down
("cannot reach pc at http://127.0.0.1:49952 - Connection reset by peer" with relay true - the PC needs to
start/update LOKI).

## Ziva (Mac), 2026-10-17: the task-success bench now runs on a Mac (the third real fix)

`tests/test_task_success.py` failed deterministically on the Mac (90 passed / 4 failed; `build-todo` and
`team-primes` ended BLOCKED) and `tools/task_bench.py --scripted` gave 29/31 - so `ship.py` refused to push
anything. Root cause, straight from the job log: the tasks' scripted models run commands such as
`python todo.py add buy milk`, and **macOS has no `python`** (only `python3`), so `safe_exec` rightly refused it
("program not found on PATH: python"); todo.py therefore never produced `todos.json`, the loop rightly rejected
the DONE claim ("the DONE line names todos.json, which does not exist"), the script ran out of steps and the job
halted BLOCKED. The checks already swapped in `sys.executable`; the scripts did not. Fixed in
`tests/tasks/base.py` (`PY_BIN` + `pycmd()`) and `tests/tasks/catalog.py` (9 scripted run_command steps):
`--scripted` is **31/31** on the Mac and the suite is 94 passed / 0 failed. Worth remembering for the PC too -
the bench must run on whichever machine it is pointed at.

## Ziva (Mac), 2026-10-17: two flaky suites fixed at the source - the MMO "sold on one machine" tie, and the peer link refusing its own retries

- **The peer link refused its own retries, and that is very likely the "link flaps" report.** A request's
  signature was HMAC(method, path, `"%.3f" % time.time()`, body) and the replay guard refuses any signature it
  has seen before, so **two identical requests inside the same millisecond** - a retry through the relay, or two
  parts of the engine polling the same endpoint - made the second one come back as "replayed request" (HTTP
  401). That reads as the other machine being down. Fixed with a fresh `X-Loki-Nonce` per request inside the
  signed message; a verifier that finds no nonce still checks the old form, so the two machines keep talking
  while one is still on the previous build, and a genuine verbatim replay is still refused. tests/test_peers.py
  grew 6 checks; 6 green runs in a row. **The same shape exists in engine/phone_link.py (line ~307) - worth the
  same fix.**
- **The shared MMO profile dropped changes made in the same millisecond.** `mmo_state` stamped last-writer-wins
  fields with `round(time.time(), 3)` and merged with a strict "newer wins", so a sale performed in the same
  millisecond as the change it replaced was silently ignored - intermittently the sword sold on one machine
  stayed in the bags on the other (tests/test_mmo_systems.py flaked: 1 failure in 2 runs). Now
  `STAMP_DECIMALS = 6` via a `stamp()` helper, with 4 new checks; 6 green runs (125 passed).

## Ziva (Mac), 2026-10-17 (patch 224): M14-M17 (session-27 ports) - two findings worth acting on

- **M15 voice works, M16 research works, M14's API works.** `say` wrote the aiff; after `brew install
  espeak-ng` and **`pip install --only-binary=:all: kokoro soundfile`** (the plain form FAILS on this Mac -
  Python 3.13 tries to build blis/spacy from source and dies in Cython), Kokoro produces a real 24 kHz wav:
  60.4 s the first time (weights + spacy model download), **1.7 s warm per sentence**. web_search and
  research_web answer with real, numbered sources (no SSL error), browse_page drove Wikipedia end to end, and
  the skills catalog lists 583 skills / 91 agents including all six anthropic ones.
- **THE PEER LINK FLAPS.** `GET /peers` gave ok true / 3484 ms earlier the same session and ok false / 835 ms
  later (the world drew the PC island as offline). Presence/MMO checks must look at /peers first; a flapping
  relay is the most likely reason "the other machine did not answer" reports come and go.
- **The Godot world (`game/loki-world`) loads on Godot 4.8, but its own headless tests are FLAKY.** A fresh
  checkout needs `godot --headless --path game/loki-world --import` first, otherwise the first run throws a
  cascade of bogus "Could not find type \"IslandBuilder\"/\"Actor\"/\"FakeWorld\"" parse errors (the global
  class cache does not exist yet). After that: 0 script errors, but
  `godot --headless --path game/loki-world res://tests/run_tests.tscn` gave "105 passed, 2 failed" once and
  "101 passed, 1 failed" twice, failing **"failed jobs are monsters"** and then crashing at
  tests/run_tests.gd:146 (`monsters_alive()` is EMPTY, so the fight/XP/loot checks never run). It happens with
  a dead `--loki-url` too, so it is a timing/order race in the first sync, not the engine connection - worth
  fixing before the MMO is called done. `test_godot_world` passed 75 but only did static checks (no Godot
  binary on PATH), which is why this went unseen.
- The interactive halves (Play in the app window, the Godot editor window) are left to a human hand on
  purpose: no window was opened on the owner's screen.

## Ziva (Mac), 2026-10-17 (patch 219): the Babylon world verified in the app's own WebKit - and the connection-drop bug behind broken windows

Read with session 27/28 below: this is a *cause* of the same family of complaints, found on the Mac.

- **BUG FIXED AND SHIPPED - the engine dropped connections while a page loaded.** `BridgeHTTPServer`
  (engine/loki_bridge.py) used `socketserver`'s default accept backlog of **5**, while one page load asks for
  ~25 files at once (index.html pulls every panel script). Measured against the live engine: 60 simultaneous
  requests -> **46** "Connection reset by peer"; 120 -> 92. A browser shows that as ERR_CONNECTION_RESET /
  ERR_SOCKET_NOT_CONNECTED, and it happened for real during a Chrome load of the UI: `play_panel.js`,
  `creations.js`, `icons.js`, `brain.js`, `workbench.js` and `sketch.js` all failed to load - a window with
  **dead panels** (Play, Creations, Brain, the drawing pad), or **blank** if `app.js`/`app.css` is one of the
  dropped ones. That matches "the Mac shows a white window" and the PC reports. `request_queue_size = 128` now;
  re-measured **0 resets** at 60 and 120 concurrent requests, guarded by
  tests/test_systems.py ("the bridge takes a whole page load at once"). It costs nothing and helps every load.
- **The blank-window guard works, and it is what caught the above**: boot.js wrote the failed loads to
  engine.out and `/health` -> `ui_errors`. Its gap: a *script* error is reported as "error at ?:0:0" with no
  message, file or line (both in the bridge log and in `ui_errors`), which cannot be diagnosed - worth adding
  `e.error.stack` when the message is empty (not changed here; the cause would have been a guess).
- **LOKI World is Babylon in the app's WKWebView, in the pixel cel-shaded look.** Verified in the real window
  (`docs/operations/screens/babylon-world-mac.png`, `babylon-two-islands-mac.png`, `babylon-fox-mac.png`,
  `babylon-world-panel-mac.png`): WebGL2 (no WebGL1 fallback), quality "high", 33.4-33.6 ms behind the glass =
  its 30 fps cap with 0 late frames in 500+, 16.7 ms (~60 fps) in the World panel, the 3-px pixel grid and the
  Bayer posterize confirmed pixel-by-pixel, no console errors (only the pre-existing `/favicon.ico` 401). CPU
  with the world running (2 min): WebKit.WebContent 11.3% median + WebKit.GPU 8.0% + the app 5.1%.
  Islands: the Mac's island, the PC's island out in the space around it, click to fly there, "back to <name>".
  The Mac<->PC relay link came up during the session ("pc via relay - 3277 ms", `GET /peers` ok true, the PC's
  hello = patch 219) - it works but is not perfectly steady (one "(timed out)" in the world while /peers was ok).
- **Creations needed image-gen switched on** (it was off on this Mac, and the wall said so clearly); enabled,
  a fox picture was made here through the free pollinations backend and now heads the wall and the island's
  creations hall. Say if you want image-gen off again.
- **test_research_ports failed on macOS only** (so `ship.py` refused to push): `repo_map.source_files`
  walks the RESOLVED root while the test compared against the unresolved one - on macOS `/tmp` is
  `/private/tmp`, so `relative_to` raised ValueError. The production path (`build()` resolves its root)
  was fine; the test now resolves too and the function says so in its docstring. 141 passed.
- **Bonsai 2 now works on the Mac - and pinning a local model no longer breaks its context.** Bonsai 2 9B
  (Q2_0, 3.2 GB) was already pulled on this Mac; it loads and answers at 6-17 tok/s (vs the local qwen3:8b's
  1.4). The bug: `POST /setup/use` ("use this model") pinned the RAW tag with no long context, while the
  one-click setup has always wrapped it as `loki-<model>` with num_ctx. With Ollama's 4096 default the agent
  prompt (system + 22 tool schemas + history) is already ~4k tokens, so Ollama truncated it, the user's message
  fell off the front, and Bonsai 2's strict GGUF Jinja template answered HTTP 500 ("No user query found in
  messages") - LOKI then answered from vireonix "auto" without telling the owner. Fixed:
  `model_setup.with_long_context` (used by `/setup/use`; 16384 on this 16 GB Mac) + tests in
  test_models_media; verified live: 0 template errors, all local calls 200, a 3-message chat and a background
  job that really wrote its file. Still open: the second turn of a chat still reports provider vireonix in the
  usage line even with prefer=local (an extra cloud call in that turn - unexplained).
- **The app now restarts itself on an update** ("restarting the whole app on the updated code"): seen twice,
  cleanly, one window each time (patches 211, 218, 219). Memory on the Mac is back to NORMAL (pressure 1, 78%
  free, swap 1517/3072 MB, no llama-server) and `GET /forecast` is on the real TimesFM-3 (mlx) backend, p50
  8.1 s / p90 37.4 s per forecast, nothing to unload. The Mac's local model answers at ~1.4 tok/s (~30 s a turn).
- **Open on the Mac:** clicking panels *inside* the app window cannot be scripted - WKWebView has no usable AX,
  the page CSP (`script-src 'self'`, no `unsafe-eval`) refuses scripted evaluation, and a real synthetic click
  cannot hit a world label because the world spins. So Play (Fox & Berries) and the Brain map were verified in
  Chrome over CDP; **one human click on Settings > Play in the app closes M12/M13's last gap**. M14/M15/M16/M17
  (session 27) are untouched.

## Session 28 models & routing (worktree)

The owner: "the core systems aren't fleshed out yet" - MODELS & ROUTING: always the right model per task, never a
dead end. From the reports: Gemini quota / Groq rate+size limits mid-task, rejected keys (mistral/together/
cerebras), deepseek out of credit, the PC's Ollama 0.40.5 cannot load Bonsai, background jobs on the local 8B
after an 'easy' triage, Claude Code argv limits (fixed in session 27: long prompts on stdin). Built:
1. **Provider health registry** (`engine/provider_health.py`): every error shape -> state + until + reason + a
   one-line fix, persisted in `harness_data/provider_health.json` (key hash only) so jobs and restarts know;
   free background probes (GET /models, OpenRouter /key, DeepSeek /user/balance - never a completion) every
   30 min, started by the bridge; model metadata (context, tools, vision) from the provider's list. Marks made
   in-process are forgotten when routing revives a provider (`loki._FailedSet`); others expire or end on a new key.
2. **Task-aware routing** (`engine/routing.py` + `loki.active_model_name/_smart_pick/_route_pick/route_for`):
   needs (kind, difficulty, background, tool-heavy, pictures, tokens, local only) x abilities (tools
   native/prompted/measured, vision, context, code) x health x a learned success table per (provider[/model],
   task kind) from the experience log. Incapable providers go last (no dead end); never across cost tiers;
   paid only when allowed. **Background jobs** skip local-first when a free capable online model exists
   (keyless anonymous routes must earn it). `LOKI_LOCAL_ONLY=1` (General > Private) keeps all on this computer.
3. **Local models**: `model_setup.ollama_version/bonsai_support/ollama_upgrade` (winget / brew), Bonsai never
   picked/planned/downloaded on Ollama < 0.40.6; `required_context` + `ensure_context` re-makes a smaller loki-*
   variant; `model_context` reads num_ctx / trained / loaded (`/api/ps`); `loki._with_context` for local,
   local-hermes, loki-tuned and a pinned LOKI_LOCAL_MODEL; `condenser.LOCAL_WINDOW_TOKENS` keeps a local
   conversation inside the real window (Ollama drops the START of an over-long prompt = the system prompt +
   tools). MLX (8082, `default_model`) is the local fallback on a Mac with no Ollama tool model; mlx-vlm
   detected (Bonsai 2 MLX).
4. **Failover** (`_model_request` only): health recorded on every failure/success; empty choices retried once
   then failed over (was an IndexError); timeouts one retry; with another provider ready a 429 gets one quick
   retry and a long Retry-After is not waited on; `make_client` sets `max_retries=0` (the SDK's hidden retries
   waited up to 60 s); `should_fail_over` covers empty replies, timeouts and context-too-long in auto mode.
5. **`/models doctor`** (window `/models`, terminal `/models doctor`, Settings > Connections > Explain routing,
   `GET /models/doctor`): "Chat -> local ..., Code -> ..., Pictures -> ..., Long documents -> ..., Background
   jobs -> ..., Hard tasks -> ..., because ...", skipped providers + fixes, the local side, Needs you. Cards
   show the health line + fix; Re-check = `POST /providers/probe`.
tests/test_routing_core.py (142, fakes only: a fake OpenAI-compatible HTTP server for 429/402/401/context/
timeout/empty/413 and a chain of them; a second Python process reading the health file; FakeOllama now answers
/api/version, /api/ps and num_ctx in /api/show) is in SUITES; ship.py gives each suite its own
LOKI_HEALTH_FILE and turns probes off. **Not verified on a real machine:** real provider error bodies beyond the
documented shapes, real `/models` metadata, a real Ollama's `/api/create num_ctx` + `/api/ps context_length`,
MLX - ZIVA W28 (PC) and M20 (Mac). Needs Mohamed: new mistral/together/cerebras keys, deepseek credit, the
PC's Ollama update.

## Session 28 memory & knowledge (worktree)

The owner: "the core systems aren't fleshed out yet" - this one is MEMORY & KNOWLEDGE. LOKI now has ONE memory
model, ONE retrieval path, careful automatic learning, the same memory on every linked machine, an index of the
project's own docs/code, and an eval. Built in a Claude worktree; `tests/test_memory_core2.py` (112 checks) is in
SUITES.

**The model** (`engine/memory_core.py`, API kept): every memory has a KIND - profile, preference, person, project,
decision, fact (semantic), episode, lesson (episodic), skill (procedural = the learned SKILL.md files) - plus an
importance, a status (active / superseded, with `history`) and `review` ("new" when LOKI learned it by itself).
`engine/memory_kinds.py` names the kind and detects contradictions by rules: "the owner's editor is VS Code" then
"... is Zed" -> the newer SUPERSEDES the older (kept, restorable); "prefers dark mode" vs "prefers light mode" too;
"is working on X" vs "uses X" do not. Same text = refresh, near-duplicate = merge, secrets scrubbed (explicit
learn) or the whole sentence dropped (automatic learning).

**Storage** (`engine/memory_store.py`): `harness_data/memory_log.jsonl`, an append-only log of put/del operations
named (host, n) with a hybrid logical clock; the winner per item id is the largest (v, host, n) - last writer wins,
tombstones for forget, merge is idempotent and order-independent. Forget also REDACTS the item's text from older
operations. Compaction keeps a per-host floor so vectors never go backwards. A cross-process file lock (fcntl /
msvcrt) because the engine and job processes both write. Session 26's `memory_core.jsonl` is migrated on first
use (renamed `.migrated`). Local only: `memory_uses.json` (use counts), `memory_vectors.json` (embedding cache),
`memory_sync.json` (per-peer vectors, last sync).

**Retrieval - the one path** (`memory.py` -> `memory_core.retrieve` -> `memory_search.py`): BM25 (k1 1.2, b .75)
with a light stemmer and a small synonym table (pc~windows, gpu~rtx, boss~manager, publish~ship...), plus
embeddings from a LOCAL Ollama embedding model when one is installed (`LOKI_EMBED=auto|off|<model>`; never pulls
anything; vectors cached by text hash; at most 64 new embeddings per search; any failure -> BM25). A candidate
needs real evidence (enough of the query's rare words, or cosine >= .6). Score = relevance x recency by kind
(profile/preference/person/project/decision never fade; facts 180 d; episodes 30 d) x importance x usefulness;
near-identical results collapse; cut to a TOKEN budget. Prompt layout:
- always on: `memory.profile_block()` - the owner's notes (memory.md) + the most important profile/preference
  memories, capped at 350 tokens (`LOKI_MEMORY_PROFILE_TOKENS`); `loki.load_memory()` uses it (memory.md used
  to be pasted whole);
- per request: `memory.pack()` - reasoning_bank lessons (<= 300 tokens) + matching memories (pack budget,
  `LOKI_MEMORY_PACK_CHARS`) + project passages with `path:line` (<= 250 tokens), total <= 1000
  (`LOKI_MEMORY_PACK_TOKENS`); the owner's note lines are not repeated, relevant profile memories are (so they
  are cited in `memories_used`). `loki._triage` now makes ONE call to
  `memory.pack` (it used to call reasoning_bank.prompt_for and memory_core.pack separately). Chat, background jobs
  (run_job -> pursue_goal -> _triage) and team roles (jobs) all go through it.

**Automatic writing** (`engine/memory_extract.py`, called from `loki._record_experience` via
`memory.after_request`): rules over the OWNER's own messages only (never the model's replies or tool output):
"my name is", "call me", "I prefer/like/hate", "always/never ...", "from now on", "Mia is my sister", "my boss is",
"I'm working on", "we decided", "my X is Y", "remember that ...". Third person, no questions/small talk/"right
now" things, no secrets, max 3 per request, marked review="new"; never from a background job's prompt
(written by LOKI or a schedule; `LOKI_MEMORY_EXTRACT_JOBS=1` to allow). `LOKI_MEMORY_EXTRACT=model` + an `ask`
function lets a model do it through the same filters (NOT wired to a model in loki.py yet - rules are the
default). The reply metadata carries `memories_learned`.

**Sync** (`engine/memory_sync.py`, `POST /peer/memory` in peers.py, callback in peer_link.py): vector exchange
over the signed link (`{have, ops}` -> merge -> answer with the ops the caller lacks), batches of 1000, works
transitively through a third machine, received items scrubbed again. memory.md rides along as one document item
(first sync of two notes files = union of lines; afterwards the newer edit wins, older text in history).
`memory_sync.run_forever` (started by `peer_link.sync_forever`) syncs ~5 s after any learn/forget and every
`LOKI_MEMORY_SYNC_S` (300 s).

**Project knowledge** (`knowledge.ProjectIndex`): `harness_data/knowledge/<workspace-hash>.json`, incremental (only
files whose size/mtime changed are re-read, deleted files dropped, a time budget per refresh), Markdown chunked at
headings, code in ~900-char windows, `.env`/key/secret files and build/vendor folders skipped, chunks scrubbed.
Refreshed in a background thread when older than 2 min (`LOKI_PROJECT_INDEX=off` to disable); Settings >
Memory has Reindex. The Obsidian vault stays separate and read-only (brain.py).

**Settings > Memory** (`app/ui/memory_panel.js`, `GET/POST /memory/core` extended): "LOKI learned N things today"
with ✓ keep / ↶ undo (icons with tooltips), the machines it is shared with + sync now, search mode, project index +
reindex, a search box that shows exactly what a request would recall (scores + project passages), kind chips,
edit/forget, "Replaced by newer memories" with restore, learned skills; the memory.md box moved into "Your notes
for LOKI (always included)". The Brain map shows memories by kind and edits/forgets them by id.

**Measured** (offline, `tests/test_memory_core2.py`): 30 questions over 29 seeded memories + 2 episodes + 12
distractors + a superseded fact: 30/30 recalled into the request's pack, search alone 30/30 in its top 5, largest memory
context 382 tokens (profile + pack; budget 1350), 3 unrelated questions recall nothing; a toy local embedder finds a paraphrase BM25 misses and
keeps 29/30. Store/merge/tombstone/redaction/compaction/migration, sync Mac<->PC<->third machine incl. over the real
HMAC PeerServer, notes sync, project index, the bridge API, the loki hooks, and the Memory tab in headless Chromium
(render, undo, search) are all checked.

**Not verified here (needs the real machines - ZIVA W28 PC, M20 Mac):** two real machines syncing over LAN/relay; a
real Ollama embedding model (nomic-embed-text) - the hybrid path is tested only with a fake embedder; the Memory tab
in WKWebView; a live model actually USING the recalled memories / citing path:line; index speed on a large project.
Still open: the model-based extractor is not wired to a model; reasoning_bank/experience/skill_learning keep their
own files (they are candidates of the one retrieval, not migrated); knowledge index is per machine (not synced, by
design - each machine indexes its own checkout).

## Session 28 tools, connectors, computer use (worktree)

The owner: "the core systems aren't fleshed out yet" - TOOLS, CONNECTORS, COMPUTER USE. Everything LOKI's agents
can touch must work, be discoverable and be safe. Built in a Claude worktree, committed there, not pushed; the
parent session merges and ships. **tests/test_tools_core.py (200+ offline checks, fakes; plus REAL headless
Chromium checks where Playwright is installed) is in SUITES.** Research and usage: docs/integrations/COMPUTER_USE.md.

- **Tool health map** (`engine/tool_health.py`, `engine/tools_api.py`, `GET /tools/health`, Settings > Tools):
  every built-in tool, MCP server (from mcp_servers.json: connected / off / needs a command or key), add-on,
  connector, computer use and the browser - installed? configured? status, last success, last error (secrets
  scrubbed), calls/failures - and a one-click fix (`POST /tools/health/fix`: reset, enable_category,
  enable_addon (high-risk ones need the owner's confirm), install (pip + post steps, in a thread), enable_mcp
  (LOKI_MCP_ENABLE, next start), arm_computer). **Dead tools are hidden from the model:** a tool whose
  requirement is missing (unset connector, no Higgsfield key, ACE-Step not running, computer use unavailable or
  stopped) or whose last 3 calls failed for an ENVIRONMENT reason (cannot reach, not installed, 401/403...) is
  not offered (30 min cool-down, then offered again). A model-fault error never hides a tool; DENIED is not a
  failure. Store: harness_data/tool_health.json.
- **Connectors** (`engine/connectors.py` + one module each, standard library only, read-only by default, every
  write in `policy.ACTION_ALWAYS_ASK` = always asks, never decidable, refused in background jobs; secrets are
  SECRET settings in harness_data/.env, shown only as saved/not saved, scrubbed from every result and error):
  - `email` (conn_email.py): IMAP list/search (Gmail X-GM-RAW)/read (EXAMINE + BODY.PEEK: never marks read),
    draft = a local .eml in workspace drafts/ (nothing leaves), send over SMTP = **always asks**, the approval
    shows recipient + subject + body (a draft is expanded before the prompt). App password, or EMAIL_AUTH=google.
  - Google sign-in (conn_google.py): OAuth loopback + PKCE (Google forbids Gmail/Calendar scopes in the device
    flow), refresh token as GOOGLE_REFRESH_TOKEN, XOAUTH2 for IMAP/SMTP. Needs the owner's own OAuth client.
  - `calendar` (conn_calendar.py): Google Calendar API, CalDAV (iCloud/Fastmail/Nextcloud; REPORT + PUT) or a
    read-only iCal link; an iCalendar reader with RRULE/EXDATE; `create` asks.
  - `github` (conn_github.py): the gh CLI when signed in (argument lists, body on stdin), else a token; repos,
    issues, issue, prs, pr, search; create_issue/comment/close_issue/create_pr ask.
  - `notes` (conn_notes.py): an Obsidian vault (never hidden folders, write never overwrites) or Notion.
  - `peer_files` (conn_peer_files.py): files on the other machine over the signed peer link - new peer route
    `POST /peer/files` (peers.py + peer_link.py callbacks) serves only that machine's shared folder
    (LOKI_PEER_FILES_ROOT, default ~/LOKI Projects), never hidden files or harness_data, text only, writes only
    when THAT machine allows them (LOKI_PEER_FILES_WRITE=1; a .bak is kept); the asking side's write asks.
- **Computer use** (`engine/computer_use.py` over `engine/computer_backends.py`, ctypes only): the `computer`
  tool - elements (the focused window's accessibility tree, numbered: Windows UI Automation via comtypes,
  macOS AXUIElement), find (fuzzy, by role), click/double/right (index, text, or x/y), type, key, scroll,
  open_app, apps, screenshot, look, wait; vision fallback (LOKI_VISION_MODEL or the active model) when the
  tree is empty, scaled pixels->points (Retina). Safety: the `computer-use` add-on (computer:host) must be on
  (policy.CAPABILITY_TOOLS); never in background jobs unless LOKI_COMPUTER_IN_JOBS=1; kill switch
  Ctrl+Alt+Esc / mouse in the top-left corner / Stop in Settings (stays stopped until re-armed); never-list
  (password managers); approval PER APP (once, until restart; LOKI_COMPUTER_APPS pre-approves); every action in
  harness_data/computer_log.jsonl. Not offered in Plan mode.
- **Browser** (`engine/browser_real.py`): with the `chromium` add-on (Install = pip playwright + playwright
  install chromium) `browse_page` opens pages that need JavaScript in a headless Chromium with the SAME
  numbered elements (data-loki-idx in the live page); private profile per session, downloads off, local
  network blocked in the browser, typing a password / submitting a POST form asks (refused in jobs).
  `engine=auto|text|chromium`, LOKI_BROWSER, LOKI_BROWSER_HEADED.
- **Tool use for small models** (`engine/tool_teach.py`): short descriptions with one worked example each,
  action synonyms repaired before validation (send_email -> send, open_application -> open_app ...), and every
  guard error gets the valid actions + "did you mean" + an example call.
- **Where it is wired:** loki.py ONE registration block after call_tool (tools, schemas, categories
  `connectors` + `computer`, LOCAL_TOOL_PRIORITY after code_map, browse_page gains engine=, requirement
  checks) whose three wrappers sit around `_tool_enabled` (health), `_guard_call` (teaching) and `call_tool`
  (recording + draft preview) - agent_turn/_pursue_goal/run_job/tool_harness/tool_guard untouched.
  policy.py: ACTION_ALWAYS_ASK + CAPABILITY_TOOLS["computer"]. loki_bridge.py: two route blocks to tools_api.
  addons_install.py: chromium, computer-use (comtypes on Windows), POST_INSTALL. app/ui/tools_panel.js +
  index.html (Tools panel) + one line in app.js + CSS. New manifests capabilities/computer-use, chromium.
- **Verified here (Linux cloud box):** all suites via `tools/ship.py --check`; the REAL headless Chromium path
  against a local page (a JavaScript-made button numbered and clicked, a GET form typed + submitted, the
  password field and POST button flagged risky, the local network refused); the Google loopback sign-in
  against a real loopback HTTP server with a fake token endpoint.
- **NOT verified (needs the real machines - ZIVA W28 PC, M20 Mac):** the Windows UI Automation and macOS
  AXUIElement backends have never run (no Windows/macOS here; the ctypes signatures follow the docs), the
  kill hotkey, DPI/Retina scaling, real IMAP/SMTP/CalDAV/Google/GitHub/Notion servers (all fakes; gh was
  faked too), the peer file route between the real Mac and PC, the Settings > Tools panel in WebView2/WKWebView
  (ui smoke test only checks it loads). Accounts to connect + the Google OAuth client: Needs Mohamed.

## 2026-10-17 night: Ziva is out (the owner's monthly limit) - it's the owner, Claude and LOKI now

LOKI does the work through its own evolve loop on the PC (docs/EVOLVE.md: E13, E15, E14, E12 at the top). For
that LOKI must be RUNNING: closing the window used to stop the engine (it was closed 18:00 and nothing ran).
Now (app/loki_app.py): LOKI_BACKGROUND (auto = on on Windows) keeps the engine working when the window closes -
opening LOKI again attaches a new window; LOKI_START_AT_LOGIN (auto = on on Windows) writes a hidden Startup
item (LOKI.vbs; a LaunchAgent on macOS) that starts it with `--background`; "Quit LOKI" (sidebar, POST /quit,
exit 76) stops it for good. ZIVA_TASKS.md is now history; open checks there wait for the owner or LOKI.
The PC still has no NVIDIA key in Settings > Connections, so DeepSeek V4.1 is not driving yet.

## 2026-10-17 evening: LOKI gets its own tasks (owner: "give loki tasks to do and fix ... and keep track")

Instead of Claude fixing them, the owner's four new issues are LOKI's own evolve steps at the top of
docs/EVOLVE.md, in this order: E13 no stray "L" in the window, E15 ground texture clipping/shimmer, E14 every
machine's island unique (seeded per machine), E12 a Maya-like loading/splash window (no terminal) for start-up
and updates. The PC's autopilot builds them when idle (improve_loki in a worktree, ship_loki, health-gated
updates); progress is tracked in Settings > Lab, in the ticks in docs/EVOLVE.md and in ZIVA W41 reports. The
roadmap was cleaned: stale open duplicates of finished steps removed; E11 (game engine) parked by the owner.
Claude's role now: watch, unblock, report - not write these fixes.

## Session 28: patching and updating clients, overhauled (after the Mac's white window)

The owner: "overhaul patching and updating clients i dont want that issue to happen again". How an update now
reaches a machine (engine/updater.py, app/loki_app.py, engine/loki_bridge.py):
1. **Pre-flight before switching.** The new commit is checked out into a throwaway git worktree and LOKI's own
   `--self-test` runs there with the ENGINE's Python (LOKI_ENGINE_PYTHON), after installing any new requirements;
   every file index.html loads must exist (`updater.ui_missing`). A failing version is NEVER applied: it goes on
   the skip list with its reason (`skip_reasons`), the machine stays on what works, and the next newer commit is
   tried. LOKI_UPDATE_PREFLIGHT=0 turns it off (suites set it off; tests/test_update_overhaul.py turns it on).
2. **On trial until the window works.** After an update the version is "pending". The engine marks it good only
   when the window reports ready (`POST /ui/ready` from app.js) - not merely when the engine answers (the Mac's
   engine was healthy behind a white window). The rescue screen (boot.js) or no ready within LOKI_TRIAL_UI_S
   (300 s) -> automatic rollback to the last good commit (skipped with the reason) and a full app restart.
   Only when the app supervises the engine (LOKI_SUPERVISED=1); a headless engine is marked good at once.
3. **A history.** Every update/refusal/rollback/good is recorded (`health()["history"]`) and shown in Settings >
   Machines & updates, with the trial state and the reason a version was skipped.
4. **Before it ships at all:** tests/test_ui_smoke.py loads the real window in headless Chromium against a fake
   engine (no script error, no missing file, reaches ready); skipped where Playwright is not installed.
Together with session 27's boot.js rescue screen, the full-app relaunch and the no-about:blank rule.

## Session 28 MMO systems (worktree) - stopped early

The owner stopped the game work mid-session ("do not focus on the game, the core systems aren't
fleshed out yet"). Only the **engine side of progression** was finished and is committed; nothing in
`game/loki-world/` changed and no new game system was started.

- **Done (engine only, tests/test_mmo_systems.py 121, in SUITES):** `engine/mmo_state.py` profile
  extended - gold, bags, gear slots (head/chest/weapon/offhand/trinket/relic) with stats, seeded gear
  drops from monsters and some quests, Trader Fenn's vendor (sell/buy), paintings from LOKI's pictures
  whose rarity is the owner's hearts, 21 achievements with Steam ids (ACH_*), 3 daily quests a day from
  real use, the guild of the owner's machines. New routes `/mmo/equip`, `/mmo/vendor/sell|buy`,
  `/mmo/daily/claim`, `/mmo/like`, `GET /mmo/likes`, `/mmo/guild` (docs/MMO_API.md section 8).
  The shared profile syncs between machines on the existing signed `/peer/presence` exchange
  (`engine/presence.py`: hash first, document only when different, works with the world closed;
  LWW for name/class/guild, per-machine counters for XP/gold/stats, per-item merge for bags/gear).
  Presence chat lines carry a channel (say/guild/party/...). `engine/creations.py`: hearts storage
  (`<data>/creations/likes.json`).
- **Not done:** every client part - procedural sound, island wildlife, gear/vendor/achievement/daily
  windows, party frames, /invite /who, Settings > Creations heart button, Steam folder/GodotSteam hook.
  The Godot client ignores the new state fields. Sync was tested on loopback with two pretend machines
  over a real signed peer link, never between the real Mac and PC.
Last updated: 2026-10-17 (session 28 self-improvement systems, Claude worktree).

## Session 28 self-improvement systems (worktree)

The owner: "keep working and implementing systems"; LOKI must improve and learn by itself, and jobs must
SUCCEED. Built in a Claude worktree, committed there (not pushed). EVOLVE E6, E8, E9 ticked.
**All offline, with fakes: nothing here has run against a real model or on the real PC/Mac yet** (ZIVA W27/M19).

- **E9 Tools LOKI writes for itself** (`engine/user_tools.py`): `harness_data/tools/<name>/` = `tool.json`
  (description, JSON-Schema parameters, required, tests `[{args, expect}]`, timeout, network) + `tool.py`
  (`def run(args)`). The `make_tool` tool (asks first: in DANGEROUS) writes one, CHECKS it (compiles, a static
  scan refuses subprocess/ctypes/eval/exec/os.system/rmtree/os.remove..., network only with `"network": true`,
  then its own tests run in the sandbox) and loads it at once (`USER_TOOLS.sync()`; offered to a local model via
  find_tools' list). Each call: `approve("user_tool", ..., decidable=False)` - the window always asks; a
  background job only with `allow_commands` (job_approve now also accepts make_tool/user_tool) - then a separate
  `python -I` process in the workspace with a minimal environment (no keys, no LOKI_*), a timeout and an output
  cap. A tool changed since its check is off until it passes again. Settings > Tools: list, Enable/Disable,
  Check, Delete (`GET /user_tools`, `POST /user_tools/{toggle,check,delete}`); a "my_tools" category toggle.
- **E6 Speed watch** (`engine/speed_watch.py`): `harness_data/speed/timings.jsonl` - engine start (bridge),
  window first paint + ready (`app/ui/boot.js` -> `POST /ui/timing`), triage, every model call, every tool
  call (named), verification, the whole request (timing hooks in loki.py only), background jobs (from the job
  store). Settings > Lab "Speed watch": median / 90% / last / n + a sparkline per step, the slowest tools.
  Weekly autopilot duty `speed`: the slowest step becomes an evolve idea (approved at once - measured and
  narrow; `LOKI_SPEED_IDEAS=ask` makes it wait). `LOKI_SPEED_WATCH=off` stops recording.
- **Forecasts on queued jobs** (`engine/job_stats.py` + forecast.py: TimesFM-3 when installed, else
  statistical): `GET /jobs` adds `forecast` (duration median/q90 from similar jobs, Laplace-smoothed failure
  risk by kind) to queued/starting jobs; the job strip shows "Forecast: ~6 min · failure risk 42%".
- **Jobs dashboard** (Settings > Lab "Jobs", `GET /jobs/stats`): success per day (30 bars), by kind
  (picture/research/build/team/selftest/other), by model (the model the job REALLY ran on, from its log line),
  top failure reasons (normalised from job errors, result files, logs; escalations "escalated from the small model
  to X" counted), recent failures with **Retry on a stronger model** (`POST /jobs/retry_stronger`: same prompt,
  first FREE online provider set up that it did not already use, through job_action/policy; never paid alone).
- **Daily self-test** (`engine/selftest.py`, autopilot duty `selftest`, `LOKI_SELFTEST=auto` = PC only): 3 cheap
  jobs (write an exact line / add numbers from a file / a markdown list) on the usual job model in
  `harness_data/selftest/<day>/`, checked FROM THE FILES (not the model's words); settled on the next autopilot
  pass after they finish; a run worse than the last is flagged REGRESSION (Lab + autopilot log).
  "Run the self-test now" in the Lab.
- **E8 Self-review** (`engine/self_review.py`, autopilot duty `review`, weekly, where evolve is on; Lab
  "Review now" = rules only): reads the newest learned report, the experience log, reflexion/evolve lessons in
  memory_core, the job dashboard, the speed watch and the self-test; adds up to 3 proposals as "LOKI's idea"
  (`approved: False`, `kind: review`) that wait for Build it / No; no repeats; at most 6 open. With
  `agent._port_ask` (LOKI_SELF_REVIEW_MODEL, on by default) one model call writes them; an unusable answer
  falls back to fixed rules.
- **Evolve end to end** (item 5): tests/test_self_systems.py drives autopilot -> evolve -> the REAL
  improve_loki -> the job through the real `loki.run_job` + goal loop on a scripted model (task_tracker, read,
  tick the roadmap line, check_loki, ship_loki with ship.py faked at subprocess level) -> ship proof -> the next
  autopilot pass records SHIPPED, moves to the next step, lesson in memory, dashboard counts it.
- Files: new engine/{user_tools,speed_watch,job_stats,selftest,self_review,self_api}.py; small hooks in
  loki.py (one tool block + timing lines + job_approve tuple), loki_bridge.py (2 route hooks, /jobs annotate,
  start-up timing), autopilot.py (3 duties + settle), evolve.py (`add_idea(approved=, kind=)`), app/ui
  lab.js (rewritten views), boot.js (timing), app.js (2 lines), index.html (#user-tools), glass.css.
- Tests: tests/test_self_systems.py (120, in SUITES). Screenshots: `python tests/lab_preview/shot.py <dir>`
  (headless Chromium against the real engine modules with seeded data) -> docs/operations/screens/lab-jobs.png,
  lab-speed.png, tools-loki-tools.png.
- **Not verified / needs a machine:** a real local model writing a tool with make_tool; the self-test on
  qwen3:8b on the PC; the weekly review's model call; first-paint timing in WebView2/WKWebView; TimesFM
  forecasts (only the statistical path ran). The sandbox is a separate process with a static scan, not an OS
  jail - the approval before each call is the real gate.
Last updated: 2026-10-17 (session 28 channels + voice, Claude worktree).

## Session 28 channels + voice (worktree)

The owner: "keep working and implementing systems" - this one is TALKING TO LOKI from anywhere.

- **Telegram (EVOLVE E10, ticked).** `engine/channels.py` (the channel core) + `engine/channel_telegram.py`
  (Bot API over stdlib urllib: getMe, long-poll getUpdates with the offset in harness_data/channels/telegram.json,
  sendMessage, sendPhoto/sendDocument multipart, sendChatAction, setMyCommands, getFile for voice notes).
  Settings > General: `LOKI_TELEGRAM_TOKEN` (secret kind, like HIGGSFIELD_KEY), `LOKI_TELEGRAM_POLL`
  (auto|on|off; auto = only the Windows PC polls, so the two machines never both answer; Telegram's 409 for a
  second poller is reported "set LOKI_TELEGRAM_POLL=off on the other machine"), `LOKI_CHANNEL_MODE` (ask|plan).
  A card under the token (app/ui/channels.js) shows the bot, who answers, and **Pair my phone**: a one-time
  8-letter code (15 min, single use) with a t.me deep link + QR; `/start <code>` from a PRIVATE chat pairs
  that user + chat; wrong codes are limited per chat (5) and in total (20, then the code is burned).
  Everybody else gets one "This is a private LOKI bot." an hour; groups and bots are ignored.
  The owner's messages go through `phone_link.chat_once` (the window's agent path, `request_chat`) in
  Ask/Plan only, every approval denied, one at a time ("still on your last message. /stop stops it").
  Replies split at 4000 chars (paragraph > line > space; at most 8 pieces), sends spaced ~1 s per chat, 429
  retry_after honoured; images LOKI made during the answer go back as photos. `/make <prompt>` ->
  creations.make_image (the image specialist directly) and the photo when it is done; `/jobs`; `/stop`
  (agent.request_cancel); `/help`. Voice notes are transcribed when Whisper is installed. Limits: 6
  messages/min, 20 commands/min. The token never reaches a log, the store, /channels or /settings/general
  (redact() on every error; URLs are never printed). Bridge: `/channels`, `/channels/pair|unpair|test`
  routes and one startup hook (`channels.start`), stopped on exit.
- **Voice (EVOLVE E7, ticked).** `engine/voice_input.py`: faster-whisper (Settings > Add-ons > **whisper**,
  new manifest + `addons_install.PIP["whisper"]`; model `LOKI_WHISPER_MODEL`, default base, int8) or whisper.cpp
  (`LOKI_WHISPER_CPP` / whisper-cli on PATH + a ggml model in harness_data/models/whisper/; ffmpeg converts
  non-WAV). `/voice` (status), `/voice/transcribe` (a 16 kHz WAV data URL, <= ~6 min, nothing kept),
  `/voice/speak` (voice.speak -> a data URL; Markdown/code stripped, <= 1500 chars). `app/ui/voice.js`: a
  **mic** button (data-icon + tooltip; hold to talk / click to toggle / Esc cancels) that records WAV itself
  with WebAudio (same bytes from WebView2 and WKWebView) for Whisper, else uses webkitSpeechRecognition when
  the webview has one, else says how to install Whisper; a **speaker** toggle for spoken replies (Kokoro via
  the engine when installed, else the window's speechSynthesis, else the OS voice). Permission errors name the
  exact macOS / Windows privacy setting. UI_CSP gains `media-src 'self' data: blob:` (audio playback);
  Loki.app's Info.plist gains NSMicrophoneUsageDescription + NSSpeechRecognitionUsageDescription (rebuild with
  tools/macos/make_loki_app.sh). app.js: one hook (`Voice.afterReply`); settings.js: one (`Channels.render`).
- **The phone app** (docs/PHONE.md, branch claude/phone) is still not built; PHONE.md now opens with the
  Telegram way, which covers "talk to LOKI from my phone" from anywhere.
- **Discord: not built.** A DM-only bot without the Discord gateway cannot see new DMs, Discord wants a bot to
  identify on the gateway (a websocket) once before it may send, and a bot can only DM users it shares a
  server with. That needs a websocket client (no stdlib one) - not "clean". The channel core is
  transport-agnostic (a transport only implements token/fetch/send_text/send_photo/me), so a
  `channel_discord.py` is one file once a small websocket dependency is acceptable.
- **Verified here:** tests/test_channels.py (in SUITES) against a fake Telegram Bot API on loopback - pairing,
  owner-only, strangers/groups/bots, wrong/burned/expired codes, splitting, photos, /jobs /make /stop /help,
  busy/409/errors, rate limits, 429 retry, 401/409/unreachable, the poll offset, the live poll switch, voice
  notes, the token absent from logs/status/store/every bridge HTTP answer; voice detection, WAV checks,
  faster-whisper + whisper.cpp (+ffmpeg) via fakes, spoken replies, the bridge routes over the real
  BridgeHTTPServer, and the UI hooks. tests/voice_preview/shot.py: headless Chromium with a FAKE microphone -
  hold the mic 1.6 s -> a 16 kHz WAV (50 KB) -> /voice/transcribe -> the words in the box; the speaker toggle;
  the "no Whisper, no recognition" notice; screenshots docs/operations/screens/voice-mic-tooltip.png,
  voice-mic-recording.png, telegram-card.png.
- **Not verified (needs a real machine/account):** the real Telegram API (no bot token here; ZIVA W27 after
  Mohamed's @BotFather bot - Needs Mohamed), real faster-whisper/whisper.cpp transcription speed, WebView2's
  and WKWebView's real microphone prompts, whether WKWebView in pywebview exposes webkitSpeechRecognition and
  grants getUserMedia (M19), Kokoro spoken replies.

## Session 28 creative pipelines (worktree)

The owner loves the fox picture and wants "more of that stuff". Built in a Claude worktree, committed there, not
pushed (the parent session merges and ships). **31 suites pass** (`tests/test_creative.py` is new: 93 offline checks,
fakes only - no download, no GPU, no model). Screens (fake data): `docs/operations/screens/creations-s28-*.png`.

- **Local pictures on the owner's own hardware** (`engine/creative.py`, runner `engine/runners/imagegen.py`):
  - the PC: **stable-diffusion.cpp** (`sd-cli`, CUDA 12 build + cudart DLLs; Vulkan without NVIDIA) running
    **Z-Image Turbo GGUF** - `z_image_turbo-Q4_K.gguf` (3.9 GB) + `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` (text encoder)
    + `ae.safetensors`, cfg 1.0, 8 steps, `--offload-to-cpu --diffusion-fa` (sd.cpp's wiki runs this on 4 GB).
    Q3_K under 6 GB, Q6_K at 12+ GB (`LOKI_SDCPP_MODEL`). A batch of 4 is one run (`-b 4`).
  - the Mac: **mflux** (MLX) `mflux-generate-z-image-turbo --model filipstrand/Z-Image-Turbo-mflux-4bit --steps 9`
    (pre-quantized ~6 GB in all; diffusers Z-Image had crashed the 16 GB M4), `--low-ram` at 16 GB.
  - auto order is now: local (sdcpp/mflux, once installed) -> diffusers Z-Image -> Qwen (ModelScope) -> Pollinations.
    Every picture now has a real seed (random when none is given, reported back).
  - **Install**: Settings > Add-ons > `local-image` / `local-video` cards show the steps and an Install button
    (`addons_install.plan/install` -> `creative.start_install`, background thread, progress in
    `harness_data/app/creative.json`, shown on the Creations wall). Same from the command line:
    `python tools/setup_extras.py local-image|local-video`. Everything goes to `harness_data/tools` and
    `harness_data/models/imagegen`. sd.cpp: latest GitHub release (`LOKI_SDCPP_TAG` pins one; assets of
    master-920-2f88688 checked), zips extracted with a path check.
- **Creations upgrades** (`engine/creations.py`, `app/ui/creations.js`, `app.css`): Make box with a style picker
  (Fooocus' 25 styles, pixel art first), Enhance (LOKI's model writes the prompt, offline expansion without one),
  aspect ratio (1:1 ... 16:9, ~1 MP), x4 variations. Every piece made there gets a sidecar
  `<kind>/.meta/<file>.json` {idea, prompt, negative, style, backend, seed, aspect, liked, daily, parent, model}.
  Tiles show the prompt on hover and a star; filters (Pictures, Videos, Music & voice, Starred); the viewer has
  Make more like this (same prompt/negative/style/aspect, 4 variations from seed+1), Animate this, Favourite and
  Delete (moves file + sidecar to `<workspace>/trash/<kind>/`, never a hard delete). `music/` and `voice/` are on
  the wall with an audio player on the tile. Bridge: POST /creations/make (style, enhance, aspect, count, seed;
  kind=video), /creations/like, /creations/delete, /creations/more, /creations/animate; GET /creations adds
  styles, aspects, `creative` (which maker this machine has, installs). `list_creations`, `creation_file` and
  `make_image(agent, prompt)` kept compatible (new arguments are keywords) for the MMO.
- **Video**: Wan2GP on the PC, headless `wgp.py --process <settings.json> --output-dir ... --profile 4 --attention
  sdpa`, default model_type `ltxv_distilled` (LTX-Video distilled; 3 s = 73 frames at 24 fps), image-to-video with
  the creation as `image_start`. A template exported from Wan2GP's own UI ("Export Settings") saved as
  `harness_data/app/wan2gp_template.json` wins (LOKI fills prompt, seed, length, start image) - **the key names
  are unverified**, so W27 asks Ziva for that template. Wan2GP install: git clone + own venv (`py -3.11` on
  Windows, `LOKI_WAN2GP_PYTHON`) + torch cu128 + requirements. Fallback: Higgsfield (key set;
  `LOKI_HIGGSFIELD_VIDEO_APP`, default `higgsfield-ai/dop/standard` - unverified; it gets the prompt only, not the
  picture). Agent tool `make_local_video(prompt, image, seconds)` (one small block in loki.py).
- **Daily creation**: autopilot duty `creation` - one picture a day when idle, from the starred styles/subjects
  (a fox by default), Enhanced, marked `daily`. `LOKI_DAILY_CREATION` on|off|auto; auto = on with an NVIDIA GPU
  (the PC), off on the Mac. The duty is only listed where it is on.

**Not verified (no GPU, no downloads here):** no sd.cpp/mflux/Wan2GP binary ever ran; sd.cpp's batch file names
(`out_2.png`), mflux's `--output`/`--low-ram` flags, Wan2GP's settings keys and `--profile` with `--process`,
the Higgsfield video app id. ZIVA W27 (PC) and M19 (Mac) run them for real and report times and VRAM.

**Next:** a "Remix" (img2img with sd.cpp `-i` / mflux `--image-path`) on the viewer; LoRA styles (sd.cpp
`--lora-model-dir`); Wan2GP's ACE-Step for music on the PC; the MMO "like" hook can call `creations.set_liked`.

## Session 27 (cont.): the Mac's white window

The owner reported the Mac shows only a white window (Ziva Mac was looking into it; this session has no access to
the Mac). Whatever the cause, a blank window is now impossible to miss and easy to diagnose: `app/ui/boot.js`
loads first and catches script/load errors, sends them to the engine (`POST /ui/error` -> engine.out "window
error" lines, `/health` `ui_errors`), and shows a rescue screen with the errors, Reload, and "Reload without the
3D world" (localStorage loki.safeMode; cleared when Settings > LOKI World is opened). loki_app.py never shows
about:blank any more when the engine fails - it shows the log tail. An update relaunch now hard-exits the old copy
after 2 s (closing a window off the main thread can hang on macOS, leaving a blank old window). Bonsai 2 gets
/no_think like qwen3. ZIVA M18.

## Ziva (Windows), 2026-10-17: the PC session-26/27 checks, and a duplicate fix dropped

Ran the [windows] inbox item and W21/W20/W19/W18/W10/W23 on the real PC. All 28 suites green. Highlights:
`POST /peers/diagnose {peer: mohameds-mac-mini}` works over the live relay and is REDACTED (no stuck
request, empty log tails); the Babylon pixel world is the default and holds ~60 fps (panel ema 16.7 ms,
boost 0); the Mac linked and /world.machines shows it ("1/1 machines linked"); Settings > Creations makes
a real ~1 MB picture with zimage in ~7 min; three/classic/babylon all switch; the option cards and CRM
work. Not done: Ollama upgrade (0.40.5, needs the owner), the fox close-up, W22 (MMO) and W24 (research
ports).

I started fixing the weak-model "Make it" bug (the model invented a tool `image`, wrote the prompt text
into the PNG and called it DONE) and then found Claude's session-27 commit (a5deaad) had already fixed it
the same day and better - call_tool now routes a role name like `image` to conductor, `_salvage_reply`
keeps text tool calls, `_specialist_made` counts a specialist-written file, and Creations makes pictures
DIRECTLY (POST /creations/make, no model). So I dropped my duplicate patch (no code shipped from this
session) and VERIFIED the upstream fix on the PC instead: /creations/make made a real 1,056,903-byte PNG
via zimage. Details, fps and screenshots are in ZIVA_TASKS.md (W21/W23).
## Session 27 Godot MMO (worktree)

The owner: LOKI World becomes a real MMO "like hordes.io ... mmo everything we can", in **Godot 4**. Built in a
Claude worktree as **`game/loki-world/`** (AGENTS.md: the one Godot project), GL Compatibility so the desktop and
web builds look the same. docs/WORLD.md "LOKI World in Godot 4" has the controls, options and export steps.

- **Play:** your own character (class hat + weapon), WASD + mouse orbit camera, jump, click/Tab to target,
  hotbar 1-9 (Strike, Bolt, Mend, then LOKI actions that start REAL jobs: picture, research, build, video, game,
  then Hearth), cast bars, cooldowns, damage numbers, XP and level-ups, emotes, day/night from the clock.
- **World:** this machine's island at home, every linked machine its own island out in the sky, walkable bridges
  of light, fly via the map (M). LOKI's agents are NPCs at their stations (classes, levels from finished jobs);
  quests = jobs (turn in at LOKI); failed jobs = monsters (beat one: XP + lesson scroll + "retry on a stronger
  model"); loot = creations (hung in the creations hall, in the bags); the fox and two rabbits.
- **HUD:** nameplates with bars, player/target/party frames, minimap + big map, chat (Say via presence, `/l` to
  LOKI via POST /chat), quest tracker + log, bags, character sheet (name/class), loot window, help, pair window.
- **Look:** 4-band cel shading with faceted normals, ink outlines (inverted hull; islands bake theirs - 2 draws
  per island), 1/3 resolution upscaled nearest + posterize/Bayer dither, banded sky, crystals, waterfall.
- **Net:** `autoload/loki_api.gd` follows docs/MMO_API.md (GET /mmo/state 3 s, /mmo/* actions, /world/presence
  150 ms/1 s); falls back to deriving the game from /world+/jobs+/creations on an older engine; offline demo
  world without LOKI. Token: page fragment (web) or LOKI's state folder / --token / Pair (desktop).
- **Web hook:** Settings > General > LOKI World look = **godot** loads `/ui/world_godot/` in one frame laid over
  the home background or the LOKI World panel (app/ui/world_godot/host.js; world.js: 4 small hooks); falls back
  to Babylon when the export is missing. engine/loki_bridge.py serves `.wasm`/`.pck` and gives
  `'wasm-unsafe-eval'` + same-origin framing ONLY to /ui/world_godot/index.html; portal_api lists "godot".
- **Verified here:** Godot 4.7.2 built from source (release downloads are blocked here) - the project imports, its
  own headless tests pass (107), and it plays headless against the REAL bridge (source=engine, quests/monster/loot
  from fake jobs, presence and chat both ways); screenshots rendered with Mesa llvmpipe under Xvfb (software, ~13
  fps - not a GPU number). A Linux release export (template built from source too) starts and runs the game.
  tests/test_godot_world.py (84) is in SUITES; it runs Godot only when one is on PATH
  (`LOKI_SUITE_GODOT`). tests/test_loki.py's "no Godot files" check now exempts game/loki-world/ only.
- **Not done here:** the Web export (needs Emscripten-built templates; their download host is blocked) and the
  Windows/macOS exports - ZIVA W26 (PC, Godot 4.8) and M17 (Mac). No real GPU, WebView2 or WKWebView run yet;
  sound; Steam (notes in WORLD.md). The web export, once made, must be committed (index.js/.wasm/.pck).

## Session 27 (2026-10-17, Claude in the cloud): why every LOKI job failed, and the fixes

From the PC's job logs (harness_data/jobs): background jobs run on qwen3:8b (PREFER=local, easy triage) and
1. it returned EMPTY replies - qwen3's thinking ate the answer (`think: false` is not honoured on Ollama's
   OpenAI-compatible endpoint) -> `_small_model_kwargs` adds Qwen3's `/no_think` switch to the system message;
2. it wrote tool calls as text (```json blocks) and called the image maker as a tool named "image" ->
   `_salvage_reply` turns text calls into real calls on every provider and drops <think> tags; an unknown
   tool named like a conductor role (image, research, generate_image...) runs conductor(role=...);
3. a real image it made did not count as work, so "DONE is premature" told it to write_file (a Godot-era
   nudge) and it wrote "a fox asleep in the snow" into images/fox_asleep_in_snow.png, which the checker
   passed -> a specialist's "made <file>" counts as written work; write_file refuses .png/.jpg/.mp4/...;
   verification checks a media file's magic bytes (a text "png" FAILS); the nudge is generic;
4. a stuck small model ended the job (empty replies, DONE without work, "BLOCKED: Builder's role
   unavailable", no tool calls) -> `_escalate_model`: once per background job, carry on with the first
   free, set-up online model (never paid on its own); LOKI_NO_ESCALATE=1 turns it off;
5. the self-improvement job crashed: Claude Code's argv held a NUL byte (from a binary read) and ~21k
   tokens (Windows caps a command line at 32,767 chars) -> cli_agents cleans control bytes and sends long
   prompts on stdin; a ValueError is a CliAgentError, not a traceback.
Creations' "Make it" for a picture now calls the image specialist directly (POST /creations/make, a
thread; the wall shows "Making..." and failures) - no chat model in between.
- **Update everything** now restarts the WHOLE app on every machine (app/loki_app.py relaunches itself and
  the new copy waits for the old one), and a waiting update is applied by itself when LOKI is idle (no chat,
  no running job) - checked every 10 min (LOKI_FORCE_UPDATE=0 / LOKI_UPDATE_EVERY_S to change).
- **Icons in favour of words** (`app/ui/icons.js`): the main buttons and Settings sections are icons; hover
  or focus one for its name and what it does. Settings is an icon rail (search is an icon that opens the
  field). Words stay in aria-labels and for the search.
- **Owner decision: the MMO is Godot.** LOKI World becomes an MMO built in Godot 4 (`game/loki-world/`),
  exported as its own app for Steam AND as a web build inside LOKI's window (replacing the Babylon world
  there when it lands). The Godot tools in LOKI stay. AGENTS.md updated.

TimesFM-3: the owner said yes (engine/data/owner_approvals.json); each engine installs it once at start-up
where missing (LOKI_TIMESFM_APPROVED=0 says no; suites never install). It forecasts numbers (usage, cost,
trends) for the forecast_series tool - it does not make jobs succeed; the fixes above do.
tests/test_job_fixes.py (33).

## Session 27 MMO world (worktree)

The owner: make LOKI World "more like hordes.io ... an actual mmo" (own character, MMO HUD, agents as
NPCs with levels/classes, jobs as quests, failures as monsters, loot = creations, combat, and the Mac and
PC seeing each other). Mid-session the owner changed plan: **the MMO client will be a Godot 4 game**
(own repo; Steam desktop build + a web build inside LOKI's window replacing the Babylon world there).
So this worktree built the **engine side every client uses** plus the first in-app stage as a fallback.

- **Contract: docs/MMO_API.md** (auth = the bridge's bearer token, loopback Host/Origin rules, polling
  rates, payloads, coordinates/zones, combat numbers, presence interpolation).
- **engine/mmo_state.py** + bridge routes `GET /mmo/state`, `POST /mmo/profile|skill|quest/accept|
  quest/turnin|monster/defeat|monster/retry|note`: quests = jobs, monsters = failed jobs (named from the
  error, stable spawn), loot = creations (+ lesson scrolls), NPC classes/levels from roles and finished
  jobs, a 9-slot hotbar whose LOKI actions start real jobs through the bridge's own `job_action` (policy
  included; same prompts as Settings > Creations). First run turns the owner's past work into XP.
  Progress: `<DATA_DIR>/mmo/profile.json`.
- **engine/presence.py** + `POST/GET /world/presence`, `presence` in GET /world, signed
  `POST /peer/presence` (peers.py route, peer_link callback): one exchange carries both machines'
  avatars and chat (works over a one-way relay link), pushes only while a world is open (~350 ms moving,
  2 s idle), back-off for a dead peer, everything sanitised. `/world/retry` = retry without the game.
- **In-app stage 1** (`app/ui/mmo/mmo_core.js`, `mmo.css`, small guarded hooks in world.js): Settings >
  LOKI World > Play: WASD/mouse/QE camera, jump, collisions, island edges, bridges of light to the other
  machines' islands (zones), class avatars, WebAudio beeps; Spectate = the old view. No HUD/combat/
  presence client in the browser (stopped per the new plan). Pooled drawing, no per-frame allocation.
- Tests: `tests/test_mmo.py` (77, in SUITES): files/hooks/no-CDN/perf guards, presence over a real
  signed peer link on loopback (both directions in one call, dedupe, expiry, back-off, wrong secret,
  old peer 404), game rules, routes with a fake engine and over the real BridgeHTTPServer.
  Screenshots: `tests/mmo_preview/shot.py` (headless Chromium + SwiftShader; checked babylon + classic).
- **Not done / needs a machine**: fps of Play on the real Mac/PC; presence between the real Mac and PC
  has only run on loopback (ZIVA W22/M14 ask for a two-machine `/world/presence` check); the Godot web
  build needs `.wasm`/`.pck` in UI_TYPES and `'wasm-unsafe-eval'` for its page (see MMO_API.md section 1).
Last updated: 2026-10-17 (session 27 harvest, Claude worktree; session 26 before it).

## Session 26 (2026-10-17, Claude in the cloud): Babylon.js world, one island per device, Creations

- **Babylon.js is LOKI World's engine** (owner's choice, over Godot/Panda3D: it runs inside the app's
  webview on both machines with no extra install). `app/ui/vendor/babylon/babylon.loki.js` is Babylon 8.9.1
  built from source (Apache-2.0; rebuild steps in `tools/babylon/README.md`, CellMaterial patched by
  `tools/babylon/patch_cell.py`). `app/ui/world_babylon.js` draws the same scene description world.js makes
  every frame, in the SAME pixel cel-shaded look the owner likes: CellMaterial bands, ink outlines (an
  inverted hull), a hardware pixel grid (setHardwareScalingLevel + `image-rendering: pixelated`), the Bayer
  posterize as a post-process, blob shadows, halos, the water shader. Thin instances: ~14 draw calls a frame.
  Lazy-loaded; if it cannot load, the world falls back to LOKI's own renderer ("classic"). Settings > General
  > LOKI World look: babylon (default) / classic / three. Nothing was taken off.
- **Every device has its own island.** `/world` now says which machine it is (`self`: name + OS). The island
  you stand on is THIS machine ("<name> - you are here" over the spire); each linked machine is a full island
  of its own out in the space around it (its house in its colours - a Mac silver, a PC blue - trees, a beacon
  lit while it answers, a figure per job, a bridge of light with packets). Slots come from the machine's name
  so islands never jump or overlap. Click a machine's name to fly there; "back to <name>" brings you home.
  So on the Mac you stand on the Mac island and see the PC's island out there, and the other way round.
- **Creations - more of the fox.** The fox picture the owner loved was made by LOKI's image specialist
  (conductor `image`, free Pollinations backend) on 2026-10-14 20:17 when Ziva Windows ran W13
  ("make an image of a red fox in studio light"); it is `images/20261014-201742-red-fox-in-studio-light.jpg`
  in the PC's workspace. New: Settings > **Creations** (`creations.js`, `engine/creations.py`, GET
  /creations, files at /creations/<kind>/<file> - this machine only, sandboxed) shows everything LOKI made,
  newest first and big, with a "Make it" box (picture / video / game, starts a background job) and "Make
  more like this". On the island a **creations hall** hangs the newest five pieces; its name opens Creations.
- Still open (owner to answer): remove the Godot code (AGENTS.md says nothing Godot; the owner also said
  "don't take anything off").

## Session 27 research ports (worktree)

The owner: "take code from open-source repos to improve LOKI natively - not the ones we have, but also
research for me". Researched ~36 NEW projects (none already in LOKI) and ported the best nine as native
engine modules + 11 tools. Full ranked table with sources: `docs/integrations/research-2026-10-17.md`.
Built in a Claude worktree, committed there, not pushed; the parent session merges and ships.
**26 suites pass** (`tests/test_research_ports.py` is new: 141 offline checks, fakes only).

Licences sit in `engine/licenses/` (Aider Apache-2.0, ReWOO/Reflexion/STORM/bigtool/instructor/ACE-Step MIT,
Kokoro Apache-2.0, Fooocus GPL-3.0); rows in docs/THIRD_PARTY.md. **Fooocus is GPL-3.0**: like OpenHuman and
MuMuAINovel, `engine/image_prompt.py` + `engine/data/image_styles.json` must go before LOKI is ever published.

**New tools (loki.py: one registration block after SELF_IMPROVE_PRIORITY; nothing in agent_turn, the goal loop,
_model_request, the parser or the DONE gate was changed):**
- `repo_map(focus, subdir, max_chars, files)` - aider's repo map (`engine/repo_map.py`): ast/regex tags,
  def/ref graph with aider's weights, personalized PageRank, budget fit. LOKI additions: `module.name` refs go to
  module.py only; a file's own copy of a common name is no cross-file edge; symbols named in `focus` come first.
- `apply_edits(blocks)` - aider's SEARCH/REPLACE blocks (`engine/edit_blocks.py`): several files per call,
  whitespace-forgiving + `...` matching, did-you-mean on failure, partial success, CRLF kept, `undo_edit` works.
- `find_tools(query)` - langgraph-bigtool (`engine/tool_select.py`): BM25 over all offered tools; the matches are
  inserted after `find_tools` in LOCAL_TOOL_PRIORITY (at most 6, oldest drops), so a local model sees them next
  step. `find_tools` and `repo_map` were added to LOCAL_TOOL_PRIORITY (index 5-6).
- `extract_structured(text, schema, instruction)` - instructor (`engine/structured.py`): JSON Schema validation,
  re-ask with the errors, constrained `response_format` on local servers (falls back once if refused).
- `plan_and_solve(task)` - ReWOO (`engine/rewoo.py`): one plan with `#E` variables, read-only tools run through
  `call_tool` (policy applies - a path outside the workspace is DENIED, tested), one solve call.
- `reflect(task, attempt, feedback)` - Reflexion (`engine/reflexion.py`): diagnosis + new plan stored as an
  episodic memory tagged `reflexion`, so the memory pack offers it on similar later tasks. `trial_loop` is there
  for callers with an evaluator (not wired into evolve yet - see Next).
- `web_search(query)` - keyless: DuckDuckGo HTML, or SearXNG when `LOKI_SEARXNG_URL` is set.
- `deep_research(question, depth 1-3)` - STORM (`engine/deep_research.py`): editors -> questions -> queries ->
  read_web -> cited answers -> outline -> sections -> `research/<date>-<slug>.md` with references.
- `enhance_image_prompt(prompt, style)` - Fooocus styles (25: pixel art, cinematic, anime, ...) + expansion by the
  model or a seeded offline fallback. The image path (conductor/generate_media) is unchanged; the model passes
  the enhanced prompt on.
- `make_music(prompt, lyrics, duration, bpm, key)` - ACE-Step 1.5 REST client (`engine/music.py`), to
  `music/`. Needs `uv run acestep-api` on the machine (or `LOKI_ACESTEP_URL`).
- `speak(text, voice_name)` - Kokoro when `pip install kokoro soundfile` was run, else macOS `say`, Windows SAPI
  (text via env vars, never in the script), espeak-ng (`engine/voice.py`), to `voice/`.
- New settings category "research" (web_search, deep_research); the others joined files/planning/memory/creative.
  `apply_edits`, `deep_research`, `make_music`, `speak` are MODIFYING (not offered in Plan mode).
- Shared model call `_port_ask` (active model, `think: false` on Ollama, usage recorded, `<think>` stripped).

**Not verified (no machine, no network here):** no live model has driven any of these tools; DuckDuckGo was
blocked by the sandbox proxy (the parser is tested on a saved page); ACE-Step and Kokoro never ran; `say` / SAPI /
espeak argv shapes are tested with fake runners only. ZIVA_TASKS W22 (PC) and M14 (Mac) ask for all of it.

**Next (from the research):** a "fix this bug" pipeline (Agentless: repo_map localize -> apply_edits candidates ->
check) and Reflexion's `trial_loop` around it; stable-diffusion.cpp (PC) / mflux (Mac) as local image backends fed
by enhance_image_prompt; Wan2GP as the PC's video add-on; Playwright MCP (accessibility snapshot) for text-only
browser control; arXiv/Wikipedia/GitHub sources in deep_research; MMO notes for the world agent are in the
research doc (Colyseus + snapshot interpolation + bitECS/miniplex).
## Session 27 harvest (worktree)

The owner: "go through all the connectors and add-ons we talked about, every single repo we have
documented - take the code and improve LOKI, not the ones we have." Licence: "LOKI stays private,
copy anything". Built in a Claude worktree, committed there; the parent session merges and ships.
**26 suites pass** (`tests/test_harvest.py` is new: offline, fake openers, 149 checks).

**docs/integrations/HARVEST.md** is the inventory: every `github.com/...` in docs/, engine/,
contrib/, capabilities/, tools/, app/ui, HANDOFF and ZIVA_TASKS (91 rows; 12 placeholder links left out),
each with licence, what LOKI already had, what was worth taking, and the decision. Session 26's
ports (OpenHuman, OpenHands, Scrapling, MuMuAINovel, PenEcho) were not redone.

**Ported into LOKI's own code (13) - priority: agents that succeed on qwen3:8b and free models:**
- **Edits that land** (Hermes Agent `fuzzy_match.py` + `escape_drift_autocorrect.py`, copied; the
  opencode/cline replacer chain): `edit_file` falls back to line-trimmed, whitespace/indent-flexible,
  escape-, unicode- (smart quotes/dashes), boundary-, block-anchor and context-aware matching, says which
  one matched, and a miss shows the closest lines. A one-line "similar" match is NOT accepted (a guess).
- **Edits that cannot break a file** (SWE-agent lint-on-edit, `engine/lint_guard.py`): an `edit_file` /
  `insert_lines` that introduces a syntax error (Python, JSON, TOML, XML, brace balance for JS/TS/CSS/
  Go/Rust/Java/C...) is not written; the model gets SWE-agent's "your edit would have looked like / the
  original" report. Errors already in the file are not blamed. LOKI_EDIT_LINT=0 turns it off.
- **Web search with no add-on** (Vane, `engine/web_search.py`): tools `web_search` (modes web, academic
  = arXiv, discussion = Reddit, news) and `research_web` (search -> read the best pages -> crawl4ai BM25
  keeps the relevant parts -> numbered sources + Vane's citation rules, one call). SearxNG when
  `LOKI_SEARXNG_URL` is set, else DuckDuckGo HTML, arXiv Atom, Wikipedia API.
- **Focused reading + local RAG** (crawl4ai, `engine/content_filter.py`): `read_web(url, query=...)`
  returns only the parts about the query; `search_docs(query)` = BM25 over workspace files (pdf with pypdf).
- **Text browser** (browser-use + page-agent, `engine/text_browser.py`): `browse_page` open/click/type/
  select/submit/scroll/back/find with numbered `[i]<tag ...>` elements; GET forms only unless
  LOKI_BROWSE_POST=1 (a POST changes something on a site - Browser Use add-on asks first).
- **Site maps** (Firecrawl map, `engine/site_map.py` - AGPL port): `map_site(url, search)`.
- **Reach** (Agent Reach, `engine/reach_native.py`): `reach(url)` - GitHub API (repo + README, issue + comments,
  file), RSS/Atom, YouTube oEmbed, Reddit/JS pages through Jina Reader (LOKI_JINA=0 = never). Its URL
  rules now also guard `loki._private_host`: `127.1`, `2130706433`, `0x7f000001`, `*.internal`,
  `metadata.google.internal` are refused everywhere LOKI fetches.
- **Code maps** (SWE-agent filemap/search_dir, `engine/code_map.py`): `code_map(path)` - a file's outline
  (Python bodies elided) or a folder's map of symbols with line numbers.
- **Compression** (Headroom SmartCrusher + LogCompressor, `engine/compress.py`): `_elide` (the one tool-result
  choke point) now keeps a big JSON array's first/last/error rows and a long log's errors, traces and
  summary before falling back to head + tail.
- **Skill abuse rules** (SkillSpector `agent_skills.yar`, `engine/skill_rules.py`): always-on
  `skill_scan.NATIVE_SCANNERS` (the add-on's EXTERNAL_SCANNERS stay separate). 0 of LOKI's 260 skills trip it.
- **Scheduled tasks** (Hermes cron, `engine/schedules.py`): `schedule_task add|list|remove|pause|resume`
  ("every weekday at 9am", "in 30m", "every 2h", cron lines, ISO times; cron matcher built in). The
  autopilot's new `schedules` duty starts a due one as a background LOKI job at its time (idle or not;
  never two runs of one schedule at once). A background job cannot schedule jobs. Store: harness_data/schedules.json.
- **Tool-argument coercion** (Hermes arg_coercion) in `tool_guard`: JSON-string objects, JSON-string
  array items, "null".
- **Skills**: six Apache-2.0 skills from anthropics/skills in `skills/anthropic/` (catalog source
  "anthropic"); the proprietary docx/pdf/pptx/xlsx skills were not copied.

Where it is wired (small blocks only): `engine/loki.py` tool block after the session-26 tools,
schemas after `read_web`, MODEL_TOOL_NAMES, TOOL_CATEGORIES (files: code_map/search_docs; web: the
web tools; planning: schedule_task), LOCAL_TOOL_PRIORITY (research_web, web_search, read_web, code_map
right after the file tools), `NETWORK_WRITES` += schedule_task (Plan mode), `_elide`, `_private_host`,
`read_web(query=)`. Not touched: agent_turn, _pursue_goal, _model_request, the prompted-tools parser,
DONE verification, cli_agents.py, creations.py, conductor.py, app/ui.

**Licence:** ports keep their upstream licence in `engine/licenses/` (Hermes, SWE-agent, crawl4ai, Vane,
Firecrawl AGPL, browser-use, page-agent, Agent Reach, Headroom + NOTICE, SkillSpector); docs/THIRD_PARTY.md
has a row each. `engine/site_map.py` is an AGPL-3.0 port - one more file to remove if LOKI is ever published.

**Not done / check on a machine (ZIVA W22 PC, M14 Mac):** none of the web tools has met the real internet
(the cloud sandbox blocks DuckDuckGo/arXiv/Wikipedia) - whether DuckDuckGo's HTML page answers LOKI's
requests from the owner's IPs is the open question; a SearxNG (LOKI_SEARXNG_URL) is the robust fix if not.
No live model has used the new tools yet; scheduled jobs have not fired on a real engine. Skipped with
reasons in HARVEST.md: memory/graph servers (Hindsight, OpenViking, Graphiti), runtimes (ruflo family,
Paperclip, cua, herdr), phone/hardware projects, API-catalog entries, deepseek-harness (TS preview),
artemis (no longer public). aider is not documented in the project, so it was left to the new-repo research.

## Session 26 core upgrade (worktree)

The owner: "take all these plugins and take their code and parts of it and make LOKI better - not
so it calls out to them. It's not improving itself right now because it doesn't have those." Built
in a Claude worktree (branch `worktree-agent-a503d5a5908a26e4b`), committed there; the parent
session merges and ships. **25 suites pass** (`tests/test_core_upgrade.py` is new, 150+ checks).

**LICENCE: LOKI MUST STAY PRIVATE.** Code ported from GPL-3.0 projects is now in LOKI:
OpenHuman (`engine/memory_core.py`, `engine/subagent.py`) and MuMuAINovel (`skills/novel-writer/`).
The owner allowed any licence because the repo is private and LOKI is not distributed. The root
LICENSE (MIT) does not cover those parts; publishing LOKI would require removing/rewriting them or
releasing all of LOKI as GPL-3.0. Licences sit next to the code (`engine/licenses/`,
`skills/novel-writer/`); docs/THIRD_PARTY.md lists every port.

**Why LOKI was not improving itself (found and fixed):**
1. An improve job ran on `LOKI_IMPROVE_MODEL=online`; with no online key on the machine that name
   resolves to an unconfigured provider, so the job could only answer BLOCKED. Now
   `improve_model()`: online when a free online provider is set up, else `smart` (local).
2. On a local model the tool list is trimmed to 22 by `LOCAL_TOOL_PRIORITY` - `check_loki` and
   `ship_loki` were not on it, so a local improve job could neither test nor ship. Inside a LOKI
   worktree `SELF_IMPROVE_PRIORITY` now puts them first.
3. A job that ended "done" counted as **shipped** even when the model said DONE without calling
   ship_loki (or ship_loki refused). `ship_loki` now leaves proof (`harness_data/jobs/<job>.shipped.json`)
   and `Evolve.settle(..., shipped=, detail=)` records "finished without shipping: <its last line>"
   as a failure (retried in 3 days with that reason in the prompt).
4. A shipped roadmap step was offered again until this checkout updated (the tick lives in the
   pushed commit). `next_item` now skips a step whose last outcome is shipped.
5. Test runs inherited the engine/job environment (`LOKI_DATA` = the live data folder,
   `LOKI_WORKSPACE`, `LOKI_JOB_ID`, keys): the suites behaved unlike CI and could write into the
   owner's real data. `check_loki`/`ship_loki` now use `check_env()` and `tools/ship.py` strips
   `LOKI_*`/`HARNESS_*` from the suites' environment (`LOKI_SUITE_*` stays).
6. `check_loki` ran the MAIN checkout's ship.py, so a suite the change added never ran: it now runs
   the worktree's own `tools/ship.py`.
7. Long jobs had no context management (`LOKI_MAX_CONTEXT=0` = keep everything) and overflowed:
   the OpenHands condenser now sends the model a condensed view (see below).
8. Nothing fed outcomes back except one line in evolve.json: every settled attempt is now also an
   episodic memory (`memory_core`), recalled into the next improve job's memory pack.
9. Loop nudges were appended between an assistant's tool calls and their results (providers reject
   that); they now wait until the whole tool batch is answered.
The whole loop is tested with fakes: autopilot -> evolve -> improve job -> (no ship) failure with
reason + lesson -> next step -> (ship proof) shipped -> not rebuilt; and a scripted improve job
through the real goal loop (task_tracker, ranged read, edit, check_loki, ship_loki, DONE).
Still true: `LOKI_EVOLVE` auto = on only on the Windows PC; `LOKI_SELF_SHIP=ask` blocks shipping
from a background job (nobody can approve there).

**Built in (engine/, tools in loki.py LOCAL_TOOLS / schema / MODEL_TOOL_NAMES / TOOL_CATEGORIES):**
- `memory_core.py` (OpenHuman): `memory` tool learn | recall | fetch | forget; secrets scrubbed
  before storing; host-stamped metadata; IDF + recency + usefulness relevance; evidence capped
  OpenHuman-style; 8 calls per request. Every request gets a bounded **memory pack** (1800 chars,
  `LOKI_MEMORY_PACK_CHARS`) in its "This request" note - never in the transcript - and the reply
  metadata says which were used (`memories_used`, `skills_used`, `learned_skill` on /chat).
  `memory.py` keeps its API and adds learn/forget/pack; recall/stats include the core.
  Settings > Memory lists, searches, edits and forgets learned memories and skills
  (`app/ui/memory_panel.js`, `GET/POST /memory/core`).
- `skill_learning.py` (E2): a verified request with more than 5 tool calls writes
  `harness_data/skills/learned/<slug>/SKILL.md` (steps in order with the file that mattered,
  files changed, pitfalls, result); similar requests refresh it; the pack offers it next time and
  the reply says "used learned skill ...". Listed by the skills catalog as "learned".
- `subagent.py` (E3, OpenHuman): `run_subagent(task | tasks[], tools, max_turns)` - own small
  context, narrowed tools (never run_subagent/delegate/improve_loki/ship_loki/start_team), same
  model routing, one collapsed result, up to 4 side by side, stuck-stopped, turn cap 12 (40 in a job).
- `condenser.py` (OpenHands LLMSummarizingCondenser + its prompt): over 160 messages or 280k chars
  (60k on a local model; `LOKI_CONDENSE_*`) the MODEL gets head + one rolling summary + recent tail;
  the chat history the window shows is never cut. A "context too long" error condenses and retries
  once. Model down -> a summary built from the events.
- `stuck.py` (OpenHands StuckDetector): same call+result x4, same failing call, alternating pair,
  monologue -> one nudge, then the request stops with "BLOCKED: I was stuck in a loop".
- `file_editor.py` (OpenHands file_editor): `read_file(filename, start_line, end_line)` numbered
  ranges (a big file read whole shows its first lines numbered + the line count), `edit_file` needs a
  UNIQUE match unless `replace_all` (it used to replace every copy silently), `insert_lines`,
  `undo_edit`; CRLF files stay CRLF.
- `web_reader.py` (Scrapling core on the standard library): `read_web(url)` - main content as
  markdown, hidden/aria-hidden/template text and zero-width characters removed (prompt-injection
  sanitizer), browser-like headers. Used when no reader add-on is on; `scrape` and
  `conductor read_web` fall back to it. Local/private hosts refused (LOKI_NET_ALLOW to allow).
- `command_risk.py` (OpenHands PatternSecurityAnalyzer + normalizer): HIGH-risk run_command is
  refused in a background job and always asks a human in the window.
- `task_tracker.py` (OpenHands): `task_tracker` view/plan with todo/in_progress/done, mirrored to plan.md.
- Novel Writer (MuMuAINovel): the pipeline prompts translated to English as skills
  (`skills/novel-writer/` + `stages/novel-world|characters|outline|chapter|analysis`), with the
  foreshadowing ledger and chapter analysis; the template loads all six.
- Drawing pad (PenEcho's idea, no code): `sketch_reply(shapes)` - LOKI draws back on the pad
  (sketches/loki-*.json, `GET /sketch/reply`, drawn under the user's strokes, toggle "LOKI's drawing").
- docs/EVOLVE.md: E1, E2, E3 ticked.

**Not done / check on a machine:** OpenHuman channels (that is roadmap E10, Telegram); no live
model has run these paths yet (all fakes) - watch the PC's next evolve step in Settings > Lab and the
Memory tab in WebKit (window.prompt for Edit); the pad's "LOKI's drawing" on a tablet.

## Session 25 (2026-10-17, Claude in the cloud): LOKI's own game engine + Play, the Brain map back, an audit

- **LOKI Pixel Engine** (`app/ui/engine/pixel_engine.js`): LOKI's own small WebGL 1 game engine in LOKI
  World's look - low-res framebuffer, Bayer posterize, 4 cel bands, ink outlines, flat-normal box/sphere/
  cylinder/cone/pyramid meshes, entities made of parts, camera, keys/pointer, HUD, beeps, collisions; the
  world's critters and props as models (fox, rabbit, tree, rock, berry, person, island). No libraries.
- **Play** (Settings > Play, `play_panel.js`, `/ui/play.html`): games run in a sandboxed frame
  (`allow-scripts` only - no token, storage or engine access). Built-in game: **Fox & Berries**. Games LOKI
  makes live in `<workspace>/games/<name>/game.js`, served by `GET /games/<name>/<file>` (only that folder,
  only .js/.json/.png/.svg) and listed by `GET /games/list`. Agent tool `game_engine_guide` gives the model
  the API + workflow + a full example. Only `/ui/play.html` may be framed, and only by LOKI itself.
  CHECK ON THE MAC: WebKit and a sandboxed frame's `'self'` scripts (ZIVA M12).
- **Brain map back** (Settings > Brain, `brain.js`): BUILD_BRIEF 5.7 said remove it "unless it becomes
  genuinely useful (browsing and correcting what LOKI knows)" - it now is: force-directed map of /brain
  (settles, then stops - no idle CPU), search, read any note, and **edit or forget a remembered fact** in
  place (memory.md via /memory). The Obsidian vault can be added there.
- Shading: no rim highlight on flat ground (it lit distant grass cyan at low camera angles) - world and engine.
- **Ziva on the PC** (the owner's Godot, not LOKI): its panel had vanished because Ziva was set to "Use Main
  Screen Tab" and the PC's portrait screen at 125% fits only two main-screen tabs. Switched it to a dock in
  Editor Settings > Ziva > UI; it shows on the left again.
- **Audit (all owner goals)**: none fully finished. Biggest gaps after this session: Godot code still in the
  repo (godot_tools.py, godot_assets.py, ~150 refs in loki.py, Godot MCP servers, the first-run Godot API
  step) although the owner wants nothing Godot; the PC as a real 24/7 worker (start at boot, cua VMs, Browser
  Use, a first LoRA run); evolve has not finished a step yet; the phone app never ran on a phone and cannot
  reach the computer through the relay; most add-ons only tested with fakes. Next session: remove Godot.

## Session 24 (2026-10-17, Claude in the cloud): the pixel look is back, the lag is gone, LOKI grows itself

The owner was right: session 22 made three.js (PBR, bloom) the default world and put the world
full-window behind live-blurred glass. That replaced the pixel cel-shaded look they liked and
made the window lag. Nothing was taken off; it was put back and the cost removed:

- **World: LOKI's own pixel cel-shaded engine is the default again** (`World.engine = "classic"`,
  `LOKI_WORLD_ENGINE` classic|three, default classic). Improved, not replaced: denser pixels (panel
  2 px, background 3 px - was 3 / 4), more colour bits (32 levels, was 20) and 4 cel bands (was 3).
  three.js stays as an option and is now loaded ONLY when chosen (no 2 MB module parsed at start).
  The session-23 asset fixes (benches, flags, books, seated people-sized agents) apply to both.
- **The lag**: every glass panel had `backdrop-filter: blur(22px)` over a 3D canvas that redraws
  30-60 times a second, and each world label had its own blur - the browser re-blurred all of it
  every frame. `--blur: none`; panels are tinted (more opaque) glass; the transcript's scroll mask
  is gone too.
- **The fox** (the owner loves the fox an agent made): a fox now lives on the island - trots between
  the flower patches, sits and looks around, goes to see LOKI now and then, and curls up asleep at
  night (little z's) - plus two rabbits. Same boxes, cel shading and ink lines as everything else.
- **A crashed engine is restarted** (`app/loki_app.py supervise`): on the PC the engine exited 1 at
  22:53 and the window sat dead until morning. Now it restarts with a growing pause and reloads the
  window; after 5 crashes in 10 minutes it stops trying. (Cause of that exit: not in the logs.)
- **LOKI grows its own "OpenHuman", by itself** (`engine/evolve.py`, `docs/EVOLVE.md`, Settings >
  Lab): a roadmap of steps (memory you can see, its own game engine with a Play panel, learning
  skills from its own work, subagents, more island life, a creations hall, speed watch, voice,
  self-review, tools it writes itself, a phone channel). When idle, the autopilot's `evolve` duty
  hands the next step to `improve_loki` (own worktree, all suites, ship), one at a time; outcomes are
  kept and fed into the next attempt; failures retry after 3 days. The owner's ideas (Lab > Add
  idea) go first; LOKI's own ideas wait for the owner's OK. `LOKI_EVOLVE` auto = on only on the
  Windows PC (on 24/7). Tests: tests/test_evolve.py (29).
- **"Moved to the web"**: nothing moved - LOKI is still the same desktop window (pywebview; the PC's
  log says "opening the Loki window" every start) talking to its own engine on this computer. Only
  the Mac-PC link goes over the internet (the bore.pub relay), and that is signed.

## Session 23 (2026-10-16, Claude in the cloud): options, drawing pad, world fixes, softer GUI, add-ons

All 22 suites pass. The owner asked: fix world assets that made no sense, 3-4 suggestions for an open
request, a way to draw for LOKI, OpenHuman/Remotion/OpenHands/PersonaLive/MuMuAINovel/marketing
skills/scraper/CRM, a less blue GUI, and Ziva's instructions in git only (not in chat).

- **"Which do you mean?"** (`engine/options.py`, `POST /options`, `Workbench.offerOptions`): an open
  request ("make me a game") gets 3-4 different readings as cards - title, meaning, what LOKI would
  do - and the pick is sent as a precise request ("Just do it as I wrote it" too). The decision is a
  local heuristic (`looks_open`), so specific requests cost nothing; only open ones make one model
  call. `LOKI_OPTIONS` auto|always|off in Settings > General; `/options <text>` forces it.
- **Drawing pad** (`app/ui/sketch.js`, `POST /sketch`): "✎ Draw" in the composer - pen with
  pressure (tablet/Apple Pencil), marker, eraser, colours, undo/redo. The PNG is saved to
  `sketches/` in the workspace and the next message tells LOKI to read it with `view_image`
  (whose default prompt now describes a drawing, not a Godot screenshot). PenEcho (a full AI canvas,
  AGPL) is the optional add-on for more.
- **World assets fixed** (`app/ui/world.js`): benches were built rotated 90 degrees (seat pointing
  at the pool, back sideways, legs along the wrong axis) - now `benchFrame()` builds slats, back
  rails, posts, legs and arm rests along the ring, facing the pool. Team banners had the same bug
  (flag edge-on): now a crossbar, a flag along the ring with its stage pips sewn on, and a hem.
  Library books stuck out of the shelf sideways: now they stand in it. Agents were 1.5x too big and
  sank into the ground when sitting: people-sized now (about 1 unit; LOKI a head taller), seated on
  the bench seat with feet on the ground; doors are taller than people. Bloom and glow sprites
  toned down (threshold 0.9, strength 0.38) so lamps and visors stop blowing out.
- **Softer GUI** (`app/ui/glass.css`): navy glass -> neutral graphite, cyan/blue/violet accent ->
  low-saturation sage/slate/lilac, lower text contrast (#e4e4e7 on graphite), body glow cut to a hint.
- **Add-ons** (see the section below, built in a worktree and merged): built-in CRM, Scrapling
  scraper, 50 marketing skills (MIT), OpenHands harness, PenEcho / OpenHuman MCP, Remotion videos,
  PersonaLive card, Novel Writer template. MuMuAINovel (GPL) and OpenHuman (GPL) are NOT vendored:
  the novel workflow was written from scratch; OpenHuman runs as a separate program over MCP.
- **OpenHuman vs LOKI:** OpenHuman (tinyhumansai/openhuman) is a Rust desktop agent harness in early
  beta - a peer, not a replacement: LOKI has the Mac+PC link, the world, teams, the workbench and
  self-shipping. It can be used as a tool server.

## Ziva (Mac), 2026-10-16: Bonsai 2 fixed, add-on packages installed, one-click add-on install

- **Bonsai 2 was broken by the tag.** `hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Q2_0` also matches the
  repo's `-PQ2_0.gguf` (Prism ternary, ggml type 142), which no Ollama can load ("unsupported tensor
  output.weight size overflows"); the runnable file is `-Q2_0.gguf` (ggml type 42), and Ollama only
  gained type 42 in **0.40.6** (PR #18967). model_setup now names the file in the tag
  (`:Ternary-Bonsai-2-9B-Q2_0`), the failure message says 0.40.6+, and test_models_media guards it.
  Verified on the Mac: Ollama 0.40.6, smoke test answers "Blue".
- **Add-on packages installed on the Mac**: browser-use, crawl4ai, headroom-ai, scrapling,
  hindsight-client, vision (trackers/supervision/rfdetr), agent-reach, ffmpeg.
- **New: install an add-on from the app.** `engine/addons_install.py` holds the pip plan per add-on;
  `POST /capabilities/install {name}` runs pip in LOKI's venv (no shell string); Settings > Add-ons
  shows **Install** on any add-on that is on but missing its packages, and a manual hint for the few
  pip cannot install (herdr, hermes, SkillSpector). test_integrations' "missing library" checks are
  now hermetic (skipped when the library is present).

## Ziva (Mac), 2026-10-16: the three.js world was dead in every checkout - fixed

- `.gitignore`'s unanchored `addons/` rule (a leftover from the Godot era) git-ignored
  `app/ui/vendor/three/addons/`, so the three.js post-processing add-ons were never committed.
  `world_three.js` failed to import, `window.WorldThree` was undefined, and the world silently fell
  back to the classic renderer on every clean checkout (the PC, CI, a fresh clone) - it worked only
  where those files were still on disk. test_portal's three.js checks only grep the source TEXT, so
  the suite stayed green while the feature was broken.
- Fixed: vendored the three.js r186 add-ons (MIT; `'three'` imports rewritten to local paths),
  anchored `addons/`/`scenes/`/`scripts/` in `.gitignore` to the repo root, wired `LOKI_WORLD_ENGINE`
  into Settings > General (it could not be set before), corrected `docs/THIRD_PARTY.md`, and added two
  regression checks (every `world_three.js` import exists on disk; the ignore rules stay anchored).
- On the Mac the world now runs three.js at quality "high": panel ema 6.97 ms (~143 fps, 80 draws),
  home 34.7 ms - higher quality and faster than the classic fallback (14.6 / 48 ms). Glass text
  contrast 9.7:1 (home) / 11.5:1 (World panel) over the lit world = WCAG AAA. Screens:
  `docs/operations/screens/glass-home-mac.png`, `world-three-mac.png`. Tasks M8/M9 answered in ZIVA_TASKS.

## Ziva (Windows), 2026-10-16: the PC's update bug fixed, and W17 verified

- The PC had NO git credential helper at all, so Git Credential Manager opened its interactive
  account picker (cancelled -> 403) and the fetch failed - `harness_data/app/loki_app.log` showed
  repeated "GitHub sign-in needed on this PC", and LOKI could not update. Fixed on the machine
  with `gh auth setup-git` (wires the gh token as the credential helper); `git fetch` now works
  with no prompt and LOKI updated itself. (Claude's Mac-side updater fix bdfba9b was already on
  master; this was the PC's own missing piece.)
- Pulled master and ran W17 end to end: 21 suites green; LOKI World is three.js once M8's fix is
  on the PC (60 fps at high quality on the RTX 3070 Ti, WebGL 2 via ANGLE/D3D11, so the earlier
  silent classic fallback is gone); the "/" command palette, /review (a real unified diff) and
  /rewind (removed the file) were verified in a real Chromium over CDP;
  hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Q2_0 pulls (3.0 GB) but Ollama 0.40.5 cannot load it
  ("unsupported tensor 'output.weight' size overflows"); GET /forecast backend = statistical
  (TimesFM deliberately not installed). Screenshot docs/operations/screens/world-three-windows.png.
  Details and the Mac's diagnosis JSON are in ZIVA_TASKS.md (W17 + Reports).

## Session 23 add-ons (worktree)

Built in a worktree by a Claude subagent; the parent merges and ships. New suite
`tests/test_addons.py` (in ship.py SUITES). Nothing below has run against the real programs
(no Scrapling, OpenHands, PenEcho, OpenHuman or Remotion was installed): command lines and
fallbacks are tested with fakes.

- **Built-in CRM** (`engine/crm.py`, SQLite at `harness_data/crm.sqlite3`): companies, contacts,
  deals (stage lead..won/lost, value, currency), interactions (note/call/email/meeting), tasks (due,
  done), find, history and a pipeline summary (per stage, open/won value, win rate, overdue tasks).
  Agent tools `crm_add/crm_update/crm_find/crm_log/crm_pipeline` (category "business"; writes are
  hidden in Plan mode). Bridge `GET /crm`, `POST /crm/<add|update|delete|find|log|list|pipeline|history>`.
  Settings > CRM tab (`app/ui/crm.js`): pipeline line, deals (stage picker), contacts, companies,
  tasks, add forms.
- **Scrape** (`engine/runners/scrape.py`, conductor role `scrape` + agent tool `scrape(url, crawl,
  max_pages, dynamic)`): Scrapling Fetcher/DynamicFetcher markdown, or a SiteToMarkdownSpider crawl
  into `scraped/<domain>/` (+ pages.jsonl), max 200 pages. No StealthyFetcher / Cloudflare solving.
  Without Scrapling it reads the one page via read_web (crawl4ai / Firecrawl) and says
  `python tools/setup_extras.py scrapling`.
- **Marketing skills**: 50 skills from coreyhaines31/marketingskills (MIT, commit 365b412) in
  `skills/marketing/` (SKILL.md + references/, no evals; 2.8 MB) with its LICENSE;
  `agents.skill_roots` has a "marketing" root, and `list_ecc_skills` sees them too.
- **OpenHands** harness: worker agent + agent-builder engine + CLI agent (`openhands --headless
  --json --override-with-envs -t <task>` in the workspace). `workers.openhands_env` sets
  LLM_MODEL=openai/<LOKI's local model> (LOKI_LOCAL_MODEL, else the resolved LOCAL_STATE),
  LLM_BASE_URL=http://localhost:11434/v1, LLM_API_KEY=ollama; `LOKI_OPENHANDS_MODEL/_BASE_URL/_API_KEY`
  override. Needs the `openhands` add-on (process:agent). Template "OpenHands Coder".
- **Add-ons** (all off, never auto-installed; `setup_extras.py <name>` only when named, not in `all`):
  `penecho` (AGPL, MCP `penecho mcp`, card button "Open drawing canvas" -> http://localhost:3888),
  `openhuman` (GPL, MCP `openhuman-core mcp`), `remotion` (custom licence; tools `video_project` /
  `render_video`, ask first, `engine/runners/video.py`), `personalive` (card only: Windows/NVIDIA,
  academic licence, cannot be turned on), `openhands`, and `scrapling` got an install hint. Manifests
  gained optional card fields (`install`, `setup_extras`, `notice`, `actions`, `platforms`,
  `card_only`; the first four are cosmetic for trust). An MCP entry with `"capability": NAME` starts
  while that add-on is on. `/open` also allows add-on homepages and card buttons.
- **Novel Writer** template (`agents.TEMPLATES`, written from scratch): idea -> world -> characters ->
  outline -> chapters -> continuity check -> rewrite, all in `novel/`.
- Not done: the Twenty CRM connector (not needed now); no real install/run of any add-on.

## Session 22 (2026-10-16, Claude in the cloud): three.js world, glass GUI, workbench, Bonsai 2, TimesFM-3, Higgsfield, Mac hangs

Two commits. All 21 suites pass (`tools/ship.py --check`).

- **Mac "not responding".** Its engine still answered over the relay (444 ms, latest version), so the
  hang is the window or the machine, and the Mac's history points at memory: 16 GB, swap at 96-100%
  (M7: image-gen crashed WindowServer). Shipped: `GET /peer/diagnose` (busy locks, progress, failing
  system-check rows, Ollama's loaded models, memory pressure, update status, redacted log tails) and
  `POST /peer/restart`; from the UI side `POST /peers/diagnose|restart {peer}`. And the cause itself:
  `forecast.memory_tick` runs every minute in the bridge, forecasts memory 10 minutes ahead and, when
  LOKI is idle and memory is heading past 92%, unloads idle Ollama models (keep_alive 0) - at most
  once per 2 minutes. Not yet read on the real Mac: ZIVA_TASKS M8.
- **PC updates hung on the Git Credential Manager account picker.** `updater.git_env` now makes GCM,
  ssh and askpass non-interactive and passes `credential.https://github.com.username=<origin owner>`.
- **LOKI World on three.js** (`app/ui/world_three.js`, vendored r186): PBR, shadows, bloom, ACES, the
  water shader ported, instanced agents; linked machines are islands with a live light bridge; HUD
  shows model, today's cost and machines. The classic renderer stays as the fallback
  (`LOKI_WORLD_ENGINE=classic`). Godot/Panda3D were rejected: no Godot in the repo (AGENTS.md) and
  Panda3D would be a second window outside the webview; three.js runs inside the existing UI.
- **Glass GUI** (`app/ui/glass.css`): frosted panels over the full-window world, gradients, rounder;
  `prefers-reduced-transparency` falls back to solid.
- **Workbench, the Claude Code/Ziva habits** (`engine/workbench.py`, `app/ui/workbench.js`):
  checkpoints in a private shadow git store before every Build request, Review (diff), Rewind
  (undoable), `@file` mentions, an `@` picker and a `/` palette (/plan /build /review /rewind /bg
  /team /test /commit /model /image ...).
- **Bonsai 2** (PrismML, Apache-2.0) in `model_setup.CATALOG`: 9B/4B/2B ternary GGUF (Q2_0) pulled
  by Ollama from Hugging Face, plus the 9B MLX build. Q2_0 needs llama.cpp b11555+, so after a pull
  `verify_runs` asks one question and reports gibberish as "update Ollama". An installed model
  within 6 points (`INSTALLED_BONUS`) now beats a download, so nobody is nagged for a small gain.
- **TimesFM-3 in the core** (`engine/forecast.py`): one forecaster (TimesFM-3 when `timesfm3` is
  installed - MLX on Apple Silicon, torch elsewhere - Holt's damped trend otherwise) feeds three
  decisions: routing (`loki.routing_order` moves a provider forecast to be >2.5x slower to the back),
  the memory guard, and the spend outlook (`GET /forecast`). The agent has `forecast_series`.
  `POST /forecast/install` pip-installs it. Kill switch `LOKI_FORECAST=off`. NOTE: TimesFM-3's
  weights are licensed for non-commercial use; LOKI never installs it on its own.
- **Higgsfield** (`engine/higgsfield.py`): images (and video with an application id) via the
  official SDK's protocol, stdlib only. The key is pasted by the owner in Settings > General >
  "Higgsfield key" (KEY:SECRET), stored as `HIGGSFIELD_KEY` in LOKI's .env and never sent back to the
  window (new `secret` setting kind). Tool `generate_media`, route `POST /media/generate`, command
  `/image`. Outputs are downloaded into the workspace's images/ or videos/.
- **Not done:** "framepipe" - no repo by that name is visible to this session; the owner needs to
  give the exact GitHub name. No API keys were searched for or copied anywhere.

## Session 21 (2026-10-15, the PC - Ziva Windows): the agent/computer boundary, and one memory

All 19 suites green on the real PC (`tools/ship.py --check`), including test_systems "the bridge
rebinds the same port immediately" (SO_REUSEADDR off on Windows) - the `[windows]` signal Claude
asked for. `macos-app` and `origin/macos-app` are 0 ahead of master: **master really is the one
branch.** The old gap `backup/pc-merge-c25660f` is REVIEWED below.

- **ACI: bound EVERY tool result, and check a file the moment it is written** (ecc2558).
  `MAX_OUTPUT` bounded only COMMAND output, so a large `read_file` dumped a whole file into a local
  model's context. Now one choke point (`call_tool`, local and MCP): `loki._elide()` keeps the head
  AND the tail (errors and totals live at the end) and inserts a marker naming what was dropped.
  `loki._check_written()` checks a file the instant write/edit/append returns - `.py` (ast), `.json`,
  `.gd` (Godot). To SEE what a model really received, read `GET /progress?after=0` (bearer token):
  it carries `tool_result` events. Proof: a local model wrote a broken file and got "SYNTAX ERROR in
  scripts/check.py: invalid syntax (line 1)" in the same result.
- **`engine/memory.py`: ONE interface over the four tiers LOKI actually has** (272d30d). `working`
  (project_state) / `episodic` (reasoning_bank + experience) / `semantic` (memory.md facts + brain
  vault + knowledge) / `procedural` (agents.skills_catalog), behind `remember` / `recall` / `stats` /
  `describe` / `tier_of`, each DELEGATING to the module that already owns the bytes - no storage moved.
  `save_memory` writes through the semantic tier; the status payload carries `memory.stats()`. A
  read-only tier says so (procedural -> "write a SKILL.md instead").
- **Difficulty-aware routing** (d6c2db6). `LOKI_PREFER` defaults to `local`, so smart mode was
  local-first for EVERYTHING - hard work stayed on the weak offline model. `loki.triage_difficulty()`
  + `LOKI_HARD_DIFFICULTY` (default 2) now drops local-first for a hard request.
- **Local models are chosen by MEASURED tool calling** (0cd6012). `experience.tool_stats`/`tool_score`
  score each model on tool rate + clean rate; `loki._best_local_by_tools` picks the best record. The
  note explaining the pick is surfaced as `local_note`; `/status` carries `tool_stats`.
- **The literal `<tool_call>` tag crashes Qwen3.5's Ollama runner** (eb1919d, found on the PC).
  Ollama dies with `HTTP 500 {"message":"EOF"}` - reproduced on `loki-qwen3.5-9b` and `qwen3.5:9b`;
  `qwen3:8b`/`hermes3:8b` are fine. The harness now teaches a fenced ```json block and `parse()`
  still accepts `<tool_call>`. The old `_FENCE_RE` was non-greedy, truncating at the first `}` - so
  every real file write failed to parse; it now captures to the closing fence.
- **`engine/evals.py` (from Inspect) + `docs/architecture/SYSTEMS_TO_IMPORT.md`** (575e21d): Task =
  dataset + solver + scorer; scorers `wrote_file`/`called_tool`/`answered`; `record()` feeds the
  routing scorecard. The doc is the open-source deep dive (9 systems, verdicts, a "deliberately NOT
  taken" table, a priority list). Items 1-4 of that list are shipped: evals, difficulty routing,
  check-on-edit, memory tiers.
- **Ruflo's plugins are really committed, and image-gen is really on** (68882cc, a260f1a, 73043ee).
  `.gitignore`'s unanchored `plugins/` rule hid `contrib/ruflo/plugins` (0 files tracked), which made
  master red on a fresh clone; anchored to `/plugins/`. A changed image-gen manifest had silently
  flipped it to `changed` (= off); re-enabled and re-saved all 10 capabilities with the new `trust`
  field - live, an agent made an image in 24.8 s.
## Session 20 (2026-10-15, cloud + the PC): real water, and local models' long tool calls

- **Water** (app/ui/world.js `WATER_FS`, app/ui/world_noise.js): its own shader with an exact
  shore distance per body (no depth texture, works on every WebGL 1 driver): Beer-Lambert depth
  colour, wobbling shoreline foam + a breathing second line, cellular caustics, Schlick fresnel
  sky reflection, stepped sun/moon glint, station lamps reflected at night, whitecaps on the
  stream, ripple rings (LOKI's beacon pings the pool on every new board line; a fish jumps in
  the pond), a waterfall sheet with sliding streaks and a white lip. Stone curbs, lily pads, a
  tiled pool floor. Credits: docs/THIRD_PARTY.md (stegu/webgl-noise MIT; paddy-exe stylized
  water MIT). Screens: docs/operations/screens/world-water-*.png.
- **Found on the PC** (harness_data/_engine_ziva6.log, 10:37 today): a local model wrote a whole
  todo page as a TEXT write_file call; LOKI dropped it because the scanner counted the CSS/JS
  braces inside the content and the model left off the final "}". Then a reply was cut off
  mid-call and lost; the task looped to the step limit with no file. Fixed: string-aware
  `tool_guard.json_object_spans`, `close_truncated` (only adds missing closers at the very end),
  and `loki._unfinished_call`: a cut-off call is kept and the model is asked to continue it,
  then the two parts are joined. 7 checks in test_tool_guard built from that run.
- **Why the PC fell behind the Mac all day** (harness_data/app/loki_app.log on the PC): every start
  said "update waiting: local changes to 3 file(s)" - an agent's unfinished edits (a new memory
  interface) blocked EVERY update. engine/updater.py now carries uncommitted edits across an update
  when git merges them cleanly (three-way, CRLF-aware, backup under refs/loki/backup/edits-*); a
  real conflict still blocks as before. The PC's three edits were checked: all merge cleanly.
  test_updater: +12 checks.
- **Mac <-> PC live across networks** (the owner chose the built-in relay over Tailscale):
  engine/relay_link.py speaks bore's protocol in plain Python; each machine publishes its peer
  port on bore.pub at ports derived from the shared secret, and dials the other as name=relay
  through a loopback forwarder. Responses are now signed and bound to the request
  (peers.sign_response) and checked over the relay; a dead or wrong relay port is skipped.
  One link code links both ways (peer_link.link_back). Settings > Machines shows the relay;
  GET /peers/relay-test proves the loop on a machine. tests/test_relay.py (23, fake bore server).
  PROVEN LIVE on the PC against the real bore.pub (2026-10-16): the owner pasted the Mac's own
  link code into the PC's Settings > Machines, so the pair is linked both ways - the PC reaches
  mohameds-mac-mini through the relay in 423-425 ms (relay-test ok 2935 ms), and link_back adds
  the PC on the Mac by itself. ZIVA_TASKS R1 is done; nothing left for the owner.

## Session 19 (2026-10-15, cloud): LOKI World becomes a life sim, and stays smooth

Owner: "go through what's not working, only add, make the LOKI world more like a sim, more
features, improve the graphics, keep everything running smooth". All 16 suites pass.
Rendered and checked in headless Chromium (software WebGL) with a mocked /world - screenshots
docs/operations/screens/world-sim*.png. NOT yet seen on the real Mac/PC GPUs (ZIVA_TASKS W10).

What was not working (fixed, tested):
- **/world re-parsed the whole event log twice per poll** (up to 4 MB, every 2.5 s, per open
  view). `engine/events.py _tail_scan()` now reads only what was appended (rotation and
  half-written lines handled); `latest_seq()` uses it too. test_events proves no lines are
  parsed when nothing is new.
- **Two agents with the same role shared one speech line** (messages were keyed by sender
  only): now by team + sender.
- **A blocked agent's red light was always dropped** (exactly 10 lamps filled the shader's 10
  lights): lights are ranked; alerts first.
- The blocked/selected ground rings z-fought into invisibility (16-bit depth, near 0.1): rings are
  now opaque dashes and the near plane is 0.5.
- A lost WebGL context (sleep / GPU switch) left the world black forever: it is rebuilt.
- Drag could stick (no pointercancel); no pinch zoom; agents stood inside lamps and each other;
  labels piled on top of each other.
- **False DONE in the main task loop** (Ziva's [claude] request): `make_dir` - or a write that
  returned an error - counted as "changed a file", so "create notes/hello.txt" was accepted after
  only `mkdir notes`. engine/loki.py: errors change nothing; a goal naming a file needs a file.

Added (app/ui/world.js, docs/WORLD.md "The life-sim layer"):
- Agents walk round the plaza (not through the pool), act out each station's work (book,
  hammer + sparks, typing + lit screen, bubbling beakers, stamping, drawing), role hats, LOKI's
  horns, state icons (cube / hourglass / red "!" with a hand up / cheer + confetti / grey cloud).
- Done/idle agents leave the desk, sit on benches, wander and "chat" (a wordless ···).
- Team banners in the plaza with one pip per real stage (`teams[].stages` from the engine).
- Settings > LOKI World: click an agent or legend row -> inspector card (all from /world:
  task, station, machine, time on task, team + stage, last line), double-click / Follow ->
  camera follows, Esc, arrows, pinch. A HUD with local time and the real counts (`stats`).
- Scenery: reflecting pool, pond + waterfall + mist, flowers, grass, benches, crystals under the
  island, floating islets, birds, fireflies, twinkling stars, chimney smoke when building.
- /world adds per agent `since`, `finished`, `stage`; per team `stages`; top-level `stats`.

Smooth: the static scene is baked once (3 draws for everything that never moves, +2 for the
turning clouds/islets) - ~200 draws per frame whatever the scenery, ~1 ms of JS per frame.
A frame-time watcher steps world pixels one size coarser when frames run late and keeps it only
if frames really got faster (`World.adaptive = false` pins it). `prefers-reduced-motion` stops
the ambience.

Libraries: none added on purpose. The UI is offline and CSP-clean, and test_portal forbids
loading anything external; three.js/OGL/regl would add weight for things this renderer already
does. If a library is ever wanted, vendor it into app/ui (no CDN).

Next (ZIVA W10): open Settings > LOKI World on both machines, start a team, screenshot, report
frame feel and `World.views.panel.perf` (ema ms, boost, draws).

## Session 17 (2026-10-15, cloud): local models that work, and an app that works by itself

Shipped to master at the owner's direction once both machines were online. All 16 suites
pass (cloud + CI on macOS and Windows). The two real-hardware checks (S2 local-model tool
calling, S3 idle autopilot) are open in ZIVA_TASKS - they confirm behaviour on a real
Ollama, they do not gate the code. Kill switches: `LOKI_AUTOPILOT=off`,
`LOKI_CONSTRAINED_TOOLS=off`.

- **Found why local felt useless** (`engine/loki.py`): a local provider that failed ONE
  request (a cold model load timing out, a brief restart) was marked used-up for the whole
  session, so every later request silently went to cloud or Claude Code until a restart.
  Now `revive_local()` brings a local provider back at the start of the next request once
  its server answers again (`LOKI_LOCAL_REVIVE_S`, default 20s). test_tool_guard proves it.
- **Tool-call guard** (`engine/tool_guard.py`, wired into `agent_turn`, text recovery and
  `call_tool`): repairs the calls small models get wrong - bad JSON (single quotes,
  trailing commas, fences), near-miss tool names (create_file->write_file, ls, cat, bash),
  numbers sent as strings, calls written as code - and when it cannot, returns ONE precise
  sentence naming the missing argument and the signature. GUARD_STATS counts repairs/rejects.
- **Constrained decoding for local servers** (`_use_constrained`/`_constrained_request`):
  sends a json_schema response_format so Ollama/llama.cpp can only produce a real tool call
  or an answer; falls back automatically if a server refuses it. `LOKI_CONSTRAINED_TOOLS=
  auto|on|off` (auto = on for local servers already in prompted-tool mode).
- **Agent factory picks a model per role** (`experience.role_stats`/`best_for_role`,
  `team.py`, `loki.model_for_role`): each team role (builder, tester, reviewer...) gets the
  model that has measurably done THAT job best, within the spending policy; a cheaper tier
  wins a near-tie; a pinned team model always wins. Jobs now record their role so outcomes
  can be scored. This is BUILD_BRIEF 5.3 "best spec per role", first real version.
- **Autopilot** (`engine/autopilot.py`, started by the bridge, `GET /autopilot`, a System
  check row): when LOKI is idle (no request in flight, no job, quiet for
  `LOKI_AUTOPILOT_IDLE_S`=600s) it does ONE duty per pass - **health** (run the System
  check, apply only the always-safe fixes, never approve/spend/update), **inbox** (start the
  oldest open `[loki]` request in ZIVA_TASKS.md as a team, one at a time), **report** (weekly
  "what LOKI learned": verified work, best model per role, routing changes, tool repairs,
  training readiness, in harness_data/reports/). `LOKI_AUTOPILOT=off` turns it all off. This
  is the first piece of BUILD_BRIEF 5.4/5.6 "alive and improving on its own".
- **Cloud testing is real now**: `tests/cloud_stubs/openai` used to fail every call, so the
  offline e2e and HTTP-400 checks were skipped in the cloud. It now speaks the
  chat-completions wire format over urllib, so every suite runs against the fake Ollama for
  real. Register it once per sandbox (see tests/cloud_stubs/README.md). The Mac/PC use the
  real openai package, unchanged.

Next (ZIVA): S2 - on the Mac and PC with real Ollama, run "create notes/hello.txt with hi,
then list the folder" with LOKI_CONSTRAINED_TOOLS=off/auto/on on your installed models,
record valid-call rate + GUARD_STATS. S3 - leave LOKI idle and confirm the autopilot's
health row and a weekly report appear (GET /autopilot).

## Session 16 (2026-10-15): System check + positive integration tests

## The machines

| | Mac mini | Windows PC |
| --- | --- | --- |
| Name / address | `mohameds-mac-mini`, 192.168.1.71 | `pc` (`mo`), 192.168.0.101, RTX 3070 Ti |
| Checkout | `~/Documents/loki` (becomes a git checkout on the next LOKI start) | `C:\Users\macul\Documents\loki` (on `macos-app`; moves to `master` on the next start) |
| Laya (first layer) | not installed yet: run `bash setup.sh` once | installed, model downloaded, self-test passed |
| Keys | none yet (Settings > Connections) | OpenRouter, DeepSeek, Groq, Gemini, Claude Code, Codex |
| Peer link | set to **listen**, not linked to the PC | listening on 8768 as `pc` |

**The link does not work yet.** The two machines are on different networks (192.168.1.x and
192.168.0.x), so they probably cannot reach each other directly. Fix: put both on the same
network, or install Tailscale on both (the link accepts Tailscale addresses), then on the Mac
use Settings > Machines > *Link another machine* with the PC's code (not "Let other
machines link to this one").

## Same version everywhere (done, session 12)

- `engine/updater.py`: every LOKI fast-forwards to GitHub `master` when it starts; a plain
  folder copy is turned into a checkout in place; local edits and unpushed commits are never
  overwritten; while running it only checks and shows "update waiting".
  2026-10-15 (Mac updates not working): git now runs with Homebrew/~/.local/bin on PATH (the
  `gh auth git-credential` helper was invisible from Finder/launchd) and `-c safe.directory=*`;
  stuck states fixed instead of blocking forever (already-published local commits dropped,
  real ones rebased and kept unpushed, backup in refs/loki/backup/*; stale/deleted files
  restored; real edits block and are named); failures are mapped to an actionable message and
  persisted in `.git/loki_update_last.json`, so `/health` `update.error`/`update.problem` show
  the start-up result. Version label: `VERSION` file + commit count -> `update.label`
  "v0.16 · patch N" (UI still has to display it: app/ui/app.js showVersion).
- `tools/ship.py`: the one way to publish (tests, commit, rebase, re-test, push, tell peers).
- `.github/workflows/tests.yml`: every push is tested on macOS and Windows.
- LOKI can change and ship its own code: tools `improve_loki` (a background agent in a git
  worktree of LOKI) and `ship_loki` (runs ship.py). `LOKI_SELF_SHIP=auto|ask|off`, default
  auto; ship.py refuses to push unless every suite passes.

## Agent teams (done, session 12) - BUILD_BRIEF 5.3, first version

`engine/team.py` + tools `start_team`, `team_post`, `team_read`; `/teams` API; teams in the
work strip with their board. Roles per goal (Laya or rules), stages plan -> build -> check,
one fix round, stops when a stage cannot finish. Verified offline (tests/test_team.py) and
live on the engine API without a model (the team stopped correctly at the architect).
Not yet: placing team stages on the PC over the peer link; a real model run end to end.

## Phone app (2026-10-15, branch claude/phone, not shipped yet)

The owner asked for iOS + Android and a phone-local model. Built: `mobile/` (one Expo app:
Chat, Connect, Models) that chats with LOKI on the Mac/PC when reachable, else with a small
on-phone model (Cactus: Needle for quick actions + Qwen3 0.6B etc.; llama.rn as the swap-in).
Engine side `engine/phone_link.py` (opt-in, port 8769, per-phone signed keys, Ask/Plan only,
a phone message can never approve), the Phone card in Settings > Machines, docs/PHONE.md,
tests/test_phone_link.py. NOT yet: npm install / prebuild / a run on a real phone (the npm
registry was unreachable where it was built); see docs/PHONE.md "Not done yet".

## Session 17 (2026-10-15): Mac updates really work; bridge port fix; S1/S2 live; phone typecheck

Ziva (Mac). Shipped as v0.16 · patch 165/166.
- **The Mac updater worked, but a GOOD version was being rolled back.** On restart the Mac pulled
  origin/master `fb6f66806db6` and the engine could not bind 127.0.0.1:8767 - `OSError: [Errno 48]
  Address already in use` - so the app rolled back and recorded the commit in
  `.git/loki_update_health.json` `skip[]`, leaving the Mac one version behind. Cause:
  `BridgeHTTPServer.allow_reuse_address = False`, so a just-exited engine leaves the port in TIME_WAIT
  and macOS refuses the rebind for ~30 s. Fix: `allow_reuse_address = True` + a `port_is_answering()`
  guard (a live engine is still never overwritten - that matters on Windows). Regression check in
  `tests/test_systems.py` (fails without the fix).
- **Two tests were red on the Mac** (CI is off, so nobody saw it): `test_loki`'s status/upgrade check
  depended on the real models disk, and `test_updater`'s "a missing disk is named" hard-coded
  `/Volumes/LokiSSD/loki` (which exists here). Both made machine-independent; all 13 suites green.
- S1 System check (Mac): "All 12 systems work together. 3 worth a look" - no red rows. S2 (Mac):
  version label / model button / Settings > Local models verified; `world-mac.png` re-captured.
  P1 phone app: `npm install`, `expo install --fix`, `typecheck` (after fixing
  `mobile/src/brains/cactus.ts` to the installed Cactus types) and `prebuild`; `run:ios` blocked on
  Xcode + CocoaPods + an iPhone (Needs Mohamed).

## Session 16 (2026-10-15): System check + positive integration tests

The owner saw only red ("systems aren't integrated and working together yet"). Now:
- **System check** (`engine/system_check.py`, Settings > System check = first tab, and "Check
  everything" in the sidebar): 14 ordered checks in a background thread, each
  `{id, title, status ok|warn|fail|skip, detail, fix}` - engine/version/update problem; a model
  answers through the real smart route (latency, dead providers and why); that model calls
  `list_tree` through `_model_request` (prompted harness included); first layer; a real
  background job (built-in agent, `selfcheck` mode: no model, no tools) watched through the jobs
  API, the event stream and /world; a team dry run (board, events, world, then cleaned up);
  policy rules; add-ons changed/invalid; image backend (no image unless "Run a real image test");
  local models; usage + ReasoningBank; peers; phone link; disk + memory. Routes: GET/POST
  `/system/check`, POST `/system/fix` (safe actions only: provider_off, revive_providers,
  laya_warm, start_ollama, jobs_start, zimage_retry; never approves add-ons, updates or spends).
- **tests/test_systems.py** (in ship.py): five scenarios wiring real modules with fakes only at
  the edges - goal -> first layer -> model -> conductor -> policy -> usage -> ReasoningBank recall;
  jobs API -> real child process -> events -> world; team plan/build/check/fix -> verified;
  providers dying mid-run (402/401) -> failover -> the check names them and switches them off;
  the check all-green / red rows with the right fixes / over the engine's HTTP routes.
- Bugs found by wiring things together (fixed, tested): ReasoningBank stored every finished chat
  as a failure; the conductor's prompt section vanished when no specialist was ready; /fleet sent
  a second 404 response; a check job could wait behind the one local-model slot.
- Next: ZIVA_TASKS S1 - run it on the PC and the Mac and report the rows.

## Session 15 (2026-10-14): repo private, Godot story removed, suites hermetic

Ziva (Windows), after pulling the session-14 branch into master:
- master fast-forwarded onto `claude/portal-world-updates` (portal, sign-in/QR, agent builder,
  3D world, Update everything, specialists).
- `m03dev/loki` made **private** (owner's request). The Mac must run `gh auth login` (ZIVA M2)
  or it stops getting updates; the PC is already authenticated.
- The "project is still in Godot" confusion removed: README, docs/WORLD.md, docs/STATUS.md,
  HANDOFF and docs/ARCHITECTURE.md now say the world is in the app (plain WebGL); the Godot
  task ZIVA_TASKS W9 is cancelled; the leftover Godot `addons/` deleted.
- test_loki + test_hardening made hermetic: they failed only on a machine that runs Ollama /
  llama-server and whose `.env` sets OPENROUTER_MODEL to a paid model. All 11 suites pass; no
  assertion was changed.
- `docs/LOKI_BLUEPRINT.pdf`: the improved master prompt + research + plan + both task lists.

## Session 14 (2026-10-14): portal, sign-in, Update everything, agent builder, 3D world

Built in the cloud by Claude; see ZIVA_TASKS.md for the full list and the machine checks.
- Settings reworked: General, Connections portal (43 providers, switches, Test, model picker,
  OpenRouter sign-in, QR codes, phone hand-off), Agents (builder), LOKI World (3D),
  Machines & updates (Update everything), Add-ons.
- Any model can use tools (engine/tool_harness.py); new providers and OpenCode.
- Update everything: peers first, then this machine; app restarts the engine (exit 75);
  a version that fails to start is rolled back and skipped (updater health file in
  harness_data/app/update_health.json).
- New specialists: media (yt-dlp, now in requirements), image (Z-Image Turbo / Pollinations),
  reach (Agent Reach). Optional installs: tools/setup_extras.py.
- Not run on a real machine yet: everything above. Ziva W1-W10 / M1-M7 are the checks.
- Not integrated: OBLITERATUS (removes model safety refusals). Kyojin is wired in but needs a
  Strix Halo machine.

## Session 13 (2026-10-14): the owner's five-layer vision

- docs/VISION.md (the owner's vision, kept), docs/STATUS.md (every item checked against the
  code - read it before planning), docs/WORLD.md (world protocol + Ziva brief).
- `events.py`: one event stream (task.*, agent.*, approval, artifact, verification, decision)
  emitted by jobs, teams, the first layer, approvals; `/events` long poll, `/world`.
- First layer returns the full structured decision; Jev answers when Laya cannot.
- Machines advertise real capabilities in hello.
- Spending policy: no automatic paid routing unless LOKI_ALLOW_PAID=1; daily dollar cap.
- Fixed: the goal loop's endless "premature DONE" path.
- The world is in the app (WebGL 3D); there is no Godot project. Checks: ZIVA_TASKS.md W6/M6.

## Done earlier (see docs/operations/SESSION_LOG.md)

engine/ layout and no Godot files (5.1); Background and Brain tabs replaced by work in the
conversation (5.7); Laya as the first layer, warm and measured (5.2); docs cleaned (9).

## Next, in order (docs/BUILD_BRIEF.md section 5; Ziva's list is ZIVA_TASKS.md)

1. Get the link working (network or Tailscale), then verify a job from the Mac runs on the PC.
2. 5.3 next steps: run a team end to end with a real model; place heavy stages on the PC
   (peer link) and stream their board notes back.
3. 5.4 the PC alive 24/7 as a service (start at boot, watchdog, apply updates on restart).
4. 5.5 cua VMs + Browser Use on the PC; 5.6 self-improvement loop running on its own.
5. 5.8 more model sources; 5.9 Ziva (no public API found as of 2026-10).
6. The owner asked for agents "talking and in game": agents talking is the peer link + team
   board (5.3); "in game" needs a decision from the owner (agents shown inside a game, or
   agents that build and play-test game projects).

## Known gaps

- The real Laya model is verified on the PC only.
- ~~`backup/pc-merge-c25660f` ... not reviewed.~~ REVIEWED (Ziva Windows, 2026-10-15): the branch is
  local-only and holds exactly ONE commit master lacks - the pre-restructure merge whose content is
  the old `addons/loki/harness/` layout (`jobs.py`, `worker.py`, `workers.py`). That layout was
  deliberately replaced by the top-level `engine/` + `engine/workers.py`; jobs.py and worker.py do not
  exist on master. Nothing master lacks, safe to delete (kept as a backup branch on purpose).
- A running engine does not restart itself after an update; the next start applies it.


## Ziva (Windows), 2026-10-17 (later): everything installed - Ollama, Bonsai 2, Kokoro, TimesFM, ACE-Step

Mohamed asked to install everything outstanding. Done on the PC, all 32 test suites green:
- **Ollama 0.40.5 -> 0.40.6** (winget has no newer manifest; used the installer from ollama.com) and Bonsai 2
  re-pulled as `hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Ternary-Bonsai-2-9B-Q2_0` - it loads and answers.
- **kokoro 0.2.2 + soundfile** into the venv (needed `--only-binary=:all:`; plain pip tried to build
  spacy->thinc->blis from source and failed). Fixed a real bug: `engine/voice.py` now hands Kokoro an
  ASCII-safe copy of its config, because Kokoro opens config.json with the Windows cp1252 locale though the
  file is UTF-8, so every call raised UnicodeDecodeError and fell back to the SAPI voice. `speak` now uses
  Kokoro (a real 24 kHz wav). espeak-ng did not install (its MSI needs admin/VCRedist); it is optional.
- **TimesFM 3.0.2** installed; /forecast reports timesfm_installed true.
- **ACE-Step 1.5** installed (C:/Users/macul/ACE-Step-1.5, uv sync) and running on http://127.0.0.1:8001
  with `ACESTEP_OFFLOAD_TO_CPU=true` (without it the 8 GB card had no free VRAM and the CPU VAE decode hung
  for 10+ min). A fox song produced a real 30 s / 480 KB mp3. Fixed `engine/music.py`: the server returns
  `file` as a ready `/v1/audio?path=...` and the client wrapped it AGAIN -> HTTP 403; `audio_url()` now uses
  a ready path as-is.

Two small code fixes (voice.py, music.py), 3 new checks in tests/test_research_ports.py (now 146).
