# Forge Render: path tracing in LOKI's window

Owner, 2026-10-21: LOKI is becoming *"a game engine, render studio, AI farm hive"*. Forge (the 3D modeller) now
has a real path-traced render, physically based light that bounces, inside the window. No external renderer, no
downloads, no server.

Code: `app/ui/forge_render.js` (loaded by `index.html` after the other `forge_*.js`). Libraries:
`app/ui/vendor/pathtracer/` (three-gpu-pathtracer) and `app/ui/vendor/three-mesh-bvh/`. Test:
`tests/test_forge_render_ui.py` (in `tools/ship.py` SUITES).

## Where it is

| | |
|---|---|
| **Renderer > Path Traced Preview** (viewport menu bar) | The viewport refines itself while the camera is still (after ~0.2 s); any change (orbit, edit, select, a new object) shows the normal raster frame again at once, and tracing restarts when it stops. Click again to turn it off (ticked while on). Command `renderPreview`. |
| **Renderer > Render...** | The Render window (drag by its title, Esc / x closes). Command `renderDialog`. |
| `window.ForgeRender` | The same renderer for scripts and the Render Studio tab, described below. |

Both commands are in `FORGE_PRO_CMDS`, so the Hotkey Editor can bind them like any other.

## The Render window

| Setting | What it does |
|---|---|
| Resolution | Viewport size / 1280x720 / 1920x1080 / 3840x2160 / Custom (width x height, up to 8192) |
| Camera | Current view, or persp (framed 3/4 view of everything), top / front / side (orthographic, framed) |
| Samples | Paths per pixel, the target. More is cleaner and slower. |
| Bounces | How many times light may bounce (transmission gets at least 4) |
| Denoise + Strength | An edge-aware smoothing filter on the result (the library's `DenoiseMaterial`, glslSmartDeNoise). Strength sets its edge threshold. |
| Light sampling | Multiple importance sampling (MIS), on by default: cleaner light from the environment. Off gives a much smaller shader that starts much sooner on a slow / software GPU, with more noise. |
| Environment | Made in code, no image files: **Studio** (dark floor, grey walls, a large soft box overhead, a key strip to one side, a rim behind), **Sky with sun** (blue sky, sun disc and glow, warm ground), **Studio gradient**, **Neutral grey**. Intensity and Rotation (around up). |
| Background | Environment / Colour (picker) / Transparent (PNG alpha) |
| Floor | None / Grey floor / Shadow catcher (the path tracer's `matte`: shows the background, keeps the shadows). Placed just under the scene's bounding box. |
| Exposure, Tone mapping | AgX (default), ACES Filmic, Neutral, Reinhard, Linear, None. Applied in Forge Render's own output pass (three.js's own tone curves), so the canvas, the PNG and the API all match. |
| Depth of field | Focus on **the selection** (its centre), the view's centre or the scene's centre, and an **f-stop** (lower is blurrier). Uses the library's `PhysicalCamera`. |
| Viewport preview: Resolution | 1/4, 1/2 (default), 3/4 or full of the viewport's pixels for Path Traced Preview |

The buttons are **Render**, **Stop** (keeps what has been rendered), **Save PNG** (downloads
`forge-render-YYYYMMDD-hhmmss.png`; works mid-render too) and **Preview in viewport**. The status line shows
`samples / target · seconds · width x height` and a progress bar. Settings are remembered on this machine
(`localStorage` `loki-forge-render`).

### What is rendered

Every **visible** mesh in Forge's scene (`forge.view.tree.api.sceneNodes()`, including the working object
`forge.view.meshObj()`), at its world transform. Hidden nodes, hidden parents, hidden display layers and templated
objects are left out, and so are overlays (selection boxes, the smoothing cage, the grid, the brush ring). The render
works on **copies**: geometry is shared read-only, materials are translated, and Forge's scene is never changed.

