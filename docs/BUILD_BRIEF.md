# LOKI - build brief (the owner's direction)

Rewritten 2026-10-24 to replace the "living AI company" brief, which no longer describes LOKI (it is in git
history). Rules for working on the code are in `AGENTS.md`; where things stand is `HANDOFF.md`.

## What LOKI is

A lightweight, modular 3D creation engine for one artist on two machines:

| Part | What it is | Where |
| --- | --- | --- |
| **Forge** | Maya-style 3D: modeling, sculpting (ZBrush-for-iPad feel), UV, retopology, baking, materials (Material Maker), animation - and a **Level** workspace in the spirit of Unreal's editor | `app/ui/forge*.js`, `native/sculpt`, `docs/FORGE_*.md` |
| **Render Studio** | renders, including the AI Renderer (ComfyUI pipelines on the PC's RTX 3070 Ti) | `app/ui/render_studio.js`, `docs/AI_RENDERER.md` |
| **Home** | the preview hub: renders, models, projects and the farm's jobs | `app/ui/` |
| **Farm** | Mac + PC (+ more later) working as one: jobs go to the machine that fits | `engine/workers.py`, `engine/peers.py` |
| **Local AI** | local models + chat; fast offline models on the Mac (colibri, TurboFieldfare) | `engine/model_setup.py` |
| **Godot tab** | the owner's games in the real Godot editor, live-linked to LOKI's agents | `docs/LIVE_GODOT.md` |
| **Content** | LOKI's agents turn what is built into ads and social posts | `skills/marketing/` |

Separate, in the same repo: **Carbon MMO Foundation** (`native/carbon_mmo/`), a code-driven MMO engine base on
CCP's open-source Carbon. It stays its own module until the owner decides to wire it in.

Gone for good: LOKI World, the MMO lobby, Spaces, the small-business agents. LOKI gets a new name later.

## Priorities, in order

1. **Forge is a professional tool.** Almost 1:1 with Maya where Maya has it (menus, marking menus, hotbox,
   hotkeys, Outliner, Channel Box, snapping, history). Every panel adjustable and closable, nothing overlapping.
2. **Forge as an editor.** The Level workspace: Place Actors, a Content Browser (models/ in the workspace),
   Details with per-actor scripts, Play in Editor / Simulate / Stop that restores the scene exactly, and saved
   levels. Engine side: `app/ui/forge_level_core.js` (tested in node). Then: prefabs, a node graph for logic
   (Forge already has a node graph), and export to Godot / the Carbon MMO server.
3. **Render Studio + the farm do real work:** AI renders on the PC, jobs queued from the Mac, results on Home.
4. **Fast and offline.** Starts quickly, runs without the internet, local models first, nothing paid by surprise.
5. **Content making** from Forge / Render Studio output.

## How it is built

- **Modular:** every capability is a module that registers itself and can be removed without breaking the rest
  (AGENTS.md > Architecture rules).
- **Lightweight:** no framework where 200 lines will do; vendor small permissive code; optional dependencies
  are imported where they are used.
- **Native where it pays:** C++ (CMake) for geometry, sculpt, bake, UV and anything tied to C++ ecosystems
  (Carbon, DCC SDKs); Rust (cargo) for standalone services. Candidates once profiling shows the need:
  the baker and UV unfold (C++ -> wasm, like `native/sculpt`), the farm worker as one small Rust binary.
  Always a narrow boundary and a fallback.
- **Copy before inventing:** prefer adapting proven open-source code with compatible licences - the three.js
  editor (Forge uses three.js), the PlayCanvas editor frontend, Godot, Material Maker, SculptGL, UVgami.

## Hard rules

1. Inspect first: the checkout and the tests are the truth, docs are not proof.
2. Never lose work: no destructive git; check twice before moving or deleting files on the owner's machines.
3. Verify every claim and say where it was verified (Mac, PC, cloud).
4. Small steps, each with a test; a test run takes at most 1 minute.
5. Free and local first; never buy or provision anything paid.
6. Safety stays: policy engine, approvals, signed peer link, secrets out of git.
7. The Mac's drive is nearly full: big things go on `/Volumes/Xero`.
