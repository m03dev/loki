# Carbon MMO Foundation

A code-driven, modular MMO engine base built on the open-source **Carbon** framework
(EVE Online's engine, [github.com/carbonengine](https://github.com/carbonengine), MIT / PSF-2.0).
No editor. Every subsystem sits behind an interface so Carbon modules can be swapped for
custom ones one at a time.

```
 scripts/init_render.py ──configure_render(cfg)──▶ ┌───────────────────────────────┐
         ▲  cmmo_engine.log / Vector3 / on_frame   │ cmmo_host (C++)               │
         └──────────────────────────────────────── │  MODULE: script-host  (Python embed)
                                                   │  MODULE: render  null | glfw  │
                                                   │  MODULE: math    Carbon Vector3
                                                   └───────────────────────────────┘
 python/cmmo/            engine packages (no game rules)
   mathbridge.py         MODULE: math         Carbon Vector3 via cmmo_math, Python fallback
   net/transport.py      MODULE: net.transport      std sockets | CarbonIO
   net/connection.py     MODULE: net.connection     peers, handshake, timeouts
   net/serialization.py  MODULE: net.serialization  schemas + binary/JSON codecs
   net/heartbeat.py      MODULE: net.heartbeat      ping/pong, RTT, server clock
   net/sync.py           MODULE: net.sync           SyncServer / SyncClient, generic replication
   ecs/                  MODULE: ecs          entities, components, systems
   nav/                  MODULE: nav          Destiny adapter | kinematic fallback
 python/cmmo_game/       MODULE: game         example game layer (click-to-move)
```

## Carbon Editor (`cmmo_editor`)

A native C++ **game engine editor** for a World of Warcraft-style online world: Unreal's toolbar and Play-in-Editor,
Godot's scene tree and inspector, Terrain3D-style terrain tools, and an MMO gameplay layer (targeting, abilities,
quests, zones, XP) you test with one key. Everything it edits and plays runs on the engine's own C++ world module and
Carbon math (`Vector3`, `Matrix`). The look: IBM Plex Sans + Font Awesome icons rasterised at the screen's real
pixel density, a dark bevelled theme, every icon with a hover tooltip (name + what it does).

```bash
./build/bin/cmmo_editor                                       # content in ./content (levels/, models/, prefabs/)
./build/bin/cmmo_editor --content /Volumes/Xero/carbon_mmo/content
```

Start with **File > New Starter Zone** (a generated valley with foliage, a camp, a quest giver, wolves and boars, a
zone) and press **Play**.

| Panel | What it does |
|---|---|
| Menus | File (new, starter zone, open, save), Edit (undo, cut / copy / paste, duplicate, delete, preferences), Actor (place, group, unparent, snap to ground, hide, rename, prefab, focus), Terrain (create, every tool, regenerate, clear foliage), Play, View (view mode, grid, stats, camera speed), Window (every panel on / off, Reset Layout), Help (Controls, F1) |
| Toolbar | Save, Undo, Redo - Select / Move / Rotate / Scale (Q W E R), Local / World, Quick Add, Snap - **Play / Simulate / Pause / Stop** - Lit / Unlit / Wireframe, grid, stats, frame |
| Viewport | **Unreal navigation**: hold RMB + W A S D to fly (Q / E down / up, mouse looks, wheel = speed 1-8, Shift = 3x), LMB drag moves and turns, MMB drag pans, Alt+LMB / RMB / MMB orbit / dolly / pan, wheel dollies, F focuses. LMB click selects, RMB click opens the viewport menu (place actor here, paste here, focus, duplicate, snap to ground, group, prefab, delete). ImGuizmo handles, a view cube, a camera-speed button, stats. Drop actors, models and prefabs onto it |
| Scene | the hierarchy, Godot-style: icons per type, eye toggles, filter, drag onto another actor to parent (keeps it in place), right-click: rename, duplicate, add child, unparent, save as prefab, delete |
| Inspector | name, visibility, transform (X / Y / Z fields), the actor's settings (creature level, health, damage, quest text, zone levels, colours...) |
| Place Actors | Gameplay: Player Start, Creature Spawn, Trigger Box, Quest Giver. World: Terrain, Zone. Basic: Empty, Shape, Model. Lighting: Point Light, Sun |
| Terrain | **tools, not a fixed map** (in the spirit of Terrain3D for Godot): create flat or from noise (size, resolution); Raise, Lower, Smooth, Flatten, Ramp, Noise, Paint, Foliage, Erase Foliage; brush size, strength, falloff; 4 texture layers + an auto-shader (rock on slopes, snow up high); foliage kinds (tree, pine, bush, rock, grass) and density - never on cliffs; Generate (seed, height, feature size, detail; replace or add) |
| Content Browser | levels, glTF / glb models (e.g. Forge exports) and prefabs as tiles; double-click or drag into the viewport |
| World Settings | world name, sky, horizon, ambient, fog, gravity |
| Output | the log |
| Play (Alt+P) / Simulate / Stop (Esc) | third person, WoW controls: W/S move, A/D turn, Q/E strafe, Space jump, Shift run, right-drag turns, left-drag looks, wheel zooms; Tab targets, 1-4 abilities (Strike, Heroic Blow, Fireball, Mend), F talks. HUD: player and target frames, action bar with cooldowns, XP, minimap, quest tracker, nameplates, combat text, zone banner. Play runs on a copy of the level, so Stop always restores it |