| Forge material | In the render |
|---|---|
| MeshStandard / MeshPhysical (Forge's default, loaded glTF, Material Maker maps) | as it is (colour, roughness, metalness, maps, vertex colours, transmission, ...) |
| Matcap (the sculpt look) | clay: a matte standard material in the matcap's tint |
| Basic / unlit with a texture (image planes) | emissive: the picture shows at its own brightness |
| Basic without a texture | matte standard in its colour |
| Phong / Lambert / Toon | standard, roughness from shininess (Phong) or matte |

The lights in the render are the environment (and the floor's bounce). Forge's viewport lights (the camera-attached
default lighting) are not used. They are for modelling, not a lighting setup.

## window.ForgeRender (for Render Studio and scripts)

```js
ForgeRender.isAvailable()          // true when WebGL2 + float render targets (EXT_color_buffer_float) exist

const job = ForgeRender.render({
  width: 1920, height: 1080,       // or res: "viewport" | "1280x720" | "1920x1080" | "3840x2160"
  samples: 256, bounces: 5,
  environment: "studio",           // or { type: "sky" | "studio" | "gradient" | "neutral", intensity: 1.2, rotation: 90 }
  background: "environment",       // "color" (+ backgroundColor: "#203040"), "transparent", or a "#rrggbb" string
  floor: "none",                   // "grey" | "catcher"
  exposure: 1, toneMapping: "agx", // "aces" | "neutral" | "reinhard" | "linear" | "none" ("ACES", "AgX" accepted)
  dof: false,                      // or true + fStop / focus, or { enabled: true, fStop: 2, focus: "selection" }
  camera: "current",               // "persp" | "top" | "front" | "side"
  denoise: true, denoiseStrength: 0.5, mis: true,
  onProgress: (job) => {},         // called after each step
});
job.progress   // 0..1
job.samples    // samples so far (job.target = the goal)
job.canvas     // the live picture (updated a few times a second)
job.stop()     // finish early, keeping what is there
const r = await job.done;          // { canvas, dataURL (PNG), blob, samples, ms, width, height, stopped }

const seq = ForgeRender.renderSequence({ ...sameOptions, start: 1, end: 24, step: 1, onFrame: (r, seq) => {} });
seq.progress; seq.frame; seq.stop();
const { frames, ms, stopped } = await seq.done;   // frames[i] is a render() result plus .frame
```

Missing options come from the Render window's saved settings, then the defaults. Renders queue: a second
`render()` starts when the first ends. `renderSequence` walks the Time Slider (`tree.api.setFrame`, which
evaluates the keys of `app/ui/forge_anim.js` / `forge_scene.js`), renders each frame and then puts the frame, range,
play state and every node's transform back exactly as they were, so the scene is never changed permanently.
Other helpers: `setPreview(on)`, `togglePreview()`, `previewOn()`, `openDialog(show)`, `savePNG()`, `settings()`,
`defaults()`, `meshes()` (what would be rendered).

## How it works

- **One WebGL context, one path tracer.** Everything draws with Forge's own `WebGLRenderer` (`view.renderer`, now
  exposed by `forge.js` with `view.scene`). The path-tracing shader is very large and compiling it is the slow part
  (a second or so on a GPU, ~25 s on SwiftShader with MIS, ~4 s without), so a second context or a second path tracer
  would pay that again. The preview and final renders take turns with the one `WebGLPathTracer`, and the preview
  pauses while a final render runs.
- **Final renders** set the path tracer's targets to the chosen size, trace a few samples per animation frame (the
  count adapts to keep the frame time near 16-24 ms, so the window never freezes; large images are traced in 256 px
  tiles), and read the result back through an 8-bit output target into a 2D canvas a few times a second for the
  live picture. The read-back happens about 4 times a second rather than every frame, because each one stalls the GPU.
