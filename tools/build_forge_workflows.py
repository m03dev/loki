"""Rebuild engine/forge_workflows/*.json (the API graphs Forge queues) from Comfy Org's MIT templates in
engine/forge_workflows/ui/ and an object_info of a ComfyUI that has the nodes (tests/fixtures/comfy_trellis_object_info.json,
written from ComfyUI's node sources, or a live one: --info http://pc:8188).

    python tools/build_forge_workflows.py [--info <object_info.json | url>]

tests/test_forge_trellis.py checks the vendored files equal a fresh build.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import comfy_workflow as cw  # noqa: E402  pylint: disable=wrong-import-position

UI_DIR = REPO / "engine" / "forge_workflows" / "ui"
FIXTURE = REPO / "tests" / "fixtures" / "comfy_trellis_object_info.json"
SAVE = {"mesh": None, "filename_prefix": "loki/forge"}
VIEWS = {"338": "front", "341": "left", "342": "back", "345": "right"}   # the sheet's columns, left to right


def single(info: dict) -> dict:
    ui = json.loads((UI_DIR / "3d_pixal3d_trellis2_image_to_model.json").read_text(encoding="utf-8"))
    api = cw.ui_to_api(ui, info)
    api["322"] = {"class_type": "SaveGLB", "_meta": {"title": "Save 3D Model"},
                  "inputs": {"mesh": ["285", 0], "filename_prefix": "loki/forge"}}
    return cw.prune(api, ["322"])


def views(info: dict) -> dict:
    """The 4-view sheet graph with one LoadImage per view in place of the template's fixed-pixel crops."""
    ui = json.loads((UI_DIR / "3d_pixal3d_multi_views.json").read_text(encoding="utf-8"))
    replace = {nid: ("LoadImage", {"image": "%s.png" % view}) for nid, view in VIEWS.items()}
    api = cw.ui_to_api(ui, info, drop=("ImageCropV2",), replace=replace)
    save = next(k for k, v in api.items() if v["class_type"] == "Save3DAdvanced")
    src = api[save]["inputs"]["model_3d"]
    api[save] = {"class_type": "SaveGLB", "_meta": {"title": "Save 3D Model"},
                 "inputs": {"mesh": src, "filename_prefix": "loki/forge"}}
    api = cw.prune(api, [save])
    return api


def main(argv: list) -> int:
    src = argv[argv.index("--info") + 1] if "--info" in argv else str(FIXTURE)
    if src.startswith("http"):
        with urllib.request.urlopen(src.rstrip("/") + "/object_info", timeout=60) as resp:
            info = json.loads(resp.read().decode("utf-8"))
    else:
        info = json.loads(Path(src).read_text(encoding="utf-8"))
    for name, fn in (("trellis2_pixal3d", single), ("pixal3d_views", views)):
        path = REPO / "engine" / "forge_workflows" / (name + ".json")
        wf = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        wf["api"] = fn(info)
        path.write_text(json.dumps(wf, indent=1), encoding="utf-8")
        print("%s: %d nodes" % (path.name, len(wf["api"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
