---
name: render
title: Render
triggers: render, rendering, renders, turntable, beauty shot, beauty pass, hero shot, product shot, lighting, light rig, three-point, hdri, depth pass, lineart pass, normal pass, passes, ai render, ai renderer, render studio, lab, farm, render farm, comfyui, still of the model, render the model, showcase, portfolio shot, look dev, lookdev, cycles, eevee
specialists: Lighting / Render, Technical Artist, Reviewer, worker
---
# Render

## Purpose
Presentation images and turntables of a finished 3D model: fast technical passes (depth, line art, normal, beauty)
rendered headless, a lit beauty set and 360-degree turntable, and - when a prompt is given - AI-finished stills or
videos from LOKI's AI Renderer on the PC's ComfyUI (the passes steer the look). Done means the passes, the stills and
the turntable exist in renders/, the camera and light rig are recorded, and the owner OK'd every AI prompt.

## Stages
```json
[
 {
  "id": "intake",
  "specialist": "Lighting / Render",
  "objective": "Pick the model and the purpose: QA passes, portfolio beauty set, turntable, or AI-finished look.",
  "output": "INTAKE: model path (.glb), purpose, outputs wanted (passes / stills / turntable / AI still / AI video), size, frames",
  "tools": ["library", "read_file", "list_machines"],
  "check": "the model file exists and opens; the PC is online when an AI render is wanted (list_machines), otherwise the stage says the AI part waits",
  "gate": "",
  "writes": false,
  "depends_on": []
 },
 {
  "id": "passes",
  "specialist": "Lighting / Render",
  "objective": "Render the fast passes headless at the chosen camera: depth, line art, normal, beauty and the contact sheet.",
  "output": "renders/<model>-<time>/depth.png lineart.png normal.png beauty.png + contact sheet",
  "tools": ["render_scene"],
  "check": "all four passes exist; subject fills ~70% of the frame height; depth has a clear near-far ramp with no clipped white/black; line art has closed outer contours",
  "gate": "",
  "writes": true,
  "depends_on": ["intake"]
 },
 {
  "id": "light",
  "specialist": "Lighting / Render",
  "objective": "Light and stage the beauty set in Blender: three-point rig or a neutral studio HDRI, camera 50-85 mm, contact shadow, neutral gradient background.",
  "output": "renders/<model>-beauty-<angle>.png (front 3/4, side, back 3/4) and the rig notes (key/fill/rim angles and ratios, camera focal length and height)",
  "tools": ["blender", "run_on_machine"],
  "check": "key 45 degrees front-left and strongest; fill at ~1/3 of the key from the other side; rim from behind separates the silhouette; no clipped highlights on the main surfaces; samples and render time reported",
  "gate": "",
  "writes": true,
  "depends_on": ["passes"]
 },
 {
  "id": "turntable",
  "specialist": "Lighting / Render",
  "objective": "Render a 360-degree turntable: 5 s at 24 fps (120 frames) or 48 frames for a quick one, camera fixed, model or light rig rotating.",
  "output": "renders/<model>-turntable.mp4",
  "tools": ["render_scene", "blender"],
  "check": "the loop is seamless (frame 0 and the last differ by one step); speed constant; no flicker; H.264 plays in a browser",
  "gate": "",
  "writes": true,
  "depends_on": ["light"]
 },
 {
  "id": "ai-look",
  "specialist": "Lighting / Render",
  "objective": "When a look prompt is given: submit it for the owner's OK, then render AI-finished stills or a video on the PC's ComfyUI from the passes.",
  "output": "renders/<model>-ai-<n>.png or renders/<model>-ai.mp4 with prompt, seed, strength",
  "tools": ["render_scene", "machine_job", "run_on_machine"],
  "check": "the silhouette and pose in the AI still match the beauty pass (overlay within a few %); the prompt was approved; video jobs collected with action=status",
  "gate": "owner",
  "writes": true,
  "depends_on": ["passes"]
 },
 {
  "id": "review",
  "specialist": "Reviewer",
  "objective": "Look at every output side by side and give a verdict per file: keep, redo with one change.",
  "output": "renders/<model>-review.md with each file's verdict and the render settings table",
  "tools": ["read_file", "bash"],
  "check": "every output opened; issues named (noise, fireflies, clipped whites, shadow acne, wrong framing, AI drift from the model); render engine, samples, time and resolution listed",
  "gate": "owner",
  "writes": true,
  "depends_on": ["turntable", "ai-look"]
 }
]
```

## Questions
```json
[
 {
  "header": "Output",
  "question": "What should the render produce?",
  "multi": true,
  "options": [
    {"label": "Beauty stills", "description": "Lit portfolio shots from three angles"},
    {"label": "Turntable", "description": "A 360-degree spin video"},
    {"label": "AI look", "description": "AI-finished stills on the PC from a look prompt"},
    {"label": "Passes only", "description": "Depth, line art, normal, beauty - seconds, no GPU"}
  ],
  "skip_if": "(?i)\\b(turntable|beauty|passes|ai render|ai look|still|portfolio)\\b"
 },
 {
  "header": "Look",
  "question": "Which lighting look?",
  "multi": false,
  "options": [
    {"label": "Studio neutral", "description": "Three-point rig, grey gradient"},
    {"label": "Night", "description": "Cool moonlight key, warm practical rim"},
    {"label": "Outdoor", "description": "Sun and sky HDRI"}
  ],
  "skip_if": "(?i)\\b(studio|night|moon\\w*|outdoor|sunset|sunlight|hdri|dramatic)\\b"
 },
 {
  "header": "Model",
  "question": "Which model should be rendered?",
  "multi": false,
  "options": [
    {"label": "Newest model", "description": "The newest finished model in the library"},
    {"label": "Pick one", "description": "I will name the file"}
  ],
  "skip_if": "(?i)(models/|\\.glb|\\.gltf|\\.fbx|\\.blend|this model|the model)"
 }
]
```

