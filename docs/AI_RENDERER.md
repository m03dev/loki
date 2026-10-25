# AI Renderer 2.0 in LOKI: Render Studio + ComfyUI

The owner's brief: `ai_renderer_2_agent_build_brief.md` (2026-10-21). His decisions that day: the host is **Forge** (LOKI's
own modeller), the generation runs on **his PC** (RTX 3070 Ti, 8 GB VRAM, on 24/7) in **ComfyUI**, with the **GGUF**
build of the VACE + SkyReels merge and **city96's ComfyUI-GGUF** loader. The creator's workflow JSON files are behind
Patreon and he does not have them, so LOKI has **its own graphs, written from scratch** from the node sources below
(AGPL-3.0, `engine/ai_renderer_workflows/`). Nothing below is guessed: each node class, input, route and file comes
from a source read on 2026-10-21, cited with its commit / revision. What could not be read is listed under Blockers.

## 1. What the creator's pipeline is (public pages only)

| Source | What it says |
| --- | --- |
| [Free workflow post](https://mickmumpitz.ai/posts/new-video-free-2-151633267) (read) | Files `260225_MICKMUMPITZ_AI-RENDERER_SMPL_2-0.json`, `260225_MICKMUMPITZ_AI-RENDERER-PREPROCESS_1-0.json`, `..._SMPL_2-0_Runpod.json`, `260303_MICKMUMPITZ_Z-IMAGE_TURBO_CN_1-1.json` (attachments, Patreon). "Install the ComfyUI-GGUF custom nodes by City96"; the 260323 update swaps "Load Diffusion Model" for "Unet Loader (GGUF)". Models: the VACE SkyReels V3 R2V merge (Inner-Reflections), its GGUF quantisation (mickmumpitz), Z-Image Turbo for reference frames, unnamed ControlNets. Passes from Blender: **depth and outline**. |
| [AI Renderer 2.0 project page](https://mickmumpitz.ai/posts/ai-renderer-2-0-153434545) (read) | Two input videos (e.g. line art + depth), "enable Blending in the Blend Outputs node. The example uses line art with 20% depth"; a Settings node sets resolution/aspect; a start image "defines the visual style"; up to four reference images; the standard workflow does up to ~121 frames in one pass; the advanced one iterates with `frames_per_iteration` (4n+1, e.g. 41 ... 81), `num_start_frames` (14 reported good), `total_iterations`, `resume_from_iteration`, one job at a time. |
| [Guide](https://mickmumpitz.ai/guides/ai-powered-3d-animation-rendering) | **Not readable** from this session (fetch error) - see Blockers. |
| [Advanced post](https://mickmumpitz.ai/posts/advanced-turn-3d-151636093) | Gated (Patreon); not read. |

LOKI's graph follows that shape: line art + a share of depth as the VACE control video, the start image as the VACE
reference image, the merged model as GGUF. The creator's own node graph (its custom "Settings", "Blend Outputs",
"Preprocess Control Video" nodes and the iteration pack) was **not** seen and is **not** reproduced.

## 2. ComfyUI's API (from `server.py`, comfyanonymous/ComfyUI @ `7a28332047b6af638dc6c7f72ef3481a718769fd`, 2026-10-20)

Every route is also served under `/api/...` (`add_routes`). The ones LOKI uses (`engine/ai_renderer.py` `Comfy`):

| Route | Source line (server.py) | LOKI's use |
| --- | --- | --- |
| `GET /system_stats` | `@routes.get("/system_stats")` | connection test; `system.comfyui_version`, `devices[0].name / vram_total / vram_free` |
| `GET /object_info` | `@routes.get("/object_info")` (`node_info`: V1 shape; V3 nodes via `GET_NODE_INFO_V1`) | preflight: node classes; a loader's combo list = the model files installed |
| `POST /upload/image` | multipart `image`, `type`, `subfolder`, `overwrite` -> `{name, subfolder, type}`; path checked with `commonpath` | the passes (APNG) and the start image into `input/loki/` |
| `POST /prompt` | `{prompt, client_id, prompt_id}`; `prompt_id` must be a canonical UUID (`validate_job_id`); 400 `{error, node_errors}` | queue the graph |
| `GET /queue` | `{queue_running, queue_pending}`, item[1] = prompt id | queued vs running |
| `GET /history/{prompt_id}` | `{}` until done; then `{id: {prompt, outputs, status: {status_str, completed, messages}}}` (`execution.py` `task_done`) | success / error / `execution_interrupted` |
| `GET /view?filename=&subfolder=&type=` | refuses `/` and `..`, subfolder kept inside the type's folder | fetch the result |
| `POST /interrupt` `{prompt_id}` | interrupts only if that prompt is running | cancel |
| `POST /queue` `{delete: [ids]}` | drops pending items | cancel before it runs |
| `GET /ws?clientId=` | JSON `{"type": "progress", "data": {value, max, prompt_id, node}}` (`main.py` `hijack_progress`), `executing`, `execution_*` | step progress (LOKI's small RFC 6455 reader, best effort) |

Also present but not needed: `/api/jobs`, `/api/jobs/{id}`, `/api/jobs/{id}/cancel`, `/free`, `/models/{folder}`.

## 3. The nodes, verified from source

ComfyUI @ `7a28332` (GPL-3.0) and city96/ComfyUI-GGUF @ `6ea2651e7df66d7585f6ffee804b20e92fb38b8a` (Apache-2.0).
`tests/fixtures/comfyui_object_info.json` is these schemas written out in `/object_info`'s shape (see Blockers: a live
ComfyUI could not be run here).

| Class | File | Inputs LOKI sets (name: type, range) | Outputs |
| --- | --- | --- | --- |
| `UnetLoaderGGUF` | ComfyUI-GGUF `nodes.py` | `unet_name`: combo of folder `unet_gguf` = `models/unet` + `models/diffusion_models`, `.gguf` only (`update_folder_names_and_paths`) | MODEL |
| `CLIPLoader` | `nodes.py` | `clip_name` (folder `text_encoders`), `type` (`"wan"` for umt5-xxl, `"lumina2"` for Z-Image's qwen3-4b), opt. `device` | CLIP |
| `VAELoader` | `nodes.py` | `vae_name` | VAE |
| `ModelSamplingSD3` | `comfy_extras/nodes_model_advanced.py` | `model`, `shift` FLOAT 0-100 | MODEL |
| `CLIPTextEncode` | `nodes.py` | `text`, `clip` | CONDITIONING |
| `LoadImage` | `nodes.py` | `image` (a file in `input/`); reads **every frame** through PyAV (`InputImpl.VideoFromFile(path).get_components()`), Pillow fallback for animated WebP | IMAGE, MASK |
| `ImageBlend` | `comfy_extras/nodes_post_processing.py` | `image1`, `image2`, `blend_factor` 0-1, `blend_mode` (`normal` ...): `image1*(1-f) + image2*f` | IMAGE |
| `WanVaceToVideo` | `comfy_extras/nodes_wan.py` | `positive`, `negative`, `vae`, `width`/`height` INT step 16, `length` INT min 1 **step 4** (default 81), `batch_size`, `strength` 0-1000; optional `control_video`, `control_masks`, `reference_image` | positive, negative, latent, trim_latent (INT) |
| `KSampler` | `nodes.py` | `model`, `seed`, `steps`, `cfg`, `sampler_name`, `scheduler` (lists: `comfy/samplers.py`), `positive`, `negative`, `latent_image`, `denoise` | LATENT |
| `TrimVideoLatent` | `nodes_wan.py` | `samples`, `trim_amount` | LATENT |
| `VAEDecode` | `nodes.py` | `samples`, `vae` | IMAGE |
| `SaveWEBM` | `comfy_extras/nodes_video.py` (experimental) | `images`, `filename_prefix`, `codec` vp9/av1, `fps`, `crf` 0-63; ui `images: [{filename, subfolder, type}]` | IMAGE |
| `ImageFromBatch` | `comfy_extras/nodes_images.py` | `image`, `batch_index`, `length` | IMAGE |
| `SaveImage` | `nodes.py` | `images`, `filename_prefix` | - |
| `Canny` | `comfy_extras/nodes_canny.py` (kornia) | `image`, `low_threshold`, `high_threshold` 0.01-0.99 | IMAGE (white edges on black) |
| `EmptySD3LatentImage` | `comfy_extras/nodes_sd3.py` | `width`, `height` step 16, `batch_size` | LATENT |
| `ModelPatchLoader` | `comfy_extras/nodes_model_patch.py` | `name` (folder `model_patches`); detects Alibaba-PAI's Z-Image Fun ControlNet by its keys | MODEL_PATCH |
| `ZImageFunControlnet` | `nodes_model_patch.py` | `model`, `model_patch`, `vae`, `strength`; opt. `image`, `inpaint_image`, `mask`, `start/end_percent` | MODEL |

**Frame counts.** `WanVaceToVideo` computes `latent_length = ((length - 1) // 4) + 1` and its `length` has `step=4` from 1,
so a full use of the latent is `4n+1` (5, 9, ... 33, 49, 81). LOKI's preflight blocks other counts and names the two
nearest. A control video shorter than `length` is padded with grey 0.5 (no guide), longer is cut - preflight warns.

**Control video polarity.** The node subtracts 0.5 and VAE-encodes the frames as images, so any RGB guide works; LOKI
matches the conventions of VACE's own annotators (ali-vilab/VACE @ `48eb44f`, Apache-2.0): `vace/annotators/depth.py`
min-max normalises MiDaS inverse depth (near = bright) and `scribble.py` outputs white contours on black; ComfyUI's
`Canny` is also white on black.

## 4. LOKI's graphs (`engine/ai_renderer_workflows/`, our own work, AGPL-3.0)

Each file holds the API-format `prompt` plus what LOKI needs to drive it: `params` (UI control -> node + input, with
the node's own range), `uploads`, `models` (file, ComfyUI folder, size, licence, pinned download), `constraints`,
`custom_nodes`, `outputs`. `tests/test_ai_renderer.py` checks every link, every required input and every mapped input
against the fixture.

**`vace_render.json`** - the render (17 nodes):

```
1 UnetLoaderGGUF(wan-14B_vace_skyreels_v3_R2V_e4m3fn_v1-Q4_K_M.gguf) -> 4 ModelSamplingSD3(shift 8) -> 12 KSampler
2 CLIPLoader(umt5_xxl_fp8_e4m3fn_scaled.safetensors, wan) -> 5 CLIPTextEncode(prompt), 6 CLIPTextEncode(negative)
3 VAELoader(wan_2.1_vae.safetensors)
7 LoadImage(depth APNG) ─┐
8 LoadImage(line-art APNG) ─ 9 ImageBlend(image1 = line art, image2 = depth, blend_factor = depth share 0.2, normal)
10 LoadImage(start image) ── reference_image
11 WanVaceToVideo(5, 6, 3, width, height, length=frames, strength, control_video = 9, reference_image = 10)
12 KSampler(4, seed, steps 20, cfg 6, uni_pc, simple, 11.positive, 11.negative, 11.latent)
13 TrimVideoLatent(12, trim_amount = 11.trim_latent) -> 14 VAEDecode(13, 3)
15 SaveWEBM(14, vp9, fps, crf 10)      16 ImageFromBatch(14, 0, 1) -> 17 SaveImage (the thumbnail)
```

The skeleton (loaders -> `ModelSamplingSD3` -> `WanVaceToVideo` -> `KSampler` -> `TrimVideoLatent` -> `VAEDecode` -> save,
uni_pc/simple, the Chinese negative prompt) follows ComfyUI_examples `wan/vace_reference_to_video.json`
(@ `f9431bb`, licence: "Permission to use, copy, modify, and/or distribute these workflows for any purpose"); the
control-video branch, the blend, the GGUF loader and the thumbnail are LOKI's. Guide "line art only" / "depth only"
rewires `control_video` to node 8 / 7 and drops the unused nodes. Without a start image node 10 and `reference_image`
are removed (it is optional). Shift 8 and cfg 6 are starting values, not tuned (Inner-Reflections' Phantom workflow
uses shift 6 / cfg 3 with a low-step model); steps/cfg/shift are exposed.

**`preprocess_lineart.json`** - optional: a beauty pass (e.g. the path-traced frames) -> `Canny` -> PNG frames.

**`zimage_reference.json`** - a reference / start frame from the prompt with core ComfyUI's Z-Image Turbo support (same
nodes and settings as ComfyUI_examples `z_image/z_image_turbo_example.png`'s embedded prompt: UNETLoader, CLIPLoader
`lumina2`, VAELoader `ae.safetensors`, EmptySD3LatentImage, KSampler 9 steps cfg 1 euler/simple). **Z-Image's loader is
in core** (`comfy/supported_models.py` `ZImage`, `comfy/sd.py` QWEN3_4B -> `z_image.te`).

**`zimage_reference_depth.json`** - the same, steered by Forge's first depth frame through `ModelPatchLoader` +
`ZImageFunControlnet` (core) and Alibaba-PAI's Z-Image-Turbo-Fun-Controlnet-Union. The creator's
`Z-IMAGE_TURBO_CN` file suggests the same idea; its graph was not seen.

### Why APNG for the control videos

`LoadImage` hands the file to PyAV; FFmpeg's `apng` demuxer probes an animated PNG at `AVPROBE_SCORE_MAX`
(FFmpeg `libavformat/apngdec.c` @ `e2798d5`), so one `.png` upload carries all frames with no custom node and no video
encoder in LOKI. LOKI writes the APNG itself (`ai_renderer.apng`) because Pillow merges identical consecutive frames,
which would shorten a still shot. **Not verified on a real ComfyUI** (Blocker 3) - if PyAV reads only the first frame
there, the fallback is VideoHelperSuite's `VHS_LoadImagesPath` (a custom pack, not added).

## 5. Model files

| File | ComfyUI folder | Size (bytes) | Repo @ revision | Licence |
| --- | --- | --- | --- | --- |
| `wan-14B_vace_skyreels_v3_R2V_e4m3fn_v1-Q4_K_M.gguf` (default) | `models/unet` | 11,627,589,408 | mickmumpitz/VACE_Skyreels_V3_R2V_Merge-GGUF @ `57045d4` | **none stated** (see Blocker 1) |
| `..._Q3_K_M.gguf` / `Q5_K_M` / `Q8_0` | `models/unet` | 8,624,197,408 / 13,025,472,288 / 18,651,410,208 | same | same |
| (full precision, not used) `wan-14B_vace_skyreels_v3_R2V_e4m3fn_v1.safetensors` / `_fp16_v1` | - | 17.3 GB / 34.7 GB | Inner-Reflections/VACE_Skyreels_V3_R2V_Merge @ `a4473e0` | apache-2.0 (card) |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `models/text_encoders` | 6,735,906,897 | Comfy-Org/Wan_2.1_ComfyUI_repackaged @ `123acf1` `split_files/text_encoders/` | apache-2.0 |
| `wan_2.1_vae.safetensors` | `models/vae` | 253,815,318 | same, `split_files/vae/` | apache-2.0 |
| `z_image_turbo_bf16.safetensors` (alt. `int8_convrot` 6.2 GB) | `models/diffusion_models` | 12,309,866,400 | Comfy-Org/z_image_turbo @ `6fc90a3` | apache-2.0 |
| `qwen_3_4b.safetensors` (alt. `fp8_mixed` 5.6 GB) | `models/text_encoders` | 8,044,982,048 | same | apache-2.0 |
| `ae.safetensors` | `models/vae` | 335,304,388 | same | apache-2.0 |
| `Z-Image-Turbo-Fun-Controlnet-Union.safetensors` | `models/model_patches` | 3,101,572,408 | alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union @ `01c794d` | apache-2.0 |

The text encoder and VAE are not named by the merge's model cards; they are the Wan 2.1 files ComfyUI_examples' VACE
page lists (the merge is a Wan 2.1 VACE 14B model). The GGUF card says to put the file in `models/unet` and load it
with "Unet Loader (GGUF)". The text encoder is ~6.7 GB fp8; on an 8 GB card ComfyUI loads and offloads the parts in
turn - expect it to be slow, and Q3_K_M if memory is short. Preflight only **warns** about memory (it cannot know).

## 6. In LOKI

- **Forge's passes** - `app/ui/forge_passes.js` (`ForgePasses.render / upload / snapshot`): depth (white near, black far
  and background, min-max over the visible meshes' bounds per frame), line art (white on black: depth jumps, silhouette
  and normal creases; width and crease angle adjustable), normals, beauty. Own camera copy (persp / top / front / side /
  current view, the same framing as `forge.js setView`), own render targets and override material; the frame, range,
  playing flag, every transform, override material, background, clear colour, render target and helper visibility
  come back in `finally`. Checked by `tests/test_render_studio_ui.py`.
- **Engine** - `engine/ai_renderer.py`: settings (`harness_data/ai_renderer/settings.json`, default
  `LOKI_COMFYUI_URL` or `http://127.0.0.1:8188`), the client, preflight, the job thread, manifests
  (`harness_data/renders/<job>/manifest.json`, read by Home), presets per project (`renders/.presets/<project>.json`).
  Bridge: `/render/*` (`engine/loki_bridge.py`, bearer token).
- **Render tab** - `app/ui/render_studio.js` + `.css`, registered with `LokiModeBar.register("render", ...)`; Forge's
  Renderer menu has "Send to Render Studio".
- **Setup on the PC** - `tools/setup_comfyui.py` (`--dry-run`, `--install`, `--models --yes-download [--quant Q3_K_M]
  [--zimage]`, `--start` hidden on 127.0.0.1:8188, `--stop`, `--status`, `--uninstall --yes`), all in
  `harness_data/comfyui/`. Never run by tests or in the cloud.

**Reaching the PC from the Mac.** LOKI's peer link (`engine/peers.py`) serves only its fixed, signed `/peer/*` routes;
it is not an HTTP proxy, so ComfyUI is reached by its own address. On the same LAN: start it on the PC with
`--listen <PC's LAN address>` and set `http://<pc>:8188` in Render Studio. An address on a linked peer's host counts as
LOKI's own machine (no upload prompt); any other address needs "Allow uploads to this server". Over the bore relay
(different networks) there is no ComfyUI route yet - **next**: a `/peer/comfy/*` pass-through in peers.py, signed like
the rest, or run Render Studio's jobs as peer jobs on the PC.

## 7. Blockers and open items

1. **Licence of the default model.** The GGUF repo states no licence; the merge repo says apache-2.0, but one parent,
   Skywork/SkyReels-V3-R2V-14B, is under the *Skywork Community License* ("other"; the model page says commercial use is
   allowed under its terms, which are in a PDF not read here). The other parents (Wan2.1-VACE-14B, Phantom) are
   apache-2.0. LOKI never ships the weights; the owner downloads them himself with `--yes-download` after reading the
   Skywork licence. Nothing in the repository is affected.
2. **The creator's guide page could not be fetched**; the advanced post is gated. The Patreon workflow files were not seen
   (the owner does not have them). LOKI's graph is an independent one in the same spirit, not a copy.
3. **No live ComfyUI run** when this was written (the cloud box could not reach PyPI or Hugging Face). **Now done on
   macOS (2026-10-21)**: `tools/setup_comfyui.py --install` builds ComfyUI + ComfyUI-GGUF at the pinned commits
   in their own venv (it came up as **0.42.0** on PyTorch 2.14.1, device **mps**), `--start` runs it on 127.0.0.1:8188,
   and `tests/test_comfyui_live.py` then checks what a fake server cannot (10 checks, all passing):
   - every node class, every input LOKI sets and every input the live server requires **match** the graphs;
   - `tests/fixtures/comfyui_object_info.json` **matches the live schemas** (the fixture was written from the sources, so
     this was worth proving);
   - **`LoadImage` reads every frame of the multi-frame APNG** - a 3-frame APNG uploaded through `/upload/image` came
     back as 3 images, so the control-video path (section 4, "Why APNG") is confirmed on a real server, PyAV included;
   - `Canny` (the preprocess graph) and `ImageBlend` (the line art + depth guide) both run;
   - the real 17-node `vace_render` graph passes the server's own validation: the only complaints are the three model
     files that are not installed here, which is what a fresh install should say. The errors are precise
     (`node 1 (UnetLoaderGGUF): Value not in list unet_name: '...-Q4_K_M.gguf'`), so Render Studio's preflight and the
     job log will name the missing file too.
   Still unverified: an actual generation (the 11.6 GB GGUF, both encoders and a VAE are not on this machine, and no
   NVIDIA GPU here) and speed / memory on the owner's 8 GB card. Both need the PC.

   How to run it again (the Mac, or the PC where ComfyUI always runs):
   `python tools/setup_comfyui.py --install --start && python tests/test_comfyui_live.py`
   (or `LOKI_COMFYUI_URL=http://<pc>:8188 python tests/test_comfyui_live.py`). With no server it skips, so it is safe in CI.

4. **Long shots** (the creator's iterative mode with frame carry-over): not built - it needs the creator's custom pack or
   our own; the graph does single passes (the creator's standard workflow says up to ~121 frames).
5. Only one reference image (VACE's `reference_image` takes the first of a batch); several references (Phantom-style)
   would need `WanPhantomSubjectToVideo` and are not wired.

## 8. Other resources worth using (Mac, 2026-10-21) - CANDIDATES, NOT YET VERIFIED

`mickmumpitz.ai/posts/ai-renderer-2-0-153434545` could **not be fetched from this machine** (this session had no web
access), so nothing below is quoted from it: this is the standing option list for this kind of pipeline, each entry
something to try and then verify. Every one is a ComfyUI custom-node pack or a model, so all of them drop into
`harness_data/comfyui/ComfyUI/custom_nodes/` and none of them changes LOKI's own graphs unless we choose to.

| Resource | What it would give LOKI | Where it touches us |
| --- | --- | --- |
| Kijai's `ComfyUI-WanVideoWrapper` | VACE 14B with block swap / attention modes - the practical way to run this model on an 8 GB card, where core nodes OOM or offload to disk | an alternative to `vace_render.json`'s loaders, same WanVace-style control video + reference image |
| `ComfyUI-VideoHelperSuite` (Kosinkadink) | `VHS_LoadImagesPath` / `LoadVideoUpload` (robust multi-frame in) and **mp4 / h264 output** - ComfyUI core only writes WEBM | the documented fallback if PyAV's APNG probe fails (section 7 Blocker 3); also the only route to mp4 |
| `comfyui_controlnet_aux` (Fannovel16) | more guide types (softedge, normal, MLSD, depth variants) and their preprocessors | today LOKI computes depth and line art itself in `forge_passes.js`; this is the fallback and the extra-pass source |
| `ComfyUI_IPAdapter_plus` (cubiq) | several style references, weighted | section 7 Blocker 5: VACE's `reference_image` takes one image today |
| `ComfyUI-SageAttention` / TeaCache nodes | faster attention and step skipping | speed only; matters on the 8 GB card |
| ComfyUI-Manager | install and update the custom nodes above from the ComfyUI UI | saves the owner hand-cloning packs |
| Core Wan routes (`WanImageToVideo`, `WanFirstLastFrameToVideo`, `WanFunControlToVideo`) | first/last-frame and fun-control conditioning without VACE | an alternative shape for the same job, all in core at our pinned commit |
| LTX-Video / LTX-2 | a much smaller video model - fits 8 GB with room to spare | a second graph (`ltx_render.json`) if the 14B is too slow to be usable, at some cost in quality |
| A rented GPU (RunPod & co.) | the creator ships a RunPod variant of his workflow, so remote is a supported shape | Render Studio's Address field already takes a public URL; it adds the upload consent prompt |

**What was verified instead, on this machine.** A real ComfyUI *can* be installed here from the pinned commits
(`tools/setup_comfyui.py --install`; PyAV, kornia and the GGUF node come with it) and `tests/test_comfyui_live.py` then
checks the things a fake server cannot: the live node schemas against the ones the graphs assume, the fixture against
the live server, and - the Blocker 3 item - whether ComfyUI really reads every frame of the multi-frame APNG the passes
are sent as. Models are not needed for any of that. The test skips cleanly when no server answers, so it is safe in CI
and useful on the PC, where a real ComfyUI runs 24/7:

    python tools/setup_comfyui.py --install --start && python tests/test_comfyui_live.py
