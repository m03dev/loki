---
name: 3d
title: 3D model
triggers: 3d, 3d model, model of, mesh, glb, gltf, fbx, obj, blend file, game asset, game-ready, game ready, low poly, low-poly, retopo, retopology, topology, uv, uvs, unwrap, bake, normal map, lod, lods, blender, forge, sculpt, rig, rigging, polycount, quads, image to 3d, trellis, make it 3d, prop model, creature model, character model, export to godot
specialists: 3D Artist, 3D Finisher, Technical Artist, Reviewer
---
# 3D model

## Purpose
A game-ready 3D asset made by LOKI from an approved design: a textured mesh lifted from the turnaround's front view
(TRELLIS.2 on the PC first), rebuilt in Blender as clean quads with UVs, baked colour and normal maps, LODs, and
exports (.glb .gltf .fbx .blend), opened in Forge. Done means the topology numbers pass, renders show it matches the
side and back views, and the files are on disk with a QA report.

## Stages
```json
[
 {
  "id": "intake",
  "specialist": "Technical Artist",
  "objective": "Decide the source and the budget: approved turnaround front view (preferred), a concept picture, or a Blender build from scratch; the use and its triangle budget.",
  "output": "INTAKE: source path, kind, use (game asset / hero / blockout), triangle budget, retopo quad target, scale and axis",
  "tools": ["library", "asset_pipeline", "read_file"],
  "check": "a source exists on disk or the stage routes to the turnaround playbook first; budget from the table (prop 1-6k tris, creature/NPC 15-40k, hero 50-100k, mobile hero 15-30k)",
  "gate": "",
  "writes": false,
  "depends_on": []
 },
 {
  "id": "generate",
  "specialist": "3D Artist",
  "objective": "Lift the front view to a textured mesh on the PC: TRELLIS.2 first, Pixal3D second, TripoSR/online only as fallback.",
  "output": "models/<name>.glb (+ .obj) with backend and seed",
  "tools": ["make_3d", "run_on_machine", "machine_job"],
  "check": "the .glb opens; triangle count above 1000; one main shell (no floaters); texture present and not smeared across the back",
  "gate": "",
  "writes": true,
  "depends_on": ["intake"]
 },
 {
  "id": "likeness",
  "specialist": "Reviewer",
  "objective": "Compare the raw mesh with the side and back views using untextured passes, before spending time on finishing.",
  "output": "renders/<name>-<time>/ passes + LIKENESS verdict per view (silhouette match, missing parts)",
  "tools": ["render_scene", "read_file"],
  "check": "depth/normal passes rendered at azimuth 0, 90 and 180; side silhouette within the 12% height check; no missing limbs or fused parts; else back to generate with the next backend (max 3 tries)",
  "gate": "",
  "writes": false,
  "depends_on": ["generate"]
 },
 {
  "id": "finish",
  "specialist": "3D Finisher",
  "objective": "Make it game-ready in Blender: repair, normalize to metres, retopo to clean quads, UV, bake colour + normal from the high mesh, LODs, exports.",
  "output": "models/<name>.glb .gltf .fbx .blend + LOD1/LOD2 + a staged render, and the topology JSON",
  "tools": ["blender", "run_on_machine"],
  "check": "topology: quad_pct >= 95, pole_pct <= 8, nonmanifold 0, faces within budget; baked colour not black; normal map written; scale 1 unit = 1 m, +Y up, origin at the feet",
  "gate": "",
  "writes": true,
  "depends_on": ["likeness"]
 },
 {
  "id": "qa",
  "specialist": "Reviewer",
  "objective": "Give a SHIP / NO-SHIP verdict from numbers and renders: beauty + wireframe, UV checker, LODs side by side.",
  "output": "models/<name>-qa.md with the numbers, render paths and the verdict",
  "tools": ["blender", "render_scene", "read_file"],
  "check": "renders looked at: no shading seams, no stretched UVs on the checker, no normal-map inversions, silhouette holds at LOD2; file sizes listed",
  "gate": "",
  "writes": true,
  "depends_on": ["finish"]
 },
 {
  "id": "deliver",
  "specialist": "3D Finisher",
  "objective": "Hand over the asset: open in Forge, list exports, and offer the render playbook.",
  "output": "the hand-off block with every export path, the QA file and the Forge-open confirmation",
  "tools": ["library", "asset_pipeline"],
  "check": "the model shows in the library as a 3D model; when the asset pipeline is used, the finish stage was submitted with its files",
  "gate": "owner",
  "writes": false,
  "depends_on": ["qa"]
 }
]
```

