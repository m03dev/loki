# The Tool Shelf

Open-source game-dev tools LOKI installs when the owner says so and runs on workspace files (engine/toolshelf.py,
Settings > Add-ons, the agents' toolshelf tool, loki-make shelf). One JSON recipe per tool in engine/toolshelf/.

LOKI (AGPL-3.0 Python app, Mac mini 16 GB Apple Silicon + Windows PC RTX 3070 Ti 8 GB) installs each tool into its OWN
folder <data>/tools/<id>/ (own Python venv when it needs pip, so torch versions never clash) and runs it as a
subprocess from a command TEMPLATE. Nothing is guessed: every install step and command line must be checked against
the tool's repo (README, CLI argparse/click source, setup files) - say where in `verified_from`.

{
  "id": "gltfpack",                       # kebab-case, unique
  "name": "gltfpack (meshoptimizer)",
  "area": "3d",                           # audio | 2d | 3d | animation | video | marketing | godot
  "what": "one plain sentence: what it does for a game dev",
  "repo": "https://github.com/zeux/meshoptimizer",
  "license": "MIT",                       # the CODE licence, from the LICENSE file
  "weights": null,                        # or {"name": "...", "license": "...", "commercial": true/false, "url": "..."}
  "hardware": "cpu",                      # cpu | gpu (CUDA) | gpu-or-mps | mps-ok ; plus "vram_gb": 8 when known
  "platforms": ["darwin", "win32", "linux"],   # where it can run
  "install": {
     "kind": "pip" | "git-pip" | "release" | "npm" | "git" | "comfyui" | "manual",
     "python": "3.11",                    # if it needs a specific Python (else omit)
     "pip": ["moviepy==2.1.2"],           # pip requirements (kind pip / git-pip); prefer exact versions from PyPI
     "pip_platform": {"win32": [...], "darwin": [...]},   # optional extras per OS (e.g. torch CUDA index)
     "pip_index": {"win32": "https://download.pytorch.org/whl/cu124"},  # optional
     "git": "https://github.com/x/y", "ref": "v1.2.3 or a commit",      # kind git / git-pip: clone into <tool>/src
     "requirements_file": "requirements.txt",    # inside the clone, if that is how it installs
     "release": {"repo": "owner/name", "tag": "v0.22", "assets": {"darwin": "gltfpack-macos.zip", "win32": "gltfpack-windows.zip", "linux": "gltfpack-ubuntu.zip"}, "exe": "gltfpack"},
     "npm": ["gltfpack@0.22.0"],
     "after": [["{python}", "-m", "something", "download"]],   # steps after install, argument lists, no shell
     "models": [{"url": "https://huggingface.co/...", "to": "models/x.onnx", "size_mb": 100}],
     "manual": "only for kind manual: what the owner must do"
  },
  "check": ["{exe}", "-h"],               # a quick command that succeeds when installed (or ["{python}", "-c", "import x"])
  "actions": {
     "optimize": {
        "what": "one sentence",
        "cmd": ["{exe}", "-i", "{input}", "-o", "{output}", "-si", "{ratio}"],
        "args": {
           "input":  {"type": "file", "exts": [".glb", ".gltf"], "what": "the model"},
           "output": {"type": "out", "ext": ".glb", "default": "{input_stem}-lod.glb"},
           "ratio":  {"type": "number", "default": 0.5, "min": 0.01, "max": 1, "what": "share of triangles kept"}
        },
        "timeout": 600
     }
  },
  "notes": "VRAM, gotchas, licence traps",
  "verified_from": "README.md 'Usage' + gltf/cli.cpp argument parser at <commit>"
}

Placeholders a command may use: {python} (the tool's venv Python), {exe} (the release/npm executable), {src} (the git
clone), {tool} (the tool's folder), {models} (<tool>/models), and any arg name. Arg types: file (must exist),
out (a path LOKI makes in the workspace), text, number, int, bool (rendered as a flag: give "flag": "--x"), choice
(give "choices": [...]). Optional args: "optional": true; a flag-style arg renders as ["--name", value] when given via
"flag": "--name". Keep each tool's actions to the 1-3 things a game dev actually uses.

Also: {loki_python} and {runners} (LOKI's Python and engine/runners - e.g. runners/godot_addon.py puts a Godot add-on
into a project and enables it), {bin} (the venv's bin / Scripts folder). An action with "ask": true (publishing a
post, changing an agent harness's skills) shows the owner the exact arguments first. "env_needed" names the
settings a tool reads (keys never go in args). tests/test_toolshelf.py validates every recipe and builds every action.
