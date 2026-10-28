"""What a "For you" card says will run (engine/review_plan.py; owner 2026-10-27: "show what the prompt was ... what images
they're using, what prompts and what engine, what their plan is ... very minimal").

Checks: the concept card shows the FULL prompt with the style words the code adds after approval (before this, the
owner never saw them); 3D concepts use the technical model-reference style, scenes the cinematic one; the Technical
Artist card shows the real orthographic sheet wording and the concept it uses; the 3D card shows the image and the
engine order; nothing is drawn.

    python tests/test_review_plan.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
os.environ.setdefault("NVIDIA_API_KEY", "test-key")
import asset_pipeline  # noqa: E402
import review_plan  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


golem = {"brief": "a moss golem guardian, stacked boulders", "kind": "creature", "name": "moss-golem"}
tool, args = asset_pipeline._args_concept(golem, {}, {})
check("a creature's concept uses the technical model-reference style", args["style"] == "model-reference", args)
tool, scene = asset_pipeline._args_concept(dict(golem, kind="scene"), {}, {})
check("... a scene keeps the cinematic game-concept style", scene["style"] == "game-concept", scene)

p = review_plan.plan({"tool": tool, "args": args, "who": "Concept Artist"})
check("the card shows the full prompt, with the style words added after approval",
      p["prompt"].startswith("a moss golem guardian") and "A-pose" in p["prompt"] and "85mm" in p["prompt"], p["prompt"])
check("... what is kept out", "background scenery" in p["negative"], p["negative"])
check("... the engine it will use", "FLUX" in p["engine"] or "Z-Image" in p["engine"] or "Qwen" in p["engine"], p["engine"])
check("... and a one-line plan", p["plan"].startswith("Concept Artist draws 1 picture") and len(p["plan"]) < 140, p["plan"])

t = review_plan.plan({"tool": "make_turnaround", "who": "Technical Artist",
                      "args": {"concept": "images/golem.png", "subject": golem["brief"], "kind": "creature"}})
check("Technical Artist card: the real orthographic sheet wording", "orthographic FRONT view" in t["prompt"]
      and "SIDE" in t["prompt"] and "BACK" in t["prompt"], t["prompt"][:200])
check("... the concept picture it uses", t["inputs"] == ["images/golem.png"], t["inputs"])
check("... the plan in one line", "front, side and back" in t["plan"], t["plan"])

m = review_plan.plan({"tool": "make_3d", "who": "3D Artist", "args": {"image": "turnarounds/golem/front.png", "judge": True}})
check("3D card: the front view it builds from and the engine order", m["inputs"] == ["turnarounds/golem/front.png"]
      and m["engine"] and m["output"] == "textured .glb", m)
check("one odd card never breaks the list", review_plan.with_plans([{"tool": "make_image", "args": None}])[0].get("plan") is not None)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
