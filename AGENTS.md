# AGENTS.md - how to work on LOKI

For every agent: Claude, Codex, LOKI's own driver. Read at the start of every session. Requests for LOKI's own
driver are in `LOKI_TASKS.md`. The previous LOKI (Python, 246 modules) is kept as the git tag `legacy-v1`
for reference: `git show legacy-v1:engine/<file>`.

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
15. Free routes only - no paid model providers (2026-10-29).

## What LOKI is now (rebuilt 2026-10-29)

A standalone art / production / creation app for the owner's Mac + PC, built like Ziva: one focus, one agent loop,
a few sharp tools, the work checked by the driver rather than trusted.

- **Driver** (`crates/`, Rust): `lokid`, a background daemon. One goal -> a checklist -> one tool call per turn ->
  each task re-checked by the driver -> hours of work, crash-safe, resting when free models are capped.
- **Window** (`app/ui/index.html`, served by `lokid`): jobs, For you approvals, results as thumbnails, models.
- **Launcher** (`app/loki_app.py`, stdlib Python): builds and starts `lokid`, opens the window, keeps the machine on
  `master` (update only after the new driver builds and answers; otherwise roll back).
- **Art tools** (`tools/`): the Blender job runner and ComfyUI graphs carried over from legacy-v1, next to become MCP
  servers. **Playbooks** (`playbooks/`): the art-pipeline roles.

## Commands

| Do | Command |
| --- | --- |
| set up | `./setup.sh` (macOS) / `setup.bat` (Windows) |
| run | `Loki.cmd` (Windows) / Loki.app, or `python app/loki_app.py` |
| quick health | `python app/loki_app.py --self-test` |
| tests | `cargo test -q` (well under 1 minute) |
| which free models answer | `lokid probe`, or the Models icon in the window |
| update this machine now | the Update icon, or `python app/loki_app.py --update-now` |

## The machines

- **Mac mini:** checkout `/Volumes/LokiSSD/loki` (external drive): build cache and Rust live in its `harness_data/`.
- **PC:** `D:\loki`, RTX 3070 Ti, on 24/7 - ComfyUI, Blender (`D:\Blender`), the heavy work.
- Runtime data: `<checkout>/harness_data/home` (runs, results, logs: `launcher.log`, `lokid.log`, `build.log`).
- Keys: `<checkout>/harness_data/.env` (`NVIDIA_API_KEY`, optional `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`).
