"""Bundle Material Maker's node definitions for Forge's Materials side.

    python tools/import_mm_nodes.py <material-maker checkout> [node names...]

Material Maker (github.com/RodZill4/material-maker, MIT, Rodolphe Suescun and contributors) describes each
node as a .mmg JSON file: parameters, inputs, outputs and GLSL ("shader_model"). Forge's compiler
(app/ui/forge_mm.js, a port of material_maker/engine/nodes/gen_shader.gd) runs those definitions unchanged
in WebGL2. The window may only load .js/.json/.css/.png files, so this tool copies the chosen .mmg files
verbatim into app/ui/vendor/material_maker/nodes.json, with Material Maker's shader_functions.tres text
(rand, rand2, rand3, hsv) and its licence. Run it again with more names to grow the library (no code change):

    git clone --depth 1 --filter=blob:none --sparse https://github.com/RodZill4/material-maker mm
    (cd mm && git sparse-checkout set addons/material_maker/nodes addons/material_maker/shader_functions.tres)
    python tools/import_mm_nodes.py mm                  # the starter set below
    python tools/import_mm_nodes.py mm bricks3 cairo    # starter set + more
Nodes that need Material Maker's buffers, iterations, SDF/3D types or curve/polygon editors are refused (they
stay for "Open in Material Maker").
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "app" / "ui" / "vendor" / "material_maker"
STARTER = ["perlin", "fbm2", "voronoi", "wavelet_noise", "noise", "bricks2", "shape", "gradient", "circular_gradient",
           "radial_gradient", "uniform", "uniform_greyscale", "colorize", "blend", "invert", "brightness_contrast",
           "adjust_hsv", "tones_map", "math", "warp", "transform2", "tile2x2", "combine", "decompose", "mirror",
           "scale", "rotate", "repeat"]
CATEGORY = {"perlin": "Noise", "fbm2": "Noise", "voronoi": "Noise", "wavelet_noise": "Noise", "noise": "Noise",
            "bricks2": "Patterns", "shape": "Patterns", "gradient": "Patterns", "circular_gradient": "Patterns",
            "radial_gradient": "Patterns", "uniform": "Simple", "uniform_greyscale": "Simple",
            "tile2x2": "Transform", "transform2": "Transform", "mirror": "Transform", "scale": "Transform",
            "rotate": "Transform", "repeat": "Transform", "warp": "Transform"}
TYPES_OK = {"f", "rgb", "rgba"}
PARAMS_OK = {"float", "enum", "boolean", "color", "gradient", "size"}


def usable(model: dict) -> str:
    """'' when Forge's compiler can run this shader model, else why not."""
    for i in model.get("inputs", []):
        if i.get("type") not in TYPES_OK:
            return "input type %s" % i.get("type")
        if i.get("function"):
            return "function inputs"
    for o in model.get("outputs", []):
        if o.get("type") not in TYPES_OK:
            return "output type %s" % o.get("type")
    for p in model.get("parameters", []):
        if p.get("type") not in PARAMS_OK:
            return "parameter type %s" % p.get("type")
    return ""


def shader_functions(checkout: Path) -> str:
    text = (checkout / "addons" / "material_maker" / "shader_functions.tres").read_text(encoding="utf-8")
    found = re.search(r'text = "(.*)"\s*$', text, re.S)
    return found.group(1).replace('\\"', '"') if found else ""


def main(argv: list) -> int:
    if not argv:
        print(__doc__)
        return 2
    checkout = Path(argv[0])
    nodes_dir = checkout / "addons" / "material_maker" / "nodes"
    names = STARTER + [n for n in argv[1:] if n not in STARTER]
    out = {"_meta": {"source": "https://github.com/RodZill4/material-maker", "licence": "MIT",
                     "copyright": "Copyright (c) 2018-present Rodolphe Suescun and contributors"},
           "_shader_functions": shader_functions(checkout), "nodes": {}}
    try:
        out["_meta"]["commit"] = subprocess.run(["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"],
                                                capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        pass
    for name in names:
        path = nodes_dir / (name + ".mmg")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print("  skip %s: %s" % (name, exc))
            continue
        why = "not a shader node" if data.get("type") != "shader" else usable(data.get("shader_model", {}))
        if why:
            print("  skip %s: %s" % (name, why))
            continue
        data["category"] = CATEGORY.get(name, "Filters")
        out["nodes"][name] = data
        print("  + %s" % name)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "nodes.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    lic = checkout / "LICENSE.md"
    if lic.is_file():
        (OUT / "LICENSE").write_text(lic.read_text(encoding="utf-8"), encoding="utf-8")
    print("%d nodes -> %s" % (len(out["nodes"]), OUT / "nodes.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
