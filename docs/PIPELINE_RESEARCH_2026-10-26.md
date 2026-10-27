# Concept -> turnaround -> 3D -> scene: open-source review (2026-10-26)

Owner 2026-10-26: "all the agents should be harmonious same with the 3d maybe they can make 3d scenes this is the
path we're taking look for more open source recourses we could use deep dive". Licences were read from the repos
and Hugging Face model cards (code AND weights). LOKI is AGPL-3.0 and meant for commercial use, so only MIT, BSD,
Apache-2.0, ISC, MPL-2.0, LGPL, GPL-3.0 and AGPL-3.0 are used; anything else is at most an optional tool the owner
installs. "unverified" = not confirmed in this review.

## Licence traps found (act on these)

- **rembg's default model is bria-rmbg (RMBG-2.0, non-commercial)** - LOKI's sprite and 3D cut-outs called it
  bare. Fixed the same day: engine/cutout.py names BiRefNet (MIT) / U^2-Net (Apache) every time.
- **nvdiffrast** (NVIDIA Source Code License, non-commercial) - TRELLIS / TRELLIS.2 use it for display and maybe
  textured GLB export (microsoft/TRELLIS.2 issue #22). Mesh-only first; the textured path needs a check.
- **DINOv3** (TRELLIS.2, Pixal3D) - Meta custom licence: commercial use allowed, needs a "Built with DINOv3" notice.
- **TripoSG / PartCrafter** - MIT, but one file carries the Tencent HunyuanDiT agreement (EU excluded). Avoid.
- **Qwen-Image-2.1** - Qwen Research Licence (non-commercial), and its LoRAs. (Qwen-Image-Edit-2509/2511 are
  Apache-2.0 - different models.)
- **InstantMesh** - Apache code, but needs Zero123++ (CC-BY-NC weights). Avoid.

## 1. Concept art

| Pick | Code / weights | 8 GB PC / Mac | ComfyUI | Why |
| --- | --- | --- | --- | --- |
| FLUX.2 klein 4B | Apache / Apache | fp8/nvfp4 + offload (unverified) / MPS (unverified) | yes | in use now; multi-reference edit |
| Qwen-Image-Edit-2511 | Apache / Apache | GGUF Q4 or Nunchaku + offload, tight on 16 GB RAM | native | best Apache identity-keeping edit |

Not usable: FLUX.2 klein **9B** (FLUX non-commercial).

## 2. Technical artist (T-pose turnaround, orthographic views)

1. **Qwen-Image-Edit-2509/2511 + DWPose keypoints + LoRAs** (Apache): re-pose the concept to a T/A-pose, then
   front / side / back at 0 degrees with `fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA` (96 camera presets) or a
   whole sheet with `tarn59/character_turnaround_sheet_qwen_image_edit_2509`. Keeps the concept's identity -
   better than LOKI's v1 (engine/turnaround.py: each view drawn from text on one seed).
2. **MV-Adapter** (github.com/huanngzh/MV-Adapter, Apache/Apache, ComfyUI-MVAdapter): consistent multi-view
   trained on orthographic views; SDXL image-to-MV needs ~14 GB, SD2.1 variants under 10 GB.
3. **Era3D** (AGPL-3.0, `-ortho` model, 6 orthographic views) - props and vehicles; idle since 2024.
4. FLUX.2 klein 4B multi-reference + DWPose skeleton (pose ControlNet for klein unverified).

Pose skeletons: DWPose (Apache, unverified) - not CMU OpenPose. Identity: OmniGen2 (Apache, ~8.5 GB with offload).
Avoid: PuLID / InstantID (InsightFace non-commercial), ACE++ / FLUX.1 Kontext dev, StdGEN, Zero123++, SV3D.

## 3. Views -> 3D, texture, rig

| Pick | Code / weights | 8 GB / Mac | ComfyUI | Note |
| --- | --- | --- | --- | --- |
| TRELLIS.2-4B, Pixal3D | MIT / MIT (+ caveats above) | 24 GB official; 8 GB "conditionally" low-VRAM; Mac: trellis-mac, trellis2-mlx | native | best quality, PBR; single image in |
| Direct3D-S2 | MIT / unstated | 10 GB at 512 | community node | geometry only |
| Step1X-3D | Apache / Apache | ~27 GB - no | no | clean licence, too big |

No clean open multi-view -> 3D model confirmed: feed the FRONT view to TRELLIS.2 / Pixal3D, use the other views to
check the model and for texturing. Texturing: MV-Adapter texture (Apache, < 10 GB SD2.1), TRELLIS.2 texturing (MIT).
Rigging: **UniRig** (MIT code, 8 GB, FBX/GLB; weights licence unstated), Puppeteer (Apache code; weights unstated).

## 4. Scenes

1. **LOKI's agents + MCP for Blender** (github.com/ahujasid/mcp-for-blender, MIT): layout from the models LOKI made,
   Poly Haven CC0 assets, glTF to Godot. Leave its paid Hunyuan/Rodin generators off; DISABLE_TELEMETRY=true.
2. **Infinigen** (BSD-3): procedural nature / indoor scenes, OBJ/USD (glTF through Blender); CPU heavy.
3. MIDI-3D (Apache code, ~30 GB - too big), PartCrafter-Scene (TripoSG doubt).

No mature open "art director -> technical artist -> 3D artist" framework exists; LOKI's own agents are the pipeline.

## Recommended stack

- **PC (RTX 3070 Ti 8 GB):** FLUX.2 klein 4B concept -> Qwen-Image-Edit-2511 GGUF + DWPose + Multiple-Angles LoRA
  turnaround (MV-Adapter SD2.1 / Era3D-ortho fallback) -> TRELLIS.2 / Pixal3D low-VRAM in ComfyUI with BiRefNet,
  mesh first -> UniRig -> GLB into the Engine tab.
- **Mac:** orchestration, MCP for Blender layout and glTF export; TRELLIS.2 through trellis-mac / MLX only with
  24 GB+ unified memory (unverified on this Mac mini). Models on Xero.

## Avoid (or owner-installed only)

Hunyuan3D-2 / 2.1 / Paint / HunyuanWorld (Tencent community licence: EU/UK/KR excluded), SPAR3D and SV3D
(Stability), FLUX.1-dev / Kontext-dev / Fill-dev / FLUX.2 klein 9B / FLUX.2-dev Fun ControlNet, Qwen-Image-2.1 and
its LoRAs, InsightFace models, Zero123++ (so InstantMesh), StdGEN, RMBG-1.4 / 2.0, nvdiffrast / nvdiffrec.

## Afternoon update (2026-10-26, owner: "add hunyuan3d-2.1 ... blender toolkit ... more open resources for free")

Three research passes (sources in the session; GitHub/HF pages partly blocked, so "unverified" marks stay).

**Hunyuan3D** - 2.1 (Jun 2025) is still the newest with downloadable weights; 2.5 / 3.0 / 3.1 / PolyGen are API-only
(paid). Licence (read from the repo): Tencent Hunyuan 3D 2.1 Community License - same terms for code and weights,
not valid in the EU/UK/South Korea, >1M MAU needs Tencent, 5.b: its output must not improve any other AI model, 3.e:
a product built on it must say Tencent does not endorse it. => **owner-installed backend only**
(engine/forge_hunyuan.py, tools/setup_hunyuan3d.py; nothing of it in LOKI) and its output is kept out of LOKI's
training (experience.build_dataset skips "no_training"). 8 GB route: ComfyUI's native 2.1 shape nodes (official
template, engine/forge_workflows/hunyuan3d21.json); the official api_server needs ~10 GB for shape and its
--low_vram_mode only empties the cache. Texture: 2.1 PBR (21 GB) unproven at 8 GB - the 2.0 Paint(-Turbo) model via
kijai's ComfyUI-Hunyuan3DWrapper is the 8 GB option (not wired yet).

