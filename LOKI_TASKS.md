# LOKI_TASKS.md - work for LOKI's own driver

Each machine's launcher does its own setup on first start (no one needs to do these by hand):

- [x] **Both machines:** build the driver `lokid` (Rust). The PC uses its Rust in `~/.cargo`; a machine without Rust
  gets it installed into `harness_data/toolchain` (the external drive on the Mac). Build cache: `harness_data/build`.
- [x] **Both machines:** stop the previous LOKI's engine, start `lokid`, check every free model (`harness_data/home/probe.json`).
- [x] **PC:** first-light job - a Blender campfire built and rendered from scratch (`renders/campfire.png`, `scenes/campfire.blend`).

Next, in order (owner's direction 2026-10-29: art, production, creation; long runs; free models):

1. MCP client in the driver, then a Blender MCP server from `tools/blender/loki_blender_core.py`.
2. ComfyUI server on the PC (`tools/comfy/graphs/`): images, TRELLIS.2 / Pixal3D, Hunyuan3D-2.1, Wan video.
3. Turnaround sheets (concept -> front/side/back) and the vision "look" check of every image.
4. Mac hands heavy jobs to the PC; Mac and PC see each other's jobs and results.
5. Playbooks from `playbooks/` read per job; every picture prompt waits in For you for the owner's OK.
