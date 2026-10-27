"""The asset pipeline (owner 2026-10-26: "technical agent skills ... like an industry pipeline where they pass on work
to each other and can improve"): concept -> turnaround -> model -> finish -> render, each stage checked before it is
handed on, retries that change what failed, review notes that send work back, lessons voted up / down and promoted
into a skill, the settings that worked reused by the next asset. The makers are faked (real files, no GPU).

    python tests/test_asset_pipeline.py
"""
from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-pipeline-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
WS = TMP / "ws"
WS.mkdir()
PASS, FAIL = [], []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %r" % (detail,)))


import asset_pipeline as ap  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def picture(path: Path, size=(768, 1024)):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, (200, 200, 200))
    ImageDraw.Draw(im).ellipse((100, 100, size[0] - 100, size[1] - 100), fill=(40, 90, 50))
    im.save(path)
    return path


def glb(path: Path, tris: int, seed=0):
    j = json.dumps({"asset": {"version": "2.0", "extras": {"seed": seed}}, "accessors": [{"count": tris * 3}, {"count": tris * 3}],
                    "meshes": [{"primitives": [{"attributes": {"POSITION": 1}, "indices": 0}]}]}).encode()
    j += b" " * (-len(j) % 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 20 + len(j)) + struct.pack("<I", len(j)) + b"JSON" + j)
    return path


script = {"turnaround_bad": 1, "model_lift": 1, "finish_bad": 0}
calls = []


def fake(tool, args, cwd):
    calls.append((tool, dict(args)))
    n = len(calls)
    if tool == "make_image":
        return {"ok": True, "files": [str(picture(cwd / "images" / ("concept%d.png" % n)).relative_to(cwd))]}
    if tool == "make_turnaround":
        folder = cwd / "turnarounds" / ("golem%d" % n)
        views = {}
        want = ["front", "side"] if script["turnaround_bad"] > 0 else ["front", "side", "back", "top"]
        script["turnaround_bad"] -= 1
        for v in want:
            views[v] = str(picture(folder / (v + ".png")).relative_to(cwd))
        sheet = picture(cwd / "turnarounds" / ("golem%d-sheet.png" % n), (1024, 1024))
        return {"ok": True, "files": [str(sheet.relative_to(cwd))] + list(views.values()), "views": views, "missing": []}
    if tool == "make_3d":
        if script["model_lift"] > 0:
            script["model_lift"] -= 1
            return {"ok": True, "files": [str(glb(cwd / "models" / ("blob%d.glb" % n), 300).relative_to(cwd))], "backend": "lift"}
        return {"ok": True, "files": [str(glb(cwd / "models" / ("golem%d.glb" % n), 30000, args.get("seed", 0)).relative_to(cwd))],
                "backend": args.get("backend")}
    if tool == "blender":
        stem = cwd / "models" / ("golem-polished%d" % n)
        files = [glb(stem.with_suffix(".glb"), 14000), stem.with_suffix(".fbx")]
        files[1].write_bytes(b"FBX")
        render = picture(cwd / "renders" / ("golem-polished%d.png" % n), (1280, 1280))
        bad = script["finish_bad"] > 0
        script["finish_bad"] -= 1
        return {"ok": True, "files": {"models": [str(f) for f in files], "render": str(render)},
                "topology": {"verdict": "mixed" if bad else "quads", "quad_pct": 60 if bad else 100, "pole_pct": 4.2,
                             "faces": 7000, "retopo": "quadriflow"}, "quality": {"verdict": "clean"}}
    if tool == "render_scene":
        return {"ok": True, "files": [str(picture(cwd / "renders" / ("pass%d.png" % n), (512, 512)))]}
    return {"ok": False, "error": "no tool"}


a = ap.start(WS, "a moss golem guardian, stone body, glowing green runes", kind="creature")
check("a new asset: concept ready, the rest waiting on it", ap.summary(a) == {
    "concept": "ready", "turnaround": "waiting", "model": "waiting", "finish": "waiting", "render": "waiting"}, ap.summary(a))
r = ap.advance(WS, a["id"], fake)
rec = ap.resolve(WS, ap.ref(a["id"], "concept"))
check("concept: drawn, checked (real, non-blank picture), approved as v001", r["ok"] and r["version"] == "v001"
      and rec and rec["verdict"] == "pass" and all(c["ok"] for c in rec["validation"]), r)
check("... a hand-off record + handoff.md, outputs with sha256", rec and len(rec["files"][0]["sha256"]) == 64
      and (ap.asset_dir(WS, a["id"]) / "concept" / "v001" / "handoff.md").is_file())
r = ap.advance(WS, a["id"], fake)
check("turnaround from the APPROVED concept (the hand-off, not 'the newest file')",
      calls[-1][0] == "make_turnaround" and calls[-1][1]["concept"] == rec["outputs_rel"][0], calls[-1])