## Checklist
- The model is the finished one (from the 3d playbook), not the raw generation, unless QA passes were asked.
- Camera 50-85 mm look, eye level or slightly below for heroic subjects; subject fills ~70% of the frame height.
- Same camera for all passes so they line up pixel for pixel.
- Three-point rig: key front-left 45 degrees (warm, strongest), fill front-right ~1/3 of the key (cool), rim from behind.
- Or a neutral studio HDRI at low strength with a ground contact shadow.
- Background neutral gradient or the scene's own; no distracting props.
- Exposure: no clipped whites on the main surfaces, no crushed blacks in the shadows (check the histogram).
- Noise acceptable at 100%: enough samples or denoising, no fireflies.
- Turntable: 360 degrees, constant speed, seamless loop, 24 fps, 5 s (or 48 frames quick).
- AI look: prompt OK'd by the owner; strength chosen so the shape follows the depth/line art; silhouette checked against the beauty pass.
- AI renders ran on the PC's ComfyUI (8 GB VRAM): resolution and frame counts kept in its budget (832x480 for video, frames in steps of 4 + 1).
- Render engine, samples, time and resolution reported for every output.
- Files in renders/ with model name and time in the name.
- Videos H.264 yuv420p, play in a browser.

## Quality bar
- Great: the silhouette reads against the background at thumbnail size; rim light outlines the whole top edge.
- Great: key-to-fill ratio around 3:1 for form; flatter (2:1) for product clarity, stronger (4-8:1) only for drama.
- Great: turntable speed 360 degrees in 5-8 s - slow enough to read every side.
- Great AI stills keep the model's proportions and parts (no new limbs, no lost horns) while adding material and atmosphere.
- Great sets are consistent: same rig, same camera height, same background across all angles.
- Acceptable renders show the model; great renders make the shapes and materials read at a glance.

## Failure modes
- Model too small or cut off in frame -> frame on the bounding box, subject at ~70% of the height, recheck after changing focal length.
- Flat, lifeless lighting -> add the rim, raise the key-to-fill ratio, move the key higher (30-45 degrees elevation).
- Black or blown-out render -> wrong light units or HDRI strength; check exposure on the beauty pass first.
- Noise and fireflies -> more samples, clamp indirect, enable denoising; avoid tiny bright emitters.
- Shadow acne or peter-panning -> adjust shadow bias / soft shadow size; add a contact shadow catcher.
- Turntable jumps at the loop -> last frame must stop one step short of 360 degrees.
- AI look ignores the model's shape -> raise the depth/line art strength; simplify the prompt to materials and light, not new shapes.
- AI look invents a different character -> remove subject-changing nouns; describe only surface, light and mood; use the beauty pass as the start image.
- PC out of VRAM in ComfyUI -> lower the size (832x480), fewer frames, one job at a time; never queue several.
- AI video job never collected -> render_scene action=status job=<id> until done; report the job id if it is still running.
- Render ran on the Mac and stalled it -> heavy Blender renders and all AI renders go to the PC.
- Passes do not line up -> one camera, one resolution for every pass; never re-frame between passes.

## Hand-off
Beyond the constitution's block: the model path, the camera (focal length, height, azimuth/elevation), the rig (key,
fill, rim angles and ratios, or HDRI and strength), each output path with engine, samples, render time and
resolution, the AI prompt with seed and strength, and AI job ids still running.

## Tools
- library kind=models: the finished model.
- render_scene model=models/<file>.glb passes=depth,lineart,normal,beauty azimuth=30 elevation=15 size=: fast passes and contact sheet, no GPU; frames=48 adds a turntable; prompt= sends an AI still (frames=1) or video (frames>1) to ComfyUI on the PC; action=status job= collects it.
- blender action=run commands=[{type: stage|render|turntable, params}] or action=polish style=studio|night|outdoor turntable=120: lit beauty sets.
- list_machines: check the PC is online before AI renders.
- run_on_machine machine=pc / machine_job: long Blender renders on the PC.
- bash: ffmpeg for contact sheets, loop checks and re-encoding.

## References
- LOKI lighting-render specialist - skills/art-pipeline/lighting-render/SKILL.md
- LOKI AI Renderer on ComfyUI (passes, VACE, frame steps) - docs/AI_RENDERER.md
- Blender manual, Cycles render baking and settings - https://docs.blender.org/manual/en/2.91/render/cycles/baking.html
- Mickmumpitz AI Renderer 2.0 project page (line art + depth control) - https://mickmumpitz.ai/posts/ai-renderer-2-0-153434545
