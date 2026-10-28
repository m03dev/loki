# AGENTS.md - how to work on LOKI

For every agent: Claude, Codex, LOKI's own agents. Read at the start of every session. Where the work stands is
`HANDOFF.md`; requests for LOKI's own agents are in `LOKI_TASKS.md`.

## The rules

These are the owner's rules, as the owner gave them. **Nothing else is a rule** - no agent adds rules of its own here,
in other docs or in prompts (owner 2026-10-27: "remove everything that you wrote in the rules because that is not what
I said").

1. **Ship to `master`.** The machines only update from `master`. Never push side branches - they confuse the
   machines (2026-10-27).
2. **Fix the root cause**, so the same problem doesn't come back (2026-10-27).
3. **Proof, not claims.** Show real outputs (images, 3D models, renders, videos) made by LOKI itself, saved in its
   folders (2026-10-25).
4. **A test run takes at most 1 minute** (2026-10-17).
5. **Keep what is useful, remove bloat** (2026-10-21).
6. **Mac and Windows never drift**: every change is for both (2026-10-17).
7. **The Mac is not the powerhouse.** Heavy work goes to the PC; keep Mac memory use light - a heavy local model next to
   Blender and agents once crashed it (2026-10-26). Big files (installs, models, caches) go on the external drive
   (Xero; LokiSSD while Xero isn't connected), never the Mac's internal drive (2026-10-26).
8. **Agents may do everything, but ask first and say what they're going to do** (2026-10-25). Every agent picture
   waits for the owner's OK on its prompt, and every hand-off for the owner's check-off (2026-10-27).
9. **No screen control or screenshots** on the owner's computers (2026-10-24).
10. **Forge works like Maya**; no hotkey used twice (2026-10-19, 2026-10-22).
11. **UI:** icons with hover tooltips (name + what it does); sizes in %; nothing ever overlaps, always padding; no
    repeated icons (2026-10-17, 2026-10-21).
12. **Open source, AGPL-3.0**; GPL/AGPL code may be built in; prefer proven open-source code over reinventing
    (2026-10-17, 2026-10-25).
13. LOKI is not a Godot project and must never look like one (2026-10-17).
14. No CI workflow (2026-10-25). No Ziva - work goes to LOKI via `LOKI_TASKS.md` (2026-10-25).

## What LOKI is now

A 3D creation engine for one artist's Mac + PC: **Forge** (Maya-style modeling, sculpt, UV, bake, animation, Level),
**Lab** (renders via ComfyUI on the PC, the farm), **local AI** (models + chat), the **Engine tab** (Godot, Carbon),
and content making from what is built. The art pipeline: concept art -> Technical Artist (turnarounds) -> 3D model ->
render.

## Commands

| Do | Command (Windows: `harness_data\.venv\Scripts\python.exe` instead of `python`) |
| --- | --- |
| set up | `./setup.sh` (macOS) / `setup.bat` (Windows) |
| run | `python app/loki_app.py` |
| quick health | `python app/loki_app.py --self-test` |
| tests | `python tools/ship.py --check` (1-minute budget) - one suite: `--only test_forge_bake_ui` |
| publish | `python tools/ship.py -m "what changed, how it was checked"` (tests, commit, push to master) |

## The machines

- **Mac mini:** checkout `/Volumes/LokiSSD/loki`; Home library `~/LOKI Projects/Home`.
- **PC:** `D:\loki`, RTX 3070 Ti, on 24/7 - ComfyUI, the farm's GPU worker. On a different network from the Mac:
  they link through a Cloudflare tunnel (engine/tunnel_link.py), the relay as fallback.
- Updates: from GitHub `master`, or straight from the other machine when GitHub can't be reached
  (engine/peer_update.py).

## Where things are

| Folder | What |
| --- | --- |
| `engine/` | Python core: agent loop `loki.py`, HTTP API `loki_bridge.py` + `*_api.py`, workers, peers, updater |
| `app/` | the window (`loki_app.py`, pywebview) and its UI `app/ui/` (Forge = `forge*.js`) |
| `native/` | C++ / Rust modules (`sculpt`, `optcuts`, `carbon_mmo`), each with its own README |
| `studio/` | LOKI Studio |
| `tools/` | `ship.py`, generators, setup, packaging |
| `tests/` | Python suites and `tests/js/` node tests |
| `docs/` | `ARCHITECTURE.md`, `FORGE_*.md`, `operations/` |