- **The output pass** (in `forge_render.js`): optional denoise into a float target, then exposure, the chosen
  tone curve (three.js's `tonemapping_pars_fragment`), and sRGB, into the canvas or the read-back target.
- **The scene** is rebuilt only when something it depends on changes (a hash of each mesh's geometry version,
  transform and material version plus the environment settings). Moving only the camera keeps the BVH.

## Licences

| Where | What | Licence |
|---|---|---|
| `app/ui/vendor/pathtracer/` | three-gpu-pathtracer **v0.0.27** (commit `afc7db62`), Garrett Johnson | MIT, `LICENSE` there |
| `app/ui/vendor/three-mesh-bvh/` | three-mesh-bvh **v0.9.16** (commit `79dd8417`), Garrett Johnson | MIT, `LICENSE` there |
| inside `pathtracer/materials/fullscreen/DenoiseMaterial.js` | glslSmartDeNoise, Michele Morrone | BSD-2-Clause, notice kept in the file |

Both are also rows in `docs/THIRD_PARTY.md`. Compatibility: the pathtracer's peer range is `three >= 0.185` and
`three-mesh-bvh >= 0.9.15`; LOKI vendors three r187dev, so both fit.

### Re-vendoring (`tools/vendor_pathtracer.py`)

npm is not used (and was not reachable). Clone both repositories into fresh directories, check out the tags, and
run the script. It only reads the clones and never runs their install or build scripts:

```
git clone https://github.com/gkjohnson/three-gpu-pathtracer.git <dir>/gpt && git -C <dir>/gpt checkout v0.0.27
git clone https://github.com/gkjohnson/three-mesh-bvh.git <dir>/bvh && git -C <dir>/bvh checkout v0.9.16
python tools/vendor_pathtracer.py --pathtracer <dir>/gpt --bvh <dir>/bvh
```

It copies `src/**/*.js` (leaving out `webgpu/`, `workers/`, typings and the pathtracer's `utils/UVUnwrapper.js`,
which needs xatlas-web + a .wasm), rewrites `'three'`, `'three/examples/jsm/...'` / `'three/addons/...'` and
`'three-mesh-bvh'` to relative paths into `app/ui/vendor/` (the page CSP is `script-src 'self'` with no import map),
expands three-mesh-bvh's `*.template.js` files into the `.generated.js` / `_indirect.generated.js` pair its rollup
build makes (the same `@if INDIRECT` / `@echo INDIRECT_STRING` directives, without npm), copies the LICENSE files, and
then checks that every relative import resolves.

### Patches (API drift against three r187dev; applied by the script, each must match exactly once)

1. `pathtracer/uniforms/EquirectHdrInfoUniform.js`: `Source` -> `TextureSource` (renamed in three r186; the old
   name still works but warns).
2. `pathtracer/core/PathTracingSceneGenerator.js`: BVH option `maxLeafTris: 1` -> `targetLeafSize: 1` (renamed in
   three-mesh-bvh 0.9; the old name warns).

Nothing else was changed. `forge_render.js` calls one internal method, `WebGLPathTracer._pathTracer.setSize(w, h)`,
because `WebGLPathTracer` has no public way to render at a size other than the canvas's. Check it when updating the
library.

## Limits (kept honest)

- **Needs WebGL2 with float render targets** (`EXT_color_buffer_float`). Every current desktop browser engine LOKI's
  window uses has it. Without it `isAvailable()` is false, the window says so, and nothing else in Forge is affected.
- **Speed is the GPU's.** On a real GPU a 1080p frame reaches a clean picture in tens of seconds to a few minutes.
  On a software renderer (SwiftShader in the tests) the first compile takes 4-25 s and a sample of a 64 px image a
  few ms. 4K at high sample counts is slow everywhere, but it never blocks the window and Stop keeps the partial result.
- **The deprecated WebGL path tracer.** Upstream 0.0.25+ marks `WebGLPathTracer` deprecated in favour of a WebGPU
  one. Forge renders with WebGL (`WebGLRenderer`), so the WebGL one is the fit today; it still ships in 0.0.27 and
  logs one deprecation warning. Moving to `WebGPUPathTracer` means a WebGPU renderer for Forge (`three/webgpu`, not
  vendored), which is a separate job.
- **The denoiser is a filter, not a learned denoiser.** The library's OIDN denoiser (`oidn-web`, WebGPU + model
  weights) is not vendored.
- **No lights from the scene yet.** Forge has no light objects; the environment (+ floor) lights the render. When
  Forge gains lights, `buildScene` can copy Directional / Point / Spot / RectArea lights, which the path tracer supports.
- Skinned and instanced meshes are skipped (the viewport does not make them today).
- `renderSequence` renders frames one after another at full quality, with no motion blur.

## Test

`tests/test_forge_render_ui.py`, headless Chromium + SwiftShader, about 20 s here (limit 55 s): offline checks (no
bare imports left, LICENSE files, THIRD_PARTY rows, the script tag, no product names), then a cube, the Renderer
menu entries, the window renders 64x64 with the samples climbing, Stop, a non-blank picture, Save PNG's data URL,
`ForgeRender.render()`'s job and result, `renderSequence` restoring the Time Slider, the viewport preview converging
and restarting on a camera move, the menu tick, and no page errors. It runs with Light sampling off so the software
GPU's compile stays short, and skips (saying why) when the browser has no WebGL2 float targets.
