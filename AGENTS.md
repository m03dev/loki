# AGENTS.md - how to work on LOKI

For every agent: Claude, Codex, LOKI's own agents. Short on purpose: it is read at the start of every
session. The owner's direction is `docs/BUILD_BRIEF.md`; where the work stands is `HANDOFF.md`; requests that
need a real machine are in `LOKI_TASKS.md`. Rewritten 2026-10-24 for the current scope (owner: "rewrite them
better for us ... modular and lightweight, maybe rust or c++, everything's on the table").

## What LOKI is now

A lightweight, modular **3D creation engine** for one artist's Mac + PC: **Forge** (Maya-style modeling, sculpt,
UV, bake, materials, animation, and a Level editor in the spirit of Unreal), **Render Studio** (AI renders via
ComfyUI on the PC), a **worker farm** (Mac + PC), **local AI** (models + chat), the **Godot tab**, and content
making (ads, social posts) from what is built. Not any more: the "AI company" app, LOKI World / the MMO, Spaces.
The separate MMO engine base lives in `native/carbon_mmo/` (its own README and rules).

## Commands

| Do | Command (Windows: `harness_data\.venv\Scripts\python.exe` instead of `python`) |
| --- | --- |
| set up | `./setup.sh` (macOS) / `setup.bat` (Windows) |
| run | `python app/loki_app.py` |
| quick health | `python app/loki_app.py --self-test` |
| check before work | `python tools/ship.py --check` (60 s budget) - one suite: `--only test_forge_bake_ui` |
| JS logic tests | `node tests/js/test_<name>.js` |
| publish | `python tools/ship.py -m "what changed, how it was checked"` |
| native code | `cmake -S native/<x> -B <build dir>` / `cargo build --manifest-path native/<x>/Cargo.toml` |

## Architecture rules (modular, lightweight)

1. **One capability, one module.** Its own file or folder (`engine/<name>.py`, `app/ui/forge_<name>.js`,
   `native/<name>/`), one entry point, its own test, a docs section. It **registers itself** - commands in
   `FORGE_PRO_CMDS`, routes in its `*_api.py`, workspaces in `FORGE_WORKSPACES` - instead of core files
   hard-coding it. Deleting the module must leave LOKI starting and every other suite green.
2. **Talk through seams.** Cross-module calls are guarded (`typeof X === "function"` in the UI, lazy `import`
   inside the function in Python). No module reaches into another's private state.
3. **Lightweight by default.** No new runtime dependency without a reason in the commit and a row in
   `docs/THIRD_PARTY.md`; vendor small MIT/BSD code instead of pulling frameworks; optional dependencies are
   imported where they are used, so the app starts without them. No polling faster than the UI needs.
4. **Pick the language by the job.** Python = engine and orchestration; plain JS + vendored three.js = the
   window (classic `defer` scripts, no build step). Go **native** only for measured hot paths or standalone
   tools: **C++17 + CMake** when the ecosystem is C++ (geometry, sculpt, bake, Carbon, DCC SDKs), **Rust +
   cargo** for new standalone services and CLIs (workers, file watchers, relays). A native module must have
   a narrow boundary (C ABI, wasm, pybind11, or a subprocess speaking JSON), a fallback or a clear "not
   available here", build on macOS arm64 and Windows x64, and a README with its exact build commands. Never
   rewrite working code just to change its language - profile first, keep the old path until the new one
   wins in a test.
5. **Generated files are generated.** Edit the source and re-run the tool (e.g. `app/ui/forge_maya_layout.js`
   comes from `python tools/forge_maya/gen_layout.py`).

## Product rules (the owner's, standing)

- **Forge works like Maya** (menus, marking menus, hotbox, hotkeys, Outliner, Channel Box). Every hotkey lives
  once in `FORGE_KEY_DEFAULTS` (`app/ui/forge_keys.js`); no key is used twice.
- **UI:** icons with hover tooltips (name + what it does) instead of words; sizes in %; nothing ever overlaps,
  always padding; every panel adjustable and closable; no floating widgets on the Modeling screen.
- **Keep what is useful, remove bloat** (2026-10-21). Never delete a check or feature just to make a test pass.
- Both machines, one version: nothing for one OS without the other (`pathlib`, `sys.platform` branches with
  both sides, no shell strings - `engine/safe_exec.py`). `.bat/.cmd/.ps1` CRLF, `.sh` LF and `bash -n` clean.

## Tests