Undo / redo (Ctrl+Z / Ctrl+Shift+Z, Cmd on the Mac) covers everything, including whole brush strokes. Ctrl+S saves,
Ctrl+C / X / V / D copy, cut, paste, duplicate, Ctrl+G groups, End snaps to the ground, H hides, F2 renames, F1 shows
every control. Every panel closes with its X and comes back from the Window menu. The window layout is remembered in `cmmo_editor_layout.ini`.

`cmmo_editor --selftest --screenshot out.png` drives the real editor (42 checks: RMB + W A S D / Q flies the camera without switching tools, wheel speed, copy / paste, snap, group, create terrain, a mouse drag sculpts,
paint, foliage, undo / redo, place, parent, prefab, glTF model, click-to-select, save / open, the starter zone, Play:
walk, F talks to the quest giver, Tab targets, 1 casts, Esc) and saves `out.png`, `out_editor.png`, `out_terrain.png`,
`out_flying.png`, `out_controls.png` and `out_play.png`; on Linux headless through EGL (Mesa), on macOS / Windows in a hidden window. `run_tests.py`
includes it.

Modules: `cpp/world/` (MODULE: world - scene, hierarchy, terrain, foliage, Play and the MMO layer, level files; no
graphics; `test_world`), `cpp/editor/` (MODULE: editor, editor.render, editor.theme, editor.gl),
`cpp/apps/cmmo_editor.cpp` (window + ImGui backends). UI: Dear ImGui 1.92.8 (docking, MIT), ImGuizmo (MIT).
Levels: nlohmann/json 3.11.3 (MIT). Models: cgltf 1.15 (MIT). Fonts in `third_party/fonts/`: IBM Plex Sans (OFL-1.1),
Font Awesome 6 Free solid (OFL-1.1), IconFontCppHeaders (zlib).

**Easiest build (Mac and Windows):** `python3 tools/build.py --open` picks an arm64 Python 3.10+, Apple's own
compiler tools (or Visual Studio), builds on /Volumes/Xero when it is mounted, runs the tests and opens the editor.
On failure it prints the first error and a toolchain diagnosis (`--doctor` prints only the diagnosis).

## Status

| Phase | What | Verified |
|---|---|---|
| 1 | C++ host embeds Python; `configure_render(cfg)` sets window size + background color on the C++ `RenderConfig`; C++ validates; per-frame `on_frame` callback; Carbon `Vector3` usable in both directions | Built and run on Linux with Carbon math compiled from source. Windowed GLFW backend compiles only on Mac/Windows here (untested on those yet) |
| 2 | Connection management, serialization, heartbeat/time sync as separate classes; server + 3 clients sync a Carbon `Vector3` | Passes in ~0.2 s on both codecs; clock sync within 0.03 ms against a server clock deliberately offset 1000 s |
| 3 | ECS + nav adapter; click → server moves entity via NavAdapter → broadcast to all clients | Passes with the kinematic backend; Destiny adapter verified against a stand-in that mirrors Destiny's exact signatures |
| — | CarbonIO transport | Module injection + full Phase 2 flow verified with stand-in modules; needs a Carbon Python build for the real sockets |

**Honest limits.** Blue, CarbonIO, Scheduler and Destiny need CCP's Python build and vcpkg
registry, and Blue's README still says some of its dependencies live in CCP's Perforce.
They ship Mac (`arm64-osx`) and Windows (`x64-windows`) presets only. This repo therefore
compiles Carbon's **math** directly and reaches the other modules through runtime adapters,
so everything runs today and switches to the real Carbon module when it's importable.

## Build (Mac and Windows)

Requirements: **CMake ≥ 3.24**, **git**, **Python 3.10–3.13 with headers** (the python.org
installer works on both), and a C++17 compiler: **Xcode Command Line Tools** on macOS
(`xcode-select --install`) or **Visual Studio 2022** with "Desktop development with C++" on Windows.
CMake fetches DirectXMath, Carbon math, pybind11 and GLFW (pinned) at configure time.

macOS:
```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/bin/cmmo_host --renderer glfw        # opens the window configured by Python
python3 run_tests.py
```

Windows (Developer PowerShell or plain PowerShell):
```powershell
cmake -S . -B build
cmake --build build --config Release
.\build\bin\cmmo_host.exe --renderer glfw
python run_tests.py
```

**One Python for build and run.** The `cmmo_math` extension only imports into the Python it was built for.
`run_tests.py` uses that Python automatically (CMake writes it to `build/python_exe.txt`). On macOS, `python3`
in the shell is often Apple's 3.9 while CMake picks Homebrew's newer one: run things by hand with
`$(cat build/python_exe.txt)`, or choose one with `-DPython3_EXECUTABLE=$(command -v python3.13)`.
Needs C++17 and pybind11 3.1 (fetched; 2.13.x does not compile against the macOS 27 SDK).

