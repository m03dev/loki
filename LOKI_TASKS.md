# LOKI_TASKS.md - work for LOKI's own driver

Each machine's launcher does its own setup on first start (no one needs to do these by hand):

- [x] **Both machines:** build the driver `lokid` (Rust). The PC uses its Rust in `~/.cargo`; a machine without Rust
  gets it installed into `harness_data/toolchain` (the external drive on the Mac). Build cache: `harness_data/build`.
- [x] **Both machines:** stop the previous LOKI's engine, start `lokid`, check every free model (`harness_data/home/probe.json`).
- [x] **PC:** first-light job - a Blender campfire built and rendered from scratch (`renders/campfire.png`, `scenes/campfire.blend`).

Done 2026-10-29 (owner: "clean look like Ziva", "modular like ZBrush", "drag and drop"):

- [x] Window rebuilt: Ziva-style chat (tool cards, inline images, Agent/Hard modes, model picker, context meter) in the
  glass look; every panel docks left/right/bottom by dragging, resizes, folds, closes, comes back with Space; layout
  saved per machine. Drop or paste files into the chat; drag Library images in as references.
- [x] Chat steers running jobs; For you prompt approval with editing; Library (paged); local models list/remove;
  `<home>/inbox` takes jobs and messages as JSON files.
- [x] Driver pauses and asks when a model makes no progress for 16 turns.

Done 2026-10-30 (owner: "old loki ui and features are wayyyyyy superior" - checklist in the chat, For you as a
notification, simple approvals, interview, abliterated models, system scan, theme presets):

- [x] One chat with the plan inside it; a slim rail + one drawer (Jobs, Library, Settings) that swaps sides and resizes;
  For you is a bell with a badge, toast and desktop notification.
- [x] Approvals read in plain words (what it does, risk, anything outside the job folder; the command behind a toggle);
  low-risk commands inside the job folder no longer ask; an approved command is not asked again in that job.
  Risk patterns: OpenHands' PatternSecurityAnalyzer via the previous LOKI's command_risk.py.
- [x] Interview before work (Every job / Big jobs / Never in Settings), templates from the previous LOKI's interview.py.
- [x] Settings: theme presets (Glass, Midnight, Ember, Forest, Mono, Light) + own accent colour, sizes; system scan
  (hardware, tools, advice) with model picks that fit this machine - standard, abliterated, fast - and one-click
  download / remove (catalog from the previous LOKI's model_setup.py).

Done 2026-10-30 (owner: "have you given it real errors to check from, not just things it makes up?"):

- [x] Real checks: `blend:` (LOKI's scene inspector, tools/blender/inspect_scene.py - floating parts, nothing in frame,
  no camera, missing materials) and `look:` (a free vision model scores the render against the brief).
- [x] Playbooks read per job (playbooks/, new blender-scripting written from real failures) and a lessons notebook
  (<home>/lessons.md, `learn` tool) so a fixed error becomes a rule for every later job.
- [x] One title bar (frameless window, own minimise / maximise / close, resize edges); a real cog; measured tok/s.

Done 2026-10-30 (owner: "make sure the mac and windows are synced", "modular as before", drag library into chat):

- [x] tools/blender/loki_bpy.py - Blender helpers every job gets in scripts/: parts in metres standing on their bottom
  centre, place_on / place_beside / place_inside / center_on by measured bounds, hinge on a real edge, coins, planks,
  frame() camera from the scene's bounds, three-point lights(), finish() saves + renders with the right engine.
- [x] The window shows the real build (version + commit + time) and says "Updated to ..." after an update.
- [x] Two docks (left + right) at once; layout presets (Focus, Classic, Studio, Gallery, Tuning); drag a panel's title
  to the other side; Library pictures drag into the chat as references.

Done 2026-10-30 (owner: "are they helping each other?", "folders not yet synced"):

- [x] Mac <-> PC link back, in Rust inside `lokid` (crates/lokid/src/link.rs): each machine serves a signed peer API on
  127.0.0.1:7718 through a free Cloudflare quick tunnel and finds the other through a private ntfy topic made from
  `LOKI_PEER_SECRET` (same pairing as the previous LOKI - no new setup). Every peer request is HMAC-signed.
- [x] The other machine's jobs show in Jobs with its name; its questions ring the bell here and are answered here;
  "Run on" in the composer starts a job on the other machine (references are copied over).
- [x] Library mirror: every picture the other machine makes is copied into `<home>/mirror/<machine>/` every 2 minutes
  and shows in the Library with the machine's name; deleted there = deleted here.

Done 2026-10-30 (owner: "blender results are shit", "floating lids ... we need to completely rework this"):

- [x] Kits: whole objects built and checked from four sides instead of boxes placed by guessed numbers. First kit:
  `chest()` - open-top body, barrel lid on two real hinges at the back, iron bands, lock, coins on a gold bed.
- [x] Real surfaces and light: `pbr()` Poly Haven scans (CC0, cached in <home>/assets, credited in renders/CREDITS.txt),
  `hdri()` studio light in lights(); flat colours only when offline.
- [x] Every finish() renders a four-view sheet (front, right, back, above); the `look:` check scores the sheet.

Next, in order (owner 2026-10-30: rework the 3D):

0. More kits, each proven with a four-view render before it ships: crate, barrel, door with frame, table + chairs,
   bookshelf, lantern, campfire, tree, rock cluster, sword/shield. Then image-to-3D on the PC through ComfyUI
   (Hunyuan3D-2 quantized first, TripoSR as the fast option) for anything no kit covers.

Then (owner's direction 2026-10-29: art, production, creation; long runs; free models;
owner's picks: library + Mac/PC mirror, For you prompt approval, Lab GPU queue + ComfyUI, Mac<->PC link + local
models; drive real Maya/Blender rather than rebuilding Forge; then ads & social and the phone app):

1. MCP client in the driver, then a Blender MCP server from `tools/blender/loki_blender_core.py`.
2. ComfyUI server on the PC (`tools/comfy/graphs/`): images, TRELLIS.2 / Pixal3D, Hunyuan3D-2.1, Wan video.
3. Turnaround sheets (concept -> front/side/back) and the vision "look" check of every image.
4. Mac hands heavy jobs to the PC; Mac and PC see each other's jobs and results.
5. Playbooks from `playbooks/` read per job; every picture prompt waits in For you for the owner's OK.
