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
Image.new("RGB", (64, 36), (120, 40, 40)).save(ws / "images" / "20261026-dragon.png")
(ws / "images" / ".meta" / "20261026-dragon.png.json").write_text(json.dumps(
    {"prompt": "a red baby dragon with golden horns and a scaled belly. game concept art, cinematic"}), encoding="utf-8")
asked = []


def fake_maker(args, cwd):
    asked.append(args)
    out = Path(cwd) / args["folder"]
    out.mkdir(parents=True, exist_ok=True)
    f = out / ("pic%d.png" % len(asked))
    Image.new("RGB", (args["width"] // 8, args["height"] // 8), (200, 200, 200)).save(f)
    return {"ok": True, "files": [os.path.relpath(f, cwd)], "backend": "nvidia", "model": "flux.2-klein-4b"}


r = turnaround.make_turnaround({"concept": "images/20261026-dragon.png", "kind": "creature"}, ws, fake_maker,
                               clock=lambda: 1793030000.0)
check("it makes front, side, back and top, and one sheet", r.get("ok") and set(r["views"]) == {"front", "side", "back", "top"}
      and (ws / r["sheet"]).is_file() and all((ws / v).is_file() for v in r["views"].values()), r)
check("the design comes from the concept's own prompt (harmonious with the concept artist)",
      all("a red baby dragon with golden horns and a scaled belly" in a["prompt"] for a in asked), asked[:1])
check("every view on the same seed, flat orthographic, plain background, its own view words",
      len({a["seed"] for a in asked}) == 1 and all("orthographic" in a["prompt"] and "plain flat light grey" in a["prompt"]
                                                 for a in asked) and "BACK view" in asked[2]["prompt"], asked)
check("a creature gets the neutral reference pose; a character the T-pose",
      "neutral reference pose" in asked[0]["prompt"] and "T-pose" in turnaround.view_prompt("a knight", "character", "front"))
info = json.loads((ws / "turnarounds" / r["sheet"].split("/")[-1].replace("-sheet.png", "") / "turnaround.json").read_text())
check("the lineage is saved: which concept, subject, kind, seed, views", info["concept"] == "images/20261026-dragon.png"
      and info["kind"] == "creature" and info["views"]["front"].endswith("/front.png"), info)
check("it hands the 3D step the front view", "make_3d image=" in r["next"] and "front.png" in r["next"], r["next"])
sheet = Image.open(ws / r["sheet"])
check("the sheet holds the views side by side", sheet.width > 4 * 96 and sheet.height > 128, sheet.size)
check("subject alone works (no concept)", turnaround.make_turnaround({"subject": "a wooden treasure chest", "kind": "prop",
                                                                      "views": "front,three-quarter"}, ws, fake_maker)["ok"])
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
