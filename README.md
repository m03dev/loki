# LOKI

A free, open-source creation app for your own machines. Give it one goal - "model and render a low-poly campfire",
"make a turnaround sheet for this character" - and its driver plans the job, works through it by itself for as long
as it takes, checks every step, and shows you the results. It runs on free models only (NVIDIA's free API, Groq,
OpenRouter's free models, local Ollama / llama.cpp) and rolls over to the next one when a free tier is used up.

- **Driver** - `lokid`, a small Rust daemon (`crates/`). Keeps working when the window is closed; resumes after a
  restart.
- **Window** - jobs, approvals ("For you"), results as thumbnails, which models answer.
- **Art tools** - Blender, ComfyUI (images, image-to-3D, video) on your GPU machine.

## Install

```bash
git clone https://github.com/m03dev/loki && cd loki
./setup.sh        # macOS / Linux
setup.bat         # Windows
```

Put a free key in `harness_data/.env` (`NVIDIA_API_KEY=...` from build.nvidia.com), then start LOKI
(`Loki.cmd` on Windows, Loki in ~/Applications on macOS). The first start builds the driver; if Rust is missing it
is installed into `harness_data/toolchain`.

## Develop

```bash
cargo test -q
cargo run -p lokid -- probe
```

The previous LOKI is kept as the tag `legacy-v1`. License: AGPL-3.0.