check("... missing back view -> failed check, not handed on, try 2 is next", not r["ok"]
      and ap.load(WS, a["id"])["stages"]["turnaround"]["status"] == "ready"
      and ap.load(WS, a["id"])["stages"]["model"]["status"] == "waiting", r)
les = ap.recall("turnaround", "creature")
check("... the failure became a lesson for the turnaround stage", any("views" in x["text"] for x in les), les)
r = ap.advance(WS, a["id"], fake)
check("try 2 runs with a changed seed and passes -> v002 approved", r["ok"] and r["version"] == "v002"
      and calls[-1][1].get("seed") and calls[-2][1].get("seed") != calls[-1][1].get("seed"), (r, calls[-2:]))
check("... a new seed is luck, not a lesson (no 'seed=... fixed it')",
      not any("fixed it" in x["text"] for x in ap.recall("turnaround", "creature")))
r = ap.advance(WS, a["id"], fake)
check("model: the turnaround's FRONT view goes in; a 'lift' blob fails its check", calls[-1][0] == "make_3d"
      and calls[-1][1]["image"].endswith("front.png") and not r["ok"]
      and any("lift" in c["detail"] for c in r["checks"]), (calls[-1], r))
r = ap.advance(WS, a["id"], fake)
check("... the retry switches backend (auto -> TRELLIS.2) and passes", r["ok"] and calls[-1][1]["backend"] == "trellis2", r)
check("... 'backend=trellis2 fixed it' is remembered", any("backend=trellis2" in x["text"] for x in ap.recall("model", "creature")))
script["finish_bad"] = 1
r = ap.advance(WS, a["id"], fake)
check("finish: Blender polish with retopo for a creature (8000 quads); 60% quads fails", calls[-1][0] == "blender"
      and calls[-1][1]["retopo"] == 8000 and not r["ok"], (calls[-1], r))
r = ap.advance(WS, a["id"], fake)
check("... the retry asks for 1.5x the quads and passes (topology, .glb + .fbx)", r["ok"] and calls[-1][1]["retopo"] == 12000, r)
r = ap.advance(WS, a["id"], fake)
check("render: the FINISHED model is rendered", r["ok"] and calls[-1][0] == "render_scene"
      and "golem-polished" in calls[-1][1]["model"], calls[-1])
check("every stage approved", set(ap.summary(ap.load(WS, a["id"])).values()) ==
      {"approved v001", "approved v002", "approved v002", "approved v002", "approved v001"}
      or all(v.startswith("approved") for v in ap.summary(ap.load(WS, a["id"])).values()), ap.summary(ap.load(WS, a["id"])))
check("nothing left to do -> advance says idle", ap.advance(WS, a["id"], fake).get("idle"))

# review notes send work back
n = ap.note(WS, a["id"], "model", "the arms are fused to the body - separate them", author="owner", retake=True)
s = ap.summary(ap.load(WS, a["id"]))
check("a retake note reopens the model and sends finish + render back to waiting (versions kept)",
      s["model"] == "ready" and s["finish"] == "waiting" and s["render"] == "waiting" and s["turnaround"].startswith("approved")
      and (ap.asset_dir(WS, a["id"]) / "finish" / "v002" / "record.json").is_file(), s)
brief = ap.stage_brief(WS, a["id"], "model")
check("the stage brief carries the upstream hand-off, the lessons and the open note",
      "From turnaround" in brief and "front.png" in brief and n["id"] in brief and "Lessons" in brief, brief)
r = ap.advance(WS, a["id"], fake)
check("a retaken model is NOT made the same way again: another backend and a new seed; the note is addressed",
      r["ok"] and calls[-1][1]["backend"] != "trellis2" and calls[-1][1].get("seed") and not ap.notes(WS, a["id"], "model", open_only=True), calls[-1])
# the same files coming back after a retake are refused
mrec = ap.resolve(WS, ap.ref(a["id"], "model"))
ap.note(WS, a["id"], "model", "still wrong", retake=True)
same_again = lambda tool, args, cwd: {"ok": True, "files": [mrec["outputs_rel"][0]], "backend": "online"}   # noqa: E731
r = ap.advance(WS, a["id"], same_again)
check("a retake that hands back the very same model is refused ('the same files as the version that was sent back')",
      not r["ok"] and r["checks"][0]["check"] == "new", r.get("checks"))
r = ap.advance(WS, a["id"], fake)

# a stage that keeps failing waits for a person
b = ap.start(WS, "a broken lantern", kind="prop", concept=str(picture(WS / "images" / "lantern.png", (1024, 1024)).relative_to(WS)))
check("an owner's concept picture is checked and approved without drawing", ap.summary(b)["concept"] == "approved v001"
      and ap.summary(b)["turnaround"] == "ready", ap.summary(b))
