# Third-party code in LOKI

**LOKI must stay private.** Since session 26 LOKI contains code ported from GPL-3.0 projects
(OpenHuman, MuMuAINovel). The owner allows copying from any licence because the repository is
private and LOKI is not distributed. If LOKI is ever published or given to anyone else, the
GPL-3.0 parts (`engine/memory_core.py`, `engine/subagent.py`, `skills/novel-writer/`) must be
removed or rewritten first - or all of LOKI released under GPL-3.0. Each project's licence is kept
next to the code taken from it (`engine/licenses/`, `skills/novel-writer/`).

| Where | What | Licence |
| --- | --- | --- |
| `app/ui/world_noise.js` | GLSL 2D simplex noise (`noise2D.glsl`, Ian McEwan, Ashima Arts) and 2D cellular noise (`cellular2D.glsl`, Stefan Gustavson) from [stegu/webgl-noise](https://github.com/stegu/webgl-noise), used unchanged except one duplicate helper removed | MIT - full text at the top of the file |
| `app/ui/world.js` (water shader) | The depth fade (Beer-Lambert) and noise-displaced shoreline foam are adapted from [paddy-exe/Godot-3D-Stylized-Water](https://github.com/paddy-exe/Godot-3D-Stylized-Water) by Patrick Exner (Godot shading language, rewritten here as WebGL 1 GLSL with an analytic shore distance instead of a depth texture) | MIT, Copyright (c) 2021 Patrick Exner |
| `app/ui/vendor/three/` | [three.js](https://github.com/mrdoob/three.js) r186: the core and the add-ons EffectComposer, RenderPass, UnrealBloomPass, OutputPass (with Pass, ShaderPass, MaskPass, CopyShader, LuminosityHighPassShader, OutputShader), with `'three'` imports rewritten to local paths because the UI's CSP allows no import map | MIT - `app/ui/vendor/three/LICENSE` |
| `app/ui/vendor/babylon/babylon.loki.js` | [Babylon.js](https://github.com/BabylonJS/Babylon.js) 8.9.1 core and CellMaterial, built from source into one slim file (`window.BABYLON`, about 2.9 MB) - LOKI World's default renderer. CellMaterial is patched so per-instance colours reach its shader (`tools/babylon/patch_cell.py`); rebuild steps in `tools/babylon/README.md` | Apache-2.0 - `app/ui/vendor/babylon/LICENSE` |
| `engine/higgsfield.py` | The request protocol of [higgsfield-client](https://github.com/higgsfield-ai/higgsfield-client) (submit to `api.higgsfield.ai/<application>`, poll `status_url`, `Authorization: Key`), re-written with the standard library; no SDK code copied | Apache-2.0 (SDK) |
| `engine/model_setup.py` catalog | [Ternary Bonsai 2](https://huggingface.co/prism-ml) GGUF/MLX weights - downloaded by Ollama/mlx-vlm on the user's machine, never stored in the repo | Apache-2.0 |
| `engine/forecast.py` (optional) | [TimesFM-3](https://github.com/google-research/timesfm) via `pip install timesfm[torch|mlx]`, only when the owner installs it | code Apache-2.0; weights non-commercial |
| `contrib/ruflo/` | see that folder | see that folder |
| `skills/marketing/` | 50 marketing skills (`SKILL.md` + `references/`, evals left out) from [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) at commit `365b412`, unchanged; about 2.8 MB | MIT, Copyright (c) 2025 Corey Haines - `skills/marketing/LICENSE` |
| `engine/runners/scrape.py` (optional) | [Scrapling](https://github.com/D4Vinci/Scrapling) via `pip install "scrapling[rag]"` + `scrapling install`, only when the owner runs `tools/setup_extras.py scrapling`; never its stealth/Cloudflare features | BSD-3-Clause |
| `engine/cli_agents.py`, `engine/workers.py` (optional) | [OpenHands](https://github.com/OpenHands/OpenHands) CLI, run as a separate program (`uv tool install openhands`); the standalone CLI is no longer actively maintained | MIT |
| `capabilities/penecho/`, `engine/mcp_servers.json` (optional) | [PenEcho](https://github.com/penecho/penecho), a separate program (`npm i -g penecho`) LOKI talks to over MCP and http://localhost:3888; no PenEcho code is in LOKI. Session 26 took its canvas <-> agent idea (the answer appears on the canvas beside the user's sketch) for the drawing pad: `sketch_reply` in `engine/loki.py` and `drawReply` in `app/ui/sketch.js`, written for LOKI | AGPL-3.0 (idea only) |
| `capabilities/openhuman/`, `engine/mcp_servers.json` (optional) | [OpenHuman](https://github.com/tinyhumansai/openhuman) `openhuman-core mcp`, a separate program on PATH (its memory and sub-agent logic is now also ported into LOKI - see `engine/memory_core.py` above) | GPL-3.0 |
| `engine/runners/video.py` (optional) | [Remotion](https://github.com/remotion-dev/remotion), fetched by `npx` into each video project the owner asks for; never vendored | Remotion License: free for individuals and companies with up to 3 employees, a company licence otherwise (remotion.dev/license) |
| `capabilities/personalive/` | [PersonaLive](https://github.com/GVCLab/PersonaLive) - an Add-ons card with a link only; LOKI does not install or run it | academic research use only |
| `engine/agents.py` Novel Writer template, `skills/novel-writer/` (SKILL.md, `stages/*/SKILL.md`, `references/prompts.md`) | Session 26: MuMuAINovel's long-story pipeline prompts ([xiamuceer-j/MuMuAINovel](https://github.com/xiamuceer-j/MuMuAINovel) `backend/app/services/prompt_service.py`: world building, characters and organizations, opening outline, outline continuation, chapter, chapter analysis with the foreshadowing tracker) translated from Chinese to English and adapted to files under `novel/` | GPL-3.0 - `skills/novel-writer/LICENSE-MuMuAINovel-GPL-3.0.txt`, `engine/licenses/MuMuAINovel-GPL-3.0.txt` |
| `engine/memory_core.py`, `engine/subagent.py` | Session 26: the design and logic of [OpenHuman](https://github.com/tinyhumansai/openhuman)'s memory host (`crates/openhuman-core/src/memory`: the one `memory` tool recall/fetch/learn/forget, host-stamped learn metadata, `capped_evidence`, the per-turn memory pack and its citations, the tool budget, the scrubbing engine) and sub-agent host (`agent/subagent_host`, `spawn_subagent`: narrowed tools, no nested spawns, one collapsed result, the autonomous iteration-cap lift), ported from Rust to Python | GPL-3.0 - `engine/licenses/OpenHuman-GPL-3.0.txt` |
| `engine/condenser.py`, `engine/stuck.py`, `engine/file_editor.py`, `engine/task_tracker.py`, `engine/command_risk.py` | Session 26: from [OpenHands software-agent-sdk](https://github.com/OpenHands/software-agent-sdk): `LLMSummarizingCondenser` and its summary prompt, `StuckDetector` and its thresholds, the file editor's view / str_replace / insert / undo semantics, the `task_tracker` tool, `PatternSecurityAnalyzer` patterns and the `_normalize` evasion filter - re-written for LOKI's message list on the standard library | MIT, Copyright (c) 2026 OpenHands contributors - `engine/licenses/OpenHands-MIT.txt` |
| `engine/web_reader.py` | Session 26: the non-browser core of [Scrapling](https://github.com/D4Vinci/Scrapling) (`Convertor._extract_content(main_content_only)`, `_strip_noise_tags`, `_sanitize_for_ai` hidden-content and zero-width filters, `get_all_text`, the browser-like headers and search referer) re-written on `urllib` + `html.parser` so pages read without any add-on; the Scrapling add-on stays the upgrade | BSD-3-Clause, Copyright (c) 2024 Karim Shoair - `engine/licenses/Scrapling-BSD-3-Clause.txt` |

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
