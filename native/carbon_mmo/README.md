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

## The engine editor (`cmmo_editor`)

A native C++ level editor for a World of Warcraft-style world, in the spirit of Unreal's editor. Everything it edits
and plays runs on the engine's own C++ world module and Carbon math (`Vector3`, `Matrix`).

```bash
./build/bin/cmmo_editor                 # macOS / Windows: opens the editor (levels are saved in ./levels)
./build/bin/cmmo_editor --levels /Volumes/Xero/carbon_mmo/levels
```

| Panel | What it does |
|---|---|
| Viewport | Maya navigation: Alt+LMB orbit, Alt+MMB pan, Alt+RMB / wheel zoom, F frame. Click selects. Q / W / E / R: select, move, rotate, scale handles (ImGuizmo), Snap |
| Place Actors | World: Player Start, Creature Spawn, Terrain. Basic: Empty, Shape (cube, sphere, cylinder, cone, plane), Trigger Box. Lights: Point Light, Sun |
| Terrain | sculpt with the mouse: Raise, Lower, Smooth, Flatten, Paint (grass, dirt, rock, snow, sand, any colour); radius, strength |
| Outliner / Details | every actor; name, visibility, transform, the actor's settings (colours, counts, ranges...) |
| Levels / Output | save / open `*.level.json`; the log |
| Play (Alt+P) / Simulate / Stop (Esc) | third person, WoW controls: W/S move, A/D turn, Q/E strafe, Space jumps, Shift runs, right-drag turns you, left-drag looks around, wheel zooms. Creatures wander, attack when you come close, leash home. Play runs on a copy of the level, so Stop always restores it |

Undo / redo (Ctrl+Z / Ctrl+Shift+Z, Cmd on the Mac) covers placing, deleting, duplicating (Ctrl+D), transforms,
settings and whole brush strokes. Ctrl+S saves. The window layout is remembered in `cmmo_editor_layout.ini`.

`cmmo_editor --selftest --screenshot out.png` drives the real editor (a mouse drag sculpts, placing, undo / redo,
click-to-select, save / open, Play with W and right-drag, Esc) and saves `out.png` + `out_play.png`; on Linux it
runs headless through EGL (Mesa), on macOS / Windows in a hidden window. `run_tests.py` includes it.

Modules: `cpp/world/` (MODULE: world - scene, terrain, Play, level files; no graphics; `test_world`),
`cpp/editor/` (MODULE: editor, editor.render, editor.gl), `cpp/apps/cmmo_editor.cpp` (window + ImGui backends).
UI: Dear ImGui 1.92.8 (docking, MIT), ImGuizmo (MIT). Levels: nlohmann/json 3.11.3 (MIT).

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

Options: `-DCMMO_WITH_GLFW=OFF` (headless only), `-DCARBON_MATH_SOURCE_DIR=<path>` (use a
local carbonengine/math checkout), `-DPython3_EXECUTABLE=<path>` (pick a Python).

### What gets compiled

| Target | Sources | Needed for |
|---|---|---|
| `CarbonMath` (static) | carbonengine/math `src/*.cpp` + DirectXMath | everything C++ |
| `cmmo_math` (Python ext) | `cpp/math/` | Carbon `Vector3` in Python (Phases 2–3 fall back to pure Python without it) |
| `cmmo_render` (static) | `cpp/render/` (+ GLFW, OpenGL when enabled) | Phase 1 |
| `cmmo_host` (exe) | `cpp/script_host/`, `cpp/apps/` + pybind11 embed | Phase 1 |
| `cmmo_world` (static) + `test_world` | `cpp/world/` + nlohmann/json | the editor and Play |
| `cmmo_editor` (exe) | `cpp/editor/`, `cpp/apps/cmmo_editor.cpp` + Dear ImGui (docking) + ImGuizmo + GLFW (Mac / Windows) or EGL (Linux, headless) | the engine editor |

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