script["turnaround_bad"] = 3
for _ in range(3):
    ap.advance(WS, b["id"], fake)
check("3 failed tries -> retake (waits for the owner or an agent's note)", ap.summary(ap.load(WS, b["id"]))["turnaround"] == "retake")
check("... and advance does not run it again", ap.advance(WS, b["id"], fake).get("idle"))

# votes, deletion, promotion
lid = ap.add_lesson("finish", "creature", "Thin capes need retopo faces 12000 or they tear.")["id"]
ap.vote([lid], False)
ap.vote([lid], False)
check("a lesson that hurt twice is deleted (score 0)", not any(x["id"] == lid for x in ap._jsonl(ap.lessons_path())))
lid = ap.add_lesson("finish", "creature", "Symmetric creatures: polish with symmetric=true.")["id"]
check("the same lesson again is an upvote, not a duplicate",
      ap.add_lesson("finish", "creature", "Symmetric creatures: polish with symmetric=true!")["id"] == lid)
for _ in range(5):
    ap.vote([lid], True)
skill = ap.promote("finish")
check("proven lessons are promoted into a learned skill the agents' catalog reads", skill and skill.is_file()
      and "symmetric=true" in skill.read_text() and skill.parent.name == "pipeline-finish", skill)

# agents hand in their own work; tick; crash recovery
c = ap.start(WS, "a wooden signpost", kind="prop")
res = ap.tool({"action": "submit", "asset": c["id"], "stage": "concept", "files": ["images/lantern.png"]}, WS)
check("an agent submits work it made itself - same checks", res["ok"] and ap.summary(ap.load(WS, c["id"]))["concept"] == "approved v001", res)
out = ap.tick(WS, fake, thread=False)
check("tick runs the next ready stage of the OLDEST asset (the golem's finish, redone after the model retake)",
      out.startswith("pipeline: a-moss-golem") and "3D Finisher" in out, out)
x = ap.load(WS, c["id"])
x["stages"]["turnaround"].update(status="wip", started=time.time())
ap.save(WS, x)
check("one stage at a time: a running stage blocks the next tick", ap.tick(WS, fake, thread=False) == "" and ap.busy(WS))
x["stages"]["turnaround"]["started"] = time.time() - ap.FRESH_WIP_S - 5
ap.save(WS, x)
check("a stage left 'wip' by a crash goes back to ready", ap.recover(WS) == 1 and not ap.busy(WS))
check("the tool: status lists every asset", len(ap.tool({"action": "status"}, WS)["assets"]) == 3)
check("the tool: bad input is an answer, not a crash", not ap.tool({"action": "note", "asset": "nope", "stage": "model"}, WS)["ok"])

# likeness: a model that does not look like its picture is not handed on
ctx = {"stage": ap.BY_NAME["model"], "outputs": [], "report": {"judge": {"score": 0.3, "shape": 0.2, "colour": 0.5,
                                                                          "missing": ["arms"], "note": "a blob"}}}
ok, detail, hint = ap.check_likeness(ctx)
check("likeness: 30% like the picture fails, with what is missing", not ok and "30%" in detail and "arms" in detail, detail)
ctx["report"]["judge"] = {"score": None, "error": "no vision model"}
ok, detail, _ = ap.check_likeness(ctx)
check("... a judge that could not look passes but says so in the record", ok and "not judged" in detail, detail)
check("the model stage asks make_3d to judge itself", ap._args_model(
    {"brief": "x", "kind": "creature"}, {"turnaround": {"report": {"views": {"front": "t/front.png"}}, "outputs_rel": []}},
    {})[1].get("judge") is True)
mac = (("auto", "online", "triposr", "trellis2", "pixal3d"))
check("on the Mac a failed model retries online first (no NVIDIA card for ComfyUI)",
      "sys.platform == \"darwin\"" in (REPO / "engine" / "asset_pipeline.py").read_text() and ap.BACKENDS in (mac, ("auto", "trellis2", "pixal3d", "online", "triposr")))

# wiring
import make_mcp  # noqa: E402
check("LOKI's making tools (OpenCode agents) have asset_pipeline", any(t["name"] == "asset_pipeline" for t in make_mcp.TOOLS))
auto = (REPO / "engine" / "autopilot.py").read_text(encoding="utf-8")
check("the autopilot runs the pipeline as a duty", "def duty_pipeline" in auto and "LOKI_AUTOPILOT_PIPELINE" in auto)
tasks = (REPO / "LOKI_TASKS.md").read_text(encoding="utf-8")
check("standing goals: a Producer starts assets, an Art Director writes review notes (no 'newest file' chains)",
      "PRODUCER" in tasks and "ART DIRECTOR" in tasks and "3D ARTIST: take the newest turnaround" not in tasks)
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
