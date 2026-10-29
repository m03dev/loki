"""Manga Studio tells one story, not three that repeat (owner 2026-10-29: "the first few panels where complete nonsense
and the logic is complete dog shit ... everyone copys from ref").

"Kitsune vs. the Vending Machine" showed the tofu coming out on pages 1, 2 AND 3, a character talking about a machine
the reader had not seen, a button pressing itself, the age "12" as a character, the machine "saying" CLANK, and every
panel drawn from words alone so the fox became a girl and the machine a boy. Fixed the way working pipelines do it
(storyboard guides; arXiv 2605.28173's section memory; the sheet + previous-panel "sliding window"):
  - the outline plans the WHOLE story as visible events, page by page, plus the world (place, time, props)
  - each page script sees the world, its own events, what earlier pages already showed and what comes later
  - page 1 opens on an establishing shot; continuity rules in the prompt
  - cast names only; an object's sound is SFX; an empty / "same" setting gets the shared world
  - panels are drawn with the characters' sheets + the panel before as references, text-only when refused
Under a minute.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import manga  # noqa: E402

PASS: list = []
FAIL: list = []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


ws = Path(tempfile.mkdtemp())
pid = manga.tool({"action": "project", "premise": "A fox spirit fears the new vending machine at her shrine.",
                  "pages": 3}, ws)["project"]
OUTLINE = {"title": "Tofu Guardian", "logline": "x", "tone": "gag", "ending": "warm",
           "world": {"place": "a small shrine courtyard: red torii gate, stone lanterns, the machine left of the gate",
                     "time": "late afternoon, warm low sun", "props": "the vending machine, a coin, fried tofu"},
           "pages": [{"n": 1, "beat": "setup", "summary": "s1", "events": ["the fox guards the gate", "workers install the machine"]},
                     {"n": 2, "beat": "turn", "summary": "s2", "events": ["she drops a coin in", "tofu falls out"]},
                     {"n": 3, "beat": "payoff", "summary": "s3", "events": ["she eats it", "she guards the machine too"]}]}
manga.tool({"action": "outline", "project": pid, "data": OUTLINE}, ws)
proj = manga.load(ws, pid)
check("the outline keeps the world every panel shares", proj["outline"]["world"]["time"].startswith("late afternoon"))
check("... and each page's visible events", proj["pages"][1]["events"] == ["she drops a coin in", "tofu falls out"])
check("the outline prompt plans the whole story as events that happen once",
      "exactly ONCE" in manga.OUTLINE_PROMPT and '"events"' in manga.OUTLINE_PROMPT and '"world"' in manga.OUTLINE_PROMPT)

manga.tool({"action": "characters", "project": pid, "data": {"characters": [
    {"name": "Kitsune", "species": "a small white fox spirit", "age": "12", "look": {"face": "round"}},
    {"name": "Tofu-Mate", "species": "a vending machine with a face", "look": {"face": "screen eyes"}}]}}, ws)

seen = {}


def ask_for(n):
    def ask(prompt):
        seen[n] = prompt
        return json.dumps({"panels": [
            {"n": 1, "shot": "wide", "characters": ["Kitsune", "12", "12 visitors"], "setting": "same location",
             "action": "page %d first" % n, "dialogue": [{"speaker": "Tofu-Mate", "kind": "speech", "text": "CLANK!"}]},
            {"n": 2, "shot": "close-up", "characters": ["Kitsune"], "action": "page %d second" % n,
             "dialogue": [{"speaker": "Kitsune", "kind": "speech", "text": "Is that tofu?"}]},
            {"n": 3, "action": "page %d third" % n}, {"n": 4, "action": "page %d fourth" % n},
            {"n": 5, "action": "page %d fifth" % n}]})
    return ask


manga.tool({"action": "script", "project": pid, "page": 1}, ws, ask=ask_for(1))
manga.tool({"action": "script", "project": pid, "page": 2}, ws, ask=ask_for(2))
p1, p2 = seen[1], seen[2]
check("page 1 opens on an establishing shot of the place", "establishing wide shot" in p1)
check("... later pages do not", "establishing wide shot" not in p2)
check("a page script sees the shared world", "red torii gate" in p2 and "late afternoon" in p2)
check("... its own events", "she drops a coin in | tofu falls out" in p2)
check("... what earlier pages already showed (their real panels), as off-limits",
      "do NOT show any of it again: p1: page 1 first" in p2)
check("... and what comes later, as not yet", "do NOT show it yet: p3: she eats it" in p2)
flat = " ".join(p2.split())
check("the continuity rules are in the prompt",
      "nothing happens by itself" in flat and "an object that cannot talk never speaks" in flat)

pg = manga.load(ws, pid)["pages"][0]
first = pg["panels"][0]
check("the age '12' is not a character, '12 visitors' becomes 'visitors'", first["characters"] == ["Kitsune", "visitors"],
      first["characters"])
check("the machine's 'CLANK!' is a sound effect, not speech",
      first["dialogue"][0]["kind"] == "sfx" and first["dialogue"][0]["speaker"] == "SFX", first["dialogue"])
check("a person's line stays speech", pg["panels"][1]["dialogue"][0]["kind"] == "speech")
pp = manga.panel_prompt(manga.load(ws, pid), pg, first)["prompt"]
check("a 'same location' panel is drawn in the shared world", "red torii gate" in pp, pp)
pp2 = manga.panel_prompt(manga.load(ws, pid), pg, dict(pg["panels"][1], setting="by the gate"))["prompt"]
check("the time of day is kept on every panel", "late afternoon" in pp2, pp2)

# drawing: the character sheets + the panel before go along as references; refused -> drawn from words
(ws / "manga" / pid / "characters").mkdir(parents=True, exist_ok=True)
sheet = "manga/%s/characters/kit.png" % pid
from PIL import Image  # noqa: E402
Image.new("RGB", (64, 64), "white").save(ws / sheet)
pr = manga.load(ws, pid)
pr["characters"][0]["sheet"] = sheet
manga.save(ws, pr)
calls = []


def make_ok(args):
    calls.append(args)
    f = ws / ("manga/%s/panels/p%d.png" % (pid, len(calls)))
    f.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), "gray").save(f)
    return {"ok": True, "files": [str(f.relative_to(ws))]}


manga.draw_page(ws, pid, 1, make_ok, only=[1, 2])
check("a panel with a character is drawn with that character's sheet as a reference",
      calls[0]["reference"] == [sheet] and calls[0]["reference_optional"] is False, calls[0].get("reference"))
check("... the next one also gets the panel before it", calls[1]["reference"][-1].endswith("p1.png"), calls[1].get("reference"))
check("... and is told to keep the design, not copy the pose", "not their pose or layout" in calls[1]["prompt"])

calls.clear()


def make_refuses_refs(args):
    if args.get("reference"):
        calls.append("refs")
        return {"ok": False, "error": "NVIDIA would not take the reference pictures"}
    return make_ok(args)


out = manga.draw_page(ws, pid, 1, make_refuses_refs, only=[1])
check("references refused: the panel is still drawn from the words", out.get("ok") and calls[0] == "refs",
      (out.get("errors"), calls[:3]))
check("... and the page says it was drawn without references", any("without references" in e for e in out.get("errors") or []))
print("\n%d passed, %d failed (%.1f s)" % (len(PASS), len(FAIL), time.time() - T0))
sys.exit(1 if FAIL else 0)