## Questions
```json
[
 {
  "header": "Use",
  "question": "What is the model for?",
  "multi": false,
  "options": [
    {"label": "Game asset", "description": "Low-poly quads, baked maps, LODs"},
    {"label": "Hero detail", "description": "High detail for renders and close shots"},
    {"label": "Blockout", "description": "Quick shapes to judge the idea"}
  ],
  "skip_if": "(?i)\\b(low.?poly|game.?ready|game asset|hero|high.?poly|blockout|print)\\b"
 },
 {
  "header": "Start from",
  "question": "What should the model be made from?",
  "multi": false,
  "options": [
    {"label": "Newest turnaround", "description": "The front view of the newest approved sheet"},
    {"label": "Concept first", "description": "Concept, then turnaround, then 3D - you OK each picture"},
    {"label": "Build in Blender", "description": "Modelled from primitives in code, no picture"}
  ],
  "skip_if": "(?i)(turnarounds/|images/|\\.png|\\.jpe?g|from (the|this|my) (picture|image|concept|turnaround)|from scratch in blender)"
 },
 {
  "header": "Kind",
  "question": "What kind of thing is it?",
  "multi": false,
  "options": [
    {"label": "Creature", "description": "About 8k quads, symmetric"},
    {"label": "Character", "description": "About 8k quads, T-pose"},
    {"label": "Prop", "description": "About 2-3k quads"},
    {"label": "Vehicle", "description": "Hard surface, about 6k quads"}
  ],
  "skip_if": "(?i)\\b(creature|monster|animal|character|person|hero|prop|weapon|sword|chair|crate|vehicle|car|ship)\\b"
 }
]
```

## Checklist
- Source is the approved turnaround front view (clean background, full body), or the work went to the turnaround playbook first.
- Generation ran on the PC; the Mac did not load the 3D model weights.
- Raw mesh: one main shell (largest share >= 0.85), no floaters, textured.
- Likeness checked against side and back views before finishing.
- Scale: 1 unit = 1 m, real-world height (a human ~1.8 m); +Y up in glTF; facing -Z; origin at the feet; transforms applied.
- Retopo: quad_pct >= 95, pole_pct <= 8, nonmanifold 0, face count within the budget for the kind.
- symmetric=true for front-facing symmetric creatures and characters.
- Original kept as <name>__high for the bake; never exported.
- UVs: no overlaps (unless mirrored on purpose), seams in hidden places, uniform texel density, >= 4 px padding at 2048.
- Bake: base colour and tangent-space normal at 2048, cage or ray distance set so no rays miss; margin >= 8 px.
- Normal map space matches the material setting (tangent for game assets).
- LODs at 100 / 50 / 20-25 % with the silhouette intact at LOD2.
- Exports: .glb .gltf .fbx .blend present and openable; file sizes listed.
- Beauty and wireframe renders looked at; UV checker render looked at.
- Free assets (from free_assets) were changed with edits before export, never shipped as downloaded.
- QA verdict SHIP or NO-SHIP with numbers; at most 3 tries per stage.
- Automatic retopo flagged as not animation-ready for close-up faces when that use is intended.

## Quality bar
- Great: quad_pct >= 98, pole_pct <= 5, every pole off the deformation zones; acceptable: 95 / 8.
- Great: texel density uniform within +-10% across the main surfaces (e.g. ~512-1024 px/m for a third-person game asset at 2048).
- Great: no visible bake errors at 1:1 - no wavy edges, no projection from the wrong side, no black spots.
- Great: LOD2 still reads as the same object at 25 m; triangle drop per LOD 50% or more.
- Great: the glb under 10 MB for a creature with 2048 maps; textures power-of-two.
- Great: matches the side and back views within the 12% silhouette check without manual fixes.

