# Forge: Pixal3D and TRELLIS.2 (native ComfyUI)

Forge's best 3D backends run Comfy Org's official image-to-3D templates through ComfyUI's own nodes (no custom node
packs). One picture becomes a textured, PBR-baked `.glb`: BiRefNet cut-out → crop → sparse structure → shape → 1536
upsample → texture → DC remesh → decimate → UV unwrap → bake base colour, metallic, roughness, normal and AO.

| Backend | What | Models (ComfyUI/models/...) |
|---|---|---|
| `pixal3d` | Pixal3D (TencentARC, MIT): pixel-aligned, MoGe estimates the camera so the front matches the picture | pixal3d_int8_convrot, 2 TRELLIS.2 VAEs, DINOv3 NAF, MoGe-2, BiRefNet |
| `trellis2` | TRELLIS.2 (Microsoft, MIT): same pipeline, no camera step | trellis_2_int8_convrot, 2 VAEs, DINOv3 NAF, BiRefNet |
| `pixal3d` + **4-view sheet** | Pixal3D multi-view: a turnaround sheet (front, left, back, right side by side), split into columns by LOKI | pixal3d_multiview_int8_convrot, 2 VAEs, DINOv3 NAF, BiRefNet |

"Best available" uses Pixal3D (or TRELLIS.2 when only its files are there) whenever the ComfyUI at Render's address is
reachable, new enough and has the files; otherwise TripoSR, the online Space, then the offline lift. The same rule as
Render: pictures only go to this computer or LOKI's own linked machines unless the owner allowed another server.

Files:
- `engine/forge_trellis.py`: status / ready / build / run / install (resumable downloads into the ComfyUI folder).
- `engine/comfy_workflow.py`: UI-format → API-format converter (widget order from `/object_info`, seed and upload
  slots, dynamic combos), switch resolution, pruning, loader and model checks.
- `engine/forge_workflows/`: the converted graphs; `ui/` holds Comfy Org's original templates (MIT,
  `engine/licenses/comfy-workflow-templates-MIT.txt`).
- `tools/build_forge_workflows.py` rebuilds the graphs (from `tests/fixtures/comfy_trellis_object_info.json` or a live
  ComfyUI); `tools/comfy_convert.py` converts any other template; `tools/setup_trellis.py` checks and installs on the PC.
- Tests: `tests/test_forge_trellis.py` (fake ComfyUI over HTTP, every graph checked link by link).

8 GB GPUs (the PC's 3070 Ti): the int8 models fit; if a run stops with "out of memory", start ComfyUI with
`--lowvram` and lower Output > Detail (remesh grid) and Texture size. Weights' licences: TRELLIS.2 MIT, Pixal3D MIT,
MoGe MIT, BiRefNet MIT; DINOv3 is Meta's DINOv3 licence (read it before selling models made with it commercially).
Retopology beyond the template's remesh + decimate is Forge's own Retopo tools.
