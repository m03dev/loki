"""What a "For you" card shows: exactly what will run, in a few short lines (owner 2026-10-27: "they need to show what
the prompt was and a lot more detail on what they're asking for - if it's a 3D model what images they're using, what
prompts and what engine, what their plan is - brief, very minimal, to the point").

plan(item) -> {"prompt": the FULL words the engine gets (style words the code adds included),
               "negative": what is kept out, "inputs": [image paths it uses], "engine": "FLUX.2 klein (NVIDIA)" ...,
               "output": what comes out, "plan": one line}
Nothing is drawn or sent: engines are read from the same order the tools will try (imagegen.plan_order,
forge3d.plan).
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

IMAGE_ENGINES = {"sdcpp": "Z-Image Turbo (local, stable-diffusion.cpp)", "mflux": "Z-Image Turbo (local, MLX)",
                 "zimage": "Z-Image Turbo (local, diffusers)", "qwen": "Qwen-Image 2.1 (ModelScope)",
                 "nvidia": "FLUX.2 klein (NVIDIA)", "huggingface": "FLUX.1 dev (Hugging Face)",
                 "local": "the PC's own image model"}
MODEL_ENGINES = {"trellis2": "TRELLIS.2 (ComfyUI on the PC)", "pixal3d": "Pixal3D (ComfyUI)",
                 "hunyuan": "Hunyuan3D 2.1", "triposr": "TripoSR (local)", "online": "online 3D service",
                 "lift": "depth lift (fallback)"}


def _image_order() -> list:
    try:
        spec = importlib.util.spec_from_file_location("loki_imagegen_plan", HERE / "runners" / "imagegen.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return list(mod.plan_order().get("order") or [])
    except Exception:  # noqa: BLE001 - the card still shows the rest
        return []


def _engine(order: list, names: dict) -> str:
    if not order:
        return "no engine ready on this machine"
    first = names.get(order[0], order[0])
    return first + ("  (then %s)" % ", ".join(names.get(b, b) for b in order[1:3]) if len(order) > 1 else "")


def _imgs(*vals) -> list:
    out = []
    for v in vals:
        for x in ([v] if isinstance(v, str) else (v or [])):
            if isinstance(x, str) and x.strip() and x not in out:
                out.append(x.strip())
    return out


def plan(it: dict) -> dict:
    tool, a = str(it.get("tool") or ""), dict(it.get("args") or {})
    role = it.get("who") or "An agent"
    if tool == "make_image":
        import art_direction  # pylint: disable=import-outside-toplevel
        full, neg = art_direction.direct(a.get("prompt", ""), a.get("style", ""))
        refs = _imgs(a.get("reference"))
        size = "%sx%s" % (a.get("width") or 1024, a.get("height") or 1024)
        return {"prompt": full, "negative": ", ".join(x for x in (a.get("negative"), neg) if x),
                "inputs": refs, "engine": _engine(_image_order(), IMAGE_ENGINES), "output": "picture, " + size,
                "plan": "%s draws %s%s, %s%s." % (role, "1 picture" if int(a.get("count") or 1) == 1
                                                   else "%s pictures" % a["count"],
                                                   " from %d reference image(s)" % len(refs) if refs else "",
                                                   size, ", style " + a["style"] if a.get("style") else "")}
    if tool == "make_turnaround":
        import turnaround  # pylint: disable=import-outside-toplevel
        concept = a.get("concept") or ""
        kind = a.get("kind") or "prop"
        try:
            full = turnaround.sheet_prompt(a.get("subject", ""), kind, bool(concept))
        except Exception:  # noqa: BLE001
            full = a.get("subject", "")
        return {"prompt": full, "negative": "", "inputs": _imgs(concept),
                "engine": _engine(_image_order(), IMAGE_ENGINES), "output": "orthographic front / side / back sheet",
                "plan": "%s turns the approved concept into front, side and back views of the same %s, one seed, "
                        "then cuts them apart for the 3D step." % (role, kind)}
    if tool == "make_3d":
        try:
            import forge3d  # pylint: disable=import-outside-toplevel
            order = forge3d.plan(a.get("backend") or "auto")
        except Exception:  # noqa: BLE001
            order = []
        return {"prompt": a.get("prompt", ""), "negative": "", "inputs": _imgs(a.get("image"), a.get("images")),
                "engine": _engine(order, MODEL_ENGINES), "output": "textured .glb",
                "plan": "%s builds a textured mesh from the front view%s." % (
                    role, ", then checks it against the side and back views" if a.get("judge") else "")}
    if tool == "blender":
        return {"prompt": "", "negative": "", "inputs": _imgs(a.get("path")), "engine": "Blender",
                "output": ".glb .fbx .blend + LODs",
                "plan": "%s %s in Blender: retopology to ~%s quads%s, UVs, bake colour + normal maps." % (
                    role, a.get("action") or "finishes the model", a.get("retopo") or "8000",
                    ", symmetric" if a.get("symmetric") else "")}
    if tool == "render_scene":
        return {"prompt": a.get("prompt", ""), "negative": "", "inputs": _imgs(a.get("model")),
                "engine": "Blender passes + ComfyUI (PC)", "output": "render passes + turntable",
                "plan": "%s renders the finished model%s." % (role, " and an AI still" if a.get("prompt") else "")}
    words = str(a.get("prompt") or a.get("subject") or "")
    return {"prompt": words, "negative": "", "inputs": _imgs(a.get("image"), a.get("reference")),
            "engine": tool or "?", "output": "", "plan": "%s runs %s." % (role, tool or "a tool")}


def with_plans(items: list) -> list:
    out = []
    for it in items:
        try:
            out.append(dict(it, plan=plan(it)))
        except Exception as exc:  # noqa: BLE001 - one odd card never hides the others
            out.append(dict(it, plan={"plan": "", "error": str(exc)[:160]}))
    return out


if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, str(HERE))
    print(json.dumps(plan({"tool": "make_image", "args": {"prompt": "a fox", "style": "model-reference"}}), indent=1))