## Failure modes
- Mesh came out empty or a blob -> the input had clutter or perspective; use the clean turnaround front view, then try the next backend (trellis2 -> pixal3d -> online).
- Back of the model smeared or copied from the front -> the generator guessed the back; check against the back view, retry with a different seed, or give the 3D Artist the back view for a texture fix.
- Floating fragments and holes -> blender action=polish runs repair; if largest share < 0.85, regenerate rather than patching.
- Retopo leaves thin parts (tails, horns, fingers) collapsed -> raise retopo faces 1.5x (cap 15000) or split thin parts; check pole_pct afterwards.
- Baked colour black -> rays missed: raise cage extrusion/ray distance, check the high mesh encloses the low, confirm the image node is active and UVs exist.
- Normal map looks inverted (dents instead of bumps) -> glTF and Blender use OpenGL (+Y) normals; DirectX targets need the green channel flipped.
- Shading seams along UV splits -> bake with a cage, keep smooth normals, add margin, put hard edges only on UV borders.
- Wrong scale in Godot (tiny or huge) -> normalize to metres and apply transforms before export; glTF is +Y up, metres.
- Model faces the wrong way in the engine -> the asset faces -Z with +Y up; fix the facing in normalize before export, not by rotating it in the engine.
- Mac froze during the bake -> send polish to the PC (run_on_machine); never run Blender bake next to a local model on the Mac.
- Free asset shipped unchanged -> blender refuses without edits; tint, reshape, combine, then export.
- The same retopo failure three times -> stop at NO-SHIP with the numbers; ask the owner whether a manual pass in Forge is wanted.

## Hand-off
Beyond the constitution's block: the source picture, backend and seed of the raw mesh, the topology JSON (faces,
quad %, pole %, nonmanifold), the bake maps and their size, every export path with its size, the render paths
(beauty, wireframe, UV checker), the SHIP/NO-SHIP verdict, and what still needs a human (face loops for animation).

## Tools
- library kind=models / images: find the turnaround and earlier versions.
- make_3d image=turnarounds/<name>/front.png backend=auto|trellis2|pixal3d|triposr|online: lift to .glb on the best available engine.
- blender action=polish path=models/<file>.glb retopo=8000 (3000 prop, 15000 hero) symmetric=true turntable=48: repair, retopo, bake, LODs, exports, render. action=run commands=[{type: topology|uv|bake|lods|export, params}] for one step; action=make code=<bpy> for a from-scratch build.
- render_scene model=models/<file>.glb passes=depth,normal,beauty azimuth=0|90|180: fast likeness and QA passes without a GPU.
- asset_pipeline action=start|status|brief|submit asset= stage=model|finish: run or record the studio pipeline with its checks and retakes.
- free_assets action=search|download: CC0 raw material only; always edited before export.
- run_on_machine machine=pc / machine_job: heavy generation and bakes go to the PC.

## References
- LOKI 3d-artist and 3d-finisher specialists - skills/art-pipeline/3d-artist/SKILL.md, skills/art-pipeline/3d-finisher/SKILL.md
- LOKI blender-gameready router (budgets, gates) - skills/blender-gameready/SKILL.md
- Blender manual, Cycles render baking (selected to active, cage, margin, normal space) - https://docs.blender.org/manual/en/2.91/render/cycles/baking.html
- ComfyUI TRELLIS.2 tutorial (background removal, PBR output) - https://docs.comfy.org/tutorials/3d/trellis2
- TRELLIS.2 input guide (failures and causes) - https://fal.ai/learn/devs/trellis-2-image-to-3d-prompt-guide
- Foundry Modo, texel density - https://learn.foundry.com/modo/12.0/content/help/pages/uving/texel_density.html
