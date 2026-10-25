"""A ComfyUI UI-format workflow (what ComfyUI saves, what Comfy-Org's templates are) -> the API format LOKI queues.

    python tools/comfy_convert.py <workflow.json> <object_info.json | http://pc:8188> [out.json] [--keep <node id>...]

object_info comes from the ComfyUI the workflow is for (GET /object_info), or a saved copy of it. --keep prunes the
graph to what those output nodes need. engine/comfy_workflow.py does the work.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import comfy_workflow  # noqa: E402  pylint: disable=wrong-import-position


def main(argv: list) -> int:
    keep = []
    if "--keep" in argv:
        i = argv.index("--keep")
        keep, argv = argv[i + 1:], argv[:i]
    if len(argv) < 2:
        print(__doc__)
        return 2
    ui = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    src = argv[1]
    if src.startswith("http"):
        with urllib.request.urlopen(src.rstrip("/") + "/object_info", timeout=60) as resp:
            info = json.loads(resp.read().decode("utf-8"))
    else:
        info = json.loads(Path(src).read_text(encoding="utf-8"))
    api = comfy_workflow.ui_to_api(ui, info)
    if keep:
        api = comfy_workflow.prune(api, keep)
    text = json.dumps(api, indent=1)
    if len(argv) > 2:
        Path(argv[2]).write_text(text, encoding="utf-8")
        print("%d nodes -> %s" % (len(api), argv[2]))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