Options: `-DCMMO_WITH_GLFW=OFF` (headless only), `-DCMMO_EDITOR_PYTHON=OFF` (an editor with no Python dependency), `-DCARBON_MATH_SOURCE_DIR=<path>` (use a
local carbonengine/math checkout), `-DPython3_EXECUTABLE=<path>` (pick a Python).

### What gets compiled

| Target | Sources | Needed for |
|---|---|---|
| `CarbonMath` (static) | carbonengine/math `src/*.cpp` + DirectXMath | everything C++ |
| `cmmo_math` (Python ext) | `cpp/math/` | Carbon `Vector3` in Python (Phases 2–3 fall back to pure Python without it) |
| `cmmo_render` (static) | `cpp/render/` (+ GLFW, OpenGL when enabled) | Phase 1 |
| `cmmo_host` (exe) | `cpp/script_host/`, `cpp/apps/` + pybind11 embed | Phase 1 |
| `cmmo_world` (static) + `test_world` | `cpp/world/` + nlohmann/json | the editor and Play |
| `cmmo_editor` (exe) | `cpp/editor/`, `cpp/apps/cmmo_editor.cpp` + Dear ImGui (docking) + ImGuizmo + cgltf + fonts + GLFW (Mac / Windows) or EGL (Linux, headless) | the engine editor |

Non-Windows builds use `third_party/sal/sal.h`, an empty-macro stub for the SAL annotations
DirectXMath expects (MSVC provides the real one).

## Running the tests

```bash
python run_tests.py                     # all phases, each capped at 60 s
ctest --test-dir build -C Release       # same suite through CTest
```

**Phase 2 networking test** (local server + 3 clients syncing player positions):
```bash
python tests/test_phase2_net.py                      # binary codec, stdlib sockets
python tests/test_phase2_net.py --codec json         # swap the codec
python tests/test_phase2_net.py --transport carbonio # inside a Carbon Python build
```
It checks the handshake, that every client mirrors every player's `Vector3`, RTT and server
clock estimate, that a live update reaches everyone, and that a disconnect is broadcast.

**Phase 3**: `python tests/test_phase3_click_to_move.py [--nav destiny|kinematic]`

**Two machines** (e.g. Mac ↔ PC on the same network):
```bash
python tools/netdemo.py server --host 0.0.0.0 --port 7777
python tools/netdemo.py client --host <server-ip> --name mac --click 25,0,10
```

## Swapping modules

Every replaceable unit starts with a `// MODULE: name` (C++) or `# MODULE: name` (Python)
comment. `grep -rn "MODULE:" cpp python scripts` lists them.

| To replace | Implement | Register in |
|---|---|---|
| Renderer (Trinity, Metal, Vulkan…) | `cmmo::IRenderer` | `cpp/render/RendererFactory.cpp` |
| Script host (Blue) | `cmmo::ScriptHost`, keep exposing `cmmo_engine` | `cpp/apps/cmmo_host.cpp` |
| Network transport (CarbonIO, UDP, ENet…) | `cmmo.net.transport.Transport` | `create_transport()` |
| Wire format | `cmmo.net.serialization.MessageCodec` | `CODECS` |
| Pathfinding (Destiny, navmesh) | `cmmo.nav.NavAdapter` | `create_nav()` |
| Vector math | `cpp/math/CarbonMathBindings.cpp` | — |

Runtime switches: `CMMO_TRANSPORT=std|carbonio|auto`, `CMMO_NAV=auto|destiny|kinematic`,
`CMMO_MATH=auto|carbon|python`, `CMMO_BUILD_DIR=<build folder>`.

Rules that keep the layers detachable: `cmmo/` never imports `cmmo_game/`; the net layer
replicates opaque bytes per (entity, component) and never interprets them; ECS components
are plain dataclasses with no Destiny/Carbon types; adapters take and return
`mathbridge.Vector3`.

## Full Carbon stack

1. Clone `carbonengine/core`, `scheduler`, `io`, `blue`, `math`, `destiny`. Each builds with
   its own presets: `cmake --list-presets`, then `cmake --preset <arm64-osx|x64-windows…>` and
   `cmake --build <dir>`. They resolve dependencies (including CCP's Python 3.12 port) from
   `github.com/carbonengine/vcpkg-registry`.
2. Run this repo's Python layers under that interpreter with the built Carbon Python packages
   on `PYTHONPATH`.
3. `CMMO_TRANSPORT=carbonio CMMO_NAV=destiny python run_tests.py --skip-host`.
   CarbonIO is installed exactly as its README describes: `_carbonsocket` / `carbonselect`
   are injected into `sys.modules` as `_socket` / `select`.

Destiny is a fixed-tick open-space simulation: "pathfinding" there is steering
(`GotoPoint`, `FollowBall`, `Orbit`), not navmesh routing around obstacles. Ground-based
worlds should add a navmesh `NavAdapter`; nothing else changes.

## Licenses

This repo: MIT. Carbon modules: MIT (math, core, scheduler, blue, destiny) and PSF-2.0 (io).
DirectXMath: MIT. pybind11: BSD-3. GLFW: zlib.
