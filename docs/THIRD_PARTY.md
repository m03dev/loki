# Third-party code in LOKI

| Where | What | Licence |
| --- | --- | --- |
| `app/ui/world_noise.js` | GLSL 2D simplex noise (`noise2D.glsl`, Ian McEwan, Ashima Arts) and 2D cellular noise (`cellular2D.glsl`, Stefan Gustavson) from [stegu/webgl-noise](https://github.com/stegu/webgl-noise), used unchanged except one duplicate helper removed | MIT - full text at the top of the file |
| `app/ui/world.js` (water shader) | The depth fade (Beer-Lambert) and noise-displaced shoreline foam are adapted from [paddy-exe/Godot-3D-Stylized-Water](https://github.com/paddy-exe/Godot-3D-Stylized-Water) by Patrick Exner (Godot shading language, rewritten here as WebGL 1 GLSL with an analytic shore distance instead of a depth texture) | MIT, Copyright (c) 2021 Patrick Exner |
| `app/ui/vendor/three/` | [three.js](https://github.com/mrdoob/three.js) r186: the core and the add-ons EffectComposer, RenderPass, UnrealBloomPass, OutputPass, FXAAPass, ShaderPass, Sky, Reflector (+ their shaders), with `'three'` imports rewritten to local paths because the UI's CSP allows no import map | MIT - `app/ui/vendor/three/LICENSE` |
| `engine/higgsfield.py` | The request protocol of [higgsfield-client](https://github.com/higgsfield-ai/higgsfield-client) (submit to `api.higgsfield.ai/<application>`, poll `status_url`, `Authorization: Key`), re-written with the standard library; no SDK code copied | Apache-2.0 (SDK) |
| `engine/model_setup.py` catalog | [Ternary Bonsai 2](https://huggingface.co/prism-ml) GGUF/MLX weights - downloaded by Ollama/mlx-vlm on the user's machine, never stored in the repo | Apache-2.0 |
| `engine/forecast.py` (optional) | [TimesFM-3](https://github.com/google-research/timesfm) via `pip install timesfm[torch|mlx]`, only when the owner installs it | code Apache-2.0; weights non-commercial |
| `contrib/ruflo/` | see that folder | see that folder |

MIT notice for Godot-3D-Stylized-Water (adapted code in app/ui/world.js):

    Copyright (c) 2021 Patrick Exner
    Permission is hereby granted, free of charge, to any person obtaining a copy of this
    software and associated documentation files (the "Software"), to deal in the Software
    without restriction, including without limitation the rights to use, copy, modify, merge,
    publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
    to whom the Software is furnished to do so, subject to the following conditions:
    The above copyright notice and this permission notice shall be included in all copies or
    substantial portions of the Software.
    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.
