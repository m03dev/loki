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

# AI speed-ups (render less, AI does the rest)

Render Studio > Path traced > **AI speed-up**: the path tracer renders fewer pixels or frames, and when it is done the
render goes to the farm with an AI graph (`engine/ai_renderer.post_job`, `POST /render/post`, `POST /farm/post`):

| Choice | Path tracer renders | AI on the farm's GPU | Graph |
| --- | --- | --- | --- |
| Half size, upscale 2x | 1/4 of the pixels | Real-ESRGAN x4, then scaled to 2x | `ai_upscale` (core ComfyUI nodes) |
| Quarter size, upscale 4x | 1/16 of the pixels | Real-ESRGAN x4 | `ai_upscale` |
| Every 2nd frame, in-betweens | 1/2 of the frames | RIFE makes the frames between | `ai_interpolate` (ComfyUI-Frame-Interpolation, MIT) |
| Every 4th frame, in-betweens | 1/4 of the frames | RIFE x4 | `ai_interpolate` |

Needs on the GPU machine: `RealESRGAN_x4plus.pth` in `ComfyUI/models/upscale_models` (BSD-3-Clause), and the
ComfyUI-Frame-Interpolation pack for RIFE (it fetches its own checkpoint). The preflight says what is missing.
RIFE VFI's inputs changed between pack versions; the graph marks it `adaptive`, so inputs an older pack lacks are
dropped and inputs a newer one requires get the server's default.

# The harness: what each model call sends (engine/context_budget.py)

Old tool results are masked (a one-line stub naming the tool and what it said; the newest 4 stay whole), the mask
moves in batches of 6 so the prompt's start stays identical and the provider's prefix cache keeps hitting, old huge
tool-call arguments are cut, one tool result is capped at 24,000 characters (start + end kept), and LLM condensing
(engine/condenser.py) starts at 160k characters for cloud models (was 280k). The meter under a reply shows how much
of the prompt came from the provider's cache. Knobs: `LOKI_MASK=off`, `LOKI_MASK_KEEP`, `LOKI_MASK_STEP`,
`LOKI_TOOL_RESULT_CHARS`, `LOKI_CONDENSE_CHARS`. Based on observation masking ("The Complexity Trap", arXiv
2508.21433: as good as LLM summarization at about half the raw agent's cost) and Anthropic's tool-result clearing.
