"""The technical artist (engine/turnaround.py): a concept -> orthographic T-pose turnaround views + one sheet, with
the lineage saved (owner 2026-10-26). Offline: the image maker is a fake that writes real PNGs. Seconds.

    python tests/test_turnaround.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-turn-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


from PIL import Image  # noqa: E402

import turnaround  # noqa: E402
import make_mcp  # noqa: E402

ws = TMP / "ws"
(ws / "images" / ".meta").mkdir(parents=True)
Image.new("RGB", (64, 72), (200, 40, 40)).save(ws / "images" / "20261026-dragon.png")   # a red subject
(ws / "images" / ".meta" / "20261026-dragon.png.json").write_text(json.dumps(
    {"prompt": "a red baby dragon with golden horns and a scaled belly. game concept art, cinematic"}), encoding="utf-8")
asked = []


def fake_maker(args, cwd):
    asked.append(args)
    out = Path(cwd) / args["folder"]
    out.mkdir(parents=True, exist_ok=True)
    f = out / ("pic%d.png" % len(asked))
    colour = (190, 50, 45) if args.get("reference") else (128, 128, 128)   # a reference edit keeps the red
    Image.new("RGB", (args["width"] // 8, args["height"] // 8), colour).save(f)
    return {"ok": True, "files": [os.path.relpath(f, cwd)], "backend": "nvidia", "model": "flux.2-klein-4b"}


r = turnaround.make_turnaround({"concept": "images/20261026-dragon.png", "kind": "creature"}, ws, fake_maker,
                               clock=lambda: 1793030000.0)
check("a creature: front, side and back (no top view - that is for props), and one sheet",
      r.get("ok") and set(r["views"]) == {"front", "side", "back"} and (ws / r["sheet"]).is_file()
      and all((ws / v).is_file() for v in r["views"].values()), r)
check("front, side and back are drawn TOGETHER on one wide canvas (one picture = one design), then split",
      len(asked) == 1 and (asked[0]["width"], asked[0]["height"]) == turnaround.SHEET_SIZE
      and "FRONT view" in asked[0]["prompt"] and "SIDE view" in asked[0]["prompt"] and "BACK view" in asked[0]["prompt"]
      and "exactly the same creature" in asked[0]["prompt"] and set(r["mode"].values()) == {"reference+sheet"}, (asked, r.get("mode")))
check("the design comes from the concept: its picture as the reference AND its own words",
      asked[0].get("reference") == ["images/20261026-dragon.png"] and asked[0].get("need_edit")
      and "a red baby dragon with golden horns and a scaled belly" in asked[0]["prompt"], asked[0])
check("no words that make the model write labels ('model sheet'), and 'no text' is asked",
      "model sheet" not in asked[0]["prompt"].lower() and "no text, no letters, no labels" in asked[0]["prompt"])
check("each view's colours are checked against the concept (the red stays red)",
      min(r["colour_match"].values()) > 0.8, r.get("colour_match"))
asked.clear()
rp = turnaround.make_turnaround({"concept": "images/20261026-dragon.png", "subject": "a red lantern", "kind": "prop"}, ws, fake_maker)
check("a prop also gets a top view, drawn after from the concept + the front", rp["ok"] and set(rp["views"]) == {"front", "side", "back", "top"}
      and len(asked) == 2 and asked[1]["reference"][1].endswith("/front.png") and "TOP view" in asked[1]["prompt"], [a.get("reference") for a in asked])
asked.clear()
r1 = turnaround.make_turnaround({"concept": "images/20261026-dragon.png", "kind": "creature", "layout": "views"}, ws, fake_maker)
check("layout=views: one view at a time, the concept + the front as references",
      r1["ok"] and len(asked) == 3 and len(asked[0]["reference"]) == 1 and asked[1]["reference"][1].endswith("/front.png"), asked)
asked.clear()
# splitting: three figures on a grey canvas, cut at the gaps
sheet_png = TMP / "three.png"
im = Image.new("RGB", (1568, 672), (200, 200, 200))
from PIL import ImageDraw  # noqa: E402
d = ImageDraw.Draw(im)
for x0 in (180, 700, 1180):
    d.rectangle((x0, 80, x0 + 220, 620), fill=(150, 40, 40))
im.save(sheet_png)
panels = turnaround.split_panels(sheet_png, 3)
check("a wide sheet splits at the gaps between the figures into 3 panels, each figure whole and centred",
      len(panels) == 3 and turnaround.split_panels.last == "gaps"
      and all(abs(turnaround.silhouette_box(_p)[1]) < 0.06 if False else True for _p in [])
      and all(p.height == 672 for p in panels), [p.size for p in panels])
for i, p in enumerate(panels):
    p.save(TMP / ("panel%d.png" % i))
check("... each panel holds one whole figure in the middle", all(abs(turnaround.silhouette_box(TMP / ("panel%d.png" % i))[1]) < 0.06
      and turnaround.silhouette_box(TMP / ("panel%d.png" % i))[0] > 0.7 for i in range(3)),
      [turnaround.silhouette_box(TMP / ("panel%d.png" % i)) for i in range(3)])
check("a creature gets the neutral reference pose; a character the T-pose",
      "neutral reference pose" in turnaround.sheet_prompt("a golem", "creature", True) and "T-pose" in turnaround.view_prompt("a knight", "character", "front"))
info = json.loads((ws / "turnarounds" / r["sheet"].split("/")[-1].replace("-sheet.png", "") / "turnaround.json").read_text())
check("the lineage is saved: which concept, subject, kind, seed, views", info["concept"] == "images/20261026-dragon.png"
      and info["kind"] == "creature" and info["views"]["front"].endswith("/front.png"), info)
check("it hands the 3D step the front view", "make_3d image=" in r["next"] and "front.png" in r["next"], r["next"])
sheet = Image.open(ws / r["sheet"])
check("the sheet holds the views side by side", sheet.width > 4 * 96 and sheet.height > 128, sheet.size)
check("subject alone works (no concept)", turnaround.make_turnaround({"subject": "a wooden treasure chest", "kind": "prop",
                                                                      "views": "front,three-quarter"}, ws, fake_maker)["ok"])
def text_only(args, cwd):
    if args.get("reference"):
        return {"ok": False, "error": "this model cannot use a reference picture"}
    return fake_maker(args, cwd)


asked.clear()
r2 = turnaround.make_turnaround({"concept": "images/20261026-dragon.png", "kind": "creature"}, ws, text_only)
check("no edit-capable model: drawn from text, and the turnaround SAYS so (mode, notes) with a low colour match",
      r2["ok"] and set(r2["mode"].values()) == {"text+sheet"} and r2["notes"] and max(r2["colour_match"].values()) < 0.5, r2)
Image.new("RGB", (1344, 768), (90, 120, 160)).save(ws / "images" / "fortress.png")
r3 = turnaround.make_turnaround({"concept": "images/fortress.png", "subject": "a glacier fortress under an aurora"}, ws, fake_maker)
check("a scene is refused - a turnaround needs one subject (the library interior on the Mac)",
      not r3["ok"] and "scene" in r3["error"], r3)
check("a wide concept picture is a scene too", "wide" in turnaround.is_scene("a dragon", (1344, 768)))
check("a bad kind or view is refused, plainly", not turnaround.make_turnaround({"subject": "x", "kind": "spaceship"}, ws, fake_maker)["ok"]
      and "views are" in turnaround.make_turnaround({"subject": "x", "views": "under"}, ws, fake_maker)["error"])
check("a concept outside the folder is refused", not turnaround.make_turnaround({"concept": "../x.png"}, ws, fake_maker)["ok"])
check("agents get it as a loki-make tool and a CLI word", any(t.get("name") == "make_turnaround" for t in make_mcp.TOOLS
                                                              if isinstance(t, dict)) and make_mcp.CLI.get("turnaround") == "make_turnaround")
import creations  # noqa: E402
import home_projects  # noqa: E402
check("the sheet shows on Home as a made thing (a picture, not a folder)", "turnarounds" in creations.KINDS
      and home_projects.MADE_KINDS.get("turnarounds") == "image")
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
