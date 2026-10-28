"""The art pipeline's specialists (engine/art_specialists.py; owner 2026-10-27: "the builder is too vague. They need
specialized agents ... over 500 skills and loads of 3-D modelling art skills ... prompts should be very technical").

Checks: each For you card is written by its stage's specialist (Concept Artist, Technical Artist ...) with its own
SKILL.md checklist in the Prompt Expert's instructions, plus a matching library skill when one is downloaded; art goals
get a specialist, never the coding Builder; a whole-asset goal is handed to the specialist pipeline (concept first,
waiting for the owner); code goals still get the coding team.

    python tests/test_art_specialists.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
DATA = Path(tempfile.mkdtemp(prefix="loki-art-"))
(DATA / "vendor" / "awesome-gamedev" / "skills" / "disciplines" / "create-game-assets").mkdir(parents=True)
(DATA / "vendor" / "awesome-gamedev" / "skills" / "disciplines" / "create-game-assets" / "SKILL.md").write_text(
    "---\nname: create-game-assets\n---\n# Create game assets\nKeep a consistent art bible across assets.")
os.environ["LOKI_DATA_DIR"] = str(DATA)
import art_specialists  # noqa: E402
import prompt_expert  # noqa: E402
import team  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


check("every specialist has its own technical skill file", all(
    (REPO / "skills" / "art-pipeline" / s["skill"] / "SKILL.md").is_file() for s in art_specialists.SPECIALISTS.values()))
ta = prompt_expert.system_for({"stage": "turnaround", "tool": "make_turnaround"})
check("a turnaround card is written by the Technical Artist with its checklist",
      ta.startswith("You are the Technical Artist") and "T-pose" in ta and "heads" in ta and "Symmetry" in ta, ta[:200])
ca = prompt_expert.system_for({"stage": "concept", "tool": "make_image"})
check("a concept card by the Concept Artist: proportions, materials, camera, light, background",
      all(w in ca for w in ("Proportions", "Materials", "85 mm", "key light", "flat light grey")), ca[:200])
check("... with the matching skill from the downloaded library", "create-game-assets" in ca and "art bible" in ca)
check("a card with no art stage keeps the general art director", prompt_expert.system_for({"tool": "x"}) == prompt_expert.SYSTEM)

check("an art goal gets a specialist, never the coding Builder",
      team.choose_roles("make concept art of a moss golem") == ["art_concept"]
      and team.choose_roles("a video of a fox running through snow") == ["art_video"],
      (team.choose_roles("make concept art of a moss golem"), team.choose_roles("a video of a fox running through snow")))
check("a code goal still gets the coding team", "builder" in team.choose_roles("write a python script that renames my files"))
prompt = team.agent_prompt({"id": "t1", "goal": "concept art of a golem", "roles": ["art_concept"]}, "art_concept")
check("the specialist agent gets its skill in its instructions", "Concept Artist" in prompt and "Proportions" in prompt
      and "For you" in prompt, prompt[:300])

WS = Path(tempfile.mkdtemp(prefix="loki-art-ws-"))


class _Policy:
    def job(self, *a):
        class V:
            allowed = True
            reason = ""
        return V()


runner = team.TeamRunner.__new__(team.TeamRunner) if hasattr(team, "TeamRunner") else None
cls = next((getattr(team, n) for n in dir(team) if isinstance(getattr(team, n), type) and hasattr(getattr(team, n), "start")
            and "goal" in getattr(team, n).start.__code__.co_varnames), None)
if cls is None:
    check("a whole-asset goal goes to the specialist pipeline", False, "no team class with start(goal)")
else:
    obj = cls.__new__(cls)
    obj.policy = _Policy()
    out = cls.start(obj, "make a 3D model of a moss golem guardian", str(WS))
    check("a whole-asset goal goes to the specialist pipeline, Concept Artist first",
          out.get("status") == "pipeline" and out["roles"][0] == "art_concept"
          and (WS / "pipeline").exists() or any(WS.rglob("pipeline.json")), out)
    check("... as the right kind of asset", team.art_kind("a knight with a big shield") == "character"
          and team.art_kind("a moss golem") == "creature")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
