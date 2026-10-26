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
