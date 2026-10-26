# The asset pipeline

Owner, 2026-10-26: "technical agent skills ... like an industry pipeline where they pass on work to each other and
can improve". Code: `engine/asset_pipeline.py` (one module, standard library only). Test: `tests/test_asset_pipeline.py`.

## The stages

| Stage | Role | Needs | Tool it runs | Checks before it is handed on | A retry changes |
| --- | --- | --- | --- | --- | --- |
| concept | Concept Artist | - | make_image | real picture, >= 512 px, not blank | seed |
| turnaround | Technical Artist | concept | make_turnaround | pictures + front / side / back views | seed |
| model | 3D Artist | turnaround (front view) | make_3d | a .glb, >= 1000 triangles, not the "lift" blob | backend (auto -> pixal3d -> trellis2 -> online -> triposr) |
| finish | 3D Finisher (skills/blender-gameready) | model | blender polish + retopo | repair not "garbage", quads >= 95 %, poles <= 8 %, .glb + .fbx | quads x1.5 (max 15000) |
| render | Lighting / Render | finish | render_scene | pictures | - |

## How work moves

- **Statuses** (Kitsu): waiting -> ready -> wip -> approved, or retake after 3 failed tries (CrewAI's guardrail
  budget; the 3D critic papers see no gain after ~3 rounds). omitted for a stage an asset does not need.
- **Hand-off** (MetaGPT / ChatDev: only the agreed result goes forward): every try writes
  `<workspace>/pipeline/<asset>/<stage>/v00N/record.json` + `handoff.md` - inputs (the upstream records), outputs with
  sha256, the settings, every check with its detail, lessons used, notes addressed. The next stage is given the
  APPROVED record of each stage it needs - never "the newest file in a folder", never a chat log.
- **References** (OpenAssetIO style): `loki://<asset>/<stage>@approved|latest|v002` -> `asset_pipeline.resolve`.
- **Checks** (Pyblish validate): nothing that failed a check is handed on; each check says what to change (its hint).
- **Review notes** (ShotGrid): `note(asset, stage, text, retake=True)` reopens that stage with 3 fresh tries and sends
  every stage after it back to waiting (their versions stay). The note is in the stage's brief until a passing version
  addresses it.
- **Checkpoints** (LangGraph): `pipeline.json` is written after every step; a `wip` older than 3 h (a crash) goes back
  to ready.

## How it improves

- **Lessons** (Reflexion / ExpeL / ACE): `<data>/pipeline/lessons.jsonl`. A failed check writes one ("check failed:
  detail. hint"); a retry that passed after a setting changed writes "When X fails, setting=value fixed it" (a new seed
  is luck, not a lesson). Lessons used by a stage are voted up when it passes and down when it fails; a lesson at
  score 0 is deleted; a near-duplicate (> 0.9 similar) is an upvote, not a new line.
- **Settings memory**: `<data>/pipeline/params.jsonl` - the next asset of the same kind starts from the last settings
  that passed (e.g. the backend that worked).
- **Skills** (Voyager): lessons that helped >= 5 times, never hurt and were in >= 3 approved runs are written to
  `<data>/skills/learned/pipeline-<stage>/SKILL.md`, which the agents' skill catalog loads.

## Who drives it

- The autopilot's `pipeline` duty (LOKI_AUTOPILOT_PIPELINE, every 120 s) runs the next ready stage of the oldest asset
  in the background, one stage at a time.
- Agents use the `asset_pipeline` tool (LOKI's own agent and OpenCode's loki-make): start, status, brief, advance,
  submit (hand in work they made themselves - same checks), note, lessons.
- LOKI_TASKS.md "Always": the PRODUCER starts assets from new concept art; the ART DIRECTOR reviews approved finishes
  and renders and writes retake notes.
- CLI: `python engine/asset_pipeline.py start "brief" --kind creature [--concept images/x.png]`, `status`, `advance
  <asset>`, `brief <asset> <stage>`, `note <asset> <stage> "text" --retake`.

## Next

Rig and export-to-game stages (UniRig after its licence check, LOKI_TASKS); a vision-model judge on the model and
finish renders (forge_judge.judge_one) as a soft check; the model stage sent to the PC from the Mac (machines.py) when
the PC's ComfyUI is up; a Studio-tab view of the stage graph with versions and notes.
