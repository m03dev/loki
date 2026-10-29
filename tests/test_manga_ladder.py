"""Manga Studio walks every model before a placeholder, and says so when it falls back (2026-10-28: the main
driver timed out on an outline and the step 'succeeded' with the premise pasted onto every page)."""
import asyncio
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

import manga  # noqa: E402
import manga_api  # noqa: E402

PASSED = FAILED = 0


def check(name, ok):
    global PASSED, FAILED
    print(("  PASS " if ok else "  FAIL ") + name)
    PASSED, FAILED = PASSED + bool(ok), FAILED + (not ok)


GOOD = '{"logline": "A fox meets a machine.", "pages": [{"beat": "setup", "summary": "The fox sees it."}, ' \
       '{"beat": "turn", "summary": "Tofu falls out."}]}'


def fake_agent(answers):
    calls = []

    async def _port_ask(prompt, max_tokens=0, provider=""):
        calls.append(provider)
        a = answers.get(provider)
        if isinstance(a, Exception):
            raise a
        return a

    return types.SimpleNamespace(_port_ask=_port_ask, port_ladder=lambda: list(answers), calls=calls)


def run(agent):
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    state = types.SimpleNamespace(agent=agent, loop=loop)
    ws = Path(tempfile.mkdtemp())
    pid = manga.tool({"action": "project", "premise": "A fox spirit fears a vending machine.", "pages": 2}, ws)["project"]
    out = manga.tool({"action": "outline", "project": pid}, ws, ask=manga_api._ask(state, timeout_s=2))
    loop.call_soon_threadsafe(loop.stop)
    return out, manga.review(ws, pid)


t0 = time.time()
a = fake_agent({"nvidia": RuntimeError("timed out"), "nvidia-nemotron": "no json here", "local": GOOD})
out, rv = run(a)
check("each model is tried in turn until one writes usable JSON", a.calls == ["nvidia", "nvidia-nemotron", "local"])
check("the outline is the model's, not the placeholder", out["outline"]["pages"][1]["summary"] == "Tofu falls out.")
check("a good write leaves no warning", not out["warnings"])

b = fake_agent({"nvidia": RuntimeError("down"), "local": "nope"})
out, rv = run(b)
check("when every model fails the step says so", "outline" in out["warnings"] and "every model failed" in out["warnings"]["outline"])
check("and the review lists it as an open issue", any(i.startswith("outline:") for i in rv["issues"]))

# A model that timed out is tried last on the next step, and first again once it answers.
manga_api.SLOW_MODELS.clear()
c = fake_agent({"nvidia": TimeoutError(), "local": GOOD})
run(c)
c.calls.clear()
run(c)
check("a model that just timed out is tried last next time", c.calls == ["local"])
manga_api.SLOW_MODELS.clear()

# A retired NVIDIA model: a real call's 404 sticks even though /models still lists it (it used to flip back to ready).
import provider_health  # noqa: E402
reg = provider_health.Registry(Path(tempfile.mkdtemp()) / "h.json")
reg.record_failure("nvidia-pro", "[model error] moonshotai/kimi-k2.6 answered HTTP 404: {'status': 404, "
                   "'title': 'Not Found', 'detail': \"Function '23d4' not found for account\"}")
reg.record_probe("nvidia-pro", {"state": "ok", "models": ["moonshotai/kimi-k2.6"]})
check("a model a real call said is gone stays benched after a /models probe", not reg.usable("nvidia-pro")[0])
reg.record_success("nvidia-pro")
check("and comes back the moment a real call works", reg.usable("nvidia-pro")[0])
reg.record_failure("other", "HTTP 404 model not found")
check("a plain missing model is benched", not reg.usable("other")[0])
# A long answer with a dropped colon (the PC's model, page 2) is repaired instead of thrown away.
broken = '{"panels": [{"n": 1, "action" "Kitsune hides", "dialogue": []}, {"n": 2, "action": "tofu drops",}]}'
try:
    import json_repair  # noqa: F401
    fixed = manga._json(broken)
    check("a dropped colon in the model's JSON is repaired", fixed["panels"][1]["action"] == "tofu drops")
except ImportError:
    print("  SKIP json_repair is not installed here")
check("a trailing comma is repaired by LOKI's own parser", manga._json('{"a": [1, 2,],}') == {"a": [1, 2]})

# What a character IS leads every drawing prompt (a fox spirit drawn as a girl, then refused by the filter).
lt = manga.look_text({"name": "Kitsune", "species": "a small white fox spirit", "look": {"face": "round"}})
check("the species comes first in the drawing prompt", lt.startswith("Kitsune (a small white fox spirit)"))
check("the cast prompt asks what each character is", '"species"' in manga.CAST_PROMPT)

# Picture prompts fit the strictest model with the layout / style / black-and-white / no-text part intact, and carry
# no name or age labels (FLUX paints them: "OTeu-Vending Mahne", "5 years" on the first sheet).
long_look = {"name": "Tofu-Vending Machine", "species": "a vending machine robot", "age": "5 years",
             "look": {k: "very detailed description " * 12 for k in ("face", "hair", "build", "outfit", "props")}}
sheet = manga.character_sheet_args({"id": "x", "style": "normal", "colour": "mono"}, long_look)["prompt"]
check("a sheet prompt stays under 800 characters", len(sheet) <= 800)
check("and keeps its layout, black and white and no-text instructions",
      "three head close-ups" in sheet and "black and white" in sheet and sheet.rstrip().endswith("no letters."))
check("and has no name or age label", "Tofu-Vending Machine" not in sheet and "5 years" not in sheet)
proj = {"id": "x", "style": "normal", "colour": "mono", "characters": [dict(long_look, name="Kit")]}
pp = manga.panel_prompt(proj, {}, {"shot": "wide", "angle": "low", "action": "Kit hides behind a pillar " * 20,
                                   "setting": "a shrine at dusk", "characters": ["Kit"], "style": "normal",
                                   "dialogue": [{"text": "hi", "place": "top"}]})["prompt"]
check("a panel prompt stays under 800 and keeps no-text and black and white",
      len(pp) <= 800 and "No text" in pp and "black and white" in pp)

# Writing and drawing steps stay background jobs (a0df9c2 named the slow-model table SLOW and replaced this set:
# every step then ran inside the HTTP request and the window hung until the picture was drawn).
check("outline / sheet / draw_page are still background actions",
      isinstance(manga_api.SLOW, set) and {"outline", "characters", "script", "sheet", "draw_page"} <= manga_api.SLOW)
print("\n%d passed, %d failed (%.1f s)" % (PASSED, FAILED, time.time() - t0))
sys.exit(1 if FAILED else 0)
