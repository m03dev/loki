# Studio - the render farm manager

The **Studio** tab (was "Render"; mode id `render`) has two views:

- **Farm** (`app/ui/studio_farm.js`, `engine/render_farm.py`) - a Deadline / Eclipse-style Monitor:
  - **Workers** are GPU render nodes, one ComfyUI each: the Studio's saved ComfyUI, every linked LOKI machine on
    port 8188, and any address added by hand. Probed every 5 s (GPU, VRAM free/total, queue). Each has pools
    (comma separated, default `gpu`), can be disabled, and keeps done / failed counts.
  - **Jobs** wrap an AI Renderer job whose passes are uploaded (render them in the Render view, then **Submit**).
    Priority 0-100, pool, "waits for" another job, max errors (default 3). Suspend, resume, requeue, cancel,
    delete. The scheduler (every 2 s) gives the best queued job (priority, then age) to the best idle worker
    (online, enabled, in the pool, not blacklisted, most free VRAM, best record) and starts it there
    (`ai_renderer.start(url=...)`). A failure is requeued as a fresh attempt on another worker; a worker that
    fails a job twice is blacklisted for that job.
  - **Farm doctor**: every failure is read offline (rule based, no model) into a cause and a fix - out of VRAM,
    worker unreachable, missing ComfyUI node or model, failed preflight, no passes.
  - **ETA** from the farm's own history (seconds per frame per workflow and worker); **History** keeps the last
    500 finished jobs. State: `<data>/farm/farm.json`.
- **Render** - the Render Studio as before (`app/ui/render_studio.js`, docs/AI_RENDERER.md).

API: `GET /farm/status`, `POST /farm/submit`, `/farm/job`, `/farm/worker`, `/farm/diagnose`. Tests:
`tests/test_render_farm.py` (engine, fake workers) and `tests/test_studio_engine_ui.py` (UI, stubbed engine).

# Engine - Godot or the Carbon Editor

The **Engine** tab (was "Godot"; mode id `godot`) picks the engine at the top: **Godot** (as before) or **Carbon**
- the owner's C++ engine editor in `native/carbon_mmo`. `engine/carbon_editor.py` finds the built `cmmo_editor`
(`LOKI_CARBON_BUILD`, else `/Volumes/Xero/carbon_mmo/build` on the Mac when Xero is mounted, else
`native/carbon_mmo/build`), builds it in the background with `tools/build.py --keep --no-tests [--open]` (log in
`<build>/../loki_build.log`) and opens it with its content folder. API: `GET /carbon/status`, `POST /carbon/open`,
`POST /carbon/build {open}`.