**Blender** - LOKI's own toolkit in the Blender core (engine/blender_scripts/loki_blender_core.py): import, cleanup,
normalize, decimate, remesh (voxel / QuadriFlow), uv (only where missing - an AI model's own UVs carry its texture),
shade, stage (PBR Neutral view transform: matches glTF viewers/Godot, keeps emission saturated), render, export,
lods, turntable; blender_link.polish() chains them. Verified on the PC (Blender 5.2.3). "Blender toolkit" the owner
named is most likely Dev-GOM's blender-toolkit Claude plugin (licence not stated - check before using). Second MCP:
dcc-mcp-blender (MIT, ~205 tools; Blender 5.x unverified) - added opt-in. Official Blender Lab MCP (GPL-3.0, 26
tools, Blender 5.1+) - optional. Avoid: Quad Remesher, Auto-Rig Pro (paid), Blender MCP Pro.

**Free assets (CC0, commercial, no attribution for the assets)** - Poly Haven (API; LOKI's User-Agent + "Powered by
Poly Haven" credit), ambientCG (API), Kenney, Quaternius, KayKit (no API). engine/free_assets.py (search/download,
sidecar with licence + credit) - verified against the real APIs from the PC. Mixed: Poly Pizza (CC0 vs CC-BY per
model), OpenGameArt, Freesound (has NC). Avoid for agents: Mixamo (no redistribution, no ML training), BlendKit RF
assets in the public repo.

**Next candidates** - UniRig (MIT code, weights licence unstated - check), gltfpack/meshoptimizer (MIT) for game
export, glTF-Validator (Apache), Basis/KTX2 (Apache), PyMeshLab (GPL) and manifold3d (Apache) for repair, xatlas
(MIT) for packing. More traps found: OmniPart (NVIDIA PartField + RMBG-2.0 in its NOTICE), PartPacker (NVIDIA NC),
HY-Motion (Hunyuan licence), SMPL-based text-to-motion, Kimodo (NVIDIA Open Model License + bundled Llama terms).

## Evening update: retopology - from AI soup to workable quads (owner: "i need the models to be improved with working topology")

What exists (web research, two agents; nothing here was tested except where it says "PC"):

| Tool | Licence | Use in LOKI |
| --- | --- | --- |
| Blender QuadriFlow | GPL, inside Blender | primary, built in. **PC: works** once the mesh passes Blender's own pre-check |
| Instant Meshes (wjakob) | BSD-3 | fallback CLI (`-o -f -d -S 2 -b -r 4 -p 4`), LOKI_INSTANT_MESHES; also already inside Forge's WASM sculpt engine |
| QuadWild Bi-MDF (cgg-bern) | GPL-3.0 | best flow of the open tools, minutes per mesh, prebuilt binaries; next fallback (LOKI_TASKS) |
| QRemeshify (Blender add-on over QuadWild) | GPL | guides from seams / sharp edges; headless use unverified |
| Quad Remesher (Exoside), Auto-Rig Pro | proprietary | never vendored; the owner may install them himself |
| MeshAnything V1/V2, BPT, DeepMesh, FastMesh, TreeMeshGPT | non-commercial or unclear; 0.8k-8k faces, triangles | not usable for creatures |
| Meshtron, QuadGPT, Nautilus, Silksong | no weights | re-check in 2027 |

Why QuadriFlow "failed as non-manifold" on every AI mesh (PC, found by reading Blender's source,
`source/blender/editors/object/object_remesh.cc` mesh_is_manifold_consistent): besides >2 faces per edge, flipped
neighbours and wire edges, it rejects ANY edge shorter than 1e-4 on every axis in LOCAL coordinates - and voxel /
marching surfaces make such edges. Scaling the object does nothing (the check reads the mesh data). LOKI's `retopo`
applies scale, voxel-rebuilds, merges below ~0.2 mm, repeats until its replica (`qf_problems`) is clean.

Recipe now in the core (`retopo` + `bake normal=true`): original kept -> voxel (diag/160) -> clean until the
pre-check passes -> QuadriFlow 3 seeds -> Instant Meshes -> voxel-only fallback -> shrinkwrap / relax / shrinkwrap onto
the voxel surface -> UV -> bake Base Color as emission (DIFFUSE is black when metallic=1, glTF's default) + tangent
normal map from the original -> topology report. PC numbers: fantasy character 32,834 tris (0% quads, 92.6% poles)
-> 7,260 quads, 100% quads, 4.2% poles, 0 non-manifold, ~5-12 s; robot 9,934 tris -> 8,196 quads, 1.0% poles.

Not automatic anywhere (open or paid): artist edge loops around eyes and mouth and extra loops at joints. Levers:
QuadWild guides (seams / face sets where loops should run), symmetry (centre, symmetrize, remesh half, mirror), or a
human pass. Agent side: skills/blender-gameready (router + cleanup / retopo / uv-bake / qa stages with numeric gates,
the layout of arjun988/blender-skills, MIT); research systems (LL3M - non-commercial, not used; BlenderGym: spending
compute on verification pays) check with renders only - none measure topology, which LOKI now does.

## Night update: the agent pipeline (owner: "like an industry pipeline where they pass on work to each other and can improve")

Built as engine/asset_pipeline.py (docs/ASSET_PIPELINE.md). What each idea came from (web research; licences as found,
nothing vendored):

| Source | Licence | Taken |
| --- | --- | --- |
| Pyblish | LGPL-3.0 | collect -> validate -> integrate: nothing failed is handed on |
| Kitsu / Zou (CGWire) | AGPL-3.0 | task statuses incl. retake |
| ShotGrid / Flow | proprietary | review notes as their own records, open until a version addresses them |
| OpenCue / Gaffer | Apache-2.0 / BSD-3 | stages with `needs` (a dependency graph) |
| OpenAssetIO | Apache-2.0 (unverified) | `loki://asset/stage@approved` references |
| MetaGPT / ChatDev | MIT / Apache-2.0 | structured hand-off documents; only the agreed result goes forward |
| CrewAI | MIT (unverified) | expected output + guardrail + 3 retries with the error fed back |
| LangGraph | MIT | a checkpoint after every step |
| Reflexion / ExpeL / ACE | MIT / CC-BY paper / Apache-2.0 | lessons after failures, helpful/harmful votes, delete at 0, dedupe |
| Voyager | MIT | promote only verified knowledge into the skill library |
| BlenderGym, planner-actor-critic (2601.05016) | papers | spend on verification; cap refinement at ~3 rounds |

Not used: LL3M (academic licence), SkillWeaver (OpenRAIL research-only) - ideas only. Studio pipelines also version
every publish (AYON products -> versions -> representations); LOKI keeps every try as v00N with its record.

## Late update: turnarounds, settings, feedback, common problems (owner: "the perspective technical images ... are awful")

What was wrong (seen on the Mac): every view was drawn from TEXT with the same seed - a red pixel-art dragon came back
grey and realistic; "model sheet" wording made FLUX write fake labels; scenes (a library interior, a glacier fortress)
were "turned around". Fixed in engine/turnaround.py: the concept is the REFERENCE for every view (FLUX.2 klein 4B edit,
Apache-2.0 - NVIDIA's hosted `image: [...]` field on the Mac; `mflux-generate-flux2-edit --image-paths` when mflux is
installed), the front view joins as a second reference, prompts say "no text, no letters, no labels", scenes are refused,
and each view is scored: colour match vs the concept + silhouette height / centring vs the front (the pipeline's
turnaround check fails a view that drifts). A view drawn from text when no edit model answered is marked mode "text".

| Option for views from one concept | Licence | Use |
| --- | --- | --- |
| FLUX.2 klein 4B edit / multi-reference | Apache-2.0 | default (hosted NVIDIA; mflux -q 8 on the Mac; sd.cpp `-r` on the PC) |
| Qwen-Image-Edit-2511 (+ Multiple-Angles LoRA) | Apache-2.0 (LoRA licence unverified) | PC high-quality path: sd.cpp `--model-args qwen_image_zero_cond_t=true` |
| MV-Adapter (SD2.1 variant < 6 GB) | Apache-2.0 code, OpenRAIL base | orthographic 6-view fallback on 8 GB |
| Era3D | AGPL-3.0 | possible |
| FLUX.1 Kontext dev, FLUX.2 klein 9B, FLUX 3 Klein, Qwen-Image 2.1, Zero123++ weights, SV3D | non-commercial / restricted | NOT used |

Next for turnarounds (LOKI_TASKS): a Blender orthographic T-pose mannequin as reference 2 (pose, scale, camera in one),
front first then the rest from it, a DINOv2 similarity check, Qwen-Image-Edit-2511 on the PC.

Common problems -> fixes (sources in the research notes): mflux OOM on 16 GB -> `-q 8`/`-q 4`, `--low-ram`; sd.cpp on
8 GB -> `--offload-to-cpu`, `--vae-tiling`, `--clip-on-cpu`, flash attention; ComfyUI 8 GB -> `--lowvram`, GGUF;
TRELLIS Spaces -> token, endpoint discovery (view_api), several Spaces in turn; rembg -> never the default bria model
(engine/cutout.py names BiRefNet); image-to-3D input -> square, centred, flat light, no perspective; QuadriFlow -> clean
until Blender's own pre-check passes (engine/blender_scripts retopo); black bakes -> emission bake of Base Color.

Settings (engine/image_settings.py, ideas from Fooocus / InvokeAI / SwarmUI / Draw Things): one list drives the
viewer's panel; distilled FLUX / Turbo models ignore CFG and the negative prompt, hosted APIs ignore samplers - the
panel greys what the chosen model ignores. Feedback (engine/image_feedback.py): thumbs up / down + reasons, Midjourney-
style preference memory without a model download (LAION aesthetic / ImageReward / PickScore later; check weights).