- **A test run takes at most 1 minute** (owner's rule). ship.py enforces the budget; `--full` only overnight.
- Every change adds or updates a test. UI logic: a node test in `tests/js/`; UI wiring: the Playwright suite of
  that area (it skips cleanly without a browser). Register new suites in `SUITES` in `tools/ship.py`.
- Say exactly what you verified and where: "Mac", "PC", or "cloud" (Linux, headless) - never "should work".

## Git and shipping

- `master` is what both machines run: they update from GitHub at start, and an update is kept only if
  `--self-test` passes and the window reports ready. **Only `tools/ship.py` writes `master`** (test, commit,
  rebase, re-test, push, tell the other machine). Never bypass it; never `push --force` or `reset --hard`.
- **Every agent ships to `master` with `tools/ship.py` - cloud sessions too.** No `agent/*` side branches (owner
  2026-10-27: "why do you keep pushing to branch and confusing my system ... why do they keep not updating"). Machines
  only ever install `master`; a branch is never seen by them, and branches nobody merged left fixes stranded for days.
  A cloud session without LOKI's venv installs what the suites need first:
  `pip install -r engine/requirements.txt` (add `--break-system-packages` on a system Python), then ship.py as usual.
  If ship.py really cannot run, stop and tell the owner what is blocking it - do not leave a branch behind.
- Commit messages say what changed and how it was checked. Update `HANDOFF.md` (its "Now" section, in place).

## Boundaries

- The repo is **public, AGPL-3.0**. Never commit keys, tokens, personal files or anything in `harness_data/`.
  Only AGPL-compatible code (MIT, BSD, Apache-2.0, ISC, MPL-2.0, LGPL, GPL-3.0, AGPL-3.0), licence kept next to
  it and a row in `docs/THIRD_PARTY.md`. Never proprietary or non-commercial code.
- `contrib/` is vendored upstream code: update it, don't hand-edit it.
- Godot lives in exactly three places: the game capability (`engine/godot_tools.py`, `engine/godot_assets.py`),
  the live Godot link (the Godot tab, docs/LIVE_GODOT.md), and the LOKI Studio plugin in
  `studio/godot_plugin/addons/loki_studio/`. No `project.godot`, `.gd`, `.tscn`, `.uid` or `addons/` anywhere
  else. The owner's games live in `~/LOKI Projects/<name>`.
- Safety stays: `engine/policy.py`, approvals for risky actions, the signed peer link. Ask the owner before
  anything irreversible or that costs money (say so in the chat and wait).

## Machine agents (LOKI's own agents on the Mac and the PC)

- Start every session: pull, read this file, the top of `HANDOFF.md`, then your open requests in `LOKI_TASKS.md`
  (oldest first unless marked DO FIRST). Answer under the request, report at the top of Reports, tick it, ship.
- **Mac mini:** checkout `~/Loki`. Its drive is nearly full: builds, downloads, caches and models go on the
  external drive **`/Volumes/Xero`** (stop and ask if it isn't mounted).
- **PC:** `D:\loki` (moved off a full C: on 2026-10-21; `C:\Users\macul\Documents\loki` no longer exists), RTX 3070 Ti, on 24/7 - the farm's GPU worker (ComfyUI, training).
- **No visible terminal windows** on the owner's screen: run hidden (Windows `Start-Process -WindowStyle
  Hidden`, Mac never `open -a Terminal`), close what you opened.
- Never open the owner's Godot projects in Godot_v4.8-beta1_mono / Godot_mono 4.8 (it rewrites them).
- Don't write LOKI's own self-improvement tasks (docs/EVOLVE.md) yourself unless the owner says so; unblock them.

## Where things are

| Folder | What |
| --- | --- |
| `engine/` | Python core: agent loop `loki.py`, HTTP API `loki_bridge.py` + `*_api.py`, workers, peers, updater |
| `app/` | the window (`loki_app.py`, pywebview) and its UI `app/ui/` (Forge = `forge*.js`, three.js in `vendor/`) |
| `native/` | C++ / Rust modules (`sculpt`, `optcuts`, `carbon_mmo`), each with its own README |
| `studio/` | LOKI Studio and its Godot plugin |
| `tools/` | `ship.py`, generators, setup, packaging |
| `tests/` | Python suites (`tools/ship.py --check`) and `tests/js/` node tests |
| `docs/` | `BUILD_BRIEF.md` (direction), `ARCHITECTURE.md`, `FORGE_*.md`, `operations/` (logs, archive) |
