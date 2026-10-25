# Tools LOKI can build in (licence-checked, 2026-10-25)

LOKI is AGPL-3.0: code under MIT / Apache-2.0 / BSD / ISC / MPL-2.0 / GPL-3.0 / AGPL-3.0 can be vendored; model
weights must allow commercial use with no revenue cap and no region exclusion. Licences were read from each repo's
LICENSE file (code) and README / model card (weights) on 2026-10-25; star counts are approximate.

## Licence traps (do not build in)
MMAudio (weights CC-BY-NC), Sony Woosh (CC-BY-NC), ThinkSound (no commercial use), YuE2 (CC-BY-NC), Higgs Audio v3
(non-commercial), fish-speech (community licence), IndexTTS2 (bilibili licence), NeuTTS Air (custom), audiocraft /
MusicGen / AudioGen (weights CC-BY-NC), F5-TTS (weights CC-BY-NC), HunyuanVideo-Foley and HY-Motion (Tencent
regional), MotionLCM / GENMO / GVHMR / GIMM-VFI (non-commercial), MoMask / MDM / MotionGPT (SMPL / HumanML3D data),
Kimodo SMPLX variant (R&D only - the SOMA weights are fine), Orpheus TTS (Llama licence), TEXGen (no licence),
godot-mcp-pro (says proprietary), SkinTokens and Make-It-Animatable (training-data provenance). rfxgen (zlib) and jsfxr
(Unlicense) are fine to run as separate tools.

## Audio
| Pick | Licence (code / weights) | Fits 8 GB / Mac | LOKI use |
|---|---|---|---|
| [MOSS-SoundEffect v2.0](https://github.com/OpenMOSS/MOSS-TTS) | Apache / Apache | likely (1.3B) | text -> sound effects, the commercial-OK SFX model |
| [DiffRhythm](https://github.com/ASLP-lab/DiffRhythm) | Apache / Apache | yes, `--chunked` | songs with vocals, next to ACE-Step |
| [Dia](https://github.com/nari-labs/dia) | Apache / Apache | ~4.4 GB | multi-speaker NPC dialogue with laughs, coughs |
| [KittenTTS](https://github.com/KittenML/KittenTTS) | Apache / Apache | CPU | tiny placeholder voice on the Mac |
| [rfxgen](https://github.com/raysan5/rfxgen) / [jsfxr](https://github.com/chr15m/jsfxr) | zlib / Unlicense | CPU | instant retro SFX (jump, coin, hit) |

## 2D art
| Pick | Licence | LOKI use |
|---|---|---|
| [Wan2.2 TI2V-5B](https://github.com/Wan-Video/Wan2.2) | Apache | first/last-frame sprite animation (8 GB with ComfyUI offload) |
| [Practical-RIFE](https://github.com/hzwer/Practical-RIFE) | MIT | in-betweens between sprite keyframes |
| [AnimatedDrawings](https://github.com/facebookresearch/AnimatedDrawings) | MIT (weights included) | rig a drawn character, BVH motion -> sprite sheet |
| [proper-pixel-art](https://github.com/KennethJAllen/proper-pixel-art) | MIT | snap "fake" AI pixel art to a true grid |
| [pyxelate](https://github.com/sedthh/pyxelate) / [hitherdither](https://github.com/hbldh/hitherdither) | MIT | more palette fitting and dithering modes |
| [libimagequant](https://github.com/ImageOptim/libimagequant) | GPL-3.0+ | best palette quantisation |
| [rembg](https://github.com/danielgatis/rembg) | MIT (avoid its bria model) | sprite cut-outs (BiRefNet) |
| [WaveFunctionCollapse](https://github.com/mxgmn/WaveFunctionCollapse) | MIT | tilemaps and levels from a sample |
| [ComfyUI-seamless-tiling](https://github.com/spinagon/ComfyUI-seamless-tiling) | GPL-3.0 | seamless textures and tiles |
| [DeepBump](https://github.com/HugoTini/DeepBump) / [Laigter](https://github.com/azagaya/laigter) | GPL-3.0 | normal maps for Godot 2D lighting |

## 3D and animation
| Pick | Licence | LOKI use |
|---|---|---|
| [meshoptimizer / gltfpack](https://github.com/zeux/meshoptimizer) | MIT | LODs + compression on every Forge export |
| [xatlas](https://github.com/jpcy/xatlas) | MIT | UV unwrap before baking |
| [AutoRemesher](https://github.com/huxingyi/autoremesher) | MIT (2026) | quad retopology |
| [QuadWild-BiMDF](https://github.com/cgg-bern/quadwild-bimdf) / [Instant Meshes](https://github.com/wjakob/instant-meshes) | GPL-3.0 / BSD | higher-quality / fast quads |
| [UniRig](https://github.com/VAST-AI-Research/UniRig) | MIT / MIT | auto skeleton + skinning (8 GB minimum) |
| [MV-Adapter](https://github.com/huanngzh/MV-Adapter) | Apache | texture an existing mesh |
| [Kimodo](https://github.com/nv-tlabs/kimodo) + [SOMA-X](https://github.com/NVlabs/SOMA-X) | Apache / NVIDIA Open Model (SOMA weights) | text -> motion (text encoder on CPU for 8 GB) |
| [FreeMoCap](https://github.com/freemocap/freemocap) / [MediaPipe](https://github.com/google-ai-edge/mediapipe) | AGPL / Apache | video -> motion |
| [ufbx](https://github.com/ufbx/ufbx) | MIT | FBX reading |

## Marketing
MoviePy (MIT), PyAV (BSD), PySceneDetect (BSD), auto-editor (Unlicense, as a tool), faster-whisper / whisper.cpp /
WhisperX / stable-ts (MIT / MIT / BSD / MIT) for captions, pysubs2 (MIT), satori + resvg or Playwright for Steam
capsule art, game-ci/steam-deploy and itch.io butler (MIT), atproto / Mastodon.py / PRAW / discord-webhook (MIT / MIT /
BSD / MIT) for direct posting next to Postiz.

## Godot
GDQuest GDScript-formatter, gdtoolkit (gdlint), gdUnit4, GUT, godot-mcp-runtime - all MIT.

## Build next
1. meshoptimizer LODs on Forge exports. 2. xatlas unwrap. 3. gdUnit4 / GUT + formatter + gdlint for generated games.
4. faster-whisper + pysubs2 captions. 5. MOSS-SoundEffect. 6. rembg + proper-pixel-art cleanup. 7. DeepBump normals.
8. PySceneDetect + MoviePy trailer rough cut. 9. UniRig. 10. Kimodo (SOMA).
