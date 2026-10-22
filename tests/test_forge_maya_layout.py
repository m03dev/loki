"""Forge laid out like Maya 2027 (owner 2026-10-22: "almost 1:1 to maya ... place everything exactly like that").

docs/forge/maya2027_layout.json is Maya's own layout (read from a Maya install by tools/forge_maya/extract_maya.py);
tools/forge_maya/gen_layout.py turns it into app/ui/forge_maya_layout.js (what Forge's menus, hotbox and marking menus
are built from) and docs/FORGE_MAYA_PARITY.md. This checks, without a browser (a few seconds):
  * the generated files are up to date (gen_layout.py --check);
  * the reference holds names, order, positions and keys only (no scripts / annotations: no Autodesk code);
  * the menu bar and the Modeling set are Maya's, in Maya's order;
  * every menu keeps Maya's order (the Forge rows are a subsequence of Maya's rows) and Maya's section headings;
  * every marking-menu wedge sits where Maya puts it, with Maya's label;
  * each command shows once per menu, and every id is a real Forge command.

    python tests/test_forge_maya_layout.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "forge_maya"))
import gen_layout  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


out = subprocess.run([sys.executable, str(REPO / "tools" / "forge_maya" / "gen_layout.py"), "--check"],
                     capture_output=True, text=True, timeout=50)
check("app/ui/forge_maya_layout.js and docs/FORGE_MAYA_PARITY.md are up to date with the generator", out.returncode == 0, out.stdout + out.stderr)

lay = json.loads(gen_layout.LAYOUT.read_text(encoding="utf-8"))
allowed = {"label", "rtc", "c", "sub", "div", "opt", "rp", "check", "radio", "call", "error"}
bad = set()


def walk_keys(t):
    for it in t:
        bad.update(set(it) - allowed)
        walk_keys(it.get("sub", []))


for t in list(lay["menus"].values()) + list(lay["marking"].values()):
    walk_keys(t)
check("the Maya reference holds names / order / positions / keys only - no Autodesk code", not bad, bad)
check("the reference is Maya 2027's Modeling menu bar",
      lay["menubar"] == ["File", "Edit", "Create", "Select", "Modify", "Display", "Windows", "Mesh", "Edit Mesh", "Mesh Tools",
                         "Mesh Display", "Curves", "Surfaces", "Deform", "UV", "Generate"], lay["menubar"])
check("...and its 500+ default hotkeys", len(lay["hotkeys"]) > 400, len(lay["hotkeys"]))

js = gen_layout.OUT_JS.read_text(encoding="utf-8")
data = json.loads(js.split("const FORGE_MAYA = ", 1)[1].rstrip().rstrip(";"))
check("Forge's bar: Maya's main menus in Maya's order", data["bar"] == lay["menubar"][:7], data["bar"])
check("Forge's Modeling set: Maya's menus in Maya's order (those Forge has rows for)",
      data["sets"]["modeling"]["menus"] == [m for m in lay["menubar"][7:] if m in data["menus"]], data["sets"]["modeling"])
check("Animation / Rendering sets are there (Maya's F4 / F6) and Sculpting (Forge's own)",
      set(data["sets"]) == {"modeling", "animation", "rendering", "sculpting"} and data["sets"]["animation"]["menus"] == ["Key", "Playback"], data["sets"])

have = gen_layout.forge_ids()


def flat(entries, out=None):
    out = [] if out is None else out
    for e in entries:
        if isinstance(e, list) and len(e) == 2 and isinstance(e[1], list):
            flat(e[1], out)
        elif isinstance(e, list):
            out.append(e[0])
        elif isinstance(e, str) and e != "-" and not e.startswith("#"):
            out.append(e)
    return out


def maya_order(tree, out=None):
    out = [] if out is None else out
    for it in tree:
        if "sub" in it:
            maya_order(it["sub"], out)
        elif it.get("label"):
            f = gen_layout.fid(it, "")
            if f:
                out.append(f)
    return out


order_bad, dup_bad, dead = [], [], []
for name, items in data["menus"].items():
    ids = flat(items)
    dead += [i for i in ids if i not in have]
    if len(ids) != len(set(ids)):
        dup_bad.append(name)
    if name not in lay["menus"]:
        continue
    head = items[:items.index("#LOKI")] if "#LOKI" in items else items
    mine = flat(head)
    ref = [x for x in dict.fromkeys(maya_order(lay["menus"][name]))]
    pos = [ref.index(i) for i in mine if i in ref]
    if pos != sorted(pos):
        order_bad.append(name)
check("every menu keeps Maya's order", not order_bad, order_bad)
check("each command shows once per menu", not dup_bad, dup_bad)
check("every command id in the layout is a real Forge command", not dead, sorted(set(dead))[:10])
heads = [e for e in data["menus"]["Edit Mesh"] if isinstance(e, str) and e.startswith("#")]
check("Edit Mesh carries Maya's section headings (Components, Vertex, Edge, Face) and LOKI's at the end",
      heads == ["#Components", "#Vertex", "#Edge", "#Face", "#LOKI"], heads)

# marking menus: each wedge at Maya's place, with Maya's label
wrong = []
for key, mname in gen_layout.MARKING.items():
    mk = data["marking"][key]
    for it in lay["marking"][mname]:
        rp = it.get("rp")
        if not rp or "sub" in it:
            continue
        f = gen_layout.fid(it, mname)
        if f in have and (mk["ring"].get(rp) != f or mk["labels"].get(rp) != it["label"]):
            wrong.append((key, rp, it["label"], mk["ring"].get(rp)))
check("every Shift+right-click wedge Forge has sits at Maya's compass place with Maya's label", not wrong, wrong[:5])
face = data["marking"]["face"]
check("Shift+right-click on a face: N Merge Faces To Center, S Extrude Face, E Bevel Face, W Multi-Cut, SE Face Normals",
      face["ring"].get("N") == "mergeCenter" and face["ring"].get("S") == "extrude" and face["ring"].get("E") == "bevel"
      and face["ring"].get("W") == "multiCut" and isinstance(face["ring"].get("SE"), dict), face["ring"])
check("the hotbox centre zone: Perspective N, Side E, Front S, Top W (Maya's)",
      data["zones"]["center"]["ring"] == {"N": "persp", "E": "side", "S": "front", "W": "top"}, data["zones"]["center"]["ring"])
md = gen_layout.OUT_MD.read_text(encoding="utf-8")
check("the parity record says where Forge stands and lists every Maya row", "## The plan" in md and "## Every row" in md and "Maya rows" in md)

ui = (REPO / "app" / "ui")
idx = (ui / "index.html").read_text(encoding="utf-8")
check("index.html loads the layout before forge_pro.js", 0 < idx.find("/ui/forge_maya_layout.js") < idx.find("/ui/forge_pro.js"))
fp = (ui / "forge_pro.js").read_text(encoding="utf-8")
check("forge_pro.js builds its menus, sets, zones and Shift+right-click menus from FORGE_MAYA",
      "FORGE_MAYA.menus" in fp and "FORGE_MAYA.sets" in fp and "FORGE_MAYA.zones" in fp and "FORGE_MAYA.marking[" in fp)
check("the old hand-made Snap / Symmetry / Animation menus are gone from the bar (Snap and Symmetry live on the status line, as in Maya)",
      "Snap: [\"snapGrid\"" not in fp and "Symmetry: [[\"Object\"" not in fp and "forge: { label: \"Forge\"" not in fp)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
